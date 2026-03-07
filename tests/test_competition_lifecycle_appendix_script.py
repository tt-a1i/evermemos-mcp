from __future__ import annotations

import asyncio
import importlib.util
import sys
from pathlib import Path


def _load_module():
    repo_root = Path(__file__).resolve().parents[1]
    scripts_dir = repo_root / "scripts"
    if str(scripts_dir) not in sys.path:
        sys.path.insert(0, str(scripts_dir))

    module_path = scripts_dir / "competition_lifecycle_appendix.py"
    spec = importlib.util.spec_from_file_location(
        "competition_lifecycle_appendix", module_path
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_build_appendix_markdown_marks_skipped_sections(tmp_path):
    module = _load_module()
    artifact_dir = tmp_path / "artifacts" / "competition" / "2026-03-07-lifecycle-demo"
    artifact_dir.mkdir(parents=True)

    results = {
        "generated_at": "2026-03-07T20:00:00+08:00",
        "prefix": "demo",
        "remember": {
            "attempts": 9,
            "successes": 9,
            "success_rate": 1.0,
        },
        "searchable": {
            "all_searchable": False,
            "sample_size": 1,
            "per_space_seconds": {
                "coding:demo": None,
                "chat:demo": None,
                "study:demo": 39.0,
            },
        },
        "isolation": module._skipped_isolation("not all spaces searchable"),
        "forget": module._skipped_forget("not all spaces searchable"),
    }

    markdown = module._build_appendix_markdown(results, artifact_dir)

    assert "`SKIP`" in markdown
    assert "Isolation check skipped: not all spaces searchable" in markdown
    assert "Forget check skipped: not all spaces searchable" in markdown
    assert "`skipped`" in markdown


def test_measure_isolation_counts_only_cross_space_leaks():
    module = _load_module()

    class FakeSvc:
        async def recall(self, *, query, space_id, top_k, retrieve_method):
            return {
                "results": [
                    {"space_id": space_id, "memory_id": f"ok:{space_id}:{query}"},
                    {"space_id": space_id, "memory_id": f"ok2:{space_id}:{query}"},
                ]
            }

    result = asyncio.run(
        module._measure_isolation(
            FakeSvc(),
            {"coding": "coding:demo", "chat": "chat:demo", "study": "study:demo"},
            {"coding": "q1", "chat": "q2", "study": "q3"},
            [],
        )
    )

    assert result["cross_space_queries"] == 6
    assert result["false_hits"] == 0
    assert result["correct"] is True
    assert all(detail["leaked_rows"] == 0 for detail in result["details"])
