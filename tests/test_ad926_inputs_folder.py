"""AD-926: read-only Inputs folder for a task workspace room.

``GET /api/threads/{thread_id}/inputs`` surfaces an honest union of two
task-scoped file sources, de-duplicated by ``content_hash``:

  1. the authoritative ``WorkItem.metadata["input_attachments"]`` convention
     (``source="task"`` — population deferred to AD-926a), and
  2. the real-today AD-916 message attachments carried on the room's messages
     (``source="message"``).

BF-287 discipline (no MagicMock at the substrate boundary): every store is
**real** — a real :class:`ChatThreadStore`, a real :class:`WorkItemStore`, and
a real :class:`FilesystemAttachmentStore` rooted under ``tmp_path``. The
endpoint is invoked by awaiting :func:`list_thread_inputs` directly with a
``SimpleNamespace`` runtime stub (the ``Depends`` default only fires under the
app), which avoids a full ``create_app`` boot.
"""

from __future__ import annotations

import hashlib
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from probos.attachments.filesystem_store import FilesystemAttachmentStore
from probos.routers.threads import list_thread_inputs
from probos.threads import ChatThreadStore
from probos.workforce import WorkItemStore

# Distinct blobs — sizes differ so the size-enrichment assertions are exact.
_BLOB_A = b"input-A-bytes"
_BLOB_B = b"input-B-bytes-which-is-longer"
_BLOB_C = b"message-only-C-blob"


def _sha(blob: bytes) -> str:
    return hashlib.sha256(blob).hexdigest()


def _runtime(chat_store, wi_store, attach_store) -> SimpleNamespace:
    """Runtime stub mirroring the production read paths.

    ``getattr(runtime, "work_item_store"/"attachment_store", None)`` reads a
    ``None`` attribute identically to an absent one, so passing ``None`` here
    exercises the honest-degrade branches.
    """
    return SimpleNamespace(
        chat_thread_store=chat_store,
        work_item_store=wi_store,
        attachment_store=attach_store,
    )


# ---------------------------------------------------------------------------
# Real-but-isolated substrate fixtures (BF-287)
# ---------------------------------------------------------------------------


@pytest.fixture
async def wi_store(tmp_path):
    """Real WorkItemStore (emit hook is a no-op lambda, not a mock)."""
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
async def attach_store(tmp_path) -> FilesystemAttachmentStore:
    """Real content-addressable store seeded with A/B/C by their real sha256."""
    store = FilesystemAttachmentStore(tmp_path / "attach")
    await store.write(_sha(_BLOB_A), _BLOB_A, "image/png")
    await store.write(_sha(_BLOB_B), _BLOB_B, "text/plain")
    await store.write(_sha(_BLOB_C), _BLOB_C, "text/plain")
    return store


# ---------------------------------------------------------------------------
# 1. work-item inputs (authoritative convention)
# ---------------------------------------------------------------------------


async def test_work_item_inputs_authoritative(wi_store, chat_store, attach_store):
    sha = _sha(_BLOB_A)
    parent = await wi_store.create_work_item(
        title="parent",
        description="p",
        work_type="task",
        metadata={
            "input_attachments": [
                {"content_hash": sha, "mime": "image/png", "filename": "diagram.png"}
            ]
        },
    )
    thread = chat_store.create_thread(
        title="room", participants=["bones-1", "forge-1"], task_id=parent.id
    )
    out = await list_thread_inputs(
        thread.id, runtime=_runtime(chat_store, wi_store, attach_store)
    )
    assert out["task_id"] == parent.id
    assert out["inputs"] == [
        {
            "content_hash": sha,
            "mime": "image/png",
            "filename": "diagram.png",
            "size": len(_BLOB_A),
            "source": "task",
        }
    ]


# ---------------------------------------------------------------------------
# 2. message inputs (real-today AD-916 source)
# ---------------------------------------------------------------------------


async def test_message_inputs_real_today(wi_store, chat_store, attach_store):
    sha = _sha(_BLOB_B)
    parent = await wi_store.create_work_item(title="parent", work_type="task")
    thread = chat_store.create_thread(
        title="room", participants=["bones-1"], task_id=parent.id
    )
    chat_store.append_message(
        thread.id,
        author_id="captain",
        role="captain",
        body="here is the file",
        metadata={"attachments": [{"content_hash": sha, "mime": "text/plain"}]},
    )
    out = await list_thread_inputs(
        thread.id, runtime=_runtime(chat_store, wi_store, attach_store)
    )
    assert out["inputs"] == [
        {
            "content_hash": sha,
            "mime": "text/plain",
            "filename": None,
            "size": len(_BLOB_B),
            "source": "message",
        }
    ]


# ---------------------------------------------------------------------------
# 3. merge + de-dupe by content_hash (task-level wins)
# ---------------------------------------------------------------------------


async def test_merge_dedupe_task_wins(wi_store, chat_store, attach_store):
    shared = _sha(_BLOB_A)
    msg_only = _sha(_BLOB_C)
    parent = await wi_store.create_work_item(
        title="parent",
        work_type="task",
        metadata={
            "input_attachments": [
                {"content_hash": shared, "mime": "image/png", "filename": "shared.png"}
            ]
        },
    )
    thread = chat_store.create_thread(
        title="room", participants=["bones-1"], task_id=parent.id
    )
    # message re-references the SAME hash (must dedupe, task wins) ...
    chat_store.append_message(
        thread.id,
        author_id="captain",
        role="captain",
        body="dup",
        metadata={"attachments": [{"content_hash": shared, "mime": "image/png"}]},
    )
    # ... plus a distinct message-only hash that must appear after the task ref.
    chat_store.append_message(
        thread.id,
        author_id="captain",
        role="captain",
        body="extra",
        metadata={"attachments": [{"content_hash": msg_only, "mime": "text/plain"}]},
    )
    out = await list_thread_inputs(
        thread.id, runtime=_runtime(chat_store, wi_store, attach_store)
    )
    inputs = out["inputs"]
    assert len(inputs) == 2
    assert inputs[0]["content_hash"] == shared
    assert inputs[0]["source"] == "task"
    assert inputs[0]["filename"] == "shared.png"
    assert inputs[1]["content_hash"] == msg_only
    assert inputs[1]["source"] == "message"


