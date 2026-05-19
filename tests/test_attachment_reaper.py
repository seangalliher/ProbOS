"""AD-733-1: AttachmentReaper retention + LRU sweep tests."""

from __future__ import annotations

import asyncio
import hashlib
import time
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from probos.attachments.filesystem_store import FilesystemAttachmentStore
from probos.attachments.reaper import AttachmentReaper
from probos.config import AttachmentsConfig, PerceptionConfig
from probos.events import EventType


def _sha(blob: bytes) -> str:
    return hashlib.sha256(blob).hexdigest()


def _make_cfg(
    *,
    frame_retention_seconds: int = 300,
    reaper_interval_seconds: int = 60,
    max_store_bytes: int = 0,
) -> tuple[PerceptionConfig, AttachmentsConfig]:
    # PerceptionConfig.frame_retention_seconds minimum is 30; tests use
    # the minimum and force-age the index entries via written_at.
    retention = max(30, frame_retention_seconds)
    perception = PerceptionConfig(
        enabled=True,
        frame_retention_seconds=retention,
        reaper_interval_seconds=reaper_interval_seconds,
    )
    attachments = AttachmentsConfig(max_store_bytes=max_store_bytes)
    return perception, attachments


async def _seed(
    store: FilesystemAttachmentStore,
    *,
    origin: str,
    blob: bytes,
    written_at: float | None = None,
) -> str:
    sha = _sha(blob)
    await store.write(sha, blob, "image/jpeg", origin=origin)
    if written_at is not None:
        # Force-age the index entry so the reaper considers it expired.
        async with store._lock:  # noqa: SLF001
            store._index[sha]["written_at"] = written_at  # noqa: SLF001
            store._save_index_sync()  # noqa: SLF001
    return sha


# ----------------------------------------------------------------------
# Age TTL policy
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_age_ttl_evicts_perception_frames_only(tmp_path: Path) -> None:
    store = FilesystemAttachmentStore(tmp_path)
    perception, attachments = _make_cfg(frame_retention_seconds=300)
    past = time.time() - 600

    sha_a = await _seed(store, origin="perception_frame", blob=b"\xff\xd8a" * 20, written_at=past)
    sha_b = await _seed(store, origin="perception_frame", blob=b"\xff\xd8b" * 20, written_at=past)
    sha_c = await _seed(store, origin="perception_frame", blob=b"\xff\xd8c" * 20, written_at=past)
    sha_chat = await _seed(store, origin="chat_attachment", blob=b"\xff\xd8chat" * 5, written_at=past)

    reaper = AttachmentReaper(store, perception_cfg=perception, attachments_cfg=attachments)
    summary = await reaper.sweep_once()

    assert summary["age_ttl_removed"] == 3
    for sha in (sha_a, sha_b, sha_c):
        assert not await store.exists(sha)
    # chat_attachment survives age TTL regardless of age.
    assert await store.exists(sha_chat)


@pytest.mark.asyncio
@pytest.mark.parametrize("retention", [30, 300, 3600])
async def test_age_ttl_respects_retention_knob(tmp_path: Path, retention: int) -> None:
    store = FilesystemAttachmentStore(tmp_path)
    perception, attachments = _make_cfg(frame_retention_seconds=retention)
    # Frame is twice the retention old -> always evicted.
    sha_old = await _seed(
        store, origin="perception_frame", blob=b"\xff\xd8old" * 10,
        written_at=time.time() - retention * 2,
    )
    # Frame is fresh -> always survives.
    sha_fresh = await _seed(store, origin="perception_frame", blob=b"\xff\xd8new" * 10)

    reaper = AttachmentReaper(store, perception_cfg=perception, attachments_cfg=attachments)
    await reaper.sweep_once()

    assert not await store.exists(sha_old)
    assert await store.exists(sha_fresh)


# ----------------------------------------------------------------------
# LRU policy
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_lru_evicts_perception_first_then_chat(tmp_path: Path) -> None:
    store = FilesystemAttachmentStore(tmp_path)
    # cap small enough that we MUST evict to fit.
    perception, attachments = _make_cfg(
        frame_retention_seconds=86400,  # don't expire by age
        max_store_bytes=5_000,
    )
    blob_p = b"P" * 2_000  # 2 KB perception frames
    blob_c = b"C" * 2_000  # 2 KB chat attachments
    # Use distinct content so each has a unique sha.
    shas_perception: list[str] = []
    shas_chat: list[str] = []
    for i in range(3):
        s = await _seed(
            store, origin="perception_frame",
            blob=blob_p + i.to_bytes(2, "big"),
            written_at=time.time() - (10 - i),  # oldest first
        )
        shas_perception.append(s)
    for i in range(2):
        s = await _seed(
            store, origin="chat_attachment",
            blob=blob_c + i.to_bytes(2, "big"),
            written_at=time.time() - (5 - i),
        )
        shas_chat.append(s)

    total_before = await store.total_size_bytes()
    assert total_before > 5_000

    reaper = AttachmentReaper(store, perception_cfg=perception, attachments_cfg=attachments)
    summary = await reaper.sweep_once()
    assert summary["lru_removed"] >= 1

    # Oldest perception frame must be gone first.
    assert not await store.exists(shas_perception[0])
    # All chat attachments survive because perception was sufficient.
    for s in shas_chat:
        assert await store.exists(s)
    assert await store.total_size_bytes() <= 5_000


