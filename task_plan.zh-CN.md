# Task Plan: evermemos-mcp — Universal Memory MCP Server

[English](task_plan.md) | [简体中文](task_plan.zh-CN.md)

## Goal
Build an MCP Server that gives MCP-compatible AI clients long-term memory via EverMemOS, and submit to Memory Genesis 2026 hackathon (Track 2: Platform Plugin).

## Phases
- [x] Phase 1: Requirements discussion & product design
- [x] Phase 2: Technical design & architecture
- [ ] Phase 3: Core implementation
- [ ] Phase 4: Demo & testing
- [ ] Phase 5: Documentation & submission materials (README, video script)

## Key Questions (Requirements)
1. 核心用户场景是什么？哪些跨会话记忆最有价值？
2. MCP Tools 该暴露哪些？粒度如何？
3. 记忆的 scope 怎么设计？per-project / per-user / global？
4. 与 EverMemOS 的对接方式：用哪些 API？需要哪些 memory types？
5. MVP 的边界在哪？18 天内哪些是必须的，哪些是加分项？
6. Demo 场景怎么设计？如何 3-5 分钟展示核心价值？

## Decisions Made
- 赛道方向：Track 2（Platform Plugin）
- 产品方向：Memory MCP Server（暂定名：evermemos-mcp）
- 核心价值：为 MCP 客户端提供跨 session 的长期记忆（开发者工具优先）
- V1 工具集：list_spaces / remember / recall / briefing / forget
- Scope 策略：先覆盖个人开发者场景，团队场景作为扩展
- 隔离模型：采用通用 `space_id`（`project_id` 是其中一种场景映射）
- 产品策略：定位泛化（universal layer），Demo 聚焦（coding + chat + study）
- 风险优先级：先验证 EverMemOS 边界检测行为，再实现工具闭环
- V1 transport：默认 stdio
- `briefing` 策略：profile + episodic_memory + foresight 分层组装
- 路由策略：AI 通过 `list_spaces` + description 选择 `space_id`
- 数据策略：Cloud-only（不做本地持久化）

## Errors Encountered
- conversation-meta v0 rejects `scene` for group-level config (must omit or use global)
- Cloud extraction is async ~2-5 min (not seconds) — remember→immediate recall will be empty

## Phase 3.1 Validation Conclusions
- Cloud v0 API works: auth ✅, write ✅ (202 queued), fetch ✅, search ✅
- Extraction timing: ~2-5 min on Cloud (critical for demo design)
- Memory types confirmed: episodic_memory, profile, event_log all extracted
- Isolation via group_id confirmed working
- Search returns pending_messages (useful for UX hint)
- `flush=true` does NOT accelerate Cloud processing
- Demo strategy: must pre-load memories, not live write→read

## Phase 3.2 — evermemos_client + space_catalog_service ✅
- `evermemos_client.py`: add_message, fetch_memories, search_memories, delete_memories
- `space_catalog_service.py`: register_space, list_spaces, ensure_space, to_group_id/from_group_id
- `config.py`: updated with API_VERSION, USER_ID, DEFAULT_SPACE, CATALOG_GROUP_ID
- Smoke test passed against Cloud v0 ✅
- API response field mapping confirmed:
  - episodic_memory: `id`, `summary`, `timestamp`, `keywords`, `subject`
  - event_log: `id`, `atomic_fact`, `timestamp`, `event_type`
  - profile: `profiles[].profile_data`, structure differs from other types
  - search results: flat items with `memory_type`, `score`, `summary`, `id`

## Phase 3.2 Bugfixes (from review)
- [x] Fix flat-item parsing in catalog recovery (was using nested group iteration)
- [x] Wrap httpx network exceptions → EverMemosError(UPSTREAM_UNAVAILABLE)
- [x] v1 local no longer requires API key (only v0 Cloud enforces)
- [x] Recovery uses timestamp from search results for created_at
- [x] 22 tests passing: auth gating, response handling, network errors, catalog recovery

## Phase 3.2 Additional Fixes (from review round 2)
- [x] Regex hyphen fix: greedy `\S+` + mandatory `\s+[—\-]\s+` delimiter
- [x] Recovery retry: cooldown mechanism instead of permanent failure
- [x] Recovery dedup: newer timestamp wins (not first-seen)
- [x] Recovery ordering: `last_used_at = timestamp` for recovered spaces
- [x] top_k bumped to 200
- [x] Unused test imports cleaned

## Phase 3.3 — server.py + memory_service + all 5 tools ✅
- `memory_service.py`: list_spaces, remember, recall, briefing, forget
- `server.py`: MCP entry point, 5 tools registered, stdio transport
- Key behaviors:
  - remember → 202 queued + processing_hint
  - recall → flat results with memory_id/type/snippet/timestamp/score + pending_count
  - briefing → parallel fetch (profile + episodic + event_log), assembled highlights
  - forget → per-ID deletion, partial failure reporting
  - All errors mapped to {ok:false, error:code, message:...}
- 45 tests passing (8 client + 16 catalog + 11 service + 10 server)
- E2E smoke test against Cloud v0 ✅

## Status
**Phase 3 core complete.** All 5 MCP tools implemented and tested.
Next: Phase 4 (Demo & testing) or Phase 5 (README + submission materials).
