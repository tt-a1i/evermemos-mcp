"""Tests for server.py: tool dispatch and error mapping."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest

from evermemos_mcp import server as server_mod
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
async def test_list_tools_returns_five():
    tools = await server_mod.handle_list_tools()  # type: ignore[call-arg]
    names = {t.name for t in tools}
    assert names == {"list_spaces", "remember", "recall", "briefing", "forget"}


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


@pytest.mark.asyncio
async def test_dispatch_recall(svc):
    svc._catalog.ensure_space("coding:app")
    result = await server_mod.handle_call_tool(
        "recall", {"query": "FastAPI", "space_id": "coding:app"}
    )
    data = _parse(result)
    assert data["ok"] is True
    assert "results" in data


@pytest.mark.asyncio
async def test_dispatch_briefing(svc):
    svc._catalog.ensure_space("coding:app")
    result = await server_mod.handle_call_tool("briefing", {"space_id": "coding:app"})
    data = _parse(result)
    assert data["ok"] is True
    assert "summary" in data


@pytest.mark.asyncio
async def test_dispatch_forget(svc):
    svc._catalog.ensure_space("coding:app")
    result = await server_mod.handle_call_tool(
        "forget", {"memory_ids": ["m1"], "space_id": "coding:app"}
    )
    data = _parse(result)
    assert data["ok"] is True
    assert data["deleted_count"] == 1


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
    result = await server_mod.handle_call_tool("remember", {"content": "no space"})
    data = _parse(result)
    assert data["ok"] is False
    assert data["error"] == "INVALID_INPUT"


@pytest.mark.asyncio
async def test_unknown_tool(svc):
    result = await server_mod.handle_call_tool("nonexistent", {})
    data = _parse(result)
    assert data["ok"] is False
    assert data["error"] == "UNKNOWN_TOOL"
