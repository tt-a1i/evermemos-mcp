"""HTTP adapter for EverMemOS Cloud API.

Thin wrapper over /api/v0/memories endpoints.
Returns raw API response dicts — service layers handle interpretation.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from uuid import uuid4

import httpx

from . import config


class EverMemosError(Exception):
    """Error from EverMemOS API interaction."""

    def __init__(
        self,
        message: str,
        code: str = "UPSTREAM_ERROR",
        status_code: int | None = None,
    ):
        super().__init__(message)
        self.code = code
        self.status_code = status_code


class EverMemosClient:
    """Async HTTP client for EverMemOS Cloud v0 API.

    Handles auth headers, timeout, and response error checking.
    Lifecycle: create → use → close().
    """

    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        api_version: str | None = None,
        user_id: str | None = None,
        timeout: float = 30.0,
        get_retry_count: int = 2,
        get_retry_backoff_seconds: float = 0.25,
    ):
        self._base_url = config.EVERMEMOS_BASE_URL if base_url is None else base_url
        self._api_key = config.EVERMEMOS_API_KEY if api_key is None else api_key
        self._api_version = (
            config.EVERMEMOS_API_VERSION if api_version is None else api_version
        )
        self._user_id = config.EVERMEMOS_USER_ID if user_id is None else user_id
        self._api_base = f"{self._base_url}/api/{self._api_version}"
        self._timeout = timeout
        self._get_retry_count = max(0, int(get_retry_count))
        self._get_retry_backoff_seconds = max(0.0, float(get_retry_backoff_seconds))
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> "EverMemosClient":
        await self._get_client()
        return self

    async def __aexit__(
        self,
        exc_type,
        exc,
        tb,
    ) -> None:
        await self.close()

    @property
    def user_id(self) -> str:
        return self._user_id

    # -- lifecycle --

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            timeout = httpx.Timeout(
                connect=self._timeout,
                read=self._timeout,
                write=self._timeout,
                pool=self._timeout,
            )
            self._client = httpx.AsyncClient(
                timeout=timeout,
                limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
            )
        return self._client

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    # -- internals --

    def _headers(self) -> dict[str, str]:
        h: dict[str, str] = {"Content-Type": "application/json"}
        if self._api_key:
            h["Authorization"] = f"Bearer {self._api_key}"
            h["X-API-Key"] = self._api_key
        return h

    def _require_key(self) -> None:
        """Enforce API key for Cloud (v0). Local (v1) can work without it."""
        if self._api_version == "v0" and not self._api_key:
            raise EverMemosError(
                "EVERMEMOS_API_KEY is required for Cloud API (v0)",
                code="CONFIG_ERROR",
            )

    async def _handle(self, r: httpx.Response) -> dict:
        """Parse response; raise EverMemosError on 4xx/5xx."""
        if r.status_code >= 400:
            try:
                body = r.json()
                msg = body.get("message", r.text)
                code = body.get("code", "UPSTREAM_ERROR")
            except (ValueError, TypeError, AttributeError):
                msg = r.text[:500]
                code = "UPSTREAM_ERROR"
            raise EverMemosError(msg, code=code, status_code=r.status_code)

        try:
            body = r.json()
        except ValueError as exc:
            raise EverMemosError(
                "Upstream returned invalid JSON response",
                code="UPSTREAM_ERROR",
                status_code=r.status_code,
            ) from exc

        if not isinstance(body, dict):
            raise EverMemosError(
                "Upstream returned non-object JSON response",
                code="UPSTREAM_ERROR",
                status_code=r.status_code,
            )
        return body

    async def _request(self, method: str, path: str, **kwargs) -> dict:
        """Unified HTTP request with network error wrapping.

        All public methods should use this instead of raw httpx calls.
        Catches httpx.RequestError (connect, timeout, etc.) and wraps
        them as EverMemosError(code="UPSTREAM_UNAVAILABLE").
        """
        client = await self._get_client()
        method_upper = method.upper()
        retries = self._get_retry_count if method_upper == "GET" else 0
        attempts = retries + 1

        for attempt in range(attempts):
            try:
                r = await client.request(
                    method_upper,
                    f"{self._api_base}{path}",
                    headers=self._headers(),
                    **kwargs,
                )
            except httpx.TimeoutException as exc:
                if attempt < retries:
                    await asyncio.sleep(self._get_retry_backoff_seconds * (2**attempt))
                    continue
                raise EverMemosError(
                    f"Request timed out: {exc}",
                    code="UPSTREAM_UNAVAILABLE",
                ) from exc
            except httpx.RequestError as exc:
                if attempt < retries:
                    await asyncio.sleep(self._get_retry_backoff_seconds * (2**attempt))
                    continue
                raise EverMemosError(
                    f"Network error: {exc}",
                    code="UPSTREAM_UNAVAILABLE",
                ) from exc

            if r.status_code in {500, 502, 503, 504} and attempt < retries:
                await asyncio.sleep(self._get_retry_backoff_seconds * (2**attempt))
                continue
            return await self._handle(r)

        raise EverMemosError(
            "Request failed after retries",
            code="UPSTREAM_UNAVAILABLE",
        )

    @staticmethod
    def _maybe_hint_get_body_stripping(
        error: EverMemosError, payload: dict
    ) -> EverMemosError:
        if error.status_code not in {400, 422}:
            return error

        msg = str(error)
        needles = [
            "Missing required field",
            "group_ids",
            "query",
            "memory_type",
        ]
        if not any(n in msg for n in needles):
            return error

        if not payload:
            return error

        hint = (
            "Possible network/proxy issue: GET request JSON body may be stripped by a proxy/WAF. "
            "If you're behind a corporate proxy, try configuring an allowlist or switching to a network that preserves GET bodies."
        )
        return EverMemosError(
            f"{msg} ({hint})", code=error.code, status_code=error.status_code
        )

    # -- public API --

    async def add_message(
        self,
        group_id: str,
        content: str,
        *,
        sender: str | None = None,
        sender_name: str | None = None,
        role: str = "user",
        flush: bool = True,
        message_id: str | None = None,
        create_time: str | None = None,
        group_name: str | None = None,
    ) -> dict:
        """Write a message to EverMemOS.

        Cloud v0 always returns 202 ``{"status": "queued", "request_id": "..."}``.
        Local v1 returns 200 with extraction result.
        """
        self._require_key()

        effective_sender = sender or self._user_id
        payload: dict = {
            "message_id": message_id or f"msg_{uuid4().hex[:12]}",
            "create_time": create_time or datetime.now(timezone.utc).isoformat(),
            "sender": effective_sender,
            "sender_name": sender_name or effective_sender,
            "role": role,
            "content": content,
            "group_id": group_id,
        }
        if group_name:
            payload["group_name"] = group_name
        # Always send flush explicitly to avoid relying on upstream defaults.
        payload["flush"] = flush

        return await self._request("POST", "/memories", json=payload)

    async def fetch_memories(
        self,
        group_id: str,
        *,
        memory_type: str = "episodic_memory",
        user_id: str | None = None,
        limit: int = 40,
        offset: int = 0,
        start_time: str | None = None,
        end_time: str | None = None,
    ) -> dict:
        """Fetch memories by type from a space.

        API contract (Cloud v0): GET /memories with JSON body.
        """
        self._require_key()

        page_size = max(1, min(limit, 100))
        safe_offset = max(0, offset)
        page = (safe_offset // page_size) + 1

        payload: dict = {
            "group_ids": [group_id],
            "user_id": user_id or self._user_id,
            "memory_type": memory_type,
            "page": page,
            "page_size": page_size,
        }
        if start_time:
            payload["start_time"] = start_time
        if end_time:
            payload["end_time"] = end_time

        try:
            return await self._request("GET", "/memories", json=payload)
        except EverMemosError as exc:
            raise self._maybe_hint_get_body_stripping(exc, payload) from exc

    async def search_memories(
        self,
        query: str,
        group_id: str,
        *,
        retrieve_method: str = "hybrid",
        memory_types: list[str] | None = None,
        top_k: int = 10,
        user_id: str | None = None,
        start_time: str | None = None,
        end_time: str | None = None,
        current_time: str | None = None,
        radius: float | None = None,
        include_metadata: bool | None = None,
    ) -> dict:
        """Search memories in a space.

        EverMemOS search endpoint uses **GET with JSON body**.
        """
        self._require_key()

        payload: dict = {
            "query": query,
            "group_ids": [group_id],
            "user_id": user_id or self._user_id,
            "retrieve_method": retrieve_method,
            "top_k": top_k,
        }
        if memory_types:
            payload["memory_types"] = memory_types
        if start_time:
            payload["start_time"] = start_time
        if end_time:
            payload["end_time"] = end_time
        if current_time:
            payload["current_time"] = current_time
        if radius is not None:
            payload["radius"] = radius
        if include_metadata is not None:
            payload["include_metadata"] = include_metadata

        try:
            return await self._request("GET", "/memories/search", json=payload)
        except EverMemosError as exc:
            raise self._maybe_hint_get_body_stripping(exc, payload) from exc

    async def get_request_status(self, request_id: str) -> dict:
        """Get async processing status for a queued add-memory request.

        Tries primary path /status/request, fallbacks to /memories/status if needed.
        """
        self._require_key()

        if not isinstance(request_id, str) or not request_id.strip():
            raise EverMemosError("request_id is required", code="INVALID_INPUT")

        request_id = request_id.strip()
        params = {"request_id": request_id}

        try:
            return await self._request("GET", "/status/request", params=params)
        except EverMemosError as exc:
            # Fallback for older/different API versions if path not found or invalid
            if exc.status_code in {400, 404, 405, 422}:
                try:
                    return await self._request("GET", "/memories/status", params=params)
                except EverMemosError:
                    # If fallback also fails, propagate original error unless fallback gives better info
                    raise exc
            raise

    async def set_conversation_metadata(
        self,
        *,
        group_id: str,
        scene: str,
        created_at: str,
        description: str | None = None,
        scene_desc: dict | None = None,
        tags: list[str] | None = None,
        llm_custom_setting: dict | None = None,
        user_details: dict | None = None,
        default_timezone: str | None = None,
    ) -> dict:
        """Create conversation metadata for a group."""
        self._require_key()

        payload: dict = {
            "group_id": group_id,
            "scene": scene,
            "created_at": created_at,
        }
        if description is not None:
            payload["description"] = description
        if scene_desc is not None:
            payload["scene_desc"] = scene_desc
        if tags is not None:
            payload["tags"] = tags
        if llm_custom_setting is not None:
            payload["llm_custom_setting"] = llm_custom_setting
        if user_details is not None:
            payload["user_details"] = user_details
        if default_timezone is not None:
            payload["default_timezone"] = default_timezone

        return await self._request("POST", "/memories/conversation-meta", json=payload)

    async def update_conversation_metadata(
        self,
        *,
        group_id: str,
        description: str | None = None,
        scene_desc: dict | None = None,
        tags: list[str] | None = None,
        llm_custom_setting: dict | None = None,
        user_details: dict | None = None,
        default_timezone: str | None = None,
    ) -> dict:
        """Patch conversation metadata for a group."""
        self._require_key()

        payload: dict = {"group_id": group_id}
        if description is not None:
            payload["description"] = description
        if scene_desc is not None:
            payload["scene_desc"] = scene_desc
        if tags is not None:
            payload["tags"] = tags
        if llm_custom_setting is not None:
            payload["llm_custom_setting"] = llm_custom_setting
        if user_details is not None:
            payload["user_details"] = user_details
        if default_timezone is not None:
            payload["default_timezone"] = default_timezone

        return await self._request("PATCH", "/memories/conversation-meta", json=payload)

    async def get_conversation_metadata(self, group_id: str) -> dict:
        """Get conversation metadata for a group.

        Some upstream deployments accept `group_id` via query params,
        others via GET JSON body. Try query params first, then fallback.
        """
        self._require_key()

        if not isinstance(group_id, str) or not group_id.strip():
            raise EverMemosError("group_id is required", code="INVALID_INPUT")

        gid = group_id.strip()
        try:
            return await self._request(
                "GET",
                "/memories/conversation-meta",
                params={"group_id": gid},
            )
        except EverMemosError as exc:
            if exc.status_code not in {400, 404, 422}:
                raise
            return await self._request(
                "GET",
                "/memories/conversation-meta",
                json={"group_id": gid},
            )

    async def delete_memories(
        self,
        *,
        memory_id: str | None = None,
        user_id: str | None = None,
        group_id: str | None = None,
    ) -> dict:
        """Soft-delete memories matching the given filters.

        At least one filter must be provided (AND logic).
        """
        self._require_key()

        payload: dict = {}
        if memory_id is not None:
            if not isinstance(memory_id, str) or not memory_id.strip():
                raise EverMemosError(
                    "memory_id must be a non-empty string when provided",
                    code="INVALID_INPUT",
                )
            payload["memory_id"] = memory_id.strip()
        if user_id is not None:
            if not isinstance(user_id, str) or not user_id.strip():
                raise EverMemosError(
                    "user_id must be a non-empty string when provided",
                    code="INVALID_INPUT",
                )
            payload["user_id"] = user_id.strip()
        if group_id is not None:
            if not isinstance(group_id, str) or not group_id.strip():
                raise EverMemosError(
                    "group_id must be a non-empty string when provided",
                    code="INVALID_INPUT",
                )
            payload["group_id"] = group_id.strip()

        if not payload:
            raise EverMemosError(
                "At least one filter (memory_id / user_id / group_id) required for delete",
                code="INVALID_INPUT",
            )

        return await self._request("DELETE", "/memories", json=payload)
