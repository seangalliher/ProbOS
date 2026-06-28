"""AD-1078: the proactive communication coaching now teaches when to escalate
from the Ward Room to a dedicated group chat.

The communication-discipline augmentation skill (loaded into every
proactive_think) was entirely Ward-Room-centric, so agents were never reminded
in their active coaching that they could convene a room. AD-1078 adds an
"Escalating to a Group Chat" section with the escalation criterion (the patterns
from the rooms the crew actually opened) and the @callsign tag shape — which
also reinforces AD-1076 (liveness-independent resolution) and AD-1077 (name
peers by callsign).
"""
from __future__ import annotations

from pathlib import Path

_SKILL = Path("config/skills/communication-discipline/SKILL.md")


def _body() -> str:
    return _SKILL.read_text(encoding="utf-8")


def test_skill_teaches_group_chat_escalation():
    body = _body()
    assert "## Escalating to a Group Chat" in body
    assert "[GROUP_CHAT" in body
    assert "@Callsign" in body


def test_skill_teaches_the_escalation_criterion():
    body = _body()
    # The four patterns observed in the rooms the crew actually opened.
    assert "handing a finished work product" in body
    assert "co-authoring" in body
    assert "specialist" in body
    assert "consolidating a scattered investigation" in body


def test_skill_reinforces_exact_callsign_and_resting_peers():
    body = _body()
    # Pairs with AD-1076 (resting peers still join) + AD-1077 (name by callsign).
    assert "exact callsign" in body
    assert "resting" in body


def test_skill_preserves_ward_room_default():
    body = _body()
    assert "most coordination still belongs in the Ward" in body


def test_existing_skill_content_and_metadata_intact():
    # The additive edit must not disturb the augmentation activation, the
    # proactive_think intent, or the original ward-room discipline content
    # (guards the AD-625/626 contract).
    body = _body()
    assert "probos-activation: augmentation" in body
    assert "proactive_think" in body
    assert "probos-skill-id: communication" in body
    assert "[NO_RESPONSE]" in body
    assert "## Capability Map" in body
    assert "## Operating Sequence" in body
    assert "ward_room_discipline" not in body
