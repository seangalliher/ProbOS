"""AD-982a: persistent Captain-set vision-capability overrides — boundary tests.

The Captain wanted to turn on PERMANENT ambient vision from the UI. The
AD-720d-2.1 approve path only flips the in-memory registry (lost on restart), so
AD-982a adds a data-dir override sidecar (keyed by agent_type, matching the gate)
re-applied at boot, plus a direct Captain grant/revoke endpoint
(``POST /api/agent/{id}/vision-capability/set``).

Layers tested:
  * ``vision_overrides`` sidecar (set/get/all/apply/persist-survives-reload),
  * ``CallsignRegistry.set_vision_capable_by_type``,
  * the ``/vision-capability/set`` endpoint (flips live AND persists),
  * ``/profile`` + ``/roster`` surface ``vision_capable``.

Real ``CallsignRegistry`` + real sidecar on tmp_path (NOT MagicMock for those).
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from probos.config import AuthConfig
from probos.crew_profile import CallsignRegistry
from probos.perception import vision_overrides


# ============================ 1. override sidecar (pure) ============================


@pytest.fixture(autouse=True)
def _reset_overrides(tmp_path: Path):
    vision_overrides.configure(tmp_path / "vision_overrides.json")
    vision_overrides.reset_all()
    yield
    vision_overrides.reset_all()
    vision_overrides.configure(None)


def test_set_and_get_override():
    assert vision_overrides.get_override("yeoman") is None  # no override yet
    vision_overrides.set_override("yeoman", True)
    assert vision_overrides.get_override("yeoman") is True
    vision_overrides.set_override("yeoman", False)
    assert vision_overrides.get_override("yeoman") is False


def test_empty_agent_type_ignored():
    vision_overrides.set_override("", True)
    assert vision_overrides.all_overrides() == {}


def test_all_overrides_is_a_copy():
    vision_overrides.set_override("yeoman", True)
    snap = vision_overrides.all_overrides()
    snap["yeoman"] = False
    assert vision_overrides.get_override("yeoman") is True  # store unaffected


def test_persistence_survives_reload(tmp_path: Path):
    path = tmp_path / "vov.json"
    vision_overrides.configure(path)
    vision_overrides.reset_all()
    vision_overrides.set_override("yeoman", True)
    vision_overrides.set_override("scout", False)
    # Simulate a restart: drop in-memory state, re-bind the same file.
    vision_overrides.configure(None)
    vision_overrides.configure(path)
    assert vision_overrides.get_override("yeoman") is True
    assert vision_overrides.get_override("scout") is False


def test_malformed_file_starts_empty(tmp_path: Path):
    path = tmp_path / "bad.json"
    path.write_text("not json{", encoding="utf-8")
    vision_overrides.configure(path)
    assert vision_overrides.all_overrides() == {}


# ===================== 2. set_vision_capable_by_type (registry) =====================


def _registry_with(agent_type: str, vision: bool) -> CallsignRegistry:
    reg = CallsignRegistry()
    reg._type_to_profile[agent_type] = {
        "display_name": agent_type.title(),
        "department": "ops",
        "vision_capable": vision,
    }
    return reg


def test_set_by_type_flips_existing():
    reg = _registry_with("yeoman", False)
    assert reg.set_vision_capable_by_type("yeoman", True) is True
    assert reg._type_to_profile["yeoman"]["vision_capable"] is True


def test_set_by_type_unknown_type_returns_false():
    reg = _registry_with("yeoman", False)
    assert reg.set_vision_capable_by_type("nobody", True) is False


def test_apply_overrides_onto_registry():
    reg = _registry_with("yeoman", False)
    vision_overrides.set_override("yeoman", True)
    applied = vision_overrides.apply(reg)
    assert applied == 1
    assert reg._type_to_profile["yeoman"]["vision_capable"] is True


def test_apply_skips_unknown_type():
    reg = _registry_with("yeoman", False)
    vision_overrides.set_override("ghost", True)  # not in registry
    assert vision_overrides.apply(reg) == 0


# ===================== 3. the /vision-capability/set endpoint =====================


def _make_runtime(*, initial_vision_capable: bool = False) -> MagicMock:
    runtime = MagicMock()
    agent = MagicMock()
    agent.id = "yeo-1"
    agent.agent_type = "yeoman"
    agent.is_alive = True
    runtime.registry = MagicMock()
    runtime.registry.get.return_value = agent
    runtime.registry.all.return_value = [agent]

    reg = CallsignRegistry()
    reg._type_to_profile["yeoman"] = {
        "display_name": "Yeoman", "department": "ops",
        "vision_capable": initial_vision_capable,
    }
    reg._type_to_callsign["yeoman"] = "Yeo"
    reg._callsign_to_type["yeo"] = "yeoman"
    reg.bind_registry(runtime.registry)
    runtime.callsign_registry = reg

    runtime.intent_bus = MagicMock()
    runtime.intent_bus.send = AsyncMock(return_value=None)
    runtime._start_time = 0.0
    runtime.episodic_memory = None
    runtime.work_item_store = None
    runtime.proactive_loop = None
    runtime.ontology = None
    runtime.add_event_listener = MagicMock()
    runtime.hebbian_router = MagicMock()
    runtime.hebbian_router.all_weights_typed.return_value = {}
    runtime.trust_network = MagicMock()
    runtime.trust_network.get_score.return_value = 0.5
    runtime.trust_network.get_history.return_value = []
    runtime.emit_event = MagicMock()
    cfg = MagicMock()
    cfg.avatars = MagicMock()
    cfg.avatars.enabled = True
    cfg.avatars.avatars_dir = "data/avatars"
    cfg.auth = AuthConfig()
    runtime.config = cfg
    return runtime


def test_set_endpoint_grants_and_persists():
    runtime = _make_runtime(initial_vision_capable=False)
    from probos.api import create_app
    client = TestClient(create_app(runtime))
    resp = client.post(
        "/api/agent/yeo-1/vision-capability/set",
        json={"enabled": True, "reason": "Captain grant for meetings."},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["vision_capable"] is True
    assert body["persisted"] is True
    # live registry flipped
    assert runtime.callsign_registry._type_to_profile["yeoman"]["vision_capable"] is True
    # persisted override recorded (by agent_type)
    assert vision_overrides.get_override("yeoman") is True


def test_set_endpoint_revokes():
    runtime = _make_runtime(initial_vision_capable=True)
    from probos.api import create_app
    client = TestClient(create_app(runtime))
    resp = client.post(
        "/api/agent/yeo-1/vision-capability/set",
        json={"enabled": False, "reason": "no longer needed"},
    )
    assert resp.status_code == 200, resp.text
    assert runtime.callsign_registry._type_to_profile["yeoman"]["vision_capable"] is False
    assert vision_overrides.get_override("yeoman") is False


def test_set_endpoint_unknown_agent_404():
    runtime = _make_runtime()
    runtime.registry.get.return_value = None
    from probos.api import create_app
    client = TestClient(create_app(runtime))
    resp = client.post(
        "/api/agent/ghost/vision-capability/set",
        json={"enabled": True},
    )
    assert resp.status_code == 404


def test_profile_surfaces_vision_capable():
    runtime = _make_runtime(initial_vision_capable=True)
    from probos.api import create_app
    client = TestClient(create_app(runtime))
    resp = client.get("/api/agent/yeo-1/profile")
    assert resp.status_code == 200, resp.text
    assert resp.json()["visionCapable"] is True
