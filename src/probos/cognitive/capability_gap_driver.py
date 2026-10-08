"""AD-855: BLOCKED -> request -> approve -> resume work-item gap driver.

Closes the loop on the work-item kanban board when an agent hits a
capability gap while working an item:

  1. ``on_capability_gap`` files a unified CapabilityRequest (AD-853) via the
     triage fast-path (AD-854), transitions the work item to ``blocked``, and
     records ``blocked_reason`` + ``capability_request_id`` in item metadata
     in the same write (merged, so pre-existing metadata survives).
  1b. ``block_on_request`` is that second half on its own (AD-1204), for a
     caller that already filed its own request. AD-1164's ``continue`` ask is
     the one caller: a turn that ran out of steps is waiting on a decision
     exactly like a capability gap is, so it parks the same way and resumes
     through the same path below. A request already fulfilled or denied when
     the item parks is resolved there and then (BF-878).
  2. ``on_capability_event`` subscribes to CAPABILITY_REQUEST_FULFILLED and
     CAPABILITY_REQUEST_DECIDED. When a blocked item's request is fulfilled it
     resumes the item (``blocked`` -> ``in_progress``) and re-dispatches it
     through the WorkItemRouter -- except an AD-1165 promoted turn, which the
     router must never be handed: the agent that ran it takes the turn's next
     pass instead (BF-887). Either way the log says what actually happened.
     When the request is denied it cancels the
     item, recording the denial reason. An ``approved`` decision is a no-op
     (resume happens only on FULFILLED, which the grant fast-path also emits,
     and which AD-1204's approval handler emits for a ``continue``). Resume and
     cancel act only on an item still parked on that request (BF-878).

Tier-2 log-and-degrade throughout: missing stores/router never raise.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from probos.cognitive.capability_triage import (
    ard_discoverer,
    triage_and_file,
    unified_ladder_enabled,
)
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
        # AD-1194: under the unified ladder a tool gap walks every rung and the
        # request records each verdict; a build is then left pending, not built.
        ladder: dict[str, Any] = {}
        if unified_ladder_enabled(getattr(self._runtime, "config", None)):
            ladder = {
                "unified": True,
                "gap_class": "tool",
                "discover_candidates": ard_discoverer(self._runtime),
            }
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
                **ladder,
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
        and records ``blocked_reason`` + ``capability_request_id`` in metadata
        in the same write, merged so pre-existing keys survive. Those two keys
        are what :meth:`on_capability_event` and the board read back, so they
        are written in exactly one place.

        Returns ``True`` when the board was updated, ``False`` when the
        transition was illegal from the item's current status or the id is
        unknown — in which case the caller still holds a filed request and
        should say so rather than pretending the item is parked.

        BF-878: a request already fulfilled or denied is acted on before this
        returns, as :meth:`on_capability_event` would have acted on its event.
        A resolution acts only on an item still parked on its own request,
        which is why the status and the request id are one write.

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
            work_item_id, "blocked", source="capability_gap_driver",
            metadata_patch={"blocked_reason": reason, "capability_request_id": request_id},
        )
        if transitioned is None:
            logger.warning(
                "AD-855: could not transition work item %s to blocked "
                "(unknown id or illegal from current status); request %s "
                "filed but board not updated",
                work_item_id, request_id[:12],
            )
            return False
        await self._resolve_if_settled(store, work_item_id, request_id)
        return True

    async def _resolve_if_settled(
        self, store: "WorkItemStore", work_item_id: str, request_id: str,
    ) -> None:
        """BF-878: act on a request that settled before its item was parked.

        Its event reached :meth:`on_capability_event` while the item was not yet
        ``blocked`` and was ignored, so this does what that handler would have.
        Never raises: the item is parked either way.
        """
        req_store = self._request_store
        if req_store is None:
            return
        try:
            req = await req_store.get(request_id)
            if req is None or req.work_item_id != work_item_id:
                return
            if req.status == "fulfilled":
                logger.info(
                    "BF-878: capability request %s was fulfilled before work item %s "
                    "was parked on it, so its event found nothing to resume; resuming now",
                    request_id[:12], work_item_id,
                )
                await self._resume(store, work_item_id, request_id)
            elif req.status == "denied":
                logger.info(
                    "BF-878: capability request %s was denied before work item %s "
                    "was parked on it, so its event found nothing to cancel; cancelling now",
                    request_id[:12], work_item_id,
                )
                await self._cancel(store, work_item_id, request_id, req)
        except Exception:
            logger.warning(
                "BF-878: could not finish resolving work item %s on settled capability "
                "request %s after parking it; its board status may not reflect the "
                "request, and if a later event for the request does not correct it, it "
                "needs a manual transition",
                work_item_id, request_id[:12], exc_info=True,
            )

    async def on_capability_event(self, event: dict) -> None:
        """Resume or cancel a blocked work item when its request resolves.

        Subscribed to CAPABILITY_REQUEST_FULFILLED and
        CAPABILITY_REQUEST_DECIDED. Idempotent: acts only while the linked
        work item is still ``blocked`` on this request (BF-878). Never raises.
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
                await self._resume(store, work_item_id, request_id)
            elif event_type == EventType.CAPABILITY_REQUEST_DECIDED.value:
                status = data.get("status") or ""
                if status == "denied":
                    await self._cancel(store, work_item_id, request_id, req)
                # "approved" -> no-op; resume fires on the FULFILLED event.
        except Exception:
            logger.warning(
                "AD-855: on_capability_event failed; degrading", exc_info=True
            )

    async def _resume(
        self, store: "WorkItemStore", work_item_id: str, request_id: str,
    ) -> None:
        """Resume a blocked item to in_progress and re-dispatch it.

        BF-878: a compare-and-set on the item still being parked on this request,
        so of the request's event and the post-park check only the one that moves
        it dispatches, and resolving a request the item no longer waits on does
        nothing.

        BF-887: an AD-1165 promoted turn is never handed to the router. Its item
        is deliberately not dispatchable, so the router dropped it while this
        logged "resumed and re-dispatched" and the turn never ran again (#1163).
        It goes to the agent that ran it. Every other item is re-dispatched as
        before, and the log says what the router did with it.
        """
        updated = await store.transition_work_item(
            work_item_id, "in_progress", source="capability_gap_driver",
            expected_status="blocked",
            expected={"capability_request_id": request_id},
        )
        if updated is None:
            if await self._moved_on(store, work_item_id, request_id):
                return
            logger.warning(
                "AD-855: could not resume work item %s (illegal "
                "blocked->in_progress); leaving blocked",
                work_item_id,
            )
            return
        from probos.cognitive.turn_promotion import (
            is_promoted_turn,
            resume_promoted_turn,
        )

        if is_promoted_turn(updated):
            await resume_promoted_turn(self._runtime, updated, request_id)
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
        await self._redispatch(router, item, request_id)

    async def _redispatch(self, router: Any, item: Any, request_id: str) -> None:
        """BF-887: hand a resumed item back to the router, and log what it did.

        ``dispatch_work_item`` returns whether a delivery substrate admitted the
        item (BF-810). ``on_work_item_created``, which this called before,
        returns nothing, so a resume the router dropped was logged as a
        re-dispatch. The item's status is the same either way.
        """
        wi = item.to_dict()
        try:
            admitted = await router.dispatch_work_item(wi)
        except Exception:
            logger.warning(
                "AD-855: re-dispatching resumed work item %s raised; it stays "
                "in_progress with no agent sent it, so it needs reassigning or "
                "cancelling",
                item.id, exc_info=True,
            )
            return
        if admitted:
            logger.info("AD-855: work item %s resumed and re-dispatched", item.id)
        elif not router.is_dispatchable(wi):
            logger.warning(
                "AD-855: work item %s resumed to in_progress on capability request "
                "%s, but it is not dispatchable (no tag in "
                "hybrid_dispatch.dispatchable_tags and no metadata['dispatchable']), "
                "so the router sent it to no agent; it stays in_progress until it "
                "is reassigned or cancelled, or the Quartermaster strands it after "
                "work_board_reconciler.strand_timeout_seconds",
                item.id, request_id[:12],
            )
        else:
            logger.warning(
                "AD-855: work item %s resumed to in_progress on capability request "
                "%s, but no agent admitted its re-dispatch; it stays in_progress "
                "until it is reassigned or cancelled (the Quartermaster re-routes a "
                "live-owned item only once it stalls past "
                "work_board_reconciler.stall_timeout_seconds, off by default)",
                item.id, request_id[:12],
            )

    async def _cancel(
        self,
        store: "WorkItemStore",
        work_item_id: str,
        request_id: str,
        req: "CapabilityRequest | None",
    ) -> None:
        """Cancel a blocked item whose capability request was denied (BF-878: compare-and-set)."""
        cancelled = await store.transition_work_item(
            work_item_id, "cancelled", source="capability_gap_driver",
            expected_status="blocked",
            expected={"capability_request_id": request_id},
        )
        if cancelled is None:
            if await self._moved_on(store, work_item_id, request_id):
                return
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

    async def _moved_on(
        self, store: "WorkItemStore", work_item_id: str, request_id: str,
    ) -> bool:
        """BF-878: whether a refused move found the item no longer parked on ``request_id``."""
        current = await store.get_work_item(work_item_id)
        if current is None:
            return False
        if current.status != "blocked":
            logger.debug(
                "BF-878: work item %s is already %s, so resolving capability request %s "
                "leaves it as it is",
                work_item_id, current.status, request_id[:12],
            )
            return True
        parked_on = (current.metadata or {}).get("capability_request_id")
        if parked_on == request_id:
            return False
        logger.info(
            "BF-878: work item %s is blocked waiting on %s, not on capability request %s, "
            "so resolving that request leaves it blocked",
            work_item_id,
            f"capability request {str(parked_on)[:12]}" if parked_on else "no recorded request",
            request_id[:12],
        )
        return True

    def _triage_config(self) -> Any:
        config = getattr(self._runtime, "config", None)
        return getattr(config, "capability_triage", None) if config is not None else None
