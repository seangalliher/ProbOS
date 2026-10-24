# BF-919: test boots never open the operator's Ship's Archive, and the suite downloads no embedding model into the home directory

**Drafted by:** `claude-architect` (Claude Code, Opus 5.5), 2026-10-23

**Status:** build-ready after the orchestrator's verification by tool on the then-current `main`. One issue (#1632), two milestones (M1 is the archive, M2 is the model cache), one gate and one PR. **Tier HIGH** (data integrity: test boots opened and migrated the operator's archive). Never lower the tier without the Captain. **Base:** `origin/main` `26bec26d` (BF-914 merged). BF-918 (#1626) is in review and edits none of these files.

**Tests:** M1 adds `tests/fixtures/archive_isolation.py` and `tests/test_bf919_archive_isolation.py` (7 tests). M2 adds `tests/fixtures/model_download_guard.py` and `tests/test_bf919_model_download_guard.py` (5 tests). Both milestones edit `tests/conftest.py`. No production file changes.

**Line endings:** working copies are CRLF (`core.autocrlf=true`). The SEARCH blocks are LF; match and write with the file's own endings. New files are written LF.

---

## 0. Premise: what is present on this tree

| Clause | State | Evidence |
|---|---|---|
| `ArchiveConfig.enabled` is True and `db_path` is `""` | present, unmoved | `config_models/knowledge.py:358-362` |
| An empty `db_path` resolves under `Path.home()` (Windows `AppData\Local\ProbOS\archive`); `XDG_DATA_HOME` is read only on Linux | present, unmoved | `config.py:2631-2655` |
| The boot creates the parent directory and runs `initialize`; a failure is logged and the boot continues | present (the issue cited `:681-689`; the block is `:669-697`) | `startup/cognitive_services.py:671-697` |
| `initialize` migrates (`PRAGMA user_version`, additive columns, commit) | present, unmoved | `knowledge/archive_store.py:326-359` |
| Other callers of the resolver: the reset and erase CLI, and the backup roots at boot | present | `__main__.py:3205-3212`, `:3223-3227`; `infrastructure/backup_inventory.py:229-240`; `startup/finalize.py:3650` |
| The suite isolates `data_dir` (BF-883, AD-682) and the keyring (BF-908), not the archive | present | `tests/conftest.py:7-20`, `:52-58`, `:66-89` |
| `lifecycle_config` redirects the archive for its own users only | present | `tests/fixtures/runtime_lifecycle.py:74-90` |
| Only CI forces `PROBOS_EMBEDDINGS=local` | present | `.github/workflows/ci.yml:40`, `:131`; `tests/test_ci_shards.py:1581` |
| Chroma's ONNX download directory is a class attribute derived from `Path.home()` | present | `chromadb/utils/embedding_functions/onnx_mini_lm_l6_v2.py:39`, `:293-317` |
| Live: `%LOCALAPPDATA%\ProbOS\archive\` holds `archive.db` | listed read-only 2026-10-23 | Glob; row counts and `user_version` taken from #1632 (not re-read, §19) |

## 1. Problem

`ArchiveConfig.db_path` defaults to `""`, and `resolve_archive_db_path` turns that into a platform default under the home directory, outside `data_dir`. Every default-config runtime boot in the suite therefore opened, and migrated forward, the operator's own Ship's Archive (`cognitive_services.py:681-689`, `archive_store.py:326-359`).

The same resolver feeds the reset and erase CLI (`__main__.py:3209`, `:3227`) and the backup roots (`backup_inventory.py:240`, wired at boot by `finalize.py:3650`). So a test that ran a restore under the default configuration would have written into the operator's archive directory.

Separately, a boot on a machine without the sentence-transformers model cached falls through to Chroma's ONNX function. That function downloads 83 MB into `~/.cache/chroma` whatever `HF_HUB_OFFLINE` says (`embeddings.py:197-211`; #1632, comment R2-1).

## 2. Decisions

**D1: the archive guard (in the envelope).** Ranked:
1. **Chosen:** a session-level redirect of `probos.config.resolve_archive_db_path`, plus a refusal at `ArchiveStore` construction that is recorded and fails the test.
2. A production `PROBOS_ARCHIVE_DB_PATH` seam. Deferred: it would add a facade environment-read row (`test_ad1270e1_config_facade.py:567`, `:1598`), and today's booting child processes redirect their own home.
3. Monkeypatching only the resolver per test. Insufficient alone.
4. Redirecting HOME and the related variables. Rejected: the Hugging Face cache, the git identity, Playwright and Chroma's import-time path all move.
5. A default `ArchiveConfig` under tmp. Rejected: it changes default goldens.
6. A guard in production code. Rejected.

**D2: the model cache (in the envelope; it revises R2-1).** When the model is absent, Chroma's public `DOWNLOAD_PATH` is pointed beneath a file. `PROBOS_EMBEDDINGS` is not set, so real-embedding coverage stays in the local gate (`test-suite-optimization-plan.md:267`, `:298`).

**D3: where the tripwire lives.** Refusal at construction; failure at the per-test teardown and at the session-fixture teardown. Rejected: `pytest_sessionfinish`, which xdist does not report reliably, and a spy on `initialize`, which fires too late and reads a private attribute.

**D4: no environment change.** No `os.environ` write and no `setdefault`. So `check_config_profiles.py`, the facade's environment differential, `test_ci_shards.py` and `run_test_gate.py` are untouched.

## 3. Solution overview

- **M1.**
  - `tests/fixtures/archive_isolation.py` holds `ArchiveIsolation` and the context manager `archive_isolation`.
  - Conftest enters it once per session per worker, rooted at `<basetemp>/probos_archive_<worker>`, which sits beside the AD-682 data directory and never inside it.
  - An autouse function fixture, `isolated_archive_path`, gives each test its own path (`t<n>/archive.db`, created only if the test opens the archive) and fails the test when a refusal happened during it.
  - Allowed roots: the worker's basetemp and `tempfile.gettempdir()`, never the operator's default. `:memory:` is allowed.
- **M2.**
  - `tests/fixtures/model_download_guard.py`: when `<DOWNLOAD_PATH>/onnx/model.onnx` is absent, `DOWNLOAD_PATH` is pointed beneath a file in the worker's basetemp.
  - Conftest enters it once per session per worker. Both are restored on exit.

## 4. Consumers of every value this changes

| Value | Consumers | Effect |
|---|---|---|
| `probos.config.resolve_archive_db_path`, inside the suite | boot (`cognitive_services.py:673`, `:681`), reset and erase (`__main__.py:3205`, `:3223`), backup roots (`backup_inventory.py:229`, `:240`); `test_ad1347_s1_wiring.py:57` replaces it with its own spy for its tests, and monkeypatch restores it | An empty `db_path` resolves to the current test's path; a set `db_path` resolves unchanged |
| `ArchiveStore.__init__`, inside the suite | every construction (6 test sites, all under tmp_path; the boot; the CLI) | A path outside the temporary roots raises before any I/O and is recorded |
| `ONNXMiniLM_L6_V2.DOWNLOAD_PATH`, inside the suite | `ONNXMiniLM_L6_V2` via `DefaultEmbeddingFunction` (`embeddings.py:199-201`); `test_ad1347_s1_wiring.py:76` overrides it for its own tests | Unchanged when the model is on disk; otherwise the download step raises `OSError`, which `embeddings.py:205-211` catches |
| New fixtures `_bf919_isolated_archive`, `isolated_archive_path`, `_bf919_no_model_download` | autouse; `test_ad682_fixture_isolation.py:25-30` finds the conftest plugin by attribute (no collision) | none |

## 5. Tests

**Focused gate** (each milestone, run by the Builder; the main session runs it once on the frozen candidate):

```
d:/ProbOS/.venv/Scripts/python.exe -m pytest -q -n 0 tests/test_bf919_archive_isolation.py tests/test_bf919_model_download_guard.py tests/test_ad682_fixture_isolation.py tests/test_ad1347_s1_wiring.py tests/test_ad1346_admission_service_boot.py tests/test_ad1265_backup_coverage.py tests/test_ad1341_s1_reset_and_erase.py tests/test_ad1341_s1_archive_store.py tests/test_ad1341_s1_promotion.py tests/test_ad524_ships_archive.py tests/test_ad1340_s1_archive_store.py tests/test_ad1340_s2a_archive_lookup.py tests/test_ad1340_s2b_archive_reads.py tests/test_ad1340_s2b_eviction_locking.py tests/test_ad1340_s1_restore_reset.py tests/test_issue1452_stop_leftovers.py tests/test_reset_integration.py tests/test_bf657_local_embedding_fallback.py tests/test_embeddings.py tests/test_ad584_recall_qa_fix.py tests/test_ad1185_config_profiles.py tests/test_ad1270e1_config_facade.py tests/test_bf245_nats_xdist_isolation.py tests/test_abortive_self_pipe.py tests/test_timeout_timer_release.py tests/test_ad1270f_codebase_index_memo.py tests/test_conftest_attachment_store_cache_isolation.py tests/test_issue1419_failed_start_rollback.py
```

After that, the two new files once more at `-n 4`, which exercises the per-worker roots. Also run `scripts/phantom-api-precheck.ps1 prompts/bf-919-test-boots-isolate-archive-and-embedding-cache.md`.

**New, M1:** `tests/test_bf919_archive_isolation.py`. On today's tree every test fails at import (the fixture module does not exist).

| Id | Test | Proves |
|---|---|---|
| A1 | `test_a1_a_default_config_boot_opens_this_tests_archive_and_leaves_an_empty_home_empty` | **The seam.** Premises: the home is redirected and empty; the configuration is the default; the original resolver points into this home; the test's path does not exist yet. A real boot then creates this test's archive at `user_version` 1, and the home stays empty. |
| A2 | `test_a2_an_archive_outside_the_temporary_roots_is_refused_and_recorded_before_anything_is_created` | Refusal of a path outside the roots and of the operator's default; each is recorded; nothing is created; a temporary path is accepted |
| A3 | `test_a3_the_rule_admits_the_temporary_roots_and_memory_and_never_the_operators_default` | The rule itself, including an operator default placed under an allowed root; `resolve` for an empty and a set `db_path` |
| A4 | `test_a4_a_refusal_during_a_test_fails_that_test_at_teardown` | The per-test fixture, through `__wrapped__`: it fails, and the next test starts from the session path |
| A4b | `test_a4b_a_refusal_outside_any_test_fails_the_session_and_the_install_is_undone` | The session fixture, through `__wrapped__`: it fails, and both patches are restored |
| A5 | `test_a5_an_empty_db_path_resolves_to_this_tests_own_path_and_a_set_one_as_given` | The redirect, the backup roots, a distinct path per test, and nothing created by resolving |
| A6 | `test_a6_each_worker_has_its_own_archive_root_beside_its_data_directory` | Per-worker roots; the archive root is not inside, and does not contain, `PROBOS_DATA_DIR` |

**New, M2:** `tests/test_bf919_model_download_guard.py`. The tests run in file order; C1 and C2 precede C3.

| Id | Test | Proves |
|---|---|---|
| C1 | `test_c1_with_no_model_on_disk_the_download_directory_is_beneath_the_sinkhole` | The path rule when the model is absent; deciding creates nothing |
| C2 | `test_c2_with_the_model_on_disk_chromas_own_directory_is_kept` | A cache on disk is kept |
| C3 | `test_c3_with_no_model_on_disk_a_default_embedding_falls_back_and_creates_nothing` | **The seam.** sentence-transformers unavailable, the toggle unset and every proxy pointed at a closed port: `get_embedding_function` returns None, and nothing is created where Chroma would download or beside the sinkhole |
| C4 | `test_c4_the_guard_writes_its_sinkhole_points_chroma_beneath_it_and_restores_chromas_directory` | Install, the sinkhole file, and restore |
| C5 | `test_c5_conftest_installed_the_guard_for_this_worker` | Conftest's install is live: the model is on disk, or the path lies under the sinkhole |

**Hard stop:** if A1 fails on the candidate only because the home holds an entry other than the archive, that is a second write into the home. Report it; do not weaken the assertion.

## 6. Milestones

| Milestone | Sections | Commit |
|---|---|---|
| M1 (archive) | §7.1 to §7.3 | `BF-919: test boots resolve the Ship's Archive under the worker's temporary root and refuse any other` |
| M2 (model cache) | §7.4 to §7.6, and §8 | `BF-919: the test suite downloads no embedding model into the home directory` |

**M1 opens at §7.1 and M2 opens at §7.4.** §7.6 anchors on text that §7.3 creates, so M1 is built first.

## 7. The contract

### 7.1 New file: `tests/fixtures/archive_isolation.py` (M1)

```python
"""BF-919 (#1632): no test opens the operator's Ship's Archive.

``ArchiveConfig.db_path`` defaults to ``""``, and ``resolve_archive_db_path`` turns that into a platform default
under the home directory (on Windows ``AppData\\Local\\ProbOS\\archive\\archive.db``). That is outside ``data_dir``,
so BF-883's data directory isolation never covered it, and every default-config boot in the suite opened and
migrated the operator's own archive.

``tests/conftest.py`` enters ``archive_isolation`` once per session in every xdist worker:

* the redirect: ``probos.config.resolve_archive_db_path`` answers an empty ``db_path`` with the current test's own
  path under the worker's archive root, and resolves a set ``db_path`` exactly as before. Every production caller
  imports the resolver inside the calling function, so replacing the module attribute is what they call;
* the refusal: ``ArchiveStore`` refuses, before it opens anything, a file that is the operator's own default or is
  not under the suite's temporary roots. A boot logs that error and continues without the archive, so each refusal
  is also recorded, and the test that caused it (or the session, for one outside any test) fails.

A caller that bound the resolver at import would bypass the redirect; the refusal still stops it. Neither reaches a
child process: the suites that start ``probos`` children give them their own home directory.
"""

from __future__ import annotations

import functools
import itertools
import os
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import probos.config as probos_config
from probos.config import ArchiveConfig
from probos.knowledge.archive_store import ArchiveStore

ARCHIVE_FILE = "archive.db"
IN_MEMORY = ":memory:"


def comparable(path: str | os.PathLike[str]) -> Path:
    """One form for comparing paths: absolute, links resolved, the platform's case rule applied."""
    return Path(os.path.normcase(str(Path(path).resolve())))


def archive_root_for(tmp_path_factory: Any, worker_id: str) -> Path:
    """The worker's own archive root, beside its AD-682 data directory and never inside it."""
    return tmp_path_factory.mktemp(f"probos_archive_{worker_id}", numbered=False)


class ArchiveIsolation:
    """The redirect of the archive's default path and the refusal of any archive file outside the temporary roots."""

    def __init__(
        self, root: Path, allowed_roots: list[Path], original_resolver: Callable[[ArchiveConfig], Path],
    ) -> None:
        self.root = root
        self.original_resolver = original_resolver
        self.operator_default = comparable(original_resolver(ArchiveConfig()))
        self.allowed_roots = [comparable(allowed) for allowed in allowed_roots]
        self.session_path = root / "session" / ARCHIVE_FILE
        self.current = self.session_path
        self.refused: list[str] = []
        self._reported = 0
        self._numbers = itertools.count(1)

    def resolve(self, archive: ArchiveConfig) -> Path:
        """The redirect: a set ``db_path`` as before, an empty one the current test's own path."""
        if archive.db_path:
            return self.original_resolver(archive)
        return self.current

    def allowed(self, db_path: str) -> bool:
        """True for ``:memory:`` and for a file under a temporary root that is not the operator's default."""
        if db_path == IN_MEMORY:
            return True
        candidate = comparable(db_path)
        if candidate == self.operator_default:
            return False
        return any(candidate.is_relative_to(allowed) for allowed in self.allowed_roots)

    def next_test_path(self) -> Path:
        """A fresh path for the next test; nothing creates it unless that test opens the archive."""
        return self.root / f"t{next(self._numbers)}" / ARCHIVE_FILE

    def unreported(self) -> list[str]:
        """The refusals not reported yet; this call reports them."""
        new = self.refused[self._reported:]
        self._reported = len(self.refused)
        return new

    def refusing(self, original_init: Callable[..., None]) -> Callable[..., None]:
        """``ArchiveStore.__init__`` that refuses, and records, a file outside the temporary roots."""

        @functools.wraps(original_init)
        def _refusing_init(store: Any, db_path: str, *args: Any, **kwargs: Any) -> None:
            if not self.allowed(str(db_path)):
                self.refused.append(str(db_path))
                raise RuntimeError(
                    f"BF-919: a test opened a Ship's Archive outside the suite's temporary roots: {db_path}"
                )
            original_init(store, db_path, *args, **kwargs)

        return _refusing_init


@contextmanager
def archive_isolation(root: Path, allowed_roots: list[Path]) -> Iterator[ArchiveIsolation]:
    """Install the redirect and the refusal; restore both on exit."""
    original_resolver = probos_config.resolve_archive_db_path
    original_init = ArchiveStore.__init__
    isolation = ArchiveIsolation(root, allowed_roots, original_resolver)
    probos_config.resolve_archive_db_path = isolation.resolve
    ArchiveStore.__init__ = isolation.refusing(original_init)  # type: ignore[method-assign]
    try:
        yield isolation
    finally:
        ArchiveStore.__init__ = original_init  # type: ignore[method-assign]
        probos_config.resolve_archive_db_path = original_resolver
```

### 7.2 `tests/conftest.py` (M1): the session root, the redirect and refusal, and each test's own path

The SEARCH block occurs once (`install_codebase_index_memo` appears only at lines 136 and 138). The fixtures are inserted after `_ad1270f_codebase_index_memo`.

SEARCH:
```python
    from tests.fixtures.codebase_index_memo import install_codebase_index_memo

    with install_codebase_index_memo():
        yield
```
REPLACE:
```python
    from tests.fixtures.codebase_index_memo import install_codebase_index_memo

    with install_codebase_index_memo():
        yield


@pytest.fixture(scope="session", autouse=True)
def _bf919_isolated_archive(tmp_path_factory, worker_id):
    """BF-919 (#1632): no test opens the operator's Ship's Archive, per xdist worker.

    ``archive.db_path`` defaults to ``""``, which resolves to the operator's archive under the home directory,
    outside the data directory AD-682 and BF-883 isolate. For the whole session an empty ``db_path`` resolves under
    this worker's own archive root, and ``ArchiveStore`` refuses any file outside the suite's temporary roots before
    it opens it -- see ``tests/fixtures/archive_isolation.py``. A refusal outside any test fails the session here.
    """
    from tests.fixtures.archive_isolation import archive_isolation, archive_root_for

    root = archive_root_for(tmp_path_factory, worker_id)
    allowed_roots = [tmp_path_factory.getbasetemp(), Path(tempfile.gettempdir())]
    with archive_isolation(root, allowed_roots) as isolation:
        yield isolation
        stray = isolation.unreported()
        if stray:
            pytest.fail(f"BF-919: an archive outside the temporary roots was refused outside any test: {stray}", pytrace=False)


@pytest.fixture(autouse=True)
def isolated_archive_path(_bf919_isolated_archive):
    """BF-919 (#1632): this test's own Ship's Archive path, where an empty ``archive.db_path`` resolves.

    Nothing creates it unless the test opens the archive. A refusal during the test fails it at teardown: the boot
    only logs the error and continues without the archive.
    """
    isolation = _bf919_isolated_archive
    path = isolation.next_test_path()
    isolation.current = path
    try:
        yield path
    finally:
        isolation.current = isolation.session_path
    refused = isolation.unreported()
    if refused:
        pytest.fail(f"BF-919: this test opened a Ship's Archive outside the temporary roots: {refused}", pytrace=False)
```

(`tempfile`, `Path` and `pytest` are already imported at `tests/conftest.py:5`, `:24` and `:22`.)

### 7.3 New file: `tests/test_bf919_archive_isolation.py` (M1)

```python
"""BF-919 (#1632): no test opens the operator's Ship's Archive.

``tests/conftest.py`` enters ``tests/fixtures/archive_isolation.py`` for the session in every xdist worker: an empty
``archive.db_path`` resolves to the current test's own path under the worker's archive root, and ``ArchiveStore``
refuses any file outside the suite's temporary roots. A1 is the seam: a real default-config boot with the home
directory pointed at an empty directory opens this test's archive and leaves the home empty.
"""

from __future__ import annotations

import contextlib
import os
import sqlite3
from pathlib import Path
from typing import Any

import pytest

import probos.config as probos_config
import probos.knowledge.embeddings as embeddings_module
from probos.cognitive.llm_client import MockLLMClient
from probos.config import ArchiveConfig, SystemConfig
from probos.infrastructure import build_default_roots
from probos.knowledge.archive_store import ARCHIVE_SCHEMA_VERSION, ArchiveStore
from probos.runtime import ProbOSRuntime
from probos.storage.sqlite_factory import default_factory
from tests.fixtures.archive_isolation import ArchiveIsolation, archive_root_for


class _FakeTmpPathFactory:
    """The two ``tmp_path_factory`` calls the fixtures make, rooted under one test's ``tmp_path`` (AD-682's pattern)."""

    def __init__(self, root: Path) -> None:
        self._root = root

    def mktemp(self, basename: str, numbered: bool = True) -> Path:
        path = self._root / basename
        path.mkdir(parents=True, exist_ok=False)
        return path

    def getbasetemp(self) -> Path:
        return self._root


def _conftest_plugin(pytestconfig: pytest.Config) -> Any:
    return next(
        plugin for plugin in pytestconfig.pluginmanager.get_plugins() if hasattr(plugin, "_bf919_isolated_archive")
    )


def _boot_config() -> SystemConfig:
    """AD-1346's boot shape (``tests/test_ad1346_admission_service_boot.py``), the archive left at its default."""
    config = SystemConfig()
    config.onboarding.naming_ceremony = False
    config.proactive_cognitive.enabled = False
    config.qa.enabled = False
    return config


def _user_version(path: Path) -> int:
    with contextlib.closing(sqlite3.connect(path)) as raw:
        return int(raw.execute("PRAGMA user_version").fetchone()[0])


def _outside(tmp_path: Path) -> Path:
    """A path under the drive root: outside the basetemp and the system temporary directory."""
    return Path(tmp_path.anchor) / f"bf919-outside-{tmp_path.name}" / "archive.db"


def _never_called(store: Any, db_path: str, *args: Any, **kwargs: Any) -> None:
    pytest.fail("the refusal must stop before the original constructor")


async def test_a1_a_default_config_boot_opens_this_tests_archive_and_leaves_an_empty_home_empty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, isolated_archive_path: Path,
    _bf919_isolated_archive: ArchiveIsolation,
) -> None:
    """The seam: the platform default would land in this home; the boot opens this test's archive instead."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    monkeypatch.setenv("PROBOS_EMBEDDINGS", "local")  # BF-657's backend: this boot needs no model (M2 owns that path)
    monkeypatch.setattr(embeddings_module, "_embedding_available", None)
    monkeypatch.setattr(embeddings_module, "_embedding_fn", None)
    config = _boot_config()
    assert Path.home() == home, "premise: the home directory is redirected"
    assert list(home.iterdir()) == [], "premise: the home is empty"
    assert config.archive.enabled and config.archive.db_path == "", "premise: the default archive configuration"
    assert home in _bf919_isolated_archive.original_resolver(config.archive).parents, (
        "premise: without the redirect this boot's archive would be created in this home"
    )
    assert not isolated_archive_path.exists(), "premise: nothing creates this test's archive in advance"

    rt = ProbOSRuntime(config=config, data_dir=tmp_path / "data", llm_client=MockLLMClient())
    await rt.start()
    try:
        assert isolated_archive_path.is_file(), "the boot opened this test's own archive"
    finally:
        await rt.stop()
    assert _user_version(isolated_archive_path) == ARCHIVE_SCHEMA_VERSION, "and migrated it there"
    assert sorted(home.rglob("*")) == [], "the boot wrote nothing under the home directory"


def test_a2_an_archive_outside_the_temporary_roots_is_refused_and_recorded_before_anything_is_created(
    tmp_path: Path, _bf919_isolated_archive: ArchiveIsolation,
) -> None:
    isolation = _bf919_isolated_archive
    outside = _outside(tmp_path)
    assert not outside.parent.exists(), "premise"
    with pytest.raises(RuntimeError, match="BF-919"):
        ArchiveStore(str(outside), connection_factory=default_factory)
    with pytest.raises(RuntimeError, match="BF-919"):
        ArchiveStore(str(isolation.operator_default), connection_factory=default_factory)
    assert isolation.unreported() == [str(outside), str(isolation.operator_default)], "each refusal is recorded"
    assert not outside.parent.exists(), "refused before anything was created"
    ArchiveStore(str(tmp_path / "archive.db"), connection_factory=default_factory)
    assert isolation.unreported() == [], "a temporary path is accepted"


def test_a3_the_rule_admits_the_temporary_roots_and_memory_and_never_the_operators_default(tmp_path: Path) -> None:
    allowed_root = tmp_path / "allowed"
    operator = allowed_root / "operator" / "archive.db"

    def _platform(archive: ArchiveConfig) -> Path:
        return Path(archive.db_path) if archive.db_path else operator

    isolation = ArchiveIsolation(tmp_path / "root", [allowed_root], _platform)
    assert isolation.allowed(str(allowed_root / "t1" / "archive.db"))
    assert isolation.allowed(":memory:")
    assert not isolation.allowed(str(operator)), "the operator's default is refused even under an allowed root"
    assert not isolation.allowed(str(tmp_path / "elsewhere" / "archive.db"))
    assert isolation.resolve(ArchiveConfig()) == isolation.session_path
    chosen = tmp_path / "chosen" / "archive.db"
    assert isolation.resolve(ArchiveConfig(db_path=str(chosen))) == chosen


def test_a4_a_refusal_during_a_test_fails_that_test_at_teardown(tmp_path: Path, pytestconfig: pytest.Config) -> None:
    allowed_root = tmp_path / "allowed"
    isolation = ArchiveIsolation(tmp_path / "root", [allowed_root], lambda archive: allowed_root / "operator.db")
    fixture = _conftest_plugin(pytestconfig).isolated_archive_path.__wrapped__
    run = fixture(isolation)
    path = next(run)
    assert isolation.current == path and path.parent.parent == isolation.root
    with pytest.raises(RuntimeError, match="BF-919"):
        isolation.refusing(_never_called)(object(), str(tmp_path / "outside.db"))
    with pytest.raises(pytest.fail.Exception, match="BF-919"):
        next(run)
    assert isolation.current == isolation.session_path, "the next test starts from the session path"


def test_a4b_a_refusal_outside_any_test_fails_the_session_and_the_install_is_undone(
    tmp_path: Path, pytestconfig: pytest.Config,
) -> None:
    outer_resolver = probos_config.resolve_archive_db_path
    outer_init = ArchiveStore.__init__
    fixture = _conftest_plugin(pytestconfig)._bf919_isolated_archive.__wrapped__
    run = fixture(_FakeTmpPathFactory(tmp_path / "base"), "gw9")
    nested = next(run)
    assert nested.root == tmp_path / "base" / "probos_archive_gw9"
    assert probos_config.resolve_archive_db_path == nested.resolve, "premise: the nested redirect is installed"
    with pytest.raises(RuntimeError, match="BF-919"):
        ArchiveStore(str(_outside(tmp_path)), connection_factory=default_factory)
    with pytest.raises(pytest.fail.Exception, match="outside any test"):
        next(run)
    assert probos_config.resolve_archive_db_path == outer_resolver, "the redirect is restored"
    assert ArchiveStore.__init__ is outer_init, "the refusal is restored"


def test_a5_an_empty_db_path_resolves_to_this_tests_own_path_and_a_set_one_as_given(
    tmp_path: Path, isolated_archive_path: Path, _bf919_isolated_archive: ArchiveIsolation,
) -> None:
    assert probos_config.resolve_archive_db_path(ArchiveConfig()) == isolated_archive_path
    chosen = tmp_path / "chosen" / "archive.db"
    assert probos_config.resolve_archive_db_path(ArchiveConfig(db_path=str(chosen))) == chosen
    roots = build_default_roots(tmp_path / "data", SystemConfig())
    assert [root.path for root in roots if root.name == "archive"] == [isolated_archive_path.parent]
    assert isolated_archive_path.parent.parent == _bf919_isolated_archive.root
    first = _bf919_isolated_archive.next_test_path()
    assert first != _bf919_isolated_archive.next_test_path() and first != isolated_archive_path, "each test its own"
    assert not isolated_archive_path.parent.exists(), "resolving creates nothing"


def test_a6_each_worker_has_its_own_archive_root_beside_its_data_directory(
    tmp_path: Path, worker_id: str, tmp_path_factory: pytest.TempPathFactory,
    _bf919_isolated_archive: ArchiveIsolation,
) -> None:
    factory = _FakeTmpPathFactory(tmp_path)
    assert archive_root_for(factory, "gw0") != archive_root_for(factory, "gw1")
    root = _bf919_isolated_archive.root
    assert root == tmp_path_factory.getbasetemp() / f"probos_archive_{worker_id}"
    data_dir = Path(os.environ["PROBOS_DATA_DIR"])
    assert root != data_dir and data_dir not in root.parents and root not in data_dir.parents
```

### 7.4 New file: `tests/fixtures/model_download_guard.py` (M2)

```python
"""BF-919 (#1632) M2: the test suite downloads no embedding model into the home directory.

Chroma's default ONNX embedding function, which ``DefaultEmbeddingFunction`` calls, downloads its 83 MB model from S3
into its class attribute ``DOWNLOAD_PATH`` -- ``~/.cache/chroma/onnx_models/all-MiniLM-L6-v2``, computed when chromadb
is imported -- on first use, whatever ``HF_HUB_OFFLINE`` says. ``get_embedding_function`` reaches it only when the
sentence-transformers model does not load, which under the suite's ``HF_HUB_OFFLINE=1`` means that model is not
cached. So a machine without it downloaded Chroma's model into the home directory on its first boot.

``tests/conftest.py`` enters ``model_download_guard`` once per session in every xdist worker. When the extracted model
is on disk, ``DOWNLOAD_PATH`` keeps its value (the cache is read, never fetched). When it is not, ``DOWNLOAD_PATH`` is
pointed beneath a file: ``os.makedirs`` cannot create a directory under a file, so the download step fails before it
creates or fetches anything, its error names the file, and ``get_embedding_function`` takes its keyword fallback, the
path CI selects with ``PROBOS_EMBEDDINGS=local``. Only public class attributes are touched, as AD-1347 S1's tests do.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from chromadb.utils.embedding_functions.onnx_mini_lm_l6_v2 import ONNXMiniLM_L6_V2

SINKHOLE_NAME = "BF-919-the-test-suite-downloads-no-embedding-model"
MODEL_FILE = "model.onnx"


def download_path_for(original: Path, extracted: str, sinkhole: Path) -> Path:
    """Chroma's own directory when its extracted model is on disk, otherwise the same name beneath ``sinkhole``."""
    if original.joinpath(extracted, MODEL_FILE).is_file():
        return original
    return sinkhole / original.name


@contextmanager
def model_download_guard(sinkhole: Path) -> Iterator[Path]:
    """Write ``sinkhole``, point Chroma's download directory beneath it if no model is on disk, restore on exit."""
    original_value = ONNXMiniLM_L6_V2.DOWNLOAD_PATH
    sinkhole.write_text("BF-919 (#1632): the test suite downloads no embedding model.\n", encoding="utf-8")
    chosen = download_path_for(Path(original_value), ONNXMiniLM_L6_V2.EXTRACTED_FOLDER_NAME, sinkhole)
    ONNXMiniLM_L6_V2.DOWNLOAD_PATH = chosen
    try:
        yield chosen
    finally:
        ONNXMiniLM_L6_V2.DOWNLOAD_PATH = original_value
```

### 7.5 New file: `tests/test_bf919_model_download_guard.py` (M2)

```python
"""BF-919 (#1632) M2: the test suite downloads no embedding model into the home directory.

``tests/conftest.py`` enters ``tests/fixtures/model_download_guard.py`` for the session: when Chroma's ONNX model is
not already on disk, Chroma's download directory is pointed beneath a file, so the download step fails before it
creates or fetches anything and ``get_embedding_function`` takes its keyword fallback (what CI's
``PROBOS_EMBEDDINGS=local`` gives). A model already on disk is read as before, so real-model tests still run where
it is cached. The tests run in file order and the mutation campaign stops at the first failure: C1 and C2 kill a
mutated path rule before C3 reaches Chroma, and C3 also points every proxy at a closed port.
"""

from __future__ import annotations

from pathlib import Path

import chromadb.utils.embedding_functions as chroma_functions
import pytest
from chromadb.utils.embedding_functions.onnx_mini_lm_l6_v2 import ONNXMiniLM_L6_V2

import probos.knowledge.embeddings as embeddings_module
from tests.fixtures.model_download_guard import SINKHOLE_NAME, download_path_for, model_download_guard

_CLOSED_PORT = "http://127.0.0.1:9"
_MODEL = "all-MiniLM-L6-v2"


def _sinkhole(directory: Path) -> Path:
    directory.mkdir(parents=True)
    sinkhole = directory / SINKHOLE_NAME
    sinkhole.write_text("BF-919 test\n", encoding="utf-8")
    return sinkhole


def _no_sentence_transformer(*args: object, **kwargs: object) -> None:
    raise ImportError("BF-919 test: the sentence-transformers model is unavailable")


def test_c1_with_no_model_on_disk_the_download_directory_is_beneath_the_sinkhole(tmp_path: Path) -> None:
    original = tmp_path / "home" / ".cache" / "chroma" / "onnx_models" / _MODEL
    sinkhole = _sinkhole(tmp_path / "guard")
    assert download_path_for(original, "onnx", sinkhole) == sinkhole / _MODEL
    assert not (tmp_path / "home").exists(), "deciding creates nothing"


def test_c2_with_the_model_on_disk_chromas_own_directory_is_kept(tmp_path: Path) -> None:
    original = tmp_path / "cache" / _MODEL
    (original / "onnx").mkdir(parents=True)
    (original / "onnx" / "model.onnx").write_bytes(b"")
    assert download_path_for(original, "onnx", _sinkhole(tmp_path / "guard")) == original


def test_c3_with_no_model_on_disk_a_default_embedding_falls_back_and_creates_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = tmp_path / "home" / ".cache" / "chroma" / "onnx_models" / _MODEL
    sinkhole = _sinkhole(tmp_path / "guard")
    chosen = download_path_for(original, ONNXMiniLM_L6_V2.EXTRACTED_FOLDER_NAME, sinkhole)
    monkeypatch.setattr(ONNXMiniLM_L6_V2, "DOWNLOAD_PATH", chosen)
    monkeypatch.setattr(chroma_functions, "SentenceTransformerEmbeddingFunction", _no_sentence_transformer)
    monkeypatch.delenv("PROBOS_EMBEDDINGS", raising=False)
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        monkeypatch.setenv(name, _CLOSED_PORT)
    monkeypatch.delenv("NO_PROXY", raising=False)
    monkeypatch.delenv("no_proxy", raising=False)
    monkeypatch.setattr(embeddings_module, "_embedding_available", None)
    monkeypatch.setattr(embeddings_module, "_embedding_fn", None)

    assert embeddings_module.get_embedding_function() is None, "both real backends fail, so the keyword fallback"
    assert not (tmp_path / "home").exists(), "nothing was created where Chroma would download"
    assert [path.name for path in sinkhole.parent.iterdir()] == [SINKHOLE_NAME], "nor beside the sinkhole"


def test_c4_the_guard_writes_its_sinkhole_points_chroma_beneath_it_and_restores_chromas_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    absent = tmp_path / "home" / ".cache" / "chroma" / "onnx_models" / _MODEL
    monkeypatch.setattr(ONNXMiniLM_L6_V2, "DOWNLOAD_PATH", absent)
    sinkhole = tmp_path / SINKHOLE_NAME
    with model_download_guard(sinkhole) as chosen:
        assert sinkhole.is_file(), "the guard writes the file the download directory sits beneath"
        assert chosen == sinkhole / _MODEL
        assert ONNXMiniLM_L6_V2.DOWNLOAD_PATH == chosen
    assert ONNXMiniLM_L6_V2.DOWNLOAD_PATH == absent, "Chroma's directory is restored on exit"
    assert not (tmp_path / "home").exists()


def test_c5_conftest_installed_the_guard_for_this_worker(_bf919_no_model_download: Path) -> None:
    assert ONNXMiniLM_L6_V2.DOWNLOAD_PATH == _bf919_no_model_download
    folder = _bf919_no_model_download / ONNXMiniLM_L6_V2.EXTRACTED_FOLDER_NAME
    assert (folder / "model.onnx").is_file() or _bf919_no_model_download.parent.name == SINKHOLE_NAME
```

### 7.6 `tests/conftest.py` (M2): the model-download guard

The SEARCH block is created by §7.2 and occurs once after it.

SEARCH:
```python
    refused = isolation.unreported()
    if refused:
        pytest.fail(f"BF-919: this test opened a Ship's Archive outside the temporary roots: {refused}", pytrace=False)
```
REPLACE:
```python
    refused = isolation.unreported()
    if refused:
        pytest.fail(f"BF-919: this test opened a Ship's Archive outside the temporary roots: {refused}", pytrace=False)


@pytest.fixture(scope="session", autouse=True)
def _bf919_no_model_download(tmp_path_factory, worker_id):
    """BF-919 (#1632) M2: no test downloads Chroma's embedding model into the home directory.

    Where the model is not already on disk, Chroma's download directory is pointed beneath a file in this worker's
    basetemp, so the download fails before it creates anything and the embeddings fall back as CI's
    ``PROBOS_EMBEDDINGS=local`` does; a model on disk is read as before -- see
    ``tests/fixtures/model_download_guard.py``. ``PROBOS_EMBEDDINGS`` is deliberately not set here: real-model tests
    keep running wherever the model is cached (``docs/development/test-suite-optimization-plan.md`` section 6).
    """
    from tests.fixtures.model_download_guard import SINKHOLE_NAME, model_download_guard

    guard_dir = tmp_path_factory.mktemp(f"probos_model_guard_{worker_id}", numbered=False)
    with model_download_guard(guard_dir / SINKHOLE_NAME) as download_path:
        yield download_path
```

## 8. Tracking (tracker pairs; in M2's commit)

Each pair anchors on one line that occurs once in its file and that other entries do not change. BF-918 inserts its `PROGRESS.md` entry under the title line and its `DECISIONS.md` entry before the same heading used below, so both anchors survive it. Set the date to the commit date.

**`PROGRESS.md`** (anchored on the title line, `PROGRESS.md:1`):

SEARCH:
```markdown
# ProbOS Progress
```
REPLACE:
```markdown
# ProbOS Progress

**BF-919 (2026-10-23), closes #1632 -- test boots no longer open the operator's Ship's Archive, and the suite downloads no embedding model into the home directory.** An empty `archive.db_path` resolves under the home directory, outside `data_dir`, so every default-config boot in the suite opened and migrated the operator's archive (BF-883 covered only `data_dir`). `tests/conftest.py` now enters `tests/fixtures/archive_isolation.py` once per session in every xdist worker: an empty `db_path` resolves to each test's own path under `<basetemp>/probos_archive_<worker>`, and `ArchiveStore` refuses, before it opens anything, a file outside the suite's temporary roots or equal to the operator's default; a refusal fails its test (or the session), because the boot only logs it. Where Chroma's ONNX model is not on disk, `tests/fixtures/model_download_guard.py` points Chroma's download directory beneath a file, so a boot falls back as CI does and nothing lands in `~/.cache/chroma`; `PROBOS_EMBEDDINGS` is not set, so real-model tests still run where the model is cached. No production code, environment variable or config default changes. New: the two fixture modules, `tests/test_bf919_archive_isolation.py` and `tests/test_bf919_model_download_guard.py`. The contract is `prompts/bf-919-test-boots-isolate-archive-and-embedding-cache.md`.
```

**`DECISIONS.md`** (inserted before the heading below, which is at `DECISIONS.md:686` on this tree):

SEARCH:
```markdown
### Explicit delegation models, plain-id profile models and the orchestrator's model guard (2026-10-17; F-91, F-116 and F-117 on #1523)
```
REPLACE:
```markdown
### BF-919 -- Test boots never open the operator's Ship's Archive, and the suite downloads no embedding model into the home directory (2026-10-23, #1632)

- *Scope.* Test infrastructure only: `tests/conftest.py` (two session fixtures and one autouse function fixture), new `tests/fixtures/archive_isolation.py` and `tests/fixtures/model_download_guard.py`, new `tests/test_bf919_archive_isolation.py` and `tests/test_bf919_model_download_guard.py`. Contract: `prompts/bf-919-test-boots-isolate-archive-and-embedding-cache.md`. Tier HIGH (data integrity).
- *D1 (decided by the Architect under Delegated AD Execution Mode).* A session-level redirect of `probos.config.resolve_archive_db_path` (every production caller imports it inside the calling function) plus a refusal at `ArchiveStore` construction, recorded and failed at teardown because the boot swallows archive errors. Rejected: redirecting HOME/USERPROFILE/LOCALAPPDATA/XDG (moves the Hugging Face cache, git identity, Playwright and Chroma's import-time path; Windows ignores HOME), a default `ArchiveConfig` under tmp (moves default goldens), a guard in production code. Deferred: a production `PROBOS_ARCHIVE_DB_PATH` seam, if a booting child process ever inherits the real home (today's two give their children their own home).
- *D2 (revises the R2-1 direction on #1632).* No `PROBOS_EMBEDDINGS=local` in `tests/conftest.py`: CI already forces it, so the local gate is the only place real embeddings run, and `docs/development/test-suite-optimization-plan.md` section 6 rejects it. Chroma's public `DOWNLOAD_PATH` is pointed beneath a file only when its model is not on disk.
- *D3 (the tripwire).* Refusal at construction; the per-test teardown names the offender; the session teardown catches a refusal outside any test. Rejected: `pytest_sessionfinish` (not reliably reported under xdist) and a spy on `initialize` (after the open).
- *Disclosed effects.* Within the suite, an empty `db_path` resolves to a per-test path that exists only if the test opened the archive; `isolated_archive_path` is a new autouse fixture tests may request. On a machine without the sentence-transformers model, boots take the keyword fallback instead of downloading Chroma's model.
- *Reversal.* Revert the commits.

### Explicit delegation models, plain-id profile models and the orchestrator's model guard (2026-10-17; F-91, F-116 and F-117 on #1523)
```

**After both edits:** run `d:/ProbOS/.venv/Scripts/python.exe -P scripts/gen_ad_ledger.py`, commit the regenerated `docs/development/open-ads-report.md` and `docs/development/ad-ledger-snapshot.json`, and verify with `--check` and `tests/test_ad1184_ad_ledger.py`.

**`docs/development/roadmap.md`:** no row. The Bug Tracker has no `BF-9xx` rows (grep `BF-9[0-2]\d` returns 0), following BF-916's precedent.

**Docs-only commit after M2:** add a *Validation of record* bullet before *Reversal*: the campaign of record (§10), its base tree, the sha256 of each §10 file and each new test file, and each row's first failing test.

## 9. What this does NOT change

- No file under `src/probos/`: `resolve_archive_db_path`, `ArchiveConfig`, `ArchiveStore`, `embeddings.py` and the boot are byte-identical.
- `os.environ`, `Path.home()`, HOME, USERPROFILE, LOCALAPPDATA, `XDG_*`, `PROBOS_EMBEDDINGS`, `HF_HUB_OFFLINE`. No new `setdefault`, so `check_config_profiles.py` is unaffected.
- `.github/workflows/ci.yml`, `tests/test_ci_shards.py`, `scripts/run_test_gate.py`, `config-profiles.yaml`, the facade baseline.
- `tests/fixtures/runtime_lifecycle.py::lifecycle_config`: its explicit redirect stays, and is harmless.
- AD-1347 S1's own spies (`test_ad1347_s1_wiring.py:44-77`).
- Child processes: the guards do not cross a process boundary. The booting child fixtures redirect their own home (§11, AV4).
- The Hugging Face cache (still read from the real home, offline); the utility agents' `~/.probos` files; the default repository path of a directly constructed `KnowledgeStore` (§20).
- Any of BF-918's 33 files.

## 10. Mutation rows

Tier HIGH. Run each row on the contract-applied tree after an unmutated baseline passes, and restore the file before the next row.

Campaign command: `d:/ProbOS/.venv/Scripts/python.exe -m pytest -q -n 0 -x -p no:randomly tests/test_bf919_archive_isolation.py tests/test_bf919_model_download_guard.py`

Each Line cell occurs exactly once in its file after §7. Every mutant leaves one guard layer in place: rows on the redirect keep the refusal, and rows on the refusal keep the redirect. So the campaign cannot open the live archive. **No killer below has been probed (§19). Run the campaign in census mode, recording every failing test of every mutant, and revise any row whose named killer does not fail.**

| # | File | Line (stripped) | Mutate to | Killed by |
|---|---|---|---|---|
| M1-R1 | `tests/fixtures/archive_isolation.py` | `return self.current` | `return self.original_resolver(archive)` | A5; A3; A1 |
| M1-R2 | `tests/fixtures/archive_isolation.py` | `probos_config.resolve_archive_db_path = isolation.resolve` | `pass` | A5; A4b (premise) |
| M1-R3 | `tests/conftest.py` | `isolation.current = path` | `pass` | A5; A1 |
| M1-R4 | `tests/conftest.py` | `isolation.current = isolation.session_path` | `pass` | A4 |
| M1-R5 | `tests/fixtures/archive_isolation.py` | `if not self.allowed(str(db_path)):` | `if False:` | A2 |
| M1-R6 | `tests/fixtures/archive_isolation.py` | `return any(candidate.is_relative_to(allowed) for allowed in self.allowed_roots)` | `return True` | A2; A3 |
| M1-R7 | `tests/fixtures/archive_isolation.py` | `if candidate == self.operator_default:` | `if False:` | A3 |
| M1-R8 | `tests/fixtures/archive_isolation.py` | `if db_path == IN_MEMORY:` | `if False:` | A3 (relies on `Path(":memory:").resolve()` not raising on Windows; §19) |
| M1-R9 | `tests/fixtures/archive_isolation.py` | `self.refused.append(str(db_path))` | `pass` | A2; A4 |
| M1-R10 | `tests/conftest.py` | `if refused:` | `if False:` | A4 |
| M1-R11 | `tests/conftest.py` | `if stray:` | `if False:` | A4b |
| M1-R12 | `tests/fixtures/archive_isolation.py` | `ArchiveStore.__init__ = isolation.refusing(original_init)  # type: ignore[method-assign]` | `pass` | A2 |
| M1-R13 | `tests/fixtures/archive_isolation.py` | `ArchiveStore.__init__ = original_init  # type: ignore[method-assign]` | `pass` | A4b |
| M1-R14 | `tests/fixtures/archive_isolation.py` | `return self.root / f"t{next(self._numbers)}" / ARCHIVE_FILE` | `return self.session_path` | A5 |
| M1-R15 | `tests/fixtures/archive_isolation.py` | `return tmp_path_factory.mktemp(f"probos_archive_{worker_id}", numbered=False)` | `return tmp_path_factory.mktemp("probos_archive", numbered=False)` | A6 (second `mktemp` raises `FileExistsError`) |
| M2-R1 | `tests/fixtures/model_download_guard.py` | `if original.joinpath(extracted, MODEL_FILE).is_file():` | `if True:` | C1 |
| M2-R2 | `tests/fixtures/model_download_guard.py` | `return sinkhole / original.name` | `return original` | C1 |
| M2-R3 | `tests/fixtures/model_download_guard.py` | `ONNXMiniLM_L6_V2.DOWNLOAD_PATH = chosen` | `pass` | C4 |
| M2-R4 | `tests/fixtures/model_download_guard.py` | `ONNXMiniLM_L6_V2.DOWNLOAD_PATH = original_value` | `pass` | C4 |
| M2-R5 | `tests/fixtures/model_download_guard.py` | `sinkhole.write_text("BF-919 (#1632): the test suite downloads no embedding model.\n", encoding="utf-8")` | `pass` | C4 |

## 11. Verified Against Codebase (2026-10-23, `origin/main` `26bec26d`)

```
src/probos/config_models/knowledge.py
  358: class ArchiveConfig(BaseModel):   361: enabled: bool = True   362: db_path: str = ""
src/probos/config.py
  2631: def resolve_archive_db_path(archive: ArchiveConfig) -> Path:
  2642-2643: if archive.db_path: return Path(archive.db_path)
  2645: base = Path.home() / "AppData" / "Local" / "ProbOS" / "archive"   2649: xdg_data_home = os.environ.get("XDG_DATA_HOME")
src/probos/startup/cognitive_services.py
  671: if config.archive.enabled:   673: from probos.config import resolve_archive_db_path
  681: resolved_archive_path = resolve_archive_db_path(config.archive)   685: resolved_archive_path.parent.mkdir(...)
  688: archive_store = ArchiveStore(archive_db_path, connection_factory=default_factory)   689: await archive_store.initialize()
  691-697: except Exception -> logger.warning(...); archive_store = None
src/probos/knowledge/archive_store.py
  65: ARCHIVE_SCHEMA_VERSION = 1   320: def __init__(self, db_path: str, *, connection_factory: ConnectionFactory) -> None:
  326: async def initialize   343: PRAGMA user_version   358: PRAGMA user_version = {ARCHIVE_SCHEMA_VERSION}   359: commit
src/probos/__main__.py 3205/3209 (_configured_archive_store), 3223/3227 (_archive_reset_overlap): imports inside the function
src/probos/infrastructure/backup_inventory.py 216 build_default_roots; 229 import inside; 240 BackupRoot("archive", resolve_archive_db_path(archive).parent)
src/probos/infrastructure/__init__.py 15, 41: build_default_roots exported;  startup/finalize.py 3650: roots = build_default_roots(runtime.data_dir, config)
src/probos/config_models/operations.py 585: backup_include_archive_root: bool = True
src/probos/knowledge/embeddings.py 170: PROBOS_EMBEDDINGS local short-circuit; 179-180 Try 1; 199-201 Try 2; 205-211 except -> None
chromadb/utils/embedding_functions/onnx_mini_lm_l6_v2.py 39: DOWNLOAD_PATH = Path.home() / ".cache" / "chroma" / "onnx_models" / MODEL_NAME
  40: EXTRACTED_FOLDER_NAME = "onnx"   293-301: extracted check, then os.makedirs(self.DOWNLOAD_PATH, exist_ok=True)
chromadb/api/types.py 952-965: DefaultEmbeddingFunction.__call__ -> ONNXMiniLM_L6_V2()(input)
cpython 3.12.13 Lib/ntpath.py 366-375: USERPROFILE, else HOMEDRIVE+HOMEPATH;  Lib/pathlib.py 1198-1202: home() = Path("~").expanduser()
tests/conftest.py 5 import tempfile; 17-20 BF-883; 22 import pytest; 24 Path; 44-45 NATS/HF setdefault; 50 overlay; 58 keyring (forced)
  66-89 _ad682_isolated_data_dir (mktemp probos_data_<worker>); 128-139 _ad1270f_codebase_index_memo
tests/fixtures/runtime_lifecycle.py 74-90 lifecycle_config (explicit archive db_path under tmp_path)
tests/fixtures/federation_cluster.py 147-158 child HOME/USERPROFILE/LOCALAPPDATA/XDG under its node dir
tests/test_ad1137_quickstart_chain.py 195-207 child home under tmp_path, PROBOS_* stripped
tests/fixtures/failed_start_child.py 104, 156: make_runtime(base, config=lifecycle_config(...))
tests/test_ad682_fixture_isolation.py 15-22 _FakeTmpPathFactory; 25-30 plugin lookup; 99, 116 fixture.__wrapped__
tests/test_ad1347_s1_wiring.py 57 setattr(probos_config, "resolve_archive_db_path", ...); 76 setattr(ONNXMiniLM_L6_V2, "DOWNLOAD_PATH", ...)
tests/test_ad487_self_distillation.py 388: <Class>.__init__ = _patched_init  # type: ignore[assignment]   (precedent)
scripts/run_test_gate.py 70-79 _PYTEST_CONTROL_ENV; 812-822 env = os.environ.copy() ...; 825-836 _pytest_subprocess_env
scripts/check_config_profiles.py 389-406 setdefault pairs by AST; 564-586 declared->real only for declared rows
tests/test_ci_shards.py 1581: assert shard["env"] == {"PROBOS_EMBEDDINGS": "local"};  .github/workflows/ci.yml 40, 131
docs/development/test-suite-optimization-plan.md 267 (P2.6), 298 (section 6): PROBOS_EMBEDDINGS=local in the canonical gate rejected
pyproject.toml 181 asyncio_mode = "auto"; 196 addopts = "-n 16 --dist=loadfile"
PROGRESS.md 1: # ProbOS Progress;  DECISIONS.md 686: ### Explicit delegation models, ...
```

SEARCH uniqueness: `install_codebase_index_memo` occurs at `tests/conftest.py:136` and `:138` only, so the §7.2 block occurs once. The §7.6 block exists only after §7.2. The tracker anchors occur once each (Grep).

## 12. Absence Verified (2026-10-23)

| # | Claim | Run | Found | Holds |
|---|---|---|---|---|
| AV1 | No `src` caller binds `resolve_archive_db_path` at module import | Grep `resolve_archive_db_path` in `src` | `config.py:2631` (def); `__main__.py:3205`, `:3223`, `cognitive_services.py:673`, `backup_inventory.py:229`, all indented inside functions | yes |
| AV2 | No test constructs `ArchiveStore` outside tmp_path | Grep `ArchiveStore\(` in `tests` | `test_ad1341_s1_archive_store.py:52`, `test_ad1341_s1_promotion.py:49`, `test_ad1341_s1_reset_and_erase.py:201`, `:245`, `test_ad524_ships_archive.py:128` (fake), `:158` (tmp_path at `:159`) | yes (statically) |
| AV3 | No test clears `os.environ` wholesale | Grep `os\.environ.*clear=True`, `patch\.dict\(\s*os\.environ`, `setattr\(os, "environ"` | none | yes |
| AV4 | Child processes that boot a runtime have their own home or an explicit archive | Glob `tests/fixtures/*child*.py`; Grep `ProbOSRuntime\(\|make_runtime\(` in `tests/fixtures`; Grep `"-m",\s*"probos"` in `tests` | `failed_start_child.py` (lifecycle_config); `rollback_child.py` (BareRuntime, no archive); `federation_cluster_node.py:182` (home from `child_env`); quickstart (own home); `test_bf908_crew_scope_token.py:1346` (`crew-token`, no boot) | yes |
| AV5 | The installed chromadb has no environment variable for the ONNX directory | Grep `CHROMA_CACHE_DIR\|cache_dir` in `onnx_mini_lm_l6_v2.py` | none | yes |
| AV6 | No existing name collides with the new fixtures or modules | Grep `isolated_archive\|_bf919\|archive_isolation\|model_download_guard` in `tests`, `src`, `scripts` | none | yes |
| AV7 | A default boot writes nothing else under the home directory | src enumeration (§13) and #1632's reproduction (an empty home gained only the archive and `.cache/chroma`) | the desktop lock file (`experience.py:365`; desktop off, `finalize.py:124`); M365 cache (`runtime.py:723`, needs `enabled` and `client_id`); office dirs (`config.py:3771`, off); `KnowledgeStore` (boot passes `data_dir`, `cognitive_services.py:547-548`) | yes; A1 asserts it |

## 13. Pins the change makes stale, and home-derived paths

**Search for pins:**

| Run | Hits | Classification |
|---|---|---|
| Grep `resolve_archive_db_path` in `tests` | `test_ad1265_backup_coverage.py:268` (docstring); `test_ad1270e1_config_facade.py:1613` (docstring); `test_ad1347_s1_wiring.py:48`, `:57` | unaffected (S1 replaces the redirect for its tests; monkeypatch restores it) |
| Grep `ONNXMiniLM_L6_V2\|DOWNLOAD_PATH\|_download_model_if_not_exists` in `tests` | `test_ad1347_s1_wiring.py:16`, `:76` | unaffected |
| Grep `getbasetemp\|probos_archive\|probos_data_\|pytest-of-` in `tests` | `conftest.py:80`; `test_ad682_fixture_isolation.py:39` | unaffected |
| Grep `conftest` in `tests` (32 files) | readers of conftest content: `test_ad1185_config_profiles.py:1042-1045` (setdefault pairs; none added), `test_ad682_fixture_isolation.py:25-30` (plugin found by attribute), `test_abortive_self_pipe.py:336`, `test_timeout_timer_release.py:86-89`, `test_bf245_nats_xdist_isolation.py:49`, `test_ad1270f_impact_selector.py:1625-1633` (glob), `test_ad1270f_codebase_index_memo.py:304-307`; nested-run tests (`test_run_test_gate.py`, `test_ci_shard_pytest_plugin.py`) write their own conftest | unaffected; none pins the conftest fixture set |
| Facade in-process introspection: Grep `build_surface\|_classify` in `tests` | `test_ad1270e1_config_facade.py:246` (a fake module, `:243-245`); the real capture runs in a scrubbed child (`check_config_facade.py:1015-1016`) | unaffected |
| Default goldens (`test_ad1152`, `test_ad1270e2f` EXPECTED_DUMPS) | no config default changes | unaffected |
| Grep `Path\.home\|expanduser\|USERPROFILE\|LOCALAPPDATA\|XDG_DATA_HOME\|XDG_CACHE_HOME\|"HOME"` in `tests` (17 files: `test_claude_architect_bridge`, `test_bf911_*`, `test_bf908_floor_and_children`, `test_bf892_spawn_env`, `test_bf890_command_env`, `test_bf883_*`, `test_bf864_*`, `test_bf539_avatars_path`, `test_ad841_desktop_status`, `test_ad1270e1_*`, `test_ad1265_backup_coverage`, `test_ad1185_*`, `test_ad1137_quickstart_chain`, `test_ad1025b_path_anchoring`, `fixtures/federation_cluster.py`, `fixtures/ad1328_shell_oracle.json`, `conftest.py`) | none is affected: this change does not alter the home or the environment |
| Embedding toggle readers (D2) | listed in D2 | unaffected: the toggle is not set |

**Not classified:** a test that asserts archive contents after a default-config boot would now see an empty per-test archive. No such test was found, but the search (`archive_store` reads after a default boot) was not exhaustive.

**Home-derived paths in `src`:**

| Site | Reached by a test boot | Owner |
|---|---|---|
| `config.py:2645-2653` archive | yes (boot, backup roots); the CLI reset and erase | **this BF (M1)** |
| chromadb `DOWNLOAD_PATH` (third-party) | yes, when sentence-transformers does not load | **this BF (M2)** |
| `runtime.py:247-253`, `execution/workspace.py:81-88`, `cognitive/scout.py:34-41` data directory | no (`PROBOS_DATA_DIR` set by BF-883 and AD-682) | done |
| `knowledge/store.py:110` `~/.probos/knowledge` | no (boot passes `data_dir`) | register R-2 |
| `config.py:3760`, `:3772-3783` (M365, office: expanded strings only) | no (off, or needs `client_id`) | none |
| `experience/desktop/lifecycle.py:27`, `:104-187` | no (desktop off) | none |
| `agents/utility/organizer_agents.py:119`, `:249`; `productivity_agents.py:162` | only on their intents | register R-1 |
| `doctor/runner.py:29-38`, `migration/__init__.py:81-239`, `__main__.py:84` | CLI only | none |
| `security/file_access.py:226`, `startup/finalize.py:1929`, `skill_framework.py:69/209/416`, `integrations/template_registry.py:35`, `consultation/delivery.py:370`, `routers/desktop.py:81` | reads, or on explicit calls | none |
| `cognitive/builder.py:1592`, `execution/command_env.py:38-47` (environment names passed to children) | n/a | none |

## 14. Deterministic gate checks, resolved up front

| Check | Result |
|---|---|
| Phantom precheck, pattern 3 | Capitalised calls are ProbOS classes (`ProbOSRuntime`, `SystemConfig`, `ArchiveConfig`, `ArchiveStore`, `MockLLMClient`), classes this contract defines (`ArchiveIsolation`), or builtins found by `except X:` in `src` (`RuntimeError`, `ImportError`). `_FakeTmpPathFactory(` begins with an underscore. Chroma names appear only as string literals or in uppercase attribute access. |
| Pattern 2 | `ArchiveStore.__init__` (exists). `ONNXMiniLM_L6_V2.DOWNLOAD_PATH` and `.EXTRACTED_FOLDER_NAME` start uppercase, so they are not matched. |
| Pattern B | `isolation = ArchiveIsolation(` types `isolation` as a class this contract defines (unresolved, skipped). `rt = ProbOSRuntime(` calls only `start` and `stop`. |
| Config profiles and facade | No `setdefault` added; no `config.py` change. |
| Architecture and store registry | Tests only; no `CREATE TABLE`. |
| Ledger | Regenerated in M2's commit. |
| Cost | One counter step per test. M2 imports chromadb once per worker at session start (unmeasured; §19). A1 is one real boot. |

## 15. Prior Art and Blind Spots

- **Bug fix in ProbOS-specific plumbing.** `docs/research/reference-projects.md` was checked on 2026-10-23: no listed project concerns test hermeticity, so none was reviewed and the overdue rows were not relevant. There are no row updates.
- **Internal precedent, adopted:**
  - BF-883 and AD-682: per-worker temporary roots, and the AD-682 fake-factory and `__wrapped__` test shape;
  - AD-1347 S1 A3 and A4: a per-test resolver spy and the `DOWNLOAD_PATH` redirect, generalised here to the whole suite;
  - BF-908: the guard is installed for the session, not file by file;
  - the federation and quickstart fixtures: child processes get their own home.
- **External, one search.** A docs mirror describes a `CHROMA_CACHE_DIR` setting ([mintlify mirror](https://mintlify.wiki/chroma-core/chroma/integrations/sentence-transformers)). Rejected: the installed chromadb has no such read (AV5). The Go client pre-caches the model for offline tests ([offline runtime bundle](https://go-client.chromadb.dev/offline-runtime-bundle)). Considered and deferred: pre-caching would add a download to set-up, which this BF exists to avoid.
- **Blind spots absorbed:**
  - the boot swallows archive errors, so a refusal is recorded and failed rather than only raised;
  - AD-1265's backup and restore roots and AD-1341's reset and erase use the same resolver, so both are covered;
  - a resolver bound at import is caught by the construction refusal;
  - a mutation campaign could otherwise open the live archive, so every row keeps one guard layer;
  - Chroma ignores `HF_HUB_OFFLINE`;
  - nested pytest runs write their own conftest.
- **Considered and deferred:** the production environment seam (D1 option 2); pre-caching models; a ci_divergences row (there is no environment divergence).

## 16. Diff Reviewer: properties to verify

1. While the session fixtures are installed, no `ArchiveStore` can be constructed for a path that is the operator's default or that lies outside the worker's basetemp and `tempfile.gettempdir()`. Each such attempt raises before any I/O, is recorded, and fails the active test at teardown, or the session if no test is active, even when the caller catches the exception.
2. An empty `db_path` resolves to a path unique to each test under `<basetemp>/probos_archive_<worker>`. Nothing creates it except a caller that opens the archive. A set `db_path` resolves exactly as the original function does.
3. Both patches, and Chroma's `DOWNLOAD_PATH`, are restored on exit, and a nested install restores the outer state.
4. No file under `src/` changes, and no environment variable, `Path.home()` or config default changes.
5. The archive root is per xdist worker, comes from `tmp_path_factory`, and is neither inside nor a parent of the AD-682 data directory.
6. `DOWNLOAD_PATH` is replaced only when `<DOWNLOAD_PATH>/onnx/model.onnx` is absent. In that case nothing is created under the original path or beside the sinkhole, and no network fetch is attempted.
7. On a machine whose Hugging Face cache holds the model, every embedding test runs exactly as before.
8. **Consumers that must accept the change:** the boot's archive block, `__main__`'s reset and erase, `build_default_roots`, AD-1347 S1's spies and `test_ad682`'s plugin lookup.
9. No new test can pass vacuously. A1 asserts the empty home, the original resolver pointing into it, and the per-test archive created at `user_version` 1. C4 and C5 assert the installation itself.

## 17. Acceptance criteria

- §7.1 to §7.6 and §8 are applied in milestone order. Each milestone's focused gate passes at `-n 0`, and the two new files pass at `-n 4`. The precheck is clean, and `gen_ad_ledger.py --check` reports current.
- Every new test fails on the tree before the change (import). A1 fails on the behaviour when M1-R1 is applied.
- All 20 rows in §10 are killed in census mode; any row whose named killer does not fail is revised before the merge.
- The §18 runs hold.
- The broad gate runs once, run by the orchestrator, with `--receipt`; one PR closes #1632.
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## 18. Live acceptance (read-only; never open the live file with SQLite; never `d:\ProbOS\data`)

`<T>` is a fresh directory under `%TEMP%`. Set the variables for the child process only, never in the orchestrator's own shell.

1. **Run 1 (the check discriminates; the tree before the fix).** In a worktree at `origin/main`, with `USERPROFILE` and `HOME` set to an empty `<T>\homeB` (assert 0 entries first), run `pytest -q -n 0 tests/test_ad1346_admission_service_boot.py`. Expect `homeB\AppData\Local\ProbOS\archive\archive.db`, and `.cache\chroma` if the network is reachable (#1632's reproduction).
2. **Run 2 (the candidate).** The same command plus both new test files, with a fresh empty `<T>\homeC`. Expect 0 entries in `homeC`.
3. **Run 3 (the candidate, full gate).**
   - Build `<T>\homeA\AppData\Local\ProbOS\archive\archive.db` as a file copy of `%LOCALAPPDATA%\ProbOS\archive\archive.db`. Copy `%USERPROFILE%\.gitconfig` into `homeA`, if it exists, for the git identity.
   - Record the sha256 of the copy and a listing of every entry under `homeA` (relative path, size, LastWriteTimeUtc), stored outside `homeA`.
   - Run `scripts/run_test_gate.py --label bf919-acceptance --receipt logs/gates/bf919-acceptance.receipt.json` with `USERPROFILE` and `HOME` set to `homeA`, and `HF_HOME` set to the real `%USERPROFILE%\.cache\huggingface`, so model coverage is kept and the Hugging Face cache writes stay out of `homeA`. The wrapper carries these into its worktree child and the xdist workers (`run_test_gate.py:812-836`).
   - Expect the copy's sha256 unchanged and the listing identical.
   - This is acceptance evidence. The gate of record runs in the normal environment; its outcomes should match Run 3's.
4. **Optional, on the live file.** Before and after Run 3, copy the live archive to a scratch directory and hash the copies; record the live file's length and LastWriteTimeUtc. Expect them unchanged, unless the running vessel itself rebooted during the run.
5. **Optional, on the tree before the fix.** Repeat Run 2's command with a fresh copy in `homeA'`. A changed hash shows that the Run 3 check discriminates. If the hash does not change, the header write does not alter bytes, and Run 1 is the discriminating evidence. Record which.

## 19. Not verified

- **No probe was run.** Under this bridge only `ad_ceiling.py` may run. Every killer in §10 and every expectation in §5 is hand-traced. In particular:
  - `os.makedirs` beneath a file raising an `OSError` on Windows;
  - `Path(":memory:").resolve()` not raising on Windows (M1-R8);
  - `__wrapped__` on the new fixtures (precedent: `test_ad682`).
- **Live archive row counts and `user_version`** were not read (no SQLite); #1632's 2026-10-23 measurement stands. The listing shows only `archive.db` in the archive directory.
- **Listings of the home directory** for `.probos` and `.gitconfig` were denied, which is why §18 says "if it exists".
- **The cost** of importing chromadb once per worker at session start was not measured.
- **Inline `python -c` child processes:** one grep found none; other spawn styles were not enumerated.

## 20. For the register (not fixed here)

- **R-1.** The utility agents write `~/.probos/notes`, `reminders.json` and `todos.json` on their intents (`organizer_agents.py:119`, `:249`; `productivity_agents.py:162`). A test that dispatches those intents to a real agent writes into the real home.
- **R-2.** `KnowledgeStore` defaults to `~/.probos/knowledge` when constructed directly with an empty `repo_path` (`knowledge/store.py:110`). The boot overrides this; direct test constructions were not enumerated.
- **R-3.** Under offline mode, huggingface_hub may write `.no_exist` markers into the real `~/.cache/huggingface` (seen in the Captain's cache; the cause is unverified).
- **R-4.** If a child process that boots a runtime ever inherits the real home, adopt the production environment seam (D1 option 2).
- **R-5.** The docstrings of `lifecycle_config` (`runtime_lifecycle.py:77`) and `test_ad1347_s1_wiring.py:34-35` describe production behaviour. Inside the suite the default is now redirected; a later doc pass may say so.

