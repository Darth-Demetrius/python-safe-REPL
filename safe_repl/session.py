"""Stateful session and interactive REPL orchestration."""

import argparse
import sys

from .execution import (
    ExecutionMode,
    ExecutionModeInput,
    ExecutionModeOverride,
    PersistentSubprocessSession,
    coerce_execution_mode,
    dispatch_execution,
    reset_execution_state,
    uses_persistent_process,
)
from .imports import parse_import_spec
from .policy import PermissionLevel, Permissions


def _resolve_cli_imports(import_args: list[str] | None) -> dict[str, object]:
    """Resolve CLI import specs into the globals injection map.

    Behavior mirrors previous implementation:
    - When no `--import` args are provided, auto-import `math:*`.
    - Empty/whitespace specs are ignored.
    - Any non-empty explicit imports print a warning to stderr.
    """
    if import_args:
        import_specs = [spec for spec in import_args if spec.strip()]
        if import_specs:
            print(
                "Warning: Imported libraries bypass AST validation and have full access.",
                file=sys.stderr,
            )
            imports: dict[str, object] = {}
            for spec in import_specs:
                imports.update(parse_import_spec(spec))
            return imports
    return parse_import_spec("math:*")


def _default_show_details_once(level: PermissionLevel) -> bool:
    """Return default detail-print mode for a permission level.

    MINIMUM/LIMITED default to repeated details (`False`) for transparency.
    PERMISSIVE/UNSUPERVISED default to one-time details (`True`) to reduce
    repeated high-volume output.
    """
    return level >= PermissionLevel.PERMISSIVE


class SafeSession:
    """Stateful execution wrapper around policy, variables, and REPL lifecycle."""

    def __init__(
        self,
        perms: Permissions,
        user_vars: dict[str, object] | None = None,
        *,
        execution_mode: ExecutionModeInput = ExecutionMode.PROCESS,
    ):
        """Create a session with persistent variables and execution mode."""
        self.perms = perms
        self.user_vars: dict[str, object] = user_vars or {}
        self.execution_mode = coerce_execution_mode(execution_mode)
        self._persistent_process_session: PersistentSubprocessSession | None = None
        builtins_scope = self.perms.globals_dict.get("__builtins__", {})
        builtins_names = sorted(builtins_scope.keys()) if isinstance(builtins_scope, dict) else []
        self._startup_details = {
            "builtins": ", ".join(builtins_names),
            "nodes": ", ".join(sorted(node.__name__ for node in self.perms.allowed_nodes)),
            "imports": ", ".join(sorted(self.perms.imported_symbols)),
        }
        self._startup_details_printed = False

    def _resolve_mode(self, execution_mode: ExecutionModeOverride) -> ExecutionMode:
        """Resolve effective execution mode for one call path."""
        return coerce_execution_mode(execution_mode, fallback=self.execution_mode)

    def _open_if_persistent_mode(self, mode: ExecutionMode) -> bool:
        """Open persistent subprocess worker when selected mode requires it."""
        should_open = uses_persistent_process(mode)
        if should_open:
            self.open_subprocess_session()
        return should_open

    def _print_startup_details(
        self,
        *,
        show_details: bool,
        show_details_once: bool,
    ) -> None:
        """Print startup detail block according to configured flags."""
        if not show_details:
            return
        if show_details_once and self._startup_details_printed:
            return

        print(f"  Builtins: {self._startup_details['builtins']}")
        print(f"  Nodes: {self._startup_details['nodes']}")
        if self._startup_details["imports"]:
            print(f"  Imports: {self._startup_details['imports']}")
        self._startup_details_printed = True

    def _run_repl_loop(self, *, mode: ExecutionMode) -> None:
        """Run interactive input/execute loop for one resolved mode."""
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

            try:
                result = self.exec(line, execution_mode=mode)
                if result is not None:
                    print(result)
            except Exception as e:
                print(f"Error: {e}")

    @classmethod
    def from_cli_args(
        cls,
        args: argparse.Namespace,
        *,
        user_vars: dict[str, object] | None = None,
    ) -> "SafeSession":
        """Build a session from parsed CLI arguments."""
        imports = _resolve_cli_imports(args.imports)

        perms = Permissions(
            base_perms=PermissionLevel(args.level),
            imports=imports,
            allow_symbols=set(args.allow_functions) if args.allow_functions else None,
            block_symbols=set(args.block_functions) if args.block_functions else None,
            allow_nodes=set(args.allow_nodes) if args.allow_nodes else None,
            block_nodes=set(args.block_nodes) if args.block_nodes else None,
        )
        execution_mode = coerce_execution_mode(
            getattr(args, "execution_mode", ExecutionMode.default())
        )
        return cls(perms=perms, user_vars=user_vars, execution_mode=execution_mode)

    def exec(
        self,
        code: str,
        *,
        execution_mode: ExecutionModeOverride = None,
    ) -> object | None:
        """Execute one snippet and return expression result (if any).

        Args:
            code: Single snippet to execute.
            execution_mode: Optional one-off backend override. When omitted,
                uses this session's configured execution mode.
        """
        mode = self._resolve_mode(execution_mode)
        return dispatch_execution(
            mode=mode,
            code=code,
            user_vars=self.user_vars,
            perms=self.perms,
            persistent_session=self._persistent_process_session,
        )

    def reset(self) -> None:
        """Reset session state (local vars and persistent worker, when open)."""
        reset_execution_state(
            self.user_vars,
            persistent_session=self._persistent_process_session,
        )

    def open_subprocess_session(self) -> None:
        """Start long-lived subprocess worker for repeated process-mode execution."""
        if self._persistent_process_session is None:
            self._persistent_process_session = PersistentSubprocessSession(
                perms=self.perms,
                user_vars=self.user_vars,
            )
        self._persistent_process_session.open()

    def close_subprocess_session(self) -> None:
        """Stop long-lived subprocess worker if active."""
        if self._persistent_process_session is not None:
            self._persistent_process_session.close()
            self._persistent_process_session = None

    def reopen_subprocess_session(self) -> None:
        """Restart long-lived subprocess worker with current local variables."""
        self.close_subprocess_session()
        self.open_subprocess_session()

    def repl(
        self,
        *,
        show_details: bool = False,
        show_details_once: bool | None = None,
        execution_mode: ExecutionModeOverride = None,
    ) -> None:
        """Run interactive single-line REPL loop.

        Args:
            show_details: When true, print builtins/nodes/import summary.
            show_details_once: When true, details are printed once per session.
                Defaults to `False` for MINIMUM/LIMITED and `True` for
                PERMISSIVE/UNSUPERVISED.
            execution_mode: Optional backend override for this REPL run only.
                When omitted, uses this session's configured execution mode.
        """
        if show_details_once is None:
            show_details_once = _default_show_details_once(self.perms.level)

        mode = self._resolve_mode(execution_mode)
        use_persistent_process = self._open_if_persistent_mode(mode)

        print(f"Safe REPL ({self.perms})")
        self._print_startup_details(
            show_details=show_details,
            show_details_once=show_details_once,
        )
        print("Type 'quit' to exit.")

        try:
            self._run_repl_loop(mode=mode)
        finally:
            if use_persistent_process:
                self.close_subprocess_session()


def repl(
    *,
    perms: Permissions,
    show_details: bool = False,
    show_details_once: bool | None = None,
    execution_mode: ExecutionModeOverride = None,
) -> None:
    """Convenience function to launch a REPL for one permissions object."""
    SafeSession(perms).repl(
        show_details=show_details,
        show_details_once=show_details_once,
        execution_mode=execution_mode,
    )
