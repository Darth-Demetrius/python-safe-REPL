"""Decorator-based REPL command registry for the RestrictedPython REPL.

Functionally identical to the original ``safe_repl.repl_command_registry``; the
only change is updated forward-references to ``ResPy_session.SafeSession``.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .session import SafeSession

__all__ = ("CommandRegistry",)

CommandHandler = Callable[[str, "SafeSession"], bool | object]


@dataclass(frozen=True)
class _RegisteredCommand:
    """One registered REPL command with metadata and handler."""

    name: str
    help_text: str
    args_desc: str
    is_hidden: bool
    handler: CommandHandler


class CommandRegistry:
    """Registry that binds command names to decorator-registered handlers.

    Command lines are expected with the command prefix already stripped.
    Matching is exact (case-sensitive first, then lower-case fallback).

    Usage example::

        registry = CommandRegistry()

        @registry.command("greet", help_text="Say hello.")
        def _greet(args, session):
            print(f"Hello, {args or 'world'}!")
    """

    def __init__(self) -> None:
        self._commands_by_name: dict[str, _RegisteredCommand] = {}
        self._register_builtin_commands()

    def command(
        self,
        name: str,
        *,
        help_text: str = "",
        args_desc: str = "",
        is_hidden: bool = False,
    ) -> Callable[[CommandHandler], CommandHandler]:
        """Decorator that registers *handler* as a REPL command.

        Args:
            name: The command token (without the command prefix).
            help_text: One-line help string.  ``{0}`` is replaced by the
                command prefix when displayed.
            args_desc: Optional argument description; ``{0}`` is the prefix.
            is_hidden: When ``True`` the command is omitted from ``{0}commands``.

        Returns:
            A pass-through decorator that registers the function unchanged.
        """
        name = name.strip()
        if not name:
            raise ValueError("Command name cannot be empty.")

        def decorator(func: CommandHandler) -> CommandHandler:
            self._commands_by_name[name] = _RegisteredCommand(
                name=name,
                help_text=help_text,
                args_desc=args_desc,
                is_hidden=is_hidden,
                handler=func,
            )
            return func

        return decorator

    def dispatch(self, line: str, *, session: "SafeSession") -> bool | object:
        """Execute the command whose token is the first word of *line*.

        Returns ``False`` when no matching command is found.
        """
        if not line.strip():
            return False

        command_name, _, args = line.partition(" ")
        command_name, args = command_name.strip(), args.strip()

        cmd = (
            self._commands_by_name.get(command_name)
            or self._commands_by_name.get(command_name.lower())
        )
        if cmd is None:
            return False

        result = cmd.handler(args, session)
        return result if isinstance(result, bool) else True

    def show_help(self, cmd_name: str = "", cmd_char: str = ":") -> None:
        """Print help text for *cmd_name* (defaults to ``help``)."""
        cmd_name = cmd_name.strip() or "help"
        cmd = (
            self._commands_by_name.get(cmd_name)
            or self._commands_by_name.get(cmd_name.lower())
        )
        if cmd is None:
            print(f"{cmd_char}{cmd_name} is not a recognised command.")
            return
        if not cmd.help_text:
            print(f"No help available for '{cmd_char}{cmd_name}'.")
            return

        try:
            print(cmd.help_text.format(cmd_char))
        except (IndexError, KeyError, ValueError):
            print(cmd.help_text)
        if cmd.args_desc:
            try:
                print(f"Args: {cmd.args_desc.format(cmd_char)}")
            except (IndexError, KeyError, ValueError):
                print(f"Args: {cmd.args_desc}")

    def list_commands(self, cmd_char: str = ":", hidden: bool = False) -> None:
        """Print all available (or hidden) commands with one-line descriptions."""
        entries = self.all_help_entries(hidden=hidden)
        if not entries:
            print("Available commands: (none)")
            return
        lines = [
            f" {name}: {text.format(cmd_char)}"
            for name, text in entries.items()
        ]
        print("Available commands:\n" + "\n".join(lines))

    def all_help_entries(self, hidden: bool = False) -> dict[str, str]:
        """Return ``{command_name: help_text}`` for visible (or hidden) commands."""
        return {
            name: cmd.help_text
            for name in sorted(self._commands_by_name)
            if (cmd := self._commands_by_name[name]).help_text
            and cmd.is_hidden == hidden
        }

    def _register_builtin_commands(self) -> None:
        """Register the built-in commands shipped with every registry."""

        # Help / discovery
        @self.command(
            "help",
            help_text=(
                "Use '{0}help <command>' to show help for a command, "
                "or '{0}commands' to list all available commands."
            ),
        )
        def _show_help(args: str, session: "SafeSession") -> None:
            self.show_help(args, cmd_char=session.command_char)

        @self.command(
            "commands",
            help_text="Lists all available commands.  Format: '{0}<command> <args>'.",
        )
        def _list_commands(args: str, session: "SafeSession") -> None:
            self.list_commands(cmd_char=session.command_char)

        # Session introspection
        @self.command("level", help_text="Prints the current permission level.")
        def _show_level(_args: str, session: "SafeSession") -> None:
            print(f"  Permission level: {session.perms}")

        @self.command(
            "functions",
            help_text="Prints available built-in functions for the current session.",
        )
        def _show_functions(_args: str, session: "SafeSession") -> None:
            session.print_builtins()

        @self.command(
            "imports",
            help_text="Prints pre-imported symbols for the current session.",
        )
        def _show_imports(_args: str, session: "SafeSession") -> None:
            if session.perms.imports:
                session.print_imports()
            else:
                print("  Imports: (none)")

        @self.command(
            "vars",
            help_text="Lists user-defined variables.",
            args_desc="(optional) 'values' – also show variable values.",
        )
        def _show_vars(args: str, session: "SafeSession") -> None:
            session.print_user_vars(include_values=(args.strip() == "values"))

        @self.command(
            "reset",
            help_text="Clears all user-defined variables for the current session.",
        )
        def _reset(_args: str, session: "SafeSession") -> None:
            session.reset()
            print("  Variables cleared.")
