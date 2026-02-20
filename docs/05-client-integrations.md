# MCP Client Integration Guide (Claude Code / Cursor / Cline / Cherry)

[English](05-client-integrations.md) | [Chinese](05-client-integrations.zh-CN.md)

This document provides copy-paste MCP server configuration for `evermemos-mcp`.

Config snippet directory: `docs/mcp-config-snippets/`

## 1) Prerequisites
1. Project installed or runnable from source
2. Executable command available (`evermemos-mcp` or `uv`)
3. Cloud key configured: `EVERMEMOS_API_KEY`
4. Optional custom extraction config: `EVERMEMOS_LLM_CUSTOM_SETTING_JSON`
5. Optional conversation metadata timezone: `EVERMEMOS_DEFAULT_TIMEZONE` (default `UTC`)

> `EVERMEMOS_BASE_URL` and `EVERMEMOS_API_VERSION` already default to Cloud (`https://api.evermind.ai` + `v0`) in this project.

## 2) Recommended Startup

### Option A: Installed command (recommended)

```json
{
  "command": "evermemos-mcp",
  "args": [],
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
      "command": "evermemos-mcp",
      "args": [],
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
      "command": "evermemos-mcp",
      "args": [],
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
      "command": "evermemos-mcp",
      "args": [],
      "env": {
        "EVERMEMOS_API_KEY": "YOUR_KEY"
      }
    }
  }
}
```

If running from source, replace with Option B.

Reference snippet: `docs/mcp-config-snippets/claude-code.json`

## 6) Cherry Studio Example

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
      },
      "isActive": true
    }
  }
}
```

## 7) Source Snippet Reference
Use `docs/mcp-config-snippets/from-source.json` when global command install is not available.

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

## 9) 30-Second Smoke Check
In your MCP client:
1. `list_spaces` (expect `ok=true`)
2. `remember` with `include_status=true`
   - expect `message_id/request_id/processing_hint`
   - expect `request_status` when status check succeeds
3. `recall` in the same space
   - immediate recall can be empty due to async extraction
   - look for `pending_count` and `pending_hint`

## 10) Common Issues
- `CONFIG_ERROR: EVERMEMOS_API_KEY is required for Cloud API (v0)`
  - add `EVERMEMOS_API_KEY` in MCP server `env`
- `UNKNOWN_TOOL`
  - restart client and verify the active server is `evermemos`
- Remember succeeds but recall is empty
  - Cloud extraction is async (wait 2-5 minutes)
- Missing required field errors behind proxy/WAF
  - your network may strip GET request bodies used by upstream `fetch/search`
