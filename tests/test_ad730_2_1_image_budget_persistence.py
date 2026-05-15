"""AD-730-2-1 tests: persistence of the per-Captain daily image budget tracker."""

from __future__ import annotations

import json
import logging
import time
from collections import deque
from pathlib import Path

import pytest

from probos.attachments.image_budget_store import load, save
from probos.attachments.image_policy import ImagePolicyEnforcer


class _FakeCfg:
    daily_image_budget_per_captain = 50
    images_per_dm_hard_cap = 0
    image_max_dimension = 0


class _FakeRuntime:
    def __init__(self, path: Path) -> None:
        self._image_budget_path = path
        self.image_budget_tracker: dict[str, deque] = {}


def test_load_missing_file_returns_empty(tmp_path: Path) -> None:
    target = tmp_path / "missing.json"
    result = load(target)
    assert result == {}
    assert not target.exists()


def test_save_then_load_roundtrip(tmp_path: Path) -> None:
    target = tmp_path / "ib.json"
    tracker: dict[str, deque] = {
        "captain_a": deque([(100.0, 1), (200.0, 2), (300.0, 3)]),
    }
    save(target, tracker)
    assert target.exists()

    loaded = load(target)
    assert set(loaded.keys()) == {"captain_a"}
    assert list(loaded["captain_a"]) == [(100.0, 1), (200.0, 2), (300.0, 3)]


def test_save_skips_empty_deques(tmp_path: Path) -> None:
    target = tmp_path / "ib.json"
    tracker: dict[str, deque] = {
        "captain_a": deque([(100.0, 2)]),
        "captain_b": deque(),
    }
    save(target, tracker)

    raw = json.loads(target.read_text(encoding="utf-8"))
    assert set(raw.keys()) == {"captain_a"}
    assert raw["captain_a"] == [[100.0, 2]]


def test_corrupt_file_loads_empty(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    target = tmp_path / "ib.json"
    target.write_text("not json", encoding="utf-8")
    with caplog.at_level(logging.WARNING):
        result = load(target)
    assert result == {}
    assert any("AD-730-2-1" in r.message for r in caplog.records)


def test_enforcer_persists_on_append_and_prune(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "ib.json"
    runtime = _FakeRuntime(path)
    enforcer = ImagePolicyEnforcer(runtime, _FakeCfg())

    t0 = 1_700_000_000.0
    monkeypatch.setattr(time, "time", lambda: t0)
    enforcer.check_budget("captain_x", 1)

    assert path.exists()
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert "captain_x" in raw
    assert len(raw["captain_x"]) == 1
    assert raw["captain_x"][0][1] == 1

    # Jump 25h forward so prior entry is outside the 24h window.
    monkeypatch.setattr(time, "time", lambda: t0 + 25 * 3600)
    enforcer.check_budget("captain_x", 1)

    raw2 = json.loads(path.read_text(encoding="utf-8"))
    # Only the new entry should remain.
    assert "captain_x" in raw2
    assert len(raw2["captain_x"]) == 1
    assert raw2["captain_x"][0][0] == pytest.approx(t0 + 25 * 3600)
