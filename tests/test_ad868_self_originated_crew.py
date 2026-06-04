"""AD-868: Lieutenant+ agents self-originate their own crew tasks.

Two surfaces are exercised:

1. :meth:`CrewOrchestrator.originate_crew_task` — decomposes a goal, creates a
   self-originated parent + ``parent_id``-linked children, and runs the full
   AD-867 pipeline. Honest-degrades (disabled / no-decomposer / decompose-raise /
   empty-specs) to ``None`` with **no dangling parent** and never raises. Trust
   attribution is owned by the AD-861 synthesizer — no second write happens here.

2. The ``[CREW]...[/CREW]`` proactive tag in
   :meth:`ProactiveCognitiveLoop._extract_and_execute_actions`, rank-gated to
   Lieutenant+ via the AD-654d ``_RANK_ORDER_ASSIGN`` machinery. Ensign is
   silently ignored; the tag is stripped regardless. A missing
   ``crew_orchestrator`` logs and skips without raising.

Per BF-287 the substrate boundary (the :class:`WorkItemStore`) is REAL in every
test; only the LLM boundary (the plan decomposer) is faked. The proactive runtime
itself follows the established ``MagicMock(spec=ProbOSRuntime)`` harness used by
the existing proposal/handoff tests, but the ``crew_orchestrator`` it carries is a
REAL :class:`CrewOrchestrator` over a REAL store.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest

from probos.cognitive.crew_orchestrator import CrewOrchestrator
from probos.cognitive.crew_synth import SynthesisResult
from probos.config import SystemConfig
from probos.consultation.dispatch import WorkItemSpec
from probos.proactive import ProactiveCognitiveLoop
from probos.runtime import ProbOSRuntime
from probos.substrate.agent import BaseAgent
from probos.ward_room_router import WardRoomRouter
from probos.workforce import WorkItemStore


# ------------------------------------------------------------------ fakes


class _FakeDecomposer:
    """LLM-boundary stub: returns scripted specs, or raises when ``fail`` is set.

    Conforms to the ``decompose(markdown_text) -> list[WorkItemSpec]`` protocol
    used by :meth:`CrewOrchestrator._get_decomposer`.
    """

    def __init__(self, specs: list[WorkItemSpec] | None = None,
                 fail: bool = False) -> None:
        self._specs = specs
        self._fail = fail
        self.calls: list[str] = []

    def decompose(self, markdown_text: str) -> list[WorkItemSpec]:
        self.calls.append(markdown_text)
        if self._fail:
            raise RuntimeError("decompose boom")
        if self._specs is None:
            return []
        return list(self._specs)


class _FakeResolver:
    def resolve(self, spec: Any) -> Any:
        from probos.cognitive.crew_assignment import AssignmentDecision
        return AssignmentDecision(
            spec_id=spec.spec_id,
            agent_id="worker-default",
            department=spec.department,
            capability=spec.capability,
            score=1.0,
            reason="capability_match",
        )


class _FakeDelegator:
    def delegate(self, decision: Any) -> Any:
        from probos.cognitive.crew_delegation import DelegationDecision
        return DelegationDecision(
            spec_id=decision.spec_id,
            chief_agent_id="chief-1",
            worker_agent_id=decision.agent_id,
            order_id="order-1",
            delegated=True,
            reason="delegated_via_chief",
        )


class _FakeExecutor:
    """``async run(parent_id) -> list[SubtaskResult]`` echoing the loaded children."""

    def __init__(self, store: WorkItemStore) -> None:
        self._store = store
        self.calls: list[str] = []

    async def run(self, parent_id: str) -> list[Any]:
        from probos.cognitive.crew_executor import SubtaskResult
        self.calls.append(parent_id)
        children = await self._store.list_work_items(parent_id=parent_id, limit=1000)
        return [
            SubtaskResult(
                work_item_id=c.id,
                spec_id=c.metadata.get("spec_id", c.id),
                agent_id="worker-default",
                output=f"output for {c.id}",
                status="done",
            )
            for c in children
        ]


class _FakeVerifier:
    async def verify(self, result: Any) -> Any:
        from probos.cognitive.crew_verifier import VerificationVerdict
        return VerificationVerdict(
            accepted=True, confidence=0.9, critique="ok",
            verifier_agent_id="verifier-1",
        )


class _FakeSynth:
    """Records the synth call; never writes trust (AD-861 owns attribution)."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, list[Any]]] = []

    async def synthesize(self, parent_id: str, outcomes: list[Any]) -> SynthesisResult:
        self.calls.append((parent_id, list(outcomes)))
        accepted = sum(1 for o in outcomes if o.verdict.accepted)
        return SynthesisResult(
            parent_id=parent_id,
            final_output="synthesised",
            completed=True,
            accepted_count=accepted,
            total_count=len(outcomes),
        )


