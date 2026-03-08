from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import time
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import uuid4

SCRIPTS_DIR = Path(__file__).resolve().parent
_COMMON_SPEC = importlib.util.spec_from_file_location(
    "evermemos_scripts_common",
    SCRIPTS_DIR / "common.py",
)
if _COMMON_SPEC is None or _COMMON_SPEC.loader is None:
    raise RuntimeError("Unable to load scripts/common.py")
common = importlib.util.module_from_spec(_COMMON_SPEC)
_COMMON_SPEC.loader.exec_module(common)

ROOT = common.ROOT
add_project_src_to_path = common.add_project_src_to_path
demo_space_ids = common.demo_space_ids
has_searchable_rows = common.has_searchable_rows
searchable_result_rows = common.searchable_result_rows

add_project_src_to_path()

if TYPE_CHECKING:
    from evermemos_mcp.memory_service import MemoryService


def _log(lines: list[str], message: str) -> None:
    print(message)
    lines.append(message)


def _display_artifact_dir(artifact_dir: Path) -> str:
    try:
        return artifact_dir.relative_to(ROOT).as_posix()
    except ValueError:
        return artifact_dir.as_posix()


async def _preload_spaces(
    svc: MemoryService,
    ids: dict[str, str],
    demo_data: dict[str, dict],
    logs: list[str],
) -> dict[str, dict]:
    metrics: dict[str, dict] = {}

    for domain, space_id in ids.items():
        spec = demo_data[domain]
        _log(logs, f"\n=== preload {space_id} ===")
        domain_metrics = {
            "space_id": space_id,
            "remember_attempts": 0,
            "remember_successes": 0,
            "request_status_successes": 0,
            "request_status_found": 0,
            "request_status_queued": 0,
            "request_status_searchable": 0,
            "first_ack_monotonic": None,
            "queued_message_ids": [],
        }
        metrics[domain] = domain_metrics

        for index, content in enumerate(spec["messages"]):
            result = await svc.remember(
                space_id,
                content,
                description=spec["description"] if index == 0 else None,
                sender="user",
                flush=True,
                include_status=True,
            )
            domain_metrics["remember_attempts"] += 1
            if result.get("ok"):
                domain_metrics["remember_successes"] += 1
            if domain_metrics["first_ack_monotonic"] is None:
                domain_metrics["first_ack_monotonic"] = time.monotonic()

            message_id = str(result.get("message_id", "")).strip()
            if message_id:
                domain_metrics["queued_message_ids"].append(message_id)

            status_result = result.get("request_status")
            if isinstance(status_result, dict):
                if status_result.get("success") is True:
                    domain_metrics["request_status_successes"] += 1
                if status_result.get("found") is True:
                    domain_metrics["request_status_found"] += 1
                lifecycle = status_result.get("lifecycle")
                lifecycle_state = (
                    lifecycle.get("state") if isinstance(lifecycle, dict) else None
                )
                if lifecycle_state == "queued":
                    domain_metrics["request_status_queued"] += 1
                if lifecycle_state == "searchable":
                    domain_metrics["request_status_searchable"] += 1

            _log(
                logs,
                f"[{index + 1}/{len(spec['messages'])}] ok={result.get('ok')} "
                f"message_id={message_id or '-'} request_status={json.dumps(status_result, ensure_ascii=False, default=str)}",
            )
            await asyncio.sleep(0.2)

    return metrics


async def _wait_until_searchable(
    svc: MemoryService,
    ids: dict[str, str],
    metrics: dict[str, dict],
    demo_data: dict[str, dict],
    logs: list[str],
    *,
    timeout: int,
    interval: int,
) -> bool:
    started = time.monotonic()
    pending_domains = set(ids)
    _log(
        logs,
        (
            "\n=== wait_until_searchable === "
            f"timeout={timeout}s interval={interval}s pending={sorted(pending_domains)}"
        ),
    )

    while pending_domains and (time.monotonic() - started) < timeout:
        elapsed = int(time.monotonic() - started)
        _log(logs, f"\n=== readiness check t+{elapsed}s ===")

        for domain in list(pending_domains):
            result = await svc.recall(
                query=demo_data[domain]["query"],
                space_id=ids[domain],
                top_k=3,
                retrieve_method="hybrid",
            )
            total_count = len(result.get("results", []))
            searchable_rows = searchable_result_rows(result)
            searchable_count = len(searchable_rows)
            pending = int(result.get("pending_count", 0) or 0)
            lifecycle = result.get("lifecycle")
            lifecycle_state = (
                lifecycle.get("state") if isinstance(lifecycle, dict) else None
            )
            _log(
                logs,
                f"{ids[domain]}: results={total_count} searchable={searchable_count} "
                f"pending={pending} lifecycle={lifecycle_state}",
            )

            if has_searchable_rows(result):
                first_ack = metrics[domain].get("first_ack_monotonic")
                searchable_after = None
                if isinstance(first_ack, (int, float)):
                    searchable_after = round(time.monotonic() - first_ack, 2)
                metrics[domain]["searchable_after_seconds"] = searchable_after
                metrics[domain]["first_search_hit_count"] = searchable_count
                pending_domains.remove(domain)

        if pending_domains:
            remaining = max(timeout - elapsed, 0)
            _log(
                logs,
                (
                    f"pending domains after t+{elapsed}s: {sorted(pending_domains)}; "
                    f"next check in {interval}s; remaining budget ~{remaining}s"
                ),
            )
            await asyncio.sleep(interval)

    for domain in pending_domains:
        metrics[domain]["searchable_after_seconds"] = None
        metrics[domain]["first_search_hit_count"] = 0

    if pending_domains:
        _log(
            logs,
            f"\nNot fully ready within timeout. Remaining: {sorted(pending_domains)}",
        )
        return False

    _log(logs, "\nAll demo spaces are searchable.")
    return True


