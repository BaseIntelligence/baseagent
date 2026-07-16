"""LLM Client via LiteLLM multi-provider (openrouter default; openai; custom).

Challenge / score mode refuses Base LLM gateway residue fail-closed.
Never requires BASE_LLM_GATEWAY_URL for production construction with OpenRouter.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence

import litellm

# Neutral markers only used by the refuse path (never as a live call target).
_GATEWAY_ENV_NAMES: tuple[str, ...] = (
    "BASE_LLM_GATEWAY_URL",
    "BASE_GATEWAY_TOKEN",
    "GATEWAY_TOKEN",
    "CENTRAL_GATEWAY_TOKEN",
    "CHALLENGE_LLM_GATEWAY_TOKEN",
    "CHALLENGE_LLM_GATEWAY_BASE_URL",
    "CHALLENGE_LLM_GATEWAY_TOKEN_FILE",
    "CHALLENGE_AGENT_GATEWAY_TOKEN",
)

_GATEWAY_URL_MARKERS: tuple[str, ...] = (
    "/llm/v1",
    "BASE_LLM_GATEWAY",
    "X-Gateway-Token",
)

_DEFAULT_OPENROUTER_BASE = "https://openrouter.ai/api/v1"
_DEFAULT_OPENROUTER_MODEL = "openai/gpt-4o-mini"
_PLACEHOLDER_MODELS = frozenset({"", "gateway-default", "gateway_default"})


def _truthy(value: Optional[str]) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "on"} if value else False


def _env(*names: str, default: Optional[str] = None) -> Optional[str]:
    for name in names:
        value = os.environ.get(name)
        if value is not None and str(value).strip() != "":
            return str(value)
    return default


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


class GatewayForbiddenError(ValueError):
    """Base LLM gateway configuration is present and must not be used."""

    def __init__(self, message: str = "base_gateway_forbidden: Base LLM gateway is not allowed"):
        super().__init__(message)


@dataclass(frozen=True)
class LLMProviderConfig:
    """Resolved multi-provider settings for LiteLLM."""

    provider: str
    model: str
    base_url: Optional[str]
    api_key: Optional[str]
    mock: bool = False

    def litellm_model(self) -> str:
        """Map provider + model id into a LiteLLM model string."""
        model = self.model
        if self.provider == "openrouter":
            if model.startswith("openrouter/"):
                return model
            return f"openrouter/{model}"
        if self.provider == "openai":
            if model.startswith("openai/"):
                return model
            return f"openai/{model}"
        # custom: pass through; api_base drives the endpoint
        return model


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


def detect_gateway_residue(
    env: Optional[Mapping[str, str]] = None,
    *,
    base_url: Optional[str] = None,
    extra_values: Optional[Sequence[Optional[str]]] = None,
) -> list[str]:
    """Return human-readable reasons if Base gateway residue is present."""
    source = env if env is not None else os.environ
    hits: list[str] = []
    for name in _GATEWAY_ENV_NAMES:
        value = source.get(name)
        if value is not None and str(value).strip() != "":
            hits.append(f"env:{name}")
    candidates: list[str] = []
    if base_url:
        candidates.append(str(base_url))
    if extra_values:
        candidates.extend(str(v) for v in extra_values if v)
    for value in candidates:
        lowered = value.lower()
        for marker in _GATEWAY_URL_MARKERS:
            if marker.lower() in lowered:
                hits.append(f"marker:{marker}")
                break
    return hits


def refuse_if_gateway_residue(
    env: Optional[Mapping[str, str]] = None,
    *,
    base_url: Optional[str] = None,
    extra_values: Optional[Sequence[Optional[str]]] = None,
) -> None:
    """Fail closed when Base LLM gateway env or URL markers are present."""
    hits = detect_gateway_residue(env, base_url=base_url, extra_values=extra_values)
    if hits:
        raise GatewayForbiddenError(
            "base_gateway_forbidden: Base LLM gateway residue is not allowed "
            f"({', '.join(hits)}). Use LiteLLM provider openrouter|openai|custom."
        )


def _normalize_provider(raw: Optional[str], *, default: str = "openrouter") -> str:
    value = (raw or default).strip().lower()
    aliases = {
        "or": "openrouter",
        "open-router": "openrouter",
        "oai": "openai",
        "openai-compatible": "custom",
        "openai_compatible": "custom",
    }
    value = aliases.get(value, value)
    if value in {"gateway", "base_gateway", "base-gateway"}:
        raise GatewayForbiddenError(
            "base_gateway_forbidden: provider 'gateway' is not allowed; "
            "use openrouter|openai|custom"
        )
    if value not in {"openrouter", "openai", "custom"}:
        raise ValueError(
            f"Unknown LLM provider {value!r}. Expected openrouter|openai|custom."
        )
    return value


def _resolve_model(
    model: Optional[str],
    *,
    provider: str,
    mock: bool,
) -> str:
    resolved = (
        model
        or _env("LLM_MODEL", "BASEAGENT_MODEL")
        or (_DEFAULT_OPENROUTER_MODEL if provider == "openrouter" else None)
    )
    if mock:
        return resolved or "mock"
    if resolved is None or resolved.strip().lower() in _PLACEHOLDER_MODELS:
        raise ValueError(
            "A concrete model id is required (set LLM_MODEL / BASEAGENT_MODEL). "
            "Placeholder 'gateway-default' is rejected."
        )
    return resolved.strip()


def resolve_provider_config(
    *,
    provider: Optional[str] = None,
    model: Optional[str] = None,
    base_url: Optional[str] = None,
    api_key: Optional[str] = None,
    mock: Optional[bool] = None,
    env: Optional[Mapping[str, str]] = None,
    challenge_mode: Optional[bool] = None,
) -> LLMProviderConfig:
    """Resolve openrouter|openai|custom provider settings from kwargs + env.

    Challenge mode (default on) refuses any Base gateway residue before returning.
    """
    source = env if env is not None else os.environ
    mock_mode = (
        mock
        if mock is not None
        else _truthy(source.get("BASEAGENT_MOCK_LLM") if hasattr(source, "get") else None)
    )
    # os.environ always supports get; Mapping may not carry False for missing.
    if mock is None and not isinstance(source, type(os.environ)) and not mock_mode:
        mock_mode = _truthy(os.environ.get("BASEAGENT_MOCK_LLM"))

    if challenge_mode is None:
        # Default ON for challenge/score path; set BASEAGENT_CHALLENGE_MODE=0 only for lab.
        challenge_mode = True
        flag = source.get("BASEAGENT_CHALLENGE_MODE") if hasattr(source, "get") else None
        if flag is None:
            flag = os.environ.get("BASEAGENT_CHALLENGE_MODE")
        if flag is not None and not _truthy(flag) and str(flag).strip() != "":
            # Explicit 0/false/off disables; empty falls back to default True.
            if str(flag).strip().lower() in {"0", "false", "no", "off"}:
                challenge_mode = False

    # Always refuse gateway residue when challenge mode is on, including mock.
    # Mock still cannot "legitimize" a gateway of record in scored packaging.
    if challenge_mode:
        refuse_if_gateway_residue(source, base_url=base_url)

    if mock_mode:
        return LLMProviderConfig(
            provider="openrouter",
            model=_resolve_model(model, provider="openrouter", mock=True),
            base_url=None,
            api_key=None,
            mock=True,
        )

    # Constructor kwargs outrank env for provider selection.
    resolved_provider = _normalize_provider(
        provider
        or (source.get("BASEAGENT_LLM_PROVIDER") if hasattr(source, "get") else None)
        or (source.get("LLM_PROVIDER") if hasattr(source, "get") else None)
        or os.environ.get("BASEAGENT_LLM_PROVIDER")
        or os.environ.get("LLM_PROVIDER")
        or "openrouter"
    )

    resolved_model = _resolve_model(model, provider=resolved_provider, mock=False)

    if resolved_provider == "openrouter":
        resolved_key = (
            api_key
            or (source.get("OPENROUTER_API_KEY") if hasattr(source, "get") else None)
            or os.environ.get("OPENROUTER_API_KEY")
        )
        resolved_base = (
            base_url
            or (source.get("OPENROUTER_BASE_URL") if hasattr(source, "get") else None)
            or os.environ.get("OPENROUTER_BASE_URL")
            or _DEFAULT_OPENROUTER_BASE
        )
        if not resolved_key:
            raise ValueError(
                "OPENROUTER_API_KEY is required for provider=openrouter "
                "(or pass api_key=...). Mock with BASEAGENT_MOCK_LLM=1 for offline."
            )
    elif resolved_provider == "openai":
        resolved_key = (
            api_key
            or (source.get("OPENAI_API_KEY") if hasattr(source, "get") else None)
            or os.environ.get("OPENAI_API_KEY")
        )
        resolved_base = (
            base_url
            or (source.get("OPENAI_BASE_URL") if hasattr(source, "get") else None)
            or os.environ.get("OPENAI_BASE_URL")
        )
        if not resolved_key:
            raise ValueError(
                "OPENAI_API_KEY is required for provider=openai (or pass api_key=...)."
            )
    else:  # custom
        resolved_key = (
            api_key
            or (source.get("BASEAGENT_LLM_API_KEY") if hasattr(source, "get") else None)
            or (source.get("LLM_API_KEY") if hasattr(source, "get") else None)
            or os.environ.get("BASEAGENT_LLM_API_KEY")
            or os.environ.get("LLM_API_KEY")
        )
        resolved_base = (
            base_url
            or (source.get("BASEAGENT_LLM_BASE_URL") if hasattr(source, "get") else None)
            or os.environ.get("BASEAGENT_LLM_BASE_URL")
        )
        missing = []
        if not resolved_base:
            missing.append("base_url (BASEAGENT_LLM_BASE_URL)")
        if not resolved_key:
            missing.append("api_key (BASEAGENT_LLM_API_KEY / LLM_API_KEY)")
        if missing:
            raise ValueError(
                "custom provider requires " + " and ".join(missing)
            )

    # Defend against gateway markers in the resolved base URL as well.
    if challenge_mode:
        refuse_if_gateway_residue(source, base_url=resolved_base)

    return LLMProviderConfig(
        provider=resolved_provider,
        model=resolved_model,
        base_url=resolved_base,
        api_key=resolved_key,
        mock=False,
    )


class LLMClient:
    """LiteLLM multi-provider client for openrouter | openai | custom.

    Production construction for OpenRouter only needs ``OPENROUTER_API_KEY``
    (+ model). Base gateway env/URL markers raise ``GatewayForbiddenError``
    in challenge mode (default).
    """

    DEFAULT_MODEL = _DEFAULT_OPENROUTER_MODEL
    DEFAULT_PROVIDER = "openrouter"
    OPENROUTER_BASE_URL = _DEFAULT_OPENROUTER_BASE

    def __init__(
        self,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: int = 16384,
        cost_limit: Optional[float] = None,
        base_url: Optional[str] = None,
        token: Optional[str] = None,
        api_key: Optional[str] = None,
        provider: Optional[str] = None,
        timeout: float = 120.0,
        mock: Optional[bool] = None,
        challenge_mode: Optional[bool] = None,
    ):
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.cost_limit = cost_limit or float(os.environ.get("LLM_COST_LIMIT", "10.0"))
        self.timeout = timeout

        self._total_cost = 0.0
        self._total_tokens = 0
        self._request_count = 0
        self._input_tokens = 0
        self._output_tokens = 0
        self._cached_tokens = 0

        # Prefer explicit api_key; never treat BASE gateway tokens as provider keys.
        # ``token`` is historical gateway auth and must never become an OpenRouter key.
        if token and not api_key and not mock:
            refuse_if_gateway_residue(
                base_url=base_url,
                extra_values=[token, "BASE_GATEWAY_TOKEN"],
            )
            # Even without URL markers, a bare token kwarg is not a supported path.
            raise GatewayForbiddenError(
                "base_gateway_forbidden: gateway token kwarg is not allowed; "
                "pass api_key for openrouter|openai|custom"
            )

        cfg = resolve_provider_config(
            provider=provider,
            model=model,
            base_url=base_url,
            api_key=api_key,
            mock=mock,
            challenge_mode=challenge_mode,
        )

        self._config = cfg
        self.provider = cfg.provider
        self.model = cfg.model
        self.base_url = cfg.base_url
        self.api_key = cfg.api_key
        self._mock = cfg.mock
        self._client = None  # no httpx client; litellm owns transport

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

    def _completion_kwargs(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]],
        max_tokens: Optional[int],
        extra_body: Optional[Dict[str, Any]],
        model: Optional[str],
    ) -> Dict[str, Any]:
        litellm_model = (
            self._config.litellm_model()
            if model is None
            else LLMProviderConfig(
                provider=self.provider,
                model=model,
                base_url=self.base_url,
                api_key=self.api_key,
            ).litellm_model()
        )
        kwargs: Dict[str, Any] = {
            "model": litellm_model,
            "messages": self._prepare_messages(messages),
            "max_tokens": max_tokens or self.max_tokens,
            "timeout": self.timeout,
        }
        if self.api_key:
            kwargs["api_key"] = self.api_key
        if self.base_url:
            kwargs["api_base"] = self.base_url
        if self._supports_temperature(litellm_model) and self.temperature is not None:
            kwargs["temperature"] = self.temperature
        if tools:
            kwargs["tools"] = self._build_tools(tools)
            kwargs["tool_choice"] = "auto"
        if extra_body:
            kwargs.update(extra_body)
        return kwargs

    def chat(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        max_tokens: Optional[int] = None,
        extra_body: Optional[Dict[str, Any]] = None,
        model: Optional[str] = None,
    ) -> LLMResponse:
        """Send a chat request via LiteLLM (OpenAI-compatible surface)."""
        if self._mock:
            return self._mock_chat()

        if self._total_cost >= self.cost_limit:
            raise CostLimitExceeded(
                f"Cost limit exceeded: ${self._total_cost:.4f} >= ${self.cost_limit:.4f}",
                used=self._total_cost,
                limit=self.cost_limit,
            )

        kwargs = self._completion_kwargs(messages, tools, max_tokens, extra_body, model)

        try:
            data = litellm.completion(**kwargs)
            self._request_count += 1
        except Exception as exc:  # map LiteLLM / httpx / network failures
            raise self._map_exception(exc) from exc

        return self._parse_response(data)

    def _map_exception(self, exc: Exception) -> LLMError:
        name = type(exc).__name__.lower()
        message = str(exc)
        lower = message.lower()
        if "timeout" in name or "timeout" in lower:
            return LLMError(f"Request timed out: {exc}", code="timeout")
        if "auth" in name or "unauthorized" in lower or "401" in lower:
            return LLMError(message, code="authentication_error")
        if "rate" in name or "429" in lower:
            return LLMError(message, code="rate_limit")
        if "connect" in name or "connection" in lower:
            return LLMError(f"Connection error: {exc}", code="connection_error")
        if any(x in lower for x in ("500", "502", "503", "504", "server")):
            return LLMError(message, code="server_error")
        return LLMError(message, code="api_error")

    def _parse_response(self, data: Any) -> LLMResponse:
        """Adapt LiteLLM / OpenAI-shaped response into LLMResponse."""
        raw: Optional[Dict[str, Any]]
        if hasattr(data, "model_dump"):
            try:
                raw = data.model_dump()
            except Exception:
                raw = None
        elif isinstance(data, dict):
            raw = data
        else:
            raw = None

        result = LLMResponse(raw=raw)

        usage = _attr_or_key(data, "usage")
        if usage:
            input_tokens = _attr_or_key(usage, "prompt_tokens") or 0
            output_tokens = _attr_or_key(usage, "completion_tokens") or 0
            cached_tokens = 0
            prompt_details = _attr_or_key(usage, "prompt_tokens_details")
            if prompt_details:
                cached_tokens = _attr_or_key(prompt_details, "cached_tokens") or 0

            input_tokens = int(input_tokens or 0)
            output_tokens = int(output_tokens or 0)
            cached_tokens = int(cached_tokens or 0)

            self._input_tokens += input_tokens
            self._output_tokens += output_tokens
            self._cached_tokens += cached_tokens
            self._total_tokens += input_tokens + output_tokens

            result.tokens = {
                "input": input_tokens,
                "output": output_tokens,
                "cached": cached_tokens,
            }
            cost = (input_tokens * 3.0 / 1_000_000) + (output_tokens * 15.0 / 1_000_000)
            self._total_cost += cost

        result.model = _attr_or_key(data, "model") or self.model

        choices = _attr_or_key(data, "choices") or []
        if choices:
            choice = choices[0]
            message = _attr_or_key(choice, "message") or {}
            result.finish_reason = (_attr_or_key(choice, "finish_reason") or "") or ""
            result.text = (_attr_or_key(message, "content") or "") or ""

            tool_calls = _attr_or_key(message, "tool_calls") or []
            for call in tool_calls:
                func = _attr_or_key(call, "function") or {}
                args_str = _attr_or_key(func, "arguments") or "{}"
                try:
                    args = json.loads(args_str) if isinstance(args_str, str) else args_str
                except json.JSONDecodeError:
                    args = {"raw": args_str}
                result.function_calls.append(
                    FunctionCall(
                        id=(_attr_or_key(call, "id") or "") or "",
                        name=(_attr_or_key(func, "name") or "") or "",
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
            "provider": self.provider,
        }

    def close(self):
        """No-op for LiteLLM (kept for call-site compatibility)."""
        self._client = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False


def _attr_or_key(obj: Any, name: str) -> Any:
    if obj is None:
        return None
    if isinstance(obj, dict):
        return obj.get(name)
    return getattr(obj, name, None)


# Re-export time for tests that patch sleep historically (unused in LiteLLM path).
__all__ = [
    "CostLimitExceeded",
    "FunctionCall",
    "GatewayForbiddenError",
    "LLMClient",
    "LLMError",
    "LLMProviderConfig",
    "LLMResponse",
    "detect_gateway_residue",
    "refuse_if_gateway_residue",
    "resolve_provider_config",
    "_truthy",
]
