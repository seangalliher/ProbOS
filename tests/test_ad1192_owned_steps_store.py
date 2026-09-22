"""M1 storage, writer-fence and accounting crossings for owned crew steps."""

from __future__ import annotations

import asyncio
import cProfile
import dataclasses
import json
import logging
import sqlite3
import time
import uuid
from collections import OrderedDict
from contextvars import ContextVar
from pathlib import Path
from typing import Any

import aiosqlite
import pytest

from probos import work_item_steps as steps
from probos.storage.sqlite_factory import SQLiteConnectionFactory
from probos.workforce import (
    BookableResource, CrewSessionParentCreate, WorkItem, WorkItemPlanInsert, WorkItemStore,
)
from tests.test_ad1192_owned_steps_dm import owned_view_rig


@pytest.mark.parametrize("raw", [
    '{"x":NaN}', '{"x":Infinity}', '{"x":1,"x":2}', '{"x":1e999}',
    '[] trailing', '{"x":', '"\\ud800"',
])
def test_owned_json_loads_invalid_rejects(raw: str) -> None:
    with pytest.raises(steps.OwnedStepsError):
        steps.owned_json_loads(raw)


@pytest.mark.parametrize("raw", [
    '{}', '[null]', '["label"]', '[{"label":"a","status":"done","extra":1}]',
    '[{"label":"a","status":"done","note":false}]',
    '[{"label":"a","status":"done","assigned_to":42}]',
    '[{"label":" ","status":"pending"}]',
])
def test_owned_row_spans_malformed_rejects(raw: str) -> None:
    with pytest.raises(steps.OwnedStepsError):
        steps.owned_row_spans(raw)


def test_owned_projection_preserves_prefix_and_untouched_serialization() -> None:
    raw = '[ { "label" : "\\u03bb ", "status": "done", "note":null },\n' \
        '{"status":"pending", "label":"second", "submitted_by":""} ]'
    suffix = '{"label":"child","status":"pending"}'
    appended = steps.append_owned_rows(raw, (suffix,))
    assert appended[:raw.rfind("]")] == raw[:raw.rfind("]")]
    replaced = steps.replace_owned_row(appended, 1, '{"label":"changed","status":"pending"}')
    before_spans = steps.owned_row_spans(appended)
    after_spans = steps.owned_row_spans(replaced)
    for index in (0, 2):
        start, end = before_spans[index]
        new_start, new_end = after_spans[index]
        assert appended[start:end] == replaced[new_start:new_end]
    assert json.loads(replaced)[0]["note"] is None


def test_owned_projection_empty_and_limits() -> None:
    assert steps.append_owned_rows(" [ ] ", ()) == " [ ] "
    assert json.loads(steps.append_owned_rows(" [ ] ", ('{"label":"x","status":"pending"}',)))
    with pytest.raises(steps.OwnedStepsError):
        steps.replace_owned_row("[]", 0, '{"label":"x","status":"pending"}')
    with pytest.raises(steps.OwnedStepsError):
        steps.owned_row_spans(json.dumps([{"label": "x", "status": "pending"}] * 1001))
    with pytest.raises(steps.OwnedStepsError):
        steps.owned_json_loads('"' + "x" * steps.MAX_OWNED_MANIFEST_BYTES + '"')
    with pytest.raises(steps.OwnedStepsError):
        steps.owned_json_bytes({"opaque": object()})


@pytest.mark.parametrize("ordinal", [0, 1, 2])
@pytest.mark.parametrize("row_json", [
    '{"label":"x","status":"done"}',
    ' \n { "label":"longer \u03bb [{}] \\"quoted\\" replacement", "status":"pending" } \t',
])
def test_owned_projection_delta_reuses_validated_sibling_spans(
    monkeypatch: pytest.MonkeyPatch, ordinal: int, row_json: str,
) -> None:
    identity = uuid.uuid4().hex
    raw = (
        f'[ {{ "label" : "\\u03bb {identity}", "status":"done", "note":null }},\n'
        f'{{"status":"pending", "label":"second {identity}", "submitted_by":""}},\n'
        f'{{"label":"third {identity}","status":"pending"}} ]'
    )
    spans = steps.owned_row_spans(raw)
    start, end = spans[ordinal]
    expected = raw[:start] + row_json + raw[end:]
    decoded_positions: list[int] = []
    original_decode = json.JSONDecoder.raw_decode

    def observe_decode(
        decoder: json.JSONDecoder, source: str, idx: int = 0,
    ) -> tuple[Any, int]:
        if source == expected:
            decoded_positions.append(idx)
        return original_decode(decoder, source, idx)

    monkeypatch.setattr(json.JSONDecoder, "raw_decode", observe_decode)
    result = steps.replace_owned_row(raw, ordinal, row_json)
    result_spans = steps.owned_row_spans(result)

    assert result == expected
    assert decoded_positions == [0]  # Recheck the envelope, not each unchanged row.
    decoder = json.JSONDecoder()
    position = result.index("[") + 1
    oracle = []
    for _ in range(3):
        while result[position].isspace() or result[position] == ",":
            position += 1
        _, row_end = original_decode(decoder, result, position)
        oracle.append((position, row_end))
        position = row_end
    assert result_spans == tuple(oracle)
    assert [result[a:b] for i, (a, b) in enumerate(result_spans) if i != ordinal] == [
        raw[a:b] for i, (a, b) in enumerate(spans) if i != ordinal
    ]
    corrupted = result.replace('"status"', '"unexpected"', 1)
    with pytest.raises(steps.OwnedStepsError):
        steps.owned_row_spans(corrupted)


