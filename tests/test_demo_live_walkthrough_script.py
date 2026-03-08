from __future__ import annotations

import asyncio
import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace


def _load_module():
    repo_root = Path(__file__).resolve().parents[1]
    scripts_dir = repo_root / "scripts"
    if str(scripts_dir) not in sys.path:
        sys.path.insert(0, str(scripts_dir))

    module_path = scripts_dir / "demo_live_walkthrough.py"
    spec = importlib.util.spec_from_file_location("demo_live_walkthrough", module_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_main_verifies_forget_with_history_before_recall(monkeypatch):
    module = _load_module()
    events: list[tuple[str, str]] = []
    rendered: list[str] = []

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

    class FakeMemoryService:
        def __init__(self, client, catalog):
            self.client = client
            self.catalog = catalog

        async def list_spaces(self, limit=20):
            return {"ok": True, "spaces": []}

        async def recall(self, *, query, space_id, top_k, retrieve_method):
            events.append(("recall", space_id))
            return {
                "ok": True,
                "results": [{"memory_id": "ep-001", "stability": "searchable"}],
            }

        async def briefing(self, *, space_id, max_items):
            return {"ok": True, "summary": "brief"}

        async def forget(self, *, memory_ids, space_id, reason):
            events.append(("forget", space_id))
            return {"ok": True, "deleted_count": 1}

        async def fetch_history(self, *, space_id, memory_type, limit, offset):
            events.append(("fetch_history", space_id))
            return {"ok": True, "items": []}

    monkeypatch.setattr(
        module.argparse.ArgumentParser,
        "parse_args",
        lambda self: SimpleNamespace(prefix="", do_forget=True),
    )
    monkeypatch.setattr(module, "EverMemosClient", FakeClient)
    monkeypatch.setattr(module, "SpaceCatalogService", lambda client: object())
    monkeypatch.setattr(module, "MemoryService", FakeMemoryService)
    monkeypatch.setattr(
        module, "pp", lambda label, payload, max_len=1400: rendered.append(label)
    )

    exit_code = asyncio.run(module.main())

    assert exit_code == 0
    assert "history_after_forget" in rendered
    assert "recall_after_forget" in rendered
    forget_idx = events.index(("forget", "coding:demo-app"))
    history_idx = events.index(("fetch_history", "coding:demo-app"))
    coding_recall_positions = [
        idx
        for idx, event in enumerate(events)
        if event == ("recall", "coding:demo-app")
    ]
    assert history_idx > forget_idx
    assert history_idx < coding_recall_positions[-1]
