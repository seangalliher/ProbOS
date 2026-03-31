"""BF-087: Reset integration tests — full state-create-reset-verify cycle."""

import argparse
import sqlite3
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


def _create_sqlite_db(path: Path, table: str = "data", rows: int = 3) -> None:
    """Create a real SQLite database with a table and sample rows."""
    conn = sqlite3.connect(str(path))
    conn.execute(f"CREATE TABLE {table} (id INTEGER PRIMARY KEY, value TEXT)")
    for i in range(rows):
        conn.execute(f"INSERT INTO {table} VALUES (?, ?)", (i, f"row_{i}"))
    conn.commit()
    conn.close()


def _db_has_data(path: Path, table: str = "data") -> bool:
    """Check if a SQLite database exists and has rows."""
    if not path.exists():
        return False
    conn = sqlite3.connect(str(path))
    try:
        cursor = conn.execute(f"SELECT COUNT(*) FROM {table}")
        return cursor.fetchone()[0] > 0
    except Exception:
        return False
    finally:
        conn.close()


def _reset_args(data_dir, **overrides):
    defaults = dict(
        yes=True, soft=False, full=False,
        dry_run=False, wipe_records=False, config=None, data_dir=data_dir,
    )
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


def _run_reset(data_dir, tmp_path, **flag_overrides):
    """Execute _cmd_reset with proper mocks."""
    from probos.__main__ import _cmd_reset

    knowledge_dir = tmp_path / "knowledge"
    knowledge_dir.mkdir(exist_ok=True)

    args = _reset_args(data_dir, **flag_overrides)
    mock_config = MagicMock()
    mock_config.knowledge.repo_path = str(knowledge_dir)

    with patch("probos.__main__._load_config_with_fallback", return_value=(mock_config, None)):
        with patch("probos.__main__._default_data_dir", return_value=data_dir):
            _cmd_reset(args)


class TestTier1RebootIntegration:
    """Tier 1: clears transients, preserves cognition + identity + records."""

    def test_clears_tier1_preserves_rest(self, tmp_path):
        data_dir = tmp_path / "data"
        data_dir.mkdir()

        # Tier 1 targets
        _create_sqlite_db(data_dir / "scheduled_tasks.db", "tasks")
        _create_sqlite_db(data_dir / "events.db", "events")
        cp_dir = data_dir / "checkpoints"
        cp_dir.mkdir()
        (cp_dir / "dag1.json").write_text("{}")

        # Tier 2 files (should survive)
        _create_sqlite_db(data_dir / "trust.db", "trust_scores")
        _create_sqlite_db(data_dir / "identity.db", "agents")
        _create_sqlite_db(data_dir / "hebbian_weights.db", "weights")
        (data_dir / "session_last.json").write_text('{"ts": 1}')

        # Tier 3 files (should survive)
        _create_sqlite_db(data_dir / "ward_room.db", "threads")
        _create_sqlite_db(data_dir / "workforce.db", "items")

        _run_reset(data_dir, tmp_path, soft=True)

        # Tier 1 targets: GONE
        assert not (data_dir / "scheduled_tasks.db").exists()
        assert not (data_dir / "events.db").exists()
        assert not list(cp_dir.glob("*.json"))

        # Tier 2 files: PRESERVED
        assert _db_has_data(data_dir / "trust.db", "trust_scores")
        assert _db_has_data(data_dir / "identity.db", "agents")
        assert _db_has_data(data_dir / "hebbian_weights.db", "weights")
        assert (data_dir / "session_last.json").exists()

        # Tier 3 files: PRESERVED
        assert _db_has_data(data_dir / "ward_room.db", "threads")
        assert _db_has_data(data_dir / "workforce.db", "items")


