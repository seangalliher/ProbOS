"""AD-720: Filesystem AttachmentStore — v1 implementation.

Content-addressed by sha256. BF-918 M4 (#1626): every blocking call runs on the
store's own bounded executor (``ATTACHMENT_IO_WORKERS`` threads), so crew work
that fills asyncio's default pool does not delay storing or serving an
attachment; after :meth:`close`, on the default pool (no ``aiofiles``
dependency; project standard is ``run_in_executor``). The exception is the
constructor (resolving the root, making it and loading the index), which is
called from sync code.

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
import concurrent.futures
import contextvars
import errno
import json
import logging
import os
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, TypeVar

from probos.attachments.store import (
    ATTACHMENT_ORIGINS,
    AttachmentStoreFullError,
)

logger = logging.getLogger(__name__)

_T = TypeVar("_T")

#: BF-918 M4 (#1626): threads for one store's blocking I/O. Calls beyond it queue.
ATTACHMENT_IO_WORKERS = 4
#: BF-918 M4: the name prefix of those threads (``probos-attachment-io_0`` ...).
ATTACHMENT_IO_THREAD_PREFIX = "probos-attachment-io"


async def _finish_cancelled(call: asyncio.Future[Any]) -> None:
    """BF-918 M4 (review round 1): wait for a store call whose caller was cancelled.

    A thread cannot be stopped. Waiting keeps the caller's lock held until the call
    really ends; the caller then re-raises its cancellation. A further cancellation
    while waiting is absorbed for the same reason. An exception the call raised is
    logged, since its caller can no longer receive it.
    """
    while not call.done():
        try:
            await asyncio.wait((call,))
        except asyncio.CancelledError:
            pass  # cancelled again: keep waiting; the caller re-raises the first cancellation
    if not call.cancelled() and call.exception() is not None:
        logger.warning(
            "BF-918: an attachment store call failed after its caller was cancelled: %r",
            call.exception(),
        )


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
        "tts_audio",  # BF-918: least durable; any other write of the same bytes wins
        "perception_frame",
        "browser_screenshot",
        "avatar_render",
        "crew_trace",
        "chat_attachment",
        "agent_artifact",
    )

    def __init__(self, root: Path, *, io_workers: int = ATTACHMENT_IO_WORKERS) -> None:
        if io_workers < 1:
            raise ValueError("BF-918: the attachment store needs at least 1 I/O thread")
        # BF-918 M4 (#1626): this store's own I/O threads, made on first use.
        self._io_workers = io_workers
        self._io_executor: concurrent.futures.ThreadPoolExecutor | None = None
        self._io_closed = False
        self._root = root.resolve()
        self._root.mkdir(parents=True, exist_ok=True)
        # AD-733-1: sidecar index. Loaded lazily-synchronously here (the
        # constructor is called from sync code paths); subsequent updates
        # are async-serialized via ``_lock``.
        self._index_path = self._root / ".index.json"
        self._index: dict[str, dict[str, Any]] = self._load_index_sync()
        self._lock = asyncio.Lock()

    # ---- BF-918 M4 (#1626): the store's own I/O threads ---------------

    @property
    def io_closed(self) -> bool:
        """True once :meth:`close` has run; the store's I/O then uses the default pool."""
        return self._io_closed

    async def _run(self, fn: Callable[..., _T], *args: Any) -> _T:
        """Run one blocking call on this store's threads (the default pool once closed).

        Crew work that fills asyncio's default pool no longer delays the store.
        Calls beyond ``io_workers`` queue on these threads: store I/O is never
        refused. After :meth:`close`, a call (a route, or crew work that stops
        later in shutdown) runs on the default pool, as before BF-918 M4.

        A thread cannot be stopped, so a cancelled caller first waits for its call
        to end and then re-raises the cancellation (BF-918 M4, review round 1). A
        caller that holds ``self._lock`` therefore never releases it while its
        index save, blob write or unlink still runs.

        After :meth:`close`, the call is the default pool's own future, run in a
        copy of the caller's context, never a task: the event loop's teardown
        (``asyncio.run``) cancels every task, and a cancelled task would end the
        caller's wait while its thread still runs (BF-918 M4, review round 2).
        """
        call: asyncio.Future[_T]
        if self._io_closed:
            call = asyncio.get_running_loop().run_in_executor(None, contextvars.copy_context().run, fn, *args)
        else:
            if self._io_executor is None:
                self._io_executor = concurrent.futures.ThreadPoolExecutor(
                    max_workers=self._io_workers,
                    thread_name_prefix=ATTACHMENT_IO_THREAD_PREFIX,
                )
            call = asyncio.get_running_loop().run_in_executor(self._io_executor, fn, *args)
        try:
            return await asyncio.shield(call)
        except asyncio.CancelledError:
            await _finish_cancelled(call)
            raise

    def close(self) -> None:
        """Stop this store's I/O threads. Idempotent; never raises; never awaits.

        Work already accepted runs to completion: nothing is cancelled, so a caller
        awaiting a write never sees it fail because shutdown began. The threads exit
        once that work is done. Called by ``startup/shutdown.py`` after the
        attachment reaper has stopped.
        """
        self._io_closed = True
        executor, self._io_executor = self._io_executor, None
        if executor is not None:
            executor.shutdown(wait=False, cancel_futures=False)

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

    def _locate_sync(self, content_hash: str, mime: str) -> tuple[Path, bool]:
        """BF-918 M4 (review round 1): the blob's checked path and whether it exists.

        ``Path.resolve`` and ``exists`` touch the filesystem, so ``write`` runs
        both in one call on a store thread. The validation in :meth:`_path_for`
        raises ``ValueError`` from there, unchanged.
        """
        path = self._path_for(content_hash, mime)
        return path, path.exists()

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
        async with self._lock:
            path, present = await self._run(self._locate_sync, content_hash, mime)
            need_write = not present
            if need_write:
                try:
                    await self._run(path.write_bytes, blob)
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
            # BF-918 M4: still under the lock, so no other call changes the index while it is written.
            await self._run(self._save_index_sync)
        return path

    async def _find(self, content_hash: str) -> Path | None:
        # Reject malformed hashes before touching disk.
        if (
            len(content_hash) != 64
            or not all(c in "0123456789abcdef" for c in content_hash)
        ):
            raise ValueError(f"AD-720: malformed content_hash {content_hash!r}")
        matches = await self._run(
            lambda: list(self._root.glob(f"{content_hash}.*")),
        )
        return matches[0] if matches else None

    async def read(self, content_hash: str) -> bytes:
        path = await self._find(content_hash)
        if path is None:
            raise FileNotFoundError(content_hash)
        return await self._run(path.read_bytes)

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
        return await self._run(lambda: path.stat().st_size)

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
                    await self._run(path.unlink)
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
                await self._run(self._save_index_sync)
            return existed or removed_from_index

    async def unlink_if_unchanged(
        self,
        content_hash: str,
        *,
        origin: str,
        written_at: float,
    ) -> int | None:
        """BF-918 (#1626): remove an entry only if it is still the one a caller listed.

        The reaper lists entries under the lock, releases it, and removes them
        one by one; a write in between may refresh ``written_at`` or upgrade the
        origin. The check and the removal happen here under one hold of the
        lock, so such an entry is kept. The lock and the index are this
        instance's: a write through another store object or another process on
        the same root is not seen, so one instance per attachment root is a
        precondition (production builds one per runtime; BF-918 review round 2).
        Returns the bytes freed (0 when the blob
        was already gone and only its index entry is removed), or ``None`` when
        the entry is absent, has another origin, was written after
        ``written_at``, or its blob could not be removed.
        """
        async with self._lock:
            entry = self._index.get(content_hash)
            if entry is None or entry.get("origin", "chat_attachment") != origin:
                return None
            try:
                current = float(entry.get("written_at", 0.0))
            except (TypeError, ValueError):
                return None
            if current > written_at:
                return None
            path = await self._find(content_hash)
            freed = 0
            if path is not None:
                try:
                    freed = (await self._run(path.stat)).st_size
                    await self._run(path.unlink)
                except FileNotFoundError:
                    freed = 0
                except OSError as ex:
                    logger.warning(
                        "BF-918: conditional unlink failed for %s: %s; "
                        "leaving on disk for next sweep",
                        content_hash[:8],
                        ex,
                    )
                    return None
            del self._index[content_hash]
            await self._run(self._save_index_sync)
            return freed

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
        return await self._run(_scan)

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
