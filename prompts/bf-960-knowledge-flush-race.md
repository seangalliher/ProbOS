# BF-960 (#1767): the knowledge store's shutdown flush waits for the debounced commit in flight

**Drafted by:** `claude-architect` (Claude Code, Opus 5.5), 2026-11-07
**Status:** ready to build on `origin/main` `46950c39` (see the orchestrator note: it is built before the BF-957 + BF-958 batch merges).
**Base:** the anchors were taken at `eb204e3c674a47cf5edc9cee4c8b8819d1160961`. `src/probos/knowledge/store.py` is blob `c2135ed2`, `tests/test_knowledge_store.py` is blob `4da2a472`, and `src/probos/startup/shutdown.py` is blob `e006c05f`.
**Dependencies:** none in code.
**Orchestrator note (2026-11-07, before building):** (1) **Order.** The BF-957 + BF-958 batch (PR #1768) has not merged. Its fourth canonical gate failed on this issue's race again, with the first gate's signature, so by the Architect's rule for that case this item is built FIRST, on `origin/main` `46950c39`, merged, and then main is merged into the batch branch. `store.py`, `shutdown.py` and the named test files have the same text on `46950c39` as at `eb204e3c` (the batch does not touch them), so every source and test pair applies unchanged: `git diff --stat eb204e3c HEAD -- <those files>` is empty on the build tree. (2) **Amendment A1 (T6).** The orchestrator's rehearsal of this contract by tool found T6 (`test_a_cancelled_flush_leaves_the_debounced_commit_running_to_its_end`) non-deterministic on the unbuilt base (2 failures in 5 runs; stable once built: 15 of 15, the file 4 of 4, the loaded G2 command 3 of 3). The Copilot `Architect` (the Claude Code bridge's login had expired) decided option C: T6 releases the injected hold `_RELEASE_AFTER` after it cancels `flush()`, not at once. The five amendment pairs (the G1 sentence, the section 6 note, the constant's comment, T6's release, limit L8) are already applied to this text; G1 is unchanged (5 passed, 7 xfailed). (3) **Trackers.** Main's DECISIONS.md has no BF-958 entry, so P3-2 is re-anchored on AD-1358 S1's last bullet (`- *Reversal.* Revert the AD-1358 S1 commits.`, once on main), and the residual line reads L1 to L8. When main is merged into the batch branch later, the two insertions at that point conflict: keep both entries and regenerate the ledger.
**Tier:** M1 STANDARD, M2 HIGH, M3 STANDARD.
**Estimated tests:** one new file with 10 functions and 12 cases. No existing test file is edited. Counted by reading, not by running.

**Which text describes the head.** Before building:
1. Run `git rev-parse HEAD:src/probos/knowledge/store.py`. It must print `c2135ed267212e3af8c8da6b5723d4d2ec4428ad`.
2. Run `git diff --stat eb204e3c HEAD -- src/probos/knowledge/store.py src/probos/startup/shutdown.py tests/test_knowledge_store.py tests/test_knowledge_store_git_recovery.py tests/test_bf906_crew_enrollment_boot.py`. It must be empty.
3. Check that `tests/test_bf960_knowledge_flush_race.py` does not exist.

Then:
- Each SEARCH must occur exactly once. Otherwise it is a hard stop, and the SEARCH goes back to the Architect.
- Working copies are CRLF, and SEARCH text here is LF.
- Where prose and a block differ, the block wins.
- Apply the pairs with the `edit` tool one at a time, whole block, in label order.

## 1. Problem

1. **The task is not kept.** `_schedule_commit` arms `loop.call_later(debounce, lambda: asyncio.create_task(self._flush_pending()))` (`store.py:1083-1086`) and keeps no handle to the task.
2. **`flush()` does not coordinate with it.** `flush()` (`:1204-1224`) sets `_flushing`, cancels the timer and runs its own `_git_commit`. It neither waits for a task that is already running nor serializes with it.
3. **Effect.** While the task's `git add -A` holds `.git/index.lock`, flush's own `add` fails with `Git add failed: … index.lock: File exists` (`:1137-1139`). `flush()` returns, `rt.stop()` returns, and then the task's commit lands. Measured in the issue (RACE): no commit existed when `flush()` returned, and 10 files under `.git` changed afterwards. With no injection, the natural window opened in 1 to 2 of 16 runs.
4. **Same exposure.** `rollback_artifact` (`:1359`) calls `_git_commit` directly.
5. **Latent.** `_flush_pending` clears `_commit_timer` (`:1100`) when its task starts. A timer armed between the old timer firing and that moment is lost, and `flush()` can no longer cancel it.

## 2. Solution

- **`_commit_lock`.** It serializes the add-and-commit sequence (`_git_commit` → `_git_add_and_commit`).
- **The timer's callback.** `_on_commit_timer` clears `_commit_timer`, creates the task and keeps it in `_commit_tasks`. `_on_commit_task_done` removes the task and logs an exception it ended with.
- **`flush()`.** After cancelling the timer, it waits for the running tasks with `asyncio.wait` and never cancels them. Then it commits what `_take_pending()` hands it, or `"Shutdown flush"` when nothing is pending.
- **`_flush_pending`.** It keeps its `_flushing` check and uses `_take_pending()`.

## 3. Decisions

D0 to D6 are in the tables above this contract.

## 4. Milestones and gates

| M | Pairs | Gate |
|---|---|---|
| M1 | N1-1 | G1 |
| M2 | P2-1 to P2-3, then N2-1 to N2-7 (removing the markers) | G2 |
| M3 | P3-1, P3-2, ledger | G3 |

`PY` = `d:/ProbOS/.venv/Scripts/python.exe`.

- **M0.** On the head, record the collected count (`--collect-only -q`) of every existing file named in G2. The bridge allows no pytest, so I could not.
- **G1.** `PY -m pytest tests/test_bf960_knowledge_flush_race.py -q -n 0 -p no:randomly`
  - Expected on a host with git: **5 passed** (T2, T5[raises], T5[fails], T6, T9) and **7 xfailed** (T1, T3, T4, T7[absent], T7[present], T8, T10).
  - The marker is strict and has `raises=AssertionError`, so any other exception, or an XPASS, is a failure.
  - Any other count is a hard stop. T6 passes here only because it releases the hold `_RELEASE_AFTER` after it cancels `flush()` (section 6). If T6 fails, keep the output and stop; do not rerun it until it passes.
- **G2.**
  1. `PY -m pytest tests/test_bf960_knowledge_flush_race.py tests/test_knowledge_store.py tests/test_knowledge_store_git_recovery.py tests/test_bf906_crew_enrollment_boot.py tests/test_issue1419_failed_start_rollback.py tests/test_persistent_identity.py tests/test_quality_hardening.py tests/test_bf892_spawn_env_guard.py tests/test_ad1346_admission_effect_census.py tests/test_ad1346_admission_file_write_census.py tests/test_ad1343_seam_registry.py tests/test_ad1343_stop_seam_inventory.py tests/test_ad1270b_architecture_fitness.py tests/test_layer_boundaries.py -q -n 0 -p no:randomly`
  2. `PY -P scripts/check_architecture_principles.py --check`
  3. Under load: `PY -m pytest tests/test_bf960_knowledge_flush_race.py tests/test_knowledge_store.py -q`. This uses the repository's default `-n 16 --dist=loadfile`.
  - Expected: **12 passed** in the new file, in both runs. Every other file has 0 failed, and its collected count equals M0. The architecture check is clean.
- **G3.**
  1. `PY -P scripts/gen_ad_ledger.py`
  2. `PY -P scripts/gen_ad_ledger.py --check`
  3. `PY -m pytest tests/test_ad1184_ad_ledger.py -q -n 0`
- **Harness rule.** No source change made to pass a test, no skip, and no loosened assertion. Any of these goes back to the Architect. `tests/test_bf906_crew_enrollment_boot.py` is not edited.
- The broad gate runs once, in the main session, with `--receipt`, after the review repairs.

## 5. Commit messages

- **M1:** `BF-960 M1: tests for the knowledge store's flush racing the debounced commit, xfail until built (#1767)`
- **M2:** `BF-960 M2: one commit lock for the knowledge store's git sequence, and flush() waits for the debounced commit in flight without cancelling it (#1767)`
- **M3:** `BF-960 M3: trackers and ledger (#1767)`

## 6. Tests (`tests/test_bf960_knowledge_flush_race.py`)

| Id | Test | Cases | Covers | xfail until |
|---|---|---|---|---|
| T1 | `test_flush_waits_for_the_debounced_commit_in_flight_and_nothing_lands_after_it` | 1 | The issue's RACE scenario: no lock failure; the commit is present when `flush()` returns; nothing changes after it; each message is committed once | M2 |
| T2 | `test_control_a_flush_after_the_debounced_commit_finished_changes_nothing_afterwards` | 1 | The SETTLED control: proves the harness discriminates | none |
| T3 | `test_two_concurrent_flushes_both_wait_and_neither_meets_the_lock` | 1 | Two concurrent `flush()` calls during the commit | M2 |
| T4 | `test_a_rollback_during_the_debounced_commit_queues_behind_it_and_head_matches_the_file` | 1 | Pins the lock: `rollback_artifact` does not wait for the task | M2 |
| T5 | `test_a_failed_debounced_commit_leaves_the_lock_free_for_the_next_commit` | 2 | The lock is released after `add` raises or fails | none (kills row 2) |
| T6 | `test_a_cancelled_flush_leaves_the_debounced_commit_running_to_its_end` | 1 | A cancelled `flush()` does not cancel the task | none (kills rows 4 and 5) |
| T7 | `test_flush_returns_with_no_debounce_task_left_and_commits_each_write_once` | 2 | The task has been created but not started; pins the wait (absent) and `_flushing` (present) | M2 |
| T8 | `test_a_timer_armed_before_the_fired_timers_task_starts_stays_the_one_flush_cancels` | 1 | The timer hand-off | M2 |
| T9 | `test_a_store_whose_timer_never_fired_flushes_its_writes_in_one_commit` | 1 | Behaves as before | none |
| T10 | `test_a_debounce_task_that_raises_is_logged_once_and_forgotten` | 1 | The done callback | M2 |

**How each xfail case fails on the base.** Each fails at an `AssertionError`:
- T1, T3 and T4 fail at `_lock_failures(caplog) == []`. Flush's add, or rollback's add, meets the held lock.
- T7, T8 and T10 fail at `_api()`.

**Why T6 passes on the base, and why it releases the hold late.** On the base a cancelled `flush()` has already started its own `git add -A` in an executor thread, and cancelling cannot stop that thread. Released at once, the abandoned `add` and the timer's `add` race for `index.lock`; when the abandoned one wins, the timer's `add` fails and no commit lands (measured by the orchestrator on 2026-11-07: 2 failures in 5 runs on the base). T6 releases the hold `_RELEASE_AFTER` after the cancel, as T1 and T3 do after `flush()` starts, so the abandoned `add` meets the held lock and ends before the timer's `add` begins. After the build no `add` is abandoned: a cancelled `flush()` is waiting and has started none.

## 7. The contract

### 7.1 M1

**N1-1.** New file `tests/test_bf960_knowledge_flush_race.py`:

```python
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
from collections.abc import Callable
from pathlib import Path

import pytest

from probos.config import KnowledgeConfig
from probos.knowledge.store import KnowledgeStore

_LOGGER = "probos.knowledge.store"
_GIT = pytest.mark.skipif(shutil.which("git") is None, reason="git not available")
_BUILT = pytest.mark.xfail(raises=AssertionError, strict=True, reason="BF-960 M2 builds it")
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
    """Wraps the store's ``_git_run``: holds or fails the next ``add`` on request, and signals results."""

    def __init__(self, store: KnowledgeStore) -> None:
        self.original = store._git_run
        self.git_dir = store.repo_path / ".git"
        self.hold_next_add = False
        self.fail_next_add = ""  # "", "raises" or "fails"
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
@_BUILT
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
@_BUILT
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
@_BUILT
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


@_BUILT
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
@_BUILT
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


@_BUILT
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
```

### 7.2 M2

**P2-1.** `src/probos/knowledge/store.py`
SEARCH:
```
        self._flushing: bool = False  # Guard against debounce/flush race (AD-161)
        self._pending_messages: list[str] = []
        self._commit_timer: asyncio.TimerHandle | None = None
        self._skill_locks: dict[str, asyncio.Lock] = {}
```
REPLACE:
```
        self._flushing: bool = False  # Guard against debounce/flush race (AD-161)
        self._pending_messages: list[str] = []
        self._commit_timer: asyncio.TimerHandle | None = None
        # BF-960: one add-and-commit sequence at a time (the debounce task, flush()
        # and rollback_artifact), and the debounce timer's tasks until each is done.
        # An asyncio.Lock binds to a loop only on its first contended acquire, so
        # creating it here, before any loop runs, is safe (as RecordsStore does).
        self._commit_lock = asyncio.Lock()
        self._commit_tasks: set[asyncio.Task[None]] = set()
        self._skill_locks: dict[str, asyncio.Lock] = {}
```

**P2-2.** `src/probos/knowledge/store.py`
SEARCH:
```
        try:
            loop = asyncio.get_running_loop()
            self._commit_timer = loop.call_later(
                self._config.commit_debounce_seconds,
                lambda: asyncio.create_task(self._flush_pending()),
            )
        except RuntimeError:
            # No running loop (e.g. during testing without async context)
            pass

    async def _flush_pending(self) -> None:
        """Commit all pending messages.  Called by debounce timer."""
        if self._flushing:
            return
        if not self._pending_messages:
            return

        messages = self._pending_messages[:]
        self._pending_messages.clear()
        self._commit_timer = None

        combined = "; ".join(messages)
        await self._git_commit(combined)

    async def _git_commit(self, message: str) -> None:
        """Run git add + commit in thread executor (AD-166).

        BF: Concurrent processes touching the same repo can leave the
        index or HEAD ref in a half-written state. Detect both classes
        and recover in place rather than just logging a warning.
        """
        if not self._git_available:
            return

        try:
            result_add = await self._git_run("add", "-A")
```
REPLACE:
```
        try:
            loop = asyncio.get_running_loop()
            self._commit_timer = loop.call_later(
                self._config.commit_debounce_seconds,
                self._on_commit_timer,
            )
        except RuntimeError:
            # No running loop (e.g. during testing without async context)
            pass

    def _on_commit_timer(self) -> None:
        """The debounce timer's callback: start the commit and keep its task (BF-960).

        A cancelled timer never runs its callback, and every re-arm cancels the
        previous timer first, so the timer running this is ``_commit_timer``. It is
        cleared here, so a timer armed after this point is the next one, which
        ``flush()`` can still cancel. The task stays in ``_commit_tasks`` until it
        is done, so ``flush()`` can wait for it.
        """
        self._commit_timer = None  # BF-960: this timer has fired; one armed later is the next
        task = asyncio.create_task(self._flush_pending())
        self._commit_tasks.add(task)
        task.add_done_callback(self._on_commit_task_done)

    def _on_commit_task_done(self, task: asyncio.Task[None]) -> None:
        """Forget a finished debounce task; log an exception it ended with (BF-960)."""
        self._commit_tasks.discard(task)
        if task.cancelled():
            return
        exc = task.exception()
        if exc is not None:
            log.warning(
                "Knowledge store debounced commit failed at %s: %s; the writes "
                "stay on disk and the next commit or the shutdown flush includes them",
                self._repo_path,
                exc,
            )

    def _take_pending(self) -> str | None:
        """Hand the pending commit messages, joined, to one committer (BF-960).

        Synchronous, so nothing else runs between the read and the clear: each
        message is taken, and committed, by exactly one caller. ``None`` when
        nothing is pending.
        """
        if not self._pending_messages:
            return None
        combined = "; ".join(self._pending_messages)
        self._pending_messages.clear()
        return combined

    async def _flush_pending(self) -> None:
        """Commit all pending messages.  Called by the debounce timer's task.

        BF-960: ``_take_pending`` and the commit lock request in ``_git_commit``
        follow each other with no suspension point, so a ``flush()`` that starts
        later queues behind this commit. The timer reference is cleared by
        ``_on_commit_timer``, not here.
        """
        if self._flushing:  # BF-960: a flush that has begun takes the pending messages itself
            return
        combined = self._take_pending()
        if combined is None:
            return
        await self._git_commit(combined)

    async def _git_commit(self, message: str) -> None:
        """Run git add + commit in thread executor (AD-166), one sequence at a time.

        BF-960: the whole sequence runs under ``_commit_lock``, so a second caller
        (the debounce task, ``flush()`` or ``rollback_artifact``) waits for the
        first instead of meeting git's ``index.lock``. Nothing under the lock takes
        it again: ``_git_add_and_commit`` awaits only ``_git_run`` and
        ``_recover_last_commit_sha``, and neither calls back into this method.
        """
        if not self._git_available:
            return
        async with self._commit_lock:
            await self._git_add_and_commit(message)

    async def _git_add_and_commit(self, message: str) -> None:
        """The add-and-commit sequence with its recovery; call only under ``_commit_lock``.

        BF: Concurrent processes touching the same repo can leave the
        index or HEAD ref in a half-written state. Detect both classes
        and recover in place rather than just logging a warning.
        """
        try:
            result_add = await self._git_run("add", "-A")
```

**P2-3.** `src/probos/knowledge/store.py`
SEARCH:
```
    async def flush(self) -> None:
        """Force commit any pending changes.  Called on shutdown.

        Sets _flushing=True, cancels pending timer, commits, resets flag (AD-161).
        """
        self._flushing = True
        try:
            if self._commit_timer is not None:
                self._commit_timer.cancel()
                self._commit_timer = None

            if self._pending_messages:
                messages = self._pending_messages[:]
                self._pending_messages.clear()
                combined = "; ".join(messages)
                await self._git_commit(combined)
            else:
                # Commit any un-committed file changes
                await self._git_commit("Shutdown flush")
        finally:
            self._flushing = False
```
REPLACE:
```
    async def flush(self) -> None:
        """Force commit any pending changes.  Called on shutdown.

        Sets _flushing=True, cancels pending timer, commits, resets flag (AD-161).

        BF-960: before its own commit it waits for every debounce task already
        started, so no such task is still running when it returns. It waits and
        never cancels: a task's git child runs in an executor thread that
        cancelling cannot stop, so a cancelled task would leave git holding
        ``index.lock``. It holds no lock while it waits (a task needs
        ``_commit_lock``), and if ``flush()`` itself is cancelled the tasks run on.
        Each git command is bounded by ``_git_run``'s 30 s timeout.
        """
        self._flushing = True
        try:
            if self._commit_timer is not None:
                self._commit_timer.cancel()
                self._commit_timer = None

            running = {task for task in self._commit_tasks if not task.done()}
            if running:
                await asyncio.wait(running)  # BF-960: wait, never cancel; see the docstring

            # Commit the pending writes, or any un-committed file changes
            combined = self._take_pending()
            await self._git_commit(combined if combined is not None else "Shutdown flush")
        finally:
            self._flushing = False
```

**N2-1.** `tests/test_bf960_knowledge_flush_race.py`
SEARCH:
```
@_BUILT
async def test_flush_waits_for_the_debounced_commit_in_flight_and_nothing_lands_after_it(
```
REPLACE:
```
async def test_flush_waits_for_the_debounced_commit_in_flight_and_nothing_lands_after_it(
```

**N2-2.** `tests/test_bf960_knowledge_flush_race.py`
SEARCH:
```
@_BUILT
async def test_two_concurrent_flushes_both_wait_and_neither_meets_the_lock(
```
REPLACE:
```
async def test_two_concurrent_flushes_both_wait_and_neither_meets_the_lock(
```

**N2-3.** `tests/test_bf960_knowledge_flush_race.py`
SEARCH:
```
@_BUILT
async def test_a_rollback_during_the_debounced_commit_queues_behind_it_and_head_matches_the_file(
```
REPLACE:
```
async def test_a_rollback_during_the_debounced_commit_queues_behind_it_and_head_matches_the_file(
```

**N2-4.** `tests/test_bf960_knowledge_flush_race.py`
SEARCH:
```
@_BUILT
@pytest.mark.parametrize("git", ["absent", pytest.param("present", marks=_GIT)])
```
REPLACE:
```
@pytest.mark.parametrize("git", ["absent", pytest.param("present", marks=_GIT)])
```

**N2-5.** `tests/test_bf960_knowledge_flush_race.py`
SEARCH:
```
@_BUILT
async def test_a_timer_armed_before_the_fired_timers_task_starts_stays_the_one_flush_cancels(
```
REPLACE:
```
async def test_a_timer_armed_before_the_fired_timers_task_starts_stays_the_one_flush_cancels(
```

**N2-6.** `tests/test_bf960_knowledge_flush_race.py`
SEARCH:
```
@_BUILT
async def test_a_debounce_task_that_raises_is_logged_once_and_forgotten(
```
REPLACE:
```
async def test_a_debounce_task_that_raises_is_logged_once_and_forgotten(
```

**N2-7.** `tests/test_bf960_knowledge_flush_race.py`
SEARCH:
```
_GIT = pytest.mark.skipif(shutil.which("git") is None, reason="git not available")
_BUILT = pytest.mark.xfail(raises=AssertionError, strict=True, reason="BF-960 M2 builds it")
```
REPLACE:
```
_GIT = pytest.mark.skipif(shutil.which("git") is None, reason="git not available")
```

After N2-7, `@_BUILT` must have 0 matches in the file.

### 7.3 M3: tracking

**P3-1.** `PROGRESS.md`. The anchor is the title line and the blank line after it (once). Replace `DATE` with M3's date.
SEARCH:
```
# ProbOS Progress

```
REPLACE:
```
# ProbOS Progress

**BF-960 (DATE), #1767 -- the knowledge store's shutdown flush waits for the debounced commit in flight.**
- **Base.** `KnowledgeStore`'s debounce timer started its commit with `asyncio.create_task` and kept no reference to the task. `flush()` neither waited for that task nor serialized with it. A flush that started while the task's `git add` held `.git/index.lock` logged `Git add failed` and returned, and the task's commit landed after `rt.stop()`. The issue measured 10 files under `.git` changing afterwards. This was the intermittent red in `tests/test_bf906_crew_enrollment_boot.py`.
- **Fix.** `_git_commit` runs its add-and-commit sequence under one `asyncio.Lock` (`_commit_lock`), so the debounce task, `flush()` and `rollback_artifact` queue instead of meeting git's lock. The timer's callback `_on_commit_timer` keeps each task in `_commit_tasks` until it is done, and an exception the task ends with is logged at WARNING. `flush()` waits for those tasks with `asyncio.wait`, never cancelling them, because a git child in an executor thread cannot be stopped. Then it commits what is pending. `_take_pending` hands the pending messages to exactly one committer.
- **Changed.** At shutdown, `flush()` can take longer by one in-flight debounced commit. A timer re-armed between a timer firing and its task starting is no longer lost.
- **Not changed.** `startup/shutdown.py`, the configuration, `_git_run` and its 30 s timeout, the index and ref recovery paths, and Ship's Records. The contract is `prompts/bf-960-knowledge-flush-race.md`.

```

**P3-2.** `DECISIONS.md`. Append after AD-1358 S1's entry on main (orchestrator re-anchor, see the note at the top). Its last bullet must occur once. If BF-955 has landed first, its entry also follows this bullet; insert BF-960 directly after the bullet either way.
SEARCH:
```
- *Reversal.* Revert the AD-1358 S1 commits.
```
REPLACE:
```
- *Reversal.* Revert the AD-1358 S1 commits.

### BF-960 -- The knowledge store's shutdown flush waits for the debounced commit in flight (DATE, #1767)

- *Scope.* `knowledge/store.py`: `KnowledgeStore.__init__`, `_schedule_commit`, `_on_commit_timer`, `_on_commit_task_done`, `_take_pending`, `_flush_pending`, `_git_commit`, `_git_add_and_commit` and `flush`, plus tests. Contract `prompts/bf-960-knowledge-flush-race.md`.
- *G1 (serialization).* One `asyncio.Lock` over the whole add-and-commit sequence, created in `__init__` as `RecordsStore` does. Rejected: a single-flight commit worker (more state for the same ordering); a per-command thread lock (two callers' adds and commits could interleave); retrying on `index.lock` (it depends on timing, and the commit still lands after stop).
- *G2 (the task).* Each task is kept in a set until it is done. `flush()` waits with `asyncio.wait` and never cancels. Rejected: `await task` (a cancelled flush would cancel the commit); `asyncio.shield` (it raises the task's exception in flush, whereas the done callback logs it); cancelling (git keeps running in its thread and keeps `index.lock`).
- *G3 (hand-off).* `_flushing` stays: once a flush has begun, it commits everything pending in one commit. `_take_pending` is synchronous, and nothing suspends between it and the lock request, so each message is committed once. The timer reference is cleared by the timer's own callback.
- *Not changed.* `startup/shutdown.py`, `_git_run`, the recovery paths, the configuration.
- *Residual.* Recorded limits L1 to L8 of the contract.
- *Reversal.* Revert the BF-960 commits.
```

**Ledger.** Run G3. The roadmap Bug Tracker is not edited: a Grep for `BF-9[56][0-9]` in `docs/development/roadmap.md` finds 0. No doc names the edited internals: a Grep for `_flushing|_commit_timer|_flush_pending|_git_commit|_pending_messages` in `docs/` finds 0.

## 8. What this does NOT change

- `startup/shutdown.py`, including the flush at `:2082` and its `except Exception`.
- `_git_run`, its environment and its 30 s timeout; `_recover_last_commit_sha`.
- The add-and-commit body, which moves unchanged from `try:` onward.
- `_ensure_repo`, the configuration, every `store_*` method, `rollback_artifact`'s own code, and `artifact_history`.
- Ship's Records (`records_store.py`, #1760).
- `tests/test_bf906_crew_enrollment_boot.py` and `tests/test_knowledge_store.py`, which stay unedited.

## 9. Mutation rows (each Line occurs once, stripped, in `src/probos/knowledge/store.py` on M2's head)

| # | M | File | Line (stripped) | Mutate to | Killed by |
|---|---|---|---|---|---|
| 1 | M2 | src/probos/knowledge/store.py | `async with self._commit_lock:` | `if True:` | T4 |
| 2 | M2 | src/probos/knowledge/store.py | `async with self._commit_lock:` | `if await self._commit_lock.acquire():` | T1, T5[raises], T5[fails] (flush times out) |
| 3 | M2 | src/probos/knowledge/store.py | `await asyncio.wait(running)  # BF-960: wait, never cancel; see the docstring` | `pass` | T7[absent] |
| 4 | M2 | src/probos/knowledge/store.py | `await asyncio.wait(running)  # BF-960: wait, never cancel; see the docstring` | `await asyncio.gather(*running)` | T6 |
| 5 | M2 | src/probos/knowledge/store.py | `await asyncio.wait(running)  # BF-960: wait, never cancel; see the docstring` | `[task.cancel() for task in running]` | T1, T3, T6 |
| 6 | M2 | src/probos/knowledge/store.py | `self._pending_messages.clear()` | `pass` | T1, T3, T8 |
| 7 | M2 | src/probos/knowledge/store.py | `self._commit_tasks.add(task)` | `pass` | T7[absent], T8 |
| 8 | M2 | src/probos/knowledge/store.py | `self._commit_tasks.discard(task)` | `pass` | T7, T10 |
| 9 | M2 | src/probos/knowledge/store.py | `task.add_done_callback(self._on_commit_task_done)` | `pass` | T7, T10 |
| 10 | M2 | src/probos/knowledge/store.py | `self._commit_timer = None  # BF-960: this timer has fired; one armed later is the next` | `pass` | T8 |
| 11 | M2 | src/probos/knowledge/store.py | `if combined is None:` | `if combined is None or setattr(self, "_commit_timer", None):` | T8 |
| 12 | M2 | src/probos/knowledge/store.py | `if self._flushing:  # BF-960: a flush that has begun takes the pending messages itself` | `if False:` | T7[present] |
| 13 | M2 | src/probos/knowledge/store.py | `if exc is not None:` | `if False:` | T10 |
| 14 | M2 | src/probos/knowledge/store.py | `running = {task for task in self._commit_tasks if not task.done()}` | `running = set()` | T7[absent] |

- **No mutant is killed by T2 or T9.** They are guards against a regression in behaviour that already worked.
- **Rows 1 and 3 are not killed by T1, and this is by design.** Each of the two mechanisms alone keeps the RACE scenario correct (§0).
- **No campaign of record yet.** The Builder runs these mutants on M2's head.

## 10. Recorded limits

- **L1.** The lock binds to the loop of its first contended acquire. A store whose lock was contended under one loop and is contended again under another raises `RuntimeError`. Production runs one loop. The suite's reuse of a store across `asyncio.run` calls (`test_knowledge_store_git_recovery.py`) never contends.
- **L2.** A write after `flush()` returns arms a new timer, as on the base. Shutdown writes nothing to the store after `:2082` (§11).
- **L3.** With two concurrent `flush()` calls, the first one's `finally` clears `_flushing` while the second is still committing. A write in that window arms a timer, as on the base.
- **L4.** When a debounced commit's `add` or `commit` fails, its messages are lost from the commit log. The files are not lost: the next commit includes them. This is unchanged. T5 does not pin the subjects for this reason.
- **L5.** A rollback during the debounced commit can have the rolled-back file committed under the debounce message. The rollback's own commit is then empty (`--allow-empty`). HEAD still equals the file (T4). This is unchanged in kind.
- **L6.** Shutdown waits longer by at most the in-flight commit. That is normally one `add` and one `commit`. In the worst case it is the recovery path, with each git command up to 30 s. No new timeout is added.
- **L7.** A debounce task left pending by a loop that closed without cancelling it never completes, so a `flush()` on a later loop would wait for it. `asyncio.run` cancels and drains its tasks on exit. Not measured: whether pytest-asyncio's teardown does the same. Every store in the suite is function-scoped.
- **L8.** Before the build, T1, T3, T4 and T6 each rely on one failing git `add` ending inside `_RELEASE_AFTER` (T4: `_ROLLBACK_WINDOW`) while the lock is held. On a host where one git launch takes longer, G1 can show an XPASS (T1, T3, T4) or a T6 failure. After the build these windows only delay a release; no assertion depends on them.

## 11. Verified Against Codebase (2026-11-07, tree `eb204e3c`)

```
git rev-parse HEAD HEAD:src/probos/knowledge/store.py HEAD:tests/test_knowledge_store.py HEAD:src/probos/startup/shutdown.py
  -> eb204e3c…, c2135ed2…, 4da2a472…, e006c05f…
git status --short -> empty
git diff --stat origin/main HEAD -- store.py shutdown.py test_knowledge_store.py test_knowledge_store_git_recovery.py test_bf906_crew_enrollment_boot.py -> empty
Read store.py:100-132 (__init__ :114-117), :1018-1061 (_ensure_repo returns at :1028 when initialised), :1063-1303, :1309-1360, :1405-1418 (trust -> trust/snapshot.json), :1476-1493 (_write_json awaits run_in_executor)
rg "_git_commit" store.py -> 1103, 1105, 1219, 1222, 1359 (callers outside _git_commit/_git_run/_recover_last_commit_sha: no re-entry)
rg "_flushing|_commit_timer|_flush_pending|_git_commit\b|_pending_messages" src -> store.py only
rg same tests -> test_knowledge_store.py, test_knowledge_store_git_recovery.py only (read :735-777, :1776-1819, :2022-2064, :3245-3249, :3313-3316; none pins the clear at :1100)
rg "_commit_lock|_commit_tasks|_on_commit_timer|_on_commit_task_done|_take_pending|_git_add_and_commit" (*.py) -> records_store.py:588,:1812 (_commit_lock, other class); test_ad1125…:3043 (function-name substring); else 0
Read records_store.py:584-598, :1801-1825 (prior art: asyncio.Lock in __init__, async with around the commit)
Read shutdown.py:2050-2091; rg "_knowledge_store\." shutdown.py -> 1602, 2066, 2068, 2076, 2078, 2082 (no write after the flush)
Read test_bf906_crew_enrollment_boot.py:433-481; rg knowledge|flush test_issue1419… -> :540-582 (store mocked; flush recorded)
Read ad1343_seam_census.py:25-42, ad1343_seam_registry.py:70-89 (RECORDED names; none added)
rg "knowledge/store" tests -> ad1346_effect_census.py:144 (_git_run,1), ad1346_file_write_census.py:170 (file row), test_bf892:102 (_git_run), test_knowledge_store.py imports; test_quality_hardening.py:50 getsource(_git_run)
rg "knowledge" ad1346_store_census.py -> :166-170 (other knowledge files; SQL scan :87-101)
Read check_architecture_principles.py:80-98, :652-686, :928-945, :1071; architecture-baseline.yaml:767-775 (srp-size triggers only); rg broad_create_task tests -> 0
rg "\"tests\"\).rglob" tests -> ad1270e2g:727, ad1270f:902,:1069 (the new file names no fast_teardown and no moved config class by string)
rg "ast\.parse\(" tests -> 175 files (re-derived; the 2026-10-22 list was not trusted); the readers whose scope includes store.py and key on names are the rows above
rg "autouse=True|create_task" tests/conftest.py -> sync fixtures only; no task left in a test's loop
CPython 3.12.13 Lib/asyncio: locks.py:92-105 (fast path; _get_loop on contention), mixins.py:12-20 (bind/raise), tasks.py:530-563 (_wait: callbacks on fs, awaits its own waiter), base_events.py:1983-1986 (cancelled ready handle skipped)
pyproject.toml:9 requires-python >=3.12; :181 asyncio_mode auto; :196 addopts -n 16 --dist=loadfile
command_env.py:134-149 trusted_command_env = dict(os.environ); test_bf957_records_git_signal.py:93-119 (_isolate_git pattern copied)
config_models/knowledge.py:286 commit_debounce_seconds 5.0 (unchanged)
gh issue view 1767 -> OPEN, bug, "BF-960: …"; rg -i "bf-?960" -> DECISIONS.md:1569 commit hash only
DECISIONS.md "- *Reversal.* Revert the BF-958 commits." -> once (:1511); PROGRESS.md:1 "# ProbOS Progress" then blank :2
SEARCH uniqueness (store.py): ":116 self._commit_timer: asyncio.TimerHandle | None = None" once; ":1085 lambda: asyncio.create_task(self._flush_pending())," once; ":1222 await self._git_commit(\"Shutdown flush\")" once
```

**Not measured.**
- The `--collect-only` counts. The bridge allows no pytest, so M0 records them.
- The new file's runtime. Estimated at about 8 s.
- Whether pytest-asyncio's loop teardown cancels pending tasks (L7).

## 12. Prior Art and Blind Spots

- **Internal, adopted.** `RecordsStore._commit_lock` (`records_store.py:588`, `:1812`): an `asyncio.Lock` created in `__init__` and held around the commit.
- **Internal, adapted.** AD-161's `_flushing` guard stays, and BF-960 adds an ordering guarantee alongside it. BF-816 (#1280) fixed the tests' calibrated sleeps against the same debounce; this fixes the production ordering behind them.
- **External: Python docs** ([asyncio tasks](https://docs.python.org/3/library/asyncio-task.html)).
  - `create_task`: "Save a reference to the result of this function … The event loop only keeps weak references to tasks." **Adopted.**
  - `wait`: "If `wait()` is cancelled, the futures in *aws* are not cancelled and continue to run." **Adopted** over `shield` and `gather`.
- **External: git's `index.lock`.** A second writer fails rather than waiting ([Pluralsight](https://www.pluralsight.com/resources/blog/guides/understanding-and-using-gits-indexlock-file)). git-annex fixed parallel `git add` jobs by letting one thread flush at a time ([git-annex commit](https://ayakael.net/mirrors/git-annex/commit/3a71f3a4a955c0334f5f68defecd5995a424ee2d)). **Adopted:** the store serializes itself, and nothing retries.
- **`reference-projects.md`** (judged on 2026-11-07). No row concerns git locking or asyncio shutdown ordering, so no row was examined or updated. The overdue row (AG-UI, never reviewed) is not relevant: considered, deferred.
- **Blind spots handled.**
  - Each mechanism masks the other in the RACE test, so each has its own scenario (T4 and T7).
  - A cancelled flush must not cancel the commit (T6).
  - The callback runs for a task that was cancelled (it checks `cancelled()` before `exception()`).
  - The `_commit_timer` reference could be lost (T8).
  - Host git configuration leaks into real-git tests (the autouse fixture).
  - A second task can start while the first is still in git (hence a set).
- **Considered, deferred.**
  - Re-queueing the messages of a failed commit (L4).
  - A timeout on the shutdown flush. Today each git command is already bounded at 30 s, and adding a timeout would change `shutdown.py`.

## 13. Diff Reviewer: properties to verify

1. **The lock.** `_commit_lock` is taken only in `_git_commit`, only through `async with`. Under it, only `_git_run` and `_recover_last_commit_sha` are awaited, and neither reaches `_git_commit`, `flush` or `_flush_pending`.
2. **`flush()`'s wait.** `flush()` holds no lock while it waits. It waits with `asyncio.wait` and never cancels a task. `running` is computed after the timer is cancelled and before `_take_pending()`.
3. **Task lifetime.** Every task `_on_commit_timer` creates is in `_commit_tasks` until it is done, and `_on_commit_task_done` removes it. The callback cannot raise: it checks `cancelled()` before `exception()`.
4. **No gap before the lock.** In `_flush_pending`, nothing can suspend between `_take_pending()` and the lock request. In `_git_commit`, only the `_git_available` check comes before `async with`.
5. **Single writers.** `self._pending_messages.clear()` appears only in `_take_pending`. `_commit_timer = None` appears only in `_on_commit_timer` and `flush()`.
6. **Logging under the lock is safe.** The warnings inside `_git_add_and_commit` run while `_commit_lock` is held. A logging handler is synchronous and cannot await an `asyncio.Lock`, so it cannot wait on it. The new WARNING says what failed, where, and what happens next.
7. **Moved code is unchanged.** The body of `_git_add_and_commit` from `try:` onward is byte-identical to the base's `_git_commit` body. `shutdown.py`, `_git_run`, `_recover_last_commit_sha` and the configuration have no diff.
8. **The test file.** At M1, each xfail case fails at an `AssertionError`. At M2, `_BUILT` is gone. The test isolates git configuration before its first git call.

## 14. Acceptance criteria

- G1, G2 and G3 pass as stated. The broad gate is green, with a receipt.
- T1 (the issue's RACE scenario) passes. When `flush()` returns, the repository holds its commit, no `Git add failed` warning was logged, and nothing under `.git` changes after the store's tasks settle. T2 (the SETTLED control) passes on the base and after the change.
- T3, T4 and T6 pass: two concurrent flushes, a rollback during the commit, and a cancelled flush each end with a consistent repository, and none deadlocks.
- `tests/test_knowledge_store.py` and `tests/test_bf906_crew_enrollment_boot.py` pass unchanged.
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

Sources:
- [Python docs: asyncio coroutines and tasks](https://docs.python.org/3/library/asyncio-task.html)
- [Pluralsight: Understanding and Using Git's index.lock File](https://www.pluralsight.com/resources/blog/guides/understanding-and-using-gits-indexlock-file)
- [git-annex commit on parallel git add and the index lock](https://ayakael.net/mirrors/git-annex/commit/3a71f3a4a955c0334f5f68defecd5995a424ee2d)
