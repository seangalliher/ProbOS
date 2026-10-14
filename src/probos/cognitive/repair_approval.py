"""AD-1299 S2a (#1352): the Captain's approval of one exact repair candidate.

Execute-after-approval (D-B2 N1, ``docs/development/self-maintenance-architecture.md``): no
candidate code runs before the Captain approves its exact candidate digest. This module is the
file side and the check side of that approval, and nothing else:

* ``file_candidate_approval`` files one ``kind="action"`` request in the existing
  ``CapabilityRequestStore`` (tool ``repair``, action ``approve_candidate``) whose params carry the
  candidate digest, the authority class and the campaign id. AD-1213 reserves every ``action``
  request to the Captain (``delegated_approvals.classify_capability_request``). Filing runs nothing.
* ``check_candidate_approval`` (pure) and ``authorize_candidate_execution`` (one durable read, then
  the check) answer one question: is that request the Captain's current approval of exactly this
  candidate, authority class and campaign? An approval expires ``CANDIDATE_APPROVAL_TTL_SECONDS``
  after the Captain's decision. A caller re-checks at every boundary and keeps no cached answer.

The tool id is ``capability_request.REPAIR_TOOL_ID`` on purpose: the decide route issues no
standing rule for a request with that tool id (``routers/capability_requests.py``,
``_maybe_issue_standing_rule``), so an approval never becomes a standing rule. The action differs
from ``REPAIR_ACTION``, so ``capability_request.repair_action`` does not recognise the request and
the decide route does not hand it to the AD-1206 issue fulfiller.

An approval decides; it does not contain. Nothing here runs candidate code, proves that code did
not run, or authenticates the request row: a writer with ProbOS's own OS identity can edit the
request database (D-B2). No delegated, scheduled or autonomous authority exists here (D-B2 option
(a), the working default). Not wired into the runtime: nothing under ``src/`` imports this module
until a later AD-1299 S2 slice admits campaigns.
"""

from __future__ import annotations

import logging
import math
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Final, Protocol

from probos.capability_request import REPAIR_TOOL_ID, CapabilityRequest, validate_action_payload
from probos.cognitive.repair_candidate import (
    AUTHORITY_CLASSES,
    AuthorityClass,
    RepairCandidate,
    is_evidence_ref,
    is_sha256_hex,
)

logger = logging.getLogger(__name__)

CANDIDATE_APPROVAL_TOOL_ID: Final = REPAIR_TOOL_ID
CANDIDATE_APPROVAL_ACTION: Final = "approve_candidate"
# A fixed constant, not configuration: no caller, agent or filed payload can lengthen it.
CANDIDATE_APPROVAL_TTL_SECONDS: Final = 86_400.0
_PARAM_KEYS: Final = frozenset(
    {"candidate_digest", "authority_class", "campaign_id", "base_commit", "candidate_commit", "tree"}
)
_AUTHORIZED: Final = "approval_authorized"
APPROVAL_REASONS: Final[frozenset[str]] = frozenset({
    _AUTHORIZED,
    "approval_not_found",
    "approval_malformed",
    "approval_candidate_mismatch",
    "approval_class_mismatch",
    "approval_campaign_mismatch",
    "approval_pending",
    "approval_denied",
    "approval_not_approved",
    "approval_not_captain",
    "approval_decision_time_invalid",
    "approval_expired",
})


class CandidateApprovalFilingRefused(ValueError):
    """The approval store refused the payload, so no request was filed."""


class ActionRequestFiler(Protocol):
    """The one approval-store write filing needs (``CapabilityRequestStore.file_action_request``)."""

    async def file_action_request(
        self,
        agent_id: str,
        payload: dict[str, Any],
        *,
        rationale: str = "",
        work_item_id: str | None = None,
    ) -> CapabilityRequest | None: ...


class DurableRequestReader(Protocol):
    """The one approval-store read the check needs (``CapabilityRequestStore.get``)."""

    async def get(self, request_id: str, *, durable: bool = False) -> CapabilityRequest | None: ...


@dataclass(frozen=True, slots=True)
class CandidateApprovalCheck:
    """One answer to "is this the Captain's current approval of exactly this candidate?".

    A report, not a token: ``authorized`` holds only for the clock reading it was computed at, so a
    caller re-checks at each boundary instead of keeping it. ``expires_at`` is set exactly when
    ``authorized``. Not evidence completeness: S1b's ``EvidenceCompleteness`` is a separate type.
    """

    reason: str
    request_id: str
    candidate_digest: str
    expires_at: float | None = None

    def __post_init__(self) -> None:
        if (
            type(self.reason) is not str
            or self.reason not in APPROVAL_REASONS
            or not is_evidence_ref(self.request_id)
            or not is_sha256_hex(self.candidate_digest)
            or (self.reason == _AUTHORIZED) != (self.expires_at is not None)
            or (self.expires_at is not None and (type(self.expires_at) is not float or not math.isfinite(self.expires_at)))
        ):
            raise ValueError("candidate_approval_check_invalid")

    @property
    def authorized(self) -> bool:
        """True only for the Captain's approval of this candidate, class and campaign, unexpired when checked."""
        return self.reason == _AUTHORIZED


