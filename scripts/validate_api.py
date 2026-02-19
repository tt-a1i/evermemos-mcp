"""Phase 3.1: Validate EverMemOS API behavior.

Tests:
1. Connectivity & auth
2. Store single message → check response (extracted vs accumulated)
3. Store with flush=true → check if extraction is faster
4. Search immediately after store → can we find it?
5. Search with different group_id → isolation check
6. Fetch by memory_type (profile, episodic, foresight)
"""

import asyncio
import json
import os
from uuid import uuid4

import httpx
from common import auth_headers, flatten_search_memories, new_message_id, utc_now_iso
from dotenv import load_dotenv

load_dotenv()

BASE_URL = os.getenv("EVERMEMOS_BASE_URL", "http://localhost:8001")
API_KEY = os.getenv("EVERMEMOS_API_KEY", "")
API_VERSION = os.getenv("EVERMEMOS_API_VERSION", "v0")

# Try both v0 and v1
API_PATHS = {
    "v0": f"{BASE_URL}/api/v0",
    "v1": f"{BASE_URL}/api/v1",
}

SPACE_A = f"test:validate-a-{uuid4().hex[:6]}"
SPACE_B = f"test:validate-b-{uuid4().hex[:6]}"
USER_ID = "mcp-test-user"


async def test_connectivity(client: httpx.AsyncClient):
    """Test 1: Check if API is reachable."""
    print("\n=== Test 1: Connectivity ===")
    for version, base in API_PATHS.items():
        try:
            # Try health endpoint
            r = await client.get(
                f"{BASE_URL}/health", headers=auth_headers(API_KEY), timeout=10
            )
            print(f"  /health: {r.status_code} {r.text[:200]}")
        except Exception as e:
            print(f"  /health: FAILED - {e}")

        try:
            # Try memories endpoint with GET
            r = await client.request(
                "GET",
                f"{base}/memories",
                headers=auth_headers(API_KEY),
                json={
                    "group_ids": [SPACE_A],
                    "user_id": USER_ID,
                    "memory_type": "episodic_memory",
                    "page": 1,
                    "page_size": 1,
                },
                timeout=10,
            )
            print(f"  {version} GET /memories: {r.status_code} {r.text[:300]}")
        except Exception as e:
            print(f"  {version} GET /memories: FAILED - {e}")
        break  # Only test one version for connectivity


async def test_store_single(
    client: httpx.AsyncClient, api_base: str, label: str, flush: bool = False
):
    """Test 2/3: Store a single message and observe response."""
    print(f"\n=== Test: Store single message ({label}, flush={flush}) ===")
    payload: dict[str, object] = {
        "message_id": new_message_id(),
        "create_time": utc_now_iso(),
        "sender": USER_ID,
        "sender_name": "Test User",
        "role": "user",
        "content": f"[{label}] Our project uses React with TypeScript and Zustand for state management. We chose Zustand over Redux because of its simplicity.",
        "group_id": SPACE_A,
        "group_name": f"Test Space A ({label})",
    }
    payload["flush"] = flush

    try:
        r = await client.post(
            f"{api_base}/memories",
            headers=auth_headers(API_KEY),
            json=payload,
            timeout=30,
        )
        print(f"  Status: {r.status_code}")
        print(f"  Response: {json.dumps(r.json(), indent=2, ensure_ascii=False)[:500]}")
        return r.json()
    except Exception as e:
        print(f"  FAILED: {e}")
        return None


async def test_store_conversation(client: httpx.AsyncClient, api_base: str):
    """Test: Store a mini conversation (user + assistant) to trigger boundary."""
    print("\n=== Test: Store mini conversation (2 messages) ===")
    messages = [
        {
            "message_id": new_message_id(),
            "create_time": utc_now_iso(),
            "sender": USER_ID,
            "sender_name": "Test User",
            "role": "user",
            "content": "We decided to use PostgreSQL instead of MongoDB for the new project because we need strong ACID transactions.",
            "group_id": SPACE_A,
            "group_name": "Test Space A",
        },
        {
            "message_id": new_message_id(),
            "create_time": utc_now_iso(),
            "sender": "assistant",
            "sender_name": "AI Assistant",
            "role": "assistant",
            "content": "Got it. PostgreSQL for ACID compliance. I'll keep this in mind for future database-related discussions.",
            "group_id": SPACE_A,
            "group_name": "Test Space A",
        },
    ]

    results = []
    for i, msg in enumerate(messages):
        try:
            r = await client.post(
                f"{api_base}/memories",
                headers=auth_headers(API_KEY),
                json=msg,
                timeout=30,
            )
            print(
                f"  Message {i + 1}: {r.status_code} → {r.json().get('result', {}).get('status_info', 'unknown')}"
            )
            results.append(r.json())
        except Exception as e:
            print(f"  Message {i + 1}: FAILED - {e}")
            results.append(None)
    return results


