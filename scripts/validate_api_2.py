"""Phase 3.1 Round 2: Deep validation.

1. Check if first run's spaces have memories now (minutes later)
2. Try setting conversation-meta before writing
3. Try different auth header formats
4. Send a longer conversation to force boundary detection
"""

import asyncio
import argparse
import json
import os
from uuid import uuid4

import httpx
from common import auth_headers, flatten_search_memories, new_message_id, utc_now_iso
from dotenv import load_dotenv

load_dotenv()

BASE_URL = os.getenv("EVERMEMOS_BASE_URL", "https://api.evermind.ai")
API_KEY = os.getenv("EVERMEMOS_API_KEY", "")
API_BASE = f"{BASE_URL}/api/v0"

# Optional: reuse a previous validation space (set via env/cli)
OLD_SPACE = os.getenv("EVERMEMOS_OLD_SPACE_ID", "").strip()
NEW_SPACE = f"test:conv-{uuid4().hex[:6]}"
USER_ID = "mcp-test-user"


async def check_old_space(client: httpx.AsyncClient):
    """Check if first run's memories have been processed."""
    if not OLD_SPACE:
        print(
            "\n=== Check old space: skipped (set EVERMEMOS_OLD_SPACE_ID to enable) ==="
        )
        return

    print(f"\n=== Check old space: {OLD_SPACE} ===")
    for mem_type in ["episodic_memory", "profile", "event_log"]:
        r = await client.request(
            "GET",
            f"{API_BASE}/memories",
            headers=auth_headers(API_KEY),
            json={
                "group_ids": [OLD_SPACE],
                "user_id": USER_ID,
                "memory_type": mem_type,
                "page": 1,
                "page_size": 5,
            },
            timeout=15,
        )
        data = r.json()
        memories = data.get("result", {}).get("memories", [])
        print(f"  {mem_type}: {len(memories)} memories")
        if memories:
            for m in memories[:2]:
                print(f"    → {str(m)[:150]}")

    # Also try search
    r = await client.request(
        "GET",
        f"{API_BASE}/memories/search",
        headers=auth_headers(API_KEY),
        json={
            "query": "React TypeScript",
            "group_ids": [OLD_SPACE],
            "user_id": USER_ID,
            "retrieve_method": "keyword",
            "top_k": 5,
        },
        timeout=15,
    )
    data = r.json()
    memories = data.get("result", {}).get("memories", [])
    pending = data.get("result", {}).get("pending_messages", [])
    print(f"  search: {len(memories)} groups, {len(pending)} pending")
    if pending:
        print(f"    pending msgs: {json.dumps(pending[:2], ensure_ascii=False)[:300]}")


async def setup_conversation_meta(client: httpx.AsyncClient, group_id: str):
    """Set up conversation metadata before writing messages."""
    print(f"\n=== Setup conversation-meta for {group_id} ===")
    payload = {
        "version": "1.0.0",
        "scene": "assistant",
        "scene_desc": {"description": "MCP memory test conversation", "type": "test"},
        "name": "API Validation Conversation",
        "description": "Testing memory extraction behavior",
        "group_id": group_id,
        "created_at": utc_now_iso(),
        "user_details": {
            USER_ID: {
                "full_name": "Test User",
                "role": "user",
            },
            "assistant": {
                "full_name": "AI Assistant",
                "role": "assistant",
            },
        },
    }
    r = await client.post(
        f"{API_BASE}/memories/conversation-meta",
        headers=auth_headers(API_KEY),
        json=payload,
        timeout=15,
    )
    print(f"  Status: {r.status_code}")
    print(f"  Response: {r.text[:300]}")
    return r.json()


