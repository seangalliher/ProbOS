"""AD-1270f — fail-broad impact selector in shadow mode.

Every rule in ``select_tests.FAIL_BROAD_RULES`` gets a firing test on a real
input and a non-firing test on a benign one. A rule permanently on is not a
safety property, it is a broken selector that merely looks safe, so the pair is
the acceptance property, not the firing half alone. ``FIRING_TESTS`` below binds
each ID to its firing test and ``test_every_fail_broad_rule_has_a_firing_test``
fails the suite when a rule is added without one.

Git-dependent rules run against synthetic temporary repositories: an
unrelated-history base or a genuine rename cannot be faked against the live
tree. Blast-radius patterns are additionally proven against the live tree so the
pattern list claims nothing that does not exist.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest


REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "select_tests.py"
LIVE_SEAMS_DIR = REPO_ROOT / "docs" / "development" / "seams"
LIVE_LEDGER = REPO_ROOT / "docs" / "development" / "test-selection-shadow-ledger.jsonl"
LIVE_GATE_DIR = REPO_ROOT / "logs" / "gates"


def _load_selector() -> ModuleType:
    spec = importlib.util.spec_from_file_location("select_tests", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def selector() -> ModuleType:
    return _load_selector()


#: Rule ID -> the name of the test that proves it fires on a real input.
FIRING_TESTS: dict[str, str] = {
    "map-missing": "test_map_missing_fails_broad",
    "map-schema": "test_map_schema_drift_fails_broad",
    "map-base-unknown": "test_map_base_unknown_fails_broad",
    "map-not-ancestor": "test_map_not_ancestor_fails_broad",
    "map-tree-mismatch": "test_map_tree_mismatch_fails_broad",
    "change-deleted": "test_change_deleted_fails_broad",
    "change-renamed": "test_change_renamed_fails_broad",
    "blast-radius": "test_blast_radius_fails_broad",
    "unknown-module": "test_unknown_module_fails_broad",
    "dynamic-import": "test_dynamic_import_fails_broad",
    "uncontexted-test": "test_unaccounted_collected_node_fails_broad",
    "selector-self-change": "test_selector_self_change_fails_broad",
}


# ---------------------------------------------------------------------------
# Synthetic repository fixture
# ---------------------------------------------------------------------------


def _git(repo: Path, *arguments: str) -> None:
    subprocess.run(["git", *arguments], cwd=repo, check=True, capture_output=True)


def _commit(repo: Path, message: str) -> str:
    _git(
        repo,
        "-c",
        "user.name=ProbOS Tests",
        "-c",
        "user.email=tests@probos.invalid",
        "commit",
        "-q",
        "-m",
        message,
    )
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


FULL_NODES = (
    "tests/test_alpha.py::test_one",
    "tests/test_alpha.py::test_three",
    "tests/test_alpha.py::test_two",
)


def _make_repo(tmp_path: Path) -> tuple[Path, str]:
    """A minimal repo whose layout mirrors the paths the selector reasons about."""
    repo = tmp_path / "repo"
    (repo / "src" / "probos" / "startup").mkdir(parents=True)
    (repo / "tests").mkdir()
    (repo / "scripts").mkdir()
    (repo / "docs" / "development" / "seams").mkdir(parents=True)
    _git(repo, "init", "-q", "-b", "main")
    (repo / "src" / "probos" / "alpha.py").write_text("VALUE = 1\n", encoding="utf-8")
    (repo / "src" / "probos" / "beta.py").write_text("VALUE = 2\n", encoding="utf-8")
    (repo / "src" / "probos" / "runtime.py").write_text("BOOT = 1\n", encoding="utf-8")
    (repo / "src" / "probos" / "movable.py").write_text(
        "MOVED = 'stable content so rename detection has something to match'\n",
        encoding="utf-8",
    )
    (repo / "tests" / "test_alpha.py").write_text(
        "def test_one():\n    pass\n\n\ndef test_two():\n    pass\n\n\n"
        "def test_three():\n    pass\n",
        encoding="utf-8",
    )
    (repo / "scripts" / "select_tests.py").write_text("SELECTOR = 1\n", encoding="utf-8")
    _git(repo, "add", "-A")
    head = _commit(repo, "initial")
    return repo, head


def _tree_of(repo: Path, commit: str) -> str:
    return subprocess.run(
        ["git", "rev-parse", f"{commit}^{{tree}}"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _map(selector: ModuleType, repo: Path, base: str, **overrides: object):
    payload: dict[str, object] = {
        "schema_version": selector.SCHEMA_VERSION,
        "selector_version": selector.SELECTOR_VERSION,
        "map_version": selector.MAP_VERSION,
        "base_commit": base,
        "base_tree": _tree_of(repo, base),
        "contexts": {
            "tests.test_alpha.test_one": ("src/probos/alpha.py",),
            "tests.test_alpha.test_two": ("src/probos/beta.py",),
        },
        "measured_files": (
            "src/probos/alpha.py",
            "src/probos/beta.py",
            "src/probos/movable.py",
            "src/probos/runtime.py",
        ),
        "uncontexted_tests": ("tests/test_alpha.py::test_three",),
    }
    payload.update(overrides)
    return selector.TestMap(**payload)  # type: ignore[arg-type]


def _select(selector: ModuleType, repo: Path, test_map, **kwargs):
    return selector.select(
        repo_root=repo,
        test_map=test_map,
        map_errors=kwargs.pop("map_errors", []),
        full_nodes=kwargs.pop("full_nodes", FULL_NODES),
        seams_dir=kwargs.pop("seams_dir", repo / "docs" / "development" / "seams"),
        base=kwargs.pop("base", None),
    )


@pytest.fixture()
def benign(selector: ModuleType, tmp_path: Path):
    """A repo with one ordinary edit to a mapped, non-blast-radius module."""
    repo, head = _make_repo(tmp_path)
    (repo / "src" / "probos" / "alpha.py").write_text("VALUE = 99\n", encoding="utf-8")
    return repo, head, _select(selector, repo, _map(selector, repo, head))


# ---------------------------------------------------------------------------
# Firing tests -- one per rule ID, on a real input
# ---------------------------------------------------------------------------


def test_map_missing_fails_broad(selector: ModuleType, tmp_path: Path) -> None:
    repo, _ = _make_repo(tmp_path)
    result = _select(selector, repo, None, map_errors=["no test map found"])
    assert result.verdict == "fail-broad"
    assert "map-missing" in result.reasons
    assert result.nodes == result.full_nodes


def test_map_schema_drift_fails_broad(selector: ModuleType, tmp_path: Path) -> None:
    repo, head = _make_repo(tmp_path)
    result = _select(
        selector, repo, _map(selector, repo, head, selector_version="ad-1270f.0")
    )
    assert result.verdict == "fail-broad"
    assert "map-schema" in result.reasons


def test_map_base_unknown_fails_broad(selector: ModuleType, tmp_path: Path) -> None:
    repo, head = _make_repo(tmp_path)
    absent = "0" * 40
    result = _select(
        selector,
        repo,
        _map(selector, repo, head, base_commit=absent),
    )
    assert result.verdict == "fail-broad"
    assert "map-base-unknown" in result.reasons


def test_map_not_ancestor_fails_broad(selector: ModuleType, tmp_path: Path) -> None:
    """A sibling commit exists in the repo but is not reachable from HEAD."""
    repo, head = _make_repo(tmp_path)
    _git(repo, "checkout", "-q", "-b", "sibling", head)
    (repo / "src" / "probos" / "alpha.py").write_text("SIDE = 1\n", encoding="utf-8")
    _git(repo, "add", "-A")
    sibling = _commit(repo, "sibling")
    _git(repo, "checkout", "-q", "main")
    (repo / "src" / "probos" / "beta.py").write_text("MAIN = 1\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _commit(repo, "main advances")

    ancestor = subprocess.run(
        ["git", "merge-base", "--is-ancestor", sibling, "HEAD"],
        cwd=repo,
        capture_output=True,
    )
    assert ancestor.returncode == 1, "premise: the sibling must not be an ancestor"

    result = _select(selector, repo, _map(selector, repo, sibling))
    assert result.verdict == "fail-broad"
    assert "map-not-ancestor" in result.reasons


def test_map_tree_mismatch_fails_broad(selector: ModuleType, tmp_path: Path) -> None:
    repo, head = _make_repo(tmp_path)
    result = _select(selector, repo, _map(selector, repo, head, base_tree="1" * 40))
    assert result.verdict == "fail-broad"
    assert "map-tree-mismatch" in result.reasons


def test_change_deleted_fails_broad(selector: ModuleType, tmp_path: Path) -> None:
    repo, head = _make_repo(tmp_path)
    (repo / "src" / "probos" / "beta.py").unlink()
    result = _select(selector, repo, _map(selector, repo, head))
    assert result.verdict == "fail-broad"
    assert "change-deleted" in result.reasons
    assert any("src/probos/beta.py" in detail for detail in result.details)


def test_change_renamed_fails_broad(selector: ModuleType, tmp_path: Path) -> None:
    repo, head = _make_repo(tmp_path)
    _git(repo, "mv", "src/probos/movable.py", "src/probos/relocated.py")
    _commit(repo, "rename")
    result = _select(selector, repo, _map(selector, repo, head))
    assert result.verdict == "fail-broad"
    assert "change-renamed" in result.reasons
    assert any("relocated.py" in detail for detail in result.details)


def test_blast_radius_fails_broad(selector: ModuleType, tmp_path: Path) -> None:
    repo, head = _make_repo(tmp_path)
    (repo / "src" / "probos" / "runtime.py").write_text("BOOT = 2\n", encoding="utf-8")
    result = _select(selector, repo, _map(selector, repo, head))
    assert result.verdict == "fail-broad"
    assert "blast-radius" in result.reasons


def test_unknown_module_fails_broad(selector: ModuleType, tmp_path: Path) -> None:
    repo, head = _make_repo(tmp_path)
    (repo / "src" / "probos" / "gamma.py").write_text("NEW = 1\n", encoding="utf-8")
    _git(repo, "add", "src/probos/gamma.py")
    result = _select(selector, repo, _map(selector, repo, head))
    assert result.verdict == "fail-broad"
    assert "unknown-module" in result.reasons
    assert any("src/probos/gamma.py" in detail for detail in result.details)


def test_dynamic_import_fails_broad(selector: ModuleType, tmp_path: Path) -> None:
    repo, head = _make_repo(tmp_path)
    (repo / "src" / "probos" / "alpha.py").write_text(
        "import importlib\n\n\ndef load(name):\n"
        "    return importlib.import_module(name)\n",
        encoding="utf-8",
    )
    result = _select(selector, repo, _map(selector, repo, head))
    assert result.verdict == "fail-broad"
    assert "dynamic-import" in result.reasons


def test_unaccounted_collected_node_fails_broad(
    selector: ModuleType, tmp_path: Path
) -> None:
    """A node the map can neither resolve nor name in its uncontexted census."""
    repo, head = _make_repo(tmp_path)
    (repo / "src" / "probos" / "alpha.py").write_text("VALUE = 9\n", encoding="utf-8")
    result = _select(
        selector,
        repo,
        _map(selector, repo, head),
        full_nodes=(*FULL_NODES, "tests/test_alpha.py::test_brand_new"),
    )
    assert result.verdict == "fail-broad"
    assert "uncontexted-test" in result.reasons
    assert any("test_brand_new" in detail for detail in result.details)


def test_selector_self_change_fails_broad(selector: ModuleType, tmp_path: Path) -> None:
    repo, head = _make_repo(tmp_path)
    (repo / "scripts" / "select_tests.py").write_text("SELECTOR = 2\n", encoding="utf-8")
    result = _select(selector, repo, _map(selector, repo, head))
    assert result.verdict == "fail-broad"
    assert "selector-self-change" in result.reasons


# ---------------------------------------------------------------------------
# Non-firing tests -- one per rule ID, on a discriminating benign input
# ---------------------------------------------------------------------------


def test_benign_change_selects_rather_than_failing_broad(benign) -> None:
    _, _, result = benign
    assert result.verdict == "selected"
    assert result.reasons == ()
    assert len(result.nodes) < len(result.full_nodes)


def test_map_missing_absent_when_a_map_is_present(benign) -> None:
    assert "map-missing" not in benign[2].reasons


def test_map_schema_absent_when_versions_match(benign) -> None:
    assert "map-schema" not in benign[2].reasons


def test_map_base_unknown_absent_when_base_exists(benign) -> None:
    assert "map-base-unknown" not in benign[2].reasons


def test_map_not_ancestor_absent_when_base_is_an_ancestor(
    selector: ModuleType, tmp_path: Path
) -> None:
    """The base is a real ancestor two commits back, not merely HEAD itself."""
    repo, head = _make_repo(tmp_path)
    (repo / "src" / "probos" / "alpha.py").write_text("VALUE = 5\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _commit(repo, "advance")
    result = _select(selector, repo, _map(selector, repo, head))
    assert "map-not-ancestor" not in result.reasons


def test_map_tree_mismatch_absent_when_declared_tree_matches(benign) -> None:
    assert "map-tree-mismatch" not in benign[2].reasons


def test_change_deleted_absent_for_a_modification(benign) -> None:
    _, _, result = benign
    assert "change-deleted" not in result.reasons
    assert [entry.status for entry in result.changed] == ["M"]


def test_change_renamed_absent_for_a_modification(benign) -> None:
    assert "change-renamed" not in benign[2].reasons


def test_blast_radius_absent_for_an_ordinary_module(benign) -> None:
    _, _, result = benign
    assert "blast-radius" not in result.reasons
    assert result.changed_paths == ("src/probos/alpha.py",)


def test_unknown_module_absent_when_the_module_is_measured(benign) -> None:
    assert "unknown-module" not in benign[2].reasons


def test_a_changed_data_file_fails_broad(
    selector: ModuleType, tmp_path: Path
) -> None:
    """Coverage sees executed lines, not files opened.

    A changed YAML that tests read produces no context anywhere, so the
    pre-widening behaviour was a ``selected`` verdict with zero nodes -- the
    worst shape this tool can emit. Measured on the live tree during the build:
    three doc-only edits selected 0 of 26,340 nodes.
    """
    repo, head = _make_repo(tmp_path)
    (repo / "config").mkdir()
    (repo / "config" / "system.yaml").write_text("value: 1\n", encoding="utf-8")
    _git(repo, "add", "config/system.yaml")
    result = _select(selector, repo, _map(selector, repo, head))
    assert result.verdict == "fail-broad"
    assert "unknown-module" in result.reasons
    assert any("cannot be related to any test" in d for d in result.details)


def test_a_changed_markdown_file_fails_broad(
    selector: ModuleType, tmp_path: Path
) -> None:
    repo, head = _make_repo(tmp_path)
    (repo / "README.md").write_text("# docs\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    result = _select(selector, repo, _map(selector, repo, head))
    assert result.verdict == "fail-broad"
    assert "unknown-module" in result.reasons


def test_an_empty_selection_for_a_real_change_fails_broad(
    selector: ModuleType, tmp_path: Path
) -> None:
    """A change that resolves to no test is not a fast run; it is a miss."""
    repo, head = _make_repo(tmp_path)
    (repo / "src" / "probos" / "movable.py").write_text("X = 2\n", encoding="utf-8")
    # movable.py is measured but carries no context, and the map's uncontexted
    # census is empty here, so nothing at all resolves.
    result = _select(
        selector,
        repo,
        _map(selector, repo, head, uncontexted_tests=()),
        full_nodes=("tests/test_alpha.py::test_one", "tests/test_alpha.py::test_two"),
    )
    assert result.verdict == "fail-broad"
    assert "unknown-module" in result.reasons
    assert any("resolved to zero tests" in detail for detail in result.details)
    assert result.nodes == result.full_nodes


def test_a_changed_test_file_alone_does_not_fire_unknown_module(
    selector: ModuleType, tmp_path: Path
) -> None:
    """Editing a test is the commonest change; its own nodes are selectable."""
    repo, head = _make_repo(tmp_path)
    (repo / "tests" / "test_alpha.py").write_text(
        "def test_one():\n    pass\n\n\ndef test_two():\n    pass\n\n\n"
        "def test_three():\n    assert 1\n",
        encoding="utf-8",
    )
    result = _select(selector, repo, _map(selector, repo, head))
    assert "unknown-module" not in result.reasons
    assert result.verdict == "selected"


def test_dynamic_import_absent_for_a_constant_argument(
    selector: ModuleType, tmp_path: Path
) -> None:
    """A literal module name is a static edge the map already sees."""
    repo, head = _make_repo(tmp_path)
    (repo / "src" / "probos" / "alpha.py").write_text(
        "import importlib\n\n\ndef load():\n"
        "    return importlib.import_module('probos.beta')\n",
        encoding="utf-8",
    )
    result = _select(selector, repo, _map(selector, repo, head))
    assert "dynamic-import" not in result.reasons
    assert result.verdict == "selected"


@pytest.mark.parametrize(
    "source",
    [
        "import importlib as il\n\n\ndef load(n):\n    return il.import_module(n)\n",
        "from importlib import import_module\n\n\ndef load(n):\n"
        "    return import_module(n)\n",
        "from importlib import import_module as _load\n\n\ndef load(n):\n"
        "    return _load(n)\n",
        "def load(n):\n    return __import__(n)\n",
    ],
    ids=["module-alias", "from-import", "from-import-alias", "builtin"],
)
def test_dynamic_import_sees_ordinary_import_styles(
    selector: ModuleType, tmp_path: Path, source: str
) -> None:
    """An attribute-only matcher is walked straight through by normal style.

    ``from importlib import import_module`` renders a bare name with no
    attribute node at all; adversarial review found exactly this class in
    AD-1270b slice 2, so each form is proven rather than assumed.
    """
    repo, head = _make_repo(tmp_path)
    (repo / "src" / "probos" / "alpha.py").write_text(source, encoding="utf-8")
    result = _select(selector, repo, _map(selector, repo, head))
    assert result.verdict == "fail-broad"
    assert "dynamic-import" in result.reasons


def test_dynamic_import_ignores_a_matching_name_in_a_comment_or_docstring(
    selector: ModuleType, tmp_path: Path
) -> None:
    """AST only: a dotted path in prose must not read as behaviour."""
    repo, head = _make_repo(tmp_path)
    (repo / "src" / "probos" / "alpha.py").write_text(
        '"""Never call importlib.import_module(name) here."""\n'
        "# importlib.import_module(name)\n"
        "TEXT = 'importlib.import_module(name)'\n",
        encoding="utf-8",
    )
    result = _select(selector, repo, _map(selector, repo, head))
    assert "dynamic-import" not in result.reasons
    assert result.verdict == "selected"


def test_an_unparseable_changed_file_fails_broad(
    selector: ModuleType, tmp_path: Path
) -> None:
    repo, head = _make_repo(tmp_path)
    (repo / "src" / "probos" / "alpha.py").write_text("def (\n", encoding="utf-8")
    result = _select(selector, repo, _map(selector, repo, head))
    assert result.verdict == "fail-broad"
    assert "dynamic-import" in result.reasons


def test_uncontexted_test_absent_when_every_node_is_accounted_for(benign) -> None:
    assert "uncontexted-test" not in benign[2].reasons


def test_selector_self_change_absent_for_an_ordinary_path(benign) -> None:
    assert "selector-self-change" not in benign[2].reasons


# ---------------------------------------------------------------------------
# Completeness
# ---------------------------------------------------------------------------


def test_every_fail_broad_rule_has_a_firing_test(selector: ModuleType) -> None:
    """Adding a rule without a firing test fails the suite here."""
    module = sys.modules[__name__]
    assert set(selector.FAIL_BROAD_RULES) == set(FIRING_TESTS)
    assert len(selector.FAIL_BROAD_RULES) == len(set(selector.FAIL_BROAD_RULES))
    missing = [
        name for name in FIRING_TESTS.values() if not callable(getattr(module, name, None))
    ]
    assert missing == [], f"firing tests named but not defined: {missing}"


def test_fail_broad_rules_is_the_only_source_of_reason_ids(
    selector: ModuleType, tmp_path: Path
) -> None:
    """No run may emit a reason outside the declared set."""
    repo, head = _make_repo(tmp_path)
    (repo / "src" / "probos" / "runtime.py").write_text("BOOT = 3\n", encoding="utf-8")
    (repo / "src" / "probos" / "beta.py").unlink()
    result = _select(selector, repo, _map(selector, repo, head, base_tree="2" * 40))
    assert result.reasons
    assert set(result.reasons) <= set(selector.FAIL_BROAD_RULES)


# ---------------------------------------------------------------------------
# Context <-> node-ID translation
# ---------------------------------------------------------------------------


def test_context_for_a_module_level_test(selector: ModuleType) -> None:
    assert (
        selector.context_for_node("tests/test_alpha.py::test_one")
        == "tests.test_alpha.test_one"
    )


def test_context_for_a_class_method(selector: ModuleType) -> None:
    assert (
        selector.context_for_node(
            "tests/test_builder_agent.py::TestAct::test_act_parses_file_blocks"
        )
        == "tests.test_builder_agent.TestAct.test_act_parses_file_blocks"
    )


def test_context_strips_the_parametrisation_suffix(selector: ModuleType) -> None:
    assert (
        selector.context_for_node("tests/test_alpha.py::test_one[case-2]")
        == "tests.test_alpha.test_one"
    )


def test_parametrised_nodes_fan_out_from_one_context(selector: ModuleType) -> None:
    """One context selects every parameterisation -- conservative, not precise."""
    index = selector.build_context_index(
        [
            "tests/test_alpha.py::test_one[a]",
            "tests/test_alpha.py::test_one[b]",
            "tests/test_alpha.py::test_one[c]",
            "tests/test_alpha.py::test_two",
        ]
    )
    assert len(index["tests.test_alpha.test_one"]) == 3
    assert index["tests.test_alpha.test_two"] == ("tests/test_alpha.py::test_two",)


def test_a_node_without_a_separator_has_no_context(selector: ModuleType) -> None:
    assert selector.context_for_node("tests/test_alpha.py") is None
    assert selector.context_for_node("not-a-node") is None


def test_an_unresolvable_map_context_fails_broad(
    selector: ModuleType, tmp_path: Path
) -> None:
    """A context that resolves to no collected node is never silently dropped."""
    repo, head = _make_repo(tmp_path)
    (repo / "src" / "probos" / "alpha.py").write_text("VALUE = 4\n", encoding="utf-8")
    contexts = {
        "tests.test_alpha.test_one": ("src/probos/alpha.py",),
        "tests.test_alpha.test_two": ("src/probos/beta.py",),
        "tests.test_gone.test_vanished": ("src/probos/alpha.py",),
    }
    result = _select(selector, repo, _map(selector, repo, head, contexts=contexts))
    assert result.verdict == "fail-broad"
    assert "uncontexted-test" in result.reasons
    assert any("resolve to no collected node" in detail for detail in result.details)


@pytest.mark.skipif(
    not list(LIVE_GATE_DIR.glob("*.collection.json")),
    reason="no shipped gate collection artifact on this machine",
)
def test_translation_resolves_every_live_collected_node(selector: ModuleType) -> None:
    """Risk 3: translations rot. Assert the rate against the live collection."""
    artifact = sorted(LIVE_GATE_DIR.glob("*.collection.json"))[-1]
    nodes, errors = selector.load_collection(artifact)
    assert errors == []
    assert len(nodes) > 1000
    unresolvable = [node for node in nodes if selector.context_for_node(node) is None]
    assert unresolvable == [], f"{len(unresolvable)} node(s) produced no context"
    index = selector.build_context_index(nodes)
    assert sum(len(found) for found in index.values()) == len(nodes)
    assert any(len(found) > 1 for found in index.values()), "expected fan-out"


# ---------------------------------------------------------------------------
# Seam manifest union
# ---------------------------------------------------------------------------


def _write_seams(directory: Path, entries: list[dict[str, object]]) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "fixture-manifest.yaml").write_text(
        json.dumps({"schema_version": 1, "seams": entries, "tombstones": []}),
        encoding="utf-8",
    )


def test_fixture_manifest_yields_its_non_null_crossing_tests(
    selector: ModuleType, tmp_path: Path
) -> None:
    _write_seams(
        tmp_path / "seams",
        [
            {"id": "TA-P0-001-a", "crossing_test": "tests/test_alpha.py::test_one"},
            {"id": "TA-P0-002-b", "crossing_test": "tests/test_alpha.py::test_two"},
        ],
    )
    found, errors = selector.seam_crossing_tests(tmp_path / "seams")
    assert errors == ()
    assert found == (
        "tests/test_alpha.py::test_one",
        "tests/test_alpha.py::test_two",
    )


def test_fixture_manifest_ignores_null_and_blank_crossing_tests(
    selector: ModuleType, tmp_path: Path
) -> None:
    _write_seams(
        tmp_path / "seams",
        [
            {"id": "TA-P0-001-a", "crossing_test": None},
            {"id": "TA-P0-002-b", "crossing_test": "   "},
            {"id": "TA-P0-003-c", "crossing_test": "tests/test_alpha.py::test_two"},
        ],
    )
    found, errors = selector.seam_crossing_tests(tmp_path / "seams")
    assert errors == ()
    assert found == ("tests/test_alpha.py::test_two",)


def test_fixture_manifest_reports_a_non_string_crossing_test(
    selector: ModuleType, tmp_path: Path
) -> None:
    _write_seams(tmp_path / "seams", [{"id": "TA-P0-001-a", "crossing_test": 17}])
    found, errors = selector.seam_crossing_tests(tmp_path / "seams")
    assert found == ()
    assert any("crossing_test is not a string" in problem for problem in errors)


def test_seam_crossing_tests_are_unioned_into_a_selection(
    selector: ModuleType, tmp_path: Path
) -> None:
    """The union path, proven with non-null values the live manifest lacks."""
    repo, head = _make_repo(tmp_path)
    (repo / "src" / "probos" / "alpha.py").write_text("VALUE = 7\n", encoding="utf-8")
    seams = repo / "docs" / "development" / "seams"
    without = _select(selector, repo, _map(selector, repo, head), seams_dir=seams)
    assert without.verdict == "selected"
    assert "tests/test_alpha.py::test_two" not in without.nodes

    _write_seams(seams, [{"id": "TA-P0-001-a", "crossing_test": "tests/test_alpha.py::test_two"}])
    with_seam = _select(selector, repo, _map(selector, repo, head), seams_dir=seams)
    assert with_seam.verdict == "selected"
    assert "tests/test_alpha.py::test_two" in with_seam.nodes
    assert set(without.nodes) < set(with_seam.nodes)


def test_a_missing_seams_directory_fails_broad(
    selector: ModuleType, tmp_path: Path
) -> None:
    repo, head = _make_repo(tmp_path)
    (repo / "src" / "probos" / "alpha.py").write_text("VALUE = 8\n", encoding="utf-8")
    result = _select(
        selector, repo, _map(selector, repo, head), seams_dir=repo / "no-such-dir"
    )
    assert result.verdict == "fail-broad"
    assert "uncontexted-test" in result.reasons


def test_the_live_seam_manifest_contributes_nothing_today(
    selector: ModuleType,
) -> None:
    """AD-1270b slice 3 has not shipped: all 8 crossing_test values are null.

    An empty input looks identical to a rule that works, which is why the union
    above is proven with a fixture rather than with this.
    """
    found, errors = selector.seam_crossing_tests(LIVE_SEAMS_DIR)
    assert errors == ()
    assert found == ()


# ---------------------------------------------------------------------------
# Ledger
# ---------------------------------------------------------------------------


def test_declare_enrollment_writes_the_header_once(
    selector: ModuleType, tmp_path: Path
) -> None:
    repo, _ = _make_repo(tmp_path)
    ledger = tmp_path / "ledger.jsonl"
    written, message = selector.declare_enrollment(ledger, repo_root=repo)
    assert written, message
    records, errors = selector.read_ledger(ledger)
    assert errors == []
    assert len(records) == 1
    assert records[0]["kind"] == "enrollment"
    assert records[0]["target_runs"] == selector.TARGET_RUNS
    assert records[0]["cutoff_utc"]


def test_a_second_declare_enrollment_is_refused(
    selector: ModuleType, tmp_path: Path
) -> None:
    repo, _ = _make_repo(tmp_path)
    ledger = tmp_path / "ledger.jsonl"
    assert selector.declare_enrollment(ledger, repo_root=repo)[0]
    before = ledger.read_bytes()
    written, message = selector.declare_enrollment(ledger, repo_root=repo)
    assert not written
    assert "already exists" in message
    assert ledger.read_bytes() == before


def test_verify_append_refuses_truncation(selector: ModuleType) -> None:
    with pytest.raises(RuntimeError, match="shortens the file"):
        selector.verify_append(b'{"a":1}\n{"b":2}\n', b'{"a":1}\n')


def test_verify_append_refuses_a_rewrite_of_existing_bytes(
    selector: ModuleType,
) -> None:
    with pytest.raises(RuntimeError, match="append-only"):
        selector.verify_append(b'{"a":1}\n', b'{"a":2}\n{"b":3}\n')


def test_verify_append_refuses_a_no_op_write(selector: ModuleType) -> None:
    with pytest.raises(RuntimeError, match="added no bytes"):
        selector.verify_append(b'{"a":1}\n', b'{"a":1}\n')


def test_append_refuses_a_ledger_whose_last_line_is_partial(
    selector: ModuleType, tmp_path: Path
) -> None:
    ledger = tmp_path / "ledger.jsonl"
    ledger.write_text('{"kind":"enrollment"}\n{"kind":"run"', encoding="utf-8")
    with pytest.raises(RuntimeError, match="partial"):
        selector._append_ledger(ledger, {"kind": "run"})


def test_a_same_tree_retry_is_recorded_but_marked_ineligible(
    selector: ModuleType, tmp_path: Path
) -> None:
    repo, head = _make_repo(tmp_path)
    (repo / "src" / "probos" / "alpha.py").write_text("VALUE = 3\n", encoding="utf-8")
    ledger = tmp_path / "ledger.jsonl"
    assert selector.declare_enrollment(ledger, repo_root=repo)[0]
    result = _select(selector, repo, _map(selector, repo, head))
    collection = tmp_path / "collection.json"
    collection.write_text(json.dumps({"collected_nodeids": list(FULL_NODES)}), "utf-8")

    first, _ = selector.run_shadow(
        repo_root=repo,
        result=result,
        collection_path=collection,
        ledger_path=ledger,
        record_dir=tmp_path / "shadow",
    )
    second, _ = selector.run_shadow(
        repo_root=repo,
        result=result,
        collection_path=collection,
        ledger_path=ledger,
        record_dir=tmp_path / "shadow",
    )
    assert first["eligible"] is True
    assert second["eligible"] is False, "a same-tree retry cannot pad the sample"
    rows = [r for r in selector.read_ledger(ledger)[0] if r["kind"] == "run"]
    assert len(rows) == 2, "the retry is still recorded, and remains visible as cost"
    assert selector.check_ledger(ledger) == []


def test_check_ledger_detects_a_tampered_node_digest(
    selector: ModuleType, tmp_path: Path
) -> None:
    ledger = tmp_path / "ledger.jsonl"
    ledger.write_text(
        json.dumps(
            {
                "kind": "enrollment",
                "schema_version": 1,
                "cutoff_utc": "2026-01-01T00:00:00+00:00",
            }
        )
        + "\n"
        + json.dumps(
            {
                "kind": "run",
                "schema_version": 1,
                "recorded_at_utc": "2026-02-01T00:00:00+00:00",
                "tree_fingerprint": "abc",
                "eligible": True,
                "changed_path_count": 1,
                "selected_nodes": ["tests/test_alpha.py::test_one"],
                "selector": {"nodes_sha256": "0" * 64},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    problems = selector.check_ledger(ledger)
    assert any("nodes_sha256 disagrees" in problem for problem in problems)


def test_check_ledger_requires_the_header_first(
    selector: ModuleType, tmp_path: Path
) -> None:
    ledger = tmp_path / "ledger.jsonl"
    ledger.write_text(json.dumps({"kind": "run", "schema_version": 1}) + "\n", "utf-8")
    problems = selector.check_ledger(ledger)
    assert any("first record is not the enrollment header" in p for p in problems)


def test_the_ledger_survives_crlf_and_mixed_line_endings(
    selector: ModuleType, tmp_path: Path
) -> None:
    """``core.autocrlf=true`` here and there is no ``.gitattributes``.

    A fresh checkout hands back CRLF while appends are written LF, so the file
    is legitimately mixed. Reading must not depend on which, and an append onto
    CRLF must still satisfy the prefix check.
    """
    repo, _ = _make_repo(tmp_path)
    ledger = tmp_path / "ledger.jsonl"
    assert selector.declare_enrollment(ledger, repo_root=repo)[0]
    ledger.write_bytes(ledger.read_bytes().replace(b"\n", b"\r\n"))
    records, errors = selector.read_ledger(ledger)
    assert errors == []
    assert len(records) == 1 and records[0]["kind"] == "enrollment"

    selector._append_ledger(ledger, {"kind": "run", "schema_version": 1})
    raw = ledger.read_bytes()
    assert b"\r\n" in raw and raw.endswith(b"}\n")
    mixed, errors = selector.read_ledger(ledger)
    assert errors == []
    assert [record["kind"] for record in mixed] == ["enrollment", "run"]


def test_ledger_status_never_claims_the_series_is_complete(
    selector: ModuleType, tmp_path: Path
) -> None:
    """The 20-run series cannot complete in one session; nothing may imply it has."""
    repo, _ = _make_repo(tmp_path)
    ledger = tmp_path / "ledger.jsonl"
    selector.declare_enrollment(ledger, repo_root=repo)
    status = selector.ledger_status(ledger)
    assert status["series_complete"] is False
    assert "NOT complete" in status["series_status"]
    assert status["eligible_count"] < status["target_runs"]


def test_the_live_ledger_is_structurally_sound_and_incomplete(
    selector: ModuleType,
) -> None:
    """Pins the durable invariants, not a transient row count.

    At the AD-1270f slice-1 commit the ledger holds exactly one run row, and
    that is verified by inspection rather than asserted here: hard-coding the
    count would fail the moment the series legitimately accrues its second row,
    which is the whole point of the enrollment.
    """
    records, errors = selector.read_ledger(LIVE_LEDGER)
    assert errors == []
    assert records and records[0]["kind"] == "enrollment"
    assert records[0]["series"] == selector.SERIES_NAME
    assert records[0]["target_runs"] == selector.TARGET_RUNS
    assert selector.check_ledger(LIVE_LEDGER) == []
    status = selector.ledger_status(LIVE_LEDGER)
    assert status["series_complete"] is False
    assert status["eligible_count"] < status["target_runs"]
    assert status["detected_misses"] == 0


# ---------------------------------------------------------------------------
# Balance measurement
# ---------------------------------------------------------------------------


def _write_balance_pair(
    tmp_path: Path,
    *,
    nodes: list[str],
    junit_nodes: list[tuple[str, str, str, float]],
    workers: dict[str, int],
) -> tuple[Path, Path]:
    collection = tmp_path / "collection.json"
    collection.write_text(
        json.dumps({"collected_nodeids": nodes, "worker_execution_counts": workers}),
        encoding="utf-8",
    )
    cases = "".join(
        f'<testcase classname="{classname}" name="{name}" file="{file}" time="{time}"/>'
        for file, classname, name, time in junit_nodes
    )
    junit = tmp_path / "junit.xml"
    junit.write_text(
        f'<?xml version="1.0"?><testsuites><testsuite name="pytest" tests="'
        f'{len(junit_nodes)}">{cases}</testsuite></testsuites>',
        encoding="utf-8",
    )
    return collection, junit


def test_gate_balance_reports_union_equality(
    selector: ModuleType, tmp_path: Path
) -> None:
    collection, junit = _write_balance_pair(
        tmp_path,
        nodes=["tests/test_a.py::test_one", "tests/test_a.py::TestB::test_two"],
        junit_nodes=[
            ("tests/test_a.py", "tests.test_a", "test_one", 0.5),
            ("tests\\test_a.py", "tests.test_a.TestB", "test_two", 1.5),
        ],
        workers={"gw0": 1, "gw1": 1},
    )
    report = selector.gate_balance(collection, junit)
    assert report["errors"] == []
    assert report["union_equal"] is True
    assert report["only_in_collection_count"] == 0
    assert report["only_in_junit_count"] == 0
    assert report["total_duration_seconds"] == 2.0


def test_gate_balance_reports_a_union_mismatch(
    selector: ModuleType, tmp_path: Path
) -> None:
    collection, junit = _write_balance_pair(
        tmp_path,
        nodes=["tests/test_a.py::test_one", "tests/test_a.py::test_missing"],
        junit_nodes=[("tests/test_a.py", "tests.test_a", "test_one", 0.1)],
        workers={"gw0": 2},
    )
    report = selector.gate_balance(collection, junit)
    assert report["union_equal"] is False
    assert report["only_in_collection"] == ["tests/test_a.py::test_missing"]


def test_gate_balance_detects_duplicates(selector: ModuleType, tmp_path: Path) -> None:
    collection, junit = _write_balance_pair(
        tmp_path,
        nodes=["tests/test_a.py::test_one", "tests/test_a.py::test_one"],
        junit_nodes=[
            ("tests/test_a.py", "tests.test_a", "test_one", 0.1),
            ("tests/test_a.py", "tests.test_a", "test_one", 0.2),
        ],
        workers={"gw0": 2},
    )
    report = selector.gate_balance(collection, junit)
    assert report["duplicate_collected_nodes"] == ["tests/test_a.py::test_one"]
    assert report["duplicate_junit_nodes"] == ["tests/test_a.py::test_one"]


def test_gate_balance_reports_per_worker_counts_and_spread(
    selector: ModuleType, tmp_path: Path
) -> None:
    collection, junit = _write_balance_pair(
        tmp_path,
        nodes=["tests/test_a.py::test_one"],
        junit_nodes=[("tests/test_a.py", "tests.test_a", "test_one", 0.25)],
        workers={"gw0": 100, "gw1": 400},
    )
    report = selector.gate_balance(collection, junit)
    assert report["worker_count"] == 2
    assert report["worker_min"] == 100
    assert report["worker_max"] == 400
    assert report["worker_spread_ratio"] == 4.0
    assert report["worker_total_matches_collection"] is False


def test_junit_node_id_reconstruction(selector: ModuleType) -> None:
    assert (
        selector.junit_node_id(
            {
                "file": "tests\\test_knowledge_store.py",
                "classname": "tests.test_knowledge_store.TestKnowledgeConfig",
                "name": "test_defaults",
            }
        )
        == "tests/test_knowledge_store.py::TestKnowledgeConfig::test_defaults"
    )
    assert (
        selector.junit_node_id(
            {"file": "tests/test_a.py", "classname": "tests.test_a", "name": "test_x[1]"}
        )
        == "tests/test_a.py::test_x[1]"
    )
    assert (
        selector.junit_node_id(
            {"file": "tests/test_a.py", "classname": "unrelated", "name": "test_x"}
        )
        is None
    )


@pytest.mark.skipif(
    not list(LIVE_GATE_DIR.glob("*.collection.json"))
    or not list(LIVE_GATE_DIR.glob("*.xml")),
    reason="no shipped gate artifacts on this machine",
)
def test_gate_balance_against_the_live_shipped_gate(selector: ModuleType) -> None:
    """Measurement only: the imbalance is real and this slice changes nothing."""
    collection = sorted(LIVE_GATE_DIR.glob("*.collection.json"))[-1]
    junit = collection.with_name(collection.name.replace(".collection.json", ".xml"))
    if not junit.is_file():
        pytest.skip("the newest collection artifact has no paired JUnit report")
    report = selector.gate_balance(collection, junit)
    assert report["errors"] == []
    assert report["union_equal"] is True
    assert report["junit_unresolved_testcases"] == 0
    assert report["worker_total_matches_collection"] is True
    assert report["worker_spread_ratio"] > 1.0


# ---------------------------------------------------------------------------
# Blast-radius patterns against the live tree
# ---------------------------------------------------------------------------


def _tracked(*patterns: str) -> list[str]:
    completed = subprocess.run(
        ["git", "ls-files", "-z", "--", *patterns],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return [name.replace("\\", "/") for name in completed.stdout.split("\0") if name]


@pytest.mark.parametrize(
    "pattern",
    [
        "src/probos/runtime.py",
        "src/probos/startup/*",
        "src/probos/config.py",
        "src/probos/types.py",
        "src/probos/*protocol*.py",
        "src/probos/*event*.py",
        "pyproject.toml",
        "*conftest.py",
        "scripts/run_test_gate.py",
        "scripts/_gate_pytest_plugin.py",
        "scripts/_gate_process_supervisor.py",
    ],
)
def test_blast_radius_pattern_matches_a_real_tracked_file(
    selector: ModuleType, pattern: str
) -> None:
    assert pattern in selector.BLAST_RADIUS_PATTERNS
    tracked = _tracked("*")
    assert any(
        selector.matches_any(name, (pattern,)) for name in tracked
    ), f"{pattern} matches nothing on the live tree"


def test_conftest_pattern_is_a_glob_not_a_hardcoded_pair(selector: ModuleType) -> None:
    """Root conftest.py does not exist today; a glob catches one appearing later."""
    assert set(_tracked("*conftest.py")) == {
        "tests/ablation/conftest.py",
        "tests/conftest.py",
    }
    assert selector.matches_any("conftest.py", selector.BLAST_RADIUS_PATTERNS)
    assert selector.matches_any(
        "tests/ablation/conftest.py", selector.BLAST_RADIUS_PATTERNS
    )


def test_protocol_and_event_globs_cover_per_domain_modules(
    selector: ModuleType,
) -> None:
    """The broader glob is deliberate: uncertainty selects more, never fewer."""
    for name in ("src/probos/discovery/protocol.py", "src/probos/avatars/events.py"):
        assert Path(REPO_ROOT / name).is_file(), f"premise: {name} must exist"
        assert selector.matches_any(name, selector.BLAST_RADIUS_PATTERNS)


def test_requirements_glob_is_forward_looking(selector: ModuleType) -> None:
    """No requirements.txt here -- the manifest is pyproject.toml -- but one
    appearing later must be caught without a code change."""
    assert _tracked("requirements*.txt") == []
    assert selector.matches_any("requirements.txt", selector.BLAST_RADIUS_PATTERNS)


# ---------------------------------------------------------------------------
# Structure, read-only guarantees, and the release-authority boundary
# ---------------------------------------------------------------------------


def test_main_returns_an_integer_and_requires_a_mode(selector: ModuleType) -> None:
    with pytest.raises(SystemExit):
        selector.main([])
    assert selector.main(["--check", "--ledger", str(LIVE_LEDGER)]) == 0


def test_check_mode_writes_nothing_into_the_repository(
    selector: ModuleType,
) -> None:
    before = subprocess.run(
        ["git", "status", "--porcelain=v1", "--untracked-files=all"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert selector.main(["--check", "--ledger", str(LIVE_LEDGER)]) == 0
    after = subprocess.run(
        ["git", "status", "--porcelain=v1", "--untracked-files=all"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert before == after


def test_shadow_dry_run_writes_nothing(selector: ModuleType, tmp_path: Path) -> None:
    repo, head = _make_repo(tmp_path)
    (repo / "src" / "probos" / "alpha.py").write_text("VALUE = 2\n", encoding="utf-8")
    ledger = tmp_path / "ledger.jsonl"
    selector.declare_enrollment(ledger, repo_root=repo)
    before = ledger.read_bytes()
    result = _select(selector, repo, _map(selector, repo, head))
    payload, _ = selector.run_shadow(
        repo_root=repo,
        result=result,
        collection_path=tmp_path / "collection.json",
        ledger_path=ledger,
        record_dir=tmp_path / "shadow",
        dry_run=True,
    )
    assert payload["record"] is None
    assert ledger.read_bytes() == before
    assert not (tmp_path / "shadow").exists()


def test_the_selector_is_absent_from_the_gate_wrapper() -> None:
    """No path by which selection authorizes release, and no preflight phase."""
    gate = (REPO_ROOT / "scripts" / "run_test_gate.py").read_text(encoding="utf-8")
    assert "select_tests" not in gate


def test_no_runtime_module_imports_the_selector() -> None:
    """AD-1270a D6: the direction is checker -> data, never runtime -> tool."""
    offenders = [
        name
        for name in _tracked("src/probos/*.py")
        if "select_tests" in (REPO_ROOT / name).read_text(encoding="utf-8")
    ]
    assert offenders == []


def test_the_module_docstring_states_the_promotion_condition(
    selector: ModuleType,
) -> None:
    doc = selector.__doc__ or ""
    assert "no release authority" in doc
    assert "20 eligible rows" in doc
    assert "NOT" in doc and "complete" in doc


def test_tracked_files_returns_none_when_git_cannot_answer(
    selector: ModuleType, tmp_path: Path
) -> None:
    """An empty measurement must degrade loudly, never read as 'nothing to do'."""
    outside = tmp_path / "not-a-repo"
    outside.mkdir()
    assert selector.tracked_files(outside, "*.py") is None


def test_a_diff_failure_forces_fail_broad(
    selector: ModuleType, tmp_path: Path
) -> None:
    repo, head = _make_repo(tmp_path)
    result = _select(
        selector, repo, _map(selector, repo, head), base="refs/heads/does-not-exist"
    )
    assert result.verdict == "fail-broad"
    assert {"change-deleted", "change-renamed"} <= set(result.reasons)


def test_node_digest_matches_the_gate_digest_shape(selector: ModuleType) -> None:
    """The ledger's hashes must be recomputable against the gate's own artifacts."""
    import hashlib

    values = ["tests/test_a.py::test_one", "tests/test_b.py::test_two"]
    expected = hashlib.sha256(
        json.dumps(tuple(values), ensure_ascii=True, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()
    assert selector.node_digest(values) == expected


def test_capture_map_refuses_a_dirty_tree(
    selector: ModuleType, tmp_path: Path
) -> None:
    """A map declaring a base it did not measure would pass every staleness rule."""
    repo, _ = _make_repo(tmp_path)
    (repo / "src" / "probos" / "alpha.py").write_text("DIRTY = 1\n", encoding="utf-8")
    destination, errors = selector.capture_map(
        repo_root=repo, targets=["tests"], output=tmp_path / "map.json"
    )
    assert destination is None
    assert any("dirty tree" in problem for problem in errors)
    assert not (tmp_path / "map.json").exists()


def test_capture_map_accepts_a_clean_tree_far_enough_to_run(
    selector: ModuleType, tmp_path: Path
) -> None:
    """The dirty-tree guard is a real gate, not a permanent refusal."""
    repo, _ = _make_repo(tmp_path)
    destination, errors = selector.capture_map(
        repo_root=repo, targets=["tests"], output=tmp_path / "map.json"
    )
    assert not any("dirty tree" in problem for problem in errors), errors
    if destination is None:
        # The synthetic repo has no probos package, so the instrumented run
        # itself may fail -- that is a different refusal, and it is the one
        # that proves the guard let the clean tree through.
        assert any("instrumented run exited" in problem for problem in errors), errors


def test_selected_nodes_are_sorted_and_deterministic(benign) -> None:
    _, _, result = benign
    assert list(result.nodes) == sorted(result.nodes)
    assert list(result.full_nodes) == sorted(result.full_nodes)


def test_known_uncontexted_tests_are_always_selected(benign) -> None:
    """The 25-test invisible class is included on every run, never dropped."""
    _, _, result = benign
    assert "tests/test_alpha.py::test_three" in result.nodes


def test_a_changed_test_file_selects_all_of_its_nodes(
    selector: ModuleType, tmp_path: Path
) -> None:
    repo, head = _make_repo(tmp_path)
    (repo / "tests" / "test_alpha.py").write_text(
        "def test_one():\n    pass\n\n\ndef test_two():\n    pass\n\n\n"
        "def test_three():\n    assert True\n",
        encoding="utf-8",
    )
    result = _select(selector, repo, _map(selector, repo, head))
    assert result.verdict == "selected"
    assert set(result.nodes) == set(FULL_NODES)


def test_a_report_round_trips_as_json(benign) -> None:
    _, _, result = benign
    report = result.to_report()
    assert json.loads(json.dumps(report)) == report
    assert report["verdict"] == "selected"
    assert report["selected"]["node_count"] == len(result.nodes)

# ---------------------------------------------------------------------------
# adversarial-review regressions (2026-09-02) -- ledger integrity
# ---------------------------------------------------------------------------


def _chained_ledger(selector: ModuleType, path: Path, rows: int = 2) -> None:
    header = {
        "kind": "enrollment",
        "cutoff_utc": "2026-01-01T00:00:00Z",
        "target": 20,
    }
    path.write_text(
        json.dumps(header, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
        + "\n",
        encoding="utf-8",
        newline="\n",
    )
    for index in range(1, rows + 1):
        selector._append_ledger(
            path,
            {
                "kind": "run",
                "tree_fingerprint": f"fingerprint-{index}",
                "changed_path_count": 1,
                "eligible": True,
                "recorded_at_utc": f"2026-09-02T0{index}:00:00Z",
            },
        )


def test_reordering_two_valid_rows_is_detected(
    selector: ModuleType, tmp_path: Path
) -> None:
    """Append-only must be a fact, not a convention.

    Review swapped two individually valid rows and the checker reported nothing,
    because every row validated fine in isolation. Each row now carries the
    SHA-256 of the line stored before it.
    """
    ledger = tmp_path / "ledger.jsonl"
    _chained_ledger(selector, ledger)
    assert selector.check_ledger(ledger) == []

    lines = [l for l in ledger.read_text(encoding="utf-8").splitlines() if l.strip()]
    ledger.write_text(
        "\n".join([lines[0], lines[2], lines[1]]) + "\n",
        encoding="utf-8",
        newline="\n",
    )

    problems = selector.check_ledger(ledger)
    assert any("reordered" in problem for problem in problems)


def test_rewriting_a_row_in_place_is_detected(
    selector: ModuleType, tmp_path: Path
) -> None:
    """A row edited after the fact breaks the chain for every row after it."""
    ledger = tmp_path / "ledger.jsonl"
    _chained_ledger(selector, ledger)
    lines = [l for l in ledger.read_text(encoding="utf-8").splitlines() if l.strip()]
    tampered = json.loads(lines[1])
    tampered["tree_fingerprint"] = "tampered-after-the-fact"
    lines[1] = json.dumps(
        tampered, ensure_ascii=True, sort_keys=True, separators=(",", ":")
    )
    ledger.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")

    problems = selector.check_ledger(ledger)
    assert any("reordered, rewritten, or removed" in problem for problem in problems)


def test_a_row_without_prev_sha256_is_reported_not_silently_accepted(
    selector: ModuleType, tmp_path: Path
) -> None:
    ledger = tmp_path / "ledger.jsonl"
    _chained_ledger(selector, ledger, rows=1)
    lines = [l for l in ledger.read_text(encoding="utf-8").splitlines() if l.strip()]
    row = json.loads(lines[1])
    row.pop("prev_sha256")
    lines[1] = json.dumps(row, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    ledger.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")

    problems = selector.check_ledger(ledger)
    assert any("predates the hash chain" in problem for problem in problems)


def test_the_live_ledger_is_chained_from_its_first_row(
    selector: ModuleType,
) -> None:
    """The shipped ledger must itself satisfy the chain it declares."""
    assert selector._chain_problems(LIVE_LEDGER) == []
