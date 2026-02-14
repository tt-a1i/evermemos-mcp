"""Business logic layer for memory operations.

Orchestrates between evermemos_client and space_catalog_service.
Each method returns a plain dict that server.py serialises to the MCP client.
"""

from __future__ import annotations

import asyncio
import re
from datetime import datetime, timezone

from .evermemos_client import EverMemosClient, EverMemosError
from .space_catalog_service import SpaceCatalogService, to_group_id

_VALID_SENDERS = {"user", "assistant"}
_VALID_RETRIEVE_METHODS = {"keyword", "hybrid", "vector"}
_SPACE_ID_RE = re.compile(r"^[^\s:]+:[^\s:]+$")


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

        return {
            "ok": True,
            "space_id": space_id,
            "message_id": result.get("request_id", ""),
            "created_at": created_at,
            "processing_hint": (
                "Memory is queued for extraction. "
                "It may take a few minutes before it becomes searchable."
            ),
        }

    # -- recall --

    async def recall(
        self,
        query: str,
        space_id: str,
        *,
        top_k: int = 5,
        retrieve_method: str = "hybrid",
    ) -> dict:
        query = self._validate_text(query, "query")
        space_id = self._validate_space_id(space_id)
        top_k = self._validate_positive_int(top_k, "top_k")
        if retrieve_method not in _VALID_RETRIEVE_METHODS:
            raise EverMemosError(
                "retrieve_method must be one of: keyword, hybrid, vector",
                code="INVALID_INPUT",
            )

        group_id = to_group_id(space_id)
        self._catalog.touch_space(space_id)

        result = await self._client.search_memories(
            query, group_id, retrieve_method=retrieve_method, top_k=top_k
        )
        res = result.get("result", {})

        results = []
        for item in res.get("memories", []):
            if not isinstance(item, dict):
                continue
            snippet = item.get("summary", "") or item.get("atomic_fact", "") or ""
            results.append(
                {
                    "memory_id": item.get("id", ""),
                    "memory_type": item.get("memory_type", ""),
                    "snippet": snippet[:500],
                    "timestamp": item.get("timestamp", ""),
                    "score": item.get("score"),
                }
            )

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

        return output

    # -- briefing --

    async def briefing(self, space_id: str, *, max_items: int = 8) -> dict:
        space_id = self._validate_space_id(space_id)
        max_items = self._validate_positive_int(max_items, "max_items")

        group_id = to_group_id(space_id)
        self._catalog.touch_space(space_id)

        profile_res, episodic_res, event_res = await asyncio.gather(
            self._client.fetch_memories(group_id, memory_type="profile", limit=1),
            self._client.fetch_memories(
                group_id, memory_type="episodic_memory", limit=max_items
            ),
            self._client.fetch_memories(
                group_id, memory_type="event_log", limit=max_items
            ),
            return_exceptions=True,
        )

        results = {
            "profile": profile_res,
            "episodic_memory": episodic_res,
            "event_log": event_res,
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
                for pd in pw.get("profiles", [])[:3]:
                    data = pd.get("profile_data", {})
                    text = (
                        data.get("summary", "") if isinstance(data, dict) else str(data)
                    )
                    if text:
                        highlights.append(
                            {
                                "type": "profile",
                                "content": text[:300],
                                "timestamp": (
                                    data.get("timestamp", "")
                                    if isinstance(data, dict)
                                    else ""
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
        deleted = 0
        errors: list[str] = []

        for mid in unique_ids:
            try:
                result = await self._client.delete_memories(
                    event_id=mid, group_id=group_id
                )
                count = result.get("result", {}).get("count", 0)
                deleted += count
                self._catalog.adjust_memory_count(space_id, -count)
            except EverMemosError as e:
                errors.append(f"{mid}: {e}")

        output: dict = {
            "ok": len(errors) == 0,
            "space_id": space_id,
            "deleted_count": deleted,
        }
        if errors:
            output["errors"] = errors
        return output
