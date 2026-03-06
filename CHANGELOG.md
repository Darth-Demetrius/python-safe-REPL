# Changelog

## Unreleased

### Changed
- Refactored monolithic implementation into focused modules (`policy`, `validator`, `engine`, `imports`, `session`, `cli`) with stable top-level re-exports.
- `Permissions` now stores per-instance timeout/memory limits and supports optional constructor overrides.
- `PermissionLevel` parsing now relies on enum `_missing_` behavior with warning + fallback to level `0` (`MINIMUM`).
- `SafeSession.from_level(...)` removed; sessions are now constructed explicitly with `SafeSession(Permissions(...))`.
- REPL startup detail display is now opt-in and supports level-aware defaults and CLI flags.

### Fixed
- Mutable default argument usage removed from `Permissions.__init__`.

### Developer Experience
- CLI/import helpers now raise typed library exceptions (`SafeReplImportError`, `SafeReplCliArgError`) while CLI boundary handles stderr + exit code `1`.
- Added unit and integration CLI tests for error handling and flag behavior.
- Expanded README with API surface, exception handling, and CLI detail-flag documentation.
