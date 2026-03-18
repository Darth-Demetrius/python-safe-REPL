"""Import specification parsing and CLI argument validation utilities."""

import argparse
import ast
import importlib

# { (module_name, module_alias): {(import_name, import_alias), ...}, ... }
NormalizedImportSpec = dict[tuple[str, str], set[tuple[str, str]]]


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
    resolution. It is formatted as such:
    { (module_name, module_alias): {(import_name, import_alias), ...}, ... }
    
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

    names: set[tuple[str, str]] = set()
    import_items = [item.strip() for item in imports.split(",") if item.strip()]

    for item in import_items:
        item = _parse_symbol_alias(item)
        if item[0] == "*":
            if len(import_items) > 1:
                raise SafeReplImportError("Cannot combine star import with other imports")
            module_obj = importlib.import_module(module[0])
            export_names = getattr(module_obj, "__all__", None)
            if export_names is None:
                export_names = [n for n in dir(module_obj) if not n.startswith("_")]
            for nm in export_names:
                names.add((nm, nm))
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
        names.add(item)

    return {module: names}


def normalize_validate_imports(specs: list[str]) -> NormalizedImportSpec:
    """Normalize a list of import spec strings into structured specs.

    Filters out empty/whitespace-only specs.
    """
    return imports_union(*(normalize_validate_import(s) for s in specs if s.strip()))


def imports_union(*imports: NormalizedImportSpec) -> NormalizedImportSpec:
    """Merge normalized import specs by module, keeping aliases separate."""
    merged: NormalizedImportSpec = {}
    for import_spec in imports:
        for module, names in import_spec.items():
            if module not in merged:
                merged[module] = set(names)
            else:
                merged[module].update(names)

    return merged


def imports_intersection(*imports: NormalizedImportSpec) -> NormalizedImportSpec:
    """Intersect normalized import specs by module, keeping aliases separate.
    
    I do not anticipate this function ever being used, so I have not implemented any alias
    reconciliation logic. Thus, this currently requires module aliases to match exactly
    across specs to be included in the intersection.
    """
    if not imports:
        return {}

    # Start with the first spec and iteratively intersect with the rest.
    merged: NormalizedImportSpec = {
        module: set(names)
        for module, names in imports[0].items()
    }
    for _import in imports[1:]:
        new_intersection: NormalizedImportSpec = {}
        for module, names in merged.items():
            if module in _import:
                # Intersect the sets of names for this module.
                common_names = names.intersection(_import[module])
                if common_names:
                    new_intersection[module] = common_names
        merged = new_intersection

    return merged


def collect_import_symbols(imports: NormalizedImportSpec) -> set[str]:
    """Extract imported symbol aliases from normalized import specs.

    This reproduces the logic used by callers that need the set of
    names/aliases that the import specs introduce into scope.
    """
    result: set[str] = set()
    for (_module_name, module_alias), names in imports.items():
        if not names:
            # If no names are specified, the module alias (or name) is the only symbol added.
            if module_alias:
                result.add(module_alias)
            continue

        for _import_name, import_alias in names:
            result.add(import_alias)

    return result


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
