"""File system utilities."""

from __future__ import annotations

from pathlib import Path
from typing import Optional, Union


def resolve_path(path: Union[str, Path], cwd: Optional[Path] = None, allow_escape: bool = False) -> Path:
    """Resolve a path relative to CWD with optional containment validation.

    Args:
        path: Path to resolve
        cwd: Current working directory (defaults to os.getcwd())
        allow_escape: If False, raises ValueError when resolved path is outside cwd

    Returns:
        Resolved absolute path

    Raises:
        ValueError: If allow_escape is False and path escapes the cwd
    """
    if cwd is None:
        cwd = Path.cwd()

    p = Path(path)
    if p.is_absolute():
        resolved = p.resolve()
    else:
        resolved = (cwd / p).resolve()

    # Validate containment if not explicitly allowed to escape
    if not allow_escape:
        try:
            resolved.relative_to(cwd.resolve())
        except ValueError:
            raise ValueError(
                f"Path '{path}' resolves to '{resolved}' which is outside "
                f"the working directory '{cwd}'. Path traversal is not allowed."
            )

    return resolved


def is_binary_file(path: Path) -> bool:
    """Check if a file is binary.

    Args:
        path: Path to file

    Returns:
        True if file appears to be binary
    """
    try:
        with open(path, "rb") as f:
            chunk = f.read(1024)
            return b"\0" in chunk
    except Exception:
        return False


def read_file_safely(path: Path, max_size: int = 10 * 1024 * 1024) -> str:
    """Read a file safely with size limit.

    Args:
        path: Path to file
        max_size: Maximum size in bytes

    Returns:
        File content

    Raises:
        ValueError: If file is too large or binary
    """
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")

    if not path.is_file():
        raise ValueError(f"Not a file: {path}")

    size = path.stat().st_size
    if size > max_size:
        raise ValueError(f"File too large: {size} bytes (max {max_size})")

    if is_binary_file(path):
        raise ValueError("File appears to be binary")

    return path.read_text(encoding="utf-8", errors="replace")
