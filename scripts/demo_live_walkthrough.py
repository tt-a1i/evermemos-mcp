"""Live demo walkthrough using preloaded spaces.

Usage:
  uv run python scripts/demo_live_walkthrough.py
  uv run python scripts/demo_live_walkthrough.py --do-forget
"""

# ruff: noqa: E402

from __future__ import annotations

import argparse
import asyncio
from common import add_project_src_to_path, demo_space_ids, pp

add_project_src_to_path()

from evermemos_mcp.evermemos_client import EverMemosClient
from evermemos_mcp.memory_service import MemoryService
from evermemos_mcp.space_catalog_service import SpaceCatalogService


QUERIES = {
    "coding": "FastAPI PostgreSQL architecture decision",
    "chat": "morning coffee preference",
    "study": "bias variance regularization",
}


async def main() -> int:
    parser = argparse.ArgumentParser(description="Run live memory demo walkthrough")
    parser.add_argument(
        "--prefix",
        type=str,
        default="",
        help="Optional slug prefix for space IDs",
    )
    parser.add_argument(
        "--do-forget",
        action="store_true",
        help="Also demonstrate forget using one recalled memory ID",
    )
    args = parser.parse_args()

    ids = demo_space_ids(args.prefix.strip())

    async with EverMemosClient() as client:
        catalog = SpaceCatalogService(client)
        svc = MemoryService(client, catalog)

        pp("list_spaces", await svc.list_spaces(limit=20), max_len=1400)

        recall_results: dict[str, dict] = {}
        for domain, space_id in ids.items():
            result = await svc.recall(
                query=QUERIES[domain],
                space_id=space_id,
                top_k=5,
                retrieve_method="hybrid",
            )
            recall_results[domain] = result
            pp(f"recall:{space_id}", result, max_len=1400)

        briefing = await svc.briefing(space_id=ids["coding"], max_items=8)
        pp(f"briefing:{ids['coding']}", briefing, max_len=1400)

        if args.do_forget:
            coding_results = recall_results.get("coding", {}).get("results", [])
            if not coding_results:
                print("\nNo recall results found in coding space; skip forget demo.")
            else:
                memory_id = coding_results[0].get("memory_id", "")
                if not memory_id:
                    print("\nFirst recall result has no memory_id; skip forget demo.")
                else:
                    forget_result = await svc.forget(
                        memory_ids=[memory_id],
                        space_id=ids["coding"],
                        reason="demo cleanup",
                    )
                    pp("forget", forget_result, max_len=1400)
                    verify = await svc.recall(
                        query=QUERIES["coding"],
                        space_id=ids["coding"],
                        top_k=5,
                        retrieve_method="hybrid",
                    )
                    pp("recall_after_forget", verify, max_len=1400)

        return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
