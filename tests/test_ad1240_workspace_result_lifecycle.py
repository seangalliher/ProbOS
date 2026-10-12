"""AD-1240: hourly-generation retention, the integrity latch and I/O drainage.

Every clock here is injected and every retry sleep is a recorder: no test waits
on the wall clock. Premises are asserted before the outcome they gate, so a
setup that did not reach its boundary fails loudly instead of passing quietly.
"""

from __future__ import annotations

import ast
import asyncio
import calendar
import dataclasses
import errno
import hashlib
import json
import logging
import os
import shutil
import stat
import sys
import threading
from collections.abc import Callable
from contextlib import contextmanager
from pathlib import Path, PureWindowsPath
from types import SimpleNamespace
from typing import Any

import pytest

import probos.execution.workspace_result_store as store_module
import probos.startup.infrastructure as infrastructure_module
import probos.startup.shutdown as shutdown_module
from probos.cognitive.yeoman import YeomanAgent
from probos.config import MemoryConfig, SystemConfig
from probos.execution.workspace import WorkspaceManager
from probos.execution.workspace_result_store import (
    CommittedArtifacts,
    GenerationReaper,
    RetryPolicy,
    WorkspaceResultStore,
    classify_os_error,
)
from probos.execution.workspace_results import (
    GENERATION_NAME_RE,
    GENERATION_SECONDS,
    RESULT_DIRECTORY,
    RESULT_RETENTION_SECONDS,
    AgentWorkspace,
    CanonicalCapture,
    UnavailableWorkspaceResults,
    WorkspaceReapResult,
    WorkspaceResultError,
    WorkspaceResultRef,
    generation_expiry,
    generation_name,
    generation_start,
)
from probos.identity import AgentIdentityRegistry
from probos.runtime import ProbOSRuntime
from probos.security.file_access import FileAccessDenied, PinnedDirectory, is_reparse_point
from probos.startup.infrastructure import boot_infrastructure
from probos.startup.results import InfrastructureResult
from tests.fixtures.runtime_factory import make_runtime, started_runtime
from tests.fixtures.runtime_lifecycle import (
    NOTHING_LEFT,
    BareRuntime,
    InjectedStartFailure,
    LifecycleBaseline,
    SqliteTracker,
    inject_start_failure,
    lifecycle_config,
)
from tests.test_ad1240_tool_result_delivery import _assert_provenance
from tests.test_ad1240_workspace_results import (  # noqa: F401  (_candidate_provenance registers the session fixture)
    GEN,
    GEN_START,
    T0,
    StoreHarness,
    _agent,
    _candidate_provenance,
    _capture,
    _make_junction,
    _make_symlink,
    _remove_alias,
    generation_of,
    make_store,
    transient_error,
)


def expiry_of(name: str) -> float:
    """end(G) + R, written out from the constants.

    Deliberately not ``generation_expiry``: the sweep-timing assertions below
    must keep their own clock if the function under test is wrong.
    """
    return generation_start(name) + GENERATION_SECONDS + RESULT_RETENTION_SECONDS


EXPIRY = expiry_of(GEN)  # the first instant the generation may be removed
ESCALATION = EXPIRY + RESULT_RETENTION_SECONDS  # end(G) + 2R


async def _running(
    owned: Path, *, clock: float = T0, retry: RetryPolicy | None = None,
) -> tuple[StoreHarness, AgentWorkspace]:
    harness = make_store(owned / "workspaces", clock=clock, retry=retry)
    binding = harness.store.bind_agent("agent-a", _agent())
    await harness.store.start()
    return harness, binding


async def _retention_pair(
    owned: Path,
) -> tuple[StoreHarness, AgentWorkspace, WorkspaceResultRef, WorkspaceResultRef]:
    """An artifact in ``GEN`` and a live one two hours later; the clock ends at ``GEN``'s expiry."""
    _assert_provenance()
    assert owned.is_absolute()
    harness, binding = await _running(owned)
    try:
        expired = await harness.store.store_tool_result(binding, _capture("expired original"))
        harness.clock[0] = T0 + 7200.0
        live = await harness.store.store_tool_result(binding, _capture("valid retained body"))
        harness.clock[0] = EXPIRY
        assert generation_of(expired.path) == GEN and generation_of(live.path) != GEN
        assert harness.clock[0] < live.expires_at
        return harness, binding, expired, live
    except BaseException:
        await harness.store.stop()
        raise


async def _entered(event: threading.Event) -> None:
    assert await asyncio.to_thread(event.wait, 10), "the owned worker never reached its hook"


class _FailingRemoval:
    """Make ``PinnedDirectory.remove_file`` fail for one leaf name.

    ``failures=None`` fails every call while ``broken``; an integer fails that
    many calls and then delegates to the real remover.
    """

    def __init__(
        self, monkeypatch: pytest.MonkeyPatch, error: Callable[[], Exception], *,
        name: str = "payload.jsonl", failures: int | None = None,
    ) -> None:
        self.calls = 0
        self.broken = True
        original = PinnedDirectory.remove_file

        def remove(directory: PinnedDirectory, leaf: str) -> None:
            if self.broken and leaf == name and (failures is None or self.calls < failures):
                self.calls += 1
                raise error()
            original(directory, leaf)

        monkeypatch.setattr(PinnedDirectory, "remove_file", remove)


def _artifact_dir(reference: WorkspaceResultRef) -> Path:
    return Path(reference.path).parent


def _generation_dir(reference: WorkspaceResultRef) -> Path:
    return Path(reference.path).parents[2]


def _namespace_dir(reference: WorkspaceResultRef) -> Path:
    return Path(reference.path).parents[3]


def _recording_instances(monkeypatch: pytest.MonkeyPatch, name: str) -> list[Any]:
    """Record every ``store_module.<name>`` the store builds from now on.

    The harness does not expose the store's collaborators, so a test that needs
    one patches in a recording subclass before it constructs the store and then
    reads it through its public methods.
    """
    real = getattr(store_module, name)
    built: list[Any] = []

    class _Recording(real):  # type: ignore[misc, valid-type]
        def __init__(self) -> None:
            super().__init__()
            built.append(self)

    monkeypatch.setattr(store_module, name, _Recording)
    return built


def _rewrite_artifact(
    reference: WorkspaceResultRef, replacement: CanonicalCapture, *, committed_at: float | None = None,
) -> None:
    """Overwrite an artifact's payload, outline and manifest, as a same-user process outside ProbOS could.

    Afterwards the three files agree with one another (digest, sizes and outline
    hash), so only a record of what ProbOS itself committed can tell the rewrite
    from the original.
    """
    artifact = _artifact_dir(reference)
    (artifact / "payload.jsonl").write_bytes((json.dumps(replacement.text) + "\n").encode("ascii"))
    (artifact / "outline.json").write_bytes(replacement.outline.encode("ascii"))
    manifest = json.loads((artifact / "manifest.json").read_bytes())
    manifest.update(
        sha256=replacement.sha256, source_chars=replacement.source_chars,
        utf8_bytes=replacement.utf8_bytes,
        outline_sha256=hashlib.sha256(replacement.outline.encode("ascii")).hexdigest(),
    )
    if committed_at is not None:
        manifest["committed_at"] = committed_at
    (artifact / "manifest.json").write_text(json.dumps(manifest), encoding="ascii")


def _files_agree(reference: WorkspaceResultRef, replacement: CanonicalCapture) -> bool:
    """True when payload, outline and manifest on disk agree with one another and with ``replacement``."""
    artifact = _artifact_dir(reference)
    manifest = json.loads((artifact / "manifest.json").read_bytes())
    text = json.loads((artifact / "payload.jsonl").read_bytes())
    return (
        text == replacement.text
        and hashlib.sha256(text.encode("utf-8")).hexdigest() == manifest["sha256"]
        and len(text) == manifest["source_chars"] and len(text.encode("utf-8")) == manifest["utf8_bytes"]
        and hashlib.sha256((artifact / "outline.json").read_bytes()).hexdigest() == manifest["outline_sha256"]
    )


class _Busy:
    """A transient failure injected at one pin or one listing; ``on`` switches it off."""

    def __init__(self) -> None:
        self.on = True
        self.hits: list[Path] = []
        self.seen = 0


def _busy_pin(
    monkeypatch: pytest.MonkeyPatch, target: Path, *, after: int = 0,
    error: Callable[[], Exception] = lambda: transient_error(),
) -> _Busy:
    """Fail ``store_module.pin_directory(target)`` with ``error()``, from its ``after`` + 1-th call on."""
    real_pin = store_module.pin_directory
    busy = _Busy()

    @contextmanager
    def pinning(path: Path, **kwargs: Any) -> Any:
        if path == target:
            busy.seen += 1
            if busy.on and busy.seen > after:
                busy.hits.append(path)
                raise error()
        with real_pin(path, **kwargs) as opened:
            yield opened

    monkeypatch.setattr(store_module, "pin_directory", pinning)
    return busy


def _busy_listing(
    monkeypatch: pytest.MonkeyPatch, target: Path, *, error: Callable[[], Exception] = lambda: transient_error(),
) -> _Busy:
    """Fail ``PinnedDirectory.list_names`` with ``error()`` for the pin of ``target``."""
    real_names = PinnedDirectory.list_names
    busy = _Busy()

    def listing(directory: PinnedDirectory) -> tuple[str, ...]:
        if busy.on and directory.path == target:
            busy.hits.append(target)
            raise error()
        return real_names(directory)

    monkeypatch.setattr(PinnedDirectory, "list_names", listing)
    return busy


def _busy_exit(
    monkeypatch: pytest.MonkeyPatch, target: Path, *, after: int = 0, failures: int = 1,
) -> _Busy:
    """Fail the closing check of a pin of ``target``, after the real context has exited.

    The (``after`` + 1)-th pin of ``target``, and the ``failures`` - 1 after it, are
    entered, used and verified for real; only then does the context raise
    ``transient_error()``. The failure arrives at the context exit, where whatever
    ran inside the pin has already run and can be run again only by whoever retries
    the whole pin. ``busy.seen`` counts every pin of ``target``, failed or not.
    """
    real_pin = store_module.pin_directory
    busy = _Busy()

    @contextmanager
    def pinning(path: Path, **kwargs: Any) -> Any:
        number = 0
        if path == target:
            busy.seen += 1
            number = busy.seen
        with real_pin(path, **kwargs) as opened:
            yield opened
        if busy.on and after < number <= after + failures:
            busy.hits.append(path)
            raise transient_error()

    monkeypatch.setattr(store_module, "pin_directory", pinning)
    return busy


@pytest.mark.asyncio
async def test_logical_expiry_at_24h_physical_at_generation_end(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness, binding = await _running(tmp_path)
    store, clock = harness.store, harness.clock
    text = "retained" * 2000
    try:
        reference = await store.store_tool_result(binding, _capture(text))
        payload = Path(reference.path)
        # Premise: committed mid-hour, so logical (committed + R) and physical (end + R) expiry differ.
        assert generation_of(reference.path) == GEN and reference.committed_at == T0 == GEN_START + 1800.0
        assert reference.expires_at == T0 + RESULT_RETENTION_SECONDS < EXPIRY and payload.is_file()
        names_read: list[str] = []
        original = PinnedDirectory.read_bytes

        def recording(directory: PinnedDirectory, name: str, *, max_bytes: int | None = None) -> Any:
            names_read.append(name)
            return original(directory, name, max_bytes=max_bytes)

        monkeypatch.setattr(PinnedDirectory, "read_bytes", recording)
        clock[0] = reference.expires_at - 0.001
        assert (await store.read_tool_result_slice(binding, reference.path, 3, 99)).text == text[3:102]
        assert "payload.jsonl" in names_read
        names_read.clear()
        clock[0] = reference.expires_at
        with pytest.raises(WorkspaceResultError, match="result_expired"):
            await store.read_tool_result_slice(binding, reference.path, 0, 1)
        assert "payload.jsonl" not in names_read, "the exact-expiry refusal precedes the payload read"
        assert payload.exists(), "expiry is logical before a due sweep removes anything"
        assert await store.reap_tool_results() == WorkspaceReapResult()
        assert payload.exists()
        clock[0] = EXPIRY - 0.001
        assert await store.reap_tool_results() == WorkspaceReapResult()
        assert payload.exists()
        clock[0] = EXPIRY
        names_read.clear()
        with pytest.raises(WorkspaceResultError, match="result_expired"):
            await store.read_tool_result_slice(binding, reference.path, 0, 1)
        assert names_read == [], "at the generation's own expiry the refusal precedes every read"
        assert (await store.reap_tool_results()).deleted == 1
        assert not _generation_dir(reference).exists()
        assert (await store.reap_tool_results()) == WorkspaceReapResult()
        assert harness.sleeps == [], "no retry sleep and no wall-clock wait anywhere"
    finally:
        await store.stop()


@pytest.mark.asyncio
async def test_expired_generation_read_refuses_before_any_io(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness, binding = await _running(tmp_path)
    store, clock = harness.store, harness.clock
    pins: list[Path] = []
    real_pin = store_module.pin_directory

    @contextmanager
    def recording_pin(path: Path, **kwargs: Any) -> Any:
        pins.append(path)
        with real_pin(path, **kwargs) as opened:
            yield opened

    monkeypatch.setattr(store_module, "pin_directory", recording_pin)
    try:
        reference = await store.store_tool_result(binding, _capture("body" * 4000))
        pins.clear()
        # Premise: the recorder sees a pin for an ordinary, unexpired read.
        assert (await store.read_tool_result_slice(binding, reference.path, 0, 4)).text == "body"
        assert pins, "the recorder must observe the filesystem authority of a normal read"
        pins.clear()
        clock[0] = EXPIRY
        assert Path(reference.path).is_file() and clock[0] >= reference.expires_at
        with pytest.raises(WorkspaceResultError, match="result_expired"):
            await store.read_tool_result_slice(binding, reference.path, 0, 4)
        assert pins == [], "an expired generation is refused before any directory is opened"
    finally:
        await store.stop()


@pytest.mark.asyncio
async def test_unexpired_generation_never_reaped(tmp_path: Path) -> None:
    harness, binding = await _running(tmp_path)
    store, clock = harness.store, harness.clock
    try:
        reference = await store.store_tool_result(binding, _capture("original"))
        tampered = b'"user replacement"\n'
        Path(reference.path).write_bytes(tampered)
        assert Path(reference.path).read_bytes() == tampered
        for moment in (
            T0, reference.expires_at - 0.001, reference.expires_at,
            GEN_START + GENERATION_SECONDS, EXPIRY - 0.001,
        ):
            clock[0] = moment
            assert moment < EXPIRY
            assert await store.reap_tool_results() == WorkspaceReapResult(), moment
            assert Path(reference.path).read_bytes() == tampered
            assert _generation_dir(reference).is_dir()
        # Before the generation even begins its name is a future name: kept, not aged.
        clock[0] = GEN_START - 1.0
        assert await store.reap_tool_results() == WorkspaceReapResult(skipped=1)
        assert Path(reference.path).read_bytes() == tampered
        clock[0] = T0
        with pytest.raises(WorkspaceResultError, match="payload_changed"):
            await store.read_tool_result_slice(binding, reference.path, 0, 4)
        clock[0] = reference.expires_at
        with pytest.raises(WorkspaceResultError, match="result_expired"):
            await store.read_tool_result_slice(binding, reference.path, 0, 4)
    finally:
        await store.stop()


@pytest.mark.asyncio
async def test_queued_sweep_after_clock_rollback_never_deletes_a_new_commit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """F1: a sweep samples the store clock only once it holds the serializing lock.

    Port of the reviewer's ``queued-clock`` probe. The publication is paused with
    the lock held, the clock is advanced to the generation's expiry and a sweep is
    queued behind the publication; the clock is rolled back before the
    publication is released. A sweep that had sampled the clock while it waited
    would delete a commit made at its own ``committed_at``.
    """
    _assert_provenance()
    assert tmp_path.is_absolute()
    clock = [T0]
    reads: list[float] = []
    sleeps: list[float] = []
    tasks: list[asyncio.Task[None]] = []

    def recording_clock() -> float:
        reads.append(clock[0])
        return clock[0]

    store = WorkspaceResultStore(
        WorkspaceManager(tmp_path / "workspaces"), clock=recording_clock,
        background_register=tasks.append, sleep=sleeps.append,
    )
    binding = store.bind_agent("agent-a", _agent())
    await store.start()
    staged, release = threading.Event(), threading.Event()
    write_new = PinnedDirectory.write_new

    def pausing(directory: PinnedDirectory, name: str, data: bytes) -> None:
        write_new(directory, name, data)
        if name == "outline.json":
            staged.set()
            assert release.wait(10), "the paused publication was never released"

    monkeypatch.setattr(PinnedDirectory, "write_new", pausing)
    publication = asyncio.create_task(store.store_tool_result(binding, _capture("original text")))
    sweep: asyncio.Task[WorkspaceReapResult] | None = None
    try:
        await _entered(staged)
        # Premise 1: the publication is paused mid-commit (no manifest yet), holding the lock.
        assert not publication.done() and list(store.root.rglob("manifest.json")) == []
        clock[0] = EXPIRY
        reads.clear()
        sweep = asyncio.create_task(store.reap_tool_results())
        await asyncio.sleep(0)
        # Premise 2: the sweep is queued behind the publication and has not sampled the clock.
        assert not sweep.done() and reads == [], "the sweep must not read the clock before it holds the lock"
        clock[0] = T0
        release.set()
        reference = await publication
        outcome = await sweep
    finally:
        release.set()
        await asyncio.gather(*(task for task in (publication, sweep) if task is not None), return_exceptions=True)
    try:
        assert reference.committed_at == T0 and generation_of(reference.path) == GEN
        assert reference.committed_at < reference.expires_at and clock[0] < reference.expires_at
        assert outcome == WorkspaceReapResult(), "a sweep at the rolled-back clock deletes nothing"
        assert Path(reference.path).is_file()
        assert (await store.read_tool_result_slice(binding, reference.path, None, None)).text == "original text"
    finally:
        await store.stop()


@pytest.mark.asyncio
async def test_documented_outside_write_in_expired_generation_is_removed(tmp_path: Path) -> None:
    """Once a generation's retention has expired, the reaper removes the whole generation, including any file that a process outside ProbOS wrote or substituted inside it; the sweep counts the generation as deleted, reports failed=0, and does not latch publication."""
    _assert_provenance()
    harness, binding = await _running(tmp_path)
    store, clock = harness.store, harness.clock
    try:
        reference = await store.store_tool_result(binding, _capture("original" * 100))
        payload = Path(reference.path)
        sentinel = b"OUTSIDE_PROCESS_SENTINEL\n"
        payload.write_bytes(sentinel)
        note = payload.with_name("user-note.txt")
        note.write_bytes(b"a note the process outside ProbOS added")
        assert payload.read_bytes() == sentinel and note.is_file()
        clock[0] = EXPIRY
        outcome = await store.reap_tool_results()
        assert not _generation_dir(reference).exists()
        assert outcome.deleted == 1 and outcome.failed == 0 and outcome.deferred == 0
        reference_after = await store.store_tool_result(binding, _capture("accepted after the sweep"))
        assert generation_of(reference_after.path) != GEN
        assert harness.sleeps == []
    finally:
        await store.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize("position", ["digest", "artifact"])
@pytest.mark.parametrize("kind", [
    pytest.param("junction", marks=pytest.mark.skipif(
        sys.platform != "win32", reason="AD-1240: a junction is Windows-only")),
    pytest.param("symlink", marks=pytest.mark.skipif(
        sys.platform == "win32", reason="AD-1240: an unprivileged directory symlink is a POSIX premise")),
])
async def test_link_in_expired_generation_is_not_followed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kind: str, position: str,
) -> None:
    _assert_provenance()
    harness, binding = await _running(tmp_path)
    store, clock = harness.store, harness.clock
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "sentinel.txt").write_bytes(b"outside sentinel")
    link: Path | None = None
    attempts: list[str] = []
    real_pin = store_module.pin_directory
    real_remove_file = PinnedDirectory.remove_file
    real_remove_directory = PinnedDirectory.remove_directory

    @contextmanager
    def recording_pin(path: Path, **kwargs: Any) -> Any:
        attempts.append(f"pin:{path.name}")
        with real_pin(path, **kwargs) as opened:
            yield opened

    def recording_remove_file(directory: PinnedDirectory, name: str) -> None:
        attempts.append(f"remove_file:{name}")
        real_remove_file(directory, name)

    def recording_remove_directory(directory: PinnedDirectory, name: str) -> None:
        attempts.append(f"remove_directory:{name}")
        real_remove_directory(directory, name)

    try:
        reference = await store.store_tool_result(binding, _capture("body" * 500))
        parent = _artifact_dir(reference) if position == "artifact" else _artifact_dir(reference).parent
        link = parent / "link"
        (_make_junction if kind == "junction" else _make_symlink)(link, outside)
        # Premise: a real link whose resolution leaves the generation.
        assert (link.is_junction() if kind == "junction" else link.is_symlink())
        assert link.resolve() == outside.resolve() and (link / "sentinel.txt").is_file()
        monkeypatch.setattr(store_module, "pin_directory", recording_pin)
        monkeypatch.setattr(PinnedDirectory, "remove_file", recording_remove_file)
        monkeypatch.setattr(PinnedDirectory, "remove_directory", recording_remove_directory)
        clock[0] = EXPIRY
        outcome = await store.reap_tool_results()
        assert "remove_file:payload.jsonl" in attempts, "premise: the recorder saw the sweep remove ordinary entries"
        assert not [attempt for attempt in attempts if attempt.endswith(":link")], (
            "the link is never opened, followed or removed"
        )
        assert (outside / "sentinel.txt").read_bytes() == b"outside sentinel"
        assert (link.is_junction() if kind == "junction" else link.is_symlink()), "the link is left in place"
        assert outcome.skipped >= 1 and outcome.failed == 0 and outcome.deleted == 0
        assert _generation_dir(reference).is_dir(), "the generation that holds a link is retained"
        assert not Path(reference.path).exists(), "everything the reaper could remove below the link was removed"
        await store.store_tool_result(binding, _capture("publication stays admitted"))
    finally:
        if link is not None and (link.is_symlink() or link.exists()):
            _remove_alias(link)
        await store.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["file", "directory"])
