"""AD-1176: ``WorkItem.project_id`` — the work-management spine.

Issue #1107. A soft, optional reference from a work item to a ``Project``,
mirroring ``ChatThread.project_id``: no foreign key, no existence check at
insert, and a filter that simply stops matching when the project is gone.

House rule these tests exist to honour: **cache-only store tests mask
column-mapping bugs.** ``WorkItemStore`` accepts ``db_path=""`` and gates
``start()`` on ``if self.db_path:``, so a cache-only test never runs
``_row_to_work_item``, the INSERT column alignment, or the migration. Every
test here uses a real temp SQLite file, and the migration test hand-builds a
pre-AD-1176 table so the ``ALTER TABLE`` path is actually exercised — a fresh
database takes the ``CREATE TABLE`` path and proves nothing about upgrades.
"""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from probos.routers import workforce as workforce_router
from probos.routers.deps import get_runtime
from probos.threads import ProjectStore
from probos.workforce import (
    _WORK_ITEM_CHILD_SNAPSHOT_KEYS,
    _WORK_ITEM_PLAN_ADOPTION_SNAPSHOT_KEYS,
    WorkItem,
    WorkItemStore,
    _detach_direct_child_snapshots,
    _detach_plan_adoption_children,
    _work_item_child_snapshot,
)

# The ``work_items`` DDL exactly as it shipped before AD-1176 — 24 columns,
# no ``project_id``. Hand-applied so the migration has something real to
# upgrade.
_PRE_AD1176_WORK_ITEMS_DDL = """
CREATE TABLE work_items (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT '',
    work_type TEXT NOT NULL DEFAULT 'task',
    status TEXT NOT NULL DEFAULT 'open',
    priority INTEGER NOT NULL DEFAULT 3,
    parent_id TEXT,
    depends_on TEXT NOT NULL DEFAULT '[]',
    assigned_to TEXT,
    created_by TEXT NOT NULL DEFAULT 'captain',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    due_at REAL,
    estimated_tokens INTEGER,
    actual_tokens INTEGER NOT NULL DEFAULT 0,
    trust_requirement REAL NOT NULL DEFAULT 0.0,
    required_capabilities TEXT NOT NULL DEFAULT '[]',
    tags TEXT NOT NULL DEFAULT '[]',
    metadata TEXT NOT NULL DEFAULT '{}',
    steps TEXT NOT NULL DEFAULT '[]',
    verification TEXT NOT NULL DEFAULT '{}',
    schedule TEXT NOT NULL DEFAULT '{}',
    ttl_seconds INTEGER,
    template_id TEXT
)
"""


def _new_store(db_path: str) -> WorkItemStore:
    """A real-DB store with the tick loop effectively disabled."""
    return WorkItemStore(db_path=db_path, tick_interval=1000.0)


def _work_item_columns(db_path: str) -> list[str]:
    conn = sqlite3.connect(db_path)
    try:
        return [r[1] for r in conn.execute("PRAGMA table_info(work_items)")]
    finally:
        conn.close()


def _client(store: WorkItemStore | None) -> tuple[FastAPI, httpx.AsyncClient]:
    """Bare app with only the workforce router — no full runtime needed."""
    app = FastAPI()
    app.include_router(workforce_router.router)
    runtime = SimpleNamespace(work_item_store=store)
    app.dependency_overrides[get_runtime] = lambda: runtime
    transport = httpx.ASGITransport(app=app)
    return app, httpx.AsyncClient(transport=transport, base_url="http://test")


# ---------------------------------------------------------------------------
# Dataclass surface
# ---------------------------------------------------------------------------


def test_work_item_project_id_defaults_to_none() -> None:
    item = WorkItem(title="No project")

    assert item.project_id is None
    assert item.to_dict()["project_id"] is None


def test_work_item_to_dict_round_trips_project_id() -> None:
    item = WorkItem(title="Owned", project_id="proj-alpha")

    payload = item.to_dict()

    assert payload["project_id"] == "proj-alpha"
    assert WorkItem(**payload).project_id == "proj-alpha"


