"""ProbOS API — Capability-request decision surface (AD-857).

Thin router exposing the pending capability requests filed by agents (the
BLOCKED -> request -> approve/deny loop) and the Captain's decision endpoint.
Backed by ``runtime.capability_request_store`` (AD-853). The store owns
persistence; this router owns the pending-state guard and serialization.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from probos.api_models import CapabilityRequestDecideRequest
from probos.capability_request import CapabilityRequest

# AD-1211: the rung fulfillers, shared with the file-time fast path so there is
# one description of how each kind is fulfilled. ``capability_triage`` imports
# only ``probos.tools.protocol`` (stdlib-only in turn), so this does not pull
# the cognitive stack into the API import chain.
from probos.cognitive.capability_triage import (
    fulfil_build,
    fulfil_grant,
    fulfil_install,
)
from probos.routers.deps import get_runtime

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/capability-requests", tags=["capability-requests"])


def _serialize(req: CapabilityRequest) -> dict[str, Any]:
    """Serialize a CapabilityRequest dataclass to a JSON-safe dict.

    The dataclass has no ``to_dict()``; the field set is built explicitly so
    the wire shape is stable and the HXI card can read ``work_item_id`` (the
    DECIDED event omits it — AD-857 correction #3).
    """
    return {
        "id": req.id,
        "agent_id": req.agent_id,
        "kind": req.kind,
        "target": req.target,
        "rationale": req.rationale,
        "work_item_id": req.work_item_id,
        "status": req.status,
        "created_at": req.created_at,
        "decided_at": req.decided_at,
        "decided_by": req.decided_by,
        "decision_reason": req.decision_reason,
        # AD-1154: the action shape for kind="action"; None for every other
        # kind. Without it the Captain sees a bare ``target`` and nothing else.
        "payload": req.payload,
    }


@router.get("")
async def list_capability_requests(
    status: str = "pending",
    runtime: Any = Depends(get_runtime),
) -> dict[str, Any]:
    """AD-857: List capability requests (pending by default).

    Only the pending view is served today; the ``status`` query param is
    accepted for forward-compatibility but anything other than ``pending``
    returns an empty list (no other view is built in this AD).
    """
    if not runtime.capability_request_store:
        raise HTTPException(status_code=503, detail="capability request store not available")
    if status != "pending":
        return {"requests": [], "status": status}
    pending = await runtime.capability_request_store.list_pending()
    return {"requests": [_serialize(r) for r in pending], "status": "pending"}


@router.post("/{request_id}/decide")
async def decide_capability_request(
    request_id: str,
    req: CapabilityRequestDecideRequest,
    runtime: Any = Depends(get_runtime),
) -> dict[str, Any]:
    """AD-857: Approve or deny a pending capability request.

    Unknown id -> 404. Already-decided (non-pending) -> 400. The store's
    ``decide()`` has no already-decided guard, so the pending check is owned
    here (AD-857 correction #2).

    BF-722: one exception to that guard — an ``approved`` request re-approved is
    a retry of the FULFILMENT, not a re-decision. Fulfilment can fail while the
    approval is durably recorded (``_maybe_fulfil_on_approval`` honest-degrades
    to ``False``), and a blanket guard then refused the only retry the Captain
    had. The retry deliberately does NOT call ``decide()`` again: ``decide()``
    records a trust outcome, so re-deciding would inflate the requesting agent's
    trust once per click. Deciding once and retrying fulfilment separately is
    what keeps trust honest.

    Every other non-pending status still returns 400. A ``denied`` request is
    not re-decidable here, and re-denying an approved one is a revocation — a
    different operation, out of scope.
    """
    if not runtime.capability_request_store:
        raise HTTPException(status_code=503, detail="capability request store not available")
    store = runtime.capability_request_store
    existing = await store.get(request_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="capability request not found")

    standing: dict[str, Any] | None = None
    if existing.status == "pending":
        decided = await store.decide(
            request_id, req.approve, reason=req.reason, decided_by="captain"
        )
        if decided is None:  # pragma: no cover - guarded above, defensive only
            raise HTTPException(status_code=404, detail="capability request not found")
        standing = await _maybe_issue_standing_rule(runtime, decided, req)
    elif existing.status == "approved" and req.approve:
        # BF-722: retry the fulfilment of an approval already on record. No
        # decide(), so no second trust outcome; no standing rule either, since
        # the one decision that could issue it has already been made.
        decided = existing
        logger.info(
            "BF-722: capability request %s is already approved; retrying "
            "fulfilment without re-deciding it",
            request_id[:12],
        )
    else:
        raise HTTPException(
            status_code=400,
            detail=f"capability request already decided (status={existing.status})",
        )

    # AD-1204: after the standing rule, so a resumed turn that immediately
    # consults ``_standing_rule_permits`` sees the rule the same approval just
    # granted rather than racing it.
    fulfilled = await _maybe_fulfil_on_approval(
        runtime, store, decided, approve=req.approve
    )
    # BF-722: re-read so the body reports the state the store actually holds.
    # ``decide()`` now returns a distinct object rather than the cached
    # instance, so a successful ``mark_fulfilled`` no longer shows through it.
    current = await store.get(request_id) or decided
    return {
        "request": _serialize(current),
        "standing_rule": standing,
        # BF-722: lets a caller tell "approved and fulfilled" from "approved,
        # fulfilment pending". The route still returns 200 when this is False:
        # the approval IS durably recorded, and failing the request would
        # discard it.
        "fulfilled": fulfilled,
    }

# ── Fulfilment: what approving a request of each kind actually DOES ────────
#
# AD-1211. Until this AD, approving a pending ``grant``, ``install`` or
# ``build`` recorded the decision and stopped. The card vanished, no grant was
# issued, no package installed, no agent built, no FULFILLED event fired — and
# ``CapabilityGapDriver.on_capability_event`` resumes a blocked work item on
# FULFILLED **only** (DECIDED+approved is deliberately a no-op there), so the
# linked work item stayed blocked permanently.
#
# The comment that stood here through AD-1204 said every other kind "names
# something a separate fulfiller then does... and ``mark_fulfilled`` is called
# by whoever did it". That was true of the file-time fast path in
# ``capability_triage`` and false of this path, where no such actor existed. A
# wrong premise in a comment is worse than the bug: it tells the next reader
# the chain is there.
#
# So: an explicit kind -> fulfiller map. Explicit rather than "any kind nobody
# else fulfils", for the same Minimal Authority reason ``_STANDING_RULE_KINDS``
# is one — a future kind becomes fulfillable when someone decides it should,
# not by inheriting it.
#
#   continue -> the approval IS the fulfilment (AD-1204). The thing asked for
#               is permission to carry on, so once permission is given there is
#               nothing left to do.
#   grant    -> issue the tool grant, then mark fulfilled.
#   install  -> install the dependency, then mark fulfilled.
#   build    -> run the self-mod pipeline, then mark fulfilled if it produced
#               an active agent.
#   action   -> DELIBERATELY ABSENT. An approved action is authorised by a
#               standing grant for NEXT time; the parked action is not replayed
#               from here. The recorded browser session is almost certainly
#               reaped by the time a human answers, and re-running an agentic
#               loop from a REST handler would put an unbudgeted LLM run behind
#               a button. The standing rule ``decide_capability_request``
#               issues just before it gets here is the whole of what an
#               approved action does.
#
# ``continue`` is kept as a literal rather than importing
# ``continue_or_ask.CONTINUE_REQUEST_KIND`` so this router does not pull the
# cognitive agentic stack into its import chain; a drift guard in
# tests/test_ad1204_approval_resumes_the_turn.py asserts the two agree.
_CONTINUE_KIND: str = "continue"

#: What a fulfiller looks like: ``(runtime, store, decided)`` in, the fulfilled
#: request out — or ``None`` when it could not fulfil, which MUST mean
#: ``mark_fulfilled`` was not called (BF-722: the failure is reported and the
#: Captain can retry).
ApprovalFulfiller = Callable[
    [Any, Any, CapabilityRequest], Awaitable[CapabilityRequest | None]
]


async def _fulfil_by_approval_itself(
    _runtime: Any, store: Any, decided: CapabilityRequest
) -> CapabilityRequest | None:
    """AD-1204: ``continue`` — approval is the whole of the fulfilment."""
    return await store.mark_fulfilled(decided.id)


async def _fulfil_grant_request(
    runtime: Any, store: Any, decided: CapabilityRequest
) -> CapabilityRequest | None:
    """AD-1211: issue the tool grant this request asked for, then fulfil it.

    Same function the file-time fast path calls, so there is one description of
    how a grant is issued rather than two that drift.
    """
    tool_registry = getattr(runtime, "tool_registry", None)
    return await fulfil_grant(
        decided.id,
        store=store,
        agent_id=decided.agent_id,
        tool_id=decided.target,
        tool_registration=(
            tool_registry.get(decided.target) if tool_registry is not None else None
        ),
        permission_store=getattr(runtime, "tool_permission_store", None),
        reason=decided.decision_reason or "AD-1211: Captain approved this grant",
        issued_by=decided.decided_by or "captain",
    )


async def _fulfil_install_request(
    runtime: Any, store: Any, decided: CapabilityRequest
) -> CapabilityRequest | None:
    """AD-1211: install what this request asked for, then fulfil it."""
    return await fulfil_install(
        decided.id, store=store, target=decided.target, runtime=runtime
    )


async def _fulfil_build_request(
    runtime: Any, store: Any, decided: CapabilityRequest
) -> CapabilityRequest | None:
    """AD-1211: build the agent this request asked for, then fulfil it."""
    return await fulfil_build(
        decided.id,
        store=store,
        gap_target=decided.target,
        rationale=decided.rationale,
        self_mod_pipeline=getattr(runtime, "self_mod_pipeline", None),
        # BF-744: what the gap actually asked for, carried on the request since
        # file time. Without it an approved build designed an agent with
        # requires_consensus=False no matter how destructive the gap was.
        design_context=decided.payload,
    )


_APPROVAL_FULFILLERS: dict[str, ApprovalFulfiller] = {
    _CONTINUE_KIND: _fulfil_by_approval_itself,
    "grant": _fulfil_grant_request,
    "install": _fulfil_install_request,
    "build": _fulfil_build_request,
}


async def _maybe_fulfil_on_approval(
    runtime: Any,
    store: Any,
    decided: CapabilityRequest,
    *,
    approve: bool,
) -> bool:
    """AD-1211: run the fulfiller for an approved request's kind.

    Returns whether FULFILLED was emitted. Honest-degrade throughout: a denial,
    a kind with no fulfiller, a fulfiller that declines, and a fulfiller that
    raises all yield ``False`` with HTTP 200. The decision is already durably
    recorded by ``decide()``; failing the whole request because the follow-on
    work did not land would discard it, and BF-722 made that ``False`` the
    signal the Captain can retry on.

    A DENIAL deliberately does nothing here. The blocked work item is cancelled
    by ``CapabilityGapDriver._cancel`` off the DECIDED event that ``decide()``
    already emitted, so a denied request leaves nothing stranded.
    """
    if not approve:
        return False
    fulfiller = _APPROVAL_FULFILLERS.get(decided.kind)
    if fulfiller is None:
        logger.info(
            "AD-1211: approved %s request %s has no fulfiller — the approval "
            "itself is the whole effect for this kind",
            decided.kind, decided.id[:12],
        )
        return False
    try:
        updated = await fulfiller(runtime, store, decided)
    except Exception:
        logger.warning(
            "AD-1211: fulfilling approved %s request %s failed; the approval "
            "itself is recorded, but any work item blocked on it stays blocked "
            "until the Captain approves it again",
            decided.kind, decided.id[:12], exc_info=True,
        )
        return False
    if updated is None:
        logger.warning(
            "AD-1211: approved %s request %s could not be fulfilled; the "
            "approval stands and any blocked work item is not resumed",
            decided.kind, decided.id[:12],
        )
        return False
    logger.info(
        "AD-1211: approved %s request %s is fulfilled; any work item blocked "
        "on it now resumes",
        decided.kind, decided.id[:12],
    )
    return True

# AD-1175: request kinds a standing rule can be scoped to.
#
# A standing rule is keyed on (agent, tool_id, action, scope_key), all of which
# come from the request's action payload. So the real precondition is "carries a
# valid action payload", and the kind is how that is declared.
#
# ``continue`` (AD-1164) was the omission this constant exists to correct. Its
# payload is the same validated six-key shape as an ``action`` request --
# ``tool_id="dm_agentic"``, ``action="continue"`` -- so it has always had an
# action shape to scope a rule to. But the guard tested the kind LABEL rather
# than the shape, and refused it.
#
# The consequence was circular and total: AD-1164's second pass re-invokes an
# exhausted turn only while a live standing rule permits it, the only way to get
# that rule is approving a continue request with ``grant_standing``, and that
# path refused the only kind that needed it. Every exhausted turn stopped at
# pass 1 to ask, forever, and the reference vessel's log says so on every run:
# "reached its step limit on pass 1/2 and no standing rule covers continuation".
#
# An explicit allowlist rather than "any kind with a payload", per Minimal
# Authority: a future kind gets a standing rule when someone decides it should,
# not by inheriting one.
_STANDING_RULE_KINDS: frozenset[str] = frozenset({"action", "continue"})


async def _maybe_issue_standing_rule(
    runtime: Any,
    decided: CapabilityRequest,
    req: CapabilityRequestDecideRequest,
) -> dict[str, Any] | None:
    """AD-1154: convert an approval into a scoped, expiring standing rule.

    Returns the issued rule, or ``None`` when one was not issued for any reason.
    Honest-degrade throughout — a missing store, a disabled flag or a failed
    write yields ``None`` with HTTP 200, never a 500. The decision itself is
    already durably recorded by ``decide()``; failing the whole request because
    an *optional* convenience could not be granted would discard it.

    Deliberately narrow, in four ways:

    * Only kinds carrying an action shape to scope a rule to — ``action``
      (AD-1154) and ``continue`` (AD-1164). ``grant`` / ``install`` / ``build``
      describe a capability to acquire rather than an operation to repeat, so
      ``grant_standing`` is logged and ignored rather than rejected.
    * Only on ``approve=True``. A denial issues nothing even when
      ``grant_standing`` is set.
    * Only when ``approval_inbox.standing_rules_enabled`` is on.
    * TTL clamped to ``standing_rule_max_ttl_hours``; omitted TTL falls back to
      ``standing_rule_default_ttl_hours``, itself clamped, so an operator whose
      default exceeds their max still gets the max rather than a 422.

    It does NOT re-execute the parked action and does NOT re-dispatch the
    originating work item: the recorded browser session is almost certainly
    reaped (session TTL 1800s vs human latency), and re-running the agentic loop
    from a REST handler would put an unbudgeted LLM run behind a button.
    """
    if not req.grant_standing:
        return None
    if decided.kind not in _STANDING_RULE_KINDS:
        logger.info(
            "AD-1154: grant_standing ignored for capability request %s — kind "
            "'%s' has no action shape to scope a standing rule to; the "
            "decision itself was recorded normally",
            decided.id[:12],
            decided.kind,
        )
        return None
    if not req.approve:
        logger.info(
            "AD-1154: grant_standing ignored for denied request %s — a denial "
            "never issues a standing rule",
            decided.id[:12],
        )
        return None

    config = getattr(getattr(runtime, "config", None), "approval_inbox", None)
    if not getattr(config, "standing_rules_enabled", False):
        logger.info(
            "AD-1154: grant_standing requested for %s but "
            "approval_inbox.standing_rules_enabled is off; the approval stands "
            "and no durable privilege was granted",
            decided.id[:12],
        )
        return None

    store = getattr(runtime, "action_approval_store", None)
    payload = decided.payload
    if store is None or type(payload) is not dict:
        logger.warning(
            "AD-1154: cannot issue a standing rule for %s — %s. The approval "
            "itself is recorded; the Captain will be asked again next run",
            decided.id[:12],
            "no action-approval store is wired" if store is None
            else "the request carries no decoded action payload",
        )
        return None

    max_hours = int(getattr(config, "standing_rule_max_ttl_hours", 168))
    default_hours = int(getattr(config, "standing_rule_default_ttl_hours", 24))
    requested = req.standing_ttl_hours
    hours = default_hours if requested is None else int(requested)
    hours = max(1, min(hours, max_hours))

    try:
        approval = await store.issue_approval(
            decided.agent_id,
            str(payload.get("tool_id", "")),
            str(payload.get("action", "")),
            scope_key=str(payload.get("scope_key", "")),
            ttl_seconds=hours * 3600.0,
            reason=req.reason,
            issued_by="captain",
        )
    except Exception:
        logger.warning(
            "AD-1154: issuing a standing rule for %s failed; the approval "
            "itself is recorded and the Captain will be asked again next run",
            decided.id[:12],
            exc_info=True,
        )
        return None
    return {
        "id": approval.id,
        "agent_id": approval.agent_id,
        "tool_id": approval.tool_id,
        "action": approval.action,
        "scope_key": approval.scope_key,
        "issued_at": approval.issued_at,
        "expires_at": approval.expires_at,
    }
