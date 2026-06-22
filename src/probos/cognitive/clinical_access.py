"""AD-903: clinical trend read access resolution (pure, no I/O).

The clinical indicator surface (trust / cognitive-zone / self-similarity /
hebbian-drift / duty trends, and — under AD-904 — clinical notes) is a
**CONFIDENTIAL** read. This module is the single deny-by-default authority that
decides whether a caller may read one crewman's clinical indicators.

Naval grounding: minimum-necessary / need-to-know disclosure of a service
member's behavioral-health information (DoDI 6490.08 — *Command Notification
Requirements to Dispel Stigma*, which limits disclosure to the minimum
necessary and to those with a genuine need to know). The Counselor (the ship's
behavioral-health authority) and the Captain have standing need-to-know; any
other crew member needs an explicit, time-limited, Captain-issued grant. A
crewman never reads their own clinical record (the subject-denied rung) — the
assessment is a professional opinion *about* them, not a self-service field.

Design — MIRRORS ``federation/ard/access.py`` (AD-1048): a pure,
exhaustively-unit-testable deny-default ladder (``resolve_clinical_access``)
plus a thin store-backed convenience (``clinical_access_for_caller``) that reads
the AD-622 ``ClearanceGrantStore`` and **FAILS CLOSED** — any error in
resolution denies. The need-to-know grant reuses the existing AD-622
``ClearanceGrant.scope`` field (``clinical:{target}`` or the wildcard
``clinical:*``); NO ClearanceGrant extension is required.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from probos.earned_agency import resolve_active_grants

logger = logging.getLogger(__name__)


# Agent types with standing clinical-read authority (in addition to the
# Captain). DELIBERATELY a FRESH frozenset — distinct from AD-635's
# ``clinical_telemetry.CLINICAL_ROLES`` ({diagnostician, counselor}). The
# diagnostician handles medical telemetry; only the counselor reads the
# behavioral-health clinical-notes surface (Captain + counselor ratified).
CLINICAL_READ_ROLES: frozenset[str] = frozenset({"counselor"})


def clinical_grant_scope(target_agent_id: str) -> str:
    """The AD-622 ``ClearanceGrant.scope`` value that authorizes clinical reads.

    A Captain issues the grant to the would-be reader (e.g. a Department Chief)
    with ``target_agent_id=<reader>`` and ``scope=clinical:{crewman}``. The
    wildcard ``clinical:*`` authorizes reading any crewman's clinical record.
    """
    return f"clinical:{target_agent_id}"


@dataclass(frozen=True)
class ClinicalAccessDecision:
    """Outcome of a clinical-read authorization check.

    ``source`` is one of ``{"captain", "subject_denied", "counselor_role",
    "grant", "default", "error"}`` — a stable audit/diagnostic label for which
    rung of the ladder decided (or that resolution failed closed).
    """

    allowed: bool
    source: str
    reason: str = ""


def _has_clinical_grant(grants: Sequence[Any], target_agent_id: str) -> bool:
    """True if any non-revoked grant authorizes reading ``target_agent_id``.

    Direct attribute access (``.revoked`` / ``.scope``) on the AD-622
    ``ClearanceGrant`` is intentional: a malformed grant object raises here and
    the ``clinical_access_for_caller`` fail-closed guard converts that to a
    deny, rather than silently treating it as "no grant".
    """
    wanted = clinical_grant_scope(target_agent_id)
    for grant in grants:
        if grant.revoked:
            continue
        if grant.scope == wanted or grant.scope == "clinical:*":
            return True
    return False


def resolve_clinical_access(
    *,
    caller_agent_id: str,
    caller_agent_type: str,
    target_agent_id: str,
    is_captain: bool,
    active_grants: Sequence[Any] = (),
) -> ClinicalAccessDecision:
    """Pure deny-by-default ladder (first match wins).

    1. ``is_captain``                              → allow ``"captain"``
    2. caller is the subject (non-captain)         → DENY  ``"subject_denied"``
    3. caller type in ``CLINICAL_READ_ROLES``      → allow ``"counselor_role"``
    4. an active clinical grant covers the target  → allow ``"grant"``
    5. (nothing)                                   → DENY  ``"default"``

    Rung 2 precedes rung 3 deliberately: a counselor reading *their own*
    clinical record is still denied (the subject never self-reads), so the
    subject check must outrank the role check.
    """
    if is_captain:
        return ClinicalAccessDecision(allowed=True, source="captain")
    if caller_agent_id and caller_agent_id == target_agent_id:
        return ClinicalAccessDecision(
            allowed=False,
            source="subject_denied",
            reason="a crewman cannot read their own clinical record",
        )
    if caller_agent_type in CLINICAL_READ_ROLES:
        return ClinicalAccessDecision(allowed=True, source="counselor_role")
    if _has_clinical_grant(active_grants, target_agent_id):
        return ClinicalAccessDecision(allowed=True, source="grant")
    return ClinicalAccessDecision(
        allowed=False,
        source="default",
        reason="no clinical-read authority (need-to-know)",
    )


def clinical_access_for_caller(
    *,
    caller_agent_id: str,
    caller_agent_type: str,
    target_agent_id: str,
    is_captain: bool,
    grant_store: Any = None,
) -> ClinicalAccessDecision:
    """Store-backed convenience: read active grants then resolve. FAILS CLOSED.

    Reads ``resolve_active_grants(caller_agent_id, grant_store)`` (AD-622, sync
    cache read) when the caller is not the Captain, then folds via
    ``resolve_clinical_access``. The whole resolution is wrapped: ANY error
    (store raising, a malformed grant, an unexpected input) DENIES with
    ``source="error"`` — a CONFIDENTIAL gate must never fail open.
    """
    try:
        active_grants: Sequence[Any] = ()
        if not is_captain and caller_agent_id:
            active_grants = resolve_active_grants(caller_agent_id, grant_store)
        return resolve_clinical_access(
            caller_agent_id=caller_agent_id,
            caller_agent_type=caller_agent_type,
            target_agent_id=target_agent_id,
            is_captain=is_captain,
            active_grants=active_grants,
        )
    except Exception:
        logger.error(
            "AD-903: clinical access resolution failed for caller=%s target=%s; "
            "FAIL-CLOSED deny",
            caller_agent_id,
            target_agent_id,
            exc_info=True,
        )
        return ClinicalAccessDecision(
            allowed=False, source="error", reason="resolution_failed"
        )
