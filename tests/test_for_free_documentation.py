from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHILD_AD_PROMPTS = [
    "ad-749-yeo-m365-auth-core-connectors.md",
    "ad-750-yeo-semantic-work-layer.md",
    "ad-751-yeo-desktop-ux-surface.md",
    "ad-752-yeo-proactive-scheduling-work-hours-quiet-hours.md",
    "ad-753-yeo-unattended-permissions-modes.md",
    "ad-754-yeo-data-hardening-baseline.md",
    "ad-755-yeo-office-doc-skills-sharepoint-routing.md",
    "ad-756-yeo-conversational-front-door-ux.md",
    "ad-757-yeo-identity-continuity-captain-card.md",
]


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_for_free_learning_documented_for_all_child_ads() -> None:
    for file_name in CHILD_AD_PROMPTS:
        text = _read(ROOT / "prompts" / file_name).lower()
        assert "for free leverage" in text
