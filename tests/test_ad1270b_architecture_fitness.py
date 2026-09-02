"""AD-1270b slice 2: stated architecture principles must actually be measured.

The repository states review triggers -- a ~500-line / ~15-method SRP trigger,
lower-to-higher layer imports, direct database connections outside approved
adapters, unowned ``asyncio.create_task`` calls -- and nothing counted them.
``scripts/check_architecture_principles.py`` measures them against a reviewed
frozen baseline and fails on any difference in either direction.

These tests cover both halves: the real committed baseline stays valid (the
currency guard, which also runs in gate preflight), and the checker actually
rejects each defect class rather than passing unconditionally. A check that
cannot fail is not a gate, and a check that always fails is not a predicate --
so every injected violation is paired with a negative control that must NOT
fire.

Fix a currency failure with::

    python scripts/check_architecture_principles.py --check
    python scripts/check_architecture_principles.py --update-baseline
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import types
from pathlib import Path
from typing import Any

import pytest
import yaml

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SCRIPT = _REPO_ROOT / "scripts" / "check_architecture_principles.py"
_REAL_BASELINE = _REPO_ROOT / "docs" / "development" / "architecture-baseline.yaml"

_LAYERS = {
    "substrate": 0,
    "mesh": 1,
    "consensus": 2,
    "cognitive": 3,
    "experience": 4,
}


@pytest.fixture(scope="module")
def checker() -> types.ModuleType:
    """Import the checker from its path -- ``scripts/`` is not a package.

    Registered in ``sys.modules`` before execution because the module defines
    dataclasses and, under PEP 563, the dataclass machinery re-reads each
    annotation out of ``sys.modules[cls.__module__]``.
    """
    spec = importlib.util.spec_from_file_location(
        "check_architecture_principles", _SCRIPT
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["check_architecture_principles"] = module
    spec.loader.exec_module(module)
    return module


# ---------------------------------------------------------------------------
# Synthetic tree helpers
# ---------------------------------------------------------------------------


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


def _make_repo(tmp_path: Path, files: dict[str, str]) -> Path:
    """A real git repo whose ``src``/``tests`` files are all **committed**.

    Committed rather than merely written, because the checker indexes from
    ``git ls-files``: an untracked fixture would be invisible and every
    assertion below would pass vacuously.
    """
    repo = tmp_path / "repo"
    (repo / "src").mkdir(parents=True, exist_ok=True)
    (repo / "tests").mkdir(parents=True, exist_ok=True)
    _git(repo, "init", "-q")
    for relative, text in files.items():
        target = repo / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    _git(repo, "add", "-A")
    _git(
        repo,
        "-c",
        "user.name=t",
        "-c",
        "user.email=t@t.invalid",
        "commit",
        "-q",
        "-m",
        "fixture",
    )
    return repo


def _baseline_document(violations: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "baseline_id": "fixture",
        "owner": "AD-1270b",
        "tracking_issue": 1324,
        "source_commit": "0" * 40,
        "layers": dict(_LAYERS),
        "gating_categories": [
            "srp-size",
            "layer-import",
            "db-connect",
            "unowned-task",
        ],
        "report_only_categories": {
            "private-access": {
                "reason": "r",
                "promotion": "p",
                "owner": "AD-1270b",
            },
            "source-text-tests": {
                "reason": "r",
                "promotion": "p",
                "owner": "AD-1270b",
            },
        },
        "violations": violations if violations is not None else [],
    }


def _row(**overrides: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "category": "db-connect",
        "key": "probos.demo.store::Store.open",
        "callee": "sqlite3.connect",
        "count": 1,
        "disposition": "debt",
        "owner": "AD-1256",
        "rationale": "fixture row",
        "review_by": "AD-1256 completion",
    }
    row.update(overrides)
    return row


def _write_baseline(
    tmp_path: Path, document: Any, name: str = "architecture-baseline.yaml"
) -> Path:
    path = tmp_path / name
    text = (
        document
        if isinstance(document, str)
        else yaml.safe_dump(document, sort_keys=False)
    )
    path.write_text(text, encoding="utf-8")
    return path


def _run(
    checker: types.ModuleType, repo: Path, baseline: Path
) -> Any:
    return checker.check(
        baseline_path=baseline,
        src_root=repo / "src",
        tests_root=repo / "tests",
    )


def _categories(result: Any) -> dict[str, Any]:
    return result.report["categories"]


CLEAN_SOURCE = "class Small:\n    def one(self) -> None: ...\n"


# ---------------------------------------------------------------------------
# Live-baseline currency
# ---------------------------------------------------------------------------


def test_the_checker_script_exists() -> None:
    assert _SCRIPT.is_file(), (
        "scripts/check_architecture_principles.py is missing; the stated "
        "architecture principles are unmeasured without it"
    )


def test_committed_baseline_passes_check_in_a_subprocess() -> None:
    """Runs the real command a developer and gate preflight are told to run."""
    result = subprocess.run(
        [sys.executable, str(_SCRIPT), "--check"],
        capture_output=True,
        text=True,
        cwd=str(_REPO_ROOT),
        timeout=300,
    )

    assert result.returncode == 0, (
        "the committed architecture baseline does not match the tree.\n"
        "Re-check with: python scripts/check_architecture_principles.py --check\n"
        "Regenerate rows with: --update-baseline, then review every added row.\n\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )


def test_check_mode_writes_nothing_into_the_repository() -> None:
    """Gate preflight fails the whole run if a phase mutates the tree."""
    before = _REAL_BASELINE.stat().st_mtime_ns

    result = subprocess.run(
        [sys.executable, str(_SCRIPT), "--check"],
        capture_output=True,
        text=True,
        cwd=str(_REPO_ROOT),
        timeout=300,
    )

    assert result.returncode == 0
    assert _REAL_BASELINE.stat().st_mtime_ns == before


def test_committed_baseline_carries_review_metadata_on_every_row() -> None:
    """The format's whole point is that a row means somebody reviewed it."""
    document = yaml.safe_load(_REAL_BASELINE.read_text(encoding="utf-8"))

    assert document["violations"], "an empty baseline would gate nothing"
    for row in document["violations"]:
        assert row["disposition"] in {"approved", "debt"}
        for required in ("owner", "rationale", "review_by"):
            assert str(row.get(required) or "").strip(), (
                f"{row['category']} {row['key']} has a blank {required!r}"
            )


