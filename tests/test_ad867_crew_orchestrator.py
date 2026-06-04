"""AD-867: :class:`CrewOrchestrator` threads the full crew pipeline.

``CrewOrchestrator`` wires the dormant crew stages — AD-864 assignment resolver,
AD-865 delegator, AD-859 executor, AD-860 verifier, AD-861 synthesizer — into one
end-to-end flow (resolve -> delegate -> fan-out -> verify -> synthesize) behind a
single ``run_crew_task`` entry point, gated by ``orchestrator_enabled`` (default
OFF) and triggered as a *held* task by ``maybe_dispatch_crew`` only for >1-child
parents.

Per BF-287 these tests use a REAL :class:`WorkItemStore` (so a phantom attribute
on the substrate boundary cannot hide behind a MagicMock); the stage collaborators
are small ``_Fake*`` stubs that return the REAL decision/verdict/result/outcome
dataclasses with the exact public shapes the orchestrator calls.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import asyncio

import pytest

from probos.cognitive.crew_assignment import AssignmentDecision
from probos.cognitive.crew_delegation import DelegationDecision
from probos.cognitive.crew_executor import SubtaskResult
from probos.cognitive.crew_orchestrator import CrewOrchestrator
from probos.cognitive.crew_synth import SynthesisResult
from probos.cognitive.crew_verifier import VerificationVerdict
from probos.config import SystemConfig
from probos.events import EventType
from probos.workforce import WorkItemStore


# ------------------------------------------------------------------ fakes


class _FakeResolver:
    """Maps a spec to an :class:`AssignmentDecision`. ``workers`` keys off the
    spec's ``capability`` echo via ``spec_id`` so a per-child worker (or ``None``
    for an unresolved child) can be scripted."""

    def __init__(self, workers: dict[str, str | None] | None = None,
                 default_worker: str | None = "worker-default") -> None:
        self._workers = workers or {}
        self._default = default_worker
        self.calls: list[Any] = []

    def resolve(self, spec: Any) -> AssignmentDecision:
        self.calls.append(spec)
        worker = self._workers.get(spec.spec_id, self._default)
        return AssignmentDecision(
            spec_id=spec.spec_id,
            agent_id=worker,
            department=spec.department,
            capability=spec.capability,
            score=1.0 if worker else 0.0,
            reason="capability_match" if worker else "unresolved",
        )


class _FakeDelegator:
    """Routes an :class:`AssignmentDecision` through a (fake) chief, carrying the
    worker through unless it was unresolved."""

    def __init__(self) -> None:
        self.calls: list[Any] = []

    def delegate(self, decision: AssignmentDecision) -> DelegationDecision:
        self.calls.append(decision)
        if decision.agent_id is None:
            return DelegationDecision(
                spec_id=decision.spec_id,
                chief_agent_id=None,
                worker_agent_id=None,
                order_id=None,
                delegated=False,
                reason="unresolved",
            )
        return DelegationDecision(
            spec_id=decision.spec_id,
            chief_agent_id="chief-1",
            worker_agent_id=decision.agent_id,
            order_id="order-1",
            delegated=True,
            reason="delegated_via_chief",
        )


class _FakeExecutor:
    """``async run(parent_id) -> list[SubtaskResult]``. Returns scripted results,
    or raises when ``fail`` is set (to exercise honest-degrade)."""

    def __init__(self, results: list[SubtaskResult] | None = None,
                 fail: bool = False) -> None:
        self._results = results or []
        self._fail = fail
        self.calls: list[str] = []

    async def run(self, parent_id: str) -> list[SubtaskResult]:
        self.calls.append(parent_id)
        if self._fail:
            raise RuntimeError("executor boom")
        return list(self._results)


class _FakeVerifier:
    """``async verify(result) -> VerificationVerdict``. Accepts by default;
    ``refute`` lists ``work_item_id``s to reject; ``fail`` raises for all."""

    def __init__(self, refute: set[str] | None = None, fail: bool = False) -> None:
        self._refute = refute or set()
        self._fail = fail
        self.calls: list[Any] = []

    async def verify(self, result: SubtaskResult) -> VerificationVerdict:
        self.calls.append(result)
        if self._fail:
            raise RuntimeError("verifier boom")
        accepted = result.work_item_id not in self._refute
        return VerificationVerdict(
            accepted=accepted,
            confidence=0.9,
            critique="ok" if accepted else "flawed",
            verifier_agent_id="verifier-1",
        )


class _FakeSynth:
    """``async synthesize(parent_id, outcomes) -> SynthesisResult``. Records the
    call args; optionally completes the parent (mirrors AD-861's in_progress->done
    completion) or raises to exercise the partial-result path."""

    def __init__(self, store: WorkItemStore | None = None,
                 complete_parent: bool = False, fail: bool = False) -> None:
        self._store = store
        self._complete = complete_parent
        self._fail = fail
        self.calls: list[tuple[str, list[Any]]] = []

    async def synthesize(self, parent_id: str, outcomes: list[Any]) -> SynthesisResult:
        self.calls.append((parent_id, list(outcomes)))
        if self._fail:
            raise RuntimeError("synth boom")
        if self._complete and self._store is not None:
            await self._store.transition_work_item(parent_id, "done", source="test")
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
        db_path=str(tmp_path / "crew_orch.db"),
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


async def _make_dag(store: WorkItemStore, n_children: int, *, with_hints: bool = True):
    """Create an ``open`` task parent with ``n_children`` ``open`` task children."""
    parent = await store.create_work_item(title="parent", work_type="task")
    children = []
    for i in range(n_children):
        md = (
            {"spec_id": f"spec-{i}", "capability": "analysis", "department": "science"}
            if with_hints
            else {}
        )
        child = await store.create_work_item(
            title=f"child {i}", work_type="task", parent_id=parent.id, metadata=md,
        )
        children.append(child)
    return parent, children


def _make_orch(
    *,
    store: WorkItemStore,
    config: SystemConfig,
    resolver: Any = None,
    delegator: Any = None,
    executor: Any = None,
    verifier: Any = None,
    synthesizer: Any = None,
    emit_fn: Any = None,
) -> CrewOrchestrator:
    return CrewOrchestrator(
        assignment_resolver=resolver or _FakeResolver(),
        delegator=delegator or _FakeDelegator(),
        crew_executor=executor or _FakeExecutor([]),
        verifier=verifier or _FakeVerifier(),
        synthesizer=synthesizer or _FakeSynth(store),
        work_item_store=store,
        runtime=SimpleNamespace(),
        emit_fn=emit_fn,
        config=config,
    )


def _result(child_id: str, spec_id: str, *, status: str = "done",
            agent: str = "worker-default") -> SubtaskResult:
    return SubtaskResult(
        work_item_id=child_id,
        spec_id=spec_id,
        agent_id=agent,
        output=f"output for {child_id}",
        status=status,
    )


# ------------------------------------------------------------------ pipeline


@pytest.mark.asyncio
async def test_run_crew_task_end_to_end_completes_parent(store):
    parent, children = await _make_dag(store, 3)
    results = [_result(c.id, f"spec-{i}") for i, c in enumerate(children)]
    synth = _FakeSynth(store, complete_parent=True)
    orch = _make_orch(
        store=store, config=_config(enabled=True),
        executor=_FakeExecutor(results), synthesizer=synth,
    )

    out = await orch.run_crew_task(parent.id)

    assert isinstance(out, SynthesisResult)
    assert out.completed is True
    assert out.total_count == 3
    reloaded = await store.get_work_item(parent.id)
    assert reloaded is not None and reloaded.status == "done"
    # Every child got an assigned worker + provenance.
    for child in children:
        rc = await store.get_work_item(child.id)
        assert rc is not None and rc.assigned_to == "worker-default"
        assert rc.metadata.get("delegated") is True


@pytest.mark.asyncio
async def test_unresolved_child_degrades_without_aborting_siblings(store):
    parent, children = await _make_dag(store, 3)
    # spec-1 resolves to nobody.
    resolver = _FakeResolver(workers={"spec-1": None}, default_worker="worker-X")
    orch = _make_orch(store=store, config=_config(enabled=True), resolver=resolver)

    out = await orch.run_crew_task(parent.id)

    assert isinstance(out, SynthesisResult)
    rc0 = await store.get_work_item(children[0].id)
    rc1 = await store.get_work_item(children[1].id)
    rc2 = await store.get_work_item(children[2].id)
    assert rc0.assigned_to == "worker-X"
    assert rc1.assigned_to is None  # unresolved -> left unassigned
    assert rc2.assigned_to == "worker-X"


@pytest.mark.asyncio
async def test_verifier_refuted_child_marked_unverified(store):
    parent, children = await _make_dag(store, 2)
    results = [_result(c.id, f"spec-{i}") for i, c in enumerate(children)]
    verifier = _FakeVerifier(refute={children[0].id})
    synth = _FakeSynth(store)
    orch = _make_orch(
        store=store, config=_config(enabled=True),
        executor=_FakeExecutor(results), verifier=verifier, synthesizer=synth,
    )

    await orch.run_crew_task(parent.id)

    _pid, outcomes = synth.calls[0]
    statuses = {o.result.work_item_id: o.status for o in outcomes}
    assert statuses[children[0].id] == "unverified"
    assert statuses[children[1].id] == "converged"


@pytest.mark.asyncio
async def test_failed_subtask_skipped_in_verification(store):
    parent, children = await _make_dag(store, 2)
    results = [
        _result(children[0].id, "spec-0", status="done"),
        _result(children[1].id, "spec-1", status="failed"),
    ]
    verifier = _FakeVerifier()
    synth = _FakeSynth(store)
    orch = _make_orch(
        store=store, config=_config(enabled=True),
        executor=_FakeExecutor(results), verifier=verifier, synthesizer=synth,
    )

    await orch.run_crew_task(parent.id)

    # The failed subtask is never sent to the verifier and never reaches synthesis.
    assert len(verifier.calls) == 1
    _pid, outcomes = synth.calls[0]
    assert [o.result.work_item_id for o in outcomes] == [children[0].id]


@pytest.mark.asyncio
async def test_synthesize_called_with_parent_id_and_outcomes(store):
    parent, children = await _make_dag(store, 2)
    results = [_result(c.id, f"spec-{i}") for i, c in enumerate(children)]
    synth = _FakeSynth(store)
    orch = _make_orch(
        store=store, config=_config(enabled=True),
        executor=_FakeExecutor(results), synthesizer=synth,
    )

    await orch.run_crew_task(parent.id)

    assert len(synth.calls) == 1
    pid, outcomes = synth.calls[0]
    assert pid == parent.id
    assert len(outcomes) == 2


@pytest.mark.asyncio
async def test_update_work_item_writes_assigned_to_and_provenance(store):
    parent, children = await _make_dag(store, 1)
    # 1 child won't trigger maybe_dispatch, but run_crew_task assigns directly.
    orch = _make_orch(store=store, config=_config(enabled=True))

    await orch.run_crew_task(parent.id)

    rc = await store.get_work_item(children[0].id)
    assert rc.assigned_to == "worker-default"
    md = rc.metadata
    assert md.get("chief_agent_id") == "chief-1"
    assert md.get("order_id") == "order-1"
    assert md.get("delegated") is True
    assert md.get("delegation_reason") == "delegated_via_chief"
    assert md.get("assigned_capability") == "analysis"
    assert md.get("assigned_department") == "science"


@pytest.mark.asyncio
async def test_promote_parent_open_to_in_progress(store):
    parent, _children = await _make_dag(store, 2)
    # A synth that does NOT complete the parent leaves it in_progress.
    orch = _make_orch(store=store, config=_config(enabled=True),
                      synthesizer=_FakeSynth(store, complete_parent=False))

    await orch.run_crew_task(parent.id)

    reloaded = await store.get_work_item(parent.id)
    assert reloaded.status == "in_progress"


# ---------------------------------------------------------------- honest-degrade


@pytest.mark.asyncio
async def test_synthesizer_failure_surfaces_partial_never_raises(store):
    parent, children = await _make_dag(store, 2)
    results = [_result(c.id, f"spec-{i}") for i, c in enumerate(children)]
    synth = _FakeSynth(store, fail=True)
    orch = _make_orch(
        store=store, config=_config(enabled=True),
        executor=_FakeExecutor(results), synthesizer=synth,
    )

    out = await orch.run_crew_task(parent.id)

    assert isinstance(out, SynthesisResult)
    assert out.completed is False
    assert out.final_output == ""
    assert out.total_count == 2  # outcomes count carried into the partial


@pytest.mark.asyncio
async def test_executor_failure_degrades_to_empty(store):
    parent, _children = await _make_dag(store, 2)
    synth = _FakeSynth(store)
    orch = _make_orch(
        store=store, config=_config(enabled=True),
        executor=_FakeExecutor(fail=True), synthesizer=synth,
    )

    out = await orch.run_crew_task(parent.id)

    assert isinstance(out, SynthesisResult)
    _pid, outcomes = synth.calls[0]
    assert outcomes == []


@pytest.mark.asyncio
async def test_missing_parent_degrades_to_empty_synthesis(store):
    synth = _FakeSynth(store)
    orch = _make_orch(store=store, config=_config(enabled=True), synthesizer=synth)

    out = await orch.run_crew_task("does-not-exist")

    assert isinstance(out, SynthesisResult)
    pid, outcomes = synth.calls[0]
    assert pid == "does-not-exist"
    assert outcomes == []


# ------------------------------------------------------------------ trigger gate


@pytest.mark.asyncio
async def test_orchestrator_disabled_no_ops(store):
    parent, _children = await _make_dag(store, 3)
    orch = _make_orch(store=store, config=_config(enabled=False))

    task = await orch.maybe_dispatch_crew(parent.id)

    assert task is None
    assert orch._tasks == set()


@pytest.mark.asyncio
async def test_single_spec_parent_skips_crew_path(store):
    parent, _children = await _make_dag(store, 1)
    orch = _make_orch(store=store, config=_config(enabled=True))

    task = await orch.maybe_dispatch_crew(parent.id)

    assert task is None


@pytest.mark.asyncio
async def test_maybe_dispatch_holds_task_reference(store):
    parent, children = await _make_dag(store, 2)
    results = [_result(c.id, f"spec-{i}") for i, c in enumerate(children)]
    synth = _FakeSynth(store, complete_parent=True)
    orch = _make_orch(
        store=store, config=_config(enabled=True),
        executor=_FakeExecutor(results), synthesizer=synth,
    )

    task = await orch.maybe_dispatch_crew(parent.id)

    # Held reference (no fire-and-forget): the task is tracked while pending.
    assert isinstance(task, asyncio.Task)
    assert task in orch._tasks
    out = await task
    assert isinstance(out, SynthesisResult)
    # The done-callback discards the completed task from the held set.
    await asyncio.sleep(0)
    assert task not in orch._tasks


# ------------------------------------------------------------------ events


@pytest.mark.asyncio
async def test_emit_events_fire(store):
    parent, _children = await _make_dag(store, 2)
    events: list[tuple[Any, dict[str, Any]]] = []

    def _emit(event_type: Any, data: dict[str, Any]) -> None:
        events.append((event_type, data))

    orch = _make_orch(store=store, config=_config(enabled=True), emit_fn=_emit)

    await orch.run_crew_task(parent.id)

    started = [d for et, d in events if et == EventType.CREW_ORCHESTRATION_STARTED]
    assert len(started) == 1
    assert started[0]["parent_id"] == parent.id
    assert started[0]["child_count"] == 2


@pytest.mark.asyncio
async def test_emit_failure_does_not_break_pipeline(store):
    parent, children = await _make_dag(store, 2)
    results = [_result(c.id, f"spec-{i}") for i, c in enumerate(children)]

    def _emit(event_type: Any, data: dict[str, Any]) -> None:
        raise RuntimeError("emit boom")

    orch = _make_orch(
        store=store, config=_config(enabled=True),
        executor=_FakeExecutor(results), emit_fn=_emit,
    )

    out = await orch.run_crew_task(parent.id)

    assert isinstance(out, SynthesisResult)


# ------------------------------------------------------------------ wirer


def test_wirer_attaches_orchestrator_when_enabled():
    from probos.startup.finalize import _wire_crew_orchestrator

    cfg = _config(enabled=True)
    runtime = SimpleNamespace(
        work_item_store=MagicMock(),
        registry=MagicMock(),
        capability_registry=MagicMock(),
        ontology=MagicMock(),
        trust_network=MagicMock(),
        llm_client=MagicMock(),
        order_manager=MagicMock(),
        episodic_memory=MagicMock(),
        emit_event=lambda *a, **k: None,
    )

    ok = _wire_crew_orchestrator(runtime=runtime, config=cfg)

    assert ok is True
    assert isinstance(runtime.crew_orchestrator, CrewOrchestrator)


def test_wirer_skips_when_flag_off():
    from probos.startup.finalize import _wire_crew_orchestrator

    cfg = _config(enabled=False)
    runtime = SimpleNamespace(
        work_item_store=MagicMock(),
        registry=MagicMock(),
        capability_registry=MagicMock(),
        ontology=MagicMock(),
        trust_network=MagicMock(),
        llm_client=MagicMock(),
    )

    ok = _wire_crew_orchestrator(runtime=runtime, config=cfg)

    assert ok is False
    assert not hasattr(runtime, "crew_orchestrator")


def test_wirer_skips_when_dependency_missing(caplog):
    from probos.startup.finalize import _wire_crew_orchestrator

    cfg = _config(enabled=True)
    runtime = SimpleNamespace(
        work_item_store=None,
        registry=MagicMock(),
        capability_registry=MagicMock(),
        ontology=MagicMock(),
        trust_network=MagicMock(),
        llm_client=MagicMock(),
    )

    with caplog.at_level("INFO"):
        ok = _wire_crew_orchestrator(runtime=runtime, config=cfg)

    assert ok is False
    assert not hasattr(runtime, "crew_orchestrator")
    assert any("missing dependencies" in r.message for r in caplog.records)
