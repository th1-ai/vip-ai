# Workflow: working the review queue

Objective: turn a queued brief or letter into a decision - approve, edit, or
reject - and, once approved, actually send it.

Nothing reaches the duty team, and no letter file is written, without going
through this. `mode: shadow` blocks `send_message` and `publish` for
everything, including an item you have approved or edited - shadow is a
global kill switch, not a per-item exception; see `docs/safety.md` for the
full guard.

## Steps

1. **See what is waiting.**
   ```bash
   make review
   python3 tools/review.py list --kind vip_brief
   python3 tools/review.py list --kind letter
   ```
   Each line shows the item id, status, kind, guest, and a short detail.

2. **Read one in full.**
   ```bash
   python3 tools/review.py show <id>
   ```
   For a `vip_brief` item this is the full brief - housekeeping, F&B, front
   office, the GM line - each line with its `trace`. For a `letter` item
   it's the subject and body. Summarize it for the hotel in plain language;
   do not paste the raw JSON at them.

3. **Decide.**
   ```bash
   python3 tools/review.py approve <id>
   python3 tools/review.py edit <id> --body-file my-version.txt
   python3 tools/review.py reject <id> --reason "wrong tone"
   ```
   For a `vip_brief`, `edit` rewrites the GM line (the desk sections are
   trace-backed and meant to be read, not rewritten - if a preference line
   is wrong, fix it at the source with `tools/vip.py capture` and re-run).
   For a `letter`, `edit` rewrites the whole body. `edit` records the
   before/after as a `learnings` row.

4. **Send what was approved.**
   ```bash
   python3 tools/review.py send                    # everything approved/edited, any kind
   python3 tools/review.py send --kind vip_brief    # just the briefs
   python3 tools/review.py send --kind letter       # just the letters
   ```
   `send` dispatches by `kind`: `vip_brief` goes to `messaging.notify_staff`,
   then a best-effort `sheets.append` to the duty-team sheet; `letter` writes
   a print-ready file (`docs/how-it-works.md`). In `mode: shadow` every one
   of these is blocked, even an item you just approved - `send` reports it
   as `blocked` and **keeps the approval**: the item goes right back to
   `approved` (never `failed`), so it stays queued and is picked up the
   moment you switch to `mode: live` - no `retry` needed.

5. **A failed send.** `failed` means a real send failure - the messaging
   adapter rejected it, a file write failed - never a shadow block (step 4
   keeps a shadow-blocked item `approved`, not `failed`).
   ```bash
   python3 tools/review.py retry <id>
   ```

## Rules

- Only `tools/review.py` writes `approved` / `edited` / `rejected` / `stale`.
- `python3 tools/review.py stale` is the go-live step that clears the
  shadow-era backlog (`workflows/90-go-live.md`).
- Confirm with the hotel before sending anything, even an approved item, the
  first few times. `workflows/90-go-live.md` covers when to stop doing that.
