"""AD-1287 S1: execution profiles -- the exact combination a worker slot qualifies -- and their evaluation evidence.

An ``ExecutionProfile`` names one exact combination: role, task class, the resource digest of each
cognitive skill, the model (provider, name, version label), each prompt revision, each tool's schema
and implementation digests, the policy digest, and the evaluation suite (its id, revision, dataset
digest, pass rule and validity). Its identity is ``sha256(PROFILE_DOMAIN + RFC 8785 bytes)`` over
``model_dump(mode="json")``, computed with AD-1286's ``canonicalize_projection``. Identity material
holds no floats. Component sequences are sorted by their key at validation and a duplicate key is
refused, so declaration order never changes a reference. Every field is always emitted: a new field
is a new schema version, never a silent re-hash of v1.

Evidence is keyed by profile reference and this slice has no migration path, so a profile that
differs in any component starts with no evaluation. ``EvaluationRecord`` is one evaluator run, raw:
per case, whether it passed, its quality score in basis points, its cost in micro-USD and its latency
in milliseconds, all integers. ``assess_evaluation`` turns one record plus the store's facts (issue
time, invalidation, now) into a status; ``slot_refusal`` compares a profile with a slot's declared
constraints. These types carry no tool scope, data scope, rank or lease, and nothing here grants
authority: qualification permits selection consideration only (AD-1288 leases authority).
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable
from typing import Annotated, Any, Final, Literal

from pydantic import BaseModel, BeforeValidator, ConfigDict

from probos.cognitive.elastic_team import ElasticId, Revision, Sha256Ref, WorkerSlot, canonicalize_projection

EXECUTION_PROFILE_SCHEMA_VERSION: Final = 1
PROFILE_DOMAIN: Final = b"probos.execution_profile/profile/v1\x00"
EVALUATION_DOMAIN: Final = b"probos.execution_profile/evaluation/v1\x00"
BASIS_POINTS: Final = 10_000

_LABEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:/@+-]{0,127}$")
_MAX_COMPONENTS: Final = 32
_MAX_OBSERVATIONS: Final = 1_024
_MAX_SAFE_INT: Final = 2**53 - 1
_MAX_VALIDITY_SECONDS: Final = 31_622_400  # 366 days

QualificationStatus = Literal[
    "qualified",
    "unevaluated",
    "invalidated",
    "expired",
    "structurally_invalid",
    "insufficient_sample",
    "failed",
]


def _int_range(low: int, high: int, code: str) -> Callable[[Any], int]:
    def check(value: Any) -> int:
        if type(value) is not int or not low <= value <= high:
            raise ValueError(code)
        return value

    return check


def _label(value: Any) -> str:
    if type(value) is not str or _LABEL_RE.fullmatch(value) is None:
        raise ValueError("execution_profile_model_invalid")
    return value


def _keyed(
    model: type[BaseModel], key: str, minimum: int, maximum: int, code: str,
) -> Callable[[Any], tuple[Any, ...]]:
    """Sort a component sequence by ``key`` and refuse a duplicate key, so declaration order never matters."""

    def check(value: Any) -> tuple[Any, ...]:
        if type(value) not in (list, tuple) or not minimum <= len(value) <= maximum:
            raise ValueError(code)
        keyed: list[tuple[str, Any]] = []
        for entry in value:
            if type(entry) is model:
                name: Any = getattr(entry, key)
            elif type(entry) is dict:
                name = entry.get(key)
            else:
                name = None
            if type(name) is not str:
                raise ValueError(code)
            keyed.append((name, entry))
        names = [name for name, _ in keyed]
        if len(set(names)) != len(names):
            raise ValueError(code)
        return tuple(entry for _, entry in sorted(keyed, key=lambda pair: pair[0]))

    return check


ModelLabel = Annotated[str, BeforeValidator(_label)]
ProfileSchemaVersion = Annotated[
    Literal[1], BeforeValidator(_int_range(1, 1, "execution_profile_schema_version_invalid"))
]
MinSamples = Annotated[int, BeforeValidator(_int_range(1, _MAX_OBSERVATIONS, "execution_profile_suite_invalid"))]
PassBasisPoints = Annotated[int, BeforeValidator(_int_range(1, BASIS_POINTS, "execution_profile_suite_invalid"))]
ValiditySeconds = Annotated[
    int, BeforeValidator(_int_range(1, _MAX_VALIDITY_SECONDS, "execution_profile_suite_invalid"))
]
ScoreBasisPoints = Annotated[int, BeforeValidator(_int_range(0, BASIS_POINTS, "profile_evaluation_invalid"))]
Measure = Annotated[int, BeforeValidator(_int_range(0, _MAX_SAFE_INT, "profile_evaluation_invalid"))]


class _Frozen(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True, revalidate_instances="always")


class SkillComponent(_Frozen):
    """One AD-596 cognitive skill by ``CognitiveSkillEntry.name`` and the digest of its resources."""

    skill_name: ElasticId
    resource_digest: Sha256Ref


class ModelComponent(_Frozen):
    """The model a profile runs on: ``ModelDescriptor.provider`` and ``.name``, plus the provider's version label."""

    provider: ElasticId
    name: ModelLabel
    version: ModelLabel


