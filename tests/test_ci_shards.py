"""AD-1270f P2.7: CI shard planning, exactly-once evidence verification and the ci.yml guard.

Loads ``scripts/ci_shards.py`` by file path, like the other script tests. CI shard
evidence is not release authority: these tests pin the CI proof, not the canonical gate.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import random
import re
import shlex
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "ci_shards.py"
GATE_PLUGIN = REPO_ROOT / "scripts" / "_gate_pytest_plugin.py"
CI_YML = REPO_ROOT / ".github" / "workflows" / "ci.yml"
REAL_DURATIONS = REPO_ROOT / "tests" / "fixtures" / "file_durations.json"


def _load(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def cs() -> ModuleType:
    return _load("ci_shards_under_test", SCRIPT)


def _durations_file(tmp_path: Path, payload: Any, name: str = "durations.json") -> Path:
    path = tmp_path / name
    path.write_text(payload if isinstance(payload, str) else json.dumps(payload), encoding="utf-8")
    return path


def _nodes(counts: dict[str, int]) -> list[str]:
    return [f"{path}::test_{number}" for path, count in counts.items() for number in range(count)]


# --- the durations loader ----------------------------------------------------


def test_default_durations_path_is_the_p14_file(cs: ModuleType) -> None:
    assert cs.DEFAULT_DURATIONS_PATH == "tests/fixtures/file_durations.json"
    assert (REPO_ROOT / cs.DEFAULT_DURATIONS_PATH).is_file()


def test_load_durations_real_file_converts_every_entry_to_milliseconds(cs: ModuleType) -> None:
    raw = json.loads(REAL_DURATIONS.read_text(encoding="utf-8"))

    loaded = cs.read_durations(REAL_DURATIONS)

    assert loaded.milliseconds == {
        path: max(1, round(seconds * 1000)) for path, seconds in raw["files"].items()
    }
    assert len(loaded.milliseconds) > 1000
    assert all(isinstance(ms, int) and ms >= 1 for ms in loaded.milliseconds.values())
    assert loaded.sha256 == hashlib.sha256(REAL_DURATIONS.read_bytes()).hexdigest()
    assert cs.load_durations(REAL_DURATIONS) == loaded.milliseconds


def test_load_durations_ignores_other_top_level_keys(cs: ModuleType, tmp_path: Path) -> None:
    path = _durations_file(
        tmp_path,
        {"schema_version": 1, "source": {"x": 1}, "mean_test_seconds": 0.2, "files": {"tests/a.py": 2}},
    )

    assert cs.load_durations(path) == {"tests/a.py": 2000}


@pytest.mark.parametrize(
    ("seconds", "expected"),
    [(0, 1), (0.0, 1), (-0.0, 1), (0.0004, 1), (1.5, 1500), (3, 3000), (0.1, 100), (12.3456, 12346)],
)
def test_load_durations_converts_seconds_to_at_least_one_millisecond(
    cs: ModuleType, tmp_path: Path, seconds: float, expected: int
) -> None:
    path = _durations_file(tmp_path, {"schema_version": 1, "files": {"tests/a.py": seconds}})

    assert cs.load_durations(path) == {"tests/a.py": expected}


def test_load_durations_rounds_like_python_round(cs: ModuleType, tmp_path: Path) -> None:
    seconds = [0.0005, 0.0015, 0.0025, 0.0035, 0.4999, 2.0006]
    path = _durations_file(
        tmp_path,
        {"schema_version": 1, "files": {f"tests/t{i}.py": value for i, value in enumerate(seconds)}},
    )

    loaded = cs.load_durations(path)

    assert list(loaded.values()) == [max(1, round(value * 1000)) for value in seconds]


def test_load_durations_accepts_an_empty_files_object(cs: ModuleType, tmp_path: Path) -> None:
    assert cs.load_durations(_durations_file(tmp_path, {"schema_version": 1, "files": {}})) == {}


def _doc(files: Any, version: Any = 1) -> str:
    return json.dumps({"schema_version": version, "files": files})


_BAD_DURATIONS = {
    "not json": ("{", "not valid JSON"),
    "empty": ("", "not valid JSON"),
    "top-level list": ("[]", "JSON object"),
    "top-level number": ("1", "JSON object"),
    "nan constant": ('{"schema_version": 1, "files": {"tests/a.py": NaN}}', "non-finite"),
    "infinity constant": ('{"schema_version": 1, "files": {"tests/a.py": Infinity}}', "non-finite"),
    "negative infinity": ('{"schema_version": 1, "files": {"tests/a.py": -Infinity}}', "non-finite"),
    "overflowing float": ('{"schema_version": 1, "files": {"tests/a.py": 1e999}}', "finite"),
    "float that overflows once scaled": (_doc({"tests/a.py": 1e308}), "finite"),
    "huge int": (_doc({"tests/a.py": 10**400}), "finite"),
    "duplicate top-level key": ('{"schema_version": 1, "schema_version": 1, "files": {}}', "repeats a key"),
    "duplicate file key": ('{"schema_version": 1, "files": {"tests/a.py": 1, "tests/a.py": 2}}', "repeats a key"),
    "no schema_version": ('{"files": {}}', "schema_version"),
    "schema_version 2": (_doc({}, 2), "schema_version"),
    "schema_version true": (_doc({}, True), "schema_version"),
    "schema_version string": (_doc({}, "1"), "schema_version"),
    "schema_version float": ('{"schema_version": 1.0, "files": {}}', "schema_version"),
    "no files": ('{"schema_version": 1}', "files must be an object"),
    "files list": (_doc([]), "files must be an object"),
    "files null": (_doc(None), "files must be an object"),
    "empty key": (_doc({"": 1}), "relative"),
    "absolute key": (_doc({"/tests/a.py": 1}), "relative"),
    "drive key": (_doc({"C:/tests/a.py": 1}), "relative"),
    "backslash key": (_doc({"tests\\a.py": 1}), "relative"),
    "parent segment key": (_doc({"tests/../a.py": 1}), "relative"),
    "node id key": (_doc({"tests/a.py::test_x": 1}), "relative"),
    "negative seconds": (_doc({"tests/a.py": -1}), ">= 0"),
    "bool seconds": (_doc({"tests/a.py": True}), "not a number"),
    "string seconds": (_doc({"tests/a.py": "1"}), "not a number"),
    "null seconds": (_doc({"tests/a.py": None}), "not a number"),
    "list seconds": (_doc({"tests/a.py": [1]}), "not a number"),
}


@pytest.mark.parametrize(("text", "message"), list(_BAD_DURATIONS.values()), ids=list(_BAD_DURATIONS))
def test_load_durations_rejects_a_file_that_breaks_the_schema(
    cs: ModuleType, tmp_path: Path, text: str, message: str
) -> None:
    with pytest.raises(cs.ShardError, match=message):
        cs.load_durations(_durations_file(tmp_path, text))


def test_load_durations_rejects_a_missing_file(cs: ModuleType, tmp_path: Path) -> None:
    with pytest.raises(cs.ShardError, match="unreadable"):
        cs.load_durations(tmp_path / "absent.json")


def test_load_durations_rejects_a_directory(cs: ModuleType, tmp_path: Path) -> None:
    with pytest.raises(cs.ShardError, match="unreadable"):
        cs.load_durations(tmp_path)


def test_load_durations_rejects_bytes_that_are_not_utf8(cs: ModuleType, tmp_path: Path) -> None:
    path = tmp_path / "durations.json"
    path.write_bytes(b'{"schema_version": 1, "files": {}}\xff')

    with pytest.raises(cs.ShardError, match="not valid JSON"):
        cs.load_durations(path)


def test_load_durations_rejects_json_nested_beyond_the_recursion_limit(
    cs: ModuleType, tmp_path: Path
) -> None:
    path = _durations_file(tmp_path, "[" * 200_000 + "]" * 200_000)

    with pytest.raises(cs.ShardError, match="not valid JSON"):
        cs.load_durations(path)


# --- the files-key rule is the generator's, as in the scheduler's loader --------------


@pytest.fixture(scope="module")
def scheduler() -> ModuleType:
    from tests.fixtures import duration_scheduler

    return duration_scheduler


def _committed_with_files(tmp_path: Path, files: dict[str, Any]) -> Path:
    payload = json.loads(REAL_DURATIONS.read_text(encoding="utf-8"))
    payload["files"] = files
    return _durations_file(tmp_path, payload)


def _judged(load: Any, error: type[Exception]) -> tuple[bool, str]:
    try:
        load()
    except error as exc:
        return False, str(exc)
    return True, ""


def test_both_loaders_read_the_committed_file_to_the_same_seconds(cs: ModuleType, scheduler: ModuleType) -> None:
    committed = scheduler.load_file_durations(REAL_DURATIONS)

    shard = cs.read_durations(REAL_DURATIONS).milliseconds

    assert len(shard) > 1000
    assert shard == {path: max(1, round(seconds * 1000)) for path, seconds in committed.files.items()}


def test_the_parity_file_is_valid_for_both_loaders_apart_from_its_key(
    cs: ModuleType, scheduler: ModuleType, tmp_path: Path
) -> None:
    path = _committed_with_files(tmp_path, {"tests/test_x.py": 1.5})

    assert dict(scheduler.load_file_durations(path).files) == {"tests/test_x.py": 1.5}
    assert cs.read_durations(path).milliseconds == {"tests/test_x.py": 1500}


@pytest.mark.parametrize("key", ["tests/../test_x.py", "tests/test_x.py::test_y", "tests\\test_x.py"])
def test_both_loaders_reject_an_escaping_or_node_id_key_with_the_generators_message(
    cs: ModuleType, scheduler: ModuleType, tmp_path: Path, key: str
) -> None:
    path = _committed_with_files(tmp_path, {key: 1.5})

    with pytest.raises(scheduler.DurationDataError, match="relative test path") as theirs:
        scheduler.load_file_durations(path)
    with pytest.raises(cs.ShardError, match="relative test path") as ours:
        cs.read_durations(path)

    assert str(theirs.value) in str(ours.value)


@pytest.mark.parametrize(
    "key",
    [
        "tests/test_x.py", "tests/sub/test_x.py", "tests/test_x.txt", "tests//test_x.py", "./tests/test_x.py",
        "", "tests/../test_x.py", "tests/test_x.py::test_y", "tests\\test_x.py", "/tests/test_x.py",
        "C:/tests/test_x.py", "//host/share/test_x.py",
    ],
    ids=repr,
)  # fmt: skip
def test_both_loaders_judge_every_files_key_alike(
    cs: ModuleType, scheduler: ModuleType, tmp_path: Path, key: str
) -> None:
    path = _committed_with_files(tmp_path, {key: 1.5})

    ours = _judged(lambda: cs.read_durations(path), cs.ShardError)
    theirs = _judged(lambda: scheduler.load_file_durations(path), scheduler.DurationDataError)

    assert ours[0] == theirs[0], (key, ours, theirs)
    assert theirs[1] in ours[1]


def test_the_key_rule_is_the_generators_function_and_no_local_copy(
    cs: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    script = tmp_path / "gen_file_durations.py"
    script.write_text(
        "def file_key_problem(key):\n    return 'stub says no' if key == 'tests/a.py' else None\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(cs, "_GENERATOR_PATH", script)
    refused = _durations_file(tmp_path, {"schema_version": 1, "files": {"tests/b.py": 1, "tests/a.py": 2}})
    accepted = _durations_file(tmp_path, {"schema_version": 1, "files": {"tests/b.txt": 1}}, "ok.json")

    with pytest.raises(cs.ShardError, match="stub says no"):
        cs.read_durations(refused)
    assert cs.read_durations(accepted).milliseconds == {"tests/b.txt": 1000}


@pytest.mark.parametrize(
    ("body", "failure"),
    [
        pytest.param(None, "FileNotFoundError", id="script-missing"),
        pytest.param("def file_key_problem(key:\n", "SyntaxError", id="syntax-error"),
        pytest.param("raise RuntimeError('boom')\n", "RuntimeError", id="raises-at-import"),
        pytest.param("import sys\nsys.exit(0)\n", "SystemExit", id="exits-at-import"),
        pytest.param("VALUE = 1\n", "AttributeError", id="rule-missing"),
    ],
)
def test_a_key_rule_that_cannot_be_loaded_is_a_shard_error(
    cs: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, body: str | None, failure: str
) -> None:
    script = tmp_path / "gen_file_durations.py"
    if body is not None:
        script.write_text(body, encoding="utf-8")
    monkeypatch.setattr(cs, "_GENERATOR_PATH", script)
    path = _durations_file(tmp_path, {"schema_version": 1, "files": {"tests/a.py": 1}})

    with pytest.raises(cs.ShardError, match=rf"cannot load the key rule from gen_file_durations\.py \({failure}\)"):
        cs.read_durations(path)


def test_a_key_rule_that_is_not_callable_is_a_shard_error(
    cs: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    script = tmp_path / "gen_file_durations.py"
    script.write_text("file_key_problem = 1\n", encoding="utf-8")
    monkeypatch.setattr(cs, "_GENERATOR_PATH", script)
    path = _durations_file(tmp_path, {"schema_version": 1, "files": {}})

    with pytest.raises(cs.ShardError, match=r"file_key_problem is not callable"):
        cs.read_durations(path)


@pytest.mark.parametrize(
    ("body", "failure"),
    [
        ("def file_key_problem(key):\n    raise RuntimeError('boom')\n", "RuntimeError"),
        ("def file_key_problem(key):\n    raise SystemExit(0)\n", "SystemExit"),
        ("def file_key_problem(key):\n    return 1 / 0\n", "ZeroDivisionError"),
    ],
    ids=["raises", "exits", "divides-by-zero"],
)
def test_a_key_rule_that_fails_when_called_is_a_shard_error(
    cs: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, body: str, failure: str
) -> None:
    script = tmp_path / "gen_file_durations.py"
    script.write_text(body, encoding="utf-8")
    monkeypatch.setattr(cs, "_GENERATOR_PATH", script)
    path = _durations_file(tmp_path, {"schema_version": 1, "files": {"tests/a.py": 1}})

    with pytest.raises(cs.ShardError, match=rf"the key rule failed on 'tests/a\.py' \({failure}\)"):
        cs.read_durations(path)


@pytest.mark.parametrize(
    "body",
    ["raise KeyboardInterrupt\n", "def file_key_problem(key):\n    raise KeyboardInterrupt\n"],
    ids=["at-import", "when-called"],
)
def test_a_keyboard_interrupt_from_the_key_rule_still_propagates(
    cs: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, body: str
) -> None:
    script = tmp_path / "gen_file_durations.py"
    script.write_text(body, encoding="utf-8")
    monkeypatch.setattr(cs, "_GENERATOR_PATH", script)
    path = _durations_file(tmp_path, {"schema_version": 1, "files": {"tests/a.py": 1}})

    with pytest.raises(KeyboardInterrupt):
        cs.read_durations(path)


def test_a_key_rule_that_exits_zero_cannot_end_verify_with_status_zero(
    cs: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = make_run(cs, tmp_path)
    run.write()
    script = tmp_path / "gen_file_durations.py"
    script.write_text("import sys\nsys.exit(0)\n", encoding="utf-8")
    monkeypatch.setattr(cs, "_GENERATOR_PATH", script)

    code, out, err = _verify(cs, capsys, run, write=False)

    assert (code, out) == (2, "")
    assert "usage error" in err and "cannot load the key rule from gen_file_durations.py (SystemExit)" in err


def test_loading_the_key_rule_writes_no_bytecode_and_registers_no_module(
    cs: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sys, "dont_write_bytecode", False)
    monkeypatch.setattr(sys, "pycache_prefix", None)
    real = cs._GENERATOR_PATH
    control, isolated = tmp_path / "control", tmp_path / "isolated"
    for directory in (control, isolated):
        directory.mkdir()
        shutil.copy(real, directory / real.name)
    # The premise: the ordinary import machinery does leave a bytecode cache beside a script,
    # so an untouched directory below proves something.
    spec = importlib.util.spec_from_file_location("_p27_control", control / real.name)
    assert spec is not None and spec.loader is not None
    spec.loader.exec_module(importlib.util.module_from_spec(spec))
    assert (control / "__pycache__").is_dir()
    monkeypatch.setattr(cs, "_GENERATOR_PATH", isolated / real.name)

    durations = cs.read_durations(REAL_DURATIONS)

    assert len(durations.milliseconds) > 1000, "every committed key went through the loaded rule"
    assert [path.name for path in isolated.rglob("*")] == [real.name]
    assert not [name for name in sys.modules if name.startswith("_ad1270f_p27_file_key")]


# --- node helpers ------------------------------------------------------------


def test_node_file_is_the_part_before_the_first_double_colon(cs: ModuleType) -> None:
    assert cs.node_file("tests/test_a.py::TestX::test_y[1::2]") == "tests/test_a.py"
    assert cs.node_file("tests/test_a.py") == "tests/test_a.py"
    assert cs.node_file("") == ""


@pytest.mark.parametrize(
    "ids",
    [[], ["tests/a.py::t"], ["tests/a.py::t[é]", 'tests/b.py::t["q"]', "tests/c.py::t\n2"]],
)
def test_node_digest_matches_the_gate_plugin_encoding(cs: ModuleType, ids: list[str]) -> None:
    gate_plugin = _load("gate_plugin_for_digest_parity", GATE_PLUGIN)

    assert cs.node_digest(ids) == gate_plugin._digest(tuple(ids))
    assert cs.node_digest(iter(ids)) == cs.node_digest(ids)


def test_node_digest_binds_the_order_it_is_given(cs: ModuleType) -> None:
    assert cs.node_digest(["a", "b"]) != cs.node_digest(["b", "a"])
    assert re.fullmatch(r"[0-9a-f]{64}", cs.node_digest(["a"]))


def test_ci_shards_uses_only_the_standard_library_and_disclaims_release_authority() -> None:
    import ast

    tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
    modules = {
        alias.name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {
        node.module.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    }

    assert modules <= set(sys.stdlib_module_names), sorted(modules - set(sys.stdlib_module_names))
    assert not [name for name in modules if "gate" in name]
    assert "CI shard evidence is not release authority" in (ast.get_docstring(tree) or "")


# --- assign_files ------------------------------------------------------------

def test_assign_files_spreads_the_longest_files_first(cs: ModuleType) -> None:
    counts = {f"tests/{name}.py": 1 for name in "abcdef"}
    durations = {
        "tests/a.py": 10000,
        "tests/b.py": 9000,
        "tests/c.py": 5000,
        "tests/d.py": 4000,
        "tests/e.py": 3000,
        "tests/f.py": 3000,
    }

    plan = cs.assign_files(_nodes(counts), durations, 3)

    assert plan.file_shards == {
        "tests/a.py": 1,
        "tests/b.py": 2,
        "tests/c.py": 3,
        "tests/d.py": 3,
        "tests/e.py": 2,
        "tests/f.py": 3,
    }
    assert plan.shard_ms == (10000, 12000, 12000)
    assert plan.unknown_files == ()


def test_assign_files_breaks_a_load_tie_by_the_shard_with_fewer_files(cs: ModuleType) -> None:
    counts = {f"tests/f{index}.py": 1 for index in range(6)}
    durations = {f"tests/f{index}.py": ms for index, ms in enumerate([1, 1, 1, 3, 3, 4])}

    plan = cs.assign_files(_nodes(counts), durations, 2)

    # f2 meets a 6 ms / 6 ms tie while shard 1 holds three files and shard 2 two, so it
    # goes to shard 2; a tie-break on shard index alone would have given it to shard 1
    assert plan.file_shards == {
        "tests/f5.py": 1,
        "tests/f3.py": 2,
        "tests/f4.py": 2,
        "tests/f0.py": 1,
        "tests/f1.py": 1,
        "tests/f2.py": 2,
    }
    assert plan.shard_ms == (6, 7)


def test_assign_files_breaks_a_full_tie_by_shard_index_and_path(cs: ModuleType) -> None:
    counts = {f"tests/{name}.py": 1 for name in "dcba"}
    durations = {f"tests/{name}.py": 1000 for name in "abcd"}

    plan = cs.assign_files(_nodes(counts), durations, 2)

    assert plan.file_shards == {"tests/a.py": 1, "tests/b.py": 2, "tests/c.py": 1, "tests/d.py": 2}


def test_assign_files_weighs_an_unknown_file_at_the_known_mean_per_node(cs: ModuleType) -> None:
    counts = {"tests/a.py": 3, "tests/b.py": 1, "tests/u.py": 2}
    durations = {"tests/a.py": 3000, "tests/b.py": 5000}

    plan = cs.assign_files(_nodes(counts), durations, 2)

    # known: 8000 ms over 4 nodes = 2000 ms per node, so u weighs 2 x 2000 = 4000 ms
    assert plan.file_shards == {"tests/b.py": 1, "tests/u.py": 2, "tests/a.py": 2}
    assert plan.shard_ms == (5000, 7000)
    assert plan.unknown_files == ("tests/u.py",)


def test_assign_files_floors_the_known_mean_per_node(cs: ModuleType) -> None:
    counts = {"tests/a.py": 2, "tests/u.py": 2}

    plan = cs.assign_files(_nodes(counts), {"tests/a.py": 7}, 2)

    assert plan.shard_ms == (7, 6)


def test_assign_files_weighs_an_unknown_file_at_least_one_millisecond_per_node(cs: ModuleType) -> None:
    counts = {"tests/k.py": 5, "tests/u.py": 3}

    plan = cs.assign_files(_nodes(counts), {"tests/k.py": 1}, 2)

    assert plan.file_shards == {"tests/u.py": 1, "tests/k.py": 2}
    assert plan.shard_ms == (3, 1)


def test_assign_files_weighs_every_node_at_a_second_when_no_file_is_known(cs: ModuleType) -> None:
    counts = {"tests/x.py": 2, "tests/y.py": 1}

    plan = cs.assign_files(_nodes(counts), {"tests/elsewhere.py": 9}, 2)

    assert plan.shard_ms == (2000, 1000)
    assert plan.unknown_files == ("tests/x.py", "tests/y.py")


def test_assign_files_ignores_durations_for_files_that_were_not_collected(cs: ModuleType) -> None:
    counts = {"tests/a.py": 2, "tests/b.py": 3, "tests/c.py": 1}
    durations = {"tests/a.py": 500, "tests/b.py": 900, "tests/c.py": 100}
    stale = {**durations, "tests/gone.py": 10**9, "tests/bad.py": 0}

    assert cs.assign_files(_nodes(counts), stale, 2) == cs.assign_files(_nodes(counts), durations, 2)


def test_assign_files_numbers_shards_from_one_and_fills_every_one(cs: ModuleType) -> None:
    counts = {f"tests/t{index}.py": 1 + index % 3 for index in range(10)}

    plan = cs.assign_files(_nodes(counts), {}, 4)

    assert set(plan.file_shards.values()) == {1, 2, 3, 4}
    assert sum(plan.shard_ms) == 1000 * sum(counts.values())
    assert max(plan.shard_ms) - min(plan.shard_ms) <= 3000


def test_assign_files_is_identical_for_any_input_order(cs: ModuleType) -> None:
    counts = {f"tests/f{index:02d}.py": 1 + (index * 7) % 5 for index in range(40)}
    durations = {f"tests/f{index:02d}.py": 100 * ((index * 13) % 11 + 1) for index in range(0, 40, 2)}
    ids = _nodes(counts)
    reference = cs.assign_files(ids, durations, 3)

    for seed in range(5):
        shuffled = list(ids)
        random.Random(seed).shuffle(shuffled)
        assert cs.assign_files(shuffled, durations, 3) == reference
    assert cs.assign_files(iter(ids), durations, 3) == reference


def test_assign_files_digest_hashes_the_sorted_path_shard_pairs(cs: ModuleType) -> None:
    counts = {f"tests/f{index}.py": 2 for index in range(6)}

    plan = cs.assign_files(_nodes(counts), {}, 3)
    pairs = sorted([path, shard] for path, shard in plan.file_shards.items())
    expected = hashlib.sha256(
        json.dumps(pairs, ensure_ascii=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()

    assert plan.assignment_sha256 == expected
    assert cs.assign_files(_nodes(counts), {}, 2).assignment_sha256 != expected


def test_assigned_nodeids_partition_the_collection(cs: ModuleType) -> None:
    ids = _nodes({f"tests/f{index}.py": 1 + index % 4 for index in range(9)})
    plan = cs.assign_files(ids, {}, 3)

    parts = [cs.assigned_nodeids(ids, plan.file_shards, shard) for shard in (1, 2, 3)]

    assert all(part == sorted(part) and part for part in parts)
    assert sorted(node for part in parts for node in part) == sorted(ids)
    assert sum(len(part) for part in parts) == len(ids)


def test_real_durations_split_into_three_balanced_nonempty_shards(cs: ModuleType) -> None:
    durations = cs.load_durations(REAL_DURATIONS)

    plan = cs.assign_files([f"{path}::test_x" for path in durations], durations, 3)

    assert sorted(set(plan.file_shards.values())) == [1, 2, 3]
    assert sum(plan.shard_ms) == sum(durations.values())
    assert max(plan.shard_ms) - min(plan.shard_ms) <= max(durations.values())
    assert plan.unknown_files == ()


@pytest.mark.parametrize("count", [0, -1, True, 1.5, "2", None])
def test_assign_files_rejects_a_shard_count_that_is_not_a_positive_int(
    cs: ModuleType, count: Any
) -> None:
    with pytest.raises(cs.ShardError, match="shard_count"):
        cs.assign_files(["tests/a.py::t"], {}, count)


def test_assign_files_rejects_duplicate_node_ids(cs: ModuleType) -> None:
    with pytest.raises(cs.ShardError, match="duplicate node IDs"):
        cs.assign_files(["tests/a.py::t", "tests/b.py::t", "tests/a.py::t"], {}, 1)


def test_assign_files_rejects_fewer_files_than_shards(cs: ModuleType) -> None:
    with pytest.raises(cs.ShardError, match=r"shard\(s\) \[3\] would get no files"):
        cs.assign_files(["tests/a.py::t", "tests/b.py::t"], {}, 3)


def test_assign_files_rejects_an_empty_collection(cs: ModuleType) -> None:
    with pytest.raises(cs.ShardError, match="no files"):
        cs.assign_files([], {}, 1)


@pytest.mark.parametrize("bad", [0, -5, True, 1.5, "7", None])
def test_assign_files_rejects_a_collected_file_with_unusable_milliseconds(
    cs: ModuleType, bad: Any
) -> None:
    with pytest.raises(cs.ShardError, match=r"durations_ms\['tests/a.py'\]"):
        cs.assign_files(["tests/a.py::t", "tests/b.py::t"], {"tests/a.py": bad}, 2)


# --- synthetic evidence ------------------------------------------------------

SECONDS = {
    "suite/test_a.py": 8.0,
    "suite/test_b.py": 6.0,
    "suite/test_c.py": 3.0,
    "suite/test_d.py": 1.0,
    "suite/test_stale.py": 99.0,
}


def _collection(extra: tuple[str, ...] = ()) -> list[str]:
    nodes = [
        f"suite/test_{name}.py::test_{number}"
        for name, count in (("a", 4), ("b", 3), ("c", 3), ("d", 2))
        for number in range(count)
    ]
    nodes += ["suite/test_e.py::test_one", "suite/test_e.py::test_unicode[\u00e9]", *extra]
    return sorted(nodes)


def _payload(
    cs: ModuleType,
    *,
    shard: int,
    shard_count: int,
    worker: str,
    worker_count: int,
    collection: list[str],
    plan: Any,
    durations: Any,
    reports: list[str],
) -> dict[str, Any]:
    assigned = sorted(n for n in collection if plan.file_shards[n.split("::", 1)[0]] == shard)
    payload: dict[str, Any] = {
        "kind": "probos-ci-shard-evidence",
        "schema_version": 1,
        "shard_index": shard,
        "shard_count": shard_count,
        "worker_id": worker,
        "worker_count": worker_count,
        "testrunuid": f"run-{shard}",
        "exitstatus": 0,
        "durations_path": "durations.json",
        "durations_sha256": durations.sha256,
        "collection_count": len(collection),
        "collection_sha256": cs.node_digest(collection),
        "assignment_sha256": plan.assignment_sha256,
        "assigned_count": len(assigned),
        "assigned_sha256": cs.node_digest(assigned),
        "unknown_file_count": len(plan.unknown_files),
        "setup_reports": list(reports),
    }
    if worker in ("gw0", "main"):
        payload["collected_nodeids"] = list(collection)
        payload["file_shards"] = dict(plan.file_shards)
    return payload


@dataclass
class Run:
    """A consistent synthetic CI run that tests then break one way at a time."""

    cs: ModuleType
    root: Path
    durations_path: Path
    durations: Any
    collection: list[str]
    plan: Any
    shard_count: int
    payloads: dict[int, dict[str, Any]]

    def write(self) -> Path:
        if self.root.exists():
            shutil.rmtree(self.root)
        self.root.mkdir(parents=True)
        for shard, workers in self.payloads.items():
            (self.root / f"shard-{shard}").mkdir()
            for worker, payload in workers.items():
                (self.root / f"shard-{shard}" / f"{worker}.json").write_text(
                    json.dumps(payload), encoding="utf-8"
                )
        return self.root

    def reports(self, shard: int, worker: str) -> list[str]:
        return self.payloads[shard][worker]["setup_reports"]


def make_run(
    cs: ModuleType,
    tmp_path: Path,
    *,
    layouts: dict[int, list[str]] | None = None,
    durations_path: Path | None = None,
    extra_nodes: tuple[str, ...] = (),
) -> Run:
    layouts = layouts or {1: ["gw0", "gw1"], 2: ["main"]}
    durations_path = durations_path or _durations_file(
        tmp_path, {"schema_version": 1, "files": SECONDS}
    )
    durations = cs.read_durations(durations_path)
    collection = _collection(extra_nodes)
    plan = cs.assign_files(collection, durations.milliseconds, len(layouts))
    payloads: dict[int, dict[str, Any]] = {}
    for shard, workers in layouts.items():
        files = sorted({path for path, owner in plan.file_shards.items() if owner == shard})
        payloads[shard] = {}
        for position, worker in enumerate(workers):
            mine = {path for index, path in enumerate(files) if index % len(workers) == position}
            payloads[shard][worker] = _payload(
                cs,
                shard=shard,
                shard_count=len(layouts),
                worker=worker,
                worker_count=len(workers),
                collection=collection,
                plan=plan,
                durations=durations,
                reports=[n for n in reversed(collection) if cs.node_file(n) in mine],
            )
    return Run(cs, tmp_path / "evidence", durations_path, durations, collection, plan, len(layouts), payloads)


def _verify(
    cs: ModuleType,
    capsys: pytest.CaptureFixture[str],
    run: Run,
    *,
    durations: Path | None = None,
    shard_count: int | None = None,
    write: bool = True,
) -> tuple[int, str, str]:
    root = run.write() if write else run.root
    argv = [
        "verify",
        "--evidence-root",
        str(root),
        "--shard-count",
        str(shard_count or run.shard_count),
        "--durations",
        str(durations or run.durations_path),
    ]
    code = cs.main(argv)
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def _shown(text: str) -> str:
    return text.encode("ascii", "backslashreplace").decode("ascii")


def _error_lines(out: str) -> list[str]:
    return [line for line in out.splitlines() if line.startswith("::error")]


# --- building and writing evidence --------------------------------------------


def test_build_evidence_matches_an_independently_built_payload(cs: ModuleType, tmp_path: Path) -> None:
    run = make_run(cs, tmp_path)

    for shard, workers in run.payloads.items():
        for worker, expected in workers.items():
            built = cs.build_evidence(
                shard_index=shard,
                shard_count=2,
                worker_id=worker,
                worker_count=len(workers),
                testrunuid=expected["testrunuid"],
                exitstatus=0,
                durations_path="durations.json",
                durations_sha256=run.durations.sha256,
                collection=run.collection,
                plan=run.plan,
                setup_reports=expected["setup_reports"],
            )
            assert built == expected
            assert ("collected_nodeids" in built) == (worker in {"gw0", "main"})
            assert ("file_shards" in built) == (worker in {"gw0", "main"})


def test_build_evidence_keeps_repeated_setup_reports_and_the_exit_status(
    cs: ModuleType, tmp_path: Path
) -> None:
    run = make_run(cs, tmp_path)
    node = run.reports(1, "gw1")[0]

    built = cs.build_evidence(
        shard_index=1,
        shard_count=2,
        worker_id="gw1",
        worker_count=2,
        testrunuid="u",
        exitstatus=pytest.ExitCode.TESTS_FAILED,
        durations_path="d.json",
        durations_sha256=run.durations.sha256,
        collection=run.collection,
        plan=run.plan,
        setup_reports=[node, node],
    )

    assert built["setup_reports"] == [node, node]
    assert built["exitstatus"] == 1 and type(built["exitstatus"]) is int


def test_write_evidence_writes_one_file_atomically_and_replaces_it(
    cs: ModuleType, tmp_path: Path
) -> None:
    run = make_run(cs, tmp_path)
    payload = run.payloads[1]["gw1"]

    first = cs.write_evidence(tmp_path / "out", payload)
    again = cs.write_evidence(tmp_path / "out", {**payload, "exitstatus": 3})

    assert first == again == tmp_path / "out" / "shard-1" / "gw1.json"
    assert json.loads(first.read_text(encoding="utf-8"))["exitstatus"] == 3
    assert [entry.name for entry in first.parent.iterdir()] == ["gw1.json"]


@pytest.mark.parametrize("worker", ["../x", "gw", "gw1/../../x", "gw1234567", "worker", "main2", ""])
def test_write_evidence_rejects_a_worker_id_that_is_not_main_or_gw_number(
    cs: ModuleType, tmp_path: Path, worker: str
) -> None:
    with pytest.raises(cs.ShardError, match="not main or gw"):
        cs.write_evidence(tmp_path, {"worker_id": worker, "shard_index": 1})

    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("index", [0, -1, True, 1.5, "../x", None])
def test_write_evidence_rejects_a_shard_index_that_is_not_a_positive_int(
    cs: ModuleType, tmp_path: Path, index: Any
) -> None:
    with pytest.raises(cs.ShardError, match="not a positive integer"):
        cs.write_evidence(tmp_path, {"worker_id": "main", "shard_index": index})

    assert list(tmp_path.iterdir()) == []


def test_write_evidence_removes_its_temporary_file_when_the_replace_fails(
    cs: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse(*_args: object) -> None:
        raise OSError("replace refused")

    monkeypatch.setattr(cs.os, "replace", refuse)

    with pytest.raises(OSError, match="replace refused"):
        cs.write_evidence(tmp_path, {"worker_id": "main", "shard_index": 2})

    assert list((tmp_path / "shard-2").iterdir()) == []


# --- verify: accepted --------------------------------------------------------


def test_verify_accepts_an_untampered_run_and_reports_each_shard(
    cs: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    run = make_run(cs, tmp_path)

    code, out, err = _verify(cs, capsys, run)

    assert (code, err) == (0, "")
    assert run.plan.unknown_files == ("suite/test_e.py",)
    expected = [
        f"verified {len(run.collection)} nodes: every collected node executed exactly once across 2 shards"
    ]
    for shard, workers in ((1, 2), (2, 1)):
        assigned = len(cs.assigned_nodeids(run.collection, run.plan.file_shards, shard))
        unknown = 1 if run.plan.file_shards["suite/test_e.py"] == shard else 0
        expected.append(
            f"  shard {shard}: assigned={assigned} executed={assigned} workers={workers} "
            f"estimated_load={run.plan.shard_ms[shard - 1] / 1000:.1f}s unknown_files={unknown}"
        )
    assert out.splitlines() == expected
    assert _error_lines(out) == []


def test_verify_accepts_three_single_process_shards(
    cs: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    run = make_run(cs, tmp_path, layouts={1: ["main"], 2: ["main"], 3: ["main"]})

    code, out, _ = _verify(cs, capsys, run)

    assert code == 0, out
    assert "across 3 shards" in out


def test_verify_accepts_a_single_xdist_worker_and_workers_with_no_files(
    cs: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    run = make_run(cs, tmp_path, layouts={1: ["gw0", "gw1", "gw2", "gw3"], 2: ["gw0"]})

    code, out, _ = _verify(cs, capsys, run)

    assert code == 0, out
    assert any(not run.reports(1, worker) for worker in ("gw2", "gw3"))
    assert "workers=4" in out and "workers=1" in out


# --- verify: rejected --------------------------------------------------------

GHOST = "suite/test_ghost.py::test_ghost"


def _drop_a_node(run: Run) -> list[str]:
    node = run.reports(1, "gw0").pop()
    return ["missing (never executed): 1", node]


def _repeat_a_node_in_one_worker(run: Run) -> list[str]:
    node = run.reports(1, "gw1")[0]
    run.reports(1, "gw1").append(node)
    return ["duplicated (executed more than once): 1", f"{node} <- shard-1/gw1 x2"]


def _run_a_node_in_two_shards(run: Run) -> list[str]:
    node = run.reports(1, "gw0")[0]
    run.reports(2, "main").append(node)
    return [
        "duplicated (executed more than once): 1",
        f"{node} <- shard-1/gw0, shard-2/main",
        "shard-2/main ran it; it belongs to shard-1",
    ]


def _run_a_node_only_in_the_wrong_shard(run: Run) -> list[str]:
    node = run.reports(1, "gw0").pop(0)
    run.reports(2, "main").append(node)
    return [
        "unexpected (outside the collection or its shard): 1",
        f"{node} <- shard-2/main ran it; it belongs to shard-1",
    ]


def _run_a_node_outside_the_collection(run: Run) -> list[str]:
    run.reports(2, "main").append(GHOST)
    return [f"{GHOST} <- shard-2/main ran it; it is not in the collection"]


def _shard_two_collects_one_node_fewer(run: Run) -> list[str]:
    main = run.payloads[2]["main"]
    main["collected_nodeids"].pop()
    main["collection_count"] -= 1
    main["collection_sha256"] = run.cs.node_digest(main["collected_nodeids"])
    return ["workers report different full collections"]


def _one_worker_reports_another_collection_digest(run: Run) -> list[str]:
    run.payloads[1]["gw1"]["collection_sha256"] = "0" * 64
    return ["workers report different full collections"]


def _lose_a_worker_file(run: Run) -> list[str]:
    lost = run.reports(1, "gw1")
    del run.payloads[1]["gw1"]
    return ["shard-1 lacks worker file gw1.json", "missing (never executed)", lost[0]]


def _gain_an_extra_worker_file(run: Run) -> list[str]:
    run.payloads[1]["gw2"] = {**run.payloads[1]["gw1"], "worker_id": "gw2"}
    return ["shard-1 has an extra worker file gw2.json"]


def _lose_a_shard_directory(run: Run) -> list[str]:
    del run.payloads[2]
    return ["evidence root has no shard-2 directory", "missing (never executed)"]


def _mix_testrunuids(run: Run) -> list[str]:
    run.payloads[1]["gw1"]["testrunuid"] = "another-run"
    return ["shard-1 mixes 2 different testrunuid values"]


def _report_a_nonzero_exit_status(run: Run) -> list[str]:
    run.payloads[2]["main"]["exitstatus"] = 1
    return ["shard-2/main reports exitstatus 1, not 0"]


def _tamper_the_assigned_digest(run: Run) -> list[str]:
    run.payloads[1]["gw1"]["assigned_sha256"] = "0" * 64
    return ["shard-1: gw1 report a assigned_sha256"]


def _tamper_the_assigned_count(run: Run) -> list[str]:
    run.payloads[2]["main"]["assigned_count"] += 1
    return ["shard-2: main report a assigned_count"]


def _tamper_the_assignment_digest(run: Run) -> list[str]:
    for worker in run.payloads[1].values():
        worker["assignment_sha256"] = "1" * 64
    return ["shard-1: gw0, gw1 report a assignment_sha256"]


def _tamper_the_unknown_file_count(run: Run) -> list[str]:
    run.payloads[2]["main"]["unknown_file_count"] += 1
    return ["shard-2: main report a unknown_file_count"]


def _tamper_the_file_shard_map(run: Run) -> list[str]:
    run.payloads[1]["gw0"]["file_shards"]["suite/test_a.py"] = 2
    return ["shard-1: gw0 report a file_shards"]


def _tamper_the_durations_digest(run: Run) -> list[str]:
    run.payloads[2]["main"]["durations_sha256"] = "2" * 64
    return ["shard-2: main report a durations_sha256"]


def _disagree_on_worker_count(run: Run) -> list[str]:
    run.payloads[1]["gw1"]["worker_count"] = 3
    return ["shard-1 workers disagree on worker_count: [2, 3]"]


def _put_main_beside_workers(run: Run) -> list[str]:
    run.payloads[1]["main"] = {**run.payloads[2]["main"], "shard_index": 1}
    return ["shard-1 mixes main.json with ['gw0', 'gw1']"]


def _claim_main_with_two_workers(run: Run) -> list[str]:
    run.payloads[2]["main"]["worker_count"] = 2
    return ["shard-2/main reports worker_count [2], not 1"]


def _unsort_the_collection(run: Run) -> list[str]:
    run.payloads[1]["gw0"]["collected_nodeids"].reverse()
    return ["shard-1/gw0 collected_nodeids is not sorted and unique"]


def _repeat_a_collected_node(run: Run) -> list[str]:
    ids = run.payloads[2]["main"]["collected_nodeids"]
    ids.insert(1, ids[0])
    return ["shard-2/main collected_nodeids is not sorted and unique"]


def _swap_a_collected_node(run: Run) -> list[str]:
    run.payloads[2]["main"]["collected_nodeids"][-1] = "suite/test_zzz.py::test_swapped"
    return ["shard-2/main collected_nodeids does not hash to its collection_sha256"]


def _name_the_wrong_shard(run: Run) -> list[str]:
    run.payloads[1]["gw0"]["shard_index"] = 2
    return ["shard-1/gw0.json has an invalid shard_index: '2'"]


def _name_the_wrong_shard_count(run: Run) -> list[str]:
    run.payloads[2]["main"]["shard_count"] = 3
    return ["shard-2/main.json has an invalid shard_count: '3'"]


def _name_the_wrong_worker(run: Run) -> list[str]:
    run.payloads[1]["gw1"]["worker_id"] = "gw0"
    return ["shard-1/gw1.json has an invalid worker_id: 'gw0'"]


def _lose_a_field(run: Run) -> list[str]:
    del run.payloads[1]["gw1"]["setup_reports"]
    return ["shard-1/gw1.json lacks field setup_reports"]


def _use_a_bool_exit_status(run: Run) -> list[str]:
    run.payloads[2]["main"]["exitstatus"] = False
    return ["shard-2/main.json has an invalid exitstatus: 'False'"]


def _use_a_string_node_count(run: Run) -> list[str]:
    run.payloads[2]["main"]["collection_count"] = str(len(run.collection))
    return ["shard-2/main.json has an invalid collection_count"]


def _use_a_foreign_kind(run: Run) -> list[str]:
    run.payloads[1]["gw0"]["kind"] = "probos-test-gate-evidence"
    return ["shard-1/gw0.json has an invalid kind"]


def _report_a_non_string_node(run: Run) -> list[str]:
    run.reports(1, "gw1").append(7)
    return ["shard-1/gw1.json has an invalid setup_reports"]


def _drop_the_collection_from_the_primary(run: Run) -> list[str]:
    del run.payloads[1]["gw0"]["collected_nodeids"]
    return ["shard-1/gw0.json lacks a list of collected_nodeids"]


def _drop_the_file_map_from_the_primary(run: Run) -> list[str]:
    run.payloads[2]["main"]["file_shards"] = {"suite/test_a.py": "1"}
    return ["shard-2/main.json lacks a file_shards map"]


def _write_a_list_instead_of_an_object(run: Run) -> list[str]:
    run.payloads[1]["gw1"] = ["not", "an", "object"]
    return ["shard-1/gw1.json is not a JSON object"]


def _lose_the_primary_worker_file(run: Run) -> list[str]:
    del run.payloads[1]["gw0"]
    return ["shard-1 lacks worker file gw0.json", "missing (never executed)"]


def _break_every_primary_collection(run: Run) -> list[str]:
    for workers in run.payloads.values():
        workers["main" if "main" in workers else "gw0"]["collected_nodeids"][-1] = "suite/test_zzz.py::test_swapped"
    return [
        "shard-1/gw0 collected_nodeids does not hash to its collection_sha256",
        "no primary worker file carries a verifiable full collection",
    ]


MUTATIONS = {
    "dropped node": _drop_a_node,
    "lost primary worker file": _lose_the_primary_worker_file,
    "no verifiable primary collection": _break_every_primary_collection,
    "node repeated within one worker": _repeat_a_node_in_one_worker,
    "node executed in two shards": _run_a_node_in_two_shards,
    "node executed once but in the wrong shard": _run_a_node_only_in_the_wrong_shard,
    "node outside the collection": _run_a_node_outside_the_collection,
    "differing full collection": _shard_two_collects_one_node_fewer,
    "one worker with another collection digest": _one_worker_reports_another_collection_digest,
    "missing worker file": _lose_a_worker_file,
    "extra worker file": _gain_an_extra_worker_file,
    "missing shard directory": _lose_a_shard_directory,
    "mixed testrunuid": _mix_testrunuids,
    "nonzero exitstatus": _report_a_nonzero_exit_status,
    "tampered assigned digest": _tamper_the_assigned_digest,
    "tampered assigned count": _tamper_the_assigned_count,
    "tampered assignment digest": _tamper_the_assignment_digest,
    "tampered unknown file count": _tamper_the_unknown_file_count,
    "tampered file-to-shard map": _tamper_the_file_shard_map,
    "tampered durations digest": _tamper_the_durations_digest,
    "worker_count disagreement": _disagree_on_worker_count,
    "main.json beside gw files": _put_main_beside_workers,
    "main.json claiming two workers": _claim_main_with_two_workers,
    "unsorted collected_nodeids": _unsort_the_collection,
    "repeated collected node": _repeat_a_collected_node,
    "collected_nodeids that do not hash": _swap_a_collected_node,
    "wrong shard index": _name_the_wrong_shard,
    "wrong shard count": _name_the_wrong_shard_count,
    "wrong worker id": _name_the_wrong_worker,
    "missing field": _lose_a_field,
    "bool exit status": _use_a_bool_exit_status,
    "string collection count": _use_a_string_node_count,
    "foreign kind": _use_a_foreign_kind,
    "non-string setup report": _report_a_non_string_node,
    "primary without collection": _drop_the_collection_from_the_primary,
    "primary with a bad file map": _drop_the_file_map_from_the_primary,
    "payload that is not an object": _write_a_list_instead_of_an_object,
}


@pytest.mark.parametrize("mutate", list(MUTATIONS.values()), ids=list(MUTATIONS))
def test_verify_rejects_broken_evidence_with_exit_one_and_one_error_line(
    cs: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str], mutate: Any
) -> None:
    run = make_run(cs, tmp_path)
    fragments = mutate(run)

    code, out, err = _verify(cs, capsys, run)

    assert code == 1, out
    assert err == ""
    for fragment in fragments:
        assert _shown(fragment) in out
    assert out.splitlines()[0] == "CI shard evidence REJECTED"
    assert len(_error_lines(out)) == 1 and out.splitlines()[-1].startswith("::error title=")
    assert not out.startswith("verified")


@pytest.mark.parametrize(
    ("mutate", "label"),
    [
        (_drop_a_node, "missing"),
        (_repeat_a_node_in_one_worker, "duplicated"),
        (_run_a_node_outside_the_collection, "unexpected"),
    ],
)
def test_verify_error_annotation_names_the_first_offending_node_when_nothing_else_is_wrong(
    cs: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str], mutate: Any, label: str
) -> None:
    run = make_run(cs, tmp_path)
    node = mutate(run)[-1].split(" <- ")[0]

    _, out, _ = _verify(cs, capsys, run)

    assert "0 problem(s)" in _error_lines(out)[0]
    assert f"first: {label} {_shown(node)}" in _error_lines(out)[0]


def test_verify_rejects_a_different_durations_file_by_its_digest(
    cs: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    run = make_run(cs, tmp_path)
    other = _durations_file(tmp_path, {"schema_version": 1, "files": {**SECONDS, "suite/test_d.py": 2.0}}, "other.json")

    code, out, _ = _verify(cs, capsys, run, durations=other)

    assert code == 1
    assert "report a durations_sha256" in out
    assert len(_error_lines(out)) == 1


def test_verify_rejects_a_shard_count_that_differs_from_the_evidence(
    cs: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    run = make_run(cs, tmp_path)

    code, out, _ = _verify(cs, capsys, run, shard_count=3)

    assert code == 1
    assert "evidence root has no shard-3 directory" in out
    assert "has an invalid shard_count: '2'" in out


def _category_rows(out: str, title: str) -> list[str]:
    lines = out.splitlines()
    start = next(index for index, line in enumerate(lines) if line.startswith(title))
    rows = []
    for line in lines[start + 1 :]:
        if not line.startswith("  "):
            break
        rows.append(line)
    return rows


def test_verify_prints_at_most_twenty_nodes_per_category(
    cs: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    gone = tuple(f"suite/test_gone.py::test_{number:02d}" for number in range(30))
    twice = tuple(f"suite/test_twice.py::test_{number:02d}" for number in range(22))
    run = make_run(cs, tmp_path, extra_nodes=gone + twice)
    for shard, workers in run.payloads.items():
        for worker, payload in workers.items():
            payload["setup_reports"] = [n for n in payload["setup_reports"] if n not in gone]
            if twice[0] in payload["setup_reports"]:
                payload["setup_reports"].extend(twice)
                payload["setup_reports"].extend(f"suite/test_ghost.py::test_{n}" for n in range(25))

    code, out, _ = _verify(cs, capsys, run)

    assert code == 1
    assert "missing (never executed): 30 (showing 20)" in out
    assert len(_category_rows(out, "missing (never executed)")) == 20
    assert "duplicated (executed more than once): 22 (showing 20)" in out
    assert len(_category_rows(out, "duplicated")) == 20
    assert "unexpected (outside the collection or its shard): 25 (showing 20)" in out
    assert len(_category_rows(out, "unexpected")) == 20
    assert len(_error_lines(out)) == 1
    assert "30 missing, 22 duplicated, 25 unexpected" in out


def test_verify_prints_only_ascii_even_for_unusual_node_ids(
    cs: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    newline = "suite/test_n.py::test_nl[a\nb]"
    run = make_run(cs, tmp_path, extra_nodes=(newline,))
    unicode_node = "suite/test_e.py::test_unicode[\u00e9]"
    for workers in run.payloads.values():
        for payload in workers.values():
            payload["setup_reports"] = [
                n for n in payload["setup_reports"] if n not in {newline, unicode_node}
            ]

    code, out, _ = _verify(cs, capsys, run)

    assert code == 1
    assert out.isascii()
    assert "suite/test_e.py::test_unicode[\\xe9]" in out
    assert "suite/test_n.py::test_nl[a\\x0ab]" in out
    assert len(_error_lines(out)) == 1
    assert out.splitlines()[-1].startswith("::error title=CI shard evidence::")


def test_verify_escapes_percent_and_newlines_in_the_error_annotation(
    cs: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    run = make_run(cs, tmp_path)
    run.payloads[1]["gw1"]["kind"] = "100%\nbad"

    _, out, _ = _verify(cs, capsys, run)

    error = _error_lines(out)
    assert len(error) == 1
    assert "invalid kind: '100%25\\nbad'" in error[0]


@pytest.mark.parametrize(
    "damage",
    ["notes.txt", ".gw0.0123.tmp", "subdir/", "gw0.json.bak", "gw1234567.json", "main.JSON"],
)
def test_verify_rejects_an_unexpected_entry_in_a_shard_directory(
    cs: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str], damage: str
) -> None:
    run = make_run(cs, tmp_path)
    root = run.write()
    target = root / "shard-1" / damage
    if damage.endswith("/"):
        target.mkdir()
    else:
        target.write_text("{}", encoding="utf-8")

    code, out, _ = _verify(cs, capsys, run, write=False)

    assert code == 1
    assert f"shard-1 has an unexpected entry {damage.rstrip('/')}" in out


@pytest.mark.parametrize("damage", ["notes.txt", "shard-3", "shard-0", "extra/"])
def test_verify_rejects_an_unexpected_entry_in_the_evidence_root(
    cs: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str], damage: str
) -> None:
    run = make_run(cs, tmp_path)
    root = run.write()
    if damage.endswith("/"):
        (root / damage).mkdir()
    else:
        (root / damage).write_text("{}", encoding="utf-8")

    code, out, _ = _verify(cs, capsys, run, write=False)

    assert code == 1
    assert f"evidence root has an unexpected entry {damage.rstrip('/')}" in out


def test_verify_rejects_a_shard_entry_that_is_a_file(
    cs: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    run = make_run(cs, tmp_path)
    root = run.write()
    shutil.rmtree(root / "shard-2")
    (root / "shard-2").write_text("{}", encoding="utf-8")

    code, out, _ = _verify(cs, capsys, run, write=False)

    assert code == 1
    assert "shard-2 is not a directory" in out


@pytest.mark.parametrize("content", ["{", "", "[1, 2]", "null", "\ufeff{}"])
def test_verify_rejects_an_evidence_file_that_is_not_a_json_object(
    cs: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str], content: str
) -> None:
    run = make_run(cs, tmp_path)
    root = run.write()
    (root / "shard-2" / "main.json").write_text(content, encoding="utf-8")

    code, out, _ = _verify(cs, capsys, run, write=False)

    assert code == 1
    assert "shard-2/main.json" in out


def test_verify_rejects_an_empty_shard_directory(
    cs: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    run = make_run(cs, tmp_path)
    root = run.write()
    (root / "shard-2" / "main.json").unlink()

    code, out, _ = _verify(cs, capsys, run, write=False)

    assert code == 1
    assert "shard-2 holds no evidence files" in out
    assert "missing (never executed)" in out


def test_verify_rejects_an_evidence_root_that_does_not_exist(
    cs: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    run = make_run(cs, tmp_path)

    code, out, _ = _verify(cs, capsys, run, write=False)

    assert code == 1
    assert "is not a directory" in out
    assert "no evidence file could be read" in out
    assert len(_error_lines(out)) == 1


def test_verify_rejects_evidence_whose_collection_cannot_fill_the_shards(
    cs: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    run = make_run(cs, tmp_path)
    for workers in run.payloads.values():
        for worker in workers.values():
            worker["shard_count"] = 9
    run.shard_count = 9

    code, out, _ = _verify(cs, capsys, run)

    assert code == 1
    assert "the verifier cannot recompute the file assignment" in out
    assert "would get no files" in out


# --- verify: usage errors and the real command line -----------------------------


@pytest.mark.parametrize(
    "argv",
    [
        [],
        ["verify"],
        ["verify", "--evidence-root", "x"],
        ["verify", "--shard-count", "2"],
        ["verify", "--evidence-root", "x", "--shard-count", "0"],
        ["verify", "--evidence-root", "x", "--shard-count", "two"],
        ["verify", "--evidence-root", "x", "--shard-count", "-1"],
        ["plan", "--evidence-root", "x", "--shard-count", "2"],
    ],
)
def test_verify_exits_two_on_a_usage_error(
    cs: ModuleType, capsys: pytest.CaptureFixture[str], argv: list[str]
) -> None:
    with pytest.raises(SystemExit) as raised:
        cs.main(argv)

    assert raised.value.code == 2
    assert capsys.readouterr().out == ""


@pytest.mark.parametrize("text", [None, "{", '{"schema_version": 2, "files": {}}'])
def test_verify_exits_two_when_the_durations_file_is_unusable(
    cs: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str], text: str | None
) -> None:
    run = make_run(cs, tmp_path)
    durations = tmp_path / "bad.json"
    if text is not None:
        durations.write_text(text, encoding="utf-8")

    code, out, err = _verify(cs, capsys, run, durations=durations)

    assert code == 2
    assert out == ""
    assert "usage error" in err and "durations file" in err


def _cli(*arguments: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    return subprocess.run(
        [sys.executable, str(SCRIPT), *arguments],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
        check=False,
    )


def test_command_line_verifies_with_the_default_durations_file_from_any_directory(
    cs: ModuleType, tmp_path: Path
) -> None:
    run = make_run(cs, tmp_path, durations_path=REAL_DURATIONS)
    root = run.write()
    arguments = ("verify", "--evidence-root", str(root), "--shard-count", "2")

    accepted = _cli(*arguments, cwd=tmp_path)
    run.reports(1, "gw0").pop()
    run.write()
    rejected = _cli(*arguments, cwd=tmp_path)
    unusable = _cli("verify", cwd=tmp_path)

    assert accepted.returncode == 0, accepted.stdout + accepted.stderr
    assert accepted.stdout.startswith(f"verified {len(run.collection)} nodes")
    assert rejected.returncode == 1
    assert len(_error_lines(rejected.stdout)) == 1
    assert unusable.returncode == 2 and "usage:" in unusable.stderr


def test_command_line_rejects_evidence_built_against_another_durations_file(
    cs: ModuleType, tmp_path: Path
) -> None:
    run = make_run(cs, tmp_path)
    root = run.write()

    completed = _cli("verify", "--evidence-root", str(root), "--shard-count", "2", cwd=tmp_path)

    assert completed.returncode == 1
    assert "durations_sha256" in completed.stdout


# --- the ci.yml drift guard ----------------------------------------------------

SHARD_JOB = "python-tests-shard"
SUMMARY_JOB = "python-tests"
SELECTION_FLAGS = {
    "-k", "-m", "--deselect", "--ignore", "--ignore-glob", "--lf", "--last-failed",
    "--ff", "--failed-first", "-x", "--exitfirst", "--sw", "--stepwise",
}  # fmt: skip


def _workflow() -> dict[str, Any]:
    return yaml.safe_load(CI_YML.read_text(encoding="utf-8"))


def _tokens(command: str) -> list[str]:
    expanded = re.sub(
        r"\$\{\{\s*(.*?)\s*\}\}", lambda match: "<" + re.sub(r"\s+", "", match.group(1)) + ">", command
    )
    return shlex.split(expanded)


def _option(tokens: list[str], name: str) -> list[str]:
    values = [tokens[i + 1] for i, token in enumerate(tokens[:-1]) if token == name]
    return values + [token.split("=", 1)[1] for token in tokens if token.startswith(name + "=")]


def _run_of(job: dict[str, Any], needle: str) -> str:
    runs = [step["run"] for step in job["steps"] if needle in step.get("run", "")]
    assert len(runs) == 1, runs
    return runs[0]


def _step_using(job: dict[str, Any], action: str) -> dict[str, Any]:
    steps = [step for step in job["steps"] if str(step.get("uses", "")).startswith(action + "@")]
    assert len(steps) == 1, steps
    return steps[0]


def _shard_pytest_tokens() -> list[str]:
    tokens = _tokens(_run_of(_workflow()["jobs"][SHARD_JOB], "pytest"))
    return tokens[tokens.index("pytest") + 1 :]


def test_workflow_matrix_and_every_shard_count_agree() -> None:
    jobs = _workflow()["jobs"]
    matrix = jobs[SHARD_JOB]["strategy"]["matrix"]
    count = len(matrix["shard"])
    verify = _tokens(_run_of(jobs[SUMMARY_JOB], "ci_shards.py"))

    assert set(matrix) == {"shard"}
    assert matrix["shard"] == list(range(1, count + 1)) and count >= 2
    assert _option(_shard_pytest_tokens(), "--probos-shard-count") == [str(count)]
    assert _option(verify, "--shard-count") == [str(count)]
    assert _option(_shard_pytest_tokens(), "--probos-shard-index") == ["<matrix.shard>"]


def test_shard_job_keeps_the_runner_environment_extras_and_timeouts() -> None:
    shard = _workflow()["jobs"][SHARD_JOB]

    assert "name" not in shard
    assert shard["runs-on"] == "ubuntu-latest"
    assert shard["timeout-minutes"] == 45
    assert shard["strategy"]["fail-fast"] is False
    assert shard["env"] == {"PROBOS_EMBEDDINGS": "local"}
    assert _step_using(shard, "actions/checkout")["uses"] == "actions/checkout@v7"
    setup_python = _step_using(shard, "actions/setup-python")
    assert (setup_python["uses"], setup_python["with"]) == ("actions/setup-python@v5", {"python-version": "3.12"})
    assert _step_using(shard, "astral-sh/setup-uv")["uses"] == "astral-sh/setup-uv@v5"
    assert _run_of(shard, "uv sync") == "uv sync --group dev --extra discovery --extra browser"


def test_shard_command_loads_the_plugin_and_keeps_the_original_pytest_arguments() -> None:
    shard = _workflow()["jobs"][SHARD_JOB]
    command = _tokens(_run_of(shard, "pytest"))
    args = _shard_pytest_tokens()

    assert command[:5] == ["uv", "run", "python", "-m", "pytest"]
    assert args[0] == "tests/"
    assert _option(args, "-n") == ["auto"]
    assert "--maxfail=10" in args and "-q" in args and "--tb=short" in args
    assert _option(args, "-p") == ["scripts._ci_shard_pytest_plugin"]
    assert _option(args, "--probos-shard-evidence-dir") == ["<runner.temp>/ci-shard-evidence"]
    assert not [token for token in args if token.startswith("--probos-shard-durations")]


@pytest.mark.parametrize("flag", sorted(SELECTION_FLAGS))
def test_shard_command_cannot_select_deselect_or_stop_early_by_flag(flag: str) -> None:
    for token in _shard_pytest_tokens():
        assert token.split("=", 1)[0] != flag
        if len(flag) == 2 and re.fullmatch(r"-[A-Za-z]{2,}", token):
            assert flag[1] not in token[1:], f"{flag} hides inside the short-flag cluster {token}"


def test_workflow_cannot_change_pytest_selection_through_the_environment() -> None:
    text = CI_YML.read_text(encoding="utf-8")

    assert "PYTEST_ADDOPTS" not in text and "PYTEST_PLUGINS" not in text


def test_shard_job_uploads_its_evidence_whatever_the_outcome() -> None:
    shard = _workflow()["jobs"][SHARD_JOB]
    upload = _step_using(shard, "actions/upload-artifact")
    major = int(upload["uses"].split("@v")[1].split(".")[0])

    assert major >= 4
    assert shard["steps"].index(upload) == len(shard["steps"]) - 1
    assert upload["if"] == "${{ !cancelled() }}"
    assert upload["with"] == {
        "name": "ci-shard-evidence-${{ matrix.shard }}",
        "path": "${{ runner.temp }}/ci-shard-evidence",
        "if-no-files-found": "error",
        "overwrite": True,
        "retention-days": 7,
    }


def test_summary_job_keeps_the_check_name_and_cannot_pass_on_a_skipped_shard() -> None:
    jobs = _workflow()["jobs"]
    summary = jobs[SUMMARY_JOB]
    first = summary["steps"][0]

    assert "name" not in summary
    assert summary["needs"] in (SHARD_JOB, [SHARD_JOB])
    assert summary["if"] == "${{ always() }}"
    assert summary["timeout-minutes"] == 15
    assert summary["runs-on"] == "ubuntu-latest"
    assert "needs.python-tests-shard.result != 'success'" in first["if"]
    assert "exit 1" in first["run"]
    assert "uv " not in " ".join(step.get("run", "") for step in summary["steps"])


def test_summary_job_downloads_every_shard_artifact_and_runs_the_verifier() -> None:
    jobs = _workflow()["jobs"]
    summary = jobs[SUMMARY_JOB]
    steps = summary["steps"]
    download = _step_using(summary, "actions/download-artifact")
    major = int(download["uses"].split("@v")[1].split(".")[0])
    verify = _tokens(_run_of(summary, "ci_shards.py"))
    evidence = jobs[SHARD_JOB]["steps"][-1]["with"]["path"]

    assert _step_using(summary, "actions/checkout")["uses"] == "actions/checkout@v7"
    setup_python = _step_using(summary, "actions/setup-python")
    assert (setup_python["uses"], setup_python["with"]) == ("actions/setup-python@v5", {"python-version": "3.12"})
    assert major >= 4
    assert download["with"] == {
        "pattern": "ci-shard-evidence-*",
        "merge-multiple": True,
        "path": evidence,
    }
    assert verify[:3] == ["python", "scripts/ci_shards.py", "verify"]
    assert _option(verify, "--evidence-root") == ["<runner.temp>/ci-shard-evidence"]
    assert "--durations" not in verify
    verify_step = steps[-1]
    assert verify_step["run"].startswith("python scripts/ci_shards.py verify")
    assert steps.index(download) < steps.index(verify_step)
    assert steps.index(summary["steps"][0]) < steps.index(download)


def _comment_block_above(lines: list[str], index: int) -> str:
    block = []
    for line in reversed(lines[:index]):
        if not line.strip().startswith("#"):
            break
        block.append(line.strip())
    return "\n".join(reversed(block))


def test_workflow_keeps_the_rationale_comments_beside_the_commands_they_explain() -> None:
    lines = CI_YML.read_text(encoding="utf-8").splitlines()
    timeout = lines.index("    timeout-minutes: 45")
    step = next(i for i, line in enumerate(lines) if line == "      - name: Run tests")
    run = next(i for i in range(step, len(lines)) if lines[i].strip().startswith("run:"))
    step_comments = "\n".join(line.strip() for line in lines[step + 1 : run])
    timeout_comments = _comment_block_above(lines, timeout)
    text = "\n".join(lines)

    assert "BF-322" in timeout_comments and "BF-657" in timeout_comments
    assert "BF-322" in step_comments and "BF-657" in step_comments and "-n auto" in step_comments
    assert "--maxfail=10" in step_comments and "missing node" in step_comments
    assert re.search(r"#.*exactly once", text)
    assert "release authority" in text
