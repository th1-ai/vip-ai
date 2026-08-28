# Guardrails and safety

This agent talks to your guests and touches your systems. Everything below is
built in, not optional, and this page explains what it does and what is left for
you to decide.

## The two modes

| Mode | What happens |
|---|---|
| `shadow` (default) | The agent reads, thinks, drafts and queues. It **never** sends a message and **never** writes to your PMS. Approving, editing or rejecting a draft records your decision (and teaches the agent) but sends nothing. At go-live, `python3 tools/review.py stale` clears that shadow-era queue so nothing old goes out by surprise. |
| `live` | Items you approved are really sent. Everything else still waits. |

`mode` lives in `config/hotel.yaml`. It is a global kill switch: flipping it back
to `shadow` stops every outbound action immediately, mid-schedule, with no other
change. `config/agent.yaml` can be stricter than `hotel.yaml`, never looser.

Two more brakes:

- `make run ARGS="--dry-run"` computes everything and writes nothing, even in
  live mode. Use it when you change a prompt.
- `review.require_approval_for` in `config/hotel.yaml` lists the actions that
  need a human even in live mode. The defaults are `send_email`, `send_message`,
  `pms_write`, `payment`, `publish`. Shortening that list is how you hand the
  agent more rope, one action at a time.

Every outbound action in the codebase goes through one function,
`core/review.py:assert_write_allowed`. There is no second path.

## The review queue

Nothing reaches a guest without passing through the queue.

```bash
make review                       # what is waiting
python3 tools/review.py show <id>  # the full draft and how it got there
python3 tools/review.py approve <id>
python3 tools/review.py edit <id> --body-file my-version.txt
python3 tools/review.py reject <id> --reason "wrong tone"
```

An item moves `new -> classified -> drafted -> pending_review` and then waits.
Only `tools/review.py` can write `approved`, `edited` or `rejected`; only
`tools/run.py` can write `sent`. A crash between "about to send" and "sent" is
picked up on the next pass and shown to you as failed rather than silently
retried.

**Your edits teach it.** When you rewrite a draft, the before and after are
stored. Over time that is what makes the drafts sound like your hotel instead of
like a machine.

## What the agent will not do

- Send anything while `mode: shadow`.
- Send an item a human has not approved, when the action needs approval.
- Take a payment, issue a refund, or move money. Payment adapters are read-only
  by design.
- Invent a fact that is not in `knowledge/` or in the data it was given. When it
  is not sure, it queues the item as `needs_human` instead of guessing.
- Argue. Complaints, refund requests, legal or medical topics, and anything that
  reads as distressed go straight to a person.

## Data handling

**What leaves your machine.** With `llm.provider: anthropic` or `claude-code`,
the prompt goes to Anthropic. That prompt contains the guest message and the
relevant property facts. With `llm.provider: mock` or `interactive`, nothing
leaves the machine at all.

**What is stored, and where.** Everything lives in `data/` inside this folder:
`agent.db` (SQLite), `logs/*.jsonl`, `exports/`. `data/` is gitignored. There is
no cloud service behind this repo and no telemetry.

**Card numbers are redacted on the way in.** Every inbound message passes through
`core/redact.py` before it is stored, logged or put into a prompt. A payment card
number is replaced with `[CARD REDACTED ****1234]`, and labelled CVC and expiry
values in the same message go with it. Detection requires a real card prefix and
a valid Luhn checksum, so booking references and door codes survive. IBANs are
masked the same way. Nothing you can do in config turns this off.

**Retention.** `privacy.retention_days` (default 365) is how long processed items
stay in the database. Deleting `data/agent.db` deletes everything the agent knows.

## GDPR, in practice

If you are in the EU or handle EU guests' data, the short version:

- **You are the controller.** This software runs on your machine, under your
  control, on your data. TH1 does not receive it.
- **Your model provider is a processor.** If you use the `anthropic` or
  `claude-code` provider, Anthropic processes guest data on your behalf. Check
  their data processing terms and record them in your processing register.
- **Purpose and minimisation.** The agent sees the message and the property facts
  it needs. Do not put staff phone numbers, card data or full guest histories in
  `knowledge/`.
- **Right to erasure.** A guest asking to be deleted means removing their rows
  from `data/agent.db` and any exported CSVs. Ask your Claude session:
  *"Delete every item in data/agent.db whose payload mentions this email address,
  and tell me how many rows you removed."*
- **Retention.** Set `privacy.retention_days` to what your own policy says, not
  to the default.

