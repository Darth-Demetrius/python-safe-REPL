"""Stateful session orchestration for the RestrictedPython REPL.

``SafeSession`` is the primary integration point for embedding the REPL in
other applications, including Discord bots.

Key differences from the original ``safe_repl.session``
---------------------------------------------------------
* **No subprocess / worker process.**  Execution happens in-process via
  ``ResPy_engine.exec_restricted``, using RestrictedPython's compile-time
  code transformation and thread-based timeout.
* **``exec()`` returns ``(result, output)``** for backward-compatible text
    flows, while ``exec_response()`` returns the full ``ExecResult`` (including
    rich display artifacts such as matplotlib images).
* **``async_exec()``** wraps the synchronous ``exec()`` in
  ``asyncio.to_thread`` + ``asyncio.wait_for`` so it is safe to ``await``
  directly from a Discord bot command handler without blocking the event loop.
* **``repl()``** provides a minimal interactive CLI loop for local testing.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import asyncio
from collections.abc import Callable, Mapping
import pickle
import cloudpickle

from .engine import DisplayArtifact, ExecResult, _code_preview, exec_restricted
from .imports import NormalizedImportSpec
from .policy import PermissionLevel, Permissions
from .repl_command_registry import CommandRegistry

class ExecutionTimeoutError(TimeoutError):
    """Timeout error carrying partial execution output.

    Attributes:
        output: Captured text output generated before timeout.
        display_artifacts: Captured rich artifacts generated before timeout.
    """

    def __init__(
        self,
        message: str,
        *,
        output: str = "",
        display_artifacts: list[DisplayArtifact] | None = None,
    ) -> None:
        super().__init__(message)
        self.output = output
        self.display_artifacts = list(display_artifacts or [])


class ExecutionMemoryLimitError(MemoryError):
    """Memory-limit error carrying partial execution output.

    Attributes:
        output: Captured text output generated before memory-limit failure.
        display_artifacts: Captured rich artifacts generated before failure.
    """

    def __init__(
        self,
        message: str,
        *,
        output: str = "",
        display_artifacts: list[DisplayArtifact] | None = None,
    ) -> None:
        super().__init__(message)
        self.output = output
        self.display_artifacts = list(display_artifacts or [])


class SafeSession:
    """Stateful execution wrapper for policy, user variables, and REPL lifecycle.

    Args:
        perms: Execution policy (permission level, builtins, imports, limits).
        user_vars: Initial variable namespace.  Mutated in-place on each exec.
        identifier: Optional host-owned identifier reserved for embedding use.
        command_registry: Optional custom command registry; defaults to the
            built-in ``CommandRegistry``.
    """

    def __init__(
        self,
        perms: Permissions,
        user_vars: dict[str, object] | None = None,
        identifier: str | None = None,
        *,
        command_registry: CommandRegistry | None = None,
    ) -> None:
        self.perms = perms
        self.user_vars: dict[str, object] = user_vars or {}
        self.command_registry = command_registry or CommandRegistry()
        self._cache_startup_summaries()

    # ------------------------------------------------------------------
    # Serialisation / relaunch
    # ------------------------------------------------------------------

    _CLOUDPICKLE_MARKER: str = "__respy_cloudpickle__"

    def to_relaunch_data(self) -> dict[str, object]:
        """Return a picklable payload re-creating this session.

        Only relaunch-safe state is included: permissions and user variables.
        Live handles and registries are excluded.

        Values that standard ``pickle`` cannot handle are encoded as
        ``{_CLOUDPICKLE_MARKER: True, "data": bytes}`` so the outer dict
        stays standard-pickle-safe.

        Returns:
            A dict suitable for ``pickle.dumps`` / ``from_relaunch_data``.
        """

        serialisable_vars: dict[str, object] = {}
        for k, v in self.user_vars.items():
            try:
                pickle.dumps(v)
                serialisable_vars[k] = v
            except Exception:
                try:
                    serialisable_vars[k] = {
                        self._CLOUDPICKLE_MARKER: True,
                        "data": cloudpickle.dumps(v),
                    }
                except Exception:
                    pass  # Skip values that can't be serialised at all.

        return {
            "perms": self.perms.to_relaunch_data(),
            "user_vars": serialisable_vars,
            #"command_registry": self.command_registry,
        }

    @classmethod
    def from_relaunch_data(cls, payload: Mapping[str, object]) -> "SafeSession":
        """Rebuild a session from ``to_relaunch_data`` output.

        Args:
            payload: Serialised session payload.

        Returns:
            A reconstructed ``SafeSession``.
        """
        perms_payload = payload["perms"]
        user_vars_raw = payload.get("user_vars", {})
        command_registry = payload.get("command_registry", None)

        if isinstance(user_vars_raw, dict):
            user_vars: dict[str, object] = {}
            for k, v in user_vars_raw.items():
                if (
                    isinstance(v, dict)
                    and v.get(cls._CLOUDPICKLE_MARKER) is True
                    and isinstance(v.get("data"), bytes)
                ):
                    try:
                        user_vars[k] = cloudpickle.loads(v["data"])
                    except Exception:
                        pass  # Drop values that fail to deserialise.
                else:
                    user_vars[k] = v
        else:
            user_vars = {}
        command_registry = command_registry if isinstance(command_registry, CommandRegistry) else None

        return cls(
            perms=Permissions.from_relaunch_data(perms_payload),  # type: ignore[arg-type]
            user_vars=user_vars,
            command_registry=command_registry,
        )

    def __getstate__(self) -> dict[str, object]:
        return self.to_relaunch_data()

    def __setstate__(self, state: Mapping[str, object]) -> None:
        restored = self.from_relaunch_data(state)
        self.__dict__.update(restored.__dict__)

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------

    def exec_response(self, code: str) -> ExecResult:
        """Execute one snippet and return the full ``ExecResult`` payload.

        Returns:
            Full execution response including result, text output, and rich
            display artifacts.

        Raises:
            The exception raised by the user's code (re-raised verbatim).
            ``SyntaxError`` when the source cannot be compiled.
            ``TimeoutError`` when the execution timeout is exceeded.
            ``MemoryError`` when the memory limit is exceeded.
        """
        outcome: ExecResult = exec_restricted(code, self.user_vars, perms=self.perms)
        if not outcome.ok:
            assert outcome.exception is not None
            if isinstance(outcome.exception, TimeoutError):
                detail = str(outcome.exception).strip()
                if not detail:
                    detail = (
                        f"Execution timed out after {self.perms.timeout_seconds:.3f}s."
                        if self.perms.timeout_seconds is not None
                        else "Execution timed out."
                    )
                preview = _code_preview(code)
                if preview:
                    detail = f"{detail} Code preview: {preview!r}."
                raise ExecutionTimeoutError(
                    detail,
                    output=outcome.output,
                    display_artifacts=outcome.display_artifacts,
                ) from outcome.exception
            if isinstance(outcome.exception, MemoryError):
                raise ExecutionMemoryLimitError(
                    str(outcome.exception),
                    output=outcome.output,
                    display_artifacts=outcome.display_artifacts,
                ) from outcome.exception
            raise outcome.exception
        return outcome

    def exec(self, code: str) -> tuple[object | None, str]:
        """Execute one snippet and return ``(result, captured_output)``.

        The ``user_vars`` dict is updated in place with any new names defined
        by the snippet, preserving state across calls.

        Args:
            code: Raw Python source string.

        Returns:
            A ``(result, output)`` tuple where *result* is the value of the
            final expression (or ``None`` for statements) and *output* is any
            text emitted by ``print()`` calls.

        Raises:
            The exception raised by the user's code (re-raised verbatim).
            ``SyntaxError`` when the source cannot be compiled.
            ``TimeoutError`` when the execution timeout is exceeded.
            ``MemoryError`` when the memory limit is exceeded.
        """
        outcome = self.exec_response(code)
        return outcome.result, outcome.output

    async def async_exec_response(
        self,
        code: str,
        *,
        timeout: float | None = None,
    ) -> ExecResult:
        """Execute one snippet asynchronously and return ``ExecResult``.

        Args:
            code: Raw Python source string.
            timeout: Optional asyncio-level timeout in seconds.  Defaults to the
                session's ``perms.timeout_seconds`` plus a grace window when
                not specified, allowing the in-thread timeout mechanism to fire
                first and preserve partial output. Pass ``None`` to disable the
                asyncio-level guard.

        Returns:
            Full execution response including rich display artifacts.

        Raises:
            ``TimeoutError``: When either the in-thread or asyncio timeout fires.
            Any exception raised by within the user's code.
        """
        if timeout is None and self.perms.timeout_seconds is not None:
            timeout = self.perms.timeout_seconds + 1.0

        coro = asyncio.to_thread(self.exec_response, code)
        task = asyncio.create_task(coro)
        if timeout is not None:
            try:
                return await asyncio.wait_for(asyncio.shield(task), timeout=timeout)
            except asyncio.TimeoutError as exc:
                # Give the in-thread timeout path a short grace period to finish
                # so callers can receive partial output/artifacts when available.
                try:
                    return await asyncio.wait_for(asyncio.shield(task), timeout=0.75)
                except asyncio.TimeoutError:
                    pass
                except Exception:
                    if task.done():
                        return task.result()

                preview = _code_preview(code)
                detail = f"Execution reached asyncio-level timeout after {timeout:.3f}s."
                if self.perms.timeout_seconds is not None:
                    detail += f" Session timeout is {self.perms.timeout_seconds:.3f}s."
                if preview:
                    detail += f" Code preview: {preview!r}."
                raise ExecutionTimeoutError(detail) from exc
        return await task

    async def async_exec(self, code: str, *, timeout: float | None = None) -> tuple[object | None, str]:
        """Execute one snippet asynchronously without blocking the event loop.

        Designed for use in Discord bot command handlers::

            result, output = await session.async_exec(user_code)
            await ctx.send(output or repr(result))

        The snippet runs in a thread-pool thread via ``asyncio.to_thread``.  An
        ``asyncio``-level timeout (independent of the per-session
        ``Permissions.timeout_seconds``) is applied via ``asyncio.wait_for``.
        If the asyncio timeout fires, the executing thread may still run briefly
        (best-effort), but the caller will receive a ``TimeoutError`` immediately.

        Args:
            code: Raw Python source string.
            timeout: Optional asyncio-level timeout in seconds.  Defaults to the
                session's ``perms.timeout_seconds`` plus a grace window when
                not specified, allowing the in-thread timeout mechanism to fire
                first. Pass ``None`` to disable the asyncio-level guard.

        Returns:
            A ``(result, output)`` tuple (same as ``exec``).

        Raises:
            ``TimeoutError``: When either the in-thread or asyncio timeout fires.
            Any exception raised by within the user's code.
        """
        outcome = await self.async_exec_response(code, timeout=timeout)
        return outcome.result, outcome.output

    def reset(self) -> None:
        """Clear all user-defined variables."""
        self.user_vars.clear()

    # ------------------------------------------------------------------
    # CLI construction helpers
    # ------------------------------------------------------------------

    @classmethod
    def from_cli_args(
        cls,
        args: argparse.Namespace,
        *,
        user_vars: dict[str, object] | None = None,
    ) -> "SafeSession":
        """Build a session from parsed CLI arguments.

        Args:
            args: ``argparse.Namespace`` from the CLI parser.
            user_vars: Optional pre-populated variable namespace.

        Returns:
            A ``SafeSession`` configured from the CLI arguments.
        """
        perms = Permissions(
            perm_level=PermissionLevel(args.level),
            imports=args.imports if args.imports is not None else ["math:*"],
            allow_symbols=set(args.allow_functions) if args.allow_functions else None,
            block_symbols=set(args.block_functions) if args.block_functions else None,
        )
        return cls(perms=perms, user_vars=user_vars)

    # ------------------------------------------------------------------
    # Interactive REPL
    # ------------------------------------------------------------------

    def repl(self) -> None:
        """Run an interactive single-line REPL loop (for local/CLI use).

        Captures and prints output produced by each execution.  For Discord
        integration use ``async_exec`` instead.
        """
        print("Type 'quit' or 'exit' to exit.")
        output_buffer = io.StringIO()
        with contextlib.redirect_stdout(output_buffer):
            self.command_registry.show_help()
        help_text = output_buffer.getvalue()
        if help_text:
            print(help_text, end="")

        self._run_repl_loop(execute=self._repl_execute)

    def _repl_execute(self, code: str) -> object | None:
        """Execute *code* and print captured output; return result for display."""
        result, output = self.exec(code)
        if output:
            print(output, end="")
        return result

    def _run_repl_loop(self, *, execute: Callable[[str], object | None]) -> None:
        """Drive the interactive input loop until the user exits."""
        while True:
            try:
                line = input("> ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\nBye")
                break

            if not line:
                continue
            if line.lower() in {"quit", "exit"}:
                print("Bye")
                break
            if self.command_registry.dispatch(line, session=self):
                continue
            try:
                result = execute(line)
                if result is not None:
                    print(repr(result))
            except Exception as error:
                print(f"Error: {type(error).__name__}: {error}")

    # ------------------------------------------------------------------
    # Diagnostic helpers
    # ------------------------------------------------------------------

    def _cache_startup_summaries(self) -> None:
        """Pre-compute static summary strings for introspection commands."""
        safe_builtins = self.perms.restricted_globals.get("__builtins__", {})
        if isinstance(safe_builtins, dict):
            self._startup_builtins = ", ".join(
                sorted(k for k in safe_builtins if not k.startswith("_"))
            )
        else:
            self._startup_builtins = ""
        self._startup_imports: NormalizedImportSpec = self.perms.imports

    def print_builtins(self) -> None:
        """Print the allowed built-in function names for this session."""
        print(f"  Builtins: {self._startup_builtins}")

    def print_imports(self) -> None:
        """Print pre-imported symbol summary for this session."""
        if self._startup_imports:
            print(f"  Imports: {self._startup_imports}")

    def print_user_vars(self, *, include_values: bool = True) -> str:
        """Print user-defined variable names, optionally with their values.

        Returns:
            The rendered string.
        """
        if not self.user_vars:
            return "User vars: (none)"

        rendered = "User vars:\n"
        rendered += "\n".join(
            f"  {name}{' = ' + repr(value) if include_values else ': ' + type(value).__name__}"
            for name, value in sorted(self.user_vars.items())
        )
        #print(rendered)
        return rendered
