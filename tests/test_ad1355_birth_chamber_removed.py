"""AD-1355 S1 (#1700): the AD-486 Birth Chamber and the department activation scheduler are deleted.

Neither ran with its switch at the default: ``holodeck_birth_chamber.enabled`` was False in the
model and in the tracked ``config/system.yaml``. With the switch on, the chamber admitted almost
no one and graduated no one (#1700, Problem items 1 to 10). Both are deleted with their config,
wirer, the onboarding, assignment and proactive seams, the six event types only the chamber
emitted, and their tests. A config that still carries ``holodeck_birth_chamber:`` keeps loading,
because SystemConfig ignores unknown keys (the BF-926 precedent).

The census reads every file under ``src/`` except ``__pycache__`` and files holding a NUL byte,
for the four names #1700's acceptance line lists. Two controls show that it reads the real tree
and that it reports a planted reference.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest
import yaml

import probos.config as config_module
import probos.config_models as config_models
import probos.config_models.crew as config_crew
import probos.holodeck as holodeck
from probos import event_persistence as ep
from probos.agent_onboarding import AgentOnboardingService
from probos.assignment import AssignmentService
from probos.config import SystemConfig, load_config
from probos.events import EventType
from probos.startup import finalize

_REPO = Path(__file__).resolve().parents[1]
_SRC = _REPO / "src"
_READERS = _REPO / "scripts" / "check_config_readers.py"
_TERMS = ("BirthChamber", "DepartmentActivationScheduler", "birth_chamber", "holodeck_birth_chamber")
_MODULES = ("chamber", "gates", "phases", "affect", "scheduler")
_EVENTS = (
    "HOLODECK_AFFECTIVE_BASELINE_OBSERVED",
    "HOLODECK_AGENT_ADMITTED",
    "HOLODECK_GRADUATION",
    "HOLODECK_PHASE_ENTERED",
    "HOLODECK_PHASE_GATE_BLOCKED",
    "HOLODECK_PHASE_GATE_PASSED",
)
_HOLODECK_EXPORTS = (
    "DebriefRecord",
    "GapScenarioGenerator",
    "HolodeckGapBridge",
    "HolodeckGapDrill",
    "HolodeckScenarioStore",
    "ScenarioGapLink",
    "ScenarioOutcome",
    "TeamScenario",
    "TeamScenarioRegistry",
    "TeamSimulationDrill",
    "TeamSimulationOrchestrator",
    "TeamSimulationParticipant",
    "TeamSimulationRecord",
    "TeamSimulationStore",
)


def _readable(root: Path) -> list[Path]:
    """Every file under ``root`` the census reads: not bytecode, not binary."""
    paths: list[Path] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or "__pycache__" in path.parts:
            continue
        if b"\x00" in path.read_bytes():
            continue
        paths.append(path)
    return paths


def _census(root: Path, term: str) -> list[str]:
    """``relative/path:line`` for every line under ``root`` that holds ``term``."""
    hits: list[str] = []
    for path in _readable(root):
        text = path.read_bytes().decode("utf-8", errors="replace")
        for number, line in enumerate(text.splitlines(), start=1):
            if term in line:
                hits.append(f"{path.relative_to(root).as_posix()}:{number}")
    return hits


def _load_readers():
    spec = importlib.util.spec_from_file_location("_ad1355_s1_config_readers", _READERS)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("term", _TERMS)
def test_no_src_file_names_a_removed_term(term: str) -> None:
    assert _census(_SRC, term) == []


def test_the_census_reads_the_real_tree() -> None:
    """Premise for the case above: the walk reaches every seam S1 edited and a data file, and sees a neighbour."""
    read = {path.relative_to(_SRC).as_posix() for path in _readable(_SRC)}
    for path in (
        "probos/agent_onboarding.py",
        "probos/assignment.py",
        "probos/proactive.py",
        "probos/config.py",
        "probos/config_models/crew.py",
        "probos/startup/finalize.py",
        "probos/holodeck/__init__.py",
        "probos/sop/builtin/general_quarters.yaml",
    ):
        assert path in read, path
    assert _census(_SRC, "HolodeckScenarioConfig")
    assert _census(_SRC, "_wire_holodeck_team_simulations")


def test_the_census_reports_a_planted_reference(tmp_path: Path) -> None:
    """Control: a reference put back is found in Python and in a data file; bytecode and binaries are not read."""
    package = tmp_path / "probos"
    (package / "__pycache__").mkdir(parents=True)
    (package / "seam.py").write_text("x = 1\nfrom probos.holodeck import BirthChamber\n", encoding="utf-8")
    (package / "orders.yaml").write_text("holodeck_birth_chamber:\n  enabled: true\n", encoding="utf-8")
    (package / "__pycache__" / "seam.cpython-312.pyc").write_bytes(b"BirthChamber")
    (package / "blob.bin").write_bytes(b"\x00BirthChamber")

    assert _census(tmp_path, "BirthChamber") == ["probos/seam.py:2"]
    assert _census(tmp_path, "birth_chamber") == ["probos/orders.yaml:1"]
    assert _census(tmp_path, "DepartmentActivationScheduler") == []


@pytest.mark.parametrize("name", _MODULES)
def test_the_deleted_modules_are_gone(name: str) -> None:
    assert importlib.util.find_spec(f"probos.holodeck.{name}") is None
    assert not (_SRC / "probos" / "holodeck" / f"{name}.py").exists()


def test_the_holodeck_package_keeps_scenarios_and_team_simulations() -> None:
    assert tuple(holodeck.__all__) == _HOLODECK_EXPORTS
    for name in _HOLODECK_EXPORTS:
        assert hasattr(holodeck, name), name


def test_the_config_field_and_model_are_gone() -> None:
    assert "holodeck_scenarios" in SystemConfig.model_fields  # premise: its neighbour stays
    assert "holodeck_birth_chamber" not in SystemConfig.model_fields
    assert "holodeck_birth_chamber" not in SystemConfig().model_dump()
    for module in (config_module, config_models, config_crew):
        assert not hasattr(module, "HolodeckBirthChamberConfig"), module.__name__
    assert "HolodeckBirthChamberConfig" not in config_models.__all__


@pytest.mark.parametrize("enabled", [True, False])
def test_a_config_that_still_sets_holodeck_birth_chamber_loads(enabled: bool, tmp_path: Path) -> None:
    path = tmp_path / "system.yaml"
    path.write_text(
        yaml.safe_dump({
            "holodeck_birth_chamber": {
                "enabled": enabled,
                "bypass_for_existing_agents": True,
                "department_order": ["security", "operations", "engineering", "science", "medical"],
                "calibration_min_episodes": 5,
                "auto_advance_enabled": True,
            },
            "onboarding": {"naming_ceremony": False},
        }),
        encoding="utf-8",
    )

    cfg = load_config(path)

    assert cfg.onboarding.naming_ceremony is False  # the file was read
    assert "holodeck_birth_chamber" not in cfg.model_dump()


def test_the_tracked_yaml_carries_no_holodeck_birth_chamber_key(tmp_path: Path) -> None:
    readers = _load_readers()
    document = yaml.safe_load(readers.DEFAULT_YAML.read_text(encoding="utf-8"))
    assert "holodeck_scenarios" in document  # premise: this is the tracked config
    assert "holodeck_birth_chamber" not in document

    # Control: the reader check reports the section as a key no field declares when it is present.
    (tmp_path / "src").mkdir()
    report = readers.build_report(
        SystemConfig, tmp_path / "src", {**document, "holodeck_birth_chamber": {"enabled": False}},
    )
    assert "holodeck_birth_chamber" in report.orphan_yaml_keys
    assert "holodeck_scenarios" not in report.orphan_yaml_keys


def test_the_six_event_types_and_their_grandfathered_entries_are_gone() -> None:
    assert "HOLODECK_SCENARIO_GENERATED" in EventType.__members__  # premise: AD-539b's events stay
    assert "HOLODECK_SCENARIO_GENERATED" in ep.GRANDFATHERED
    values = {member.value for member in EventType}
    for name in _EVENTS:
        assert name not in EventType.__members__, name
        assert name.lower() not in values, name
        assert name not in ep.GRANDFATHERED, name
        assert name not in ep.DECLARATIONS, name
    assert ep.assert_complete(EventType.__members__) is None


def test_the_wirer_and_both_setters_are_gone() -> None:
    assert hasattr(finalize, "_wire_holodeck_scenarios")  # premise: the neighbouring wirer stays
    assert hasattr(AgentOnboardingService, "set_crew_enroller")  # premise: the neighbouring setters stay
    assert hasattr(AssignmentService, "set_admission")
    assert not hasattr(finalize, "_wire_birth_chamber")
    assert not hasattr(AgentOnboardingService, "set_birth_chamber")
    assert not hasattr(AssignmentService, "set_birth_chamber")
