"""AD-819: rebuild-episodic — ward room → ChromaDB tests.

These tests exercise the synthesis + dispatch logic without spinning up
a real ChromaDB. ``store_episode`` is a stub that captures calls; the
asserts verify the rebuilder produces the right episode shape and is
idempotent.
"""
from __future__ import annotations

import sqlite3
import time
from pathlib import Path

import pytest

from probos.maintenance.rebuild_episodic import (
    RebuildReport,
    _row_to_episode_kwargs,
    _stable_episode_id,
    rebuild_from_wardroom,
    render_report,
)


def _build_wardroom_fixture(path: Path) -> None:
    """Create a minimal ward_room.db with the columns the rebuilder uses."""
    conn = sqlite3.connect(str(path))
    try:
        conn.executescript(
            """
            CREATE TABLE channels (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                created_by TEXT NOT NULL,
                created_at REAL NOT NULL,
                archived INTEGER NOT NULL DEFAULT 0,
                description TEXT NOT NULL DEFAULT ''
            );
            CREATE TABLE threads (
                id TEXT PRIMARY KEY,
                channel_id TEXT NOT NULL,
                author_id TEXT NOT NULL,
                title TEXT NOT NULL,
                body TEXT NOT NULL,
                created_at REAL NOT NULL,
                last_activity REAL NOT NULL,
                pinned INTEGER NOT NULL DEFAULT 0,
                locked INTEGER NOT NULL DEFAULT 0,
                thread_mode TEXT NOT NULL DEFAULT 'discuss',
                max_responders INTEGER NOT NULL DEFAULT 0,
                reply_count INTEGER NOT NULL DEFAULT 0,
                net_score INTEGER NOT NULL DEFAULT 0,
                author_callsign TEXT NOT NULL DEFAULT '',
                channel_name TEXT NOT NULL DEFAULT ''
            );
            CREATE TABLE posts (
                id TEXT PRIMARY KEY,
                thread_id TEXT NOT NULL,
                parent_id TEXT,
                author_id TEXT NOT NULL,
                body TEXT NOT NULL,
                created_at REAL NOT NULL,
                edited_at REAL,
                deleted INTEGER NOT NULL DEFAULT 0,
                delete_reason TEXT NOT NULL DEFAULT '',
                deleted_by TEXT NOT NULL DEFAULT '',
                net_score INTEGER NOT NULL DEFAULT 0,
                author_callsign TEXT NOT NULL DEFAULT ''
            );
            """
        )
        # 2 threads
        conn.execute(
            "INSERT INTO threads VALUES "
            "('t1','bridge','agent-A','Status report','Day shift baseline ok',"
            "1000.0,1000.0,0,0,'discuss',0,0,0,'Reed','#bridge')"
        )
        conn.execute(
            "INSERT INTO threads VALUES "
            "('t2','medical','agent-B','Wellness watch','Tracking Atlas',"
            "2000.0,2000.0,0,0,'discuss',0,0,0,'Troi','#medical')"
        )
        # 3 posts (2 live, 1 deleted)
        conn.execute(
            "INSERT INTO posts VALUES "
            "('p1','t1',NULL,'agent-C','acknowledged',1010.0,NULL,0,'','',0,'Worf')"
        )
        conn.execute(
            "INSERT INTO posts VALUES "
            "('p2','t1','p1','agent-A','thanks',1020.0,NULL,0,'','',0,'Reed')"
        )
        conn.execute(
            "INSERT INTO posts VALUES "
            "('p3','t2',NULL,'agent-D','retracted',2010.0,NULL,1,'','',0,'')"
        )
        conn.commit()
    finally:
        conn.close()


# ---------------- stable id ----------------


def test_stable_episode_id_deterministic():
    a = _stable_episode_id(source="x", source_id="abc")
    b = _stable_episode_id(source="x", source_id="abc")
    assert a == b
    assert len(a) == 32


def test_stable_episode_id_differs_across_inputs():
    assert _stable_episode_id(source="x", source_id="abc") != _stable_episode_id(
        source="x", source_id="def"
    )
    assert _stable_episode_id(source="x", source_id="abc") != _stable_episode_id(
        source="y", source_id="abc"
    )


# ---------------- row → kwargs ----------------


def test_thread_row_synthesizes_episode():
    row = {
        "id": "t1",
        "channel_id": "bridge",
        "author_id": "agent-A",
        "title": "Status",
        "body": "All systems green",
        "created_at": 1000.0,
        "channel_name": "#bridge",
        "author_callsign": "Reed",
    }
    kwargs = _row_to_episode_kwargs("thread", row)
    assert kwargs["timestamp"] == 1000.0
    assert "Status" in kwargs["user_input"]
    assert "All systems green" in kwargs["user_input"]
    assert kwargs["agent_ids"] == ["agent-A"]
    assert kwargs["source"] == "wardroom_import"
    assert kwargs["dag_summary"]["rebuild_source"] == "wardroom_thread"
    assert kwargs["dag_summary"]["thread_id"] == "t1"
    assert kwargs["dag_summary"]["channel"] == "#bridge"


