# Fix Forget: Use parent_id (memcell ID) for Deletion

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the `forget` tool actually delete memories by sending the correct ID (memcell `parent_id`) to the EverMemOS Cloud DELETE API.

**Architecture:** EverMemOS Cloud stores memories in a hierarchy: one *memcell* (identified by `parent_id`) produces multiple derived records (episodic_memory, event_log, profile). The DELETE API expects the memcell ID, not the derived record ID. We need to: (1) extract and expose `parent_id` from API responses, (2) use `parent_id` as the primary delete key in `forget()`, (3) fall back to the raw `id` if `parent_id` is absent, (4) parse the real affected count from the `message` string since `result.count` is always 0.

**Tech Stack:** Python 3.11, pytest, pytest-asyncio

---

## File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `src/evermemos_mcp/memory_service.py` | Modify | Add `_extract_parent_id()`, expose `parent_id` in row outputs, rewrite `forget()` delete key resolution, parse message-based count |
| `src/evermemos_mcp/server.py` | Modify | Update `forget` tool description to reflect honest boundaries (parent_id optional, 100-item scan window, user_id not sent, may be unmatched) |
| `tests/test_memory_service.py` | Modify | Add tests for parent_id extraction, row exposure, forget with parent_id fallback, message count parsing |

---

## Chunk 1: Extract and expose parent_id

### Task 1: Add `_extract_parent_id` helper and expose it in row outputs

**Files:**
- Modify: `src/evermemos_mcp/memory_service.py:532-551` (near `_extract_memory_id`)
- Modify: `src/evermemos_mcp/memory_service.py:996-1024` (`_map_fetch_memory_item_to_row`)
- Modify: `src/evermemos_mcp/memory_service.py:1026-1130` (`_map_search_response_to_results`)
- Test: `tests/test_memory_service.py`

- [ ] **Step 1: Write failing tests for `_extract_parent_id`**

```python
def test_extract_parent_id_from_top_level():
    assert MemoryService._extract_parent_id({"parent_id": "mc-001"}) == "mc-001"


def test_extract_parent_id_from_metadata():
    assert (
        MemoryService._extract_parent_id(
            {"metadata": {"parent_id": "mc-002"}}
        )
        == "mc-002"
    )


def test_extract_parent_id_prefers_top_level():
    assert (
        MemoryService._extract_parent_id(
            {"parent_id": "mc-top", "metadata": {"parent_id": "mc-meta"}}
        )
        == "mc-top"
    )


def test_extract_parent_id_returns_none_when_missing():
    assert MemoryService._extract_parent_id({}) is None
    assert MemoryService._extract_parent_id({"parent_id": ""}) is None
    assert MemoryService._extract_parent_id({"parent_id": "  "}) is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_memory_service.py::test_extract_parent_id_from_top_level -v`
Expected: FAIL — `_extract_parent_id` does not exist.

- [ ] **Step 3: Implement `_extract_parent_id`**

Add this method to `MemoryService` right after `_extract_memory_id` (after line 551):

```python
@staticmethod
def _extract_parent_id(item: dict) -> str | None:
    """Extract memcell parent_id — the ID that Cloud DELETE API expects."""
    direct = MemoryService._pick_non_empty_string(item, "parent_id")
    if direct:
        return direct
    metadata = item.get("metadata")
    return MemoryService._pick_non_empty_string(metadata, "parent_id")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_memory_service.py -k "extract_parent_id" -v`
Expected: 4 PASSED.

- [ ] **Step 5: Write failing tests for parent_id in row outputs**

