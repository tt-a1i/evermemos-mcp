"""Phase 3.1: Validate EverMemOS API behavior.

Default: Cloud/local v1 (`EVERMEMOS_API_VERSION=v1`).
Set `EVERMEMOS_API_VERSION=v0` for legacy self-hosted v0 endpoints only.

Tests:
1. Connectivity & auth
2. Store single message → check response (extracted vs accumulated)
3. Store with flush=true → check if extraction is faster
4. Search immediately after store → can we find it?
5. Search with different group_id → isolation check
6. Fetch by memory_type (v1: episodic_memory, profile; v0 adds event_log, foresight)
"""

import asyncio
import json
import os
from datetime import datetime, timezone
from uuid import uuid4

import httpx
from common import auth_headers, flatten_search_memories, new_message_id, utc_now_iso
from dotenv import load_dotenv

load_dotenv()

BASE_URL = os.getenv("EVERMEMOS_BASE_URL", "http://localhost:8001")
API_KEY = os.getenv("EVERMEMOS_API_KEY", "")
API_VERSION = os.getenv("EVERMEMOS_API_VERSION", "v1")
USE_V0 = API_VERSION == "v0"

API_PATHS = {
    "v0": f"{BASE_URL}/api/v0",
    "v1": f"{BASE_URL}/api/v1",
}

_V1_FETCH_MEMORY_TYPES = ("episodic_memory", "profile")
_V1_UNSUPPORTED_FETCH_TYPES = frozenset({"event_log", "foresight"})
_V1_GET_RESPONSE_KEYS = {
    "episodic_memory": "episodes",
    "profile": "profiles",
    "agent_case": "agent_cases",
    "agent_skill": "agent_skills",
}
_V1_USER_SCOPED_FETCH_TYPES = frozenset({"profile", "agent_case", "agent_skill"})

SPACE_A = f"test:validate-a-{uuid4().hex[:6]}"
SPACE_B = f"test:validate-b-{uuid4().hex[:6]}"
USER_ID = "mcp-test-user"


def _iso_to_unix_ms(iso: str) -> int:
    dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)


def _unwrap_v1_data(body: dict) -> dict:
    data = body.get("data")
    return data if isinstance(data, dict) else body


def _v1_group_message(
    *,
    content: str,
    group_id: str,
    group_name: str,
    role: str = "user",
    sender: str = USER_ID,
    sender_name: str = "Test User",
) -> dict:
    create_time = utc_now_iso()
    return {
        "group_id": group_id,
        "messages": [
            {
                "role": role,
                "timestamp": _iso_to_unix_ms(create_time),
                "content": content,
                "sender_id": sender,
                "sender_name": sender_name,
                "message_id": new_message_id(),
            }
        ],
        "async_mode": True,
        "group_meta": {"name": group_name},
    }


async def _post_store(
    client: httpx.AsyncClient, api_base: str, payload: dict, *, flush: bool = False
):
    if USE_V0:
        v0_payload = dict(payload)
        v0_payload["flush"] = flush
        return await client.post(
            f"{api_base}/memories",
            headers=auth_headers(API_KEY),
            json=v0_payload,
            timeout=30,
        )

    group_id = payload["group_id"]
    v1_payload = _v1_group_message(
        content=payload["content"],
        group_id=group_id,
        group_name=payload.get("group_name", group_id),
        role=payload.get("role", "user"),
        sender=payload.get("sender", USER_ID),
        sender_name=payload.get("sender_name", "Test User"),
    )
    response = await client.post(
        f"{api_base}/memories/group",
        headers=auth_headers(API_KEY),
        json=v1_payload,
        timeout=30,
    )
    if flush and response.status_code < 400:
        await client.post(
            f"{api_base}/memories/group/flush",
            headers=auth_headers(API_KEY),
            json={"group_id": group_id},
            timeout=30,
        )
    return response


