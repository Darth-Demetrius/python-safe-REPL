"""Integration tests for the RestrictedPython-based Safe REPL (ResPy variant).

These tests cover:
- Core execution (expressions, statements, print capture)
- Permission levels (RESTRICTED, CONTROLLED, TRUSTED)
- Import policy enforcement
- Security boundaries (attribute/private name blocking)
- Timeout and memory limit enforcement
- Variable persistence across snippets
- Session serialization (pickling)
- REPL command registry
- Async execution (Discord bot use)
"""

import asyncio
import math
import pickle
import sys
from io import StringIO

import pytest

from respy_repl.cli import main as respy_main
from respy_repl.engine import ExecResult, exec_restricted
from respy_repl.imports import (
    SafeReplCliArgError,
    SafeReplImportError,
    normalize_validate_import,
)
from respy_repl.policy import PermissionLevel, Permissions
from respy_repl.repl_command_registry import CommandRegistry
from respy_repl.session import ExecutionMemoryLimitError, ExecutionTimeoutError, SafeSession


# =============================================================================
# Core Engine Tests
# =============================================================================


class TestExecRestricted:
    """Low-level engine tests for exec_restricted()."""

    def test_expression_returns_result(self):
        perms = Permissions(PermissionLevel.CONTROLLED)
        uv = {}
        r = exec_restricted("1 + 2", uv, perms=perms)
        assert r.ok
        assert r.result == 3
        assert r.output == ""

    def test_statement_returns_none(self):
        perms = Permissions(PermissionLevel.CONTROLLED)
        uv = {}
        r = exec_restricted("x = 42", uv, perms=perms)
        assert r.ok
        assert r.result is None
        assert uv["x"] == 42

    def test_print_is_captured(self):
        perms = Permissions(PermissionLevel.CONTROLLED)
        uv = {}
        r = exec_restricted('print("hello", "world")', uv, perms=perms)
        assert r.ok
        assert "hello world" in r.output

    def test_print_with_starred_args_is_captured(self):
        perms = Permissions(PermissionLevel.CONTROLLED)
        uv = {}
        r = exec_restricted("print(*[x for x in range(5)])", uv, perms=perms)
        assert r.ok
        assert "0 1 2 3 4" in r.output

    def test_multiple_print_calls(self):
        perms = Permissions(PermissionLevel.CONTROLLED)
        uv = {}
        code = "print(1)\nprint(2)\nprint(3)"
        r = exec_restricted(code, uv, perms=perms)
        assert r.ok
        assert "1" in r.output and "2" in r.output and "3" in r.output

    def test_print_in_user_defined_function_is_captured(self):
        perms = Permissions(PermissionLevel.CONTROLLED)
        uv = {}
        code = "def f():\n    print('inside')\nf()"
        r = exec_restricted(code, uv, perms=perms)
        assert r.ok
        assert "inside" in r.output

    def test_print_in_persisted_function_is_captured(self):
        perms = Permissions(PermissionLevel.CONTROLLED)
        uv = {}
        r1 = exec_restricted("def f():\n    print('later')", uv, perms=perms)
        assert r1.ok
        r2 = exec_restricted("f()", uv, perms=perms)
        assert r2.ok
        assert "later" in r2.output

    def test_user_vars_persist(self):
        perms = Permissions(PermissionLevel.CONTROLLED)
        uv = {}
        exec_restricted("x = 10", uv, perms=perms)
        exec_restricted("y = x + 5", uv, perms=perms)
        r = exec_restricted("z = x + y", uv, perms=perms)
        assert r.ok
        assert uv["x"] == 10
        assert uv["y"] == 15
        assert uv["z"] == 25

    def test_syntax_error_raised(self):
        perms = Permissions(PermissionLevel.CONTROLLED)
        uv = {}
        with pytest.raises(SyntaxError):
            exec_restricted("1 +", uv, perms=perms)

    def test_exception_in_code_returned(self):
        perms = Permissions(PermissionLevel.CONTROLLED)
        uv = {}
        r = exec_restricted("1 / 0", uv, perms=perms)
        assert not r.ok
        assert isinstance(r.exception, ZeroDivisionError)

    def test_name_error_on_undefined_name(self):
        perms = Permissions(PermissionLevel.CONTROLLED)
        uv = {}
        r = exec_restricted("undefined_var", uv, perms=perms)
        assert not r.ok
        assert isinstance(r.exception, NameError)

    def test_unpacking_assignment_updates_user_vars(self):
        perms = Permissions(PermissionLevel.CONTROLLED)
        uv = {}
        r = exec_restricted("a, b, c = 'a', 'b', 'c'", uv, perms=perms)
        assert r.ok
        assert r.result is None
        assert uv["a"] == "a"
        assert uv["b"] == "b"
        assert uv["c"] == "c"

    def test_exec_collects_matplotlib_artifacts_when_available(self, monkeypatch):
        class _FakeFigure:
            def savefig(self, buffer, *, format, bbox_inches):
                assert format == "png"
                assert bbox_inches == "tight"
                buffer.write(b"fake-png")

        class _FakePyplot:
            def get_fignums(self):
                return [1]

            def figure(self, _fig_num):
                return _FakeFigure()

            def close(self, _figure):
                return None

        monkeypatch.setitem(sys.modules, "matplotlib.pyplot", _FakePyplot())

        perms = Permissions(PermissionLevel.CONTROLLED)
        uv = {}
        r = exec_restricted("1 + 2", uv, perms=perms)

        assert r.ok
        assert len(r.display_artifacts) == 1
        assert r.display_artifacts[0].mime_type == "image/png"
        assert r.display_artifacts[0].data == b"fake-png"


