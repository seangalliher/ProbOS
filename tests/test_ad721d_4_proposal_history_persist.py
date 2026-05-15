"""AD-721d-4 tests: per-agent proposal history JSON sidecar persistence."""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from probos.avatars import proposal_history


@pytest.fixture(autouse=True)
def _isolate_proposal_history():
    yield
    proposal_history.reset_all()
    proposal_history.configure(None)


def test_configure_with_no_existing_file_starts_empty(tmp_path: Path) -> None:
    target = tmp_path / "missing.json"
    proposal_history.configure(target)
    assert proposal_history.iteration_count("ezri") == 0
    assert not target.exists()


def test_append_persists_to_disk(tmp_path: Path) -> None:
    target = tmp_path / "ph.json"
    proposal_history.configure(target)
    proposal_history.append("ezri", {"name": "X"}, "note")

    assert target.exists()
    raw = json.loads(target.read_text(encoding="utf-8"))
    assert "ezri" in raw
    assert len(raw["ezri"]) == 1
    assert raw["ezri"][0]["dsl"] == {"name": "X"}
    assert raw["ezri"][0]["captain_note"] == "note"


def test_load_roundtrips_existing_state(tmp_path: Path) -> None:
    target = tmp_path / "ph.json"
    payload = {
        "ezri": [
            {"dsl": {"name": "first"}, "captain_note": "first-note", "timestamp": 100.0},
            {"dsl": {"name": "second"}, "captain_note": "second-note", "timestamp": 200.0},
        ]
    }
    target.write_text(json.dumps(payload), encoding="utf-8")
    proposal_history.configure(target)

    assert proposal_history.iteration_count("ezri") == 2
    latest = proposal_history.latest("ezri")
    assert latest is not None
    assert latest.captain_note == "second-note"
    assert latest.dsl == {"name": "second"}


def test_clear_persists_removal(tmp_path: Path) -> None:
    target = tmp_path / "ph.json"
    proposal_history.configure(target)
    proposal_history.append("ezri", {"name": "X"}, "n")
    proposal_history.clear("ezri")

    # Re-configure to reload from disk.
    proposal_history.configure(target)
    assert proposal_history.iteration_count("ezri") == 0


def test_malformed_disk_state_loads_empty_and_logs(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    target = tmp_path / "ph.json"
    target.write_text("not json", encoding="utf-8")
    with caplog.at_level(logging.WARNING):
        proposal_history.configure(target)
    assert proposal_history.iteration_count("anything") == 0
    assert any("AD-721d-4" in r.message for r in caplog.records)
