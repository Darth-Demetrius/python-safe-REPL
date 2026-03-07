"""Execution mode selection and high-level dispatch.

This module intentionally stays small and focused:
- normalize execution-mode input
- route execution to in-process vs subprocess backends
- coordinate optional persistent subprocess session usage

Process runtime mechanics (IPC protocol, workers, lifecycle) live in
`safe_repl.process_isolation`.
"""

from __future__ import annotations

from enum import Enum

from .engine import safe_exec
from .policy import Permissions
from .process_isolation import (
    PersistentSubprocessSession,
    safe_exec_process_isolated,
    supports_process_isolation,
)


class ExecutionMode(str, Enum):
    """Supported execution backends for code evaluation."""

    IN_PROCESS = "in-process"
    PROCESS = "process"

    @classmethod
    def __missing__(cls, value: object) -> "ExecutionMode | None":
        """Normalize common string variants for robust parsing."""
        if not isinstance(value, str):
            return None
        normalized = value.strip().lower().replace("_", "-")
        if normalized in {"inprocess", "in-proc", "inproc"}:
            normalized = cls.IN_PROCESS.value
        elif normalized in {"proc", "subprocess", "sub-process"}:
            normalized = cls.PROCESS.value
        for mode in cls:
            if normalized in {mode.value, mode.name.lower().replace("_", "-")}:
                return mode
        return None

    @classmethod
    def default(cls) -> "ExecutionMode":
        """Return default execution mode for sessions and CLI."""
        return cls.PROCESS

    @classmethod
    def choices(cls) -> tuple[str, ...]:
        """Return CLI-friendly choices for execution mode flags."""
        return tuple(mode.value for mode in cls)


ExecutionModeInput = ExecutionMode | str
ExecutionModeOverride = ExecutionModeInput | None


def coerce_execution_mode(
    mode: ExecutionModeInput | None,
    *,
    fallback: ExecutionModeInput | None = None,
) -> ExecutionMode:
    """Normalize optional execution mode input to `ExecutionMode`."""
    candidate = mode if mode is not None else fallback
    if candidate is None:
        return ExecutionMode.default()
    if isinstance(candidate, ExecutionMode):
        return candidate
    try:
        return ExecutionMode(candidate)
    except ValueError as exc:
        options = ", ".join(ExecutionMode.choices())
        raise ValueError(
            f"Invalid execution mode '{candidate}'. Use one of: {options}."
        ) from exc


def uses_persistent_process(mode: ExecutionMode) -> bool:
    """Return true when mode should use persistent process lifecycle."""
    return mode is ExecutionMode.PROCESS


def execute_snippet(
    mode: ExecutionMode,
    code: str,
    user_vars: dict[str, object],
    *,
    perms: Permissions,
) -> object | None:
    """Execute one snippet using the selected execution backend."""
    if mode is ExecutionMode.PROCESS:
        return safe_exec_process_isolated(code, user_vars, perms=perms)
    return safe_exec(code, user_vars, perms=perms)


def dispatch_execution(
    *,
    mode: ExecutionMode,
    code: str,
    user_vars: dict[str, object],
    perms: Permissions,
    persistent_session: PersistentSubprocessSession | None = None,
) -> object | None:
    """Execute code via persistent worker when available, else direct backend."""
    if uses_persistent_process(mode) and persistent_session is not None:
        return persistent_session.exec(code)
    return execute_snippet(mode, code, user_vars, perms=perms)


def reset_execution_state(
    user_vars: dict[str, object],
    *,
    persistent_session: PersistentSubprocessSession | None = None,
) -> None:
    """Reset local state and sync persistent worker state when present."""
    user_vars.clear()
    if persistent_session is not None:
        persistent_session.reset()


__all__ = (
    "ExecutionMode",
    "ExecutionModeInput",
    "ExecutionModeOverride",
    "coerce_execution_mode",
    "uses_persistent_process",
    "PersistentSubprocessSession",
    "safe_exec_process_isolated",
    "supports_process_isolation",
    "execute_snippet",
    "dispatch_execution",
    "reset_execution_state",
)
