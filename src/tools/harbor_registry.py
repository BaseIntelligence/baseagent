"""Harbor tool bridge for running BaseAgent inside agent-challenge submissions."""

from __future__ import annotations

import asyncio
import base64
import inspect
import posixpath
import textwrap
import time
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Optional

from src.tools.base import ToolResult
from src.tools.registry import ExecutorConfig, ToolRegistry

DEFAULT_HARBOR_CWD = "/app"
AGENT_MOUNT = "/workspace/agent"


@dataclass
class HarborExecResult:
    output: str
    exit_code: int = 0

    @property
    def success(self) -> bool:
        return self.exit_code == 0


class HarborAgentContext:
    """Synchronous context facade backed by Harbor's async BaseEnvironment."""

    def __init__(
        self,
        instruction: str,
        environment: Any,
        loop: asyncio.AbstractEventLoop,
        cwd: str = DEFAULT_HARBOR_CWD,
        env: Optional[dict[str, str]] = None,
    ) -> None:
        self.instruction = instruction
        self.environment = environment
        self.loop = loop
        self.cwd = cwd or DEFAULT_HARBOR_CWD
        self.env = dict(env or {})
        self.step = 0
        self.is_done = False
        self.history: list[dict[str, Any]] = []
        self._start_time = time.time()

    @property
    def elapsed_secs(self) -> float:
        return time.time() - self._start_time

    def shell(self, cmd: str, timeout: int = 120, cwd: str | None = None) -> HarborExecResult:
        self.step += 1
        workdir = cwd or self.cwd
        result = self.exec_remote(cmd, cwd=workdir, timeout=timeout)
        self.history.append(
            {
                "step": self.step,
                "command": cmd,
                "cwd": workdir,
                "output": result.output[:1000],
                "exit_code": result.exit_code,
            }
        )
        return result

    def exec_remote(self, command: str, cwd: str | None = None, timeout: int = 120) -> HarborExecResult:
        workdir = cwd or self.cwd
        future = asyncio.run_coroutine_threadsafe(self._exec_async(command, workdir, timeout), self.loop)
        return future.result(timeout=max(timeout + 5, 10))

    async def _exec_async(self, command: str, cwd: str, timeout: int) -> HarborExecResult:
        exec_fn = self.environment.exec
        attempts = (
            ((command,), {"cwd": cwd, "timeout": timeout}),
            ((command,), {"cwd": cwd, "timeout_sec": timeout}),
            ((command,), {"workdir": cwd, "timeout": timeout}),
            ((command,), {"cwd": cwd}),
            ((command,), {}),
        )
        last_type_error: TypeError | None = None
        for args, kwargs in attempts:
            try:
                value = exec_fn(*args, **kwargs)
                if inspect.isawaitable(value):
                    value = await value
                return self._normalize_exec_result(value)
            except TypeError as exc:
                last_type_error = exc
                continue
        raise last_type_error or TypeError("environment.exec could not be called")

    def _normalize_exec_result(self, value: Any) -> HarborExecResult:
        if isinstance(value, HarborExecResult):
            return value
        if isinstance(value, str):
            return HarborExecResult(output=value, exit_code=0)
        if isinstance(value, dict):
            stdout = value.get("stdout") or value.get("output") or ""
            stderr = value.get("stderr") or ""
            exit_code = value.get("exit_code", value.get("returncode", value.get("return_code", 0)))
            if exit_code is None and "success" in value:
                exit_code = 0 if value["success"] else 1
            return HarborExecResult(output=self._join_output(stdout, stderr), exit_code=int(exit_code or 0))
        stdout = getattr(value, "stdout", None)
        output = getattr(value, "output", None)
        stderr = getattr(value, "stderr", None)
        exit_code = getattr(value, "exit_code", None)
        if exit_code is None:
            exit_code = getattr(value, "returncode", None)
        if exit_code is None:
            exit_code = getattr(value, "return_code", None)
        if exit_code is None and hasattr(value, "success"):
            exit_code = 0 if bool(getattr(value, "success")) else 1
        return HarborExecResult(
            output=self._join_output(stdout if stdout is not None else output, stderr),
            exit_code=int(exit_code or 0),
        )

    @staticmethod
    def _join_output(stdout: Any, stderr: Any) -> str:
        text = "" if stdout is None else str(stdout)
        err = "" if stderr is None else str(stderr)
        if err:
            text = f"{text}\n{err}" if text else err
        return text

    def done(self) -> None:
        self.is_done = True

    def log(self, msg: str) -> None:
        print(f"[harbor-context] {msg}", flush=True)


