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
from collections.abc import AsyncIterator, Awaitable, Callable
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from probos.cognitive.agentic_dispatch import _resolve_agentic_identity
from probos.cognitive.crew_assignment import (
    AssignmentDecision,
    CrewAssignmentResolver,
    CrewWorkerEligibilityResolver,
)
from probos.consensus.trust import TrustNetwork
from probos.consultation.dispatch import WorkItemSpec
from probos.crew_profile import Rank
from probos.mesh.capability import CapabilityRegistry
from probos.ontology import VesselOntologyService
from probos.substrate.agent import BaseAgent
from probos.substrate.registry import AgentRegistry
from probos.types import AgentState, CapabilityDescriptor


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


_LiveRegistryFactory = Callable[[list[tuple[str, str]]], Awaitable[AgentRegistry]]


@pytest.fixture
async def live_registry() -> AsyncIterator[_LiveRegistryFactory]:
    agents: list[BaseAgent] = []

    async def create(specs: list[tuple[str, str]]) -> AgentRegistry:
        registry = await _make_registry(specs)
        for agent in registry.all():
            agents.append(agent)
            await agent.start()
            assert agent.is_alive is True
        return registry

    try:
        yield create
    finally:
        for agent in agents:
            await agent.stop()


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
async def test_assignment_skips_live_capability_match_with_unresolved_identity(
    ontology: VesselOntologyService,
) -> None:
    registry = await _make_registry([("summarizer", "summary-1"), ("builder", "builder-1")])
    caps = _capability_registry({"summary-1": ["summarize"], "builder-1": ["summarize"]})
    trust = TrustNetwork()
    for _ in range(6):
        trust.record_outcome("summary-1", True)
    runtime = SimpleNamespace(registry=registry, ontology=ontology, trust_network=trust)
    resolver = CrewAssignmentResolver(
        capability_registry=caps,
        ontology=ontology,
        trust_network=trust,
        agent_registry=registry,
    )
    agents = registry.all()
    assert len(agents) == 2
    assert caps.agent_count == 2

    try:
        for agent in agents:
            assert isinstance(agent, BaseAgent)
            await agent.start()
        assert all(agent.is_alive is True for agent in agents)

        matches = caps.query("summarize", trust_scores=trust.all_scores())
        assert len(matches) == 2
        assert {match.agent_id for match in matches} == {"summary-1", "builder-1"}
        assert matches[0].agent_id == "summary-1"
        assert matches[0].score > matches[1].score
        assert trust.get_score("summary-1") > trust.get_score("builder-1")

        with pytest.raises(RuntimeError, match="^agentic_identity_unresolved$"):
            _resolve_agentic_identity(
                runtime=runtime,
                tool_registry=None,
                agent_id="summary-1",
                fallback_department="engineering",
                fallback_rank="lieutenant",
            )
        builder_identity = _resolve_agentic_identity(
            runtime=runtime,
            tool_registry=None,
            agent_id="builder-1",
            fallback_department="science",
            fallback_rank="captain",
        )
        assert builder_identity == ("engineering", "lieutenant")
        assert builder_identity[1] == Rank.from_trust(trust.get_score("builder-1")).value

        decision = resolver.resolve(_spec("identity-baseline", capability="summarize"))

        assert decision.agent_id == "builder-1"
    finally:
        for agent in agents:
            await agent.stop()


