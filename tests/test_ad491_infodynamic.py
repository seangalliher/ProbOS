"""AD-491: Tests for Infodynamic Telemetry."""

from __future__ import annotations

import time
from typing import Any
from unittest.mock import MagicMock

import pytest

from probos.cognitive.infodynamic import (
    EntropySignal,
    InfodynamicProbe,
    InfodynamicReport,
    _shannon_entropy,
)
from probos.config import InfodynamicConfig
from probos.events import EventType


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class _FakeAgent:
    def __init__(self, agent_id: str, state_value: str = "active") -> None:
        self.id = agent_id
        # Mimic AgentState enum: object with `.value` attribute
        self.state = type("S", (), {"value": state_value})()


class _FakeRegistry:
    def __init__(self, agents: list[_FakeAgent]) -> None:
        self._agents = agents

    def all(self) -> list[_FakeAgent]:
        return list(self._agents)


class _FakeTrustNetwork:
    def __init__(self, scores: dict[str, float]) -> None:
        self._scores = scores

    def get_score(self, agent_id: str) -> float:
        return self._scores.get(agent_id, 0.5)


class _FakeEventLog:
    def __init__(self, events: list[dict[str, Any]]) -> None:
        self._events = events

    async def query(self, limit: int = 100) -> list[dict[str, Any]]:
        return list(self._events[:limit])


class _FakeRuntime:
    def __init__(
        self,
        *,
        event_log: Any = None,
        trust_network: Any = None,
        registry: Any = None,
    ) -> None:
        self.event_log = event_log
        self.trust_network = trust_network
        self.registry = registry


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_event_type_infodynamic_report_exists() -> None:
    assert EventType.INFODYNAMIC_REPORT.value == "infodynamic_report"


def test_infodynamic_config_defaults() -> None:
    cfg = InfodynamicConfig()
    assert cfg.enabled is True
    assert cfg.event_window_seconds == 3600.0
    assert cfg.trust_buckets == 10


def test_shannon_entropy_uniform_distribution() -> None:
    # Two equal buckets: entropy = 1.0 bit
    assert _shannon_entropy([10, 10]) == pytest.approx(1.0)


def test_shannon_entropy_zero_for_empty() -> None:
    assert _shannon_entropy([]) == 0.0
    assert _shannon_entropy([0, 0, 0]) == 0.0


def test_shannon_entropy_zero_for_single_bucket() -> None:
    assert _shannon_entropy([10]) == 0.0
    assert _shannon_entropy([0, 5, 0]) == 0.0


@pytest.mark.asyncio
async def test_analyze_no_runtime_returns_empty_signals() -> None:
    probe = InfodynamicProbe(runtime=None)
    report = await probe.analyze()
    assert isinstance(report, InfodynamicReport)
    assert len(report.signals) == 3
    for s in report.signals:
        assert s.entropy == 0.0
        assert s.sample_size == 0
    assert report.total_entropy_bits == 0.0


@pytest.mark.asyncio
async def test_analyze_event_log_entropy_uses_query() -> None:
    now = time.time()
    events = [
        {"category": "intent", "timestamp": now - 60},
        {"category": "intent", "timestamp": now - 60},
        {"category": "audit", "timestamp": now - 30},
        {"category": "audit", "timestamp": now - 30},
    ]
    runtime = _FakeRuntime(event_log=_FakeEventLog(events))
    probe = InfodynamicProbe(runtime=runtime, event_window_seconds=3600.0)
    report = await probe.analyze()
    event_signal = next(s for s in report.signals if s.name == "event_log_category")
    # Two equally-weighted categories → 1.0 bits
    assert event_signal.entropy == pytest.approx(1.0)
    assert event_signal.sample_size == 4
    assert event_signal.bucket_count == 2


@pytest.mark.asyncio
async def test_analyze_trust_distribution_buckets() -> None:
    agents = [_FakeAgent(f"a{i}") for i in range(4)]
    trust = _FakeTrustNetwork({
        "a0": 0.1,
        "a1": 0.4,
        "a2": 0.7,
        "a3": 0.95,
    })
    runtime = _FakeRuntime(
        trust_network=trust,
        registry=_FakeRegistry(agents),
    )
    probe = InfodynamicProbe(runtime=runtime, trust_buckets=10)
    report = await probe.analyze()
    trust_signal = next(s for s in report.signals if s.name == "trust_score_distribution")
    assert trust_signal.entropy > 0.0
    assert trust_signal.sample_size == 4
    assert trust_signal.bucket_count == 4  # 4 distinct buckets occupied


@pytest.mark.asyncio
async def test_analyze_emits_event() -> None:
    emit = MagicMock()
    runtime = _FakeRuntime(registry=_FakeRegistry([_FakeAgent("a0")]))
    probe = InfodynamicProbe(runtime=runtime, emit_event=emit)
    await probe.analyze()
    assert emit.call_count == 1
    args = emit.call_args.args
    assert args[0] == EventType.INFODYNAMIC_REPORT
    payload = args[1]
    assert "generated_at" in payload
    assert "total_entropy_bits" in payload
    assert isinstance(payload["signals"], list)
    assert len(payload["signals"]) == 3
    for entry in payload["signals"]:
        assert "name" in entry
        assert "entropy" in entry
        assert "sample_size" in entry
        assert "bucket_count" in entry


def test_endpoint_returns_404_when_disabled() -> None:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from probos.routers.infodynamic import router

    app = FastAPI()
    app.include_router(router)

    class _RuntimeNoProbe:
        pass

    app.state.runtime = _RuntimeNoProbe()
    client = TestClient(app)
    resp = client.get("/api/infodynamic")
    assert resp.status_code == 404
