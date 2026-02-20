"""Configuration for EverMemOS MCP Server."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

_DOTENV_PATH = Path(__file__).resolve().parents[2] / ".env"
if _DOTENV_PATH.exists():
    load_dotenv(dotenv_path=_DOTENV_PATH, override=False)

EVERMEMOS_BASE_URL = os.getenv("EVERMEMOS_BASE_URL", "https://api.evermind.ai")
EVERMEMOS_API_KEY = os.getenv("EVERMEMOS_API_KEY", "")
EVERMEMOS_API_VERSION = os.getenv("EVERMEMOS_API_VERSION", "v0")
EVERMEMOS_USER_ID = os.getenv("EVERMEMOS_USER_ID", "mcp-user")

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
EVERMEMOS_DEFAULT_TIMEZONE = (
    os.getenv("EVERMEMOS_DEFAULT_TIMEZONE", "UTC").strip() or "UTC"
)

_LLM_CUSTOM_SETTING_RAW = os.getenv("EVERMEMOS_LLM_CUSTOM_SETTING_JSON", "").strip()
EVERMEMOS_LLM_CUSTOM_SETTING: dict[str, Any] | None
if _LLM_CUSTOM_SETTING_RAW:
    try:
        parsed = json.loads(_LLM_CUSTOM_SETTING_RAW)
        EVERMEMOS_LLM_CUSTOM_SETTING = parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        EVERMEMOS_LLM_CUSTOM_SETTING = None
else:
    EVERMEMOS_LLM_CUSTOM_SETTING = None

_USER_DETAILS_RAW = os.getenv("EVERMEMOS_USER_DETAILS_JSON", "").strip()
EVERMEMOS_USER_DETAILS: dict[str, dict[str, Any]] | None
if _USER_DETAILS_RAW:
    try:
        parsed_user_details = json.loads(_USER_DETAILS_RAW)
        EVERMEMOS_USER_DETAILS = (
            parsed_user_details if isinstance(parsed_user_details, dict) else None
        )
    except json.JSONDecodeError:
        EVERMEMOS_USER_DETAILS = None
else:
    EVERMEMOS_USER_DETAILS = None

# Reserved group_id for space catalog metadata
CATALOG_GROUP_ID = "space::catalog"

# Prefix for user-facing space group_ids
SPACE_GROUP_PREFIX = "space::"
