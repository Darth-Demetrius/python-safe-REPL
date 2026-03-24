import ast

import pytest

from safe_repl import PermissionLevel, Permissions, validate_ast


def test_package_validate_ast_validates_with_expected_rules() -> None:
    perms = Permissions(perm_level=PermissionLevel.CONTROLLED)
    tree = ast.parse("msg.upper()", mode="exec")

    with pytest.raises(ValueError, match="Attribute access not allowed"):
        validate_ast(
            tree,
            user_vars={"msg": "hello"},
            allowed_names={"msg"},
            perms=perms,
        )


def test_package_exports_validate_ast_symbols() -> None:
    perms = Permissions(perm_level=PermissionLevel.CONTROLLED)
    tree = ast.parse("42", mode="exec")

    validate_ast(tree, user_vars={}, allowed_names=set(), perms=perms)


@pytest.mark.parametrize(
    "code",
    [
        "_secret",
        "_secret = 1",
        "def _helper():\n    return 1",
        "def helper(_value):\n    return _value",
    ],
)
def test_validate_ast_blocks_private_and_dunder_names(code: str) -> None:
    perms = Permissions(perm_level=PermissionLevel.TRUSTED)
    tree = ast.parse(code, mode="exec")

    with pytest.raises(ValueError, match="Private and dunder names are not allowed"):
        validate_ast(tree, user_vars={}, allowed_names=set(), perms=perms)


def test_validate_ast_blocks_private_import_aliases() -> None:
    perms = Permissions(perm_level=PermissionLevel.TRUSTED)
    tree = ast.parse("import math as _math", mode="exec")

    with pytest.raises(ValueError, match="Private and dunder names are not allowed"):
        validate_ast(tree, user_vars={}, allowed_names=set(), perms=perms)


def test_validate_ast_allows_calls_to_locally_introduced_function_args() -> None:
    perms = Permissions(perm_level=PermissionLevel.CONTROLLED)
    tree = ast.parse("def apply(fn, value):\n    return fn(value)", mode="exec")

    validate_ast(tree, user_vars={}, allowed_names=set(), perms=perms)


def test_validate_ast_allows_same_snippet_trusted_import_usage() -> None:
    perms = Permissions(perm_level=PermissionLevel.TRUSTED)
    tree = ast.parse("from math import sqrt\nvalue = sqrt(16)", mode="exec")

    validate_ast(tree, user_vars={}, allowed_names=set(), perms=perms)