def test_owned_projection_delta_oversized_result_is_not_memoized() -> None:
    large_row = json.dumps({
        "label": "x" * (steps.MAX_OWNED_MANIFEST_BYTES // 2 + 100), "status": "pending",
    })
    raw = '[{"label":"replace","status":"pending"},' + large_row + "]"

    result = steps.replace_owned_row(raw, 0, large_row)

    assert len(result.encode("utf-8")) > steps.MAX_OWNED_MANIFEST_BYTES
    for _ in range(2):
        with pytest.raises(steps.OwnedStepsError, match="manifest_too_large"):
            steps.owned_row_spans(result)


@pytest.mark.parametrize("row_json", [
    "",
    '{"label":"one","status":"pending"},{"label":"two","status":"done"}',
])
def test_owned_projection_delta_non_single_replacement_keeps_strict_fallback(
    row_json: str,
) -> None:
    raw = '[{"label":"replace","status":"pending"},{"label":"keep","status":"pending"}]'

    result = steps.replace_owned_row(raw, 0, row_json)

    if not row_json:
        with pytest.raises(steps.OwnedStepsError, match="format_invalid"):
            steps.owned_row_spans(result)
    else:
        assert len(steps.owned_row_spans(result)) == 3
        assert [row["label"] for row in json.loads(result)] == ["one", "two", "keep"]


def test_owned_projection_span_cache_retains_only_eight_formats(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    identity = uuid.uuid4().hex
    formats = [
        json.dumps([{"label": f"{identity}-{index}", "status": "pending"}])
        for index in range(9)
    ]
    for raw in formats:
        steps.owned_row_spans(raw)
    decoded_positions: list[int] = []
    original_decode = json.JSONDecoder.raw_decode

    def observe_decode(
        decoder: json.JSONDecoder, source: str, idx: int = 0,
    ) -> tuple[Any, int]:
        if source == formats[0]:
            decoded_positions.append(idx)
        return original_decode(decoder, source, idx)

    monkeypatch.setattr(json.JSONDecoder, "raw_decode", observe_decode)
    spans = steps.owned_row_spans(formats[0])
    assert decoded_positions == [0, 1]
    decoded_positions.clear()
    assert steps.owned_row_spans(formats[0]) == spans
    assert decoded_positions == []


@pytest.mark.asyncio
@pytest.mark.parametrize("legacy", [False, True])
async def test_owned_column_fresh_legacy_repeated_migration_private(
    tmp_path: Path, legacy: bool,
) -> None:
    path = tmp_path / "workforce.db"
    first = WorkItemStore(str(path), tick_interval=1000, connection_factory=SQLiteConnectionFactory())
    await first.start()
    try:
        item = await first.create_work_item(title="manual", metadata={"manual": "keep"})
        expected = item.to_dict()
    finally:
        await first.stop()
    if legacy:
        with sqlite3.connect(path) as db:
            db.execute("ALTER TABLE work_items DROP COLUMN steps_control")
    for _ in range(2):
        store = WorkItemStore(str(path), tick_interval=1000, connection_factory=SQLiteConnectionFactory())
        await store.start()
        try:
            assert (await store.get_work_item(item.id)).to_dict() == expected
        finally:
            await store.stop()
        with sqlite3.connect(path) as db:
            columns = [row[1] for row in db.execute("PRAGMA table_info(work_items)")]
            assert columns.count("steps_control") == 1
            assert db.execute("SELECT steps_control FROM work_items").fetchone() == (None,)
    assert "steps_control" not in WorkItem.__dataclass_fields__
    assert "steps_control" not in expected


@pytest.mark.asyncio
async def test_proposal_tables_observation_dedup_and_cross_store_claim(
    stores: _Harness,
) -> None:
    parent = await stores.first.create_work_item(
        id="proposal-store-parent",
        title="Proposal store parent",
        steps=[{"label": "Manual", "status": "pending"}],
    )
    authority = stores.owner.authority(parent.id)
    first = await stores.first.capture_owned_steps_repair_observation(
        parent.id,
        authority,
    )
    repeated = await stores.second.capture_owned_steps_repair_observation(
        parent.id,
        stores.owner.authority(parent.id),
    )
    assert repeated.observation_id == first.observation_id
    preparation = steps.ProposalPreparation(
        parent_id=parent.id,
        preparation_id="prepare-once",
        request_digest="1" * 64,
        observation_id=first.observation_id,
        kind="replace_manual_prefix",
    )
    claimed = await stores.first.claim_owned_steps_proposal(
        preparation,
        stores.owner.authority(parent.id),
    )
    inspected = await stores.second.claim_owned_steps_proposal(
        preparation,
        stores.owner.authority(parent.id),
    )
    assert claimed.is_new is True
    assert inspected.is_new is False
    assert inspected.proposal_id == claimed.proposal_id
    with pytest.raises(steps.OwnedStepsError, match="preparation_conflict"):
        await stores.second.claim_owned_steps_proposal(
            preparation.model_copy(update={"request_digest": "2" * 64}),
            stores.owner.authority(parent.id),
        )
    with sqlite3.connect(stores.path) as db:
        assert {
            row[0]
            for row in db.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name LIKE 'owned_steps_%'"
            )
        } >= {
            "owned_steps_observations",
            "owned_steps_proposals",
            "owned_steps_retired_children",
        }
        assert db.execute(
            "SELECT COUNT(*) FROM owned_steps_observations WHERE parent_id=?",
            (parent.id,),
        ).fetchone() == (1,)


@pytest.mark.asyncio
async def test_repair_observation_retains_oversized_raw_bytes_outside_manifest(
    stores: _Harness,
) -> None:
    label = "x" * (steps.MAX_OWNED_MANIFEST_BYTES + 64)
    parent = await stores.first.create_work_item(
        id="oversized-observation-parent",
        title="Oversized observation",
        steps=[{"label": label, "status": "pending"}],
    )
    observation = (
        await stores.first.capture_owned_steps_repair_observation(
            parent.id,
            stores.owner.authority(parent.id),
        )
    )
    assert observation.raw_steps is not None
    assert len(observation.raw_steps.encode("utf-8")) > (
        steps.MAX_OWNED_MANIFEST_BYTES
    )
    assert len(observation.source_manifest.encode("utf-8")) < 4096
    with sqlite3.connect(stores.path) as db:
        retained = db.execute(
            "SELECT raw_steps,source_manifest FROM owned_steps_observations "
            "WHERE observation_id=?",
            (observation.observation_id,),
        ).fetchone()
    assert retained == (observation.raw_steps, observation.source_manifest)


@pytest.mark.asyncio
async def test_repair_observation_distinguishes_sql_null_from_json_null(
    stores: _Harness,
) -> None:
    parent = await stores.first.create_work_item(
        id="null-observation-parent",
        title="Null observation",
        steps=None,
    )
    observation = (
        await stores.first.capture_owned_steps_repair_observation(
            parent.id,
            stores.owner.authority(parent.id),
        )
    )
    assert observation.raw_steps == "null"
    assert observation.raw_control is None
    assert observation.steps_digest == steps.owned_digest("null")
    assert observation.control_digest is None


class _FakeContent:
    def __init__(self) -> None:
        self.blobs: dict[str, bytes] = {}

    async def read(self, content_hash: str) -> bytes | None:
        return self.blobs.get(content_hash)


class _FakeOwner:
    def __init__(self) -> None:
        self.grants: dict[object, steps.OwnedStepsGrant] = {}
        self.store: WorkItemStore | None = None
        self.expirations: list[str] = []
        self.refuse_expiry = False

    def authority(
        self, parent_id: str, actor_id: str = "captain", role: str = "captain",
        thread_id: str = "thread-1",
    ) -> steps.OwnedStepsAuthority:
        key = object()
        self.grants[key] = steps.OwnedStepsGrant(parent_id, actor_id, thread_id, role)
        return steps.OwnedStepsAuthority(key)

    async def authorize_owned_steps(
        self, authority: steps.OwnedStepsAuthority, *, parent_id: str, operation: str,
        token: steps.StepViewToken | steps.OwnedStepsPlanToken | steps.OwnedStepExecutionPermit | None,
    ) -> steps.OwnedStepsGrant:
        # Only the injected owner's registered, opaque contexts confer authority.
        grant = self.grants.get(authority.context)
        if grant is None:
            raise steps.OwnedStepsError("owned_steps_authority_denied")
        return grant

    async def expire_owned_steps(self, work_item_id: str, observed_at: float) -> bool:
        self.expirations.append(work_item_id)
        if self.refuse_expiry:
            return False
        assert self.store is not None
        snapshot = await self.store.get_owned_steps(work_item_id)
        index = next(i for i, row in enumerate(snapshot.control.rows) if row.child and row.child.child_id == work_item_id)
        token = _row_token(snapshot, index, actor="ttl")
        result = await self.store.compare_and_set_owned_step(steps.OwnedStepMutation(
            steps.OwnedStepChange(
                operation_id=uuid.uuid4().hex, token=token,
                command=steps.CancelOwnedStepCommand(expired_item_id=work_item_id, observed_at=observed_at),
            ),
            self.authority(snapshot.control.parent_id, "ttl", "ttl"),
        ))
        return result.disposition == "applied"


@dataclasses.dataclass
class _Harness:
    first: WorkItemStore
    second: WorkItemStore
    owner: _FakeOwner
    content: _FakeContent
    path: Path
    events: list[Any]


@pytest.fixture
def membership_conversion_counts(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    counts: list[int] = []
    scope: ContextVar[int | None] = ContextVar("membership_conversion_scope", default=None)
    real_converter = WorkItemStore._row_to_work_item
    real_membership = WorkItemStore._get_owned_crew_children_locked

    def convert(row: aiosqlite.Row) -> WorkItem:
        index = scope.get()
        if index is not None:
            counts[index] += 1
        return real_converter(row)

    async def membership(
        store: WorkItemStore, parent_id: str, control: steps.OwnedStepsControl,
        *, needed_ids: frozenset[str] | None = None,
    ) -> steps.OwnedCrewChildren:
        index = len(counts)
        counts.append(0)
        token = scope.set(index)
        try:
            return await real_membership(store, parent_id, control, needed_ids=needed_ids)
        finally:
            scope.reset(token)

    # Caller edges used to stand in for physical conversions; async profiler
    # under-observation must not change the membership correctness oracle.
    monkeypatch.setattr(WorkItemStore, "_row_to_work_item", staticmethod(convert))
    monkeypatch.setattr(WorkItemStore, "_get_owned_crew_children_locked", membership)
    return counts


@pytest.fixture
def snapshot_digest_facts(monkeypatch: pytest.MonkeyPatch) -> OrderedDict[str, str]:
    facts: OrderedDict[str, str] = OrderedDict()
    monkeypatch.setattr(steps, "_SNAPSHOT_SOURCE_DIGESTS", facts)
    return facts


@pytest.fixture
async def stores(tmp_path: Path):
    path = tmp_path / "shared.db"
    owner, content = _FakeOwner(), _FakeContent()
    events: list[Any] = []
    def emit(*args: Any, **kwargs: Any) -> None:
        events.append((args, kwargs))
    first = WorkItemStore(
        str(path), tick_interval=1000, owned_steps_authorizer=owner,
        owned_steps_ttl_owner=owner, owned_steps_content=content, emit_event=emit,
    )
    second = WorkItemStore(
        str(path), tick_interval=1000, owned_steps_authorizer=owner,
        owned_steps_ttl_owner=owner, owned_steps_content=content, emit_event=emit,
    )
    await first.start()
    await second.start()
    owner.store = first
    for store in (first, second):
        for name in ("agent-a", "agent-b", "agent-c"):
            store.register_resource(BookableResource(resource_id=name, capacity=4))
    try:
        yield _Harness(first, second, owner, content, path, events)
    finally:
        await second.stop()
        await first.stop()


def _database(harness: _Harness) -> tuple[Any, ...]:
    with sqlite3.connect(harness.path) as db:
        return tuple(
            (table, tuple(db.execute(f"SELECT * FROM {table} ORDER BY 1")))
            for table in (
                "work_items", "bookings", "booking_timestamps", "booking_journals",
                "resource_requirements", "crew_trust_outbox", "crew_delivery_outbox",
                "owned_steps_journal",
            )
        )


def _raw_steps(harness: _Harness, parent_id: str) -> str:
    with sqlite3.connect(harness.path) as db:
        return db.execute("SELECT steps FROM work_items WHERE id = ?", (parent_id,)).fetchone()[0]


def _row_token(
    snapshot: steps.OwnedStepsSnapshot, index: int, *, actor: str = "captain",
    view: str = "view-1",
) -> steps.StepViewToken:
    control = snapshot.control
    row = control.rows[index]
    return steps.StepViewToken(
        parent_id=control.parent_id, incarnation=control.incarnation,
        layout_revision=control.layout_revision, plan_revision=control.plan_revision,
        plan_digest=control.plan_digest, step_id=row.step_id, row_revision=row.revision,
        row_digest=row.digest, source_digest=row.source_digest,
        assignment_epoch=row.assignment_epoch, actor_id=actor, thread_id=control.thread_id,
        view_id=view, turn_id="turn-1",
    )


def _evidence_digest(evidence: Any) -> str:
    return steps.owned_digest(steps.owned_json_bytes(evidence.model_dump(mode="json")))


def _plan_token(snapshot: steps.OwnedStepsSnapshot) -> steps.OwnedStepsPlanToken:
    control = snapshot.control
    return steps.OwnedStepsPlanToken(
        parent_id=control.parent_id, incarnation=control.incarnation,
        layout_revision=control.layout_revision, plan_revision=control.plan_revision,
        plan_digest=control.plan_digest, steps_digest=control.steps_digest,
        source_digest=snapshot.source_digest, actor_id="captain", thread_id=control.thread_id,
        view_id="view-1", turn_id="turn-1",
    )


async def _legacy_plan(
    harness: _Harness, *, prefix: str = "[]", bookings: bool = False,
    children_count: int = 2, ttl: bool = False, historical: bool = False,
    child_gate: bool = False, work_type: str = "task",
) -> tuple[WorkItem, tuple[WorkItem, ...]]:
    store = harness.first
    parent = await store.create_work_item(
        id="parent-1", title="Parent", steps=json.loads(prefix),
        metadata={"manual_data": {"keep": None}, "steps_gate_completion": True, "facilitator": "manual-person"},
    )
    if prefix != json.dumps(json.loads(prefix)):
        with sqlite3.connect(harness.path) as db:
            db.execute("UPDATE work_items SET steps = ? WHERE id = ?", (prefix, parent.id))
    children: list[WorkItem] = []
    for index in range(children_count):
        child = await store.create_work_item(
            id=f"child-{children_count-index}", title=f"Child {index}", parent_id=parent.id,
            assigned_to=None if bookings else "agent-a",
            metadata={"spec_id": f"spec-{index}", **({"steps_gate_completion": True} if child_gate else {})},
            ttl_seconds=1 if ttl else None,
            created_at=time.time() - 100 if ttl else time.time(),
            status="done" if historical else store.work_type_registry.get_initial_status(work_type),
            verification={"accepted": True} if historical else {},
            actual_tokens=9 if historical else 0,
            steps=[{"label": "existing child gate", "status": "pending"}] if child_gate else [],
            work_type=work_type,
        )
        if bookings:
            assert await store.assign_work_item(child.id, "agent-a")
            child = await store.get_work_item(child.id)
        children.append(child)
    commitments = tuple(steps.OwnedStepChild(
        child_id=child.id, spec_id=child.metadata["spec_id"],
        commitment_digest=steps.owned_child_commitment(child.to_dict()),
    ) for child in children)
    seed = steps.OwnedStepsSeed(
        steps.OwnedStepsSeedPlan(
            parent_id=parent.id, owner_kind="legacy", thread_id="thread-1",
            facilitator_id="facilitator-1", incarnation=uuid.uuid4().hex,
            plan_digest=steps.owned_digest(steps.owned_json_bytes([c.model_dump(mode="json") for c in commitments])),
            expected_steps_digest=steps.owned_digest(prefix), children=commitments,
        ),
        harness.owner.authority(parent.id),
    )
    await store.adopt_child_plan_with_parent_metadata(
        parent.id, expected_parent_metadata=parent.metadata, expected_status=parent.status,
        expected_assigned_to=parent.assigned_to, parent_patch={},
        expected_children=tuple(sorted(children, key=lambda child: child.id)), steps_seed=seed,
    )
    return parent, tuple(children)


async def _adopt(harness: _Harness, parent_id: str) -> steps.OwnedStepMutation:
    authority = harness.owner.authority(parent_id)
    preview = await harness.first.preview_owned_steps_adoption(
        parent_id, authority=authority, view_id="adopt-view", turn_id="turn-1",
    )
    mutation = steps.OwnedStepMutation(steps.OwnedStepChange(
        operation_id=uuid.uuid4().hex, token=preview.token, command=steps.AdoptOwnedStepsCommand(preview=preview),
    ), authority)
    await harness.first.compare_and_set_owned_step(mutation)
    return mutation


async def _apply(
    harness: _Harness, snapshot: steps.OwnedStepsSnapshot, index: int,
    command: steps.OwnedStepsCommand, *, actor: str = "captain", role: str = "captain",
    store: WorkItemStore | None = None, operation_id: str | None = None,
) -> tuple[steps.OwnedStepMutationResult, steps.OwnedStepMutation]:
    mutation = steps.OwnedStepMutation(steps.OwnedStepChange(
        operation_id=operation_id or uuid.uuid4().hex,
        token=(command.submission.permit if isinstance(command, steps.SubmitOwnedStepCommand)
               else command.result.permit if isinstance(command, steps.ReviewOwnedStepCommand)
               else _row_token(snapshot, index, actor=actor)),
        command=command,
    ), harness.owner.authority(snapshot.control.parent_id, actor, role))
    return await (store or harness.first).compare_and_set_owned_step(mutation), mutation


@pytest.mark.asyncio
@pytest.mark.parametrize("prefix", [
    " [ \n ] \t",
    '[ { "label":"manual", "status":"pending", "note":null } \n ] \t',
    '[ {"label":"\\u03bb [] ,", "status":"pending"},\n {"status":"pending","label":"keep"} ]',
])
async def test_current_manual_prefix_retains_authorized_bytes_and_immutable_audit(
    stores: _Harness, prefix: str,
) -> None:
    parent, _ = await _legacy_plan(stores, prefix=prefix)
    before = await stores.first.get_owned_steps(parent.id)
    assert before.control.current_manual_prefix_json() == prefix
    current_prefix = prefix
    if before.control.manual_prefix_length:
        await _apply(stores, before, 0, steps.ManualStepCommand(kind="edit_note", note="current note"))
        edited = await stores.first.get_owned_steps(parent.id)
        current_prefix = steps.replace_owned_row(prefix, 0, edited.control.rows[0].todo_json)
        assert edited.control.current_manual_prefix_json() == current_prefix
        await _adopt(stores, parent.id)
    active = await stores.first.get_owned_steps(parent.id)
    assert active.control.current_manual_prefix_json() == current_prefix
    assert active.control.original_steps_json == prefix
    assert active.control.authorized_steps_json == steps.append_owned_rows(
        current_prefix, tuple(row.todo_json for row in active.control.rows[active.control.manual_prefix_length:]),
    )


@pytest.mark.asyncio
async def test_seed_preserves_manual_bytes_gate_bookings_and_explicit_adoption(stores: _Harness) -> None:
    prefix = '[ { "label" : "\\u03bb ", "status":"done", "note":null },\n' \
        '{"label":"Manual two", "status":"pending", "assigned_to": "", "submitted_by":null} ]'
    parent, children = await _legacy_plan(stores, prefix=prefix, bookings=True)
    before_bookings = await stores.first.list_bookings(limit=100)
    before = await stores.first.get_owned_steps(parent.id)
    assert before.control.mode == "awaiting_adoption"
    assert _raw_steps(stores, parent.id) == prefix
    assert before.control.original_steps_json == prefix
    assert [r.child.child_id for r in before.control.rows if r.child] == [c.id for c in children]
    assert (await stores.second.get_owned_steps(children[0].id)).control == before.control
    with pytest.raises(steps.OwnedStepsError, match="not_active"):
        await _apply(stores, before, 2, steps.StartOwnedStepCommand(execution_nonce="nonce"),
                     actor="agent-a", role="executor")
    mutation = await _adopt(stores, parent.id)
    after = await stores.first.get_owned_steps(parent.id)
    raw = _raw_steps(stores, parent.id)
    assert raw[:prefix.rfind("]")] == prefix[:prefix.rfind("]")]
    assert json.loads(raw)[:2] == json.loads(prefix)
    assert [r["label"] for r in json.loads(raw)[2:]] == [c.title for c in children]
    assert after.control.mode == "active"
    assert after.control.layout_revision == before.control.layout_revision + 1
    assert after.control.original_steps_json == prefix
    assert (await stores.first.get_work_item(parent.id)).metadata == parent.metadata
    assert await stores.first.list_bookings(limit=100) == before_bookings
    data, events = _database(stores), list(stores.events)
    assert (await stores.second.compare_and_set_owned_step(mutation)).disposition == "duplicate"
    assert _database(stores) == data and stores.events == events


@pytest.mark.asyncio
async def test_seed_empty_activates_exact_plan_and_stays_private(stores: _Harness) -> None:
    parent, children = await _legacy_plan(stores, prefix=" [ ] ")
    snapshot = await stores.first.get_owned_steps(parent.id)
    assert snapshot.control.mode == "active"
    assert snapshot.control.manual_prefix_length == 0
    assert [r.child.child_id for r in snapshot.control.rows] == [c.id for c in children]
    public = (await stores.first.get_work_item(parent.id)).to_dict()
    assert set(public) == set(WorkItem().to_dict())
    assert all(set(row) <= {"label", "status", "assigned_to", "submitted_by", "confirmed_by", "note"} for row in public["steps"])
    assert "steps_control" not in public["metadata"]
    with pytest.raises(steps.OwnedStepsError, match="not_pending"):
        await stores.first.preview_owned_steps_adoption(
            parent.id, authority=stores.owner.authority(parent.id), view_id="view", turn_id="turn",
        )


@pytest.mark.asyncio
async def test_two_stores_sibling_success_same_row_stale_and_foreign_reject(stores: _Harness) -> None:
    prefix = '[{"label":"one","status":"pending"},{"label":"two","status":"pending"}]'
    parent, _ = await _legacy_plan(stores, prefix=prefix)
    await _adopt(stores, parent.id)
    snapshot = await stores.first.get_owned_steps(parent.id)
    outcomes = await asyncio.gather(
        _apply(stores, snapshot, 0, steps.ManualStepCommand(kind="manual_submit")),
        _apply(stores, snapshot, 1, steps.ManualStepCommand(kind="manual_submit"), store=stores.second),
    )
    assert all(result.disposition == "applied" for result, _ in outcomes)
    assert [r["status"] for r in (await stores.first.get_work_item(parent.id)).steps[:2]] == ["submitted", "submitted"]
    before, events = _database(stores), list(stores.events)
    with pytest.raises(steps.OwnedStepsError, match="row_conflict"):
        await _apply(stores, snapshot, 0, steps.ManualStepCommand(kind="edit_note", note="stale"))
    token = _row_token(snapshot, 1).model_copy(update={"step_id": "foreign-row"})
    with pytest.raises(steps.OwnedStepsError, match="row_missing"):
        await stores.first.compare_and_set_owned_step(steps.OwnedStepMutation(
            steps.OwnedStepChange(operation_id="foreign", token=token, command=steps.ManualStepCommand(kind="manual_submit")),
            stores.owner.authority(parent.id),
        ))
    assert _database(stores) == before and stores.events == events


@pytest.mark.asyncio
async def test_two_stores_same_row_race_has_one_winner(stores: _Harness) -> None:
    parent, _ = await _legacy_plan(stores, prefix='[{"label":"manual","status":"pending"}]')
    await _adopt(stores, parent.id)
    snapshot = await stores.first.get_owned_steps(parent.id)
    outcomes = await asyncio.gather(
        _apply(stores, snapshot, 0, steps.ManualStepCommand(kind="edit_note", note="first")),
        _apply(stores, snapshot, 0, steps.ManualStepCommand(kind="edit_note", note="second"), store=stores.second),
        return_exceptions=True,
    )
    assert sum(isinstance(result, steps.OwnedStepsError) for result in outcomes) == 1
    assert sum(isinstance(result, tuple) for result in outcomes) == 1
    assert (await stores.first.get_owned_steps(parent.id)).control.rows[0].revision == 2


@pytest.mark.asyncio
async def test_canonical_install_seed_is_one_transaction_and_invalid_seed_rolls_back(stores: _Harness) -> None:
    metadata = {"crew_session": {"thread_id": "thread-1", "facilitator_id": "facilitator-1"}}
    async with stores.first.claim_crew_session_admission_port().reserve() as reservation:
        parent = await reservation.create_parent(CrewSessionParentCreate(
            id="canonical-parent", title="Canonical", description="Canonical plan",
            assigned_to="facilitator-1", created_by="captain", metadata=metadata,
        ))
    child = WorkItemPlanInsert(
        id="canonical-child", title="Child", description="Task", work_type="task", priority=3,
        depends_on=(), assigned_to="agent-a", created_by="facilitator-1", trust_requirement=0.0,
        required_capabilities=(), metadata={"spec_id": "spec"},
    )
    commitment = steps.OwnedStepChild(child_id=child.id, spec_id="spec", commitment_digest="c" * 64)
    patch = {"crew_recovery": {"plan": {
        "plan_hash": "d" * 64, "children": [{"child_id": child.id, "spec_id": "spec", "row_hash": "c" * 64}],
    }}}
    seed_plan = steps.OwnedStepsSeedPlan(
        parent_id=parent.id, owner_kind="canonical", thread_id="thread-1", facilitator_id="facilitator-1",
        incarnation=uuid.uuid4().hex, plan_digest="d" * 64,
        expected_steps_digest=steps.owned_digest("[]"), children=(commitment,),
    )
    kwargs = dict(
        expected_parent_metadata=metadata, expected_status=parent.status, expected_assigned_to=parent.assigned_to,
        parent_patch=patch, children=(child,),
    )
    before, events = _database(stores), list(stores.events)
    with pytest.raises(steps.OwnedStepsError, match="seed_conflict"):
        await stores.first.install_child_plan_with_parent_metadata(
            parent.id, **kwargs,
            steps_seed=steps.OwnedStepsSeed(seed_plan.model_copy(update={"expected_steps_digest": "0" * 64}),
                                            stores.owner.authority(parent.id)),
        )
    assert _database(stores) == before and stores.events == events
    installed, children = await stores.first.install_child_plan_with_parent_metadata(
        parent.id, **kwargs, steps_seed=steps.OwnedStepsSeed(seed_plan, stores.owner.authority(parent.id)),
    )
    snapshot = await stores.second.get_owned_steps(parent.id)
    assert snapshot.control.owner_kind == "canonical" and snapshot.control.mode == "active"
    assert children[0].parent_id == parent.id
    assert installed.metadata["crew_recovery"] == patch["crew_recovery"]
    assert len(installed.steps) == len(snapshot.control.rows) == 1
    before, events = _database(stores), list(stores.events)
    replay, repeated_children = await stores.second.install_child_plan_with_parent_metadata(
        parent.id, **kwargs, steps_seed=steps.OwnedStepsSeed(seed_plan, stores.owner.authority(parent.id)),
    )
    assert replay == installed and repeated_children == children
    assert _database(stores) == before and stores.events == events


def _submission(
    harness: _Harness, permit: steps.OwnedStepExecutionPermit, *, status: str = "done", tokens: int = 7,
) -> steps.SubmitOwnedStepCommand:
    output = b"Exact original worker output"
    digest = steps.owned_digest(output)
    harness.content.blobs[digest] = output
    execution = dict(
        version=1, parent_id=permit.parent_id, work_item_id=permit.child_id,
        thread_id="thread-1", assigned_to=permit.assignee_id, status=status,
        stopped_reason="complete" if status == "done" else "error",
        output_summary="Exact original worker output", tool_trace_ref=None, artifact_refs=[],
        tokens_used=tokens, started_at=1.0, finished_at=2.0, blocked_dependency_ids=[],
    )
    return steps.SubmitOwnedStepCommand(submission=steps.OwnedStepSubmission(
        permit=permit, execution_json=steps.owned_json_bytes(execution).decode("utf-8"),
        output=steps.OwnedContentReference(content_hash=digest, mime="text/plain", size_bytes=len(output)),
    ))


@pytest.mark.asyncio
@pytest.mark.parametrize("bookings", [False, True])
async def test_reassign_assignment_aba_fences_old_views_and_preserves_booking_population(
    stores: _Harness, bookings: bool,
) -> None:
    parent, children = await _legacy_plan(stores, bookings=bookings)
    initial = await stores.first.get_owned_steps(parent.id)
    sibling_before = await stores.first.get_work_item(children[1].id)
    initial_bookings = await stores.first.list_bookings(work_item_id=children[0].id)
    result, _ = await _apply(stores, initial, 0, steps.ReassignOwnedStepCommand(assignee_id="agent-b"))
    assert result.snapshot.control.rows[0].assignment_epoch == 2
    result, mutation = await _apply(
        stores, result.snapshot, 0, steps.ReassignOwnedStepCommand(assignee_id="agent-a"), store=stores.second,
    )
    assert result.snapshot.control.rows[0].assignment_epoch == 3
    assert (await stores.first.get_work_item(children[0].id)).assigned_to == "agent-a"
    assert (await stores.first.get_work_item(children[1].id)) == sibling_before
    current_bookings = await stores.first.list_bookings(work_item_id=children[0].id)
    if bookings:
        assert len(current_bookings) == len(initial_bookings) + 2
        assert len([b for b in current_bookings if b.status == "scheduled"]) == 1
        assert len([b for b in current_bookings if b.status == "cancelled"]) == 2
        assert {b.requirement_id for b in current_bookings} == {b.requirement_id for b in initial_bookings}
    else:
        assert current_bookings == initial_bookings == []
    before, events = _database(stores), list(stores.events)
    with pytest.raises(steps.OwnedStepsError, match="row_conflict"):
        await _apply(stores, initial, 0, steps.StartOwnedStepCommand(execution_nonce="old"),
                     actor="agent-a", role="executor")
    assert (await stores.first.compare_and_set_owned_step(mutation)).disposition == "duplicate"
    assert _database(stores) == before and stores.events == events


@pytest.mark.asyncio
@pytest.mark.parametrize("pause", [False, True])
@pytest.mark.parametrize("status", ["done", "failed"])
async def test_permit_submission_booking_journal_tokens_are_one_atomic_once_only_crossing(
    stores: _Harness, pause: bool, status: str,
) -> None:
    parent, children = await _legacy_plan(stores, bookings=True)
    initial = await stores.first.get_owned_steps(parent.id)
    sibling_booking = (await stores.first.list_bookings(work_item_id=children[1].id))[0]
    started, start_mutation = await _apply(
        stores, initial, 0, steps.StartOwnedStepCommand(execution_nonce="execute-once"),
        actor="agent-a", role="executor",
    )
    permit = started.permit
    assert started.disposition == "new" and permit is not None
    assert (await stores.first.get_work_item(children[0].id)).status == "in_progress"
    assert (await stores.first.get_booking(permit.booking_id)).status == "active"
    before, events = _database(stores), list(stores.events)
    repeated = await stores.second.compare_and_set_owned_step(start_mutation)
    assert repeated.disposition == "already_started" and repeated.permit == permit
    assert _database(stores) == before and stores.events == events
    snapshot = started.snapshot
    if pause:
        before_child = await stores.first.get_work_item(children[0].id)
        paused, pause_mutation = await _apply(stores, snapshot, 0, steps.AccountingOwnedStepCommand(
            kind="pause_accounting", booking_id=permit.booking_id, resource_id="agent-a",
        ))
        assert paused.snapshot.control.rows[0].permit == _evidence_digest(permit)
        assert await stores.second.get_owned_step_evidence(
            parent.id, permit.incarnation, "permit", paused.snapshot.control.rows[0].permit,
        ) == permit
        assert paused.snapshot.control.rows[0].permit_state == "started"
        assert await stores.first.get_work_item(children[0].id) == before_child
        assert (await stores.first.get_booking(permit.booking_id)).status == "on_break"
        snapshot = paused.snapshot
        before, events = _database(stores), list(stores.events)
        assert (await stores.second.compare_and_set_owned_step(pause_mutation)).disposition == "duplicate"
        assert _database(stores) == before and stores.events == events
    submitted, mutation = await _apply(
        stores, snapshot, 0, _submission(stores, permit, status=status), actor="agent-a", role="executor",
    )
    child = await stores.first.get_work_item(children[0].id)
    booking = await stores.first.get_booking(permit.booking_id)
    journal = await stores.first.get_booking_journal(permit.booking_id)
    assert child.status == status and child.actual_tokens == 7
    assert booking.status == "completed" and booking.total_tokens_consumed == 7
    assert child.verification == {}
    assert submitted.snapshot.control.rows[0].reviewed_result is None
    assert json.loads(submitted.snapshot.control.rows[0].todo_json)["status"] == ("submitted" if status == "done" else "rejected")
    assert submitted.snapshot.control.rows[0].permit_state == ("submitted" if status == "done" else "terminal")
    assert [entry.journal_type for entry in journal] == (["idle", "working", "break"] if pause else ["idle", "working"])
    assert sum(entry.billable for entry in journal) == 1
    assert (await stores.first.get_booking(sibling_booking.id)) == sibling_booking
    before, events = _database(stores), list(stores.events)
    assert (await stores.second.compare_and_set_owned_step(mutation)).disposition == "duplicate"
    # V1 recomputed this acknowledgement from the latest row. A journal replay
    # retains the original observation, and can never issue fresh execution.
    replay = await stores.second.compare_and_set_owned_step(start_mutation)
    assert replay.disposition == "already_started"
    assert replay.snapshot is None and replay.receipt == started.receipt
    assert _database(stores) == before and stores.events == events


@pytest.mark.asyncio
async def test_clock_resume_capacity_stale_views_and_permit_are_independent(stores: _Harness) -> None:
    for store in (stores.first, stores.second):
        store.register_resource(BookableResource(resource_id="agent-a", capacity=1))
    parent, children = await _legacy_plan(stores, bookings=True, children_count=1)
    initial = await stores.first.get_owned_steps(parent.id)
    started, _ = await _apply(stores, initial, 0, steps.StartOwnedStepCommand(execution_nonce="clock"),
                              actor="agent-a", role="executor")
    permit = started.permit
    paused, _ = await _apply(stores, started.snapshot, 0, steps.AccountingOwnedStepCommand(
        kind="pause_accounting", booking_id=permit.booking_id, resource_id="agent-a",
    ))
    unrelated = await stores.first.create_work_item(title="Other scheduling work")
    other_booking = await stores.first.assign_work_item(unrelated.id, "agent-a")
    assert other_booking is not None
    command = steps.AccountingOwnedStepCommand(kind="resume_accounting", booking_id=permit.booking_id, resource_id="agent-a")
    before, events = _database(stores), list(stores.events)
    with pytest.raises(steps.OwnedStepsError, match="booking_capacity"):
        await _apply(stores, paused.snapshot, 0, command)
    with pytest.raises(steps.OwnedStepsError, match="row_conflict"):
        await _apply(stores, started.snapshot, 0, command, store=stores.second)
    assert _database(stores) == before and stores.events == events
    await stores.first.cancel_booking(other_booking.id)
    resumed, mutation = await _apply(stores, paused.snapshot, 0, command)
    assert (await stores.first.get_booking(permit.booking_id)).status == "active"
    assert resumed.snapshot.control.rows[0].permit == _evidence_digest(permit)
    assert resumed.snapshot.control.rows[0].assignment_epoch == 1
    assert (await stores.first.get_work_item(children[0].id)).status == "in_progress"
    before, events = _database(stores), list(stores.events)
    assert (await stores.second.compare_and_set_owned_step(mutation)).disposition == "duplicate"
    assert _database(stores) == before and stores.events == events


@pytest.mark.asyncio
@pytest.mark.parametrize("pause", [False, True])
async def test_cancel_revokes_late_submission_and_only_matching_booking(stores: _Harness, pause: bool) -> None:
    parent, children = await _legacy_plan(stores, bookings=True)
    started, _ = await _apply(
        stores, await stores.first.get_owned_steps(parent.id), 0,
        steps.StartOwnedStepCommand(execution_nonce="late"), actor="agent-a", role="executor",
    )
    sibling = await stores.first.get_work_item(children[1].id)
    sibling_booking = (await stores.first.list_bookings(work_item_id=sibling.id))[0]
    cancel_view = started.snapshot
    if pause:
        paused, _ = await _apply(stores, cancel_view, 0, steps.AccountingOwnedStepCommand(
            kind="pause_accounting", booking_id=started.permit.booking_id, resource_id="agent-a",
        ))
        cancel_view = paused.snapshot
    cancelled, mutation = await _apply(stores, cancel_view, 0, steps.CancelOwnedStepCommand())
    row = cancelled.snapshot.control.rows[0]
    assert row.permit_state == "revoked" and row.assignment_epoch == 2 and row.permit == _evidence_digest(started.permit)
    assert (await stores.first.get_booking(row.booking_id)).status == "cancelled"
    assert (await stores.first.get_work_item(children[0].id)).status == "cancelled"
    assert await stores.first.get_work_item(sibling.id) == sibling
    assert await stores.first.get_booking(sibling_booking.id) == sibling_booking
    before, events = _database(stores), list(stores.events)
    for snapshot in (started.snapshot, cancelled.snapshot):
        with pytest.raises(steps.OwnedStepsError, match="row_conflict|submission_conflict"):
            await _apply(stores, snapshot, 0, _submission(stores, started.permit), actor="agent-a", role="executor")
    assert (await stores.second.compare_and_set_owned_step(mutation)).disposition == "duplicate"
    refused, refused_mutation = await _apply(stores, cancelled.snapshot, 0, steps.StartOwnedStepCommand(execution_nonce="again"),
                              actor="agent-a", role="executor")
    assert refused.disposition == "terminal"
    # A distinct read-only admission observation gets a durable acknowledgement,
    # not another worker or any work/booking/accounting mutation.
    after = _database(stores)
    assert dict(after) | {"owned_steps_journal": dict(before)["owned_steps_journal"]} == dict(before)
    assert len(dict(after)["owned_steps_journal"]) == len(dict(before)["owned_steps_journal"]) + 1
    assert stores.events == events
    replay = await stores.second.compare_and_set_owned_step(refused_mutation)
    assert replay.disposition == "terminal" and replay.receipt == refused.receipt and replay.snapshot is None
    assert _database(stores) == after


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["version_bool", "unknown", "missing", "revision_string", "row_unknown", "digest", "nonfinite"])
async def test_private_control_strict_rejects_corrupt_records_without_rebaseline(stores: _Harness, change: str) -> None:
    parent, _ = await _legacy_plan(stores)
    snapshot = await stores.first.get_owned_steps(parent.id)
    raw = snapshot.control.model_dump(mode="json")
    if change == "version_bool":
        raw["version"] = True
    elif change == "unknown":
        raw["new_state"] = {}
    elif change == "missing":
        del raw["observation_revision"]
    elif change == "revision_string":
        raw["layout_revision"] = "1"
    elif change == "row_unknown":
        raw["rows"][0]["authority"] = "captain"
    elif change == "digest":
        raw["rows"][0]["digest"] = "0" * 64
    else:
        raw["observation_revision"] = float("nan")
    with sqlite3.connect(stores.path) as db:
        db.execute("UPDATE work_items SET steps_control = ? WHERE id = ?", (json.dumps(raw), parent.id))
    before = _database(stores)
    with pytest.raises(steps.OwnedStepsError):
        await stores.second.get_owned_steps(parent.id)
    assert _database(stores) == before


@pytest.mark.asyncio
async def test_source_drift_and_new_incarnation_refuse_old_authority(stores: _Harness) -> None:
    parent, children = await _legacy_plan(stores)
    snapshot = await stores.first.get_owned_steps(parent.id)
    with sqlite3.connect(stores.path) as db:
        db.execute("UPDATE work_items SET assigned_to = 'agent-b' WHERE id = ?", (children[0].id,))
    before, events = _database(stores), list(stores.events)
    with pytest.raises(steps.OwnedStepsError, match="source_conflict"):
        await _apply(stores, snapshot, 0, steps.ReassignOwnedStepCommand(assignee_id="agent-c"))
    assert _database(stores) == before and stores.events == events
    with sqlite3.connect(stores.path) as db:
        db.execute("UPDATE work_items SET assigned_to = 'agent-a' WHERE id = ?", (children[0].id,))
        # Simulate an independently committed fresh plan incarnation, not a
        # release/export: historical viewed authority must still be rejected.
        fresh = snapshot.control.model_copy(update={"incarnation": uuid.uuid4().hex})
        db.execute("UPDATE work_items SET steps_control = ? WHERE id = ?", (fresh.model_dump_json(), parent.id))
    before = _database(stores)
    with pytest.raises(steps.OwnedStepsError, match="plan_conflict"):
        await _apply(stores, snapshot, 0, steps.ReassignOwnedStepCommand(assignee_id="agent-b"))
    assert _database(stores) == before


@pytest.mark.asyncio
async def test_reopen_retains_permits_and_exact_projection_repair_without_reexecution(stores: _Harness) -> None:
    parent, _ = await _legacy_plan(stores, prefix='[{"label":"manual","status":"pending","note":null}]')
    await _adopt(stores, parent.id)
    initial = await stores.first.get_owned_steps(parent.id)
    started, start_mutation = await _apply(stores, initial, 1, steps.StartOwnedStepCommand(execution_nonce="interrupted"),
                                          actor="agent-a", role="executor")
    await stores.second.stop()
    await stores.first.stop()
    await stores.first.start()
    await stores.second.start()
    before, events = _database(stores), list(stores.events)
    resumed = await stores.second.compare_and_set_owned_step(start_mutation)
    assert resumed.disposition == "already_started"
    assert resumed.permit == started.permit
    assert _database(stores) == before and stores.events == events
    authorized = _raw_steps(stores, parent.id)
    with sqlite3.connect(stores.path) as db:
        db.execute("UPDATE work_items SET steps = ? WHERE id = ?", ("not-json", parent.id))
    read = await stores.first.get_owned_steps(parent.id)
    assert read.projection_matches is False
    assert read.control.authorized_steps_json == authorized
    before = _database(stores)
    with pytest.raises(steps.OwnedStepsError, match="projection_conflict"):
        await _apply(stores, read, 0, steps.ManualStepCommand(kind="edit_note", note="launder"))
    assert _database(stores) == before
    result = await stores.second.compare_and_set_owned_step(steps.OwnedStepMutation(
        steps.OwnedStepChange(operation_id="repair", token=_plan_token(read),
                              command=steps.RepairOwnedStepsCommand(observed_steps_digest=steps.owned_digest("not-json"))),
        stores.owner.authority(parent.id),
    ))
    assert result.snapshot.projection_matches and _raw_steps(stores, parent.id) == authorized
    assert result.snapshot.control.rows == read.control.rows
    assert result.snapshot.control.original_steps_json == read.control.original_steps_json
    assert result.snapshot.control.layout_revision == read.control.layout_revision + 1


@pytest.mark.asyncio
@pytest.mark.parametrize("writer", [
    "create_child", "reparent_into", "reparent_out", "delete_parent", "delete_child",
    "update_status", "update_assignment", "update_tokens", "update_verification", "update_steps",
    "update_title", "update_ttl", "replace_metadata", "merge_gate", "merge_facilitator",
    "merge_execution", "merge_plan", "merge_tokens", "merge_status",
    "set_steps", "update_step", "assign", "claim", "unassign", "transition",
    "assignment_cas", "verification_cas", "publication_cas", "provisioning_clear",
    "provisioning_delete", "provisioning_fail", "untyped_adoption",
])
async def test_every_direct_managed_work_item_writer_refuses_without_any_side_effect(
    stores: _Harness, writer: str,
) -> None:
    parent, children = await _legacy_plan(stores, bookings=True)
    child = await stores.first.get_work_item(children[0].id)
    outsider = await stores.first.create_work_item(title="Unrelated")
    if writer == "publication_cas":
        for index in range(len(children)):
            snapshot = await stores.first.get_owned_steps(parent.id)
            started, _ = await _apply(stores, snapshot, index, steps.StartOwnedStepCommand(execution_nonce=f"publish-{index}"),
                                      actor="agent-a", role="executor")
            await _apply(stores, started.snapshot, index, _submission(stores, started.permit),
                         actor="agent-a", role="executor")
        children = tuple([await stores.first.get_work_item(entry.id) for entry in children])
        assert all(entry.status == "done" for entry in children)
    before, events = _database(stores), list(stores.events)
    store = stores.second
    with pytest.raises(steps.OwnedStepsError, match="write_reserved"):
        if writer == "create_child":
            await store.create_work_item(title="Injected", parent_id=parent.id)
        elif writer == "reparent_into":
            await store.update_work_item(outsider.id, parent_id=parent.id)
        elif writer == "reparent_out":
            await store.update_work_item(child.id, parent_id=outsider.id)
        elif writer in ("delete_parent", "delete_child"):
            await store.delete_work_item(parent.id if writer == "delete_parent" else child.id)
        elif writer.startswith("update_") and writer != "update_step":
            field, value = {
                "update_status": ("status", "done"), "update_assignment": ("assigned_to", "agent-b"),
                "update_tokens": ("actual_tokens", 2), "update_verification": ("verification", {"accepted": True}),
                "update_steps": ("steps", []), "update_title": ("title", "replacement"),
                "update_ttl": ("ttl_seconds", 2),
            }[writer]
            await store.update_work_item(child.id, **{field: value})
        elif writer == "replace_metadata":
            await store.update_work_item(parent.id, metadata={})
        elif writer.startswith("merge_"):
            patch, extra = {
                "merge_gate": ({"steps_gate_completion": False}, {}),
                "merge_facilitator": ({"facilitator": "impostor"}, {}),
                "merge_execution": ({"crew_execution": None}, {}),
                "merge_plan": ({"crew_recovery": {}}, {}),
                "merge_tokens": ({}, {"actual_tokens_delta": 1}),
                "merge_status": ({}, {"new_status": "done"}),
            }[writer]
            await store.merge_work_item_metadata(child.id, patch, source="crew_executor", **extra)
        elif writer == "set_steps":
            await store.set_steps(parent.id, ["replacement"], gate_completion=False, facilitator="captain")
        elif writer == "update_step":
            await store.update_step(parent.id, 0, status="submitted", actor="captain")
        elif writer == "assign":
            await store.assign_work_item(child.id, "agent-b", source="crew_session")
        elif writer == "claim":
            await store.claim_work_item("agent-a", work_item_id=child.id)
        elif writer == "unassign":
            await store.unassign_work_item(child.id, reason="captain")
        elif writer == "transition":
            await store.transition_work_item(child.id, "cancelled", source="ttl_expiry")
        elif writer == "assignment_cas":
            await store.compare_and_set_work_item_assignment(
                child.id, expected_parent_id=parent.id, expected_status=child.status,
                expected_assigned_to=child.assigned_to, expected_depends_on=child.depends_on,
                expected_metadata=child.metadata, new_assigned_to="agent-b", metadata=child.metadata,
            )
        elif writer == "verification_cas":
            await store.compare_and_set_work_item_verification(
                child.id, {}, expected_verification=child.verification,
                expected_work_type=child.work_type, expected_status=child.status,
                expected_assigned_to=child.assigned_to, expected_parent_id=parent.id,
                expected_title=child.title, expected_description=child.description,
                expected_depends_on=child.depends_on, expected_metadata=child.metadata, expected_actual_tokens=0,
            )
        elif writer == "publication_cas":
            snapshots = tuple({
                key: value for key, value in entry.to_dict().items() if key != "updated_at"
            } for entry in sorted(children, key=lambda c: c.id))
            await store.publish_work_item_metadata_with_child_barrier(
                parent.id, {"crew_session": {"revision": 1}},
                expected={}, expected_absent_keys=frozenset(), expected_present_keys=frozenset(),
                expected_work_type=parent.work_type, expected_status=parent.status,
                expected_assigned_to="facilitator-1", expected_direct_children=snapshots, new_status="done",
            )
        elif writer == "provisioning_clear":
            await store.clear_crew_session_provisioning(
                parent.id, expected_marker={}, expected_session={}, expected_recovery={},
            )
        elif writer == "provisioning_delete":
            await store.delete_untouched_crew_session_provisioning(
                parent.id, expected_marker={}, expected_assigned_to="facilitator-1",
            )
        elif writer == "provisioning_fail":
            await store.fail_crew_session_provisioning(parent.id, expected_marker={}, error_code="failure")
        elif writer == "untyped_adoption":
            await store.adopt_child_plan_with_parent_metadata(
                parent.id, expected_parent_metadata=parent.metadata, expected_status=parent.status,
                expected_assigned_to="facilitator-1", parent_patch={},
                expected_children=tuple(sorted(children, key=lambda c: c.id)),
            )
        else:
            pytest.fail(f"Missing writer premise: {writer}")
    assert _database(stores) == before and stores.events == events


@pytest.mark.asyncio
@pytest.mark.parametrize("writer", ["start_booking", "pause_booking", "resume_booking", "complete_booking", "cancel_booking", "generate_journal"])
@pytest.mark.parametrize("state", ["scheduled", "active", "on_break"])
async def test_every_raw_booking_and_journal_writer_is_fenced_in_every_live_state(
    stores: _Harness, writer: str, state: str,
) -> None:
    parent, _ = await _legacy_plan(stores, bookings=True)
    snapshot = await stores.first.get_owned_steps(parent.id)
    booking_id = snapshot.control.rows[0].booking_id
    if state != "scheduled":
        result, _ = await _apply(stores, snapshot, 0, steps.StartOwnedStepCommand(execution_nonce="raw"),
                                 actor="agent-a", role="executor")
        if state == "on_break":
            await _apply(stores, result.snapshot, 0, steps.AccountingOwnedStepCommand(
                kind="pause_accounting", booking_id=booking_id, resource_id="agent-a",
            ))
    assert (await stores.first.get_booking(booking_id)).status == state
    before, events = _database(stores), list(stores.events)
    with pytest.raises(steps.OwnedStepsError, match="write_reserved"):
        await getattr(stores.second, writer)(booking_id)
    assert _database(stores) == before and stores.events == events


@pytest.mark.asyncio
@pytest.mark.parametrize("writer", ["create_column", "update_column", "create_metadata", "update_metadata", "merge_metadata", "template_metadata", "template_column"])
async def test_control_reserved_even_on_null_control_unmanaged_rows(stores: _Harness, writer: str) -> None:
    item = await stores.first.create_work_item(title="Ordinary")
    before, events = _database(stores), list(stores.events)
    with pytest.raises(steps.OwnedStepsError, match="control_reserved"):
        if writer == "create_column":
            await stores.first.create_work_item(steps_control=None)
        elif writer == "update_column":
            await stores.first.update_work_item(item.id, steps_control=None)
        elif writer == "create_metadata":
            await stores.first.create_work_item(metadata={"steps_control": None})
        elif writer == "update_metadata":
            await stores.first.update_work_item(item.id, metadata='{"steps_control": null}')
        elif writer == "merge_metadata":
            await stores.first.merge_work_item_metadata(item.id, {"steps_control": None})
        elif writer == "template_metadata":
            template = stores.first.template_store.list_templates()[0]
            await stores.first.create_from_template(
                template.template_id, overrides={"metadata": {"steps_control": None}},
            )
        else:
            await stores.first.create_from_template("unused", overrides={"steps_control": None})
    assert _database(stores) == before and stores.events == events


@pytest.mark.asyncio
async def test_unrelated_metadata_and_ordinary_claim_booking_remain_usable(stores: _Harness) -> None:
    parent, children = await _legacy_plan(stores)
    snapshot = await stores.first.get_owned_steps(parent.id)
    await stores.first.merge_work_item_metadata(parent.id, {"unrelated": {"note": "preserve"}})
    child = await stores.first.get_work_item(children[0].id)
    await stores.second.update_work_item(child.id, metadata={**child.metadata, "unrelated": [None, ""]})
    # Incidental siblings do not invalidate an otherwise exact child command.
    result, _ = await _apply(stores, snapshot, 0, steps.ReassignOwnedStepCommand(assignee_id="agent-b"))
    assert (await stores.first.get_work_item(child.id)).metadata["unrelated"] == [None, ""]
    assert result.snapshot.control.rows[1] == snapshot.control.rows[1]
    ordinary = await stores.first.create_work_item(id="ordinary", title="Ordinary claim")
    claimed = await stores.second.claim_work_item("agent-c", work_item_id=ordinary.id)
    assert claimed is not None
    _, booking = claimed
    await stores.first.start_booking(booking.id)
    await stores.first.pause_booking(booking.id)
    await stores.first.resume_booking(booking.id)
    await stores.first.complete_booking(booking.id, tokens_consumed=11)
    assert (await stores.first.get_work_item(ordinary.id)).actual_tokens == 11
    assert (await stores.first.get_booking(booking.id)).status == "completed"
    assert [entry.journal_type for entry in await stores.first.get_booking_journal(booking.id)] == [
        "idle", "working", "break", "working",
    ]


@pytest.mark.asyncio
async def test_actor_and_source_strings_and_wrong_owner_grants_are_not_authority(stores: _Harness) -> None:
    parent, _ = await _legacy_plan(stores)
    snapshot = await stores.first.get_owned_steps(parent.id)
    change = steps.OwnedStepChange(
        operation_id="forgery", token=_row_token(snapshot, 0),
        command=steps.ReassignOwnedStepCommand(assignee_id="agent-b"),
    )
    before, events = _database(stores), list(stores.events)
    for authority in (
        steps.OwnedStepsAuthority("captain"),
        stores.owner.authority("foreign-parent"),
        stores.owner.authority(parent.id, "narrated-facilitator", "facilitator"),
        stores.owner.authority(parent.id, "captain", "captain", "foreign-thread"),
    ):
        with pytest.raises(steps.OwnedStepsError, match="authority_denied"):
            await stores.first.compare_and_set_owned_step(steps.OwnedStepMutation(change, authority))
    assert _database(stores) == before and stores.events == events


@pytest.mark.asyncio
@pytest.mark.parametrize("drift", ["prefix", "assignment", "booking", "child", "gate"])
async def test_adoption_preview_compares_whole_projection_and_sources(stores: _Harness, drift: str) -> None:
    parent, children = await _legacy_plan(stores, prefix='[{"label":"manual","status":"done"}]', bookings=True)
    authority = stores.owner.authority(parent.id)
    preview = await stores.first.preview_owned_steps_adoption(parent.id, authority=authority, view_id="view", turn_id="turn")
    with sqlite3.connect(stores.path) as db:
        if drift == "prefix":
            db.execute("UPDATE work_items SET steps = ? WHERE id = ?", ('[{"label":"changed","status":"done"}]', parent.id))
        elif drift == "assignment":
            db.execute("UPDATE work_items SET assigned_to = 'agent-b' WHERE id = ?", (children[0].id,))
        elif drift == "booking":
            db.execute("UPDATE bookings SET end_time = 100 WHERE work_item_id = ?", (children[0].id,))
        elif drift == "child":
            db.execute("UPDATE work_items SET description = 'changed' WHERE id = ?", (children[0].id,))
        else:
            changed = {**parent.metadata, "steps_gate_completion": False}
            db.execute("UPDATE work_items SET metadata = ? WHERE id = ?", (json.dumps(changed), parent.id))
    before, events = _database(stores), list(stores.events)
    with pytest.raises(steps.OwnedStepsError, match="source_conflict|projection_conflict"):
        await stores.second.compare_and_set_owned_step(steps.OwnedStepMutation(
            steps.OwnedStepChange(operation_id="adopt-stale", token=preview.token, command=steps.AdoptOwnedStepsCommand(preview=preview)),
            authority,
        ))
    assert _database(stores) == before and stores.events == events


@pytest.mark.asyncio
@pytest.mark.parametrize("refuse", [False, True])
async def test_existing_ticker_awaits_injected_ttl_owner_without_starving_ordinary_expiry(
    stores: _Harness, refuse: bool,
) -> None:
    parent, children = await _legacy_plan(stores, bookings=True, children_count=1, ttl=True)
    ordinary = await stores.first.create_work_item(
        title="Expired ordinary", created_at=time.time() - 100, ttl_seconds=1,
    )
    stores.owner.refuse_expiry = refuse
    ticker = WorkItemStore(
        str(stores.path), tick_interval=0.01, owned_steps_authorizer=stores.owner,
        owned_steps_ttl_owner=stores.owner, owned_steps_content=stores.content,
    )
    await ticker.start()
    try:
        async with asyncio.timeout(3):
            while not stores.owner.expirations or (await stores.second.get_work_item(ordinary.id)).status != "cancelled":
                await asyncio.sleep(0.01)
        child = await stores.second.get_work_item(children[0].id)
        snapshot = await stores.second.get_owned_steps(parent.id)
        assert child.status == ("scheduled" if refuse else "cancelled")
        assert snapshot.control.rows[0].permit_state == ("unstarted" if refuse else "revoked")
        assert child.actual_tokens == 0 and child.verification == {}
    finally:
        await ticker.stop()


@pytest.mark.asyncio
async def test_manual_edit_before_adoption_invalidates_preview_and_can_clear_note(stores: _Harness) -> None:
    parent, _ = await _legacy_plan(stores, prefix='[{"label":"manual","status":"pending","note":"old"}]')
    authority = stores.owner.authority(parent.id)
    preview = await stores.first.preview_owned_steps_adoption(parent.id, authority=authority, view_id="preview", turn_id="turn")
    old = await stores.first.get_owned_steps(parent.id)
    edited, _ = await _apply(stores, old, 0, steps.ManualStepCommand(kind="edit_note", note=None))
    assert edited.snapshot.control.mode == "awaiting_adoption"
    assert json.loads(_raw_steps(stores, parent.id)) == [{"label": "manual", "status": "pending", "note": None}]
    assert edited.snapshot.control.original_steps_json == old.control.original_steps_json
    before, events = _database(stores), list(stores.events)
    with pytest.raises(steps.OwnedStepsError, match="plan_conflict"):
        await stores.second.compare_and_set_owned_step(steps.OwnedStepMutation(
            steps.OwnedStepChange(operation_id="stale-preview", token=preview.token,
                                  command=steps.AdoptOwnedStepsCommand(preview=preview)), authority,
        ))
    assert _database(stores) == before and stores.events == events
    await _adopt(stores, parent.id)
    assert (await stores.first.get_work_item(parent.id)).steps[0]["note"] is None


@pytest.mark.asyncio
async def test_cancel_awaiting_adoption_preserves_the_entire_public_manual_plan(stores: _Harness) -> None:
    prefix = '[ {"label":"keep","status":"done","confirmed_by":null} ]'
    parent, children = await _legacy_plan(stores, prefix=prefix, bookings=True)
    snapshot = await stores.first.get_owned_steps(parent.id)
    result, _ = await _apply(stores, snapshot, 1, steps.CancelOwnedStepCommand())
    assert result.snapshot.control.mode == "awaiting_adoption"
    assert _raw_steps(stores, parent.id) == prefix
    assert result.snapshot.control.rows[1].permit_state == "revoked"
    assert (await stores.first.get_work_item(children[0].id)).status == "cancelled"
    assert (await stores.first.get_work_item(children[1].id)).status == "scheduled"


@pytest.mark.asyncio
async def test_two_independent_stores_admit_siblings_without_invalidating_each_other(stores: _Harness) -> None:
    parent, children = await _legacy_plan(stores, bookings=True)
    snapshot = await stores.first.get_owned_steps(parent.id)
    outcomes = await asyncio.gather(
        _apply(stores, snapshot, 0, steps.StartOwnedStepCommand(execution_nonce="sibling-one"),
               actor="agent-a", role="executor", store=stores.first),
        _apply(stores, snapshot, 1, steps.StartOwnedStepCommand(execution_nonce="sibling-two"),
               actor="agent-a", role="executor", store=stores.second),
    )
    assert [result.disposition for result, _ in outcomes] == ["new", "new"]
    assert len({result.permit.execution_nonce for result, _ in outcomes}) == 2
    current = [await stores.first.get_work_item(child.id) for child in children]
    assert all(child.status == "in_progress" for child in current)


@pytest.mark.asyncio
@pytest.mark.parametrize("field", [
    "chief_agent_id", "order_id", "delegated", "delegation_reason", "assigned_capability", "assigned_department",
])
async def test_actual_assignment_metadata_is_protected_not_an_unrelated_sibling(stores: _Harness, field: str) -> None:
    _, children = await _legacy_plan(stores)
    before, events = _database(stores), list(stores.events)
    with pytest.raises(steps.OwnedStepsError, match="write_reserved"):
        await stores.first.merge_work_item_metadata(children[0].id, {field: None}, source="crew_session_assignment")
    assert _database(stores) == before and stores.events == events


@pytest.mark.asyncio
async def test_terminal_trust_delivery_cas_cannot_bypass_managed_owner(stores: _Harness) -> None:
    from probos.consensus.crew_trust_effect import CrewTrustEffect
    from probos.crew_session_delivery import build_crew_session_delivery_record_from_payload

    parent, _ = await _legacy_plan(stores)
    contract = dict(
        state="failed", revision=2, task_id=parent.id, thread_id="thread-1",
        origin="captain", originator_id="captain", facilitator_id="facilitator-1",
        created_at=1.0, transitioned_at=2.0, completed_at=2.0,
    )
    effect = CrewTrustEffect.create(
        session_id=parent.id, session_revision=2, evidence_sha256="a" * 64,
        agent_id="facilitator-1", role="facilitator", work_item_id=parent.id,
        result_revision=1, success=False, weight=1.0, intent_type="crew_task", verifier_id="verifier",
    )
    delivery = build_crew_session_delivery_record_from_payload(contract)
    before, events = _database(stores), list(stores.events)
    with pytest.raises(steps.OwnedStepsError, match="write_reserved"):
        await stores.second.transition_crew_session_terminal_with_trust(
            parent.id, {"crew_session": contract}, expected_metadata=parent.metadata,
            expected_status=parent.status, expected_assigned_to="facilitator-1", new_status="failed",
            crew_trust_effects=(effect,), crew_session_delivery=delivery,
        )
    assert _database(stores) == before and stores.events == events


class _FailBookingConnection:
    def __init__(self, delegate: Any) -> None:
        self.delegate = delegate
        self.child_written = False
        self.failed = False
        self.fail_booking = False
        self.fail_journal = False
        self.queries: list[tuple[str, Any]] = []

    @property
    def row_factory(self) -> Any:
        return self.delegate.row_factory

    @row_factory.setter
    def row_factory(self, value: Any) -> None:
        self.delegate.row_factory = value

    async def execute(self, sql: str, parameters: Any = ()) -> Any:
        self.queries.append((sql, parameters))
        if self.fail_booking and sql.startswith("UPDATE work_items SET status = ?, metadata = ?"):
            self.child_written = True
        if self.fail_booking and sql.startswith("UPDATE bookings SET status = 'completed'"):
            self.failed = True
            raise RuntimeError("injected_booking_write_failure")
        if self.fail_journal and sql.startswith("INSERT INTO owned_steps_journal"):
            self.failed = True
            raise RuntimeError("injected_journal_write_failure")
        return await self.delegate.execute(sql, parameters)

    async def executemany(self, sql: str, parameters: Any) -> Any:
        return await self.delegate.executemany(sql, parameters)

    async def executescript(self, sql: str) -> None:
        await self.delegate.executescript(sql)

    async def fetchone(self) -> Any:
        return await self.delegate.fetchone()

    async def fetchall(self) -> Any:
        return await self.delegate.fetchall()

    async def commit(self) -> None:
        await self.delegate.commit()

    async def close(self) -> None:
        await self.delegate.close()


class _FailBookingFactory:
    def __init__(self) -> None:
        self.connection: _FailBookingConnection | None = None

    async def connect(self, db_path: str) -> _FailBookingConnection:
        self.connection = _FailBookingConnection(await SQLiteConnectionFactory().connect(db_path))
        return self.connection


@pytest.mark.asyncio
async def test_booking_failure_rolls_back_already_written_terminal_evidence_and_retry_is_exact(stores: _Harness) -> None:
    parent, children = await _legacy_plan(stores, bookings=True)
    started, _ = await _apply(stores, await stores.first.get_owned_steps(parent.id), 0,
                              steps.StartOwnedStepCommand(execution_nonce="atomic"),
                              actor="agent-a", role="executor")
    factory = _FailBookingFactory()
    failing = WorkItemStore(
        str(stores.path), connection_factory=factory, tick_interval=1000,
        owned_steps_authorizer=stores.owner, owned_steps_content=stores.content,
    )
    await failing.start()
    try:
        factory.connection.fail_booking = True
        command = _submission(stores, started.permit)
        mutation = steps.OwnedStepMutation(
            steps.OwnedStepChange(operation_id="terminal-once", token=started.permit, command=command),
            stores.owner.authority(parent.id, "agent-a", "executor"),
        )
        before, events = _database(stores), list(stores.events)
        with pytest.raises(RuntimeError, match="injected_booking_write_failure"):
            await failing.compare_and_set_owned_step(mutation)
        assert factory.connection.child_written and factory.connection.failed
        assert _database(stores) == before and stores.events == events
        result = await stores.second.compare_and_set_owned_step(mutation)
        assert result.disposition == "applied"
        assert (await stores.first.get_work_item(children[0].id)).actual_tokens == 7
        assert (await stores.first.get_booking(started.permit.booking_id)).total_tokens_consumed == 7
    finally:
        await failing.stop()


@pytest.mark.asyncio
async def test_public_store_empty_missing_unavailable_and_owner_binding_boundaries(stores: _Harness) -> None:
    assert await stores.first.get_owned_steps("missing") is None
    for value in (None, "", 1):
        with pytest.raises(steps.OwnedStepsError, match="parent_invalid"):
            await stores.first.get_owned_steps(value)
    with pytest.raises(steps.OwnedStepsError, match="mutation_invalid"):
        await stores.first.compare_and_set_owned_step(None)
    unstarted = WorkItemStore()
    assert await unstarted.get_owned_steps("missing") is None
    with pytest.raises(steps.OwnedStepsError, match="unavailable"):
        await unstarted.preview_owned_steps_adoption(
            "missing", authority=steps.OwnedStepsAuthority(object()), view_id="view", turn_id="turn",
        )
    with pytest.raises(steps.OwnedStepsError, match="owner_invalid"):
        unstarted.bind_owned_steps_owner(None, None)
    unstarted.bind_owned_steps_owner(stores.owner, stores.owner, stores.content)
    with pytest.raises(steps.OwnedStepsError, match="already_bound"):
        unstarted.bind_owned_steps_owner(stores.owner, stores.owner)


@pytest.mark.asyncio
async def test_missing_content_or_mismatched_execution_never_commits_submission(stores: _Harness) -> None:
    parent, _ = await _legacy_plan(stores, bookings=True)
    started, _ = await _apply(stores, await stores.first.get_owned_steps(parent.id), 0,
                              steps.StartOwnedStepCommand(execution_nonce="exact"),
                              actor="agent-a", role="executor")
    command = _submission(stores, started.permit)
    stores.content.blobs[command.submission.output.content_hash] = b"different bytes"
    before, events = _database(stores), list(stores.events)
    with pytest.raises(steps.OwnedStepsError, match="content_conflict"):
        await _apply(stores, started.snapshot, 0, command, actor="agent-a", role="executor")
    with pytest.raises(steps.OwnedStepsError, match="authority_denied"):
        await _apply(stores, started.snapshot, 0, command, actor="agent-b", role="executor")
    assert _database(stores) == before and stores.events == events


@pytest.mark.asyncio
@pytest.mark.parametrize("prefix", ["[]", '[{"label":"historical manual","status":"done","note":""}]'])
async def test_historical_done_summary_never_becomes_new_verified_evidence_or_admission(
    stores: _Harness, prefix: str,
) -> None:
    # This used to use "completed", accidentally admitting a sixth Todo status.
    # Valid historical "done" still proves that status alone confers no new credit.
    parent, children = await _legacy_plan(stores, prefix=prefix, historical=True)
    if json.loads(prefix):
        await _adopt(stores, parent.id)
    snapshot = await stores.first.get_owned_steps(parent.id)
    assert snapshot.control.mode == "interrupted"
    for row in snapshot.control.rows:
        if row.child:
            assert row.permit_state == "interrupted"
            assert row.permit is None and row.submission is None and row.reviewed_result is None
            assert json.loads(row.todo_json)["status"] == "pending"
    before, events = _database(stores), list(stores.events)
    with pytest.raises(steps.OwnedStepsError, match="not_active"):
        await _apply(stores, snapshot, snapshot.control.manual_prefix_length,
                     steps.StartOwnedStepCommand(execution_nonce="must-not-replay"), actor="agent-a", role="executor")
    assert _database(stores) == before and stores.events == events
    for child in children:
        current = await stores.first.get_work_item(child.id)
        assert current.status == "done" and current.actual_tokens == 9 and current.verification == {"accepted": True}


@pytest.mark.asyncio
@pytest.mark.parametrize("prefix", [
    '[{"label":"bad","status":"mystery"}]',
    '[{"label":"bad","status":"pending","note":42}]',
    '[{"label":"bad","status":"pending","authority":"captain"}]',
    json.dumps([{"label": "manual", "status": "pending"}] * 1000),
], ids=["unknown-status", "non-string-note", "unknown-field", "total-rows-over-limit"])
async def test_malformed_or_oversized_seed_remains_untouched(stores: _Harness, prefix: str) -> None:
    with pytest.raises(steps.OwnedStepsError):
        await _legacy_plan(stores, prefix=prefix)
    assert _raw_steps(stores, "parent-1") == prefix
    with sqlite3.connect(stores.path) as db:
        assert db.execute("SELECT steps_control FROM work_items WHERE id = 'parent-1'").fetchone() == (None,)
        assert db.execute("SELECT COUNT(*) FROM work_items WHERE parent_id = 'parent-1'").fetchone() == (2,)
    assert len(stores.events) == 3  # Only the pre-existing unmanaged parent/children creations.


@pytest.mark.asyncio
async def test_early_ttl_source_claim_cannot_cancel_current_live_work(stores: _Harness) -> None:
    parent, _ = await _legacy_plan(stores)
    snapshot = await stores.first.get_owned_steps(parent.id)
    row = snapshot.control.rows[0]
    before, events = _database(stores), list(stores.events)
    with pytest.raises(steps.OwnedStepsError, match="ttl_conflict"):
        await _apply(
            stores, snapshot, 0,
            steps.CancelOwnedStepCommand(expired_item_id=row.child.child_id, observed_at=time.time()),
            actor="ttl", role="ttl",
        )
    assert _database(stores) == before and stores.events == events


@pytest.mark.asyncio
async def test_owned_submission_honors_existing_child_gate_and_rolls_back_booking(stores: _Harness) -> None:
    parent, _ = await _legacy_plan(stores, bookings=True, child_gate=True)
    started, _ = await _apply(stores, await stores.first.get_owned_steps(parent.id), 0,
                              steps.StartOwnedStepCommand(execution_nonce="gated"),
                              actor="agent-a", role="executor")
    before, events = _database(stores), list(stores.events)
    with pytest.raises(steps.OwnedStepsError, match="execution_transition"):
        await _apply(stores, started.snapshot, 0, _submission(stores, started.permit),
                     actor="agent-a", role="executor")
    assert _database(stores) == before and stores.events == events
    assert (await stores.first.get_booking(started.permit.booking_id)).status == "active"


@pytest.mark.asyncio
async def test_cancellation_after_submission_revokes_authority_without_rewriting_terminal_evidence(stores: _Harness) -> None:
    parent, children = await _legacy_plan(stores, bookings=True)
    started, _ = await _apply(stores, await stores.first.get_owned_steps(parent.id), 0,
                              steps.StartOwnedStepCommand(execution_nonce="submitted"),
                              actor="agent-a", role="executor")
    submitted, _ = await _apply(stores, started.snapshot, 0, _submission(stores, started.permit),
                                actor="agent-a", role="executor")
    child = await stores.first.get_work_item(children[0].id)
    booking = await stores.first.get_booking(started.permit.booking_id)
    journal = await stores.first.get_booking_journal(booking.id)
    cancelled, _ = await _apply(stores, submitted.snapshot, 0, steps.CancelOwnedStepCommand())
    assert cancelled.snapshot.control.rows[0].permit_state == "revoked"
    assert cancelled.snapshot.control.rows[0].submission == submitted.snapshot.control.rows[0].submission
    assert await stores.first.get_work_item(child.id) == child
    assert await stores.first.get_booking(booking.id) == booking
    assert await stores.first.get_booking_journal(booking.id) == journal


@pytest.mark.asyncio
@pytest.mark.parametrize("bookings", [False, True])
async def test_owned_permits_do_not_bypass_registered_work_type_transitions(stores: _Harness, bookings: bool) -> None:
    parent, _ = await _legacy_plan(stores, bookings=bookings, work_type="work_order")
    snapshot = await stores.first.get_owned_steps(parent.id)
    assert snapshot.control.mode == "active"
    assert snapshot.control.rows[0].permit_state == "unstarted"
    command = steps.StartOwnedStepCommand(execution_nonce="formal")
    if bookings:
        result, _ = await _apply(stores, snapshot, 0, command, actor="agent-a", role="executor")
        snapshot = result.snapshot
        command = _submission(stores, result.permit)
    before, events = _database(stores), list(stores.events)
    with pytest.raises(steps.OwnedStepsError, match="execution_transition"):
        await _apply(stores, snapshot, 0, command, actor="agent-a", role="executor")
    assert _database(stores) == before and stores.events == events


@pytest.mark.asyncio
async def test_completed_prefix_is_readonly_repair_evidence_not_an_owned_todo(stores: _Harness) -> None:
    prefix = '[ { "label":"keep raw", "status" : "completed", "note":null, "confirmed_by":"" } ]'
    with pytest.raises(steps.OwnedStepsError, match="repair_required") as failure:
        await _legacy_plan(stores, prefix=prefix)
    evidence = failure.value.repair_evidence
    assert evidence is not None and evidence.read_only is True
    assert evidence.raw_steps_json == prefix
    assert evidence.digest == steps.owned_digest(prefix)
    assert _raw_steps(stores, "parent-1") == prefix
    assert await stores.first.get_owned_steps("parent-1") is None
    assert set(steps.OwnedTodo.model_json_schema()["properties"]["status"]["enum"]) == {
        "pending", "in_progress", "submitted", "done", "rejected",
    }
    with pytest.raises(ValueError):
        steps.OwnedTodo(label="invalid", status="completed")
    assert "completed" in steps.OwnedStepsControl.model_json_schema()["properties"]["mode"]["enum"]
    with sqlite3.connect(stores.path) as db:
        assert db.execute("SELECT COUNT(*) FROM owned_steps_journal").fetchone()[0] == 0


@pytest.mark.asyncio
async def test_more_than_2000_real_edits_reopen_exact_early_ack_and_digest_conflict(stores: _Harness) -> None:
    parent, _ = await _legacy_plan(stores, prefix='[{"label":"manual","status":"pending"}]', children_count=1)
    await _adopt(stores, parent.id)
    snapshot = await stores.first.get_owned_steps(parent.id)
    initial_size = len(snapshot.control.model_dump_json().encode("utf-8"))
    first_mutation = None
    first_receipt = None
    started_at = time.perf_counter()
    for index in range(2005):
        result, mutation = await _apply(
            stores, snapshot, 0, steps.ManualStepCommand(kind="edit_note", note=f"note-{index}"),
            operation_id=f"edit-{index}",
        )
        assert result.disposition == "applied" and result.snapshot is not None
        if index == 0:
            first_mutation, first_receipt = mutation, result.receipt
        snapshot = result.snapshot
    control_bytes = len(snapshot.control.model_dump_json().encode("utf-8"))
    assert control_bytes < initial_size + 64
    assert snapshot.control.version == 2 and snapshot.control.mode == "active"
    assert not hasattr(snapshot.control, "operations") and not hasattr(snapshot.control, "effect_attempts")
    assert json.loads(snapshot.control.rows[0].todo_json)["note"] == "note-2004"
    with sqlite3.connect(stores.path) as db:
        count, largest = db.execute(
            "SELECT COUNT(*), MAX(length(CAST(payload AS BLOB))) FROM owned_steps_journal WHERE kind='operation'",
        ).fetchone()
    assert count == 2006 and largest <= steps.MAX_OWNED_MANIFEST_BYTES
    await stores.second.stop()
    await stores.first.stop()
    await stores.first.start()
    await stores.second.start()
    before, events = _database(stores), list(stores.events)
    replay = await stores.second.compare_and_set_owned_step(first_mutation)
    assert replay.disposition == "duplicate" and replay.snapshot is None and replay.permit is None
    assert replay.receipt == first_receipt
    assert json.loads(replay.receipt.observation.todo_json)["note"] == "note-0"
    changed = steps.OwnedStepMutation(
        first_mutation.change.model_copy(update={"command": steps.ManualStepCommand(kind="edit_note", note="different")}),
        first_mutation.authority,
    )
    with pytest.raises(steps.OwnedStepsError, match="operation_conflict"):
        await stores.first.compare_and_set_owned_step(changed)
    assert _database(stores) == before and stores.events == events
    logging.getLogger(__name__).info(
        "M1 retention proof: 2005 real edits, %d immutable receipts, control=%d bytes, "
        "largest receipt=%d bytes, elapsed=%.3fs; early replay exact and changed digest refused",
        count, control_bytes, largest, time.perf_counter() - started_at,
    )


def _review(
    harness: _Harness, permit: steps.OwnedStepExecutionPermit, submission_digest: str,
    *, accepted: bool = True,
) -> steps.ReviewOwnedStepCommand:
    corrected = f"Independently reviewed, corrected output for {permit.child_id}".encode()
    corrected_ref = steps.OwnedContentReference(
        content_hash=steps.owned_digest(corrected), mime="text/plain", size_bytes=len(corrected),
    )
    verification = steps.owned_json_bytes({
        "version": 1, "parent_id": permit.parent_id, "work_item_id": permit.child_id,
        "thread_id": "thread-1", "producer_agent_id": permit.assignee_id,
        "accepted": accepted, "status": "accepted" if accepted else "refuted",
    })
    verification_ref = steps.OwnedContentReference(
        content_hash=steps.owned_digest(verification), mime="application/json", size_bytes=len(verification),
    )
    harness.content.blobs[corrected_ref.content_hash] = corrected
    harness.content.blobs[verification_ref.content_hash] = verification
    return steps.ReviewOwnedStepCommand(result=steps.ReviewedStepResult(
        submission_digest=submission_digest, permit=permit, reviewed_result=corrected_ref,
        verification=verification_ref, reviewer_id="verifier", review_attempt_id=f"review-{permit.child_id}",
        accepted=accepted,
    ))


@pytest.mark.asyncio
@pytest.mark.parametrize("accepted", [False, True])
async def test_storage_review_binds_actual_submission_and_corrected_bytes_without_workflow_replay(
    stores: _Harness, accepted: bool,
) -> None:
    parent, children = await _legacy_plan(stores, children_count=1)
    started, _ = await _apply(
        stores, await stores.first.get_owned_steps(parent.id), 0,
        steps.StartOwnedStepCommand(execution_nonce="review-storage"), actor="agent-a", role="executor",
    )
    submitted, _ = await _apply(
        stores, started.snapshot, 0, _submission(stores, started.permit), actor="agent-a", role="executor",
    )
    row = submitted.snapshot.control.rows[0]
    command = _review(stores, started.permit, row.submission, accepted=accepted)
    before, events = _database(stores), list(stores.events)
    with pytest.raises(steps.OwnedStepsError, match="authority_denied"):
        await _apply(stores, submitted.snapshot, 0, command, actor="agent-a", role="executor")
    assert _database(stores) == before and stores.events == events
    reviewed, mutation = await _apply(
        stores, submitted.snapshot, 0, command, actor="verifier", role="verifier",
    )
    final = reviewed.snapshot.control.rows[0]
    assert final.permit_state == "terminal" and final.review_accepted is accepted
    assert json.loads(final.todo_json)["status"] == ("done" if accepted else "rejected")
    assert final.submission == row.submission and final.permit == row.permit
    retained = await stores.second.get_owned_step_evidence(parent.id, started.permit.incarnation, "review", final.reviewed_result)
    original = await stores.second.get_owned_step_evidence(parent.id, started.permit.incarnation, "submission", final.submission)
    assert retained == command.result and retained.submission_digest == row.submission
    assert retained.reviewed_result.content_hash != original.output.content_hash
    assert (await stores.second.get_work_item(children[0].id)).actual_tokens == 7
    before, events = _database(stores), list(stores.events)
    replay = await stores.second.compare_and_set_owned_step(mutation)
    assert replay.snapshot is None and replay.receipt == reviewed.receipt
    assert _database(stores) == before and stores.events == events


@pytest.mark.asyncio
async def test_owned_membership_without_retired_children_avoids_empty_source_queries(
    stores: _Harness, monkeypatch: pytest.MonkeyPatch,
) -> None:
    parent, children = await _legacy_plan(stores, children_count=2)
    queries: list[str] = []
    original_execute = aiosqlite.Connection.execute

    def observe_execute(
        connection: aiosqlite.Connection, statement: str, *args: Any, **kwargs: Any,
    ) -> Any:
        queries.append(statement)
        return original_execute(connection, statement, *args, **kwargs)

    monkeypatch.setattr(aiosqlite.Connection, "execute", observe_execute)
    membership = await stores.second.get_owned_crew_children(parent.id)

    assert tuple(child.id for child in membership.active) == tuple(child.id for child in children)
    assert membership.retired == ()
    assert any("FROM work_items WHERE parent_id" in query for query in queries)
    assert any("FROM owned_steps_retired_children" in query for query in queries)
    assert not any("SELECT detail.*" in query for query in queries)
    with sqlite3.connect(stores.path) as db:
        db.execute("UPDATE work_items SET parent_id=NULL WHERE id=?", (children[1].id,))
    with pytest.raises(steps.OwnedStepsError, match="membership_conflict"):
        await stores.second.get_owned_crew_children(parent.id)


@pytest.mark.asyncio
async def test_owned_membership_empty_json_literals_avoid_redundant_decoding(
    stores: _Harness, monkeypatch: pytest.MonkeyPatch,
) -> None:
    parent, _ = await _legacy_plan(stores, children_count=2)
    expected = tuple(
        child.to_dict()
        for child in (await stores.first.get_owned_crew_children(parent.id)).active
    )
    empty_decodes: list[str] = []
    original_loads = json.loads

    def observe_loads(raw: str | bytes | bytearray, *args: Any, **kwargs: Any) -> Any:
        if raw in ("[]", "{}"):
            empty_decodes.append(raw)
        return original_loads(raw, *args, **kwargs)

    monkeypatch.setattr(json, "loads", observe_loads)
    membership = await stores.first.get_owned_crew_children(parent.id)

    assert tuple(child.to_dict() for child in membership.active) == expected
    assert empty_decodes == []
    first, second = membership.active
    for field in (
        "depends_on", "required_capabilities", "tags", "metadata",
        "steps", "verification", "schedule",
    ):
        assert getattr(first, field) is not getattr(second, field)
    first.depends_on.append("caller-only")
    first.metadata["caller_only"] = True
    refreshed = await stores.second.get_owned_crew_children(parent.id)
    assert tuple(child.to_dict() for child in refreshed.active) == expected


@pytest.mark.asyncio
@pytest.mark.parametrize("field", [
    "depends_on", "required_capabilities", "tags", "metadata",
    "steps", "verification", "schedule",
])
async def test_owned_mutation_corrupt_non_target_child_json_still_rejects(
    stores: _Harness, field: str,
) -> None:
    parent, children = await _legacy_plan(stores, children_count=2)
    snapshot = await stores.first.get_owned_steps(parent.id)
    with sqlite3.connect(stores.path) as db:
        db.execute(
            f"UPDATE work_items SET {field}=? WHERE id=?",
            ("[] trailing", children[1].id),
        )
    before, events = _database(stores), list(stores.events)

    with pytest.raises(json.JSONDecodeError):
        await _apply(
            stores, snapshot, 0,
            steps.StartOwnedStepCommand(execution_nonce="corrupt-sibling"),
            actor="agent-a", role="executor", store=stores.second,
        )

    assert _database(stores) == before and stores.events == events


@pytest.mark.asyncio
@pytest.mark.parametrize(("field", "empty_json"), [
    ("depends_on", "[]"), ("required_capabilities", "[]"), ("tags", "[]"),
    ("metadata", "{}"), ("steps", "[]"), ("verification", "{}"), ("schedule", "{}"),
])
@pytest.mark.parametrize("encoding", ["null", "empty", "whitespace"])
async def test_owned_membership_empty_json_boundary_preserves_values(
    stores: _Harness, field: str, empty_json: str, encoding: str,
) -> None:
    parent, children = await _legacy_plan(stores, children_count=1)
    expected = (await stores.first.get_work_item(children[0].id)).to_dict()
    raw = {"null": None, "empty": "", "whitespace": f" {empty_json[0]} {empty_json[1]} "}[encoding]
    with sqlite3.connect(stores.path) as db:
        if raw is None:
            with pytest.raises(sqlite3.IntegrityError, match="NOT NULL"):
                db.execute(f"UPDATE work_items SET {field}=? WHERE id=?", (raw, children[0].id))
        else:
            db.execute(f"UPDATE work_items SET {field}=? WHERE id=?", (raw, children[0].id))
            expected[field] = json.loads(empty_json)

    membership = await stores.second.get_owned_crew_children(parent.id)

    assert tuple(child.to_dict() for child in membership.active) == (expected,)


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["insert", "reparent", "rename"])
async def test_owned_selective_membership_rechecks_external_identity_changes(
    stores: _Harness, change: str,
) -> None:
    parent, children = await _legacy_plan(stores)
    started, _ = await _apply(
        stores, await stores.first.get_owned_steps(parent.id), 0,
        steps.StartOwnedStepCommand(execution_nonce="membership-warm"),
        actor="agent-a", role="executor",
    )
    with sqlite3.connect(stores.path) as db:
        if change == "insert":
            db.execute(
                "INSERT INTO work_items(id,title,parent_id,created_at,updated_at) VALUES(?,?,?,?,?)",
                ("unexpected-child", "Unexpected", parent.id, time.time(), time.time()),
            )
        elif change == "reparent":
            db.execute("UPDATE work_items SET parent_id=NULL WHERE id=?", (children[1].id,))
        else:
            db.execute("UPDATE work_items SET id=? WHERE id=?", ("renamed-child", children[1].id))
    before, events = _database(stores), list(stores.events)

    with pytest.raises(steps.OwnedStepsError, match="membership_conflict"):
        await _apply(
            stores, started.snapshot, 0,
            steps.StartOwnedStepCommand(execution_nonce="membership-after-change"),
            actor="agent-a", role="executor", store=stores.second,
        )

    assert _database(stores) == before and stores.events == events


