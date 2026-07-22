"""AD-1130: terminal evidence is the only CrewSession trust authority."""

from __future__ import annotations

import asyncio
import ast
import hashlib
import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from probos.cognitive.crew_finalizer import CrewSessionFinalizer
from probos.cognitive.crew_trust import (
    CrewSessionTrustRecorder,
    CrewTrustEffect,
    _all_approved_shapley,
    derive_completed_crew_trust_effects,
    derive_convergence_exhausted_effects,
    derive_final_refutation_effects,
)
from probos.consensus.shapley import compute_shapley_values
from probos.consensus.trust import TrustNetwork
from probos.config import SystemConfig
from probos.routers.thread_fanout import _record_conversation_trust
from probos.storage.sqlite_factory import SQLiteConnectionFactory
from probos.types import Vote
from probos.workforce import WorkItemStore, _insert_crew_trust_effects
from tests.test_ad1126_verified_finalization import (
    _Agent,
    _Registry,
    _ServiceFailure,
    _ScriptedLLM,
    _StaticAgenticExecutor,
    _executing_case,
    _make_finalizer,
    _make_synthesizer,
    _make_verifier,
    _registry_for,
    _runtime,
    _text,
    _verdict,
    stores as stores_fixture,
)

_SHA_A = "a" * 64
_SHA_B = "b" * 64


def _effect(
    *,
    session_id: str = "session-1",
    session_revision: int = 4,
    evidence_sha256: str = _SHA_A,
    agent_id: str = "producer-1",
    role: str = "child_producer",
    work_item_id: str = "child-1",
    result_revision: int = 1,
    success: bool = True,
    weight: float = 1.0,
    intent_type: str = "crew_session_child",
    verifier_id: str = "verifier-1",
) -> CrewTrustEffect:
    return CrewTrustEffect.create(
        session_id=session_id,
        session_revision=session_revision,
        evidence_sha256=evidence_sha256,
        agent_id=agent_id,
        role=role,  # type: ignore[arg-type]
        work_item_id=work_item_id,
        result_revision=result_revision,
        success=success,
        weight=weight,
        intent_type=intent_type,
        verifier_id=verifier_id,
    )


def _round(
    index: int,
    *,
    status: str,
    verifier_id: str = "verifier-1",
    confidence: float = 0.9,
) -> dict[str, Any]:
    result_text = f"revision-{index + 1}"
    return {
        "round_index": index,
        "result_revision": index + 1,
        "result_sha256": hashlib.sha256(result_text.encode()).hexdigest(),
        "result_summary": result_text,
        "stopped_reason": "complete",
        "correction_tokens": 0 if index == 0 else 2,
        "verifier_tokens": 3,
        "tool_trace_ref": None,
        "artifact_refs": [],
        "verdict": {
            "status": status,
            "accepted": status == "accepted",
            "confidence": confidence,
            "critique": "validated evidence",
            "verifier_agent_id": verifier_id,
            "tokens_used": 3,
            "failure_code": None,
        },
    }


def _verification(
    *,
    work_item_id: str = "child-1",
    producer_id: str = "producer-1",
    rounds: tuple[dict[str, Any], ...],
    accepted: bool,
    failure_code: str | None = None,
) -> dict[str, Any]:
    return {
        "version": 1,
        "parent_id": "session-1",
        "work_item_id": work_item_id,
        "thread_id": "thread-1",
        "producer_agent_id": producer_id,
        "status": "converged" if accepted else "unverified",
        "accepted": accepted,
        "rounds_used": len(rounds) - 1,
        "result_revision_count": len(rounds),
        "rounds": [dict(item) for item in rounds],
        "failure_code": failure_code,
        "terminal_attempt": None,
    }


@pytest.fixture
async def trust_network(tmp_path: Path) -> Any:
    network = TrustNetwork(db_path=str(tmp_path / "trust.db"))
    await network.start()
    try:
        yield network
    finally:
        await network.stop()


@pytest.fixture
async def stores(tmp_path: Path) -> Any:
    generator = stores_fixture.__wrapped__(tmp_path)
    value = await generator.__anext__()
    try:
        yield value
    finally:
        await generator.aclose()


@pytest.fixture
async def work_store(tmp_path: Path) -> Any:
    store = WorkItemStore(
        db_path=str(tmp_path / "workforce.db"),
        tick_interval=1_000,
        connection_factory=SQLiteConnectionFactory(),
    )
    await store.start()
    try:
        yield store
    finally:
        await store.stop()


async def _enqueue_effect(store: WorkItemStore, effect: CrewTrustEffect) -> None:
    assert store._db is not None
    await store._db.execute("BEGIN IMMEDIATE")
    try:
        await _insert_crew_trust_effects(store._db, (effect.to_payload(),))
        await store._db.commit()
    except BaseException:
        await store._db.execute("ROLLBACK")
        raise


async def _outbox_rows(store: WorkItemStore) -> list[Any]:
    assert store._db is not None
    cursor = await store._db.execute(
        "SELECT outcome_id, delivered FROM crew_trust_outbox ORDER BY outcome_id",
    )
    return list(await cursor.fetchall())


def _arm_postcommit_ambiguity(network: TrustNetwork) -> dict[str, Any]:
    assert network._db is not None
    database = network._db
    original_execute = database.execute
    original_commit = database.commit
    state: dict[str, Any] = {
        "fail_reads": True,
        "snapshot_reads": 0,
        "commit_raised": False,
    }

    async def execute(sql: str, parameters: Any = ()) -> Any:
        if "FROM trust_outcome_receipts AS r" in sql:
            state["snapshot_reads"] += 1
            if state["snapshot_reads"] > 1 and state["fail_reads"]:
                raise OSError("receipt reread failed")
        return await original_execute(sql, parameters)

    async def commit() -> None:
        await original_commit()
        if not state["commit_raised"]:
            state["commit_raised"] = True
            raise OSError("commit outcome unknown")

    database.execute = execute
    database.commit = commit
    state["original_execute"] = original_execute
    state["original_commit"] = original_commit
    return state


async def _recorder_finalizer(
    stores: Any,
    tmp_path: Path,
    *,
    service: Any,
    children: list[Any],
    judge: Any,
    synth: Any,
    executor: Any,
    trust: TrustNetwork,
    outbox: Any | None = None,
) -> CrewSessionFinalizer:
    registry = _registry_for(children)
    runtime = _runtime(stores, tmp_path, service)
    recorder = CrewSessionTrustRecorder(
        outbox=outbox or stores.work,
        trust_network=trust,
    )
    finalizer = _make_finalizer(
        stores=stores,
        service=service,
        registry=registry,
        verifier=_make_verifier(
            llm=judge,
            stores=stores,
            registry=registry,
            executor=executor,
            runtime=runtime,
        ),
        synthesizer=_make_synthesizer(
            llm=synth,
            stores=stores,
            runtime=runtime,
        ),
        trust_recorder=recorder,
    )
    assert isinstance(finalizer, CrewSessionFinalizer)
    return finalizer