async def test_connectivity(client: httpx.AsyncClient, api_base: str):
    """Test 1: Check if API is reachable."""
    print("\n=== Test 1: Connectivity ===")
    try:
        r = await client.get(
            f"{BASE_URL}/health", headers=auth_headers(API_KEY), timeout=10
        )
        print(f"  /health: {r.status_code} {r.text[:200]}")
    except Exception as e:
        print(f"  /health: FAILED - {e}")

    try:
        if USE_V0:
            r = await client.request(
                "GET",
                f"{api_base}/memories",
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
            print(f"  v0 GET /memories: {r.status_code} {r.text[:300]}")
        else:
            r = await client.post(
                f"{api_base}/memories/get",
                headers=auth_headers(API_KEY),
                json={
                    "memory_type": "episodic_memory",
                    "filters": {"group_id": SPACE_A},
                    "page": 1,
                    "page_size": 1,
                },
                timeout=10,
            )
            print(f"  v1 POST /memories/get: {r.status_code} {r.text[:300]}")
    except Exception as e:
        print(f"  memories probe: FAILED - {e}")


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

    try:
        r = await _post_store(client, api_base, payload, flush=flush)
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
            r = await _post_store(client, api_base, msg, flush=False)
            body = r.json()
            if USE_V0:
                status_info = body.get("result", {}).get("status_info", "unknown")
            else:
                data = _unwrap_v1_data(body)
                status_info = data.get("status", body.get("status", "unknown"))
            print(f"  Message {i + 1}: {r.status_code} → {status_info}")
            results.append(body)
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

    try:
        if USE_V0:
            payload = {
                "query": query,
                "group_ids": [group_id],
                "user_id": USER_ID,
                "retrieve_method": method,
                "top_k": 5,
            }
            r = await client.request(
                "GET",
                f"{api_base}/memories/search",
                headers=auth_headers(API_KEY),
                json=payload,
                timeout=30,
            )
            data = r.json()
            result = data.get("result", {})
            memories = result.get("memories", [])
            pending = result.get("pending_messages", [])
            flat_memories = flatten_search_memories(result)
        else:
            r = await client.post(
                f"{api_base}/memories/search",
                headers=auth_headers(API_KEY),
                json={
                    "query": query,
                    "filters": {"group_id": group_id},
                    "method": method,
                    "top_k": 5,
                },
                timeout=30,
            )
            data = r.json()
            raw = _unwrap_v1_data(data)
            memories = []
            flat_memories = []
            for memory_type, key in _V1_GET_RESPONSE_KEYS.items():
                for item in raw.get(key) or []:
                    if isinstance(item, dict):
                        memories.append(item)
                        flat_memories.append((memory_type, item))
            pending = raw.get("unprocessed_messages") or raw.get("pending_messages") or []

        print(f"  Status: {r.status_code}")
        print(f"  Found: {len(memories)} memory groups, {len(pending)} pending")

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
    if not USE_V0 and memory_type in _V1_UNSUPPORTED_FETCH_TYPES:
        print(
            f"  SKIPPED: Cloud v1 /memories/get does not support memory_type '{memory_type}'"
        )
        return None
    try:
        if USE_V0:
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
        else:
            v1_key = _V1_GET_RESPONSE_KEYS.get(memory_type, memory_type)
            filters = {"group_id": group_id}
            if memory_type in _V1_USER_SCOPED_FETCH_TYPES:
                filters["user_id"] = USER_ID
            r = await client.post(
                f"{api_base}/memories/get",
                headers=auth_headers(API_KEY),
                json={
                    "memory_type": memory_type,
                    "filters": filters,
                    "page": 1,
                    "page_size": 5,
                },
                timeout=30,
            )
            data = r.json()
            raw = _unwrap_v1_data(data)
            memories = raw.get(v1_key, [])
            if not isinstance(memories, list):
                memories = []

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
    r = await _post_store(client, api_base, payload, flush=False)
    print(f"  Stored in SPACE_B: {r.status_code}")

    await asyncio.sleep(3)

    await test_search(
        client,
        api_base,
        "Vue.js Pinia",
        SPACE_A,
        "isolation: search A for B's content",
        "keyword",
    )

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
    print(f"API Version: {API_VERSION} ({'legacy v0' if USE_V0 else 'default v1'})")
    print(f"API Key: {'set' if API_KEY else 'NOT SET'}")
    print(f"Space A: {SPACE_A}")
    print(f"Space B: {SPACE_B}")

    api_base = API_PATHS.get(API_VERSION, API_PATHS["v1"])
    print(f"Using: {api_base}")

    async with httpx.AsyncClient() as client:
        await test_connectivity(client, api_base)
        await test_store_single(client, api_base, "no-flush", flush=False)
        await test_store_single(client, api_base, "flush", flush=True)
        await test_store_conversation(client, api_base)

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

        for mem_type in (
            ["episodic_memory", "profile", "foresight", "event_log"]
            if USE_V0
            else list(_V1_FETCH_MEMORY_TYPES)
        ):
            await test_fetch_by_type(client, api_base, mem_type, SPACE_A)

        await test_isolation(client, api_base)

    print("\n=== Validation Complete ===")


if __name__ == "__main__":
    asyncio.run(main())
