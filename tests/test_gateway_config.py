"""Legacy gateway config tests rewritten for LiteLLM + fail-closed refuse path."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.config.defaults import CONFIG
from src.config.models import AgentConfig, Provider
from src.llm.client import GatewayForbiddenError, LLMClient


def _clear_provider_keys(monkeypatch):
    for key in (
        "DEEPSEEK_API_KEY",
        "DEEPSEEK_BASE_URL",
        "OPENROUTER_API_KEY",
        "OPENROUTER_BASE_URL",
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "CHUTES_API_KEY",
        "LLM_MODEL",
        "BASEAGENT_MODEL",
        "BASEAGENT_LLM_PROVIDER",
        "BASEAGENT_LLM_API_KEY",
        "BASEAGENT_LLM_BASE_URL",
        "BASE_LLM_GATEWAY_URL",
        "BASE_GATEWAY_TOKEN",
        "BASEAGENT_MOCK_LLM",
    ):
        monkeypatch.delenv(key, raising=False)


def test_llm_client_uses_openrouter_from_env(monkeypatch):
    _clear_provider_keys(monkeypatch)
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-token")
    monkeypatch.setenv("LLM_MODEL", "openai/gpt-4o-mini")

    client = LLMClient()
    try:
        assert client.provider == "openrouter"
        assert "openrouter.ai" in (client.base_url or "")
        assert client.api_key == "or-token"
    finally:
        client.close()


def test_llm_client_refuses_gateway_url_env(monkeypatch):
    _clear_provider_keys(monkeypatch)
    monkeypatch.setenv("BASE_LLM_GATEWAY_URL", "http://gateway.internal/llm/v1")
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-token")
    monkeypatch.setenv("LLM_MODEL", "openai/gpt-4o-mini")

    with pytest.raises((GatewayForbiddenError, ValueError), match="(?i)gateway"):
        LLMClient()


def test_llm_client_constructs_without_base_gateway(monkeypatch):
    _clear_provider_keys(monkeypatch)
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-token")
    monkeypatch.setenv("LLM_MODEL", "openai/gpt-4o-mini")

    client = LLMClient()
    try:
        assert client.base_url is not None
        assert "llm/v1" not in client.base_url
    finally:
        client.close()


def test_llm_client_requires_provider_key_when_not_mock(monkeypatch):
    _clear_provider_keys(monkeypatch)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("BASEAGENT_MOCK_LLM", raising=False)

    with pytest.raises(ValueError, match="(?i)OPENROUTER_API_KEY|api.?key"):
        LLMClient()


def test_llm_client_uses_explicit_model(monkeypatch):
    _clear_provider_keys(monkeypatch)
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-token")
    monkeypatch.setenv("LLM_MODEL", "moonshotai/kimi-k2")

    client = LLMClient()
    try:
        assert client.model == "moonshotai/kimi-k2"
        assert client.model != "gateway-default"
    finally:
        client.close()


def test_chat_uses_litellm_completion(monkeypatch):
    _clear_provider_keys(monkeypatch)
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-token")
    monkeypatch.setenv("LLM_MODEL", "openai/gpt-4o-mini")

    captured: dict = {}

    class FakeResponse:
        model = "openai/gpt-4o-mini"
        usage = None
        choices = [
            type(
                "C",
                (),
                {
                    "finish_reason": "stop",
                    "message": type("M", (), {"content": "hi", "tool_calls": None})(),
                },
            )()
        ]

    def fake_completion(**kwargs):
        captured.update(kwargs)
        return FakeResponse()

    monkeypatch.setattr("src.llm.client.litellm.completion", fake_completion)

    client = LLMClient()
    try:
        response = client.chat([{"role": "user", "content": "hello"}])
    finally:
        client.close()

    assert response.text == "hi"
    assert "openrouter" in captured["model"] or captured["model"] == "openai/gpt-4o-mini"
    assert captured.get("api_key") == "or-token"


def test_mock_mode_works_without_token(monkeypatch):
    _clear_provider_keys(monkeypatch)
    for key in ("BASE_LLM_GATEWAY_URL", "BASE_GATEWAY_TOKEN", "BASEAGENT_MOCK_LLM"):
        monkeypatch.delenv(key, raising=False)

    client = LLMClient(mock=True)
    try:
        response = client.chat([{"role": "user", "content": "hi"}])
        assert response.text
    finally:
        client.close()


def test_config_defaults_have_no_deepseek():
    assert CONFIG["provider"] == "openrouter"
    assert CONFIG["model"] != "gateway-default"
    assert "deepseek" not in str(CONFIG["model"]).lower()
    assert "deepseek" not in str(CONFIG["provider"]).lower()


def test_agent_config_has_no_gateway_provider():
    assert not hasattr(Provider, "GATEWAY")
    assert not hasattr(Provider, "DEEPSEEK")
    assert set(Provider) == {Provider.OPENROUTER, Provider.OPENAI, Provider.CUSTOM}

    config = AgentConfig()
    assert config.provider is Provider.OPENROUTER
    assert config.model != "gateway-default"


def test_agent_config_resolves_openrouter_env(monkeypatch):
    _clear_provider_keys(monkeypatch)
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-token")
    monkeypatch.setenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
    monkeypatch.setenv("LLM_MODEL", "openai/gpt-4o-mini")

    config = AgentConfig()
    assert config.get_base_url() == "https://openrouter.ai/api/v1"
    assert config.get_api_key() == "or-token"
    assert config.get_model() == "openai/gpt-4o-mini"
