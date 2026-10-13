"""AD-1287 S1 (M1): the pure execution-profile contract -- identity, evaluation status, slot check.

Known-answer vectors: each digest literal below was computed ONCE, by a scratch run that imported only
``_independent_digest`` from the AD-1286 contract tests and never ``probos.cognitive.execution_profile``,
over a hand-sorted copy of the fixture (``_canonical_profile`` / ``_canonical_record``), then pasted here.

Exported for the later AD-1287 test files: ``_PROFILE``, ``_profile``, ``_record`` and ``_observations``. They
return plain dicts (or a list of dicts); validate with ``ExecutionProfile.model_validate`` or
``EvaluationRecord.model_validate``.
"""

from __future__ import annotations

import ast
import copy
import json
import os
import subprocess
import sys
import typing
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel, ValidationError

import probos.cognitive.execution_profile as execution_profile_module
from probos.cognitive.elastic_team import AuthorityCeiling, WorkerSlot
from probos.cognitive.execution_profile import (
    EvaluationRecord,
    ExecutionProfile,
    assess_evaluation,
    expires_at_ms,
    slot_refusal,
)
from tests.test_ad1286_elastic_team_contract import (
    _independent_digest,
    _independent_jcs,
    _is_under,
    _review_slot,
)

_SRC_ROOT = Path(__file__).resolve().parent.parent / "src"

_DOMAIN_PROFILE = b"probos.execution_profile/profile/v1\x00"
_DOMAIN_EVALUATION = b"probos.execution_profile/evaluation/v1\x00"
_KAT_PROFILE_REF = "5c20ea63c25208c899a8409e4609a869f62c6d88b216b2db95138d141d19762d"
_KAT_EVALUATION_REF = "4de2f600ce8fa06cdd4f7ebc6636258ab795117eeacf3886ec97da0ba2058486"

_ISSUED_MS = 1_000_000
_EXPIRY_MS = _ISSUED_MS + 86_400 * 1_000

_DROP = object()  # sentinel for _with_paths: delete the key at the path instead of setting it


# --------------------------------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------------------------------

_SUITE: dict[str, Any] = {
    "qualification_id": "finding_review",
    "suite_revision": 1,
    "dataset_digest": "d" * 64,
    "min_samples": 4,
    "min_pass_bp": 7500,
    "validity_seconds": 86400,
}
_PROFILE: dict[str, Any] = {
    "schema_version": 1,
    "role_id": "reviewer",
    "task_class": "finding_review",
    # declared deliberately unsorted: the module sorts skills by name
    "skills": [
        {"skill_name": "code-review", "resource_digest": "1" * 64},
        {"skill_name": "audit-trail", "resource_digest": "2" * 64},
    ],
    "model": {"provider": "anthropic", "name": "claude-sonnet-5.5", "version": "2026-09-01"},
    "prompts": [{"prompt_id": "review.system", "revision_digest": "3" * 64}],
    "tools": [{"tool_id": "codebase_query", "schema_digest": "4" * 64, "implementation_digest": "5" * 64}],
    "policy": {"policy_digest": "6" * 64},
    "evaluation_suite": _SUITE,
}


def _with_paths(data: dict[str, Any], paths: dict[str, Any]) -> dict[str, Any]:
    """``data`` with each dotted path set to a copy of its value (digit segments index lists; ``_DROP`` deletes)."""
    for path, value in paths.items():
        *parents, leaf = path.split(".")
        node: Any = data
        for part in parents:
            node = node[int(part)] if part.isdigit() else node[part]
        key: Any = int(leaf) if leaf.isdigit() else leaf
        if value is _DROP:
            del node[key]
        else:
            node[key] = copy.deepcopy(value)
    return data


def _profile(**path_overrides: Any) -> dict[str, Any]:
    """A deep copy of ``_PROFILE`` with each dotted path set: ``_profile(**{"model.name": "x", "role_id": "y"})``."""
    return _with_paths(copy.deepcopy(_PROFILE), path_overrides)


