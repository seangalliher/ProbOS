"""AD-1194: natural-language capability gaps through the AD-854 ladder.

Two capability-gap paths existed and only one was triaged. AD-855's work-item gaps
went through ``capability_triage.triage_and_file``; the ordinary NL path went from
"no agent handles this" straight to the self-modification pipeline, whose approval
gate passes when no console callback is wired -- a serve vessel until its first HXI
slash command, which wires a stdin prompt nobody answers. With
``capability_triage.unified_ladder_enabled`` set, the NL producers file through the
same ladder, and this module is their adapter onto it:

* the unattended branch of ``process_natural_language`` -- task scheduler,
  persistent tasks, workflow cron, correction and build retries -- files a PENDING
  build and designs nothing. The Captain approves it on the capability-request
  surface, whose build fulfiller designs with the context recorded here (BF-744);
* the HXI chat files that same pending request when it proposes a build, so the
  gap's governance (``requires_consensus``) is recorded server-side. The client
  round trip carries no such field, so the Build Agent button designed every agent
  without a consensus gate;
* the attended surfaces -- HXI Build Agent and the shell prompt -- ARE the
  Captain's decision, so they decide the request under the guard and audit the
  capability-request route uses, then design. A-2: a surface designs exactly the
  request it decided -- the HXI click names it by id -- from the row its own
  decision committed, never from the client's body, a cache, or an approval taken
  elsewhere, which designs on its own path.

An NL gap has no requesting agent, so it is filed as ``NL_GAP_REQUESTER``, after
``repair_dispatch``'s precedent. At most one NL build is pending per intent name:
a scheduled task that hits the same gap on every run files one card, and a
sighting that requires consensus raises that card to require it (A-1).

A module of its own because it needs the Captain decision guard, and
``delegated_approvals``, which owns that guard, imports ``capability_triage``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from probos.capability_request import build_requires_consensus
from probos.cognitive.capability_triage import ard_discoverer, design_of, triage_and_file
from probos.delegated_approvals import audit_captain_decision, captain_decision_guard

if TYPE_CHECKING:
    from probos.capability_request import CapabilityRequest, CapabilityRequestStore

logger = logging.getLogger(__name__)

#: The requester an NL gap is filed as. Not an agent id: the Captain-DM notifier
#: and the trust network treat it as they already treat a repair request's.
NL_GAP_REQUESTER = "system"


def successful_execution_context(runtime: Any) -> str:
    """AD-235's design context -- the last execution, when it succeeded -- or ``""``."""
    manager = getattr(runtime, "self_mod_manager", None)
    if manager is None or not manager.was_last_execution_successful():
        return ""
    return manager.format_execution_context()


def requires_consensus_of(request: CapabilityRequest) -> bool:
    """The consensus requirement a build request records."""
    return build_requires_consensus(request.payload)


def recorded_design(request: CapabilityRequest) -> dict[str, Any]:
    """AD-1194 A-2: the design a build request records, as the route's fulfiller derives it."""
    return design_of(request.target, request.rationale, request.payload)


async def find_pending_nl_build(
    store: CapabilityRequestStore, target: str,
) -> CapabilityRequest | None:
    """The pending NL build request already filed for ``target``, if any."""
    for request in await store.list_pending():
        if (
            request.kind == "build"
            and request.agent_id == NL_GAP_REQUESTER
            and request.target == target
        ):
            return request
    return None


async def file_nl_gap(
    runtime: Any,
    intent_meta: dict[str, Any],
    *,
    execution_context: str = "",
) -> CapabilityRequest | None:
    """File an NL capability gap through the ladder, or join the build pending for it.

    AD-1194 A-1: the lookup and the filing hold the store's ``gap_filing_lock``, so
    two producers filing one gap at once file one request. A gap that requires
    consensus raises a pending build that does not -- the store checks and writes
    it under the lock its decisions take, so none lands between -- and a gap never
    weakens one. A build decided first stays as decided, and the gap is filed anew.

    Returns ``None`` -- logged, never raised -- when there is no request store, the
    gap has no intent name, or filing failed; each caller decides how to degrade.
    """
    store = getattr(runtime, "capability_request_store", None)
    name = str(intent_meta.get("name") or "").strip()
    if store is None or not name:
        logger.warning(
            "AD-1194: NL capability gap %r was not filed through the ladder (%s); "
            "no capability request records it",
            name or "?",
            "no capability-request store" if store is None else "no intent name",
        )
        return None
    description = str(intent_meta.get("description") or "")
    parameters = intent_meta.get("parameters")
    requires_consensus = bool(intent_meta.get("requires_consensus", False))
    try:
        async with store.gap_filing_lock:
            pending = await find_pending_nl_build(store, name)
            if pending is not None:
                if not requires_consensus or requires_consensus_of(pending):
                    return pending
                raised = await store.require_build_consensus(pending.id)
                if raised is not None:
                    return raised
                logger.info(
                    "AD-1194: NL build request %s for %r could not be raised to require "
                    "consensus (it was decided first, or the raised payload would not "
                    "load); the gap is filed anew",
                    pending.id[:12], name,
                )
            return await triage_and_file(
                gap_target=name,
                agent_id=NL_GAP_REQUESTER,
                store=store,
                rationale=f"No agent handles the intent '{name}': {description}",
                design_context={
                    "intent_description": description,
                    "parameters": parameters if isinstance(parameters, dict) else {},
                    "requires_consensus": requires_consensus,
                    "execution_context": execution_context,
                },
                gap_class="intent",
                unified=True,
                discover_candidates=ard_discoverer(runtime, description),
            )
    except Exception:
        logger.warning(
            "AD-1194: filing NL capability gap %r through the ladder failed; no "
            "capability request records it",
            name, exc_info=True,
        )
        return None


