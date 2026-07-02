import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.config.defaults import CONFIG
from src.config.models import AgentConfig, Provider
from src.llm.client import LLMClient

GATEWAY_URL = "http://gateway.internal/llm/v1"


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
    ):
        monkeypatch.delenv(key, raising=False)


def test_llm_client_uses_gateway_base_url_from_env(monkeypatch):
    _clear_provider_keys(monkeypatch)
    monkeypatch.setenv("BASE_LLM_GATEWAY_URL", GATEWAY_URL)
    monkeypatch.setenv("BASE_GATEWAY_TOKEN", "gw-token")

    client = LLMClient()
    try:
        assert client.base_url == GATEWAY_URL
    finally:
        client.close()


def test_llm_client_sends_gateway_token_as_bearer(monkeypatch):
    _clear_provider_keys(monkeypatch)
    monkeypatch.delenv("BASE_GATEWAY_TOKEN", raising=False)

    client = LLMClient(base_url=GATEWAY_URL, token="gw-token")
    try:
        assert client._client is not None
        assert client._client.headers["Authorization"] == "Bearer gw-token"
        assert str(client._client.base_url).rstrip("/") == GATEWAY_URL
    finally:
        client.close()


def test_llm_client_builds_without_a_provider_api_key(monkeypatch):
    _clear_provider_keys(monkeypatch)
    monkeypatch.delenv("BASE_GATEWAY_TOKEN", raising=False)

    # No provider API key anywhere; building only needs the gateway URL.
    client = LLMClient(base_url=GATEWAY_URL)
    try:
        assert client.base_url == GATEWAY_URL
    finally:
        client.close()


def test_llm_client_requires_gateway_url_when_not_mock(monkeypatch):
    _clear_provider_keys(monkeypatch)
    monkeypatch.delenv("BASE_LLM_GATEWAY_URL", raising=False)
    monkeypatch.delenv("BASEAGENT_MOCK_LLM", raising=False)

    with pytest.raises(ValueError, match="BASE_LLM_GATEWAY_URL"):
        LLMClient()


def test_llm_client_does_not_depend_on_a_specific_model(monkeypatch):
    _clear_provider_keys(monkeypatch)
    monkeypatch.setenv("BASE_LLM_GATEWAY_URL", GATEWAY_URL)
    monkeypatch.setenv("BASE_GATEWAY_TOKEN", "gw-token")

    client = LLMClient()
    try:
        # A neutral placeholder only; the gateway overwrites the model.
        assert client.model == "gateway-default"
    finally:
        client.close()


def test_chat_posts_to_chat_completions_with_placeholder_model(monkeypatch):
    _clear_provider_keys(monkeypatch)
    monkeypatch.setenv("BASE_LLM_GATEWAY_URL", GATEWAY_URL)
    monkeypatch.setenv("BASE_GATEWAY_TOKEN", "gw-token")

    client = LLMClient()
    captured: dict = {}

    class FakeResponse:
        status_code = 200

        @staticmethod
        def json():
            return {
                "choices": [{"message": {"content": "hi"}, "finish_reason": "stop"}],
                "model": "server-injected-model",
                "usage": {},
            }

    def fake_post(url, json):
        captured["url"] = url
        captured["json"] = json
        return FakeResponse()

    client._client.post = fake_post  # type: ignore[method-assign]
    try:
        response = client.chat([{"role": "user", "content": "hello"}])
    finally:
        client.close()

    assert captured["url"] == "/chat/completions"
    assert captured["json"]["model"] == "gateway-default"
    assert response.text == "hi"


def test_mock_mode_works_without_token(monkeypatch):
    _clear_provider_keys(monkeypatch)
    for key in ("BASE_LLM_GATEWAY_URL", "BASE_GATEWAY_TOKEN", "BASEAGENT_MOCK_LLM"):
        monkeypatch.delenv(key, raising=False)

    client = LLMClient(mock=True)
    try:
        assert client._client is None
        response = client.chat([{"role": "user", "content": "hi"}])
        assert response.text
    finally:
        client.close()


def test_config_defaults_have_no_deepseek():
    assert CONFIG["provider"] == "gateway"
    assert CONFIG["model"] == "gateway-default"
    assert "deepseek" not in str(CONFIG["model"]).lower()
    assert "deepseek" not in str(CONFIG["provider"]).lower()


def test_agent_config_has_no_deepseek_provider():
    assert not hasattr(Provider, "DEEPSEEK")
    assert list(Provider) == [Provider.GATEWAY]

    config = AgentConfig()
    assert config.provider is Provider.GATEWAY
    assert config.model == "gateway-default"


def test_agent_config_resolves_gateway_env(monkeypatch):
    _clear_provider_keys(monkeypatch)
    monkeypatch.setenv("BASE_LLM_GATEWAY_URL", GATEWAY_URL)
    monkeypatch.setenv("BASE_GATEWAY_TOKEN", "gw-token")

    config = AgentConfig()
    assert config.get_base_url() == GATEWAY_URL
    assert config.get_token() == "gw-token"
