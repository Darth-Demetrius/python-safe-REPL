# safe-repl

Safe Python REPL with tiered permission levels for restricted code execution.

## Public API stability

The package-level imports from `safe_repl` are the supported public API surface:

- `PermissionLevel`, `Permissions`, `SafeSession`
- `safe_exec`, `validate_ast`, `repl`, `main`
- `SafeReplImportError`, `SafeReplCliArgError`

Submodules (`safe_repl.policy`, `safe_repl.engine`, `safe_repl.validator`, `safe_repl.process_isolation`, etc.) are implementation details and may change more frequently.

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
- `Permissions`: resolved policy object used by execution and REPL
  - Constructor defaults to `base_perms=PermissionLevel.LIMITED`.
  - `allow_symbols`, `block_symbols`, `allow_nodes`, `block_nodes`, and `imports` are optional (`None` defaults to empty values).
  - Supports optional per-instance overrides:
      `timeout_seconds: float | None = None`, `memory_limit_bytes: int | None = None`.
- `SafeSession`: stateful executor that keeps `user_vars` across calls

### Permission-level attribute access

- `MINIMUM`: attribute access is blocked.
- `LIMITED`: attribute access is allowed on literals and imported symbols
    (for example `'Hello, World!'.split()` or `root(9)` after `math:sqrt as root`).
- `PERMISSIVE`: same as `LIMITED`, plus attributes on in-scope local/user names.
- `UNSUPERVISED`: broad attribute access is allowed, except private/dunder attributes
    are still blocked by validator rules.

### Functions

- `safe_exec(code: str, user_vars: dict[str, object], *, perms: Permissions) -> object | None`
  - Low-level stateless execution function.
  - Parses, validates, and executes one snippet under explicit permissions.
- `validate_ast(tree: ast.AST, user_vars: dict[str, object], allowed_names: set[str], perms: Permissions) -> None`
  - Validates one parsed AST against active security rules.
- `Permissions.set_limits(timeout_seconds: float | None = None, memory_limit_bytes: int | None = None) -> None`
  - Instance method that overrides timeout and/or memory limit for this `Permissions` object.
  - Values are clamped to safe minimums (`timeout_seconds >= 1`, `memory_limit_bytes >= 1024`).
- `repl(*, perms: Permissions) -> None`
  - Starts the interactive REPL loop (internally uses `SafeSession`).
- `main() -> None`
  - CLI entrypoint used by `safe-repl` and `python -m safe_repl`.

### SafeSession methods

- `SafeSession(perms: Permissions, user_vars: dict[str, object] | None = None)`
- `SafeSession.from_cli_args(args: argparse.Namespace, ..., user_vars: dict[str, object] | None = None) -> SafeSession`
  - Builds a session from parsed CLI args (same logic used by `main()`).
- `exec(code: str) -> object | None`
  - Executes code using session permissions and persistent variables.
  - Opens a worker session on first use and reuses it for subsequent `exec(...)` calls.
- `reset() -> None`
  - Clears session `user_vars`.
- `open_worker_session() -> None`
  - Starts the session worker if it is not already running.
- `close_worker_session() -> None`
  - Stops the session worker if active.
- `repl(*, command_char: str | None = None) -> None`
  - Runs interactive REPL bound to this session.
  - Prints a short startup hint for exiting and discovering commands.
  - Use REPL commands to inspect available functions, nodes, imports, level, and user vars.
  - `command_char` sets the REPL command prefix (for example `:` or `!`) and persists on the session.
  - Opens one worker session per REPL run and reuses it for every entered command.

### Internal module split (implementation detail)

- `safe_repl.process_isolation`
  - Worker runtime APIs and process isolation orchestration.
- `safe_repl.process_control`
  - Process lifecycle, context-process construction checks, timeout enforcement, and worker finalization helpers.
- `safe_repl.process_worker`
  - Worker-side execution, command handling, and response normalization.
- `safe_repl.process_protocol`
  - Shared IPC protocol constants and typed worker payload schemas.
  - Worker command parsing constrains `op` to `exec|reset|close` and returns normalized command payloads with required keys.
- `safe_repl.sandbox`
  - Linux-focused resource limit helpers for process isolation (`with_limits`, cgroup attach helpers).

## Security benchmarking

- `tools/bench_validator.py`
  - Micro-benchmarks for validator-only `validate_ast(...)` hot paths.