def test_committed_baseline_stores_no_magnitudes() -> None:
    """Storing 10,598 next to CognitiveAgent would rewrite this file on every edit."""
    document = yaml.safe_load(_REAL_BASELINE.read_text(encoding="utf-8"))

    allowed = {
        "category",
        "key",
        "triggers",
        "callee",
        "count",
        "disposition",
        "owner",
        "rationale",
        "review_by",
    }
    for row in document["violations"]:
        assert set(row) <= allowed, f"unexpected field(s) in {row['key']}: {set(row) - allowed}"
    text = _REAL_BASELINE.read_text(encoding="utf-8")
    assert "body_lines" not in text
    assert "direct_methods" not in text


def test_committed_baseline_paths_are_posix_and_dotted() -> None:
    """A WindowsPath repr in a committed artifact is permanently stale on Linux."""
    text = _REAL_BASELINE.read_text(encoding="utf-8")

    assert "WindowsPath" not in text
    assert "PosixPath" not in text
    assert "\\\\" not in text
    document = yaml.safe_load(text)
    for row in document["violations"]:
        assert "\\" not in row["key"]


# ---------------------------------------------------------------------------
# Injected violations -- one per gating category
# ---------------------------------------------------------------------------


def test_injected_srp_size_oversized_class_fails(
    checker: types.ModuleType, tmp_path: Path
) -> None:
    body = "".join(f"    x{index} = {index}\n" for index in range(501))
    repo = _make_repo(tmp_path, {"src/probos/demo/big.py": f"class Big:\n{body}"})

    result = _run(checker, repo, _write_baseline(tmp_path, _baseline_document()))

    assert any(
        "NEW VIOLATION [srp-size] probos.demo.big::Big" in error
        for error in result.errors
    ), result.errors
    assert _categories(result)["srp-size"]["current"] == 1


def test_injected_srp_size_too_many_methods_fails(
    checker: types.ModuleType, tmp_path: Path
) -> None:
    methods = "".join(f"    def m{index}(self) -> None: ...\n" for index in range(16))
    repo = _make_repo(tmp_path, {"src/probos/demo/wide.py": f"class Wide:\n{methods}"})

    result = _run(checker, repo, _write_baseline(tmp_path, _baseline_document()))

    new = [e for e in result.errors if e.startswith("NEW VIOLATION [srp-size]")]
    assert len(new) == 1 and "probos.demo.wide::Wide" in new[0]
    row = next(f for f in result.findings if f.category == "srp-size")
    assert row.triggers == ("methods",)


def test_injected_layer_import_fails(
    checker: types.ModuleType, tmp_path: Path
) -> None:
    repo = _make_repo(
        tmp_path,
        {
            "src/probos/substrate/x.py": "from probos.cognitive.y import Z\n",
            "src/probos/cognitive/y.py": "class Z: ...\n",
        },
    )

    result = _run(checker, repo, _write_baseline(tmp_path, _baseline_document()))

    assert any(
        "NEW VIOLATION [layer-import] probos.substrate.x -> probos.cognitive.y"
        in error
        for error in result.errors
    ), result.errors


def test_injected_db_connect_fails(
    checker: types.ModuleType, tmp_path: Path
) -> None:
    repo = _make_repo(
        tmp_path,
        {
            "src/probos/demo/store.py": (
                "import sqlite3\n\n\ndef open_it():\n"
                '    return sqlite3.connect(":memory:")\n'
            )
        },
    )

    result = _run(checker, repo, _write_baseline(tmp_path, _baseline_document()))

    assert any(
        "NEW VIOLATION [db-connect] probos.demo.store::open_it" in error
        and "sqlite3.connect" in error
        for error in result.errors
    ), result.errors


def test_injected_unowned_task_fails(
    checker: types.ModuleType, tmp_path: Path
) -> None:
    repo = _make_repo(
        tmp_path,
        {
            "src/probos/demo/loop.py": (
                "import asyncio\n\n\nasync def go():\n"
                "    asyncio.create_task(f())\n"
            )
        },
    )

    result = _run(checker, repo, _write_baseline(tmp_path, _baseline_document()))

    assert any(
        "NEW VIOLATION [unowned-task] probos.demo.loop::go" in error
        for error in result.errors
    ), result.errors


# ---------------------------------------------------------------------------
# Negative controls -- the predicate must discriminate, not always fire
# ---------------------------------------------------------------------------


