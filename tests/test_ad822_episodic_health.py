"""AD-822 tests: subprocess-isolated ChromaDB health probe."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from probos.episodic_health import (
    EpisodicCorruptionDetected,
    EpisodicHealthResult,
    SKIP_ENV_VAR,
    check_episodic_health,
)


def _build_healthy_store(data_dir: Path) -> None:
    """Build a real chroma store with one row in the 'episodes' collection."""
    import chromadb

    client = chromadb.PersistentClient(path=str(data_dir))
    collection = client.get_or_create_collection(name="episodes")
    collection.add(
        ids=["ad822-test-1"],
        documents=["test row for ad822 health probe"],
        metadatas=[{"source": "ad822-test"}],
    )
    # Drop references so the underlying sqlite file handle is released
    # before the subprocess probe tries to open it (Windows file lock).
    del collection
    del client


def test_probe_on_healthy_db_returns_ok(tmp_path: Path) -> None:
    pytest.importorskip("chromadb")
    _build_healthy_store(tmp_path)

    result = check_episodic_health(tmp_path)

    assert isinstance(result, EpisodicHealthResult)
    assert result.ok is True
    assert result.error is None
    assert result.duration_s > 0.0


def test_probe_on_first_boot_returns_ok(tmp_path: Path) -> None:
    # Point at a path that does not exist yet.
    nonexistent = tmp_path / "does-not-exist-yet"
    assert not nonexistent.exists()

    result = check_episodic_health(nonexistent)

    assert result.ok is True
    assert result.error is None


def test_probe_on_corrupt_db_returns_not_ok(tmp_path: Path) -> None:
    pytest.importorskip("chromadb")
    # Write garbage to chroma.sqlite3 — the probe will try to open it and fail.
    (tmp_path / "chroma.sqlite3").write_bytes(b"GARBAGE\x00" * 1024)

    result = check_episodic_health(tmp_path)

    assert result.ok is False
    assert result.error is not None
    assert len(result.error) > 0


def test_probe_timeout_returns_not_ok(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Replace the probe module spawn with a sleep loop via a tiny stub script.
    # We monkeypatch sys.executable's effective argv by writing a stub probe
    # module path — easier: just pass a microscopic timeout and a real corrupt
    # db so subprocess startup + import dwarfs the timeout. Even faster: use
    # timeout_s=0.001 against an empty path; the python interpreter import
    # alone takes longer than 1ms.
    result = check_episodic_health(tmp_path, timeout_s=0.001)

    assert result.ok is False
    assert result.error is not None
    assert "timed out" in result.error.lower()


def test_skip_env_var_bypasses_probe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Build a corrupt store so the probe would fail if it ran.
    (tmp_path / "chroma.sqlite3").write_bytes(b"GARBAGE\x00" * 1024)
    monkeypatch.setenv(SKIP_ENV_VAR, "1")

    result = check_episodic_health(tmp_path)

    assert result.ok is True
    assert result.error is None
    assert result.duration_s == 0.0


def test_subprocess_isolation_parent_survives_probe_crash(tmp_path: Path) -> None:
    pytest.importorskip("chromadb")
    (tmp_path / "chroma.sqlite3").write_bytes(b"GARBAGE\x00" * 1024)

    pid_before = os.getpid()
    result = check_episodic_health(tmp_path)
    pid_after = os.getpid()

    # Parent must not have been replaced/killed.
    assert pid_before == pid_after
    # And the call must have returned a result rather than raising.
    assert isinstance(result, EpisodicHealthResult)
    assert result.ok is False


def test_corruption_detected_remediation_message(tmp_path: Path) -> None:
    exc = EpisodicCorruptionDetected(tmp_path, "peek-or-count-failed: torn-hnsw", 1.5)

    msg = str(exc)
    assert "probos rebuild-episodic" in msg
    assert "AD-819" in msg
    assert SKIP_ENV_VAR in msg
    assert str(tmp_path) in msg
    assert "1.5" in msg