# ------------------------------------------------------------------ fixtures


@pytest.fixture
async def store(tmp_path):
    s = WorkItemStore(
        db_path=str(tmp_path / "ad868_crew.db"),
        emit_event=MagicMock(),
        tick_interval=1000,
    )
    await s.start()
    try:
        yield s
    finally:
        await s.stop()


def _config(*, enabled: bool) -> SystemConfig:
    cfg = SystemConfig()
    cfg.agentic_dispatch.orchestrator_enabled = enabled
    return cfg


def _specs(n: int = 2) -> list[WorkItemSpec]:
    out = []
    for i in range(n):
        out.append(WorkItemSpec(
            spec_id=f"spec-{i}",
            title=f"subtask {i}",
            description=f"do part {i}",
            work_type="task",
            priority=3,
            capability="analysis",
            department="science",
            expected_output="a report",
        ))
    return out


def _make_orch(
    *,
    store: WorkItemStore,
    config: SystemConfig,
    decomposer: Any = None,
    runtime: Any = None,
    synthesizer: Any = None,
) -> CrewOrchestrator:
    return CrewOrchestrator(
        assignment_resolver=_FakeResolver(),
        delegator=_FakeDelegator(),
        crew_executor=_FakeExecutor(store),
        verifier=_FakeVerifier(),
        synthesizer=synthesizer or _FakeSynth(),
        work_item_store=store,
        runtime=runtime if runtime is not None else SimpleNamespace(),
        emit_fn=None,
        config=config,
        decomposer=decomposer,
    )


# ------------------------------------------------------------------ originate


@pytest.mark.asyncio
async def test_originate_creates_self_originated_parent_with_children(store):
    orch = _make_orch(
        store=store, config=_config(enabled=True),
        decomposer=_FakeDecomposer(_specs(2)),
    )

    parent_id = await orch.originate_crew_task(
        origin_agent_id="lt-1", goal="investigate the anomaly",
    )

    assert parent_id
    parent = await store.get_work_item(parent_id)
    assert parent is not None
    assert parent.title == "investigate the anomaly"
    assert parent.created_by == "lt-1"
    children = await store.list_work_items(parent_id=parent_id, limit=1000)
    assert len(children) == 2
    # AD-863 hints survive into child metadata for _spec_view to read back.
    for child in children:
        assert child.created_by == "lt-1"
        assert child.metadata.get("capability") == "analysis"
        assert child.metadata.get("department") == "science"


@pytest.mark.asyncio
async def test_originate_provenance_metadata_recorded(store):
    orch = _make_orch(
        store=store, config=_config(enabled=True),
        decomposer=_FakeDecomposer(_specs(1)),
    )

    parent_id = await orch.originate_crew_task(
        origin_agent_id="cmdr-7", goal="draft the brief",
    )

    parent = await store.get_work_item(parent_id)
    assert parent.metadata.get("origin") == "self_originated"
    assert parent.metadata.get("originator") == "cmdr-7"


@pytest.mark.asyncio
async def test_originate_runs_pipeline_and_returns_parent_id(store):
    synth = _FakeSynth()
    orch = _make_orch(
        store=store, config=_config(enabled=True),
        decomposer=_FakeDecomposer(_specs(2)), synthesizer=synth,
    )

    parent_id = await orch.originate_crew_task(
        origin_agent_id="lt-1", goal="run the survey",
    )

    # run_crew_task drove synthesis over the originated children.
    assert parent_id
    assert len(synth.calls) == 1
    synth_parent, outcomes = synth.calls[0]
    assert synth_parent == parent_id
    assert len(outcomes) == 2


