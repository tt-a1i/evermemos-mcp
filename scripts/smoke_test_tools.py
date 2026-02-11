"""End-to-end smoke test: exercise all 5 tools against Cloud v0."""

import asyncio
import json
import sys
from uuid import uuid4

sys.path.insert(0, "src")

from evermemos_mcp.evermemos_client import EverMemosClient
from evermemos_mcp.memory_service import MemoryService
from evermemos_mcp.space_catalog_service import SpaceCatalogService


def pp(label: str, data: dict) -> None:
    print(f"\n--- {label} ---")
    print(json.dumps(data, indent=2, ensure_ascii=False, default=str)[:800])


async def main():
    client = EverMemosClient()
    catalog = SpaceCatalogService(client)
    svc = MemoryService(client, catalog)

    tag = uuid4().hex[:6]
    sid = f"test:smoke-{tag}"
    print(f"=== E2E smoke test (space: {sid}) ===")

    # 1. list_spaces (empty)
    r = await svc.list_spaces()
    pp("list_spaces (initial)", r)

    # 2. remember (creates space)
    r = await svc.remember(
        sid,
        "We use FastAPI with PostgreSQL. Redis for caching. uv as package manager.",
        description="Smoke test project",
    )
    pp("remember", r)
    assert r["ok"], f"remember failed: {r}"

    # 3. list_spaces (should show the space now)
    r = await svc.list_spaces()
    pp("list_spaces (after remember)", r)
    assert len(r["spaces"]) >= 1

    # 4. recall (likely empty — extraction takes minutes)
    r = await svc.recall("FastAPI PostgreSQL", sid)
    pp("recall", r)
    assert r["ok"]

    # 5. briefing (likely empty for new space)
    r = await svc.briefing(sid)
    pp("briefing", r)
    assert r["ok"]

    # 6. recall on pre-existing space with real data
    old_space = "test::validate-a-160de9"
    print(f"\n--- recall on old space ({old_space}) ---")
    try:
        r = await svc.recall("React TypeScript", old_space)
        pp("recall (old space)", r)
    except Exception as e:
        print(f"  skipped: {e}")

    # 7. forget (use a fake ID — expect error or 0 deleted)
    r = await svc.forget(["nonexistent-id"], sid)
    pp("forget (fake ID)", r)

    await client.close()
    print("\n=== Smoke test complete ===")


if __name__ == "__main__":
    asyncio.run(main())
