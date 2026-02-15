# Notes: evermemos-mcp Requirements Research

[English](notes.md) | [简体中文](notes.zh-CN.md)

## Competition Context
- Hackathon: Memory Genesis 2026 (Track 2: Platform Plugin)
- Deadline: Feb 28, 2026 (submission)
- Evaluation: Innovation > Technical Depth > Consumer Value
- Submission: GitHub repo + README + 3-5 min video demo
- Prize: $3,000-$10,000/slot + marketplace revenue + revenue share

## EverMemOS API Summary
- Cloud 主路径：`/api/v0/memories` + `/api/v0/memories/search`
- 本地兼容路径：`/api/v1/memories` + `/api/v1/memories/search`
- `flush=true` 可显式标记会话结束，降低边界检测延迟影响
- Memory types: episodic_memory, profile, foresight, event_log
- Retrieve methods: keyword, vector, hybrid, rrf, agentic

## MCP Protocol Basics
- Server exposes tools that AI clients can call
- Tools have name, description, input schema (JSON Schema)
- Transport: stdio (local) or SSE (remote)
- Client: Claude Code, Cursor, etc.

## User Pain Points (AI Coding Tools)
- 每次新 session 从零开始，不记得项目偏好
- 反复解释同样的架构决策
- 过往 bug 修复经验无法积累
- 代码风格偏好每次都要重新说
- 跨 session 的任务连续性断裂

## Phase 3.1 API Behavior Validation Results

### Connectivity
- Cloud health: ✅ `{"message":"ok","service":"evermemos-gateway"}`
- v0 endpoints work, auth via `Authorization: Bearer` + `X-API-Key`
- GET /memories (fetch): query params
- GET /memories/search: JSON body via `request("GET", ..., json=payload)`

### Write Behavior (Cloud)
- ALL writes return **202 Accepted** (async queued), never 200
- Response: `{"status": "queued", "request_id": "..."}`
- `flush=true` in body does NOT change Cloud response (still 202 queued)
- Completely different from local API (which returns 200 with "extracted"/"accumulated")

### Extraction Timing (Critical!)
- **Cloud extraction takes ~2-5 minutes**, not seconds
- 4 messages sent → memories found after ~5 minutes
- 11 messages sent → still 0 memories after 65s, pending messages increasing
- This means: `remember` → immediate `recall` will be EMPTY
- Pending messages visible in search response (`pending_messages` array)

### Memory Types Extracted (from first test after 5min)
- ✅ episodic_memory: 1 episode narrative
- ✅ profile: user profile with profiles array
- ✅ event_log: 2 atomic facts (React/TypeScript/Zustand, Zustand over Redux)
- ❌ foresight: 0 (not triggered from this conversation type)

### conversation-meta (Cloud v0)
- Cloud v0 does NOT allow `scene` field in group-level config
- Error: "Scene is inherited from global config"
- Need to remove `scene` or use `group_id=null` for global config

### Search Behavior
- keyword search: works, returns grouped by memory_type
- hybrid search: works
- Response includes `pending_messages` (not-yet-extracted messages)
- Profile NOT searchable via search endpoint (confirmed: fetch-only)

### Isolation
- Different group_ids do isolate memories ✅
- But couldn't verify search isolation because extraction was still pending

### Implications for evermemos-mcp
1. `remember` must tell the AI: "memory is queued, may take minutes to be searchable"
2. `recall` should report pending_messages count as context
3. Cannot demo "remember then immediately recall" — need time gap
4. Demo should pre-load memories, then show recall working
5. conversation-meta setup is optional but may improve extraction quality

## Requirements Discussion
- 核心判断标准："没有长期记忆体验就是垃圾，有了就质变"
- 高价值场景候选：
  - Personal CRM（个人关系记忆）
  - Team Memory Bot（团队决策记忆）
  - AI 日记伴侣（个人行为洞察）
  - 研究助手（跨文献知识记忆）
  - Memory MCP Server（给 AI 工具提供长期记忆能力）
  - 客户跟进助手（CRM/CSM 记忆）
- 比赛策略结论：
  - Track 1 同质化风险较高
  - Track 2 生态价值最高、与主办方目标一致
  - Track 3 技术门槛高但可作为后续加分
- 当前建议方向：Track 2 + Memory MCP Server

## Draft Requirement Decisions
- Primary persona: 高频使用 AI coding tools 的开发者
- Primary job: 让 AI 在跨 session 下保持项目级连续上下文
- Value thesis: 降低重复解释成本，减少决策上下文丢失
- Scope strategy: 先做开发者场景，团队协作场景作为 V1.1 扩展

## Scope Update (Conversation)
- 产品定位从 "仅 coding tools" 升级为 "MCP 客户端通用记忆层"
- 楔子市场不变：先以开发者工具场景做 V1 验证
- 兼容扩展目标：Cherry Studio 等聊天客户端
- 建模变化：从 `project_id` 单一隔离，升级为 `space_id` 通用隔离
- 策略原则：定位泛化，Demo 聚焦（2-3 场景）
- 路由方案：通过 `list_spaces` + description 让 AI 选空间，不依赖 cwd/git 推断
- 数据策略：Cloud-only，空间元数据与记忆正文都在 EverMemOS
