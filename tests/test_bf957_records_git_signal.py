"""BF-957 (#1760): Ship's Records says when git fails, and probos doctor reports the records repository's state."""

from __future__ import annotations

import logging
import os
import re
import subprocess
import threading
import time
from pathlib import Path

import pytest
from pydantic import ValidationError

from probos.config import RecordsConfig, SystemConfig
from probos.doctor import iter_checks
from probos.doctor.protocol import CheckOutcome, DoctorContext
from probos.knowledge.records_store import RecordsStore

_LOGGER = "probos.knowledge.records_store"
_THRESHOLDS = {"git_lock_stale_minutes": 10.0, "git_uncommitted_warn_paths": 50, "git_last_commit_warn_hours": 24.0}


def _records(tmp_path: Path, **overrides: object) -> RecordsConfig:
    return RecordsConfig(repo_path=str(tmp_path / "ship-records"), **overrides)


async def _store(tmp_path: Path) -> RecordsStore:
    store = RecordsStore(_records(tmp_path))
    await store.initialize()
    return store


def _git(repo: Path, *args: str, **env: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, encoding="utf-8", errors="replace",
        env={**os.environ, **env},
    ).stdout


def _warnings(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [r.getMessage() for r in caplog.records if r.name == _LOGGER and r.levelno == logging.WARNING]


def _add_lock_warnings(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [m for m in _warnings(caplog) if "git add failed" in m and "index.lock" in m]


def _plant_lock(repo: Path, age_minutes: float = 120.0) -> Path:
    lock = repo / ".git" / "index.lock"
    lock.write_bytes(b"")
    stamp = time.time() - age_minutes * 60.0
    os.utime(lock, (stamp, stamp))
    return lock


def _check():
    check = next((c for c in iter_checks() if c.name == "records_git"), None)
    assert check is not None, "BF-957: the records_git doctor check is not registered"
    return check


def _ctx(tmp_path: Path, records: RecordsConfig | None, *, loaded: bool = True) -> DoctorContext:
    config = SystemConfig().model_copy(update={"records": records}) if loaded else None
    return DoctorContext(config=config, home_dir=tmp_path, data_dir=tmp_path, config_path=None)


def _fake_run(monkeypatch: pytest.MonkeyPatch, fake) -> None:
    monkeypatch.setattr("probos.knowledge.records_store.subprocess.run", fake)


def _broken_link(link: Path, target: Path) -> None:
    """A directory link whose target is then removed: a symlink, or a junction where Windows refuses a symlink."""
    target.mkdir()
    try:
        os.symlink(target, link, target_is_directory=True)
    except OSError:  # WinError 1314: no symlink privilege; a junction needs none
        import _winapi

        _winapi.CreateJunction(str(target), str(link))
    target.rmdir()
    assert os.path.lexists(link) and not link.exists(), "premise: the link remains and its target is gone"


@pytest.fixture(autouse=True)
def _hermetic_git(tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch) -> None:
    """BF-957 A4: no host git configuration or repository redirect reaches these tests' git, before any store starts.

    The store's git and the check's git inherit ``os.environ`` (``trusted_command_env``), as ``_git`` does. The
    store sets its own commit identity, so the empty configuration needs none.
    """
    home = tmp_path_factory.mktemp("bf957-git-home")
    empty = home / ".gitconfig"
    empty.write_bytes(b"")
    for name in (
        "GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_OBJECT_DIRECTORY", "GIT_ALTERNATE_OBJECT_DIRECTORIES",
        "GIT_COMMON_DIR", "GIT_CONFIG_PARAMETERS",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")  # no system scope (Git for Windows' own gitconfig included)
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(empty))  # git 2.32+: the global scope is this empty file
    monkeypatch.setenv("GIT_CONFIG_COUNT", "0")  # no command-line scope from the environment (the harness's fsmonitor)
    monkeypatch.setenv("HOME", str(home))  # an older git reads ~/.gitconfig and the XDG file from here
    monkeypatch.setenv("XDG_CONFIG_HOME", str(home))


# ---------------------------------------------------------------- the seam


@pytest.mark.asyncio
async def test_a_stale_lock_is_logged_once_and_reported_by_doctor_without_a_write(tmp_path, caplog):
    caplog.set_level(logging.WARNING, logger=_LOGGER)
    store = await _store(tmp_path)
    repo = store.repo_path
    lock = _plant_lock(repo)
    head = _git(repo, "rev-parse", "HEAD")

    await store.write_entry("bones", "reports/one.md", "First.", "first")
    await store.write_entry("bones", "reports/two.md", "Second.", "second")

    assert (repo / "reports" / "one.md").is_file() and (repo / "reports" / "two.md").is_file()
    assert len(_add_lock_warnings(caplog)) == 1, _warnings(caplog)
    assert _git(repo, "rev-parse", "HEAD") == head

    def snapshot() -> dict[str, tuple[int, int]]:
        return {p.name: (p.stat().st_size, p.stat().st_mtime_ns) for p in (repo / ".git").iterdir() if p.is_file()}

    before = snapshot()
    result = await _check().run(_ctx(tmp_path, _records(tmp_path)))

    assert result.outcome == CheckOutcome.FAIL
    assert "index.lock: present" in result.detail
    pending = re.search(r"uncommitted: (\d+) path", result.detail)
    assert pending is not None and int(pending.group(1)) >= 2
    assert "does not remove" in result.remediation
    assert lock.is_file()
    assert snapshot() == before


# ---------------------------------------------------------------- the signal


@pytest.mark.asyncio
async def test_a_failed_git_command_is_logged_once_per_distinct_error_and_returns_its_stdout(tmp_path, caplog):
    caplog.set_level(logging.WARNING, logger=_LOGGER)
    store = await _store(tmp_path)

    first = store._git_sync(("add", "missing-one.md"))
    again = store._git_sync(("add", "missing-one.md"))
    other = store._git_sync(("add", "missing-two.md"))

    assert (first, again, other) == ("", "", "")
    logged = _warnings(caplog)
    assert len(logged) == 2, logged
    assert "missing-one.md" in logged[0] and "missing-two.md" in logged[1]


@pytest.mark.asyncio
@pytest.mark.parametrize("between", ["a read succeeds", "an add succeeds"])
async def test_a_successful_add_or_commit_forgets_the_logged_errors_and_a_read_does_not(tmp_path, caplog, between):
    caplog.set_level(logging.WARNING, logger=_LOGGER)
    store = await _store(tmp_path)
    lock = _plant_lock(store.repo_path)
    await store.write_entry("bones", "reports/one.md", "First.", "first")
    assert len(_add_lock_warnings(caplog)) == 1

    if between == "a read succeeds":
        assert store._git_sync(("rev-list", "--count", "HEAD")).strip().isdigit()
        expected = 1
    else:
        lock.unlink()
        await store.write_entry("bones", "reports/two.md", "Second.", "second")
        _plant_lock(store.repo_path)
        expected = 2
    await store.write_entry("bones", "reports/three.md", "Third.", "third")

    assert len(_add_lock_warnings(caplog)) == expected


def test_the_remembered_errors_are_bounded_and_the_oldest_is_dropped(tmp_path, caplog, monkeypatch):
    caplog.set_level(logging.WARNING, logger=_LOGGER)
    store = RecordsStore(_records(tmp_path))
    error = {"text": ""}
    _fake_run(monkeypatch, lambda argv, **kw: subprocess.CompletedProcess(argv, 1, stdout="", stderr=error["text"]))

    def fail(i: int) -> None:
        error["text"] = f"fatal: error {i}\n"
        store._git_sync(("status",))

    for i in range(33):
        fail(i)
    assert len(_warnings(caplog)) == 33
    fail(0)  # dropped as the oldest when the 33rd arrived
    assert len(_warnings(caplog)) == 34
    fail(32)  # still remembered
    assert len(_warnings(caplog)) == 34


def test_a_timed_out_git_command_is_logged_once_and_still_raises(tmp_path, caplog, monkeypatch):
    caplog.set_level(logging.WARNING, logger=_LOGGER)
    store = RecordsStore(_records(tmp_path))

    def timed_out(argv, **kwargs):
        raise subprocess.TimeoutExpired(argv, kwargs["timeout"])

    _fake_run(monkeypatch, timed_out)
    for _ in range(2):
        with pytest.raises(subprocess.TimeoutExpired):
            store._git_sync(("add", "reports/one.md"))

    logged = _warnings(caplog)
    assert len(logged) == 1, logged
    assert "did not finish" in logged[0] and "lock" in logged[0]


@pytest.mark.asyncio
async def test_a_commit_that_raises_is_logged_once_at_warning_and_does_not_raise(tmp_path, caplog, monkeypatch):
    caplog.set_level(logging.WARNING, logger=_LOGGER)
    store = RecordsStore(_records(tmp_path))

    async def broken_git(*args: str) -> str:
        raise FileNotFoundError("git")

    monkeypatch.setattr(store, "_git", broken_git)
    await store._commit("first")
    await store._commit("second")

    logged = _warnings(caplog)
    assert len(logged) == 1, logged
    assert "FileNotFoundError" in logged[0]
    assert "not known" in logged[0] and "did not run" not in logged[0], logged[0]  # A4: no claim git did not run


def test_one_git_child_runs_at_a_time_per_store(tmp_path, monkeypatch):
    store = RecordsStore(_records(tmp_path))
    counts = {"inside": 0, "peak": 0}
    guard = threading.Lock()
    start = threading.Barrier(2)

    def slow(argv, **kwargs):
        with guard:
            counts["inside"] += 1
            counts["peak"] = max(counts["peak"], counts["inside"])
        time.sleep(0.3)
        with guard:
            counts["inside"] -= 1
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

    _fake_run(monkeypatch, slow)

    def call() -> None:
        start.wait()
        store._git_sync(("add", "x.md"))

    threads = [threading.Thread(target=call) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert counts["peak"] == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("untracked", [False, True], ids=["nothing to commit", "nothing added to commit"])
async def test_a_commit_with_nothing_staged_is_not_an_error(tmp_path, caplog, untracked):
    caplog.set_level(logging.WARNING, logger=_LOGGER)
    store = await _store(tmp_path)
    if untracked:
        (store.repo_path / "reports" / "loose.md").write_text("loose", encoding="utf-8")

    out = store._git_sync(("commit", "-m", "nothing"))

    assert ("nothing added to commit" if untracked else "nothing to commit") in out
    assert _warnings(caplog) == []


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["success", "failure", "git missing"])
async def test_the_return_value_and_raising_are_unchanged(tmp_path, monkeypatch, case):
    store = await _store(tmp_path)
    if case == "success":
        assert store._git_sync(("rev-list", "--count", "HEAD")).strip() == "1"
    elif case == "failure":
        assert store._git_sync(("rev-parse", "--verify", "no-such-ref")) == ""
    else:
        def missing(argv, **kwargs):
            raise FileNotFoundError(argv[0])

        _fake_run(monkeypatch, missing)
        with pytest.raises(FileNotFoundError):
            store._git_sync(("status",))


@pytest.mark.asyncio
async def test_a_commit_that_times_out_is_logged_once_and_not_called_unrun(tmp_path, caplog, monkeypatch):
    caplog.set_level(logging.WARNING, logger=_LOGGER)
    store = RecordsStore(_records(tmp_path))

    def timed_out(argv, **kwargs):
        raise subprocess.TimeoutExpired(argv, kwargs["timeout"])

    _fake_run(monkeypatch, timed_out)
    await store._commit("first")
    await store._commit("second")

    logged = _warnings(caplog)
    assert len(logged) == 1, logged
    assert "did not finish" in logged[0] and "not known" in logged[0]
    assert "did not run" not in logged[0]


@pytest.mark.asyncio
async def test_a_failure_is_logged_with_git_s_first_line_only(tmp_path, caplog, monkeypatch):
    monkeypatch.setenv("LC_ALL", "C")  # git's English text, which the premise names
    caplog.set_level(logging.WARNING, logger=_LOGGER)
    store = await _store(tmp_path)
    repo = store.repo_path
    _plant_lock(repo)
    (repo / "reports" / "one.md").write_text("First.", encoding="utf-8")
    plain = subprocess.run(
        ["git", "-C", str(repo), "add", "reports/one.md"], capture_output=True, encoding="utf-8", errors="replace",
    )
    assert plain.returncode != 0 and "remove the file manually" in plain.stderr, (
        f"premise: this git advises removing the lock; report this, do not skip: {plain.stderr!r}"
    )

    await store.write_entry("bones", "reports/one.md", "First.", "first")

    logged = _add_lock_warnings(caplog)
    assert len(logged) == 1, _warnings(caplog)
    assert "remove the file" not in logged[0] and "\n" not in logged[0], logged[0]


@pytest.mark.parametrize("case", ["success", "failure", "timeout"])
def test_the_warning_memory_changes_under_the_git_lock_and_is_logged_after_its_release(
    tmp_path, caplog, monkeypatch, case
):
    caplog.set_level(logging.WARNING, logger=_LOGGER)
    store = RecordsStore(_records(tmp_path))
    held: list[tuple[str, bool]] = []

    class Memory(dict):  # the store's warning memory, observed where it changes
        def __setitem__(self, key: object, value: object) -> None:
            held.append(("remember", store._git_lock.locked()))
            super().__setitem__(key, value)

        def clear(self) -> None:
            held.append(("forget", store._git_lock.locked()))
            super().clear()

    class Emitted(logging.Handler):  # where a vessel's log handler runs; it may read git through the store
        def emit(self, record: logging.LogRecord) -> None:
            held.append(("log", store._git_lock.locked()))

    store._git_warned = Memory()
    handler = Emitted(logging.WARNING)
    log = logging.getLogger(_LOGGER)
    log.addHandler(handler)

    def fake(argv, **kwargs):
        if case == "timeout":
            raise subprocess.TimeoutExpired(argv, kwargs["timeout"])
        return subprocess.CompletedProcess(argv, 0 if case == "success" else 1, stdout="", stderr="fatal: bf957\n")

    _fake_run(monkeypatch, fake)
    try:
        if case == "timeout":
            with pytest.raises(subprocess.TimeoutExpired):
                store._git_sync(("add", "x.md"))
        else:
            store._git_sync(("add", "x.md"))
    finally:
        log.removeHandler(handler)

    # The memory changes while the lock is held, so a later child's warning is never cleared by an earlier
    # child's success; the record is emitted after the release, so a handler that reads git cannot deadlock.
    assert held == ([("forget", True)] if case == "success" else [("remember", True), ("log", False)])


@pytest.mark.asyncio
async def test_history_is_read_as_utf8_whatever_the_host_locale(tmp_path, monkeypatch):
    store = await _store(tmp_path)
    await store.write_entry("bones", "reports/one.md", "First.", "\u0401 first")
    real_run = subprocess.run

    def cp1252_host(argv, **kwargs):
        if "encoding" not in kwargs:  # decoding left to the locale: decode as a cp1252 host does (0x81 is undefined)
            kwargs["encoding"] = "cp1252"
        return real_run(argv, **kwargs)

    _fake_run(monkeypatch, cp1252_host)
    history = await store.get_history("reports/one.md")

    # The base lost this row on a cp1252 host (git exited 0; the reader returned None) and misread the em dash.
    assert [row["message"] for row in history] == ["[records] \u0401 first \u2014 by bones"], history


# ---------------------------------------------------------------- the doctor check


def test_the_doctor_check_is_registered_once_after_disk():
    names = [c.name for c in iter_checks()]
    assert names.count("records_git") == 1
    assert names[names.index("disk") + 1] == "records_git"


@pytest.mark.asyncio
@pytest.mark.parametrize(("age", "outcome"), [(9.0, CheckOutcome.OK), (11.0, CheckOutcome.FAIL)])
async def test_a_lock_is_reported_only_from_its_threshold(tmp_path, age, outcome):
    store = await _store(tmp_path)
    _plant_lock(store.repo_path, age_minutes=age)

    result = await _check().run(_ctx(tmp_path, _records(tmp_path, git_lock_stale_minutes=10.0)))

    assert result.outcome == outcome
    assert "index.lock: present" in result.detail


@pytest.mark.asyncio
@pytest.mark.parametrize(("bound", "outcome"), [(3, CheckOutcome.OK), (2, CheckOutcome.WARN)])
async def test_uncommitted_paths_warn_only_over_the_bound(tmp_path, bound, outcome):
    store = await _store(tmp_path)
    for i in range(3):
        (store.repo_path / "reports" / f"loose-{i}.md").write_text("x", encoding="utf-8")

    result = await _check().run(_ctx(tmp_path, _records(tmp_path, git_uncommitted_warn_paths=bound)))

    assert result.outcome == outcome
    assert "uncommitted: 3 path(s)" in result.detail


@pytest.mark.asyncio
@pytest.mark.parametrize(("loose", "outcome"), [(False, CheckOutcome.OK), (True, CheckOutcome.WARN)])
async def test_an_old_last_commit_warns_only_with_uncommitted_paths(tmp_path, loose, outcome):
    store = await _store(tmp_path)
    old = "2001-01-01T00:00:00+00:00"
    _git(store.repo_path, "commit", "--allow-empty", "-m", "old", GIT_COMMITTER_DATE=old, GIT_AUTHOR_DATE=old)
    if loose:
        (store.repo_path / "reports" / "loose.md").write_text("x", encoding="utf-8")

    result = await _check().run(_ctx(tmp_path, _records(tmp_path)))

    assert result.outcome == outcome
    assert "last commit:" in result.detail


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["config not loaded", "records disabled", "auto_commit off"])
async def test_the_check_skips_without_config_records_or_auto_commit(tmp_path, case):
    store = await _store(tmp_path)
    _plant_lock(store.repo_path)
    check = _check()

    if case == "config not loaded":
        result, expected = await check.run(_ctx(tmp_path, None, loaded=False)), CheckOutcome.WARN
    elif case == "records disabled":
        result, expected = await check.run(_ctx(tmp_path, _records(tmp_path, enabled=False))), CheckOutcome.OK
    else:
        result, expected = await check.run(_ctx(tmp_path, _records(tmp_path, auto_commit=False))), CheckOutcome.OK

    assert result.outcome == expected
    assert "index.lock" not in result.detail


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["no directory", "a file", "a broken link", "not a repository", "no commit yet"])
async def test_a_missing_directory_or_repository_or_commit_is_reported(tmp_path, case):
    repo = tmp_path / "ship-records"
    if case == "a file":
        repo.write_text("not a directory", encoding="utf-8")
    elif case == "a broken link":
        _broken_link(repo, tmp_path / "removed-target")
    elif case != "no directory":
        repo.mkdir()
    if case in ("a file", "a broken link"):
        with pytest.raises(FileExistsError):  # premise: startup refuses this path, so OK would be false
            await RecordsStore(_records(tmp_path)).initialize()
    if case == "no commit yet":
        _git(repo, "init")

    result = await _check().run(_ctx(tmp_path, _records(tmp_path)))

    expected = {
        "no directory": CheckOutcome.OK,
        "a file": CheckOutcome.FAIL,
        "a broken link": CheckOutcome.FAIL,
        "not a repository": CheckOutcome.WARN,
        "no commit yet": CheckOutcome.WARN,
    }
    assert result.outcome == expected[case]
    if case in ("a file", "a broken link"):
        assert "not a directory" in result.message
    if case == "a file":
        assert repo.read_text(encoding="utf-8") == "not a directory"
    if case == "a broken link":
        assert os.path.lexists(repo) and not repo.exists()  # nothing was created behind the link
    if case == "no commit yet":
        assert "last commit: not read" in result.detail


