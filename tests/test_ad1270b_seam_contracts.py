"""AD-1270b slice 1: the seam contract catalog must not rot silently.

``docs/development/seams/*.yaml`` is the canonical P0 denominator. Before
``scripts/check_seam_contracts.py`` nothing read it, so an ID could be deleted
rather than tombstoned and the four ``seam_ids`` references in the production
declaration modules could dangle without any signal.

These tests cover both halves: the real committed manifest stays valid (the
currency guard, which also runs in gate preflight), and the checker actually
fails on each defect class rather than passing unconditionally. A check that
cannot fail is not a gate.

Fix a currency failure with::

    python scripts/check_seam_contracts.py --check
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
import types
from pathlib import Path
from typing import Any

import pytest
import yaml

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SCRIPT = _REPO_ROOT / "scripts" / "check_seam_contracts.py"
_REAL_SEAMS_DIR = _REPO_ROOT / "docs" / "development" / "seams"
_REAL_SRC = _REPO_ROOT / "src"


@pytest.fixture(scope="module")
def checker() -> types.ModuleType:
    """Import the checker from its path -- ``scripts/`` is not a package.

    Registered in ``sys.modules`` before execution because the module defines a
    dataclass and, under PEP 563, the dataclass machinery re-reads each
    annotation out of ``sys.modules[cls.__module__]``.
    """
    spec = importlib.util.spec_from_file_location("check_seam_contracts", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["check_seam_contracts"] = module
    spec.loader.exec_module(module)
    return module


def _entry(**overrides: Any) -> dict[str, Any]:
    """A minimal valid active Tier-A entry, using the unresolved-symbol hatch.

    Defaulting to the hatch keeps every non-symbol test independent of whatever
    source tree it points at; the symbol tests override it explicitly.
    """
    entry: dict[str, Any] = {
        "id": "TA-P0-001-demo-seam",
        "tier": "A",
        "status": "active",
        "evidence_status": "planned",
        "owner": "AD-1270b",
        "producer": "demo producer",
        "producer_symbol": None,
        "consumer": "demo consumer",
        "consumer_symbol": None,
        "symbol_status": "unresolved",
        "symbol_note": "synthetic fixture; no owning symbol",
        "path": "a -> b",
        "crossing_test": None,
    }
    entry.update(overrides)
    return entry


def _tombstone(**overrides: Any) -> dict[str, Any]:
    stone: dict[str, Any] = {
        "id": "TA-P0-001-demo-seam",
        "rationale": "superseded by a narrower seam",
        "replacement": "TA-P0-002-demo-replacement",
        "decision": "AD-1270b",
        "date": "2026-09-02",
    }
    stone.update(overrides)
    return stone


def _manifest(**overrides: Any) -> dict[str, Any]:
    document: dict[str, Any] = {
        "schema_version": 1,
        "manifest_id": "demo-manifest",
        "owner": "AD-1270b",
        "tracking_issue": 1324,
        "id_allocation": {"TA-P0": 1},
        "rules": ["demo rule"],
        "seams": [_entry()],
        "tombstones": [],
    }
    document.update(overrides)
    return document


def _write_manifest(
    tmp_path: Path, document: Any, name: str = "p0-manifest.yaml"
) -> Path:
    """Write ``document`` into a fresh seams directory and return that directory."""
    seams_dir = tmp_path / "seams"
    seams_dir.mkdir(exist_ok=True)
    text = (
        document
        if isinstance(document, str)
        else yaml.safe_dump(document, sort_keys=False)
    )
    (seams_dir / name).write_text(text, encoding="utf-8")
    return seams_dir


def _synthetic_src(tmp_path: Path, *, seam_ids: tuple[str, ...] = ()) -> Path:
    """Build a tiny source tree so symbol and declaration tests stay hermetic.

    Points at ``probos.demo.carrier`` rather than real production symbols, so a
    later refactor of the real tree cannot turn these tests red for a reason
    that has nothing to do with the checker.
    """
    src = tmp_path / "src"
    maturity = src / "probos" / "maturity"
    maturity.mkdir(parents=True, exist_ok=True)
    (maturity / "registry.py").write_text(
        'DECLARATION_MODULES = ("probos.demo.maturity_declarations",)\n',
        encoding="utf-8",
    )
    demo = src / "probos" / "demo"
    demo.mkdir(parents=True, exist_ok=True)
    (demo / "carrier.py").write_text(
        "class Carrier:\n"
        "    def handle(self) -> None: ...\n"
        "\n"
        "\n"
        "def make() -> None: ...\n",
        encoding="utf-8",
    )
    if seam_ids:
        literal = "".join(f"{value!r}, " for value in seam_ids)
        (demo / "maturity_declarations.py").write_text(
            f"DECLARATIONS = (Declaration(seam_ids=({literal})),)\n",
            encoding="utf-8",
        )
    return src


# --------------------------------------------------------------------------
# Live-manifest currency
# --------------------------------------------------------------------------


def test_the_checker_script_exists() -> None:
    assert _SCRIPT.is_file(), (
        "scripts/check_seam_contracts.py is missing; the seam catalog cannot "
        "be validated without it"
    )


def test_committed_manifest_passes_check_in_a_subprocess() -> None:
    """Runs the real command a developer and gate preflight are told to run."""
    result = subprocess.run(
        [sys.executable, str(_SCRIPT), "--check"],
        capture_output=True,
        text=True,
        cwd=str(_REPO_ROOT),
        timeout=300,
    )

    assert result.returncode == 0, (
        "the committed seam manifest does not validate.\n"
        "Re-check with: python scripts/check_seam_contracts.py --check\n\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )


def test_committed_manifest_with_require_crossing_tests_fails_today() -> None:
    """Rule 12 ships disabled; slice 3 fills node IDs and flips the default."""
    result = subprocess.run(
        [sys.executable, str(_SCRIPT), "--check", "--require-crossing-tests"],
        capture_output=True,
        text=True,
        cwd=str(_REPO_ROOT),
        timeout=300,
    )

    assert result.returncode == 1
    for seam_id in (
        "TA-P0-001-turn-act-evidence",
        "TA-P0-002-tool-fault-repair",
        "TA-P0-003-approval-resume",
        "TA-P0-004-mcp-offer-invoke",
        "TA-P0-005-startup-lifecycle",
        "TA-P0-006-snapshot-restore-read",
        "TA-P0-007-crew-outcome-trust",
    ):
        assert seam_id in result.stderr


# --------------------------------------------------------------------------
# Schema
# --------------------------------------------------------------------------


def test_unparseable_yaml_reports_a_parse_failure(
    checker: types.ModuleType, tmp_path: Path
) -> None:
    seams_dir = _write_manifest(tmp_path, "seams: [\n  - id: broken\n    :\n")

    errors = checker.validate(seams_dir=seams_dir, src_root=_synthetic_src(tmp_path))

    assert any("does not parse as YAML" in error for error in errors)


def test_missing_top_level_key_reports_that_key(
    checker: types.ModuleType, tmp_path: Path
) -> None:
    document = _manifest()
    del document["id_allocation"]
    seams_dir = _write_manifest(tmp_path, document)

    errors = checker.validate(seams_dir=seams_dir, src_root=_synthetic_src(tmp_path))

    assert any("missing required top-level key 'id_allocation'" in e for e in errors)


def test_invalid_tier_is_reported(
    checker: types.ModuleType, tmp_path: Path
) -> None:
    seams_dir = _write_manifest(tmp_path, _manifest(seams=[_entry(tier="C")]))

    errors = checker.validate(seams_dir=seams_dir, src_root=_synthetic_src(tmp_path))

    assert any("tier is 'C'" in error for error in errors)


def test_invalid_evidence_status_is_reported(
    checker: types.ModuleType, tmp_path: Path
) -> None:
    seams_dir = _write_manifest(
        tmp_path, _manifest(seams=[_entry(evidence_status="probably")])
    )

    errors = checker.validate(seams_dir=seams_dir, src_root=_synthetic_src(tmp_path))

    assert any("evidence_status is 'probably'" in error for error in errors)


def test_entry_missing_required_field_is_reported(
    checker: types.ModuleType, tmp_path: Path
) -> None:
    entry = _entry()
    del entry["owner"]
    seams_dir = _write_manifest(tmp_path, _manifest(seams=[entry]))

    errors = checker.validate(seams_dir=seams_dir, src_root=_synthetic_src(tmp_path))

    assert any("missing required field 'owner'" in error for error in errors)


# --------------------------------------------------------------------------
# IDs
# --------------------------------------------------------------------------


def test_duplicate_id_within_seams_is_reported(
    checker: types.ModuleType, tmp_path: Path
) -> None:
    seams_dir = _write_manifest(
        tmp_path,
        _manifest(
            seams=[_entry(), _entry()],
            id_allocation={"TA-P0": 1},
        ),
    )

    errors = checker.validate(seams_dir=seams_dir, src_root=_synthetic_src(tmp_path))

    assert any("is already declared in" in error for error in errors)


def test_duplicate_id_across_seams_and_tombstones_is_reported(
    checker: types.ModuleType, tmp_path: Path
) -> None:
    seams_dir = _write_manifest(
        tmp_path,
        _manifest(seams=[_entry()], tombstones=[_tombstone()]),
    )

    errors = checker.validate(seams_dir=seams_dir, src_root=_synthetic_src(tmp_path))

    assert any("is already declared in" in error for error in errors)


def test_malformed_id_is_reported(
    checker: types.ModuleType, tmp_path: Path
) -> None:
    seams_dir = _write_manifest(
        tmp_path,
        _manifest(seams=[_entry(id="TA-P0-1-Bad_Id")], id_allocation={"TA-P0": 0}),
    )

    errors = checker.validate(seams_dir=seams_dir, src_root=_synthetic_src(tmp_path))

    assert any("does not match" in error for error in errors)


def test_ordinal_above_id_allocation_is_reported(
    checker: types.ModuleType, tmp_path: Path
) -> None:
    """Adding TA-P0-008 without bumping the high-water mark must fail."""
    seams_dir = _write_manifest(
        tmp_path,
        _manifest(
            seams=[_entry(), _entry(id="TA-P0-002-demo-extra")],
            id_allocation={"TA-P0": 1},
        ),
    )

    errors = checker.validate(seams_dir=seams_dir, src_root=_synthetic_src(tmp_path))

    assert any("above the id_allocation high-water mark" in e for e in errors)


# --------------------------------------------------------------------------
# Ordinals and tombstones
# --------------------------------------------------------------------------


def test_deleted_middle_id_is_reported_as_a_gap(
    checker: types.ModuleType, tmp_path: Path
) -> None:
    """Ordinals {1, 3} against N=3 leaves a hole at 2."""
    seams_dir = _write_manifest(
        tmp_path,
        _manifest(
            seams=[_entry(), _entry(id="TA-P0-003-demo-third")],
            id_allocation={"TA-P0": 3},
        ),
    )

    errors = checker.validate(seams_dir=seams_dir, src_root=_synthetic_src(tmp_path))

    assert any("missing ordinals ['002']" in error for error in errors)


def test_deleted_highest_id_is_reported_against_high_water_mark(
    checker: types.ModuleType, tmp_path: Path
) -> None:
    """Plain contiguity would pass {1, 2}; the high-water mark is what catches it."""
    seams_dir = _write_manifest(
        tmp_path,
        _manifest(
            seams=[_entry(), _entry(id="TA-P0-002-demo-second")],
            id_allocation={"TA-P0": 3},
        ),
    )

    errors = checker.validate(seams_dir=seams_dir, src_root=_synthetic_src(tmp_path))

    assert any("missing ordinals ['003']" in error for error in errors)


def test_id_moved_to_tombstones_keeps_the_ordinals_contiguous(
    checker: types.ModuleType, tmp_path: Path
) -> None:
    seams_dir = _write_manifest(
        tmp_path,
        _manifest(
            seams=[_entry(id="TA-P0-002-demo-second")],
            tombstones=[_tombstone(id="TA-P0-001-demo-seam")],
            id_allocation={"TA-P0": 2},
        ),
    )

    errors = checker.validate(seams_dir=seams_dir, src_root=_synthetic_src(tmp_path))

    assert errors == []


def test_tombstone_missing_rationale_is_reported(
    checker: types.ModuleType, tmp_path: Path
) -> None:
    stone = _tombstone(id="TA-P0-002-demo-second")
    del stone["rationale"]
    seams_dir = _write_manifest(
        tmp_path,
        _manifest(tombstones=[stone], id_allocation={"TA-P0": 2}),
    )

    errors = checker.validate(seams_dir=seams_dir, src_root=_synthetic_src(tmp_path))

    assert any("missing required field 'rationale'" in error for error in errors)


def test_tombstone_with_non_iso_date_is_reported(
    checker: types.ModuleType, tmp_path: Path
) -> None:
    seams_dir = _write_manifest(
        tmp_path,
        _manifest(
            tombstones=[_tombstone(id="TA-P0-002-demo-second", date="02/09/2026")],
            id_allocation={"TA-P0": 2},
        ),
    )

    errors = checker.validate(seams_dir=seams_dir, src_root=_synthetic_src(tmp_path))

    assert any("is not ISO YYYY-MM-DD" in error for error in errors)


def test_complete_tombstone_with_all_four_fields_passes(
    checker: types.ModuleType, tmp_path: Path
) -> None:
    seams_dir = _write_manifest(
        tmp_path,
        _manifest(
            tombstones=[_tombstone(id="TA-P0-002-demo-second")],
            id_allocation={"TA-P0": 2},
        ),
    )

    errors = checker.validate(seams_dir=seams_dir, src_root=_synthetic_src(tmp_path))

    assert errors == []


# --------------------------------------------------------------------------
# Symbols
# --------------------------------------------------------------------------


def test_resolvable_dotted_paths_pass(
    checker: types.ModuleType, tmp_path: Path
) -> None:
    seams_dir = _write_manifest(
        tmp_path,
        _manifest(
            seams=[
                _entry(
                    producer_symbol="probos.demo.carrier.Carrier",
                    consumer_symbol="probos.demo.carrier.Carrier.handle",
                    symbol_status=None,
                    symbol_note=None,
                )
            ]
        ),
    )

    errors = checker.validate(seams_dir=seams_dir, src_root=_synthetic_src(tmp_path))

    assert errors == []


def test_unresolvable_module_is_reported(
    checker: types.ModuleType, tmp_path: Path
) -> None:
    seams_dir = _write_manifest(
        tmp_path,
        _manifest(
            seams=[
                _entry(
                    producer_symbol="probos.demo.absent.Carrier",
                    consumer_symbol="probos.demo.carrier.make",
                    symbol_status=None,
                    symbol_note=None,
                )
            ]
        ),
    )

    errors = checker.validate(seams_dir=seams_dir, src_root=_synthetic_src(tmp_path))

    assert any("no module under src/ matches any prefix" in e for e in errors)


def test_resolvable_module_with_unresolvable_attribute_is_reported(
    checker: types.ModuleType, tmp_path: Path
) -> None:
    seams_dir = _write_manifest(
        tmp_path,
        _manifest(
            seams=[
                _entry(
                    producer_symbol="probos.demo.carrier.Carrier",
                    consumer_symbol="probos.demo.carrier.Carrier.absent_method",
                    symbol_status=None,
                    symbol_note=None,
                )
            ]
        ),
    )

    errors = checker.validate(seams_dir=seams_dir, src_root=_synthetic_src(tmp_path))

    assert any("defines no 'absent_method'" in error for error in errors)


def test_unresolved_symbol_status_with_proven_evidence_is_reported(
    checker: types.ModuleType, tmp_path: Path
) -> None:
    """Rule 8: an unresolved seam has no owning symbol to have proven anything."""
    seams_dir = _write_manifest(
        tmp_path, _manifest(seams=[_entry(evidence_status="proven")])
    )

    errors = checker.validate(seams_dir=seams_dir, src_root=_synthetic_src(tmp_path))

    assert any("cannot carry evidence_status: proven" in error for error in errors)


def test_null_symbol_without_the_unresolved_hatch_is_reported(
    checker: types.ModuleType, tmp_path: Path
) -> None:
    seams_dir = _write_manifest(
        tmp_path,
        _manifest(seams=[_entry(symbol_status=None, symbol_note=None)]),
    )

    errors = checker.validate(seams_dir=seams_dir, src_root=_synthetic_src(tmp_path))

    assert any("without symbol_status: unresolved" in error for error in errors)


def test_unresolved_hatch_without_a_note_is_reported(
    checker: types.ModuleType, tmp_path: Path
) -> None:
    seams_dir = _write_manifest(
        tmp_path, _manifest(seams=[_entry(symbol_note="  ")])
    )

    errors = checker.validate(seams_dir=seams_dir, src_root=_synthetic_src(tmp_path))

    assert any("requires a non-empty symbol_note" in error for error in errors)


def test_active_tier_a_entry_without_symbol_fields_is_reported(
    checker: types.ModuleType, tmp_path: Path
) -> None:
    entry = _entry()
    del entry["producer_symbol"]
    del entry["consumer_symbol"]
    seams_dir = _write_manifest(tmp_path, _manifest(seams=[entry]))

    errors = checker.validate(seams_dir=seams_dir, src_root=_synthetic_src(tmp_path))

    assert any(
        "missing required field 'producer_symbol'" in error for error in errors
    )


def test_resolve_symbol_bare_name_is_rejected(checker: types.ModuleType) -> None:
    """A bare ``record_outcome`` matches thirteen production definitions."""
    index = checker.SymbolIndex()

    reason = checker.resolve_symbol("record_outcome", index)

    assert reason is not None and "bare name" in reason


def test_resolve_symbol_empty_string_is_rejected(
    checker: types.ModuleType,
) -> None:
    index = checker.SymbolIndex()

    reason = checker.resolve_symbol("   ", index)

    assert reason == "symbol is empty"


def test_build_symbol_index_on_a_missing_root_returns_an_empty_index(
    checker: types.ModuleType, tmp_path: Path
) -> None:
    index = checker.build_symbol_index(tmp_path / "does-not-exist")

    assert index.modules == {}
    assert index.class_methods == {}


# --------------------------------------------------------------------------
# Declaration cross-reference
# --------------------------------------------------------------------------


def test_seam_ids_naming_an_active_entry_passes(
    checker: types.ModuleType, tmp_path: Path
) -> None:
    src = _synthetic_src(tmp_path, seam_ids=("TA-P0-001-demo-seam",))
    seams_dir = _write_manifest(tmp_path, _manifest())

    errors = checker.validate(seams_dir=seams_dir, src_root=src)

    assert errors == []


def test_seam_ids_naming_an_unknown_id_is_reported(
    checker: types.ModuleType, tmp_path: Path
) -> None:
    src = _synthetic_src(tmp_path, seam_ids=("TA-P0-001-typo-seam",))
    seams_dir = _write_manifest(tmp_path, _manifest())

    errors = checker.validate(seams_dir=seams_dir, src_root=src)

    assert any("names no active manifest entry" in error for error in errors)


def test_seam_ids_naming_a_tombstoned_id_is_reported(
    checker: types.ModuleType, tmp_path: Path
) -> None:
    """A reference to a retired seam is dead, not merely stale."""
    src = _synthetic_src(tmp_path, seam_ids=("TA-P0-001-demo-seam",))
    seams_dir = _write_manifest(
        tmp_path,
        _manifest(
            seams=[_entry(id="TA-P0-002-demo-second")],
            tombstones=[_tombstone(id="TA-P0-001-demo-seam")],
            id_allocation={"TA-P0": 2},
        ),
    )

    errors = checker.validate(seams_dir=seams_dir, src_root=src)

    assert any("which is tombstoned" in error for error in errors)


def test_declaration_modules_on_a_tree_without_a_registry_returns_empty(
    checker: types.ModuleType, tmp_path: Path
) -> None:
    assert checker.declaration_modules(tmp_path / "src") == ()


def test_declared_seam_ids_is_empty_when_no_module_declares_any(
    checker: types.ModuleType, tmp_path: Path
) -> None:
    src = _synthetic_src(tmp_path)

    assert checker.declared_seam_ids(src) == {}


def test_declared_seam_ids_reads_the_committed_declaration_modules(
    checker: types.ModuleType,
) -> None:
    """AST extraction, not regex: a docstring mention must not read as live."""
    declared = checker.declared_seam_ids(_REAL_SRC)

    assert declared["probos.tools.maturity_declarations"] == [
        "TA-P0-002-tool-fault-repair"
    ]


# --------------------------------------------------------------------------
# Crossing tests
# --------------------------------------------------------------------------


def test_null_crossing_test_is_skipped_in_default_mode(
    checker: types.ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Every entry is null today, so a default run must collect nothing.

    Symbol resolution shells out to ``git ls-files`` to keep untracked work out
    of the index, so this asserts no *collection* subprocess rather than no
    subprocess at all -- which is what the failure message always claimed.
    """
    calls: list[list[str]] = []

    def _record(*args: Any, **kwargs: Any) -> Any:
        command = list(args[0])
        calls.append(command)
        if "--collect-only" in command:
            raise AssertionError("no collection subprocess should run")
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(checker.subprocess, "run", _record)
    seams_dir = _write_manifest(tmp_path, _manifest())

    errors = checker.validate(seams_dir=seams_dir, src_root=_synthetic_src(tmp_path))

    assert errors == []
    assert not any("--collect-only" in command for command in calls)