async def test_record_outcome_once_duplicate_restart_preserves_raw_pair(
    tmp_path: Path,
) -> None:
    path = str(tmp_path / "trust.db")
    effect = _effect()
    first = TrustNetwork(db_path=path)
    await first.start()
    applied = await first.record_outcome_once(effect)
    duplicate = await first.record_outcome_once(effect)
    assert applied.disposition == "applied"
    assert duplicate.disposition == "duplicate"
    assert (duplicate.alpha, duplicate.beta) == (3.0, 2.0)
    assert len(first.get_events_for_agent("producer-1")) == 1
    await first.stop()

    restarted = TrustNetwork(db_path=path)
    await restarted.start()
    replay = await restarted.record_outcome_once(effect)
    assert replay.disposition == "duplicate"
    assert (replay.alpha, replay.beta) == (3.0, 2.0)
    assert restarted.get_recent_events() == []
    await restarted.stop()


async def test_receipt_schema_migrates_old_table_and_null_result_fails_closed(
    tmp_path: Path,
) -> None:
    path = tmp_path / "trust.db"
    effect = _effect()
    canonical = effect.canonical_bytes()
    connection = sqlite3.connect(path)
    connection.executescript("""
        CREATE TABLE trust_scores (
            agent_id TEXT PRIMARY KEY,
            alpha REAL NOT NULL DEFAULT 2.0,
            beta REAL NOT NULL DEFAULT 2.0,
            updated TEXT NOT NULL
        );
        CREATE TABLE trust_outcome_receipts (
            outcome_id TEXT PRIMARY KEY,
            payload_json TEXT NOT NULL,
            payload_sha256 TEXT NOT NULL,
            agent_id TEXT NOT NULL,
            session_id TEXT NOT NULL,
            session_revision INTEGER NOT NULL,
            evidence_sha256 TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
    """)
    connection.execute(
        "INSERT INTO trust_scores VALUES (?, ?, ?, ?)",
        (effect.agent_id, 9.0, 4.0, "old"),
    )
    connection.execute(
        "INSERT INTO trust_outcome_receipts VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            effect.outcome_id,
            canonical.decode("utf-8"),
            hashlib.sha256(canonical).hexdigest(),
            effect.agent_id,
            effect.session_id,
            effect.session_revision,
            effect.evidence_sha256,
            "old",
        ),
    )
    connection.commit()
    connection.close()

    network = TrustNetwork(db_path=str(path))
    await network.start()
    assert network._db is not None
    cursor = await network._db.execute(
        "PRAGMA table_info(trust_outcome_receipts)",
    )
    columns = [row[1] for row in await cursor.fetchall()]
    assert columns.count("result_alpha") == 1
    assert columns.count("result_beta") == 1
    with pytest.raises(
        ValueError,
        match="trust_outcome_receipt_result_missing",
    ):
        await network.record_outcome_once(effect)
    assert network.raw_scores()[effect.agent_id]["alpha"] == 9.0
    await network.stop()

    restarted = TrustNetwork(db_path=str(path))
    await restarted.start()
    assert restarted._db is not None
    cursor = await restarted._db.execute(
        "PRAGMA table_info(trust_outcome_receipts)",
    )
    columns = [row[1] for row in await cursor.fetchall()]
    assert columns.count("result_alpha") == 1
    assert columns.count("result_beta") == 1
    fresh = _effect(agent_id="producer-2", work_item_id="child-2")
    result = await restarted.record_outcome_once(fresh)
    cursor = await restarted._db.execute(
        "SELECT result_alpha, result_beta FROM trust_outcome_receipts "
        "WHERE outcome_id = ?",
        (fresh.outcome_id,),
    )
    row = await cursor.fetchone()
    assert tuple(row) == (result.alpha, result.beta) == (3.0, 2.0)
    await restarted.stop()


async def test_new_receipt_schema_declares_result_pair_not_null(
    tmp_path: Path,
) -> None:
    network = TrustNetwork(db_path=str(tmp_path / "new-trust.db"))
    await network.start()
    assert network._db is not None
    cursor = await network._db.execute(
        "PRAGMA table_info(trust_outcome_receipts)",
    )
    columns = {row[1]: row for row in await cursor.fetchall()}
    assert columns["result_alpha"][3] == 1
    assert columns["result_beta"][3] == 1
    await network.stop()


async def test_record_outcome_once_storage_failure_is_invisible(
    trust_network: TrustNetwork,
) -> None:
    assert trust_network._db is not None
    original = trust_network._db.execute

    async def failing(sql: str, parameters: Any = ()) -> Any:
        if "INSERT INTO trust_outcome_receipts" in sql:
            raise OSError("receipt write failed")
        return await original(sql, parameters)

    trust_network._db.execute = failing
    before = trust_network.raw_scores()
    with pytest.raises(OSError, match="receipt write failed"):
        await trust_network.record_outcome_once(_effect())
    trust_network._db.execute = original
    assert trust_network.raw_scores() == before
    assert trust_network.get_recent_events() == []
    assert trust_network._dampening == {}


async def test_record_outcome_once_bool_int_payload_conflict(
    trust_network: TrustNetwork,
) -> None:
    effect = _effect()
    await trust_network.record_outcome_once(effect)
    assert trust_network._db is not None
    payload = effect.to_payload()
    payload["session_revision"] = True
    await trust_network._db.execute(
        "UPDATE trust_outcome_receipts SET payload_json = ? WHERE outcome_id = ?",
        (
            json.dumps(payload, sort_keys=True, separators=(",", ":")),
            effect.outcome_id,
        ),
    )
    await trust_network._db.commit()
    with pytest.raises(ValueError, match="trust_outcome_identity_conflict"):
        await trust_network.record_outcome_once(effect)


