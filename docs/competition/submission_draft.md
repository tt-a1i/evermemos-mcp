# Submission Draft: Memory Genesis 2026

## Project
- Name: `evermemos-mcp`
- Version target: `v0.5.6`
- Primary track narrative: Platform Plugins
- Supporting narrative: Agent + Memory (minimal demo)

## Problem
AI assistants reset context between sessions, so users must repeatedly restate project rules, preferences, and prior decisions.  
In multi-topic workflows, missing isolation leads to memory contamination across tasks.  
Most demos show retrieval only, but fail to prove decision improvement and controllable deletion.

## Solution
`evermemos-mcp` provides a universal MCP memory layer on EverMemOS with explicit `space_id` isolation, optional default-space auto-detection, and production-safe tool contracts.  
It delivers a closed loop: `remember -> request_status -> recall/briefing -> fetch_history/forget`, with traceable evidence fields (`memory_type/snippet/timestamp/score`).  
The competition demo focuses on reproducible benchmark evidence (hit rate, latency, attribution error), not anecdotal screenshots.
Current release line also includes `uvx` installation, Smithery registry config, and auto-memory prompt templates for Claude Code / Cursor / Cline.

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
   - Use `fetch_history` to confirm one memory ID, call `forget`, then re-check with `fetch_history` before `recall` to show controlled deletion honestly.
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
  - current lifecycle appendix generator status (2026-03-07): implementation complete; latest live rerun under `artifacts/competition/2026-03-07-lifecycle-appendix-dec0612e/` reached full searchability (`3/3`) and passed isolation (`0/6` leaked rows), while forget remained `WARN` because the target memory still remained recallable after delete

## Community Impact
- GitHub: track stars, forks, and issue/PR interactions during sprint window.
- Discord: publish three waves (launch, technical breakdown, short clip) and capture meaningful discussion count.
- Demo feedback: collect structured feedback (what was clear, what failed, what improved trust) from at least 15 runs.

## Submission Form Answers
- Project name: `evermemos-mcp`
- Primary track: `Track 2: Platform Plugins`
- One-line summary: `An MCP memory layer on EverMemOS that gives AI coding assistants persistent, isolated, cross-session memory with traceable recall evidence.`
- Problem statement: `AI assistants lose context between sessions, forcing users to restate architecture decisions, preferences, and prior work; without strict isolation, memories also bleed across topics.`
- Solution summary: `evermemos-mcp provides seven production-oriented MCP tools on top of EverMemOS Cloud: list_spaces, remember, request_status, recall, briefing, forget, and fetch_history. It restores context across sessions, keeps memories isolated by space_id, and returns traceable evidence fields instead of opaque summaries.`
- Demo flow: `Preload three spaces, show list_spaces routing, run recall + briefing for context restoration, demonstrate before/after benchmark evidence, then show targeted delete via forget and note the current Cloud limitation if the memory remains recallable.`
- Why this matters: `It upgrades MCP clients from stateless chat tools into workflows that can preserve project memory safely over time.`
- Primary evidence: `artifacts/competition/2026-02-26-formal-real-auto-all-v3/benchmark_summary.json` with `100%` with-memory hit rate, `P95=1957.75 ms`, and `0%` attribution error.
- Supplemental lifecycle evidence status: `scripts/competition_lifecycle_appendix.py` is implemented and now produces live appendix artifacts with stage logs. The latest rerun captured `9/9` remember acknowledgements, `3/3` searchable spaces, and `PASS` isolation evidence; only forget remains `WARN` in the current Cloud deployment.`
- Repository URL: `https://github.com/tt-a1i/evermemos-mcp`
- Release URL: `https://github.com/tt-a1i/evermemos-mcp/releases/tag/v0.5.6`
- Evidence release URL: `https://github.com/tt-a1i/evermemos-mcp/releases/tag/competition-evidence-2026-02-26`
- PyPI URL: `https://pypi.org/project/evermemos-mcp/`

## Links
- Repository: https://github.com/tt-a1i/evermemos-mcp
- Release/tag: https://github.com/tt-a1i/evermemos-mcp/releases/tag/v0.5.6
- PyPI package: https://pypi.org/project/evermemos-mcp/
- Smithery config: `smithery.yaml`
- Auto-memory prompts: `docs/auto-memory-prompt.md`
- Evidence release: https://github.com/tt-a1i/evermemos-mcp/releases/tag/competition-evidence-2026-02-26
- Benchmark deep dive: `docs/competition/benchmark_deep_dive.md`
- Lifecycle appendix (write/read/delete): `docs/competition/benchmark_deep_dive.md` Section 10
- Latest appendix artifact: `artifacts/competition/2026-03-07-lifecycle-appendix-dec0612e/appendix_notes.md`
- Main video script (ZH): `docs/competition/video_script_main.zh-CN.md`
- Main video script (EN): `docs/competition/video_script_main.en.md`
- Short clip script: `docs/competition/video_script_short_clip.md`
- Demo video: pending final recording/upload
- Short clip: pending final recording/upload
- Benchmark artifacts (Phase 2):
  - `artifacts/competition/2026-02-26-formal-real-auto-all-v3/benchmark_summary.json` (primary evidence)
  - `artifacts/competition/2026-02-26-formal-real-auto-all-v3/benchmark_report.md`
  - `runs.jsonl` raw data (Release asset): `https://github.com/tt-a1i/evermemos-mcp/releases/download/competition-evidence-2026-02-26/runs.jsonl`
  - `artifacts/competition/2026-02-25-smoke/benchmark_summary.json`
  - `artifacts/competition/2026-02-25-formal-synthetic/benchmark_summary.json`
  - `artifacts/competition/2026-02-25-formal-real/benchmark_summary.json` (earlier failed baseline)

## Final Checklist
- [ ] Repo public and up to date
- [x] Tag pushed
- [x] Changelog updated
- [ ] Video uploaded
- [ ] Submission form completed
