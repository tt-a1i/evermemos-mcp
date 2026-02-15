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
