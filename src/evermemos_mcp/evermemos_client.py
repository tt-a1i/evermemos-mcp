"""HTTP adapter for EverMemOS / EverOS Cloud API.

Supports Cloud v1 (default) and legacy v0. Returns raw API response dicts in the
v0-compatible shape where possible — service layers handle interpretation.
"""

from __future__ import annotations

import asyncio
import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Iterable
from urllib.parse import quote
from uuid import uuid4

import httpx

from . import config

_FETCH_MAX_GROUP_IDS = 50
_SEARCH_MAX_GROUP_IDS = 10
V0_FETCH_MEMORY_TYPES = frozenset(
    {"episodic_memory", "profile", "event_log", "foresight"}
)
V1_FETCH_MEMORY_TYPES = frozenset(
    {"episodic_memory", "profile", "agent_case", "agent_skill"}
)
V1_SEARCH_MEMORY_TYPES = frozenset(
    {"agent_memory", "episodic_memory", "profile", "raw_message"}
)
_V1_GET_RESPONSE_KEYS = {
    "episodic_memory": "episodes",
    "profile": "profiles",
    "agent_case": "agent_cases",
    "agent_skill": "agent_skills",
}
_V1_USER_SCOPED_FETCH_MEMORY_TYPES = frozenset(
    {"profile", "agent_case", "agent_skill"}
)
_V1_SEARCH_RESPONSE_KEYS = {
    "episodic_memory": "episodes",
    "profile": "profiles",
    "agent_memory": "agent_memories",
    "raw_message": "raw_messages",
}
_V1_SEARCH_METHODS = frozenset({"keyword", "vector", "hybrid", "agentic"})


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
    """Async HTTP client for EverMemOS Cloud API (v1 default, v0 legacy).

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
        rate_limit_retry_count: int = 2,
        rate_limit_backoff_seconds: float = 0.5,
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
        self._rate_limit_retry_count = max(0, int(rate_limit_retry_count))
        self._rate_limit_backoff_seconds = max(0.0, float(rate_limit_backoff_seconds))
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

    def _use_v0(self) -> bool:
        return self._api_version == "v0"

    def supported_fetch_memory_types(self) -> frozenset[str]:
        return V0_FETCH_MEMORY_TYPES if self._use_v0() else V1_FETCH_MEMORY_TYPES

    def is_fetch_memory_type_supported(self, memory_type: str) -> bool:
        return memory_type in self.supported_fetch_memory_types()

    def supported_search_memory_types(self) -> frozenset[str]:
        return V1_SEARCH_MEMORY_TYPES

    @staticmethod
    def _validate_v0_fetch_memory_type(memory_type: str) -> None:
        if memory_type in {"agent_case", "agent_skill"}:
            raise EverMemosError(
                "Cloud v0 /memories/get does not support memory_type "
                f"'{memory_type}' (supported: episodic_memory, profile, "
                "event_log, foresight)",
                code="UNSUPPORTED_UPSTREAM",
            )
        if memory_type not in V0_FETCH_MEMORY_TYPES:
            raise EverMemosError(
                f"Unsupported v0 fetch memory_type '{memory_type}'",
                code="INVALID_INPUT",
            )

    @staticmethod
    def _validate_v1_fetch_memory_type(memory_type: str) -> None:
        if memory_type in {"event_log", "foresight"}:
            raise EverMemosError(
                "Cloud v1 /memories/get does not support memory_type "
                f"'{memory_type}' (supported: episodic_memory, profile, "
                "agent_case, agent_skill)",
                code="UNSUPPORTED_UPSTREAM",
            )
        if memory_type not in V1_FETCH_MEMORY_TYPES:
            raise EverMemosError(
                f"Unsupported v1 fetch memory_type '{memory_type}'",
                code="INVALID_INPUT",
            )

    @classmethod
    def _validate_v1_search_memory_types(
        cls, memory_types: list[str] | None
    ) -> list[str] | None:
        if memory_types is None:
            return None
        unsupported = [
            value
            for value in memory_types
            if value in {"event_log", "foresight"}
            or value not in V1_SEARCH_MEMORY_TYPES
        ]
        if not unsupported:
            return memory_types
        blocked = [
            value
            for value in unsupported
            if value in {"event_log", "foresight"}
        ]
        if blocked:
            joined = ", ".join(blocked)
            raise EverMemosError(
                "Cloud v1 /memories/search does not support memory_types "
                f"[{joined}] (supported: agent_memory, episodic_memory, "
                "profile, raw_message)",
                code="UNSUPPORTED_UPSTREAM",
            )
        joined = ", ".join(unsupported)
        raise EverMemosError(
            f"Unsupported v1 search memory_types: {joined}",
            code="INVALID_INPUT",
        )

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
            if self._use_v0():
                h["X-API-Key"] = self._api_key
        return h

    def _require_key(self) -> None:
        """Require API key for Cloud; loopback base URLs may run without one."""
        if config.is_local_base_url(self._base_url):
            return
        if not self._api_key:
            raise EverMemosError(
                "EVERMEMOS_API_KEY is required for EverMemOS Cloud API",
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
        """Unified HTTP request with network error wrapping."""
        client = await self._get_client()
        method_upper = method.upper()
        get_retries = self._get_retry_count if method_upper == "GET" else 0
        get_retry_attempt = 0
        rate_limit_retry_attempt = 0

        while True:
            try:
                r = await client.request(
                    method_upper,
                    f"{self._api_base}{path}",
                    headers=self._headers(),
                    **kwargs,
                )
            except httpx.TimeoutException as exc:
                if get_retry_attempt < get_retries:
                    await asyncio.sleep(
                        self._get_retry_backoff_seconds * (2**get_retry_attempt)
                    )
                    get_retry_attempt += 1
                    continue
                raise EverMemosError(
                    f"Request timed out: {exc}",
                    code="UPSTREAM_UNAVAILABLE",
                ) from exc
            except httpx.RequestError as exc:
                if get_retry_attempt < get_retries:
                    await asyncio.sleep(
                        self._get_retry_backoff_seconds * (2**get_retry_attempt)
                    )
                    get_retry_attempt += 1
                    continue
                raise EverMemosError(
                    f"Network error: {exc}",
                    code="UPSTREAM_UNAVAILABLE",
                ) from exc

            if r.status_code == 429 and (
                rate_limit_retry_attempt < self._rate_limit_retry_count
            ):
                retry_after = self._parse_retry_after_seconds(
                    r.headers.get("Retry-After")
                )
                sleep_seconds = (
                    retry_after
                    if retry_after is not None
                    else self._rate_limit_backoff_seconds
                    * (2**rate_limit_retry_attempt)
                )
                rate_limit_retry_attempt += 1
                await asyncio.sleep(sleep_seconds)
                continue

            if (
                r.status_code in {500, 502, 503, 504}
                and get_retry_attempt < get_retries
            ):
                await asyncio.sleep(
                    self._get_retry_backoff_seconds * (2**get_retry_attempt)
                )
                get_retry_attempt += 1
                continue
            return await self._handle(r)

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

    @staticmethod
    def _should_retry_delete_with_event_id(error: EverMemosError) -> bool:
        """Whether delete should fallback from memory_id to event_id (v0 only)."""
        if error.status_code not in {400, 422}:
            return False

        msg = str(error).lower()
        if "event_id" in msg:
            return True
        return "memory_id" in msg and "unknown" in msg

    @staticmethod
    def _parse_retry_after_seconds(value: str | None) -> float | None:
        if not isinstance(value, str):
            return None

        raw = value.strip()
        if not raw:
            return None

        try:
            seconds = float(raw)
        except ValueError:
            try:
                retry_at = parsedate_to_datetime(raw)
            except (TypeError, ValueError, OverflowError):
                return None
            if retry_at.tzinfo is None:
                retry_at = retry_at.replace(tzinfo=timezone.utc)
            seconds = (retry_at - datetime.now(timezone.utc)).total_seconds()

        return max(0.0, seconds)

    @staticmethod
    def _normalize_group_ids(
        group_ids: str | Iterable[str] | None,
        *,
        field_name: str = "group_ids",
        allow_none: bool = True,
        max_groups: int = 10,
    ) -> list[str] | None:
        if group_ids is None:
            if allow_none:
                return None
            raise EverMemosError(f"{field_name} is required", code="INVALID_INPUT")

        if isinstance(group_ids, str):
            value = group_ids.strip()
            if not value:
                raise EverMemosError(
                    f"{field_name} must contain non-empty strings",
                    code="INVALID_INPUT",
                )
            return [value]

        if isinstance(group_ids, dict):
            raise EverMemosError(
                f"{field_name} must be a string array",
                code="INVALID_INPUT",
            )

        normalized: list[str] = []
        seen: set[str] = set()
        for item in group_ids:
            if not isinstance(item, str) or not item.strip():
                raise EverMemosError(
                    f"{field_name} must contain non-empty strings",
                    code="INVALID_INPUT",
                )
            value = item.strip()
            if value in seen:
                continue
            seen.add(value)
            normalized.append(value)

        if not normalized:
            raise EverMemosError(
                f"{field_name} must contain at least one group id",
                code="INVALID_INPUT",
            )
        if len(normalized) > max_groups:
            raise EverMemosError(
                f"{field_name} supports at most {max_groups} groups",
                code="INVALID_INPUT",
            )
        return normalized

    @staticmethod
    def _validate_create_time(create_time: str | None) -> str | None:
        if create_time is None:
            return None
        if not isinstance(create_time, str) or not create_time.strip():
            raise EverMemosError(
                "create_time must be an ISO 8601 datetime string",
                code="INVALID_INPUT",
            )

        raw = create_time.strip()
        normalized = raw[:-1] + "+00:00" if raw.endswith(("Z", "z")) else raw
        try:
            parsed = datetime.fromisoformat(normalized)
        except ValueError as exc:
            raise EverMemosError(
                "create_time must be a valid ISO 8601 datetime",
                code="INVALID_INPUT",
            ) from exc

        if parsed.tzinfo is None:
            raise EverMemosError(
                "create_time must include timezone information",
                code="INVALID_INPUT",
            )
        return parsed.isoformat()

    @staticmethod
    def _iso_to_unix_ms(create_time: str | None) -> int:
        if create_time is None:
            return int(datetime.now(timezone.utc).timestamp() * 1000)
        normalized = create_time.strip()
        if normalized.endswith(("Z", "z")):
            normalized = normalized[:-1] + "+00:00"
        parsed = datetime.fromisoformat(normalized)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return int(parsed.timestamp() * 1000)

    @staticmethod
    def _map_v1_search_method(retrieve_method: str) -> str:
        """Map MCP retrieve_method to v1 search ``method`` (keyword/vector/hybrid/agentic)."""
        if retrieve_method in _V1_SEARCH_METHODS:
            return retrieve_method
        # MCP/service expose rrf/auto; v1 Cloud does not — use hybrid.
        return "hybrid"

    @staticmethod
    def _v1_group_field_warnings(
        *,
        scene: object = None,
        scene_desc: object = None,
        tags: object = None,
        llm_custom_setting: object = None,
        user_details: object = None,
        default_timezone: object = None,
        created_at: object = None,
    ) -> list[str]:
        warnings: list[str] = []
        for label, value in (
            ("scene", scene),
            ("scene_desc", scene_desc),
            ("tags", tags),
            ("llm_custom_setting", llm_custom_setting),
            ("user_details", user_details),
            ("default_timezone", default_timezone),
            ("created_at", created_at),
        ):
            if value is not None:
                warnings.append(
                    f"v1 Groups API does not support {label}; field ignored "
                    "(live key verification pending)"
                )
        return warnings

    @staticmethod
    def _normalize_v1_group_response(body: dict, *, group_id: str) -> dict:
        data = EverMemosClient._unwrap_v1_data(body)
        result: dict = {
            "group_id": data.get("group_id", group_id),
            "name": data.get("name", ""),
            "description": data.get("description", ""),
        }
        for field in ("created_at", "updated_at", "conversation_created_at"):
            value = data.get(field)
            if isinstance(value, str) and value.strip():
                result[field] = value.strip()
        return {"status": "ok", "result": result}

    @staticmethod
    def _v1_group_path(group_id: str) -> str:
        return f"/groups/{quote(group_id.strip(), safe='')}"

    def _build_v1_scope_filters(
        self,
        *,
        user_id: str | None,
        group_ids: list[str] | None,
        memory_type: str | None = None,
        start_time: str | None = None,
        end_time: str | None = None,
    ) -> dict:
        if memory_type in _V1_USER_SCOPED_FETCH_MEMORY_TYPES:
            effective_user = user_id or self._user_id
            if group_ids:
                scope = (
                    {"group_id": group_ids[0], "user_id": effective_user}
                    if len(group_ids) == 1
                    else {"group_id": {"in": group_ids}, "user_id": effective_user}
                )
            else:
                scope = {"user_id": effective_user}
        elif group_ids:
            scope = (
                {"group_id": group_ids[0]}
                if len(group_ids) == 1
                else {"group_id": {"in": group_ids}}
            )
        else:
            scope = {"user_id": user_id or self._user_id}

        time_clauses: list[dict] = []
        if start_time:
            time_clauses.append(
                {"timestamp": {"gte": self._iso_to_unix_ms(start_time)}}
            )
        if end_time:
            time_clauses.append({"timestamp": {"lte": self._iso_to_unix_ms(end_time)}})

        if not time_clauses:
            return scope
        if len(time_clauses) == 1:
            return {"AND": [scope, time_clauses[0]]}
        return {"AND": [scope, *time_clauses]}

    @staticmethod
    def _unwrap_v1_data(body: dict) -> dict:
        data = body.get("data")
        return data if isinstance(data, dict) else body

    @staticmethod
    def _normalize_v1_get_response(body: dict, memory_type: str) -> dict:
        data = EverMemosClient._unwrap_v1_data(body)
        key = _V1_GET_RESPONSE_KEYS.get(memory_type, memory_type)
        raw_items = data.get(key, [])
        if not isinstance(raw_items, list):
            raw_items = []

        memories: list[dict] = []
        for item in raw_items:
            if not isinstance(item, dict):
                continue
            row = dict(item)
            row.setdefault("memory_type", memory_type)
            memories.append(row)

        count = data.get("count", len(memories))
        total_count = data.get("total_count", count)
        return {
            "status": "ok",
            "result": {
                "memories": memories,
                "count": count if isinstance(count, int) else len(memories),
                "total_count": (
                    total_count if isinstance(total_count, int) else len(memories)
                ),
            },
        }

    @staticmethod
    def _normalize_v1_search_response(body: dict) -> dict:
        data = EverMemosClient._unwrap_v1_data(body)
        memories: list[dict] = []

        for memory_type, response_key in _V1_SEARCH_RESPONSE_KEYS.items():
            for item in data.get(response_key) or []:
                if isinstance(item, dict):
                    row = dict(item)
                    row.setdefault("memory_type", memory_type)
                    memories.append(row)

        pending = data.get("unprocessed_messages")
        if pending is None:
            pending = data.get("pending_messages")
        if not isinstance(pending, list):
            pending = []

        count = data.get("count", len(memories))
        total_count = data.get("total_count", count)
        return {
            "status": "ok",
            "result": {
                "memories": memories,
                "pending_messages": pending,
                "count": count if isinstance(count, int) else len(memories),
                "total_count": (
                    total_count if isinstance(total_count, int) else len(memories)
                ),
            },
        }

    @staticmethod
    def _normalize_v1_add_response(body: dict, *, message_id: str) -> dict:
        data = EverMemosClient._unwrap_v1_data(body)
        task_id = data.get("task_id", "")
        status = data.get("status", "queued")
        return {
            "status": status if isinstance(status, str) else "queued",
            "request_id": task_id if isinstance(task_id, str) else "",
            "message_id": message_id,
        }

    @staticmethod
    def _normalize_v1_task_response(body: dict, task_id: str) -> dict:
        data = EverMemosClient._unwrap_v1_data(body)
        upstream_status = data.get("status", "")
        status_text = upstream_status if isinstance(upstream_status, str) else ""
        normalized = status_text.lower()
        lifecycle_map = {
            "processing": "queued",
            "queued": "queued",
            "success": "success",
            "failed": "failed",
        }
        mapped_status = lifecycle_map.get(normalized, status_text or "queued")
        message = data.get("message", "")
        if not isinstance(message, str):
            message = ""
        return {
            "success": normalized != "failed",
            "found": bool(task_id or data.get("task_id")),
            "message": message,
            "data": {
                "status": mapped_status,
                "request_id": data.get("task_id") or task_id,
            },
        }

    @staticmethod
    def _normalize_v1_delete_response(body: dict) -> dict:
        data = EverMemosClient._unwrap_v1_data(body)
        count = data.get("count", data.get("deleted_count", 0))
        message = data.get("message", body.get("message", ""))
        if not isinstance(message, str):
            message = ""
        affected = count if isinstance(count, int) else 0
        if affected <= 0 and isinstance(message, str):
            match = re.search(
                r"(\d+)\s+(?:records?\s+affected|memor(?:y|ies))", message
            )
            if match:
                affected = int(match.group(1))
        return {
            "status": "ok",
            "message": message,
            "result": {"count": max(0, affected)},
        }

    async def _request_get_with_json_fallback(self, path: str, payload: dict) -> dict:
        """Prefer GET+JSON body, fallback to POST if intermediaries strip body (v0)."""
        try:
            return await self._request("GET", path, json=payload)
        except EverMemosError as exc:
            hinted = self._maybe_hint_get_body_stripping(exc, payload)
            if hinted is not exc:
                try:
                    return await self._request("POST", path, json=payload)
                except EverMemosError as post_error:
                    post_hinted = self._maybe_hint_get_body_stripping(
                        post_error, payload
                    )
                    if post_hinted is not post_error:
                        raise post_hinted from exc
                    raise post_error from exc
            raise

    # -- public API --

    async def add_message(
        self,
        group_id: str,
        content: str,
        *,
        sender: str | None = None,
        sender_name: str | None = None,
        role: str = "user",
        flush: bool = False,
        message_id: str | None = None,
        create_time: str | None = None,
        group_name: str | None = None,
        refer_list: list[str] | None = None,
    ) -> dict:
        """Write a message to EverMemOS.

        Cloud v0 returns 202 ``{"status": "queued", "request_id": "..."}``.
        Cloud v1 group add returns ``data.task_id`` (mapped to ``request_id``).
        """
        self._require_key()

        normalized_create_time = self._validate_create_time(create_time)
        effective_message_id = message_id or f"msg_{uuid4().hex[:12]}"
        effective_sender = sender or self._user_id

        if self._use_v0():
            payload: dict = {
                "message_id": effective_message_id,
                "create_time": normalized_create_time
                or datetime.now(timezone.utc).isoformat(),
                "sender": effective_sender,
                "sender_name": sender_name or effective_sender,
                "role": role,
                "content": content,
                "group_id": group_id,
                "flush": flush,
            }
            if group_name:
                payload["group_name"] = group_name
            if refer_list is not None:
                if not isinstance(refer_list, list) or not all(
                    isinstance(item, str) and item.strip() for item in refer_list
                ):
                    raise EverMemosError(
                        "refer_list must be an array of non-empty strings",
                        code="INVALID_INPUT",
                    )
                payload["refer_list"] = [item.strip() for item in refer_list]
            return await self._request("POST", "/memories", json=payload)

        v1_message: dict = {
            "role": role,
            "timestamp": self._iso_to_unix_ms(normalized_create_time),
            "content": content,
            "sender_id": effective_sender,
        }
        if sender_name or effective_sender:
            v1_message["sender_name"] = sender_name or effective_sender
        v1_message["message_id"] = effective_message_id

        v1_payload: dict = {
            "group_id": group_id,
            "messages": [v1_message],
            "async_mode": True,
        }
        if group_name:
            v1_payload["group_meta"] = {"name": group_name}

        body = await self._request("POST", "/memories/group", json=v1_payload)
        if flush:
            await self._request(
                "POST",
                "/memories/group/flush",
                json={"group_id": group_id},
            )
        return self._normalize_v1_add_response(body, message_id=effective_message_id)

    async def fetch_memories(
        self,
        group_ids: str | Iterable[str] | None = None,
        *,
        group_id: str | None = None,
        memory_type: str = "episodic_memory",
        user_id: str | None = None,
        limit: int = 40,
        offset: int = 0,
        start_time: str | None = None,
        end_time: str | None = None,
    ) -> dict:
        """Fetch memories by type from a space."""
        self._require_key()

        page_size = max(1, min(limit, 100))
        safe_offset = max(0, offset)
        page = (safe_offset // page_size) + 1

        effective_group_ids = group_ids if group_ids is not None else group_id
        normalized_group_ids = self._normalize_group_ids(
            effective_group_ids,
            max_groups=_FETCH_MAX_GROUP_IDS,
        )

        if self._use_v0():
            self._validate_v0_fetch_memory_type(memory_type)
            payload: dict = {
                "user_id": user_id or self._user_id,
                "memory_type": memory_type,
                "page": page,
                "page_size": page_size,
            }
            if normalized_group_ids is not None:
                payload["group_ids"] = normalized_group_ids
            if start_time:
                payload["start_time"] = start_time
            if end_time:
                payload["end_time"] = end_time
            return await self._request_get_with_json_fallback("/memories", payload)

        self._validate_v1_fetch_memory_type(memory_type)
        v1_payload = {
            "memory_type": memory_type,
            "filters": self._build_v1_scope_filters(
                user_id=user_id,
                group_ids=normalized_group_ids,
                memory_type=memory_type,
                start_time=start_time,
                end_time=end_time,
            ),
            "page": page,
            "page_size": page_size,
        }
        body = await self._request("POST", "/memories/get", json=v1_payload)
        return self._normalize_v1_get_response(body, memory_type)

    async def search_memories(
        self,
        query: str,
        group_ids: str | Iterable[str] | None = None,
        *,
        group_id: str | None = None,
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
        """Search memories in a space."""
        self._require_key()

        effective_group_ids = group_ids if group_ids is not None else group_id
        normalized_group_ids = self._normalize_group_ids(
            effective_group_ids,
            max_groups=_SEARCH_MAX_GROUP_IDS,
        )

        if self._use_v0():
            payload: dict = {
                "query": query,
                "user_id": user_id or self._user_id,
                "retrieve_method": retrieve_method,
                "top_k": top_k,
            }
            if normalized_group_ids is not None:
                payload["group_ids"] = normalized_group_ids
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
            return await self._request_get_with_json_fallback(
                "/memories/search", payload
            )

        v1_memory_types = self._validate_v1_search_memory_types(memory_types)
        v1_payload: dict = {
            "query": query,
            "filters": self._build_v1_scope_filters(
                user_id=user_id,
                group_ids=normalized_group_ids,
                start_time=start_time,
                end_time=end_time,
            ),
            "method": self._map_v1_search_method(retrieve_method),
            "top_k": top_k,
        }
        if v1_memory_types:
            v1_payload["memory_types"] = v1_memory_types
        if radius is not None:
            v1_payload["radius"] = radius
        if include_metadata is not None:
            v1_payload["include_original_data"] = include_metadata
        if current_time:
            v1_payload["current_time"] = self._iso_to_unix_ms(current_time)

        body = await self._request("POST", "/memories/search", json=v1_payload)
        return self._normalize_v1_search_response(body)

    async def get_request_status(self, request_id: str) -> dict:
        """Get async processing status for a queued add-memory request."""
        self._require_key()

        if not isinstance(request_id, str) or not request_id.strip():
            raise EverMemosError("request_id is required", code="INVALID_INPUT")

        task_id = request_id.strip()
        if self._use_v0():
            return await self._request(
                "GET",
                "/status/request",
                params={"request_id": task_id},
            )

        body = await self._request("GET", f"/tasks/{quote(task_id, safe='')}")
        return self._normalize_v1_task_response(body, task_id)

    async def set_conversation_metadata(
        self,
        *,
        group_id: str,
        scene: str | None = None,
        created_at: str,
        name: str | None = None,
        description: str | None = None,
        scene_desc: dict | None = None,
        tags: list[str] | None = None,
        llm_custom_setting: dict | None = None,
        user_details: dict | None = None,
        default_timezone: str | None = None,
    ) -> dict:
        """Create conversation metadata for a group.

        v0: POST /memories/conversation-meta
        v1: POST /groups (name/description only; extra fields returned as warnings)
        """
        self._require_key()

        if self._use_v0():
            payload: dict = {
                "group_id": group_id,
                "created_at": created_at,
            }
            if scene is not None:
                payload["scene"] = scene
            if name is not None:
                payload["name"] = name
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
            return await self._request(
                "POST", "/memories/conversation-meta", json=payload
            )

        warnings = self._v1_group_field_warnings(
            scene=scene,
            scene_desc=scene_desc,
            tags=tags,
            llm_custom_setting=llm_custom_setting,
            user_details=user_details,
            default_timezone=default_timezone,
            created_at=created_at,
        )
        v1_payload: dict = {"group_id": group_id}
        if name is not None:
            v1_payload["name"] = name
        if description is not None:
            v1_payload["description"] = description
        if "name" not in v1_payload and "description" not in v1_payload:
            raise EverMemosError(
                "v1 Groups API create requires at least name or description",
                code="INVALID_INPUT",
            )

        body = await self._request("POST", "/groups", json=v1_payload)
        normalized = self._normalize_v1_group_response(body, group_id=group_id)
        if warnings:
            normalized["warnings"] = warnings
        return normalized

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
        """Patch conversation metadata for a group.

        v0: PATCH /memories/conversation-meta
        v1: PATCH /groups/{group_id} (name/description only)
        """
        self._require_key()

        if self._use_v0():
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
            return await self._request(
                "PATCH", "/memories/conversation-meta", json=payload
            )

        warnings = self._v1_group_field_warnings(
            scene_desc=scene_desc,
            tags=tags,
            llm_custom_setting=llm_custom_setting,
            user_details=user_details,
            default_timezone=default_timezone,
        )
        patch_payload: dict = {}
        if description is not None:
            patch_payload["description"] = description
        if not patch_payload:
            detail = (
                "; ".join(warnings)
                if warnings
                else "v1 Groups API update requires at least name or description"
            )
            raise EverMemosError(detail, code="UNSUPPORTED_UPSTREAM")

        body = await self._request(
            "PATCH",
            self._v1_group_path(group_id),
            json=patch_payload,
        )
        normalized = self._normalize_v1_group_response(body, group_id=group_id)
        if warnings:
            normalized["warnings"] = warnings
        return normalized

    async def get_conversation_metadata(self, group_id: str) -> dict:
        """Get conversation metadata for a group.

        v0: GET /memories/conversation-meta (query params, JSON body fallback)
        v1: GET /groups/{group_id}
        """
        self._require_key()

        if not isinstance(group_id, str) or not group_id.strip():
            raise EverMemosError("group_id is required", code="INVALID_INPUT")

        gid = group_id.strip()
        if self._use_v0():
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

        body = await self._request("GET", self._v1_group_path(gid))
        return self._normalize_v1_group_response(body, group_id=gid)

    async def delete_memories(
        self,
        *,
        memory_id: str | None = None,
        user_id: str | None = None,
        group_id: str | None = None,
    ) -> dict:
        """Soft-delete memories matching the given filters."""
        self._require_key()

        if memory_id is not None:
            if not isinstance(memory_id, str) or not memory_id.strip():
                raise EverMemosError(
                    "memory_id must be a non-empty string when provided",
                    code="INVALID_INPUT",
                )
        if user_id is not None:
            if not isinstance(user_id, str) or not user_id.strip():
                raise EverMemosError(
                    "user_id must be a non-empty string when provided",
                    code="INVALID_INPUT",
                )
        if group_id is not None:
            if not isinstance(group_id, str) or not group_id.strip():
                raise EverMemosError(
                    "group_id must be a non-empty string when provided",
                    code="INVALID_INPUT",
                )

        payload: dict = {}
        if memory_id is not None:
            payload["memory_id"] = memory_id.strip()
        if user_id is not None:
            payload["user_id"] = user_id.strip()
        if group_id is not None:
            payload["group_id"] = group_id.strip()

        if not payload:
            raise EverMemosError(
                "At least one filter (memory_id / user_id / group_id) required for delete",
                code="INVALID_INPUT",
            )

        if not self._use_v0():
            v1_payload: dict = {}
            if memory_id is not None:
                v1_payload["memory_id"] = memory_id.strip()
            elif user_id is not None:
                v1_payload["user_id"] = user_id.strip()
            elif group_id is not None:
                v1_payload["group_id"] = group_id.strip()
            body = await self._request("POST", "/memories/delete", json=v1_payload)
            return self._normalize_v1_delete_response(body)

        try:
            return await self._request("DELETE", "/memories", json=payload)
        except EverMemosError as exc:
            if (
                memory_id is None
                or not self._should_retry_delete_with_event_id(exc)
                or "memory_id" not in payload
            ):
                raise

            fallback_payload = dict(payload)
            fallback_payload["event_id"] = fallback_payload.pop("memory_id")
            return await self._request("DELETE", "/memories", json=fallback_payload)
