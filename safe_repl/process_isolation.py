"""Public process-isolated execution APIs."""

from __future__ import annotations

import multiprocessing
from multiprocessing.connection import Connection
from multiprocessing.process import BaseProcess
from typing import Callable

from .policy import Permissions
from .process_control import (
    DEFAULT_START_METHOD,
    PROCESS_JOIN_TIMEOUT_SECONDS,
    await_worker_response,
    finalize_process,
    spawn_context_process,
    supports_process_isolation,
    timeout_for_perms,
    validate_process_isolation_support,
)
from .process_protocol import PERSISTENT_OP_CLOSE, PERSISTENT_OP_EXEC, PERSISTENT_OP_RESET
from .process_worker import (
    apply_success_response_to_user_vars,
    run_isolated_worker,
    run_persistent_isolated_worker,
)


def _start_worker_process(
    *,
    start_method: str,
    target: Callable[..., None],
    kwargs_builder: Callable[[Connection], dict[str, object]],
    duplex: bool,
) -> tuple[Connection, BaseProcess]:
    """Create and start a worker process with a connected IPC pipe."""
    ctx = multiprocessing.get_context(start_method)
    parent_conn, child_conn = ctx.Pipe(duplex=duplex)
    process = spawn_context_process(
        context=ctx,
        target=target,
        kwargs=kwargs_builder(child_conn),
        daemon=True,
    )
    process.start()
    child_conn.close()
    return parent_conn, process


def safe_exec_process_isolated(
    code: str,
    user_vars: dict[str, object],
    *,
    perms: Permissions,
    start_method: str = DEFAULT_START_METHOD,
) -> object | None:
    """Execute one snippet in a child process and sync state back to caller.

    Notes:
    - This mode currently targets POSIX `fork` start method.
    - Return value and synchronized user vars must be pickle-serializable.
    """
    validate_process_isolation_support(start_method)

    parent_conn, process = _start_worker_process(
        start_method=start_method,
        target=run_isolated_worker,
        kwargs_builder=lambda child_conn: {
            "conn": child_conn,
            "code": code,
            "user_vars": user_vars,
            "perms": perms,
        },
        duplex=False,
    )

    timeout = timeout_for_perms(perms)

    try:
        response = await_worker_response(parent_conn, process, timeout=timeout)
    finally:
        parent_conn.close()
        finalize_process(process)
    return apply_success_response_to_user_vars(response, user_vars)


class PersistentSubprocessSession:
    """Long-lived subprocess-backed executor for one `SafeSession` instance."""

    def __init__(
        self,
        *,
        perms: Permissions,
        user_vars: dict[str, object],
        start_method: str = DEFAULT_START_METHOD,
    ):
        validate_process_isolation_support(start_method)

        self._perms = perms
        self._user_vars = user_vars
        self._start_method = start_method
        self._parent_conn: Connection | None = None
        self._process: BaseProcess | None = None

    @property
    def is_open(self) -> bool:
        """Return true when worker process and control pipe are active."""
        return (
            self._process is not None
            and self._process.is_alive()
            and self._parent_conn is not None
        )

    def open(self) -> None:
        """Start persistent worker if it is not already running."""
        if self.is_open:
            return

        parent_conn, process = _start_worker_process(
            start_method=self._start_method,
            target=run_persistent_isolated_worker,
            kwargs_builder=lambda child_conn: {
                "conn": child_conn,
                "initial_user_vars": dict(self._user_vars),
                "perms": self._perms,
            },
            duplex=True,
        )

        self._parent_conn = parent_conn
        self._process = process

    def close(self) -> None:
        """Close persistent worker and release process resources."""
        process = self._process
        parent_conn = self._parent_conn
        self._process = None
        self._parent_conn = None

        if process is None:
            if parent_conn is not None:
                parent_conn.close()
            return

        try:
            if parent_conn is not None and process.is_alive():
                try:
                    parent_conn.send({"op": PERSISTENT_OP_CLOSE})
                    if parent_conn.poll(PROCESS_JOIN_TIMEOUT_SECONDS):
                        parent_conn.recv()
                except Exception:  # noqa: BLE001
                    pass
        finally:
            if parent_conn is not None:
                parent_conn.close()
            finalize_process(process)

    def reopen(self) -> None:
        """Restart persistent worker with current local user variable state."""
        self.close()
        self.open()

    def exec(self, code: str) -> object | None:
        """Execute one snippet through the persistent worker."""
        response = self._request(
            {"op": PERSISTENT_OP_EXEC, "code": code},
            timeout=timeout_for_perms(self._perms),
        )
        return apply_success_response_to_user_vars(response, self._user_vars)

    def reset(self) -> None:
        """Clear worker and local user variable state."""
        response = self._request(
            {"op": PERSISTENT_OP_RESET, "user_vars": {}},
            timeout=timeout_for_perms(self._perms),
        )
        apply_success_response_to_user_vars(response, self._user_vars)

    def _request(self, command: dict[str, object], *, timeout: float | None) -> object:
        """Send command to worker and return response payload."""
        if not self.is_open:
            raise RuntimeError("Persistent subprocess session is not open.")

        assert self._parent_conn is not None
        assert self._process is not None

        try:
            self._parent_conn.send(command)
            return await_worker_response(self._parent_conn, self._process, timeout=timeout)
        except TimeoutError:
            raise
        except Exception as exc:  # noqa: BLE001
            self.close()
            raise RuntimeError(f"Persistent subprocess session failed: {exc}") from exc


__all__ = [
    "PersistentSubprocessSession",
    "safe_exec_process_isolated",
    "supports_process_isolation",
]