@pytest.mark.asyncio
async def test_capability_only_picks_top_capability_match(
    ontology: VesselOntologyService, live_registry: _LiveRegistryFactory,
) -> None:
    registry = await live_registry([("builder", "builder-1"), ("data_analyst", "analyst-1")])
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
async def test_capability_and_department_keeps_only_in_department(
    ontology: VesselOntologyService, live_registry: _LiveRegistryFactory,
) -> None:
    registry = await live_registry([("data_analyst", "analyst-1"), ("diagnostician", "doc-1")])
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
async def test_department_filter_empties_falls_back_to_capability(
    ontology: VesselOntologyService, live_registry: _LiveRegistryFactory,
) -> None:
    registry = await live_registry([("builder", "builder-1"), ("data_analyst", "analyst-1")])
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
async def test_department_only_picks_highest_trust_in_department(
    ontology: VesselOntologyService, live_registry: _LiveRegistryFactory,
) -> None:
    registry = await live_registry([("builder", "builder-low"), ("engineering_officer", "eng-high")])
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
async def test_department_only_trust_tie_break_is_deterministic(
    ontology: VesselOntologyService, live_registry: _LiveRegistryFactory,
) -> None:
    # Both engineering, both at the prior (equal trust) → lexical agent_id wins.
    registry = await live_registry([("builder", "aaa-builder"), ("engineering_officer", "zzz-eng")])
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
@pytest.mark.parametrize("hint", [None, ""])
async def test_no_hints_is_unresolved(
    ontology: VesselOntologyService, live_registry: _LiveRegistryFactory,
    hint: str | None,
) -> None:
    registry = await live_registry([("builder", "builder-1")])
    resolver = CrewAssignmentResolver(
        capability_registry=_capability_registry({"builder-1": ["write code"]}),
        ontology=ontology,
        trust_network=TrustNetwork(),
        agent_registry=registry,
    )

    decision = resolver.resolve(_spec("s6", capability=hint, department=hint))

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
async def test_resolve_all_maps_each_spec(
    ontology: VesselOntologyService, live_registry: _LiveRegistryFactory,
) -> None:
    registry = await live_registry([("builder", "builder-1"), ("diagnostician", "doc-1")])
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
async def test_unknown_department_only_is_unresolved(
    ontology: VesselOntologyService, live_registry: _LiveRegistryFactory,
) -> None:
    registry = await live_registry([("builder", "builder-1")])
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
async def test_score_is_zero_iff_unresolved(
    ontology: VesselOntologyService, live_registry: _LiveRegistryFactory,
) -> None:
    registry = await live_registry([("builder", "builder-1")])
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


@pytest.mark.asyncio
@pytest.mark.parametrize("state", ["spawning", "active", "degraded", "recycling", "removed"])
async def test_check_eligibility_uses_public_lifecycle(
    ontology: VesselOntologyService, state: str,
) -> None:
    registry = await _make_registry([("builder", "builder-1")])
    agent = registry.get("builder-1")
    assert agent is not None
    assert agent.state == AgentState.SPAWNING
    resolver: CrewWorkerEligibilityResolver = CrewAssignmentResolver(
        capability_registry=_capability_registry({}), ontology=ontology,
        trust_network=TrustNetwork(), agent_registry=registry,
    )
    try:
        if state != "spawning":
            await agent.start()
            assert agent.is_alive is True
        if state == "degraded":
            agent.confidence = 0.01
            agent.update_confidence(False)
            assert agent.state == AgentState.DEGRADED
        elif state == "recycling":
            await agent.stop()
            assert agent.state == AgentState.RECYCLING
        elif state == "removed":
            assert await registry.unregister(agent.id) is agent
            assert agent.is_alive is True

        result = resolver.check_eligibility("builder-1")

        if state in {"active", "degraded"}:
            assert result.reason == "eligible"
            assert result.identity is not None
            assert result.identity.agent_id == "builder-1"
            assert result.identity.agent_type == "builder"
            assert result.identity.department == "engineering"
            assert result.identity.rank == "lieutenant"
        else:
            assert result.identity is None
            assert result.reason == ("missing" if state == "removed" else "inactive")
    finally:
        await agent.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize("agent_id", ["", None, 42, "missing"])
async def test_check_eligibility_invalid_or_missing_id_is_bounded(
    ontology: VesselOntologyService, agent_id: Any,
) -> None:
    resolver = CrewAssignmentResolver(
        capability_registry=_capability_registry({}), ontology=ontology,
        trust_network=TrustNetwork(), agent_registry=AgentRegistry(),
    )

    result = resolver.check_eligibility(agent_id)

    assert result.identity is None
    assert result.reason == ("missing" if agent_id == "missing" else "unresolved_identity")
    assert resolver.resolve_all([]) == []


