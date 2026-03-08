# Technical Architecture (Phase 2 / V1)

[English](02-architecture.md) | [Chinese](02-architecture.zh-CN.md)

## 1) Design Goals
- Build a universal MCP memory layer for coding/chat/study clients
- Guarantee V1 usability, isolation, traceability, and controlled deletion
- Keep EverMemOS integration thin and pragmatic

## 2) System Boundary

```text
MCP Client (Claude/Cursor/Cherry...)
        |
        | MCP tools
        v
evermemos-mcp server
  - tool handlers
  - space router
  - space catalog service
  - memory service
  - evermemos api client
        |
        | HTTP
        v
EverMemOS API
```

## 3) Core Modules

### 3.1 `server` (MCP entry)
- Registers 7 tools: `list_spaces`, `remember`, `request_status`, `recall`, `briefing`, `forget`, `fetch_history`
- Handles input validation, error mapping, and uniform response shape

### 3.2 `space_router`
- Routing only; no repository/directory guessing
- Priority:
  1. Explicit `space_id` from user/agent
  2. Semantic match from `list_spaces` and descriptions

### 3.3 `space_catalog_service`
- Provides `space_id`, `description`, `memory_count`, `last_used_at`
- Cloud-only metadata (no local file persistence)
- Current implementation:
  1. Enumerate via reserved `space::catalog` (backward compatible)
  2. Dual-write `conversation-meta` (`description/scene/tags/llm_custom_setting`)
  3. Recovery can enrich descriptions from `conversation-meta`

### 3.4 `memory_service`
- Maps MCP semantics to EverMemOS API calls
- Assembles citation fields (`timestamp/snippet/type/score`)
- Enforces explicit-id deletion safety

### 3.5 `evermemos_client`
- Wraps `/api/v0/memories`, `/api/v0/memories/search`, `/api/v0/status/request`
- Request status uses `/api/v0/status/request` (Cloud v0 canonical path)
- Adds auth, timeout, retries (including 429 backoff), and error normalization
- Supports local `v1` endpoints via configuration
- Note: upstream fetch/search contract is `GET + JSON body`; some proxies/WAFs may strip GET bodies

## 4) Data & Isolation Model

### 4.1 Cloud-first data strategy
- Memory bodies are stored in EverMemOS
- Space metadata is also stored in EverMemOS
- Server keeps process-local cache only (no disk persistence)

### 4.2 `space_id` policy
- `space_id` is the primary isolation key
- Domains (coding/chat/study) are naming conventions, not API-level tool differences

### 4.3 Mapping
- Recommended mapping: `group_id = "space::<space_id>"`
- `user_id` is fixed or configurable (`mcp-user` by default)
- All write/search/delete calls use the same group mapping

## 5) Tool Contract (V1)

### 5.1 `list_spaces`
- Input: `query?`, `limit?=20`
- Output: `ok`, `spaces[]` (`space_id/description/memory_count/last_used_at`)

### 5.2 `remember`
- Input:
  - `content` (required)
  - `space_id` (required)
  - `description?`
  - `sender?=user`
  - `user_id?` / `role?`
  - `flush?=false`
  - `include_status?=false`
- Output:
  - `ok`, `space_id`
  - `message_id` (submitted message id used for write request)
  - `request_id`, `created_at`, `processing_hint`
  - `lifecycle` (`state`, `state_counts`, `searchable`, `message`)
  - `request_status` (when `include_status=true`)

### 5.3 `request_status`
- Input: `request_id` (required)
- Behavior: checks upstream async write status after `remember`
- Output: `ok`, `request_id`, `success`, `found`, optional `error`, `lifecycle`
- Guidance: check `success/error` first, then interpret `lifecycle.state`

### 5.4 `recall`
- Input:
  - `query` (required)
  - `space_id?` (single-space scope)
  - `space_ids?` (multi-space scope, max 10 unique; can be combined with `space_id`)
  - `top_k?=10` (range: -1 or 1-100; `-1` disables service-side truncation and uses upstream `top_k=100`)
  - `retrieve_method?=hybrid` (`keyword|hybrid|vector|rrf|agentic|auto`)
  - `memory_types?` (`profile|episodic_memory`)
    - Cloud search currently supports only these two memory types
    - for `hybrid|rrf|agentic`: defaults to `profile + episodic_memory`
    - for `auto`: filter applies to keyword branch; hybrid branch uses the same subset
  - `start_time?`, `end_time?` (ISO 8601; naive values default to UTC; applied to episodic memory)
  - `current_time?` (ISO 8601)
  - `radius?` (0-1)
  - `include_metadata?=false`
  - `user_id?` (optional identity scope in shared spaces)
