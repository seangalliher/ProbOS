"""AD-1213 (#1170): chain-of-command approvals -- who may decide a request, and when.

A capability or skill request has three levels of authority:

* **the Captain**, always, through the existing decide routes;
* **a department chief**, for a non-destructive request from crew under their
  direct, in-department command, with no grace period;
* **the First Officer**, for a request the Captain has delegated, once the
  Captain's grace period has passed (zero while the Captain is marked
  unavailable).

A floor stays with the Captain alone: every ``action`` request, every build
whose design context carries ``requires_consensus``, a grant of the review tool
itself, and anything that cannot be classified. No one decides a requisition
they originated.

This part of the module is the pure eligibility core -- no I/O and no clocks of
its own. Classification reuses the one definition of "destructive"
(``capability_triage.derive_tool_permission`` / ``is_non_destructive``) and
``fulfil_build``'s own consensus expression, so the classifier and the
fulfillers can never disagree. Every predicate fails closed: anything that is not
exactly what a widening needs refuses, and a refusal leaves the request with the
Captain.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import math
import time
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Any, Protocol

from probos.approval_authority import CAPTAIN_UNAVAILABLE, FIRST_OFFICER_DELEGATION, REVIEW_TOOL_ID
from probos.capability_request import validate_action_payload
from probos.cognitive.capability_triage import derive_tool_permission, is_non_destructive
from probos.decision_pre_clearance import (
    PRE_CLEARANCE_AUDIT_CATEGORY,
    PreClearance,
    PreClearanceBook,
    PreClearanceKey,
    confirm_pre_clearance,
    make_offer,
    pre_clearance_key,
)

if TYPE_CHECKING:
    from probos.ontology.models import Post

logger = logging.getLogger(__name__)

# The First Officer's post in the real ontology (a test pins it to organization.yaml).
FIRST_OFFICER_POST_ID = "first_officer"
# REVIEW_TOOL_ID (imported above) is re-exported: the tool module and the wiring
# import it from here, and this module never imports the tool.
QUEUES: tuple[str, ...] = ("capability", "skill")
_PENDING: dict[str, str] = {"capability": "pending", "skill": "requested"}

# Drift-guarded against ``continue_or_ask`` by a test, as the router does for
# ``_CONTINUE_KIND``: importing that module would pull the agentic stack in.
_CONTINUE_KIND = "continue"
_CONTINUE_TOOL_ID = "dm_agentic"
_CONTINUE_ACTION = "continue"

_SKILL_SOURCES: frozenset[str] = frozenset({"self", "counselor", "chief"})
MAX_ORIGIN_ITEMS = 8
# How long the work-item re-read may hold the decision lock -- the Captain's lock
# too -- before the agent is refused. A wait budget for this service, not a bound
# on the work-item store's own thread.
ORIGIN_RECHECK_BUDGET_SECONDS = 1.0
MAX_REASON_CHARS = 500
# ApprovalInboxConfig.approval_grace_seconds is bounded 0..86_400 at parse time;
# ``evaluate`` re-checks both bounds because a settings object can be mutated
# without validation.
MAX_GRACE_SECONDS = 86_400
AUDIT_CATEGORY = "delegated_approval"
# Appended when a decision's entry was written but its commit then failed.
AUDIT_VOID_CATEGORY = "delegated_approval_void"
AUTHORITY_AUDIT_CATEGORY = "approval_authority"


class RequestClass(str, Enum):
    NON_DESTRUCTIVE = "non_destructive"
    DESTRUCTIVE = "destructive"
    CAPTAIN_RESERVED = "captain_reserved"
    UNCLASSIFIABLE = "unclassifiable"


class DeciderRole(str, Enum):
    DEPARTMENT_CHIEF = "department_chief"
    FIRST_OFFICER = "first_officer"
    CAPTAIN = "captain"


class Refusal(str, Enum):
    NOT_ENABLED = "not_enabled"
    UNKNOWN_QUEUE = "unknown_queue"
    UNKNOWN_REQUEST = "unknown_request"
    NOT_PENDING = "not_pending"
    INVALID_DECISION = "invalid_decision"
    DECIDER_UNRESOLVED = "decider_unresolved"
    REQUESTER_UNRESOLVED = "requester_unresolved"
    OWN_REQUISITION = "own_requisition"
    CAPTAIN_RESERVED = "captain_reserved"
    UNCLASSIFIABLE = "unclassifiable"
    OUTSIDE_AUTHORITY = "outside_authority"
    DESTRUCTIVE_NEEDS_FIRST_OFFICER = "destructive_needs_first_officer"
    DELEGATION_ABSENT = "delegation_absent"
    GRACE_PERIOD = "grace_period"
    STATE_UNREADABLE = "state_unreadable"
    AUDIT_UNAVAILABLE = "audit_unavailable"


# Model-facing and fixed: none echoes request data, and every one is tested
# against the decomposer's capability-gap pattern.
REFUSAL_TEXT: dict[Refusal, str] = {
    Refusal.NOT_ENABLED: "Delegated approvals are switched off on this vessel.",
    Refusal.UNKNOWN_QUEUE: "Name the queue as 'capability' or 'skill'.",
    Refusal.UNKNOWN_REQUEST: "No request has that id.",
    Refusal.NOT_PENDING: "That request has already been decided.",
    Refusal.INVALID_DECISION: "Give approve as true or false and a reason of 1 to 500 characters.",
    Refusal.DECIDER_UNRESOLVED: "Your post in the chain of command could not be resolved.",
    Refusal.REQUESTER_UNRESOLVED: "The requester's post in the chain of command could not be resolved.",
    Refusal.OWN_REQUISITION: "You originated this requisition, and no one decides their own.",
    Refusal.CAPTAIN_RESERVED: "This class of request is reserved for the Captain.",
    Refusal.UNCLASSIFIABLE: "This request could not be classified, so it is reserved for the Captain.",
    Refusal.OUTSIDE_AUTHORITY: "The requester is not under your command.",
    Refusal.DESTRUCTIVE_NEEDS_FIRST_OFFICER: (
        "It changes something, so it goes past a department chief to the First Officer."
    ),
    Refusal.DELEGATION_ABSENT: (
        "The Captain has not delegated approvals to the First Officer, or the delegation has expired."
    ),
    Refusal.GRACE_PERIOD: "The Captain has first refusal until the grace period ends.",
    Refusal.STATE_UNREADABLE: "Approval authority could not be read, so the Captain decides.",
    Refusal.AUDIT_UNAVAILABLE: "The audit log is offline, and an unaudited decision is never taken.",
}


@dataclass(frozen=True)
class Verdict:
    """Whether one decider may decide one request now, and on what terms."""

    refusal: Refusal | None
    role: DeciderRole | None = None
    request_class: RequestClass = RequestClass.UNCLASSIFIABLE
    decidable_after: float | None = None
    grace_seconds: int | None = None
    captain_unavailable: bool | None = None
    delegation_id: str | None = None

    @property
    def allowed(self) -> bool:
        return self.refusal is None


class ToolLookup(Protocol):
    """The one registry read classification needs."""

    def get(self, tool_id: str) -> Any: ...


def classify_capability_request(req: Any, *, tool_registry: ToolLookup | None) -> RequestClass:
    """Classify a capability request. Anything not positively recognised is unclassifiable."""
    kind = getattr(req, "kind", None)
    if kind == "action":  # Q1: every action, repair included
        return RequestClass.CAPTAIN_RESERVED
    if kind == _CONTINUE_KIND:
        payload = validate_action_payload(getattr(req, "payload", None))
        if (
            payload is not None
            and payload.get("tool_id") == _CONTINUE_TOOL_ID
            and payload.get("action") == _CONTINUE_ACTION
        ):
            return RequestClass.NON_DESTRUCTIVE
        return RequestClass.UNCLASSIFIABLE
    if kind == "grant":
        target = getattr(req, "target", None)
        if target == REVIEW_TOOL_ID:  # conferring decision authority is the Captain's
            return RequestClass.CAPTAIN_RESERVED
        if tool_registry is None or type(target) is not str or not target:
            return RequestClass.UNCLASSIFIABLE
        registration = tool_registry.get(target)
        if registration is None:  # never derive(None) == READ
            return RequestClass.UNCLASSIFIABLE
        return (
            RequestClass.NON_DESTRUCTIVE
            if is_non_destructive(derive_tool_permission(registration))
            else RequestClass.DESTRUCTIVE
        )
    if kind == "install":
        return RequestClass.DESTRUCTIVE
    if kind == "build":
        payload = getattr(req, "payload", None)
        ctx = payload if isinstance(payload, dict) else {}  # fulfil_build's own expression
        return (
            RequestClass.CAPTAIN_RESERVED
            if bool(ctx.get("requires_consensus", False))
            else RequestClass.DESTRUCTIVE
        )
    return RequestClass.UNCLASSIFIABLE


def classify_skill_request(req: Any) -> RequestClass:
    """A training request from a known source is non-destructive; anything else is not classified."""
    source = getattr(req, "source", None)
    if type(source) is str and source in _SKILL_SOURCES:
        return RequestClass.NON_DESTRUCTIVE
    return RequestClass.UNCLASSIFIABLE


def authority_route(chain: Sequence[Post], decider_post: Post) -> DeciderRole | None:
    """Conjunctive walk over ``get_chain_of_command(requester_post.id) == [requester, superior, ...]``.

    Every hop's superior must list the subordinate in ``authority_over``; a
    broken link grants nothing above it. A chief is the first hop, in the
    requester's department. The First Officer is any hop at the First Officer's
    post.
    """
    if not chain:
        return None
    requester = subordinate = chain[0]
    for hop, superior in enumerate(chain[1:], start=1):
        over = superior.authority_over
        if not isinstance(over, (list, tuple)) or subordinate.id not in over:
            return None  # a broken authority link grants nothing
        if superior.id == decider_post.id:
            if superior.id == FIRST_OFFICER_POST_ID:
                return DeciderRole.FIRST_OFFICER
            if hop == 1 and superior.department_id == requester.department_id:
                return DeciderRole.DEPARTMENT_CHIEF
            return None
        subordinate = superior
    return None


def _finite_real(value: Any) -> bool:
    return type(value) in (int, float) and math.isfinite(value)


def evaluate(
    *,
    request_class: RequestClass,
    route: DeciderRole | None,
    own_requisition: bool,
    chief_barred: bool,
    delegation_live: bool,
    delegation_id: str | None,
    captain_unavailable: bool,
    grace_seconds: Any,
    created_at: Any,
    now: Any,
) -> Verdict:
    """Precedence is part of the contract: own requisition, then reserved/unclassifiable, then route.

    Widening inputs count only when they are exactly ``True``; the bars count
    unless they are exactly ``False``. Junk anywhere refuses.
    """
    klass = request_class if isinstance(request_class, RequestClass) else RequestClass.UNCLASSIFIABLE
    if own_requisition is not False:
        return Verdict(Refusal.OWN_REQUISITION, role=route, request_class=klass)
    if klass is RequestClass.CAPTAIN_RESERVED:
        return Verdict(Refusal.CAPTAIN_RESERVED, role=route, request_class=klass)
    if klass is RequestClass.UNCLASSIFIABLE:
        return Verdict(Refusal.UNCLASSIFIABLE, role=route, request_class=klass)
    if route is DeciderRole.DEPARTMENT_CHIEF:
        if chief_barred is not False:
            return Verdict(Refusal.OWN_REQUISITION, role=route, request_class=klass)
        if klass is RequestClass.NON_DESTRUCTIVE:
            return Verdict(None, role=route, request_class=klass, grace_seconds=0)
        return Verdict(Refusal.DESTRUCTIVE_NEEDS_FIRST_OFFICER, role=route, request_class=klass)
    if route is DeciderRole.FIRST_OFFICER:
        unavailable = captain_unavailable is True
        if delegation_live is not True:
            return Verdict(
                Refusal.DELEGATION_ABSENT, role=route, request_class=klass,
                captain_unavailable=unavailable,
            )
        terms: dict[str, Any] = {
            "role": route, "request_class": klass,
            "captain_unavailable": unavailable, "delegation_id": delegation_id,
        }
        if not _finite_real(now) or not _finite_real(created_at):
            return Verdict(Refusal.STATE_UNREADABLE, **terms)
        if type(grace_seconds) is not int or not 0 <= grace_seconds <= MAX_GRACE_SECONDS:
            return Verdict(Refusal.STATE_UNREADABLE, **terms)
        effective = 0 if unavailable else grace_seconds
        if now < created_at + effective:
            return Verdict(
                Refusal.GRACE_PERIOD, decidable_after=float(created_at + effective),
                grace_seconds=effective, **terms,
            )
        return Verdict(None, grace_seconds=effective, **terms)
    return Verdict(Refusal.OUTSIDE_AUTHORITY, role=route, request_class=klass)


# ---------------------------------------------------------------------------
# The service: where an agent's decision is checked and committed
# ---------------------------------------------------------------------------

_CAPTAIN = "captain"  # the Captain's decided_by value and post id
_AUDIT_TARGET_CHARS = 200
_NOTE_TARGET_CHARS = 120
_NOTE_REASON_CHARS = 240
_ROLE_LABEL: dict[DeciderRole, str] = {
    DeciderRole.DEPARTMENT_CHIEF: "Department chief",
    DeciderRole.FIRST_OFFICER: "First Officer",
}


@dataclass(frozen=True)
class DecisionOutcome:
    """What one delegated decision call did: refused (``refusal`` set) or decided."""

    queue: str
    request_id: str
    refusal: Refusal | None = None
    status: str = ""
    role: DeciderRole | None = None
    request_class: RequestClass | None = None
    fulfilled: bool | None = None
    audited: bool = False
    notified: bool = False
    decidable_after: float | None = None
    pre_cleared: bool = False

    @property
    def decided(self) -> bool:
        return self.refusal is None


@dataclass(frozen=True)
class ReviewableRequest:
    """A pending request the decider may decide now, or once the grace period ends."""

    queue: str
    request_id: str
    kind: str
    target: str
    rationale: str
    requester_id: str
    created_at: float
    request_class: RequestClass
    role: DeciderRole | None
    decidable_after: float | None


class DelegatedApprovalRefused(Exception):
    """``list_reviewable`` cannot answer for this decider at all."""

    def __init__(self, refusal: Refusal) -> None:
        super().__init__(refusal.value)
        self.refusal = refusal


class AgentLookup(Protocol):
    """The agent-registry read that resolves a decider or a requester."""

    def get(self, agent_id: str) -> Any: ...


class CommandOntology(Protocol):
    """The two ontology reads the authority walk needs."""

    def get_post_for_agent(self, agent_type: str) -> Post | None: ...

    def get_chain_of_command(self, post_id: str) -> list[Post]: ...


class WorkItemLookup(Protocol):
    """The work-item read that walks a request's chain of origin."""

    async def get_work_item(self, work_item_id: str) -> Any: ...


