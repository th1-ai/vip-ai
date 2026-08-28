# Workflow: troubleshooting

Read the whole error before doing anything - every tool here says what broke
and what to do about it. If you fix something not covered below, add it here.

## `make doctor` shows a FAIL

Each `FAIL` line has a `->` fix hint right under it. Common ones:

- **`hotel identity`: name is still 'Hotel Aurora'.** Expected on a fresh
  clone. Edit `config/hotel.yaml`.
- **`tier thresholds`: platinum_min_stays must be greater than
  gold_min_stays.** Fix `config/agent.yaml`'s `tiers:` block.
- **An adapter shows FAIL, not warn.** `universal`/`built` adapters fail
  loud when misconfigured; a `warn` is reserved for stubs and for
  Handwritten Letter AI being off (that one is expected until you turn it
  on - `docs/sub-agents.md`).

## `make demo` does not print `DEMO OK`

- Make sure `make setup` ran first (`.venv` must exist).
- `tools/demo.py` runs "as of" 2026-09-10, matching
  `fixtures/hotel/reservations.json` - if you edited that file, the fixed
  commentary will drift, but `DEMO OK` should still print with whatever
  counts your edit produced.
- Read the traceback if there is one; `tools/demo.py` does not swallow
  errors on purpose.

## `python3 tools/research.py add` exits with code 3

Not an error. `llm.provider: interactive` parked the prompt. Read
`data/pending/<id>.prompt.md`, write your answer to the matching
`*.answer.json` (must match the schema in the same folder), and run the same
command again.

## A VIP isn't getting a brief

Run the sync and brief pass directly:

```bash
python3 tools/run.py --once --only briefs
python3 tools/vip.py show <guest email>
```

Common reasons: the guest's email/phone/name didn't come through on the
reservation (nothing to key the profile on - check `guest_key` matching in
`tools/vip.py:_guest_key`), the arrival is outside
`brief.lookahead_days`, or a brief for today already exists (one per guest
per day - `docs/how-it-works.md`).

## A research note keeps coming back `needs_human`

That is usually correct, not broken - see `docs/safety.md`, "A research note
that infers health, family or money gets flagged, not dropped silently." If
you are certain the flag is wrong (a clean, confirmable match that the model
mis-scored), `python3 tools/research.py confirm <id>` is the human override.

## A letter is stuck without an address

`needs_human` with "no mailing address on file" means the guest is meant to
get this letter by post (either `mailing_address` was already on file, or
staff captured `--key delivery --value postal` ahead of one being on file)
but `profile.mailing_address` is still empty. Set one - `sync` never does
this for you, it only ever touches the factual fields (`docs/how-it-works.md`
decision 17):

```bash
python3 tools/vip.py capture <guest email> --address "12 Via Roma, 22100 Como, Italy"
python3 tools/letters.py scan     # re-scan; this key date now routes to pending_review
```

Or change the guest's key date to an in-house occasion if that's what you meant.

## A research note doesn't show up on today's brief

The brief was already drafted before you logged the note - `tools/research.py
add` will have told you so ("brief for today was already drafted..."). Run:

```bash
python3 tools/run.py --once --only briefs --rebuild
```

This only refreshes a brief still `pending_review`/`needs_human` - if it has
already been approved, edited or sent, add the note to tomorrow's brief
instead, or use `python3 tools/review.py edit <id>` to hand-add it to the one
already reviewed. See `docs/how-it-works.md` "Idempotency" and decision 20.

## An item is stuck at `sending`

A process died between claiming an item and finishing the send.
`tools/run.py`'s own pass does not reap this table (only `tools/review.py
send` claims items here); if you see one stuck for a long time, ask your
Claude session to run `core.store.Store.reap_stuck_sending()` and then
`python3 tools/review.py retry <id>`.

## `python3 tools/*.py` says `ModuleNotFoundError: No module named 'core'`

You ran it with a Python that is not the repo's virtualenv, or from outside
the repo root. Use `make run` / `make doctor` / etc. (they call
`.venv/bin/python` for you), or run `.venv/bin/python tools/run.py`
directly from the repo root.

## Still stuck

`data/logs/*.jsonl` has every decision the agent made, in order, with a run
id. `python3 tools/review.py show <id>` has the full event trail for one
item. If neither explains it, that is a real bug - describe exactly what you
ran and what you expected, and ask.
