"""AD-1286 (#1333): Elastic Team Contract -- frozen contracts and canonical identity (Section 1).

Covers ``probos.cognitive.elastic_team``: malformed-value refusal, order-independent
identity, a lossless canonical round trip, material change -> new identity, runtime
state excluded from identity, a derived attempt id, the CrewSession binding value,
known-answer vectors produced by an encoder that shares no code with the module
under test, cross-process stability and the import-layering guarantees.

Fixture names are deliberately neutral: the contract carries no domain wording.
"""

from __future__ import annotations

import ast
import copy
import hashlib
import importlib.util
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from probos.cognitive.elastic_team import (
    CREW_ELASTIC_TEAM_METADATA_KEY,
    ELASTIC_TEAM_SCHEMA_VERSION,
    AuthorityCeiling,
    BillRef,
    CapacityRange,
    CrewElasticTeamBinding,
    ElasticTeamSpec,
    IndependencePolicy,
    MergeRule,
    ProcessBinding,
    QualificationRequirement,
    SlotBudget,
    WorkerAttempt,
    WorkerAttemptOutcome,
    WorkerSlot,
    canonicalize_projection,
    content_digest,
    derive_worker_attempt_id,
    is_sha256_ref,
)

_PROFILE_A = "a" * 64
_KAT_SPEC: dict[str, Any] = {
    "schema_version": 1,
    "team_id": "review-team",
    "revision": 1,
    "process": {"bill": {"bill_id": "incident-review", "bill_version": 3}, "plan_hash": None},
    "slots": [
        {
            "slot_id": "analyse",
            "role_id": "analyst",
            "task_class": "evidence_analysis",
            "capacity": {"minimum": 1, "maximum": 3},
            "qualification": {"qualification_ids": ["evidence_analysis"], "pinned_profile_refs": [_PROFILE_A]},
            "independence": {"mode": "distinct_profiles", "min_distinct": 2},
            "merge": {"kind": "adjudicator", "quorum": None, "reducer_id": None, "adjudicator_slot_id": "review"},
            "budget": {"max_tokens": 200000, "max_wall_ms": 900000, "max_attempts": 6},
            "authority": {"tool_scopes": ["records.read"], "data_scopes": ["incident.records"]},
        },
        {
            "slot_id": "review",
            "role_id": "reviewer",
            "task_class": "finding_review",
            "capacity": {"minimum": 1, "maximum": 1},
            "qualification": {"qualification_ids": ["finding_review"], "pinned_profile_refs": []},
            "independence": {"mode": "none", "min_distinct": 1},
            "merge": {"kind": "single", "quorum": None, "reducer_id": None, "adjudicator_slot_id": None},
            "budget": {"max_tokens": 100000, "max_wall_ms": 600000, "max_attempts": 2},
            "authority": {"tool_scopes": [], "data_scopes": ["incident.records"]},
        },
    ],
}

# Known-answer vectors. Each literal was computed ONCE, by a scratch run that used only
# ``_independent_jcs`` / ``hashlib`` below and never the module under test, then pasted here.
_KAT_SPEC_REF = "f8832c469bf69b7670c9632d0808032280098517a7ec062a8f4d769b494b70bb"
_KAT_SLOT_REF = "4af84380efef26f19c100d723db9c8bbc73fc0baf82f38a92962af8929239f9c"
_KAT_ATTEMPT_ID = "wa-b7de9303d4fa773791cc44311f5076018c0204056ab850b2adf922f54ae36839"
_KAT_ATTEMPT_REF = "20e53e2e3b82e303e197427f47204d73fe79e3d1992f8bd211ca73c8acf3d047"

# Domain prefixes, written as literals on purpose: importing the module's own table would make
# a wrong prefix agree with itself.
_DOMAIN_TEAM_SPEC = b"probos.elastic_team/team_spec/v1\x00"
_DOMAIN_WORKER_SLOT = b"probos.elastic_team/worker_slot/v1\x00"
_DOMAIN_WORKER_ATTEMPT = b"probos.elastic_team/worker_attempt/v1\x00"
_DOMAIN_WORKER_ATTEMPT_ID = b"probos.elastic_team/worker_attempt_id/v1\x00"

_MERGE_NONE: dict[str, Any] = {"quorum": None, "reducer_id": None, "adjudicator_slot_id": None}
_DROP = object()  # sentinel for _patched: delete the key at the path instead of setting it
_MAX_SPEC_BYTES = 262_144

_REPO_ROOT = Path(__file__).resolve().parent.parent


def _independent_jcs(value: object) -> bytes:
    """RFC 8785 bytes for the fixture domain only: None / bool / int / ASCII str / list / dict.

    Written without the module under test and without ``probos.federation.ard.jcs``. Object
    members are ordered by UTF-16 code unit (the ``utf-16-be`` bytes of the key), strings go
    through ``json.dumps(..., ensure_ascii=False)``, and a float -- or any other type -- is a
    ``TypeError``, because identity material never holds one.
    """

    def encode(item: object) -> str:
        if item is None:
            return "null"
        if isinstance(item, bool):
            return "true" if item else "false"
        if isinstance(item, int):
            return str(item)
        if isinstance(item, str):
            return json.dumps(item, ensure_ascii=False)
        if isinstance(item, list):
            return "[" + ",".join(encode(entry) for entry in item) + "]"
        if isinstance(item, dict):
            if not all(isinstance(key, str) for key in item):
                raise TypeError("object keys must be strings")
            members = sorted(item.items(), key=lambda pair: pair[0].encode("utf-16-be"))
            return "{" + ",".join(f"{encode(key)}:{encode(entry)}" for key, entry in members) + "}"
        raise TypeError(f"unsupported type {type(item).__name__}")

    return encode(value).encode("utf-8")


def _independent_digest(domain: bytes, value: object) -> str:
    return hashlib.sha256(domain + _independent_jcs(value)).hexdigest()