class AuthorityReader(Protocol):
    """The Captain's live approval-authority records."""

    def live(self, kind: str) -> Any: ...


class AuditSink(Protocol):
    """The hash-chained audit log."""

    def append(self, *, category: str, detail: str) -> Any: ...


class RequestQueue(Protocol):
    """A request store: the three calls the Captain's route makes, and a committed-row read."""

    async def get(self, request_id: str, *, durable: bool = False) -> Any: ...

    async def list_pending(self) -> list[Any]: ...

    async def decide(self, request_id: str, approve: bool, *, reason: str, decided_by: str) -> Any: ...


def _nonblank(value: Any) -> bool:
    return type(value) is str and bool(value)


def _valid_post(post: Any) -> bool:
    """A post the authority walk can rely on: typed ids and an explicit list of subordinates."""
    over = getattr(post, "authority_over", None)
    reports_to = getattr(post, "reports_to", None)
    return (
        post is not None
        and _nonblank(getattr(post, "id", None))
        and _nonblank(getattr(post, "department_id", None))
        and isinstance(over, (list, tuple))
        and all(type(item) is str for item in over)
        and (reports_to is None or type(reports_to) is str)
    )


@dataclass(frozen=True)
class _Identity:
    """A resolved decider: the agent and the post it holds."""

    agent_id: str
    agent_type: str
    pool: str
    post: Any

    @property
    def names(self) -> frozenset[str]:
        """Every name an originator record could carry for this decider."""
        return frozenset(name for name in (self.agent_id, self.agent_type, self.pool) if name)