async def test_link_in_expired_generation_is_not_followed_injected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kind: str,
) -> None:
    harness, binding = await _running(tmp_path)
    store, clock = harness.store, harness.clock
    try:
        reference = await store.store_tool_result(binding, _capture("body" * 500))
        entry = _artifact_dir(reference) / "reported-as-link"
        if kind == "file":
            entry.write_bytes(b"ordinary file")
        else:
            entry.mkdir()
            (entry / "inner.txt").write_bytes(b"ordinary inner file")
        info = entry.lstat()
        flagged = (info.st_dev, info.st_ino)
        assert not entry.is_symlink() and not (hasattr(entry, "is_junction") and entry.is_junction())
        real = store_module.is_reparse_point
        hits: list[tuple[int, int]] = []

        def reported(stat_result: os.stat_result) -> bool:
            if (stat_result.st_dev, stat_result.st_ino) == flagged:
                hits.append(flagged)
                return True
            return real(stat_result)

        monkeypatch.setattr(store_module, "is_reparse_point", reported)
        clock[0] = EXPIRY
        outcome = await store.reap_tool_results()
        assert hits, "the reaper consulted the reparse predicate for the flagged entry"
        assert entry.exists(), "an entry reported as a link is left in place"
        if kind == "directory":
            assert (entry / "inner.txt").read_bytes() == b"ordinary inner file"
        assert outcome.skipped >= 1 and outcome.failed == 0 and outcome.deleted == 0
        assert _generation_dir(reference).is_dir()
        # Foreign material never escalates: long past two retention periods it is still only skipped.
        clock[0] = ESCALATION + 5 * RESULT_RETENTION_SECONDS
        later = await store.reap_tool_results()
        assert later.skipped >= 1 and later.failed == 0 and later.deferred == 0 and later.deleted == 0
        assert entry.exists()
        await store.store_tool_result(binding, _capture("publication stays admitted"))
    finally:
        await store.stop()


def test_is_reparse_point_reports_links_and_never_ordinary_entries(tmp_path: Path) -> None:
    ordinary_file = tmp_path / "ordinary.txt"
    ordinary_file.write_bytes(b"ordinary")
    ordinary_directory = tmp_path / "ordinary"
    ordinary_directory.mkdir()
    assert not is_reparse_point(ordinary_file.lstat())
    assert not is_reparse_point(ordinary_directory.lstat())
    # The two shapes it reports, as duck-typed stat results so both run on any platform.
    assert is_reparse_point(SimpleNamespace(st_mode=stat.S_IFLNK, st_file_attributes=0))
    assert is_reparse_point(SimpleNamespace(st_mode=stat.S_IFDIR, st_file_attributes=0x400))
    assert not is_reparse_point(SimpleNamespace(st_mode=stat.S_IFDIR, st_file_attributes=0x10))
    assert not is_reparse_point(SimpleNamespace(st_mode=stat.S_IFREG))  # POSIX results carry no attributes
    # A real link of the platform's own kind (a junction on Windows, a symlink elsewhere).
    link = tmp_path / "link"
    (_make_junction if sys.platform == "win32" else _make_symlink)(link, ordinary_directory)
    try:
        assert is_reparse_point(link.lstat())
        assert not is_reparse_point(ordinary_directory.lstat())
    finally:
        _remove_alias(link)


@pytest.mark.asyncio
async def test_future_and_unknown_root_entries_are_preserved(tmp_path: Path) -> None:
    harness, binding = await _running(tmp_path)
    store = harness.store
    try:
        reference = await store.store_tool_result(binding, _capture("current generation"))
        namespace = _namespace_dir(reference)
        arabic = "\u0662\u0660\u0662\u0666\u0661\u0660\u0661\u0661T\u0660\u0667Z"
        assert GENERATION_NAME_RE.fullmatch(arabic) is not None, "must reach the round-trip branch"
        preserved: dict[str, bytes | None] = {
            "notes.txt": b"user notes",
            "20261011T07": None,
            "20261399T99Z": None,
            "20261012T05Z": None,  # a valid name whose hour has not begun: a future name
            arabic: None,
        }
        for name, body in preserved.items():
            if body is None:
                (namespace / name).mkdir()
                (namespace / name / "keep.txt").write_bytes(b"kept")
            else:
                (namespace / name).write_bytes(body)
        assert generation_start("20261012T05Z") > T0
        expired = namespace / "20261009T01Z" / "digest" / "artifact"
        expired.mkdir(parents=True)
        (expired / "stale.bin").write_bytes(b"expired generation content")
        assert expiry_of("20261009T01Z") <= T0
        outcome = await store.reap_tool_results()
        assert outcome == WorkspaceReapResult(deleted=1, skipped=len(preserved))
        assert not (namespace / "20261009T01Z").exists()
        for name, body in preserved.items():
            if body is None:
                assert (namespace / name / "keep.txt").read_bytes() == b"kept", name
            else:
                assert (namespace / name).read_bytes() == body, name
        assert Path(reference.path).is_file(), "the unexpired current generation is untouched"
        await store.store_tool_result(binding, _capture("still admitted"))
    finally:
        await store.stop()


@pytest.mark.asyncio
async def test_rollover_mid_publication_commits_in_next_generation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    next_generation = generation_name(GEN_START + GENERATION_SECONDS)
    harness, binding = await _running(tmp_path, clock=GEN_START + 3599.0)
    store, clock = harness.store, harness.clock
    original = PinnedDirectory.write_new
    jumps: list[str] = []

    def hooked(directory: PinnedDirectory, name: str, data: bytes) -> None:
        original(directory, name, data)
        if name == "outline.json" and not jumps:
            jumps.append(name)
            clock[0] = GEN_START + GENERATION_SECONDS + 1.0  # the commit-time reading is in the next hour

    monkeypatch.setattr(PinnedDirectory, "write_new", hooked)
    try:
        text = "crossing the boundary" * 100
        reference = await store.store_tool_result(binding, _capture(text))
        assert jumps == ["outline.json"], "the clock crossed the hour between admission and commit"
        assert generation_of(reference.path) == next_generation != GEN
        committed = generation_start(next_generation)
        assert committed <= reference.committed_at < committed + GENERATION_SECONDS
        assert reference.committed_at == GEN_START + GENERATION_SECONDS + 1.0
        # The first attempt stays in its own generation, unadvertised: no manifest of either name.
        first = _generation_dir(reference).parent / GEN
        stranded = [path for path in first.rglob("*") if path.is_file()]
        assert sorted(path.name for path in stranded) == ["outline.json", "payload.jsonl"]
        assert (await store.read_tool_result_slice(binding, reference.path, 5, 40)).text == text[5:45]
        # Reaping the first generation at its expiry cannot touch the committed one.
        clock[0] = EXPIRY
        assert clock[0] < reference.expires_at, "the committed artifact is still within its retention"
        assert (await store.reap_tool_results()) == WorkspaceReapResult(deleted=1)
        assert not first.exists() and Path(reference.path).is_file()
        assert (await store.read_tool_result_slice(binding, reference.path, 0, 5)).text == text[:5]
        clock[0] = expiry_of(next_generation)
        assert (await store.reap_tool_results()) == WorkspaceReapResult(deleted=1)
    finally:
        await store.stop()


@pytest.mark.asyncio
async def test_second_rollover_is_a_write_failure_and_commits_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness, binding = await _running(tmp_path, clock=GEN_START + 3599.0)
    store, clock = harness.store, harness.clock
    original = PinnedDirectory.write_new
    jumps: list[float] = []

    def hooked(directory: PinnedDirectory, name: str, data: bytes) -> None:
        original(directory, name, data)
        if name == "outline.json":
            clock[0] += GENERATION_SECONDS + 1.0
            jumps.append(clock[0])

    monkeypatch.setattr(PinnedDirectory, "write_new", hooked)
    try:
        with pytest.raises(WorkspaceResultError, match="workspace_write_failed"):
            await store.store_tool_result(binding, _capture("never committed"))
        assert len(jumps) == 2, "exactly one retry: two attempts, two crossings"
        assert list(store.root.rglob("manifest.json")) == []
        assert list(store.root.rglob("manifest.staged")) == []
        monkeypatch.setattr(PinnedDirectory, "write_new", original)
        reference = await store.store_tool_result(binding, _capture("the next publication is admitted"))
        assert (await store.read_tool_result_slice(binding, reference.path, 0, 3)).text == "the"
    finally:
        await store.stop()


@pytest.mark.asyncio
async def test_backward_clock_uses_high_water_generation(tmp_path: Path) -> None:
    harness, binding = await _running(tmp_path)
    store, clock = harness.store, harness.clock
    try:
        first = await store.store_tool_result(binding, _capture("before the clock moved"))
        assert first.committed_at == T0 and generation_of(first.path) == GEN
        for earlier in (GEN_START - 1.0, GEN_START - 7200.0):
            clock[0] = earlier
            # Premise: the injected clock really reads an earlier generation.
            assert generation_name(clock[0]) < GEN
            again = await store.store_tool_result(binding, _capture(f"after the clock moved {earlier}"))
            assert generation_of(again.path) == GEN, "never an earlier generation"
            assert again.committed_at >= first.committed_at == T0
            assert again.expires_at >= first.expires_at, "retention is never shortened"
        clock[0] = T0 + 60.0
        later = await store.store_tool_result(binding, _capture("after the clock recovered"))
        assert later.committed_at == T0 + 60.0 and generation_of(later.path) == GEN
    finally:
        await store.stop()


@pytest.mark.asyncio
async def test_reaped_generation_identities_are_evicted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    caches = _recording_instances(monkeypatch, "DirectoryIdentities")
    harness, binding = await _running(tmp_path)
    store, clock = harness.store, harness.clock
    try:
        first = await store.store_tool_result(binding, _capture("first publication"))
        removed = _generation_dir(first)
        assert removed.is_dir()
        assert len(caches) == 1, "premise: the store built exactly one identity cache"
        [cache] = caches
        # F6 premise: the cache really holds identities under the generation about to be
        # reaped, so "none remain" below cannot pass just because nothing was ever cached.
        assert any(path.is_relative_to(_namespace_dir(first) / GEN) for path in cache.known())
        clock[0] = EXPIRY
        assert (await store.reap_tool_results()).deleted == 1
        assert not removed.exists()
        assert not any(path.is_relative_to(_namespace_dir(first) / GEN) for path in cache.known())
        # The clock reads backwards again; high water keeps the same hour, so the
        # same directory path is created anew. A stale identity cached for it
        # would refuse that as a "previously pinned directory that disappeared".
        clock[0] = T0
        again = await store.store_tool_result(binding, _capture("second publication"))
        assert generation_of(again.path) == GEN and _generation_dir(again) == removed
        assert (await store.read_tool_result_slice(binding, again.path, 0, 6)).text == "second"
    finally:
        await store.stop()


