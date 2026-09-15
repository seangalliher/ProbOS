"""AD-588: Telemetry-Grounded Introspection — Tests.

Tests for IntrospectiveTelemetryService, self-query detection,
telemetry injection in DM/WR/proactive paths, and rendering.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from probos.cognitive.introspective_telemetry import IntrospectiveTelemetryService
from probos.config import SystemConfig


# ── Helpers ──────────────────────────────────────────────────────


def _make_runtime(
    *,
    episodic_memory: Any = None,
    trust_network: Any = None,
    hebbian_router: Any = None,
    registry: Any = None,
    uptime_seconds: float | None = 0.0,
    lifecycle_state: str = "running",
) -> MagicMock:
    rt = MagicMock()
    rt.episodic_memory = episodic_memory
    rt.trust_network = trust_network
    rt.hebbian_router = hebbian_router
    rt.registry = registry
    rt.identity_registry = None
    rt.get_uptime_seconds.return_value = uptime_seconds
    rt._lifecycle_state = lifecycle_state
    return rt


@dataclass
class _Issue1370Memory:
    count: int = 47
    is_available: bool = True
    calls: list[str] = field(default_factory=list)
    failure: BaseException | None = None

    async def count_for_agent(self, agent_id: str) -> int:
        self.calls.append(agent_id)
        if self.failure is not None:
            raise self.failure
        return self.count


@dataclass
class _Issue1370Registry:
    agent: Any = None

    def get(self, agent_id: str) -> Any:
        return self.agent if self.agent is not None and self.agent.id == agent_id else None


@pytest.mark.asyncio
@pytest.mark.parametrize("identity", ["runtime", "sovereign", "slot", "unmapped"])
async def test_issue1370_memory_resolves_only_membership_subject(identity: str) -> None:
    memory = _Issue1370Memory()
    agent = SimpleNamespace(id="runtime", sovereign_id="sovereign")
    slot_calls: list[str] = []

    class _IdentityRegistry:
        def get_by_slot(self, slot_id: str) -> Any:
            slot_calls.append(slot_id)
            return SimpleNamespace(agent_uuid="sovereign") if slot_id == "slot" else None

    service = IntrospectiveTelemetryService(runtime=SimpleNamespace(
        registry=_Issue1370Registry(agent), identity_registry=_IdentityRegistry(),
        episodic_memory=memory,
    ))
    before = datetime.now(timezone.utc)
    result = await service.get_memory_state(identity)
    after = datetime.now(timezone.utc)

    subject = "unmapped" if identity == "unmapped" else "sovereign"
    assert memory.calls == [subject]
    assert slot_calls == ([] if identity == "runtime" else [identity])
    assert result["episode_count"] == 47
    metadata = result["measurement"]
    assert metadata["subject_id"] == subject
    assert metadata["population"] == "stored_agent_membership"
    assert metadata["source"] == "episodic_memory.count_for_agent"
    assert metadata["unit"] == "episodes"
    assert metadata["status"] == "available"
    assert before <= datetime.fromisoformat(metadata["sample_started_at"]) <= datetime.fromisoformat(metadata["sample_completed_at"]) <= after


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["empty", "unmapped-agent", "legacy", "mock", "stopped", "resolution-error", "invalid-subject", "availability-error", "count-error", "negative", "boolean", "stopped-during-count"])
async def test_issue1370_memory_unknown_and_empty_paths(case: str, caplog: pytest.LogCaptureFixture) -> None:
    memory = _Issue1370Memory(count=0)
    runtime = SimpleNamespace(episodic_memory=memory, registry=None, identity_registry=None)
    identity = "runtime"
    expected_status = "unavailable"
    if case == "empty":
        identity = ""
    elif case == "unmapped-agent":
        runtime.registry = _Issue1370Registry(SimpleNamespace(id="runtime", sovereign_id=""))
        expected_status = "available"
    elif case == "legacy":
        class _LegacyMemory:
            async def count_for_agent(self, agent_id: str) -> int:
                raise AssertionError("Legacy availability was assumed")
        runtime.episodic_memory = _LegacyMemory()
    elif case == "mock":
        runtime.episodic_memory = MagicMock()
    elif case == "stopped":
        memory.is_available = False
    elif case == "resolution-error":
        class _BrokenRegistry:
            def get(self, agent_id: str) -> None:
                raise RuntimeError("private-measurement-payload")
        runtime.registry = _BrokenRegistry()
        expected_status = "failed"
    elif case == "invalid-subject":
        runtime.registry = _Issue1370Registry(SimpleNamespace(id="runtime", sovereign_id=object()))
        expected_status = "failed"
    elif case == "availability-error":
        class _BrokenAvailability:
            @property
            def is_available(self) -> bool:
                raise RuntimeError("private-measurement-payload")
        runtime.episodic_memory = _BrokenAvailability()
        expected_status = "failed"
    elif case == "count-error":
        memory.failure = RuntimeError("private-measurement-payload")
        expected_status = "failed"
    elif case in ("negative", "boolean"):
        memory.count = -1 if case == "negative" else True
        expected_status = "failed"
    elif case == "stopped-during-count":
        class _StoppingMemory(_Issue1370Memory):
            async def count_for_agent(self, agent_id: str) -> int:
                count = await super().count_for_agent(agent_id)
                self.is_available = False
                return count
        memory = _StoppingMemory(count=0)
        runtime.episodic_memory = memory
    result = await IntrospectiveTelemetryService(runtime=runtime).get_memory_state(identity)
    assert result["measurement"]["status"] == expected_status
    assert result["episode_count"] == (0 if expected_status == "available" else "unknown")
    assert memory.calls == (["runtime"] if case in {"unmapped-agent", "count-error", "negative", "boolean", "stopped-during-count"} else [])
    assert "private-measurement-payload" not in caplog.text + repr(result)


@pytest.mark.asyncio
async def test_issue1370_memory_cancellation_propagates() -> None:
    memory = _Issue1370Memory(failure=asyncio.CancelledError())
    service = IntrospectiveTelemetryService(runtime=SimpleNamespace(episodic_memory=memory))
    with pytest.raises(asyncio.CancelledError):
        await service.get_memory_state("subject")
    assert memory.calls == ["subject"]


@pytest.mark.asyncio
@pytest.mark.parametrize("seconds", [0.0, 10800.0, None, -1.0, float("nan"), float("inf"), True, "3"])
async def test_issue1370_temporal_uses_public_seconds(seconds: Any) -> None:
    calls: list[str] = []

    class _Clock:
        def get_uptime_seconds(self) -> float | None:
            calls.append("clock")
            return seconds

    service = IntrospectiveTelemetryService(runtime=_Clock())
    result = await service.get_temporal_state("subject")
    assert calls == ["clock"]
    metadata = result["uptime_measurement"]
    assert metadata["subject_id"] == "system"
    assert metadata["population"] == "system_runtime"
    assert metadata["unit"] == "seconds"
    assert metadata["source"] == "runtime.get_uptime_seconds"
    if type(seconds) is float and seconds in (0.0, 10800.0):
        assert result["system_uptime_seconds"] == seconds
        assert result["system_uptime_hours"] == round(seconds / 3600, 1)
        assert metadata["status"] == "available"
    else:
        assert "system_uptime_seconds" not in result
        assert "system_uptime_hours" not in result
        assert metadata["status"] == ("unavailable" if seconds is None else "failed")


@pytest.mark.asyncio
@pytest.mark.parametrize("missing", [False, True])
async def test_issue1370_temporal_failed_or_missing_clock_keeps_other_domains(missing: bool) -> None:
    class _BrokenClock:
        def get_uptime_seconds(self) -> float | None:
            raise RuntimeError("private-clock-payload")

    runtime = SimpleNamespace() if missing else _BrokenClock()
    snapshot = await IntrospectiveTelemetryService(runtime=runtime).get_full_snapshot("subject")
    assert set(snapshot) == {"memory", "trust", "cognitive", "temporal", "social"}
    assert "system_uptime_hours" not in snapshot["temporal"]
    assert snapshot["temporal"]["uptime_measurement"]["status"] == ("unavailable" if missing else "failed")
    rendered = IntrospectiveTelemetryService.render_telemetry_context(snapshot)
    assert "Uptime: unknown" in rendered
    assert "Memory: unknown episodes" in rendered
    assert "private-clock-payload" not in rendered


@pytest.mark.parametrize("start", [None, True, "1", -1.0, float("nan"), float("inf")])
def test_issue1370_runtime_uptime_invalid_start_is_unknown(start: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    from probos.runtime import ProbOSRuntime
    runtime = object.__new__(ProbOSRuntime)
    assert runtime.get_uptime_seconds() is None
    monkeypatch.setattr(runtime, "_start_time", start, raising=False)
    assert runtime.get_uptime_seconds() is None


@pytest.mark.parametrize("now", [100.0, 3700.0, None, True, "100", 99.0, float("nan"), float("inf")])
def test_issue1370_runtime_uptime_monotonic_boundary(now: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    from probos import runtime as runtime_module
    runtime = object.__new__(runtime_module.ProbOSRuntime)
    monkeypatch.setattr(runtime, "_start_time", 100.0, raising=False)
    monkeypatch.setattr(runtime_module.time, "monotonic", lambda: now)
    expected = now - 100.0 if type(now) is float and now in (100.0, 3700.0) else None
    assert runtime.get_uptime_seconds() == expected


def test_issue1370_runtime_uptime_clock_exception_is_unknown(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    from probos import runtime as runtime_module
    runtime = object.__new__(runtime_module.ProbOSRuntime)
    monkeypatch.setattr(runtime, "_start_time", 100.0, raising=False)

    def fail_clock() -> float:
        raise RuntimeError("private-clock-payload")

    monkeypatch.setattr(runtime_module.time, "monotonic", fail_clock)
    assert runtime.get_uptime_seconds() is None
    assert "uptime is unavailable" in caplog.text
    assert "private-clock-payload" not in caplog.text


@dataclass
class _FakeTrustRecord:
    agent_id: str
    alpha: float = 7.0
    beta: float = 3.0

    @property
    def score(self) -> float:
        return self.alpha / (self.alpha + self.beta)

    @property
    def observations(self) -> float:
        return (self.alpha - 2.0) + (self.beta - 2.0)

    @property
    def uncertainty(self) -> float:
        import math
        n = self.alpha + self.beta
        if n <= 0:
            return 1.0
        return math.sqrt((self.alpha * self.beta) / (n * n * (n + 1)))


@dataclass
class _FakeTrustEvent:
    timestamp: float
    agent_id: str
    success: bool
    old_score: float
    new_score: float
    weight: float = 1.0
    intent_type: str = "test_intent"
    episode_id: str = "ep-1"
    verifier_id: str = "v-1"


def _make_agent(
    agent_id: str = "agent-1",
    zone: str | None = None,
    birth_ts: float | None = None,
    last_active: datetime | None = None,
) -> MagicMock:
    agent = MagicMock()
    agent.id = agent_id
    agent.sovereign_id = agent_id
    agent._birth_timestamp = birth_ts or time.time() - 3600
    agent.meta.last_active = last_active or datetime.now(timezone.utc)

    # Working memory with optional zone
    wm = MagicMock()
    wm.get_cognitive_zone.return_value = zone
    agent._working_memory = wm
    return agent


# ── Test Class 1: IntrospectiveTelemetryService ──────────────────


class TestIntrospectiveTelemetryService:
    """Tests for the telemetry service's data-gathering methods."""

    @pytest.mark.asyncio
    async def test_get_memory_state_with_episodes(self):
        em = _Issue1370Memory(count=47)
        rt = _make_runtime(episodic_memory=em)
        svc = IntrospectiveTelemetryService(runtime=rt)

        result = await svc.get_memory_state("agent-1")
        assert result["episode_count"] == 47
        assert result["retrieval"] == "cosine_similarity"
        assert result["capacity"] == "unbounded"
        assert result["offline_processing"] is False

    @pytest.mark.asyncio
    async def test_get_memory_state_no_episodic(self):
        rt = _make_runtime(episodic_memory=None)
        svc = IntrospectiveTelemetryService(runtime=rt)

        result = await svc.get_memory_state("agent-1")
        assert "episode_count" not in result
        assert result["retrieval"] == "cosine_similarity"

    @pytest.mark.asyncio
    async def test_get_trust_state_with_record(self):
        tn = MagicMock()
        tn.get_score.return_value = 0.72
        tn.get_record.return_value = _FakeTrustRecord("agent-1", alpha=7.0, beta=3.0)
        tn.get_events_for_agent.return_value = []
        rt = _make_runtime(trust_network=tn)
        svc = IntrospectiveTelemetryService(runtime=rt)

        result = await svc.get_trust_state("agent-1")
        assert result["score"] == 0.72
        assert result["observations"] == 6  # (7-2) + (3-2)
        assert "uncertainty" in result
        assert result["model"] == "bayesian_beta"

    @pytest.mark.asyncio
    async def test_get_trust_state_no_record(self):
        tn = MagicMock()
        tn.get_score.return_value = 0.5
        tn.get_record.return_value = None
        tn.get_events_for_agent.return_value = []
        rt = _make_runtime(trust_network=tn)
        svc = IntrospectiveTelemetryService(runtime=rt)

        result = await svc.get_trust_state("agent-1")
        assert result["score"] == 0.5
        assert "observations" not in result

    @pytest.mark.asyncio
    async def test_get_trust_state_trend_rising(self):
        events = [
            _FakeTrustEvent(time.time() - 100, "agent-1", True, 0.50, 0.55),
            _FakeTrustEvent(time.time() - 80, "agent-1", True, 0.55, 0.60),
            _FakeTrustEvent(time.time() - 60, "agent-1", True, 0.60, 0.65),
            _FakeTrustEvent(time.time() - 40, "agent-1", True, 0.65, 0.70),
            _FakeTrustEvent(time.time() - 20, "agent-1", True, 0.70, 0.75),
        ]
        tn = MagicMock()
        tn.get_score.return_value = 0.75
        tn.get_record.return_value = None
        tn.get_events_for_agent.return_value = events
        rt = _make_runtime(trust_network=tn)
        svc = IntrospectiveTelemetryService(runtime=rt)

        result = await svc.get_trust_state("agent-1")
        assert result["trend"] == "rising"

    @pytest.mark.asyncio
    async def test_get_trust_state_trend_falling(self):
        events = [
            _FakeTrustEvent(time.time() - 100, "agent-1", False, 0.75, 0.70),
            _FakeTrustEvent(time.time() - 80, "agent-1", False, 0.70, 0.65),
            _FakeTrustEvent(time.time() - 60, "agent-1", False, 0.65, 0.60),
            _FakeTrustEvent(time.time() - 40, "agent-1", False, 0.60, 0.55),
            _FakeTrustEvent(time.time() - 20, "agent-1", False, 0.55, 0.50),
        ]
        tn = MagicMock()
        tn.get_score.return_value = 0.50
        tn.get_record.return_value = None
        tn.get_events_for_agent.return_value = events
        rt = _make_runtime(trust_network=tn)
        svc = IntrospectiveTelemetryService(runtime=rt)

        result = await svc.get_trust_state("agent-1")
        assert result["trend"] == "falling"

    @pytest.mark.asyncio
    async def test_get_trust_state_trend_stable(self):
        events = [
            _FakeTrustEvent(time.time() - 40, "agent-1", True, 0.70, 0.71),
            _FakeTrustEvent(time.time() - 20, "agent-1", True, 0.71, 0.71),
        ]
        tn = MagicMock()
        tn.get_score.return_value = 0.71
        tn.get_record.return_value = None
        tn.get_events_for_agent.return_value = events
        rt = _make_runtime(trust_network=tn)
        svc = IntrospectiveTelemetryService(runtime=rt)

        result = await svc.get_trust_state("agent-1")
        assert result["trend"] == "stable"

    @pytest.mark.asyncio
    async def test_get_cognitive_state_zone(self):
        agent = _make_agent(zone="amber")
        reg = MagicMock()
        reg.get.return_value = agent
        rt = _make_runtime(registry=reg)
        svc = IntrospectiveTelemetryService(runtime=rt)

        result = await svc.get_cognitive_state("agent-1")
        assert result["zone"] == "amber"
        assert result["regulation_model"] == "graduated_zones"

    @pytest.mark.asyncio
    async def test_get_temporal_state(self):
        now = time.time()
        agent = _make_agent(birth_ts=now - 7200)  # 2 hours ago
        reg = MagicMock()
        reg.get.return_value = agent
        rt = _make_runtime(registry=reg, uptime_seconds=10800.0)
        svc = IntrospectiveTelemetryService(runtime=rt)

        result = await svc.get_temporal_state("agent-1")
        assert result["system_uptime_hours"] == pytest.approx(3.0, abs=0.2)
        assert result["agent_age_hours"] == pytest.approx(2.0, abs=0.2)
        assert "last_action_minutes" in result

    @pytest.mark.asyncio
    async def test_get_social_state_hebbian(self):
        hr = MagicMock()
        hr.all_weights_typed.return_value = {
            ("analyze_logs", "agent-1", "routing"): 0.8,
            ("diagnose", "agent-1", "routing"): 0.6,
            ("other_intent", "agent-2", "routing"): 0.9,
        }
        tn = MagicMock()
        tn.get_events_for_agent.return_value = [
            _FakeTrustEvent(time.time(), "agent-1", True, 0.5, 0.6, intent_type="analyze"),
            _FakeTrustEvent(time.time(), "agent-1", True, 0.6, 0.7, intent_type="build"),
        ]
        rt = _make_runtime(hebbian_router=hr, trust_network=tn)
        svc = IntrospectiveTelemetryService(runtime=rt)

        result = await svc.get_social_state("agent-1")
        assert "routing_affinities" in result
        assert len(result["routing_affinities"]) == 2  # 2 match agent-1
        assert result["interaction_breadth"] == 2  # 2 unique intents

    @pytest.mark.asyncio
    async def test_get_full_snapshot_all_domains(self):
        em = _Issue1370Memory(count=10)
        tn = MagicMock()
        tn.get_score.return_value = 0.6
        tn.get_record.return_value = None
        tn.get_events_for_agent.return_value = []
        agent = _make_agent(zone="green")
        reg = MagicMock()
        reg.get.return_value = agent
        rt = _make_runtime(episodic_memory=em, trust_network=tn, registry=reg)
        svc = IntrospectiveTelemetryService(runtime=rt)

        snap = await svc.get_full_snapshot("agent-1")
        assert "memory" in snap
        assert "trust" in snap
        assert "cognitive" in snap
        assert "temporal" in snap
        assert "social" in snap

    @pytest.mark.asyncio
    async def test_get_full_snapshot_partial_failure(self):
        """One domain throws, others still return."""
        em = _Issue1370Memory(failure=RuntimeError("DB error"))
        tn = MagicMock()
        tn.get_score.return_value = 0.5
        tn.get_record.return_value = None
        tn.get_events_for_agent.return_value = []
        rt = _make_runtime(episodic_memory=em, trust_network=tn)
        svc = IntrospectiveTelemetryService(runtime=rt)

        snap = await svc.get_full_snapshot("agent-1")
        # Memory should still have static fields despite count failure
        assert snap["memory"]["episode_count"] == "unknown"
        # Trust should be fine
        assert snap["trust"]["score"] == 0.5