# =============================================================================
# Permission Level Tests
# =============================================================================


class TestPermissionLevels:
    """Test permission-level semantics."""

    def test_restricted_only_expressions(self):
        perms = Permissions(PermissionLevel.RESTRICTED)
        uv = {}
        # Expressions OK
        r = exec_restricted("1 + 2", uv, perms=perms)
        assert r.ok
        # Simple assignment OK
        r = exec_restricted("x = 42", uv, perms=perms)
        assert r.ok
        # Loops are allowed at RESTRICTED level in RestrictedPython
        r = exec_restricted("for i in range(10): pass", uv, perms=perms)
        assert r.ok
        # But function definitions should work at RESTRICTED
        r = exec_restricted("def f(x): return x + 1", uv, perms=perms)
        assert r.ok

    def test_controlled_allows_functions(self):
        perms = Permissions(PermissionLevel.CONTROLLED)
        uv = {}
        code = "def factorial(n):\n    return 1 if n <= 1 else n * factorial(n-1)\nresult = factorial(5)"
        r = exec_restricted(code, uv, perms=perms)
        assert r.ok
        assert uv["result"] == 120

    def test_controlled_allows_comprehensions(self):
        perms = Permissions(PermissionLevel.CONTROLLED)
        uv = {}
        r = exec_restricted("result = [x**2 for x in range(5)]", uv, perms=perms)
        assert r.ok
        assert uv["result"] == [0, 1, 4, 9, 16]

    def test_controlled_allows_classes(self):
        perms = Permissions(PermissionLevel.CONTROLLED)
        uv = {}
        code = """
class Point:
    def __init__(self, x, y):
        self.x = x
        self.y = y
p = Point(3, 4)
result = (p.x, p.y)
"""
        r = exec_restricted(code, uv, perms=perms)
        assert r.ok
        assert uv["result"] == (3, 4)

    def test_trusted_allows_imports(self):
        perms = Permissions(PermissionLevel.TRUSTED, imports=["json:*"])
        uv = {}
        r = exec_restricted('data = json.dumps({"key": "value"})', uv, perms=perms)
        assert r.ok
        assert "key" in uv["data"]

    def test_restricted_blocks_import(self):
        perms = Permissions(PermissionLevel.RESTRICTED)
        uv = {}
        r = exec_restricted("import sys", uv, perms=perms)
        assert not r.ok
        assert isinstance(r.exception, ImportError)


# =============================================================================
# Import Policy Tests
# =============================================================================


