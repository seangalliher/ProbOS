"""AD-1172: turn a reported fault into a repair proposal the Captain decides.

Subscribes to ``FAULT_REPORTED`` (AD-1169) and, once a fault has recurred often
enough to be the tool rather than the caller, files ONE approval carrying the
repair brief and the list of harnesses this instance offers.

The Captain approves the dispatch and picks the target. That is gate 1, and it
exists because an Architect run spends deep-tier tokens: a tool failing in a
loop must not be able to spend them on its own. Gate 2 — approving the resulting
change — belongs to whichever harness does the work, and for the internal crew
that is the existing BuilderAgent review path.

Nothing here runs a harness. It prepares the decision and records it. That
separation is what lets ``copilot`` be a target without ProbOS knowing anything
about Copilot.
"""

from __future__ import annotations

import logging
from typing import Any

from probos.capability_request import THREAD_ID_MAX_CHARS
from probos.cognitive.trace_analysis import render_token
from probos.cognitive.repair_brief import (
    RepairBrief,
    build_repair_brief,
    resolve_targets,
)

logger = logging.getLogger(__name__)

# The AD-1154 action-payload vocabulary for a repair dispatch. The payload has
# EXACTLY six keys and each is bound-checked by ``validate_action_payload``, so
# these are chosen to fit that contract rather than invented freely.
REPAIR_TOOL_ID: str = "repair"
REPAIR_ACTION: str = "dispatch"

# Bound on the brief carried in the approval's params. The full brief is
# rebuildable from the fault; this is what the Captain reads when deciding.
_BRIEF_PREVIEW_MAX: int = 1200