This is a practical summary, not legal advice.

## Telling guests they are talking to AI

The EU AI Act (Article 50) requires that a person is told when they are
interacting with an AI system, unless it is obvious. Whether it applies to you
depends on where you and your guests are, but it is good practice everywhere and
guests react well to it.

Add a line like this to the signature of any message the agent sends
(`knowledge/signature.md`):

> This reply was prepared with AI assistance and reviewed by our team. Reply to
> this message any time to reach a person directly.

If you run in live mode with auto-send for some intents, say so plainly:

> This reply was written by our AI assistant. If you would rather speak to a
> person, just say so and we will take over.

Keep the escape hatch in the sentence. A guest who wants a human should never
have to work out how to get one.

## Subscription or API: an honest note

Two ways to pay for the reasoning:

**Your Claude Code subscription** (`llm.provider: claude-code` or `interactive`).
Flat monthly cost, no per-message billing. This is genuinely the cheapest way to
run a small hotel's agent.

The caveat, plainly: a personal Pro or Max subscription is intended for
interactive use, and Anthropic's usage policy and rate limits apply to automated
use of it. A handful of scheduled runs a day is a normal way to work. Pointing
a busy inbox at it around the clock is not, and you will hit rate limits at the
worst moment. Read the terms and decide for yourself.

**The Anthropic API** (`llm.provider: anthropic`). Pay per token, no ambiguity
about automated use, proper rate limits, and usage you can attribute. This is
the right answer for production volume. `make report` shows what you are
spending.

Start on the subscription while you are learning what the agent does. Move to the
API when it becomes part of how the hotel runs.

## If something goes wrong

1. `mode: shadow` in `config/hotel.yaml`, or `AGENT_MODE=shadow` in `.env`. Every
   outbound action stops on the next pass.
2. Remove the schedule (`crontab -e`, `launchctl unload`, or
   `systemctl disable --now <slug>.timer`).
3. `make doctor` to see what the agent thinks its state is.
4. `data/logs/*.jsonl` has every decision, with the run id, in order.

## VIP AI's own guardrails

**Public sources only, and this repo does not fetch any.** `tools/research.py`
never calls LinkedIn, Instagram, a search engine or any other external
service — it tidies a note a staff member already found and pasted in. See
`docs/how-it-works.md` decision #1 for why a scraper is deliberately not
built here.

**A research note that infers health, family or money gets flagged, not
dropped silently.** The `research_match` LLM task sets `needs_human` true on
anything that reads as inferring a health, family or financial detail from a
public post, or that the note itself calls uncertain. A flagged or `unsure`
snippet is stored (nothing is thrown away) but excluded from every brief
until a human runs `python3 tools/research.py confirm <id>` — so "if it
isn't sure about a match, it says so" is enforced structurally, the same way
the brief's traceability is.

**A privacy-flagged profile changes the brief's tone, not its content.**
`history_note` or any preference value matching `private`, `discreet`,
`never post` or `no publicity` routes the item to `needs_human` (an extra
read before anyone sees it) and adds the line "use in conversation only if
the guest raises it, never in writing" to the front-office section.

**Every letter needs a human, full stop — there is no value threshold that
skips review.** See `docs/how-it-works.md` decision #15. A postal letter
with no address on file is refused outright (`needs_human`) rather than
built anyway.

**No handwriting-robot API is called, anywhere.** `tools/letters.py dispatch`
writes a print-ready text file and, for postal delivery, tries the `Courier`
stub — expected to fail, caught, logged. Never claim a physical mailing
happened because a file was written.

**`do_not_contact` suppresses letters, not briefs.** Staff still need to
know a do-not-contact VIP is arriving; they do not need this agent mailing
them a physical letter. `python3 tools/vip.py do-not-contact <guest_key>`
sets it; `--off` clears it.

**Erasure, specifically for this agent's tables.** In addition to `items`
(covered above), a guest's rows in `vip_profiles` and `research_snippets`
carry their name, preferences, and anything staff logged as research. Ask
your Claude session: *"Delete the vip_profiles row and every research_snippets
row for guest_key <email>, and tell me how many rows you removed."*

**Escalation.** Nothing here escalates automatically — there is no
complaint, refund or legal-risk path in this agent (that is Front Desk AI's
job). The nearest thing to an escalation is `needs_human`: a privacy flag, an
unconfirmed research match, or a letter with no mailing address all land
there instead of a plain `pending_review`.
