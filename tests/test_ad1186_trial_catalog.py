"""AD-1186 (#1123) slice 1: the Ship Trials catalog's predeclared, report-only policy, and the
Captain's trial rules (2026-10-20) as schema.

The shipped catalog holds no task yet; the crew tasks here are fixtures written to ``tmp_path``.
This file starts no runtime and calls no model.
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any, Callable

import pytest
import yaml

from tests.ablation import sigma_stats
from tests.ablation.sigma_goals import sha256_file
from tests.trials import catalog as trials

_CREW_TASK: dict[str, Any] = {
    "id": "grounded_refusal.fixture",
    "category": "grounded_refusal",
    "instrument": "behavior_contract",
    "ref": "config/contracts/sample_refusal.yaml",
    "subject": "crew",
    "disclosure": {"what": "A Ship Trial of grounded refusal.", "ends": "After the last case."},
    "episodes": "trial_labelled",
    "trust": "not_applied",
}

Mutation = Callable[[dict[str, Any]], None]


def _shipped() -> dict[str, Any]:
    return yaml.safe_load(trials.CATALOG_V1_PATH.read_bytes())


def _load_mutated(tmp_path: Path, mutate: Mutation) -> trials.TrialCatalog:
    document = _shipped()
    mutate(document)
    path = tmp_path / "catalog_v1.yaml"
    path.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
    return trials.load_catalog(path)


def _with_task(**changes: Any) -> Mutation:
    """Put one crew task, with ``changes`` applied (``None`` removes a key), in the entries."""
    task = copy.deepcopy(_CREW_TASK)
    for key, value in changes.items():
        if value is None:
            task.pop(key, None)
        else:
            task[key] = value

    def mutate(document: dict[str, Any]) -> None:
        document["entries"] = [task]

    return mutate


def _set_policy(key: str, value: Any) -> Mutation:
    def mutate(document: dict[str, Any]) -> None:
        document["policy"][key] = value

    return mutate


def test_the_shipped_catalog_is_report_only_and_content_hashed() -> None:
    catalog = trials.load_catalog()
    assert catalog.version == 1
    assert catalog.policy.mode == "report_only"
    # The same bytes AD-1143's goal-set guard hashes.
    assert catalog.sha256 == sha256_file(trials.CATALOG_V1_PATH)
    # Slice 1 declares the policy before any task exists; tasks join in later slices of #1123.
    assert catalog.entries == ()


def test_a_blocking_mode_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="policy.mode"):
        _load_mutated(tmp_path, _set_policy("mode", "blocking"))


def test_an_unknown_policy_key_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="unknown keys"):
        _load_mutated(tmp_path, _set_policy("blocks_main", True))


def test_unknown_keys_of_mixed_types_are_refused(tmp_path: Path) -> None:
    """YAML admits a non-string key; listing unknown keys of mixed types is still a ``ValueError``."""

    def mutate(document: dict[str, Any]) -> None:
        document["policy"][7] = "x"
        document["policy"]["blocks_main"] = True

    with pytest.raises(ValueError, match="unknown keys"):
        _load_mutated(tmp_path, mutate)


def test_missing_human_effort_is_unknown_never_zero(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="missing_human_effort"):
        _load_mutated(tmp_path, _set_policy("missing_human_effort", "zero"))


@pytest.mark.parametrize(
    "alpha",
    [0.0, 1.0, 1.5, "0.05", True],
    ids=["zero", "one", "above-one", "string", "bool"],
)
def test_an_out_of_range_alpha_is_refused(tmp_path: Path, alpha: Any) -> None:
    with pytest.raises(ValueError, match="policy.alpha"):
        _load_mutated(tmp_path, _set_policy("alpha", alpha))


@pytest.mark.parametrize("status", sorted(trials.REQUIRED_NON_PASSING))
def test_the_non_passing_statuses_cannot_drop_one(tmp_path: Path, status: str) -> None:
    def mutate(document: dict[str, Any]) -> None:
        document["policy"]["non_passing"].remove(status)

    with pytest.raises(ValueError, match="non_passing"):
        _load_mutated(tmp_path, mutate)


@pytest.mark.parametrize("name", sorted(trials.REQUIRED_FINGERPRINT))
def test_the_fingerprint_cannot_drop_a_field(tmp_path: Path, name: str) -> None:
    def mutate(document: dict[str, Any]) -> None:
        document["policy"]["fingerprint"].remove(name)

    with pytest.raises(ValueError, match="fingerprint"):
        _load_mutated(tmp_path, mutate)


def test_the_crew_rules_must_be_stated_exactly(tmp_path: Path) -> None:
    def mutate(document: dict[str, Any]) -> None:
        document["crew_rules"]["awareness"] = "penalised"

    with pytest.raises(ValueError, match="crew_rules"):
        _load_mutated(tmp_path, mutate)


def test_a_crew_task_with_the_trial_terms_loads(tmp_path: Path) -> None:
    """The positive control for the refusals below."""
    (task,) = _load_mutated(tmp_path, _with_task()).entries
    assert task.subject == "crew"
    assert task.disclosure_what == "A Ship Trial of grounded refusal."
    assert task.disclosure_ends == "After the last case."
    assert task.episodes == "trial_labelled"
    assert task.trust == "not_applied"


@pytest.mark.parametrize(
    "disclosure",
    [None, {"what": "A Ship Trial."}, {"what": " ", "ends": "After the last case."}],
    ids=["missing", "no-end", "blank-what"],
)
def test_a_crew_task_without_a_full_disclosure_is_refused(tmp_path: Path, disclosure: Any) -> None:
    with pytest.raises(ValueError, match="rule 1"):
        _load_mutated(tmp_path, _with_task(disclosure=disclosure))


@pytest.mark.parametrize("episodes", [None, "suppressed", "erased"], ids=["missing", "suppressed", "erased"])
def test_a_crew_task_whose_episodes_are_not_trial_labelled_is_refused(tmp_path: Path, episodes: Any) -> None:
    with pytest.raises(ValueError, match="rule 3"):
        _load_mutated(tmp_path, _with_task(episodes=episodes))


@pytest.mark.parametrize("trust", [None, "applied"], ids=["missing", "applied"])
def test_a_crew_task_whose_trust_is_neither_separate_nor_withheld_is_refused(tmp_path: Path, trust: Any) -> None:
    with pytest.raises(ValueError, match="rule 3"):
        _load_mutated(tmp_path, _with_task(trust=trust))


def test_a_scripted_task_needs_no_disclosure(tmp_path: Path) -> None:
    mutate = _with_task(
        subject="scripted",
        instrument="sigma_ablation",
        ref="tests/ablation/data/sigma_goals_v1.json",
        category="cross_department_synthesis",
        disclosure=None,
        episodes=None,
        trust=None,
    )
    (task,) = _load_mutated(tmp_path, mutate).entries
    assert task.subject == "scripted"
    assert task.disclosure_what == ""


@pytest.mark.parametrize("key", ["category", "instrument", "subject"])
def test_an_unknown_category_instrument_or_subject_is_refused(tmp_path: Path, key: str) -> None:
    with pytest.raises(ValueError, match=f"unknown {key}"):
        _load_mutated(tmp_path, _with_task(**{key: "unknown"}))


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("category", ["grounded_refusal"]),
        ("instrument", {"behavior_contract": True}),
        ("subject", ["crew"]),
        ("trust", ["not_applied"]),
    ],
    ids=["category-list", "instrument-mapping", "subject-list", "trust-list"],
)
def test_a_list_or_mapping_where_one_name_belongs_is_refused_naming_the_task(
    tmp_path: Path, key: str, value: Any
) -> None:
    """A YAML slip such as ``category: [grounded_refusal]`` is a ``ValueError`` that names the task,
    not a ``TypeError`` from hashing the list."""
    with pytest.raises(ValueError, match=rf"entry grounded_refusal\.fixture: .*{key}"):
        _load_mutated(tmp_path, _with_task(**{key: value}))


@pytest.mark.parametrize(
    "entry_id",
    ["trial-1\n", "Bad Id", "UPPER", "", "-lead"],
    ids=["trailing-newline", "space-and-capitals", "upper-case", "empty", "leading-hyphen"],
)
def test_an_id_that_is_not_a_lower_case_slug_is_refused(entry_id: str) -> None:
    """The whole id must be a slug: ``re.match`` would let ``$`` match before a final newline."""
    with pytest.raises(ValueError, match="lower-case slug"):
        trials.validate_entry(dict(_CREW_TASK, id=entry_id), source="fixture.yaml")


def test_duplicate_task_ids_are_refused(tmp_path: Path) -> None:
    def mutate(document: dict[str, Any]) -> None:
        document["entries"] = [copy.deepcopy(_CREW_TASK), copy.deepcopy(_CREW_TASK)]

    with pytest.raises(ValueError, match="duplicate entry ids"):
        _load_mutated(tmp_path, mutate)


def test_the_policy_drives_the_ablation_bootstrap() -> None:
    """The policy names parameters AD-1143's statistics accept, and its seed makes the interval reproducible."""
    policy = trials.load_catalog().policy
    pairs = [(0.6, 0.5), (0.7, 0.4), (0.5, 0.6), (0.8, 0.5), (0.4, 0.45), (0.6, 0.62)]
    first = sigma_stats.bootstrap_ci(pairs, iterations=policy.iterations, seed=policy.seed, alpha=policy.alpha)
    again = sigma_stats.bootstrap_ci(pairs, iterations=policy.iterations, seed=policy.seed, alpha=policy.alpha)
    assert first == again
    assert first[0] <= first[1]