@pytest.mark.asyncio
@pytest.mark.parametrize("field", [
    "depends_on", "required_capabilities", "tags", "metadata",
    "steps", "verification", "schedule",
])
@pytest.mark.parametrize("storage_form", ["small_text", "large_text", "blob"])
async def test_owned_selective_json_cache_revalidates_exact_changed_bytes(
    stores: _Harness, monkeypatch: pytest.MonkeyPatch, field: str, storage_form: str,
) -> None:
    parent, children = await _legacy_plan(stores)
    snapshot = await stores.first.get_owned_steps(parent.id)
    marker = uuid.uuid4().hex + ("x" * 1100 if storage_form == "large_text" else "")
    value = [marker] if field in ("depends_on", "required_capabilities", "tags", "steps") else {"marker": marker}
    raw: str | bytes = json.dumps(value)
    if storage_form == "blob":
        raw = raw.encode("utf-8")
    with sqlite3.connect(stores.path) as db:
        db.execute(f"UPDATE work_items SET {field}=? WHERE id=?", (raw, children[1].id))
    started, _ = await _apply(
        stores, snapshot, 0, steps.StartOwnedStepCommand(execution_nonce="cache-warm"),
        actor="agent-a", role="executor",
    )
    decoded: list[str | bytes] = []
    observed_raw = raw
    original_loads = json.loads

    def observe_loads(source: str | bytes | bytearray, *args: Any, **kwargs: Any) -> Any:
        if source == observed_raw:
            decoded.append(source)
        return original_loads(source, *args, **kwargs)

    monkeypatch.setattr(json, "loads", observe_loads)
    repeated, _ = await _apply(
        stores, started.snapshot, 0, steps.StartOwnedStepCommand(execution_nonce="cache-hit"),
        actor="agent-a", role="executor", store=stores.second,
    )
    assert repeated.disposition == "already_started"
    assert len(decoded) == (0 if storage_form == "small_text" else 1)
    whitespace = b" \n" if isinstance(raw, bytes) else " \n"
    observed_raw = raw + whitespace
    with sqlite3.connect(stores.path) as db:
        db.execute(f"UPDATE work_items SET {field}=? WHERE id=?", (observed_raw, children[1].id))
    decoded.clear()

    changed, _ = await _apply(
        stores, started.snapshot, 0, steps.StartOwnedStepCommand(execution_nonce="cache-changed"),
        actor="agent-a", role="executor",
    )

    assert changed.disposition == "already_started"
    assert decoded == [observed_raw]
    observed_raw += b"trailing" if isinstance(raw, bytes) else "trailing"
    with sqlite3.connect(stores.path) as db:
        db.execute(f"UPDATE work_items SET {field}=? WHERE id=?", (observed_raw, children[1].id))
    before, events = _database(stores), list(stores.events)
    with pytest.raises(json.JSONDecodeError):
        await _apply(
            stores, started.snapshot, 0, steps.StartOwnedStepCommand(execution_nonce="cache-corrupt"),
            actor="agent-a", role="executor", store=stores.second,
        )
    assert _database(stores) == before and stores.events == events


