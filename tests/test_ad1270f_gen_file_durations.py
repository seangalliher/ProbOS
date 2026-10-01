"""AD-1270f P1.4: ``scripts/gen_file_durations.py`` writes the file the scheduler reads.

The generator is standard-library only and imports nothing from the tests; the
scheduler's loader loads the generator's key rule from its path. These tests pin the
two against each other: whatever the generator writes, the scheduler's
``load_file_durations`` must accept, and everything the generator cannot vouch for
must make it exit 1 and leave ``--output`` exactly as it was. Node IDs are checked
against pytest's own legacy-JUnit naming (``mangle_test_address``), not a copy of it.
"""

from __future__ import annotations

import ast
import hashlib
import importlib.util
import json
import random
import subprocess
import sys
import xml.etree.ElementTree as ET
from collections.abc import Callable, Iterator, Sequence
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from _pytest.junitxml import mangle_test_address

from tests.fixtures import duration_scheduler as ds
from tests.fixtures.duration_scheduler import DURATIONS_PATH, load_file_durations

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "gen_file_durations.py"

#: (classname, name, seconds, child tag or None, ``file`` attribute or None)
Case = tuple[str, str, float, str | None, str | None]

_NODES = [
    "tests/test_alpha.py::test_one",
    "tests/test_alpha.py::TestA::test_two",
    "tests/test_alpha.py::TestA::test_param[x.y]",
    "tests/test_alpha.py::TestA::test_param[a/b::c]",
    "tests/test_alpha.py::TestA::TestInner::test_deep",
    "tests/test_beta.py::test_one",
    "tests/test_child.py::TestChild::test_inherited",
    "tests/sub/test_gamma.py::test_skipped",
]
_CASES: list[Case] = [
    ("tests.test_alpha", "test_one", 1.25, None, "tests\\test_alpha.py"),
    ("tests.test_alpha.TestA", "test_two", 2.5, None, "tests\\test_alpha.py"),
    ("tests.test_alpha.TestA", "test_param[x.y]", 0.31, None, "tests\\test_alpha.py"),
    # A parametrize id with ``/`` and ``::`` stays in the raw name; the class chain is the classname.
    ("tests.test_alpha.TestA", "test_param[a/b::c]", 0.5, None, "tests\\test_alpha.py"),
    ("tests.test_alpha.TestA.TestInner", "test_deep", 0.26, None, "tests\\test_alpha.py"),
    ("tests.test_beta", "test_one", 4.0, None, "tests\\test_beta.py"),
    # Inherited: the ``file`` attribute names the module that *defines* the test.
    ("tests.test_child.TestChild", "test_inherited", 3.0, None, "tests\\test_base.py"),
    ("tests.sub.test_gamma", "test_skipped", 0.0, "skipped", "tests\\sub\\test_gamma.py"),
]
_EXPECTED_FILES = {
    "tests/sub/test_gamma.py": 0.0,
    "tests/test_alpha.py": 4.8,  # 1.25 + 2.5 + 0.31 + 0.5 + 0.26 = 4.82
    "tests/test_beta.py": 4.0,
    "tests/test_child.py": 3.0,
}
_TOTAL = 11.82
_COUNT = len(_CASES)


