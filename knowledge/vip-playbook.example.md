# VIP playbook - Hotel Aurora

<!--
Copy this to knowledge/vip-playbook.md. This file is for humans reading the
brief, not for the agent's own reasoning (the brief-building code is
deterministic - see docs/how-it-works.md). Use it to brief new duty staff on
how to read and act on a VIP brief, and to record your own tiering policy
alongside config/agent.yaml's `tiers:` block.
-->

## Our tiers

- **Platinum** (`tiers.platinum_min_stays` in `config/agent.yaml`, default 8
  stays): a personal note from the GM on arrival, always offered the same
  room type if available.
- **Gold** (default 3 stays): mentioned by name at check-in, preferences
  read before they arrive.
- **Silver**: everyone else with a profile on file. `rules.vip_first`
  deliberately does not prioritise Silver requests - see
  `docs/how-it-works.md`.

## Reading a brief

Every line in a VIP brief carries a `trace` back to where it came from
(a preference key, a research snippet id, or "profile"). If a line does not
make sense, check `python3 tools/review.py show <id>` for the full trace
before repeating it to a guest.

A brief marked "Greet by name in the suite, never across the lobby" means
the guest's history note or a preference matched our privacy guardrail
(`private`, `discreet`, `never post`, `no publicity`). Use what you know in
person; do not put it in writing, and do not mention it in front of other
guests.

## Adding to a profile

When you learn something worth remembering - a drink order, a seating
preference, an allergy - tell whoever runs this agent, or run it yourself:

```bash
python3 tools/vip.py capture <guest email> --key drinks --value "negroni, no orange peel" --source "front desk, 12 Sep"
```

This updates the profile immediately and also tries to write a matching note
in the PMS, so the memory survives even if this agent stops running.

## Research notes

If you find something about a guest in a public source (their own LinkedIn,
a press mention, a conference bio), log it:

```bash
python3 tools/research.py add --guest <guest email> --source "LinkedIn" --text "what you found"
```

Only paste what is genuinely public. Never paste something inferred about
someone's health, family situation or finances - the agent flags this kind
of note for a second look, but the better habit is not writing it down in
the first place.