@pytest.mark.asyncio
@pytest.mark.parametrize(("field", "raw"), [
    ("depends_on", "{}"), ("metadata", "[]"), ("verification", "null"),
    ("schedule", "false"), ("tags", "42"),
    ("metadata", '{"duplicate":1,"duplicate":2}'),
    ("metadata", '{"legacy_nonfinite":NaN}'),
])
async def test_owned_selective_json_validation_matches_existing_decoder(
    stores: _Harness, field: str, raw: str,
) -> None:
    parent, children = await _legacy_plan(stores)
    snapshot = await stores.first.get_owned_steps(parent.id)
    with sqlite3.connect(stores.path) as db:
        db.execute(f"UPDATE work_items SET {field}=? WHERE id=?", (raw, children[1].id))

    started, _ = await _apply(
        stores, snapshot, 0, steps.StartOwnedStepCommand(execution_nonce="legacy-json"),
        actor="agent-a", role="executor",
    )

    assert started.disposition == "new"
    membership = await stores.second.get_owned_crew_children(parent.id)
    sibling = next(child for child in membership.active if child.id == children[1].id)
    assert json.dumps(getattr(sibling, field)) == json.dumps(json.loads(raw))


@pytest.mark.asyncio
async def test_owned_selective_source_scope_and_full_public_columns_stay_fresh(
    stores: _Harness,
) -> None:
    parent, children = await _legacy_plan(stores)
    snapshot = await stores.first.get_owned_steps(parent.id)
    changes = {
        "title": "External title", "description": "External description",
        "work_type": "external-type", "status": "cancelled", "priority": 17,
        "project_id": "external-project", "assigned_to": "external-agent",
        "created_by": "external-author", "created_at": 1234.5, "updated_at": 2345.6,
        "due_at": 3456.7, "estimated_tokens": 17, "actual_tokens": 19,
        "trust_requirement": 0.7, "ttl_seconds": 99, "template_id": "external-template",
    }
    expected = children[1].to_dict() | changes
    with sqlite3.connect(stores.path) as db:
        db.execute(
            "UPDATE work_items SET " + ",".join(f"{column}=?" for column in changes) + " WHERE id=?",
            (*changes.values(), children[1].id),
        )

    started, _ = await _apply(
        stores, snapshot, 0, steps.StartOwnedStepCommand(execution_nonce="unrelated-valid-state"),
        actor="agent-a", role="executor",
    )

    assert started.disposition == "new"
    membership = await stores.second.get_owned_crew_children(parent.id)
    assert len(membership.active) == 2
    assert next(child.to_dict() for child in membership.active if child.id == children[1].id) == expected
    before, events = _database(stores), list(stores.events)
    with pytest.raises(steps.OwnedStepsError, match="source_conflict"):
        await stores.second.get_owned_steps(parent.id)
    with pytest.raises(steps.OwnedStepsError, match="source_conflict"):
        await _apply(
            stores, snapshot, 1, steps.StartOwnedStepCommand(execution_nonce="changed-target"),
            actor="agent-a", role="executor", store=stores.second,
        )
    assert _database(stores) == before and stores.events == events


