"""Tests for tools/research.py - the one LLM call in this repo.

provider=mock exercises the confidence/guardrail flagging against the
bundled fixtures; the last test exercises the real `interactive` provider
path end to end (core.llm.complete parks a prompt, we answer it, it
resumes) - see factory/workflows/build-repo.md "Test the interactive path
for every LLM call".
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
for p in (REPO_ROOT, REPO_ROOT / "tools", Path(__file__).resolve().parent):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from _config_isolation import write_example_config_dir  # noqa: E402

import pytest  # noqa: E402

from core.config import load_settings, sub_data_dir  # noqa: E402
from core.llm import LLMPendingInteractive  # noqa: E402
from core.store import Store  # noqa: E402
from research import add_snippet, confirm, list_snippets  # noqa: E402
from vip import (SCHEMA, build_and_queue_briefs, confirmed_snippets,  # noqa: E402
                 get_profile, get_todays_brief, sync_profiles)

from datetime import date  # noqa: E402

from core.adapters import get_pms  # noqa: E402

DEMO_TODAY = date(2026, 9, 10)
_EXAMPLE_CONFIG_DIR = write_example_config_dir()


@pytest.fixture(autouse=True)
def _use_example_config(monkeypatch):
    monkeypatch.setenv("AGENT_CONFIG_DIR", str(_EXAMPLE_CONFIG_DIR))


def _settings():
    return load_settings(provider="mock", mode="shadow")


def _seeded_store(tmp_path, name="research.db"):
    settings = _settings()
    store = Store(settings, path=tmp_path / name)
    store.migrate(SCHEMA)
    pms = get_pms(settings)
    sync_profiles(settings, store, pms, today=DEMO_TODAY, lookahead_days=2)
    return settings, store


def test_confirmed_match_from_the_mock_fixture(tmp_path):
    settings, store = _seeded_store(tmp_path)
    result = add_snippet(settings, store, guest_key="eleanor.ashby@example.com",
                         source="Financial Times", text="a staff note",
                         fixture_id="research-note-01", provider="mock")
    assert result["confidence"] == "confirmed"
    assert result["needs_human"] is False
    store.close()


def test_unsure_match_is_stored_but_flagged(tmp_path):
    settings, store = _seeded_store(tmp_path)
    result = add_snippet(settings, store, guest_key="priya.kapoor@example.com",
                         source="conference website", text="a staff note",
                         fixture_id="research-note-02", provider="mock")
    assert result["confidence"] == "unsure"
    assert result["needs_human"] is True
    profile = get_profile(store, "priya.kapoor@example.com")
    assert confirmed_snippets(store, profile["id"]) == []  # excluded until confirmed
    store.close()


def test_guardrail_flagged_note_is_excluded_even_at_likely_confidence(tmp_path):
    settings, store = _seeded_store(tmp_path)
    result = add_snippet(settings, store, guest_key="marco.bellini@example.com",
                         source="Instagram", text="a staff note",
                         fixture_id="research-note-03", provider="mock")
    assert result["confidence"] == "likely"
    assert result["needs_human"] is True  # inferred health/family detail - see docs/safety.md
    profile = get_profile(store, "marco.bellini@example.com")
    assert confirmed_snippets(store, profile["id"]) == []
    store.close()


def test_confirm_overrides_needs_human(tmp_path):
    settings, store = _seeded_store(tmp_path)
    result = add_snippet(settings, store, guest_key="priya.kapoor@example.com",
                         source="conference website", text="a staff note",
                         fixture_id="research-note-02", provider="mock")
    profile = get_profile(store, "priya.kapoor@example.com")
    assert confirmed_snippets(store, profile["id"]) == []
    confirm(store, result["id"])
    confirmed = confirmed_snippets(store, profile["id"])
    assert len(confirmed) == 1
    assert confirmed[0]["confidence"] == "confirmed"
    store.close()


def test_list_snippets_filters_by_guest(tmp_path):
    settings, store = _seeded_store(tmp_path)
    add_snippet(settings, store, guest_key="eleanor.ashby@example.com", source="FT",
               text="note", fixture_id="research-note-01", provider="mock")
    add_snippet(settings, store, guest_key="marco.bellini@example.com", source="Instagram",
               text="note", fixture_id="research-note-03", provider="mock")
    assert len(list_snippets(store)) == 2
    assert len(list_snippets(store, guest_key="eleanor.ashby@example.com")) == 1


def test_add_snippet_warns_when_todays_brief_already_exists(tmp_path):
    """SIMULATION.md finding 5: research logged after the brief was drafted
    must not disappear silently. `add_snippet` must say so, and `--rebuild`
    must actually pull the confirmed snippet into the brief."""
    settings, store = _seeded_store(tmp_path, name="stale.db")
    first_pass = build_and_queue_briefs(settings, store, today=DEMO_TODAY)
    assert first_pass["drafted"] > 0
    profile = get_profile(store, "eleanor.ashby@example.com")
    before = get_todays_brief(store, profile["id"], DEMO_TODAY)
    assert not any("Wine columnist" in line["text"] for line in before.draft["front_office"])

    result = add_snippet(settings, store, guest_key="eleanor.ashby@example.com",
                         source="Financial Times", text="a staff note",
                         fixture_id="research-note-01", provider="mock", today=DEMO_TODAY)
    assert result["confidence"] == "confirmed" and result["needs_human"] is False
    assert result["stale_brief_warning"] is not None
    assert "--rebuild" in result["stale_brief_warning"]

    # Without --rebuild the second pass still leaves the brief untouched.
    untouched_pass = build_and_queue_briefs(settings, store, today=DEMO_TODAY)
    assert untouched_pass["drafted"] == 0
    still_before = get_todays_brief(store, profile["id"], DEMO_TODAY)
    assert not any("Wine columnist" in line["text"]
                  for line in still_before.draft["front_office"])

    rebuilt_pass = build_and_queue_briefs(settings, store, today=DEMO_TODAY, rebuild=True)
    assert rebuilt_pass["rebuilt"] >= 1
    after = get_todays_brief(store, profile["id"], DEMO_TODAY)
    assert any("Wine columnist" in line["text"] for line in after.draft["front_office"])
    store.close()


def test_add_snippet_no_warning_when_no_brief_exists_yet(tmp_path):
    settings, store = _seeded_store(tmp_path, name="no-brief.db")
    result = add_snippet(settings, store, guest_key="eleanor.ashby@example.com",
                         source="Financial Times", text="a staff note",
                         fixture_id="research-note-01", provider="mock")
    assert result["stale_brief_warning"] is None
    store.close()


def test_interactive_provider_pends_then_resumes(tmp_path):
    """The real `interactive` path (core.llm._interactive), exercised through
    our one call site. Cleans up after itself in data/pending/."""
    settings, store = _seeded_store(tmp_path, name="interactive.db")
    fixture_id = "test-interactive-research-01"
    pending = sub_data_dir("pending")
    prompt_path = pending / f"research_match-{fixture_id}.prompt.md"
    schema_path = pending / f"research_match-{fixture_id}.schema.json"
    answer_path = pending / f"research_match-{fixture_id}.answer.json"
    for p in (prompt_path, schema_path, answer_path,
             answer_path.with_suffix(".json.used")):
        p.unlink(missing_ok=True)

    try:
        with pytest.raises(LLMPendingInteractive):
            add_snippet(settings, store, guest_key="sam.whitfield@example.com",
                       source="LinkedIn", text="a staff note", fixture_id=fixture_id,
                       provider="interactive")
        assert prompt_path.exists()
        assert schema_path.exists()

        expected = json.loads((REPO_ROOT / "fixtures" / "expected" / "research_match" /
                              "research-note-04.json").read_text(encoding="utf-8"))
        answer_path.write_text(json.dumps(expected), encoding="utf-8")

        result = add_snippet(settings, store, guest_key="sam.whitfield@example.com",
                             source="LinkedIn", text="a staff note", fixture_id=fixture_id,
                             provider="interactive")
        assert result["confidence"] == "likely"
        assert result["needs_human"] is False
        assert not prompt_path.exists()  # consumed on resume
    finally:
        for p in (prompt_path, schema_path, answer_path,
                 answer_path.with_suffix(".json.used")):
            p.unlink(missing_ok=True)
        store.close()
