from __future__ import annotations

from pathlib import Path

from scripts.check_release_consistency import (
    read_init_version,
    read_project_version,
    read_tool_count,
    run_checks,
)


def test_release_consistency_checks_pass_for_repo_state():
    assert run_checks() == []


def test_project_versions_match_repo_files():
    repo_root = Path(__file__).resolve().parents[1]
    assert read_project_version(repo_root / "pyproject.toml") == "0.5.7"
    assert (
        read_init_version(repo_root / "src" / "evermemos_mcp" / "__init__.py")
        == "0.5.7"
    )


def test_server_tool_count_is_seven():
    repo_root = Path(__file__).resolve().parents[1]
    assert read_tool_count(repo_root / "src" / "evermemos_mcp" / "server.py") == 7


def test_changelog_tracks_current_release_highlights():
    repo_root = Path(__file__).resolve().parents[1]
    changelog = (repo_root / "CHANGELOG.md").read_text(encoding="utf-8")
    assert "## [0.5.7]" in changelog
    assert "Sensitive content detection" in changelog
    assert "conflict detection" in changelog
