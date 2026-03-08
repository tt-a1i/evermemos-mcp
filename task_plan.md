# Task Plan: evermemos-mcp (Universal Memory MCP Server)

[English](task_plan.md) | [Chinese](task_plan.zh-CN.md)

## Goal
Build an MCP server that provides long-term memory for MCP-compatible AI clients through EverMemOS, and submit it to Memory Genesis 2026 (Track 2: Platform Plugin).

## Phases
- [x] Phase 1: requirements and product design
- [x] Phase 2: architecture and technical design
- [x] Phase 3: core implementation
- [x] Phase 4: demo preparation and testing
- [x] Phase 5: docs and submission materials

## Key Requirement Questions
1. Which user scenarios are most valuable for cross-session memory?
2. Which MCP tools should be exposed, and at what granularity?
3. How should memory scope be designed (`space_id`, user, global)?
4. Which EverMemOS APIs and memory types are required?
5. What is in MVP scope and what is optional?
6. How can core value be demonstrated clearly in 3-5 minutes?

## Decisions
- Track: Track 2 (Platform Plugin)
- Product: universal Memory MCP server (`evermemos-mcp`)
- V1 tool set: `list_spaces`, `remember`, `request_status`, `recall`, `briefing`, `forget`, `fetch_history`
- Isolation model: generic `space_id`
- Positioning: universal platform layer, focused demo (coding/chat/study)
- Transport: `stdio` by default
- Data strategy: Cloud-first, no local persistence
- Routing: explicit `space_id` by default, with fallback discovery via `list_spaces` and optional default-space auto-detection from env/git

## Known Constraints
- Cloud extraction is async (usually 2-5 minutes)
- `remember` followed by immediate `recall` may return empty results
- Some upstream configurations have conversation-meta constraints

## Milestone Notes

### Phase 3.1 Validation
- Cloud v0 API verified: auth, write, fetch, search
- `pending_messages` confirmed useful for UX hints
- `flush=true` does not speed up Cloud extraction
- Demo must use preloaded memory data

### Phase 3.2 Delivery
- Implemented `evermemos_client`, `space_catalog_service`, and config wiring
- Added isolation mapping helpers (`to_group_id` / `from_group_id`)
- Added tests for auth, response handling, and recovery paths

### Phase 3.3 Delivery
- Implemented all 7 MCP tools end-to-end
- Added structured error semantics and citation fields
- Added smoke coverage and expanded unit tests

## Current Status
Core implementation is complete and production-hardening iterations are in progress.
