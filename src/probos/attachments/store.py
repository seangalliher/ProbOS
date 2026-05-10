"""AD-720: AttachmentStore Protocol — content-addressed blob storage seam.

The Cloud-Ready-Storage principle: consumers depend on this Protocol;
v1 ships a single FilesystemAttachmentStore implementation; commercial
overlay can swap to S3 / Azure Blob without changing chat router or UI.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol


class AttachmentStore(Protocol):
    """Content-addressed (sha256) attachment blob store.

    Implementations MUST be idempotent on ``write`` (re-writing the same
    ``content_hash`` is a no-op). Consumers depend on this Protocol; v1
    ships a single ``FilesystemAttachmentStore``.
    """

    async def write(self, content_hash: str, blob: bytes, mime: str) -> Path:
        """Persist ``blob`` keyed by ``content_hash``. Idempotent."""
        ...

    async def read(self, content_hash: str) -> bytes:
        """Return the stored blob bytes. Raises FileNotFoundError if absent."""
        ...

    async def exists(self, content_hash: str) -> bool:
        """True iff a blob with this ``content_hash`` is stored."""
        ...

    async def get_path(self, content_hash: str) -> Path:
        """Return the resolved absolute path of the blob file (without reading)."""
        ...

    async def size(self, content_hash: str) -> int:
        """Return size in bytes of the stored blob."""
        ...


def _resolve_attachments_dir(configured: str) -> Path:
    """AD-720: path-traversal-safe resolver for the attachments root.

    Mirrors ``routers/system.py:_resolve_avatars_dir`` (BF #539). Roots
    ``configured`` under ``_platform_data_dir()`` and strips a leading
    ``"data/"`` since ``_platform_data_dir()`` already ends in ``/data``.
    Returns an absolute, ``resolve()``-d path.
    """
    from probos.runtime import _platform_data_dir
    parts = Path(configured).parts
    if parts and parts[0] == "data":
        parts = parts[1:]
    base = _platform_data_dir()
    return (base.joinpath(*parts) if parts else base).resolve()
