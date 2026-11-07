"""BF-960 (#1767): the knowledge store's shutdown flush waits for the debounced commit in flight.

The debounce timer's task runs ``git add -A`` and ``git commit`` in executor threads. Before BF-960,
``flush()`` neither waited for that task nor serialized with it: a flush that started while the task's
``add`` held ``.git/index.lock`` logged ``Git add failed`` and returned, and the task's commit landed
after the store was told to stop. These tests use a real ``KnowledgeStore`` and real git, isolated from
the host's git configuration. Where the task's ``add`` must be slow, an executor thread creates
``index.lock`` and removes it when the test releases it, as a slow ``git add`` would: cancelling the
coroutine that awaits that thread does not stop it, as with git.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import subprocess
import threading
from collections.abc import Awaitable, Callable
from pathlib import Path

import pytest

from probos.config import KnowledgeConfig
from probos.knowledge.store import KnowledgeStore

_LOGGER = "probos.knowledge.store"
_GIT = pytest.mark.skipif(shutil.which("git") is None, reason="git not available")
#: Seconds after flush() starts (T6: after it is cancelled) at which the held add is released. A flush
#: that does not wait runs its own add (one git launch) well before this, while the lock is still held.
_RELEASE_AFTER = 1.5
#: Seconds a rollback that does not queue has to run its add while the lock is held.
_ROLLBACK_WINDOW = 2.0
_TIMEOUT = 60.0


def _snapshot(alpha: float) -> dict[str, dict[str, float]]:
    return {"agent-a": {"alpha": alpha, "beta": 2.0}}


@pytest.fixture(autouse=True)
def _hermetic_git(tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove every ``GIT_*`` variable and point git at an empty configuration, as BF-957's suite does.

    The store's git inherits ``os.environ`` (``trusted_command_env``), so a host setting such as
    ``commit.gpgSign`` or ``core.fsmonitor`` would otherwise reach these repositories.
    """
    home = tmp_path_factory.mktemp("bf960-git-home")
    empty = home / ".gitconfig"
    empty.write_bytes(b"")
    for name in list(os.environ):
        if name.upper().startswith("GIT_"):
            monkeypatch.delenv(name)
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(empty))
    monkeypatch.setenv("GIT_CONFIG_COUNT", "0")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(home))


def _store(tmp_path: Path, debounce: float) -> KnowledgeStore:
    return KnowledgeStore(KnowledgeConfig(
        enabled=True, repo_path=str(tmp_path / "knowledge"), auto_commit=True,
        commit_debounce_seconds=debounce,
    ))


def _api(store: KnowledgeStore) -> None:
    assert callable(getattr(store, "_on_commit_timer", None)), "BF-960: the timer's task is not kept"


def _fingerprint(git_dir: Path) -> dict[str, tuple[int, int]]:
    return {
        p.relative_to(git_dir).as_posix(): (p.stat().st_size, p.stat().st_mtime_ns)
        for p in sorted(git_dir.rglob("*")) if p.is_file()
    }


def _live_tasks() -> list[asyncio.Task]:
    current = asyncio.current_task()
    return [t for t in asyncio.all_tasks() if t is not current and not t.done()]


def _live_commits() -> list[asyncio.Task]:
    return [t for t in _live_tasks() if t.get_coro().__qualname__.endswith("_flush_pending")]


async def _settle() -> None:
    """Wait for every other task of this loop, so a commit still in flight lands before the next look."""
    others = _live_tasks()
    if others:
        await asyncio.wait(others, timeout=_TIMEOUT)


async def _until(predicate: Callable[[], bool]) -> None:
    while not predicate():
        await asyncio.sleep(0.01)