def test_proven_evidence_with_null_crossing_test_is_reported(
    checker: types.ModuleType, tmp_path: Path
) -> None:
    seams_dir = _write_manifest(
        tmp_path,
        _manifest(
            seams=[
                _entry(
                    evidence_status="proven",
                    producer_symbol="probos.demo.carrier.Carrier",
                    consumer_symbol="probos.demo.carrier.make",
                    symbol_status=None,
                    symbol_note=None,
                )
            ]
        ),
    )

    errors = checker.validate(seams_dir=seams_dir, src_root=_synthetic_src(tmp_path))

    assert any("proven with no crossing_test" in error for error in errors)


def test_non_collecting_node_id_is_reported_as_a_failure(
    checker: types.ModuleType, tmp_path: Path
) -> None:
    """Runs real pytest against a node ID that cannot collect."""
    seams_dir = _write_manifest(
        tmp_path,
        _manifest(
            seams=[_entry(crossing_test="test_absent_file.py::test_absent")]
        ),
    )

    errors = checker.validate(
        seams_dir=seams_dir,
        src_root=_synthetic_src(tmp_path),
        repo_root=tmp_path,
    )

    assert any("crossing_test" in error for error in errors)


def test_collect_exit_five_is_treated_as_a_failure(
    checker: types.ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """EXIT_NOTESTSCOLLECTED is not a pass -- uncollected is non-passing."""

    def _exit_five(*args: Any, **kwargs: Any) -> Any:
        return subprocess.CompletedProcess(args[0], 5, "", "")

    monkeypatch.setattr(checker.subprocess, "run", _exit_five)
    seams_dir = _write_manifest(
        tmp_path, _manifest(seams=[_entry(crossing_test="tests/t.py::test_x")])
    )

    errors = checker.validate(seams_dir=seams_dir, src_root=_synthetic_src(tmp_path))

    assert any("pytest exit 5" in error for error in errors)


def test_collect_command_clears_inherited_addopts(
    checker: types.ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """pyproject sets ``-n 16``; inheriting it spawns 16 workers per node ID."""
    seen: list[list[str]] = []

    def _record(*args: Any, **kwargs: Any) -> Any:
        seen.append(list(args[0]))
        return subprocess.CompletedProcess(args[0], 0, "", "")

    monkeypatch.setattr(checker.subprocess, "run", _record)
    seams_dir = _write_manifest(
        tmp_path, _manifest(seams=[_entry(crossing_test="tests/t.py::test_x")])
    )

    checker.validate(seams_dir=seams_dir, src_root=_synthetic_src(tmp_path))

    # Symbol resolution also shells out to `git ls-files`, so select the
    # collection call rather than assuming it is the only subprocess.
    collect = [cmd for cmd in seen if "--collect-only" in cmd]
    assert len(collect) == 1
    command = collect[0]
    assert command[command.index("-o") + 1] == "addopts="
    assert "--collect-only" in command
    assert "no:cacheprovider" in command


def test_require_crossing_tests_flag_is_what_flips_the_verdict(
    checker: types.ModuleType, tmp_path: Path
) -> None:
    """Same manifest, both modes -- proves rule 12 is behind the flag."""
    seams_dir = _write_manifest(tmp_path, _manifest())
    src = _synthetic_src(tmp_path)

    default_mode = checker.validate(seams_dir=seams_dir, src_root=src)
    strict_mode = checker.validate(
        seams_dir=seams_dir, src_root=src, require_crossing_tests=True
    )

    assert default_mode == []
    assert any("--require-crossing-tests is set" in e for e in strict_mode)


def test_require_crossing_tests_ignores_tier_b_entries(
    checker: types.ModuleType, tmp_path: Path
) -> None:
    """Tier B is tracked for identity and does not gate Tier A."""
    seams_dir = _write_manifest(
        tmp_path,
        _manifest(
            seams=[_entry(id="TB-P0-001-demo-tier-b", tier="B")],
            id_allocation={"TB-P0": 1},
        ),
    )

    errors = checker.validate(
        seams_dir=seams_dir,
        src_root=_synthetic_src(tmp_path),
        require_crossing_tests=True,
    )

    assert errors == []


# --------------------------------------------------------------------------
# Directory handling, accumulation, and CLI
# --------------------------------------------------------------------------


def test_every_yaml_in_the_seams_directory_is_validated(
    checker: types.ModuleType, tmp_path: Path
) -> None:
    """A hard-coded filename would ignore the second file the day it lands."""
    seams_dir = _write_manifest(tmp_path, _manifest())
    _write_manifest(
        tmp_path,
        _manifest(seams=[_entry(id="TA-P0-001-second-file", tier="Z")]),
        name="p1-manifest.yaml",
    )

    errors = checker.validate(seams_dir=seams_dir, src_root=_synthetic_src(tmp_path))

    assert any("p1-manifest.yaml" in error and "tier is 'Z'" in error for error in errors)


def test_missing_seams_directory_is_reported(
    checker: types.ModuleType, tmp_path: Path
) -> None:
    errors = checker.validate(
        seams_dir=tmp_path / "absent", src_root=_synthetic_src(tmp_path)
    )

    assert any("seams directory does not exist" in error for error in errors)


def test_empty_seams_directory_is_reported(
    checker: types.ModuleType, tmp_path: Path
) -> None:
    empty = tmp_path / "seams"
    empty.mkdir()

    errors = checker.validate(
        seams_dir=empty, src_root=_synthetic_src(tmp_path)
    )

    assert any("contains no *.yaml" in error for error in errors)


def test_three_distinct_defects_are_all_reported(
    checker: types.ModuleType, tmp_path: Path
) -> None:
    """One problem per run would cost one gate cycle per problem."""
    seams_dir = _write_manifest(
        tmp_path,
        _manifest(
            seams=[
                _entry(tier="C"),
                _entry(id="TA-P0-009-demo-far", evidence_status="maybe"),
            ],
            id_allocation={"TA-P0": 1},
        ),
    )

    errors = checker.validate(seams_dir=seams_dir, src_root=_synthetic_src(tmp_path))

    assert any("tier is 'C'" in error for error in errors)
    assert any("evidence_status is 'maybe'" in error for error in errors)
    assert any("above the id_allocation high-water mark" in e for e in errors)


def test_check_mode_writes_nothing_into_the_repository(tmp_path: Path) -> None:
    """Gate preflight fails the whole run if a phase mutates the tree."""
    before = {
        path: path.stat().st_mtime_ns
        for path in sorted(_REAL_SEAMS_DIR.rglob("*"))
        if path.is_file()
    }

    result = subprocess.run(
        [sys.executable, str(_SCRIPT), "--check"],
        capture_output=True,
        text=True,
        cwd=str(_REPO_ROOT),
        timeout=300,
    )

    after = {
        path: path.stat().st_mtime_ns
        for path in sorted(_REAL_SEAMS_DIR.rglob("*"))
        if path.is_file()
    }
    assert result.returncode == 0
    assert before == after


def test_json_flag_writes_the_failure_list(tmp_path: Path) -> None:
    report = tmp_path / "report.json"

    subprocess.run(
        [
            sys.executable,
            str(_SCRIPT),
            "--check",
            "--require-crossing-tests",
            "--json",
            str(report),
        ],
        capture_output=True,
        text=True,
        cwd=str(_REPO_ROOT),
        timeout=300,
    )

    assert report.is_file()
    assert "crossing_test: null" in report.read_text(encoding="utf-8")

# --------------------------------------------------------------------------
# adversarial-review regressions (2026-09-02)
# --------------------------------------------------------------------------


def test_symbol_index_ignores_untracked_files(
    checker: types.ModuleType, tmp_path: Path
) -> None:
    """An untracked file must not satisfy a manifest symbol.

    The canonical gate materializes HEAD into a fresh worktree, so a symbol
    resolved from uncommitted work passes locally and fails in the gate. Review
    proved the raw disk walk accepted a planted untracked module.
    """
    repo = tmp_path / "repo"
    pkg = repo / "src" / "probos" / "demo"
    pkg.mkdir(parents=True)
    (pkg / "tracked.py").write_text("class Tracked: ...\n", encoding="utf-8")
    (pkg / "untracked.py").write_text("class Untracked: ...\n", encoding="utf-8")
    for args in (
        ("init", "-q"),
        ("add", "src/probos/demo/tracked.py"),
        ("-c", "user.name=t", "-c", "user.email=t@t.invalid",
         "commit", "-q", "-m", "tracked only"),
    ):
        subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)

    checker._INDEX_CACHE.clear()
    index = checker.build_symbol_index(repo / "src")

    assert checker.resolve_symbol("probos.demo.tracked.Tracked", index) is None
    assert checker.resolve_symbol("probos.demo.untracked.Untracked", index) is not None


def test_tracked_python_files_returns_none_outside_a_git_repo(
    checker: types.ModuleType, tmp_path: Path
) -> None:
    """Fail visibly to the disk walk rather than silently indexing nothing."""
    plain = tmp_path / "plain"
    (plain / "src").mkdir(parents=True)

    assert checker._tracked_python_files(plain / "src") is None


@pytest.mark.parametrize("value", ["", "   ", "\t"])
def test_blank_crossing_test_is_rejected_as_malformed(
    checker: types.ModuleType, tmp_path: Path, value: str
) -> None:
    """Present-but-blank is malformed input, not 'no test declared yet'.

    Branching on truthiness alone let a blank string bypass collection
    validation in default mode and only surface under --require-crossing-tests.
    """
    document = _manifest(seams=[_entry(crossing_test=value)])
    seams_dir = _write_manifest(tmp_path, document)

    errors = checker.validate(
        seams_dir=seams_dir,
        src_root=_synthetic_src(tmp_path),
        repo_root=tmp_path,
        require_crossing_tests=False,
    )

    assert any("present but blank" in error for error in errors)


def test_null_crossing_test_is_not_reported_as_blank(
    checker: types.ModuleType, tmp_path: Path
) -> None:
    """null is the sanctioned way to say 'no crossing test yet' in slice 1."""
    document = _manifest(seams=[_entry(crossing_test=None)])
    seams_dir = _write_manifest(tmp_path, document)

    errors = checker.validate(
        seams_dir=seams_dir,
        src_root=_synthetic_src(tmp_path),
        repo_root=tmp_path,
        require_crossing_tests=False,
    )

    assert not any("present but blank" in error for error in errors)
