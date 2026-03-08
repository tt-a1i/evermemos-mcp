# 任务计划：evermemos-mcp（通用记忆 MCP 服务）

[English](task_plan.md) | [简体中文](task_plan.zh-CN.md)

## 总目标
构建一个 MCP 服务器，为 MCP 兼容 AI 客户端提供基于 EverMemOS 的长期记忆能力，并完成 Memory Genesis 2026（Track 2）提交。

## 阶段状态
- [x] Phase 1：需求讨论与产品设计
- [x] Phase 2：技术方案与架构设计
- [x] Phase 3：核心能力实现
- [x] Phase 4：演示流程与测试完善
- [x] Phase 5：文档与提交材料完善

## 关键问题（需求阶段）
1. 核心用户是谁，跨会话记忆的最高价值点是什么？
2. MCP 需要暴露哪些 tools，粒度如何？
3. 记忆隔离模型如何设计（`space_id`、用户级、全局级）？
4. EverMemOS 需要接哪些 API，覆盖哪些 memory types？
5. MVP 边界怎么定，哪些必须做、哪些后续迭代？
6. 如何在 3-5 分钟内清晰展示核心价值？

## 已确认决策
- 赛道：Track 2（Platform Plugin）
- 产品：通用 Memory MCP Server（`evermemos-mcp`）
- V1 工具集：`list_spaces` / `remember` / `request_status` / `recall` / `briefing` / `forget` / `fetch_history`
- 隔离模型：使用 `space_id`
- 路由策略：优先显式 `space_id`，并支持通过 `list_spaces` 发现空间或从 env/git 自动推断默认空间
- 传输方式：V1 默认 `stdio`
- 数据策略：Cloud-only（不做本地持久化）

## 风险与事实
- Cloud 提取是异步（通常 2-5 分钟），`remember` 后不能保证立刻 `recall`
- 演示必须采用“预加载 -> 等待提取 -> 现场检索”
- 某些环境下 `GET + JSON body` 可能被代理/WAF 剥离

## 里程碑回顾

### Phase 3.1（API 验证）
- 验证了 Cloud v0 的鉴权、写入、检索、抓取路径
- 确认了 `pending_messages` 对异步提示的价值

### Phase 3.2（客户端与目录）
- 完成 `evermemos_client` 与 `space_catalog_service`
- 完成 `group_id <-> space_id` 映射
- 完成基础恢复与错误语义测试

### Phase 3.3（7 个 tools 闭环）
- 完成 `list_spaces/remember/request_status/recall/briefing/forget/fetch_history`
- 完成引用字段输出与主要错误映射
- 完成服务层、客户端、服务端多层测试覆盖

## 当前状态
核心闭环已完成，后续以稳定性、文档体验和生态接入优化为主。