def _spec_dict(**overrides: Any) -> dict[str, Any]:
    """A deep copy of the KAT spec with the named top-level keys replaced."""
    data = copy.deepcopy(_KAT_SPEC)
    data.update(copy.deepcopy(overrides))
    return data


def _spec(**overrides: Any) -> ElasticTeamSpec:
    """A validated KAT spec with the named top-level keys replaced (the store tests reuse it)."""
    return ElasticTeamSpec.model_validate(_spec_dict(**overrides))


def _slot(**overrides: Any) -> dict[str, Any]:
    """A deep copy of the KAT ``analyse`` slot (a dict, so callers can patch before validating)."""
    slot = copy.deepcopy(_KAT_SPEC["slots"][0])
    slot.update(copy.deepcopy(overrides))
    return slot


def _review_slot(**overrides: Any) -> dict[str, Any]:
    """A deep copy of the KAT ``review`` slot, the adjudicator the ``analyse`` slot names."""
    slot = copy.deepcopy(_KAT_SPEC["slots"][1])
    slot.update(copy.deepcopy(overrides))
    return slot


def _patched(path: str, value: Any) -> dict[str, Any]:
    """The KAT spec dict with the dotted ``path`` set to ``value`` (digit segments index lists)."""
    data = _spec_dict()
    *parents, leaf = path.split(".")
    node: Any = data
    for part in parents:
        node = node[int(part)] if part.isdigit() else node[part]
    key: Any = int(leaf) if leaf.isdigit() else leaf
    if value is _DROP:
        del node[key]
    else:
        node[key] = value
    return data


def _attempt(**overrides: Any) -> WorkerAttempt:
    """A valid attempt for the KAT ``analyse`` slot; the id is derived unless one is supplied."""
    fields: dict[str, Any] = {
        "schema_version": 1,
        "team_spec_ref": _KAT_SPEC_REF,
        "session_id": "session-parent",
        "slot_id": "analyse",
        "ordinal": 1,
        "execution_profile_ref": _PROFILE_A,
        "supersedes_attempt_id": None,
    }
    fields.update(overrides)
    if "worker_attempt_id" not in fields:
        fields["worker_attempt_id"] = derive_worker_attempt_id(
            team_spec_ref=fields["team_spec_ref"],
            session_id=fields["session_id"],
            slot_id=fields["slot_id"],
            ordinal=fields["ordinal"],
        )
    return WorkerAttempt.model_validate(fields)


def _big_slot(index: int) -> dict[str, Any]:
    """A valid slot carrying the largest legal sets (32 items of 124-128 characters each)."""
    slot = _slot(slot_id=f"slot{index:02d}")
    slot["merge"] = {"kind": "single", **_MERGE_NONE}
    slot["qualification"] = {
        "qualification_ids": [f"q{n:03d}" + "x" * 120 for n in range(32)],
        "pinned_profile_refs": [format(n, "064x") for n in range(32)],
    }
    slot["authority"] = {
        "tool_scopes": [f"t{n:03d}" + "x" * 120 for n in range(32)],
        "data_scopes": [f"d{n:03d}" + "x" * 120 for n in range(32)],
    }
    return slot


# --------------------------------------------------------------------------------------
# 1. Happy path
# --------------------------------------------------------------------------------------


def test_spec_happy_path_has_64_hex_content_ref() -> None:
    spec = _spec()

    assert re.fullmatch(r"[0-9a-f]{64}", spec.content_ref())
    assert [slot.slot_id for slot in spec.slots] == ["analyse", "review"]
    for slot in spec.slots:
        assert re.fullmatch(r"[0-9a-f]{64}", slot.content_ref())


# --------------------------------------------------------------------------------------
# 2. Malformed values are refused with a stable code
# --------------------------------------------------------------------------------------