def _age(req: Any) -> tuple[int, float]:
    """Oldest first; a request whose ``created_at`` is unusable sorts last."""
    created_at = getattr(req, "created_at", None)
    return (0, float(created_at)) if _finite_real(created_at) else (1, 0.0)


def _kind_and_target(queue: str, req: Any) -> tuple[str, str]:
    """What a request asks for, as the decider and the Captain see it."""
    if queue == "capability":
        return str(getattr(req, "kind", "")), str(getattr(req, "target", ""))
    return "skill", str(getattr(req, "skill_label", "") or getattr(req, "skill_id", ""))


def _reviewable(queue: str, req: Any, verdict: Verdict) -> ReviewableRequest:
    kind, target = _kind_and_target(queue, req)
    rationale = getattr(req, "rationale" if queue == "capability" else "justification", "")
    return ReviewableRequest(
        queue=queue, request_id=str(req.id), kind=kind, target=target,
        rationale=str(rationale or ""), requester_id=str(req.agent_id),
        created_at=req.created_at, request_class=verdict.request_class,
        role=verdict.role, decidable_after=verdict.decidable_after,
    )


def _refused(queue: Any, request_id: Any, refusal: Refusal, verdict: Verdict | None = None) -> DecisionOutcome:
    if verdict is None:
        return DecisionOutcome(queue, request_id, refusal)
    return DecisionOutcome(
        queue, request_id, refusal, role=verdict.role, request_class=verdict.request_class,
        decidable_after=verdict.decidable_after,
    )


