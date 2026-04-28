"""AD-594: Tests for Crew Consultation Protocol."""

from __future__ import annotations

import asyncio
import contextlib
import time

import pytest

from probos.cognitive.consultation import (
    ConsultationProtocol,
    ConsultationRequest,
    ConsultationResponse,
    ConsultationUrgency,
)
from probos.config import ConsultationConfig
from probos.events import EventType


class _FakeEventCollector:
    """Collects emitted events for assertion."""

    def __init__(self) -> None:
        self.events: list[tuple[EventType, dict]] = []

    def __call__(self, event_type: EventType, data: dict) -> None:
        self.events.append((event_type, data))


class _FakeCapabilityRegistry:
    """Stub CapabilityRegistry for expert selection tests."""

    def __init__(self, matches: list | None = None) -> None:
        self._matches = matches or []

    def query(self, intent: str, trust_scores=None) -> list:
        return self._matches


class _FakeCapabilityMatch:
    """Stub for CapabilityMatch."""

    def __init__(self, agent_id: str, score: float) -> None:
        self.agent_id = agent_id
        self.score = score


class _FakeBilletHolder:
    """Stub for BilletHolder."""

    def __init__(self, agent_id: str, callsign: str, title: str, department: str) -> None:
        self.holder_agent_id = agent_id
        self.holder_callsign = callsign
        self.title = title
        self.department = department
        self.billet_id = f"billet_{agent_id}"


class _FakeBilletRegistry:
    """Stub BilletRegistry for expert selection tests."""

    def __init__(self, roster: list | None = None) -> None:
        self._roster = roster or []

    def get_roster(self) -> list:
        return self._roster


class _FakeTrustNetwork:
    """Stub trust network."""

    def __init__(self, scores: dict | None = None) -> None:
        self._scores = scores or {}

    def get_score(self, agent_id: str) -> float:
        return self._scores.get(agent_id, 0.5)


@pytest.fixture
def collector() -> _FakeEventCollector:
    return _FakeEventCollector()


@pytest.fixture
def protocol(collector: _FakeEventCollector) -> ConsultationProtocol:
    return ConsultationProtocol(emit_event_fn=collector)


async def _echo_handler(request: ConsultationRequest) -> ConsultationResponse:
    """Simple handler that echoes the topic as the answer."""
    return ConsultationResponse(
        request_id=request.request_id,
        responder_id="expert-1",
        responder_callsign="TestExpert",
        answer=f"Expert answer on: {request.topic}",
        confidence=0.8,
        reasoning_summary="Echoed topic",
    )


async def _slow_handler(request: ConsultationRequest) -> ConsultationResponse:
    """Handler that takes too long."""
    await asyncio.sleep(60)
    return ConsultationResponse()


async def _error_handler(request: ConsultationRequest) -> ConsultationResponse:
    """Handler that raises an exception."""
    raise RuntimeError("Handler failure")


def test_request_dataclass_defaults() -> None:
    request = ConsultationRequest(topic="shield harmonics")

    data = request.to_dict()

    assert request.request_id
    assert request.urgency == ConsultationUrgency.MEDIUM
    assert data["topic"] == "shield harmonics"
    assert data["urgency"] == "medium"


def test_response_dataclass_defaults() -> None:
    response = ConsultationResponse(answer="Proceed")

    data = response.to_dict()

    assert response.confidence == 0.5
    assert data["answer"] == "Proceed"
    assert data["suggested_followup"] is None


def test_urgency_enum_values() -> None:
    assert ConsultationUrgency.LOW.value == "low"
    assert ConsultationUrgency.MEDIUM.value == "medium"
    assert ConsultationUrgency.HIGH.value == "high"


def test_register_handler(protocol: ConsultationProtocol) -> None:
    protocol.register_handler("expert-1", _echo_handler)

    assert protocol.snapshot()["handlers_registered"] == 1


def test_unregister_handler(protocol: ConsultationProtocol) -> None:
    protocol.register_handler("expert-1", _echo_handler)

    protocol.unregister_handler("expert-1")

    assert protocol.snapshot()["handlers_registered"] == 0


@pytest.mark.asyncio
async def test_request_directed_consultation(protocol: ConsultationProtocol) -> None:
    protocol.register_handler("expert-1", _echo_handler)
    request = ConsultationRequest(
        requester_id="agent-a",
        topic="warp core",
        target_agent_id="expert-1",
    )

    response = await protocol.request_consultation(request)

    assert response is not None
    assert response.responder_id == "expert-1"


