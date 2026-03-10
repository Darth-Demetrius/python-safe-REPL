import ast

import pytest

from safe_repl import PermissionLevel, Permissions, validate_ast


def test_package_validate_ast_validates_with_expected_rules() -> None:
    perms = Permissions(base_perms=PermissionLevel.LIMITED)
    tree = ast.parse("msg.upper()", mode="exec")

    with pytest.raises(ValueError, match="Attribute access not allowed"):
        validate_ast(
            tree,
            user_vars={"msg": "hello"},
            allowed_names={"msg"},
            perms=perms,
        )


def test_package_exports_validate_ast_symbols() -> None:
    perms = Permissions(base_perms=PermissionLevel.LIMITED)
    tree = ast.parse("42", mode="exec")

    validate_ast(tree, user_vars={}, allowed_names=set(), perms=perms)
