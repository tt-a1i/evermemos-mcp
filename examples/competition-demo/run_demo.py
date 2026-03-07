"""Run reproducible competition benchmark collection against real EverMemOS data.

This script collects per-query recall rows for both modes:
- with_memory: query the target scenario space
- without_memory: query a control empty space

It then writes `runs.jsonl` and calls `scripts/competition_eval.py`
to generate `benchmark_summary.json` and `benchmark_report.md`.
"""

# ruff: noqa: E402

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = ROOT / "scripts"
_COMMON_SPEC = importlib.util.spec_from_file_location(
    "evermemos_scripts_common",
    SCRIPTS_DIR / "common.py",
)
if _COMMON_SPEC is None or _COMMON_SPEC.loader is None:
    raise RuntimeError("Unable to load scripts/common.py")
common = importlib.util.module_from_spec(_COMMON_SPEC)
_COMMON_SPEC.loader.exec_module(common)

add_project_src_to_path = common.add_project_src_to_path
demo_space_ids = common.demo_space_ids
searchable_result_rows = common.searchable_result_rows

add_project_src_to_path()

from evermemos_mcp.evermemos_client import EverMemosClient
from evermemos_mcp.memory_service import MemoryService
from evermemos_mcp.space_catalog_service import SpaceCatalogService

_ALLOWED_SCENARIOS = {"coding", "chat", "study"}


@dataclass(frozen=True)
class QueryCase:
    case_id: str
    scenario: str
    query: str
    expected_signals: tuple[str, ...]
    with_space_id: str
    without_space_id: str


def _slugify(raw: str) -> str:
    slug = re.sub(r"[^a-z0-9-]+", "-", raw.strip().lower())
    slug = re.sub(r"-+", "-", slug).strip("-")
    return slug or "benchmark"


def _control_space_ids(prefix: str) -> dict[str, str]:
    slug_prefix = _slugify(prefix) if prefix else ""
    base = f"{slug_prefix}-no-memory" if slug_prefix else "no-memory"
    return {
        "coding": f"coding:{base}-coding",
        "chat": f"chat:{base}-chat",
        "study": f"study:{base}-study",
    }


def _load_query_rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(f"Query set not found: {path}")

    if path.suffix.lower() == ".json":
        payload = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(payload, list):
            rows = payload
        elif isinstance(payload, dict) and isinstance(payload.get("queries"), list):
            rows = payload["queries"]
        else:
            raise ValueError("JSON query file must be a list or {'queries': [...]}.")
        return [row for row in rows if isinstance(row, dict)]

    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for line_no, raw_line in enumerate(f, start=1):
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            try:
                parsed = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSON at line {line_no}: {exc}") from exc
            if not isinstance(parsed, dict):
                raise ValueError(f"Line {line_no} must be a JSON object")
            rows.append(parsed)
    return rows


def _parse_signals(raw: Any) -> tuple[str, ...]:
    if isinstance(raw, str):
        value = raw.strip()
        return (value,) if value else ()
    if not isinstance(raw, list):
        return ()

    normalized: list[str] = []
    for item in raw:
        if isinstance(item, str):
            text = item.strip()
            if text:
                normalized.append(text)
    return tuple(normalized)


def _build_cases(
    rows: list[dict[str, Any]],
    *,
    default_spaces: dict[str, str],
    control_spaces: dict[str, str],
) -> list[QueryCase]:
    cases: list[QueryCase] = []
    for index, row in enumerate(rows, start=1):
        scenario = str(row.get("scenario", "")).strip().lower()
        if scenario not in _ALLOWED_SCENARIOS:
            raise ValueError(
                f"Row {index} has invalid scenario={scenario!r}; "
                "expected one of coding/chat/study"
            )

        query = str(row.get("query", "")).strip()
        if not query:
            raise ValueError(f"Row {index} has empty query")

        case_id = str(row.get("id", "")).strip() or f"{scenario}-{index:02d}"
        expected_signals = _parse_signals(row.get("expected_signals", []))

        with_space_id = str(row.get("space_id", "")).strip() or default_spaces[scenario]
        without_space_id = (
            str(row.get("without_space_id", "")).strip() or control_spaces[scenario]
        )

        cases.append(
            QueryCase(
                case_id=case_id,
                scenario=scenario,
                query=query,
                expected_signals=expected_signals,
                with_space_id=with_space_id,
                without_space_id=without_space_id,
            )
        )
    return cases


