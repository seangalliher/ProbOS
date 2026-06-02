from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROMPTS_DIR = ROOT / "prompts"

CHILD_TEST_COUNTS = {
    749: 24,
    750: 9,
    751: 6,
    752: 11,
    753: 11,
    754: 14,
    755: 10,
    756: 10,
    757: 9,
}

CHILD_PROMPT_FILES = {
    749: "ad-749-yeo-m365-auth-core-connectors.md",
    750: "ad-750-yeo-semantic-work-layer.md",
    751: "ad-751-yeo-desktop-ux-surface.md",
    752: "ad-752-yeo-proactive-scheduling-work-hours-quiet-hours.md",
    753: "ad-753-yeo-unattended-permissions-modes.md",
    754: "ad-754-yeo-data-hardening-baseline.md",
    755: "ad-755-yeo-office-doc-skills-sharepoint-routing.md",
    756: "ad-756-yeo-conversational-front-door-ux.md",
    757: "ad-757-yeo-identity-continuity-captain-card.md",
}


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _prompt(name: str) -> str:
    # Prompts for closed issues are archived to prompts/archive/ (383dde25).
    # Resolve from prompts/ first, then fall back to the archive.
    p = PROMPTS_DIR / name
    if not p.exists():
        p = PROMPTS_DIR / "archive" / name
    return _read(p)


def test_ad758_program_completion_rubric_and_dedupe_gate() -> None:
    ad758_text = _prompt("ad-758-yeo-feature-complete-integration-gate.md")

    for ad in CHILD_TEST_COUNTS:
        assert f"AD-{ad}" in ad758_text

    assert "Total Expected Tests:" in ad758_text
    assert "104" in ad758_text

    measured_total = 0
    for ad, expected in CHILD_TEST_COUNTS.items():
        child_text = _prompt(CHILD_PROMPT_FILES[ad])
        match = re.search(r"Total:\s*(\d+)\s+new tests", child_text)
        assert match, f"Missing test total for AD-{ad}"
        count = int(match.group(1))
        assert count == expected
        measured_total += count

    assert measured_total == 104

    for ref in ("#480", "#484", "#538", "#486"):
        assert ref in ad758_text

    roadmap_text = _read(ROOT / "docs" / "development" / "roadmap.md")
    for issue in range(695, 705):
        assert f"[#{issue}]" in roadmap_text

    wave_plan = _prompt("wave-plan.yaml")
    wave_181 = re.search(r'id: "181-yeo-kickoff".*?status:\s*(\w+)', wave_plan, re.S)
    assert wave_181
    assert wave_181.group(1) == "shipped"
    assert 'id: "182-yeo-post-gate"' in wave_plan
