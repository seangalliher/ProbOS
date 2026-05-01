"""AD-468: Runtime Configuration Service tests."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from probos.events import EventType
from probos.runtime_config_service import (
    OVERRIDABLE_FIELDS,
    OverrideSpec,
    RuntimeConfigService,
)


def test_event_type_config_changed_exists() -> None:
    assert EventType.CONFIG_CHANGED.value == "config_changed"


def test_overridable_fields_known() -> None:
    expected = {
        "proactive.interval",
        "proactive.cooldown",
        "dreaming.interval",
        "telemetry.report_interval",
    }
    assert expected.issubset(set(OVERRIDABLE_FIELDS.keys()))
    for spec in OVERRIDABLE_FIELDS.values():
        assert isinstance(spec, OverrideSpec)


def test_set_override_persists_to_disk(tmp_path: Path) -> None:
    rcs = RuntimeConfigService(store_path=tmp_path / "ov.json")
    ok, _ = rcs.set("proactive.interval", 60.0)
    assert ok is True
    assert (tmp_path / "ov.json").exists()
    rcs2 = RuntimeConfigService(store_path=tmp_path / "ov.json")
    assert rcs2.get("proactive.interval") == 60.0


def test_set_override_validates_min(tmp_path: Path) -> None:
    rcs = RuntimeConfigService(store_path=tmp_path / "ov.json")
    ok, reason = rcs.set("proactive.interval", 5.0)
    assert ok is False
    assert "below min" in reason


def test_set_override_validates_max(tmp_path: Path) -> None:
    rcs = RuntimeConfigService(store_path=tmp_path / "ov.json")
    ok, reason = rcs.set("proactive.interval", 99999.0)
    assert ok is False
    assert "above max" in reason


def test_set_override_unknown_field_rejected(tmp_path: Path) -> None:
    rcs = RuntimeConfigService(store_path=tmp_path / "ov.json")
    ok, reason = rcs.set("foo", 1)
    assert ok is False
    assert "unknown field: foo" in reason


def test_clear_removes_override(tmp_path: Path) -> None:
    rcs = RuntimeConfigService(store_path=tmp_path / "ov.json")
    rcs.set("proactive.interval", 60.0)
    cleared = rcs.clear("proactive.interval")
    assert cleared is True
    assert rcs.get("proactive.interval") is None


def test_clear_unknown_returns_false(tmp_path: Path) -> None:
    rcs = RuntimeConfigService(store_path=tmp_path / "ov.json")
    assert rcs.clear("never-set") is False


def test_get_unset_returns_none(tmp_path: Path) -> None:
    rcs = RuntimeConfigService(store_path=tmp_path / "ov.json")
    assert rcs.get("anything") is None
    assert rcs.all() == {}


def test_listener_fires_on_set(tmp_path: Path) -> None:
    rcs = RuntimeConfigService(store_path=tmp_path / "ov.json")
    calls: list[tuple[str, Any]] = []
    rcs.add_listener(lambda fid, val: calls.append((fid, val)))
    rcs.set("proactive.interval", 60.0)
    assert len(calls) == 1
    assert calls[0] == ("proactive.interval", 60.0)


def test_emit_event_on_set(tmp_path: Path) -> None:
    emitted: list[tuple[Any, dict[str, Any]]] = []
    rcs = RuntimeConfigService(
        store_path=tmp_path / "ov.json",
        emit_event=lambda et, data: emitted.append((et, data)),
    )
    rcs.set("proactive.interval", 60.0)
    assert len(emitted) == 1
    assert emitted[0][0] == EventType.CONFIG_CHANGED
    assert emitted[0][1]["field_id"] == "proactive.interval"
    assert emitted[0][1]["value"] == 60.0


def test_load_existing_file(tmp_path: Path) -> None:
    p = tmp_path / "ov.json"
    p.write_text(
        json.dumps({"overrides": {"proactive.interval": 90.0}}),
        encoding="utf-8",
    )
    rcs = RuntimeConfigService(store_path=p)
    assert rcs.get("proactive.interval") == 90.0


def test_coerce_string_to_float(tmp_path: Path) -> None:
    rcs = RuntimeConfigService(store_path=tmp_path / "ov.json")
    ok, _ = rcs.set("proactive.interval", "60.0")
    assert ok is True
    assert rcs.get("proactive.interval") == 60.0


def test_runtime_overrides_config_defaults() -> None:
    from probos.config import RuntimeOverridesConfig
    cfg = RuntimeOverridesConfig()
    assert cfg.enabled is True
    assert cfg.store_filename == "runtime_overrides.json"