def _audit_detail(
    queue: str, req: Any, *, decider_id: str, role: DeciderRole, decider_post: str,
    approve: bool, request_class: RequestClass, verdict: Verdict | None, reason: Any,
    status: str | None = None, pre_clearance_id: str | None = None,
) -> str:
    """One compact, key-sorted JSON object of bounded fields: no payload, no full rationale."""
    kind, target = _kind_and_target(queue, req)
    fo = verdict if verdict is not None and verdict.role is DeciderRole.FIRST_OFFICER else None
    detail: dict[str, Any] = {
        "v": 1,
        "queue": queue,
        "request_id": str(getattr(req, "id", "")),
        "target": target[:_AUDIT_TARGET_CHARS],
        "requester_id": str(getattr(req, "agent_id", "")),
        "decider_id": decider_id,
        "decider_role": role.value,
        "decider_post": decider_post,
        "approve": approve,
        "status": str(getattr(req, "status", "")) if status is None else status,
        "request_class": request_class.value,
        "pre_cleared": pre_clearance_id is not None,  # AD-1214
        "grace_seconds": fo.grace_seconds if fo else None,
        "captain_unavailable": fo.captain_unavailable if fo else None,
        "delegation_id": fo.delegation_id if fo else None,
        "reason": str(reason or "")[:MAX_REASON_CHARS],
    }
    if pre_clearance_id is not None:  # AD-1214: only when pre-cleared, so every other entry keeps 17 keys
        detail["pre_clearance_id"] = pre_clearance_id
    if queue == "capability":
        detail["kind"] = kind
    else:
        detail["skill_id"] = str(getattr(req, "skill_id", ""))
    return json.dumps(detail, sort_keys=True, separators=(",", ":"))