def _check_arguments(candidate: object, authority_class: object, campaign_id: object) -> None:
    if type(candidate) is not RepairCandidate:
        raise TypeError("repair_candidate_required")
    if type(authority_class) is not str or authority_class not in AUTHORITY_CLASSES:
        raise ValueError("authority_class_invalid")
    if not is_evidence_ref(campaign_id):
        raise ValueError("campaign_id_invalid")


def candidate_approval_payload(
    candidate: RepairCandidate, *, authority_class: AuthorityClass, campaign_id: str,
) -> dict[str, Any]:
    """The six-key action payload asking the Captain to approve exactly ``candidate``.

    ``params`` carry the candidate digest, three of the commit and tree ids it covers (so the
    Captain reads them), the authority class and the campaign id; ``scope_key`` is the campaign id.
    Raises ``TypeError`` for a non-``RepairCandidate`` and ``ValueError`` for an unknown authority
    class or a campaign id that is not an owned-id string.
    """
    _check_arguments(candidate, authority_class, campaign_id)
    return {
        "tool_id": CANDIDATE_APPROVAL_TOOL_ID,
        "action": CANDIDATE_APPROVAL_ACTION,
        "params": {
            "candidate_digest": candidate.digest(),
            "authority_class": authority_class,
            "campaign_id": campaign_id,
            "base_commit": candidate.base_commit,
            "candidate_commit": candidate.candidate_commit,
            "tree": candidate.tree,
        },
        "scope_key": campaign_id,
        "session_id": None,
        "thread_id": "",
    }


