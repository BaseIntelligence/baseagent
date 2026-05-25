#!/usr/bin/env python3
"""
SuperAgent for Term Challenge - Entry Point (SDK 3.0 Compatible).

This agent accepts --instruction from the validator and runs autonomously.
Uses DeepSeek API for LLM calls instead of term_sdk.

Installation:
    pip install .                    # via pyproject.toml
    pip install -r requirements.txt  # via requirements.txt

Usage:
    python agent.py --instruction "Your task description here..."
"""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent))


# Auto-install dependencies if missing
def ensure_dependencies():
    """Install dependencies if not present."""
    if importlib.util.find_spec("httpx") and importlib.util.find_spec("pydantic"):
        return
    print("[setup] Installing dependencies...", file=sys.stderr)
    agent_dir = Path(__file__).parent
    req_file = agent_dir / "requirements.txt"
    if req_file.exists():
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "-r", str(req_file), "-q"], check=True
        )
    else:
        subprocess.run(
            [sys.executable, "-m", "pip", "install", str(agent_dir), "-q"], check=True
        )
    print("[setup] Dependencies installed", file=sys.stderr)


ensure_dependencies()

from src.config.defaults import CONFIG, get_config  # noqa: E402
from src.core.loop import run_agent_loop  # noqa: E402
from src.llm.client import CostLimitExceeded, LLMClient  # noqa: E402
from src.output.jsonl import ErrorEvent, emit  # noqa: E402
from src.tools.harbor_registry import (  # noqa: E402
    DEFAULT_HARBOR_CWD,
    HarborAgentContext,
    HarborToolRegistry,
)
from src.tools.registry import ToolRegistry  # noqa: E402

try:
    from harbor.agents.base import BaseAgent as HarborBaseAgent
except ModuleNotFoundError:
    HarborBaseAgent = object


class Agent(HarborBaseAgent):
    """Harbor-compatible BaseAgent adapter for agent-challenge ZIP submissions."""

    def __init__(
        self,
        logs_dir: Path | None = None,
        model_name: str | None = None,
        **kwargs: Any,
    ) -> None:
        if HarborBaseAgent is not object:
            super().__init__(logs_dir=logs_dir or Path("."), model_name=model_name, **kwargs)
        self.environment: Any | None = None

    @staticmethod
    def name() -> str:
        return "BaseAgent"

    @staticmethod
    def version() -> str:
        return "1.0.0"

    @staticmethod
    def import_path() -> str:
        return "agent:Agent"

    async def setup(self, environment: Any) -> None:
        self.environment = environment

    async def run(self, instruction: str, environment: Any, context: Any) -> str:
        active_environment = environment or self.environment
        if active_environment is None:
            raise ValueError("Harbor environment is required")

        context_env = _extract_context_env(context)
        api_key = os.environ.get("DEEPSEEK_API_KEY") or context_env.get("DEEPSEEK_API_KEY")
        if not api_key:
            raise ValueError("DEEPSEEK_API_KEY is required for BaseAgent Harbor runs")

        config = get_config()
        if context_env.get("LLM_MODEL"):
            config["model"] = context_env["LLM_MODEL"]

        cost_limit = _parse_optional_float(context_env.get("LLM_COST_LIMIT"))
        base_url = context_env.get("DEEPSEEK_BASE_URL") or os.environ.get("DEEPSEEK_BASE_URL")

        llm = LLMClient(
            model=config["model"],
            temperature=config.get("temperature"),
            max_tokens=int(config.get("max_tokens", 16384)),
            cost_limit=cost_limit,
            base_url=base_url,
            api_key=api_key,
        )

        loop = asyncio.get_running_loop()
        harbor_context = HarborAgentContext(
            instruction=instruction,
            environment=active_environment,
            loop=loop,
            cwd=DEFAULT_HARBOR_CWD,
            env=context_env,
        )
        tools = HarborToolRegistry(harbor_context, cwd=DEFAULT_HARBOR_CWD)

        try:
            await asyncio.to_thread(run_agent_loop, llm, tools, harbor_context, config)
        finally:
            close = getattr(llm, "close", None)
            if callable(close):
                close()

        return "Task completed"


