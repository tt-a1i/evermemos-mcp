"""Preload demo memories and optionally wait until searchable.

Usage:
  uv run python scripts/demo_preload.py --wait
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time

sys.path.insert(0, "src")

from evermemos_mcp.evermemos_client import EverMemosClient
from evermemos_mcp.memory_service import MemoryService
from evermemos_mcp.space_catalog_service import SpaceCatalogService


def _pp(title: str, payload: dict) -> None:
    print(f"\n--- {title} ---")
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=str)[:1200])


def _space_ids(prefix: str) -> dict[str, str]:
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


DEMO_DATA = {
    "coding": {
        "description": "Demo coding workspace (FastAPI + PostgreSQL + Redis)",
        "query": "FastAPI PostgreSQL Redis architecture",
        "messages": [
            "Project stack: FastAPI + PostgreSQL + SQLAlchemy 2.0 async + Redis cache.",
            "Architecture decision: keep domain services pure, adapters at boundary.",
            "Coding rules: ruff + black, strict typing, no hidden magic defaults.",
        ],
    },
    "chat": {
        "description": "Demo daily chat memory for personal preferences",
        "query": "coffee preference morning routine",
        "messages": [
            "I prefer hand-drip coffee in the morning and avoid sugary drinks.",
            "I like concise answers with clear next steps, not long essays.",
            "If a plan has trade-offs, call out risks first before recommendations.",
        ],
    },
    "study": {
        "description": "Demo study memory for machine learning notes",
        "query": "bias variance overfitting regularization",
        "messages": [
            "Bias-variance tradeoff: high bias underfits, high variance overfits.",
            "Regularization options: L2, dropout, early stopping.",
            "Current weak point: choosing validation strategy for small datasets.",
        ],
    },
}


async def preload(svc: MemoryService, ids: dict[str, str]) -> None:
    for domain, space_id in ids.items():
        spec = DEMO_DATA[domain]
        print(f"\n=== preload {space_id} ===")
        for idx, content in enumerate(spec["messages"]):
            result = await svc.remember(
                space_id,
                content,
                description=spec["description"] if idx == 0 else None,
                sender="user",
                flush=True,
            )
            print(
                f"[{idx + 1}/{len(spec['messages'])}] queued message_id={result.get('message_id', '')}"
            )
            await asyncio.sleep(0.2)


async def wait_until_ready(
    svc: MemoryService,
    ids: dict[str, str],
    timeout: int,
    interval: int,
) -> bool:
    start = time.monotonic()
    pending_domains = set(ids.keys())

    while pending_domains and (time.monotonic() - start) < timeout:
        elapsed = int(time.monotonic() - start)
        print(f"\n=== readiness check t+{elapsed}s ===")

        for domain in list(pending_domains):
            space_id = ids[domain]
            query = DEMO_DATA[domain]["query"]
            result = await svc.recall(query=query, space_id=space_id, top_k=3)
            count = len(result.get("results", []))
            pending = result.get("pending_count", 0)
            print(f"{space_id}: results={count} pending={pending}")
            if count > 0:
                pending_domains.remove(domain)

        if pending_domains:
            await asyncio.sleep(interval)

    if pending_domains:
        print(f"\nNot fully ready within timeout. Remaining: {sorted(pending_domains)}")
        return False

    print("\nAll demo spaces are searchable.")
    return True


async def main() -> int:
    parser = argparse.ArgumentParser(description="Preload EverMemOS demo memories")
    parser.add_argument(
        "--wait",
        action="store_true",
        help="Poll recall until memories are searchable",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=480,
        help="Max seconds to wait when --wait is enabled",
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=20,
        help="Polling interval seconds when --wait is enabled",
    )
    parser.add_argument(
        "--prefix",
        type=str,
        default="",
        help="Optional slug prefix for space IDs",
    )
    args = parser.parse_args()

    ids = _space_ids(args.prefix.strip())
    _pp("Target spaces", ids)

    client = EverMemosClient()
    catalog = SpaceCatalogService(client)
    svc = MemoryService(client, catalog)

    try:
        await preload(svc, ids)
        if args.wait:
            ok = await wait_until_ready(svc, ids, args.timeout, args.interval)
            return 0 if ok else 1
        return 0
    finally:
        await client.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