def test_class_just_under_both_srp_triggers_does_not_fire(
    checker: types.ModuleType, tmp_path: Path
) -> None:
    """499 body lines and 15 methods: one line either side of the trigger."""
    lines = "".join(f"    x{index} = {index}\n" for index in range(498))
    methods = "".join(f"    def m{index}(self) -> None: ...\n" for index in range(15))
    repo = _make_repo(
        tmp_path,
        {
            "src/probos/demo/tall.py": f"class Tall:\n{lines}",
            "src/probos/demo/wide.py": f"class Wide:\n{methods}",
        },
    )

    result = _run(checker, repo, _write_baseline(tmp_path, _baseline_document()))

    assert result.errors == []
    assert _categories(result)["srp-size"]["current"] == 0


def test_type_checking_import_does_not_fire(
    checker: types.ModuleType, tmp_path: Path
) -> None:
    """The exact edge the reviewed baseline allowed. Mandatory control."""
    repo = _make_repo(
        tmp_path,
        {
            "src/probos/substrate/x.py": (
                "from typing import TYPE_CHECKING\n\n"
                "if TYPE_CHECKING:\n"
                "    from probos.cognitive.y import Z\n"
            ),
            "src/probos/cognitive/y.py": "class Z: ...\n",
        },
    )

    result = _run(checker, repo, _write_baseline(tmp_path, _baseline_document()))

    assert result.errors == []
    assert _categories(result)["layer-import"]["current"] == 0


def test_typing_dot_type_checking_import_does_not_fire(
    checker: types.ModuleType, tmp_path: Path
) -> None:
    """``if typing.TYPE_CHECKING:`` is the same edge spelled differently."""
    repo = _make_repo(
        tmp_path,
        {
            "src/probos/substrate/x.py": (
                "import typing\n\n"
                "if typing.TYPE_CHECKING:\n"
                "    from probos.cognitive.y import Z\n"
            ),
            "src/probos/cognitive/y.py": "class Z: ...\n",
        },
    )

    result = _run(checker, repo, _write_baseline(tmp_path, _baseline_document()))

    assert result.errors == []


def test_intra_package_import_does_not_fire(
    checker: types.ModuleType, tmp_path: Path
) -> None:
    """The artifact that made cross_layer_analysis.py report 1,981 rows."""
    repo = _make_repo(
        tmp_path,
        {
            "src/probos/cognitive/a.py": "from probos.cognitive.b import B\n",
            "src/probos/cognitive/b.py": "class B: ...\n",
        },
    )

    result = _run(checker, repo, _write_baseline(tmp_path, _baseline_document()))

    assert result.errors == []
    assert _categories(result)["layer-import"]["current"] == 0


def test_higher_to_lower_import_does_not_fire(
    checker: types.ModuleType, tmp_path: Path
) -> None:
    """cognitive -> substrate is the allowed direction."""
    repo = _make_repo(
        tmp_path,
        {
            "src/probos/cognitive/a.py": "from probos.substrate.b import B\n",
            "src/probos/substrate/b.py": "class B: ...\n",
        },
    )

    result = _run(checker, repo, _write_baseline(tmp_path, _baseline_document()))

    assert result.errors == []


def test_unranked_package_import_does_not_fire(
    checker: types.ModuleType, tmp_path: Path
) -> None:
    """An unranked package is neither a source nor a target of any layer rule."""
    repo = _make_repo(
        tmp_path,
        {
            "src/probos/toolbox/a.py": "from probos.cognitive.b import B\n",
            "src/probos/cognitive/b.py": "class B: ...\n",
        },
    )

    result = _run(checker, repo, _write_baseline(tmp_path, _baseline_document()))

    assert result.errors == []
    assert "toolbox" in _categories(result)["layer-import"]["unranked_top_level"]


def test_assigned_and_domain_create_task_do_not_fire(
    checker: types.ModuleType, tmp_path: Path
) -> None:
    """Ownership, not syntax: a retained reference and a domain method both pass."""
    repo = _make_repo(
        tmp_path,
        {
            "src/probos/demo/owned.py": (
                "import asyncio\n\n\nasync def go(work_store):\n"
                "    t = asyncio.create_task(f())\n"
                "    work_store.create_task(payload)\n"
                "    asyncio.create_task(g()).add_done_callback(h)\n"
                "    return t\n"
            )
        },
    )

    result = _run(checker, repo, _write_baseline(tmp_path, _baseline_document()))

    assert result.errors == []
    assert _categories(result)["unowned-task"]["current"] == 0


def test_loop_create_task_bare_statement_does_fire(
    checker: types.ModuleType, tmp_path: Path
) -> None:
    """The loop-receiver half of the narrowed predicate, so it is not dead."""
    repo = _make_repo(
        tmp_path,
        {
            "src/probos/demo/looped.py": (
                "def go(loop):\n    loop.create_task(f())\n"
            )
        },
    )

    result = _run(checker, repo, _write_baseline(tmp_path, _baseline_document()))

    assert any(
        "NEW VIOLATION [unowned-task] probos.demo.looped::go" in error
        for error in result.errors
    ), result.errors


def test_a_clean_tree_against_an_empty_baseline_passes(
    checker: types.ModuleType, tmp_path: Path
) -> None:
    """The whole-check negative control: no findings, no errors, exit-0 shape."""
    repo = _make_repo(tmp_path, {"src/probos/demo/ok.py": CLEAN_SOURCE})

    result = _run(checker, repo, _write_baseline(tmp_path, _baseline_document()))

    assert result.errors == []
    assert all(
        _categories(result)[name]["current"] == 0
        for name in ("srp-size", "layer-import", "db-connect", "unowned-task")
    )


