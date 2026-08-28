#!/usr/bin/env python3
"""tools/demo.py - the whole loop on the bundled fixtures, zero credentials.

    make demo
    python3 tools/demo.py

Forces `llm.provider=mock`, `mode=shadow` and `mock` adapters for every
system, reading config/hotel.example.yaml and config/agent.example.yaml
directly regardless of any config/*.yaml a hotel has already filled in
(ARCHITECTURE.md, "works in 5 minutes with zero credentials"). It runs
against its own database (data/demo/demo.db), never data/agent.db.

Handwritten Letter AI is off in the shipped example config - see
docs/sub-agents.md. To see it draft a letter: set
`subagents.handwritten_letter.enabled: true` in
`config/agent.example.yaml` and re-run `make demo` (demo.py always reads the
`.example.yaml` files, never your own `config/agent.yaml`).
"""

from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from core.adapters import get_pms  # noqa: E402
from core.config import ConfigError, load_settings, sub_data_dir  # noqa: E402
from core.log import summary_line  # noqa: E402
from core.store import Store, StoreError  # noqa: E402
from letters import scan as letters_scan  # noqa: E402
from research import add_snippet  # noqa: E402
from vip import SCHEMA, build_and_queue_briefs, sync_profiles  # noqa: E402

DEMO_TODAY = date(2026, 9, 10)  # fixed so `make demo` prints the same thing every time


def main() -> int:
    try:
        settings = load_settings(demo=True)
    except ConfigError as exc:
        print(f"config error: {exc}", file=sys.stderr)
        return 1

    demo_db = sub_data_dir("demo") / "demo.db"
    if demo_db.exists():
        demo_db.unlink()  # every `make demo` is a clean, repeatable run
    store = Store(settings, path=demo_db)
    store.migrate(SCHEMA)

    today = DEMO_TODAY
    print(f"VIP AI demo - arrivals book as of {today.isoformat()} from "
         "fixtures/hotel/reservations.json\n")

    pms = get_pms(settings)
    lookahead = int(settings.agent_get("brief.lookahead_days", 2))
    sync_stats = sync_profiles(settings, store, pms, today=today, lookahead_days=lookahead)
    print(f"Synced {sync_stats['synced']} VIP arrival(s) from the PMS, "
         f"{sync_stats['skipped']} skipped (no email/phone/name to key on).\n")

    research_dir = REPO_ROOT / "fixtures" / "inbound"
    for path in sorted(research_dir.glob("research-note-*.json")):
        note = json.loads(path.read_text(encoding="utf-8"))
        try:
            result = add_snippet(settings, store, guest_key=note["guest_key"],
                                 source=note["source"], text=note["text"],
                                 fixture_id=path.stem, provider="mock")
        except StoreError as exc:
            print(f"  research {path.stem}: skipped ({exc})")
            continue
        flag = " - needs a human look" if result.get("needs_human") else ""
        print(f"  research {path.stem} ({note['guest_key']}): {result['confidence']}{flag}")
        print(f"    {result.get('headline', '')}")
    print()

    brief_stats = build_and_queue_briefs(settings, store, today=today)
    print(f"Built {brief_stats['drafted']} brief(s): {brief_stats['needs_human']} flagged "
         f"for a privacy check before anyone sees them, {brief_stats['skipped']} already "
         "briefed today.\n")
    for item in store.list_items(kind="vip_brief", limit=50):
        brief = item.draft or {}
        payload = item.payload or {}
        print(f"  {item.review_status:<14} {payload.get('guest_name', ''):<22} "
             f"{brief.get('gm_line', '')}")

    letters_lookahead = int(settings.agent_get("subagents.handwritten_letter.lookahead_days", 14))
    letter_stats = letters_scan(settings, store, today=today, lookahead_days=letters_lookahead)
    if letter_stats["disabled"]:
        print("\nHandwritten Letter AI is off by default (subagents.handwritten_letter."
             "enabled: false). Flip it to true in config/agent.example.yaml and re-run "
             "`make demo` to see it draft a letter.")
    else:
        print(f"\nLetters: {letter_stats['drafted']} drafted, "
             f"{letter_stats['needs_human']} need an address, "
             f"{letter_stats['skipped']} skipped.")

    print("\nNothing was sent: mode is shadow, and demo never calls `tools/review.py send`.")
    print("Next: `make review` to see what is waiting, or read workflows/10-vip-brief.md.\n")

    drafted = brief_stats["drafted"] + (0 if letter_stats["disabled"] else letter_stats["drafted"])
    stats = {"processed": sync_stats["synced"], "drafted": drafted, "sent": 0}
    print(f"DEMO OK — {summary_line(stats, settings.mode)}")
    store.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
