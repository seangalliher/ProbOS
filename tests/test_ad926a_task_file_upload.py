"""AD-926a: task-level multi-file input upload (the WRITE/population path).

``POST /api/work-items/{work_item_id}/inputs`` is the missing population path
for the AD-926 Inputs convention: it validates + stores one OR MORE uploaded
files via the SHARED chat uploader (``_validate_and_store_attachment``) and
appends ``{content_hash, mime, filename}`` refs to
``WorkItem.metadata["input_attachments"]`` via a single read-merge-write. The
files then surface as the task room's Inputs through the existing AD-926
``GET /api/threads/{id}/inputs`` endpoint.

BF-287 discipline (no MagicMock at the substrate boundary): every store is
**real** — a real :class:`WorkItemStore`, a real :class:`FilesystemAttachmentStore`,
a real :class:`ChatThreadStore`, and a real :class:`SystemConfig` (so the
validate gates read the real ``config.attachments`` allowlist / size cap). The
endpoint is invoked by awaiting :func:`attach_work_item_inputs` directly with a
``SimpleNamespace`` runtime stub; the chat uploader's per-runtime store cache
is seeded so the write lands in the test store (the AD-916 e2e precedent).
"""

from __future__ import annotations

import hashlib
import io
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from starlette.datastructures import Headers, UploadFile

from probos.attachments.filesystem_store import FilesystemAttachmentStore
from probos.config import SystemConfig
from probos.routers import chat as chat_router
from probos.routers.threads import list_thread_inputs
from probos.routers.workforce import attach_work_item_inputs
from probos.threads import ChatThreadStore
from probos.workforce import WorkItemStore

# Happy-path inputs: text/plain + .txt filename + strict-UTF-8 bytes pass the
# whole defense-in-depth chain (mime allowlist + magic-byte + extension gate).
_TXT_A = "alpha context\n".encode("utf-8")
_TXT_B = "bravo context, a bit longer\n".encode("utf-8")
# A blob that is NOT a valid PNG but is declared image/png — rejected at the
# magic-byte validator (gate 5), used for the per-file honest-degrade case.
_FAKE_PNG = b"this is plainly not a png image"


def _sha(blob: bytes) -> str:
    return hashlib.sha256(blob).hexdigest()


def _upload(name: str, blob: bytes, mime: str) -> UploadFile:
    """Build a Starlette UploadFile from in-memory bytes (no temp file)."""
    return UploadFile(
        file=io.BytesIO(blob),
        filename=name,
        headers=Headers({"content-type": mime}),
    )


# ---------------------------------------------------------------------------
# Real-but-isolated substrate fixtures (BF-287)
# ---------------------------------------------------------------------------


@pytest.fixture
async def wi_store(tmp_path):
    s = WorkItemStore(
        db_path=str(tmp_path / "crew.db"),
        emit_event=lambda *a, **k: None,
        tick_interval=1000,
    )
    await s.start()
    try:
        yield s
    finally:
        await s.stop()


@pytest.fixture
def chat_store(tmp_path) -> ChatThreadStore:
    return ChatThreadStore(tmp_path / "chat_threads.db")


@pytest.fixture
def attach_store(tmp_path) -> FilesystemAttachmentStore:
    return FilesystemAttachmentStore(tmp_path / "attach")


@pytest.fixture
def runtime(wi_store, attach_store, chat_store):
    """SimpleNamespace runtime with REAL stores + REAL config.

    Seeds the chat uploader's per-runtime store cache so the write lands in the
    test ``FilesystemAttachmentStore``; the cache key is popped on teardown so
    the module leaves no global state behind (no test pollution).
    """
    rt = SimpleNamespace(
        work_item_store=wi_store,
        attachment_store=attach_store,
        chat_thread_store=chat_store,
        config=SystemConfig(),
    )
    chat_router._ATTACHMENT_STORE_CACHE[id(rt)] = attach_store
    try:
        yield rt
    finally:
        chat_router._ATTACHMENT_STORE_CACHE.pop(id(rt), None)


