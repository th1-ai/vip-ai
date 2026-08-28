"""Regression test for SIMULATION.md finding 1 (BLOCKER).

The `csv` PMS adapter is the one docs/integrations.md says to "start with" -
and it is the one real hotels actually use on day one, since Cloudbeds
credentials rarely exist yet. This drives `tools/vip.py sync` end to end
through the real `csv` adapter (not the `mock` fixtures every other test in
this repo uses), reproducing the simulation's exact case: a 9-stay Platinum
guest and a guest whose reservation carries a privacy note. Both must reach
the VIP profile / brief correctly - see docs/integrations.md "the one that
always works" and core/adapters/pms_csv.py.
"""

from __future__ import annotations

import csv
import sys
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
for p in (REPO_ROOT, REPO_ROOT / "tools", Path(__file__).resolve().parent):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from core.adapters import get_pms  # noqa: E402
from core.config import load_settings  # noqa: E402
from core.store import Store  # noqa: E402
from vip import (SCHEMA, build_and_queue_briefs, get_profile,  # noqa: E402
                 sync_profiles)

TODAY = date(2026, 9, 10)

RESERVATIONS_HEADER = [
    "id", "guest_email", "guest_first_name", "guest_last_name", "check_in",
    "check_out", "room_type_name", "tier", "stays", "guest_notes",
]


def _write_reservations(imports_dir: Path, rows: list[list[str]]) -> None:
    imports_dir.mkdir(parents=True, exist_ok=True)
    with (imports_dir / "reservations.csv").open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(RESERVATIONS_HEADER)
        writer.writerows(rows)


def _csv_settings(tmp_path: Path, monkeypatch) -> tuple:
    """Isolated repo root + config dir, `systems.pms.adapter: csv`."""
    monkeypatch.setenv("AGENT_REPO_ROOT", str(tmp_path))
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "hotel.yaml").write_text(
        "hotel:\n  name: Villa Contessa\n  currency: EUR\n  languages: [it, en]\n"
        "systems:\n  pms:\n    adapter: csv\n  email:\n    adapter: mock\n"
        "  messaging:\n    adapter: mock\n  sheets:\n    adapter: csv\n"
        "mode: shadow\nllm:\n  provider: mock\n", encoding="utf-8")
    (config_dir / "agent.yaml").write_text(
        "tiers:\n  platinum_min_stays: 8\n  gold_min_stays: 3\n"
        "brief:\n  lookahead_days: 2\n"
        "rules:\n  brief_daily: true\n  vip_first: true\n", encoding="utf-8")
    monkeypatch.setenv("AGENT_CONFIG_DIR", str(config_dir))
    settings = load_settings(provider="mock", mode="shadow")
    return settings, tmp_path


def test_csv_sync_carries_tier_stays_and_privacy_note_into_the_profile(tmp_path, monkeypatch):
    settings, root = _csv_settings(tmp_path, monkeypatch)
    _write_reservations(root / "data" / "imports", [
        ["R1", "isabella.conti@example.com", "Isabella", "Conti", "2026-09-10",
         "2026-09-12", "Lake Suite", "Platinum", "9", ""],
        ["R2", "helena.reiss@example.com", "Helena", "Reiss", "2026-09-11",
         "2026-09-13", "Garden Room", "", "5", "discreet, no publicity please"],
    ])
    store = Store(settings, path=root / "data" / "vip.db")
    store.migrate(SCHEMA)
    pms = get_pms(settings)

    stats = sync_profiles(settings, store, pms, today=TODAY, lookahead_days=2)
    assert stats["synced"] == 2

    isabella = get_profile(store, "isabella.conti@example.com")
    assert isabella["tier"] == "Platinum"
    assert isabella["visits"] == 9  # not silently reset to 1 - finding 1

    helena = get_profile(store, "helena.reiss@example.com")
    assert helena["tier"] == "Gold"  # 5 stays, no explicit tier column -> tier_for()
    assert "no publicity" in helena["history_note"]

    brief_stats = build_and_queue_briefs(settings, store, today=TODAY)
    assert brief_stats["drafted"] == 2
    assert brief_stats["needs_human"] == 1  # Helena's privacy note routes her brief here

    from vip import get_todays_brief
    helena_brief = get_todays_brief(store, helena["id"], TODAY)
    assert helena_brief.review_status == "needs_human"
    assert helena_brief.draft["private"] is True

    isabella_brief = get_todays_brief(store, isabella["id"], TODAY)
    assert isabella_brief.review_status == "pending_review"
    assert isabella_brief.draft["private"] is False
    store.close()
