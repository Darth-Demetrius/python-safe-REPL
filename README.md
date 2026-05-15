# safe-repl

Safe Python REPL with tiered permission levels for restricted code execution.

## Overview

As of `0.8.1`, the project ships the `respy_repl` backend only.
Legacy `safe_repl` process-isolated modules were removed.

For `respy_repl`, `SafeSession.exec(...)` and `SafeSession.async_exec(...)` return `(result, output)`, where `output` contains captured `print(...)` text from the executed snippet.
When you need rich outputs (for example matplotlib figures), use `SafeSession.exec_response(...)` or `SafeSession.async_exec_response(...)` and read `response.display_artifacts`.
When user code raises, `respy_repl.SafeSession` raises typed exceptions from `respy_repl.exceptions` instead of mutating built-in exceptions in place.
Non-timeout/non-memory failures are raised as `UserCodeExecutionError` with a user-formatted traceback (only user-code frames), plus exception notes (`__notes__`) such as Python hints.
Syntax errors use the same internal filename configured for that execution input (for example `<discord input>`).
You can customize the displayed filename via `SafeSession(..., user_traceback_filename="<your label>")`.
For per-snippet labels, pass `input_name` to `exec(...)` / `exec_response(...)` (and async variants). Empty or whitespace-only `input_name` values fall back to `<repl input>`. This allows mixed-frame tracebacks when one snippet calls a function defined in another snippet.
Traceback frame filtering is based on traceback structure: user frames start immediately after the engine execution shim frame (`respy_repl/engine.py` in `_run`). No extra filename-mapping state is tracked for formatting.
Function traceback labels are stable across session pickle/relaunch because the filename metadata is attached to compiled function code objects.
When a `respy_repl` execution times out, `SafeSession.exec_response(...)` and `SafeSession.async_exec_response(...)` raise `ExecutionTimeoutError`, which includes partial `output` and `display_artifacts` generated before timeout.
Timeout exception messages include the effective timeout duration and a short code preview to make timeout failures easier to diagnose.
If an asyncio-level timeout fires before the in-thread timeout path completes, partial output may be unavailable.
When a `respy_repl` execution exceeds `memory_limit_bytes`, these response-oriented APIs raise `ExecutionMemoryLimitError`, which also includes partial `output` and `display_artifacts` generated before the memory-limit failure.
All execution exceptions share a common base class: `ExecutionError`.
For wrapped user-code failures, inspect `source_exception_type` to identify the original exception class name.

Example:

```python
from respy_repl import PermissionLevel, Permissions, SafeSession

session = SafeSession(Permissions(PermissionLevel.CONTROLLED, imports=["matplotlib.pyplot:*", "math:*"]))
response = session.exec_response(
  """
import matplotlib.pyplot as plt
plt.plot([1, 2, 3], [1, 4, 9])
plt.title('Demo Plot')
"""
)

for artifact in response.display_artifacts:
  if artifact.mime_type == "image/png":
    # send artifact.data to your client (Discord attachment, HTTP response, etc.)
    print(f"Captured PNG bytes: {len(artifact.data)}")

session.exec_response("def foo():\n    return 1 / 0", input_name="<foo file>")
try:
    session.exec_response("foo()", input_name="<repl input>")
except Exception as exc:
    print(str(exc))
    # Traceback (most recent call last):
    #   File "<repl input>", line 1, in <module>
    #   File "<foo file>", line 2, in foo
```

## Public API

- `PermissionLevel`, `Permissions`, `SafeSession`, `CommandRegistry`
- `ExecutionError`, `UserCodeExecutionError`, `ExecutionTimeoutError`, `ExecutionMemoryLimitError`
- `exec_restricted`, `ExecResult`, `DisplayArtifact`, `main`
- `SafeReplError`, `SafeReplImportError`, `SafeReplCliArgError`

Submodules are implementation details and may change.

## Install

From PyPI (when published):

```bash
pip install safe-repl
```

From source (local development):

```bash
pip install -e .
```

## Import in another project

```python
from respy_repl import PermissionLevel, Permissions, SafeSession
import io
import contextlib

perms = Permissions(
  PermissionLevel.CONTROLLED,
    imports=["numpy:sum", "math:sqrt as root"],
)

buf = io.StringIO()
session = SafeSession(perms)
with contextlib.redirect_stdout(buf):
    session.exec("x = sum(range(9))")
    session.exec("print(root(x))")
captured = buf.getvalue()

print(captured)  # '6.0'
```

## API Reference

