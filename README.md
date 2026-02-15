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

## Core Behavior (Cloud v0)
- Writes are async queued: `remember` returns a `request_id` and does not guarantee immediate recall
- `recall` can include `pending_count` and `pending_hint` while extraction is still running
- `space_id` is the only isolation key (`<domain>:<slug>`)
- Routing is expected to use `list_spaces` and descriptions, not cwd/git auto-detection

## Quick Start
- Cloud defaults are built in: `EVERMEMOS_BASE_URL=https://api.evermind.ai`, `EVERMEMOS_API_VERSION=v0`
- Required for Cloud: `EVERMEMOS_API_KEY`
- Start server: `uv run evermemos-mcp` or `uv run python -m evermemos_mcp.server`
- Optional: `EVERMEMOS_ENABLE_CONVERSATION_META=true` (enabled by default)
- Optional: `EVERMEMOS_LLM_CUSTOM_SETTING_JSON` to pass `llm_custom_setting`

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
- `remember`: optional `include_status`; returns `message_id`, `request_id`, `created_at`, `processing_hint`
- `recall`: supports `retrieve_method=keyword|hybrid|vector|rrf|agentic`
- `recall`: supports `start_time/end_time` (ISO 8601; naive values default to UTC), applied to `episodic_memory`
- `recall`: supports `current_time`, `radius`, `include_metadata`, optional `memory_types`
- `recall` and `briefing`: return traceable fields (`memory_type`, `snippet`, `timestamp`, `score`)
- `briefing`: combines `profile`, `episodic_memory`, `event_log`, and `foresight`
- `briefing` time filters apply to `episodic_memory` and `event_log` (not `foresight`)
- Cloud `fetch/search` follow upstream `GET + JSON body`; some proxies/WAFs may strip GET bodies

## MCP Client Integration
- Integration guide: `docs/05-client-integrations.md`
- Copy-paste snippets: `docs/mcp-config-snippets/`
- Demo scripts: `scripts/demo_preload.py`, `scripts/demo_live_walkthrough.py`

## Development
- Install dev dependencies: `uv sync --group dev`
- Lint: `uv run ruff check`
- Test: `uv run pytest`
- CI: `.github/workflows/ci.yml` (runs ruff + pytest on push/PR)

## Documentation
- Requirements: `docs/01-requirements.md`
- Architecture: `docs/02-architecture.md`
- Demo playbook: `docs/03-demo-playbook.md`
- Submission notes: `docs/04-submission.md`
- Client integrations: `docs/05-client-integrations.md`
- Work plan: `task_plan.md`
