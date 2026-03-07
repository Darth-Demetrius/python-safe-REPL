"""AST safety validation helpers.

Contains node-level checks used to enforce assignment, call, and attribute
access rules under the active permission policy.
"""

import ast

from .policy import PermissionLevel, Permissions


def extract_root_name(node: ast.expr) -> str | None:
    """Return root name for a subscript chain, if rooted at a variable.

    Example: `arr[0][1]` -> `arr`.
    """
    while isinstance(node, ast.Subscript):
        node = node.value
    return node.id if isinstance(node, ast.Name) else None


def is_literal_value(node: ast.expr) -> bool:
    """Return true when node is a container/scalar literal AST expression."""
    return isinstance(node, (ast.Constant, ast.List, ast.Dict, ast.Tuple, ast.Set))


def can_access_attribute(node: ast.expr, allowed_names: set[str], perms: Permissions) -> bool:
    """Check whether attribute access on `node` is allowed for this level."""
    if perms.level >= PermissionLevel.UNSUPERVISED:
        return True
    if perms.level <= PermissionLevel.MINIMUM:
        return False
    if is_literal_value(node):
        return True
    if not isinstance(node, ast.Name):
        return False
    if node.id in perms.imported_symbols:
        return True
    if perms.level >= PermissionLevel.PERMISSIVE and node.id in allowed_names:
        return True
    return False


def is_unsafe_attribute(attr: str) -> bool:
    """Block private/dunder attribute names."""
    return attr.startswith("_")


def validate_assignment_target(target: ast.expr, user_vars: dict[str, object], perms: Permissions) -> None:
    """Validate assignment target shape under active permissions.

    Allowed:
    - name assignment (`x = ...`)
    - unpacking (except in MINIMUM)
    - subscript/slice assignment only on existing user vars
    """
    if isinstance(target, ast.Name):
        return

    if isinstance(target, (ast.Tuple, ast.List)):
        if perms.level <= PermissionLevel.MINIMUM:
            raise ValueError("Unpacking assignment is not allowed in MINIMUM mode.")
        for element in target.elts:
            actual_target = element.value if isinstance(element, ast.Starred) else element
            validate_assignment_target(actual_target, user_vars, perms)
        return

    if isinstance(target, ast.Subscript):
        root = extract_root_name(target)
        if root and root in user_vars:
            return
        raise ValueError("Subscript/slice assignment is only allowed on existing user variables.")

    raise ValueError("Unsupported assignment target.")


def validate_call(call: ast.Call, allowed_names: set[str], perms: Permissions) -> None:
    """Validate function/method call target against symbol and attribute rules."""
    func = call.func

    if isinstance(func, ast.Name):
        if func.id not in perms.allowed_symbols and func.id not in allowed_names:
            raise ValueError(f"Function '{func.id}' is not allowed.")
    elif isinstance(func, ast.Lambda):
        pass
    elif isinstance(func, ast.Attribute):
        if is_unsafe_attribute(func.attr):
            raise ValueError("Private methods are not allowed.")
        if not can_access_attribute(func.value, allowed_names, perms):
            raise ValueError("Attribute access not allowed at this permission level.")
    else:
        raise ValueError("Unsupported call target.")


def _collect_defined_and_assigned_names(tree: ast.AST) -> set[str]:
    """Collect names introduced by this snippet for call/attribute validation."""
    defined_names = {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.ClassDef))
    }
    assigned_names = {
        node.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store)
    }
    return defined_names | assigned_names


def _validate_attribute_node(node: ast.Attribute, allowed_names: set[str], perms: Permissions) -> None:
    """Validate one attribute node against private-name and access rules."""
    if is_unsafe_attribute(node.attr):
        raise ValueError("Private attributes are not allowed.")
    if not can_access_attribute(node.value, allowed_names, perms):
        raise ValueError("Attribute access not allowed at this permission level.")


def _validate_tree_node(
    node: ast.AST,
    *,
    user_vars: dict[str, object],
    allowed_names: set[str],
    perms: Permissions,
) -> None:
    """Validate one AST node against policy, assignment, and call constraints."""
    if not isinstance(node, perms.allowed_node_tuple):
        raise ValueError("Unsupported syntax.")

    if isinstance(node, ast.Name) and node.id == "__builtins__":
        raise ValueError("Unsupported identifier.")

    if isinstance(node, ast.Attribute):
        _validate_attribute_node(node, allowed_names, perms)
        return

    if isinstance(node, ast.Assign):
        for target in node.targets:
            validate_assignment_target(target, user_vars, perms)
        return

    if isinstance(node, ast.AugAssign):
        validate_assignment_target(node.target, user_vars, perms)
        return

    if isinstance(node, ast.Call):
        validate_call(node, allowed_names, perms)


def validate_ast(
    tree: ast.AST,
    user_vars: dict[str, object],
    allowed_names: set[str],
    perms: Permissions,
) -> None:
    """Validate parsed AST against node, identifier, call, and assignment rules."""
    allowed_names |= _collect_defined_and_assigned_names(tree)

    for node in ast.walk(tree):
        _validate_tree_node(
            node,
            user_vars=user_vars,
            allowed_names=allowed_names,
            perms=perms,
        )