@pytest.mark.parametrize("seconds,name", [
    (0.0, "19700101T00Z"),
    (3599.999, "19700101T00Z"),
    (3600.0, "19700101T01Z"),
    (-1.0, "19691231T23Z"),
    (GEN_START, GEN),
    (GEN_START - 0.001, "20261011T06Z"),
    (GEN_START + 3599.999, GEN),
    (GEN_START + 3600.0, "20261011T08Z"),
    (float(calendar.timegm((2028, 2, 29, 23, 30, 0))), "20280229T23Z"),
    (float(calendar.timegm((2028, 3, 1, 0, 0, 0))), "20280301T00Z"),
    (float(calendar.timegm((2026, 12, 31, 23, 59, 59))), "20261231T23Z"),
    (float(calendar.timegm((2027, 1, 1, 0, 0, 0))), "20270101T00Z"),
])
def test_generation_name_round_trip_and_rejects_noncanonical(seconds: float, name: str) -> None:
    assert generation_name(seconds) == name and len(name) == 12
    assert generation_start(name) == (seconds // 3600) * 3600
    assert generation_name(generation_start(name)) == name
    assert generation_expiry(name) == generation_start(name) + GENERATION_SECONDS + RESULT_RETENTION_SECONDS
    assert (GENERATION_SECONDS, RESULT_RETENTION_SECONDS) == (3600, 86400)
    # Every near-miss spelling of a canonical name is refused, never normalised.
    for spelling in (name.lower(), name[:-1], name + "x", " " + name, name.replace("T", "t"), name + "\n"):
        assert spelling != name
        with pytest.raises(WorkspaceResultError, match="^generation_invalid$"):
            generation_start(spelling)


@pytest.mark.parametrize("name", [
    "", "2026101T07Z", "20261011T7Z", "20261011t07z", "20261011T07", "20261011T0700Z",
    "20261301T07Z", "20261011T24Z", "20260230T01Z", "00000101T00Z", " 20261011T07Z",
    "20261011T07Z\n", "20261011T07Z\x00", "2026-10-11T07Z", "\u0662\u0660\u0662\u0666\u0661\u0660\u0661\u0661T\u0660\u0667Z",
    None, b"20261011T07Z", 20261011,
])
def test_generation_start_rejects_noncanonical_names(name: object) -> None:
    with pytest.raises(WorkspaceResultError, match="^generation_invalid$"):
        generation_start(name)
    with pytest.raises(WorkspaceResultError, match="^generation_invalid$"):
        generation_expiry(name)


@pytest.mark.parametrize("clock", [
    float("nan"), float("inf"), float("-inf"), True, "100", None, 1e300, -1e300, 10 ** 400,
])
def test_generation_name_rejects_invalid_clock_readings(clock: object) -> None:
    with pytest.raises(WorkspaceResultError, match="^clock_invalid$"):
        generation_name(clock)


def _os_error(kind: type[OSError], code: int, *, winerror: int | None = None) -> OSError:
    error = kind(code, "fixture")
    if winerror is not None:
        error.winerror = winerror
    return error


def _posix_cases() -> list[tuple[str, str, Callable[[], BaseException], str]]:
    transient = [name for name in ("EBUSY", "EAGAIN", "ETXTBSY", "ENOTEMPTY") if hasattr(errno, name)]
    integrity = [name for name in ("EACCES", "EPERM", "EROFS", "EIO", "ELOOP", "ENOTDIR") if hasattr(errno, name)]
    cases: list[tuple[str, str, Callable[[], BaseException], str]] = [
        ("linux", "not-found", lambda: FileNotFoundError(errno.ENOENT, "x"), "gone"),
        ("linux", "permission-error", lambda: PermissionError(errno.EACCES, "x"), "integrity"),
        ("linux", "winerror-ignored", lambda: _os_error(OSError, errno.EINVAL, winerror=32), "integrity"),
        ("linux", "access-denied-object", lambda: FileAccessDenied("", "chain"), "integrity"),
        ("linux", "typed-clock", lambda: WorkspaceResultError("clock_invalid"), "integrity"),
        ("linux", "unexpected-type", lambda: RuntimeError("x"), "integrity"),
        ("linux", "no-errno", lambda: OSError("x"), "integrity"),
    ]
    cases += [
        ("linux", f"errno-{name}", (lambda name=name: OSError(getattr(errno, name), "x")), "transient")
        for name in transient
    ]
    cases += [
        ("linux", f"errno-{name}", (lambda name=name: OSError(getattr(errno, name), "x")), "integrity")
        for name in integrity
    ]
    return cases


_CLASSIFY_CASES: list[tuple[str, str, Callable[[], BaseException], str]] = [
    ("win32", "not-found", lambda: FileNotFoundError(errno.ENOENT, "x"), "gone"),
    ("win32", "permission-error", lambda: PermissionError(errno.EACCES, "x"), "transient"),
    *(
        ("win32", f"winerror-{code}", (lambda code=code: _os_error(OSError, errno.EINVAL, winerror=code)), "transient")
        for code in (32, 33, 5, 145, 303)
    ),
    ("win32", "winerror-other", lambda: _os_error(OSError, errno.EINVAL, winerror=1), "integrity"),
    ("win32", "ebusy-without-winerror", lambda: OSError(errno.EBUSY, "x"), "integrity"),
    ("win32", "eio", lambda: OSError(errno.EIO, "x"), "integrity"),
    ("win32", "access-denied-object", lambda: FileAccessDenied("", "chain"), "integrity"),
    ("win32", "typed-clock", lambda: WorkspaceResultError("clock_invalid"), "integrity"),
    ("win32", "unexpected-type", lambda: RuntimeError("x"), "integrity"),
    *_posix_cases(),
]


@pytest.mark.parametrize(
    "platform,build,expected", [pytest.param(p, b, e, id=f"{p}-{label}") for p, label, b, e in _CLASSIFY_CASES],
)
def test_classify_os_error_table(platform: str, build: Callable[[], BaseException], expected: str) -> None:
    assert classify_os_error(build(), platform=platform) == expected


def _forbidden_names(tree: ast.AST) -> list[str]:
    forbidden = {"replace", "rename", "renames", "rmtree", "move"}
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr in forbidden:
            found.append(f"attribute .{node.attr} (line {node.lineno})")
        elif isinstance(node, ast.Name) and node.id in forbidden:
            found.append(f"name {node.id} (line {node.lineno})")
        elif isinstance(node, ast.alias) and node.name.rsplit(".", 1)[-1] in forbidden:
            found.append(f"import {node.name}")
    return found


def test_store_source_never_overwrites_by_rename() -> None:
    for snippet in (
        "os.replace(a, b)", "os.rename(a, b)", "Path(a).replace(b)", "p.rename(b)",
        "shutil.rmtree(p)", "shutil.move(a, b)", "from os import replace", "replace(a, b)",
    ):
        assert _forbidden_names(ast.parse(snippet)), f"the detector must flag: {snippet}"
    source = Path(store_module.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    classes = {node.name for node in ast.walk(tree) if isinstance(node, ast.ClassDef)}
    assert {"WorkspaceResultStore", "GenerationReaper", "ArtifactIO"} <= classes
    assert '.publish_file("manifest.staged", "manifest.json")' in source
    assert _forbidden_names(tree) == []


@pytest.mark.asyncio
async def test_publication_never_overwrites_a_manifest_that_already_exists(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness, binding = await _running(tmp_path)
    store = harness.store
    original = PinnedDirectory.write_new
    planted: list[Path] = []

    def planting(directory: PinnedDirectory, name: str, data: bytes) -> None:
        original(directory, name, data)
        if name == "manifest.staged" and not planted:
            planted.append(directory.path / "manifest.json")
            planted[0].write_bytes(b"outside manifest")

    monkeypatch.setattr(PinnedDirectory, "write_new", planting)
    try:
        with pytest.raises(WorkspaceResultError, match="workspace_write_failed"):
            await store.store_tool_result(binding, _capture("body" * 100))
        assert len(planted) == 1 and planted[0].read_bytes() == b"outside manifest"
        assert planted[0].with_name("manifest.staged").is_file(), "nothing was published or removed"
        reference = await store.store_tool_result(binding, _capture("the next publication is admitted"))
        assert (await store.read_tool_result_slice(binding, reference.path, 0, 3)).text == "the"
    finally:
        await store.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize("failures,sleeps,staged_left,calls", [
    (1, [], False, 1),  # publish_file's own removal fails; the first retried removal succeeds
    (3, [0.05, 0.2], False, 3),
    (99, [0.05, 0.2, 0.5], True, 5),  # the removal inside publish_file plus all four attempts
])
async def test_staged_removal_failure_after_commit_retries_then_leaves_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    failures: int, sleeps: list[float], staged_left: bool, calls: int,
) -> None:
    harness, binding = await _running(tmp_path)
    store = harness.store
    removal = _FailingRemoval(monkeypatch, transient_error, name="manifest.staged", failures=failures)
    try:
        text = "committed despite the staged name" * 50
        reference = await store.store_tool_result(binding, _capture(text))
        assert removal.calls == calls, "premise: the staged removal really failed after the link"
        assert (await store.read_tool_result_slice(binding, reference.path, 0, None)).text == text
        assert harness.sleeps == sleeps
        assert Path(reference.path).with_name("manifest.staged").exists() is staged_left
        # A committed artifact is a success, not a failure: nothing latched.
        await store.store_tool_result(binding, _capture("still admitted"))
    finally:
        removal.broken = False
        await store.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize("failures,sleeps,reads", [
    (2, [0.05, 0.2], True),
    (99, [0.05, 0.2, 0.5], False),
])
async def test_payload_open_retries_only_sharing_violations(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failures: int, sleeps: list[float], reads: bool,
) -> None:
    harness, binding = await _running(tmp_path)
    store = harness.store
    state = {"left": failures}
    original = PinnedDirectory.read_bytes

    def sharing(directory: PinnedDirectory, name: str, *, max_bytes: int | None = None) -> Any:
        if name == "payload.jsonl" and state["left"] > 0:
            state["left"] -= 1
            error = PermissionError(errno.EACCES, "fixture sharing violation")
            error.winerror = 32
            raise error
        return original(directory, name, max_bytes=max_bytes)

    try:
        reference = await store.store_tool_result(binding, _capture("held by a scanner"))
        monkeypatch.setattr(PinnedDirectory, "read_bytes", sharing)
        if reads:
            assert (await store.read_tool_result_slice(binding, reference.path, 0, None)).text == "held by a scanner"
        else:
            with pytest.raises(WorkspaceResultError, match="workspace_read_failed"):
                await store.read_tool_result_slice(binding, reference.path, 0, None)
        assert harness.sleeps == sleeps
    finally:
        await store.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize("winerror", [5, None])
async def test_payload_open_does_not_retry_other_failures(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, winerror: int | None,
) -> None:
    harness, binding = await _running(tmp_path)
    store = harness.store
    original = PinnedDirectory.read_bytes
    calls: list[str] = []

    def failing(directory: PinnedDirectory, name: str, *, max_bytes: int | None = None) -> Any:
        if name == "payload.jsonl":
            calls.append(name)
            error = OSError(errno.EIO, "fixture io failure")
            if winerror is not None:
                error.winerror = winerror
            raise error
        return original(directory, name, max_bytes=max_bytes)

    try:
        reference = await store.store_tool_result(binding, _capture("body"))
        monkeypatch.setattr(PinnedDirectory, "read_bytes", failing)
        with pytest.raises(WorkspaceResultError, match="workspace_read_failed"):
            await store.read_tool_result_slice(binding, reference.path, 0, None)
        assert calls == ["payload.jsonl"] and harness.sleeps == []
    finally:
        await store.stop()


@pytest.mark.asyncio
async def test_unadvertised_partial_publication_is_removed_with_its_expired_generation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness, binding = await _running(tmp_path)
    store, clock = harness.store, harness.clock
    original = PinnedDirectory.publish_file

    def failed_publish(directory: PinnedDirectory, staged: str, name: str) -> None:
        raise OSError("private disk details")

    try:
        monkeypatch.setattr(PinnedDirectory, "publish_file", failed_publish)
        with pytest.raises(WorkspaceResultError, match="workspace_write_failed"):
            await store.store_tool_result(binding, _capture("body" * 4000))
        partial = [path for path in store.root.rglob("manifest.staged")]
        assert len(partial) == 1
        assert sorted(path.name for path in partial[0].parent.iterdir()) == [
            "manifest.staged", "outline.json", "payload.jsonl",
        ]
        assert await store.reap_tool_results() == WorkspaceReapResult(), "an unexpired partial is left alone"
        monkeypatch.setattr(PinnedDirectory, "publish_file", original)
        reference = await store.store_tool_result(binding, _capture("body"))
        namespace = _namespace_dir(reference)
        (namespace / "user.txt").write_text("keep", encoding="utf-8")
        (namespace / "unknown").mkdir()
        (namespace / "unknown" / "payload.jsonl").write_text("not ours", encoding="utf-8")
        clock[0] = EXPIRY
        outcome = await store.reap_tool_results()
        assert outcome == WorkspaceReapResult(deleted=1, skipped=2)
        assert not _generation_dir(reference).exists() and not partial[0].exists()
        assert (namespace / "user.txt").read_text(encoding="utf-8") == "keep"
        assert (namespace / "unknown" / "payload.jsonl").read_text(encoding="utf-8") == "not ours"
    finally:
        await store.stop()


@pytest.mark.asyncio
async def test_interrupted_generation_removal_resumes_after_restart(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "workspaces"
    first = make_store(root)
    binding = first.store.bind_agent("agent-a", _agent())
    await first.store.start()
    reference = await first.store.store_tool_result(binding, _capture("owned content"))
    removal = _FailingRemoval(monkeypatch, lambda: OSError(errno.EIO, "owned deletion failure"))
    try:
        first.clock[0] = EXPIRY
        result = await first.store.reap_tool_results()
        assert result.failed == 1 and result.deleted == 0 and removal.calls == 1
        # Premise: the removal really was interrupted part-way.
        assert [path.name for path in _artifact_dir(reference).iterdir()] == ["payload.jsonl"]
    finally:
        await first.store.stop()
    removal.broken = False
    restarted = make_store(root, clock=EXPIRY)
    await restarted.store.start()
    try:
        assert not _generation_dir(reference).exists(), "the expired remainder is finished by the startup sweep"
    finally:
        await restarted.store.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize("failures,sleeps,deferred", [
    (2, [0.05, 0.2], 0),
    (None, [0.05, 0.2, 0.5], 1),
])
async def test_sharing_violation_defers_without_latch_injected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    failures: int | None, sleeps: list[float], deferred: int,
) -> None:
    harness, binding, expired, live = await _retention_pair(tmp_path)
    store = harness.store
    removal = _FailingRemoval(monkeypatch, transient_error, failures=failures)
    try:
        outcome = await store.reap_tool_results()
        assert removal.calls >= 1, "the injected remover was reached"
        assert outcome.deferred == deferred and outcome.failed == 0 and outcome.deleted == 1 - deferred
        assert harness.sleeps == sleeps and sum(harness.sleeps) <= 2.0
        reference = await store.store_tool_result(binding, _capture("publication is still admitted"))
        assert (await store.read_tool_result_slice(binding, reference.path, 0, 11)).text == "publication"
        assert (await store.read_tool_result_slice(binding, live.path, 0, 5)).text == "valid"
        removal.broken = False
        final = await store.reap_tool_results()
        assert final.deleted == deferred and final.failed == 0
        assert not _generation_dir(expired).exists()
    finally:
        removal.broken = False
        await store.stop()


@pytest.mark.skipif(sys.platform != "win32", reason="AD-1240: a handle opened without FILE_SHARE_DELETE is Windows-only")
@pytest.mark.asyncio
async def test_sharing_violation_defers_without_latch(tmp_path: Path) -> None:
    import ctypes
    from ctypes import wintypes

    harness, binding, expired, live = await _retention_pair(tmp_path)
    store = harness.store
    payload = Path(expired.path)
    api = ctypes.WinDLL("kernel32", use_last_error=True)
    api.CreateFileW.argtypes = (
        wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
        wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE,
    )
    api.CreateFileW.restype = wintypes.HANDLE
    api.CloseHandle.argtypes = (wintypes.HANDLE,)
    api.CloseHandle.restype = wintypes.BOOL
    handle = None
    try:
        # Read/write sharing deliberately excludes FILE_SHARE_DELETE.
        handle = api.CreateFileW(str(payload), 0x80000000, 0x1 | 0x2, None, 3, 0x80, None)
        assert handle != ctypes.c_void_p(-1).value, ctypes.get_last_error()
        with pytest.raises(PermissionError) as refusal:
            os.remove(payload)
        assert refusal.value.winerror == 32 and payload.is_file(), "the real sharing-violation premise"
        outcome = await store.reap_tool_results()
        assert outcome.deferred == 1 and outcome.failed == 0 and outcome.deleted == 0
        assert harness.sleeps == [0.05, 0.2, 0.5] and sum(harness.sleeps) <= 2.0
        reference = await store.store_tool_result(binding, _capture("publication is still admitted"))
        assert (await store.read_tool_result_slice(binding, reference.path, 0, 11)).text == "publication"
        assert (await store.read_tool_result_slice(binding, live.path, 0, 5)).text == "valid"
        assert api.CloseHandle(handle)
        handle = None
        assert (await store.reap_tool_results()).deleted == 1
        assert not _generation_dir(expired).exists()
    finally:
        if handle is not None:
            assert api.CloseHandle(handle)
        await store.stop()


@pytest.mark.asyncio
async def test_sweep_sleep_budget_caps_total_sleep_across_operations(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    policy = RetryPolicy(attempts=2, delays=(0.5,), sweep_sleep_budget=1.0)
    harness, binding = await _running(tmp_path, retry=policy)
    store, clock = harness.store, harness.clock
    removal = _FailingRemoval(monkeypatch, transient_error)
    try:
        references = [await store.store_tool_result(binding, _capture(f"body {index}")) for index in range(3)]
        clock[0] = EXPIRY
        outcome = await store.reap_tool_results()
        assert removal.calls == 5, "two operations retry once, the third gives up at once"
        assert outcome.deferred == 3 and outcome.failed == 0 and outcome.deleted == 0
        assert harness.sleeps == [0.5, 0.5], "the third operation defers without sleeping"
        removal.broken = False
        assert (await store.reap_tool_results()).deleted == 1
        assert all(not Path(ref.path).exists() for ref in references)
    finally:
        removal.broken = False
        await store.stop()


@pytest.mark.asyncio
async def test_startup_sweep_with_a_deferred_generation_starts_and_admits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "workspaces"
    first = make_store(root)
    binding = first.store.bind_agent("agent-a", _agent())
    await first.store.start()
    reference = await first.store.store_tool_result(binding, _capture("body"))
    await first.store.stop()
    removal = _FailingRemoval(monkeypatch, transient_error)
    restarted = make_store(root, clock=EXPIRY)
    binding = restarted.store.bind_agent("agent-a", _agent())
    try:
        await restarted.store.start()
        assert removal.calls >= 1 and len(restarted.tasks) == 1 and not restarted.tasks[0].done()
        assert _generation_dir(reference).is_dir(), "the deferred generation stays for the next sweep"
        admitted = await restarted.store.store_tool_result(binding, _capture("admitted after a deferred startup"))
        assert (await restarted.store.read_tool_result_slice(binding, admitted.path, 0, 8)).text == "admitted"
    finally:
        removal.broken = False
        await restarted.store.stop()


@pytest.mark.asyncio
async def test_persistent_deferral_escalates_at_two_retention_periods(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness, binding = await _running(tmp_path)
    store, clock = harness.store, harness.clock
    removal = _FailingRemoval(monkeypatch, transient_error)
    try:
        held = await store.store_tool_result(binding, _capture("held by something outside ProbOS"))
        # Premise: the escalation instant is exactly end(G) + 2R.
        assert ESCALATION == GEN_START + GENERATION_SECONDS + 2 * RESULT_RETENTION_SECONDS
        for moment in (EXPIRY, EXPIRY + 3600.0, ESCALATION - 0.001):
            clock[0] = moment
            outcome = await store.reap_tool_results()
            assert outcome == WorkspaceReapResult(deferred=1), moment
        assert removal.calls >= 3 and _generation_dir(held).is_dir()
        reference = await store.store_tool_result(binding, _capture("no latch before two retention periods"))
        assert (await store.read_tool_result_slice(binding, reference.path, 0, 2)).text == "no"
        clock[0] = ESCALATION
        escalated = await store.reap_tool_results()
        assert escalated == WorkspaceReapResult(failed=1)
        with pytest.raises(WorkspaceResultError, match="workspace_unavailable"):
            await store.store_tool_result(binding, _capture("latched"))
        removal.broken = False
        assert (await store.reap_tool_results()).deleted == 1
        with pytest.raises(WorkspaceResultError, match="workspace_unavailable"):
            await store.store_tool_result(binding, _capture("a clean sweep does not clear the latch"))
        await store.stop()
        await store.start()
        recovered = await store.store_tool_result(binding, _capture("recovered"))
        assert (await store.read_tool_result_slice(binding, recovered.path, 0, None)).text == "recovered"
    finally:
        removal.broken = False
        await store.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["entry-cap", "foreign-entries"])
async def test_cap_deferral_and_foreign_entries_never_escalate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, case: str,
) -> None:
    harness, binding = await _running(tmp_path)
    store, clock = harness.store, harness.clock
    try:
        if case == "entry-cap":
            reference = await store.store_tool_result(binding, _capture("body"))
            generation = _generation_dir(reference)
            cap = 3
            entries = 1 + sum(1 for _ in generation.rglob("*"))  # the generation itself and all below it
            assert entries > cap, "premise: the generation holds more entries than the sweep cap"
            monkeypatch.setattr(store_module, "SWEEP_ENTRY_CAP", cap)
            clock[0] = ESCALATION
            assert clock[0] >= expiry_of(GEN) + RESULT_RETENTION_SECONDS, "premise: at the escalation instant"
            outcome = await store.reap_tool_results()
            assert outcome.deferred >= 1 and outcome.failed == 0 and outcome.deleted == 0
            assert generation.is_dir(), "the capped generation waits for the next sweep"
            await store.store_tool_result(binding, _capture("publication stays admitted"))
            monkeypatch.setattr(store_module, "SWEEP_ENTRY_CAP", 10_000)
            finished = await store.reap_tool_results()
            assert finished.deleted == 1 and finished.failed == 0 and not generation.exists()
        else:
            name = "20261009T01Z"
            refused_dir = store.root / binding.owner_key / RESULT_DIRECTORY / name / "digest" / "artifact"
            refused_dir.mkdir(parents=True)
            refused = [refused_dir / "odd-one.txt", refused_dir / "odd-two.txt"]
            for path in refused:
                path.write_bytes(b"outside material")
            assert all(path.is_file() for path in refused), "premise: the refused entries exist"
            assert ESCALATION >= expiry_of(name) + RESULT_RETENTION_SECONDS, "premise: past its escalation instant"
            original = PinnedDirectory.remove_file
            refusals: list[str] = []

            def refusing(directory: PinnedDirectory, leaf: str) -> None:
                if leaf.startswith("odd-"):
                    refusals.append(leaf)
                    raise FileAccessDenied("", "invalid child name")
                original(directory, leaf)

            monkeypatch.setattr(PinnedDirectory, "remove_file", refusing)
            clock[0] = ESCALATION
            outcome = await store.reap_tool_results()
            assert sorted(refusals) == ["odd-one.txt", "odd-two.txt"], "premise: the primitives refused both"
            assert outcome.skipped >= 1 and outcome.failed == 0 and outcome.deferred == 0 and outcome.deleted == 0
            assert all(path.read_bytes() == b"outside material" for path in refused)
            assert refused_dir.parents[1].is_dir(), "the generation that holds refused entries is retained"
            await store.store_tool_result(binding, _capture("publication stays admitted"))
    finally:
        await store.stop()


@pytest.mark.asyncio
async def test_namespace_level_transient_failure_defers_with_a_warning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
) -> None:
    harness, binding = await _running(tmp_path)
    store, clock = harness.store, harness.clock
    try:
        reference = await store.store_tool_result(binding, _capture("body"))
        namespace = _namespace_dir(reference)
        listed: list[Path] = []
        names = PinnedDirectory.list_names

        def listing(directory: PinnedDirectory) -> tuple[str, ...]:
            if directory.path == namespace:
                listed.append(namespace)
                raise transient_error()
            return names(directory)

        monkeypatch.setattr(PinnedDirectory, "list_names", listing)
        caplog.set_level(logging.INFO, logger=store_module.__name__)
        clock[0] = EXPIRY + 5 * RESULT_RETENTION_SECONDS  # far past any escalation instant
        outcome = await store.reap_tool_results()
        assert listed, "premise: the owner namespace really failed with a transient error"
        assert outcome == WorkspaceReapResult(deferred=1), "a deferral, not a failure: nothing latches"
        warnings = [
            record for record in caplog.records
            if record.levelno == logging.WARNING and "owner namespace" in record.getMessage()
        ]
        assert len(warnings) == 1
        message = warnings[0].getMessage()
        # F5: this line used to pin "never escalates". A namespace that stays deferred
        # for one retention period within this process now latches publication, so the
        # warning must say that instead of promising it never does.
        assert "transient failure" in message and "next sweep" in message and "one retention period" in message
        assert "never escalates" not in message
        assert not [record for record in caplog.records if record.levelno >= logging.ERROR]
        # The sweep's own INFO deferral line is separate and does not replace the WARNING.
        assert any(
            record.levelno == logging.INFO and record.getMessage().startswith("Workspace result sweep deferred")
            for record in caplog.records
        )
        await store.store_tool_result(binding, _capture("publication stays admitted"))
    finally:
        await store.stop()


async def _assert_latched_until_restart(
    harness: StoreHarness, binding: AgentWorkspace, restore: Callable[[], None],
) -> None:
    store = harness.store
    with pytest.raises(WorkspaceResultError, match="workspace_unavailable"):
        await store.store_tool_result(binding, _capture("must not publish"))
    restore()
    assert (await store.reap_tool_results()).failed == 0, "the cause is repaired"
    with pytest.raises(WorkspaceResultError, match="workspace_unavailable"):
        await store.store_tool_result(binding, _capture("a clean sweep does not clear the latch"))
    with pytest.raises(WorkspaceResultError, match="workspace_unavailable"):
        await store.start()
    await store.stop()
    await store.start()
    reference = await store.store_tool_result(binding, _capture("recovered"))
    assert (await store.read_tool_result_slice(binding, reference.path, 0, None)).text == "recovered"


@pytest.mark.asyncio
@pytest.mark.parametrize("cause", [
    pytest.param("junction-namespace", marks=pytest.mark.skipif(
        sys.platform != "win32", reason="AD-1240: a junction is Windows-only")),
    pytest.param("junction-owner", marks=pytest.mark.skipif(
        sys.platform != "win32", reason="AD-1240: a junction is Windows-only")),
    pytest.param("symlink-namespace", marks=pytest.mark.skipif(
        sys.platform == "win32", reason="AD-1240: an unprivileged directory symlink is a POSIX premise")),
    pytest.param("symlink-owner", marks=pytest.mark.skipif(
        sys.platform == "win32", reason="AD-1240: an unprivileged directory symlink is a POSIX premise")),
    "replaced-namespace",
    "replaced-owner",
    "injected-access-denied",
    "stubbed-failed-count",
])
async def test_integrity_failure_latches_publication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, cause: str,
) -> None:
    _assert_provenance()
    harness, binding = await _running(tmp_path)
    store = harness.store
    try:
        reference = await store.store_tool_result(binding, _capture("published before the cause"))
        namespace, owner = _namespace_dir(reference), _namespace_dir(reference).parent
        restore: Callable[[], None]
        if cause == "injected-access-denied":
            state = {"broken": True, "calls": 0}
            names = PinnedDirectory.list_names

            def listing(directory: PinnedDirectory) -> tuple[str, ...]:
                if state["broken"] and directory.path == namespace:
                    state["calls"] += 1
                    raise FileAccessDenied("", "directory identity changed")
                return names(directory)

            monkeypatch.setattr(PinnedDirectory, "list_names", listing)
            restore = lambda: state.update(broken=False)  # noqa: E731
        elif cause == "stubbed-failed-count":
            real_sweep = GenerationReaper.sweep
            monkeypatch.setattr(GenerationReaper, "sweep", lambda self, now: WorkspaceReapResult(failed=1))
            restore = lambda: monkeypatch.setattr(GenerationReaper, "sweep", real_sweep)  # noqa: E731
        else:
            style, target = cause.split("-")
            victim = namespace if target == "namespace" else owner
            moved, decoy = tmp_path / "moved-original", tmp_path / "decoy"
            expired_decoy = decoy / "20200101T00Z" / "digest" / "artifact"
            expired_decoy.mkdir(parents=True)
            (expired_decoy / "sentinel.txt").write_bytes(b"decoy sentinel")
            before = victim.lstat()
            victim.rename(moved)
            if style == "junction":
                _make_junction(victim, decoy)
            elif style == "symlink":
                _make_symlink(victim, decoy)
            else:
                victim.mkdir()  # a different real directory under the same name
            after = victim.lstat()
            assert (before.st_dev, before.st_ino) != (after.st_dev, after.st_ino), "the identity really changed"

            def restore() -> None:
                if style == "replaced":
                    victim.rmdir()
                else:
                    _remove_alias(victim)
                moved.rename(victim)

        outcome = await store.reap_tool_results()
        assert outcome == WorkspaceReapResult(failed=1), cause
        if cause == "injected-access-denied":
            assert state["calls"] >= 1, "the injected chain failure was reached"
        if cause.split("-")[0] in ("junction", "symlink"):
            assert (decoy / "20200101T00Z" / "digest" / "artifact" / "sentinel.txt").read_bytes() == b"decoy sentinel"
        await _assert_latched_until_restart(harness, binding, restore)
        assert harness.sleeps == [], "an integrity failure is never retried"
    finally:
        await store.stop()


@pytest.mark.asyncio
async def test_failed_startup_sweep_refuses_start_and_publication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = make_store(tmp_path / "ws")
    store = harness.store
    binding = store.bind_agent("agent-a", _agent())
    calls: list[float] = []

    def failed_sweep(self: GenerationReaper, now: float) -> WorkspaceReapResult:
        calls.append(now)
        return WorkspaceReapResult(failed=1)

    monkeypatch.setattr(GenerationReaper, "sweep", failed_sweep)
    try:
        with pytest.raises(WorkspaceResultError, match="workspace_reap_failed"):
            await store.start()
        assert calls == [T0], "the startup sweep ran and reported the failure"
        assert harness.tasks == [] and store.background_tasks == ()
        with pytest.raises(WorkspaceResultError, match="workspace_unavailable"):
            await store.store_tool_result(binding, _capture("retained" * 2000))
        assert not store.root.exists()
    finally:
        await store.stop()


@pytest.mark.skipif(sys.platform != "win32", reason="AD-1240: an unavailable drive letter is Windows-only")
@pytest.mark.asyncio
@pytest.mark.parametrize("consumer", ["sweep", "start", "phase1"])
async def test_missing_anchor_terminates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, consumer: str,
) -> None:
    import ctypes

    _assert_provenance()
    drives = ctypes.windll.kernel32.GetLogicalDrives()
    assert drives, "the unavailable-drive premise requires a valid drive mask"
    letter = next(chr(65 + index) for index in reversed(range(26)) if not drives & (1 << index))
    anchor = Path(f"{letter}:\\")
    with pytest.raises(FileNotFoundError):
        anchor.lstat()
    root = anchor / "probos-r1-absent" / "workspaces"
    assert anchor.parent == anchor and root.is_absolute()
    await _assert_anchor_terminates(
        monkeypatch, root, anchor, consumer, real=True, data_dir=tmp_path / "data", caplog=caplog,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("consumer", ["sweep", "start", "phase1"])
async def test_missing_anchor_terminates_injected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, consumer: str,
) -> None:
    root = tmp_path / "absent" / "workspaces"
    anchor = Path(root.anchor)
    assert anchor.parent == anchor and root.is_absolute() and not root.exists()
    await _assert_anchor_terminates(
        monkeypatch, root, anchor, consumer, real=False, data_dir=tmp_path / "data", caplog=caplog,
    )


