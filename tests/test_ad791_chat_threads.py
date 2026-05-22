"""AD-791: chat-threads substrate tests (store + REST routes)."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from probos.threads import ChatThread, ChatThreadStore


# ---------------- Store ----------------


def test_create_thread_assigns_id_and_timestamps(tmp_path):
    store = ChatThreadStore(tmp_path / "threads.db")
    t = store.create_thread(title="Hello", participants=["agent-1"])
    assert t.id and isinstance(t.id, str)
    assert t.title == "Hello"
    assert t.participants == ["agent-1"]
    assert t.created_at == t.last_active_at
    assert not t.pinned and not t.archived


def test_get_thread_round_trips(tmp_path):
    store = ChatThreadStore(tmp_path / "threads.db")
    created = store.create_thread(
        title="Project sync",
        participants=["agent-1", "agent-2"],
        project_id="proj-7",
        personality_override="formal",
    )
    fetched = store.get_thread(created.id)
    assert fetched is not None
    assert fetched.project_id == "proj-7"
    assert fetched.personality_override == "formal"
    assert set(fetched.participants) == {"agent-1", "agent-2"}


def test_list_threads_excludes_archived_by_default(tmp_path):
    store = ChatThreadStore(tmp_path / "threads.db")
    a = store.create_thread(title="A", participants=[])
    b = store.create_thread(title="B", participants=[])
    store.update_thread(b.id, archived=True)
    listed = store.list_threads()
    ids = [t.id for t in listed]
    assert a.id in ids and b.id not in ids
    full = store.list_threads(include_archived=True)
    assert {t.id for t in full} == {a.id, b.id}


def test_list_threads_filters_by_project(tmp_path):
    store = ChatThreadStore(tmp_path / "threads.db")
    store.create_thread(title="X", participants=[], project_id="P1")
    store.create_thread(title="Y", participants=[], project_id="P2")
    store.create_thread(title="Z", participants=[])
    p1 = store.list_threads(project_id="P1")
    assert len(p1) == 1 and p1[0].title == "X"


def test_list_threads_sorts_pinned_first(tmp_path):
    store = ChatThreadStore(tmp_path / "threads.db")
    t_old = store.create_thread(title="old", participants=[])
    t_new = store.create_thread(title="new", participants=[])
    store.update_thread(t_old.id, pinned=True)
    listed = store.list_threads()
    assert listed[0].id == t_old.id


def test_update_thread_returns_none_for_missing(tmp_path):
    store = ChatThreadStore(tmp_path / "threads.db")
    assert store.update_thread("does-not-exist", title="x") is None


def test_delete_thread_cascades_messages(tmp_path):
    store = ChatThreadStore(tmp_path / "threads.db")
    t = store.create_thread(title="t", participants=[])
    store.append_message(t.id, author_id="captain", role="captain", body="hi")
    assert store.delete_thread(t.id) is True
    assert store.list_messages(t.id) == []


def test_append_message_updates_last_active(tmp_path):
    clock = {"t": 100.0}
    store = ChatThreadStore(tmp_path / "threads.db", clock=lambda: clock["t"])
    t = store.create_thread(title="t", participants=[])
    clock["t"] = 250.0
    msg = store.append_message(t.id, author_id="captain", role="captain", body="hi")
    assert msg is not None
    refreshed = store.get_thread(t.id)
    assert refreshed.last_active_at == 250.0


def test_append_message_returns_none_for_missing_thread(tmp_path):
    store = ChatThreadStore(tmp_path / "threads.db")
    assert store.append_message("nope", author_id="x", role="agent", body="y") is None


def test_list_messages_chronological(tmp_path):
    clock = {"t": 1.0}
    store = ChatThreadStore(tmp_path / "threads.db", clock=lambda: clock["t"])
    t = store.create_thread(title="t", participants=[])
    for i in range(3):
        clock["t"] = float(10 + i)
        store.append_message(t.id, author_id="a", role="agent", body=f"m{i}")
    msgs = store.list_messages(t.id)
    assert [m.body for m in msgs] == ["m0", "m1", "m2"]


def test_list_messages_before_filter(tmp_path):
    clock = {"t": 1.0}
    store = ChatThreadStore(tmp_path / "threads.db", clock=lambda: clock["t"])
    t = store.create_thread(title="t", participants=[])
    for i in range(3):
        clock["t"] = float(10 + i)
        store.append_message(t.id, author_id="a", role="agent", body=f"m{i}")
    msgs = store.list_messages(t.id, before=11.5)
    assert [m.body for m in msgs] == ["m0", "m1"]


# ---------------- REST ----------------


@pytest.fixture
def client(tmp_path):
    from probos.routers import threads as threads_router
    from probos.routers.deps import get_runtime

    store = ChatThreadStore(tmp_path / "threads.db")
    runtime = SimpleNamespace(chat_thread_store=store)

    app = FastAPI()
    app.include_router(threads_router.router)
    app.dependency_overrides[get_runtime] = lambda: runtime
    return TestClient(app), store


def test_rest_create_and_list(client):
    c, _ = client
    r = c.post("/api/threads", json={"title": "First", "participants": ["a1"]})
    assert r.status_code == 200
    tid = r.json()["id"]
    r = c.get("/api/threads")
    assert r.status_code == 200
    titles = [t["title"] for t in r.json()["threads"]]
    assert "First" in titles


def test_rest_get_404(client):
    c, _ = client
    r = c.get("/api/threads/missing")
    assert r.status_code == 404


def test_rest_patch_archive(client):
    c, _ = client
    tid = c.post("/api/threads", json={"title": "x", "participants": []}).json()["id"]
    r = c.patch(f"/api/threads/{tid}", json={"archived": True})
    assert r.status_code == 200 and r.json()["archived"] is True
    listed = c.get("/api/threads").json()["threads"]
    assert tid not in [t["id"] for t in listed]
    listed_all = c.get("/api/threads", params={"include_archived": True}).json()["threads"]
    assert tid in [t["id"] for t in listed_all]


def test_rest_messages_round_trip(client):
    c, _ = client
    tid = c.post("/api/threads", json={"title": "t", "participants": []}).json()["id"]
    r = c.post(
        f"/api/threads/{tid}/messages",
        json={"author_id": "captain", "role": "captain", "body": "Hello"},
    )
    assert r.status_code == 200
    msgs = c.get(f"/api/threads/{tid}/messages").json()["messages"]
    assert len(msgs) == 1 and msgs[0]["body"] == "Hello"


def test_rest_delete(client):
    c, _ = client
    tid = c.post("/api/threads", json={"title": "t", "participants": []}).json()["id"]
    r = c.delete(f"/api/threads/{tid}")
    assert r.status_code == 200 and r.json()["deleted"] is True
    assert c.get(f"/api/threads/{tid}").status_code == 404


def test_rest_message_role_validation(client):
    c, _ = client
    tid = c.post("/api/threads", json={"title": "t", "participants": []}).json()["id"]
    r = c.post(
        f"/api/threads/{tid}/messages",
        json={"author_id": "x", "role": "invalid", "body": "y"},
    )
    assert r.status_code == 422


def test_rest_503_when_store_missing(tmp_path):
    from probos.routers import threads as threads_router
    from probos.routers.deps import get_runtime

    app = FastAPI()
    app.include_router(threads_router.router)
    app.dependency_overrides[get_runtime] = lambda: SimpleNamespace()
    c = TestClient(app)
    assert c.get("/api/threads").status_code == 503
