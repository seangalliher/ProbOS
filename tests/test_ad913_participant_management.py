"""AD-913: chat-thread participant management tests (store + REST routes).

Real ``ChatThreadStore`` on ``tmp_path`` at the substrate boundary
(BF-287: no MagicMock for substrate stores). The REST ``client`` fixture
mirrors ``tests/test_ad791_chat_threads.py`` — real store wired into a
``SimpleNamespace`` runtime via ``dependency_overrides[get_runtime]``.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from probos.threads import ChatThread, ChatThreadStore


def _seq_clock():
    """Deterministic monotonic clock so ``last_active_at`` is checkable."""
    n = {"t": 0}

    def _c() -> float:
        n["t"] += 1
        return float(n["t"])

    return _c


# ---------------- Store ----------------


def test_add_participant_appends(tmp_path):
    store = ChatThreadStore(tmp_path / "threads.db")
    t = store.create_thread(title="1:1", participants=["a1"])
    updated = store.add_participant(t.id, "a2")
    assert isinstance(updated, ChatThread)
    assert updated.participants == ["a1", "a2"]


def test_add_participant_idempotent_no_duplicate(tmp_path):
    store = ChatThreadStore(tmp_path / "threads.db")
    t = store.create_thread(title="1:1", participants=["a1"])
    store.add_participant(t.id, "a2")
    updated = store.add_participant(t.id, "a2")
    assert updated is not None
    assert updated.participants.count("a2") == 1
    assert updated.participants == ["a1", "a2"]


def test_add_participant_bumps_last_active_at(tmp_path):
    store = ChatThreadStore(tmp_path / "threads.db", clock=_seq_clock())
    t = store.create_thread(title="1:1", participants=["a1"])
    created_at = t.created_at
    updated = store.add_participant(t.id, "a2")
    assert updated is not None
    assert updated.last_active_at > created_at


def test_add_participant_idempotent_does_not_bump_last_active_at(tmp_path):
    store = ChatThreadStore(tmp_path / "threads.db", clock=_seq_clock())
    t = store.create_thread(title="1:1", participants=["a1"])
    first = store.add_participant(t.id, "a2")
    assert first is not None
    bumped = first.last_active_at
    second = store.add_participant(t.id, "a2")
    assert second is not None
    assert second.last_active_at == bumped


def test_add_participant_missing_thread_returns_none(tmp_path):
    store = ChatThreadStore(tmp_path / "threads.db")
    assert store.add_participant("nope", "a1") is None


def test_remove_participant_removes(tmp_path):
    store = ChatThreadStore(tmp_path / "threads.db")
    t = store.create_thread(title="group", participants=["a1", "a2"])
    updated = store.remove_participant(t.id, "a1")
    assert updated is not None
    assert "a1" not in updated.participants
    assert updated.participants == ["a2"]


def test_remove_participant_absent_is_noop(tmp_path):
    store = ChatThreadStore(tmp_path / "threads.db")
    t = store.create_thread(title="group", participants=["a1", "a2"])
    updated = store.remove_participant(t.id, "a3")
    assert isinstance(updated, ChatThread)
    assert updated.participants == ["a1", "a2"]


def test_remove_participant_missing_thread_returns_none(tmp_path):
    store = ChatThreadStore(tmp_path / "threads.db")
    assert store.remove_participant("nope", "a1") is None


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


def test_rest_add_participant_happy(client):
    c, _ = client
    tid = c.post(
        "/api/threads", json={"title": "1:1", "participants": ["a1"]}
    ).json()["id"]
    r = c.post(f"/api/threads/{tid}/participants", json={"agent_id": "a2"})
    assert r.status_code == 200
    assert "a2" in r.json()["participants"]


def test_rest_add_participant_404_missing_thread(client):
    c, _ = client
    r = c.post("/api/threads/missing/participants", json={"agent_id": "a2"})
    assert r.status_code == 404


def test_rest_add_participant_400_empty_agent_id(client):
    c, _ = client
    tid = c.post(
        "/api/threads", json={"title": "1:1", "participants": ["a1"]}
    ).json()["id"]
    r = c.post(f"/api/threads/{tid}/participants", json={"agent_id": ""})
    assert r.status_code == 400


def test_rest_add_participant_400_missing_agent_id(client):
    c, _ = client
    tid = c.post(
        "/api/threads", json={"title": "1:1", "participants": ["a1"]}
    ).json()["id"]
    r = c.post(f"/api/threads/{tid}/participants", json={})
    assert r.status_code == 400


def test_rest_remove_participant_happy(client):
    c, _ = client
    tid = c.post(
        "/api/threads", json={"title": "group", "participants": ["a1", "a2"]}
    ).json()["id"]
    r = c.delete(f"/api/threads/{tid}/participants/a2")
    assert r.status_code == 200
    assert "a2" not in r.json()["participants"]


def test_rest_remove_participant_404_missing_thread(client):
    c, _ = client
    r = c.delete("/api/threads/missing/participants/a2")
    assert r.status_code == 404
