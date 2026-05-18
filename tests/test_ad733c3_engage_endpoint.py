"""AD-733c-3 (Wave 172): wake-word -> engage endpoint tests.

4 tests covering the POST /api/perception/engage flow:
1. Flips ambient -> engaged + transitioned=True.
2. 5s cooldown returns transitioned=False, reason='cooldown'.
3. Already-engaged refresh returns transitioned=False, reason='refreshed'.
4. Invalid source returns 400.

BF-287: real PerceptionModeController with real PerceptualHashStrategy
fakes wrapped in _FakeConsumer; no MagicMock at the substrate boundary.
"""
from __future__ import annotations

from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from probos.perception.mode_controller import (
    Mode,
    PerceptionModeController,
)
from probos.perception.supervisor import (
    PerceptualHashStrategy,
    VisionSupervisor,
)
from probos.routers.auth import require_crew_scope
from probos.routers.deps import get_runtime
from probos.routers.perception import router


class _FakeConsumer:
    def __init__(self) -> None:
        self._supervisor = VisionSupervisor(
            strategy=PerceptualHashStrategy(
                min_interval_seconds=5.0,
                novelty_threshold=0.15,
                baseline_max_age_seconds=30.0,
            ),
        )


class _FakeRuntime:
    def __init__(self, controller: PerceptionModeController) -> None:
        self.vision_consumer = controller._runtime.vision_consumer  # type: ignore[attr-defined]
        self.perception_mode_controller = controller


def _make_app(initial_mode: Mode = Mode.AMBIENT) -> tuple[FastAPI, PerceptionModeController]:
    inner_runtime = type("R", (), {"vision_consumer": _FakeConsumer()})()
    controller = PerceptionModeController(inner_runtime, initial_mode=initial_mode)
    runtime = _FakeRuntime(controller)
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_runtime] = lambda: runtime
    app.dependency_overrides[require_crew_scope] = lambda: True
    return app, controller


def test_engage_endpoint_flips_to_engaged() -> None:
    app, controller = _make_app(initial_mode=Mode.AMBIENT)
    with TestClient(app) as client:
        resp = client.post(
            "/api/perception/engage",
            json={"agent": "ezri", "phrase": "Hello Ezri", "source": "wake_word"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["mode"] == "engaged"
        assert body["transitioned"] is True
        assert body["reason"] == "transitioned"
    assert controller.current_mode is Mode.ENGAGED


def test_engage_endpoint_cooldown_returns_no_transition() -> None:
    app, controller = _make_app(initial_mode=Mode.AMBIENT)
    with TestClient(app) as client:
        r1 = client.post(
            "/api/perception/engage",
            json={"agent": "ezri", "source": "wake_word"},
        )
        assert r1.json()["transitioned"] is True
        # Second POST within 5s -> cooldown.
        r2 = client.post(
            "/api/perception/engage",
            json={"agent": "ezri", "source": "wake_word"},
        )
        assert r2.status_code == 200
        body = r2.json()
        assert body["transitioned"] is False
        assert body["reason"] == "cooldown"


def test_engage_endpoint_already_engaged_refreshes() -> None:
    app, controller = _make_app(initial_mode=Mode.ENGAGED)
    before = controller.last_dm_activity_at
    with TestClient(app) as client:
        resp = client.post(
            "/api/perception/engage",
            json={"agent": "ezri", "source": "wake_word"},
        )
        assert resp.status_code == 200
        body = resp.json()
        # Cooldown is 5s but _last_wake_word_at starts at 0 -> first call
        # passes the cooldown gate; reason should be "refreshed" since we
        # were already engaged.
        assert body["transitioned"] is False
        assert body["reason"] == "refreshed"
        assert body["mode"] == "engaged"
    assert controller.last_dm_activity_at > before


def test_engage_endpoint_invalid_source() -> None:
    app, _controller = _make_app(initial_mode=Mode.AMBIENT)
    with TestClient(app) as client:
        resp = client.post(
            "/api/perception/engage",
            json={"agent": "ezri", "source": "bogus"},
        )
        assert resp.status_code == 400
        assert resp.json()["error"] == "invalid_source"