def _rationale(digest: str, authority_class: str, campaign_id: str) -> str:
    hours = int(CANDIDATE_APPROVAL_TTL_SECONDS // 3600)
    return (
        f"Approve candidate {digest[:12]} ({authority_class}) for campaign {campaign_id[:24]}. "
        f"Approval authorizes running this exact candidate's code, not promoting it, and expires "
        f"{hours} hours after your decision."
    )


async def file_candidate_approval(
    filer: ActionRequestFiler,
    candidate: RepairCandidate,
    *,
    authority_class: AuthorityClass,
    campaign_id: str,
    agent_id: str,
) -> CapabilityRequest:
    """File the pending request asking the Captain to approve ``candidate``; returns the request.

    Runs nothing and authorizes nothing: the request stays pending until the Captain decides it.
    ``CapabilityRequestStore.file_action_request`` returns an existing pending request with the same
    agent, payload and work item instead of filing a second one. Argument errors raise before the
    store is called (``ValueError`` for an ``agent_id`` that is not an owned-id string, plus those of
    :func:`candidate_approval_payload`); ``CandidateApprovalFilingRefused`` when the store refuses the
    payload; every store exception propagates. A cancelled or failed call leaves the outcome unknown,
    never "nothing filed": the store can commit a queued write after its caller is cancelled, so a
    pending request may exist that the store's cache does not hold, and a retry can then file a second
    request for the same candidate. Each request is decided separately, and neither widens what the
    Captain approved.
    """
    payload = candidate_approval_payload(candidate, authority_class=authority_class, campaign_id=campaign_id)
    if not is_evidence_ref(agent_id):
        raise ValueError("agent_id_invalid")
    filed = await filer.file_action_request(
        agent_id, payload, rationale=_rationale(candidate.digest(), authority_class, campaign_id),
    )
    if filed is None:
        raise CandidateApprovalFilingRefused("candidate_approval_payload_refused")
    logger.info(
        "AD-1299 S2a: approval of candidate %s (%s, campaign %s) requested as %s; its code must not run "
        "until the Captain approves it",
        candidate.digest()[:12], authority_class, campaign_id[:24], str(filed.id)[:12],
    )
    return filed


def _approval_reason(
    candidate: RepairCandidate,
    digest: str,
    request: CapabilityRequest | None,
    request_id: str,
    authority_class: str,
    campaign_id: str,
    now: float,
) -> tuple[str, float | None]:
    # Identity first (which candidate, class and campaign the request is about), then the decision.
    if request is None:
        return "approval_not_found", None
    payload = validate_action_payload(request.payload)
    if (
        type(request.id) is not str
        or request.id != request_id
        or request.kind != "action"
        or type(request.status) is not str
        or type(request.decided_by) is not str
        or payload is None
        or payload["tool_id"] != CANDIDATE_APPROVAL_TOOL_ID
        or payload["action"] != CANDIDATE_APPROVAL_ACTION
        or payload["session_id"] is not None
        or set(payload["params"]) != _PARAM_KEYS
        or any(type(value) is not str for value in payload["params"].values())
    ):
        return "approval_malformed", None
    params = payload["params"]
    if (
        params["candidate_digest"] != digest
        or params["base_commit"] != candidate.base_commit
        or params["candidate_commit"] != candidate.candidate_commit
        or params["tree"] != candidate.tree
    ):
        return "approval_candidate_mismatch", None
    if params["authority_class"] != authority_class:
        return "approval_class_mismatch", None
    if params["campaign_id"] != campaign_id or payload["scope_key"] != campaign_id:
        return "approval_campaign_mismatch", None
    if request.status == "pending":
        return "approval_pending", None
    if request.status == "denied":
        return "approval_denied", None
    if request.status != "approved":
        return "approval_not_approved", None
    if request.decided_by != "captain":
        return "approval_not_captain", None
    decided_at = request.decided_at
    if type(decided_at) not in (int, float) or not math.isfinite(decided_at) or decided_at > now:
        return "approval_decision_time_invalid", None
    expires_at = float(decided_at) + CANDIDATE_APPROVAL_TTL_SECONDS
    if now >= expires_at:
        return "approval_expired", None
    return _AUTHORIZED, expires_at


def check_candidate_approval(
    candidate: RepairCandidate,
    request: CapabilityRequest | None,
    *,
    request_id: str,
    authority_class: AuthorityClass,
    campaign_id: str,
    now: float,
) -> CandidateApprovalCheck:
    """Is ``request`` the Captain's unexpired approval of exactly ``candidate``, class and campaign at ``now``?

    Pure. Reasons are checked in a fixed order, identity before decision: ``approval_not_found``
    (``request`` is ``None``), ``approval_malformed`` (another id, kind, tool, action or param set, a
    session id, or a non-string param, id, status or decider), ``approval_candidate_mismatch``,
    ``approval_class_mismatch``, ``approval_campaign_mismatch`` (params or scope key), then
    ``approval_pending``, ``approval_denied``, ``approval_not_approved`` (any other status),
    ``approval_not_captain`` (``decided_by`` other than ``"captain"``),
    ``approval_decision_time_invalid`` (``decided_at`` absent, not a finite real, or later than
    ``now``) and ``approval_expired`` (``now`` at or after ``decided_at`` plus the TTL). Raises
    ``TypeError`` for a non-``RepairCandidate`` candidate or a ``request`` that is neither ``None``
    nor a ``CapabilityRequest``, and ``ValueError`` for an unknown class, a campaign or request id
    that is not an owned-id string, or a ``now`` that is not a finite real. Not covered: an ``int`` too
    large to convert to a float, as ``now`` or as ``decided_at``, raises ``OverflowError`` from the
    finiteness test instead of the documented ``ValueError`` or ``approval_decision_time_invalid``, and
    a ``request`` whose ``kind`` is an object that merely compares equal to ``"action"`` is read as an
    action. Both need an in-memory object built to do so: a stored row yields a ``str`` kind and a
    float ``decided_at``.
    """
    _check_arguments(candidate, authority_class, campaign_id)
    if not is_evidence_ref(request_id):
        raise ValueError("approval_request_id_invalid")
    if type(now) not in (int, float) or not math.isfinite(now):
        raise ValueError("approval_clock_invalid")
    if request is not None and type(request) is not CapabilityRequest:
        raise TypeError("capability_request_required")
    digest = candidate.digest()
    reason, expires_at = _approval_reason(
        candidate, digest, request, request_id, authority_class, campaign_id, float(now),
    )
    return CandidateApprovalCheck(reason, request_id, digest, expires_at)


async def authorize_candidate_execution(
    reader: DurableRequestReader,
    candidate: RepairCandidate,
    *,
    request_id: str,
    authority_class: AuthorityClass,
    campaign_id: str,
    clock: Callable[[], float] = time.time,
) -> CandidateApprovalCheck:
    """Read ``request_id`` once with ``durable=True``, then :func:`check_candidate_approval` at a clock read taken after it.

    ``CapabilityRequestStore.get(..., durable=True)`` reads committed rows on a separate connection
    and returns ``None`` both for an unknown id and for a store with no durable database, so
    ``approval_not_found`` covers both and claims neither. The clock is read after the read, so a
    slow read cannot pull ``now`` back inside the approval's window. Argument errors raise before
    the read. Every reader exception propagates, ``CancelledError`` included: an approval that was
    not read is never authorized. Nothing is written. A clock that does not return a finite real
    raises ``ValueError`` after the read.
    """
    _check_arguments(candidate, authority_class, campaign_id)
    if not is_evidence_ref(request_id):
        raise ValueError("approval_request_id_invalid")
    request = await reader.get(request_id, durable=True)
    check = check_candidate_approval(
        candidate, request, request_id=request_id, authority_class=authority_class,
        campaign_id=campaign_id, now=clock(),
    )
    if not check.authorized:
        logger.info(
            "AD-1299 S2a: candidate %s is not authorized in campaign %s (%s, request %s); its code must not "
            "run until the Captain approves this exact candidate",
            check.candidate_digest[:12], campaign_id[:24], check.reason, request_id[:12],
        )
    return check
