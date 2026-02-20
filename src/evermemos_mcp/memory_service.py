"""Business logic layer for memory operations.

Orchestrates between evermemos_client and space_catalog_service.
Each method returns a plain dict that server.py serialises to the MCP client.
"""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, timezone
from uuid import uuid4

from .evermemos_client import EverMemosClient, EverMemosError
from .space_catalog_service import SpaceCatalogService, to_group_id

_VALID_ROLES = {"user", "assistant"}
_VALID_RETRIEVE_METHODS = {"keyword", "hybrid", "vector", "rrf", "agentic", "auto"}
_DEFAULT_RECALL_TOP_K = 10
_MAX_RECALL_TOP_K = 100
_MEMORY_TYPE_ORDER = ("episodic_memory", "profile", "foresight", "event_log")
_FETCH_MEMORY_TYPES = set(_MEMORY_TYPE_ORDER)
_SEARCH_MEMORY_TYPES = ("profile", "episodic_memory")
_VALID_MEMORY_TYPES = set(_SEARCH_MEMORY_TYPES)
_HYBRID_RESTRICTED_METHODS = {"hybrid", "rrf", "agentic"}
_HYBRID_ALLOWED_MEMORY_TYPES = set(_SEARCH_MEMORY_TYPES)
_SPACE_ID_RE = re.compile(r"^[^\s:]+:[^\s:]+$")
_FORGET_DELETE_CONCURRENCY = 8
_MAX_FETCH_HISTORY_LIMIT = 100

logger = logging.getLogger(__name__)