@pytest.mark.asyncio
async def test_without_git_the_lock_is_still_reported(tmp_path, monkeypatch):
    store = await _store(tmp_path)
    _plant_lock(store.repo_path)
    check = _check()
    monkeypatch.setattr("probos.doctor.checks.records_git_check.shutil.which", lambda name: None)

    result = await check.run(_ctx(tmp_path, _records(tmp_path)))

    assert result.outcome == CheckOutcome.FAIL
    assert "git: not found" in result.detail


@pytest.mark.asyncio
async def test_the_check_reads_git_with_optional_locks_off(tmp_path, monkeypatch):
    monkeypatch.setenv("GIT_OPTIONAL_LOCKS", "1")  # an ambient value the check must override, on any host
    await _store(tmp_path)
    check = _check()
    seen: list[str | None] = []
    real_run = subprocess.run

    def spy(argv, **kwargs):
        seen.append((kwargs.get("env") or {}).get("GIT_OPTIONAL_LOCKS"))
        return real_run(argv, **kwargs)

    monkeypatch.setattr("probos.doctor.checks.records_git_check.subprocess.run", spy)
    result = await check.run(_ctx(tmp_path, _records(tmp_path)))

    assert result.outcome == CheckOutcome.OK
    assert seen == ["0", "0"]


