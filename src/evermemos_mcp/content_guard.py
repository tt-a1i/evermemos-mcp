"""Sensitive content detection for memory writes.

Pure functions — no async, no network, no side effects.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SensitiveMatch:
    """A single sensitive content detection result."""

    category: str
    description: str
    matched_text: str


def _mask(text: str) -> str:
    """Return a masked version that shows pattern type but hides the secret."""
    if len(text) <= 8:
        return text[:3] + "****"
    return text[:8] + "****"


# -- Tier 1: format-based patterns (high confidence, specific formats) --
_PATTERNS: list[tuple[re.Pattern[str], str, str]] = [
    # API keys with known prefixes
    (
        re.compile(r"\bsk-(?:proj-|ant-api\d{2}-)?(?!-)[A-Za-z0-9_]{20,}"),
        "api_key",
        "OpenAI/Anthropic API key",
    ),
    (
        re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
        "aws_key",
        "AWS Access Key ID",
    ),
    (
        re.compile(r"\bgh[psortu]_[A-Za-z0-9]{36,}\b"),
        "github_token",
        "GitHub token",
    ),
    (
        re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b"),
        "github_token",
        "GitHub fine-grained PAT",
    ),
    (
        re.compile(r"\bxox[bp]-[A-Za-z0-9\-]{20,}\b"),
        "slack_token",
        "Slack token",
    ),
    # Private keys
    (
        re.compile(
            r"-----BEGIN (?:RSA |EC |DSA |ED25519 |OPENSSH )?PRIVATE KEY-----"
        ),
        "private_key",
        "Private key block",
    ),
    # Connection strings with embedded credentials
    (
        re.compile(
            r"\b(?:postgres(?:ql)?|mysql|mongodb(?:\+srv)?|redis|amqp)"
            r"://[^\s:]+:[^\s@]+@[^\s]+"
        ),
        "connection_string",
        "Database connection string with credentials",
    ),
]

# -- Tier 2: keyword presence (broader, catches rewrites by AI models) --
# If ANY of these keywords appear in the text, the content is flagged.
# False positives are acceptable here because the hint only asks the model
# to confirm with the user — not a hard block.
# ASCII-only word boundary: prevents matching inside English words like
# "keyboard" or "monkey", but works after CJK characters.
_AB = r"(?<![a-zA-Z0-9_])"  # ASCII boundary before
_AE = r"(?![a-zA-Z0-9_])"   # ASCII boundary after

_KEYWORD_PATTERNS: list[tuple[re.Pattern[str], str, str]] = [
    # English keywords
    (
        re.compile(_AB + r"(?:password|passwd|pwd)" + _AE, re.IGNORECASE),
        "password",
        "Content mentions password",
    ),
    (
        re.compile(_AB + r"(?:api[_\-]?key|access[_\-]?key|secret[_\-]?key)" + _AE, re.IGNORECASE),
        "secret",
        "Content mentions API key",
    ),
    (
        re.compile(_AB + r"(?:secret|token|credential)" + _AE, re.IGNORECASE),
        "secret",
        "Content mentions secret/token/credential",
    ),
    (
        re.compile(_AB + r"key\s*[=:是为：]", re.IGNORECASE),
        "secret",
        "Content contains key assignment",
    ),
    # Chinese keywords
    (
        re.compile(r"密[码钥]|秘钥|凭[证据]"),
        "secret",
        "Content mentions 密码/密钥/凭证",
    ),
]


def scan_sensitive_content(text: str) -> list[SensitiveMatch]:
    """Scan text for sensitive patterns. Returns empty list if clean."""
    if not isinstance(text, str) or not text:
        return []

    matches: list[SensitiveMatch] = []
    seen_spans: set[tuple[int, int]] = set()

    # Tier 1: format-based patterns
    for pattern, category, description in _PATTERNS:
        for m in pattern.finditer(text):
            span = (m.start(), m.end())
            if any(s[0] < span[1] and span[0] < s[1] for s in seen_spans):
                continue
            seen_spans.add(span)
            matches.append(
                SensitiveMatch(
                    category=category,
                    description=description,
                    matched_text=_mask(m.group(0)),
                )
            )

    # Tier 2: keyword presence (only if tier 1 didn't already find something)
    if not matches:
        for pattern, category, description in _KEYWORD_PATTERNS:
            m = pattern.search(text)
            if m:
                matches.append(
                    SensitiveMatch(
                        category=category,
                        description=description,
                        matched_text=m.group(0),
                    )
                )
                break  # One keyword match is enough to block

    return matches
