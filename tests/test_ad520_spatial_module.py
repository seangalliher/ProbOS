"""AD-520: Tests for src/probos/ontology/spatial.py."""

from __future__ import annotations

import logging
from dataclasses import FrozenInstanceError

import pytest

from probos.ontology.spatial import (
    _DEFAULT_LAYOUT,
    SpatialDeck,
    SpatialLayout,
    compute_agent_positions,
    load_spatial_layout,
)


def test_spatial_deck_and_layout_to_dict_round_trip() -> None:
    deck = SpatialDeck(
        deck_id="test_deck",
        name="Test",
        department_id="science",
        position=(1.0, 2.0, 3.0),
        dimensions=(4.0, 5.0, 6.0),
        post_offsets={"role_a": (0.5, 0.0, 0.0)},
        accent_color="#abcdef",
    )
    layout = SpatialLayout(decks=[deck], schema_version=1)
    d = layout.to_dict()
    assert d["schema_version"] == 1
    assert len(d["decks"]) == 1
    deck_d = d["decks"][0]
    assert deck_d["deck_id"] == "test_deck"
    assert deck_d["name"] == "Test"
    assert deck_d["department_id"] == "science"
    assert deck_d["position"] == [1.0, 2.0, 3.0]
    assert deck_d["dimensions"] == [4.0, 5.0, 6.0]
    assert deck_d["post_offsets"] == {"role_a": [0.5, 0.0, 0.0]}
    assert deck_d["accent_color"] == "#abcdef"
    # Frozen
    with pytest.raises(FrozenInstanceError):
        deck.deck_id = "nope"  # type: ignore[misc]


def test_default_layout_ships_all_required_decks() -> None:
    deck_ids = {d.deck_id for d in _DEFAULT_LAYOUT.decks}
    required = {"bridge", "engineering", "sickbay", "tactical", "science_lab", "computer_core"}
    assert required.issubset(deck_ids)
    assert len(_DEFAULT_LAYOUT.decks) >= 6
    for d in _DEFAULT_LAYOUT.decks:
        assert isinstance(d.position, tuple)
        assert len(d.position) == 3
        for v in d.position:
            assert isinstance(v, float)
    bridge = next(d for d in _DEFAULT_LAYOUT.decks if d.deck_id == "bridge")
    assert len(bridge.post_offsets) >= 1


def test_load_spatial_layout_none_returns_default() -> None:
    assert load_spatial_layout(None) is _DEFAULT_LAYOUT
    assert load_spatial_layout("") is _DEFAULT_LAYOUT


def test_load_spatial_layout_missing_path_warns_and_returns_default(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.WARNING, logger="probos.ontology.spatial"):
        result = load_spatial_layout("does/not/exist/spatial.yaml")
    assert result is _DEFAULT_LAYOUT
    assert any("not found" in r.message for r in caplog.records)


def test_load_spatial_layout_malformed_yaml_warns_and_returns_default(
    tmp_path, caplog: pytest.LogCaptureFixture
) -> None:
    bad = tmp_path / "bad.yaml"
    bad.write_text("not: valid: yaml: [unclosed", encoding="utf-8")
    with caplog.at_level(logging.WARNING, logger="probos.ontology.spatial"):
        result = load_spatial_layout(str(bad))
    assert result is _DEFAULT_LAYOUT
    assert any("failed to parse" in r.message for r in caplog.records)


def test_compute_agent_positions_known_and_unknown_department() -> None:
    manifest = [
        {
            "agent_type": "engineer-1",
            "agent_id": "engineer-1-id",
            "department": "engineering",
            "post": "chief_engineer",
            "on_watch": True,
        },
        {
            "agent_type": "drifter",
            "agent_id": "drifter-id",
            "department": "no-such-dept",
            "post": "wanderer",
            "on_watch": True,
        },
    ]
    placements = compute_agent_positions(_DEFAULT_LAYOUT, manifest)
    assert len(placements) == 2
    eng = next(p for p in placements if p["agent_id"] == "engineer-1-id")
    eng_deck = next(d for d in _DEFAULT_LAYOUT.decks if d.deck_id == "engineering")
    expected = [
        eng_deck.position[0] + eng_deck.post_offsets["chief_engineer"][0],
        eng_deck.position[1] + eng_deck.post_offsets["chief_engineer"][1],
        eng_deck.position[2] + eng_deck.post_offsets["chief_engineer"][2],
    ]
    assert eng["position"] == expected
    assert eng["deck_id"] == "engineering"
    assert eng["on_watch"] is True

    drift = next(p for p in placements if p["agent_id"] == "drifter-id")
    assert drift["deck_id"] == "common_areas"
    assert drift["on_watch"] is False
