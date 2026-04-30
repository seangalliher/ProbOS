from __future__ import annotations

import time
from typing import Any
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from probos.cognitive.counselor import (
    CounselorAgent,
    CounselorAssessment,
    InterventionRecord,
    InterventionType,
)
from probos.events import EventType
from probos.routers.counselor import router
from probos.routers.deps import get_runtime


class _FakeProactiveLoop:
    def __init__(self) -> None:
        self.cooldowns: list[tuple[str, float, str]] = []

    def get_agent_cooldown(self, agent_id: str) -> float:
        return 100.0

    def set_agent_cooldown(self, agent_id: str, cooldown: float, *, reason: str) -> None:
        self.cooldowns.append((agent_id, cooldown, reason))


class _FakeDreamScheduler:
    is_dreaming = False

    def __init__(self) -> None:
        self.force_dream = AsyncMock()


class _FakeRegistry:
    def get(self, agent_id: str) -> Any:
        return type("Agent", (), {"agent_type": "science"})()


class _FakePoolRegistry:
    def __init__(self, counselor: CounselorAgent | None) -> None:
        self._counselor = counselor

    def get_by_pool(self, pool: str) -> list[CounselorAgent]:
        if pool == "counselor" and self._counselor is not None:
            return [self._counselor]
        return []


class _FakeRuntime:
    def __init__(self, counselor: CounselorAgent | None) -> None:
        self.pools = {"counselor": object()} if counselor is not None else {}
        self.registry = _FakePoolRegistry(counselor)


def _client_for(runtime: _FakeRuntime) -> TestClient:
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_runtime] = lambda: runtime
    return TestClient(app)


def _make_assessment(trigger: str = "sweep") -> CounselorAssessment:
    return CounselorAssessment(
        timestamp=time.time(),
        agent_id="agent-1",
        trigger=trigger,
        wellness_score=0.2,
        fit_for_duty=False,
        concerns=["Repetitive output detected"],
        recommendations=["Redirect attention"],
    )


def _make_counselor(**kwargs: Any) -> CounselorAgent:
    agent = object.__new__(CounselorAgent)
    agent.id = "counselor-001"
    agent.callsign = "Counselor"
    agent._ward_room = kwargs.get("ward_room")
    agent._ward_room_router = None
    agent._directive_store = None
    agent._dream_scheduler = kwargs.get("dream_scheduler")
    agent._proactive_loop = kwargs.get("proactive_loop")
    agent._registry = kwargs.get("registry")
    agent._dm_cooldowns = {}
    agent._intervention_targets = set()
    agent._intervention_history = []
    agent._emit_event_fn = kwargs.get("emit_event_fn")
    agent.DM_COOLDOWN_SECONDS = 0
    return agent


def test_intervention_type_enum_values() -> None:
    assert InterventionType.THERAPEUTIC_DM.value == "therapeutic_dm"
    assert InterventionType.COOLDOWN_EXTENSION.value == "cooldown_extension"
    assert InterventionType.FORCED_DREAM.value == "forced_dream"
    assert InterventionType.GUIDANCE_DIRECTIVE.value == "guidance_directive"
    assert InterventionType.TRUST_ADJUSTMENT.value == "trust_adjustment"


def test_intervention_record_creation() -> None:
    record = InterventionRecord(
        intervention_type=InterventionType.THERAPEUTIC_DM,
        agent_id="agent-1",
        callsign="Worf",
        trigger="sweep",
        severity="concern",
        detail="Therapeutic DM sent",
    )

    assert record.intervention_type is InterventionType.THERAPEUTIC_DM
    assert record.agent_id == "agent-1"
    assert record.callsign == "Worf"
    assert record.trigger == "sweep"
    assert record.severity == "concern"
    assert record.detail == "Therapeutic DM sent"


def test_intervention_record_default_timestamp() -> None:
    before = time.time()
    record = InterventionRecord(
        intervention_type=InterventionType.FORCED_DREAM,
        agent_id="agent-1",
        callsign="Worf",
        trigger="zone",
        severity="intervention",
        detail="Forced dream cycle initiated",
    )

    assert before <= record.timestamp <= time.time()


def test_counselor_intervention_event_type() -> None:
    assert EventType.COUNSELOR_INTERVENTION.value == "counselor_intervention"


def test_record_intervention_appends_to_history() -> None:
    counselor = _make_counselor()

    record = counselor._record_intervention(
        InterventionType.THERAPEUTIC_DM,
        "agent-1",
        "Worf",
        "sweep",
        "concern",
        "Therapeutic DM sent",
    )

    assert counselor._intervention_history == [record]


