"""AD-720d-2.1: Captain vision-capability approval flow — boundary tests."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from probos.avatars import vision_proposal_history
from probos.avatars.vision_proposal_history import VisionProposalEntry
from probos.config import AuthConfig


# ── Fakes ───────────────────────────────────────────────────────


def _make_runtime(
    *,
    agent_present: bool = True,
    initial_vision_capable: bool = False,
) -> MagicMock:
    """Build a minimal runtime that supports the AD-720d-2.1 endpoints.

    Uses a real ``CallsignRegistry`` with a stub ``AgentRegistry`` so
    ``set_vision_capable`` exercises the full resolution path.
    """
    from probos.crew_profile import CallsignRegistry

    runtime = MagicMock()
    agent = MagicMock()
    agent.id = "agent-007"
    agent.agent_type = "counselor"
    agent.is_alive = True

    runtime.registry = MagicMock()
    runtime.registry.get.return_value = agent if agent_present else None
    runtime.registry.all.return_value = [agent] if agent_present else []
    runtime.registry.get_by_pool.return_value = [agent] if agent_present else []

    callsign_registry = CallsignRegistry()
    callsign_registry._type_to_profile["counselor"] = {
        "display_name": "Counselor",
        "department": "bridge",
        "vision_capable": initial_vision_capable,
    }
    callsign_registry._type_to_callsign["counselor"] = "Troi"
    callsign_registry._callsign_to_type["troi"] = "counselor"
    callsign_registry.bind_registry(runtime.registry)
    runtime.callsign_registry = callsign_registry

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
    cfg.avatars.max_vrm_size_bytes = 25 * 1024 * 1024
    cfg.avatars.max_proposal_iterations = 3
    cfg.auth = AuthConfig()  # AD-722b-1a: empty token = auth-disabled.
    runtime.config = cfg
    return runtime


@pytest.fixture(autouse=True)
def _reset_vision_history(tmp_path: Path):
    """Reset module-level vision proposal history between tests."""
    vision_proposal_history.configure(tmp_path / "vph.json")
    vision_proposal_history.reset_all()
    yield
    vision_proposal_history.reset_all()
    vision_proposal_history.configure(None)


@pytest.fixture
def client() -> TestClient:
    from probos.api import create_app
    return TestClient(create_app(_make_runtime()))


# ── Tests ──────────────────────────────────────────────────────────────


def test_propose_creates_entry(client: TestClient) -> None:
    resp = client.post(
        "/api/agent/agent-007/vision-capability/propose",
        json={"rationale": "Captain is sending images in DMs."},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["agent_id"] == "agent-007"
    assert body["rationale"] == "Captain is sending images in DMs."
    assert body["proposal_id"]
    entries = vision_proposal_history.list_for_agent("agent-007")
    assert len(entries) == 1


def test_approve_flips_registry() -> None:
    runtime = _make_runtime(initial_vision_capable=False)
    from probos.api import create_app
    client = TestClient(create_app(runtime))
    resp = client.post(
        "/api/agent/agent-007/vision-capability/propose",
        json={"rationale": "Need vision to triage incident screenshots."},
    )
    proposal_id = resp.json()["proposal_id"]

    resp2 = client.post(
        f"/api/agent/agent-007/vision-capability/approve?proposal_id={proposal_id}",
        json={"approve": True, "reason": "Approved by Captain."},
    )
    assert resp2.status_code == 200, resp2.text
    profile = runtime.callsign_registry.get_profile("counselor")
    assert profile["vision_capable"] is True


def test_deny_leaves_registry() -> None:
    runtime = _make_runtime(initial_vision_capable=False)
    from probos.api import create_app
    client = TestClient(create_app(runtime))
    resp = client.post(
        "/api/agent/agent-007/vision-capability/propose",
        json={"rationale": "Speculative request."},
    )
    proposal_id = resp.json()["proposal_id"]

    resp2 = client.post(
        f"/api/agent/agent-007/vision-capability/approve?proposal_id={proposal_id}",
        json={"approve": False, "reason": "Not needed right now."},
    )
    assert resp2.status_code == 200
    profile = runtime.callsign_registry.get_profile("counselor")
    assert profile["vision_capable"] is False


def test_approve_unknown_proposal_404(client: TestClient) -> None:
    resp = client.post(
        "/api/agent/agent-007/vision-capability/approve?proposal_id=does-not-exist",
        json={"approve": True, "reason": ""},
    )
    assert resp.status_code == 404


def test_approve_already_resolved_404(client: TestClient) -> None:
    resp = client.post(
        "/api/agent/agent-007/vision-capability/propose",
        json={"rationale": "x"},
    )
    proposal_id = resp.json()["proposal_id"]
    first = client.post(
        f"/api/agent/agent-007/vision-capability/approve?proposal_id={proposal_id}",
        json={"approve": True, "reason": ""},
    )
    assert first.status_code == 200
    second = client.post(
        f"/api/agent/agent-007/vision-capability/approve?proposal_id={proposal_id}",
        json={"approve": True, "reason": "again"},
    )
    assert second.status_code == 404


def test_history_persists_across_configure(tmp_path: Path) -> None:
    path = tmp_path / "vph.json"
    vision_proposal_history.configure(path)
    vision_proposal_history.reset_all()
    vision_proposal_history.append(
        VisionProposalEntry(
            proposal_id="p1",
            agent_id="agent-007",
            rationale="persist me",
            proposed_at=1.0,
        )
    )
    # Re-configure with the same path; entries reload from disk.
    vision_proposal_history.configure(None)
    vision_proposal_history.configure(path)
    entries = vision_proposal_history.list_for_agent("agent-007")
    assert len(entries) == 1
    assert entries[0].rationale == "persist me"


def test_rationale_length_validation(client: TestClient) -> None:
    too_long = "x" * 281
    resp = client.post(
        "/api/agent/agent-007/vision-capability/propose",
        json={"rationale": too_long},
    )
    assert resp.status_code == 422


def test_history_endpoint_lists_entries(client: TestClient) -> None:
    client.post(
        "/api/agent/agent-007/vision-capability/propose",
        json={"rationale": "first request"},
    )
    resp = client.get("/api/agent/agent-007/vision-capability/history")
    assert resp.status_code == 200
    body = resp.json()
    assert body["agent_id"] == "agent-007"
    assert len(body["entries"]) == 1
    assert body["entries"][0]["rationale"] == "first request"
