"""Public process-isolated execution APIs."""

from __future__ import annotations

import multiprocessing
from multiprocessing.connection import Connection
from multiprocessing.process import BaseProcess
from typing import Callable

from .policy import Permissions
from .process_control import (
    PROCESS_JOIN_TIMEOUT_SECONDS,
    await_worker_response,
    finalize_process,
    spawn_context_process,
)
from .process_protocol import (
    PERSISTENT_OP_CLOSE,
    PERSISTENT_OP_EXEC,
    PERSISTENT_OP_RESET,
)
from .process_worker import (
    apply_worker_response_to_user_vars,
    run_persistent_isolated_worker,
)

__all__ = [
    "WorkerSession",
]

def _start_worker_process(
    *,
    target: Callable[..., None],
    kwargs_builder: Callable[[Connection], dict[str, object]],
    duplex: bool,
) -> tuple[Connection, BaseProcess]:
    """Create and start a worker process with a connected IPC pipe."""
    ctx = multiprocessing.get_context("spawn")
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


class WorkerSession:
    """Long-lived worker executor for one `SafeSession` instance."""

    def __init__(
        self,
        *,
        perms: Permissions,
        user_vars: dict[str, object],
    ):
        self._perms = perms
        self._user_vars = user_vars
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
        """Start worker if it is not already running."""
        if self.is_open:
            return

        parent_conn, process = _start_worker_process(
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
        """Close worker and release process resources."""
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

    def exec(self, code: str) -> object | None:
        """Execute one snippet through the worker."""
        response = self._request({"op": PERSISTENT_OP_EXEC, "code": code})
        return apply_worker_response_to_user_vars(response, self._user_vars)

    def reset(self) -> None:
        """Clear worker and local user variable state."""
        response = self._request({"op": PERSISTENT_OP_RESET, "user_vars": {}})
        apply_worker_response_to_user_vars(response, self._user_vars)

    def _request(self, command: dict[str, object]) -> object:
        """Send command to worker and return response payload."""
        if not self.is_open:
            raise RuntimeError("Worker session is not open.")

        assert self._parent_conn is not None
        assert self._process is not None

        try:
            self._parent_conn.send(command)
            return await_worker_response(
                self._parent_conn,
                self._process,
                timeout=self._perms.timeout_seconds
            )
        except TimeoutError:
            raise
        except Exception as exc:  # noqa: BLE001
            self.close()
            raise RuntimeError(f"Worker session failed: {exc}") from exc