@pytest.mark.asyncio
async def test_request_returns_response(protocol: ConsultationProtocol) -> None:
    protocol.register_handler("expert-1", _echo_handler)


    response = await protocol.request_consultation(ConsultationRequest(
        requester_id="agent-a",
        topic="diagnostics",
        target_agent_id="expert-1",
    ))

    assert response is not None
    assert response.answer == "Expert answer on: diagnostics"


@pytest.mark.asyncio
async def test_request_emits_events(
    protocol: ConsultationProtocol,
    collector: _FakeEventCollector,
) -> None:
    protocol.register_handler("expert-1", _echo_handler)

    await protocol.request_consultation(ConsultationRequest(
        requester_id="agent-a",
        requester_callsign="Alpha",
        topic="routing",
        target_agent_id="expert-1",
    ))

    assert [event[0] for event in collector.events] == [
        EventType.CONSULTATION_REQUESTED,
        EventType.CONSULTATION_COMPLETED,
    ]


@pytest.mark.asyncio
async def test_request_timeout_returns_none(collector: _FakeEventCollector) -> None:
    cfg = ConsultationConfig(timeout_seconds=0.01)
    protocol = ConsultationProtocol(emit_event_fn=collector, config=cfg)
    protocol.register_handler("expert-1", _slow_handler)

    response = await protocol.request_consultation(ConsultationRequest(
        requester_id="agent-a",
        topic="slow topic",
        target_agent_id="expert-1",
    ))

    assert response is None
    assert collector.events[-1][0] == EventType.CONSULTATION_TIMEOUT


@pytest.mark.asyncio
async def test_request_handler_error_returns_none(protocol: ConsultationProtocol) -> None:
    protocol.register_handler("expert-1", _error_handler)

    response = await protocol.request_consultation(ConsultationRequest(
        requester_id="agent-a",
        topic="fault analysis",
        target_agent_id="expert-1",
    ))

    assert response is None


@pytest.mark.asyncio
async def test_request_no_handler_returns_none(protocol: ConsultationProtocol) -> None:
    response = await protocol.request_consultation(ConsultationRequest(
        requester_id="agent-a",
        topic="unhandled",
        target_agent_id="missing",
    ))

    assert response is None


@pytest.mark.asyncio
async def test_request_empty_topic_returns_none(protocol: ConsultationProtocol) -> None:
    protocol.register_handler("expert-1", _echo_handler)

    response = await protocol.request_consultation(ConsultationRequest(
        requester_id="agent-a",
        target_agent_id="expert-1",
    ))

    assert response is None


@pytest.mark.asyncio
async def test_rate_limit_enforced() -> None:
    cfg = ConsultationConfig(max_consultations_per_agent_per_hour=2)
    protocol = ConsultationProtocol(config=cfg)
    protocol.register_handler("expert-1", _echo_handler)

    for _ in range(2):
        response = await protocol.request_consultation(ConsultationRequest(
            requester_id="agent-a",
            topic="topic",
            target_agent_id="expert-1",
        ))
        assert response is not None

    response = await protocol.request_consultation(ConsultationRequest(
        requester_id="agent-a",
        topic="topic",
        target_agent_id="expert-1",
    ))
    assert response is None


@pytest.mark.asyncio
async def test_rate_limit_expires_after_hour(monkeypatch: pytest.MonkeyPatch) -> None:
    now = 1000.0
    import probos.cognitive.consultation as consultation_module
    monkeypatch.setattr(consultation_module.time, "time", lambda: now)
    cfg = ConsultationConfig(max_consultations_per_agent_per_hour=1)
    protocol = ConsultationProtocol(config=cfg)
    protocol.register_handler("expert-1", _echo_handler)

    first = await protocol.request_consultation(ConsultationRequest(
        requester_id="agent-a",
        topic="topic",
        target_agent_id="expert-1",
    ))
    blocked = await protocol.request_consultation(ConsultationRequest(
        requester_id="agent-a",
        topic="topic",
        target_agent_id="expert-1",
    ))
    now = 5000.0
    allowed = await protocol.request_consultation(ConsultationRequest(
        requester_id="agent-a",
        topic="topic",
        target_agent_id="expert-1",
    ))

    assert first is not None
    assert blocked is None
    assert allowed is not None


@pytest.mark.asyncio
async def test_max_pending_cap() -> None:
    cfg = ConsultationConfig(max_pending_requests=1, timeout_seconds=10.0)
    protocol = ConsultationProtocol(config=cfg)
    gate = asyncio.Event()

    async def blocked_handler(request: ConsultationRequest) -> ConsultationResponse:
        await gate.wait()
        return ConsultationResponse(responder_id="expert-1")

    protocol.register_handler("expert-1", blocked_handler)
    task = asyncio.create_task(protocol.request_consultation(ConsultationRequest(
        requester_id="agent-a",
        topic="first",
        target_agent_id="expert-1",
    )))
    await asyncio.sleep(0)

    response = await protocol.request_consultation(ConsultationRequest(
        requester_id="agent-b",
        topic="second",
        target_agent_id="expert-1",
    ))

    assert response is None
    gate.set()
    await task


