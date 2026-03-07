# 需求与验证笔记

[English](notes.md) | [简体中文](notes.zh-CN.md)

## 比赛背景
- Hackathon：Memory Genesis 2026（Track 2：Platform Plugin）
- 截止日期：2026-03-15
- 评估优先级：Quality & Execution > Memory Integration > Community Impact
- 提交物：GitHub 仓库 + README + 3-5 分钟演示视频

## EverMemOS API 摘要
- Cloud 路径：`/api/v0/memories`、`/api/v0/memories/search`
- 本地兼容路径：`/api/v1/memories`、`/api/v1/memories/search`
- `flush=true` 可显式标记会话边界
- 记忆类型：`episodic_memory`、`profile`、`foresight`、`event_log`
- 检索方式：`keyword`、`vector`、`hybrid`、`rrf`、`agentic`

## MCP 基础
- MCP Server 向客户端暴露可调用的 tools
- tool 包含名称、描述和 JSON Schema 输入
- 传输方式常见为 `stdio`（本地）或 `SSE`（远程）

## 用户痛点（以开发者为例）
- 新会话丢失项目偏好与上下文
- 架构决策需要反复解释
- Bug 修复经验无法积累
- 代码风格偏好每次都要重新说明

## Phase 3.1 行为验证结论

### 连通性
- Cloud 可访问，v0 鉴权通过 `Authorization: Bearer` + `X-API-Key`

### Cloud 写入行为
- 写入返回 `202 Accepted`（排队），不是立刻提取
- 常见响应：`{"status":"queued","request_id":"..."}`

### 提取延迟（关键）
- Cloud 提取一般需要约 2-5 分钟
- 立即 `remember -> recall` 往往为空
- 搜索返回 `pending_messages` 可用于提示“仍在处理中”

### 检索/抓取观察
- `keyword`/`hybrid` 检索可用
- profile 类型在 search/fetch 中表现与其他类型不同
- 通过 `group_id` 的隔离是有效的

### 对产品的含义
1. `remember` 必须明确告知“已排队，可能需要几分钟才可检索”
2. `recall` 应提供 pending 提示，避免误导
3. 演示视频应“预加载记忆”而非现场写入立即召回
4. `conversation-meta` 是可选增强（更结构化的空间信息）

## 产品方向补充
- 定位从“仅 coding tools”扩展为“通用 MCP 记忆层”
- 先以开发者工具作为楔子市场验证
- 目标扩展到聊天客户端（例如 Cherry Studio）
- 隔离模型从 `project_id` 升级为通用 `space_id`
