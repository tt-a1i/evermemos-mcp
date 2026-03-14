# Changelog

All notable changes to this project will be documented in this file.

## [0.5.6] - 2026-03-14

### Changed
- Rewrote sensitive content detection with two-tier approach: Tier 1 matches specific formats (sk-, AKIA, ghp_, private keys, connection strings). Tier 2 blocks on keyword presence alone (password, api_key, secret, token, credential, 密码, 密钥, 秘钥, 凭证) regardless of value format, so AI model rewrites cannot bypass the guard.

## [0.5.5] - 2026-03-14

### Fixed
- Added bare `key` to sensitive keyword list so `我的key是xxx` and `key=xxx` are now blocked.
- Removed `allow_sensitive` from tool schema so AI models cannot bypass content guard preemptively. The parameter still works but is only revealed in the blocked response hint.

## [0.5.4] - 2026-03-14

### Changed
- Hidden `allow_sensitive` from tool description so AI models try the normal path first and see the content guard block before bypassing it.

## [0.5.3] - 2026-03-14

### Fixed
- Sensitive content guard now supports Chinese connectors (是/为/：) and Chinese keywords (密码/密钥/秘钥).
- Removed minimum value length requirement — any value after a sensitive keyword is now blocked regardless of length.
- Fixed `\b` word boundary not matching after CJK characters in Python regex.

## [0.5.2] - 2026-03-14

### Fixed
- Changed `flush` default from `false` to `true` so memories are extracted immediately instead of waiting indefinitely in the queue.

## [0.5.1] - 2026-03-12

### Fixed
- Added Python version classifiers to PyPI metadata (fixes "python missing" badge).

## [0.5.0] - 2026-03-12

### Added
- Sensitive content detection: `remember` scans for API keys, passwords, tokens, private keys, and connection strings before storing. Blocked writes return findings so the user can confirm; retry with `allow_sensitive=true` after confirmation.
- Memory conflict detection: `remember` checks for similar existing memories in `chat:*` spaces by default. Conflicts are surfaced in the response with memory IDs and snippets. Use `check_conflicts` parameter to override auto behavior.
- New module `content_guard.py` with `scan_sensitive_content()` for pattern-based sensitive content detection.

### Changed
- Updated `remember` tool description to document content guard and conflict detection behavior.
- Added `allow_sensitive` and `check_conflicts` parameters to `remember` tool schema.

## [0.4.8] - 2026-03-10

### Fixed
- Fixed `forget` tool: now resolves memcell `parent_id` before calling Cloud DELETE API, which previously returned 0 affected records when using derived record IDs.
- Fixed delete count parsing: Cloud DELETE always returns `result.count=0` but the real count is in the `message` string; now parsed correctly via regex.
- Removed `user_id` from Cloud DELETE calls — upstream returns 0 affected when `user_id` is included alongside `memory_id`.

### Added
- `_extract_parent_id()` helper extracts memcell parent_id from API responses.
- `parent_id` field now exposed in `fetch_history` and `recall` row outputs (when available).
- `_resolve_parent_ids()` scans recent memories (100 per type) to map derived record IDs to their memcell parent_id before deletion.
- `deleted_count_note` field in forget output explains that the count reflects total upstream records affected (may exceed input count).
- Warning when parent_id resolution fails for some IDs (e.g. older memories beyond the 100-item scan window).

### Changed
- Updated `forget` tool description to reflect honest boundaries: parent_id is optional, 100-item scan window, user_id not sent to DELETE, some IDs may remain unmatched.

## [0.4.7] - 2026-03-08

### Changed
- Tightened MCP tool descriptions for `list_spaces`, `recall`, `briefing`, and `forget` so agents make fewer optimistic assumptions under current EverMemOS Cloud behavior.
- Clarified `remember.space_id` defaulting to mention both `EVERMEMOS_DEFAULT_SPACE` and git-remote auto-detection.
- Updated release-facing docs and explicit pinned-version examples from `0.4.6` to `0.4.7`.

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