def test_post_row_synthesizes_episode():
    row = {
        "id": "p1",
        "thread_id": "t1",
        "parent_id": None,
        "author_id": "agent-C",
        "body": "ack",
        "created_at": 1010.0,
        "author_callsign": "Worf",
    }
    kwargs = _row_to_episode_kwargs("post", row)
    assert kwargs["timestamp"] == 1010.0
    assert kwargs["user_input"] == "ack"
    assert kwargs["agent_ids"] == ["agent-C"]
    assert kwargs["dag_summary"]["rebuild_source"] == "wardroom_post"
    assert kwargs["dag_summary"]["thread_id"] == "t1"


def test_thread_row_title_only_no_body():
    row = {
        "id": "tx",
        "channel_id": "ops",
        "author_id": "a",
        "title": "Brief",
        "body": "",
        "created_at": 1.0,
        "channel_name": "",
        "author_callsign": "",
    }
    kwargs = _row_to_episode_kwargs("thread", row)
    assert kwargs["user_input"] == "Brief"


# ---------------- rebuild flow ----------------


@pytest.mark.asyncio
async def test_rebuild_writes_threads_and_posts_in_order(tmp_path):
    db = tmp_path / "ward_room.db"
    _build_wardroom_fixture(db)

    captured: list[dict] = []

    async def _stub_store(kwargs: dict) -> None:
        captured.append(kwargs)

    report = await rebuild_from_wardroom(
        wardroom_db=db,
        store_episode=_stub_store,
        progress_every=0,
    )
    assert isinstance(report, RebuildReport)
    # 2 threads + 2 live posts (deleted post skipped by SQL WHERE)
    assert report.rows_scanned == 4
    assert report.episodes_written == 4
    # The two threads are dispatched before any post (we iterate threads first)
    sources = [e["dag_summary"]["rebuild_source"] for e in captured]
    assert sources[:2] == ["wardroom_thread", "wardroom_thread"]
    assert sources[2:] == ["wardroom_post", "wardroom_post"]


@pytest.mark.asyncio
async def test_rebuild_skips_existing_episode_ids(tmp_path):
    db = tmp_path / "ward_room.db"
    _build_wardroom_fixture(db)

    # Compute the stable id for thread t1 and put it in the existing set.
    existing = {_stable_episode_id(source="wardroom_rebuild_thread", source_id="t1")}

    captured: list[dict] = []

    async def _stub_store(kwargs: dict) -> None:
        captured.append(kwargs)

    report = await rebuild_from_wardroom(
        wardroom_db=db,
        store_episode=_stub_store,
        existing_episode_ids=existing,
        progress_every=0,
    )
    assert report.rows_skipped_existing == 1
    assert report.episodes_written == 3  # t2 + p1 + p2
    captured_ids = [e["dag_summary"]["thread_id"] for e in captured]
    # t1 should NOT be in the captured threads
    assert "t1" not in {
        e["dag_summary"]["thread_id"]
        for e in captured
        if e["dag_summary"]["rebuild_source"] == "wardroom_thread"
    }


@pytest.mark.asyncio
async def test_rebuild_dry_run_invokes_no_store(tmp_path):
    db = tmp_path / "ward_room.db"
    _build_wardroom_fixture(db)

    calls = 0

    async def _stub_store(kwargs: dict) -> None:
        nonlocal calls
        calls += 1

    report = await rebuild_from_wardroom(
        wardroom_db=db,
        store_episode=_stub_store,
        dry_run=True,
        progress_every=0,
    )
    assert calls == 0
    assert report.dry_run is True
    assert report.episodes_written == 4


@pytest.mark.asyncio
async def test_rebuild_since_filter(tmp_path):
    db = tmp_path / "ward_room.db"
    _build_wardroom_fixture(db)

    async def _stub_store(kwargs: dict) -> None:
        pass

    # Only rows with created_at >= 1500 (skips t1, p1, p2)
    report = await rebuild_from_wardroom(
        wardroom_db=db,
        store_episode=_stub_store,
        since_ts=1500.0,
        progress_every=0,
    )
    assert report.rows_scanned == 1  # only t2 survives (p3 is deleted)
    assert report.episodes_written == 1


@pytest.mark.asyncio
async def test_rebuild_missing_db_returns_error_report(tmp_path):
    async def _stub_store(kwargs: dict) -> None:
        pass

    report = await rebuild_from_wardroom(
        wardroom_db=tmp_path / "does_not_exist.db",
        store_episode=_stub_store,
    )
    assert report.errors
    assert "not found" in report.errors[0]


@pytest.mark.asyncio
async def test_rebuild_skips_empty_body_post(tmp_path):
    db = tmp_path / "ward_room.db"
    _build_wardroom_fixture(db)
    # Append a post with empty body
    conn = sqlite3.connect(str(db))
    conn.execute(
        "INSERT INTO posts VALUES "
        "('p4','t1',NULL,'agent-E','   ',1500.0,NULL,0,'','',0,'X')"
    )
    conn.commit()
    conn.close()

    captured: list[dict] = []

    async def _stub_store(kwargs: dict) -> None:
        captured.append(kwargs)

    report = await rebuild_from_wardroom(
        wardroom_db=db,
        store_episode=_stub_store,
        progress_every=0,
    )
    # 2 threads + 3 live posts scanned, but p4 has empty body → skipped
    assert report.rows_scanned == 5
    assert report.rows_skipped_filtered == 1
    assert report.episodes_written == 4


