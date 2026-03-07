"""Tests for evermemos_client: error wrapping, auth gating."""

from __future__ import annotations

from unittest.mock import AsyncMock

import httpx
import pytest

from evermemos_mcp.evermemos_client import EverMemosClient, EverMemosError
from evermemos_mcp import config


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


def test_explicit_empty_api_key_does_not_fallback_to_env(monkeypatch):
    monkeypatch.setattr(config, "EVERMEMOS_API_KEY", "env-key")
    c = EverMemosClient(api_key="", api_version="v0")
    assert c._api_key == ""


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


@pytest.mark.asyncio
async def test_handle_200_invalid_json_raises_upstream_error():
    c = EverMemosClient()
    resp = httpx.Response(
        200,
        text="not-json",
        request=httpx.Request("GET", "http://test"),
    )
    with pytest.raises(EverMemosError) as exc_info:
        await c._handle(resp)
    assert exc_info.value.code == "UPSTREAM_ERROR"
    assert exc_info.value.status_code == 200


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


@pytest.mark.asyncio
async def test_request_retries_get_on_network_error():
    c = EverMemosClient(api_key="fake", api_version="v0", get_retry_count=2)
    req = httpx.Request("GET", "http://test")
    response = httpx.Response(200, json={"status": "ok"}, request=req)

    mock_client = AsyncMock()
    mock_client.request = AsyncMock(
        side_effect=[
            httpx.ConnectError("conn reset", request=req),
            response,
        ]
    )
    c._get_client = AsyncMock(return_value=mock_client)

    result = await c._request("GET", "/memories")

    assert result["status"] == "ok"
    assert mock_client.request.call_count == 2


@pytest.mark.asyncio
async def test_request_does_not_retry_post_on_network_error():
    c = EverMemosClient(api_key="fake", api_version="v0", get_retry_count=2)
    req = httpx.Request("POST", "http://test")
    mock_client = AsyncMock()
    mock_client.request = AsyncMock(
        side_effect=httpx.ConnectError("conn reset", request=req)
    )
    c._get_client = AsyncMock(return_value=mock_client)

    with pytest.raises(EverMemosError) as exc_info:
        await c._request("POST", "/memories", json={"x": 1})

    assert exc_info.value.code == "UPSTREAM_UNAVAILABLE"
    assert mock_client.request.call_count == 1


@pytest.mark.asyncio
async def test_request_retries_get_on_503_response():
    c = EverMemosClient(api_key="fake", api_version="v0", get_retry_count=2)
    req = httpx.Request("GET", "http://test")
    response_503 = httpx.Response(503, text="busy", request=req)
    response_200 = httpx.Response(200, json={"status": "ok"}, request=req)

    mock_client = AsyncMock()
    mock_client.request = AsyncMock(side_effect=[response_503, response_200])
    c._get_client = AsyncMock(return_value=mock_client)

    result = await c._request("GET", "/memories")
    assert result["status"] == "ok"
    assert mock_client.request.call_count == 2


@pytest.mark.asyncio
async def test_request_retries_on_429_with_retry_after_header():
    c = EverMemosClient(
        api_key="fake",
        api_version="v0",
        rate_limit_retry_count=1,
    )
    req = httpx.Request("POST", "http://test")
    response_429 = httpx.Response(
        429,
        json={"code": "RATE_LIMIT", "message": "Too many requests"},
        headers={"Retry-After": "0"},
        request=req,
    )
    response_queued = httpx.Response(
        202,
        json={"status": "queued", "request_id": "req-1"},
        request=req,
    )

    mock_client = AsyncMock()
    mock_client.request = AsyncMock(side_effect=[response_429, response_queued])
    c._get_client = AsyncMock(return_value=mock_client)

    result = await c._request("POST", "/memories", json={"x": 1})
    assert result["status"] == "queued"
    assert mock_client.request.call_count == 2


