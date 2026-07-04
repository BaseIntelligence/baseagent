import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.llm.client import LLMClient, LLMError

GATEWAY_URL = "http://gateway.internal/llm/v1"


def _prep_env(monkeypatch):
    monkeypatch.setenv("BASE_LLM_GATEWAY_URL", GATEWAY_URL)
    monkeypatch.setenv("BASE_GATEWAY_TOKEN", "gw-token")
    monkeypatch.delenv("BASEAGENT_MOCK_LLM", raising=False)


class FakeResponse:
    """Minimal stand-in for an httpx.Response returned by the gateway."""

    def __init__(self, payload=None, status_code=200):
        self.status_code = status_code
        self._payload = payload or {
            "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
            "model": "server-injected-model",
            "usage": {},
        }
        self.text = "ok"

    def json(self):
        return self._payload


class FakeClient:
    """Scriptable stand-in for httpx.Client exposing post/is_closed/close.

    ``actions`` is consumed one item per ``post`` call: an ``Exception`` is
    raised, anything else is returned as the response.
    """

    def __init__(self, actions):
        self._actions = list(actions)
        self.is_closed = False
        self.post_calls = 0

    def post(self, url, json):
        self.post_calls += 1
        if not self._actions:
            raise AssertionError("FakeClient.post called with no scripted actions left")
        action = self._actions.pop(0)
        if isinstance(action, Exception):
            raise action
        return action

    def close(self):
        self.is_closed = True


def _install_clients(monkeypatch, client, clients):
    """Make ``client`` use ``clients[0]`` now and hand out the rest on rebuild."""
    real = client._client
    client._client = clients[0]
    remaining = iter(clients[1:])
    monkeypatch.setattr(client, "_build_client", lambda: next(remaining))
    if real is not None:
        real.close()


def test_chat_recovers_from_closed_client_runtimeerror(monkeypatch):
    _prep_env(monkeypatch)
    monkeypatch.setattr("src.llm.client.time.sleep", lambda *a, **k: None)

    client = LLMClient()
    failing = FakeClient([RuntimeError("Cannot send a request, as the client has been closed.")])
    healthy = FakeClient([FakeResponse()])
    _install_clients(monkeypatch, client, [failing, healthy])

    try:
        response = client.chat([{"role": "user", "content": "hello"}])
    finally:
        client.close()

    assert response.text == "ok"
    assert failing.is_closed  # broken client was discarded
    assert healthy.post_calls == 1  # rebuilt client served the request


def test_chat_recovers_from_transport_error(monkeypatch):
    _prep_env(monkeypatch)
    monkeypatch.setattr("src.llm.client.time.sleep", lambda *a, **k: None)

    client = LLMClient()
    failing = FakeClient([httpx.ConnectError("simulated connect failure")])
    healthy = FakeClient([FakeResponse()])
    _install_clients(monkeypatch, client, [failing, healthy])

    try:
        response = client.chat([{"role": "user", "content": "hello"}])
    finally:
        client.close()

    assert response.text == "ok"
    assert failing.is_closed
    assert healthy.post_calls == 1


def test_chat_raises_connection_error_after_exhausting_retries(monkeypatch):
    _prep_env(monkeypatch)
    monkeypatch.setattr("src.llm.client.time.sleep", lambda *a, **k: None)

    client = LLMClient()
    failing_clients = [
        FakeClient([httpx.ConnectError("simulated connect failure")]) for _ in range(3)
    ]
    _install_clients(monkeypatch, client, failing_clients)

    try:
        with pytest.raises(LLMError) as excinfo:
            client.chat([{"role": "user", "content": "hello"}])
    finally:
        client.close()

    assert excinfo.value.code == "connection_error"
    assert all(fc.is_closed for fc in failing_clients)


def test_ensure_client_rebuilds_closed_client(monkeypatch):
    _prep_env(monkeypatch)

    client = LLMClient()
    fresh = FakeClient([])
    monkeypatch.setattr(client, "_build_client", lambda: fresh)

    client._client.close()  # real httpx client -> is_closed True
    assert client._client.is_closed

    client._ensure_client()

    assert client._client is fresh
    assert client._client.is_closed is False
    client.close()


def test_mock_mode_returns_mock_without_client(monkeypatch):
    for key in ("BASE_LLM_GATEWAY_URL", "BASE_GATEWAY_TOKEN", "BASEAGENT_MOCK_LLM"):
        monkeypatch.delenv(key, raising=False)

    client = LLMClient(mock=True)
    try:
        assert client._client is None
        response = client.chat([{"role": "user", "content": "hi"}])
        assert response.text
        assert client._client is None  # mock never builds a network client
    finally:
        client.close()