@pytest.mark.asyncio
async def test_the_check_runs_no_fsmonitor_and_writes_nothing_in_the_repository(tmp_path, monkeypatch):
    store = await _store(tmp_path)
    repo = store.repo_path
    marker = repo / ".git" / "bf957-fsmonitor-ran"
    hook = tmp_path / "fsmonitor-bf957"
    hook.write_bytes(f'#!/bin/sh\necho ran >> "{marker.as_posix()}"\n'.encode("utf-8"))
    os.chmod(hook, 0o755)
    _git(repo, "config", "core.fsmonitor", hook.as_posix())
    # _hermetic_git switched off the harness's command-line core.fsmonitor=false (GIT_CONFIG_COUNT) and the host's
    # git configuration before the store initialised, so neither can hide a missing option or stop the first commit.
    assert _git(repo, "rev-list", "--count", "HEAD").strip() == "1", "premise: initialisation committed"
    check = _check()

    # premise: with optional locks off, as the check's reads had before A3, plain git status runs the fsmonitor
    plain = subprocess.run(
        ["git", "-C", str(repo), "status", "--porcelain"],
        env={**os.environ, "GIT_OPTIONAL_LOCKS": "0"}, capture_output=True, encoding="utf-8", errors="replace",
    )
    assert plain.returncode == 0, plain.stderr
    assert marker.is_file(), "premise: this git runs a configured fsmonitor; report this, do not skip"
    marker.unlink()

    def snapshot() -> dict[str, tuple[int, int]]:
        return {
            p.relative_to(repo).as_posix(): (p.stat().st_size, p.stat().st_mtime_ns)
            for p in repo.rglob("*") if p.is_file()
        }

    before = snapshot()
    result = await check.run(_ctx(tmp_path, _records(tmp_path)))

    assert result.outcome == CheckOutcome.OK, result.detail
    assert not marker.exists(), "the check's git ran the repository's fsmonitor"
    assert snapshot() == before


def test_the_thresholds_are_bounded_config_fields_with_defaults():
    fields = RecordsConfig.model_fields
    assert {name: fields[name].default for name in _THRESHOLDS if name in fields} == _THRESHOLDS
    for name in _THRESHOLDS:
        assert fields[name].description
        with pytest.raises(ValidationError):
            RecordsConfig(**{name: 0})
