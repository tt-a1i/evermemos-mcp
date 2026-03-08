from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_common_module():
    repo_root = Path(__file__).resolve().parents[1]
    module_path = repo_root / "scripts" / "common.py"
    spec = importlib.util.spec_from_file_location("scripts_common", module_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_searchable_result_rows_filters_provisional_and_fallback():
    module = _load_common_module()

    result = {
        "results": [
            {"memory_id": "ep-001", "stability": "searchable"},
            {"memory_id": "pending:1", "stability": "provisional"},
            {"memory_id": "meta:1", "stability": "fallback"},
            {"memory_id": "legacy-row-without-stability"},
        ]
    }

    rows = module.searchable_result_rows(result)

    assert [row["memory_id"] for row in rows] == [
        "ep-001",
        "legacy-row-without-stability",
    ]
    assert module.has_searchable_rows(result) is True


def test_has_searchable_rows_false_when_only_non_searchable_rows_present():
    module = _load_common_module()

    result = {
        "results": [
            {"memory_id": "pending:1", "stability": "provisional"},
            {"memory_id": "meta:1", "stability": "fallback"},
        ]
    }

    assert module.searchable_result_rows(result) == []
    assert module.has_searchable_rows(result) is False
