"""Stateful session orchestration for the RestrictedPython REPL.

``SafeSession`` is the primary integration point for embedding the REPL in
other applications, including Discord bots.

Key differences from the original ``safe_repl.session``
---------------------------------------------------------
* **No subprocess / worker process.**  Execution happens in-process via
  ``ResPy_engine.exec_restricted``, using RestrictedPython's compile-time
  code transformation and thread-based timeout.
* **``exec()`` returns ``(result, output)``** — the caller decides what to do
  with the output (print it, send it to Discord, etc.).  No stdout side-effects.
* **``async_exec()``** wraps the synchronous ``exec()`` in
  ``asyncio.to_thread`` + ``asyncio.wait_for`` so it is safe to ``await``
  directly from a Discord bot command handler without blocking the event loop.
* **``repl()``** provides a minimal interactive CLI loop for local testing.
"""

from __future__ import annotations

import argparse
import contextlib
import io
from collections.abc import Callable, Mapping
import pickle
import cloudpickle

from .engine import ExecResult, exec_restricted
from .imports import NormalizedImportSpec, normalize_validate_imports
from .policy import PermissionLevel, Permissions
from .repl_command_registry import CommandRegistry


class SafeSession:
    """Stateful execution wrapper for policy, user variables, and REPL lifecycle.

    Args:
        perms: Execution policy (permission level, builtins, imports, limits).
        user_vars: Initial variable namespace.  Mutated in-place on each exec.
        command_char: Prefix character that triggers REPL command dispatch.
        repl_commands: Optional custom command registry; defaults to the
            built-in ``CommandRegistry``.
    """

    def __init__(
        self,
        perms: Permissions,
        user_vars: dict[str, object] | None = None,
        *,
        command_char: str = ":",
        repl_commands: CommandRegistry | None = None,
    ) -> None:
        self.perms = perms
        self.user_vars: dict[str, object] = user_vars or {}
        self.command_char = command_char
        self.command_registry = repl_commands or CommandRegistry()
        self._cache_startup_summaries()

    # ------------------------------------------------------------------
    # Serialisation / relaunch
    # ------------------------------------------------------------------

    _CLOUDPICKLE_MARKER: str = "__respy_cloudpickle__"

    def to_relaunch_data(self) -> dict[str, object]:
        """Return a picklable payload re-creating this session.

        Only relaunch-safe state is included: permissions, user variables,
        and the command prefix.  Live handles (threads, etc.) are excluded.

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
            "command_char": self.command_char,
        }

    @classmethod
    def from_relaunch_data(
        cls,
        payload: Mapping[str, object],
        *,
        repl_commands: CommandRegistry | None = None,
    ) -> "SafeSession":
        """Rebuild a session from ``to_relaunch_data`` output.

        Args:
            payload: Serialised session payload.
            repl_commands: Optional command registry override.

        Returns:
            A reconstructed ``SafeSession``.
        """
        perms_payload = payload["perms"]
        user_vars_raw = payload.get("user_vars", {})
        command_char = payload.get("command_char", ":")

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
        command_char = command_char if isinstance(command_char, str) else ":"

        return cls(
            perms=Permissions.from_relaunch_data(perms_payload),  # type: ignore[arg-type]
            user_vars=user_vars,
            command_char=command_char,
            repl_commands=repl_commands,
        )

    def __getstate__(self) -> dict[str, object]:
        return self.to_relaunch_data()

    def __setstate__(self, state: Mapping[str, object]) -> None:
        restored = self.from_relaunch_data(state)
        self.__dict__.update(restored.__dict__)

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------

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
        outcome: ExecResult = exec_restricted(code, self.user_vars, perms=self.perms)
        if not outcome.ok:
            assert outcome.exception is not None
            raise outcome.exception
        return outcome.result, outcome.output

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
                session's ``perms.timeout_seconds`` if not specified (using a
                generous 1.5× multiplier to allow the in-thread mechanism to
                fire first).  Pass ``None`` to disable the asyncio-level guard.

        Returns:
            A ``(result, output)`` tuple (same as ``exec``).

        Raises:
            ``TimeoutError``: When either the in-thread or asyncio timeout fires.
            Any exception raised by within the user's code.
        """
        import asyncio

        # Give the in-thread timeout a chance to fire before the asyncio one.
        if timeout is None and self.perms.timeout_seconds is not None:
            timeout = self.perms.timeout_seconds * 1.5

        coro = asyncio.to_thread(self.exec, code)
        if timeout is not None:
            return await asyncio.wait_for(coro, timeout=timeout)
        return await coro

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
            self.command_registry.show_help(cmd_char=self.command_char)
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
            if line.startswith(self.command_char):
                cmd_line = line.removeprefix(self.command_char)
                output_buf = io.StringIO()
                with contextlib.redirect_stdout(output_buf):
                    dispatched = self.command_registry.dispatch(cmd_line, session=self)
                out = output_buf.getvalue()
                if out:
                    print(out, end="")
                if dispatched:
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
