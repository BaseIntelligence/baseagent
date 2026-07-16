import asyncio
import subprocess
import sys
import zipfile
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


@dataclass
class FakeExecResult:
    stdout: str
    stderr: str = ""
    exit_code: int = 0


class FakeHarborEnvironment:
    def __init__(self, root: Path):
        self.root = root
        self.app = root / "app"
        self.agent_mount = root / "workspace" / "agent"
        self.app.mkdir(parents=True, exist_ok=True)
        self.agent_mount.mkdir(parents=True, exist_ok=True)
        self.calls = []

    async def exec(self, command, cwd=None, timeout=None, **kwargs):
        self.calls.append({"command": command, "cwd": cwd, "timeout": timeout, "kwargs": kwargs})
        mapped_cwd = self._map_path(cwd or "/app")
        mapped_command = self._map_command(command)
        result = subprocess.run(
            ["sh", "-c", mapped_command],
            cwd=mapped_cwd,
            capture_output=True,
            text=True,
            timeout=timeout or 120,
        )
        return FakeExecResult(result.stdout, result.stderr, result.returncode)

    def _map_path(self, path):
        text = str(path)
        if text == "/app" or text.startswith("/app/"):
            return str(self.app) + text[len("/app") :]
        if text == "/workspace/agent" or text.startswith("/workspace/agent/"):
            return str(self.agent_mount) + text[len("/workspace/agent") :]
        return text

    def _map_command(self, command):
        return command.replace("/workspace/agent", str(self.agent_mount)).replace("/app", str(self.app))


class ShellContext:
    instruction = "test task"
    cwd = "/app"

    def __init__(self):
        self.is_done = False

    def shell(self, command):
        return SimpleNamespace(output="/app\ntotal 0", exit_code=0)

    def done(self):
        self.is_done = True


class LoopResponse:
    text = "done"
    function_calls = []
    tokens = {"input": 1, "output": 1, "cached": 0}

    def has_function_calls(self):
        return False


class RecordingLLM:
    def __init__(self):
        self.calls = []

    def chat(self, *args, **kwargs):
        self.calls.append(kwargs)
        return LoopResponse()


def test_agent_entrypoint_importable_without_harbor():
    sys.modules.pop("harbor", None)

    import agent as agent_module

    instance = agent_module.Agent()
    assert agent_module.Agent.name() == "BaseAgent"
    assert agent_module.Agent.version() == "1.0.0"
    assert agent_module.Agent.import_path() == "agent:Agent"
    assert instance.name() == "BaseAgent"
    assert instance.version() == "1.0.0"
    assert instance.import_path() == "agent:Agent"


def test_agent_entrypoint_accepts_harbor_factory_kwargs(tmp_path):
    import agent as agent_module

    instance = agent_module.Agent(logs_dir=tmp_path, model_name="openai/gpt-4o-mini", extra="ignored")

    assert instance.import_path() == "agent:Agent"