class PromptComponent(_Frozen):
    """One prompt by id and the digest of the exact revision used."""

    prompt_id: ElasticId
    revision_digest: Sha256Ref


class ToolComponent(_Frozen):
    """One tool by ``Tool.tool_id`` and digests of its declared schemas and implementation. Names it; grants nothing."""

    tool_id: ElasticId
    schema_digest: Sha256Ref
    implementation_digest: Sha256Ref


class PolicyComponent(_Frozen):
    """The digest of the policy and permission profile a worker would run under. A reference, never a grant."""

    policy_digest: Sha256Ref


class EvaluationSuite(_Frozen):
    """The evaluation that decides qualification: id, revision, dataset, pass rule and how long a pass counts.

    ``qualification_id`` is the value ``WorkerSlot.qualification.qualification_ids`` names.
    """

    qualification_id: ElasticId
    suite_revision: Revision
    dataset_digest: Sha256Ref
    min_samples: MinSamples
    min_pass_bp: PassBasisPoints
    validity_seconds: ValiditySeconds


class ExecutionProfile(_Frozen):
    """One exact execution profile. Any component change gives a different ``content_ref()``."""

    schema_version: ProfileSchemaVersion
    role_id: ElasticId
    task_class: ElasticId
    skills: Annotated[
        tuple[SkillComponent, ...],
        BeforeValidator(_keyed(SkillComponent, "skill_name", 0, _MAX_COMPONENTS, "execution_profile_skills_invalid")),
    ]
    model: ModelComponent
    prompts: Annotated[
        tuple[PromptComponent, ...],
        BeforeValidator(_keyed(PromptComponent, "prompt_id", 0, _MAX_COMPONENTS, "execution_profile_prompts_invalid")),
    ]
    tools: Annotated[
        tuple[ToolComponent, ...],
        BeforeValidator(_keyed(ToolComponent, "tool_id", 0, _MAX_COMPONENTS, "execution_profile_tools_invalid")),
    ]
    policy: PolicyComponent
    evaluation_suite: EvaluationSuite

    def canonical_bytes(self) -> bytes:
        """RFC 8785 bytes of the full projection (no domain prefix); what the store persists."""
        return canonicalize_projection(self.model_dump(mode="json"))

    def content_ref(self) -> str:
        """The profile's identity: ``sha256(PROFILE_DOMAIN + canonical_bytes())``."""
        return hashlib.sha256(PROFILE_DOMAIN + self.canonical_bytes()).hexdigest()


class EvaluationObservation(_Frozen):
    """One evaluation case, raw. Integers only: score in basis points, cost in micro-USD, latency in ms."""

    case_id: ElasticId
    passed: bool
    score_bp: ScoreBasisPoints
    cost_micro_usd: Measure
    latency_ms: Measure


