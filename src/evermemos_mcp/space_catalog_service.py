"""Space catalog: manages space metadata.

Primary storage is in-memory (process lifetime).
Writes are also persisted to a reserved EverMemOS space for cross-session recovery.
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone

from .config import CATALOG_GROUP_ID, SPACE_GROUP_PREFIX
from .evermemos_client import EverMemosClient, EverMemosError

logger = logging.getLogger(__name__)

_RECOVER_COOLDOWN_SECS = 30.0


# -- helpers --

def to_group_id(space_id: str) -> str:
    """Convert user-facing space_id to EverMemOS group_id."""
    return f"{SPACE_GROUP_PREFIX}{space_id}"


def from_group_id(group_id: str) -> str | None:
    """Extract space_id from group_id, or None if not a user space."""
    if not group_id.startswith(SPACE_GROUP_PREFIX):
        return None
    candidate = group_id[len(SPACE_GROUP_PREFIX):]
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

    async def register_space(
        self, space_id: str, description: str = ""
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
        await self._persist_entry(space_id, description)
        return info

    def touch_space(self, space_id: str) -> None:
        """Bump last_used_at for an existing space."""
        if space_id in self._cache:
            self._cache[space_id].last_used_at = (
                datetime.now(timezone.utc).isoformat()
            )

    def get_space(self, space_id: str) -> SpaceInfo | None:
        return self._cache.get(space_id)

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

    async def _persist_entry(self, space_id: str, description: str) -> None:
        try:
            content = (
                f"Registered memory space: {space_id}"
                f" — {description or 'no description'}"
            )
            await self._client.add_message(
                group_id=CATALOG_GROUP_ID,
                content=content,
                role="user",
                flush=True,
            )
        except EverMemosError:
            logger.warning("Failed to persist catalog entry for %s", space_id)

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

        Search results are **flat items** (each with ``memory_type``, ``summary``,
        ``atomic_fact``, ``timestamp``, etc.), not nested groups.

        On network failure, retries after a cooldown instead of giving up permanently.
        """
        try:
            result = await self._client.search_memories(
                query="Registered memory space",
                group_id=CATALOG_GROUP_ID,
                retrieve_method="keyword",
                top_k=200,
            )
            res = result.get("result", {})

            # Parse extracted memories (flat items)
            for item in res.get("memories", []):
                if isinstance(item, dict):
                    self._parse_memory(item)

            # Parse pending (not-yet-extracted) messages
            for msg in res.get("pending_messages", []):
                self._parse_content(
                    msg.get("content", ""),
                    timestamp=msg.get("created_at", ""),
                )

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

    # -- parsing helpers --

    # Greedy \S+ so hyphenated IDs like coding:my-app are captured whole.
    # Delimiter requires whitespace on both sides to avoid splitting on
    # hyphens within the space_id.
    _ENTRY_RE = re.compile(
        r"Registered memory space:\s*(\S+)(?:\s+[—\-]\s+(.+))?$", re.MULTILINE
    )

    def _parse_content(
        self, content: str, timestamp: str = ""
    ) -> None:
        if not content:
            return
        for m in self._ENTRY_RE.finditer(content):
            sid = m.group(1).rstrip(".")
            desc = (m.group(2) or "").strip().rstrip(".")
            if desc.lower() == "no description":
                desc = ""
            if not sid:
                continue
            existing = self._cache.get(sid)
            if existing is None:
                self._cache[sid] = SpaceInfo(
                    space_id=sid,
                    description=desc,
                    created_at=timestamp,
                    last_used_at=timestamp,
                )
            elif timestamp and timestamp > (existing.last_used_at or ""):
                # Newer entry wins — update description and timestamps
                if desc:
                    existing.description = desc
                existing.last_used_at = timestamp

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
        ts = memory.get("timestamp", "") or memory.get("created_at", "")
        self._parse_content(text, timestamp=ts)