# ── Test Class 2: Self-Query Detection ──────────────────────────


class TestSelfQueryDetection:
    """Tests for _is_introspective_query pattern matching."""

    def _detect(self, text: str) -> bool:
        from probos.cognitive.cognitive_agent import CognitiveAgent
        return CognitiveAgent._is_introspective_query(text)

    def test_detects_memory_query(self):
        assert self._detect("What are your memories like?")

    def test_detects_trust_query(self):
        assert self._detect("How's your trust score?")

    def test_detects_state_query(self):
        assert self._detect("How are you doing?")

    def test_detects_architecture_query(self):
        assert self._detect("How does your brain work?")

    def test_detects_stasis_query(self):
        assert self._detect("What happened during stasis?")

    def test_detects_identity_query(self):
        assert self._detect("Tell me about yourself")

    def test_ignores_non_introspective(self):
        assert not self._detect("What's the weather like?")

    def test_ignores_third_person(self):
        assert not self._detect("Is the captain's budget good?")

    def test_empty_string(self):
        assert not self._detect("")

    def test_none_returns_false(self):
        assert not self._detect(None)  # type: ignore[arg-type]


# ── Test Class 3: Telemetry Injection ────────────────────────────


def _make_cognitive_agent(**kwargs):
    """Create a minimal CognitiveAgent for injection tests."""
    from probos.cognitive.cognitive_agent import CognitiveAgent

    agent = CognitiveAgent.__new__(CognitiveAgent)
    agent.id = kwargs.get("agent_id", "test-agent")
    agent.agent_type = "cognitive"
    agent.sovereign_id = agent.id
    agent.callsign = kwargs.get("callsign", "TestAgent")
    agent._runtime = kwargs.get("runtime", None)
    agent._working_memory = kwargs.get("working_memory", None)
    agent._build_temporal_context = lambda: ""
    agent._format_memory_section = lambda *a, **kw: []
    agent._build_active_game_context = lambda: ""
    agent._orientation_rendered = ""
    agent._build_crew_complement = lambda: ""
    agent._recent_post_count = None
    agent.meta = MagicMock()
    agent.meta.last_active = None
    agent._birth_timestamp = None
    agent._system_start_time = None
    agent._strategy_advisor = None
    # AD-722: this helper bypasses __init__ (CognitiveAgent.__new__), so it must
    # mirror the attrs __init__ sets that _build_user_message now reads. The
    # avatar self-observation injection reads self._last_self_avatar_snap
    # (initialized to None in __init__); without it the read raises
    # AttributeError and the whole message assembly degrades to "".
    agent._last_self_avatar_snap = None
    return agent


