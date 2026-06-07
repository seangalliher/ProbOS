"""AD-910: Yeoman personal standing orders + Bridge department assignment.

The Captain's Yeoman (AD-766, ``agent_type="yeoman"``) previously had NO
personal standing orders file and was not mapped to a department, so
``compose_instructions`` loaded only the federation + ship tiers for him.
AD-910 adds ``config/standing_orders/yeoman.md`` (the Tier-5 agent file) and
maps ``yeoman -> bridge`` in the legacy department fallback so he also
inherits the Bridge department protocols like the Counselor.

Real ``compose_instructions`` against the on-disk standing-order files — no
mocks (the file content IS the contract).
"""

from __future__ import annotations

from pathlib import Path

from probos.cognitive.standing_orders import (
    clear_cache,
    compose_instructions,
    get_department,
)


def test_yeoman_personal_standing_orders_file_exists() -> None:
    path = Path("config/standing_orders/yeoman.md")
    assert path.is_file(), "AD-910: yeoman.md personal standing orders missing"
    text = path.read_text(encoding="utf-8")
    assert "Yeoman — Personal Standing Orders" in text


def test_yeoman_personal_standing_orders_compose() -> None:
    clear_cache()
    composed = compose_instructions(
        agent_type="yeoman", hardcoded_instructions="", callsign="Yeo",
    )
    # The Tier-5 agent file loads as "Personal Standing Orders".
    assert "Yeoman — Personal Standing Orders" in composed
    # A role-specific phrase proves the file content (not just the header)
    # reached the composed instructions.
    assert "reduce the Captain" in composed


def test_yeoman_standing_orders_teach_honesty_clause() -> None:
    """The honesty clause is the seam that prevents the confabulation the
    Captain observed (claiming a note was saved when it was not)."""
    clear_cache()
    composed = compose_instructions(
        agent_type="yeoman", hardcoded_instructions="", callsign="Yeo",
    )
    assert "Never claim to have done something you did not do" in composed


def test_yeoman_mapped_to_bridge_department() -> None:
    assert get_department("yeoman") == "bridge"


def test_counselor_department_unchanged() -> None:
    # Open/Closed: the existing Bridge mapping is untouched.
    assert get_department("counselor") == "bridge"


def test_unmapped_agent_still_returns_none() -> None:
    assert get_department("nonexistent_agent_xyz") is None