# NOTE (prompt-vs-code): the build prompt's prose lists ``elastic_team_ref_set_invalid`` and
# ``elastic_team_scope_set_invalid`` for a malformed ELEMENT (an uppercase profile ref, the scope
# "Tool Read"). Section 1's normative ``_unique_sorted`` raises the ITEM code for a bad element
# (``elastic_team_ref_invalid`` / ``elastic_team_scope_invalid`` / ``elastic_team_id_invalid``) and
# the ``*_set_invalid`` code only for a container-level fault (not a list/tuple, more than 32
# items, a duplicate). These cases pin what the code does at both levels; they do not edit it.
_MALFORMED: list[Any] = [
    # team_id
    pytest.param("team_id", "", "elastic_team_id_invalid", id="team-id-empty"),
    pytest.param("team_id", "review team", "elastic_team_id_invalid", id="team-id-space"),
    pytest.param("team_id", "-review", "elastic_team_id_invalid", id="team-id-leading-punctuation"),
    pytest.param("team_id", "t" * 129, "elastic_team_id_invalid", id="team-id-too-long"),
    pytest.param("team_id", "review-team\n", "elastic_team_id_invalid", id="team-id-trailing-newline"),
    pytest.param("team_id", 7, "elastic_team_id_invalid", id="team-id-not-a-string"),
    # revision / schema_version
    pytest.param("revision", 0, "elastic_team_revision_invalid", id="revision-zero"),
    pytest.param("revision", True, "elastic_team_revision_invalid", id="revision-bool"),
    pytest.param("revision", 1.0, "elastic_team_revision_invalid", id="revision-float"),
    pytest.param("revision", "1", "elastic_team_revision_invalid", id="revision-string"),
    pytest.param("revision", 2_147_483_648, "elastic_team_revision_invalid", id="revision-too-large"),
    pytest.param("schema_version", 2, "elastic_team_schema_version_invalid", id="schema-version-2"),
    pytest.param("schema_version", True, "elastic_team_schema_version_invalid", id="schema-version-bool"),
    pytest.param("schema_version", "1", "elastic_team_schema_version_invalid", id="schema-version-string"),
    # slots
    pytest.param("slots", [], "elastic_team_slots_invalid", id="slots-empty"),
    pytest.param("slots", {"slot_id": "analyse"}, "elastic_team_slots_invalid", id="slots-not-a-sequence"),
    pytest.param(
        "slots", [{"slot_id": f"s{n:02d}"} for n in range(65)], "elastic_team_slots_invalid", id="slots-over-64"
    ),
    pytest.param("slots", [1], "elastic_team_slots_invalid", id="slots-entry-not-a-mapping"),
    pytest.param("slots", [{}], "elastic_team_slots_invalid", id="slots-entry-without-slot-id"),
    pytest.param("slots", [{"slot_id": 5}], "elastic_team_slots_invalid", id="slots-entry-slot-id-not-a-string"),
    pytest.param("slots.1.slot_id", "analyse", "elastic_team_slot_duplicate", id="slots-duplicate-slot-id"),
    # capacity
    pytest.param("slots.1.capacity.minimum", 2, "elastic_team_capacity_invalid", id="capacity-minimum-above-maximum"),
    pytest.param("slots.1.capacity.minimum", -1, "elastic_team_capacity_invalid", id="capacity-minimum-negative"),
    pytest.param("slots.0.capacity.maximum", 0, "elastic_team_capacity_invalid", id="capacity-maximum-zero"),
    pytest.param("slots.0.capacity.maximum", 65, "elastic_team_capacity_invalid", id="capacity-maximum-65"),
    pytest.param("slots.0.capacity.maximum", True, "elastic_team_capacity_invalid", id="capacity-maximum-bool"),
    # qualification: element faults surface the item code, container faults the set code
    pytest.param(
        "slots.0.qualification.pinned_profile_refs", ["A" * 64], "elastic_team_ref_invalid", id="pinned-ref-uppercase"
    ),
    pytest.param(
        "slots.0.qualification.pinned_profile_refs", ["a" * 63], "elastic_team_ref_invalid", id="pinned-ref-63-chars"
    ),
    pytest.param(
        "slots.0.qualification.pinned_profile_refs", [123], "elastic_team_ref_invalid", id="pinned-ref-not-a-string"
    ),
    pytest.param(
        "slots.0.qualification.pinned_profile_refs",
        [_PROFILE_A, _PROFILE_A],
        "elastic_team_ref_set_invalid",
        id="pinned-ref-duplicate",
    ),
    pytest.param(
        "slots.0.qualification.pinned_profile_refs", _PROFILE_A, "elastic_team_ref_set_invalid", id="pinned-ref-string"
    ),
    pytest.param(
        "slots.0.qualification.pinned_profile_refs",
        [format(n, "064x") for n in range(33)],
        "elastic_team_ref_set_invalid",
        id="pinned-ref-over-32",
    ),
    pytest.param(
        "slots.0.qualification.qualification_ids",
        ["finding_review", "finding_review"],
        "elastic_team_id_set_invalid",
        id="qualification-id-duplicate",
    ),
    pytest.param(
        "slots.0.qualification.qualification_ids", ["bad id"], "elastic_team_id_invalid", id="qualification-id-space"
    ),
    # independence
    pytest.param("slots.0.independence.mode", "random", "Input should be", id="independence-mode-unknown"),
    pytest.param(
        "slots.0.independence.min_distinct", 4, "elastic_team_independence_invalid", id="independence-above-capacity"
    ),
    pytest.param(
        "slots.0.independence",
        {"mode": "none", "min_distinct": 2},
        "elastic_team_independence_invalid",
        id="independence-none-with-distinct-2",
    ),
    pytest.param(
        "slots.0.independence.min_distinct", 0, "elastic_team_independence_invalid", id="independence-distinct-zero"
    ),
    # merge
    pytest.param("slots.0.merge.kind", "vote", "Input should be", id="merge-kind-unknown"),
    pytest.param(
        "slots.0.merge",
        {"kind": "first_accepted", **_MERGE_NONE},
        "elastic_team_merge_invalid",
        id="merge-first-accepted-without-quorum",
    ),
    pytest.param(
        "slots.1.merge",
        {**_MERGE_NONE, "kind": "single", "quorum": 1},
        "elastic_team_merge_invalid",
        id="merge-single-with-quorum",
    ),
    pytest.param(
        "slots.0.merge",
        {"kind": "reducer", **_MERGE_NONE},
        "elastic_team_merge_invalid",
        id="merge-reducer-without-reducer-id",
    ),
    pytest.param(
        "slots.0.merge",
        {"kind": "adjudicator", **_MERGE_NONE},
        "elastic_team_merge_invalid",
        id="merge-adjudicator-without-slot",
    ),
    pytest.param(
        "slots.0.merge",
        {"kind": "reducer", "quorum": 1, "reducer_id": "joiner", "adjudicator_slot_id": None},
        "elastic_team_merge_invalid",
        id="merge-reducer-with-a-second-field",
    ),
    pytest.param(
        "slots.0.merge.adjudicator_slot_id", "ghost", "elastic_team_merge_invalid", id="merge-adjudicator-unknown-slot"
    ),
    pytest.param(
        "slots.0.merge.adjudicator_slot_id", "analyse", "elastic_team_merge_invalid", id="merge-adjudicator-itself"
    ),
    pytest.param(
        "slots.0.merge",
        {**_MERGE_NONE, "kind": "first_accepted", "quorum": 4},
        "elastic_team_merge_invalid",
        id="merge-quorum-above-capacity",
    ),
    pytest.param(
        "slots.0.merge",
        {**_MERGE_NONE, "kind": "first_accepted", "quorum": 0},
        "elastic_team_merge_invalid",
        id="merge-quorum-zero",
    ),
    # budget
    pytest.param("slots.0.budget.max_tokens", 0, "elastic_team_budget_invalid", id="budget-max-tokens-zero"),
    pytest.param("slots.0.budget.max_tokens", True, "elastic_team_budget_invalid", id="budget-max-tokens-bool"),
    pytest.param("slots.0.budget.max_tokens", 2**53, "elastic_team_budget_invalid", id="budget-max-tokens-unsafe"),
    pytest.param("slots.0.budget.max_wall_ms", 1.5, "elastic_team_budget_invalid", id="budget-max-wall-ms-float"),
    pytest.param(
        "slots.0.budget.max_attempts", 2, "elastic_team_budget_invalid", id="budget-attempts-below-capacity"
    ),
    pytest.param("slots.0.budget.max_attempts", 1025, "elastic_team_budget_invalid", id="budget-attempts-over-1024"),
    # authority: element faults surface the item code, container faults the set code
    pytest.param(
        "slots.0.authority.tool_scopes", ["Tool Read"], "elastic_team_scope_invalid", id="tool-scope-with-space"
    ),
    pytest.param(
        "slots.0.authority.tool_scopes", ["Records.read"], "elastic_team_scope_invalid", id="tool-scope-uppercase"
    ),
    pytest.param(
        "slots.0.authority.tool_scopes", ["1records"], "elastic_team_scope_invalid", id="tool-scope-leading-digit"
    ),
    pytest.param(
        "slots.0.authority.data_scopes",
        ["incident.records", "incident.records"],
        "elastic_team_scope_set_invalid",
        id="data-scope-duplicate",
    ),
    pytest.param(
        "slots.0.authority.tool_scopes",
        [f"scope{n:02d}" for n in range(33)],
        "elastic_team_scope_set_invalid",
        id="tool-scope-over-32",
    ),
    # process binding
    pytest.param(
        "process", {"bill": None, "plan_hash": None}, "elastic_team_process_binding_empty", id="process-empty"
    ),
    pytest.param("process.plan_hash", "x", "elastic_team_ref_invalid", id="process-plan-hash-short"),
    pytest.param("process.bill.bill_version", 0, "elastic_team_revision_invalid", id="process-bill-version-zero"),
    pytest.param("process.bill.bill_id", "", "elastic_team_id_invalid", id="process-bill-id-empty"),
    # unknown and missing keys
    pytest.param("bogus", 1, "extra_forbidden", id="extra-top-level-key"),
    pytest.param("slots.0.budget.bogus", 1, "extra_forbidden", id="extra-nested-key"),
    pytest.param("slots.0.merge.reducer_id", _DROP, "Field required", id="missing-optional-key-merge"),
    pytest.param("process.plan_hash", _DROP, "Field required", id="missing-optional-key-plan-hash"),
    pytest.param("schema_version", _DROP, "Field required", id="missing-schema-version"),
]


