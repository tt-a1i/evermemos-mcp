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


# (compiled_regex, category, description)
# Order: most specific first to reduce false positives.
_PATTERNS: list[tuple[re.Pattern[str], str, str]] = [
    # -- API keys with known prefixes --
    (
        re.compile(r"\bsk-(?:proj-|ant-api\d{2}-)?[A-Za-z0-9_\-]{20,}"),
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
        re.compile(r"\bxox[bp]-[A-Za-z0-9\-]{20,}\b"),
        "slack_token",
        "Slack token",
    ),
    # -- Private keys --
    (
        re.compile(r"-----BEGIN (?:RSA |EC |DSA |ED25519 )?PRIVATE KEY-----"),
        "private_key",
        "Private key block",
    ),
    # -- Connection strings with embedded credentials --
    (
        re.compile(
            r"\b(?:postgres(?:ql)?|mysql|mongodb(?:\+srv)?|redis|amqp)"
            r"://[^\s:]+:[^\s@]+@[^\s]+"
        ),
        "connection_string",
        "Database connection string with credentials",
    ),
    # -- Explicit password/secret assignments --
    (
        re.compile(
            r"\b(?:password|passwd|pwd)\s*[=:]\s*[\"']?([^\s\"']{8,})",
            re.IGNORECASE,
        ),
        "password",
        "Password value",
    ),
    (
        re.compile(
            r"\b(?:secret|token|api[_-]?key|access[_-]?key|SECRET_KEY|API_KEY)"
            r"\s*[=:]\s*[\"']?([^\s\"']{16,})",
            re.IGNORECASE,
        ),
        "secret",
        "Secret or token value",
    ),
]

_SK_MIN_LENGTH = 20


def scan_sensitive_content(text: str) -> list[SensitiveMatch]:
    """Scan text for sensitive patterns. Returns empty list if clean."""
    if not isinstance(text, str) or not text:
        return []

    matches: list[SensitiveMatch] = []
    seen_spans: set[tuple[int, int]] = set()

    for pattern, category, description in _PATTERNS:
        for m in pattern.finditer(text):
            span = (m.start(), m.end())
            if any(
                s[0] <= span[0] < s[1] or s[0] < span[1] <= s[1]
                for s in seen_spans
            ):
                continue
            matched = m.group(0)
            if category == "api_key" and len(matched) < _SK_MIN_LENGTH:
                continue
            seen_spans.add(span)
            matches.append(
                SensitiveMatch(
                    category=category,
                    description=description,
                    matched_text=matched,
                )
            )

    return matches
