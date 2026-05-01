"""AD-682 fixture isolation regression tests."""

from __future__ import annotations

import os
from pathlib import Path

import pytest


class _FakeTmpPathFactory:
    def __init__(self, root: Path) -> None:
        self._root = root

    def mktemp(self, basename: str, numbered: bool = True) -> Path:
        path = self._root / basename
        path.mkdir(parents=True, exist_ok=False)
        return path


class _FakeEmbeddingFunction:
    def name(self) -> str:
        return "ad682-fake-embedding"

    def __call__(self, input: list[str]) -> list[list[float]]:
        return [[0.1, 0.2, 0.3] for _ in input]


def _ad682_conftest_plugin(pytestconfig):
    return next(
        plugin
        for plugin in pytestconfig.pluginmanager.get_plugins()
        if hasattr(plugin, "_ad682_isolated_data_dir")
    )


def test_data_dir_is_isolated() -> None:
    data_dir = Path(os.environ["PROBOS_DATA_DIR"])
    project_data = Path.cwd() / "data"

    assert data_dir.exists()
    assert data_dir != project_data
    assert "probos_data_" in data_dir.name


def test_default_data_dir_honors_env(monkeypatch, tmp_path: Path) -> None:
    from probos.__main__ import _default_data_dir

    override = tmp_path / "override-data"
    monkeypatch.setenv("PROBOS_DATA_DIR", str(override))

    assert _default_data_dir() == override


def test_default_data_dir_falls_back_when_env_unset(monkeypatch) -> None:
    from probos.__main__ import _default_data_dir

    monkeypatch.delenv("PROBOS_DATA_DIR", raising=False)

    data_dir = _default_data_dir()

    assert data_dir.name == "data"
    assert data_dir.parent.name == "ProbOS"


@pytest.mark.asyncio
async def test_chroma_writes_inside_isolated_dir(monkeypatch) -> None:
    from probos.cognitive.episodic import EpisodicMemory
    from probos.knowledge import embeddings
    from probos.types import Episode

    data_dir = Path(os.environ["PROBOS_DATA_DIR"])
    monkeypatch.setattr(embeddings, "get_embedding_function", lambda: _FakeEmbeddingFunction())
    memory = EpisodicMemory(data_dir / "episodes.sqlite3")
    await memory.start()
    try:
        await memory.store(
            Episode(
                user_input="AD-682 isolation smoke episode",
                outcomes=[{"success": True, "response": "stored"}],
                agent_ids=["ad682"],
            )
        )

        chroma_files = list(data_dir.rglob("chroma.sqlite3*"))

        assert chroma_files
        assert all(data_dir in path.parents for path in chroma_files)
    finally:
        await memory.stop()


def test_module_cache_cleared_between_tests(pytestconfig, tmp_path: Path) -> None:
    from probos.cognitive import standing_orders

    conftest = _ad682_conftest_plugin(pytestconfig)
    missing_file = tmp_path / "missing.md"
    standing_orders._load_file(missing_file)
    standing_orders._build_personality_block("missing_agent")
    assert standing_orders._load_file.cache_info().currsize > 0
    assert standing_orders._build_personality_block.cache_info().currsize > 0

    fixture = conftest._ad682_clear_module_caches.__wrapped__
    clear_run = fixture()
    try:
        next(clear_run)

        assert standing_orders._load_file.cache_info().currsize == 0
        assert standing_orders._build_personality_block.cache_info().currsize == 0
    finally:
        try:
            next(clear_run)
        except StopIteration:
            pass


def test_two_pseudo_workers_dont_collide(pytestconfig, tmp_path: Path) -> None:
    conftest = _ad682_conftest_plugin(pytestconfig)
    factory = _FakeTmpPathFactory(tmp_path)
    fixture = conftest._ad682_isolated_data_dir.__wrapped__
    worker_zero = fixture(factory, "gw0")
    worker_one = fixture(factory, "gw1")
    try:
        path_zero = next(worker_zero)
        (path_zero / "sentinel.txt").write_text("gw0", encoding="utf-8")
        path_one = next(worker_one)
        (path_one / "sentinel.txt").write_text("gw1", encoding="utf-8")

        assert path_zero != path_one
        assert (path_zero / "sentinel.txt").read_text(encoding="utf-8") == "gw0"
        assert (path_one / "sentinel.txt").read_text(encoding="utf-8") == "gw1"
    finally:
        for worker in (worker_one, worker_zero):
            try:
                next(worker)
            except StopIteration:
                pass
