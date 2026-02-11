# evermemos-mcp

Universal MCP memory layer powered by EverMemOS.

## Current Positioning
- Works with MCP-compatible clients (coding/chat/study scenarios)
- Uses `space_id` as the primary isolation key
- Cloud-only data strategy (no local persistence)

## V1 Tool Set
- `list_spaces`
- `remember`
- `recall`
- `briefing`
- `forget`

## Quick Start
- Cloud 默认值已内置：`EVERMEMOS_BASE_URL=https://api.evermind.ai`、`EVERMEMOS_API_VERSION=v0`
- Cloud 需要配置：`EVERMEMOS_API_KEY`
- 启动：`uv run evermemos-mcp` 或 `uv run python -m evermemos_mcp.server`

## MCP Client Integration
- Claude Code / Cursor / Cline 配置示例见：`docs/05-client-integrations.md`
- 演示脚本见：`scripts/demo_preload.py`、`scripts/demo_live_walkthrough.py`

## Design Docs
- Requirements: `docs/01-requirements.md`
- Architecture: `docs/02-architecture.md`
- Demo playbook: `docs/03-demo-playbook.md`
- Submission notes: `docs/04-submission.md`
- Client integrations: `docs/05-client-integrations.md`
- Working plan: `task_plan.md`