# ---------------------------------------------------------------------------
# Symmetric difference: stale rows and count drift
# ---------------------------------------------------------------------------


def test_stale_baseline_row_fails_and_names_the_row_to_delete(
    checker: types.ModuleType, tmp_path: Path
) -> None:
    """A violation that was FIXED must shrink the baseline in the same commit.

    Without this the baseline rots into a list of things that used to be true,
    and a genuinely new violation can hide behind a stale row's key.
    """
    repo = _make_repo(tmp_path, {"src/probos/demo/ok.py": CLEAN_SOURCE})
    baseline = _write_baseline(
        tmp_path,
        _baseline_document([_row(key="probos.demo.gone::Store.open")]),
    )

    result = _run(checker, repo, baseline)

    stale = [e for e in result.errors if e.startswith("STALE BASELINE ROW")]
    assert len(stale) == 1
    assert "probos.demo.gone::Store.open" in stale[0]
    assert "Delete this row" in stale[0]
    assert "--update-baseline" in stale[0]


def test_stale_srp_row_fails_when_the_class_shrinks(
    checker: types.ModuleType, tmp_path: Path
) -> None:
    """The realistic fix path: a god class gets decomposed below the trigger."""
    repo = _make_repo(tmp_path, {"src/probos/demo/now_small.py": CLEAN_SOURCE})
    baseline = _write_baseline(
        tmp_path,
        _baseline_document(
            [
                _row(
                    category="srp-size",
                    key="probos.demo.now_small::Small",
                    triggers=["lines"],
                    callee=None,
                    count=1,
                    owner="AD-1270h",
                    review_by="AD-1270h closeout",
                )
            ]
        ),
    )

    result = _run(checker, repo, baseline)

    assert any(
        "STALE BASELINE ROW [srp-size] probos.demo.now_small::Small" in error
        for error in result.errors
    ), result.errors


def test_count_drift_upward_fails(
    checker: types.ModuleType, tmp_path: Path
) -> None:
    """A SECOND connect added to an already-frozen symbol.

    Key-set difference alone cannot see this, which is why ``count`` is frozen
    as payload.
    """
    repo = _make_repo(
        tmp_path,
        {
            "src/probos/demo/store.py": (
                "import sqlite3\n\n\nclass Store:\n"
                "    def open(self):\n"
                '        a = sqlite3.connect(":memory:")\n'
                '        b = sqlite3.connect(":memory:")\n'
                "        return a, b\n"
            )
        },
    )
    baseline = _write_baseline(tmp_path, _baseline_document([_row(count=1)]))

    result = _run(checker, repo, baseline)

    drift = [e for e in result.errors if e.startswith("COUNT DRIFT")]
    assert len(drift) == 1
    assert "rose from 1 to 2" in drift[0]


def test_count_drift_downward_also_fails(
    checker: types.ModuleType, tmp_path: Path
) -> None:
    """A partial fix must update the reviewed row, not sit silently."""
    repo = _make_repo(
        tmp_path,
        {
            "src/probos/demo/store.py": (
                "import sqlite3\n\n\nclass Store:\n"
                "    def open(self):\n"
                '        return sqlite3.connect(":memory:")\n'
            )
        },
    )
    baseline = _write_baseline(tmp_path, _baseline_document([_row(count=2)]))

    result = _run(checker, repo, baseline)

    assert any("fell from 2 to 1" in error for error in result.errors), result.errors


def test_trigger_drift_fails(
    checker: types.ModuleType, tmp_path: Path
) -> None:
    """A class frozen as lines-only that grows past the method trigger too."""
    methods = "".join(f"    def m{index}(self) -> None: ...\n" for index in range(16))
    repo = _make_repo(tmp_path, {"src/probos/demo/wide.py": f"class Wide:\n{methods}"})
    baseline = _write_baseline(
        tmp_path,
        _baseline_document(
            [
                _row(
                    category="srp-size",
                    key="probos.demo.wide::Wide",
                    triggers=["lines"],
                    callee=None,
                    owner="AD-1270h",
                    review_by="AD-1270h closeout",
                )
            ]
        ),
    )

    result = _run(checker, repo, baseline)

    assert any(
        "TRIGGER DRIFT [srp-size] probos.demo.wide::Wide" in error
        for error in result.errors
    ), result.errors


def test_a_frozen_violation_that_still_exists_passes(
    checker: types.ModuleType, tmp_path: Path
) -> None:
    """Accepted debt must not fail, or the gate is unusable on day one."""
    repo = _make_repo(
        tmp_path,
        {
            "src/probos/demo/store.py": (
                "import sqlite3\n\n\nclass Store:\n"
                "    def open(self):\n"
                '        return sqlite3.connect(":memory:")\n'
            )
        },
    )
    baseline = _write_baseline(tmp_path, _baseline_document([_row()]))

    result = _run(checker, repo, baseline)

    assert result.errors == []


def test_fixing_one_violation_and_adding_another_still_fails(
    checker: types.ModuleType, tmp_path: Path
) -> None:
    """The exact case a count-only gate would wave through.

    Total stays at one; the baseline is still wrong in both directions.
    """
    repo = _make_repo(
        tmp_path,
        {
            "src/probos/demo/other.py": (
                "import sqlite3\n\n\nclass Other:\n"
                "    def open(self):\n"
                '        return sqlite3.connect(":memory:")\n'
            )
        },
    )
    baseline = _write_baseline(tmp_path, _baseline_document([_row()]))

    result = _run(checker, repo, baseline)

    assert any(e.startswith("NEW VIOLATION") for e in result.errors)
    assert any(e.startswith("STALE BASELINE ROW") for e in result.errors)


