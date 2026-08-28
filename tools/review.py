#!/usr/bin/env python3
"""tools/review.py - work the review queue: list / show / approve / edit / reject / send.

    python3 tools/review.py list [--status pending_review] [--kind vip_brief]
    python3 tools/review.py show <id>
    python3 tools/review.py approve <id> [--note "..."]
    python3 tools/review.py edit <id> --body-file draft.txt [--subject "..."] [--note "..."]
    python3 tools/review.py reject <id> --reason "wrong tone"
    python3 tools/review.py retry <id>          # re-queue a failed send
    python3 tools/review.py send [--kind vip_brief|letter]
    python3 tools/review.py stale               # go-live step, see workflows/90-go-live.md

Two item kinds share this one queue: ``vip_brief`` (draft = the brief dict,
`gm_line`/`housekeeping`/`fnb`/`front_office`) and ``letter`` (draft =
{subject, body}). ``send`` dispatches each claimed item by its ``kind`` - a
brief goes to ``messaging.notify_staff`` then, on success, a follow-on
``sheets.append``; a letter goes to ``tools/letters.py:dispatch`` (a local
file write, no handwriting robot - see docs/how-it-works.md). Only this tool
writes `approved` / `edited` / `rejected` / `stale`; only `send` writes
`sending` / `sent`. Nothing here bypasses `mode: shadow` - every dispatch is
guarded by `core.review.assert_write_allowed`, which blocks every send while
shadow is on, approved or not - see docs/safety.md.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from core.adapters import get_messaging, get_sheets  # noqa: E402
from core.adapters.base import AdapterError, AdapterNotImplemented  # noqa: E402
from core.config import ConfigError, load_settings  # noqa: E402
from core.log import get_logger  # noqa: E402
from core.review import (WriteBlocked, approve, edit, list_queue, reject,  # noqa: E402
                         retry, show, stale_backlog)
from core.store import Store, StoreError  # noqa: E402
from letters import dispatch as dispatch_letter  # noqa: E402
from vip import SCHEMA  # noqa: E402

log = get_logger("review", quiet=True)


def _print_item_line(item) -> None:
    payload = item.payload or {}
    detail = payload.get("occasion") or payload.get("tier", "")
    who = payload.get("guest_name") or "?"
    marker = "[SAMPLE DATA] " if item.is_sample else ""
    print(f"  {item.id}  {item.review_status:<14} {item.kind:<10} {who[:24]:<24} "
          f"{detail[:28]:<28} {marker}".rstrip())


def cmd_list(store, args) -> int:
    items = list_queue(store, status=args.status, kind=args.kind, limit=args.limit)
    if not items:
        print("Nothing is waiting for you.")
        return 0
    print(f"{len(items)} item(s) waiting:\n")
    for item in items:
        _print_item_line(item)
    if any(item.is_sample for item in items):
        print("\n[SAMPLE DATA] One or more items above were built from the shipped "
              "sample fixtures, not your property - systems.pms.adapter is 'mock'. "
              "Connect a real PMS (docs/integrations.md) before approving them.")
    print("\nRun `python3 tools/review.py show <id>` for the full draft.")
    return 0


def cmd_show(store, args) -> int:
    try:
        detail = show(store, args.id)
    except KeyError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    payload = (detail.get("item") or {}).get("payload") or {}
    if payload.get("_sample"):
        print("[SAMPLE DATA] This item was built from the shipped sample fixtures, not "
              "your property - systems.pms.adapter is 'mock'. Connect a real PMS "
              "(docs/integrations.md) before approving it.\n")
    print(json.dumps(detail, indent=2, ensure_ascii=False, default=str))
    return 0


def cmd_approve(store, args) -> int:
    item = approve(store, args.id, note=args.note or "")
    log.info("approved", item_id=item.id, kind=item.kind)
    print(f"approved {item.id} - now in the send queue")
    return 0


def cmd_edit(store, args) -> int:
    item = store.get_item(args.id)
    if item is None:
        print(f"error: no item {args.id}", file=sys.stderr)
        return 1
    try:
        body = Path(args.body_file).read_text(encoding="utf-8")
    except OSError as exc:
        print(f"error: cannot read {args.body_file}: {exc}", file=sys.stderr)
        return 1
    new_draft = dict(item.draft or {})
    if item.kind == "letter":
        new_draft["body"] = body
        if args.subject:
            new_draft["subject"] = args.subject
    else:
        new_draft["gm_line"] = body
    edit(store, args.id, new_draft, note=args.note or "")
    log.info("edited", item_id=item.id, kind=item.kind)
    print(f"edited {item.id} - now in the send queue")
    return 0


def cmd_reject(store, args) -> int:
    item = reject(store, args.id, reason=args.reason or "")
    log.info("rejected", item_id=item.id, kind=item.kind, reason=args.reason or "")
    print(f"rejected {item.id}")
    return 0


def cmd_retry(store, args) -> int:
    item = retry(store, args.id)
    log.info("retry queued", item_id=item.id, kind=item.kind)
    print(f"queued {item.id} for another send attempt")
    return 0


def _format_brief_text(payload: dict, brief: dict) -> str:
    lines = [f"VIP brief - {payload.get('guest_name', '')} "
            f"({payload.get('tier', '')}, {payload.get('arrival_date', '')})"]
    for section, label in (("housekeeping", "Housekeeping"), ("fnb", "F&B"),
                           ("front_office", "Front office")):
        rows = brief.get(section) or []
        if not rows:
            continue
        lines.append(f"{label}:")
        lines += [f"  - {row['text']}" for row in rows]
    lines += ["", brief.get("gm_line", "")]
    return "\n".join(lines)


def dispatch_brief(settings, item) -> dict:
    """`messaging.notify_staff` (guarded), then a best-effort sheets export."""
    messaging = get_messaging(settings)
    brief = item.draft or {}
    text = _format_brief_text(item.payload or {}, brief)
    result = messaging.notify_staff(text, item=item)  # raises WriteBlocked in shadow
    try:
        sheet = settings.agent_get("review_notify.duty_team_sheet", "vip_briefs")
        sheets = get_sheets(settings)
        payload = item.payload or {}
        sheets.append(sheet, [[item.id, payload.get("guest_name", ""),
                              payload.get("arrival_date", ""), brief.get("gm_line", "")]],
                     item=item)
        result = {**result, "sheet": sheet}
    except (AdapterError, AdapterNotImplemented) as exc:
        # Best-effort: the guarded send above is what "dispatched" means.
        log.warn("sheets export skipped", item_id=item.id, error=str(exc))
    return result


def cmd_send(store, settings, args) -> int:
    items = store.list_items(status=["approved", "edited"], kind=args.kind, limit=args.limit)
    if not items:
        print("Nothing approved or edited is waiting to send.")
        return 0
    sent, failed = 0, 0
    for item in items:
        claimed = store.transition(item.id, "sending", actor="agent", detail={"claim": True})
        try:
            if claimed.kind == "letter":
                result = dispatch_letter(settings, store, claimed)
                store.mark_sent(claimed.id, result.get("file"))
            else:
                result = dispatch_brief(settings, claimed)
                store.mark_sent(claimed.id, result.get("message_id"))
        except WriteBlocked as exc:
            # Not a failure: the mode blocked it. The approval stands - see
            # core/store.py TRANSITIONS ("sending" -> "approved" is the
            # shadow-block path; "failed" means a real send failure, below).
            store.transition(item.id, "approved", "agent", {"blocked": str(exc)[:200]})
            log.info("send blocked", item_id=item.id, kind=item.kind, reason=str(exc))
            print(f"blocked {item.id} (approval kept): {exc}")
            failed += 1
            continue
        except Exception as exc:  # noqa: BLE001 - record and move on, never crash the batch
            store.mark_send_failed(item.id, str(exc))
            log.warn("send failed", item_id=item.id, kind=item.kind, error=str(exc))
            print(f"failed {item.id}: {exc}")
            failed += 1
            continue
        log.info("sent", item_id=item.id, kind=item.kind)
        print(f"sent {item.id} ({item.kind})")
        sent += 1
    print(f"\n{sent} sent, {failed} failed.")
    return 0 if failed == 0 else 1


def cmd_stale(store, args) -> int:
    moved = stale_backlog(store)
    log.info("marked stale", count=len(moved), item_ids=moved)
    print(f"marked {len(moved)} item(s) stale. Nothing from before go-live will be sent.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)

    p_list = sub.add_parser("list", help="what is waiting for a human")
    p_list.add_argument("--status", default=None)
    p_list.add_argument("--kind", default=None, choices=["vip_brief", "letter"])
    p_list.add_argument("--limit", type=int, default=50)

    p_show = sub.add_parser("show", help="full detail for one item")
    p_show.add_argument("id")

    p_approve = sub.add_parser("approve", help="approve the draft unchanged")
    p_approve.add_argument("id")
    p_approve.add_argument("--note", default="")

    p_edit = sub.add_parser("edit", help="rewrite the draft, then queue it")
    p_edit.add_argument("id")
    p_edit.add_argument("--body-file", required=True)
    p_edit.add_argument("--subject", default=None, help="letters only")
    p_edit.add_argument("--note", default="")

    p_reject = sub.add_parser("reject", help="discard the draft")
    p_reject.add_argument("id")
    p_reject.add_argument("--reason", "--note", dest="reason", default="")

    p_retry = sub.add_parser("retry", help="re-queue a failed send")
    p_retry.add_argument("id")

    p_send = sub.add_parser("send", help="send everything approved or edited")
    p_send.add_argument("--limit", type=int, default=20)
    p_send.add_argument("--kind", default=None, choices=["vip_brief", "letter"])

    sub.add_parser("stale", help="go-live step: mark everything still un-sent as stale "
                                 "(the shadow-era queue was never sent and is out of date)")

    args = parser.parse_args(argv)
    try:
        settings = load_settings()
    except ConfigError as exc:
        print(f"config error: {exc}", file=sys.stderr)
        return 1

    store = Store(settings)
    store.migrate(SCHEMA)
    try:
        if args.command == "list":
            return cmd_list(store, args)
        if args.command == "show":
            return cmd_show(store, args)
        if args.command == "approve":
            return cmd_approve(store, args)
        if args.command == "edit":
            return cmd_edit(store, args)
        if args.command == "reject":
            return cmd_reject(store, args)
        if args.command == "retry":
            return cmd_retry(store, args)
        if args.command == "send":
            return cmd_send(store, settings, args)
        if args.command == "stale":
            return cmd_stale(store, args)
        parser.error(f"unknown command {args.command}")
        return 2
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
