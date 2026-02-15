"""Business logic layer for memory operations.

Orchestrates between evermemos_client and space_catalog_service.
Each method returns a plain dict that server.py serialises to the MCP client.
"""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, timezone

from .evermemos_client import EverMemosClient, EverMemosError
from .space_catalog_service import SpaceCatalogService, to_group_id

_VALID_SENDERS = {"user", "assistant"}
_VALID_RETRIEVE_METHODS = {"keyword", "hybrid", "vector", "rrf", "agentic"}
_DEFAULT_RECALL_TOP_K = 10
_MAX_RECALL_TOP_K = 50
_MEMORY_TYPE_ORDER = ("episodic_memory", "profile", "foresight", "event_log")
_VALID_MEMORY_TYPES = set(_MEMORY_TYPE_ORDER)
_HYBRID_RESTRICTED_METHODS = {"hybrid", "rrf", "agentic"}
_HYBRID_ALLOWED_MEMORY_TYPES = {"profile", "episodic_memory"}
_SPACE_ID_RE = re.compile(r"^[^\s:]+:[^\s:]+$")
_FORGET_DELETE_CONCURRENCY = 8

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
    def _validate_top_k(value: int) -> int:
        value = MemoryService._validate_positive_int(value, "top_k")
        if value > _MAX_RECALL_TOP_K:
            raise EverMemosError(
                f"top_k must be less than or equal to {_MAX_RECALL_TOP_K}",
                code="INVALID_INPUT",
            )
        return value

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
                    "memory_types must be one of: profile, episodic_memory, foresight, event_log",
                    code="INVALID_INPUT",
                )
            if value in seen:
                continue
            seen.add(value)
            normalized.append(value)
        return normalized

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
        sender: str = "user",
        flush: bool = True,
        include_status: bool = False,
    ) -> dict:
        space_id = self._validate_space_id(space_id)
        content = self._validate_text(content, "content")
        if description is not None and not isinstance(description, str):
            raise EverMemosError(
                "description must be a string when provided",
                code="INVALID_INPUT",
            )
        if sender not in _VALID_SENDERS:
            raise EverMemosError(
                "sender must be either 'user' or 'assistant'",
                code="INVALID_INPUT",
            )
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
            await self._catalog.register_space(space_id, description.strip())
        else:
            self._catalog.ensure_space(space_id)

        group_id = to_group_id(space_id)
        role = "assistant" if sender == "assistant" else "user"
        created_at = datetime.now(timezone.utc).isoformat()

        result = await self._client.add_message(
            group_id=group_id,
            content=content,
            sender=sender,
            role=role,
            flush=flush,
            create_time=created_at,
        )

        self._catalog.adjust_memory_count(space_id, 1)

        request_id = result.get("request_id", "")
        if not isinstance(request_id, str):
            request_id = ""
        message_id = result.get("message_id", "")
        if not isinstance(message_id, str):
            message_id = ""
        if not message_id:
            message_id = request_id

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
    ) -> dict:
        query = self._validate_text(query, "query")
        space_id = self._validate_space_id(space_id)
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
                "retrieve_method must be one of: keyword, hybrid, vector, rrf, agentic",
                code="INVALID_INPUT",
            )

        if retrieve_method in _HYBRID_RESTRICTED_METHODS:
            if memory_types is None:
                memory_types = ["profile", "episodic_memory"]
            else:
                disallowed = [
                    value
                    for value in memory_types
                    if value not in _HYBRID_ALLOWED_MEMORY_TYPES
                ]
                if disallowed:
                    raise EverMemosError(
                        "For hybrid/rrf/agentic retrieval, memory_types can only include "
                        "profile and episodic_memory",
                        code="INVALID_INPUT",
                    )

        group_id = to_group_id(space_id)
        self._catalog.touch_space(space_id)

        result = await self._client.search_memories(
            query,
            group_id,
            retrieve_method=retrieve_method,
            top_k=top_k,
            memory_types=memory_types,
            start_time=start_time,
            end_time=end_time,
            current_time=current_time,
            radius=radius,
            include_metadata=include_metadata,
        )
        res = result.get("result", {})

        results = []
        scores = res.get("scores", [])
        if not isinstance(scores, list):
            scores = []

        memory_items = self._normalize_search_memory_items(res.get("memories", []))
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

            results.append(
                {
                    "memory_id": item.get("id", ""),
                    "memory_type": item.get("memory_type", ""),
                    "snippet": snippet[:500],
                    "timestamp": item.get("timestamp", "")
                    or item.get("created_at", ""),
                    "score": score,
                }
            )
            if include_metadata and "metadata" in item:
                results[-1]["metadata"] = item.get("metadata")

        for profile in res.get("profiles", []):
            if not isinstance(profile, dict):
                continue
            snippet = profile.get("description", "")
            if not snippet:
                continue
            results.append(
                {
                    "memory_id": "",
                    "memory_type": "profile",
                    "snippet": snippet[:500],
                    "timestamp": "",
                    "score": profile.get("score"),
                }
            )
            if include_metadata and "metadata" in profile:
                results[-1]["metadata"] = profile.get("metadata")

        output: dict = {
            "ok": True,
            "space_id": space_id,
            "results": results,
        }

        pending = res.get("pending_messages", [])
        if pending:
            output["pending_count"] = len(pending)
            output["pending_hint"] = (
                f"{len(pending)} message(s) are still being processed "
                "and may contain relevant information."
            )

        partial_errors = res.get("partial_errors")
        warnings = res.get("warnings")
        status = result.get("status")
        message = result.get("message")
        has_partial = status == "partial" or bool(partial_errors)

        if has_partial:
            output["partial_hint"] = "Search returned partial results from upstream."
            if isinstance(partial_errors, list) and partial_errors:
                output["partial_errors"] = partial_errors
            elif isinstance(message, str) and message:
                output["partial_errors"] = [{"message": message}]
        if isinstance(warnings, list) and warnings:
            output["warnings"] = warnings

        return output

    # -- briefing --

    async def briefing(
        self,
        space_id: str,
        *,
        max_items: int = 8,
        start_time: str | None = None,
        end_time: str | None = None,
    ) -> dict:
        space_id = self._validate_space_id(space_id)
        max_items = self._validate_positive_int(max_items, "max_items")
        start_time = self._validate_iso_datetime(start_time, "start_time")
        end_time = self._validate_iso_datetime(end_time, "end_time")
        start_time, end_time = self._validate_time_window(start_time, end_time)

        group_id = to_group_id(space_id)
        self._catalog.touch_space(space_id)

        profile_res, episodic_res, event_res, foresight_res = await asyncio.gather(
            self._client.fetch_memories(group_id, memory_type="profile", limit=1),
            self._client.fetch_memories(
                group_id,
                memory_type="episodic_memory",
                limit=max_items,
                start_time=start_time,
                end_time=end_time,
            ),
            self._client.fetch_memories(
                group_id,
                memory_type="event_log",
                limit=max_items,
                start_time=start_time,
                end_time=end_time,
            ),
            self._client.fetch_memories(
                group_id,
                memory_type="foresight",
                limit=max_items,
                # Intentional: briefing time window currently scopes only
                # episodic_memory/event_log, not profile/foresight.
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
                data = pw.get("profile_data", {})
                if isinstance(data, dict):
                    text = (
                        data.get("summary", "")
                        or data.get("description", "")
                        or data.get("content", "")
                    )
                    if not text:
                        kv_pairs = [
                            f"{k}: {v}"
                            for k, v in data.items()
                            if isinstance(v, (str, int, float, bool))
                        ]
                        text = "; ".join(kv_pairs)
                else:
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
                    highlights.append(
                        {
                            "type": "episodic_memory",
                            "content": summary[:300],
                            "timestamp": ep.get("timestamp", ""),
                        }
                    )
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
                    highlights.append(
                        {
                            "type": "event_log",
                            "content": fact[:300],
                            "timestamp": ev.get("timestamp", ""),
                        }
                    )
            if events:
                summary_parts.append(f"{len(events)} key fact(s)")

        # Foresight
        if isinstance(foresight_res, dict):
            foresights = foresight_res.get("result", {}).get("memories", [])
            for fo in foresights:
                if not isinstance(fo, dict):
                    continue

                text = (
                    fo.get("summary", "")
                    or fo.get("future_event", "")
                    or fo.get("content", "")
                )
                if text:
                    highlights.append(
                        {
                            "type": "foresight",
                            "content": str(text)[:300],
                            "timestamp": (
                                fo.get("timestamp", "")
                                or fo.get("target_time", "")
                                or fo.get("created_at", "")
                            ),
                        }
                    )
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

        async def _delete_one(mid: str) -> tuple[str, int, EverMemosError | None]:
            async with semaphore:
                try:
                    result = await self._client.delete_memories(
                        memory_id=mid,
                        group_id=group_id,
                    )
                    count = result.get("result", {}).get("count", 0)
                    if not isinstance(count, int):
                        count = 0
                    return mid, max(0, count), None
                except EverMemosError as e:
                    return mid, 0, e
                except Exception as e:  # pragma: no cover - defensive safeguard
                    return (
                        mid,
                        0,
                        EverMemosError(
                            f"unexpected delete error: {e}",
                            code="UPSTREAM_ERROR",
                        ),
                    )

        delete_results = await asyncio.gather(*(_delete_one(mid) for mid in unique_ids))

        deleted = 0
        for mid, count, err in delete_results:
            deleted += count
            if err is not None:
                errors.append(f"{mid}: {err}")

        if deleted:
            self._catalog.adjust_memory_count(space_id, -deleted)

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
