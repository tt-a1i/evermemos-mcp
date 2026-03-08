# Main Video Script (EN, 2-3 min, read-as-is)

## 0) Locked evidence scope
- Primary evidence is fixed to:
  `artifacts/competition/2026-02-26-formal-real-auto-all-v3/benchmark_summary.json`
- No parameter changes during recording.

## 1) Pre-record setup (off camera)
```bash
uv sync --group dev
uv run python scripts/demo_preload.py --wait --check-status --timeout 480 --interval 20
```

## 2) Narration + shots

### 00:00-00:20 (Evaluation goal)
Narration:
"This is not a feature-only demo. It is a reproducible evaluation. We verify three things: recall quality improvement, production-safe latency, and correct source attribution."

### 00:20-00:45 (Evaluation method)
Narration:
"We run A/B on a fixed 60-query set: with_memory versus without_memory, using the same dataset and scoring rules, and output runs.jsonl, benchmark_summary.json, and benchmark_report.md."

### 00:45-01:20 (Product loop)
Action:
```bash
uv run python scripts/demo_live_walkthrough.py
```
Narration:
"The product loop is remember -> request_status -> recall/briefing -> fetch_history/forget. It proves we can store memory, verify lifecycle state, restore context across sessions, and handle deletion honestly under current Cloud limits."

### 01:20-01:55 (Metric meaning)
Narration:
"Hit rate shows usefulness. Delta shows gains from memory instead of chance. P95 latency shows production usability. Attribution error shows whether space routing is reliable."

### 01:55-02:20 (Primary evidence result)
Action (recommended: show pre-generated file, no live full rerun):
```bash
cat artifacts/competition/2026-02-26-formal-real-auto-all-v3/benchmark_summary.json
```
Narration:
"Formal real-data primary evidence: with-memory 60 out of 60, P95 equals 1957.75 milliseconds, resolved rows 236, attribution error zero, and all gates pass."

### 02:20-02:45 (Transparency and auditability)
Narration:
"We keep failed v1 and v2 attempts visible, and v3 passes. Raw runs.jsonl is published as a release asset with checksum for independent audit."

## 3) End card (3 seconds)
- Primary evidence directory:
  `artifacts/competition/2026-02-26-formal-real-auto-all-v3/`
- Evidence release:
  `competition-evidence-2026-02-26`
