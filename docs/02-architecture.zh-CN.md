# evermemos-mcp 技术设计（Phase 2 / V1）

[English](02-architecture.md) | [简体中文](02-architecture.zh-CN.md)

## 1) 设计目标
- 作为通用 MCP 记忆层，服务多种 AI 客户端（coding/chat/study）
- 在 V1 内保证：可用、可隔离、可追溯、可删除
- 对 EverMemOS 保持薄封装，避免过重二次系统

## 2) 系统边界

```text
MCP Client (Claude/Cursor/Cherry...)
        |
        | MCP tools
        v
evermemos-mcp server
  - tool handlers
  - space router
  - space catalog service
  - memory service
  - evermemos api client
        |
        | HTTP
        v
EverMemOS API
```

## 3) 核心模块

### 3.1 `server`（MCP 入口）
- 注册 7 个 tools：`list_spaces` / `remember` / `request_status` / `recall` / `briefing` / `forget` / `fetch_history`
- 做输入校验、错误映射、统一响应格式

### 3.2 `space_router`（空间路由）
- 只做路由，不做目录/仓库猜测。
- 路由优先级：
  1. 用户或上层 agent 显式给出的 `space_id`
  2. `list_spaces` 结果 + 用户 query 的语义匹配
- 低置信度场景返回候选列表，要求先确认再写入。

### 3.3 `space_catalog_service`（空间目录）
- 提供 `list_spaces` 所需的空间元数据：`space_id`, `description`, `memory_count`, `last_used_at`。
- 元数据存储在 EverMemOS（Cloud-only），不落本地文件。
- 当前实现：
  1. 使用保留空间 `space::catalog` 做空间枚举（兼容历史数据）
  2. 同步写入 `conversation-meta`（description/scene/tags/llm_custom_setting）
  3. recovery 后用 `conversation-meta` 反查并覆盖描述，减少正则解析依赖

### 3.4 `memory_service`（业务编排）
- 将通用语义映射到 EverMemOS API
- 负责来源引用组装（时间 + 片段 + 类型 + score）
- 负责 V1 的安全删除策略（仅按明确 id 删除）

### 3.5 `evermemos_client`（HTTP 适配）
- Cloud 优先：封装 `/api/v0/memories` 与 `/api/v0/memories/search`
- 封装 `/api/v0/status/request`，用于查询异步写入状态
- 状态查询使用 `/api/v0/status/request`（Cloud v0 标准路径）
- 本地兼容：可切换到 `/api/v1/*`（通过配置）
- 处理鉴权、超时、重试（含 429 退避）和错误信息提炼
- 注意：官方 `fetch/search` 契约是 `GET + JSON body`，在部分代理/WAF 环境可能被剥离请求体

## 4) 数据与隔离模型

### 4.1 Cloud-only 数据策略
- 记忆正文存 EverMemOS。
- 空间元数据也存 EverMemOS。
- MCP 服务端不做本地持久化（可有进程内缓存，但不落盘）。

### 4.2 `space_id` 原则
- `space_id` 是一级隔离键，避免不同场景记忆串味
- coding/chat/study 只是 domain，不影响统一工具接口

### 4.3 EverMemOS 映射（V1）
- 推荐映射：`group_id = "space::<space_id>"`
- `user_id` 使用固定或可配置值（如 `mcp-user`）
- 所有写入/检索/删除都带相同 `group_id`，实现空间隔离

### 4.4 示例
- `coding:my-app` -> `group_id=space::coding:my-app`
- `chat:daily` -> `group_id=space::chat:daily`
- `study:ml` -> `group_id=space::study:ml`

## 5) Tool 契约（V1）

### 5.1 `list_spaces`
- 输入：
  - `query` (optional)
  - `limit` (optional, default: 20)
- 行为：返回可路由空间列表（支持 query 过滤）
- 输出：
  - `ok`
  - `spaces[]`（每项包含 `space_id`, `description`, `memory_count`, `last_used_at`）

### 5.2 `remember`
- 输入：
  - `content` (required)
  - `space_id` (required)
  - `description` (optional, 创建新 space 时建议提供)
  - `sender` (optional, default: `user`)
  - `user_id` / `role` (optional)
  - `flush` (optional, default: false)
  - `include_status` (optional, default: false)
