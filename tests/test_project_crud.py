"""AD-793 (Wave 196): pytest for Project CRUD + REST endpoints."""

from __future__ import annotations

import asyncio
import tempfile
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


def test_create_project_happy_path(client: TestClient) -> None:
    res = client.post("/api/projects", json={"name": "ProbOS Development"})
    assert res.status_code == 200
    body = res.json()
    # Response is the project dict DIRECTLY (no {"project": ...} wrapper).
    assert "id" in body
    assert body["name"] == "ProbOS Development"
    assert body["description"] == ""
    assert body["pinned_attachment_ids"] == []
    assert body["archived"] is False
    # last_active_at == created_at at creation.
    assert body["last_active_at"] == body["created_at"]


def test_get_project_missing_returns_404(client: TestClient) -> None:
    res = client.get("/api/projects/does-not-exist")
    assert res.status_code == 404


def test_patch_project_name_only(client: TestClient) -> None:
    created = client.post(
        "/api/projects",
        json={"name": "Original", "description": "Keep me"},
    ).json()
    res = client.patch(
        f"/api/projects/{created['id']}",
        json={"name": "Renamed"},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["name"] == "Renamed"
    # description untouched.
    assert body["description"] == "Keep me"


def test_delete_project_unparent_default(
    client: TestClient, runtime: _FakeRuntime
) -> None:
    project = client.post(
        "/api/projects", json={"name": "P1"}
    ).json()
    # Create a thread inside the project.
    thread = runtime.chat_thread_store.create_thread(
        title="T1", participants=["a1"], project_id=project["id"]
    )
    # Default cascade=false → unparent.
    res = client.delete(f"/api/projects/{project['id']}")
    assert res.status_code == 200
    body = res.json()
    assert body == {
        "deleted": True,
        "affected_threads": 1,
        "cascade": False,
    }
    # Thread still exists, project_id is NULL.
    surviving = runtime.chat_thread_store.get_thread(thread.id)
    assert surviving is not None
    assert surviving.project_id is None


def test_delete_project_cascade_removes_threads_and_messages(
    client: TestClient, runtime: _FakeRuntime
) -> None:
    project = client.post(
        "/api/projects", json={"name": "P2"}
    ).json()
    thread = runtime.chat_thread_store.create_thread(
        title="T2", participants=["a1"], project_id=project["id"]
    )
    runtime.chat_thread_store.append_message(
        thread.id, author_id="a1", role="agent", body="hello"
    )
    res = client.delete(
        f"/api/projects/{project['id']}?cascade=true"
    )
    assert res.status_code == 200
    body = res.json()
    assert body["deleted"] is True
    assert body["cascade"] is True
    assert body["affected_threads"] == 1
    # Thread is gone.
    assert runtime.chat_thread_store.get_thread(thread.id) is None
    # Messages are gone.
    assert runtime.chat_thread_store.list_messages(thread.id) == []


def test_list_projects_orders_by_last_active(
    client: TestClient, runtime: _FakeRuntime
) -> None:
    p1 = client.post("/api/projects", json={"name": "Oldest"}).json()
    p2 = client.post("/api/projects", json={"name": "Middle"}).json()
    p3 = client.post("/api/projects", json={"name": "Newest"}).json()
    # Touch p1 last so it becomes most-active.
    runtime.project_store.touch(p2["id"])
    runtime.project_store.touch(p3["id"])
    runtime.project_store.touch(p1["id"])
    body = client.get("/api/projects").json()
    names = [p["name"] for p in body["projects"]]
    # Most recent activity first.
    assert names[0] == "Oldest"


def test_create_project_with_description_and_pins(
    client: TestClient,
) -> None:
    res = client.post(
        "/api/projects",
        json={
            "name": "Newsletter",
            "description": "LinkedIn newsletter drafts",
            "pinned_attachment_ids": ["sha1", "sha2"],
        },
    )
    assert res.status_code == 200
    body = res.json()
    assert body["description"] == "LinkedIn newsletter drafts"
    assert body["pinned_attachment_ids"] == ["sha1", "sha2"]


def test_patch_project_archived(client: TestClient) -> None:
    created = client.post("/api/projects", json={"name": "X"}).json()
    res = client.patch(
        f"/api/projects/{created['id']}", json={"archived": True}
    )
    assert res.status_code == 200
    assert res.json()["archived"] is True
    # By default list excludes archived.
    body = client.get("/api/projects").json()
    assert all(p["id"] != created["id"] for p in body["projects"])
    # include_archived=true surfaces it.
    body2 = client.get("/api/projects?include_archived=true").json()
    assert any(p["id"] == created["id"] for p in body2["projects"])


def test_patch_missing_project_returns_404(client: TestClient) -> None:
    res = client.patch(
        "/api/projects/does-not-exist", json={"name": "x"}
    )
    assert res.status_code == 404


def test_delete_missing_project_returns_404(client: TestClient) -> None:
    res = client.delete("/api/projects/does-not-exist")
    assert res.status_code == 404


def test_create_project_validation_rejects_empty_name(
    client: TestClient,
) -> None:
    res = client.post("/api/projects", json={"name": ""})
    # Pydantic validation → 422 for min_length violations.
    assert res.status_code == 422