async def _assert_anchor_terminates(
    monkeypatch: pytest.MonkeyPatch, root: Path, anchor: Path, consumer: str, *, real: bool,
    data_dir: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    attempts: list[Path] = []
    expected = [root, *root.parents]
    pin = store_module.pin_directory

    class _PinAttemptOverrun(RuntimeError):
        pass

    @contextmanager
    def bounded_pin(path: Path, **kwargs: Any) -> Any:
        attempts.append(path)
        if len(attempts) > len(expected):
            raise _PinAttemptOverrun("missing_anchor_pin_attempt_bound_exceeded")
        assert path == expected[len(attempts) - 1]
        assert not kwargs.get("create", False)
        if not real:
            # The anchor itself is stubbed unavailable: a finite failing authority.
            raise FileNotFoundError(str(path))
        with pin(path, **kwargs) as opened:
            yield opened

    monkeypatch.setattr(store_module, "pin_directory", bounded_pin)
    if consumer == "phase1":
        await _assert_phase_one_degrades_to_unavailable(
            root, anchor, attempts, expected, data_dir=data_dir, caplog=caplog,
        )
        return
    harness = make_store(root)
    store = harness.store
    binding = store.bind_agent("agent-a", _agent())
    try:
        with pytest.raises(WorkspaceResultError, match="^workspace_reap_failed$"):
            if consumer == "sweep":
                await store.reap_tool_results()
            else:
                await store.start()
        assert attempts == expected and attempts.count(anchor) == 1, "the anchor is visited once"
        assert harness.tasks == [] and store.background_tasks == ()
        assert not root.exists() and not root.parent.exists(), "nothing is created"
        # The owner stays armed-unavailable: nothing is published under a missing anchor.
        with pytest.raises(WorkspaceResultError, match="workspace_unavailable"):
            await store.store_tool_result(binding, _capture("not published"))
    finally:
        await store.stop()


@pytest.mark.asyncio
async def test_absent_child_of_accessible_anchor_is_empty_without_creation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _assert_provenance()
    assert tmp_path.is_absolute() and tmp_path.is_dir()
    root = tmp_path / "not-created" / "workspaces"
    pin = store_module.pin_directory
    attempts: list[Path] = []

    @contextmanager
    def counted_pin(path: Path, **kwargs: Any) -> Any:
        attempts.append(path)
        assert len(attempts) <= 3, "accessible_ancestor_pin_attempt_bound_exceeded"
        assert not kwargs.get("create", False)
        with pin(path, **kwargs) as opened:
            yield opened

    monkeypatch.setattr(store_module, "pin_directory", counted_pin)
    store = make_store(root).store
    assert await store.reap_tool_results() == WorkspaceReapResult()
    assert attempts == [root, root.parent, tmp_path]
    assert not root.parent.exists()


@pytest.mark.asyncio
async def test_start_requires_registration_no_absent_root_creation(tmp_path: Path) -> None:
    root = tmp_path / "absent" / "workspaces"
    legacy = make_store(root, register=False).store
    with pytest.raises(WorkspaceResultError, match="reaper_unregistered"):
        await legacy.start()
    assert not root.parent.exists()
    tasks: list[asyncio.Task[None]] = []

    def cancelled_registration(task: asyncio.Task[None]) -> None:
        tasks.append(task)
        task.cancel()

    store = WorkspaceResultStore(WorkspaceManager(root), background_register=cancelled_registration)
    with pytest.raises(WorkspaceResultError, match="reaper_unavailable"):
        await store.start()
    assert not root.parent.exists() and all(task.done() for task in tasks)
    await store.stop()
    await store.stop()


@pytest.mark.asyncio
async def test_cancelled_registered_reaper_refuses_new_publication(tmp_path: Path) -> None:
    harness, binding = await _running(tmp_path)
    harness.tasks[0].cancel()
    try:
        with pytest.raises(WorkspaceResultError, match="workspace_unavailable"):
            await harness.store.store_tool_result(binding, _capture("body"))
        assert not harness.store.root.exists()
    finally:
        await harness.store.stop()


@pytest.mark.asyncio
async def test_cancelled_io_drains_thread_and_shutdown_waits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness, binding = await _running(tmp_path)
    store = harness.store
    entered, release, finished = threading.Event(), threading.Event(), threading.Event()
    original = PinnedDirectory.write_new

    def blocked_write(directory: PinnedDirectory, name: str, data: bytes) -> None:
        if name == "payload.jsonl":
            entered.set()
            assert release.wait(10), "test must release its owned worker"
            try:
                original(directory, name, data)
            finally:
                finished.set()
        else:
            original(directory, name, data)

    monkeypatch.setattr(PinnedDirectory, "write_new", blocked_write)
    operation = asyncio.create_task(store.store_tool_result(binding, _capture("body" * 4000)))
    shutdown: asyncio.Task[None] | None = None
    try:
        await _entered(entered)
        operation.cancel()
        shutdown = asyncio.create_task(store.stop())
        await asyncio.sleep(0)
        assert not operation.done() and not shutdown.done() and not finished.is_set()
        operation.cancel()
        await asyncio.sleep(0)
        assert not operation.done() and not shutdown.done() and not finished.is_set()
    finally:
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await operation
        if shutdown is not None:
            await shutdown
        else:
            await store.stop()
    assert finished.is_set()


@pytest.mark.asyncio
async def test_concurrent_store_read_and_sweep_are_serialized(tmp_path: Path) -> None:
    harness, binding = await _running(tmp_path)
    store = harness.store
    try:
        references = await asyncio.gather(*(
            store.store_tool_result(binding, _capture(f"value-{index}" * 2000))
            for index in range(6)
        ))
        assert len({ref.path for ref in references}) == 6
        outcomes = await asyncio.gather(
            *(store.read_tool_result_slice(binding, ref.path, 5, 55) for ref in references),
            store.reap_tool_results(),
        )
        assert [part.text for part in outcomes[:-1]] == [
            (f"value-{index}" * 2000)[5:60] for index in range(6)
        ]
        assert outcomes[-1] == WorkspaceReapResult()
    finally:
        await store.stop()


@pytest.mark.asyncio
async def test_root_identity_replacement_refuses_new_write_and_old_read(tmp_path: Path) -> None:
    harness, binding = await _running(tmp_path)
    store = harness.store
    try:
        reference = await store.store_tool_result(binding, _capture("body" * 4000))
        store.root.rename(tmp_path / "moved")
        store.root.mkdir()
        with pytest.raises(WorkspaceResultError, match="workspace_write_failed"):
            await store.store_tool_result(binding, _capture("new body"))
        with pytest.raises(WorkspaceResultError):
            await store.read_tool_result_slice(binding, reference.path, 0, 1)
        assert list(store.root.iterdir()) == []
        assert len(list((tmp_path / "moved").rglob("payload.jsonl"))) == 1
    finally:
        await store.stop()


@pytest.mark.asyncio
async def test_opened_root_reparse_swap_is_typed_refusal_without_target_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    import shutil
    import subprocess

    harness = make_store(tmp_path / "workspace")
    store = harness.store
    binding = store.bind_agent("agent-a", _agent())
    await store.start()
    reference = await store.store_tool_result(binding, _capture("owned bytes"))
    target = tmp_path / "unrelated"
    target.mkdir()
    shutil.copytree(store.root, target, dirs_exist_ok=True)
    (target / "user.txt").write_text("preserve", encoding="utf-8")
    moved = tmp_path / "original"
    original_lstat = Path.lstat
    swapped = False

    def racing_lstat(path: Path) -> os.stat_result:
        nonlocal swapped
        before = original_lstat(path)
        if not swapped and path == store.root:
            swapped = True
            store.root.rename(moved)
            if os.name == "nt":
                outcome = subprocess.run(
                    ["cmd", "/c", "mklink", "/J", str(store.root), str(target)],
                    capture_output=True, check=False,
                )
                assert outcome.returncode == 0, outcome.stderr
            else:
                store.root.symlink_to(target, target_is_directory=True)
        return before

    monkeypatch.setattr(Path, "lstat", racing_lstat)
    try:
        with pytest.raises(WorkspaceResultError, match="workspace_read_failed"):
            await store.read_tool_result_slice(binding, reference.path, 0, 1)
        assert swapped
        assert (target / "user.txt").read_text(encoding="utf-8") == "preserve"
        assert len(list(target.rglob("payload.jsonl"))) == 1
        assert len(list(moved.rglob("payload.jsonl"))) == 1
    finally:
        monkeypatch.setattr(Path, "lstat", original_lstat)
        await store.stop()
        if swapped:
            store.root.rmdir() if os.name == "nt" else store.root.unlink()
            moved.rename(store.root)


@pytest.mark.asyncio
async def test_failed_periodic_reaper_refuses_publication_until_restarted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    entered = asyncio.Event()
    release = asyncio.Event()
    original_sleep = asyncio.sleep

    async def sleep(delay: float) -> None:
        if delay == 60:
            entered.set()
            await release.wait()
            raise OSError("private sweep details")
        await original_sleep(delay)

    monkeypatch.setattr(asyncio, "sleep", sleep)
    harness, binding = await _running(tmp_path)
    store, tasks = harness.store, harness.tasks
    try:
        await entered.wait()
        release.set()
        with pytest.raises(OSError):
            await tasks[0]
        with pytest.raises(WorkspaceResultError, match="workspace_unavailable"):
            await store.store_tool_result(binding, _capture("not published"))
        assert not store.root.exists()
    finally:
        await store.stop()
    monkeypatch.setattr(asyncio, "sleep", original_sleep)
    await store.start()
    try:
        reference = await store.store_tool_result(binding, _capture("restarted"))
        assert Path(reference.path).is_file()
    finally:
        await store.stop()


@pytest.mark.asyncio
async def test_live_periodic_reaper_deletes_on_due_sweep_and_start_is_idempotent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert tmp_path.is_absolute()
    entered, release, swept = asyncio.Event(), asyncio.Event(), asyncio.Event()
    sleep = asyncio.sleep
    ticks = 0

    async def controlled_sleep(delay: float) -> None:
        nonlocal ticks
        if delay != 60:
            await sleep(delay)
            return
        ticks += 1
        if ticks == 1:
            entered.set()
            await release.wait()
        else:
            swept.set()
            await asyncio.Event().wait()

    monkeypatch.setattr(asyncio, "sleep", controlled_sleep)
    harness, binding = await _running(tmp_path)
    store, clock, tasks = harness.store, harness.clock, harness.tasks
    try:
        await store.start()
        assert store.background_tasks == tuple(tasks) and len(tasks) == 1
        reference = await store.store_tool_result(binding, _capture("retained until due"))
        user_file = store.root / "user.txt"
        user_file.write_bytes(b"unknown user bytes")
        unknown = _namespace_dir(reference) / "unknown.txt"
        unknown.write_bytes(b"unknown namespace bytes")
        await entered.wait()
        clock[0] = EXPIRY
        release.set()
        await asyncio.wait_for(swept.wait(), timeout=5)
        assert not _generation_dir(reference).exists()
        assert user_file.read_bytes() == b"unknown user bytes"
        assert unknown.read_bytes() == b"unknown namespace bytes"
        assert not tasks[0].done()
    finally:
        await store.stop()
    assert tasks[0].done()


@pytest.mark.asyncio
@pytest.mark.parametrize("origin", ["startup", "public", "periodic"])
@pytest.mark.parametrize("fault", ["count", "oserror", "typed", "unexpected"])
async def test_retention_failure_latches_until_completed_stop_and_clean_start(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture, origin: str, fault: str,
) -> None:
    release_tick = asyncio.Event()
    sleep = asyncio.sleep
    ticks = 0

    async def controlled_sleep(delay: float) -> None:
        nonlocal ticks
        if delay != 60:
            await sleep(delay)
        else:
            ticks += 1
            if ticks == 1:
                await release_tick.wait()
            else:
                await asyncio.Event().wait()

    monkeypatch.setattr(asyncio, "sleep", controlled_sleep)
    harness, binding, expired, live = await _retention_pair(tmp_path)
    store, tasks = harness.store, harness.tasks
    reaper = store.background_tasks[0]
    if origin == "startup":
        await store.stop()
        assert reaper.done()
    names = PinnedDirectory.list_names
    broken = True
    failure_calls = 0
    private_detail = "private-backend-details-not-for-logs"
    removal = _FailingRemoval(monkeypatch, lambda: OSError(errno.EIO, private_detail)) if fault == "count" else None

    def listing(directory: PinnedDirectory) -> tuple[str, ...]:
        nonlocal failure_calls
        if broken and fault != "count" and directory.path == store.root:
            failure_calls += 1
            if fault == "typed":
                raise WorkspaceResultError("clock_invalid")
            if fault == "unexpected":
                raise RuntimeError(private_detail)
            raise OSError(private_detail)
        return names(directory)

    monkeypatch.setattr(PinnedDirectory, "list_names", listing)
    expected = "clock_invalid" if fault == "typed" else "workspace_reap_failed"
    try:
        if origin == "startup":
            with pytest.raises(WorkspaceResultError, match=expected):
                await store.start()
        elif origin == "periodic":
            release_tick.set()
            with pytest.raises(WorkspaceResultError, match=expected):
                await asyncio.wait_for(reaper, 5)
            assert reaper.done()
        elif fault == "count":
            result = await store.reap_tool_results()
            assert result == WorkspaceReapResult(failed=1)
        else:
            with pytest.raises(WorkspaceResultError, match=expected):
                await store.reap_tool_results()
        failure_calls += removal.calls if removal is not None else 0
        assert failure_calls == 1 and tasks == [reaper]
        assert store.background_tasks == (reaper,)
        assert private_detail not in caplog.text
        if fault == "count":
            assert "count=1" in caplog.text
        assert (await store.read_tool_result_slice(binding, live.path, 0, None)).text == "valid retained body"
        files = set(store.root.rglob("*"))
        with pytest.raises(WorkspaceResultError, match="workspace_unavailable"):
            await store.store_tool_result(binding, _capture("must not publish"))
        with pytest.raises(WorkspaceResultError, match="workspace_unavailable"):
            await store.start()
        assert tasks == [reaper] and store.background_tasks == (reaper,)
        assert set(store.root.rglob("*")) == files
        broken = False
        if removal is not None:
            removal.broken = False
        clean = await store.reap_tool_results()
        assert clean.failed == 0 and clean.deleted == 1
        with pytest.raises(WorkspaceResultError, match="workspace_unavailable"):
            await store.store_tool_result(binding, _capture("clean sweep does not reset"))
        with pytest.raises(WorkspaceResultError, match="workspace_unavailable"):
            await store.start()
        await store.stop()
        assert reaper.done()
        monkeypatch.setattr(asyncio, "sleep", sleep)
        await store.start()
        assert len(tasks) == 2 and store.background_tasks == (tasks[-1],) and not tasks[-1].done()
        reference = await store.store_tool_result(binding, _capture("recovered publisher"))
        assert (await store.read_tool_result_slice(binding, reference.path, 0, None)).text == "recovered publisher"
        assert harness.sleeps == []
    finally:
        await store.stop()
        assert all(task.done() for task in tasks)


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel", [False, True])
async def test_sweep_latches_before_waiting_publisher_and_drains_cancelled_worker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, cancel: bool,
) -> None:
    harness, binding, expired, live = await _retention_pair(tmp_path)
    store, tasks = harness.store, harness.tasks
    entered, release, finished = threading.Event(), threading.Event(), threading.Event()
    remove = PinnedDirectory.remove_file

    def blocked_removal(directory: PinnedDirectory, name: str) -> None:
        if directory.path == _artifact_dir(expired) and name == "payload.jsonl":
            entered.set()
            assert release.wait(10), "test must release the bounded sweep worker"
            finished.set()
            raise OSError(errno.EIO, "fixture deletion refusal")
        remove(directory, name)

    monkeypatch.setattr(PinnedDirectory, "remove_file", blocked_removal)
    sweep = asyncio.create_task(store.reap_tool_results())
    publication: asyncio.Task[WorkspaceResultRef] | None = None
    try:
        await _entered(entered)
        publication = asyncio.create_task(store.store_tool_result(binding, _capture("queued publication")))
        await asyncio.sleep(0)
        assert not publication.done()
        if cancel:
            sweep.cancel()
            await asyncio.sleep(0)
            sweep.cancel()
            await asyncio.sleep(0)
            assert not sweep.done() and not finished.is_set() and not publication.done()
        release.set()
        if cancel:
            with pytest.raises(asyncio.CancelledError):
                await sweep
        else:
            assert (await sweep).failed == 1
        assert finished.is_set()
        with pytest.raises(WorkspaceResultError, match="workspace_unavailable"):
            await publication
        assert (await store.read_tool_result_slice(binding, live.path, 0, 5)).text == "valid"
        assert list(store.root.rglob("manifest.json")) == [Path(live.path).with_name("manifest.json")]
        assert tasks == list(store.background_tasks)
    finally:
        release.set()
        await asyncio.gather(sweep, *([publication] if publication is not None else []), return_exceptions=True)
        await store.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize("interruption", ["sweep", "cancel"])
async def test_yielding_start_does_not_overwrite_a_concurrent_sweep_fault(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, interruption: str,
) -> None:
    _assert_provenance()
    assert tmp_path.is_absolute()
    root = tmp_path / "workspaces"
    root.mkdir()
    harness = make_store(root)
    store, tasks = harness.store, harness.tasks
    binding = store.bind_agent("agent-a", _agent())
    entered, release = asyncio.Event(), asyncio.Event()
    sleep, names = asyncio.sleep, PinnedDirectory.list_names
    starting: asyncio.Task[None] | None = None
    fault = False

    async def gated_sleep(delay: float) -> None:
        if delay == 0 and asyncio.current_task() is starting:
            entered.set()
            await release.wait()
        else:
            await sleep(delay)

    def listing(directory: PinnedDirectory) -> tuple[str, ...]:
        if fault and directory.path == root:
            raise OSError("fixture concurrent retention fault")
        return names(directory)

    monkeypatch.setattr(asyncio, "sleep", gated_sleep)
    monkeypatch.setattr(PinnedDirectory, "list_names", listing)
    starting = asyncio.create_task(store.start())
    try:
        await asyncio.wait_for(entered.wait(), 5)
        assert len(tasks) == 1 and store.background_tasks == tuple(tasks)
        if interruption == "sweep":
            fault = True
            with pytest.raises(WorkspaceResultError, match="workspace_reap_failed"):
                await store.reap_tool_results()
            fault = False
            assert (await store.reap_tool_results()).failed == 0
            release.set()
            with pytest.raises(WorkspaceResultError, match="workspace_reap_failed"):
                await starting
        else:
            starting.cancel()
            with pytest.raises(asyncio.CancelledError):
                await starting
            release.set()
        assert tasks[0].done() and store.background_tasks == tuple(tasks)
        with pytest.raises(WorkspaceResultError, match="workspace_unavailable"):
            await store.start()
        with pytest.raises(WorkspaceResultError, match="workspace_unavailable"):
            await store.store_tool_result(binding, _capture("must stay disabled"))
        assert list(root.iterdir()) == [] and len(tasks) == 1
        await store.stop()
        await store.start()
        assert len(tasks) == 2 and store.background_tasks == (tasks[-1],)
        reference = await store.store_tool_result(binding, _capture("after explicit recovery"))
        assert Path(reference.path).is_file()
    finally:
        release.set()
        await asyncio.gather(starting, return_exceptions=True)
        await store.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["stop", "reaper"])
async def test_final_manifest_commit_rechecks_lifecycle_after_staged_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str,
) -> None:
    _assert_provenance()
    assert tmp_path.is_absolute()
    tick = asyncio.Event()
    sleep = asyncio.sleep

    async def failing_tick(delay: float) -> None:
        if delay == 60:
            await tick.wait()
            raise OSError("fixture reaper failure")
        await sleep(delay)

    monkeypatch.setattr(asyncio, "sleep", failing_tick)
    harness, binding = await _running(tmp_path)
    store, tasks = harness.store, harness.tasks
    entered, release = threading.Event(), threading.Event()
    write = PinnedDirectory.write_new

    def staged_write(directory: PinnedDirectory, name: str, data: bytes) -> None:
        write(directory, name, data)
        if name == "manifest.staged":
            entered.set()
            assert release.wait(10), "test must release the staged publication worker"

    monkeypatch.setattr(PinnedDirectory, "write_new", staged_write)
    publication = asyncio.create_task(store.store_tool_result(binding, _capture("not committed")))
    stopping: asyncio.Task[None] | None = None
    try:
        await _entered(entered)
        assert not publication.done()
        if failure == "reaper":
            tick.set()
            with pytest.raises(OSError, match="fixture reaper failure"):
                await tasks[0]
            with pytest.raises(WorkspaceResultError, match="workspace_unavailable"):
                await store.start()
        else:
            stopping = asyncio.create_task(store.stop())
            await sleep(0)
            await sleep(0)
            await asyncio.gather(tasks[0], return_exceptions=True)
            assert not stopping.done()
        release.set()
        with pytest.raises(WorkspaceResultError, match="workspace_unavailable"):
            await publication
        if stopping is not None:
            await stopping
        assert list(store.root.rglob("manifest.json")) == []
        assert len(list(store.root.rglob("manifest.staged"))) == 1
        assert len(tasks) == 1 and tasks[0].done()
        await store.stop()
        monkeypatch.setattr(asyncio, "sleep", sleep)
        monkeypatch.setattr(PinnedDirectory, "write_new", write)
        await store.start()
        assert len(list(store.root.rglob("manifest.staged"))) == 1, "an unexpired partial is not reaped"
        reference = await store.store_tool_result(binding, _capture("clean restart"))
        assert Path(reference.path).is_file()
    finally:
        release.set()
        await asyncio.gather(publication, *([stopping] if stopping is not None else []), return_exceptions=True)
        await store.stop()


@pytest.mark.asyncio
async def test_skipped_user_material_does_not_latch_publisher(tmp_path: Path) -> None:
    harness, binding, expired, live = await _retention_pair(tmp_path)
    store, tasks = harness.store, harness.tasks
    namespace = _namespace_dir(expired)
    user = namespace / "user.txt"
    user.write_bytes(b"preserve unknown user content")
    folder = namespace / "unknown"
    folder.mkdir()
    (folder / "keep.txt").write_bytes(b"preserve unknown folder content")
    try:
        result = await store.reap_tool_results()
        assert result == WorkspaceReapResult(deleted=1, skipped=2)
        await store.start()
        assert len(tasks) == 1
        reference = await store.store_tool_result(binding, _capture("still admitted"))
        assert (await store.read_tool_result_slice(binding, reference.path, 0, None)).text == "still admitted"
        assert (await store.read_tool_result_slice(binding, live.path, 0, 5)).text == "valid"
        assert user.read_bytes() == b"preserve unknown user content"
        assert (folder / "keep.txt").read_bytes() == b"preserve unknown folder content"
        assert not _generation_dir(expired).exists()
    finally:
        await store.stop()


@pytest.mark.asyncio
async def test_entries_below_the_depth_bound_are_skipped_in_place(tmp_path: Path) -> None:
    harness, binding = await _running(tmp_path)
    store, clock = harness.store, harness.clock
    try:
        assert (store_module.REAP_MAX_DEPTH, store_module.SWEEP_ENTRY_CAP) == (3, 10_000)
        reference = await store.store_tool_result(binding, _capture("body"))
        artifact = _artifact_dir(reference)
        (artifact / "empty-at-the-bound").mkdir()
        deep = artifact / "too-deep"
        deep.mkdir()
        (deep / "below.txt").write_bytes(b"below the depth bound")
        clock[0] = EXPIRY
        outcome = await store.reap_tool_results()
        assert outcome == WorkspaceReapResult(skipped=1)
        assert (deep / "below.txt").read_bytes() == b"below the depth bound"
        assert not (artifact / "empty-at-the-bound").exists(), "an empty directory at the bound is removed"
        assert [path.name for path in artifact.iterdir()] == ["too-deep"]
        assert _generation_dir(reference).is_dir()
    finally:
        await store.stop()