```python
def test_fetch_history_row_includes_parent_id():
    item = {
        "id": "ep-001",
        "parent_type": "memcell",
        "parent_id": "mc-001",
        "summary": "test memory",
        "timestamp": "2026-01-01T00:00:00Z",
    }
    row = MemoryService._map_fetch_memory_item_to_row(
        item, memory_type="episodic_memory", include_metadata=False
    )
    assert row["parent_id"] == "mc-001"


def test_fetch_history_row_omits_parent_id_when_absent():
    item = {"id": "ep-002", "summary": "no parent", "timestamp": ""}
    row = MemoryService._map_fetch_memory_item_to_row(
        item, memory_type="episodic_memory", include_metadata=False
    )
    assert "parent_id" not in row
```

- [ ] **Step 6: Run tests to verify they fail**

Run: `uv run pytest tests/test_memory_service.py::test_fetch_history_row_includes_parent_id -v`
Expected: FAIL — `parent_id` not in row.

- [ ] **Step 7: Add parent_id to `_map_fetch_memory_item_to_row`**

In `_map_fetch_memory_item_to_row` (around line 1017), after the `source_message_id` block, add:

```python
parent_id = MemoryService._extract_parent_id(item)
if parent_id:
    row["parent_id"] = parent_id
```

- [ ] **Step 8: Add parent_id to `_map_search_response_to_results`**

In `_map_search_response_to_results`, in the `memory_items` loop (around line 1082), after the `source_message_id` block, add:

```python
parent_id = MemoryService._extract_parent_id(item)
if parent_id:
    row["parent_id"] = parent_id
```

And in the `profiles` loop (around line 1114), after `source_message_id`, add the same:

```python
parent_id = MemoryService._extract_parent_id(profile)
if parent_id:
    row["parent_id"] = parent_id
```

- [ ] **Step 9: Run all tests**

Run: `uv run pytest tests/test_memory_service.py -v`
Expected: ALL PASSED (including new tests).

- [ ] **Step 10: Commit**

```bash
git add src/evermemos_mcp/memory_service.py tests/test_memory_service.py
git commit -m "feat: extract and expose parent_id (memcell ID) in memory rows"
```

---

## Chunk 2: Fix forget to use parent_id and parse message count

### Task 2: Rewrite forget delete-key resolution

The core fix: when `forget()` receives memory IDs from the agent, it should first look up whether a `parent_id` is available for each ID by doing a lightweight `fetch_memories` call, then use the `parent_id` for deletion. If no parent_id is found, fall back to the original ID.

Also fix count parsing: Cloud always returns `result.count: 0` but puts the real count in the `message` string like `"Delete operation completed, 17 records affected"`.

**Files:**
- Modify: `src/evermemos_mcp/memory_service.py` — `forget()` method (lines 2352-2535)
- Test: `tests/test_memory_service.py`

- [ ] **Step 1: Write failing test for message-based count parsing**

```python
def test_parse_delete_affected_count_from_message():
    assert MemoryService._parse_delete_affected_count(
        {"message": "Delete operation completed, 17 records affected", "result": {"count": 0}}
    ) == 17


def test_parse_delete_affected_count_falls_back_to_result_count():
    assert MemoryService._parse_delete_affected_count(
        {"message": "ok", "result": {"count": 3}}
    ) == 3


def test_parse_delete_affected_count_zero_when_unparseable():
    assert MemoryService._parse_delete_affected_count({}) == 0
    assert MemoryService._parse_delete_affected_count(
        {"message": "no match here", "result": {"count": 0}}
    ) == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_memory_service.py::test_parse_delete_affected_count_from_message -v`
Expected: FAIL — method does not exist.

- [ ] **Step 3: Implement `_parse_delete_affected_count`**

Add near the top of `MemoryService` class (after other static helpers):

```python
_DELETE_AFFECTED_RE = re.compile(r"(\d+)\s+records?\s+affected")

@staticmethod
def _parse_delete_affected_count(result: dict) -> int:
    """Parse actual affected count from Cloud DELETE response.

    Cloud v0 always returns result.count=0 but puts the real count
    in the message string like "Delete operation completed, 17 records affected".
    """
    message = result.get("message", "")
    if isinstance(message, str):
        match = MemoryService._DELETE_AFFECTED_RE.search(message)
        if match:
            parsed = int(match.group(1))
            if parsed > 0:
                return parsed
    count = result.get("result", {}).get("count", 0)
    return max(0, count) if isinstance(count, int) else 0
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_memory_service.py -k "parse_delete_affected" -v`
Expected: 3 PASSED.