class MemoryService:
    def __init__(self, client: EverMemosClient, catalog: SpaceCatalogService):
        self._client = client
        self._catalog = catalog

    @staticmethod
    def _validate_space_id(space_id: str) -> str:
        if not isinstance(space_id, str) or not space_id.strip():
            raise EverMemosError("space_id is required", code="INVALID_INPUT")
        value = space_id.strip()
        if not _SPACE_ID_RE.match(value):
            raise EverMemosError(
                "space_id must be in <domain>:<slug> format",
                code="INVALID_INPUT",
            )
        return value

    @staticmethod
    def _validate_text(value: str, field_name: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise EverMemosError(
                f"{field_name} must be a non-empty string",
                code="INVALID_INPUT",
            )
        return value.strip()

    @staticmethod
    def _validate_positive_int(value: int, field_name: str) -> int:
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise EverMemosError(
                f"{field_name} must be a positive integer",
                code="INVALID_INPUT",
            )
        return value

    @staticmethod
    def _validate_non_negative_int(value: int, field_name: str) -> int:
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise EverMemosError(
                f"{field_name} must be a non-negative integer",
                code="INVALID_INPUT",
            )
        return value

    @staticmethod
    def _validate_fetch_limit(value: int) -> int:
        limit = MemoryService._validate_positive_int(value, "limit")
        if limit > _MAX_FETCH_HISTORY_LIMIT:
            raise EverMemosError(
                f"limit must be between 1 and {_MAX_FETCH_HISTORY_LIMIT}",
                code="INVALID_INPUT",
            )
        return limit

    @staticmethod
    def _validate_top_k(value: int) -> int:
        if isinstance(value, bool) or not isinstance(value, int):
            raise EverMemosError(
                "top_k must be an integer",
                code="INVALID_INPUT",
            )
        if value == -1:
            return value
        if value <= 0 or value > _MAX_RECALL_TOP_K:
            raise EverMemosError(
                f"top_k must be -1 or between 1 and {_MAX_RECALL_TOP_K}",
                code="INVALID_INPUT",
            )
        return value

    @staticmethod
    def _validate_user_id(value: str | None) -> str | None:
        if value is None:
            return None
        if not isinstance(value, str) or not value.strip():
            raise EverMemosError(
                "user_id must be a non-empty string when provided",
                code="INVALID_INPUT",
            )
        return value.strip()

    @staticmethod
    def _validate_refer_list(refer_list: list[str] | None) -> list[str] | None:
        if refer_list is None:
            return None
        if not isinstance(refer_list, list) or not refer_list:
            raise EverMemosError(
                "refer_list must be a non-empty array when provided",
                code="INVALID_INPUT",
            )

        normalized: list[str] = []
        seen: set[str] = set()
        for item in refer_list:
            if not isinstance(item, str) or not item.strip():
                raise EverMemosError(
                    "refer_list must contain non-empty strings",
                    code="INVALID_INPUT",
                )
            value = item.strip()
            if value in seen:
                continue
            seen.add(value)
            normalized.append(value)
        return normalized

    @staticmethod
    def _validate_iso_datetime(value: str | None, field_name: str) -> str | None:
        if value is None:
            return None
        if not isinstance(value, str) or not value.strip():
            raise EverMemosError(
                f"{field_name} must be an ISO 8601 datetime string",
                code="INVALID_INPUT",
            )

        raw = value.strip()
        normalized = raw
        if raw.endswith("Z") or raw.endswith("z"):
            normalized = f"{raw[:-1]}+00:00"

        try:
            parsed = datetime.fromisoformat(normalized)
        except ValueError as exc:
            raise EverMemosError(
                f"{field_name} must be a valid ISO 8601 datetime",
                code="INVALID_INPUT",
            ) from exc

        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.isoformat()

    @staticmethod
    def _validate_memory_types(memory_types: list[str] | None) -> list[str] | None:
        if memory_types is None:
            return None
        if not isinstance(memory_types, list) or not memory_types:
            raise EverMemosError(
                "memory_types must be a non-empty array when provided",
                code="INVALID_INPUT",
            )

        normalized: list[str] = []
        seen: set[str] = set()
        for item in memory_types:
            if not isinstance(item, str) or not item.strip():
                raise EverMemosError(
                    "memory_types must contain non-empty strings",
                    code="INVALID_INPUT",
                )
            value = item.strip()
            if value not in _VALID_MEMORY_TYPES:
                raise EverMemosError(
                    "memory_types for recall/search only support: profile, episodic_memory",
                    code="INVALID_INPUT",
                )
            if value in seen:
                continue
            seen.add(value)
            normalized.append(value)
        return normalized

    @staticmethod
    def _validate_fetch_memory_type(memory_type: str) -> str:
        if not isinstance(memory_type, str) or not memory_type.strip():
            raise EverMemosError(
                "memory_type is required",
                code="INVALID_INPUT",
            )

        value = memory_type.strip()
        if value not in _FETCH_MEMORY_TYPES:
            raise EverMemosError(
                "memory_type must be one of: profile, episodic_memory, foresight, event_log",
                code="INVALID_INPUT",
            )
        return value

    @staticmethod
    def _validate_radius(radius: float | None) -> float | None:
        if radius is None:
            return None
        if isinstance(radius, bool) or not isinstance(radius, (int, float)):
            raise EverMemosError(
                "radius must be a number between 0 and 1",
                code="INVALID_INPUT",
            )

        value = float(radius)
        if value < 0.0 or value > 1.0:
            raise EverMemosError(
                "radius must be between 0 and 1",
                code="INVALID_INPUT",
            )
        return value

    @staticmethod
    def _validate_time_window(
        start_time: str | None,
        end_time: str | None,
    ) -> tuple[str | None, str | None]:
        if start_time is None or end_time is None:
            # Open-ended windows are allowed. Each endpoint is validated separately
            # by _validate_iso_datetime before this cross-field check.
            return start_time, end_time

        start_dt = datetime.fromisoformat(start_time)
        end_dt = datetime.fromisoformat(end_time)
        if start_dt > end_dt:
            raise EverMemosError(
                "start_time must be earlier than or equal to end_time",
                code="INVALID_INPUT",
            )
        return start_time, end_time

    @staticmethod
    def _is_profile_unsupported_search_error(error: EverMemosError) -> bool:
        if error.status_code not in {400, 422}:
            return False
        message = str(error).lower()
        if "profile" not in message:
            return False

        unsupported_markers = (
            "not supported",
            "unsupported",
            "does not support",
            "doesn't support",
            "only supports",
            "only support",
        )
        return any(marker in message for marker in unsupported_markers)

    @staticmethod
    def _normalize_search_memory_items(
        raw_memories: object,
    ) -> list[tuple[int, dict, float | None]]:
        """Normalize search memories to a flat list.

        Supports both upstream shapes:
        - Flat: [{"id": ..., "memory_type": ...}, ...]
        - Grouped: [{"episodic_memory": [...], "profile": [...]}, ...]
        """

        normalized: list[tuple[int, dict, float | None]] = []
        if not isinstance(raw_memories, list):
            return normalized

        for source_index, entry in enumerate(raw_memories):
            if not isinstance(entry, dict):
                continue

            grouped_items: list[dict] = []
            group_score = entry.get("score")
            if isinstance(group_score, bool) or not isinstance(
                group_score, (int, float)
            ):
                group_score = None

            for memory_type in _MEMORY_TYPE_ORDER:
                items = entry.get(memory_type)
                if not isinstance(items, list):
                    continue
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    item_copy = dict(item)
                    item_copy.setdefault("memory_type", memory_type)
                    grouped_items.append(item_copy)

            # Grouped shape normally has no top-level id/memory_type.
            if grouped_items and "memory_type" not in entry and "id" not in entry:
                for grouped_item in grouped_items:
                    normalized.append((source_index, grouped_item, group_score))
                continue

            normalized.append((source_index, entry, None))

        return normalized

    @staticmethod
    def _extract_source_message_id(item: dict) -> str | None:
        def _pick_string(mapping: object, key: str) -> str | None:
            if not isinstance(mapping, dict):
                return None
            value = mapping.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
            return None

        direct = _pick_string(item, "source_message_id") or _pick_string(
            item, "message_id"
        )
        if direct:
            return direct

        metadata = item.get("metadata")
        metadata_direct = _pick_string(metadata, "source_message_id") or _pick_string(
            metadata, "message_id"
        )
        if metadata_direct:
            return metadata_direct

        parent_type = item.get("parent_type")
        parent_id = _pick_string(item, "parent_id")
        if isinstance(parent_type, str) and parent_id:
            if parent_type.strip().lower() in {"message", "chat_message", "msg"}:
                return parent_id

        meta_parent_type = (
            metadata.get("parent_type") if isinstance(metadata, dict) else None
        )
        meta_parent_id = _pick_string(metadata, "parent_id")
        if isinstance(meta_parent_type, str) and meta_parent_id:
            if meta_parent_type.strip().lower() in {"message", "chat_message", "msg"}:
                return meta_parent_id

        return None

    @staticmethod
    def _extract_memory_text(item: dict) -> str:
        profile_data = item.get("profile_data")
        if isinstance(profile_data, dict):
            profile_text = (
                profile_data.get("summary", "")
                or profile_data.get("description", "")
                or profile_data.get("content", "")
            )
            if isinstance(profile_text, str) and profile_text.strip():
                return profile_text

        atomic_fact = item.get("atomic_fact", "")
        if isinstance(atomic_fact, list):
            atomic_fact = "; ".join(str(v) for v in atomic_fact if v)

        text = (
            item.get("summary", "")
            or item.get("episode", "")
            or item.get("foresight", "")
            or atomic_fact
            or item.get("description", "")
            or item.get("content", "")
            or ""
        )
        return text if isinstance(text, str) else str(text)

    @staticmethod
    def _map_fetch_memory_item_to_row(
        item: dict,
        *,
        memory_type: str,
        include_metadata: bool,
    ) -> dict:
        snippet = MemoryService._extract_memory_text(item)[:800]
        row: dict = {
            "memory_id": item.get("id", ""),
            "memory_type": item.get("memory_type", "") or memory_type,
            "snippet": snippet,
            "content": snippet,
            "timestamp": (
                item.get("timestamp", "")
                or item.get("start_time", "")
                or item.get("created_at", "")
            ),
        }

        source_message_id = MemoryService._extract_source_message_id(item)
        if source_message_id:
            row["source_message_id"] = source_message_id

        if include_metadata and "metadata" in item:
            row["metadata"] = item.get("metadata")

        return row

    @staticmethod
    def _map_search_response_to_results(
        result: dict,
        *,
        include_metadata: bool,
    ) -> tuple[list[dict], list, list, str | None, str | None, int]:
        """Map upstream search response to tool-friendly result rows."""
        res = result.get("result", {})
        if not isinstance(res, dict):
            res = {}

        results: list[dict] = []
        scores = res.get("scores", [])
        if not isinstance(scores, list):
            scores = []

        memory_items = MemoryService._normalize_search_memory_items(
            res.get("memories", [])
        )
        for source_index, item, group_score in memory_items:
            if not isinstance(item, dict):
                continue
            atomic_fact = item.get("atomic_fact", "")
            if isinstance(atomic_fact, list):
                atomic_fact = "; ".join(str(v) for v in atomic_fact if v)

            snippet = (
                item.get("summary", "")
                or atomic_fact
                or item.get("description", "")
                or item.get("content", "")
                or ""
            )
            score = item.get("score")
            if score is None and group_score is not None:
                score = group_score
            if score is None and source_index < len(scores):
                score = scores[source_index]

            snippet_text = snippet[:500]
            row = {
                "memory_id": item.get("id", ""),
                "memory_type": item.get("memory_type", ""),
                "snippet": snippet_text,
                "content": snippet_text,
                "timestamp": item.get("timestamp", "") or item.get("created_at", ""),
                "score": score,
            }
            source_message_id = MemoryService._extract_source_message_id(item)
            if source_message_id:
                row["source_message_id"] = source_message_id
            if include_metadata and "metadata" in item:
                row["metadata"] = item.get("metadata")
            results.append(row)

        for profile in res.get("profiles", []):
            if not isinstance(profile, dict):
                continue
            snippet = profile.get("description", "")
            if not snippet:
                continue
            snippet_text = snippet[:500]
            row = {
                "memory_id": "",
                "memory_type": "profile",
                "snippet": snippet_text,
                "content": snippet_text,
                "timestamp": "",
                "score": profile.get("score"),
            }
            if include_metadata and "metadata" in profile:
                row["metadata"] = profile.get("metadata")
            results.append(row)

        pending = res.get("pending_messages", [])
        pending_count = len(pending) if isinstance(pending, list) else 0
        partial_errors = res.get("partial_errors")
        warnings = res.get("warnings")
        status = result.get("status")
        message = result.get("message")

        return (
            results,
            partial_errors if isinstance(partial_errors, list) else [],
            warnings if isinstance(warnings, list) else [],
            status if isinstance(status, str) else None,
            message if isinstance(message, str) else None,
            pending_count,
        )

    # -- list_spaces --

    async def list_spaces(self, query: str | None = None, limit: int = 20) -> dict:
        limit = self._validate_positive_int(limit, "limit")
        spaces = await self._catalog.list_spaces(query, limit)
        return {
            "ok": True,
            "spaces": [
                {
                    "space_id": s.space_id,
                    "description": s.description,
                    "memory_count": s.memory_count,
                    "last_used_at": s.last_used_at,
                }
                for s in spaces
            ],
            "memory_count_hint": (
                "memory_count is approximate in Cloud mode because extraction is async "
                "and one message can yield zero or multiple memories."
            ),
        }

    # -- remember --

    async def remember(
        self,
        space_id: str,
        content: str,
        *,
        description: str | None = None,
        sender: str | None = "user",
        user_id: str | None = None,
        role: str | None = None,
        flush: bool = False,
        refer_list: list[str] | None = None,
        include_status: bool = False,
    ) -> dict:
        space_id = self._validate_space_id(space_id)
        content = self._validate_text(content, "content")
        if description is not None and not isinstance(description, str):
            raise EverMemosError(
                "description must be a string when provided",
                code="INVALID_INPUT",
            )
        user_id = self._validate_user_id(user_id)
        refer_list = self._validate_refer_list(refer_list)

        normalized_role = (
            role.strip() if isinstance(role, str) and role.strip() else None
        )
        normalized_sender = (
            sender.strip() if isinstance(sender, str) and sender.strip() else None
        )

        if normalized_role is not None and normalized_role not in _VALID_ROLES:
            raise EverMemosError(
                "role must be either 'user' or 'assistant'",
                code="INVALID_INPUT",
            )

        sender_id = user_id or self._client.user_id
        effective_role = normalized_role or "user"

        # Backward compatibility:
        # `sender` used to represent role ('user'/'assistant').
        if normalized_sender in _VALID_ROLES:
            if normalized_role is not None and normalized_role != normalized_sender:
                raise EverMemosError(
                    "role conflicts with sender; use either role or sender role alias",
                    code="INVALID_INPUT",
                )
            effective_role = normalized_sender
        elif normalized_sender is not None:
            # New behavior: sender can carry user_id directly.
            if user_id is not None and normalized_sender != user_id:
                raise EverMemosError(
                    "sender and user_id conflict; provide only one user id",
                    code="INVALID_INPUT",
                )
            sender_id = normalized_sender

        if not isinstance(flush, bool):
            raise EverMemosError(
                "flush must be a boolean",
                code="INVALID_INPUT",
            )
        if not isinstance(include_status, bool):
            raise EverMemosError(
                "include_status must be a boolean",
                code="INVALID_INPUT",
            )

        if description:
            await self._catalog.register_space(
                space_id,
                description.strip(),
                actor_user_id=sender_id,
                actor_role=effective_role,
            )
        else:
            self._catalog.ensure_space(space_id)
            await self._catalog.ensure_conversation_meta(
                space_id,
                actor_user_id=sender_id,
                actor_role=effective_role,
            )

        group_id = to_group_id(space_id)
        created_at = datetime.now(timezone.utc).isoformat()
        submitted_message_id = f"msg_{uuid4().hex[:12]}"

        result = await self._client.add_message(
            group_id=group_id,
            content=content,
            sender=sender_id,
            role=effective_role,
            flush=flush,
            message_id=submitted_message_id,
            create_time=created_at,
            refer_list=refer_list,
        )

        self._catalog.adjust_memory_count(space_id, 1)

        request_id = result.get("request_id", "")
        if not isinstance(request_id, str):
            request_id = ""
        message_id = result.get("message_id", "")
        if isinstance(message_id, str) and message_id.strip():
            message_id = message_id.strip()
        else:
            message_id = submitted_message_id

        output: dict = {
            "ok": True,
            "space_id": space_id,
            "message_id": message_id,
            "request_id": request_id,
            "created_at": created_at,
            "processing_hint": (
                "Memory is queued for extraction. "
                "It may take a few minutes before it becomes searchable."
            ),
            "memory_count_hint": (
                "Space memory_count is approximate in Cloud mode. "
                "A queued message can produce zero or multiple memories."
            ),
        }

        if include_status and request_id:
            try:
                status_res = await self._client.get_request_status(request_id)
                output["request_status"] = {
                    "success": status_res.get("success", False),
                    "found": status_res.get("found", False),
                    "data": status_res.get("data"),
                    "message": status_res.get("message", ""),
                }
            except EverMemosError as exc:
                output["request_status"] = {
                    "success": False,
                    "found": False,
                    "message": str(exc),
                    "error": exc.code,
                }

        return output

    # -- recall --

    async def recall(
        self,
        query: str,
        space_id: str,
        *,
        top_k: int = _DEFAULT_RECALL_TOP_K,
        retrieve_method: str = "hybrid",
        start_time: str | None = None,
        end_time: str | None = None,
        current_time: str | None = None,
        radius: float | None = None,
        include_metadata: bool = False,
        memory_types: list[str] | None = None,
        user_id: str | None = None,
    ) -> dict:
        # Intentionally default to hybrid for better practical recall quality,
        # while upstream API defaults to keyword.
        query = self._validate_text(query, "query")
        space_id = self._validate_space_id(space_id)
        user_id = self._validate_user_id(user_id)
        top_k = self._validate_top_k(top_k)
        start_time = self._validate_iso_datetime(start_time, "start_time")
        end_time = self._validate_iso_datetime(end_time, "end_time")
        start_time, end_time = self._validate_time_window(start_time, end_time)
        current_time = self._validate_iso_datetime(current_time, "current_time")
        radius = self._validate_radius(radius)
        memory_types = self._validate_memory_types(memory_types)
        if not isinstance(include_metadata, bool):
            raise EverMemosError(
                "include_metadata must be a boolean",
                code="INVALID_INPUT",
            )

        if retrieve_method not in _VALID_RETRIEVE_METHODS:
            raise EverMemosError(
                "retrieve_method must be one of: keyword, hybrid, vector, rrf, agentic, auto",
                code="INVALID_INPUT",
            )

        group_id = to_group_id(space_id)
        self._catalog.touch_space(space_id)

        def _normalize_types_for_method(
            method: str,
            types_filter: list[str] | None,
        ) -> list[str] | None:
            if method not in _HYBRID_RESTRICTED_METHODS:
                return types_filter
            if types_filter is None:
                return ["profile", "episodic_memory"]
            disallowed = [
                value
                for value in types_filter
                if value not in _HYBRID_ALLOWED_MEMORY_TYPES
            ]
            if disallowed:
                raise EverMemosError(
                    "For hybrid/rrf/agentic retrieval, memory_types can only include "
                    "profile and episodic_memory",
                    code="INVALID_INPUT",
                )
            return types_filter

        async def _run_single(
            method: str, method_memory_types: list[str] | None
        ) -> dict:
            try:
                return await self._client.search_memories(
                    query,
                    group_id,
                    user_id=user_id,
                    retrieve_method=method,
                    top_k=top_k,
                    memory_types=method_memory_types,
                    start_time=start_time,
                    end_time=end_time,
                    current_time=current_time,
                    radius=radius,
                    include_metadata=include_metadata,
                )
            except EverMemosError as exc:
                has_profile = (
                    bool(method_memory_types) and "profile" in method_memory_types
                )
                has_episodic = bool(method_memory_types) and (
                    "episodic_memory" in method_memory_types
                )
                if (
                    method not in _HYBRID_RESTRICTED_METHODS
                    or not has_profile
                    or not has_episodic
                    or not self._is_profile_unsupported_search_error(exc)
                ):
                    raise

                assert method_memory_types is not None
                fallback_memory_types = [
                    value for value in method_memory_types if value != "profile"
                ]
                fallback = await self._client.search_memories(
                    query,
                    group_id,
                    user_id=user_id,
                    retrieve_method=method,
                    top_k=top_k,
                    memory_types=fallback_memory_types,
                    start_time=start_time,
                    end_time=end_time,
                    current_time=current_time,
                    radius=radius,
                    include_metadata=include_metadata,
                )

                if isinstance(fallback, dict):
                    result_payload = fallback.get("result")
                    if isinstance(result_payload, dict):
                        warning = {
                            "code": "PROFILE_UNSUPPORTED_FALLBACK",
                            "message": (
                                "Upstream search rejected profile memory type for "
                                f"{method}; retried with episodic_memory only."
                            ),
                        }
                        warnings = result_payload.get("warnings")
                        if not isinstance(warnings, list):
                            result_payload["warnings"] = [warning]
                        else:
                            warnings.append(warning)

                return fallback

        if retrieve_method != "auto":
            normalized_types = _normalize_types_for_method(
                retrieve_method, memory_types
            )
            result = await _run_single(retrieve_method, normalized_types)

            rows, partial_errors, warnings, status, message, pending_count = (
                self._map_search_response_to_results(
                    result,
                    include_metadata=include_metadata,
                )
            )

            if top_k != -1:
                rows = rows[:top_k]

            output: dict = {
                "ok": True,
                "space_id": space_id,
                "retrieve_method_actual": retrieve_method,
                "results": rows,
            }
            if pending_count > 0:
                output["pending_count"] = pending_count
                output["pending_hint"] = (
                    f"{pending_count} message(s) are still being processed "
                    "and may contain relevant information."
                )

            has_partial = status == "partial" or bool(partial_errors)
            if has_partial:
                output["partial_hint"] = (
                    "Search returned partial results from upstream."
                )
                if partial_errors:
                    output["partial_errors"] = partial_errors
                elif message:
                    output["partial_errors"] = [{"message": message}]
            if warnings:
                output["warnings"] = warnings
            return output

        can_run_hybrid_branch = memory_types is None or all(
            value in _HYBRID_ALLOWED_MEMORY_TYPES for value in memory_types
        )
        branches: list[tuple[str, list[str] | None]] = []
        if can_run_hybrid_branch:
            branches.append(
                ("hybrid", _normalize_types_for_method("hybrid", memory_types))
            )
        branches.append(("keyword", memory_types))

        branch_results = await asyncio.gather(
            *(
                _run_single(method, branch_memory_types)
                for method, branch_memory_types in branches
            ),
            return_exceptions=True,
        )

        successes: list[tuple[str, dict]] = []
        failures: list[tuple[str, BaseException]] = []
        for (method, _), branch_result in zip(branches, branch_results, strict=True):
            if isinstance(branch_result, BaseException):
                failures.append((method, branch_result))
                continue
            successes.append((method, branch_result))

        if not successes:
            first_error = failures[0][1]
            if isinstance(first_error, EverMemosError):
                raise first_error
            raise EverMemosError(
                f"auto recall failed: {first_error}",
                code="UPSTREAM_UNAVAILABLE",
            )

        merged_rows: list[dict] = []
        seen: set[str] = set()
        pending_count = 0
        warnings: list = []

        for _, success in successes:
            rows, _, branch_warnings, _, _, branch_pending = (
                self._map_search_response_to_results(
                    success,
                    include_metadata=include_metadata,
                )
            )
            pending_count += branch_pending
            warnings.extend(branch_warnings)
            for row in rows:
                dedupe_key = (
                    row.get("memory_id")
                    or f"{row.get('memory_type')}::{row.get('snippet')}"
                )
                if dedupe_key in seen:
                    continue
                seen.add(dedupe_key)
                merged_rows.append(row)

        if top_k != -1:
            merged_rows = merged_rows[:top_k]

        output = {
            "ok": True,
            "space_id": space_id,
            "retrieve_method_actual": "auto(hybrid+keyword)"
            if can_run_hybrid_branch
            else "auto(keyword)",
            "results": merged_rows,
        }
        if pending_count > 0:
            output["pending_count"] = pending_count
            output["pending_hint"] = (
                f"{pending_count} message(s) are still being processed "
                "and may contain relevant information."
            )
        if warnings:
            output["warnings"] = warnings
        if failures:
            output["partial_hint"] = "Search returned partial results from upstream."
            output["partial_errors"] = [
                {"branch": method, "message": str(error)} for method, error in failures
            ]
        return output

    # -- briefing --

    async def briefing(
        self,
        space_id: str,
        *,
        max_items: int = 8,
        start_time: str | None = None,
        end_time: str | None = None,
        user_id: str | None = None,
    ) -> dict:
        space_id = self._validate_space_id(space_id)
        user_id = self._validate_user_id(user_id)
        max_items = self._validate_positive_int(max_items, "max_items")
        start_time = self._validate_iso_datetime(start_time, "start_time")
        end_time = self._validate_iso_datetime(end_time, "end_time")
        start_time, end_time = self._validate_time_window(start_time, end_time)

        group_id = to_group_id(space_id)
        self._catalog.touch_space(space_id)

        profile_res, episodic_res, event_res, foresight_res = await asyncio.gather(
            self._client.fetch_memories(
                group_id, user_id=user_id, memory_type="profile", limit=1
            ),
            self._client.fetch_memories(
                group_id,
                user_id=user_id,
                memory_type="episodic_memory",
                limit=max_items,
                start_time=start_time,
                end_time=end_time,
            ),
            self._client.fetch_memories(
                group_id,
                user_id=user_id,
                memory_type="event_log",
                limit=max_items,
                start_time=start_time,
                end_time=end_time,
            ),
            self._client.fetch_memories(
                group_id,
                user_id=user_id,
                memory_type="foresight",
                limit=max_items,
                start_time=start_time,
                end_time=end_time,
            ),
            return_exceptions=True,
        )

        results = {
            "profile": profile_res,
            "episodic_memory": episodic_res,
            "event_log": event_res,
            "foresight": foresight_res,
        }
        failures = [
            (memory_type, value)
            for memory_type, value in results.items()
            if isinstance(value, BaseException)
        ]

        # All fetches failed — propagate as upstream error
        if len(failures) == len(results):
            first_err = failures[0][1]
            if isinstance(first_err, EverMemosError):
                raise first_err
            raise EverMemosError(
                f"All briefing fetches failed: {first_err}",
                code="UPSTREAM_UNAVAILABLE",
            )

        highlights: list[dict] = []
        summary_parts: list[str] = []

        # Profile
        if isinstance(profile_res, dict):
            profiles_wrapper = profile_res.get("result", {}).get("memories", [])
            for pw in profiles_wrapper[:1]:
                if not isinstance(pw, dict):
                    continue
                text = self._extract_memory_text(pw)
                if not text:
                    data = pw.get("profile_data", {})
                    if isinstance(data, dict):
                        kv_pairs = [
                            f"{k}: {v}"
                            for k, v in data.items()
                            if isinstance(v, (str, int, float, bool))
                        ]
                        text = "; ".join(kv_pairs)
                    elif data is not None:
                        text = str(data)

                if text:
                    highlights.append(
                        {
                            "type": "profile",
                            "content": text[:300],
                            "timestamp": (
                                pw.get("updated_at", "")
                                or pw.get("created_at", "")
                                or pw.get("timestamp", "")
                            ),
                        }
                    )
            if highlights:
                summary_parts.append(f"User profile ({len(highlights)} entries)")

        # Episodic memory
        if isinstance(episodic_res, dict):
            episodes = episodic_res.get("result", {}).get("memories", [])
            for ep in episodes:
                if not isinstance(ep, dict):
                    continue
                summary = ep.get("summary", "")
                if summary:
                    highlight = {
                        "type": "episodic_memory",
                        "content": summary[:300],
                        "timestamp": ep.get("timestamp", ""),
                    }
                    source_message_id = self._extract_source_message_id(ep)
                    if source_message_id:
                        highlight["source_message_id"] = source_message_id
                    highlights.append(highlight)
            if episodes:
                summary_parts.append(f"{len(episodes)} recent episode(s)")

        # Event log (atomic facts)
        if isinstance(event_res, dict):
            events = event_res.get("result", {}).get("memories", [])
            for ev in events:
                if not isinstance(ev, dict):
                    continue
                fact = ev.get("atomic_fact", "")
                if isinstance(fact, list):
                    fact = "; ".join(str(v) for v in fact if v)
                if fact:
                    highlight = {
                        "type": "event_log",
                        "content": fact[:300],
                        "timestamp": ev.get("timestamp", ""),
                    }
                    source_message_id = self._extract_source_message_id(ev)
                    if source_message_id:
                        highlight["source_message_id"] = source_message_id
                    highlights.append(highlight)
            if events:
                summary_parts.append(f"{len(events)} key fact(s)")

        # Foresight
        if isinstance(foresight_res, dict):
            raw_foresights = foresight_res.get("result", {}).get("memories", [])
            foresights = (
                [item for item in raw_foresights if isinstance(item, dict)]
                if isinstance(raw_foresights, list)
                else []
            )

            for fo in foresights:
                text = (
                    fo.get("foresight", "")
                    or fo.get("summary", "")
                    or fo.get("future_event", "")
                    or fo.get("content", "")
                )
                if text:
                    highlight = {
                        "type": "foresight",
                        "content": str(text)[:300],
                        "timestamp": (
                            fo.get("start_time", "")
                            or fo.get("end_time", "")
                            or fo.get("timestamp", "")
                            or fo.get("target_time", "")
                            or fo.get("created_at", "")
                        ),
                    }
                    source_message_id = self._extract_source_message_id(fo)
                    if source_message_id:
                        highlight["source_message_id"] = source_message_id
                    highlights.append(highlight)
            if foresights:
                summary_parts.append(f"{len(foresights)} foresight item(s)")

        output: dict = {
            "ok": True,
            "space_id": space_id,
            "summary": (
                "; ".join(summary_parts)
                if summary_parts
                else "No memories found in this space yet."
            ),
            "highlights": highlights,
        }

        # Partial failure — include warning
        if failures:
            output["partial_hint"] = "Some memory types could not be fetched."
            output["partial_errors"] = [
                {"memory_type": memory_type, "message": str(error)}
                for memory_type, error in failures
            ]

        return output

    # -- fetch_history --

    async def fetch_history(
        self,
        space_id: str,
        *,
        memory_type: str = "episodic_memory",
        limit: int = 50,
        offset: int = 0,
        user_id: str | None = None,
        start_time: str | None = None,
        end_time: str | None = None,
        include_metadata: bool = False,
    ) -> dict:
        space_id = self._validate_space_id(space_id)
        memory_type = self._validate_fetch_memory_type(memory_type)
        limit = self._validate_fetch_limit(limit)
        offset = self._validate_non_negative_int(offset, "offset")
        user_id = self._validate_user_id(user_id)
        start_time = self._validate_iso_datetime(start_time, "start_time")
        end_time = self._validate_iso_datetime(end_time, "end_time")
        start_time, end_time = self._validate_time_window(start_time, end_time)
        if not isinstance(include_metadata, bool):
            raise EverMemosError(
                "include_metadata must be a boolean",
                code="INVALID_INPUT",
            )

        group_id = to_group_id(space_id)
        self._catalog.touch_space(space_id)

        aligned_offset = (offset // limit) * limit
        intra_page_offset = offset - aligned_offset
        target_count = intra_page_offset + limit

        raw_memories: list[dict] = []
        total_count: int | None = None
        reached_end = False
        current_offset = aligned_offset

        while len(raw_memories) < target_count and not reached_end:
            page_result = await self._client.fetch_memories(
                group_id,
                memory_type=memory_type,
                user_id=user_id,
                limit=limit,
                offset=current_offset,
                start_time=start_time,
                end_time=end_time,
            )

            res = page_result.get("result", {}) if isinstance(page_result, dict) else {}
            if not isinstance(res, dict):
                res = {}

            page_memories_raw = res.get("memories", [])
            if not isinstance(page_memories_raw, list):
                page_memories_raw = []
            page_memories = [
                item for item in page_memories_raw if isinstance(item, dict)
            ]
            raw_memories.extend(page_memories)

            page_count = res.get("count")
            if not isinstance(page_count, int) or page_count < 0:
                page_count = len(page_memories)

            page_total_count = res.get("total_count")
            if (
                total_count is None
                and isinstance(page_total_count, int)
                and page_total_count >= 0
            ):
                total_count = page_total_count

            if not page_memories or page_count <= 0:
                reached_end = True
            elif total_count is not None:
                reached_end = current_offset + page_count >= total_count
            else:
                reached_end = page_count < limit

            current_offset += limit

        sliced_memories = raw_memories[intra_page_offset : intra_page_offset + limit]

        rows = [
            self._map_fetch_memory_item_to_row(
                item,
                memory_type=memory_type,
                include_metadata=include_metadata,
            )
            for item in sliced_memories
        ]

        count = len(rows)

        if total_count is not None:
            has_more = offset + count < total_count
        else:
            consumed_end = intra_page_offset + count
            has_buffered_tail = len(raw_memories) > consumed_end
            has_more = has_buffered_tail or (not reached_end and count > 0)

        output: dict = {
            "ok": True,
            "space_id": space_id,
            "memory_type": memory_type,
            "limit": limit,
            "offset": offset,
            "count": count,
            "items": rows,
            "has_more": has_more,
        }
        if total_count is not None:
            output["total_count"] = total_count
        if has_more:
            output["next_offset"] = offset + count

        return output

    # -- forget --

    async def forget(
        self,
        memory_ids: list[str],
        space_id: str,
        *,
        reason: str | None = None,
    ) -> dict:
        space_id = self._validate_space_id(space_id)
        if not isinstance(memory_ids, list) or not memory_ids:
            raise EverMemosError(
                "memory_ids must be a non-empty array",
                code="INVALID_INPUT",
            )
        if reason is not None and not isinstance(reason, str):
            raise EverMemosError(
                "reason must be a string when provided",
                code="INVALID_INPUT",
            )

        unique_ids: list[str] = []
        seen: set[str] = set()
        for raw_id in memory_ids:
            if not isinstance(raw_id, str) or not raw_id.strip():
                raise EverMemosError(
                    "memory_ids must contain non-empty strings",
                    code="INVALID_INPUT",
                )
            mid = raw_id.strip()
            if mid in seen:
                continue
            seen.add(mid)
            unique_ids.append(mid)

        group_id = to_group_id(space_id)
        errors: list[str] = []

        semaphore = asyncio.Semaphore(_FORGET_DELETE_CONCURRENCY)

        async def _delete_one(
            mid: str,
        ) -> tuple[str, int, int, EverMemosError | None]:
            async with semaphore:
                try:
                    result = await self._client.delete_memories(
                        memory_id=mid,
                        group_id=group_id,
                    )
                    count = result.get("result", {}).get("count", 0)
                    if not isinstance(count, int):
                        count = 0
                    upstream_count = max(0, count)
                    logical_deleted = 1 if upstream_count > 0 else 0
                    return mid, upstream_count, logical_deleted, None
                except EverMemosError as e:
                    return mid, 0, 0, e
                except Exception as e:  # pragma: no cover - defensive safeguard
                    return (
                        mid,
                        0,
                        0,
                        EverMemosError(
                            f"unexpected delete error: {e}",
                            code="UPSTREAM_ERROR",
                        ),
                    )

        delete_results = await asyncio.gather(*(_delete_one(mid) for mid in unique_ids))

        deleted = 0
        logical_deleted = 0
        for mid, count, logical_count, err in delete_results:
            deleted += count
            logical_deleted += logical_count
            if err is not None:
                errors.append(f"{mid}: {err}")

        if logical_deleted:
            self._catalog.adjust_memory_count(space_id, -logical_deleted)

        normalized_reason = reason.strip() if isinstance(reason, str) else ""
        if normalized_reason:
            logger.info(
                "forget called with reason in space %s for %d memory ids",
                space_id,
                len(unique_ids),
            )

        output: dict = {
            "ok": len(errors) == 0,
            "space_id": space_id,
            "deleted_count": deleted,
        }
        if normalized_reason:
            output["reason_logged"] = True
        if errors:
            output["errors"] = errors
        return output
