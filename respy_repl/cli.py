"""Command-line entry-point for the RestrictedPython-based safe REPL.

Usage examples::

    python -m safe_repl.ResPy___main__
    python -c "from safe_repl.ResPy_cli import main; main()"

Compared to the original CLI, the ``--allow-nodes`` / ``--block-nodes`` flags
are removed because RestrictedPython manages AST-level restrictions at compile
time and does not expose per-node toggles to callers.
"""

from __future__ import annotations

import argparse
import sys

from .imports import SafeReplCliArgError, SafeReplImportError, validate_cli_args
from .session import SafeSession


def _build_parser() -> argparse.ArgumentParser:
    """Create and return the CLI argument parser."""
    parser = argparse.ArgumentParser(
        prog="respy-repl",
        description="Safe REPL (RestrictedPython backend) with tiered permission levels",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Examples:
  %(prog)s                               # CONTROLLED level (default)
  %(prog)s --level RESTRICTED            # Expression-only, no loops/functions
  %(prog)s --level TRUSTED               # Broader access; most builtins allowed
  %(prog)s --import "math:*"             # Pre-import math symbols
  %(prog)s --allow-functions divmod      # Add a builtin to the allowed set
  %(prog)s --list-functions              # Show allowed builtins and exit

REPL commands (prefix with the command character, default ':'):
  :help <command>       Show help for one command
  :commands             List all available commands
  :vars                 Show user variable names
  :vars values          Show user variables with values
  :level                Show active permission level
  :reset                Clear all user variables
""",
    )

    parser.add_argument(
        "--level",
        default="CONTROLLED",
        help="Permission level: RESTRICTED/1, CONTROLLED/2 (default), TRUSTED/3",
    )
    parser.add_argument(
        "--import",
        dest="imports",
        action="append",
        metavar="SPEC",
        help=(
            "Pre-import a module or symbol.  "
            "Accepted formats: 'module', 'module as alias', "
            "'module:name', 'module:*'.  "
            "Passing this flag disables the default 'math:*' auto-import; "
            "use --import \"\" to disable auto-import without adding imports."
        ),
    )
    parser.add_argument(
        "--allow-functions",
        nargs="+",
        metavar="NAME",
        help="Add extra built-in names to the allowed set.",
    )
    parser.add_argument(
        "--block-functions",
        nargs="+",
        metavar="NAME",
        help="Remove built-in names from the allowed set.",
    )
    parser.add_argument(
        "--list-functions",
        action="store_true",
        help="Print allowed built-in names and exit.",
    )
    return parser


def _parse_and_build(
    parser: argparse.ArgumentParser,
) -> tuple[argparse.Namespace, SafeSession]:
    """Parse CLI args and construct session, exiting on user-facing errors."""
    args = parser.parse_args()
    try:
        validate_cli_args(args)
        session = SafeSession.from_cli_args(args)
    except (SafeReplCliArgError, SafeReplImportError) as err:
        print(err, file=sys.stderr)
        sys.exit(1)
    return args, session


def main() -> None:
    """Parse CLI arguments and run list mode or interactive REPL."""
    parser = _build_parser()
    args, session = _parse_and_build(parser)

    if args.list_functions:
        safe_builtins = session.perms.restricted_globals.get("__builtins__", {})
        if isinstance(safe_builtins, dict):
            print("Allowed functions:")
            for name in sorted(k for k in safe_builtins if not k.startswith("_")):
                print(f"  {name}")
        return

    session.repl()