- [ ] **Step 5: Write failing tests for forget with parent_id resolution**

```python
@pytest.mark.asyncio
async def test_forget_resolves_parent_id_for_deletion():
    """When agent passes a memory id, forget should look up parent_id and use it."""
    fetch_response = {
        "result": {
            "memories": [
                {"id": "ep-001", "parent_type": "memcell", "parent_id": "mc-001", "summary": "test"},
            ]
        }
    }

    async def mock_fetch(group_ids=None, *, group_id=None, memory_type="episodic_memory", **kw):
        return fetch_response

    delete_calls = []

    async def mock_delete(*, memory_id=None, group_id=None, user_id=None):
        delete_calls.append(memory_id)
        return {"message": "Delete operation completed, 5 records affected", "result": {"count": 0}}

    svc, client = _make_svc()
    client.fetch_memories = AsyncMock(side_effect=mock_fetch)
    client.delete_memories = AsyncMock(side_effect=mock_delete)
    svc._catalog.ensure_space("coding:app")

    result = await svc.forget(["ep-001"], "coding:app")

    assert result["ok"] is True
    assert result["deleted_count"] == 5
    # Should have used parent_id mc-001, not the original ep-001
    assert "mc-001" in delete_calls


@pytest.mark.asyncio
async def test_forget_falls_back_to_original_id_when_no_parent():
    """If parent_id is not found, use the original memory_id."""
    fetch_response = {"result": {"memories": []}}

    svc, client = _make_svc()
    client.fetch_memories = AsyncMock(return_value=fetch_response)
    client.delete_memories = AsyncMock(
        return_value={"message": "Delete operation completed, 1 records affected", "result": {"count": 0}}
    )
    svc._catalog.ensure_space("coding:app")

    result = await svc.forget(["orphan-id"], "coding:app")
    assert result["ok"] is True
    _, kwargs = client.delete_memories.call_args
    assert kwargs["memory_id"] == "orphan-id"
```

- [ ] **Step 6: Run tests to verify they fail**

Run: `uv run pytest tests/test_memory_service.py::test_forget_resolves_parent_id_for_deletion -v`
Expected: FAIL — forget does not resolve parent_id yet.

- [ ] **Step 7: Implement the fix in `forget()`**

Replace the `forget()` method body. Key changes:

1. Before deleting, do a batch lookup across memory types to build an `id → parent_id` mapping.
2. For each memory_id, prefer `parent_id` if available.
3. Use `_parse_delete_affected_count` instead of `result["result"]["count"]`.
4. Remove the `user_id` from DELETE calls (our tests showed `memory_id + user_id` returns 0 even with correct parent_id; `memory_id + group_id` works).

The updated `forget` method:

```python
async def forget(
    self,
    memory_ids: list[str],
    space_id: str,
    *,
    reason: str | None = None,
    user_id: str | None = None,
) -> dict:
    space_id = self._validate_space_id(space_id)
    user_id = self._validate_user_id(user_id)
    if not isinstance(memory_ids, list) or not memory_ids:
        raise EverMemosError(
            "memory_ids must be a non-empty array",
            code="INVALID_INPUT",
        )
    if reason is not None and not isinstance(reason, str):
        raise EverMemosError(
            "reason must be a string when provided",
            code="INVALID_INPUT",
        )

    unique_ids: list[str] = []
    seen: set[str] = set()
    for raw_id in memory_ids:
        if not isinstance(raw_id, str) or not raw_id.strip():
            raise EverMemosError(
                "memory_ids must contain non-empty strings",
                code="INVALID_INPUT",
            )
        mid = raw_id.strip()
        if mid in seen:
            continue
        seen.add(mid)
        unique_ids.append(mid)

    group_id = to_group_id(space_id)

    # -- Resolve parent_ids (memcell IDs) for deletion --
    id_to_parent: dict[str, str] = {}
    id_to_parent = await self._resolve_parent_ids(group_id, unique_ids)

    errors: list[str] = []
    unmatched_ids: list[str] = []
    warnings: list[str] = []

    semaphore = asyncio.Semaphore(_FORGET_DELETE_CONCURRENCY)

    async def _delete_one(
        mid: str,
    ) -> tuple[str, int, EverMemosError | None]:
        async with semaphore:
            # Prefer parent_id (memcell ID) — the key Cloud DELETE actually uses
            delete_key = id_to_parent.get(mid, mid)
            try:
                result = await self._client.delete_memories(
                    memory_id=delete_key,
                    group_id=group_id,
                )
            except EverMemosError as e:
                return mid, 0, e
            except Exception as e:  # pragma: no cover
                return mid, 0, EverMemosError(
                    f"unexpected delete error: {e}",
                    code="UPSTREAM_ERROR",
                )

            affected = self._parse_delete_affected_count(result)
            return mid, affected, None

    delete_results = await asyncio.gather(
        *(_delete_one(mid) for mid in unique_ids)
    )

    total_affected = 0
    logical_deleted = 0
    for mid, affected, err in delete_results:
        total_affected += affected
        if err is not None:
            errors.append(f"{mid}: {err}")
        elif affected > 0:
            logical_deleted += 1
        else:
            unmatched_ids.append(mid)

    if logical_deleted:
        self._catalog.adjust_memory_count(space_id, -logical_deleted)

    if unmatched_ids:
        warnings.append(
            "Some memory IDs were not matched by upstream delete."
        )

    normalized_reason = reason.strip() if isinstance(reason, str) else ""
    if normalized_reason:
        logger.info(
            "forget called with reason in space %s for %d memory ids",
            space_id,
            len(unique_ids),
        )

    output: dict = {
        "ok": len(errors) == 0,
        "space_id": space_id,
        "deleted_count": total_affected,
    }
    if unmatched_ids:
        output["unmatched_ids"] = unmatched_ids
        output["unmatched_count"] = len(unmatched_ids)
    if normalized_reason:
        output["reason_logged"] = True
    if errors:
        output["errors"] = errors
    if warnings:
        output["warnings"] = warnings
    return output
```

- [ ] **Step 8: Implement `_resolve_parent_ids` helper**

Add this method to `MemoryService`:

```python
async def _resolve_parent_ids(
    self,
    group_id: str,
    memory_ids: list[str],
) -> dict[str, str]:
    """Look up memcell parent_id for each memory_id by scanning recent memories."""
    target_set = set(memory_ids)
    id_to_parent: dict[str, str] = {}

    # Any id that is already a parent_id of something else should be used directly
    # We scan the main memory types to build the mapping
    fetch_types = ("episodic_memory", "event_log", "profile", "foresight")
    fetch_results = await asyncio.gather(
        *(
            self._client.fetch_memories(
                group_id, memory_type=mt, limit=100, offset=0
            )
            for mt in fetch_types
        ),
        return_exceptions=True,
    )

    known_parent_ids: set[str] = set()
    for fetch_result in fetch_results:
        if isinstance(fetch_result, BaseException):
            continue
        if not isinstance(fetch_result, dict):
            continue
        memories = fetch_result.get("result", {}).get("memories", [])
        if not isinstance(memories, list):
            continue
        for item in memories:
            if not isinstance(item, dict):
                continue
            item_id = self._extract_memory_id(item)
            parent_id = self._extract_parent_id(item)
            if parent_id:
                known_parent_ids.add(parent_id)
            if item_id and item_id in target_set and parent_id:
                id_to_parent[item_id] = parent_id

    # If an input id is itself a known parent_id, map it to itself
    for mid in memory_ids:
        if mid in known_parent_ids and mid not in id_to_parent:
            id_to_parent[mid] = mid

    return id_to_parent
```