async def send_long_conversation(client: httpx.AsyncClient, group_id: str):
    """Send a longer conversation to force boundary detection."""
    print(f"\n=== Send long conversation to {group_id} ===")
    conversation = [
        (
            "user",
            "I'm starting a new Python project for a REST API. What framework should I use?",
        ),
        (
            "assistant",
            "For a modern Python REST API, I'd recommend FastAPI. It's async-first, has great OpenAPI docs generation, and excellent type safety with Pydantic.",
        ),
        (
            "user",
            "Good choice. We'll use FastAPI. For the database, let's go with PostgreSQL and SQLAlchemy 2.0 with async support.",
        ),
        (
            "assistant",
            "Great stack choice. SQLAlchemy 2.0's async support with asyncpg works really well with FastAPI. Do you want to use Alembic for migrations?",
        ),
        (
            "user",
            "Yes, Alembic for migrations. Also, we need Redis for caching and Celery for background tasks.",
        ),
        (
            "assistant",
            "Noted. Your full stack: FastAPI + PostgreSQL + SQLAlchemy 2.0 + Alembic + Redis + Celery. That's a solid, production-ready setup.",
        ),
        (
            "user",
            "One more thing - we're using a monorepo structure with uv as the package manager. Code style: black + ruff.",
        ),
        (
            "assistant",
            "Perfect. I'll remember: monorepo with uv, formatting with black, linting with ruff. Any specific ruff rules or black line length?",
        ),
        (
            "user",
            "Line length 100, and enable all ruff rules except E501 since black handles line length.",
        ),
        (
            "assistant",
            "Got it: black --line-length 100, ruff with all rules except E501. This is a well-thought-out setup.",
        ),
    ]

    for i, (role, content) in enumerate(conversation):
        sender = USER_ID if role == "user" else "assistant"
        payload = {
            "message_id": new_message_id(),
            "create_time": utc_now_iso(offset_minutes=i),
            "sender": sender,
            "sender_name": "Test User" if role == "user" else "AI Assistant",
            "role": role,
            "content": content,
            "group_id": group_id,
            "group_name": "API Validation",
        }
        r = await client.post(
            f"{API_BASE}/memories",
            headers=auth_headers(API_KEY),
            json=payload,
            timeout=15,
        )
        status = r.json().get("status", "?")
        print(f"  [{i + 1}/10] {role}: {status} ({r.status_code})")
        await asyncio.sleep(0.5)

    # Send flush signal
    print("  Sending flush...")
    flush_payload = {
        "message_id": new_message_id(),
        "create_time": utc_now_iso(offset_minutes=11),
        "sender": USER_ID,
        "sender_name": "Test User",
        "role": "user",
        "content": "That's all for now, let's wrap up this discussion.",
        "group_id": group_id,
        "group_name": "API Validation",
        "flush": True,
    }
    r = await client.post(
        f"{API_BASE}/memories",
        headers=auth_headers(API_KEY),
        json=flush_payload,
        timeout=15,
    )
    print(f"  flush: {r.json().get('status', '?')} ({r.status_code})")


async def search_and_fetch(client: httpx.AsyncClient, group_id: str, wait: int):
    """Search and fetch after waiting."""
    print(f"\n=== Search & Fetch after {wait}s wait ({group_id}) ===")
    await asyncio.sleep(wait)

    # Search
    for method in ["keyword", "hybrid"]:
        r = await client.request(
            "GET",
            f"{API_BASE}/memories/search",
            headers=auth_headers(API_KEY),
            json={
                "query": "FastAPI PostgreSQL",
                "group_ids": [group_id],
                "user_id": USER_ID,
                "retrieve_method": method,
                "top_k": 5,
            },
            timeout=30,
        )
        data = r.json()
        memories = data.get("result", {}).get("memories", [])
        pending = data.get("result", {}).get("pending_messages", [])
        print(f"  {method}: {len(memories)} groups, {len(pending)} pending")
        flat_memories = flatten_search_memories(data.get("result", {}))
        if flat_memories:
            for mem_type, memory in flat_memories[:4]:
                snippet = (
                    memory.get("summary", "")
                    or memory.get("description", "")
                    or memory.get("content", "")
                )[:120]
                print(f"    [{mem_type}] {snippet}")

    # Fetch by type
    for mem_type in ["episodic_memory", "profile", "event_log"]:
        r = await client.request(
            "GET",
            f"{API_BASE}/memories",
            headers=auth_headers(API_KEY),
            json={
                "group_ids": [group_id],
                "user_id": USER_ID,
                "memory_type": mem_type,
                "page": 1,
                "page_size": 5,
            },
            timeout=15,
        )
        memories = r.json().get("result", {}).get("memories", [])
        count = len(memories)
        print(f"  fetch {mem_type}: {count}")
        if memories and count > 0:
            for m in memories[:2]:
                if isinstance(m, dict):
                    print(f"    → {str(m.get('summary', m.get('content', m)))[:150]}")


async def main():
    global OLD_SPACE

    parser = argparse.ArgumentParser(description="EverMemOS Cloud deep validation")
    parser.add_argument(
        "--old-space",
        type=str,
        default=OLD_SPACE,
        help="Optional existing group_id from a previous run",
    )
    args = parser.parse_args()
    OLD_SPACE = args.old_space.strip()

    print("EverMemOS Cloud API - Deep Validation")
    print(f"Base: {API_BASE}")
    if OLD_SPACE:
        print(f"Old space: {OLD_SPACE}")
    else:
        print("Old space: <not set>")
    print(f"New space: {NEW_SPACE}")

    async with httpx.AsyncClient() as client:
        # 1. Check old space
        await check_old_space(client)

        # 2. Setup meta + send long conversation
        await setup_conversation_meta(client, NEW_SPACE)
        await send_long_conversation(client, NEW_SPACE)

        # 3. Search immediately
        await search_and_fetch(client, NEW_SPACE, wait=5)

        # 4. Search after 30s
        await search_and_fetch(client, NEW_SPACE, wait=30)

        # 5. Search after another 30s (total ~65s)
        await search_and_fetch(client, NEW_SPACE, wait=30)

    print("\n=== Done ===")


if __name__ == "__main__":
    asyncio.run(main())
