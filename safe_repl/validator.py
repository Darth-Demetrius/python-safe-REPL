"""AST safety validation helpers.

Contains node-level checks used to enforce assignment, call, and attribute
access rules under the active permission policy.
"""

import ast

from .policy import PermissionLevel, Permissions

# Module-level type tuples to avoid re-allocating on each call
LITERAL_NODE_TYPES = (ast.Constant, ast.List, ast.Dict, ast.Tuple, ast.Set)
ASSIGNABLE_CONTAINER_NODES = (ast.Tuple, ast.List)


def extract_root_name(node: ast.expr) -> str | None:
    """Return root name for a subscript chain, if rooted at a variable.

    Example: `arr[0][1]` -> `arr`.
    """
    while isinstance(node, ast.Subscript):
        node = node.value
    return node.id if isinstance(node, ast.Name) else None


def can_access_attribute(node: ast.expr, allowed_names: set[str], perms: Permissions) -> bool:
    """Check whether attribute access on `node` is allowed for this level."""
    if perms.level >= PermissionLevel.UNSUPERVISED:
        return True
    if perms.level <= PermissionLevel.MINIMUM:
        return False
    if isinstance(node, LITERAL_NODE_TYPES):
        return True
    if not isinstance(node, ast.Name):
        return False
    if node.id in perms.imported_symbols:
        return True
    if perms.level >= PermissionLevel.PERMISSIVE and node.id in allowed_names:
        return True
    return False


def validate_assignment_target(target: ast.expr, user_vars: dict[str, object], perms: Permissions) -> None:
    """Validate assignment target shape under active permissions.

    Allowed:
    - name assignment (`x = ...`)
    - unpacking (except in MINIMUM)
    - subscript/slice assignment only on existing user vars
    """
    match target:
        case ast.Name():
            return

        case ast.Tuple() | ast.List():
            if perms.level <= PermissionLevel.MINIMUM:
                raise ValueError("Unpacking assignment is not allowed in MINIMUM mode.")
            for element in target.elts:
                actual_target = element.value if isinstance(element, ast.Starred) else element
                validate_assignment_target(actual_target, user_vars, perms)

        case ast.Subscript():
            root = extract_root_name(target)
            if root and root in user_vars:
                return
            raise ValueError("Subscript/slice assignment is only allowed on existing user variables.")

        case _:
            raise ValueError("Unsupported assignment target.")


def validate_call(call: ast.Call, allowed_names: set[str], perms: Permissions) -> None:
    """Validate function/method call target against symbol and attribute rules."""
    func = call.func
    match func:
        case ast.Name(id=name):
            if name not in perms.allowed_symbols and name not in allowed_names:
                raise ValueError(f"Function '{name}' is not allowed.")

        case ast.Lambda():
            return

        # Attribute nodes are validated separately when visited as AST nodes.
        case ast.Attribute():
            return

        case _:
            raise ValueError("Unsupported call target.")


def _collect_defined_and_assigned_names(tree: ast.AST) -> set[str]:
    """Collect names introduced by this snippet for call/attribute validation."""
    defined_names: set[str] = set()
    assigned_names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
            defined_names.add(node.name)
        elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            assigned_names.add(node.id)
    return defined_names | assigned_names


# Module-level handlers used by the dispatch-table validator.
def _handle_attribute(node: ast.Attribute, parent: ast.AST | None, user_vars: dict[str, object], allowed_names: set[str], perms: Permissions) -> None:
    if node.attr.startswith("_"):
        if isinstance(parent, ast.Call) and parent.func is node:
            raise ValueError("Private methods are not allowed.")
        raise ValueError("Private attributes are not allowed.")
    if not can_access_attribute(node.value, allowed_names, perms):
        raise ValueError("Attribute access not allowed at this permission level.")


def _handle_assign(node: ast.Assign, parent: ast.AST | None, user_vars: dict[str, object], allowed_names: set[str], perms: Permissions) -> None:
    for target in node.targets:
        validate_assignment_target(target, user_vars, perms)


def _handle_augassign(node: ast.AugAssign, parent: ast.AST | None, user_vars: dict[str, object], allowed_names: set[str], perms: Permissions) -> None:
    validate_assignment_target(node.target, user_vars, perms)


def _handle_call(node: ast.Call, parent: ast.AST | None, user_vars: dict[str, object], allowed_names: set[str], perms: Permissions) -> None:
    validate_call(node, allowed_names, perms)


def _handle_name(node: ast.Name, parent: ast.AST | None, user_vars: dict[str, object], allowed_names: set[str], perms: Permissions) -> None:
    if getattr(node, "id", None) == "__builtins__":
        raise ValueError("Unsupported identifier.")


_handlers = {
    ast.Assign: _handle_assign,
    ast.AugAssign: _handle_augassign,
    ast.Call: _handle_call,
    ast.Name: _handle_name,
}


def validate_ast(
    tree: ast.AST,
    user_vars: dict[str, object],
    allowed_names: set[str],
    perms: Permissions,
) -> None:
    """Validate parsed AST against node, identifier, call, and assignment rules.

    Implementation: single-pass walker with a dispatch-table of handlers.
    """
    collected = _collect_defined_and_assigned_names(tree)
    local_allowed = allowed_names | collected

    allowed_node_tuple = perms.allowed_node_tuple
    handlers_get = _handlers.get
    iter_children = ast.iter_child_nodes

    # Single-pass walker with dispatch
    stack: list[tuple[ast.AST, ast.AST | None]] = [(tree, None)]
    while stack:
        node, parent = stack.pop()

        # Attribute nodes need to be checked regardless of allowed-node masking
        if isinstance(node, ast.Attribute):
            _handle_attribute(node, parent, user_vars, local_allowed, perms)

        if not isinstance(node, allowed_node_tuple):
            raise ValueError("Unsupported syntax.")

        handler = handlers_get(type(node))
        if handler is not None:
            handler(node, parent, user_vars, local_allowed, perms)

        for child in iter_children(node):
            stack.append((child, node))
