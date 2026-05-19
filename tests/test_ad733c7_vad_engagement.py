"""AD-733c-7 — Silero VAD secondary engagement trigger.

Tests cover:
- ``note_voice_activity`` step-wise ramp + cooldown + refreshed/blocked
- ``VOICE_ACTIVITY_COOLDOWN_S`` floor
- ``PerceptionConfig.vad_engagement_enabled`` default-off
- ``POST /api/perception/voice-activity`` endpoint: 503 when disabled,
  routes per-agent when registry wired, 404 on unknown agent.

Real ``PerceptionConfig`` + real ``PerceptionModeController`` +
``FastAPI TestClient`` (BF-287 — no MagicMock at substrate boundary).
"""

from __future__ import annotations

import time
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from probos.config import SystemConfig
from probos.perception.engagement_registry import PerceptionEngagementRegistry
from probos.perception.mode_controller import (
    Mode,
    PerceptionModeController,
)
from probos.routers import perception as perception_router


class _FakeRuntime:
    def __init__(self, vad_enabled: bool = True) -> None:
        self.config = SystemConfig()
        self.config.perception.vad_engagement_enabled = vad_enabled
        self.perception_mode_controller: Any = None
        self.perception_engagement_registry: Any = None
        self.callsign_registry: Any = None


def _make_controller(initial: Mode = Mode.AMBIENT, agent_id: str = "") -> PerceptionModeController:
    return PerceptionModeController(
        _FakeRuntime(),
        initial_mode=initial,
        idle_tick_seconds=0.001,
        agent_id=agent_id,
    )


# ── Test 1: DORMANT → AMBIENT (step-wise ramp) ─────────────────


def test_note_voice_activity_dormant_to_ambient() -> None:
    ctrl = _make_controller(initial=Mode.DORMANT)
    transitioned, reason = ctrl.note_voice_activity()
    assert transitioned is True
    assert reason == "transitioned"
    assert ctrl.current_mode is Mode.AMBIENT


# ── Test 2: AMBIENT → ENGAGED after cooldown clears ────────────


def test_note_voice_activity_ambient_to_engaged() -> None:
    ctrl = _make_controller(initial=Mode.AMBIENT)
    # First call: AMBIENT → ENGAGED.
    transitioned, reason = ctrl.note_voice_activity()
    assert transitioned is True
    assert reason == "transitioned"
    assert ctrl.current_mode is Mode.ENGAGED


# ── Test 3: ENGAGED refreshes (no transition) ──────────────────


def test_note_voice_activity_engaged_refreshes() -> None:
    ctrl = _make_controller(initial=Mode.ENGAGED)
    # Need to bypass cooldown by setting _last_voice_activity_at far in the past
    ctrl._last_voice_activity_at = 0.0
    transitioned, reason = ctrl.note_voice_activity()
    assert transitioned is False
    assert reason == "refreshed"
    assert ctrl.current_mode is Mode.ENGAGED


# ── Test 4: cooldown blocks within 3s ──────────────────────────


def test_note_voice_activity_cooldown_blocks() -> None:
    ctrl = _make_controller(initial=Mode.DORMANT)
    first = ctrl.note_voice_activity()
    assert first == (True, "transitioned")
    # Immediate second call → cooldown.
    second = ctrl.note_voice_activity()
    assert second == (False, "cooldown")


# ── Test 5: endpoint returns 503 when VAD disabled ─────────────


def _make_app(runtime: _FakeRuntime) -> TestClient:
    app = FastAPI()
    app.include_router(perception_router.router)

    def _get_runtime() -> Any:
        return runtime

    app.dependency_overrides[perception_router.get_runtime] = _get_runtime
    # Bypass crew-scope auth in tests.
    app.dependency_overrides[perception_router.require_crew_scope] = lambda: None
    return TestClient(app)


def test_voice_activity_endpoint_disabled_returns_503() -> None:
    runtime = _FakeRuntime(vad_enabled=False)
    runtime.perception_mode_controller = _make_controller()
    client = _make_app(runtime)
    resp = client.post(
        "/api/perception/voice-activity",
        json={"source": "vad"},
    )
    assert resp.status_code == 503
    assert resp.json()["error"] == "vad_engagement_disabled"


# ── Test 6: endpoint routes per-agent through registry ─────────


def test_voice_activity_endpoint_routes_per_agent() -> None:
    runtime = _FakeRuntime(vad_enabled=True)
    ezri = _make_controller(initial=Mode.DORMANT, agent_id="e1")
    atlas = _make_controller(initial=Mode.DORMANT, agent_id="a1")
    runtime.perception_mode_controller = ezri  # back-compat singleton
    reg = PerceptionEngagementRegistry(runtime)  # type: ignore[arg-type]
    reg.register("e1", ezri)
    reg.register("a1", atlas)
    runtime.perception_engagement_registry = reg

    client = _make_app(runtime)
    resp = client.post(
        "/api/perception/voice-activity",
        json={"agent": "e1", "source": "vad"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["transitioned"] is True
    assert body["agent_id"] == "e1"
    # Only Ezri transitioned.
    assert ezri.current_mode is Mode.AMBIENT
    assert atlas.current_mode is Mode.DORMANT


# ── Test 7: endpoint 404s on unknown agent ─────────────────────


def test_voice_activity_endpoint_unknown_agent_404() -> None:
    runtime = _FakeRuntime(vad_enabled=True)
    runtime.perception_mode_controller = _make_controller()
    reg = PerceptionEngagementRegistry(runtime)  # type: ignore[arg-type]
    runtime.perception_engagement_registry = reg

    client = _make_app(runtime)
    resp = client.post(
        "/api/perception/voice-activity",
        json={"agent": "nonexistent", "source": "vad"},
    )
    assert resp.status_code == 404
    assert resp.json()["error"] == "unknown_agent"


# ── Test 8: endpoint rejects invalid source ────────────────────


def test_voice_activity_endpoint_invalid_source_400() -> None:
    runtime = _FakeRuntime(vad_enabled=True)
    runtime.perception_mode_controller = _make_controller()
    client = _make_app(runtime)
    resp = client.post(
        "/api/perception/voice-activity",
        json={"source": "telepathy"},
    )
    assert resp.status_code == 400
    assert resp.json()["error"] == "invalid_source"


# ── Test 9 (bonus): config defaults preserve behavior ──────────


def test_perception_config_vad_defaults() -> None:
    cfg = SystemConfig()
    assert cfg.perception.vad_engagement_enabled is False
    assert cfg.perception.vad_min_speech_duration_ms == 400


# ── Test 10 (bonus): VOICE_ACTIVITY_COOLDOWN_S sits between others ──


def test_voice_activity_cooldown_constant_between_programmatic_and_wake() -> None:
    # AD-733c-7: between PROGRAMMATIC (1s) and WAKE_WORD (5s).
    assert (
        PerceptionModeController.PROGRAMMATIC_COOLDOWN_S
        < PerceptionModeController.VOICE_ACTIVITY_COOLDOWN_S
        < PerceptionModeController.WAKE_WORD_COOLDOWN_S
    )
