# Demo Playbook (Phase 4)

[English](03-demo-playbook.md) | [Chinese](03-demo-playbook.zh-CN.md)

This guide is for the 3-5 minute Memory Genesis 2026 submission demo video.

## 1. Demo Objectives
- Show cross-session memory restoration
- Show `space_id` isolation across coding/chat/study
- Show traceable citations (`timestamp + snippet + type + score`)
- Show timeline verification via `fetch_history`
- Show best-effort deletion via `forget`

## 2. Core Principles
- EverMemOS Cloud v0 writes are async (`202 queued`) before retrieval becomes available
- Avoid live "write then immediate recall" in the video
- Recommended flow: **preload -> wait for extraction -> live recall/briefing**

## 3. Pre-demo Setup
1. Configure Cloud environment variables (`.env`)
2. Run preload script (recommended 5-10 minutes before recording)
3. Verify each of the three spaces has at least one retrievable item

```bash
uv run python scripts/demo_preload.py --wait --check-status --timeout 480 --interval 20
```

## 4. Suggested 3-5 Minute Script

### Part A (30-45s): Problem and Positioning
- AI clients forget context in new sessions
- This MCP layer provides durable memory without modifying client internals

### Part B (45-60s): Space Discovery and Routing
1. Call `list_spaces`
2. Show `coding:*`, `chat:*`, and `study:*` spaces
3. Explain that `space_id` is the primary isolation key

### Part C (60-90s): Live Recall
1. `recall(query="FastAPI PostgreSQL", space_id="coding:demo-app")`
2. Highlight `memory_type/snippet/timestamp/score`
3. Switch to `chat:daily` and run recall again to prove isolation

### Part D (45-60s): Live Briefing
1. `briefing(space_id="coding:demo-app")`
2. Show `summary + highlights[]`
3. Explain layered sources (`profile/episodic/event_log/foresight`)

### Part E (30-45s): Controlled Forget
1. Use `fetch_history` first to show the target `memory_id` in a stable timeline view
2. Call `forget(memory_ids=[...])`
3. Re-run `fetch_history` before `recall` to verify whether the target disappeared
4. If Cloud delete returns `ok` but the target remains visible, present it as a current Cloud limitation rather than an MCP routing failure

## 5. Demo Command Checklist

```bash
# Preload
uv run python scripts/demo_preload.py --wait --check-status

# Live walkthrough (list/recall/briefing, optional forget)
uv run python scripts/demo_live_walkthrough.py
```

## 6. Common Issues
- Recall is empty with `pending_count > 0`: extraction is still queued; check `recall.lifecycle` and do not treat provisional/fallback answers as searchable yet
- `remember` returns `request_status` with `found=false`: status may not be indexed yet; queued write is still valid
- Cloud jitter: rerun recall or show `UPSTREAM_UNAVAILABLE` error semantics in the demo
- Incomplete `list_spaces`: rerun preload before listing spaces
- `forget` returns `ok` but the target still recalls: current Cloud targeted delete may not honor the selected memory ID; treat as an upstream limitation and use appendix evidence instead of forcing a live delete pass

## 7. Scoring Mapping
- Innovation: universal MCP memory layer + `space_id` routing
- Technical Depth: 7-tool loop + explicit error semantics + citation fields
- Consumer Value: continuity across sessions + timeline/retrieval/verify controls