@pytest.mark.asyncio
async def test_request_returns_429_error_after_rate_limit_retries_exhausted():
    c = EverMemosClient(
        api_key="fake",
        api_version="v0",
        rate_limit_retry_count=1,
        rate_limit_backoff_seconds=0,
    )
    req = httpx.Request("GET", "http://test")
    response_429 = httpx.Response(
        429,
        json={"code": "RATE_LIMIT", "message": "Too many requests"},
        request=req,
    )

    mock_client = AsyncMock()
    mock_client.request = AsyncMock(side_effect=[response_429, response_429])
    c._get_client = AsyncMock(return_value=mock_client)

    with pytest.raises(EverMemosError) as exc_info:
        await c._request("GET", "/memories")

    assert exc_info.value.status_code == 429
    assert mock_client.request.call_count == 2


@pytest.mark.asyncio
async def test_client_supports_async_context_manager_close():
    c = EverMemosClient(api_key="fake", api_version="v0")
    c._get_client = AsyncMock(return_value=AsyncMock())
    c.close = AsyncMock()

    async with c as entered:
        assert entered is c

    c.close.assert_called_once()


# -- delete input validation --


@pytest.mark.asyncio
async def test_delete_requires_at_least_one_filter():
    """delete_memories without any filter raises INVALID_INPUT."""
    c = EverMemosClient(api_key="fake", api_version="v0")
    with pytest.raises(EverMemosError) as exc_info:
        await c.delete_memories()
    assert exc_info.value.code == "INVALID_INPUT"


@pytest.mark.asyncio
async def test_delete_rejects_empty_memory_id_when_provided():
    c = EverMemosClient(api_key="fake", api_version="v0")
    with pytest.raises(EverMemosError) as exc_info:
        await c.delete_memories(memory_id="   ")
    assert exc_info.value.code == "INVALID_INPUT"


@pytest.mark.asyncio
async def test_fetch_memories_uses_get_json_body_contract():
    c = EverMemosClient(api_key="fake", api_version="v0")
    c._request = AsyncMock(return_value={"status": "ok", "result": {"memories": []}})

    await c.fetch_memories("space::coding:app", memory_type="episodic_memory", limit=20)

    c._request.assert_called_once()
    _, kwargs = c._request.call_args
    assert kwargs["json"]["group_ids"] == ["space::coding:app"]
    assert kwargs["json"]["page"] == 1
    assert kwargs["json"]["page_size"] == 20


@pytest.mark.asyncio
async def test_fetch_memories_maps_non_zero_offset_to_page_number():
    c = EverMemosClient(api_key="fake", api_version="v0")
    c._request = AsyncMock(return_value={"status": "ok", "result": {"memories": []}})

    await c.fetch_memories(
        "space::coding:app",
        memory_type="episodic_memory",
        limit=20,
        offset=25,
    )

    _, kwargs = c._request.call_args
    assert kwargs["json"]["page"] == 2
    assert kwargs["json"]["page_size"] == 20


@pytest.mark.asyncio
async def test_fetch_memories_passes_time_filters_when_provided():
    c = EverMemosClient(api_key="fake", api_version="v0")
    c._request = AsyncMock(return_value={"status": "ok", "result": {"memories": []}})

    await c.fetch_memories(
        "space::coding:app",
        memory_type="event_log",
        start_time="2024-01-01T00:00:00+00:00",
        end_time="2024-12-31T23:59:59+00:00",
    )

    _, kwargs = c._request.call_args
    payload = kwargs["json"]
    assert payload["start_time"] == "2024-01-01T00:00:00+00:00"
    assert payload["end_time"] == "2024-12-31T23:59:59+00:00"


@pytest.mark.asyncio
async def test_fetch_memories_supports_up_to_50_group_ids():
    c = EverMemosClient(api_key="fake", api_version="v0")
    c._request = AsyncMock(return_value={"status": "ok", "result": {"memories": []}})

    group_ids = [f"space::team:{index}" for index in range(12)]
    await c.fetch_memories(group_ids, memory_type="event_log")

    _, kwargs = c._request.call_args
    assert kwargs["json"]["group_ids"] == group_ids


@pytest.mark.asyncio
async def test_fetch_memories_rejects_more_than_50_group_ids():
    c = EverMemosClient(api_key="fake", api_version="v0")
    group_ids = [f"space::team:{index}" for index in range(51)]

    with pytest.raises(EverMemosError) as exc_info:
        await c.fetch_memories(group_ids)

    assert exc_info.value.code == "INVALID_INPUT"


