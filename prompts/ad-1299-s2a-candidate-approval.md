# AD-1299 S2a (#1352): the Captain's approval of one exact repair candidate

**Drafted by:** `claude-architect` (Claude Code, Opus 5.5), 2026-10-14

**One line.** Build the Captain's approval of one exact candidate on the existing approval surface: one module that files an action-shaped `CapabilityRequestStore` request bound to the candidate digest, authority class and campaign; that the Captain decides on the existing decide route; and that a pure check and a durable-read authorizer turn into "authorized" only for the Captain's own decision, unexpired, for exactly that candidate, class and campaign. Built and runtime-unwired, with one test crossing filer -> real store -> real decide route -> restart -> authorizer.

| | |
|---|---|
| Status | Build-ready (split workflow: the Copilot orchestrator executes Section 1 mechanically, then Builders write tests only). |
| Epic / AD | #1352 / AD-1299 slice S2a. **No new AD or BF number**: S2 is an already-versioned slice of AD-1299 (`docs/development/self-maintenance-architecture.md:469-476`). |
| Base | `origin/main` `cff84495` (tree `ee9e4e686855fc877a5a60ff93b2722b5f3b92bb`), branch `feat/ad1299-s2-20261014-cff84495` |
| Depends on | S1a (PR #1508) and S1b (PR #1519), shipped. Reads `RepairCandidate`, `AUTHORITY_CLASSES`, `is_evidence_ref`, `is_sha256_hex`; changes neither module. |
| D-B2 | Option (a), execute-after-approval. Nothing here is delegated, scheduled or autonomous, and nothing claims containment. |
| Estimated tests | M1 ~30 functions (~60 collected), M2 ~8 functions |
| Milestones | M0 orchestrator applies Section 1; M1 pure/fake tests (high); M2 chain tests + mutation campaign of record (max); M3 trackers (medium) |

---

## Problem

1. **No approval binder.** S1 names "verification of ... the Captain approval against one candidate" (`logs/architect/issue-1352.md:175`), and S1b defers it: "S2 adds `captain_approval` to every class when its binder exists" (`src/probos/cognitive/repair_candidate.py:101-102`). Nothing files or checks such an approval (Absence Verified #3).
2. **The approval surface has no expiry and no candidate binding.** `CapabilityRequest` has no expiry field and the table has no expiry column (`src/probos/capability_request.py:89-104`, `:508-527`; Absence #4). The only action-shaped repair request today is the AD-1172 `dispatch` ask, which files a GitHub issue (`src/probos/cognitive/repair_dispatch.py:285-317`, `src/probos/capability_request.py:115-147`). N1 (`docs/development/self-maintenance-architecture.md:390-393`) requires an approval of an exact candidate digest, expiring and re-checked at each boundary (`logs/architect/issue-1352.md:112`).
3. **Every later S2 step needs it.** Admission, change approval and promotion are each "the Captain's decision on an action-shaped `CapabilityRequestStore` request ... bound to the candidate digest, expiring, re-checked at each boundary" (`logs/architect/issue-1352.md:112`). S2a builds the candidate-bound form; admission (no candidate yet) reuses the shape in S2e.

## Slicing S2 (ranked) and the choice

S2 as written spans an agent, three grant classes, a fault-store guard, admission and a default-off switch. Ranked on correctness, safety, compatibility, architectural fit, reversibility and validation cost, with the no-half-chain rule:

| Rank | First cut | Verdict |
|---|---|---|
| 1 | **Candidate approval** (this prompt): filer + pure check + durable authorizer, crossing the real store and the real decide route. | **Chosen.** Every later S2 step depends on it; producer and consumer both in-slice; no runtime wiring, config, event, route, agent or S1 change; rollback is one file. |
| 2 | `FaultReportStore.resolve` expected-state guard first. | Second (becomes S2c). Small, but its only production caller `verify_and_close` has no production caller (Absence #1, #2), so it guards a path nothing reaches today. |
| 3 | Campaign admission first (CrewSession parent WorkItem, ledger wiring, C12). | Third (S2e). Admission is itself a Captain step, so it needs this binder; it also touches `crew_session.py`/`workforce.py`, each over 5,000 lines. |
| 4 | Utility agent first. | Last (S2f). An agent with no governed step to call is a half-chain, and agent/pool registration churns registry pins. |

**Later slices** (each leaves the next one runnable):

- **S2b stays reserved** for delegated repair and scheduled maintenance grants, only if the Captain chooses D-B2 (b) or (c) (`docs/development/self-maintenance-architecture.md:421-422`; `logs/architect/issue-1352.md:261-262`). In-envelope slices therefore skip the letter.
- **S2c, fault resolution guard:** an expected-state compare-and-set on `FaultReportStore.resolve` (`src/probos/fault_report.py:909-941`), consumed by `verify_and_close` (`src/probos/cognitive/repair_verification.py:266`). Blind spot to settle there: `resolve` mutates the cached report before persisting and log-and-degrades a failed write (`fault_report.py:922-939`), the shape BF-722 removed from `CapabilityRequestStore.decide` (`capability_request.py:959-968`).
- **S2d, approval joins completion:** add `captain_approval` to `REQUIRED_EVIDENCE_KINDS` with a link derived from S2a's check; widen the ledger kind CHECK (`repair_evidence_store.py:76`, `:89`); migrate the S1a/S1b pins (Hidden pins, below). Decides whether expiry is judged at completion or at the gate run.
- **S2e, campaign admission:** an `admit_campaign` approval (no candidate digest yet), the CrewSession parent WorkItem as campaign id, construction and start of the ledger with a ledger identity recorded at admission (C12), a fresh evidence reference per gate run, D4a handling, and C10's first half.
- **S2f, Utility agent:** instructions-first perceive -> decide -> act -> report over S2a/S2e. Name check: `EngineeringMaintenanceAgent` is free as a class name, but pool `engineering_maintenance` and agent type `maintenance` belong to AD-457's `MaintenanceAgent` (`src/probos/startup/agent_fleet.py:281`, `src/probos/agents/engineering/maintenance.py:24`, `:47`); S2f must pick another pool and type. Also S2f: the HXI card says "Only this repair request is authorized" for every `tool_id === 'repair'` request (`ui/src/components/capability/CapabilityRequestCard.tsx:136`), which reads oddly for a maintenance or enhancement candidate.

## Solution overview

| Piece | Where | Pure? |
|---|---|---|
| Constants: tool `repair` (= `REPAIR_TOOL_ID`), action `approve_candidate`, TTL 86,400 s, `APPROVAL_REASONS` | `src/probos/cognitive/repair_approval.py` (new) | data |
| `candidate_approval_payload` (the six-key action payload) | same | yes |
| `file_candidate_approval` (files through a narrow `ActionRequestFiler` protocol) | same | no (one store call) |
| `CandidateApprovalCheck`, `check_candidate_approval` | same | yes |
| `authorize_candidate_execution` (one durable read through `DurableRequestReader`, then the check) | same | no (one read) |

**Runtime wiring: none.** No config, EventType, route, store, agent, UI or S1 change. The decide route already handles the request: it issues no standing rule for tool `repair` (`src/probos/routers/capability_requests.py:579-585`), finds no fulfiller for `kind="action"` other than the repair `dispatch` shape (`:451-472`), and `decide_capability_request` owns the pending-only guard (`:167-191`).

---

## Decisions and ranked options

All chosen options are in the Delegated AD Execution envelope: each adds a control or keeps one, changes no persisted schema or public API, and rolls back by deleting one file.

### D1. Request shape

| Rank | Option | Verdict |
|---|---|---|
| 1 | `kind="action"`, `tool_id=REPAIR_TOOL_ID` (`"repair"`), `action="approve_candidate"`, params `{candidate_digest, authority_class, campaign_id, base_commit, candidate_commit, tree}` (all strings), `scope_key=campaign_id`, `session_id=None`, `thread_id=""`. | **Chosen.** The `repair` tool id is the existing exclusion from standing rules on the route (`routers/capability_requests.py:579`) and in the HXI (`ui/src/store/capabilityApprovals.ts:125-128`); `approve_candidate` is not `dispatch`, so `repair_action` returns `None` (`capability_request.py:132-138`) and no fulfiller runs (`routers/capability_requests.py:451`). AD-1213 classifies every `action` as `CAPTAIN_RESERVED` (`delegated_approvals.py:171-172`). |
| 2 | A new tool id such as `self_maintenance`. | Rejected: becomes standing-rule-eligible in the route and the HXI; today only AD-1321's work-item check (`routers/capability_requests.py:625-634`) would block it. |
| 3 | A new request kind. | Rejected: changes the `RequestKind` literal, the decide route, AD-1213 classification and the UI. |

The commit and tree params repeat what the digest covers so the Captain can read them; the check refuses any disagreement.

### D2. Expiry

| Rank | Option | Verdict |
|---|---|---|
| 1 | Fixed module constant `CANDIDATE_APPROVAL_TTL_SECONDS = 86_400.0`, measured from `decided_at`; expired when `now >= decided_at + TTL`. | **Chosen.** No caller, agent or payload can lengthen it; the rationale tells the Captain the window. |
| 2 | A TTL carried in params. | Rejected: the filing agent would choose its own authority window. |
| 3 | A Pydantic config field. | Rejected: a new knob, and it churns the config reference, profile and facade baselines. Can be added later if the Captain wants it. |
| 4 | An `expires_at` column on `capability_requests`. | Rejected: persisted-schema change for one consumer. |

### D3. Result type: authority is not evidence

| Rank | Option | Verdict |
|---|---|---|
| 1 | Own frozen type `CandidateApprovalCheck(reason, request_id, candidate_digest, expires_at)`; `authorized` iff `reason == "approval_authorized"`; `expires_at` set exactly when authorized. | **Chosen.** Keeps authority apart from evidence completeness, and leaves S1a/S1b untouched. |
| 2 | Return an `EvidenceLink(kind="captain_approval")` now and add the kind to C9. | Deferred to S2d: it widens `EvidenceKind`, `REASON_CODES` and the ledger CHECK and rewrites about 56 pinned S1a/S1b assertions (Hidden pins). |

### D4. Check order and failure tiers

Identity before decision, fixed order: `approval_not_found` -> `approval_malformed` -> `approval_candidate_mismatch` -> `approval_class_mismatch` -> `approval_campaign_mismatch` -> `approval_pending` -> `approval_denied` -> `approval_not_approved` -> `approval_not_captain` -> `approval_decision_time_invalid` -> `approval_expired` -> `approval_authorized`.

| Condition | Tier | Behaviour |
|---|---|---|
| Wrong argument type/shape (candidate, class, campaign id, request id, agent id, `now`, a non-`CapabilityRequest` request) | Propagate | `TypeError`/`ValueError` with a stable code, before any store call |
| Store refuses the payload on filing | Propagate | `CandidateApprovalFilingRefused` (a `ValueError`) |
| Reader or filer raises, `CancelledError` included | Propagate | Unchanged; an approval that was not read is never authorized |
| Every evidence condition above | Return | A `CandidateApprovalCheck`; the authorizer logs non-authorized outcomes at INFO |

The authorizer reads the clock **after** the durable read, so a slow read cannot pull `now` back inside the window. `get(..., durable=True)` returns `None` for an unknown id and for a store with no durable database (`capability_request.py:1130-1132`), so `approval_not_found` covers both and claims neither.

### D5. Wiring and the autonomy switch

| Rank | Option | Verdict |
|---|---|---|
| 1 | Runtime-unwired module; the in-slice consumer is `authorize_candidate_execution`, crossed end to end by M2. **No delegated, scheduled or autonomous admission flag** in this or any S2 slice under D-B2 (a). | **Chosen.** A switch that exists only to be turned on later is a control nobody has chosen. "Default-disabled autonomous admission" is met by its absence, pinned by the `captain`-only decider check, the `CAPTAIN_RESERVED` classification and the no-standing-rule test. A flag lands with S2b only if the Captain chooses (b) or (c). |
| 2 | Add `self_maintenance.autonomous_admission: bool = False` now. | Rejected: dead config, three baseline regenerations, and a future reader would assume something honours it. |

### D6. Re-asking after a denial

| Rank | Option | Verdict |
|---|---|---|
| 1 | The store's pending-only dedup (`capability_request.py:818-828`); a filing after a decision files a new ask. | **Chosen for S2a.** What a denial means for a campaign (end it, or require a new candidate) belongs to the campaign owner, S2e. |
| 2 | Refuse to re-file a candidate that has a denied request (the AD-1268 "a decision is a standing answer" rule). | Deferred to S2e, with the campaign record. |

## Constraints carried forward: disposition in S2a

| Constraint | S2a |
|---|---|
| AD-1213 / Captain-per-step | Built: `decided_by == "captain"` required; `kind="action"` is `CAPTAIN_RESERVED` (M2 pins it). |
| N1, execute-after-approval | The check S3's runner will call. S2a runs no candidate code. |
| Expiring, re-checked at each boundary | Built: fixed TTL; a fresh durable read per call; the result is documented as non-cacheable. |
| Completion is not authority | Kept: separate type; `EvidenceCompleteness` untouched. |
| C12 (ledger reset) and fresh reference per gate run | Not touched: S2a records nothing in the ledger. S2e. |
| D4a | Not applicable: the authorizer only reads; a cancelled call recorded nothing here. S2e must apply D4a when it calls `assess_candidate_evidence`. |
| C10 | Neither half here. The candidate digest covers `base_commit` (`repair_candidate.py:169-185`), so an approved digest fixes the base; equality with the base approved at admission is S2e; descent from the active release is S4. |
| Never route through `merge_to_main`/`remove` or `routers/build.py` | Not touched. |
| Design Principle #13c | The filed request is itself the escalation: it appears in the Captain's approval queue. Every non-authorized check names its reason for the caller to escalate. |

---

## Implementation

### Section 0 -- Event Types

None. S2a adds no `EventType`. Filing and deciding emit the existing `CAPABILITY_REQUEST_FILED` and `CAPABILITY_REQUEST_DECIDED` (`capability_request.py:766-772`, `:1023-1030`); `CapabilityGapDriver` ignores a request without `work_item_id` (`src/probos/cognitive/capability_gap_driver.py:255-259`), and S2a files none.

### Section 1 -- NEW `src/probos/cognitive/repair_approval.py`

```python
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
```

### Section 2 -- EDIT `DECISIONS.md` (M3 only)

```text
<<<<<<< SEARCH
*Named constraint C12 (S2).* The ledger detects a change only per reference the consumer re-presents, and only while the file exists: deleting `repair_evidence.db` makes `start()` create an empty ledger and the first digests vanish without a signal. This detects nothing and is not prevented; S2 must decide how a recreated ledger is detected (for example a ledger identity recorded at campaign admission), and must derive a fresh reference per gate run.
=======
*Named constraint C12 (S2).* The ledger detects a change only per reference the consumer re-presents, and only while the file exists: deleting `repair_evidence.db` makes `start()` create an empty ledger and the first digests vanish without a signal. This detects nothing and is not prevented; S2 must decide how a recreated ledger is detected (for example a ledger identity recorded at campaign admission), and must derive a fresh reference per gate run.

**S2a (2026-10-14).** The Captain's approval of one exact candidate: filed on the existing approval surface, decided on the existing decide route, and checked by one durable read with a fixed expiry; built and unwired (nothing under `src/` imports `probos.cognitive.repair_approval`); contract `prompts/ad-1299-s2a-candidate-approval.md`; no new AD or BF number. Decisions, one line each:

- *E1 (slicing).* S2 is cut into S2a (this), S2c (an expected-state guard on `FaultReportStore.resolve`), S2d (`captain_approval` joins C9, derived from S2a's check), S2e (campaign admission: CrewSession parent WorkItem, an admission approval, ledger wiring with a ledger identity for C12 and a fresh reference per gate run, C10's first half) and S2f (the Utility agent). S2b stays reserved for delegated and scheduled grants under D-B2 (b) or (c).
- *E2 (request shape).* `kind="action"`, tool `repair` (`REPAIR_TOOL_ID`, which the decide route and the HXI already exclude from standing rules), action `approve_candidate` (not `dispatch`, so `repair_action` ignores it and no fulfiller runs); params carry the candidate digest, class, campaign id, base and candidate commits and tree; the scope key is the campaign id. AD-1213 reserves every action to the Captain.
- *E3 (expiry).* A fixed 24-hour TTL from the Captain's `decided_at`, a module constant rather than configuration, so no caller or payload can lengthen it; the request schema is not changed.
- *E4 (check).* A fixed reason order, identity before decision; authorized only for `approved` by `captain` with a finite `decided_at` not later than now, and now before expiry; the clock is read after one durable read; reader errors propagate; `approval_not_found` covers an unknown id and a store with no durable database alike.
- *E5 (authority is not evidence).* The check returns its own type, not an `EvidenceLink`; S1a and S1b are unchanged; S2d decides how `captain_approval` enters completion.
- *E6 (no autonomy switch).* No delegated, scheduled or autonomous admission flag is added in any S2 slice under D-B2 (a): a switch that exists only to be turned on later is a control nobody has chosen. "Default-disabled autonomous admission" is met by its absence, pinned by the `captain`-only decider, the `CAPTAIN_RESERVED` classification and the no-standing-rule test.
- *E7 (carried, not built).* C12, D4a and the ledger are untouched (S2e). C10's first half (candidate base equals the admitted base) is S2e: the candidate digest already fixes `base_commit`, but the approved base is recorded at admission. Its second half (descends from the active release) is S4.
>>>>>>> REPLACE
```

### Section 3 -- EDIT `PROGRESS.md` (M3 only)

```text
<<<<<<< SEARCH
**AD-1299 slice S1b BUILT (2026-10-12), #1352, built and unwired -- nothing under `src/` constructs the store; no new AD or BF number.**
=======
**AD-1299 slice S2a BUILT (2026-10-14), #1352, built and unwired -- nothing under `src/` imports `probos.cognitive.repair_approval`; no new AD or BF number.** It adds `file_candidate_approval` (one `kind="action"` request on the existing approval surface: tool `repair`, action `approve_candidate`, bound to the candidate digest, authority class and campaign id), the pure `check_candidate_approval` and the durable-read `authorize_candidate_execution` (authorized only for the Captain's own approval of exactly that candidate, class and campaign, for 24 hours from the decision); files `src/probos/cognitive/repair_approval.py`, `tests/test_ad1299_s2a_candidate_approval.py` and `tests/test_ad1299_s2a_approval_chain.py`, whose chain test crosses the real store, the real decide route, a restart and changed inputs. No config, event, route, store, agent, UI or S1 change. See DECISIONS.md AD-1299, "S2a (2026-10-14)".

**AD-1299 slice S1b BUILT (2026-10-12), #1352, built and unwired -- nothing under `src/` constructs the store; no new AD or BF number.**
>>>>>>> REPLACE
```

### Section 4 -- EDIT `docs/development/self-maintenance-architecture.md` (M3 only)

```text
<<<<<<< SEARCH
  must preserve the existing runtime.
=======
  must preserve the existing runtime. **S2a** (the Captain's approval of one
  exact candidate, filed on the existing approval surface and checked by one
  durable read with a 24-hour expiry; built, runtime-unwired):
  [prompts/ad-1299-s2a-candidate-approval.md](../../prompts/ad-1299-s2a-candidate-approval.md).
  Later in-envelope slices are S2c to S2f; S2b stays reserved for delegated
  and scheduled grants under D-B2 (b) or (c).
>>>>>>> REPLACE
```

### Section 5 -- EDIT `docs/development/roadmap.md` (M3 only)

```text
<<<<<<< SEARCH
S1b (`prompts/ad-1299-s1b-evidence-completion-ledger.md`: C8, C9 and a first-trusted-digest evidence ledger, built and runtime-unwired).
=======
S1b (`prompts/ad-1299-s1b-evidence-completion-ledger.md`: C8, C9 and a first-trusted-digest evidence ledger, built and runtime-unwired). S2a (`prompts/ad-1299-s2a-candidate-approval.md`: the Captain's approval of one exact candidate, built and runtime-unwired).
>>>>>>> REPLACE
```

After Sections 2-5: `d:/ProbOS/.venv/Scripts/python.exe scripts/gen_ad_ledger.py` (rewrites `docs/development/ad-ledger-snapshot.json` and `docs/development/open-ads-report.md`), then `d:/ProbOS/.venv/Scripts/python.exe scripts/gen_ad_ledger.py --check` (what `tests/test_ad1184_ad_ledger.py` runs). Precedent: the separate `chore(ledger)` commit `6b948280`. Then append to the DECISIONS S2a block the review record and the campaign-of-record line (base tree, file sha256, result), as S1b did at `DECISIONS.md:9496-9503`.

---

## Tests

Builders write **tests only**, against the frozen Section 1 file, one file per milestone. `_Fake*` stubs, no `MagicMock` chains. Each test asserts its own premise (an unmodified request authorizes before the modified one is shown to fail). Fixtures: `_candidate(tree_char)` builds `RepairCandidate("a"*40, "b"*40, t, t)` with `t = tree_char*40`; `_request(candidate, **overrides)` builds a `CapabilityRequest(id="req-1", agent_id="agent-1", kind="action", status="approved", decided_by="captain", decided_at=1_000.0, created_at=900.0, payload=candidate_approval_payload(...))`, then applies overrides with `dataclasses.replace` or a payload deep copy.

### M1 -- `tests/test_ad1299_s2a_candidate_approval.py` (pure and fakes)

1. `test_constants_are_pinned` -- tool id `== REPAIR_TOOL_ID == "repair"`; action `== "approve_candidate"` and `!= REPAIR_ACTION`; TTL `== 86_400.0`; `APPROVAL_REASONS` equals a literal 12-member set.
2. `test_payload_is_a_valid_action_payload_with_exact_params` -- `validate_action_payload(p) is p`; exact param keys and values; `scope_key == campaign_id`; `session_id is None`; `thread_id == ""`.
3. `test_payload_is_not_a_repair_dispatch` -- for an `action` request carrying the payload: `repair_action(req) is None` and `can_fulfil_request(req) is False` (the decide route's fulfiller gate).
4. `test_payload_argument_errors_raise` -- non-candidate -> `TypeError`; class `"upkeep"` and a `str` subclass -> `ValueError`; campaign `""`, `" x"`, 129 chars -> `ValueError`.
5. `test_check_authorizes_captain_approval_within_ttl` -- `now=1_010.0`: authorized, `expires_at == 87_400.0`, digest and request id echoed.
6. `test_check_absent_request_is_not_found`.
7. `test_check_identity_precedes_decision_state` -- a pending request for another candidate reads `approval_candidate_mismatch`, not `approval_pending`.
8. `test_check_refuses_malformed_requests` (parametrized, each against the authorizing premise): `other-request-id`, `kind-grant`, `payload-none`, `tool-browser`, `action-dispatch`, `session-id`, `extra-param`, `missing-param`, `int-param`, `status-not-str`, `decided-by-not-str` -> `approval_malformed`.
9. `test_check_refuses_forged_digest_param` -- params copied from the candidate but `candidate_digest` of another -> `approval_candidate_mismatch`.
10. `test_check_refuses_display_field_mismatch` (parametrized `base_commit`, `candidate_commit`, `tree`) -> `approval_candidate_mismatch`.
11. `test_check_refuses_other_class`; 12. `test_check_refuses_other_campaign`; 13. `test_check_refuses_scope_key_mismatch` (params right, scope key wrong) -> `approval_campaign_mismatch`.
14. `test_check_decision_status` (parametrized): `pending` -> `approval_pending`, `denied` -> `approval_denied`, `fulfilled` and `failed` -> `approval_not_approved`.
15. `test_check_requires_captain_decider` -- `first_officer`, `""` -> `approval_not_captain`.
16. `test_check_decision_time` (parametrized): `None`, NaN, inf, `True`, `now + 1` -> `approval_decision_time_invalid`; `decided_at == now` authorizes.
17. `test_check_expiry_boundary` -- `now = 1_000.0 + 86_399.5` authorizes; `1_000.0 + 86_400.0` and `+ 86_401.0` -> `approval_expired` (literal numbers, not the constant).
18. `test_check_argument_errors` (parametrized): `now` NaN, inf, `"1"`, `True` -> `ValueError("approval_clock_invalid")`; bad request id -> `ValueError`; `SimpleNamespace` request -> `TypeError`; wrong candidate type -> `TypeError`.
19. `test_check_record_invariants` -- `CandidateApprovalCheck` refuses an unknown reason, authorized without `expires_at`, `approval_pending` with `expires_at`, a non-finite or `int` `expires_at`, a non-hex digest, an invalid request id.
20. `test_file_files_the_payload_with_a_bounded_rationale` -- `_FakeFiler` records `(agent_id, payload, rationale, work_item_id)`; payload equals `candidate_approval_payload`; `work_item_id is None`; with a 128-character campaign id and `"enhancement"`, `len(rationale) <= RATIONALE_MAX_CHARS`, and it contains `digest[:12]` and `"24 hours"`.
21. `test_file_refused_payload_raises` -- filer returns `None` -> `CandidateApprovalFilingRefused`, which is a `ValueError`.
22. `test_file_argument_errors_raise_before_the_store` -- bad agent id, candidate, class, campaign: raises and `_FakeFiler.calls == []`.
23. `test_file_store_exception_propagates`.
24. `test_authorize_reads_durably_once` -- `_FakeReader` returns the approved request only when `durable=True` (negative control: a non-durable read returns `None`); one call, `durable=True`.
25. `test_authorize_reads_the_clock_after_the_read` -- one shared event list shows `["read", "clock"]`.
26. `test_authorize_reader_errors_propagate` -- `RuntimeError` and `asyncio.CancelledError` propagate; the clock is never read.
27. `test_authorize_bad_clock_raises_after_the_read`.
28. `test_authorize_argument_errors_raise_before_the_read`.
29. `test_authorize_logs_refusal_reason` -- `caplog` at INFO on `probos.cognitive.repair_approval` contains `approval_pending` for a pending request; nothing logged by the authorizer for an authorized one.

### M2 -- `tests/test_ad1299_s2a_approval_chain.py` (real store, real route)

Real `CapabilityRequestStore(db_path=str(tmp_path / "capability_requests.db"))`; the route called directly as `decide_capability_request(request_id, CapabilityRequestDecideRequest(...), runtime=_FakeRuntime(...))` (the `tests/test_ad1154_approval_inbox.py:955-959` pattern). `_FakeRuntime` sets `capability_request_store`, `action_approval_store`, `config`, `work_item_store`.

1. `test_candidate_approval_crosses_store_route_and_restart` -- file with `file_candidate_approval`; premise: `await store.get(id, durable=True)` returns the row; authorize -> `approval_pending`; decide via the route with `approve=True, grant_standing=True, standing_ttl_hours=1` and a config `SimpleNamespace(approval_inbox=SimpleNamespace(standing_rules_enabled=True, standing_rule_max_ttl_hours=168, standing_rule_default_ttl_hours=24))` and an `action_approval_store` fake that fails the test if touched; response: `status == "approved"`, `decided_by == "captain"`, `standing_rule is None`, `fulfilled is False`; `stop()`; a NEW store on the same path; `start()`; read `decided_at` durably; authorize with `clock=lambda: decided_at + 60` -> authorized; `decided_at + 86_400` -> `approval_expired`; another candidate -> `approval_candidate_mismatch`; another campaign -> `approval_campaign_mismatch`; another class -> `approval_class_mismatch`. Do not claim this isolates the tool-id exclusion: with no `work_item_id`, AD-1321's check (`routers/capability_requests.py:625-634`) would also withhold the rule.
2. `test_denial_through_the_route_reads_denied_after_restart` -- deny with a reason; restart; `approval_denied`.
3. `test_refiling_the_same_pending_candidate_dedups` -- two filings return the same id; `list_pending()` has one row.
4. `test_candidate_approval_is_captain_reserved` -- `classify_capability_request(filed, tool_registry=None) is RequestClass.CAPTAIN_RESERVED`.
5. `test_cache_only_store_never_authorizes` -- `CapabilityRequestStore(db_path="")`; file; `store.decide(id, True, decided_by="captain")`; premise: the cached request reads `approved`; authorize -> `approval_not_found`.
6. `test_rewritten_row_is_judged_by_its_new_content` -- after approval and `stop()`, a stdlib `sqlite3` UPDATE (a) sets `decided_at` one hour ahead of now -> `approval_decision_time_invalid`; (b) on a second request, sets `decided_by='first_officer'` -> `approval_not_captain`. Shows detection by re-reading, not prevention.
7. `test_nothing_in_src_imports_the_module` -- AST scan of `src/probos/**/*.py` (excluding the module itself) for `Import`/`ImportFrom` of `probos.cognitive.repair_approval`: none. Positive control: the same scanner finds `probos.cognitive.repair_candidate` imported by `src/probos/cognitive/repair_evidence_store.py`. Pins D5; S2e changes this test deliberately.

## Mutation campaign of record (M2)

Target `src/probos/cognitive/repair_approval.py` only. Baseline first (both S2a files green, else abort). In place, `.mutbak` sibling, restore in `finally`. Before each mutant assert the anchor occurs **exactly once** (match the line without its terminator; the tree is CRLF). Not found = INERT, not killed; timeout = INVALID. Record the base tree and the sha256 of the source and both test files; a later Builder whose hashes match does not rerun it.

| Id | Anchor (exact line) | Replacement | Expected first killer |
|---|---|---|---|
| P1 | `        or payload["tool_id"] != CANDIDATE_APPROVAL_TOOL_ID` | `        or False` | M1 #8 `tool-browser` |
| P2 | `        or payload["action"] != CANDIDATE_APPROVAL_ACTION` | `        or False` | M1 #8 `action-dispatch` |
| P3 | `        or payload["session_id"] is not None` | `        or False` | M1 #8 `session-id` |
| P4 | `        or set(payload["params"]) != _PARAM_KEYS` | `        or False` | M1 #8 `extra-param` |
| P5 | `        or request.kind != "action"` | `        or False` | M1 #8 `kind-grant` |
| P6 | `        or request.id != request_id` | `        or False` | M1 #8 `other-request-id` |
| P7 | `        params["candidate_digest"] != digest` | `        False` | M1 #9 |
| P8 | `        or params["tree"] != candidate.tree` | `        or False` | M1 #10 `tree` |
| P9 | `    if params["authority_class"] != authority_class:` | `    if False:` | M1 #11 |
| P10 | `    if params["campaign_id"] != campaign_id or payload["scope_key"] != campaign_id:` | `    if params["campaign_id"] != campaign_id:` | M1 #13 |
| P11 | `    if request.status == "pending":` | `    if False:` | M1 #14 `pending` |
| P12 | `    if request.status == "denied":` | `    if False:` | M1 #14 `denied` |
| P13 | `    if request.status != "approved":` | `    if False:` | M1 #14 `fulfilled` |
| P14 | `    if request.decided_by != "captain":` | `    if False:` | M1 #15 |
| P15 | `    if type(decided_at) not in (int, float) or not math.isfinite(decided_at) or decided_at > now:` | `    if type(decided_at) not in (int, float) or not math.isfinite(decided_at):` | M1 #16 `future` |
| P16 | `    if now >= expires_at:` | `    if now > expires_at:` | M1 #17 |
| P17 | `CANDIDATE_APPROVAL_TTL_SECONDS: Final = 86_400.0` | `CANDIDATE_APPROVAL_TTL_SECONDS: Final = 864_000.0` | M1 #1 |
| P18 | `    if type(now) not in (int, float) or not math.isfinite(now):` | `    if False:` | M1 #18 `now-nan` |
| P19 | `    if request is not None and type(request) is not CapabilityRequest:` | `    if False:` | M1 #18 `namespace` |
| P20 | `            or (self.reason == _AUTHORIZED) != (self.expires_at is not None)` | `            or False` | M1 #19 |
| P21 | `    if filed is None:` | `    if False:` | M1 #21 |
| P22 | `        "scope_key": campaign_id,` | `        "scope_key": "",` | M1 #2 |
| P23 | `    request = await reader.get(request_id, durable=True)` | `    request = await reader.get(request_id)` | M1 #24 |
| P24 | `    if not check.authorized:` | `    if False:` | M1 #29 |

Every row must be KILLED. A survivor is first checked for a wrong mutant (does it reach the behaviour?), then for a weak test; never weaken an assertion to kill a mutant.

## Hidden pins enumerated (2026-10-14)

| Pin | Command run | Effect on S2a |
|---|---|---|
| S1a/S1b reason, kind and table pins | Grep `REQUIRED_EVIDENCE_KINDS\|REASON_CODES\|EvidenceKind\|captain_approval\|COMPLETION_REASONS` in `tests/test_ad1299*` | Found `test_ad1299_s1a_repair_candidate.py:899-982`, `test_ad1299_s1b_evidence_completion.py:297-316, 370, 487, 533`, `test_ad1299_s1b_repair_evidence_store.py:753-761, 889`, and 56 completion assertions (Grep count). S2a changes neither S1 module (D3), so none move; S2d owns them. |
| Layer boundaries | Read `tests/test_layer_boundaries.py:16-56, 128-133` | S2a imports no federation module; the root-module import of `probos.capability_request` mirrors `repair_dispatch.py:19-21`, which passes today. No `ALLOWED_EXCEPTIONS` entry. |
| Architecture fitness baseline | Read `scripts/check_architecture_principles.py:80-85, 160-165` | Only five packages are ranked; `capability_request` is unranked; no class near the size trigger, no DB connect, no task. Expect `--check` unchanged. |
| Store registry | No store added | `scripts/check_store_registry.py --check` unchanged. |
| Config reference, profiles, facade | No config added | `gen_config_reference.py --check`, `check_config_profiles.py --check`, `check_config_facade.py --check` unchanged. |
| EventType, API routes, agents, pools, crew, standing orders | None added | No enumeration moves. |
| Goldens | Glob `tests/fixtures/*golden*` | Four files (`ad1152_agentic_off`, `ad1179_tool_definition`, `ad1200_no_instructions`, `ad1240_below_threshold`); none covers approvals or this module. |
| Source scans for `repair` producers | Grep `REPAIR_TOOL_ID` in `tests/` | Value asserts only (`test_ad1172_repair_dispatch.py:194, 233`, `test_ad1268_...:526-746`); no producer allowlist. |
| AD ledger | `tests/test_ad1184_ad_ledger.py` runs `scripts/gen_ad_ledger.py --check` | Tracker edits (M3) require regeneration (Section 5 note). |

## Gates

- **Focused (per milestone):** `d:/ProbOS/.venv/Scripts/pytest.exe <files> -q -n 0 -p no:randomly`. M1: the M1 file. M2: both S2a files plus consumers `tests/test_ad1299_s1a_repair_candidate.py tests/test_ad1299_s1b_evidence_completion.py tests/test_ad1299_s1b_repair_evidence_store.py tests/test_layer_boundaries.py tests/test_ad1270b_architecture_fitness.py tests/test_ad1154_approval_inbox.py tests/test_ad1172_repair_dispatch.py tests/test_ad1206_repair_issue.py tests/test_ad1268_a_decision_is_a_standing_answer.py tests/test_ad1213_delegated_approvals.py`. M3: add `tests/test_ad1184_ad_ledger.py`.
- **Scripts, once after M2:** `d:/ProbOS/.venv/Scripts/python.exe scripts/check_architecture_principles.py --check`, `scripts/check_store_registry.py --check`, `scripts/gen_config_reference.py --check`, `scripts/check_config_profiles.py --check`, `scripts/check_config_facade.py --check` (all expected unchanged).
- **Broad gate, once**, by the orchestrator after review repairs and a local commit: `d:/ProbOS/.venv/Scripts/python.exe scripts/run_test_gate.py --label ad1299-s2a --receipt logs/gates/ad1299-s2a.receipt.json`.

## What This Does NOT Change

`repair_candidate.py`, `repair_evidence_store.py` and their tests; `capability_request.py`, `routers/capability_requests.py`, `delegated_approvals.py`, `approval_authority.py`; `fault_report.py`, `repair_dispatch.py`, `repair_issue.py`, `repair_verification.py`; `crew_session.py`, `workforce.py`; every agent, pool, startup module, config model, EventType, route and UI file.

## Do not build

- No `captain_approval` evidence kind, no change to `REQUIRED_EVIDENCE_KINDS`, `EvidenceLink`, `REASON_CODES` or the ledger schema (S2d).
- No campaign admission, `admit_campaign` action, CrewSession/WorkItem creation, ledger construction or start, ledger identity (S2e).
- No guard on `FaultReportStore.resolve` (S2c). No Utility agent, pool or registration (S2f).
- No config field or flag of any kind, including a default-off delegation, scheduling or autonomy switch (D5).
- No delegated or scheduled grant, no standing-rule path, no AD-1213 change (S2b, Captain only).
- No runtime wiring, no candidate execution, no worktree, no call to `WorktreeManager.merge_to_main`/`remove` or `routers/build.py`.
- No UI change (the card wording is S2f), no new EventType, no new route.
- No "re-ask refused after denial" rule (S2e).

## Tracking

`DECISIONS.md` AD-1299 (Section 2, plus the review record and campaign line after the build), `PROGRESS.md` (Section 3), `docs/development/self-maintenance-architecture.md` S2 bullet (Section 4), `docs/development/roadmap.md` (Section 5), regenerated `docs/development/ad-ledger-snapshot.json` and `docs/development/open-ads-report.md`. #1352 stays open; the orchestrator posts the S2a comment after merge.

## Acceptance Criteria

1. Section 1 applied byte-for-byte; `import probos.cognitive.repair_approval` succeeds from the worktree import root.
2. M1 and M2 files pass at `-n 0 -p no:randomly`; every listed consumer test file still passes; the five scripts report unchanged.
3. Paths covered: happy (authorized), denied, expired, empty (`approval_not_found`), unavailable (cache-only store; reader exception propagates), malformed, and default-off parity (nothing imports the module; no flag exists; a delegate decider never authorizes; the request is `CAPTAIN_RESERVED`; no standing rule is issued).
4. One test crosses the real filer, the real store on `tmp_path`, the real decide route, a restart and changed inputs (M2 #1), and one shows a rewritten row judged by its new content (M2 #6).
5. Mutation campaign of record: 24 of 24 KILLED, none INERT or INVALID, with base tree and file sha256 recorded in DECISIONS.
6. No file outside the Section 1 file, the two test files and the Section 2-5 trackers (plus the two regenerated ledger files) changes. Staged by explicit path; never `git add -A`.
7. Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

---

## Verified Against Codebase (2026-10-14)

Base `cff8449587c0f360218f6461d8d32d891d3a7a78` (`git rev-parse HEAD HEAD^{tree}`).

```
Grep "def |status" src/probos/fault_report.py
  60: FaultStatus = Literal["open", "diagnosing", "repaired", "dismissed"]
  568: class FaultReportStore:
  909: async def resolve(   (922-939: cache mutated before the persist; persist failure logged, not raised)
Grep "REPAIR_TOOL_ID|REPAIR_ACTION" src/probos
  capability_request.py:115 REPAIR_TOOL_ID = "repair"; :116 REPAIR_ACTION = "dispatch"
  capability_request.py:127-147 repair_action(): requires action == REPAIR_ACTION
  routers/capability_requests.py:579 decided.payload.get("tool_id") == REPAIR_TOOL_ID -> no standing rule
Read src/probos/capability_request.py
  :109-110 RequestKind / RequestStatus literals; :165-230 validate_action_payload (six exact keys, total)
  :508-527 CapabilityRequest fields; :649-679 CapabilityRequestStore.__init__
  :779-839 file_action_request (pending-only dedup :818-828); :948-1035 decide (no pending guard)
  :1126-1142 get(request_id, *, durable=False); durable -> None when no db (:1131-1132)
Read src/probos/routers/capability_requests.py
  :119-155 decide_capability_request(request_id, req, runtime); :167-191 pending guard
  :423-472 _APPROVAL_FULFILLERS has no "action"; :451 repair_action gate; :523 _STANDING_RULE_KINDS
Read src/probos/delegated_approvals.py:168-172  if kind == "action": return RequestClass.CAPTAIN_RESERVED
Grep "class CapabilityRequestDecideRequest" src/probos/api_models.py:271 (approve, reason, grant_standing, standing_ttl_hours; deny needs reason :292-296)
Read src/probos/cognitive/repair_candidate.py
  :69-71 EvidenceKind/EvidenceStatus/AuthorityClass; :99 AUTHORITY_CLASSES; :101-107 REQUIRED_EVIDENCE_KINDS
  :133 is_sha256_hex; :138 is_evidence_ref; :152-185 RepairCandidate (projection covers base_commit)
Read src/probos/cognitive/repair_evidence_store.py:76, :89 kind CHECK IN ('gate_receipt','review_set'); :365 assess_candidate_evidence
Read src/probos/cognitive/repair_issue.py:293-303 fulfil(): durable get, status approved, decided_by captain
Read src/probos/cognitive/repair_verification.py:251-285 verify_and_close; :266 store.resolve(...)
Grep "open_or_resume|compare_and_set_recovery" src/probos/cognitive/crew_session.py:3529, :5593
Grep workforce.py: :3985 claim_owned_effect_attempt, :9608 compare_and_set_work_item_verification, :10002 transition_crew_session_terminal_with_trust
Grep "class ReviewedStepResult" src/probos/work_item_steps.py:506
Grep "class EngineeringAgent" src/probos/cognitive/engineering_officer.py:32
Grep "class MaintenanceAgent|pool" src/probos/agents/engineering/maintenance.py:24, :47 pool "engineering_maintenance"; startup/agent_fleet.py:281
Grep 'tier = "utility"' src/probos/agents: system_qa.py:77, introspect.py:28, federation_recall_agent.py:27 (Utility pattern)
Read src/probos/cognitive/capability_gap_driver.py:255-259 no work_item_id -> ignored
Read ui/src/store/capabilityApprovals.ts:125-128, 161, 245-258; ui/src/components/capability/CapabilityRequestCard.tsx:55, 136
Read tests/test_ad1154_approval_inbox.py:236-246 _FakeRuntime; :955-959 route called directly
Read src/probos/config_models/experience.py:119-120 standing_rules_enabled default False
```

## Absence Verified (2026-10-14)

```
1. CLAIM: FaultReportStore.resolve has one production caller.
   RUN:   Grep "\.resolve\(" src/ ; Grep "verify_and_close|store\.resolve\(|faults?\.resolve\(|fault_report_store\.resolve" **/*.py
   FOUND: src/probos/cognitive/repair_verification.py:266 only; every other .resolve( in src is a Path, callsign, billet, resolver or registry call; routers/faults.py has no "resolve" (Grep, no match)
   HOLDS: yes
2. CLAIM: verify_and_close has no production caller.
   RUN:   Grep "verify_and_close" **/*.py
   FOUND: src/probos/cognitive/repair_verification.py:251 (def); tests/test_ad1173_repair_verification.py; tests/test_ad1268_...:251 (docstring)
   HOLDS: yes
3. CLAIM: no Captain-approval binder, approve_candidate action or captain_approval evidence kind exists.
   RUN:   Grep "approve_candidate|captain_approval|CandidateApproval|repair_approval" **/*.{py,ts,tsx,yaml,json}
   FOUND: sop/schema.py:28,71 and sop/builtin/general_quarters.yaml:110-111 (SOP gate, unrelated); repair_candidate.py:101 (comment); unrelated tests; test_ad1299_s1b_evidence_completion.py:487 (outside-table case)
   HOLDS: yes; module name repair_approval.py is free (Glob src/probos/cognitive/repair_*.py: brief, candidate, dispatch, evidence_store, issue, verification)
4. CLAIM: capability requests carry no expiry.
   RUN:   Grep -i "expires_at|ttl" src/probos/capability_request.py
   FOUND: no match
   HOLDS: yes
5. CLAIM: no test pins the set of producers of tool "repair" requests.
   RUN:   Grep "REPAIR_TOOL_ID" tests/ ; Grep "rglob|walk_packages|iter_modules" tests/test_ad1{154,172,206,212,213,267,268}*.py
   FOUND: value asserts only; one rglob at test_ad1154_approval_inbox.py:1826 (consensus_dir)
   HOLDS: yes
6. CLAIM: no EngineeringMaintenanceAgent class exists; pool engineering_maintenance is taken.
   RUN:   Grep "EngineeringMaintenance|class MaintenanceAgent|class EngineeringAgent|engineering_maintenance" (excluding logs/)
   FOUND: name only in DECISIONS.md:9407 and docs; pool at startup/agent_fleet.py:281, agents/engineering/maintenance.py:47
   HOLDS: yes
```

## Prior Art and Blind Spots

Bounded to what S2a newly raises (S1a's pass covers in-toto, TUF and boot assessment).

| Idea | Source | Decision |
|---|---|---|
| Approvals are per patch set; carrying a vote to a new patch set is opt-in (trivial rebase, no code change) | Gerrit sticky approvals ([no-code-change copy](https://opendev.org/opendev/gerrit/commit/54122d372511fb3a7835f51ab946da7abc1865a9), [trivial rebase](https://opendev.org/opendev/gerrit/commit/f5c08415e0b9e71d260de3b32a2031ae85fd8136)) | **Adopt the default, reject copying.** Any change is a new digest and a new approval (N1). No copy condition is offered. |
| The initiator may be barred from approving; approval gates secrets and the job | GitHub environments ([deployments and environments](https://docs.github.com/en/actions/reference/workflows-and-actions/deployments-and-environments)) | **Adopt.** `decided_by == "captain"`; AD-1213 already refuses originators deciding their own requests. The approval gates candidate execution (S3's runner). |
| A human-review attestation binds a subject digest, a result and a timestamp | SLSA/in-toto ([in-toto and SLSA](https://slsa.dev/blog/2023/05/in-toto-and-slsa)) | **Defer to S2d** (when `captain_approval` becomes an evidence link). No envelope: a hash is integrity, not authenticity (AD-1047). |

**Blind spots named:**
- *Standing rules.* A new tool id would have been standing-rule-eligible in the route and HXI; D1 reuses the existing `repair` exclusion.
- *Cache vs durable.* `get()` without `durable=True` returns the in-memory cache, which a failed commit can leave ahead of the row (BF-722 history, `capability_request.py:959-968`); the authorizer reads durably and P23 pins it.
- *Absent vs unavailable.* `get(durable=True)` cannot tell an unknown id from a store with no database; S2a names one reason for both rather than claim a distinction (M2 #5).
- *Clock order.* Reading the clock before a slow read would authorize a request that expired during the read; the clock is read after (M1 #25).
- *Future-dated decisions.* A `decided_at` after now (clock rollback or an edited row) is refused, not authorized for longer.
- *Trust side effect.* `decide()` records a trust outcome for the filing agent (`capability_request.py:1008-1016`); a denied candidate lowers that agent's trust. Accepted: it is how every request works; S2f's agent inherits it.
- *Same-user writers.* An edited row is judged by its new content (M2 #6); detection by re-reading, never prevention (D-B2).
- *Cancelled filing (review round 1, F1; the store's behaviour, recorded, not changed here).* `CapabilityRequestStore.file_request` awaits the INSERT and the COMMIT and only then publishes to its cache; a caller cancelled at either await leaves the queued write to run on the aiosqlite worker, so a durable pending row can exist that the cache does not hold and a retry then files a second row (reproduced on the real store). The same class as S1b's D4a. `file_candidate_approval` documents "outcome unknown, never nothing filed"; both requests are decided separately and neither widens what the Captain approved. A cancellation-safe `file_request` is a store change outside S2a (follow-up).
- *Malformed in-memory evidence (review round 1, F2 and F3; injected reach, recorded).* A request `kind` that is an object comparing equal to `"action"` is read as an action, and an `int` too large for a float raises `OverflowError` from the finiteness tests, as `now` or as `decided_at`. Neither can come from a stored row; the docstring states both, the code is unchanged, and the guards are recorded follow-ups.
- *Considered, deferred:* a configurable TTL (D2 #3); refusing re-asks after a denial (S2e); approval-row digests in the ledger (S2d).

## Milestones

| M | Who | Output | Gate |
|---|---|---|---|
| M0 | Orchestrator (mechanical) | Section 1 file | import check; `check_architecture_principles.py --check` |
| M1 | Fresh Builder, high, about 150 calls | `tests/test_ad1299_s2a_candidate_approval.py` | M1 focused |
| M2 | Fresh Builder, max, about 150 calls | `tests/test_ad1299_s2a_approval_chain.py`; mutation campaign of record | M2 focused + scripts |
| M3 | Orchestrator or Builder, medium | Sections 2-5; ledger regeneration; review record and campaign line | M3 focused |

Then the Diff Reviewer (security/authority change: also the Copilot Diff Reviewer), repairs, local commit, one broad gate.

=== BUILDER BRIEFS ===

### M1 brief (tests only; high effort)

Contract: `prompts/ad-1299-s2a-candidate-approval.md`, "Tests" M1 (#1-#29) and "Mutation campaign" (which tests must kill which mutants). Source `src/probos/cognitive/repair_approval.py` is FROZEN: do not edit it, `repair_candidate.py`, `capability_request.py` or any router. A source defect is a hard stop to the Architect with the failing test and the line.

Write ONE file, `tests/test_ad1299_s2a_candidate_approval.py`. pytest + pytest-asyncio, `_Fake*` classes (`_FakeFiler`, `_FakeReader`), no MagicMock chains. Arrange-Act-Assert; names `test_<subject>_<scenario>_<expected>` or the names given. Each malformed or mismatch case first shows the unmodified request authorizes (its premise), then that the change produces the exact reason. Use literal numbers for expiry (86_400.0), not the constant, so P17 dies. Expected reason strings must be literals.

Environment (PowerShell, from the worktree root `<WT>`):
```
$env:PYTHONPATH = "<WT>\src;<WT>"
d:/ProbOS/.venv/Scripts/python.exe -c "import probos; print(probos.__file__)"
d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad1299_s2a_candidate_approval.py -q -n 0 -p no:randomly --tb=short -rfE
```
`probos.__file__` must be under `<WT>\src`; otherwise stop. Never print environment variables. Show failure output only.

Done when: the file passes; every M1 test number in the contract exists (list them with their function names); you ran no other suite. Report: test count, the mapping of contract numbers to functions, and anything in the contract you could not express.

### M2 brief (tests + campaign of record; max effort)

Contract: `prompts/ad-1299-s2a-candidate-approval.md`, "Tests" M2 (#1-#7), "Mutation campaign of record" (P1-P24), "Gates". Source and the M1 test file are FROZEN.

Write ONE file, `tests/test_ad1299_s2a_approval_chain.py`. Real `CapabilityRequestStore` on `tmp_path`, always `stop()` in `finally`. Call the route directly: `from probos.routers.capability_requests import decide_capability_request`, `from probos.api_models import CapabilityRequestDecideRequest`; `_FakeRuntime` with `capability_request_store`, `action_approval_store`, `config`, `work_item_store` (see `tests/test_ad1154_approval_inbox.py:236-246`, `:955-959`). Restart = a NEW store instance on the same path. The row rewrite in #6 uses stdlib `sqlite3` after `stop()`. #7 includes its positive control. Each test asserts its own premise.

Then the campaign: baseline both S2a files green; mutate `src/probos/cognitive/repair_approval.py` in place with a `.mutbak` sibling restored in `finally`; assert each anchor occurs exactly once (match without the line terminator); run both S2a files per mutant; classify KILLED / SURVIVED / INERT / INVALID (timeout). Record base tree (`git rev-parse HEAD^{tree}`), sha256 of the source and both test files, and the first killing test per row. After the campaign confirm `git diff --stat` shows the source unchanged.

Environment as M1 (PYTHONPATH, `probos.__file__` check, never print environment variables, failure-only output). Focused gate and the five scripts: the contract's "Gates" list.

Done when: M2 passes, consumers pass, scripts unchanged, 24/24 KILLED. Report counts per file, the campaign table and hashes. A survivor is a hard stop to the Architect, not a reason to edit source.

### M3 brief (trackers; medium effort)

Apply Sections 2-5 of `prompts/ad-1299-s2a-candidate-approval.md` as SEARCH/REPLACE (each SEARCH occurs once; stop if not). Then `d:/ProbOS/.venv/Scripts/python.exe scripts/gen_ad_ledger.py` and `... scripts/gen_ad_ledger.py --check`. Append to the DECISIONS "S2a (2026-10-14)" block the review record and the campaign line from M2 (S1b format, `DECISIONS.md:9496-9503`). Run `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad1184_ad_ledger.py -q -n 0 -p no:randomly`. Stage by explicit path only. Never print environment variables.
