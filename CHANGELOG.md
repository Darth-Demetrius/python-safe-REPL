# Changelog

## [Unreleased]

## [0.5.0] - 2026-03-17

### Added

- Added `cloudpickle` as a runtime dependency for IPC fallback serialization.
- Added `PermissionLevel.NONE` as explicit level `0`, and extended default policy tables to include a `NONE` baseline.
- Added normalized import utilities (`imports_union`, `imports_intersection`, `collect_import_symbols`) and switched normalized import specs to a module/alias-keyed mapping format.
- Added `Permissions` ordering and merge helpers (`__int__`, `__eq__`, `__lt__`, `permissive_merge(...)`, `restrictive_merge(...)`).

### Changed

- Several small refactors.
- Changed default permission baseline to `PermissionLevel.NONE` when `perm_level` is omitted.
- Removed `SafeSession` constructor I/O callbacks and setter methods. Session and REPL I/O now use built-in `input()`/`print()` directly; embedding should use `contextlib.redirect_stdout(...)` and patch `builtins.input` for scripted input.
- Reworked import handling so `Permissions.build_globals()` resolves imports directly into execution globals through `importlib.import_module(...)`.
- Hardened worker IPC serialization for non-pickleable values by encoding response values with `cloudpickle`; response `result` falls back to safe placeholder text when serialization fails, while un-serializable `user_vars` entries are filtered out to keep transport stable.
- Updated `SafeSession` relaunch/pickle serialization and worker command transport to encode/decode `user_vars` through shared IPC codec helpers, enabling user-defined functions in pickled session variables.

### Fixed

- Fixed imported-symbol alias collection so explicit import specs like `math:sqrt as root` correctly populate allowed symbols.

## [0.4.3] - 2026-03-16

### Added

- Added relaunch serialization APIs for `Permissions` and `SafeSession` (`to_relaunch_data(...)` / `from_relaunch_data(...)`) and pickle round-trip hooks that persist only relaunch-safe session state.

### Changed

- Simplified worker IPC and session execution so all worker operations use one normalized response payload that always carries result, user-vars state, output text, and exception metadata.
- Simplified REPL embedding by replacing custom REPL I/O protocol classes with constructor-level `read(prompt)` and `write(text)` callbacks on `SafeSession`.

### Documentation

- Updated README module/layout notes and examples to reflect the current worker-session internals and callback-based REPL/session APIs.

## [0.4.2] - 2026-03-11

### Added

- Star imports (`module:*`) now expand all public module names so they are accessible directly (`sqrt(16)`). The module object itself is not put in scope, avoiding `name.name`-style conflicts for modules whose attribute name matches the module name.
- Added `tools/bench_security.py` to benchmark security-surface import-time and runtime paths (`Permissions` construction and `validate_ast`).

### Fixed

- `safe_exec` memory limit was always silently ignored when called directly (not via a worker): `tracemalloc` was never started, so `get_traced_memory()` always returned `(0, 0)`. `safe_exec` now starts and stops `tracemalloc` itself when `memory_limit_bytes` is active and tracing is not already running. The worker's `RLIMIT_AS` OS cap is unchanged and remains the hard limit in worker-backed sessions.

### Changed

- Optimized validation/runtime hot paths across security modules by removing duplicate attribute-handler work in AST validation and reducing repeated lookup overhead in validation and allowed-name collection.
- Added Linux-focused process memory limit enforcement in process isolation by applying child `RLIMIT_AS` via `with_limits(...)` and attempting best-effort cgroup v2 PID attachment through the new `safe_repl.sandbox` helpers.
- Updated process worker response helper naming for clearer semantics (`apply_worker_response_to_user_vars`).

### Tests

- Aligned process-control and session tests with current APIs: context-process validation checks, worker-safe import usage in process-backed sessions, and `Permissions.set_limits(...)` limit overrides.

### Documentation

- Updated README API reference and examples to use `Permissions.set_limits(...)`, clarified current `process_control` responsibilities, and documented process-serializable import requirements for worker-backed execution.

## [0.4.1] - 2026-03-09

### Changed

- Standardized execution on process isolation by removing mode-selection paths/flags and routing session execution through one persistent worker workflow.
- Simplified internal module boundaries and process lifecycle utilities, including consolidated process finalization and direct timeout polling based on session permissions.
- Tightened worker IPC command handling by normalizing command payloads, requiring explicit command shape, and constraining persistent operations to `exec|reset|close`.

### Tests

- Updated test coverage to match process-only execution behavior and current session/CLI flows.
- Added focused unit tests for process-control lifecycle helpers and worker command-protocol coercion.

### Documentation

- Updated README/docs for process-only execution, current internal module split, and worker-session lifecycle behavior.
- Refreshed README testing matrix and internal runtime notes to match current process-control/protocol behavior.

