"""Offline benchmark aggregator for competition evidence artifacts.

Input: JSONL records at --input (one run per line).
Output:
- benchmark_summary.json at --output
- benchmark_report.md (default: same directory as output)

Expected JSONL record fields:
- scenario: str
- query: str
- mode: "with_memory" | "without_memory"
- latency_ms: number
- hit: bool
- resolved_rows: int (optional, default 0)
- wrong_attributions: int (optional, default 0)
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class Targets:
    hit_rate_with_memory: float
    hit_rate_delta: float
    latency_p95_ms: float
    attribution_error_rate: float
    min_queries: int
    min_resolved_rows: int


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(f"Input JSONL file not found: {path}")

    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for line_no, raw_line in enumerate(f, start=1):
            line = raw_line.strip()
            if not line:
                continue
            try:
                parsed = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSON at line {line_no}: {exc}") from exc
            if not isinstance(parsed, dict):
                raise ValueError(f"Line {line_no} must be a JSON object")
            rows.append(parsed)
    return rows


def _to_int(value: object, default: int = 0) -> int:
    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return default
        try:
            return int(float(text))
        except ValueError:
            return default
    return default


def _to_float(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            return float(text)
        except ValueError:
            return None
    return None


def _to_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y"}
    return False


def _percentile(values: list[float], p: float) -> float | None:
    if not values:
        return None
    sorted_values = sorted(values)
    if len(sorted_values) == 1:
        return sorted_values[0]
    idx = int((len(sorted_values) - 1) * p)
    return sorted_values[idx]


def _normalize_rows(raw_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for index, row in enumerate(raw_rows, start=1):
        mode = row.get("mode")
        if mode not in {"with_memory", "without_memory"}:
            raise ValueError(
                f"Row {index} has invalid mode={mode!r}; expected with_memory/without_memory"
            )

        latency_ms = _to_float(row.get("latency_ms"))
        if latency_ms is None:
            raise ValueError(f"Row {index} missing valid latency_ms")
        if latency_ms < 0:
            raise ValueError(f"Row {index} has negative latency_ms")

        normalized.append(
            {
                "scenario": str(row.get("scenario", "")).strip(),
                "query": str(row.get("query", "")).strip(),
                "mode": mode,
                "latency_ms": latency_ms,
                "hit": _to_bool(row.get("hit")),
                "resolved_rows": max(0, _to_int(row.get("resolved_rows"), 0)),
                "wrong_attributions": max(0, _to_int(row.get("wrong_attributions"), 0)),
            }
        )
    return normalized


def _compute_summary(rows: list[dict[str, Any]], targets: Targets) -> dict[str, Any]:
    with_rows = [row for row in rows if row["mode"] == "with_memory"]
    without_rows = [row for row in rows if row["mode"] == "without_memory"]

    with_hits = sum(1 for row in with_rows if row["hit"])
    without_hits = sum(1 for row in without_rows if row["hit"])

    with_total = len(with_rows)
    without_total = len(without_rows)

    with_hit_rate = with_hits / with_total if with_total else 0.0
    without_hit_rate = without_hits / without_total if without_total else 0.0
    delta_hit_rate = with_hit_rate - without_hit_rate

    latency_samples_success = [row["latency_ms"] for row in with_rows if row["hit"]]
    if not latency_samples_success:
        # Fallback for sparse smoke runs: use all with-memory rows.
        latency_samples_success = [row["latency_ms"] for row in with_rows]

    latency_p50 = _percentile(latency_samples_success, 0.50)
    latency_p95 = _percentile(latency_samples_success, 0.95)

    resolved_rows = sum(row["resolved_rows"] for row in with_rows)
    wrong_attributions = sum(row["wrong_attributions"] for row in with_rows)
    attribution_error_rate = (
        (wrong_attributions / resolved_rows) if resolved_rows > 0 else None
    )

    gate_data_volume = with_total >= targets.min_queries
    gate_hit_rate = (
        with_hit_rate >= targets.hit_rate_with_memory
        and delta_hit_rate >= targets.hit_rate_delta
    )
    gate_latency = latency_p95 is not None and latency_p95 <= targets.latency_p95_ms
    gate_attribution = (
        resolved_rows >= targets.min_resolved_rows
        and attribution_error_rate is not None
        and attribution_error_rate <= targets.attribution_error_rate
    )

    return {
        "date": datetime.now(timezone.utc).date().isoformat(),
        "row_count": len(rows),
        "with_memory": {
            "queries": with_total,
            "hits": with_hits,
            "hit_rate": with_hit_rate,
            "latency_samples": len(latency_samples_success),
            "latency_p50_ms": latency_p50,
            "latency_p95_ms": latency_p95,
        },
        "without_memory": {
            "queries": without_total,
            "hits": without_hits,
            "hit_rate": without_hit_rate,
        },
        "delta_hit_rate": delta_hit_rate,
        "attribution": {
            "resolved_rows": resolved_rows,
            "wrong_attributions": wrong_attributions,
            "attribution_error_rate": attribution_error_rate,
        },
        "targets": {
            "hit_rate_with_memory": targets.hit_rate_with_memory,
            "hit_rate_delta": targets.hit_rate_delta,
            "latency_p95_ms": targets.latency_p95_ms,
            "attribution_error_rate": targets.attribution_error_rate,
            "min_queries": targets.min_queries,
            "min_resolved_rows": targets.min_resolved_rows,
        },
        "gates": {
            "data_volume": "pass" if gate_data_volume else "fail",
            "hit_rate": "pass" if gate_hit_rate else "fail",
            "latency_p95": "pass" if gate_latency else "fail",
            "attribution_error_rate": "pass" if gate_attribution else "fail",
            "overall": "pass"
            if (gate_data_volume and gate_hit_rate and gate_latency and gate_attribution)
            else "fail",
        },
    }


def _format_percent(value: float | None) -> str:
    if value is None:
        return "N/A"
    return f"{value * 100:.2f}%"


def _format_ms(value: float | None) -> str:
    if value is None:
        return "N/A"
    return f"{value:.0f} ms"


def _display_path(path: Path) -> str:
    try:
        return path.relative_to(Path.cwd().resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _infer_run_date(*paths: Path) -> str:
    date_pattern = re.compile(r"(\d{4}-\d{2}-\d{2})")
    for path in paths:
        for candidate in (path.parent.name, path.name):
            match = date_pattern.search(candidate)
            if match:
                return match.group(1)
    return datetime.now(timezone.utc).date().isoformat()


def _build_report(summary: dict[str, Any], input_path: Path, output_path: Path) -> str:
    with_memory = summary["with_memory"]
    without_memory = summary["without_memory"]
    attribution = summary["attribution"]
    gates = summary["gates"]

    lines = [
        "# Competition Benchmark Report",
        "",
        f"- Evidence date: {summary['date']}",
        f"- Generated at: {datetime.now(timezone.utc).isoformat()}",
        f"- Input: `{_display_path(input_path)}`",
        f"- Summary JSON: `{_display_path(output_path)}`",
        "",
        "## Headline",
        (
            f"- Overall gate: **{gates['overall'].upper()}** "
            f"(data_volume={gates['data_volume']}, hit_rate={gates['hit_rate']}, "
            f"latency={gates['latency_p95']}, attribution={gates['attribution_error_rate']})"
        ),
        "",
        "## Metrics",
        f"- With-memory hit rate: {_format_percent(with_memory['hit_rate'])} ({with_memory['hits']}/{with_memory['queries']})",
        f"- Without-memory hit rate: {_format_percent(without_memory['hit_rate'])} ({without_memory['hits']}/{without_memory['queries']})",
        f"- Delta hit rate: {_format_percent(summary['delta_hit_rate'])}",
        f"- Recall latency P50: {_format_ms(with_memory['latency_p50_ms'])}",
        f"- Recall latency P95: {_format_ms(with_memory['latency_p95_ms'])}",
        f"- Attribution error rate: {_format_percent(attribution['attribution_error_rate'])} ({attribution['wrong_attributions']}/{attribution['resolved_rows']})",
        "",
        "## Gate Status",
        f"- Data volume: {gates['data_volume']}",
        f"- Hit rate: {gates['hit_rate']}",
        f"- Latency P95: {gates['latency_p95']}",
        f"- Attribution error rate: {gates['attribution_error_rate']}",
    ]
    return "\n".join(lines) + "\n"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Aggregate competition runs.jsonl into benchmark summary/report."
    )
    parser.add_argument(
        "--input",
        required=True,
        help="Input JSONL path (e.g., artifacts/competition/2026-03-08-formal-real/runs.jsonl)",
    )
    parser.add_argument(
        "--output",
        required=True,
        help="Output summary JSON path (e.g., artifacts/competition/2026-03-08-formal-real/benchmark_summary.json)",
    )
    parser.add_argument(
        "--report-output",
        default="",
        help="Optional markdown report path (default: <output_dir>/benchmark_report.md)",
    )
    parser.add_argument(
        "--run-date",
        default="",
        help="Optional evidence date override (YYYY-MM-DD). Defaults to inferring from artifact paths.",
    )
    parser.add_argument("--target-hit-rate", type=float, default=0.80)
    parser.add_argument("--target-delta-hit-rate", type=float, default=0.40)
    parser.add_argument("--target-p95-ms", type=float, default=2000.0)
    parser.add_argument("--target-attribution-error-rate", type=float, default=0.02)
    parser.add_argument("--min-queries", type=int, default=60)
    parser.add_argument("--min-resolved-rows", type=int, default=200)
    return parser


def main() -> int:
    args = _build_parser().parse_args()

    input_path = Path(args.input).expanduser().resolve()
    output_path = Path(args.output).expanduser().resolve()
    report_path = (
        Path(args.report_output).expanduser().resolve()
        if args.report_output
        else output_path.parent / "benchmark_report.md"
    )

    targets = Targets(
        hit_rate_with_memory=args.target_hit_rate,
        hit_rate_delta=args.target_delta_hit_rate,
        latency_p95_ms=args.target_p95_ms,
        attribution_error_rate=args.target_attribution_error_rate,
        min_queries=max(1, int(args.min_queries)),
        min_resolved_rows=max(1, int(args.min_resolved_rows)),
    )

    raw_rows = _read_jsonl(input_path)
    rows = _normalize_rows(raw_rows)
    summary = _compute_summary(rows, targets)
    summary["date"] = args.run_date.strip() or _infer_run_date(input_path, output_path)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    report = _build_report(summary, input_path=input_path, output_path=output_path)
    report_path.write_text(report, encoding="utf-8")

    print(f"Summary written to: {output_path}")
    print(f"Report written to: {report_path}")
    print(f"Overall gate: {summary['gates']['overall']}")

    return 0 if summary["gates"]["overall"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
