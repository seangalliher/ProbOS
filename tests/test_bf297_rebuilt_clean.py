"""BF-297: `consolidation_result="rebuilt"` must be treated as clean shutdown."""
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from probos.shutdown_integrity import (
    STATUS_FILENAME,
    UncleanShutdownDetected,
    check_previous_shutdown,
    mark_clean_shutdown,
    read_shutdown_status,
)


def test_mark_clean_shutdown_rebuilt_writes_status_clean(tmp_path):
    """BF-297: writer side — consolidation_result=rebuilt must produce status=clean."""
    mark_clean_shutdown(tmp_path, consolidation_result="rebuilt", note="AD-819 rebuild")
    payload = json.loads((tmp_path / STATUS_FILENAME).read_text())
    assert payload["status"] == "clean", (
        f"BF-297: status should be clean when consolidation=rebuilt, got {payload['status']}"
    )
    assert payload["consolidation_result"] == "rebuilt"


def test_check_previous_shutdown_accepts_rebuilt_marker(tmp_path):
    """BF-297: reader side — a marker with consolidation=rebuilt boots cleanly."""
    mark_clean_shutdown(tmp_path, consolidation_result="rebuilt")
    # Should NOT raise
    check_previous_shutdown(tmp_path)


def test_check_previous_shutdown_accepts_legacy_partial_rebuilt_marker(tmp_path):
    """BF-297 defensive: a legacy marker (status=partial, consolidation=rebuilt)
    from pre-fix BF-288 should still boot cleanly so operators don't have to
    delete their marker file by hand."""
    # Simulate a marker written by pre-BF-297 code
    legacy = {
        "status": "partial",  # buggy writer set this
        "last_shutdown_at": time.time(),
        "consolidation_result": "rebuilt",
        "version": "",
        "note": "AD-819 rebuild",
    }
    (tmp_path / STATUS_FILENAME).write_text(json.dumps(legacy))
    # Should NOT raise
    check_previous_shutdown(tmp_path)


def test_check_previous_shutdown_still_rejects_failed(tmp_path):
    """BF-297 regression: consolidation_result=failed must still block boot."""
    legacy = {
        "status": "partial",
        "last_shutdown_at": time.time(),
        "consolidation_result": "failed",
        "version": "",
        "note": "phase1_elapsed=8.9s",
    }
    (tmp_path / STATUS_FILENAME).write_text(json.dumps(legacy))
    with pytest.raises(UncleanShutdownDetected):
        check_previous_shutdown(tmp_path)
