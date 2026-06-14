"""AD-1006: capability clarity — "serves" vs ship-wide "can request".

The ``GET /api/agent/{id}/capabilities`` mesh axis now tags which intents THIS
agent SERVES (its own ``intent_descriptors`` — its specialty) vs the ship-wide
reachable surface every agent can request. This resolves the "83 identical
capabilities on every crew card" confusion: the list is the ship's surface, not
the agent's role.

BF-287: the real async route handler + real ``SimpleNamespace`` registry/agents
at the substrate boundary — no MagicMock (a phantom ``.all()``/``.get()`` would
pass against a mock but mis-resolve in production).
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from probos.routers.agents import get_agent_capabilities


def _intent(name: str) -> SimpleNamespace:
    return SimpleNamespace(
        name=name,
        description=f"{name} description",
        usage_hint="",
        requires_consensus=False,
        tier="domain",
    )


class _Registry:
    """Minimal real registry: .get(id) for the viewed agent, .all() for the
    ship-wide mesh walk (BF-287 — not a MagicMock)."""

    def __init__(self, agents: list[SimpleNamespace]) -> None:
        self._agents = {a.id: a for a in agents}

    def get(self, agent_id: str) -> SimpleNamespace | None:
        return self._agents.get(agent_id)

    def all(self) -> list[SimpleNamespace]:
        return list(self._agents.values())


def _runtime(agents: list[SimpleNamespace]) -> SimpleNamespace:
    # No tool_permission_store / cognitive_skill_catalog wired -> the tool + skill
    # blocks honest-degrade to [], isolating the AD-1006 mesh-served behavior.
    return SimpleNamespace(registry=_Registry(agents))


@pytest.mark.asyncio
async def test_serves_tags_only_this_agents_own_intents():
    counselor = SimpleNamespace(
        id="ezri",
        intent_descriptors=[_intent("counselor_wellness_report"), _intent("counselor_assess")],
    )
    engineer = SimpleNamespace(id="laforge", intent_descriptors=[_intent("engineering_analyze")])
    body = await get_agent_capabilities("ezri", _runtime([counselor, engineer]))

    mesh = {mi["id"]: mi for mi in body["mesh_intents"]}
    # Ship-wide surface = deduped union of ALL agents' intents (unchanged).
    assert set(mesh) == {"counselor_wellness_report", "counselor_assess", "engineering_analyze"}
    # Ezri SERVES her two specialty intents; she does NOT serve the engineer's.
    assert mesh["counselor_wellness_report"]["served"] is True
    assert mesh["counselor_assess"]["served"] is True
    assert mesh["engineering_analyze"]["served"] is False


@pytest.mark.asyncio
async def test_served_flag_is_per_viewed_agent():
    counselor = SimpleNamespace(id="ezri", intent_descriptors=[_intent("counselor_wellness_report")])
    engineer = SimpleNamespace(id="laforge", intent_descriptors=[_intent("engineering_analyze")])
    runtime = _runtime([counselor, engineer])

    # Same ship-wide list, but the served flags flip to match the agent viewed.
    eng = {mi["id"]: mi for mi in (await get_agent_capabilities("laforge", runtime))["mesh_intents"]}
    assert eng["engineering_analyze"]["served"] is True
    assert eng["counselor_wellness_report"]["served"] is False


@pytest.mark.asyncio
async def test_agent_serving_nothing_has_all_can_request():
    yeo = SimpleNamespace(id="yeo", intent_descriptors=[])
    counselor = SimpleNamespace(id="ezri", intent_descriptors=[_intent("counselor_assess")])
    body = await get_agent_capabilities("yeo", _runtime([yeo, counselor]))

    # Yeo declares no intents -> every ship-wide intent is can-request only for him.
    assert body["mesh_intents"]  # the ship-wide surface is non-empty
    assert all(mi["served"] is False for mi in body["mesh_intents"])
    # No perm store / catalog wired -> honest-degrade to empty tool + skill axes.
    assert body["tools"] == []
    assert body["skills"] == []


@pytest.mark.asyncio
async def test_unknown_agent_404():
    with pytest.raises(HTTPException) as exc:
        await get_agent_capabilities("ghost", _runtime([]))
    assert exc.value.status_code == 404
