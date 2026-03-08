# Requirements Draft (V0)

[English](01-requirements.md) | [Chinese](01-requirements.zh-CN.md)

## 1) Product Goal
Provide long-term memory for MCP-compatible AI clients so assistants can keep context across sessions.

The launch focus remains developer tools (Claude Code/Cursor/Cline), while keeping architecture generic enough for chat-first clients such as Cherry Studio.

Principle: broad positioning as a universal memory layer, with a focused demo in 2-3 high-value scenarios.

## 2) Core Problem
Session resets break user experience:
- Preferences, constraints, decisions, and context are forgotten
- Past fixes and conclusions are lost
- Conversations are not continuous
- Users repeat background information in every session

## 3) Target Users
- Primary (V1): developers who frequently use AI coding tools
- Secondary (V1.1): knowledge workers using Cherry Studio or similar AI chat clients
- Shared need: cross-session continuity with controllable memory (query/delete/isolate)

## 4) Value Proposition
- Continue context in new sessions instead of starting from zero
- Avoid cross-topic contamination by isolating memories with `space_id`
- Reduce risk through retrievable, deletable, auditable memory

## 5) Scope
### In Scope (V1)
- MCP tools: `list_spaces`, `remember`, `request_status`, `recall`, `briefing`, `forget`, `fetch_history`
- Memory scope isolation by `space_id` (required); `project_id` is only one mapping for coding scenarios
- EverMemOS API integration for store/status/search/delete
- Cloud-only data strategy (no local persistence)
- Minimal safety via explicit deletion (`forget`)

### Out of Scope (V1)
- Visual admin dashboard
- Automated sensitive-data detection/redaction engine
- Complex permission model (multi-tenant RBAC)

## 6) Key User Stories (V1)
1. As a developer, I want AI to remember project conventions so I do not re-explain in new sessions.
2. As a developer, I want to retrieve past decisions by query to resume interrupted work quickly.
3. As a developer, I want a project briefing at session start to restore context immediately.
4. As a developer, I want to remove wrong or sensitive memories safely.
5. As a chat user, I want topic-level isolation via `space_id`.
6. As a learner, I want AI to remember prior understanding and blind spots in a study space.

## 7) V1 Acceptance Criteria
- `list_spaces` returns routable metadata: `space_id`, `description`, `memory_count`
- After `remember`, `recall` can retrieve related memories under the same `space_id`
- `fetch_history` supports paginated timeline retrieval by `memory_type`
- Cross-space retrieval does not leak memory across `space_id`
- `briefing` returns explainable output for both empty and non-empty spaces
- `forget` is exposed as a best-effort delete path with explicit pre/post verification guidance

## 8) Demo Success Criteria
- Clear comparison: without memory vs with memory
- Show 2-3 scenario switches (coding / daily chat / study)
- Show isolation between Space A and Space B
- Show controlled deletion with timeline verification and an honest Cloud-limit fallback narrative

## 9) Non-Functional Requirements
- Performance target: typical retrieval under 2 seconds (local benchmark target)
- Reliability: explicit errors when EverMemOS is unavailable
- Portability: switchable local/Cloud EverMemOS endpoints

## 10) Version Plan
### V1 (Hackathon Submission)
- Seven MCP tools (including `request_status`) + `space_id` isolation + reproducible demo

### V1.1 (Enhancements)
- Automatic session-summary ingestion
- Team mode (`group` scope)

## 11) Frozen Decisions
1. **`space_id` naming**: `<domain>:<slug>` (for example: `coding:my-app`, `chat:daily`, `study:ml`)
2. **Routing**: AI should prefer explicit `space_id` or `list_spaces` discovery; when omitted, a default space may be inferred from `EVERMEMOS_DEFAULT_SPACE` or the git remote.
3. **Data placement**: Cloud-only for both space metadata and memory bodies
4. **Citations**: required in V1 (at least timestamp + snippet)
