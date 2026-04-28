"""AD-565: Quality-informed routing tests."""

from __future__ import annotations

import pytest

from probos.config import QualityRouterConfig
from probos.knowledge.quality_router import QualityRouter


class _FakeEmitter:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict]] = []

    def __call__(self, event_type: str, data: dict) -> None:
        self.events.append((event_type, data))


class _FakeAgentQuality:
    def __init__(self, callsign: str, quality_score: float) -> None:
        self.callsign = callsign
        self.quality_score = quality_score


class _FakeSnapshot:
    def __init__(self, per_agent: list[_FakeAgentQuality]) -> None:
        self.per_agent = per_agent


def test_quality_weight_calculation() -> None:
    router = QualityRouter(QualityRouterConfig())

    router.update_quality("low", 0.0)
    router.update_quality("mid", 0.5)
    router.update_quality("high", 1.0)

    assert router.get_quality_weight("low") == pytest.approx(0.5)
    assert router.get_quality_weight("mid") == pytest.approx(1.0)
    assert router.get_quality_weight("high") == pytest.approx(1.5)


def test_update_quality() -> None:
    router = QualityRouter(QualityRouterConfig())

    router.update_quality("Chapel", 0.7)
    diagnostic = router.get_diagnostic("Chapel")

    assert diagnostic["quality_score"] == 0.7
    assert diagnostic["last_updated"] is not None


def test_get_diagnostic() -> None:
    router = QualityRouter(QualityRouterConfig())
    router.update_quality("Chapel", 0.2)

    diagnostic = router.get_diagnostic("Chapel")

    assert diagnostic["agent_id"] == "Chapel"
    assert diagnostic["quality_score"] == 0.2
    assert diagnostic["weight"] == pytest.approx(0.7)
    assert diagnostic["concern"] is True


def test_min_max_weight_bounds() -> None:
    router = QualityRouter(QualityRouterConfig())

    router.update_quality("below", -1.0)
    router.update_quality("above", 2.0)

    assert router.get_quality_weight("below") == pytest.approx(0.5)
    assert router.get_quality_weight("above") == pytest.approx(1.5)


def test_unknown_agent_default_weight() -> None:
    router = QualityRouter(QualityRouterConfig())

    assert router.get_quality_weight("unknown") == 1.0


def test_quality_concern_event() -> None:
    emitter = _FakeEmitter()
    router = QualityRouter(QualityRouterConfig(), emit_event_fn=emitter)

    router.update_quality("Chapel", 0.2)

    assert len(emitter.events) == 1
    event_type, data = emitter.events[0]
    assert event_type == "quality_concern"
    assert data == {
        "agent_id": "Chapel",
        "quality_score": 0.2,
        "weight": pytest.approx(0.7),
    }


def test_no_concern_above_threshold() -> None:
    emitter = _FakeEmitter()
    router = QualityRouter(QualityRouterConfig(), emit_event_fn=emitter)

    router.update_quality("Chapel", 0.3)

    assert emitter.events == []


def test_dream_update_flow() -> None:
    router = QualityRouter(QualityRouterConfig())
    snapshot = _FakeSnapshot([
        _FakeAgentQuality("Chapel", 0.2),
        _FakeAgentQuality("Dax", 0.8),
    ])

    for agent_quality in snapshot.per_agent:
        router.update_quality(agent_quality.callsign, agent_quality.quality_score)

    assert router.get_all_weights() == {
        "Chapel": pytest.approx(0.7),
        "Dax": pytest.approx(1.3),
    }


def test_config_disabled() -> None:
    emitter = _FakeEmitter()
    router = QualityRouter(QualityRouterConfig(enabled=False), emit_event_fn=emitter)

    router.update_quality("Chapel", 0.0)

    assert router.get_quality_weight("Chapel") == 1.0
    assert router.get_diagnostic("Chapel")["quality_score"] is None
    assert emitter.events == []


def test_get_all_weights() -> None:
    router = QualityRouter(QualityRouterConfig())
    router.update_quality("Chapel", 0.25)
    router.update_quality("Dax", 0.75)

    weights = router.get_all_weights()

    assert weights == {
        "Chapel": pytest.approx(0.75),
        "Dax": pytest.approx(1.25),
    }