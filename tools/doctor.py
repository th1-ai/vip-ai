#!/usr/bin/env python3
"""tools/doctor.py - is VIP AI configured and reachable right now?

    make doctor
    python3 tools/doctor.py

Runs the generic core.doctor checks (python, deps, config, .env, hotel
identity, mode, llm provider, every adapter, the store, knowledge) plus
VIP-AI-specific ones: the tier thresholds, whether Handwritten Letter AI is
on, and the one prompt this repo ships. Exits 0 when everything passed, 1
when a FAIL line needs fixing. Never a traceback: a config error is shown as
a FAIL row like any other.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from core.config import ConfigError, Settings, load_settings  # noqa: E402
from core.doctor import Check, FAIL, PASS, WARN, print_table, run_checks  # noqa: E402


def check_tiers(settings: Settings) -> Check:
    platinum = int(settings.agent_get("tiers.platinum_min_stays", 0))
    gold = int(settings.agent_get("tiers.gold_min_stays", 0))
    if platinum <= gold:
        return Check("tier thresholds", FAIL,
                     f"platinum_min_stays ({platinum}) must be greater than "
                     f"gold_min_stays ({gold})",
                     "Fix config/agent.yaml's tiers: block.")
    return Check("tier thresholds", PASS, f"Silver < {gold} <= Gold < {platinum} <= Platinum")


def check_subagents(settings: Settings) -> Check:
    letters_on = bool(settings.agent_get("subagents.handwritten_letter.enabled", False))
    if not letters_on:
        return Check("sub-agents", WARN, "Handwritten Letter AI is off (the default) - "
                     "see docs/sub-agents.md")
    return Check("sub-agents", PASS, "handwritten_letter=on")


def check_prompts() -> Check:
    missing = [p for p in ("prompts/research_match.md", "prompts/schemas/research_match.json")
              if not (REPO_ROOT / p).is_file()]
    if missing:
        return Check("prompts", FAIL, f"missing {', '.join(missing)}",
                     "These ship with the repo - restore them from git.")
    return Check("prompts", PASS, "research_match.md + schema present")


def main() -> int:
    try:
        settings = load_settings()
    except ConfigError as exc:
        checks = run_checks(None) + [Check("config", FAIL, str(exc),
                                           "Fix config/hotel.yaml or config/agent.yaml.")]
        return print_table(checks, title="VIP AI - doctor")

    checks = run_checks(settings, extra=[check_tiers, check_subagents])
    checks.append(check_prompts())
    return print_table(checks, title="VIP AI - doctor")


if __name__ == "__main__":
    raise SystemExit(main())
