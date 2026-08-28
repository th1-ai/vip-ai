"""A real (not `make demo`) pass on a fresh clone reads the shipped fixtures,
because every `config/*.example.yaml` ships with `adapter: mock`. Core tags
anything read that way with payload `_sample: True` (`core.store.Store.upsert_item`
via `core.adapters.is_sample_source`; `item.is_sample` reads it back) - this repo
does not re-implement the tagging, it only consumes it.

These tests pin the consuming half: `make review` must say `[SAMPLE DATA]` in
both the `list` line and the `show` output, so a duty manager can never mistake
an invented VIP for one of their own arrivals.

`tests/conftest.py`'s autouse fixture isolates AGENT_CONFIG_DIR/AGENT_REPO_ROOT
for this module.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

REPO_ROOT = Path(__file__).resolve().parent.parent
for p in (REPO_ROOT, REPO_ROOT / "tools"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from core.config import load_settings  # noqa: E402
from core.store import Store  # noqa: E402
from review import cmd_list, cmd_show  # noqa: E402


def _queued_brief(tmp_path):
    """One `vip_brief` read from the PMS on the shipped `mock` default."""
    settings = load_settings()
    assert settings.systems.pms.adapter == "mock"  # the shipped default
    assert settings.demo is False  # the real path, not `make demo`
    store = Store(settings, path=tmp_path / "test.db")
    item = store.upsert_item("pms", "res-9001", kind="vip_brief", payload={
        "profile_id": "p-1", "guest_name": "Amelia Rossi", "tier": "platinum",
        "arrival_date": "2026-09-12"})
    store.transition(item.id, "pending_review", actor="agent")
    return store, store.get_item(item.id)


def test_a_real_pass_on_the_mock_default_tags_its_item_sample(tmp_path):
    store, item = _queued_brief(tmp_path)
    store.close()
    assert item.is_sample is True
    assert item.payload.get("_sample") is True


def test_review_list_shows_the_sample_marker(tmp_path, capsys):
    store, item = _queued_brief(tmp_path)
    capsys.readouterr()
    cmd_list(store, SimpleNamespace(status=None, kind=None, limit=50))
    store.close()
    out = capsys.readouterr().out
    assert "[SAMPLE DATA]" in out
    assert "not your property" in out


def test_review_show_warns_before_the_json(tmp_path, capsys):
    store, item = _queued_brief(tmp_path)
    capsys.readouterr()
    cmd_show(store, SimpleNamespace(id=item.id))
    store.close()
    out = capsys.readouterr().out
    assert out.startswith("[SAMPLE DATA]")
