"""AD-733-1: FilesystemAttachmentStore origin tagging + sidecar index tests."""

from __future__ import annotations

import errno
import hashlib
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from probos.attachments.filesystem_store import FilesystemAttachmentStore
from probos.attachments.store import AttachmentStoreFullError


def _sha(blob: bytes) -> str:
    return hashlib.sha256(blob).hexdigest()


@pytest.mark.asyncio
async def test_write_with_origin_round_trips_through_list_by_origin(tmp_path: Path) -> None:
    store = FilesystemAttachmentStore(tmp_path)
    blob = b"\x89PNG\r\n\x1a\nperception-bytes"
    sha = _sha(blob)
    await store.write(sha, blob, "image/png", origin="perception_frame")

    rows = await store.list_by_origin("perception_frame")
    assert [r[0] for r in rows] == [sha]

    other = await store.list_by_origin("chat_attachment")
    assert other == []

    # Sidecar index persisted on disk.
    index_path = tmp_path / ".index.json"
    assert index_path.exists()
    data = json.loads(index_path.read_text(encoding="utf-8"))
    assert data[sha]["origin"] == "perception_frame"
    assert data[sha]["size_bytes"] == len(blob)


@pytest.mark.asyncio
async def test_idempotent_rewrite_touches_written_at(tmp_path: Path) -> None:
    store = FilesystemAttachmentStore(tmp_path)
    blob = b"\xff\xd8\xff\xe0jpeg-bytes-here-for-test"
    sha = _sha(blob)

    await store.write(sha, blob, "image/jpeg", origin="perception_frame")
    rows1 = await store.list_by_origin("perception_frame")
    t1 = rows1[0][1]

    # Force a measurable time gap.
    import time as _t
    _t.sleep(0.01)

    await store.write(sha, blob, "image/jpeg", origin="perception_frame")
    rows2 = await store.list_by_origin("perception_frame")
    t2 = rows2[0][1]
    assert t2 > t1


@pytest.mark.asyncio
async def test_origin_upgrade_perception_to_chat(tmp_path: Path) -> None:
    """A perception_frame rewritten as chat_attachment upgrades to durable."""
    store = FilesystemAttachmentStore(tmp_path)
    blob = b"\xff\xd8\xff\xe0upgrade-test-bytes"
    sha = _sha(blob)

    await store.write(sha, blob, "image/jpeg", origin="perception_frame")
    assert (await store.list_by_origin("perception_frame"))[0][0] == sha

    await store.write(sha, blob, "image/jpeg", origin="chat_attachment")
    assert await store.list_by_origin("perception_frame") == []
    assert (await store.list_by_origin("chat_attachment"))[0][0] == sha

    # Reverse: chat_attachment must NOT be downgraded to perception_frame.
    await store.write(sha, blob, "image/jpeg", origin="perception_frame")
    assert await store.list_by_origin("perception_frame") == []
    assert (await store.list_by_origin("chat_attachment"))[0][0] == sha


@pytest.mark.asyncio
async def test_corrupt_index_recovers_to_empty(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    """Corrupt .index.json starts empty + WARNING; never raises."""
    (tmp_path / ".index.json").write_text("{not: valid json", encoding="utf-8")
    with caplog.at_level("WARNING"):
        store = FilesystemAttachmentStore(tmp_path)
    assert store._index == {}  # noqa: SLF001
    assert any("attachment index" in rec.message for rec in caplog.records)

    # Still functional after recovery.
    blob = b"\x89PNGrecovery"
    sha = _sha(blob)
    await store.write(sha, blob, "image/png", origin="chat_attachment")
    assert (await store.list_by_origin("chat_attachment"))[0][0] == sha


@pytest.mark.asyncio
async def test_enospc_raises_attachment_store_full(tmp_path: Path) -> None:
    """OSError(ENOSPC) on write surfaces as AttachmentStoreFullError."""
    store = FilesystemAttachmentStore(tmp_path)
    blob = b"\xff\xd8\xff\xe0enospc-test"
    sha = _sha(blob)

    def _raise_enospc(self: Path, _blob: bytes) -> int:
        raise OSError(errno.ENOSPC, "No space left on device")

    with patch.object(Path, "write_bytes", _raise_enospc):
        with pytest.raises(AttachmentStoreFullError):
            await store.write(sha, blob, "image/jpeg", origin="perception_frame")
