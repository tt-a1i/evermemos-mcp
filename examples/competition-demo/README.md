# Competition Demo Runner

This folder provides a one-command benchmark collection flow for Memory Genesis submission evidence.

## Files
- `run_demo.py`: collects `runs.jsonl` from real recall calls and aggregates summary/report
- `run.sh`: one-command wrapper
- `query_set_real_template.jsonl`: 60-query template (`coding/chat/study` = 20 each)

## Quick Start
1. Configure `.env` with `EVERMEMOS_API_KEY`
2. Preload demo data and wait until searchable:

```bash
uv run python scripts/demo_preload.py --wait --check-status --timeout 480 --interval 20
```

3. Run formal real benchmark:

```bash
examples/competition-demo/run.sh
```

Output directory defaults to:
- `artifacts/competition/<YYYY-MM-DD>-formal-real/`

## Optional Flags
Pass extra flags through `run.sh` directly:

```bash
examples/competition-demo/run.sh --prefix mydemo --top-k 8 --retrieve-method hybrid
```

To only collect `runs.jsonl` without aggregation:

```bash
examples/competition-demo/run.sh --skip-eval
```
