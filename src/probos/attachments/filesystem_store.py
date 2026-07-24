"""AD-720: Filesystem AttachmentStore — v1 implementation.

Content-addressed by sha256. All blocking I/O wrapped in ``asyncio.to_thread``
(no ``aiofiles`` dependency — verified zero hits in pyproject.toml at HEAD;
project standard is ``run_in_executor`` / ``asyncio.to_thread``).

Cloud-Ready Storage: this implementation is the v1 substrate. The
``AttachmentStore`` Protocol in ``store.py`` is the seam — commercial
overlay can swap to S3 / Azure Blob without changing the chat router
or UI.

AD-733-1: origin tagging + sidecar index for the AttachmentReaper.
Concurrent ``write`` / ``unlink`` from the reaper task is serialized via
an ``asyncio.Lock`` on the store instance. The on-disk files remain the
source of truth; ``.index.json`` is a hint and corruption is tolerated
(logged WARNING, loaded as empty).
"""

from __future__ import annotations

import asyncio
import errno
import json
import logging
import os
import time
from pathlib import Path
from typing import Any

from probos.attachments.store import (
    ATTACHMENT_ORIGINS,
    AttachmentStoreFullError,
)

logger = logging.getLogger(__name__)


_MIME_TO_EXT: dict[str, str] = {
    "image/png":         "png",
    "image/jpeg":        "jpg",
    "image/webp":        "webp",
    "image/gif":         "gif",
    # AD-720a (Wave 139): file upload — non-image types.
    "application/pdf":   "pdf",
    "text/plain":        "txt",
    "text/markdown":     "md",
    "application/json":  "json",
    "text/csv":          "csv",
    # BF-643: Office document deliverables (agents produce .docx via the
    # AD-1064/code-exec path; .xlsx/.pptx round out the set). All are ZIP-based
    # OOXML containers; the allow-list gates persistence, magic-byte signatures
    # live in ``attachments/mime.py``.
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document":   "docx",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet":         "xlsx",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": "pptx",
    # AD-721b-1 (Wave 155): browser-captured utterance audio for the
    # rhubarb-lip-sync backend. Magic-byte signatures are registered in
    # ``attachments/mime.py._SIGNATURES``; the store needs the
    # mime→extension mapping to persist captured blobs.
    "audio/webm":        "webm",
    "audio/wav":         "wav",
    # AD-721d-3 / AD-721h (Wave 167): VRM is a glTF-binary container.
    "model/gltf-binary": "vrm",
}


def ext_to_mime(ext: str) -> str:
    """AD-720a: reverse-lookup helper. Single source of truth via ``_MIME_TO_EXT``.

    ``ext`` is the lowercase extension without leading dot. Returns the first
    matching MIME or ``"application/octet-stream"`` for unknown extensions.
    The GET endpoint uses this to set the response media type.
    """
    normalized = ext.lstrip(".").lower()
    # ``jpeg`` is an alias the GET endpoint historically accepted.
    if normalized == "jpeg":
        normalized = "jpg"
    for mime, e in _MIME_TO_EXT.items():
        if e == normalized:
            return mime
    return "application/octet-stream"


