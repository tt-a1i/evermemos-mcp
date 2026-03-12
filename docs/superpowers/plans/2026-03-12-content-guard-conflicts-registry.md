# Content Guard, Conflict Detection & Registry Listing

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add sensitive content detection (block + ask user), memory conflict detection on `remember()`, and list on Smithery.ai / mcp.so registries.

**Architecture:** New `content_guard.py` module handles sensitive pattern matching (pure functions, no async). Conflict detection lives in `memory_service.remember()` — a pre-write `recall()` call that surfaces similar existing memories. Both features gate on new `remember` tool parameters: `allow_sensitive` and `check_conflicts`. Registry listing is docs/config only.

**Tech Stack:** Python 3.12, regex, existing recall infrastructure, smithery.yaml

---

## File Map

| File | Action | Responsibility |
|------|--------|---------------|
| `src/evermemos_mcp/content_guard.py` | Create | Sensitive pattern matching — pure functions |
| `tests/test_content_guard.py` | Create | Unit tests for content guard |
| `src/evermemos_mcp/memory_service.py` | Modify | Integrate content guard + conflict detection in `remember()` |
| `src/evermemos_mcp/server.py` | Modify | Add `allow_sensitive` + `check_conflicts` params to `remember` tool schema + dispatch |
| `tests/test_memory_service.py` | Modify | Tests for sensitive blocking + conflict detection in remember |
| `tests/test_server.py` | Modify | Tests for new params in dispatch |
| `README.md` | Modify | Add Smithery/mcp.so badges, mention new features |
| `README.zh-CN.md` | Modify | Same for Chinese README |
| `CHANGELOG.md` | Modify | v0.5.0 entry |
| `pyproject.toml` | Modify | Version bump to 0.5.0 |
| `src/evermemos_mcp/__init__.py` | Modify | Version bump to 0.5.0 |
| `tests/test_release_consistency.py` | Modify | Update version assertions |

---

## Chunk 1: Content Guard Module

### Task 1: Create `content_guard.py` with sensitive pattern detection

**Files:**
- Create: `src/evermemos_mcp/content_guard.py`
- Test: `tests/test_content_guard.py`

- [ ] **Step 1: Write failing tests for `scan_sensitive_content()`**

