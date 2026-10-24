"""BF-918 M4 (#1626, the BF-918 contract's section 18 R9): the attachment store's own I/O threads.

Crew work can fill asyncio's default pool; storing the spoken WAV and serving it
must not wait behind that work. Real store, real files. Only the default pool and,
in some cases, one blocking file call are replaced.
"""

from __future__ import annotations

import ast
import asyncio
import errno
import hashlib
import inspect
import json
import logging
import textwrap
import threading
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import pytest

from probos.attachments.filesystem_store import (
    ATTACHMENT_IO_THREAD_PREFIX,
    FilesystemAttachmentStore,
)
from probos.startup import shutdown as shutdown_module

_PNG = b"\x89PNG\r\n\x1a\n"


def _blob(seed: bytes) -> tuple[bytes, str]:
    blob = _PNG + seed * 32
    return blob, hashlib.sha256(blob).hexdigest()


async def _until(predicate, timeout: float = 3.0) -> bool:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        if predicate():
            return True
        await asyncio.sleep(0.01)
    return bool(predicate())


class _HeldReads:
    """Stands in for ``Path.read_bytes``: each call records its thread, then blocks until released.

    It records the thread object, not its name: every store names its threads alike
    (review round 1, finding 2).
    """

    def __init__(self) -> None:
        self.release = threading.Event()
        self.threads: list[threading.Thread] = []
        self._real = Path.read_bytes
        self._lock = threading.Lock()

    def __call__(self, path: Path) -> bytes:
        with self._lock:
            self.threads.append(threading.current_thread())
        self.release.wait(10)
        return self._real(path)


class _Gate:
    """Stands in for one blocking call: its first call sets ``entered``, then blocks until ``release``.

    ``finished`` is set once that call has returned or raised. Later calls pass straight through.
    """

    def __init__(self, real, *, fail: BaseException | None = None) -> None:
        self.entered = threading.Event()
        self.release = threading.Event()
        self.finished = threading.Event()
        self._real = real
        self._fail = fail
        self._first = True
        self._lock = threading.Lock()

    def __call__(self, *args):
        with self._lock:
            first, self._first = self._first, False
        if not first:
            return self._real(*args)
        self.entered.set()
        self.release.wait(10)
        try:
            if self._fail is not None:
                raise self._fail
            return self._real(*args)
        finally:
            self.finished.set()


async def _turns(count: int = 20) -> None:
    """Lets the event loop run ``count`` times: loop turns, not wall-clock time."""
    for _ in range(count):
        await asyncio.sleep(0)


@pytest.fixture(autouse=True)
def _close_the_stores_built_here(monkeypatch) -> Iterator[None]:
    """Closes every store a test in this file builds, pass or fail (review round 1, finding 2)."""
    built: list[FilesystemAttachmentStore] = []
    real_init = FilesystemAttachmentStore.__init__

    def init(self, *args, **kwargs) -> None:
        real_init(self, *args, **kwargs)
        built.append(self)

    monkeypatch.setattr(FilesystemAttachmentStore, "__init__", init)
    yield
    for store in built:
        store.close()


@pytest.mark.asyncio
async def test_store_io_does_not_wait_for_a_busy_default_pool(tmp_path: Path) -> None:
    """R9: with asyncio's default pool fully held, spoken audio is stored, found and served."""
    store = FilesystemAttachmentStore(tmp_path / "attachments")
    loop = asyncio.get_running_loop()
    release = threading.Event()
    pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="bf918-m4-busy-default")
    loop.set_default_executor(pool)
    held = loop.run_in_executor(None, release.wait, 30)
    blob, h = _blob(b"w")

    async def _store_and_serve() -> bytes:
        await store.write(h, blob, "audio/wav", origin="tts_audio")  # routers/avatars.py
        assert await store.exists(h)  # routers/chat.py, GET /api/chat/attachments
        assert (await store.get_path(h)).name == f"{h}.wav"
        return await store.read(h)

    try:
        assert await asyncio.wait_for(_store_and_serve(), timeout=3.0) == blob
    finally:
        release.set()
        await held
        store.close()
        pool.shutdown(wait=True)
        loop.set_default_executor(ThreadPoolExecutor(thread_name_prefix="asyncio"))


