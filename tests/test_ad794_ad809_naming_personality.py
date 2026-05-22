"""AD-794 + AD-809: thread auto-name + personality resolution tests."""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from probos.threads import ChatThreadStore
from probos.threads.naming import resolve_personality, suggest_title


# ---------------- AD-794 ----------------


@pytest.mark.parametrize(
    "body, expected",
    [
        ("", "New thread"),
        ("   ", "New thread"),
        ("Hello", "Hello"),
        ("Hello world. Second sentence here.", "Hello world"),
        ("Quick question?", "Quick question"),
        ("...lots of leading dots", "lots of leading dots"),
        ("\nLine one\nLine two", "Line one"),
        (" multi    spaces   between  ", "multi spaces between"),
    ],
)
def test_suggest_title_heuristics(body, expected):
    assert suggest_title(body) == expected


def test_suggest_title_truncates_long_body():
    long_body = "Word " * 100  # 500 chars
    title = suggest_title(long_body)
    assert len(title) <= 61
    assert title.endswith("…")


def test_suggest_title_break_on_word_boundary():
    body = "A" * 30 + " " + "B" * 80
    title = suggest_title(body, max_len=40)
    assert " " in title or title.endswith("…")
    assert len(title) <= 41


# ---------------- AD-809 ----------------


def test_resolve_personality_returns_default_when_thread_none():
    assert resolve_personality(None, default="formal") == "formal"


def test_resolve_personality_returns_override(tmp_path):
    store = ChatThreadStore(tmp_path / "t.db")
    t = store.create_thread(
        title="x", participants=[], personality_override="playful"
    )
    assert resolve_personality(t, default="formal") == "playful"


def test_resolve_personality_falls_back_when_override_empty(tmp_path):
    store = ChatThreadStore(tmp_path / "t.db")
    t = store.create_thread(title="x", participants=[], personality_override="   ")
    assert resolve_personality(t, default="formal") == "formal"


def test_resolve_personality_no_override_uses_default(tmp_path):
    store = ChatThreadStore(tmp_path / "t.db")
    t = store.create_thread(title="x", participants=[])
    assert resolve_personality(t, default="formal") == "formal"


# ---------------- REST auto-name ----------------


@pytest.fixture
def client(tmp_path):
    from probos.routers import threads as threads_router
    from probos.routers.deps import get_runtime

    store = ChatThreadStore(tmp_path / "threads.db")
    runtime = SimpleNamespace(chat_thread_store=store)
    app = FastAPI()
    app.include_router(threads_router.router)
    app.dependency_overrides[get_runtime] = lambda: runtime
    return TestClient(app)


def test_rest_auto_name_after_first_message(client):
    tid = client.post(
        "/api/threads", json={"title": "untitled", "participants": []}
    ).json()["id"]
    client.post(
        f"/api/threads/{tid}/messages",
        json={
            "author_id": "captain",
            "role": "captain",
            "body": "Can you help me draft a Substack post about ProbOS?",
        },
    )
    r = client.post(f"/api/threads/{tid}/auto-name")
    assert r.status_code == 200
    title = r.json()["title"]
    assert title.lower().startswith("can you help me draft")


def test_rest_auto_name_409_when_no_messages(client):
    tid = client.post(
        "/api/threads", json={"title": "empty", "participants": []}
    ).json()["id"]
    r = client.post(f"/api/threads/{tid}/auto-name")
    assert r.status_code == 409


def test_rest_auto_name_404_missing_thread(client):
    r = client.post("/api/threads/missing/auto-name")
    assert r.status_code == 404
