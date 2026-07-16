"""TDD: LiteLLM multi-provider config resolution (openrouter | openai | custom)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.config.defaults import CONFIG
from src.config.models import AgentConfig, Provider
from src.llm.client import (
    LLMClient,
    LLMProviderConfig,
    resolve_provider_config,
)


def _clear_llm_env(monkeypatch):
    for key in (
        "BASE_LLM_GATEWAY_URL",
        "BASE_GATEWAY_TOKEN",
        "GATEWAY_TOKEN",
        "CENTRAL_GATEWAY_TOKEN",
        "CHALLENGE_LLM_GATEWAY_TOKEN",
        "CHALLENGE_LLM_GATEWAY_BASE_URL",
        "CHALLENGE_LLM_GATEWAY_TOKEN_FILE",
        "CHALLENGE_AGENT_GATEWAY_TOKEN",
        "BASEAGENT_MOCK_LLM",
        "BASEAGENT_CHALLENGE_MODE",
        "BASEAGENT_LLM_PROVIDER",
        "LLM_PROVIDER",
        "LLM_MODEL",
        "BASEAGENT_MODEL",
        "OPENROUTER_API_KEY",
        "OPENROUTER_BASE_URL",
        "OPENAI_API_KEY",
        "OPENAI_BASE_URL",
        "BASEAGENT_LLM_BASE_URL",
        "BASEAGENT_LLM_API_KEY",
        "LLM_API_KEY",
        "DEEPSEEK_API_KEY",
        "ANTHROPIC_API_KEY",
        "CHUTES_API_KEY",
    ):
        monkeypatch.delenv(key, raising=False)


def test_default_openrouter_from_env(monkeypatch):
    _clear_llm_env(monkeypatch)
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-test-key")
    monkeypatch.setenv("LLM_MODEL", "moonshotai/kimi-k2")

    cfg = resolve_provider_config()
    assert cfg.provider == "openrouter"
    assert cfg.model == "moonshotai/kimi-k2"
    assert cfg.api_key == "or-test-key"
    assert "openrouter.ai" in (cfg.base_url or "")
    assert cfg.base_url.rstrip("/").endswith("/api/v1")


def test_openai_provider_and_key(monkeypatch):
    _clear_llm_env(monkeypatch)
    monkeypatch.setenv("BASEAGENT_LLM_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("LLM_MODEL", "gpt-4o-mini")

    cfg = resolve_provider_config()
    assert cfg.provider == "openai"
    assert cfg.model == "gpt-4o-mini"
    assert cfg.api_key == "sk-test"


def test_custom_requires_base_url_and_key(monkeypatch):
    _clear_llm_env(monkeypatch)
    monkeypatch.setenv("BASEAGENT_LLM_PROVIDER", "custom")
    monkeypatch.setenv("LLM_MODEL", "my-model")

    with pytest.raises(ValueError, match="(?i)base.?url|api.?key|custom"):
        resolve_provider_config()

    monkeypatch.setenv("BASEAGENT_LLM_BASE_URL", "https://example.com/v1")
    with pytest.raises(ValueError, match="(?i)api.?key|custom"):
        resolve_provider_config()

    monkeypatch.setenv("BASEAGENT_LLM_API_KEY", "custom-key")
    cfg = resolve_provider_config()
    assert cfg.provider == "custom"
    assert cfg.base_url == "https://example.com/v1"
    assert cfg.api_key == "custom-key"
    assert cfg.model == "my-model"


def test_rejects_gateway_default_model_placeholder(monkeypatch):
    _clear_llm_env(monkeypatch)
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-test-key")
    monkeypatch.setenv("LLM_MODEL", "gateway-default")

    with pytest.raises(ValueError, match="(?i)model|gateway-default"):
        resolve_provider_config(model="gateway-default")


def test_constructor_kwargs_override_env(monkeypatch):
    _clear_llm_env(monkeypatch)
    monkeypatch.setenv("BASEAGENT_LLM_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "env-openai")
    monkeypatch.setenv("LLM_MODEL", "env-model")
    monkeypatch.setenv("OPENROUTER_API_KEY", "env-or")

    cfg = resolve_provider_config(
        provider="openrouter",
        model="kwarg-model",
        api_key="kwarg-key",
        base_url="https://openrouter.ai/api/v1",
    )
    assert cfg.provider == "openrouter"
    assert cfg.model == "kwarg-model"
    assert cfg.api_key == "kwarg-key"


def test_mock_mode_skips_keys(monkeypatch):
    _clear_llm_env(monkeypatch)
    client = LLMClient(mock=True)
    try:
        assert client._mock is True
        response = client.chat([{"role": "user", "content": "hi"}])
        assert response.text
        assert "mock" in response.text.lower() or response.text
    finally:
        client.close()


def test_openrouter_client_constructs_without_gateway_env(monkeypatch):
    _clear_llm_env(monkeypatch)
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-test-key")
    monkeypatch.setenv("LLM_MODEL", "openai/gpt-4o-mini")

    client = LLMClient()
    try:
        assert client.provider == "openrouter"
        assert client.api_key == "or-test-key"
        assert client.base_url is not None
        assert "openrouter.ai" in client.base_url
        assert "gateway" not in (client.model or "").lower()
    finally:
        client.close()


def test_config_defaults_are_openrouter_not_gateway():
    assert CONFIG["provider"] == "openrouter"
    assert CONFIG["model"] != "gateway-default"
    assert "gateway" not in str(CONFIG["provider"]).lower()


def test_agent_config_provider_enum_multi():
    assert not hasattr(Provider, "GATEWAY")
    names = {p.value for p in Provider}
    assert names == {"openrouter", "openai", "custom"}

    config = AgentConfig()
    assert config.provider is Provider.OPENROUTER
    assert config.model != "gateway-default"


def test_agent_config_resolves_openrouter_env(monkeypatch):
    _clear_llm_env(monkeypatch)
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-cfg")
    monkeypatch.setenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
    monkeypatch.setenv("LLM_MODEL", "openai/gpt-4o-mini")

    config = AgentConfig()
    assert config.get_api_key() == "or-cfg"
    assert "openrouter.ai" in (config.get_base_url() or "")
    assert config.get_model() == "openai/gpt-4o-mini"


def test_resolve_returns_dataclass_fields(monkeypatch):
    _clear_llm_env(monkeypatch)
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    monkeypatch.setenv("LLM_MODEL", "m")

    cfg = resolve_provider_config()
    assert isinstance(cfg, LLMProviderConfig)
    assert set(cfg.__dataclass_fields__) >= {"provider", "model", "base_url", "api_key"}
