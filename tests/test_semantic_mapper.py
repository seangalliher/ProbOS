"""Tests for AD-750 SemanticMapper (integrations/semantic_mapper.py)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from probos.knowledge.semantic_store import SemanticStore
from probos.integrations.semantic_mapper import SemanticMapper


def _make_store(tmp_path) -> SemanticStore:
    db = str(tmp_path / "mapper_test.db")
    return SemanticStore(db_path=db, owner_id="captain")


@pytest.mark.asyncio
async def test_bootstrap_from_episodic_migrates_expected_entities(tmp_path) -> None:
    """Happy path + boundary: only classifiable episodic docs are migrated."""
    store = _make_store(tmp_path)

    # Fake ChromaDB collection with 3 task/meeting/unclassifiable docs
    fake_collection = MagicMock()
    fake_collection.get.return_value = {
        "ids": ["id-1", "id-2", "id-3"],
        "documents": [
            "Finish the task todo write tests",    # should classify as task
            "Meeting standup with team",            # should classify as meeting
            "Random unrelated note abc xyz",        # should NOT classify
        ],
        "metadatas": [{}, {}, {}],
    }

    fake_episodic = MagicMock()
    fake_episodic._collection = fake_collection

    mapper = SemanticMapper(store=store, owner_id="captain", episodic_memory=fake_episodic)
    count = await mapper.bootstrap_from_episodic(store)

    assert count == 2

    tasks = await store.query_tasks(completed=False)
    meetings = await store.query_meetings(
        (datetime(2000, 1, 1, tzinfo=timezone.utc), datetime.now(timezone.utc))
    )
    assert len(tasks) == 1
    assert len(meetings) == 1
    store.close()


@pytest.mark.asyncio
async def test_sync_m365_to_semantic_handles_success_and_connector_failure(tmp_path) -> None:
    """Happy path + error path: one connector succeeds while another fails."""
    store = _make_store(tmp_path)

    now_str = datetime.now(timezone.utc).isoformat()

    # Fake Calendar connector returning 2 events
    fake_calendar_connector = MagicMock()
    fake_calendar_connector.agent_type = "CalendarAgent"
    fake_calendar_connector.list_changes = AsyncMock(return_value=[
        {
            "id": uuid.uuid4().hex,
            "subject": "Sprint planning",
            "start": now_str,
            "end": now_str,
            "attendees": ["alice"],
            "created_at": now_str,
        },
        {
            "id": uuid.uuid4().hex,
            "subject": "Retrospective",
            "start": now_str,
            "end": now_str,
            "attendees": ["bob"],
            "created_at": now_str,
        },
    ])

    failing_connector = MagicMock()
    failing_connector.agent_type = "OutlookAgent"
    failing_connector.list_changes = AsyncMock(side_effect=RuntimeError("connector down"))

    mapper = SemanticMapper(store=store, owner_id="captain")
    count = await mapper.sync_m365_to_semantic([fake_calendar_connector, failing_connector])

    assert count == 2
    meetings = await store.query_meetings(
        (datetime(2000, 1, 1, tzinfo=timezone.utc), datetime.now(timezone.utc))
    )
    assert len(meetings) == 2
    store.close()