class FilesystemAttachmentStore:
    """Filesystem-backed AttachmentStore. Content-addressed by sha256."""

    # AD-733-1: precedence order for origin "upgrades" on idempotent writes.
    # A higher index is more-durable; a write may upgrade a less-durable
    # origin (perception_frame) to a more-durable one (chat_attachment)
    # for the same hash, but never the reverse.
    _ORIGIN_DURABILITY: tuple[str, ...] = (
        "perception_frame",
        "browser_screenshot",
        "avatar_render",
        "crew_trace",
        "chat_attachment",
        "agent_artifact",
    )

    def __init__(self, root: Path) -> None:
        self._root = root.resolve()
        self._root.mkdir(parents=True, exist_ok=True)
        # AD-733-1: sidecar index. Loaded lazily-synchronously here (the
        # constructor is called from sync code paths); subsequent updates
        # are async-serialized via ``_lock``.
        self._index_path = self._root / ".index.json"
        self._index: dict[str, dict[str, Any]] = self._load_index_sync()
        self._lock = asyncio.Lock()

    # ---- AD-733-1: sidecar index helpers ------------------------------

    def _load_index_sync(self) -> dict[str, dict[str, Any]]:
        """Load ``.index.json`` synchronously. Corruption -> WARNING + empty."""
        if not self._index_path.exists():
            return {}
        try:
            with self._index_path.open("r", encoding="utf-8") as fh:
                data = json.load(fh)
            if not isinstance(data, dict):
                logger.warning(
                    "AD-733-1: attachment index %s is not a dict; "
                    "starting empty (on-disk files remain source of truth)",
                    self._index_path,
                )
                return {}
            # Defensive: drop any non-dict entries.
            cleaned: dict[str, dict[str, Any]] = {}
            for k, v in data.items():
                if isinstance(k, str) and isinstance(v, dict):
                    cleaned[k] = v
            return cleaned
        except (OSError, json.JSONDecodeError) as ex:
            logger.warning(
                "AD-733-1: attachment index %s corrupt (%s); "
                "starting empty (on-disk files remain source of truth)",
                self._index_path,
                ex,
            )
            return {}

    def _save_index_sync(self) -> None:
        """Atomically persist ``.index.json`` via write-temp + rename.

        Tier-2 honest-degrade: on OSError we log WARNING and continue --
        the on-disk attachment files remain the source of truth. We
        intentionally do NOT re-raise here since the calling write() has
        already succeeded; failing to persist the index is degraded
        telemetry, not a data-loss event.
        """
        tmp = self._index_path.with_suffix(".json.tmp")
        try:
            with tmp.open("w", encoding="utf-8") as fh:
                json.dump(self._index, fh)
            os.replace(tmp, self._index_path)
        except OSError as ex:
            logger.warning(
                "AD-733-1: failed to persist attachment index %s: %s; "
                "next sweep will rebuild from disk",
                self._index_path,
                ex,
            )
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass

    @staticmethod
    def _normalize_origin(origin: str) -> str:
        """Coerce unknown origins to ``chat_attachment`` (safe -- never sweeps)."""
        if origin in ATTACHMENT_ORIGINS:
            return origin
        logger.warning(
            "AD-733-1: unknown attachment origin %r; coercing to "
            "'chat_attachment' (never sweeps by age)",
            origin,
        )
        return "chat_attachment"

    @classmethod
    def _origin_can_upgrade(cls, current: str, incoming: str) -> bool:
        """Return True iff ``incoming`` is at least as durable as ``current``."""
        order = cls._ORIGIN_DURABILITY
        try:
            return order.index(incoming) >= order.index(current)
        except ValueError:
            # Unknown origin -- defensive, keep current.
            return False

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

    async def write(
        self,
        content_hash: str,
        blob: bytes,
        mime: str,
        *,
        origin: str = "chat_attachment",
    ) -> Path:
        """Idempotent write — if path exists, return without rewriting.

        AD-733-1: tags the entry with ``origin`` in the sidecar index and
        touches ``written_at`` (LRU). Idempotent re-writes of the same
        hash may UPGRADE the origin (perception_frame -> chat_attachment)
        but never downgrade. Raises :class:`AttachmentStoreFullError` on
        ENOSPC.
        """
        normalized_origin = self._normalize_origin(origin)
        path = self._path_for(content_hash, mime)
        async with self._lock:
            need_write = not path.exists()
            if need_write:
                try:
                    await asyncio.to_thread(path.write_bytes, blob)
                except OSError as ex:
                    if getattr(ex, "errno", None) == errno.ENOSPC:
                        logger.error(
                            "AD-733-1: ENOSPC writing attachment %s (%d bytes); "
                            "disk-full -- frame dropped, no crash",
                            content_hash[:8],
                            len(blob),
                        )
                        raise AttachmentStoreFullError(
                            ex.errno, "attachment store out of space"
                        ) from ex
                    raise
            # Index update (always: re-touches written_at on idempotent re-write).
            entry = self._index.get(content_hash)
            now = time.time()
            if entry is None:
                self._index[content_hash] = {
                    "origin": normalized_origin,
                    "written_at": now,
                    "mime": mime,
                    "size_bytes": len(blob),
                }
            else:
                # Pin-style upgrade: never downgrade to a less-durable origin.
                existing_origin = entry.get("origin", "chat_attachment")
                if self._origin_can_upgrade(existing_origin, normalized_origin):
                    entry["origin"] = normalized_origin
                entry["written_at"] = now
                entry.setdefault("mime", mime)
                entry.setdefault("size_bytes", len(blob))
            self._save_index_sync()
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

    async def unlink(self, content_hash: str) -> bool:
        """AD-733-1: remove blob + index entry. ``False`` when not found.

        Concurrent ``FileNotFoundError`` (reaper races) is swallowed --
        the desired post-state is "not present", which is satisfied.
        """
        async with self._lock:
            path = await self._find(content_hash)
            existed = False
            if path is not None:
                try:
                    await asyncio.to_thread(path.unlink)
                    existed = True
                except FileNotFoundError:
                    pass
                except OSError as ex:
                    logger.warning(
                        "AD-733-1: unlink failed for %s: %s; "
                        "leaving on disk for next sweep",
                        content_hash[:8],
                        ex,
                    )
                    return False
            removed_from_index = self._index.pop(content_hash, None) is not None
            if existed or removed_from_index:
                self._save_index_sync()
            return existed or removed_from_index

    async def list_by_origin(self, origin: str) -> list[tuple[str, float]]:
        """AD-733-1: ``[(sha, written_at)]`` for entries with ``origin``,
        sorted ascending by ``written_at`` (oldest first).
        """
        normalized = self._normalize_origin(origin)
        async with self._lock:
            rows: list[tuple[str, float]] = []
            for sha, entry in self._index.items():
                if entry.get("origin", "chat_attachment") == normalized:
                    try:
                        rows.append((sha, float(entry.get("written_at", 0.0))))
                    except (TypeError, ValueError):
                        continue
            rows.sort(key=lambda r: r[1])
            return rows

    async def total_size_bytes(self) -> int:
        """AD-733-1: total bytes occupied. Falls back to a disk scan when
        the index is empty (cold-boot before any write).
        """
        async with self._lock:
            if self._index:
                total = 0
                for entry in self._index.values():
                    try:
                        total += int(entry.get("size_bytes", 0))
                    except (TypeError, ValueError):
                        continue
                return total
        # Cold path: index empty, scan disk. No need to hold the lock --
        # we're only reading sizes, and concurrent writes will update the
        # index for the next call.
        def _scan() -> int:
            total = 0
            for child in self._root.iterdir():
                if child.name.startswith("."):
                    continue
                try:
                    if child.is_file():
                        total += child.stat().st_size
                except OSError:
                    continue
            return total
        return await asyncio.to_thread(_scan)

    async def mime_for(self, content_hash: str) -> str | None:
        """AD-720d (Wave 139): derive MIME from the on-disk extension.

        Returns the MIME or None if the attachment is not stored. Uses the
        module-level ``ext_to_mime`` helper as the single source of truth
        (backed by ``_MIME_TO_EXT``).
        """
        path = await self._find(content_hash)
        if path is None:
            return None
        return ext_to_mime(path.suffix)
