"""AD-815c: promote chat instruction to Task (WorkItem + TaskSession)."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from probos.task_sessions import TaskSessionStore
from probos.threads import ChatThreadStore


class _FakeWorkItem:
    def __init__(self, id: str, **kwargs):
        self.id = id
        self.kwargs = kwargs


class _FakeWorkItemStore:
    def __init__(self):
        self.created: list[dict] = []

    async def create_work_item(self, **kwargs):
        self.created.append(kwargs)
        return _FakeWorkItem(id=f"wi-{len(self.created)}", **kwargs)


class _BrokenWorkItemStore:
    async def create_work_item(self, **kwargs):
        raise RuntimeError("DB down")


@pytest.fixture
def client(tmp_path):
    from probos.routers import threads as router_module
    from probos.routers.deps import get_runtime

    thread_store = ChatThreadStore(tmp_path / "threads.db")
    ts_store = TaskSessionStore(
        db_path=tmp_path / "ts.db",
        workspace_root=tmp_path / "ws",
    )
    wi_store = _FakeWorkItemStore()
    runtime = SimpleNamespace(
        chat_thread_store=thread_store,
        task_session_store=ts_store,
        work_item_store=wi_store,
    )
    app = FastAPI()
    app.include_router(router_module.router)
    app.dependency_overrides[get_runtime] = lambda: runtime
    return TestClient(app), thread_store, ts_store, wi_store


def test_promote_creates_work_item_and_task_session(client):
    c, ts, _, wi = client
    tid = c.post(
        "/api/threads", json={"title": "Brief", "participants": ["yao"]}
    ).json()["id"]
    c.post(
        f"/api/threads/{tid}/messages",
        json={"author_id": "captain", "role": "captain", "body": "Generate the report"},
    )
    r = c.post(
        f"/api/threads/{tid}/promote-to-task",
        json={"title": "Generate report"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["work_item_id"] is not None
    assert body["task_session"]["status"] == "pending"
    assert body["task_session"]["work_item_id"] == body["work_item_id"]
    # Description defaulted from last message body
    assert wi.created[0]["description"] == "Generate the report"
    # Single-participant thread auto-assigns
    assert wi.created[0]["assigned_to"] == "yao"


def test_promote_uses_explicit_description_when_provided(client):
    c, *_ = client
    tid = c.post(
        "/api/threads", json={"title": "x", "participants": ["a"]}
    ).json()["id"]
    r = c.post(
        f"/api/threads/{tid}/promote-to-task",
        json={"title": "Explicit", "description": "Custom brief here"},
    )
    assert r.status_code == 200
    assert r.json()["task_session"]["title"] == "Explicit"


def test_promote_409_when_no_message_and_no_description(client):
    c, *_ = client
    tid = c.post(
        "/api/threads", json={"title": "empty", "participants": ["a"]}
    ).json()["id"]
    r = c.post(f"/api/threads/{tid}/promote-to-task", json={"title": "x"})
    assert r.status_code == 409


def test_promote_404_for_missing_thread(client):
    c, *_ = client
    r = c.post(
        "/api/threads/missing/promote-to-task",
        json={"title": "x", "description": "y"},
    )
    assert r.status_code == 404


def test_promote_passes_through_schedule_and_egress(client):
    c, _, ts_store, _ = client
    tid = c.post(
        "/api/threads", json={"title": "x", "participants": ["a"]}
    ).json()["id"]
    r = c.post(
        f"/api/threads/{tid}/promote-to-task",
        json={
            "title": "Daily",
            "description": "summarize daily",
            "schedule_kind": "recurring",
            "schedule_cron": "0 9 * * *",
            "schedule_timezone": "UTC",
            "recurrence_policy": "new_session_each_run",
            "egress_policy": "none",
        },
    ).json()
    sess_id = r["task_session"]["id"]
    sess = ts_store.get_session(sess_id)
    assert sess.schedule_kind == "recurring"
    assert sess.schedule_cron == "0 9 * * *"
    assert sess.recurrence_policy == "new_session_each_run"
    assert sess.egress_policy == "none"


def test_promote_degrades_when_work_item_store_fails(tmp_path):
    from probos.routers import threads as router_module
    from probos.routers.deps import get_runtime

    thread_store = ChatThreadStore(tmp_path / "threads.db")
    ts_store = TaskSessionStore(
        db_path=tmp_path / "ts.db", workspace_root=tmp_path / "ws"
    )
    runtime = SimpleNamespace(
        chat_thread_store=thread_store,
        task_session_store=ts_store,
        work_item_store=_BrokenWorkItemStore(),
    )
    app = FastAPI()
    app.include_router(router_module.router)
    app.dependency_overrides[get_runtime] = lambda: runtime
    c = TestClient(app)
    tid = c.post(
        "/api/threads", json={"title": "x", "participants": ["a"]}
    ).json()["id"]
    r = c.post(
        f"/api/threads/{tid}/promote-to-task",
        json={"title": "x", "description": "y"},
    )
    # TaskSession still ships; work_item_id is None.
    assert r.status_code == 200
    body = r.json()
    assert body["work_item_id"] is None
    assert body["task_session"]["status"] == "pending"


def test_promote_503_when_task_session_store_missing(tmp_path):
    from probos.routers import threads as router_module
    from probos.routers.deps import get_runtime

    thread_store = ChatThreadStore(tmp_path / "threads.db")
    runtime = SimpleNamespace(chat_thread_store=thread_store)
    app = FastAPI()
    app.include_router(router_module.router)
    app.dependency_overrides[get_runtime] = lambda: runtime
    c = TestClient(app)
    tid = c.post(
        "/api/threads", json={"title": "x", "participants": ["a"]}
    ).json()["id"]
    r = c.post(
        f"/api/threads/{tid}/promote-to-task",
        json={"title": "x", "description": "y"},
    )
    assert r.status_code == 503