@pytest.mark.asyncio
async def test_every_blocking_call_runs_on_the_store_threads(tmp_path: Path, monkeypatch) -> None:
    """Every blocking call of every method, including ``write``'s path resolution and each stat
    (review round 1, finding 3) and the cold size scan (review round 2, finding 2), runs on a store
    thread. Only calls on paths in the store count."""
    store = FilesystemAttachmentStore(tmp_path / "attachments")
    root = str((tmp_path / "attachments").resolve())
    seen: dict[str, set[str]] = {}
    real_save = FilesystemAttachmentStore._save_index_sync

    def save(self) -> None:
        seen.setdefault("index save", set()).add(threading.current_thread().name)
        real_save(self)

    def spy(name: str, real):
        def call(path: Path, *args, **kwargs):
            if str(path).startswith(root):
                seen.setdefault(name, set()).add(threading.current_thread().name)
            return real(path, *args, **kwargs)

        return call

    (tmp_path / "attachments" / "stray.bin").write_bytes(b"abc")  # unindexed: only the cold size scan counts it
    monkeypatch.setattr(FilesystemAttachmentStore, "_save_index_sync", save)
    for name in ("resolve", "exists", "stat", "read_bytes", "write_bytes", "unlink", "iterdir", "is_file"):
        monkeypatch.setattr(Path, name, spy(name, getattr(Path, name)))
    blob, h = _blob(b"n")
    other, h2 = _blob(b"m")
    try:
        await store.write(h, blob, "audio/wav", origin="tts_audio")
        await store.write(h, blob, "audio/wav", origin="tts_audio")  # the repeated write
        assert await store.read(h) == blob
        assert await store.size(h) == len(blob)
        assert await store.unlink(h) is True
        await store.write(h2, other, "audio/wav", origin="tts_audio")
        [(_, written_at)] = await store.list_by_origin("tts_audio")
        assert await store.unlink_if_unchanged(h2, origin="tts_audio", written_at=written_at) == len(other)
        assert await store.total_size_bytes() == 3  # the index is empty now: the cold scan of the root
    finally:
        store.close()
    expected = {"index save", "resolve", "exists", "stat", "read_bytes", "write_bytes", "unlink", "iterdir", "is_file"}
    assert set(seen) == expected, seen
    assert all(name.startswith(ATTACHMENT_IO_THREAD_PREFIX) for names in seen.values() for name in names), seen


@pytest.mark.asyncio
async def test_calls_beyond_the_bound_queue_and_all_complete(tmp_path: Path, monkeypatch) -> None:
    store = FilesystemAttachmentStore(tmp_path / "attachments", io_workers=1)
    blob, h = _blob(b"q")
    await store.write(h, blob, "image/png")
    held = _HeldReads()
    monkeypatch.setattr(Path, "read_bytes", lambda self: held(self))
    reads = [asyncio.create_task(store.read(h)) for _ in range(3)]
    try:
        assert await _until(lambda: len(held.threads) == 1)
        await asyncio.sleep(0.05)  # room for a second read to start, if the bound allowed one
        assert len(held.threads) == 1
        assert not any(task.done() for task in reads)  # queued, not refused
    finally:
        held.release.set()
    assert await asyncio.wait_for(asyncio.gather(*reads), timeout=5.0) == [blob, blob, blob]
    assert len(held.threads) == 3 and len(set(held.threads)) == 1
    store.close()


@pytest.mark.asyncio
async def test_close_lets_accepted_work_finish_and_its_threads_exit(tmp_path: Path, monkeypatch) -> None:
    store = FilesystemAttachmentStore(tmp_path / "attachments", io_workers=1)
    blob, h = _blob(b"c")
    await store.write(h, blob, "image/png")
    held = _HeldReads()
    monkeypatch.setattr(Path, "read_bytes", lambda self: held(self))
    running = asyncio.create_task(store.read(h))
    assert await _until(lambda: len(held.threads) == 1)
    worker = held.threads[0]  # this store's own thread: names repeat across stores
    queued = asyncio.create_task(store.read(h))  # its lookup is queued behind the running read
    await asyncio.sleep(0.05)

    store.close()
    store.close()  # idempotent
    assert store.io_closed is True
    held.release.set()

    assert await asyncio.wait_for(asyncio.gather(running, queued), timeout=5.0) == [blob, blob]
    assert await _until(lambda: not worker.is_alive())


@pytest.mark.asyncio
async def test_a_closed_store_still_stores_and_serves_on_the_default_pool(tmp_path: Path, monkeypatch) -> None:
    store = FilesystemAttachmentStore(tmp_path / "attachments")
    store.close()
    threads: list[str] = []
    real_write = Path.write_bytes

    def write(self, data) -> int:
        threads.append(threading.current_thread().name)
        return real_write(self, data)

    monkeypatch.setattr(Path, "write_bytes", write)
    blob, h = _blob(b"d")
    await store.write(h, blob, "image/png")
    assert await store.read(h) == blob
    assert threads and not any(name.startswith(ATTACHMENT_IO_THREAD_PREFIX) for name in threads), threads