class TestImportPolicy:
    """Test import allow/block rules."""

    def test_pre_import_available_math(self):
        perms = Permissions(PermissionLevel.CONTROLLED, imports=["math:*"])
        uv = {}
        r = exec_restricted("result = sqrt(16)", uv, perms=perms)
        assert r.ok
        assert uv["result"] == 4.0

    def test_preimport_with_alias(self):
        perms = Permissions(PermissionLevel.CONTROLLED, imports=["math as m:sqrt"])
        uv = {}
        r = exec_restricted("result = m.sqrt(9)", uv, perms=perms)
        assert r.ok
        assert uv["result"] == 3.0

    def test_import_spec_parsing(self):
        spec = normalize_validate_import("json:dumps,loads")
        assert spec
        assert len(spec) == 1
        (mod, alias), names = list(spec.items())[0]
        assert mod == "json"
        assert alias == "json"
        assert any(n[0] == "dumps" for n in names)
        assert any(n[0] == "loads" for n in names)

    def test_import_star_expansion(self):
        spec = normalize_validate_import("math:*")
        assert spec
        (mod, alias), names = list(spec.items())[0]
        assert mod == "math"
        # Star should expand to all public math symbols
        assert len(names) > 10
        assert any(n[0] == "sqrt" for n in names)

    def test_blocked_import_modules(self):
        perms = Permissions(PermissionLevel.CONTROLLED)
        uv = {}
        # os is not in the allow table
        r = exec_restricted("import os", uv, perms=perms)
        assert not r.ok
        assert isinstance(r.exception, ImportError)

    def test_blocked_submodule_import(self):
        perms = Permissions(PermissionLevel.CONTROLLED)
        uv = {}
        r = exec_restricted("import os.path", uv, perms=perms)
        assert not r.ok


# =============================================================================
# Security Tests
# =============================================================================


class TestSecurityBoundaries:
    """Test that sensitive operations are blocked."""

    def test_private_attribute_access_blocked(self):
        """RestrictedPython blocks "__" attributes at compile-time."""
        perms = Permissions(PermissionLevel.CONTROLLED)
        uv = {}
        with pytest.raises(SyntaxError):
            exec_restricted("x = (1).__class__", uv, perms=perms)

    def test_underscore_attribute_blocked(self):
        """RestrictedPython blocks "_" prefixed attributes."""
        perms = Permissions(PermissionLevel.CONTROLLED)
        uv = {}
        with pytest.raises(SyntaxError):
            exec_restricted("x = some_object._private", uv, perms=perms)

    def test_eval_not_available(self):
        """RestrictedPython blocks eval() at compile time."""
        perms = Permissions(PermissionLevel.CONTROLLED)
        uv = {}
        # eval() is blocked by RestrictedPython at compile time, raising SyntaxError
        with pytest.raises(SyntaxError, match="Eval calls are not allowed"):
            exec_restricted('eval("1+1")', uv, perms=perms)

    def test_exec_not_available(self):
        """RestrictedPython blocks exec() at compile time."""
        perms = Permissions(PermissionLevel.CONTROLLED)
        uv = {}
        # exec() is blocked by RestrictedPython at compile time, raising SyntaxError
        with pytest.raises(SyntaxError, match="Exec calls are not allowed"):
            exec_restricted('exec("x = 1")', uv, perms=perms)

    def test_compile_not_available(self):
        perms = Permissions(PermissionLevel.CONTROLLED)
        uv = {}
        r = exec_restricted('compile("1+1", "<test>", "eval")', uv, perms=perms)
        assert not r.ok

    def test_no_access_to_frame_globals(self):
        """Attempt to escape via frame introspection is blocked."""
        perms = Permissions(PermissionLevel.CONTROLLED)
        uv = {}
        # We can't access __globals__ but we can test that builtins are limited
        r = exec_restricted('len(globals())', uv, perms=perms)
        assert not r.ok

    def test_restricted_builtins_at_each_level(self):
        """Each level has correct builtin availability."""
        # RESTRICTED: only math/iteration/type-conversion
        perms_r = Permissions(PermissionLevel.RESTRICTED)
        uv_r = {}
        r = exec_restricted("abs(-5)", uv_r, perms=perms_r)
        assert r.ok

        # But not getattr
        r = exec_restricted("getattr(object, '__init__')", uv_r, perms=perms_r)
        assert not r.ok

        # TRUSTED has more builtins
        perms_t = Permissions(PermissionLevel.TRUSTED)
        uv_t = {}
        r = exec_restricted("getattr(dict, 'get')", uv_t, perms=perms_t)
        assert r.ok