@pytest.mark.asyncio
async def test_lru_disabled_when_max_store_bytes_zero(tmp_path: Path) -> None:
    store = FilesystemAttachmentStore(tmp_path)
    perception, attachments = _make_cfg(
        frame_retention_seconds=86400,
        max_store_bytes=0,
    )
    blob = b"X" * 8_000
    sha = await _seed(store, origin="chat_attachment", blob=blob)

    reaper = AttachmentReaper(store, perception_cfg=perception, attachments_cfg=attachments)
    summary = await reaper.sweep_once()

    assert summary["lru_removed"] == 0
    assert await store.exists(sha)


# ----------------------------------------------------------------------
# Honest-degrade on filesystem errors
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reaper_continues_past_file_not_found(tmp_path: Path) -> None:
    """Concurrent unlink mid-sweep must not raise."""
    store = FilesystemAttachmentStore(tmp_path)
    perception, attachments = _make_cfg(frame_retention_seconds=10)
    past = time.time() - 1000
    sha = await _seed(store, origin="perception_frame", blob=b"\xff\xd8gone", written_at=past)

    # Race: delete the on-disk file before the reaper sweeps.
    path = await store.get_path(sha)
    path.unlink()

    reaper = AttachmentReaper(store, perception_cfg=perception, attachments_cfg=attachments)
    summary = await reaper.sweep_once()  # MUST NOT raise.
    # The index entry is cleaned up regardless.
    assert sha not in store._index  # noqa: SLF001
    assert summary["age_ttl_removed"] >= 0  # tolerant -- the key behavior is no-raise


@pytest.mark.asyncio
async def test_reaper_continues_past_permission_error(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    store = FilesystemAttachmentStore(tmp_path)
    perception, attachments = _make_cfg(frame_retention_seconds=10)
    past = time.time() - 1000
    sha_blocked = await _seed(
        store, origin="perception_frame", blob=b"\xff\xd8blocked", written_at=past
    )
    sha_ok = await _seed(
        store, origin="perception_frame", blob=b"\xff\xd8okay", written_at=past
    )

    original_unlink = FilesystemAttachmentStore.unlink

    async def _flaky_unlink(self: FilesystemAttachmentStore, ch: str) -> bool:
        if ch == sha_blocked:
            raise PermissionError("Windows file in use")
        return await original_unlink(self, ch)

    with patch.object(FilesystemAttachmentStore, "unlink", _flaky_unlink):
        with caplog.at_level("WARNING"):
            reaper = AttachmentReaper(
                store, perception_cfg=perception, attachments_cfg=attachments
            )
            await reaper.sweep_once()  # MUST NOT raise.

    # The non-blocked entry was reaped; the blocked one survives for next sweep.
    assert await store.exists(sha_blocked)
    assert not await store.exists(sha_ok)


# ----------------------------------------------------------------------
# Lifecycle
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reaper_start_stop_roundtrip_under_2s(tmp_path: Path) -> None:
    store = FilesystemAttachmentStore(tmp_path)
    perception, attachments = _make_cfg(reaper_interval_seconds=60)
    reaper = AttachmentReaper(store, perception_cfg=perception, attachments_cfg=attachments)

    await reaper.start()
    assert reaper._task is not None  # noqa: SLF001
    assert not reaper._task.done()  # noqa: SLF001

    t0 = time.monotonic()
    await reaper.stop()
    elapsed = time.monotonic() - t0
    assert elapsed < 2.0
    assert reaper._task is None  # noqa: SLF001

    # Idempotent: second stop is a no-op.
    await reaper.stop()


@pytest.mark.asyncio
async def test_attachment_reaped_event_emitted(tmp_path: Path) -> None:
    store = FilesystemAttachmentStore(tmp_path)
    perception, attachments = _make_cfg(frame_retention_seconds=10)
    past = time.time() - 1000
    await _seed(store, origin="perception_frame", blob=b"\xff\xd8e1", written_at=past)
    await _seed(store, origin="perception_frame", blob=b"\xff\xd8e2", written_at=past)

    events: list[tuple[Any, dict[str, Any]]] = []

    def _emit(et, payload):  # noqa: ANN001
        events.append((et, payload))

    reaper = AttachmentReaper(
        store,
        perception_cfg=perception,
        attachments_cfg=attachments,
        event_emitter=_emit,
    )
    await reaper.sweep_once()
    assert any(et == EventType.ATTACHMENT_REAPED for et, _ in events)
    payload = next(p for et, p in events if et == EventType.ATTACHMENT_REAPED)
    assert payload["age_ttl_removed"] == 2


# Remove unused import warning suppression -- asyncio is used by pytest-asyncio.
_ = asyncio
