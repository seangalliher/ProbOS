"""AD-792: sidebar search + recents tests."""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from probos.threads import ChatThreadStore


# ---------------- Store ----------------


def test_search_empty_query_returns_empty(tmp_path):
    store = ChatThreadStore(tmp_path / "t.db")
    store.create_thread(title="Project Aurora kickoff", participants=[])
    assert store.search_threads("") == []
    assert store.search_threads("   ") == []


def test_search_case_insensitive_substring(tmp_path):
    store = ChatThreadStore(tmp_path / "t.db")
    store.create_thread(title="Project Aurora kickoff", participants=[])
    store.create_thread(title="weekly sync", participants=[])
    hits = store.search_threads("aurora")
    assert len(hits) == 1 and "Aurora" in hits[0].title


def test_search_orders_pinned_first(tmp_path):
    store = ChatThreadStore(tmp_path / "t.db")
    t_recent = store.create_thread(title="Aurora ops", participants=[])
    t_pinned = store.create_thread(title="Aurora plan", participants=[])
    store.update_thread(t_pinned.id, pinned=True)
    hits = store.search_threads("Aurora")
    assert hits[0].id == t_pinned.id


def test_recents_excludes_archived(tmp_path):
    clock = {"t": 1.0}
    store = ChatThreadStore(tmp_path / "t.db", clock=lambda: clock["t"])
    a = store.create_thread(title="a", participants=[])
    clock["t"] = 2.0
    b = store.create_thread(title="b", participants=[])
    store.update_thread(b.id, archived=True)
    items = store.recents()
    ids = [t.id for t in items]
    assert a.id in ids and b.id not in ids


def test_recents_ordered_by_last_active_desc(tmp_path):
    clock = {"t": 1.0}
    store = ChatThreadStore(tmp_path / "t.db", clock=lambda: clock["t"])
    a = store.create_thread(title="a", participants=[])
    clock["t"] = 2.0
    b = store.create_thread(title="b", participants=[])
    clock["t"] = 3.0
    store.append_message(a.id, author_id="x", role="captain", body="ping")
    items = store.recents()
    assert items[0].id == a.id and items[1].id == b.id


# ---------------- REST ----------------


@pytest.fixture
def client(tmp_path):
    from probos.routers import threads as threads_router
    from probos.routers.deps import get_runtime

    store = ChatThreadStore(tmp_path / "t.db")
    runtime = SimpleNamespace(chat_thread_store=store)
    app = FastAPI()
    app.include_router(threads_router.router)
    app.dependency_overrides[get_runtime] = lambda: runtime
    return TestClient(app)


def test_rest_search_returns_results(client):
    client.post("/api/threads", json={"title": "Project Aurora", "participants": []})
    client.post("/api/threads", json={"title": "weekly sync", "participants": []})
    r = client.get("/api/threads/search", params={"q": "aurora"})
    assert r.status_code == 200
    assert len(r.json()["results"]) == 1


def test_rest_search_empty_returns_empty_list(client):
    client.post("/api/threads", json={"title": "x", "participants": []})
    r = client.get("/api/threads/search", params={"q": ""})
    assert r.status_code == 200 and r.json()["results"] == []


def test_rest_recents(client):
    for i in range(3):
        client.post("/api/threads", json={"title": f"t{i}", "participants": []})
    r = client.get("/api/threads/recents", params={"limit": 5})
    assert r.status_code == 200
    assert len(r.json()["recents"]) == 3
