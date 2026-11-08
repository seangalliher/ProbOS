# BF-960 (#1767): the knowledge store's shutdown flush waits for the debounced commit in flight

**Drafted by:** `claude-architect` (Claude Code, Opus 5.5), 2026-11-07
**Revised by:** the Copilot `Architect` (fallback for `claude-architect`), 2026-11-07 (the caller's clock): Amendment A2, the repair of review round 1 (gpt-6.1-sol, NOT READY). With `auto_commit` on and one active flush, a write that lands while `flush()` commits is now committed before `flush()` returns (P2, not introduced here), bounded at `_FLUSH_DRAIN_PASSES` extra commits; the shutdown-wait claim is corrected (P3). T11 to T13 are added, rows 15 to 20 are added, L2, L3 and L6 are revised, and L9 and L10 are added. Amendment A3 (review round 2, two P3 text findings) states that scope: L2, L3 and L6 are revised again and L11 is added. It changes no code line, no test and no mutation row. See the end of this file.
**Status:** ready to build on `origin/main` `46950c39` (see the orchestrator note: it is built before the BF-957 + BF-958 batch merges).
**Base:** the anchors were taken at `eb204e3c674a47cf5edc9cee4c8b8819d1160961`. `src/probos/knowledge/store.py` is blob `c2135ed2`, `tests/test_knowledge_store.py` is blob `4da2a472`, and `src/probos/startup/shutdown.py` is blob `e006c05f`.
**Dependencies:** none in code.
**Orchestrator note (2026-11-07, before building):** (1) **Order.** The BF-957 + BF-958 batch (PR #1768) has not merged. Its fourth canonical gate failed on this issue's race again, with the first gate's signature, so by the Architect's rule for that case this item is built FIRST, on `origin/main` `46950c39`, merged, and then main is merged into the batch branch. `store.py`, `shutdown.py` and the named test files have the same text on `46950c39` as at `eb204e3c` (the batch does not touch them), so every source and test pair applies unchanged: `git diff --stat eb204e3c HEAD -- <those files>` is empty on the build tree. (2) **Amendment A1 (T6).** The orchestrator's rehearsal of this contract by tool found T6 (`test_a_cancelled_flush_leaves_the_debounced_commit_running_to_its_end`) non-deterministic on the unbuilt base (2 failures in 5 runs; stable once built: 15 of 15, the file 4 of 4, the loaded G2 command 3 of 3). The Copilot `Architect` (the Claude Code bridge's login had expired) decided option C: T6 releases the injected hold `_RELEASE_AFTER` after it cancels `flush()`, not at once. The five amendment pairs (the G1 sentence, the section 6 note, the constant's comment, T6's release, limit L8) are already applied to this text; G1 is unchanged (5 passed, 7 xfailed). (3) **Trackers.** Main's DECISIONS.md has no BF-958 entry, so P3-2 is re-anchored on AD-1358 S1's last bullet (`- *Reversal.* Revert the AD-1358 S1 commits.`, once on main), and the residual line read L1 to L8 (L1 to L10 after Amendment A2, L1 to L11 after Amendment A3). When main is merged into the batch branch later, the two insertions at that point conflict: keep both entries and regenerate the ledger.
**Tier:** M1 STANDARD, M2 HIGH, M3 STANDARD.
**Estimated tests:** one new file with 10 functions and 12 cases; after Amendment A2, 13 functions and 15 cases. No existing test file is edited. Counted by reading, not by running.

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
- **`flush()`.** After cancelling the timer, it waits for the running tasks with `asyncio.wait` and never cancels them. Then it commits what `_take_pending()` hands it, or `"Shutdown flush"` when nothing is pending. After that commit it makes up to `_FLUSH_DRAIN_PASSES` more, one per batch of writes that landed during the previous one (A2).
- **`_schedule_commit`.** With `auto_commit` on (L11), while `_flushing` it keeps the message and arms no timer, so `flush()` commits it (A2). With two overlapping flushes `_flushing` can be false while one still runs (L3). The base dropped it.
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
  - Expected: **12 passed** in the new file at M2 (**15 passed** after Amendment A2), in both runs. Every other file has 0 failed, and its collected count equals M0. The architecture check is clean.
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
- **A2:** `BF-960 (#1767): Amendment A2, the repair of review round 1: flush() commits writes that land while it commits`
- **A3:** `BF-960 (#1767): Amendment A3, the repair of review round 2: the late-write promise is scoped to auto_commit on and one active flush (text and docstrings only)`

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
| T11 | `test_a_write_that_lands_while_flush_commits_is_in_head_when_flush_returns` | 1 | A2: a write whose file lands after flush()'s `add` is in HEAD when `flush()` returns; nothing pending, no timer | none (fails on the base: the message is dropped) |
| T12 | `test_a_write_that_lands_while_the_drain_commits_is_committed_too` | 1 | A2: a second write lands during the first drain commit; pins the loop | none (fails on the base) |
| T13 | `test_a_writer_that_never_stops_cannot_hold_flush_past_the_drain_bound` | 1 | A2: the bound, the warning and the message left pending | none (fails before A2 at `monkeypatch.setattr`: no `_FLUSH_DRAIN_PASSES`) |

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
- **Fix.** `_git_commit` runs its add-and-commit sequence under one `asyncio.Lock` (`_commit_lock`), so the debounce task, `flush()` and `rollback_artifact` queue instead of meeting git's lock. The timer's callback `_on_commit_timer` keeps each task in `_commit_tasks` until it is done, and an exception the task ends with is logged at WARNING. `flush()` waits for those tasks with `asyncio.wait`, never cancelling them, because a git child in an executor thread cannot be stopped. Then it commits what is pending, and, with `auto_commit` on and one flush at a time, commits again for each batch of writes that lands while it commits, up to five more commits (on the base such a write stayed uncommitted until the next commit). `_take_pending` hands the pending messages to exactly one committer.
- **Changed.** At shutdown, `flush()` waits for every debounced commit that is running or queued when it starts, each normally one `git add` and one `git commit`, then makes its own commit and, with `auto_commit` on, up to five more for writes that land while it commits; there is no aggregate timeout. With `auto_commit` on and one flush at a time, a write that lands while a flush runs keeps its message and arms no timer. With `auto_commit` off no message is kept, and such a write stays uncommitted until the next commit, as before (L11). If two flushes overlap, a write that lands after the first one ends arms a timer, and that commit can end after the second returns, as before (L3). A timer re-armed between a timer firing and its task starting is no longer lost.
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
- *G3 (hand-off).* `_flushing` stays: once a flush has begun, it takes everything pending for its own commit. `_take_pending` is synchronous, and nothing suspends between it and the lock request, so each message is committed once. The timer reference is cleared by the timer's own callback.
- *G4 (late writes, A2).* With `auto_commit` on and one flush at a time, a write that lands while the flush runs keeps its message and arms no timer; the flush commits it. After its own commit it makes up to `_FLUSH_DRAIN_PASSES` (5) more, one per batch that landed during the previous commit, and past that it warns and leaves the messages pending. With `auto_commit` off `_schedule_commit` returns before it keeps a message, so such a write stays uncommitted until the next commit, as before (L11). If two flushes overlap, the first one's exit clears `_flushing`, and a write after that arms a timer whose commit can end after the second returns, as before (L3); production has one flush, from `shutdown()`. Rejected: arming the timer (that commit would land after the store was told to stop, the defect this removes); asking git for a dirty tree after the commit (one more git call on every flush, and a tree that `add` cannot clean would loop); an unbounded drain (a writer that never stops would hold shutdown, and a `_take_pending` that failed to clear would hang it).
- *Not changed.* `startup/shutdown.py`, `_git_run`, the recovery paths, the configuration.
- *Residual.* Recorded limits L1 to L11 of the contract.
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

## 9. Mutation rows (each Line occurs once, stripped, in `src/probos/knowledge/store.py` on M2's head; rows 15 to 20 on A2's head)

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
| 15 | A2 | src/probos/knowledge/store.py | `await self._git_commit(late)` | `pass` | T11, T12, T13 |
| 16 | A2 | src/probos/knowledge/store.py | `for _ in range(_FLUSH_DRAIN_PASSES):` | `for _ in range(1):` | T12, T13 |
| 17 | A2 | src/probos/knowledge/store.py | `self._pending_messages.append(message)` | `if not self._flushing: self._pending_messages.append(message)` | T11, T12, T13 |
| 18 | A2 | src/probos/knowledge/store.py | `if self._flushing:  # BF-960 A2: flush() commits it; a timer would fire after it returns` | `if False:` | T11, T12 |
| 19 | A2 | src/probos/knowledge/store.py | `for _ in range(_FLUSH_DRAIN_PASSES):` | `while True:` | T13 (flush times out) |
| 20 | A2 | src/probos/knowledge/store.py | `if self._pending_messages:` | `if False:` | T13 |

- **No mutant is killed by T2 or T9.** They are guards against a regression in behaviour that already worked.
- **Rows 1 and 3 are not killed by T1, and this is by design.** Each of the two mechanisms alone keeps the RACE scenario correct (§0).
- **Campaign of record: none for A2 yet.** The run on `37a8b44d` (store.py blob `0c3de026`, test blob `1b71f992`; 14 of 14 killed) is superseded: store.py and the test file differ after A2. The Builder runs all 20 rows once on A2's head; the orchestrator records that run with the head tree and each file's sha256. Allow about 8 minutes for row 2 and 60 s for row 19.

## 10. Recorded limits

- **L1.** The lock binds to the loop of its first contended acquire. A store whose lock was contended under one loop and is contended again under another raises `RuntimeError`. Production runs one loop. The suite's reuse of a store across `asyncio.run` calls (`test_knowledge_store_git_recovery.py`) never contends.
- **L2.** A write after `flush()` returns arms a new timer, as on the base. With `auto_commit` on (L11) and one active flush (L3), a write whose `_schedule_commit` runs while `flush()` runs arms no timer: its message is kept and `flush()` commits it before it returns (A2, L9). Shutdown writes nothing to the store after `:2082` (§11).
- **L3.** With two concurrent `flush()` calls, the first one's `finally` clears `_flushing` while the second is still running. A write in that window arms a timer, as on the base, and whichever of the timer's task and the second flush takes its message first commits it. If the second flush takes it (at a take of its drain, before the timer fires), the timer then finds nothing pending. If the timer's task takes it (a debounce shorter than the rest of the second flush), the second flush can return with that write not yet in HEAD and that debounce commit still pending, as on the base. The return guarantee of L2 is therefore for one active flush. Production has one: the only call site is `shutdown.py:2082`; a rollback does not reach it (`:2063`), and the BF-598 guard (`:914`) returns a repeated `shutdown()` that is not a rollback. No test has a write in this window: T3, the only test with two concurrent flushes, has none.
- **L4.** When a debounced commit's `add` or `commit` fails, its messages are lost from the commit log. The files are not lost: the next commit includes them. This is unchanged. T5 does not pin the subjects for this reason.
- **L5.** A rollback during the debounced commit can have the rolled-back file committed under the debounce message. The rollback's own commit is then empty (`--allow-empty`). HEAD still equals the file (T4). This is unchanged in kind.
- **L6.** Shutdown waits for every debounced commit that is running or queued behind the commit lock when `flush()` starts, then for its own commit, then, with `auto_commit` on, for one more commit per batch of writes that lands while it commits, at most `_FLUSH_DRAIN_PASSES` (A2). Each is normally one `add` and one `commit`; in the recovery path each git command is bounded by 30 s. There is no aggregate timeout, and no new timeout is added.
- **L7.** A debounce task left pending by a loop that closed without cancelling it never completes, so a `flush()` on a later loop would wait for it. `asyncio.run` cancels and drains its tasks on exit. Not measured: whether pytest-asyncio's teardown does the same. Every store in the suite is function-scoped.
- **L8.** Before the build, T1, T3, T4 and T6 each rely on one failing git `add` ending inside `_RELEASE_AFTER` (T4: `_ROLLBACK_WINDOW`) while the lock is held. On a host where one git launch takes longer, G1 can show an XPASS (T1, T3, T4) or a T6 failure. After the build these windows only delay a release; no assertion depends on them.
- **L9.** The drain stops after `_FLUSH_DRAIN_PASSES` (5) extra commits. A writer that produces a message during every one of them leaves the last batch pending, with one WARNING (T13); the files stay on disk and the next commit or flush includes them, as on the base. No timer is armed for them: one armed during shutdown would commit after the store was told to stop. At `:2082` the pools, the IntentBus, the dream scheduler's monitor (`:1161`) and the proactive loop (`:1606`) have stopped, so only an in-flight request or task can still write. A `flush()` that is cancelled likewise leaves what it had not taken pending, with no timer; the base dropped those messages. A pass can be an empty commit (`--allow-empty`) when the `add` had already staged the file. The bound is a module constant, not a configuration field, as `_git_run`'s 30 s timeout is.
- **L10.** `store_cooldowns` schedules no commit (`store.py:915-921`), so it leaves no message for the drain: a cooldowns write that lands after a flush's `add` stays uncommitted until the next commit, as on the base and as for every cooldowns write. Each of the 12 `_schedule_commit(` call sites belongs to another writer.
- **L11.** With `auto_commit` off (the default is on: `config_models/knowledge.py:285`, `config/system.yaml:769`; startup passes the setting through, `cognitive_services.py:546-550`), `_schedule_commit` returns at its first guard, before it keeps a message, so L2 and the drain do not apply: no message is kept and no timer is ever armed. `_git_available` starts `None` and is set only by `_ensure_repo`, which nothing under `src` calls except `_schedule_commit`, behind that guard; `initialize()` does not call it (git init waits for the first write, AD-159). So with `auto_commit` off `_git_available` stays `None`, `_git_commit` returns at its guard, and `flush()` makes no git call: it commits nothing, not even a `Shutdown flush`, and every write of that store stays uncommitted until something else commits it (a later run with `auto_commit` on, for example), as on the base. Only on an instance whose `_git_available` was set true by other means (a test that calls `_ensure_repo` or assigns it) does `flush()` commit what is on disk at its `add`, as `Shutdown flush`. Where this contract says `flush()` commits, it means a store whose `_git_available` is true. T1 to T13 all run with `auto_commit=True` (`_store`, the only store built in the test file), so none of them covers the off case.

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
9. **Late writes (A2).** `_schedule_commit` appends the message before it checks `_flushing`, and arms no timer while `_flushing`. `flush()` repeats `_take_pending()` and `_git_commit(late)` at most `_FLUSH_DRAIN_PASSES` times, and nothing suspends between the take that finds nothing (or the warning) and `_flushing = False`. A write's file lands before its message is appended, so the pass that takes the message stages the file.
10. **The bound and the red state (A2).** Past `_FLUSH_DRAIN_PASSES`, `flush()` logs one WARNING, leaves the messages pending and arms no timer. On the pre-A2 `store.py`, T11 and T12 fail at an `AssertionError` and T13 at `monkeypatch.setattr`.

## 14. Acceptance criteria

- G1, G2 and G3 pass as stated. The broad gate is green, with a receipt.
- T1 (the issue's RACE scenario) passes. When `flush()` returns, the repository holds its commit, no `Git add failed` warning was logged, and nothing under `.git` changes after the store's tasks settle. T2 (the SETTLED control) passes on the base and after the change.
- T3, T4 and T6 pass: two concurrent flushes, a rollback during the commit, and a cancelled flush each end with a consistent repository, and none deadlocks.
- T11, T12 and T13 pass (they run with `auto_commit` on and one flush): a write that lands while `flush()` commits is in HEAD when it returns, a second one that lands during the drain is too, and a writer that never stops is cut off after `_FLUSH_DRAIN_PASSES` commits with a warning.
- `tests/test_knowledge_store.py` and `tests/test_bf906_crew_enrollment_boot.py` pass unchanged.
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

Sources:
- [Python docs: asyncio coroutines and tasks](https://docs.python.org/3/library/asyncio-task.html)
- [Pluralsight: Understanding and Using Git's index.lock File](https://www.pluralsight.com/resources/blog/guides/understanding-and-using-gits-indexlock-file)
- [git-annex commit on parallel git add and the index lock](https://ayakael.net/mirrors/git-annex/commit/3a71f3a4a955c0334f5f68defecd5995a424ee2d)

## Amendment A2 (2026-11-07): review round 1 (gpt-6.1-sol, NOT READY)

**Drafted by:** the Copilot `Architect` (fallback for `claude-architect`, whose login had expired), 2026-11-07 (the caller's clock). **Anchors:** candidate head `37a8b44d` (tree `1c78d6a1`); blobs `store.py` `0c3de026`, the test file `1b71f992`, `PROGRESS.md` `c65c582a`, `DECISIONS.md` `52b3cbb5`, this contract `bafa1d1a`. **Tier:** HIGH. A2-01 to A2-05 are M1 text (the test file), A2-06 and A2-07 are base text and A2-08 and A2-09 are M2 text (`store.py`), A2-10 to A2-13 are M3 text (the trackers). The Builder applies A2-01 to A2-13 in label order. C-01 to C-20 were applied to this file by the orchestrator and are not a Builder step.

### A2.1 Findings and decisions

| # | Finding (round 1) | Severity, reach | Introduced here | Decision |
|---|---|---|---|---|
| 1 | A write that lands while `flush()` commits, after its `add`, is dropped by `_schedule_commit` and is not in HEAD when `flush()` returns | P2, ordinary | no (the base behaves the same) | Keep the message, arm no timer, and `flush()` commits up to `_FLUSH_DRAIN_PASSES` more times (A2-01 to A2-09) |
| 2 | "longer by one in-flight debounced commit" understates the wait: three live tasks were drained | P3, ordinary | yes (the text) | Corrected in A2-10, A2-11, C-11, C-15 and C-16 |

### A2.2 Gates

- **GA2.1** after A2-01 to A2-05 on `37a8b44d`'s `store.py`: `PY -m pytest tests/test_bf960_knowledge_flush_race.py -q -n 0 -p no:randomly`. Expected **3 failed** (T11 and T12 at their `files` assertion, T13 at `monkeypatch.setattr`) and **12 passed**. Any other result is a hard stop.
- **GA2.2** after A2-06 to A2-09: the same command. Expected **15 passed**.
- **GA2.3** after A2-13: G2 (the new file 15 passed, every other file 0 failed with its M0 count, the architecture check clean, the loaded run), then G3.
- **GA2.4** the 20-row campaign on A2's head, once, as the campaign of record.

### A2.3 Pairs: A2-01 to A2-13

**A2-01.** `tests/test_bf960_knowledge_flush_race.py` (M1 text)
SEARCH:
```
from collections.abc import Callable
```
REPLACE:
```
from collections.abc import Awaitable, Callable
```

**A2-02.** `tests/test_bf960_knowledge_flush_race.py` (M1 text)
SEARCH:
```
    """Wraps the store's ``_git_run``: holds or fails the next ``add`` on request, and signals results."""
```
REPLACE:
```
    """Wraps the store's ``_git_run``: holds or fails the next ``add`` on request, runs a queued late
    writer after an ``add`` returns, and signals results."""
```

**A2-03.** `tests/test_bf960_knowledge_flush_race.py` (M1 text)
SEARCH:
```
        self.fail_next_add = ""  # "", "raises" or "fails"
```
REPLACE:
```
        self.fail_next_add = ""  # "", "raises" or "fails"
        self.after_add: list[Callable[[], Awaitable[None]]] = []  # one runs after each add returns
```

**A2-04.** `tests/test_bf960_knowledge_flush_race.py` (M1 text)
SEARCH:
```
        if verb == "add":
            self.add_returned.set()
        elif verb == "show":
```
REPLACE:
```
        if verb == "add":
            self.add_returned.set()
            if self.after_add:
                await self.after_add.pop(0)()  # a writer whose file lands right after this add
        elif verb == "show":
```

**A2-05.** `tests/test_bf960_knowledge_flush_race.py` (M1 text: the end of T10; T11 to T13 appended)
SEARCH:
```
    assert len(records) == 1 and "injected commit error" in records[0]
    assert store._commit_tasks == set()
```
REPLACE:
```
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
```

**A2-06.** `src/probos/knowledge/store.py` (base text)
SEARCH:
```
_SKILL_STORAGE_DIRS = frozenset({"skills", "skill_quarantine"})
```
REPLACE:
```
_SKILL_STORAGE_DIRS = frozenset({"skills", "skill_quarantine"})
# BF-960 A2: the most extra commits flush() makes, after its own, for writes that land while it
# commits. A writer that produced a message during every pass would otherwise hold shutdown (L9).
_FLUSH_DRAIN_PASSES = 5
```

**A2-07.** `src/probos/knowledge/store.py` (base text: `_schedule_commit`)
SEARCH:
```
        Batches writes within the debounce window.
        Skips if _flushing is True (shutdown flush is handling the commit).
        """
        if not self._config.auto_commit:
            return
        await self._ensure_repo()

        if self._flushing:
            return

        self._pending_messages.append(message)
```
REPLACE:
```
        Batches writes within the debounce window.
        While _flushing is True (a shutdown flush is running) the message is kept but no
        timer is armed: flush() commits it before it returns (BF-960 A2). The file is
        already on disk, so the flush's next add stages it.
        """
        if not self._config.auto_commit:
            return
        await self._ensure_repo()

        self._pending_messages.append(message)

        if self._flushing:  # BF-960 A2: flush() commits it; a timer would fire after it returns
            return
```

**A2-08.** `src/probos/knowledge/store.py` (M2 text: the `flush()` docstring)
SEARCH:
```
        Each git command is bounded by ``_git_run``'s 30 s timeout.
        """
        self._flushing = True
```
REPLACE:
```
        Each git command is bounded by ``_git_run``'s 30 s timeout.

        A2: a write that lands while ``flush()`` commits keeps its message
        (``_schedule_commit`` arms no timer for it), and ``flush()`` commits it before
        it returns: one more commit per batch that landed during the previous one, at
        most ``_FLUSH_DRAIN_PASSES``. Past that it logs a warning and leaves the
        messages pending; their files stay on disk for the next commit (limit L9).
        """
        self._flushing = True
```

**A2-09.** `src/probos/knowledge/store.py` (M2 text: the `flush()` body)
SEARCH:
```
            combined = self._take_pending()
            await self._git_commit(combined if combined is not None else "Shutdown flush")
        finally:
            self._flushing = False
```
REPLACE:
```
            combined = self._take_pending()
            await self._git_commit(combined if combined is not None else "Shutdown flush")

            # BF-960 A2: a write that lands while flush() commits keeps its message (see
            # _schedule_commit) and is committed here, one pass per batch. Nothing suspends
            # between the take that finds nothing and the reset below, so none arrives after it.
            for _ in range(_FLUSH_DRAIN_PASSES):
                late = self._take_pending()
                if late is None:
                    break
                await self._git_commit(late)
            else:
                if self._pending_messages:
                    log.warning(
                        "Knowledge store flush at %s: writes were still landing after %d extra "
                        "commits; %d message(s) stay pending and their files stay on disk for "
                        "the next commit",
                        self._repo_path,
                        _FLUSH_DRAIN_PASSES,
                        len(self._pending_messages),
                    )
        finally:
            self._flushing = False
```

**A2-10.** `PROGRESS.md` (M3 text)
SEARCH:
```
Then it commits what is pending. `_take_pending` hands the pending messages to exactly one committer.
```
REPLACE:
```
Then it commits what is pending, and commits again for each batch of writes that lands while it commits, up to five more commits (on the base such a write stayed uncommitted until the next commit). `_take_pending` hands the pending messages to exactly one committer.
```

**A2-11.** `PROGRESS.md` (M3 text)
SEARCH:
```
- **Changed.** At shutdown, `flush()` can take longer by one in-flight debounced commit. A timer re-armed between a timer firing and its task starting is no longer lost.
```
REPLACE:
```
- **Changed.** At shutdown, `flush()` waits for every debounced commit that is running or queued when it starts, each normally one `git add` and one `git commit`, then makes its own commit and up to five more for writes that land while it commits; there is no aggregate timeout. A write that lands while a flush runs keeps its message and arms no timer. A timer re-armed between a timer firing and its task starting is no longer lost.
```

**A2-12.** `DECISIONS.md` (M3 text)
SEARCH:
```
- *G3 (hand-off).* `_flushing` stays: once a flush has begun, it commits everything pending in one commit. `_take_pending` is synchronous, and nothing suspends between it and the lock request, so each message is committed once. The timer reference is cleared by the timer's own callback.
```
REPLACE:
```
- *G3 (hand-off).* `_flushing` stays: once a flush has begun, it takes everything pending for its own commit. `_take_pending` is synchronous, and nothing suspends between it and the lock request, so each message is committed once. The timer reference is cleared by the timer's own callback.
- *G4 (late writes, A2).* A write that lands while the flush runs keeps its message and arms no timer; the flush commits it. After its own commit it makes up to `_FLUSH_DRAIN_PASSES` (5) more, one per batch that landed during the previous commit, and past that it warns and leaves the messages pending. Rejected: arming the timer (that commit would land after the store was told to stop, the defect this removes); asking git for a dirty tree after the commit (one more git call on every flush, and a tree that `add` cannot clean would loop); an unbounded drain (a writer that never stops would hold shutdown, and a `_take_pending` that failed to clear would hang it).
```

**A2-13.** `DECISIONS.md` (M3 text)
SEARCH:
```
- *Residual.* Recorded limits L1 to L8 of the contract.
```
REPLACE:
```
- *Residual.* Recorded limits L1 to L10 of the contract.
```

### A2.4 Absence Verified (A2, on 37a8b44d)

CLAIM: KnowledgeStore.flush() has one production call site
RUN:   git grep -n -E "\.flush\(\)" 37a8b44d -- src/ ; git grep -n -E "def flush\(" 37a8b44d -- src/
FOUND: 12 hits for .flush(): file or stream handles, telemetry.py:131 (another class's flush, defined at :119), routers/system.py:409 (a logging handler), and startup/shutdown.py:2082 (await runtime._knowledge_store.flush()), the only knowledge-store one; defs: consultation/dispatch.py:217, knowledge/store.py:1263, security/audit.py:349, substrate/telemetry.py:119
HOLDS: yes

CLAIM: store_cooldowns schedules no commit
RUN:   git grep -n "_schedule_commit(" 37a8b44d -- src/
FOUND: store.py 171, 274, 312, 338, 471, 497, 547, 877, 898, 949, 970, 995 (def 1069); store_cooldowns spans 915-921
HOLDS: yes, none inside 915-921

CLAIM: no existing test pins the drop, and none of T1..T10 has a writer landing during a flush
RUN:   git grep -n -E "_flushing|_pending_messages|after_add" 37a8b44d -- tests/ ; git grep -n -E "store\.store_|\.flush\(\)" 37a8b44d -- tests/test_bf960_knowledge_flush_race.py
FOUND: _flushing: test_knowledge_store.py:2033, :2037 (comments); _pending_messages: :741, :777 ("== []" after rejected skill calls); after_add: none. In the new file every store_* call precedes its flush(): 176/179, 200/203, 223/226, 249-250, 287/290, 304-318, 339/342, 358-367, 381-385, 400 (T10 and T4's tail have no flush after the write)
HOLDS: yes

CLAIM: only store.py touches _flushing, _pending_messages or _commit_timer in src/
RUN:   git grep -n -E "_pending_messages|_flushing|_commit_timer" 37a8b44d -- src/
FOUND: knowledge/store.py only (lines 114-116, 1073-1146, 1266-1290)
HOLDS: yes

CLAIM: the old latency claim is carried only by PROGRESS.md:6 and contract lines 834 and 900
RUN:   git grep -n -i -E "one in-flight|in-flight debounced|at most the in-flight|in-flight commit|longer by one|waits longer" 37a8b44d -- .   (unfiltered, whole tree)
FOUND: 12 hits: those three, and nine in other ADs and BFs, delegation_budget.py and two UI tests (DECISIONS.md:2105 is "one in-flight read per ref", another entry)
HOLDS: yes

## Amendment A3 (2026-11-07): review round 2 (gpt-6.1-sol, NOT READY)

**Drafted by:** the Copilot `Architect` (fallback for `claude-architect`, whose login had expired), 2026-11-07 (the caller's clock). **Anchors:** candidate head `028633ff` (tree `b16cd7dd`); blobs `store.py` `2adedba4`, `PROGRESS.md` `405c494f`, `DECISIONS.md` `a2f57663`, this contract `cace3d08`. **Tier:** STANDARD (text only: no code line, no test, no mutation row). A3-01 and A3-02 are M2 text (the docstrings of `store.py`), A3-03 is M2 text (one comment in `flush()`'s body), and A3-04 to A3-07 are M3 text (the trackers). The Builder applies A3-01 to A3-07 in label order; each SEARCH is LF and occurs once in its target as committed at `028633ff`. C3-01 to C3-12 were applied to this file by the orchestrator, in label order, and are not a Builder step. A2's blocks stay as the record of what A2 applied; A3 amends the result, so read A2 and then A3.

### A3.1 Findings and decisions

| # | Finding (round 2) | Severity, reach | Introduced here | Decision |
|---|---|---|---|---|
| 1 | The A2 promise (a write that lands while a flush runs keeps its message, arms no timer and is committed by `flush()`) omits `auto_commit`: `_schedule_commit` returns at its first guard when the option is off, so no message is kept and a write after the flush's `add` stays uncommitted until the next commit | P3, ordinary configuration (a config field, default on) | yes (the text; the behaviour is the base's) | Scope the promise to `auto_commit` on wherever it is made; record the off case as L11 (A3-01 to A3-07, C3-01 to C3-12) |
| 2 | L3 says the second flush's drain commits a write in the overlap window and the timer then finds nothing; with a short debounce the timer's task takes the message first, and the second flush can return with the write not in HEAD while one debounce commit is pending | P3, injected only (production has one flush, A3.4) | yes (the text; the behaviour is the base's) | L3 states both outcomes, and the return guarantee is scoped to one active flush (A3-01, A3-02, C3-09) |

Choices. L11 is its own limit, over a clause in L2 (three scopes in one limit, and the docstrings need a label to cite) and over L9 (the drain bound). A3-03 scopes a comment, which is neither a docstring nor code, over leaving it (it points to `_schedule_commit` for the condition). Finding 2 is fixed in text, over a code change (a depth counter for `_flushing`, or serialising `flush()` callers): production cannot reach the window, the base has it, and code would reopen the 20-row campaign and need a test. L3 and L11 are recorded limits and are not pinned by a test, as L10 is not (the test file calls only `store_trust_snapshot`, `store_routing_weights` and `store_workflows`: A3.4). The old text quoted in A2.1, A2-11 and A2.4 stays: it is a table cell naming a corrected claim, a SEARCH that must equal the file as it was, and an enumeration's own command.

### A3.2 Gates

- **GA3.1** after A3-01 to A3-03: `git diff -U0 028633ff -- src/probos/knowledge/store.py` shows 3 hunks, each inside old lines 1076-1078, 1281-1285 or 1301-1303; no other file under `src/` or `tests/` differs; the 16 distinct lines of section 9's rows 1 to 20 each still occur once, stripped, in `store.py`.
- **GA3.2** after A3-04 to A3-07: each tracker pair replaces text inside one line (A3-07 changes one line of its two), so `git diff --numstat 028633ff -- PROGRESS.md DECISIONS.md` shows 2 lines added and 2 deleted in each file, and the line counts do not change.
- **GA3.3** the checks a docstring or comment can reach: (1) `PY -m pytest tests/test_bf960_knowledge_flush_race.py -q -n 0 -p no:randomly`: 15 passed; (2) `PY -P scripts/check_architecture_principles.py --check`: clean, `unowned-task=13`; (3) the loaded run, `PY -m pytest tests/test_bf960_knowledge_flush_race.py tests/test_knowledge_store.py -q`: 322 passed, 1 skipped, as measured on `028633ff`; (4) G3: `PY -P scripts/gen_ad_ledger.py --check` and `PY -m pytest tests/test_ad1184_ad_ledger.py -q -n 0`.
- **GA3.4** not rerun: the serial 14-file list of G2. No statement changes (two docstrings and one comment differ), so no behavioural test can change its verdict; the text-keyed readers run in the broad gate before push, which is already required. The campaign of record (the 20-row run on `028633ff`'s files) stays the campaign of record: A3 alters none of the 20 anchor lines, no other code line and no test, so no mutant needs a rerun; the record keeps tree `b16cd7dd` and the sha256 of `store.py` and of the test file as they were in that run. A diff that fails GA3.1 voids this rule.
- **Not changed by A3.** Every code line of `store.py`, `tests/`, the mutation rows (section 9), `startup/shutdown.py`, the configuration, `_FLUSH_DRAIN_PASSES`, and L1, L4 to L5, L7 to L10.
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

### A3.3 Pairs: A3-01 to A3-07

**A3-01.** `src/probos/knowledge/store.py` (M2 text: the `_schedule_commit` docstring)
SEARCH:
```
        While _flushing is True (a shutdown flush is running) the message is kept but no
        timer is armed: flush() commits it before it returns (BF-960 A2). The file is
        already on disk, so the flush's next add stages it.
```
REPLACE:
```
        With auto_commit off it returns at once: no message is kept and no timer is armed
        (BF-960 limit L11).
        With auto_commit on, while _flushing is True (a shutdown flush is running) the
        message is kept but no timer is armed: flush() commits it before it returns, up
        to its drain bound (BF-960 A2, limit L9). The file is already on disk, so the
        flush's next add stages it.
        This is for one active flush: the first of two overlapping flush() calls to
        finish clears _flushing on its way out, and a write after that arms a timer, as
        on the base (limit L3).
```

**A3-02.** `src/probos/knowledge/store.py` (M2 text: the `flush()` docstring)
SEARCH:
```
        A2: a write that lands while ``flush()`` commits keeps its message
        (``_schedule_commit`` arms no timer for it), and ``flush()`` commits it before
        it returns: one more commit per batch that landed during the previous one, at
        most ``_FLUSH_DRAIN_PASSES``. Past that it logs a warning and leaves the
        messages pending; their files stay on disk for the next commit (limit L9).
```
REPLACE:
```
        A2: with auto_commit on and one active flush, a write that lands while
        ``flush()`` commits keeps its message (``_schedule_commit`` arms no timer for
        it), and ``flush()`` commits it before it returns: one more commit per batch
        that landed during the previous one, at most ``_FLUSH_DRAIN_PASSES``. Past that
        it logs a warning and leaves the messages pending; their files stay on disk for
        the next commit (limit L9).

        A3, what that does not cover: with auto_commit off no message is kept, so a
        write after the flush's add stays uncommitted until the next commit (limit
        L11); and the first of two overlapping ``flush()`` calls to finish clears
        ``_flushing`` on its way out, so a write after that arms a timer whose commit
        can end after the other call returns (limit L3). In production only
        shutdown() calls it, once per run.
```

**A3-03.** `src/probos/knowledge/store.py` (M2 text: a comment in the `flush()` body, not a docstring and not code)
SEARCH:
```
            # BF-960 A2: a write that lands while flush() commits keeps its message (see
            # _schedule_commit) and is committed here, one pass per batch. Nothing suspends
            # between the take that finds nothing and the reset below, so none arrives after it.
```
REPLACE:
```
            # BF-960 A2: a message that _schedule_commit kept while flush() ran (see that
            # docstring: auto_commit on, one flush) is committed here, one pass per batch.
            # Nothing suspends between the take that finds nothing and the reset below, so
            # none arrives after it.
```

**A3-04.** `PROGRESS.md` (M3 text: line 5, the Fix bullet)
SEARCH:
```
Then it commits what is pending, and commits again for each batch of writes that lands while it commits, up to five more commits (on the base such a write stayed uncommitted until the next commit).
```
REPLACE:
```
Then it commits what is pending, and, with `auto_commit` on and one flush at a time, commits again for each batch of writes that lands while it commits, up to five more commits (on the base such a write stayed uncommitted until the next commit).
```

**A3-05.** `PROGRESS.md` (M3 text: line 6, the Changed bullet)
SEARCH:
```
then makes its own commit and up to five more for writes that land while it commits; there is no aggregate timeout. A write that lands while a flush runs keeps its message and arms no timer.
```
REPLACE:
```
then makes its own commit and, with `auto_commit` on, up to five more for writes that land while it commits; there is no aggregate timeout. With `auto_commit` on and one flush at a time, a write that lands while a flush runs keeps its message and arms no timer. With `auto_commit` off no message is kept, and such a write stays uncommitted until the next commit, as before (L11). If two flushes overlap, a write that lands after the first one ends arms a timer, and that commit can end after the second returns, as before (L3).
```

**A3-06.** `DECISIONS.md` (M3 text: the G4 bullet, line 1498)
SEARCH:
```
A write that lands while the flush runs keeps its message and arms no timer; the flush commits it. After its own commit it makes up to `_FLUSH_DRAIN_PASSES` (5) more, one per batch that landed during the previous commit, and past that it warns and leaves the messages pending. Rejected: arming the timer
```
REPLACE:
```
With `auto_commit` on and one flush at a time, a write that lands while the flush runs keeps its message and arms no timer; the flush commits it. After its own commit it makes up to `_FLUSH_DRAIN_PASSES` (5) more, one per batch that landed during the previous commit, and past that it warns and leaves the messages pending. With `auto_commit` off `_schedule_commit` returns before it keeps a message, so such a write stays uncommitted until the next commit, as before (L11). If two flushes overlap, the first one's exit clears `_flushing`, and a write after that arms a timer whose commit can end after the second returns, as before (L3); production has one flush, from `shutdown()`. Rejected: arming the timer
```

**A3-07.** `DECISIONS.md` (M3 text: the residual line, line 1500)
SEARCH:
```
- *Residual.* Recorded limits L1 to L10 of the contract.
- *Reversal.* Revert the BF-960 commits.
```
REPLACE:
```
- *Residual.* Recorded limits L1 to L11 of the contract.
- *Reversal.* Revert the BF-960 commits.
```

### A3.4 Absence Verified (A3, on 028633ff)

CLAIM: no other live text carries the unscoped late-write promise or the old L3 text, outside the lines A3 changes
RUN:   P1 = git grep -n -i -E "keeps its message|keeps the message|keep its message|keep the message|message is kept|arms no timer|arm no timer|no timer is armed|arming the timer|keeps the pending|commits it before|committed before .flush|before it returns|before .flush\(\). returns|is in HEAD when|are in HEAD when|in HEAD when" 028633ff -- src tests PROGRESS.md DECISIONS.md prompts/bf-960-knowledge-flush-race.md
       P2 = git grep -n -i -E "late write|lands while|land while|landed during|landing|writes that land|write that lands|drain|_FLUSH_DRAIN_PASSES" 028633ff -- src/probos/knowledge/store.py tests/test_bf960_knowledge_flush_race.py prompts/bf-960-knowledge-flush-race.md ; the same on PROGRESS.md and DECISIONS.md, read inside the two BF-960 entries (PROGRESS.md 3-7, DECISIONS.md 1492-1501)
       P3 = git grep -n -i -E "finds nothing|second flush|two concurrent|overlapping|concurrent .?flush|one caller" over the same files and the same two entries
FOUND: store.py 1076-1077 and 1281-1282 (docstrings: A3-01, A3-02), 1301-1303 (comment: A3-03), 56-58 (the constant and its comment: an upper bound, true in both configurations), 1303 ("the take that finds nothing": the invariant of one flush), 1304, 1312 and 1316 (the loop and its warning: code); tests/test_bf960_knowledge_flush_race.py 422-527, incl. 506 (the names, docstrings and messages of T11 to T13 describe the scenario each sets up through `_store`, which is auto_commit=True: left, A3 changes no test); PROGRESS.md 5 and 6 (A3-04, A3-05); DECISIONS.md 1498 and 1500 (A3-06, A3-07); contract, live part: 4, 8, 36, 75, 839-840, 860, 862, 909, 910, 913, 993 (C3-01 to C3-12), and left: 35 (a bound), 91-93 (the tests' Covers cells), 896 and 899 (mutation rows), 914, 916 and 917 (L7, L9, L10: other limits), 985-986 (code structure, true in both configurations); contract, A2 section (1002 on): the record of A2, including :1011, :1305 and :1356-1357 (left on purpose); other work: src/probos/audio/tts/resident.py:158, src/probos/execution/workspace_result_store.py:744, tests/test_ad1173_repair_verification.py:1, tests/test_issue1419_failed_start_rollback.py:2145 ("before it returns"), DECISIONS.md:12794, store.py:576 and :596 (another class's drain), and 36 (P3) and 103 (P2) hits inside other entries of PROGRESS.md and DECISIONS.md, counted and not read (the trackers name BF-960 only at DECISIONS.md:1492 and :1501 and PROGRESS.md:3, by git grep -n -E "BF-960|#1767")
HOLDS: yes

CLAIM: KnowledgeStore.flush() has one production call site
RUN:   git grep -n -E "\.flush\(\)" 028633ff -- src ; git grep -n -P "\.flush\b(?!\()|[\x22\x27]flush[\x22\x27]" 028633ff -- src ; git grep -n -E "def flush\(" 028633ff -- src
FOUND: 12 hits for .flush(): audio/tts/resident.py:196, cognitive/sandbox.py:83, cognitive/self_mod.py:596, infrastructure/snapshot_manifest.py:258, knowledge/records_snapshot.py:274, knowledge/store.py:848 (temp_file.flush()), routers/system.py:409, security/file_access.py:990, startup/shutdown.py:2082 (await runtime._knowledge_store.flush()), substrate/telemetry.py:131 (another class), warm_boot.py:147 and :567; one reference by name, shutdown.py:218 (audit_log); defs: consultation/dispatch.py:217, knowledge/store.py:1268, security/audit.py:349, substrate/telemetry.py:119
HOLDS: yes, only shutdown.py:2082 calls the knowledge store's

CLAIM: that call runs once per runtime and never in a rollback
RUN:   git grep -n -E "_knowledge_store and not rollback|_shutdown_started" 028633ff -- src ; git grep -n -E "startup\.shutdown|from probos\.startup import shutdown" 028633ff -- src
FOUND: runtime.py:1575 (= False, the only reset); startup/shutdown.py:914 (the guard, `and not rollback`), :921 (= True; no await between :914 and :921), :2063 (`if runtime._knowledge_store and not rollback:`); the importers of shutdown(): runtime.py:4326 (stop(), rollback False) and startup/rollback.py:93 (rollback=True at :98)
HOLDS: yes

CLAIM: auto_commit is read once in store.py, and the only timer is armed behind that read
RUN:   git grep -n auto_commit 028633ff -- src ; git grep -n -E "call_later|_commit_timer *=" 028633ff -- src/probos/knowledge/store.py ; git grep -n _schedule_commit 028633ff -- src (hits outside store.py)
FOUND: store.py:1080 is the only read in store.py (records_store.py reads it for Ship's Records); defaults true: config_models/knowledge.py:285 (KnowledgeConfig) and :322 (RecordsConfig), config/system.yaml:769 (knowledge) and :777 (records); call_later at store.py:1094 only (:119, :1111, :1291 declare or clear the handle); no caller of _schedule_commit outside store.py
HOLDS: yes

CLAIM: the BF-960 test file never builds a store with auto_commit off, never calls store_cooldowns, and no test has a write in the two-flush window
RUN:   git grep -n -E "auto_commit|KnowledgeConfig\(|KnowledgeStore\(" 028633ff -- tests/test_bf960_knowledge_flush_race.py ; git grep -n -E "gather\(|create_task\(|flush\(\)" 028633ff -- tests/test_bf960_knowledge_flush_race.py ; git grep -c store_cooldowns 028633ff -- tests/test_bf960_knowledge_flush_race.py ; git grep -n -o -E "store\.store_[a-z_]+" 028633ff -- tests/test_bf960_knowledge_flush_race.py
FOUND: :64-65 only (`_store`, auto_commit=True); two concurrent flushes only at :230 (T3: store_trust_snapshot, then gather(store.flush(), store.flush()), no write after); :310 (T6) creates one flush task; T11 to T13 (:465, :490, :523) run one flush each; store_cooldowns: no match (exit 1); the store_* calls are store_trust_snapshot (14), store_routing_weights (4) and store_workflows (1)
HOLDS: yes (other test files do run stores with auto_commit=False, e.g. tests/test_knowledge_store.py:288; they are not BF-960 tests, and A3 adds none)

CLAIM: no test reads the text or the docstring of `_schedule_commit`, `flush()` or `store.py`, apart from `_git_run`'s source
RUN:   git grep -n -E "getsource|getdoc|__doc__" 028633ff -- tests (read for KnowledgeStore, _schedule_commit, flush, knowledge/store) ; git grep -n -E "knowledge[/\\]store\.py" 028633ff -- tests ; git grep -l -E "rglob\(.\*\.py.\)|glob\(.\*\*/\*\.py.\)" 028633ff -- tests
FOUND: tests/test_quality_hardening.py:50 (inspect.getsource(KnowledgeStore._git_run): untouched by A3); `store.py` is named only as a census key, with `KnowledgeStore._git_run`, in tests/fixtures/ad1346_effect_census.py:144, tests/fixtures/ad1346_file_write_census.py:170 and tests/test_bf892_spawn_env_guard.py:101; 62 test files glob .py files under a tree and 55 of them read text or use a regex (counted, not read): they stay with the broad gate
HOLDS: yes for the named readers

CLAIM: the 16 distinct anchor lines of section 9 (rows 1 to 20) occur once each in store.py, and no A3 pair touches one
RUN:   in memory (PowerShell): the stripped-line count of each anchor in `git show 028633ff:src/probos/knowledge/store.py`; the same count after A3-01 to A3-03 are applied; each line of those pairs' SEARCH and REPLACE compared with the 16
FOUND: 16 of 16 distinct anchors (20 rows) count 1 before and after A3-01 to A3-03 are applied in memory; 0 lines of those pairs' SEARCH or REPLACE equal an anchor; the pairs lie in old lines 1076-1078, 1281-1285 and 1301-1303; the text outside them is identical; no triple quote, backslash, tab, trailing space or line over 100 columns in those REPLACE blocks; `store.py` grows by 15 lines (`KnowledgeStore`'s srp-size row records triggers only, `lines` and `methods`, so no baseline row changes)
HOLDS: yes

CLAIM: every SEARCH of A3-01 to A3-07 and C3-01 to C3-12 occurs exactly once in its target as committed at 028633ff, and every REPLACE is ASCII-only
RUN:   in memory (PowerShell): this file parsed; the blob by `git show 028633ff:<path>`, LF; ordinal IndexOf count; any character above 127 in each REPLACE
FOUND: 19 of 19 SEARCH blocks occur once in their target as committed at 028633ff (C3-01 to C3-12 also once at their turn, applied in label order); `git grep -c -F` on the committed blobs finds each of the 12 single-line blocks on exactly 1 line, and the first line of A3-01, A3-02 and A3-03 on 1 line, while C3-05, C3-06, C3-07 and A3-07 are two-line blocks whose first line also occurs elsewhere (the REPLACE blocks of A2-10, A2-12 and A2-13 in the contract; DECISIONS.md:1394), so their second line makes each unique; 0 non-ASCII characters in any block (the file has none) and no no-op pair; applied in memory, PROGRESS.md changes lines 5 and 6 only and DECISIONS.md lines 1498 and 1500 only, and both keep their line counts (1547 and 12922); after C3-01 to C3-12 the contract's section 7.3 Fix, Changed, G4 and residual lines equal those tracker lines
HOLDS: yes

Not run in this consult (a read-only call: no python, no pytest): the new file, the loaded run, the architecture check, the ledger check, an AST comparison of `store.py` before and after, and a render of the two docstrings. GA3.1 (hunks and anchors) stands in for the AST comparison; GA3.3 is the rest.

### A3.5 Diff Reviewer: properties to verify (round 3: the delta of A3 on 028633ff only)

1. **No code change.** The A3 diff touches no code line: the `store.py` hunks lie inside the two docstrings and one comment (GA3.1), the module's AST with docstrings removed equals `028633ff`'s, the 16 anchor lines occur once, and no file under `tests/` differs. Round 2's properties 1 to 5 therefore stand.
2. **F1 as scoped.** With `auto_commit` off and an active flush on real git: no message is kept, none is pending and no timer is armed; a write after the flush's `add` stays uncommitted; `flush()` commits `Shutdown flush` only where `_git_available` was already true on the instance (A4: on ordinary startup it is `None` and `flush()` makes no git call). With it on, the T11 behaviour. Every sentence of L11 and of both docstrings is true.
3. **F2 as scoped.** Two concurrent flushes and a write in the window: with a long debounce the second flush's drain commits it and the timer finds nothing; with a zero-delay debounce the timer's task takes it, and the second flush can return with the write not in HEAD and that debounce commit pending. On the candidate and on the base.
4. **No unscoped carrier remains.** Rerun A3.4's P1 to P3 on the A3 head: every hit is scoped, a test's own scenario, a bound, another limit, or A2-section history.
5. **The embedded text equals the trackers.** C3-05 to C3-07 render to PROGRESS.md lines 5 and 6 and DECISIONS.md lines 1498 and 1500 (the contract's heading date aside), and the contract's L2, L3, L6 and L11 agree with the two docstrings (A3-01, A3-02).
6. **The production reach claim.** `shutdown.py:2082` is the only call site, `:2063` skips it in a rollback, and `:914` and `:921` make it once per runtime (A3.4).
7. **Housekeeping.** Every REPLACE is ASCII-only; the tracker pairs keep the line counts; the ledger and the architecture check are current.

**A4 (2026-11-07, the caller's clock), review round 3 (gpt-6.1-sol, NOT READY on one finding).** R3-F1, P3, ordinary configuration, introduced by A3's text, not by the code: L11 said that with `auto_commit` off `flush()` still commits what is on disk at its `add`; with it off nothing sets `_git_available`, so `flush()` makes no git call. Repaired by C4-01 (L11), C4-02 (property 2 above) and A4-01 (the `flush()` docstring: text only, no code line, no test, no mutation row; A3-02's block above stays as the record of what A3 applied). Round 4 reviews that delta only. Enumeration on `4ca28104`: `git grep -n -i -E "ensure_repo|git_available" 4ca28104 -- src` has hits in `store.py` only: `_git_available` is set at :115 (`None`) and :1041 (`_ensure_repo`), `_ensure_repo` is called at :1088 only (`_schedule_commit`, after the `auto_commit` guard at :1086-1087), and `_git_commit` guards on it at :1173 and returns when it is falsy; all lie before the `flush()` docstring, which A4-01 alone changes.