@pytest.mark.asyncio
async def test_owned_selective_mutation_retains_second_store_valid_sibling_verdict(
    stores: _Harness,
) -> None:
    parent, _ = await _legacy_plan(stores)
    stale = await stores.first.get_owned_steps(parent.id)
    started, _ = await _apply(
        stores, stale, 1, steps.StartOwnedStepCommand(execution_nonce="other-store"),
        actor="agent-a", role="executor", store=stores.second,
    )
    submitted, _ = await _apply(
        stores, started.snapshot, 1, _submission(stores, started.permit),
        actor="agent-a", role="executor", store=stores.second,
    )
    reviewed, _ = await _apply(
        stores, submitted.snapshot, 1,
        _review(stores, started.permit, submitted.snapshot.control.rows[1].submission),
        actor="verifier", role="verifier", store=stores.second,
    )

    independent, _ = await _apply(
        stores, stale, 0, steps.StartOwnedStepCommand(execution_nonce="first-store"),
        actor="agent-a", role="executor",
    )

    assert independent.disposition == "new"
    assert independent.snapshot.control.rows[1] == reviewed.snapshot.control.rows[1]
    assert independent.snapshot.control.rows[1].review_accepted is True
    assert (await stores.first.get_owned_steps(parent.id)).control == independent.snapshot.control