# ---------------------------------------------------------------------------
# Untracked files must be invisible (slice 1's review found this defect)
# ---------------------------------------------------------------------------


def test_untracked_violation_is_invisible(
    checker: types.ModuleType, tmp_path: Path
) -> None:
    """An untracked file must not change the result, in either direction.

    The canonical gate materializes HEAD into a fresh worktree, so anything
    satisfied -- or broken -- by uncommitted work behaves differently there.
    Slice 1's adversarial review proved a raw disk walk accepted a planted
    untracked module; this is the regression test for the same defect class.
    """
    repo = _make_repo(tmp_path, {"src/probos/demo/ok.py": CLEAN_SOURCE})
    baseline = _write_baseline(tmp_path, _baseline_document())

    before = _run(checker, repo, baseline)
    assert before.errors == []

    planted = repo / "src" / "probos" / "demo" / "untracked.py"
    planted.write_text(
        "import sqlite3\nimport asyncio\n\n\n"
        "class Sneaky:\n"
        "    def open(self):\n"
        '        return sqlite3.connect(":memory:")\n\n\n'
        "async def go():\n"
        "    asyncio.create_task(f())\n",
        encoding="utf-8",
    )
    status = subprocess.run(
        ["git", "status", "--short"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert "src/probos/demo/untracked.py" in status.replace("\\", "/")

    after = _run(checker, repo, baseline)

    assert after.errors == []
    assert not any("untracked" in finding.key for finding in after.findings)
    assert _categories(after)["db-connect"]["current"] == 0
    assert _categories(after)["unowned-task"]["current"] == 0


def test_the_same_violation_tracked_does_fire(
    checker: types.ModuleType, tmp_path: Path
) -> None:
    """Proves the previous test measured tracking, not a broken fixture.

    Without this pair, ``test_untracked_violation_is_invisible`` would pass
    just as happily against a checker that never detects anything.
    """
    repo = _make_repo(
        tmp_path,
        {
            "src/probos/demo/ok.py": CLEAN_SOURCE,
            "src/probos/demo/tracked_bad.py": (
                "import sqlite3\n\n\nclass Sneaky:\n"
                "    def open(self):\n"
                '        return sqlite3.connect(":memory:")\n'
            ),
        },
    )

    result = _run(checker, repo, _write_baseline(tmp_path, _baseline_document()))

    assert any(
        "NEW VIOLATION [db-connect] probos.demo.tracked_bad::Sneaky.open" in error
        for error in result.errors
    ), result.errors


def test_tracked_module_names_warns_and_falls_back_outside_a_git_repo(
    checker: types.ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Fail visibly to a disk walk rather than silently measuring nothing.

    An empty measurement would read as "no violations", which is the worst
    possible failure mode for a gate.
    """
    plain = tmp_path / "plain" / "src"
    plain.mkdir(parents=True)
    (plain / "mod.py").write_text("x = 1\n", encoding="utf-8")

    assert checker._tracked_python_files(plain) is None
    names = checker.tracked_module_names(plain)

    assert names == ["mod.py"]
    assert "git could not enumerate" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# Report-only categories must read as ungated, never as empty
# ---------------------------------------------------------------------------


def test_report_only_categories_do_not_gate(
    checker: types.ModuleType, tmp_path: Path
) -> None:
    """A new private-access reach-through and a new source-text test both pass."""
    repo = _make_repo(
        tmp_path,
        {
            "src/probos/demo/reach.py": (
                "def go(runtime):\n    return runtime._secret\n"
            ),
            "tests/test_demo.py": (
                "import inspect\n\n\ndef test_source():\n"
                "    assert inspect.getsource(go)\n"
            ),
        },
    )

    result = _run(checker, repo, _write_baseline(tmp_path, _baseline_document()))

    assert result.errors == []
    categories = _categories(result)
    assert categories["private-access"]["current"] == 1
    assert categories["source-text-tests"]["current"] == 1


def test_every_category_declares_its_mode(
    checker: types.ModuleType, tmp_path: Path
) -> None:
    """A consumer must never mistake an absent category for an empty one."""
    repo = _make_repo(tmp_path, {"src/probos/demo/ok.py": CLEAN_SOURCE})

    result = _run(checker, repo, _write_baseline(tmp_path, _baseline_document()))

    categories = _categories(result)
    assert set(categories) == set(checker.ALL_CATEGORIES)
    for name in checker.GATING_CATEGORIES:
        assert categories[name]["mode"] == "gating"
    for name in checker.REPORT_ONLY_CATEGORIES:
        assert categories[name]["mode"] == "report-only"
        assert categories[name]["promotion"]


def test_private_access_narrowing_drops_dunders_and_builtin_receivers(
    checker: types.ModuleType, tmp_path: Path
) -> None:
    """The narrowed figure is what the next slice has to classify."""
    repo = _make_repo(
        tmp_path,
        {
            "src/probos/demo/reach.py": (
                "def go(runtime, obj):\n"
                "    a = type(obj).__name__\n"
                "    b = runtime._secret\n"
                "    c = obj.__class__\n"
                "    return a, b, c\n"
            )
        },
    )

    result = _run(checker, repo, _write_baseline(tmp_path, _baseline_document()))

    private = _categories(result)["private-access"]
    assert private["current"] == 3
    assert private["dunder"] == 2
    assert private["narrowed"] == 1


def test_self_private_access_is_not_reach_through(
    checker: types.ModuleType, tmp_path: Path
) -> None:
    """``self._x`` is encapsulation working, not a violation of it."""
    repo = _make_repo(
        tmp_path,
        {
            "src/probos/demo/own.py": (
                "class A:\n    def go(self):\n        return self._x\n"
            )
        },
    )

    result = _run(checker, repo, _write_baseline(tmp_path, _baseline_document()))

    assert _categories(result)["private-access"]["current"] == 0


def test_source_text_prefilter_does_not_change_results(
    checker: types.ModuleType, tmp_path: Path
) -> None:
    """The parse prefilter must be an optimisation, never a predicate.

    A file mentioning the marker only in a comment is still parsed and still
    yields nothing; a file that really calls ``inspect.getsource`` is found.
    """
    repo = _make_repo(
        tmp_path,
        {
            "tests/test_comment.py": "# inspect.getsource is mentioned here\n",
            "tests/test_real.py": (
                "import inspect\n\n\ndef test_x():\n"
                "    assert inspect.getsource(test_x)\n"
            ),
            "tests/test_none.py": "def test_y():\n    assert True\n",
        },
    )

    result = _run(checker, repo, _write_baseline(tmp_path, _baseline_document()))

    rows = [f for f in result.findings if f.category == "source-text-tests"]
    assert len(rows) == 1
    assert rows[0].key == "tests/test_real.py::test_x"
    assert result.report["test_modules_scanned"] == 2
    assert result.report["test_files_tracked"] == 3


# ---------------------------------------------------------------------------
# Baseline schema validation
# ---------------------------------------------------------------------------


def test_missing_top_level_key_is_reported(
    checker: types.ModuleType, tmp_path: Path
) -> None:
    document = _baseline_document()
    del document["layers"]
    repo = _make_repo(tmp_path, {"src/probos/demo/ok.py": CLEAN_SOURCE})

    result = _run(checker, repo, _write_baseline(tmp_path, document))

    assert any("missing required top-level key 'layers'" in e for e in result.errors)


def test_absent_baseline_file_is_reported_with_the_fix_command(
    checker: types.ModuleType, tmp_path: Path
) -> None:
    repo = _make_repo(tmp_path, {"src/probos/demo/ok.py": CLEAN_SOURCE})

    result = checker.check(
        baseline_path=tmp_path / "absent.yaml",
        src_root=repo / "src",
        tests_root=repo / "tests",
    )

    assert any("does not exist" in e and "--update-baseline" in e for e in result.errors)


def test_unparseable_baseline_is_reported(
    checker: types.ModuleType, tmp_path: Path
) -> None:
    repo = _make_repo(tmp_path, {"src/probos/demo/ok.py": CLEAN_SOURCE})
    baseline = _write_baseline(tmp_path, "violations: [\n  - key: broken\n    :\n")

    result = _run(checker, repo, baseline)

    assert any("does not parse as YAML" in e for e in result.errors)


@pytest.mark.parametrize("field", ["owner", "rationale", "review_by"])
def test_blank_review_field_is_rejected(
    checker: types.ModuleType, tmp_path: Path, field: str
) -> None:
    """A row means somebody reviewed it; a blank field means nobody did."""
    repo = _make_repo(
        tmp_path,
        {
            "src/probos/demo/store.py": (
                "import sqlite3\n\n\nclass Store:\n"
                "    def open(self):\n"
                '        return sqlite3.connect(":memory:")\n'
            )
        },
    )
    baseline = _write_baseline(tmp_path, _baseline_document([_row(**{field: "  "})]))

    result = _run(checker, repo, baseline)

    assert any(f"{field!r} is missing or blank" in e for e in result.errors)


def test_bad_disposition_is_rejected(
    checker: types.ModuleType, tmp_path: Path
) -> None:
    repo = _make_repo(tmp_path, {"src/probos/demo/ok.py": CLEAN_SOURCE})
    baseline = _write_baseline(
        tmp_path, _baseline_document([_row(disposition="probably")])
    )

    result = _run(checker, repo, baseline)

    assert any("disposition 'probably' is not one of" in e for e in result.errors)


def test_unknown_category_is_rejected(
    checker: types.ModuleType, tmp_path: Path
) -> None:
    """A report-only category name in the gated rows is a category error."""
    repo = _make_repo(tmp_path, {"src/probos/demo/ok.py": CLEAN_SOURCE})
    baseline = _write_baseline(
        tmp_path, _baseline_document([_row(category="private-access")])
    )

    result = _run(checker, repo, baseline)

    assert any("category 'private-access' is not one of" in e for e in result.errors)


def test_duplicate_row_is_rejected(
    checker: types.ModuleType, tmp_path: Path
) -> None:
    repo = _make_repo(tmp_path, {"src/probos/demo/ok.py": CLEAN_SOURCE})
    baseline = _write_baseline(tmp_path, _baseline_document([_row(), _row()]))

    result = _run(checker, repo, baseline)

    assert any("duplicate row" in e for e in result.errors)


def test_every_defect_is_reported_not_just_the_first(
    checker: types.ModuleType, tmp_path: Path
) -> None:
    """One problem per run costs one gate cycle per problem."""
    repo = _make_repo(
        tmp_path,
        {
            "src/probos/substrate/x.py": "from probos.cognitive.y import Z\n",
            "src/probos/cognitive/y.py": "class Z: ...\n",
            "src/probos/demo/store.py": (
                "import sqlite3\n\n\ndef open_it():\n"
                '    return sqlite3.connect(":memory:")\n'
            ),
        },
    )
    baseline = _write_baseline(
        tmp_path, _baseline_document([_row(key="probos.demo.gone::Store.open")])
    )

    result = _run(checker, repo, baseline)

    kinds = {error.split(" [")[0] for error in result.errors}
    assert {"NEW VIOLATION", "STALE BASELINE ROW"} <= kinds
    assert len(result.errors) >= 3


def test_expired_review_by_warns_but_does_not_fail(
    checker: types.ModuleType, tmp_path: Path
) -> None:
    """A gate that turns red at midnight with no code change is not a gate."""
    repo = _make_repo(
        tmp_path,
        {
            "src/probos/demo/store.py": (
                "import sqlite3\n\n\nclass Store:\n"
                "    def open(self):\n"
                '        return sqlite3.connect(":memory:")\n'
            )
        },
    )
    baseline = _write_baseline(
        tmp_path, _baseline_document([_row(review_by="2020-01-01")])
    )

    result = checker.check(
        baseline_path=baseline,
        src_root=repo / "src",
        tests_root=repo / "tests",
        today="2026-09-02",
    )

    assert result.errors == []
    assert any("2020-01-01 has passed" in warning for warning in result.warnings)


def test_a_removal_condition_review_by_never_warns(
    checker: types.ModuleType, tmp_path: Path
) -> None:
    """``review_by`` accepts a condition, not only an ISO date."""
    repo = _make_repo(
        tmp_path,
        {
            "src/probos/demo/store.py": (
                "import sqlite3\n\n\nclass Store:\n"
                "    def open(self):\n"
                '        return sqlite3.connect(":memory:")\n'
            )
        },
    )
    baseline = _write_baseline(
        tmp_path, _baseline_document([_row(review_by="AD-1256 completion")])
    )

    result = checker.check(
        baseline_path=baseline,
        src_root=repo / "src",
        tests_root=repo / "tests",
        today="2026-09-02",
    )

    assert result.errors == []
    assert result.warnings == []


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def test_json_report_carries_the_categories_block(tmp_path: Path) -> None:
    report = tmp_path / "report.json"

    result = subprocess.run(
        [sys.executable, str(_SCRIPT), "--check", "--json", str(report)],
        capture_output=True,
        text=True,
        cwd=str(_REPO_ROOT),
        timeout=300,
    )

    assert result.returncode == 0
    document = json.loads(report.read_text(encoding="utf-8"))
    assert document["schema_version"] == 1
    assert document["generated_by"] == "scripts/check_architecture_principles.py"
    categories = document["categories"]
    assert categories["srp-size"] == {
        "mode": "gating",
        "current": 93,
        "baseline": 93,
    }
    assert categories["layer-import"]["current"] == 0
    assert categories["private-access"]["mode"] == "report-only"
    assert categories["source-text-tests"]["mode"] == "report-only"
    assert document["findings"]


def test_json_report_is_deterministic_and_posix(tmp_path: Path) -> None:
    """No absolute paths, no Path reprs, no timestamps, stable ordering.

    Path drift has already turned this repository's CI red three commits
    running while ``--check`` passed locally.
    """
    first, second = tmp_path / "a.json", tmp_path / "b.json"
    for target in (first, second):
        subprocess.run(
            [sys.executable, str(_SCRIPT), "--check", "--json", str(target)],
            capture_output=True,
            text=True,
            cwd=str(_REPO_ROOT),
            timeout=300,
        )

    text = first.read_text(encoding="utf-8")
    assert text == second.read_text(encoding="utf-8")
    assert "WindowsPath" not in text
    assert "PosixPath" not in text
    assert "\\\\" not in text
    assert "d:/probos" not in text.lower()
    document = json.loads(text)
    rows = [
        (f["category"], f["key"], f.get("callee") or "", f["file"], f["line"])
        for f in document["findings"]
    ]
    assert rows == sorted(rows)
    for finding in document["findings"]:
        assert not finding["file"].startswith("/")
        assert ":" not in finding["file"]


def test_update_baseline_is_unreachable_from_preflight() -> None:
    """Preflight passes only --check; the gate must never rewrite the baseline."""
    gate_source = (_REPO_ROOT / "scripts" / "run_test_gate.py").read_text(
        encoding="utf-8"
    )

    assert "check_architecture_principles.py" in gate_source
    assert "--update-baseline" not in gate_source


def test_update_baseline_round_trips_the_committed_file(tmp_path: Path) -> None:
    """Regenerating must preserve reviewed metadata byte-for-byte.

    If it did not, every regeneration would silently discard the owner and
    rationale fields that make a row mean "reviewed".
    """
    copy = tmp_path / "architecture-baseline.yaml"
    copy.write_bytes(_REAL_BASELINE.read_bytes())
    original = copy.read_bytes()

    result = subprocess.run(
        [sys.executable, str(_SCRIPT), "--update-baseline", "--baseline", str(copy)],
        capture_output=True,
        text=True,
        cwd=str(_REPO_ROOT),
        timeout=300,
    )

    assert result.returncode == 0
    assert copy.read_bytes() == original


def test_update_baseline_emits_blank_review_fields_for_new_rows(
    checker: types.ModuleType, tmp_path: Path
) -> None:
    """Blank, not a placeholder: blank fails --check, so a human must fill it.

    A ``TODO`` string would satisfy the non-blank test and ship unreviewed.
    """
    repo = _make_repo(
        tmp_path,
        {
            "src/probos/demo/store.py": (
                "import sqlite3\n\n\ndef open_it():\n"
                '    return sqlite3.connect(":memory:")\n'
            )
        },
    )
    baseline = tmp_path / "architecture-baseline.yaml"

    exit_code = checker.main(
        [
            "--update-baseline",
            "--baseline",
            str(baseline),
            "--src-root",
            str(repo / "src"),
            "--tests-root",
            str(repo / "tests"),
        ]
    )

    assert exit_code == 0
    document = yaml.safe_load(baseline.read_text(encoding="utf-8"))
    row = document["violations"][0]
    assert row["key"] == "probos.demo.store::open_it"
    assert row["owner"] == ""
    assert row["rationale"] == ""
    assert row["review_by"] == ""

    result = _run(checker, repo, baseline)
    assert any("is missing or blank" in error for error in result.errors)


def test_main_returns_one_on_failure_and_zero_on_success(
    checker: types.ModuleType, tmp_path: Path
) -> None:
    repo = _make_repo(
        tmp_path,
        {
            "src/probos/demo/store.py": (
                "import sqlite3\n\n\ndef open_it():\n"
                '    return sqlite3.connect(":memory:")\n'
            )
        },
    )
    failing = _write_baseline(tmp_path, _baseline_document(), name="failing.yaml")
    passing = _write_baseline(
        tmp_path,
        _baseline_document([_row(key="probos.demo.store::open_it")]),
        name="passing.yaml",
    )
    common = [
        "--check",
        "--src-root",
        str(repo / "src"),
        "--tests-root",
        str(repo / "tests"),
    ]

    assert checker.main([*common, "--baseline", str(failing)]) == 1
    assert checker.main([*common, "--baseline", str(passing)]) == 0

# ---------------------------------------------------------------------------
# adversarial-review regressions (2026-09-02) -- import-alias bypasses
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("label", "source", "expected"),
    [
        (
            "module-alias",
            "import sqlite3 as s\ndef f():\n    return s.connect(':memory:')\n",
            "db-connect",
        ),
        (
            "from-import",
            "from sqlite3 import connect\ndef f():\n    return connect(':memory:')\n",
            "db-connect",
        ),
        (
            "from-import-as",
            "from sqlite3 import connect as c\ndef f():\n    return c(':memory:')\n",
            "db-connect",
        ),
        (
            "canonical",
            "import sqlite3\ndef f():\n    return sqlite3.connect(':memory:')\n",
            "db-connect",
        ),
        (
            "task-module-alias",
            "import asyncio as aio\nasync def f():\n    aio.create_task(g())\n",
            "unowned-task",
        ),
        (
            "task-from-import-as",
            "from asyncio import create_task as ct\nasync def f():\n    ct(g())\n",
            "unowned-task",
        ),
        (
            "ensure-future",
            "import asyncio\nasync def f():\n    asyncio.ensure_future(g())\n",
            "unowned-task",
        ),
    ],
)
def test_import_aliases_do_not_bypass_the_gate(
    checker: types.ModuleType, label: str, source: str, expected: str
) -> None:
    """Ordinary import style must not evade a gating category.

    Adversarial review demonstrated every form below passing a checker that
    matched only the literal rendered attribute. These are not clever evasions;
    they are how the standard library is normally imported, so missing them made
    two of the four gating categories partly theatre.
    """
    import ast as _ast

    module = checker.ModuleSource(
        dotted="probos.substrate.probe",
        path="src/probos/substrate/probe.py",
        tree=_ast.parse(source),
    )

    scan = checker.collect_source_findings(iter([module]), _LAYERS)

    assert expected in {finding.category for finding in scan.findings}, label


def test_a_domain_store_create_task_is_still_not_a_finding(
    checker: types.ModuleType,
) -> None:
    """Alias resolution must not widen the predicate into a false positive."""
    import ast as _ast

    module = checker.ModuleSource(
        dotted="probos.substrate.probe",
        path="src/probos/substrate/probe.py",
        tree=_ast.parse("async def f(work_store):\n    work_store.create_task(x)\n"),
    )

    scan = checker.collect_source_findings(iter([module]), _LAYERS)

    categories = {finding.category for finding in scan.findings}
    assert "unowned-task" not in categories


def test_canonical_callee_leaves_an_unknown_head_alone(
    checker: types.ModuleType,
) -> None:
    """An unrecognised binding is returned unchanged rather than guessed at."""
    aliases = {"s": "sqlite3"}

    assert checker.canonical_callee("s.connect", aliases) == "sqlite3.connect"
    assert checker.canonical_callee("other.connect", aliases) == "other.connect"
    assert checker.canonical_callee("", aliases) == ""


def test_import_aliases_maps_every_binding_form(checker: types.ModuleType) -> None:
    import ast as _ast

    aliases = checker.import_aliases(
        _ast.parse(
            "import sqlite3\n"
            "import asyncio as aio\n"
            "from sqlite3 import connect\n"
            "from asyncio import create_task as ct\n"
            "from . import sibling\n"
        )
    )

    assert aliases["sqlite3"] == "sqlite3"
    assert aliases["aio"] == "asyncio"
    assert aliases["connect"] == "sqlite3.connect"
    assert aliases["ct"] == "asyncio.create_task"
    assert "sibling" not in aliases
