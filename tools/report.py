#!/usr/bin/env python3
"""tools/report.py - what VIP AI knows, and what it cost.

    make report
    python3 tools/report.py [--since 2026-09-01]

Reads core.store: how many VIPs are known and researched, briefs by status,
letters by status (if the Scribe is on), and LLM spend (research intake is
the only caller of a model in this repo). This is the metric behind the
roster's "every VIP researched, remembered, and briefed" output claim - see
docs/benefits.md.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from core.config import ConfigError, load_settings  # noqa: E402
from core.store import Store  # noqa: E402
from vip import SCHEMA  # noqa: E402


def _counts_by_kind(store: Store) -> dict[str, dict[str, int]]:
    out: dict[str, dict[str, int]] = {}
    rows = store.db.execute(
        "SELECT kind, review_status, COUNT(*) AS n FROM items GROUP BY kind, review_status")
    for row in rows.fetchall():
        out.setdefault(row["kind"], {})[row["review_status"]] = row["n"]
    return out


def _profile_counts(store: Store) -> dict[str, int]:
    rows = store.db.execute("SELECT tier, COUNT(*) AS n FROM vip_profiles GROUP BY tier")
    return {row["tier"]: row["n"] for row in rows.fetchall()}


def _research_counts(store: Store) -> dict[str, int]:
    rows = store.db.execute(
        "SELECT confidence, COUNT(*) AS n FROM research_snippets GROUP BY confidence")
    return {row["confidence"]: row["n"] for row in rows.fetchall()}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--since", default=None, help="ISO timestamp - only count usage after this")
    args = parser.parse_args(argv)

    try:
        settings = load_settings()
    except ConfigError as exc:
        print(f"config error: {exc}", file=sys.stderr)
        return 1

    store = Store(settings)
    store.migrate(SCHEMA)
    try:
        tiers = _profile_counts(store)
        total_profiles = sum(tiers.values())
        print(f"VIP AI report - {settings.hotel.name} ({settings.mode})\n")
        print(f"  VIP profiles known: {total_profiles} "
             f"(Platinum={tiers.get('Platinum', 0)}, Gold={tiers.get('Gold', 0)}, "
             f"Silver={tiers.get('Silver', 0)})")

        research = _research_counts(store)
        total_research = sum(research.values())
        print(f"  Research on file: {total_research} "
             f"(confirmed={research.get('confirmed', 0)}, likely={research.get('likely', 0)}, "
             f"unsure={research.get('unsure', 0)})")

        counts = _counts_by_kind(store)
        for kind, label in (("vip_brief", "Briefs"), ("letter", "Letters")):
            by_status = counts.get(kind, {})
            if not by_status:
                print(f"  {label}: none yet")
                continue
            waiting = sum(n for s, n in by_status.items() if s in ("pending_review", "needs_human"))
            print(f"  {label}: " + ", ".join(f"{s}={n}" for s, n in sorted(by_status.items())))
            if waiting:
                print(f"           {waiting} waiting for a human")

        usage = store.usage_totals(since=args.since)
        print(f"\n  LLM usage{f' since {args.since}' if args.since else ''}: {usage['calls']} "
             f"call(s) (research intake only), {usage['input_tokens']} in / "
             f"{usage['output_tokens']} out tokens, ${usage['cost_usd']:.4f}")
        return 0
    finally:
        store.close()


if __name__ == "__main__":
    raise SystemExit(main())