def _observations(passes: int, total: int) -> list[dict[str, Any]]:
    """``total`` cases ``c001``.. in order, the first ``passes`` passing (score 9000, else 1000)."""
    return [
        {
            "case_id": f"c{number:03d}",
            "passed": number <= passes,
            "score_bp": 9000 if number <= passes else 1000,
            "cost_micro_usd": 120,
            "latency_ms": 800,
        }
        for number in range(1, total + 1)
    ]


def _record(
    profile_ref: str,
    evaluation_id: str = "eval-1",
    passes: int = 4,
    total: int = 4,
    structurally_valid: bool = True,
    evaluator_id: str = "qual-harness",
) -> dict[str, Any]:
    """An ``EvaluationRecord`` input dict (not yet validated, so a caller can reorder or patch it first)."""
    return {
        "schema_version": 1,
        "profile_ref": profile_ref,
        "evaluation_id": evaluation_id,
        "evaluator_id": evaluator_id,
        "structurally_valid": structurally_valid,
        "observations": _observations(passes, total),
    }


def _canonical_profile() -> dict[str, Any]:
    """``_PROFILE`` written out by hand, with ``skills``, ``prompts`` and ``tools`` already sorted by their key."""
    return {
        "schema_version": 1,
        "role_id": "reviewer",
        "task_class": "finding_review",
        "skills": [
            {"skill_name": "audit-trail", "resource_digest": "2" * 64},
            {"skill_name": "code-review", "resource_digest": "1" * 64},
        ],
        "model": {"provider": "anthropic", "name": "claude-sonnet-5.5", "version": "2026-09-01"},
        "prompts": [{"prompt_id": "review.system", "revision_digest": "3" * 64}],
        "tools": [{"tool_id": "codebase_query", "schema_digest": "4" * 64, "implementation_digest": "5" * 64}],
        "policy": {"policy_digest": "6" * 64},
        "evaluation_suite": {
            "qualification_id": "finding_review",
            "suite_revision": 1,
            "dataset_digest": "d" * 64,
            "min_samples": 4,
            "min_pass_bp": 7500,
            "validity_seconds": 86400,
        },
    }


def _canonical_record() -> dict[str, Any]:
    """``_record(_KAT_PROFILE_REF)`` written out by hand, with the observations sorted by ``case_id``."""
    return {
        "schema_version": 1,
        "profile_ref": _KAT_PROFILE_REF,
        "evaluation_id": "eval-1",
        "evaluator_id": "qual-harness",
        "structurally_valid": True,
        "observations": [
            {"case_id": "c001", "passed": True, "score_bp": 9000, "cost_micro_usd": 120, "latency_ms": 800},
            {"case_id": "c002", "passed": True, "score_bp": 9000, "cost_micro_usd": 120, "latency_ms": 800},
            {"case_id": "c003", "passed": True, "score_bp": 9000, "cost_micro_usd": 120, "latency_ms": 800},
            {"case_id": "c004", "passed": True, "score_bp": 9000, "cost_micro_usd": 120, "latency_ms": 800},
        ],
    }


def _status(
    *,
    passes: int = 4,
    total: int = 4,
    structurally_valid: bool = True,
    invalidated: bool = False,
    now_ms: int = _ISSUED_MS + 1,
) -> str:
    """``assess_evaluation`` of the fixture profile and one fresh record, issued at ``_ISSUED_MS``."""
    profile = ExecutionProfile.model_validate(_PROFILE)
    record = EvaluationRecord.model_validate(
        _record(profile.content_ref(), passes=passes, total=total, structurally_valid=structurally_valid)
    )
    return assess_evaluation(profile, record, issued_at_ms=_ISSUED_MS, invalidated=invalidated, now_ms=now_ms)


# --------------------------------------------------------------------------------------
# 1-4. Identity: known answers, a fresh interpreter, declaration order
# --------------------------------------------------------------------------------------


def test_profile_reference_matches_independent_known_answer() -> None:
    assert [skill["skill_name"] for skill in _PROFILE["skills"]] == ["code-review", "audit-trail"]  # unsorted

    profile = ExecutionProfile.model_validate(_PROFILE)

    assert profile.content_ref() == _KAT_PROFILE_REF
    assert profile.canonical_bytes() == _independent_jcs(_canonical_profile())
    # the literal is the independent digest, so it cannot be edited to follow the module
    assert _independent_digest(_DOMAIN_PROFILE, _canonical_profile()) == _KAT_PROFILE_REF


