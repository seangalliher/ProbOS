"""AD-1287 S2b: record a qualified profile's live skill and tool drift as S1 invalidations.

``record_component_drift`` reads a profile's qualification. Only when the status is ``qualified`` does it ask a
``ProfileComponentSource`` (S2a) for drift through ``profile_drift``. Each drift whose live state was read --
``RECORDED_DRIFT_CODES``: a skill whose resources digest differently, a skill that fails ``validate_skill``, a tool
whose schemas digest differently -- is recorded through ``invalidate_profile`` with its code as the reason. So
``get_qualification`` reports ``invalidated`` until a new evaluation is recorded. A missing or unreadable component is
logged at INFO and not recorded: an absent catalog or registry entry, or a failed read, can be transient, and an
invalidation is durable. The slot boundary (``admit_current_qualified_attempt``) still refuses both at admission.

The invalidation id binds the profile, the deciding evaluation's evidence reference and the drift's kind, key, code
and live digest. A replay or a concurrent recorder holding the same evaluation gets the same id, and the store
answers the row it already holds; the same drift seen after a requalification is recorded again, against the new
evaluation.

Checked and recorded: skills and tool schemas, as S2a checks them. Not checked or recorded (declared only): the
model, the policy, prompts, tool implementation digests and the evaluation suite. The record holds as of its own
reads: the qualification read, the component reads and each write are separate operations. A newly inserted
invalidation applies to every evaluation recorded before it, including one recorded between the reads and the write;
an id the store already holds answers its existing row, which applies only to the evaluations recorded before that
row, so a duplicate replay does not invalidate a later evaluation. If a write raises, the drifts recorded before it
stay recorded; a rerun then finds the profile ``invalidated`` and records nothing more, and the slot boundary refuses
the profile until a new evaluation is recorded. Nothing here grants anything, and nothing calls it: no sweeper is wired.
"""

from __future__ import annotations

import hashlib
import logging
from typing import Final, Protocol

from probos.cognitive.elastic_team import canonicalize_projection, is_sha256_ref
from probos.cognitive.profile_currency import ComponentDrift, ProfileComponentSource, profile_drift
from probos.cognitive.profile_qualification_store import (
    ProfileQualification,
    ProfileQualificationConflict,
    RecordedInvalidation,
)

logger = logging.getLogger(__name__)

DRIFT_INVALIDATION_DOMAIN: Final = b"probos.execution_profile/drift_invalidation/v1\x00"
RECORDED_DRIFT_CODES: Final = frozenset(
    {
        "component_drift_skill",
        "component_structurally_invalid_skill",
        "component_drift_tool_schema",
    }
)


class DriftInvalidationStore(Protocol):
    """The two ``ProfileQualificationStore`` operations the recorder uses; ``ProfileQualificationStore`` satisfies it."""

    async def get_qualification(self, profile_ref: str) -> ProfileQualification | None: ...

    async def invalidate_profile(
        self, profile_ref: str, invalidation_id: str, reason_code: str,
    ) -> RecordedInvalidation: ...


def drift_invalidation_id(profile_ref: str, evidence_ref: str, drift: ComponentDrift) -> str:
    """The invalidation id for ``drift`` of ``profile_ref`` observed against the evaluation ``evidence_ref``.

    ``drift-`` followed by the sha256 hex of ``DRIFT_INVALIDATION_DOMAIN`` plus the RFC 8785 bytes of the profile
    reference, the evidence reference and the drift's kind, key, code and live digest: 70 characters.

    Raises:
        TypeError: ``drift_invalidation_input_invalid`` when either reference is not a 64-hex digest, ``drift`` is
            not exactly a ``ComponentDrift``, or its live digest is not a 64-hex digest (an exact ``ComponentDrift``
            built without its fields raises ``AttributeError`` instead).
    """
    if (
        not is_sha256_ref(profile_ref)
        or not is_sha256_ref(evidence_ref)
        or type(drift) is not ComponentDrift
        or not is_sha256_ref(drift.live)
    ):
        raise TypeError("drift_invalidation_input_invalid")
    material = {
        "code": drift.code,
        "evidence_ref": evidence_ref,
        "key": drift.key,
        "kind": drift.kind,
        "live": drift.live,
        "profile_ref": profile_ref,
    }
    digest = hashlib.sha256(DRIFT_INVALIDATION_DOMAIN + canonicalize_projection(material)).hexdigest()
    return f"drift-{digest}"


async def record_component_drift(
    store: DriftInvalidationStore, source: ProfileComponentSource, profile_ref: str,
) -> tuple[RecordedInvalidation, ...]:
    """Record each live skill or tool drift of a qualified profile as an S1 invalidation; the records in drift order.

    Reads ``store.get_qualification(profile_ref)``. Unless its status is ``qualified`` with a deciding evaluation, it
    returns an empty tuple, asks ``source`` nothing and writes nothing. Otherwise it runs ``profile_drift``, records
    each drift whose code is in ``RECORDED_DRIFT_CODES`` through ``store.invalidate_profile`` (id
    ``drift_invalidation_id`` over the deciding evaluation, reason the drift's code), and logs each other drift at
    INFO without recording it. Returns what the store answered for each recorded drift; an id the store already
    holds answers its existing row.

    Raises:
        ValueError: ``execution_profile_ref_invalid`` for a malformed reference, before the store is asked;
            ``profile_evidence_mismatch`` when the store answers for another profile (nothing is written).
        ProfileQualificationConflict: ``profile_unknown`` when the store holds no such profile.
        What ``profile_drift`` or ``store.invalidate_profile`` raises, unchanged. Drifts recorded before a write
        that raises stay recorded, and a rerun then finds the profile ``invalidated`` and records nothing more.
    """
    if not is_sha256_ref(profile_ref):
        raise ValueError("execution_profile_ref_invalid")
    qualification = await store.get_qualification(profile_ref)
    if qualification is None:
        raise ProfileQualificationConflict("profile_unknown")
    if qualification.profile_ref != profile_ref or qualification.profile.content_ref() != profile_ref:
        raise ValueError("profile_evidence_mismatch")
    if qualification.status != "qualified" or qualification.deciding is None:
        return ()
    evidence_ref = qualification.deciding.evidence_ref
    recorded: list[RecordedInvalidation] = []
    for drift in await profile_drift(qualification.profile, source):
        if drift.code not in RECORDED_DRIFT_CODES:
            logger.info(
                "AD-1287: %s %s of execution profile %s is %s; not recorded as an invalidation (it may be "
                "transient), and the slot boundary still refuses the profile",
                drift.kind,
                drift.key,
                profile_ref,
                drift.code,
            )
            continue
        invalidation_id = drift_invalidation_id(profile_ref, evidence_ref, drift)
        recorded.append(await store.invalidate_profile(profile_ref, invalidation_id, drift.code))
    return tuple(recorded)
