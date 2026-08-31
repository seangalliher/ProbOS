"""AD-855: BLOCKED -> request -> approve -> resume work-item gap driver.

Closes the loop on the work-item kanban board when an agent hits a
capability gap while working an item:

  1. ``on_capability_gap`` files a unified CapabilityRequest (AD-853) via the
     triage fast-path (AD-854), transitions the work item to ``blocked``, and
     records ``blocked_reason`` + ``capability_request_id`` in item metadata
     (read-merge-write so pre-existing metadata survives).
  1b. ``block_on_request`` is that second half on its own (AD-1204), for a
     caller that already filed its own request. AD-1164's ``continue`` ask is
     the one caller: a turn that ran out of steps is waiting on a decision
     exactly like a capability gap is, so it parks the same way and resumes
     through the same path below.
  2. ``on_capability_event`` subscribes to CAPABILITY_REQUEST_FULFILLED and
     CAPABILITY_REQUEST_DECIDED. When a blocked item's request is fulfilled it
     resumes the item (``blocked`` -> ``in_progress``) and re-dispatches it
     through the WorkItemRouter. When the request is denied it cancels the
     item, recording the denial reason. An ``approved`` decision is a no-op
     (resume happens only on FULFILLED, which the grant fast-path also emits,
     and which AD-1204's approval handler emits for a ``continue``).

Tier-2 log-and-degrade throughout: missing stores/router never raise.
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Any

from probos.cognitive.capability_triage import triage_and_file
from probos.events import EventType

if TYPE_CHECKING:
    from probos.capability_request import CapabilityRequest, CapabilityRequestStore
    from probos.workforce import WorkItemStore

logger = logging.getLogger(__name__)


class CapabilityGapDriver:
    """Drives the BLOCKED -> request -> approve -> resume work-item loop."""

    def __init__(
        self,
        *,
        runtime: Any,
        work_item_store: "WorkItemStore | None",
        capability_request_store: "CapabilityRequestStore | None",
    ) -> None:
        self._runtime = runtime
        self._work_item_store = work_item_store
        self._request_store = capability_request_store

    async def on_capability_gap(
        self,
        *,
        work_item_id: str,
        gap_target: str,
        agent_id: str,
    ) -> "CapabilityRequest | None":
        """File a capability request and block the work item on it.

        Returns the filed CapabilityRequest, or None when a store is absent or
        the operation degrades.
        """
        store = self._work_item_store
        req_store = self._request_store
        if store is None or req_store is None:
            logger.warning(
                "AD-855: capability gap for work item %s on %r but "
                "work-item/request store absent; degrading (item not blocked)",
                work_item_id, gap_target,
            )
            return None
        try:
            # File first so the request id is available for item metadata and
            # the request carries the originating work_item_id (AD-853 link).
            req = await triage_and_file(
                gap_target=gap_target,
                agent_id=agent_id,
                store=req_store,
                rationale=(
                    f"work item {work_item_id} blocked on capability: {gap_target}"
                ),
                work_item_id=work_item_id,
                tool_registry=getattr(self._runtime, "tool_registry", None),
                permission_store=getattr(self._runtime, "tool_permission_store", None),
                mcp_server_store=getattr(self._runtime, "mcp_server_store", None),
                ontology=getattr(self._runtime, "ontology", None),
                trust_network=getattr(self._runtime, "trust_network", None),
                self_mod_pipeline=getattr(self._runtime, "self_mod_pipeline", None),
                config=self._triage_config(),
            )
            # Transition via the validated state machine.
            blocked = await self.block_on_request(
                work_item_id=work_item_id,
                request_id=req.id,
                reason=gap_target,
            )
            if not blocked:
                return req
            logger.info(
                "AD-855: work item %s BLOCKED on %r; capability request %s filed",
                work_item_id, gap_target, req.id[:12],
            )
            return req
        except Exception:
            logger.warning(
                "AD-855: on_capability_gap failed for work item %s on %r; "
                "degrading",
                work_item_id, gap_target, exc_info=True,
            )
            return None

    async def block_on_request(
        self,
        *,
        work_item_id: str,
        request_id: str,
        reason: str,
    ) -> bool:
        """Park a work item on a capability request it is waiting for.

        Transitions the item to ``blocked`` through the validated state machine
        and records ``blocked_reason`` + ``capability_request_id`` in metadata,
        read-merge-write so pre-existing keys survive. Those two keys are what
        :meth:`on_capability_event` and the board read back, so they are written
        in exactly one place.

        Returns ``True`` when the board was updated, ``False`` when the
        transition was illegal from the item's current status or the id is
        unknown — in which case the caller still holds a filed request and
        should say so rather than pretending the item is parked.

        AD-1204: extracted from :meth:`on_capability_gap` so a ``continue`` ask
        (whose request is filed by ``continue_or_ask``, not by triage) reaches
        the same parking behaviour without duplicating the metadata contract.
        Exceptions propagate: each caller already owns its own degrade
        boundary, and swallowing here would change ``on_capability_gap``'s
        established failure shape.
        """
        store = self._work_item_store
        if store is None:
            logger.warning(
                "AD-855: no work-item store, so work item %s cannot be parked "
                "on request %s; the request stands and the board is unchanged",
                work_item_id, request_id[:12],
            )
            return False
        transitioned = await store.transition_work_item(
            work_item_id, "blocked", source="capability_gap_driver"
        )
        if transitioned is None:
            logger.warning(
                "AD-855: could not transition work item %s to blocked "
                "(unknown id or illegal from current status); request %s "
                "filed but board not updated",
                work_item_id, request_id[:12],
            )
            return False
        # Read-merge-write so pre-existing metadata keys survive.
        item = await store.get_work_item(work_item_id)
        base = dict(item.metadata) if item and item.metadata else {}
        base["blocked_reason"] = reason
        base["capability_request_id"] = request_id
        await store.update_work_item(work_item_id, metadata=base)
        return True

    async def on_capability_event(self, event: dict) -> None:
        """Resume or cancel a blocked work item when its request resolves.

        Subscribed to CAPABILITY_REQUEST_FULFILLED and
        CAPABILITY_REQUEST_DECIDED. Idempotent: acts only while the linked
        work item is still ``blocked``. Never raises.
        """
        try:
            store = self._work_item_store
            req_store = self._request_store
            if store is None or req_store is None:
                logger.warning(
                    "AD-855: capability event received but work-item/request "
                    "store absent; ignoring",
                )
                return
            data = event.get("data") or {}
            event_type = event.get("type") or ""
            request_id = data.get("id")
            if not request_id:
                logger.warning(
                    "AD-855: capability event %s carries no request id; ignoring",
                    event_type,
                )
                return
            # DECIDED/FULFILLED payloads omit work_item_id; recover via store.
            req = await req_store.get(request_id)
            work_item_id = req.work_item_id if req else None
            if not work_item_id:
                logger.info(
                    "AD-855: capability event %s for request %s has no linked "
                    "work item; nothing to resume",
                    event_type, str(request_id)[:12],
                )
                return
            item = await store.get_work_item(work_item_id)
            if item is None:
                logger.warning(
                    "AD-855: work item %s for request %s no longer exists; "
                    "ignoring event %s",
                    work_item_id, str(request_id)[:12], event_type,
                )
                return
            # Idempotency guard: only blocked items are eligible to resume/cancel.
            if item.status != "blocked":
                logger.debug(
                    "AD-855: work item %s is %s (not blocked); event %s is a no-op",
                    work_item_id, item.status, event_type,
                )
                return
            if event_type == EventType.CAPABILITY_REQUEST_FULFILLED.value:
                await self._resume(store, work_item_id)
            elif event_type == EventType.CAPABILITY_REQUEST_DECIDED.value:
                status = data.get("status") or ""
                if status == "denied":
                    await self._cancel(store, work_item_id, req)
                # "approved" -> no-op; resume fires on the FULFILLED event.
        except Exception:
            logger.warning(
                "AD-855: on_capability_event failed; degrading", exc_info=True
            )

    async def _resume(self, store: "WorkItemStore", work_item_id: str) -> None:
        """Resume a blocked item to in_progress and re-dispatch it."""
        updated = await store.transition_work_item(
            work_item_id, "in_progress", source="capability_gap_driver"
        )
        if updated is None:
            logger.warning(
                "AD-855: could not resume work item %s (illegal "
                "blocked->in_progress); leaving blocked",
                work_item_id,
            )
            return
        router = getattr(self._runtime, "work_item_router", None)
        if router is None:
            logger.warning(
                "AD-855: work item %s resumed to in_progress but no "
                "work_item_router to re-dispatch",
                work_item_id,
            )
            return
        item = await store.get_work_item(work_item_id)
        if item is None:
            return
        await router.on_work_item_created(
            {
                "type": "work_item_created",
                "data": {"work_item": item.to_dict()},
                "timestamp": time.time(),
            }
        )
        logger.info(
            "AD-855: work item %s resumed and re-dispatched", work_item_id
        )

    async def _cancel(
        self,
        store: "WorkItemStore",
        work_item_id: str,
        req: "CapabilityRequest | None",
    ) -> None:
        """Cancel a blocked item whose capability request was denied."""
        cancelled = await store.transition_work_item(
            work_item_id, "cancelled", source="capability_gap_driver"
        )
        if cancelled is None:
            logger.warning(
                "AD-855: could not cancel work item %s (illegal "
                "blocked->cancelled)",
                work_item_id,
            )
            return
        item = await store.get_work_item(work_item_id)
        reason = req.decision_reason if req else ""
        base = dict(item.metadata) if item and item.metadata else {}
        base["denial_reason"] = reason
        await store.update_work_item(work_item_id, metadata=base)
        logger.info(
            "AD-855: work item %s cancelled (capability request denied)",
            work_item_id,
        )

    def _triage_config(self) -> Any:
        config = getattr(self._runtime, "config", None)
        return getattr(config, "capability_triage", None) if config is not None else None