- [ ] **Step 9: Run all tests**

Run: `uv run pytest tests/test_memory_service.py -v`
Expected: ALL PASSED. Some existing forget tests may need minor adjustments because:
- `deleted_count` is now parsed from `message` (default mock returns `{"result": {"count": 1}}` which still works for old tests since `_parse_delete_affected_count` falls back to `result.count`).
- `delete_scope_user_id` is no longer emitted (removed `user_id` from delete calls).
- Some tests assert `client.delete_memories.call_count` — still correct.

Fix any failing existing tests by adjusting expected values. The `_make_svc` default `delete_rv` of `{"result": {"count": 1}}` will still parse to count=1 via the fallback path.

- [ ] **Step 10: Run full test suite + lint**

Run: `uv run ruff check && uv run pytest -v`
Expected: All checks passed, all tests pass.

- [ ] **Step 11: Commit**

```bash
git add src/evermemos_mcp/memory_service.py tests/test_memory_service.py
git commit -m "fix: forget uses parent_id (memcell ID) for Cloud deletion and parses message-based count"
```

---

## Chunk 3: Update tool description and cleanup

### Task 3: Update forget tool description

**Files:**
- Modify: `src/evermemos_mcp/server.py:341-379` (forget tool definition)

- [ ] **Step 1: Update tool description**

Replace the `forget` tool description in `server.py`. Key boundaries the description must reflect:

- "Request deletion" not "Delete" — operation is not guaranteed
- parent_id is **optional** ("results may include"), not every row has it
- 100-item-per-type scan window is explicit
- user_id is not sent to Cloud DELETE (upstream compatibility)
- Some IDs may remain unmatched

See `src/evermemos_mcp/server.py:341-381` for the actual deployed wording.

- [ ] **Step 2: Run server tool list test**

Run: `uv run pytest tests/test_server.py -v`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add src/evermemos_mcp/server.py
git commit -m "docs: update forget tool description to reflect parent_id delete semantics"
```

### Task 4: End-to-end verification (manual)

- [ ] **Step 1: Run full test suite**

Run: `uv run ruff check && uv run pytest -v`
Expected: All checks passed, all tests pass.

- [ ] **Step 2: Verify with real Cloud API**

Run the following to confirm the fix works against the live API:

```bash
uv run python -c "
import asyncio, json

async def e2e():
    from evermemos_mcp.evermemos_client import EverMemosClient
    from evermemos_mcp.memory_service import MemoryService
    from evermemos_mcp.space_catalog_service import SpaceCatalogService

    space_id = 'chat:preferences'
    async with EverMemosClient() as client:
        catalog = SpaceCatalogService(client)
        svc = MemoryService(client, catalog)

        h = await svc.fetch_history(space_id, memory_type='episodic_memory', limit=10)
        items = h.get('items', [])
        print(f'Before: {len(items)} items')
        for i in items:
            print(f'  id={i[\"memory_id\"]}  parent_id={i.get(\"parent_id\",\"\")}  snippet={i.get(\"snippet\",\"\")[:50]}')

        if items:
            target = items[0]['memory_id']
            print(f'Deleting: {target}')
            result = await svc.forget([target], space_id)
            print(json.dumps(result, ensure_ascii=False, indent=2))

            await asyncio.sleep(3)
            h2 = await svc.fetch_history(space_id, memory_type='episodic_memory', limit=10)
            print(f'After: {len(h2.get(\"items\", []))} items')

asyncio.run(e2e())
"
```

Expected: `deleted_count > 0`, item actually removed from fetch_history.

- [ ] **Step 3: Final commit if any adjustments needed**
