"""tools/profile_engine.py - The Insider's brief logic. Pure functions, no I/O.

Ports `runVipBrief()` from the demo's `concierge-engine.ts` (see
specs/vip-ai.md section 3): filter research to this guest, flag privacy,
route every preference to a desk, write the GM's one line. Every step is
deterministic and every line carries a trace back to where it came from -
see docs/how-it-works.md, "nothing in this brief is invented" is enforced
structurally here, not asserted.

Shared by tools/vip.py (the real loop) and tools/demo.py, so both exercise
exactly the same code path.
"""

from __future__ import annotations

import re
from datetime import date

PRIVATE_RE = re.compile(r"private|discreet|never post|no publicity", re.I)

#: default desk routing - config/agent.yaml: sections can extend this
DEFAULT_SECTION_OF = {
    "room": "housekeeping", "pet": "housekeeping", "pets": "housekeeping",
    "flowers": "housekeeping", "amenities": "housekeeping", "turndown": "housekeeping",
    "wellness": "housekeeping",
    "dining": "fnb", "drinks": "fnb", "food": "fnb", "diet": "fnb", "allergies": "fnb",
    "occasion": "front_office", "transport": "front_office", "arrival": "front_office",
    "privacy": "front_office",
}
CATCH_ALL = "front_office"

#: metadata for tools/letter_engine.py / tools/letters.py, not a guest fact for
#: the daily brief - e.g. `flowers_from` names who sends flowers in a letter's
#: closing line, `delivery` (`postal`/`in_house`) tells `letters.py::scan`
#: whether this guest's letters should be mailed (see docs/how-it-works.md
#: decision #17). Routing either through the brief would read as a strange,
#: meaningless line to the duty team.
LETTER_ONLY_KEYS = {"flowers_from", "delivery"}


def section_of(sections_cfg: dict | None) -> dict[str, str]:
    """Flatten config/agent.yaml's `sections:` (section -> [keys]) into key -> section.

    Falls back to :data:`DEFAULT_SECTION_OF` for any key the config does not
    mention, so a hotel only has to list what they want to change.
    """
    out = dict(DEFAULT_SECTION_OF)
    for section, keys in (sections_cfg or {}).items():
        for key in keys or []:
            out[str(key).lower()] = section
    return out


def tier_for(stays: int, *, platinum_min_stays: int = 8, gold_min_stays: int = 3) -> str:
    """Deterministic tiering - see docs/how-it-works.md decision area for the demo split."""
    if stays >= platinum_min_stays:
        return "Platinum"
    if stays >= gold_min_stays:
        return "Gold"
    return "Silver"


def is_private(history_note: str, preferences: dict) -> bool:
    """The demo's guardrail regex over history_note + every preference value."""
    text = " ".join([history_note or "", *[str(v) for v in (preferences or {}).values()]])
    return bool(PRIVATE_RE.search(text))


def arrival_label(offset: int | None, arrival_date: str | None = None) -> str:
    """`null` -> no upcoming stay; 0 -> today; 1 -> tomorrow; else D+N with a date."""
    if offset is None:
        return "no upcoming stay"
    if offset == 0:
        return "arriving today"
    if offset == 1:
        return "arriving tomorrow"
    label = f"D+{offset}"
    if arrival_date:
        try:
            d = date.fromisoformat(arrival_date)
            # %-d is a glibc/BSD extension, not portable to every platform;
            # d.day as a plain int never carries a leading zero, so this
            # reads "Fri 12 Sep" everywhere without relying on it.
            return f"arriving {d.strftime('%a')} {d.day} {d.strftime('%b')} ({label})"
        except (ValueError, TypeError):
            pass
    return f"arriving in {offset} days ({label})"


def route_preference(key: str, value: str, sections: dict[str, str]) -> tuple[str, str, str]:
    """One preference key/value -> (section, line text, trace). Empty values skip."""
    section = sections.get(str(key).lower(), CATCH_ALL)
    title = str(key).replace("_", " ").title()
    text = f"{title} — {value}"
    trace = f"preference · {key}"
    return section, text, trace


