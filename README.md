# evermemos-mcp

[![Smithery](https://smithery.ai/badge/@tt-a1i/evermemos-mcp)](https://smithery.ai/server/@tt-a1i/evermemos-mcp)

[English](README.md) | [简体中文](README.zh-CN.md)

**Universal long-term memory layer for AI coding assistants, powered by [EverMemOS](https://evermind.ai/).**

> Built for the [Memory Genesis Competition 2026](https://luma.com/n88icl03) — Track 2: Platform Plugins

---

You spent thirty minutes explaining your project architecture, naming conventions, and why you abandoned MongoDB to Claude Code. Next day, new session — it remembers nothing. You explain it all over again.

evermemos-mcp writes that context into EverMemOS long-term memory. Next time, one `briefing` call and it knows who you are, where the project stands, and what was decided last time. **Benchmark: 60/60 successful memory-backed recall vs 0/60 in the no-memory baseline — zero wrong attributions across 236 resolved rows (p95 1958 ms).**

---

evermemos-mcp is an MCP (Model Context Protocol) server that gives any compatible AI client — Claude Code, Cursor, Cline, Cherry Studio, and more — persistent, cross-session memory. It bridges the gap between stateless AI conversations and the contextual awareness that real-world workflows demand.

## Why This Exists

AI coding assistants forget everything between sessions. This is not a bug — it is an architectural consequence: every session starts as a fresh, stateless instance. This means:

- Architecture decisions you explained need to be re-explained every time
- Your naming preferences and work conventions are never "learned"
- Multiple projects run in parallel with no context isolation and no cross-project memory sharing

evermemos-mcp solves this by providing a **Memory → Reasoning → Action** loop:

```
  remember ──▶ EverMemOS Cloud ──▶ recall / briefing ──▶ Agent acts with context
     ▲                                                          │
     └──────────────── new decisions fed back ◀─────────────────┘
```

1. **Remember** — Store decisions, preferences, and context as you work
2. **Recall** — Retrieve relevant memories using hybrid search (keyword + vector + semantic)
3. **Brief** — Get a full context restoration at the start of any new session

This is not a concept diagram — it is the workflow verified in automated benchmarks: **60/60 successful memory-backed recall vs 0/60 in the no-memory baseline**, all 4 gates passed ([benchmark summary](artifacts/competition/2026-02-26-formal-real-auto-all-v3/benchmark_summary.json) | [runs.jsonl](https://github.com/tt-a1i/evermemos-mcp/releases/tag/competition-evidence-2026-02-26)).

All memories are organized into isolated **spaces** (e.g. `coding:my-app`, `study:ml-notes`, `chat:daily`), so different projects and workflows never bleed into each other.

## Demo

Final demo video will be added after the last recording pass.

Current submission-ready evidence:
- Primary benchmark summary: [`artifacts/competition/2026-02-26-formal-real-auto-all-v3/benchmark_summary.json`](artifacts/competition/2026-02-26-formal-real-auto-all-v3/benchmark_summary.json)
- Human-readable benchmark report: [`artifacts/competition/2026-02-26-formal-real-auto-all-v3/benchmark_report.md`](artifacts/competition/2026-02-26-formal-real-auto-all-v3/benchmark_report.md)
- Evidence release (`runs.jsonl`): [`competition-evidence-2026-02-26`](https://github.com/tt-a1i/evermemos-mcp/releases/tag/competition-evidence-2026-02-26)
- Latest lifecycle appendix: [`artifacts/competition/2026-03-07-lifecycle-appendix-dec0612e/appendix_notes.md`](artifacts/competition/2026-03-07-lifecycle-appendix-dec0612e/appendix_notes.md) (`remember/searchable/isolation` pass; `forget` remains a current Cloud limitation)

## Features

| Tool | Description |
|------|-------------|
| `list_spaces` | Discover available memory spaces |
| `remember` | Store information into long-term memory (async extraction). Scans for sensitive content and checks for conflicting memories in chat spaces |
| `request_status` | Check whether a queued write is still queued or has been reported completed by upstream |
| `recall` | Search memories with 6 retrieval strategies and label whether results are `searchable`, `provisional`, or `fallback` |
| `briefing` | Get a structured context briefing: profile + episodes + facts + foresights, with explicit fallback labeling when needed |
| `forget` | Targeted memory deletion by ID (verification-first under current Cloud semantics) |
| `fetch_history` | Paginate through memory timeline by type |

### Key Capabilities

- **Space isolation** — `space_id` (`<domain>:<slug>`) keeps memories separated by project or topic
- **Multi-space search** — Query up to 10 spaces in a single `recall` call with automatic source attribution
- **Traceable citations** — Every result includes `memory_type`, `snippet`, `timestamp`, `score`, and optional `source_message_id`
- **Multi-user support** — Optional `user_id` filtering for shared spaces
- **Conversation metadata sync** — Automatic `conversation-meta` integration with EverMemOS Cloud
- **Async-friendly identity fallback** — Chat identity/preferences are best-effort mirrored into `conversation-meta` and can be surfaced as explicit fallback results when extracted search results are unavailable
- **Unified lifecycle semantics** — `remember`, `request_status`, `recall`, and `briefing` expose compatible `lifecycle` blocks so clients can collectively distinguish `queued`, `provisional`, `fallback`, and `searchable`
- **Sensitive content guard** — Detects API keys, passwords, tokens, and private keys before storing. Blocks the write and asks the user to confirm
- **Memory conflict detection** — Automatically checks for similar existing memories in `chat:*` spaces and surfaces conflicts so the agent can decide whether to update or append
- **Robust error handling** — Retry with backoff (429 / 5xx), GET body fallback for proxy/WAF compatibility, and structured error codes

## Quick Start

Get your API key from [EverMemOS Cloud](https://evermind.ai/).

### Option A: Install from PyPI (recommended)

No clone needed — just add to your MCP client config:

```json
{
  "mcpServers": {
    "evermemos-mcp": {
      "type": "stdio",
      "command": "uvx",
      "args": ["evermemos-mcp@latest"],
      "env": {
        "EVERMEMOS_API_KEY": "your-key-here",
        "EVERMEMOS_USER_ID": "mcp-user"
      }
    }
  }
}
```

Or run directly from the command line:

```bash
uvx evermemos-mcp@latest
```

If your client still launches an older cached build after a release, refresh it with:

```bash
uv cache clean evermemos-mcp
```

### Option B: Install from source

```bash
git clone https://github.com/tt-a1i/evermemos-mcp.git
cd evermemos-mcp
cp .env.example .env
# Edit .env and set your EVERMEMOS_API_KEY
uv run evermemos-mcp
```

MCP client config for source installs:

```json
{
  "mcpServers": {
    "evermemos-mcp": {
      "type": "stdio",
      "command": "uv",
      "args": [
        "run",
        "--directory",
        "/absolute/path/to/evermemos-mcp",
        "evermemos-mcp"
      ],
      "env": {
        "EVERMEMOS_API_KEY": "your-key-here",
        "EVERMEMOS_USER_ID": "mcp-user"
      }
    }
  }
}
```

Client-specific setup guides (Claude Code, Cursor, Cline, Cherry Studio) are in [`docs/05-client-integrations.md`](docs/05-client-integrations.md).

## Architecture

```
MCP Client (Claude Code / Cursor / Cline / Cherry Studio)
        │
        │  MCP stdio
        ▼
┌─────────────────────────────┐
│     evermemos-mcp server    │
│  ┌───────────────────────┐  │
│  │   7 Tool Handlers     │  │
│  └──────────┬────────────┘  │
│  ┌──────────▼────────────┐  │
│  │   Memory Service      │  │  remember / request_status / recall / briefing / forget / fetch_history
│  └──────────┬────────────┘  │
│  ┌──────────▼────────────┐  │
│  │ Space Catalog Service │  │  space registry, metadata sync, cross-session recovery
│  └──────────┬────────────┘  │
│  ┌──────────▼────────────┐  │
│  │  EverMemOS HTTP Client│  │  auth, retries, rate-limit backoff, error normalization
│  └──────────┬────────────┘  │
└─────────────┼───────────────┘
              │  HTTPS
              ▼
       EverMemOS Cloud API
```

- **Cloud-first** — All memories live in EverMemOS Cloud. No local persistence, no state to lose.
- **Process-local cache** — Space catalog is cached in-memory for fast lookups, recovered from Cloud on startup.
- **Async extraction** — `remember` queues content for AI-powered extraction. Memories become searchable after processing.

## EverMemOS Integration Depth

evermemos-mcp is not a thin API wrapper. Each tool maps to a specific EverMemOS capability:

| Tool | EverMemOS Concept | What it does |
|------|-------------------|--------------|
| `remember` | MemCell-backed ingestion path | Feeds raw context into Cloud extraction pipeline |
| `request_status` | Processing status tracking | Checks whether upstream extraction has completed |
| `recall` | Hierarchical Memory retrieval | Hybrid search across keyword, vector, and semantic layers |
| `briefing` | Reconstructive Recollection | Reassembles profile + episodes + facts + foresights into a session-start context packet |
| `fetch_history` | Episodic Trace + event log | Timeline access over selected memory types |
| `forget` | Verification-first targeted delete | Issues delete against current Cloud semantics with re-check guidance |

The four surfaced lifecycle/result states (`queued`, `provisional`, `fallback`, `searchable`) are unified across all tool outputs, giving agents a consistent view of memory maturity regardless of which tool they call.

## Memory Lifecycle States

| State | Meaning | Typical surface |
|-------|---------|-----------------|
| `queued` | The write was accepted, but formal extraction is not confirmed searchable yet | `remember.lifecycle`, `request_status.lifecycle`, `recall.pending_count` |
| `provisional` | The answer comes from `pending_messages` while extraction is still queued | `recall.results[].stability == provisional` |
| `fallback` | The answer comes from mirrored `conversation-meta`, not formal extracted memory | `recall.results[].stability == fallback`, `briefing.highlights[].stability == fallback` |
| `searchable` | The answer comes from formal extracted memories returned by search/fetch APIs | `recall.results[].stability == searchable`, `briefing.highlights[].stability == searchable` |

If a tool can answer using `provisional` or `fallback` data, that does not mean formal extraction has completed.

## Space Templates

Use spaces to separate intent, not just data:

| Template | Use it for |
|----------|------------|
| `chat:preferences` | durable personal preferences, names, tone, UI likes/dislikes |
| `chat:daily` | ongoing chat context that should not leak into project memory |
| `coding:<repo>` | architecture decisions, conventions, bugs, and project context |
| `study:<topic>` | learning notes, topic progress, and revision context |

Why split spaces? Because "who I am", "what this repo needs", and "what I'm learning" should not overwrite each other.

## Which Tool To Use

| Goal | Primary tool | Why |
|------|--------------|-----|
| Start a new session | `briefing` | fastest way to restore context in one call |
| Find the most relevant prior fact | `recall` | relevance-ranked lookup across one or more spaces |
| Review what happened over time | `fetch_history` | chronological timeline beats ranked search for audits and replay |
| Verify before or after deletion | `fetch_history` | stable timeline check before trusting `forget` |

If `recall` feels unstable or too selective, switch to `fetch_history` instead of retrying the same search blindly.

## Forget Safety

Cloud-side deletion is asynchronous and best-effort. Rather than hiding this, evermemos-mcp provides a verification-first workflow:

1. Confirm the target `memory_id` via `fetch_history` or `recall`.
2. Call `forget(memory_ids=[...], space_id=...)`.
3. Verify with `fetch_history`, then `recall` if needed.
4. If the target persists, the lifecycle model surfaces this transparently — so agents do not silently assume deletion succeeded.

This is a deliberate design choice: expose the real state to the agent rather than pretend deletion is instant.

## Use Cases

### Coding: Persistent Architecture Context
```
You: remember that we chose PostgreSQL over MongoDB because our data is highly relational
     [space_id: coding:my-saas]

-- next day, new session --

You: what database did we choose and why?
     → recall finds: "Chose PostgreSQL over MongoDB — highly relational data model"
```

### Study: Cross-Session Learning Notes
```
You: remember: bias-variance tradeoff — high bias = underfitting, high variance = overfitting
     [space_id: study:ml-notes]

-- later --

You: briefing for study:ml-notes
     → Returns: profile (technical skills), recent episodes, key facts, foresights
```

### Chat: Personal Preferences
```
You: remember I prefer dark mode, vim keybindings, and concise responses
     [space_id: chat:preferences]

-- any future session --

You: recall my UI preferences
     → "Prefers dark mode, vim keybindings, concise responses"
```

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `EVERMEMOS_API_KEY` | *(required)* | EverMemOS Cloud API key |
| `EVERMEMOS_USER_ID` | `mcp-user` | Default user identity |
| `EVERMEMOS_BASE_URL` | `https://api.evermind.ai` | API endpoint |
| `EVERMEMOS_API_VERSION` | `v0` | API version |
| `EVERMEMOS_ENABLE_CONVERSATION_META` | `true` | Sync conversation metadata |
| `EVERMEMOS_DEFAULT_TIMEZONE` | `UTC` | Timezone for metadata |
| `EVERMEMOS_DEFAULT_SPACE` | *(auto)* | Default space_id. If unset, auto-detected from git remote as `coding:<repo-name>` |
| `EVERMEMOS_LLM_CUSTOM_SETTING_JSON` | — | Custom LLM extraction settings |
| `EVERMEMOS_USER_DETAILS_JSON` | — | User profile details for conversations |

### Space Auto-Detection

When `space_id` is omitted from `remember` or `recall`, the server automatically infers a default from:
1. `EVERMEMOS_DEFAULT_SPACE` environment variable (if set)
2. Git remote origin URL → `coding:<repo-name>` (e.g. `coding:my-saas`)

This means inside a git project, you can simply call `remember` without specifying a space — memories are automatically routed to the right place.

## `flush` Boundary Rules

`flush` controls when EverMemOS triggers memory extraction:

| Scenario | `flush` |
|----------|---------|
| Mid-conversation, more messages coming | `false` |
| End of session / topic switch / summary | `true` |
| Uncertain | `true` (safer default) |

## Development

```bash
uv sync --group dev       # Install dev dependencies
uv run ruff check         # Lint
uv run pytest             # Unit tests
EVERMEMOS_RUN_INTEGRATION_TESTS=true uv run pytest -m integration  # Integration tests
```

CI runs on every push and PR via [`.github/workflows/ci.yml`](.github/workflows/ci.yml).

## Documentation

| Document | Description |
|----------|-------------|
| [`docs/01-requirements.md`](docs/01-requirements.md) | Product requirements |
| [`docs/02-architecture.md`](docs/02-architecture.md) | Technical architecture |
| [`docs/03-demo-playbook.md`](docs/03-demo-playbook.md) | Demo walkthrough |
| [`docs/04-submission.md`](docs/04-submission.md) | Submission checklist |
| [`docs/05-client-integrations.md`](docs/05-client-integrations.md) | Client setup guides |
| [`docs/06-benchmark.md`](docs/06-benchmark.md) | Benchmark protocol and acceptance gates |
| [`docs/07-release-checklist.md`](docs/07-release-checklist.md) | Release readiness checklist |
| [`docs/competition/benchmark_deep_dive.md`](docs/competition/benchmark_deep_dive.md) | Primary evidence deep dive |
| [`docs/auto-memory-prompt.md`](docs/auto-memory-prompt.md) | Auto-memory prompt templates for CLAUDE.md / Cursor / Cline |
| [`CHANGELOG.md`](CHANGELOG.md) | Version history |

## Support

If evermemos-mcp is useful to you, give it a [star on GitHub](https://github.com/tt-a1i/evermemos-mcp) — it helps others discover the project.

## License

See [LICENSE](LICENSE).
