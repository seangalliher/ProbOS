"""AD-866: department-aware independent verifier selection.

``SubtaskVerifier._pick_independent_verifier`` gains an org-chart-aware
selection order when an ``ontology`` is wired: a same-department peer is
preferred, then the producer's chief (a superior post's agent), then any
independent agent (the AD-860 behavior), then honest-degrade to ``unverified``.
With no ontology wired, the AD-860 any-independent path runs verbatim.

BF-287 (HARD): the selection reads ``.agent_type``/``.id`` off registered
agents, maps ``agent_type -> department`` through the ontology, and walks the
real chain of command resolving ``get_agents_for_post`` assignments. A
MagicMock would auto-create every one of those attributes and pass even if the
production code read a phantom name. So these tests use a **real**
:class:`AgentRegistry` (concrete ``BaseAgent`` subclass instances) and a
**real** :class:`VesselOntologyService` loaded from the shipped
``config/ontology``. Only the LLM judge / store / AD-859a executor are small
``_Fake*`` stubs (no org-chart surface to phantom).

Real org-chart facts these tests rely on (``config/ontology/organization.yaml``):

- agent_type ``builder`` fills post ``builder_officer`` (department
  ``engineering``, leaf).
- agent_type ``engineering_officer`` fills post ``chief_engineer`` (department
  ``engineering``; ``chief_engineer`` ``reports_to: first_officer``).
- agent_type ``architect`` fills post ``first_officer`` (department ``bridge``).
- agent_type ``scout`` fills post ``scout_officer`` (department ``science``).
"""

from __future__ import annotations

import shutil
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from probos.cognitive.agentic_dispatch import WorkItemAgenticOutcome
from probos.cognitive.crew_executor import SubtaskResult
from probos.cognitive.crew_verifier import SubtaskVerifier
from probos.consensus.trust import TrustNetwork
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


# ------------------------------------------------------------------ fakes

class _FakeLLM:
    """Scripted LLM judge: ``complete`` always accepts so the returned verdict's
    ``verifier_agent_id`` reveals exactly which agent the selection picked."""

    async def complete(self, request: Any, **_kw: Any) -> Any:
        return SimpleNamespace(
            content='{"accepted": true, "confidence": 0.9, "critique": "ok"}'
        )


class _FakeStore:
    """No work item -> the free-text critique path (no expected_output)."""

    async def get_work_item(self, work_item_id: str) -> Any:
        return None


class _FakeExecutor:
    """AD-859a executor stub — never exercised (the judge accepts)."""

    async def run(self, *, agent_id: str, instructions: str, task_text: str,
                  runtime: Any, department: str = "", rank: str = "ensign") -> WorkItemAgenticOutcome:
        return WorkItemAgenticOutcome(final_text="")


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


async def _register(
    registry: AgentRegistry,
    *,
    agent_id: str,
    agent_type: str,
) -> None:
    """Register a real BaseAgent carrying ``agent_type`` (the selection reads it)."""
    agent = _CrewAgent(agent_id=agent_id)
    agent.agent_type = agent_type
    await registry.register(agent)


def _make_verifier(
    registry: AgentRegistry,
    ontology: VesselOntologyService | None,
) -> SubtaskVerifier:
    kwargs: dict[str, Any] = dict(
        llm_client=_FakeLLM(),
        work_item_store=_FakeStore(),
        agent_registry=registry,
        trust_network=TrustNetwork(),
        agentic_executor=_FakeExecutor(),
        runtime=SimpleNamespace(),
    )
    if ontology is not None:
        kwargs["ontology"] = ontology
    return SubtaskVerifier(**kwargs)


def _result(agent_id: str) -> SubtaskResult:
    return SubtaskResult(
        work_item_id="wi-1",
        spec_id="spec-1",
        agent_id=agent_id,
        output="the produced output",
        status="done",
    )


# ------------------------------------------------------------------ tests

@pytest.mark.asyncio
async def test_pick_verifier_same_department_peer_preferred_over_cross_department(
    ontology: VesselOntologyService,
) -> None:
    registry = AgentRegistry()
    await _register(registry, agent_id="builder-1", agent_type="builder")  # producer (eng)
    # Register the cross-department independent FIRST so a naive any-independent
    # pass would pick it — the dept-peer step must beat positional order.
    await _register(registry, agent_id="scout-1", agent_type="scout")  # science
    await _register(registry, agent_id="eng-1", agent_type="engineering_officer")  # eng peer
    ontology.wire_agent("builder", "builder-1")
    ontology.wire_agent("scout", "scout-1")
    ontology.wire_agent("engineering_officer", "eng-1")
    verifier = _make_verifier(registry, ontology)

    verdict = await verifier.verify(_result("builder-1"))

    assert verdict.verifier_agent_id == "eng-1"
    assert verdict.verifier_agent_id != "scout-1"
    assert verdict.verifier_agent_id != "builder-1"


