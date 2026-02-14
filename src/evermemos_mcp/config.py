"""Configuration for EverMemOS MCP Server."""

from __future__ import annotations

import json
import os

from dotenv import load_dotenv

load_dotenv()

EVERMEMOS_BASE_URL = os.getenv("EVERMEMOS_BASE_URL", "https://api.evermind.ai")
EVERMEMOS_API_KEY = os.getenv("EVERMEMOS_API_KEY", "")
EVERMEMOS_API_VERSION = os.getenv("EVERMEMOS_API_VERSION", "v0")
EVERMEMOS_USER_ID = os.getenv("EVERMEMOS_USER_ID", "mcp-user")
EVERMEMOS_DEFAULT_SPACE = os.getenv("EVERMEMOS_SPACE_ID", "")

# Conversation metadata integration (Cloud v0)
EVERMEMOS_ENABLE_CONVERSATION_META = os.getenv(
    "EVERMEMOS_ENABLE_CONVERSATION_META", "true"
).strip().lower() in {"1", "true", "yes", "on"}
EVERMEMOS_CONVERSATION_SCENE = (
    os.getenv(
        "EVERMEMOS_CONVERSATION_SCENE",
        "assistant",
    ).strip()
    or "assistant"
)

_LLM_CUSTOM_SETTING_RAW = os.getenv("EVERMEMOS_LLM_CUSTOM_SETTING_JSON", "").strip()
if _LLM_CUSTOM_SETTING_RAW:
    try:
        parsed = json.loads(_LLM_CUSTOM_SETTING_RAW)
        EVERMEMOS_LLM_CUSTOM_SETTING = parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        EVERMEMOS_LLM_CUSTOM_SETTING = None
else:
    EVERMEMOS_LLM_CUSTOM_SETTING = None

# Reserved group_id for space catalog metadata
CATALOG_GROUP_ID = "space::catalog"

# Prefix for user-facing space group_ids
SPACE_GROUP_PREFIX = "space::"
