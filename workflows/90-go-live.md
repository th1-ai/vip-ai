# Workflow: shadow to live

Objective: decide, together with the hotel, whether VIP AI is ready to send
approved briefs to the duty team and dispatch approved letters on its own
instead of only queuing them - and make the change safely if so.

This is the hotel's decision, never the agent's. Do not suggest it until the
checklist below is genuinely true, and when you do raise it, say plainly
what changes.

## Checklist

- [ ] `make doctor` is clean (no `FAIL` lines). `warn` on `mode` is expected
      until you flip it.
- [ ] `config/hotel.yaml` has the real property name, address and contact
      details.
- [ ] `config/agent.yaml`'s `tiers:` matches how this property actually
      talks about its regulars.
- [ ] At least a week of real `make run` passes have gone through the review
      queue, not just the demo fixtures - you've read several real briefs
      end to end and they read right.
- [ ] `systems.messaging.adapter` is connected and `make doctor` shows it
      healthy - this is where an approved brief actually goes.
- [ ] If Handwritten Letter AI is on: you've watched at least one real
      letter draft, approved or edited it, and are comfortable with the
      wording before trusting it unwatched.
- [ ] The hotel understands `courier` is a stub - a postal letter's "send"
      still ends with a person handling the printed file, unless you've
      wired in a real courier adapter (`docs/integrations.md`).

## Making the change

1. Edit `config/hotel.yaml`:
   ```yaml
   mode: live
   ```
2. `review.require_approval_for` still lists `send_message` and `publish` by
   default - it should. Going live means **approved** briefs get sent and
   **approved** letters get dispatched, not that either track starts acting
   unapproved. There is no config that changes that.
3. Clear the shadow-era backlog:
   ```bash
   python3 tools/review.py stale
   ```
   Everything still `pending_review`, `needs_human`, `approved` or `edited`
   from before this moment moves to `stale`. None of it was ever sent -
   shadow blocked every send, approved or not - but a brief built days ago
   may be stale by now (the guest's arrival details could have changed). If
   one still genuinely matters, ask your Claude session to move it back with
   `core.store.Store.transition(item_id, "pending_review", "human")` -
   there is no dedicated CLI command for this on purpose.
4. Run `make doctor` again to confirm.
5. Run one real pass and manually watch a send go through:
   ```bash
   python3 tools/run.py --once
   python3 tools/review.py list
   python3 tools/review.py approve <id>
   python3 tools/review.py send
   ```
6. Tell the hotel exactly what just changed: an approved brief now actually
   reaches the duty team, and an approved letter now actually gets a
   print-ready file, the next time someone (or a scheduled job) runs the
   relevant command. Nothing sends or writes before that approval, live mode
   or not.

## Going back to shadow

```yaml
mode: shadow
```
in `config/hotel.yaml`, or `AGENT_MODE=shadow` in `.env` for one run. Either
stops every outbound action on the next pass, with no other change required.