- Output:
  - `ok`, `space_ids`, `results[]`
  - `space_id` is also returned when only one space is used
  - `retrieve_method_actual=auto(hybrid+keyword)` when auto strategy is used
  - `pending_count/pending_hint` when extraction is pending
  - `lifecycle` (`queued|provisional|fallback|searchable|empty` summary for the current response)
  - row-level `results[].stability` distinguishes formal extracted rows from provisional/fallback rows
  - optional `warnings[]` includes source-space recovery hints when upstream omits `group_id`
  - `partial_hint/partial_errors` when upstream returns partial results

### 5.5 `briefing`
- Input: `space_id`, `max_items?=8`, `start_time?`, `end_time?`, `user_id?`
- Behavior: layered fetch and synthesis from `profile + episodic_memory + event_log + foresight`
- Time filters apply to `episodic_memory`, `event_log`, and `foresight` (not `profile`)
- Output: `ok`, `space_id`, `summary`, `highlights[]`, `lifecycle`
- Row-level `highlights[].stability` is `searchable` for formal memories and `fallback` for metadata fallback

### 5.6 `forget`
- Input: `memory_ids[]`, `space_id`, `reason?`, `user_id?`
- Behavior: explicit-id deletion only; concurrent deletes with partial-failure reporting
- Behavior: delete defaults to MCP client identity scope when `user_id` is omitted
- Behavior: current Cloud semantics are best-effort, so callers should verify before and after deletion rather than assuming immediate removal
- Output: `ok`, `space_id`, `deleted_count`, optional `delete_scope_user_id`, optional `errors[]`
- Output: idempotent delete; unmatched IDs are reported via optional `unmatched_ids/unmatched_count` and `warnings[]`

### 5.7 `fetch_history`
- Input: `space_id`, `memory_type?=episodic_memory`, `limit?=50`, `offset?=0`, `user_id?`, `start_time?`, `end_time?`, `include_metadata?=false`
- Behavior: paginated fetch by memory type for timeline-style review (including `event_log` and `foresight`)
- Behavior: keeps exact 0-based offset semantics by stitching upstream `page/page_size` responses when needed
- Behavior: primary review path for timeline audits and pre/post delete verification when recall ranking is not enough
- Output: `ok`, `space_id`, `memory_type`, `items[]` (`memory_id`, `timestamp`, `snippet` + `content`, optional `source_message_id`), `count`, optional `total_count`, `has_more`, optional `next_offset`

## 6) Citation Policy (V1)
- `recall/briefing` results include traceable evidence fields:
  - `timestamp`
  - `snippet`
  - `memory_type`
  - `score` (if available)
  - `source_message_id` (if upstream includes a resolvable message reference)

## 7) Error Semantics
- `CONFIG_ERROR`: missing/invalid config
- `UPSTREAM_UNAVAILABLE`: timeout/network/upstream outage
- `INVALID_INPUT`: tool argument validation error
- `NOT_FOUND`: empty query result or missing target

## 8) Test Matrix (V1)
- Contract tests for all 7 tools
- Isolation tests across different `space_id`
- Citation field tests for `recall/briefing`
- Safety tests for explicit-id deletion
- Failure tests for upstream outage and malformed responses

## 9) Demo Strategy
- Scenario A (coding): remember architecture decisions -> recall in new session
- Scenario B (chat): remember preference -> retrieve in follow-up Q&A
- Scenario C (study): remember learning notes -> briefing restoration

## 10) Technical Risks & Mitigations

### 10.1 Async extraction latency
- Risk: Cloud write is queued; recall is not immediately available
- Mitigation: preload memories before live demo, expose pending hints in recall

### 10.2 Briefing synthesis quality
- Use layered fetch (profile/episodic/event_log/foresight) instead of opaque summarization

### 10.3 MCP transport
- V1 defaults to `stdio` for compatibility and reproducibility

## 11) Delivery Order
1. Validate EverMemOS API behavior
2. Implement `evermemos_client` + catalog/router
3. Implement `remember` + `recall`
4. Implement `briefing` + `forget`
5. Add citation fields and complete test matrix

## 12) Non-goals for V1
- Auto summary write-back (V1.1)
- Team collaboration scope (V1.1)
- Advanced redaction/policy engine (later)