class DelegatedApprovalService:
    """Answers one question -- may this agent decide this request now? -- and commits it if so.

    It never chooses a decider, ranks work or judges merit (DP-1). One lock per
    queue serializes check-and-commit for agents and for both Captain routes
    (``captain_decision_guard``). Inside the lock the awaits are on the request
    store the Captain's route uses anyway and on one re-read of the work-item
    chain, bounded by ``origin_recheck_budget``; the verdict and the audit
    append are synchronous, and so is the AD-1214 pre-clearance lookup. So
    another store can hold up a Captain decision by at most that wait budget,
    and a work-item store that is already wedged when an agent calls stalls
    only that agent's lock-free first read. Any
    dependency may be ``None``: one the check needs refuses the agent, and every
    refusal leaves the request with the Captain; a missing notifier or
    fulfilment degrades after the commit.
    """

    def __init__(
        self,
        *,
        capability_requests: RequestQueue | None,
        skill_requests: RequestQueue | None,
        authority_store: AuthorityReader | None,
        agent_registry: AgentLookup | None,
        ontology: CommandOntology | None,
        tool_registry: ToolLookup | None,
        work_items: WorkItemLookup | None,
        audit_log: AuditSink | None,
        notify: Callable[..., Any] | None,
        fulfil: Callable[..., Awaitable[bool]] | None,
        settings: Callable[[], Any] | None,
        pre_clearances: PreClearanceBook | None = None,
        clock: Callable[[], float] = time.time,
        origin_recheck_budget: float = ORIGIN_RECHECK_BUDGET_SECONDS,
    ) -> None:
        self._queues: dict[str, RequestQueue | None] = {
            "capability": capability_requests,
            "skill": skill_requests,
        }
        self._authority = authority_store
        self._agents = agent_registry
        self._ontology = ontology
        self._tool_registry = tool_registry
        self._work_items = work_items
        self._audit_log = audit_log
        self._notify = notify
        self._fulfil = fulfil
        self._settings = settings
        self._pre_clearances = pre_clearances
        self._clock = clock
        self._origin_recheck_budget = origin_recheck_budget
        self._locks: dict[str, asyncio.Lock] = {queue: asyncio.Lock() for queue in QUEUES}

    def enabled(self) -> bool:
        """The live enable flag, re-read on every call; a provider that fails reads as off."""
        try:
            return self._settings().delegated_approvals_enabled is True  # type: ignore[misc]
        except Exception:
            logger.warning(
                "AD-1213: approval_inbox settings could not be read; delegated approvals "
                "are treated as switched off and the Captain decides",
                exc_info=True,
            )
            return False

    def decision_lock(self, queue: str) -> asyncio.Lock:
        """The one lock serializing check-and-commit on ``queue``."""
        if type(queue) is not str or queue not in self._locks:
            raise ValueError(f"AD-1213: unknown approval queue {queue!r}")
        return self._locks[queue]

    async def decide(
        self, agent_id: str, *, queue: str, request_id: str, approve: bool, reason: str,
    ) -> DecisionOutcome:
        """Check one agent's decision on one request and commit it if it is permitted.

        Never raises except ``CancelledError``: every failure is a refusal, and a
        refusal leaves the request pending for the Captain. Inside the lock the
        audit entry is appended before the commit, and an append that fails
        refuses, so no delegated decision is committed before its entry is
        appended. A commit that raises is reconciled against the committed row:
        still pending, and the entry is voided; recorded as this decision, and
        the decision stands, with the Captain's notification and any fulfilment
        attempted as usual; anything else leaves the entry unvoided for the
        Captain to check. Reconciling does not replay
        what the store itself skipped after its commit -- publishing its cache,
        recording trust, emitting ``DECIDED`` -- a store gap the Captain's own
        routes share. The Captain's notification follows the commit; fulfilment
        runs after the lock is released.

        The self-requisition bar is judged on the work-item chain re-read inside
        the lock, immediately before the commit and within the wait budget. The
        chain is also read once before the lock, so a work-item store that is
        wedged when the agent calls never reaches the Captain's lock. The two
        stores share no transaction: a reassignment committed while the decision
        itself is being written is not caught.

        AD-1214: a matched pre-clearance, and both flags, are re-read immediately
        after the commit, inside the lock, and that re-read is the linearisation
        point: a revocation, expiry or switch-off that completes before it makes the
        decision notify (after a switch-off, without an offer), and one that
        completes after it does not.
        """
        if type(queue) is not str or queue not in QUEUES:
            return _refused(queue, request_id, Refusal.UNKNOWN_QUEUE)
        if not self.enabled():
            return _refused(queue, request_id, Refusal.NOT_ENABLED)
        text = reason.strip() if type(reason) is str else ""
        if type(approve) is not bool or not text or len(text) > MAX_REASON_CHARS:
            return _refused(queue, request_id, Refusal.INVALID_DECISION)
        store = self._queues[queue]
        if store is None:
            return _refused(queue, request_id, Refusal.NOT_ENABLED)
        if self._audit_log is None:  # an unaudited decision is never taken
            return _refused(queue, request_id, Refusal.AUDIT_UNAVAILABLE)
        audit_log = self._audit_log
        try:
            identity = self._resolve(agent_id)
        except Exception as exc:
            logger.warning(
                "AD-1213: decider %s could not be resolved to a post (%s: %s); %s request %s "
                "stays with the Captain",
                str(agent_id)[:64], type(exc).__name__, exc, queue, str(request_id)[:12],
            )
            return _refused(queue, request_id, Refusal.DECIDER_UNRESOLVED)
        pending = _PENDING[queue]
        # A lock-free first read: a work-item store that is wedged now stalls this
        # agent, never the Captain's lock. The verdict uses the re-read inside it.
        try:
            first = await store.get(request_id) if _nonblank(request_id) else None
            if first is None:
                return _refused(queue, request_id, Refusal.UNKNOWN_REQUEST)
            if first.status != pending:
                return _refused(queue, request_id, Refusal.NOT_PENDING)
            await self._originators(queue, first)
        except Exception:
            logger.warning(
                "AD-1213: the origin of %s request %s could not be read for %s; the request "
                "stays with the Captain",
                queue, str(request_id)[:12], identity.agent_id, exc_info=True,
            )
            return _refused(queue, request_id, Refusal.STATE_UNREADABLE)
        async with self._locks[queue]:
            try:
                req = await store.get(request_id)
                if req is None:
                    return _refused(queue, request_id, Refusal.UNKNOWN_REQUEST)
                if req.status != pending:
                    return _refused(queue, request_id, Refusal.NOT_PENDING)
                if req.agent_id != first.agent_id or (
                    getattr(req, "work_item_id", None) != getattr(first, "work_item_id", None)
                ):
                    return _refused(queue, request_id, Refusal.STATE_UNREADABLE)
                origin = await asyncio.wait_for(
                    self._originators(queue, req), self._origin_recheck_budget,
                )
                verdict = self._verdict(identity, queue, req, origin, self._clock())
            except Exception:
                logger.warning(
                    "AD-1213: approval authority for %s request %s could not be read for %s; "
                    "the request stays with the Captain",
                    queue, str(request_id)[:12], identity.agent_id, exc_info=True,
                )
                return _refused(queue, request_id, Refusal.STATE_UNREADABLE)
            if verdict.refusal is not None:
                return _refused(queue, request_id, verdict.refusal, verdict)
            # AD-1214: synchronous and cache-only, and only after every refusal -- it widens nothing.
            key, match, offer_hours = self._pre_clearance(identity, queue, req, verdict, approve)
            written, entry = _append_decision(
                audit_log, identity, queue, req, verdict, approve, text,
                pre_clearance_id=None if match is None else match.id,
            )
            if not written:  # the entry precedes the commit, so this refusal commits nothing
                return _refused(queue, request_id, Refusal.AUDIT_UNAVAILABLE, verdict)
            try:
                decided = await store.decide(
                    request_id, approve, reason=text, decided_by=identity.agent_id,
                )
            except asyncio.CancelledError:
                logger.warning(
                    "AD-1213: %s's decision on %s request %s was cancelled while it was being "
                    "recorded; its audit entry stands unvoided and the Captain should check "
                    "the request",
                    identity.agent_id, queue, str(request_id)[:12],
                )
                raise
            except Exception:
                decided = await _reconcile_failed_commit(
                    store, audit_log, identity, queue, req, entry, approve,
                )
                if decided is None:
                    return _refused(queue, request_id, Refusal.STATE_UNREADABLE, verdict)
            if decided is None:  # an unknown id: the store wrote nothing
                _void_decision(audit_log, identity, queue, req, entry)
                return _refused(queue, request_id, Refusal.UNKNOWN_REQUEST, verdict)
            lapsed = match  # AD-1214: the linearisation point -- are both flags and the match still live?
            armed = lapsed is None or _pre_clearance_armed(self._settings)
            match = confirm_pre_clearance(self._pre_clearances, key, match) if armed else None
            if lapsed is not None and match is None:
                _record_lapse(audit_log, identity, queue, req, lapsed, entry, switched_off=not armed)
        if match is not None:  # AD-1214: audited above; the Captain pre-cleared this exact class
            notified = False
            logger.info(
                "AD-1214: %s's decision on %s request %s matched pre-clearance %s; it is audited and "
                "the Captain is not notified", identity.agent_id, queue, str(request_id)[:12], match.id[:12],
            )
        else:
            notified = self._notify_captain(
                identity, queue, decided, verdict, approve, text,
                offer_key=key if armed else None, offer_hours=offer_hours,  # switched off: no offer
            )
        if queue != "capability":
            return DecisionOutcome(
                queue, request_id, status=str(getattr(decided, "status", "")), role=verdict.role,
                request_class=verdict.request_class, audited=True, notified=notified,
                pre_cleared=match is not None,
            )
        fulfilled = await self._fulfilled(store, decided, approve)
        try:  # report the state the store holds now, as the Captain's route does
            current = await store.get(request_id) or decided
        except Exception:
            current = decided
        return DecisionOutcome(
            queue, request_id, status=str(getattr(current, "status", "")), role=verdict.role,
            request_class=verdict.request_class, fulfilled=fulfilled, audited=True,
            notified=notified, pre_cleared=match is not None,
        )

    async def list_reviewable(
        self, agent_id: str, *, limit: int = 10,
    ) -> tuple[list[ReviewableRequest], bool]:
        """An advisory snapshot, taken without the lock: what ``agent_id`` may decide now or after the grace.

        Oldest first within each queue; returns ``(items, more)``. Raises
        :class:`DelegatedApprovalRefused` when the feature is off or the decider
        does not resolve.
        """
        if not self.enabled():
            raise DelegatedApprovalRefused(Refusal.NOT_ENABLED)
        try:
            identity = self._resolve(agent_id)
        except Exception as exc:
            raise DelegatedApprovalRefused(Refusal.DECIDER_UNRESOLVED) from exc
        items: list[ReviewableRequest] = []
        more = False
        skipped = 0
        for queue in QUEUES:
            store = self._queues[queue]
            if store is None or more:
                continue
            try:
                pending = sorted(await store.list_pending(), key=_age)
            except Exception:
                skipped += 1
                continue
            for req in pending:
                try:
                    origin = await self._originators(queue, req)
                    verdict = self._verdict(identity, queue, req, origin, self._clock())
                    eligible = verdict.allowed or verdict.refusal is Refusal.GRACE_PERIOD
                    entry = _reviewable(queue, req, verdict) if eligible else None
                except Exception:
                    skipped += 1
                    continue
                if entry is None:
                    continue
                if len(items) >= limit:
                    more = True
                    break
                items.append(entry)
        if skipped:
            logger.warning(
                "AD-1213: %d request read(s) failed while listing reviewable requests for %s; "
                "those requests were left off the list and stay with the Captain",
                skipped, identity.agent_id,
            )
        return items, more

    def record_captain_decision(self, queue: str, decided: Any) -> None:
        """Audit a Captain decision while the feature is on. Never raises and never blocks the Captain."""
        try:
            if not self.enabled():
                return
            if self._audit_log is None:
                logger.warning(
                    "AD-1213: the Captain's decision on %s request %s is recorded but not "
                    "audited: no audit log is wired",
                    queue, str(getattr(decided, "id", ""))[:12],
                )
                return
            try:
                request_class = (
                    classify_capability_request(decided, tool_registry=self._tool_registry)
                    if queue == "capability" else classify_skill_request(decided)
                )
            except Exception:  # recorded as unclassifiable in the entry itself
                request_class = RequestClass.UNCLASSIFIABLE
            self._audit_log.append(category=AUDIT_CATEGORY, detail=_audit_detail(
                queue, decided, decider_id=_CAPTAIN, role=DeciderRole.CAPTAIN,
                decider_post=_CAPTAIN, approve=getattr(decided, "status", None) == "approved",
                request_class=request_class, verdict=None,
                reason=getattr(decided, "decision_reason", ""),
            ))
        except Exception:
            logger.warning(
                "AD-1213: auditing the Captain's decision on a %s request failed; the decision "
                "itself stands",
                queue, exc_info=True,
            )

    def _registered(self, agent_id: Any) -> tuple[str, str, Any] | None:
        """``(agent_type, pool, post)`` for exactly this registered agent, else None; a raising lookup propagates."""
        if self._agents is None or self._ontology is None or not _nonblank(agent_id):
            return None
        agent = self._agents.get(agent_id)
        if agent is None or getattr(agent, "id", None) != agent_id:
            return None
        agent_type = getattr(agent, "agent_type", None)
        pool = getattr(agent, "pool", "")
        if not _nonblank(agent_type) or type(pool) is not str:
            return None
        post = self._ontology.get_post_for_agent(agent_type)
        return (agent_type, pool, post) if _valid_post(post) else None

    def _resolve(self, agent_id: str) -> _Identity:
        """The decider, strictly (P14): this exact registered agent, at a post that is not the Captain's."""
        found = self._registered(agent_id)
        if found is None or found[2].id == _CAPTAIN:
            raise LookupError("AD-1213: the decider holds no post in the chain of command")
        agent_type, pool, post = found
        return _Identity(agent_id=agent_id, agent_type=agent_type, pool=pool, post=post)

    def _chain(self, post: Any) -> list[Any]:
        """``[post, superior, ..., captain]`` with every link a valid post; anything else raises."""
        chain = list(self._ontology.get_chain_of_command(post.id))  # type: ignore[union-attr]
        if not chain or not all(_valid_post(link) for link in chain) or chain[0].id != post.id:
            raise LookupError("AD-1213: the chain of command could not be read")
        return chain

    async def _originators(self, queue: str, req: Any) -> frozenset[str]:
        """Q11: the requester, and every creator and assignee of the linked work item and its ancestors."""
        names: list[Any] = [getattr(req, "agent_id", None)]
        current = getattr(req, "work_item_id", None) if queue == "capability" else None
        if current not in (None, ""):
            if self._work_items is None:
                raise LookupError("AD-1213: a linked work item cannot be read without the work-item store")
            seen: set[Any] = set()
            while current is not None:
                if current in seen or len(seen) >= MAX_ORIGIN_ITEMS:
                    raise LookupError("AD-1213: the work-item chain has a cycle or is too long")
                item = await self._work_items.get_work_item(current)
                if item is None:
                    raise LookupError("AD-1213: a work item in the chain is missing")
                seen.add(current)
                names += [getattr(item, "created_by", None), getattr(item, "assigned_to", None)]
                current = item.parent_id
        return frozenset(name for name in names if _nonblank(name))

    def _verdict(self, identity: _Identity, queue: str, req: Any, origin: frozenset[str], now: Any) -> Verdict:
        """Synchronous, so the decision lock is never held across I/O on another store.

        Reads the authority store and the grace only on a First Officer route, so
        an outage there never blocks a chief. The caller refuses on any exception.
        """
        settings = self._settings()  # type: ignore[misc]
        if settings.delegated_approvals_enabled is not True:  # Q10: re-read inside the lock
            return Verdict(Refusal.NOT_ENABLED)
        own = bool(identity.names & origin)
        if queue == "capability":
            request_class = classify_capability_request(req, tool_registry=self._tool_registry)
            chief_barred = False
        else:
            request_class = classify_skill_request(req)
            chief_barred = getattr(req, "source", None) == "chief"  # the filer is not stored
        requester = self._registered(getattr(req, "agent_id", None))
        if requester is None:
            refusal = Refusal.OWN_REQUISITION if own else Refusal.REQUESTER_UNRESOLVED
            return Verdict(refusal, request_class=request_class)
        route = authority_route(self._chain(requester[2]), identity.post)
        delegation = unavailable = grace = None
        if route is DeciderRole.FIRST_OFFICER:
            if self._authority is None:
                raise LookupError("AD-1213: no approval-authority store is wired")
            delegation = self._authority.live(FIRST_OFFICER_DELEGATION)
            unavailable = self._authority.live(CAPTAIN_UNAVAILABLE)
            grace = settings.approval_grace_seconds
        return evaluate(
            request_class=request_class, route=route, own_requisition=own,
            chief_barred=chief_barred, delegation_live=delegation is not None,
            delegation_id=getattr(delegation, "id", None),
            captain_unavailable=unavailable is not None, grace_seconds=grace,
            created_at=getattr(req, "created_at", None), now=now,
        )

    def _pre_clearance(
        self, identity: _Identity, queue: str, req: Any, verdict: Verdict, approve: bool,
    ) -> tuple[PreClearanceKey | None, PreClearance | None, int]:
        """AD-1214: ``(key, live pre-clearance, offer hours)``; synchronous, cache-only, never raises."""
        if self._pre_clearances is None:
            return None, None, 0
        try:
            settings = self._settings()  # type: ignore[misc]
            if settings.decision_pre_clearance_enabled is not True:
                return None, None, 0
            requester = self._registered(getattr(req, "agent_id", None))
            key = None if requester is None else pre_clearance_key(
                queue=queue,
                kind=_kind_and_target(queue, req)[0],
                target=getattr(req, "target" if queue == "capability" else "skill_id", None),
                install_payload=getattr(req, "payload", None),
                request_class=getattr(verdict.request_class, "value", None),
                requester_department=getattr(requester[2], "department_id", None),
                decider_post=getattr(identity.post, "id", None),
                decider_role=getattr(verdict.role, "value", None),
                approve=approve,
            )
            if key is None:
                return None, None, 0
            ttl = (settings.decision_pre_clearance_default_ttl_hours, settings.decision_pre_clearance_max_ttl_hours)
            return key, self._pre_clearances.lookup(key), min(ttl)  # the default, clamped to the ceiling
        except Exception:
            logger.warning(
                "AD-1214: the pre-clearance for %s's decision on %s request %s could not be read; "
                "the decision proceeds and the Captain is notified as usual",
                identity.agent_id, queue, str(getattr(req, "id", ""))[:12], exc_info=True,
            )
            return None, None, 0

    def _notify_captain(
        self, identity: _Identity, queue: str, decided: Any, verdict: Verdict, approve: bool, reason: str,
        *, offer_key: PreClearanceKey | None = None, offer_hours: int = 0,
    ) -> bool:
        """Tell the Captain, in the notification drawer, who decided what (log-and-degrade)."""
        request_id = str(getattr(decided, "id", ""))
        if self._notify is None:
            logger.warning(
                "AD-1213: %s's decision on %s request %s is recorded and audited, but no "
                "notifier is wired to tell the Captain",
                identity.agent_id, queue, request_id[:12],
            )
            return False
        book = self._pre_clearances
        offer = None if offer_key is None or book is None else make_offer(book, offer_key, hours=offer_hours)
        try:
            kind, target = _kind_and_target(queue, decided)
            verb = "approved" if approve else "denied"
            title = f"Delegated decision: {verb} {kind} request {request_id[:8]}"
            note_reason = reason[:_NOTE_REASON_CHARS].rstrip().rstrip(".")  # the detail adds the period
            detail = (
                f"{_ROLE_LABEL[verdict.role]} {identity.agent_id} {verb} "  # type: ignore[index]
                f"{decided.agent_id}'s {kind} request for '{target[:_NOTE_TARGET_CHARS]}'. "
                f"Class: {verdict.request_class.value}. Reason: {note_reason}. "
                "Not pre-cleared (AD-1213)."
            )
            if offer is None:
                self._notify(identity.agent_id, title, detail=detail, notification_type="info")
            else:  # AD-1214: the offer sentence, and the marker the HXI's Pre-clear control reads
                self._notify(
                    identity.agent_id, title, detail=f"{detail} {offer[1]}", notification_type="info",
                    action_url=offer[0],
                )
        except Exception:
            logger.warning(
                "AD-1213: %s's decision on %s request %s is recorded and audited, but the "
                "Captain's notification failed",
                identity.agent_id, queue, request_id[:12], exc_info=True,
            )
            return False
        return True

    async def _fulfilled(self, store: Any, decided: Any, approve: bool) -> bool:
        """The Captain route's own fulfilment; a failure leaves the approval for the Captain's retry (BF-722)."""
        request_id = str(getattr(decided, "id", ""))[:12]
        if self._fulfil is None:
            logger.warning(
                "AD-1213: no fulfilment is wired, so decided request %s is not fulfilled; the "
                "Captain can retry it",
                request_id,
            )
            return False
        try:
            return await self._fulfil(store, decided, approve=approve) is True
        except Exception:
            logger.warning(
                "AD-1213: fulfilling request %s after a delegated decision failed; the decision "
                "stands and the Captain can retry the fulfilment",
                request_id, exc_info=True,
            )
            return False


