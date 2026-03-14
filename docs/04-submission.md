# Submission Checklist (Phase 5)

[English](04-submission.md) | [Chinese](04-submission.zh-CN.md)

## 1. Repository Readiness
- [x] README (setup, configuration, tools, demo workflow)
- [x] Requirements doc: `docs/01-requirements.md`
- [x] Architecture doc: `docs/02-architecture.md`
- [x] Demo playbook: `docs/03-demo-playbook.md`
- [x] Runnable entrypoint: `evermemos-mcp`
- [x] Tests passing: `uv run pytest`

## 1.1 Non-video Submission Assets
- [x] Latest package metadata aligned to `v0.5.6`
- [x] Latest release/tag available: `v0.5.6`
- [x] Evidence release available: `competition-evidence-2026-02-26`
- [x] Benchmark deep dive: `docs/competition/benchmark_deep_dive.md`
- [x] Lifecycle appendix generator: `scripts/competition_lifecycle_appendix.py`
- [x] Final handoff checklist: `docs/competition/final_submission_30s_checklist.md`

## 2. Video Checklist (3-5 min)
- [ ] Script finalized: `docs/competition/video_script_main.en.md` / `docs/competition/video_script_main.zh-CN.md`
- [ ] Short clip script finalized: `docs/competition/video_script_short_clip.md`
- [ ] Explain pain point: context loss across sessions
- [ ] Show `list_spaces` routing
- [ ] Explain `request_status` as the write-after verification path
- [ ] Show citation fields in `recall` (`timestamp/snippet/type/score`)
- [ ] Show context restoration via `briefing`
- [ ] Show `fetch_history` for timeline or delete verification
- [ ] Show targeted delete via `forget` (or state current Cloud limitation if delete remains recallable)
- [ ] Clearly state Cloud async extraction and preload strategy

## 3. Suggested Submission Structure
1. Problem
2. Solution
3. Why MCP + EverMemOS
4. Live capabilities (7 tools)
5. Demo highlights
6. Future roadmap

## 4. Reusable Demo Talking Points
- "We use `space_id` as the primary isolation key to prevent context leakage across tasks."
- "Writes are queued on Cloud, so we preload memories before live retrieval demos."
- "`request_status` is the write-after check before we claim a memory is searchable."
- "Recall and briefing return traceable evidence fields, not opaque summaries."

## 5. AI Disclosure for Open Source PRs
Keep this exact block in PR descriptions:

```md
## AI Assistance Disclosure

I used Codex to review the changes, sanity-check the implementation against existing patterns, and help spot potential edge cases.
```

## 6. Final Verification Before Release

```bash
uv run ruff check
uv run pytest
uv run python scripts/demo_preload.py --wait --check-status --timeout 480 --interval 20
uv run python scripts/demo_live_walkthrough.py
uv run python scripts/competition_lifecycle_appendix.py
```

Notes:
- The two live EverMemOS commands above require a valid `EVERMEMOS_API_KEY`.
- `scripts/competition_lifecycle_appendix.py` writes failure artifacts (`appendix_notes.md`, `appendix_results.json`, `raw_logs.txt`) even when auth or environment validation fails, so blocked runs remain auditable.
