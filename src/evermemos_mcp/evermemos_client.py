"""HTTP adapter for EverMemOS Cloud API.

Thin wrapper over /api/v0/memories endpoints.
Returns raw API response dicts — service layers handle interpretation.
"""

from __future__ import annotations

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
    ):
        self._base_url = base_url or config.EVERMEMOS_BASE_URL
        self._api_key = api_key or config.EVERMEMOS_API_KEY
        self._api_version = api_version or config.EVERMEMOS_API_VERSION
        self._user_id = user_id or config.EVERMEMOS_USER_ID
        self._api_base = f"{self._base_url}/api/{self._api_version}"
        self._timeout = timeout
        self._client: httpx.AsyncClient | None = None

    @property
    def user_id(self) -> str:
        return self._user_id

    # -- lifecycle --

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=self._timeout)
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
        if r.status_code == 202:
            return r.json()
        if r.status_code >= 400:
            try:
                body = r.json()
                msg = body.get("message", r.text)
                code = body.get("code", "UPSTREAM_ERROR")
            except Exception:
                msg = r.text[:500]
                code = "UPSTREAM_ERROR"
            raise EverMemosError(msg, code=code, status_code=r.status_code)
        return r.json()

    async def _request(self, method: str, path: str, **kwargs) -> dict:
        """Unified HTTP request with network error wrapping.

        All public methods should use this instead of raw httpx calls.
        Catches httpx.RequestError (connect, timeout, etc.) and wraps
        them as EverMemosError(code="UPSTREAM_UNAVAILABLE").
        """
        client = await self._get_client()
        try:
            r = await client.request(
                method, f"{self._api_base}{path}", headers=self._headers(), **kwargs
            )
        except httpx.TimeoutException as exc:
            raise EverMemosError(
                f"Request timed out: {exc}",
                code="UPSTREAM_UNAVAILABLE",
            ) from exc
        except httpx.RequestError as exc:
            raise EverMemosError(
                f"Network error: {exc}",
                code="UPSTREAM_UNAVAILABLE",
            ) from exc
        return await self._handle(r)

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
        if flush:
            payload["flush"] = True

        return await self._request("POST", "/memories", json=payload)

    async def fetch_memories(
        self,
        group_id: str,
        *,
        memory_type: str = "episodic_memory",
        user_id: str | None = None,
        limit: int = 40,
        offset: int = 0,
    ) -> dict:
        """Fetch memories by type from a space."""
        self._require_key()

        params: dict = {
            "group_id": group_id,
            "user_id": user_id or self._user_id,
            "memory_type": memory_type,
            "limit": limit,
            "offset": offset,
        }

        return await self._request("GET", "/memories", params=params)

    async def search_memories(
        self,
        query: str,
        group_id: str,
        *,
        retrieve_method: str = "hybrid",
        memory_types: list[str] | None = None,
        top_k: int = 5,
    ) -> dict:
        """Search memories in a space.

        EverMemOS search endpoint uses **GET with JSON body**.
        """
        self._require_key()

        payload: dict = {
            "query": query,
            "group_id": group_id,
            "retrieve_method": retrieve_method,
            "top_k": top_k,
        }
        if memory_types:
            payload["memory_types"] = memory_types

        return await self._request("GET", "/memories/search", json=payload)

    async def delete_memories(
        self,
        *,
        event_id: str | None = None,
        user_id: str | None = None,
        group_id: str | None = None,
    ) -> dict:
        """Soft-delete memories matching the given filters.

        At least one filter must be provided (AND logic).
        """
        self._require_key()

        payload: dict = {}
        if event_id:
            payload["event_id"] = event_id
        if user_id:
            payload["user_id"] = user_id
        if group_id:
            payload["group_id"] = group_id

        if not payload:
            raise EverMemosError(
                "At least one filter (event_id / user_id / group_id) required for delete",
                code="INVALID_INPUT",
            )

        return await self._request("DELETE", "/memories", json=payload)
