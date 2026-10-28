"""AD-1270 (#1324) slice 4c, M1: the AD-509 boot-camp phase tracker is deleted, not wired.

Finalization built it and nothing fed it: no caller of ``advance_phase`` or ``get_or_create``
and no reader of ``runtime.boot_camp_tracker``. Its five phases are not AD-638's 1 to 4, and
AD-486's birth chamber carries the orientation phases. A config that still carries
``boot_camp_phase:`` keeps loading, because SystemConfig ignores unknown keys (the BF-926
precedent); the Captain's own file is one.
"""

from __future__ import annotations

import ast
import importlib.util
import sys
from pathlib import Path

import pytest
import yaml

import probos.config as config_module
import probos.crew_development as crew_development
from probos import event_persistence as ep
from probos.config import SystemConfig, load_config
from probos.events import EventType
from probos.startup import finalize

_REPO = Path(__file__).resolve().parents[1]
_SRC = _REPO / "src" / "probos"
_READERS = _REPO / "scripts" / "check_config_readers.py"
_TRACKER_NAMES = ("AgentBootCampRecord", "BootCampPhase", "BootCampPhaseTracker")


def _load_readers():
    spec = importlib.util.spec_from_file_location("_ad1270_4c_config_readers", _READERS)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_the_tracker_module_is_gone() -> None:
    assert importlib.util.find_spec("probos.crew_development.boot_camp") is None
    assert not (_SRC / "crew_development" / "boot_camp.py").exists()


@pytest.mark.parametrize("name", _TRACKER_NAMES)
def test_the_package_no_longer_exports_the_tracker(name: str) -> None:
    assert name not in crew_development.__all__
    assert not hasattr(crew_development, name)


def test_the_package_keeps_its_other_exports() -> None:
    """Premise for the case above: the deletion took the tracker's three names and nothing else."""
    assert len(crew_development.__all__) == 14
    for name in crew_development.__all__:
        assert hasattr(crew_development, name), name


def test_finalization_no_longer_wires_a_tracker() -> None:
    assert not hasattr(finalize, "_wire_boot_camp_tracker")
    tree = ast.parse((_SRC / "startup" / "finalize.py").read_bytes())
    called = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    attributes = {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}

    assert "_wire_birth_chamber" in called  # premise: the scan sees the neighbouring wirer
    assert "_wire_boot_camp_tracker" not in called
    assert "ship_state_snapshot" in attributes  # premise: the scan sees runtime attributes
    assert "boot_camp_tracker" not in attributes


def test_the_config_field_and_model_are_gone() -> None:
    assert "crew_development" in SystemConfig.model_fields  # premise: its neighbour stays
    assert "boot_camp_phase" not in SystemConfig.model_fields
    assert not hasattr(config_module, "BootCampPhaseConfig")
    assert "boot_camp_phase" not in SystemConfig().model_dump()


@pytest.mark.parametrize("enabled", [True, False])
def test_a_config_that_still_sets_boot_camp_phase_loads(enabled: bool, tmp_path: Path) -> None:
    path = tmp_path / "system.yaml"
    path.write_text(
        yaml.safe_dump({"boot_camp_phase": {"enabled": enabled}, "crew_development": {"enabled": False}}),
        encoding="utf-8",
    )

    cfg = load_config(path)

    assert cfg.crew_development.enabled is False  # the file was read
    assert "boot_camp_phase" not in cfg.model_dump()


def test_the_tracked_yaml_carries_no_boot_camp_phase_key(tmp_path: Path) -> None:
    readers = _load_readers()
    document = yaml.safe_load(readers.DEFAULT_YAML.read_text(encoding="utf-8"))
    assert "crew_development" in document  # premise: this is the tracked config
    assert "boot_camp_phase" not in document

    # Control: the reader check reports the section as a key no field declares when it is present.
    (tmp_path / "src").mkdir()
    report = readers.build_report(
        SystemConfig, tmp_path / "src", {**document, "boot_camp_phase": {"enabled": True}},
    )
    assert "boot_camp_phase" in report.orphan_yaml_keys
    assert "crew_development" not in report.orphan_yaml_keys


def test_the_event_type_and_its_grandfathered_entry_are_gone() -> None:
    assert "BOOT_CAMP_ACTIVATED" in ep.GRANDFATHERED  # premise: its AD-638 neighbours stay
    assert "BOOT_CAMP_PHASE_ADVANCED" not in EventType.__members__
    assert "boot_camp_phase_advanced" not in {member.value for member in EventType}
    assert "BOOT_CAMP_PHASE_ADVANCED" not in ep.GRANDFATHERED
    assert ep.assert_complete(EventType.__members__) is None