# ---------------------------------------------------------------------------
# 4. non-task thread → empty (even with message attachments)
# ---------------------------------------------------------------------------


async def test_no_task_id_returns_empty(wi_store, chat_store, attach_store):
    sha = _sha(_BLOB_B)
    thread = chat_store.create_thread(title="plain 1:1", participants=["bones-1"])
    chat_store.append_message(
        thread.id,
        author_id="captain",
        role="captain",
        body="hi",
        metadata={"attachments": [{"content_hash": sha, "mime": "text/plain"}]},
    )
    out = await list_thread_inputs(
        thread.id, runtime=_runtime(chat_store, wi_store, attach_store)
    )
    assert out["task_id"] is None
    assert out["inputs"] == []


# ---------------------------------------------------------------------------
# 5. task room with no inputs anywhere → empty
# ---------------------------------------------------------------------------


async def test_task_room_no_inputs_anywhere_empty(wi_store, chat_store, attach_store):
    parent = await wi_store.create_work_item(title="parent", work_type="task")
    thread = chat_store.create_thread(
        title="room", participants=["bones-1"], task_id=parent.id
    )
    out = await list_thread_inputs(
        thread.id, runtime=_runtime(chat_store, wi_store, attach_store)
    )
    assert out["inputs"] == []


# ---------------------------------------------------------------------------
# 6. unknown blob → honest-degrade size=None
# ---------------------------------------------------------------------------


async def test_unknown_blob_size_none(wi_store, chat_store, attach_store):
    ghost = hashlib.sha256(b"never-stored").hexdigest()
    parent = await wi_store.create_work_item(
        title="parent",
        work_type="task",
        metadata={
            "input_attachments": [
                {"content_hash": ghost, "mime": "text/plain", "filename": "ghost.txt"}
            ]
        },
    )
    thread = chat_store.create_thread(
        title="room", participants=["bones-1"], task_id=parent.id
    )
    out = await list_thread_inputs(
        thread.id, runtime=_runtime(chat_store, wi_store, attach_store)
    )
    assert out["inputs"][0]["content_hash"] == ghost
    assert out["inputs"][0]["size"] is None


# ---------------------------------------------------------------------------
# 7. missing thread → 404
# ---------------------------------------------------------------------------


async def test_missing_thread_404(wi_store, chat_store, attach_store):
    with pytest.raises(HTTPException) as exc:
        await list_thread_inputs(
            "does-not-exist", runtime=_runtime(chat_store, wi_store, attach_store)
        )
    assert exc.value.status_code == 404


# ---------------------------------------------------------------------------
# 8. work_item_store=None → message inputs still returned, no crash
# ---------------------------------------------------------------------------


async def test_work_item_store_none_degrades(chat_store, attach_store):
    sha = _sha(_BLOB_B)
    thread = chat_store.create_thread(
        title="room", participants=["bones-1"], task_id="task-xyz"
    )
    chat_store.append_message(
        thread.id,
        author_id="captain",
        role="captain",
        body="m",
        metadata={"attachments": [{"content_hash": sha, "mime": "text/plain"}]},
    )
    out = await list_thread_inputs(
        thread.id, runtime=_runtime(chat_store, None, attach_store)
    )
    assert [i["content_hash"] for i in out["inputs"]] == [sha]
    assert out["inputs"][0]["source"] == "message"


# ---------------------------------------------------------------------------
# 9. attachment_store=None → entries returned with size=None, no crash
# ---------------------------------------------------------------------------


async def test_attachment_store_none_size_none(wi_store, chat_store):
    sha = _sha(_BLOB_A)
    parent = await wi_store.create_work_item(
        title="parent",
        work_type="task",
        metadata={
            "input_attachments": [
                {"content_hash": sha, "mime": "image/png", "filename": "x.png"}
            ]
        },
    )
    thread = chat_store.create_thread(
        title="room", participants=["bones-1"], task_id=parent.id
    )
    out = await list_thread_inputs(
        thread.id, runtime=_runtime(chat_store, wi_store, None)
    )
    assert out["inputs"][0]["content_hash"] == sha
    assert out["inputs"][0]["size"] is None


# ---------------------------------------------------------------------------
# 10. metadata shape is exactly {content_hash, mime, filename, size, source}
# ---------------------------------------------------------------------------


async def test_metadata_shape_exact(wi_store, chat_store, attach_store):
    parent = await wi_store.create_work_item(
        title="parent",
        work_type="task",
        metadata={
            "input_attachments": [
                {"content_hash": _sha(_BLOB_A), "mime": "image/png", "filename": "x.png"}
            ]
        },
    )
    thread = chat_store.create_thread(
        title="room", participants=["bones-1"], task_id=parent.id
    )
    chat_store.append_message(
        thread.id,
        author_id="captain",
        role="captain",
        body="m",
        metadata={"attachments": [{"content_hash": _sha(_BLOB_B), "mime": "text/plain"}]},
    )
    out = await list_thread_inputs(
        thread.id, runtime=_runtime(chat_store, wi_store, attach_store)
    )
    assert len(out["inputs"]) == 2
    for entry in out["inputs"]:
        assert set(entry) == {"content_hash", "mime", "filename", "size", "source"}