@pytest.mark.asyncio
async def test_sweep_entry_cap_defers_the_rest_to_the_next_sweep(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness, binding = await _running(tmp_path)
    store, clock = harness.store, harness.clock
    try:
        reference = await store.store_tool_result(binding, _capture("body"))
        clock[0] = EXPIRY
        monkeypatch.setattr(store_module, "SWEEP_ENTRY_CAP", 3)
        capped = await store.reap_tool_results()
        assert capped.deleted == 0 and capped.deferred >= 1 and capped.failed == 0
        assert _generation_dir(reference).is_dir()
        monkeypatch.setattr(store_module, "SWEEP_ENTRY_CAP", 10_000)
        assert (await store.reap_tool_results()).deleted == 1
        assert not _generation_dir(reference).exists()
    finally:
        await store.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize("persistent", [False, True])
async def test_directory_not_empty_is_listed_again_and_removed_again(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, persistent: bool,
) -> None:
    harness, binding = await _running(tmp_path)
    store, clock = harness.store, harness.clock
    original = PinnedDirectory.remove_directory
    refusals: list[str] = []

    def not_empty() -> OSError:
        error = OSError(errno.ENOTEMPTY, "fixture directory not empty")
        if sys.platform == "win32":
            error.winerror = 145
        return error

    try:
        reference = await store.store_tool_result(binding, _capture("body"))
        artifact = _artifact_dir(reference)

        def arriving(directory: PinnedDirectory, name: str) -> None:
            if name == artifact.name and (persistent or not refusals):
                refusals.append(name)
                if not persistent:
                    (artifact / "late.txt").write_bytes(b"arrived after the listing")
                raise not_empty()
            original(directory, name)

        monkeypatch.setattr(PinnedDirectory, "remove_directory", arriving)
        clock[0] = EXPIRY
        outcome = await store.reap_tool_results()
        if persistent:
            assert len(refusals) == RetryPolicy().attempts
            assert outcome == WorkspaceReapResult(deferred=1) and _generation_dir(reference).is_dir()
        else:
            assert refusals == [artifact.name], "premise: the first removal was refused as not empty"
            assert outcome == WorkspaceReapResult(deleted=1)
            assert not _generation_dir(reference).exists()
        assert harness.sleeps == [], "not-empty is re-listed, never slept on"
    finally:
        await store.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize("refusal,chain", [
    ("access-denied", "intact"), ("value-error", "intact"),
    ("access-denied", "broken"), ("value-error", "broken"),
    # A transient failure on a chain that no longer verifies is not a deferral.
    ("transient", "broken"),
])
async def test_entry_refused_by_the_pinned_primitives_is_foreign_unless_the_chain_failed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, refusal: str, chain: str,
) -> None:
    harness, binding = await _running(tmp_path)
    store, clock = harness.store, harness.clock
    try:
        reference = await store.store_tool_result(binding, _capture("body"))
        odd = _artifact_dir(reference) / "odd.txt"
        odd.write_bytes(b"outside material")
        original = PinnedDirectory.remove_file

        def refusing(directory: PinnedDirectory, name: str) -> None:
            if name == "odd.txt":
                if refusal == "access-denied":
                    raise FileAccessDenied("", "invalid child name")
                if refusal == "value-error":
                    raise ValueError("invalid path")
                raise transient_error()
            original(directory, name)

        monkeypatch.setattr(PinnedDirectory, "remove_file", refusing)
        if chain == "broken":
            monkeypatch.setattr(store_module, "_chain_intact", lambda directory: False)
        clock[0] = EXPIRY
        outcome = await store.reap_tool_results()
        assert odd.read_bytes() == b"outside material" and _generation_dir(reference).is_dir()
        # Premise: the transient case really was classified transient (retried) before the chain check.
        assert harness.sleeps == ([0.05, 0.2, 0.5] if refusal == "transient" else [])
        if chain == "intact":
            assert outcome == WorkspaceReapResult(skipped=1)
            await store.store_tool_result(binding, _capture("publication stays admitted"))
        else:
            assert outcome == WorkspaceReapResult(failed=1)
            with pytest.raises(WorkspaceResultError, match="workspace_unavailable"):
                await store.store_tool_result(binding, _capture("latched"))
    finally:
        await store.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize("chain", ["intact", "vanished"])
async def test_enoent_on_the_leaf_is_success_but_enoent_in_the_chain_is_an_integrity_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, chain: str,
) -> None:
    harness, binding = await _running(tmp_path)
    store, clock = harness.store, harness.clock
    try:
        reference = await store.store_tool_result(binding, _capture("body"))
        namespace = _namespace_dir(reference)
        original = PinnedDirectory.remove_file
        victims: list[PinnedDirectory] = []
        consulted: list[Path] = []

        def concurrently_removed(directory: PinnedDirectory, name: str) -> None:
            original(directory, name)
            if name == "payload.jsonl":
                victims.append(directory)
                # Another remover got there first: the leaf was already gone when we asked.
                raise FileNotFoundError(errno.ENOENT, "fixture: already gone")

        def anchor_vanished(directory: PinnedDirectory) -> bool:
            consulted.append(directory.path)
            return not (victims and directory.path == namespace)

        monkeypatch.setattr(PinnedDirectory, "remove_file", concurrently_removed)
        if chain == "vanished":
            # Retargeted by F3. This used to break the pin of the failing leaf's
            # parent (the artifact directory); failures are now settled against the
            # anchor (root -> owner -> .tool-results), and a vanished chain below the
            # anchor is "gone", which is success. So the vanished chain is the
            # namespace pin's.
            monkeypatch.setattr(store_module, "_chain_intact", anchor_vanished)
        clock[0] = EXPIRY
        outcome = await store.reap_tool_results()
        assert len(victims) == 1, "premise: the leaf removal reported ENOENT exactly once"
        if chain == "intact":
            assert outcome == WorkspaceReapResult(deleted=1)
            assert not _generation_dir(reference).exists()
            await store.store_tool_result(binding, _capture("publication stays admitted"))
        else:
            assert consulted == [namespace], "premise: the settle consulted the namespace pin, once"
            assert outcome == WorkspaceReapResult(failed=1)
            assert _generation_dir(reference).is_dir()
            with pytest.raises(WorkspaceResultError, match="workspace_unavailable"):
                await store.store_tool_result(binding, _capture("latched"))
    finally:
        await store.stop()


@pytest.mark.skipif(sys.platform == "win32", reason="AD-1240: these entry names can only be created on POSIX")
@pytest.mark.asyncio
@pytest.mark.parametrize("name", ["with:colon", "trailing.", "back\\slash", "aux", "nul.txt"])
async def test_posix_only_entry_names_the_primitives_refuse_are_left_in_place(
    tmp_path: Path, name: str,
) -> None:
    # Premise, before anything else: the exact property that makes the pinned
    # primitives refuse this name (a colon or backslash character, a trailing
    # dot or space, or a Windows-reserved device name), so a platform where it
    # does not hold fails loudly instead of passing for the wrong reason.
    premises: dict[str, Callable[[str], bool]] = {
        "with:colon": lambda candidate: ":" in candidate,
        "trailing.": lambda candidate: candidate.rstrip(". ") != candidate,
        "back\\slash": lambda candidate: "\\" in candidate,
        "aux": lambda candidate: PureWindowsPath(candidate).is_reserved(),
        "nul.txt": lambda candidate: PureWindowsPath(candidate).is_reserved(),
    }
    assert premises[name](name), f"premise: {name!r} is not a name the pinned primitives refuse"
    harness, binding = await _running(tmp_path)
    store, clock = harness.store, harness.clock
    try:
        reference = await store.store_tool_result(binding, _capture("body"))
        odd = _artifact_dir(reference) / name
        odd.write_bytes(b"outside material")
        assert odd.read_bytes() == b"outside material"
        clock[0] = EXPIRY
        outcome = await store.reap_tool_results()
        assert outcome == WorkspaceReapResult(skipped=1) and odd.read_bytes() == b"outside material"
        await store.store_tool_result(binding, _capture("publication stays admitted"))
    finally:
        await store.stop()


@pytest.mark.asyncio
async def test_special_file_reported_by_lstat_is_left_in_place(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness, binding = await _running(tmp_path)
    store, clock = harness.store, harness.clock
    real_lstat = Path.lstat
    try:
        reference = await store.store_tool_result(binding, _capture("body"))
        device = _artifact_dir(reference) / "device"
        device.write_bytes(b"ordinary bytes the lstat stub reports as a device")
        reported: list[Path] = []

        def fake_lstat(path: Path) -> os.stat_result:
            if path == device:
                reported.append(path)
                # Windows stat results carry st_file_attributes; a bare 10-tuple leaves it None.
                extra = {"st_file_attributes": 0} if sys.platform == "win32" else {}
                return os.stat_result((stat.S_IFCHR | 0o600, 1, 1, 1, 0, 0, 0, 0, 0, 0), extra)
            return real_lstat(path)

        monkeypatch.setattr(Path, "lstat", fake_lstat)
        clock[0] = EXPIRY
        outcome = await store.reap_tool_results()
        assert reported, "the walker consulted lstat for the special entry"
        assert outcome == WorkspaceReapResult(skipped=1) and device.is_file()
        assert _generation_dir(reference).is_dir()
    finally:
        monkeypatch.setattr(Path, "lstat", real_lstat)
        await store.stop()


@pytest.mark.skipif(sys.platform == "win32", reason="AD-1240: a FIFO is a POSIX special file")
@pytest.mark.asyncio
async def test_posix_fifo_in_expired_generation_is_left_in_place(tmp_path: Path) -> None:
    harness, binding = await _running(tmp_path)
    store, clock = harness.store, harness.clock
    try:
        reference = await store.store_tool_result(binding, _capture("body"))
        fifo = _artifact_dir(reference) / "pipe"
        os.mkfifo(fifo)
        assert stat.S_ISFIFO(fifo.lstat().st_mode)
        clock[0] = EXPIRY
        assert await store.reap_tool_results() == WorkspaceReapResult(skipped=1)
        assert stat.S_ISFIFO(fifo.lstat().st_mode)
    finally:
        await store.stop()


# --- Call 4 repairs: F2 (committed-artifact registry) ------------------------------------------


def test_committed_artifacts_keep_one_bucket_per_namespace_and_generation(tmp_path: Path) -> None:
    mine, theirs = tmp_path / "mine" / RESULT_DIRECTORY, tmp_path / "theirs" / RESULT_DIRECTORY
    digest = "1" * 64

    def payload(namespace: Path, generation: str, artifact: str) -> Path:
        return namespace / generation / digest / (artifact * 32) / "payload.jsonl"

    def committed(path: Path, sha: str) -> Any:
        reference = WorkspaceResultRef(
            str(path), digest, path.parent.name, sha * 64, 1, 1, "text",
            T0, T0 + RESULT_RETENTION_SECONDS, "{}",
        )
        return store_module._Committed.of(reference, digest)

    paths = [
        payload(mine, GEN, "a"), payload(mine, GEN, "b"),
        payload(mine, "20261011T08Z", "c"), payload(theirs, GEN, "d"),
    ]
    registry = CommittedArtifacts()
    assert len(registry) == 0 and all(registry.get(path) is None for path in paths), "premise: starts empty"
    values = [committed(path, str(index)) for index, path in enumerate(paths)]
    assert len(set(values)) == 4, "premise: four distinct records"
    for path, value in zip(paths, values):
        registry.record(path, value)
    assert len(registry) == 4 and [registry.get(path) for path in paths] == values
    # Only the (mine, GEN) bucket goes: the other generation and the other namespace survive.
    registry.evict_generation(mine, GEN)
    assert len(registry) == 2
    assert registry.get(paths[0]) is None and registry.get(paths[1]) is None
    assert registry.get(paths[2]) == values[2] and registry.get(paths[3]) == values[3]
    # Evicting a bucket that is already gone, or never existed, is a no-op.
    registry.evict_generation(mine, GEN)
    registry.evict_generation(tmp_path, "20991231T23Z")
    assert len(registry) == 2
    # Recording again replaces the record under the same key.
    registry.record(paths[2], values[3])
    assert len(registry) == 2 and registry.get(paths[2]) == values[3]


@pytest.mark.asyncio
async def test_consistent_rewrite_is_refused_while_the_process_lives(tmp_path: Path) -> None:
    """F2, port of the reviewer's ``mutable-manifest`` probe.

    While a generation is unexpired, a read refuses a payload, outline and
    manifest that were rewritten to agree with one another: the running process
    committed something else.
    """
    _assert_provenance()
    harness, binding = await _running(tmp_path)
    store = harness.store
    try:
        reference = await store.store_tool_result(binding, _capture("original text"))
        revised = _capture("outside replacement")
        payload = Path(reference.path)
        assert payload.is_file() and reference.committed_at == T0 and revised.sha256 != reference.sha256
        assert len(revised.text) <= 42, "premise: the replacement fits one payload line"
        # Premise: the digest check ran. A payload-only substitution is refused by it.
        payload.write_bytes((json.dumps(revised.text) + "\n").encode("ascii"))
        with pytest.raises(WorkspaceResultError, match="^payload_changed$"):
            await store.read_tool_result_slice(binding, reference.path, None, None)
        # The rewrite is then made consistent: only the process's own record can refuse it now.
        _rewrite_artifact(reference, revised)
        assert _files_agree(reference, revised), "premise: payload, outline and manifest agree"
        assert harness.clock[0] < reference.expires_at, "premise: well inside the retention window"
        with pytest.raises(WorkspaceResultError, match="^payload_changed$"):
            await store.read_tool_result_slice(binding, reference.path, None, None)
        untouched = await store.store_tool_result(binding, _capture("untouched"))
        assert (await store.read_tool_result_slice(binding, untouched.path, None, None)).text == "untouched"
    finally:
        await store.stop()


@pytest.mark.asyncio
async def test_committed_at_tamper_is_refused_while_the_process_lives(tmp_path: Path) -> None:
    """F2: moving ``committed_at`` later must not extend readability past the original expiry."""
    _assert_provenance()
    harness, binding = await _running(tmp_path)
    store, clock = harness.store, harness.clock
    try:
        tampered = await store.store_tool_result(binding, _capture("original text"))
        control = await store.store_tool_result(binding, _capture("untouched control"))
        original_expiry = tampered.committed_at + RESULT_RETENTION_SECONDS
        last_second = GEN_START + GENERATION_SECONDS - 1.0
        assert tampered.committed_at == T0 == control.committed_at and original_expiry == tampered.expires_at
        assert T0 < last_second < GEN_START + GENERATION_SECONDS
        manifest_path = _artifact_dir(tampered) / "manifest.json"
        manifest = json.loads(manifest_path.read_bytes())
        manifest["committed_at"] = last_second
        manifest_path.write_text(json.dumps(manifest), encoding="ascii")
        # Premise: the tampered manifest is valid and would buy time past the original expiry.
        assert json.loads(manifest_path.read_bytes())["committed_at"] == last_second
        assert original_expiry < last_second + RESULT_RETENTION_SECONDS
        # Premise: the boundary is real. An untouched artifact reads a second before it
        # and is expired at exactly the original ``committed_at + R``.
        clock[0] = original_expiry - 1.0
        assert (await store.read_tool_result_slice(binding, control.path, None, None)).text == "untouched control"
        clock[0] = original_expiry
        with pytest.raises(WorkspaceResultError, match="^result_expired$"):
            await store.read_tool_result_slice(binding, control.path, None, None)
        # The tampered one is refused at that same instant, as changed rather than served, and
        # it never succeeds at or after the original expiry (the last case is the latest
        # instant the tampered ``committed_at`` would have kept it readable).
        for moment in (original_expiry, original_expiry + 1.0, last_second + RESULT_RETENTION_SECONDS - 1.0):
            clock[0] = moment
            with pytest.raises(WorkspaceResultError, match="^payload_changed$"):
                await store.read_tool_result_slice(binding, tampered.path, None, None)
    finally:
        await store.stop()


@pytest.mark.asyncio
async def test_manifest_representation_flip_is_refused_while_the_process_lives(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """F2: ``representation`` is part of what the process committed, so a flip is refused.

    Changing only the manifest's ``representation`` (``text`` to ``python-repr``)
    leaves a structurally valid manifest, so only the process's own record can tell.
    The store that committed the artifact refuses the read; a second store on the
    same root has no record (the documented restart residual) and serves the flipped
    value.
    """
    _assert_provenance()
    registries = _recording_instances(monkeypatch, "CommittedArtifacts")
    first, binding = await _running(tmp_path)
    try:
        reference = await first.store.store_tool_result(binding, _capture("original text"))
        second, rebound = await _running(tmp_path)  # a second store on the same root: it has no record
        try:
            artifact = _artifact_dir(reference)
            manifest_path = artifact / "manifest.json"
            committed = json.loads(manifest_path.read_bytes())
            untouched = {name: (artifact / name).read_bytes() for name in ("payload.jsonl", "outline.json")}
            # Premise: the artifact was committed as text and reads back as text; the first store
            # holds a record of it and the second holds none.
            assert reference.representation == "text" and committed["representation"] == "text"
            assert len(registries) == 2 and len(registries[0]) == 1 and len(registries[1]) == 0
            before = await first.store.read_tool_result_slice(binding, reference.path, None, None)
            assert before.text == "original text" and before.reference.representation == "text"
            # Rewrite that one manifest field and nothing else.
            manifest_path.write_text(json.dumps({**committed, "representation": "python-repr"}), encoding="ascii")
            flipped = json.loads(manifest_path.read_bytes())
            assert flipped["representation"] == "python-repr"
            assert {k: v for k, v in flipped.items() if k != "representation"} == {
                k: v for k, v in committed.items() if k != "representation"
            }
            assert {name: (artifact / name).read_bytes() for name in untouched} == untouched
            # Premise: without a record the flip is valid on its own. The second store serves it
            # and the flipped value reaches the consumer, so the refusal below cannot be the
            # manifest validation.
            served = await second.store.read_tool_result_slice(rebound, reference.path, None, None)
            assert served.text == "original text" and served.reference.representation == "python-repr"
            # Outcome: the store that committed it refuses; the store with no record still serves it.
            with pytest.raises(WorkspaceResultError, match="^payload_changed$"):
                await first.store.read_tool_result_slice(binding, reference.path, None, None)
            again = await second.store.read_tool_result_slice(rebound, reference.path, None, None)
            assert again.text == "original text" and again.reference.representation == "python-repr"
        finally:
            await second.store.stop()
    finally:
        await first.store.stop()


@pytest.mark.asyncio
async def test_after_restart_a_consistent_rewrite_is_the_documented_residual(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """F2, documented behaviour: after a restart a new store has no record of what was committed.

    Documented outcome: "after a restart, a read can check only that the payload,
    outline and manifest agree with one another". A consistent rewrite is therefore
    served before ``generation_expiry(GEN)`` and refused with ``result_expired`` from
    ``generation_expiry(GEN)`` on, never later: that bound is decided from the
    directory name alone.
    """
    _assert_provenance()
    registries = _recording_instances(monkeypatch, "CommittedArtifacts")
    first, binding = await _running(tmp_path)
    try:
        reference = await first.store.store_tool_result(binding, _capture("original text"))
        assert len(registries) == 1 and len(registries[0]) == 1, "premise: the first process recorded it"
    finally:
        await first.store.stop()
    second, rebound = await _running(tmp_path)  # a NEW store on the same root
    try:
        assert len(registries) == 2 and len(registries[1]) == 0, "premise: the restarted store has no record"
        revised = _capture("outside replacement")
        last_second = GEN_START + GENERATION_SECONDS - 1.0
        _rewrite_artifact(reference, revised, committed_at=last_second)
        assert _files_agree(reference, revised) and last_second > reference.committed_at
        clock = second.clock

        async def read() -> str:
            return (await second.store.read_tool_result_slice(rebound, reference.path, None, None)).text

        # Served, including past the original expiry, before generation_expiry(GEN).
        assert await read() == revised.text
        clock[0] = reference.expires_at
        assert await read() == revised.text
        clock[0] = EXPIRY - 2.0
        assert await read() == revised.text
        # Refused from generation_expiry(GEN) on, and never later.
        for moment in (EXPIRY, EXPIRY + 1.0, EXPIRY + RESULT_RETENTION_SECONDS, ESCALATION):
            clock[0] = moment
            with pytest.raises(WorkspaceResultError, match="^result_expired$"):
                await read()
    finally:
        await second.store.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize("committed_at", [GEN_START - 1.0, GEN_START + GENERATION_SECONDS])
async def test_after_restart_an_out_of_hour_committed_at_is_an_invalid_manifest(
    tmp_path: Path, committed_at: float,
) -> None:
    """Where there is no registry the commit-hour range check still stands.

    In the committing process the same tamper is refused earlier, as changed
    content; after a restart only this check, which needs nothing but the
    generation's name, is left to refuse it.
    """
    _assert_provenance()
    first, binding = await _running(tmp_path)
    try:
        reference = await first.store.store_tool_result(binding, _capture("original text"))
    finally:
        await first.store.stop()
    manifest_path = _artifact_dir(reference) / "manifest.json"
    manifest = json.loads(manifest_path.read_bytes())
    manifest["committed_at"] = committed_at
    manifest_path.write_text(json.dumps(manifest), encoding="ascii")
    assert not GEN_START <= committed_at < GEN_START + GENERATION_SECONDS, "premise: outside the hour"
    second, rebound = await _running(tmp_path)
    try:
        with pytest.raises(WorkspaceResultError, match="^manifest_invalid$"):
            await second.store.read_tool_result_slice(rebound, reference.path, None, None)
    finally:
        await second.store.stop()


@pytest.mark.asyncio
async def test_registry_bucket_evicted_with_its_generation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    registries = _recording_instances(monkeypatch, "CommittedArtifacts")
    harness, binding, expired, live = await _retention_pair(tmp_path)
    store, clock = harness.store, harness.clock
    try:
        assert len(registries) == 1, "premise: the store built exactly one registry"
        [registry] = registries
        assert len(registry) == 2, "premise: both artifacts are recorded before the sweep"
        # Not evicted early: a sweep one second before the generation's expiry removes nothing.
        clock[0] = EXPIRY - 1.0
        assert await store.reap_tool_results() == WorkspaceReapResult()
        assert len(registry) == 2 and _generation_dir(expired).is_dir()
        clock[0] = EXPIRY
        assert (await store.reap_tool_results()).deleted == 1
        assert not _generation_dir(expired).exists()
        assert len(registry) == 1, "the expired generation's bucket is gone and the live one's is not"
        # The live bucket still does its job: a consistent rewrite of it is still refused.
        revised = _capture("outside replacement")
        _rewrite_artifact(live, revised)
        assert _files_agree(live, revised)
        with pytest.raises(WorkspaceResultError, match="^payload_changed$"):
            await store.read_tool_result_slice(binding, live.path, None, None)
    finally:
        await store.stop()


# --- Call 4 repairs: F3 (settle against the anchor) and F4 (POSIX relocation) ---------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("variant", ["swapped-on-disk", "injected-verify"])
async def test_identity_change_inside_expired_generation_is_documented_outside_behaviour(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, variant: str,
) -> None:
    """F3, port of the reviewer's ``child-identity`` probe.

    Documented outcome: "An entry inside an expired generation whose identity
    changes while the reaper removes it is treated as content placed there by a
    process outside ProbOS." It is left for the next sweep, nothing latches, and
    nothing the swap moved away is followed. ``injected-verify`` is the variant
    that runs wherever the on-disk swap cannot.
    """
    _assert_provenance()
    harness, binding = await _running(tmp_path)
    store, clock = harness.store, harness.clock
    try:
        reference = await store.store_tool_result(binding, _capture("original text"))
        artifact = _artifact_dir(reference)
        moved = tmp_path / "moved-artifact"
        original = {name: (artifact / name).read_bytes() for name in ("payload.jsonl", "outline.json", "manifest.json")}
        assert not moved.exists() and not moved.is_relative_to(store.root), "premise: outside the workspace root"
        observed: list[int] = []
        swapped: list[int] = []
        before = artifact.lstat().st_ino
        if variant == "swapped-on-disk":
            real_lstat = Path.lstat

            def changing(path: Path) -> os.stat_result:
                info = real_lstat(path)
                if path == artifact:
                    observed.append(info.st_ino)
                    if len(observed) == 2:  # the open of the artifact directory, after the walker's own look
                        artifact.rename(moved)
                        artifact.mkdir()
                        swapped.append(real_lstat(artifact).st_ino)
                return info

            monkeypatch.setattr(Path, "lstat", changing)
        else:
            real_verify = PinnedDirectory.verify
            inside = [False]

            def verify(directory: PinnedDirectory) -> None:
                real_verify(directory)
                if inside[0]:
                    return
                inside[0] = True
                try:
                    where = directory.path  # re-enters this wrapper, inertly
                finally:
                    inside[0] = False
                if where == artifact:
                    observed.append(len(observed))
                    if len(observed) == 2:  # the child is open; its first verification was the open's own
                        raise FileAccessDenied("", "directory identity changed")

            monkeypatch.setattr(PinnedDirectory, "verify", verify)
        clock[0] = EXPIRY
        first = await store.reap_tool_results()
        # Premises: the identity change happened where the variant says, and before any result below.
        assert len(observed) >= 2
        if variant == "swapped-on-disk":
            assert observed[:2] == [before, before] and len(swapped) == 1 and swapped[0] != before
            assert {name: (moved / name).read_bytes() for name in original} == original
        assert first.skipped >= 1 and first.failed == 0 and first.deleted == 0 and first.deferred == 0
        admitted = await store.store_tool_result(binding, _capture("publication stays admitted"))
        assert (await store.read_tool_result_slice(binding, admitted.path, 0, 11)).text == "publication"
        second = await store.reap_tool_results()
        assert second.deleted == 1 and second.failed == 0 and not _generation_dir(reference).exists()
        if variant == "swapped-on-disk":
            # Nothing was followed: what the swap moved away is still exactly as it was.
            assert {name: (moved / name).read_bytes() for name in original} == original
    finally:
        await store.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize("variant", [
    "injected",
    pytest.param("renamed-namespace", marks=pytest.mark.skipif(
        sys.platform == "win32",
        reason="AD-1240: Windows anchor handles deny renaming a directory the sweep holds open",
    )),
])
async def test_ancestor_change_above_generation_during_removal_latches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, variant: str,
) -> None:
    """F3: a change anywhere from the workspace root to ``.tool-results`` is an integrity failure.

    A change above ``<GEN>`` while the walk is inside it is not foreign content:
    nothing is dismissed as skipped, publication latches until restart, and an
    unexpired generation in the namespace is left intact. ``injected`` runs
    everywhere: the walker's pin of the artifact directory is refused and the
    anchor's own ``verify()`` raises once when the settle asks it, so exactly one
    failure is counted. ``renamed-namespace`` is the real rename, which only POSIX
    allows while the sweep holds the namespace open; that break persists, and a
    persistent break is counted at every enclosing level of the walk (three), so
    only ``failed >= 1`` is asserted there.
    """
    harness, binding, expired, live = await _retention_pair(tmp_path)
    store = harness.store
    try:
        namespace, generation, artifact = _namespace_dir(expired), _generation_dir(expired), _artifact_dir(expired)
        restore: Callable[[], None]
        if variant == "injected":
            armed = [False]
            pinned: list[Path] = []
            refused: list[Path] = []
            inside = [False]
            real_pin = store_module.pin_directory
            real_verify = PinnedDirectory.verify

            @contextmanager
            def pinning(path: Path, **kwargs: Any) -> Any:
                if path == artifact and not pinned:
                    pinned.append(path)
                    armed[0] = True
                    raise FileAccessDenied("", "directory identity changed")  # the new pin refuses the changed chain
                with real_pin(path, **kwargs) as opened:
                    yield opened

            def verify(directory: PinnedDirectory) -> None:
                real_verify(directory)
                if not armed[0] or inside[0]:
                    return
                inside[0] = True
                try:
                    where = directory.path  # re-enters this wrapper, inertly
                finally:
                    inside[0] = False
                if where == namespace:  # the anchor, asked once by the settle
                    armed[0] = False
                    refused.append(where)
                    raise FileAccessDenied("", "directory identity changed")

            monkeypatch.setattr(store_module, "pin_directory", pinning)
            monkeypatch.setattr(PinnedDirectory, "verify", verify)
            restore = lambda: None  # noqa: E731  (the injected break was one-shot and is already spent)
        else:
            moved = tmp_path / "moved-namespace"
            renamed: list[Path] = []
            real_names = PinnedDirectory.list_names

            def listing(directory: PinnedDirectory) -> tuple[str, ...]:
                found = real_names(directory)
                if directory.path == generation and not renamed:
                    namespace.rename(moved)  # the walk is inside the generation
                    renamed.append(namespace)
                return found

            monkeypatch.setattr(PinnedDirectory, "list_names", listing)
            restore = lambda: moved.rename(namespace)  # noqa: E731
        outcome = await store.reap_tool_results()
        # Premises: the ancestor change happened while the walk was inside the expired generation.
        if variant == "injected":
            assert pinned == [artifact] and refused == [namespace], "the injected raise was reached"
            held = Path(live.path)
        else:
            assert renamed == [namespace] and moved.is_dir() and not namespace.exists()
            held = moved / Path(live.path).relative_to(namespace)
        assert held.is_file(), "the unexpired generation is intact"
        assert (held.parents[3] / generation.name).is_dir(), "nothing of the expired generation was removed"
        assert outcome.skipped == 0 and outcome.deleted == 0, variant
        assert outcome.failed == 1 if variant == "injected" else outcome.failed >= 1, variant
        await _assert_latched_until_restart(harness, binding, restore)
    finally:
        await store.stop()


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="AD-1240: relocating a directory the sweep holds open is a POSIX premise",
)
@pytest.mark.asyncio
async def test_posix_relocation_during_removal_is_documented(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """F4, a documented POSIX residual.

    Documented outcome: "removal acts on directory objects that were verified to be
    inside the expired generation when they were opened, not on their current
    pathnames". A process outside ProbOS relocates the artifact directory between
    the primitive's own check and its ``unlink`` and leaves another directory at the
    old path. The unlink goes through the directory it holds open, so that entry is
    removed from the directory's new location; the next check then finds the path
    naming a different directory, which is foreign (inside the generation), never a
    latch. The paired variant that runs on both platforms is the ``injected-verify``
    case of the identity-change test above. It first runs on CI.
    """
    harness, binding = await _running(tmp_path)
    store, clock = harness.store, harness.clock
    try:
        reference = await store.store_tool_result(binding, _capture("body"))
        artifact = _artifact_dir(reference)
        moved = tmp_path / "relocated-artifact"
        assert not moved.exists() and not moved.is_relative_to(store.root), "premise: outside the root"
        assert sorted(path.name for path in artifact.iterdir()) == ["manifest.json", "outline.json", "payload.jsonl"]
        events: list[str] = []
        real_unlink = os.unlink

        def unlinking(name: str, *, dir_fd: int | None = None) -> None:
            if not events:
                artifact.rename(moved)  # relocate the directory the walker holds open ...
                artifact.mkdir()  # ... and leave another one at its old path
                events.append("relocated")
            events.append(f"unlink {name}")
            real_unlink(name, dir_fd=dir_fd)

        monkeypatch.setattr(os, "unlink", unlinking)
        clock[0] = EXPIRY
        outcome = await store.reap_tool_results()
        monkeypatch.setattr(os, "unlink", real_unlink)
        # Premises: the relocation happened before the unlink, which then ran through the open directory.
        assert events[:2] == ["relocated", "unlink manifest.json"]
        assert moved.is_dir() and artifact.is_dir() and artifact.lstat().st_ino != moved.lstat().st_ino
        # Documented outcome: the entry is gone from its NEW location, every other entry there survives,
        # and the check that followed treated the change as foreign.
        assert not (moved / "manifest.json").exists()
        assert sorted(path.name for path in moved.iterdir()) == ["outline.json", "payload.jsonl"]
        assert outcome.skipped >= 1 and outcome.failed == 0 and outcome.deleted == 0
        admitted = await store.store_tool_result(binding, _capture("publication stays admitted"))
        assert (await store.read_tool_result_slice(binding, admitted.path, 0, 11)).text == "publication"
    finally:
        await store.stop()


# --- Call 4 repairs: F5 (root and namespace operations retry, defer and escalate) -------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("where", ["probe", "root-pin", "root-list", "namespace-pin", "namespace-list"])
async def test_root_transient_defers_without_latch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, where: str,
) -> None:
    """F5, port of the reviewer's ``root-transient`` probe.

    A brief sharing failure on a root or namespace operation is retried under the
    sweep's policy on the recorded clock and, once exhausted, deferred with a
    WARNING. It used to escape as a sweep exception and latch publication.
    """
    _assert_provenance()
    harness, binding = await _running(tmp_path)
    store = harness.store
    try:
        reference = await store.store_tool_result(binding, _capture("body"))
        namespace = _namespace_dir(reference)
        assert store.root.is_dir() and namespace.is_dir() and harness.sleeps == []
        if where == "probe":
            busy = _busy_pin(monkeypatch, store.root)
        elif where == "root-pin":
            busy = _busy_pin(monkeypatch, store.root, after=1)  # the probe's own pin gets through
        elif where == "root-list":
            busy = _busy_listing(monkeypatch, store.root)
        elif where == "namespace-pin":
            busy = _busy_pin(monkeypatch, namespace)
        else:
            busy = _busy_listing(monkeypatch, namespace)
        caplog.set_level(logging.INFO, logger=store_module.__name__)
        outcome = await store.reap_tool_results()
        assert len(busy.hits) == 4, "premise: the failing call was attempted once per retry attempt"
        assert harness.sleeps == [0.05, 0.2, 0.5], "retried under the sweep's policy, on the recorded clock"
        assert outcome == WorkspaceReapResult(deferred=1)
        subject = "workspace root" if where in ("probe", "root-pin", "root-list") else "owner namespace"
        warnings = [
            record for record in caplog.records
            if record.levelno == logging.WARNING and subject in record.getMessage()
        ]
        assert len(warnings) == 1 and "transient failure" in warnings[0].getMessage()
        assert not [record for record in caplog.records if record.levelno >= logging.ERROR]
        admitted = await store.store_tool_result(binding, _capture("publication stays admitted"))
        assert (await store.read_tool_result_slice(binding, admitted.path, 0, 11)).text == "publication"
    finally:
        await store.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize("where", ["probe", "root-list"])
async def test_root_integrity_failure_is_not_retried_and_latches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, where: str,
) -> None:
    """F5: only a transient failure at the root defers; any other failure still raises and latches."""
    _assert_provenance()
    harness, binding = await _running(tmp_path)
    store = harness.store
    try:
        await store.store_tool_result(binding, _capture("body"))

        def failure() -> OSError:
            return OSError(errno.EIO, "fixture I/O failure")

        assert classify_os_error(failure(), platform=sys.platform) == "integrity", "premise: not transient"
        busy = (
            _busy_pin(monkeypatch, store.root, error=failure) if where == "probe"
            else _busy_listing(monkeypatch, store.root, error=failure)
        )
        with pytest.raises(WorkspaceResultError, match="^workspace_reap_failed$"):
            await store.reap_tool_results()
        assert len(busy.hits) == 1 and harness.sleeps == [], "an integrity failure is never retried"
        with pytest.raises(WorkspaceResultError, match="workspace_unavailable"):
            await store.store_tool_result(binding, _capture("latched"))
    finally:
        await store.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize("where", ["workspace-root", "owner-namespace"])
