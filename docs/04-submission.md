# Memory Genesis 2026 提交清单（Phase 5）

## 1. 仓库内容检查

- [x] README（安装、配置、工具说明、演示方式）
- [x] 需求文档 `docs/01-requirements.md`
- [x] 架构文档 `docs/02-architecture.md`
- [x] Demo 手册 `docs/03-demo-playbook.md`
- [x] 可运行入口：`evermemos-mcp`
- [x] 测试通过：`uv run pytest`

## 2. 演示视频检查（3-5 分钟）

- [ ] 介绍痛点：跨 session 丢失上下文
- [ ] 展示 `list_spaces` 路由
- [ ] 展示 `recall` 引用字段（timestamp/snippet/type/score）
- [ ] 展示 `briefing` 恢复上下文
- [ ] 展示 `forget` 删除可控
- [ ] 明确说明 Cloud 异步提取（预加载策略）

## 3. 提交描述建议结构

1. Problem
2. Solution
3. Why MCP + EverMemOS
4. Live capabilities (5 tools)
5. Demo highlights
6. Future roadmap

## 4. Demo 讲解要点（可直接复用）

- "We use `space_id` as the primary isolation key to prevent context leakage across tasks."
- "Writes are queued on Cloud, so we preload memories before live retrieval demos."
- "Recall and briefing always return traceable evidence fields, not opaque summaries."

## 5. PR 模板中的 AI Disclosure（按工作区规范）

在开源 PR 描述中，保留以下原文：

```md
## AI Assistance Disclosure

I used Codex to review the changes, sanity-check the implementation against existing patterns, and help spot potential edge cases.
```

## 6. 发布前最终验证

```bash
uv run pytest
uv run python scripts/demo_preload.py --wait --check-status --timeout 480 --interval 20
uv run python scripts/demo_live_walkthrough.py
```
