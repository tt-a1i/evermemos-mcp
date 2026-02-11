"""Tests for evermemos_client: error wrapping, auth gating."""

from __future__ import annotations

import pytest
import httpx

from evermemos_mcp.evermemos_client import EverMemosClient, EverMemosError


# -- auth gating --


def test_v0_requires_api_key():
    """v0 (Cloud) must reject calls when API key is missing."""
    c = EverMemosClient(api_key="none", api_version="v0")
    c._api_key = ""
    with pytest.raises(EverMemosError) as exc_info:
        c._require_key()
    assert exc_info.value.code == "CONFIG_ERROR"


def test_v1_allows_no_api_key():
    """v1 (local) should not enforce API key."""
    c = EverMemosClient(api_key="none", api_version="v1")
    c._api_key = ""
    # Should not raise
    c._require_key()


# -- response handling --


@pytest.mark.asyncio
async def test_handle_202_queued():
    """Cloud v0 returns 202 for queued writes."""
    c = EverMemosClient()
    resp = httpx.Response(
        202,
        json={"status": "queued", "request_id": "abc123"},
        request=httpx.Request("POST", "http://test"),
    )
    result = await c._handle(resp)
    assert result["status"] == "queued"
    assert result["request_id"] == "abc123"


@pytest.mark.asyncio
async def test_handle_200_ok():
    """Normal 200 response is returned as-is."""
    c = EverMemosClient()
    resp = httpx.Response(
        200,
        json={"status": "ok", "result": {"memories": []}},
        request=httpx.Request("GET", "http://test"),
    )
    result = await c._handle(resp)
    assert result["status"] == "ok"


@pytest.mark.asyncio
async def test_handle_400_raises():
    """4xx responses raise EverMemosError with upstream code."""
    c = EverMemosClient()
    resp = httpx.Response(
        400,
        json={"status": "failed", "code": "INVALID_PARAMETER", "message": "bad input"},
        request=httpx.Request("POST", "http://test"),
    )
    with pytest.raises(EverMemosError) as exc_info:
        await c._handle(resp)
    assert exc_info.value.code == "INVALID_PARAMETER"
    assert exc_info.value.status_code == 400


@pytest.mark.asyncio
async def test_handle_500_raises():
    """5xx responses raise EverMemosError."""
    c = EverMemosClient()
    resp = httpx.Response(
        500,
        text="Internal Server Error",
        request=httpx.Request("GET", "http://test"),
    )
    with pytest.raises(EverMemosError) as exc_info:
        await c._handle(resp)
    assert exc_info.value.status_code == 500
    assert exc_info.value.code == "UPSTREAM_ERROR"


# -- network error wrapping --


@pytest.mark.asyncio
async def test_network_timeout_wraps_as_upstream_unavailable():
    """httpx.TimeoutException is wrapped as UPSTREAM_UNAVAILABLE."""
    c = EverMemosClient(
        api_key="fake",
        api_version="v0",
        base_url="http://192.0.2.1:1",  # RFC 5737 TEST-NET, unreachable
        timeout=2.0,
    )
    with pytest.raises(EverMemosError) as exc_info:
        await c.add_message("g", "content")
    assert exc_info.value.code == "UPSTREAM_UNAVAILABLE"
    await c.close()


# -- delete input validation --


@pytest.mark.asyncio
async def test_delete_requires_at_least_one_filter():
    """delete_memories without any filter raises INVALID_INPUT."""
    c = EverMemosClient(api_key="fake", api_version="v0")
    with pytest.raises(EverMemosError) as exc_info:
        await c.delete_memories()
    assert exc_info.value.code == "INVALID_INPUT"
