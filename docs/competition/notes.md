# Notes: Memory Genesis 2026 Sprint

## Source Inventory

### Competition page
- URL: https://luma.com/n88icl03?tk=0kqlJJ
- Notes:
  - Scoring dimensions include execution quality, memory integration, and community impact.
  - Submission deadline is 2026-03-15.

### Local project status
- Repo: `evermemos-mcp`
- Current test baseline:
  - `ruff check`: pass
  - `pytest`: 188 passed, 1 skipped

## Research Log
- 2026-02-25:
  - Competition prep switched from stability iteration to submission asset production.
  - Main narrative frozen as Track 2 (Platform Plugins), with a lightweight Track 1-compatible agent demo.
  - Benchmark-first rule adopted: metrics must be reproducible from scripts, not manual screenshots.
- 2026-02-26:
  - Formal-real benchmark reached full gate pass at `artifacts/competition/2026-02-26-formal-real-auto-all-v3/`.
  - Iteration trail kept for audit: v1/v2 failed, v3 passed after minimal query/signal alignment on failed cases.
  - Raw `runs.jsonl` is distributed via Release asset (repo keeps summary/report only).

## Metrics Design Notes

### Recall hit rate
- Definition:
  - Query-level success rate. A query is a "hit" when `recall` returns at least one result containing an expected signal for that scenario.
- Formula:
  - `hit_rate = hit_queries / total_queries`
- Dataset size:
  - `N = 60` queries minimum (coding/chat/study, 20 each), fixed query set committed in demo fixtures.
- Baseline:
  - Compare `with memory` vs `without memory` on the same query set.
  - Submission target: `with memory >= 80%`, and improvement over baseline `>= +40 percentage points`.

### Recall latency
- Definition:
  - End-to-end `recall` response time measured at client side (request start to parsed response).
- Formula:
  - `latency_ms = t_response - t_request`
  - Report `P50` and `P95` across all successful query runs.
- Dataset size:
  - Same 60-query set, 3 warm runs per query (cold start excluded from headline number).
- Baseline:
  - Baseline is current main branch behavior before competition-demo tuning.
  - Submission target: `P95 <= 2000 ms` in warm runs.

### Source attribution error rate
- Definition:
  - Error rate of wrong `space_id` attribution among rows where source recovery resolves a concrete `space_id`.
- Formula:
  - `attribution_error_rate = wrong_attributions / resolved_rows`
- Dataset size:
  - Minimum `200` resolved rows aggregated from multi-space benchmark scenarios.
- Baseline:
  - Baseline is current source-recovery behavior at sprint start.
  - Submission target: `<= 2.0%`.

## Community Tracking Notes
- Targets:
  - GitHub stars net increase >= 30
  - Demo feedback count >= 15
  - Discord meaningful interactions >= 20
- Wave 1 (launch post):
  - Date:
  - Channel:
  - URL:
  - Outcome:
- Wave 2 (technical breakdown):
  - Date:
  - Channel:
  - URL:
  - Outcome:
- Wave 3 (short demo clip):
  - Date:
  - Channel:
  - URL:
  - Outcome:

## Evidence Release
- Tag: `competition-evidence-2026-02-26`
- Release URL:
  - `https://github.com/tt-a1i/evermemos-mcp/releases/tag/competition-evidence-2026-02-26`
- Raw runs asset URL (`runs.jsonl`):
  - `https://github.com/tt-a1i/evermemos-mcp/releases/download/competition-evidence-2026-02-26/runs.jsonl`
- Raw runs sha256:
  - `4facef0cbebf752eb1d34709072a2d81aa7fd3b946d3970dbe542b95382f3421`

## Risks and Mitigations
- Risk: Cloud API latency spikes or transient errors during recording/demo.
  - Mitigation: preload data ahead of recording, cache stable demo outputs under `artifacts/competition/`, and keep one offline fallback clip.
- Risk: community targets are not reached by deadline.
  - Mitigation: pre-schedule 3 publishing waves, prepare bilingual content in advance, and reuse short-clip assets across channels.
- Risk: video delivery slips close to submission deadline.
  - Mitigation: lock script first, finish primary recording before 2026-03-12, reserve 2026-03-13 to 2026-03-15 for edits/bug fixes only.
