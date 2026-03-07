"""Shared helpers for local demo/validation scripts."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]


def add_project_src_to_path() -> None:
    src_path = str(ROOT / "src")
    if src_path not in sys.path:
        sys.path.insert(0, src_path)


def pp(title: str, payload: dict[str, Any], *, max_len: int = 1200) -> None:
    print(f"\n--- {title} ---")
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=str)[:max_len])


def demo_space_ids(prefix: str) -> dict[str, str]:
    if not prefix:
        return {
            "coding": "coding:demo-app",
            "chat": "chat:daily",
            "study": "study:ml-notes",
        }
    return {
        "coding": f"coding:{prefix}-app",
        "chat": f"chat:{prefix}-daily",
        "study": f"study:{prefix}-ml-notes",
    }


def auth_headers(api_key: str) -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
        headers["X-API-Key"] = api_key
    return headers


def utc_now_iso(*, offset_minutes: int = 0) -> str:
    return (datetime.now(timezone.utc) + timedelta(minutes=offset_minutes)).isoformat()


def new_message_id() -> str:
    return f"msg_{uuid4().hex[:8]}"


def searchable_result_rows(result: dict[str, Any]) -> list[dict[str, Any]]:
    rows = result.get("results", []) if isinstance(result, dict) else []
    if not isinstance(rows, list):
        return []

    filtered: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        stability = row.get("stability")
        if isinstance(stability, str) and stability != "searchable":
            continue
        filtered.append(row)
    return filtered


def has_searchable_rows(result: dict[str, Any]) -> bool:
    return bool(searchable_result_rows(result))


def flatten_search_memories(result: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    """Normalize search memories from flat or grouped response shapes."""
    flattened: list[tuple[str, dict[str, Any]]] = []
    memories = result.get("memories", []) if isinstance(result, dict) else []
    if not isinstance(memories, list):
        return flattened

    valid_types = {"profile", "episodic_memory", "foresight", "event_log"}
    for entry in memories:
        if not isinstance(entry, dict):
            continue

        grouped_found = False
        for memory_type in valid_types:
            grouped_items = entry.get(memory_type)
            if not isinstance(grouped_items, list):
                continue
            grouped_found = True
            for item in grouped_items:
                if isinstance(item, dict):
                    flattened.append((memory_type, item))

        if grouped_found:
            continue

        memory_type = entry.get("memory_type", "unknown")
        flattened.append((str(memory_type), entry))

    return flattened