- 行为：写入一条消息并触发 EverMemOS 记忆提取
- 输出：
  - `ok`
  - `space_id`
  - `message_id`（写入请求使用的消息 ID）
  - `request_id`
  - `created_at`
  - `processing_hint`（如 "memory extraction may be async"）
  - `lifecycle`（包含 `state`、`state_counts`、`searchable`、`message`）
  - `request_status`（仅 `include_status=true` 时返回）

### 5.3 `request_status`
- 输入：`request_id` (required)
- 行为：在 `remember` 之后查询上游异步写入状态
- 输出：`ok`、`request_id`、`success`、`found`、可选 `error`、`lifecycle`
- 使用说明：先看 `success/error`，再解释 `lifecycle.state`

### 5.4 `recall`
- 输入：
  - `query` (required)
  - `space_id` (optional，单空间检索)
  - `space_ids` (optional，多空间检索，去重后最多 10 个；可与 `space_id` 同时传)
  - `top_k` (optional, default: 10, 范围为 -1 或 1-100；`-1` 表示服务层不截断，并以 `top_k=100` 请求上游)
  - `retrieve_method` (optional, default: `hybrid`)
    - 可选值：`keyword|hybrid|vector|rrf|agentic|auto`
  - `memory_types` (optional)
    - 可选值：`profile|episodic_memory`
    - Cloud search 当前仅支持这两类
    - 对 `hybrid|rrf|agentic`：不传时默认收敛到 `profile|episodic_memory`
    - 对 `auto`：过滤条件作用于 keyword 分支；hybrid 分支使用同一子集
  - `start_time` / `end_time` (optional, ISO 8601 with timezone)
    - 仅对 `episodic_memory` 生效
  - `current_time` (optional, ISO 8601 with timezone)
  - `radius` (optional, 0-1, 主要用于 `vector/hybrid`)
  - `include_metadata` (optional, default: false)
  - `user_id` (optional，多用户共享空间时可按身份过滤)
- 行为：检索相关记忆并返回可引用结果
- 输出：
  - `ok`
  - `space_ids`
  - 单空间时也会返回 `space_id`
  - `results[]`（每项包含 `memory_id`, `memory_type`, `snippet`, `timestamp`, `score`）
  - 使用 `auto` 时会返回 `retrieve_method_actual=auto(hybrid+keyword)`
  - `pending_count/pending_hint`（存在待提取消息时）
  - `lifecycle`（当前响应级别的 `queued|provisional|fallback|searchable|empty` 摘要）
  - `results[].stability` 用来区分正式提取结果、provisional 结果、fallback 结果
  - 上游缺少 `group_id` 时，来源恢复相关信息会通过可选 `warnings[]` 返回

### 5.5 `briefing`
- 输入：
  - `space_id` (required)
  - `max_items` (optional, default: 8)
  - `user_id` (optional)
  - `start_time` / `end_time` (optional, ISO 8601 with timezone)
- 行为：分层抓取后生成上下文简报（profile + episodic + event_log + foresight）
- 输出：`ok`、`space_id`、`summary`、`highlights[]`、`lifecycle`
- `highlights[].stability` 在正式记忆上为 `searchable`，在 metadata fallback 上为 `fallback`
  - `start_time/end_time` 作用于 `episodic_memory`、`event_log` 与 `foresight`，不作用于 `profile`
- 输出：
  - `ok`
  - `space_id`
  - `summary`
  - `highlights[]`（带引用）

### 5.6 `forget`
- 输入：
  - `memory_ids` (required, array)
  - `space_id` (required)
  - `reason` (optional)
  - `user_id` (optional)
- 行为：删除指定记忆（V1 只支持显式 id，避免误删）
- 行为：未传 `user_id` 时默认使用 MCP 客户端身份做删除范围约束
- 行为：当前 Cloud 删除语义应按 best-effort 理解，调用方需要删前删后都做核验，不能假设立即消失
- 输出：
  - `ok`
  - `space_id`
  - `deleted_count`
  - 可选 `delete_scope_user_id`
  - 可选 `errors[]`
  - 删除保持幂等：未命中 ID 通过可选 `unmatched_ids/unmatched_count` 与 `warnings[]` 返回

