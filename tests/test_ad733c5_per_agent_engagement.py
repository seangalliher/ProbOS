"""AD-733c-5 — Per-agent perception engagement.

Tests cover:
- ``PerceptionProfile`` defaults + roundtrip + backward compat
- ``PerceptionEngagementRegistry`` register / get / current_modes
- Per-agent controller independence (transitions stay scoped)
- ``select_primary_controller`` back-compat pointer
- Real ``PerceptionModeController`` with ``agent_id`` kwarg

Uses real Pydantic + real CrewProfile + real PerceptionModeController
per BF-287 (no MagicMock at substrate boundary).
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from probos.crew_profile import CrewProfile, PerceptionProfile
from probos.perception.engagement_registry import (
    PerceptionEngagementRegistry,
    select_primary_controller,
)
from probos.perception.mode_controller import (
    Mode,
    PerceptionModeController,
)


# ── Test 1: PerceptionProfile defaults ─────────────────────────


def test_perception_profile_default_values() -> None:
    p = PerceptionProfile()
    assert p.engagement_enabled is True
    assert p.initial_mode == "ambient"
    assert p.camera_device_id == ""


# ── Test 2: CrewProfile roundtrip preserves perception ─────────


def test_crew_profile_roundtrip_with_perception() -> None:
    profile = CrewProfile(agent_id="e1", callsign="Counselor")
    profile.perception = PerceptionProfile(
        engagement_enabled=False,
        initial_mode="dormant",
        camera_device_id="cam-42",
    )
    data = profile.to_dict()
    assert "perception" in data
    assert data["perception"]["camera_device_id"] == "cam-42"
    reloaded = CrewProfile.from_dict(data)
    assert reloaded.perception.engagement_enabled is False
    assert reloaded.perception.initial_mode == "dormant"
    assert reloaded.perception.camera_device_id == "cam-42"


# ── Test 3: legacy JSON without perception block backward compat ──


def test_crew_profile_legacy_json_backcompat() -> None:
    legacy = {
        "agent_id": "old1",
        "callsign": "Legacy",
    }
    profile = CrewProfile.from_dict(legacy)
    # Default PerceptionProfile when block absent.
    assert profile.perception is not None
    assert profile.perception.engagement_enabled is True
    assert profile.perception.initial_mode == "ambient"
    assert profile.perception.camera_device_id == ""


# ── Test 4: engagement registry register/get contract ──────────


class _FakeRuntime:
    def __init__(self) -> None:
        # Minimal shape — controllers don't actually touch the runtime
        # outside of `note_*` methods which read mode/timestamps internally.
        pass


def _make_controller(agent_id: str = "") -> PerceptionModeController:
    return PerceptionModeController(
        _FakeRuntime(),
        initial_mode=Mode.AMBIENT,
        idle_tick_seconds=0.001,
        agent_id=agent_id,
    )


def test_engagement_registry_register_get() -> None:
    runtime = _FakeRuntime()
    reg = PerceptionEngagementRegistry(runtime)  # type: ignore[arg-type]
    ctrl = _make_controller("e1")
    reg.register("e1", ctrl)
    assert reg.get("e1") is ctrl
    assert reg.get("nonexistent") is None
    assert "e1" in reg
    assert len(reg) == 1


# ── Test 5: per-agent controllers transition independently ─────


def test_per_agent_controllers_independent_transitions() -> None:
    runtime = _FakeRuntime()
    reg = PerceptionEngagementRegistry(runtime)  # type: ignore[arg-type]
    ezri = _make_controller("e1")
    atlas = _make_controller("a1")
    reg.register("e1", ezri)
    reg.register("a1", atlas)

    # Engage only Ezri.
    ezri.transition_to(Mode.ENGAGED, trigger="manual")
    modes = reg.current_modes()
    assert modes["e1"] == "engaged"
    assert modes["a1"] == "ambient"


# ── Test 6: select_primary_controller prefers Counselor ────────


def test_select_primary_prefers_counselor() -> None:
    runtime = _FakeRuntime()
    reg = PerceptionEngagementRegistry(runtime)  # type: ignore[arg-type]
    ezri = _make_controller("e1")
    atlas = _make_controller("a1")
    reg.register("a1", atlas)  # register Atlas first
    reg.register("e1", ezri)
    primary = select_primary_controller(reg)
    assert primary is ezri  # Counselor (e1) preference wins ordering.


# ── Test 7: select_primary_controller falls back to first ──────


def test_select_primary_no_counselor_falls_back() -> None:
    runtime = _FakeRuntime()
    reg = PerceptionEngagementRegistry(runtime)  # type: ignore[arg-type]
    atlas = _make_controller("a1")
    reg.register("a1", atlas)
    primary = select_primary_controller(reg)
    assert primary is atlas


# ── Test 8: empty registry → primary is None ───────────────────


def test_select_primary_empty_registry() -> None:
    runtime = _FakeRuntime()
    reg = PerceptionEngagementRegistry(runtime)  # type: ignore[arg-type]
    assert select_primary_controller(reg) is None


# ── Test 9: agent_id kwarg defaults to empty (back-compat) ─────


def test_controller_agent_id_default_empty() -> None:
    ctrl = PerceptionModeController(_FakeRuntime(), idle_tick_seconds=0.001)
    assert ctrl.agent_id == ""


# ── Test 10: agent_id kwarg threaded through ───────────────────


def test_controller_agent_id_kwarg_preserved() -> None:
    ctrl = _make_controller("worf")
    assert ctrl.agent_id == "worf"


# ── Test 11: registry rejects empty agent_id ───────────────────


def test_engagement_registry_rejects_empty_agent_id(
    caplog: Any,
) -> None:
    runtime = _FakeRuntime()
    reg = PerceptionEngagementRegistry(runtime)  # type: ignore[arg-type]
    ctrl = _make_controller("")
    reg.register("", ctrl)
    assert len(reg) == 0
