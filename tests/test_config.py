"""Tests for config env parsing."""

from __future__ import annotations

import importlib

from evermemos_mcp import config as config_module


def _reload_config_module():
    return importlib.reload(config_module)


def test_source_recovery_probe_env_overrides(monkeypatch):
    monkeypatch.setenv("EVERMEMOS_SOURCE_RECOVERY_PROBE_TOP_K", "55")
    monkeypatch.setenv("EVERMEMOS_SOURCE_RECOVERY_PROBE_CONCURRENCY", "6")

    reloaded = _reload_config_module()
    assert reloaded.EVERMEMOS_SOURCE_RECOVERY_PROBE_TOP_K == 55
    assert reloaded.EVERMEMOS_SOURCE_RECOVERY_PROBE_CONCURRENCY == 6

    monkeypatch.delenv("EVERMEMOS_SOURCE_RECOVERY_PROBE_TOP_K", raising=False)
    monkeypatch.delenv("EVERMEMOS_SOURCE_RECOVERY_PROBE_CONCURRENCY", raising=False)
    _reload_config_module()


def test_source_recovery_probe_env_clamps_invalid_values(monkeypatch):
    monkeypatch.setenv("EVERMEMOS_SOURCE_RECOVERY_PROBE_TOP_K", "-3")
    monkeypatch.setenv("EVERMEMOS_SOURCE_RECOVERY_PROBE_CONCURRENCY", "99")

    reloaded = _reload_config_module()
    assert reloaded.EVERMEMOS_SOURCE_RECOVERY_PROBE_TOP_K == 1
    assert reloaded.EVERMEMOS_SOURCE_RECOVERY_PROBE_CONCURRENCY == 10

    monkeypatch.delenv("EVERMEMOS_SOURCE_RECOVERY_PROBE_TOP_K", raising=False)
    monkeypatch.delenv("EVERMEMOS_SOURCE_RECOVERY_PROBE_CONCURRENCY", raising=False)
    _reload_config_module()
