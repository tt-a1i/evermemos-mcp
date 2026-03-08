# evermemos-mcp 需求草案（V0）

[English](01-requirements.md) | [简体中文](01-requirements.zh-CN.md)

## 1) 产品目标
为 MCP 兼容 AI 客户端提供长期记忆能力，让助手在跨会话场景下持续保有上下文。

首发仍聚焦开发者工具（Claude Code/Cursor/Cline），但架构设计保持通用，可扩展到 Cherry Studio 等聊天客户端。

原则：定位泛化（通用记忆层），演示聚焦（2-3 个高价值场景）。

## 2) 核心问题
当前 AI 客户端体验的主要断点在于会话重置：
- 历史偏好、约束、决策与上下文会丢失
- 过去修复过的问题与结论无法复用
- 不同会话缺少连续性
- 用户需要反复提供背景信息

## 3) 目标用户
- 主要人群（V1）：高频使用 AI 编程工具的开发者
- 次要人群（V1.1）：使用 Cherry Studio/其他 AI 聊天客户端的知识工作者
- 共性诉求：跨会话连续性 + 记忆可控（可查、可删、可隔离）

## 4) 价值主张
- 新会话可延续上下文，不再从零开始
- 通过 `space_id` 隔离记忆，避免不同任务串味
- 通过可检索、可删除、可回溯机制降低误用风险

## 5) 产品边界
### In Scope（V1 必做）
- MCP 工具集：`list_spaces` / `remember` / `request_status` / `recall` / `briefing` / `forget` / `fetch_history`
- 记忆隔离：以 `space_id` 为主（必须）；`project_id` 只是 coding 场景的一种映射
- EverMemOS API：完成写入、状态查询、检索、删除闭环
- 数据策略：Cloud-only（不做本地持久化）
- 最小安全：支持显式删除（`forget`）

### Out of Scope（V1 不做）
- 可视化后台
- 自动敏感信息检测与脱敏引擎
- 复杂权限系统（多租户 RBAC）

## 6) 关键用户故事（V1）
1. 作为开发者，我希望 AI 记住项目架构约定，新开会话时无需重复解释。
2. 作为开发者，我希望按问题检索历史决策，快速续接中断任务。
3. 作为开发者，我希望开场能拿到简报，快速恢复上下文。
4. 作为开发者，我希望能删除错误或敏感记忆，保证可控与安全。
5. 作为聊天用户，我希望按 `space_id` 做主题隔离，避免话题串味。
6. 作为学习用户，我希望 AI 记住我在某学习空间中的历史理解与盲点。

## 7) 验收标准（V1）
- `list_spaces` 返回可路由信息：`space_id`、`description`、`memory_count`
- `remember` 后可在同 `space_id` 通过 `recall` 找回相关记忆
- `fetch_history` 支持按 `memory_type` 分页翻阅历史
- 跨 `space_id` 检索不应返回其他空间记忆
- `briefing` 在空空间和非空空间都返回可解释结果
- `forget` 以 best-effort 删除路径对外暴露，并提供删前/删后核验指引

## 8) 演示成功标准（比赛导向）
- 同一问题对照明显成立（无记忆 vs 有记忆）
- 展示 2-3 个场景切换（coding / daily chat / study）
- 展示 `space_id` 隔离（Space A 与 Space B 不串）
- 展示删除可控，并能诚实表达 Cloud 限制与核验流程

## 9) 非功能需求
- 性能：常规检索 < 2 秒（本地目标）
- 稳定性：EverMemOS 不可用时返回明确错误
- 可迁移性：支持本地/Cloud 地址切换

## 10) 版本规划
### V1（比赛提交版）
- 七个 MCP tools（含 `request_status`）+ `space_id` 隔离 + 可复现实验 Demo

### V1.1（加分项）
- 自动会话摘要入库
- 团队模式（group scope）

## 11) 已冻结决策（不再讨论）
1. **`space_id` 命名规范**：`<domain>:<slug>`（如 `coding:my-app`, `chat:daily`, `study:ml`）
2. **路由策略**：优先显式传入 `space_id` 或先通过 `list_spaces` 发现空间；未提供时允许从 `EVERMEMOS_DEFAULT_SPACE` 或 git remote 自动推断默认空间
3. **数据落点**：Cloud-only，空间元数据与记忆正文都在 EverMemOS
4. **来源引用**：V1 必做（至少返回时间 + 上下文片段）