@pytest.mark.parametrize("workers", [0, -1])
def test_a_store_needs_at_least_one_io_thread(tmp_path: Path, workers: int) -> None:
    root = tmp_path / "attachments"
    with pytest.raises(ValueError):
        FilesystemAttachmentStore(root, io_workers=workers)
    assert not root.exists()


def test_shutdown_closes_the_cached_store_after_the_reaper_and_builds_none(tmp_path: Path) -> None:
    from probos.routers import chat as chat_router

    runtime = SimpleNamespace()
    shutdown_module._close_attachment_store(runtime)  # nothing cached: nothing built, the close point recorded
    assert not isinstance(chat_router._ATTACHMENT_STORE_CACHE.get(id(runtime)), FilesystemAttachmentStore)
    assert not (tmp_path / "attachments").exists()

    store = FilesystemAttachmentStore(tmp_path / "attachments")
    other = SimpleNamespace()
    chat_router._ATTACHMENT_STORE_CACHE[id(runtime)] = store
    chat_router._ATTACHMENT_STORE_CACHE[id(other)] = SimpleNamespace()  # a test double: left alone
    try:
        shutdown_module._close_attachment_store(runtime)
        shutdown_module._close_attachment_store(other)
        assert store.io_closed is True
        assert chat_router._ATTACHMENT_STORE_CACHE[id(runtime)] is store  # kept: one store per root
    finally:
        chat_router._ATTACHMENT_STORE_CACHE.pop(id(runtime), None)
        chat_router._ATTACHMENT_STORE_CACHE.pop(id(other), None)

    tree = ast.parse(textwrap.dedent(inspect.getsource(shutdown_module.shutdown)))

    def _first_line(match) -> int:
        return min(node.lineno for node in ast.walk(tree) if isinstance(node, ast.Call) and match(node))

    reaper_stop = _first_line(
        lambda n: isinstance(n.func, ast.Attribute) and n.func.attr == "stop"
        and ast.unparse(n.func.value) == "runtime.attachment_reaper"
    )
    store_close = _first_line(lambda n: isinstance(n.func, ast.Name) and n.func.id == "_close_attachment_store")
    assert reaper_stop < store_close


def test_a_store_first_built_after_the_close_point_is_born_closed(tmp_path: Path, monkeypatch) -> None:
    """Review round 1, finding 4: shutdown passed its close point before any store was built, and a
    request accepted earlier builds one afterwards. That store is closed before it is returned."""
    from probos.routers import chat as chat_router

    root = tmp_path / "attachments"
    monkeypatch.setattr("probos.attachments.store._resolve_attachments_dir", lambda configured: root)
    runtime = SimpleNamespace(config=SimpleNamespace(attachments=SimpleNamespace(attachments_dir="attachments")))
    try:
        shutdown_module._close_attachment_store(runtime)
        assert not root.exists()  # the closer built nothing
        store = chat_router._get_attachment_store(runtime)
        assert isinstance(store, FilesystemAttachmentStore) and store.io_closed is True
        assert chat_router._get_attachment_store(runtime) is store  # one store per root
    finally:
        chat_router._ATTACHMENT_STORE_CACHE.pop(id(runtime), None)


_SAVE_SITES = ("write", "unlink", "unlink_if_unchanged")


@pytest.mark.parametrize("closed", [False, True], ids=["own-threads", "closed"])
@pytest.mark.parametrize("site", _SAVE_SITES)
@pytest.mark.asyncio
async def test_a_cancelled_caller_keeps_the_lock_until_its_index_save_finishes(
    tmp_path: Path, monkeypatch, site: str, closed: bool
) -> None:
    """Review round 1, finding 1: cancelling a caller while its index save runs (the reaper's stop
    cancels its sweep) neither releases the lock nor ends the caller before that save has ended, even
    when it is cancelled twice. The file on disk then holds what the caller left in memory."""
    root = tmp_path / "attachments"
    store = FilesystemAttachmentStore(root)
    blob, h = _blob(b"s")
    await store.write(h, blob, "image/png", origin="perception_frame")
    [(_, written_at)] = await store.list_by_origin("perception_frame")
    if closed:
        store.close()
    gate = _Gate(FilesystemAttachmentStore._save_index_sync)
    monkeypatch.setattr(FilesystemAttachmentStore, "_save_index_sync", lambda self: gate(self))
    operations = {
        "write": lambda: store.write(h, blob, "image/png", origin="agent_artifact"),
        "unlink": lambda: store.unlink(h),
        "unlink_if_unchanged": lambda: store.unlink_if_unchanged(
            h, origin="perception_frame", written_at=written_at
        ),
    }
    task = asyncio.create_task(operations[site]())
    ended_after_save: list[bool] = []
    task.add_done_callback(lambda _task: ended_after_save.append(gate.finished.is_set()))
    try:
        assert await asyncio.to_thread(gate.entered.wait, 5)
        task.cancel()
        await _turns()
        task.cancel()  # cancelled again while it waits
        await _turns()
        contender = asyncio.create_task(store.list_by_origin("agent_artifact"))
        await _turns()
        assert not task.done() and not contender.done()  # the caller still holds the lock
    finally:
        gate.release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert ended_after_save == [True]
    in_memory = await contender
    reopened = FilesystemAttachmentStore(root)
    assert await reopened.list_by_origin("agent_artifact") == in_memory
    assert await reopened.list_by_origin("perception_frame") == await store.list_by_origin("perception_frame")