# ---------------------------------------------------------------------------
# 1. two files attach -> two refs appended, survive a read-back
# ---------------------------------------------------------------------------


async def test_two_files_attach_appends_two_refs(runtime, wi_store):
    wi = await wi_store.create_work_item(title="parent", work_type="task")
    out = await attach_work_item_inputs(
        wi.id,
        files=[_upload("a.txt", _TXT_A, "text/plain"), _upload("b.txt", _TXT_B, "text/plain")],
        runtime=runtime,
    )
    assert out["work_item_id"] == wi.id
    assert out["skipped"] == []
    assert {i["content_hash"] for i in out["inputs"]} == {_sha(_TXT_A), _sha(_TXT_B)}

    # Survives a fresh read-back from the real store with the correct shape.
    reloaded = await wi_store.get_work_item(wi.id)
    refs = reloaded.metadata["input_attachments"]
    assert len(refs) == 2
    by_hash = {r["content_hash"]: r for r in refs}
    assert by_hash[_sha(_TXT_A)] == {
        "content_hash": _sha(_TXT_A), "mime": "text/plain", "filename": "a.txt",
    }
    assert by_hash[_sha(_TXT_B)]["filename"] == "b.txt"


# ---------------------------------------------------------------------------
# 2. bytes land in the content-addressable store under their sha256
# ---------------------------------------------------------------------------


async def test_bytes_land_in_store_by_sha256(runtime, wi_store, attach_store):
    wi = await wi_store.create_work_item(title="parent", work_type="task")
    await attach_work_item_inputs(
        wi.id,
        files=[_upload("a.txt", _TXT_A, "text/plain"), _upload("b.txt", _TXT_B, "text/plain")],
        runtime=runtime,
    )
    assert await attach_store.read(_sha(_TXT_A)) == _TXT_A
    assert await attach_store.read(_sha(_TXT_B)) == _TXT_B


# ---------------------------------------------------------------------------
# 3. second upload APPENDS — sentinel metadata key + pre-existing ref survive
# ---------------------------------------------------------------------------


async def test_second_upload_appends_preserving_other_metadata(runtime, wi_store):
    pre_ref = {"content_hash": _sha(b"preexisting"), "mime": "text/plain", "filename": "old.txt"}
    wi = await wi_store.create_work_item(
        title="parent",
        work_type="task",
        metadata={"owner": "captain", "input_attachments": [pre_ref]},
    )
    out = await attach_work_item_inputs(
        wi.id,
        files=[_upload("new.txt", _TXT_A, "text/plain")],
        runtime=runtime,
    )
    # The new ref AND the pre-existing ref are both present (3 inputs counted
    # via the read-back metadata: pre + new).
    reloaded = await wi_store.get_work_item(wi.id)
    meta = reloaded.metadata
    # The sentinel non-input key is preserved (REPLACE-not-merge guard).
    assert meta["owner"] == "captain"
    hashes = [r["content_hash"] for r in meta["input_attachments"]]
    assert pre_ref["content_hash"] in hashes  # pre-existing survives
    assert _sha(_TXT_A) in hashes  # new ref appended
    assert len(hashes) == 2
    assert {i["content_hash"] for i in out["inputs"]} == set(hashes)


# ---------------------------------------------------------------------------
# 4. duplicate content_hash within one request -> exactly one ref (idempotent)
# ---------------------------------------------------------------------------


async def test_duplicate_within_request_dedupes_to_one(runtime, wi_store):
    wi = await wi_store.create_work_item(title="parent", work_type="task")
    out = await attach_work_item_inputs(
        wi.id,
        # Two distinct UploadFile objects wrapping the SAME bytes -> same sha256.
        files=[_upload("a.txt", _TXT_A, "text/plain"), _upload("a-copy.txt", _TXT_A, "text/plain")],
        runtime=runtime,
    )
    assert [i["content_hash"] for i in out["inputs"]] == [_sha(_TXT_A)]
    reloaded = await wi_store.get_work_item(wi.id)
    assert len(reloaded.metadata["input_attachments"]) == 1


# ---------------------------------------------------------------------------
# 5. mixed good + bad -> bad file skipped per file, good file still attaches
# ---------------------------------------------------------------------------


