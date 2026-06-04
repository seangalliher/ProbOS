"""AD-865: tests for :class:`CrewDelegator`.

BF-287 (HARD): ``CrewDelegator`` reads ``.agent_type``/``.id`` off registered
agents, walks the real chain of command, and reads ``authority_over``/
``department_id`` off real :class:`Post`\\ s, then issues orders through a real
:class:`OrderManager` (which owns ``authority_over`` validation). A MagicMock
would auto-create every one of those attributes and pass even if the production
code read a phantom name. So these tests use a **real**
:class:`AgentRegistry` (concrete ``BaseAgent`` subclass instances), a **real**
:class:`VesselOntologyService` loaded from the shipped ``config/ontology``, and
a **real** :class:`OrderManager`.

Real org-chart facts these tests rely on (``config/ontology/organization.yaml``):

- agent_type ``engineering_officer`` fills post ``chief_engineer``
  (department ``engineering``, ``authority_over=[engineering_officer,
  builder_officer]``).
- agent_type ``builder`` fills post ``builder_officer`` (department
  ``engineering``, leaf — ``authority_over=[]``).
- agent_type ``security_officer`` fills post ``chief_security`` (department
  ``security``, ``authority_over=[]`` — a chief with no subordinates).
- agent_type ``scout`` fills post ``scout_officer`` (department ``science``,
  ``authority_over=[]``).
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

import pytest

from probos.cognitive.crew_assignment import AssignmentDecision
from probos.cognitive.crew_delegation import CrewDelegator, DelegationDecision
from probos.cognitive.orders import OrderManager
from probos.ontology import VesselOntologyService
from probos.substrate.agent import BaseAgent
from probos.substrate.registry import AgentRegistry


# ------------------------------------------------------------------ real agent

class _CrewAgent(BaseAgent):
    """Concrete BaseAgent so the registry holds a real ``.id``/``.agent_type``."""

    async def perceive(self, intent: dict[str, Any]) -> Any:
        return None

    async def decide(self, observation: Any) -> Any:
        return None

    async def act(self, plan: Any) -> Any:
        return None

    async def report(self, result: Any) -> dict[str, Any]:
        return {}


# ------------------------------------------------------------------ fixtures

@pytest.fixture
def ontology_dir(tmp_path: Path) -> Path:
    src = Path(__file__).resolve().parents[1] / "config" / "ontology"
    dst = tmp_path / "ontology"
    shutil.copytree(src, dst)
    return dst


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    d = tmp_path / "data"
    d.mkdir()
    return d


@pytest.fixture
async def ontology(ontology_dir: Path, data_dir: Path) -> VesselOntologyService:
    svc = VesselOntologyService(ontology_dir, data_dir=data_dir)
    await svc.initialize()
    return svc


async def _wire(
    ontology: VesselOntologyService,
    registry: AgentRegistry,
    *,
    ontology_type: str,
    agent_id: str,
    registry_type: str | None = None,
) -> None:
    """Wire ``agent_id`` to ``ontology_type``'s billet and register the agent.

    ``registry_type`` defaults to ``ontology_type``; pass a different value to
    fabricate a billet filled by a wrong-role agent (out-of-chain tests).
    """
    ontology.wire_agent(ontology_type, agent_id)
    agent = _CrewAgent(agent_id=agent_id)
    agent.agent_type = registry_type or ontology_type
    await registry.register(agent)


def _decision(
    spec_id: str,
    agent_id: str | None,
    *,
    capability: str | None = "build code",
    department: str | None = "engineering",
) -> AssignmentDecision:
    return AssignmentDecision(
        spec_id=spec_id,
        agent_id=agent_id,
        department=department,
        capability=capability,
        score=0.5,
        reason="capability_match",
    )


# ------------------------------------------------------------------ tests

@pytest.mark.asyncio
async def test_chief_delegates_issues_order(ontology: VesselOntologyService) -> None:
    registry = AgentRegistry()
    await _wire(ontology, registry, ontology_type="engineering_officer", agent_id="chief-eng-1")
    await _wire(ontology, registry, ontology_type="builder", agent_id="builder-1")
    mgr = OrderManager(ontology=ontology, registry=registry)
    delegator = CrewDelegator(ontology=ontology, order_manager=mgr, agent_registry=registry)

    result = delegator.delegate(_decision("s1", "builder-1"))

    assert result.delegated is True
    assert result.reason == "delegated_via_chief"
    assert result.chief_agent_id == "chief-eng-1"
    assert result.worker_agent_id == "builder-1"
    assert result.order_id is not None


@pytest.mark.asyncio
async def test_worker_is_chief_self_assigned(ontology: VesselOntologyService) -> None:
    registry = AgentRegistry()
    # engineering_officer fills chief_engineer — a leader with no in-dept superior.
    await _wire(ontology, registry, ontology_type="engineering_officer", agent_id="eng-self-1")
    mgr = OrderManager(ontology=ontology, registry=registry)
    delegator = CrewDelegator(ontology=ontology, order_manager=mgr, agent_registry=registry)

    result = delegator.delegate(_decision("s2", "eng-self-1"))

    assert result.reason == "self_assigned"
    assert result.delegated is False
    assert result.worker_agent_id == "eng-self-1"
    assert result.chief_agent_id is None
    assert result.order_id is None


@pytest.mark.asyncio
async def test_fabricated_out_of_chain_rejected(ontology: VesselOntologyService) -> None:
    registry = AgentRegistry()
    # chief_engineer billet filled by an agent whose REAL role (scout) holds no
    # authority over builder_officer -> OrderManager rejects -> out_of_chain.
    await _wire(
        ontology, registry,
        ontology_type="engineering_officer", agent_id="rogue-1", registry_type="scout",
    )
    await _wire(ontology, registry, ontology_type="builder", agent_id="builder-1")
    mgr = OrderManager(ontology=ontology, registry=registry)
    delegator = CrewDelegator(ontology=ontology, order_manager=mgr, agent_registry=registry)

    result = delegator.delegate(_decision("s3", "builder-1"))

    assert result.reason == "out_of_chain"
    assert result.delegated is False
    assert result.chief_agent_id == "rogue-1"
    assert result.worker_agent_id == "builder-1"
    assert result.order_id is None


@pytest.mark.asyncio
async def test_no_chief_in_department_direct(ontology: VesselOntologyService) -> None:
    registry = AgentRegistry()
    # security_officer fills chief_security: leaf (authority_over=[]), no in-dept
    # superior with authority over it -> direct_no_chief.
    await _wire(ontology, registry, ontology_type="security_officer", agent_id="sec-1")
    mgr = OrderManager(ontology=ontology, registry=registry)
    delegator = CrewDelegator(ontology=ontology, order_manager=mgr, agent_registry=registry)

    result = delegator.delegate(_decision("s4", "sec-1", department="security"))

    assert result.reason == "direct_no_chief"
    assert result.delegated is False
    assert result.worker_agent_id == "sec-1"
    assert result.chief_agent_id is None
    assert result.order_id is None


@pytest.mark.asyncio
async def test_order_manager_none_degrades_without_raise(ontology: VesselOntologyService) -> None:
    registry = AgentRegistry()
    await _wire(ontology, registry, ontology_type="engineering_officer", agent_id="chief-eng-1")
    await _wire(ontology, registry, ontology_type="builder", agent_id="builder-1")
    delegator = CrewDelegator(ontology=ontology, order_manager=None, agent_registry=registry)

    result = delegator.delegate(_decision("s5", "builder-1"))

    assert result.reason == "direct_no_chief"
    assert result.delegated is False
    assert result.worker_agent_id == "builder-1"
    # chief provenance is still recorded even though no manager could issue.
    assert result.chief_agent_id == "chief-eng-1"
    assert result.order_id is None


@pytest.mark.asyncio
async def test_order_id_traces_to_issued_order(ontology: VesselOntologyService) -> None:
    registry = AgentRegistry()
    await _wire(ontology, registry, ontology_type="engineering_officer", agent_id="chief-eng-1")
    await _wire(ontology, registry, ontology_type="builder", agent_id="builder-1")
    mgr = OrderManager(ontology=ontology, registry=registry)
    delegator = CrewDelegator(ontology=ontology, order_manager=mgr, agent_registry=registry)

    result = delegator.delegate(_decision("s6", "builder-1"))

    issued = {o.id: o for o in mgr.all_orders()}
    assert result.order_id in issued
    assert issued[result.order_id].to_post_id == "builder_officer"


@pytest.mark.asyncio
async def test_chief_post_unwired_degrades(ontology: VesselOntologyService) -> None:
    registry = AgentRegistry()
    # Worker wired, but the chief_engineer billet (engineering_officer) is left
    # unwired -> resolved chief agent_id is None -> direct_no_chief.
    await _wire(ontology, registry, ontology_type="builder", agent_id="builder-1")
    mgr = OrderManager(ontology=ontology, registry=registry)
    delegator = CrewDelegator(ontology=ontology, order_manager=mgr, agent_registry=registry)

    result = delegator.delegate(_decision("s7", "builder-1"))

    assert result.reason == "direct_no_chief"
    assert result.delegated is False
    assert result.worker_agent_id == "builder-1"
    assert result.chief_agent_id is None
    assert result.order_id is None


@pytest.mark.asyncio
async def test_authority_over_is_the_gate(ontology: VesselOntologyService) -> None:
    registry = AgentRegistry()
    await _wire(ontology, registry, ontology_type="engineering_officer", agent_id="chief-eng-1")
    await _wire(ontology, registry, ontology_type="builder", agent_id="builder-1")
    mgr = OrderManager(ontology=ontology, registry=registry)
    delegator = CrewDelegator(ontology=ontology, order_manager=mgr, agent_registry=registry)

    result = delegator.delegate(_decision("s8", "builder-1"))

    # Delegation only succeeded because builder_officer is in the chief's
    # authority_over — assert that gate holds in the live ontology.
    chief_post = ontology.get_post_for_agent("engineering_officer")
    assert chief_post is not None
    assert "builder_officer" in chief_post.authority_over
    assert result.delegated is True
    assert result.reason == "delegated_via_chief"


@pytest.mark.asyncio
async def test_unresolved_decision_no_order_attempted(ontology: VesselOntologyService) -> None:
    registry = AgentRegistry()
    mgr = OrderManager(ontology=ontology, registry=registry)
    delegator = CrewDelegator(ontology=ontology, order_manager=mgr, agent_registry=registry)

    result = delegator.delegate(_decision("s9", None))

    assert result.reason == "unresolved"
    assert result.delegated is False
    assert result.worker_agent_id is None
    assert result.chief_agent_id is None
    assert result.order_id is None
    # No order should have been attempted for an unresolved decision.
    assert mgr.all_orders() == []


@pytest.mark.asyncio
async def test_worker_agent_id_carried_on_degrade(ontology: VesselOntologyService) -> None:
    registry = AgentRegistry()
    # builder worker with an unwired chief degrades, but the worker_agent_id
    # (what lands in WorkItem.assigned_to) is preserved.
    await _wire(ontology, registry, ontology_type="builder", agent_id="builder-1")
    mgr = OrderManager(ontology=ontology, registry=registry)
    delegator = CrewDelegator(ontology=ontology, order_manager=mgr, agent_registry=registry)

    result = delegator.delegate(_decision("s10", "builder-1"))

    assert result.worker_agent_id == "builder-1"
    assert result.delegated is False


def test_delegation_decision_is_frozen() -> None:
    decision = DelegationDecision(
        spec_id="s",
        chief_agent_id=None,
        worker_agent_id="w",
        order_id=None,
        delegated=False,
        reason="unresolved",
    )
    with pytest.raises((AttributeError, TypeError)):
        decision.delegated = True  # type: ignore[misc]
