"""AD-482 v1: Self-Improvement Pipeline tests.

Test classes:
  - TestStageContract       (4 tests, AD-482a)
  - TestCapabilityProposal  (4 tests, AD-482b)
  - TestPivotRefine         (3 tests, AD-482e)
  - TestApprovalGate        (6 tests, AD-482c)
  - TestEvolutionStore      (6 tests, AD-482d)
  - TestQAAgentPool         (7 tests, AD-482f)
  - TestVersioning          (3 tests, AD-482g)
  - TestPersistence         (4 tests, AD-482h)
  - TestShadowSeam          (2 tests, AD-482i)
  - TestConfigAndWiring     (2 tests)
  - TestIntegration         (1 test)

Total: 42 tests.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest

from probos.cognitive.self_improvement import (
    AgentVersion,
    AgentVersionStore,
    ApprovalGate,
    CapabilityProposal,
    EvolutionStore,
    IterationGuard,
    LocalDiskPersistence,
    NoOpShadowDeploymentPolicy,
    PivotRefineDecision,
    ProposalState,
    ProposalStore,
    QAAgentPool,
    ShadowComparisonResult,
    StageContract,
)
from probos.cognitive.self_improvement.versioning import compute_source_hash


# ---------------------------------------------------------------------------
# AD-482a StageContract
# ---------------------------------------------------------------------------

class TestStageContract:
    def test_validate_input_happy_path(self) -> None:
        contract = StageContract(
            name="discover",
            inputs={"query": str, "max_results": int},
            outputs={"hits": list},
            definition_of_done="At least one hit returned.",
        )
        ok, reason = contract.validate_input({"query": "foo", "max_results": 5})
        assert ok is True
        assert reason == ""

    def test_validate_input_missing_key(self) -> None:
        contract = StageContract(
            name="discover",
            inputs={"query": str},
            outputs={},
            definition_of_done="",
        )
        ok, reason = contract.validate_input({})
        assert ok is False
        assert "missing input key" in reason
        assert "'query'" in reason

    def test_validate_input_type_mismatch(self) -> None:
        contract = StageContract(
            name="discover",
            inputs={"query": str},
            outputs={},
            definition_of_done="",
        )
        ok, reason = contract.validate_input({"query": 42})
        assert ok is False
        assert "expected str" in reason
        assert "got int" in reason

    def test_validate_output_happy_path(self) -> None:
        contract = StageContract(
            name="discover",
            inputs={},
            outputs={"hits": list},
            definition_of_done="",
        )
        ok, reason = contract.validate_output({"hits": [1, 2, 3]})
        assert ok is True
        assert reason == ""


# ---------------------------------------------------------------------------
# AD-482b CapabilityProposal + ProposalStore
# ---------------------------------------------------------------------------

def _make_proposal(pid: str = "p1", **kwargs: Any) -> CapabilityProposal:
    defaults = dict(
        id=pid,
        source="repo",
        source_url="https://example.com/x",
        summary="A discovered capability.",
        relevance=0.8,
        fit_assessment="Good fit.",
        integration_effort_hours=4.0,
        dependencies=("foo", "bar"),
        license="Apache-2.0",
        submitted_at=0.0,
        submitter_agent_id="research_1",
    )
    defaults.update(kwargs)
    return CapabilityProposal(**defaults)


class TestCapabilityProposal:
    def test_submit_and_get(self) -> None:
        store = ProposalStore(clock=lambda: 1234.0)
        pid = store.submit(_make_proposal("p1"))
        assert pid == "p1"
        got = store.get("p1")
        assert got is not None
        assert got.summary == "A discovered capability."
        assert got.submitted_at == 1234.0  # stamped by clock

    def test_list_pending_filters_terminal(self) -> None:
        store = ProposalStore(iteration_cap=3)
        store.submit(_make_proposal("p1"))
        store.submit(_make_proposal("p2"))
        store.update_state("p1", ProposalState.APPROVED, rationale="ok")
        pending = store.list_pending()
        assert [p.id for p in pending] == ["p2"]

    def test_submit_emits_capability_proposal_created(self) -> None:
        events: list[tuple[str, dict[str, Any]]] = []
        store = ProposalStore(event_emit_fn=lambda name, payload: events.append((name, payload)))
        store.submit(_make_proposal("p1"))
        assert any(name == "CAPABILITY_PROPOSAL_CREATED" for name, _ in events)

    def test_submit_routes_terminal_lesson_to_callback(self) -> None:
        captured: list[tuple[str, str, str, str, dict[str, Any]]] = []

        def cb(category: str, summary: str, source_proposal_id: str,
               outcome: str, payload: dict[str, Any]) -> str:
            captured.append((category, summary, source_proposal_id, outcome, payload))
            return "lesson_1"

        store = ProposalStore(evolution_store_callback=cb)
        store.submit(_make_proposal("p1"))
        store.update_state("p1", ProposalState.APPROVED, rationale="captain approved")
        assert len(captured) == 1
        assert captured[0][0] == "approved"
        assert captured[0][2] == "p1"


# ---------------------------------------------------------------------------
# AD-482e PIVOT/REFINE + IterationGuard
# ---------------------------------------------------------------------------

class TestPivotRefine:
    def test_iteration_guard_caps_refine(self) -> None:
        guard = IterationGuard(max_iterations=2)
        assert guard.register(PivotRefineDecision.REFINE, now=1.0) is True
        assert guard.register(PivotRefineDecision.REFINE, now=2.0) is True
        assert guard.register(PivotRefineDecision.REFINE, now=3.0) is False
        assert len(guard.decisions) == 2

    def test_proposal_store_transition_emits_pivot_refine_decided(self) -> None:
        events: list[tuple[str, dict[str, Any]]] = []
        store = ProposalStore(event_emit_fn=lambda name, payload: events.append((name, payload)))
        store.submit(_make_proposal("p1"))
        ok = store.transition("p1", PivotRefineDecision.PIVOT, rationale="dead end")
        assert ok is True
        assert store.state("p1") is ProposalState.PIVOTED
        assert any(name == "PIVOT_REFINE_DECIDED" for name, _ in events)

    def test_artifact_versioning_records_history(self) -> None:
        guard = IterationGuard(max_iterations=5)
        guard.record_artifact("a1", "hash1")
        guard.record_artifact("a1", "hash2")
        assert guard.artifacts == [("a1", "hash1"), ("a1", "hash2")]


# ---------------------------------------------------------------------------
# AD-482c ApprovalGate
# ---------------------------------------------------------------------------

class TestApprovalGate:
    def test_enqueue_and_pending_count(self) -> None:
        store = ProposalStore()
        gate = ApprovalGate(proposal_store=store)
        gate.enqueue(_make_proposal("p1"))
        gate.enqueue(_make_proposal("p2"))
        assert gate.pending_count() == 2

    def test_approve_transitions_state(self) -> None:
        store = ProposalStore()
        gate = ApprovalGate(proposal_store=store)
        gate.enqueue(_make_proposal("p1"))
        ok = gate.approve("p1", approver="captain")
        assert ok is True
        assert store.state("p1") is ProposalState.APPROVED

    def test_approve_unknown_returns_false(self) -> None:
        gate = ApprovalGate(proposal_store=ProposalStore())
        assert gate.approve("missing", approver="captain") is False

    def test_reject_requires_reason(self) -> None:
        store = ProposalStore()
        gate = ApprovalGate(proposal_store=store)
        gate.enqueue(_make_proposal("p1"))
        assert gate.reject("p1", approver="captain", reason="") is False
        assert store.state("p1") is ProposalState.PENDING

    def test_reject_emits_capability_proposal_rejected(self) -> None:
        events: list[tuple[str, dict[str, Any]]] = []
        store = ProposalStore()
        gate = ApprovalGate(
            proposal_store=store,
            event_emit_fn=lambda name, payload: events.append((name, payload)),
        )
        gate.enqueue(_make_proposal("p1"))
        gate.reject("p1", approver="captain", reason="not aligned")
        assert any(name == "CAPABILITY_PROPOSAL_REJECTED" for name, _ in events)

    def test_audit_entries_filter_by_proposal_id(self) -> None:
        store = ProposalStore()
        gate = ApprovalGate(proposal_store=store, clock=lambda: 7.0)
        gate.enqueue(_make_proposal("p1"))
        gate.enqueue(_make_proposal("p2"))
        gate.approve("p1", approver="captain")
        gate.reject("p2", approver="captain", reason="duplicate")
        assert len(gate.audit_entries(proposal_id="p1")) == 1
        assert gate.audit_entries(proposal_id="p1")[0][1] == "approve"


# ---------------------------------------------------------------------------
# AD-482d EvolutionStore
# ---------------------------------------------------------------------------

class TestEvolutionStore:
    def test_record_lesson_in_memory_fallback(self) -> None:
        store = EvolutionStore(chroma_client=None)
        lid = store.record_lesson(
            "approved", "Integrated foo lib", "p1", "approved", {"k": "v"},
        )
        assert isinstance(lid, str) and len(lid) == 12

    def test_recall_substring_match_with_decay(self) -> None:
        clock_value = [1000.0]

        def clock() -> float:
            return clock_value[0]

        store = EvolutionStore(chroma_client=None, clock=clock, half_life_seconds=10.0)
        store.record_lesson("approved", "Integrated requests library", "p1", "approved", {})
        clock_value[0] = 1100.0  # 100s later (10 half-lives -> ~1/1024 weight)
        store.record_lesson("approved", "Skipped numpy migration", "p2", "approved", {})
        # "requests" matches lesson 1 substring; lesson 2 is recent. Recent dominates.
        results = store.recall("foo", top_k=2)
        assert len(results) == 2
        # Lesson 2 is more recent -> higher weight despite weaker similarity.
        assert results[0].source_proposal_id == "p2"

    def test_record_lesson_emits_evolution_lesson_recorded(self) -> None:
        events: list[tuple[str, dict[str, Any]]] = []
        store = EvolutionStore(
            chroma_client=None,
            event_emit_fn=lambda name, payload: events.append((name, payload)),
        )
        store.record_lesson("rejected", "X did not fit", "p3", "rejected", {})
        assert any(name == "EVOLUTION_LESSON_RECORDED" for name, _ in events)

    def test_start_with_chroma_client_opens_collection(self) -> None:
        client = MagicMock()
        store = EvolutionStore(chroma_client=client)
        store.start()
        assert client.get_or_create_collection.called

    def test_start_idempotent(self) -> None:
        client = MagicMock()
        store = EvolutionStore(chroma_client=client)
        store.start()
        store.start()
        # Only one collection-open call regardless of repeated start
        assert client.get_or_create_collection.call_count == 1

    def test_recall_returns_top_k_only(self) -> None:
        store = EvolutionStore(chroma_client=None)
        for i in range(7):
            store.record_lesson("approved", f"lesson {i}", f"p{i}", "approved", {})
        results = store.recall("lesson", top_k=3)
        assert len(results) == 3


# ---------------------------------------------------------------------------
# AD-482f QAAgentPool
# ---------------------------------------------------------------------------

class _FakeQAReport:
    def __init__(self, passed: bool) -> None:
        self.passed = passed


class _FakeQAAgent:
    def __init__(self, agent_id: str, passed: bool, *, raise_exc: bool = False) -> None:
        self.id = agent_id
        self._passed = passed
        self._raise = raise_exc

    async def smoke_test_record(self, candidate_record: Any) -> Any:
        if self._raise:
            raise RuntimeError("simulated qa failure")
        return _FakeQAReport(self._passed)


class TestQAAgentPool:
    def test_requires_at_least_one_agent(self) -> None:
        with pytest.raises(ValueError):
            QAAgentPool(qa_agents=[])

    @pytest.mark.asyncio
    async def test_evaluate_proposal_all_pass(self) -> None:
        pool = QAAgentPool(
            qa_agents=[_FakeQAAgent("qa1", True), _FakeQAAgent("qa2", True), _FakeQAAgent("qa3", True)],
        )
        eval_ = await pool.evaluate_proposal(
            proposal_id="p1", candidate_record=SimpleNamespace(),
        )
        assert eval_.pass_count == 3
        assert eval_.fail_count == 0
        assert eval_.overall_pass is True

    @pytest.mark.asyncio
    async def test_evaluate_proposal_majority_pass(self) -> None:
        pool = QAAgentPool(
            qa_agents=[_FakeQAAgent("qa1", True), _FakeQAAgent("qa2", True), _FakeQAAgent("qa3", False)],
        )
        eval_ = await pool.evaluate_proposal(
            proposal_id="p1", candidate_record=SimpleNamespace(),
        )
        assert eval_.pass_count == 2
        assert eval_.fail_count == 1
        assert eval_.overall_pass is True

    @pytest.mark.asyncio
    async def test_evaluate_proposal_minority_pass_overall_fail(self) -> None:
        pool = QAAgentPool(
            qa_agents=[_FakeQAAgent("qa1", True), _FakeQAAgent("qa2", False), _FakeQAAgent("qa3", False)],
        )
        eval_ = await pool.evaluate_proposal(
            proposal_id="p1", candidate_record=SimpleNamespace(),
        )
        assert eval_.overall_pass is False

    @pytest.mark.asyncio
    async def test_evaluate_proposal_qa_exception_counts_as_fail(self) -> None:
        pool = QAAgentPool(
            qa_agents=[_FakeQAAgent("qa1", True), _FakeQAAgent("qa2", True, raise_exc=True)],
        )
        eval_ = await pool.evaluate_proposal(
            proposal_id="p1", candidate_record=SimpleNamespace(),
        )
        assert eval_.per_agent_outcomes["qa2"] is False

    @pytest.mark.asyncio
    async def test_evaluate_proposal_shapley_contributions_sum_to_about_one(self) -> None:
        pool = QAAgentPool(
            qa_agents=[_FakeQAAgent("qa1", True), _FakeQAAgent("qa2", True), _FakeQAAgent("qa3", True)],
        )
        eval_ = await pool.evaluate_proposal(
            proposal_id="p1", candidate_record=SimpleNamespace(),
        )
        total = sum(eval_.shapley_contributions.values())
        assert 0.99 <= total <= 1.01

    @pytest.mark.asyncio
    async def test_size_property(self) -> None:
        pool = QAAgentPool(qa_agents=[_FakeQAAgent("qa1", True)])
        assert pool.size == 1


# ---------------------------------------------------------------------------
# AD-482g Versioning
# ---------------------------------------------------------------------------

def _make_version(version: int = 1, parent: int | None = None) -> AgentVersion:
    return AgentVersion(
        version=version,
        parent_version=parent,
        designed_at=1000.0,
        designer="captain",
        trust_alpha_at_promotion=1.0,
        trust_beta_at_promotion=3.0,
        source_hash=compute_source_hash(f"src_v{version}"),
    )


class TestVersioning:
    def test_register_and_latest(self) -> None:
        store = AgentVersionStore()
        store.register_version("foo_agent", _make_version(1))
        store.register_version("foo_agent", _make_version(2, parent=1))
        latest = store.latest("foo_agent")
        assert latest is not None
        assert latest.version == 2
        assert latest.parent_version == 1

    def test_history_returns_copy(self) -> None:
        store = AgentVersionStore()
        store.register_version("foo_agent", _make_version(1))
        history = store.history("foo_agent")
        history.append(_make_version(99))  # mutate copy
        assert len(store.history("foo_agent")) == 1

    def test_register_version_emits_agent_version_promoted(self) -> None:
        events: list[tuple[str, dict[str, Any]]] = []
        store = AgentVersionStore(event_emit_fn=lambda name, payload: events.append((name, payload)))
        store.register_version("foo_agent", _make_version(1))
        assert any(name == "AGENT_VERSION_PROMOTED" for name, _ in events)


# ---------------------------------------------------------------------------
# AD-482h LocalDiskPersistence
# ---------------------------------------------------------------------------

class TestPersistence:
    @pytest.mark.asyncio
    async def test_promote_writes_source_and_sidecar(self, tmp_path: Path) -> None:
        persistence = LocalDiskPersistence(root_dir=str(tmp_path))
        record = SimpleNamespace(agent_type="foo_agent", source_code="def x():\n    pass\n")
        version = _make_version(1)
        path = await persistence.promote(record, version)
        assert path
        assert (tmp_path / "foo_agent_v1.py").read_text() == "def x():\n    pass\n"
        meta_text = (tmp_path / "foo_agent_v1.meta.yaml").read_text()
        assert "agent_type: foo_agent" in meta_text
        assert "version: 1" in meta_text

    @pytest.mark.asyncio
    async def test_promote_skips_when_record_missing_fields(self, tmp_path: Path) -> None:
        persistence = LocalDiskPersistence(root_dir=str(tmp_path))
        record = SimpleNamespace(agent_type="", source_code="")
        version = _make_version(1)
        path = await persistence.promote(record, version)
        assert path == ""
        assert not list(tmp_path.iterdir())

    @pytest.mark.asyncio
    async def test_promote_handles_oserror_log_and_degrade(self, tmp_path: Path) -> None:
        # Point root_dir at an existing FILE so mkdir fails
        bad_path = tmp_path / "blocker"
        bad_path.write_text("blocker")
        persistence = LocalDiskPersistence(root_dir=str(bad_path / "designed"))
        record = SimpleNamespace(agent_type="foo_agent", source_code="x")
        version = _make_version(1)
        path = await persistence.promote(record, version)
        assert path == ""

    def test_compute_source_hash_stable(self) -> None:
        h1 = compute_source_hash("foo")
        h2 = compute_source_hash("foo")
        assert h1 == h2
        assert len(h1) == 16


# ---------------------------------------------------------------------------
# AD-482i Shadow Deployment seam
# ---------------------------------------------------------------------------

class TestShadowSeam:
    @pytest.mark.asyncio
    async def test_noop_returns_none(self) -> None:
        policy = NoOpShadowDeploymentPolicy()
        result = await policy.shadow_compare(
            baseline_version=_make_version(1),
            candidate_version=_make_version(2, parent=1),
            runtime=SimpleNamespace(),
        )
        assert result is None

    def test_shadow_comparison_result_dataclass_shape(self) -> None:
        result = ShadowComparisonResult(
            baseline_version=1,
            candidate_version=2,
            baseline_score=0.7,
            candidate_score=0.9,
            sample_size=50,
            confident_winner=2,
        )
        assert result.confident_winner == 2


# ---------------------------------------------------------------------------
# Config + wiring
# ---------------------------------------------------------------------------

class TestConfigAndWiring:
    def test_config_default_disabled(self) -> None:
        from probos.config import SelfImprovementConfig

        cfg = SelfImprovementConfig()
        assert cfg.enabled is False
        assert cfg.qa_pool_size == 3
        assert cfg.iteration_cap == 5
        assert cfg.evolution_collection_name == "self_improvement_lessons"

    def test_wirer_skips_when_disabled(self) -> None:
        from probos.config import SystemConfig
        from probos.startup.finalize import _wire_self_improvement

        runtime = SimpleNamespace(
            _chroma_client=None,
            spawner=None,
            emit_event=None,
            proposal_store=None,
            approval_gate=None,
            evolution_store=None,
            qa_agent_pool=None,
            agent_version_store=None,
            agent_persistence=None,
            shadow_deployment_policy=None,
        )
        config = SystemConfig()
        wired = _wire_self_improvement(runtime=runtime, config=config)
        assert wired is False
        assert runtime.proposal_store is None


# ---------------------------------------------------------------------------
# Integration -- proposal -> approve -> evolution lesson -> version -> persist
# ---------------------------------------------------------------------------

class TestIntegration:
    @pytest.mark.asyncio
    async def test_full_lifecycle(self, tmp_path: Path) -> None:
        events: list[tuple[str, dict[str, Any]]] = []

        def emit(name: str, payload: dict[str, Any]) -> None:
            events.append((name, payload))

        # Wire pipeline manually (skip wirer; default-False)
        evolution = EvolutionStore(chroma_client=None, event_emit_fn=emit)
        proposals = ProposalStore(
            evolution_store_callback=evolution.record_lesson,
            event_emit_fn=emit,
        )
        gate = ApprovalGate(proposal_store=proposals, event_emit_fn=emit)
        versions = AgentVersionStore(event_emit_fn=emit)
        persistence = LocalDiskPersistence(root_dir=str(tmp_path))

        # Submit + approve
        proposal = _make_proposal(
            "p1", summary="Add foo_agent capability", submitted_at=0.0,
        )
        gate.enqueue(proposal)
        assert gate.approve("p1", approver="captain") is True
        assert proposals.state("p1") is ProposalState.APPROVED

        # Lesson should have been emitted on approval
        names = [n for n, _ in events]
        assert "CAPABILITY_PROPOSAL_CREATED" in names
        assert "CAPABILITY_PROPOSAL_APPROVED" in names
        assert "EVOLUTION_LESSON_RECORDED" in names

        # Register version + promote
        version = _make_version(1)
        versions.register_version("foo_agent", version)
        record = SimpleNamespace(agent_type="foo_agent", source_code="def x(): pass\n")
        persisted_path = await persistence.promote(record, version)
        assert persisted_path
        assert (tmp_path / "foo_agent_v1.py").exists()
        assert (tmp_path / "foo_agent_v1.meta.yaml").exists()

        # Recall should surface the approval lesson
        hits = evolution.recall("foo_agent capability", top_k=3)
        assert hits  # at least one lesson recalled
        assert hits[0].source_proposal_id == "p1"