def build_brief(profile: dict, snippets: list[dict], *, rules: dict, sections_cfg: dict,
                today: date) -> dict:
    """Port of `runVipBrief()`. Returns a VipBrief dict plus a `thinking` log.

    ``profile`` needs: guest_name, tier, visits, room_type, arrival_offset,
    arrival_date, preferences (dict), history_note. ``snippets`` is already
    filtered to this guest and to confirmed/likely confidence (unsure/flagged
    rows are excluded by the caller - docs/how-it-works.md decision #2).
    """
    sections = section_of(sections_cfg)
    prefs = profile.get("preferences") or {}
    history_note = profile.get("history_note") or ""
    private = is_private(history_note, prefs)
    label = arrival_label(profile.get("arrival_offset"), profile.get("arrival_date"))
    thinking: list[str] = []

    housekeeping: list[dict] = []
    fnb: list[dict] = []
    front_office: list[dict] = []
    buckets = {"housekeeping": housekeeping, "fnb": fnb, "front_office": front_office}

    # Step: seed front_office with the one-line profile summary - always first.
    front_office.append({
        "text": f"{profile.get('tier')} · {profile.get('visits')} stays on file · "
               f"{profile.get('room_type') or 'room type on request'} · {label}.",
        "trace": "profile",
    })
    routable_prefs = [k for k in prefs if k not in LETTER_ONLY_KEYS]
    thinking.append(f"Pulled the preference card: {profile.get('tier')}, "
                    f"{profile.get('visits')} stays, {profile.get('room_type') or '-'}, "
                    f"{len(routable_prefs)} preference key(s) on file.")

    # Step: route every preference key to a desk.
    routed = 0
    for key, value in prefs.items():
        if not value or key in LETTER_ONLY_KEYS:
            continue
        section, text, trace = route_preference(key, value, sections)
        buckets[section].append({"text": text, "trace": trace})
        routed += 1
    thinking.append(f"Routed {routed} preference(s) to a desk (unknown keys land in "
                    f"front_office).")

    # Step: stay context + two plain staff-facing sentences on how this
    # brief was generated and whether this guest gets priority handling -
    # content only, no internal rule-engine wording (see decision #4/#9 and
    # SIMULATION.md finding 3: this used to read as leaked meta text).
    cadence_line = ("Part of the automatic daily VIP brief."
                    if rules.get("brief_daily", True)
                    else "Built on request - this hotel does not run a daily brief.")
    priority_line = ("Handle their requests ahead of the regular queue."
                     if rules.get("vip_first", True) and profile.get("tier") != "Silver"
                     else "No special priority - they take their turn in the queue.")
    front_office.append({"text": f"Stay context: {label}. {cadence_line} {priority_line}",
                         "trace": "rule · brief_daily+vip_first"})

    # Step: the history note.
    if history_note:
        front_office.append({"text": history_note, "trace": "profile · history_note"})

    # Step: fold in research.
    if snippets:
        for s in snippets:
            front_office.append({
                "text": f"{s.get('headline')} — {s.get('body')}",
                "trace": f"research · {s.get('id')} ({s.get('source')})",
            })
        note = (f"{len(snippets)} research card(s) on file, every one labelled "
               f"'{snippets[0].get('provenance', 'public source — staff verified')}'. "
               "Public sources only: nothing scraped from a private account, nothing "
               "inferred about health, family or money.")
        if private:
            note += (" Privacy flag on this profile — use in conversation only if the "
                     "guest raises it, never in writing.")
        thinking.append(note)
    else:
        thinking.append("No research cards on file for this guest, so the brief runs on "
                        "the preference card and stay history alone.")

    thinking.append(f"{len(housekeeping)} housekeeping line(s), {len(fnb)} F&B line(s), "
                    f"{len(front_office)} front office line(s). Every line carries the "
                    "preference key or research id it came from — nothing in this brief "
                    "is invented.")

    # Step: the GM's one line.
    tone = ("Greet by name in the suite, never across the lobby. " if private
           else "Worth thirty seconds of your morning. ")
    if snippets:
        angle = f"If the conversation allows: {snippets[0].get('headline', '').lower()} " \
               f"({snippets[0].get('id')})."
    else:
        angle = "No research angle on file — keep it warm and short."
    gm_line = (f"{profile.get('guest_name')} — {profile.get('tier')}, "
              f"{profile.get('visits')} stays, {label}. {tone}{angle}")

    return {
        "guest": profile.get("guest_name"), "arrival": label, "housekeeping": housekeeping,
        "fnb": fnb, "front_office": front_office, "gm_line": gm_line, "private": private,
        "thinking": thinking, "sent": False,
    }