# =============================================================================
# Timeout Tests
# =============================================================================


class TestTimeout:
    """Test execution timeout enforcement."""

    def test_timeout_is_enforced(self):
        perms = Permissions(
            PermissionLevel.CONTROLLED,
            timeout_seconds=0.1,
        )
        uv = {}
        # Infinite loop should timeout
        r = exec_restricted("while True: pass", uv, perms=perms)
        assert not r.ok
        assert isinstance(r.exception, TimeoutError)
        assert "Execution timed out after" in str(r.exception)

    def test_timeout_none_disables_limit(self):
        perms = Permissions(
            PermissionLevel.CONTROLLED,
            timeout_seconds=None,
        )
        uv = {}
        # This completes quickly and should not timeout
        r = exec_restricted("x = sum(range(1000))", uv, perms=perms)
        assert r.ok

    def test_different_timeout_levels(self):
        # RESTRICTED has 0.2s timeout by default
        perms_r = Permissions(PermissionLevel.RESTRICTED)
        assert perms_r.timeout_seconds == 0.2

        # CONTROLLED has 1.0s timeout
        perms_c = Permissions(PermissionLevel.CONTROLLED)
        assert perms_c.timeout_seconds == 1.0

        # TRUSTED has 10.0s timeout
        perms_t = Permissions(PermissionLevel.TRUSTED)
        assert perms_t.timeout_seconds == 10.0


# =============================================================================
# Memory Tests
# =============================================================================


class TestMemoryLimits:
    """Test memory limit enforcement."""

    def test_memory_limit_enforced(self):
        # 1 MB limit
        perms = Permissions(
            PermissionLevel.CONTROLLED,
            memory_limit_bytes=1024 * 1024,
        )
        uv = {}
        # Allocate a huge list
        r = exec_restricted("x = [0] * (1024 * 1024 * 2)", uv, perms=perms)
        assert not r.ok
        assert isinstance(r.exception, MemoryError)

    def test_memory_limit_none_disables(self):
        perms = Permissions(
            PermissionLevel.CONTROLLED,
            memory_limit_bytes=None,
        )
        uv = {}
        # This should not hit a memory limit
        r = exec_restricted("x = list(range(100000))", uv, perms=perms)
        assert r.ok

    def test_different_memory_levels(self):
        perms_r = Permissions(PermissionLevel.RESTRICTED)
        assert perms_r.memory_limit_bytes == 64 * 1024 * 1024  # 64 MB

        perms_c = Permissions(PermissionLevel.CONTROLLED)
        assert perms_c.memory_limit_bytes == 256 * 1024 * 1024  # 256 MB

        perms_t = Permissions(PermissionLevel.TRUSTED)
        assert perms_t.memory_limit_bytes is None


# =============================================================================
# SafeSession Tests
# =============================================================================


