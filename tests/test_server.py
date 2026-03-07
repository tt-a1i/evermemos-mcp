"""Tests for server.py: tool dispatch and error mapping."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest

from evermemos_mcp import config, server as server_mod
from evermemos_mcp.evermemos_client import EverMemosClient, EverMemosError
from evermemos_mcp.memory_service import MemoryService
from evermemos_mcp.space_catalog_service import SpaceCatalogService


@pytest.fixture
def svc():
    """Wire up a MemoryService with mocked client and install it on the server module."""
    client = AsyncMock(spec=EverMemosClient)
    client.user_id = "mcp-user"
    client.add_message = AsyncMock(
        return_value={"status": "queued", "request_id": "req-abc"}
    )
    client.search_memories = AsyncMock(
        return_value={"result": {"memories": [], "pending_messages": []}}
    )
    client.fetch_memories = AsyncMock(return_value={"result": {"memories": []}})
    client.delete_memories = AsyncMock(return_value={"result": {"count": 1}})
    client.get_request_status = AsyncMock(
        return_value={
            "success": True,
            "found": True,
            "data": {"request_id": "req-abc", "status": "queued"},
        }
    )
    catalog = SpaceCatalogService(client)
    ms = MemoryService(client, catalog)
    server_mod._svc = ms
    yield ms
    server_mod._svc = None


def _parse(text_contents) -> dict:
    """Extract JSON from tool response."""
    assert len(text_contents) == 1
    return json.loads(text_contents[0].text)


# -- tool registration --


@pytest.mark.asyncio
async def test_list_tools_returns_seven():
    tools = await server_mod.handle_list_tools()  # type: ignore[call-arg]
    names = {t.name for t in tools}
    assert names == {
        "list_spaces",
        "remember",
        "request_status",
        "recall",
        "briefing",
        "forget",
        "fetch_history",
    }


# -- dispatch --


@pytest.mark.asyncio
async def test_dispatch_remember(svc):
    result = await server_mod.handle_call_tool(
        "remember", {"content": "test content", "space_id": "coding:app"}
    )
    data = _parse(result)
    assert data["ok"] is True
    assert data["space_id"] == "coding:app"
    assert data["created_at"]
    assert data["lifecycle"]["state"] == "queued"
    assert data["status_check"]["tool"] == "request_status"


@pytest.mark.asyncio
async def test_dispatch_remember_with_status(svc):
    result = await server_mod.handle_call_tool(
        "remember",
        {
            "content": "test content",
            "space_id": "coding:app",
            "include_status": True,
        },
    )
    data = _parse(result)
    assert data["ok"] is True
    assert data["request_status"]["ok"] is True
    assert data["request_status"]["request_id"] == "req-abc"
    assert data["request_status"]["success"] is True
    assert data["request_status"]["lifecycle"]["state"] == "queued"
    assert data["status_check"]["checked_now"] is True


@pytest.mark.asyncio
async def test_dispatch_request_status(svc):
    result = await server_mod.handle_call_tool(
        "request_status",
        {"request_id": "req-abc"},
    )
    data = _parse(result)
    assert data["ok"] is True
    assert data["request_id"] == "req-abc"
    assert data["status"] == "queued"
    assert data["lifecycle"]["state"] == "queued"


@pytest.mark.asyncio
async def test_dispatch_recall(svc):
    svc._catalog.ensure_space("coding:app")
    result = await server_mod.handle_call_tool(
        "recall", {"query": "FastAPI", "space_id": "coding:app"}
    )
    data = _parse(result)
    assert data["ok"] is True
    assert "results" in data
    assert data["space_id"] == "coding:app"
    assert data["space_ids"] == ["coding:app"]

    svc._client.search_memories.assert_called_once()
    _, kwargs = svc._client.search_memories.call_args
    assert kwargs["top_k"] == 10


@pytest.mark.asyncio
async def test_dispatch_recall_with_extended_filters(svc):
    svc._catalog.ensure_space("coding:app")
    result = await server_mod.handle_call_tool(
        "recall",
        {
            "query": "FastAPI",
            "space_id": "coding:app",
            "start_time": "2024-01-01T00:00:00+00:00",
            "end_time": "2024-12-31T23:59:59+00:00",
            "current_time": "2024-06-01T00:00:00+00:00",
            "radius": 0.6,
            "include_metadata": True,
            "retrieve_method": "vector",
            "memory_types": ["profile", "episodic_memory"],
        },
    )
    data = _parse(result)
    assert data["ok"] is True

    svc._client.search_memories.assert_called_once()
    _, kwargs = svc._client.search_memories.call_args
    assert kwargs["memory_types"] == ["profile", "episodic_memory"]
    assert kwargs["retrieve_method"] == "vector"


@pytest.mark.asyncio
async def test_dispatch_recall_with_space_ids(svc):
    svc._catalog.ensure_space("coding:app")
    svc._catalog.ensure_space("coding:infra")
    result = await server_mod.handle_call_tool(
        "recall",
        {
            "query": "FastAPI",
            "space_ids": ["coding:app", "coding:infra", "coding:app"],
        },
    )
    data = _parse(result)
    assert data["ok"] is True
    assert data["space_ids"] == ["coding:app", "coding:infra"]
    assert "space_id" not in data

    svc._client.search_memories.assert_called_once()
    args = svc._client.search_memories.call_args.args
    assert args[1] == ["space::coding:app", "space::coding:infra"]


@pytest.mark.asyncio
async def test_dispatch_recall_invalid_memory_types_returns_invalid_input(svc):
    svc._catalog.ensure_space("coding:app")
    result = await server_mod.handle_call_tool(
        "recall",
        {
            "query": "FastAPI",
            "space_id": "coding:app",
            "memory_types": ["not-a-type"],
        },
    )
    data = _parse(result)
    assert data["ok"] is False
    assert data["error"] == "INVALID_INPUT"


@pytest.mark.asyncio
async def test_dispatch_recall_hybrid_rejects_event_log_memory_types(svc):
    svc._catalog.ensure_space("coding:app")
    result = await server_mod.handle_call_tool(
        "recall",
        {
            "query": "FastAPI",
            "space_id": "coding:app",
            "retrieve_method": "hybrid",
            "memory_types": ["event_log"],
        },
    )
    data = _parse(result)
    assert data["ok"] is False
    assert data["error"] == "INVALID_INPUT"


@pytest.mark.asyncio
async def test_dispatch_recall_requires_space_scope(svc):
    with patch.object(config, "EVERMEMOS_DEFAULT_SPACE", None):
        result = await server_mod.handle_call_tool(
            "recall",
            {
                "query": "FastAPI",
            },
        )
    data = _parse(result)
    assert data["ok"] is False
    assert data["error"] == "INVALID_INPUT"


@pytest.mark.asyncio
async def test_dispatch_recall_auto_detects_space(svc):
    with patch.object(config, "EVERMEMOS_DEFAULT_SPACE", "coding:my-repo"):
        svc._catalog.ensure_space("coding:my-repo")
        result = await server_mod.handle_call_tool("recall", {"query": "FastAPI"})
    data = _parse(result)
    assert data["ok"] is True
    assert data["space_id"] == "coding:my-repo"


@pytest.mark.asyncio
async def test_dispatch_briefing(svc):
    svc._catalog.ensure_space("coding:app")
    result = await server_mod.handle_call_tool("briefing", {"space_id": "coding:app"})
    data = _parse(result)
    assert data["ok"] is True
    assert "summary" in data


@pytest.mark.asyncio
async def test_dispatch_briefing_with_time_filters(svc):
    svc._catalog.ensure_space("coding:app")
    result = await server_mod.handle_call_tool(
        "briefing",
        {
            "space_id": "coding:app",
            "start_time": "2024-01-01T00:00:00+00:00",
            "end_time": "2024-12-31T23:59:59+00:00",
        },
    )
    data = _parse(result)
    assert data["ok"] is True

    for call in svc._client.fetch_memories.call_args_list:
        _, kwargs = call
        memory_type = kwargs.get("memory_type")
        if memory_type in {"episodic_memory", "event_log", "foresight"}:
            assert kwargs.get("start_time") == "2024-01-01T00:00:00+00:00"
            assert kwargs.get("end_time") == "2024-12-31T23:59:59+00:00"
        if memory_type == "profile":
            assert kwargs.get("start_time") is None
            assert kwargs.get("end_time") is None


@pytest.mark.asyncio
async def test_dispatch_forget(svc):
    svc._catalog.ensure_space("coding:app")
    result = await server_mod.handle_call_tool(
        "forget", {"memory_ids": ["m1"], "space_id": "coding:app"}
    )
    data = _parse(result)
    assert data["ok"] is True
    assert data["deleted_count"] == 1
    svc._client.delete_memories.assert_called_with(
        memory_id="m1",
        group_id="space::coding:app",
        user_id="mcp-user",
    )


@pytest.mark.asyncio
async def test_dispatch_forget_with_user_id_scope(svc):
    svc._catalog.ensure_space("coding:app")
    result = await server_mod.handle_call_tool(
        "forget",
        {
            "memory_ids": ["m1"],
            "space_id": "coding:app",
            "user_id": "alice",
        },
    )
    data = _parse(result)
    assert data["ok"] is True

    svc._client.delete_memories.assert_called_with(
        memory_id="m1",
        group_id="space::coding:app",
        user_id="alice",
    )


@pytest.mark.asyncio
async def test_dispatch_fetch_history(svc):
    svc._catalog.ensure_space("coding:app")
    svc._client.fetch_memories = AsyncMock(
        return_value={
            "result": {
                "memories": [
                    {
                        "id": "evt-001",
                        "memory_type": "event_log",
                        "atomic_fact": "Project uses FastAPI",
                        "timestamp": "2026-02-10T10:00:00Z",
                    }
                ],
                "count": 1,
                "total_count": 1,
            }
        }
    )

    result = await server_mod.handle_call_tool(
        "fetch_history",
        {
            "space_id": "coding:app",
            "memory_type": "event_log",
            "limit": 20,
            "offset": 0,
            "user_id": "alice",
        },
    )
    data = _parse(result)
    assert data["ok"] is True
    assert data["memory_type"] == "event_log"
    assert data["items"][0]["memory_id"] == "evt-001"

    svc._client.fetch_memories.assert_called_once()
    _, kwargs = svc._client.fetch_memories.call_args
    assert kwargs["memory_type"] == "event_log"
    assert kwargs["limit"] == 20
    assert kwargs["offset"] == 0
    assert kwargs["user_id"] == "alice"


@pytest.mark.asyncio
async def test_dispatch_list_spaces(svc):
    await svc.remember("coding:app", "x", description="My app")
    result = await server_mod.handle_call_tool("list_spaces", {})
    data = _parse(result)
    assert data["ok"] is True
    assert len(data["spaces"]) == 1


# -- error mapping --


@pytest.mark.asyncio
async def test_upstream_error_mapped(svc):
    svc._client.search_memories = AsyncMock(
        side_effect=EverMemosError("timeout", code="UPSTREAM_UNAVAILABLE")
    )
    svc._catalog.ensure_space("coding:app")
    result = await server_mod.handle_call_tool(
        "recall", {"query": "x", "space_id": "coding:app"}
    )
    data = _parse(result)
    assert data["ok"] is False
    assert data["error"] == "UPSTREAM_UNAVAILABLE"


@pytest.mark.asyncio
async def test_missing_required_field(svc):
    with patch.object(config, "EVERMEMOS_DEFAULT_SPACE", None):
        result = await server_mod.handle_call_tool("remember", {"content": "no space"})
    data = _parse(result)
    assert data["ok"] is False
    assert data["error"] == "INVALID_INPUT"


@pytest.mark.asyncio
async def test_remember_auto_detects_space(svc):
    with patch.object(config, "EVERMEMOS_DEFAULT_SPACE", "coding:my-repo"):
        result = await server_mod.handle_call_tool(
            "remember", {"content": "auto space"}
        )
    data = _parse(result)
    assert data["ok"] is True
    assert data["space_id"] == "coding:my-repo"


@pytest.mark.asyncio
async def test_invalid_role_mapped_to_invalid_input(svc):
    result = await server_mod.handle_call_tool(
        "remember",
        {
            "content": "x",
            "space_id": "coding:app",
            "role": "system",
        },
    )
    data = _parse(result)
    assert data["ok"] is False
    assert data["error"] == "INVALID_INPUT"


@pytest.mark.asyncio
async def test_unknown_tool(svc):
    result = await server_mod.handle_call_tool("nonexistent", {})
    data = _parse(result)
    assert data["ok"] is False
    assert data["error"] == "UNKNOWN_TOOL"


@pytest.mark.asyncio
async def test_arguments_none_mapped_to_invalid_input(svc):
    with patch.object(config, "EVERMEMOS_DEFAULT_SPACE", None):
        result = await server_mod.handle_call_tool("remember", None)  # type: ignore[arg-type]
    data = _parse(result)
    assert data["ok"] is False
    assert data["error"] == "INVALID_INPUT"


@pytest.mark.asyncio
async def test_uninitialized_service_returns_config_error():
    server_mod._svc = None
    result = await server_mod.handle_call_tool("list_spaces", {})
    data = _parse(result)
    assert data["ok"] is False
    assert data["error"] == "CONFIG_ERROR"


# -- error diagnostics --


@pytest.mark.asyncio
async def test_upstream_unavailable_includes_hint(svc):
    svc._client.search_memories = AsyncMock(
        side_effect=EverMemosError("timeout", code="UPSTREAM_UNAVAILABLE")
    )
    svc._catalog.ensure_space("coding:app")
    result = await server_mod.handle_call_tool(
        "recall", {"query": "x", "space_id": "coding:app"}
    )
    data = _parse(result)
    assert data["ok"] is False
    assert "hint" in data
    assert "network" in data["hint"].lower()


@pytest.mark.asyncio
async def test_config_error_api_key_includes_hint(svc):
    svc._client.search_memories = AsyncMock(
        side_effect=EverMemosError(
            "EVERMEMOS_API_KEY is required for Cloud API (v0)",
            code="CONFIG_ERROR",
        )
    )
    svc._catalog.ensure_space("coding:app")
    result = await server_mod.handle_call_tool(
        "recall", {"query": "x", "space_id": "coding:app"}
    )
    data = _parse(result)
    assert data["ok"] is False
    assert data["error"] == "CONFIG_ERROR"
    assert "hint" in data
    assert "EVERMEMOS_API_KEY" in data["hint"]
    assert "evermind.ai" in data["hint"]


@pytest.mark.asyncio
async def test_config_error_without_api_key_no_hint():
    server_mod._svc = None
    result = await server_mod.handle_call_tool("list_spaces", {})
    data = _parse(result)
    assert data["ok"] is False
    assert data["error"] == "CONFIG_ERROR"
    # Generic CONFIG_ERROR (not about API_KEY) should not have a hint
    assert "hint" not in data


@pytest.mark.asyncio
async def test_401_auth_error_includes_hint(svc):
    svc._client.search_memories = AsyncMock(
        side_effect=EverMemosError(
            "Unauthorized", code="UPSTREAM_ERROR", status_code=401
        )
    )
    svc._catalog.ensure_space("coding:app")
    result = await server_mod.handle_call_tool(
        "recall", {"query": "x", "space_id": "coding:app"}
    )
    data = _parse(result)
    assert data["ok"] is False
    assert "hint" in data
    assert "invalid" in data["hint"].lower() or "expired" in data["hint"].lower()


@pytest.mark.asyncio
async def test_429_rate_limit_includes_hint(svc):
    svc._client.search_memories = AsyncMock(
        side_effect=EverMemosError(
            "Too Many Requests", code="UPSTREAM_ERROR", status_code=429
        )
    )
    svc._catalog.ensure_space("coding:app")
    result = await server_mod.handle_call_tool(
        "recall", {"query": "x", "space_id": "coding:app"}
    )
    data = _parse(result)
    assert data["ok"] is False
    assert "hint" in data
    assert "rate" in data["hint"].lower()
