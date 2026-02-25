# 主视频脚本（中文，2-3 分钟）

## 0) 固定口径（录制前必须锁定）
- 证据口径固定为：`artifacts/competition/2026-02-26-formal-real-auto-all-v3/benchmark_summary.json`
- 录制时不改参数，不临场切换方案。

## 1) 录制前准备（不入镜）
```bash
uv sync --group dev
uv run python scripts/demo_preload.py --wait --check-status --timeout 480 --interval 20
```

## 2) 正片台词与操作

### 00:00-00:20 问题定义
台词：
“很多 AI 助手在新会话里会丢上下文，用户要反复重复偏好和项目决策。我们做的 `evermemos-mcp`，目标是把跨会话记忆做成可检索、可归因、可删除的 MCP 插件能力。”

### 00:20-00:50 能力总览
操作：
```bash
uv run python scripts/demo_live_walkthrough.py
```
台词：
“我们先看 `list_spaces`，用 `space_id` 做强隔离。然后看 `recall` 和 `briefing`，它们返回可追踪字段，不是黑盒摘要。”

### 00:50-01:30 隔离与恢复
台词：
“同样是召回，`coding:*` 和 `chat:*` 分开检索，避免记忆串线。`briefing` 可以在新会话开头快速恢复上下文。”

### 01:30-02:10 主证据展示
操作：
```bash
examples/competition-demo/run.sh --retrieve-method auto --top-k -1
cat artifacts/competition/2026-02-26-formal-real-auto-all-v3/benchmark_summary.json
```
台词：
“这是 formal-real 主证据。60 条查询里 with-memory 命中率 100%，P95 延迟 1957.75ms，误归因为 0，四项门禁全部通过。”

### 02:10-02:35 透明性与审计
台词：
“我们保留了 v1/v2 未过线记录，v3 通过。原始 `runs.jsonl` 不入库，作为 release 资产提供，并附 sha256，方便评委复核。”

### 02:35-02:55 收尾
台词：
“总结：`evermemos-mcp` 把长期记忆做成了可复现、可审计、可上线的插件层能力。”

## 3) 结束画面建议
- 屏幕停留 3 秒：
  - 主证据文件路径
  - Evidence release 链接
