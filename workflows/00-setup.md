# Workflow: first-run setup

Objective: get VIP AI from a fresh clone to a working demo, then to real
config, in one sitting.

## Steps

1. **Install and check.**
   ```bash
   make setup
   make doctor
   ```
   `make setup` creates the virtualenv, installs `requirements.txt`, and
   copies `.env.example` -> `.env` and every `config/*.example.yaml` ->
   `config/*.yaml` (only if those files do not exist yet). `make doctor`
   shows a `FAIL` on "hotel identity" right after setup - expected, it means
   the property is still the shipped placeholder. Everything else should be
   `ok` or `warn`.

2. **Run the demo.** No credentials needed.
   ```bash
   make demo
   ```
   Expect to see the PMS sync, four sample research notes logged (one flagged
   `unsure`, one flagged for inferring a personal detail the guardrail
   excludes), four briefs built and printed with their GM line, a note that
   Handwritten Letter AI is off by default, and finally
   `DEMO OK — 4 items processed, 4 drafted, 0 sent (shadow)`. If you do not
   see that, stop and read `workflows/99-troubleshooting.md`.

3. **Fill in the property.** Edit `config/hotel.yaml` (name, address,
   contact, languages, currency). Then:
   ```bash
   cp knowledge/property.example.md    knowledge/property.md
   cp knowledge/faq.example.md         knowledge/faq.md
   cp knowledge/vip-playbook.example.md knowledge/vip-playbook.md
   ```
   The brief-building code does not read any of these at runtime (it is
   deliberately template-free - see `docs/how-it-works.md`); they are for
   the humans reading the brief, and for `tools/research.py`'s prompt, which
   reads only `{{hotel_name}}`.

4. **Set your tiers and desk routing.** Edit `config/agent.yaml`:
   - `tiers.platinum_min_stays` / `tiers.gold_min_stays` - stays on file, low
     to high, matching how your own team already talks about regulars.
   - `sections:` - only if a preference key your property tracks does not
     fit the defaults (`docs/how-it-works.md` decision #8).
   Run `make doctor` again - it checks the thresholds are sane.

5. **Pick how the agent thinks.** Only one LLM call exists in this whole
   repo (`tools/research.py add` - see `docs/how-it-works.md`), and it never
   runs on a schedule, so this matters less here than in most of the family.
   `config/hotel.yaml`'s `llm.provider` still starts as `interactive` - it
   asks you, in this Claude Code session, instead of calling a model.
   `docs/safety.md` covers the other three providers.

6. **Connect a real PMS, and where briefs go (optional for now).**
   `systems.pms.adapter` starts as `mock`. `docs/integrations.md` covers
   `csv` (works with any PMS with zero API access) and `cloudbeds` (built).
   `systems.messaging.adapter` is where an approved brief goes - `webhook`
   is the fastest way to relay into whatever your "morning huddle" tool
   already is. Run `make doctor` after changing either.

7. **Re-check.**
   ```bash
   make doctor
   ```
   Once the property name is real and your tiers match reality, move on to
   `workflows/10-vip-brief.md`.