async def _source_reader_plan(
    harness: _Harness, *, owner_kind: str, bookings: bool,
) -> tuple[WorkItem, tuple[WorkItem, ...]]:
    store = harness.first
    if owner_kind == "canonical":
        async with store.claim_crew_session_admission_port().reserve() as reservation:
            parent = await reservation.create_parent(CrewSessionParentCreate(
                id="source-parent", title="Source plan", description="Source equivalence",
                assigned_to="facilitator-1", created_by="captain",
                metadata={"crew_session": {"thread_id": "thread-1", "facilitator_id": "facilitator-1"}},
            ))
    else:
        parent = await store.create_work_item(id="source-parent", title="Source plan")
    children = []
    for index in range(2):
        child = await store.create_work_item(
            id=f"source-child-{index}", title=f"Child {index}", parent_id=parent.id,
            assigned_to=None if bookings else "agent-a",
            metadata={"spec_id": f"spec-{index}", "plan_only": {"exact": index}},
        )
        if bookings:
            assert await store.assign_work_item(child.id, "agent-a")
            child = await store.get_work_item(child.id)
        children.append(child)
    commitments = tuple(steps.OwnedStepChild(
        child_id=child.id, spec_id=child.metadata["spec_id"],
        commitment_digest=steps.owned_child_commitment(child.to_dict()),
    ) for child in children)
    plan_digest = steps.owned_digest(steps.owned_json_bytes([
        child.model_dump(mode="json") for child in commitments
    ]))
    patch = {"crew_recovery": {"plan": {
        "plan_hash": plan_digest,
        "children": [
            {"child_id": child.child_id, "spec_id": child.spec_id, "row_hash": child.commitment_digest}
            for child in commitments
        ],
    }}} if owner_kind == "canonical" else {}
    parent = await store.adopt_child_plan_with_parent_metadata(
        parent.id, expected_parent_metadata=parent.metadata, expected_status=parent.status,
        expected_assigned_to=parent.assigned_to, parent_patch=patch,
        expected_children=tuple(children),
        steps_seed=steps.OwnedStepsSeed(steps.OwnedStepsSeedPlan(
            parent_id=parent.id, owner_kind=owner_kind, thread_id="thread-1",
            facilitator_id="facilitator-1", incarnation=uuid.uuid4().hex,
            plan_digest=plan_digest, expected_steps_digest=steps.owned_digest("[]"),
            children=commitments,
        ), harness.owner.authority(parent.id)),
    )
    return parent, tuple(children)


@pytest.mark.asyncio
@pytest.mark.parametrize("owner_kind", ["legacy", "canonical"])
@pytest.mark.parametrize("bookings", [False, True])
async def test_row_scoped_source_reader_matches_bulk_digest(
    stores: _Harness, monkeypatch: pytest.MonkeyPatch, owner_kind: str, bookings: bool,
) -> None:
    parent, children = await _source_reader_plan(stores, owner_kind=owner_kind, bookings=bookings)
    snapshot = await stores.first.get_owned_steps(parent.id)
    calls: list[tuple[str, tuple[str, ...], tuple[str, ...]]] = []
    real_source = WorkItemStore._owned_child_source

    async def observe_source(
        store: WorkItemStore, child: WorkItem, *, exclude_steps: bool = False,
        protected_metadata_keys: tuple[str, ...] = (),
    ) -> str:
        if child.parent_id == parent.id:
            calls.append((child.id, protected_metadata_keys, tuple(child.metadata)))
        return await real_source(
            store, child, exclude_steps=exclude_steps, protected_metadata_keys=protected_metadata_keys,
        )

    monkeypatch.setattr(WorkItemStore, "_owned_child_source", observe_source)
    permit = None
    for state in ("unstarted", "started", "submitted", "terminal"):
        assert snapshot.control.rows[0].permit_state == state
        current = {child.id: await stores.second.get_work_item(child.id) for child in children}
        keys = {
            row.child.child_id: (
                tuple(current[row.child.child_id].metadata)
                if owner_kind == "canonical" else row.plan_metadata_keys
            )
            for row in snapshot.control.rows
        }
        bulk = await stores.second._owned_children_sources(parent.id, current, keys)
        for row in snapshot.control.rows:
            child = current[row.child.child_id]
            point = await stores.second._owned_child_source(child, protected_metadata_keys=keys[child.id])
            assert point == bulk[child.id] == row.source_digest
            changed = dataclasses.replace(child, metadata={**child.metadata, "plan_only": {"exact": "changed"}})
            assert await stores.second._owned_child_source(
                changed, protected_metadata_keys=keys[child.id],
            ) != point
            incidental = dataclasses.replace(child, metadata={**child.metadata, "later_detail": "incidental"})
            incidental_keys = tuple(incidental.metadata) if owner_kind == "canonical" else row.plan_metadata_keys
            incidental_digest = await stores.second._owned_child_source(
                incidental, protected_metadata_keys=incidental_keys,
            )
            assert (incidental_digest == point) is (owner_kind == "legacy")
        if state == "terminal":
            break
        if state == "unstarted":
            command = steps.StartOwnedStepCommand(execution_nonce="source-equivalence")
        elif state == "started":
            command = _submission(stores, permit)
        else:
            command = _review(stores, permit, snapshot.control.rows[0].submission)
        calls.clear()
        result, _ = await _apply(
            stores, snapshot, 0, command,
            actor="verifier" if state == "submitted" else "agent-a",
            role="verifier" if state == "submitted" else "executor",
        )
        assert len(calls) == 2  # Fresh selected source, then the changed source.
        for child_id, protected, all_keys in calls:
            assert child_id == children[0].id
            assert protected == (all_keys if owner_kind == "canonical" else snapshot.control.rows[0].plan_metadata_keys)
        if state == "unstarted":
            permit = result.permit
            assert permit is not None
        snapshot = result.snapshot
    reopened = await stores.second.get_owned_steps(parent.id)
    assert reopened == snapshot
    assert reopened.control.rows[0].review_accepted is True
    with sqlite3.connect(stores.path) as db:
        assert dict(db.execute("SELECT kind,COUNT(*) FROM owned_steps_journal GROUP BY kind")) == {
            "operation": 3, "permit": 1, "submission": 1, "review": 1,
        }
        for table in ("bookings", "booking_timestamps", "booking_journals"):
            count = db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            assert (count > 0) is bookings


@pytest.mark.asyncio
async def test_row_scoped_source_reads_only_relevant_requirements(
    stores: _Harness, monkeypatch: pytest.MonkeyPatch,
    membership_conversion_counts: list[int],
) -> None:
    parent, children = await _legacy_plan(stores, children_count=1000)
    snapshot = await stores.first.get_owned_steps(parent.id)
    with sqlite3.connect(stores.path) as db:
        assert db.execute("SELECT COUNT(*) FROM resource_requirements").fetchone()[0] == 1001
    loading: ContextVar[bool] = ContextVar("source_row_load", default=False)
    membership_rows: list[tuple[str, ...]] = []
    requirement_rows: list[tuple[str, ...]] = []
    real_load = WorkItemStore._load_owned_steps
    real_fetchall = aiosqlite.Cursor.fetchall

    async def observe_load(store: WorkItemStore, *args: Any, **kwargs: Any) -> Any:
        token = loading.set(True)
        try:
            return await real_load(store, *args, **kwargs)
        finally:
            loading.reset(token)

    async def observe_fetchall(cursor: aiosqlite.Cursor) -> Any:
        rows = await real_fetchall(cursor)
        if loading.get():
            columns = {column[0] for column in cursor.description or ()}
            if "steps_control" in columns and "parent_id" in columns:
                membership_rows.append(tuple(row["id"] for row in rows))
            elif "duration_estimate_seconds" in columns:
                requirement_rows.append(tuple(row["work_item_id"] for row in rows))
        return rows

    monkeypatch.setattr(WorkItemStore, "_load_owned_steps", observe_load)
    monkeypatch.setattr(aiosqlite.Cursor, "fetchall", observe_fetchall)
    membership_conversion_counts.clear()
    for index in (0, 500, 999):
        started, _ = await _apply(
            stores, snapshot, index, steps.StartOwnedStepCommand(execution_nonce=f"source-{index}"),
            actor="agent-a", role="executor",
        )
        submitted, _ = await _apply(
            stores, started.snapshot, index, _submission(stores, started.permit, tokens=1),
            actor="agent-a", role="executor",
        )
        reviewed, _ = await _apply(
            stores, submitted.snapshot, index,
            _review(stores, started.permit, submitted.snapshot.control.rows[index].submission),
            actor="verifier", role="verifier",
        )
        snapshot = reviewed.snapshot
    expected_ids = tuple(sorted(child.id for child in children))
    assert membership_rows == [expected_ids] * 9
    assert membership_conversion_counts == [1] * 9
    assert requirement_rows == [
        ids
        for index in (0, 500, 999)
        for _ in range(3)
        for ids in ((parent.id,), (children[index].id,))
    ]
    assert sum(len(ids) for ids in requirement_rows if ids != (parent.id,)) == 9
    assert (await stores.second.get_owned_steps(parent.id)) == snapshot


@pytest.mark.asyncio
@pytest.mark.parametrize("target", ["manual", "child"])
@pytest.mark.parametrize("corruption", [
    "retired_source", "retired_json", "proposal_receipt", "lineage", "observation",
])
async def test_owned_selective_mutation_rechecks_real_retirement_proof(
    owned_view_rig: Any, target: str, corruption: str,
    membership_conversion_counts: list[int], snapshot_digest_facts: OrderedDict[str, str],
) -> None:
    from tests.test_ad1192_owned_steps_dm import (
        _adopt as adopt_rig, _capture_presented,
    )

    rig = owned_view_rig
    await adopt_rig(rig)
    context, reference, _ = await _capture_presented(rig, turn_id="selective-replan")
    page = await rig.owner.prepare_owned_steps_proposal(
        steps.ReplanUnstartedProposalRequest(
            preparation_id="selective-replan-preparation", reference=reference,
        ),
        context,
    )
    replanned = await rig.owner.apply_owned_steps_proposal(
        steps.OwnedStepsProposalApplyRequest(
            operation_id="selective-replan-operation", reference=page.reference,
        ),
        context,
    )
    assert replanned.disposition == "applied"
    owner = _FakeOwner()
    events: list[Any] = []

    def emit(*args: Any, **kwargs: Any) -> None:
        events.append((args, kwargs))

    reader = WorkItemStore(
        str(rig.path), tick_interval=1000,
        owned_steps_authorizer=owner, emit_event=emit,
    )
    await reader.start()
    harness = _Harness(reader, reader, owner, _FakeContent(), rig.path, events)
    try:
        for resource_id in ("agent-a", "agent-b"):
            reader.register_resource(BookableResource(resource_id=resource_id, capacity=4))
        snapshot = await reader.get_owned_steps(rig.parent_id)
        index = 0 if target == "manual" else snapshot.control.manual_prefix_length
        actor = "captain" if target == "manual" else snapshot.control.rows[index].assignee_id
        assert actor is not None
        authority = owner.authority(
            rig.parent_id, actor, "captain" if target == "manual" else "executor",
            thread_id=snapshot.control.thread_id,
        )
        command = (
            steps.ManualStepCommand(kind="edit_note", note="Retirement proof crossing")
            if target == "manual" else steps.StartOwnedStepCommand(execution_nonce="retired-crossing")
        )
        membership_conversion_counts.clear()
        applied = await reader.compare_and_set_owned_step(steps.OwnedStepMutation(
            steps.OwnedStepChange(
                operation_id=uuid.uuid4().hex, token=_row_token(snapshot, index, actor=actor),
                command=command,
            ),
            authority,
        ))
        assert applied.disposition == ("applied" if target == "manual" else "new")
        assert membership_conversion_counts == [2 if target == "manual" else 3]
        membership = await reader.get_owned_crew_children(rig.parent_id)
        assert len(membership.active) == len(membership.retired) == 2
        retired_id = rig.child_ids[0]
        with sqlite3.connect(rig.path) as db:
            raw_control = db.execute(
                "SELECT steps_control FROM work_items WHERE id=?", (rig.parent_id,),
            ).fetchone()[0]
            assert snapshot_digest_facts[raw_control] == applied.snapshot.source_digest
            if corruption == "retired_source":
                db.execute("UPDATE work_items SET actual_tokens=1 WHERE id=?", (retired_id,))
            elif corruption == "retired_json":
                db.execute("UPDATE work_items SET metadata=? WHERE id=?", ("{broken", retired_id))
            elif corruption == "proposal_receipt":
                db.execute(
                    "UPDATE owned_steps_proposals "
                    "SET acknowledgement=json_set(acknowledgement,'$.operation_id','wrong-operation') "
                    "WHERE proposal_id=?",
                    (page.reference.proposal_id,),
                )
            elif corruption == "lineage":
                db.execute(
                    "UPDATE owned_steps_retired_children SET successor_incarnation=? WHERE child_id=?",
                    ("unknown-incarnation", retired_id),
                )
            else:
                db.execute(
                    "UPDATE owned_steps_observations SET source_manifest=source_manifest || char(10) "
                    "WHERE observation_id=(SELECT observation_id FROM owned_steps_proposals WHERE proposal_id=?)",
                    (page.reference.proposal_id,),
                )
        before, prior_events = _database(harness), list(events)
        expected_error = json.JSONDecodeError if corruption == "retired_json" else steps.OwnedStepsError
        with pytest.raises(
            expected_error, match=None if corruption == "retired_json" else "retirement_conflict",
        ):
            await reader.compare_and_set_owned_step(steps.OwnedStepMutation(
                steps.OwnedStepChange(
                    operation_id=uuid.uuid4().hex,
                    token=_row_token(applied.snapshot, index, actor=actor), command=command,
                ),
                authority,
            ))
        assert _database(harness) == before and events == prior_events
    finally:
        await reader.stop()


@pytest.mark.asyncio
async def test_owned_row_scoped_mutations_materialize_only_needed_children(
    stores: _Harness, membership_conversion_counts: list[int],
) -> None:
    parent, children = await _legacy_plan(stores, children_count=1000)
    snapshot = await stores.first.get_owned_steps(parent.id)
    membership_conversion_counts.clear()
    profile = cProfile.Profile()
    started_at = time.perf_counter()
    profile.enable()
    try:
        for index in (0, 500, 999):
            started, _ = await _apply(
                stores, snapshot, index,
                steps.StartOwnedStepCommand(execution_nonce=f"selective-{index}"),
                actor="agent-a", role="executor",
            )
            assert started.disposition == "new"
            submitted, _ = await _apply(
                stores, started.snapshot, index, _submission(stores, started.permit, tokens=1),
                actor="agent-a", role="executor",
            )
            reviewed, _ = await _apply(
                stores, submitted.snapshot, index,
                _review(stores, started.permit, submitted.snapshot.control.rows[index].submission),
                actor="verifier", role="verifier",
            )
            snapshot = reviewed.snapshot
            assert snapshot.control.rows[index].permit_state == "terminal"
            stores.events.clear()
    finally:
        profile.disable()
    elapsed = time.perf_counter() - started_at
    entries = profile.getstats()
    assert membership_conversion_counts == [1] * 9
    membership_conversions = sum(membership_conversion_counts)
    total_conversions = sum(
        entry.callcount for entry in entries
        if getattr(entry.code, "co_name", None) == "_row_to_work_item"
    )
    json_decodes = sum(entry.callcount for entry in entries if entry.code is json.loads.__code__)
    logging.getLogger(__name__).info(
        "Selective materialization diagnostic: rows=1000 real_transitions=9 "
        "membership_WorkItems=%d all_WorkItems=%d json_decodes=%d elapsed=%.6fs",
        membership_conversions, total_conversions, json_decodes, elapsed,
    )
    membership = await stores.second.get_owned_crew_children(parent.id)
    reopened = await stores.second.get_owned_steps(parent.id)
    assert tuple(child.id for child in membership.active) == tuple(child.id for child in children)
    assert reopened.control == snapshot.control
    assert membership_conversion_counts[9:] == [1000, 1000]
    full_conversions = sum(membership_conversion_counts[9:])
    assert full_conversions == 2000
    with sqlite3.connect(stores.path) as db:
        counts = dict(db.execute("SELECT kind,COUNT(*) FROM owned_steps_journal GROUP BY kind"))
    assert counts == {"operation": 9, "permit": 3, "submission": 3, "review": 3}
    assert membership_conversions == 9


@pytest.mark.asyncio
async def test_owned_materialization_counter_ignores_profiler_undercoverage(
    stores: _Harness, membership_conversion_counts: list[int],
) -> None:
    parent, children = await _legacy_plan(stores, children_count=1000)
    expected = await stores.first.get_owned_steps(parent.id)
    membership_conversion_counts.clear()
    profile = cProfile.Profile()
    profile.enable()
    try:
        membership = await stores.second.get_owned_crew_children(parent.id)
    finally:
        profile.disable()
    assert membership_conversion_counts == [1000]

    # Deliberate undercoverage, not a reproduction of native Linux attribution.
    outside = await stores.second.get_work_item(parent.id)
    assert outside is not None and outside.id == parent.id
    assert membership_conversion_counts == [1000]
    reopened = await stores.second.get_owned_steps(parent.id)
    assert membership_conversion_counts == [1000, 1000]
    assert sum(membership_conversion_counts) == 2000
    assert tuple(child.id for child in membership.active) == tuple(child.id for child in children)
    assert reopened == expected
    profiled = sum(
        entry.callcount for entry in profile.getstats()
        if getattr(entry.code, "co_name", None) == "_row_to_work_item"
    )
    assert 0 < profiled < sum(membership_conversion_counts)


