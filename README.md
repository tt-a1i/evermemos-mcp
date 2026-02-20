# evermemos-mcp

[English](README.md) | [Chinese](README.zh-CN.md)

Universal MCP memory layer powered by EverMemOS.

## Positioning
- Works with MCP-compatible clients (coding/chat/study workflows)
- Uses `space_id` as the primary isolation key
- Cloud-first strategy with no local persistence

## V1 Tool Set
- `list_spaces`
- `remember`
- `recall`
- `briefing`
- `forget`
- `fetch_history`

## Core Behavior (Cloud v0)
- Writes are async queued: `remember` returns a `request_id` and does not guarantee immediate recall
- `recall` can include `pending_count` and `pending_hint` while extraction is still running
- `space_id` is the only isolation key (`<domain>:<slug>`)
- Routing is expected to use `list_spaces` and descriptions, not cwd/git auto-detection
- `remember` with a dynamic `user_id` best-effort syncs participant identity into conversation metadata

## Why `space::catalog` Exists
- EverMemOS metadata APIs are scoped by `group_id` (`get/set/update`) and do not provide a global list endpoint
- `list_spaces` therefore uses a reserved catalog group (`space::catalog`) as a durable index
- Space registration uses best-effort dual-write: catalog entry text + `conversation-meta` metadata sync
- On recovery, catalog entries are read first, then `conversation-meta` is used to enrich descriptions

## Quick Start
- Cloud defaults are built in: `EVERMEMOS_BASE_URL=https://api.evermind.ai`, `EVERMEMOS_API_VERSION=v0`
- Required for Cloud: `EVERMEMOS_API_KEY`
- Start server: `uv run evermemos-mcp` or `uv run python -m evermemos_mcp.server`
- Optional: `EVERMEMOS_ENABLE_CONVERSATION_META=true` (enabled by default)
- Optional: `EVERMEMOS_LLM_CUSTOM_SETTING_JSON` to pass `llm_custom_setting`
- Optional: `EVERMEMOS_USER_DETAILS_JSON` to pass conversation `user_details`
- Optional: `EVERMEMOS_DEFAULT_TIMEZONE` for conversation metadata timezone (default `UTC`)

## Installation
- Clone repo: `git clone https://github.com/tt-a1i/evermemos-mcp.git`
- Enter project: `cd evermemos-mcp`
- Create env file: `cp .env.example .env` and set `EVERMEMOS_API_KEY`
- Run from source (recommended): `uv run --directory . evermemos-mcp`
- Optional global install: `uv tool install --from . evermemos-mcp`

## Generic MCP Configuration (stdio)
Use this generic config in any MCP client that supports `command + args + env`:

```json
{
  "mcpServers": {
    "evermemos-mcp": {
      "type": "stdio",
      "command": "uv",
      "args": [
        "run",
        "--directory",
        "/ABS/PATH/evermemos-mcp",
        "evermemos-mcp"
      ],
      "env": {
        "EVERMEMOS_API_KEY": "YOUR_KEY",
        "EVERMEMOS_USER_ID": "mcp-user"
      }
    }
  }
}
```

If globally installed, replace with `"command": "evermemos-mcp", "args": []`.

## Tool Contract Notes
- `list_spaces`: `memory_count` is approximate in Cloud mode due async extraction
- `remember`: optional `include_status`; returns `message_id` (submitted message ID), `request_id`, `created_at`, `processing_hint`
- `remember`: also returns `memory_count_hint` to clarify Cloud-mode counts are approximate
- `remember`: forwards `flush` explicitly (`true` or `false`) to keep behavior deterministic
- `remember`: default `flush=false`; use `flush=true` only at clear conversation boundaries
- `recall`: supports `retrieve_method=keyword|hybrid|vector|rrf|agentic|auto`
- `recall`: default `top_k=10`; accepted range is `-1` or `1-100` (`-1` means all, capped by upstream)
- `recall`: supports optional `user_id` filter for multi-user spaces
- `recall`: accepts `space_id` (single space) or `space_ids` (multi-space, up to 10 unique)
- `recall`: response includes `space_ids`; when upstream provides `group_id`, each row may include `space_id`
- `recall`: supports `start_time/end_time` (ISO 8601; naive values default to UTC), applied to `episodic_memory`
- `recall`: supports `current_time`, `radius`, `include_metadata`, optional `memory_types`
- `recall`: `memory_types` currently supports only `profile|episodic_memory` (Cloud search API limitation)
- `recall`: for `hybrid|rrf|agentic`, default `memory_types` is `profile+episodic_memory`
- `recall`: `auto` runs `hybrid + keyword` in parallel, deduplicates by `memory_id`, and merges partial failures as hints
- `recall` and `briefing`: return traceable fields (`memory_type`, `snippet`, `timestamp`, `score`, optional `source_message_id`)
- `briefing`: combines `profile`, `episodic_memory`, `event_log`, and `foresight`
- `briefing` time filters apply to `episodic_memory`, `event_log`, and `foresight` (not `profile`)
- `briefing`: supports optional `user_id` filter
- `forget`: supports optional `user_id` scope; defaults to the MCP client identity for safer multi-user deletes
- `forget`: returns `ok=false` with `errors[]` when requested IDs match no rows under the active delete scope
- `fetch_history`: paginates by `memory_type` (`profile|episodic_memory|foresight|event_log`) with exact 0-based `limit/offset`
- `fetch_history`: internally stitches page-based upstream results to keep non-aligned offsets accurate
- `fetch_history`: returns `has_more/next_offset` and trace fields (`memory_id`, `timestamp`, `snippet` + `content`, optional `source_message_id`)
- Cloud `fetch/search` follow upstream `GET + JSON body`; some proxies/WAFs may strip GET bodies
- Request status uses `/status/request` (Cloud v0 canonical path)

### `flush` Boundary Rule
- `flush` is caller-controlled (MCP client/agent), not auto-inferred by this server
- Always pass `flush` explicitly; do not rely on upstream defaults
- Use `flush=false` for intermediate turns in one ongoing conversation
- Use `flush=true` for final answer/summary/topic switch/session close or timeout
- If uncertain, prefer `flush=true` as the safe fallback
- Prompt template and host-side rules: `docs/05-client-integrations.md`

## MCP Client Integration
- Integration guide: `docs/05-client-integrations.md`
- Copy-paste snippets: `docs/mcp-config-snippets/`
- Demo scripts: `scripts/demo_preload.py`, `scripts/demo_live_walkthrough.py`

## Development
- Install dev dependencies: `uv sync --group dev`
- Lint: `uv run ruff check`
- Test: `uv run pytest`
- Optional integration tests: `EVERMEMOS_RUN_INTEGRATION_TESTS=true uv run pytest -m integration`
- CI: `.github/workflows/ci.yml` (runs ruff + pytest on push/PR)

## Documentation
- Requirements: `docs/01-requirements.md`
- Architecture: `docs/02-architecture.md`
- Demo playbook: `docs/03-demo-playbook.md`
- Submission notes: `docs/04-submission.md`
- Client integrations: `docs/05-client-integrations.md`
- Work plan: `task_plan.md`
