"""AD-729b: peer-observation conduct training module tests."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from probos.cognitive.peer_observation_training import (
    grade_module,
    load_module,
    peer_observation_graduation_gate,
    set_peer_observation_certified,
)
from probos.config import SystemConfig
from probos.crew_profile import CrewProfile, PeerPerceptionProfile
from probos.events import EventType


MODULE_PATH = Path("config/manuals/peer_observation_conduct.yaml")


class _FakeAgent:
    def __init__(self, agent_id: str, *, certified: bool = False) -> None:
        self.profile = CrewProfile(
            agent_id=agent_id,
            peer_perception=PeerPerceptionProfile(enabled=True, certified=certified),
        )


class _FakeRegistry:
    def __init__(self) -> None:
        self._agents: dict[str, _FakeAgent] = {}

    def add(self, agent_id: str, *, certified: bool = False) -> None:
        self._agents[agent_id] = _FakeAgent(agent_id, certified=certified)

    def get(self, agent_id: str) -> Any:
        return self._agents.get(agent_id)


class _FakeRuntime:
    def __init__(self, registry: _FakeRegistry) -> None:
        self.registry = registry
        self.emitted: list[tuple[EventType, dict[str, Any]]] = []

    async def emit_event(self, event_type: EventType, payload: dict[str, Any]) -> None:
        self.emitted.append((event_type, dict(payload)))


# 1. module YAML loads correctly.
def test_load_module_succeeds() -> None:
    module = load_module(MODULE_PATH)
    assert module is not None
    assert module["id"] == "peer_observation_conduct"
    assert isinstance(module["sections"], list)
    section_ids = [s["id"] for s in module["sections"]]
    assert "register_identification" in section_ids
    assert "phrasing_practice" in section_ids
    assert "permission_protocol" in section_ids
    assert "pattern_recognition" in section_ids
    assert "final_assessment" in section_ids


# 2. grading pass at and above threshold.
def test_grade_module_pass_above_threshold() -> None:
    module = load_module(MODULE_PATH)
    assert module is not None
    responses = {
        "register_identification": 1.0,
        "phrasing_practice": 1.0,
        "permission_protocol": 0.8,
        "pattern_recognition": 0.0,
    }
    # Weighted: 0.3*1.0 + 0.3*1.0 + 0.3*0.8 + 0.1*0.0 = 0.84 >= 0.8.
    assert grade_module(module=module, responses=responses) is True


# 3. grading fail below threshold.
def test_grade_module_fail_below_threshold() -> None:
    module = load_module(MODULE_PATH)
    assert module is not None
    responses = {
        "register_identification": 0.5,
        "phrasing_practice": 0.5,
        "permission_protocol": 0.5,
        "pattern_recognition": 0.5,
    }
    # Weighted: 0.3*0.5 + 0.3*0.5 + 0.3*0.5 + 0.1*0.5 = 0.5 < 0.8.
    assert grade_module(module=module, responses=responses) is False


# 4. Boot Camp / Qualification gate blocks when required + uncertified.
def test_graduation_gate_blocks_uncertified() -> None:
    cfg = SystemConfig()
    cfg.qualification.peer_observation_certification_required = True
    profile = CrewProfile(agent_id="alpha", peer_perception=PeerPerceptionProfile(certified=False))
    allowed, reason = peer_observation_graduation_gate(
        profile=profile, qualification_config=cfg.qualification,
    )
    assert allowed is False
    assert reason == "peer_observation_certification_required"


# 5. Boot Camp permits when flag default (False) regardless of certified.
def test_graduation_gate_permits_when_flag_off() -> None:
    cfg = SystemConfig()  # default peer_observation_certification_required=False
    profile = CrewProfile(agent_id="alpha", peer_perception=PeerPerceptionProfile(certified=False))
    allowed, reason = peer_observation_graduation_gate(
        profile=profile, qualification_config=cfg.qualification,
    )
    assert allowed is True
    assert reason is None


# 6. Qualification gate permits when certified.
def test_graduation_gate_permits_certified_when_required() -> None:
    cfg = SystemConfig()
    cfg.qualification.peer_observation_certification_required = True
    profile = CrewProfile(agent_id="alpha", peer_perception=PeerPerceptionProfile(certified=True))
    allowed, reason = peer_observation_graduation_gate(
        profile=profile, qualification_config=cfg.qualification,
    )
    assert allowed is True
    assert reason is None


# 7. set_peer_observation_certified mutates CrewProfile + emits event.
@pytest.mark.asyncio
async def test_set_peer_observation_certified_mutates_and_emits() -> None:
    registry = _FakeRegistry()
    registry.add("alpha", certified=False)
    rt = _FakeRuntime(registry)
    ok = await set_peer_observation_certified(
        runtime=rt, agent_id="alpha", value=True, reason="boot_camp_pass",
    )
    assert ok is True
    assert registry.get("alpha").profile.peer_perception.certified is True
    assert (EventType.PEER_OBSERVATION_CERTIFIED, {
        "agent_id": "alpha",
        "value": True,
        "reason": "boot_camp_pass",
    }) in rt.emitted


# 8. certification roundtrips through CrewProfile.to_dict / from_dict.
def test_certification_persists_through_serialisation() -> None:
    profile = CrewProfile(
        agent_id="alpha",
        peer_perception=PeerPerceptionProfile(enabled=True, certified=True),
    )
    serialised = profile.to_dict()
    assert serialised["peer_perception"]["certified"] is True
    restored = CrewProfile.from_dict(serialised)
    assert restored.peer_perception.certified is True
    # Revoke also roundtrips.
    restored.peer_perception.certified = False
    assert CrewProfile.from_dict(restored.to_dict()).peer_perception.certified is False