@pytest.mark.asyncio
async def test_fetch_memories_adds_proxy_hint_for_missing_required_fields():
    c = EverMemosClient(api_key="fake", api_version="v0")
    c._request = AsyncMock(
        side_effect=EverMemosError(
            "Missing required field group_ids",
            code="INVALID_PARAMETER",
            status_code=400,
        )
    )

    with pytest.raises(EverMemosError) as exc_info:
        await c.fetch_memories("space::coding:app")

    assert "GET request JSON body may be stripped" in str(exc_info.value)


@pytest.mark.asyncio
async def test_fetch_memories_fallbacks_to_post_after_get_body_strip_hint():
    c = EverMemosClient(api_key="fake", api_version="v0")
    c._request = AsyncMock(
        side_effect=[
            EverMemosError(
                "Missing required field group_ids",
                code="INVALID_PARAMETER",
                status_code=400,
            ),
            {"status": "ok", "result": {"memories": []}},
        ]
    )

    result = await c.fetch_memories("space::coding:app")

    assert result["status"] == "ok"
    assert c._request.call_count == 2
    first_call = c._request.call_args_list[0]
    second_call = c._request.call_args_list[1]
    assert first_call.args[0] == "GET"
    assert second_call.args[0] == "POST"
    assert first_call.args[1] == "/memories"
    assert second_call.args[1] == "/memories"


@pytest.mark.asyncio
async def test_fetch_memories_fallback_post_failure_preserves_post_error():
    c = EverMemosClient(api_key="fake", api_version="v0")
    c._request = AsyncMock(
        side_effect=[
            EverMemosError(
                "Missing required field group_ids",
                code="INVALID_PARAMETER",
                status_code=400,
            ),
            EverMemosError(
                "bad gateway",
                code="UPSTREAM_ERROR",
                status_code=502,
            ),
        ]
    )

    with pytest.raises(EverMemosError) as exc_info:
        await c.fetch_memories("space::coding:app")

    assert str(exc_info.value) == "bad gateway"
    assert exc_info.value.status_code == 502
    assert "GET request JSON body may be stripped" not in str(exc_info.value)


@pytest.mark.asyncio
async def test_add_message_sends_flush_false_explicitly():
    c = EverMemosClient(api_key="fake", api_version="v0")
    c._request = AsyncMock(return_value={"status": "queued", "request_id": "req-1"})

    await c.add_message("space::coding:app", "hello", flush=False)

    _, kwargs = c._request.call_args
    assert kwargs["json"]["flush"] is False


@pytest.mark.asyncio
async def test_add_message_defaults_flush_to_false():
    c = EverMemosClient(api_key="fake", api_version="v0")
    c._request = AsyncMock(return_value={"status": "queued", "request_id": "req-1"})

    await c.add_message("space::coding:app", "hello")

    _, kwargs = c._request.call_args
    assert kwargs["json"]["flush"] is False


@pytest.mark.asyncio
async def test_add_message_rejects_create_time_without_timezone():
    c = EverMemosClient(api_key="fake", api_version="v0")
    c._request = AsyncMock(return_value={"status": "queued", "request_id": "req-1"})

    with pytest.raises(EverMemosError) as exc_info:
        await c.add_message(
            "space::coding:app",
            "hello",
            create_time="2024-01-01T00:00:00",
        )

    assert exc_info.value.code == "INVALID_INPUT"


@pytest.mark.asyncio
async def test_search_memories_uses_group_ids_in_json_body():
    c = EverMemosClient(api_key="fake", api_version="v0")
    c._request = AsyncMock(return_value={"status": "ok", "result": {"memories": []}})

    await c.search_memories("fastapi", "space::coding:app", retrieve_method="agentic")

    c._request.assert_called_once()
    _, kwargs = c._request.call_args
    assert kwargs["json"]["group_ids"] == ["space::coding:app"]
    assert kwargs["json"]["retrieve_method"] == "agentic"


