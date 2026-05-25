"""
Hardcoded benchmark configuration for SuperAgent.

Simulates Codex exec with these flags:
- --model gpt-5.2
- -c model_reasoning_effort=xhigh
- --dangerously-bypass-approvals-and-sandbox
- --skip-git-repo-check
- --enable unified_exec
- --json

All settings are hardcoded - no CLI arguments needed.
"""

from __future__ import annotations

import os
from typing import Any, Dict

# Main configuration - simulates Codex exec benchmark mode
CONFIG: Dict[str, Any] = {
    # ==========================================================================
    # Model Settings (simulates --model gpt-5.2 -c model_reasoning_effort=xhigh)
    # ==========================================================================
    # Model to use via DeepSeek API (OpenAI-compatible)
    "model": os.environ.get("LLM_MODEL", "deepseek-v4-pro"),
    # Provider
    "provider": "deepseek",
    # Reasoning effort: none, minimal, low, medium, high, xhigh (not used for Claude)
    "reasoning_effort": "none",
    # Token limits
    "max_tokens": 16384,
    # Temperature (0 = deterministic)
    "temperature": 0.0,
    # ==========================================================================
    # Agent Execution Settings
    # ==========================================================================
    # Maximum iterations before stopping
    "max_iterations": 200,
    # Maximum tokens for tool output truncation (middle-out strategy)
    "max_output_tokens": 2500,  # ~10KB
    # Timeout for shell commands (seconds)
    "shell_timeout": 60,
    # ==========================================================================
    # Context Management (like OpenCode/Codex)
    # ==========================================================================
    # Model context window (Claude Opus 4.5 = 200K)
    "model_context_limit": 200_000,
    # Reserved tokens for output
    "output_token_max": 32_000,
    # Trigger compaction at this % of usable context (85%)
    "auto_compact_threshold": 0.85,
    # Tool output pruning constants (from OpenCode)
    "prune_protect": 40_000,  # Protect this many tokens of recent tool output
    "prune_minimum": 20_000,  # Only prune if we can recover at least this many
    # ==========================================================================
    # Prompt Caching
    # ==========================================================================
    # Enable prompt caching
    "cache_enabled": True,
    # Note: Caching behavior depends on the model/provider
    # System prompt should be large enough to meet provider thresholds
    # ==========================================================================
    # Simulated Codex Flags (all enabled/bypassed for benchmark)
    # ==========================================================================
    # --dangerously-bypass-approvals-and-sandbox
    "bypass_approvals": True,
    "bypass_sandbox": True,
    # --skip-git-repo-check
    "skip_git_check": True,
    # --enable unified_exec
    "unified_exec": True,
    # --json (always JSONL output)
    "json_output": True,
    # ==========================================================================
    # Double Confirmation for Task Completion
    # ==========================================================================
    # Require double confirmation before marking task complete
    # Disabled for fully autonomous operation in evaluation mode
    "require_completion_confirmation": False,
}


def get_config() -> Dict[str, Any]:
    """Get the configuration dictionary."""
    return CONFIG.copy()


def get(key: str, default: Any = None) -> Any:
    """Get a configuration value."""
    return CONFIG.get(key, default)
