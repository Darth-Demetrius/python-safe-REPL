"""Decorator-based REPL command registry.

`help_text` and `args_desc` may include `str.format` placeholders for the
command prefix (for example, `'{0}vars values'`).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .session import SafeSession


__all__ = (
    "CommandRegistry",
)


CommandHandler = Callable[[str, "SafeSession"], bool | object]


@dataclass(frozen=True)
class _RegisteredCommand:
    """One registered REPL command with metadata and callback."""

    name: str
    help_text: str
    args_desc: str
    is_hidden: bool
    handler: CommandHandler


class CommandRegistry:
    """Registry that binds command names to decorator-registered handlers.

    Design decisions:
    - Command lines are interpreted as `<command> <args...>`.
    - Input is assumed to already have the command prefix removed.
    - Matching is exact on the command token (first whitespace-separated token).
    - Lookup is case-sensitive first, then falls back to lowercase key.
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
        """Decorator to register a function as a REPL command handler.

        Args:
            name: Prefix-stripped command token (for example `vars`).
            help_text: Optional command help text. May include `{0}` placeholder
                for the active command prefix.
            args_desc: Optional description of command arguments. May include
                `{0}` placeholder for the active command prefix.
            is_hidden: Whether to hide this command from default listings.
        Returns:
            A decorator that registers the function and returns it unchanged.
        """
        name = name.strip()
        if not name:
            raise ValueError("Command name cannot be empty")

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
        """Execute a command if the first token matches a registered handler.

        Command lookup is case-sensitive first, then falls back to lowercase.
        """
        if not line.strip():
            return False

        command_name, _, args = line.partition(" ")
        command_name, args = command_name.strip(), args.strip()

        command = self._commands_by_name.get(command_name) or self._commands_by_name.get(command_name.lower())
        if command is None:
            return False

        result = command.handler(args, session)
        if isinstance(result, bool):
            return result
        return True

    def show_help(self, cmd_name: str = "", cmd_char: str = ":") -> None:
        """Print help text for one command.

        Command lookup is case-sensitive first, then falls back to lowercase.
        """
        cmd_name = cmd_name.strip() or "help"
        command = self._commands_by_name.get(cmd_name) or self._commands_by_name.get(cmd_name.lower())
        if command is None:
            print(f"{cmd_char}{cmd_name} is not a recognized command")
            return
        if not command.help_text:
            print(f"No help available for '{cmd_char}{cmd_name}' command.")
            return

        try:
            print(command.help_text.format(cmd_char))
        except (IndexError, KeyError, ValueError):
            print(command.help_text)
        if command.args_desc:
            try:
                print(f"Args: {command.args_desc.format(cmd_char)}")
            except (IndexError, KeyError, ValueError):
                print(f"Args: {command.args_desc}")

    def list_commands(self, cmd_char: str = ":", hidden: bool = False) -> None:
        """Print available command names with one-line help text.

        Args:
            cmd_char: Prefix used when rendering command names.
            hidden: When true, list hidden commands instead of visible ones.
        """
        help_entries = self.all_help_entries(hidden=hidden)
        if not help_entries:
            print("Available commands: (none)")
            return

        lines = [
            f" {name}: {help_line.format(cmd_char)}"
            for name, help_line in help_entries.items()
        ]
        print("Available commands:\n" + "\n".join(lines))

    def all_help_entries(self, hidden: bool = False) -> dict[str, str]:
        """Return command-to-help mapping in command-name order.

        Args:
            hidden: Select visible (`False`) or hidden (`True`) command entries.
        """
        return dict(
            (name, help_line)
            for name in sorted(self._commands_by_name)
            if (help_line := self._commands_by_name[name].help_text)
            and (self._commands_by_name[name].is_hidden == hidden)
        )

    def _register_builtin_commands(self) -> None:
        """Register built-in commands shipped with every registry instance.

        Keep registrations grouped by category to make future additions easy to
        locate and maintain.
        """

        # Help and command discovery.
        @self.command(
            "help",
            help_text="Use '{0}help <command>' to show help for a command, or '{0}commands' to list all available commands.",
        )
        def _show_help_command(args: str, session: "SafeSession") -> None:
            self.show_help(args, cmd_char=session.command_char)

        @self.command(
            "commands",
            help_text="Lists all available commands. Commands are formatted as '{0}<command> <args...>'.",
        )
        def _list_commands_command(args: str, session: SafeSession) -> None:
            self.list_commands(cmd_char=session.command_char)

        # Session data inspection.
        @self.command(
            "level",
            help_text="Prints the current permission level.",
        )
        def _show_permission_level_command(_args: str, session: SafeSession) -> None:
            print(f"  Permission level: {session.perms}")

        @self.command(
            "functions",
            help_text="Prints available functions for the current session.",
        )
        def _show_functions_command(_args: str, session: SafeSession) -> None:
            session.print_builtins()

        @self.command(
            "nodes",
            help_text="Prints allowed AST nodes for the current session.",
        )
        def _show_nodes_command(_args: str, session: SafeSession) -> None:
            session.print_nodes()

        @self.command(
            "imports",
            help_text="Prints imported symbols for the current session.",
        )
        def _show_imports_command(_args: str, session: SafeSession) -> None:
            if session.perms.imported_symbols:
                session.print_imports()
            else:
                print("  Imports: (none)")

        @self.command(
            "vars",
            help_text="Lists all user-defined variables.",
            args_desc="(optional) values: Use 'values' to also show variable values.",
        )
        def _show_vars_command(args: str, session: SafeSession) -> None:
            session.print_user_vars(include_values=(args.strip() == "values"))

        # Future built-ins:
        # - Add additional @self.command(...) registrations in the category
        #   blocks above, or create a new category block when needed.
