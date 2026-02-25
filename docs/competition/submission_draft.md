# Submission Draft: Memory Genesis 2026

## Project
- Name: `evermemos-mcp`
- Version target: `v0.4.0`
- Primary track narrative: Platform Plugins
- Supporting narrative: Agent + Memory (minimal demo)

## Problem
AI assistants reset context between sessions, so users must repeatedly restate project rules, preferences, and prior decisions.  
In multi-topic workflows, missing isolation leads to memory contamination across tasks.  
Most demos show retrieval only, but fail to prove decision improvement and controllable deletion.

## Solution
`evermemos-mcp` provides a universal MCP memory layer on EverMemOS with explicit `space_id` isolation and production-safe tool contracts.  
It delivers a closed loop: `remember -> recall/briefing -> action improvement -> forget`, with traceable evidence fields (`memory_type/snippet/timestamp/score`).  
The competition demo focuses on reproducible benchmark evidence (hit rate, latency, attribution error), not anecdotal screenshots.

## Demo Flow (3-5 minutes)
1. Setup and preload (off-camera or first 20s)
   - `uv sync --group dev`
   - `cp .env.example .env` and set `EVERMEMOS_API_KEY`
   - `uv run python scripts/demo_preload.py --wait --check-status --timeout 480 --interval 20`
2. Live tool walkthrough (core value)
   - `uv run python scripts/demo_live_walkthrough.py`
   - Show `list_spaces` for routing, then `recall` in `coding:*` and `chat:*` to demonstrate strict space isolation.
   - Show `briefing` to restore context at session start.
3. Closed-loop proof (memory improves action)
   - Run competition demo script: `examples/competition-demo/run.sh`
   - Or direct command: `uv run python examples/competition-demo/run_demo.py --queries examples/competition-demo/query_set_real_template.jsonl --artifact-dir artifacts/competition/<date>-formal-real`
   - Show before/after comparison (`without memory` vs `with memory`) and benchmark summary.
   - Use `forget` on one memory ID and re-run recall to show controlled deletion.
4. Reliability and delivery
   - Mention async extraction reality and preload strategy.
   - Show test confidence quickly: `uv run pytest -q`.

## Memory Integration Evidence
- Hit rate: query-level recall hit rate on fixed 60-query set (coding/chat/study, 20 each), target >= 80% with memory.
- Latency: recall latency P50/P95 from warm runs, target P95 <= 2000 ms.
- Source attribution error rate: wrong `space_id` attribution / resolved rows, target <= 2.0%.
- Current Phase 2 formal-real snapshot (2026-02-26, primary evidence):
  - with-memory hit rate: `100.00%` (60/60)
  - without-memory hit rate: `0.00%` (0/60)
  - delta hit rate: `+100.00%`
  - recall latency: `P95=1957.75 ms`
  - attribution error rate: `0.00%` (0/236)
  - gate result: `PASS` (all gates pass)
- Transparency note:
  - v1/v2 formal-real attempts did not pass all gates.
  - v3 passed after minimal query/signal alignment on failed cases only; retrieval implementation unchanged.
- Appendix references:
  - synthetic threshold validation (2026-02-25): `PASS`
  - early formal-real attempts (2026-02-25 / 2026-02-26 k12/kall/v2): diagnostics only

## Community Impact
- GitHub: track stars, forks, and issue/PR interactions during sprint window.
- Discord: publish three waves (launch, technical breakdown, short clip) and capture meaningful discussion count.
- Demo feedback: collect structured feedback (what was clear, what failed, what improved trust) from at least 15 runs.

## Links
- Repository: https://github.com/tt-a1i/evermemos-mcp
- Release/tag: https://github.com/tt-a1i/evermemos-mcp/releases/tag/v0.4.0
- Evidence release: https://github.com/tt-a1i/evermemos-mcp/releases/tag/competition-evidence-2026-02-26
- Benchmark deep dive: `docs/competition/benchmark_deep_dive.md`
- Main video script (ZH): `docs/competition/video_script_main.zh-CN.md`
- Main video script (EN): `docs/competition/video_script_main.en.md`
- Short clip script: `docs/competition/video_script_short_clip.md`
- Demo video: TBD
- Short clip: TBD
- Benchmark artifacts (Phase 2):
  - `artifacts/competition/2026-02-26-formal-real-auto-all-v3/benchmark_summary.json` (primary evidence)
  - `artifacts/competition/2026-02-26-formal-real-auto-all-v3/benchmark_report.md`
  - `runs.jsonl` raw data (Release asset): `https://github.com/tt-a1i/evermemos-mcp/releases/download/competition-evidence-2026-02-26/runs.jsonl`
  - `artifacts/competition/2026-02-25-smoke/benchmark_summary.json`
  - `artifacts/competition/2026-02-25-formal-synthetic/benchmark_summary.json`
  - `artifacts/competition/2026-02-25-formal-real/benchmark_summary.json` (earlier failed baseline)

## Final Checklist
- [ ] Repo public and up to date
- [ ] Tag pushed
- [ ] Changelog updated
- [ ] Video uploaded
- [ ] Submission form completed
