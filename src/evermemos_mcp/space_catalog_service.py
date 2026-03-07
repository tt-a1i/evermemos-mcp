"""Space catalog: manages space metadata.

Primary storage is in-memory (process lifetime).
Writes are also persisted to a reserved EverMemOS space for cross-session recovery.
"""

from __future__ import annotations

import logging
import json
import re
import time
import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone

from .config import (
    CATALOG_GROUP_ID,
    SPACE_GROUP_PREFIX,
    EVERMEMOS_CONVERSATION_SCENE,
    EVERMEMOS_DEFAULT_TIMEZONE,
    EVERMEMOS_ENABLE_CONVERSATION_META,
    EVERMEMOS_LLM_CUSTOM_SETTING,
    EVERMEMOS_USER_DETAILS,
)
from .evermemos_client import EverMemosClient, EverMemosError

logger = logging.getLogger(__name__)

_RECOVER_COOLDOWN_SECS = 30.0
_META_ENRICH_CONCURRENCY = 8
_META_ENRICH_MAX_SPACES = 60
_CATALOG_PAGE_SIZE = 100
_CATALOG_MAX_FETCH_PAGES = 500
_CATALOG_SEARCH_TOP_K_PREFERRED = -1
_CATALOG_SEARCH_TOP_K_FALLBACK = 200
_ENTRY_JSON_PREFIX = "SPACE_CATALOG_ENTRY:"
_VALID_META_ROLES = {"user", "assistant"}


# -- helpers --


def to_group_id(space_id: str) -> str:
    """Convert user-facing space_id to EverMemOS group_id."""
    return f"{SPACE_GROUP_PREFIX}{space_id}"


def from_group_id(group_id: str) -> str | None:
    """Extract space_id from group_id, or None if not a user space."""
    if not group_id.startswith(SPACE_GROUP_PREFIX):
        return None
    candidate = group_id[len(SPACE_GROUP_PREFIX) :]
    if candidate == "catalog" or candidate.startswith("catalog:"):
        return None
    return candidate


# -- data --


@dataclass
class SpaceInfo:
    space_id: str
    description: str = ""
    memory_count: int = 0
    last_used_at: str = ""
    created_at: str = ""


# -- service --