def _lock_failures(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [
        r.getMessage() for r in caplog.records
        if r.name == _LOGGER and "Git add failed" in r.getMessage()
    ]


class _Git:
    """Wraps the store's ``_git_run``: holds or fails the next ``add`` on request, runs a queued late
    writer after an ``add`` returns, and signals results."""

    def __init__(self, store: KnowledgeStore) -> None:
        self.original = store._git_run
        self.git_dir = store.repo_path / ".git"
        self.hold_next_add = False
        self.fail_next_add = ""  # "", "raises" or "fails"
        self.after_add: list[Callable[[], Awaitable[None]]] = []  # one runs after each add returns
        self.held = threading.Event()
        self.release = threading.Event()
        self.add_returned = asyncio.Event()
        self.shown = asyncio.Event()
        self.committed = asyncio.Event()
        store._git_run = self.run  # type: ignore[method-assign]

    def _hold(self) -> None:
        lock = self.git_dir / "index.lock"
        os.close(os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY))
        self.held.set()
        try:
            self.release.wait(_TIMEOUT)
        finally:
            lock.unlink()

    async def run(self, *args: str) -> subprocess.CompletedProcess:
        verb = args[0] if args else ""
        if verb == "add" and self.fail_next_add:
            mode, self.fail_next_add = self.fail_next_add, ""
            if mode == "raises":
                raise RuntimeError("injected add error")
            return subprocess.CompletedProcess(["git", *args], 1, "", "injected add failure")
        if verb == "add" and self.hold_next_add:
            self.hold_next_add = False
            await asyncio.get_running_loop().run_in_executor(None, self._hold)
            return await self.original(*args)
        result = await self.original(*args)
        if verb == "add":
            self.add_returned.set()
            if self.after_add:
                await self.after_add.pop(0)()  # a writer whose file lands right after this add
        elif verb == "show":
            self.shown.set()
        elif verb == "commit":
            self.committed.set()
        return result

    async def wait_until_held(self) -> None:
        held = await asyncio.wait_for(asyncio.to_thread(self.held.wait, _TIMEOUT), _TIMEOUT + 5)
        assert held, "premise: the timer's add took the lock"

    async def subjects(self) -> list[str]:
        out = await self.original("log", "--format=%s")
        return out.stdout.splitlines() if out.returncode == 0 else []


# ---------------------------------------------------------------- the race (the issue's probe)