@pytest.mark.asyncio
async def test_originate_disabled_returns_none_no_parent(store):
    orch = _make_orch(
        store=store, config=_config(enabled=False),
        decomposer=_FakeDecomposer(_specs(2)),
    )

    parent_id = await orch.originate_crew_task(
        origin_agent_id="lt-1", goal="should not run",
    )

    assert parent_id is None
    assert await store.list_work_items(limit=1000) == []


@pytest.mark.asyncio
async def test_originate_empty_goal_returns_none_no_parent(store):
    orch = _make_orch(
        store=store, config=_config(enabled=True),
        decomposer=_FakeDecomposer(_specs(2)),
    )

    parent_id = await orch.originate_crew_task(origin_agent_id="lt-1", goal="   ")

    assert parent_id is None
    assert await store.list_work_items(limit=1000) == []


@pytest.mark.asyncio
async def test_originate_decompose_failure_returns_none_no_dangling_parent(store):
    orch = _make_orch(
        store=store, config=_config(enabled=True),
        decomposer=_FakeDecomposer(fail=True),
    )

    parent_id = await orch.originate_crew_task(
        origin_agent_id="lt-1", goal="this will fail to decompose",
    )

    # Decomposition runs BEFORE the parent is created, so a failure leaves no
    # dangling parent and never raises.
    assert parent_id is None
    assert await store.list_work_items(limit=1000) == []


@pytest.mark.asyncio
async def test_originate_empty_specs_returns_none_no_parent(store):
    orch = _make_orch(
        store=store, config=_config(enabled=True),
        decomposer=_FakeDecomposer(specs=None),  # decompose() -> []
    )

    parent_id = await orch.originate_crew_task(
        origin_agent_id="lt-1", goal="yields zero specs",
    )

    assert parent_id is None
    assert await store.list_work_items(limit=1000) == []


@pytest.mark.asyncio
async def test_originate_no_decomposer_returns_none_no_parent(store):
    # No injected decomposer AND a runtime without llm_client -> _get_decomposer
    # returns None -> honest-degrade.
    orch = _make_orch(
        store=store, config=_config(enabled=True),
        decomposer=None, runtime=SimpleNamespace(llm_client=None),
    )

    parent_id = await orch.originate_crew_task(
        origin_agent_id="lt-1", goal="no decomposer available",
    )

    assert parent_id is None
    assert await store.list_work_items(limit=1000) == []


@pytest.mark.asyncio
async def test_originate_no_second_trust_write(store):
    # A trust_network on the runtime must NOT be touched by originate_crew_task
    # itself; AD-861's synthesizer owns attribution.
    trust_calls: list[Any] = []
    trust = SimpleNamespace(
        record_outcome=lambda *a, **k: trust_calls.append((a, k)),
    )
    orch = _make_orch(
        store=store, config=_config(enabled=True),
        decomposer=_FakeDecomposer(_specs(2)),
        runtime=SimpleNamespace(trust_network=trust),
    )

    parent_id = await orch.originate_crew_task(
        origin_agent_id="lt-1", goal="no trust write here",
    )

    assert parent_id
    assert trust_calls == []


# ------------------------------------------------------------------ get_decomposer


@pytest.mark.asyncio
async def test_get_decomposer_prefers_injected(store):
    injected = _FakeDecomposer(_specs(1))
    orch = _make_orch(store=store, config=_config(enabled=True), decomposer=injected)

    assert orch._get_decomposer() is injected


@pytest.mark.asyncio
async def test_get_decomposer_lazy_builds_from_runtime_llm_client(store):
    # A runtime with a (non-None) llm_client lets _get_decomposer build a real
    # LLMPlanDecomposer lazily and cache it.
    from probos.consultation.llm_decomposer import LLMPlanDecomposer

    fake_llm = SimpleNamespace(complete=None)  # presence is enough to build one
    orch = _make_orch(
        store=store, config=_config(enabled=True),
        decomposer=None, runtime=SimpleNamespace(llm_client=fake_llm),
    )

    dec = orch._get_decomposer()
    assert isinstance(dec, LLMPlanDecomposer)
    # Cached: a second call returns the same instance.
    assert orch._get_decomposer() is dec


# ------------------------------------------------------------------ proactive [CREW]


