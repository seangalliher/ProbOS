"""AD-793 (Wave 196): pytest for Project pin/unpin endpoints."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from probos.routers import projects as projects_router
from probos.routers.deps import get_runtime
from probos.threads import ChatThreadStore, ProjectStore


class _FakeAttachmentStore:
    """Async exists() — matches AttachmentStore protocol from
    ``attachments/store.py:60``."""

    def __init__(self, known: set[str]) -> None:
        self._known = known

    async def exists(self, sha: str) -> bool:
        return sha in self._known


class _FakeRuntime:
    def __init__(self, db_path: Path, known_shas: set[str]) -> None:
        self.chat_thread_store = ChatThreadStore(db_path=db_path)
        self.project_store = ProjectStore(db_path=db_path)
        self._attachment_store = _FakeAttachmentStore(known_shas)
        # AD-793: stub the lazy per-runtime cache the cross-router
        # _get_attachment_store helper consults — avoids real filesystem
        # init + lets us inject known/missing SHAs deterministically.
        from probos.routers.chat import _ATTACHMENT_STORE_CACHE
        _ATTACHMENT_STORE_CACHE[id(self)] = self._attachment_store

        # Stub a minimal config attribute so any future code-path that
        # walks runtime.config doesn't trip — not strictly required since
        # the cache hits first, but defensive.
        class _Cfg:
            class attachments:
                attachments_dir = str(db_path.parent / "attachments")
        self.config = _Cfg()


@pytest.fixture()
def runtime(tmp_path: Path) -> _FakeRuntime:
    # Pre-known SHA for the happy-path test.
    return _FakeRuntime(tmp_path / "chat_threads.db", {"sha-known"})


@pytest.fixture()
def client(runtime: _FakeRuntime) -> TestClient:
    app = FastAPI()
    app.include_router(projects_router.router)
    app.dependency_overrides[get_runtime] = lambda: runtime
    return TestClient(app)


def test_pin_attachment_validates_sha_exists(
    client: TestClient,
) -> None:
    project = client.post(
        "/api/projects", json={"name": "P1"}
    ).json()
    # SHA not in the store → 400 (not 404 — the request was valid).
    res = client.post(
        f"/api/projects/{project['id']}/pin",
        json={"attachment_id": "sha-unknown"},
    )
    assert res.status_code == 400
    assert "not found" in res.json().get("detail", "").lower()


def test_pin_unpin_idempotent(client: TestClient) -> None:
    project = client.post(
        "/api/projects", json={"name": "P2"}
    ).json()
    pid = project["id"]
    # First pin.
    r1 = client.post(
        f"/api/projects/{pid}/pin",
        json={"attachment_id": "sha-known"},
    )
    assert r1.status_code == 200
    assert r1.json()["pinned_attachment_ids"] == ["sha-known"]
    # Second pin (same SHA) — no duplicate.
    r2 = client.post(
        f"/api/projects/{pid}/pin",
        json={"attachment_id": "sha-known"},
    )
    assert r2.status_code == 200
    assert r2.json()["pinned_attachment_ids"] == ["sha-known"]
    # Unpin.
    r3 = client.post(
        f"/api/projects/{pid}/unpin",
        json={"attachment_id": "sha-known"},
    )
    assert r3.status_code == 200
    assert r3.json()["pinned_attachment_ids"] == []
    # Unpin again (already gone) — still 200, still empty list.
    r4 = client.post(
        f"/api/projects/{pid}/unpin",
        json={"attachment_id": "sha-known"},
    )
    assert r4.status_code == 200
    assert r4.json()["pinned_attachment_ids"] == []


def test_pin_missing_project_returns_404(client: TestClient) -> None:
    res = client.post(
        "/api/projects/does-not-exist/pin",
        json={"attachment_id": "sha-known"},
    )
    assert res.status_code == 404
