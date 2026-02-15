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
_ENTRY_JSON_PREFIX = "SPACE_CATALOG_ENTRY:"


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

    # -- public API --

    async def register_space(self, space_id: str, description: str = "") -> SpaceInfo:
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
        await self._persist_conversation_meta(
            space_id, description, created_at=info.created_at
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

    async def _persist_conversation_meta(
        self,
        space_id: str,
        description: str,
        *,
        created_at: str,
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

        try:
            await self._client.set_conversation_metadata(
                group_id=group_id,
                scene=scene,
                created_at=created_at,
                description=payload_description or None,
                scene_desc=scene_desc,
                tags=tags,
                llm_custom_setting=EVERMEMOS_LLM_CUSTOM_SETTING,
                user_details=EVERMEMOS_USER_DETAILS,
                default_timezone="UTC",
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

        try:
            await self._client.update_conversation_metadata(
                group_id=group_id,
                description=payload_description or None,
                scene_desc=scene_desc,
                tags=tags,
                llm_custom_setting=EVERMEMOS_LLM_CUSTOM_SETTING,
                user_details=EVERMEMOS_USER_DETAILS,
                default_timezone="UTC",
            )
        except EverMemosError as exc:
            logger.warning(
                "Failed to persist conversation metadata for %s: %s", space_id, exc
            )

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
            if self._cache:
                logger.info("Recovered %d spaces from catalog", len(self._cache))
        except EverMemosError:
            # Allow retry after cooldown
            self._recover_failed_at = time.monotonic()
            logger.debug(
                "Catalog recovery failed, will retry after %.0fs",
                _RECOVER_COOLDOWN_SECS,
            )

    async def _recover_from_paginated_fetch(self) -> bool:
        """Recover catalog entries by paging through fetch_memories results.

        Returns True when fetch API returned a parseable dict response at least once.
        """

        saw_valid_fetch = False
        for memory_type in ("event_log", "episodic_memory"):
            page = 1
            while page <= _CATALOG_MAX_FETCH_PAGES:
                response = await self._client.fetch_memories(
                    CATALOG_GROUP_ID,
                    memory_type=memory_type,
                    limit=_CATALOG_PAGE_SIZE,
                    offset=(page - 1) * _CATALOG_PAGE_SIZE,
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
                    if (page - 1) * _CATALOG_PAGE_SIZE + count >= total_count:
                        break
                elif count < _CATALOG_PAGE_SIZE:
                    break
                page += 1
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
        result = await self._client.search_memories(
            query="Registered memory space",
            group_id=CATALOG_GROUP_ID,
            retrieve_method="keyword",
            top_k=200,
        )
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

    def _parse_content(self, content: str, timestamp: str = "") -> None:
        if not content:
            return
        if self._parse_structured_content(content, timestamp=timestamp):
            return
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
        self._parse_content(text, timestamp=ts)