@pytest.mark.asyncio
async def test_a_cancelled_blob_write_keeps_the_lock_until_the_bytes_are_written(tmp_path: Path, monkeypatch) -> None:
    """Review round 1, finding 1: a write cancelled during its blob write keeps the lock until the bytes
    are on disk, so a second write of the same hash cannot find a partly written file and skip its own."""
    store = FilesystemAttachmentStore(tmp_path / "attachments")
    gate = _Gate(Path.write_bytes)
    monkeypatch.setattr(Path, "write_bytes", lambda self, data: gate(self, data))
    blob, h = _blob(b"p")
    first = asyncio.create_task(store.write(h, blob, "image/png", origin="perception_frame"))
    try:
        assert await asyncio.to_thread(gate.entered.wait, 5)
        first.cancel()
        await _turns()
        second = asyncio.create_task(store.write(h, blob, "image/png", origin="agent_artifact"))
        await _turns()
        assert not first.done() and not second.done()  # the cancelled write still holds the lock
    finally:
        gate.release.set()
    with pytest.raises(asyncio.CancelledError):
        await first
    assert (await second).read_bytes() == blob
    assert [sha for sha, _ in await store.list_by_origin("agent_artifact")] == [h]


@pytest.mark.asyncio
async def test_the_reapers_stop_returns_only_after_its_cancelled_save_has_finished(tmp_path: Path, monkeypatch) -> None:
    """Review round 1, finding 1, across the seam: shutdown's ``AttachmentReaper.stop()`` cancels a sweep
    whose index save is running. It returns once that save has ended, with the sweep's removal on disk."""
    from probos.attachments.reaper import AttachmentReaper
    from probos.config import AttachmentsConfig, PerceptionConfig

    root = tmp_path / "attachments"
    store = FilesystemAttachmentStore(root)
    blob, h = _blob(b"r")
    await store.write(h, blob, "image/png", origin="perception_frame")
    async with store._lock:  # noqa: SLF001 -- force-age, as tests/test_attachment_reaper.py does
        store._index[h]["written_at"] -= 3600  # noqa: SLF001
    gate = _Gate(FilesystemAttachmentStore._save_index_sync)
    monkeypatch.setattr(FilesystemAttachmentStore, "_save_index_sync", lambda self: gate(self))
    reaper = AttachmentReaper(
        store,
        perception_cfg=PerceptionConfig(enabled=True, frame_retention_seconds=30, reaper_interval_seconds=60),
        attachments_cfg=AttachmentsConfig(max_store_bytes=0),
    )
    await reaper.start()  # its first sweep starts at once
    try:
        assert await asyncio.to_thread(gate.entered.wait, 5)  # the sweep's removal is saving the index
        stop = asyncio.create_task(reaper.stop())
        await _turns()
        assert not stop.done()  # stop() waits for the save its cancellation interrupted
    finally:
        gate.release.set()
    await stop
    assert gate.finished.is_set()
    assert await FilesystemAttachmentStore(root).list_by_origin("perception_frame") == []