@pytest.mark.asyncio
async def test_search_memories_supports_multiple_group_ids():
    c = EverMemosClient(api_key="fake", api_version="v0")
    c._request = AsyncMock(return_value={"status": "ok", "result": {"memories": []}})

    await c.search_memories(
        "fastapi",
        ["space::coding:app", "space::coding:infra", "space::coding:app"],
    )

    _, kwargs = c._request.call_args
    assert kwargs["json"]["group_ids"] == ["space::coding:app", "space::coding:infra"]


@pytest.mark.asyncio
async def test_search_memories_rejects_more_than_10_group_ids():
    c = EverMemosClient(api_key="fake", api_version="v0")
    group_ids = [f"space::team:{index}" for index in range(11)]

    with pytest.raises(EverMemosError) as exc_info:
        await c.search_memories("fastapi", group_ids)

    assert exc_info.value.code == "INVALID_INPUT"


@pytest.mark.asyncio
async def test_search_memories_allows_none_group_ids_for_global_search():
    c = EverMemosClient(api_key="fake", api_version="v0")
    c._request = AsyncMock(return_value={"status": "ok", "result": {"memories": []}})

    await c.search_memories("fastapi", None)

    _, kwargs = c._request.call_args
    assert "group_ids" not in kwargs["json"]


@pytest.mark.asyncio
async def test_search_memories_passes_optional_filters():
    c = EverMemosClient(api_key="fake", api_version="v0")
    c._request = AsyncMock(return_value={"status": "ok", "result": {"memories": []}})

    await c.search_memories(
        "fastapi",
        "space::coding:app",
        retrieve_method="hybrid",
        memory_types=["episodic_memory"],
        start_time="2024-01-01T00:00:00+00:00",
        end_time="2024-12-31T23:59:59+00:00",
        current_time="2024-06-01T00:00:00+00:00",
        radius=0.7,
        include_metadata=True,
    )

    c._request.assert_called_once()
    _, kwargs = c._request.call_args
    payload = kwargs["json"]
    assert payload["memory_types"] == ["episodic_memory"]
    assert payload["start_time"] == "2024-01-01T00:00:00+00:00"
    assert payload["end_time"] == "2024-12-31T23:59:59+00:00"
    assert payload["current_time"] == "2024-06-01T00:00:00+00:00"
    assert payload["radius"] == 0.7
    assert payload["include_metadata"] is True


@pytest.mark.asyncio
async def test_delete_memories_uses_memory_id_in_json_body():
    c = EverMemosClient(api_key="fake", api_version="v0")
    c._request = AsyncMock(return_value={"status": "ok", "result": {"count": 1}})

    await c.delete_memories(memory_id="mem-123")

    c._request.assert_called_once()
    _, kwargs = c._request.call_args
    assert kwargs["json"]["memory_id"] == "mem-123"


@pytest.mark.asyncio
async def test_delete_memories_falls_back_to_event_id_when_memory_id_is_rejected():
    c = EverMemosClient(api_key="fake", api_version="v0")
    c._request = AsyncMock(
        side_effect=[
            EverMemosError(
                "Missing required field event_id",
                code="INVALID_PARAMETER",
                status_code=400,
            ),
            {"status": "ok", "result": {"count": 1}},
        ]
    )

    result = await c.delete_memories(memory_id="mem-123")

    assert result["status"] == "ok"
    assert c._request.call_count == 2
    first_call = c._request.call_args_list[0]
    second_call = c._request.call_args_list[1]
    assert first_call.kwargs["json"]["memory_id"] == "mem-123"
    assert "event_id" not in first_call.kwargs["json"]
    assert second_call.kwargs["json"]["event_id"] == "mem-123"
    assert "memory_id" not in second_call.kwargs["json"]


@pytest.mark.asyncio
async def test_delete_memories_does_not_fallback_for_non_schema_errors():
    c = EverMemosClient(api_key="fake", api_version="v0")
    c._request = AsyncMock(
        side_effect=EverMemosError(
            "memory not found",
            code="NOT_FOUND",
            status_code=404,
        )
    )

    with pytest.raises(EverMemosError) as exc_info:
        await c.delete_memories(memory_id="mem-404")

    assert exc_info.value.code == "NOT_FOUND"
    assert c._request.call_count == 1