def _append_decision(
    audit_log: AuditSink, identity: _Identity, queue: str, req: Any, verdict: Verdict,
    approve: bool, reason: str, *, pre_clearance_id: str | None = None,
) -> tuple[bool, Any]:
    """Append a delegated decision's entry before it is committed; ``(False, None)`` refuses the agent."""
    try:
        entry = audit_log.append(category=AUDIT_CATEGORY, detail=_audit_detail(
            queue, req, decider_id=identity.agent_id, role=verdict.role,  # type: ignore[arg-type]
            decider_post=identity.post.id, approve=approve,
            request_class=verdict.request_class, verdict=verdict, reason=reason,
            status="approved" if approve else "denied", pre_clearance_id=pre_clearance_id,
        ))
    except Exception:
        logger.error(
            "AD-1213: the audit entry for %s's decision on %s request %s could not be "
            "appended; nothing was committed and the request stays with the Captain",
            identity.agent_id, queue, str(getattr(req, "id", ""))[:12], exc_info=True,
        )
        return False, None
    return True, entry


def _void_decision(audit_log: AuditSink, identity: _Identity, queue: str, req: Any, entry: Any) -> None:
    """Record that an appended decision entry was never committed (the chain is append-only)."""
    request_id = str(getattr(req, "id", ""))
    try:
        audit_log.append(category=AUDIT_VOID_CATEGORY, detail=json.dumps({
            "v": 1,
            "queue": queue,
            "request_id": request_id,
            "decider_id": identity.agent_id,
            "voids_sequence": getattr(entry, "sequence", None),
            "voids_hash": getattr(entry, "entry_hash", None),
        }, sort_keys=True, separators=(",", ":")))
    except Exception:
        logger.error(
            "AD-1213: %s's decision on %s request %s was not committed, and voiding its "
            "audit entry failed too; the log holds an entry for a decision that did not "
            "happen, and the request stays with the Captain",
            identity.agent_id, queue, request_id[:12], exc_info=True,
        )


