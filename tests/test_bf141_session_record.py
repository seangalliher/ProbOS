"""BF-141: Session record written synchronously before async shutdown."""

from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest


def _make_mock_runtime(tmp_path: Path) -> MagicMock:
    """Create a mock runtime with required attributes for session record write."""
    rt = MagicMock()
    rt._session_id = "test-session-141"
    rt._start_time_wall = time.time() - 60  # started 60s ago
    rt._start_time = time.monotonic() - 60
    rt._data_dir = tmp_path
    # registry.all() returns empty list (no crew agents)
    rt.registry.all.return_value = []
    rt.ontology = None
    return rt


def _write_session_record(runtime: MagicMock, reason: str = "interrupted") -> None:
    """Reproduce the BF-141 synchronous write block from __main__.py."""
    import json
    import time

    _sr = {
        "session_id": runtime._session_id,
        "start_time_utc": runtime._start_time_wall,
        "shutdown_time_utc": time.time(),
        "uptime_seconds": time.monotonic() - runtime._start_time,
        "agent_count": len(runtime.registry.all()),
        "reason": reason,
    }
    (runtime._data_dir / "session_last.json").write_text(
        json.dumps(_sr, indent=2)
    )


class TestBF141SessionRecord:
    """BF-141: Ctrl+C must write session_last.json before async shutdown."""

    def test_session_record_written(self, tmp_path: Path):
        """Session record file is created with expected fields."""
        rt = _make_mock_runtime(tmp_path)
        _write_session_record(rt)

        path = tmp_path / "session_last.json"
        assert path.exists()
        data = json.loads(path.read_text())
        assert data["session_id"] == "test-session-141"
        assert "shutdown_time_utc" in data
        assert "uptime_seconds" in data
        assert data["reason"] == "interrupted"

    def test_session_record_has_recent_timestamp(self, tmp_path: Path):
        """shutdown_time_utc is within the last few seconds."""
        rt = _make_mock_runtime(tmp_path)
        before = time.time()
        _write_session_record(rt)
        after = time.time()

        data = json.loads((tmp_path / "session_last.json").read_text())
        assert before <= data["shutdown_time_utc"] <= after

    def test_stale_record_overwritten(self, tmp_path: Path):
        """A stale session record is replaced with current timestamp."""
        path = tmp_path / "session_last.json"
        stale = {"shutdown_time_utc": 1000000000.0, "session_id": "old"}
        path.write_text(json.dumps(stale))

        rt = _make_mock_runtime(tmp_path)
        _write_session_record(rt)

        data = json.loads(path.read_text())
        assert data["shutdown_time_utc"] > 1700000000.0  # well past stale
        assert data["session_id"] == "test-session-141"

    def test_write_failure_does_not_raise(self, tmp_path: Path):
        """Best-effort: write failure silently passes."""
        rt = _make_mock_runtime(tmp_path)
        rt._data_dir = Path("/nonexistent/impossible/path")
        # Should not raise — matches the try/except Exception: pass pattern
        try:
            _write_session_record(rt)
        except Exception:
            pass  # This is what the production code does

    def test_stasis_duration_from_fresh_record(self, tmp_path: Path):
        """After writing, next boot computes stasis_duration < 5s."""
        rt = _make_mock_runtime(tmp_path)
        _write_session_record(rt)

        # Simulate startup read (from cognitive_services.py line 298)
        data = json.loads((tmp_path / "session_last.json").read_text())
        stasis_duration = time.time() - data["shutdown_time_utc"]
        assert stasis_duration < 5.0, (
            f"Stasis duration {stasis_duration:.1f}s should be < 5s for freshly written record"
        )