async def test_mixed_good_and_bad_skips_per_file(runtime, wi_store):
    wi = await wi_store.create_work_item(title="parent", work_type="task")
    out = await attach_work_item_inputs(
        wi.id,
        files=[
            _upload("good.txt", _TXT_A, "text/plain"),
            _upload("evil.png", _FAKE_PNG, "image/png"),  # non-image bytes -> magic mismatch
        ],
        runtime=runtime,
    )
    assert [i["content_hash"] for i in out["inputs"]] == [_sha(_TXT_A)]
    assert len(out["skipped"]) == 1
    assert out["skipped"][0]["filename"] == "evil.png"
    # The good file's ref still landed in the work item.
    reloaded = await wi_store.get_work_item(wi.id)
    assert [r["content_hash"] for r in reloaded.metadata["input_attachments"]] == [_sha(_TXT_A)]


# ---------------------------------------------------------------------------
# 6. disallowed MIME -> skipped at the allowlist gate, no refs written
# ---------------------------------------------------------------------------


async def test_disallowed_mime_skipped(runtime, wi_store):
    wi = await wi_store.create_work_item(title="parent", work_type="task")
    out = await attach_work_item_inputs(
        wi.id,
        files=[_upload("archive.zip", b"PK\x03\x04stuff", "application/zip")],
        runtime=runtime,
    )
    assert out["inputs"] == []
    assert len(out["skipped"]) == 1
    assert out["skipped"][0]["filename"] == "archive.zip"
    reloaded = await wi_store.get_work_item(wi.id)
    assert "input_attachments" not in (reloaded.metadata or {})


# ---------------------------------------------------------------------------
# 7. unknown work item -> 404
# ---------------------------------------------------------------------------


async def test_unknown_work_item_404(runtime):
    with pytest.raises(HTTPException) as exc:
        await attach_work_item_inputs(
            "does-not-exist",
            files=[_upload("a.txt", _TXT_A, "text/plain")],
            runtime=runtime,
        )
    assert exc.value.status_code == 404


# ---------------------------------------------------------------------------
# 8. no work_item_store -> 503
# ---------------------------------------------------------------------------


async def test_no_work_item_store_503():
    rt = SimpleNamespace(work_item_store=None, config=SystemConfig())
    with pytest.raises(HTTPException) as exc:
        await attach_work_item_inputs(
            "wi-1",
            files=[_upload("a.txt", _TXT_A, "text/plain")],
            runtime=rt,
        )
    assert exc.value.status_code == 503


# ---------------------------------------------------------------------------
# 9. empty files list -> no-op (no refs written, returns current inputs)
# ---------------------------------------------------------------------------


async def test_empty_files_list_noop(runtime, wi_store):
    wi = await wi_store.create_work_item(title="parent", work_type="task")
    out = await attach_work_item_inputs(
        wi.id, files=[], runtime=runtime,
    )
    assert out["inputs"] == []
    assert out["skipped"] == []
    reloaded = await wi_store.get_work_item(wi.id)
    assert "input_attachments" not in (reloaded.metadata or {})


# ---------------------------------------------------------------------------
# 10. integration: attached files surface via the AD-926 read endpoint
# ---------------------------------------------------------------------------


async def test_integration_surfaces_via_read_endpoint(runtime, wi_store, chat_store):
    wi = await wi_store.create_work_item(title="parent", work_type="task")
    thread = chat_store.create_thread(
        title="room", participants=["bones-1", "forge-1"], task_id=wi.id,
    )
    await attach_work_item_inputs(
        wi.id,
        files=[_upload("a.txt", _TXT_A, "text/plain"), _upload("b.txt", _TXT_B, "text/plain")],
        runtime=runtime,
    )
    read = await list_thread_inputs(thread.id, runtime=runtime)
    assert read["task_id"] == wi.id
    assert {i["content_hash"] for i in read["inputs"]} == {_sha(_TXT_A), _sha(_TXT_B)}
    assert all(i["source"] == "task" for i in read["inputs"])
