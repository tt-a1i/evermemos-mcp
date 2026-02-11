"""Tests for memory_service: tool logic with mocked Cloud API."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from evermemos_mcp.evermemos_client import EverMemosClient, EverMemosError
from evermemos_mcp.memory_service import MemoryService
from evermemos_mcp.space_catalog_service import SpaceCatalogService


def _make_svc(
    add_msg_rv=None,
    search_rv=None,
    fetch_rv=None,
    delete_rv=None,
):
    """Create a MemoryService with a fully mocked client."""
    client = AsyncMock(spec=EverMemosClient)
    client.user_id = "mcp-user"
    client.add_message = AsyncMock(
        return_value=add_msg_rv or {"status": "queued", "request_id": "req-123"}
    )
    client.search_memories = AsyncMock(
        return_value=search_rv or {"result": {"memories": [], "pending_messages": []}}
    )
    client.fetch_memories = AsyncMock(
        return_value=fetch_rv or {"result": {"memories": []}}
    )
    client.delete_memories = AsyncMock(
        return_value=delete_rv or {"result": {"count": 1}}
    )
    catalog = SpaceCatalogService(client)
    return MemoryService(client, catalog), client


# -- list_spaces --


@pytest.mark.asyncio
async def test_list_spaces_empty():
    svc, client = _make_svc()
    # Catalog recovery will try search and get empty results
    client.search_memories = AsyncMock(
        return_value={"result": {"memories": [], "pending_messages": []}}
    )
    result = await svc.list_spaces()
    assert result["ok"] is True
    assert result["spaces"] == []


@pytest.mark.asyncio
async def test_list_spaces_after_remember():
    svc, _ = _make_svc()
    await svc.remember("coding:app", "some content", description="My app")
    result = await svc.list_spaces()
    assert len(result["spaces"]) == 1
    assert result["spaces"][0]["space_id"] == "coding:app"
    assert result["spaces"][0]["description"] == "My app"


# -- remember --


@pytest.mark.asyncio
async def test_remember_returns_queued():
    svc, client = _make_svc()
    result = await svc.remember("coding:app", "We use FastAPI")
    assert result["ok"] is True
    assert result["space_id"] == "coding:app"
    assert result["message_id"] == "req-123"
    assert result["created_at"]
    assert (
        "queued" in result["processing_hint"].lower()
        or "minutes" in result["processing_hint"].lower()
    )

    # Verify Cloud call
    client.add_message.assert_called_once()
    call_kwargs = client.add_message.call_args
    assert call_kwargs.kwargs.get("flush") or call_kwargs[1].get("flush", True)


@pytest.mark.asyncio
async def test_remember_with_description_registers_space():
    svc, _ = _make_svc()
    await svc.remember("study:ml", "Neural nets", description="ML course")
    result = await svc.list_spaces()
    assert result["spaces"][0]["description"] == "ML course"


@pytest.mark.asyncio
async def test_remember_without_description_ensures_space():
    svc, _ = _make_svc()
    await svc.remember("chat:daily", "Hello world")
    result = await svc.list_spaces()
    assert result["spaces"][0]["space_id"] == "chat:daily"
    assert result["spaces"][0]["description"] == ""


# -- recall --


@pytest.mark.asyncio
async def test_recall_maps_search_results():
    search_response = {
        "result": {
            "memories": [
                {
                    "id": "mem-001",
                    "memory_type": "episodic_memory",
                    "summary": "User discussed FastAPI with SQLAlchemy",
                    "timestamp": "2026-02-10T10:00:00Z",
                    "score": 4.5,
                },
                {
                    "id": "mem-002",
                    "memory_type": "event_log",
                    "atomic_fact": "Project uses FastAPI",
                    "timestamp": "2026-02-10T10:01:00Z",
                    "score": 3.2,
                },
            ],
            "pending_messages": [],
        }
    }
    svc, _ = _make_svc(search_rv=search_response)
    svc._catalog.ensure_space("coding:app")

    result = await svc.recall("FastAPI", "coding:app")
    assert result["ok"] is True
    assert len(result["results"]) == 2

    r0 = result["results"][0]
    assert r0["memory_id"] == "mem-001"
    assert r0["memory_type"] == "episodic_memory"
    assert "FastAPI" in r0["snippet"]
    assert r0["score"] == 4.5

    r1 = result["results"][1]
    assert r1["memory_id"] == "mem-002"
    assert "FastAPI" in r1["snippet"]


@pytest.mark.asyncio
async def test_recall_reports_pending():
    search_response = {
        "result": {
            "memories": [],
            "pending_messages": [
                {"id": "p1", "content": "msg1"},
                {"id": "p2", "content": "msg2"},
            ],
        }
    }
    svc, _ = _make_svc(search_rv=search_response)
    svc._catalog.ensure_space("coding:app")

    result = await svc.recall("anything", "coding:app")
    assert result["pending_count"] == 2
    assert "2 message" in result["pending_hint"]


@pytest.mark.asyncio
async def test_recall_no_pending_key_when_empty():
    svc, _ = _make_svc()
    svc._catalog.ensure_space("coding:app")
    result = await svc.recall("anything", "coding:app")
    assert "pending_count" not in result


# -- briefing --


@pytest.mark.asyncio
async def test_briefing_assembles_three_types():
    call_count = 0

    async def mock_fetch(group_id, *, memory_type="episodic_memory", limit=40, **kw):
        nonlocal call_count
        call_count += 1
        if memory_type == "profile":
            return {
                "result": {
                    "memories": [
                        {
                            "profiles": [
                                {
                                    "profile_data": {
                                        "summary": "Developer who prefers TypeScript",
                                        "timestamp": "2026-02-10T10:00:00Z",
                                    }
                                }
                            ]
                        }
                    ]
                }
            }
        if memory_type == "episodic_memory":
            return {
                "result": {
                    "memories": [
                        {
                            "summary": "Discussed React architecture decisions",
                            "timestamp": "2026-02-10T11:00:00Z",
                        }
                    ]
                }
            }
        if memory_type == "event_log":
            return {
                "result": {
                    "memories": [
                        {
                            "atomic_fact": "Project uses Zustand for state management",
                            "timestamp": "2026-02-10T11:05:00Z",
                        }
                    ]
                }
            }
        return {"result": {"memories": []}}

    svc, client = _make_svc()
    client.fetch_memories = AsyncMock(side_effect=mock_fetch)
    svc._catalog.ensure_space("coding:app")

    result = await svc.briefing("coding:app")
    assert result["ok"] is True
    assert call_count == 3  # profile + episodic + event_log
    assert (
        "profile" in result["summary"].lower() or "episode" in result["summary"].lower()
    )
    assert len(result["highlights"]) == 3

    types_found = {h["type"] for h in result["highlights"]}
    assert types_found == {"profile", "episodic_memory", "event_log"}


@pytest.mark.asyncio
async def test_briefing_empty_space():
    svc, _ = _make_svc()
    svc._catalog.ensure_space("empty:space")
    result = await svc.briefing("empty:space")
    assert result["ok"] is True
    assert "no memories" in result["summary"].lower()
    assert result["highlights"] == []


@pytest.mark.asyncio
async def test_briefing_all_fetches_fail_returns_error():
    """When all 3 parallel fetches fail, briefing must raise (→ ok:false via server)."""
    svc, client = _make_svc()
    client.fetch_memories = AsyncMock(
        side_effect=EverMemosError("timeout", code="UPSTREAM_UNAVAILABLE")
    )
    svc._catalog.ensure_space("coding:app")

    with pytest.raises(EverMemosError) as exc_info:
        await svc.briefing("coding:app")
    assert exc_info.value.code == "UPSTREAM_UNAVAILABLE"


@pytest.mark.asyncio
async def test_briefing_partial_failure_returns_ok_with_warning():
    """When some fetches fail but others succeed, return ok:true with partial details."""
    call_count = 0

    async def mock_fetch(group_id, *, memory_type="episodic_memory", limit=40, **kw):
        nonlocal call_count
        call_count += 1
        if memory_type == "profile":
            raise EverMemosError("timeout", code="UPSTREAM_UNAVAILABLE")
        if memory_type == "episodic_memory":
            return {
                "result": {
                    "memories": [
                        {
                            "summary": "Discussed project architecture",
                            "timestamp": "2026-02-10T11:00:00Z",
                        }
                    ]
                }
            }
        return {"result": {"memories": []}}

    svc, client = _make_svc()
    client.fetch_memories = AsyncMock(side_effect=mock_fetch)
    svc._catalog.ensure_space("coding:app")

    result = await svc.briefing("coding:app")
    assert result["ok"] is True
    assert result["partial_hint"]
    assert len(result["partial_errors"]) == 1
    assert result["partial_errors"][0]["memory_type"] == "profile"
    assert len(result["highlights"]) >= 1


# -- forget --


@pytest.mark.asyncio
async def test_forget_deletes_by_id():
    svc, client = _make_svc()
    svc._catalog.ensure_space("coding:app")

    result = await svc.forget(["mem-001", "mem-002"], "coding:app")
    assert result["ok"] is True
    assert result["deleted_count"] == 2
    assert client.delete_memories.call_count == 2


@pytest.mark.asyncio
async def test_forget_partial_failure():
    call_count = 0

    async def mock_delete(*, event_id=None, group_id=None, **kw):
        nonlocal call_count
        call_count += 1
        if call_count == 2:
            raise EverMemosError("not found", code="NOT_FOUND", status_code=404)
        return {"result": {"count": 1}}

    svc, client = _make_svc()
    client.delete_memories = AsyncMock(side_effect=mock_delete)
    svc._catalog.ensure_space("coding:app")

    result = await svc.forget(["ok-1", "bad-2", "ok-3"], "coding:app")
    assert result["ok"] is False
    assert result["deleted_count"] == 2
    assert len(result["errors"]) == 1
    assert "bad-2" in result["errors"][0]
