"""AD-793 (Wave 196): pytest for project.last_active_at touch on message
append via the router endpoint."""

from __future__ import annotations

import time
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from probos.routers import projects as projects_router
from probos.routers import threads as threads_router
from probos.routers.deps import get_runtime
from probos.threads import ChatThreadStore, ProjectStore


class _FakeRuntime:
    def __init__(self, db_path: Path) -> None:
        self.chat_thread_store = ChatThreadStore(db_path=db_path)
        self.project_store = ProjectStore(db_path=db_path)


@pytest.fixture()
def runtime(tmp_path: Path) -> _FakeRuntime:
    return _FakeRuntime(tmp_path / "chat_threads.db")


@pytest.fixture()
def client(runtime: _FakeRuntime) -> TestClient:
    app = FastAPI()
    app.include_router(projects_router.router)
    app.include_router(threads_router.router)
    app.dependency_overrides[get_runtime] = lambda: runtime
    return TestClient(app)


def test_message_append_in_project_thread_bumps_last_active(
    client: TestClient, runtime: _FakeRuntime
) -> None:
    project = client.post(
        "/api/projects", json={"name": "Touch Test"}
    ).json()
    pid = project["id"]
    initial_active = project["last_active_at"]

    # Create a thread inside the project.
    thread = runtime.chat_thread_store.create_thread(
        title="t", participants=["a1"], project_id=pid,
    )

    # Sleep a moment so the touch timestamp is monotonically greater.
    time.sleep(0.02)

    # Append via the ROUTER (exercises the touch call-site at the
    # router layer, not via ChatThreadStore.append_message directly).
    res = client.post(
        f"/api/threads/{thread.id}/messages",
        json={"author_id": "a1", "role": "captain", "body": "hi"},
    )
    assert res.status_code == 200

    # Re-fetch project; last_active_at must have advanced.
    refreshed = client.get(f"/api/projects/{pid}").json()
    assert refreshed["last_active_at"] > initial_active


def test_message_append_in_unparented_thread_does_not_touch_any_project(
    client: TestClient, runtime: _FakeRuntime
) -> None:
    project = client.post(
        "/api/projects", json={"name": "Untouched"}
    ).json()
    initial_active = project["last_active_at"]

    # Thread NOT in any project.
    thread = runtime.chat_thread_store.create_thread(
        title="loose", participants=["a1"], project_id=None,
    )
    time.sleep(0.02)
    res = client.post(
        f"/api/threads/{thread.id}/messages",
        json={"author_id": "a1", "role": "captain", "body": "hi"},
    )
    assert res.status_code == 200

    refreshed = client.get(f"/api/projects/{project['id']}").json()
    # last_active_at unchanged.
    assert refreshed["last_active_at"] == initial_active
