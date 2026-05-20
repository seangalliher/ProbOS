"""Tests for AD-750 SemanticStore (knowledge/semantic_store.py)."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from probos.knowledge.semantic_store import SemanticStore
from probos.types import Meeting, Task


def _make_store(tmp_path) -> SemanticStore:
    return SemanticStore(db_path=str(tmp_path / "semantic_store.db"), owner_id="captain")


def _now() -> datetime:
    return datetime.now(timezone.utc)


@pytest.mark.asyncio
async def test_insert_entity_and_query_tasks_with_due_filter(tmp_path) -> None:
    """Happy path + boundary: retrieves only incomplete tasks due before cutoff."""
    store = _make_store(tmp_path)
    now = _now()
    early = Task(
        id=uuid.uuid4().hex,
        entity_type="task",
        owner_id="captain",
        created_at=now,
        modified_at=now,
        content="Send standup notes",
        title="Send standup notes",
        due_date=now + timedelta(hours=1),
        completed=False,
    )
    late = Task(
        id=uuid.uuid4().hex,
        entity_type="task",
        owner_id="captain",
        created_at=now,
        modified_at=now,
        content="Draft roadmap",
        title="Draft roadmap",
        due_date=now + timedelta(days=2),
        completed=False,
    )
    done = Task(
        id=uuid.uuid4().hex,
        entity_type="task",
        owner_id="captain",
        created_at=now,
        modified_at=now,
        content="Closed item",
        title="Closed item",
        completed=True,
    )
    await store.insert_entity(early)
    await store.insert_entity(late)
    await store.insert_entity(done)

    results = await store.query_tasks(
        due_before=now + timedelta(hours=12),
        completed=False,
    )
    ids = {r.id for r in results}
    assert early.id in ids
    assert late.id not in ids
    assert done.id not in ids
    store.close()


@pytest.mark.asyncio
async def test_link_entities_and_get_linked_entity_ids(tmp_path) -> None:
    """Happy path + boundary: link retrieval is scoped by link_type."""
    store = _make_store(tmp_path)
    now = _now()
    task = Task(
        id=uuid.uuid4().hex,
        entity_type="task",
        owner_id="captain",
        created_at=now,
        modified_at=now,
        content="Prepare demo",
        title="Prepare demo",
    )
    meeting = Meeting(
        id=uuid.uuid4().hex,
        entity_type="meeting",
        owner_id="captain",
        created_at=now,
        modified_at=now,
        content="Demo sync",
        title="Demo sync",
        start_time=now,
        end_time=now + timedelta(minutes=30),
        attendees=["captain"],
    )
    await store.insert_entity(task)
    await store.insert_entity(meeting)
    await store.link_entities(task.id, [meeting.id], "depends_on")

    depends_ids = await store.get_linked_entity_ids(task.id, "depends_on")
    unrelated_ids = await store.get_linked_entity_ids(task.id, "related")
    assert meeting.id in depends_ids
    assert unrelated_ids == []
    store.close()


@pytest.mark.asyncio
async def test_search_returns_matches_and_handles_non_matches(tmp_path) -> None:
    """Happy path + error-like boundary: non-match query returns empty list."""
    store = _make_store(tmp_path)
    now = _now()
    task = Task(
        id=uuid.uuid4().hex,
        entity_type="task",
        owner_id="captain",
        created_at=now,
        modified_at=now,
        content="Summarize architecture review notes",
        title="Architecture summary",
    )
    await store.insert_entity(task)

    matching = await store.search("architecture")
    not_found = await store.search("doesnotexisttoken")
    assert any(entity.id == task.id for entity in matching)
    assert not any(entity.id == task.id for entity in not_found)
    store.close()
