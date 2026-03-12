"""Tests for content_guard: sensitive content detection."""

from __future__ import annotations

from evermemos_mcp.content_guard import scan_sensitive_content


def test_detects_openai_api_key():
    text = "Use this key: sk-proj-abcdefghijklmnopqrstuvwxyz1234567890abcdef"
    matches = scan_sensitive_content(text)
    assert len(matches) >= 1
    assert matches[0].category == "api_key"
    assert "sk-proj-" in matches[0].matched_text


def test_detects_anthropic_api_key():
    text = "My key is sk-ant-api03-abcdefghijklmnopqrstuvwxyz1234567890"
    matches = scan_sensitive_content(text)
    assert len(matches) >= 1
    assert matches[0].category == "api_key"


def test_detects_aws_access_key():
    text = "AWS key: AKIAIOSFODNN7EXAMPLE"
    matches = scan_sensitive_content(text)
    assert len(matches) >= 1
    assert matches[0].category == "aws_key"


def test_detects_github_token():
    text = "Token: ghp_ABCDEFabcdef1234567890abcdef1234567890"
    matches = scan_sensitive_content(text)
    assert len(matches) >= 1
    assert matches[0].category == "github_token"


def test_detects_private_key_block():
    text = "-----BEGIN RSA PRIVATE KEY-----\nMIIEpQIBAAK..."
    matches = scan_sensitive_content(text)
    assert len(matches) >= 1
    assert matches[0].category == "private_key"


def test_detects_generic_private_key():
    text = "-----BEGIN PRIVATE KEY-----\ndata..."
    matches = scan_sensitive_content(text)
    assert len(matches) >= 1
    assert matches[0].category == "private_key"


def test_detects_connection_string_with_password():
    text = "Use postgres://admin:s3cretP4ss@db.example.com:5432/mydb"
    matches = scan_sensitive_content(text)
    assert len(matches) >= 1
    assert matches[0].category == "connection_string"


def test_detects_password_assignment():
    text = 'config has password="SuperSecret123!"'
    matches = scan_sensitive_content(text)
    assert len(matches) >= 1
    assert matches[0].category == "password"


def test_detects_secret_assignment():
    text = "export API_KEY=abcdef1234567890abcdef"
    matches = scan_sensitive_content(text)
    assert len(matches) >= 1
    assert matches[0].category == "secret"


def test_detects_slack_token():
    text = "Bot token: xoxb-1234567890-abcdefghij-ABCDEFGHIJ"
    matches = scan_sensitive_content(text)
    assert len(matches) >= 1
    assert matches[0].category == "slack_token"


def test_no_false_positive_on_normal_text():
    text = "I prefer using Python for backend development. My name is Alice."
    matches = scan_sensitive_content(text)
    assert matches == []


def test_no_false_positive_on_code_discussion():
    text = "The function returns sk_count which tracks how many items were skipped."
    matches = scan_sensitive_content(text)
    assert matches == []


def test_no_false_positive_on_short_sk_prefix():
    text = "Variable sk is used for socket."
    matches = scan_sensitive_content(text)
    assert matches == []


def test_detects_multiple_sensitive_items():
    text = (
        "Key: sk-proj-abc123def456ghi789jkl012mno345pqr678stu\n"
        "DB: postgres://root:hunter2@localhost/prod"
    )
    matches = scan_sensitive_content(text)
    assert len(matches) >= 2
    categories = {m.category for m in matches}
    assert "api_key" in categories
    assert "connection_string" in categories


def test_match_has_description():
    text = "Token: ghp_ABCDEFabcdef1234567890abcdef1234567890"
    matches = scan_sensitive_content(text)
    assert matches[0].description  # non-empty string
