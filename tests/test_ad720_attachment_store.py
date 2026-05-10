"""AD-720: FilesystemAttachmentStore tests."""

from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path

import pytest

from probos.attachments.filesystem_store import FilesystemAttachmentStore


_PNG_HEADER = b"\x89PNG\r\n\x1a\n"


def _make_blob(seed: bytes = b"x") -> tuple[bytes, str]:
    blob = _PNG_HEADER + seed * 32
    return blob, hashlib.sha256(blob).hexdigest()


@pytest.fixture
def store(tmp_path: Path) -> FilesystemAttachmentStore:
    return FilesystemAttachmentStore(tmp_path / "attachments")


@pytest.mark.asyncio
async def test_filesystem_store_write_persists_blob(store, tmp_path):
    blob, h = _make_blob(b"a")
    path = await store.write(h, blob, "image/png")
    assert path.exists()
    assert path.name == f"{h}.png"
    assert path.read_bytes() == blob


@pytest.mark.asyncio
async def test_filesystem_store_write_is_idempotent(store):
    blob, h = _make_blob(b"b")
    p1 = await store.write(h, blob, "image/png")
    mtime1 = p1.stat().st_mtime_ns
    await asyncio.sleep(0.01)
    p2 = await store.write(h, blob, "image/png")
    assert p1 == p2
    # File not rewritten — mtime preserved.
    assert p2.stat().st_mtime_ns == mtime1


@pytest.mark.asyncio
async def test_filesystem_store_exists_round_trip(store):
    blob, h = _make_blob(b"c")
    assert await store.exists(h) is False
    await store.write(h, blob, "image/png")
    assert await store.exists(h) is True


@pytest.mark.asyncio
async def test_filesystem_store_size_returns_byte_count(store):
    blob, h = _make_blob(b"d")
    await store.write(h, blob, "image/png")
    assert await store.size(h) == len(blob)


@pytest.mark.asyncio
async def test_filesystem_store_read_returns_original_bytes(store):
    blob, h = _make_blob(b"e")
    await store.write(h, blob, "image/png")
    assert await store.read(h) == blob


@pytest.mark.asyncio
async def test_filesystem_store_path_traversal_rejected(store):
    with pytest.raises(ValueError):
        await store.write("../../etc/passwd", b"x", "image/png")


@pytest.mark.asyncio
async def test_filesystem_store_unknown_mime_rejected(store):
    blob, h = _make_blob(b"f")
    with pytest.raises(ValueError):
        await store.write(h, blob, "image/svg+xml")


@pytest.mark.asyncio
async def test_filesystem_store_uses_asyncio_to_thread(store, monkeypatch):
    """Verify blocking IO is dispatched through asyncio.to_thread."""
    calls: list[str] = []
    real_to_thread = asyncio.to_thread

    async def spy(fn, *args, **kwargs):
        calls.append(getattr(fn, "__name__", str(fn)))
        return await real_to_thread(fn, *args, **kwargs)

    monkeypatch.setattr("probos.attachments.filesystem_store.asyncio.to_thread", spy)
    blob, h = _make_blob(b"g")
    await store.write(h, blob, "image/png")
    assert calls, "asyncio.to_thread was not invoked"


@pytest.mark.asyncio
async def test_filesystem_store_get_path_returns_absolute(store):
    blob, h = _make_blob(b"h")
    await store.write(h, blob, "image/png")
    p = await store.get_path(h)
    assert p.is_absolute()
    assert p.name == f"{h}.png"


@pytest.mark.asyncio
async def test_filesystem_store_read_missing_raises(store):
    with pytest.raises(FileNotFoundError):
        await store.read("0" * 64)