@pytest.mark.asyncio
async def test_a_call_that_fails_after_its_caller_was_cancelled_is_logged(tmp_path: Path, monkeypatch, caplog) -> None:
    """Review round 1, finding 1: the caller ends cancelled, and the error its call raised afterwards is logged."""
    store = FilesystemAttachmentStore(tmp_path / "attachments")
    gate = _Gate(Path.write_bytes, fail=OSError(errno.EIO, "injected"))
    monkeypatch.setattr(Path, "write_bytes", lambda self, data: gate(self, data))
    caplog.set_level(logging.WARNING, logger="probos.attachments.filesystem_store")
    blob, h = _blob(b"e")
    task = asyncio.create_task(store.write(h, blob, "image/png"))
    try:
        assert await asyncio.to_thread(gate.entered.wait, 5)
        task.cancel()
        await _turns()
    finally:
        gate.release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert any("after its caller was cancelled" in record.getMessage() for record in caplog.records)


@pytest.mark.parametrize("closed", [False, True], ids=["own-threads", "closed"])
def test_loop_teardown_keeps_the_lock_until_the_interrupted_save_ends(
    tmp_path: Path, monkeypatch, closed: bool
) -> None:
    """Review round 2, finding 1: ``asyncio.run``'s teardown (``Runner.close()``) cancels every task, and
    another task's cleanup still writes to the store while those cancellations unwind. The caller whose
    index save it interrupted keeps the lock until that save has ended, open or closed, so the cleanup's
    durable upgrade is saved after it and survives a reopen and the real reaper. A plain function: the
    Runner owns its loop."""
    from probos.attachments.reaper import AttachmentReaper
    from probos.config import AttachmentsConfig, PerceptionConfig

    root = tmp_path / "attachments"
    store = FilesystemAttachmentStore(root)
    frame, h_frame = _blob(b"f")
    artifact, h_artifact = _blob(b"g")
    entered, release, finished = threading.Event(), threading.Event(), threading.Event()
    claimed: list[bool] = []
    claim = threading.Lock()
    errors: list[str] = []
    states: dict[str, bool] = {}
    pending: list[asyncio.Task[None]] = []
    real_dump = json.dump
    artifact_key = json.dumps(h_artifact)

    class _PausedFile:
        """The first save's file: it pauses after the frame's entry, before the artifact's key."""

        def __init__(self, file) -> None:
            self._file = file

        def write(self, chunk: str) -> int:
            if chunk == artifact_key and not entered.is_set():
                entered.set()
                release.wait(10)
            return self._file.write(chunk)

    def dump(value, file, *args, **kwargs) -> None:
        with claim:
            first = not claimed
            claimed.append(True)
        try:
            real_dump(value, _PausedFile(file) if first else file, *args, **kwargs)
        except BaseException as error:
            errors.append(repr(error))
            raise
        finally:
            if first:
                finished.set()

    async def main() -> None:
        await store.write(h_frame, frame, "image/png", origin="perception_frame")
        await store.write(h_artifact, artifact, "image/png", origin="agent_artifact")
        if closed:
            store.close()
        monkeypatch.setattr(json, "dump", dump)
        interrupted = asyncio.create_task(store.write(h_artifact, artifact, "image/png", origin="agent_artifact"))
        assert await asyncio.to_thread(entered.wait, 5)  # its index save has written the frame's entry

        async def cleanup_writer() -> None:
            try:
                await asyncio.Event().wait()  # pending until the teardown cancels it
            finally:
                await _turns(60)  # the teardown's other cancellations unwind
                states["caller_pending"] = not interrupted.done()
                states["save_running"] = not finished.is_set()
                try:
                    if not interrupted.done():
                        release.set()  # the save may end; this write waits for the lock
                    await store.write(h_frame, frame, "image/png", origin="agent_artifact")
                    states["acknowledged_while_save_ran"] = not finished.is_set()
                finally:
                    release.set()

        pending.extend((interrupted, asyncio.create_task(cleanup_writer())))
        await _turns(3)
        assert not any(task.done() for task in pending)

    try:
        with asyncio.Runner() as runner:
            runner.run(main())  # returns with both tasks pending; leaving the block tears the loop down
    finally:
        release.set()
    assert states == {"caller_pending": True, "save_running": True, "acknowledged_while_save_ran": False}, states
    assert finished.is_set() and errors == [] and pending[0].cancelled()

    async def reopen_and_reap() -> tuple[list[str], bool]:
        recovered = FilesystemAttachmentStore(root)
        reaper = AttachmentReaper(
            recovered,
            perception_cfg=PerceptionConfig(enabled=True, reaper_interval_seconds=60),
            attachments_cfg=AttachmentsConfig(max_store_bytes=1),  # the LRU pass removes all but agent_artifact
        )
        await reaper.sweep_once()
        durable = [sha for sha, _ in await recovered.list_by_origin("agent_artifact")]
        return durable, await recovered.exists(h_frame)

    durable, kept = asyncio.run(reopen_and_reap())
    assert h_frame in durable and kept