@pytest.mark.asyncio
async def test_rebuild_records_store_errors(tmp_path):
    db = tmp_path / "ward_room.db"
    _build_wardroom_fixture(db)

    async def _failing_store(kwargs: dict) -> None:
        raise RuntimeError(f"chroma down at {kwargs['id']}")

    report = await rebuild_from_wardroom(
        wardroom_db=db,
        store_episode=_failing_store,
        progress_every=0,
    )
    assert report.episodes_written == 0
    assert len(report.errors) == 4


def test_render_report_human_readable():
    report = RebuildReport(
        source="wardroom",
        dry_run=False,
        rows_scanned=100,
        rows_skipped_existing=20,
        rows_skipped_filtered=5,
        episodes_written=75,
    )
    out = render_report(report)
    assert "wardroom" in out
    assert "100" in out
    assert "75" in out
    assert "20" in out


def test_render_report_with_errors_truncates_list():
    report = RebuildReport(
        source="wardroom",
        dry_run=False,
        rows_scanned=10,
        errors=[f"err {i}" for i in range(20)],
    )
    out = render_report(report)
    assert "errors:" in out
    assert "and 15 more" in out


class TestShutdownMarkerReset:
    """BF-288: successful rebuild must reset AD-820 shutdown_status.json."""

    def test_successful_rebuild_resets_marker(self, tmp_path, monkeypatch):
        """After a successful rebuild, marker should reflect consolidation_result='rebuilt'."""
        import argparse
        import json as _json
        from probos.__main__ import _cmd_rebuild_episodic
        from probos.shutdown_integrity import mark_dirty_shutdown, STATUS_FILENAME

        data_dir = tmp_path / "data"
        data_dir.mkdir()
        _build_wardroom_fixture(data_dir / "ward_room.db")

        # Simulate the pre-rebuild state: previous shutdown was dirty.
        mark_dirty_shutdown(
            data_dir,
            consolidation_result="failed",
            note="simulated #750 crash",
        )
        marker = data_dir / STATUS_FILENAME
        assert _json.loads(marker.read_text())["consolidation_result"] == "failed"

        # Monkeypatch rebuild_from_wardroom to return a synthetic success
        # report so the test does not require ChromaDB cold-start.
        async def _fake_rebuild(**kwargs):
            return RebuildReport(
                source="wardroom",
                dry_run=False,
                rows_scanned=10,
                episodes_written=10,
                errors=[],
            )

        # The handler imports rebuild_from_wardroom inside _run, so patch
        # at the source module.
        import probos.maintenance.rebuild_episodic as _rebuild_mod
        monkeypatch.setattr(_rebuild_mod, "rebuild_from_wardroom", _fake_rebuild)

        # Also stub EpisodicMemory so we don't touch ChromaDB.
        import probos.cognitive.episodic as _ep_mod

        class _FakeEM:
            def __init__(self, *a, **kw):
                self._collection = None

            async def start(self):
                return None

            async def stop(self):
                return None

            async def store(self, _ep):
                return None

        monkeypatch.setattr(_ep_mod, "EpisodicMemory", _FakeEM)

        args = argparse.Namespace(
            data_dir=data_dir,
            config=None,
            since=None,
            dry_run=False,
        )
        rc = _cmd_rebuild_episodic(args)
        assert rc == 0

        payload = _json.loads(marker.read_text())
        assert payload["consolidation_result"] == "rebuilt"
        # mark_clean_shutdown writes status="partial" for any
        # consolidation_result != "full". AD-820's boot gate only blocks
        # on consolidation_result=="failed", so "rebuilt" boots.
        assert payload["status"] in ("clean", "partial")
        assert "rebuild" in payload.get("note", "").lower()

    def test_dry_run_does_not_touch_marker(self, tmp_path):
        """Dry-run must NOT reset the marker (no real recovery happened)."""
        import argparse
        import json as _json
        from probos.__main__ import _cmd_rebuild_episodic
        from probos.shutdown_integrity import mark_dirty_shutdown, STATUS_FILENAME

        data_dir = tmp_path / "data"
        data_dir.mkdir()
        _build_wardroom_fixture(data_dir / "ward_room.db")
        mark_dirty_shutdown(
            data_dir,
            consolidation_result="failed",
            note="simulated #750 crash",
        )

        args = argparse.Namespace(
            data_dir=data_dir,
            config=None,
            since=None,
            dry_run=True,
        )
        rc = _cmd_rebuild_episodic(args)
        assert rc == 0

        payload = _json.loads((data_dir / STATUS_FILENAME).read_text())
        assert payload["consolidation_result"] == "failed"
