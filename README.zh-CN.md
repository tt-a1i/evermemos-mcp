# evermemos-mcp

[English](README.md) | [简体中文](README.zh-CN.md)

**基于 [EverMemOS](https://evermind.ai/) 的通用 AI 长期记忆层，通过 MCP 协议为任意 AI 编程助手赋予跨会话记忆能力。**

> 参赛项目：[Memory Genesis Competition 2026](https://luma.com/n88icl03) — Track 2: Platform Plugins

evermemos-mcp 是一个 MCP（Model Context Protocol）服务器，可以让 Claude Code、Cursor、Cline、Cherry Studio 等任意兼容客户端拥有持久化的跨会话记忆。它填补了 AI 对话"无状态"与真实工作流"需要上下文"之间的鸿沟。

## 为什么需要它

AI 编程助手在会话之间会遗忘一切。你解释了架构决策、个人偏好、项目上下文——下一次对话，全部归零。evermemos-mcp 通过 **记忆 → 推理 → 行动** 闭环解决这个问题：

1. **Remember（记住）** — 工作中随时存储决策、偏好和上下文
2. **Recall（回忆）** — 通过混合检索（关键词 + 向量 + 语义）找回相关记忆
3. **Briefing（简报）** — 新会话开始时一键恢复完整上下文

所有记忆按 **空间（space）** 隔离（如 `coding:my-app`、`study:ml-notes`、`chat:daily`），不同项目和工作流互不干扰。

## 演示

最终演示视频会在最后一次录制完成后补上。

当前可直接查看的提交证据：
- 主 benchmark 汇总：[`artifacts/competition/2026-02-26-formal-real-auto-all-v3/benchmark_summary.json`](artifacts/competition/2026-02-26-formal-real-auto-all-v3/benchmark_summary.json)
- 人类可读 benchmark 报告：[`artifacts/competition/2026-02-26-formal-real-auto-all-v3/benchmark_report.md`](artifacts/competition/2026-02-26-formal-real-auto-all-v3/benchmark_report.md)
- Evidence release（含 `runs.jsonl`）：[`competition-evidence-2026-02-26`](https://github.com/tt-a1i/evermemos-mcp/releases/tag/competition-evidence-2026-02-26)
- 最新 lifecycle appendix：[`artifacts/competition/2026-03-07-lifecycle-appendix-dec0612e/appendix_notes.md`](artifacts/competition/2026-03-07-lifecycle-appendix-dec0612e/appendix_notes.md)（`remember/searchable/isolation` 已通过；`forget` 仍属于当前 Cloud 限制）

## 功能一览

| 工具 | 说明 |
|------|------|
| `list_spaces` | 发现可用的记忆空间 |
| `remember` | 将信息存入长期记忆（异步提取） |
| `request_status` | 查询某次 `remember` 写入当前是否仍在排队，或已被上游标记为完成 |
| `recall` | 搜索记忆，支持 6 种检索策略，并显式标注结果是 `searchable`、`provisional` 还是 `fallback` |
| `briefing` | 获取结构化上下文简报：用户画像 + 情景记忆 + 关键事实 + 前瞻预测，必要时会显式标记 fallback |
| `forget` | 按 ID 发起定向删除（当前 Cloud 行为可能有差异） |
| `fetch_history` | 按类型分页浏览记忆时间线 |

### 核心特性

- **空间隔离** — `space_id`（`<domain>:<slug>` 格式）确保记忆按项目/主题分离
- **多空间检索** — 单次 `recall` 可查询最多 10 个空间，自动标注来源
- **可追溯引用** — 每条结果包含 `memory_type`、`snippet`、`timestamp`、`score` 及可选 `source_message_id`
- **多用户支持** — 可选 `user_id` 过滤，适用于共享空间场景
- **会话元数据同步** — 自动与 EverMemOS Cloud 的 `conversation-meta` 集成
- **异步身份兜底** — 聊天身份/偏好会以 best-effort 方式轻量镜像到 `conversation-meta`，并在提取型搜索结果不可用时以显式 fallback 形式返回
- **统一生命周期语义** — `remember`、`request_status`、`recall`、`briefing` 都会返回兼容的 `lifecycle` 视图，让客户端可以组合区分 `queued`、`provisional`、`fallback`、`searchable`
- **健壮的错误处理** — 429/5xx 自动退避重试、GET body 代理兼容回退、结构化错误码

## 快速开始

从 [EverMemOS Cloud](https://evermind.ai/) 获取 API Key。

### 方式 A：从 PyPI 安装（推荐）

无需克隆仓库，直接在 MCP 客户端配置中添加：

```json
{
  "mcpServers": {
    "evermemos-mcp": {
      "type": "stdio",
      "command": "uvx",
      "args": ["evermemos-mcp@latest"],
      "env": {
        "EVERMEMOS_API_KEY": "你的KEY",
        "EVERMEMOS_USER_ID": "mcp-user"
      }
    }
  }
}
```

或直接在命令行运行：

```bash
uvx evermemos-mcp@latest
```

如果发布后客户端仍启动旧缓存版本，可执行：

```bash
uv cache clean evermemos-mcp
```

### 方式 B：从源码安装

```bash
git clone https://github.com/tt-a1i/evermemos-mcp.git
cd evermemos-mcp
cp .env.example .env
# 编辑 .env，填入你的 EVERMEMOS_API_KEY
uv run evermemos-mcp
```

源码安装的 MCP 客户端配置：

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

各客户端详细配置指南（Claude Code、Cursor、Cline、Cherry Studio）见 [`docs/05-client-integrations.zh-CN.md`](docs/05-client-integrations.zh-CN.md)。

## 架构

```
MCP 客户端（Claude Code / Cursor / Cline / Cherry Studio）
        │
        │  MCP stdio
        ▼
┌─────────────────────────────┐
│     evermemos-mcp 服务器     │
│  ┌───────────────────────┐  │
│  │    7 个工具处理器       │  │
│  └──────────┬────────────┘  │
│  ┌──────────▼────────────┐  │
│  │     记忆服务层         │  │  remember / request_status / recall / briefing / forget / fetch_history
│  └──────────┬────────────┘  │
│  ┌──────────▼────────────┐  │
│  │   空间目录服务         │  │  空间注册、元数据同步、跨会话恢复
│  └──────────┬────────────┘  │
│  ┌──────────▼────────────┐  │
│  │  EverMemOS HTTP 客户端 │  │  认证、重试、限流退避、错误规范化
│  └──────────┬────────────┘  │
└─────────────┼───────────────┘
              │  HTTPS
              ▼
       EverMemOS Cloud API
```

- **Cloud 优先** — 所有记忆存储在 EverMemOS Cloud，无本地持久化，不会丢失状态
- **进程内缓存** — 空间目录在内存中缓存，启动时从 Cloud 恢复
- **异步提取** — `remember` 将内容加入队列，由 AI 提取后变为可检索的记忆

## 记忆生命周期状态

| 状态 | 含义 | 常见体现位置 |
|------|------|--------------|
| `queued` | 写入已被接受，但正式提取结果还没有确认可检索 | `remember.lifecycle`、`request_status.lifecycle`、`recall.pending_count` |
| `provisional` | 当前答案来自 `pending_messages`，说明还在排队阶段 | `recall.results[].stability == provisional` |
| `fallback` | 当前答案来自镜像后的 `conversation-meta`，不是正式提取记忆 | `recall.results[].stability == fallback`、`briefing.highlights[].stability == fallback` |
| `searchable` | 当前答案来自正式提取后的记忆结果 | `recall.results[].stability == searchable`、`briefing.highlights[].stability == searchable` |

如果工具能用 `provisional` 或 `fallback` 给出答案，并不代表正式提取已经完成。

## 空间模板

请按“使用目的”来分空间，而不是只把它当参数格式：

| 模板 | 适合存什么 |
|------|------------|
| `chat:preferences` | 长期个人偏好、名字、称呼、语气、UI 喜好 |
| `chat:daily` | 持续聊天上下文，不应混入项目记忆 |
| `coding:<repo>` | 架构决策、项目惯例、Bug 根因、项目上下文 |
| `study:<topic>` | 学习笔记、主题进度、复盘上下文 |

为什么要分空间？因为“我是谁”“这个项目怎么做”“我最近在学什么”本来就是三类不同记忆，不应该互相覆盖。

## 工具怎么选

| 目标 | 主工具 | 原因 |
|------|--------|------|
| 开始一个新会话 | `briefing` | 一次调用就能恢复整体上下文 |
| 找最相关的旧信息 | `recall` | 适合按相关性找重点 |
| 按时间回看发生过什么 | `fetch_history` | 做时间线复盘时，比 relevance 排序更可靠 |
| 删除前后做核验 | `fetch_history` | 删除核验更适合先看稳定时间线 |

如果 `recall` 看起来不稳定、太挑结果，先切到 `fetch_history`，不要盲目重复同一个搜索。

## Forget 安全说明

`forget` 目前应理解为 Cloud 下的 best-effort 操作，不是“立刻、稳定、必然删除”的强承诺。

推荐删除流程：
1. 先用 `fetch_history` 或 `recall` 确认目标 `memory_id`。
2. 调用 `forget(memory_ids=[...], space_id=...)`。
3. 优先用 `fetch_history` 复查，再按需用 `recall` 做补充确认。
4. 如果目标仍出现，应先按当前 Cloud 限制理解，而不是立刻怀疑 MCP 路由错误。

## 使用场景

### 编程：持久化架构上下文
```
你：记住我们选择 PostgreSQL 而非 MongoDB，因为数据高度关联
    [space_id: coding:my-saas]

—— 第二天，新会话 ——

你：我们选了什么数据库？为什么？
    → recall 找到："选择 PostgreSQL 而非 MongoDB — 数据模型高度关联"
```

### 学习：跨会话学习笔记
```
你：记住 bias-variance tradeoff — 高 bias = 欠拟合，高 variance = 过拟合
    [space_id: study:ml-notes]

—— 之后 ——

你：给我 study:ml-notes 的简报
    → 返回：用户画像（技术技能）、近期情景、关键事实、前瞻预测
```

### 聊天：个人偏好
```
你：记住我偏好暗色主题、vim 快捷键、简洁回复风格
    [space_id: chat:preferences]

—— 任意后续会话 ——

你：回忆我的 UI 偏好
    → "偏好暗色主题、vim 快捷键、简洁回复风格"
```

## 配置项

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `EVERMEMOS_API_KEY` | *（必填）* | EverMemOS Cloud API Key |
| `EVERMEMOS_USER_ID` | `mcp-user` | 默认用户身份 |
| `EVERMEMOS_BASE_URL` | `https://api.evermind.ai` | API 地址 |
| `EVERMEMOS_API_VERSION` | `v0` | API 版本 |
| `EVERMEMOS_ENABLE_CONVERSATION_META` | `true` | 是否同步会话元数据 |
| `EVERMEMOS_DEFAULT_TIMEZONE` | `UTC` | 元数据时区 |
| `EVERMEMOS_DEFAULT_SPACE` | *（自动）* | 默认 space_id。未设置时从 git remote 自动推断为 `coding:<仓库名>` |
| `EVERMEMOS_LLM_CUSTOM_SETTING_JSON` | — | 自定义 LLM 提取设置 |
| `EVERMEMOS_USER_DETAILS_JSON` | — | 会话用户详情 |

### Space 自动推断

当 `remember` 或 `recall` 未指定 `space_id` 时，服务器自动推断默认值：
1. `EVERMEMOS_DEFAULT_SPACE` 环境变量（如已设置）
2. 从 git remote origin URL 推断 → `coding:<仓库名>`（如 `coding:my-saas`）

这意味着在 git 项目目录中，你可以直接调用 `remember` 而无需指定 space——记忆会自动路由到正确的空间。

## `flush` 边界规则

`flush` 控制 EverMemOS 何时触发记忆提取：

| 场景 | `flush` |
|------|---------|
| 对话进行中，还有后续消息 | `false` |
| 会话结束 / 话题切换 / 总结 | `true` |
| 不确定 | `true`（更稳妥） |

## 开发

```bash
uv sync --group dev       # 安装开发依赖
uv run ruff check         # 代码检查
uv run pytest             # 单元测试
EVERMEMOS_RUN_INTEGRATION_TESTS=true uv run pytest -m integration  # 集成测试
```

CI 在每次 push 和 PR 时自动运行，配置见 [`.github/workflows/ci.yml`](.github/workflows/ci.yml)。

## 文档索引

| 文档 | 说明 |
|------|------|
| [`docs/01-requirements.zh-CN.md`](docs/01-requirements.zh-CN.md) | 需求文档 |
| [`docs/02-architecture.zh-CN.md`](docs/02-architecture.zh-CN.md) | 架构设计 |
| [`docs/03-demo-playbook.zh-CN.md`](docs/03-demo-playbook.zh-CN.md) | 演示手册 |
| [`docs/04-submission.zh-CN.md`](docs/04-submission.zh-CN.md) | 提交清单 |
| [`docs/05-client-integrations.zh-CN.md`](docs/05-client-integrations.zh-CN.md) | 客户端接入指南 |
| [`docs/06-benchmark.md`](docs/06-benchmark.md) | Benchmark 协议与门禁 |
| [`docs/07-release-checklist.md`](docs/07-release-checklist.md) | 发布前核对清单 |
| [`docs/competition/benchmark_deep_dive.md`](docs/competition/benchmark_deep_dive.md) | 主证据深度说明 |
| [`docs/auto-memory-prompt.zh-CN.md`](docs/auto-memory-prompt.zh-CN.md) | 自动记忆 Prompt 模板（CLAUDE.md / Cursor / Cline） |
| [`CHANGELOG.md`](CHANGELOG.md) | 版本历史 |

## License

见 [LICENSE](LICENSE)。
