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

import re
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import chromadb
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
from probos.knowledge.embeddings import get_embedding_backend_id
from tests.fixtures.bf662_embedding_fakes import (
    BF662EmbeddingFunctionA,
    BF662EmbeddingFunctionB,
)


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


@contextmanager
def _patched_evolution_backend(embedding_function):
    backend_id = get_embedding_backend_id(embedding_function)
    with (
        patch(
            "probos.knowledge.embeddings.get_collection_embedding_function",
            return_value=embedding_function,
        ),
        patch(
            "probos.knowledge.embeddings.get_active_embedding_model_name",
            return_value=embedding_function.name(),
        ),
        patch(
            "probos.knowledge.embeddings.get_active_embedding_backend_id",
            return_value=backend_id,
        ),
    ):
        yield backend_id


def _raw_dump(client: Any, name: str) -> dict[str, Any]:
    collection = client.get_collection(name=name, embedding_function=None)
    return collection.get(include=["documents", "metadatas"])


def _names(client: Any) -> set[str]:
    return {collection.name for collection in client.list_collections()}


def _collection_snapshot(client: Any) -> dict[str, dict[str, Any]]:
    snapshot: dict[str, dict[str, Any]] = {}
    for name in sorted(_names(client)):
        collection = client.get_collection(name=name, embedding_function=None)
        result = collection.get(include=["documents", "metadatas"])
        rows = sorted(
            (
                str(row_id),
                str(document),
                dict(metadata or {}),
            )
            for row_id, document, metadata in zip(
                result.get("ids") or [],
                result.get("documents") or [],
                result.get("metadatas") or [],
                strict=True,
            )
        )
        snapshot[name] = {
            "count": collection.count(),
            "collection_metadata": dict(collection.metadata or {}),
            "rows": rows,
        }
    return snapshot


def _bf662_temporary_metadata(
    store: EvolutionStore,
    embedding_function: Any,
    *,
    txn: str,
    role: str,
    state: str,
    source_count: Any,
) -> dict[str, Any]:
    return {
        "embedding_model": embedding_function.name(),
        "embedding_backend_id": get_embedding_backend_id(embedding_function),
        "bf662_canonical_name": store._collection_name,
        "bf662_owner": store._owner,
        "bf662_txn": txn,
        "bf662_role": role,
        "bf662_state": state,
        "bf662_source_count": source_count,
    }


def _seed_evolution_store(
    path: Path,
    embedding_function: Any,
    *,
    collection_name: str = "self_improvement_lessons",
) -> tuple[str, dict[str, Any]]:
    with _patched_evolution_backend(embedding_function):
        store = EvolutionStore(
            chroma_path=path,
            collection_name=collection_name,
            clock=lambda: 1234.5,
        )
        store.start()
        try:
            lesson_id = store.record_lesson(
                "approved",
                "Preserve exact evolution lesson fields",
                "proposal-662",
                "approved",
                {"not": "persisted"},
            )
            assert store._collection is not None
            before = store._collection.get(include=["documents", "metadatas"])
        finally:
            store.stop()
    return lesson_id, before


def _leave_candidate_and_backup(
    path: Path,
) -> dict[str, Any]:
    _, before = _seed_evolution_store(path, BF662EmbeddingFunctionA())
    with _patched_evolution_backend(BF662EmbeddingFunctionB()):
        with patch.object(
            EvolutionStore,
            "_prove_active_candidate",
            side_effect=RuntimeError("leave candidate and backup for recovery"),
        ):
            interrupted = EvolutionStore(chroma_path=path)
            try:
                interrupted.start()
                assert interrupted._collection is None
            finally:
                interrupted.stop()
    return before


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
        assert client.create_collection.called

    def test_start_idempotent(self) -> None:
        client = MagicMock()
        store = EvolutionStore(chroma_client=client)
        store.start()
        store.start()
        # Only one collection-open call regardless of repeated start
        assert client.create_collection.call_count == 1

    def test_recall_returns_top_k_only(self) -> None:
        store = EvolutionStore(chroma_client=None)
        for i in range(7):
            store.record_lesson("approved", f"lesson {i}", f"p{i}", "approved", {})
        results = store.recall("lesson", top_k=3)
        assert len(results) == 3


