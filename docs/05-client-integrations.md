# MCP Client Integration Guide (Claude Code / Cursor / Cline / Cherry)

[English](05-client-integrations.md) | [Chinese](05-client-integrations.zh-CN.md)

This document provides copy-paste MCP server configuration for `evermemos-mcp`.

Config snippet directory: `docs/mcp-config-snippets/`

## 1) Prerequisites
1. `uv` / `uvx` available locally, or the project runnable from source
2. Executable command available (`uvx` for releases, `uv` for source)
3. Cloud key configured: `EVERMEMOS_API_KEY`
4. Optional custom extraction config: `EVERMEMOS_LLM_CUSTOM_SETTING_JSON`
5. Optional conversation metadata timezone: `EVERMEMOS_DEFAULT_TIMEZONE` (default `UTC`)

> `EVERMEMOS_BASE_URL` and `EVERMEMOS_API_VERSION` already default to Cloud (`https://api.evermind.ai` + `v0`) in this project.

## 2) Recommended Startup

### Option A: Published release via `uvx` (recommended)

```json
{
  "command": "uvx",
  "args": ["evermemos-mcp@latest"],
  "env": {
    "EVERMEMOS_API_KEY": "YOUR_KEY"
  }
}
```

### Option B: Run from source

```json
{
  "command": "uv",
  "args": ["run", "--directory", "/ABS/PATH/evermemos-mcp", "evermemos-mcp"],
  "env": {
    "EVERMEMOS_API_KEY": "YOUR_KEY"
  }
}
```

## 3) Cursor Example

```json
{
  "mcpServers": {
    "evermemos": {
      "command": "uvx",
      "args": ["evermemos-mcp@latest"],
      "env": {
        "EVERMEMOS_API_KEY": "YOUR_KEY"
      }
    }
  }
}
```

Reference snippet: `docs/mcp-config-snippets/cursor.json`

## 4) Cline Example

```json
{
  "mcpServers": {
    "evermemos": {
      "command": "uvx",
      "args": ["evermemos-mcp@latest"],
      "env": {
        "EVERMEMOS_API_KEY": "YOUR_KEY"
      }
    }
  }
}
```

Reference snippet: `docs/mcp-config-snippets/cline.json`

## 5) Claude Code Example

```json
{
  "mcpServers": {
    "evermemos": {
      "command": "uvx",
      "args": ["evermemos-mcp@latest"],
      "env": {
        "EVERMEMOS_API_KEY": "YOUR_KEY"
      }
    }
  }
}
```

If you need a pinned release, replace `evermemos-mcp@latest` with an explicit version such as `evermemos-mcp@0.4.7`. If running from source, replace with Option B.

Reference snippet: `docs/mcp-config-snippets/claude-code.json`

## 6) Cherry Studio Example

Recommended for published releases:

```json
{
  "mcpServers": {
    "evermemos-mcp": {
      "type": "stdio",
      "command": "uvx",
      "args": [
        "evermemos-mcp@latest"
      ],
      "env": {
        "EVERMEMOS_API_KEY": "YOUR_KEY",
        "EVERMEMOS_USER_ID": "mcp-user"
      },
      "isActive": true
    }
  }
}
```

If you prefer a fixed release, replace `evermemos-mcp@latest` with an explicit version such as `evermemos-mcp@0.4.7`.

If Cherry Studio still launches an older cached build after an upgrade, run:

```bash
uv cache clean evermemos-mcp
```

For local source development, keep using `uv run --directory /ABS/PATH/evermemos-mcp evermemos-mcp`.

### Cherry Studio write-after check example

For a high-value write in Cherry Studio:
1. Call `remember(..., include_status=true, flush=true)`.
2. Confirm the response contains `status_check` and keep the returned `request_id`.
3. If `request_status.lifecycle.state` is still `queued`, do not assume memory loss.
4. Re-run `request_status(request_id=...)` before relying on `recall` as proof of searchable extraction.

## 7) Source Snippet Reference
Use `docs/mcp-config-snippets/from-source.json` when you prefer a local source checkout instead of the published `uvx` package.

## 8) `flush` Boundary Strategy (Recommended)

`flush` is a conversation-boundary signal for `remember` calls. This server does not infer it automatically.

