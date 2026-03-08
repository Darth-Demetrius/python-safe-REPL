"""Import specification parsing and CLI argument validation utilities."""

import argparse
import ast
import importlib
from types import ModuleType


class SafeReplImportError(ValueError):
    """Raised when an import spec cannot be resolved."""


class SafeReplCliArgError(ValueError):
    """Raised when CLI AST-node arguments are invalid."""


def _parse_symbol_alias(item: str) -> tuple[str, str]:
    """Parse `name` or `name as alias` into `(source_name, alias)`."""
    source_name, has_alias, alias = item.partition(" as ")
    source_name = source_name.strip()
    alias = alias.strip() if has_alias else source_name

    if (
        not source_name
        or not alias
        or any(char.isspace() for char in source_name)
        or any(char.isspace() for char in alias)
    ):
        raise SafeReplImportError(f"Invalid import symbol spec: {item!r}")
    return source_name, alias


def _parse_import_list(module: ModuleType, import_names: str) -> dict[str, object]:
    """Parse comma-separated symbol import names for one imported module."""
    if import_names == "*":
        return {name: obj for name, obj in vars(module).items() if not name.startswith("_")}

    result: dict[str, object] = {}
    for item in import_names.split(","):
        original_name, alias = _parse_symbol_alias(item)
        try:
            result[alias] = getattr(module, original_name)
        except AttributeError as exc:
            raise SafeReplImportError(
                f"Module '{module.__name__}' has no attribute '{original_name}'"
            ) from exc
    return result


def parse_import_spec(spec: str) -> dict[str, object]:
    """Parse one import spec and return injected globals mapping.

    Supported forms:
    - `module`
    - `module as alias`
    - `module:name`
    - `module:name as alias`
    - `module:*`

    Raises:
        SafeReplImportError: If parsing/import resolution fails.
    """
    spec = spec.strip()
    if not spec:
        raise SafeReplImportError("Empty import spec cannot be parsed")

    try:
        if ":" in spec:
            module_name, import_names = spec.split(":", 1)
            module = importlib.import_module(module_name.strip())
            return _parse_import_list(module, import_names.strip())

        module_name, alias = _parse_symbol_alias(spec)
        imported_module = importlib.import_module(module_name)
        if alias != module_name:
            return {alias: imported_module}

        top_level_name, has_submodule, _ = module_name.partition(".")
        if not has_submodule:
            return {top_level_name: imported_module}
        return {top_level_name: importlib.import_module(top_level_name)}
    except SafeReplImportError:
        raise
    except Exception as e:
        raise SafeReplImportError(f"Failed to import '{spec}': {e}") from e


def validate_cli_args(args: argparse.Namespace) -> None:
    """Resolve CLI `allow/block-nodes` names into AST node classes.

    Raises:
        SafeReplCliArgError: If any node name does not exist in `ast`.
    """
    def resolve_node_class(node_name: str) -> type[ast.AST]:
        node = getattr(ast, node_name, None)
        if not isinstance(node, type) or not issubclass(node, ast.AST):
            raise SafeReplCliArgError(f"Unknown node type: {node_name}")
        return node

    for arg_name in ("allow_nodes", "block_nodes"):
        node_names = getattr(args, arg_name)
        if not node_names:
            continue
        setattr(args, arg_name, [resolve_node_class(node_name) for node_name in node_names])
