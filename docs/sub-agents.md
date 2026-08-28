# Sub-agents in this repo

VIP AI's own promise — research, memory, and the daily brief — stands on its
own. Handwritten Letter AI is folded into this repo but is **off by
default**, because a physical letter is a real cost and a real mailing, not
a free extra a hotel gets just by cloning this repo.

## Handwritten Letter AI — "The Scribe" (`tools/letter_engine.py` + `tools/letters.py`)

**Does.** Sends real handwritten letters (via a robotic-handwriting service)
to VIPs for birthdays, anniversaries, and the milestones it tracks, to
deepen long-term relationships.

**Won't.** Drafts the message for approval on high-value relationships, and
works from the key dates the VIP AI tracks.

**Why.** A handwritten note cuts through where another email never will.
It's how you turn a guest into a regular.

**Output.** Turns key VIP dates into a personal touch that drives repeat
stays and loyalty.

**What this build actually does, honestly.** It watches `key_dates` you (or
another tool) add to a VIP's profile with `tools/vip.py key-date`, drafts a
letter from the preference card the moment one is due, and waits for a human
to approve or edit it — every letter, no threshold. `tools/letters.py
dispatch` then writes a print-ready text file to `data/exports/letters/`.
**No robotic-handwriting service is called anywhere in this repo** — see
`docs/how-it-works.md` decision #13 and `docs/integrations.md`. Hand the
printed file to whichever pen-plotter vendor, or a person with a pen, you
actually use.

**Config:** `subagents.handwritten_letter` in `config/agent.yaml` —
`enabled` (default `false`) and `lookahead_days` (default 14, how far ahead
`scan` watches key dates).

**Enable/disable:**

```yaml
subagents:
  handwritten_letter:
    enabled: true    # VIP AI keeps briefing on its own either way
```

**Workflow:** `workflows/20-handwritten-letter.md`.

## How they talk to each other

The only link is the shared `vip_profiles` table: the Scribe reads
`visits`, `preferences` (`room`, `dining`, `drinks`, `flowers_from`) and
`key_dates` by `vip_id`, and respects `do_not_contact` (see
`docs/how-it-works.md` decision #6 — this flag suppresses letters, not
briefs). There is no message or event between the two tracks. Disabling the
Scribe never touches a `vip_brief` item, and turning it on later starts
watching key dates from whatever is on file at that moment — nothing is
retroactively drafted for a date that already passed while it was off.

## Coach — not applicable

VIP AI is not in `email-coach-ai.appliesTo` (`specs/agents.json`), so the
Email Optimizer / Coach AI layer does not apply here — no `tools/coach.py`,
no `workflows/85-coach-weekly.md`.
