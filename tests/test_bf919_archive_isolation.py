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
