"""Stateful session and interactive REPL loop orchestration."""

import argparse
import sys

from .engine import safe_exec
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
    """Stateful execution wrapper around `safe_exec` and `Permissions`."""

    def __init__(self, perms: Permissions, user_vars: dict[str, object] | None = None):
        """Create a session with persistent user variables."""
        self.perms = perms
        self.user_vars: dict[str, object] = user_vars or {}
        builtins_scope = self.perms.globals_dict.get("__builtins__", {})
        builtins_names = sorted(builtins_scope.keys()) if isinstance(builtins_scope, dict) else []
        self._startup_details = {
            "builtins": ", ".join(builtins_names),
            "nodes": ", ".join(sorted(node.__name__ for node in self.perms.allowed_nodes)),
            "imports": ", ".join(sorted(self.perms.imported_symbols)),
        }
        self._startup_details_printed = False

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
        return cls(perms=perms, user_vars=user_vars)

    def exec(self, code: str) -> object | None:
        """Execute one snippet and return expression result, if any."""
        return safe_exec(code, self.user_vars, perms=self.perms)

    def reset(self) -> None:
        """Clear persistent user variables for this session."""
        self.user_vars.clear()

    def repl(self, *, show_details: bool = False, show_details_once: bool | None = None) -> None:
        """Run interactive single-line REPL loop.

        Args:
            show_details: When true, print builtins/nodes/import summary.
            show_details_once: When true, details are printed once per session.
                Defaults to `False` for MINIMUM/LIMITED and `True` for
                PERMISSIVE/UNSUPERVISED.
        """
        if show_details_once is None:
            show_details_once = _default_show_details_once(self.perms.level)

        print(f"Safe REPL ({self.perms})")
        if show_details and (not show_details_once or not self._startup_details_printed):
            print(f"  Builtins: {self._startup_details['builtins']}")
            print(f"  Nodes: {self._startup_details['nodes']}")
            if self._startup_details["imports"]:
                print(f"  Imports: {self._startup_details['imports']}")
            self._startup_details_printed = True
        print("Type 'quit' to exit.")

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
                result = self.exec(line)
                if result is not None:
                    print(result)
            except Exception as e:
                print(f"Error: {e}")


def repl(
    *,
    perms: Permissions,
    show_details: bool = False,
    show_details_once: bool | None = None,
) -> None:
    """Convenience function to launch a REPL for one permissions object."""
    SafeSession(perms).repl(show_details=show_details, show_details_once=show_details_once)
