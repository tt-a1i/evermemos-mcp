"""Optional integration tests for real EverMemOS APIs.

Run with:
  EVERMEMOS_RUN_INTEGRATION_TESTS=true uv run pytest -m integration
"""

from __future__ import annotations

import os
from uuid import uuid4

import pytest

from evermemos_mcp.evermemos_client import EverMemosClient
from evermemos_mcp.space_catalog_service import to_group_id


_RUN_INTEGRATION = os.getenv("EVERMEMOS_RUN_INTEGRATION_TESTS", "").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


def _skip_unless_enabled() -> None:
    if not _RUN_INTEGRATION:
        pytest.skip(
            "Integration tests are disabled (set EVERMEMOS_RUN_INTEGRATION_TESTS=true)"
        )
    if not os.getenv("EVERMEMOS_API_KEY", "").strip():
        pytest.skip("Integration tests require EVERMEMOS_API_KEY")


async def test_cloud_add_search_and_fetch_contracts() -> None:
    _skip_unless_enabled()

    async with EverMemosClient() as client:
        space_id = f"test:integration-{uuid4().hex[:8]}"
        group_id = to_group_id(space_id)

        add_res = await client.add_message(
            group_id=group_id,
            content="integration smoke: FastAPI + PostgreSQL",
            flush=True,
        )
        assert isinstance(add_res, dict)
        assert add_res.get("request_id") or add_res.get("message_id")

        search_res = await client.search_memories(
            "integration smoke",
            group_id,
            retrieve_method="keyword",
            top_k=3,
        )
        assert isinstance(search_res, dict)
        assert isinstance(search_res.get("result", {}), dict)

        fetch_res = await client.fetch_memories(
            group_id,
            memory_type="episodic_memory",
            limit=3,
        )
        assert isinstance(fetch_res, dict)
        assert isinstance(fetch_res.get("result", {}), dict)
