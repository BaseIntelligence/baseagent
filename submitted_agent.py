"""Harbor entrypoint for agent-challenge ZIP submissions."""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from typing import Any

_AGENT_ROOT = Path(__file__).resolve().parent
if str(_AGENT_ROOT) not in sys.path:
    sys.path.insert(0, str(_AGENT_ROOT))

from src.config.defaults import get_config  # noqa: E402
from src.core.loop import run_agent_loop  # noqa: E402
from src.llm.client import LLMClient  # noqa: E402
from src.tools.harbor_registry import (  # noqa: E402
    DEFAULT_HARBOR_CWD,
    HarborAgentContext,
    HarborToolRegistry,
)

try:
    from harbor.agents.base import BaseAgent as HarborBaseAgent
except ModuleNotFoundError:
    HarborBaseAgent = object


class Agent(HarborBaseAgent):
    """Harbor-compatible BaseAgent adapter."""

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
        return "submitted_agent:Agent"

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