class TestTelemetryInjection:
    """Tests for telemetry injection into DM/WR/proactive paths."""

    @pytest.mark.asyncio
    async def test_dm_introspective_gets_telemetry(self):
        svc = MagicMock()
        svc.get_full_snapshot = AsyncMock(return_value={
            "memory": {"episode_count": 47, "retrieval": "cosine_similarity"},
            "trust": {"score": 0.72},
        })
        svc.render_telemetry_context.return_value = "--- Your Telemetry ---\nMemory: 47 episodes"

        rt = MagicMock()
        # BF-287: a real config so _resolve_attention_budget() returns the
        # unbounded budget. With a bare MagicMock, rt.config.memory.attention
        # is truthy and token_budget is a MagicMock -> int(MagicMock)=1 -> the
        # ContextAssembler evicts every bid and _build_user_message renders "".
        rt.config = SystemConfig()
        rt._introspective_telemetry = svc
        agent = _make_cognitive_agent(runtime=rt)

        obs = {
            "intent": "direct_message",
            "params": {"text": "What are your memories like?"},
        }
        result = await agent._build_user_message(obs)
        assert "Your Telemetry" in result
        assert "47 episodes" in result

    @pytest.mark.asyncio
    async def test_dm_non_introspective_no_telemetry(self):
        svc = MagicMock()
        svc.get_full_snapshot = AsyncMock()

        rt = MagicMock()
        rt._introspective_telemetry = svc
        agent = _make_cognitive_agent(runtime=rt)

        obs = {
            "intent": "direct_message",
            "params": {"text": "Run diagnostics on the warp core"},
        }
        result = await agent._build_user_message(obs)
        assert "Your Telemetry" not in result
        svc.get_full_snapshot.assert_not_called()

    @pytest.mark.asyncio
    async def test_wr_introspective_gets_telemetry(self):
        svc = MagicMock()
        svc.get_full_snapshot = AsyncMock(return_value={
            "trust": {"score": 0.8},
        })
        svc.render_telemetry_context.return_value = "--- Your Telemetry ---\nTrust: 0.8"

        rt = MagicMock()
        # BF-287: real config so _resolve_attention_budget() is unbounded (see
        # the DM test above) instead of int(MagicMock)=1 evicting every bid.
        rt.config = SystemConfig()
        rt._introspective_telemetry = svc
        rt.is_cold_start = False
        agent = _make_cognitive_agent(runtime=rt)

        obs = {
            "intent": "ward_room_notification",
            "params": {
                "channel_name": "bridge",
                "author_callsign": "Captain",
                "title": "Trust discussion",
                "text": "How's your trust score?",
            },
            "context": "",
        }
        result = await agent._build_user_message(obs)
        assert "Your Telemetry" in result

    @pytest.mark.asyncio
    async def test_proactive_gets_telemetry_snapshot(self):
        agent = _make_cognitive_agent()
        obs = {
            "intent": "proactive_think",
            "params": {
                "context_parts": {
                    "introspective_telemetry": "--- Your Telemetry ---\nMemory: 10 episodes",
                },
            },
        }
        result = await agent._build_user_message(obs)
        assert "Your Telemetry" in result

    @pytest.mark.asyncio
    async def test_telemetry_injection_failure_graceful(self):
        svc = MagicMock()
        svc.get_full_snapshot = AsyncMock(side_effect=RuntimeError("boom"))

        rt = MagicMock()
        rt._introspective_telemetry = svc
        agent = _make_cognitive_agent(runtime=rt)

        obs = {
            "intent": "direct_message",
            "params": {"text": "Tell me about yourself"},
        }
        # Should not raise
        result = await agent._build_user_message(obs)
        assert isinstance(result, str)

    @pytest.mark.asyncio
    async def test_no_telemetry_service_no_crash(self):
        rt = MagicMock()
        rt._introspective_telemetry = None
        agent = _make_cognitive_agent(runtime=rt)

        obs = {
            "intent": "direct_message",
            "params": {"text": "What are your memories?"},
        }
        result = await agent._build_user_message(obs)
        assert isinstance(result, str)

    @pytest.mark.asyncio
    async def test_cognitive_zone_in_dm_amber(self):
        from probos.cognitive.agent_working_memory import AgentWorkingMemory
        wm = AgentWorkingMemory()
        wm.update_cognitive_state(zone="amber")

        agent = _make_cognitive_agent(working_memory=wm)

        obs = {
            "intent": "direct_message",
            "params": {"text": "Status report"},
        }
        result = await agent._build_user_message(obs)
        assert "<cognitive_zone>AMBER</cognitive_zone>" in result

    @pytest.mark.asyncio
    async def test_cognitive_zone_green_not_shown(self):
        from probos.cognitive.agent_working_memory import AgentWorkingMemory
        wm = AgentWorkingMemory()
        wm.update_cognitive_state(zone="green")

        agent = _make_cognitive_agent(working_memory=wm)

        obs = {
            "intent": "direct_message",
            "params": {"text": "Status report"},
        }
        result = await agent._build_user_message(obs)
        assert "<cognitive_zone>" not in result


