"""Tests for space_catalog_service: recovery, parsing, helpers."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest

import evermemos_mcp.space_catalog_service as catalog_module
from evermemos_mcp.evermemos_client import EverMemosClient, EverMemosError
from evermemos_mcp.space_catalog_service import (
    SpaceCatalogService,
    from_group_id,
    to_group_id,
)


# -- helper functions --


def test_to_group_id():
    assert to_group_id("coding:myapp") == "space::coding:myapp"
    assert to_group_id("chat:daily") == "space::chat:daily"


def test_from_group_id():
    assert from_group_id("space::coding:myapp") == "coding:myapp"
    assert from_group_id("space::chat:daily") == "chat:daily"


def test_from_group_id_filters_catalog():
    assert from_group_id("space::catalog") is None
    assert from_group_id("space::catalog:extra") is None


def test_from_group_id_filters_non_space():
    assert from_group_id("other-prefix") is None
    assert from_group_id("") is None


# -- catalog: in-memory operations --


@pytest.mark.asyncio
async def test_register_and_list():
    client = AsyncMock(spec=EverMemosClient)
    client.add_message = AsyncMock(return_value={"status": "queued"})
    client.set_conversation_metadata = AsyncMock(
        return_value={"status": "ok", "result": {"id": "meta-1"}}
    )
    client.update_conversation_metadata = AsyncMock(
        return_value={"status": "ok", "result": {"id": "meta-1"}}
    )
    client.search_memories = AsyncMock(
        return_value={"result": {"memories": [], "pending_messages": []}}
    )
    catalog = SpaceCatalogService(client)

    info = await catalog.register_space("coding:app", "My React app")
    assert info.space_id == "coding:app"
    assert info.description == "My React app"
    assert info.last_used_at != ""

    spaces = await catalog.list_spaces()
    assert len(spaces) == 1
    assert spaces[0].space_id == "coding:app"
    client.set_conversation_metadata.assert_called()


@pytest.mark.asyncio
async def test_register_falls_back_to_update_conversation_metadata():
    client = AsyncMock(spec=EverMemosClient)
    client.add_message = AsyncMock(return_value={"status": "queued"})
    client.set_conversation_metadata = AsyncMock(
        side_effect=EverMemosError("exists", code="INVALID_PARAMETER", status_code=400)
    )
    client.update_conversation_metadata = AsyncMock(
        return_value={"status": "ok", "result": {"id": "meta-1"}}
    )
    catalog = SpaceCatalogService(client)

    await catalog.register_space("coding:app", "My React app")

    client.set_conversation_metadata.assert_called_once()
    client.update_conversation_metadata.assert_called_once()


@pytest.mark.asyncio
async def test_register_meta_update_failure_does_not_block():
    client = AsyncMock(spec=EverMemosClient)
    client.add_message = AsyncMock(return_value={"status": "queued"})
    client.set_conversation_metadata = AsyncMock(
        side_effect=EverMemosError("exists", code="INVALID_PARAMETER", status_code=400)
    )
    client.update_conversation_metadata = AsyncMock(
        side_effect=EverMemosError("network", code="UPSTREAM_UNAVAILABLE")
    )
    catalog = SpaceCatalogService(client)

    info = await catalog.register_space("coding:app", "My React app")

    assert info.space_id == "coding:app"
    client.set_conversation_metadata.assert_called_once()
    client.update_conversation_metadata.assert_called_once()


@pytest.mark.asyncio
async def test_register_does_not_patch_after_set_network_failure():
    client = AsyncMock(spec=EverMemosClient)
    client.add_message = AsyncMock(return_value={"status": "queued"})
    client.set_conversation_metadata = AsyncMock(
        side_effect=EverMemosError("network", code="UPSTREAM_UNAVAILABLE")
    )
    client.update_conversation_metadata = AsyncMock(
        return_value={"status": "ok", "result": {"id": "meta-1"}}
    )
    catalog = SpaceCatalogService(client)

    info = await catalog.register_space("coding:app", "My React app")

    assert info.space_id == "coding:app"
    client.set_conversation_metadata.assert_called_once()
    client.update_conversation_metadata.assert_not_called()


@pytest.mark.asyncio
async def test_register_passes_llm_custom_setting(monkeypatch):
    monkeypatch.setattr(
        catalog_module,
        "EVERMEMOS_LLM_CUSTOM_SETTING",
        {
            "boundary": {
                "provider": "openrouter",
                "model": "openai/gpt-4.1-mini",
            }
        },
    )

    client = AsyncMock(spec=EverMemosClient)
    client.add_message = AsyncMock(return_value={"status": "queued"})
    client.set_conversation_metadata = AsyncMock(
        return_value={"status": "ok", "result": {"id": "meta-1"}}
    )
    catalog = SpaceCatalogService(client)

    await catalog.register_space("coding:app", "My React app")

    _, kwargs = client.set_conversation_metadata.call_args
    assert kwargs["llm_custom_setting"] is not None


@pytest.mark.asyncio
async def test_register_passes_user_details(monkeypatch):
    monkeypatch.setattr(
        catalog_module,
        "EVERMEMOS_USER_DETAILS",
        {
            "mcp-user": {
                "full_name": "Test User",
                "role": "user",
            }
        },
    )

    client = AsyncMock(spec=EverMemosClient)
    client.add_message = AsyncMock(return_value={"status": "queued"})
    client.set_conversation_metadata = AsyncMock(
        return_value={"status": "ok", "result": {"id": "meta-1"}}
    )
    catalog = SpaceCatalogService(client)

    await catalog.register_space("coding:app", "My React app")

    _, kwargs = client.set_conversation_metadata.call_args
    assert kwargs["user_details"]["mcp-user"]["full_name"] == "Test User"


@pytest.mark.asyncio
async def test_ensure_conversation_meta_adds_dynamic_actor_to_user_details(monkeypatch):
    monkeypatch.setattr(
        catalog_module,
        "EVERMEMOS_USER_DETAILS",
        {
            "mcp-user": {
                "full_name": "Default User",
                "role": "user",
            }
        },
    )

    client = AsyncMock(spec=EverMemosClient)
    client.set_conversation_metadata = AsyncMock(
        return_value={"status": "ok", "result": {"id": "meta-1"}}
    )
    catalog = SpaceCatalogService(client)

    await catalog.ensure_conversation_meta(
        "coding:app",
        actor_user_id="alice",
        actor_role="assistant",
    )

    _, kwargs = client.set_conversation_metadata.call_args
    user_details = kwargs["user_details"]
    assert user_details["mcp-user"]["full_name"] == "Default User"
    assert user_details["alice"]["role"] == "assistant"
    assert user_details["alice"]["full_name"] == "alice"


@pytest.mark.asyncio
async def test_register_updates_description():
    client = AsyncMock(spec=EverMemosClient)
    client.add_message = AsyncMock(return_value={"status": "queued"})
    catalog = SpaceCatalogService(client)

    await catalog.register_space("s1", "old desc")
    await catalog.register_space("s1", "new desc")

    info = catalog.get_space("s1")
    assert info is not None
    assert info.description == "new desc"


@pytest.mark.asyncio
async def test_ensure_space_no_cloud_write():
    client = AsyncMock(spec=EverMemosClient)
    catalog = SpaceCatalogService(client)

    info = catalog.ensure_space("test:ephemeral")
    assert info.space_id == "test:ephemeral"
    # No Cloud call should have been made
    client.add_message.assert_not_called()


@pytest.mark.asyncio
async def test_list_spaces_query_filter():
    client = AsyncMock(spec=EverMemosClient)
    client.add_message = AsyncMock(return_value={"status": "queued"})
    client.search_memories = AsyncMock(
        return_value={"result": {"memories": [], "pending_messages": []}}
    )
    catalog = SpaceCatalogService(client)

    await catalog.register_space("coding:app", "React frontend")
    await catalog.register_space("study:ml", "Machine learning notes")

    spaces = await catalog.list_spaces(query="react")
    assert len(spaces) == 1
    assert spaces[0].space_id == "coding:app"


def test_adjust_memory_count_increments_and_never_negative():
    client = AsyncMock(spec=EverMemosClient)
    catalog = SpaceCatalogService(client)

    catalog.adjust_memory_count("coding:app", 2)
    info = catalog.get_space("coding:app")
    assert info is not None
    assert info.memory_count == 2

    catalog.adjust_memory_count("coding:app", -5)
    info = catalog.get_space("coding:app")
    assert info is not None
    assert info.memory_count == 0


def test_adjust_memory_count_negative_unknown_space_is_noop():
    client = AsyncMock(spec=EverMemosClient)
    catalog = SpaceCatalogService(client)

    catalog.adjust_memory_count("coding:missing", -1)
    assert catalog.get_space("coding:missing") is None


@pytest.mark.asyncio
async def test_persist_failure_does_not_block():
    """register_space should succeed even if Cloud write fails."""
    client = AsyncMock(spec=EverMemosClient)
    client.add_message = AsyncMock(
        side_effect=EverMemosError("network down", code="UPSTREAM_UNAVAILABLE")
    )
    catalog = SpaceCatalogService(client)

    info = await catalog.register_space("coding:app", "My app")
    assert info.space_id == "coding:app"


# -- catalog: recovery from flat search results --


@pytest.mark.asyncio
async def test_recover_from_flat_search_items():
    """Recovery should parse flat items (memory_type/summary/atomic_fact)."""
    client = AsyncMock(spec=EverMemosClient)
    client.search_memories = AsyncMock(
        return_value={
            "result": {
                "memories": [
                    {
                        "memory_type": "episodic_memory",
                        "id": "mem1",
                        "summary": "Registered memory space: coding:app — My React project",
                        "timestamp": "2026-02-10T10:00:00Z",
                        "score": 4.5,
                    },
                    {
                        "memory_type": "event_log",
                        "id": "mem2",
                        "atomic_fact": "Registered memory space: study:ml — ML course notes",
                        "timestamp": "2026-02-10T11:00:00Z",
                        "score": 3.2,
                    },
                ],
                "pending_messages": [],
            }
        }
    )
    client.get_conversation_metadata = AsyncMock(
        return_value={
            "status": "ok",
            "result": {
                "description": "My React project from meta",
                "updated_at": "2026-02-10T12:00:00Z",
            },
        }
    )
    catalog = SpaceCatalogService(client)

    spaces = await catalog.list_spaces()  # triggers recovery
    assert len(spaces) == 2
    ids = {s.space_id for s in spaces}
    assert ids == {"coding:app", "study:ml"}

    app = catalog.get_space("coding:app")
    assert app is not None
    assert app.description == "My React project from meta"
    assert app.created_at == "2026-02-10T10:00:00Z"


@pytest.mark.asyncio
async def test_recover_from_pending_messages():
    """Recovery should parse pending_messages (not-yet-extracted raw content)."""
    client = AsyncMock(spec=EverMemosClient)
    client.search_memories = AsyncMock(
        return_value={
            "result": {
                "memories": [],
                "pending_messages": [
                    {
                        "content": "Registered memory space: chat:daily — Daily chat log",
                        "created_at": "2026-02-11T08:00:00Z",
                    },
                ],
            }
        }
    )
    catalog = SpaceCatalogService(client)

    spaces = await catalog.list_spaces()
    assert len(spaces) == 1
    assert spaces[0].space_id == "chat:daily"
    assert spaces[0].description == "Daily chat log"
    assert spaces[0].created_at == "2026-02-11T08:00:00Z"


@pytest.mark.asyncio
async def test_recover_deduplicates_latest_wins():
    """Same space in both extracted and pending: newer timestamp wins."""
    client = AsyncMock(spec=EverMemosClient)
    client.search_memories = AsyncMock(
        return_value={
            "result": {
                "memories": [
                    {
                        "memory_type": "episodic_memory",
                        "summary": "Registered memory space: coding:app — My app",
                        "timestamp": "2026-02-10T10:00:00Z",
                    },
                ],
                "pending_messages": [
                    {
                        "content": "Registered memory space: coding:app — My app updated",
                        "created_at": "2026-02-11T08:00:00Z",
                    },
                ],
            }
        }
    )
    catalog = SpaceCatalogService(client)

    spaces = await catalog.list_spaces()
    assert len(spaces) == 1
    # Pending message has newer timestamp → description updated
    assert spaces[0].description == "My app updated"
    assert spaces[0].last_used_at == "2026-02-11T08:00:00Z"


@pytest.mark.asyncio
async def test_recover_handles_api_failure():
    """Recovery failure should not crash list_spaces."""
    client = AsyncMock(spec=EverMemosClient)
    client.search_memories = AsyncMock(
        side_effect=EverMemosError("unavailable", code="UPSTREAM_UNAVAILABLE")
    )
    catalog = SpaceCatalogService(client)

    spaces = await catalog.list_spaces()
    assert spaces == []


@pytest.mark.asyncio
async def test_recover_skips_no_description_entries():
    """'no description' sentinel should be treated as empty."""
    client = AsyncMock(spec=EverMemosClient)
    client.search_memories = AsyncMock(
        return_value={
            "result": {
                "memories": [
                    {
                        "memory_type": "event_log",
                        "atomic_fact": "Registered memory space: test:bare — no description",
                        "timestamp": "2026-02-10T10:00:00Z",
                    },
                ],
                "pending_messages": [],
            }
        }
    )
    catalog = SpaceCatalogService(client)

    spaces = await catalog.list_spaces()
    assert len(spaces) == 1
    assert spaces[0].description == ""


# -- regression: hyphenated space_ids --


@pytest.mark.asyncio
async def test_recover_hyphenated_space_id():
    """space_ids with hyphens (e.g. coding:my-app) must not be split at the hyphen."""
    client = AsyncMock(spec=EverMemosClient)
    client.search_memories = AsyncMock(
        return_value={
            "result": {
                "memories": [
                    {
                        "memory_type": "event_log",
                        "atomic_fact": (
                            "Registered memory space: coding:my-app"
                            " — React frontend project"
                        ),
                        "timestamp": "2026-02-10T10:00:00Z",
                    },
                    {
                        "memory_type": "episodic_memory",
                        "summary": (
                            "Registered memory space: study:deep-learning"
                            " — ML course notes"
                        ),
                        "timestamp": "2026-02-10T11:00:00Z",
                    },
                ],
                "pending_messages": [
                    {
                        "content": (
                            "Registered memory space: chat:work-life-balance"
                            " — Daily reflections"
                        ),
                        "created_at": "2026-02-11T09:00:00Z",
                    },
                ],
            }
        }
    )
    catalog = SpaceCatalogService(client)
    spaces = await catalog.list_spaces()

    ids = {s.space_id for s in spaces}
    assert ids == {"coding:my-app", "study:deep-learning", "chat:work-life-balance"}

    app = catalog.get_space("coding:my-app")
    assert app is not None
    assert app.description == "React frontend project"
    assert app.last_used_at == "2026-02-10T10:00:00Z"


# -- recovery retry after transient failure --


@pytest.mark.asyncio
async def test_recover_retries_after_cooldown():
    """First recovery failure should not permanently disable recovery."""
    call_count = 0

    async def search_side_effect(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise EverMemosError("network blip", code="UPSTREAM_UNAVAILABLE")
        return {
            "result": {
                "memories": [
                    {
                        "memory_type": "event_log",
                        "atomic_fact": "Registered memory space: coding:app — My app",
                        "timestamp": "2026-02-10T10:00:00Z",
                    },
                ],
                "pending_messages": [],
            }
        }

    client = AsyncMock(spec=EverMemosClient)
    client.search_memories = AsyncMock(side_effect=search_side_effect)
    catalog = SpaceCatalogService(client)

    # First call: recovery fails
    spaces = await catalog.list_spaces()
    assert spaces == []
    assert call_count == 1

    # Immediately after: cooldown blocks retry
    spaces = await catalog.list_spaces()
    assert spaces == []
    assert call_count == 1  # no new call

    # Fast-forward past cooldown
    catalog._recover_failed_at = 0.0  # simulate cooldown expired

    # Third call: recovery succeeds
    spaces = await catalog.list_spaces()
    assert len(spaces) == 1
    assert spaces[0].space_id == "coding:app"
    assert call_count == 2


# -- regression: recovery not blocked by non-empty cache --


@pytest.mark.asyncio
async def test_recover_runs_even_when_cache_has_entries():
    """Recovery should still run after ensure_space populated the cache.

    Previously, `if not self._cache` blocked recovery when remember was called
    before list_spaces.
    """
    client = AsyncMock(spec=EverMemosClient)
    client.search_memories = AsyncMock(
        return_value={
            "result": {
                "memories": [
                    {
                        "memory_type": "event_log",
                        "atomic_fact": "Registered memory space: study:ml — ML course",
                        "timestamp": "2026-02-10T10:00:00Z",
                    },
                ],
                "pending_messages": [],
            }
        }
    )
    catalog = SpaceCatalogService(client)

    # Simulate: remember was called first, populating cache with one space
    catalog.ensure_space("coding:app")
    assert len(catalog._cache) == 1

    # list_spaces should still trigger recovery and merge the historical space
    spaces = await catalog.list_spaces()
    ids = {s.space_id for s in spaces}
    assert "coding:app" in ids  # from ensure_space
    assert "study:ml" in ids  # from recovery
    assert len(spaces) == 2

    # Recovery search was actually called
    client.search_memories.assert_called_once()


@pytest.mark.asyncio
async def test_recover_from_paginated_fetch_without_topk_truncation():
    total = 220

    def _structured_entry(index: int) -> str:
        payload = {
            "version": 1,
            "space_id": f"bulk:space-{index}",
            "description": f"Bulk space {index}",
            "created_at": "2026-02-10T10:00:00+00:00",
            "updated_at": "2026-02-10T10:00:00+00:00",
        }
        return f"{catalog_module._ENTRY_JSON_PREFIX}{json.dumps(payload)}"

    async def fetch_side_effect(
        group_id, *, memory_type="episodic_memory", limit=40, offset=0, **kwargs
    ):
        if group_id != "space::catalog":
            return {"result": {"memories": [], "count": 0, "total_count": 0}}

        if memory_type == "event_log":
            if offset >= total:
                return {"result": {"memories": [], "count": 0, "total_count": total}}

            end = min(offset + limit, total)
            memories = [
                {
                    "memory_type": "event_log",
                    "atomic_fact": _structured_entry(i),
                    "timestamp": "2026-02-10T10:00:00+00:00",
                }
                for i in range(offset, end)
            ]
            return {
                "result": {
                    "memories": memories,
                    "count": len(memories),
                    "total_count": total,
                }
            }

        return {"result": {"memories": [], "count": 0, "total_count": 0}}

    client = AsyncMock(spec=EverMemosClient)
    client.fetch_memories = AsyncMock(side_effect=fetch_side_effect)
    client.search_memories = AsyncMock(
        return_value={"result": {"pending_messages": []}}
    )
    client.get_conversation_metadata = AsyncMock(
        return_value={"status": "ok", "result": {}}
    )

    catalog = SpaceCatalogService(client)
    spaces = await catalog.list_spaces(limit=500)

    assert len(spaces) == total
    assert catalog.get_space("bulk:space-0") is not None
    assert catalog.get_space("bulk:space-219") is not None


@pytest.mark.asyncio
async def test_conversation_meta_enrich_is_capped_for_large_catalog():
    memories = []
    for i in range(120):
        memories.append(
            {
                "memory_type": "event_log",
                "atomic_fact": f"Registered memory space: cap:space-{i} — desc {i}",
                "timestamp": "2026-02-10T10:00:00Z",
            }
        )

    client = AsyncMock(spec=EverMemosClient)
    client.fetch_memories = AsyncMock(return_value={"invalid": True})
    client.search_memories = AsyncMock(
        return_value={"result": {"memories": memories, "pending_messages": []}}
    )
    client.get_conversation_metadata = AsyncMock(
        return_value={"status": "ok", "result": {}}
    )

    catalog = SpaceCatalogService(client)
    spaces = await catalog.list_spaces(limit=500)

    assert len(spaces) == 120
    assert (
        client.get_conversation_metadata.call_count
        <= catalog_module._META_ENRICH_MAX_SPACES
    )
