"""Stateful session and interactive REPL orchestration."""

import argparse
import builtins
import contextlib
import io
from collections.abc import Callable
from collections.abc import Mapping
from typing import cast

from .policy import PermissionLevel, Permissions
from .worker_session import WorkerSession
from .process_protocol import WorkerResponse
from .repl_command_registry import CommandRegistry


ReadFunc = Callable[[str], str]
WriteFunc = Callable[[str], None]


class SafeSession:
    """Stateful execution wrapper around policy, variables, and REPL lifecycle."""

    def __init__(
        self,
        perms: Permissions,
        user_vars: dict[str, object] | None = None,
        *,
        command_char: str = ":",
        repl_commands: CommandRegistry | None = None,
        read: ReadFunc = input,
        write: WriteFunc = print,
    ):
        """Create a session with persistent variables and worker-backed execution."""
        self.perms = perms
        self.user_vars: dict[str, object] = user_vars or {}
        self.command_char = command_char
        self.command_registry = repl_commands or CommandRegistry()
        self._worker_session: WorkerSession | None = None
        self._write = write
        self._read = read
        self._cache_startup_summaries()

    def to_relaunch_data(self) -> dict[str, object]:
        """Return the minimal state required to relaunch this session.

        Returns:
            A pickle-friendly payload containing permissions, user variables,
            and command prefix configuration.
        """
        return {
            "perms": self.perms.to_relaunch_data(),
            "user_vars": dict(self.user_vars),
            "command_char": self.command_char,
        }

    @classmethod
    def from_relaunch_data(
        cls,
        payload: Mapping[str, object],
        *,
        repl_commands: CommandRegistry | None = None,
    ) -> "SafeSession":
        """Rebuild a session from ``to_relaunch_data`` output."""
        perms_payload = payload["perms"]
        user_vars_payload = payload.get("user_vars", {})
        command_char_payload = payload.get("command_char", ":")

        user_vars = dict(user_vars_payload) if isinstance(user_vars_payload, dict) else {}
        command_char = command_char_payload if isinstance(command_char_payload, str) else ":"

        return cls(
            perms=Permissions.from_relaunch_data(cast(Mapping[str, object], perms_payload)),
            user_vars=user_vars,
            repl_commands=repl_commands,
            command_char=command_char,
        )

    def __getstate__(self) -> dict[str, object]:
        """Serialize relaunch-safe state for pickling."""
        return self.to_relaunch_data()

    def __setstate__(self, state: Mapping[str, object]) -> None:
        """Restore from pickled relaunch payload."""
        restored = self.from_relaunch_data(state)
        self.__dict__.update(restored.__dict__)

    def _cache_startup_summaries(self) -> None:
        """Precompute static startup summary strings for this session."""
        builtins_scope = self.perms.globals_dict.get("__builtins__", {})
        builtins_names = (
            sorted(builtins_scope.keys()) if isinstance(builtins_scope, dict) else []
        )
        self._startup_builtins = ", ".join(builtins_names)
        self._startup_nodes = ", ".join(sorted(node.__name__ for node in self.perms.allowed_nodes))
        self._startup_imports = self.perms.imports

    def print_builtins(self) -> None:
        """Print builtins summary for the current session permissions."""
        self.print(f"  Builtins: {self._startup_builtins}")

    def print_nodes(self) -> None:
        """Print AST-node summary for the current session permissions."""
        self.print(f"  Nodes: {self._startup_nodes}")

    def print_imports(self) -> None:
        """Print import summary for the current session permissions."""
        if self._startup_imports:
            self.print(f"  Imports: {self._startup_imports}")

    def print_user_vars(self, *, include_values: bool = True) -> str:
        """Print user variable names, optionally including their values."""
        rendered_string = "  User vars: "

        if not self.user_vars:
            rendered_string += "(none)"
        elif include_values:
            rendered_string += "".join(
                f"\n    {name}={value!r}" for name, value in sorted(self.user_vars.items())
            )
        else:
            rendered_string += ", ".join(sorted(self.user_vars.keys()))

        self.print(rendered_string)
        return rendered_string

    def input(self, prompt: str = "") -> str:
        """Read one line of input from the user."""
        return self._read(prompt)

    def print(self, output: str | None) -> None:
        """Emit captured output text as line-oriented callback events."""
        if output is None:
            return
        for line in output.splitlines():
            self._write(line)

    def _dispatch_command(self, line: str) -> bool | object:
        """Run one REPL command and redirect command print output."""
        output_buffer = io.StringIO()
        with contextlib.redirect_stdout(output_buffer):
            result = self.command_registry.dispatch(line, session=self)
        self.print(output_buffer.getvalue() or None)
        return result

    def _run_repl_loop(self, *, execute: Callable[[str], object | None]) -> None:
        """Run interactive input/execute loop until user exits."""
        while True:
            try:
                line = self.input("> ").strip()
            except (EOFError, KeyboardInterrupt):
                self.print("")
                self.print("Bye")
                break

            if not line:
                continue
            if line.lower() in {"quit", "exit"}:
                self.print("Bye")
                break
            if line.startswith(self.command_char):
                command_result = self._dispatch_command(
                    line.removeprefix(self.command_char),
                )
                if command_result:
                    continue

            try:
                result = execute(line)
                if result is not None:
                    self.print(str(result))
            except Exception as error:
                self.print(f"Error: {error}")

    @classmethod
    def from_cli_args(
        cls,
        args: argparse.Namespace,
        *,
        user_vars: dict[str, object] | None = None,
    ) -> "SafeSession":
        """Build a session from parsed CLI arguments and normalized mode."""
        perms = Permissions(
            base_perms=PermissionLevel(args.level),
            imports=args.imports if args.imports is not None else ["math:*"],
            allow_symbols=set(args.allow_functions) if args.allow_functions else None,
            block_symbols=set(args.block_functions) if args.block_functions else None,
            allow_nodes=set(args.allow_nodes) if args.allow_nodes else None,
            block_nodes=set(args.block_nodes) if args.block_nodes else None,
        )
        return cls(
            perms=perms,
            user_vars=user_vars,
        )

    def _resolve_worker_response(self, response: WorkerResponse) -> object | None:
        """Emit worker output and either return result or raise worker exception."""
        self.print(response["output"])
        if response["ok"]:
            return response["result"]

        if response["exception_type"] is not None:
            candidate = getattr(builtins, response["exception_type"], None)
            if isinstance(candidate, type) and issubclass(candidate, Exception):
                raise candidate(response["message"])

        raise RuntimeError(f"Worker raised {response['exception_type']}: {response['message']}")

    def exec(self, code: str) -> object | None:
        """Execute one snippet through the session's worker."""
        self.open_worker_session()
        if self._worker_session is None:
            raise RuntimeError("Worker session is unavailable for execution.")

        response = self._worker_session.exec(code)
        return self._resolve_worker_response(response)

    def reset(self) -> None:
        """Reset local variables and worker state if open."""
        self.user_vars.clear()
        if self._worker_session is not None:
            self._worker_session.reset()

    def open_worker_session(self) -> None:
        """Start worker session for repeated execution."""
        if self._worker_session is None:
            self._worker_session = WorkerSession(
                perms=self.perms,
                user_vars=self.user_vars,
            )
        self._worker_session.open()

    def close_worker_session(self) -> None:
        """Stop worker session if active."""
        session = self._worker_session
        self._worker_session = None
        if session is not None:
            session.close()

    def repl(self) -> None:
        """Run interactive single-line REPL loop."""
        self.open_worker_session()
        if self._worker_session is None:
            raise RuntimeError("Worker session is unavailable for REPL execution.")

        self.print("Type 'quit' or 'exit' to exit.")
        output_buffer = io.StringIO()
        with contextlib.redirect_stdout(output_buffer):
            self.command_registry.show_help(cmd_char=self.command_char)
        self.print(output_buffer.getvalue() or None)

        try:
            def _execute_and_capture(code: str) -> object | None:
                assert self._worker_session is not None
                response = self._worker_session.exec(code)
                return self._resolve_worker_response(response)

            self._run_repl_loop(execute=_execute_and_capture)
        finally:
            self.close_worker_session()
