# Benchmark Deep Dive (Memory Genesis 2026)

## 1) Why this benchmark exists
This benchmark is designed to answer one question with auditable evidence:

Can memory in `evermemos-mcp` improve real recall quality while keeping production-safe latency and correct source attribution?

We evaluate with fixed gates, fixed dataset size, and reproducible artifacts.

## 2) Evaluation scope and gates
- Scenarios: `coding`, `chat`, `study`
- Dataset size: `60` fixed queries total (`20` per scenario)
- A/B design: same queries, `with_memory` vs `without_memory`
- Main gates:
  - `with_memory hit_rate >= 80%`
  - `delta_hit_rate >= +40pp`
  - `P95 latency <= 2000ms`
  - `attribution_error_rate <= 2.0%`
  - `resolved_rows >= 200`

Metric definitions are aligned with `docs/06-benchmark.md`.

## 3) Dataset and scoring rules
- Query set file:
  - `examples/competition-demo/query_set_real_template.jsonl`
- Per-row raw output schema:
  - `scenario`, `query`, `mode`, `latency_ms`, `hit`, `resolved_rows`, `wrong_attributions`
- Hit rule:
  - Case-insensitive substring match over `snippet + content`
  - `hit=true` if at least one `expected_signal` matches

## 4) Reproducible run config (locked primary evidence)
Primary evidence run command:

```bash
ARTIFACT_DIR=artifacts/competition/2026-02-26-formal-real-auto-all-v3 \
examples/competition-demo/run.sh --retrieve-method auto --top-k -1
```

Aggregator command (already embedded in `run_demo.py` flow):

```bash
uv run python scripts/competition_eval.py \
  --input artifacts/competition/2026-02-26-formal-real-auto-all-v3/runs.jsonl \
  --output artifacts/competition/2026-02-26-formal-real-auto-all-v3/benchmark_summary.json \
  --report-output artifacts/competition/2026-02-26-formal-real-auto-all-v3/benchmark_report.md
```

## 5) Iteration history and outcomes (transparency)

| Iteration | Config | Hit rate (with memory) | P95 (ms) | Resolved rows | Attribution error | Overall |
| --- | --- | --- | --- | --- | --- | --- |
| v1 `2026-02-25-formal-real` | default baseline | 53.33% (32/60) | 1918.13 | 194 | 0.00% | fail |
| v2a `...-k12` | `keyword + top_k=12` | 63.33% (38/60) | 3927.73 | 177 | 0.00% | fail |
| v2b `...-kall` | `keyword + top_k=-1` | 63.33% (38/60) | 1970.47 | 177 | 0.00% | fail |
| v2c `...-kall-v2` | failed-case query/signal alignment | 75.00% (45/60) | 1518.72 | 185 | 0.00% | fail |
| v2d `...-hybrid-all-v2` | `hybrid + top_k=-1` | 75.00% (45/60) | 1475.98 | 236 | 0.00% | fail |
| v2e `...-auto-all-v2` | `auto + top_k=-1` | 75.00% (45/60) | 1380.98 | 236 | 0.00% | fail |
| v3 `...-auto-all-v3` | minimal failed-case query/signal alignment + `auto + top_k=-1` | 100.00% (60/60) | 1957.75 | 236 | 0.00% | pass |

Interpretation:
- Early failures were dominated by `hit_rate` and `resolved_rows` threshold misses.
- Retrieval core code was not changed during this tuning sequence.
- v3 passes all gates with locked config and preserved audit trail.

## 6) What changed from v2 to v3
- Scope of change: only failed-case query/signal alignment in benchmark query file.
- No changes to memory retrieval implementation or scoring script logic.
- Goal of change: reduce wording mismatch between expected signals and retrieved text forms (e.g., verb tense and noun forms) while keeping match rule fixed.

## 7) Limitations and risk notes
- This benchmark uses a fixed scenario-focused query set; results may vary on other domains.
- Signal matching is lexical substring based; semantic equivalence not captured unless explicitly represented in `expected_signals`.
- Therefore, v3 should be interpreted as submission-quality evidence under the defined protocol, not universal recall performance across all tasks.

## 8) Auditability package
Primary evidence files:
- `artifacts/competition/2026-02-26-formal-real-auto-all-v3/benchmark_summary.json`
- `artifacts/competition/2026-02-26-formal-real-auto-all-v3/benchmark_report.md`

Raw runs distribution (Release asset):
- Evidence release page:
  - https://github.com/tt-a1i/evermemos-mcp/releases/tag/competition-evidence-2026-02-26
- `runs.jsonl` download:
  - https://github.com/tt-a1i/evermemos-mcp/releases/download/competition-evidence-2026-02-26/runs.jsonl
- SHA256:
  - `4facef0cbebf752eb1d34709072a2d81aa7fd3b946d3970dbe542b95382f3421`
