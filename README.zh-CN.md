# evermemos-mcp

[English](README.md) | [简体中文](README.zh-CN.md)

基于 EverMemOS 的通用 MCP 长期记忆层。

## 当前定位
- 适用于 MCP 兼容客户端（coding/chat/study 等场景）
- 使用 `space_id` 作为一级隔离键
- Cloud-only 策略（不做本地持久化）

## V1 工具集
- `list_spaces`
- `remember`
- `recall`
- `briefing`
- `forget`

## 核心行为（Cloud v0）
- 写入是异步队列：`remember` 成功后返回 `request_id`，并不代表立刻可召回
- 检索可见待处理提示：`recall` 会返回 `pending_count/pending_hint`
- `space_id` 是唯一隔离键（格式 `<domain>:<slug>`）
- 默认路由依赖 `list_spaces` + 描述，不做 cwd/git 自动猜测

## 快速开始
- Cloud 默认值已内置：`EVERMEMOS_BASE_URL=https://api.evermind.ai`、`EVERMEMOS_API_VERSION=v0`
- Cloud 需要配置：`EVERMEMOS_API_KEY`
- 启动：`uv run evermemos-mcp` 或 `uv run python -m evermemos_mcp.server`
- 可选：`EVERMEMOS_ENABLE_CONVERSATION_META=true`（默认开启）
- 可选：`EVERMEMOS_LLM_CUSTOM_SETTING_JSON` 用于透传 `llm_custom_setting`

## Tool 契约说明
- `remember`: 支持 `include_status`（可选），开启后会附带一次 `request_status`
- `remember` 输出包含：`message_id`、`request_id`、`created_at`、`processing_hint`
- `recall`: `retrieve_method` 支持 `keyword|hybrid|vector|rrf|agentic`
- `recall`: 支持 `start_time/end_time`（ISO 8601，若无时区按 UTC 处理），仅对 `episodic_memory` 生效
- `recall`: 支持 `current_time`、`radius`、`include_metadata`
- `recall`: 支持可选 `memory_types` 覆盖默认过滤策略
- `recall/briefing` 返回可追溯引用字段：`memory_type/snippet/timestamp/score`
- `briefing`: 除 `profile/episodic_memory/event_log` 外，也会包含 `foresight` 高亮
- `briefing`: 支持 `start_time/end_time` 时间过滤（ISO 8601，若无时区按 UTC 处理，仅对 `episodic_memory/event_log` 生效）
- Cloud `fetch/search` 按官方 API 使用 `GET + JSON body`；若在代理/WAF 后出现缺字段错误，请检查是否被中间件剥离请求体

## MCP 客户端接入
- Claude Code / Cursor / Cline / Cherry 配置见：`docs/05-client-integrations.zh-CN.md`
- 可直接复制的 JSON 片段：`docs/mcp-config-snippets/`
- 演示脚本见：`scripts/demo_preload.py`、`scripts/demo_live_walkthrough.py`

## 开发与验证
- 安装开发依赖：`uv sync --group dev`
- Lint：`uv run ruff check`
- Test：`uv run pytest`
- CI 工作流：`.github/workflows/ci.yml`（每次 push / PR 执行 ruff + pytest）

## 文档索引
- 需求文档：`docs/01-requirements.zh-CN.md`
- 架构设计：`docs/02-architecture.zh-CN.md`
- 演示手册：`docs/03-demo-playbook.zh-CN.md`
- 提交清单：`docs/04-submission.zh-CN.md`
- 客户端接入：`docs/05-client-integrations.zh-CN.md`
- 任务计划：`task_plan.zh-CN.md`
