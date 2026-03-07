"""MCP Server entry point for evermemos-mcp.

Registers 7 tools and runs over stdio transport.
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

from . import __version__, config
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


def _resolve_space_id(args: dict[str, Any] | None, required: bool = True) -> str | None:
    """Resolve space_id from args, falling back to auto-detected default."""
    space_id = args.get("space_id") if args else None
    if space_id:
        return space_id
    default = config.EVERMEMOS_DEFAULT_SPACE
    if default:
        return default
    if required:
        raise EverMemosError(
            "space_id is required (no auto-detected default available — "
            "set EVERMEMOS_DEFAULT_SPACE or run inside a git repo)",
            code="INVALID_INPUT",
        )
    return None


# ---------------------------------------------------------------------------
# Tool definitions
# ---------------------------------------------------------------------------

TOOLS: list[types.Tool] = [
    types.Tool(
        name="list_spaces",
        description=(
            "List available memory spaces. Call this first to discover "
            "which space_id values exist before using other memory tools. "
            "Each space isolates memories by project or topic "
            "(e.g. coding:my-app, study:ml-notes, chat:preferences). "
            "If no spaces exist yet, create one by calling remember with a new space_id and description."
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
            "Use this proactively to save architecture decisions, user preferences, "
            "project conventions, bug solutions, and key context. "
            "Content is queued for AI extraction and becomes searchable via recall "
            "after a few minutes. "
            "Set flush=true at end of session or topic switch; flush=false during ongoing work. "
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
                        "(e.g. coding:my-app, chat:daily, study:ml). "
                        "If omitted, auto-detected from git remote (coding:<repo-name>)."
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
                    "description": (
                        "Backward-compatible alias. "
                        "Use 'user'/'assistant' as role alias, or pass a sender user_id"
                    ),
                    "default": "user",
                },
                "user_id": {
                    "type": "string",
                    "description": "Optional sender user_id override (API sender field)",
                },
                "role": {
                    "type": "string",
                    "description": "Message role: 'user' or 'assistant'",
                    "enum": ["user", "assistant"],
                },
                "flush": {
                    "type": "boolean",
                    "description": (
                        "Whether to force immediate boundary detection/extraction. "
                        "Default false allows natural boundary detection"
                    ),
                    "default": False,
                },
                "refer_list": {
                    "type": "array",
                    "description": "Optional referenced message ID list",
                    "items": {"type": "string"},
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
            "required": ["content"],
        },
    ),
    types.Tool(
        name="request_status",
        description=(
            "Check the async processing status for a prior remember request. "
            "Use this when remember returned a request_id and you need to know "
            "whether extraction is still queued, processing, or completed."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "request_id": {
                    "type": "string",
                    "description": "Queued remember request_id returned by remember",
                }
            },
            "required": ["request_id"],
        },
    ),
    types.Tool(
        name="recall",
        description=(
            "Search for relevant memories in one or more spaces. "
            "Use this when you need context about prior decisions, preferences, "
            "conventions, or anything discussed in previous sessions. "
            "Returns matching memories with traceable citations "
            "(memory_type, snippet, timestamp, relevance score). "
            "Also reports pending_count — how many messages are still being extracted. "
            "If space_id and space_ids are both omitted, auto-detected from git remote (coding:<repo-name>)."
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
                    "description": "Single memory space to search",
                },
                "space_ids": {
                    "type": "array",
                    "description": (
                        "Optional multi-space search scope (max 10 unique). "
                        "Can be used alone or together with space_id."
                    ),
                    "items": {"type": "string"},
                },
                "top_k": {
                    "type": "integer",
                    "description": "Max number of results (-1 means all, capped by upstream at 100)",
                    "minimum": -1,
                    "maximum": 100,
                    "default": 10,
                },
                "retrieve_method": {
                    "type": "string",
                    "description": (
                        "Search strategy. "
                        "auto is an MCP-layer strategy that runs hybrid+keyword "
                        "in parallel and merges results"
                    ),
                    "enum": ["keyword", "hybrid", "vector", "rrf", "agentic", "auto"],
                    "default": "hybrid",
                },
                "user_id": {
                    "type": "string",
                    "description": "Optional user ID to filter memories. Defaults to the MCP client's identity.",
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
                        "ISO 8601 current time with timezone for upstream relevance filtering"
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
                        "Cloud search currently supports: profile and "
                        "episodic_memory."
                    ),
                    "items": {
                        "type": "string",
                        "enum": [
                            "profile",
                            "episodic_memory",
                        ],
                    },
                },
            },
            "required": ["query"],
        },
    ),
    types.Tool(
        name="briefing",
        description=(
            "Get a structured context briefing for a memory space. "
            "Call this at the start of every new session to restore context. "
            "Returns: user profile, recent episodes, key facts, and foresights. "
            "This is the fastest way to catch up on everything stored in a space."
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
                "user_id": {
                    "type": "string",
                    "description": "Optional user ID to filter memories. Defaults to the MCP client's identity.",
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
            "Delete specific memories by their IDs (permanent). "
            "Use recall first to find the memory_id values you want to remove. "
            "Useful for correcting outdated or incorrect memories."
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
                "user_id": {
                    "type": "string",
                    "description": (
                        "Optional user ID scope for delete. "
                        "Defaults to the MCP client's identity."
                    ),
                },
            },
            "required": ["memory_ids", "space_id"],
        },
    ),
    types.Tool(
        name="fetch_history",
        description=(
            "Page through historical memories in a space by memory_type. "
            "Useful for chronological timeline review when recall's relevance ranking "
            "is not sufficient, or when you need to browse all memories of a type."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "space_id": {
                    "type": "string",
                    "description": "Memory space to fetch",
                },
                "memory_type": {
                    "type": "string",
                    "description": "Memory type to page through",
                    "enum": [
                        "profile",
                        "episodic_memory",
                        "foresight",
                        "event_log",
                    ],
                    "default": "episodic_memory",
                },
                "limit": {
                    "type": "integer",
                    "description": "Page size (1-100)",
                    "minimum": 1,
                    "maximum": 100,
                    "default": 50,
                },
                "offset": {
                    "type": "integer",
                    "description": "Pagination offset (0-based)",
                    "minimum": 0,
                    "default": 0,
                },
                "user_id": {
                    "type": "string",
                    "description": "Optional user ID to filter memories. Defaults to the MCP client's identity.",
                },
                "start_time": {
                    "type": "string",
                    "description": (
                        "ISO 8601 start time with timezone "
                        "(naive values default to UTC)"
                    ),
                },
                "end_time": {
                    "type": "string",
                    "description": (
                        "ISO 8601 end time with timezone (naive values default to UTC)"
                    ),
                },
                "include_metadata": {
                    "type": "boolean",
                    "description": "Whether to include metadata in each item",
                    "default": False,
                },
            },
            "required": ["space_id"],
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
        result = _diagnose_error(exc)
    except (KeyError, TypeError, ValueError) as exc:
        result = {"ok": False, "error": "INVALID_INPUT", "message": str(exc)}

    return [types.TextContent(type="text", text=_to_json(result))]


def _diagnose_error(exc: EverMemosError) -> dict:
    """Enrich error responses with actionable troubleshooting hints."""
    base: dict = {"ok": False, "error": exc.code, "message": str(exc)}
    if exc.code == "CONFIG_ERROR" and "API_KEY" in str(exc):
        base["hint"] = (
            "Set EVERMEMOS_API_KEY in your MCP client env config. "
            "Get a key at https://evermind.ai/"
        )
    elif exc.code == "UPSTREAM_UNAVAILABLE":
        base["hint"] = (
            "Cannot reach EverMemOS Cloud. Check your network connection "
            "and verify EVERMEMOS_BASE_URL is correct."
        )
    elif exc.status_code == 401:
        base["hint"] = (
            "API key is invalid or expired. "
            "Verify your EVERMEMOS_API_KEY at https://evermind.ai/"
        )
    elif exc.status_code == 429:
        base["hint"] = "Rate limited. Wait a moment and try again."
    return base


async def _dispatch(name: str, args: dict[str, Any]) -> dict:
    svc = _require_service()

    if name == "list_spaces":
        return await svc.list_spaces(
            query=args.get("query"),
            limit=args.get("limit", 20),
        )

    if name == "remember":
        remember_space_id = _resolve_space_id(args)
        if remember_space_id is None:
            raise EverMemosError(
                "space_id is required",
                code="INVALID_INPUT",
            )
        return await svc.remember(
            space_id=remember_space_id,
            content=args["content"],
            description=args.get("description"),
            sender=args.get("sender", "user"),
            user_id=args.get("user_id"),
            role=args.get("role"),
            flush=args.get("flush", False),
            refer_list=args.get("refer_list"),
            include_status=args.get("include_status", False),
        )

    if name == "request_status":
        return await svc.request_status(args["request_id"])

    if name == "recall":
        raw_space_id = args.get("space_id")
        raw_space_ids = args.get("space_ids")
        # Auto-fill default space only when no scope is provided at all
        if not raw_space_id and not raw_space_ids:
            raw_space_id = _resolve_space_id(args, required=False)
        return await svc.recall(
            query=args["query"],
            space_id=raw_space_id,
            space_ids=raw_space_ids,
            top_k=args.get("top_k", 10),
            retrieve_method=args.get("retrieve_method", "hybrid"),
            start_time=args.get("start_time"),
            end_time=args.get("end_time"),
            current_time=args.get("current_time"),
            radius=args.get("radius"),
            include_metadata=args.get("include_metadata", False),
            memory_types=args.get("memory_types"),
            user_id=args.get("user_id"),
        )

    if name == "briefing":
        return await svc.briefing(
            space_id=args["space_id"],
            max_items=args.get("max_items", 8),
            start_time=args.get("start_time"),
            end_time=args.get("end_time"),
            user_id=args.get("user_id"),
        )

    if name == "forget":
        return await svc.forget(
            memory_ids=args["memory_ids"],
            space_id=args["space_id"],
            reason=args.get("reason"),
            user_id=args.get("user_id"),
        )

    if name == "fetch_history":
        return await svc.fetch_history(
            space_id=args["space_id"],
            memory_type=args.get("memory_type", "episodic_memory"),
            limit=args.get("limit", 50),
            offset=args.get("offset", 0),
            user_id=args.get("user_id"),
            start_time=args.get("start_time"),
            end_time=args.get("end_time"),
            include_metadata=args.get("include_metadata", False),
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
