# Changelog

All notable changes to this project will be documented in this file.

## [0.4.0] - 2026-02-25

### Added
- Added `fetch_history` with exact offset-preserving pagination stitching for timeline use cases.
- Added multi-space recall support (`space_id` + `space_ids`) with scoped dedupe and source-space recovery warnings.
- Added optional `user_id` filtering for `recall`, `briefing`, and safer scoped `forget`.
- Added competition preparation docs:
  - `docs/06-benchmark.md`
  - `docs/07-release-checklist.md`
  - `docs/competition/*` planning and submission assets

### Changed
- Updated recall `top_k=-1` semantics to avoid passing `-1` upstream directly; service now uses upstream-safe `top_k=100`.
- Improved source-space recovery logic:
  - stronger row-key fallback (`memory_id` -> `source_message_id` -> typed text key)
  - probe deduping for already-attempted unresolved keys
  - configurable probe behavior via env (`EVERMEMOS_SOURCE_RECOVERY_PROBE_TOP_K`, `EVERMEMOS_SOURCE_RECOVERY_PROBE_CONCURRENCY`)
- Expanded briefing behavior for no-`user_id` scope to include multiple profile entries.
- Hardened conversation metadata persistence with snapshot caching, conflict re-fetch, and lock lifecycle cleanup.

### Fixed
- Fixed pending-message dedupe and maintained idempotent `forget` behavior on unmatched IDs.
- Fixed recall/profile mapping robustness (`memory_id`, `source_message_id`, grouped search shape handling).
- Fixed fetch-history boundary correctness for non-aligned offsets and has_more signaling consistency.
- Reduced catalog recovery truncation risk by preferring unbounded search (`top_k=-1`) and falling back to bounded values when required.

### Docs
- Added and expanded bilingual docs for architecture, client integrations, demo playbook, and submission guidance.
- Clarified Cloud async extraction behavior, `flush` boundary rules, and reproducible demo workflows.

## [0.1.0] - 2026-02-10

### Added
- Initial public release of `evermemos-mcp`.
- Core MCP tools: `list_spaces`, `remember`, `recall`, `briefing`, `forget`.
- EverMemOS Cloud v0 client wrapper with retries, error normalization, and metadata integration.