```python
# tests/test_content_guard.py
"""Tests for content_guard: sensitive content detection."""

from __future__ import annotations

from evermemos_mcp.content_guard import SensitiveMatch, scan_sensitive_content


def test_detects_openai_api_key():
    text = "Use this key: sk-proj-abcdefghijklmnopqrstuvwxyz1234567890abcdef"
    matches = scan_sensitive_content(text)
    assert len(matches) >= 1
    assert matches[0].category == "api_key"
    assert "sk-proj-" in matches[0].matched_text


def test_detects_anthropic_api_key():
    text = "My key is sk-ant-api03-abcdefghijklmnopqrstuvwxyz1234567890"
    matches = scan_sensitive_content(text)
    assert len(matches) >= 1
    assert matches[0].category == "api_key"


def test_detects_aws_access_key():
    text = "AWS key: AKIAIOSFODNN7EXAMPLE"
    matches = scan_sensitive_content(text)
    assert len(matches) >= 1
    assert matches[0].category == "aws_key"


def test_detects_github_token():
    text = "Token: ghp_ABCDEFabcdef1234567890abcdef1234567890"
    matches = scan_sensitive_content(text)
    assert len(matches) >= 1
    assert matches[0].category == "github_token"


def test_detects_private_key_block():
    text = "-----BEGIN RSA PRIVATE KEY-----\nMIIEpQIBAAK..."
    matches = scan_sensitive_content(text)
    assert len(matches) >= 1
    assert matches[0].category == "private_key"


def test_detects_generic_private_key():
    text = "-----BEGIN PRIVATE KEY-----\ndata..."
    matches = scan_sensitive_content(text)
    assert len(matches) >= 1
    assert matches[0].category == "private_key"


def test_detects_connection_string_with_password():
    text = "Use postgres://admin:s3cretP4ss@db.example.com:5432/mydb"
    matches = scan_sensitive_content(text)
    assert len(matches) >= 1
    assert matches[0].category == "connection_string"


def test_detects_password_assignment():
    text = 'config has password="SuperSecret123!"'
    matches = scan_sensitive_content(text)
    assert len(matches) >= 1
    assert matches[0].category == "password"


def test_detects_secret_assignment():
    text = "export API_KEY=abcdef1234567890abcdef"
    matches = scan_sensitive_content(text)
    assert len(matches) >= 1
    assert matches[0].category == "secret"


def test_detects_slack_token():
    text = "Bot token: xoxb-1234567890-abcdefghij-ABCDEFGHIJ"
    matches = scan_sensitive_content(text)
    assert len(matches) >= 1
    assert matches[0].category == "slack_token"


def test_no_false_positive_on_normal_text():
    text = "I prefer using Python for backend development. My name is Alice."
    matches = scan_sensitive_content(text)
    assert matches == []


def test_no_false_positive_on_code_discussion():
    text = "The function returns sk_count which tracks how many items were skipped."
    matches = scan_sensitive_content(text)
    assert matches == []


def test_no_false_positive_on_short_sk_prefix():
    text = "Variable sk is used for socket."
    matches = scan_sensitive_content(text)
    assert matches == []


def test_detects_multiple_sensitive_items():
    text = (
        "Key: sk-proj-abc123def456ghi789jkl012mno345pqr678stu\n"
        "DB: postgres://root:hunter2@localhost/prod"
    )
    matches = scan_sensitive_content(text)
    assert len(matches) >= 2
    categories = {m.category for m in matches}
    assert "api_key" in categories
    assert "connection_string" in categories


def test_match_has_description():
    text = "Token: ghp_ABCDEFabcdef1234567890abcdef1234567890"
    matches = scan_sensitive_content(text)
    assert matches[0].description  # non-empty string
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_content_guard.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'evermemos_mcp.content_guard'`

- [ ] **Step 3: Implement `content_guard.py`**

```python
# src/evermemos_mcp/content_guard.py
"""Sensitive content detection for memory writes.

Pure functions — no async, no network, no side effects.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SensitiveMatch:
    """A single sensitive content detection result."""

    category: str
    description: str
    matched_text: str


# (compiled_regex, category, description)
# Order: most specific first to reduce false positives.
_PATTERNS: list[tuple[re.Pattern[str], str, str]] = [
    # -- API keys with known prefixes --
    (
        re.compile(r"\bsk-(?:proj-|ant-api\d{2}-)?[A-Za-z0-9_\-]{20,}"),
        "api_key",
        "OpenAI/Anthropic API key",
    ),
    (
        re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
        "aws_key",
        "AWS Access Key ID",
    ),
    (
        re.compile(r"\bgh[psortu]_[A-Za-z0-9]{36,}\b"),
        "github_token",
        "GitHub token",
    ),
    (
        re.compile(r"\bxox[bp]-[A-Za-z0-9\-]{20,}\b"),
        "slack_token",
        "Slack token",
    ),
    # -- Private keys --
    (
        re.compile(r"-----BEGIN (?:RSA |EC |DSA |ED25519 )?PRIVATE KEY-----"),
        "private_key",
        "Private key block",
    ),
    # -- Connection strings with embedded credentials --
    (
        re.compile(
            r"\b(?:postgres(?:ql)?|mysql|mongodb(?:\+srv)?|redis|amqp)"
            r"://[^\s:]+:[^\s@]+@[^\s]+"
        ),
        "connection_string",
        "Database connection string with credentials",
    ),
    # -- Explicit password/secret assignments --
    (
        re.compile(
            r"\b(?:password|passwd|pwd)\s*[=:]\s*[\"']?([^\s\"']{8,})",
            re.IGNORECASE,
        ),
        "password",
        "Password value",
    ),
    (
        re.compile(
            r"\b(?:secret|token|api[_-]?key|access[_-]?key|SECRET_KEY|API_KEY)"
            r"\s*[=:]\s*[\"']?([^\s\"']{16,})",
            re.IGNORECASE,
        ),
        "secret",
        "Secret or token value",
    ),
]

# Guard against false positives on short `sk-` fragments like `sk_count`.
_SK_MIN_LENGTH = 20


def scan_sensitive_content(text: str) -> list[SensitiveMatch]:
    """Scan text for sensitive patterns. Returns empty list if clean."""
    if not isinstance(text, str) or not text:
        return []

    matches: list[SensitiveMatch] = []
    seen_spans: set[tuple[int, int]] = set()

    for pattern, category, description in _PATTERNS:
        for m in pattern.finditer(text):
            span = (m.start(), m.end())
            # Skip overlapping matches.
            if any(s[0] <= span[0] < s[1] or s[0] < span[1] <= s[1] for s in seen_spans):
                continue
            matched = m.group(0)
            # Extra guard for sk- prefix: require minimum length.
            if category == "api_key" and len(matched) < _SK_MIN_LENGTH:
                continue
            seen_spans.add(span)
            matches.append(
                SensitiveMatch(
                    category=category,
                    description=description,
                    matched_text=matched,
                )
            )

    return matches
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_content_guard.py -v`
Expected: All PASS