class EvaluationRecord(_Frozen):
    """One evaluation run of one profile as the evaluator reports it. The store stamps issue time and sequence.

    ``evaluator_id`` is provenance only; this slice does not authenticate it.
    """

    schema_version: ProfileSchemaVersion
    profile_ref: Sha256Ref
    evaluation_id: ElasticId
    evaluator_id: ElasticId
    structurally_valid: bool
    observations: Annotated[
        tuple[EvaluationObservation, ...],
        BeforeValidator(_keyed(EvaluationObservation, "case_id", 1, _MAX_OBSERVATIONS, "profile_evaluation_invalid")),
    ]

    @property
    def sample_size(self) -> int:
        """How many cases were observed."""
        return len(self.observations)

    @property
    def pass_count(self) -> int:
        """How many observed cases passed."""
        return sum(1 for observation in self.observations if observation.passed)

    def canonical_bytes(self) -> bytes:
        """RFC 8785 bytes of the full record (no domain prefix); what the store persists."""
        return canonicalize_projection(self.model_dump(mode="json"))

    def content_ref(self) -> str:
        """The record's identity (its ``evidence_ref``): ``sha256(EVALUATION_DOMAIN + canonical_bytes())``."""
        return hashlib.sha256(EVALUATION_DOMAIN + self.canonical_bytes()).hexdigest()


def expires_at_ms(profile: ExecutionProfile, issued_at_ms: int) -> int:
    """When an evaluation issued at ``issued_at_ms`` stops counting: issue time plus the suite's validity."""
    return issued_at_ms + profile.evaluation_suite.validity_seconds * 1_000


def assess_evaluation(
    profile: ExecutionProfile,
    record: EvaluationRecord,
    *,
    issued_at_ms: int,
    invalidated: bool,
    now_ms: int,
) -> QualificationStatus:
    """The status ``record`` gives ``profile`` at ``now_ms``. The first matching rule wins:

    ``invalidated``; ``expired`` (``now_ms`` at or after expiry); ``structurally_invalid``;
    ``insufficient_sample`` (fewer observations than ``min_samples``); ``failed`` (pass rate below
    ``min_pass_bp``, compared in integers, so a rate exactly at the threshold qualifies); otherwise
    ``qualified``.

    Raises:
        TypeError: ``profile_evaluation_type_invalid`` for a wrong argument type.
        ValueError: ``profile_evaluation_profile_mismatch`` when ``record`` is evidence for another profile.
    """
    if (
        type(profile) is not ExecutionProfile
        or type(record) is not EvaluationRecord
        or type(issued_at_ms) is not int
        or type(now_ms) is not int
        or type(invalidated) is not bool
    ):
        raise TypeError("profile_evaluation_type_invalid")
    if record.profile_ref != profile.content_ref():
        raise ValueError("profile_evaluation_profile_mismatch")
    suite = profile.evaluation_suite
    if invalidated:
        return "invalidated"
    if now_ms >= expires_at_ms(profile, issued_at_ms):
        return "expired"
    if not record.structurally_valid:
        return "structurally_invalid"
    if record.sample_size < suite.min_samples:
        return "insufficient_sample"
    if record.pass_count * BASIS_POINTS < suite.min_pass_bp * record.sample_size:
        return "failed"
    return "qualified"


def slot_refusal(slot: WorkerSlot, profile: ExecutionProfile) -> str | None:
    """The first of ``slot``'s declared constraints ``profile`` does not meet, as a stable code, or None.

    Role and task class must be equal; a non-empty ``qualification_ids`` must contain the suite's
    ``qualification_id``; a non-empty ``pinned_profile_refs`` must contain the profile's reference.
    Qualification status is a separate check (``check_slot_qualification``).

    Raises:
        TypeError: ``profile_slot_type_invalid`` for a wrong argument type.
    """
    if type(slot) is not WorkerSlot or type(profile) is not ExecutionProfile:
        raise TypeError("profile_slot_type_invalid")
    if profile.role_id != slot.role_id:
        return "profile_role_mismatch"
    if profile.task_class != slot.task_class:
        return "profile_task_class_mismatch"
    wanted = slot.qualification.qualification_ids
    if wanted and profile.evaluation_suite.qualification_id not in wanted:
        return "profile_qualification_id_mismatch"
    pinned = slot.qualification.pinned_profile_refs
    if pinned and profile.content_ref() not in pinned:
        return "profile_not_pinned"
    return None