@pytest.mark.asyncio
@pytest.mark.parametrize("defect", ["id_mismatch", "unknown_type", "empty_type", "malformed_type"])
@pytest.mark.parametrize("capability", [None, "write code"])
async def test_assignment_rejects_malformed_identity_and_selects_valid_alternative(
    ontology: VesselOntologyService, live_registry: _LiveRegistryFactory,
    defect: str, capability: str | None,
) -> None:
    registry = await live_registry([("builder", "invalid-1"), ("builder", "builder-1")])
    agent = registry.get("invalid-1")
    assert agent is not None and agent.is_alive
    trust = TrustNetwork()
    for _ in range(6):
        trust.record_outcome("invalid-1", True)
    caps = _capability_registry({"invalid-1": ["write code"], "builder-1": ["write code"]})
    assert caps.query("write code", trust_scores=trust.all_scores())[0].agent_id == "invalid-1"
    if defect == "id_mismatch":
        agent.id = "different-id"
    elif defect == "unknown_type":
        agent.agent_type = "summarizer"
    elif defect == "empty_type":
        agent.agent_type = ""
    else:
        agent.agent_type = None
    resolver = CrewAssignmentResolver(
        capability_registry=caps, ontology=ontology,
        trust_network=trust, agent_registry=registry,
    )

    result = resolver.check_eligibility("invalid-1")
    decision = resolver.resolve(_spec("identity", capability=capability, department="engineering"))

    assert result.identity is None
    assert result.reason == "unresolved_identity"
    assert decision.agent_id == "builder-1"


@pytest.mark.asyncio
@pytest.mark.parametrize("capability", [None, "write code"])
@pytest.mark.parametrize("state", ["spawning", "recycling", "removed"])
async def test_assignment_filters_inactive_top_candidate_before_ranking(
    ontology: VesselOntologyService, live_registry: _LiveRegistryFactory,
    capability: str | None, state: str,
) -> None:
    registry = await live_registry([("builder", "builder-1")])
    unavailable = _CrewAgent(agent_id="unavailable-1")
    unavailable.agent_type = "builder"
    await registry.register(unavailable)
    try:
        if state != "spawning":
            await unavailable.start()
        if state == "recycling":
            await unavailable.stop()
        elif state == "removed":
            await registry.unregister(unavailable.id)
        trust = TrustNetwork()
        for _ in range(6):
            trust.record_outcome(unavailable.id, True)
        caps = _capability_registry({unavailable.id: ["write code"], "builder-1": ["write code"]})
        assert caps.query("write code", trust_scores=trust.all_scores())[0].agent_id == unavailable.id
        resolver = CrewAssignmentResolver(
            capability_registry=caps, ontology=ontology,
            trust_network=trust, agent_registry=registry,
        )

        decision = resolver.resolve(_spec("lifecycle", capability=capability, department="engineering"))

        assert decision.agent_id == "builder-1"
        await registry.unregister("builder-1")
        assert resolver.resolve(_spec("no-candidate", capability=capability, department="engineering")).agent_id is None
    finally:
        await unavailable.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize("capability", [None, "write code"])
async def test_assignment_uses_authoritative_standing_orders_department_fallback(
    live_registry: _LiveRegistryFactory, capability: str | None,
) -> None:
    class _EmptyOntology:
        def get_agent_department(self, agent_type: str) -> str | None:
            return None

    registry = await live_registry([("builder", "builder-1")])
    resolver = CrewAssignmentResolver(
        capability_registry=_capability_registry({"builder-1": ["write code"]}),
        ontology=_EmptyOntology(), trust_network=TrustNetwork(), agent_registry=registry,
    )

    result = resolver.check_eligibility("builder-1")
    decision = resolver.resolve(_spec("fallback", capability=capability, department="engineering"))

    assert result.identity is not None
    assert result.identity.department == "engineering"
    assert decision.agent_id == "builder-1"
    assert decision.reason == ("capability_match" if capability else "department_only")


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["registry", "ontology", "trust"])
async def test_check_eligibility_dependency_failure_rejects_without_privilege_fallback(
    ontology: VesselOntologyService, live_registry: _LiveRegistryFactory,
    monkeypatch: pytest.MonkeyPatch, failure: str,
) -> None:
    registry = await live_registry([("builder", "builder-1")])
    trust = TrustNetwork()
    resolver = CrewAssignmentResolver(
        capability_registry=_capability_registry({"builder-1": ["write code"]}),
        ontology=ontology, trust_network=trust, agent_registry=registry,
    )
    assert resolver.check_eligibility("builder-1").identity is not None

    def fail_lookup(key: str) -> Any:
        raise RuntimeError("collaborator unavailable")

    dependency, method = {
        "registry": (registry, "get"),
        "ontology": (ontology, "get_agent_department"),
        "trust": (trust, "get_score"),
    }[failure]
    monkeypatch.setattr(dependency, method, fail_lookup)

    result = resolver.check_eligibility("builder-1")

    assert result.identity is None
    assert result.reason == "unresolved_identity"
    for capability in (None, "write code"):
        assert resolver.resolve(_spec("failure", capability=capability, department="engineering")).agent_id is None
