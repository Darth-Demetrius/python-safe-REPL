"""Public process-isolated execution APIs."""

from __future__ import annotations
import multiprocessing
from multiprocessing.connection import Connection
from multiprocessing.process import BaseProcess
from typing import Final

from .policy import Permissions
from .process_protocol import (
    OP_CLOSE,
    OP_EXEC,
    OP_RESET,
    WorkerResponse,
    open_response_payload,
)
from .process_worker import (
    run_persistent_isolated_worker,
)

PROCESS_JOIN_TIMEOUT_SECONDS: Final[float] = 0.2


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

        ctx = multiprocessing.get_context("spawn")
        self._parent_conn, child_conn = ctx.Pipe(duplex=True)

        process_factory = getattr(ctx, "Process", None)
        if process_factory is None:
            raise RuntimeError("Multiprocessing context does not provide a Process factory.")

        self._process = process_factory(
            target=run_persistent_isolated_worker,
            kwargs={
                "conn": child_conn,
                "initial_user_vars": dict(self._user_vars),
                "perms": self._perms,
            },
            daemon=True
        )
        if not isinstance(self._process, BaseProcess):
            raise RuntimeError("Multiprocessing context returned unsupported process type.")

        self._process.start()
        child_conn.close()

    def finalize(self, *, terminate: bool = False) -> None:
        process = self._process
        if process is None:
            return
        if terminate:
            process.terminate()

        process.join(timeout=PROCESS_JOIN_TIMEOUT_SECONDS)
        if process.is_alive():
            process.kill()
            process.join(timeout=PROCESS_JOIN_TIMEOUT_SECONDS)

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
                    parent_conn.send({"op": OP_CLOSE})
                    if parent_conn.poll(PROCESS_JOIN_TIMEOUT_SECONDS):
                        parent_conn.recv()
                except Exception:
                    pass
        finally:
            if parent_conn is not None:
                parent_conn.close()
            self.finalize()

    def exec(self, code: str) -> WorkerResponse:
        """Execute one snippet through the worker and return the normalized payload."""
        response = self._request({"op": OP_EXEC, "code": code})
        self._user_vars.clear()
        self._user_vars.update(response["user_vars"])
        return response

    def reset(self) -> None:
        """Clear worker and local user variable state."""
        response = self._request({"op": OP_RESET, "user_vars": {}})
        self._user_vars.clear()
        self._user_vars.update(response["user_vars"])

    def _request(self, command: dict[str, object]) -> WorkerResponse:
        """Send command to worker and return response payload."""
        if not self.is_open:
            raise RuntimeError("Worker session is not open.")

        assert self._parent_conn is not None
        assert self._process is not None

        try:
            self._parent_conn.send(command)
            if self._parent_conn.poll(self._perms.timeout_seconds):
                return open_response_payload(self._parent_conn.recv())
            self.finalize(terminate=True)
            raise TimeoutError("Execution timed out.")
        except TimeoutError:
            raise
        except Exception as exc:
            self.close()
            raise RuntimeError(f"Worker session failed: {exc}") from exc