Host-side deterministic policy:
1. Always send `flush` explicitly (`true` or `false`).
2. Use `flush=false` for intermediate turns in one ongoing conversation.
3. Use `flush=true` for final answer, summary, topic switch, app close, or timeout.
4. If uncertain, use `flush=true` as safe fallback.

Recommended agent prompt snippet:

```text
When calling remember:
1) Always pass flush explicitly (never omit).
2) Use flush=false for intermediate turns in the same ongoing conversation.
3) Use flush=true when:
   - providing a final answer/summary,
   - topic switches,
   - user says session is done,
   - app signals conversation close/timeout.
4) If boundary is uncertain, use flush=true as safe fallback.
```

## 8.5) Space Templates (Recommended)

Use these defaults unless you have a strong reason not to:

| Space | Recommended usage |
|-------|-------------------|
| `chat:preferences` | durable identity, names, preferences, communication style |
| `chat:daily` | temporary or rolling chat context |
| `coding:<repo>` | project decisions, bugs, architecture, conventions |
| `study:<topic>` | notes, topic progress, revision context |

Why this matters: it prevents personal preferences from polluting project memory, and keeps project history from polluting general chat memory.

## 9) 30-Second Smoke Check
In your MCP client:
1. `list_spaces` (expect `ok=true`)
2. `remember` with `include_status=true`
   - expect `message_id/request_id/processing_hint/lifecycle`
   - expect `status_check.tool == request_status` and `status_check.checked_now == true`
   - expect `request_status.lifecycle.state` to start as `queued`
3. `recall` in the same space
   - immediate recall can still be `queued`, `provisional`, or `fallback`
   - inspect `lifecycle.state`, plus `results[].stability` for row-level labels
   - `pending_count/pending_hint` means relevant writes are still queued
4. `briefing` in the same space
   - expect `summary`, `highlights[]`, and `lifecycle`
   - `highlights[].stability == fallback` means metadata fallback, not formal extracted memory
5. `fetch_history` with timeline pagination
   - example: `memory_type=event_log`, `limit=20`, `offset=0`
   - use `has_more/next_offset` to continue paging

### Lifecycle quick reference

| State | Meaning |
|-------|---------|
| `queued` | write accepted, formal extraction not confirmed searchable |
| `provisional` | answer comes from `pending_messages` |
| `fallback` | answer comes from mirrored `conversation-meta` |
| `searchable` | answer comes from formal extracted memories |

## Write-After Check Playbook

Recommended path after an important write:
1. Call `remember(..., include_status=true)`.
2. Read `status_check` first, then check `request_status.success` / `request_status.error`.
3. Only after the status check succeeds should you interpret `request_status.lifecycle.state`.
4. If the state is still `queued`, do **not** treat an empty `recall` as memory loss.
5. Use `recall` or `briefing` only to check whether you have provisional/fallback help while waiting.
6. Re-run `request_status(request_id=...)` until upstream confirms a searchable state.

Note: the embedded `remember.request_status` now mirrors the standalone `request_status` tool contract, including `ok` and `request_id`.

## 9.5) Recall vs History vs Forget

- Use `recall` when you want the most relevant answer.
- Use `fetch_history` when you want a timeline, when recall feels unstable, or before/after deletion.
- Treat `forget` as best-effort in current Cloud behavior.

Recommended delete flow:
1. Use `fetch_history(space_id=..., memory_type=...)` to verify the target `memory_id`.
2. Call `forget(memory_ids=[...], space_id=...)`.
3. Re-run `fetch_history` first; use `recall` only as a secondary confirmation.
4. If the target still appears, record it as a Cloud limitation rather than assuming the MCP route failed.

## 10) Common Issues
- `CONFIG_ERROR: EVERMEMOS_API_KEY is required for Cloud API (v0)`
  - add `EVERMEMOS_API_KEY` in MCP server `env`
- `UNKNOWN_TOOL`
  - restart client and verify the active server is `evermemos`
- Remember succeeds but recall is empty
  - Cloud extraction is async and queue time is variable
  - inspect `request_status.success/error` first, then `request_status.lifecycle`, `recall.lifecycle`, and `briefing.lifecycle` instead of assuming a fixed delay
- Cherry Studio still starts an older version after a release
- `uvx` may reuse cached builds; run `uv cache clean evermemos-mcp` or pin an explicit release such as `evermemos-mcp@0.4.7`
- Missing required field errors behind proxy/WAF
  - your network may strip GET request bodies used by upstream `fetch/search`