async def decide_nl_gap(
    runtime: Any,
    request: CapabilityRequest,
    *,
    approve: bool,
    reason: str,
) -> CapabilityRequest | None:
    """Record the Captain's decision on an NL build request, as the decide route does.

    Same guard and audit as ``POST /api/capability-requests/{id}/decide``. Returns
    the request as this approval committed it, and ``None`` for a denial, a request
    no longer pending -- A-2: one approved elsewhere designs on that surface's path,
    not this one's -- a decision the committed row refused, or a store failure.
    """
    store = getattr(runtime, "capability_request_store", None)
    if store is None:
        return None
    try:
        async with captain_decision_guard(runtime, "capability"):
            current = await store.get(request.id)
            if current is None or current.status != "pending":
                return None
            decided = await store.decide(
                request.id, approve, reason=reason, decided_by="captain",
            )
    except Exception:
        logger.warning(
            "AD-1194: recording the Captain's decision on NL build request %s "
            "failed; the request stays as it was",
            request.id[:12], exc_info=True,
        )
        return None
    if decided is not None:
        audit_captain_decision(runtime, "capability", decided)
    return decided if approve else None


@dataclass(frozen=True)
class NlGapApproval:
    """What a Build Agent click approved (``request``), or why it approved nothing."""

    request: CapabilityRequest | None
    refusal: str = ""


async def approve_nl_gap(
    runtime: Any,
    request_id: str,
    *,
    intent_name: str,
    description: str,
    parameters: dict[str, Any],
    reason: str,
) -> NlGapApproval:
    """Approve, as the Captain, the NL build request a Build Agent click names.

    AD-1194 A-2: the click names its request by id -- the proposal carries it -- and
    must name this gap's build with exactly the design the proposal showed; anything
    else, or a request no longer pending, approves nothing and says why. Never files
    a request (A-1): the click carries no consensus requirement.
    """
    store = getattr(runtime, "capability_request_store", None)
    if store is None:
        return NlGapApproval(None, "no capability-request store is wired")
    if not str(request_id or "").strip():
        return NlGapApproval(None, "the proposal names no build request; ask again to file one")
    try:
        request = await store.get(request_id)
    except Exception:
        logger.warning(
            "AD-1194: reading build request %s for a Build Agent click failed; nothing "
            "was approved", str(request_id)[:12], exc_info=True,
        )
        return NlGapApproval(None, "the build request could not be read")
    if request is None:
        return NlGapApproval(None, "no build request with that id is on record")
    if (request.kind, request.agent_id, request.target) != (
        "build", NL_GAP_REQUESTER, str(intent_name or "").strip()
    ):
        return NlGapApproval(None, "the request named is not this gap's build request")
    design = recorded_design(request)
    if (design["intent_description"], design["parameters"]) != (description, dict(parameters or {})):
        return NlGapApproval(
            None,
            "the design sent is not the one this request records; approve the recorded "
            "design, or deny the request and ask again with your guidance",
        )
    if request.status != "pending":
        return NlGapApproval(None, f"the build request is already {request.status}")
    approved = await decide_nl_gap(runtime, request, approve=True, reason=reason)
    if approved is None:
        return NlGapApproval(
            None, "the approval could not be recorded (decided elsewhere first, or the store failed)",
        )
    return NlGapApproval(approved)


async def fulfil_nl_gap(runtime: Any, request: CapabilityRequest) -> None:
    """Mark an approved NL build fulfilled once its agent is active."""
    store = getattr(runtime, "capability_request_store", None)
    if store is None:
        return
    try:
        await store.mark_fulfilled(request.id)
    except Exception:
        logger.warning(
            "AD-1194: the agent for NL build request %s is active but marking the "
            "request fulfilled failed; it stays approved in the inbox",
            request.id[:12], exc_info=True,
        )


async def pending_nl_gap_result(runtime: Any, intent_meta: dict[str, Any]) -> dict[str, Any]:
    """The unattended NL path's ``self_mod`` result: a pending build, never a design."""
    name = str(intent_meta.get("name") or "")
    request = await file_nl_gap(
        runtime, intent_meta, execution_context=successful_execution_context(runtime),
    )
    if request is None:
        return {
            "status": "failed",
            "intent": name,
            "error": "no capability request could be filed for this gap",
        }
    return {
        "status": "pending_approval",
        "intent": name,
        "capability_request_id": request.id,
    }