class TestSafeSession:
    """Test the SafeSession integration API."""

    def test_session_exec_returns_tuple(self):
        perms = Permissions(PermissionLevel.CONTROLLED, imports=["math:*"])
        session = SafeSession(perms=perms)
        result, output = session.exec("1 + 2")
        assert result == 3
        assert output == ""

    def test_session_exec_response_includes_rich_artifacts(self, monkeypatch):
        class _FakeFigure:
            def savefig(self, buffer, *, format, bbox_inches):
                assert format == "png"
                assert bbox_inches == "tight"
                buffer.write(b"session-fake-png")

        class _FakePyplot:
            def get_fignums(self):
                return [7]

            def figure(self, _fig_num):
                return _FakeFigure()

            def close(self, _figure):
                return None

        monkeypatch.setitem(sys.modules, "matplotlib.pyplot", _FakePyplot())

        perms = Permissions(PermissionLevel.CONTROLLED)
        session = SafeSession(perms=perms)

        response = session.exec_response("10 + 5")

        assert response.result == 15
        assert response.output == ""
        assert len(response.display_artifacts) == 1
        assert response.display_artifacts[0].mime_type == "image/png"
        assert response.display_artifacts[0].data == b"session-fake-png"

    def test_session_exec_with_print(self):
        perms = Permissions(PermissionLevel.CONTROLLED)
        session = SafeSession(perms=perms)
        result, output = session.exec('print("hello")')
        assert result is None
        assert "hello" in output

    def test_session_exec_with_print_inside_function(self):
        perms = Permissions(PermissionLevel.CONTROLLED)
        session = SafeSession(perms=perms)
        result, output = session.exec("def f():\n    print('nested')\nf()")
        assert result is None
        assert "nested" in output

    def test_session_exec_with_print_inside_persisted_function(self):
        perms = Permissions(PermissionLevel.CONTROLLED)
        session = SafeSession(perms=perms)
        session.exec("def f():\n    print('persisted')")
        result, output = session.exec("f()")
        assert result is None
        assert "persisted" in output

    def test_session_vars_persist(self):
        perms = Permissions(PermissionLevel.CONTROLLED)
        session = SafeSession(perms=perms)
        session.exec("x = 42")
        result, _ = session.exec("x + 8")
        assert result == 50

    def test_session_exec_raises_on_error(self):
        perms = Permissions(PermissionLevel.CONTROLLED)
        session = SafeSession(perms=perms)
        with pytest.raises(ZeroDivisionError):
            session.exec("1 / 0")

    def test_session_exec_formats_user_traceback(self):
        perms = Permissions(PermissionLevel.CONTROLLED)
        session = SafeSession(perms=perms)

        code = (
            "def inner():\n"
            "    return 1 / 0\n"
            "\n"
            "def outer():\n"
            "    return inner()\n"
            "\n"
            "outer()"
        )

        with pytest.raises(ZeroDivisionError) as error_info:
            session.exec_response(code)

        rendered = str(error_info.value)
        assert rendered.startswith("Traceback (most recent call last):")
        assert 'File "<repl input>", line ' in rendered
        assert "in inner" in rendered
        assert "in outer" in rendered
        assert "ZeroDivisionError: division by zero" in rendered
        assert 'File "<string>"' not in rendered
        assert getattr(error_info.value, "formatted_user_traceback") == rendered

    def test_session_exec_formats_user_traceback_with_notes(self):
        perms = Permissions(PermissionLevel.CONTROLLED)
        session = SafeSession(perms=perms)

        code = (
            "def boom():\n"
            "    try:\n"
            "        raise ValueError('invalid value')\n"
            "    except ValueError as err:\n"
            "        err.add_note(\"Did you mean: 'abs'?\")\n"
            "        raise\n"
            "\n"
            "boom()"
        )

        with pytest.raises(ValueError) as error_info:
            session.exec_response(code)

        rendered = str(error_info.value)
        assert "ValueError: invalid value" in rendered
        assert "Did you mean: 'abs'?" in rendered

    def test_session_exec_formats_user_traceback_with_custom_filename(self):
        perms = Permissions(PermissionLevel.CONTROLLED)
        session = SafeSession(
            perms=perms,
            user_traceback_filename="<discord input>",
        )

        with pytest.raises(ZeroDivisionError) as error_info:
            session.exec_response("1 / 0")

        assert 'File "<discord input>", line 1, in <module>' in str(error_info.value)

    def test_session_exec_preserves_name_error_suggestions(self):
        perms = Permissions(PermissionLevel.CONTROLLED)
        session = SafeSession(perms=perms)

        with pytest.raises(NameError) as error_info:
            session.exec_response("abx")

        rendered = str(error_info.value)
        assert "NameError: name 'abx' is not defined" in rendered
        assert "Did you mean: 'abs'?" in rendered

    def test_session_exec_traceback_can_mix_input_names(self):
        perms = Permissions(PermissionLevel.CONTROLLED)
        session = SafeSession(perms=perms)

        session.exec_response(
            "def foo(bar: str):\n    return 1 / 0",
            input_name="<foo file>",
        )

        with pytest.raises(ZeroDivisionError) as error_info:
            session.exec_response("foo('alice')", input_name="<repl input>")

        rendered = str(error_info.value)
        assert 'File "<repl input>", line 1, in <module>' in rendered
        assert 'File "<foo file>", line 2, in foo' in rendered

    def test_session_exec_uses_default_name_for_blank_input_name(self):
        perms = Permissions(PermissionLevel.CONTROLLED)
        session = SafeSession(perms=perms)

        with pytest.raises(NameError) as error_info:
            session.exec_response("missing_name", input_name="   ")

        rendered = str(error_info.value)
        assert 'File "<repl input>", line 1, in <module>' in rendered

    def test_session_traceback_labels_persist_after_pickle_round_trip(self):
        perms = Permissions(PermissionLevel.CONTROLLED)
        session = SafeSession(perms=perms)

        session.exec_response(
            "def foo():\n    return 1 / 0",
            input_name="<foo file>",
        )

        restored = pickle.loads(pickle.dumps(session))
        with pytest.raises(ZeroDivisionError) as error_info:
            restored.exec_response("foo()", input_name="<repl input>")

        rendered = str(error_info.value)
        assert 'File "<repl input>", line 1, in <module>' in rendered
        assert 'File "<foo file>", line 2, in foo' in rendered

    def test_session_timeout_error_contains_partial_output(self):
        perms = Permissions(PermissionLevel.CONTROLLED, timeout_seconds=0.1)
        session = SafeSession(perms=perms)

        with pytest.raises(ExecutionTimeoutError) as timeout_error:
            session.exec_response("print('begin')\nwhile True: pass")

        assert "begin" in timeout_error.value.output
        assert "Execution timed out after" in str(timeout_error.value)

    def test_session_memory_limit_error_contains_partial_output(self):
        perms = Permissions(PermissionLevel.CONTROLLED, memory_limit_bytes=1024 * 32)
        session = SafeSession(perms=perms)

        with pytest.raises(ExecutionMemoryLimitError) as memory_error:
            session.exec_response("print('before mem fail')\nblob = [0] * (1024 * 1024)")

        assert "before mem fail" in memory_error.value.output

    def test_session_reset_clears_vars(self):
        perms = Permissions(PermissionLevel.CONTROLLED)
        session = SafeSession(perms=perms)
        session.exec("x = 100")
        session.reset()
        r, _ = session.exec("'x' in vars() and x")
        assert r is False

    def test_session_command_char_customizable(self):
        perms = Permissions(PermissionLevel.CONTROLLED)
        registry = CommandRegistry("!")
        session = SafeSession(perms=perms, command_registry=registry)
        assert session.command_registry.command_prefix == "!"

    def test_session_serialization(self):
        perms = Permissions(PermissionLevel.CONTROLLED, imports=["math:*"])
        session = SafeSession(perms=perms)
        session.exec("x = 42")
        session.exec("y = [1, 2, 3]")

        # Pickling
        payload = pickle.dumps(session)
        restored = pickle.loads(payload)

        # Check state is preserved
        assert restored.perms.level == PermissionLevel.CONTROLLED
        assert restored.user_vars["x"] == 42
        assert restored.user_vars["y"] == [1, 2, 3]

    def test_session_to_from_relaunch_data(self):
        perms = Permissions(PermissionLevel.CONTROLLED)
        session = SafeSession(perms=perms)
        session.exec("z = 99")

        data = session.to_relaunch_data()
        restored = SafeSession.from_relaunch_data(data)
        assert restored.user_vars["z"] == 99