- [ ] **Step 5: Lint**

Run: `uv run ruff check src/evermemos_mcp/content_guard.py tests/test_content_guard.py`
Expected: No errors

- [ ] **Step 6: Commit**

```bash
git add src/evermemos_mcp/content_guard.py tests/test_content_guard.py
git commit -m "feat: add content_guard module for sensitive content detection"
```

---

### Task 2: Integrate content guard into `remember()`

**Files:**
- Modify: `src/evermemos_mcp/memory_service.py` (lines ~1201-1407, `remember()`)
- Modify: `src/evermemos_mcp/server.py` (tool schema + dispatch)
- Test: `tests/test_memory_service.py`, `tests/test_server.py`

- [ ] **Step 7: Write failing tests for sensitive content blocking in remember**

Add to `tests/test_memory_service.py`:

```python
# -- sensitive content detection --


@pytest.mark.asyncio
async def test_remember_blocks_sensitive_content_by_default():
    svc, client = _make_svc()
    result = await svc.remember(
        space_id="chat:test",
        content="Use this key: sk-proj-abcdefghijklmnopqrstuvwxyz1234567890abcdef",
    )
    assert result["ok"] is False
    assert result["blocked_reason"] == "sensitive_content_detected"
    assert len(result["sensitive_matches"]) >= 1
    assert result["sensitive_matches"][0]["category"] == "api_key"
    # Must NOT call Cloud API
    client.add_message.assert_not_called()


@pytest.mark.asyncio
async def test_remember_allows_sensitive_content_when_explicitly_allowed():
    svc, client = _make_svc()
    result = await svc.remember(
        space_id="chat:test",
        content="Use this key: sk-proj-abcdefghijklmnopqrstuvwxyz1234567890abcdef",
        allow_sensitive=True,
    )
    assert result["ok"] is True
    client.add_message.assert_called_once()


@pytest.mark.asyncio
async def test_remember_passes_clean_content_without_blocking():
    svc, client = _make_svc()
    result = await svc.remember(
        space_id="chat:test",
        content="I prefer using vim for quick edits",
    )
    assert result["ok"] is True
    client.add_message.assert_called_once()
```

- [ ] **Step 8: Run tests to verify they fail**

Run: `uv run pytest tests/test_memory_service.py::test_remember_blocks_sensitive_content_by_default -v`
Expected: FAIL — `remember()` doesn't accept `allow_sensitive`

- [ ] **Step 9: Add `allow_sensitive` parameter to `remember()` in memory_service.py**

In `memory_service.py`, modify `remember()` signature (line ~1201) to add `allow_sensitive: bool = False`. After input validation (line ~1267, before `_extract_chat_profile_patch`), add:

```python
        # -- sensitive content guard --
        if not allow_sensitive:
            from .content_guard import scan_sensitive_content

            sensitive_matches = scan_sensitive_content(content)
            if sensitive_matches:
                return {
                    "ok": False,
                    "blocked_reason": "sensitive_content_detected",
                    "sensitive_matches": [
                        {
                            "category": m.category,
                            "description": m.description,
                            "matched_text": m.matched_text[:20] + "..."
                            if len(m.matched_text) > 20
                            else m.matched_text,
                        }
                        for m in sensitive_matches
                    ],
                    "hint": (
                        "Sensitive content detected (API keys, passwords, tokens). "
                        "Ask the user whether to proceed. "
                        "If confirmed, retry with allow_sensitive=true."
                    ),
                }
```

- [ ] **Step 10: Add `allow_sensitive` to server.py tool schema and dispatch**

In `server.py`, add to remember tool `inputSchema.properties` (after `include_status`):

```python
                "allow_sensitive": {
                    "type": "boolean",
                    "description": (
                        "Set to true to bypass sensitive content detection. "
                        "Only use after the user has explicitly confirmed they want "
                        "to store content containing API keys, passwords, or tokens."
                    ),
                    "default": False,
                },
```

In `_dispatch()` remember branch (line ~518), add to the call:

```python
            allow_sensitive=args.get("allow_sensitive", False),
```

- [ ] **Step 11: Add server dispatch test**

Add to `tests/test_server.py`:

```python
@pytest.mark.asyncio
async def test_dispatch_remember_passes_allow_sensitive(svc):
    await _dispatch("remember", {
        "content": "key: sk-proj-abcdefghijklmnopqrstuvwxyz1234567890abcdef",
        "space_id": "chat:test",
        "allow_sensitive": True,
    })
    svc.remember.assert_called_once()
    _, kwargs = svc.remember.call_args
    assert kwargs.get("allow_sensitive") is True or (
        svc.remember.call_args[1].get("allow_sensitive") is True
    )
```

- [ ] **Step 12: Run all tests**

Run: `uv run pytest tests/test_memory_service.py tests/test_server.py tests/test_content_guard.py -v`
Expected: All PASS

- [ ] **Step 13: Commit**

```bash
git add src/evermemos_mcp/memory_service.py src/evermemos_mcp/server.py tests/test_memory_service.py tests/test_server.py
git commit -m "feat: block sensitive content in remember, ask user before storing"
```

---

## Chunk 2: Memory Conflict Detection

### Task 3: Add conflict detection to `remember()`

**Files:**
- Modify: `src/evermemos_mcp/memory_service.py` (`remember()`)
- Modify: `src/evermemos_mcp/server.py` (tool schema + dispatch)
- Test: `tests/test_memory_service.py`, `tests/test_server.py`

- [ ] **Step 14: Write failing tests for conflict detection**

Add to `tests/test_memory_service.py`:

```python
# -- conflict detection --


@pytest.mark.asyncio
async def test_remember_detects_conflicts_for_chat_space():
    """chat:* spaces auto-enable conflict detection."""
    search_rv = {
        "result": {
            "memories": [
                {
                    "id": "mem-old",
                    "memory_type": "profile",
                    "content": "User prefers vim",
                    "score": 0.88,
                    "timestamp": "2026-03-01T00:00:00Z",
                }
            ],
            "pending_messages": [],
        }
    }
    svc, client = _make_svc(search_rv=search_rv)
    svc._catalog.ensure_space("chat:preferences")

    result = await svc.remember(
        space_id="chat:preferences",
        content="I now prefer vscode over vim",
    )

    assert result["ok"] is True
    # Memory is stored (add_message called)
    client.add_message.assert_called_once()
    # Conflicts are surfaced
    assert "conflicts" in result
    assert result["conflicts"]["found"] >= 1
    assert result["conflicts"]["items"][0]["memory_id"] == "mem-old"


@pytest.mark.asyncio
async def test_remember_skips_conflicts_for_coding_space_by_default():
    """coding:* spaces skip conflict detection by default."""
    svc, client = _make_svc()
    svc._catalog.ensure_space("coding:app")

    result = await svc.remember(
        space_id="coding:app",
        content="Decided to use PostgreSQL",
    )

    assert result["ok"] is True
    assert "conflicts" not in result
    # search_memories should NOT be called (no conflict check)
    client.search_memories.assert_not_called()


@pytest.mark.asyncio
async def test_remember_force_conflict_check_on_coding_space():
    """check_conflicts=True forces detection on any space."""
    search_rv = {
        "result": {
            "memories": [
                {
                    "id": "mem-db",
                    "memory_type": "episodic_memory",
                    "content": "Using MongoDB for storage",
                    "score": 0.75,
                    "timestamp": "2026-02-20T00:00:00Z",
                }
            ],
            "pending_messages": [],
        }
    }
    svc, client = _make_svc(search_rv=search_rv)
    svc._catalog.ensure_space("coding:app")

    result = await svc.remember(
        space_id="coding:app",
        content="Migrated from MongoDB to PostgreSQL",
        check_conflicts=True,
    )

    assert result["ok"] is True
    assert "conflicts" in result
    assert result["conflicts"]["found"] >= 1


@pytest.mark.asyncio
async def test_remember_no_conflicts_returns_clean_response():
    """When no similar memories exist, no conflicts section."""
    empty_search = {
        "result": {"memories": [], "pending_messages": []}
    }
    svc, client = _make_svc(search_rv=empty_search)
    svc._catalog.ensure_space("chat:preferences")

    result = await svc.remember(
        space_id="chat:preferences",
        content="I like dark themes",
    )

    assert result["ok"] is True
    assert "conflicts" not in result


@pytest.mark.asyncio
async def test_remember_conflict_check_failure_does_not_block_write():
    """If recall fails during conflict check, remember still proceeds."""
    svc, client = _make_svc()
    svc._catalog.ensure_space("chat:preferences")
    client.search_memories = AsyncMock(side_effect=Exception("network error"))

    result = await svc.remember(
        space_id="chat:preferences",
        content="My favorite color is blue",
    )

    assert result["ok"] is True
    client.add_message.assert_called_once()
    # Should have a warning about failed conflict check
    warnings = result.get("warnings", [])
    assert any(w.get("code") == "CONFLICT_CHECK_FAILED" for w in warnings)
```

- [ ] **Step 15: Run tests to verify they fail**

Run: `uv run pytest tests/test_memory_service.py::test_remember_detects_conflicts_for_chat_space -v`
Expected: FAIL — `remember()` doesn't accept `check_conflicts`

- [ ] **Step 16: Implement conflict detection in `remember()`**

In `memory_service.py`, modify `remember()`:

1. Add parameter `check_conflicts: bool | None = None` to signature.

2. After the sensitive content guard block and before `_extract_chat_profile_patch()` (line ~1269), add conflict check logic:

```python
        # -- conflict detection --
        should_check_conflicts = check_conflicts
        if should_check_conflicts is None:
            should_check_conflicts = space_id.startswith(_CHAT_SPACE_PREFIX)

        conflict_items: list[dict] | None = None
        conflict_warning: dict | None = None
        if should_check_conflicts:
            try:
                # Truncate content for search query (long content makes poor queries).
                query_text = content[:200].strip()
                conflict_search = await self._client.search_memories(
                    group_id=to_group_id(space_id),
                    query=query_text,
                    top_k=5,
                    retrieve_method="hybrid",
                )
                raw_memories = (
                    conflict_search.get("result", {}).get("memories", [])
                )
                if isinstance(raw_memories, list):
                    conflict_items = []
                    for item in raw_memories:
                        if not isinstance(item, dict):
                            continue
                        mid = self._extract_memory_id(item)
                        if not mid:
                            continue
                        snippet = self._extract_snippet(item)
                        score = item.get("score")
                        conflict_items.append(
                            {
                                "memory_id": mid,
                                "memory_type": item.get("memory_type", ""),
                                "snippet": snippet[:200] if snippet else "",
                                "score": score,
                                "timestamp": self._extract_timestamp(item),
                            }
                        )
                    if not conflict_items:
                        conflict_items = None
            except Exception as exc:
                logger.warning("Conflict check failed: %s", exc)
                conflict_warning = {
                    "code": "CONFLICT_CHECK_FAILED",
                    "message": f"Could not check for conflicting memories: {exc}",
                }
```