@pytest.mark.parametrize(("path", "value", "code"), _MALFORMED)
def test_spec_rejects_malformed_values(path: str, value: Any, code: str) -> None:
    payload = _patched(path, value)

    with pytest.raises(ValidationError, match=code):
        ElasticTeamSpec.model_validate(payload)


# --------------------------------------------------------------------------------------
# 3. Order never changes identity
# --------------------------------------------------------------------------------------


def test_set_order_and_slot_order_do_not_change_identity() -> None:
    declared = _spec_dict()
    declared["slots"][0]["authority"]["tool_scopes"] = ["records.read", "records.write"]
    declared["slots"][0]["qualification"]["qualification_ids"] = ["evidence_analysis", "triage"]
    declared["slots"][0]["qualification"]["pinned_profile_refs"] = [_PROFILE_A, "b" * 64]
    reordered = copy.deepcopy(declared)
    reordered["slots"].reverse()
    analyse = next(slot for slot in reordered["slots"] if slot["slot_id"] == "analyse")
    analyse["authority"]["tool_scopes"].reverse()
    analyse["qualification"]["qualification_ids"].reverse()
    analyse["qualification"]["pinned_profile_refs"].reverse()
    assert [slot["slot_id"] for slot in reordered["slots"]] == ["review", "analyse"]

    first = ElasticTeamSpec.model_validate(declared)
    second = ElasticTeamSpec.model_validate(reordered)

    assert first.content_ref() == second.content_ref()
    assert first.canonical_bytes() == second.canonical_bytes()
    assert first == second
    slot_ids = [slot.slot_id for slot in second.slots]
    assert slot_ids == sorted(slot_ids) == ["analyse", "review"]
    assert second.slots[0].authority.tool_scopes == ("records.read", "records.write")
    assert second.slots[0].qualification.qualification_ids == ("evidence_analysis", "triage")
    assert second.slots[0].qualification.pinned_profile_refs == (_PROFILE_A, "b" * 64)


def test_spec_accepts_slot_instances_and_tuples_with_the_same_identity() -> None:
    from_dicts = _spec()
    instances = tuple(WorkerSlot.model_validate(slot) for slot in reversed(_KAT_SPEC["slots"]))

    from_instances = _spec(slots=instances)

    assert from_instances.content_ref() == from_dicts.content_ref()
    assert from_instances == from_dicts


# --------------------------------------------------------------------------------------
# 4. Canonical round trip
# --------------------------------------------------------------------------------------


def test_canonical_round_trip_preserves_every_field() -> None:
    spec = _spec()

    dumped = json.loads(spec.canonical_bytes())
    again = ElasticTeamSpec.model_validate(dumped)

    assert again == spec
    assert again.canonical_bytes() == spec.canonical_bytes()
    assert again.content_ref() == spec.content_ref()
    assert set(dumped) == set(ElasticTeamSpec.model_fields)
    slot = dumped["slots"][0]
    nested = [
        (dumped["process"], ProcessBinding),
        (dumped["process"]["bill"], BillRef),
        (slot, WorkerSlot),
        (slot["capacity"], CapacityRange),
        (slot["qualification"], QualificationRequirement),
        (slot["independence"], IndependencePolicy),
        (slot["merge"], MergeRule),
        (slot["budget"], SlotBudget),
        (slot["authority"], AuthorityCeiling),
    ]
    for payload, model in nested:
        assert set(payload) == set(model.model_fields), model.__name__