@_GIT
async def test_flush_waits_for_the_debounced_commit_in_flight_and_nothing_lands_after_it(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    """T1, the issue's RACE: the timer's add holds index.lock when flush() starts."""
    store = _store(tmp_path, 0.05)
    await store.initialize()
    git = _Git(store)
    git.hold_next_add = True
    try:
        with caplog.at_level(logging.WARNING, logger=_LOGGER):
            await store.store_trust_snapshot(_snapshot(2.0))
            await git.wait_until_held()
            asyncio.get_running_loop().call_later(_RELEASE_AFTER, git.release.set)
            await asyncio.wait_for(store.flush(), _TIMEOUT)
            at_return = _fingerprint(git.git_dir)
            subjects = await git.subjects()
            await _settle()
        assert _lock_failures(caplog) == []
        assert subjects == ["Shutdown flush", "Store trust snapshot"]
        assert _fingerprint(git.git_dir) == at_return
    finally:
        git.release.set()
        await _settle()


@_GIT
async def test_control_a_flush_after_the_debounced_commit_finished_changes_nothing_afterwards(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    """T2, the issue's SETTLED control: the same assertions hold when flush() starts after the commit."""
    store = _store(tmp_path, 0.05)
    await store.initialize()
    git = _Git(store)
    with caplog.at_level(logging.WARNING, logger=_LOGGER):
        await store.store_trust_snapshot(_snapshot(2.0))
        await asyncio.wait_for(git.committed.wait(), _TIMEOUT)
        await _settle()
        await asyncio.wait_for(store.flush(), _TIMEOUT)
        at_return = _fingerprint(git.git_dir)
        subjects = await git.subjects()
        await _settle()
    assert _lock_failures(caplog) == []
    assert subjects == ["Shutdown flush", "Store trust snapshot"]
    assert _fingerprint(git.git_dir) == at_return


@_GIT
async def test_two_concurrent_flushes_both_wait_and_neither_meets_the_lock(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    """T3: two flush() calls during the timer's commit both return consistent, without deadlock."""
    store = _store(tmp_path, 0.05)
    await store.initialize()
    git = _Git(store)
    git.hold_next_add = True
    try:
        with caplog.at_level(logging.WARNING, logger=_LOGGER):
            await store.store_trust_snapshot(_snapshot(2.0))
            await git.wait_until_held()
            asyncio.get_running_loop().call_later(_RELEASE_AFTER, git.release.set)
            await asyncio.wait_for(asyncio.gather(store.flush(), store.flush()), _TIMEOUT)
            at_return = _fingerprint(git.git_dir)
            subjects = await git.subjects()
            await _settle()
        assert _lock_failures(caplog) == []
        assert subjects == ["Shutdown flush", "Shutdown flush", "Store trust snapshot"]
        assert _fingerprint(git.git_dir) == at_return
    finally:
        git.release.set()
        await _settle()


@_GIT
async def test_a_rollback_during_the_debounced_commit_queues_behind_it_and_head_matches_the_file(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    """T4: rollback_artifact, which does not wait for the timer's task, queues on the commit lock."""
    store = _store(tmp_path, 3600.0)
    await store.initialize()
    git = _Git(store)
    path = store.repo_path / "trust" / "snapshot.json"
    try:
        for alpha in (1.0, 2.0):  # two commits of the file: the rollback's history
            await store.store_trust_snapshot(_snapshot(alpha))
            await asyncio.wait_for(store.flush(), _TIMEOUT)
        store._config = store._config.model_copy(update={"commit_debounce_seconds": 0.05})
        git.add_returned.clear()
        git.hold_next_add = True
        with caplog.at_level(logging.WARNING, logger=_LOGGER):
            await store.store_trust_snapshot(_snapshot(3.0))
            await git.wait_until_held()
            rollback = asyncio.create_task(store.rollback_artifact("trust", "snapshot"))
            await asyncio.wait_for(git.shown.wait(), _TIMEOUT)
            try:  # a rollback that does not queue runs its add now, while the lock is held
                await asyncio.wait_for(git.add_returned.wait(), _ROLLBACK_WINDOW)
            except TimeoutError:
                pass
            git.release.set()
            assert await asyncio.wait_for(rollback, _TIMEOUT) is True
            await _settle()
        assert _lock_failures(caplog) == []
        head = await git.original("show", "HEAD:trust/snapshot.json")
        status = await git.original("status", "--porcelain")
        assert json.loads(head.stdout) == json.loads(path.read_text(encoding="utf-8")) == _snapshot(1.0)
        assert status.stdout == ""
        assert (await git.subjects())[0].startswith("Rollback trust/snapshot to ")
    finally:
        git.release.set()
        await _settle()


@_GIT
@pytest.mark.parametrize("failure", ["raises", "fails"])
async def test_a_failed_debounced_commit_leaves_the_lock_free_for_the_next_commit(
    tmp_path: Path, failure: str,
) -> None:
    """T5: the timer's add raises or returns an error; the shutdown flush still commits."""
    store = _store(tmp_path, 0.05)
    await store.initialize()
    git = _Git(store)
    git.fail_next_add = failure
    await store.store_trust_snapshot(_snapshot(2.0))
    await asyncio.wait_for(_until(lambda: not git.fail_next_add), _TIMEOUT)
    await _settle()
    await asyncio.wait_for(store.flush(), _TIMEOUT)
    status = await git.original("status", "--porcelain")
    assert await git.subjects() != []
    assert status.stdout == ""


@_GIT
async def test_a_cancelled_flush_leaves_the_debounced_commit_running_to_its_end(tmp_path: Path) -> None:
    """T6: cancelling flush() while it waits must not cancel the timer's commit."""
    store = _store(tmp_path, 0.05)
    await store.initialize()
    git = _Git(store)
    git.hold_next_add = True
    try:
        await store.store_trust_snapshot(_snapshot(2.0))
        await git.wait_until_held()
        flush = asyncio.create_task(store.flush())
        for _ in range(5):
            await asyncio.sleep(0)
        flush.cancel()
        with pytest.raises(asyncio.CancelledError):
            await flush
        # Not at once: a flush that does not wait has started its own add, an executor thread that
        # cancelling cannot stop. That add must meet the held lock and end before the timer's add
        # starts, or the two race for index.lock and the timer's commit may never land.
        asyncio.get_running_loop().call_later(_RELEASE_AFTER, git.release.set)
        await _settle()
        assert "Store trust snapshot" in await git.subjects()
        await asyncio.wait_for(store.flush(), _TIMEOUT)
        status = await git.original("status", "--porcelain")
        assert status.stdout == ""
    finally:
        git.release.set()
        await _settle()


# ---------------------------------------------------------------- the task and the hand-off


@pytest.mark.parametrize("git", ["absent", pytest.param("present", marks=_GIT)])
async def test_flush_returns_with_no_debounce_task_left_and_commits_each_write_once(
    tmp_path: Path, git: str,
) -> None:
    """T7: the timer has fired and its task has not started when flush() begins."""
    store = _store(tmp_path, 3600.0)
    await store.initialize()
    _api(store)
    if git == "absent":
        store._git_available = False  # a host without git: flush() itself never suspends
    await store.store_trust_snapshot(_snapshot(2.0))
    store._commit_timer.cancel()
    store._on_commit_timer()  # what the loop does when the timer fires; the task starts later
    await store.flush()
    assert _live_commits() == []
    assert store._commit_tasks == set()
    if git == "present":
        out = await store._git_run("log", "--format=%s")
        assert out.stdout.splitlines() == ["Store trust snapshot"]


@_GIT
async def test_a_timer_armed_before_the_fired_timers_task_starts_stays_the_one_flush_cancels(
    tmp_path: Path,
) -> None:
    """T8: the fired timer's task must not drop the reference to a timer armed after it fired."""
    store = _store(tmp_path, 3600.0)
    await store.initialize()
    _api(store)
    await store.store_trust_snapshot(_snapshot(2.0))
    store._commit_timer.cancel()
    store._on_commit_timer()
    assert store._commit_timer is None
    await store._schedule_commit("Second write")  # does not suspend: the repository is initialised
    armed = store._commit_timer
    assert armed is not None
    await asyncio.wait(set(store._commit_tasks), timeout=_TIMEOUT)
    assert store._commit_timer is armed and not armed.cancelled()
    await asyncio.wait_for(store.flush(), _TIMEOUT)
    assert armed.cancelled()
    out = await store._git_run("log", "--format=%s")
    assert out.stdout.splitlines() == ["Shutdown flush", "Store trust snapshot; Second write"]


@_GIT
async def test_a_store_whose_timer_never_fired_flushes_its_writes_in_one_commit(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    """T9: with no task in flight, flush() behaves as before."""
    store = _store(tmp_path, 3600.0)
    await store.initialize()
    with caplog.at_level(logging.WARNING, logger=_LOGGER):
        await store.store_trust_snapshot(_snapshot(2.0))
        await store.store_routing_weights(
            [{"source": "a", "target": "b", "rel_type": "intent", "weight": 0.5}],
        )
        await asyncio.wait_for(store.flush(), _TIMEOUT)
    out = await store._git_run("log", "--format=%s")
    assert out.stdout.splitlines() == ["Store trust snapshot; Store routing weights"]
    assert _lock_failures(caplog) == []
    assert store._commit_timer is None


async def test_a_debounce_task_that_raises_is_logged_once_and_forgotten(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    """T10: the task's done callback logs an exception it ended with and drops the task."""
    store = _store(tmp_path, 3600.0)
    await store.initialize()
    _api(store)
    store._git_available = False
    await store.store_trust_snapshot(_snapshot(2.0))

    async def _raises(message: str) -> None:
        raise RuntimeError("injected commit error")

    store._git_commit = _raises  # type: ignore[method-assign]
    store._commit_timer.cancel()
    with caplog.at_level(logging.WARNING, logger=_LOGGER):
        store._on_commit_timer()
        await asyncio.wait(set(store._commit_tasks), timeout=_TIMEOUT)
    records = [
        r.getMessage() for r in caplog.records
        if r.name == _LOGGER and "debounced commit failed" in r.getMessage()
    ]
    assert len(records) == 1 and "injected commit error" in records[0]
    assert store._commit_tasks == set()


# ---------------------------------------------------------------- late writes (A2)

_ROUTING = [{"source": "a", "target": "b", "rel_type": "intent", "weight": 0.5}]
_WORKFLOWS = [{"pattern": "p", "hit_count": 1}]


def _late_write(
    store: KnowledgeStore, seen: list[bool], write: Callable[[], Awaitable[None]],
) -> Callable[[], Awaitable[None]]:
    """A ``_Git.after_add`` hook: ``write`` runs as a writer's would, and ``seen`` records whether
    flush() was running. The store catches an exception raised under its commit, so the tests
    assert on ``seen`` instead."""

    async def run() -> None:
        seen.append(store._flushing)
        await write()

    return run


async def _committed(git: _Git) -> tuple[list[str], str, list[str]]:
    """The files in HEAD, the porcelain status, and the commit subjects, newest first."""
    tree = await git.original("ls-tree", "-r", "--name-only", "HEAD")
    status = await git.original("status", "--porcelain")
    return tree.stdout.splitlines(), status.stdout, await git.subjects()


def _store_warnings(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [r.getMessage() for r in caplog.records if r.name == _LOGGER]


@_GIT
async def test_a_write_that_lands_while_flush_commits_is_in_head_when_flush_returns(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    """T11: the write's file lands after flush()'s add, so flush()'s own commit cannot hold it."""
    store = _store(tmp_path, 3600.0)
    await store.initialize()
    git = _Git(store)
    seen: list[bool] = []
    git.after_add = [_late_write(store, seen, lambda: store.store_routing_weights(_ROUTING))]
    with caplog.at_level(logging.WARNING, logger=_LOGGER):
        await store.store_trust_snapshot(_snapshot(2.0))
        await asyncio.wait_for(store.flush(), _TIMEOUT)
        files, status, subjects = await _committed(git)
    assert "routing/weights.json" in files, f"in HEAD: {files}; flushing at each late write: {seen}"
    assert status == ""
    assert subjects == ["Store routing weights", "Store trust snapshot"]
    assert store._pending_messages == [] and store._commit_timer is None
    assert _store_warnings(caplog) == []
    assert seen == [True], "premise: the write landed while flush() ran"


@_GIT
async def test_a_write_that_lands_while_the_drain_commits_is_committed_too(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    """T12: a second write lands during the first drain commit, so flush() commits once more for it."""
    store = _store(tmp_path, 3600.0)
    await store.initialize()
    git = _Git(store)
    seen: list[bool] = []
    git.after_add = [
        _late_write(store, seen, lambda: store.store_routing_weights(_ROUTING)),
        _late_write(store, seen, lambda: store.store_workflows(_WORKFLOWS)),
    ]
    with caplog.at_level(logging.WARNING, logger=_LOGGER):
        await store.store_trust_snapshot(_snapshot(2.0))
        await asyncio.wait_for(store.flush(), _TIMEOUT)
        files, status, subjects = await _committed(git)
    assert {"routing/weights.json", "workflows/cache.json"} <= set(files), (
        f"in HEAD: {files}; flushing at each late write: {seen}"
    )
    assert status == ""
    assert subjects == ["Store workflow cache", "Store routing weights", "Store trust snapshot"]
    assert store._pending_messages == [] and store._commit_timer is None
    assert _store_warnings(caplog) == []
    assert seen == [True, True], "premise: both writes landed while flush() ran"


@_GIT
async def test_a_writer_that_never_stops_cannot_hold_flush_past_the_drain_bound(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """T13: a write lands during every commit; flush() stops after the bound, warns, keeps the message."""
    monkeypatch.setattr("probos.knowledge.store._FLUSH_DRAIN_PASSES", 2)
    store = _store(tmp_path, 3600.0)
    await store.initialize()
    git = _Git(store)
    seen: list[bool] = []

    async def again() -> None:
        seen.append(store._flushing)
        git.after_add.append(again)  # the writer is still writing when the next add returns
        await store.store_routing_weights(
            [{"source": "a", "target": "b", "rel_type": "intent", "weight": float(len(seen))}],
        )

    git.after_add = [again]
    with caplog.at_level(logging.WARNING, logger=_LOGGER):
        await store.store_trust_snapshot(_snapshot(2.0))
        await asyncio.wait_for(store.flush(), _TIMEOUT)
        _, _, subjects = await _committed(git)
    assert subjects == ["Store routing weights", "Store routing weights", "Store trust snapshot"]
    assert store._pending_messages == ["Store routing weights"]
    assert [w for w in _store_warnings(caplog) if "still landing" in w] != []
    assert store._flushing is False
    assert seen == [True, True, True], "premise: a write landed in each of the three commits"
