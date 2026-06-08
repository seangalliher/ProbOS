"""AD-920: meeting-mode flag tests (store + PATCH route).

A meeting is a live MODE of a group chat. ``metadata.meeting_active`` is
the persisted flag the UI gallery (and future voice path) reads to know
the meeting is open. The scoped ``ChatThreadStore.set_meeting_active``
writer is a ``BEGIN IMMEDIATE`` read-modify-write that MERGES the JSON
``metadata`` column (mirroring ``set_title(lock=True)``), so sibling keys
such as ``created_by_agent`` (AD-918) and ``title_locked`` (AD-794) are
preserved.

Real ``ChatThreadStore`` on ``tmp_path`` at the substrate boundary
(BF-287: no MagicMock for substrate stores). The REST ``client`` fixture
mirrors ``tests/test_ad913_participant_management.py`` — real store wired
into a ``SimpleNamespace`` runtime via ``dependency_overrides[get_runtime]``.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from probos.threads import ChatThread, ChatThreadStore


# ---------------- Store ----------------


def test_set_meeting_active_true_writes_flag(tmp_path):
    store = ChatThreadStore(tmp_path / "threads.db")
    t = store.create_thread(title="group", participants=["a1", "a2"])
    updated = store.set_meeting_active(t.id, True)
    assert isinstance(updated, ChatThread)
    assert updated.metadata["meeting_active"] is True


def test_set_meeting_active_false_removes_key(tmp_path):
    store = ChatThreadStore(tmp_path / "threads.db")
    t = store.create_thread(title="group", participants=["a1", "a2"])
    store.set_meeting_active(t.id, True)
    updated = store.set_meeting_active(t.id, False)
    assert updated is not None
    assert "meeting_active" not in updated.metadata


def test_set_meeting_active_missing_thread_returns_none(tmp_path):
    store = ChatThreadStore(tmp_path / "threads.db")
    assert store.set_meeting_active("missing", True) is None


def test_set_meeting_active_preserves_sibling_metadata(tmp_path):
    store = ChatThreadStore(tmp_path / "threads.db")
    t = store.create_thread(
        title="group",
        participants=["a1", "a2"],
        metadata={"created_by_agent": "bones", "title_locked": True},
    )
    updated = store.set_meeting_active(t.id, True)
    assert updated is not None
    assert updated.metadata["meeting_active"] is True
    assert updated.metadata["created_by_agent"] == "bones"
    assert updated.metadata["title_locked"] is True


# ---------------- Router (PATCH) ----------------


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


def test_patch_meeting_active_true(client):
    c, _ = client
    tid = c.post(
        "/api/threads", json={"title": "group", "participants": ["a1", "a2"]}
    ).json()["id"]
    r = c.patch(f"/api/threads/{tid}", json={"meeting_active": True})
    assert r.status_code == 200
    assert r.json()["metadata"]["meeting_active"] is True


def test_patch_meeting_active_false_clears(client):
    c, _ = client
    tid = c.post(
        "/api/threads", json={"title": "group", "participants": ["a1", "a2"]}
    ).json()["id"]
    c.patch(f"/api/threads/{tid}", json={"meeting_active": True})
    r = c.patch(f"/api/threads/{tid}", json={"meeting_active": False})
    assert r.status_code == 200
    assert "meeting_active" not in r.json()["metadata"]


def test_patch_meeting_active_missing_thread_404(client):
    c, _ = client
    r = c.patch("/api/threads/missing", json={"meeting_active": True})
    assert r.status_code == 404


def test_patch_meeting_active_does_not_touch_title(client):
    c, _ = client
    tid = c.post(
        "/api/threads", json={"title": "Quarterly sync", "participants": ["a1", "a2"]}
    ).json()["id"]
    r = c.patch(f"/api/threads/{tid}", json={"meeting_active": True})
    assert r.status_code == 200
    body = r.json()
    assert body["title"] == "Quarterly sync"
    assert body["metadata"]["meeting_active"] is True
