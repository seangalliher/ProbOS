"""AD-720: Filesystem AttachmentStore — v1 implementation.

Content-addressed by sha256. All blocking I/O wrapped in ``asyncio.to_thread``
(no ``aiofiles`` dependency — verified zero hits in pyproject.toml at HEAD;
project standard is ``run_in_executor`` / ``asyncio.to_thread``).

Cloud-Ready Storage: this implementation is the v1 substrate. The
``AttachmentStore`` Protocol in ``store.py`` is the seam — commercial
overlay can swap to S3 / Azure Blob without changing the chat router
or UI.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


_MIME_TO_EXT: dict[str, str] = {
    "image/png":  "png",
    "image/jpeg": "jpg",
    "image/webp": "webp",
    "image/gif":  "gif",
}


class FilesystemAttachmentStore:
    """Filesystem-backed AttachmentStore. Content-addressed by sha256."""

    def __init__(self, root: Path) -> None:
        self._root = root.resolve()
        self._root.mkdir(parents=True, exist_ok=True)

    def _path_for(self, content_hash: str, mime: str) -> Path:
        ext = _MIME_TO_EXT.get(mime)
        if ext is None:
            raise ValueError(f"AD-720: MIME {mime!r} not in allowed set")
        # sha256 hex is 64 chars [0-9a-f]; reject anything else for defense.
        if (
            len(content_hash) != 64
            or not all(c in "0123456789abcdef" for c in content_hash)
        ):
            raise ValueError(f"AD-720: malformed content_hash {content_hash!r}")
        candidate = (self._root / f"{content_hash}.{ext}").resolve()
        if not candidate.is_relative_to(self._root):
            raise ValueError(
                f"AD-720: path traversal rejected for {content_hash!r}"
            )
        return candidate

    async def write(self, content_hash: str, blob: bytes, mime: str) -> Path:
        """Idempotent write — if path exists, return without rewriting."""
        path = self._path_for(content_hash, mime)
        if path.exists():
            return path
        await asyncio.to_thread(path.write_bytes, blob)
        return path

    async def _find(self, content_hash: str) -> Path | None:
        # Reject malformed hashes before touching disk.
        if (
            len(content_hash) != 64
            or not all(c in "0123456789abcdef" for c in content_hash)
        ):
            raise ValueError(f"AD-720: malformed content_hash {content_hash!r}")
        matches = await asyncio.to_thread(
            lambda: list(self._root.glob(f"{content_hash}.*")),
        )
        return matches[0] if matches else None

    async def read(self, content_hash: str) -> bytes:
        path = await self._find(content_hash)
        if path is None:
            raise FileNotFoundError(content_hash)
        return await asyncio.to_thread(path.read_bytes)

    async def exists(self, content_hash: str) -> bool:
        path = await self._find(content_hash)
        return path is not None

    async def get_path(self, content_hash: str) -> Path:
        path = await self._find(content_hash)
        if path is None:
            raise FileNotFoundError(content_hash)
        return path

    async def size(self, content_hash: str) -> int:
        path = await self.get_path(content_hash)
        return await asyncio.to_thread(lambda: path.stat().st_size)