def test_contracts_are_frozen() -> None:
    spec = _spec()
    attempt = _attempt()

    with pytest.raises(ValidationError, match="frozen_instance"):
        spec.revision = 2  # type: ignore[misc]
    with pytest.raises(ValidationError, match="frozen_instance"):
        spec.slots[0].role_id = "other"  # type: ignore[misc]
    with pytest.raises(ValidationError, match="frozen_instance"):
        attempt.ordinal = 2  # type: ignore[misc]


# --------------------------------------------------------------------------------------
# 5. Material change -> new identity
# --------------------------------------------------------------------------------------

_NEW_SLOT = {
    "slot_id": "triage",
    "role_id": "triager",
    "task_class": "intake_triage",
    "capacity": {"minimum": 1, "maximum": 1},
    "qualification": {"qualification_ids": [], "pinned_profile_refs": []},
    "independence": {"mode": "none", "min_distinct": 1},
    "merge": {"kind": "single", **_MERGE_NONE},
    "budget": {"max_tokens": 1000, "max_wall_ms": 1000, "max_attempts": 1},
    "authority": {"tool_scopes": [], "data_scopes": []},
}

# (id, dotted path, new value, slot-level?) -- every row is ONE change to a valid spec.
_MATERIAL_CHANGES: list[Any] = [
    pytest.param("slots.0.role_id", "senior_analyst", True, id="role-id"),
    pytest.param("slots.0.task_class", "deep_analysis", True, id="task-class"),
    pytest.param("slots.0.capacity.minimum", 2, True, id="capacity-minimum"),
    pytest.param("slots.0.capacity.maximum", 4, True, id="capacity-maximum"),
    pytest.param(
        "slots.0.qualification.qualification_ids", ["evidence_analysis", "triage"], True, id="qualification-id-added"
    ),
    pytest.param("slots.0.qualification.pinned_profile_refs", ["b" * 64], True, id="pinned-profile-changed"),
    pytest.param("slots.0.independence.mode", "distinct_models", True, id="independence-mode"),
    pytest.param("slots.0.independence.min_distinct", 3, True, id="independence-min-distinct"),
    pytest.param(
        "slots.0.merge", {"kind": "all_required", **_MERGE_NONE}, True, id="merge-kind-all-required-adjudicator-cleared"
    ),
    pytest.param("slots.0.budget.max_tokens", 200001, True, id="budget-max-tokens"),
    pytest.param("slots.0.budget.max_wall_ms", 900001, True, id="budget-max-wall-ms"),
    pytest.param("slots.0.budget.max_attempts", 7, True, id="budget-max-attempts"),
    pytest.param("slots.0.authority.tool_scopes", ["records.read", "records.write"], True, id="tool-scope-added"),
    pytest.param(
        "slots.0.authority.data_scopes", ["incident.records", "incident.notes"], True, id="data-scope-added"
    ),
    pytest.param("process.bill.bill_version", 4, False, id="bill-version"),
    pytest.param("process.plan_hash", "c" * 64, False, id="plan-hash-set"),
    pytest.param("team_id", "review-team-b", False, id="team-id"),
    pytest.param("revision", 2, False, id="revision"),
]


@pytest.mark.parametrize(("path", "value", "slot_level"), _MATERIAL_CHANGES)
def test_material_change_changes_identity(path: str, value: Any, slot_level: bool) -> None:
    before = _spec()
    assert ElasticTeamSpec.model_validate(_spec_dict()).content_ref() == before.content_ref()  # control

    after = ElasticTeamSpec.model_validate(_patched(path, value))

    assert after.content_ref() != before.content_ref()
    assert after.canonical_bytes() != before.canonical_bytes()
    if slot_level:
        assert after.slot("analyse").content_ref() != before.slot("analyse").content_ref()
        assert after.slot("review").content_ref() == before.slot("review").content_ref()


def test_adding_a_slot_changes_the_spec_identity_but_no_existing_slot() -> None:
    before = _spec()

    after = _spec(slots=[_slot(), _review_slot(), _NEW_SLOT])

    assert after.content_ref() != before.content_ref()
    assert [slot.slot_id for slot in after.slots] == ["analyse", "review", "triage"]
    for slot_id in ("analyse", "review"):
        assert after.slot(slot_id).content_ref() == before.slot(slot_id).content_ref()


def test_spec_slot_lookup_returns_the_named_slot_or_none() -> None:
    spec = _spec()

    assert spec.slot("review") == spec.slots[1]
    assert spec.slot("analyse") == spec.slots[0]
    assert spec.slot("ghost") is None


def test_oversize_spec_is_refused() -> None:
    within_limit = _spec(slots=[_big_slot(index) for index in range(5)])  # control: same shape, fewer slots
    assert len(within_limit.canonical_bytes()) <= _MAX_SPEC_BYTES

    with pytest.raises(ValidationError, match="elastic_team_spec_too_large"):
        _spec(slots=[_big_slot(index) for index in range(20)])


@pytest.mark.parametrize(
    "process",
    [
        {"bill": {"bill_id": "incident-review", "bill_version": 3}, "plan_hash": None},
        {"bill": None, "plan_hash": "c" * 64},
        {"bill": {"bill_id": "incident-review", "bill_version": 3}, "plan_hash": "c" * 64},
    ],
    ids=["bill-only", "plan-only", "both"],
)
def test_process_binding_accepts_a_bill_a_plan_or_both(process: dict[str, Any]) -> None:
    spec = _spec(process=process)

    assert spec.process.model_dump(mode="json") == process


# --------------------------------------------------------------------------------------
# 6-8. Attempts: identity excludes runtime state; the id is derived; outcome boundaries
# --------------------------------------------------------------------------------------


