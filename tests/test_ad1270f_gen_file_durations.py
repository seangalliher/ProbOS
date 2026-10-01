"""AD-1270f P1.4: ``scripts/gen_file_durations.py`` writes the file the scheduler reads.

The generator is standard-library only and cannot import the loader, so these tests
pin the two against each other: whatever the generator writes, the scheduler's
``load_file_durations`` must accept, and everything the generator cannot vouch for
must make it exit 1 and leave ``--output`` exactly as it was.
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
    "tests/test_beta.py::test_one",
    "tests/test_child.py::TestChild::test_inherited",
    "tests/sub/test_gamma.py::test_skipped",
]
_CASES: list[Case] = [
    ("tests.test_alpha", "test_one", 1.25, None, "tests\\test_alpha.py"),
    ("tests.test_alpha.TestA", "test_two", 2.5, None, "tests\\test_alpha.py"),
    ("tests.test_alpha.TestA", "test_param[x.y]", 0.31, None, "tests\\test_alpha.py"),
    ("tests.test_beta", "test_one", 4.0, None, "tests\\test_beta.py"),
    # Inherited: the ``file`` attribute names the module that *defines* the test.
    ("tests.test_child.TestChild", "test_inherited", 3.0, None, "tests\\test_base.py"),
    ("tests.sub.test_gamma", "test_skipped", 0.0, "skipped", "tests\\sub\\test_gamma.py"),
]
_EXPECTED_FILES = {
    "tests/sub/test_gamma.py": 0.0,
    "tests/test_alpha.py": 4.1,  # 1.25 + 2.5 + 0.31 = 4.06
    "tests/test_beta.py": 4.0,
    "tests/test_child.py": 3.0,
}
_TOTAL = 11.06


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
        "testcases": 6,
        "total_seconds": round(_TOTAL, 1),
    }
    assert payload["mean_test_seconds"] == round(_TOTAL / 6, 4)


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
    assert '"mean_test_seconds": 1.8433,' in text
    assert '"tests/test_alpha.py": 4.1,' in text


def test_the_scheduler_loader_accepts_what_the_generator_writes(
    gen: ModuleType, tmp_path: Path
) -> None:
    gate = _Gate(tmp_path)
    assert gen.main(gate.argv()) == 0

    loaded = load_file_durations(gate.output)

    assert dict(loaded.files) == _EXPECTED_FILES
    assert loaded.mean_test_seconds == round(_TOTAL / 6, 4)


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


_ALL_ZERO: list[Case] = [(classname, name, 0.0, child, file) for classname, name, _, child, file in _CASES]

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
    ("junit-has-fewer-testcases-than-nodes", _with_cases(_CASES[:-1]), "different testcase count"),
    ("junit-has-more-testcases-than-nodes", _with_cases([*_CASES, _CASES[0]]), "different testcase count"),
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