def _result_rows(result: dict[str, Any]) -> list[dict[str, Any]]:
    return searchable_result_rows(result)


def _collect_text_blobs(rows: list[dict[str, Any]]) -> list[str]:
    blobs: list[str] = []
    for row in rows:
        snippet = row.get("snippet")
        content = row.get("content")
        text = " ".join(
            value.strip()
            for value in [snippet, content]
            if isinstance(value, str) and value.strip()
        )
        if text:
            blobs.append(text.lower())
    return blobs


def _compute_hit(
    rows: list[dict[str, Any]], signals: tuple[str, ...]
) -> tuple[bool, list[str]]:
    if not signals:
        return False, []

    blobs = _collect_text_blobs(rows)
    matched: list[str] = []
    for signal in signals:
        needle = signal.lower()
        if any(needle in blob for blob in blobs):
            matched.append(signal)
    return bool(matched), matched


def _compute_attribution(
    rows: list[dict[str, Any]], expected_space_id: str
) -> tuple[int, int]:
    resolved = 0
    wrong = 0
    for row in rows:
        source_space_id = row.get("space_id")
        if not isinstance(source_space_id, str):
            continue
        source_space_id = source_space_id.strip()
        if not source_space_id:
            continue
        resolved += 1
        if source_space_id != expected_space_id:
            wrong += 1
    return resolved, wrong


async def _run_single_mode(
    svc: MemoryService,
    *,
    case: QueryCase,
    mode: str,
    top_k: int,
    retrieve_method: str,
) -> dict[str, Any]:
    space_id = case.with_space_id if mode == "with_memory" else case.without_space_id

    start = time.perf_counter()
    result = await svc.recall(
        query=case.query,
        space_id=space_id,
        top_k=top_k,
        retrieve_method=retrieve_method,
    )
    latency_ms = (time.perf_counter() - start) * 1000.0

    rows = _result_rows(result)
    hit, matched_signals = _compute_hit(rows, case.expected_signals)
    resolved_rows, wrong_attributions = _compute_attribution(rows, space_id)

    return {
        "id": case.case_id,
        "scenario": case.scenario,
        "query": case.query,
        "mode": mode,
        "space_id": space_id,
        "latency_ms": round(latency_ms, 2),
        "hit": hit,
        "resolved_rows": resolved_rows,
        "wrong_attributions": wrong_attributions,
        "result_count": len(rows),
        "matched_signals": matched_signals,
        "expected_signals": list(case.expected_signals),
        "pending_count": int(result.get("pending_count", 0))
        if isinstance(result.get("pending_count"), int)
        else 0,
        "lifecycle_state": (
            (result.get("lifecycle") or {}).get("state")
            if isinstance(result.get("lifecycle"), dict)
            else None
        ),
        "warnings_count": len(result.get("warnings", []))
        if isinstance(result.get("warnings"), list)
        else 0,
    }


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def _run_eval(args: argparse.Namespace, *, runs_path: Path, output_dir: Path) -> int:
    summary_path = output_dir / "benchmark_summary.json"
    report_path = output_dir / "benchmark_report.md"

    cmd = [
        sys.executable,
        str(ROOT / "scripts" / "competition_eval.py"),
        "--input",
        str(runs_path),
        "--output",
        str(summary_path),
        "--report-output",
        str(report_path),
        "--target-hit-rate",
        str(args.target_hit_rate),
        "--target-delta-hit-rate",
        str(args.target_delta_hit_rate),
        "--target-p95-ms",
        str(args.target_p95_ms),
        "--target-attribution-error-rate",
        str(args.target_attribution_error_rate),
        "--min-queries",
        str(args.min_queries),
        "--min-resolved-rows",
        str(args.min_resolved_rows),
    ]

    print("\nRunning competition_eval:")
    print(" ".join(cmd))
    result = subprocess.run(cmd, cwd=ROOT, check=False)
    return result.returncode


