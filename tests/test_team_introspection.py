"""Tests for AD-293: Crew Team Introspection."""

from __future__ import annotations

from dataclasses import field
from unittest.mock import MagicMock

import pytest

from probos.agents.introspect import IntrospectionAgent
from probos.runtime import ProbOSRuntime
from probos.substrate.agent import BaseAgent
from probos.substrate.pool import ResourcePool
from probos.substrate.pool_group import PoolGroup, PoolGroupRegistry
from probos.types import IntentMessage


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


def _make_agent(agent_type: str, agent_id: str, pool: str):
    """Create a mock agent with .info() and .id."""
    agent = MagicMock(spec=BaseAgent)
    agent.id = agent_id
    agent.agent_type = agent_type
    agent.pool = pool
    agent.state = MagicMock()
    agent.state.value = "active"
    agent.confidence = 0.8
    agent.info.return_value = {
        "id": agent_id,
        "type": agent_type,
        "pool": pool,
        "state": "active",
        "confidence": 0.8,
    }
    return agent


def _make_pool(agent_ids, agent_type: str = "unknown"):
    """Create a mock pool holding the given agent IDs (matching real ResourcePool)."""
    pool = MagicMock(spec=ResourcePool)
    pool.healthy_agents = agent_ids
    pool.target_size = len(agent_ids)
    pool.info.return_value = {
        "current_size": len(agent_ids),
        "target_size": len(agent_ids),
        "agent_type": agent_type,
    }
    return pool


def _build_runtime():
    """Build a mock runtime with pool groups and pools matching the real runtime."""
    rt = MagicMock(spec=ProbOSRuntime)

    # Agents
    med_vitals = _make_agent("vitals_monitor", "med-vm-0", "medical_vitals")
    med_diag = _make_agent("diagnostician", "med-d-0", "medical_diagnostician")
    med_surg = _make_agent("surgeon", "med-s-0", "medical_surgeon")
    med_pharm = _make_agent("pharmacist", "med-p-0", "medical_pharmacist")
    med_path = _make_agent("pathologist", "med-pa-0", "medical_pathologist")
    fs_reader = _make_agent("file_reader", "fs-0", "filesystem")
    shell_agent = _make_agent("shell_command", "sh-0", "shell")

    all_agents = [med_vitals, med_diag, med_surg, med_pharm, med_path, fs_reader, shell_agent]

    # Registry — resolve agent IDs to agent objects
    rt.registry = MagicMock()
    rt.registry.all.return_value = all_agents
    agent_by_id = {a.id: a for a in all_agents}
    rt.registry.get.side_effect = lambda aid: agent_by_id.get(aid)
    rt.registry.count = len(all_agents)

    # Trust
    rt.trust_network = MagicMock()
    rt.trust_network.get_score.return_value = 0.5
    rt.trust_network.all_scores.return_value = {a.id: 0.5 for a in all_agents}

    # Hebbian
    rt.hebbian_router = MagicMock()
    rt.hebbian_router.all_weights_typed.return_value = {}
    rt.hebbian_router.weight_count = 0

    # Pools — healthy_agents returns IDs (matching real ResourcePool)
    rt.pools = {
        "medical_vitals": _make_pool([med_vitals.id], "vitals_monitor"),
        "medical_diagnostician": _make_pool([med_diag.id], "diagnostician"),
        "medical_surgeon": _make_pool([med_surg.id], "surgeon"),
        "medical_pharmacist": _make_pool([med_pharm.id], "pharmacist"),
        "medical_pathologist": _make_pool([med_path.id], "pathologist"),
        "filesystem": _make_pool([fs_reader.id], "file_reader"),
        "shell": _make_pool([shell_agent.id], "shell_command"),
    }

    # Pool groups
    registry = PoolGroupRegistry()
    registry.register(PoolGroup(
        name="medical",
        display_name="Medical",
        pool_names={"medical_vitals", "medical_diagnostician", "medical_surgeon",
                    "medical_pharmacist", "medical_pathologist"},
        exclude_from_scaler=True,
    ))
    registry.register(PoolGroup(
        name="core",
        display_name="Core Systems",
        pool_names={"filesystem", "shell"},
    ))
    rt.pool_groups = registry

    # Other runtime attrs
    rt.attention = MagicMock()
    rt.attention.queue_size = 0
    rt.workflow_cache = MagicMock()
    rt.workflow_cache.size = 0
    rt.workflow_cache.entries = []
    rt.dream_scheduler = None
    rt._previous_execution = None
    rt.episodic_memory = None

    return rt


