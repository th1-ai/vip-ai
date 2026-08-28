# Measuring the benefit

## The business case, from the roster

**Output.** "Every VIP researched, remembered, and briefed to the right
staff before check-in — a compounding memory of your best guests."

**ROI.** +25% VIP repeat rate (guest).

The Scribe adds its own, separate figure: +12% VIP return rate, from "turns
key VIP dates into a personal touch that drives repeat stays and loyalty."

**Honest caveat.** Neither figure is something this repo can prove on its
own — repeat-rate and return-rate are outcomes measured over months, against
a control group this template does not build for you. What follows is what
`tools/report.py` can actually show you today: the volume of memory built
and delivered, which is the leading indicator the roster's figure depends
on. Nothing about "VIP repeat rate" is asserted here beyond the roster's own
words.

## What to track

- **VIP profiles known** — how many returning or notable guests this hotel
  now has a living memory of, and their tier split. Zero to start; grows
  with every `tools/vip.py sync`.
- **Research on file, by confidence** — `confirmed` / `likely` / `unsure`.
  A high `unsure` share means staff are pasting notes faster than they can
  verify them; that is useful signal on its own.
- **Briefs, by status** — how many are waiting for a human, how many were
  sent to the duty team. A brief nobody ever approves is a brief that never
  reaches anyone — watch `pending_review`/`needs_human` for a backlog.
- **Letters, by status** (once the Scribe is on) — drafted, waiting for an
  address, dispatched.
- **LLM spend** — should stay near zero. The only model call in this repo is
  `research_match`, run on demand, not on a schedule.

```bash
make report
```

## Why this shape

Three things the roster's `why` calls out as one job, split across three
tools until now: research, memory, and the daily brief. `tools/report.py`
deliberately reports on all three together (profiles known, research
confidence, briefs sent) rather than picking one metric, because a hotel
that only tracks "briefs sent" cannot tell whether the memory behind them is
actually growing.

## What this repo does not measure

- **Repeat-rate itself.** That lives in the PMS's own reservation history,
  compared over a period longer than this agent has usually been running.
  Pull it from your PMS's own reporting, or from `pms.list_reservations`
  over a wider date range than this agent asks for day to day.
- **Whether a brief changed a staff member's behaviour.** The brief's
  `sent`/read status is as far as this repo's data goes — what happened at
  the front desk after that is not captured here.