- `tools/bench_security.py`
  - Benchmarks import-time and runtime costs across `policy` and `validator` surfaces.

Example:

```python
from safe_repl import PermissionLevel, Permissions, SafeSession

# "math:*" expands all public math names for direct access only:
# sqrt(16) works; math.sqrt(16) does NOT (module not put in scope)
session = SafeSession(Permissions(base_perms=PermissionLevel.LIMITED, imports=["math:*"]))
print(session.exec("sqrt(16)"))    # 4.0
print(session.exec("floor(3.7)"))  # 3

# Import specific names with optional alias:
session2 = SafeSession(Permissions(base_perms=PermissionLevel.LIMITED, imports=["math:sqrt as root"]))
print(session2.exec("root(9)"))  # 3.0
```

### Manual worker session lifecycle

```python
from safe_repl import PermissionLevel, Permissions, SafeSession

session = SafeSession(Permissions(base_perms=PermissionLevel.LIMITED))

session.open_worker_session()
try:
    session.exec("x = 10")
    print(session.exec("x + 5"))  # 15
finally:
  session.close_worker_session()
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
safe-repl --import "json"
```

### REPL commands

- `:commands`
  - Prints all non-hidden command help lines.
- `:help <command>`
  - Prints help for a single command.
- `:level`
  - Prints the current permission level.
- `:functions`
  - Prints available functions for the current session.
- `:nodes`
  - Prints allowed AST nodes for the current session.
- `:imports`
  - Prints imported symbols for the current session.
- `:vars`
  - Prints only user variable names.
- `:vars values`
  - Prints user variables with their values.

Command lookup is case-sensitive first, then falls back to lowercase for `help` and `dispatch` lookups.

### Custom REPL commands

You can provide a custom command registry when constructing a session.

```python
from safe_repl import PermissionLevel, Permissions, SafeSession
from safe_repl.repl_command_registry import CommandRegistry


registry = CommandRegistry()

@registry.command("ping", help_text="Use '{0}ping' to print pong.")
def ping_command(_args: str, _session: SafeSession) -> None:
    print("pong")


perms = Permissions(base_perms=PermissionLevel.LIMITED)
session = SafeSession(
    perms,
    repl_commands=registry,
)
session.repl()
```

Notes:

- Handlers are looked up by command token (case-sensitive first, then lowercase fallback).
- Handlers receive command args and session as `(args: str, session: SafeSession)`.
- REPL dispatch receives prefix-stripped command input (`:ping` becomes `ping`).
- To add commands without replacing defaults, create your own registry and register handlers with `@registry.command(...)`.

### Process-only execution note

- REPL/session execution is process-isolated by default and currently has no mode-selection flag.
- Timeouts use `Permissions.timeout_seconds` directly for worker response polling and terminate the worker on timeout.
- Update path: alternate execution strategies may be added later behind explicit opt-in API/CLI flags.

### CLI import flag behavior

- `--import SPEC`
  - Supports `module`, `module as alias`, `module:name`, `module:name as alias`, and `module:*`.
  - If `--import` is not used, CLI defaults to importing `math:*`.
  - Any use of `--import` disables default `math:*` auto-import.
  - `--import ""` disables auto-import without adding any imports.
  - `module:*` expands all public names at startup — each name is accessible directly (for example `sqrt(16)`). The module object itself is **not** put in scope, so `math.sqrt(16)` does not work with `math:*`; use `math:sqrt` for that.
  - Import specs are validated at policy construction time; the worker resolves them locally at launch.
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
    - REPL invocation and list-output modes
- `tests/test_cli_integration.py`
  - End-to-end `python -m safe_repl` subprocess behavior
  - CLI success paths and non-zero exit error paths
- `tests/test_process_control.py`
  - Process lifecycle, context-process guardrails, and timeout/finalization behavior
- `tests/test_process_protocol.py`
  - Worker command payload coercion and normalization rules
- `tests/test_security_api.py`
  - Package-level and policy-level AST validation API behavior

## TODO

- Manually review code.
  - [ ] `session.py`
- Add ability to create custom REPL commands during runtime via session API.
- Use `colorama` or similar for colored CLI output.
- Graceful handling of lumped I/O à la discord messaging. (don't send a bajillion individual messages in response to a single message)
- Graceful shutdown handling for subprocess workers (for example on `KeyboardInterrupt`).
- Replace denylist-heavy `UNSUPERVISED` policy behavior with a capability/profile-based model.

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