# ---------------------------------------------------------------------------
# Exact-key barrier contracts
#
# Two crew-session barriers compare whole ``WorkItem`` projections and reject
# any snapshot whose key set differs from a frozen constant:
#   * plan adoption   -> ``set(to_dict())``
#   * child publication -> ``set(to_dict()) - {"updated_at"}``
# Adding a field to ``WorkItem`` without listing it in both raises
# ``work_item_plan_adoption_invalid`` / ``work_item_child_barrier_invalid`` and
# breaks crew-session publication. Neither snapshot is persisted — both are
# recomputed from live rows inside the write transaction — so growing them
# invalidates nothing on disk. These guards turn future drift into a unit-test
# failure instead of a full-suite one.
# ---------------------------------------------------------------------------


def test_plan_adoption_key_set_matches_work_item_to_dict() -> None:
    assert set(WorkItem().to_dict()) == set(_WORK_ITEM_PLAN_ADOPTION_SNAPSHOT_KEYS)
    assert "project_id" in _WORK_ITEM_PLAN_ADOPTION_SNAPSHOT_KEYS


def test_child_barrier_key_set_matches_to_dict_without_updated_at() -> None:
    assert set(WorkItem().to_dict()) - {"updated_at"} == set(
        _WORK_ITEM_CHILD_SNAPSHOT_KEYS,
    )
    assert "updated_at" not in _WORK_ITEM_CHILD_SNAPSHOT_KEYS


def test_store_and_finalizer_child_snapshots_agree_on_keys() -> None:
    """The barrier has two independent producers; they must not drift apart.

    ``workforce._work_item_child_snapshot`` is hand-built;
    ``crew_finalizer._publication_child_snapshot`` derives from ``to_dict()``.
    Both feed the same exact-key validator.
    """
    from probos.cognitive.crew_finalizer import CrewSessionFinalizer

    item = WorkItem(
        id="child-x", title="Snap", parent_id="parent-x", assigned_to="agent-x",
        project_id="proj-alpha",
    )

    store_side = _work_item_child_snapshot(item)
    finalizer_side = CrewSessionFinalizer._publication_child_snapshot(item)

    assert set(store_side) == set(finalizer_side) == set(
        _WORK_ITEM_CHILD_SNAPSHOT_KEYS,
    )
    assert store_side["project_id"] == "proj-alpha"
    assert finalizer_side["project_id"] == "proj-alpha"


def test_detach_plan_adoption_children_accepts_a_project_scoped_child() -> None:
    """The path that actually broke: adoption must admit a project-bearing child."""
    child = WorkItem(
        id="child-1", title="Scoped", parent_id="parent-1",
        project_id="proj-alpha", assigned_to="agent-1",
    )

    detached = _detach_plan_adoption_children("parent-1", (child,))

    assert len(detached) == 1
    assert detached[0]["project_id"] == "proj-alpha"
    assert detached[0] == child.to_dict()


def test_detach_direct_child_snapshots_accepts_a_project_scoped_child() -> None:
    child = WorkItem(
        id="child-1", title="Scoped", parent_id="parent-1", status="done",
        project_id="proj-alpha", assigned_to="agent-1",
    )

    detached = _detach_direct_child_snapshots(
        "parent-1", (_work_item_child_snapshot(child),),
    )

    assert detached[0]["project_id"] == "proj-alpha"


def test_detach_direct_child_snapshots_rejects_non_string_project_id() -> None:
    """Error path: the barrier type-checks ``project_id`` like its siblings."""
    child = WorkItem(
        id="child-1", title="Scoped", parent_id="parent-1", status="done",
        assigned_to="agent-1",
    )
    snapshot = _work_item_child_snapshot(child)
    snapshot["project_id"] = 17

    with pytest.raises(ValueError, match="work_item_child_barrier_invalid"):
        _detach_direct_child_snapshots("parent-1", (snapshot,))


def test_detach_plan_adoption_children_still_rejects_a_foreign_key_set() -> None:
    """Error path: the barrier remains exact, not merely permissive."""
    child = WorkItem(id="child-2", title="Odd", parent_id="parent-1", assigned_to="a1")
    original_to_dict = WorkItem.to_dict
    try:
        WorkItem.to_dict = lambda self: {  # type: ignore[method-assign]
            **original_to_dict(self), "surprise": 1,
        }
        with pytest.raises(ValueError, match="work_item_plan_adoption_invalid"):
            _detach_plan_adoption_children("parent-1", (child,))
    finally:
        WorkItem.to_dict = original_to_dict  # type: ignore[method-assign]


# ---------------------------------------------------------------------------
# Real-DB round trip — the column-mapping guard
# ---------------------------------------------------------------------------