class SpaceCatalogService:
    """In-memory space registry backed by EverMemOS for persistence.

    Spaces are created implicitly when ``remember`` is called with a new space_id.
    On first ``list_spaces`` call, attempts recovery from the catalog space.
    """

    def __init__(self, client: EverMemosClient):
        self._client = client
        self._cache: dict[str, SpaceInfo] = {}
        self._recovered = False
        self._recover_failed_at: float = 0.0
        self._recover_last_error: dict[str, str | int] | None = None
        self._conversation_meta_locks: dict[str, asyncio.Lock] = {}
        self._known_conversation_meta_spaces: set[str] = set()
        self._conversation_meta_created_at: dict[str, str] = {}
        self._conversation_meta_user_details: dict[str, dict[str, dict]] = {}

    # -- public API --

    async def register_space(
        self,
        space_id: str,
        description: str = "",
        *,
        actor_user_id: str | None = None,
        actor_role: str = "user",
        actor_profile: dict | None = None,
    ) -> SpaceInfo:
        """Register or update a space. Persists to EverMemOS (best-effort)."""
        now = datetime.now(timezone.utc).isoformat()

        if space_id in self._cache:
            info = self._cache[space_id]
            if description and description != info.description:
                info.description = description
            info.last_used_at = now
        else:
            info = SpaceInfo(
                space_id=space_id,
                description=description,
                last_used_at=now,
                created_at=now,
            )
            self._cache[space_id] = info

        # Best-effort persist to catalog space
        await self._persist_entry(space_id, description, created_at=info.created_at)
        await self._persist_conversation_meta_locked(
            space_id,
            description,
            created_at=info.created_at,
            actor_user_id=actor_user_id,
            actor_role=actor_role,
            actor_profile=actor_profile,
        )
        return info

    def touch_space(self, space_id: str) -> None:
        """Bump last_used_at for an existing space."""
        if space_id in self._cache:
            self._cache[space_id].last_used_at = datetime.now(timezone.utc).isoformat()

    def get_space(self, space_id: str) -> SpaceInfo | None:
        return self._cache.get(space_id)

    def adjust_memory_count(self, space_id: str, delta: int) -> None:
        """Adjust in-memory memory_count for a space.

        - Positive delta: creates the space if missing.
        - Negative delta: no-op when space is unknown.
        - Count never drops below 0.
        """
        if delta == 0:
            return

        info = self._cache.get(space_id)
        if info is None:
            if delta < 0:
                return
            info = self.ensure_space(space_id)

        info.memory_count = max(0, info.memory_count + delta)
        info.last_used_at = datetime.now(timezone.utc).isoformat()

    def ensure_space(self, space_id: str) -> SpaceInfo:
        """Get or create a minimal space entry (no Cloud write)."""
        if space_id not in self._cache:
            now = datetime.now(timezone.utc).isoformat()
            self._cache[space_id] = SpaceInfo(
                space_id=space_id, last_used_at=now, created_at=now
            )
        return self._cache[space_id]

    async def ensure_conversation_meta(
        self,
        space_id: str,
        description: str | None = None,
        *,
        actor_user_id: str | None = None,
        actor_role: str = "user",
        actor_profile: dict | None = None,
    ) -> None:
        """Best-effort metadata upsert for a space.

        Useful when remember() writes to a space that has no explicit description.
        """
        info = self.ensure_space(space_id)
        if description is not None and description.strip():
            info.description = description.strip()

        created_at = info.created_at or datetime.now(timezone.utc).isoformat()
        if not info.created_at:
            info.created_at = created_at
        await self._persist_conversation_meta_locked(
            space_id,
            info.description,
            created_at=created_at,
            actor_user_id=actor_user_id,
            actor_role=actor_role,
            actor_profile=actor_profile,
        )

    async def get_conversation_meta(
        self,
        space_id: str,
        *,
        refresh: bool = False,
    ) -> dict | None:
        if not EVERMEMOS_ENABLE_CONVERSATION_META:
            return None

        if not refresh:
            cached_snapshot = self._get_cached_conversation_meta_snapshot(space_id)
            if cached_snapshot is not None:
                return cached_snapshot

        snapshot = await self._fetch_conversation_meta_snapshot(to_group_id(space_id))
        if isinstance(snapshot, dict):
            self._cache_conversation_meta_snapshot(
                space_id,
                created_at=snapshot.get("created_at"),
                user_details=snapshot.get("user_details"),
            )
            return snapshot

        if not refresh:
            return self._get_cached_conversation_meta_snapshot(space_id)
        return None

    async def list_spaces(
        self, query: str | None = None, limit: int = 20
    ) -> list[SpaceInfo]:
        """Return known spaces, optionally filtered by query substring."""
        if self._should_try_recover():
            await self._try_recover()

        spaces = list(self._cache.values())

        if query:
            q = query.lower()
            spaces = [
                s
                for s in spaces
                if q in s.space_id.lower() or q in s.description.lower()
            ]

        spaces.sort(key=lambda s: s.last_used_at or "", reverse=True)
        return spaces[:limit]

    def get_recovery_warning(self) -> dict | None:
        if self._recover_last_error is None:
            return None

        warning = {
            "code": "CATALOG_RECOVERY_FAILED",
            "message": (
                "Cloud catalog recovery failed; list_spaces is showing local cache only."
            ),
            "details": dict(self._recover_last_error),
        }
        if self._recover_last_error.get("code") == "AuthenticationError":
            warning["hint"] = (
                "Cloud requests are being rejected by upstream authentication. "
                "Verify the active EVERMEMOS_API_KEY in the runtime environment."
            )
        return warning

    # -- persistence (best-effort) --

    async def _persist_entry(
        self,
        space_id: str,
        description: str,
        *,
        created_at: str,
    ) -> None:
        try:
            payload = {
                "version": 1,
                "space_id": space_id,
                "description": description or "",
                "created_at": created_at,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
            legacy_text = (
                f"Registered memory space: {space_id}"
                f" — {description or 'no description'}"
            )
            content = (
                f"{_ENTRY_JSON_PREFIX}{json.dumps(payload, ensure_ascii=True)}\n"
                f"{legacy_text}"
            )
            await self._client.add_message(
                group_id=CATALOG_GROUP_ID,
                content=content,
                role="user",
                flush=True,
            )
        except EverMemosError:
            logger.warning("Failed to persist catalog entry for %s", space_id)

    def _get_conversation_meta_lock(self, space_id: str) -> asyncio.Lock:
        # Intentionally sync-only: keep get/create atomic in one event-loop turn.
        # Do not add await points in this helper.
        lock = self._conversation_meta_locks.get(space_id)
        if lock is None:
            lock = asyncio.Lock()
            self._conversation_meta_locks[space_id] = lock
        return lock

    async def _persist_conversation_meta_locked(
        self,
        space_id: str,
        description: str,
        *,
        created_at: str,
        actor_user_id: str | None = None,
        actor_role: str = "user",
        actor_profile: dict | None = None,
    ) -> None:
        lock = self._get_conversation_meta_lock(space_id)
        async with lock:
            await self._persist_conversation_meta(
                space_id,
                description,
                created_at=created_at,
                actor_user_id=actor_user_id,
                actor_role=actor_role,
                actor_profile=actor_profile,
            )

        waiters = getattr(lock, "_waiters", None)
        has_waiters = bool(waiters)
        if (
            self._conversation_meta_locks.get(space_id) is lock
            and not lock.locked()
            and not has_waiters
        ):
            self._conversation_meta_locks.pop(space_id, None)

    @staticmethod
    def _extract_meta_created_at(meta: dict) -> str | None:
        created = meta.get("conversation_created_at") or meta.get("created_at")
        if isinstance(created, str) and created.strip():
            return created.strip()
        return None

    def _cache_conversation_meta_snapshot(
        self,
        space_id: str,
        *,
        created_at: str | None,
        user_details: object,
    ) -> None:
        self._known_conversation_meta_spaces.add(space_id)

        if isinstance(created_at, str) and created_at.strip():
            normalized_created_at = created_at.strip()
            self._conversation_meta_created_at[space_id] = normalized_created_at

            info = self._cache.get(space_id)
            if info is not None:
                info.created_at = normalized_created_at

        normalized_user_details = self._normalize_user_details(user_details)
        if normalized_user_details:
            self._conversation_meta_user_details[space_id] = normalized_user_details

    def _get_cached_conversation_meta_snapshot(self, space_id: str) -> dict | None:
        if space_id not in self._known_conversation_meta_spaces:
            return None

        snapshot: dict = {}
        created_at = self._conversation_meta_created_at.get(space_id)
        if isinstance(created_at, str) and created_at:
            snapshot["created_at"] = created_at

        user_details = self._conversation_meta_user_details.get(space_id)
        if isinstance(user_details, dict) and user_details:
            snapshot["user_details"] = dict(user_details)

        return snapshot

    @staticmethod
    def _is_group_scene_desc_compat_error(exc: EverMemosError) -> bool:
        message = str(exc).lower()
        return "scene_desc" in message and "group-level config" in message

    @staticmethod
    def _is_group_scene_inherited_error(exc: EverMemosError) -> bool:
        message = str(exc).lower()
        return "group-level config" in message and "cannot set 'scene'" in message

    @staticmethod
    def _requires_group_name_error(exc: EverMemosError) -> bool:
        message = str(exc).lower()
        return "group-level config requires 'name' field" in message

    @staticmethod
    def _conversation_meta_name(space_id: str) -> str:
        return space_id

    async def _set_conversation_metadata_compat(
        self,
        *,
        group_id: str,
        space_id: str,
        scene: str,
        created_at: str,
        description: str | None,
        scene_desc: dict,
        tags: list[str],
        user_details: dict | None,
    ) -> None:
        payload = {
            "group_id": group_id,
            "scene": scene,
            "created_at": created_at,
            "description": description,
            "scene_desc": scene_desc,
            "tags": tags,
            "llm_custom_setting": EVERMEMOS_LLM_CUSTOM_SETTING,
            "user_details": user_details,
            "default_timezone": EVERMEMOS_DEFAULT_TIMEZONE,
        }

        try:
            await self._client.set_conversation_metadata(**payload)
            return
        except EverMemosError as exc:
            needs_group_create_compat = (
                self._is_group_scene_inherited_error(exc)
                or self._is_group_scene_desc_compat_error(exc)
                or self._requires_group_name_error(exc)
            )
            if not needs_group_create_compat:
                raise

        compat_payload = dict(payload)
        compat_payload.pop("scene", None)
        compat_payload.pop("scene_desc", None)
        compat_payload["name"] = self._conversation_meta_name(space_id)
        await self._client.set_conversation_metadata(**compat_payload)

    async def _update_conversation_metadata_compat(
        self,
        *,
        group_id: str,
        description: str | None,
        scene_desc: dict,
        tags: list[str],
        user_details: dict | None,
    ) -> None:
        payload = {
            "group_id": group_id,
            "description": description,
            "scene_desc": scene_desc,
            "tags": tags,
            "llm_custom_setting": EVERMEMOS_LLM_CUSTOM_SETTING,
            "user_details": user_details,
            "default_timezone": EVERMEMOS_DEFAULT_TIMEZONE,
        }

        try:
            await self._client.update_conversation_metadata(**payload)
            return
        except EverMemosError as exc:
            if not self._is_group_scene_desc_compat_error(exc):
                raise

        payload.pop("scene_desc", None)
        await self._client.update_conversation_metadata(**payload)

    async def _fetch_conversation_meta_snapshot(self, group_id: str) -> dict | None:
        try:
            existing_response = await self._client.get_conversation_metadata(group_id)
        except EverMemosError:
            return None

        if not isinstance(existing_response, dict):
            return None

        result = existing_response.get("result")
        if not isinstance(result, dict):
            return None

        snapshot: dict = {}
        created_at = self._extract_meta_created_at(result)
        if created_at:
            snapshot["created_at"] = created_at
        user_details = result.get("user_details")
        if isinstance(user_details, dict) and user_details:
            snapshot["user_details"] = user_details
        return snapshot or None

    async def _persist_conversation_meta(
        self,
        space_id: str,
        description: str,
        *,
        created_at: str,
        actor_user_id: str | None = None,
        actor_role: str = "user",
        actor_profile: dict | None = None,
    ) -> None:
        if not EVERMEMOS_ENABLE_CONVERSATION_META:
            return

        group_id = to_group_id(space_id)
        domain = space_id.split(":", 1)[0] if ":" in space_id else "general"
        payload_description = (
            description or self._cache.get(space_id, SpaceInfo(space_id)).description
        )

        scene = EVERMEMOS_CONVERSATION_SCENE
        if scene not in {"assistant", "group_chat"}:
            scene = "assistant"

        scene_desc = {
            "description": payload_description or f"MCP memory space for {space_id}",
            "space_id": space_id,
            "domain": domain,
            "source": "evermemos-mcp",
        }
        tags = ["mcp", "memory-space", f"domain:{domain}", f"space:{space_id}"]
        base_user_details = self._merge_user_details(
            actor_user_id=actor_user_id,
            actor_role=actor_role,
            actor_profile=actor_profile,
        )

        known_exists = space_id in self._known_conversation_meta_spaces
        existing_snapshot = self._get_cached_conversation_meta_snapshot(space_id)
        if existing_snapshot is None:
            fetched_snapshot = await self._fetch_conversation_meta_snapshot(group_id)
            if isinstance(fetched_snapshot, dict):
                existing_snapshot = fetched_snapshot
                known_exists = True
                self._cache_conversation_meta_snapshot(
                    space_id,
                    created_at=fetched_snapshot.get("created_at"),
                    user_details=fetched_snapshot.get("user_details"),
                )

        effective_created_at = created_at
        if isinstance(existing_snapshot, dict):
            existing_created_at = existing_snapshot.get("created_at")
            if isinstance(existing_created_at, str) and existing_created_at.strip():
                effective_created_at = existing_created_at.strip()

        user_details = self._merge_with_existing_user_details(
            base_user_details,
            existing_snapshot.get("user_details")
            if isinstance(existing_snapshot, dict)
            else None,
        )

        if known_exists:
            try:
                await self._update_conversation_metadata_compat(
                    group_id=group_id,
                    description=payload_description or None,
                    scene_desc=scene_desc,
                    tags=tags,
                    user_details=user_details,
                )
            except EverMemosError as exc:
                logger.warning(
                    "Failed to persist conversation metadata for %s: %s", space_id, exc
                )
            else:
                self._cache_conversation_meta_snapshot(
                    space_id,
                    created_at=effective_created_at,
                    user_details=user_details,
                )
            return

        try:
            await self._set_conversation_metadata_compat(
                group_id=group_id,
                space_id=space_id,
                scene=scene,
                created_at=effective_created_at,
                description=payload_description or None,
                scene_desc=scene_desc,
                tags=tags,
                user_details=user_details,
            )
            self._cache_conversation_meta_snapshot(
                space_id,
                created_at=effective_created_at,
                user_details=user_details,
            )
            return
        except EverMemosError as exc:
            recoverable_statuses = {400, 404, 409, 422}
            if exc.code == "UPSTREAM_UNAVAILABLE" or (
                exc.status_code is not None and exc.status_code >= 500
            ):
                logger.warning(
                    "Failed to set conversation metadata for %s: %s", space_id, exc
                )
                return
            if (
                exc.status_code is not None
                and exc.status_code not in recoverable_statuses
            ):
                logger.warning(
                    "Failed to set conversation metadata for %s: %s", space_id, exc
                )
                return
            # Existing metadata or schema variance — fallback to patch.

        retry_snapshot = await self._fetch_conversation_meta_snapshot(group_id)
        if isinstance(retry_snapshot, dict):
            retry_created_at = retry_snapshot.get("created_at")
            if isinstance(retry_created_at, str) and retry_created_at.strip():
                effective_created_at = retry_created_at.strip()
            user_details = self._merge_with_existing_user_details(
                base_user_details,
                retry_snapshot.get("user_details"),
            )
            self._cache_conversation_meta_snapshot(
                space_id,
                created_at=retry_snapshot.get("created_at"),
                user_details=retry_snapshot.get("user_details"),
            )

        try:
            await self._update_conversation_metadata_compat(
                group_id=group_id,
                description=payload_description or None,
                scene_desc=scene_desc,
                tags=tags,
                user_details=user_details,
            )
        except EverMemosError as exc:
            logger.warning(
                "Failed to persist conversation metadata for %s: %s", space_id, exc
            )
        else:
            self._cache_conversation_meta_snapshot(
                space_id,
                created_at=effective_created_at,
                user_details=user_details,
            )

    @staticmethod
    def _merge_user_details(
        *,
        actor_user_id: str | None,
        actor_role: str,
        actor_profile: dict | None = None,
    ) -> dict | None:
        merged: dict[str, dict] = {}

        user_details = EVERMEMOS_USER_DETAILS
        if isinstance(user_details, dict):
            for raw_user_id, raw_profile in user_details.items():
                if not isinstance(raw_user_id, str) or not raw_user_id.strip():
                    continue
                user_id = raw_user_id.strip()
                profile = dict(raw_profile) if isinstance(raw_profile, dict) else {}
                merged[user_id] = profile

        if isinstance(actor_user_id, str) and actor_user_id.strip():
            normalized_actor_user_id = actor_user_id.strip()
            normalized_role = actor_role if actor_role in _VALID_META_ROLES else "user"
            existing_actor_profile = merged.get(normalized_actor_user_id)
            if existing_actor_profile is None:
                merged[normalized_actor_user_id] = {
                    "full_name": normalized_actor_user_id,
                    "role": normalized_role,
                }
            else:
                if not isinstance(
                    existing_actor_profile.get("role"), str
                ) or not existing_actor_profile.get("role"):
                    existing_actor_profile["role"] = normalized_role
                if not isinstance(
                    existing_actor_profile.get("full_name"), str
                ) or not existing_actor_profile.get("full_name"):
                    existing_actor_profile["full_name"] = normalized_actor_user_id

        if (
            isinstance(actor_user_id, str)
            and actor_user_id.strip()
            and isinstance(actor_profile, dict)
            and actor_profile
        ):
            normalized_actor_user_id = actor_user_id.strip()
            existing_profile = merged.get(normalized_actor_user_id, {})
            merged[normalized_actor_user_id] = SpaceCatalogService._merge_profile_payload(
                existing_profile,
                actor_profile,
                user_id=normalized_actor_user_id,
            )

        return merged or None

    @staticmethod
    def _is_empty_profile_value(value: object) -> bool:
        if value is None:
            return True
        if isinstance(value, str):
            return not value.strip()
        if isinstance(value, (list, dict, tuple, set)):
            return len(value) == 0
        return False

    @classmethod
    def _merge_profile_payload(
        cls,
        existing_profile: object,
        incoming_profile: object,
        *,
        user_id: str,
    ) -> dict:
        existing = (
            dict(existing_profile) if isinstance(existing_profile, dict) else {}
        )
        incoming = (
            dict(incoming_profile) if isinstance(incoming_profile, dict) else {}
        )

        merged = dict(existing)
        for key, value in incoming.items():
            if cls._is_empty_profile_value(value):
                continue

            if key == "full_name" and isinstance(value, str):
                incoming_name = value.strip()
                if not incoming_name:
                    continue
                current_name = merged.get("full_name")
                normalized_current = (
                    current_name.strip() if isinstance(current_name, str) else ""
                )
                if (
                    not normalized_current
                    or normalized_current == user_id
                    or incoming_name != user_id
                ):
                    merged["full_name"] = incoming_name
                continue

            if key == "role" and isinstance(value, str):
                incoming_role = value.strip()
                current_role = merged.get("role")
                normalized_current = (
                    current_role.strip() if isinstance(current_role, str) else ""
                )
                if not normalized_current or (
                    normalized_current == "user" and incoming_role != "user"
                ):
                    merged["role"] = incoming_role
                continue

            current_value = merged.get(key)
            if isinstance(value, list):
                existing_items = (
                    list(current_value) if isinstance(current_value, list) else []
                )
                seen_items = {
                    item.strip() if isinstance(item, str) else repr(item)
                    for item in existing_items
                }
                merged_items = list(existing_items)
                for item in value:
                    normalized_item = item.strip() if isinstance(item, str) else item
                    dedupe_key = (
                        normalized_item if isinstance(normalized_item, str) else repr(item)
                    )
                    if dedupe_key in seen_items or cls._is_empty_profile_value(
                        normalized_item
                    ):
                        continue
                    seen_items.add(dedupe_key)
                    merged_items.append(normalized_item)
                if merged_items:
                    merged[key] = merged_items
                continue

            if isinstance(value, dict):
                merged[key] = cls._merge_profile_payload(
                    current_value,
                    value,
                    user_id=user_id,
                )
                continue

            if cls._is_empty_profile_value(current_value):
                merged[key] = value

        return merged

    @staticmethod
    def _normalize_user_details(payload: object) -> dict[str, dict]:
        if not isinstance(payload, dict):
            return {}

        normalized: dict[str, dict] = {}
        for raw_user_id, raw_profile in payload.items():
            if not isinstance(raw_user_id, str) or not raw_user_id.strip():
                continue
            user_id = raw_user_id.strip()
            profile = dict(raw_profile) if isinstance(raw_profile, dict) else {}
            normalized[user_id] = profile
        return normalized

    @classmethod
    def _merge_with_existing_user_details(
        cls,
        base_user_details: dict | None,
        existing_user_details: object,
    ) -> dict | None:
        merged = cls._normalize_user_details(base_user_details)
        existing = cls._normalize_user_details(existing_user_details)

        for user_id, profile in existing.items():
            current = merged.get(user_id)
            if current is None:
                merged[user_id] = profile
                continue

            merged[user_id] = cls._merge_profile_payload(
                profile,
                current,
                user_id=user_id,
            )

        return merged or None

    def _should_try_recover(self) -> bool:
        """Check if recovery should be attempted."""
        if self._recovered:
            return False
        if self._recover_failed_at:
            elapsed = time.monotonic() - self._recover_failed_at
            if elapsed < _RECOVER_COOLDOWN_SECS:
                return False
        return True

    async def _try_recover(self) -> None:
        """Best-effort: recover space list from EverMemOS catalog space.

        Prefer paginated fetch (stable, exhaustive). Fallback to keyword search when
        fetch is unavailable/incompatible.

        On network failure, retries after a cooldown instead of giving up permanently.
        """
        try:
            recovered_from_fetch = await self._recover_from_paginated_fetch()
            if not recovered_from_fetch:
                await self._recover_from_search(include_extracted=True)
            else:
                # Fetch API does not include pending_messages; enrich with a lightweight
                # search call to surface queued-but-not-extracted catalog writes.
                await self._recover_from_search(include_extracted=False)

            if self._cache and EVERMEMOS_ENABLE_CONVERSATION_META:
                ranked = sorted(
                    self._cache.values(),
                    key=lambda item: item.last_used_at or "",
                    reverse=True,
                )
                target_space_ids = [
                    item.space_id for item in ranked[:_META_ENRICH_MAX_SPACES]
                ]
                await self._enrich_with_conversation_meta(target_space_ids)

            # Mark success — no more retries
            self._recovered = True
            self._recover_failed_at = 0.0
            self._recover_last_error = None
            if self._cache:
                logger.info("Recovered %d spaces from catalog", len(self._cache))
        except EverMemosError as exc:
            # Allow retry after cooldown
            self._recover_failed_at = time.monotonic()
            self._recover_last_error = {
                "message": str(exc),
                "code": exc.code,
                "status_code": exc.status_code or 0,
            }
            logger.debug(
                "Catalog recovery failed, will retry after %.0fs",
                _RECOVER_COOLDOWN_SECS,
            )

    async def _recover_from_paginated_fetch(self) -> bool:
        """Recover catalog entries by paging through fetch_memories results.

        Returns True when fetch API returned a parseable dict response at least once.
        """

        saw_valid_fetch = False
        # Keep pagination aligned with client-side limit clamp (<=100).
        page_size = max(1, min(_CATALOG_PAGE_SIZE, 100))
        for memory_type in ("event_log", "episodic_memory"):
            page = 0
            offset = 0
            while page < _CATALOG_MAX_FETCH_PAGES:
                response = await self._client.fetch_memories(
                    CATALOG_GROUP_ID,
                    memory_type=memory_type,
                    limit=page_size,
                    offset=offset,
                )
                if not isinstance(response, dict):
                    return saw_valid_fetch

                result = response.get("result")
                if not isinstance(result, dict):
                    break

                memories = result.get("memories", [])
                if not isinstance(memories, list):
                    break
                saw_valid_fetch = True
                for item in memories:
                    if isinstance(item, dict):
                        self._parse_memory(item)

                count = result.get("count")
                if not isinstance(count, int):
                    count = len(memories)
                total_count = result.get("total_count")

                if count <= 0:
                    break
                if isinstance(total_count, int) and total_count >= 0:
                    if offset + count >= total_count:
                        break
                elif count < page_size:
                    break
                page += 1
                offset += page_size
            else:
                logger.warning(
                    "Catalog recovery stopped at max pages for %s (limit=%d)",
                    memory_type,
                    _CATALOG_MAX_FETCH_PAGES,
                )

        return saw_valid_fetch

    async def _recover_from_search(self, *, include_extracted: bool) -> None:
        """Recover from search API.

        - include_extracted=True: parse extracted memories + pending messages.
        - include_extracted=False: parse only pending messages.
        """
        result = await self._search_catalog_records("Registered memory space")
        if not isinstance(result, dict):
            return
        res = result.get("result", {})
        if not isinstance(res, dict):
            return

        if include_extracted:
            for item in res.get("memories", []):
                if isinstance(item, dict):
                    self._parse_memory(item)

        for msg in res.get("pending_messages", []):
            if not isinstance(msg, dict):
                continue
            self._parse_content(
                msg.get("content", ""),
                timestamp=msg.get("created_at", ""),
            )

    async def _search_catalog_records(self, query: str) -> dict:
        try:
            return await self._client.search_memories(
                query=query,
                group_id=CATALOG_GROUP_ID,
                retrieve_method="keyword",
                top_k=_CATALOG_SEARCH_TOP_K_PREFERRED,
            )
        except EverMemosError as exc:
            recoverable_codes = {"INVALID_INPUT", "INVALID_PARAMETER"}
            recoverable_statuses = {400, 422}
            if (
                exc.code not in recoverable_codes
                and exc.status_code not in recoverable_statuses
            ):
                raise

        return await self._client.search_memories(
            query=query,
            group_id=CATALOG_GROUP_ID,
            retrieve_method="keyword",
            top_k=_CATALOG_SEARCH_TOP_K_FALLBACK,
        )

    async def _enrich_with_conversation_meta(self, space_ids: list[str]) -> None:
        if not space_ids:
            return
        semaphore = asyncio.Semaphore(_META_ENRICH_CONCURRENCY)

        async def _fetch_for_space(space_id: str) -> None:
            async with semaphore:
                try:
                    response = await self._client.get_conversation_metadata(
                        to_group_id(space_id)
                    )
                except EverMemosError:
                    return

                if not isinstance(response, dict):
                    return
                result = response.get("result")
                if not isinstance(result, dict):
                    return

                info = self._cache.get(space_id)
                if info is None:
                    return

                desc = result.get("description")
                if isinstance(desc, str) and desc.strip():
                    info.description = desc.strip()

                created = result.get("conversation_created_at") or result.get(
                    "created_at"
                )
                if isinstance(created, str) and created and not info.created_at:
                    info.created_at = created

                updated = result.get("updated_at") or result.get("created_at")
                if isinstance(updated, str) and updated:
                    info.last_used_at = max(info.last_used_at or "", updated)

                self._cache_conversation_meta_snapshot(
                    space_id,
                    created_at=created,
                    user_details=result.get("user_details"),
                )

        await asyncio.gather(*(_fetch_for_space(space_id) for space_id in space_ids))

    # -- parsing helpers --

    # Greedy \S+ so hyphenated IDs like coding:my-app are captured whole.
    # Delimiter requires whitespace on both sides to avoid splitting on
    # hyphens within the space_id.
    _ENTRY_RE = re.compile(
        r"Registered memory space:\s*(\S+)(?:\s+[—\-]\s+(.+))?$", re.MULTILINE
    )

    @staticmethod
    def _pick_newest(a: str, b: str) -> str:
        return a if (a or "") >= (b or "") else b

    def _apply_space_record(
        self,
        *,
        space_id: str,
        description: str,
        created_at: str,
        updated_at: str,
    ) -> None:
        existing = self._cache.get(space_id)
        if existing is None:
            self._cache[space_id] = SpaceInfo(
                space_id=space_id,
                description=description,
                created_at=created_at,
                last_used_at=updated_at,
            )
            return

        if description and updated_at >= (existing.last_used_at or ""):
            existing.description = description
        if created_at and not existing.created_at:
            existing.created_at = created_at
        if updated_at:
            existing.last_used_at = self._pick_newest(existing.last_used_at, updated_at)

    def _parse_structured_content(self, content: str, timestamp: str = "") -> bool:
        parsed_any = False
        for line in content.splitlines():
            prefix_index = line.find(_ENTRY_JSON_PREFIX)
            if prefix_index < 0:
                continue

            raw_json = line[prefix_index + len(_ENTRY_JSON_PREFIX) :].strip()
            if not raw_json:
                continue

            try:
                payload = json.loads(raw_json)
            except json.JSONDecodeError:
                continue

            if not isinstance(payload, dict):
                continue
            sid = payload.get("space_id")
            if not isinstance(sid, str) or not sid.strip():
                continue

            desc = payload.get("description")
            if not isinstance(desc, str):
                desc = ""

            created_at = payload.get("created_at")
            if not isinstance(created_at, str):
                created_at = timestamp

            updated_at = payload.get("updated_at")
            if not isinstance(updated_at, str):
                updated_at = timestamp or created_at

            self._apply_space_record(
                space_id=sid.strip(),
                description=desc.strip(),
                created_at=created_at,
                updated_at=updated_at,
            )
            parsed_any = True

        return parsed_any

    def _parse_content(self, content: str, timestamp: str = "") -> bool:
        if not content:
            return False
        if self._parse_structured_content(content, timestamp=timestamp):
            return True
        parsed_any = False
        for m in self._ENTRY_RE.finditer(content):
            sid = m.group(1).rstrip(".")
            desc = (m.group(2) or "").strip().rstrip(".")
            if desc.lower() == "no description":
                desc = ""
            if not sid:
                continue
            self._apply_space_record(
                space_id=sid,
                description=desc,
                created_at=timestamp,
                updated_at=timestamp,
            )
            parsed_any = True
        return parsed_any

    @staticmethod
    def _iter_original_data_objects(payload: object) -> list[dict]:
        if isinstance(payload, dict):
            return [payload]
        if isinstance(payload, list):
            return [item for item in payload if isinstance(item, dict)]
        return []

    def _parse_original_content(self, memory: dict, timestamp: str = "") -> bool:
        original_data = memory.get("original_data")
        payloads = self._iter_original_data_objects(original_data)
        if not payloads:
            return False

        parsed_any = False

        def _parse_candidate(content: object) -> None:
            nonlocal parsed_any
            if isinstance(content, str) and content:
                parsed_any = self._parse_content(content, timestamp=timestamp) or parsed_any

        for payload in payloads:
            _parse_candidate(payload.get("content"))

            message = payload.get("message")
            if isinstance(message, dict):
                _parse_candidate(message.get("content"))

            messages = payload.get("messages")
            if isinstance(messages, list):
                for item in messages:
                    if isinstance(item, dict):
                        _parse_candidate(item.get("content"))

        return parsed_any

    def _parse_memory(self, memory: dict) -> None:
        """Parse a flat search-result item.

        Handles both episodic_memory (``summary``) and
        event_log (``atomic_fact``) field naming.
        """
        text = (
            memory.get("summary", "")
            or memory.get("atomic_fact", "")
            or memory.get("content", "")
        )
        if isinstance(text, list):
            text = "\n".join(str(item) for item in text if item)
        if not isinstance(text, str):
            text = str(text)
        ts = memory.get("timestamp", "") or memory.get("created_at", "")
        if self._parse_original_content(memory, timestamp=ts):
            return
        self._parse_content(text, timestamp=ts)
