# Workflow: the daily VIP brief

Objective: know who your VIPs are, keep researching and remembering them,
and get every one of them a brief before they arrive.

## Steps

1. **Run the loop.**
   ```bash
   make run                                # sync profiles + build briefs + scan letters
   make run ARGS="--only briefs"           # just the sync + brief pass
   make run ARGS="--dry-run"               # compute nothing new, write nothing
   make run ARGS="--only briefs --rebuild" # refresh today's un-approved briefs (step 4)
   ```
   Pulls arrivals for the next `brief.lookahead_days` days (default 2) from
   the PMS, refreshes each VIP's tier/visits/room/arrival on their profile,
   and builds a brief for each one that doesn't already have one for today.
   No model call happens in this loop - see `docs/how-it-works.md`.

2. **Check the profiles it found.**
   ```bash
   python3 tools/vip.py show <guest email>
   ```
   Prints the tier, visits, preferences, key dates, and whether the guest is
   marked do-not-contact.

3. **Add what you know.** The profile only grows when someone tells it
   something - see `docs/how-it-works.md` decision #3.
   ```bash
   python3 tools/vip.py capture <guest email> --key drinks --value "negroni, no orange peel" --source "front desk"
   python3 tools/vip.py key-date <guest email> --type anniversary --date 2026-10-02 --label "25th anniversary"
   ```
   `capture` also tries to write a matching PMS note (best-effort, guarded
   like any other PMS write).

4. **Log research a human found.** This repo does not scrape anything - see
   `docs/how-it-works.md` decision #1.
   ```bash
   python3 tools/research.py add --guest <guest email> --source "LinkedIn" --text "what you found"
   python3 tools/research.py list --guest <guest email>
   ```
   If `llm.provider: interactive`, this parks a prompt and exits 3 - read
   `data/pending/<id>.prompt.md`, write your answer to the matching
   `*.answer.json`, and re-run. A snippet flagged `unsure` or `needs_human`
   is stored but excluded from every brief until you run
   `python3 tools/research.py confirm <id>`.

   **If the guest's brief for today already exists**, this note will not be
   on it - `research.py add` tells you so. Refresh it:
   ```bash
   make run ARGS="--only briefs --rebuild"
   ```
   Only rebuilds a brief still `pending_review`/`needs_human` - one already
   approved, edited or sent is left alone. See `docs/how-it-works.md`
   "Idempotency" and decision #20.

5. **See what's waiting.**
   ```bash
   make review
   python3 tools/review.py show <id>
   ```
   Summarize the brief for the hotel in plain language - who's arriving,
   what desk each line goes to, and the GM's one-line summary. See
   `workflows/80-review.md` for the full approve/edit/reject/send loop.

## What runs when

| Job | Cadence | Command |
|---|---|---|
| Sync profiles + build briefs | every morning | `python3 tools/run.py --once` |
| Letter scan (if enabled) | every morning, after briefs | `python3 tools/letters.py scan` |

Both are in `config/agent.yaml: schedule:` -
`make schedule ARGS="--all"` prints the exact snippet for each; see
`scheduler/` for cron/launchd/systemd. `workflows/99-troubleshooting.md` if
a scheduled run behaves differently from a manual one.