async def test_real_db_reopen_reloads_every_field_including_project_id(
    tmp_path: Path,
) -> None:
    """Create -> stop -> reopen a NEW store over the same file.

    Asserts every pre-existing field survives beside ``project_id``. A column
    misalignment in the INSERT or ``_row_to_work_item`` shows up here as a
    shifted value, which asserting on ``project_id`` alone would miss.
    """
    db_path = str(tmp_path / "roundtrip.db")
    # Current-clock base: ``ttl_seconds`` below is live, and a stale
    # ``created_at`` would let the store's TTL sweep cancel the row before
    # the reopen assertion runs.
    created_at = time.time()
    store = _new_store(db_path)
    await store.start()
    try:
        original = await store.create_work_item(
            id="wi-round",
            title="Round trip",
            description="Every field must survive the reopen",
            work_type="task",
            status="open",
            priority=2,
            parent_id="wi-parent",
            project_id="proj-alpha",
            depends_on=["wi-dep-a", "wi-dep-b"],
            assigned_to="agent-7",
            created_by="captain",
            created_at=created_at,
            updated_at=created_at + 1.0,
            due_at=created_at + 3600.0,
            estimated_tokens=1234,
            actual_tokens=567,
            trust_requirement=0.75,
            required_capabilities=["research", "writing"],
            tags=["alpha", "beta"],
            metadata={"note": "hello"},
            steps=[{"label": "step one", "status": "pending"}],
            verification={"kind": "manual"},
            schedule={"cron": "0 9 * * *"},
            ttl_seconds=86_400,
            template_id="tmpl-1",
        )
    finally:
        await store.stop()

    reopened = _new_store(db_path)
    await reopened.start()
    try:
        loaded = await reopened.get_work_item("wi-round")
    finally:
        await reopened.stop()

    assert loaded is not None
    assert loaded.project_id == "proj-alpha"
    assert loaded.to_dict() == original.to_dict()
    # Spelled out so a shifted column cannot hide behind an equal dict.
    assert loaded.id == "wi-round"
    assert loaded.title == "Round trip"
    assert loaded.description == "Every field must survive the reopen"
    assert loaded.work_type == "task"
    assert loaded.status == "open"
    assert loaded.priority == 2
    assert loaded.parent_id == "wi-parent"
    assert loaded.depends_on == ["wi-dep-a", "wi-dep-b"]
    assert loaded.assigned_to == "agent-7"
    assert loaded.created_by == "captain"
    assert loaded.created_at == created_at
    assert loaded.updated_at == created_at + 1.0
    assert loaded.due_at == created_at + 3600.0
    assert loaded.estimated_tokens == 1234
    assert loaded.actual_tokens == 567
    assert loaded.trust_requirement == 0.75
    assert loaded.required_capabilities == ["research", "writing"]
    assert loaded.tags == ["alpha", "beta"]
    assert loaded.metadata == {"note": "hello"}
    assert loaded.steps == [{"label": "step one", "status": "pending"}]
    assert loaded.verification == {"kind": "manual"}
    assert loaded.schedule == {"cron": "0 9 * * *"}
    assert loaded.ttl_seconds == 86_400
    assert loaded.template_id == "tmpl-1"


async def test_real_db_reopen_keeps_absent_project_id_none(tmp_path: Path) -> None:
    db_path = str(tmp_path / "default.db")
    store = _new_store(db_path)
    await store.start()
    try:
        await store.create_work_item(id="wi-plain", title="No project given")
    finally:
        await store.stop()

    reopened = _new_store(db_path)
    await reopened.start()
    try:
        loaded = await reopened.get_work_item("wi-plain")
    finally:
        await reopened.stop()

    assert loaded is not None
    assert loaded.project_id is None


# ---------------------------------------------------------------------------
# Migration from a pre-AD-1176 schema
# ---------------------------------------------------------------------------