async def _run_team_info(rt, team: str = "") -> dict:
    """Helper to invoke team_info through IntrospectionAgent."""
    agent = IntrospectionAgent(agent_id="intro-0")
    agent._runtime = rt
    msg = IntentMessage(intent="team_info", params={"team": team})
    result = await agent.handle_intent(msg)
    assert result is not None
    return result.result


async def _run_agent_info(rt, agent_type: str) -> dict:
    """Helper to invoke agent_info through IntrospectionAgent."""
    agent = IntrospectionAgent(agent_id="intro-0")
    agent._runtime = rt
    msg = IntentMessage(intent="agent_info", params={"agent_type": agent_type})
    result = await agent.handle_intent(msg)
    assert result is not None
    return result.result


# ------------------------------------------------------------------
# Tests
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_team_info_specific_team():
    """team_info(team='medical') returns team details, health, and agent roster."""
    rt = _build_runtime()
    data = await _run_team_info(rt, team="medical")

    assert data["team"]["name"] == "medical"
    assert data["team"]["display_name"] == "Medical"
    assert data["team"]["exclude_from_scaler"] is True
    assert data["health"]["total_agents"] == 5
    assert data["health"]["healthy_agents"] == 5
    assert data["health"]["health_ratio"] == 1.0
    assert len(data["agents"]) == 5
    # Each agent should have trust_score and pool
    for agent in data["agents"]:
        assert "trust_score" in agent
        assert "pool" in agent


@pytest.mark.asyncio
async def test_team_info_all_teams():
    """team_info with no team param lists all registered teams."""
    rt = _build_runtime()
    data = await _run_team_info(rt, team="")

    assert data["count"] == 2
    names = {t["name"] for t in data["teams"]}
    assert names == {"medical", "core"}
    for team in data["teams"]:
        assert "display_name" in team
        assert "total_agents" in team
        assert "health_ratio" in team


@pytest.mark.asyncio
async def test_team_info_unknown_team():
    """team_info for nonexistent team returns helpful error with available names."""
    rt = _build_runtime()
    data = await _run_team_info(rt, team="nonexistent")

    assert "No crew team found" in data["message"]
    assert "available_teams" in data
    assert "medical" in data["available_teams"]
    assert "core" in data["available_teams"]


@pytest.mark.asyncio
async def test_team_info_fuzzy_match():
    """team_info with partial name 'med' finds the medical team."""
    rt = _build_runtime()
    data = await _run_team_info(rt, team="med")

    assert data["team"]["name"] == "medical"
    assert len(data["agents"]) == 5


@pytest.mark.asyncio
async def test_agent_info_pool_name_fallback():
    """agent_info with 'medical' finds agents via pool name fallback."""
    rt = _build_runtime()
    data = await _run_agent_info(rt, agent_type="medical")

    # No agent has agent_type="medical", but pools named medical_* match
    assert "agents" in data
    assert len(data["agents"]) >= 1
    pool_names = {a.get("pool") for a in data["agents"]}
    assert any("medical" in p for p in pool_names)


@pytest.mark.asyncio
async def test_team_info_core_team():
    """team_info(team='core') returns core system agents."""
    rt = _build_runtime()
    data = await _run_team_info(rt, team="core")

    assert data["team"]["name"] == "core"
    assert data["team"]["display_name"] == "Core Systems"
    assert data["health"]["total_agents"] == 2
    agent_types = {a["type"] for a in data["agents"]}
    assert "file_reader" in agent_types
    assert "shell_command" in agent_types
