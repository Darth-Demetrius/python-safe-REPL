"""Minimal Linux-only sandbox helpers for memory limiting.

This module provides small helpers to:
- detect and create simple cgroup v2 subtrees under /sys/fs/cgroup
- add a PID to a cgroup v2 `cgroup.procs`
- decorate worker callables with `with_limits(...)` to apply `RLIMIT_AS`
    in the child process
- attach started worker PIDs to cgroups as a best-effort parent-side step

This file intentionally assumes Linux and cgroup v2; it does not attempt to
manage permissions or delegated subtrees — the caller should handle admin
delegation if required.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Optional

__all__ = [
    "cgroup_v2_available",
    "create_cgroup_v2",
    "add_pid_to_cgroup",
    "remove_cgroup",
    "try_attach_pid_to_cgroup",
    "attach_pid_to_cgroup",
    "with_limits",
]


def cgroup_v2_available() -> bool:
    """Return True if cgroup v2 unified hierarchy appears present."""
    cg = Path("/sys/fs/cgroup")
    return (cg / "cgroup.controllers").exists()


def create_cgroup_v2(name: str, memory_max_bytes: Optional[int] = None) -> Path:
    """Create a cgroup v2 directory and optionally set `memory.max`.

    Caller must have permission to write under `/sys/fs/cgroup` (root or
    delegated subtree). Raises RuntimeError if cgroup v2 not available.
    """
    base = Path("/sys/fs/cgroup")
    if not (base / "cgroup.controllers").exists():
        raise RuntimeError("cgroup v2 not available on this system")

    cg = base / name
    cg.mkdir(mode=0o755, exist_ok=True)

    if memory_max_bytes is not None:
        (cg / "memory.max").write_text(str(memory_max_bytes))

    return cg


def add_pid_to_cgroup(cg_path: Path, pid: int) -> None:
    """Write `pid` into the cgroup's `cgroup.procs` file."""
    procs = cg_path / "cgroup.procs"
    procs.write_text(f"{pid}\n")


def remove_cgroup(cg_path: Path) -> None:
    """Attempt to remove an empty cgroup directory (raises on failure)."""
    cg_path.rmdir()


def try_attach_pid_to_cgroup(name: str, pid: int, memory_max_bytes: Optional[int] = None) -> Optional[Path]:
    """Best-effort: create a cgroup and add `pid` to it.

    Returns the cgroup Path on success or `None` on any failure (permissions,
    missing cgroup v2, etc.). This allows callers to attempt cgroup
    enforcement and fall back to other techniques on failure.
    """
    try:
        cg = create_cgroup_v2(name, memory_max_bytes)
        add_pid_to_cgroup(cg, pid)
        return cg
    except Exception:
        return None


def attach_pid_to_cgroup(pid: int, memory_max_bytes: Optional[int], name_prefix: str = "safe_repl") -> Optional[Path]:
    """Convenience wrapper to attach `pid` to a cgroup named `<prefix>/<pid>`.

    Returns the cgroup Path on success or `None` on failure.
    """
    if memory_max_bytes is None:
        return None
    try:
        name = f"{name_prefix}/{pid}"
        return try_attach_pid_to_cgroup(name, pid, memory_max_bytes)
    except Exception:
        return None


def with_limits(memory_bytes: Optional[int]):
    """Decorator factory that applies `RLIMIT_AS` in the child.

    Usage:
        @with_limits(100*1024*1024)
        def worker(...):
            ...

    The decorator is minimal and only sets `RLIMIT_AS` before invoking the
    wrapped function; cgroup attachment must still be done by the parent
    after process start using `attach_pid_to_cgroup`.
    """

    def decorator(func: Callable[..., None]) -> Callable[..., None]:
        if memory_bytes is None:
            return func

        mem_value = int(memory_bytes)

        def _wrapped(*args, **kwargs):
            try:
                import resource

                soft = hard = mem_value
                resource.setrlimit(resource.RLIMIT_AS, (soft, hard))
            except Exception:
                pass
            return func(*args, **kwargs)

        return _wrapped

    return decorator
