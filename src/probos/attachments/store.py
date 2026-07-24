"""AD-720: AttachmentStore Protocol — content-addressed blob storage seam.

The Cloud-Ready-Storage principle: consumers depend on this Protocol;
v1 ships a single FilesystemAttachmentStore implementation; commercial
overlay can swap to S3 / Azure Blob without changing chat router or UI.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol


# AD-733-1: known origin tags. Anything else is coerced to ``chat_attachment``
# on write (safe default — chat_attachment never sweeps by age).
ATTACHMENT_ORIGINS: tuple[str, ...] = (
    "chat_attachment",
    "perception_frame",
    "browser_screenshot",
    "avatar_render",
    "agent_artifact",  # AD-797 (Wave 197): artifact bytes extracted from agent replies
    "crew_trace",  # AD-859a: durable agentic-loop provenance JSON
)


class AttachmentStoreFullError(OSError):
    """AD-733-1: raised by ``write`` when the underlying filesystem is out of
    space (ENOSPC). Callers translate this to HTTP 503 + Retry-After.
    """


class AttachmentStore(Protocol):
    """Content-addressed (sha256) attachment blob store.

    Implementations MUST be idempotent on ``write`` (re-writing the same
    ``content_hash`` is a no-op). Consumers depend on this Protocol; v1
    ships a single ``FilesystemAttachmentStore``.
    """

    async def write(
        self,
        content_hash: str,
        blob: bytes,
        mime: str,
        *,
        origin: str = "chat_attachment",
    ) -> Path:
        """Persist ``blob`` keyed by ``content_hash``. Idempotent.

        AD-733-1: ``origin`` tags the attachment so the reaper can apply
        different retention policies (e.g. ``perception_frame`` has an
        age-TTL; ``chat_attachment`` is operator intent and never expires
        by age). Unknown origins coerce to ``chat_attachment``. Raises
        :class:`AttachmentStoreFullError` on ENOSPC.
        """
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

    async def unlink(self, content_hash: str) -> bool:
        """AD-733-1: remove the blob and its index entry. Returns ``False``
        when not found. Concurrent ``FileNotFoundError`` never raises.
        """
        ...

    async def list_by_origin(self, origin: str) -> list[tuple[str, float]]:
        """AD-733-1: return ``[(content_hash, written_at)]`` for entries with
        the given origin, sorted ascending by ``written_at``.
        """
        ...

    async def total_size_bytes(self) -> int:
        """AD-733-1: return the total bytes occupied by the store."""
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