def _make_proactive_rt(*, trust_score: float, orchestrator: Any) -> Any:
    """Minimal proactive runtime harness mirroring the proposal tests, but with a
    REAL crew_orchestrator attached."""
    rt = MagicMock(spec=ProbOSRuntime)
    rt.ward_room = MagicMock()
    rt.trust_network = MagicMock()
    rt.trust_network.get_score.return_value = trust_score
    rt.ward_room_router = MagicMock(spec=WardRoomRouter)
    rt.ward_room_router.extract_endorsements.return_value = (None, [])
    rt.config = MagicMock()
    rt.config.communications = MagicMock()
    rt.config.communications.dm_min_rank = "ensign"
    rt.crew_orchestrator = orchestrator
    rt.dispatcher = None
    rt.callsign_registry = MagicMock()
    rt.callsign_registry.get_callsign.return_value = "callsign"
    return rt


def _make_agent(agent_id: str) -> Any:
    agent = MagicMock(spec=BaseAgent)
    agent.id = agent_id
    agent.callsign = agent_id
    return agent


@pytest.mark.asyncio
async def test_proactive_lieutenant_originates_crew_via_tag(store):
    orch = _make_orch(
        store=store, config=_config(enabled=True),
        decomposer=_FakeDecomposer(_specs(2)),
    )
    loop = ProactiveCognitiveLoop(cooldown=0)
    loop.set_runtime(_make_proactive_rt(trust_score=0.6, orchestrator=orch))
    agent = _make_agent("lt-1")

    text = "I see an opportunity.\n[CREW]map the sensor grid[/CREW]\nThoughts above."
    cleaned, actions = await loop._extract_and_execute_actions(agent, text)

    assert "[CREW]" not in cleaned and "[/CREW]" not in cleaned
    crew_actions = [a for a in actions if a.get("type") == "crew"]
    assert len(crew_actions) == 1
    assert crew_actions[0]["goal"] == "map the sensor grid"
    # A real parent was created in the store.
    parent = await store.get_work_item(crew_actions[0]["parent_id"])
    assert parent is not None and parent.created_by == "lt-1"


@pytest.mark.asyncio
async def test_proactive_ensign_blocked_tag_stripped(store):
    orch = _make_orch(
        store=store, config=_config(enabled=True),
        decomposer=_FakeDecomposer(_specs(2)),
    )
    loop = ProactiveCognitiveLoop(cooldown=0)
    loop.set_runtime(_make_proactive_rt(trust_score=0.0, orchestrator=orch))
    agent = _make_agent("ensign-1")

    text = "[CREW]do something big[/CREW]"
    cleaned, actions = await loop._extract_and_execute_actions(agent, text)

    # Ensign cannot originate; tag is stripped, no crew action, no parent.
    assert "[CREW]" not in cleaned
    assert [a for a in actions if a.get("type") == "crew"] == []
    assert await store.list_work_items(limit=1000) == []


@pytest.mark.asyncio
@pytest.mark.parametrize("trust_score", [0.75, 0.9])
async def test_proactive_commander_and_senior_allowed(store, trust_score):
    orch = _make_orch(
        store=store, config=_config(enabled=True),
        decomposer=_FakeDecomposer(_specs(1)),
    )
    loop = ProactiveCognitiveLoop(cooldown=0)
    loop.set_runtime(_make_proactive_rt(trust_score=trust_score, orchestrator=orch))
    agent = _make_agent("officer-1")

    text = "[CREW]coordinate the away team[/CREW]"
    _cleaned, actions = await loop._extract_and_execute_actions(agent, text)

    crew_actions = [a for a in actions if a.get("type") == "crew"]
    assert len(crew_actions) == 1


@pytest.mark.asyncio
async def test_proactive_missing_orchestrator_logs_and_skips(store):
    loop = ProactiveCognitiveLoop(cooldown=0)
    loop.set_runtime(_make_proactive_rt(trust_score=0.6, orchestrator=None))
    agent = _make_agent("lt-1")

    text = "[CREW]this has nowhere to go[/CREW]"
    cleaned, actions = await loop._extract_and_execute_actions(agent, text)

    # No raise; tag stripped; no crew action recorded.
    assert "[CREW]" not in cleaned
    assert [a for a in actions if a.get("type") == "crew"] == []
