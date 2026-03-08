"""End-to-end smoke test: exercise all 7 tools against Cloud v0."""

# ruff: noqa: E402

import asyncio
from uuid import uuid4

from common import add_project_src_to_path, pp

add_project_src_to_path()

from evermemos_mcp.evermemos_client import EverMemosClient
from evermemos_mcp.memory_service import MemoryService
from evermemos_mcp.space_catalog_service import SpaceCatalogService


async def main():
    async with EverMemosClient() as client:
        catalog = SpaceCatalogService(client)
        svc = MemoryService(client, catalog)

        tag = uuid4().hex[:6]
        sid = f"test:smoke-{tag}"
        print(f"=== E2E smoke test (space: {sid}) ===")

        # 1. list_spaces (empty)
        r = await svc.list_spaces()
        pp("list_spaces (initial)", r, max_len=800)

        # 2. remember (creates space)
        r = await svc.remember(
            sid,
            "We use FastAPI with PostgreSQL. Redis for caching. uv as package manager.",
            description="Smoke test project",
            include_status=True,
        )
        pp("remember", r, max_len=800)
        assert r["ok"], f"remember failed: {r}"

        # 3. list_spaces (should show the space now)
        r = await svc.list_spaces()
        pp("list_spaces (after remember)", r, max_len=800)
        assert len(r["spaces"]) >= 1

        # 4. recall (likely empty — extraction takes minutes)
        r = await svc.recall("FastAPI PostgreSQL", sid)
        pp("recall", r, max_len=800)
        assert r["ok"]

        # 5. briefing (likely empty for new space)
        r = await svc.briefing(sid)
        pp("briefing", r, max_len=800)
        assert r["ok"]

        # 6. fetch_history (timeline-style pagination)
        r = await svc.fetch_history(
            sid, memory_type="episodic_memory", limit=5, offset=0
        )
        pp("fetch_history", r, max_len=800)
        assert r["ok"]

        # 7. forget (use a fake ID — expect error or 0 deleted)
        r = await svc.forget(["nonexistent-id"], sid)
        pp("forget (fake ID)", r, max_len=800)

    print("\n=== Smoke test complete ===")


if __name__ == "__main__":
    asyncio.run(main())
