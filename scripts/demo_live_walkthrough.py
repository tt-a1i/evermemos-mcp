"""Live demo walkthrough using preloaded spaces.

Usage:
  uv run python scripts/demo_live_walkthrough.py
  uv run python scripts/demo_live_walkthrough.py --do-forget
"""

# ruff: noqa: E402

from __future__ import annotations

import argparse
import asyncio
import importlib.util
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
pp = common.pp
searchable_result_rows = common.searchable_result_rows

add_project_src_to_path()

from evermemos_mcp.evermemos_client import EverMemosClient
from evermemos_mcp.memory_service import MemoryService
from evermemos_mcp.space_catalog_service import SpaceCatalogService


QUERIES = {
    "coding": "FastAPI PostgreSQL architecture decision",
    "chat": "morning coffee preference",
    "study": "bias variance regularization",
}


async def _pick_forget_memory_id(
    svc: MemoryService, space_id: str, rows: list[dict]
) -> str:
    target = next(
        (
            row
            for row in rows
            if isinstance(row, dict) and str(row.get("memory_id", "")).strip()
        ),
        None,
    )
    if isinstance(target, dict):
        return str(target.get("memory_id", "")).strip()

    history = await svc.fetch_history(
        space_id,
        memory_type="episodic_memory",
        limit=20,
        offset=0,
    )
    for item in history.get("items", []):
        if isinstance(item, dict):
            memory_id = str(item.get("memory_id", "")).strip()
            if memory_id:
                return memory_id

    return ""


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
            coding_results = searchable_result_rows(recall_results.get("coding", {}))
            if not coding_results:
                print(
                    "\nNo searchable recall results found in coding space; skip forget demo."
                )
            else:
                memory_id = await _pick_forget_memory_id(
                    svc, ids["coding"], coding_results
                )
                if not memory_id:
                    print(
                        "\nNo deletable memory_id found in recall/history; skip forget demo."
                    )
                else:
                    forget_result = await svc.forget(
                        memory_ids=[memory_id],
                        space_id=ids["coding"],
                        reason="demo cleanup",
                    )
                    pp("forget", forget_result, max_len=1400)
                    verify_history = await svc.fetch_history(
                        space_id=ids["coding"],
                        memory_type="episodic_memory",
                        limit=10,
                        offset=0,
                    )
                    pp("history_after_forget", verify_history, max_len=1400)
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
