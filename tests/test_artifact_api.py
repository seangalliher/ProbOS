"""AD-797 (Wave 197): tests for artifacts router /content + project-pinned merge."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from probos.artifacts import ArtifactStore
from probos.routers import artifacts as artifacts_router
from probos.routers.deps import get_runtime
from probos.threads import ChatThreadStore, ProjectStore


class _FakeAttachmentStore:
    """Async ``read``/``exists`` matching AttachmentStore Protocol."""

    def __init__(self) -> None:
        self._blobs: dict[str, bytes] = {}

    async def write(
        self, content_hash: str, blob: bytes, mime: str,
        *, origin: str = "chat_attachment",
    ) -> Path:
        self._blobs[content_hash] = blob
        return Path("/fake") / content_hash

    async def read(self, content_hash: str) -> bytes:
        if content_hash not in self._blobs:
            raise FileNotFoundError(content_hash)
        return self._blobs[content_hash]

    async def exists(self, content_hash: str) -> bool:
        return content_hash in self._blobs


class _FakeRuntime:
    def __init__(self, tmp_path: Path) -> None:
        self.artifact_store = ArtifactStore(tmp_path / "artifacts.db")
        self.chat_thread_store = ChatThreadStore(db_path=tmp_path / "threads.db")
        self.project_store = ProjectStore(db_path=tmp_path / "threads.db")
        self.attachment_store = _FakeAttachmentStore()


@pytest.fixture()
def runtime(tmp_path: Path) -> _FakeRuntime:
    return _FakeRuntime(tmp_path)


@pytest.fixture()
def client(runtime: _FakeRuntime) -> TestClient:
    app = FastAPI()
    app.include_router(artifacts_router.router)
    app.dependency_overrides[get_runtime] = lambda: runtime
    return TestClient(app)


def _seed_artifact(
    runtime: _FakeRuntime, *, thread_id: str, name: str, body: bytes,
    mime: str = "text/markdown",
) -> tuple[str, str]:
    """Write to AttachmentStore + ArtifactStore. Returns (artifact_id, hash)."""
    h = hashlib.sha256(body).hexdigest()
    import asyncio
    asyncio.run(runtime.attachment_store.write(h, body, mime, origin="agent_artifact"))
    art = runtime.artifact_store.add_version(
        thread_id=thread_id, name=name, content_hash=h, mime=mime,
        size_bytes=len(body), created_by="agent",
    )
    return art.id, h


def test_get_content_endpoint_returns_raw_bytes_and_mime(
    client: TestClient, runtime: _FakeRuntime,
) -> None:
    body = b"# Hello\n\nWorld\n"
    art_id, _h = _seed_artifact(runtime, thread_id="t1", name="x.md", body=body)
    res = client.get(f"/api/artifacts/{art_id}/content")
    assert res.status_code == 200
    assert res.content == body
    assert res.headers["content-type"].startswith("text/markdown")


def test_get_content_404_when_artifact_missing(client: TestClient) -> None:
    res = client.get("/api/artifacts/nope/content")
    assert res.status_code == 404
    assert res.json()["detail"] == "artifact_not_found"


def test_get_content_404_when_blob_missing(
    client: TestClient, runtime: _FakeRuntime,
) -> None:
    # Insert metadata row without backing bytes (orphan).
    art = runtime.artifact_store.add_version(
        thread_id="t1", name="orphan.md", content_hash="nohash",
        mime="text/markdown", size_bytes=0, created_by="agent",
    )
    res = client.get(f"/api/artifacts/{art.id}/content")
    assert res.status_code == 404
    assert res.json()["detail"] == "content_missing"


def test_list_thread_includes_project_pinned(
    client: TestClient, runtime: _FakeRuntime,
) -> None:
    # Project P, with two threads. Pin an artifact created in T1 to P;
    # query T2 (in same project) — pinned row must appear.
    project = runtime.project_store.create_project(name="P1")
    t1 = runtime.chat_thread_store.create_thread(
        title="T1", participants=["a1"], project_id=project.id,
    )
    t2 = runtime.chat_thread_store.create_thread(
        title="T2", participants=["a1"], project_id=project.id,
    )
    body = b"shared content\n"
    _, shared_hash = _seed_artifact(
        runtime, thread_id=t1.id, name="shared.md", body=body,
    )
    runtime.project_store.pin_attachment(project.id, shared_hash)

    # T2 has no native artifacts; pinned merge should produce one row.
    res = client.get(f"/api/artifacts/thread/{t2.id}")
    assert res.status_code == 200
    payload = res.json()
    assert payload["thread_id"] == t2.id
    assert len(payload["artifacts"]) == 1
    a = payload["artifacts"][0]
    assert a["content_hash"] == shared_hash
    assert a["_pinned_from_project"] is True


def test_list_thread_native_wins_on_collision(
    client: TestClient, runtime: _FakeRuntime,
) -> None:
    project = runtime.project_store.create_project(name="P2")
    t1 = runtime.chat_thread_store.create_thread(
        title="T1", participants=["a1"], project_id=project.id,
    )
    body = b"native and pinned\n"
    _, shared_hash = _seed_artifact(
        runtime, thread_id=t1.id, name="dup.md", body=body,
    )
    runtime.project_store.pin_attachment(project.id, shared_hash)

    res = client.get(f"/api/artifacts/thread/{t1.id}")
    payload = res.json()
    # Native wins — only one row, marked not-from-project.
    assert len(payload["artifacts"]) == 1
    assert payload["artifacts"][0]["_pinned_from_project"] is False


def test_list_thread_skips_pinned_with_no_artifact_row(
    client: TestClient, runtime: _FakeRuntime,
) -> None:
    project = runtime.project_store.create_project(name="P3")
    t1 = runtime.chat_thread_store.create_thread(
        title="T1", participants=["a1"], project_id=project.id,
    )
    # Pin a SHA that has no Artifact row (raw upload, not extracted).
    runtime.project_store.pin_attachment(project.id, "sha-no-artifact-row")

    res = client.get(f"/api/artifacts/thread/{t1.id}")
    payload = res.json()
    assert payload["artifacts"] == []  # skipped silently
