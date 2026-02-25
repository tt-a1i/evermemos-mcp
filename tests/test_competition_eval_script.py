"""Tests for scripts/competition_eval.py."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def test_competition_eval_smoke_passes_with_relaxed_thresholds(tmp_path):
    input_path = tmp_path / "runs.jsonl"
    output_path = tmp_path / "benchmark_summary.json"
    report_path = tmp_path / "benchmark_report.md"

    rows = [
        {
            "scenario": "coding",
            "query": "q1",
            "mode": "with_memory",
            "latency_ms": 1000,
            "hit": True,
            "resolved_rows": 4,
            "wrong_attributions": 0,
        },
        {
            "scenario": "chat",
            "query": "q2",
            "mode": "with_memory",
            "latency_ms": 1200,
            "hit": True,
            "resolved_rows": 4,
            "wrong_attributions": 0,
        },
        {
            "scenario": "coding",
            "query": "q1",
            "mode": "without_memory",
            "latency_ms": 900,
            "hit": False,
            "resolved_rows": 0,
            "wrong_attributions": 0,
        },
        {
            "scenario": "chat",
            "query": "q2",
            "mode": "without_memory",
            "latency_ms": 1100,
            "hit": False,
            "resolved_rows": 0,
            "wrong_attributions": 0,
        },
    ]
    input_path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
        encoding="utf-8",
    )

    cmd = [
        sys.executable,
        "scripts/competition_eval.py",
        "--input",
        str(input_path),
        "--output",
        str(output_path),
        "--report-output",
        str(report_path),
        "--min-queries",
        "2",
        "--min-resolved-rows",
        "8",
    ]
    result = subprocess.run(cmd, cwd=_repo_root(), check=False, capture_output=True)

    assert result.returncode == 0
    assert output_path.exists()
    assert report_path.exists()

    summary = json.loads(output_path.read_text(encoding="utf-8"))
    assert summary["gates"]["overall"] == "pass"
    assert summary["with_memory"]["queries"] == 2
    assert summary["without_memory"]["queries"] == 2


def test_competition_eval_fails_on_invalid_mode(tmp_path):
    input_path = tmp_path / "runs.jsonl"
    output_path = tmp_path / "benchmark_summary.json"

    bad_row = {
        "scenario": "coding",
        "query": "q1",
        "mode": "unknown",
        "latency_ms": 1000,
        "hit": True,
    }
    input_path.write_text(json.dumps(bad_row) + "\n", encoding="utf-8")

    cmd = [
        sys.executable,
        "scripts/competition_eval.py",
        "--input",
        str(input_path),
        "--output",
        str(output_path),
    ]
    result = subprocess.run(cmd, cwd=_repo_root(), check=False, capture_output=True)

    assert result.returncode != 0
    assert b"invalid mode" in result.stderr.lower()
