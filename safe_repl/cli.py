"""Command-line entrypoint for safe_repl."""

import argparse
import sys

from .execution import ExecutionMode
from .imports import SafeReplCliArgError, SafeReplImportError, validate_cli_args
from .session import SafeSession


def _build_parser() -> argparse.ArgumentParser:
    """Create and configure the CLI argument parser."""
    parser = argparse.ArgumentParser(
        description="Safe REPL with restricted execution context",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Examples:
  %(prog)s                               # Limited permission level (default)
  %(prog)s --level MINIMUM               # Restrict to arithmetic only
  %(prog)s --level PERMISSIVE            # Allow classes and exception handling
  %(prog)s --execution-mode process      # Run snippets in isolated subprocesses
  %(prog)s --level UNSUPERVISED          # Allow imports and most builtins
  %(prog)s --allow-functions map filter  # Add functions to default set
  %(prog)s --list-functions              # Show allowed functions and exit
        """,
    )

    parser.add_argument(
        "--level",
        default="LIMITED",
        help="Permission level: MINIMUM/0, LIMITED/1 (default), PERMISSIVE/2, UNSUPERVISED/3",
    )
    parser.add_argument(
        "--import",
        dest="imports",
        action="append",
        metavar="SPEC",
        help=(
            "Import library (bypasses AST validation)\n"
            "'module', 'module as alias', 'module:name', or 'module:*' are valid\n"
            "use a comma-separated list for multiple imports\n"
            "any use of this argument disables auto-import of math module "
            "(use --import \"\" to disable auto-import without adding any imports)"
        ),
    )
    parser.add_argument("--allow-functions", nargs="+", help="Add builtin functions")
    parser.add_argument("--block-functions", nargs="+", help="Remove builtin functions")
    parser.add_argument("--allow-nodes", nargs="+", help="Add AST nodes")
    parser.add_argument("--block-nodes", nargs="+", help="Remove AST nodes")
    parser.add_argument("--list-functions", action="store_true", help="Show allowed functions")
    parser.add_argument("--list-nodes", action="store_true", help="Show allowed AST nodes")
    parser.add_argument(
        "--show-repl-details",
        action="store_true",
        help="Show REPL startup details (builtins, nodes, imports).",
    )
    parser.add_argument(
        "--show-repl-details-once",
        action=argparse.BooleanOptionalAction,
        default=None,
        help=(
            "Whether startup details print once per session (default: false for "
            "MINIMUM/LIMITED, true for PERMISSIVE/UNSUPERVISED)."
        ),
    )
    parser.add_argument(
        "--execution-mode",
        choices=ExecutionMode.choices(),
        default=ExecutionMode.default().value,
        help=(
            "Execution backend. 'process' (default) runs snippets in isolated "
            "subprocesses; 'in-process' runs in the current interpreter."
        ),
    )
    return parser


def _print_allowed_functions(session: SafeSession) -> None:
    """Print allowed builtin function names for the active session."""
    builtins_scope = session.perms.globals_dict.get("__builtins__", {})
    if not isinstance(builtins_scope, dict):
        builtins_scope = {}

    print("Allowed functions:")
    for name in sorted(builtins_scope.keys()):
        print(f"  {name}")


def _print_allowed_nodes(session: SafeSession) -> None:
    """Print allowed AST node names for the active session."""
    print("Allowed AST nodes:")
    for node in sorted(session.perms.allowed_nodes, key=lambda n: n.__name__):
        print(f"  {node.__name__}")


def main() -> None:
    """Parse CLI arguments and run list/report or interactive REPL mode."""
    parser = _build_parser()

    args = parser.parse_args()
    try:
        validate_cli_args(args)
        session = SafeSession.from_cli_args(args)
    except (SafeReplCliArgError, SafeReplImportError) as error:
        print(error, file=sys.stderr)
        sys.exit(1)

    if args.list_functions:
        _print_allowed_functions(session)
        return

    if args.list_nodes:
        _print_allowed_nodes(session)
        return

    session.repl(
        show_details=args.show_repl_details,
        show_details_once=args.show_repl_details_once,
    )