@pytest.mark.asyncio
async def test_pick_verifier_chief_used_when_no_department_peer(
    ontology: VesselOntologyService,
) -> None:
    registry = AgentRegistry()
    # Producer fills chief_engineer (engineering); it is the only engineering
    # agent, so there is no same-department peer.
    await _register(registry, agent_id="eng-chief-1", agent_type="engineering_officer")
    # The producer's chief in the chain (first_officer, bridge) is alive.
    await _register(registry, agent_id="arch-1", agent_type="architect")
    ontology.wire_agent("engineering_officer", "eng-chief-1")
    ontology.wire_agent("architect", "arch-1")
    verifier = _make_verifier(registry, ontology)

    verdict = await verifier.verify(_result("eng-chief-1"))

    assert verdict.verifier_agent_id == "arch-1"
    assert verdict.verifier_agent_id != "eng-chief-1"


@pytest.mark.asyncio
async def test_pick_verifier_any_independent_fallback_when_department_has_only_producer(
    ontology: VesselOntologyService,
) -> None:
    registry = AgentRegistry()
    # Producer is the only engineering agent and no superior post is wired/alive,
    # so steps 1-2 yield nothing and selection falls to any-independent (step 3).
    await _register(registry, agent_id="builder-1", agent_type="builder")
    await _register(registry, agent_id="scout-1", agent_type="scout")  # science independent
    ontology.wire_agent("builder", "builder-1")
    ontology.wire_agent("scout", "scout-1")
    verifier = _make_verifier(registry, ontology)

    verdict = await verifier.verify(_result("builder-1"))

    assert verdict.verifier_agent_id == "scout-1"
    assert verdict.verifier_agent_id != "builder-1"


@pytest.mark.asyncio
async def test_pick_verifier_degrades_unverified_when_no_independent_agent(
    ontology: VesselOntologyService,
) -> None:
    registry = AgentRegistry()
    # Registry holds ONLY the producer — no peer, no chief, no independent.
    await _register(registry, agent_id="builder-1", agent_type="builder")
    ontology.wire_agent("builder", "builder-1")
    verifier = _make_verifier(registry, ontology)

    verdict = await verifier.verify(_result("builder-1"))

    assert verdict.verifier_agent_id == ""
    assert verdict.accepted is False


@pytest.mark.asyncio
async def test_pick_verifier_ontology_none_reproduces_ad860_any_independent(
    ontology: VesselOntologyService,
) -> None:
    registry = AgentRegistry()
    # With ontology=None the org-chart steps are skipped: the first registered
    # agent that is not the producer wins (AD-860 behavior, verbatim).
    await _register(registry, agent_id="builder-1", agent_type="builder")  # producer
    await _register(registry, agent_id="scout-1", agent_type="scout")  # first non-producer
    verifier = _make_verifier(registry, ontology=None)

    verdict = await verifier.verify(_result("builder-1"))

    assert verdict.verifier_agent_id == "scout-1"
    assert verdict.verifier_agent_id != "builder-1"


@pytest.mark.asyncio
async def test_pick_verifier_producer_never_selected_as_its_own_verifier(
    ontology: VesselOntologyService,
) -> None:
    registry = AgentRegistry()
    # Sole-producer branch: must honest-degrade, never return the producer.
    await _register(registry, agent_id="builder-1", agent_type="builder")
    ontology.wire_agent("builder", "builder-1")
    verifier = _make_verifier(registry, ontology)
    sole = await verifier.verify(_result("builder-1"))
    assert sole.verifier_agent_id != "builder-1"
    assert sole.verifier_agent_id == ""

    # Peer branch: a same-department peer is returned, never the producer.
    await _register(registry, agent_id="eng-1", agent_type="engineering_officer")
    ontology.wire_agent("engineering_officer", "eng-1")
    peer = await verifier.verify(_result("builder-1"))
    assert peer.verifier_agent_id == "eng-1"
    assert peer.verifier_agent_id != "builder-1"


@pytest.mark.asyncio
async def test_pick_verifier_dead_chief_excluded_falls_through_to_live_independent(
    ontology: VesselOntologyService,
) -> None:
    registry = AgentRegistry()
    # Producer fills chief_engineer; no engineering peer.
    await _register(registry, agent_id="eng-chief-1", agent_type="engineering_officer")
    # The chief post (first_officer) is WIRED in the ontology but its agent is
    # NOT registered — a dead/unregistered superior that must be excluded.
    ontology.wire_agent("engineering_officer", "eng-chief-1")
    ontology.wire_agent("architect", "dead-arch")
    # A live, independent agent in another department is the only valid judge.
    await _register(registry, agent_id="scout-1", agent_type="scout")
    ontology.wire_agent("scout", "scout-1")
    verifier = _make_verifier(registry, ontology)

    verdict = await verifier.verify(_result("eng-chief-1"))

    assert verdict.verifier_agent_id == "scout-1"
    assert verdict.verifier_agent_id != "dead-arch"
    assert verdict.verifier_agent_id != "eng-chief-1"
