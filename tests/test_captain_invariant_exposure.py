from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROMPTS = [
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


def test_captain_invariant_exposure_gate() -> None:
    for name in PROMPTS:
        text = _read(ROOT / "prompts" / name).lower()
        assert "captain invariant" in text
        assert "capability is usable by all crew agents" in text
        assert "yeo is the front-door orchestrator and delegates to specialists" in text

    connector_text = _read(ROOT / "src" / "probos" / "integrations" / "m365_connector.py")
    for intent_name in ("outlook_read_inbox", "teams_list_chats", "calendar_find_time"):
        assert intent_name in connector_text

    runtime_text = _read(ROOT / "src" / "probos" / "runtime.py").lower()
    for symbol in (
        "outlookagent",
        "teamsagent",
        "calendaragent",
        "sharepointagent",
        "onedriveagent",
        "docxagent",
        "pptxagent",
        "xlsxagent",
        "semanticstore",
        "sessionmanager",
    ):
        assert symbol in runtime_text
