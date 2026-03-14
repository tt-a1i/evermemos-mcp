# Memory Genesis 2026 提交清单（Phase 5）

[English](04-submission.md) | [简体中文](04-submission.zh-CN.md)

## 1. 仓库内容检查

- [x] README（安装、配置、工具说明、演示方式）
- [x] 需求文档 `docs/01-requirements.md`
- [x] 架构文档 `docs/02-architecture.md`
- [x] Demo 手册 `docs/03-demo-playbook.md`
- [x] 可运行入口：`evermemos-mcp`
- [x] 测试通过：`uv run pytest`

## 1.1 非视频提交资产

- [x] 最新包元数据已对齐到 `v0.5.6`
- [x] 最新 release/tag 已可访问：`v0.5.6`
- [x] Evidence release 已可访问：`competition-evidence-2026-02-26`
- [x] Benchmark 深度说明：`docs/competition/benchmark_deep_dive.md`
- [x] Lifecycle appendix 生成脚本：`scripts/competition_lifecycle_appendix.py`

## 2. 演示视频检查（3-5 分钟）

- [ ] 脚本定稿：`docs/competition/video_script_main.en.md` / `docs/competition/video_script_main.zh-CN.md`
- [ ] 短视频脚本定稿：`docs/competition/video_script_short_clip.md`
- [ ] 介绍痛点：跨 session 丢失上下文
- [ ] 展示 `list_spaces` 路由
- [ ] 说明 `request_status` 是写后核验主路径
- [ ] 展示 `recall` 引用字段（timestamp/snippet/type/score）
- [ ] 展示 `briefing` 恢复上下文
- [ ] 展示 `fetch_history` 的时间线/删除核验路径
- [ ] 展示 `forget` 的定向删除（若目标仍可 recall，则说明这是当前 Cloud 限制）
- [ ] 明确说明 Cloud 异步提取（预加载策略）

## 3. 提交描述建议结构

1. 问题定义
2. 方案说明
3. 为什么选择 MCP + EverMemOS
4. 线上能力展示（7 个 tools）
5. 演示亮点（Demo highlights）
6. 后续路线图

## 4. 演示讲解要点（可直接复用）

- "We use `space_id` as the primary isolation key to prevent context leakage across tasks."
- "Writes are queued on Cloud, so we preload memories before live retrieval demos."
- "`request_status` is the write-after check before we claim a memory is searchable."
- "Recall and briefing always return traceable evidence fields, not opaque summaries."

## 5. PR 模板中的 AI Disclosure（按工作区规范）

在开源 PR 描述中，保留以下原文：

```md
## AI Assistance Disclosure

I used Codex to review the changes, sanity-check the implementation against existing patterns, and help spot potential edge cases.
```

## 6. 发布前最终验证

```bash
uv run ruff check
uv run pytest
uv run python scripts/demo_preload.py --wait --check-status --timeout 480 --interval 20
uv run python scripts/demo_live_walkthrough.py
uv run python scripts/competition_lifecycle_appendix.py
```

说明：
- 上面两个 EverMemOS live 命令都依赖有效的 `EVERMEMOS_API_KEY`。
- `scripts/competition_lifecycle_appendix.py` 在鉴权失败或环境校验失败时，仍会落盘失败产物（`appendix_notes.md`、`appendix_results.json`、`raw_logs.txt`），便于保留可审计的阻塞证据。
