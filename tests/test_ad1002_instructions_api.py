"""AD-1002: GET /api/agent/{id}/instructions — Instructions + Model read surface.

The Instructions (Standing Orders) + Model axes of the Service Configuration hub.
BF-287: a REAL `CognitiveConfig` at the config boundary (a MagicMock would make
`getattr(cog, "llm_model_*")` truthy and corrupt the available-tiers list).
"""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from probos.config import AuthConfig, CognitiveConfig


class _Agent:
    """A real-ish agent object (not a mock): identity instructions + tier resolver."""

    def __init__(self, agent_type="diagnostician", instructions="You are the ship's diagnostician.", tier="deep"):
        self.id = "med-1"
        self.agent_type = agent_type
        self.instructions = instructions
        self._tier = tier

    def _resolve_tier(self) -> str:
        return self._tier


def _client(agent: Any = None):
    from probos.api import create_app

    agent = agent if agent is not None else _Agent()
    runtime = MagicMock()
    runtime.registry.get = MagicMock(return_value=agent)
    cfg = MagicMock()
    cfg.cognitive = CognitiveConfig()   # REAL config — gating the available-tiers list
    cfg.auth = AuthConfig()
    runtime.config = cfg
    return TestClient(create_app(runtime)), runtime


def test_instructions_identity_present():
    client, _ = _client()
    resp = client.get("/api/agent/med-1/instructions")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["agent_type"] == "diagnostician"
    assert body["instructions"]["present"] is True
    assert body["instructions"]["char_count"] > 0
    assert "diagnostician" in body["instructions"]["preview"]


def test_standing_order_tiers_four_tier_shape():
    client, _ = _client()
    resp = client.get("/api/agent/med-1/instructions")
    body = resp.json()
    tiers = body["standing_order_tiers"]
    # The composer's four-tier shape (federation/ship/department/agent), char
    # counts only (text not dumped).
    names = [t["tier"] for t in tiers]
    assert names == ["federation", "ship", "department", "agent"]
    for t in tiers:
        assert "char_count" in t and "present" in t and "source_file" in t
        assert "text" not in t  # never dump the system prompt
    # diagnostician resolves to the medical department.
    assert body["department"] == "medical"


def test_model_resolved_and_available_tiers():
    client, _ = _client(_Agent(tier="deep"))
    body = client.get("/api/agent/med-1/instructions").json()
    model = body["model"]
    assert model["resolved_tier"] == "deep"
    # CognitiveConfig defaults: fast/standard/deep have models, vision is None.
    assert "fast" in model["available_tiers"]
    assert "standard" in model["available_tiers"]
    assert "deep" in model["available_tiers"]
    assert "vision" not in model["available_tiers"]
    assert "Settings" in model["note"]


def test_agent_without_resolve_tier_defaults_standard():
    plain = SimpleNamespace(id="x", agent_type="file_reader", instructions="")
    client, _ = _client(plain)
    body = client.get("/api/agent/x/instructions").json()
    assert body["model"]["resolved_tier"] == "standard"
    assert body["instructions"]["present"] is False


def test_unknown_agent_404():
    client, runtime = _client()
    runtime.registry.get = MagicMock(return_value=None)
    resp = client.get("/api/agent/ghost/instructions")
    assert resp.status_code == 404