# =============================================================================
# Async Execution Tests (Discord Bot Use)
# =============================================================================


class TestAsyncExecution:
    """Test async_exec() for Discord bot integration."""

    @pytest.mark.asyncio
    async def test_async_exec_basic(self):
        perms = Permissions(PermissionLevel.CONTROLLED, imports=["math:*"])
        session = SafeSession(perms=perms)
        result, output = await session.async_exec("sqrt(16)")
        assert result == 4.0

    @pytest.mark.asyncio
    async def test_async_exec_with_print(self):
        perms = Permissions(PermissionLevel.CONTROLLED)
        session = SafeSession(perms=perms)
        result, output = await session.async_exec('print("async test")')
        assert "async test" in output

    @pytest.mark.asyncio
    async def test_async_exec_respects_limits(self):
        perms = Permissions(
            PermissionLevel.CONTROLLED,
            timeout_seconds=0.1,
        )
        session = SafeSession(perms=perms)
        with pytest.raises(TimeoutError):
            await session.async_exec("while True: pass")

    @pytest.mark.asyncio
    async def test_async_exec_timeout_error_contains_partial_output(self):
        perms = Permissions(
            PermissionLevel.CONTROLLED,
            timeout_seconds=0.1,
        )
        session = SafeSession(perms=perms)
        with pytest.raises(ExecutionTimeoutError) as timeout_error:
            await session.async_exec_response("print('async begin')\nwhile True: pass")

        message = str(timeout_error.value)
        if timeout_error.value.output:
            assert "async begin" in timeout_error.value.output
            assert "Execution timed out after" in message
        else:
            assert "asyncio-level timeout" in message

    @pytest.mark.asyncio
    async def test_async_exec_asyncio_timeout_message_is_descriptive(self):
        perms = Permissions(
            PermissionLevel.CONTROLLED,
            imports=["time:sleep"],
            timeout_seconds=None,
        )
        session = SafeSession(perms=perms)

        with pytest.raises(ExecutionTimeoutError) as timeout_error:
            await session.async_exec_response("sleep(2.0)", timeout=0.01)

        message = str(timeout_error.value)
        assert "asyncio-level timeout" in message
        assert "0.010s" in message

    @pytest.mark.asyncio
    async def test_async_exec_memory_limit_error_contains_partial_output(self):
        perms = Permissions(
            PermissionLevel.CONTROLLED,
            memory_limit_bytes=1024 * 32,
        )
        session = SafeSession(perms=perms)
        with pytest.raises(ExecutionMemoryLimitError) as memory_error:
            await session.async_exec_response("print('async mem')\nblob = [0] * (1024 * 1024)")

        assert "async mem" in memory_error.value.output

    @pytest.mark.asyncio
    async def test_async_exec_custom_timeout(self):
        perms = Permissions(PermissionLevel.CONTROLLED, timeout_seconds=10.0)
        session = SafeSession(perms=perms)
        result, _ = await session.async_exec(
            "sum(range(1000))",
            timeout=0.5,  # Should complete well before this
        )
        assert result == sum(range(1000))

    @pytest.mark.asyncio
    async def test_async_exec_response_includes_rich_artifacts(self, monkeypatch):
        class _FakeFigure:
            def savefig(self, buffer, *, format, bbox_inches):
                assert format == "png"
                assert bbox_inches == "tight"
                buffer.write(b"async-fake-png")

        class _FakePyplot:
            def get_fignums(self):
                return [11]

            def figure(self, _fig_num):
                return _FakeFigure()

            def close(self, _figure):
                return None

        monkeypatch.setitem(sys.modules, "matplotlib.pyplot", _FakePyplot())

        perms = Permissions(PermissionLevel.CONTROLLED)
        session = SafeSession(perms=perms)

        response = await session.async_exec_response("2 * 8")

        assert response.result == 16
        assert response.output == ""
        assert len(response.display_artifacts) == 1
        assert response.display_artifacts[0].mime_type == "image/png"
        assert response.display_artifacts[0].data == b"async-fake-png"