def test_attempt_identity_excludes_runtime_state() -> None:
    attempt = _attempt()
    digest_before = attempt.content_ref()

    succeeded = WorkerAttemptOutcome(
        worker_attempt_id=attempt.worker_attempt_id, terminal_status="succeeded", error_code=None, recorded_at=1000.0
    )
    failed = WorkerAttemptOutcome(
        worker_attempt_id=attempt.worker_attempt_id, terminal_status="failed", error_code="model_timeout",
        recorded_at=2000.0,
    )

    assert attempt.content_ref() == digest_before
    assert succeeded.terminal_status != failed.terminal_status
    projection = set(attempt.model_dump(mode="json"))
    assert projection == {
        "schema_version",
        "worker_attempt_id",
        "team_spec_ref",
        "session_id",
        "slot_id",
        "ordinal",
        "execution_profile_ref",
        "supersedes_attempt_id",
    }
    runtime_only = set(WorkerAttemptOutcome.model_fields) - {"worker_attempt_id"}
    assert runtime_only == {"terminal_status", "error_code", "recorded_at"}
    assert not runtime_only & projection


def test_attempt_id_is_derived_and_refuses_mismatch() -> None:
    base = {"team_spec_ref": _KAT_SPEC_REF, "session_id": "session-parent", "slot_id": "analyse", "ordinal": 1}
    derived = derive_worker_attempt_id(**base)

    assert derived == derive_worker_attempt_id(**base)
    assert re.fullmatch(r"wa-[0-9a-f]{64}", derived)
    variants = [
        {**base, "team_spec_ref": "b" * 64},
        {**base, "session_id": "session-other"},
        {**base, "slot_id": "review"},
        {**base, "ordinal": 2},
    ]
    variant_ids = {derive_worker_attempt_id(**variant) for variant in variants}
    assert len(variant_ids) == 4 and derived not in variant_ids
    assert _attempt().worker_attempt_id == derived

    with pytest.raises(ValidationError, match="elastic_attempt_id_mismatch"):
        _attempt(worker_attempt_id="wa-" + "0" * 64)
    with pytest.raises(ValidationError, match="elastic_attempt_supersedes_invalid"):
        _attempt(supersedes_attempt_id=derived)
    for ordinal in (0, 1025):
        with pytest.raises(ValidationError, match="elastic_attempt_ordinal_invalid"):
            _attempt(worker_attempt_id=derived, ordinal=ordinal)
        with pytest.raises(ValueError, match="elastic_attempt_ordinal_invalid"):
            derive_worker_attempt_id(**{**base, "ordinal": ordinal})


def test_derive_worker_attempt_id_refuses_malformed_inputs() -> None:
    base = {"team_spec_ref": _KAT_SPEC_REF, "session_id": "session-parent", "slot_id": "analyse", "ordinal": 1}

    with pytest.raises(ValueError, match="elastic_team_ref_invalid"):
        derive_worker_attempt_id(**{**base, "team_spec_ref": "A" * 64})
    with pytest.raises(ValueError, match="elastic_team_id_invalid"):
        derive_worker_attempt_id(**{**base, "session_id": "session parent"})
    with pytest.raises(ValueError, match="elastic_team_id_invalid"):
        derive_worker_attempt_id(**{**base, "slot_id": ""})
    with pytest.raises(ValueError, match="elastic_attempt_ordinal_invalid"):
        derive_worker_attempt_id(**{**base, "ordinal": True})


def test_attempt_validates_its_reference_fields() -> None:
    derived = derive_worker_attempt_id(
        team_spec_ref=_KAT_SPEC_REF, session_id="session-parent", slot_id="analyse", ordinal=1
    )

    predecessor = _attempt(ordinal=2, supersedes_attempt_id=derived)

    assert predecessor.supersedes_attempt_id == derived
    with pytest.raises(ValidationError, match="elastic_team_id_invalid"):
        _attempt(ordinal=2, supersedes_attempt_id="not a valid id")
    with pytest.raises(ValidationError, match="elastic_team_ref_invalid"):
        _attempt(execution_profile_ref="A" * 64)


_OUTCOME_BASE: dict[str, Any] = {
    "worker_attempt_id": "wa-" + "1" * 64,
    "terminal_status": "failed",
    "error_code": "model_timeout",
    "recorded_at": 1000.0,
}


@pytest.mark.parametrize(
    ("patch", "code"),
    [
        pytest.param({"terminal_status": "succeeded"}, "elastic_attempt_outcome_invalid", id="succeeded-with-error-code"),
        pytest.param({"error_code": None}, "elastic_attempt_outcome_invalid", id="failed-without-error-code"),
        pytest.param(
            {"terminal_status": "cancelled", "error_code": None},
            "elastic_attempt_outcome_invalid",
            id="cancelled-without-error-code",
        ),
        pytest.param({"recorded_at": 5}, "elastic_attempt_outcome_invalid", id="recorded-at-int"),
        pytest.param({"recorded_at": float("nan")}, "elastic_attempt_outcome_invalid", id="recorded-at-nan"),
        pytest.param({"recorded_at": float("inf")}, "elastic_attempt_outcome_invalid", id="recorded-at-inf"),
        pytest.param({"recorded_at": -1.0}, "elastic_attempt_outcome_invalid", id="recorded-at-negative"),
        pytest.param(
            {"recorded_at": 253_402_300_800.0}, "elastic_attempt_outcome_invalid", id="recorded-at-after-year-9999"
        ),
        pytest.param({"error_code": "Model Timeout"}, "elastic_attempt_outcome_invalid", id="error-code-not-snake-case"),
        pytest.param({"error_code": ""}, "elastic_attempt_outcome_invalid", id="error-code-empty"),
        pytest.param({"terminal_status": "pending"}, "Input should be", id="terminal-status-unknown"),
        pytest.param({"worker_attempt_id": "not an id"}, "elastic_team_id_invalid", id="attempt-id-malformed"),
        pytest.param({"unexpected": 1}, "extra_forbidden", id="extra-key"),
    ],
)
def test_outcome_boundaries(patch: dict[str, Any], code: str) -> None:
    fields = {**_OUTCOME_BASE, **patch}

    with pytest.raises(ValidationError, match=code):
        WorkerAttemptOutcome.model_validate(fields)


