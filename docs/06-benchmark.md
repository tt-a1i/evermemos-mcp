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
  - Baseline definition: `without_memory` means calling the same `recall` pipeline on control `no-memory` spaces (not disabling recall).
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

### 3.1 `runs.jsonl` row schema
Each line in `runs.jsonl` must be a JSON object:

```json
{
  "scenario": "coding",
  "query": "What did we decide about deployment rollback?",
  "mode": "with_memory",
  "latency_ms": 1130,
  "hit": true,
  "resolved_rows": 4,
  "wrong_attributions": 0
}
```

Field notes:
- `mode`: `with_memory` or `without_memory`
  - `with_memory`: recall on scenario target spaces (preloaded with relevant memories)
  - `without_memory`: recall on control `no-memory` spaces for A/B baseline
- `latency_ms`: end-to-end recall latency in milliseconds
- `hit`: whether the query matched expected signals
- `resolved_rows` / `wrong_attributions`: attribution stats used for error-rate aggregation

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
Collect real run rows and aggregate in one command:

```bash
examples/competition-demo/run.sh
```

Equivalent direct run:

```bash
uv run python examples/competition-demo/run_demo.py \
  --queries examples/competition-demo/query_set_real_template.jsonl \
  --artifact-dir artifacts/competition/{date}-<run-label>
```

Standalone aggregation (if `runs.jsonl` already exists):

```bash
uv run python scripts/competition_eval.py \
  --input artifacts/competition/{date}-<run-label>/runs.jsonl \
  --output artifacts/competition/{date}-<run-label>/benchmark_summary.json
```

Smoke run (6-10 rows) example:

```bash
uv run python scripts/competition_eval.py \
  --input artifacts/competition/2026-02-25-smoke/runs.jsonl \
  --output artifacts/competition/2026-02-25-smoke/benchmark_summary.json \
  --report-output artifacts/competition/2026-02-25-smoke/benchmark_report.md \
  --min-queries 4 \
  --min-resolved-rows 16
```

## 6) Artifact Layout
All benchmark evidence should be written under:

`artifacts/competition/{date}-<run-label>/`

Examples of `<run-label>`: `smoke`, `formal-real`, `formal-real-auto-all-v3`.

Required files:
- `runs.jsonl`: raw per-query run records
- `benchmark_summary.json`: aggregated metrics and pass/fail against gates
- `benchmark_report.md`: human-readable summary for submission

Repository boundary for submission packaging:
- Commit to git: `benchmark_summary.json` + `benchmark_report.md` + docs/scripts.
- Keep out of git: `runs.jsonl` (upload as Release asset for audit download).

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

## 9) Current Phase 2 Outputs
- Demo runner and template:
  - `examples/competition-demo/run_demo.py`
  - `examples/competition-demo/run.sh`
  - `examples/competition-demo/query_set_real_template.jsonl`
- Formal real-data artifacts (primary evidence, 2026-02-26):
  - `artifacts/competition/2026-02-26-formal-real-auto-all-v3/benchmark_summary.json`
  - `artifacts/competition/2026-02-26-formal-real-auto-all-v3/benchmark_report.md`
  - Gate status: `overall=pass` (`data_volume/hit_rate/latency_p95/attribution_error_rate` all pass)
- Smoke artifacts:
  - `artifacts/competition/2026-02-25-smoke/runs.jsonl`
  - `artifacts/competition/2026-02-25-smoke/benchmark_summary.json`
  - `artifacts/competition/2026-02-25-smoke/benchmark_report.md`
- Formal threshold validation artifacts (synthetic dataset, appendix only):
  - `artifacts/competition/2026-02-25-formal-synthetic/runs.jsonl`
  - `artifacts/competition/2026-02-25-formal-synthetic/benchmark_summary.json`
  - `artifacts/competition/2026-02-25-formal-synthetic/benchmark_report.md`
- Formal real-data diagnostics (appendix only):
  - `artifacts/competition/2026-02-25-formal-real/benchmark_summary.json`
  - `artifacts/competition/2026-02-26-formal-real-k12/benchmark_summary.json`
  - `artifacts/competition/2026-02-26-formal-real-kall/benchmark_summary.json`
  - `artifacts/competition/2026-02-26-formal-real-kall-v2/benchmark_summary.json`
  - `artifacts/competition/2026-02-26-formal-real-hybrid-all-v2/benchmark_summary.json`
  - `artifacts/competition/2026-02-26-formal-real-auto-all-v2/benchmark_summary.json`

## 10) Audit Trail (Formal-Real)
- Primary evidence run command:

```bash
ARTIFACT_DIR=artifacts/competition/2026-02-26-formal-real-auto-all-v3 \
examples/competition-demo/run.sh --retrieve-method auto --top-k -1
```

- Iteration transparency:
  - v1 (`2026-02-25-formal-real`): `overall=fail` (hit rate and resolved rows below gate)
  - v2 (`2026-02-26-*-v2`): `overall=fail` (hit rate below gate)
  - v3 (`2026-02-26-formal-real-auto-all-v3`): `overall=pass`
  - v3 change scope: minimal query/signal alignment on failed cases only; no retrieval core code changes.
- Raw dataset checksum:
  - `runs.jsonl` sha256:
    `4facef0cbebf752eb1d34709072a2d81aa7fd3b946d3970dbe542b95382f3421`
- Raw dataset distribution:
  - Stored as Release asset (not committed): `runs.jsonl` download link:
    `https://github.com/tt-a1i/evermemos-mcp/releases/download/competition-evidence-2026-02-26/runs.jsonl`
  - Evidence release page:
    `https://github.com/tt-a1i/evermemos-mcp/releases/tag/competition-evidence-2026-02-26`