async def test_persistent_root_deferral_escalates_after_one_retention_period(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, where: str,
) -> None:
    """F5: a root or namespace deferred for one retention period latches publication."""
    _assert_provenance()
    harness, binding = await _running(tmp_path)
    store, clock = harness.store, harness.clock
    try:
        reference = await store.store_tool_result(binding, _capture("body"))
        target = store.root if where == "workspace-root" else _namespace_dir(reference)
        assert target.is_dir() and clock[0] == T0
        busy = _busy_pin(monkeypatch, target)
        assert await store.reap_tool_results() == WorkspaceReapResult(deferred=1)  # stamps the first deferral
        assert busy.hits, "premise: the target really failed transiently"
        # One second short of a full retention period: still a deferral, nothing latched.
        clock[0] = T0 + RESULT_RETENTION_SECONDS - 1.0
        assert await store.reap_tool_results() == WorkspaceReapResult(deferred=1)
        await store.store_tool_result(binding, _capture("still admitted"))
        # One retention period after the first deferral it counts as a failure, which latches.
        clock[0] = T0 + RESULT_RETENTION_SECONDS
        assert await store.reap_tool_results() == WorkspaceReapResult(failed=1)
        await _assert_latched_until_restart(harness, binding, lambda: setattr(busy, "on", False))
    finally:
        await store.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize("where", ["workspace-root", "owner-namespace"])
async def test_a_clean_sweep_restarts_the_deferral_period(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, where: str,
) -> None:
    _assert_provenance()
    harness, binding = await _running(tmp_path)
    store, clock = harness.store, harness.clock
    try:
        reference = await store.store_tool_result(binding, _capture("body"))
        target = store.root if where == "workspace-root" else _namespace_dir(reference)
        busy = _busy_pin(monkeypatch, target)
        assert await store.reap_tool_results() == WorkspaceReapResult(deferred=1)  # stamped at T0
        busy.on = False
        clock[0] = T0 + 10.0
        assert await store.reap_tool_results() == WorkspaceReapResult(), "a clean sweep clears the stamp"
        busy.on = True
        hits_before = len(busy.hits)
        clock[0] = T0 + RESULT_RETENTION_SECONDS + 10.0  # more than R after the FIRST deferral
        assert await store.reap_tool_results() == WorkspaceReapResult(deferred=1), "a new period begins"
        assert len(busy.hits) > hits_before, "premise: the target failed again"
        await store.store_tool_result(binding, _capture("still admitted"))
    finally:
        await store.stop()


# --- Call 4 repairs: F7 (the post-sweep wording follows the latch) ------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("plan,latched", [
    ([WorkspaceReapResult(failed=1, deferred=1)], True),
    ([WorkspaceReapResult(deferred=1)], False),
    ([WorkspaceReapResult(failed=1), WorkspaceReapResult(deferred=1)], True),
])
async def test_deferral_line_states_publication_availability_from_the_latch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
    plan: list[WorkspaceReapResult], latched: bool,
) -> None:
    """F7: "publication stays enabled" only when the store is not latched.

    The cases are the reviewer's mixed failed/deferred sweep, a deferral-only
    sweep, and a deferral after an earlier sweep already latched the store.
    """
    _assert_provenance()
    harness, binding = await _running(tmp_path)
    store = harness.store
    results = iter(plan)
    monkeypatch.setattr(GenerationReaper, "sweep", lambda self, now: next(results))
    caplog.set_level(logging.INFO, logger=store_module.__name__)
    try:
        for _ in plan:
            await store.reap_tool_results()
        lines = [
            record.getMessage() for record in caplog.records
            if record.getMessage().startswith("Workspace result sweep deferred")
        ]
        assert len(lines) == 1, "premise: exactly one deferral line was logged"
        if latched:
            with pytest.raises(WorkspaceResultError, match="workspace_unavailable"):
                await store.store_tool_result(binding, _capture("must not publish"))
            assert "publication stays enabled" not in lines[0] and "unavailable" in lines[0]
        else:
            admitted = await store.store_tool_result(binding, _capture("admitted"))
            assert (await store.read_tool_result_slice(binding, admitted.path, 0, 3)).text == "adm"
            assert "publication stays enabled" in lines[0]
    finally:
        await store.stop()


# --- Call 9 repairs: A1-1 to A1-6 (clock sample, commitment record, remembered anchors, cap rotation, retry whole) ---


@pytest.mark.asyncio
async def test_sweep_decides_every_removal_from_its_one_clock_sample(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A1-1, documented behaviour: a sweep decides every removal from the one clock sample it took.

    The documented residual: "A sweep decides every removal from the one clock sample
    it takes inside the store lock; if the clock steps backwards while that sweep is
    removing, an artifact it removes may be one that a reading of the stepped-back
    clock would still call unexpired. Reads are serialized with sweeps, so no read
    observes the clock in the middle of a sweep." This is the contract and not a
    defect: by the sweep's own sample the artifact was already expired, and holding a
    removal back for a clock that moves mid-sweep would need a clock-coordination
    mechanism the design does not have.
    """
    _assert_provenance()
    harness, binding = await _running(tmp_path)
    store, clock = harness.store, harness.clock
    try:
        reference = await store.store_tool_result(binding, _capture("body"))
        payload = Path(reference.path)
        clock[0] = EXPIRY
        sampled: list[float] = []
        original = PinnedDirectory.remove_file

        def stepping(directory: PinnedDirectory, leaf: str) -> None:
            if not sampled:
                sampled.append(clock[0])  # what the sweep's one sample was
                clock[0] = T0  # the clock steps backwards while the sweep is already removing
            original(directory, leaf)

        monkeypatch.setattr(PinnedDirectory, "remove_file", stepping)
        assert payload.is_file() and T0 < reference.expires_at < EXPIRY, "premise: expired at the sample, live at T0"
        outcome = await store.reap_tool_results()
        assert sampled == [EXPIRY] and clock[0] == T0, "premise: the clock stepped back mid-removal"
        assert outcome.deleted == 1 and outcome.failed == 0
        assert not payload.exists() and not _generation_dir(reference).exists()
    finally:
        await store.stop()


@pytest.mark.asyncio
async def test_deferred_generation_keeps_its_commitment_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A1-2: a registry bucket is evicted only once its generation was removed whole or found already gone.

    A deferred generation is still on disk and, if the clock moves back, readable
    again, so the record of what ProbOS committed must outlive the deferral: a
    consistent rewrite of its files is still refused. Evicting the bucket when the
    removal merely starts would let that rewrite be served.
    """
    _assert_provenance()
    registries = _recording_instances(monkeypatch, "CommittedArtifacts")
    harness, binding = await _running(tmp_path)
    store, clock = harness.store, harness.clock
    try:
        reference = await store.store_tool_result(binding, _capture("original text"))
        generation = _generation_dir(reference)
        assert len(registries) == 1 and len(registries[0]) == 1, "premise: the artifact is recorded"
        [registry] = registries
        busy = _busy_pin(monkeypatch, generation)
        clock[0] = EXPIRY
        deferred = await store.reap_tool_results()
        assert busy.hits, "premise: the generation's own pin failed transiently"
        assert deferred.deferred == 1 and deferred.deleted == 0 and deferred.failed == 0
        assert generation.is_dir() and Path(reference.path).is_file(), "the deferred generation keeps its files"
        assert len(registry) == 1, "and its commitment record"
        # The fault clears and the clock moves back, so the artifact is readable again:
        # a consistent rewrite of it must still be refused.
        busy.on = False
        clock[0] = T0
        revised = _capture("outside replacement")
        _rewrite_artifact(reference, revised)
        assert _files_agree(reference, revised), "premise: the rewrite is consistent on its own"
        with pytest.raises(WorkspaceResultError, match="^payload_changed$"):
            await store.read_tool_result_slice(binding, reference.path, None, None)
        clock[0] = EXPIRY
        finished = await store.reap_tool_results()
        assert finished.deleted == 1 and finished.failed == 0 and not generation.exists()
        assert len(registry) == 0, "removed whole: the bucket goes with its generation"
    finally:
        await store.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize("anchor", ["root", "namespace"])
async def test_remembered_anchor_missing_is_an_integrity_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, anchor: str,
) -> None:
    """A1-3: a root or owner namespace this process pinned, and that is now missing, is not "never created".

    "Remembered" means this process's ``DirectoryIdentities`` holds the anchor's exact
    path, which a publication or a successful sweep pin sets. Its absence is then a
    change to the anchor: the sweep reports a failure and publication latches until a
    completed stop and a successful start. In a live process the pin's own memory
    normally refuses such a directory first, with ``FileAccessDenied`` (see
    ``test_anchor_removed_while_the_process_runs_latches_publication``). The reaper's
    rule is the second guard, for a pin that reports a plain ``FileNotFoundError``,
    for example a directory that vanishes between the pin's existence check and its
    open. The pin's memory is switched off for this store, so that the real removal
    reaches the rule instead of being refused above it.
    """
    _assert_provenance()
    caches = _recording_instances(monkeypatch, "DirectoryIdentities")
    harness, binding = await _running(tmp_path)
    store = harness.store
    try:
        reference = await store.store_tool_result(binding, _capture("body"))
        target = store.root if anchor == "root" else _namespace_dir(reference)
        [cache] = caches
        assert cache.knows(target), "premise: this process pinned the anchor, so it remembers it"
        shutil.rmtree(target)
        assert not target.exists(), "premise: the anchor is really gone"
        monkeypatch.setattr(cache, "expected", lambda: ())
        outcome = await store.reap_tool_results()
        assert outcome.failed >= 1 and outcome.deleted == 0
        with pytest.raises(WorkspaceResultError, match="workspace_unavailable"):
            await store.store_tool_result(binding, _capture("refused after the latch"))
    finally:
        await store.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize("anchor", ["root", "namespace"])
async def test_anchor_removed_while_the_process_runs_latches_publication(
    tmp_path: Path, anchor: str,
) -> None:
    """A1-3, the whole chain with nothing switched off: publish, remove the anchor, sweep, latch, refuse.

    A remembered anchor that is removed under a running process is refused by the
    pin itself (``FileAccessDenied``: a previously pinned directory disappeared), so
    the root sweep raises ``workspace_reap_failed`` and the namespace sweep reports a
    failure; either way publication is latched.
    """
    _assert_provenance()
    harness, binding = await _running(tmp_path)
    store = harness.store
    try:
        reference = await store.store_tool_result(binding, _capture("body"))
        target = store.root if anchor == "root" else _namespace_dir(reference)
        shutil.rmtree(target)
        assert not target.exists(), "premise: the anchor is really gone"
        if anchor == "root":
            with pytest.raises(WorkspaceResultError, match="^workspace_reap_failed$"):
                await store.reap_tool_results()
        else:
            outcome = await store.reap_tool_results()
            assert outcome.failed == 1 and outcome.deleted == 0
        with pytest.raises(WorkspaceResultError, match="workspace_unavailable"):
            await store.store_tool_result(binding, _capture("refused after the latch"))
    finally:
        await store.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize("anchor", ["root", "namespace", "restart"])
async def test_never_created_anchor_is_a_healthy_empty_sweep(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, anchor: str,
) -> None:
    """A1-3: a root or owner namespace this process never pinned is a healthy empty sweep.

    ``root`` is a store with no publication and no root, ``namespace`` an owner
    directory without ``.tool-results``, and ``restart`` the documented residual: "A
    root or owner namespace that disappears while ProbOS is stopped is treated after
    the restart as never created."
    """
    _assert_provenance()
    caches = _recording_instances(monkeypatch, "DirectoryIdentities")
    root = tmp_path / "workspaces"
    if anchor == "restart":
        first, first_binding = await _running(tmp_path)
        try:
            reference = await first.store.store_tool_result(first_binding, _capture("body"))
        finally:
            await first.store.stop()
        shutil.rmtree(_namespace_dir(reference))
    store = make_store(root).store  # after a restart this is a NEW store on the same root
    binding = store.bind_agent("agent-a", _agent())
    if anchor == "namespace":
        (root / binding.owner_key).mkdir(parents=True)
    target = root if anchor == "root" else root / binding.owner_key / RESULT_DIRECTORY
    cache = caches[-1]
    try:
        assert not target.exists() and not cache.knows(target), "premise: absent, and never pinned by this process"
        await store.start()  # the startup sweep must not fail
        outcome = await store.reap_tool_results()
        assert outcome == WorkspaceReapResult(), "a healthy empty sweep: nothing failed, nothing deferred"
        assert not target.exists() and not cache.knows(target), "nothing is created and nothing is remembered"
        admitted = await store.store_tool_result(binding, _capture("publication is admitted"))
        assert Path(admitted.path).is_file()
    finally:
        await store.stop()


