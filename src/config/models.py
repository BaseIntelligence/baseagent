"""Pydantic models for SuperAgent configuration."""

from __future__ import annotations

import os
from enum import Enum
from pathlib import Path

from pydantic import BaseModel, Field, field_validator


class ReasoningEffort(str, Enum):
    """Reasoning effort levels for the model."""

    NONE = "none"
    MINIMAL = "minimal"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    XHIGH = "xhigh"


class OutputMode(str, Enum):
    """Output mode for the agent."""

    HUMAN = "human"
    JSON = "json"


class Provider(str, Enum):
    """LLM provider.

    The agent always calls the platform LLM gateway; the gateway (not the agent)
    picks the real upstream provider and model.
    """

    GATEWAY = "gateway"


class ReasoningConfig(BaseModel):
    """Configuration for model reasoning."""

    effort: ReasoningEffort = Field(
        default=ReasoningEffort.HIGH, description="Reasoning effort level"
    )


class CacheConfig(BaseModel):
    """Configuration for prompt caching."""

    enabled: bool = Field(default=True, description="Enable prompt caching")


class RetryConfig(BaseModel):
    """Configuration for retry logic."""

    max_attempts: int = Field(default=5, description="Maximum retry attempts")
    base_delay: float = Field(default=1.0, description="Base delay in seconds")
    max_delay: float = Field(default=60.0, description="Maximum delay in seconds")
    retry_on_status: list[int] = Field(
        default=[429, 500, 502, 503, 504], description="HTTP status codes to retry on"
    )


class ToolsConfig(BaseModel):
    """Configuration for available tools."""

    shell_enabled: bool = Field(default=True, description="Enable shell execution")
    shell_timeout: int = Field(default=30, description="Shell timeout in seconds")
    file_ops_enabled: bool = Field(default=True, description="Enable file operations")
    max_file_size: int = Field(default=1048576, description="Maximum file size to read")
    grep_enabled: bool = Field(default=True, description="Enable grep/search")
    max_grep_results: int = Field(default=100, description="Maximum grep results")


class OutputConfig(BaseModel):
    """Configuration for output formatting."""

    mode: OutputMode = Field(default=OutputMode.HUMAN, description="Output mode")
    streaming: bool = Field(default=True, description="Enable streaming output")
    colors: bool = Field(default=True, description="Enable colored output")


class PathsConfig(BaseModel):
    """Configuration for file paths."""

    cwd: str = Field(default="", description="Working directory")
    readable_roots: list[str] = Field(default=[], description="Additional readable directories")
    writable_roots: list[str] = Field(default=[], description="Additional writable directories")

    @field_validator("cwd", mode="before")
    @classmethod
    def resolve_cwd(cls, v: str) -> str:
        """Resolve empty cwd to current directory."""
        if not v:
            return os.getcwd()
        return str(Path(v).resolve())


class AgentConfig(BaseModel):
    """Main configuration for the SuperAgent."""

    # Model settings
    model: str = Field(
        default="gateway-default",
        description="Neutral placeholder; the gateway injects the real model",
    )
    provider: Provider = Field(default=Provider.GATEWAY, description="LLM provider")
    max_iterations: int = Field(default=50, description="Maximum iterations")
    timeout: int = Field(default=120, description="Timeout per LLM call in seconds")
    temperature: float = Field(default=0.7, description="Generation temperature")
    max_tokens: int = Field(default=16384, description="Maximum tokens for response")

    # Sub-configurations
    reasoning: ReasoningConfig = Field(default_factory=ReasoningConfig)
    cache: CacheConfig = Field(default_factory=CacheConfig)
    retry: RetryConfig = Field(default_factory=RetryConfig)
    tools: ToolsConfig = Field(default_factory=ToolsConfig)
    output: OutputConfig = Field(default_factory=OutputConfig)
    paths: PathsConfig = Field(default_factory=PathsConfig)

    @property
    def working_directory(self) -> Path:
        """Get the working directory as a Path object."""
        return Path(self.paths.cwd or os.getcwd())

    def get_token(self) -> str | None:
        """Get the signed gateway token used to authenticate to the LLM gateway.

        The agent never holds a provider API key; the gateway token is the auth.
        """
        return os.environ.get("BASE_GATEWAY_TOKEN")

    def get_base_url(self) -> str | None:
        """Get the LLM gateway base URL (OpenAI-compatible)."""
        return os.environ.get("BASE_LLM_GATEWAY_URL")
