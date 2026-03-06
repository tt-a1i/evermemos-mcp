"""Configuration for EverMemOS MCP Server."""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
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


def _get_positive_int_env(
    name: str,
    default: int,
    *,
    minimum: int = 1,
    maximum: int | None = None,
) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default

    text = raw.strip()
    if not text:
        return default

    try:
        value = int(text)
    except ValueError:
        return default

    if value < minimum:
        return minimum
    if maximum is not None and value > maximum:
        return maximum
    return value


EVERMEMOS_SOURCE_RECOVERY_PROBE_TOP_K = _get_positive_int_env(
    "EVERMEMOS_SOURCE_RECOVERY_PROBE_TOP_K",
    100,
    minimum=1,
    maximum=100,
)
EVERMEMOS_SOURCE_RECOVERY_PROBE_CONCURRENCY = _get_positive_int_env(
    "EVERMEMOS_SOURCE_RECOVERY_PROBE_CONCURRENCY",
    4,
    minimum=1,
    maximum=10,
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

_logger = logging.getLogger(__name__)

# Git remote URL patterns → repo name extraction
_GIT_REMOTE_RE = re.compile(
    r"(?:github\.com|gitlab\.com|bitbucket\.org)[:/]"
    r"[^/]+/([^/.]+?)(?:\.git)?$"
)


def _detect_git_repo_name() -> str | None:
    """Try to infer a repo name from git remote origin URL.

    Returns the repo slug (e.g. 'my-app') or None if detection fails.
    """
    try:
        result = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            capture_output=True,
            text=True,
            timeout=3,
        )
        if result.returncode != 0:
            return None
        url = result.stdout.strip()
        if not url:
            return None
        m = _GIT_REMOTE_RE.search(url)
        if m:
            return m.group(1)
        # Fallback: last path component
        basename = url.rstrip("/").rsplit("/", 1)[-1]
        if basename.endswith(".git"):
            basename = basename[:-4]
        return basename if basename else None
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return None


def _resolve_default_space() -> str | None:
    """Resolve a default space_id from env or git repo.

    Priority: EVERMEMOS_DEFAULT_SPACE env > git remote detection.
    """
    env_space = os.getenv("EVERMEMOS_DEFAULT_SPACE", "").strip()
    if env_space:
        return env_space

    repo = _detect_git_repo_name()
    if repo:
        space = f"coding:{repo}"
        _logger.debug("Auto-detected default space from git: %s", space)
        return space

    return None


EVERMEMOS_DEFAULT_SPACE: str | None = _resolve_default_space()
