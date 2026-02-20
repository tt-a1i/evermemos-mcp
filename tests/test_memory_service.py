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
    status_rv=None,
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
    client.get_request_status = AsyncMock(
        return_value=status_rv
        or {
            "success": True,
            "found": True,
            "data": {"request_id": "req-123", "status": "queued"},
        }
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
    assert "approximate" in result["memory_count_hint"].lower()


@pytest.mark.asyncio
async def test_list_spaces_invalid_limit():
    svc, _ = _make_svc()
    with pytest.raises(EverMemosError) as exc_info:
        await svc.list_spaces(limit=0)
    assert exc_info.value.code == "INVALID_INPUT"


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
    assert isinstance(result["message_id"], str)
    assert result["message_id"].startswith("msg_")
    assert result["message_id"] != result["request_id"]
    assert result["created_at"]
    assert (
        "queued" in result["processing_hint"].lower()
        or "minutes" in result["processing_hint"].lower()
    )
    assert "approximate" in result["memory_count_hint"].lower()

    # Verify Cloud call
    client.add_message.assert_called_once()
    call_kwargs = client.add_message.call_args
    assert call_kwargs.kwargs.get("flush") is False
    assert call_kwargs.kwargs.get("message_id") == result["message_id"]


@pytest.mark.asyncio
async def test_remember_with_description_registers_space():
    svc, _ = _make_svc()
    await svc.remember("study:ml", "Neural nets", description="ML course")
    result = await svc.list_spaces()
    assert result["spaces"][0]["description"] == "ML course"


@pytest.mark.asyncio
async def test_remember_prefers_upstream_message_id_when_present():
    svc, _ = _make_svc(
        add_msg_rv={
            "status": "queued",
            "request_id": "req-123",
            "message_id": "msg-upstream-001",
        }
    )

    result = await svc.remember("coding:app", "payload")
    assert result["message_id"] == "msg-upstream-001"


@pytest.mark.asyncio
async def test_remember_updates_conversation_meta_with_dynamic_user_identity():
    svc, client = _make_svc()

    await svc.remember(
        "coding:app",
        "payload",
        sender="assistant",
        user_id="alice",
        role="assistant",
    )

    client.set_conversation_metadata.assert_called_once()
    _, kwargs = client.set_conversation_metadata.call_args
    user_details = kwargs["user_details"]
    assert user_details["alice"]["role"] == "assistant"


@pytest.mark.asyncio
async def test_remember_include_status_fetches_request_status():
    svc, client = _make_svc()
    result = await svc.remember("study:ml", "Neural nets", include_status=True)

    assert result["ok"] is True
    assert result["request_id"] == "req-123"
    assert result["request_status"]["success"] is True
    client.get_request_status.assert_called_once_with("req-123")


@pytest.mark.asyncio
async def test_remember_without_description_ensures_space():
    svc, _ = _make_svc()
    await svc.remember("chat:daily", "Hello world")
    result = await svc.list_spaces()
    assert result["spaces"][0]["space_id"] == "chat:daily"
    assert result["spaces"][0]["description"] == ""


@pytest.mark.asyncio
async def test_remember_invalid_sender_raises():
    svc, _ = _make_svc()
    result = await svc.remember("coding:app", "x", sender="system")
    assert result["ok"] is True


@pytest.mark.asyncio
async def test_remember_role_validation_raises_on_invalid_role():
    svc, _ = _make_svc()
    with pytest.raises(EverMemosError) as exc_info:
        await svc.remember("coding:app", "x", role="system")
    assert exc_info.value.code == "INVALID_INPUT"


@pytest.mark.asyncio
async def test_memory_count_updates_on_remember_and_forget():
    svc, _ = _make_svc()
    await svc.remember("coding:app", "keep this")
    listed = await svc.list_spaces()
    assert listed["spaces"][0]["memory_count"] == 1

    await svc.forget(["mem-1"], "coding:app")
    listed = await svc.list_spaces()
    assert listed["spaces"][0]["memory_count"] == 0


@pytest.mark.asyncio
async def test_forget_adjusts_catalog_count_by_deleted_ids_not_upstream_count():
    svc, _ = _make_svc(delete_rv={"result": {"count": 3}})

    await svc.remember("coding:app", "entry-1")
    await svc.remember("coding:app", "entry-2")
    before = await svc.list_spaces()
    assert before["spaces"][0]["memory_count"] == 2

    result = await svc.forget(["mem-1"], "coding:app")
    assert result["deleted_count"] == 3

    after = await svc.list_spaces()
    assert after["spaces"][0]["memory_count"] == 1


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
    assert "FastAPI" in r0["content"]
    assert r0["score"] == 4.5

    r1 = result["results"][1]
    assert r1["memory_id"] == "mem-002"
    assert "FastAPI" in r1["snippet"]
    assert "FastAPI" in r1["content"]


@pytest.mark.asyncio
async def test_recall_includes_source_message_id_when_available():
    search_response = {
        "result": {
            "memories": [
                {
                    "id": "mem-001",
                    "memory_type": "episodic_memory",
                    "summary": "User discussed FastAPI with SQLAlchemy",
                    "timestamp": "2026-02-10T10:00:00Z",
                    "parent_type": "message",
                    "parent_id": "msg-001",
                }
            ],
            "pending_messages": [],
        }
    }
    svc, _ = _make_svc(search_rv=search_response)
    svc._catalog.ensure_space("coding:app")

    result = await svc.recall("FastAPI", "coding:app")
    assert result["ok"] is True
    assert result["results"][0]["source_message_id"] == "msg-001"


@pytest.mark.asyncio
async def test_recall_defaults_top_k_to_10():
    svc, client = _make_svc()
    svc._catalog.ensure_space("coding:app")

    await svc.recall("query", "coding:app")

    _, kwargs = client.search_memories.call_args
    assert kwargs["top_k"] == 10


@pytest.mark.asyncio
async def test_recall_maps_grouped_search_results():
    search_response = {
        "result": {
            "memories": [
                {
                    "episodic_memory": [
                        {
                            "id": "ep-001",
                            "summary": "Discussed migration plan",
                            "timestamp": "2026-02-10T10:00:00Z",
                        }
                    ],
                    "profile": [
                        {
                            "id": "pf-001",
                            "description": "Prefers short updates",
                            "created_at": "2026-02-10T10:02:00Z",
                        }
                    ],
                    "score": 0.88,
                }
            ],
            "pending_messages": [],
        }
    }
    svc, _ = _make_svc(search_rv=search_response)
    svc._catalog.ensure_space("coding:app")

    result = await svc.recall("plan", "coding:app", retrieve_method="keyword")
    assert result["ok"] is True
    assert len(result["results"]) == 2

    first = result["results"][0]
    assert first["memory_id"] == "ep-001"
    assert first["memory_type"] == "episodic_memory"
    assert "migration" in first["snippet"]

    second = result["results"][1]
    assert second["memory_id"] == "pf-001"
    assert second["memory_type"] == "profile"
    assert "Prefers" in second["snippet"]
    assert second["timestamp"] == "2026-02-10T10:02:00Z"
    assert second["score"] == 0.88


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
async def test_recall_includes_profile_results():
    search_response = {
        "result": {
            "memories": [],
            "profiles": [
                {
                    "item_type": "explicit_info",
                    "description": "Prefers concise technical answers",
                    "score": 0.92,
                }
            ],
            "pending_messages": [],
        }
    }
    svc, _ = _make_svc(search_rv=search_response)
    svc._catalog.ensure_space("coding:app")

    result = await svc.recall("style", "coding:app")
    assert result["ok"] is True
    assert len(result["results"]) == 1
    assert result["results"][0]["memory_type"] == "profile"
    assert "concise" in result["results"][0]["snippet"]


@pytest.mark.asyncio
async def test_recall_profile_results_include_memory_id_and_source_refs():
    search_response = {
        "result": {
            "memories": [],
            "profiles": [
                {
                    "id": "pf-001",
                    "description": "Prefers concise technical answers",
                    "score": 0.92,
                    "group_id": "space::coding:infra",
                    "source_message_id": "msg-001",
                    "updated_at": "2026-02-10T10:02:00Z",
                }
            ],
            "pending_messages": [],
        }
    }
    svc, _ = _make_svc(search_rv=search_response)
    svc._catalog.ensure_space("coding:app")
    svc._catalog.ensure_space("coding:infra")

    result = await svc.recall("style", space_ids=["coding:app", "coding:infra"])
    assert result["ok"] is True
    assert result["space_ids"] == ["coding:app", "coding:infra"]
    assert "space_id" not in result

    row = result["results"][0]
    assert row["memory_type"] == "profile"
    assert row["memory_id"] == "pf-001"
    assert row["source_message_id"] == "msg-001"
    assert row["space_id"] == "coding:infra"
    assert row["timestamp"] == "2026-02-10T10:02:00Z"


@pytest.mark.asyncio
async def test_recall_no_pending_key_when_empty():
    svc, _ = _make_svc()
    svc._catalog.ensure_space("coding:app")
    result = await svc.recall("anything", "coding:app")
    assert "pending_count" not in result


@pytest.mark.asyncio
async def test_recall_invalid_retrieve_method_raises():
    svc, _ = _make_svc()
    with pytest.raises(EverMemosError) as exc_info:
        await svc.recall("x", "coding:app", retrieve_method="invalid")
    assert exc_info.value.code == "INVALID_INPUT"


@pytest.mark.asyncio
async def test_recall_keyword_does_not_force_memory_types():
    svc, client = _make_svc()
    svc._catalog.ensure_space("coding:app")

    await svc.recall("x", "coding:app", retrieve_method="keyword")

    _, kwargs = client.search_memories.call_args
    assert kwargs["memory_types"] is None


@pytest.mark.asyncio
async def test_recall_auto_runs_hybrid_and_keyword_and_sets_actual_method():
    svc, client = _make_svc(
        search_rv={"result": {"memories": [], "pending_messages": []}}
    )
    svc._catalog.ensure_space("coding:app")

    result = await svc.recall("q", "coding:app", retrieve_method="auto")

    assert result["ok"] is True
    assert result["retrieve_method_actual"] == "auto(hybrid+keyword)"
    assert client.search_memories.call_count == 2
    methods = [
        call.kwargs["retrieve_method"] for call in client.search_memories.call_args_list
    ]
    assert set(methods) == {"hybrid", "keyword"}


@pytest.mark.asyncio
async def test_recall_auto_merges_and_deduplicates_results_by_memory_id():
    svc, client = _make_svc()
    svc._catalog.ensure_space("coding:app")
    client.search_memories = AsyncMock(
        side_effect=[
            {
                "result": {
                    "memories": [
                        {
                            "id": "ep-001",
                            "memory_type": "episodic_memory",
                            "summary": "Discussed migration plan",
                            "timestamp": "2026-02-10T10:00:00Z",
                            "score": 0.9,
                        }
                    ],
                    "pending_messages": [],
                }
            },
            {
                "result": {
                    "memories": [
                        {
                            "id": "ep-001",
                            "memory_type": "episodic_memory",
                            "summary": "duplicate from keyword",
                            "timestamp": "2026-02-10T10:00:00Z",
                            "score": 0.8,
                        },
                        {
                            "id": "ev-001",
                            "memory_type": "event_log",
                            "atomic_fact": "Use branch strategy A",
                            "timestamp": "2026-02-10T10:01:00Z",
                            "score": 0.7,
                        },
                    ],
                    "pending_messages": [],
                }
            },
        ]
    )

    result = await svc.recall("plan", "coding:app", retrieve_method="auto")

    assert result["ok"] is True
    ids = [item["memory_id"] for item in result["results"]]
    assert ids.count("ep-001") == 1
    assert "ev-001" in ids


@pytest.mark.asyncio
async def test_recall_auto_partial_when_one_branch_fails():
    svc, client = _make_svc()
    svc._catalog.ensure_space("coding:app")
    client.search_memories = AsyncMock(
        side_effect=[
            EverMemosError("hybrid timeout", code="UPSTREAM_UNAVAILABLE"),
            {"result": {"memories": [], "pending_messages": []}},
        ]
    )

    result = await svc.recall("plan", "coding:app", retrieve_method="auto")

    assert result["ok"] is True
    assert result["partial_hint"]
    assert result["partial_errors"][0]["branch"] == "hybrid"


@pytest.mark.asyncio
async def test_recall_auto_raises_when_all_branches_fail():
    svc, client = _make_svc()
    svc._catalog.ensure_space("coding:app")
    client.search_memories = AsyncMock(
        side_effect=[
            EverMemosError("hybrid timeout", code="UPSTREAM_UNAVAILABLE"),
            EverMemosError("keyword timeout", code="UPSTREAM_UNAVAILABLE"),
        ]
    )

    with pytest.raises(EverMemosError) as exc_info:
        await svc.recall("plan", "coding:app", retrieve_method="auto")

    assert exc_info.value.code == "UPSTREAM_UNAVAILABLE"


@pytest.mark.asyncio
async def test_recall_auto_rejects_unsupported_memory_types():
    svc, client = _make_svc()
    svc._catalog.ensure_space("coding:app")

    with pytest.raises(EverMemosError) as exc_info:
        await svc.recall(
            "file name",
            "coding:app",
            retrieve_method="auto",
            memory_types=["event_log"],
        )

    assert exc_info.value.code == "INVALID_INPUT"
    assert client.search_memories.call_count == 0


@pytest.mark.asyncio
async def test_recall_vector_does_not_force_memory_types():
    svc, client = _make_svc()
    svc._catalog.ensure_space("coding:app")

    await svc.recall("x", "coding:app", retrieve_method="vector")

    _, kwargs = client.search_memories.call_args
    assert kwargs["memory_types"] is None


@pytest.mark.asyncio
async def test_recall_hybrid_defaults_to_profile_and_episodic_memory_types():
    svc, client = _make_svc()
    svc._catalog.ensure_space("coding:app")

    await svc.recall("x", "coding:app", retrieve_method="hybrid")

    _, kwargs = client.search_memories.call_args
    assert kwargs["memory_types"] == ["profile", "episodic_memory"]


@pytest.mark.asyncio
async def test_recall_hybrid_falls_back_when_profile_search_is_unsupported():
    svc, client = _make_svc()
    svc._catalog.ensure_space("coding:app")
    client.search_memories = AsyncMock(
        side_effect=[
            EverMemosError(
                "profile memory type is not supported in the search interface",
                code="INVALID_PARAMETER",
                status_code=400,
            ),
            {"result": {"memories": [], "pending_messages": []}},
        ]
    )

    result = await svc.recall("x", "coding:app", retrieve_method="hybrid")

    assert result["ok"] is True
    assert result["warnings"][0]["code"] == "PROFILE_UNSUPPORTED_FALLBACK"
    assert client.search_memories.call_count == 2
    first_call = client.search_memories.call_args_list[0]
    second_call = client.search_memories.call_args_list[1]
    assert first_call.kwargs["memory_types"] == ["profile", "episodic_memory"]
    assert second_call.kwargs["memory_types"] == ["episodic_memory"]


@pytest.mark.asyncio
async def test_recall_hybrid_does_not_fallback_on_unrelated_profile_errors():
    svc, client = _make_svc()
    svc._catalog.ensure_space("coding:app")
    client.search_memories = AsyncMock(
        side_effect=EverMemosError(
            "invalid profile payload format",
            code="INVALID_PARAMETER",
            status_code=400,
        )
    )

    with pytest.raises(EverMemosError) as exc_info:
        await svc.recall("x", "coding:app", retrieve_method="hybrid")

    assert exc_info.value.code == "INVALID_PARAMETER"
    assert client.search_memories.call_count == 1


@pytest.mark.asyncio
async def test_recall_explicit_memory_types_override_for_vector_search():
    svc, client = _make_svc()
    svc._catalog.ensure_space("coding:app")

    await svc.recall(
        "x",
        "coding:app",
        retrieve_method="vector",
        memory_types=["profile", "episodic_memory", "profile"],
    )

    _, kwargs = client.search_memories.call_args
    assert kwargs["memory_types"] == ["profile", "episodic_memory"]


@pytest.mark.asyncio
async def test_recall_invalid_memory_types_raises():
    svc, _ = _make_svc()
    svc._catalog.ensure_space("coding:app")

    with pytest.raises(EverMemosError) as exc_info:
        await svc.recall("x", "coding:app", memory_types=["unknown"])
    assert exc_info.value.code == "INVALID_INPUT"


@pytest.mark.asyncio
async def test_recall_hybrid_accepts_profile_or_episodic_subset_only():
    svc, client = _make_svc()
    svc._catalog.ensure_space("coding:app")

    await svc.recall(
        "x",
        "coding:app",
        retrieve_method="hybrid",
        memory_types=["profile"],
    )

    _, kwargs = client.search_memories.call_args
    assert kwargs["memory_types"] == ["profile"]


@pytest.mark.asyncio
async def test_recall_hybrid_rejects_event_log_memory_types():
    svc, _ = _make_svc()
    svc._catalog.ensure_space("coding:app")

    with pytest.raises(EverMemosError) as exc_info:
        await svc.recall(
            "x",
            "coding:app",
            retrieve_method="hybrid",
            memory_types=["event_log"],
        )
    assert exc_info.value.code == "INVALID_INPUT"


@pytest.mark.asyncio
async def test_recall_rrf_defaults_to_profile_and_episodic_memory_types():
    svc, client = _make_svc()
    svc._catalog.ensure_space("coding:app")

    await svc.recall("x", "coding:app", retrieve_method="rrf")

    _, kwargs = client.search_memories.call_args
    assert kwargs["memory_types"] == ["profile", "episodic_memory"]


@pytest.mark.asyncio
async def test_recall_agentic_rejects_non_profile_or_episodic_memory_types():
    svc, _ = _make_svc()
    svc._catalog.ensure_space("coding:app")

    with pytest.raises(EverMemosError) as exc_info:
        await svc.recall(
            "x",
            "coding:app",
            retrieve_method="agentic",
            memory_types=["foresight"],
        )
    assert exc_info.value.code == "INVALID_INPUT"


# -- fetch_history --


@pytest.mark.asyncio
async def test_fetch_history_maps_rows_and_pagination_fields():
    fetch_response = {
        "result": {
            "memories": [
                {
                    "id": "evt-001",
                    "memory_type": "event_log",
                    "atomic_fact": "Project uses FastAPI",
                    "timestamp": "2026-02-10T10:00:00Z",
                    "parent_type": "message",
                    "parent_id": "msg-001",
                }
            ],
            "count": 1,
            "total_count": 3,
        }
    }
    svc, client = _make_svc(fetch_rv=fetch_response)
    svc._catalog.ensure_space("coding:app")

    result = await svc.fetch_history(
        "coding:app",
        memory_type="event_log",
        limit=1,
        offset=1,
        user_id="alice",
    )

    assert result["ok"] is True
    assert result["memory_type"] == "event_log"
    assert result["count"] == 1
    assert result["total_count"] == 3
    assert result["has_more"] is True
    assert result["next_offset"] == 2
    assert result["items"][0]["source_message_id"] == "msg-001"
    assert "FastAPI" in result["items"][0]["snippet"]
    assert "FastAPI" in result["items"][0]["content"]

    client.fetch_memories.assert_called_once()
    _, kwargs = client.fetch_memories.call_args
    assert kwargs["memory_type"] == "event_log"
    assert kwargs["limit"] == 1
    assert kwargs["offset"] == 1
    assert kwargs["user_id"] == "alice"


@pytest.mark.asyncio
async def test_fetch_history_non_aligned_offset_returns_exact_slice():
    async def mock_fetch(
        group_id,
        *,
        memory_type="episodic_memory",
        user_id=None,
        limit=40,
        offset=0,
        **kw,
    ):
        assert group_id == "space::coding:app"
        assert memory_type == "event_log"
        assert user_id == "alice"
        assert limit == 50

        total_count = 130
        start = offset
        end = min(start + limit, total_count)
        memories = [
            {
                "id": f"evt-{index:03d}",
                "memory_type": "event_log",
                "atomic_fact": f"fact-{index}",
                "timestamp": "2026-02-10T10:00:00Z",
            }
            for index in range(start, end)
        ]
        return {
            "result": {
                "memories": memories,
                "count": len(memories),
                "total_count": total_count,
            }
        }

    svc, client = _make_svc()
    client.fetch_memories = AsyncMock(side_effect=mock_fetch)
    svc._catalog.ensure_space("coding:app")

    result = await svc.fetch_history(
        "coding:app",
        memory_type="event_log",
        limit=50,
        offset=55,
        user_id="alice",
    )

    assert result["ok"] is True
    assert result["offset"] == 55
    assert result["count"] == 50
    assert result["next_offset"] == 105
    assert result["has_more"] is True
    assert len(result["items"]) == 50
    assert result["items"][0]["memory_id"] == "evt-055"
    assert result["items"][-1]["memory_id"] == "evt-104"

    assert client.fetch_memories.call_count == 2
    first_call = client.fetch_memories.call_args_list[0].kwargs
    second_call = client.fetch_memories.call_args_list[1].kwargs
    assert first_call["offset"] == 50
    assert second_call["offset"] == 100


@pytest.mark.asyncio
async def test_fetch_history_rejects_invalid_memory_type():
    svc, _ = _make_svc()
    svc._catalog.ensure_space("coding:app")

    with pytest.raises(EverMemosError) as exc_info:
        await svc.fetch_history("coding:app", memory_type="unknown")

    assert exc_info.value.code == "INVALID_INPUT"


@pytest.mark.asyncio
async def test_fetch_history_rejects_negative_offset():
    svc, _ = _make_svc()
    svc._catalog.ensure_space("coding:app")

    with pytest.raises(EverMemosError) as exc_info:
        await svc.fetch_history("coding:app", offset=-1)

    assert exc_info.value.code == "INVALID_INPUT"


# -- briefing --


@pytest.mark.asyncio
async def test_briefing_assembles_four_types():
    call_count = 0

    async def mock_fetch(group_id, *, memory_type="episodic_memory", limit=40, **kw):
        nonlocal call_count
        call_count += 1
        if memory_type == "profile":
            return {
                "result": {
                    "memories": [
                        {
                            "profile_data": {
                                "summary": "Developer who prefers TypeScript"
                            },
                            "updated_at": "2026-02-10T10:00:00Z",
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
                            "parent_type": "message",
                            "parent_id": "msg-ep-001",
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
        if memory_type == "foresight":
            return {
                "result": {
                    "memories": [
                        {
                            "id": "fo-1",
                            "memory_type": "foresight",
                            "foresight": "Need to prepare migration plan next sprint",
                            "start_time": "2026-03-01T09:00:00Z",
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
    assert call_count == 4  # profile + episodic + event_log + foresight
    assert (
        "profile" in result["summary"].lower() or "episode" in result["summary"].lower()
    )
    assert any(
        item.get("source_message_id") == "msg-ep-001"
        for item in result["highlights"]
        if item.get("type") == "episodic_memory"
    )
    assert len(result["highlights"]) == 4

    types_found = {h["type"] for h in result["highlights"]}
    assert types_found == {"profile", "episodic_memory", "event_log", "foresight"}


@pytest.mark.asyncio
async def test_briefing_profile_highlight_uses_common_text_extractor():
    async def mock_fetch(group_id, *, memory_type="episodic_memory", **kw):
        if memory_type == "profile":
            return {
                "result": {
                    "memories": [
                        {
                            "summary": "Prefers concise status updates",
                            "updated_at": "2026-02-10T10:00:00Z",
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
    assert result["highlights"][0]["type"] == "profile"
    assert "concise" in result["highlights"][0]["content"]


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
    """When all 4 parallel fetches fail, briefing must raise (→ ok:false via server)."""
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
    assert result["delete_scope_user_id"] == "mcp-user"
    assert client.delete_memories.call_count == 2

    for call in client.delete_memories.call_args_list:
        _, kwargs = call
        assert kwargs["group_id"] == "space::coding:app"
        assert kwargs["user_id"] == "mcp-user"


@pytest.mark.asyncio
async def test_forget_partial_failure():
    async def mock_delete(*, memory_id=None, group_id=None, **kw):
        if memory_id == "bad-2":
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


@pytest.mark.asyncio
async def test_forget_unexpected_exception_is_isolated_as_partial_error():
    async def mock_delete(*, memory_id=None, group_id=None, **kw):
        if memory_id == "boom":
            raise RuntimeError("socket closed")
        return {"result": {"count": 1}}

    svc, client = _make_svc()
    client.delete_memories = AsyncMock(side_effect=mock_delete)
    svc._catalog.ensure_space("coding:app")

    result = await svc.forget(["ok-1", "boom", "ok-2"], "coding:app")
    assert result["ok"] is False
    assert result["deleted_count"] == 2
    assert len(result["errors"]) == 1
    assert "boom" in result["errors"][0]
    assert "unexpected delete error" in result["errors"][0]


@pytest.mark.asyncio
async def test_forget_reason_is_logged_in_output():
    svc, _ = _make_svc()
    svc._catalog.ensure_space("coding:app")

    result = await svc.forget(["ok-1"], "coding:app", reason="cleanup duplicate")
    assert result["ok"] is True
    assert result["reason_logged"] is True


@pytest.mark.asyncio
async def test_forget_rejects_empty_memory_ids():
    svc, _ = _make_svc()
    with pytest.raises(EverMemosError) as exc_info:
        await svc.forget([], "coding:app")
    assert exc_info.value.code == "INVALID_INPUT"


@pytest.mark.asyncio
async def test_forget_deduplicates_ids_before_delete_calls():
    svc, client = _make_svc()
    svc._catalog.ensure_space("coding:app")
    result = await svc.forget(["dup-1", "dup-1", "dup-2"], "coding:app")

    assert result["ok"] is True
    assert result["deleted_count"] == 2
    assert client.delete_memories.call_count == 2


@pytest.mark.asyncio
async def test_forget_uses_explicit_user_id_when_provided():
    svc, client = _make_svc()
    svc._catalog.ensure_space("coding:app")

    await svc.forget(["m1"], "coding:app", user_id="alice")

    _, kwargs = client.delete_memories.call_args
    assert kwargs["memory_id"] == "m1"
    assert kwargs["group_id"] == "space::coding:app"
    assert kwargs["user_id"] == "alice"


@pytest.mark.asyncio
async def test_forget_returns_error_when_no_memory_matches_scope():
    svc, client = _make_svc(delete_rv={"result": {"count": 0}})
    svc._catalog.ensure_space("coding:app")

    result = await svc.forget(["m1"], "coding:app", user_id="alice")

    assert result["ok"] is False
    assert result["deleted_count"] == 0
    assert result["delete_scope_user_id"] == "alice"
    assert len(result["errors"]) == 1
    assert "no memory matched delete scope" in result["errors"][0]


@pytest.mark.asyncio
async def test_forget_rejects_blank_user_id():
    svc, _ = _make_svc()
    svc._catalog.ensure_space("coding:app")

    with pytest.raises(EverMemosError) as exc_info:
        await svc.forget(["m1"], "coding:app", user_id="   ")

    assert exc_info.value.code == "INVALID_INPUT"


@pytest.mark.asyncio
async def test_recall_with_time_range_passes_to_client():
    svc, client = _make_svc()
    svc._catalog.ensure_space("coding:app")

    await svc.recall(
        "query",
        "coding:app",
        start_time="2024-01-01T00:00:00+00:00",
        end_time="2024-12-31T23:59:59+00:00",
        current_time="2024-06-01T00:00:00+00:00",
        radius=0.6,
        include_metadata=True,
    )

    client.search_memories.assert_called_once()
    _, kwargs = client.search_memories.call_args
    assert kwargs["start_time"] == "2024-01-01T00:00:00+00:00"
    assert kwargs["end_time"] == "2024-12-31T23:59:59+00:00"
    assert kwargs["current_time"] == "2024-06-01T00:00:00+00:00"
    assert kwargs["radius"] == 0.6
    assert kwargs["include_metadata"] is True


@pytest.mark.asyncio
async def test_recall_with_user_id_passes_to_client():
    svc, client = _make_svc()
    svc._catalog.ensure_space("coding:app")

    result = await svc.recall("query", "coding:app", user_id="custom-user-123")
    assert result["space_id"] == "coding:app"
    assert result["space_ids"] == ["coding:app"]

    client.search_memories.assert_called_once()
    _, kwargs = client.search_memories.call_args
    assert kwargs["user_id"] == "custom-user-123"


@pytest.mark.asyncio
async def test_recall_with_space_ids_passes_group_ids_to_client():
    svc, client = _make_svc()
    svc._catalog.ensure_space("coding:app")
    svc._catalog.ensure_space("coding:infra")

    result = await svc.recall(
        "query",
        space_ids=["coding:app", "coding:infra", "coding:app"],
    )
    assert result["space_ids"] == ["coding:app", "coding:infra"]
    assert "space_id" not in result

    client.search_memories.assert_called_once()
    call_args = client.search_memories.call_args.args
    assert call_args[1] == ["space::coding:app", "space::coding:infra"]


@pytest.mark.asyncio
async def test_recall_rejects_when_no_space_scope_is_provided():
    svc, _ = _make_svc()

    with pytest.raises(EverMemosError) as exc_info:
        await svc.recall("query")

    assert exc_info.value.code == "INVALID_INPUT"


@pytest.mark.asyncio
async def test_recall_rejects_more_than_10_unique_space_ids():
    svc, _ = _make_svc()
    too_many = [f"coding:s{index}" for index in range(11)]

    with pytest.raises(EverMemosError) as exc_info:
        await svc.recall("query", space_ids=too_many)

    assert exc_info.value.code == "INVALID_INPUT"


@pytest.mark.asyncio
async def test_recall_maps_space_id_from_group_id_when_available():
    search_response = {
        "result": {
            "memories": [
                {
                    "id": "mem-001",
                    "memory_type": "episodic_memory",
                    "summary": "Discussed FastAPI architecture",
                    "timestamp": "2026-02-10T10:00:00Z",
                    "group_id": "space::coding:infra",
                }
            ],
            "pending_messages": [],
        }
    }
    svc, _ = _make_svc(search_rv=search_response)

    result = await svc.recall("FastAPI", space_ids=["coding:app", "coding:infra"])

    assert result["ok"] is True
    assert result["space_ids"] == ["coding:app", "coding:infra"]
    assert result["results"][0]["space_id"] == "coding:infra"


@pytest.mark.asyncio
async def test_recall_rejects_blank_user_id():
    svc, _ = _make_svc()
    svc._catalog.ensure_space("coding:app")

    with pytest.raises(EverMemosError) as exc_info:
        await svc.recall("query", "coding:app", user_id="   ")

    assert exc_info.value.code == "INVALID_INPUT"


@pytest.mark.asyncio
async def test_briefing_with_time_range_passes_to_client():
    svc, client = _make_svc()
    svc._catalog.ensure_space("coding:app")

    await svc.briefing(
        "coding:app",
        start_time="2024-01-01T00:00:00+00:00",
        end_time="2024-12-31T23:59:59+00:00",
    )

    # briefing calls fetch_memories 4 times.
    for call in client.fetch_memories.call_args_list:
        _, kwargs = call
        mtype = kwargs.get("memory_type")
        if mtype in ["episodic_memory", "event_log", "foresight"]:
            assert kwargs["start_time"] == "2024-01-01T00:00:00+00:00"
            assert kwargs["end_time"] == "2024-12-31T23:59:59+00:00"
        elif mtype == "profile":
            assert kwargs.get("start_time") is None
            assert kwargs.get("end_time") is None


@pytest.mark.asyncio
async def test_briefing_with_user_id_passes_to_client():
    svc, client = _make_svc()
    svc._catalog.ensure_space("coding:app")

    await svc.briefing("coding:app", user_id="briefing-user")

    # briefing calls fetch_memories 4 times.
    for call in client.fetch_memories.call_args_list:
        _, kwargs = call
        assert kwargs["user_id"] == "briefing-user"


@pytest.mark.asyncio
async def test_briefing_rejects_blank_user_id():
    svc, _ = _make_svc()
    svc._catalog.ensure_space("coding:app")

    with pytest.raises(EverMemosError) as exc_info:
        await svc.briefing("coding:app", user_id="   ")

    assert exc_info.value.code == "INVALID_INPUT"


@pytest.mark.asyncio
async def test_recall_accepts_naive_time_and_normalizes_to_utc():
    svc, client = _make_svc()
    svc._catalog.ensure_space("coding:app")

    await svc.recall(
        "query",
        "coding:app",
        start_time="2024-01-01T00:00:00",
    )

    _, kwargs = client.search_memories.call_args
    assert kwargs["start_time"] == "2024-01-01T00:00:00+00:00"


@pytest.mark.asyncio
async def test_recall_rejects_out_of_range_radius():
    svc, _ = _make_svc()
    svc._catalog.ensure_space("coding:app")

    with pytest.raises(EverMemosError) as exc_info:
        await svc.recall("query", "coding:app", radius=1.5)
    assert exc_info.value.code == "INVALID_INPUT"


@pytest.mark.asyncio
async def test_recall_rejects_top_k_above_limit():
    svc, _ = _make_svc()
    svc._catalog.ensure_space("coding:app")

    with pytest.raises(EverMemosError) as exc_info:
        await svc.recall("query", "coding:app", top_k=101)
    assert exc_info.value.code == "INVALID_INPUT"


@pytest.mark.asyncio
async def test_recall_accepts_top_k_minus_one_for_all_results():
    svc, client = _make_svc()
    svc._catalog.ensure_space("coding:app")

    await svc.recall("query", "coding:app", top_k=-1)

    _, kwargs = client.search_memories.call_args
    assert kwargs["top_k"] == -1


@pytest.mark.asyncio
async def test_recall_rejects_inverted_time_range():
    svc, _ = _make_svc()
    svc._catalog.ensure_space("coding:app")

    with pytest.raises(EverMemosError) as exc_info:
        await svc.recall(
            "query",
            "coding:app",
            start_time="2024-12-31T23:59:59+00:00",
            end_time="2024-01-01T00:00:00+00:00",
        )
    assert exc_info.value.code == "INVALID_INPUT"


@pytest.mark.asyncio
async def test_recall_allows_equal_time_window():
    svc, client = _make_svc()
    svc._catalog.ensure_space("coding:app")

    await svc.recall(
        "query",
        "coding:app",
        start_time="2024-01-01T00:00:00+00:00",
        end_time="2024-01-01T00:00:00+00:00",
    )

    _, kwargs = client.search_memories.call_args
    assert kwargs["start_time"] == "2024-01-01T00:00:00+00:00"
    assert kwargs["end_time"] == "2024-01-01T00:00:00+00:00"


@pytest.mark.asyncio
async def test_briefing_accepts_naive_time_and_normalizes_to_utc():
    svc, client = _make_svc()
    svc._catalog.ensure_space("coding:app")

    await svc.briefing("coding:app", end_time="2024-12-31T23:59:59")

    for call in client.fetch_memories.call_args_list:
        _, kwargs = call
        if kwargs.get("memory_type") in {"episodic_memory", "event_log", "foresight"}:
            assert kwargs.get("end_time") == "2024-12-31T23:59:59+00:00"


@pytest.mark.asyncio
async def test_briefing_rejects_inverted_time_range():
    svc, _ = _make_svc()
    svc._catalog.ensure_space("coding:app")

    with pytest.raises(EverMemosError) as exc_info:
        await svc.briefing(
            "coding:app",
            start_time="2024-12-31T23:59:59+00:00",
            end_time="2024-01-01T00:00:00+00:00",
        )
    assert exc_info.value.code == "INVALID_INPUT"


@pytest.mark.asyncio
async def test_recall_includes_partial_hint_when_upstream_partial():
    svc, _ = _make_svc(
        search_rv={
            "status": "partial",
            "message": "partial shard failure",
            "result": {"memories": [], "pending_messages": [], "partial_errors": []},
        }
    )
    svc._catalog.ensure_space("coding:app")

    result = await svc.recall("query", "coding:app")
    assert result["partial_hint"]
    assert result["partial_errors"][0]["message"] == "partial shard failure"
