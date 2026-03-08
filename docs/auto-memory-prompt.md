# Auto-Memory Prompt Templates

[English](auto-memory-prompt.md) | [简体中文](auto-memory-prompt.zh-CN.md)

Copy-paste these prompt snippets into your AI client's system prompt or CLAUDE.md to enable automatic memory — no manual "remember this" needed.

## Full Template (Claude Code / CLAUDE.md)

Add to your project's `CLAUDE.md` or global `~/.claude/CLAUDE.md`:

```markdown
# Long-Term Memory (evermemos-mcp)

You have access to persistent long-term memory via evermemos-mcp. Use it proactively — don't wait for the user to ask you to remember things.

## Auto-Remember Rules

Automatically call `remember` when you encounter:
- **Architecture decisions** — tech stack choices, design patterns, trade-off rationale
- **User preferences** — coding style, tool preferences, communication style
- **Project conventions** — naming conventions, file structure patterns, deployment processes
- **Bug fixes & solutions** — root causes found, workarounds applied, lessons learned
- **Key context** — project goals, constraints, team structure, external dependencies

Do NOT remember:
- Transient debugging output or intermediate steps
- Information already stored in code comments or documentation
- Trivial or obvious facts

When a write matters, prefer `remember(..., include_status=true)`.
After the call, inspect `status_check`, then `request_status.success` / `request_status.error`, and only then interpret `request_status.lifecycle.state`.

## Auto-Recall Rules

Automatically call `recall` or `briefing` when:
- Starting a new session (use `briefing` to restore context)
- The user asks about something that might have been discussed before
- You need context about prior decisions, preferences, or conventions
- Working on a feature that relates to previous work

## Space Routing

Use `<domain>:<project>` format:
- `coding:<repo-name>` for code projects (e.g. `coding:my-saas`)
- `study:<topic>` for learning (e.g. `study:rust-lang`)
- `chat:preferences` for durable personal preferences
- `chat:daily` for rolling conversation context

If you need a timeline, delete verification, or replay of recent changes, use `fetch_history` instead of relying on `recall` alone.

## Flush Rules

- Use `flush=false` during ongoing multi-turn work
- Use `flush=true` at end of session, topic switch, or when summarizing
- When uncertain, use `flush=true`
```

## Minimal Template

For clients with limited system prompt space:

```text
You have long-term memory via evermemos-mcp. Use it proactively:
- Auto-remember: architecture decisions, user preferences, project conventions, bug solutions
- For important writes, prefer remember(..., include_status=true) and inspect request_status.success/error before lifecycle.state
- Auto-recall: at session start (briefing), when context from past sessions is relevant
- Space format: coding:<repo>, study:<topic>, chat:preferences, chat:daily
- flush=false during conversation, flush=true at boundaries
```

## Cursor / Cline Rules File

Add to `.cursorrules` or `.clinerules`:

```text
# Memory Integration
This project uses evermemos-mcp for persistent memory (space: coding:<project-name>).

At session start:
1. Call briefing(space_id="coding:<project-name>") to restore context

During work:
2. When making architecture decisions or finding bugs, call `remember(..., include_status=true)` to store them and run a write-after check
3. When unsure about prior decisions, call recall() to check
4. If `request_status.success` is false, surface the status-check failure instead of treating it as normal queueing
5. If `request_status.lifecycle.state` stays `queued`, treat recall/briefing as provisional help rather than proof of searchable extraction

At session end:
6. Summarize key decisions and call `remember(flush=true, include_status=true)`
```

## How It Works

```
Session Start
    │
    ▼
briefing → restore context from last session
    │
    ▼
User asks a question
    │
    ├─ recall → check if related context exists in memory
    │
    ▼
AI works on the task
    │
    ├─ remember(flush=false, include_status=true) → store decisions/findings and capture request status
    │
    ▼
Session End / Topic Switch
    │
    └─ remember(flush=true, include_status=true) → finalize, then keep checking request_status until searchable
```

This creates the **Memory → Reasoning → Action** loop:
- **Memory**: briefing + recall provide context
- **Reasoning**: AI uses recalled context to make better decisions
- **Action**: AI stores new insights for future sessions
