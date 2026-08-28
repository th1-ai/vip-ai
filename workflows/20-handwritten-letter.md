# Workflow: Handwritten Letter AI ("The Scribe")

Objective: turn a tracked key date into a letter draft, get it approved, and
dispatch it — with no handwriting-robot API called anywhere, see
`docs/how-it-works.md` decision #13.

Off by default. Before running any of this, decide whether you actually want
it on: `docs/sub-agents.md` and `config/agent.yaml`:

```yaml
subagents:
  handwritten_letter:
    enabled: true
```

## Steps

1. **Track a key date.** The Scribe never invents one - see
   `workflows/10-vip-brief.md` step 3.
   ```bash
   python3 tools/vip.py key-date <guest email> --type anniversary --date 2026-10-02 --label "25th anniversary"
   ```

1b. **If this letter should go in the post, say so - and record an address.**
   Nothing seeds `mailing_address` on its own, and delivery only becomes
   `postal` when there is a reason to think it should be - `docs/how-it-works.md`
   decision 17. Skip both for an in-house letter (placed at turndown, the
   default for a guest who is arriving).
   ```bash
   python3 tools/vip.py capture <guest email> --key delivery --value postal
   python3 tools/vip.py capture <guest email> --address "12 Via Roma, 22100 Como, Italy"
   ```
   Know the address already? The second command alone is enough - having
   one on file also means `postal`. Know only that the letter must be
   mailed, not yet where to? Run the first command now; the scan below
   routes that guest to `needs_human` ("no mailing address on file") until
   you add the address.

2. **Scan.**
   ```bash
   python3 tools/letters.py scan                      # real "today"
   python3 tools/letters.py scan --as-of 2026-09-20    # testing
   ```
   Queues a letter for every key date inside
   `subagents.handwritten_letter.lookahead_days` (default 14) that doesn't
   already have one for that occasion and year (`docs/how-it-works.md`
   decision #14). A `do_not_contact` guest is skipped outright. A `postal`
   delivery with no `mailing_address` on the profile goes to `needs_human`
   instead of building an undeliverable letter.

3. **Read and decide.** Every letter needs a human - there is no threshold
   that skips this, high-value guest or not (`docs/how-it-works.md` decision
   #15).
   ```bash
   python3 tools/review.py list --kind letter
   python3 tools/review.py show <id>
   python3 tools/review.py approve <id>
   python3 tools/review.py edit <id> --body-file my-version.txt
   ```
   `edit` here rewrites the whole body - the robot (or the person) copies
   exactly what you leave in the file.

4. **Dispatch.**
   ```bash
   python3 tools/review.py send --kind letter
   ```
   Writes a print-ready `.txt` file to `data/exports/letters/<item-id>.txt`.
   For a `postal` delivery it also tries the `Courier` stub, which is
   expected to fail with `AdapterNotImplemented` - read the printed line,
   it tells you to hand the file to your own mail/courier process. `mode:
   shadow` blocks this whole step, approved or not - see `docs/safety.md`.

## What runs when

| Job | Cadence | Command |
|---|---|---|
| Letter scan | every morning, after the VIP brief | `python3 tools/letters.py scan` |

In `config/agent.yaml: schedule.letters_scan` - `make schedule ARGS="--all"`
prints it. Safe to leave scheduled even while disabled: `scan` no-ops and
says so.