@pytest.fixture(scope="module")
def gen() -> Iterator[ModuleType]:
    name = "_ad1270f_p14_gen_file_durations"
    spec = importlib.util.spec_from_file_location(name, SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
        yield module
    finally:
        sys.modules.pop(name, None)


def _write_junit(path: Path, cases: Sequence[Case], *, root: str = "testsuites") -> Path:
    suite = ET.Element("testsuite", name="pytest", tests=str(len(cases)))
    for classname, name, seconds, child, file_attribute in cases:
        attributes = {"classname": classname, "name": name, "time": repr(seconds)}
        if file_attribute is not None:
            attributes["file"] = file_attribute
        testcase = ET.SubElement(suite, "testcase", attributes)
        if child is not None:
            ET.SubElement(testcase, child)
    top = suite
    if root == "testsuites":
        top = ET.Element("testsuites", name="pytest tests")
        top.append(suite)
    ET.ElementTree(top).write(path, encoding="utf-8", xml_declaration=True)
    return path


def _write_collection(path: Path, nodes: Sequence[str], **overrides: Any) -> Path:
    payload: dict[str, Any] = {"schema_version": 1, "collected_nodeids": sorted(nodes)}
    payload.update(overrides)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


class _Gate:
    """A canonical gate's two artifacts side by side, as the wrapper leaves them."""

    def __init__(
        self,
        directory: Path,
        *,
        cases: Sequence[Case] = _CASES,
        nodes: Sequence[str] = _NODES,
        stem: str = "20260930T000000Z-ad1270f",
    ) -> None:
        self.junit = _write_junit(directory / f"{stem}.xml", cases)
        self.collection = _write_collection(directory / f"{stem}.collection.json", nodes)
        self.output = directory / "out" / "file_durations.json"

    def argv(self, *, collection: bool = False) -> list[str]:
        argv = ["--junit", str(self.junit), "--output", str(self.output)]
        if collection:
            argv += ["--collection", str(self.collection)]
        return argv


def _payload(output: Path) -> dict[str, Any]:
    return json.loads(output.read_bytes())


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _case_for(node_id: str, seconds: float = 1.0) -> Case:
    """The legacy-JUnit testcase pytest itself would write for ``node_id``."""
    *classnames, name = mangle_test_address(node_id)
    return (".".join(classnames), name, seconds, None, None)


# --- What it writes -----------------------------------------------------------------


def test_per_file_seconds_sum_the_testcases_and_an_inherited_test_goes_to_its_collecting_file(
    gen: ModuleType, tmp_path: Path
) -> None:
    gate = _Gate(tmp_path)

    assert gen.main(gate.argv()) == 0

    assert _payload(gate.output)["files"] == _EXPECTED_FILES
    assert "tests/test_base.py" not in _payload(gate.output)["files"]


def test_the_source_block_names_the_artifacts_by_basename_and_hash(
    gen: ModuleType, tmp_path: Path
) -> None:
    gate = _Gate(tmp_path)

    assert gen.main(gate.argv()) == 0

    payload = _payload(gate.output)
    assert set(payload) == {"schema_version", "source", "mean_test_seconds", "files"}
    assert payload["schema_version"] == 1 and payload["schema_version"] is not True
    assert payload["source"] == {
        "junit": gate.junit.name,
        "collection": gate.collection.name,
        "junit_sha256": _sha256(gate.junit),
        "collection_sha256": _sha256(gate.collection),
        "testcases": _COUNT,
        "total_seconds": round(_TOTAL, 1),
    }
    assert payload["mean_test_seconds"] == round(_TOTAL / _COUNT, 4)


def test_the_longest_dotted_prefix_wins_and_a_name_prefix_is_not_a_package_prefix(
    gen: ModuleType, tmp_path: Path
) -> None:
    nodes = [
        "tests/pkg.py::test_a",
        "tests/pkg.py::TestY::test_d",
        "tests/pkg/mod.py::TestX::test_b",
        "tests/pkg_extra.py::test_c",
    ]
    cases: list[Case] = [
        ("tests.pkg", "test_a", 1.0, None, None),
        ("tests.pkg.TestY", "test_d", 8.0, None, None),
        ("tests.pkg.mod.TestX", "test_b", 2.0, None, None),
        ("tests.pkg_extra", "test_c", 4.0, None, None),
    ]
    gate = _Gate(tmp_path, cases=cases, nodes=nodes)

    assert gen.main(gate.argv()) == 0

    assert _payload(gate.output)["files"] == {
        "tests/pkg.py": 9.0,
        "tests/pkg/mod.py": 2.0,
        "tests/pkg_extra.py": 4.0,
    }


def test_a_junit_whose_root_is_the_testsuite_is_read_too(gen: ModuleType, tmp_path: Path) -> None:
    gate = _Gate(tmp_path)
    _write_junit(gate.junit, _CASES, root="testsuite")

    assert gen.main(gate.argv()) == 0

    assert _payload(gate.output)["files"] == _EXPECTED_FILES


def test_the_same_inputs_give_identical_bytes_whatever_order_the_testcases_arrive_in(
    gen: ModuleType, tmp_path: Path
) -> None:
    gate = _Gate(tmp_path)
    first, second = tmp_path / "first.json", tmp_path / "second.json"
    assert gen.main(["--junit", str(gate.junit), "--output", str(first)]) == 0
    assert gen.main(["--junit", str(gate.junit), "--output", str(second)]) == 0
    shuffled = list(_CASES)
    random.Random(7).shuffle(shuffled)
    reordered_directory = tmp_path / "reordered"
    reordered_directory.mkdir()
    reordered = _Gate(reordered_directory, cases=shuffled)
    assert shuffled != _CASES
    assert gen.main(reordered.argv()) == 0

    assert first.read_bytes() == second.read_bytes()
    ours, theirs = _payload(first), _payload(reordered.output)
    assert (ours["files"], ours["mean_test_seconds"]) == (theirs["files"], theirs["mean_test_seconds"])


def test_the_output_is_lf_only_indented_two_sorted_and_rounded(gen: ModuleType, tmp_path: Path) -> None:
    gate = _Gate(tmp_path)
    assert gen.main(gate.argv()) == 0

    data = gate.output.read_bytes()
    text = data.decode("utf-8")
    assert b"\r" not in data and text.endswith("}\n")
    assert text == json.dumps(json.loads(text), indent=2, sort_keys=True) + "\n"
    assert text.startswith('{\n  "files": {\n    "tests/sub/test_gamma.py": 0.0,\n')
    assert '"mean_test_seconds": 1.4775,' in text
    assert '"tests/test_alpha.py": 4.8,' in text


def test_the_scheduler_loader_accepts_what_the_generator_writes(
    gen: ModuleType, tmp_path: Path
) -> None:
    gate = _Gate(tmp_path)
    assert gen.main(gate.argv()) == 0

    loaded = load_file_durations(gate.output)

    assert dict(loaded.files) == _EXPECTED_FILES
    assert loaded.mean_test_seconds == round(_TOTAL / _COUNT, 4)


def test_the_collection_defaults_to_the_sibling_and_an_explicit_one_is_honoured(
    gen: ModuleType, tmp_path: Path
) -> None:
    gate = _Gate(tmp_path)
    assert gen.main(gate.argv()) == 0
    by_default = gate.output.read_bytes()
    assert gen.main(gate.argv(collection=True)) == 0
    assert gate.output.read_bytes() == by_default

    renamed = tmp_path / "chosen.collection.json"
    renamed.write_bytes(gate.collection.read_bytes())
    gate.collection.unlink()
    assert gen.main(gate.argv()) == 1, "the default sibling no longer exists"
    assert gen.main([*gate.argv(), "--collection", str(renamed)]) == 0
    assert _payload(gate.output)["source"]["collection"] == "chosen.collection.json"


def test_the_script_runs_as_a_program_and_exits_zero_or_one(tmp_path: Path) -> None:
    gate = _Gate(tmp_path)

    ok = subprocess.run(
        [sys.executable, "-I", str(SCRIPT), *gate.argv()],
        capture_output=True, text=True, timeout=120,
    )
    refused = subprocess.run(
        [sys.executable, "-I", str(SCRIPT), "--junit", str(tmp_path / "nope.xml"),
         "--output", str(tmp_path / "never.json")],
        capture_output=True, text=True, timeout=120,
    )

    assert ok.returncode == 0, ok.stderr
    assert "wrote" in ok.stdout and gate.output.is_file()
    assert refused.returncode == 1 and "refusing" in refused.stderr
    assert not (tmp_path / "never.json").exists()


# --- What it refuses ------------------------------------------------------------------


def _break(mutator: Callable[[_Gate], None]) -> Callable[[Path], _Gate]:
    def build(directory: Path) -> _Gate:
        gate = _Gate(directory)
        mutator(gate)
        return gate

    return build


def _with_cases(cases: Sequence[Case], nodes: Sequence[str] = _NODES) -> Callable[[Path], _Gate]:
    return lambda directory: _Gate(directory, cases=cases, nodes=nodes)


def _with_child(child: str) -> Callable[[Path], _Gate]:
    broken = [
        ("tests.test_beta", "test_one", 4.0, child, None) if case[0] == "tests.test_beta" else case
        for case in _CASES
    ]
    return _with_cases(broken)


def _raw_junit(body: str) -> Callable[[Path], _Gate]:
    def mutate(gate: _Gate) -> None:
        gate.junit.write_text(
            f'<testsuites><testsuite name="pytest">{body}</testsuite></testsuites>', encoding="utf-8"
        )
        gate.collection.write_text(
            json.dumps({"schema_version": 1, "collected_nodeids": ["tests/test_beta.py::t"]}),
            encoding="utf-8",
        )

    return _break(mutate)


def _collection_payload(**overrides: Any) -> Callable[[Path], _Gate]:
    return _break(lambda gate: _write_collection(gate.collection, _NODES, **overrides))


def _swapped(
    classname: str, name: str, *, to_classname: str | None = None, to_name: str | None = None
) -> list[Case]:
    """``_CASES`` with one testcase renamed: the per-file counts stay equal."""
    return [
        (to_classname or c, to_name or n, s, child, file) if (c, n) == (classname, name) else (c, n, s, child, file)
        for c, n, s, child, file in _CASES
    ]


def _with_invalid_path(path: str) -> Callable[[Path], _Gate]:
    """A collection and a JUnit that agree exactly, except that the file path is not a valid key."""
    node = f"{path}::test_t"
    return _with_cases([_case_for(node)], nodes=[node])


_ALL_ZERO: list[Case] = [(classname, name, 0.0, child, file) for classname, name, _, child, file in _CASES]
_INVALID_FILE_PATHS = {
    "empty": "",
    "absolute": "/abs/test_a.py",
    "drive": "C:/abs/test_a.py",
    "backslash": "tests\\test_a.py",
    "dotdot-segment": "tests/../test_a.py",
    "dotdot-only": "..",
    "unc": "//host/share/test_a.py",
}
_ONE_OFF = "1 missing, 1 unexpected, 0 repeated"

_REFUSALS: list[tuple[str, Callable[[Path], _Gate], str]] = [
    ("failure-child", _with_child("failure"), "failed or errored"),
    ("error-child", _with_child("error"), "failed or errored"),
    ("collection-missing", _break(lambda gate: gate.collection.unlink()), "collection artifact is unreadable"),
    (
        "collection-malformed",
        _break(lambda gate: gate.collection.write_text("{", encoding="utf-8")),
        "collection artifact is unreadable",
    ),
    ("collection-schema-two", _collection_payload(schema_version=2), "not schema_version 1"),
    ("collection-schema-bool", _collection_payload(schema_version=True), "not schema_version 1"),
    (
        "collection-without-nodeids",
        _break(lambda gate: gate.collection.write_text('{"schema_version": 1}', encoding="utf-8")),
        "no collected_nodeids",
    ),
    ("collection-empty", _collection_payload(collected_nodeids=[]), "no collected_nodeids"),
    ("collection-repeats-a-node", _collection_payload(collected_nodeids=[*_NODES, _NODES[0]]), "more than once"),
    (
        "testcase-matches-no-file",
        _with_cases([*_CASES, ("tests.test_ghost", "test_x", 1.0, None, None)]),
        "match no collected file",
    ),
    (
        "two-files-share-a-dotted-name",
        _with_cases(
            [("tests.a.b", "t", 1.0, None, None)],
            nodes=["tests/a/b.py::t", "tests/a.b.py::t"],
        ),
        "share the dotted name 'tests.a.b'",
    ),
    (
        "junit-lacks-a-collected-node",
        _with_cases(_CASES[:-1]),
        "1 missing, 0 unexpected, 0 repeated); first 1: "
        "collected but not in the JUnit: tests/sub/test_gamma.py::test_skipped",
    ),
    (
        "junit-repeats-a-node",
        _with_cases([*_CASES, _CASES[0]]),
        "0 missing, 0 unexpected, 1 repeated); first 1: "
        "repeated in the JUnit: tests/test_alpha.py::test_one",
    ),
    (
        "junit-has-an-uncollected-node",
        _with_cases([*_CASES, ("tests.test_beta", "test_extra", 1.0, None, None)]),
        "0 missing, 1 unexpected, 0 repeated); first 1: "
        "in the JUnit but not collected: tests/test_beta.py::test_extra",
    ),
    # The counts per file stay equal, so only the node identities can tell these runs apart.
    (
        "same-counts-but-a-renamed-test",
        _with_cases(_swapped("tests.test_beta", "test_one", to_name="test_renamed")),
        _ONE_OFF,
    ),
    (
        "same-counts-but-another-class-chain",
        _with_cases(_swapped("tests.test_alpha.TestA", "test_two", to_classname="tests.test_alpha.TestB")),
        _ONE_OFF,
    ),
    (
        "same-counts-but-another-parametrize-id",
        _with_cases(_swapped("tests.test_alpha.TestA", "test_param[x.y]", to_name="test_param[x_y]")),
        _ONE_OFF,
    ),
    (
        "same-counts-but-the-slash-id-lost-its-colons",
        _with_cases(_swapped("tests.test_alpha.TestA", "test_param[a/b::c]", to_name="test_param[a/b:c]")),
        _ONE_OFF,
    ),
    *[
        (f"invalid-file-path-{label}", _with_invalid_path(path), "cannot be written as a key")
        for label, path in _INVALID_FILE_PATHS.items()
    ],
    ("all-time-is-zero", _with_cases(_ALL_ZERO), "records no time"),
    (
        "mean-rounds-to-zero",
        _with_cases([("tests.test_beta", "t", 0.00001, None, None)], nodes=["tests/test_beta.py::t"]),
        "rounds to 0.0",
    ),
    ("junit-missing", _break(lambda gate: gate.junit.unlink()), "JUnit report is unreadable"),
    (
        "junit-malformed",
        _break(lambda gate: gate.junit.write_text("<testsuites", encoding="utf-8")),
        "JUnit report is unreadable",
    ),
    ("testcase-time-not-numeric", _raw_junit('<testcase classname="tests.test_beta" name="t" time="abc"/>'), "no numeric time"),
    ("testcase-time-missing", _raw_junit('<testcase classname="tests.test_beta" name="t"/>'), "no numeric time"),
    ("testcase-time-negative", _raw_junit('<testcase classname="tests.test_beta" name="t" time="-1"/>'), "has time -1.0"),
    ("testcase-time-nan", _raw_junit('<testcase classname="tests.test_beta" name="t" time="nan"/>'), "has time nan"),
    ("testcase-time-infinite", _raw_junit('<testcase classname="tests.test_beta" name="t" time="1e999"/>'), "has time inf"),
]


def test_the_baseline_the_refusal_cases_start_from_is_accepted(gen: ModuleType, tmp_path: Path) -> None:
    assert gen.main(_Gate(tmp_path).argv()) == 0


@pytest.mark.parametrize(
    ("build", "message"),
    [pytest.param(build, message, id=name) for name, build, message in _REFUSALS],
)
def test_every_refusal_exits_one_names_its_reason_and_leaves_the_output_untouched(
    gen: ModuleType,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    build: Callable[[Path], _Gate],
    message: str,
) -> None:
    gate = build(tmp_path)
    folder = gate.output.parent
    folder.mkdir(parents=True)
    gate.output.write_bytes(b"SENTINEL")

    assert gen.main(gate.argv()) == 1

    assert message in capsys.readouterr().err
    assert gate.output.read_bytes() == b"SENTINEL"
    assert [path.name for path in folder.iterdir()] == [gate.output.name], "no temporary file left"
    gate.output.unlink()
    assert gen.main(gate.argv()) == 1
    assert not gate.output.exists(), "a refusal must not create the output either"
    assert list(folder.iterdir()) == []


def test_a_successful_write_leaves_no_temporary_file(gen: ModuleType, tmp_path: Path) -> None:
    gate = _Gate(tmp_path)

    assert gen.main(gate.argv()) == 0

    assert [path.name for path in gate.output.parent.iterdir()] == [gate.output.name]


def test_the_output_is_replaced_atomically_from_a_temporary_beside_it(
    gen: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    gate = _Gate(tmp_path)
    gate.output.parent.mkdir(parents=True)
    gate.output.write_bytes(b"OLD")
    real_replace = gen.os.replace
    seen: list[tuple[Path, Path, bytes]] = []

    def spy(source: Any, destination: Any) -> None:
        seen.append((Path(source), Path(destination), Path(source).read_bytes()))
        real_replace(source, destination)

    monkeypatch.setattr(gen.os, "replace", spy)

    assert gen.main(gate.argv()) == 0

    [(source, destination, staged)] = seen
    assert destination == gate.output and source.parent == destination.parent
    assert source.name.startswith(f".{gate.output.name}.") and source.name.endswith(".tmp")
    assert staged == gate.output.read_bytes() and staged != b"OLD"
    assert not source.exists()


def test_a_write_that_cannot_replace_the_output_exits_one_and_cleans_up(
    gen: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    gate = _Gate(tmp_path)
    gate.output.mkdir(parents=True)

    assert gen.main(gate.argv()) == 1

    assert "refusing" in capsys.readouterr().err
    assert gate.output.is_dir() and list(gate.output.iterdir()) == []
    assert [path.name for path in gate.output.parent.iterdir()] == [gate.output.name]


# --- Exact identity: the JUnit must describe the collected nodes, no more and no less ----


_ORACLE_NODES = [
    "tests/test_a.py::test_plain",
    "tests/test_a.py::TestA::test_method",
    "tests/test_a.py::TestA::TestInner::test_deep",
    "tests/test_a.py::test_param[a/b]",
    "tests/test_a.py::test_param[x::y]",
    "tests/test_a.py::TestA::test_param[a/b::c]",
    "tests/test_a.py::test_param[a[b]c.d]",
    "tests/odd.dir/test_b.py::test_x",
    "tests/sub/test_c.py::test_y[1-2]",
]


def test_node_ids_are_rebuilt_exactly_as_pytest_names_them_in_the_junit(
    gen: ModuleType, tmp_path: Path
) -> None:
    gate = _Gate(tmp_path, cases=[_case_for(node) for node in _ORACLE_NODES], nodes=_ORACLE_NODES)
    files = sorted({node.split("::", 1)[0] for node in _ORACLE_NODES})

    testcases = gen.read_testcases(gate.junit, gen._dotted_index(files))

    assert [testcase.node_id for testcase in testcases] == _ORACLE_NODES
    assert [testcase.file for testcase in testcases] == [node.split("::", 1)[0] for node in _ORACLE_NODES]
    assert gen.main(gate.argv()) == 0


def test_a_same_counts_run_of_other_nodes_is_refused_naming_both_sides(
    gen: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    gate = _Gate(tmp_path, cases=_swapped("tests.test_beta", "test_one", to_name="test_renamed"))

    assert gen.main(gate.argv()) == 1

    error = capsys.readouterr().err
    assert "collected but not in the JUnit: tests/test_beta.py::test_one" in error
    assert "in the JUnit but not collected: tests/test_beta.py::test_renamed" in error
    assert not gate.output.exists()


def test_at_most_ten_mismatches_are_listed_but_all_are_counted(
    gen: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    nodes = [f"tests/test_many.py::test_{number:02d}" for number in range(25)]
    gate = _Gate(tmp_path, cases=[_case_for(node) for node in nodes[:2]], nodes=nodes)

    assert gen.main(gate.argv()) == 1

    error = capsys.readouterr().err
    assert "(23 missing, 0 unexpected, 0 repeated); first 10: " in error
    assert error.count("collected but not in the JUnit:") == 10


def test_a_matching_junit_in_another_order_is_accepted(gen: ModuleType, tmp_path: Path) -> None:
    shuffled = [_case_for(node) for node in _ORACLE_NODES]
    random.Random(11).shuffle(shuffled)
    gate = _Gate(tmp_path, cases=shuffled, nodes=_ORACLE_NODES)

    assert gen.main(gate.argv()) == 0


# --- One key rule, defined by the writer and applied by the reader -----------------------

_VALID_KEYS = [
    "tests/test_a.py",
    "tests/sub/test_b.py",
    "test_c.py",
    "tests/odd.name/test_d.py",
    "tests/a..b/test_e.py",
]
_INVALID_KEYS = [
    "",
    "/abs/test_a.py",
    "C:/abs/test_a.py",
    "C:test_a.py",
    "//host/share/test_a.py",
    "tests\\test_a.py",
    "tests/../test_a.py",
    "..",
    "tests/test_a.py::test_one",
]


@pytest.mark.parametrize("key", _VALID_KEYS)
def test_a_relative_test_path_is_a_valid_key(gen: ModuleType, key: str) -> None:
    assert gen.file_key_problem(key) is None


@pytest.mark.parametrize("key", _INVALID_KEYS)
def test_every_other_key_has_a_stated_problem_and_the_loader_refuses_it_too(
    gen: ModuleType, tmp_path: Path, key: str
) -> None:
    assert "relative test path" in (gen.file_key_problem(key) or "")
    payload = {
        "schema_version": 1,
        "source": {
            "junit": "run.xml",
            "collection": "run.collection.json",
            "junit_sha256": "a" * 64,
            "collection_sha256": "b" * 64,
            "testcases": 1,
            "total_seconds": 1.0,
        },
        "mean_test_seconds": 1.0,
        "files": {key: 1.0},
    }
    path = tmp_path / "file_durations.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ds.DurationDataError, match="relative test path"):
        load_file_durations(path)


def test_the_generator_asks_the_shared_rule_for_every_key_it_would_write(
    gen: ModuleType,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gate = _Gate(tmp_path)
    monkeypatch.setattr(
        gen, "file_key_problem", lambda key: "stub says no" if key == "tests/test_beta.py" else None
    )

    assert gen.main(gate.argv()) == 1

    assert "stub says no" in capsys.readouterr().err
    assert not gate.output.exists()


# --- Parser failures are refusals, not tracebacks ------------------------------------------


@pytest.fixture
def digit_limit() -> Iterator[int]:
    """Python's default cap on int<->str conversion, restored afterwards, whatever the environment sets."""
    previous = sys.get_int_max_str_digits()
    sys.set_int_max_str_digits(4300)
    try:
        yield 4300
    finally:
        sys.set_int_max_str_digits(previous)


def _huge_integer_collection(gate: _Gate, digits: int) -> None:
    gate.collection.write_text(
        '{"schema_version": 1, "collected_nodeids": ["tests/test_beta.py::test_one"], "junk": '
        + "1" + "0" * digits + "}",
        encoding="utf-8",
    )


def test_an_integer_beyond_the_digit_limit_is_a_refusal_with_the_output_untouched(
    gen: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str], digit_limit: int
) -> None:
    gate = _Gate(tmp_path)
    _huge_integer_collection(gate, digit_limit)
    gate.output.parent.mkdir(parents=True)
    gate.output.write_bytes(b"SENTINEL")

    assert gen.main(gate.argv()) == 1

    error = capsys.readouterr().err
    assert "collection artifact is unreadable" in error and "Exceeds the limit" in error
    assert gate.output.read_bytes() == b"SENTINEL"
    assert [path.name for path in gate.output.parent.iterdir()] == [gate.output.name]


def test_the_script_prints_a_refusal_not_a_traceback_for_a_huge_integer(tmp_path: Path) -> None:
    gate = _Gate(tmp_path)
    _huge_integer_collection(gate, 4300)

    refused = subprocess.run(
        [sys.executable, "-I", "-X", "int_max_str_digits=4300", str(SCRIPT), *gate.argv()],
        capture_output=True, text=True, timeout=120,
    )

    assert refused.returncode == 1
    assert "refusing" in refused.stderr and "Traceback" not in refused.stderr
    assert not gate.output.exists()


def test_a_collection_nested_beyond_the_parsers_depth_is_a_refusal(
    gen: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    gate = _Gate(tmp_path)
    gate.collection.write_text("[" * 100_000, encoding="utf-8")

    assert gen.main(gate.argv()) == 1

    assert "collection artifact is unreadable" in capsys.readouterr().err
    assert not gate.output.exists()


def test_a_collection_that_is_not_utf8_is_a_refusal(
    gen: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    gate = _Gate(tmp_path)
    gate.collection.write_bytes(b"\xff\xfe{")

    assert gen.main(gate.argv()) == 1

    assert "collection artifact is unreadable" in capsys.readouterr().err


@pytest.mark.parametrize("raised", [ValueError("a parser limit nobody anticipated"), RecursionError("too deep")])
def test_an_unexpected_parser_error_while_building_is_still_a_refusal_not_a_traceback(
    gen: ModuleType,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    raised: Exception,
) -> None:
    gate = _Gate(tmp_path)

    def surprise(junit: Path, collection: Path) -> dict[str, Any]:
        raise raised

    monkeypatch.setattr(gen, "build_payload", surprise)

    assert gen.main(gate.argv()) == 1

    assert str(raised) in capsys.readouterr().err
    assert not gate.output.exists()


# --- The generator against its neighbours --------------------------------------------


def test_the_generator_imports_only_the_standard_library() -> None:
    tree = ast.parse(SCRIPT.read_bytes())
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0 and node.module
            imported.add(node.module.split(".")[0])

    assert imported <= set(sys.stdlib_module_names)
    assert not imported & {"run_test_gate", "select_tests", "tests", "probos", "scripts"}


def test_the_generator_and_the_loader_agree_on_the_schema(gen: ModuleType) -> None:
    assert gen.SCHEMA_VERSION == ds.SCHEMA_VERSION == 1
    assert (gen.FILE_SECONDS_DIGITS, gen.MEAN_SECONDS_DIGITS) == (1, 4)
    assert Path(gen.DEFAULT_OUTPUT).resolve() == DURATIONS_PATH.resolve()


def test_the_default_collection_is_the_sibling_with_the_collection_suffix(gen: ModuleType) -> None:
    assert gen.sibling_collection(Path("logs/gates/run.xml")) == Path("logs/gates/run.collection.json")


@pytest.mark.parametrize(
    ("file_path", "dotted"),
    [
        ("tests/test_a.py", "tests.test_a"),
        ("tests/sub/test_b.py", "tests.sub.test_b"),
        ("tests/odd.name/test_c.py", "tests.odd.name.test_c"),
        ("tests/test_d", "tests.test_d"),
    ],
)
def test_the_dotted_module_name_is_the_legacy_junit_classname_prefix(
    gen: ModuleType, file_path: str, dotted: str
) -> None:
    assert gen.dotted_module_name(file_path) == dotted


def test_the_committed_file_is_the_generators_canonical_output_of_its_named_artifacts(
    gen: ModuleType,
) -> None:
    text = DURATIONS_PATH.read_bytes().decode("utf-8").replace("\r\n", "\n")
    payload = json.loads(text)

    assert gen.render(payload).decode("utf-8") == text, "regenerate with scripts/gen_file_durations.py"
    source = payload["source"]
    assert source["junit"].endswith(".xml")
    assert source["collection"] == source["junit"].removesuffix(".xml") + ".collection.json"
    assert payload["mean_test_seconds"] == pytest.approx(
        source["total_seconds"] / source["testcases"], abs=1e-4
    )
