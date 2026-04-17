"""Import specification parsing and policy-aware import guard factory.

Responsibilities
----------------
* Parse and validate user-supplied import specs (``module``, ``module as alias``,
  ``module:name``, ``module:*``) – identical to the original ``safe_repl.imports``.
* Build a ``__import__`` replacement function that enforces per-module / per-symbol
  allow/block rules from ``ResPy_imports_policy_tables`` at runtime.

The import guard is injected into the ``__builtins__`` dict that RestrictedPython
executes code with.  This means every ``import`` statement (which RestrictedPython
compiles into a ``__import__`` call) is automatically subject to the policy.
"""

from __future__ import annotations

import argparse
import builtins
import importlib
from typing import TYPE_CHECKING

from .imports_policy_tables import DEFAULT_IMPORTS_ALLOW, DEFAULT_IMPORTS_BLOCK

if TYPE_CHECKING:
    pass

# ``{ (module_name, module_alias): {(import_name, import_alias), ...}, ... }``
NormalizedImportSpec = dict[tuple[str, str], set[tuple[str, str]]]


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class SafeReplImportError(ValueError):
    """Raised when an import spec cannot be resolved or is disallowed."""


class SafeReplCliArgError(ValueError):
    """Raised when CLI arguments are invalid (e.g. bad node names)."""


# ---------------------------------------------------------------------------
# Spec parsing helpers  (unchanged from original safe_repl.imports)
# ---------------------------------------------------------------------------

def _parse_symbol_alias(item: str) -> tuple[str, str]:
    """Parse ``name`` or ``name as alias`` into ``(source_name, alias)``."""
    source_name, has_alias, alias = item.partition(" as ")
    source_name, alias = source_name.strip(), alias.strip()
    if has_alias and not alias:
        raise SafeReplImportError(f"Invalid import symbol spec: {item!r}")
    alias = alias or source_name

    if (
        not source_name
        or any(ch.isspace() for ch in source_name)
        or any(ch.isspace() for ch in alias)
    ):
        raise SafeReplImportError(f"Invalid import symbol spec: {item!r}")
    return source_name, alias


def normalize_validate_import(spec: str) -> NormalizedImportSpec:
    """Normalize one CLI import spec into a structured, picklable representation.

    Output Format: ``{ (module_name, module_alias): {(import_name, import_alias), ...} }``

    Args:
        spec: Import spec string, e.g. ``"math:sqrt"`` or ``"numpy as np:*"``.

    Returns:
        Normalized import spec dict.

    Raises:
        SafeReplImportError: If the module or any requested attribute cannot be
            imported / resolved.
    """
    module_raw, _, imports = spec.partition(":")
    module = _parse_symbol_alias(module_raw)

    try:
        importlib.import_module(module[0])
    except Exception as exc:
        raise SafeReplImportError(
            f"Cannot import module {module[0]!r}: {exc}"
        ) from exc

    names: set[tuple[str, str]] = set()
    import_items = [item.strip() for item in imports.split(",") if item.strip()]

    for item in import_items:
        parsed = _parse_symbol_alias(item)
        if parsed[0] == "*":
            if len(import_items) > 1:
                raise SafeReplImportError(
                    "Cannot combine star import with other imports"
                )
            module_obj = importlib.import_module(module[0])
            export_names = getattr(module_obj, "__all__", None)
            if export_names is None:
                export_names = [n for n in dir(module_obj) if not n.startswith("_")]
            for nm in export_names:
                names.add((nm, nm))
            break
        try:
            module_obj = importlib.import_module(module[0])
            getattr(module_obj, parsed[0])
        except AttributeError as exc:
            raise SafeReplImportError(
                f"Cannot import {parsed[0]!r} from {module[0]!r}: {exc}"
            ) from exc
        except Exception as exc:
            raise SafeReplImportError(
                f"Cannot import {parsed[0]!r} from {module[0]!r}: {exc}"
            ) from exc
        names.add(parsed)

    return {module: names}


def normalize_validate_imports(specs: list[str]) -> NormalizedImportSpec:
    """Normalize a list of import spec strings, filtering empty entries."""
    return imports_union(*(normalize_validate_import(s) for s in specs if s.strip()))


def imports_union(*imports: NormalizedImportSpec) -> NormalizedImportSpec:
    """Merge multiple normalized import specs by module."""
    merged: NormalizedImportSpec = {}
    for import_spec in imports:
        for module, names in import_spec.items():
            if module not in merged:
                merged[module] = set(names)
            else:
                merged[module].update(names)
    return merged


