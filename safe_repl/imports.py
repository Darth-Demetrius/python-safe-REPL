"""Import specification parsing and CLI argument validation utilities."""

import argparse
import ast
import importlib


class SafeReplImportError(ValueError):
    """Raised when an import spec cannot be resolved."""


class SafeReplCliArgError(ValueError):
    """Raised when CLI AST-node arguments are invalid."""


def _parse_symbol_alias(item: str) -> tuple[str, str]:
    """Parse `name` or `name as alias` into `(source_name, target_name)`."""
    if " as " in item:
        source_name, alias = item.split(" as ", 1)
        return source_name.strip(), alias.strip()
    clean_item = item.strip()
    return clean_item, clean_item


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
    try:
        if ":" in spec:
            module_name, import_names = spec.split(":", 1)
            module = importlib.import_module(module_name.strip())
            import_names = import_names.strip()

            if import_names == "*":
                return {name: obj for name, obj in vars(module).items() if not name.startswith("_")}

            result: dict[str, object] = {}
            for item in import_names.split(","):
                original_name, alias = _parse_symbol_alias(item)
                result[alias] = getattr(module, original_name)
            return result

        if " as " in spec:
            module_name, alias = spec.split(" as ", 1)
            return {alias.strip(): importlib.import_module(module_name.strip())}

        importlib.import_module(spec)
        top_level_name = spec.split(".")[0]
        return {top_level_name: sys.modules[top_level_name]}
    except Exception as e:
        raise SafeReplImportError(f"Failed to import '{spec}': {e}") from e


def validate_cli_args(args: argparse.Namespace) -> None:
    """Resolve CLI `allow/block-nodes` names into AST node classes.

    Raises:
        SafeReplCliArgError: If any node name does not exist in `ast`.
    """
    for node_list in (args.allow_nodes, args.block_nodes):
        if node_list:
            for i, node_name in enumerate(node_list):
                if not hasattr(ast, node_name):
                    raise SafeReplCliArgError(f"Unknown node type: {node_name}")
                node_list[i] = getattr(ast, node_name)
