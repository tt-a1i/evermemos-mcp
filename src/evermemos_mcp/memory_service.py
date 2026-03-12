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

from . import config
from .evermemos_client import EverMemosClient, EverMemosError
from .space_catalog_service import SpaceCatalogService, from_group_id, to_group_id

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
_DELETE_AFFECTED_RE = re.compile(
    r"(\d+)\s+(?:records?\s+affected|memor(?:y|ies))"
)
_FORGET_DELETE_CONCURRENCY = 8
_MAX_FETCH_HISTORY_LIMIT = 100
_SOURCE_RECOVERY_PROBE_TOP_K = config.EVERMEMOS_SOURCE_RECOVERY_PROBE_TOP_K
_SOURCE_RECOVERY_PROBE_CONCURRENCY = config.EVERMEMOS_SOURCE_RECOVERY_PROBE_CONCURRENCY
_CHAT_SPACE_PREFIX = "chat:"
_NAME_EXTRACTION_PATTERNS = (
    re.compile(r"\bmy name is\s+([A-Za-z][A-Za-z0-9'\- ]{0,48})", re.IGNORECASE),
    re.compile(r"\bcall me\s+([A-Za-z][A-Za-z0-9'\- ]{0,48})", re.IGNORECASE),
    re.compile(
        r"(?:我的?名字(?:叫|是)|用户名叫)\s*([A-Za-z\u4e00-\u9fff·•][A-Za-z0-9\u4e00-\u9fff·•'\- ]{0,48})"
    ),
    re.compile(r"我叫\s*([A-Za-z\u4e00-\u9fff·•]{1,20})"),
    re.compile(r"叫我\s*([A-Za-z\u4e00-\u9fff·•]{1,20})"),
)
_PREFERENCE_SENTENCE_MARKERS = (
    "i prefer",
    "i like",
    "i love",
    "my preference",
    "preferences",
    "偏好",
    "喜欢",
    "喜好",
    "习惯",
)
_NAME_QUERY_MARKERS = (
    "my name",
    "what is my name",
    "what's my name",
    "who am i",
    "call me",
    "name?",
    "名字",
    "叫什么",
    "称呼",
)
_PREFERENCE_QUERY_MARKERS = (
    "preference",
    "preferences",
    "prefer",
    "like",
    "settings",
    "style",
    "偏好",
    "喜欢",
    "喜好",
    "风格",
)

logger = logging.getLogger(__name__)


