"""Smoke test for evermemos_client + space_catalog_service against Cloud v0."""

# ruff: noqa: E402

import asyncio
from uuid import uuid4

from common import add_project_src_to_path

add_project_src_to_path()

from evermemos_mcp.evermemos_client import EverMemosClient, EverMemosError
from evermemos_mcp.space_catalog_service import (
    SpaceCatalogService,
    to_group_id,
)


async def test_client():
    async with EverMemosClient() as client:
        tag = uuid4().hex[:6]
        space_id = f"test:smoke-{tag}"
        group_id = to_group_id(space_id)

        print("=== evermemos_client smoke test ===")
        print(f"Space: {space_id}  →  group_id: {group_id}")

        # 1. add_message
        print("\n--- add_message ---")
        r = await client.add_message(
            group_id=group_id,
            content="We use FastAPI with SQLAlchemy 2.0 for the backend. Redis for caching.",
            flush=True,
        )
        print(f"  status: {r.get('status')}")
        print(f"  request_id: {r.get('request_id', 'n/a')}")

        # 2. fetch_memories (empty — just wrote, extraction pending)
        print("\n--- fetch_memories (episodic_memory) ---")
        r = await client.fetch_memories(
            group_id, memory_type="episodic_memory", limit=5
        )
        memories = r.get("result", {}).get("memories", [])
        print(f"  found: {len(memories)} (expected 0 — extraction pending)")

        # 3. search_memories (keyword)
        print("\n--- search_memories (keyword) ---")
        r = await client.search_memories(
            "FastAPI SQLAlchemy", group_id, retrieve_method="keyword", top_k=5
        )
        res = r.get("result", {})
        mem_groups = res.get("memories", [])
        pending = res.get("pending_messages", [])
        print(f"  memory groups: {len(mem_groups)}")
        print(f"  pending messages: {len(pending)}")

        # 4. search_memories (hybrid)
        print("\n--- search_memories (hybrid) ---")
        r = await client.search_memories(
            "backend stack", group_id, retrieve_method="hybrid", top_k=3
        )
        res = r.get("result", {})
        print(f"  memory groups: {len(res.get('memories', []))}")
        print(f"  pending: {len(res.get('pending_messages', []))}")

    # 5. error: missing key
    print("\n--- error: no API key ---")
    async with EverMemosClient(api_key="") as bad_client:
        try:
            await bad_client.add_message("x", "y")
        except EverMemosError as e:
            print(f"  caught: {e.code} — {e}")

    print("\n✓ evermemos_client OK")


async def test_catalog():
    async with EverMemosClient() as client:
        catalog = SpaceCatalogService(client)

        print("\n=== space_catalog_service smoke test ===")

        # 1. register space
        tag = uuid4().hex[:6]
        sid = f"test:catalog-{tag}"
        print(f"\n--- register_space({sid}) ---")
        info = await catalog.register_space(sid, "Smoke test space for validation")
        print(f"  space_id: {info.space_id}")
        print(f"  description: {info.description}")
        print(f"  last_used_at: {info.last_used_at}")

        # 2. list_spaces (from cache)
        print("\n--- list_spaces() ---")
        spaces = await catalog.list_spaces()
        for s in spaces:
            print(f"  {s.space_id}: {s.description}")

        # 3. list_spaces with query
        print("\n--- list_spaces(query='catalog') ---")
        spaces = await catalog.list_spaces(query="catalog")
        print(f"  matched: {len(spaces)}")

        # 4. get_space
        print(f"\n--- get_space({sid}) ---")
        info = catalog.get_space(sid)
        print(f"  found: {info is not None}")

        # 5. ensure_space (no Cloud write)
        print("\n--- ensure_space('test:ephemeral') ---")
        info = catalog.ensure_space("test:ephemeral")
        print(f"  space_id: {info.space_id}")

        # 6. touch_space
        catalog.touch_space(sid)
        print(f"\n--- touch_space({sid}) ---")
        touched = catalog.get_space(sid)
        print(f"  last_used_at updated: {touched.last_used_at if touched else 'n/a'}")

    print("\n✓ space_catalog_service OK")


async def main():
    await test_client()
    await test_catalog()
    print("\n=== All smoke tests passed ===")


if __name__ == "__main__":
    asyncio.run(main())