@pytest.mark.asyncio
async def test_get_request_status_requires_request_id():
    c = EverMemosClient(api_key="fake", api_version="v0")
    with pytest.raises(EverMemosError) as exc_info:
        await c.get_request_status("   ")
    assert exc_info.value.code == "INVALID_INPUT"


@pytest.mark.asyncio
async def test_get_request_status_uses_status_request_endpoint_only():
    c = EverMemosClient(api_key="fake", api_version="v0")
    c._request = AsyncMock(
        return_value={"status": "ok", "result": {"request_id": "req-123"}}
    )

    result = await c.get_request_status("req-123")

    assert result["status"] == "ok"
    assert c._request.call_count == 1
    first_call = c._request.call_args_list[0]
    assert first_call.args[1] == "/status/request"


@pytest.mark.asyncio
async def test_get_request_status_propagates_error_without_legacy_fallback():
    c = EverMemosClient(api_key="fake", api_version="v0")
    c._request = AsyncMock(side_effect=EverMemosError("not found", status_code=404))

    with pytest.raises(EverMemosError) as exc_info:
        await c.get_request_status("req-123")

    assert exc_info.value.status_code == 404
    assert c._request.call_count == 1


@pytest.mark.asyncio
async def test_set_conversation_metadata_payload():
    c = EverMemosClient(api_key="fake", api_version="v0")
    c._request = AsyncMock(return_value={"status": "ok", "result": {"id": "meta-1"}})

    await c.set_conversation_metadata(
        group_id="space::coding:app",
        scene="assistant",
        created_at="2025-01-15T10:00:00+00:00",
        description="Coding app memory",
        scene_desc={"space_id": "coding:app"},
        tags=["mcp"],
        llm_custom_setting={
            "boundary": {"provider": "openrouter", "model": "openai/gpt-4.1-mini"}
        },
        user_details={"mcp-user": {"full_name": "Test User", "role": "user"}},
    )

    _, kwargs = c._request.call_args
    payload = kwargs["json"]
    assert payload["group_id"] == "space::coding:app"
    assert payload["scene"] == "assistant"
    assert payload["created_at"] == "2025-01-15T10:00:00+00:00"
    assert payload["description"] == "Coding app memory"
    assert payload["user_details"]["mcp-user"]["full_name"] == "Test User"


@pytest.mark.asyncio
async def test_set_conversation_metadata_payload_supports_name_and_optional_scene():
    c = EverMemosClient(api_key="fake", api_version="v0")
    c._request = AsyncMock(return_value={"status": "ok", "result": {"id": "meta-1"}})

    await c.set_conversation_metadata(
        group_id="space::coding:app",
        scene=None,
        name="coding:app",
        created_at="2025-01-15T10:00:00+00:00",
        description="Coding app memory",
    )

    _, kwargs = c._request.call_args
    payload = kwargs["json"]
    assert payload["group_id"] == "space::coding:app"
    assert payload["name"] == "coding:app"
    assert payload["created_at"] == "2025-01-15T10:00:00+00:00"
    assert "scene" not in payload


@pytest.mark.asyncio
async def test_get_conversation_metadata_fallbacks_to_json_body():
    c = EverMemosClient(api_key="fake", api_version="v0")
    c._request = AsyncMock(
        side_effect=[
            EverMemosError("invalid parameter", status_code=400),
            {"status": "ok", "result": {"id": "meta-1"}},
        ]
    )

    result = await c.get_conversation_metadata("space::coding:app")

    assert result["status"] == "ok"
    assert c._request.call_count == 2


@pytest.mark.asyncio
async def test_update_conversation_metadata_payload():
    c = EverMemosClient(api_key="fake", api_version="v0")
    c._request = AsyncMock(return_value={"status": "ok", "result": {"id": "meta-1"}})

    await c.update_conversation_metadata(
        group_id="space::coding:app",
        description="Updated",
        tags=["mcp", "space"],
        user_details={"assistant": {"full_name": "AI Assistant", "role": "assistant"}},
    )

    _, kwargs = c._request.call_args
    assert kwargs["json"]["group_id"] == "space::coding:app"
    assert kwargs["json"]["description"] == "Updated"
    assert kwargs["json"]["tags"] == ["mcp", "space"]
    assert kwargs["json"]["user_details"]["assistant"]["role"] == "assistant"