def collect_import_symbols(imports: NormalizedImportSpec) -> set[str]:
    """Return the set of alias names introduced into scope by the import specs."""
    result: set[str] = set()
    for (module_name, module_alias), names in imports.items():
        if module_alias != module_name:
            result.add(module_alias)
        for _import_name, import_alias in names:
            result.add(import_alias)
    return result


# ---------------------------------------------------------------------------
# Policy-aware import guard
# ---------------------------------------------------------------------------

def _collect_allowed_symbols_for_module(module_name: str, level: int) -> set[str] | None:
    """Return the set of allowed symbols for *module_name* at *level*.

    Returns ``None`` when the module is not listed in the allow table (i.e.
    the module is not explicitly allowed at *level* or any lower level).

    Returns an empty set if the module is allowed but no specific symbols are
    listed (everything is blocked after applying block rules).
    """
    allow_table = DEFAULT_IMPORTS_ALLOW.get(module_name)
    if allow_table is None:
        return None

    # Accumulate allow rules from level 1 up to (and including) current level.
    allowed: set[str] = set()
    for lvl in range(1, level + 1):
        symbols = allow_table.get(lvl)
        if symbols:
            allowed.update(symbols)

    if not allowed:
        return None  # Module listed but no rule applies at this level.

    # Accumulate block rules.
    block_table = DEFAULT_IMPORTS_BLOCK.get(module_name, {})
    blocked: set[str] = set()
    for lvl in range(1, level + 1):
        b = block_table.get(lvl)
        if b:
            blocked.update(b)

    if "*" in allowed:
        # All public symbols allowed except explicitly blocked ones;
        # return sentinel so callers know "everything minus blocked".
        return blocked  # caller interprets as "blocked set" when "*" is present

    return allowed - blocked


def _check_module_allowed(module_name: str, level: int) -> bool:
    """Return True if *module_name* is accessible at *level*."""
    # Walk up the module hierarchy: "numpy.linalg" → "numpy" first.
    parts = module_name.split(".")
    for end in range(len(parts), 0, -1):
        candidate = ".".join(parts[:end])
        if candidate in DEFAULT_IMPORTS_ALLOW:
            result = _collect_allowed_symbols_for_module(candidate, level)
            return result is not None
    return False


def make_import_guard(
    allowed_imports: NormalizedImportSpec,
    *,
    level: int,
) -> "type[object]":
    """Return a ``__import__`` replacement that enforces import policy.

    The guard is intended for injection into the ``__builtins__`` dict used
    during restricted execution.

    Args:
        allowed_imports: Explicitly pre-approved imports (from ``Permissions``).
        level: Numeric permission level (1–3).

    Returns:
        A callable with the same signature as the built-in ``__import__``.
    """
    # Build a quick lookup of explicitly pre-approved module names.
    _explicit_modules: set[str] = {mod_name for (mod_name, _) in allowed_imports}

    def _import(
        name: str,
        globals: dict | None = None,
        locals: dict | None = None,
        fromlist: tuple = (),
        level_arg: int = 0,
    ) -> object:
        # 1. Explicit user-approved imports always pass through.
        root_name = name.split(".")[0]
        if root_name in _explicit_modules or name in _explicit_modules:
            return builtins.__import__(name, globals, locals, fromlist, level_arg)

        # 2. Check against policy tables.
        if not _check_module_allowed(name, level):
            raise ImportError(
                f"Import of {name!r} is not allowed at permission level {level}."
            )

        # 3. Validate fromlist symbols against per-module block rules.
        if fromlist:
            block_table = DEFAULT_IMPORTS_BLOCK.get(name, {})
            blocked: set[str] = set()
            for lvl in range(1, level + 1):
                b = block_table.get(lvl)
                if b:
                    blocked.update(b)
            for sym in fromlist:
                if sym != "*" and sym in blocked:
                    raise ImportError(
                        f"Import of {sym!r} from {name!r} is not allowed "
                        f"at permission level {level}."
                    )

        return builtins.__import__(name, globals, locals, fromlist, level_arg)

    return _import  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# CLI argument validation helper
# ---------------------------------------------------------------------------

def validate_cli_args(args: argparse.Namespace) -> None:
    """Validate CLI ``--allow-functions`` / ``--block-functions`` argument values.

    Unlike the original, there are no ``--allow-nodes`` / ``--block-nodes`` args
    because RestrictedPython manages node-level restrictions internally.

    Raises:
        SafeReplCliArgError: (currently a no-op placeholder; kept for API parity).
    """
    # Symbol args are plain strings – nothing to resolve against a registry.
    pass