@pytest.mark.asyncio
async def test_run_requires_api_key_without_gateway(monkeypatch, tmp_path):
    import agent

    for key in (
        "BASE_LLM_GATEWAY_URL",
        "BASE_GATEWAY_TOKEN",
        "BASEAGENT_MOCK_LLM",
        "OPENROUTER_API_KEY",
        "OPENAI_API_KEY",
        "BASEAGENT_LLM_API_KEY",
        "LLM_API_KEY",
        "DEEPSEEK_API_KEY",
        "ANTHROPIC_API_KEY",
        "CHUTES_API_KEY",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(
        agent, "LLMClient", lambda **kwargs: pytest.fail("LLMClient should not be constructed")
    )

    with pytest.raises(ValueError, match="(?i)API key|OPENROUTER"):
        await agent.Agent().run("do work", FakeHarborEnvironment(tmp_path), SimpleNamespace(env={}))


@pytest.mark.asyncio
async def test_run_refuses_gateway_env_even_with_openrouter(monkeypatch, tmp_path):
    import agent

    monkeypatch.delenv("BASEAGENT_MOCK_LLM", raising=False)
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-key")
    monkeypatch.setenv("BASE_LLM_GATEWAY_URL", "https://gateway.example/llm/v1")
    monkeypatch.setattr(
        agent, "LLMClient", lambda **kwargs: pytest.fail("LLMClient should not be constructed")
    )

    with pytest.raises(ValueError, match="(?i)gateway"):
        await agent.Agent().run("do work", FakeHarborEnvironment(tmp_path), SimpleNamespace(env={}))


@pytest.mark.asyncio
async def test_context_env_hydrates_openrouter(monkeypatch, tmp_path):
    import agent
    from src.tools.harbor_registry import HarborToolRegistry

    captured = {}

    class DummyLLM:
        def __init__(self, **kwargs):
            captured["llm_kwargs"] = kwargs

        def close(self):
            captured["closed"] = True

    def fake_loop(llm, tools, ctx, config):
        captured["ctx_cwd"] = ctx.cwd
        captured["tools_type"] = type(tools)
        captured["config"] = config
        ctx.done()

    for key in (
        "BASE_LLM_GATEWAY_URL",
        "BASE_GATEWAY_TOKEN",
        "OPENROUTER_API_KEY",
        "LLM_MODEL",
        "BASEAGENT_LLM_PROVIDER",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(agent, "LLMClient", DummyLLM)
    monkeypatch.setattr(agent, "run_agent_loop", fake_loop)

    env = {
        "OPENROUTER_API_KEY": "context-or-key",
        "LLM_MODEL": "openai/gpt-4o-mini",
        "LLM_COST_LIMIT": "1.25",
        "BASEAGENT_LLM_PROVIDER": "openrouter",
    }

    result = await agent.Agent().run("do work", FakeHarborEnvironment(tmp_path), {"env": env})

    assert result == "Task completed"
    kwargs = captured["llm_kwargs"]
    assert kwargs["temperature"] == 0.0
    assert kwargs["max_tokens"] == 16384
    assert kwargs["cost_limit"] == 1.25
    assert kwargs["api_key"] == "context-or-key"
    assert kwargs["mock"] is False
    assert kwargs.get("provider") == "openrouter"
    assert kwargs.get("model") == "openai/gpt-4o-mini"
    assert "token" not in kwargs or kwargs.get("token") is None
    assert not (kwargs.get("base_url") or "").endswith("/llm/v1")
    assert captured["ctx_cwd"] == "/app"
    assert captured["tools_type"] is HarborToolRegistry
    assert captured["closed"] is True


@pytest.mark.asyncio
async def test_run_mock_llm_executes_without_api_key(monkeypatch, tmp_path):
    import agent

    for key in (
        "BASE_LLM_GATEWAY_URL",
        "BASE_GATEWAY_TOKEN",
        "DEEPSEEK_API_KEY",
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "OPENROUTER_API_KEY",
        "CHUTES_API_KEY",
        "BASEAGENT_MOCK_LLM",
    ):
        monkeypatch.delenv(key, raising=False)

    environment = FakeHarborEnvironment(tmp_path)
    result = await agent.Agent().run(
        "do a trivial task",
        environment,
        {"env": {"BASEAGENT_MOCK_LLM": "1"}},
    )

    assert result == "Task completed"
    assert environment.calls, "mock run should still execute real environment commands"


@pytest.mark.asyncio
async def test_shell_bridge_uses_environment_exec_from_worker_thread(tmp_path):
    from src.tools.harbor_registry import HarborAgentContext

    environment = FakeHarborEnvironment(tmp_path)
    ctx = HarborAgentContext("task", environment, asyncio.get_running_loop())

    result = await asyncio.to_thread(ctx.shell, "printf bridge-ok")

    assert result.output == "bridge-ok"
    assert result.exit_code == 0
    assert environment.calls[0]["cwd"] == "/app"


@pytest.mark.asyncio
async def test_registry_remote_operations_use_app_not_agent_mount(tmp_path):
    from src.tools.harbor_registry import HarborAgentContext, HarborToolRegistry

    environment = FakeHarborEnvironment(tmp_path)
    ctx = HarborAgentContext("task", environment, asyncio.get_running_loop())
    registry = HarborToolRegistry(ctx)

    write = await asyncio.to_thread(
        registry.execute,
        ctx,
        "write_file",
        {"file_path": "notes/example.txt", "content": "alpha\nbeta\n"},
    )
    read = await asyncio.to_thread(
        registry.execute,
        ctx,
        "read_file",
        {"file_path": "notes/example.txt", "offset": 2, "limit": 1},
    )
    listed = await asyncio.to_thread(
        registry.execute,
        ctx,
        "list_dir",
        {"dir_path": "notes", "limit": 5},
    )
    grep = await asyncio.to_thread(
        registry.execute,
        ctx,
        "grep_files",
        {"pattern": "beta", "path": "notes", "limit": 5},
    )
    patch = await asyncio.to_thread(
        registry.execute,
        ctx,
        "apply_patch",
        {
            "patch": """*** Begin Patch
*** Update File: notes/example.txt
@@
 alpha
-beta
+gamma
*** End Patch"""
        },
    )
    reread = await asyncio.to_thread(
        registry.execute,
        ctx,
        "read_file",
        {"file_path": "notes/example.txt"},
    )
    image = await asyncio.to_thread(registry.execute, ctx, "view_image", {"path": "image.png"})

    assert write.success, write.output
    assert read.output.strip() == "L2: beta"
    assert "example.txt" in listed.output
    assert "example.txt" in grep.output
    assert patch.success, patch.output
    assert "gamma" in reread.output
    assert not image.success
    assert (environment.app / "notes" / "example.txt").exists()
    assert not (environment.agent_mount / "notes" / "example.txt").exists()
    assert all(call["cwd"] == "/app" for call in environment.calls)


def test_loop_does_not_send_incompatible_reasoning_payload():
    from src.core.loop import run_agent_loop
    from src.tools.registry import ToolRegistry

    llm = RecordingLLM()
    ctx = ShellContext()
    config = {"max_iterations": 3, "cache_enabled": False, "max_tokens": 128, "max_output_tokens": 100}

    run_agent_loop(llm=llm, tools=ToolRegistry(), ctx=ctx, config=config)

    assert ctx.is_done is True
    assert llm.calls
    assert all("extra_body" not in call for call in llm.calls)


def test_runtime_zip_contract_includes_harbor_entrypoint_and_validates_if_available(tmp_path):
    required = {"agent.py", "pyproject.toml", "requirements.txt"}
    paths = [ROOT / name for name in required]
    paths.extend(sorted((ROOT / "src").glob("**/*.py")))

    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in paths:
            archive.write(path, path.relative_to(ROOT).as_posix())

    zip_bytes = buffer.getvalue()
    names = set(zipfile.ZipFile(BytesIO(zip_bytes)).namelist())

    assert required <= names
    assert "src/tools/harbor_registry.py" in names
    assert any(name.startswith("src/") and name.endswith(".py") for name in names)
    assert len(zip_bytes) <= 1_048_576
    assert "harbor" not in (ROOT / "requirements.txt").read_text(encoding="utf-8").lower()
    assert "harbor" not in (ROOT / "pyproject.toml").read_text(encoding="utf-8").lower()

    agent_challenge_src = Path("/root/agent-challenge/src")
    if agent_challenge_src.exists():
        sys.path.insert(0, str(agent_challenge_src))
        from agent_challenge.submissions.artifacts import build_zip_manifest

        manifest = build_zip_manifest(zip_bytes=zip_bytes, artifact_reference="agent.zip")
        assert {entry.normalized_path for entry in manifest.entries} == names