async def test_duplicate_reconciles_current_raw_and_authoritative_removal(
    trust_network: TrustNetwork,
) -> None:
    effect = _effect()
    applied = await trust_network.record_outcome_once(effect)
    record = trust_network.get_record(effect.agent_id)
    assert record is not None
    record.alpha = 99.0
    record.beta = 1.0
    duplicate = await trust_network.record_outcome_once(effect)
    assert (duplicate.alpha, duplicate.beta) == (applied.alpha, applied.beta)
    assert trust_network.raw_scores()[effect.agent_id]["alpha"] == 3.0

    assert trust_network._db is not None
    await trust_network._db.execute(
        "UPDATE trust_scores SET alpha = ?, beta = ? WHERE agent_id = ?",
        (7.0, 4.0, effect.agent_id),
    )
    await trust_network._db.commit()
    duplicate = await trust_network.record_outcome_once(effect)
    assert (duplicate.alpha, duplicate.beta) == (3.0, 2.0)
    assert trust_network.raw_scores()[effect.agent_id]["alpha"] == 7.0
    assert trust_network.raw_scores()[effect.agent_id]["beta"] == 4.0

    await trust_network._db.execute(
        "DELETE FROM trust_scores WHERE agent_id = ?",
        (effect.agent_id,),
    )
    await trust_network._db.commit()
    record = trust_network.get_or_create(effect.agent_id)
    record.alpha = 55.0
    duplicate = await trust_network.record_outcome_once(effect)
    assert (duplicate.alpha, duplicate.beta) == (3.0, 2.0)
    assert effect.agent_id not in trust_network.raw_scores()


@pytest.mark.parametrize(
    ("column", "value"),
    [
        ("result_alpha", -1.0),
        ("result_beta", float("inf")),
    ],
)
async def test_duplicate_invalid_receipt_result_fails_closed(
    trust_network: TrustNetwork,
    column: str,
    value: float,
) -> None:
    effect = _effect()
    await trust_network.record_outcome_once(effect)
    assert trust_network._db is not None
    await trust_network._db.execute(
        f"UPDATE trust_outcome_receipts SET {column} = ? WHERE outcome_id = ?",
        (value, effect.outcome_id),
    )
    await trust_network._db.commit()
    before = trust_network.raw_scores()
    with pytest.raises(
        ValueError,
        match="trust_outcome_receipt_result_invalid",
    ):
        await trust_network.record_outcome_once(effect)
    assert trust_network.raw_scores() == before


@pytest.mark.parametrize("value", [-1.0, float("inf")])
async def test_duplicate_invalid_current_raw_fails_closed(
    trust_network: TrustNetwork,
    value: float,
) -> None:
    effect = _effect()
    await trust_network.record_outcome_once(effect)
    assert trust_network._db is not None
    await trust_network._db.execute(
        "UPDATE trust_scores SET alpha = ? WHERE agent_id = ?",
        (value, effect.agent_id),
    )
    await trust_network._db.commit()
    before = trust_network.raw_scores()
    with pytest.raises(
        ValueError,
        match="trust_outcome_current_state_invalid",
    ):
        await trust_network.record_outcome_once(effect)
    assert trust_network.raw_scores() == before


async def test_record_outcome_once_sync_writer_busy_before_mutation(
    trust_network: TrustNetwork,
) -> None:
    assert trust_network._db is not None
    original = trust_network._db.execute
    entered = asyncio.Event()
    release = asyncio.Event()

    async def blocked(sql: str, parameters: Any = ()) -> Any:
        if "INSERT INTO trust_scores" in sql and not entered.is_set():
            entered.set()
            await release.wait()
        return await original(sql, parameters)

    trust_network._db.execute = blocked
    task = asyncio.create_task(trust_network.record_outcome_once(_effect()))
    await entered.wait()
    before = (
        trust_network.raw_scores(),
        dict(trust_network._dampening),
        list(trust_network.get_recent_events()),
        trust_network._floor_hit_count,
    )
    with pytest.raises(RuntimeError, match="^trust_write_in_progress$"):
        trust_network.record_outcome("producer-1", success=True, weight=1.0)
    with pytest.raises(RuntimeError, match="^trust_write_in_progress$"):
        trust_network.create_with_prior("other-agent", 1.0, 3.0)
    assert (
        trust_network.raw_scores(),
        dict(trust_network._dampening),
        list(trust_network.get_recent_events()),
        trust_network._floor_hit_count,
    ) == before
    release.set()
    result = await task
    trust_network._db.execute = original
    assert (result.alpha, result.beta) == (3.0, 2.0)
    await trust_network.save()
    cursor = await trust_network._db.execute(
        "SELECT alpha, beta FROM trust_scores WHERE agent_id = ?",
        ("producer-1",),
    )
    row = await cursor.fetchone()
    assert tuple(row) == (3.0, 2.0)
    assert not hasattr(trust_network, "_queued_sync_outcomes")


async def test_ambiguous_commit_blocks_mutation_then_reconciles_newer_raw_once(
    trust_network: TrustNetwork,
) -> None:
    effect = _effect()
    state = _arm_postcommit_ambiguity(trust_network)
    before = trust_network.raw_scores()
    with pytest.raises(OSError, match="commit outcome unknown"):
        await trust_network.record_outcome_once(effect)
    assert trust_network.raw_scores() == before
    assert trust_network.get_recent_events() == []
    assert trust_network._outcome_reconciliation is not None
    with pytest.raises(RuntimeError, match="^trust_write_in_progress$"):
        trust_network.record_outcome("other-agent", success=True)
    with pytest.raises(RuntimeError, match="^trust_write_in_progress$"):
        trust_network.create_with_prior("other-agent", 1.0, 3.0)
    with pytest.raises(
        RuntimeError,
        match="^trust_outcome_reconciliation_required$",
    ):
        await trust_network.save()
    with pytest.raises(
        RuntimeError,
        match="^trust_outcome_reconciliation_required$",
    ):
        await trust_network.record_outcome_once(
            _effect(agent_id="producer-2", work_item_id="child-2"),
        )
    with pytest.raises(OSError, match="commit outcome unknown"):
        await trust_network.record_outcome_once(effect)

    state["fail_reads"] = False
    await state["original_execute"](
        "UPDATE trust_scores SET alpha = ?, beta = ? WHERE agent_id = ?",
        (7.0, 4.0, effect.agent_id),
    )
    await state["original_commit"]()
    result = await trust_network.record_outcome_once(effect)
    assert result.disposition == "applied"
    assert (result.alpha, result.beta) == (3.0, 2.0)
    assert trust_network.raw_scores()[effect.agent_id]["alpha"] == 7.0
    assert trust_network.raw_scores()[effect.agent_id]["beta"] == 4.0
    assert len(trust_network.get_events_for_agent(effect.agent_id)) == 1
    duplicate = await trust_network.record_outcome_once(effect)
    assert duplicate.disposition == "duplicate"
    assert len(trust_network.get_events_for_agent(effect.agent_id)) == 1


