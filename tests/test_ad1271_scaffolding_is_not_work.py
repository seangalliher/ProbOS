"""AD-1271 / BF-735 (#1194): scaffolding is not work.

36 permanently-open `Room workspace` rows existed because a chat thread needs a
`task_id` for its FILES rail to bind to. Nothing was ever meant to complete
them. While they sat in `open`, the ship told the Captain it had 36 open work
items in THREE separate narrations -- `captains_log`, `plan_of_day` and
`ship_state_snapshot` all render `f"Open work items: {len(items)}"` -- on top of
the board and the Quartermaster's sweep.

Measured on the live vessel (read-only, 2026-08-25) before any of this was
designed:

* 77 rows total: 36 open / 27 done / 13 cancelled / 1 failed. Every `open` row
  is titled `Room workspace`, so the open column was ENTIRELY scaffolding.
* All 36 are `assigned_to=None`, `work_type=task`, `parent_id=None`, aged
  39.3-58.3 days, and all 36 are LIVE-BOUND: 36 chat threads hold that row's id
  in `ChatThread.task_id`, and zero threads bind to anything else. Deleting them
  would break the rail binding on every room the Captain has.
* 32 are inert (`steps` empty, `metadata` `{}`). **Four are not** -- they carry
  real three-step Captain-visible checklists with `steps_gate_completion`, on
  rooms last active 58 days ago. Those are abandoned WORK, not scaffolding.

So the fix is a store-level default exclusion (this file) plus a one-off
migration that flags all 36 by provenance and cancels the 4 by work state.

The producer is already dead: AD-1128 (2026-07-21) removed the passive UI POST,
and `WorkspaceFilesRail.test.tsx` pins `'ensureRoomTask' in todosApi` false.

Asked of the real `WorkTypeRegistry` rather than read off the source, because
the migration is only legal if these edges are:

    open -> done       INVALID   ("work type 'task' does not allow" it)
    open -> cancelled  VALID, and requires_assignment=False

which is why "just mark the 32 done" is not on the table at all, and why
cancelling four unassigned rows is.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from probos.workforce import WorkItem, WorkItemStore


@pytest.fixture
async def store(tmp_path):
    """A REAL sqlite-backed store. `db_path=""` is cache-only and would never
    execute the SQL this file exists to test."""
    s = WorkItemStore(db_path=str(tmp_path / "workforce.db"))
    await s.start()
    try:
        yield s
    finally:
        await s.stop()


async def _add(
    store: WorkItemStore,
    *,
    title: str,
    metadata: dict[str, Any] | None = None,
    status: str = "open",
    priority: int = 5,
) -> WorkItem:
    """Create a row, flagging it BELOW the store when the flag is wanted.

    The store refuses `ui_scaffold` from an ordinary write on purpose -- it is
    an invisibility switch -- so a flagged fixture has to arrive the way the
    real rows did: written directly by the one-off migration, under the public
    API. Going through `create_work_item` here would test nothing but the
    guard.
    """
    meta = dict(metadata) if metadata else {}
    flagged = meta.pop("ui_scaffold", None)
    item = await store.create_work_item(
        title=title,
        work_type="task",
        status=status,
        priority=priority,
        metadata=meta,
    )
    if flagged:
        meta["ui_scaffold"] = True
        await store._db.execute(
            "UPDATE work_items SET metadata = ? WHERE id = ?",
            (json.dumps(meta, sort_keys=True), item.id),
        )
        await store._db.commit()
        refreshed = await store.get_work_item(item.id)
        assert refreshed is not None
        return refreshed
    return item


# ---------------------------------------------------------------------------
# The contract
# ---------------------------------------------------------------------------


async def test_a_scaffolding_row_is_excluded_by_default(store) -> None:
    await _add(store, title="Room workspace", metadata={"ui_scaffold": True})
    real = await _add(store, title="Real work")

    listed = await store.list_work_items(status="open")

    assert [i.id for i in listed] == [real.id], (
        "a UI binding was counted as open work"
    )


async def test_include_scaffold_returns_it(store) -> None:
    """A migration, and an operator asking what is actually in there, both need
    the unfiltered view -- otherwise the flag hides the rows from the only tool
    that could ever un-flag them."""
    scaffold = await _add(
        store, title="Room workspace", metadata={"ui_scaffold": True}
    )
    real = await _add(store, title="Real work")

    listed = await store.list_work_items(status="open", include_scaffold=True)

    assert {i.id for i in listed} == {scaffold.id, real.id}


@pytest.mark.parametrize(
    "metadata",
    [
        pytest.param(None, id="null-metadata"),
        pytest.param({}, id="empty-metadata"),
        pytest.param({"other": "value"}, id="unrelated-key"),
        pytest.param({"ui_scaffold": False}, id="explicitly-false"),
    ],
)
async def test_ordinary_rows_are_never_dropped(store, metadata) -> None:
    """Pins `IS NOT 1` rather than `!= 1`.

    `json_extract` yields NULL when the key is absent, and `NULL != 1` is NULL,
    which SQLite treats as FALSE -- so the `!=` spelling would drop every
    ordinary row in the table. That mistake is invisible in a fixture where
    every row carries metadata.
    """
    item = await _add(store, title="Real work", metadata=metadata)

    listed = await store.list_work_items(status="open")

    assert [i.id for i in listed] == [item.id]


async def test_the_scaffold_predicate_survives_non_json_metadata(
    store, tmp_path
) -> None:
    """A hand-edited metadata column must not make the WHERE clause raise.

    Scoped to the predicate deliberately. `_row_to_work_item` calls
    `json.loads` on that column and raises on junk, which is pre-existing and
    unchanged here -- asserting that the whole listing degrades would be
    claiming a property this change does not deliver. What IS new is the
    `json_valid` guard.

    Driven through the PRODUCTION constant, not a copy of it. The first version
    of this test pasted the SQL into the test body, so mutating the real
    predicate left it green -- it was testing a string the test itself owned.
    """
    from probos.workforce import _SCAFFOLD_EXCLUSION_SQL

    item = await _add(store, title="Real work")
    await store._db.execute(
        "UPDATE work_items SET metadata = ? WHERE id = ?", ("not json{", item.id)
    )
    await store._db.commit()

    cursor = await store._db.execute(
        f"SELECT item.id FROM work_items AS item WHERE {_SCAFFOLD_EXCLUSION_SQL}"
    )
    rows = await cursor.fetchall()

    assert [r["id"] for r in rows] == [item.id], (
        "the predicate dropped or failed on a row whose metadata is not JSON"
    )


async def test_the_filter_runs_before_the_limit(store) -> None:
    """The whole point of filtering in SQL.

    Filtering after the fetch lets scaffolding consume the LIMIT and hide real
    work behind it -- which is the live shape exactly: 36 scaffolding rows and
    a default limit of 50. `tags` is filtered post-fetch and shows what that
    looks like; this must not join it.
    """
    for i in range(10):
        await _add(
            store,
            title=f"Room workspace {i}",
            metadata={"ui_scaffold": True},
            priority=1,  # sorted FIRST, so they take the LIMIT
        )
    real = await _add(store, title="Real work", priority=9)

    listed = await store.list_work_items(status="open", limit=5)

    assert [i.id for i in listed] == [real.id], (
        "scaffolding consumed the LIMIT and hid the real row behind it"
    )


async def test_the_exclusion_composes_with_the_other_filters(store) -> None:
    await _add(
        store, title="Room workspace", metadata={"ui_scaffold": True}, status="open"
    )
    real = await _add(store, title="Real work", status="open")
    await _add(store, title="Done work", status="open")

    open_items = await store.list_work_items(status="open", work_type="task")

    assert real.id in {i.id for i in open_items}
    assert all(
        not (i.metadata or {}).get("ui_scaffold") for i in open_items
    )


async def test_nothing_in_the_table_carries_the_flag_before_a_migration(
    store,
) -> None:
    """The safety property behind shipping the default as EXCLUDE.

    Default-exclude only removes rows that carry the flag, and no code path
    writes it -- only the one-off migration does. So every existing call site
    sees byte-identical results from the contract change alone, which is what
    makes a default change to a 47-call-site method safe to ship.
    """
    for title in ("a", "b", "c"):
        await _add(store, title=title)

    with_flag = [
        i
        for i in await store.list_work_items(include_scaffold=True, limit=100)
        if (i.metadata or {}).get("ui_scaffold")
    ]

    assert with_flag == []
    assert len(await store.list_work_items(limit=100)) == 3


# ---------------------------------------------------------------------------
# The seam: store -> the three narrators that tell the Captain a number
# ---------------------------------------------------------------------------


async def test_the_captains_log_stops_counting_scaffolding(store) -> None:
    """Store to NARRATOR in one test.

    Two tests each stopping at the boundary would prove the filter works and
    that the log renders a count, and nothing about whether the log's count is
    the filtered one. `captains_log.py:207` renders
    `f"Open work items: {len(items)}"` straight off `list_work_items` -- this is
    the sentence the Captain actually reads.
    """
    for i in range(3):
        await _add(
            store, title=f"Room workspace {i}", metadata={"ui_scaffold": True}
        )

    from types import SimpleNamespace

    from probos.config import CaptainsLogConfig
    from probos.naval.captains_log import CaptainsLogService

    service = CaptainsLogService(
        runtime=SimpleNamespace(work_item_store=store),
        config=CaptainsLogConfig(),
    )
    section = await service._collect_work_items_section()

    assert section == "_(no open work items)_", (
        f"the Captain is still told about scaffolding: {section!r}"
    )


# ---------------------------------------------------------------------------
# The four rows that are NOT scaffolding
# ---------------------------------------------------------------------------


async def test_an_abandoned_gated_checklist_can_still_be_cancelled(store) -> None:
    """The shape of the four live rows, driven through the real state machine.

    They are unassigned, `steps_gate_completion` is set, and their steps are
    unfinished. `open -> done` is not an edge `task` has at all, so the only
    terminal state available is `cancelled` -- and the AD-1080 gate must stay
    scoped to `done` or these four could never be closed by anything.
    """
    item = await store.create_work_item(
        title="Room workspace",
        work_type="task",
        status="open",
        assigned_to=None,
        metadata={"steps_gate_completion": True},
        steps=[
            {"label": "Ezri: write a paragraph", "status": "submitted"},
            {"label": "Yeo: write a paragraph", "status": "pending"},
        ],
    )

    valid, reason = store.work_type_registry.validate_transition(
        "task", "open", "done"
    )
    assert valid is False, (
        f"premise: 'done' must be unreachable for a task, else the whole "
        f"cancel decision is moot -- {reason}"
    )

    cancelled = await store.transition_work_item(item.id, "cancelled")

    assert cancelled is not None
    assert cancelled.status == "cancelled"
    assert len(cancelled.steps) == 2, "cancelling must not discard the checklist"


async def test_a_cancelled_room_keeps_its_checklist_readable(store) -> None:
    """The reason cancelling the four is safe.

    The room's Todo panel fetches steps BY ID (`GET /work-items/{id}/steps`),
    never through `list_work_items`, so a cancelled row still shows the Captain
    what was asked and how far it got. Deleting the row is what would destroy
    that.
    """
    item = await store.create_work_item(
        title="Room workspace",
        work_type="task",
        status="open",
        metadata={"steps_gate_completion": True},
        steps=[{"label": "Ezri: write a paragraph", "status": "submitted"}],
    )
    await store.transition_work_item(item.id, "cancelled")

    fetched = await store.get_work_item(item.id)

    assert fetched is not None
    assert fetched.status == "cancelled"
    assert fetched.steps[0]["label"] == "Ezri: write a paragraph"
    assert bool((fetched.metadata or {}).get("steps_gate_completion")) is True


async def test_a_cancelled_scaffolding_row_is_still_excluded(store) -> None:
    """Flag and status are independent axes.

    Provenance ("this came from a rail binding") does not change when a Captain
    later types a checklist into the row, and work state does not change because
    the row was scaffolding. The migration flags all 36 and cancels only the 4.
    """
    item = await _add(
        store, title="Room workspace", metadata={"ui_scaffold": True}
    )
    await store.transition_work_item(item.id, "cancelled")

    assert await store.list_work_items(status="cancelled") == []
    assert len(
        await store.list_work_items(status="cancelled", include_scaffold=True)
    ) == 1


# ---------------------------------------------------------------------------
# The flag must be unreachable from an ordinary write
# ---------------------------------------------------------------------------


async def test_an_ordinary_create_cannot_set_the_scaffold_flag(store) -> None:
    """The flag decides whether a row is visible to the Captain AT ALL.

    Review measured the first draft letting a real work item be created with
    `metadata={"ui_scaffold": True}` and vanish from every default consumer --
    an invisibility switch reachable from `POST /api/work-items`, which passes
    the request body's metadata straight through.

    Raises rather than strips, mirroring `crew_session_write_reserved` beside
    it: a caller whose value was silently discarded would believe it took
    effect.
    """
    with pytest.raises(ValueError, match="ui_scaffold_write_reserved"):
        await store.create_work_item(
            title="A real work item someone tried to hide",
            work_type="task",
            status="open",
            metadata={"ui_scaffold": True},
        )

    assert len(await store.list_work_items(status="open", limit=100)) == 0


async def test_an_ordinary_update_cannot_hide_an_existing_row(store) -> None:
    """The same switch, reached from the other direction.

    Measured on the first draft: a previously-visible real row disappeared from
    the default listing after one `update_work_item`.
    """
    item = await _add(store, title="Real work")
    assert [i.id for i in await store.list_work_items(status="open")] == [item.id]

    with pytest.raises(ValueError, match="ui_scaffold_write_reserved"):
        await store.update_work_item(item.id, metadata={"ui_scaffold": True})

    assert [i.id for i in await store.list_work_items(status="open")] == [item.id], (
        "the row was hidden despite the write being refused"
    )


async def test_a_metadata_merge_cannot_set_the_scaffold_flag(store) -> None:
    item = await _add(store, title="Real work")

    with pytest.raises(ValueError, match="ui_scaffold_write_reserved"):
        await store.merge_work_item_metadata(item.id, {"ui_scaffold": True})

    assert [i.id for i in await store.list_work_items(status="open")] == [item.id]


async def test_an_unrelated_metadata_write_is_untouched(store) -> None:
    """The guard must reject one key, not make metadata writes awkward."""
    item = await _add(store, title="Real work")

    await store.update_work_item(item.id, metadata={"anything": "else"})
    merged = await store.merge_work_item_metadata(item.id, {"more": 1})

    assert merged is not None
    assert merged.metadata["anything"] == "else"
    assert merged.metadata["more"] == 1


# ---------------------------------------------------------------------------
# The board's own live source
# ---------------------------------------------------------------------------


async def test_the_websocket_board_source_also_excludes_scaffolding(store) -> None:
    """`list_ws_visible_work_items` has its OWN SQL and does not go through
    `list_work_items`.

    Review measured scaffolding still reaching it after the default lister was
    filtered -- exactly the "every consumer has to know better" failure the
    store-level default exists to avoid, reappearing one method along. There is
    deliberately no override: nothing renders a UI binding on a work board.
    """
    scaffold = await _add(
        store, title="Room workspace", metadata={"ui_scaffold": True}
    )
    real = await _add(store, title="Real work")

    visible = await store.list_ws_visible_work_items(limit=50)

    assert [i.id for i in visible] == [real.id], (
        f"the board's live source still surfaces scaffolding: "
        f"{[i.title for i in visible]}"
    )
    assert scaffold.id not in {i.id for i in visible}


async def test_the_websocket_source_still_returns_ordinary_rows(store) -> None:
    """Premise for the test above: without it, an empty result would pass."""
    for i in range(3):
        await _add(store, title=f"Real work {i}")

    visible = await store.list_ws_visible_work_items(limit=50)

    assert len(visible) == 3


# ---------------------------------------------------------------------------
# The producer must stay dead
# ---------------------------------------------------------------------------


def test_no_source_path_writes_the_scaffold_flag() -> None:
    """A LITERAL census, and deliberately the weaker half of the guarantee.

    Review was right that this alone gives false confidence: the real write
    surface is `POST /api/work-items`, which forwards a caller-supplied
    metadata dict and never mentions the key by name, so no literal scan could
    ever see it. The behavioural guarantee is
    `test_an_ordinary_create_cannot_set_the_scaffold_flag` and its siblings;
    this catches the different mistake of a NEW production site starting to
    write the flag directly, which would bypass the store guard by construction
    if it wrote raw SQL.

    Scanned through the AST, not line by line, because a text scan matches its
    own explanatory prose -- the first version failed on the docstring in
    `list_work_items` describing the very rule it checks. Comments are absent
    from the AST entirely; docstrings are excluded explicitly.

    Matched on the EXACT literal `"ui_scaffold"`, the spelling of a dict key or
    an index. `SCAFFOLD_METADATA_FLAG`'s own definition is the one permitted
    site.
    """
    import ast
    import pathlib

    src = pathlib.Path(__file__).resolve().parents[1] / "src" / "probos"
    assert src.is_dir(), f"premise: the source tree must exist at {src}"

    def _docstring_nodes(tree: ast.AST) -> set[int]:
        found: set[int] = set()
        for node in ast.walk(tree):
            if not isinstance(
                node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
            ):
                continue
            body = getattr(node, "body", None)
            if not body:
                continue
            first = body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
                if isinstance(first.value.value, str):
                    found.add(id(first.value))
        return found

    scanned = 0
    writers: list[str] = []
    for path in src.rglob("*.py"):
        text = path.read_text(encoding="utf-8", errors="replace")
        if "ui_scaffold" not in text:
            continue
        scanned += 1
        tree = ast.parse(text)
        docstrings = _docstring_nodes(tree)
        # The constant's own definition: SCAFFOLD_METADATA_FLAG = "ui_scaffold"
        permitted: set[int] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant):
                targets = [
                    t.id for t in node.targets if isinstance(t, ast.Name)
                ]
                if "SCAFFOLD_METADATA_FLAG" in targets:
                    permitted.add(id(node.value))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Constant):
                continue
            if id(node) in docstrings or id(node) in permitted:
                continue
            if not isinstance(node.value, str) or node.value != "ui_scaffold":
                continue
            writers.append(f"{path.name}:{node.lineno}")

    assert scanned >= 1, (
        "premise: no source file mentions ui_scaffold at all, so this guard "
        "would pass against a tree that never grew the feature"
    )
    assert writers == [], f"production now writes the scaffold flag: {writers}"
