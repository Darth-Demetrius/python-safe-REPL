"""AST safety validation helpers.

Contains node-level checks used to enforce assignment, call, and attribute
access rules under the active permission policy.
"""

import ast
from dataclasses import dataclass
from functools import singledispatchmethod

from .policy import PermissionLevel, Permissions
from .policy_tables import LITERALS

# Module-level type tuples to avoid re-allocating on each call
LITERAL_NODE_TYPES = tuple(LITERALS)


@dataclass(slots=True)
class ValidationContext:
    """Resolved validator state for a single parsed snippet."""
    user_vars: dict[str, object]
    visible_names: set[str]
    perms: Permissions
    allowed_node_types: tuple[type[ast.AST], ...]


def validate_ast(
    tree: ast.AST,
    user_vars: dict[str, object],
    allowed_names: set[str],
    perms: Permissions,
) -> None:
    """Validate parsed AST against node, identifier, call, and assignment rules."""
    AstValidator(user_vars, allowed_names, perms).validate(tree)


class AstValidator:
    """Validate one parsed AST against the active execution policy."""
    def __init__(
        self,
        user_vars: dict[str, object],
        allowed_names: set[str],
        perms: Permissions,
    ) -> None:
        self.context = ValidationContext(
            user_vars=user_vars,
            visible_names=set(allowed_names),
            perms=perms,
            allowed_node_types=perms.allowed_nodes_tuple,
        )
        # singledispatchmethod registry is used for node handlers below.

    @staticmethod
    def _bound_name_from_alias(node: ast.alias) -> str:
        if node.asname is not None:
            return node.asname
        return node.name.split(".", 1)[0]

    def validate(self, tree: ast.AST) -> None:
        """Walk ``tree`` once and validate each node under the active policy."""
        self.context.visible_names.update(self._collect_local_names(tree))

        stack: list[tuple[ast.AST, ast.AST | None]] = [(tree, None)]
        while stack:
            node, parent = stack.pop()
            self._validate_node(node, parent)
            for child in ast.iter_child_nodes(node):
                stack.append((child, node))

    def _validate_node(self, node: ast.AST, parent: ast.AST | None) -> None:
        if isinstance(node, ast.Attribute):
            self._handle_attribute(node, parent)

        if not isinstance(node, self.context.allowed_node_types):
            raise ValueError("Unsupported syntax.")

        name, names = None, None
        match node:
            case (
                ast.arg(arg=name) |
                ast.AsyncFunctionDef(name=name) |
                ast.ClassDef(name=name) |
                ast.ExceptHandler(name=name) |
                ast.FunctionDef(name=name) |
                ast.keyword(arg=name) |
                ast.Name(id=name)
            ) if name is not None:
                self._validate_public_name(name)
            case ast.Global(names=names) | ast.Nonlocal(names=names):
                for name in names:
                    self._validate_public_name(name)
            case ast.alias(name=name):
                for part in name.split("."):
                    self._validate_public_name(part)
                self._validate_public_name(self._bound_name_from_alias(node))
            case ast.ImportFrom(module=name) if name is not None:
                for part in name.split("."):
                    self._validate_public_name(part)
            case ast.Assign(targets=names):
                for name in names:
                    self._validate_assignment_target(name)
            case ast.AugAssign(target=name):
                self._validate_assignment_target(name)
            case ast.Call():
                self._validate_call(node)
            case _:
                pass

    def _validate_call(self, node: ast.Call) -> None:
        match node.func:
            case ast.Name(id=name):
                if (name not in self.context.perms.allowed_symbols
                and name not in self.context.visible_names):
                    raise ValueError(f"Function '{name}' is not allowed.")
            case ast.Lambda() | ast.Attribute():
                return
            case _:
                raise ValueError("Unsupported call target.")

    def _handle_attribute(self, node: ast.Attribute, parent: ast.AST | None) -> None:
        if node.attr.startswith("_"):
            if isinstance(parent, ast.Call) and parent.func is node:
                raise ValueError("Private methods are not allowed.")
            raise ValueError("Private attributes are not allowed.")

        if node.attr in self.context.perms.allowed_symbols:
            return

        raise ValueError(f"Attribute access '{node.attr}' is not allowed.")

    def _collect_local_names(self, tree: ast.AST) -> set[str]:
        names: set[str] = set()
        for node in ast.walk(tree):
            match node:
                case (
                    ast.arg(arg=name) |
                    ast.AsyncFunctionDef(name=name) |
                    ast.ExceptHandler(name=name) |
                    ast.FunctionDef(name=name) |
                    ast.ClassDef(name=name) |
                    ast.MatchAs(name=name) |
                    ast.MatchStar(name=name) |
                    ast.Name(id=name)
                ) if name is not None:
                    names.add(name)
                case ast.alias():
                    names.add(self._bound_name_from_alias(node))
        return names

    def _validate_public_name(self, name: str) -> None:
        if name.startswith("_"):
            raise ValueError("Private and dunder names are not allowed.")

    def _validate_assignment_target(self, target: ast.expr) -> None:
        match target:
            case ast.Name():
                return

            case ast.Tuple() | ast.List():
                if self.context.perms.level <= PermissionLevel.RESTRICTED:
                    raise ValueError("Unpacking assignment is not allowed in RESTRICTED mode.")
                for element in target.elts:
                    actual_target = element.value if isinstance(element, ast.Starred) else element
                    self._validate_assignment_target(actual_target)

            case ast.Subscript():
                target = target.value
                while isinstance(target, ast.Subscript):
                    target = target.value
                root = target.id if isinstance(target, ast.Name) else None
                if root and root in self.context.user_vars:
                    return
                raise ValueError("Subscript/slice assignment is only allowed on existing user variables.")

            case _:
                raise ValueError("Unsupported assignment target.")