async def test_ambiguous_commit_stop_closes_and_restart_duplicate_acknowledges(
    tmp_path: Path,
) -> None:
    work_path = str(tmp_path / "workforce.db")
    trust_path = str(tmp_path / "trust.db")
    store = WorkItemStore(db_path=work_path, tick_interval=1_000)
    trust = TrustNetwork(db_path=trust_path)
    await store.start()
    await trust.start()
    effect = _effect()
    await _enqueue_effect(store, effect)
    _arm_postcommit_ambiguity(trust)
    recorder = CrewSessionTrustRecorder(outbox=store, trust_network=trust)
    assert await recorder.drain_pending() == 0
    assert len(await store.list_pending_crew_trust_outcomes(limit=10)) == 1
    with pytest.raises(
        RuntimeError,
        match="^trust_outcome_reconciliation_required$",
    ):
        await trust.stop()
    assert trust._db is None
    await store.stop()

    restarted_store = WorkItemStore(db_path=work_path, tick_interval=1_000)
    restarted_trust = TrustNetwork(db_path=trust_path)
    await restarted_store.start()
    await restarted_trust.start()
    assert restarted_trust.raw_scores()[effect.agent_id]["alpha"] == 3.0
    restarted = CrewSessionTrustRecorder(
        outbox=restarted_store,
        trust_network=restarted_trust,
    )
    assert await restarted.drain_pending() == 1
    assert await restarted.drain_pending() == 0
    assert restarted_trust.get_recent_events() == []
    assert restarted_trust.raw_scores()[effect.agent_id]["alpha"] == 3.0
    await restarted_trust.stop()
    await restarted_store.stop()


async def test_recorder_ack_failure_replays_duplicate_once(
    work_store: WorkItemStore,
    trust_network: TrustNetwork,
) -> None:
    effect = _effect()
    await _enqueue_effect(work_store, effect)

    class _AckFailure:
        def __init__(self, delegate: WorkItemStore) -> None:
            self.delegate = delegate
            self.failed = False

        async def list_pending_crew_trust_outcomes(self, *, limit: int) -> Any:
            return await self.delegate.list_pending_crew_trust_outcomes(limit=limit)

        async def mark_crew_trust_outcome_delivered(self, *args: Any, **kwargs: Any) -> bool:
            if not self.failed:
                self.failed = True
                raise OSError("ack failed")
            return await self.delegate.mark_crew_trust_outcome_delivered(*args, **kwargs)

    outbox = _AckFailure(work_store)
    recorder = CrewSessionTrustRecorder(outbox=outbox, trust_network=trust_network)
    assert await recorder.drain_pending() == 0
    first = trust_network.raw_scores()["producer-1"]
    events = len(trust_network.get_events_for_agent("producer-1"))
    assert await recorder.drain_pending() == 1
    assert trust_network.raw_scores()["producer-1"] == first
    assert len(trust_network.get_events_for_agent("producer-1")) == events == 1
    assert await work_store.list_pending_crew_trust_outcomes(limit=10) == ()


async def test_recorder_trust_failure_leaves_pending_then_retry_applies_once(
    work_store: WorkItemStore,
    trust_network: TrustNetwork,
) -> None:
    effect = _effect()
    await _enqueue_effect(work_store, effect)

    class _TrustFailure:
        async def record_outcome_once(self, effect: CrewTrustEffect) -> Any:
            raise OSError("trust store failed")

    failing = CrewSessionTrustRecorder(outbox=work_store, trust_network=_TrustFailure())
    assert await failing.drain_pending() == 0
    assert trust_network.raw_scores() == {}
    assert len(await work_store.list_pending_crew_trust_outcomes(limit=10)) == 1

    retry = CrewSessionTrustRecorder(outbox=work_store, trust_network=trust_network)
    assert await retry.drain_pending() == 1
    assert trust_network.raw_scores()["producer-1"]["alpha"] == 3.0
    assert await work_store.list_pending_crew_trust_outcomes(limit=10) == ()


async def test_recorder_cancellation_leaves_pending_and_restart_applies_once(
    tmp_path: Path,
) -> None:
    work_path = str(tmp_path / "workforce.db")
    trust_path = str(tmp_path / "trust.db")
    store = WorkItemStore(db_path=work_path, tick_interval=1_000)
    trust = TrustNetwork(db_path=trust_path)
    await store.start()
    await trust.start()
    effect = _effect()
    await _enqueue_effect(store, effect)

    class _CancelledTrust:
        async def record_outcome_once(self, effect: CrewTrustEffect) -> Any:
            raise asyncio.CancelledError("delivery cancelled")

    recorder = CrewSessionTrustRecorder(outbox=store, trust_network=_CancelledTrust())
    with pytest.raises(asyncio.CancelledError, match="delivery cancelled"):
        await recorder.drain_pending()
    assert len(await store.list_pending_crew_trust_outcomes(limit=10)) == 1
    await trust.stop()
    await store.stop()

    restarted_store = WorkItemStore(db_path=work_path, tick_interval=1_000)
    restarted_trust = TrustNetwork(db_path=trust_path)
    await restarted_store.start()
    await restarted_trust.start()
    restarted = CrewSessionTrustRecorder(
        outbox=restarted_store,
        trust_network=restarted_trust,
    )
    assert await restarted.drain_pending() == 1
    assert restarted_trust.raw_scores()["producer-1"]["alpha"] == 3.0
    assert await restarted.drain_pending() == 0
    await restarted_trust.stop()
    await restarted_store.stop()


async def test_restart_pending_outbox_with_existing_receipt_is_duplicate_noop(
    tmp_path: Path,
) -> None:
    work_path = str(tmp_path / "workforce.db")
    trust_path = str(tmp_path / "trust.db")
    store = WorkItemStore(db_path=work_path, tick_interval=1_000)
    trust = TrustNetwork(db_path=trust_path)
    await store.start()
    await trust.start()
    effect = _effect()
    await _enqueue_effect(store, effect)
    await trust.record_outcome_once(effect)
    await trust.stop()
    await store.stop()

    restarted_store = WorkItemStore(db_path=work_path, tick_interval=1_000)
    restarted_trust = TrustNetwork(db_path=trust_path)
    await restarted_store.start()
    await restarted_trust.start()
    recorder = CrewSessionTrustRecorder(
        outbox=restarted_store,
        trust_network=restarted_trust,
    )
    assert await recorder.drain_pending() == 1
    assert restarted_trust.raw_scores()["producer-1"]["alpha"] == 3.0
    assert restarted_trust.get_recent_events() == []
    await restarted_trust.stop()
    await restarted_store.stop()


