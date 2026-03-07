# safe-repl

Safe Python REPL with tiered permission levels for restricted code execution.

## Public API stability

The package-level imports from `safe_repl` are the supported public API surface:

- `PermissionLevel`, `Permissions`, `ExecutionMode`, `SafeSession`
- `safe_exec`, `repl`, `main`
- `SafeReplImportError`, `SafeReplCliArgError`

Submodules (`safe_repl.policy`, `safe_repl.engine`, `safe_repl.validator`, `safe_repl.execution`, `safe_repl.process_isolation`, etc.) are implementation details and may change more frequently.

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
from safe_repl import PermissionLevel, Permissions, SafeSession

perms = Permissions(
    # base_perms defaults to LIMITED when omitted
    base_perms=PermissionLevel.LIMITED,
    allow_symbols=None,
    block_symbols=None,
    allow_nodes=None,
    block_nodes=None,
    imports=None,
    timeout_seconds=None,      # Optional override for this instance
    memory_limit_bytes=None,   # Optional override for this instance
)

session = SafeSession(perms)
result = session.exec("2 + 3 * 4")
print(result)  # 14
```

## API reference

### Types

- `PermissionLevel`: `MINIMUM`, `LIMITED`, `PERMISSIVE`, `UNSUPERVISED`
    - Invalid values warn and default to level `0` (`MINIMUM`).
- `ExecutionMode`: `IN_PROCESS` (`"in-process"`), `PROCESS` (`"process"`)
    - Used by `SafeSession`/`repl` to select in-process vs subprocess execution.
    - String inputs are accepted for convenience and normalized to enum values.
    - Default mode is `PROCESS`.
- `Permissions`: resolved policy object used by execution and REPL
    - Constructor defaults to `base_perms=PermissionLevel.LIMITED`.
    - `allow_symbols`, `block_symbols`, `allow_nodes`, `block_nodes`, and `imports` are optional (`None` defaults to empty values).
    - Supports optional per-instance overrides:
        `timeout_seconds: float | None = None`, `memory_limit_bytes: int | None = None`.
- `SafeSession`: stateful executor that keeps `user_vars` across calls

### Permission-level attribute access

- `MINIMUM`: attribute access is blocked.
- `LIMITED`: attribute access is allowed on literals and imported symbols
    (for example `'Hello, World!'.split()` or `math.sqrt(9)`).
- `PERMISSIVE`: same as `LIMITED`, plus attributes on in-scope local/user names.
- `UNSUPERVISED`: broad attribute access is allowed, except private/dunder attributes
    are still blocked by validator rules.

### Functions

- `safe_exec(code: str, user_vars: dict[str, object], *, perms: Permissions) -> object | None`
    - Low-level stateless execution function.
    - Parses, validates, and executes one snippet under explicit permissions.
- `Permissions.set_timeout_seconds(seconds: float) -> None`
    - Instance method that overrides timeout for this `Permissions` object.
- `Permissions.set_memory_limit_bytes(bytes_limit: int) -> None`
    - Instance method that overrides memory limit for this `Permissions` object.
- `repl(*, perms: Permissions, execution_mode: ExecutionMode | str | None = None) -> None`
    - Starts the interactive REPL loop (internally uses `SafeSession`).
- `main() -> None`
    - CLI entrypoint used by `safe-repl` and `python -m safe_repl`.

### SafeSession methods

- `SafeSession(perms: Permissions, user_vars: dict[str, object] | None = None, execution_mode: ExecutionMode | str = ExecutionMode.PROCESS)`
- `SafeSession.from_cli_args(args: argparse.Namespace, ..., user_vars: dict[str, object] | None = None) -> SafeSession`
    - Builds a session from parsed CLI args (same logic used by `main()`).
- `exec(code: str, *, execution_mode: ExecutionMode | str | None = None) -> object | None`
    - Executes code using the session's permissions and persistent variables.
    - Uses the session's saved mode unless an explicit override is passed.
- `reset() -> None`
    - Clears session `user_vars`.
- `open_subprocess_session() -> None`
    - Starts a long-lived subprocess worker for process-mode execution.
- `close_subprocess_session() -> None`
    - Stops the long-lived subprocess worker if active.
- `reopen_subprocess_session() -> None`
    - Restarts the long-lived subprocess worker using current local state.
- `repl(*, execution_mode: ExecutionMode | str | None = None) -> None`
    - Runs interactive REPL bound to this session.
    - `show_details_once` defaults are level-aware: `False` for `MINIMUM`/`LIMITED`, `True` for `PERMISSIVE`/`UNSUPERVISED`.
    - Uses the session's saved mode unless an explicit override is passed.
    - In `process` mode, opens a persistent subprocess worker for the REPL run.

### Internal module split (implementation detail)

- `safe_repl.execution`
    - Execution-mode parsing and high-level dispatch helpers.
- `safe_repl.process_isolation`
    - Public process-isolated execution APIs and persistent session orchestration.
- `safe_repl.process_control`
    - Process lifecycle, start-method validation, and timeout coordination helpers.
- `safe_repl.process_worker`
    - Worker-side execution, command handling, and response normalization.
- `safe_repl.process_protocol`
    - Shared IPC protocol constants and typed worker payload schemas.

Example:

```python
import math

from safe_repl import PermissionLevel, Permissions, SafeSession

session = SafeSession(Permissions(base_perms=PermissionLevel.LIMITED, imports={"math": math}))
print(session.exec("math.sqrt(16)"))  # 4.0