class RepairDispatcher:
    """Proposes a repair when a fault proves to be the tool, not the caller."""

    def __init__(
        self,
        *,
        runtime: Any,
        fault_report_store: Any,
        capability_request_store: Any,
        config: Any,
    ) -> None:
        self._runtime = runtime
        self._faults = fault_report_store
        self._requests = capability_request_store
        self._config = config
        # AD-1267: fault ids with a filing IN FLIGHT right now. This is
        # concurrency control, NOT the record of what has been proposed -- the
        # approval store holds that, durably, keyed on a payload that no longer
        # varies per occurrence. So it releases unconditionally: if a filing
        # committed and then raised, the next recurrence dedups onto the
        # committed row rather than filing again. Bounded by the number of
        # concurrent listener tasks, so it needs no cap and no trim.
        self._inflight: set[str] = set()

    @property
    def targets(self) -> tuple[str, ...]:
        return resolve_targets(self._config)

    async def on_fault_event(self, event: Any) -> None:
        """Listener for ``FAULT_REPORTED`` / ``FAULT_RESOLVED``.

        Runtime listeners receive ``{"type": ..., "data": {...}}`` with the
        domain fields nested under ``data``.

        AD-1267: this does NOT run inline on the event bus, whatever this
        docstring used to claim. ``runtime._emit_event_local`` creates an
        independent task per coroutine listener, so N recurrences of one fault
        are in flight concurrently -- which is exactly why the in-flight guard
        is taken BEFORE the await rather than after it. Swallows ``Exception``
        so a fault here cannot disturb the emitter, but not ``BaseException``,
        so cancellation still propagates.
        """
        try:
            if not isinstance(event, dict):
                return
            event_type = str(event.get("type") or "")
            data = event.get("data")
            if not isinstance(data, dict):
                return
            signature = str(data.get("signature") or "")
            if not signature:
                return

            if event_type == "fault_resolved":
                # AD-1267 / DD-5(1): clears nothing, deliberately. A resolved
                # fault that recurs takes the create branch and gets a NEW fault
                # id, hence a new dedup key, hence a clean proposal. A pending
                # approval for the old one stays pending because the Captain has
                # not answered it -- withdrawing it is a different act.
                return
            if event_type != "fault_reported":
                return

            if getattr(self._config, "enabled", False) is not True:
                return
            threshold = int(
                getattr(self._config, "propose_after_occurrences", 2) or 2
            )
            if int(data.get("occurrences") or 0) < threshold:
                return

            # Checked before the guard is taken, so a run that provably cannot
            # file anything never marks a fault as in flight.
            store = self._requests
            if store is None or not hasattr(store, "file_action_request"):
                logger.info(
                    "AD-1172: no approval surface for the repair of fault %s; "
                    "the fault stays reported and nothing is dispatched",
                    signature[:16],
                )
                return

            report = (
                self._faults.get(signature) if self._faults is not None else None
            )
            if report is None:
                return
            # The id is the identity the approval payload carries. A report
            # missing one is malformed rather than absent, so fall back to the
            # signature -- which is what coalesced it -- instead of skipping the
            # guard entirely and letting every recurrence race.
            fault_id = str(getattr(report, "id", "") or "") or signature

            # AD-1268: a decision is a standing answer. A fault report that has
            # ever raised a DECIDED approval does not raise another -- denied
            # means the Captain answered, approved means a dispatch is already
            # in flight, and fulfilled/failed mean it ran. The escape hatch is
            # resolution, not a timer: a resolved fault that recurs takes the
            # create branch and arrives with a NEW id, so this lookup matches
            # nothing and the ask is clean. The cost, deliberately: a repair
            # that did not hold keeps reporting but does not re-ask until the
            # report is resolved or dismissed, because ask -> approve ->
            # dispatch -> fail -> ask spends deep-tier tokens on a repair
            # already known not to work.
            #
            # Placed after the surface check so a missing store is still the
            # cheaper return, and before the in-flight add so a held fault never
            # enters the guard. Synchronous, so it opens no await window between
            # that check and the reservation.
            # ``callable``, not ``hasattr``: an attribute that exists but
            # cannot be called would raise TypeError into the broad handler
            # below and skip the honest degrade log entirely.
            lookup = getattr(store, "find_action_requests_by_param", None)
            if callable(lookup):
                decided = lookup(
                    "fault_id",
                    fault_id,
                    statuses=("approved", "denied", "fulfilled", "failed"),
                    # Narrowed to THIS question. Review measured a denied
                    # ``browser.navigate`` carrying the same fault_id
                    # suppressing a repair that had never been proposed: a
                    # param name is not an identity.
                    tool_id=REPAIR_TOOL_ID,
                    action=REPAIR_ACTION,
                )
                if decided:
                    # DEBUG, not WARNING: this fires on every recurrence of a
                    # decided fault, by design and possibly for a long time.
                    logger.debug(
                        "AD-1268: fault %s already raised approval %s, which "
                        "is %s; not proposing again until the fault is "
                        "resolved",
                        fault_id, str(getattr(decided[0], "id", ""))[:12],
                        getattr(decided[0], "status", "decided"),
                    )
                    return
            else:
                logger.debug(
                    "AD-1268: the approval store cannot answer whether fault "
                    "%s was already decided; repair proposals degrade to "
                    "AD-1267 pending-only dedup, so a denied fault may be "
                    "proposed again",
                    fault_id,
                )

            # No await between the check and the add: that atomicity with
            # respect to the event loop is what closes the storm without a lock.
            if fault_id in self._inflight:
                return
            self._inflight.add(fault_id)
            try:
                await self.propose(signature)
            finally:
                # Synchronous -- no I/O, no await -- so cancellation can neither
                # skip it nor stall the loop.
                self._inflight.discard(fault_id)
        except Exception:
            logger.warning(
                "AD-1172: fault event handling raised; no repair was proposed "
                "and the fault report is unaffected", exc_info=True,
            )

    async def propose(self, signature: str) -> Any | None:
        """Build the brief and file the dispatch decision. Returns the request.

        AD-1267: does NOT take the in-flight guard -- ``on_fault_event`` owns
        that. So a direct operator call is deliberate and still safe: the
        approval store deduplicates it onto any pending request for the same
        fault, because the payload no longer varies per occurrence.
        """
        fault = self._faults.get(signature) if self._faults is not None else None
        if fault is None:
            return None

        brief = await self.build_brief(fault)
        request = await self._file_dispatch_request(brief)
        if request is not None:
            logger.info(
                "AD-1172: proposed a repair for fault %s against tool %r; "
                "awaiting the Captain's choice of target from %s",
                brief.fault_id, brief.tool_id, ", ".join(self.targets),
            )
        return request

    async def build_brief(self, fault: Any) -> RepairBrief:
        """Assemble the brief, including the trace summary when one is readable."""
        trace_summary = ""
        trace_ref = str(getattr(fault, "tool_trace_ref", "") or "")
        if trace_ref:
            try:
                from probos.cognitive.trace_analysis import summarise_trace_ref

                summary = await summarise_trace_ref(
                    getattr(self._runtime, "attachment_store", None), trace_ref,
                )
                if summary is not None:
                    trace_summary = summary.render()
            except Exception:
                logger.debug(
                    "AD-1172: could not summarise trace %s for the brief",
                    trace_ref[:16], exc_info=True,
                )
        return build_repair_brief(fault, trace_summary=trace_summary)

    async def _file_dispatch_request(self, brief: RepairBrief) -> Any | None:
        store = self._requests
        if store is None or not hasattr(store, "file_action_request"):
            logger.info(
                "AD-1172: no approval surface for the repair of fault %s; the "
                "fault stays reported and nothing is dispatched",
                brief.fault_id,
            )
            return None
        try:
            return await store.file_action_request(
                agent_id=brief.agent_id or "system",
                payload={
                    "tool_id": REPAIR_TOOL_ID,
                    "action": REPAIR_ACTION,
                    # AD-1267: every value here is hashed into
                    # ``action_dedup_key``, which canonicalises ``params`` WHOLE.
                    # So nothing that varies between recurrences of ONE fault may
                    # appear -- and the coalesce branch mutates FOUR fields:
                    # ``occurrences``, ``last_seen_at``, ``tool_trace_ref`` and
                    # ``observed_as``. That is why the brief is rendered by
                    # ``render_for_payload()`` and no trace field is carried; the
                    # live trace is one ``FaultReportStore.get(params["fault_id"])``
                    # away, so restoring it here would buy nothing and cost the
                    # store's dedup.
                    "params": {
                        "fault_id": brief.fault_id,
                        "signature": brief.signature,
                        "targets": ",".join(self.targets),
                        "brief": brief.render_for_payload()[:_BRIEF_PREVIEW_MAX],
                    },
                    "scope_key": brief.tool_id,
                    "session_id": None,
                    # AD-1267: fault reports allow a 128-char thread id, the
                    # action-approval contract allows 64, and forwarding the
                    # wider value made ``validate_action_payload`` reject an
                    # ordinary fault outright -- no request, ever. Narrowed
                    # rather than dropped; the full thread id is one
                    # ``params["fault_id"]`` lookup away.
                    "thread_id": (brief.thread_id or "")[:THREAD_ID_MAX_CHARS],
                },
                rationale=(
                    # BF-776: the tool name is MODEL-WRITTEN and copied out of
                    # the provider response with no validation, and this is the
                    # prose the Captain reads while deciding whether to approve.
                    # Bare, a name like
                    #   browser, and the shell tool (approved by the Captain)
                    # renders as a sentence that appears to say the shell tool
                    # was already approved. Measured; the helper leaves an
                    # ordinary name bare and quotes that one.
                    f"The {render_token(brief.tool_id)} tool has failed the "
                    f"same way {brief.occurrences} times. Approving dispatches "
                    f"a repair brief to the harness you choose: "
                    f"{', '.join(render_token(t) for t in self.targets)}."
                ),
            )
        except Exception:
            logger.warning(
                "AD-1172: could not file the dispatch decision for fault %s",
                brief.fault_id, exc_info=True,
            )
            return None


