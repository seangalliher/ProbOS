"""BF-926 (#1656): config fields that promise behaviour nothing reads are marked inert or removed,
and a report-only check lists fields no production code reads and yaml keys no field declares.

The check is loaded by path, as it is run. The fixture model, source tree and yaml are the check's
inputs, not doubles of production code; the real-tree cases run it on ``SystemConfig``,
``src/probos`` and the tracked ``config/system.yaml``, so each inert marker is pinned on the model
that carries it.
"""

from __future__ import annotations

import functools
import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest
import yaml
from pydantic import BaseModel, Field

from probos.config import MemorySecurityConfig, SystemConfig

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SCRIPT = _REPO_ROOT / "scripts" / "check_config_readers.py"


def _load_checker():
    spec = importlib.util.spec_from_file_location("_bf926_config_readers", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


checker = _load_checker()
MARK = checker.INERT_MARKER


class _Leaf(BaseModel):
    read_field: int = 1
    unread_field: int = 2
    inert_field: int = Field(default=3, description=f"{MARK} field. Fixture.")
    inert_but_named: int = Field(default=4, description=f"{MARK} field. Fixture.")


class _DormantSection(BaseModel):
    """Fixture section. Inert: no production code reads this section."""

    knob: int = 5


class _Root(BaseModel):
    leaf: _Leaf = _Leaf()
    dormant: _DormantSection = _DormantSection()


def test_the_report_separates_read_unread_inert_and_orphan_keys(tmp_path: Path) -> None:
    assert MARK in (_DormantSection.__doc__ or "")  # premise: the fixture section carries the marker
    source = tmp_path / "src"
    (source / "pkg").mkdir(parents=True)
    (source / "pkg" / "reader.py").write_text(
        "def use(cfg):\n    return cfg.leaf.read_field, getattr(cfg, 'inert_but_named')\n", encoding="utf-8"
    )
    # A declaring module: a mention here is the declaration, not a reader.
    (source / "config.py").write_text("def declare(cfg):\n    return cfg.unread_field\n", encoding="utf-8")
    document = {"leaf": {"read_field": 1, "ghost": 2}, "dormant": {"knob": 5}, "stray_section": {"x": 1}}

    report = checker.build_report(_Root, source, document)

    assert report.unread == ["leaf.unread_field"]
    assert report.inert == ["leaf.inert_field", "leaf.inert_but_named", "dormant.knob"]
    assert report.inert_referenced == ["leaf.inert_but_named"]
    assert report.orphan_yaml_keys == ["leaf.ghost", "stray_section"]
    assert report.warnings == []


_EXIT_CASES = {
    "the real tree": [],
    "a missing yaml file": ["--yaml", "{tmp}/absent.yaml"],
    "a malformed yaml file": ["--yaml", "{tmp}/broken.yaml"],
    "a source file that does not parse": ["--src", "{tmp}/src"],
    "an unknown argument": ["--strict"],
    "an argument without its value": ["--yaml"],
}


@pytest.mark.parametrize("case", sorted(_EXIT_CASES))
def test_the_check_exits_zero_on_every_input(case: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (tmp_path / "broken.yaml").write_text("leaf: [unclosed\n", encoding="utf-8")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "broken.py").write_text("def (:\n", encoding="utf-8")
    argv = [part.format(tmp=tmp_path.as_posix()) for part in _EXIT_CASES[case]]

    assert checker.main(argv) == 0

    assert capsys.readouterr().out.startswith(checker.PREFIX)


def test_the_command_line_exit_status_is_zero(tmp_path: Path) -> None:
    completed = subprocess.run(
        [sys.executable, "-P", str(_SCRIPT), "--yaml", str(tmp_path / "absent.yaml")],
        capture_output=True, text=True, timeout=300, cwd=_REPO_ROOT,
    )

    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.startswith(checker.PREFIX)


_WORKING_MEMORY_INERT = (
    "token_budget", "max_recent_actions", "max_recent_observations", "max_recent_conversations", "max_events",
    "proactive_budget", "conclusion_ttl_seconds", "max_conclusions", "duty_budget", "social_budget", "ship_budget",
    "engagement_budget",
)
# AD-1270 (#1324) slice 3: "metabolism" left this table. working_memory.cognition_enabled now builds
# MemoryMetabolism from that section, so its fields are read and no longer marked inert;
# tests/test_ad1270_working_memory_cognition.py pins that they are neither inert nor unread.
_SECTIONS_INERT = {
    "memory_budget": ("enabled", "total_budget_tokens", "l0_budget", "l1_budget", "l2_budget", "l3_budget"),
    "pinned_knowledge": ("enabled", "max_tokens", "max_pins", "default_ttl_seconds"),
    "temporal_validity": ("enabled", "default_validity_hours"),
}
BF926_INERT = (
    "cognitive.use_consensus_for_writes",
    "federation.memory_policy",
    "federation.memory_policy_selective_tags",
    "federation.min_peer_trust_score",
    "federation.shared_trust_min_score",
    "security.permission_mode",
    "security.policy_engine_class",
    *(f"working_memory.{name}" for name in _WORKING_MEMORY_INERT),
    *(f"{section}.{name}" for section, names in _SECTIONS_INERT.items() for name in names),
)


@functools.lru_cache(maxsize=1)
def _real_report():
    """Built once per process from the real model, source and tracked yaml; tests only read it."""
    document = yaml.safe_load(checker.DEFAULT_YAML.read_text(encoding="utf-8"))
    return checker.build_report(SystemConfig, checker.DEFAULT_SOURCE, document)


@pytest.mark.parametrize("path", BF926_INERT)
def test_the_real_config_reports_each_bf926_field_as_inert(path: str) -> None:
    report = _real_report()

    assert path in report.inert
    assert path not in report.unread


def test_the_leak_guard_flag_is_gone_and_a_config_that_sets_it_still_loads() -> None:
    assert "enforce_leak_guard" not in MemorySecurityConfig.model_fields

    cfg = SystemConfig.model_validate({
        "security": {"memory": {"enforce_leak_guard": True, "enforce_store": True}},
        "cognitive": {"captain_card_refresh_min_interval_seconds": 60},
    })

    assert cfg.security.memory.enforce_store is True
    assert "enforce_leak_guard" not in cfg.security.memory.model_dump()


def test_the_tracked_yaml_carries_no_key_bf926_removed() -> None:
    report = _real_report()

    assert "cognitive.captain_card_refresh_min_interval_seconds" not in report.orphan_yaml_keys
    assert "security.memory.enforce_leak_guard" not in report.orphan_yaml_keys
    assert "working_memory.stale_threshold_hours" not in report.inert  # the one read field is not marked
