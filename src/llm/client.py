"""LLM Client using httpx for the platform LLM gateway (OpenAI-compatible)."""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import httpx


def _truthy(value: Optional[str]) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "on"} if value else False


class CostLimitExceeded(Exception):
    """Raised when cost limit is exceeded."""

    def __init__(self, message: str, used: float = 0, limit: float = 0):
        super().__init__(message)
        self.used = used
        self.limit = limit


class LLMError(Exception):
    """LLM API error."""

    def __init__(self, message: str, code: str = "unknown"):
        super().__init__(message)
        self.message = message
        self.code = code


@dataclass
class FunctionCall:
    """Represents a function/tool call from the LLM."""

    id: str
    name: str
    arguments: Dict[str, Any]

    @classmethod
    def from_openai(cls, call: Dict[str, Any]) -> "FunctionCall":
        """Parse from OpenAI tool_calls format."""
        func = call.get("function", {})
        args_str = func.get("arguments", "{}")

        try:
            args = json.loads(args_str)
        except json.JSONDecodeError:
            args = {"raw": args_str}

        return cls(
            id=call.get("id", ""),
            name=func.get("name", ""),
            arguments=args,
        )


@dataclass
class LLMResponse:
    """Response from the LLM."""

    text: str = ""
    function_calls: List[FunctionCall] = field(default_factory=list)
    tokens: Optional[Dict[str, int]] = None
    model: str = ""
    finish_reason: str = ""
    raw: Optional[Dict[str, Any]] = None

    def has_function_calls(self) -> bool:
        """Check if response contains function calls."""
        return len(self.function_calls) > 0


