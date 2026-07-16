"""TDD: challenge mode fail-closed on Base LLM gateway residue."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.llm.client import GatewayForbiddenError, LLMClient, resolve_provider_config


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
    ):
        monkeypatch.delenv(key, raising=False)


BASE_GATEWAY_ENV_CASES = (
    "BASE_LLM_GATEWAY_URL",
    "BASE_GATEWAY_TOKEN",
    "GATEWAY_TOKEN",
    "CENTRAL_GATEWAY_TOKEN",
    "CHALLENGE_LLM_GATEWAY_TOKEN",
    "CHALLENGE_LLM_GATEWAY_BASE_URL",
    "CHALLENGE_AGENT_GATEWAY_TOKEN",
)


@pytest.mark.parametrize("env_name", BASE_GATEWAY_ENV_CASES)
def test_gateway_env_refused_even_with_openrouter(monkeypatch, env_name):
    _clear_llm_env(monkeypatch)
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-valid")
    monkeypatch.setenv("LLM_MODEL", "openai/gpt-4o-mini")
    if "URL" in env_name:
        monkeypatch.setenv(env_name, "http://master.internal/llm/v1")
    else:
        monkeypatch.setenv(env_name, "gw-token")

    with pytest.raises((GatewayForbiddenError, ValueError)) as excinfo:
        LLMClient()
    msg = str(excinfo.value).lower()
    assert "gateway" in msg or "base_gateway" in msg or "forbidden" in msg


def test_gateway_url_kwarg_with_llm_v1_marker_refused(monkeypatch):
    _clear_llm_env(monkeypatch)
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-valid")
    monkeypatch.setenv("LLM_MODEL", "openai/gpt-4o-mini")

    with pytest.raises((GatewayForbiddenError, ValueError)) as excinfo:
        LLMClient(base_url="https://chain.joinbase.ai/llm/v1")
    msg = str(excinfo.value).lower()
    assert "gateway" in msg or "llm/v1" in msg or "forbidden" in msg


def test_resolve_refuses_gateway_env(monkeypatch):
    _clear_llm_env(monkeypatch)
    monkeypatch.setenv("BASE_LLM_GATEWAY_URL", "http://x/llm/v1")
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-valid")
    monkeypatch.setenv("LLM_MODEL", "openai/gpt-4o-mini")

    with pytest.raises((GatewayForbiddenError, ValueError)):
        resolve_provider_config()


def test_gateway_token_alone_refuses(monkeypatch):
    _clear_llm_env(monkeypatch)
    monkeypatch.setenv("BASE_GATEWAY_TOKEN", "t")
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-valid")
    monkeypatch.setenv("LLM_MODEL", "openai/gpt-4o-mini")

    with pytest.raises((GatewayForbiddenError, ValueError)):
        LLMClient()


def test_refuse_path_does_not_call_litellm(monkeypatch):
    _clear_llm_env(monkeypatch)
    monkeypatch.setenv("BASE_LLM_GATEWAY_URL", "http://x/llm/v1")
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-valid")
    monkeypatch.setenv("LLM_MODEL", "openai/gpt-4o-mini")

    calls = {"n": 0}

    def boom(*a, **k):
        calls["n"] += 1
        raise AssertionError("litellm.completion must not be called when gateway residue present")

    monkeypatch.setattr("src.llm.client.litellm.completion", boom, raising=False)
    # Import after environment set; still must raise before completion.
    with pytest.raises((GatewayForbiddenError, ValueError)):
        client = LLMClient()
        client.chat([{"role": "user", "content": "nope"}])
    assert calls["n"] == 0


def test_mock_allows_empty_env_without_gateway(monkeypatch):
    _clear_llm_env(monkeypatch)
    client = LLMClient(mock=True)
    try:
        assert client.chat([{"role": "user", "content": "x"}]).text
    finally:
        client.close()
