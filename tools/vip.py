#!/usr/bin/env python3
"""tools/vip.py - VIP profile store + the daily brief. The Insider's own loop.

    python3 tools/vip.py sync                        # pull arrivals, upsert profiles
    python3 tools/vip.py show <guest_key>
    python3 tools/vip.py capture <guest_key> --key drinks --value "tawny port" [--source front-desk]
    python3 tools/vip.py capture <guest_key> --address "12 Via Roma, 22100 Como, Italy"
    python3 tools/vip.py key-date <guest_key> --type anniversary --date 2026-09-12 --label "40th anniversary"
    python3 tools/vip.py do-not-contact <guest_key> [--off]

`capture --address` is the only writer of `mailing_address` - nothing seeds
it from a sync. Set it before a key date's letter is due, or
`tools/letters.py scan` will route a `postal` delivery to `needs_human` for
"no mailing address on file" (see workflows/20-handwritten-letter.md).

`sync` only ever touches the factual fields (tier, visits, room_type,
arrival) - `capture` / `key-date` / `do-not-contact` are the only writers of
`preferences_json` / `history_note` / `key_dates_json` / `do_not_contact`,
so a sync can never overwrite the living memory a human built up. See
docs/how-it-works.md "Data model" and decision #3.
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from core.adapters import get_pms  # noqa: E402
from core.adapters.base import AdapterError  # noqa: E402
from core.config import ConfigError, Settings, load_settings  # noqa: E402
from core.review import WriteBlocked  # noqa: E402
from core.store import Item, Store, StoreError, utcnow  # noqa: E402
from profile_engine import build_brief, tier_for  # noqa: E402

SCHEMA = """
CREATE TABLE IF NOT EXISTS vip_profiles (
  id                TEXT PRIMARY KEY,
  guest_key         TEXT NOT NULL,
  guest_name        TEXT NOT NULL,
  tier              TEXT NOT NULL DEFAULT 'Silver',
  visits            INTEGER NOT NULL DEFAULT 0,
  room_type         TEXT,
  arrival_date      TEXT,
  arrival_offset    INTEGER,
  preferences_json  TEXT,
  history_note      TEXT,
  key_dates_json    TEXT,
  mailing_address   TEXT,
  do_not_contact    INTEGER NOT NULL DEFAULT 0,
  created_at        TEXT NOT NULL,
  updated_at        TEXT NOT NULL,
  UNIQUE (guest_key)
);

