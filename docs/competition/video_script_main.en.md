# Main Video Script (EN, 2-3 min)

## 0) Locked Evidence Scope (must stay fixed)
- Primary evidence is fixed to:
  `artifacts/competition/2026-02-26-formal-real-auto-all-v3/benchmark_summary.json`
- No parameter changes during recording.

## 1) Pre-record setup (off camera)
```bash
uv sync --group dev
uv run python scripts/demo_preload.py --wait --check-status --timeout 480 --interval 20
```

## 2) On-camera script and actions

### 00:00-00:20 Problem
Narration:
“AI assistants often lose context across sessions, forcing users to repeat preferences and prior decisions. `evermemos-mcp` turns long-term memory into auditable MCP plugin capabilities.”

### 00:20-00:50 Capability overview
Action:
```bash
uv run python scripts/demo_live_walkthrough.py
```
Narration:
“We start with `list_spaces` for routing and isolation, then use `recall` and `briefing` with traceable fields instead of opaque summaries.”

### 00:50-01:30 Isolation and restoration
Narration:
“`coding:*` and `chat:*` are strictly isolated to prevent memory leakage. `briefing` restores session context quickly at startup.”

### 01:30-02:10 Primary evidence
Action:
```bash
examples/competition-demo/run.sh --retrieve-method auto --top-k -1
cat artifacts/competition/2026-02-26-formal-real-auto-all-v3/benchmark_summary.json
```
Narration:
“This is our formal-real primary evidence. With memory: 100% hit rate on 60 queries, P95 latency 1957.75ms, zero attribution errors, and all gates pass.”

### 02:10-02:35 Transparency and auditability
Narration:
“We keep failed v1/v2 attempts visible, and v3 passes. Raw `runs.jsonl` is distributed as a release asset with checksum for independent verification.”

### 02:35-02:55 Closing
Narration:
“`evermemos-mcp` delivers practical long-term memory as reproducible, auditable plugin infrastructure.”

## 3) End card
- Hold for 3 seconds:
  - Primary evidence path
  - Evidence release URL
