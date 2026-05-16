"""AD-722a-6: cross-agent intent-vs-presentation divergence observation tests."""
from __future__ import annotations

import inspect
import re
import time
from collections import deque
from dataclasses import dataclass
from typing import Any

import pytest

from probos.avatars import peer_perception as pp
from probos.avatars.peer_perception import (
    ObservationRegister,
    PeerObservation,
    observe_peer_divergence,
    register_permission_listener,
    request_permission,
    reset_state,
)
from probos.config import SystemConfig
from probos.crew_profile import CrewProfile, PeerPerceptionProfile
from probos.events import EventType


@dataclass(frozen=True)
class _FakeDivergenceResult:
    intent_emotion: str
    magnitude: float


@dataclass(frozen=True)
class _FakeDivergenceHistoryEntry:
    timestamp: float
    result: _FakeDivergenceResult


class _FakeAgent:
    def __init__(self, *, agent_id: str, enabled: bool, certified: bool) -> None:
        self.profile = CrewProfile(
            agent_id=agent_id,
            peer_perception=PeerPerceptionProfile(enabled=enabled, certified=certified),
        )


class _FakeRegistry:
    def __init__(self) -> None:
        self._agents: dict[str, _FakeAgent] = {}

    def add(self, agent_id: str, *, enabled: bool = True, certified: bool = False) -> None:
        self._agents[agent_id] = _FakeAgent(
            agent_id=agent_id, enabled=enabled, certified=certified
        )

    def get(self, agent_id: str) -> Any:
        return self._agents.get(agent_id)


class _FakeRuntime:
    def __init__(
        self,
        *,
        config: SystemConfig,
        registry: _FakeRegistry,
        divergence_history: dict[str, deque] | None = None,
    ) -> None:
        self.config = config
        self.registry = registry
        self.records_store = None
        self.divergence_history = divergence_history if divergence_history is not None else {}
        self.emitted: list[tuple[EventType, dict[str, Any]]] = []

    async def emit_event(self, event_type: EventType, payload: dict[str, Any]) -> None:
        self.emitted.append((event_type, dict(payload)))


def _config_enabled() -> SystemConfig:
    cfg = SystemConfig()
    cfg.avatars.peer_perception_enabled = True
    cfg.avatars.peer_observation_max_per_pair_per_thread = 5
    cfg.avatars.peer_observation_decay_seconds = 3600
    cfg.avatars.cross_agent_divergence_observation_enabled = True
    cfg.avatars.vision_intent_divergence_enabled = True
    return cfg


def _runtime_with_history(entries: list[_FakeDivergenceHistoryEntry]) -> _FakeRuntime:
    registry = _FakeRegistry()
    registry.add("maya", enabled=True, certified=True)
    registry.add("ezri", enabled=True, certified=False)
    history = {"ezri": deque(entries, maxlen=100)}
    return _FakeRuntime(config=_config_enabled(), registry=registry, divergence_history=history)


def _standard_history() -> list[_FakeDivergenceHistoryEntry]:
    now = time.time()
    return [
        _FakeDivergenceHistoryEntry(
            timestamp=now - 100,
            result=_FakeDivergenceResult(intent_emotion="concerned", magnitude=0.5),
        ),
        _FakeDivergenceHistoryEntry(
            timestamp=now - 200,
            result=_FakeDivergenceResult(intent_emotion="concerned", magnitude=0.4),
        ),
        _FakeDivergenceHistoryEntry(
            timestamp=now - 300,
            result=_FakeDivergenceResult(intent_emotion="calm", magnitude=0.3),
        ),
    ]


@pytest.fixture(autouse=True)
def _reset():
    reset_state()
    yield
    reset_state()


# 1. happy path.
@pytest.mark.asyncio
async def test_happy_path_returns_observation() -> None:
    rt = _runtime_with_history(_standard_history())
    result = await observe_peer_divergence(
        runtime=rt, observer_id="maya", observed_id="ezri",
    )
    assert isinstance(result, PeerObservation)
    assert result.register == ObservationRegister.OPERATIONAL
    types = [et for et, _ in rt.emitted]
    assert EventType.CROSS_AGENT_DIVERGENCE_OBSERVED in types
    assert EventType.PEER_OBSERVATION_RECORDED in types


# 2. capability disabled → None, no events.
@pytest.mark.asyncio
async def test_capability_disabled_returns_none() -> None:
    rt = _runtime_with_history(_standard_history())
    rt.config.avatars.cross_agent_divergence_observation_enabled = False
    result = await observe_peer_divergence(
        runtime=rt, observer_id="maya", observed_id="ezri",
    )
    assert result is None
    # No event traffic on AD-722a-6 gate failure.
    assert all(et is not EventType.CROSS_AGENT_DIVERGENCE_OBSERVED for et, _ in rt.emitted)