async def test_outbox_exact_duplicate_is_idempotent_and_conflict_rejected(
    work_store: WorkItemStore,
) -> None:
    effect = _effect()
    await _enqueue_effect(work_store, effect)
    await _enqueue_effect(work_store, effect)
    rows = await _outbox_rows(work_store)
    assert len(rows) == 1
    assert work_store._db is not None
    await work_store._db.execute(
        "UPDATE crew_trust_outbox SET session_revision = ? WHERE outcome_id = ?",
        (True, effect.outcome_id),
    )
    await work_store._db.commit()
    with pytest.raises(ValueError, match="crew_trust_outbox_corrupt"):
        await work_store.list_pending_crew_trust_outcomes(limit=10)


async def test_concurrent_drainers_apply_one_effect(
    work_store: WorkItemStore,
    trust_network: TrustNetwork,
) -> None:
    await _enqueue_effect(work_store, _effect())
    first = CrewSessionTrustRecorder(outbox=work_store, trust_network=trust_network)
    second = CrewSessionTrustRecorder(outbox=work_store, trust_network=trust_network)
    results = await asyncio.gather(first.drain_pending(), second.drain_pending())
    assert sum(results) in {1, 2}
    assert trust_network.raw_scores()["producer-1"]["alpha"] == 3.0
    assert len(trust_network.get_events_for_agent("producer-1")) == 1


def test_effect_identity_changes_with_revision_and_evidence() -> None:
    base = _effect()
    revision = _effect(session_revision=5)
    evidence = _effect(evidence_sha256=_SHA_B)
    assert len({base.outcome_id, revision.outcome_id, evidence.outcome_id}) == 3


def test_completed_derivation_rewards_corrected_producer_and_verifiers() -> None:
    history = (_round(0, status="refuted"), _round(1, status="accepted"))
    verification = _verification(rounds=history, accepted=True)
    effects = derive_completed_crew_trust_effects(
        session_id="session-1",
        session_revision=5,
        child_verifications=(verification,),
        facilitator_id="facilitator-1",
        final_verifier_id="final-verifier-1",
        final_confidence=0.95,
        final_evidence_sha256=_SHA_B,
        approval_threshold=0.6,
        use_confidence_weights=True,
    )
    by_role = [(effect.role, effect.success, effect.result_revision) for effect in effects]
    assert by_role.count(("child_producer", True, 2)) == 1
    assert ("child_producer", False, 1) not in by_role
    assert by_role.count(("child_verifier", True, 1)) == 1
    assert by_role.count(("child_verifier", True, 2)) == 1
    assert ("facilitator", True, 1) in by_role
    assert ("final_verifier", True, 1) in by_role
    assert all(effect.weight >= 0.1 for effect in effects if effect.role in {"child_producer", "facilitator"})


