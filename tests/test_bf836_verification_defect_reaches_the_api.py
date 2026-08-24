"""BF-836 (#1301): the crew-tasks API dropped ``verification_defect``.

BF-784 put the flag into both durable records so the audit trail could tell
"the verifier failed" from "the work was refused". The read path could not:
``_verdict_from_subtask`` projected only the original four fields, so the HXI
rendered a verification defect as ``rejected`` -- the exact conflation BF-777
introduced the field to prevent, now shown to the Captain rather than only to a
log reader.

Reproduced against the real router before the fix:

    ROUTER indexed_has_flag=True projected_has_flag=False

These drive the real router and the real store, not a mirror of the projection.
A test that rebuilt the dict would assert its own arithmetic.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from probos.routers.crew_tasks import _verdict_from_subtask, router
from probos.routers.deps import get_runtime
from probos.workforce import WorkItemStore


class _Attachments:
    def __init__(self) -> None:
        self._blobs: dict[str, bytes] = {}

    def put(self, blob: bytes) -> str:
        ref = hashlib.sha256(blob).hexdigest()
        self._blobs[ref] = blob
        return ref

    async def read(self, content_hash: str) -> bytes:
        return self._blobs[content_hash]


class _Runtime:
    def __init__(self, store: WorkItemStore, attachments: Any) -> None:
        self.work_item_store = store
        self.attachment_store = attachments


@pytest.fixture
async def store(tmp_path: Any) -> WorkItemStore:
    s = WorkItemStore(db_path=str(tmp_path / "crew.db"))
    await s.start()
    try:
        yield s
    finally:
        await s.stop()


def _client(store: WorkItemStore, attachments: Any) -> TestClient:
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_runtime] = lambda: _Runtime(store, attachments)
    return TestClient(app)


async def _tree_with_subtask(
    store: WorkItemStore, sub_extra: dict[str, Any],
) -> dict[str, Any]:
    """Build a real parent/child with a real provenance blob, and GET it."""
    parent = await store.create_work_item(title="Goal", work_type="task")
    child = await store.create_work_item(
        title="Sub", work_type="task", parent_id=parent.id, status="done",
    )
    sub = {
        "work_item_id": child.id,
        "accepted": False,
        "confidence": 0.1,
        "critique": "the verifier raised",
        "verifier_agent_id": "v1",
        **sub_extra,
    }
    attachments = _Attachments()
    ref = attachments.put(json.dumps({
        "parent_id": parent.id,
        "accepted_count": 0,
        "total_count": 1,
        "subtasks": [sub],
    }, sort_keys=True).encode("utf-8"))
    # The router reads the ref from `metadata["crew_synth"]["provenance_ref"]`
    # and only when the parent is `done` -- verdicts are null otherwise.
    await store.update_work_item(
        parent.id,
        status="done",
        metadata={**(parent.metadata or {}), "crew_synth": {"provenance_ref": ref}},
    )

    resp = _client(store, attachments).get(f"/api/crew-tasks/{parent.id}")
    assert resp.status_code == 200, resp.text
    verdict = resp.json()["children"][0]["verdict"]
    assert verdict is not None, (
        "the provenance never dereferenced, so this test would prove nothing "
        "about the projection"
    )
    return verdict


# ── the projection ────────────────────────────────────────────────


async def test_a_verification_defect_reaches_the_api(store: WorkItemStore) -> None:
    """The headline. Measured before the fix: present in storage, absent here."""
    verdict = await _tree_with_subtask(store, {"verification_defect": True})

    assert verdict["verification_defect"] is True
    # Still refused -- the flag says WHY, it does not make the work accepted.
    assert verdict["accepted"] is False


async def test_a_refusal_is_not_reported_as_a_defect(store: WorkItemStore) -> None:
    """The counter-case. Without it, always-True would pass the test above."""
    verdict = await _tree_with_subtask(store, {"verification_defect": False})

    assert verdict["verification_defect"] is False
    assert verdict["accepted"] is False


async def test_a_blob_written_before_bf784_cannot_say(
    store: WorkItemStore,
) -> None:
    """An older record has no such key, and `accepted=False` alone cannot
    establish whether the work was judged poor or never judged at all.

    ``None``, not ``False``: reporting it as a genuine refusal would assert
    something the record does not support. The UI renders this as
    "verification unavailable", not "rejected".
    """
    verdict = await _tree_with_subtask(store, {})

    assert verdict["verification_defect"] is None


# ── the projection function itself ────────────────────────────────


def test_a_malformed_flag_is_not_read_as_a_defect() -> None:
    """`bool("false")` is True.

    A previous fix in this repo turned a malformed value into a confident
    wrong bool exactly this way, so the projection tests the TYPE, not
    truthiness -- and a value it cannot read becomes ``None`` (unknown) rather
    than ``False`` (a positive claim that no defect occurred).
    """
    for bad in ("false", "no", 0, 1, "", [], "True", {}):
        out = _verdict_from_subtask({"verification_defect": bad})
        assert out["verification_defect"] is None, bad

    assert _verdict_from_subtask(
        {"verification_defect": True},
    )["verification_defect"] is True
    assert _verdict_from_subtask(
        {"verification_defect": False},
    )["verification_defect"] is False


def test_the_projection_carries_every_wire_field() -> None:
    """The frontend validates an EXACT key set, so a field added here without
    the matching TypeScript change breaks the panel. Pinning the set makes that
    coupling fail loudly rather than at runtime."""
    out = _verdict_from_subtask({})

    assert set(out) == {
        "accepted",
        "confidence",
        "critique",
        "verifier_agent_id",
        "verification_defect",
    }