def _extract_context_env(context: Any) -> dict[str, str]:
    if context is None:
        return {}
    if isinstance(context, dict):
        raw_env = context.get("env", {})
    else:
        raw_env = getattr(context, "env", {})
    if raw_env is None:
        return {}
    return {str(key): str(value) for key, value in dict(raw_env).items()}


def _parse_optional_float(value: str | None) -> float | None:
    if value in (None, ""):
        return None
    return float(value)


class AgentContext:
    """Minimal context for agent execution (replaces term_sdk.AgentContext)."""

    def __init__(self, instruction: str, cwd: str = None):
        self.instruction = instruction
        self.cwd = cwd or os.getcwd()
        self.step = 0
        self.is_done = False
        self.history = []
        self._start_time = time.time()

    @property
    def elapsed_secs(self) -> float:
        return time.time() - self._start_time

    def shell(self, cmd: str, timeout: int = 120) -> "ShellResult":
        """Execute a shell command."""
        self.step += 1
        try:
            result = subprocess.run(
                cmd,
                shell=True,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=self.cwd,
            )
            output = result.stdout + result.stderr
            exit_code = result.returncode
        except subprocess.TimeoutExpired:
            output = "[TIMEOUT]"
            exit_code = -1
        except Exception as e:
            output = f"[ERROR] {e}"
            exit_code = -1

        shell_result = ShellResult(output=output, exit_code=exit_code)
        self.history.append(
            {
                "step": self.step,
                "command": cmd,
                "output": output[:1000],
                "exit_code": exit_code,
            }
        )
        return shell_result

    def done(self):
        """Mark task as complete."""
        self.is_done = True

    def log(self, msg: str):
        """Log a message."""
        timestamp = time.strftime("%H:%M:%S")
        print(f"[{timestamp}] [ctx] {msg}", file=sys.stderr, flush=True)


class ShellResult:
    """Result from shell command."""

    def __init__(self, output: str, exit_code: int):
        self.output = output
        self.stdout = output
        self.stderr = ""
        self.exit_code = exit_code

    def has(self, text: str) -> bool:
        return text in self.output


def _log(msg: str):
    """Log to stderr."""
    timestamp = time.strftime("%H:%M:%S")
    print(f"[{timestamp}] [superagent] {msg}", file=sys.stderr, flush=True)


def main():
    parser = argparse.ArgumentParser(description="SuperAgent for Term Challenge SDK 3.0")
    parser.add_argument("--instruction", required=True, help="Task instruction from validator")
    args = parser.parse_args()

    _log("=" * 60)
    _log("SuperAgent Starting (SDK 3.0 - DeepSeek API)")
    _log("=" * 60)
    _log(f"Model: {CONFIG['model']}")
    _log(f"Reasoning effort: {CONFIG.get('reasoning_effort', 'default')}")
    _log(f"Instruction: {args.instruction[:200]}...")
    _log("-" * 60)

    # Initialize components
    start_time = time.time()

    llm = LLMClient(
        model=CONFIG["model"],
        temperature=CONFIG.get("temperature"),
        max_tokens=CONFIG.get("max_tokens", 16384),
    )

    tools = ToolRegistry()
    ctx = AgentContext(instruction=args.instruction)

    _log("Components initialized")

    try:
        run_agent_loop(
            llm=llm,
            tools=tools,
            ctx=ctx,
            config=CONFIG,
        )
    except CostLimitExceeded as e:
        _log(f"Cost limit exceeded: {e}")
        emit(ErrorEvent(message=f"Cost limit exceeded: {e}"))
    except Exception as e:
        _log(f"Fatal error: {e}")
        emit(ErrorEvent(message=str(e)))
        raise
    finally:
        elapsed = time.time() - start_time
        try:
            stats = llm.get_stats()
            _log(f"Total tokens: {stats.get('total_tokens', 0)}")
            _log(f"Total cost: ${stats.get('total_cost', 0):.4f}")
            _log(f"Requests: {stats.get('request_count', 0)}")
        except Exception as e:
            _log(f"Stats error: {e}")
        _log(f"Elapsed: {elapsed:.1f}s")
        _log("Agent finished")
        _log("=" * 60)


if __name__ == "__main__":
    main()
