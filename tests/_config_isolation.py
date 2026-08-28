"""Shared test helper: an isolated copy of config/*.example.yaml.

test_vip_flow.py and test_research.py need the repo's real fixtures/,
prompts/ and knowledge/*.example.md - so they cannot redirect
AGENT_REPO_ROOT to an empty tmp dir the way a fully isolated unit test
could. But they must never read this repo's own config/hotel.yaml or
config/agent.yaml: a hotel's own edits to those files (mode, tiers,
schedule...) must never be able to turn `make test` red - see
factory/workflows/build-repo.md "Tests never read the live config".

``write_example_config_dir()`` only ever *creates* the tmp copy - it never
touches ``os.environ`` itself. Each test file points ``AGENT_CONFIG_DIR`` at
it through an autouse ``monkeypatch`` fixture, so the override is scoped to
that file's own tests and is cleaned up after each one.

Not a `test_*.py` file, so pytest never collects it.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent


def write_example_config_dir() -> Path:
    """Return a fresh tmp dir holding config/*.example.yaml copied to *.yaml."""
    cfg_dir = Path(tempfile.mkdtemp(prefix="vip-ai-test-config-"))
    for example in (_REPO_ROOT / "config").glob("*.example.yaml"):
        target = cfg_dir / example.name.replace(".example.yaml", ".yaml")
        target.write_text(example.read_text(encoding="utf-8"), encoding="utf-8")
    return cfg_dir