@pytest.mark.asyncio
async def test_sweep_listing_remembers_the_namespace_so_its_removal_is_an_integrity_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A1-3: the namespace listing pin is one of the sweep pins that remember.

    After a restart a store remembers nothing until its own sweep pins the
    namespace. From then on a namespace that vanishes is a changed anchor, a
    failure that latches; with nothing remembered it would be a healthy empty sweep.
    """
    _assert_provenance()
    caches = _recording_instances(monkeypatch, "DirectoryIdentities")
    first, first_binding = await _running(tmp_path)
    try:
        reference = await first.store.store_tool_result(first_binding, _capture("body"))
    finally:
        await first.store.stop()
    namespace = _namespace_dir(reference)
    second, binding = await _running(tmp_path)  # a NEW store; its startup sweep pins the namespace
    store = second.store
    try:
        assert len(caches) == 2 and namespace.is_dir()
        assert caches[1].knows(namespace), "premise: nothing but the sweep's listing pin can have remembered it"
        shutil.rmtree(namespace)
        outcome = await store.reap_tool_results()
        assert outcome.failed == 1 and outcome.deleted == 0
        with pytest.raises(WorkspaceResultError, match="workspace_unavailable"):
            await store.store_tool_result(binding, _capture("refused after the latch"))
    finally:
        await store.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize("where", ["generation", "owner"])
async def test_capped_sweeps_rotate_to_later_generations(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, where: str,
) -> None:
    """A1-4: foreign entries in one expired generation can delay, but not prevent, the removal of others.

    The cap is exactly what the later generation costs: the generation and
    everything in it. The earlier one holds cap - 1 foreign entries that sort first
    and are retained, so on its own it spends the whole budget. A sweep that always
    started in the same place would never get past it; a capped sweep resumes after
    the generation, and after the owner, where its budget ran out. ``owner`` is the
    same scene across two owner directories, which is the cursor at the root.
    """
    _assert_provenance()
    harness, binding = await _running(tmp_path)
    store, clock = harness.store, harness.clock
    try:
        if where == "generation":
            earlier = await store.store_tool_result(binding, _capture("earlier body"))
            clock[0] = T0 + GENERATION_SECONDS
            later = await store.store_tool_result(binding, _capture("later body"))
            clock[0] = expiry_of(generation_of(later.path))
            assert _namespace_dir(earlier) == _namespace_dir(later), "premise: one owner, two generations"
            assert generation_of(earlier.path) < generation_of(later.path)
        else:
            other = store.bind_agent("agent-b", _agent("agent-b", "Other owner"))
            one = await store.store_tool_result(binding, _capture("one body"))
            two = await store.store_tool_result(other, _capture("two body"))
            earlier, later = sorted((one, two), key=lambda ref: _namespace_dir(ref).parent.name)
            clock[0] = EXPIRY
            assert _namespace_dir(earlier) != _namespace_dir(later), "premise: two owners"
            assert generation_of(earlier.path) == generation_of(later.path) == GEN
        holder, victim = _generation_dir(earlier), _generation_dir(later)
        cap = 1 + len(list(victim.rglob("*")))  # the later generation, and everything in it
        foreign = [holder / f"000-foreign-{index}" for index in range(cap - 1)]
        for path in foreign:
            path.write_bytes(b"outside material")
        marked = {(info.st_dev, info.st_ino) for info in (path.lstat() for path in foreign)}
        real_reparse = store_module.is_reparse_point
        monkeypatch.setattr(
            store_module, "is_reparse_point",
            lambda info: (info.st_dev, info.st_ino) in marked or real_reparse(info),
        )
        monkeypatch.setattr(store_module, "SWEEP_ENTRY_CAP", cap)
        assert len(marked) == cap - 1 > 0, "premise: every foreign entry has an identity of its own"
        assert 1 + len(list(holder.rglob("*"))) > cap, "premise: the earlier generation alone exhausts the budget"
        capped = await store.reap_tool_results()
        assert capped.deleted == 0 and capped.failed == 0 and capped.deferred >= 1
        assert Path(later.path).is_file(), "the first sweep spent its whole budget on the earlier generation"
        resumed = await store.reap_tool_results()
        assert resumed.deleted == 1 and resumed.failed == 0
        assert not victim.exists() and not Path(later.path).exists(), "the second sweep reached the later one"
        assert holder.is_dir() and all(path.is_file() for path in foreign), "foreign entries keep their generation"
    finally:
        await store.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize("where,after,pins,retried", [
    pytest.param("root", 0, 3, True, id="root-probe"),
    pytest.param("root", 1, 3, True, id="root-listing"),
    pytest.param("namespace", 0, 3, True, id="namespace-listing"),
    pytest.param("namespace", 1, 2, False, id="namespace-work"),
])
async def test_transient_failure_at_context_exit_is_retried(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, where: str, after: int, pins: int, retried: bool,
) -> None:
    """A1-5: a transient failure at the closing check of a root or namespace pin is retried whole.

    The climb probe, the root pin with its listing, and the namespace pin with its
    listing each run as one unit (pin, use, verify on close) under the sweep's
    retry policy, with a fresh pin for every attempt. The namespace pin that
    generation removal runs under is entered under the runner but its closing check
    is not retried, because the removal work is never repeated: a transient failure
    there defers the namespace after the generation was removed (``namespace-work``).
    """
    _assert_provenance()
    harness, binding = await _running(tmp_path)
    store, clock = harness.store, harness.clock
    try:
        reference = await store.store_tool_result(binding, _capture("body"))
        target = store.root if where == "root" else _namespace_dir(reference)
        clock[0] = EXPIRY
        assert target.is_dir() and harness.sleeps == [], "premise: nothing has been retried yet"
        busy = _busy_exit(monkeypatch, target, after=after)
        outcome = await store.reap_tool_results()
        assert busy.hits == [target] and busy.seen == pins, "premise: the closing check failed once, where intended"
        if retried:
            assert harness.sleeps == [0.05], "retried under the sweep's policy, on the recorded clock"
            assert outcome == WorkspaceReapResult(deleted=1)
        else:
            assert harness.sleeps == [], "the removal work is never repeated, so its closing check is not retried"
            assert outcome == WorkspaceReapResult(deleted=1, deferred=1)
        assert not _generation_dir(reference).exists()
    finally:
        await store.stop()


def test_directory_identities_knows_only_the_paths_it_remembers(tmp_path: Path) -> None:
    """A1-3: ``knows`` is an exact-path lookup of what this process pinned, and eviction forgets it."""
    cache = store_module.DirectoryIdentities()
    anchor = tmp_path / "workspaces"
    assert cache.knows(anchor) is False, "an empty cache knows nothing"
    cache.remember([(anchor, (1, 2, stat.S_IFDIR)), (anchor / "owner", (1, 3, stat.S_IFDIR))])
    assert cache.knows(anchor) is True and cache.knows(anchor / "owner") is True
    assert cache.knows(anchor / "other") is False, "a sibling that was never pinned is not known"
    assert cache.knows(tmp_path) is False, "an ancestor that was never pinned is not known"
    cache.evict_under(anchor)
    assert cache.knows(anchor) is False and cache.knows(anchor / "owner") is False


@pytest.mark.parametrize("names,after,expected", [
    (["c", "a", "d", "b"], None, ["a", "b", "c", "d"]),
    (["c", "a", "d", "b"], "b", ["c", "d", "a", "b"]),  # the cursor's own name is visited last
    (["c", "a", "d", "b"], "d", ["a", "b", "c", "d"]),  # nothing sorts after it: plain order
    (["c", "a", "d", "b"], "0", ["a", "b", "c", "d"]),  # a cursor before every name: plain order
    (["c", "a", "d", "b"], "bb", ["c", "d", "a", "b"]),  # a cursor that is no longer a name still splits the order
    ([], "b", []),
    ([], None, []),
])
def test_rotated_resumes_after_the_cursor_then_wraps_round(
    names: list[str], after: str | None, expected: list[str],
) -> None:
    """A1-4: the cursor changes only the order of visits: every name appears exactly once."""
    assert store_module._rotated(names, after) == expected
    assert sorted(store_module._rotated(names, after)) == sorted(names)


# --- M4b: runtime and startup wiring of the store (Phase 1, shutdown, the real runtime) -------------------
#
# The tests above own the store's own lifecycle. These cross the seams around it: Phase 1 builds and starts
# the store, the runtime exposes it, and shutdown stops it after the pools while leaving it out of the AD-824
# background-task sweep. Nothing here sleeps on the wall clock; a store that Phase 1 builds reads the real
# clock only to name the hour of a publication, and no assertion depends on which hour that is.


class _StartService:
    """An inert Phase-1 service double: ``start()`` only."""

    async def start(self) -> None:
        return None


async def _prune() -> None:
    await asyncio.Event().wait()


def _no_waits() -> SystemConfig:
    """Shutdown without its two fixed grace waits, so no test sleeps through them."""
    return SystemConfig(memory=MemoryConfig(shutdown_write_grace_s=0.0, shutdown_dispatch_grace_s=0.0))


def _phase_one_config(root: object) -> SystemConfig:
    """A real default config whose ``execution.workspace_root`` is ``root``; the config does not validate it."""
    config = SystemConfig()
    config.execution.workspace_root = root  # type: ignore[assignment]
    return config


def _config_without_execution() -> Any:
    """What Phase 1 reads, minus the whole ``execution`` section."""
    real = SystemConfig()
    return SimpleNamespace(
        protected_execution=real.protected_execution, federation=real.federation, execution=None,
    )


async def _boot_phase_one(
    data_dir: Path, config: Any, background_register: Callable[[asyncio.Task[None]], None] | None,
) -> InfrastructureResult:
    service = _StartService()
    return await boot_infrastructure(
        service, service, service, service, service,  # type: ignore[arg-type]
        data_dir, config, _prune, background_register=background_register,
    )


async def _release_phase_one(infrastructure: InfrastructureResult) -> None:
    """Stop what a successful Phase 1 left running: the owner, the prune loop and the identity registry."""
    await infrastructure.workspace_results.stop()
    infrastructure.event_prune_task.cancel()
    await asyncio.gather(infrastructure.event_prune_task, return_exceptions=True)
    await infrastructure.identity_registry.stop()


def _record_phase_one_stores(
    monkeypatch: pytest.MonkeyPatch, journal: list[str] | None = None,
) -> list[Any]:
    """Make Phase 1 build a recording store and return every one it builds, with its lifecycle calls in order.

    ``journal``, when given, is one shared list that also receives ``store.<event>`` for each call
    (and ``store.started`` once a start completes), so a test can order the store against another
    component that writes to the same list.
    """
    built: list[Any] = []

    def note(event: str) -> None:
        if journal is not None:
            journal.append(f"store.{event}")

    class _Recording(WorkspaceResultStore):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            super().__init__(*args, **kwargs)
            self.events: list[str] = []
            built.append(self)

        async def start(self) -> None:
            self.events.append("start")
            note("start")
            try:
                await super().start()
            except BaseException as exc:
                self.events.append(f"start-raised-{type(exc).__name__}")
                note(f"start-raised-{type(exc).__name__}")
                raise
            note("started")

        async def stop(self) -> None:
            self.events.append("stop")
            note("stop")
            await super().stop()
            self.events.append("stopped")
            note("stopped")

    monkeypatch.setattr(infrastructure_module, "WorkspaceResultStore", _Recording)
    return built


def _record_identity_registries(monkeypatch: pytest.MonkeyPatch) -> list[Any]:
    """Record the identity registry Phase 1 builds: a boot that fails after it started hands it to nobody."""
    created: list[Any] = []

    def create(**kwargs: Any) -> Any:
        registry = AgentIdentityRegistry(**kwargs)
        created.append(registry)
        return registry

    monkeypatch.setattr("probos.identity.AgentIdentityRegistry", create)
    return created


def _record_identity_registry_starts(
    monkeypatch: pytest.MonkeyPatch, journal: list[str], *, error: BaseException | None = None,
) -> list[Any]:
    """Record every ``AgentIdentityRegistry.start`` (as ``identity.start`` in ``journal``), and optionally raise ``error``.

    Patched on the class, so it sees a start however Phase 1 reaches the registry. With ``error`` the
    real start never runs, so nothing is opened on disk.
    """
    real_start = AgentIdentityRegistry.start
    starts: list[Any] = []

    async def recording_start(self: AgentIdentityRegistry, *args: Any, **kwargs: Any) -> None:
        starts.append(self)
        journal.append("identity.start")
        if error is not None:
            raise error
        await real_start(self, *args, **kwargs)

    monkeypatch.setattr(AgentIdentityRegistry, "start", recording_start)
    return starts


async def _stop_identities_and_tasks(identities: list[Any], tasks: list[asyncio.Task[None]]) -> None:
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    for registry in identities:
        await registry.stop()


def test_infrastructure_result_workspace_results_is_last_and_defaults_unavailable() -> None:
    names = [field.name for field in dataclasses.fields(InfrastructureResult)]
    # Premise: main's five fields keep their order, so every older construction still binds the same way.
    assert names == [
        "identity_registry", "event_prune_task", "identity_key_binding", "execution_authority",
        "effect_broker", "workspace_results",
    ]
    by_keyword = InfrastructureResult(identity_registry=object(), event_prune_task=object())  # type: ignore[arg-type]
    by_position = InfrastructureResult(object(), object(), None, None, None)  # type: ignore[arg-type]
    assert isinstance(by_keyword.workspace_results, UnavailableWorkspaceResults)
    assert isinstance(by_position.workspace_results, UnavailableWorkspaceResults)
    assert by_position.workspace_results.background_tasks == ()


@pytest.mark.asyncio
@pytest.mark.parametrize("register", [False, True])
@pytest.mark.parametrize("relative", [False, True])
async def test_phase_one_owns_configured_root_shared_registered_reaper(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
    register: bool, relative: bool,
) -> None:
    _assert_provenance()
    monkeypatch.setenv("PROBOS_DATA_DIR", str(tmp_path / "platform-data"))
    expected_root = (
        tmp_path / "platform-data" / "execution" / "workspaces" if relative
        else tmp_path / "configured-workspaces"
    )
    configured = "data/execution/workspaces" if relative else str(expected_root)
    # Premises: the value is relative or absolute as parametrized, and resolves to the root expected below.
    assert Path(configured).is_absolute() is not relative
    assert WorkspaceManager(configured).root == expected_root
    instance_dir = tmp_path / "instance-data"
    tasks: list[asyncio.Task[None]] = []
    caplog.set_level(logging.ERROR, logger=infrastructure_module.__name__)
    infrastructure = await _boot_phase_one(
        instance_dir, _phase_one_config(configured), tasks.append if register else None,
    )
    owner = infrastructure.workspace_results
    reaper: asyncio.Task[None] | None = None
    try:
        assert not expected_root.exists(), "Phase 1 creates no workspace directory"
        if register:
            assert isinstance(owner, WorkspaceResultStore) and owner.root == expected_root
            assert len(owner.background_tasks) == 1
            reaper = owner.background_tasks[0]
            # The reaper the runtime's registry holds is the one object the owner drains.
            assert reaper in tasks and reaper.get_name() == "workspace-result-reaper" and not reaper.done()
            binding = owner.bind_agent("agent-a", _agent())
            reference = await owner.store_tool_result(binding, _capture("phase-one body"))
            assert Path(reference.path).is_relative_to(expected_root)
            assert not Path(reference.path).is_relative_to(instance_dir)
            assert (await owner.read_tool_result_slice(binding, reference.path, 0, 5)).text == "phase"
        else:
            assert isinstance(owner, UnavailableWorkspaceResults) and owner.background_tasks == ()
            assert any(
                "Workspace result store failed to start (reaper_unregistered)" in record.getMessage()
                for record in caplog.records
            ), "the missing registration is why no store started"
    finally:
        await _release_phase_one(infrastructure)
    if reaper is not None:
        assert reaper.done(), "stopping the owner drains the reaper it registered"


@pytest.mark.asyncio
async def test_phase_one_failed_owner_remains_unavailable_and_drains_registration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
) -> None:
    _assert_provenance()
    built = _record_phase_one_stores(monkeypatch)
    root = tmp_path / "not-created"
    tasks: list[asyncio.Task[None]] = []

    def register(task: asyncio.Task[None]) -> None:
        tasks.append(task)
        if task.get_name() == "workspace-result-reaper":
            raise RuntimeError(f"owned registration failure at {root}")

    caplog.set_level(logging.ERROR, logger=infrastructure_module.__name__)
    infrastructure = await _boot_phase_one(tmp_path / "data", _phase_one_config(str(root)), register)
    try:
        reapers = [task for task in tasks if task.get_name() == "workspace-result-reaper"]
        assert len(reapers) == 1, "premise: the failing registration was reached"
        assert isinstance(infrastructure.workspace_results, UnavailableWorkspaceResults)
        assert reapers[0].done() and not root.exists()
        assert len(built) == 1
        # The failed start is followed by a stop of the same owner: that is the drain.
        assert built[0].events == ["start", "start-raised-RuntimeError", "stop", "stopped"]
        messages = [record.getMessage() for record in caplog.records]
        assert any("Workspace result store failed to start (RuntimeError)" in message for message in messages)
        assert not any("owned registration failure" in message or str(root) in message for message in messages), (
            "the failure line carries the error class or code, never its text or a path"
        )
    finally:
        await _release_phase_one(infrastructure)


@pytest.mark.asyncio
async def test_phase_one_cancelled_registration_drains_owner_before_propagating(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _assert_provenance()
    built = _record_phase_one_stores(monkeypatch)
    identities = _record_identity_registries(monkeypatch)
    root = tmp_path / "not-created"
    tasks: list[asyncio.Task[None]] = []

    def register(task: asyncio.Task[None]) -> None:
        tasks.append(task)
        if task.get_name() == "workspace-result-reaper":
            current = asyncio.current_task()
            assert current is not None
            current.cancel()  # delivered at the store's next await, with the reaper already registered

    boot = asyncio.create_task(_boot_phase_one(tmp_path / "data", _phase_one_config(str(root)), register))
    try:
        with pytest.raises(asyncio.CancelledError):
            await boot
        reapers = [task for task in tasks if task.get_name() == "workspace-result-reaper"]
        assert len(reapers) == 1 and boot.cancelled(), "premise: the registration was reached and the boot cancelled"
        assert reapers[0].done(), "the reaper is drained before the cancellation propagates"
        assert len(built) == 1
        # The unwind stopped the owner after its own start raised: draining is not only start()'s doing.
        assert built[0].events == ["start", "start-raised-CancelledError", "stop", "stopped"]
        assert not root.exists()
        # The store starts before the identity registry (D4.2), so this cancelled boot never built one.
        assert identities == []
    finally:
        await _stop_identities_and_tasks(identities, tasks)


@pytest.mark.asyncio
@pytest.mark.parametrize("configured", [
    pytest.param(None, id="none"),
    pytest.param("", id="empty-string"),
    pytest.param(".", id="dot"),
    pytest.param(Path(), id="empty-path"),
    pytest.param(42, id="not-a-path"),
    pytest.param("no-execution-section", id="no-execution-section"),
])
async def test_phase_one_missing_root_keeps_typed_unavailable_owner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, configured: object,
) -> None:
    _assert_provenance()
    platform_data = tmp_path / "platform-data"
    monkeypatch.setenv("PROBOS_DATA_DIR", str(platform_data))
    built = _record_phase_one_stores(monkeypatch)
    config = _config_without_execution() if configured == "no-execution-section" else _phase_one_config(configured)
    # Premises: the config really carries the value under test, and "" and "." are what WorkspaceManager
    # would resolve to the platform data directory itself (the ambient storage that must not be selected).
    if configured == "no-execution-section":
        assert config.execution is None
    else:
        assert config.execution.workspace_root == configured
    if configured in ("", "."):
        assert WorkspaceManager(configured).root == platform_data
    tasks: list[asyncio.Task[None]] = []
    caplog.set_level(logging.ERROR, logger=infrastructure_module.__name__)
    infrastructure = await _boot_phase_one(tmp_path / "data", config, tasks.append)
    try:
        assert isinstance(infrastructure.workspace_results, UnavailableWorkspaceResults)
        assert infrastructure.workspace_results.background_tasks == ()
        assert [task.get_name() for task in tasks] == ["event-log-prune-loop"]
        assert built == [], "no store is built over a root that is missing or not a path"
        assert any(
            "root configuration is missing or not a path" in record.getMessage() for record in caplog.records
        )
        assert not platform_data.exists(), "no ambient storage was selected"
    finally:
        await _release_phase_one(infrastructure)


async def _assert_phase_one_degrades_to_unavailable(
    root: Path, anchor: Path, attempts: list[Path], expected: list[Path], *,
    data_dir: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    """R1-3's Phase-1 clause: an unavailable anchor ends the climb once and leaves the typed owner."""
    caplog.set_level(logging.ERROR, logger=infrastructure_module.__name__)
    tasks: list[asyncio.Task[None]] = []
    infrastructure = await _boot_phase_one(data_dir, _phase_one_config(str(root)), tasks.append)
    try:
        owner = infrastructure.workspace_results
        assert isinstance(owner, UnavailableWorkspaceResults), "Phase 1 degrades; it neither fails nor starts a store"
        assert attempts == expected and attempts.count(anchor) == 1, "the anchor is visited once"
        assert [task.get_name() for task in tasks] == ["event-log-prune-loop"] and owner.background_tasks == ()
        assert not root.exists() and not root.parent.exists(), "nothing is created"
        assert any(
            "Workspace result store failed to start (workspace_reap_failed)" in record.getMessage()
            for record in caplog.records
        )
        with pytest.raises(WorkspaceResultError, match="workspace_unavailable"):
            owner.bind_agent("agent-a", _agent())
    finally:
        await _release_phase_one(infrastructure)