class HarborToolRegistry(ToolRegistry):
    """Tool registry that executes task-facing operations through Harbor."""

    def __init__(
        self,
        harbor_context: HarborAgentContext,
        cwd: str = DEFAULT_HARBOR_CWD,
        config: ExecutorConfig | None = None,
    ) -> None:
        super().__init__(cwd=Path(cwd), config=config or ExecutorConfig(cache_enabled=False))
        self.harbor_context = harbor_context
        self.cwd = Path(cwd)

    def _execute_shell(self, ctx: HarborAgentContext, cwd: Path, args: dict[str, Any]) -> ToolResult:
        command = args.get("command", "")
        if not command:
            return _fail("No command provided")
        timeout_ms = int(args.get("timeout_ms", 60000) or 60000)
        timeout_sec = max(1, timeout_ms // 1000)
        workdir = self._resolve_path(str(args.get("workdir") or cwd))
        if _is_agent_mount(workdir):
            return _fail(f"Refusing to run task command in agent mount: {workdir}")
        result = ctx.shell(command, timeout=timeout_sec, cwd=workdir)
        return ToolResult(success=result.success, output=result.output, error=None if result.success else result.output)

    def _execute_read_file(self, cwd: Path, args: dict[str, Any]) -> ToolResult:
        file_path = args.get("file_path", "")
        if not file_path:
            return _fail("No file_path provided")
        path = self._resolve_task_path(file_path)
        offset = max(1, int(args.get("offset", 1) or 1))
        limit = max(0, int(args.get("limit", 2000) or 2000))
        script = f"""
from pathlib import Path
path = Path({path!r})
if not path.exists():
    raise SystemExit(f"File not found: {{path}}")
if not path.is_file():
    raise SystemExit(f"Not a file: {{path}}")
lines = path.read_text(encoding='utf-8', errors='replace').splitlines()
start = max(0, {offset} - 1)
end = start + {limit}
for number, line in enumerate(lines[start:end], start=start + 1):
    print(f"L{{number}}: {{line}}")
if len(lines) > end:
    print(f"\\n[... {{len(lines) - end}} more lines ...]")
"""
        return self._run_python(script)

    def _execute_write_file(self, cwd: Path, args: dict[str, Any]) -> ToolResult:
        file_path = args.get("file_path", "")
        if not file_path:
            return _fail("No file_path provided")
        path = self._resolve_task_path(file_path)
        encoded = base64.b64encode(str(args.get("content", "")).encode("utf-8")).decode("ascii")
        script = f"""
import base64
from pathlib import Path
path = Path({path!r})
content = base64.b64decode({encoded!r}).decode('utf-8')
path.parent.mkdir(parents=True, exist_ok=True)
path.write_text(content, encoding='utf-8')
print(f"Wrote {{len(content)}} bytes to {{path}}")
"""
        return self._run_python(script)

    def _execute_list_dir(self, cwd: Path, args: dict[str, Any]) -> ToolResult:
        dir_path = args.get("dir_path", args.get("path", "."))
        path = self._resolve_task_path(str(dir_path))
        depth = max(0, int(args.get("depth", 2) or 2))
        limit = max(1, int(args.get("limit", 50) or 50))
        offset = max(1, int(args.get("offset", 1) or 1))
        script = f"""
from pathlib import Path
base = Path({path!r})
if not base.exists():
    raise SystemExit(f"Directory not found: {{base}}")
if not base.is_dir():
    raise SystemExit(f"Not a directory: {{base}}")
entries = []
def walk(current, current_depth):
    if current_depth > {depth} or len(entries) >= {limit + offset - 1}:
        return
    for item in sorted(current.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
        if len(entries) >= {limit + offset - 1}:
            break
        rel = item.relative_to(base)
        if item.is_dir():
            entries.append(str(rel) + '/')
            walk(item, current_depth + 1)
        elif item.is_symlink():
            entries.append(str(rel) + '@')
        else:
            entries.append(str(rel))
walk(base, 0)
selected = entries[{offset - 1}:{offset - 1 + limit}]
if selected:
    print('\\n'.join(selected))
else:
    print('(empty directory)')
if len(entries) > {offset - 1 + limit}:
    print(f"\\n[... {{len(entries) - ({offset - 1 + limit})}} more entries ...]")
"""
        return self._run_python(script)

    def _execute_grep(self, ctx: HarborAgentContext, cwd: Path, args: dict[str, Any]) -> ToolResult:
        pattern = args.get("pattern", "")
        if not pattern:
            return _fail("No pattern provided")
        search_path = self._resolve_task_path(str(args.get("path", ".") or "."))
        include = args.get("include") or ""
        limit = max(1, int(args.get("limit", 100) or 100))
        script = f"""
import subprocess
cmd = ['rg', '-l', '--color=never']
if {include!r}:
    cmd.extend(['-g', {include!r}])
cmd.extend([{pattern!r}, {search_path!r}])
result = subprocess.run(cmd, cwd={str(self.cwd)!r}, capture_output=True, text=True, timeout=30)
files = [line for line in result.stdout.splitlines() if line]
if files:
    print('\\n'.join(files[:{limit}]))
    if len(files) > {limit}:
        print(f"\\n[... {{len(files) - {limit}}} more files ...]")
elif result.returncode in (0, 1):
    print('No matches found')
else:
    raise SystemExit(result.stderr or f'rg failed with exit code {{result.returncode}}')
"""
        return self._run_python(script)

    def _execute_apply_patch(self, cwd: Path, args: dict[str, Any]) -> ToolResult:
        patch = args.get("patch", "")
        if not patch:
            return _fail("No patch provided")
        encoded = base64.b64encode(patch.encode("utf-8")).decode("ascii")
        script = _REMOTE_PATCH_SCRIPT.replace('__PATCH_B64__', encoded).replace('__CWD__', str(self.cwd))
        return self._run_python(script)

    def _execute_view_image(self, cwd: Path, args: dict[str, Any]) -> ToolResult:
        return _fail("view_image is unsupported in Harbor remote execution")

    def _run_python(self, script: str) -> ToolResult:
        command = "python3 - <<'PY'\n" + textwrap.dedent(script).strip() + "\nPY"
        result = self.harbor_context.exec_remote(command, cwd=str(self.cwd), timeout=120)
        if result.success:
            return ToolResult.ok(result.output.strip())
        return _fail(result.output.strip() or "Remote command failed")

    def _resolve_task_path(self, path: str) -> str:
        resolved = self._resolve_path(path)
        if _is_agent_mount(resolved):
            raise ValueError(f"Refusing to operate on agent mount path: {resolved}")
        return resolved

    def _resolve_path(self, path: str) -> str:
        posix_path = PurePosixPath(path)
        if posix_path.is_absolute():
            resolved = posixpath.normpath(str(posix_path))
        else:
            resolved = posixpath.normpath(posixpath.join(str(self.cwd), str(posix_path)))
        return resolved or str(self.cwd)


def _is_agent_mount(path: str) -> bool:
    normalized = posixpath.normpath(path)
    return normalized == AGENT_MOUNT or normalized.startswith(AGENT_MOUNT + "/")


def _fail(message: str) -> ToolResult:
    return ToolResult(success=False, output=f"Error: {message}", error=message)


_REMOTE_PATCH_SCRIPT = r'''
import base64
from pathlib import Path

patch = base64.b64decode('__PATCH_B64__').decode('utf-8')
cwd = Path('__CWD__')


def resolve(path):
    target = Path(path)
    if not target.is_absolute():
        target = cwd / target
    resolved = target.resolve()
    agent_mount = Path('/workspace/agent')
    try:
        resolved.relative_to(agent_mount)
    except ValueError:
        return resolved
    raise SystemExit(f'Refusing to operate on agent mount path: {resolved}')


def split_ops(text):
    lines = text.splitlines()
    ops = []
    current = None
    body = []
    for line in lines:
        if line.startswith('*** Add File: '):
            if current:
                ops.append((current[0], current[1], body))
            current = ('add', line.split(': ', 1)[1].strip())
            body = []
        elif line.startswith('*** Update File: '):
            if current:
                ops.append((current[0], current[1], body))
            current = ('update', line.split(': ', 1)[1].strip())
            body = []
        elif line.startswith('*** Delete File: '):
            if current:
                ops.append((current[0], current[1], body))
            current = ('delete', line.split(': ', 1)[1].strip())
            body = []
        elif line.startswith('*** End Patch'):
            if current:
                ops.append((current[0], current[1], body))
                current = None
                body = []
        elif line.startswith('*** Begin Patch'):
            continue
        elif current:
            body.append(line)
    if current:
        ops.append((current[0], current[1], body))
    return ops


def apply_update(path, body):
    lines = path.read_text(encoding='utf-8').splitlines()
    cursor = 0
    changed = False
    hunk = []
    hunks = []
    for line in body:
        if line.startswith('@@'):
            if hunk:
                hunks.append(hunk)
            hunk = []
        elif hunk is not None and line[:1] in (' ', '+', '-'):
            hunk.append(line)
    if hunk:
        hunks.append(hunk)
    for hunk in hunks:
        old = [line[1:] for line in hunk if line.startswith((' ', '-'))]
        new = [line[1:] for line in hunk if line.startswith((' ', '+'))]
        found = -1
        max_start = len(lines) - len(old)
        for index in range(cursor, max_start + 1):
            if lines[index:index + len(old)] == old:
                found = index
                break
        if found < 0:
            raise SystemExit(f'Patch context not found in {path}')
        lines[found:found + len(old)] = new
        cursor = found + len(new)
        changed = True
    if changed:
        path.write_text('\n'.join(lines) + ('\n' if lines else ''), encoding='utf-8')
    return changed

ops = split_ops(patch)
if not ops:
    raise SystemExit('No valid operations in patch')
reports = []
for kind, raw_path, body in ops:
    path = resolve(raw_path)
    if kind == 'add':
        content = '\n'.join(line[1:] if line.startswith('+') else line for line in body)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content + ('\n' if content else ''), encoding='utf-8')
        reports.append(f'Added {path}')
    elif kind == 'delete':
        path.unlink()
        reports.append(f'Deleted {path}')
    elif kind == 'update':
        apply_update(path, body)
        reports.append(f'Updated {path}')
print('\n'.join(reports))
'''