def _pre_clearance_armed(settings: Callable[[], Any] | None) -> bool:
    """AD-1214: both approval_inbox flags, read live now, are exactly ``True``; a failed read counts as off."""
    try:
        inbox = settings()  # type: ignore[misc]
        return inbox.delegated_approvals_enabled is True and inbox.decision_pre_clearance_enabled is True
    except Exception:
        logger.warning(
            "AD-1214: approval_inbox settings could not be re-read when a pre-cleared decision was "
            "committed; pre-clearance is treated as switched off and the Captain is notified without an offer",
            exc_info=True,
        )
        return False


def _record_lapse(
    audit_log: AuditSink, identity: _Identity, queue: str, req: Any, lapsed: PreClearance, entry: Any,
    *, switched_off: bool,
) -> None:
    """AD-1214: correct a decision entry that says pre-cleared when its pre-clearance lapsed before the commit."""
    request_id = str(getattr(req, "id", ""))
    cause = "switched_off" if switched_off else "expired_or_revoked"
    try:
        audit_log.append(category=PRE_CLEARANCE_AUDIT_CATEGORY, detail=json.dumps({
            "v": 1,
            "action": "lapsed_before_commit",
            "cause": cause,
            "queue": queue,
            "request_id": request_id,
            "decider_id": identity.agent_id,
            "pre_clearance_id": lapsed.id,
            "entry_hash": getattr(entry, "entry_hash", None),
        }, sort_keys=True, separators=(",", ":")))
    except Exception:
        logger.error(
            "AD-1214: pre-clearance %s lapsed (%s) before %s's decision on %s request %s was committed, "
            "and recording that correction failed; the decision entry still reads pre-cleared, and "
            "the Captain is notified",
            lapsed.id[:12], cause, identity.agent_id, queue, request_id[:12], exc_info=True,
        )
        return
    logger.info(
        "AD-1214: pre-clearance %s lapsed (%s) before %s's decision on %s request %s was committed; the "
        "correction is audited and the Captain is notified",
        lapsed.id[:12], cause, identity.agent_id, queue, request_id[:12],
    )