class TestTier2RecommissioningIntegration:
    """Tier 2: clears cognition + identity (cumulative with Tier 1), preserves records."""

    def test_clears_tier1_and_tier2_preserves_tier3(self, tmp_path):
        data_dir = tmp_path / "data"
        data_dir.mkdir()

        # Tier 1
        _create_sqlite_db(data_dir / "events.db", "events")

        # Tier 2 targets — ALL of these must be cleared
        for db_name in [
            "trust.db", "identity.db", "hebbian_weights.db",
            "cognitive_journal.db", "service_profiles.db",
            "acm.db", "skills.db", "directives.db", "assignments.db",
        ]:
            _create_sqlite_db(data_dir / db_name, "data")
        (data_dir / "session_last.json").write_text('{"ts": 1}')
        # chroma.sqlite3 (just a file for this test)
        (data_dir / "chroma.sqlite3").write_text("chroma data")
        # semantic dir
        sem_dir = data_dir / "semantic"
        sem_dir.mkdir()
        (sem_dir / "index.dat").write_text("index")

        # Tier 3 (should survive)
        _create_sqlite_db(data_dir / "ward_room.db", "threads")

        _run_reset(data_dir, tmp_path)  # default = Tier 2

        # Tier 1: GONE
        assert not (data_dir / "events.db").exists()

        # Tier 2: GONE
        for db_name in [
            "trust.db", "identity.db", "hebbian_weights.db",
            "cognitive_journal.db", "service_profiles.db",
            "acm.db", "skills.db", "directives.db", "assignments.db",
        ]:
            assert not (data_dir / db_name).exists(), f"{db_name} should be cleared"
        assert not (data_dir / "session_last.json").exists()
        assert not (data_dir / "chroma.sqlite3").exists()

        # Tier 3: PRESERVED
        assert _db_has_data(data_dir / "ward_room.db", "threads")


class TestTier3MaidenVoyageIntegration:
    """Tier 3: clears everything including institutional knowledge."""

    def test_clears_all_tiers(self, tmp_path):
        data_dir = tmp_path / "data"
        data_dir.mkdir()

        # Tier 1
        _create_sqlite_db(data_dir / "events.db", "events")

        # Tier 2
        _create_sqlite_db(data_dir / "trust.db", "data")
        _create_sqlite_db(data_dir / "identity.db", "data")
        _create_sqlite_db(data_dir / "assignments.db", "data")

        # Tier 3
        _create_sqlite_db(data_dir / "ward_room.db", "threads")
        _create_sqlite_db(data_dir / "workforce.db", "items")
        records_dir = data_dir / "ship-records"
        records_dir.mkdir()
        (records_dir / "log.md").write_text("captain's log")

        _run_reset(data_dir, tmp_path, full=True)

        # ALL tiers: GONE
        assert not (data_dir / "events.db").exists()
        assert not (data_dir / "trust.db").exists()
        assert not (data_dir / "identity.db").exists()
        assert not (data_dir / "assignments.db").exists()
        assert not (data_dir / "ward_room.db").exists()
        assert not (data_dir / "workforce.db").exists()
        # ship-records dir should be cleared
        assert not records_dir.exists() or not list(records_dir.iterdir())

    def test_archives_ward_room_before_clearing(self, tmp_path):
        """Tier 3 archives ward_room.db before deletion (archive_first)."""
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        _create_sqlite_db(data_dir / "ward_room.db", "threads")

        _run_reset(data_dir, tmp_path, full=True)

        assert not (data_dir / "ward_room.db").exists()
        archive_dir = data_dir / "archives"
        assert archive_dir.exists()
        archives = list(archive_dir.glob("ward_room_*.db"))
        assert len(archives) == 1


class TestResetInvariants:
    """Cross-tier invariants that must always hold."""

    def test_archives_never_cleared(self, tmp_path):
        """Archives directory survives all tiers."""
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        archive_dir = data_dir / "archives"
        archive_dir.mkdir()
        (archive_dir / "old_backup.db").write_text("preserved")

        _run_reset(data_dir, tmp_path, full=True)

        assert (archive_dir / "old_backup.db").exists()

    def test_idempotent_reset(self, tmp_path):
        """Running reset twice doesn't crash on missing files."""
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        _create_sqlite_db(data_dir / "trust.db", "data")

        _run_reset(data_dir, tmp_path)
        # Second reset on empty dir — should not crash
        _run_reset(data_dir, tmp_path)

    def test_assignments_db_in_tier2(self):
        """Verify assignments.db is declared in Tier 2 of RESET_TIERS."""
        from probos.__main__ import RESET_TIERS
        tier2_files = RESET_TIERS[2]["files"]
        assert "assignments.db" in tier2_files, (
            "assignments.db must be in Tier 2 — it stores assignment state "
            "which should be cleared on recommissioning"
        )