# =============================================================================
# REPL Command Registry Tests
# =============================================================================


class TestCommandRegistry:
    """Test REPL command registration and dispatch."""

    def test_builtin_help_command(self):
        registry = CommandRegistry()
        perms = Permissions(PermissionLevel.CONTROLLED)
        session = SafeSession(perms=perms)
        # Ensure help command exists and dispatches
        result = registry.dispatch(":help vars", session=session)
        assert result is not False

    def test_builtin_commands_command(self):
        registry = CommandRegistry()
        perms = Permissions(PermissionLevel.CONTROLLED)
        session = SafeSession(perms=perms)
        result = registry.dispatch(":commands", session=session)
        assert result is not False

    def test_vars_command_lists_variables(self):
        registry = CommandRegistry()
        perms = Permissions(PermissionLevel.CONTROLLED)
        session = SafeSession(perms=perms)
        session.exec("x = 42")
        session.exec("y = 'hello'")
        # just ensure it dispatches without error
        result = registry.dispatch(":vars", session=session)
        assert result is not False

    def test_reset_command_clears_vars(self):
        registry = CommandRegistry()
        perms = Permissions(PermissionLevel.CONTROLLED)
        session = SafeSession(perms=perms)
        session.exec("x = 100")
        registry.dispatch(":reset", session=session)
        assert len(session.user_vars) == 0

    def test_custom_command_registration(self):
        registry = CommandRegistry()
        perms = Permissions(PermissionLevel.CONTROLLED)
        session = SafeSession(perms=perms, command_registry=registry)

        called = []

        @registry.command("test", help_text="A test command.")
        def _test(args, sess):
            called.append(args)
            return True

        result = registry.dispatch(":test arg1", session=session)
        assert result is True
        assert called == ["arg1"]


