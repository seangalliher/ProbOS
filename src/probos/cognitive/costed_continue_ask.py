"""AD-1323 (#1478): ask, with a costed case, instead of stopping at the token budget.

When a turn that is worth more than it has cost stops at ``token_budget``, the
agent used to say so and stop. Armed, it instead promotes the turn to a work
item, files ONE ``kind="continue"`` request whose rationale states the spend,
the value and an estimate, and parks on it. Approval by somebody other than the
asking agent activates a single-use permit; the next pass spends it exactly
once and runs under the extension, never the standing budget.

Nothing here decides who may approve (the existing capability-request surface
does), and nothing here raises the standing budget. Every failure degrades to
today's stop: :func:`file_costed_continue` returns ``None`` and the caller
renders the stop it always rendered.

Default OFF and import-free: callers import this module only after
:func:`continue_extension_armed` is true.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from probos.continue_extension_permits import ContinueExtensionPermit

logger = logging.getLogger(__name__)

RATIONALE_MAX_CHARS = 280
_SIGNAL_OVERSPEND = "overspend"
_RATIONALE_HEAD = (
    "Token budget spent {spent}/{budget}. Value {band} ({vprov}); stakes {stakes} ({sprov}); "
    "verified {verified}."
)
_RATIONALE_TAIL = " Est. {estimate} more tokens to finish; asking for up to {cap}. One extension only."
_STOP_TEXT_MAX_CHARS = 2000


class PermitOutcome:
    """What applying a permit did. Closed set; the caller branches on it, never on a count."""

    APPLIED = "applied"  # won the claim, pass marked started, budget extended (grant may be 0)
    NONE = "none"  # no claimable permit: the pass runs on the standing remainder
    CLAIM_LOST = "claim_lost"  # another actor holds the claim: this pass must not run
    NOT_ADMITTED = "not_admitted"  # claim won, never admitted: left consumed-unstarted for reclaim
    FAILED = "failed"  # claim won, then something failed: no model call, left for reclaim


@dataclass(frozen=True)
class PermitApplication:
    outcome: str
    grant: int = 0


@dataclass(frozen=True)
class AskDecision:
    """Whether to ask, and what the case says. Counts only."""

    eligible: bool
    cap: int = 0
    estimate: int = 0
    reason: str = ""


def continue_extension_armed(
    config: Any, *, promote_after_seconds: Any, token_budget: Any,
) -> bool:
    """Whether the costed continue ask is armed. Every input must be literally valid."""
    if getattr(config, "enabled", False) is not True:
        return False
    if getattr(config, "continue_or_ask_enabled", False) is not True:
        return False
    judgment = getattr(config, "economic_judgment", None)
    if getattr(judgment, "enabled", False) is not True:
        return False
    if getattr(getattr(judgment, "continue_extension", None), "enabled", False) is not True:
        return False
    if type(token_budget) is not int or token_budget < 1:
        return False
    return type(promote_after_seconds) in (int, float) and promote_after_seconds > 0


def _extension_config(config: Any) -> Any:
    return getattr(getattr(config, "economic_judgment", None), "continue_extension", None)


def assess(case: Any, config: Any) -> AskDecision:
    """Cheapest-first eligibility from the turn's costed case. Never raises."""
    try:
        ext = _extension_config(config)
        budget = getattr(case, "budget", None)
        spent = getattr(case, "spent", 0)
        deltas = tuple(getattr(case, "recent_step_deltas", ()) or ())
        if ext is None or type(budget) is not int or budget < 1:
            return AskDecision(False, reason="no_budget")
        if type(spent) is not int or spent < 1 or not deltas:
            return AskDecision(False, reason="no_spend_evidence")
        band = getattr(case, "value_band", None)
        if band is None:
            if ext.ask_when_value_unrecorded is not True:
                return AskDecision(False, reason="value_unrecorded")
        elif band not in ext.min_value_bands:
            return AskDecision(False, reason="value_below_threshold")
        if (
            getattr(case, "verified", False) is not True
            and _SIGNAL_OVERSPEND in tuple(getattr(case, "signals", ()) or ())
        ):
            return AskDecision(False, reason="no_progress_evidence")
        recent = deltas[-3:]
        estimate = (sum(recent) // len(recent)) * ext.assumed_remaining_steps
        cap = budget if ext.max_extension_tokens == 0 else min(ext.max_extension_tokens, budget)
        return AskDecision(True, cap=cap, estimate=max(estimate, 0), reason="eligible")
    except Exception:
        logger.warning(
            "AD-1323: assessing the costed continue case raised; the turn stops as it would "
            "have without the extension", exc_info=True,
        )
        return AskDecision(False, reason="assess_failed")


def build_rationale(case: Any, decision: AskDecision) -> str:
    """The card text: ints and closed-enum tokens only, ASCII, at most 280 characters."""
    from probos.cognitive.economic_judgment_organ import VALUE_PROVENANCE_TOKENS

    band = getattr(case, "value_band", None)
    stakes = getattr(case, "stakes", None)
    vprov = getattr(case, "value_provenance", None)
    sprov = getattr(case, "stakes_provenance", None)
    head = _RATIONALE_HEAD.format(
        spent=int(case.spent),
        budget=int(case.budget),
        band=band if type(band) is str and band.isalpha() else "unrecorded",
        vprov=vprov if vprov in VALUE_PROVENANCE_TOKENS else "unrecorded",
        stakes=stakes if type(stakes) is str and stakes.isalpha() else "unrecorded",
        sprov=sprov if sprov in VALUE_PROVENANCE_TOKENS else "unrecorded",
        verified="yes" if getattr(case, "verified", False) is True else "no",
    )
    tail = _RATIONALE_TAIL.format(estimate=int(decision.estimate), cap=int(decision.cap))
    # The provenance is part of the head; only the tail is ever cut.
    return (head + tail)[:RATIONALE_MAX_CHARS] if len(head) < RATIONALE_MAX_CHARS else head[:RATIONALE_MAX_CHARS]


def validate_snapshot(permit: ContinueExtensionPermit) -> str | None:
    """The first invalid field of a permit's durable snapshot, or ``None``. Never raises.

    A resumed pass is built only from this snapshot, so every field is checked
    strictly: a NULL or wrong-typed value must stop the pass, not be defaulted.
    """
    stop_text = permit.stop_text
    if type(stop_text) is not str or not stop_text.strip() or len(stop_text) > _STOP_TEXT_MAX_CHARS:
        return "stop_text"
    if type(permit.plan_mode) is not bool:
        return "plan_mode"
    configured = permit.configured_budget
    if type(configured) is not int or configured < 1:
        return "configured_budget"
    if extension_amount(permit) < 1:
        return "amount"
    return None


def extension_amount(permit: ContinueExtensionPermit) -> int:
    """Tokens one permit grants: its cap, never above the turn's configured budget. 0 = none."""
    configured = permit.configured_budget
    if type(configured) is not int or configured < 1:
        return 0
    if permit.cap_tokens == 0:
        return configured
    return min(permit.cap_tokens, configured)


async def file_costed_continue(
    runtime: Any,
    *,
    agent_id: str,
    thread_id: str,
    base_task_text: str,
    display_task_text: str,
    case: Any,
    config: Any,
    promote: Callable[[], Awaitable[str | None]],
    work_item_id: str | None,
    passes: int,
    stop_text: str,
    plan_mode: bool,
    configured_budget: int,
    parked: dict[str, str],
) -> str | None:
    """Promote, reserve an unbound permit, file ONE costed ask, park, bind, reconcile. Never raises.

    Returns the filed request id, or ``None`` when the turn should stop as it
    always did: not eligible, no store, promotion failed, the item has already
    had its one ask, or any later step failed (the permit is then voided).
    Nothing is resumable until the permit is bound to the request AND the item is
    parked on it; a decision landing in between is reconciled after the bind.
    """
    store = getattr(runtime, "continue_extension_permit_store", None)
    if store is None:
        return None
    decision = assess(case, config)
    if not decision.eligible:
        logger.info(
            "AD-1323: agent %s turn stops at its token budget without asking (%s)",
            agent_id[:12], decision.reason,
        )
        return None
    request_id = ""
    filed = ""
    item_id = ""
    reserved = False
    bound = False
    try:
        item_id = work_item_id or await promote() or ""
        if not item_id:
            logger.info(
                "AD-1323: agent %s turn could not be promoted, so it stops at its token budget",
                agent_id[:12],
            )
            return None
        from probos.cognitive.continue_or_ask import file_continue_request

        async def _reserve() -> bool:
            nonlocal reserved
            placeholder = await store.reserve_filing(
                agent_id=agent_id, work_item_id=item_id, thread_id=thread_id,
                cap_tokens=decision.cap, stop_text=stop_text, plan_mode=plan_mode,
                configured_budget=configured_budget,
            )
            reserved = placeholder is not None
            return reserved

        async def _bind(filed_id: str) -> bool:
            nonlocal bound, filed
            filed = filed_id  # captured before the await: a cancel mid-commit must still find it
            try:
                bound = bool(await store.bind(item_id, filed_id))
            except Exception:
                logger.warning(
                    "AD-1323: binding the extension permit to request %s failed",
                    filed_id[:12], exc_info=True,
                )
            if not bound:
                await _void_after_failed_filing(store, item_id, filed_id)
            return bound

        request_id = await file_continue_request(
            runtime,
            agent_id=agent_id,
            thread_id=thread_id,
            base_task_text=base_task_text,
            passes=passes,
            display_task_text=display_task_text,
            work_item_id=item_id,
            parked=parked,
            rationale=build_rationale(case, decision),
            before_file=_reserve,
            after_park=_bind,
        )
        if not request_id or parked.get("request_id") != request_id or not bound:
            if reserved and not bound:
                await _void_after_failed_filing(store, item_id, request_id or filed)
            return None
        await reconcile_filed_request(runtime, request_id)
        return request_id
    except asyncio.CancelledError:
        # Cancellation is not a failure to swallow: void whatever this filing made (the
        # request may have been filed, parked or neither), shielded so a second cancel
        # cannot interrupt the cleanup, then let the cancel propagate.
        if item_id:
            await asyncio.shield(_void_after_failed_filing(store, item_id, request_id or filed))
        raise
    except Exception:
        logger.warning(
            "AD-1323: filing the costed continue ask for agent %s failed; the turn stops as "
            "it would have without the extension", agent_id[:12], exc_info=True,
        )
        if reserved and not bound:
            await _void_after_failed_filing(store, item_id, request_id or filed)
        return None


async def _void_after_failed_filing(store: Any, item_id: str, request_id: str) -> None:
    """Void this filing's own still-``requested`` reservation, unbound or bound, never an active one."""
    try:
        await store.void_reservation(item_id, request_id)
    except Exception:
        logger.warning(
            "AD-1323: could not void the extension permit for work item %s; it cannot be "
            "activated unless its request is bound and approved", item_id[:12], exc_info=True,
        )


async def reconcile_filed_request(runtime: Any, request_id: str) -> None:
    """Settle a decision that landed between filing and binding. Never raises.

    An ``approved`` (unfulfilled) request is handed to the runtime's reconciler,
    which re-runs the fulfilment now that the permit is bound; a ``denied`` one
    voids its permit (the driver already cancelled the item). Anything else is
    left alone.
    """
    try:
        requests = getattr(runtime, "capability_request_store", None)
        if requests is None:
            return
        request = await requests.get(request_id)
        status = getattr(request, "status", "")
        if status == "approved":
            reconciler = getattr(runtime, "continue_extension_reconciler", None)
            if reconciler is None:
                logger.warning(
                    "AD-1323: request %s was approved while filing but no reconciler is wired; "
                    "approving it again, or the next startup sweep, fulfils it",
                    request_id[:12],
                )
                return
            await reconciler(request_id)
        elif status == "denied":
            permits = getattr(runtime, "continue_extension_permit_store", None)
            if permits is not None:
                await permits.void(request_id)
    except Exception:
        logger.warning(
            "AD-1323: reconciling request %s after filing failed; approving it again, or the "
            "next startup sweep, settles it", str(request_id)[:12], exc_info=True,
        )


async def apply_permit(
    store: Any,
    *,
    request_id: str,
    agent_id: str,
    work_item_id: str,
    thread_id: str,
    turn_cost: Any,
    await_admission: Callable[[], Awaitable[str]] | None = None,
) -> PermitApplication:
    """Claim the permit for ``request_id``, wait to be admitted, mark the pass, extend once.

    Order is consume, validate, admission, begin_pass, extend: the claim is the
    atomic CAS, the pass is marked started only once it really holds its slot, and
    the budget is raised only once that mark is durable. A pass that was claimed
    but never admitted stays consumed-unstarted, which the startup sweep reclaims.
    """
    try:
        permit = await store.consume(
            request_id, agent_id=agent_id, work_item_id=work_item_id, thread_id=thread_id,
        )
    except Exception:
        logger.warning(
            "AD-1323: claiming the extension permit for request %s failed; the pass runs "
            "on the standing budget remainder", str(request_id)[:12], exc_info=True,
        )
        return PermitApplication(PermitOutcome.NONE)
    try:
        if permit is None:
            row = await store.get(request_id)
            if row is not None and row.state == "consumed":
                return PermitApplication(PermitOutcome.CLAIM_LOST)
            return PermitApplication(PermitOutcome.NONE)
    except Exception:
        logger.warning(
            "AD-1323: reading the permit for request %s after a lost claim failed; the pass "
            "runs on the standing budget remainder", str(request_id)[:12], exc_info=True,
        )
        return PermitApplication(PermitOutcome.NONE)
    try:
        invalid = validate_snapshot(permit)
        if invalid is not None:
            logger.warning(
                "AD-1323: the permit for request %s has an invalid %s; the pass does not run",
                str(request_id)[:12], invalid,
            )
            return PermitApplication(PermitOutcome.FAILED)
        if await_admission is not None and await await_admission() != "admitted":
            return PermitApplication(PermitOutcome.NOT_ADMITTED)
        if not await store.begin_pass(request_id):
            return PermitApplication(PermitOutcome.CLAIM_LOST)
        amount = extension_amount(permit)
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.warning(
            "AD-1323: applying the claimed extension permit for request %s failed; the pass "
            "does not run and the permit is left for reclaim", str(request_id)[:12], exc_info=True,
        )
        return PermitApplication(PermitOutcome.FAILED)
    try:
        grant = int(turn_cost.extend(amount))
    except Exception:
        logger.warning(
            "AD-1323: extending the turn budget for request %s raised after the pass was "
            "marked started; the pass runs on the standing remainder", str(request_id)[:12],
            exc_info=True,
        )
        grant = 0
    if grant < 1:
        logger.warning(
            "AD-1323: the extension for request %s granted nothing; the pass runs on the "
            "standing remainder", str(request_id)[:12],
        )
    return PermitApplication(PermitOutcome.APPLIED, grant)
