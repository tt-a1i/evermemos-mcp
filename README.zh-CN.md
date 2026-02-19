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

## 为什么需要 `space::catalog`
- EverMemOS 的 metadata 接口都要求传具体 `group_id`（`get/set/update`），没有全局会话列表接口
- 因此 `list_spaces` 需要通过保留分组 `space::catalog` 维护一份可恢复的空间索引
- 空间注册采用 best-effort 双写：catalog 文本条目 + `conversation-meta` 同步
- 恢复时先读 catalog 条目，再用 `conversation-meta` 做描述补全

## 快速开始
- Cloud 默认值已内置：`EVERMEMOS_BASE_URL=https://api.evermind.ai`、`EVERMEMOS_API_VERSION=v0`
- Cloud 需要配置：`EVERMEMOS_API_KEY`
- 启动：`uv run evermemos-mcp` 或 `uv run python -m evermemos_mcp.server`
- 可选：`EVERMEMOS_ENABLE_CONVERSATION_META=true`（默认开启）
- 可选：`EVERMEMOS_LLM_CUSTOM_SETTING_JSON` 用于透传 `llm_custom_setting`
- 可选：`EVERMEMOS_USER_DETAILS_JSON` 用于透传 conversation `user_details`

## 安装方式
- 克隆仓库：`git clone https://github.com/tt-a1i/evermemos-mcp.git`
- 进入目录：`cd evermemos-mcp`
- 创建环境变量文件：`cp .env.example .env`，并配置 `EVERMEMOS_API_KEY`
- 推荐源码运行：`uv run --directory . evermemos-mcp`
- 可选全局安装：`uv tool install --from . evermemos-mcp`

## 通用 MCP 配置（stdio）
支持 `command + args + env` 的 MCP 客户端都可以直接使用下面模板：

```json
{
  "mcpServers": {
    "evermemos-mcp": {
      "type": "stdio",
      "command": "uv",
      "args": [
        "run",
        "--directory",
        "/你的绝对路径/evermemos-mcp",
        "evermemos-mcp"
      ],
      "env": {
        "EVERMEMOS_API_KEY": "你的KEY",
        "EVERMEMOS_USER_ID": "mcp-user"
      }
    }
  }
}
```

若已全局安装，可改为：`"command": "evermemos-mcp", "args": []`。

## Tool 契约说明
- `list_spaces`: Cloud 模式下 `memory_count` 为近似值（异步提取）
- `remember`: 支持 `include_status`（可选），开启后会附带一次 `request_status`
- `remember` 输出包含：`message_id`、`request_id`、`created_at`、`processing_hint`
- `remember`: 还会返回 `memory_count_hint`，说明 Cloud 模式下计数是近似值
- `remember`: 会显式透传 `flush`（`true/false`），避免依赖上游默认值
- `remember`: 默认 `flush=false`，仅在明确会话边界时使用 `flush=true`
- `recall`: `retrieve_method` 支持 `keyword|hybrid|vector|rrf|agentic|auto`
- `recall`: 默认 `top_k=10`，可接受范围为 `-1` 或 `1-100`（`-1` 表示返回全部，仍受上游上限约束）
- `recall`: 支持 `start_time/end_time`（ISO 8601，若无时区按 UTC 处理），仅对 `episodic_memory` 生效
- `recall`: 支持 `current_time`、`radius`、`include_metadata`
- `recall`: 支持可选 `memory_types` 覆盖默认过滤策略
- `recall`: 对 `hybrid|rrf|agentic`，默认会收敛到 `profile+episodic_memory`，且自定义值也仅允许这两类
- `recall`: `auto` 会并行执行 `hybrid + keyword` 并按 `memory_id` 去重合并，分支失败会以提示形式返回
- `recall/briefing` 返回可追溯引用字段：`memory_type/snippet/timestamp/score`
- `briefing`: 除 `profile/episodic_memory/event_log` 外，也会包含 `foresight` 高亮
- `briefing`: 支持 `start_time/end_time` 时间过滤（ISO 8601，若无时区按 UTC 处理，仅对 `episodic_memory/event_log` 生效，不作用于 `profile/foresight`）
- Cloud `fetch/search` 按官方 API 使用 `GET + JSON body`；若在代理/WAF 后出现缺字段错误，请检查是否被中间件剥离请求体
- 状态查询优先使用 `/status/request`，失败时回退到 `/memories/status`

### `flush` 边界规则
- `flush` 由调用方（MCP 客户端/Agent）控制，本服务不做自动推断
- 建议始终显式传 `flush`，不要依赖上游默认值
- 同一段持续多轮对话的中间轮次用 `flush=false`
- 收尾/总结/话题切换/会话结束或超时时用 `flush=true`
- 若无法判断边界，默认使用 `flush=true` 更稳妥
- 可直接复用的提示词和调用约束见：`docs/05-client-integrations.zh-CN.md`

## MCP 客户端接入
- Claude Code / Cursor / Cline / Cherry 配置见：`docs/05-client-integrations.zh-CN.md`
- 可直接复制的 JSON 片段：`docs/mcp-config-snippets/`
- 演示脚本见：`scripts/demo_preload.py`、`scripts/demo_live_walkthrough.py`

## 开发与验证
- 安装开发依赖：`uv sync --group dev`
- Lint：`uv run ruff check`
- Test：`uv run pytest`
- 可选集成测试：`EVERMEMOS_RUN_INTEGRATION_TESTS=true uv run pytest -m integration`
- CI 工作流：`.github/workflows/ci.yml`（每次 push / PR 执行 ruff + pytest）

## 文档索引
- 需求文档：`docs/01-requirements.zh-CN.md`
- 架构设计：`docs/02-architecture.zh-CN.md`
- 演示手册：`docs/03-demo-playbook.zh-CN.md`
- 提交清单：`docs/04-submission.zh-CN.md`
- 客户端接入：`docs/05-client-integrations.zh-CN.md`
- 任务计划：`task_plan.zh-CN.md`
