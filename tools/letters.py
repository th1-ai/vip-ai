#!/usr/bin/env python3
"""tools/letters.py - The Scribe: scan key dates, draft letters, dispatch approved ones.

    python3 tools/letters.py scan                 # queue a letter for every due key date
    python3 tools/letters.py scan --as-of 2026-09-10
    python3 tools/letters.py dispatch <item-id>    # write the print-ready file (used by review.py send)

Off by default (`subagents.handwritten_letter.enabled` in config/agent.yaml)
- see docs/sub-agents.md. `scan` is a safe no-op while disabled: it prints
why and returns 0, so a schedule entry can stay in place either way.

Every letter is `pending_review` the moment it is built - there is no
auto-queue path, matching the guardrail: "Drafts the message for approval on
high-value relationships" - here, on every relationship, high-value or not
(docs/how-it-works.md decision #15). `dispatch` never calls a handwriting
robot: see docs/how-it-works.md decision #13.

Delivery is `in_house` (the default) unless a mailing address is on file
(`tools/vip.py capture <guest> --address ...`) or staff say the guest should
get their letters by post ahead of one being on file
(`tools/vip.py capture <guest> --key delivery --value postal`) - see
`_delivery_for` and docs/how-it-works.md decision #17. A `postal` letter
with no address on file goes to `needs_human`, never out the door
undeliverable.
"""

from __future__ import annotations

import argparse
import re
import sys
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from core.adapters import get_stub  # noqa: E402
from core.adapters.base import AdapterError, AdapterNotImplemented  # noqa: E402
from core.config import ConfigError, Settings, load_settings, sub_data_dir  # noqa: E402
from core.review import WriteBlocked, assert_write_allowed  # noqa: E402
from core.store import Item, Store, StoreError  # noqa: E402
from letter_engine import build_letter  # noqa: E402
from vip import SCHEMA, list_profiles_with_key_dates  # noqa: E402

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _slug(text: str) -> str:
    return _SLUG_RE.sub("-", (text or "").lower()).strip("-") or "occasion"


def enabled(settings: Settings) -> bool:
    return bool(settings.agent_get("subagents.handwritten_letter.enabled", False))


def _delivery_for(profile: dict) -> dict:
    """Decide `{"channel": "in_house"|"postal", "address": ...}` for one profile.

    `postal` fires either because a mailing address is already on file, or
    because staff explicitly said so (`tools/vip.py capture <guest> --key
    delivery --value postal`) before one was - which is what makes the
    "no mailing_address on file -> needs_human" guardrail reachable at all:
    with address-presence as the *only* signal, a postal delivery could
    never exist without an address, so it could never be missing one
    either. See docs/how-it-works.md decision #17 and SIMULATION.md
    finding 2. Everything else defaults to `in_house` (placed at turndown),
    same as before.
    """
    wants_postal = (str((profile.get("preferences") or {}).get("delivery", ""))
                    .strip().lower() == "postal")
    if wants_postal or profile["mailing_address"]:
        return {"channel": "postal", "address": profile["mailing_address"]}
    return {"channel": "in_house", "address": ""}


def scan(settings: Settings, store: Store, *, today: date, lookahead_days: int) -> dict:
    """Queue a letter for every key date due inside the lookahead window."""
    stats = {"drafted": 0, "skipped": 0, "needs_human": 0, "disabled": not enabled(settings)}
    if not enabled(settings):
        return stats
    for profile in list_profiles_with_key_dates(store):
        if profile["do_not_contact"]:
            stats["skipped"] += len(profile["key_dates"])
            continue
        for kd in profile["key_dates"]:
            try:
                due = date.fromisoformat(kd["date"])
            except (KeyError, ValueError):
                stats["skipped"] += 1
                continue
            days_out = (due - today).days
            if not (0 <= days_out <= lookahead_days):
                stats["skipped"] += 1
                continue
            year = due.year
            unique_key = f"{profile['id']}:{_slug(kd['label'])}:{year}"
            delivery = _delivery_for(profile)
            letter = build_letter(hotel_name=settings.hotel.name, guest_name=profile["guest_name"],
                                  occasion=kd["label"], visits=profile["visits"],
                                  preferences=profile["preferences"])
            item, created = store.upsert_unique("letter", unique_key, payload={
                "profile_id": profile["id"], "guest_name": profile["guest_name"],
                "occasion": kd["label"], "key_date_type": kd["type"], "delivery": delivery,
                "subject": letter["subject"]})
            if not created:
                stats["skipped"] += 1
                continue
            store.set_fields(item.id, draft=letter)
            no_address = delivery["channel"] == "postal" and not delivery["address"]
            status = "needs_human" if no_address else "pending_review"
            store.transition(item.id, status, actor="agent",
                             detail={"occasion": kd["label"],
                                    "reason": "no mailing address on file" if no_address else None})
            stats["drafted"] += 1
            if no_address:
                stats["needs_human"] += 1
    return stats