def test_evaluation_reference_matches_independent_known_answer() -> None:
    declared = _record(_KAT_PROFILE_REF)
    declared["observations"].reverse()  # declared in REVERSE case order; the module sorts them
    assert [case["case_id"] for case in declared["observations"]] == ["c004", "c003", "c002", "c001"]

    record = EvaluationRecord.model_validate(declared)

    assert record.content_ref() == _KAT_EVALUATION_REF
    assert record.canonical_bytes() == _independent_jcs(_canonical_record())
    assert _independent_digest(_DOMAIN_EVALUATION, _canonical_record()) == _KAT_EVALUATION_REF


_FRESH_INTERPRETER_SCRIPT = (
    "import json, sys\n"
    "from probos.cognitive.execution_profile import ExecutionProfile\n"
    "profile = ExecutionProfile.model_validate(json.loads(sys.argv[1]))\n"
    "print(profile.content_ref())\n"
)


def test_reference_is_stable_in_a_fresh_interpreter() -> None:
    completed = subprocess.run(
        [sys.executable, "-c", _FRESH_INTERPRETER_SCRIPT, json.dumps(_PROFILE)],
        env={**os.environ, "PYTHONPATH": str(_SRC_ROOT), "PYTHONHASHSEED": "12345"},
        check=True,
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert completed.stdout.strip() == _KAT_PROFILE_REF


_EXTRA_PROMPT = {"prompt_id": "audit.system", "revision_digest": "7" * 64}
_EXTRA_TOOL = {"tool_id": "audit_query", "schema_digest": "8" * 64, "implementation_digest": "9" * 64}


def test_component_order_does_not_change_the_reference() -> None:
    # (a) the fixture with skills, prompts and tools reversed keeps the known answer
    reversed_fixture = _profile(**{key: list(reversed(_PROFILE[key])) for key in ("skills", "prompts", "tools")})
    assert ExecutionProfile.model_validate(reversed_fixture).content_ref() == _KAT_PROFILE_REF

    # (b) the fixture holds one prompt and one tool, so (a) moves neither: repeat with two of each, out of order
    declared = _profile(prompts=[*_PROFILE["prompts"], _EXTRA_PROMPT], tools=[*_PROFILE["tools"], _EXTRA_TOOL])
    assert [prompt["prompt_id"] for prompt in declared["prompts"]] == ["review.system", "audit.system"]
    assert [tool["tool_id"] for tool in declared["tools"]] == ["codebase_query", "audit_query"]
    flipped = _profile(**{key: list(reversed(declared[key])) for key in ("skills", "prompts", "tools")})
    wide = ExecutionProfile.model_validate(declared)
    assert ExecutionProfile.model_validate(flipped).content_ref() == wide.content_ref()
    assert wide.content_ref() != _KAT_PROFILE_REF
    assert [skill.skill_name for skill in wide.skills] == ["audit-trail", "code-review"]
    assert [prompt.prompt_id for prompt in wide.prompts] == ["audit.system", "review.system"]
    assert [tool.tool_id for tool in wide.tools] == ["audit_query", "codebase_query"]

    # (c) the record, observations declared in reverse case order
    reversed_record = _record(_KAT_PROFILE_REF)
    reversed_record["observations"].reverse()
    record = EvaluationRecord.model_validate(reversed_record)
    assert record.content_ref() == _KAT_EVALUATION_REF
    assert [case.case_id for case in record.observations] == ["c001", "c002", "c003", "c004"]


# --------------------------------------------------------------------------------------
# 5. Every component is part of the identity
# --------------------------------------------------------------------------------------

_COMPONENT_CHANGES: dict[str, dict[str, Any]] = {
    "role_id": {"role_id": "auditor"},
    "task_class": {"task_class": "evidence_analysis"},
    "skills.0.resource_digest": {"skills.0.resource_digest": "a" * 64},
    "skill added": {"skills": [*_PROFILE["skills"], {"skill_name": "triage", "resource_digest": "7" * 64}]},
    "skill removed": {"skills": _PROFILE["skills"][:1]},
    "model.provider": {"model.provider": "openai"},
    "model.name": {"model.name": "gpt-5"},
    "model.version": {"model.version": "2026-10-01"},
    "prompts.0.revision_digest": {"prompts.0.revision_digest": "a" * 64},
    "tools.0.schema_digest": {"tools.0.schema_digest": "a" * 64},
    "tools.0.implementation_digest": {"tools.0.implementation_digest": "a" * 64},
    "policy.policy_digest": {"policy.policy_digest": "a" * 64},
    "evaluation_suite.qualification_id": {"evaluation_suite.qualification_id": "evidence_analysis"},
    "evaluation_suite.suite_revision": {"evaluation_suite.suite_revision": 2},
    "evaluation_suite.dataset_digest": {"evaluation_suite.dataset_digest": "a" * 64},
    "evaluation_suite.min_samples": {"evaluation_suite.min_samples": 5},
    "evaluation_suite.min_pass_bp": {"evaluation_suite.min_pass_bp": 8000},
    "evaluation_suite.validity_seconds": {"evaluation_suite.validity_seconds": 3600},
    "prompt added": {"prompts": [*_PROFILE["prompts"], {"prompt_id": "review.followup", "revision_digest": "8" * 64}]},
}


@pytest.mark.parametrize("change", list(_COMPONENT_CHANGES))
def test_each_component_change_gives_a_new_reference(change: str) -> None:
    refs = {
        name: ExecutionProfile.model_validate(_profile(**paths)).content_ref()
        for name, paths in _COMPONENT_CHANGES.items()
    }

    assert len(refs) == 19
    assert refs[change] != _KAT_PROFILE_REF
    # companion assertion: no other change lands on this reference, so the 19 are pairwise distinct across the run
    assert sum(1 for ref in refs.values() if ref == refs[change]) == 1


# --------------------------------------------------------------------------------------
# 6-7. Malformed input is refused (each case changes one thing and names why it is refused)
# --------------------------------------------------------------------------------------

_MALFORMED_PROFILES: dict[str, tuple[dict[str, Any], str]] = {
    "schema_version 2": ({"schema_version": 2}, "execution_profile_schema_version_invalid"),
    "schema_version True": ({"schema_version": True}, "execution_profile_schema_version_invalid"),
    "role_id with a space": ({"role_id": "bad id"}, "elastic_team_id_invalid"),
    "duplicate skill name": (
        {"skills": [_PROFILE["skills"][0], {"skill_name": "code-review", "resource_digest": "9" * 64}]},
        "execution_profile_skills_invalid",
    ),
    "33 skills": (
        {"skills": [{"skill_name": f"skill-{number:02d}", "resource_digest": "1" * 64} for number in range(33)]},
        "execution_profile_skills_invalid",
    ),
    "skills is a string": ({"skills": "x"}, "execution_profile_skills_invalid"),
    "uppercase resource digest": ({"skills.0.resource_digest": "A" * 64}, "elastic_team_ref_invalid"),
    "model name with a space": ({"model.name": "has space"}, "execution_profile_model_invalid"),
    "model name of 129 characters": ({"model.name": "a" * 129}, "execution_profile_model_invalid"),
    "prompt without revision_digest": ({"prompts.0.revision_digest": _DROP}, "Field required"),
    "duplicate tool id": (
        {"tools": [_PROFILE["tools"][0], {**_PROFILE["tools"][0], "schema_digest": "9" * 64}]},
        "execution_profile_tools_invalid",
    ),
    "extra top-level key": ({"unexpected": "x"}, "Extra inputs are not permitted"),
    "min_samples 0": ({"evaluation_suite.min_samples": 0}, "execution_profile_suite_invalid"),
    "min_samples 1025": ({"evaluation_suite.min_samples": 1025}, "execution_profile_suite_invalid"),
    "min_samples True": ({"evaluation_suite.min_samples": True}, "execution_profile_suite_invalid"),
    "min_pass_bp 0": ({"evaluation_suite.min_pass_bp": 0}, "execution_profile_suite_invalid"),
    "min_pass_bp 10001": ({"evaluation_suite.min_pass_bp": 10001}, "execution_profile_suite_invalid"),
    "validity_seconds 0": ({"evaluation_suite.validity_seconds": 0}, "execution_profile_suite_invalid"),
    "validity_seconds 31622401": (
        {"evaluation_suite.validity_seconds": 31_622_401},
        "execution_profile_suite_invalid",
    ),
    "suite_revision 0": ({"evaluation_suite.suite_revision": 0}, "elastic_team_revision_invalid"),
}


@pytest.mark.parametrize(("paths", "message"), list(_MALFORMED_PROFILES.values()), ids=list(_MALFORMED_PROFILES))
def test_profile_refuses_malformed_input(paths: dict[str, Any], message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        ExecutionProfile.model_validate(_profile(**paths))


_MALFORMED_RECORDS: dict[str, tuple[dict[str, Any], str]] = {
    "no observations": ({"observations": []}, "profile_evaluation_invalid"),
    "1025 observations": ({"observations": _observations(1025, 1025)}, "profile_evaluation_invalid"),
    "duplicate case_id": ({"observations.1.case_id": "c001"}, "profile_evaluation_invalid"),
    "passed 1": ({"observations.0.passed": 1}, "Input should be a valid boolean"),
    "score_bp 10001": ({"observations.0.score_bp": 10001}, "profile_evaluation_invalid"),
    "score_bp 50.5": ({"observations.0.score_bp": 50.5}, "profile_evaluation_invalid"),
    "cost_micro_usd -1": ({"observations.0.cost_micro_usd": -1}, "profile_evaluation_invalid"),
    "latency_ms 2**53": ({"observations.0.latency_ms": 2**53}, "profile_evaluation_invalid"),
    "structurally_valid 'yes'": ({"structurally_valid": "yes"}, "Input should be a valid boolean"),
    "profile_ref 'x'": ({"profile_ref": "x"}, "elastic_team_ref_invalid"),
    "extra key": ({"unexpected": "x"}, "Extra inputs are not permitted"),
}


@pytest.mark.parametrize(("paths", "message"), list(_MALFORMED_RECORDS.values()), ids=list(_MALFORMED_RECORDS))
def test_evaluation_record_refuses_malformed_input(paths: dict[str, Any], message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        EvaluationRecord.model_validate(_with_paths(_record(_KAT_PROFILE_REF), paths))


# --------------------------------------------------------------------------------------
# 8-10. assess_evaluation
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("passes", "total", "structurally_valid", "now_ms", "expected"),
    [
        pytest.param(4, 4, True, _ISSUED_MS + 1, "qualified", id="all_cases_pass"),
        # 3 * 10000 == 7500 * 4: a rate exactly at the threshold qualifies
        pytest.param(3, 4, True, _ISSUED_MS + 1, "qualified", id="rate_at_threshold_qualifies"),
        pytest.param(2, 4, True, _ISSUED_MS + 1, "failed", id="rate_below_threshold_fails"),
        pytest.param(4, 5, True, _ISSUED_MS + 1, "qualified", id="four_of_five_qualifies"),
        pytest.param(3, 5, True, _ISSUED_MS + 1, "failed", id="three_of_five_fails"),
        pytest.param(3, 3, True, _ISSUED_MS + 1, "insufficient_sample", id="fewer_than_min_samples"),
        pytest.param(4, 4, False, _ISSUED_MS + 1, "structurally_invalid", id="structurally_invalid_record"),
        pytest.param(4, 4, True, _EXPIRY_MS - 1, "qualified", id="one_ms_before_expiry"),
        pytest.param(4, 4, True, _EXPIRY_MS, "expired", id="at_expiry"),
    ],
)
def test_assess_evaluation_status_boundaries(
    passes: int, total: int, structurally_valid: bool, now_ms: int, expected: str
) -> None:
    assert _status(passes=passes, total=total, structurally_valid=structurally_valid, now_ms=now_ms) == expected


def test_assess_evaluation_precedence() -> None:
    # invalidated + expired + structurally invalid + insufficient -> invalidated
    everything_wrong = _status(passes=3, total=3, structurally_valid=False, invalidated=True, now_ms=_EXPIRY_MS + 1)
    assert everything_wrong == "invalidated"
    # expired + structurally invalid -> expired
    assert _status(structurally_valid=False, now_ms=_EXPIRY_MS) == "expired"
    # structurally invalid + insufficient + failed -> structurally_invalid
    assert _status(passes=1, total=3, structurally_valid=False) == "structurally_invalid"
    # insufficient + failed -> insufficient_sample
    assert _status(passes=1, total=3) == "insufficient_sample"


def test_assess_evaluation_refuses_wrong_types_and_foreign_records() -> None:
    profile = ExecutionProfile.model_validate(_PROFILE)
    other = ExecutionProfile.model_validate(_profile(role_id="auditor"))
    record_input = _record(profile.content_ref())
    record = EvaluationRecord.model_validate(record_input)
    foreign = EvaluationRecord.model_validate(_record(other.content_ref()))
    good: dict[str, Any] = {"issued_at_ms": _ISSUED_MS, "invalidated": False, "now_ms": _ISSUED_MS + 1}

    with pytest.raises(ValueError) as mismatch:
        assess_evaluation(profile, foreign, **good)
    assert mismatch.value.args == ("profile_evaluation_profile_mismatch",)

    wrong_types: list[tuple[Any, Any, dict[str, Any]]] = [
        (profile, record, {"now_ms": True}),
        (profile, record, {"issued_at_ms": 1.0}),
        (profile, record, {"invalidated": 0}),
        (_PROFILE, record, {}),
        (profile, record_input, {}),
    ]
    for wrong_profile, wrong_record, wrong in wrong_types:
        with pytest.raises(TypeError) as refused:
            assess_evaluation(wrong_profile, wrong_record, **{**good, **wrong})
        assert refused.value.args == ("profile_evaluation_type_invalid",)


# --------------------------------------------------------------------------------------
# 11-12. slot_refusal
# --------------------------------------------------------------------------------------


# What the slot pins: nothing, some other profile, or this very profile (resolved from the profile in the test).
_PINS: dict[str, Callable[[str], list[str]]] = {
    "none": lambda ref: [],
    "elsewhere": lambda ref: ["e" * 64],
    "this": lambda ref: [ref],
}

# (id, slot role_id, slot task_class, slot qualification_ids, slot pins, expected refusal code)
_SLOT_CASES: list[tuple[str, str, str, list[str], str, str | None]] = [
    ("matching", "reviewer", "finding_review", ["finding_review"], "none", None),
    ("no_ids_and_no_pins_declared", "reviewer", "finding_review", [], "none", None),
    ("role", "auditor", "finding_review", ["finding_review"], "none", "profile_role_mismatch"),
    ("task_class", "reviewer", "evidence_analysis", ["finding_review"], "none", "profile_task_class_mismatch"),
    ("qualification_id", "reviewer", "finding_review", ["other"], "none", "profile_qualification_id_mismatch"),
    ("pinned_elsewhere", "reviewer", "finding_review", ["finding_review"], "elsewhere", "profile_not_pinned"),
    ("pinned_to_this_profile", "reviewer", "finding_review", ["finding_review"], "this", None),
    # the first unmet constraint is the one reported: every later constraint is also violated in these three
    ("role_first", "auditor", "evidence_analysis", ["other"], "elsewhere", "profile_role_mismatch"),
    ("task_class_second", "reviewer", "evidence_analysis", ["other"], "elsewhere", "profile_task_class_mismatch"),
    ("qual_id_third", "reviewer", "finding_review", ["other"], "elsewhere", "profile_qualification_id_mismatch"),
]


@pytest.mark.parametrize(
    ("role_id", "task_class", "qualification_ids", "pins", "expected"),
    [case[1:] for case in _SLOT_CASES],
    ids=[case[0] for case in _SLOT_CASES],
)
def test_slot_refusal_codes(
    role_id: str, task_class: str, qualification_ids: list[str], pins: str, expected: str | None
) -> None:
    profile = ExecutionProfile.model_validate(_PROFILE)
    slot = WorkerSlot.model_validate(
        _review_slot(
            role_id=role_id,
            task_class=task_class,
            qualification={
                "qualification_ids": qualification_ids,
                "pinned_profile_refs": _PINS[pins](profile.content_ref()),
            },
        )
    )

    assert slot_refusal(slot, profile) == expected


def test_slot_refusal_refuses_wrong_types() -> None:
    profile = ExecutionProfile.model_validate(_PROFILE)
    slot = WorkerSlot.model_validate(_review_slot())

    for wrong_slot, wrong_profile in ((_review_slot(), profile), (slot, _PROFILE)):
        with pytest.raises(TypeError) as refused:
            slot_refusal(wrong_slot, wrong_profile)
        assert refused.value.args == ("profile_slot_type_invalid",)


# --------------------------------------------------------------------------------------
# 13-14. Authority and import boundaries
# --------------------------------------------------------------------------------------

_AUTHORITY_WORDS = ("scope", "rank", "lease", "grant", "authority", "permission")
_ALLOWED_PROBOS_IMPORTS = {"probos.cognitive.elastic_team"}


def _nested_models(annotation: Any) -> list[type[BaseModel]]:
    """Every pydantic model named anywhere in ``annotation``, through generics such as ``tuple[X, ...]``."""
    if typing.get_origin(annotation) is None and isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return [annotation]
    return [nested for argument in typing.get_args(annotation) for nested in _nested_models(argument)]


def _all_field_names(model: type[BaseModel]) -> set[str]:
    """Every field name of ``model`` and of each model reachable from it."""
    names: set[str] = set()
    seen: set[type[BaseModel]] = set()
    pending = [model]
    while pending:
        current = pending.pop()
        if current in seen:
            continue
        seen.add(current)
        for name, field in current.model_fields.items():
            names.add(name)
            pending.extend(_nested_models(field.annotation))
    return names


def _authority_named(names: set[str]) -> set[str]:
    return {name for name in names if any(word in name for word in _AUTHORITY_WORDS)}


def test_profile_types_carry_no_authority_fields() -> None:
    profile_fields = _all_field_names(ExecutionProfile)
    record_fields = _all_field_names(EvaluationRecord)

    # the walk reaches models nested inside tuples (a walk that stopped at the top level would pass vacuously)
    assert {"provider", "resource_digest", "implementation_digest", "min_pass_bp"} <= profile_fields
    assert {"case_id", "latency_ms"} <= record_fields
    assert _authority_named(profile_fields) == set()
    assert _authority_named(record_fields) == set()
    # negative control: the same walker flags AD-1286's AuthorityCeiling
    assert "tool_scopes" in _authority_named(_all_field_names(AuthorityCeiling))


def _probos_imports(tree: ast.AST) -> set[str]:
    """Every ProbOS module an import node anywhere in ``tree`` (any depth) names; a relative import keeps its dots."""
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names if _is_under(alias.name, "probos"))
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                modules.add("." * node.level + (node.module or ""))
            elif node.module and _is_under(node.module, "probos"):
                modules.add(node.module)
    return modules


def test_module_imports_only_elastic_team() -> None:
    source = Path(execution_profile_module.__file__).read_text(encoding="utf-8")

    assert _probos_imports(ast.parse(source)) == _ALLOWED_PROBOS_IMPORTS
    # negative controls: the helper sees an import outside the allowlist whatever its form or depth
    assert _probos_imports(ast.parse("import probos.tools.registry")) == {"probos.tools.registry"}
    assert _probos_imports(ast.parse("from probos.tools import registry")) == {"probos.tools"}
    assert _probos_imports(ast.parse("def late():\n    import probos.tools.registry\n")) == {"probos.tools.registry"}
    assert _probos_imports(ast.parse("from . import registry")) == {"."}


# --------------------------------------------------------------------------------------
# 15. expires_at_ms
# --------------------------------------------------------------------------------------


def test_expires_at_ms_adds_validity() -> None:
    profile = ExecutionProfile.model_validate(_PROFILE)

    assert expires_at_ms(profile, 1_000_000) == 1_000_000 + 86_400_000