## [0.4.0] - 2026-03-08

### Changed

- Renamed the REPL command module to `safe_repl.repl_command_registry` for clearer ownership and naming consistency.
- Simplified REPL startup output to a concise intro hint (`quit`/`exit`) plus command help hint.
- Expanded built-in REPL inspection commands (`:level`, `:functions`, `:nodes`, `:imports`) and aligned startup guidance with command-driven discovery.

### Tests

- Simplified/parameterized overlapping REPL command and startup tests in `tests/test_safe_repl.py`.
- Renamed doctest module file to match current command-registry naming (`tests/test_doctest_repl_command_registry.py`).

### Documentation

- Updated README and CLI help text to match current REPL command semantics (`:vars` and `:vars values`).
- Removed stale references to deprecated REPL detail flags and old command-module naming.

## [0.3.1] - 2026-03-07

### Changed

- Merged `safe_repl.execution_mode` into `safe_repl.execution` so execution mode types/coercion now live in one module.
- Merged `safe_repl.session_repl` helpers into `safe_repl.session` and simplified session internals.
- Reduced small single-use helper indirection across session/import/runtime modules while preserving behavior.

### Fixed

- Aligned `SafeSession.from_cli_args` import behavior with documented CLI `--import` semantics:
  - no `--import` uses default `math:*`
  - any `--import` usage disables default math auto-import
  - `--import ""` disables auto-import without adding imports

### Documentation

- Updated README to explicitly describe `--import` default/override behavior.
- Clarified internal module layout after execution/session helper merges.

## [0.3.0] - 2026-03-07

### Added

- Process-isolated execution backend via `safe_exec_process_isolated(...)` with worker IPC, timeout enforcement, and best-effort worker memory limits.
- New execution mode model via `ExecutionMode` enum (`in-process`, `process`) with normalization helpers and package-level export.
- Persistent subprocess lifecycle support on `SafeSession`:
  - `open_subprocess_session()`
  - `close_subprocess_session()`
  - `reopen_subprocess_session()`
- New tests covering subprocess-isolated execution behavior in `tests/test_isolation.py`.

### Changed

- Refactored monolithic implementation into focused modules (`policy`, `validator`, `engine`, `imports`, `session`, `cli`) with stable top-level re-exports.
- `Permissions` now stores per-instance timeout/memory limits and supports optional constructor overrides.
- `PermissionLevel` parsing now relies on enum `_missing_` behavior with warning + fallback to level `0` (`MINIMUM`).
- `SafeSession.from_level(...)` removed; sessions are now constructed explicitly with `SafeSession(Permissions(...))`.
- REPL startup detail display is now opt-in and supports level-aware defaults and CLI flags.
- CLI now supports `--execution-mode {in-process,process}`.
- `SafeSession` now accepts configurable execution mode and supports one-off mode overrides for `exec(...)` and `repl(...)`.
- Default execution mode is now `process` for stronger isolation by default.
- REPL in process mode now opens one persistent subprocess worker for the session run and closes it on exit.
- Execution internals were split for clarity:
  - `safe_repl.execution` handles mode coercion and dispatch.
  - `safe_repl.process_isolation` is the process-execution module.
  - `safe_repl.process_protocol` centralizes worker IPC schema/constants.

### Fixed

- Mutable default argument usage removed from `Permissions.__init__`.
- Process mode exception mapping now preserves builtin exception types raised by user code (for example `NameError`) instead of collapsing to generic runtime errors.
- Typing compatibility improved for multiprocessing process construction and worker-command payload coercion.

### Developer Experience

- CLI/import helpers now raise typed library exceptions (`SafeReplImportError`, `SafeReplCliArgError`) while CLI boundary handles stderr + exit code `1`.
- Added unit and integration CLI tests for error handling and flag behavior.
- Expanded README with API surface, exception handling, execution-mode defaults, internal module split notes, and persistent subprocess lifecycle examples.

[Unreleased]: https://github.com/Darth-Demetrius/python-sub-REPL/compare/v0.5.0...HEAD
[0.5.0]: https://github.com/Darth-Demetrius/python-sub-REPL/releases/tag/v0.5.0
[0.4.3]: https://github.com/Darth-Demetrius/python-sub-REPL/releases/tag/v0.4.3
[0.4.2]: https://github.com/Darth-Demetrius/python-sub-REPL/releases/tag/v0.4.2
[0.4.1]: https://github.com/Darth-Demetrius/python-sub-REPL/releases/tag/v0.4.1
[0.4.0]: https://github.com/Darth-Demetrius/python-sub-REPL/releases/tag/v0.4.0
[0.3.1]: https://github.com/Darth-Demetrius/python-sub-REPL/releases/tag/v0.3.1
[0.3.0]: https://github.com/Darth-Demetrius/python-sub-REPL/releases/tag/v0.3.0