class MemoryService:
    def __init__(self, client: EverMemosClient, catalog: SpaceCatalogService):
        self._client = client
        self._catalog = catalog

    @staticmethod
    def _canonical_lifecycle_state(value: object) -> str | None:
        if not isinstance(value, str) or not value.strip():
            return None

        normalized = value.strip().lower()
        if normalized in {"queued", "pending", "processing", "running", "accepted"}:
            return "queued"
        if normalized in {
            "searchable",
            "success",
            "succeeded",
            "completed",
            "complete",
            "done",
            "processed",
            "ready",
        }:
            return "searchable"
        if normalized in {"provisional", "fallback", "empty"}:
            return normalized
        return None

    @classmethod
    def _build_collection_lifecycle(
        cls,
        *,
        rows: list[dict],
        pending_count: int = 0,
        partial: bool = False,
        empty_message: str,
    ) -> dict:
        counts = {
            "queued": max(pending_count, 0),
            "provisional": 0,
            "fallback": 0,
            "searchable": 0,
        }

        for row in rows:
            state = cls._canonical_lifecycle_state(row.get("stability")) or "searchable"
            if state in counts:
                counts[state] += 1

        if counts["searchable"] > 0:
            primary_state = "searchable"
            if counts["provisional"] > 0 or counts["fallback"] > 0:
                message = (
                    "Searchable memories are available. Some returned items still come from "
                    "provisional or fallback sources."
                )
            else:
                message = (
                    "Searchable memories are available from formal extraction results."
                )
        elif counts["provisional"] > 0:
            primary_state = "provisional"
            message = (
                "No searchable memories were found yet. Showing provisional results from "
                "queued pending messages."
            )
        elif counts["fallback"] > 0:
            primary_state = "fallback"
            message = (
                "No searchable memories were found yet. Showing conversation metadata "
                "fallback instead."
            )
        elif counts["queued"] > 0:
            primary_state = "queued"
            message = (
                "Relevant writes are still queued for extraction, so searchable results are "
                "not available yet."
            )
        else:
            primary_state = "empty"
            message = empty_message

        lifecycle = {
            "state": primary_state,
            "state_counts": counts,
            "searchable": counts["searchable"] > 0,
            "message": message,
        }
        if partial:
            lifecycle["partial"] = True
        return lifecycle

    @classmethod
    def _build_request_status_output(cls, request_id: str, status_res: dict) -> dict:
        success = (
            status_res.get("success", False) if isinstance(status_res, dict) else False
        )
        found = (
            status_res.get("found", False) if isinstance(status_res, dict) else False
        )
        message = status_res.get("message", "") if isinstance(status_res, dict) else ""
        data = status_res.get("data") if isinstance(status_res, dict) else None
        upstream_status = data.get("status") if isinstance(data, dict) else None
        upstream_state = cls._canonical_lifecycle_state(upstream_status)
        lifecycle_state = (
            "searchable"
            if upstream_state == "searchable" and success and found
            else "queued"
        )

        if lifecycle_state == "searchable":
            lifecycle_message = (
                "Upstream reports this write as completed. Recall and briefing should now "
                "prefer searchable memories over provisional or fallback answers."
            )
        elif found is False:
            lifecycle_message = (
                "Upstream has not confirmed a searchable status record for this request yet. "
                "Treat the write as still queued."
            )
        elif success:
            lifecycle_message = (
                "The write has been accepted, but extraction is still queued or not yet "
                "confirmed searchable. Recall and briefing may still rely on provisional or "
                "fallback results."
            )
        else:
            lifecycle_message = (
                "Status check did not confirm whether extraction is searchable yet. Treat the "
                "write as still queued until recall or briefing shows searchable results."
            )

        output: dict = {
            "ok": True,
            "request_id": request_id,
            "success": success,
            "found": found,
            "message": message,
            "lifecycle": {
                "state": lifecycle_state,
                "searchable": lifecycle_state == "searchable",
                "status_check_ok": success,
                "request_found": found,
                "message": lifecycle_message,
                "state_counts": {
                    "queued": 1 if lifecycle_state == "queued" else 0,
                    "provisional": 0,
                    "fallback": 0,
                    "searchable": 1 if lifecycle_state == "searchable" else 0,
                },
            },
        }
        if isinstance(upstream_status, str) and upstream_status:
            output["status"] = upstream_status
            output["lifecycle"]["upstream_status"] = upstream_status
        if data is not None:
            output["data"] = data
        return output

    @classmethod
    def _build_request_status_error_output(
        cls,
        request_id: str,
        *,
        error_message: str,
        error_code: str | None,
    ) -> dict:
        return {
            "ok": True,
            "request_id": request_id,
            "success": False,
            "found": False,
            "message": error_message,
            "error": error_code,
            "lifecycle": {
                "state": "queued",
                "searchable": False,
                "status_check_ok": False,
                "request_found": False,
                "state_counts": {
                    "queued": 1,
                    "provisional": 0,
                    "fallback": 0,
                    "searchable": 0,
                },
                "message": (
                    "Status check failed or is not yet visible upstream. Treat the write as "
                    "queued until recall or briefing returns searchable results."
                ),
            },
        }

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
    def _validate_space_ids(space_ids: list[str] | None) -> list[str] | None:
        if space_ids is None:
            return None
        if not isinstance(space_ids, list) or not space_ids:
            raise EverMemosError(
                "space_ids must be a non-empty array when provided",
                code="INVALID_INPUT",
            )

        normalized: list[str] = []
        seen: set[str] = set()
        for raw_space_id in space_ids:
            sid = MemoryService._validate_space_id(raw_space_id)
            if sid in seen:
                continue
            seen.add(sid)
            normalized.append(sid)
        return normalized

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
    def _pick_non_empty_string(mapping: object, key: str) -> str | None:
        if not isinstance(mapping, dict):
            return None
        value = mapping.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
        return None

    @staticmethod
    def _extract_memory_id(item: dict) -> str:
        direct = MemoryService._pick_non_empty_string(item, "id")
        if direct:
            return direct

        legacy = MemoryService._pick_non_empty_string(item, "memory_id")
        if legacy:
            return legacy

        metadata = item.get("metadata")
        metadata_direct = MemoryService._pick_non_empty_string(metadata, "id")
        if metadata_direct:
            return metadata_direct

        metadata_legacy = MemoryService._pick_non_empty_string(metadata, "memory_id")
        if metadata_legacy:
            return metadata_legacy

        return ""

    @staticmethod
    def _extract_parent_id(item: dict) -> str | None:
        """Extract memcell parent_id — the ID that Cloud DELETE API expects."""
        direct = MemoryService._pick_non_empty_string(item, "parent_id")
        if direct:
            return direct
        metadata = item.get("metadata")
        return MemoryService._pick_non_empty_string(metadata, "parent_id")

    @staticmethod
    def _parse_delete_affected_count(result: dict) -> int:
        """Parse actual affected count from Cloud DELETE response.

        Cloud v0 may return result.count=0 but puts the real count in the
        message string.  Two known formats:
          - "Delete operation completed, 17 records affected"
          - "Successfully deleted 25 memories"
        Falls back to result.count when message parsing fails.
        """
        message = result.get("message", "")
        if isinstance(message, str):
            match = _DELETE_AFFECTED_RE.search(message)
            if match:
                parsed = int(match.group(1))
                if parsed > 0:
                    return parsed
        count = result.get("result", {}).get("count", 0)
        return max(0, count) if isinstance(count, int) else 0

    @staticmethod
    def _pending_message_key(item: object, fallback_index: int) -> str:
        if isinstance(item, dict):
            for key in ("id", "request_id", "message_id", "source_message_id"):
                value = MemoryService._pick_non_empty_string(item, key)
                if value:
                    return f"{key}:{value}"
            content = item.get("content")
            if isinstance(content, str) and content.strip():
                return f"content:{content.strip()}"
            return f"dict:{fallback_index}:{repr(item)}"
        if isinstance(item, str) and item.strip():
            return f"text:{item.strip()}"
        return f"raw:{fallback_index}:{repr(item)}"

    @staticmethod
    def _extract_pending_message_keys(search_result: dict) -> set[str]:
        result_payload = search_result.get("result", {})
        if not isinstance(result_payload, dict):
            return set()

        pending_messages = result_payload.get("pending_messages", [])
        if not isinstance(pending_messages, list):
            return set()

        keys: set[str] = set()
        for index, pending_item in enumerate(pending_messages):
            keys.add(MemoryService._pending_message_key(pending_item, index))
        return keys

    @staticmethod
    def _normalize_note_text(value: str) -> str:
        compact = re.sub(r"\s+", " ", value).strip()
        return compact.strip("\t\n\r ;,，。.!！?？")

    @classmethod
    def _extract_name_from_text(cls, content: str) -> str | None:
        for pattern in _NAME_EXTRACTION_PATTERNS:
            match = pattern.search(content)
            if not match:
                continue
            candidate = cls._normalize_note_text(match.group(1))
            candidate = re.split(
                r"\s+(?:and|who|that|with|but)\b|[，。,.；;]", candidate, 1
            )[0]
            candidate = cls._normalize_note_text(candidate)
            if candidate:
                return candidate
        return None

    @classmethod
    def _extract_preference_items(cls, content: str) -> list[str]:
        normalized = cls._normalize_note_text(content)
        lowered = normalized.lower()
        clauses: list[str] = []
        for marker in _PREFERENCE_SENTENCE_MARKERS:
            if marker not in lowered:
                continue
            start = lowered.find(marker)
            clause = normalized[start + len(marker) :].strip(" :：,-")
            if clause:
                clauses.append(clause)

        items: list[str] = []
        seen: set[str] = set()
        for clause in clauses:
            for raw_item in re.split(r",|，|;|；|\band\b|以及|还有|和", clause):
                item = cls._normalize_note_text(raw_item)
                if not item:
                    continue
                lowered_item = item.lower()
                if lowered_item.startswith("that "):
                    item = cls._normalize_note_text(item[5:])
                    lowered_item = item.lower()
                if lowered_item.startswith("to "):
                    continue
                if lowered_item in seen:
                    continue
                seen.add(lowered_item)
                items.append(item)
        return items

    @classmethod
    def _extract_chat_profile_patch(
        cls,
        *,
        space_id: str,
        content: str,
        role: str,
    ) -> dict | None:
        if not space_id.startswith(_CHAT_SPACE_PREFIX) or role != "user":
            return None

        normalized = cls._normalize_note_text(content)
        if not normalized:
            return None

        patch: dict[str, object] = {}
        full_name = cls._extract_name_from_text(normalized)
        if full_name:
            patch["full_name"] = full_name

        preference_items = cls._extract_preference_items(normalized)
        if preference_items:
            patch["preferences"] = preference_items
            patch["preference_notes"] = [normalized[:240]]
        elif any(
            marker in normalized.lower() for marker in _PREFERENCE_SENTENCE_MARKERS
        ):
            patch["preference_notes"] = [normalized[:240]]

        return patch or None

    @staticmethod
    def _classify_identity_query(query: str) -> tuple[bool, bool]:
        lowered = query.lower()
        asks_name = any(marker in lowered for marker in _NAME_QUERY_MARKERS)
        asks_preferences = any(
            marker in lowered for marker in _PREFERENCE_QUERY_MARKERS
        )
        return asks_name, asks_preferences

    @staticmethod
    def _select_conversation_meta_profile(
        user_details: object,
        *,
        target_user_id: str | None,
    ) -> tuple[str | None, dict | None]:
        if not isinstance(user_details, dict) or not user_details:
            return None, None

        if isinstance(target_user_id, str) and target_user_id.strip():
            normalized_target = target_user_id.strip()
            profile = user_details.get(normalized_target)
            if isinstance(profile, dict):
                return normalized_target, profile

        if len(user_details) == 1:
            only_user_id, only_profile = next(iter(user_details.items()))
            if isinstance(only_user_id, str) and isinstance(only_profile, dict):
                return only_user_id, only_profile

        return None, None

    @classmethod
    def _build_profile_summary_lines(
        cls,
        profile: dict,
        *,
        user_id: str,
        asks_name: bool,
        asks_preferences: bool,
        include_all_when_unspecified: bool = False,
    ) -> list[str]:
        lines: list[str] = []
        full_name = profile.get("full_name")
        if isinstance(full_name, str) and full_name.strip():
            normalized_name = full_name.strip()
            if normalized_name.casefold() != user_id.strip().casefold() and (
                asks_name or include_all_when_unspecified
            ):
                lines.append(f"Known name: {normalized_name}")

        preferences = profile.get("preferences")
        if isinstance(preferences, list):
            preference_text = ", ".join(
                item.strip()
                for item in preferences
                if isinstance(item, str) and item.strip()
            )
            if preference_text and (asks_preferences or include_all_when_unspecified):
                lines.append(f"Known preferences: {preference_text}")

        preference_notes = profile.get("preference_notes")
        if isinstance(preference_notes, list) and (
            asks_preferences or include_all_when_unspecified
        ):
            for note in preference_notes:
                if isinstance(note, str) and note.strip():
                    lines.append(note.strip())

        if not lines and include_all_when_unspecified:
            role = profile.get("role")
            if (
                isinstance(role, str)
                and role.strip()
                and role.strip().casefold() != "user"
            ):
                lines.append(f"Known role for {user_id}: {role.strip()}")

        deduped: list[str] = []
        seen: set[str] = set()
        for line in lines:
            if line in seen:
                continue
            seen.add(line)
            deduped.append(line)
        return deduped

    @classmethod
    def _build_pending_identity_rows(
        cls,
        *,
        query: str,
        search_results: list[dict],
        default_space_id: str | None,
    ) -> list[dict]:
        asks_name, asks_preferences = cls._classify_identity_query(query)
        if not asks_name and not asks_preferences:
            return []
        if not isinstance(default_space_id, str) or not default_space_id.startswith(
            _CHAT_SPACE_PREFIX
        ):
            return []

        rows: list[dict] = []
        seen_texts: set[str] = set()
        for search_result in search_results:
            result_payload = search_result.get("result", {})
            if not isinstance(result_payload, dict):
                continue
            pending_messages = result_payload.get("pending_messages", [])
            if not isinstance(pending_messages, list):
                continue

            for index, pending_item in enumerate(pending_messages):
                if not isinstance(pending_item, dict):
                    continue
                content = pending_item.get("content")
                if not isinstance(content, str) or not content.strip():
                    continue

                patch = cls._extract_chat_profile_patch(
                    space_id=default_space_id,
                    content=content,
                    role="user",
                )
                if not isinstance(patch, dict):
                    continue

                lines = cls._build_profile_summary_lines(
                    patch,
                    user_id="pending-user",
                    asks_name=asks_name,
                    asks_preferences=asks_preferences,
                )
                if not lines:
                    continue

                text = " | ".join(lines)
                if text in seen_texts:
                    continue
                seen_texts.add(text)

                row = {
                    "memory_id": f"pending:{index}:{cls._pending_message_key(pending_item, index)}",
                    "memory_type": "pending_message",
                    "snippet": text[:500],
                    "content": text[:500],
                    "timestamp": pending_item.get("created_at", ""),
                    "source": "pending_messages",
                    "stability": "provisional",
                }
                if isinstance(default_space_id, str) and default_space_id:
                    row["space_id"] = default_space_id
                rows.append(row)
        return rows

    async def _build_conversation_meta_rows(
        self,
        *,
        query: str,
        space_ids: list[str],
        user_id: str | None,
        include_all_when_unspecified: bool = False,
    ) -> list[dict]:
        asks_name, asks_preferences = self._classify_identity_query(query)
        if not asks_name and not asks_preferences and not include_all_when_unspecified:
            return []

        target_user_id = user_id or getattr(self._client, "user_id", None)
        snapshots = await asyncio.gather(
            *(self._catalog.get_conversation_meta(space_id) for space_id in space_ids)
        )

        rows: list[dict] = []
        seen_texts: set[str] = set()
        for space_id, snapshot in zip(space_ids, snapshots, strict=True):
            if not isinstance(snapshot, dict):
                continue
            selected_user_id, profile = self._select_conversation_meta_profile(
                snapshot.get("user_details"),
                target_user_id=target_user_id,
            )
            if not selected_user_id or not isinstance(profile, dict):
                continue

            lines = self._build_profile_summary_lines(
                profile,
                user_id=selected_user_id,
                asks_name=asks_name,
                asks_preferences=asks_preferences,
                include_all_when_unspecified=include_all_when_unspecified,
            )
            if not lines:
                continue

            text = " | ".join(lines)
            if text in seen_texts:
                continue
            seen_texts.add(text)

            rows.append(
                {
                    "memory_id": f"conversation-meta:{space_id}:{selected_user_id}",
                    "memory_type": "metadata_fallback",
                    "snippet": text[:500],
                    "content": text[:500],
                    "timestamp": snapshot.get("created_at", ""),
                    "space_id": space_id,
                    "source": "conversation_meta",
                    "stability": "fallback",
                    "user_id": selected_user_id,
                }
            )
        return rows

    @staticmethod
    def _is_user_scope_compat_error(error: EverMemosError) -> bool:
        if error.status_code not in {400, 404, 422} and error.code not in {
            "INVALID_PARAMETER",
            "INVALID_INPUT",
        }:
            return False

        message = str(error).lower()
        return "user_id" in message or "unknown field" in message

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
        direct = MemoryService._pick_non_empty_string(
            item, "source_message_id"
        ) or MemoryService._pick_non_empty_string(item, "message_id")
        if direct:
            return direct

        metadata = item.get("metadata")
        metadata_direct = MemoryService._pick_non_empty_string(
            metadata, "source_message_id"
        ) or MemoryService._pick_non_empty_string(metadata, "message_id")
        if metadata_direct:
            return metadata_direct

        parent_type = item.get("parent_type")
        parent_id = MemoryService._pick_non_empty_string(item, "parent_id")
        if isinstance(parent_type, str) and parent_id:
            if parent_type.strip().lower() in {"message", "chat_message", "msg"}:
                return parent_id

        meta_parent_type = (
            metadata.get("parent_type") if isinstance(metadata, dict) else None
        )
        meta_parent_id = MemoryService._pick_non_empty_string(metadata, "parent_id")
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
            "memory_id": MemoryService._extract_memory_id(item),
            "memory_type": item.get("memory_type", "") or memory_type,
            "snippet": snippet,
            "content": snippet,
            "timestamp": (
                item.get("timestamp", "")
                or item.get("start_time", "")
                or item.get("created_at", "")
            ),
            "stability": "searchable",
        }

        source_message_id = MemoryService._extract_source_message_id(item)
        if source_message_id:
            row["source_message_id"] = source_message_id
        parent_id = MemoryService._extract_parent_id(item)
        if parent_id:
            row["parent_id"] = parent_id

        if include_metadata and "metadata" in item:
            row["metadata"] = item.get("metadata")

        return row

    @staticmethod
    def _map_search_response_to_results(
        result: dict,
        *,
        include_metadata: bool,
    ) -> tuple[list[dict], list, list, str | None, str | None]:
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
                "memory_id": MemoryService._extract_memory_id(item),
                "memory_type": item.get("memory_type", ""),
                "snippet": snippet_text,
                "content": snippet_text,
                "timestamp": item.get("timestamp", "") or item.get("created_at", ""),
                "score": score,
                "stability": "searchable",
            }
            source_group_id = item.get("group_id")
            if isinstance(source_group_id, str):
                source_space_id = from_group_id(source_group_id.strip())
                if source_space_id:
                    row["space_id"] = source_space_id
            source_message_id = MemoryService._extract_source_message_id(item)
            if source_message_id:
                row["source_message_id"] = source_message_id
            parent_id = MemoryService._extract_parent_id(item)
            if parent_id:
                row["parent_id"] = parent_id
            if include_metadata and "metadata" in item:
                row["metadata"] = item.get("metadata")
            results.append(row)

        for profile in res.get("profiles", []):
            if not isinstance(profile, dict):
                continue
            snippet = MemoryService._extract_memory_text(profile)
            if not snippet:
                continue
            snippet_text = snippet[:500]
            row = {
                "memory_id": MemoryService._extract_memory_id(profile),
                "memory_type": "profile",
                "snippet": snippet_text,
                "content": snippet_text,
                "timestamp": (
                    profile.get("timestamp", "")
                    or profile.get("updated_at", "")
                    or profile.get("created_at", "")
                ),
                "score": profile.get("score"),
                "stability": "searchable",
            }
            source_group_id = profile.get("group_id")
            if isinstance(source_group_id, str):
                source_space_id = from_group_id(source_group_id.strip())
                if source_space_id:
                    row["space_id"] = source_space_id
            source_message_id = MemoryService._extract_source_message_id(profile)
            if source_message_id:
                row["source_message_id"] = source_message_id
            parent_id = MemoryService._extract_parent_id(profile)
            if parent_id:
                row["parent_id"] = parent_id
            if include_metadata and "metadata" in profile:
                row["metadata"] = profile.get("metadata")
            results.append(row)

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
        )

    # -- list_spaces --

    async def list_spaces(self, query: str | None = None, limit: int = 20) -> dict:
        limit = self._validate_positive_int(limit, "limit")
        spaces = await self._catalog.list_spaces(query, limit)
        output = {
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
        warning = self._catalog.get_recovery_warning()
        if warning is not None:
            output["warnings"] = [warning]
        return output

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
        allow_sensitive: bool = False,
        check_conflicts: bool | None = None,
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

        # -- sensitive content guard --
        if not allow_sensitive:
            from .content_guard import scan_sensitive_content

            sensitive_matches = scan_sensitive_content(content)
            if sensitive_matches:
                return {
                    "ok": False,
                    "blocked_reason": "sensitive_content_detected",
                    "sensitive_matches": [
                        {
                            "category": m.category,
                            "description": m.description,
                            "matched_text": (
                                m.matched_text[:20] + "..."
                                if len(m.matched_text) > 20
                                else m.matched_text
                            ),
                        }
                        for m in sensitive_matches
                    ],
                    "hint": (
                        "Sensitive content detected (API keys, passwords, tokens). "
                        "Ask the user whether to proceed. "
                        "If confirmed, retry with allow_sensitive=true."
                    ),
                }

        # -- conflict detection --
        # Skip conflict check when sensitive content is being force-stored:
        # the search query would leak sensitive text to the search API.
        should_check_conflicts = check_conflicts
        if allow_sensitive and should_check_conflicts is None:
            should_check_conflicts = False
        if should_check_conflicts is None:
            should_check_conflicts = space_id.startswith(_CHAT_SPACE_PREFIX)

        conflict_items: list[dict] | None = None
        conflict_warning: dict | None = None
        if should_check_conflicts:
            try:
                query_text = content[:200].strip()
                conflict_search = await self._client.search_memories(
                    group_id=to_group_id(space_id),
                    query=query_text,
                    top_k=5,
                    retrieve_method="hybrid",
                )
                raw_memories = conflict_search.get("result", {}).get(
                    "memories", []
                )
                if isinstance(raw_memories, list):
                    conflict_items = []
                    for item in raw_memories:
                        if not isinstance(item, dict):
                            continue
                        mid = self._extract_memory_id(item)
                        if not mid:
                            continue
                        snippet = self._extract_memory_text(item)
                        ts = (
                            item.get("timestamp", "")
                            or item.get("start_time", "")
                            or item.get("created_at", "")
                        )
                        conflict_items.append(
                            {
                                "memory_id": mid,
                                "memory_type": item.get("memory_type", ""),
                                "snippet": snippet[:200] if snippet else "",
                                "score": item.get("score"),
                                "timestamp": ts,
                            }
                        )
                    if not conflict_items:
                        conflict_items = None
            except Exception as exc:
                logger.warning("Conflict check failed: %s", exc)
                conflict_warning = {
                    "code": "CONFLICT_CHECK_FAILED",
                    "message": f"Could not check for conflicting memories: {exc}",
                }

        actor_profile = self._extract_chat_profile_patch(
            space_id=space_id,
            content=content,
            role=effective_role,
        )

        if description:
            await self._catalog.register_space(
                space_id,
                description.strip(),
                actor_user_id=sender_id,
                actor_role=effective_role,
                actor_profile=actor_profile,
            )
        else:
            self._catalog.ensure_space(space_id)
            await self._catalog.ensure_conversation_meta(
                space_id,
                actor_user_id=sender_id,
                actor_role=effective_role,
                actor_profile=actor_profile,
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
                "Memory write accepted and queued for AI extraction. "
                "Extraction timing depends on EverMemOS Cloud queue progress. "
                "Use request_status, recall, or briefing to distinguish queued, "
                "provisional, fallback, and searchable states. "
                "Tip: use flush=true at session end to finalize extraction."
            ),
            "memory_count_hint": (
                "Space memory_count is approximate in Cloud mode. "
                "A queued message can produce zero or multiple memories."
            ),
            "lifecycle": {
                "state": "queued",
                "searchable": False,
                "state_counts": {
                    "queued": 1,
                    "provisional": 0,
                    "fallback": 0,
                    "searchable": 0,
                },
                "message": (
                    "The write was accepted and queued. Until extraction completes, recall "
                    "or briefing may only surface provisional or fallback answers."
                ),
            },
        }

        if request_id:
            output["status_check"] = {
                "recommended": True,
                "tool": "request_status",
                "request_id": request_id,
                "checked_now": False,
                "message": (
                    "Recommended write-after check: call request_status with this "
                    "request_id before assuming the write is searchable. For future "
                    "writes, prefer remember(include_status=true)."
                ),
            }

        if actor_profile:
            output["metadata_mirror"] = {
                "enabled": True,
                "message": (
                    "Detected chat identity/preferences and mirrored them into conversation "
                    "metadata so recall or briefing can expose a fallback while searchable "
                    "memories are not ready yet."
                ),
            }

        if include_status and request_id:
            try:
                status_res = await self._client.get_request_status(request_id)
                remember_status = self._build_request_status_output(
                    request_id, status_res
                )
                output["request_status"] = remember_status
                status_check = output.get("status_check")
                if isinstance(status_check, dict):
                    status_check["checked_now"] = True
                    status_check["message"] = (
                        "Write-after check completed once. Check request_status.success "
                        "and request_status.error before interpreting lifecycle.state. "
                        "If lifecycle.state remains queued without an error, keep using "
                        "request_status with this request_id until upstream confirms "
                        "searchable completion."
                    )
            except EverMemosError as exc:
                remember_status = self._build_request_status_error_output(
                    request_id,
                    error_message=str(exc),
                    error_code=exc.code,
                )
                output["request_status"] = remember_status
                status_check = output.get("status_check")
                if isinstance(status_check, dict):
                    status_check["checked_now"] = True
                    status_check["message"] = (
                        "Write-after check attempted once but upstream status was not "
                        "confirmed. Inspect request_status.success / request_status.error, "
                        "then keep the request_id and retry request_status later."
                    )

        if conflict_items:
            output["conflicts"] = {
                "found": len(conflict_items),
                "items": conflict_items,
                "hint": (
                    "Similar memories already exist in this space. "
                    "If these represent outdated information, use forget to remove "
                    "them. The new memory has been stored regardless."
                ),
            }

        if conflict_warning is not None:
            output.setdefault("warnings", []).append(conflict_warning)

        return output

    # -- recall --

    async def request_status(self, request_id: str) -> dict:
        if not isinstance(request_id, str) or not request_id.strip():
            raise EverMemosError("request_id is required", code="INVALID_INPUT")

        normalized_request_id = request_id.strip()
        try:
            status_res = await self._client.get_request_status(normalized_request_id)
        except EverMemosError as exc:
            return self._build_request_status_error_output(
                normalized_request_id,
                error_message=str(exc),
                error_code=exc.code,
            )
        return self._build_request_status_output(normalized_request_id, status_res)

    async def recall(
        self,
        query: str,
        space_id: str | None = None,
        *,
        space_ids: list[str] | None = None,
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
        normalized_space_id = (
            self._validate_space_id(space_id) if space_id is not None else None
        )
        normalized_space_ids = self._validate_space_ids(space_ids)

        resolved_space_ids: list[str] = []
        seen_space_ids: set[str] = set()
        if normalized_space_id is not None:
            resolved_space_ids.append(normalized_space_id)
            seen_space_ids.add(normalized_space_id)
        if normalized_space_ids:
            for sid in normalized_space_ids:
                if sid in seen_space_ids:
                    continue
                seen_space_ids.add(sid)
                resolved_space_ids.append(sid)

        if not resolved_space_ids:
            raise EverMemosError(
                "Either space_id or space_ids is required",
                code="INVALID_INPUT",
            )
        if len(resolved_space_ids) > 10:
            raise EverMemosError(
                "At most 10 unique spaces are allowed in recall",
                code="INVALID_INPUT",
            )

        user_id = self._validate_user_id(user_id)
        top_k = self._validate_top_k(top_k)
        request_top_k = _MAX_RECALL_TOP_K if top_k == -1 else top_k
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

        search_group_ids = [to_group_id(sid) for sid in resolved_space_ids]
        search_scope: str | list[str] = (
            search_group_ids[0] if len(search_group_ids) == 1 else search_group_ids
        )
        for sid in resolved_space_ids:
            self._catalog.touch_space(sid)

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

        def _row_lookup_key(row: dict) -> str | None:
            memory_id = row.get("memory_id")
            if isinstance(memory_id, str) and memory_id:
                return f"id:{memory_id}"

            source_message_id = row.get("source_message_id")
            if isinstance(source_message_id, str) and source_message_id.strip():
                return f"msg:{source_message_id.strip()}"

            memory_type = row.get("memory_type")
            normalized_type = (
                memory_type.strip()
                if isinstance(memory_type, str) and memory_type.strip()
                else "unknown"
            )
            timestamp = row.get("timestamp")
            snippet = row.get("snippet")
            if isinstance(snippet, str) and snippet.strip():
                normalized_snippet = snippet.strip()
                if isinstance(timestamp, str) and timestamp.strip():
                    return (
                        f"{normalized_type}::{timestamp.strip()}::{normalized_snippet}"
                    )
                return f"{normalized_type}::{normalized_snippet}"
            return None

        def _row_merge_key(row: dict) -> str:
            base_key = _row_lookup_key(row)
            if base_key is None:
                return repr(row)

            source_space_id = row.get("space_id")
            if isinstance(source_space_id, str) and source_space_id:
                return f"{source_space_id}::{base_key}"
            return base_key

        recovered_candidate_spaces: dict[str, set[str]] = {}
        completed_probe_signatures: set[tuple[str, tuple[str, ...] | None]] = set()
        probed_row_keys: set[str] = set()

        async def _run_single(
            method: str,
            method_memory_types: list[str] | None,
            *,
            scope: str | list[str] | None = None,
            top_k_override: int | None = None,
            include_metadata_override: bool | None = None,
        ) -> dict:
            effective_scope = search_scope if scope is None else scope
            effective_top_k = (
                request_top_k if top_k_override is None else top_k_override
            )
            effective_include_metadata = (
                include_metadata
                if include_metadata_override is None
                else include_metadata_override
            )
            try:
                return await self._client.search_memories(
                    query,
                    effective_scope,
                    user_id=user_id,
                    retrieve_method=method,
                    top_k=effective_top_k,
                    memory_types=method_memory_types,
                    start_time=start_time,
                    end_time=end_time,
                    current_time=current_time,
                    radius=radius,
                    include_metadata=effective_include_metadata,
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
                    effective_scope,
                    user_id=user_id,
                    retrieve_method=method,
                    top_k=effective_top_k,
                    memory_types=fallback_memory_types,
                    start_time=start_time,
                    end_time=end_time,
                    current_time=current_time,
                    radius=radius,
                    include_metadata=effective_include_metadata,
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

        async def _recover_missing_space_ids(
            rows: list[dict],
            *,
            method: str,
            method_memory_types: list[str] | None,
        ) -> list[dict]:
            if not rows:
                return []

            if len(resolved_space_ids) == 1:
                default_space_id = resolved_space_ids[0]
                for row in rows:
                    source_space_id = row.get("space_id")
                    if not isinstance(source_space_id, str) or not source_space_id:
                        row["space_id"] = default_space_id
                return []

            for row in rows:
                row_key = _row_lookup_key(row)
                source_space_id = row.get("space_id")
                if (
                    row_key is not None
                    and isinstance(source_space_id, str)
                    and source_space_id
                ):
                    recovered_candidate_spaces.setdefault(row_key, set()).add(
                        source_space_id
                    )

            missing_rows = [
                row
                for row in rows
                if not isinstance(row.get("space_id"), str) or not row.get("space_id")
            ]
            if not missing_rows:
                return []

            def _apply_cached_source_space(target_rows: list[dict]) -> int:
                unresolved = 0
                for row in target_rows:
                    row_key = _row_lookup_key(row)
                    if row_key is None:
                        unresolved += 1
                        continue

                    candidate_spaces = recovered_candidate_spaces.get(row_key, set())
                    if len(candidate_spaces) == 1:
                        row["space_id"] = next(iter(candidate_spaces))
                    else:
                        unresolved += 1
                return unresolved

            unresolved_count = _apply_cached_source_space(missing_rows)
            if unresolved_count == 0:
                return []

            unresolved_probe_keys = {
                row_key
                for row in missing_rows
                if (row_key := _row_lookup_key(row)) is not None
                and len(recovered_candidate_spaces.get(row_key, set())) != 1
            }
            has_new_probe_keys = bool(unresolved_probe_keys - probed_row_keys)

            probe_signature = (
                method,
                tuple(method_memory_types) if method_memory_types is not None else None,
            )

            probe_errors: list[dict] = []
            if probe_signature not in completed_probe_signatures and has_new_probe_keys:
                completed_probe_signatures.add(probe_signature)
                probed_row_keys.update(unresolved_probe_keys)

                probe_semaphore = asyncio.Semaphore(
                    min(len(resolved_space_ids), _SOURCE_RECOVERY_PROBE_CONCURRENCY)
                )

                async def _probe_one_space(
                    sid: str,
                ) -> tuple[str, list[dict] | None, str | None]:
                    async with probe_semaphore:
                        try:
                            scoped_result = await _run_single(
                                method,
                                method_memory_types,
                                scope=to_group_id(sid),
                                top_k_override=_SOURCE_RECOVERY_PROBE_TOP_K,
                                include_metadata_override=False,
                            )
                        except EverMemosError as exc:
                            return sid, None, str(exc)

                    scoped_rows, _, _, _, _ = self._map_search_response_to_results(
                        scoped_result,
                        include_metadata=False,
                    )
                    return sid, scoped_rows, None

                probe_results = await asyncio.gather(
                    *(_probe_one_space(sid) for sid in resolved_space_ids)
                )

                for sid, scoped_rows, error_message in probe_results:
                    if error_message is not None:
                        probe_errors.append({"space_id": sid, "message": error_message})
                        continue

                    if scoped_rows is None:
                        continue
                    for scoped_row in scoped_rows:
                        scoped_space_id = scoped_row.get("space_id")
                        if not isinstance(scoped_space_id, str) or not scoped_space_id:
                            scoped_space_id = sid

                        row_key = _row_lookup_key(scoped_row)
                        if row_key is None:
                            continue

                        recovered_candidate_spaces.setdefault(row_key, set()).add(
                            scoped_space_id
                        )

            unresolved_count = _apply_cached_source_space(missing_rows)

            recovery_warnings: list[dict] = []
            if unresolved_count > 0:
                recovery_warnings.append(
                    {
                        "code": "SOURCE_SPACE_UNRESOLVED",
                        "message": (
                            f"{unresolved_count} result(s) have no source space because "
                            "upstream search response omitted group_id."
                        ),
                    }
                )
            if probe_errors:
                recovery_warnings.append(
                    {
                        "code": "SOURCE_SPACE_RECOVERY_PARTIAL",
                        "message": "Failed to probe some spaces while recovering source labels.",
                        "details": probe_errors,
                    }
                )

            return recovery_warnings

        if retrieve_method != "auto":
            normalized_types = _normalize_types_for_method(
                retrieve_method, memory_types
            )
            result = await _run_single(retrieve_method, normalized_types)

            rows, partial_errors, warnings, status, message = (
                self._map_search_response_to_results(
                    result,
                    include_metadata=include_metadata,
                )
            )
            pending_count = len(self._extract_pending_message_keys(result))
            warnings = list(warnings)
            warnings.extend(
                await _recover_missing_space_ids(
                    rows,
                    method=retrieve_method,
                    method_memory_types=normalized_types,
                )
            )

            if not rows:
                fallback_rows = self._build_pending_identity_rows(
                    query=query,
                    search_results=[result],
                    default_space_id=resolved_space_ids[0]
                    if len(resolved_space_ids) == 1
                    else None,
                )
                fallback_rows.extend(
                    await self._build_conversation_meta_rows(
                        query=query,
                        space_ids=resolved_space_ids,
                        user_id=user_id,
                    )
                )
                if fallback_rows:
                    rows = fallback_rows
                    warnings.append(
                        {
                            "code": "IDENTITY_FALLBACK_APPLIED",
                            "message": (
                                "Search returned no searchable memories; surfaced provisional "
                                "pending-message or conversation-metadata fallback results instead."
                            ),
                        }
                    )

            if top_k != -1:
                rows = rows[:top_k]

            output: dict = {
                "ok": True,
                "space_ids": resolved_space_ids,
                "retrieve_method_actual": retrieve_method,
                "results": rows,
            }
            if len(resolved_space_ids) == 1:
                output["space_id"] = resolved_space_ids[0]
            if pending_count > 0:
                output["pending_count"] = pending_count
                output["pending_hint"] = (
                    f"{pending_count} message(s) are still queued for extraction and may later "
                    "produce searchable memories."
                )

            has_partial = status == "partial" or bool(partial_errors)
            if has_partial:
                output["partial_hint"] = (
                    "Search returned partial results from upstream, so lifecycle counts may be incomplete."
                )
                if partial_errors:
                    output["partial_errors"] = partial_errors
                elif message:
                    output["partial_errors"] = [{"message": message}]
            if warnings:
                output["warnings"] = warnings
            output["lifecycle"] = self._build_collection_lifecycle(
                rows=rows,
                pending_count=pending_count,
                partial=has_partial,
                empty_message="No matching memories were found in the current search scope.",
            )
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

        successes: list[tuple[str, list[str] | None, dict]] = []
        failures: list[tuple[str, BaseException]] = []
        for (method, branch_memory_types), branch_result in zip(
            branches, branch_results, strict=True
        ):
            if isinstance(branch_result, BaseException):
                failures.append((method, branch_result))
                continue
            successes.append((method, branch_memory_types, branch_result))

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
        pending_keys: set[str] = set()
        warnings: list = []

        for method, branch_memory_types, success in successes:
            rows, _, branch_warnings, _, _ = self._map_search_response_to_results(
                success,
                include_metadata=include_metadata,
            )
            pending_keys.update(self._extract_pending_message_keys(success))
            warnings.extend(branch_warnings)
            warnings.extend(
                await _recover_missing_space_ids(
                    rows,
                    method=method,
                    method_memory_types=branch_memory_types,
                )
            )
            for row in rows:
                dedupe_key = _row_merge_key(row)
                if dedupe_key in seen:
                    continue
                seen.add(dedupe_key)
                merged_rows.append(row)

        if top_k != -1:
            merged_rows = merged_rows[:top_k]

        pending_count = len(pending_keys)

        if not merged_rows:
            fallback_rows = self._build_pending_identity_rows(
                query=query,
                search_results=[success for _, _, success in successes],
                default_space_id=resolved_space_ids[0]
                if len(resolved_space_ids) == 1
                else None,
            )
            fallback_rows.extend(
                await self._build_conversation_meta_rows(
                    query=query,
                    space_ids=resolved_space_ids,
                    user_id=user_id,
                )
            )
            if fallback_rows:
                merged_rows = fallback_rows[:top_k] if top_k != -1 else fallback_rows
                warnings.append(
                    {
                        "code": "IDENTITY_FALLBACK_APPLIED",
                        "message": (
                            "Auto recall returned no searchable memories; surfaced provisional "
                            "pending-message or conversation-metadata fallback results instead."
                        ),
                    }
                )

        output = {
            "ok": True,
            "space_ids": resolved_space_ids,
            "retrieve_method_actual": "auto(hybrid+keyword)"
            if can_run_hybrid_branch
            else "auto(keyword)",
            "results": merged_rows,
        }
        if len(resolved_space_ids) == 1:
            output["space_id"] = resolved_space_ids[0]
        if pending_count > 0:
            output["pending_count"] = pending_count
            output["pending_hint"] = (
                f"{pending_count} message(s) are still queued for extraction and may later "
                "produce searchable memories."
            )
        if warnings:
            output["warnings"] = warnings
        if failures:
            output["partial_hint"] = (
                "Search returned partial results from upstream, so lifecycle counts may be incomplete."
            )
            output["partial_errors"] = [
                {"branch": method, "message": str(error)} for method, error in failures
            ]
        output["lifecycle"] = self._build_collection_lifecycle(
            rows=merged_rows,
            pending_count=pending_count,
            partial=bool(failures),
            empty_message="No matching memories were found in the current search scope.",
        )
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

        profile_limit = 1 if user_id is not None else max_items

        profile_res, episodic_res, event_res, foresight_res = await asyncio.gather(
            self._client.fetch_memories(
                group_id,
                user_id=user_id,
                memory_type="profile",
                limit=profile_limit,
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
        profile_highlight_count = 0

        # Profile
        if isinstance(profile_res, dict):
            profiles_wrapper = profile_res.get("result", {}).get("memories", [])
            for pw in profiles_wrapper[:profile_limit]:
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
                    snippet_text = text[:300]
                    highlights.append(
                        {
                            "type": "profile",
                            "snippet": snippet_text,
                            "content": snippet_text,
                            "timestamp": (
                                pw.get("updated_at", "")
                                or pw.get("created_at", "")
                                or pw.get("timestamp", "")
                            ),
                            "stability": "searchable",
                        }
                    )
                    profile_highlight_count += 1
            if highlights:
                summary_parts.append(
                    f"User profile ({profile_highlight_count} entries)"
                )

        # Episodic memory
        if isinstance(episodic_res, dict):
            episodes = episodic_res.get("result", {}).get("memories", [])
            for ep in episodes:
                if not isinstance(ep, dict):
                    continue
                text = self._extract_memory_text(ep)
                if text:
                    snippet_text = text[:300]
                    highlight = {
                        "type": "episodic_memory",
                        "snippet": snippet_text,
                        "content": snippet_text,
                        "timestamp": ep.get("timestamp", ""),
                        "stability": "searchable",
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
                    snippet_text = fact[:300]
                    highlight = {
                        "type": "event_log",
                        "snippet": snippet_text,
                        "content": snippet_text,
                        "timestamp": ev.get("timestamp", ""),
                        "stability": "searchable",
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
                    snippet_text = str(text)[:300]
                    highlight = {
                        "type": "foresight",
                        "snippet": snippet_text,
                        "content": snippet_text,
                        "timestamp": (
                            fo.get("start_time", "")
                            or fo.get("end_time", "")
                            or fo.get("timestamp", "")
                            or fo.get("target_time", "")
                            or fo.get("created_at", "")
                        ),
                        "stability": "searchable",
                    }
                    source_message_id = self._extract_source_message_id(fo)
                    if source_message_id:
                        highlight["source_message_id"] = source_message_id
                    highlights.append(highlight)
            if foresights:
                summary_parts.append(f"{len(foresights)} foresight item(s)")

        if profile_highlight_count == 0:
            metadata_rows = await self._build_conversation_meta_rows(
                query="profile briefing",
                space_ids=[space_id],
                user_id=user_id,
                include_all_when_unspecified=True,
            )
            if metadata_rows:
                for row in metadata_rows[:1]:
                    highlights.insert(
                        0,
                        {
                            "type": "metadata_fallback",
                            "snippet": row["snippet"],
                            "content": row["content"],
                            "timestamp": row.get("timestamp", ""),
                            "source": row.get("source", "conversation_meta"),
                            "stability": row.get("stability", "fallback"),
                            "user_id": row.get("user_id"),
                        },
                    )
                summary_parts.insert(
                    0,
                    "Conversation metadata fallback (1 entry; not formally extracted)",
                )

        output: dict = {
            "ok": True,
            "space_id": space_id,
            "summary": (
                "; ".join(summary_parts)
                if summary_parts
                else "No memories found in this space yet."
            ),
            "highlights": highlights,
            "lifecycle": self._build_collection_lifecycle(
                rows=highlights,
                empty_message="No searchable or fallback memories were found in this space yet.",
            ),
        }

        # Partial failure — include warning
        if failures:
            output["partial_hint"] = (
                "Some memory types could not be fetched, so lifecycle counts may be incomplete."
            )
            output["partial_errors"] = [
                {"memory_type": memory_type, "message": str(error)}
                for memory_type, error in failures
            ]
            output["lifecycle"]["partial"] = True

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

            # Keep the same step size as page_size (client maps page_size from limit)
            # so offset->page conversion remains stable across stitched fetches.
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

    async def _resolve_parent_ids(
        self,
        group_id: str,
        memory_ids: list[str],
    ) -> dict[str, str]:
        """Look up memcell parent_id for each memory_id by scanning recent memories."""
        target_set = set(memory_ids)
        id_to_parent: dict[str, str] = {}

        fetch_types = ("episodic_memory", "event_log", "profile", "foresight")
        fetch_results = await asyncio.gather(
            *(
                self._client.fetch_memories(
                    group_id, memory_type=mt, limit=100, offset=0
                )
                for mt in fetch_types
            ),
            return_exceptions=True,
        )

        known_parent_ids: set[str] = set()
        for fetch_result in fetch_results:
            if isinstance(fetch_result, BaseException):
                continue
            if not isinstance(fetch_result, dict):
                continue
            memories = fetch_result.get("result", {}).get("memories", [])
            if not isinstance(memories, list):
                continue
            for item in memories:
                if not isinstance(item, dict):
                    continue
                item_id = self._extract_memory_id(item)
                parent_id = self._extract_parent_id(item)
                if parent_id:
                    known_parent_ids.add(parent_id)
                if item_id and item_id in target_set and parent_id:
                    id_to_parent[item_id] = parent_id

        # If an input id is itself a known parent_id, map it to itself
        for mid in memory_ids:
            if mid in known_parent_ids and mid not in id_to_parent:
                id_to_parent[mid] = mid

        return id_to_parent

    async def forget(
        self,
        memory_ids: list[str],
        space_id: str,
        *,
        reason: str | None = None,
        user_id: str | None = None,
    ) -> dict:
        space_id = self._validate_space_id(space_id)
        user_id = self._validate_user_id(user_id)
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

        # Resolve parent_ids (memcell IDs) for deletion
        id_to_parent = await self._resolve_parent_ids(group_id, unique_ids)

        unresolved = [mid for mid in unique_ids if mid not in id_to_parent]

        errors: list[str] = []
        unmatched_ids: list[str] = []
        warnings: list[str] = []

        semaphore = asyncio.Semaphore(_FORGET_DELETE_CONCURRENCY)

        async def _delete_one(
            mid: str,
        ) -> tuple[str, int, EverMemosError | None]:
            async with semaphore:
                # Prefer parent_id (memcell ID) — the key Cloud DELETE actually uses
                delete_key = id_to_parent.get(mid, mid)
                try:
                    result = await self._client.delete_memories(
                        memory_id=delete_key,
                        group_id=group_id,
                    )
                except EverMemosError as e:
                    return mid, 0, e
                except Exception as e:  # pragma: no cover
                    return mid, 0, EverMemosError(
                        f"unexpected delete error: {e}",
                        code="UPSTREAM_ERROR",
                    )

                affected = self._parse_delete_affected_count(result)
                return mid, affected, None

        delete_results = await asyncio.gather(
            *(_delete_one(mid) for mid in unique_ids)
        )

        total_affected = 0
        logical_deleted = 0
        for mid, affected, err in delete_results:
            total_affected += affected
            if err is not None:
                errors.append(f"{mid}: {err}")
            elif affected > 0:
                logical_deleted += 1
            else:
                unmatched_ids.append(mid)

        if logical_deleted:
            self._catalog.adjust_memory_count(space_id, -logical_deleted)

        if unresolved:
            warnings.append(
                f"parent_id could not be resolved for {len(unresolved)} ID(s) "
                f"(beyond 100-item scan window or missing); "
                f"original id was sent as-is: {', '.join(unresolved[:5])}"
            )
        if unmatched_ids:
            warnings.append(
                "Some memory IDs were not matched by upstream delete."
            )

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
            "deleted_count": total_affected,
            "deleted_count_note": (
                "Total upstream records affected (may exceed input count "
                "because one memcell can have multiple derived records)."
            ),
        }
        if unmatched_ids:
            output["unmatched_ids"] = unmatched_ids
            output["unmatched_count"] = len(unmatched_ids)
        if normalized_reason:
            output["reason_logged"] = True
        if errors:
            output["errors"] = errors
        if warnings:
            output["warnings"] = warnings
        return output
