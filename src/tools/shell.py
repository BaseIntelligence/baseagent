"""Shell command tool for SuperAgent."""

from __future__ import annotations

import os
import platform
import subprocess
from pathlib import Path
from typing import Optional

from src.tools.base import BaseTool, ToolResult


class ShellCommandTool(BaseTool):
    """Tool for executing shell commands."""

    name = "shell_command"
    description = "Runs a shell command and returns its output."

    # Default timeout in milliseconds
    DEFAULT_TIMEOUT_MS = 30000

    # Maximum output size
    MAX_OUTPUT_SIZE = 100000  # 100KB

    def __init__(self, cwd: Path, timeout_ms: int = DEFAULT_TIMEOUT_MS):
        """Initialize the shell command tool.

        Args:
            cwd: Working directory
            timeout_ms: Default timeout in milliseconds
        """
        super().__init__(cwd)
        self.default_timeout_ms = timeout_ms

    def _get_shell(self) -> tuple[str, list[str]]:
        """Get the shell and shell arguments for the current platform.

        Returns:
            Tuple of (shell executable, shell arguments)
        """
        if platform.system() == "Windows":
            # Use PowerShell on Windows
            return "powershell.exe", ["-NoProfile", "-Command"]
        else:
            # Use bash on Unix with login shell
            shell = os.environ.get("SHELL", "/bin/bash")
            return shell, ["-lc"]

    def _build_safe_env(self) -> dict:
        """Build a safe environment for command execution.

        Returns a minimal environment that excludes sensitive variables
        while preserving necessary ones for command execution.
        """
        # Allowlist of safe environment variables to pass through
        safe_vars = {
            # Essential system variables
            "PATH",
            "HOME",
            "USER",
            "SHELL",
            "LANG",
            "LC_ALL",
            "LC_CTYPE",
            "TERM",
            "PWD",
            "TMPDIR",
            "TMP",
            "TEMP",
            # Development tools
            "EDITOR",
            "VISUAL",
            "PAGER",
            # Python-related
            "PYTHONPATH",
            "PYTHONHOME",
            "VIRTUAL_ENV",
            # Git-related (non-sensitive)
            "GIT_AUTHOR_NAME",
            "GIT_AUTHOR_EMAIL",
            "GIT_COMMITTER_NAME",
            "GIT_COMMITTER_EMAIL",
        }

        # Build environment with only safe variables
        safe_env = {}
        for var in safe_vars:
            if var in os.environ:
                safe_env[var] = os.environ[var]

        # Override TERM to disable color codes
        safe_env["TERM"] = "dumb"

        return safe_env

    def execute(
        self,
        command: str,
        workdir: Optional[str] = None,
        timeout_ms: Optional[int] = None,
    ) -> ToolResult:
        """Execute a shell command.

        Args:
            command: The command to execute
            workdir: Working directory (defaults to cwd)
            timeout_ms: Timeout in milliseconds

        Returns:
            ToolResult with command output
        """
        # Resolve working directory
        if workdir:
            work_path = self.resolve_path(workdir)
        else:
            work_path = self.cwd

        if not work_path.exists():
            return ToolResult.fail(f"Working directory does not exist: {work_path}")

        # Get timeout
        timeout_s = (timeout_ms or self.default_timeout_ms) / 1000

        # Build command
        shell, shell_args = self._get_shell()

        try:
            # Run the command with a safe environment (no sensitive variables)
            result = subprocess.run(
                [shell, *shell_args, command],
                cwd=str(work_path),
                capture_output=True,
                text=True,
                timeout=timeout_s,
                env=self._build_safe_env(),
            )

            # Combine stdout and stderr
            output_parts = []

            if result.stdout:
                stdout = result.stdout
                if len(stdout) > self.MAX_OUTPUT_SIZE:
                    stdout = stdout[: self.MAX_OUTPUT_SIZE] + "\n... (output truncated)"
                output_parts.append(stdout)

            if result.stderr:
                stderr = result.stderr
                if len(stderr) > self.MAX_OUTPUT_SIZE:
                    stderr = stderr[: self.MAX_OUTPUT_SIZE] + "\n... (stderr truncated)"
                if output_parts:
                    output_parts.append(f"\nstderr:\n{stderr}")
                else:
                    output_parts.append(stderr)

            output = "".join(output_parts).strip()

            # Add exit code info if non-zero
            if result.returncode != 0:
                output = (
                    f"{output}\n\nExit code: {result.returncode}"
                    if output
                    else f"Exit code: {result.returncode}"
                )

            if not output:
                output = "(no output)"

            # Return result based on exit code
            if result.returncode == 0:
                return ToolResult.ok(output)
            else:
                return ToolResult.ok(
                    output
                )  # Still "ok" - we return the output even on non-zero exit

        except subprocess.TimeoutExpired:
            return ToolResult.fail(
                f"Command timed out after {timeout_s}s",
                output="(command killed due to timeout)",
            )
        except FileNotFoundError:
            return ToolResult.fail(f"Shell not found: {shell}")
        except PermissionError:
            return ToolResult.fail(f"Permission denied executing: {command}")
        except Exception as e:
            return ToolResult.fail(f"Failed to execute command: {e}")
