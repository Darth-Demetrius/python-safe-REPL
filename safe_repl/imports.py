"""Import specification parsing and CLI argument validation utilities."""

import argparse
import ast
import importlib


NormalizedImportSpec = dict[str, tuple[str, str] | list[tuple[str, str]]]

class SafeReplImportError(ValueError):
    """Raised when an import spec cannot be resolved."""


class SafeReplCliArgError(ValueError):
    """Raised when CLI AST-node arguments are invalid."""


def _parse_symbol_alias(item: str) -> tuple[str, str]:
    """Parse `name` or `name as alias` into `(source_name, alias)`."""
    source_name, has_alias, alias = item.partition(" as ")
    source_name, alias = source_name.strip(), alias.strip()
    if has_alias and not alias:
        raise SafeReplImportError(f"Invalid import symbol spec: {item!r}")
    alias = alias or source_name

    if (
        not source_name
        or any(char.isspace() for char in source_name)
        or any(char.isspace() for char in alias)
    ):
        raise SafeReplImportError(f"Invalid import symbol spec: {item!r}")
    return (source_name, alias)


def normalize_validate_import(spec: str) -> NormalizedImportSpec:
    """Normalize one CLI import spec into a structured representation.

    The returned dict is picklable and intended to be sent to a worker for
    resolution. It will contain the following items:
    - "module": (module_name, module_alias)
    - "names": [(import_name, import_alias), ...]
    
    Empty aliases are normalized to the original name.
    """
    module, _, imports = spec.partition(":")
    module = _parse_symbol_alias(module)
    try:
        importlib.import_module(module[0])
    except Exception as exc:
        raise SafeReplImportError(
            f"Cannot import module {module[0]!r}: {exc} (Failed to import)"
        ) from exc

    names: list[tuple[str, str]] = []
    import_items = [item.strip() for item in imports.split(",") if item.strip()]

    for item in import_items:
        item = _parse_symbol_alias(item)
        if item[0] == "*":
            if len(import_items) > 1:
                raise SafeReplImportError("Cannot combine star import with other imports")
            # Expand star import into the module's public names so callers
            # can access them directly (e.g. `math:*` allows `random` as
            # a direct call, and `math.sqrt` as attribute access).
            # A sentinel entry `("*", module_alias)` is prepended so consumers
            # can detect this was a star import and allow attribute access on
            # the module name itself.
            module_obj = importlib.import_module(module[0])
            export_names = getattr(module_obj, "__all__", None)
            if export_names is None:
                export_names = [n for n in dir(module_obj) if not n.startswith("_")]
            names.append(("*", module[1]))  # sentinel: marks star import
            for nm in export_names:
                names.append((nm, nm))
            break
        try:
            module_obj = importlib.import_module(module[0])
            getattr(module_obj, item[0])
        except AttributeError as exc:
            raise SafeReplImportError(
                f"Cannot import attribute {item[0]!r} from module {module[0]!r}: {exc}"
            ) from exc
        except Exception as exc:
            raise SafeReplImportError(
                f"Cannot import attribute {item[0]!r} from module {module[0]!r}: {exc}"
            ) from exc
        names.append(item)

    return {"module": module, "names": names}


def normalize_validate_imports(specs: list[str]) -> list[NormalizedImportSpec]:
    """Normalize a list of import spec strings into structured specs.

    Filters out empty/whitespace-only specs.
    """
    return [normalize_validate_import(s) for s in specs if s.strip()]


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
