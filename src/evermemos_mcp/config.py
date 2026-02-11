"""Configuration for EverMemOS MCP Server."""

from __future__ import annotations

import os

from dotenv import load_dotenv

load_dotenv()

EVERMEMOS_BASE_URL = os.getenv("EVERMEMOS_BASE_URL", "https://api.evermind.ai")
EVERMEMOS_API_KEY = os.getenv("EVERMEMOS_API_KEY", "")
EVERMEMOS_API_VERSION = os.getenv("EVERMEMOS_API_VERSION", "v0")
EVERMEMOS_USER_ID = os.getenv("EVERMEMOS_USER_ID", "mcp-user")
EVERMEMOS_DEFAULT_SPACE = os.getenv("EVERMEMOS_SPACE_ID", "")

# Derived
EVERMEMOS_API_BASE = f"{EVERMEMOS_BASE_URL}/api/{EVERMEMOS_API_VERSION}"

# Reserved group_id for space catalog metadata
CATALOG_GROUP_ID = "space::catalog"

# Prefix for user-facing space group_ids
SPACE_GROUP_PREFIX = "space::"