def test_large_weighted_shapley_is_positive_only_stable_and_floored(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    verifications = tuple(
        _verification(
            work_item_id=f"child-{index}",
            producer_id=f"producer-{index}",
            rounds=(_round(
                0,
                status="accepted",
                verifier_id=f"verifier-{index}",
                confidence=0.9 if index in {0, 5} else 0.0,
            ),),
            accepted=True,
        )
        for index in range(11)
    )
    votes = [
        Vote(
            agent_id=f"child:child-{index}",
            approved=True,
            confidence=0.9 if index in {0, 5} else 0.0,
        )
        for index in range(11)
    ]
    votes.append(Vote(
        agent_id="facilitator:session-1",
        approved=True,
        confidence=0.8,
    ))
    raw = _all_approved_shapley(votes, use_confidence_weights=True)
    assert raw["child:child-0"] == pytest.approx(1.0 / 3.0)
    assert raw["child:child-5"] == pytest.approx(1.0 / 3.0)
    assert raw["facilitator:session-1"] == pytest.approx(1.0 / 3.0)
    assert raw["child:child-1"] == 0.0

    def unexpected_shared_shapley(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("large vote set reached shared Monte Carlo path")

    monkeypatch.setattr(
        "probos.cognitive.crew_trust.compute_shapley_values",
        unexpected_shared_shapley,
    )
    first = derive_completed_crew_trust_effects(
        session_id="session-1",
        session_revision=5,
        child_verifications=tuple(reversed(verifications)),
        facilitator_id="facilitator-1",
        final_verifier_id="final-verifier-1",
        final_confidence=0.8,
        final_evidence_sha256=_SHA_B,
        approval_threshold=0.6,
        use_confidence_weights=True,
    )
    second = derive_completed_crew_trust_effects(
        session_id="session-1",
        session_revision=5,
        child_verifications=verifications,
        facilitator_id="facilitator-1",
        final_verifier_id="final-verifier-1",
        final_confidence=0.8,
        final_evidence_sha256=_SHA_B,
        approval_threshold=0.6,
        use_confidence_weights=True,
    )
    assert [effect.outcome_id for effect in first] == [effect.outcome_id for effect in second]
    producers = [effect for effect in first if effect.role in {"child_producer", "facilitator"}]
    by_work_item = {effect.work_item_id: effect.weight for effect in producers}
    assert by_work_item["child-0"] == pytest.approx(1.0 / 3.0)
    assert by_work_item["child-5"] == pytest.approx(1.0 / 3.0)
    assert by_work_item["session-1"] == pytest.approx(1.0 / 3.0)
    assert by_work_item["child-1"] == 0.1
    assert sum(effect.weight for effect in producers) > 1.0
    child_order = [
        effect.work_item_id
        for effect in first
        if effect.role == "child_producer"
    ]
    assert child_order == sorted(child_order)


def test_large_shapley_all_zero_and_unweighted_fallbacks() -> None:
    votes = [
        Vote(agent_id=f"vote-{index}", approved=True, confidence=0.0)
        for index in range(12)
    ]
    weighted = _all_approved_shapley(votes, use_confidence_weights=True)
    unweighted = _all_approved_shapley(votes, use_confidence_weights=False)
    assert all(value == pytest.approx(1.0 / 12.0) for value in weighted.values())
    assert all(value == pytest.approx(1.0 / 12.0) for value in unweighted.values())

    verifications = tuple(
        _verification(
            work_item_id=f"child-{index}",
            producer_id=f"producer-{index}",
            rounds=(_round(
                0,
                status="accepted",
                verifier_id=f"verifier-{index}",
                confidence=0.0,
            ),),
            accepted=True,
        )
        for index in range(11)
    )
    for confidence_weights in (True, False):
        effects = derive_completed_crew_trust_effects(
            session_id="session-1",
            session_revision=5,
            child_verifications=verifications,
            facilitator_id="facilitator-1",
            final_verifier_id="final-verifier-1",
            final_confidence=0.0,
            final_evidence_sha256=_SHA_B,
            approval_threshold=0.6,
            use_confidence_weights=confidence_weights,
        )
        producers = [
            effect
            for effect in effects
            if effect.role in {"child_producer", "facilitator"}
        ]
        assert len(producers) == 12
        assert all(effect.weight == 0.1 for effect in producers)


def test_small_vote_set_delegates_to_live_exact_shapley(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[int] = []

    def recording_shapley(votes: list[Vote], **kwargs: Any) -> dict[str, float]:
        calls.append(len(votes))
        return compute_shapley_values(votes, **kwargs)

    monkeypatch.setattr(
        "probos.cognitive.crew_trust.compute_shapley_values",
        recording_shapley,
    )
    verification = _verification(
        rounds=(_round(0, status="accepted"),),
        accepted=True,
    )
    derive_completed_crew_trust_effects(
        session_id="session-1",
        session_revision=5,
        child_verifications=(verification,),
        facilitator_id="facilitator-1",
        final_verifier_id="final-verifier-1",
        final_confidence=0.9,
        final_evidence_sha256=_SHA_B,
        approval_threshold=0.6,
        use_confidence_weights=True,
    )
    assert calls == [2]


def test_effect_rejects_invalid_runtime_role() -> None:
    valid = _effect().to_payload()
    valid["role"] = 1
    valid["outcome_id"] = hashlib.sha256(
        json.dumps(
            {key: value for key, value in valid.items() if key != "outcome_id"},
            sort_keys=True,
            separators=(",", ":"),
        ).encode(),
    ).hexdigest()
    with pytest.raises(ValueError, match="crew_trust_effect_invalid"):
        CrewTrustEffect.from_payload(valid)


def test_failure_derivations_reward_rejection_never_verifier_beta() -> None:
    exhausted = _verification(
        rounds=(_round(0, status="refuted"), _round(1, status="refuted")),
        accepted=False,
        failure_code="convergence_exhausted",
    )
    child_effects = derive_convergence_exhausted_effects(
        session_id="session-1",
        session_revision=5,
        child_verifications=(exhausted,),
    )
    assert any(effect.role == "child_producer" and not effect.success for effect in child_effects)
    assert all(effect.success for effect in child_effects if effect.role == "child_verifier")

    accepted = _verification(rounds=(_round(0, status="accepted"),), accepted=True)
    final_effects = derive_final_refutation_effects(
        session_id="session-1",
        session_revision=5,
        facilitator_id="facilitator-1",
        final_verifier_id="final-verifier-1",
        final_evidence_sha256=_SHA_B,
        child_verifications=(accepted,),
    )
    assert any(effect.role == "facilitator" and not effect.success for effect in final_effects)
    assert any(effect.role == "final_verifier" and effect.success for effect in final_effects)
    assert not any(effect.role == "child_producer" for effect in final_effects)


async def test_finalizer_accepted_applies_producer_facilitator_and_verifiers(
    stores: Any,
    tmp_path: Path,
    trust_network: TrustNetwork,
) -> None:
    parent, _thread, service, _contract, children, results = await _executing_case(stores)
    finalizer = await _recorder_finalizer(
        stores,
        tmp_path,
        service=service,
        children=children,
        judge=_ScriptedLLM([_verdict(True), _verdict(True, confidence=0.97)]),
        synth=_ScriptedLLM([_text("Final verified crew result")]),
        executor=_StaticAgenticExecutor(),
        trust=trust_network,
    )
    result = await finalizer.finalize(parent.id, results)
    assert result.completed is True
    raw = trust_network.raw_scores()
    assert raw["producer-1"]["alpha"] > 2.0 and raw["producer-1"]["beta"] == 2.0
    assert raw["facilitator-1"]["alpha"] > 2.0 and raw["facilitator-1"]["beta"] == 2.0
    assert raw["verifier-1"]["alpha"] > 2.0 and raw["verifier-1"]["beta"] == 2.0
    assert await stores.work.list_pending_crew_trust_outcomes(limit=20) == ()
    rows = await _outbox_rows(stores.work)
    assert len(rows) == 4 and all(row[1] == 1 for row in rows)
    before = trust_network.raw_scores()
    event_count = len(trust_network.get_recent_events())
    duplicate = await finalizer.finalize(parent.id, results)
    assert duplicate.completed is False and duplicate.state == "done"
    assert trust_network.raw_scores() == before
    assert len(trust_network.get_recent_events()) == event_count


async def test_finalizer_corrected_success_has_no_producer_beta(
    stores: Any,
    tmp_path: Path,
    trust_network: TrustNetwork,
) -> None:
    parent, _thread, service, _contract, children, results = await _executing_case(stores)
    finalizer = await _recorder_finalizer(
        stores,
        tmp_path,
        service=service,
        children=children,
        judge=_ScriptedLLM([
            _verdict(False, critique="correct it"),
            _verdict(True, critique="correction accepted"),
            _verdict(True, critique="final accepted"),
        ]),
        synth=_ScriptedLLM([_text("Final corrected result")]),
        executor=_StaticAgenticExecutor(final_text="Corrected child result"),
        trust=trust_network,
    )
    result = await finalizer.finalize(parent.id, results)
    assert result.completed is True
    raw = trust_network.raw_scores()
    assert raw["producer-1"]["beta"] == 2.0
    assert raw["producer-1"]["alpha"] > 2.0
    assert raw["verifier-1"]["alpha"] > 3.0


async def test_finalizer_convergence_exhausted_producer_beta_verifier_alpha(
    stores: Any,
    tmp_path: Path,
    trust_network: TrustNetwork,
) -> None:
    parent, _thread, service, _contract, children, results = await _executing_case(stores)
    finalizer = await _recorder_finalizer(
        stores,
        tmp_path,
        service=service,
        children=children,
        judge=_ScriptedLLM([
            _verdict(False, critique="incomplete"),
            _verdict(False, critique="still incomplete"),
            _verdict(False, critique="terminally incomplete"),
        ]),
        synth=_ScriptedLLM([]),
        executor=_StaticAgenticExecutor(final_text="Still incomplete"),
        trust=trust_network,
    )
    result = await finalizer.finalize(parent.id, results)
    assert result.reason == "convergence_exhausted"
    raw = trust_network.raw_scores()
    assert raw["producer-1"]["alpha"] == 2.0 and raw["producer-1"]["beta"] > 2.0
    assert raw["verifier-1"]["alpha"] > 2.0 and raw["verifier-1"]["beta"] == 2.0
    assert "facilitator-1" not in raw
    rows = await _outbox_rows(stores.work)
    assert len(rows) == 4 and all(row[1] == 1 for row in rows)


async def test_finalizer_final_refutation_facilitator_beta_verifier_alpha(
    stores: Any,
    tmp_path: Path,
    trust_network: TrustNetwork,
) -> None:
    parent, _thread, service, _contract, children, results = await _executing_case(stores)
    finalizer = await _recorder_finalizer(
        stores,
        tmp_path,
        service=service,
        children=children,
        judge=_ScriptedLLM([
            _verdict(True),
            _verdict(False, critique="final incomplete"),
        ]),
        synth=_ScriptedLLM([_text("Candidate")]),
        executor=_StaticAgenticExecutor(),
        trust=trust_network,
    )
    result = await finalizer.finalize(parent.id, results)
    assert result.reason == "final_verification_refuted"
    raw = trust_network.raw_scores()
    assert raw["facilitator-1"]["beta"] > 2.0
    assert raw["verifier-1"]["alpha"] > 2.0
    assert "producer-1" not in raw
    rows = await _outbox_rows(stores.work)
    assert len(rows) == 2 and all(row[1] == 1 for row in rows)


@pytest.mark.parametrize(
    ("judge", "synth", "executor", "agents", "reason"),
    [
        ([], [], _StaticAgenticExecutor(), ["producer-1"], "independent_verifier_unavailable"),
        ([RuntimeError("judge down")], [], _StaticAgenticExecutor(), ["producer-1", "verifier-1", "facilitator-1"], "verification_defect"),
        ([_text("not-json")], [], _StaticAgenticExecutor(), ["producer-1", "verifier-1", "facilitator-1"], "verification_defect"),
        ([_verdict(False)], [], _StaticAgenticExecutor(denied_tools=["run_python"]), ["producer-1", "verifier-1", "facilitator-1"], "correction_capability_denied"),
        ([_verdict(False)], [], _StaticAgenticExecutor(stopped_reason="token_budget"), ["producer-1", "verifier-1", "facilitator-1"], "correction_budget_exhausted"),
        ([_verdict(False)], [], _StaticAgenticExecutor(stopped_reason="error"), ["producer-1", "verifier-1", "facilitator-1"], "correction_execution_defect"),
        ([_verdict(True)], [RuntimeError("synthesis down")], _StaticAgenticExecutor(), ["producer-1", "verifier-1", "facilitator-1"], "synthesis_defect"),
        ([], [], _StaticAgenticExecutor(), ["verifier-1", "facilitator-1"], "child_producer_unavailable"),
    ],
)
async def test_neutral_terminal_paths_create_no_effect(
    stores: Any,
    tmp_path: Path,
    trust_network: TrustNetwork,
    judge: list[Any],
    synth: list[Any],
    executor: Any,
    agents: list[str],
    reason: str,
) -> None:
    parent, _thread, service, _contract, children, results = await _executing_case(stores)
    registry_agents = [
        _Agent(agent_id, rank="commander" if agent_id == "facilitator-1" else "ensign")
        for agent_id in agents
    ]
    registry = _Registry(registry_agents)
    runtime = _runtime(stores, tmp_path, service)
    recorder = CrewSessionTrustRecorder(outbox=stores.work, trust_network=trust_network)
    finalizer = _make_finalizer(
        stores=stores,
        service=service,
        registry=registry,
        verifier=_make_verifier(
            llm=_ScriptedLLM(judge),
            stores=stores,
            registry=registry,
            executor=executor,
            runtime=runtime,
        ),
        synthesizer=_make_synthesizer(
            llm=_ScriptedLLM(synth),
            stores=stores,
            runtime=runtime,
        ),
        trust_recorder=recorder,
    )
    assert finalizer is not None
    result = await finalizer.finalize(parent.id, results)
    assert result.reason == reason
    assert trust_network.raw_scores() == {}
    assert await stores.work.list_pending_crew_trust_outcomes(limit=20) == ()


async def test_no_attempt_invalid_child_creates_no_effect(
    stores: Any,
    tmp_path: Path,
    trust_network: TrustNetwork,
) -> None:
    parent, _thread, service, _contract, children, _results = await _executing_case(stores)
    finalizer = await _recorder_finalizer(
        stores,
        tmp_path,
        service=service,
        children=children,
        judge=_ScriptedLLM([]),
        synth=_ScriptedLLM([]),
        executor=_StaticAgenticExecutor(),
        trust=trust_network,
    )
    result = await finalizer.finalize(parent.id, [])
    assert result.reason == "child_result_invalid"
    assert trust_network.raw_scores() == {}
    assert await stores.work.list_pending_crew_trust_outcomes(limit=20) == ()


async def test_publication_failure_and_precommit_cancellation_create_no_effect(
    stores: Any,
    tmp_path: Path,
    trust_network: TrustNetwork,
) -> None:
    parent, _thread, service, _contract, children, results = await _executing_case(stores)
    finalizer = await _recorder_finalizer(
        stores,
        tmp_path,
        service=_ServiceFailure(
            service,
            fail_publish=ValueError("crew_session_publication_conflict"),
        ),
        children=children,
        judge=_ScriptedLLM([_verdict(True), _verdict(True)]),
        synth=_ScriptedLLM([_text("Publication failure candidate")]),
        executor=_StaticAgenticExecutor(),
        trust=trust_network,
    )
    result = await finalizer.finalize(parent.id, results)
    assert result.reason == "result_publication_failed"
    assert trust_network.raw_scores() == {}
    assert await stores.work.list_pending_crew_trust_outcomes(limit=20) == ()
    assert await _outbox_rows(stores.work) == []

    parent, _thread, service, _contract, children, results = await _executing_case(
        stores,
        child_prefix="cancel-child",
    )
    finalizer = await _recorder_finalizer(
        stores,
        tmp_path,
        service=service,
        children=children,
        judge=_ScriptedLLM([asyncio.CancelledError("cancel before terminal")]),
        synth=_ScriptedLLM([]),
        executor=_StaticAgenticExecutor(),
        trust=trust_network,
    )
    with pytest.raises(asyncio.CancelledError, match="cancel before terminal"):
        await finalizer.finalize(parent.id, results)
    assert trust_network.raw_scores() == {}
    assert await stores.work.list_pending_crew_trust_outcomes(limit=20) == ()


async def test_postcommit_cancellation_leaves_committed_outbox_for_retry(
    stores: Any,
    tmp_path: Path,
    trust_network: TrustNetwork,
) -> None:
    parent, _thread, service, _contract, children, results = await _executing_case(stores)

    class _PostCommitCancellationService:
        def __init__(self, delegate: Any) -> None:
            self.delegate = delegate

        def __getattr__(self, name: str) -> Any:
            return getattr(self.delegate, name)

        async def publish_verified_result(self, parent_id: str, **kwargs: Any) -> Any:
            stores.connection.inject_commit_error(
                asyncio.CancelledError("postcommit cancellation"),
                after_commit=True,
            )
            return await self.delegate.publish_verified_result(parent_id, **kwargs)

    finalizer = await _recorder_finalizer(
        stores,
        tmp_path,
        service=_PostCommitCancellationService(service),
        children=children,
        judge=_ScriptedLLM([_verdict(True), _verdict(True)]),
        synth=_ScriptedLLM([_text("Committed candidate")]),
        executor=_StaticAgenticExecutor(),
        trust=trust_network,
    )
    with pytest.raises(asyncio.CancelledError, match="postcommit cancellation"):
        await finalizer.finalize(parent.id, results)
    session = await service.get_session(parent.id)
    assert session is not None and session.state == "done"
    pending = await stores.work.list_pending_crew_trust_outcomes(limit=20)
    assert len(pending) == 4
    assert trust_network.raw_scores() == {}

    recorder = CrewSessionTrustRecorder(outbox=stores.work, trust_network=trust_network)
    assert await recorder.drain_pending() == 4
    assert await recorder.drain_pending() == 0
    assert trust_network.raw_scores()["producer-1"]["alpha"] > 2.0


async def test_success_terminal_outbox_failure_never_commits_done_or_success(
    stores: Any,
    tmp_path: Path,
    trust_network: TrustNetwork,
) -> None:
    parent, _thread, service, _contract, children, results = await _executing_case(stores)
    finalizer = await _recorder_finalizer(
        stores,
        tmp_path,
        service=service,
        children=children,
        judge=_ScriptedLLM([_verdict(True), _verdict(True)]),
        synth=_ScriptedLLM([_text("Candidate")]),
        executor=_StaticAgenticExecutor(),
        trust=trust_network,
    )
    original = stores.connection.execute

    async def fail_outbox(sql: str, parameters: Any = ()) -> Any:
        if "INSERT INTO crew_trust_outbox" in sql:
            raise OSError("outbox insert failed")
        return await original(sql, parameters)

    stores.connection.execute = fail_outbox
    try:
        result = await finalizer.finalize(parent.id, results)
    finally:
        stores.connection.execute = original
    assert result.reason == "result_publication_failed"
    row = await stores.work.get_work_item(parent.id)
    assert row is not None and row.status == "failed"
    assert "crew_synth" not in row.metadata
    assert await _outbox_rows(stores.work) == []
    assert trust_network.raw_scores() == {}


async def test_failure_terminal_outbox_failure_rolls_back_parent_and_effects(
    stores: Any,
    tmp_path: Path,
    trust_network: TrustNetwork,
) -> None:
    parent, _thread, service, _contract, children, results = await _executing_case(stores)
    finalizer = await _recorder_finalizer(
        stores,
        tmp_path,
        service=service,
        children=children,
        judge=_ScriptedLLM([
            _verdict(False),
            _verdict(False),
            _verdict(False),
        ]),
        synth=_ScriptedLLM([]),
        executor=_StaticAgenticExecutor(final_text="Still incomplete"),
        trust=trust_network,
    )
    original = stores.connection.execute

    async def fail_outbox(sql: str, parameters: Any = ()) -> Any:
        if "INSERT INTO crew_trust_outbox" in sql:
            raise OSError("outbox insert failed")
        return await original(sql, parameters)

    stores.connection.execute = fail_outbox
    try:
        with pytest.raises(OSError, match="outbox insert failed"):
            await finalizer.finalize(parent.id, results)
    finally:
        stores.connection.execute = original
    session = await service.get_session(parent.id)
    assert session is not None and session.state == "verifying"
    assert await _outbox_rows(stores.work) == []
    assert trust_network.raw_scores() == {}


def test_work_room_skips_linguistic_trust_and_social_policy_is_unchanged() -> None:
    calls: list[tuple[Any, ...]] = []

    class _Trust:
        def record_outcome(self, *args: Any, **kwargs: Any) -> None:
            calls.append((args, kwargs))

    config = SystemConfig()
    config.group_chat.conversation_trust_enabled = True
    runtime = SimpleNamespace(config=config, trust_network=_Trust())
    replies = [
        {"agent_id": agent_id, "callsign": "", "text": "shared convergent plan"}
        for agent_id in ("a1", "a2", "a3", "a4")
    ]
    _record_conversation_trust(
        runtime,
        SimpleNamespace(id="work", title="plan", task_id="task-1"),
        replies,
        ["a1", "a2", "a3", "a4"],
    )
    assert calls == []

    _record_conversation_trust(
        runtime,
        SimpleNamespace(id="social", title="plan", task_id=None),
        replies,
        ["a1", "a2", "a3", "a4"],
    )
    assert len(calls) == 4
    assert all(kwargs["weight"] == 0.05 for _args, kwargs in calls)

    calls.clear()
    config.group_chat.conversation_trust_enabled = False
    _record_conversation_trust(
        runtime,
        SimpleNamespace(id="off", title="plan", task_id=None),
        replies,
        ["a1", "a2", "a3", "a4"],
    )
    assert calls == []


def test_static_guards_session_path_has_no_legacy_learning_or_out_of_scope_writes() -> None:
    root = Path(__file__).parents[1]
    finalizer = (root / "src/probos/cognitive/crew_finalizer.py").read_text(encoding="utf-8")
    session = (root / "src/probos/cognitive/crew_session.py").read_text(encoding="utf-8")
    crew_trust = (root / "src/probos/cognitive/crew_trust.py").read_text(encoding="utf-8")
    tree = ast.parse(finalizer)
    calls = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    assert "record_outcome" not in calls
    assert "verify" not in calls
    assert "synthesize" not in calls
    assert "verify_for_session" in calls
    assert "synthesize_for_session" in calls
    combined = session + crew_trust
    for forbidden in ("derived_mean", "hebbian", "promotion", "EventType.", "system.yaml"):
        assert forbidden not in combined
    startup = (root / "src/probos/startup/finalize.py").read_text(encoding="utf-8")
    drain_at = startup.index("await trust_drain()")
    recovery_at = startup.index("await crew_start()", drain_at)
    assert drain_at < recovery_at
