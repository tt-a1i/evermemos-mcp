# 主视频脚本（中文，2-3 分钟，可直接照读）

## 0) 固定口径（录制前必须锁定）
- 主证据固定为：`artifacts/competition/2026-02-26-formal-real-auto-all-v3/benchmark_summary.json`
- 录制时不改参数，不临场切方案。

## 1) 录制前准备（不入镜）
```bash
uv sync --group dev
uv run python scripts/demo_preload.py --wait --check-status --timeout 480 --interval 20
```

## 2) 逐句口播 + 画面

### 00:00-00:20（评测目标）
口播：
“这不是普通功能演示，而是一套可复现评测。我们要验证三件事：记忆是否提升召回质量、延迟是否可上线、归因是否正确不串线。”

### 00:20-00:45（评测方法）
口播：
“我们在固定 60 条查询上做 A/B：with_memory 对比 without_memory，同一查询集、同一口径，输出 runs.jsonl、benchmark_summary.json、benchmark_report.md。”

### 00:45-01:20（产品闭环）
画面操作：
```bash
uv run python scripts/demo_live_walkthrough.py
```
口播：
“产品闭环是 remember -> request_status -> recall/briefing -> fetch_history/forget。也就是说，不只是能记住，还能核验生命周期、跨会话恢复，并且在当前 Cloud 限制下诚实处理删除能力。”

### 01:20-01:55（指标意义）
口播：
“hit rate 看记忆是否有用；delta 看提升是否来自 memory；P95 latency 看线上可用性；attribution error 看会不会记错空间导致串线。”

### 01:55-02:20（主证据结果）
画面操作（建议直接展示已生成文件，不临场全量重跑）：
```bash
cat artifacts/competition/2026-02-26-formal-real-auto-all-v3/benchmark_summary.json
```
口播：
“正式 real-data 主证据：with-memory 60/60，P95=1957.75ms，resolved_rows=236，attribution_error=0，四项门禁全部通过。”

### 02:20-02:45（透明性与审计）
口播：
“我们保留了 v1/v2 未过线记录，v3 通过。原始 runs.jsonl 作为 release 资产公开，并提供校验信息，便于独立复核。”

## 3) 结束画面（3 秒）
- 主证据目录：`artifacts/competition/2026-02-26-formal-real-auto-all-v3/`
- Evidence release：`competition-evidence-2026-02-26`
