"""Tests for AD-750 work router endpoints (routers/work.py)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from probos.knowledge.semantic_store import SemanticStore
from probos.routers.work import router
from probos.types import Task


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _make_store(tmp_path) -> SemanticStore:
    return SemanticStore(db_path=str(tmp_path / "work_router.db"), owner_id="captain")


def _make_app(store: SemanticStore | None) -> FastAPI:
    app = FastAPI()
    app.include_router(router)
    runtime = MagicMock()
    runtime._semantic_store = store
    app.state.runtime = runtime
    return app


@pytest.mark.asyncio
async def test_get_work_tasks_returns_incomplete_tasks_only(tmp_path) -> None:
    """Happy path + boundary: completed filter excludes done tasks."""
    store = _make_store(tmp_path)
    now = _now()
    open_task = Task(
        id=uuid.uuid4().hex,
        entity_type="task",
        owner_id="captain",
        created_at=now,
        modified_at=now,
        content="Daily planning",
        title="Daily planning",
        completed=False,
    )
    done_task = Task(
        id=uuid.uuid4().hex,
        entity_type="task",
        owner_id="captain",
        created_at=now,
        modified_at=now,
        content="Done",
        title="Done",
        completed=True,
    )
    await store.insert_entity(open_task)
    await store.insert_entity(done_task)

    client = TestClient(_make_app(store))
    response = client.get("/api/work/tasks?completed=false")
    assert response.status_code == 200
    ids = {task["id"] for task in response.json()}
    assert open_task.id in ids
    assert done_task.id not in ids
    store.close()


@pytest.mark.asyncio
async def test_post_work_link_creates_cross_reference_and_503_when_store_missing(tmp_path) -> None:
    """Happy path + error path: link API works with store and degrades without store."""
    store = _make_store(tmp_path)
    now = _now()
    source = Task(
        id=uuid.uuid4().hex,
        entity_type="task",
        owner_id="captain",
        created_at=now,
        modified_at=now,
        content="Delegate prep",
        title="Delegate prep",
    )

    await store.insert_entity(source)

    client = TestClient(_make_app(store))
    payload = {
        "source_id": source.id,
        "target_ids": [uuid.uuid4().hex],
        "link_type": "related",
    }
    ok = client.post("/api/work/link", json=payload)
    assert ok.status_code == 200
    assert ok.json()["linked"] == 1

    no_store_client = TestClient(_make_app(None))
    unavailable = no_store_client.post("/api/work/link", json=payload)
    assert unavailable.status_code == 503

    store.close()