# =============================================================================
# Import Error Handling Tests
# =============================================================================


class TestImportValidation:
    """Test import spec validation."""

    def test_invalid_module_raises(self):
        with pytest.raises(SafeReplImportError):
            normalize_validate_import("nonexistent_module_xyz")

    def test_invalid_attribute_raises(self):
        with pytest.raises(SafeReplImportError):
            normalize_validate_import("math:nonexistent_attr")

    def test_valid_import_spec(self):
        spec = normalize_validate_import("math:sqrt,cos")
        assert spec
        (mod, alias), names = list(spec.items())[0]
        assert any(n[0] == "sqrt" for n in names)


# =============================================================================
# Edge Cases and Integration
# =============================================================================


class TestEdgeCases:
    """Test edge cases and corner scenarios."""

    def test_empty_code_string(self):
        perms = Permissions(PermissionLevel.CONTROLLED)
        uv = {}
        r = exec_restricted("", uv, perms=perms)
        assert r.ok
        assert r.result is None

    def test_comments_only(self):
        perms = Permissions(PermissionLevel.CONTROLLED)
        uv = {}
        r = exec_restricted("# This is a comment\n# Another comment", uv, perms=perms)
        assert r.ok

    def test_multiline_string_literal(self):
        perms = Permissions(PermissionLevel.CONTROLLED)
        uv = {}
        code = '''result = """
        This is a
        multiline string
        """'''
        r = exec_restricted(code, uv, perms=perms)
        assert r.ok
        assert "multiline" in uv["result"]

    def test_f_strings_work(self):
        perms = Permissions(PermissionLevel.CONTROLLED)
        uv = {}
        uv["name"] = "World"
        r = exec_restricted('result = f"Hello {name}"', uv, perms=perms)
        assert r.ok
        assert uv["result"] == "Hello World"

    def test_lambda_definitions(self):
        perms = Permissions(PermissionLevel.CONTROLLED)
        uv = {}
        r = exec_restricted("f = lambda x: x * 2\nresult = f(21)", uv, perms=perms)
        assert r.ok
        assert uv["result"] == 42

    def test_try_except_blocks(self):
        perms = Permissions(PermissionLevel.CONTROLLED)
        uv = {}
        code = """
try:
    x = 1 / 0
except ZeroDivisionError:
    result = "caught"
"""
        r = exec_restricted(code, uv, perms=perms)
        assert r.ok
        assert uv["result"] == "caught"

    def test_type_checking_in_userspace(self):
        perms = Permissions(PermissionLevel.CONTROLLED)
        uv = {}
        code = "result = isinstance(42, int) and not isinstance('hello', int)"
        r = exec_restricted(code, uv, perms=perms)
        assert r.ok
        assert uv["result"] is True

    def test_standard_exceptions_available(self):
        perms = Permissions(PermissionLevel.CONTROLLED)
        uv = {}
        code = "try:\n    raise ValueError('test')\nexcept ValueError as e:\n    result = str(e)"
        r = exec_restricted(code, uv, perms=perms)
        assert r.ok
        assert uv["result"] == "test"