@pytest.mark.asyncio
async def test_owned_materialization_counter_scopes_concurrent_reads_and_exceptions(
    stores: _Harness, membership_conversion_counts: list[int],
) -> None:
    parent, children = await _legacy_plan(stores)
    snapshot = await stores.first.get_owned_steps(parent.id)
    membership_conversion_counts.clear()
    partial, complete = await asyncio.gather(
        stores.first._get_owned_crew_children_locked(
            parent.id, snapshot.control, needed_ids=frozenset({children[0].id}),
        ),
        stores.second.get_owned_crew_children(parent.id),
    )
    assert tuple(child.id for child in partial.active) == (children[0].id,)
    assert tuple(child.id for child in complete.active) == tuple(child.id for child in children)
    assert sorted(membership_conversion_counts) == [1, 2]

    with sqlite3.connect(stores.path) as db:
        db.execute("UPDATE work_items SET metadata=? WHERE id=?", ("{broken", children[1].id))
    membership_conversion_counts.clear()
    with pytest.raises(json.JSONDecodeError):
        await stores.second.get_owned_crew_children(parent.id)
    assert membership_conversion_counts == [1]
    outside = await stores.second.get_work_item(children[0].id)
    assert outside is not None and outside.id == children[0].id
    assert membership_conversion_counts == [1]


@pytest.mark.asyncio
async def test_1000_admitted_rows_reach_real_storage_verdicts_with_bounded_terminal_footprint(stores: _Harness) -> None:
    started_at = time.perf_counter()
    parent, children = await _legacy_plan(stores, children_count=1000)
    snapshot = await stores.first.get_owned_steps(parent.id)
    logging.getLogger(__name__).info("M1 capacity admission: 1000 rows committed/read in %.3fs", time.perf_counter() - started_at)
    assert len(snapshot.control.rows) == 1000
    assert snapshot.control.mode == "active"
    stores.events.clear()
    for index in range(1000):
        started, _ = await _apply(
            stores, snapshot, index, steps.StartOwnedStepCommand(execution_nonce=f"capacity-{index}"),
            actor="agent-a", role="executor",
        )
        if index == 0:
            logging.getLogger(__name__).info("M1 first start committed at %.3fs", time.perf_counter() - started_at)
        assert started.disposition == "new"
        submitted, _ = await _apply(
            stores, started.snapshot, index, _submission(stores, started.permit, tokens=1),
            actor="agent-a", role="executor",
        )
        if index == 0:
            logging.getLogger(__name__).info("M1 first submission committed at %.3fs", time.perf_counter() - started_at)
        command = _review(stores, started.permit, submitted.snapshot.control.rows[index].submission)
        reviewed, _ = await _apply(
            stores, submitted.snapshot, index, command, actor="verifier", role="verifier",
        )
        snapshot = reviewed.snapshot
        assert snapshot.control.rows[index].permit_state == "terminal"
        stores.events.clear()  # The test observer is not another lifetime payload history.
        if index == 0:
            logging.getLogger(__name__).info("M1 first verdict committed at %.3fs", time.perf_counter() - started_at)
        if (index + 1) % 250 == 0:
            logging.getLogger(__name__).info(
                "M1 capacity proof: %d/1000 actual start/submission/verdict chains committed in %.3fs",
                index + 1, time.perf_counter() - started_at,
            )
    assert all(row.review_accepted is True and json.loads(row.todo_json)["status"] == "done"
               for row in snapshot.control.rows)
    reopened = await stores.second.get_owned_steps(parent.id)
    assert reopened.control == snapshot.control
    control_size = len(snapshot.control.model_dump_json().encode("utf-8"))
    # Format headroom only: this does not publish, close, or run an M2 finalizer.
    manifest_ref = steps.OwnedContentReference(
        content_hash="f" * 64, mime="application/" + "a" * 243,
        size_bytes=steps.MAX_OWNED_MANIFEST_BYTES,
    )
    final_receipt = steps.FinalizeReceipt(
        parent_id=parent.id, incarnation=snapshot.control.incarnation, owner_kind="legacy",
        thread_id="thread-1", plan_digest=snapshot.control.plan_digest,
        source_review_digest=snapshot.source_digest, manifest=manifest_ref,
        output=manifest_ref.model_copy(update={"size_bytes": 2**63 - 1}),
        publication_owner_id="p" * 128,
    )
    future = snapshot.control.model_dump(mode="json")
    future.update(finalization=final_receipt.model_dump(mode="json"), finalization_disposition="pending")
    with_final = steps.OwnedStepsControl.model_validate_json(steps.owned_json_bytes(future))
    final_size = len(with_final.model_dump_json().encode("utf-8"))
    assert final_size <= steps.MAX_OWNED_MANIFEST_BYTES
    with sqlite3.connect(stores.path) as db:
        counts = dict(db.execute("SELECT kind,COUNT(*) FROM owned_steps_journal GROUP BY kind"))
        largest = db.execute("SELECT MAX(length(CAST(payload AS BLOB))) FROM owned_steps_journal").fetchone()[0]
        token_count = db.execute("SELECT SUM(actual_tokens) FROM work_items WHERE parent_id=?", (parent.id,)).fetchone()[0]
        verified = db.execute(
            "SELECT COUNT(*) FROM work_items WHERE parent_id=? AND json_extract(verification,'$.accepted')=1",
            (parent.id,),
        ).fetchone()[0]
    assert counts == {"operation": 3000, "permit": 1000, "submission": 1000, "review": 1000}
    assert token_count == verified == len(children) == 1000
    assert largest <= steps.MAX_OWNED_MANIFEST_BYTES
    logging.getLogger(__name__).info(
        "M1 capacity proof complete: control=%d bytes, with bounded final-receipt binding=%d bytes, "
        "largest journal record=%d bytes, rows=1000, transitions=3000, elapsed=%.3fs",
        control_size, final_size, largest, time.perf_counter() - started_at,
    )


@pytest.mark.asyncio
async def test_thousand_row_format_cost_and_strict_corruption_rejection(stores: _Harness) -> None:
    started_at = time.perf_counter()
    parent, _ = await _legacy_plan(stores, children_count=1000)
    snapshot = await stores.first.get_owned_steps(parent.id)
    admitted_at = time.perf_counter()
    raw = snapshot.control.model_dump_json()
    durations = []
    for _ in range(3):
        before = time.perf_counter()
        assert steps.parse_owned_control(raw) == snapshot.control
        durations.append(time.perf_counter() - before)
    bad = json.loads(raw)
    bad["rows"][500]["unexpected"] = "not a valid field"
    with pytest.raises(steps.OwnedStepsError, match="control_invalid"):
        steps.parse_owned_control(json.dumps(bad))
    logging.getLogger(__name__).info(
        "M1 format diagnosis (NOT capacity acceptance): admitted/read 1000 rows in %.3fs; "
        "control=%d bytes; three strict parse times=%s",
        admitted_at - started_at, len(raw.encode("utf-8")), durations,
    )


async def _inline_fixture(
    stores: _Harness, *, completed_prefix: bool = False,
) -> tuple[str, str, steps.OwnedStepMutation, steps.OwnedEffectAttempt, dict[str, Any]]:
    """Encode a prior-v1 database fixture; never used to advance capacity tests."""
    parent, _ = await _legacy_plan(stores, prefix='[ {"label":"manual","status":"done","note":null} ]', children_count=1)
    adoption = await _adopt(stores, parent.id)
    started, start_mutation = await _apply(
        stores, await stores.first.get_owned_steps(parent.id), 1,
        steps.StartOwnedStepCommand(execution_nonce="retained-v1"), actor="agent-a", role="executor",
    )
    submitted, _ = await _apply(
        stores, started.snapshot, 1, _submission(stores, started.permit), actor="agent-a", role="executor",
    )
    value = submitted.snapshot.control.model_dump(mode="json")
    incarnation = value["incarnation"]
    for row in value["rows"]:
        for field, kind in (("permit", "permit"), ("submission", "submission"), ("reviewed_result", "review")):
            digest = row[field]
            row[field] = (
                (await stores.first.get_owned_step_evidence(parent.id, incarnation, kind, digest)).model_dump(mode="json")
                if digest is not None else None
            )
        row.pop("review_accepted")
    with sqlite3.connect(stores.path) as db:
        receipts = [json.loads(row[0]) for row in db.execute(
            "SELECT payload FROM owned_steps_journal WHERE parent_id=? AND incarnation=? AND kind='operation' ORDER BY rowid",
            (parent.id, incarnation),
        )]
    value["version"] = 1
    value["operations"] = [
        {key: receipt[key] for key in ("operation_id", "request_digest", "step_id", "disposition", "permit")}
        for receipt in receipts
    ]
    intent = b'{"effect":"old uncertain attempt"}'
    ref = steps.OwnedContentReference(content_hash=steps.owned_digest(intent), mime="application/json", size_bytes=len(intent))
    attempt = steps.OwnedEffectAttempt(
        effect_id="retained-effect", kind="producer_trust", intent=ref, claimed_at=1.0,
    )
    value["effect_attempts"] = [attempt.model_dump(mode="json")]
    if completed_prefix:
        value["original_steps_json"] = value["original_steps_json"].replace('"done"', '"completed"', 1)
        value["authorized_steps_json"] = value["authorized_steps_json"].replace('"done"', '"completed"', 1)
        value["steps_digest"] = steps.owned_digest(value["authorized_steps_json"])
        value["rows"][0]["todo_json"] = value["rows"][0]["todo_json"].replace('"done"', '"completed"', 1)
        value["rows"][0]["digest"] = steps.owned_digest(value["rows"][0]["todo_json"])
    raw = steps.owned_json_bytes(value).decode("utf-8")
    assert steps.parse_inline_owned_control(raw).version == 1
    await stores.second.stop()
    await stores.first.stop()
    with sqlite3.connect(stores.path) as db:
        db.execute("DELETE FROM owned_steps_journal")
        db.execute(
            "UPDATE work_items SET steps_control=?,steps=? WHERE id=?",
            (raw, value["authorized_steps_json"], parent.id),
        )
    assert adoption.change.operation_id in {entry["operation_id"] for entry in value["operations"]}
    return parent.id, incarnation, start_mutation, attempt, value


@pytest.mark.asyncio
async def test_inline_history_migration_replay_uncertainty_and_repeated_reopen_are_exact(stores: _Harness) -> None:
    parent_id, incarnation, start_mutation, attempt, old = await _inline_fixture(stores)
    with sqlite3.connect(stores.path) as db:
        rows_before = list(db.execute("SELECT id,steps,metadata,verification,actual_tokens,updated_at FROM work_items ORDER BY id"))
    await stores.first.start()
    await stores.second.start()
    snapshot = await stores.first.get_owned_steps(parent_id)
    assert snapshot.control.version == 2
    assert not hasattr(snapshot.control, "operations") and not hasattr(snapshot.control, "effect_attempts")
    with sqlite3.connect(stores.path) as db:
        assert list(db.execute("SELECT id,steps,metadata,verification,actual_tokens,updated_at FROM work_items ORDER BY id")) == rows_before
        counts = dict(db.execute("SELECT kind,COUNT(*) FROM owned_steps_journal GROUP BY kind"))
    assert counts == {"operation": 3, "effect": 1, "permit": 1, "submission": 1}
    before, events = _database(stores), list(stores.events)
    replay = await stores.second.compare_and_set_owned_step(start_mutation)
    assert replay.disposition == "already_started" and replay.snapshot is None
    assert replay.permit is not None and replay.permit.execution_nonce == "retained-v1"
    original = next(entry for entry in old["operations"] if entry["operation_id"] == start_mutation.change.operation_id)
    assert replay.receipt.request_digest == original["request_digest"]
    assert replay.receipt.disposition == original["disposition"]
    assert replay.permit.model_dump(mode="json") == original["permit"]
    assert replay.receipt.observation is None  # V1 never recorded one; do not invent today's state.
    assert await stores.first.get_owned_effect_attempt(parent_id, incarnation, attempt.effect_id) == attempt
    claim = steps.OwnedEffectClaim(_plan_token(snapshot), attempt, stores.owner.authority(parent_id))
    old_claim = await stores.second.claim_owned_effect_attempt(claim)
    assert old_claim.created is False and old_claim.attempt.disposition == "attempted_unknown"
    with pytest.raises(steps.OwnedStepsError, match="effect_conflict"):
        await stores.first.claim_owned_effect_attempt(dataclasses.replace(
            claim, attempt=attempt.model_copy(update={"claimed_at": 2.0}),
        ))
    assert _database(stores) == before and stores.events == events
    await stores.second.stop()
    await stores.first.stop()
    await stores.first.start()
    await stores.second.start()
    assert _database(stores) == before


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["operation", "effect"])
@pytest.mark.parametrize("conflict", [False, True])
async def test_inline_migration_existing_journal_copies_match_or_abort_atomically(
    stores: _Harness, kind: str, conflict: bool,
) -> None:
    parent_id, incarnation, _, attempt, old = await _inline_fixture(stores)
    if kind == "operation":
        model = steps.OwnedOperationReceipt.model_validate(old["operations"][0])
        if conflict:
            model = model.model_copy(update={"request_digest": "0" * 64})
        record_id, step_id = model.operation_id, model.step_id
    else:
        model = attempt.model_copy(update={"claimed_at": 2.0}) if conflict else attempt
        record_id, step_id = model.effect_id, None
    payload = steps.owned_json_bytes(model.model_dump(mode="json")).decode("utf-8")
    with sqlite3.connect(stores.path) as db:
        db.execute(
            "INSERT INTO owned_steps_journal(parent_id,incarnation,kind,record_id,payload_digest,payload,step_id,accepted) "
            "VALUES(?,?,?,?,?,?,?,NULL)",
            (parent_id, incarnation, kind, record_id, steps.owned_digest(payload), payload, step_id),
        )
    before, events = _database(stores), list(stores.events)
    if conflict:
        with pytest.raises(steps.OwnedStepsError, match="journal_conflict"):
            await stores.first.start()
        assert _database(stores) == before and stores.events == events
        with sqlite3.connect(stores.path) as db:
            assert json.loads(db.execute("SELECT steps_control FROM work_items WHERE id=?", (parent_id,)).fetchone()[0])["version"] == 1
    else:
        await stores.first.start()
        await stores.second.start()
        assert (await stores.first.get_owned_steps(parent_id)).control.version == 2
        with sqlite3.connect(stores.path) as db:
            assert db.execute(
                "SELECT COUNT(*) FROM owned_steps_journal WHERE parent_id=? AND incarnation=? AND kind=? AND record_id=?",
                (parent_id, incarnation, kind, record_id),
            ).fetchone()[0] == 1


@pytest.mark.asyncio
async def test_migrated_completed_prefix_stays_raw_readonly_and_retains_claims(stores: _Harness) -> None:
    parent_id, incarnation, _, attempt, old = await _inline_fixture(stores, completed_prefix=True)
    prefix = old["authorized_steps_json"]
    await stores.first.start()
    await stores.second.start()
    assert _raw_steps(stores, parent_id) == prefix
    with pytest.raises(steps.OwnedStepsError, match="repair_required") as failure:
        await stores.first.get_owned_steps(parent_id)
    assert failure.value.repair_evidence.raw_steps_json == prefix
    assert failure.value.repair_evidence.digest == old["steps_digest"]
    assert failure.value.repair_evidence.read_only
    assert await stores.second.get_owned_effect_attempt(parent_id, incarnation, attempt.effect_id) == attempt
    with sqlite3.connect(stores.path) as db:
        raw = db.execute("SELECT steps_control FROM work_items WHERE id=?", (parent_id,)).fetchone()[0]
        control = steps.parse_owned_control(raw)
        assert isinstance(control, steps.OwnedStepsRepairControl) and control.version == 2
        archived, digest = db.execute(
            "SELECT payload,payload_digest FROM owned_steps_journal WHERE parent_id=? AND incarnation=? AND kind='control'",
            (parent_id, incarnation),
        ).fetchone()
    assert digest == control.archived_control == steps.owned_digest(archived)
    assert json.loads(archived) == old
    assert "rows" not in control.model_dump()  # Not a success-shaped empty Todo list.
    before, events = _database(stores), list(stores.events)
    with pytest.raises(steps.OwnedStepsError, match="repair_required"):
        await stores.first.preview_owned_steps_adoption(
            parent_id, authority=stores.owner.authority(parent_id), view_id="repair-only", turn_id="turn",
        )
    assert _database(stores) == before and stores.events == events


@pytest.mark.asyncio
async def test_two_store_same_operation_replay_has_one_immutable_receipt(stores: _Harness) -> None:
    parent, _ = await _legacy_plan(stores, prefix='[{"label":"manual","status":"pending"}]')
    await _adopt(stores, parent.id)
    snapshot = await stores.first.get_owned_steps(parent.id)
    mutation = steps.OwnedStepMutation(steps.OwnedStepChange(
        operation_id="same-key", token=_row_token(snapshot, 0),
        command=steps.ManualStepCommand(kind="edit_note", note="one change"),
    ), stores.owner.authority(parent.id))
    results = await asyncio.gather(
        stores.first.compare_and_set_owned_step(mutation), stores.second.compare_and_set_owned_step(mutation),
    )
    assert sorted(result.disposition for result in results) == ["applied", "duplicate"]
    assert results[0].receipt == results[1].receipt
    assert sum(result.snapshot is None for result in results) == 1
    with sqlite3.connect(stores.path) as db:
        assert db.execute("SELECT COUNT(*) FROM owned_steps_journal WHERE kind='operation' AND record_id='same-key'").fetchone()[0] == 1


@pytest.mark.asyncio
async def test_journal_failure_rolls_back_booking_evidence_and_two_store_retry(stores: _Harness) -> None:
    parent, children = await _legacy_plan(stores, bookings=True)
    snapshot = await stores.first.get_owned_steps(parent.id)
    factory = _FailBookingFactory()
    failing = WorkItemStore(
        str(stores.path), connection_factory=factory, tick_interval=1000,
        owned_steps_authorizer=stores.owner, owned_steps_content=stores.content,
    )
    failing.register_resource(BookableResource(resource_id="agent-a", capacity=4))
    await failing.start()
    try:
        mutation = steps.OwnedStepMutation(steps.OwnedStepChange(
            operation_id="atomic-start", token=_row_token(snapshot, 0, actor="agent-a"),
            command=steps.StartOwnedStepCommand(execution_nonce="atomic-journal"),
        ), stores.owner.authority(parent.id, "agent-a", "executor"))
        factory.connection.fail_journal = True
        before, events = _database(stores), list(stores.events)
        with pytest.raises(RuntimeError, match="injected_journal_write_failure"):
            await failing.compare_and_set_owned_step(mutation)
        assert factory.connection.failed
        assert any("UPDATE bookings SET status = 'active'" in sql for sql, _ in factory.connection.queries)
        assert _database(stores) == before and stores.events == events
        retry = await stores.second.compare_and_set_owned_step(mutation)
        assert retry.disposition == "new"
        assert (await stores.first.get_work_item(children[0].id)).status == "in_progress"
        before = _database(stores)
        assert (await stores.first.compare_and_set_owned_step(mutation)).disposition == "already_started"
        assert _database(stores) == before
    finally:
        await failing.stop()


@pytest.mark.asyncio
async def test_actual_reference_query_uses_full_journal_key_not_history_scan(stores: _Harness) -> None:
    parent, _ = await _legacy_plan(stores, children_count=1)
    await _apply(stores, await stores.first.get_owned_steps(parent.id), 0,
                 steps.StartOwnedStepCommand(execution_nonce="indexed"), actor="agent-a", role="executor")
    factory = _FailBookingFactory()
    observer = WorkItemStore(str(stores.path), connection_factory=factory, tick_interval=1000)
    await observer.start()
    try:
        await observer.get_owned_steps(parent.id)
        sql, parameters = next(
            (sql, parameters) for sql, parameters in factory.connection.queries
            if "json_each(?) AS wanted" in sql and "owned_steps_journal" in sql
        )
        with sqlite3.connect(stores.path) as db:
            details = [row[3] for row in db.execute("EXPLAIN QUERY PLAN " + sql, parameters)]
        assert any("parent_id=? AND incarnation=? AND kind=? AND record_id=?" in detail for detail in details)
        assert not any("SCAN journal" in detail for detail in details)
    finally:
        await observer.stop()


