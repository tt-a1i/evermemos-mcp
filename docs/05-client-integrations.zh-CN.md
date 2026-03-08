# MCP 客户端接入指南（Claude Code / Cursor / Cline / Cherry）

[English](05-client-integrations.md) | [简体中文](05-client-integrations.zh-CN.md)

本文提供 `evermemos-mcp` 的可复制接入配置。

配置片段目录：`docs/mcp-config-snippets/`

## 1) 前置条件
1. 本机可用 `uv` / `uvx`，或可直接从源码运行本项目
2. 可执行命令可用（发布版推荐 `uvx`，源码联调使用 `uv`）
3. 已配置 Cloud API Key：`EVERMEMOS_API_KEY`
4. （可选）若需要自定义提取模型，可设置 `EVERMEMOS_LLM_CUSTOM_SETTING_JSON`
5. （可选）可设置 conversation metadata 时区：`EVERMEMOS_DEFAULT_TIMEZONE`（默认 `UTC`）

> 本项目默认内置 Cloud 地址和版本：`EVERMEMOS_BASE_URL=https://api.evermind.ai`、`EVERMEMOS_API_VERSION=v0`。

## 2) 推荐启动方式

### 方式 A：通过 `uvx` 运行已发布版本（推荐）

```json
{
  "command": "uvx",
  "args": ["evermemos-mcp@latest"],
  "env": {
    "EVERMEMOS_API_KEY": "YOUR_KEY"
  }
}
```

### 方式 B：从源码启动

```json
{
  "command": "uv",
  "args": ["run", "--directory", "/ABS/PATH/evermemos-mcp", "evermemos-mcp"],
  "env": {
    "EVERMEMOS_API_KEY": "YOUR_KEY"
  }
}
```

## 3) Cursor 配置示例

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

对应片段：`docs/mcp-config-snippets/cursor.json`

## 4) Cline 配置示例

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

对应片段：`docs/mcp-config-snippets/cline.json`

## 5) Claude Code 配置示例

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

如果你想固定到某个已发布版本，可把 `evermemos-mcp@latest` 改成显式版本，例如 `evermemos-mcp@0.4.7`。若你使用源码启动，请改为“方式 B”。

对应片段：`docs/mcp-config-snippets/claude-code.json`

## 6) Cherry Studio 配置示例

已发布版本推荐这样配置：

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

如果你想固定到某个已发布版本，可把 `evermemos-mcp@latest` 改成显式版本，例如 `evermemos-mcp@0.4.7`。

如果发布后 Cherry Studio 仍启动旧缓存版本，可执行：

```bash
uv cache clean evermemos-mcp
```

如果你是在本地源码联调，才继续使用 `uv run --directory /ABS/PATH/evermemos-mcp evermemos-mcp`。

### Cherry Studio 写后检查示例

如果这是一次高价值写入：
1. 调用 `remember(..., include_status=true, flush=true)`。
2. 确认返回里包含 `status_check`，并保留 `request_id`。
3. 如果 `request_status.lifecycle.state` 仍是 `queued`，不要误判成“没记住”。
4. 在把 `recall` 当作正式提取证明之前，先继续调用 `request_status(request_id=...)`。

## 7) 源码片段
如果你不想走已发布的 `uvx` 包，而是本地源码联调，可直接使用：`docs/mcp-config-snippets/from-source.json`。

## 8) `flush` 边界策略（推荐）

`flush` 是 `remember` 的会话边界信号，本服务不会自动推断。

建议在宿主侧实现确定性规则：
1. 始终显式传 `flush`（`true` 或 `false`）。
2. 同一段持续对话的中间轮次使用 `flush=false`。
3. 收尾答复、总结、话题切换、会话关闭或超时时使用 `flush=true`。
4. 边界不确定时，兜底使用 `flush=true`。

建议给 Agent 的提示词片段：

```text
调用 remember 时：
1) 始终显式传入 flush（不要省略）。
2) 同一段持续会话中的中间轮次使用 flush=false。
3) 在以下场景使用 flush=true：
   - 给出最终答复或总结时
   - 话题切换时
   - 用户表示会话结束时
   - 应用发出会话关闭或超时信号时
4) 如果边界不确定，兜底使用 flush=true。
```

## 8.5) 空间模板（推荐）

除非你有明确理由，否则建议直接按下面用：

