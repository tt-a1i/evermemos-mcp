# MCP 客户端接入指南（Claude Code / Cursor / Cline / Cherry）

[English](05-client-integrations.md) | [简体中文](05-client-integrations.zh-CN.md)

本文提供 `evermemos-mcp` 的可复制接入配置。

配置片段目录：`docs/mcp-config-snippets/`

## 1) 前置条件
1. 已安装本项目，或可从源码运行
2. 可执行命令可用（`evermemos-mcp` 或 `uv`）
3. 已配置 Cloud API Key：`EVERMEMOS_API_KEY`
4. （可选）若需要自定义提取模型，可设置 `EVERMEMOS_LLM_CUSTOM_SETTING_JSON`
5. （可选）可设置 conversation metadata 时区：`EVERMEMOS_DEFAULT_TIMEZONE`（默认 `UTC`）

> 本项目默认内置 Cloud 地址和版本：`EVERMEMOS_BASE_URL=https://api.evermind.ai`、`EVERMEMOS_API_VERSION=v0`。

## 2) 推荐启动方式

### 方式 A：已安装命令（推荐）

```json
{
  "command": "evermemos-mcp",
  "args": [],
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
      "command": "evermemos-mcp",
      "args": [],
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
      "command": "evermemos-mcp",
      "args": [],
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
      "command": "evermemos-mcp",
      "args": [],
      "env": {
        "EVERMEMOS_API_KEY": "YOUR_KEY"
      }
    }
  }
}
```

若你使用源码启动，请改为“方式 B”。

对应片段：`docs/mcp-config-snippets/claude-code.json`

## 6) Cherry Studio 配置示例

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

## 7) 源码片段
如果未安装全局命令，可直接使用：`docs/mcp-config-snippets/from-source.json`。

## 8) `flush` 边界策略（推荐）

`flush` 是 `remember` 的会话边界信号，本服务不会自动推断。

建议在宿主侧实现确定性规则：
1. 始终显式传 `flush`（`true` 或 `false`）。
2. 同一段持续对话的中间轮次使用 `flush=false`。
3. 收尾答复、总结、话题切换、会话关闭或超时时使用 `flush=true`。
4. 边界不确定时，兜底使用 `flush=true`。

建议给 Agent 的提示词片段：

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

## 9) 接入后 30 秒自检
在客户端里依次调用：

1. `list_spaces`（应返回 `ok=true`）
2. `remember`（建议 `include_status=true`）
   - 应返回 `message_id/request_id/processing_hint`
   - 若状态查询成功，应返回 `request_status`
3. `recall`（同一个 `space_id`）
   - 刚写完可能为空（Cloud 异步提取）
   - 可观察 `pending_count/pending_hint`

## 10) 常见问题
- `CONFIG_ERROR: EVERMEMOS_API_KEY is required for Cloud API (v0)`
  - 原因：未配置 API Key
  - 处理：在 MCP server 的 `env` 增加 `EVERMEMOS_API_KEY`

- `UNKNOWN_TOOL`
  - 原因：客户端连接了旧 server 或缓存未刷新
  - 处理：重启客户端并确认启用的是 `evermemos`

- `remember` 成功但 `recall` 为空
  - 原因：Cloud 提取是异步
  - 处理：等待 2-5 分钟后重试

- 在代理/WAF 环境出现缺字段错误
  - 原因：中间件可能剥离了 GET 请求体（上游 fetch/search 使用 `GET + JSON body`）
  - 处理：更换网络、配置白名单或绕过相关代理策略
