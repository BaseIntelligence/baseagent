"""API module for SuperAgent - re-exports LiteLLM client + retry helpers."""

from src.llm.client import FunctionCall, LLMClient, LLMResponse

try:
    from src.api.retry import RetryHandler, with_retry
except Exception:  # pragma: no cover - retry helpers are optional
    RetryHandler = None  # type: ignore[misc, assignment]
    with_retry = None  # type: ignore[misc, assignment]

__all__ = ["LLMClient", "LLMResponse", "FunctionCall", "RetryHandler", "with_retry"]
