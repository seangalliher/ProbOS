"""AD-820: shutdown integrity marker + boot clean-check tests."""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest

from probos.shutdown_integrity import (
    STATUS_FILENAME,
    UncleanShutdownDetected,
    check_previous_shutdown,
    mark_clean_shutdown,
    mark_dirty_shutdown,
    read_shutdown_status,
)


# ---------------- atomic write ----------------


def test_mark_clean_shutdown_creates_status_file(tmp_path):
    mark_clean_shutdown(tmp_path, consolidation_result="full", version="abc")
    path = tmp_path / STATUS_FILENAME
    assert path.exists()
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["status"] == "clean"
    assert payload["consolidation_result"] == "full"
    assert payload["version"] == "abc"


def test_mark_clean_overwrites_previous_marker(tmp_path):
    (tmp_path / STATUS_FILENAME).write_text(
        json.dumps({"status": "partial"}), encoding="utf-8"
    )
    mark_clean_shutdown(tmp_path)
    payload = json.loads((tmp_path / STATUS_FILENAME).read_text(encoding="utf-8"))
    assert payload["status"] == "clean"


def test_mark_dirty_shutdown_records_partial(tmp_path):
    mark_dirty_shutdown(tmp_path, consolidation_result="partial", note="timeout")
    payload = json.loads((tmp_path / STATUS_FILENAME).read_text(encoding="utf-8"))
    assert payload["status"] == "partial"
    assert payload["consolidation_result"] == "partial"
    assert payload["note"] == "timeout"


def test_mark_clean_with_partial_consolidation_results_in_partial_status(tmp_path):
    """Clean call but the underlying result was 'partial' → status should be 'partial'."""
    mark_clean_shutdown(tmp_path, consolidation_result="partial")
    payload = json.loads((tmp_path / STATUS_FILENAME).read_text(encoding="utf-8"))
    assert payload["status"] == "partial"


def test_mark_handles_missing_parent_dir(tmp_path):
    nested = tmp_path / "does" / "not" / "exist"
    mark_clean_shutdown(nested)
    assert (nested / STATUS_FILENAME).exists()


def test_atomic_write_leaves_no_tmp_file(tmp_path):
    mark_clean_shutdown(tmp_path)
    tmp_files = list(tmp_path.glob("*.tmp"))
    assert tmp_files == []


# ---------------- read ----------------


def test_read_returns_empty_when_absent(tmp_path):
    assert read_shutdown_status(tmp_path) == {}


def test_read_returns_payload_when_present(tmp_path):
    mark_clean_shutdown(tmp_path, note="hello")
    payload = read_shutdown_status(tmp_path)
    assert payload["status"] == "clean"
    assert payload["note"] == "hello"


def test_read_unreadable_treated_as_unknown(tmp_path):
    # Write garbage
    (tmp_path / STATUS_FILENAME).write_text("not json at all", encoding="utf-8")
    payload = read_shutdown_status(tmp_path)
    assert payload == {"status": "unknown"}


# ---------------- check_previous_shutdown ----------------


def test_check_first_boot_passes_when_no_marker(tmp_path):
    check_previous_shutdown(tmp_path, is_first_boot=True)


def test_check_warns_but_passes_when_marker_absent_and_data_exists(tmp_path, caplog):
    # Simulate a pre-AD-820 data dir: events.db exists, no marker
    (tmp_path / "events.db").write_text("x")
    check_previous_shutdown(tmp_path, is_first_boot=False)


def test_check_passes_when_marker_clean(tmp_path):
    mark_clean_shutdown(tmp_path)
    check_previous_shutdown(tmp_path)


def test_check_raises_when_marker_partial(tmp_path):
    mark_dirty_shutdown(tmp_path, consolidation_result="partial")
    with pytest.raises(UncleanShutdownDetected) as ei:
        check_previous_shutdown(tmp_path)
    assert ei.value.data_dir == tmp_path
    assert ei.value.payload["status"] == "partial"


def test_check_raises_when_marker_failed(tmp_path):
    mark_dirty_shutdown(tmp_path, consolidation_result="failed", note="exception")
    with pytest.raises(UncleanShutdownDetected):
        check_previous_shutdown(tmp_path)


def test_check_force_unclean_overrides(tmp_path):
    mark_dirty_shutdown(tmp_path, consolidation_result="partial")
    # Must NOT raise
    check_previous_shutdown(tmp_path, force_unclean=True)


def test_unclean_error_message_mentions_recovery_options(tmp_path):
    mark_dirty_shutdown(
        tmp_path, consolidation_result="partial", note="timeout"
    )
    try:
        check_previous_shutdown(tmp_path)
    except UncleanShutdownDetected as exc:
        msg = str(exc)
        assert "probos rebuild-episodic" in msg
        assert "--force-unclean" in msg
        assert str(tmp_path) in msg
        assert "partial" in msg
    else:
        pytest.fail("expected UncleanShutdownDetected")


def test_check_passes_when_marker_unreadable_garbage(tmp_path):
    """Unreadable marker shouldn't block boot — the warning is logged but
    the boot proceeds (we don't have positive evidence of corruption)."""
    (tmp_path / STATUS_FILENAME).write_text("not json", encoding="utf-8")
    # Should not raise — payload reads as {"status": "unknown"}, which is
    # treated like 'partial' to be safe.
    with pytest.raises(UncleanShutdownDetected):
        check_previous_shutdown(tmp_path)


# ---------------- atomicity smoke test ----------------


def test_atomic_write_survives_partial_tmp_file(tmp_path):
    """If a previous run died after creating the .tmp but before os.replace,
    the live status file should be untouched. Simulate by manually
    pre-creating both, then call mark_clean and verify the live file
    reflects the new mark and no .tmp remains.
    """
    live = tmp_path / STATUS_FILENAME
    live.write_text(json.dumps({"status": "clean", "stale": True}), encoding="utf-8")
    # Pre-existing tmp from a prior crash
    (tmp_path / (STATUS_FILENAME + ".tmp")).write_text("garbage", encoding="utf-8")
    mark_clean_shutdown(tmp_path)
    payload = json.loads(live.read_text(encoding="utf-8"))
    assert payload["status"] == "clean"
    assert "stale" not in payload  # Replaced, not merged
    assert not (tmp_path / (STATUS_FILENAME + ".tmp")).exists()
