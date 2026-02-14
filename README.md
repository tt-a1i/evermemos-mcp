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

## Core Behavior (Cloud v0)
- 写入是异步队列：`remember` 成功后返回 `request_id`，并不代表立刻可召回
- 检索可见待处理提示：`recall` 会返回 `pending_count/pending_hint`
- `space_id` 是唯一隔离键（格式 `<domain>:<slug>`）
- 默认路由依赖 `list_spaces` + 描述，不做 cwd/git 自动猜测

## Quick Start
- Cloud 默认值已内置：`EVERMEMOS_BASE_URL=https://api.evermind.ai`、`EVERMEMOS_API_VERSION=v0`
- Cloud 需要配置：`EVERMEMOS_API_KEY`
- 启动：`uv run evermemos-mcp` 或 `uv run python -m evermemos_mcp.server`
- 可选：`EVERMEMOS_ENABLE_CONVERSATION_META=true`（默认开启）
- 可选：`EVERMEMOS_LLM_CUSTOM_SETTING_JSON` 用于透传 `llm_custom_setting`

## Tool Contract Notes
- `remember`: 支持 `include_status`（可选），开启后会附带一次 `request_status`
- `remember` 输出包含：`message_id`、`request_id`、`created_at`、`processing_hint`
- `recall`: `retrieve_method` 支持 `keyword|hybrid|vector|rrf|agentic`
- `recall`: 支持 `start_time/end_time`（ISO 8601，若无时区按 UTC 处理），仅对 `episodic_memory` 生效
- `recall`: 支持 `current_time`、`radius`、`include_metadata`
- `recall`: 支持可选 `memory_types` 覆盖默认过滤策略
- `recall/briefing` 返回可追溯引用字段：`memory_type/snippet/timestamp/score`
- `briefing`: 除 `profile/episodic_memory/event_log` 外，也会包含 `foresight` 高亮

## MCP Client Integration
- Claude Code / Cursor / Cline 配置示例见：`docs/05-client-integrations.md`
- 可直接复制的 JSON 片段：`docs/mcp-config-snippets/`
- 演示脚本见：`scripts/demo_preload.py`、`scripts/demo_live_walkthrough.py`

## Development
- 安装开发依赖：`uv sync --group dev`
- Lint：`uv run ruff check`
- Test：`uv run pytest`
- CI 工作流：`.github/workflows/ci.yml`（每次 push / PR 执行 ruff + pytest）

## Design Docs
- Requirements: `docs/01-requirements.md`
- Architecture: `docs/02-architecture.md`
- Demo playbook: `docs/03-demo-playbook.md`
- Submission notes: `docs/04-submission.md`
- Client integrations: `docs/05-client-integrations.md`
- Working plan: `task_plan.md`