| 空间 | 推荐用途 |
|------|----------|
| `chat:preferences` | 长期身份信息、名字、偏好、沟通风格 |
| `chat:daily` | 临时或滚动聊天上下文 |
| `coding:<repo>` | 项目决策、Bug、架构、项目惯例 |
| `study:<topic>` | 笔记、学习进度、复盘上下文 |

这样做的好处是：个人偏好不会污染项目记忆，项目历史也不会反过来污染一般聊天上下文。

## 9) 接入后 30 秒自检
在客户端里依次调用：

1. `list_spaces`（应返回 `ok=true`）
2. `remember`（建议 `include_status=true`）
   - 应返回 `message_id/request_id/processing_hint/lifecycle`
   - 应看到 `status_check.tool == request_status`，并且 `status_check.checked_now == true`
   - 若状态查询成功，应看到 `request_status.lifecycle.state` 初始通常为 `queued`
3. `recall`（同一个 `space_id`）
   - 刚写完可能仍是 `queued`、`provisional` 或 `fallback`
   - 观察 `lifecycle.state`，以及 `results[].stability` 的逐条标记
   - `pending_count/pending_hint` 表示相关写入仍在提取队列里
4. `briefing`（同一个 `space_id`）
   - 应返回 `summary`、`highlights[]` 与 `lifecycle`
   - 若 `highlights[].stability == fallback`，表示当前是 metadata fallback，不是正式提取记忆
5. `fetch_history`（时间线分页）
   - 示例：`memory_type=event_log`、`limit=20`、`offset=0`
   - 通过 `has_more/next_offset` 继续翻页

### 生命周期速查表

| 状态 | 含义 |
|------|------|
| `queued` | 写入已接受，但正式提取结果还没确认可检索 |
| `provisional` | 当前答案来自 `pending_messages` |
| `fallback` | 当前答案来自镜像后的 `conversation-meta` |
| `searchable` | 当前答案来自正式提取后的记忆 |

## 写后检查 Playbook

重要写入后的推荐路径：
1. 调用 `remember(..., include_status=true)`。
2. 先看 `status_check`，再检查 `request_status.success` / `request_status.error`。
3. 只有在状态检查成功后，才去解释 `request_status.lifecycle.state`。
4. 如果状态仍是 `queued`，不要把空的 `recall` 误判成“没记住”。
5. `recall` / `briefing` 主要用来确认当前是否只能拿到 provisional/fallback 帮助。
6. 持续使用 `request_status(request_id=...)`，直到上游确认进入 searchable 状态。

说明：`remember.request_status` 现在与独立 `request_status` 工具保持同构，包含 `ok` 和 `request_id`。

## 9.5) `recall` / `fetch_history` / `forget` 怎么选

- 想找“最相关的一条答案”时，用 `recall`
- 想按时间复盘、搜索不稳定、或删除前后做核验时，用 `fetch_history`
- `forget` 目前应按 Cloud 下的 best-effort 行为理解

推荐删除流程：
1. 先用 `fetch_history(space_id=..., memory_type=...)` 确认目标 `memory_id`。
2. 调用 `forget(memory_ids=[...], space_id=...)`。
3. 优先重新执行 `fetch_history`；`recall` 只作为补充确认。
4. 如果目标仍出现，应先按 Cloud 限制记录，而不是立刻判断 MCP 路由失败。

## 10) 常见问题
- `CONFIG_ERROR: EVERMEMOS_API_KEY is required for Cloud API (v0)`
  - 原因：未配置 API Key
  - 处理：在 MCP server 的 `env` 增加 `EVERMEMOS_API_KEY`

- `UNKNOWN_TOOL`
  - 原因：客户端连接了旧 server 或缓存未刷新
  - 处理：重启客户端并确认启用的是 `evermemos`

- `remember` 成功但 `recall` 为空
  - 原因：Cloud 提取是异步，队列时长不固定
  - 处理：先检查 `request_status.success/error`，再看 `request_status.lifecycle`、`recall.lifecycle`、`briefing.lifecycle`，不要假设固定等待时间

- Cherry Studio 发布后仍启动旧版本
  - 原因：`uvx` 可能复用本地缓存
- 处理：执行 `uv cache clean evermemos-mcp`，或直接固定显式版本，例如 `evermemos-mcp@0.4.7`

- 在代理/WAF 环境出现缺字段错误
  - 原因：中间件可能剥离了 GET 请求体（上游 fetch/search 使用 `GET + JSON body`）
  - 处理：更换网络、配置白名单或绕过相关代理策略