class LLMClient:
    """LLM Client using httpx for the platform LLM gateway (OpenAI-compatible).

    The client targets the master LLM gateway. It authenticates with the signed
    gateway token (``BASE_GATEWAY_TOKEN``) and never carries a provider API key:
    the gateway injects the provider and the model, so the client only sends a
    neutral placeholder model that the gateway overwrites.
    """

    # A neutral placeholder; the gateway overwrites the model per its config.
    DEFAULT_MODEL = "gateway-default"
    BASE_URL_ENV = "BASE_LLM_GATEWAY_URL"
    TOKEN_ENV = "BASE_GATEWAY_TOKEN"

    def __init__(
        self,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: int = 16384,
        cost_limit: Optional[float] = None,
        base_url: Optional[str] = None,
        token: Optional[str] = None,
        timeout: float = 120.0,
        mock: Optional[bool] = None,
    ):
        self.model = model or self.DEFAULT_MODEL
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.cost_limit = cost_limit or float(os.environ.get("LLM_COST_LIMIT", "10.0"))
        self.base_url = base_url or os.environ.get(self.BASE_URL_ENV)
        self.timeout = timeout

        self._total_cost = 0.0
        self._total_tokens = 0
        self._request_count = 0
        self._input_tokens = 0
        self._output_tokens = 0
        self._cached_tokens = 0

        self._token = token or os.environ.get(self.TOKEN_ENV)

        # Mock mode runs the agent end-to-end without any gateway URL or token
        # (pipeline checks). It needs neither credentials nor a network client.
        self._mock = _truthy(os.environ.get("BASEAGENT_MOCK_LLM")) if mock is None else mock
        if self._mock:
            self._client = None
            return

        if not self.base_url:
            raise ValueError(
                f"Gateway base URL required. Set {self.BASE_URL_ENV} environment "
                "variable or pass base_url parameter."
            )

        # The gateway token is the auth; a provider API key is never used. The
        # header is only attached when a token is present so mock/dev flows work.
        headers = {"Content-Type": "application/json"}
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        self._headers = headers

        self._client = self._build_client()

    def _build_client(self) -> httpx.Client:
        """Construct a freshly-configured gateway HTTP client.

        Isolated from ``__init__`` so a broken or closed client can be rebuilt
        transparently mid-run with the same base_url, headers, and timeout.
        """
        return httpx.Client(
            base_url=self.base_url,
            headers=self._headers,
            timeout=httpx.Timeout(self.timeout, connect=30.0),
        )

    def _discard_client(self) -> None:
        """Best-effort close the current client and drop the reference."""
        client = self._client
        self._client = None
        if client is not None:
            try:
                client.close()
            except Exception:
                pass

    def _ensure_client(self) -> None:
        """Rebuild the HTTP client if it is missing or has been closed.

        A single transient socket error can close the pooled client, after which
        httpx raises ``RuntimeError: Cannot send a request, as the client has
        been closed.`` for every later request. Rebuilding restores service.
        """
        if self._client is None or self._client.is_closed:
            self._discard_client()
            self._client = self._build_client()

    @staticmethod
    def _is_transport_failure(exc: Exception) -> bool:
        """Whether an exception means the HTTP client/connection is broken.

        Covers httpx transport/protocol errors, the "client has been closed"
        RuntimeError, and a stale-socket ``Bad file descriptor`` surfaced as an
        OSError or generic httpx error. Timeouts are intentionally excluded:
        they carry their own error code and do not indicate a dead client.
        """
        if isinstance(exc, httpx.TimeoutException):
            return False
        if isinstance(exc, (httpx.TransportError, httpx.RemoteProtocolError)):
            return True
        message = str(exc).lower()
        if isinstance(exc, RuntimeError):
            return "closed" in message
        if isinstance(exc, (OSError, httpx.HTTPError)):
            return "bad file descriptor" in message
        return False

    def _post_with_transport_retry(self, payload: Dict[str, Any]) -> httpx.Response:
        """POST to the gateway, transparently rebuilding a broken client.

        A transient connection/transport failure (including a closed client or a
        stale socket raising ``Bad file descriptor``) discards the client and
        retries with a freshly built one, up to a small bounded number of
        attempts, before surfacing a connection error. Timeouts and genuine HTTP
        status responses are left to the caller's existing handling.
        """
        max_transport_attempts = 3
        for transport_attempt in range(1, max_transport_attempts + 1):
            self._ensure_client()
            try:
                return self._client.post("/chat/completions", json=payload)
            except httpx.TimeoutException:
                # Handled separately as code="timeout"; not a broken client.
                raise
            except (
                httpx.TransportError,
                httpx.RemoteProtocolError,
                RuntimeError,
                OSError,
                httpx.HTTPError,
            ) as exc:
                if not self._is_transport_failure(exc):
                    raise
                self._discard_client()
                if transport_attempt >= max_transport_attempts:
                    raise LLMError(f"Connection error: {exc}", code="connection_error")
                time.sleep(transport_attempt)
        # Unreachable: the loop always returns or raises.
        raise LLMError("Connection error: retries exhausted", code="connection_error")

    def _mock_chat(self) -> LLMResponse:
        # Emits no function calls so the agent loop runs one self-verification
        # turn and completes; real environment commands still execute.
        self._request_count += 1
        self._input_tokens += 1
        self._output_tokens += 1
        self._total_tokens += 2
        return LLMResponse(
            text="[mock-llm] Task acknowledged; no further actions required.",
            tokens={"input": 1, "output": 1, "cached": 0},
            model=self.model,
            finish_reason="stop",
        )

    def _supports_temperature(self, model: str) -> bool:
        """Check if model supports temperature parameter."""
        model_lower = model.lower()
        # Some reasoning models don't support temperature.
        if any(x in model_lower for x in ["o1", "o3"]):
            return False
        return True

    def _build_tools(self, tools: Optional[List[Dict[str, Any]]]) -> Optional[List[Dict[str, Any]]]:
        """Build tools in OpenAI format."""
        if not tools:
            return None

        result = []
        for tool in tools:
            result.append(
                {
                    "type": "function",
                    "function": {
                        "name": tool["name"],
                        "description": tool.get("description", ""),
                        "parameters": tool.get("parameters", {"type": "object", "properties": {}}),
                    },
                }
            )
        return result

    def chat(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        max_tokens: Optional[int] = None,
        extra_body: Optional[Dict[str, Any]] = None,
        model: Optional[str] = None,
    ) -> LLMResponse:
        """Send a chat request to the LLM gateway (OpenAI-compatible)."""
        if self._mock:
            return self._mock_chat()

        # Check cost limit
        if self._total_cost >= self.cost_limit:
            raise CostLimitExceeded(
                f"Cost limit exceeded: ${self._total_cost:.4f} >= ${self.cost_limit:.4f}",
                used=self._total_cost,
                limit=self.cost_limit,
            )

        # Build request payload
        payload: Dict[str, Any] = {
            "model": model or self.model,
            "messages": self._prepare_messages(messages),
            "max_tokens": max_tokens or self.max_tokens,
        }

        if self._supports_temperature(payload["model"]) and self.temperature is not None:
            payload["temperature"] = self.temperature

        if tools:
            payload["tools"] = self._build_tools(tools)
            payload["tool_choice"] = "auto"

        # Add extra body params (like reasoning effort) - some may be ignored by API
        if extra_body:
            payload.update(extra_body)

        try:
            response = self._post_with_transport_retry(payload)
            self._request_count += 1

            # Handle HTTP errors
            if response.status_code != 200:
                error_body = response.text
                try:
                    error_json = response.json()
                    error_msg = error_json.get("error", {}).get("message", error_body)
                except (json.JSONDecodeError, KeyError):
                    error_msg = error_body

                # Map status codes to error codes
                if response.status_code == 401:
                    raise LLMError(error_msg, code="authentication_error")
                elif response.status_code == 429:
                    raise LLMError(error_msg, code="rate_limit")
                elif response.status_code >= 500:
                    raise LLMError(error_msg, code="server_error")
                else:
                    raise LLMError(f"HTTP {response.status_code}: {error_msg}", code="api_error")

            data = response.json()

        except httpx.TimeoutException as e:
            raise LLMError(f"Request timed out: {e}", code="timeout")
        except httpx.ConnectError as e:
            raise LLMError(f"Connection error: {e}", code="connection_error")
        except httpx.HTTPError as e:
            raise LLMError(f"HTTP error: {e}", code="api_error")

        # Parse response
        result = LLMResponse(raw=data)

        # Extract usage
        usage = data.get("usage", {})
        if usage:
            input_tokens = usage.get("prompt_tokens", 0) or 0
            output_tokens = usage.get("completion_tokens", 0) or 0
            cached_tokens = 0

            # Check for cached tokens (OpenAI format)
            prompt_details = usage.get("prompt_tokens_details", {})
            if prompt_details:
                cached_tokens = prompt_details.get("cached_tokens", 0) or 0

            self._input_tokens += input_tokens
            self._output_tokens += output_tokens
            self._cached_tokens += cached_tokens
            self._total_tokens += input_tokens + output_tokens

            result.tokens = {
                "input": input_tokens,
                "output": output_tokens,
                "cached": cached_tokens,
            }

            # Estimate cost (generic pricing, adjust per model if needed)
            # Using conservative estimates: $3/1M input, $15/1M output
            cost = (input_tokens * 3.0 / 1_000_000) + (output_tokens * 15.0 / 1_000_000)
            self._total_cost += cost

        # Extract model
        result.model = data.get("model", self.model)

        # Extract choices
        choices = data.get("choices", [])
        if choices:
            choice = choices[0]
            message = choice.get("message", {})

            result.finish_reason = choice.get("finish_reason", "") or ""
            result.text = message.get("content", "") or ""

            # Extract function calls
            tool_calls = message.get("tool_calls", [])
            if tool_calls:
                for call in tool_calls:
                    func = call.get("function", {})
                    args_str = func.get("arguments", "{}")

                    try:
                        args = json.loads(args_str) if isinstance(args_str, str) else args_str
                    except json.JSONDecodeError:
                        args = {"raw": args_str}

                    result.function_calls.append(
                        FunctionCall(
                            id=call.get("id", "") or "",
                            name=func.get("name", "") or "",
                            arguments=args if isinstance(args, dict) else {},
                        )
                    )

        return result

    def _prepare_messages(self, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Prepare messages for the API, cleaning up any incompatible fields."""
        prepared = []
        for msg in messages:
            new_msg = dict(msg)

            content = new_msg.get("content")
            if isinstance(content, list):
                # Convert multipart format, removing cache_control
                cleaned_parts = []
                for part in content:
                    if isinstance(part, dict):
                        cleaned_part = {k: v for k, v in part.items() if k != "cache_control"}
                        cleaned_parts.append(cleaned_part)
                    else:
                        cleaned_parts.append(part)
                new_msg["content"] = cleaned_parts

            prepared.append(new_msg)

        return prepared

    def get_stats(self) -> Dict[str, Any]:
        """Get usage statistics."""
        return {
            "total_tokens": self._total_tokens,
            "input_tokens": self._input_tokens,
            "output_tokens": self._output_tokens,
            "cached_tokens": self._cached_tokens,
            "total_cost": self._total_cost,
            "request_count": self._request_count,
        }

    def close(self):
        """Close the HTTP client."""
        if self._client is not None:
            self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False
