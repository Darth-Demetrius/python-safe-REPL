# Changelog

## Unreleased

- No changes yet.

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
	- `safe_repl.subprocess_runtime` handles process worker protocol and lifecycle.

### Fixed
- Mutable default argument usage removed from `Permissions.__init__`.
- Process mode exception mapping now preserves builtin exception types raised by user code (for example `NameError`) instead of collapsing to generic runtime errors.
- Typing compatibility improved for multiprocessing process construction and worker-command payload coercion.

### Developer Experience
- CLI/import helpers now raise typed library exceptions (`SafeReplImportError`, `SafeReplCliArgError`) while CLI boundary handles stderr + exit code `1`.
- Added unit and integration CLI tests for error handling and flag behavior.
- Expanded README with API surface, exception handling, execution-mode defaults, internal module split notes, and persistent subprocess lifecycle examples.

[Unreleased]: https://github.com/Darth-Demetrius/python-sub-REPL/compare/v0.3.0...HEAD
[0.3.0]: https://github.com/Darth-Demetrius/python-sub-REPL/releases/tag/v0.3.0