# ── Test Class 4: Render Telemetry Context ───────────────────────


class TestRenderTelemetryContext:
    """Tests for the render_telemetry_context static method."""

    def test_renders_full_snapshot(self):
        snap = {
            "memory": {"episode_count": 47, "retrieval": "cosine_similarity", "offline_processing": False},
            "trust": {"score": 0.72, "observations": 23, "uncertainty": 0.08, "trend": "stable"},
            "cognitive": {"zone": "green"},
            "temporal": {"system_uptime_hours": 2.3, "agent_age_hours": 2.3, "last_action_minutes": 4.1},
            "social": {},
        }
        result = IntrospectiveTelemetryService.render_telemetry_context(snap)
        assert "47 episodes" in result
        assert "0.72" in result
        assert "23 observations" in result
        assert "GREEN" in result
        assert "2.3h" in result

    def test_renders_populated_social(self) -> None:
        snap = {
            "temporal": {"system_uptime_hours": 2.3},
            "social": {
                "routing_affinities": [
                    {"intent": "analyze_logs", "weight": 0.8},
                    {"intent": "diagnose", "weight": 0.6},
                ],
                "interaction_breadth": 2,
            },
        }
        result = IntrospectiveTelemetryService.render_telemetry_context(snap)
        assert (
            "Collaboration: routing affinities: analyze_logs (0.8), "
            "diagnose (0.6) | interaction breadth: 2"
        ) in result
        assert result.index("Uptime: 2.3h") < result.index("Collaboration:")
        assert result.index("Collaboration:") < result.index("When discussing yourself")

    def test_renders_partial_snapshot(self):
        snap = {
            "memory": {"episode_count": 5},
            "trust": {},
        }
        result = IntrospectiveTelemetryService.render_telemetry_context(snap)
        assert "5 episodes" in result
        assert "no record yet" in result

    def test_renders_empty_snapshot(self):
        result = IntrospectiveTelemetryService.render_telemetry_context({})
        assert result == ""

    def test_grounding_instructions_present(self):
        snap = {
            "memory": {"episode_count": 1},
            "trust": {"score": 0.5},
            "cognitive": {},
            "temporal": {},
            "social": {},
        }
        result = IntrospectiveTelemetryService.render_telemetry_context(snap)
        assert "ground self-referential claims" in result
        assert "cite these numbers" in result


# ── Test Class 5: AgentWorkingMemory.get_cognitive_zone ──────────


class TestGetCognitiveZone:
    """Tests for the new get_cognitive_zone() accessor."""

    def test_returns_zone_when_set(self):
        from probos.cognitive.agent_working_memory import AgentWorkingMemory
        wm = AgentWorkingMemory()
        wm.update_cognitive_state(zone="amber")
        assert wm.get_cognitive_zone() == "amber"

    def test_returns_none_when_not_set(self):
        from probos.cognitive.agent_working_memory import AgentWorkingMemory
        wm = AgentWorkingMemory()
        assert wm.get_cognitive_zone() is None

    def test_returns_updated_zone(self):
        from probos.cognitive.agent_working_memory import AgentWorkingMemory
        wm = AgentWorkingMemory()
        wm.update_cognitive_state(zone="green")
        assert wm.get_cognitive_zone() == "green"
        wm.update_cognitive_state(zone="red")
        assert wm.get_cognitive_zone() == "red"
