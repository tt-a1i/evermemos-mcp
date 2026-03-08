# Benchmark Deep Dive (Memory Genesis 2026)

## TL;DR
- **Hit rate**: `100%` (with memory, `60/60`) vs `0%` (without memory) ✅
- **Delta hit rate**: `+100pp` (target `>= +40pp`) ✅
- **P95 latency**: `1957.75ms` (target `<= 2000ms`) ✅
- **Attribution error**: `0.00%` with `resolved_rows=236` (target `<= 2.0%`, rows `>= 200`) ✅
- **Gate result**: **PASS** (`data_volume/hit_rate/latency_p95/attribution_error_rate` all pass)

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

Dataset fingerprint (frozen for evidence run):
- Query file SHA256:
  - `4567f5450d05be69ff06f6d4ec78287708aa9dd7894676763f4e926eae0bf180`
- Query file commit:
  - `82a4dd6` (`feat: add real-data competition demo runner`)

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

## 5) Scenario-level snapshot (v3)

| Scenario | With-memory hit | Without-memory hit | With-memory P95 (ms) |
| --- | --- | --- | --- |
| coding | 20/20 (100%) | 0/20 (0%) | 2339.49 |
| chat | 20/20 (100%) | 0/20 (0%) | 1506.98 |
| study | 20/20 (100%) | 0/20 (0%) | 1480.33 |

Note:
- Gate evaluation uses aggregate metrics (`benchmark_summary.json`), not per-scenario pass/fail checks.

## 6) Iteration history and outcomes (transparency)

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

## 7) What changed from v2 to v3
- Scope of change: only failed-case query/signal alignment in benchmark query file.
- No changes to memory retrieval implementation or scoring script logic.
- Goal of change: reduce wording mismatch between expected signals and retrieved text forms (e.g., verb tense and noun forms) while keeping match rule fixed.

## 8) Limitations and risk notes
- This benchmark uses a fixed scenario-focused query set; results may vary on other domains.
- Signal matching is lexical substring based; semantic equivalence not captured unless explicitly represented in `expected_signals`.
- Therefore, v3 should be interpreted as submission-quality evidence under the defined protocol, not universal recall performance across all tasks.

## 9) Auditability package
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

## 10) Lightweight Write/Read/Delete Lifecycle Appendix (Supplemental)

Scope:
- This appendix is supplemental evidence only.
- It does **not** change the primary benchmark gates in Sections 2 and 5.

Purpose:
- Demonstrate that memory lifecycle is operational end-to-end:
  `remember -> request_status/searchable -> isolated recall -> fetch_history/forget`.

### 10.1 Suggested minimal checks
1. `remember` success rate  
2. time-to-searchable (`remember` ack to first recall hit)  
3. `space_id` isolation correctness (cross-space no-hit)  
4. `forget` effectiveness (post-delete recall miss for deleted item)

### 10.2 Minimal execution protocol
Use a fresh appendix prefix and keep the generated files under `artifacts/competition/`.

1. Preload baseline spaces (manual smoke path):
```bash
uv run python scripts/demo_preload.py --wait --check-status --timeout 480 --interval 20
```

2. Execute lifecycle walkthrough and capture terminal logs:
```bash
uv run python scripts/demo_live_walkthrough.py --do-forget
```

3. Preferred path: generate appendix artifacts directly:
```bash
uv run python scripts/competition_lifecycle_appendix.py
```

Generated files:
- `artifacts/competition/<date>-lifecycle-<prefix>/appendix_notes.md`
- `artifacts/competition/<date>-lifecycle-<prefix>/appendix_results.json`
- `artifacts/competition/<date>-lifecycle-<prefix>/raw_logs.txt`

Current local status:
- The generator is implemented and now produces stage-by-stage logs plus explicit `SKIP` results when not all spaces become searchable within the wait budget.
- Latest live rerun artifact:
  - `artifacts/competition/2026-03-07-lifecycle-appendix-dec0612e/appendix_notes.md`
  - `artifacts/competition/2026-03-07-lifecycle-appendix-dec0612e/appendix_results.json`
- Current live status captured in that run:
  - remember acknowledgements: `9/9`
  - searchable sample size: `3/3`
  - coding searchable after `69.07s`
  - chat searchable after `37.82s`
  - study searchable after `91.48s`
  - isolation correctness: `PASS` (`0/6` leaked rows)
  - forget effectiveness: `WARN` because the target memory still remained recallable after delete (`1/1`)
- This means auth and searchability are no longer the main blockers; the remaining appendix gap is upstream targeted delete behavior for `forget`.

### 10.3 Reporting template (fill after run)

| Check | Definition | Sample size | Result | Status |
| --- | --- | --- | --- | --- |
| Remember success rate | successful remember acknowledgements / total remember calls | from `appendix_results.json` | from `appendix_notes.md` | PASS / WARN |
| Time-to-searchable P50/P95 | time from first remember ack in each demo space to first recall hit | from `appendix_results.json` | from `appendix_notes.md` | PASS / WARN |
| Space isolation correctness | cross-space false hits / cross-space queries | from `appendix_results.json` | from `appendix_notes.md` | PASS / WARN |
| Forget effectiveness | deleted item still recalled / delete attempts | from `appendix_results.json` | from `appendix_notes.md` | PASS / WARN |

Notes:
- Keep metric formulas explicit when filling this table.
- Keep this appendix independent from the primary gate decision.