def test_expert_selection_capability_match() -> None:
    protocol = ConsultationProtocol(
        capability_registry=_FakeCapabilityRegistry([
            _FakeCapabilityMatch("expert-low", 0.2),
            _FakeCapabilityMatch("expert-high", 0.9),
        ])
    )

    selected = protocol._select_expert(ConsultationRequest(
        requester_id="agent-a",
        topic="navigation",
    ))

    assert selected == "expert-high"


def test_expert_selection_excludes_requester() -> None:
    protocol = ConsultationProtocol(
        capability_registry=_FakeCapabilityRegistry([
            _FakeCapabilityMatch("agent-a", 1.0),
            _FakeCapabilityMatch("expert-1", 0.6),
        ])
    )

    selected = protocol._select_expert(ConsultationRequest(
        requester_id="agent-a",
        topic="navigation",
    ))

    assert selected == "expert-1"


def test_expert_selection_billet_fallback() -> None:
    protocol = ConsultationProtocol(
        billet_registry=_FakeBilletRegistry([
            _FakeBilletHolder("expert-1", "Geordi", "Chief Engineer", "engineering"),
        ])
    )

    selected = protocol._select_expert(ConsultationRequest(
        requester_id="agent-a",
        topic="warp field",
        required_expertise="engineering",
    ))

    assert selected == "expert-1"


def test_expert_selection_trust_weighting() -> None:
    protocol = ConsultationProtocol(
        capability_registry=_FakeCapabilityRegistry([
            _FakeCapabilityMatch("expert-low-trust", 0.7),
            _FakeCapabilityMatch("expert-high-trust", 0.7),
        ]),
        trust_network=_FakeTrustNetwork({
            "expert-low-trust": 0.2,
            "expert-high-trust": 0.9,
        }),
    )

    selected = protocol._select_expert(ConsultationRequest(
        requester_id="agent-a",
        topic="navigation",
    ))

    assert selected == "expert-high-trust"


def test_billet_relevance_scoring() -> None:
    protocol = ConsultationProtocol(
        billet_registry=_FakeBilletRegistry([
            _FakeBilletHolder("engineer", "Geordi", "Chief Engineer", "engineering"),
            _FakeBilletHolder("doctor", "Crusher", "Chief Medical Officer", "medical"),
        ])
    )

    direct = protocol._score_billet_relevance(
        "engineer", ConsultationRequest(required_expertise="engineering")
    )
    partial = protocol._score_billet_relevance(
        "doctor", ConsultationRequest(required_expertise="medical triage")
    )
    none = protocol._score_billet_relevance(
        "doctor", ConsultationRequest(required_expertise="tactical")
    )

    assert direct == 1.0
    assert 0.0 < partial < 1.0
    assert none == 0.0


def test_snapshot_diagnostic(protocol: ConsultationProtocol) -> None:
    protocol.register_handler("expert-1", _echo_handler)

    snapshot = protocol.snapshot()

    assert snapshot == {
        "pending_count": 0,
        "completed_count": 0,
        "handlers_registered": 1,
        "rate_tracker_agents": 0,
    }


@pytest.mark.asyncio
async def test_get_recent_completions(protocol: ConsultationProtocol) -> None:
    protocol.register_handler("expert-1", _echo_handler)

    await protocol.request_consultation(ConsultationRequest(
        requester_id="agent-a",
        topic="recent",
        target_agent_id="expert-1",
    ))

    recent = protocol.get_recent_completions()
    assert len(recent) == 1
    assert recent[0]["request"]["topic"] == "recent"


def test_config_defaults() -> None:
    cfg = ConsultationConfig()

    assert cfg.enabled is True
    assert cfg.timeout_seconds == 30.0
    assert cfg.max_consultations_per_agent_per_hour == 20
    assert cfg.max_pending_requests == 10
    assert cfg.expert_selection_max_candidates == 5
    assert cfg.weight_capability_match == 0.5
    assert cfg.weight_trust == 0.3
    assert cfg.weight_billet_relevance == 0.2


def test_event_type_members_exist() -> None:
    assert EventType.CONSULTATION_REQUESTED.value == "consultation_requested"
    assert EventType.CONSULTATION_COMPLETED.value == "consultation_completed"
    assert EventType.CONSULTATION_TIMEOUT.value == "consultation_timeout"
    assert EventType.CONSULTATION_FAILED.value == "consultation_failed"