async def test_search(
    client: httpx.AsyncClient,
    api_base: str,
    query: str,
    group_id: str,
    label: str,
    method: str = "hybrid",
):
    """Test: Search memories."""
    print(f"\n=== Test: Search ({label}) ===")
    print(f"  Query: {query}")
    print(f"  Group: {group_id}")
    print(f"  Method: {method}")

    payload = {
        "query": query,
        "group_ids": [group_id],
        "user_id": USER_ID,
        "retrieve_method": method,
        "top_k": 5,
    }

    try:
        # EverMemOS search uses GET with JSON body — use request() directly
        r = await client.request(
            "GET",
            f"{api_base}/memories/search",
            headers=auth_headers(API_KEY),
            json=payload,
            timeout=30,
        )
        data = r.json()
        print(f"  Status: {r.status_code}")

        result = data.get("result", {})
        memories = result.get("memories", [])
        pending = result.get("pending_messages", [])
        print(f"  Found: {len(memories)} memory groups, {len(pending)} pending")

        flat_memories = flatten_search_memories(result)
        if flat_memories:
            for mem_type, memory in flat_memories[:4]:
                snippet = (
                    memory.get("summary", "")
                    or memory.get("description", "")
                    or memory.get("content", "")
                )[:100]
                print(f"    [{mem_type}] {snippet}")

        return data
    except Exception as e:
        print(f"  FAILED: {e}")
        return None


async def test_fetch_by_type(
    client: httpx.AsyncClient, api_base: str, memory_type: str, group_id: str
):
    """Test: Fetch memories by type."""
    print(f"\n=== Test: Fetch {memory_type} from {group_id} ===")
    try:
        r = await client.request(
            "GET",
            f"{api_base}/memories",
            headers=auth_headers(API_KEY),
            json={
                "group_ids": [group_id],
                "user_id": USER_ID,
                "memory_type": memory_type,
                "page": 1,
                "page_size": 5,
            },
            timeout=30,
        )
        data = r.json()
        memories = data.get("result", {}).get("memories", [])
        print(f"  Status: {r.status_code}, Found: {len(memories)} memories")
        for m in memories[:2]:
            snippet = str(m.get("summary", m.get("content", m)))[:120]
            print(f"    {snippet}")
        return data
    except Exception as e:
        print(f"  FAILED: {e}")
        return None


async def test_isolation(client: httpx.AsyncClient, api_base: str):
    """Test: Verify space isolation."""
    print("\n=== Test: Space Isolation ===")
    # Store in SPACE_B
    payload = {
        "message_id": new_message_id(),
        "create_time": utc_now_iso(),
        "sender": USER_ID,
        "sender_name": "Test User",
        "role": "user",
        "content": "In Space B, we use Vue.js with Pinia. This is completely different from Space A.",
        "group_id": SPACE_B,
        "group_name": "Test Space B",
    }
    r = await client.post(
        f"{api_base}/memories",
        headers=auth_headers(API_KEY),
        json=payload,
        timeout=30,
    )
    print(f"  Stored in SPACE_B: {r.status_code}")

    await asyncio.sleep(3)

    # Search SPACE_A for Vue → should NOT find it
    await test_search(
        client,
        api_base,
        "Vue.js Pinia",
        SPACE_A,
        "isolation: search A for B's content",
        "keyword",
    )

    # Search SPACE_B for Vue → should find it
    await test_search(
        client,
        api_base,
        "Vue.js Pinia",
        SPACE_B,
        "isolation: search B for B's content",
        "keyword",
    )


async def main():
    print("EverMemOS API Validation")
    print(f"Base URL: {BASE_URL}")
    print(f"API Key: {'set' if API_KEY else 'NOT SET'}")
    print(f"Space A: {SPACE_A}")
    print(f"Space B: {SPACE_B}")

    api_base = API_PATHS[API_VERSION]
    print(f"Using: {api_base}")

    async with httpx.AsyncClient() as client:
        # 1. Connectivity
        await test_connectivity(client)

        # 2. Store single message (no flush)
        await test_store_single(client, api_base, "no-flush", flush=False)

        # 3. Store single message (flush=true)
        await test_store_single(client, api_base, "flush", flush=True)

        # 4. Store mini conversation
        await test_store_conversation(client, api_base)

        # 5. Wait and search (Cloud is async, needs more time)
        print("\n--- Waiting 30s for Cloud memory extraction ---")
        await asyncio.sleep(30)

        await test_search(
            client,
            api_base,
            "React TypeScript Zustand",
            SPACE_A,
            "after store",
            "keyword",
        )
        await test_search(
            client, api_base, "state management", SPACE_A, "semantic", "hybrid"
        )

        # 6. Fetch by type
        for mem_type in ["episodic_memory", "profile", "foresight", "event_log"]:
            await test_fetch_by_type(client, api_base, mem_type, SPACE_A)

        # 7. Isolation
        await test_isolation(client, api_base)

    print("\n=== Validation Complete ===")


if __name__ == "__main__":
    asyncio.run(main())