def test_record_intervention_emits_event() -> None:
    emitted: list[tuple[Any, dict[str, Any]]] = []
    counselor = _make_counselor(
        emit_event_fn=lambda event_type, payload: emitted.append((event_type, payload)),
    )

    counselor._record_intervention(
        InterventionType.COOLDOWN_EXTENSION,
        "agent-1",
        "Worf",
        "sweep",
        "intervention",
        "Cooldown extended",
    )

    assert emitted[0][0] is EventType.COUNSELOR_INTERVENTION
    assert emitted[0][1]["intervention_type"] == "cooldown_extension"
    assert emitted[0][1]["agent_id"] == "agent-1"


@pytest.mark.asyncio
async def test_therapeutic_dm_records_intervention() -> None:
    ward_room = AsyncMock()
    ward_room.get_or_create_dm_channel = AsyncMock(return_value=type("Channel", (), {"id": "dm-1"})())
    ward_room.create_thread = AsyncMock()
    counselor = _make_counselor(ward_room=ward_room)

    assert await counselor._send_therapeutic_dm("agent-1", "Worf", "Hello") is True

    assert counselor._intervention_history[-1].intervention_type is InterventionType.THERAPEUTIC_DM


@pytest.mark.asyncio
async def test_cooldown_extension_records_intervention() -> None:
    counselor = _make_counselor(proactive_loop=_FakeProactiveLoop())

    await counselor._apply_intervention("agent-1", "Worf", _make_assessment(), "intervention")

    assert any(
        r.intervention_type is InterventionType.COOLDOWN_EXTENSION
        for r in counselor._intervention_history
    )


@pytest.mark.asyncio
async def test_forced_dream_records_intervention() -> None:
    counselor = _make_counselor(dream_scheduler=_FakeDreamScheduler())

    await counselor._apply_intervention("agent-1", "Worf", _make_assessment(), "intervention")

    assert any(
        r.intervention_type is InterventionType.FORCED_DREAM
        for r in counselor._intervention_history
    )


@pytest.mark.asyncio
async def test_guidance_directive_records_intervention() -> None:
    counselor = _make_counselor(registry=_FakeRegistry())
    counselor._issue_guidance_directive = lambda agent_type, content: True

    await counselor._apply_intervention("agent-1", "Worf", _make_assessment(), "intervention")

    assert any(
        r.intervention_type is InterventionType.GUIDANCE_DIRECTIVE
        for r in counselor._intervention_history
    )


def test_get_intervention_history_filter_by_agent() -> None:
    counselor = _make_counselor()
    counselor._record_intervention(InterventionType.THERAPEUTIC_DM, "agent-1", "Worf", "sweep", "concern", "dm")
    counselor._record_intervention(InterventionType.FORCED_DREAM, "agent-2", "Data", "sweep", "intervention", "dream")

    history = counselor.get_intervention_history(agent_id="agent-1")

    assert len(history) == 1
    assert history[0].agent_id == "agent-1"


def test_get_intervention_history_filter_by_type() -> None:
    counselor = _make_counselor()
    counselor._record_intervention(InterventionType.THERAPEUTIC_DM, "agent-1", "Worf", "sweep", "concern", "dm")
    counselor._record_intervention(InterventionType.FORCED_DREAM, "agent-2", "Data", "sweep", "intervention", "dream")

    history = counselor.get_intervention_history(intervention_type=InterventionType.FORCED_DREAM)

    assert len(history) == 1
    assert history[0].intervention_type is InterventionType.FORCED_DREAM


def test_get_intervention_summary() -> None:
    counselor = _make_counselor()
    counselor._record_intervention(InterventionType.THERAPEUTIC_DM, "agent-1", "Worf", "sweep", "concern", "dm")
    counselor._record_intervention(InterventionType.THERAPEUTIC_DM, "agent-2", "Data", "sweep", "concern", "dm")
    counselor._record_intervention(InterventionType.FORCED_DREAM, "agent-2", "Data", "zone", "intervention", "dream")

    assert counselor.get_intervention_summary() == {
        "therapeutic_dm": 2,
        "forced_dream": 1,
    }


def test_get_interventions_endpoint_returns_summary() -> None:
    counselor = _make_counselor()
    counselor._record_intervention(InterventionType.THERAPEUTIC_DM, "agent-1", "Worf", "sweep", "concern", "dm")
    client = _client_for(_FakeRuntime(counselor))

    response = client.get("/api/counselor/interventions")
    payload = response.json()

    assert response.status_code == 200
    assert payload["summary"] == {"therapeutic_dm": 1}
    assert payload["recent"][0]["type"] == "therapeutic_dm"


def test_get_interventions_endpoint_without_counselor_returns_status() -> None:
    client = _client_for(_FakeRuntime(None))

    response = client.get("/api/counselor/interventions")

    assert response.status_code == 200
    assert response.json() == {"status": "no_counselor", "summary": {}, "recent": []}