3. After building `output` dict (after line ~1349), add conflict results:

```python
        if conflict_items:
            output["conflicts"] = {
                "found": len(conflict_items),
                "items": conflict_items,
                "hint": (
                    "Similar memories already exist in this space. "
                    "If these represent outdated information, use forget to remove "
                    "them. The new memory has been stored regardless."
                ),
            }

        if conflict_warning is not None:
            output.setdefault("warnings", []).append(conflict_warning)
```

- [ ] **Step 17: Add `check_conflicts` to server.py tool schema and dispatch**

In `server.py`, add to remember tool `inputSchema.properties`:

```python
                "check_conflicts": {
                    "type": "boolean",
                    "description": (
                        "Check for similar existing memories before storing. "
                        "Default: auto (enabled for chat:* spaces, disabled for others). "
                        "When conflicts are found, the new memory is still stored "
                        "and conflicts are returned for the agent to decide."
                    ),
                },
```

In `_dispatch()` remember branch, add to the call:

```python
            check_conflicts=args.get("check_conflicts"),
```

- [ ] **Step 18: Add server dispatch test for check_conflicts**

Add to `tests/test_server.py`:

```python
@pytest.mark.asyncio
async def test_dispatch_remember_passes_check_conflicts(svc):
    await _dispatch("remember", {
        "content": "test",
        "space_id": "coding:app",
        "check_conflicts": True,
    })
    svc.remember.assert_called_once()
    call_kwargs = svc.remember.call_args[1]
    assert call_kwargs.get("check_conflicts") is True
```

- [ ] **Step 19: Run all tests**

Run: `uv run pytest tests/ -v`
Expected: All PASS

- [ ] **Step 20: Lint**

Run: `uv run ruff check src/evermemos_mcp/memory_service.py src/evermemos_mcp/server.py`
Expected: No errors

- [ ] **Step 21: Commit**

```bash
git add src/evermemos_mcp/memory_service.py src/evermemos_mcp/server.py tests/test_memory_service.py tests/test_server.py
git commit -m "feat: detect conflicting memories on remember, auto-enabled for chat spaces"
```

---

## Chunk 3: Registry Listing, Docs & Version Bump

### Task 4: Update remember tool description

**Files:**
- Modify: `src/evermemos_mcp/server.py` (remember tool description)

- [ ] **Step 22: Update remember tool description to mention new features**

In `server.py`, update the remember tool description (line ~88) to append:

```python
            "Content is scanned for sensitive patterns (API keys, passwords, tokens) before "
            "sending to Cloud. If detected, the write is blocked and the server returns the "
            "findings so the user can confirm. Retry with allow_sensitive=true after confirmation. "
            "For chat:* spaces, similar existing memories are checked automatically and surfaced "
            "as conflicts in the response. Use check_conflicts to override this behavior."
```

- [ ] **Step 23: Run description coverage test**

Run: `uv run pytest tests/test_server.py::test_tool_descriptions_cover_client_guidance -v`
Expected: PASS (or update assertions if needed)

- [ ] **Step 24: Commit**

```bash
git add src/evermemos_mcp/server.py
git commit -m "docs: update remember tool description with content guard and conflict detection"
```

### Task 5: Version bump and changelog

**Files:**
- Modify: `pyproject.toml` — version `0.4.8` → `0.5.0`
- Modify: `src/evermemos_mcp/__init__.py` — version `0.4.8` → `0.5.0`
- Modify: `CHANGELOG.md` — add `## [0.5.0]` entry
- Modify: `tests/test_release_consistency.py` — update version assertions

