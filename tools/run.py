#!/usr/bin/env python3
"""tools/run.py - VIP AI's main loop: sync profiles, build briefs, scan letters.

    python3 tools/run.py --once
    python3 tools/run.py --watch
    python3 tools/run.py --once --only briefs
    python3 tools/run.py --once --only letters
    python3 tools/run.py --once --dry-run
    python3 tools/run.py --once --as-of 2026-09-10
    python3 tools/run.py --once --rebuild        # refresh today's un-approved briefs

One pass: pull VIP arrivals from the PMS, refresh the factual profile fields,
build a brief for every arrival inside the lookahead window, then (if
enabled) scan for letters due soon. Nothing here sends anything -
workflows/80-review.md and docs/safety.md cover the review queue and the
shadow/live switch. There is no LLM call anywhere in this loop - see
docs/how-it-works.md; `tools/research.py` is the one place this repo calls a
model, and it runs on demand, not on a schedule.

`--rebuild` re-runs `build_brief` for any brief already drafted today whose
`review_status` is still `pending_review`/`needs_human` - i.e. no human has
approved, edited or rejected it yet - so a research note logged after the
first pass of the day actually reaches the brief. Without `--rebuild`, a
second pass leaves that brief alone (idempotency), and
`tools/research.py add` prints the same instruction at intake time so this
is never a silent gap. See docs/how-it-works.md "Idempotency".

`--dry-run` computes nothing new at all: it skips the sync and brief/letter
passes entirely rather than trying to undo writes after the fact, since
`vip.sync_profiles` and the brief/letter builders are themselves writes (an
upsert, an item row). Running it twice leaves the database untouched.

Exit codes: 0 ok, 1 a real error. There is no interactive-provider exit here
(3) because this loop never calls the model - see tools/research.py for that
path.
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from core.adapters import get_pms  # noqa: E402
from core.adapters.base import AdapterError  # noqa: E402
from core.config import ConfigError, load_settings  # noqa: E402
from core.log import Run, get_logger  # noqa: E402
from core.store import Store, StoreError  # noqa: E402
from letters import scan as letters_scan  # noqa: E402
from vip import SCHEMA, build_and_queue_briefs, sync_profiles  # noqa: E402

log = get_logger("run")


def one_pass(settings, store, *, only: str, today: date, dry_run: bool,
            rebuild: bool = False) -> tuple[int, dict]:
    stats: dict = {}
    with Run("vip", settings, None if dry_run else store) as run:
        if dry_run:
            return 0, stats
        if only in ("all", "briefs"):
            pms = get_pms(settings)
            lookahead = int(settings.agent_get("brief.lookahead_days", 2))
            stats["sync"] = sync_profiles(settings, store, pms, today=today,
                                          lookahead_days=lookahead)
            stats["briefs"] = build_and_queue_briefs(settings, store, today=today,
                                                      rebuild=rebuild)
        if only in ("all", "letters"):
            letter_lookahead = int(settings.agent_get("subagents.handwritten_letter."
                                                       "lookahead_days", 14))
            stats["letters"] = letters_scan(settings, store, today=today,
                                            lookahead_days=letter_lookahead)
        run.stats = dict(stats)
    return 0, stats


def _print_summary(stats: dict, mode: str) -> None:
    b = stats.get("briefs", {})
    s = stats.get("sync", {})
    parts = []
    if "briefs" in stats:
        parts.append(f"{s.get('synced', 0)} profile(s) synced, {b.get('drafted', 0)} "
                     f"brief(s) drafted, {b.get('needs_human', 0)} need a privacy check, "
                     f"{b.get('skipped', 0)} already briefed today"
                     + (f", {b.get('rebuilt', 0)} rebuilt" if b.get("rebuilt") else ""))
    if "letters" in stats:
        letter_stats = stats["letters"]
        if letter_stats.get("disabled"):
            parts.append("letters: off (subagents.handwritten_letter.enabled: false)")
        else:
            parts.append(f"letters: {letter_stats.get('drafted', 0)} drafted, "
                         f"{letter_stats.get('needs_human', 0)} need an address, "
                         f"{letter_stats.get('skipped', 0)} skipped")
    print(f"VIP RUN OK - {' | '.join(parts) if parts else 'nothing to do'} ({mode})")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument("--once", action="store_true", help="run a single pass (default)")
    mode_group.add_argument("--watch", action="store_true",
                            help="keep running on the configured interval")
    parser.add_argument("--dry-run", action="store_true",
                        help="compute nothing new, write nothing, even in live mode")
    parser.add_argument("--only", choices=["all", "briefs", "letters"], default="all")
    parser.add_argument("--rebuild", action="store_true",
                        help="refresh today's brief for any profile still pending_review/"
                             "needs_human, so newly logged research reaches it")
    parser.add_argument("--as-of", default=None, help="override today, YYYY-MM-DD (testing)")
    parser.add_argument("--poll-seconds", type=int, default=None,
                        help="override the --watch interval (default: agent.yaml or 3600)")
    args = parser.parse_args(argv)

    try:
        settings = load_settings(dry_run=args.dry_run)
    except ConfigError as exc:
        print(f"config error: {exc}", file=sys.stderr)
        return 1

    today = date.fromisoformat(args.as_of) if args.as_of else date.today()
    store = Store(settings)
    store.migrate(SCHEMA)
    try:
        if args.watch:
            poll_seconds = args.poll_seconds or int(settings.agent_get("poll_seconds", 3600))
            while True:
                code, stats = one_pass(settings, store, only=args.only, today=today,
                                       dry_run=args.dry_run, rebuild=args.rebuild)
                _print_summary(stats, settings.mode)
                if code != 0:
                    return code
                time.sleep(poll_seconds)
        code, stats = one_pass(settings, store, only=args.only, today=today,
                               dry_run=args.dry_run, rebuild=args.rebuild)
        _print_summary(stats, settings.mode)
        return code
    except AdapterError as exc:
        print(f"integration error: {exc}", file=sys.stderr)
        print("Run `make doctor` to see what is missing and how to fix it.", file=sys.stderr)
        return 1
    except StoreError as exc:
        print(f"cannot do that: {exc}", file=sys.stderr)
        return 1
    finally:
        store.close()


if __name__ == "__main__":
    raise SystemExit(main())