def dispatch(settings: Settings, store: Store, item: Item) -> dict:
    """Write the print-ready file. Guarded by `assert_write_allowed(..., "publish", item)`.

    No handwriting-robot API is called anywhere in this build - see
    docs/how-it-works.md decision #13. A postal letter also tries the
    `Courier` stub, which is expected to raise `AdapterNotImplemented`; that
    is caught and logged, never swallowed silently.
    """
    assert_write_allowed(settings, "publish", item)  # raises WriteBlocked in shadow
    payload = item.payload or {}
    draft = item.draft or {}
    out_dir = sub_data_dir("exports") / "letters"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{item.id}.txt"
    path.write_text(
        f"To: {payload.get('guest_name', '')}\n"
        f"Occasion: {payload.get('occasion', '')}\n"
        f"Delivery: {(payload.get('delivery') or {}).get('channel', 'in_house')}\n"
        f"Subject: {draft.get('subject', '')}\n\n{draft.get('body', '')}\n",
        encoding="utf-8")
    result = {"file": str(path)}
    delivery = payload.get("delivery") or {}
    if delivery.get("channel") == "postal":
        courier = get_stub("courier", settings)
        try:
            shipment = courier.create_shipment({
                "item_id": item.id, "address": delivery.get("address", ""),
                "reference": payload.get("occasion", "")})
            result["courier"] = shipment
        except AdapterNotImplemented as exc:
            result["courier"] = (f"not automated: {exc} - hand the file above to your own "
                                 "mail/courier process")
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)

    p_scan = sub.add_parser("scan", help="queue a letter for every due key date")
    p_scan.add_argument("--as-of", default=None, help="override today, YYYY-MM-DD (testing)")

    p_dispatch = sub.add_parser("dispatch", help="write the print-ready file for one item "
                                "(normally called by `tools/review.py send`)")
    p_dispatch.add_argument("id")

    args = parser.parse_args(argv)
    try:
        settings = load_settings()
    except ConfigError as exc:
        print(f"config error: {exc}", file=sys.stderr)
        return 1

    store = Store(settings)
    store.migrate(SCHEMA)
    try:
        if args.command == "scan":
            today = date.fromisoformat(args.as_of) if args.as_of else date.today()
            lookahead = int(settings.agent_get("subagents.handwritten_letter.lookahead_days", 14))
            stats = scan(settings, store, today=today, lookahead_days=lookahead)
            if stats["disabled"]:
                print("Handwritten Letter AI is off (subagents.handwritten_letter.enabled: "
                     "false in config/agent.yaml) - see docs/sub-agents.md. Nothing scanned.")
                return 0
            print(f"letters: {stats['drafted']} drafted, {stats['needs_human']} need an "
                 f"address, {stats['skipped']} skipped ({settings.mode})")
            return 0
        if args.command == "dispatch":
            item = store.get_item(args.id)
            if item is None:
                print(f"error: no item {args.id}", file=sys.stderr)
                return 1
            try:
                result = dispatch(settings, store, item)
            except WriteBlocked as exc:
                print(f"blocked: {exc}", file=sys.stderr)
                return 1
            print(f"wrote {result['file']}")
            if "courier" in result:
                print(f"courier: {result['courier']}")
            return 0
        parser.error(f"unknown command {args.command}")
        return 2
    except StoreError as exc:
        print(f"cannot do that: {exc}", file=sys.stderr)
        return 1
    except AdapterError as exc:
        print(f"integration error: {exc}", file=sys.stderr)
        return 1
    finally:
        store.close()


if __name__ == "__main__":
    raise SystemExit(main())
