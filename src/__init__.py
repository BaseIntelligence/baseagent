"""
BaseAgent - An autonomous coding agent for Term Challenge.

Inspired by OpenAI Codex CLI, BaseAgent is designed to solve
terminal-based coding tasks autonomously using LLMs.

SDK 3.0 Compatible - Uses DeepSeek API via httpx instead of term_sdk.

Usage:
    python agent.py --instruction "Your task here..."
"""

__version__ = "1.0.0"
__author__ = "Platform Network"

# Import main components for convenience
from src.config.defaults import CONFIG
from src.output.jsonl import emit
from src.tools.registry import ToolRegistry

__all__ = [
    "CONFIG",
    "ToolRegistry",
    "emit",
    "__version__",
]
