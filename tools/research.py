#!/usr/bin/env python3
"""tools/research.py - The Scout, honestly: intake for research a HUMAN already did.

    python3 tools/research.py add --guest <guest_key> --source "LinkedIn" --text "..."
    python3 tools/research.py list [--guest <guest_key>]
    python3 tools/research.py confirm <snippet-id>

This repo does not scrape LinkedIn, Instagram or the press - see
docs/how-it-works.md decision #1. `add` takes a note a staff member found
themselves and pasted here; the one LLM call in this repo (`research_match`)
tidies it into a headline/body and flags low-confidence or guardrail-adjacent
content. `confirm` is the human override for an `unsure`/flagged row a
person has actually checked - only confirmed rows are read by
`profile_engine.build_brief` (`tools/vip.py:confirmed_snippets`).

If the guest's brief for today was already drafted, `add` prints a warning
telling you to run `python3 tools/run.py --once --only briefs --rebuild` -
otherwise the note sits in `research_snippets` but never reaches that brief.
See `tools/vip.py::build_and_queue_briefs` and docs/how-it-works.md
"Idempotency".
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

from core.config import ConfigError, load_settings  # noqa: E402
from core.llm import LLMError, LLMPendingInteractive, LLMSchemaError, complete  # noqa: E402
from core.store import Store, StoreError, utcnow  # noqa: E402
from core.templates import build_prompt  # noqa: E402
from vip import (SCHEMA, UNAPPROVED_BRIEF_STATUSES, get_profile,  # noqa: E402
                 get_todays_brief)

SCHEMAS_DIR = REPO_ROOT / "prompts" / "schemas"
RESEARCH_SCHEMA = json.loads((SCHEMAS_DIR / "research_match.json").read_text(encoding="utf-8"))
PROVENANCE = "public source — staff verified"


def add_snippet(settings, store: Store, *, guest_key: str, source: str, text: str,
                fixture_id: str | None = None, provider: str | None = None,
                today: date | None = None) -> dict:
    profile = get_profile(store, guest_key)
    if profile is None:
        raise StoreError(f"no VIP profile for '{guest_key}' - run `python3 tools/vip.py sync` "
                         "first, or check the guest key.")
    prompt = build_prompt("research_match", settings=settings,
                          item={"guest_name": profile["guest_name"], "source": source,
                               "text": text}, fixture_id=fixture_id)
    result = complete("research_match", prompt, RESEARCH_SCHEMA, settings=settings,
                      provider=provider, store=store, fixture_id=fixture_id)
    data = result.data or {}
    # Deterministic when a fixture_id is given (demo, tests, `make demo`'s
    # printed output must be reproducible) - random otherwise, for real use.
    snippet_id = f"r-{fixture_id}" if fixture_id else f"r-{uuid.uuid4().hex[:8]}"
    store.db.execute(
        "INSERT INTO research_snippets (id, vip_id, source, headline, body, confidence, "
        "needs_human, reasoning, provenance, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (snippet_id, profile["id"], source, data.get("headline", ""), data.get("body", ""),
         data.get("confidence", "unsure"), 1 if data.get("needs_human") else 0,
         data.get("reasoning", ""), PROVENANCE, utcnow()))
    # This note only reaches a brief that has not been built yet today, or one
    # that gets rebuilt - a brief already drafted for today is left alone
    # (idempotency, docs/how-it-works.md). Warn here instead of leaving that
    # a silent gap: see SIMULATION.md finding 5 and workflows/10-vip-brief.md.
    stale_warning = None
    existing_brief = get_todays_brief(store, profile["id"], today or date.today())
    if existing_brief is not None and existing_brief.review_status in UNAPPROVED_BRIEF_STATUSES:
        stale_warning = (
            f"{profile['guest_name']}'s brief for today was already drafted before this "
            "note was logged, so it does not have this yet. Run "
            "`python3 tools/run.py --once --only briefs --rebuild` to refresh it (only "
            "works while the brief is still pending_review/needs_human - not once it is "
            "approved, edited or sent).")
    return {"id": snippet_id, "stale_brief_warning": stale_warning, **data}


def list_snippets(store: Store, *, guest_key: str | None = None) -> list[dict]:
    if guest_key:
        profile = get_profile(store, guest_key)
        if profile is None:
            return []
        rows = store.db.execute("SELECT * FROM research_snippets WHERE vip_id=? "
                                "ORDER BY created_at", (profile["id"],)).fetchall()
    else:
        rows = store.db.execute("SELECT * FROM research_snippets ORDER BY created_at").fetchall()
    return [dict(r) for r in rows]


def confirm(store: Store, snippet_id: str) -> dict:
    row = store.db.execute("SELECT * FROM research_snippets WHERE id=?",
                           (snippet_id,)).fetchone()
    if row is None:
        raise StoreError(f"no research snippet '{snippet_id}'.")
    store.db.execute("UPDATE research_snippets SET needs_human=0, confidence='confirmed', "
                     "confirmed_at=? WHERE id=?", (utcnow(), snippet_id))
    return {"id": snippet_id, "confidence": "confirmed", "needs_human": False}


def _print_snippet(s: dict) -> None:
    flag = " [NEEDS HUMAN]" if s.get("needs_human") else ""
    print(f"  {s['id']}  {s['confidence']:<10}{flag}  {s.get('source', '')}")
    print(f"    {s.get('headline', '')}")
    print(f"    {s.get('body', '')}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)

    p_add = sub.add_parser("add", help="log a research note a human already found")
    p_add.add_argument("--guest", required=True, dest="guest_key")
    p_add.add_argument("--source", required=True, help='e.g. "LinkedIn", "press: FT article"')
    p_add.add_argument("--text", required=True, help="what you found, pasted as plain text")
    p_add.add_argument("--fixture-id", default=None, help="for the mock provider / tests")
    p_add.add_argument("--provider", default=None)

    p_list = sub.add_parser("list", help="show research on file")
    p_list.add_argument("--guest", default=None, dest="guest_key")

    p_confirm = sub.add_parser("confirm", help="human confirms an unsure/flagged snippet")
    p_confirm.add_argument("id")

    args = parser.parse_args(argv)
    try:
        settings = load_settings(provider=getattr(args, "provider", None))
    except ConfigError as exc:
        print(f"config error: {exc}", file=sys.stderr)
        return 1

    store = Store(settings)
    store.migrate(SCHEMA)
    try:
        if args.command == "add":
            try:
                result = add_snippet(settings, store, guest_key=args.guest_key,
                                     source=args.source, text=args.text,
                                     fixture_id=args.fixture_id, provider=args.provider)
            except LLMPendingInteractive as exc:
                print(str(exc))
                return 3
            except LLMSchemaError as exc:
                print(f"the model's answer did not fit the schema: {exc}", file=sys.stderr)
                return 1
            flag = " - NEEDS A HUMAN LOOK" if result.get("needs_human") else ""
            print(f"logged {result['id']} ({result['confidence']}){flag}")
            print(f"  {result.get('headline', '')}")
            if result.get("stale_brief_warning"):
                print(f"WARNING: {result['stale_brief_warning']}")
            return 0
        if args.command == "list":
            snippets = list_snippets(store, guest_key=args.guest_key)
            if not snippets:
                print("No research on file.")
                return 0
            for s in snippets:
                _print_snippet(s)
            return 0
        if args.command == "confirm":
            result = confirm(store, args.id)
            print(f"confirmed {result['id']}")
            return 0
        parser.error(f"unknown command {args.command}")
        return 2
    except StoreError as exc:
        print(f"cannot do that: {exc}", file=sys.stderr)
        return 1
    except LLMError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    finally:
        store.close()


if __name__ == "__main__":
    raise SystemExit(main())