@pytest.mark.asyncio
async def test_snapshot_digest_fact_cache_uses_exact_bytes_and_is_bounded(
    stores: _Harness, monkeypatch: pytest.MonkeyPatch,
    snapshot_digest_facts: OrderedDict[str, str],
) -> None:
    parent, _ = await _legacy_plan(stores)
    snapshot = await stores.first.get_owned_steps(parent.id)
    raw = snapshot.control.model_dump_json()
    formats = tuple("\n" * index + raw for index in range(5))
    snapshot_digest_facts.clear()
    envelopes: list[Any] = []
    real_encode = steps.owned_json_bytes

    def observe_encode(value: Any) -> bytes:
        if type(value) is dict and set(value) == {"parent", "rows", "gate"}:
            envelopes.append(value)
        return real_encode(value)

    monkeypatch.setattr(steps, "owned_json_bytes", observe_encode)
    assert steps.owned_snapshot_source_digest(formats[0]) == snapshot.source_digest
    assert len(envelopes) == 1
    assert steps.owned_snapshot_source_digest(formats[0]) == snapshot.source_digest
    assert len(envelopes) == 1
    for index in range(1, 4):
        assert steps.owned_snapshot_source_digest(formats[index]) == snapshot.source_digest
        assert len(envelopes) == index + 1
    assert tuple(snapshot_digest_facts) == formats[:4]
    assert steps.owned_snapshot_source_digest(formats[0]) == snapshot.source_digest
    assert len(envelopes) == 4
    assert steps.owned_snapshot_source_digest(formats[4]) == snapshot.source_digest
    assert tuple(snapshot_digest_facts) == (formats[2], formats[3], formats[0], formats[4])
    assert len(envelopes) == 5
    assert steps.owned_snapshot_source_digest(formats[1]) == snapshot.source_digest
    assert len(envelopes) == 6
    assert tuple(snapshot_digest_facts) == (formats[3], formats[0], formats[4], formats[1])
    assert all(type(value) is str and value == snapshot.source_digest for value in snapshot_digest_facts.values())
    before = tuple(snapshot_digest_facts.items())
    assert steps.owned_snapshot_source_digest(snapshot.control) == snapshot.source_digest
    assert len(envelopes) == 7
    assert tuple(snapshot_digest_facts.items()) == before


@pytest.mark.asyncio
async def test_snapshot_digest_fact_cache_carries_fresh_control_and_projection(
    stores: _Harness, monkeypatch: pytest.MonkeyPatch,
    snapshot_digest_facts: OrderedDict[str, str],
) -> None:
    parent, _ = await _legacy_plan(stores)
    original = await stores.first.get_owned_steps(parent.id)
    with sqlite3.connect(stores.path) as db:
        encoded = db.execute("SELECT steps_control FROM work_items WHERE id=?", (parent.id,)).fetchone()[0]
        raw = " \n" + encoded + "\t"
        db.execute("UPDATE work_items SET steps_control=? WHERE id=?", (raw, parent.id))
    snapshot_digest_facts.clear()
    inputs: list[steps.OwnedStepsControl | str] = []
    real_digest = steps.owned_snapshot_source_digest

    def observe_digest(control: steps.OwnedStepsControl | str) -> str:
        inputs.append(control)
        return real_digest(control)

    def unexpected_dump(*args: Any, **kwargs: Any) -> str:
        pytest.fail("A fresh control read must not be reserialized for its digest cache key")

    monkeypatch.setattr(steps, "owned_snapshot_source_digest", observe_digest)
    monkeypatch.setattr(steps.OwnedStepsControl, "model_dump_json", unexpected_dump)
    cold = await stores.first.get_owned_steps(parent.id)
    warm = await stores.second.get_owned_steps(parent.id)
    assert cold == warm == original and cold is not warm
    assert inputs == [raw, raw]
    assert tuple(snapshot_digest_facts.items()) == ((raw, original.source_digest),)
    with sqlite3.connect(stores.path) as db:
        db.execute("UPDATE work_items SET steps=? WHERE id=?", ("[]", parent.id))
    mismatched = await stores.second.get_owned_steps(parent.id)
    assert mismatched is not warm and mismatched.projection_matches is False
    assert warm.projection_matches is True
    assert mismatched.control == warm.control
    assert mismatched.source_digest == warm.source_digest
    assert inputs == [raw, raw, raw]
    assert tuple(snapshot_digest_facts.items()) == ((raw, original.source_digest),)
    with pytest.raises(dataclasses.FrozenInstanceError):
        mismatched.projection_matches = True


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid", [
    "duplicate", "nonfinite", "malformed", "none", "wrong_type", "oversized", "repair",
])
async def test_snapshot_digest_fact_cache_invalid_input_never_populates(
    stores: _Harness, snapshot_digest_facts: OrderedDict[str, str], invalid: str,
) -> None:
    parent, _ = await _legacy_plan(stores)
    snapshot = await stores.first.get_owned_steps(parent.id)
    control = snapshot.control
    raw = control.model_dump_json()
    assert steps.owned_snapshot_source_digest(raw) == snapshot.source_digest
    repair = steps.OwnedStepsRepairControl(
        parent_id=control.parent_id, incarnation=control.incarnation,
        owner_kind=control.owner_kind, thread_id=control.thread_id,
        facilitator_id=control.facilitator_id, plan_digest=control.plan_digest,
        child_ids=tuple(row.child.child_id for row in control.rows if row.child),
        archived_control=steps.owned_digest(raw),
        original_steps_digest=steps.owned_digest(control.original_steps_json),
        steps_digest=control.steps_digest,
    )
    inputs = {
        "duplicate": ['{"version":2,' + raw[1:]],
        "nonfinite": [
            raw.replace('"observation_revision":1', f'"observation_revision":{value}')
            for value in ("NaN", "Infinity", "1e999")
        ],
        "malformed": ["", "{broken", "[]", "null", '"wrong shape"', raw + " trailing"],
        "none": [None],
        "wrong_type": [1, True, [], {}, raw.encode("utf-8")],
        "oversized": [" " * steps.MAX_OWNED_MANIFEST_BYTES + raw],
        "repair": [repair.model_dump_json(), repair],
    }[invalid]
    before = tuple(snapshot_digest_facts.items())
    for value in inputs:
        assert value != raw
        for _ in range(2):
            with pytest.raises(steps.OwnedStepsError):
                steps.owned_snapshot_source_digest(value)
            assert tuple(snapshot_digest_facts.items()) == before


@pytest.mark.asyncio
@pytest.mark.parametrize("drift", [
    "membership", "parent", "child", "requirements", "booking",
    "timestamps", "journals", "evidence", "projection", "authority",
])
async def test_cached_format_facts_do_not_authorize_stale_database_state(
    stores: _Harness, monkeypatch: pytest.MonkeyPatch,
    snapshot_digest_facts: OrderedDict[str, str], drift: str,
) -> None:
    parent, children = await _legacy_plan(stores, bookings=True)
    started, _ = await _apply(
        stores, await stores.first.get_owned_steps(parent.id), 0,
        steps.StartOwnedStepCommand(execution_nonce="fact-cache-freshness"),
        actor="agent-a", role="executor",
    )
    submitted, _ = await _apply(
        stores, started.snapshot, 0, _submission(stores, started.permit),
        actor="agent-a", role="executor",
    )
    warm = await stores.second.get_owned_steps(parent.id)
    assert warm == submitted.snapshot and warm is not submitted.snapshot
    with sqlite3.connect(stores.path) as db:
        raw = db.execute("SELECT steps_control FROM work_items WHERE id=?", (parent.id,)).fetchone()[0]
    assert steps.parse_owned_control(raw) == warm.control
    assert snapshot_digest_facts[raw] == warm.source_digest
    command = _review(stores, started.permit, warm.control.rows[0].submission)
    authority = stores.owner.authority(parent.id, "verifier", "verifier")
    mutation = steps.OwnedStepMutation(steps.OwnedStepChange(
        operation_id=uuid.uuid4().hex, token=started.permit, command=command,
    ), authority)
    statements = {
        "membership": ("UPDATE work_items SET parent_id=NULL WHERE id=?", (children[1].id,)),
        "parent": ("UPDATE work_items SET actual_tokens=actual_tokens+1 WHERE id=?", (parent.id,)),
        "child": ("UPDATE work_items SET actual_tokens=actual_tokens+1 WHERE id=?", (children[0].id,)),
        "requirements": ("UPDATE resource_requirements SET priority=priority+1 WHERE work_item_id=?", (children[0].id,)),
        "booking": ("UPDATE bookings SET total_tokens_consumed=total_tokens_consumed+1 WHERE id=?", (started.permit.booking_id,)),
        "timestamps": ("UPDATE booking_timestamps SET timestamp=timestamp+1 WHERE booking_id=?", (started.permit.booking_id,)),
        "journals": ("UPDATE booking_journals SET tokens_consumed=tokens_consumed+1 WHERE booking_id=?", (started.permit.booking_id,)),
        "evidence": (
            "UPDATE owned_steps_journal SET payload_digest=? WHERE parent_id=? AND kind='permit'",
            ("0" * 64, parent.id),
        ),
        "projection": ("UPDATE work_items SET steps=? WHERE id=?", ("[]", parent.id)),
    }
    if drift == "authority":
        del stores.owner.grants[authority.context]
    else:
        with sqlite3.connect(stores.path) as db:
            statement, parameters = statements[drift]
            assert db.execute(statement, parameters).rowcount > 0
    facts_used: list[steps.OwnedStepsControl | str] = []
    real_digest = steps.owned_snapshot_source_digest

    def observe_digest(control: steps.OwnedStepsControl | str) -> str:
        facts_used.append(control)
        return real_digest(control)

    monkeypatch.setattr(steps, "owned_snapshot_source_digest", observe_digest)
    expected = {
        "membership": "membership_conflict", "projection": "projection_conflict",
        "evidence": "evidence_conflict", "authority": "authority_denied",
    }.get(drift, "source_conflict")
    before, events, blobs = _database(stores), list(stores.events), dict(stores.content.blobs)
    with pytest.raises(steps.OwnedStepsError, match=expected):
        await stores.second.compare_and_set_owned_step(mutation)
    assert _database(stores) == before and stores.events == events and stores.content.blobs == blobs
    # The existing authorization boundary follows the freshly proved load.
    # Even a valid cached digest never substitutes for that authority check.
    assert facts_used == ([raw] if drift == "authority" else [])
    assert snapshot_digest_facts[raw] == warm.source_digest


@pytest.mark.asyncio
async def test_prepared_projection_encoding_is_exact_and_single_pass(
    stores: _Harness, monkeypatch: pytest.MonkeyPatch,
) -> None:
    prefix = '[ { "label" : "\\u03bb ", "status":"done", "note":null },\n' \
        '{"status":"pending", "label":"manual sibling", "submitted_by":""} ] \t'
    parent, _ = await _legacy_plan(stores, prefix=prefix)
    await _adopt(stores, parent.id)
    snapshot = await stores.first.get_owned_steps(parent.id)
    control = snapshot.control
    original_encoding = control.model_dump_json()
    index = control.manual_prefix_length
    rows = list(control.rows)
    todo = steps.owned_json_loads(rows[index].todo_json)
    todo["note"] = "Exact \u03bb encoding"
    todo_json = steps.owned_json_bytes(todo).decode("utf-8")
    rows[index] = rows[index].model_copy(update={
        "todo_json": todo_json, "digest": steps.owned_digest(todo_json),
        "revision": rows[index].revision + 1,
    })
    projection = steps.replace_owned_row(control.authorized_steps_json, index, todo_json)
    expected = control.model_copy(update={
        "rows": tuple(rows), "authorized_steps_json": projection,
        "steps_digest": steps.owned_digest(projection),
        "observation_revision": control.observation_revision + 1,
    }).model_dump_json()
    encodings: list[str] = []
    real_dump = steps.OwnedStepsControl.model_dump_json

    def observe_dump(candidate: steps.OwnedStepsControl, *args: Any, **kwargs: Any) -> str:
        encoded = real_dump(candidate, *args, **kwargs)
        encodings.append(encoded)
        return encoded

    monkeypatch.setattr(steps.OwnedStepsControl, "model_dump_json", observe_dump)
    arguments = dict(
        rows=tuple(rows), projection=projection, mode=control.mode,
        layout_revision=control.layout_revision,
    )
    candidate, encoded = control.prepare_projection(**arguments)
    assert type(candidate) is steps.OwnedStepsControl
    assert encoded == expected and encodings == [expected]
    assert steps.parse_owned_control(encoded) is candidate
    assert candidate.steps_digest == steps.owned_digest(projection)
    assert candidate.current_manual_prefix_json() == prefix
    assert candidate.original_steps_json == prefix
    for ordinal, row in enumerate(control.rows):
        if ordinal != index:
            assert candidate.rows[ordinal].model_dump_json() == row.model_dump_json()
    assert real_dump(control) == original_encoding
    encodings.clear()
    compatible = control.with_projection(**arguments)
    assert type(compatible) is steps.OwnedStepsControl
    assert compatible == candidate and encodings == [expected]

    encodings.clear()
    applied, _ = await _apply(
        stores, snapshot, index, steps.StartOwnedStepCommand(execution_nonce="prepared-encoding"),
        actor="agent-a", role="executor",
    )
    assert len(encodings) == 1
    with sqlite3.connect(stores.path) as db:
        persisted = db.execute("SELECT steps_control FROM work_items WHERE id=?", (parent.id,)).fetchone()[0]
    assert persisted == encodings[0] == real_dump(applied.snapshot.control)
    assert applied.snapshot.control.current_manual_prefix_json() == prefix
    assert applied.snapshot.control.rows[index + 1] == control.rows[index + 1]
    assert applied.snapshot.source_digest == steps.owned_digest(steps.owned_json_bytes({
        "parent": applied.snapshot.control.parent_source_digest,
        "rows": [
            [row.step_id, row.revision, row.digest, row.source_digest]
            for row in applied.snapshot.control.rows
        ],
        "gate": applied.snapshot.control.gate_json,
    }))
    reopened = await stores.second.get_owned_steps(parent.id)
    assert reopened == applied.snapshot
    assert encodings == [persisted]


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid", [
    "rows_none", "rows_empty", "rows_list", "row_type", "row_revision",
    "projection_none", "projection_empty", "projection_mismatch",
    "mode_none", "mode_invalid", "layout_zero",
])
async def test_prepared_projection_invalid_input_preserves_compatibility_errors(
    stores: _Harness, invalid: str,
) -> None:
    parent, _ = await _legacy_plan(stores)
    control = (await stores.first.get_owned_steps(parent.id)).control
    arguments: dict[str, Any] = dict(
        rows=control.rows, projection=control.authorized_steps_json,
        mode=control.mode, layout_revision=control.layout_revision,
    )
    changes = {
        "rows_none": ("rows", None),
        "rows_empty": ("rows", ()),
        "rows_list": ("rows", list(control.rows)),
        "row_type": ("rows", (object(), control.rows[1])),
        "row_revision": ("rows", (control.rows[0].model_copy(update={"revision": 0}), control.rows[1])),
        "projection_none": ("projection", None),
        "projection_empty": ("projection", ""),
        "projection_mismatch": ("projection", "[]"),
        "mode_none": ("mode", None),
        "mode_invalid": ("mode", "unknown"),
        "layout_zero": ("layout_revision", 0),
    }
    key, value = changes[invalid]
    arguments[key] = value
    errors = []
    before, events = _database(stores), list(stores.events)
    for method in (control.prepare_projection, control.with_projection):
        with pytest.raises(TypeError if invalid == "projection_none" else ValueError) as caught:
            method(**arguments)
        errors.append((type(caught.value), str(caught.value)))
    assert errors[0] == errors[1]
    assert _database(stores) == before and stores.events == events


@pytest.mark.asyncio
async def test_projection_delta_revalidates_changes_and_keeps_actual_two_mib_bound(stores: _Harness) -> None:
    parent, _ = await _legacy_plan(stores)
    control = (await stores.first.get_owned_steps(parent.id)).control
    raw = json.loads(control.rows[0].todo_json)
    raw["status"] = "completed"
    bad_json = json.dumps(raw)
    bad = control.rows[0].model_copy(update={"todo_json": bad_json, "digest": steps.owned_digest(bad_json)})
    with pytest.raises(ValueError):
        control.with_projection(rows=(bad, control.rows[1]), projection=f"[{bad_json},{control.rows[1].todo_json}]",
                                mode="active", layout_revision=control.layout_revision)
    with pytest.raises(ValueError):
        control.with_projection(rows=control.rows, projection=control.authorized_steps_json,
                                mode="unknown", layout_revision=control.layout_revision)
    with pytest.raises(steps.OwnedStepsError, match="rows_invalid"):
        control.with_projection(rows=(), projection="[]", mode="active", layout_revision=1)
    large_rows = []
    for row in control.rows:
        todo = json.loads(row.todo_json)
        todo["note"] = "n" * (steps.MAX_OWNED_MANIFEST_BYTES // 4)
        encoded = steps.owned_json_bytes(todo).decode("utf-8")
        large_rows.append(row.model_copy(update={"todo_json": encoded, "digest": steps.owned_digest(encoded)}))
    with pytest.raises(steps.OwnedStepsError, match="manifest_too_large"):
        control.with_projection(
            rows=tuple(large_rows), projection="[" + ",".join(row.todo_json for row in large_rows) + "]",
            mode="active", layout_revision=1,
        )
    assert (await stores.first.get_owned_steps(parent.id)).control == control


@pytest.mark.asyncio
async def test_journal_read_boundaries_and_retention_declaration(stores: _Harness) -> None:
    from probos.storage.declarations import StoreRetention
    from probos.storage_declarations import STORE_DECLARATIONS

    declaration = next(item for item in STORE_DECLARATIONS if item.id == "workforce.work-items")
    assert declaration.retention is StoreRetention.UNBOUNDED
    assert "indefinitely" in declaration.retention_note and "uncertain" in declaration.retention_note
    assert await stores.first.get_owned_operation_receipt("missing", "incarnation", "operation") is None
    assert await stores.first.get_owned_effect_attempt("missing", "incarnation", "effect") is None
    with pytest.raises(steps.OwnedStepsError, match="evidence_missing"):
        await stores.first.get_owned_step_evidence("missing", "incarnation", "permit", "0" * 64)
    with pytest.raises(steps.OwnedStepsError, match="evidence_invalid"):
        await stores.first.get_owned_step_evidence("missing", "incarnation", "not-evidence", "0" * 64)
    for value in (None, "", 1):
        with pytest.raises(steps.OwnedStepsError, match="journal_key_invalid"):
            await stores.first.get_owned_operation_receipt(value, "incarnation", "operation")
    empty = WorkItemStore()
    with pytest.raises(steps.OwnedStepsError, match="unavailable"):
        await empty.get_owned_operation_receipt("parent", "incarnation", "operation")
    with pytest.raises(steps.OwnedStepsError, match="unavailable"):
        await empty.get_owned_effect_attempt("parent", "incarnation", "effect")
    with pytest.raises(steps.OwnedStepsError, match="unavailable"):
        await empty.get_owned_step_evidence("parent", "incarnation", "permit", "0" * 64)
