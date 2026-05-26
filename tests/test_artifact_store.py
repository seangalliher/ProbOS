"""AD-797 (Wave 197): tests for ArtifactStore race-safety + new helpers."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from probos.artifacts import ArtifactStore


@pytest.fixture()
def store(tmp_path: Path) -> ArtifactStore:
    return ArtifactStore(tmp_path / "artifacts.db")


def test_add_version_sequential(store: ArtifactStore) -> None:
    a = store.add_version(
        thread_id="t1", name="foo.txt", content_hash="h1",
        mime="text/plain", size_bytes=3, created_by="agent",
    )
    b = store.add_version(
        thread_id="t1", name="foo.txt", content_hash="h2",
        mime="text/plain", size_bytes=3, created_by="agent",
    )
    assert a.version == 1
    assert b.version == 2
    assert b.supersedes == a.id


def test_add_version_race_safety_bf324(tmp_path: Path) -> None:
    """BF-324 regression: 4 concurrent ``add_version`` calls on the same
    ``(thread_id, name)`` must produce versions 1/2/3/4 without
    IntegrityError.

    ArtifactStore is sync — run each add_version on its own SQLite
    connection from a thread, and let the BEGIN IMMEDIATE serialize
    them. asyncio.gather over run_in_executor mimics what production
    looks like when multiple pipelines race the same thread.
    """
    store = ArtifactStore(tmp_path / "race.db")

    async def _go() -> list[int]:
        loop = asyncio.get_running_loop()

        def _add(i: int) -> int:
            a = store.add_version(
                thread_id="race-thread", name="boom.txt",
                content_hash=f"h{i}", mime="text/plain",
                size_bytes=1, created_by="agent",
            )
            return a.version

        return await asyncio.gather(
            *(loop.run_in_executor(None, _add, i) for i in range(4))
        )

    versions = asyncio.run(_go())
    assert sorted(versions) == [1, 2, 3, 4]


def test_find_first_by_hash_returns_earliest(
    store: ArtifactStore,
) -> None:
    # Two artifacts in different threads sharing the same content hash.
    a = store.add_version(
        thread_id="t1", name="x.md", content_hash="shared",
        mime="text/markdown", size_bytes=4, created_by="agent",
    )
    b = store.add_version(
        thread_id="t2", name="y.md", content_hash="shared",
        mime="text/markdown", size_bytes=4, created_by="agent",
    )
    found = store.find_first_by_hash("shared")
    assert found is not None
    # ``a`` was created first; expect its id back (deterministic).
    assert found.id == a.id
    assert found.thread_id == "t1"


def test_find_first_by_hash_missing_returns_none(
    store: ArtifactStore,
) -> None:
    assert store.find_first_by_hash("does-not-exist") is None