@pytest.mark.asyncio
@pytest.mark.parametrize("failure_type", [RuntimeError, asyncio.CancelledError])
async def test_phase_one_failure_after_the_store_started_stops_it_and_reraises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure_type: type[BaseException],
) -> None:
    _assert_provenance()
    built = _record_phase_one_stores(monkeypatch)
    identities = _record_identity_registries(monkeypatch)
    root = tmp_path / "workspaces"
    handed_over: list[Any] = []

    def failing_result(**fields: Any) -> Any:
        # Injection point: the ``InfrastructureResult(...)`` construction, the last statement of Phase 1.
        # By then the store and the identity registry have both started (the store starts first, D4.2),
        # and main's unwind, which this test leaves as it is, stops only the store.
        handed_over.append(fields["workspace_results"])
        raise failure_type("injected after the store started")

    monkeypatch.setattr(infrastructure_module, "InfrastructureResult", failing_result)
    tasks: list[asyncio.Task[None]] = []
    try:
        with pytest.raises(failure_type, match="injected after the store started"):
            await _boot_phase_one(tmp_path / "data", _phase_one_config(str(root)), tasks.append)
        # Premises: the failure came after the store had started, and what was about to be exposed was
        # that started store, not the typed unavailable owner. The identity registry had been built and
        # started too (the helper stops it below, because no unwind does).
        assert len(built) == 1 and len(handed_over) == 1 and handed_over[0] is built[0]
        assert len(identities) == 1
        reapers = [task for task in tasks if task.get_name() == "workspace-result-reaper"]
        assert len(reapers) == 1
        # Outcome: the unwind stopped it, and the runtime never receives a store that is already stopped.
        assert built[0].events == ["start", "stop", "stopped"]
        assert reapers[0].done()
        binding = built[0].bind_agent("agent-a", _agent())
        with pytest.raises(WorkspaceResultError, match="workspace_unavailable"):
            await built[0].store_tool_result(binding, _capture("after the unwind"))
        assert not root.exists()
    finally:
        await _stop_identities_and_tasks(identities, tasks)


@pytest.mark.asyncio
async def test_phase_one_failure_after_a_failed_store_start_does_not_stop_the_owner_again(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _assert_provenance()
    built = _record_phase_one_stores(monkeypatch)
    identities = _record_identity_registries(monkeypatch)
    handed_over: list[Any] = []
    tasks: list[asyncio.Task[None]] = []

    def register(task: asyncio.Task[None]) -> None:
        tasks.append(task)
        if task.get_name() == "workspace-result-reaper":
            raise RuntimeError("owned registration failure")

    def failing_result(**fields: Any) -> Any:
        # Injection point: the ``InfrastructureResult(...)`` construction, after the degraded store and
        # the identity registry (the store starts first, D4.2).
        handed_over.append(fields["workspace_results"])
        raise RuntimeError("injected after the degraded store")

    monkeypatch.setattr(infrastructure_module, "InfrastructureResult", failing_result)
    try:
        with pytest.raises(RuntimeError, match="injected after the degraded store"):
            await _boot_phase_one(tmp_path / "data", _phase_one_config(str(tmp_path / "workspaces")), register)
        # Premise: the store's start failed and Phase 1 had already degraded to the typed owner.
        assert len(built) == 1 and len(handed_over) == 1 and len(identities) == 1
        assert isinstance(handed_over[0], UnavailableWorkspaceResults)
        # Outcome: that failed start already stopped the store once; the unwind owns nothing more to stop.
        assert built[0].events == ["start", "start-raised-RuntimeError", "stop", "stopped"]
    finally:
        await _stop_identities_and_tasks(identities, tasks)


@pytest.mark.asyncio
async def test_phase_one_starts_the_store_before_the_identity_registry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """D4.2: the order itself, on a healthy boot; it is also the positive control for the identity recorder."""
    _assert_provenance()
    journal: list[str] = []
    built = _record_phase_one_stores(monkeypatch, journal)
    starts = _record_identity_registry_starts(monkeypatch, journal)
    tasks: list[asyncio.Task[None]] = []
    infrastructure = await _boot_phase_one(
        tmp_path / "data", _phase_one_config(str(tmp_path / "workspaces")), tasks.append,
    )
    try:
        # Premises: both really started, so the journal below orders two real starts.
        assert len(built) == 1 and len(starts) == 1
        assert isinstance(infrastructure.workspace_results, WorkspaceResultStore)
        assert infrastructure.identity_registry is starts[0]
        assert journal == ["store.start", "store.started", "identity.start"]
    finally:
        await _release_phase_one(infrastructure)


@pytest.mark.asyncio
async def test_cancellation_during_store_start_never_starts_the_identity_registry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _assert_provenance()
    journal: list[str] = []
    built = _record_phase_one_stores(monkeypatch, journal)
    identities = _record_identity_registries(monkeypatch)
    starts = _record_identity_registry_starts(monkeypatch, journal)
    # Premise: the recorder sees a start of the very class Phase 1 builds (a control outside Phase 1).
    control = AgentIdentityRegistry(tmp_path / "control")
    await control.start()
    await control.stop()
    assert starts == [control]
    starts.clear()
    journal.clear()
    data_dir = tmp_path / "data"
    tasks: list[asyncio.Task[None]] = []

    def register(task: asyncio.Task[None]) -> None:
        tasks.append(task)
        if task.get_name() == "workspace-result-reaper":
            current = asyncio.current_task()
            assert current is not None
            current.cancel()  # delivered at the store's next await, inside store.start()

    boot = asyncio.create_task(
        _boot_phase_one(data_dir, _phase_one_config(str(tmp_path / "not-created")), register),
    )
    try:
        with pytest.raises(asyncio.CancelledError):
            await boot
        # Premises: the cancellation was delivered inside store.start(), after the reaper was registered.
        assert [task.get_name() for task in tasks].count("workspace-result-reaper") == 1 and boot.cancelled()
        assert len(built) == 1 and built[0].events[:2] == ["start", "start-raised-CancelledError"]
        # Outcome: the identity registry was never started (nor built, nor opened on disk), and the
        # unwind stopped the store.
        assert starts == [] and identities == [] and not (data_dir / "identity.db").exists()
        assert journal == ["store.start", "store.start-raised-CancelledError", "store.stop", "store.stopped"]
    finally:
        await _stop_identities_and_tasks(identities, tasks)


@pytest.mark.asyncio
@pytest.mark.parametrize("failure_type", [RuntimeError, asyncio.CancelledError])
async def test_identity_registry_start_failure_stops_the_started_store(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure_type: type[BaseException],
) -> None:
    _assert_provenance()
    journal: list[str] = []
    built = _record_phase_one_stores(monkeypatch, journal)
    starts = _record_identity_registry_starts(
        monkeypatch, journal, error=failure_type("injected identity registry start failure"),
    )
    root = tmp_path / "workspaces"
    tasks: list[asyncio.Task[None]] = []
    try:
        with pytest.raises(failure_type, match="injected identity registry start failure"):
            await _boot_phase_one(tmp_path / "data", _phase_one_config(str(root)), tasks.append)
        # Premises: the identity registry's start was reached and raised, after the store had started.
        assert len(built) == 1 and len(starts) == 1
        assert journal[:3] == ["store.start", "store.started", "identity.start"]
        reapers = [task for task in tasks if task.get_name() == "workspace-result-reaper"]
        assert len(reapers) == 1
        # Outcome: the error propagated (the raises above) and the unwind stopped the store.
        assert journal == ["store.start", "store.started", "identity.start", "store.stop", "store.stopped"]
        assert reapers[0].done()
        binding = built[0].bind_agent("agent-a", _agent())
        with pytest.raises(WorkspaceResultError, match="workspace_unavailable"):
            await built[0].store_tool_result(binding, _capture("after the unwind"))
        assert not root.exists()
    finally:
        await _stop_identities_and_tasks([], tasks)


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel", [False, True])
async def test_shutdown_consumer_stops_workspace_after_pools(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, cancel: bool,
) -> None:
    """The store is outside the AD-824 sweep, stops after the pools, and a cancellation from it is deferred."""
    _assert_provenance()
    harness = make_store(tmp_path / "workspaces")
    store = harness.store
    await store.start()
    reaper = store.background_tasks[0]
    other = asyncio.create_task(asyncio.Event().wait(), name="other-background-loop")
    runtime = BareRuntime(tmp_path / "data", config=_no_waits(), started=True)
    runtime.workspace_results = store
    runtime._background_tasks = {*harness.tasks, other}  # the runtime's registry holds both, as in production
    assert harness.tasks == [reaper] and not reaper.done() and not other.done(), "premise: both loops are running"
    order: list[str] = []
    seen: dict[str, bool] = {}

    class _Pool:
        async def stop(self) -> None:
            # Recorded, not asserted: shutdown logs and swallows a pool whose stop raises.
            seen["reaper_alive"] = not reaper.done() and not reaper.cancelling()
            seen["other_swept"] = other.done()
            order.append("pool")

    runtime.pools["owned-fixture"] = _Pool()
    real_stop = store.stop

    async def recorded_stop() -> None:
        order.append("store-stop")
        await real_stop()
        order.append("store-stopped")
        if cancel:
            raise asyncio.CancelledError  # what a cancelled shutdown surfaces once the drain is complete

    monkeypatch.setattr(store, "stop", recorded_stop)
    caplog.set_level(logging.WARNING, logger=shutdown_module.__name__)
    try:
        if cancel:
            with pytest.raises(asyncio.CancelledError):
                await shutdown_module.shutdown(runtime, reason="test")  # type: ignore[arg-type]
        else:
            await shutdown_module.shutdown(runtime, reason="test")  # type: ignore[arg-type]
        # The AD-824 sweep ran before the pools stopped: it cancelled the other loop and left the reaper alone.
        assert seen == {"reaper_alive": True, "other_swept": True}
        assert order == ["pool", "store-stop", "store-stopped"]
        assert reaper.done() and other.cancelled()
        # The cancellation was deferred, not immediate: the teardown after the store still ran to its end.
        assert runtime.calls[-1] == "llm_client.close"
        assert any(
            "Workspace result store completed its drain-safe stop" in record.getMessage()
            for record in caplog.records
        ) is cancel
    finally:
        other.cancel()
        await asyncio.gather(other, return_exceptions=True)
        await real_stop()


@pytest.mark.asyncio
async def test_shutdown_cancelled_during_the_store_stop_drains_the_worker_then_defers_the_cancellation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _assert_provenance()
    harness, binding = await _running(tmp_path)
    store = harness.store
    runtime = BareRuntime(tmp_path / "bare-data", config=_no_waits(), started=True)
    runtime.workspace_results = store
    runtime._background_tasks = set(harness.tasks)
    entered, release, finished = threading.Event(), threading.Event(), threading.Event()
    original = PinnedDirectory.write_new

    def blocked_write(directory: PinnedDirectory, name: str, data: bytes) -> None:
        if name == "payload.jsonl":
            entered.set()
            assert release.wait(10), "test must release its owned worker"
            try:
                original(directory, name, data)
            finally:
                finished.set()
        else:
            original(directory, name, data)

    monkeypatch.setattr(PinnedDirectory, "write_new", blocked_write)
    stop_entered = asyncio.Event()
    real_stop = store.stop

    async def noted_stop() -> None:
        stop_entered.set()
        await real_stop()

    monkeypatch.setattr(store, "stop", noted_stop)
    publishing = asyncio.create_task(store.store_tool_result(binding, _capture("body" * 4000)))
    shutting_down: asyncio.Task[None] | None = None
    try:
        await _entered(entered)  # a publication's worker thread holds the store mid-write
        shutting_down = asyncio.create_task(shutdown_module.shutdown(runtime, reason="test"))  # type: ignore[arg-type]
        await asyncio.wait_for(stop_entered.wait(), timeout=10)
        # Premise: shutdown reached the store's stop, which is parked behind the publication.
        assert not shutting_down.done() and not finished.is_set()
        shutting_down.cancel()
        await asyncio.sleep(0)
        assert not shutting_down.done() and not finished.is_set(), "the stop drains the worker before it lets the cancellation out"
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await shutting_down
        assert finished.is_set() and harness.tasks[0].done()
        # Deferred: the whole remaining teardown ran before the cancellation surfaced.
        assert runtime.calls[-1] == "llm_client.close"
    finally:
        release.set()
        if shutting_down is not None and not shutting_down.done():
            shutting_down.cancel()
        await asyncio.gather(*(task for task in (publishing, shutting_down) if task is not None), return_exceptions=True)
        await real_stop()


@pytest.mark.asyncio
@pytest.mark.parametrize("rollback", [pytest.param(False, id="normal"), pytest.param(True, id="rollback")])
async def test_shutdown_stops_the_store_even_when_the_pool_step_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, rollback: bool,
) -> None:
    """D4.1: the store stops in a ``finally``, so a pool step that raises cannot leave it running."""
    _assert_provenance()
    harness, binding = await _running(tmp_path)
    store = harness.store
    reaper = store.background_tasks[0]
    runtime = BareRuntime(tmp_path / "bare-data", config=_no_waits(), started=not rollback)
    runtime.workspace_results = store
    runtime._background_tasks = set(harness.tasks)
    pool_error = RuntimeError("INJECTED pool step failure")
    pool_calls: list[str] = []

    async def failing_pool_step(_runtime: Any) -> None:
        pool_calls.append("pool step")
        raise pool_error

    monkeypatch.setattr(shutdown_module, "_stop_pools_and_drain_intent_bus", failing_pool_step)
    entered, release, finished = threading.Event(), threading.Event(), threading.Event()
    original = PinnedDirectory.write_new

    def blocked_write(directory: PinnedDirectory, name: str, data: bytes) -> None:
        if name == "payload.jsonl":
            entered.set()
            assert release.wait(10), "test must release its owned worker"
            try:
                original(directory, name, data)
            finally:
                finished.set()
        else:
            original(directory, name, data)

    monkeypatch.setattr(PinnedDirectory, "write_new", blocked_write)
    stop_entered = asyncio.Event()
    real_stop = store.stop

    async def noted_stop() -> None:
        stop_entered.set()
        await real_stop()

    monkeypatch.setattr(store, "stop", noted_stop)

    async def release_once_the_stop_is_parked() -> None:
        await asyncio.wait_for(stop_entered.wait(), timeout=10)
        for _ in range(1000):  # zero-length yields: the stop cancels the reaper, then waits on the store lock
            if reaper.done():
                break
            await asyncio.sleep(0)
        assert reaper.done() and not finished.is_set(), "premise: the stop is parked behind the blocked worker"
        release.set()

    publishing = asyncio.create_task(store.store_tool_result(binding, _capture("body" * 4000)))
    releasing: asyncio.Task[None] | None = None
    caplog.set_level(logging.WARNING, logger=shutdown_module.__name__)
    try:
        await _entered(entered)  # a publication's worker thread holds the store mid-write
        releasing = asyncio.create_task(release_once_the_stop_is_parked())
        if rollback:
            await shutdown_module.shutdown(runtime, reason="startup_failed", rollback=True)  # type: ignore[arg-type]
        else:
            with pytest.raises(RuntimeError) as raised:
                await shutdown_module.shutdown(runtime, reason="test")  # type: ignore[arg-type]
            assert raised.value is pool_error
        # Premise: the pool step was called and raised; in a rollback its guard logged that and went on.
        assert pool_calls == ["pool step"]
        if rollback:
            named = [
                record for record in caplog.records
                if "startup rollback step 'pools stop and intent bus drain'" in record.getMessage()
            ]
            assert len(named) == 1 and named[0].exc_info is not None and named[0].exc_info[1] is pool_error
        # Outcome: the store's stop ran after the failed pool step, and it waited for the worker.
        assert stop_entered.is_set(), "the store's stop did not run although the pool step raised"
        await releasing  # re-raises a failed premise of the release helper
        assert reaper.done() and finished.is_set()
        with pytest.raises(WorkspaceResultError, match="workspace_unavailable"):
            await store.store_tool_result(binding, _capture("after the stop"))
        if rollback:
            assert runtime.calls[-1] == "llm_client.close", "the rollback went on to its last step"
    finally:
        release.set()
        if releasing is not None and not releasing.done():
            releasing.cancel()
        await asyncio.gather(*(task for task in (publishing, releasing) if task is not None), return_exceptions=True)
        await real_stop()


@pytest.mark.asyncio
async def test_shutdown_stops_the_owner_it_excluded_from_the_sweep_not_a_later_one(tmp_path: Path) -> None:
    _assert_provenance()
    first, second = make_store(tmp_path / "first"), make_store(tmp_path / "second")
    await first.store.start()
    await second.store.start()
    runtime = BareRuntime(tmp_path / "data", config=_no_waits(), started=True)
    runtime.workspace_results = first.store
    runtime._background_tasks = {*first.tasks, *second.tasks}
    second_stops: list[str] = []
    real_second_stop = second.store.stop

    async def counted_second_stop() -> None:
        second_stops.append("stop")
        await real_second_stop()

    second.store.stop = counted_second_stop  # type: ignore[method-assign]

    class _Pool:
        async def stop(self) -> None:
            runtime.workspace_results = second.store  # the attribute changes between the sweep and the stop

    runtime.pools["swapping-pool"] = _Pool()
    try:
        await shutdown_module.shutdown(runtime, reason="test")  # type: ignore[arg-type]
        assert runtime.workspace_results is second.store, "premise: the swap happened between the two uses"
        # The owner read once, for the sweep, is the owner stopped: re-reading would stop the other one.
        assert first.tasks[0].done(), "the owner the sweep excluded was stopped"
        assert second_stops == []
    finally:
        await first.store.stop()
        await real_second_stop()


@pytest.mark.asyncio
async def test_shutdown_without_a_store_runs_to_its_end_on_the_typed_unavailable_owner(tmp_path: Path) -> None:
    runtime = BareRuntime(tmp_path / "data", config=_no_waits(), started=True)
    # Premise: a bare runtime reads as having no owner, which resolves to the typed unavailable one.
    assert runtime.workspace_results is None
    await shutdown_module.shutdown(runtime, reason="test")  # type: ignore[arg-type]
    assert runtime.calls[-1] == "llm_client.close"


@pytest.mark.asyncio
async def test_real_runtime_exposes_the_started_store_after_phase_one_and_its_rollback_stops_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Boot -> Phase 1 -> ``runtime.workspace_results`` -> a failed start -> the real rollback shutdown."""
    _assert_provenance()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PROBOS_DATA_DIR", str(tmp_path / "platform-data"))
    monkeypatch.setattr(YeomanAgent, "_live_instance_count", YeomanAgent._live_instance_count)
    runtime = make_runtime(tmp_path, config=lifecycle_config(tmp_path, zero_grace=True))
    assert isinstance(runtime.workspace_results, UnavailableWorkspaceResults), "before boot it is the typed owner"
    seen: dict[str, Any] = {}

    def at_phase_one_exit(booted: ProbOSRuntime) -> None:
        owner = booted.workspace_results
        seen["owner"] = owner
        seen["reapers"] = tuple(owner.background_tasks)
        seen["registered"] = bool(owner.background_tasks) and all(
            task in booted._background_tasks for task in owner.background_tasks
        )
        seen["alive"] = bool(owner.background_tasks) and all(not task.done() for task in owner.background_tasks)

    failure = inject_start_failure(monkeypatch, runtime, "after_infra", on_fire=at_phase_one_exit)
    with pytest.raises(InjectedStartFailure):
        await runtime.start()
    assert failure.fired and failure.facts["started"] is False, "premise: Phase 1 ran and the boot had not finished"
    owner = seen["owner"]
    assert isinstance(owner, WorkspaceResultStore), "after Phase 1 it is the real store"
    assert owner.root == tmp_path / "platform-data" / "execution" / "workspaces"
    assert len(seen["reapers"]) == 1 and seen["registered"] and seen["alive"]
    # The rollback is a real ``shutdown(rollback=True)``: it stopped the store it found on the runtime.
    assert seen["reapers"][0].done()
    binding = owner.bind_agent("agent-a", _agent())
    with pytest.raises(WorkspaceResultError, match="workspace_unavailable"):
        await owner.store_tool_result(binding, _capture("after the rollback"))


@pytest.mark.asyncio
async def test_real_runtime_start_and_stop_run_the_store_lifecycle_end_to_end(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A full boot: the store is registered, serves a publication, and is stopped by ``runtime.stop()``."""
    _assert_provenance()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PROBOS_DATA_DIR", str(tmp_path / "platform-data"))
    monkeypatch.setattr(YeomanAgent, "_live_instance_count", YeomanAgent._live_instance_count)
    with SqliteTracker() as tracker:
        baseline = LifecycleBaseline.capture(tracker)
        async with started_runtime(tmp_path, config=lifecycle_config(tmp_path, zero_grace=True)) as runtime:
            owner = runtime.workspace_results
            assert isinstance(owner, WorkspaceResultStore), "premise: the full boot exposed the real store"
            assert len(owner.background_tasks) == 1
            reaper = owner.background_tasks[0]
            assert reaper in runtime._background_tasks and not reaper.done()
            binding = owner.bind_agent("agent-a", _agent())
            reference = await owner.store_tool_result(binding, _capture("end to end body"))
            assert (await owner.read_tool_result_slice(binding, reference.path, 4, 2)).text == "to"

            await runtime.stop()

            assert reaper.done(), "runtime.stop() stopped the store it had started"
            with pytest.raises(WorkspaceResultError, match="workspace_unavailable"):
                await owner.store_tool_result(binding, _capture("after the stop"))
            assert await baseline.leftovers() == NOTHING_LEFT


def _called_name(call: ast.Call) -> str | None:
    if isinstance(call.func, ast.Attribute):
        return call.func.attr
    if isinstance(call.func, ast.Name):
        return call.func.id
    return None


def test_no_production_caller_passes_an_argument_to_reap_tool_results() -> None:
    package = Path(store_module.__file__).resolve().parents[1]
    assert package.name == "probos" and (package / "execution").is_dir()
    calls: list[tuple[str, int, int]] = []
    definitions: dict[str, list[str]] = {}
    for path in sorted(package.rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        if "reap_tool_results" not in text:
            continue
        relative = path.relative_to(package).as_posix()
        for node in ast.walk(ast.parse(text)):
            if isinstance(node, ast.Call) and _called_name(node) == "reap_tool_results":
                calls.append((relative, node.lineno, len(node.args) + len(node.keywords)))
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "reap_tool_results":
                parameters = node.args
                definitions[f"{relative}:{node.lineno}"] = [
                    *(arg.arg for arg in (*parameters.posonlyargs, *parameters.args, *parameters.kwonlyargs)),
                    *(["*" + parameters.vararg.arg] if parameters.vararg else []),
                    *(["**" + parameters.kwarg.arg] if parameters.kwarg else []),
                ]
    # Premise: the scan found the real call sites (startup sweep and reaper loop) and the three definitions
    # (protocol, typed unavailable owner, store), so an empty offender list is not a scan that saw nothing.
    store_calls = [call for call in calls if call[0] == "execution/workspace_result_store.py"]
    assert len(store_calls) >= 2
    assert {key.split(":")[0] for key in definitions} == {
        "execution/workspace_results.py", "execution/workspace_result_store.py",
    } and len(definitions) == 3
    assert [call for call in calls if call[2] != 0] == []
    assert all(parameters == ["self"] for parameters in definitions.values())
