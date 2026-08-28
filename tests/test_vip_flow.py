"""Integration tests for the daily loop: tools/vip.py + tools/letters.py +
tools/review.py against the bundled fixtures, provider=mock. No network.
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
for p in (REPO_ROOT, REPO_ROOT / "tools", Path(__file__).resolve().parent):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from _config_isolation import write_example_config_dir  # noqa: E402

import pytest  # noqa: E402

from core.adapters import get_pms  # noqa: E402
from core.config import load_settings  # noqa: E402
from core.review import WriteBlocked, approve  # noqa: E402
from core.store import Store  # noqa: E402
from letters import enabled as letters_enabled  # noqa: E402
from letters import scan as letters_scan  # noqa: E402
from review import dispatch_brief  # noqa: E402
from vip import SCHEMA, build_and_queue_briefs, sync_profiles  # noqa: E402

DEMO_TODAY = date(2026, 9, 10)  # matches fixtures/hotel/reservations.json
_EXAMPLE_CONFIG_DIR = write_example_config_dir()


@pytest.fixture(autouse=True)
def _use_example_config(monkeypatch):
    """Never read this repo's own config/hotel.yaml / agent.yaml - see
    factory/workflows/build-repo.md "Tests never read the live config"."""
    monkeypatch.setenv("AGENT_CONFIG_DIR", str(_EXAMPLE_CONFIG_DIR))


def _settings():
    return load_settings(provider="mock", mode="shadow")


def _store(tmp_path, name="vip.db"):
    store = Store(_settings(), path=tmp_path / name)
    store.migrate(SCHEMA)
    return store


def test_sync_and_build_briefs_matches_demo_counts(tmp_path):
    settings = _settings()
    store = _store(tmp_path)
    pms = get_pms(settings)
    sync_stats = sync_profiles(settings, store, pms, today=DEMO_TODAY, lookahead_days=2)
    assert sync_stats["synced"] == 4  # Ashby, Kapoor, Bellini, Whitfield - Haddad is outside the window

    brief_stats = build_and_queue_briefs(settings, store, today=DEMO_TODAY)
    assert brief_stats["drafted"] == 4
    assert brief_stats["needs_human"] == 1  # Kapoor, privacy-flagged
    store.close()


def test_rerun_same_day_is_idempotent(tmp_path):
    settings = _settings()
    store = _store(tmp_path)
    pms = get_pms(settings)
    sync_profiles(settings, store, pms, today=DEMO_TODAY, lookahead_days=2)
    first = build_and_queue_briefs(settings, store, today=DEMO_TODAY)
    assert first["drafted"] == 4

    sync_profiles(settings, store, pms, today=DEMO_TODAY, lookahead_days=2)
    second = build_and_queue_briefs(settings, store, today=DEMO_TODAY)
    assert second["drafted"] == 0
    assert second["skipped"] == 4
    assert len(store.list_items(kind="vip_brief", limit=100)) == 4  # never duplicated
    store.close()


def test_rebuild_refreshes_unapproved_briefs_but_never_an_approved_one(tmp_path):
    """SIMULATION.md finding 5: `--rebuild` is how research logged after the
    day's brief was drafted reaches it - but only while no human has acted
    on that brief yet. An approved one is never rewritten out from under a
    human decision."""
    settings = _settings()
    store = _store(tmp_path, name="rebuild.db")
    pms = get_pms(settings)
    sync_profiles(settings, store, pms, today=DEMO_TODAY, lookahead_days=2)
    build_and_queue_briefs(settings, store, today=DEMO_TODAY)

    items = store.list_items(kind="vip_brief", limit=100)
    pending = next(i for i in items if i.review_status == "pending_review")
    approve(store, pending.id)

    still_unapproved = [i for i in items if i.id != pending.id
                        and i.review_status in ("pending_review", "needs_human")]
    assert still_unapproved, "expected at least one other brief left un-approved"

    rebuilt = build_and_queue_briefs(settings, store, today=DEMO_TODAY, rebuild=True)
    assert rebuilt["rebuilt"] == len(still_unapproved)

    approved_after = store.get_item(pending.id)
    assert approved_after.review_status == "approved"  # rebuild never touched it
    store.close()


def test_shadow_blocks_brief_send_and_keeps_approval(tmp_path):
    settings = _settings()
    assert settings.mode == "shadow"
    store = _store(tmp_path)
    pms = get_pms(settings)
    sync_profiles(settings, store, pms, today=DEMO_TODAY, lookahead_days=2)
    build_and_queue_briefs(settings, store, today=DEMO_TODAY)

    item = next(i for i in store.list_items(kind="vip_brief", limit=100)
               if i.review_status == "pending_review")
    approved = approve(store, item.id)
    claimed = store.transition(approved.id, "sending", actor="agent")
    with pytest.raises(WriteBlocked):
        dispatch_brief(settings, claimed)
    # the review.py cmd_send pattern: on WriteBlocked, move back to approved,
    # never failed - see tools/review.py.
    recovered = store.transition(claimed.id, "approved", actor="agent")
    assert recovered.review_status == "approved"
    counts = store.counts()
    assert counts.get("sent", 0) == 0
    assert counts.get("auto_sent", 0) == 0
    store.close()


def test_dry_run_writes_nothing_and_is_safe_twice(tmp_path):
    import run as run_module

    settings = load_settings(provider="mock", mode="shadow", dry_run=True)
    store = _store(tmp_path, name="dryrun.db")
    for _ in range(2):
        code, stats = run_module.one_pass(settings, store, only="all", today=DEMO_TODAY,
                                          dry_run=True)
        assert code == 0
        assert stats == {}
    assert store.list_items(limit=100) == []
    store.close()


def test_letters_disabled_by_default_scan_is_a_noop(tmp_path):
    settings = _settings()
    assert letters_enabled(settings) is False
    store = _store(tmp_path, name="letters_off.db")
    pms = get_pms(settings)
    sync_profiles(settings, store, pms, today=DEMO_TODAY, lookahead_days=2)

    stats = letters_scan(settings, store, today=DEMO_TODAY, lookahead_days=14)
    assert stats["disabled"] is True
    assert stats["drafted"] == 0
    assert store.list_items(kind="letter", limit=100) == []
    store.close()


def test_letters_scan_when_enabled_needs_an_address_for_postal(tmp_path):
    settings = _settings()
    settings.agent.setdefault("subagents", {})["handwritten_letter"] = {
        "enabled": True, "lookahead_days": 14}
    assert letters_enabled(settings) is True
    store = _store(tmp_path, name="letters_on.db")
    pms = get_pms(settings)
    sync_profiles(settings, store, pms, today=DEMO_TODAY, lookahead_days=2)
    # Eleanor Ashby's fixture carries a key date 8 days out, no mailing_address
    # seeded - see fixtures/hotel/reservations.json.
    from vip import get_profile
    profile = get_profile(store, "eleanor.ashby@example.com")
    assert profile["key_dates"], "expected a seeded key date on the Ashby fixture"

    stats = letters_scan(settings, store, today=DEMO_TODAY, lookahead_days=14)
    assert stats["drafted"] == 1
    items = store.list_items(kind="letter", limit=100)
    assert len(items) == 1
    assert items[0].review_status == "pending_review"  # in_house delivery, no address needed
    # The PMS fixture carries one named guest per reservation (Guest is a
    # single-person dataclass - see core/adapters/base.py); the couple-name
    # salutation split ("Eleanor & George Ashby" -> "Eleanor and George") is
    # unit-tested directly in tests/test_letter_engine.py.
    assert items[0].draft["body"].startswith("Dear Eleanor Ashby,")
    assert "Forty years." in items[0].draft["body"]
    store.close()


def test_postal_letter_with_no_address_on_file_goes_needs_human(tmp_path):
    """SIMULATION.md finding 2: the "no mailing_address -> needs_human"
    guardrail must actually be reachable, not dead code. Staff mark a guest
    for postal delivery (`capture --key delivery --value postal`) before an
    address is on file - `tools/vip.py capture --address ...` is the only
    thing that can clear it."""
    settings = _settings()
    settings.agent.setdefault("subagents", {})["handwritten_letter"] = {
        "enabled": True, "lookahead_days": 14}
    store = _store(tmp_path, name="postal_no_address.db")
    pms = get_pms(settings)
    sync_profiles(settings, store, pms, today=DEMO_TODAY, lookahead_days=2)

    from vip import capture
    capture(settings, store, pms, "eleanor.ashby@example.com",
           key="delivery", value="postal")

    stats = letters_scan(settings, store, today=DEMO_TODAY, lookahead_days=14)
    assert stats["drafted"] == 1
    assert stats["needs_human"] == 1
    items = store.list_items(kind="letter", limit=100)
    assert items[0].review_status == "needs_human"
    assert items[0].payload["delivery"] == {"channel": "postal", "address": ""}
    store.close()


def test_capture_address_clears_the_postal_guardrail(tmp_path):
    """`tools/vip.py capture <guest> --address ...` is the documented fix for
    the case above - a guest already flagged for postal delivery who now has
    an address gets a clean `pending_review` letter with that address."""
    settings = _settings()
    settings.agent.setdefault("subagents", {})["handwritten_letter"] = {
        "enabled": True, "lookahead_days": 14}
    store = _store(tmp_path, name="postal_with_address.db")
    pms = get_pms(settings)
    sync_profiles(settings, store, pms, today=DEMO_TODAY, lookahead_days=2)

    from vip import capture, set_mailing_address
    capture(settings, store, pms, "eleanor.ashby@example.com",
           key="delivery", value="postal")
    result = set_mailing_address(store, "eleanor.ashby@example.com",
                                 address="12 Via Roma, 22100 Como, Italy")
    assert result["mailing_address"] == "12 Via Roma, 22100 Como, Italy"

    stats = letters_scan(settings, store, today=DEMO_TODAY, lookahead_days=14)
    assert stats["drafted"] == 1
    assert stats["needs_human"] == 0
    items = store.list_items(kind="letter", limit=100)
    assert items[0].review_status == "pending_review"
    assert items[0].payload["delivery"] == {
        "channel": "postal", "address": "12 Via Roma, 22100 Como, Italy"}
    store.close()


def test_mailing_address_on_its_own_still_implies_postal(tmp_path):
    """Backward compatible: an address alone is still enough - staff do not
    have to also set `--key delivery --value postal` if they already know
    the address."""
    settings = _settings()
    settings.agent.setdefault("subagents", {})["handwritten_letter"] = {
        "enabled": True, "lookahead_days": 14}
    store = _store(tmp_path, name="address_only.db")
    pms = get_pms(settings)
    sync_profiles(settings, store, pms, today=DEMO_TODAY, lookahead_days=2)

    from vip import set_mailing_address
    set_mailing_address(store, "eleanor.ashby@example.com",
                        address="12 Via Roma, 22100 Como, Italy")

    stats = letters_scan(settings, store, today=DEMO_TODAY, lookahead_days=14)
    items = store.list_items(kind="letter", limit=100)
    assert items[0].payload["delivery"]["channel"] == "postal"
    assert items[0].review_status == "pending_review"
    store.close()


def test_do_not_contact_suppresses_letters(tmp_path):
    settings = _settings()
    settings.agent.setdefault("subagents", {})["handwritten_letter"] = {
        "enabled": True, "lookahead_days": 14}
    store = _store(tmp_path, name="dnc.db")
    pms = get_pms(settings)
    sync_profiles(settings, store, pms, today=DEMO_TODAY, lookahead_days=2)

    from vip import set_do_not_contact
    set_do_not_contact(store, "eleanor.ashby@example.com", on=True)
    stats = letters_scan(settings, store, today=DEMO_TODAY, lookahead_days=14)
    assert stats["drafted"] == 0
    assert store.list_items(kind="letter", limit=100) == []
    store.close()
