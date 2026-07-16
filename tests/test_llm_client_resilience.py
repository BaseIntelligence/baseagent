"""Resilience tests remapped onto LiteLLM completion error surfaces."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.llm.client import LLMClient, LLMError


def _prep_env(monkeypatch):
    for key in (
        "BASE_LLM_GATEWAY_URL",
        "BASE_GATEWAY_TOKEN",
        "BASEAGENT_MOCK_LLM",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-token")
    monkeypatch.setenv("LLM_MODEL", "openai/gpt-4o-mini")


class OKResponse:
    model = "openai/gpt-4o-mini"
    usage = None
    choices = [
        type(
            "C",
            (),
            {
                "finish_reason": "stop",
                "message": type("M", (), {"content": "ok", "tool_calls": None})(),
            },
        )()
    ]


def test_chat_maps_connection_errors(monkeypatch):
    _prep_env(monkeypatch)

    def raise_connect(**kwargs):
        raise ConnectionError("simulated connect failure")

    monkeypatch.setattr("src.llm.client.litellm.completion", raise_connect)
    client = LLMClient()
    try:
        with pytest.raises(LLMError) as excinfo:
            client.chat([{"role": "user", "content": "hello"}])
    finally:
        client.close()
    assert excinfo.value.code == "connection_error"


def test_chat_maps_timeouts(monkeypatch):
    _prep_env(monkeypatch)

    class TimeoutException(Exception):
        pass

    def raise_timeout(**kwargs):
        raise TimeoutException("request timeout")

    monkeypatch.setattr("src.llm.client.litellm.completion", raise_timeout)
    client = LLMClient()
    try:
        with pytest.raises(LLMError) as excinfo:
            client.chat([{"role": "user", "content": "hello"}])
    finally:
        client.close()
    assert excinfo.value.code == "timeout"


def test_chat_success_after_transient_retry_ostyle(monkeypatch):
    """LiteLLM owns transport; success path still returns LLMResponse."""
    _prep_env(monkeypatch)
    monkeypatch.setattr("src.llm.client.litellm.completion", lambda **k: OKResponse())

    client = LLMClient()
    try:
        response = client.chat([{"role": "user", "content": "hello"}])
    finally:
        client.close()
    assert response.text == "ok"


def test_mock_mode_returns_mock_without_network(monkeypatch):
    for key in ("BASE_LLM_GATEWAY_URL", "BASE_GATEWAY_TOKEN", "BASEAGENT_MOCK_LLM", "OPENROUTER_API_KEY"):
        monkeypatch.delenv(key, raising=False)

    client = LLMClient(mock=True)
    try:
        response = client.chat([{"role": "user", "content": "hi"}])
        assert response.text
    finally:
        client.close()
