# Submission Checklist (Phase 5)

[English](04-submission.md) | [Chinese](04-submission.zh-CN.md)

## 1. Repository Readiness
- [x] README (setup, configuration, tools, demo workflow)
- [x] Requirements doc: `docs/01-requirements.md`
- [x] Architecture doc: `docs/02-architecture.md`
- [x] Demo playbook: `docs/03-demo-playbook.md`
- [x] Runnable entrypoint: `evermemos-mcp`
- [x] Tests passing: `uv run pytest`

## 2. Video Checklist (3-5 min)
- [ ] Script finalized: `docs/competition/video_script_main.en.md` / `docs/competition/video_script_main.zh-CN.md`
- [ ] Short clip script finalized: `docs/competition/video_script_short_clip.md`
- [ ] Explain pain point: context loss across sessions
- [ ] Show `list_spaces` routing
- [ ] Show citation fields in `recall` (`timestamp/snippet/type/score`)
- [ ] Show context restoration via `briefing`
- [ ] Show controlled delete via `forget`
- [ ] Clearly state Cloud async extraction and preload strategy

## 3. Suggested Submission Structure
1. Problem
2. Solution
3. Why MCP + EverMemOS
4. Live capabilities (6 tools)
5. Demo highlights
6. Future roadmap

## 4. Reusable Demo Talking Points
- "We use `space_id` as the primary isolation key to prevent context leakage across tasks."
- "Writes are queued on Cloud, so we preload memories before live retrieval demos."
- "Recall and briefing return traceable evidence fields, not opaque summaries."

## 5. AI Disclosure for Open Source PRs
Keep this exact block in PR descriptions:

```md
## AI Assistance Disclosure

I used Codex to review the changes, sanity-check the implementation against existing patterns, and help spot potential edge cases.
```

## 6. Final Verification Before Release

```bash
uv run pytest
uv run python scripts/demo_preload.py --wait --check-status --timeout 480 --interval 20
uv run python scripts/demo_live_walkthrough.py
```
