"""Preload demo memories and optionally wait until searchable.

Usage:
  uv run python scripts/demo_preload.py --wait --check-status
"""

# ruff: noqa: E402

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import time
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
_COMMON_SPEC = importlib.util.spec_from_file_location(
    "evermemos_scripts_common",
    SCRIPTS_DIR / "common.py",
)
if _COMMON_SPEC is None or _COMMON_SPEC.loader is None:
    raise RuntimeError("Unable to load scripts/common.py")
common = importlib.util.module_from_spec(_COMMON_SPEC)
_COMMON_SPEC.loader.exec_module(common)

add_project_src_to_path = common.add_project_src_to_path
demo_space_ids = common.demo_space_ids
has_searchable_rows = common.has_searchable_rows
pp = common.pp

add_project_src_to_path()

from evermemos_mcp.evermemos_client import EverMemosClient
from evermemos_mcp.memory_service import MemoryService
from evermemos_mcp.space_catalog_service import SpaceCatalogService


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


async def preload(
    svc: MemoryService,
    ids: dict[str, str],
    *,
    check_status: bool = False,
) -> None:
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
                include_status=check_status,
            )
            print(
                f"[{idx + 1}/{len(spec['messages'])}] queued message_id={result.get('message_id', '')}"
            )
            if check_status and result.get("request_status"):
                rs = result["request_status"]
                status = (
                    (rs.get("data") or {}).get("status")
                    if isinstance(rs.get("data"), dict)
                    else ""
                )
                lifecycle_state = (
                    (rs.get("lifecycle") or {}).get("state")
                    if isinstance(rs.get("lifecycle"), dict)
                    else ""
                )
                print(
                    "    status_check: "
                    f"success={rs.get('success')} found={rs.get('found')} "
                    f"status={status} lifecycle={lifecycle_state}"
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
            total_count = len(result.get("results", []))
            searchable_count = len(common.searchable_result_rows(result))
            pending = result.get("pending_count", 0)
            lifecycle_state = (
                (result.get("lifecycle") or {}).get("state")
                if isinstance(result.get("lifecycle"), dict)
                else ""
            )
            print(
                f"{space_id}: results={total_count} searchable={searchable_count} "
                f"pending={pending} lifecycle={lifecycle_state}"
            )
            if has_searchable_rows(result):
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
    parser.add_argument(
        "--check-status",
        action="store_true",
        help="Call request status once after each remember",
    )
    args = parser.parse_args()

    ids = demo_space_ids(args.prefix.strip())
    pp("Target spaces", ids)

    async with EverMemosClient() as client:
        catalog = SpaceCatalogService(client)
        svc = MemoryService(client, catalog)
        await preload(svc, ids, check_status=args.check_status)
        if args.wait:
            ok = await wait_until_ready(svc, ids, args.timeout, args.interval)
            return 0 if ok else 1
        return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
