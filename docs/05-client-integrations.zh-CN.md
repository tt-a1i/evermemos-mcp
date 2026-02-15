# MCP 客户端接入指南（Claude Code / Cursor / Cline）

[English](05-client-integrations.md) | [简体中文](05-client-integrations.zh-CN.md)

本文给出 `evermemos-mcp` 的可复制接入配置。

现成配置片段目录：`docs/mcp-config-snippets/`

## 1) 前置条件

1. 已安装本项目（或可以从源码运行）
2. 可执行命令可用：`evermemos-mcp`
3. Cloud 模式已设置：`EVERMEMOS_API_KEY`
4. （可选）需要自定义提取模型时，设置 `EVERMEMOS_LLM_CUSTOM_SETTING_JSON`

> 说明：`EVERMEMOS_BASE_URL` 和 `EVERMEMOS_API_VERSION` 默认已内置为 Cloud（`https://api.evermind.ai` + `v0`），通常不需要再配。

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

### 方式 B：从源码启动（未安装全局命令时）

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

在 Cursor 的 MCP 配置里添加：

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

对应片段文件：`docs/mcp-config-snippets/cursor.json`

## 4) Cline 配置示例

在 Cline 的 MCP Servers 配置里添加：

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

对应片段文件：`docs/mcp-config-snippets/cline.json`

## 5) Claude Code 配置示例

Claude Code 支持添加 stdio MCP server。配置字段同样使用：`command + args + env`。

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

如果你是源码方式运行，把 `command/args` 替换成第 2 节的方式 B。

对应片段文件：`docs/mcp-config-snippets/claude-code.json`

## 5.1) 源码启动片段

如果你还没安装全局命令，可直接使用：`docs/mcp-config-snippets/from-source.json`

```json
{
  "mcpServers": {
    "evermemos": {
      "command": "uv",
      "args": ["run", "--directory", "/ABS/PATH/evermemos-mcp", "evermemos-mcp"],
      "env": {
        "EVERMEMOS_API_KEY": "YOUR_KEY"
      }
    }
  }
}
```

## 6) 接入后自检（30 秒）

在客户端里调用：

1. `list_spaces`（应返回 `ok=true`）
2. `remember` 写一条测试内容（建议 `include_status=true`）
   - 应返回 `message_id/request_id/processing_hint`
   - 若开启 `include_status`，应有 `request_status`
3. `recall` 查询同空间（短时间可能空，但可看到 `pending_count`）
   - `retrieve_method` 可选：`keyword|hybrid|vector|rrf|agentic`

## 7) 常见问题

- `CONFIG_ERROR: EVERMEMOS_API_KEY is required for Cloud API (v0)`
  - 原因：Cloud 模式没配 key
  - 处理：在 MCP server 的 `env` 增加 `EVERMEMOS_API_KEY`

- `UNKNOWN_TOOL`
  - 原因：客户端缓存了旧配置或连接到错误 server
  - 处理：重启客户端并确认 server 名称是 `evermemos`

- 记忆写入后立刻检索不到
  - 原因：Cloud 异步提取（正常）
  - 处理：等待 2-5 分钟，或看 `pending_count` 提示

- `remember` 没有返回 `request_status`
  - 原因：未传 `include_status=true`，或本次状态查询失败
  - 处理：开启 `include_status`，或用 `request_id` 做后续状态追踪
