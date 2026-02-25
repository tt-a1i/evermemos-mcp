# Benchmark Protocol (Competition)

## 1) Purpose
Provide reproducible evidence for Memory Genesis 2026 submission quality.

This benchmark focuses on three measurable outcomes:
- Recall hit rate
- Recall latency (P50 / P95)
- Source attribution error rate

## 2) Scope
- Product: `evermemos-mcp`
- Deadline context: submit before 2026-03-15
- Scenarios:
  - `coding`
  - `chat`
  - `study`

## 3) Dataset Design
- Query set:
  - Minimum `N = 60` total queries
  - `20` queries per scenario (`coding/chat/study`)
- Comparison:
  - `with memory` vs `without memory` on the same fixed query set
- Attribution sample:
  - Minimum `N = 200` resolved rows for attribution error analysis

Recommended query schema:

```json
{
  "scenario": "coding",
  "space_ids": ["coding:demo-app", "coding:infra"],
  "query": "What did we decide about deployment rollback?",
  "expected_signals": ["blue-green", "canary", "rollback plan"]
}
```

## 4) Metric Definitions

### 4.1 Recall Hit Rate
- Definition: query-level success rate
- Hit condition: at least one retrieved row contains expected signal
- `expected_signals` matching rule:
  - Default rule is case-insensitive substring match on concatenated `snippet + content`.
  - Optional fuzzy match is allowed only when explicitly enabled in benchmark script config and must be reported in output metadata.
- Formula: `hit_rate = hit_queries / total_queries`
- Submission gate:
  - With-memory hit rate `>= 80%`
  - Improvement over no-memory baseline `>= +40 percentage points`

### 4.2 Recall Latency
- Definition: end-to-end recall latency at client side
- Formula: `latency_ms = t_response - t_request`
- Reporting:
  - `P50` and `P95`
  - Use warm runs for headline numbers (cold start excluded)
- Submission gate:
  - `P95 <= 2000 ms`

### 4.3 Source Attribution Error Rate
- Definition: wrong `space_id` attribution among resolved rows
- Formula: `attribution_error_rate = wrong_attributions / resolved_rows`
- Submission gate:
  - `<= 2.0%`

## 5) Execution Protocol

### 5.1 Preconditions
1. `.env` configured (`EVERMEMOS_API_KEY` set)
2. Demo preload completed
3. Test baseline healthy

```bash
uv run ruff check
uv run pytest -q
uv run python scripts/demo_preload.py --wait --check-status --timeout 480 --interval 20
```

### 5.2 Benchmark Run
Run benchmark collector (script path aligned with sprint plan):

```bash
uv run python scripts/competition_eval.py \
  --input artifacts/competition/{date}/runs.jsonl \
  --output artifacts/competition/{date}/benchmark_summary.json
```

## 6) Artifact Layout
All benchmark evidence should be written under:

`artifacts/competition/{date}/`

Required files:
- `runs.jsonl`: raw per-query run records
- `benchmark_summary.json`: aggregated metrics and pass/fail against gates
- `benchmark_report.md`: human-readable summary for submission

## 7) Reporting Template
Minimal summary schema:

```json
{
  "date": "2026-03-08",
  "query_count": 60,
  "resolved_rows": 220,
  "hit_rate_with_memory": 0.85,
  "hit_rate_without_memory": 0.38,
  "delta_hit_rate": 0.47,
  "latency_p50_ms": 820,
  "latency_p95_ms": 1720,
  "attribution_error_rate": 0.0136,
  "gates": {
    "hit_rate": "pass",
    "latency_p95": "pass",
    "attribution_error_rate": "pass"
  }
}
```

## 8) Acceptance Rules
Benchmark is considered submission-ready only when all are true:
1. Data volume thresholds are met (`60` queries, `200` resolved rows)
2. All three metric gates pass
3. Artifacts are complete and reproducible by command
4. Report is linked in submission materials