- `PermissionLevel`: Enum of permission levels: `NONE`, `RESTRICTED`, `CONTROLLED`, `TRUSTED`. Invalid values warn and default to `NONE`.
- `Permissions`: Policy object for execution and REPL. Supports per-instance overrides for `timeout_seconds` and `memory_limit_bytes` via `set_limits()`.
- `SafeSession`: Stateful executor that keeps `user_vars` across calls.
- `CommandRegistry`: Decorator-based registry for custom REPL commands.
- `exec_restricted`: Low-level stateless execution function.
- `main`: CLI entrypoint.
- `SafeReplError`, `SafeReplImportError`, `SafeReplCliArgError`: User-facing input/CLI exception hierarchy.
- `ExecutionError` family: Execution exceptions with partial output and source exception metadata.

### Permission-level attribute access

- `RESTRICTED`: Attribute access is blocked.
- `CONTROLLED`: Attribute access is allowed on literals and imported symbols (e.g. `'abc'.split()`, or `np.sqrt(9)` after `numpy as np`).
- `TRUSTED`: Also allows attributes on in-scope user names. Private and dunder attributes are still blocked.

### Pickle round-trip and relaunch

```python
import pickle

from respy_repl import PermissionLevel, Permissions, SafeSession

session = SafeSession(
  Permissions(PermissionLevel.CONTROLLED, imports=["math:sqrt as root"]),
    user_vars={"x": 25},
)

# Direct session pickle round-trip.
restored = pickle.loads(pickle.dumps(session))
print(restored.exec("root(x)"))  # 5.0

# Explicit relaunch payload workflow.
payload = session.to_relaunch_data()
blob = pickle.dumps(payload)
restored2 = SafeSession.from_relaunch_data(pickle.loads(blob))
print(restored2.exec("x + 1"))  # 26
```

## Quickstart

Install:

```bash
pip install safe-repl
# or for development:
pip install -e .
```

Run REPL:

```bash
respy-repl
# or
python -m respy_repl
```

## Usage Example

```python
from respy_repl import PermissionLevel, Permissions, SafeSession
perms = Permissions(PermissionLevel.CONTROLLED, imports=["math:*"])
session = SafeSession(perms)
print(session.exec("2 + 3 * 4"))  # 14
```

## CLI Arguments

- `--level LEVEL` — Permission level: RESTRICTED/1, CONTROLLED/2 (default), TRUSTED/3
- `--import SPEC` — Import module/spec (e.g. `math:*`, disables default if used)
- `--allow-functions ...` / `--block-functions ...` — Add/remove builtins
- `--list-functions` — Show allowed functions and exit

## REPL Commands

- `:commands` — List commands
- `:help <command>` — Show help
- `:level` — Print permission level
- `:functions` — Print available functions
- `:imports` — Print imported symbols
- `:vars` — Print user variable names
- `:vars values` — Print user variables with values

## Embedding & Custom Commands

```python
from respy_repl import PermissionLevel, Permissions, SafeSession
from respy_repl.repl_command_registry import CommandRegistry
registry = CommandRegistry("!")
@registry.command("ping", help_text="Use '{0}ping' to print pong.")
def ping_command(_args, _session): print("pong")
session = SafeSession(Permissions(PermissionLevel.CONTROLLED), command_registry=registry)
session.repl()
```

## Error Handling

| error_type   | Exception type                  | Meaning                                        |
| ------------ | ------------------------------- | ---------------------------------------------- |
| validation   | `SafeReplInputError` subclasses | Input rejected by import/CLI validation        |
| timeout      | `ExecutionTimeoutError`         | Execution exceeded configured timeout          |
| memory       | `ExecutionMemoryLimitError`     | Execution exceeded configured memory limit     |
| user_code    | `UserCodeExecutionError`        | User exception with filtered traceback details |

## TODO

- Add ability to remove items from blocklists.
- Add ability to create custom REPL commands during runtime via session API.
- Use `colorama` or similar for colored CLI output.
- Graceful shutdown handling for subprocess workers (for example on `KeyboardInterrupt`).

## Sandbox upgrade paths

Current in-process RestrictedPython controls can be strengthened with additional isolation layers at the host level.
The most promising near-term options are Linux namespaces and microVM execution.

- Replace denylist-heavy `TRUSTED` policy behavior with a capability/profile-based model.
- Linux namespaces (recommended next step)
  - Run workers in isolated `user`, `pid`, `mount`, and `net` namespaces.
  - Combine with `no_new_privs`, read-only mounts, and restricted `/tmp`.
  - Pair with seccomp and cgroup limits for syscall and resource control.
- MicroVMs (strongest practical boundary)
  - Run each execution in a minimal VM (for example Firecracker-class isolation).
  - Provides stronger kernel boundary than process/container isolation.
  - Higher startup/runtime overhead, but best fit for multi-tenant untrusted code.
- Optional middle layer: rootless containers
  - Easier operationally than microVMs, stronger than plain processes.
  - Still shares host kernel, so boundary is weaker than microVM/VM isolation.

## Notes

- Distribution/package name: `safe-repl`
- Python import name: `respy_repl`
- See `CHANGELOG.md` for recent API and behavior changes.