### 5.7 `fetch_history`
- 输入：
  - `space_id` (required)
  - `memory_type` (optional, default: `episodic_memory`，可选 `profile|episodic_memory|foresight|event_log`)
  - `limit` (optional, default: 50, 范围 1-100)
  - `offset` (optional, default: 0)
  - `user_id` (optional)
  - `start_time` / `end_time` (optional)
  - `include_metadata` (optional, default: false)
- 行为：按 memory type 分页读取历史，适合时间线浏览/批量复盘
- 行为：当上游只支持 `page/page_size` 时，服务层会做拼接，保证 0-based `offset` 语义精确
- 行为：当 `recall` 排序不稳定，或需要做删前/删后核验时，`fetch_history` 是首选时间线路径
- 输出：`ok`、`space_id`、`memory_type`、`items[]`（含 `memory_id`、`timestamp`、`snippet` + `content`、可选 `source_message_id`）、`count`、可选 `total_count`、`has_more`、可选 `next_offset`

## 6) 来源引用策略（V1 必做）
- recall/briefing 输出必须带轻量引用：
  - `timestamp`
  - `snippet`（截断后的上下文片段）
  - `memory_type`
  - `score`（若检索结果提供）
  - `source_message_id`（若上游可解析到原始消息引用）
- 目标：让结果可追溯、可验证、可解释

## 7) 错误语义
- `CONFIG_ERROR`：环境变量缺失或配置非法
- `UPSTREAM_UNAVAILABLE`：EverMemOS 不可用/超时
- `INVALID_INPUT`：tool 参数校验失败
- `NOT_FOUND`：查询为空或待删除对象不存在

## 8) 最小测试矩阵（V1）
- 合同测试：7 个 tools 的输入输出结构
- 隔离测试：不同 `space_id` 互不召回
- 引用测试：recall/briefing 必须返回时间+片段
- 安全测试：forget 仅允许显式 id 删除
- 路由测试：`list_spaces` + query 能返回正确候选
- 失败测试：EverMemOS 断开时返回可理解错误

## 9) 演示脚本建议
- 场景 A（coding）：记住架构决策 -> 新会话 recall
- 场景 B（chat）：记住偏好 -> 问答召回
- 场景 C（study）：记住学习要点 -> briefing 总结

每个场景都演示：写入 -> 检索 -> 引用 -> 隔离。

## 10) 已识别技术风险与应对

### 10.1 边界检测延迟（高优先级）
- 风险：EverMemOS 存储后不一定立即可检索，可能需要边界检测完成后才提取记忆。
- 影响：`remember` 后立即 `recall` 可能为空，影响体验和 demo 稳定性。
- 应对策略（按优先级）：
  1. 先做 API 行为验证（单条写入、双条 mini conversation、等待时间）
  2. `remember` 默认 `flush=false`，并由调用方在明确边界时显式传 `flush=true`
  3. `recall` 空结果时提供 graceful 提示，不把空结果当系统错误
  4. 若上游支持强制提取参数，则作为可选能力接入

### 10.2 `briefing` 组装路径（中优先级）
- V1 采用分层抓取并结构化拼装：
  1. `profile`：画像/偏好
  2. `episodic_memory`：近期活动（limit N）
  3. `event_log`：关键事实与结论
  4. `foresight`：未来计划/提醒
- 目标：体现 EverMemOS 多 memory type 的差异化价值，不做黑盒摘要。

### 10.3 MCP Transport 选择（中优先级）
- V1 默认 `stdio`：
  - 客户端兼容性好（Claude Code/Cursor/Cherry Studio）
  - 无需额外 HTTP 服务，安装与配置最轻
  - 更适合比赛演示的可复现性

## 11) 实施顺序（已调整）
1. 验证 EverMemOS API 行为（边界检测、写入后可检索时机）
2. 实现 `evermemos_client` + `space_catalog_service` + `space_router`
3. 实现 `remember` + `recall`（核心闭环）
4. 实现 `briefing` + `forget`
5. 补来源引用字段与测试矩阵

## 12) V1 非目标
- 自动摘要写回（V1.1）
- 团队协作 group scope（V1.1）
- 高级脱敏与权限策略（后续）
