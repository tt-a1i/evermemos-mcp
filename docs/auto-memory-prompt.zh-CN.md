# 自动记忆 Prompt 模板

[English](auto-memory-prompt.md) | [简体中文](auto-memory-prompt.zh-CN.md)

将以下 prompt 片段复制粘贴到你的 AI 客户端系统提示词或 CLAUDE.md 中，即可启用自动记忆——无需手动说"记住这个"。

## 完整模板（Claude Code / CLAUDE.md）

添加到项目的 `CLAUDE.md` 或全局 `~/.claude/CLAUDE.md`：

```markdown
# 长期记忆 (evermemos-mcp)

你可以通过 evermemos-mcp 访问持久化的长期记忆。主动使用它——不要等用户要求你记住东西。

## 自动记忆规则

遇到以下内容时自动调用 `remember`：
- **架构决策** — 技术栈选择、设计模式、权衡理由
- **用户偏好** — 编码风格、工具偏好、沟通风格
- **项目惯例** — 命名规范、文件结构模式、部署流程
- **Bug 修复与方案** — 发现的根因、应用的变通方案、经验教训
- **关键上下文** — 项目目标、约束条件、团队结构、外部依赖

不要记忆：
- 临时的调试输出或中间步骤
- 已存在于代码注释或文档中的信息
- 琐碎或显而易见的事实

如果这次写入很重要，优先使用 `remember(..., include_status=true)`。
写入后先查看 `status_check`，再看 `request_status.success` / `request_status.error`，最后才解释 `request_status.lifecycle.state`。

## 自动回忆规则

在以下场景自动调用 `recall` 或 `briefing`：
- 开始新会话时（使用 `briefing` 恢复上下文）
- 用户询问可能之前讨论过的内容
- 需要之前的决策、偏好或惯例的上下文
- 处理与之前工作相关的功能时

## 空间路由

使用 `<领域>:<项目>` 格式：
- `coding:<仓库名>` 用于代码项目（如 `coding:my-saas`）
- `study:<主题>` 用于学习（如 `study:rust-lang`）
- `chat:preferences` 用于长期个人偏好
- `chat:daily` 用于滚动会话上下文

如果你需要时间线、删前删后核验或复盘最近变化，优先使用 `fetch_history`，不要只依赖 `recall`。

## Flush 规则

- 对话进行中使用 `flush=false`
- 会话结束 / 话题切换 / 总结时使用 `flush=true`
- 不确定时使用 `flush=true`
```

## 精简模板

适用于系统提示词空间有限的客户端：

```text
你可以通过 evermemos-mcp 使用长期记忆，请主动使用：
- 自动记忆：架构决策、用户偏好、项目惯例、Bug 解决方案
- 重要写入优先使用 remember(..., include_status=true)，并先检查 request_status.success/error，再看 lifecycle.state
- 自动回忆：会话开始时（briefing）、需要历史上下文时
- 空间格式：coding:<仓库名>, study:<主题>, chat:preferences, chat:daily
- 对话中 flush=false，边界处 flush=true
```

## Cursor / Cline 规则文件

添加到 `.cursorrules` 或 `.clinerules`：

```text
# 记忆集成
本项目使用 evermemos-mcp 进行持久化记忆（space: coding:<项目名>）。

会话开始时：
1. 调用 briefing(space_id="coding:<项目名>") 恢复上下文

工作过程中：
2. 做出架构决策或发现 Bug 时，调用 `remember(..., include_status=true)` 存储，并立即做写后检查
3. 不确定之前的决策时，调用 recall() 查询
4. 如果 `request_status.success` 为 false，应先暴露状态检查失败，而不是把它当成正常排队
5. 如果 `request_status.lifecycle.state` 仍是 `queued`，把 recall/briefing 当作临时帮助，而不是 searchable 的正式证明

会话结束时：
6. 总结关键决策并调用 `remember(flush=true, include_status=true)`
```

## 工作原理

```
会话开始
    │
    ▼
briefing → 从上次会话恢复上下文
    │
    ▼
用户提出问题
    │
    ├─ recall → 检查记忆中是否有相关上下文
    │
    ▼
AI 处理任务
    │
    ├─ remember(flush=false, include_status=true) → 随时存储决策和发现，并记录 request_status
    │
    ▼
会话结束 / 话题切换
    │
    └─ remember(flush=true, include_status=true) → 触发最终提取，并继续用 request_status 检查直到 searchable
```

这构建了 **记忆 → 推理 → 行动** 闭环：
- **记忆**：briefing + recall 提供上下文
- **推理**：AI 利用回忆的上下文做出更好的决策
- **行动**：AI 存储新的洞察供未来会话使用
