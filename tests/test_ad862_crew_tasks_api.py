"""AD-862: crew-collaboration surface API tests.

GET /api/crew-tasks/{parent_id} returns a parent WorkItem plus its children,
each with live persisted ``status`` (which drives HXI pulse/settle motion) and
per-subtask ``verdict``/``rounds`` attached ONLY post-completion via the AD-861
provenance blob deref (else ``null``). Uses a REAL WorkItemStore (BF-287: never
MagicMock a substrate store — its auto-attributes hide phantom-API bugs) and a
small fake attachment store returning a canned provenance blob in the real
AD-861 shape.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from probos.routers.crew_tasks import router
from probos.routers.deps import get_runtime
from probos.workforce import WorkItemStore


class _FakeAttachmentStore:
    """Minimal content-addressable read surface matching AttachmentStore.read."""

    def __init__(self) -> None:
        self._blobs: dict[str, bytes] = {}

    def put(self, blob: bytes) -> str:
        ref = hashlib.sha256(blob).hexdigest()
        self._blobs[ref] = blob
        return ref

    async def read(self, content_hash: str) -> bytes:
        if content_hash not in self._blobs:
            raise FileNotFoundError(content_hash)
        return self._blobs[content_hash]


class _FakeRuntime:
    def __init__(self, store: WorkItemStore | None, attachments: Any = None) -> None:
        self.work_item_store = store
        self.attachment_store = attachments


def _client_for(runtime: _FakeRuntime) -> TestClient:
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_runtime] = lambda: runtime
    return TestClient(app)


@pytest.fixture
async def store(tmp_path: Any) -> WorkItemStore:
    s = WorkItemStore(db_path=str(tmp_path / "crew.db"))
    await s.start()
    try:
        yield s
    finally:
        await s.stop()


def _provenance_blob(parent_id: str, subtasks: list[dict[str, Any]]) -> bytes:
    accepted = sum(1 for s in subtasks if s.get("accepted"))
    payload = {
        "parent_id": parent_id,
        "accepted_count": accepted,
        "total_count": len(subtasks),
        "subtasks": subtasks,
    }
    return json.dumps(payload, sort_keys=True).encode("utf-8")


async def test_get_crew_task_returns_parent_and_children_with_status(
    store: WorkItemStore,
) -> None:
    parent = await store.create_work_item(title="Crew goal", work_type="task")
    await store.create_work_item(
        title="Subtask A", work_type="task", parent_id=parent.id, status="in_progress",
    )
    await store.create_work_item(
        title="Subtask B", work_type="task", parent_id=parent.id, status="done",
    )
    client = _client_for(_FakeRuntime(store))

    resp = client.get(f"/api/crew-tasks/{parent.id}")

    assert resp.status_code == 200
    body = resp.json()
    assert body["parent"]["id"] == parent.id
    assert body["count"] == 2
    statuses = {c["title"]: c["status"] for c in body["children"]}
    assert statuses["Subtask A"] == "in_progress"
    assert statuses["Subtask B"] == "done"
    # No provenance ref on the parent -> verdict/rounds are null on every child.
    for child in body["children"]:
        assert child["verdict"] is None
        assert child["rounds"] is None


async def test_get_crew_task_missing_parent_returns_404(store: WorkItemStore) -> None:
    client = _client_for(_FakeRuntime(store))

    resp = client.get("/api/crew-tasks/does-not-exist")

    assert resp.status_code == 404


def test_get_crew_task_without_store_returns_503() -> None:
    client = _client_for(_FakeRuntime(None))

    resp = client.get("/api/crew-tasks/whatever")

    assert resp.status_code == 503


async def test_in_progress_parent_yields_null_verdict_rounds(
    store: WorkItemStore,
) -> None:
    # Parent NOT done -> provenance is never dereferenced even if a ref exists.
    parent = await store.create_work_item(
        title="Crew goal", work_type="task", status="in_progress",
        metadata={"crew_synth": {"provenance_ref": "deadbeef"}},
    )
    await store.create_work_item(
        title="Subtask A", work_type="task", parent_id=parent.id, status="in_progress",
    )
    client = _client_for(_FakeRuntime(store, _FakeAttachmentStore()))

    resp = client.get(f"/api/crew-tasks/{parent.id}")

    assert resp.status_code == 200
    body = resp.json()
    child = body["children"][0]
    assert child["verdict"] is None
    assert child["rounds"] is None


async def test_completed_parent_attaches_verdict_and_rounds(
    store: WorkItemStore,
) -> None:
    parent = await store.create_work_item(title="Crew goal", work_type="task")
    child_a = await store.create_work_item(
        title="Subtask A", work_type="task", parent_id=parent.id, status="done",
    )
    child_b = await store.create_work_item(
        title="Subtask B", work_type="task", parent_id=parent.id, status="done",
    )
    attachments = _FakeAttachmentStore()
    blob = _provenance_blob(
        parent.id,
        [
            {
                "work_item_id": child_a.id,
                "spec_id": "spec-a",
                "producer_agent_id": "agent-prod-a",
                "verifier_agent_id": "agent-verify-a",
                "accepted": True,
                "confidence": 0.91,
                "status": "done",
                "rounds": 2,
                "critique": "Looks complete.",
            },
            {
                "work_item_id": child_b.id,
                "spec_id": "spec-b",
                "producer_agent_id": "agent-prod-b",
                "verifier_agent_id": "agent-verify-b",
                "accepted": False,
                "confidence": 0.4,
                "status": "done",
                "rounds": 3,
                "critique": "Missing edge case.",
            },
        ],
    )
    ref = attachments.put(blob)
    # Mark the parent done with the provenance ref (AD-861 completion shape).
    await store.update_work_item(
        parent.id, status="done",
        metadata={"crew_synth": {"provenance_ref": ref, "completed": True}},
    )
    client = _client_for(_FakeRuntime(store, attachments))

    resp = client.get(f"/api/crew-tasks/{parent.id}")

    assert resp.status_code == 200
    body = resp.json()
    by_title = {c["title"]: c for c in body["children"]}
    va = by_title["Subtask A"]
    assert va["verdict"]["accepted"] is True
    assert va["verdict"]["confidence"] == 0.91
    assert va["verdict"]["critique"] == "Looks complete."
    assert va["verdict"]["verifier_agent_id"] == "agent-verify-a"
    assert va["rounds"] == 2
    vb = by_title["Subtask B"]
    assert vb["verdict"]["accepted"] is False
    assert vb["rounds"] == 3


async def test_completed_parent_missing_blob_degrades_to_null(
    store: WorkItemStore,
) -> None:
    # Parent done with a ref, but the blob is absent from the store ->
    # honest-degrade to null, no crash.
    parent = await store.create_work_item(title="Crew goal", work_type="task")
    await store.create_work_item(
        title="Subtask A", work_type="task", parent_id=parent.id, status="done",
    )
    await store.update_work_item(
        parent.id, status="done",
        metadata={"crew_synth": {"provenance_ref": "missing-ref"}},
    )
    client = _client_for(_FakeRuntime(store, _FakeAttachmentStore()))

    resp = client.get(f"/api/crew-tasks/{parent.id}")

    assert resp.status_code == 200
    child = resp.json()["children"][0]
    assert child["verdict"] is None
    assert child["rounds"] is None