async def test_start_migrates_pre_ad1176_database(tmp_path: Path) -> None:
    """The whole point of this AD: an existing install must upgrade in place.

    Hand-builds the 24-column pre-AD-1176 table, inserts a row through raw
    SQL, then opens a ``WorkItemStore`` over that file. ``start()`` must
    succeed, the legacy row must load with ``project_id is None``, and a new
    row must round-trip with a ``project_id`` set.
    """
    db_path = str(tmp_path / "legacy.db")
    now = 1_699_000_000.0
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(_PRE_AD1176_WORK_ITEMS_DDL)
        conn.execute(
            """INSERT INTO work_items (
                id, title, description, work_type, status, priority,
                parent_id, depends_on, assigned_to, created_by,
                created_at, updated_at, due_at, estimated_tokens,
                actual_tokens, trust_requirement, required_capabilities,
                tags, metadata, steps, verification, schedule,
                ttl_seconds, template_id
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                "wi-legacy", "Legacy row", "Written before AD-1176", "task",
                "open", 3, None, json.dumps(["wi-old-dep"]), "agent-legacy",
                "captain", now, now, None, None, 0, 0.0,
                json.dumps(["legacy-cap"]), json.dumps(["legacy-tag"]),
                json.dumps({"legacy": True}), json.dumps([]), json.dumps({}),
                json.dumps({}), None, None,
            ),
        )
        conn.commit()
    finally:
        conn.close()

    assert "project_id" not in _work_item_columns(db_path)

    store = _new_store(db_path)
    await store.start()  # (a) must not raise
    try:
        assert "project_id" in _work_item_columns(db_path)

        legacy = await store.get_work_item("wi-legacy")
        assert legacy is not None
        assert legacy.project_id is None  # (b) legacy row loads, unowned
        assert legacy.title == "Legacy row"
        assert legacy.depends_on == ["wi-old-dep"]
        assert legacy.tags == ["legacy-tag"]
        assert legacy.metadata == {"legacy": True}

        # (c) a new row written against the migrated table carries project_id
        await store.create_work_item(
            id="wi-post", title="After migration", project_id="proj-alpha",
        )
        migrated = await store.get_work_item("wi-post")
        assert migrated is not None
        assert migrated.project_id == "proj-alpha"

        assert await store.list_work_items(project_id="proj-alpha") != []
    finally:
        await store.stop()


async def test_migration_is_idempotent_across_restarts(tmp_path: Path) -> None:
    """``start()`` twice over the same file must not raise on the ALTER."""
    db_path = str(tmp_path / "idempotent.db")
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(_PRE_AD1176_WORK_ITEMS_DDL)
        conn.commit()
    finally:
        conn.close()

    for _ in range(3):
        store = _new_store(db_path)
        await store.start()
        try:
            assert _work_item_columns(db_path).count("project_id") == 1
        finally:
            await store.stop()


async def test_fresh_and_migrated_schemas_have_identical_columns(
    tmp_path: Path,
) -> None:
    """``CREATE TABLE`` and ``ALTER TABLE`` must converge on one schema."""
    fresh_path = str(tmp_path / "fresh.db")
    legacy_path = str(tmp_path / "upgraded.db")
    conn = sqlite3.connect(legacy_path)
    try:
        conn.execute(_PRE_AD1176_WORK_ITEMS_DDL)
        conn.commit()
    finally:
        conn.close()

    for path in (fresh_path, legacy_path):
        store = _new_store(path)
        await store.start()
        await store.stop()

    assert _work_item_columns(fresh_path) == _work_item_columns(legacy_path)
    assert _work_item_columns(fresh_path)[-1] == "project_id"


# ---------------------------------------------------------------------------
# Filtering
# ---------------------------------------------------------------------------


@pytest.fixture
async def populated_store(tmp_path: Path) -> Any:
    """Store seeded with two projects plus one unowned item."""
    store = _new_store(str(tmp_path / "filter.db"))
    await store.start()
    base = time.time()
    await store.create_work_item(
        id="wi-a1", title="Alpha open task", project_id="proj-alpha",
        status="open", work_type="task", assigned_to="agent-1",
        created_at=base,
    )
    await store.create_work_item(
        id="wi-a2", title="Alpha done incident", project_id="proj-alpha",
        status="in_progress", work_type="incident", assigned_to="agent-2",
        created_at=base + 1,
    )
    await store.create_work_item(
        id="wi-b1", title="Beta open task", project_id="proj-beta",
        status="open", work_type="task", assigned_to="agent-1",
        created_at=base + 2,
    )
    await store.create_work_item(
        id="wi-none", title="Unowned", status="open", work_type="task",
        assigned_to="agent-1", created_at=base + 3,
    )
    yield store
    await store.stop()


async def test_list_work_items_filters_by_project(populated_store: Any) -> None:
    items = await populated_store.list_work_items(project_id="proj-alpha")

    assert sorted(i.id for i in items) == ["wi-a1", "wi-a2"]


async def test_list_work_items_unknown_project_returns_empty(
    populated_store: Any,
) -> None:
    assert await populated_store.list_work_items(project_id="proj-ghost") == []


async def test_list_work_items_without_project_returns_everything(
    populated_store: Any,
) -> None:
    """``None`` preserves the pre-AD behaviour — no implicit filtering."""
    items = await populated_store.list_work_items()

    assert sorted(i.id for i in items) == ["wi-a1", "wi-a2", "wi-b1", "wi-none"]


async def test_list_work_items_project_filter_composes_with_other_filters(
    populated_store: Any,
) -> None:
    by_status = await populated_store.list_work_items(
        project_id="proj-alpha", status="open",
    )
    by_work_type = await populated_store.list_work_items(
        project_id="proj-alpha", work_type="incident",
    )
    by_assignee = await populated_store.list_work_items(
        project_id="proj-beta", assigned_to="agent-1",
    )
    contradictory = await populated_store.list_work_items(
        project_id="proj-beta", assigned_to="agent-2",
    )

    assert [i.id for i in by_status] == ["wi-a1"]
    assert [i.id for i in by_work_type] == ["wi-a2"]
    assert [i.id for i in by_assignee] == ["wi-b1"]
    assert contradictory == []


async def test_list_work_items_project_filter_applies_in_sql_before_limit(
    tmp_path: Path,
) -> None:
    """Filtering in SQL, not in memory: LIMIT must apply after the WHERE.

    Twenty non-matching rows are inserted ahead of the single matching one.
    An in-memory filter over a LIMIT-ed page (the ``tags`` pattern) would
    return nothing here.
    """
    store = _new_store(str(tmp_path / "sqlfilter.db"))
    await store.start()
    try:
        base = time.time()
        for n in range(20):
            await store.create_work_item(
                id=f"wi-noise-{n}", title=f"Noise {n}",
                project_id="proj-noise", created_at=base + n,
            )
        await store.create_work_item(
            id="wi-needle", title="Needle", project_id="proj-needle",
            created_at=base - 100,
        )

        found = await store.list_work_items(project_id="proj-needle", limit=5)
    finally:
        await store.stop()

    assert [i.id for i in found] == ["wi-needle"]


# ---------------------------------------------------------------------------
# Mutability
# ---------------------------------------------------------------------------


async def test_update_work_item_sets_and_clears_project_id(
    tmp_path: Path,
) -> None:
    """Work gets reassigned to a project after the fact — and unassigned."""
    store = _new_store(str(tmp_path / "update.db"))
    await store.start()
    try:
        await store.create_work_item(id="wi-move", title="Movable")

        attached = await store.update_work_item("wi-move", project_id="proj-alpha")
        assert attached is not None
        assert attached.project_id == "proj-alpha"
        assert (await store.list_work_items(project_id="proj-alpha"))[0].id == "wi-move"

        moved = await store.update_work_item("wi-move", project_id="proj-beta")
        assert moved is not None
        assert moved.project_id == "proj-beta"
        assert await store.list_work_items(project_id="proj-alpha") == []

        detached = await store.update_work_item("wi-move", project_id=None)
        assert detached is not None
        assert detached.project_id is None
        assert await store.list_work_items(project_id="proj-beta") == []
    finally:
        await store.stop()


# ---------------------------------------------------------------------------
# Soft reference
# ---------------------------------------------------------------------------


async def test_project_reference_is_soft_across_project_deletion(
    tmp_path: Path,
) -> None:
    """No foreign key: a deleted project leaves the work item intact.

    Uses the real ``ProjectStore`` (its own database file) so this asserts
    the actual project lifecycle rather than a stand-in id.
    """
    projects = ProjectStore(tmp_path / "threads.db")
    project = projects.create_project(name="Alpha")

    store = _new_store(str(tmp_path / "soft.db"))
    await store.start()
    try:
        await store.create_work_item(
            id="wi-orphan", title="Survives its project", project_id=project.id,
        )

        deleted, _ = projects.delete_project(project.id)
        assert deleted is True
        assert projects.get_project(project.id) is None

        survivor = await store.get_work_item("wi-orphan")
        assert survivor is not None
        assert survivor.project_id == project.id
        assert [i.id for i in await store.list_work_items()] == ["wi-orphan"]
        # It simply stops being reachable through the project filter's
        # intended meaning — the row itself is untouched.
        assert [i.id for i in await store.list_work_items(project_id=project.id)] == [
            "wi-orphan",
        ]
    finally:
        await store.stop()


async def test_create_accepts_project_id_that_never_existed(
    tmp_path: Path,
) -> None:
    """No existence check at insert — matching ``ChatThread.project_id``."""
    store = _new_store(str(tmp_path / "nocheck.db"))
    await store.start()
    try:
        item = await store.create_work_item(
            id="wi-ghost", title="Points at nothing", project_id="proj-never",
        )
        assert item.project_id == "proj-never"
        stored = await store.get_work_item("wi-ghost")
        assert stored is not None
        assert stored.project_id == "proj-never"
    finally:
        await store.stop()


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------


async def test_post_work_items_persists_project_id(tmp_path: Path) -> None:
    store = _new_store(str(tmp_path / "api-post.db"))
    await store.start()
    _, client = _client(store)
    try:
        async with client:
            resp = await client.post(
                "/api/work-items",
                json={"id": "wi-api", "title": "Via API", "project_id": "proj-alpha"},
            )

        assert resp.status_code == 200
        assert resp.json()["work_item"]["project_id"] == "proj-alpha"
        stored = await store.get_work_item("wi-api")
        assert stored is not None
        assert stored.project_id == "proj-alpha"
    finally:
        await store.stop()


async def test_post_work_items_without_project_id_persists_none(
    tmp_path: Path,
) -> None:
    """Input validation: the field is optional and defaults through the API."""
    store = _new_store(str(tmp_path / "api-post-default.db"))
    await store.start()
    _, client = _client(store)
    try:
        async with client:
            resp = await client.post(
                "/api/work-items", json={"id": "wi-api-bare", "title": "Bare"},
            )

        assert resp.status_code == 200
        assert resp.json()["work_item"]["project_id"] is None
        stored = await store.get_work_item("wi-api-bare")
        assert stored is not None
        assert stored.project_id is None
    finally:
        await store.stop()


async def test_get_work_items_filters_by_project_query_param(
    tmp_path: Path,
) -> None:
    store = _new_store(str(tmp_path / "api-get.db"))
    await store.start()
    _, client = _client(store)
    try:
        await store.create_work_item(
            id="wi-q-alpha", title="Alpha", project_id="proj-alpha",
        )
        await store.create_work_item(
            id="wi-q-beta", title="Beta", project_id="proj-beta",
        )
        await store.create_work_item(id="wi-q-none", title="None")

        async with client:
            scoped = await client.get("/api/work-items?project_id=proj-alpha")
            unknown = await client.get("/api/work-items?project_id=proj-ghost")
            unfiltered = await client.get("/api/work-items")

        assert scoped.status_code == 200
        assert [i["id"] for i in scoped.json()["work_items"]] == ["wi-q-alpha"]
        assert scoped.json()["count"] == 1

        assert unknown.status_code == 200
        assert unknown.json() == {"work_items": [], "count": 0}

        assert unfiltered.status_code == 200
        assert sorted(i["id"] for i in unfiltered.json()["work_items"]) == [
            "wi-q-alpha", "wi-q-beta", "wi-q-none",
        ]
    finally:
        await store.stop()


async def test_get_work_items_project_filter_composes_with_status_param(
    tmp_path: Path,
) -> None:
    store = _new_store(str(tmp_path / "api-compose.db"))
    await store.start()
    _, client = _client(store)
    try:
        await store.create_work_item(
            id="wi-c-open", title="Open", project_id="proj-alpha", status="open",
        )
        await store.create_work_item(
            id="wi-c-prog", title="Running", project_id="proj-alpha",
            status="in_progress",
        )

        async with client:
            resp = await client.get(
                "/api/work-items?project_id=proj-alpha&status=in_progress",
            )

        assert resp.status_code == 200
        assert [i["id"] for i in resp.json()["work_items"]] == ["wi-c-prog"]
    finally:
        await store.stop()


async def test_work_item_routes_503_when_engine_disabled() -> None:
    """Error path: no work item store configured on the runtime."""
    _, client = _client(None)

    async with client:
        listed = await client.get("/api/work-items?project_id=proj-alpha")
        created = await client.post(
            "/api/work-items", json={"title": "x", "project_id": "proj-alpha"},
        )

    assert listed.status_code == 503
    assert created.status_code == 503
