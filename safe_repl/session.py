"""Stateful session and interactive REPL orchestration."""

import argparse
import sys
from collections.abc import Callable

from .imports import parse_import_spec
from .policy import PermissionLevel, Permissions
from .process_isolation import WorkerSession
from .repl_command_registry import (
    CommandRegistry,
)


def _resolve_cli_imports(import_args: list[str] | None) -> dict[str, object]:
    """Resolve CLI import specs into the globals injection map.

    Behavior matches the CLI `--import` flag contract:
    - when `--import` is not used, auto-import `math:*`
    - any use of `--import` disables auto-import of `math`
    - empty/whitespace specs are ignored, so `--import ""` results in no imports
    """
    if import_args is None:
        return parse_import_spec("math:*")

    import_specs = [spec for spec in (import_args or []) if spec.strip()]
    if import_specs:
        print(
            "Warning: Imported libraries bypass AST validation and have full access.",
            file=sys.stderr,
        )
        imports: dict[str, object] = {}
        for spec in import_specs:
            imports.update(parse_import_spec(spec))
        return imports
    return {}


class SafeSession:
    """Stateful execution wrapper around policy, variables, and REPL lifecycle."""

    def __init__(
        self,
        perms: Permissions,
        user_vars: dict[str, object] | None = None,
        *,
        repl_commands: CommandRegistry | None = None,
        command_char: str = ":",
    ):
        """Create a session with persistent variables and worker-backed execution."""
        self.perms = perms
        self.user_vars: dict[str, object] = user_vars or {}
        self.command_char = command_char
        self._worker_session: WorkerSession | None = None
        self.command_registry = repl_commands or CommandRegistry()

        self._cache_startup_summaries()

    def _cache_startup_summaries(self) -> None:
        """Precompute static startup summary strings for this session."""

        builtins_scope = self.perms.globals_dict.get("__builtins__", {})
        builtins_names = (
            sorted(builtins_scope.keys()) if isinstance(builtins_scope, dict) else []
        )
        self._startup_builtins = ", ".join(builtins_names)
        self._startup_nodes = ", ".join(sorted(node.__name__ for node in self.perms.allowed_nodes))
        self._startup_imports = ", ".join(sorted(self.perms.imported_symbols))

    def print_builtins(self) -> None:
        """Print builtins summary for the current session permissions."""
        print(f"  Builtins: {self._startup_builtins}")

    def print_nodes(self) -> None:
        """Print AST-node summary for the current session permissions."""
        print(f"  Nodes: {self._startup_nodes}")

    def print_imports(self) -> None:
        """Print import summary for the current session permissions."""
        if self._startup_imports:
            print(f"  Imports: {self._startup_imports}")

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

        print(rendered_string)
        return rendered_string

    def _print_repl_intro(self) -> None:
        """Print basic REPL guidance and available command help lines."""
        print("Type 'quit' or 'exit' to exit.")
        self.command_registry.show_help(cmd_char=self.command_char)

    def _run_repl_loop(self, *, execute: Callable[[str], object | None]) -> None:
        """Run interactive input/execute loop until user exits."""
        while True:
            try:
                line = input("> ").strip()
            except (EOFError, KeyboardInterrupt):
                print("", "Bye")
                break

            if not line:
                continue
            if line.lower() in {"quit", "exit"}:
                print("Bye")
                break
            if line.startswith(self.command_char):
                if self.command_registry.dispatch(line.removeprefix(self.command_char), session=self):
                    continue

            try:
                result = execute(line)
                if result is not None:
                    print(result)
            except Exception as error:
                print(f"Error: {error}")

    @classmethod
    def from_cli_args(
        cls,
        args: argparse.Namespace,
        *,
        user_vars: dict[str, object] | None = None,
    ) -> "SafeSession":
        """Build a session from parsed CLI arguments and normalized mode."""
        imports = _resolve_cli_imports(args.imports)
        perms = Permissions(
            base_perms=PermissionLevel(args.level),
            imports=imports,
            allow_symbols=set(args.allow_functions) if args.allow_functions else None,
            block_symbols=set(args.block_functions) if args.block_functions else None,
            allow_nodes=set(args.allow_nodes) if args.allow_nodes else None,
            block_nodes=set(args.block_nodes) if args.block_nodes else None,
        )
        return cls(
            perms=perms,
            user_vars=user_vars,
        )

    def exec(
        self,
        code: str,
    ) -> object | None:
        """Execute one snippet through the session's worker."""
        self.open_worker_session()
        if self._worker_session is None:
            raise RuntimeError("Worker session is unavailable for execution.")
        return self._worker_session.exec(code)

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

    def repl(
        self,
        *,
        command_char: str | None = None,
    ) -> None:
        """Run interactive single-line REPL loop.

        Args:
            command_char: Optional prefix used to identify REPL commands.
                When omitted, reuses the session's current command prefix.

        Uses one worker session for the REPL run and closes it on exit.
        """
        if command_char is not None:
            self.command_char = command_char

        self.open_worker_session()
        if self._worker_session is None:
            raise RuntimeError("Worker session is unavailable for REPL execution.")

        self._print_repl_intro()

        try:
            self._run_repl_loop(execute=self._worker_session.exec)
        finally:
            self.close_worker_session()


def repl(
    *,
    perms: Permissions,
    command_char: str = ":",
) -> None:
    """Convenience function to launch a REPL for one permissions object."""
    SafeSession(perms).repl(
        command_char=command_char,
    )
