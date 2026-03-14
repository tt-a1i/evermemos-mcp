# Task Plan: Memory Genesis 2026 Submission Sprint

## Goal
Ship a competition-ready submission package for `evermemos-mcp` by 2026-03-15, optimized for scoring on execution quality, memory integration evidence, and community impact.

## Timeline
- Start date: 2026-02-25
- Submission deadline: 2026-03-15
- Safety buffer: 2026-03-13 to 2026-03-15 (bug fixes only, no new features)

## Phases
- [x] Phase 0: Scope freeze and scoring strategy
- [x] Phase 1: Release readiness (`v0.5.6`)
- [x] Phase 2: Benchmark evidence and demo automation
- [ ] Phase 3: Video and submission assets
- [ ] Phase 4: Community rollout and final submission

## Phase Owners, Due Dates, Exit Criteria

| Phase | Owner | Due date | Exit criteria |
| --- | --- | --- | --- |
| Phase 1: Release readiness | Project maintainer | 2026-03-06 | `pyproject` bumped to `0.5.0`; `CHANGELOG.md` merged; release gates pass (`ruff`, `pytest`); tag `v0.5.6` pushed |
| Phase 2: Benchmark + demo | Project maintainer | 2026-03-08 | `docs/06-benchmark.md` complete; benchmark scripts produce reproducible report; `examples/competition-demo` one-command run works |
| Phase 3: Submission assets | Project maintainer | 2026-03-12 | bilingual video script complete; README competition section merged; submission draft complete with links and metrics |
| Phase 4: Community + final submit | Project maintainer | 2026-03-15 | 3 community waves posted; outcome metrics recorded; submission package delivered before deadline |

## Workstreams

### A) Release Workstream
- [x] Bump version through the competition release line to `0.5.0`
- [x] Create `CHANGELOG.md` from recent shipped fixes
- [x] Enforce release gates:
  - [x] `uv run ruff check`
  - [x] `uv run pytest`
  - [ ] 3-minute quickstart smoke test
- [x] Create and push git tag `v0.5.6`

### B) Evidence Workstream
- [x] Add `docs/06-benchmark.md`
- [x] Define metrics and formulas:
  - [x] Recall hit rate
  - [x] Recall latency (P50/P95)
  - [x] Source attribution error rate
- [x] Define sample size and baseline:
  - [x] With memory vs without memory
  - [x] Fixed query set and acceptance threshold
- [x] Automate result generation from demo runs
- [x] Meet metric gates for submission narrative:
  - [x] Recall hit rate >= 80% (with memory, query-level, N >= 60)
  - [x] P95 recall latency <= 2000 ms (warm runs)
  - [x] Source attribution error rate <= 2.0% (resolved rows, N >= 200)

### C) Demo Workstream
- [x] Create `examples/competition-demo/`
- [x] Provide one-command entrypoint (`run.sh` or `Makefile`)
- [x] Include end-to-end flow:
  - [x] remember
  - [x] cross-session recall
  - [x] action improvement step
  - [x] optional briefing/forget
- [x] Export machine-readable report for benchmark docs
  - [x] Output path convention: `artifacts/competition/{date}-<run-label>/`
  - [x] Summary JSON: `artifacts/competition/{date}-<run-label>/benchmark_summary.json`
  - [x] Raw runs JSONL: `artifacts/competition/{date}-<run-label>/runs.jsonl`
  - [x] Rebuild command: `uv run python scripts/competition_eval.py --input artifacts/competition/{date}-<run-label>/runs.jsonl --output artifacts/competition/{date}-<run-label>/benchmark_summary.json`

### D) Submission Workstream
- [x] Upgrade `README.md` with competition-focused section
- [x] Add bilingual video scripts (EN + ZH)
- [x] Add `docs/07-release-checklist.md`
- [x] Finalize `docs/04-submission.md` assets checklist

### E) Community Workstream
- [ ] Define measurable targets:
  - [ ] GitHub stars net increase >= 30 during sprint
  - [ ] Demo feedback count >= 15
  - [ ] Discord meaningful interactions >= 20
- [ ] Wave 1: launch post
- [ ] Wave 2: technical breakdown
- [ ] Wave 3: short demo clip
- [ ] Track outcomes in one table for submission narrative

## Resolved Decisions
1. Primary track narrative: Track 2 (Platform Plugins) as the main line, with a lightweight Track 1-compatible demo as supporting evidence.
2. Benchmark sample size: at least 60 fixed queries for hit rate/latency, and at least 200 resolved rows for attribution error.
3. Community targets by 2026-03-15: stars `+30`, demo feedback `>=15`, Discord meaningful interactions `>=20`.
4. Buffer policy: 2026-03-13 to 2026-03-15 is bug-fix only, no net-new features.

## Decisions Made
- Main scoring strategy: optimize for Track 2 (Platform Plugins), with a lightweight Track 1-compatible demo storyline.
- Delivery rule: no net-new core features after entering buffer window.
- Documentation-first packaging: lock story and evidence format before video recording.

## Errors Encountered
- `git fetch upstream` fails in this repo because no `upstream` remote is configured. Current remote setup uses `origin` only.

## Status
**Currently in Phase 3** - Phase 2 gates are met on formal-real run `artifacts/competition/2026-02-26-formal-real-auto-all-v3/` (`overall=pass`, all four gate checks pass).
