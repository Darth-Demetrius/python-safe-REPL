# Changelog

## [Unreleased]

### Added

- Added `tools/bench_security.py` to benchmark security-surface import-time and runtime paths (`Permissions` construction and `validate_ast`).

### Changed

- Optimized validation/runtime hot paths across security modules by removing duplicate attribute-handler work in AST validation and reducing repeated lookup overhead in validation and allowed-name collection.
- Added Linux-focused process memory limit enforcement in process isolation by applying child `RLIMIT_AS` via `with_limits(...)` and attempting best-effort cgroup v2 PID attachment through the new `safe_repl.sandbox` helpers.

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

[Unreleased]: https://github.com/Darth-Demetrius/python-sub-REPL/compare/v0.4.1...HEAD
[0.4.1]: https://github.com/Darth-Demetrius/python-sub-REPL/releases/tag/v0.4.1
[0.4.0]: https://github.com/Darth-Demetrius/python-sub-REPL/releases/tag/v0.4.0
[0.3.1]: https://github.com/Darth-Demetrius/python-sub-REPL/releases/tag/v0.3.1
[0.3.0]: https://github.com/Darth-Demetrius/python-sub-REPL/releases/tag/v0.3.0