class TestBF662EvolutionTransitions:
    @pytest.mark.asyncio
    async def test_runtime_wiring_uses_public_data_dir_not_phantom_client(
        self, tmp_path: Path
    ) -> None:
        from probos.config import SystemConfig
        from probos.startup.finalize import _wire_self_improvement

        runtime = SimpleNamespace(
            data_dir=tmp_path,
            emit_event=None,
            spawner=None,
            codebase_index=None,
        )
        config = SystemConfig(
            self_improvement={"enabled": True, "persistence_root_dir": str(tmp_path / "versions")}
        )
        with patch(
            "probos.cognitive.self_improvement.EvolutionStore"
        ) as evolution_type:
            evolution = evolution_type.return_value
            evolution.record_lesson = MagicMock(return_value="lesson")
            assert await _wire_self_improvement(runtime=runtime, config=config) is True
        kwargs = evolution_type.call_args.kwargs
        assert kwargs["chroma_path"] == tmp_path
        assert "chroma_client" not in kwargs
        evolution.start.assert_called_once_with()

    def test_transition_a_to_b_preserves_persisted_lesson_fields(
        self, tmp_path: Path
    ) -> None:
        path = tmp_path / "a-to-b"
        lesson_id, before = _seed_evolution_store(path, BF662EmbeddingFunctionA())
        with _patched_evolution_backend(BF662EmbeddingFunctionB()) as backend_id:
            store = EvolutionStore(chroma_path=path)
            store.start()
            try:
                assert store._collection is not None
                after = store._collection.get(include=["documents", "metadatas"])
                assert after == before
                assert store._collection.metadata["embedding_backend_id"] == backend_id
                assert store._collection.metadata["bf662_state"] == "stable"
                hits = store.recall("exact evolution lesson", top_k=1)
                assert [lesson.id for lesson in hits] == [lesson_id]
                assert hits[0].category == "approved"
                assert hits[0].source_proposal_id == "proposal-662"
                assert hits[0].outcome == "approved"
                assert hits[0].timestamp == 1234.5
            finally:
                store.stop()

    def test_transition_b_to_a_preserves_persisted_lesson_fields(
        self, tmp_path: Path
    ) -> None:
        path = tmp_path / "b-to-a"
        lesson_id, before = _seed_evolution_store(path, BF662EmbeddingFunctionB())
        with _patched_evolution_backend(BF662EmbeddingFunctionA()):
            store = EvolutionStore(chroma_path=path)
            store.start()
            try:
                assert store._collection is not None
                assert store._collection.get(
                    include=["documents", "metadatas"]
                ) == before
                assert store.recall("Preserve exact", top_k=1)[0].id == lesson_id
            finally:
                store.stop()

    def test_mid_copy_failure_preserves_original_canonical(
        self, tmp_path: Path
    ) -> None:
        path = tmp_path / "mid-copy"
        _, before = _seed_evolution_store(path, BF662EmbeddingFunctionA())
        with _patched_evolution_backend(BF662EmbeddingFunctionB()):
            with patch.object(
                EvolutionStore,
                "_read_rows_by_ids",
                side_effect=RuntimeError("injected copy proof failure"),
            ):
                failed = EvolutionStore(chroma_path=path)
                failed.start()
                assert failed._collection is None
                assert failed._client is None

            client = chromadb.PersistentClient(path=str(path))
            try:
                names = _names(client)
                assert "self_improvement_lessons" in names
                assert _raw_dump(client, "self_improvement_lessons") == before
                assert len([name for name in names if name.startswith("bf662e-s-")]) == 1
            finally:
                client.close()

            recovered = EvolutionStore(chroma_path=path)
            recovered.start()
            try:
                assert recovered._collection is not None
                assert recovered._collection.get(
                    include=["documents", "metadatas"]
                ) == before
                assert not any(
                    name.startswith("bf662e-")
                    for name in _names(recovered._client)
                )
            finally:
                recovered.stop()

    def test_first_rename_failure_preserves_original_canonical(
        self, tmp_path: Path
    ) -> None:
        path = tmp_path / "first-rename"
        _, before = _seed_evolution_store(path, BF662EmbeddingFunctionA())
        with _patched_evolution_backend(BF662EmbeddingFunctionB()):
            with patch.object(
                EvolutionStore,
                "_rename_collection",
                side_effect=RuntimeError("injected first rename failure"),
            ):
                failed = EvolutionStore(chroma_path=path)
                failed.start()
                assert failed._collection is None

            client = chromadb.PersistentClient(path=str(path))
            try:
                names = _names(client)
                assert "self_improvement_lessons" in names
                assert _raw_dump(client, "self_improvement_lessons") == before
                assert not any(name.startswith("bf662e-b-") for name in names)
            finally:
                client.close()

            recovered = EvolutionStore(chroma_path=path)
            recovered.start()
            try:
                assert recovered._collection is not None
                assert recovered._collection.get(
                    include=["documents", "metadatas"]
                ) == before
            finally:
                recovered.stop()

    def test_second_rename_failure_recovery_without_canonical_finishes_or_restores_from_backup(
        self, tmp_path: Path
    ) -> None:
        path = tmp_path / "backup-shadow"
        _, before = _seed_evolution_store(path, BF662EmbeddingFunctionA())
        calls = 0

        def _fail_second_rename(collection: Any, new_name: str) -> None:
            nonlocal calls
            calls += 1
            if calls == 2:
                raise RuntimeError("injected second rename failure")
            collection.modify(name=new_name)

        with _patched_evolution_backend(BF662EmbeddingFunctionB()):
            with patch.object(
                EvolutionStore,
                "_rename_collection",
                side_effect=_fail_second_rename,
            ):
                failed = EvolutionStore(chroma_path=path)
                failed.start()
                assert failed._collection is None

            client = chromadb.PersistentClient(path=str(path))
            try:
                names = _names(client)
                assert "self_improvement_lessons" not in names
                backup_names = [name for name in names if name.startswith("bf662e-b-")]
                shadow_names = [name for name in names if name.startswith("bf662e-s-")]
                assert len(backup_names) == 1
                assert len(shadow_names) == 1
                assert _raw_dump(client, backup_names[0]) == before
            finally:
                client.close()

            recovered = EvolutionStore(chroma_path=path)
            recovered.start()
            try:
                assert recovered._collection is not None
                assert recovered._collection.get(
                    include=["documents", "metadatas"]
                ) == before
                assert _names(recovered._client) == {"self_improvement_lessons"}
            finally:
                recovered.stop()

    def test_recovery_candidate_with_backup_validates_before_cleanup(
        self, tmp_path: Path
    ) -> None:
        path = tmp_path / "candidate-backup"
        _, before = _seed_evolution_store(path, BF662EmbeddingFunctionA())
        with _patched_evolution_backend(BF662EmbeddingFunctionB()):
            with patch.object(
                EvolutionStore,
                "_prove_active_candidate",
                side_effect=RuntimeError("defer candidate proof"),
            ):
                failed = EvolutionStore(chroma_path=path)
                failed.start()
                assert failed._collection is None

            client = chromadb.PersistentClient(path=str(path))
            try:
                names = _names(client)
                assert "self_improvement_lessons" in names
                assert len([name for name in names if name.startswith("bf662e-b-")]) == 1
            finally:
                client.close()

            recovered = EvolutionStore(chroma_path=path)
            recovered.start()
            try:
                assert recovered._collection is not None
                assert recovered._collection.get(
                    include=["documents", "metadatas"]
                ) == before
                assert _names(recovered._client) == {"self_improvement_lessons"}
            finally:
                recovered.stop()

    def test_invalid_candidate_rolls_back_to_backup(self, tmp_path: Path) -> None:
        path = tmp_path / "invalid-candidate"
        _, before = _seed_evolution_store(path, BF662EmbeddingFunctionA())
        with _patched_evolution_backend(BF662EmbeddingFunctionB()):
            with patch.object(
                EvolutionStore,
                "_prove_active_candidate",
                side_effect=RuntimeError("defer candidate proof"),
            ):
                failed = EvolutionStore(chroma_path=path)
                failed.start()

            client = chromadb.PersistentClient(path=str(path))
            try:
                candidate = client.get_collection(
                    name="self_improvement_lessons",
                    embedding_function=BF662EmbeddingFunctionB(),
                )
                candidate.update(
                    ids=[before["ids"][0]],
                    documents=["corrupted candidate document"],
                )
            finally:
                client.close()

            original_rollback = EvolutionStore._rollback_candidate_to_backup
            rollbacks: list[str] = []

            def _record_rollback(self, *, candidate: Any, backup: Any) -> None:
                rollbacks.append(backup.name)
                original_rollback(self, candidate=candidate, backup=backup)

            with patch.object(
                EvolutionStore,
                "_rollback_candidate_to_backup",
                new=_record_rollback,
            ):
                recovered = EvolutionStore(chroma_path=path)
                recovered.start()
            try:
                assert rollbacks
                assert recovered._collection is not None
                assert recovered._collection.get(
                    include=["documents", "metadatas"]
                ) == before
                assert _names(recovered._client) == {"self_improvement_lessons"}
            finally:
                recovered.stop()

    def test_corrupt_backup_never_replaces_valid_candidate(
        self, tmp_path: Path
    ) -> None:
        path = tmp_path / "corrupt-backup"
        before = _leave_candidate_and_backup(path)
        client = chromadb.PersistentClient(path=str(path))
        try:
            backup_name = next(
                name for name in _names(client) if name.startswith("bf662e-b-")
            )
            backup = client.get_collection(
                name=backup_name,
                embedding_function=None,
            )
            backup.delete(ids=list(before["ids"]))
            assert backup.count() == 0
            snapshot_before = _collection_snapshot(client)
        finally:
            client.close()

        with _patched_evolution_backend(BF662EmbeddingFunctionB()):
            recovered = EvolutionStore(chroma_path=path)
            try:
                recovered.start()
                assert recovered._collection is None
                assert recovered._client is None
            finally:
                recovered.stop()

        verifier = chromadb.PersistentClient(path=str(path))
        try:
            assert _collection_snapshot(verifier) == snapshot_before
            assert _raw_dump(verifier, "self_improvement_lessons") == before
        finally:
            verifier.close()

    def test_canonical_count_mismatch_preserves_ready_shadow(
        self, tmp_path: Path
    ) -> None:
        path = tmp_path / "canonical-count-mismatch"
        _, before = _seed_evolution_store(path, BF662EmbeddingFunctionA())
        with _patched_evolution_backend(BF662EmbeddingFunctionB()):
            with patch.object(
                EvolutionStore,
                "_rename_collection",
                side_effect=RuntimeError("leave tagged canonical and ready shadow"),
            ):
                interrupted = EvolutionStore(chroma_path=path)
                try:
                    interrupted.start()
                    assert interrupted._collection is None
                finally:
                    interrupted.stop()

            client = chromadb.PersistentClient(path=str(path))
            try:
                canonical = client.get_collection(
                    name="self_improvement_lessons",
                    embedding_function=None,
                )
                canonical.delete(ids=list(before["ids"]))
                assert canonical.count() == 0
                assert len(
                    [name for name in _names(client) if name.startswith("bf662e-s-")]
                ) == 1
                snapshot_before = _collection_snapshot(client)
            finally:
                client.close()

            recovered = EvolutionStore(chroma_path=path)
            try:
                recovered.start()
                assert recovered._collection is None
                assert recovered._client is None
            finally:
                recovered.stop()

            verifier = chromadb.PersistentClient(path=str(path))
            try:
                assert _collection_snapshot(verifier) == snapshot_before
            finally:
                verifier.close()

    def test_rollback_candidate_rename_failure_recovers_on_restart(
        self, tmp_path: Path
    ) -> None:
        path = tmp_path / "rollback-candidate-rename"
        before = _leave_candidate_and_backup(path)
        client = chromadb.PersistentClient(path=str(path))
        try:
            candidate = client.get_collection(
                name="self_improvement_lessons",
                embedding_function=BF662EmbeddingFunctionB(),
            )
            candidate.update(
                ids=list(before["ids"]),
                documents=["invalid candidate document"],
            )
            snapshot_before = _collection_snapshot(client)
        finally:
            client.close()

        def _fail_candidate_rename(collection: Any, new_name: str) -> None:
            if (
                collection.name == "self_improvement_lessons"
                and new_name.startswith("bf662e-s-")
            ):
                raise RuntimeError("injected rollback candidate rename failure")
            collection.modify(name=new_name)

        with _patched_evolution_backend(BF662EmbeddingFunctionB()):
            with patch.object(
                EvolutionStore,
                "_rename_collection",
                side_effect=_fail_candidate_rename,
            ):
                failed = EvolutionStore(chroma_path=path)
                try:
                    failed.start()
                    assert failed._collection is None
                finally:
                    failed.stop()

            verifier = chromadb.PersistentClient(path=str(path))
            try:
                assert _collection_snapshot(verifier) == snapshot_before
            finally:
                verifier.close()

            recovered = EvolutionStore(chroma_path=path)
            try:
                recovered.start()
                assert recovered._collection is not None
                assert recovered._collection.get(
                    include=["documents", "metadatas"]
                ) == before
                assert _names(recovered._client) == {"self_improvement_lessons"}
            finally:
                recovered.stop()

    def test_rollback_backup_rename_failure_recovers_on_restart(
        self, tmp_path: Path
    ) -> None:
        path = tmp_path / "rollback-backup-rename"
        before = _leave_candidate_and_backup(path)
        client = chromadb.PersistentClient(path=str(path))
        try:
            candidate = client.get_collection(
                name="self_improvement_lessons",
                embedding_function=BF662EmbeddingFunctionB(),
            )
            candidate.update(
                ids=list(before["ids"]),
                documents=["invalid candidate document"],
            )
        finally:
            client.close()

        def _fail_backup_rename(collection: Any, new_name: str) -> None:
            if (
                collection.name.startswith("bf662e-b-")
                and new_name == "self_improvement_lessons"
            ):
                raise RuntimeError("injected rollback backup rename failure")
            collection.modify(name=new_name)

        with _patched_evolution_backend(BF662EmbeddingFunctionB()):
            with patch.object(
                EvolutionStore,
                "_rename_collection",
                side_effect=_fail_backup_rename,
            ):
                failed = EvolutionStore(chroma_path=path)
                try:
                    failed.start()
                    assert failed._collection is None
                finally:
                    failed.stop()

            verifier = chromadb.PersistentClient(path=str(path))
            try:
                names = _names(verifier)
                assert "self_improvement_lessons" not in names
                backup_name = next(
                    name for name in names if name.startswith("bf662e-b-")
                )
                shadow_name = next(
                    name for name in names if name.startswith("bf662e-s-")
                )
                backup = verifier.get_collection(
                    name=backup_name,
                    embedding_function=None,
                )
                shadow = verifier.get_collection(
                    name=shadow_name,
                    embedding_function=None,
                )
                assert backup.metadata["bf662_txn"] == shadow.metadata["bf662_txn"]
                assert shadow.metadata["bf662_role"] == "failed"
                assert shadow.metadata["bf662_state"] == "failed"
                assert shadow_name.endswith(str(shadow.metadata["bf662_txn"]))
            finally:
                verifier.close()

            recovered = EvolutionStore(chroma_path=path)
            try:
                recovered.start()
                assert recovered._collection is not None
                assert recovered._collection.get(
                    include=["documents", "metadatas"]
                ) == before
                assert _names(recovered._client) == {"self_improvement_lessons"}
            finally:
                recovered.stop()

    def test_no_canonical_with_unowned_temporary_degrades_without_creating_canonical(
        self, tmp_path: Path
    ) -> None:
        path = tmp_path / "unowned-temporary"
        with _patched_evolution_backend(BF662EmbeddingFunctionA()):
            client = chromadb.PersistentClient(path=str(path))
            try:
                probe = EvolutionStore(chroma_client=client)
                txn = "f" * 16
                name = f"bf662e-s-{probe._owner}-{txn}"
                temporary = client.create_collection(
                    name=name,
                    embedding_function=BF662EmbeddingFunctionA(),
                    metadata={"malformed": "not-owned"},
                )
                temporary.add(
                    ids=["unowned-row"],
                    documents=["preserve unowned temporary content"],
                    metadatas=[{"scope": "unchanged"}],
                )
                snapshot_before = _collection_snapshot(client)
            finally:
                client.close()

            store = EvolutionStore(chroma_path=path)
            try:
                store.start()
                assert store._collection is None
                assert store._client is None
            finally:
                store.stop()

            verifier = chromadb.PersistentClient(path=str(path))
            try:
                assert "self_improvement_lessons" not in _names(verifier)
                assert _collection_snapshot(verifier) == snapshot_before
            finally:
                verifier.close()

    def test_no_canonical_backup_with_mismatched_ready_shadow_degrades_without_mutation(
        self, tmp_path: Path
    ) -> None:
        path = tmp_path / "mismatched-ready-shadow"
        embedding_function = BF662EmbeddingFunctionA()
        with _patched_evolution_backend(embedding_function):
            client = chromadb.PersistentClient(path=str(path))
            try:
                probe = EvolutionStore(chroma_client=client)
                backup_txn = "a" * 16
                shadow_txn = "b" * 16
                backup = client.create_collection(
                    name=probe._temporary_name("backup", backup_txn),
                    embedding_function=embedding_function,
                    metadata=_bf662_temporary_metadata(
                        probe,
                        embedding_function,
                        txn=backup_txn,
                        role="backup",
                        state="backup",
                        source_count=1,
                    ),
                )
                backup.add(
                    ids=["backup-row"],
                    documents=["the unique backup authority"],
                    metadatas=[{"copy": "backup"}],
                )
                shadow = client.create_collection(
                    name=probe._temporary_name("shadow", shadow_txn),
                    embedding_function=embedding_function,
                    metadata=_bf662_temporary_metadata(
                        probe,
                        embedding_function,
                        txn=shadow_txn,
                        role="shadow",
                        state="ready",
                        source_count=1,
                    ),
                )
                shadow.add(
                    ids=["shadow-row"],
                    documents=["unrelated ready shadow"],
                    metadatas=[{"copy": "shadow"}],
                )
                snapshot_before = _collection_snapshot(client)
            finally:
                client.close()

            recovered = EvolutionStore(chroma_path=path)
            try:
                recovered.start()
                assert recovered._collection is None
                assert recovered._client is None
            finally:
                recovered.stop()

            verifier = chromadb.PersistentClient(path=str(path))
            try:
                assert "self_improvement_lessons" not in _names(verifier)
                assert _collection_snapshot(verifier) == snapshot_before
            finally:
                verifier.close()

    def test_candidate_backup_with_unrelated_shadow_degrades_without_mutation(
        self, tmp_path: Path
    ) -> None:
        path = tmp_path / "candidate-backup-unrelated-shadow"
        _leave_candidate_and_backup(path)
        embedding_function = BF662EmbeddingFunctionB()
        with _patched_evolution_backend(embedding_function):
            client = chromadb.PersistentClient(path=str(path))
            try:
                probe = EvolutionStore(chroma_client=client)
                candidate = client.get_collection(
                    name=probe._collection_name,
                    embedding_function=None,
                )
                candidate_txn = candidate.metadata["bf662_txn"]
                unrelated_txn = (
                    "0" * 16 if candidate_txn != "0" * 16 else "1" * 16
                )
                unrelated = client.create_collection(
                    name=probe._temporary_name("shadow", unrelated_txn),
                    embedding_function=embedding_function,
                    metadata=_bf662_temporary_metadata(
                        probe,
                        embedding_function,
                        txn=unrelated_txn,
                        role="shadow",
                        state="ready",
                        source_count=1,
                    ),
                )
                unrelated.add(
                    ids=["unrelated-row"],
                    documents=["unrelated candidate shadow"],
                    metadatas=[{"copy": "unrelated"}],
                )
                snapshot_before = _collection_snapshot(client)
            finally:
                client.close()

            recovered = EvolutionStore(chroma_path=path)
            try:
                recovered.start()
                assert recovered._collection is None
                assert recovered._client is None
            finally:
                recovered.stop()

            verifier = chromadb.PersistentClient(path=str(path))
            try:
                assert _collection_snapshot(verifier) == snapshot_before
            finally:
                verifier.close()

    @pytest.mark.parametrize(
        "invalid_case",
        [
            "missing-state",
            "invalid-state",
            "missing-transaction",
            "uppercase-transaction",
            "short-transaction",
            "missing-role",
            "invalid-role-state-pair",
            "missing-count",
            "string-count",
            "float-count",
            "bool-count",
            "negative-count",
            "missing-owner",
            "owner-mismatch",
            "missing-canonical-name",
            "canonical-name-mismatch",
            "temporary-name-mismatch",
        ],
    )
    def test_no_canonical_partially_owned_temporary_degrades_without_mutation(
        self,
        tmp_path: Path,
        invalid_case: str,
    ) -> None:
        path = tmp_path / invalid_case
        embedding_function = BF662EmbeddingFunctionA()
        with _patched_evolution_backend(embedding_function):
            client = chromadb.PersistentClient(path=str(path))
            try:
                probe = EvolutionStore(chroma_client=client)
                txn = "a" * 16
                name_txn = txn
                metadata = _bf662_temporary_metadata(
                    probe,
                    embedding_function,
                    txn=txn,
                    role="shadow",
                    state="ready",
                    source_count=1,
                )
                if invalid_case == "missing-state":
                    metadata.pop("bf662_state")
                elif invalid_case == "invalid-state":
                    metadata["bf662_state"] = "stable"
                elif invalid_case == "missing-transaction":
                    metadata.pop("bf662_txn")
                elif invalid_case == "uppercase-transaction":
                    metadata["bf662_txn"] = "A" * 16
                elif invalid_case == "short-transaction":
                    metadata["bf662_txn"] = "a" * 15
                elif invalid_case == "missing-role":
                    metadata.pop("bf662_role")
                elif invalid_case == "invalid-role-state-pair":
                    metadata["bf662_state"] = "backup"
                elif invalid_case == "missing-count":
                    metadata.pop("bf662_source_count")
                elif invalid_case == "string-count":
                    metadata["bf662_source_count"] = "1"
                elif invalid_case == "float-count":
                    metadata["bf662_source_count"] = 1.0
                elif invalid_case == "bool-count":
                    metadata["bf662_source_count"] = True
                elif invalid_case == "negative-count":
                    metadata["bf662_source_count"] = -1
                elif invalid_case == "missing-owner":
                    metadata.pop("bf662_owner")
                elif invalid_case == "owner-mismatch":
                    metadata["bf662_owner"] = "0" * 12
                elif invalid_case == "missing-canonical-name":
                    metadata.pop("bf662_canonical_name")
                elif invalid_case == "canonical-name-mismatch":
                    metadata["bf662_canonical_name"] = "other-lessons"
                elif invalid_case == "temporary-name-mismatch":
                    name_txn = "b" * 16

                temporary = client.create_collection(
                    name=probe._temporary_name("shadow", name_txn),
                    embedding_function=embedding_function,
                    metadata=metadata,
                )
                temporary.add(
                    ids=["partially-owned-row"],
                    documents=["preserve every partially owned field"],
                    metadatas=[{"case": invalid_case}],
                )
                snapshot_before = _collection_snapshot(client)
            finally:
                client.close()

            recovered = EvolutionStore(chroma_path=path)
            try:
                recovered.start()
                assert recovered._collection is None
                assert recovered._client is None
            finally:
                recovered.stop()

            verifier = chromadb.PersistentClient(path=str(path))
            try:
                assert "self_improvement_lessons" not in _names(verifier)
                assert _collection_snapshot(verifier) == snapshot_before
            finally:
                verifier.close()

    def test_same_backend_start_is_idempotent_without_temp_collections(
        self, tmp_path: Path
    ) -> None:
        path = tmp_path / "same-backend"
        _, before = _seed_evolution_store(path, BF662EmbeddingFunctionA())
        with _patched_evolution_backend(BF662EmbeddingFunctionA()):
            with patch.object(
                EvolutionStore,
                "_transition_collection",
            ) as transition:
                store = EvolutionStore(chroma_path=path)
                store.start()
                try:
                    transition.assert_not_called()
                    assert store._collection is not None
                    assert store._collection.get(
                        include=["documents", "metadatas"]
                    ) == before
                    assert _names(store._client) == {"self_improvement_lessons"}
                finally:
                    store.stop()

    def test_empty_store_transition_succeeds(self, tmp_path: Path) -> None:
        path = tmp_path / "empty"
        with _patched_evolution_backend(BF662EmbeddingFunctionA()):
            first = EvolutionStore(chroma_path=path)
            first.start()
            first.stop()
        with _patched_evolution_backend(BF662EmbeddingFunctionB()) as backend_id:
            second = EvolutionStore(chroma_path=path)
            second.start()
            try:
                assert second._collection is not None
                assert second._collection.count() == 0
                assert second._collection.metadata["embedding_backend_id"] == backend_id
                assert second._collection.metadata["bf662_state"] == "stable"
                assert _names(second._client) == {"self_improvement_lessons"}
            finally:
                second.stop()

    def test_shadow_names_are_bounded_valid_and_collision_safe(
        self, tmp_path: Path
    ) -> None:
        canonical = "c" + ("x" * 510) + "z"
        path = tmp_path / "names"
        with _patched_evolution_backend(BF662EmbeddingFunctionA()):
            store = EvolutionStore(chroma_path=path, collection_name=canonical)
            store.start()
            try:
                first_txn = "1" * 16
                second_txn = "2" * 16
                collision = store._temporary_name("shadow", first_txn)
                store._client.create_collection(
                    name=collision,
                    embedding_function=BF662EmbeddingFunctionA(),
                    metadata={"unowned": True},
                )
                with patch(
                    "probos.cognitive.self_improvement.evolution_store.uuid.uuid4",
                    side_effect=[
                        SimpleNamespace(hex=first_txn + ("0" * 16)),
                        SimpleNamespace(hex=second_txn + ("0" * 16)),
                    ],
                ):
                    txn, shadow, backup = store._allocate_transaction_names()
                assert txn == second_txn
                assert shadow != collision
                for name in (shadow, backup):
                    assert len(name) < 63
                    assert re.fullmatch(r"[a-z0-9-]+", name)
                    assert canonical not in name
            finally:
                store.stop()

    def test_payload_remains_explicitly_unpersisted_across_transition(
        self, tmp_path: Path
    ) -> None:
        path = tmp_path / "payload"
        with _patched_evolution_backend(BF662EmbeddingFunctionA()):
            first = EvolutionStore(chroma_path=path)
            first.start()
            try:
                first.record_lesson(
                    "approved",
                    "payload scope lesson",
                    "payload-proposal",
                    "approved",
                    {"ephemeral": "value"},
                )
            finally:
                first.stop()
        with _patched_evolution_backend(BF662EmbeddingFunctionB()):
            second = EvolutionStore(chroma_path=path)
            second.start()
            try:
                hits = second.recall("payload scope", top_k=1)
                assert hits
                assert hits[0].payload == {}
            finally:
                second.stop()

    def test_stop_closes_only_owned_client(self, tmp_path: Path) -> None:
        with _patched_evolution_backend(BF662EmbeddingFunctionA()):
            owned = EvolutionStore(chroma_path=tmp_path / "owned")
            owned.start()
            owned_client = owned._client
            with patch.object(
                owned_client, "close", wraps=owned_client.close
            ) as owned_close:
                owned.stop()
                owned.stop()
                owned_close.assert_called_once_with()
            assert owned._client is None
            assert owned._collection is None

            injected_client = chromadb.PersistentClient(
                path=str(tmp_path / "injected")
            )
            try:
                injected = EvolutionStore(chroma_client=injected_client)
                injected.start()
                with patch.object(
                    injected_client, "close", wraps=injected_client.close
                ) as injected_close:
                    injected.stop()
                    injected_close.assert_not_called()
                assert injected._client is None
                assert injected._collection is None
            finally:
                injected_client.close()

    def test_ambiguous_backup_state_degrades_without_mutation(
        self, tmp_path: Path
    ) -> None:
        path = tmp_path / "ambiguous"
        with _patched_evolution_backend(BF662EmbeddingFunctionA()):
            client = chromadb.PersistentClient(path=str(path))
            try:
                owner = EvolutionStore(
                    chroma_client=client
                )._owner
                names_before: set[str] = set()
                for txn in ("a" * 16, "b" * 16):
                    name = f"bf662e-b-{owner}-{txn}"
                    names_before.add(name)
                    collection = client.create_collection(
                        name=name,
                        embedding_function=BF662EmbeddingFunctionA(),
                        metadata={
                            "embedding_model": BF662EmbeddingFunctionA.name(),
                            "embedding_backend_id": get_embedding_backend_id(
                                BF662EmbeddingFunctionA()
                            ),
                            "bf662_canonical_name": "self_improvement_lessons",
                            "bf662_owner": owner,
                            "bf662_txn": txn,
                            "bf662_role": "backup",
                            "bf662_state": "backup",
                            "bf662_source_count": 0,
                        },
                    )
                    assert collection.count() == 0
            finally:
                client.close()

            store = EvolutionStore(chroma_path=path)
            store.start()
            assert store._collection is None
            assert store._client is None
            verifier = chromadb.PersistentClient(path=str(path))
            try:
                assert _names(verifier) == names_before
            finally:
                verifier.close()


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

    @pytest.mark.asyncio
    async def test_wirer_skips_when_disabled(self) -> None:
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
        wired = await _wire_self_improvement(runtime=runtime, config=config)
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