- [ ] **Step 25: Bump version in pyproject.toml and __init__.py**

`pyproject.toml`: change `version = "0.4.8"` → `version = "0.5.0"`
`__init__.py`: change `__version__ = "0.4.8"` → `__version__ = "0.5.0"`

- [ ] **Step 26: Update CHANGELOG.md**

Prepend after the header:

```markdown
## [0.5.0] - 2026-03-12

### Added
- Sensitive content detection: `remember` scans for API keys, passwords, tokens, private keys, and connection strings before storing. Blocked writes return findings so the user can confirm; retry with `allow_sensitive=true` after confirmation.
- Memory conflict detection: `remember` checks for similar existing memories in `chat:*` spaces by default. Conflicts are surfaced in the response with memory IDs and snippets. Use `check_conflicts` parameter to override auto behavior.
- New module `content_guard.py` with `scan_sensitive_content()` for pattern-based detection.

### Changed
- Updated `remember` tool description to document content guard and conflict detection behavior.
- Added `allow_sensitive` and `check_conflicts` parameters to `remember` tool schema.
```

- [ ] **Step 27: Update test_release_consistency.py**

Change version assertions from `"0.4.8"` to `"0.5.0"`.
Update changelog assertion to check for `"## [0.5.0]"` or keep existing `"## [0.4.7]"` check (both should be present).

- [ ] **Step 28: Run release consistency tests**

Run: `uv run pytest tests/test_release_consistency.py -v`
Expected: All PASS

- [ ] **Step 29: Commit**

```bash
git add pyproject.toml src/evermemos_mcp/__init__.py CHANGELOG.md tests/test_release_consistency.py
git commit -m "release: bump version to 0.5.0"
```

### Task 6: README badges and feature updates

**Files:**
- Modify: `README.md`
- Modify: `README.zh-CN.md`

- [ ] **Step 30: Add Smithery badge and update feature list in README.md**

After line 1 (`# evermemos-mcp`), add badges:

```markdown
[![Smithery](https://smithery.ai/badge/@tt-a1i/evermemos-mcp)](https://smithery.ai/server/@tt-a1i/evermemos-mcp)
```

In the Features table, update the `remember` row:

```markdown
| `remember` | Store information into long-term memory (async extraction). Scans for sensitive content (API keys, passwords) and checks for conflicting memories in chat spaces |
```

In Key Capabilities, add two new bullets:

```markdown
- **Sensitive content guard** — Detects API keys, passwords, tokens, and private keys before storing. Blocks the write and asks the user to confirm
- **Memory conflict detection** — Automatically checks for similar existing memories in `chat:*` spaces and surfaces conflicts so the agent can decide whether to update or append
```

- [ ] **Step 31: Mirror changes to README.zh-CN.md**

Same structure updates in Chinese.

- [ ] **Step 32: Commit**

```bash
git add README.md README.zh-CN.md
git commit -m "docs: add Smithery badge, document content guard and conflict detection"
```

### Task 7: Registry submission instructions

- [ ] **Step 33: Verify smithery.yaml is ready**

Run: `cat smithery.yaml` — confirm it has correct `startCommand`, `configSchema`, and `commandFunction`.

The existing `smithery.yaml` is already correct. No code changes needed.

**Manual steps (not automated):**

1. **Smithery.ai**: Go to https://smithery.ai/new and submit the GitHub repo URL `https://github.com/tt-a1i/evermemos-mcp`. Smithery reads `smithery.yaml` automatically.

2. **mcp.so**: Go to https://mcp.so/submit (or equivalent) and submit the same repo URL. May need to provide: name, description, category (Knowledge & Memory).

These are manual web form submissions, not code changes.

### Task 8: Final verification

- [ ] **Step 34: Run full test suite**

Run: `uv run pytest tests/ -v`
Expected: All PASS

- [ ] **Step 35: Run lint**

Run: `uv run ruff check`
Expected: No errors

- [ ] **Step 36: Verify git log**

Run: `git log --oneline -10`
Expected: 5 new commits on top of `c96e418`.