async def _measure_isolation(
    svc: MemoryService,
    ids: dict[str, str],
    queries: dict[str, str],
    logs: list[str],
) -> dict:
    cross_space_queries = 0
    false_hits = 0
    details: list[dict] = []

    for query_domain, query in queries.items():
        for target_domain, target_space in ids.items():
            if query_domain == target_domain:
                continue
            cross_space_queries += 1
            result = await svc.recall(
                query=query,
                space_id=target_space,
                top_k=3,
                retrieve_method="hybrid",
            )
            rows = searchable_result_rows(result)
            hit_count = len(rows)
            leaked_rows = 0
            for row in rows:
                if not isinstance(row, dict):
                    continue
                source_space_id = str(row.get("space_id", "")).strip()
                if source_space_id and source_space_id != target_space:
                    leaked_rows += 1
            false_hits += leaked_rows
            details.append(
                {
                    "query_domain": query_domain,
                    "target_space": target_space,
                    "hit_count": hit_count,
                    "leaked_rows": leaked_rows,
                }
            )
            _log(
                logs,
                f"isolation query={query_domain} target={target_space} hits={hit_count} leaked_rows={leaked_rows}",
            )

    return {
        "cross_space_queries": cross_space_queries,
        "false_hits": false_hits,
        "details": details,
        "correct": false_hits == 0,
    }


async def _pick_deletable_memory_id(
    svc: MemoryService, space_id: str, coding_query: str
) -> str:
    recall_result = await svc.recall(
        query=coding_query,
        space_id=space_id,
        top_k=10,
        retrieve_method="hybrid",
    )
    for row in searchable_result_rows(recall_result):
        if isinstance(row, dict):
            memory_id = str(row.get("memory_id", "")).strip()
            if memory_id:
                return memory_id

    history = await svc.fetch_history(
        space_id, memory_type="episodic_memory", limit=20, offset=0
    )
    for row in history.get("items", []):
        if isinstance(row, dict):
            memory_id = str(row.get("memory_id", "")).strip()
            if memory_id:
                return memory_id
    return ""


async def _measure_forget_effectiveness(
    svc: MemoryService,
    space_id: str,
    coding_query: str,
    logs: list[str],
) -> dict:
    memory_id = await _pick_deletable_memory_id(svc, space_id, coding_query)
    if not memory_id:
        _log(logs, "forget check: no deletable memory_id found")
        return {
            "attempts": 0,
            "deleted_count": 0,
            "still_recalled": None,
            "ok": False,
            "memory_id": "",
            "note": "No deletable memory_id found in recall/fetch_history results.",
        }

    forget_result = await svc.forget(
        memory_ids=[memory_id],
        space_id=space_id,
        reason="competition lifecycle appendix validation",
    )
    verify = await svc.fetch_history(
        space_id, memory_type="episodic_memory", limit=20, offset=0
    )
    still_recalled = any(
        isinstance(item, dict) and str(item.get("memory_id", "")).strip() == memory_id
        for item in verify.get("items", [])
    )
    deleted_count = int(forget_result.get("deleted_count", 0) or 0)
    ok = deleted_count > 0 and not still_recalled
    _log(
        logs,
        f"forget check: memory_id={memory_id} deleted_count={deleted_count} still_recalled={still_recalled}",
    )
    return {
        "attempts": 1,
        "deleted_count": deleted_count,
        "still_recalled": still_recalled,
        "ok": ok,
        "memory_id": memory_id,
        "warnings": forget_result.get("warnings", []),
        "unmatched_ids": forget_result.get("unmatched_ids", []),
    }


