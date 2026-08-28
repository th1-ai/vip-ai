"""Tests for tools/letter_engine.py - pure functions, never a model."""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(REPO_ROOT / "tools") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "tools"))

from letter_engine import (build_letter, flowers_clause, opening_line,  # noqa: E402
                           preference_details, salutation_name, visit_times_phrase,
                           visit_word)


def test_salutation_name_couple_uses_first_names_only():
    assert salutation_name("Eleanor & George Ashby") == "Eleanor and George"


def test_salutation_name_single_guest_unchanged():
    assert salutation_name("Marco Bellini") == "Marco Bellini"


def test_visit_word_spells_small_numbers():
    assert visit_word(0) == "no"
    assert visit_word(9) == "nine"
    assert visit_word(11) == "11"  # above ten, keep the digit


def test_visit_times_phrase_never_says_one_times():
    """SIMULATION.md finding 4: "You have stayed with us one times now" is
    broken grammar - a first-time guest (or a 9-stay Platinum guest wrongly
    reset to visits=1, see finding 1) must read "one time"."""
    assert visit_times_phrase(1) == "one time"


def test_visit_times_phrase_pluralises_everything_else():
    assert visit_times_phrase(9) == "nine times"
    assert visit_times_phrase(2) == "two times"
    assert visit_times_phrase(0) == "no times"
    assert visit_times_phrase(11) == "11 times"


def test_opening_line_anniversary_uses_years_wording():
    opening, closing = opening_line("40th anniversary")
    assert opening.startswith("Forty years.")
    assert "forty years" in closing


def test_opening_line_birthday_never_says_years():
    # the source defect: an occasion with no anniversary number still read
    # "This years." - see docs/how-it-works.md decision #10.
    opening, closing = opening_line("Birthday")
    assert "years" not in opening.lower()
    assert opening.startswith("Happy birthday.")


def test_opening_line_stay_milestone_uses_an_ordinal():
    opening, closing = opening_line("100th stay")
    assert "hundredth stay" in opening.lower()
    assert "years" not in opening.lower()


def test_opening_line_no_number_at_all_is_generic_not_broken():
    opening, closing = opening_line("A lovely surprise")
    assert opening.startswith("A milestone worth marking.")
    assert "This years" not in opening  # the exact defect from the source


def test_preference_details_lowercases_only_the_leading_character():
    details = preference_details({"room": "Corner suite", "drinks": "Tawny port — George"})
    assert details[0] == "corner suite"
    assert details[1] == "tawny port — George"  # "George" keeps its capital


def test_flowers_clause_requires_a_named_sender():
    with_sender = flowers_clause({"occasion": "40th, flowers arranged", "flowers_from": "Their daughter"})
    assert "Their daughter" in with_sender
    without_sender = flowers_clause({"occasion": "40th, flowers arranged"})
    assert without_sender == ""  # no hard-coded "your daughter's" - decision #11


def test_build_letter_uses_the_configured_hotel_name_not_a_fictional_one():
    letter = build_letter(hotel_name="Hotel Aurora", guest_name="Eleanor & George Ashby",
                          occasion="40th anniversary", visits=9,
                          preferences={"room": "Corner suite", "dining": "Late seating",
                                      "drinks": "Tawny port — George"})
    assert "The team at Hotel Aurora" in letter["body"]
    assert "Grand Meridian" not in letter["body"]
    assert letter["body"].startswith("Dear Eleanor and George,")
    assert "stayed with us nine times now" in letter["body"]
    assert "one times" not in letter["body"]


def test_build_letter_first_time_guest_uses_singular_time():
    letter = build_letter(hotel_name="Hotel Aurora", guest_name="Marco Bellini",
                          occasion="Birthday", visits=1, preferences={})
    assert "stayed with us one time now" in letter["body"]
    assert "one times" not in letter["body"]
