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
        # Signatures already proposed, so a fault that keeps recurring raises
        # one decision rather than one per occurrence. Cleared when the fault
        # resolves, so a repair that does not hold can be proposed again.
        self._proposed: set[str] = set()

    @property
    def targets(self) -> tuple[str, ...]:
        return resolve_targets(self._config)

    async def on_fault_event(self, event: Any) -> None:
        """Listener for ``FAULT_REPORTED`` / ``FAULT_RESOLVED``.

        Runtime listeners receive ``{"type": ..., "data": {...}}`` with the
        domain fields nested under ``data``. Never raises: this runs inline on
        the event bus and a fault here must not disturb the emitter.
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
                self._proposed.discard(signature)
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
            if signature in self._proposed:
                return

            await self.propose(signature)
        except Exception:
            logger.warning(
                "AD-1172: fault event handling raised; no repair was proposed "
                "and the fault report is unaffected", exc_info=True,
            )

    async def propose(self, signature: str) -> Any | None:
        """Build the brief and file the dispatch decision. Returns the request."""
        fault = self._faults.get(signature) if self._faults is not None else None
        if fault is None:
            return None

        brief = await self.build_brief(fault)
        request = await self._file_dispatch_request(brief)
        if request is not None:
            self._proposed.add(signature)
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
                    "params": {
                        "fault_id": brief.fault_id,
                        "signature": brief.signature,
                        "targets": ",".join(self.targets),
                        "brief": brief.render_markdown()[:_BRIEF_PREVIEW_MAX],
                    },
                    "scope_key": brief.tool_id,
                    "session_id": None,
                    "thread_id": brief.thread_id,
                },
                rationale=(
                    f"The {brief.tool_id} tool has failed the same way "
                    f"{brief.occurrences} times. Approving dispatches a repair "
                    f"brief to the harness you choose: {', '.join(self.targets)}."
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
