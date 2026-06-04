"""AD-864: tests for :class:`CrewAssignmentResolver`.

BF-287 (HARD): the resolver reads ``.agent_type``/``.id`` off registered agents,
``.agent_id``/``.score`` off capability matches, and department/trust lookups off
the ontology and trust network. MagicMock would auto-create every one of those
attributes and pass even if the production code read a phantom name. So these
tests use a **real** :class:`AgentRegistry` (concrete ``BaseAgent`` subclass
instances), a **real** :class:`VesselOntologyService` (loaded from the shipped
``config/ontology``), a **real** :class:`TrustNetwork`, and a **real**
:class:`CapabilityRegistry` with real :class:`CapabilityDescriptor`s.

Agent types below (``builder``/``data_analyst``/``diagnostician``/…) are the real
ones in ``config/ontology/organization.yaml`` so ``get_agent_department`` returns
the genuine department mapping (builder→engineering, data_analyst/scout→science,
diagnostician→medical, security_officer→security).
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

import pytest

from probos.cognitive.crew_assignment import AssignmentDecision, CrewAssignmentResolver
from probos.consensus.trust import TrustNetwork
from probos.consultation.dispatch import WorkItemSpec
from probos.mesh.capability import CapabilityRegistry
from probos.ontology import VesselOntologyService
from probos.substrate.agent import BaseAgent
from probos.substrate.registry import AgentRegistry
from probos.types import CapabilityDescriptor


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


async def _make_registry(agents: list[tuple[str, str]]) -> AgentRegistry:
    """``agents`` = list of (agent_type, agent_id). Returns a real registry."""
    registry = AgentRegistry()
    for agent_type, agent_id in agents:
        agent = _CrewAgent(agent_id=agent_id)
        agent.agent_type = agent_type
        await registry.register(agent)
    return registry


def _capability_registry(specs: dict[str, list[str]]) -> CapabilityRegistry:
    """``specs`` = {agent_id: [can, ...]}. Semantic matching off for determinism."""
    reg = CapabilityRegistry(semantic_matching=False)
    for agent_id, cans in specs.items():
        reg.register(agent_id, [CapabilityDescriptor(can=c) for c in cans])
    return reg


def _spec(spec_id: str, *, capability: str | None = None, department: str | None = None) -> WorkItemSpec:
    return WorkItemSpec(spec_id=spec_id, title=spec_id, capability=capability, department=department)


# ------------------------------------------------------------------ tests

@pytest.mark.asyncio
async def test_capability_only_picks_top_capability_match(ontology: VesselOntologyService) -> None:
    registry = await _make_registry([("builder", "builder-1"), ("data_analyst", "analyst-1")])
    caps = _capability_registry({"builder-1": ["write code"]})
    resolver = CrewAssignmentResolver(
        capability_registry=caps,
        ontology=ontology,
        trust_network=TrustNetwork(),
        agent_registry=registry,
    )

    decision = resolver.resolve(_spec("s1", capability="write code"))

    assert decision.agent_id == "builder-1"
    assert decision.reason == "capability_match"
    assert decision.score > 0.0
    assert decision.capability == "write code"


@pytest.mark.asyncio
async def test_capability_and_department_keeps_only_in_department(ontology: VesselOntologyService) -> None:
    registry = await _make_registry([("data_analyst", "analyst-1"), ("diagnostician", "doc-1")])
    # Both claim the same capability; only the medical agent should survive.
    caps = _capability_registry({"analyst-1": ["diagnose"], "doc-1": ["diagnose"]})
    resolver = CrewAssignmentResolver(
        capability_registry=caps,
        ontology=ontology,
        trust_network=TrustNetwork(),
        agent_registry=registry,
    )

    decision = resolver.resolve(_spec("s2", capability="diagnose", department="medical"))

    assert decision.agent_id == "doc-1"
    assert decision.reason == "capability_match"
    assert decision.department == "medical"


@pytest.mark.asyncio
async def test_department_filter_empties_falls_back_to_capability(ontology: VesselOntologyService) -> None:
    registry = await _make_registry([("builder", "builder-1"), ("data_analyst", "analyst-1")])
    caps = _capability_registry({"builder-1": ["write code"], "analyst-1": ["write code"]})
    trust = TrustNetwork()
    for _ in range(5):  # make the builder the clear top match
        trust.record_outcome("builder-1", True)
    resolver = CrewAssignmentResolver(
        capability_registry=caps,
        ontology=ontology,
        trust_network=trust,
        agent_registry=registry,
    )

    # No agent is in "medical" → department filter empties → fallback.
    decision = resolver.resolve(_spec("s3", capability="write code", department="medical"))

    assert decision.reason == "capability_match_dept_unavailable"
    assert decision.agent_id == "builder-1"
    assert decision.score > 0.0


@pytest.mark.asyncio
async def test_department_only_picks_highest_trust_in_department(ontology: VesselOntologyService) -> None:
    registry = await _make_registry([("builder", "builder-low"), ("engineering_officer", "eng-high")])
    trust = TrustNetwork()
    for _ in range(6):  # eng-high earns the higher trust score
        trust.record_outcome("eng-high", True)
    resolver = CrewAssignmentResolver(
        capability_registry=_capability_registry({}),
        ontology=ontology,
        trust_network=trust,
        agent_registry=registry,
    )

    decision = resolver.resolve(_spec("s4", department="engineering"))

    assert decision.agent_id == "eng-high"
    assert decision.reason == "department_only"
    assert decision.score > 0.5


@pytest.mark.asyncio
async def test_department_only_trust_tie_break_is_deterministic(ontology: VesselOntologyService) -> None:
    # Both engineering, both at the prior (equal trust) → lexical agent_id wins.
    registry = await _make_registry([("builder", "aaa-builder"), ("engineering_officer", "zzz-eng")])
    resolver = CrewAssignmentResolver(
        capability_registry=_capability_registry({}),
        ontology=ontology,
        trust_network=TrustNetwork(),
        agent_registry=registry,
    )

    decision = resolver.resolve(_spec("s5", department="engineering"))

    assert decision.agent_id == "aaa-builder"
    assert decision.reason == "department_only"


@pytest.mark.asyncio
async def test_no_hints_is_unresolved(ontology: VesselOntologyService) -> None:
    registry = await _make_registry([("builder", "builder-1")])
    resolver = CrewAssignmentResolver(
        capability_registry=_capability_registry({"builder-1": ["write code"]}),
        ontology=ontology,
        trust_network=TrustNetwork(),
        agent_registry=registry,
    )

    decision = resolver.resolve(_spec("s6"))

    assert decision.agent_id is None
    assert decision.reason == "unresolved_no_candidate"
    assert decision.score == 0.0


@pytest.mark.asyncio
async def test_dead_agent_excluded_from_candidates(ontology: VesselOntologyService) -> None:
    # Capability registered for "ghost", but ghost is not in the agent registry.
    registry = await _make_registry([("builder", "builder-1")])
    caps = _capability_registry({"ghost": ["exotic skill"]})
    resolver = CrewAssignmentResolver(
        capability_registry=caps,
        ontology=ontology,
        trust_network=TrustNetwork(),
        agent_registry=registry,
    )

    decision = resolver.resolve(_spec("s7", capability="exotic skill"))

    assert decision.agent_id is None
    assert decision.reason == "unresolved_no_candidate"


@pytest.mark.asyncio
async def test_resolve_all_maps_each_spec(ontology: VesselOntologyService) -> None:
    registry = await _make_registry([("builder", "builder-1"), ("diagnostician", "doc-1")])
    caps = _capability_registry({"builder-1": ["write code"], "doc-1": ["diagnose"]})
    resolver = CrewAssignmentResolver(
        capability_registry=caps,
        ontology=ontology,
        trust_network=TrustNetwork(),
        agent_registry=registry,
    )

    specs = [
        _spec("a", capability="write code"),
        _spec("b", capability="diagnose"),
        _spec("c"),  # unresolved
    ]
    decisions = resolver.resolve_all(specs)

    assert [d.spec_id for d in decisions] == ["a", "b", "c"]
    assert decisions[0].agent_id == "builder-1"
    assert decisions[1].agent_id == "doc-1"
    assert decisions[2].agent_id is None


@pytest.mark.asyncio
async def test_unknown_department_only_is_unresolved(ontology: VesselOntologyService) -> None:
    registry = await _make_registry([("builder", "builder-1")])
    resolver = CrewAssignmentResolver(
        capability_registry=_capability_registry({}),
        ontology=ontology,
        trust_network=TrustNetwork(),
        agent_registry=registry,
    )

    decision = resolver.resolve(_spec("s9", department="nonexistent-dept"))

    assert decision.agent_id is None
    assert decision.reason == "unresolved_no_candidate"


@pytest.mark.asyncio
async def test_score_is_zero_iff_unresolved(ontology: VesselOntologyService) -> None:
    registry = await _make_registry([("builder", "builder-1")])
    caps = _capability_registry({"builder-1": ["write code"]})
    resolver = CrewAssignmentResolver(
        capability_registry=caps,
        ontology=ontology,
        trust_network=TrustNetwork(),
        agent_registry=registry,
    )

    resolved = resolver.resolve(_spec("ok", capability="write code"))
    unresolved = resolver.resolve(_spec("nope", capability="no such skill"))

    assert resolved.score > 0.0 and resolved.agent_id is not None
    assert unresolved.score == 0.0 and unresolved.agent_id is None


@pytest.mark.asyncio
async def test_collaborator_error_degrades_to_unresolved(ontology: VesselOntologyService) -> None:
    class _RaisingCapabilityRegistry:
        def query(self, intent: str, trust_scores: dict[str, float] | None = None) -> list:
            raise RuntimeError("capability index corrupted")

    registry = await _make_registry([("builder", "builder-1")])
    resolver = CrewAssignmentResolver(
        capability_registry=_RaisingCapabilityRegistry(),
        ontology=ontology,
        trust_network=TrustNetwork(),
        agent_registry=registry,
    )

    # Must not propagate — honest-degrade to unresolved.
    decision = resolver.resolve(_spec("s11", capability="write code"))

    assert isinstance(decision, AssignmentDecision)
    assert decision.agent_id is None
    assert decision.reason == "unresolved_no_candidate"
