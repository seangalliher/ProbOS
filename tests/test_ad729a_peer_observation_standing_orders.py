"""AD-729a: Peer observation Standing Orders extension — boundary tests.

Verifies the markdown content authored by the Captain (issue #588) is present
verbatim in `config/standing_orders/peer_observation.md`, and that the
ship-wide standing orders cross-reference the new file.
"""
from __future__ import annotations

from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parent.parent
PEER_OBS_PATH = REPO_ROOT / "config" / "standing_orders" / "peer_observation.md"
SHIP_PATH = REPO_ROOT / "config" / "standing_orders" / "ship.md"


@pytest.fixture(scope="module")
def peer_observation_text() -> str:
    assert PEER_OBS_PATH.exists(), f"missing: {PEER_OBS_PATH}"
    return PEER_OBS_PATH.read_text(encoding="utf-8")


def test_peer_observation_md_exists_and_loads(peer_observation_text: str) -> None:
    assert peer_observation_text.strip(), "peer_observation.md is empty"
    assert "# Peer Observation" in peer_observation_text
    assert "AD-729a" in peer_observation_text
    assert "AD-489" in peer_observation_text


def test_section_1_operational_observation_phrases_present(peer_observation_text: str) -> None:
    assert (
        "Crew may make observations of fellow crew's presentation when operationally relevant"
        in peer_observation_text
    )
    assert "Operational observations are phrased descriptively, not evaluatively" in peer_observation_text


def test_section_2_personal_commentary_phrases_present(peer_observation_text: str) -> None:
    assert (
        "Personal commentary about a fellow crew member's presentation is a privilege, not a right"
        in peer_observation_text
    )
    assert "Granted permission applies to a single exchange" in peer_observation_text


def test_section_3_prohibited_behavior_phrases_present(peer_observation_text: str) -> None:
    assert (
        "Cascade observation — repeating an observation made by another officer without independent corroboration — is prohibited"
        in peer_observation_text
    )
    assert "Aesthetic conformity pressure" in peer_observation_text
    assert "Static impressions" in peer_observation_text


def test_section_4_permission_protocol_phrases_present(peer_observation_text: str) -> None:
    assert "[PERMISSION_REQUEST observed_agent: <id>, register: personal]" in peer_observation_text
    assert "[PERMISSION_GRANTED]" in peer_observation_text
    assert "[PERMISSION_DENIED <optional reason>]" in peer_observation_text


def test_section_5_captain_exception_phrases_present(peer_observation_text: str) -> None:
    assert (
        "The Captain may make either register of observation at any time without requesting permission"
        in peer_observation_text
    )
    assert "Rank does not exempt from Code of Conduct" in peer_observation_text


def test_ship_md_cross_references_peer_observation() -> None:
    assert SHIP_PATH.exists(), f"missing: {SHIP_PATH}"
    ship_text = SHIP_PATH.read_text(encoding="utf-8")
    assert "peer_observation.md" in ship_text, "ship.md must cross-reference peer_observation.md"
    assert "AD-729a" in ship_text, "ship.md must mention AD-729a"
