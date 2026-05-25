import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.config.defaults import CONFIG
from src.config.models import AgentConfig, Provider
from src.llm.client import LLMClient


def test_llm_client_uses_default_deepseek_base_url(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "deepseek-key")
    monkeypatch.delenv("DEEPSEEK_BASE_URL", raising=False)

    client = LLMClient(model="deepseek-v4-pro")

    try:
        assert client.base_url == "https://api.deepseek.com"
    finally:
        client.close()


def test_llm_client_requires_deepseek_api_key(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)

    with pytest.raises(ValueError, match="DEEPSEEK_API_KEY"):
        LLMClient(model="deepseek-v4-pro")


def test_llm_client_accepts_explicit_api_key_without_env(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)

    client = LLMClient(model="deepseek-v4-pro", api_key="explicit-key")

    try:
        assert client.base_url == "https://api.deepseek.com"
    finally:
        client.close()


def test_openrouter_api_key_is_ignored(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.setenv("OPENROUTER_API_KEY", "openrouter-key")
    monkeypatch.setenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")

    with pytest.raises(ValueError, match="DEEPSEEK_API_KEY"):
        LLMClient(model="deepseek-v4-pro")


def test_openrouter_base_url_is_not_used_with_explicit_key(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_BASE_URL", raising=False)
    monkeypatch.setenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")

    client = LLMClient(model="deepseek-v4-pro", api_key="explicit-key")

    try:
        assert client.base_url == "https://api.deepseek.com"
    finally:
        client.close()


def test_config_defaults_are_deepseek():
    assert CONFIG["provider"] == "deepseek"
    assert CONFIG["model"] == "deepseek-v4-pro"


def test_agent_config_is_deepseek_only(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "deepseek-key")
    monkeypatch.delenv("DEEPSEEK_BASE_URL", raising=False)
    monkeypatch.setenv("OPENROUTER_API_KEY", "openrouter-key")

    config = AgentConfig()

    assert list(Provider) == [Provider.DEEPSEEK]
    assert config.provider is Provider.DEEPSEEK
    assert config.model == "deepseek-v4-pro"
    assert config.get_base_url() == "https://api.deepseek.com"
    assert config.get_api_key() == "deepseek-key"


def test_agent_config_base_url_override_is_deepseek_only(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_BASE_URL", "https://deepseek.example")
    monkeypatch.setenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")

    assert AgentConfig().get_base_url() == "https://deepseek.example"