# Process-isolated mode
session = SafeSession(
    Permissions(base_perms=PermissionLevel.LIMITED, imports={"math": math}),
    execution_mode="process",
)
print(session.exec("math.sqrt(25)"))  # 5.0
```

### Manual persistent subprocess lifecycle

```python
from safe_repl import ExecutionMode, PermissionLevel, Permissions, SafeSession

session = SafeSession(
    Permissions(base_perms=PermissionLevel.LIMITED),
    execution_mode=ExecutionMode.PROCESS,
)

session.open_subprocess_session()
try:
    session.exec("x = 10")
    print(session.exec("x + 5"))  # 15
finally:
    session.close_subprocess_session()
```

### Minimal embedding pattern

```python
from safe_repl import PermissionLevel, Permissions, SafeSession

perms = Permissions(
    base_perms=PermissionLevel.LIMITED,
    allow_symbols=None,
    block_symbols=None,
    allow_nodes=None,
    block_nodes=None,
    imports=None,
    timeout_seconds=0.5,
    memory_limit_bytes=256 * 1024 * 1024,
)

session = SafeSession(perms)
session.exec("x = 2")
print(session.exec("x * 10"))  # 20
```

### Error model

Use this shared taxonomy for API responses/logging:

| error_type | Source exception | Meaning |
| --- | --- | --- |
| `validation` | `ValueError` | Input rejected by AST/safety validation. |
| `timeout` | `TimeoutError` | Execution exceeded configured per-level timeout. |
| `runtime` | `RuntimeError` | Policy/runtime failure (for example unset permissions or memory limit exceeded). |
| `user_code` | any other exception | Exception raised by executed user code. |

CLI note: invalid AST node names or failed import specs print an error and exit with status `1`.

Library note: low-level import/CLI parsing helpers raise exceptions (`SafeReplImportError`,
`SafeReplCliArgError`) so embedding code can handle failures without process exit.

These exceptions are also re-exported from `safe_repl`:

```python
from safe_repl import SafeReplCliArgError, SafeReplImportError
```

### Handling errors

```python
from safe_repl import SafeSession

session = SafeSession(perms)

try:
    result = session.exec(user_code)
except ValueError as err:
    print(f"[validation] {err}")
except TimeoutError:
    print("[timeout] Execution timed out")
except RuntimeError as err:
    print(f"[runtime] {err}")
except Exception as err:
    print(f"[user_code] {type(err).__name__}: {err}")
else:
    if result is not None:
        print(result)
```

### Handling errors (structured result)

```python
from typing import Any

from safe_repl import SafeSession

session = SafeSession(perms)


def run_user_code(user_code: str) -> dict[str, Any]:
    try:
        value = session.exec(user_code)
    except ValueError as err:
        return {"ok": False, "error_type": "validation", "message": str(err)}
    except TimeoutError:
        return {"ok": False, "error_type": "timeout", "message": "Execution timed out"}
    except RuntimeError as err:
        return {"ok": False, "error_type": "runtime", "message": str(err)}
    except Exception as err:
        return {
            "ok": False,
            "error_type": "user_code",
            "message": str(err),
            "exception": type(err).__name__,
        }

    return {"ok": True, "result": value}
```

## CLI usage

After install, run either of these:

```bash
safe-repl
python -m safe_repl
```

Examples:

```bash
safe-repl --level MINIMUM
safe-repl --level PERMISSIVE
safe-repl --execution-mode process
safe-repl --import "json"
safe-repl --show-repl-details
safe-repl --show-repl-details --no-show-repl-details-once
```

### CLI detail flags

- `--show-repl-details`
  - Prints startup summaries (builtins, AST nodes, imports).
- `--show-repl-details-once` / `--no-show-repl-details-once`
  - Overrides whether startup details print only once per session.
  - If omitted, defaults are level-aware:
    - `False` for `MINIMUM` / `LIMITED`
    - `True` for `PERMISSIVE` / `UNSUPERVISED`

### CLI execution mode flag

- `--execution-mode {in-process,process}`
    - `process` (default): executes snippets in isolated subprocesses (stronger containment).
    - `in-process`: executes snippets in the current interpreter process.

### CLI import flag behavior

- `--import SPEC`
    - Supports `module`, `module as alias`, `module:name`, and `module:*`.
    - If `--import` is not used, CLI defaults to importing `math:*`.
    - Any use of `--import` disables default `math:*` auto-import.
    - `--import ""` disables auto-import without adding any imports.

## Testing matrix

Current automated test coverage includes:

- `tests/test_safe_repl.py`
  - Permission-level policy behavior
  - AST validation constraints
  - Runtime timeout/memory behavior
  - Session behavior and state persistence
  - Exception and fallback behavior for enum/import helpers
- `tests/test_cli.py`
  - CLI argument handling via unit-level monkeypatched invocations
  - CLI error/exit handling for invalid node/import args
  - REPL detail flag forwarding and list-output modes
- `tests/test_cli_integration.py`
  - End-to-end `python -m safe_repl` subprocess behavior
  - CLI success paths and non-zero exit error paths

## TODO (deferred improvements)

- Replace denylist-heavy `UNSUPERVISED` policy behavior with a capability/profile-based model.
- Improve timeout portability across environments (keep current behavior but add non-`SIGALRM` fallback strategy).

## Sandbox upgrade paths

Current process isolation improves containment, but stronger boundaries can be added in layers.
The most promising near-term options are Linux namespaces and microVM execution.

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
- Python import name: `safe_repl`
- See `CHANGELOG.md` for recent API and behavior changes.
