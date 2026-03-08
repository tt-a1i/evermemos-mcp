# Changelog

All notable changes to this project will be documented in this file.

## [0.4.6] - 2026-03-08

### Added
- Added explicit lifecycle-aware guidance for `space_id` templates, `fetch_history` timeline review, and `forget` verification across tool descriptions, README, and client docs.
- Added runnable and tested demo guidance so live walkthroughs verify delete effects with `fetch_history` before fallback `recall` checks.

### Changed
- Promoted `request_status` to the standard write-after verification path in prompts, client integrations, and competition/demo narratives.
- Marked roadmap items 1-6 as completed and kept items 7-8 explicitly deferred pending upstream stability or later product decisions.

### Fixed
- Aligned requirements and architecture docs with the actual 7-tool contract, including a dedicated `request_status` section.

## [0.4.5] - 2026-03-07

### Changed
- Updated Cherry Studio and `uvx` docs to recommend `evermemos-mcp@latest` and explicit cache refresh steps after upgrades.

### Fixed
- Added Chinese name extraction support for phrases like `用户名叫 Tom` when mirroring chat identity into conversation metadata.
- Stopped exposing placeholder names such as `mcp-user` as user-facing identity fallback results in `briefing`.

## [0.4.4] - 2026-03-07

### Added
- Added `request_status` as a first-class MCP tool so clients can check async write progress explicitly.

### Changed
- Updated README feature docs to describe metadata-backed identity fallback as best-effort behavior.
- Surfaced metadata-backed identity and preference fallback results when extracted recall results are unavailable.

### Fixed
- Mirrored chat identity/preferences into `conversation-meta` for better short-fact recall in EverMemOS Cloud.
- Restricted pending identity fallback to single `chat:*` recall scopes to avoid leaking chat heuristics into unrelated multi-space searches.

## [0.4.3] - 2026-03-07

### Added
- `scripts/competition_lifecycle_appendix.py` to generate live write/read/delete appendix artifacts with searchable latency, isolation checks, and raw logs.
- `docs/competition/final_submission_30s_checklist.md` for final handoff and submission verification.

### Changed
- Updated README, submission docs, and demo playbooks to point at the latest competition evidence and to describe the current Cloud `forget` limitation accurately.
- Refined lifecycle appendix reporting so partial runs show explicit stage logs and `SKIP` semantics instead of ambiguous waits.
- Updated competition benchmark metadata generation to infer evidence dates from artifact paths and emit cleaner relative paths.

### Fixed
- Hardened Cloud catalog recovery for `original_data` payloads returned as lists.
- Added compatibility fallbacks for Cloud conversation metadata create/update behavior when group-level `scene` / `scene_desc` fields are rejected.
- Improved live walkthrough deletion target selection by falling back to `fetch_history` when recall returns profile-only rows.
- Surfaced clearer warnings when Cloud delete returns `ok` but does not actually remove the targeted memory.

## [0.4.2] - 2026-03-07

### Added
- Space auto-detection from git remote — `space_id` now optional in `remember` and `recall`, auto-inferred as `coding:<repo-name>`.
- `EVERMEMOS_DEFAULT_SPACE` environment variable for explicit default space override.
- `smithery.yaml` for MCP registry listing (smithery.ai / mcp.so).
- Actionable error diagnostics with hints for API key missing, network unreachable, 401 auth, and 429 rate limit.

### Changed
- Enhanced all 6 tool descriptions for better AI comprehension and proactive usage.
- Improved `remember` return hint with flush guidance and verification instructions.

## [0.4.1] - 2026-03-07

### Added
- PyPI publishing via `uvx evermemos-mcp` — no clone needed for end users.
- Auto-memory prompt templates (`docs/auto-memory-prompt.md`) for Claude Code, Cursor, and Cline.
- GitHub Actions workflow for automated PyPI releases on tag.

### Changed
- Updated READMEs with PyPI install instructions (Option A) and documentation links.

### Fixed
- Fixed space catalog recovery parsing to read `original_data.messages[].content` first, resolving `list_spaces` returning empty results.

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
