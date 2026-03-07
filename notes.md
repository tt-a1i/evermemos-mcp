# Notes: Requirements & Validation Research

[English](notes.md) | [Chinese](notes.zh-CN.md)

## Competition Context
- Hackathon: Memory Genesis 2026 (Track 2: Platform Plugin)
- Submission deadline: Mar 15, 2026
- Evaluation priority: Quality & Execution > Memory Integration > Community Impact
- Submission package: GitHub repo + README + 3-5 minute video

## EverMemOS API Summary
- Cloud paths: `/api/v0/memories`, `/api/v0/memories/search`
- Local-compatible paths: `/api/v1/memories`, `/api/v1/memories/search`
- `flush=true` can mark a conversation boundary
- Memory types: `episodic_memory`, `profile`, `foresight`, `event_log`
- Retrieval methods: `keyword`, `vector`, `hybrid`, `rrf`, `agentic`

## MCP Basics
- Server exposes callable tools to MCP clients
- Tool schema includes name, description, and JSON input schema
- Transport options: `stdio` (local) and `SSE` (remote)

## User Pain Points
- New sessions lose project preferences and context
- Architecture decisions must be repeated
- Bug-fix history is not retained
- Coding style preferences are repeatedly re-explained

## Phase 3.1 Validation Results

### Connectivity
- Cloud health endpoint is reachable
- v0 auth works via `Authorization: Bearer` + `X-API-Key`

### Cloud Write Behavior
- Writes return `202 Accepted` (queued), not immediate extraction
- Typical response: `{ "status": "queued", "request_id": "..." }`

### Extraction Timing
- Cloud extraction usually takes around 2-5 minutes
- Immediate `remember -> recall` often returns empty
- `pending_messages` is useful as an extraction-progress signal

### Search/Fetch Observations
- `keyword` and `hybrid` retrieval work
- Profile memory behaves differently across search/fetch contexts
- Group-level isolation via `group_id` is effective

### Product Implications
1. `remember` must communicate queued async behavior clearly
2. `recall` should expose pending hints to avoid misleading UX
3. Demo must preload memory before live retrieval
4. Conversation-meta integration is optional but useful for richer metadata

## Product Direction Notes
- Positioning evolved from coding-only to universal MCP memory layer
- Wedge remains developer tooling for V1 validation
- Expansion target includes chat clients (for example Cherry Studio)
- Isolation model moved from `project_id` to generic `space_id`
