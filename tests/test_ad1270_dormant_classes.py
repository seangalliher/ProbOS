"""AD-1270 (#1324) slice 2: the dormant-class check is report-only, finds a class nothing live uses
by the rules its docstring states, and keeps a disposition-only baseline current.

The check is loaded by path, as it is run. Every finding case scans a fixture tree under
``tmp_path``. The one real-tree case asserts only that the check runs and exits 0, so nothing in
the suite depends on what the real tree contains: the check stays report-only (decision D4).
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SCRIPT = _REPO_ROOT / "scripts" / "check_dormant_classes.py"


def _load_checker():
    spec = importlib.util.spec_from_file_location("_ad1270_dormant_classes", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


checker = _load_checker()


def _tree(root: Path, files: dict[str, str]) -> Path:
    for relative, text in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")
    return root


# --- T1: what is and is not a use ---------------------------------------------------

_DEFS = '''\
"""Fixture module: the classes under test."""
from dataclasses import dataclass
from enum import Enum
from typing import Protocol, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class SelfRef:
    def clone(self):
        return SelfRef()


class Called: ...
class AttrRead: ...
class ByName: ...
class Subclassed: ...
class LoopValue: ...
class ByString: ...
class ByDottedString: ...
class OnlyImported: ...
class OnlyAnnotated: ...
class OnlyAssigned: ...
class OnlyAll: ...
class OnlyIsinstance: ...
class OnlyIdentity: ...
class OnlyTypeChecking: ...
class OnlyDocstring: ...
class UsedByLiveHelper: ...
class UsedByDeadHelper: ...
class UsedAtModuleLevel: ...
class SchemaModel(BaseModel): ...
class SchemaChild(SchemaModel): ...
class Kind(Enum): ...
class Port(Protocol): ...
class TypedPort(Protocol[T]): ...
class Failure(ValueError): ...
class _Private: ...


@register
class Registered: ...


@dataclass(frozen=True)
class DataOnly: ...


__all__ = ["OnlyAll"]
DEFAULT = UsedAtModuleLevel


def live_helper():
    return _middle()


def _middle():
    return UsedByLiveHelper()


def dead_helper():
    return UsedByDeadHelper()
'''

_USER = '''\
import typing

from pkg import defs
from pkg.defs import ByName, OnlyAnnotated, OnlyIdentity, OnlyImported, OnlyIsinstance

if typing.TYPE_CHECKING:
    from pkg.defs import OnlyTypeChecking

    Alias = OnlyTypeChecking

CURRENT: OnlyAnnotated | None = None
OnlyAssigned = None


def run(x: OnlyAnnotated) -> OnlyAnnotated:
    """Mentions OnlyDocstring in prose."""
    defs.Called()
    defs.AttrRead.make()
    ByName()
    for cls in (defs.LoopValue,):
        cls()
    getattr(defs, "ByString")
    target = "pkg.defs.ByDottedString"
    defs.live_helper()
    if isinstance(x, OnlyIsinstance) or type(x) is OnlyIdentity:
        return x
    return target


class Child(defs.Subclassed): ...
'''

_EXPECTED_DORMANT = [
    "pkg/defs.py::DataOnly",
    "pkg/defs.py::OnlyAll",
    "pkg/defs.py::OnlyAnnotated",
    "pkg/defs.py::OnlyAssigned",
    "pkg/defs.py::OnlyDocstring",
    "pkg/defs.py::OnlyIdentity",
    "pkg/defs.py::OnlyImported",
    "pkg/defs.py::OnlyIsinstance",
    "pkg/defs.py::OnlyTypeChecking",
    "pkg/defs.py::SelfRef",
    "pkg/defs.py::UsedByDeadHelper",
    "pkg/user.py::Child",
]


def test_a_class_is_dormant_unless_something_live_uses_it_as_a_value(tmp_path: Path) -> None:
    source = _tree(tmp_path / "src", {"pkg/defs.py": _DEFS, "pkg/user.py": _USER})

    report = checker.build_report(source)

    assert [candidate.key for candidate in report.dormant] == _EXPECTED_DORMANT
    assert report.warnings == []


# --- T2: the findings ---------------------------------------------------------------

_SEVEN = ("Alpha", "Beta", "Gamma", "Delta", "Epsilon", "Zeta", "Eta")


def test_the_check_lists_new_incomplete_and_no_longer_dormant_rows(tmp_path: Path) -> None:
    source = _tree(tmp_path / "src", {"pkg/a.py": "".join(f"class {name}: ...\n" for name in _SEVEN)})
    rows = {
        "pkg/a.py::Alpha": {"disposition": "wire", "owner": "#1324"},
        "pkg/a.py::Beta": {"disposition": "unreviewed"},
        "pkg/a.py::Gamma": {"disposition": "staged"},
        "pkg/a.py::Delta": {"disposition": "false-positive"},
        "pkg/a.py::Epsilon": {"disposition": "maybe"},
        "pkg/a.py::Zeta": {"disposition": "staged", "owner": "AD-1288"},
        "pkg/gone.py::Ghost": {"disposition": "wire", "owner": "#1"},
    }

    output = checker.render(checker.build_report(source), rows)

    assert output.splitlines() == [
        f"{checker.PREFIX}7 dormant class(es): 1 new, 4 without a reviewed disposition, "
        "1 baseline row(s) no longer dormant; this check warns and never fails",
        "  new: pkg/a.py:7 Eta",
        "  unreviewed: pkg/a.py:2 Beta",
        "  false-positive without a note: pkg/a.py:4 Delta",
        "  unknown disposition 'maybe': pkg/a.py:5 Epsilon",
        "  staged without an owner issue or AD: pkg/a.py:3 Gamma",
        "  no longer dormant (remove the row): pkg/gone.py::Ghost",
    ]


# --- T3, T4: the baseline -------------------------------------------------------------


def test_updating_the_baseline_keeps_reviewed_rows_adds_new_ones_and_drops_the_rest(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = _tree(tmp_path / "src", {"pkg/a.py": "class Alpha: ...\nclass Beta: ...\n"})
    baseline = tmp_path / "baseline.yaml"
    baseline.write_text(yaml.safe_dump({"schema_version": 1, "classes": {
        "pkg/a.py::Alpha": {"disposition": "wire", "owner": "#1324", "note": "slice 3"},
        "pkg/gone.py::Ghost": {"disposition": "retire", "owner": "#1"},
    }}), encoding="utf-8")
    argv = ["--update-baseline", "--src", str(source), "--baseline", str(baseline)]

    assert checker.main(argv) == 0
    first = baseline.read_bytes()
    assert checker.main(argv) == 0

    assert baseline.read_bytes() == first  # a second run changes nothing
    assert first.startswith(checker.HEADER.encode("ascii"))
    assert b"\r" not in first
    assert yaml.safe_load(first.decode("utf-8")) == {
        "schema_version": 1,
        "classes": {
            "pkg/a.py::Alpha": {"disposition": "wire", "owner": "#1324", "note": "slice 3"},
            "pkg/a.py::Beta": {"disposition": "unreviewed"},
        },
    }
    output = capsys.readouterr().out
    assert "  warning: baseline rewritten: " in output
    assert "  unreviewed: pkg/a.py:2 Beta" in output


_KEPT = "schema_version: 1\nclasses:\n  pkg/gone.py::Ghost:\n    disposition: retire\n    owner: '#1'\n"


@pytest.mark.parametrize("case", ["an incomplete scan", "an unreadable baseline", "a baseline with no classes mapping"])
def test_the_baseline_is_not_rewritten_from_an_incomplete_scan_or_an_unreadable_baseline(
    case: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    files = {"pkg/a.py": "class Alpha: ...\n"}
    if case == "an incomplete scan":
        files["pkg/broken.py"] = "def (:\n"
    source = _tree(tmp_path / "src", files)
    text = {"an unreadable baseline": "classes: [unclosed\n", "a baseline with no classes mapping": "schema_version: 1\n"}.get(
        case, _KEPT
    )
    baseline = tmp_path / "baseline.yaml"
    baseline.write_bytes(text.encode("utf-8"))

    assert checker.main(["--update-baseline", "--src", str(source), "--baseline", str(baseline)]) == 0

    assert baseline.read_bytes() == text.encode("utf-8")
    assert "baseline not rewritten" in capsys.readouterr().out


# --- T5 to T8: report-only, host-independent ---------------------------------------------

_EXIT_CASES = {
    "the real tree": ([], ""),
    "a missing baseline": (["--src", "{tmp}/src", "--baseline", "{tmp}/absent.yaml"], "no baseline at"),
    "a malformed baseline": (["--src", "{tmp}/src", "--baseline", "{tmp}/broken.yaml"], "baseline not read ("),
    "a source file that does not parse": (
        ["--src", "{tmp}/src", "--baseline", "{tmp}/absent.yaml"], "skipped broken.py: SyntaxError"
    ),
    "a missing source root": (["--src", "{tmp}/nowhere", "--baseline", "{tmp}/absent.yaml"], "is not a directory"),
    "an unknown argument": (
        ["--strict", "--src", "{tmp}/src", "--baseline", "{tmp}/absent.yaml"], "ignored argument '--strict'"
    ),
    "an argument without its value": (["--baseline"], "could not parse the arguments"),
    "both modes at once": (["--check", "--update-baseline"], "could not parse the arguments"),
    "a baseline in a missing directory": (
        ["--update-baseline", "--src", "{tmp}/clean", "--baseline", "{tmp}/missing/dir/b.yaml"],
        "could not run: FileNotFoundError",
    ),
}


@pytest.mark.parametrize("case", sorted(_EXIT_CASES))
def test_the_check_exits_zero_on_every_input(case: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (tmp_path / "broken.yaml").write_text("classes: [unclosed\n", encoding="utf-8")
    _tree(tmp_path / "src", {"broken.py": "def (:\n", "pkg/a.py": "class Alpha: ...\n"})
    _tree(tmp_path / "clean", {"pkg/a.py": "class Alpha: ...\n"})
    template, expected = _EXIT_CASES[case]
    argv = [part.format(tmp=tmp_path.as_posix()) for part in template]

    assert checker.main(argv) == 0

    output = capsys.readouterr().out
    assert output.startswith(checker.PREFIX)
    assert expected in output


def test_the_command_line_exits_zero_with_lf_utf8_output(tmp_path: Path) -> None:
    source = _tree(tmp_path / "src", {"pkg/a.py": "class Alpha: ...\n"})
    completed = subprocess.run(
        [sys.executable, "-P", str(_SCRIPT), "--src", str(source), "--baseline", str(tmp_path / "absent.yaml")],
        capture_output=True, timeout=300, cwd=_REPO_ROOT,
    )

    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.startswith(checker.PREFIX.encode("ascii"))
    assert completed.stdout.endswith(b"\n")
    assert b"\r" not in completed.stdout
    assert b"  new: pkg/a.py:1 Alpha\n" in completed.stdout


def test_the_output_names_no_absolute_path(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (tmp_path / "broken.yaml").write_text("classes: [unclosed\n", encoding="utf-8")

    checker.main(["--src", str(tmp_path / "nowhere"), "--baseline", str(tmp_path / "broken.yaml")])

    output = capsys.readouterr().out
    assert "nowhere" in output and "broken.yaml" in output
    assert str(tmp_path) not in output
    assert tmp_path.as_posix() not in output


def test_modules_are_read_in_posix_path_order_on_every_host(tmp_path: Path) -> None:
    source = _tree(tmp_path / "src", {"pkg/a.py": "def (:\n", "pkg/B.py": "def (:\n"})

    report = checker.build_report(source)

    assert report.warnings == ["skipped pkg/B.py: SyntaxError", "skipped pkg/a.py: SyntaxError"]
