"""TDD: LLMClient.chat adapts litellm.completion into existing LLMResponse."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.llm.client import LLMClient, LLMError


def _clear_llm_env(monkeypatch):
    for key in (
        "BASE_LLM_GATEWAY_URL",
        "BASE_GATEWAY_TOKEN",
        "GATEWAY_TOKEN",
        "BASEAGENT_MOCK_LLM",
        "BASEAGENT_LLM_PROVIDER",
        "LLM_MODEL",
        "OPENROUTER_API_KEY",
        "OPENAI_API_KEY",
        "BASEAGENT_LLM_BASE_URL",
        "BASEAGENT_LLM_API_KEY",
    ):
        monkeypatch.delenv(key, raising=False)


def _fake_message(**kwargs):
    return SimpleNamespace(**kwargs)


def _fake_choice(message, finish_reason="stop"):
    return SimpleNamespace(message=message, finish_reason=finish_reason)


def _fake_usage(prompt=3, completion=5, cached=1):
    return SimpleNamespace(
        prompt_tokens=prompt,
        completion_tokens=completion,
        prompt_tokens_details=SimpleNamespace(cached_tokens=cached),
    )


def test_chat_maps_text_and_tools_from_litellm(monkeypatch):
    _clear_llm_env(monkeypatch)
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-test")
    monkeypatch.setenv("LLM_MODEL", "openai/gpt-4o-mini")

    captured = {}

    tool_call = SimpleNamespace(
        id="call_1",
        function=SimpleNamespace(name="shell", arguments=json.dumps({"command": "ls"})),
    )
    message = _fake_message(content="working", tool_calls=[tool_call])
    fake = SimpleNamespace(
        choices=[_fake_choice(message, finish_reason="tool_calls")],
        usage=_fake_usage(),
        model="openai/gpt-4o-mini",
        model_extra=None,
    )

    def fake_completion(**kwargs):
        captured.update(kwargs)
        return fake

    monkeypatch.setattr("src.llm.client.litellm.completion", fake_completion)

    client = LLMClient()
    try:
        response = client.chat(
            [{"role": "user", "content": "list files"}],
            tools=[{"name": "shell", "description": "run shell", "parameters": {"type": "object"}}],
        )
    finally:
        client.close()

    assert response.text == "working"
    assert response.has_function_calls()
    assert response.function_calls[0].name == "shell"
    assert response.function_calls[0].arguments["command"] == "ls"
    assert response.tokens["input"] == 3
    assert response.tokens["output"] == 5
    assert "openrouter/" in captured["model"] or captured["model"] == "openai/gpt-4o-mini"
    assert captured.get("api_key") == "or-test"
    assert captured.get("tools")


def test_chat_maps_timeout_to_llm_error(monkeypatch):
    _clear_llm_env(monkeypatch)
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-test")
    monkeypatch.setenv("LLM_MODEL", "openai/gpt-4o-mini")

    class TimeoutErrorLite(Exception):
        pass

    def raise_timeout(**kwargs):
        raise TimeoutErrorLite("timed out")

    monkeypatch.setattr("src.llm.client.litellm.completion", raise_timeout)
    # Map by string when exception is not litellm native
    client = LLMClient()
    try:
        with pytest.raises(LLMError) as excinfo:
            client.chat([{"role": "user", "content": "x"}])
        assert excinfo.value.code in {"timeout", "api_error", "connection_error", "unknown"}
    finally:
        client.close()


def test_requirements_pins_litellm():
    root = Path(__file__).resolve().parents[1]
    req = (root / "requirements.txt").read_text(encoding="utf-8").lower()
    pyproject = (root / "pyproject.toml").read_text(encoding="utf-8").lower()
    assert "litellm" in req
    assert "litellm" in pyproject
