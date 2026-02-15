"""MCP Server entry point for evermemos-mcp.

Registers 5 tools and runs over stdio transport.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

import mcp.server.stdio
from mcp import types
from mcp.server.lowlevel import NotificationOptions, Server
from mcp.server.models import InitializationOptions

from . import __version__
from .evermemos_client import EverMemosClient, EverMemosError
from .memory_service import MemoryService
from .space_catalog_service import SpaceCatalogService

logger = logging.getLogger(__name__)

server = Server("evermemos-mcp")

# Module-level service — set in main() before server.run()
_svc: MemoryService | None = None


def _require_service() -> MemoryService:
    if _svc is None:
        raise EverMemosError(
            "MemoryService is not initialized",
            code="CONFIG_ERROR",
        )
    return _svc


# ---------------------------------------------------------------------------
# Tool definitions
# ---------------------------------------------------------------------------

TOOLS: list[types.Tool] = [
    types.Tool(
        name="list_spaces",
        description=(
            "List available memory spaces. Call this first to discover "
            "which space_id to use with other memory tools. "
            "Each space isolates memories by topic (e.g. coding:my-app, chat:daily)."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Optional keyword to filter spaces",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max number of spaces to return",
                    "default": 20,
                },
            },
        },
    ),
    types.Tool(
        name="remember",
        description=(
            "Store information in long-term memory within a specific space. "
            "The content is queued for extraction and may take a few minutes "
            "to become searchable via recall. "
            "Provide a description when creating a new space for the first time."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "content": {
                    "type": "string",
                    "description": "The information to remember",
                },
                "space_id": {
                    "type": "string",
                    "description": (
                        "Target memory space in <domain>:<slug> format "
                        "(e.g. coding:my-app, chat:daily, study:ml)"
                    ),
                },
                "description": {
                    "type": "string",
                    "description": (
                        "Human-readable description of this space "
                        "(recommended when creating a new space)"
                    ),
                },
                "sender": {
                    "type": "string",
                    "description": "Who is speaking: 'user' or 'assistant'",
                    "default": "user",
                },
                "flush": {
                    "type": "boolean",
                    "description": "Signal end of a conversation segment",
                    "default": True,
                },
                "include_status": {
                    "type": "boolean",
                    "description": (
                        "Whether to also query request status once after queuing "
                        "the memory write"
                    ),
                    "default": False,
                },
            },
            "required": ["content", "space_id"],
        },
    ),
    types.Tool(
        name="recall",
        description=(
            "Search for relevant memories in a specific space. "
            "Returns matching memories with source citations "
            "(type, snippet, timestamp, relevance score). "
            "Also reports how many messages are still being processed."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "What to search for",
                },
                "space_id": {
                    "type": "string",
                    "description": "Memory space to search",
                },
                "top_k": {
                    "type": "integer",
                    "description": "Max number of results (1-50)",
                    "minimum": 1,
                    "maximum": 50,
                    "default": 10,
                },
                "retrieve_method": {
                    "type": "string",
                    "description": (
                        "Search strategy. "
                        "auto runs hybrid+keyword in parallel and merges results"
                    ),
                    "enum": ["keyword", "hybrid", "vector", "rrf", "agentic", "auto"],
                    "default": "hybrid",
                },
                "start_time": {
                    "type": "string",
                    "description": (
                        "ISO 8601 start time with timezone "
                        "(e.g. 2024-01-01T00:00:00+00:00, naive values default to UTC). "
                        "For search results, this only filters episodic_memory items."
                    ),
                },
                "end_time": {
                    "type": "string",
                    "description": (
                        "ISO 8601 end time with timezone (naive values default to UTC). "
                        "For search results, this only filters episodic_memory items."
                    ),
                },
                "current_time": {
                    "type": "string",
                    "description": (
                        "ISO 8601 current time with timezone for foresight relevance filtering"
                    ),
                },
                "radius": {
                    "type": "number",
                    "description": (
                        "Cosine similarity threshold (0-1). "
                        "Effective for vector and hybrid retrieval, default from upstream is 0.6"
                    ),
                },
                "include_metadata": {
                    "type": "boolean",
                    "description": "Whether to include memory metadata in results",
                    "default": False,
                },
                "memory_types": {
                    "type": "array",
                    "description": (
                        "Optional memory type filter override. "
                        "Allowed: profile, episodic_memory, foresight, event_log. "
                        "For hybrid/rrf/agentic retrieval, only profile and "
                        "episodic_memory are supported. "
                        "For auto retrieval, this filter applies to keyword "
                        "and hybrid uses the profile/episodic subset."
                    ),
                    "items": {
                        "type": "string",
                        "enum": [
                            "profile",
                            "episodic_memory",
                            "foresight",
                            "event_log",
                        ],
                    },
                },
            },
            "required": ["query", "space_id"],
        },
    ),
    types.Tool(
        name="briefing",
        description=(
            "Get a contextual briefing for a memory space. "
            "Returns the user profile, recent episodes, key facts, and future foresights "
            "to quickly restore context at the start of a session."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "space_id": {
                    "type": "string",
                    "description": "Memory space to summarise",
                },
                "max_items": {
                    "type": "integer",
                    "description": "Max items per section",
                    "default": 8,
                },
                "start_time": {
                    "type": "string",
                    "description": (
                        "ISO 8601 start time for filtering "
                        "(naive values default to UTC)"
                    ),
                },
                "end_time": {
                    "type": "string",
                    "description": (
                        "ISO 8601 end time for filtering (naive values default to UTC)"
                    ),
                },
            },
            "required": ["space_id"],
        },
    ),
    types.Tool(
        name="forget",
        description=(
            "Delete specific memories by their IDs. "
            "Use recall first to find the memory_id values you want to remove. "
            "Deletion is permanent."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "memory_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "IDs of memories to delete (from recall results)",
                },
                "space_id": {
                    "type": "string",
                    "description": "Memory space containing the memories",
                },
                "reason": {
                    "type": "string",
                    "description": "Optional reason for deletion",
                },
            },
            "required": ["memory_ids", "space_id"],
        },
    ),
]

# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------


@server.list_tools()
async def handle_list_tools() -> list[types.Tool]:
    return TOOLS


@server.call_tool()
async def handle_call_tool(
    name: str, arguments: dict[str, Any]
) -> list[types.TextContent]:
    try:
        result = await _dispatch(name, arguments)
    except EverMemosError as exc:
        result = {"ok": False, "error": exc.code, "message": str(exc)}
    except (KeyError, TypeError, ValueError) as exc:
        result = {"ok": False, "error": "INVALID_INPUT", "message": str(exc)}

    return [types.TextContent(type="text", text=_to_json(result))]


async def _dispatch(name: str, args: dict[str, Any]) -> dict:
    svc = _require_service()

    if name == "list_spaces":
        return await svc.list_spaces(
            query=args.get("query"),
            limit=args.get("limit", 20),
        )

    if name == "remember":
        return await svc.remember(
            space_id=args["space_id"],
            content=args["content"],
            description=args.get("description"),
            sender=args.get("sender", "user"),
            flush=args.get("flush", True),
            include_status=args.get("include_status", False),
        )

    if name == "recall":
        return await svc.recall(
            query=args["query"],
            space_id=args["space_id"],
            top_k=args.get("top_k", 10),
            retrieve_method=args.get("retrieve_method", "hybrid"),
            start_time=args.get("start_time"),
            end_time=args.get("end_time"),
            current_time=args.get("current_time"),
            radius=args.get("radius"),
            include_metadata=args.get("include_metadata", False),
            memory_types=args.get("memory_types"),
        )

    if name == "briefing":
        return await svc.briefing(
            space_id=args["space_id"],
            max_items=args.get("max_items", 8),
            start_time=args.get("start_time"),
            end_time=args.get("end_time"),
        )

    if name == "forget":
        return await svc.forget(
            memory_ids=args["memory_ids"],
            space_id=args["space_id"],
            reason=args.get("reason"),
        )

    return {"ok": False, "error": "UNKNOWN_TOOL", "message": f"No tool named '{name}'"}


def _to_json(data: dict) -> str:
    return json.dumps(data, ensure_ascii=False, default=str)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


async def _run() -> None:
    global _svc

    async with EverMemosClient() as client:
        catalog = SpaceCatalogService(client)
        _svc = MemoryService(client, catalog)

        try:
            async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
                await server.run(
                    read_stream,
                    write_stream,
                    InitializationOptions(
                        server_name="evermemos-mcp",
                        server_version=__version__,
                        capabilities=server.get_capabilities(
                            notification_options=NotificationOptions(),
                            experimental_capabilities={},
                        ),
                    ),
                )
        finally:
            _svc = None


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    asyncio.run(_run())


if __name__ == "__main__":
    main()