def _default_artifact_dir() -> Path:
    date = datetime.now(timezone.utc).date().isoformat()
    return ROOT / "artifacts" / "competition" / f"{date}-formal-real"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Collect real benchmark runs and aggregate competition evidence artifacts.",
    )
    parser.add_argument(
        "--queries",
        default=str(
            ROOT / "examples" / "competition-demo" / "query_set_real_template.jsonl"
        ),
        help="Path to query set (.jsonl or .json)",
    )
    parser.add_argument(
        "--artifact-dir",
        default=str(_default_artifact_dir()),
        help="Output directory for runs/summary/report",
    )
    parser.add_argument(
        "--prefix",
        default="",
        help="Optional prefix for target space IDs, shared with scripts/common.py",
    )
    parser.add_argument(
        "--top-k",
        type=int,
        default=8,
        help="Recall top_k for each query",
    )
    parser.add_argument(
        "--retrieve-method",
        default="hybrid",
        choices=["keyword", "hybrid", "vector", "rrf", "agentic", "auto"],
        help="Recall retrieve method",
    )
    parser.add_argument(
        "--sleep-ms",
        type=int,
        default=120,
        help="Sleep between requests to reduce API burst",
    )
    parser.add_argument(
        "--skip-eval",
        action="store_true",
        help="Only generate runs.jsonl, skip benchmark aggregation",
    )

    parser.add_argument("--target-hit-rate", type=float, default=0.80)
    parser.add_argument("--target-delta-hit-rate", type=float, default=0.40)
    parser.add_argument("--target-p95-ms", type=float, default=2000.0)
    parser.add_argument("--target-attribution-error-rate", type=float, default=0.02)
    parser.add_argument("--min-queries", type=int, default=60)
    parser.add_argument("--min-resolved-rows", type=int, default=200)

    return parser


async def _run(args: argparse.Namespace) -> int:
    query_path = Path(args.queries).expanduser().resolve()
    output_dir = Path(args.artifact_dir).expanduser().resolve()

    default_spaces = demo_space_ids(args.prefix.strip())
    control_spaces = _control_space_ids(args.prefix.strip())

    raw_rows = _load_query_rows(query_path)
    cases = _build_cases(
        raw_rows,
        default_spaces=default_spaces,
        control_spaces=control_spaces,
    )

    print(f"Loaded {len(cases)} query cases from {query_path}")
    print("With-memory spaces:", default_spaces)
    print("Without-memory control spaces:", control_spaces)

    runs: list[dict[str, Any]] = []

    async with EverMemosClient() as client:
        catalog = SpaceCatalogService(client)
        svc = MemoryService(client, catalog)

        for index, case in enumerate(cases, start=1):
            with_row = await _run_single_mode(
                svc,
                case=case,
                mode="with_memory",
                top_k=args.top_k,
                retrieve_method=args.retrieve_method,
            )
            runs.append(with_row)
            print(
                f"[{index}/{len(cases)}] with_memory {case.case_id} "
                f"hit={with_row['hit']} latency={with_row['latency_ms']:.0f}ms "
                f"results={with_row['result_count']}"
            )

            without_row = await _run_single_mode(
                svc,
                case=case,
                mode="without_memory",
                top_k=args.top_k,
                retrieve_method=args.retrieve_method,
            )
            runs.append(without_row)
            print(
                f"[{index}/{len(cases)}] without_memory {case.case_id} "
                f"hit={without_row['hit']} latency={without_row['latency_ms']:.0f}ms "
                f"results={without_row['result_count']}"
            )

            if args.sleep_ms > 0:
                await asyncio.sleep(args.sleep_ms / 1000.0)

    runs_path = output_dir / "runs.jsonl"
    _write_jsonl(runs_path, runs)
    print(f"\nruns.jsonl written to: {runs_path}")

    if args.skip_eval:
        print("Skip eval enabled; benchmark_summary/report were not generated.")
        return 0

    return _run_eval(args, runs_path=runs_path, output_dir=output_dir)


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()

    if args.top_k == 0 or args.top_k < -1:
        parser.error("--top-k must be -1 or a positive integer")
    if args.min_queries < 1:
        parser.error("--min-queries must be >= 1")
    if args.min_resolved_rows < 1:
        parser.error("--min-resolved-rows must be >= 1")

    return asyncio.run(_run(args))


if __name__ == "__main__":
    raise SystemExit(main())