async def _reconcile_failed_commit(
    store: Any, audit_log: AuditSink, identity: _Identity, queue: str, req: Any, entry: Any,
    approve: bool,
) -> Any | None:
    """The decided request when a raising ``decide`` had committed anyway, else None.

    Called inside ``except``, so ``exc_info`` is the commit's exception. A store
    commits, then publishes its cache, then records trust and emits ``DECIDED``,
    so a raise can follow a persisted decision -- even one the cache does not
    show yet. The committed row is therefore read on a separate connection
    (``durable=True``): only a row that still reads pending proves nothing was
    recorded, and only then is the entry voided.
    """
    request_id = str(getattr(req, "id", ""))
    try:
        current = await store.get(request_id, durable=True)
    except Exception:
        logger.error(
            "AD-1213: %s's decision on %s request %s raised and the request could not be "
            "re-read, so whether it was recorded is unknown; its audit entry stands "
            "unvoided and the Captain should check the request",
            identity.agent_id, queue, request_id[:12], exc_info=True,
        )
        return None
    status = getattr(current, "status", None)
    if status == _PENDING[queue]:
        logger.error(
            "AD-1213: recording %s's decision on %s request %s failed; nothing was "
            "recorded, its audit entry is voided, and the request stays with the Captain",
            identity.agent_id, queue, request_id[:12], exc_info=True,
        )
        _void_decision(audit_log, identity, queue, req, entry)
        return None
    if status == ("approved" if approve else "denied") and (
        getattr(current, "decided_by", None) == identity.agent_id
    ):
        logger.warning(
            "AD-1213: %s's decision on %s request %s was recorded, but a step after the "
            "commit raised; the decision stands and notification and any fulfilment are "
            "attempted as usual, but the store's own cache, trust and DECIDED steps after "
            "its commit may not have run",
            identity.agent_id, queue, request_id[:12], exc_info=True,
        )
        return current
    logger.error(
        "AD-1213: %s's decision on %s request %s raised, and the request now reads "
        "status %r; its audit entry stands unvoided and the Captain should check the "
        "request",
        identity.agent_id, queue, request_id[:12], status, exc_info=True,
    )
    return None


def captain_decision_guard(runtime: Any, queue: str) -> contextlib.AbstractAsyncContextManager[Any]:
    """What a Captain route holds across check-and-commit: the service's lock, or nothing while off.

    ``isinstance`` rather than truthiness, so a ``MagicMock`` runtime -- or any
    runtime without a real service -- keeps the Captain path byte-identical.
    """
    service = getattr(runtime, "delegated_approvals", None)
    if not isinstance(service, DelegatedApprovalService):
        return contextlib.nullcontext()
    return service.decision_lock(queue)


def audit_captain_decision(runtime: Any, queue: str, decided: Any) -> None:
    """Audit a Captain decision when a real service is wired; a no-op otherwise."""
    service = getattr(runtime, "delegated_approvals", None)
    if isinstance(service, DelegatedApprovalService):
        service.record_captain_decision(queue, decided)