CREATE TABLE IF NOT EXISTS research_snippets (
  id           TEXT PRIMARY KEY,
  vip_id       TEXT NOT NULL,
  source       TEXT,
  headline     TEXT,
  body         TEXT,
  confidence   TEXT NOT NULL DEFAULT 'unsure',
  needs_human  INTEGER NOT NULL DEFAULT 1,
  reasoning    TEXT,
  provenance   TEXT NOT NULL DEFAULT 'public source — staff verified',
  confirmed_at TEXT,
  created_at   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_research_vip ON research_snippets (vip_id);
"""

#: A brief in one of these review_status values has not been touched by a
#: human yet, so `--rebuild` may safely overwrite its draft and
#: `research.add_snippet`'s stale-brief warning may safely fire for it - see
#: `build_and_queue_briefs` and docs/how-it-works.md "Idempotency".
UNAPPROVED_BRIEF_STATUSES = ("pending_review", "needs_human")


def _guest_key(email: str = "", phone: str = "", name: str = "") -> str:
    return (email or phone or name or "").strip().lower()


def _row_to_profile(row) -> dict:
    return {
        "id": row["id"], "guest_key": row["guest_key"], "guest_name": row["guest_name"],
        "tier": row["tier"], "visits": row["visits"], "room_type": row["room_type"],
        "arrival_date": row["arrival_date"], "arrival_offset": row["arrival_offset"],
        "preferences": json.loads(row["preferences_json"] or "{}"),
        "history_note": row["history_note"] or "",
        "key_dates": json.loads(row["key_dates_json"] or "[]"),
        "mailing_address": row["mailing_address"] or "",
        "do_not_contact": bool(row["do_not_contact"]),
    }


def get_profile(store: Store, guest_key: str) -> dict | None:
    row = store.db.execute("SELECT * FROM vip_profiles WHERE guest_key=?",
                           (guest_key,)).fetchone()
    return _row_to_profile(row) if row else None


def list_profiles_with_key_dates(store: Store) -> list[dict]:
    """Every profile that has at least one tracked key date. Used by tools/letters.py."""
    rows = store.db.execute(
        "SELECT * FROM vip_profiles WHERE key_dates_json IS NOT NULL "
        "AND key_dates_json != '[]'").fetchall()
    return [_row_to_profile(r) for r in rows]


def sync_profiles(settings: Settings, store: Store, pms, *, today: date,
                  lookahead_days: int) -> dict:
    """Pull arrivals for [today, today+lookahead_days] and upsert the factual
    fields only - see the module docstring. Returns {"synced": n, "skipped": n}.
    """
    thresholds = settings.agent_get("tiers", {}) or {}
    stats = {"synced": 0, "skipped": 0}
    seen_ids: set[str] = set()
    for offset in range(0, lookahead_days + 1):
        day = today.fromordinal(today.toordinal() + offset).isoformat()
        for res in pms.list_arrivals(day):
            guest = res.guest
            key = _guest_key(guest.email, guest.phone, guest.full_name)
            if not key or res.id in seen_ids:
                stats["skipped"] += 1
                continue
            seen_ids.add(res.id)
            stays = int(guest.extra.get("stays", 1)) if guest.extra else 1
            tier = str(guest.extra.get("tier") or tier_for(
                stays, platinum_min_stays=int(thresholds.get("platinum_min_stays", 8)),
                gold_min_stays=int(thresholds.get("gold_min_stays", 3))))
            now = utcnow()
            existing = get_profile(store, key)
            if existing is None:
                # Seed preferences/key_dates ONCE, from whatever your PMS
                # already stores on the reservation (many keep a custom-field
                # preferences block) - never again after this. A later sync
                # only ever touches the factual columns below; every other
                # write to the living memory goes through `capture` /
                # `key-date` - see the module docstring and
                # docs/how-it-works.md decision #3.
                seed_prefs = res.extra.get("preferences") or guest.extra.get("preferences") or {}
                seed_dates = res.extra.get("key_dates") or guest.extra.get("key_dates") or []
                store.db.execute(
                    "INSERT INTO vip_profiles (id, guest_key, guest_name, tier, visits, "
                    "room_type, arrival_date, arrival_offset, preferences_json, "
                    "history_note, key_dates_json, created_at, updated_at) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (uuid.uuid4().hex, key, guest.full_name or key, tier, stays,
                     res.room_type_name or res.room_type_id, res.check_in, offset,
                     json.dumps(seed_prefs, ensure_ascii=False), guest.notes or "",
                     json.dumps(seed_dates, ensure_ascii=False), now, now))
            else:
                store.db.execute(
                    "UPDATE vip_profiles SET guest_name=?, tier=?, visits=?, room_type=?, "
                    "arrival_date=?, arrival_offset=?, updated_at=? WHERE guest_key=?",
                    (guest.full_name or key, tier, stays, res.room_type_name or res.room_type_id,
                     res.check_in, offset, now, key))
            stats["synced"] += 1
    return stats


def capture(settings: Settings, store: Store, pms, guest_key: str, *, key: str, value: str,
           source: str = "") -> dict:
    """Add or update one preference key on the living profile. Best-effort PMS note."""
    profile = get_profile(store, guest_key)
    if profile is None:
        raise StoreError(f"no VIP profile for '{guest_key}' - run `python3 tools/vip.py sync` "
                         "first, or check the guest key (email, else phone, else name).")
    prefs = dict(profile["preferences"])
    prefs[key] = value
    store.db.execute("UPDATE vip_profiles SET preferences_json=?, updated_at=? "
                     "WHERE guest_key=?", (json.dumps(prefs, ensure_ascii=False), utcnow(),
                                           guest_key))
    note = f"[{source or 'capture'}] {key}: {value}"
    try:
        pms.add_note(profile["id"], note)
        pms_note = "also written to the PMS"
    except WriteBlocked as exc:
        pms_note = f"not written to the PMS ({exc.reason})"
    except AdapterError as exc:
        pms_note = f"PMS note failed: {exc}"
    return {"guest_key": guest_key, "key": key, "value": value, "pms": pms_note}


def set_mailing_address(store: Store, guest_key: str, *, address: str) -> dict:
    """Record the postal address a handwritten letter would be mailed to.

    The only writer of `mailing_address` - see the module docstring and
    `tools/letters.py::scan`, which reads it to decide `postal` vs
    `in_house` delivery and to route an address-less postal letter to
    `needs_human` (docs/safety.md, workflows/20-handwritten-letter.md).
    """
    profile = get_profile(store, guest_key)
    if profile is None:
        raise StoreError(f"no VIP profile for '{guest_key}' - run `python3 tools/vip.py sync` "
                         "first, or check the guest key (email, else phone, else name).")
    store.db.execute("UPDATE vip_profiles SET mailing_address=?, updated_at=? "
                     "WHERE guest_key=?", (address, utcnow(), guest_key))
    return {"guest_key": guest_key, "mailing_address": address}


def add_key_date(store: Store, guest_key: str, *, date_type: str, on: str, label: str) -> dict:
    profile = get_profile(store, guest_key)
    if profile is None:
        raise StoreError(f"no VIP profile for '{guest_key}'.")
    dates = list(profile["key_dates"])
    dates.append({"id": uuid.uuid4().hex[:8], "type": date_type, "date": on, "label": label})
    store.db.execute("UPDATE vip_profiles SET key_dates_json=?, updated_at=? WHERE guest_key=?",
                     (json.dumps(dates, ensure_ascii=False), utcnow(), guest_key))
    return {"guest_key": guest_key, "key_dates": len(dates)}


def set_do_not_contact(store: Store, guest_key: str, *, on: bool) -> dict:
    profile = get_profile(store, guest_key)
    if profile is None:
        raise StoreError(f"no VIP profile for '{guest_key}'.")
    store.db.execute("UPDATE vip_profiles SET do_not_contact=?, updated_at=? WHERE guest_key=?",
                     (1 if on else 0, utcnow(), guest_key))
    return {"guest_key": guest_key, "do_not_contact": on}


def confirmed_snippets(store: Store, vip_id: str) -> list[dict]:
    """Snippets ready for a brief: confirmed/likely and not flagged needs_human.

    Excludes `unsure` and guardrail-flagged rows until a human confirms them -
    see docs/how-it-works.md decision #2.
    """
    rows = store.db.execute(
        "SELECT * FROM research_snippets WHERE vip_id=? AND needs_human=0 "
        "AND confidence IN ('confirmed','likely') ORDER BY created_at", (vip_id,)).fetchall()
    return [dict(r) for r in rows]


def get_todays_brief(store: Store, profile_id: str, today: date) -> Item | None:
    """The `vip_brief` item already drafted for this profile today, if any.

    Used by `tools/research.py::add_snippet` to warn when a research note is
    logged after that brief was drafted - see `UNAPPROVED_BRIEF_STATUSES`
    and `build_and_queue_briefs`'s `rebuild` argument.
    """
    row = store.db.execute("SELECT * FROM items WHERE kind='vip_brief' AND unique_key=?",
                           (f"{profile_id}:{today.isoformat()}",)).fetchone()
    return Item.from_row(row) if row else None


def build_and_queue_briefs(settings: Settings, store: Store, *, today: date,
                           rebuild: bool = False) -> dict:
    """Build (or skip) a brief for every profile arriving in [today, today+lookahead].

    `rebuild=True` (`tools/run.py --once --rebuild`) refreshes the draft of
    a brief that already exists for today, as long as no human has acted on
    it yet (`review_status` still `pending_review` or `needs_human` - see
    `UNAPPROVED_BRIEF_STATUSES`). That is how research logged *after* the
    day's first pass reaches the brief: re-run with `--rebuild`. An
    approved/edited/sent/rejected brief is never rewritten out from under a
    human decision. See docs/how-it-works.md "Idempotency" and
    `tools/research.py::add_snippet`, which prints the same instruction when
    it detects this situation instead of silently dropping the note.
    """
    lookahead = int(settings.agent_get("brief.lookahead_days", 2))
    horizon = today.fromordinal(today.toordinal() + lookahead).isoformat()
    rows = store.db.execute(
        "SELECT * FROM vip_profiles WHERE arrival_date IS NOT NULL "
        "AND arrival_date >= ? AND arrival_date <= ? ORDER BY arrival_date",
        (today.isoformat(), horizon)).fetchall()
    rules = settings.agent_get("rules", {}) or {}
    sections_cfg = settings.agent_get("sections", {}) or {}
    stats = {"drafted": 0, "skipped": 0, "needs_human": 0, "rebuilt": 0}
    for row in rows:
        profile = _row_to_profile(row)
        offset = (date.fromisoformat(profile["arrival_date"]) - today).days
        profile["arrival_offset"] = offset
        unique_key = f"{profile['id']}:{today.isoformat()}"
        item, created = store.upsert_unique("vip_brief", unique_key, payload={
            "profile_id": profile["id"], "guest_name": profile["guest_name"],
            "tier": profile["tier"], "arrival_date": profile["arrival_date"]})
        if not created and item.draft is not None:
            if rebuild and item.review_status in UNAPPROVED_BRIEF_STATUSES:
                snippets = confirmed_snippets(store, profile["id"])
                brief = build_brief(profile, snippets, rules=rules, sections_cfg=sections_cfg,
                                    today=today)
                store.set_fields(item.id, draft=brief)
                stats["rebuilt"] += 1
                continue
            stats["skipped"] += 1
            continue
        snippets = confirmed_snippets(store, profile["id"])
        brief = build_brief(profile, snippets, rules=rules, sections_cfg=sections_cfg,
                            today=today)
        store.set_fields(item.id, draft=brief)
        # A privacy-flagged profile gets the extra-care lane, not because the
        # brief is uncertain (it never is - every line is traced) but because
        # the whole point of the flag is "read this before you brief anyone".
        status = "needs_human" if brief["private"] else "pending_review"
        updated = store.transition(item.id, status, actor="agent",
                                   detail={"guest": profile["guest_name"]})
        stats["drafted"] += 1
        if updated.review_status == "needs_human":
            stats["needs_human"] += 1
    return stats


def _print_profile(profile: dict) -> None:
    print(f"{profile['guest_name']}  ({profile['guest_key']})")
    print(f"  tier={profile['tier']}  visits={profile['visits']}  "
         f"room={profile['room_type'] or '-'}  arrival={profile['arrival_date'] or '-'}")
    print(f"  do_not_contact={profile['do_not_contact']}")
    if profile["preferences"]:
        print("  preferences:")
        for k, v in profile["preferences"].items():
            print(f"    {k}: {v}")
    if profile["key_dates"]:
        print("  key dates:")
        for d in profile["key_dates"]:
            print(f"    {d['date']}  {d['type']}  {d['label']}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("sync", help="pull upcoming arrivals from the PMS")

    p_show = sub.add_parser("show", help="print one profile")
    p_show.add_argument("guest_key")

    p_capture = sub.add_parser(
        "capture", help="add/update one preference key, or record a mailing address")
    p_capture.add_argument("guest_key")
    p_capture.add_argument("--key", help="preference key, e.g. drinks (needs --value)")
    p_capture.add_argument("--value", help="the preference value (needs --key)")
    p_capture.add_argument("--address",
                           help="postal mailing address on its own, e.g. "
                                '"12 Via Roma, 22100 Como, Italy" (instead of --key/--value)')
    p_capture.add_argument("--source", default="")

    p_kd = sub.add_parser("key-date", help="track a birthday / anniversary / milestone")
    p_kd.add_argument("guest_key")
    p_kd.add_argument("--type", required=True, choices=["anniversary", "birthday", "stay_milestone"])
    p_kd.add_argument("--date", required=True, dest="on", help="YYYY-MM-DD, next occurrence")
    p_kd.add_argument("--label", required=True, help='e.g. "40th anniversary"')

    p_dnc = sub.add_parser("do-not-contact", help="suppress letters for this guest")
    p_dnc.add_argument("guest_key")
    p_dnc.add_argument("--off", action="store_true", help="clear the flag instead of setting it")

    args = parser.parse_args(argv)
    try:
        settings = load_settings()
    except ConfigError as exc:
        print(f"config error: {exc}", file=sys.stderr)
        return 1

    store = Store(settings)
    store.migrate(SCHEMA)
    try:
        if args.command == "sync":
            pms = get_pms(settings)
            stats = sync_profiles(settings, store, pms, today=date.today(),
                                  lookahead_days=int(settings.agent_get("brief.lookahead_days", 2)))
            print(f"synced {stats['synced']} arrival(s), {stats['skipped']} skipped "
                 "(no email/phone/name to key on, or already seen this pass)")
            return 0
        if args.command == "show":
            profile = get_profile(store, args.guest_key)
            if profile is None:
                print(f"no VIP profile for '{args.guest_key}'", file=sys.stderr)
                return 1
            _print_profile(profile)
            return 0
        if args.command == "capture":
            if args.address:
                if args.key or args.value:
                    parser.error("capture takes --address on its own, not with --key/--value")
                result = set_mailing_address(store, args.guest_key, address=args.address)
                print(f"mailing address on file for {result['guest_key']} - postal letters "
                     "can now use it (see workflows/20-handwritten-letter.md)")
                return 0
            if not args.key or not args.value:
                parser.error("capture needs either --address, or both --key and --value")
            pms = get_pms(settings)
            result = capture(settings, store, pms, args.guest_key, key=args.key,
                             value=args.value, source=args.source)
            print(f"captured {result['key']}={result['value']!r} for {result['guest_key']} "
                 f"({result['pms']})")
            return 0
        if args.command == "key-date":
            result = add_key_date(store, args.guest_key, date_type=args.type, on=args.on,
                                  label=args.label)
            print(f"{args.guest_key} now has {result['key_dates']} key date(s) on file")
            return 0
        if args.command == "do-not-contact":
            result = set_do_not_contact(store, args.guest_key, on=not args.off)
            print(f"{args.guest_key}: do_not_contact={result['do_not_contact']}")
            return 0
        parser.error(f"unknown command {args.command}")
        return 2
    except StoreError as exc:
        print(f"cannot do that: {exc}", file=sys.stderr)
        return 1
    except AdapterError as exc:
        print(f"integration error: {exc}", file=sys.stderr)
        print("Run `make doctor` to see what is missing and how to fix it.", file=sys.stderr)
        return 1
    finally:
        store.close()


if __name__ == "__main__":
    raise SystemExit(main())
