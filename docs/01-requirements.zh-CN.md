# evermemos-mcp 需求草案（V0）

[English](01-requirements.md) | [简体中文](01-requirements.zh-CN.md)

## 1) 产品目标
在各类 AI 客户端（MCP-compatible）中提供长期记忆能力，让助手跨 session 持续上下文。

首发场景仍聚焦开发者工具（Claude Code/Cursor/Cline），但架构上保持通用，可扩展到 Cherry Studio 等通用聊天客户端。

定位原则：定位泛化（universal memory layer），Demo 聚焦（2-3 个高价值场景）。

## 2) 核心问题
当前 AI 客户端体验的主要断点是会话重置：
- 不记得历史偏好、约束、决策与上下文
- 不记得曾经修复过的问题与结论
- 不同会话之间缺乏连续性
- 每次都要重复提供背景

## 3) 目标用户（Primary Persona）
- Primary（V1）：高频使用 AI coding tools 的开发者
- Secondary（V1.1）：使用 Cherry Studio/其他 AI 聊天客户端的知识工作者
- 共性需求：跨会话连续性、记忆可控（可查/可删/可隔离）

## 4) 价值主张（Value Proposition）
- 新 session 也能持续上下文，不再从零开始
- 用 `space_id` 隔离的记忆避免上下文串味
- 通过可检索、可删除、可回顾的记忆降低风险

## 5) 产品边界
### In Scope（V1 必做）
- MCP 工具集：`list_spaces` / `remember` / `recall` / `briefing` / `forget`
- 记忆 scope：`space_id` 隔离（必须），`project_id` 只是 coding 场景的一种默认映射
- EverMemOS API 接入：存储、检索、删除
- 数据策略：Cloud-only（不做本地持久化）
- 最小安全：敏感字段手动删除（forget）

### Out of Scope（V1 不做）
- 可视化前端后台
- 自动敏感信息检测与脱敏策略引擎
- 复杂权限系统（多租户 RBAC）

## 6) 关键用户故事（V1）
1. 作为开发者，我希望 AI 记住本项目的架构约定，这样新开会话时不用重复解释。
2. 作为开发者，我希望按问题检索历史决策和方案，这样可以快速继续中断任务。
3. 作为开发者，我希望启动会话时拿到项目简报，这样我能马上进入上下文。
4. 作为开发者，我希望删除错误或敏感记忆，这样可控且安全。
5. 作为聊天用户，我希望按主题 `space_id` 隔离记忆，避免不同话题串味。
6. 作为学习用户，我希望 AI 记住我在某个学习空间中的历史理解与盲点。

## 7) 验收标准（V1）
- `list_spaces` 可返回可路由信息：`space_id` + `description` + `memory_count`
- `remember` 成功后，`recall` 可在同 `space_id` 检索到相关记忆
- 跨 `space_id` 检索不应返回其他空间记忆（隔离）
- `briefing` 在空空间和非空空间都能返回可解释结果
- `forget` 对目标记忆生效，后续检索不可见

## 8) Demo 成功标准（比赛导向）
- 同一问题对照（无记忆 vs 有记忆）明显成立
- 展示 2-3 场景切换（coding / daily chat / study）
- 展示 `space_id` 隔离：Space A 与 Space B 记忆不串
- 演示删除可控：删除后检索不到目标内容

## 9) 非功能需求
- 响应速度：常规检索 < 2s（本地环境目标）
- 稳定性：EverMemOS 不可用时返回明确错误
- 可迁移性：本地 EverMemOS 与 Cloud URL 可切换

## 10) 版本规划
### V1（比赛提交版）
- 五个 MCP tools（含 `list_spaces`）+ `space_id` 隔离 + 可复现实验 demo

### V1.1（加分项）
- 自动 session 摘要入库
- 团队模式（group scope）

## 11) 已冻结决策（不再讨论）
1. **`space_id` 命名规范**：`<domain>:<slug>`（如 `coding:my-app`, `chat:daily`, `study:ml`）
2. **路由策略**：优先由 AI 先调用 `list_spaces`，基于 `description` 匹配后再调用业务 tool；不依赖 cwd/git 自动推断
3. **数据落点**：Cloud-only，空间元数据与记忆正文都在 EverMemOS
4. **来源引用**：V1 必做（轻量版，至少返回时间 + 上下文片段）