# 3. upstream AD-722a-1 detector disabled → None.
@pytest.mark.asyncio
async def test_upstream_detector_disabled_returns_none() -> None:
    rt = _runtime_with_history(_standard_history())
    rt.config.avatars.vision_intent_divergence_enabled = False
    result = await observe_peer_divergence(
        runtime=rt, observer_id="maya", observed_id="ezri",
    )
    assert result is None


# 4. observed has no recent divergence data → None.
@pytest.mark.asyncio
async def test_no_recent_divergence_returns_none() -> None:
    rt = _runtime_with_history([])
    result = await observe_peer_divergence(
        runtime=rt, observer_id="maya", observed_id="ezri",
    )
    assert result is None


# 5. AD-729 gate: observer uncertified → declined (delegated).
@pytest.mark.asyncio
async def test_observer_uncertified_delegated_decline() -> None:
    rt = _runtime_with_history(_standard_history())
    # Replace the registry's observer with an uncertified one.
    rt.registry.add("maya", enabled=True, certified=False)
    result = await observe_peer_divergence(
        runtime=rt, observer_id="maya", observed_id="ezri",
    )
    assert result is None
    decline_payloads = [
        p for et, p in rt.emitted if et is EventType.PEER_OBSERVATION_DECLINED
    ]
    assert decline_payloads
    assert decline_payloads[-1]["reason"] == "observer_uncertified"


# 6. AD-729 gate: observed opt-out → declined (delegated).
@pytest.mark.asyncio
async def test_observed_opted_out_delegated_decline() -> None:
    rt = _runtime_with_history(_standard_history())
    rt.registry.add("ezri", enabled=False, certified=False)
    result = await observe_peer_divergence(
        runtime=rt, observer_id="maya", observed_id="ezri",
    )
    assert result is None
    decline_payloads = [
        p for et, p in rt.emitted if et is EventType.PEER_OBSERVATION_DECLINED
    ]
    assert decline_payloads[-1]["reason"] == "observed_opted_out"


# 7. AD-729 gate: PERSONAL register requires permission_grant.
@pytest.mark.asyncio
async def test_personal_without_grant_delegated_decline() -> None:
    rt = _runtime_with_history(_standard_history())
    result = await observe_peer_divergence(
        runtime=rt, observer_id="maya", observed_id="ezri",
        register=ObservationRegister.PERSONAL,
    )
    assert result is None
    decline_payloads = [
        p for et, p in rt.emitted if et is EventType.PEER_OBSERVATION_DECLINED
    ]
    assert decline_payloads[-1]["reason"] == "permission_required"


# 8. summary template OPERATIONAL phrasing — no value-judgment vocabulary.
def test_summary_template_operational_phrasing_no_value_judgment() -> None:
    summary = pp._format_divergence_summary(_standard_history())
    # No PERSONAL-register vocabulary should appear.
    forbidden = re.compile(
        r"\b(she|he|they|seems|stressed|sad|happy|tired|upset|fine)\b",
        re.IGNORECASE,
    )
    assert forbidden.search(summary) is None, f"PERSONAL phrasing leaked: {summary}"
    # Should mention the count + magnitude + dominant emotion.
    assert "divergence" in summary.lower()
    assert "magnitude" in summary.lower()


# 9. CROSS_AGENT_DIVERGENCE_OBSERVED payload integrity.
@pytest.mark.asyncio
async def test_cross_agent_event_payload_integrity() -> None:
    rt = _runtime_with_history(_standard_history())
    await observe_peer_divergence(
        runtime=rt, observer_id="maya", observed_id="ezri",
    )
    payloads = [
        p for et, p in rt.emitted if et is EventType.CROSS_AGENT_DIVERGENCE_OBSERVED
    ]
    assert len(payloads) == 1
    payload = payloads[0]
    assert payload["observer_id"] == "maya"
    assert payload["observed_id"] == "ezri"
    assert payload["register"] == "operational"
    assert payload["divergence_count"] == 3
    assert "summary" in payload
    assert "timestamp" in payload


# 10. AD-731 invariant: payload carries no inline image bytes.
@pytest.mark.asyncio
async def test_ad731_invariant_no_inline_image_bytes() -> None:
    rt = _runtime_with_history(_standard_history())
    await observe_peer_divergence(
        runtime=rt, observer_id="maya", observed_id="ezri",
    )
    for _, payload in rt.emitted:
        assert "image_url" not in payload
        assert "source" not in payload
    # Module source-scan: AD-722a-6 path adds no base64 inlining.
    source = inspect.getsource(pp)
    assert "b64encode" not in source
    assert "base64.b64" not in source