@pytest.mark.parametrize(
    ("status", "error_code"),
    [("succeeded", None), ("failed", "model_timeout"), ("cancelled", "operator_cancelled")],
)
def test_outcome_accepts_each_terminal_status_with_its_matching_error_code(
    status: str, error_code: str | None
) -> None:
    outcome = WorkerAttemptOutcome.model_validate(
        {**_OUTCOME_BASE, "terminal_status": status, "error_code": error_code}
    )

    assert outcome.terminal_status == status
    assert outcome.error_code == error_code
    assert outcome.recorded_at == 1000.0


# --------------------------------------------------------------------------------------
# 9. The CrewSession binding value
# --------------------------------------------------------------------------------------


def test_binding_for_spec_names_exact_spec() -> None:
    spec = _spec()

    binding = CrewElasticTeamBinding.for_spec(spec)

    assert binding.team_spec_ref == spec.content_ref()
    assert binding.team_id == spec.team_id
    assert binding.revision == spec.revision
    assert binding.version == 1
    assert set(binding.model_dump(mode="json")) == {"version", "team_spec_ref", "team_id", "revision"}
    assert CrewElasticTeamBinding.model_validate(binding.model_dump(mode="json")) == binding
    assert CREW_ELASTIC_TEAM_METADATA_KEY == "crew_elastic_team"
    assert ELASTIC_TEAM_SCHEMA_VERSION == 1


@pytest.mark.parametrize(
    ("patch", "code"),
    [
        pytest.param({"team_spec_ref": "A" * 64}, "elastic_team_ref_invalid", id="ref-uppercase"),
        pytest.param({"team_spec_ref": "a" * 63}, "elastic_team_ref_invalid", id="ref-short"),
        pytest.param({"version": 2}, "elastic_team_schema_version_invalid", id="version-2"),
        pytest.param({"revision": 0}, "elastic_team_revision_invalid", id="revision-zero"),
        pytest.param({"team_id": ""}, "elastic_team_id_invalid", id="team-id-empty"),
        pytest.param({"extra": 1}, "extra_forbidden", id="extra-key"),
    ],
)
def test_binding_refuses_malformed_values(patch: dict[str, Any], code: str) -> None:
    binding = CrewElasticTeamBinding.for_spec(_spec()).model_dump(mode="json")

    with pytest.raises(ValidationError, match=code):
        CrewElasticTeamBinding.model_validate({**binding, **patch})


# --------------------------------------------------------------------------------------
# 10. Known-answer vectors
# --------------------------------------------------------------------------------------


def test_known_answer_vectors_match_an_independent_rfc8785_encoding() -> None:
    spec = _spec()
    attempt_projection = {
        "schema_version": 1,
        "worker_attempt_id": _KAT_ATTEMPT_ID,
        "team_spec_ref": _KAT_SPEC_REF,
        "session_id": "session-parent",
        "slot_id": "analyse",
        "ordinal": 1,
        "execution_profile_ref": _PROFILE_A,
        "supersedes_attempt_id": None,
    }

    # The independent encoder, digested with hashlib alone, reproduces every pinned literal ...
    assert _independent_digest(_DOMAIN_TEAM_SPEC, _KAT_SPEC) == _KAT_SPEC_REF
    assert _independent_digest(_DOMAIN_WORKER_SLOT, _KAT_SPEC["slots"][0]) == _KAT_SLOT_REF
    assert (
        "wa-" + _independent_digest(_DOMAIN_WORKER_ATTEMPT_ID, [_KAT_SPEC_REF, "session-parent", "analyse", 1])
        == _KAT_ATTEMPT_ID
    )
    assert _independent_digest(_DOMAIN_WORKER_ATTEMPT, attempt_projection) == _KAT_ATTEMPT_REF
    # ... and the module under test agrees byte for byte.
    assert spec.canonical_bytes() == _independent_jcs(_KAT_SPEC)
    assert spec.content_ref() == _KAT_SPEC_REF
    assert spec.slot("analyse").content_ref() == _KAT_SLOT_REF
    assert (
        derive_worker_attempt_id(
            team_spec_ref=_KAT_SPEC_REF, session_id="session-parent", slot_id="analyse", ordinal=1
        )
        == _KAT_ATTEMPT_ID
    )
    attempt = _attempt()
    assert attempt.worker_attempt_id == _KAT_ATTEMPT_ID
    assert attempt.model_dump(mode="json") == attempt_projection
    assert attempt.content_ref() == _KAT_ATTEMPT_REF
    # The domain prefix is part of what is hashed: the bare canonical bytes digest differently.
    assert hashlib.sha256(_independent_jcs(_KAT_SPEC)).hexdigest() != _KAT_SPEC_REF
    assert hashlib.sha256(_independent_jcs(_KAT_SPEC["slots"][0])).hexdigest() != _KAT_SLOT_REF


def test_independent_encoder_refuses_floats_and_unknown_types() -> None:
    assert _independent_jcs({"b": [True, None, 2], "a": "x"}) == b'{"a":"x","b":[true,null,2]}'
    for unsupported in (1.5, 1.0, {"x": 1.5}, [b"bytes"], (1, 2), {1: "numeric key"}):
        with pytest.raises(TypeError):
            _independent_jcs(unsupported)


def test_content_digest_refuses_an_unknown_or_non_string_kind() -> None:
    value = {"a": 1}

    assert content_digest("team_spec", value) == _independent_digest(_DOMAIN_TEAM_SPEC, value)
    assert content_digest("worker_slot", value) != content_digest("team_spec", value)
    for kind in ("unknown", "", b"team_spec", None, 3):
        with pytest.raises(ValueError, match="elastic_team_identity_kind_invalid"):
            content_digest(kind, value)  # type: ignore[arg-type]
    assert canonicalize_projection(value) == _independent_jcs(value)


def test_is_sha256_ref_accepts_only_lowercase_64_hex() -> None:
    assert is_sha256_ref("0" * 64)
    assert is_sha256_ref(_KAT_SPEC_REF)
    for rejected in ("A" * 64, "a" * 63, "a" * 65, "g" * 64, "a" * 64 + "\n", "", None, 5, b"a" * 64):
        assert not is_sha256_ref(rejected)