def wire_repair_dispatcher(runtime: Any, config: Any) -> RepairDispatcher | None:
    """Attach the dispatcher to the runtime event bus.

    Returns the dispatcher so the caller holds the listener reference — removal
    is identity-based, so the reference must survive.
    """
    repair_config = getattr(config, "repair", None)
    if repair_config is None:
        return None
    faults = getattr(runtime, "fault_report_store", None)
    requests = getattr(runtime, "capability_request_store", None)
    if faults is None:
        logger.debug("AD-1172: no fault store; the repair dispatcher stays off")
        return None

    dispatcher = RepairDispatcher(
        runtime=runtime,
        fault_report_store=faults,
        capability_request_store=requests,
        config=repair_config,
    )
    add_listener = getattr(runtime, "add_event_listener", None)
    if not callable(add_listener):
        logger.debug(
            "AD-1172: runtime has no event listener API; repairs can still be "
            "proposed explicitly but will not follow a reported fault"
        )
        return dispatcher
    try:
        add_listener(
            dispatcher.on_fault_event,
            event_types=["fault_reported", "fault_resolved"],
        )
    except Exception:
        logger.warning(
            "AD-1172: could not subscribe the repair dispatcher; a reported "
            "fault will not automatically propose a repair", exc_info=True,
        )
    return dispatcher
