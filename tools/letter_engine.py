"""tools/letter_engine.py - The Scribe's letter text. Pure functions, no I/O.

Ports `buildLetterBody()` from the demo's `concierge-engine.ts` (see
specs/handwritten-letter-ai.md section 3): built from the preference card and
the occasion, never from a model. Fixes the three defects the spec's open
questions flagged - see docs/how-it-works.md decisions #10-12:

- the opening line branches by occasion type instead of always forcing
  "years" wording (the "This years." defect on a birthday or a plain
  milestone visit);
- the flowers clause is parameterised on `preferences.flowers_from` instead
  of hard-coding "your daughter's";
- the closing signs off with the hotel's own configured name, never a
  fictional one.
"""

from __future__ import annotations

import re

YEAR_WORDS = {
    5: "Five", 10: "Ten", 15: "Fifteen", 20: "Twenty", 25: "Twenty-five",
    30: "Thirty", 35: "Thirty-five", 40: "Forty", 45: "Forty-five",
    50: "Fifty", 55: "Fifty-five", 60: "Sixty", 65: "Sixty-five", 70: "Seventy",
}
VISIT_WORDS = ["no", "one", "two", "three", "four", "five", "six", "seven",
              "eight", "nine", "ten"]
ORDINAL_WORDS = {
    5: "Fifth", 10: "Tenth", 20: "Twentieth", 25: "Twenty-fifth", 50: "Fiftieth",
    100: "Hundredth",
}
NUMBER_RE = re.compile(r"(\d+)")
FLOWER_RE = re.compile(r"flower", re.I)
ANNIVERSARY_RE = re.compile(r"anniversary", re.I)
BIRTHDAY_RE = re.compile(r"birthday", re.I)
STAY_RE = re.compile(r"\bstay\b|\bvisit\b", re.I)


def salutation_name(guest_name: str) -> str:
    """'Eleanor & George Ashby' -> 'Eleanor and George'. A single name is unchanged."""
    if " & " not in (guest_name or ""):
        return guest_name or ""
    first, second = guest_name.split(" & ", 1)
    second_first = second.strip().split(" ")[0]
    return f"{first.strip()} and {second_first}"


def visit_word(visits: int) -> str:
    if 0 <= visits < len(VISIT_WORDS):
        return VISIT_WORDS[visits]
    return str(visits)


def visit_times_phrase(visits: int) -> str:
    """'{word} time(s)' with correct singular/plural - never "one times".

    `visits == 1` -> "one time"; everything else, including 0, -> "N times"
    ("no times" reads fine, unlike "no time" here). See
    docs/how-it-works.md decision #19 and SIMULATION.md finding 4.
    """
    return f"{visit_word(visits)} {'time' if visits == 1 else 'times'}"


def _year_word(n: int) -> str:
    if n in YEAR_WORDS:
        return YEAR_WORDS[n]
    return str(n)


def _ordinal_word(n: int) -> str:
    if n in ORDINAL_WORDS:
        return ORDINAL_WORDS[n]
    suffix = "th"
    if n % 100 not in (11, 12, 13):
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def opening_line(occasion: str) -> tuple[str, str]:
    """(opening sentence, "years"-style word for the closing) for this occasion.

    Branches by occasion type instead of always forcing anniversary wording -
    see docs/how-it-works.md decision #10. Returns the closing word too,
    since the template's closing paragraph names the same milestone again.
    """
    occasion = occasion or ""
    match = NUMBER_RE.search(occasion)
    number = int(match.group(1)) if match else None

    if ANNIVERSARY_RE.search(occasion) and number:
        years = _year_word(number)
        return (f"{years} years. That deserves rather more than a printed card, "
               f"so this one is written by hand.", f"mark {years.lower()} years")
    if BIRTHDAY_RE.search(occasion):
        return ("Happy birthday. That deserves rather more than a printed card, "
               "so this one is written by hand.", "mark another year")
    if STAY_RE.search(occasion) and number:
        ordinal = _ordinal_word(number)
        return (f"Your {ordinal.lower()} stay with us. That deserves rather more than "
               f"a printed card, so this one is written by hand.",
               f"mark your {ordinal.lower()} stay")
    return ("A milestone worth marking. That deserves rather more than a printed card, "
           "so this one is written by hand.", "mark this occasion")


def preference_details(preferences: dict) -> list[str]:
    """Room, dining, drinks - in that fixed order, first character lower-cased only.

    Comment carried from the source: values carry first names ("tawny port -
    George") that must keep their capitals, so only the leading character
    is touched.
    """
    details = []
    for key in ("room", "dining", "drinks"):
        value = (preferences or {}).get(key)
        if value:
            details.append(value[:1].lower() + value[1:])
    return details


def flowers_clause(preferences: dict) -> str:
    """Fires only when `flowers_from` is set - see docs/how-it-works.md decision #11."""
    occasion_pref = (preferences or {}).get("occasion") or ""
    sender = (preferences or {}).get("flowers_from")
    if FLOWER_RE.search(occasion_pref) and sender:
        return (f" {sender}'s flowers will be waiting upstairs when you come back "
               "from dinner.")
    return ""


def build_letter(*, hotel_name: str, guest_name: str, occasion: str, visits: int,
                 preferences: dict) -> dict:
    """Assemble the ~100-word letter. Returns {"subject": ..., "body": ...}."""
    names = salutation_name(guest_name)
    opening, closing_word = opening_line(occasion)
    details = preference_details(preferences)
    detail_text = "; ".join(details) if details else "your usual arrangements"
    flowers = flowers_clause(preferences)

    body = (
        f"Dear {names},\n\n"
        f"{opening}\n\n"
        f"You have stayed with us {visit_times_phrase(visits)} now — long enough that we "
        f"know the small things: {detail_text}. All of it is ready for you.{flowers}\n\n"
        f"Thank you for choosing to {closing_word} in our house. We will do our best to "
        f"make it feel like yours.\n\n"
        f"With our warmest wishes,\n"
        f"The team at {hotel_name}"
    )
    subject = f"Letter — {occasion}" if occasion else "Letter"
    return {"subject": subject, "body": body}
