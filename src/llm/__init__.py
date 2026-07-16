"""LLM module via LiteLLM multi-provider (openrouter default; openai; custom)."""

from .client import (
    CostLimitExceeded,
    FunctionCall,
    GatewayForbiddenError,
    LLMClient,
    LLMError,
    LLMProviderConfig,
    LLMResponse,
    resolve_provider_config,
)

__all__ = [
    "LLMClient",
    "LLMResponse",
    "LLMProviderConfig",
    "FunctionCall",
    "CostLimitExceeded",
    "LLMError",
    "GatewayForbiddenError",
    "resolve_provider_config",
]