def _skipped_isolation(reason: str) -> dict:
    return {
        "cross_space_queries": 0,
        "false_hits": 0,
        "details": [],
        "correct": False,
        "skipped": True,
        "reason": reason,
    }


def _skipped_forget(reason: str) -> dict:
    return {
        "attempts": 0,
        "deleted_count": 0,
        "still_recalled": None,
        "ok": False,
        "memory_id": "",
        "skipped": True,
        "reason": reason,
    }


def _build_appendix_markdown(results: dict, artifact_dir: Path) -> str:
    error_message = results.get("error")
    if isinstance(error_message, str) and error_message:
        return (
            "\n".join(
                [
                    "# Lifecycle Appendix Notes",
                    "",
                    f"- Generated at: {results['generated_at']}",
                    f"- Artifact dir: `{_display_artifact_dir(artifact_dir)}`",
                    f"- Prefix: `{results['prefix']}`",
                    "- Status: `FAILED TO GENERATE LIVE METRICS`",
                    f"- Error: `{error_message}`",
                    "",
                    "## Notes",
                    "",
                    "- The appendix generator reached the live Cloud validation step but could not finish.",
                    "- See `raw_logs.txt` for the full execution trace.",
                    "- Re-run `uv run python scripts/competition_lifecycle_appendix.py` after fixing the environment/auth issue.",
                ]
            )
            + "\n"
        )

    remember = results["remember"]
    searchable = results["searchable"]
    isolation = results["isolation"]
    forget = results["forget"]
    isolation_skipped = bool(isolation.get("skipped"))
    forget_skipped = bool(forget.get("skipped"))

    searchable_values = [
        value
        for value in searchable["per_space_seconds"].values()
        if isinstance(value, (int, float))
    ]
    if searchable_values:
        sorted_values = sorted(searchable_values)
        p50 = sorted_values[(len(sorted_values) - 1) // 2]
        p95 = sorted_values[int((len(sorted_values) - 1) * 0.95)]
        searchable_summary = f"P50={p50:.2f}s, P95={p95:.2f}s"
    else:
        searchable_summary = "No successful searchable samples"

    isolation_sample_size = (
        str(isolation["cross_space_queries"]) if not isolation_skipped else "N/A"
    )
    isolation_result = (
        f"{isolation['false_hits']}/{isolation['cross_space_queries']}"
        if not isolation_skipped
        else "skipped"
    )
    isolation_status = (
        "PASS" if isolation["correct"] else ("SKIP" if isolation_skipped else "WARN")
    )
    forget_sample_size = str(forget["attempts"]) if not forget_skipped else "N/A"
    forget_result = (
        f"{int(bool(forget['still_recalled'])) if forget['still_recalled'] is not None else 'N/A'}/{forget['attempts']}"
        if not forget_skipped
        else "skipped"
    )
    forget_status = "PASS" if forget["ok"] else ("SKIP" if forget_skipped else "WARN")

    return (
        "\n".join(
            [
                "# Lifecycle Appendix Notes",
                "",
                f"- Generated at: {results['generated_at']}",
                f"- Artifact dir: `{_display_artifact_dir(artifact_dir)}`",
                f"- Prefix: `{results['prefix']}`",
                "",
                "| Check | Definition | Sample size | Result | Status |",
                "| --- | --- | --- | --- | --- |",
                (
                    f"| Remember success rate | successful remember acknowledgements / total remember calls | "
                    f"`{remember['attempts']}` | `{remember['successes']}/{remember['attempts']}` ({remember['success_rate']:.2%}) | "
                    f"`{'PASS' if remember['success_rate'] == 1.0 else 'WARN'}` |"
                ),
                (
                    f"| Time-to-searchable P50/P95 | time from first remember ack in each demo space to first recall hit | "
                    f"`{searchable['sample_size']}` | `{searchable_summary}` | `{'PASS' if searchable['all_searchable'] else 'WARN'}` |"
                ),
                (
                    f"| Space isolation correctness | cross-space false hits / cross-space queries | `"
                    f"{isolation_sample_size}` | `{isolation_result}` | `{isolation_status}` |"
                ),
                (
                    f"| Forget effectiveness | deleted item still recalled / delete attempts | `"
                    f"{forget_sample_size}` | `{forget_result}` | `{forget_status}` |"
                ),
                "",
                "## Per-space searchable latency",
                "",
                *[
                    f"- `{space_id}`: `{seconds:.2f}s`"
                    if isinstance(seconds, (int, float))
                    else f"- `{space_id}`: `timeout`"
                    for space_id, seconds in searchable["per_space_seconds"].items()
                ],
                "",
                "## Notes",
                "",
                "- This appendix is supplemental evidence and does not change the primary benchmark gates.",
                "- Raw execution logs are stored in `raw_logs.txt` alongside this file.",
                *(
                    [f"- Isolation check skipped: {isolation['reason']}"]
                    if isolation_skipped
                    else []
                ),
                *(
                    [f"- Forget check skipped: {forget['reason']}"]
                    if forget_skipped
                    else []
                ),
            ]
        )
        + "\n"
    )


async def main() -> int:
    from demo_live_walkthrough import QUERIES
    from demo_preload import DEMO_DATA
    from evermemos_mcp.evermemos_client import EverMemosClient
    from evermemos_mcp.memory_service import MemoryService
    from evermemos_mcp.space_catalog_service import SpaceCatalogService

    parser = argparse.ArgumentParser(description="Generate lifecycle appendix evidence")
    parser.add_argument(
        "--prefix", default="", help="Optional fixed prefix for demo spaces"
    )
    parser.add_argument("--timeout", type=int, default=240)
    parser.add_argument("--interval", type=int, default=10)
    args = parser.parse_args()

    prefix = args.prefix.strip() or f"appendix-{uuid4().hex[:8]}"
    ids = demo_space_ids(prefix)
    logs: list[str] = []
    generated_at = datetime.now().astimezone().isoformat()
    artifact_dir = (
        ROOT
        / "artifacts"
        / "competition"
        / f"{datetime.now().date().isoformat()}-lifecycle-{prefix}"
    )
    artifact_dir.mkdir(parents=True, exist_ok=True)

    exit_code = 0
    try:
        async with EverMemosClient() as client:
            catalog = SpaceCatalogService(client)
            svc = MemoryService(client, catalog)

            _log(logs, f"=== lifecycle appendix start prefix={prefix} ===")
            _log(logs, "=== phase 1/4 preload demo spaces ===")
            remember_metrics = await _preload_spaces(svc, ids, DEMO_DATA, logs)
            _log(logs, "=== phase 2/4 wait until searchable ===")
            all_searchable = await _wait_until_searchable(
                svc,
                ids,
                remember_metrics,
                DEMO_DATA,
                logs,
                timeout=args.timeout,
                interval=args.interval,
            )
            if all_searchable:
                _log(logs, "=== phase 3/4 measure isolation ===")
                isolation = await _measure_isolation(svc, ids, QUERIES, logs)
                _log(logs, "=== phase 4/4 measure forget effectiveness ===")
                forget = await _measure_forget_effectiveness(
                    svc,
                    ids["coding"],
                    QUERIES["coding"],
                    logs,
                )
            else:
                skip_reason = "Skipped because not all spaces became searchable within the wait budget."
                _log(logs, f"=== skip isolation/forget: {skip_reason} ===")
                isolation = _skipped_isolation(skip_reason)
                forget = _skipped_forget(skip_reason)

        remember_attempts = sum(
            item["remember_attempts"] for item in remember_metrics.values()
        )
        remember_successes = sum(
            item["remember_successes"] for item in remember_metrics.values()
        )
        per_space_seconds = {
            ids[domain]: remember_metrics[domain].get("searchable_after_seconds")
            for domain in ids
        }
        results = {
            "generated_at": generated_at,
            "prefix": prefix,
            "spaces": ids,
            "remember": {
                "attempts": remember_attempts,
                "successes": remember_successes,
                "success_rate": (remember_successes / remember_attempts)
                if remember_attempts
                else 0.0,
                "per_space": remember_metrics,
            },
            "searchable": {
                "all_searchable": all_searchable,
                "sample_size": sum(
                    1
                    for value in per_space_seconds.values()
                    if isinstance(value, (int, float))
                ),
                "per_space_seconds": per_space_seconds,
            },
            "isolation": isolation,
            "forget": forget,
        }
    except Exception as exc:
        exit_code = 1
        _log(logs, f"\nLifecycle appendix generation failed: {exc}")
        results = {
            "generated_at": generated_at,
            "prefix": prefix,
            "spaces": ids,
            "error": str(exc),
        }

    (artifact_dir / "appendix_results.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (artifact_dir / "appendix_notes.md").write_text(
        _build_appendix_markdown(results, artifact_dir),
        encoding="utf-8",
    )
    (artifact_dir / "raw_logs.txt").write_text("\n".join(logs) + "\n", encoding="utf-8")

    print(f"\nLifecycle appendix written to {artifact_dir}")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