# --------------------------------------------------------------------------------------
# 10b. Instances are revalidated (review round 1, F4)
# --------------------------------------------------------------------------------------


def test_outer_validation_refuses_a_nested_instance_built_without_validation() -> None:
    """``model_copy(update=...)`` skips validation, so a nested copy can carry a value no constructor accepts.

    With the default ``revalidate_instances='never'`` the outer ``model_validate`` accepted such a nested
    instance as-is; ``revalidate_instances='always'`` makes the outer validation re-check it.
    """
    unvalidated = SlotBudget(max_tokens=200000, max_wall_ms=900000, max_attempts=6).model_copy(
        update={"max_tokens": 1.5}
    )
    assert unvalidated.max_tokens == 1.5  # the copy really does hold the invalid value
    data = _spec_dict()
    data["slots"][0]["budget"] = unvalidated

    with pytest.raises(ValidationError, match="elastic_team_budget_invalid"):
        ElasticTeamSpec.model_validate(data)


def test_revalidation_keeps_every_known_answer_identity() -> None:
    """Re-validating an already valid instance yields an equal instance with the SAME pinned identity."""
    spec = _spec()
    slot = spec.slot("analyse")
    attempt = _attempt()
    assert slot is not None

    revalidated_spec = ElasticTeamSpec.model_validate(spec)
    revalidated_slot = WorkerSlot.model_validate(slot)
    revalidated_attempt = WorkerAttempt.model_validate(attempt)

    assert revalidated_spec == spec and revalidated_spec.content_ref() == _KAT_SPEC_REF
    assert revalidated_slot == slot and revalidated_slot.content_ref() == _KAT_SLOT_REF
    assert revalidated_attempt == attempt
    assert revalidated_attempt.worker_attempt_id == _KAT_ATTEMPT_ID
    assert revalidated_attempt.content_ref() == _KAT_ATTEMPT_REF
    assert revalidated_spec.canonical_bytes() == spec.canonical_bytes()


# --------------------------------------------------------------------------------------
# 11. Cross-process stability
# --------------------------------------------------------------------------------------

_STABILITY_SCRIPT = (
    "import json, sys\n"
    "from probos.cognitive.elastic_team import ElasticTeamSpec\n"
    "spec = ElasticTeamSpec.model_validate(json.loads(sys.argv[1]))\n"
    "print(spec.content_ref())\n"
)


def test_identity_is_stable_across_processes(tmp_path: Path) -> None:
    printed = []
    for seed in ("0", "4242"):
        env = {**os.environ, "PYTHONHASHSEED": seed, "PROBOS_DATA_DIR": str(tmp_path)}

        completed = subprocess.run(
            [sys.executable, "-c", _STABILITY_SCRIPT, json.dumps(_KAT_SPEC)],
            env=env,
            check=True,
            capture_output=True,
            text=True,
            timeout=120,
        )

        printed.append(completed.stdout.strip())

    assert printed == [_KAT_SPEC_REF, _KAT_SPEC_REF]


# --------------------------------------------------------------------------------------
# 12. Import layering
# --------------------------------------------------------------------------------------

_CREW_AND_WORKFORCE_MODULES = (
    "probos.cognitive.crew_session",
    "probos.cognitive.crew_executor",
    "probos.cognitive.crew_orchestrator",
    "probos.workforce",
)


class _ImportCollector(ast.NodeVisitor):
    """Collects dotted import names, optionally only those that run when the module is imported."""

    def __init__(self, *, module_scope_only: bool) -> None:
        self.names: set[str] = set()
        self._module_scope_only = module_scope_only

    def visit_Import(self, node: ast.Import) -> None:
        self.names.update(alias.name for alias in node.names)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.level == 0 and node.module:
            self.names.add(node.module)
            self.names.update(f"{node.module}.{alias.name}" for alias in node.names)

    def _enter_function(self, node: ast.AST) -> None:
        # A function body does not run at import time; a class body does.
        if not self._module_scope_only:
            self.generic_visit(node)

    visit_FunctionDef = visit_AsyncFunctionDef = visit_Lambda = _enter_function


def _imports_of(module_name: str, *, module_scope_only: bool) -> set[str]:
    spec = importlib.util.find_spec(module_name)
    assert spec is not None and spec.origin is not None, f"{module_name} is not importable"
    collector = _ImportCollector(module_scope_only=module_scope_only)
    collector.visit(ast.parse(Path(spec.origin).read_text(encoding="utf-8")))
    return collector.names


def _is_under(name: str, prefix: str) -> bool:
    return name == prefix or name.startswith(prefix + ".")


@pytest.mark.parametrize("module_name", ["probos.cognitive.elastic_team", "probos.cognitive.elastic_team_store"])
def test_module_imports_no_crew_or_workforce_and_no_federation_at_import(
    module_name: str, tmp_path: Path
) -> None:
    at_import = _imports_of(module_name, module_scope_only=True)
    anywhere = _imports_of(module_name, module_scope_only=False)

    # (a) static: neither module imports the crew/workforce modules (at all), nor federation at import.
    for forbidden in _CREW_AND_WORKFORCE_MODULES:
        assert not [name for name in at_import if _is_under(name, forbidden)], forbidden
        assert not [name for name in anywhere if _is_under(name, forbidden)], forbidden
    assert not [name for name in at_import if _is_under(name, "probos.federation")]
    if module_name.endswith(".elastic_team"):
        # the one permitted federation import is lazy, inside ``canonicalize_projection``
        assert "probos.federation.ard.jcs" in anywhere

    # (b) dynamic: importing the module does not import the federation package.
    completed = subprocess.run(
        [sys.executable, "-c", f"import {module_name}, sys; print('probos.federation' in sys.modules)"],
        env={**os.environ, "PROBOS_DATA_DIR": str(tmp_path)},
        check=True,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert completed.stdout.strip() == "False"
