"""AD-1323 (#1478): startup sweep that finishes costed continue extensions across a restart.

After a restart nothing in memory remembers that a turn asked for an extension.
The durable permit does. First it voids permits whose filing died before they were
bound to a request, reclaims (once, ever) a permit consumed by a pass that never
reached its first model call, and finishes an approval that landed mid-filing.
Then it walks the ACTIVE permits and, for each, either re-delivers the approval
the driver never saw, resumes an item that was unblocked but never restarted, or
voids a permit whose request or item is gone. A permit whose pass DID reach its
first model call stays consumed: that extension is lost rather than risk spending
it twice.

It never starts a pass itself and never extends a budget: it only re-enters the
existing resume path (``CapabilityGapDriver`` / ``resume_promoted_turn``), whose
agent seam consumes the permit by compare-and-set. Other requested permits are left alone. It never raises and is bounded by the number of active
permits.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

_TERMINAL_ITEM_STATUSES = frozenset({"done", "failed", "cancelled", "canceled", "completed"})
MAX_PERMITS_PER_SWEEP = 200


@dataclass(frozen=True)
class SweepReport:
    """What one sweep did, as counts."""

    examined: int = 0
    expired_voided: int = 0
    voided: int = 0
    redelivered: int = 0
    resumed: int = 0
    left: int = 0
    failed: int = 0
    unbound_voided: int = 0
    reclaimed: int = 0
    reconciled: int = 0


async def recover_continue_permits(runtime: Any) -> SweepReport:
    """Re-enter the resume path for every active permit. Never raises."""
    permits = getattr(runtime, "continue_extension_permit_store", None)
    if permits is None:
        return SweepReport()
    counts = {"examined": 0, "expired_voided": 0, "voided": 0, "redelivered": 0,
              "resumed": 0, "left": 0, "failed": 0, "unbound_voided": 0,
              "reclaimed": 0, "reconciled": 0}
    try:
        counts["unbound_voided"] = await _void_unbound(permits)
        counts["reclaimed"] = await _reclaim_unstarted(permits)
        counts["expired_voided"] = int(await permits.void_expired() or 0)
        active = list(await permits.list_active())[:MAX_PERMITS_PER_SWEEP]
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.warning(
            "AD-1323: the startup sweep could not read the extension permits; they are left "
            "as they are and no pass is restarted", exc_info=True,
        )
        return SweepReport(failed=1)
    for permit in active:
        counts["examined"] += 1
        try:
            outcome = await _recover_one(runtime, permits, permit)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.warning(
                "AD-1323: recovering extension permit for request %s failed; it is left "
                "active until the next start", str(getattr(permit, "request_id", ""))[:12],
                exc_info=True,
            )
            outcome = "failed"
        counts[outcome] += 1
    counts["reconciled"] = await _reconcile_approved(runtime, permits)
    if any(counts.values()):
        logger.info("AD-1323: extension permit sweep: %s", counts)
    return SweepReport(**counts)


async def _void_unbound(permits: Any) -> int:
    """A process that died between reserving and binding: any request is an ordinary continue."""
    voided = 0
    for permit in list(await permits.list_unbound())[:MAX_PERMITS_PER_SWEEP]:
        if await permits.void_unbound(permit.work_item_id):
            voided += 1
    return voided


async def _reclaim_unstarted(permits: Any) -> int:
    """Consumed with no first model call: nothing was spent, so it is active once more, once."""
    reclaimed = 0
    for permit in list(await permits.list_consumed_unstarted())[:MAX_PERMITS_PER_SWEEP]:
        if await permits.reclaim_unstarted(permit.request_id) is not None:
            reclaimed += 1
    return reclaimed


async def _reconcile_approved(runtime: Any, permits: Any) -> int:
    """An approval recorded while the permit was unbound, never fulfilled: fulfil it now."""
    reconciler = getattr(runtime, "continue_extension_reconciler", None)
    requests = getattr(runtime, "capability_request_store", None)
    items = getattr(runtime, "work_item_store", None)
    if reconciler is None or requests is None or items is None:
        return 0
    reconciled = 0
    try:
        requested = list(await permits.list_requested())[:MAX_PERMITS_PER_SWEEP]
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.warning(
            "AD-1323: the startup sweep could not read requested extension permits; approvals "
            "recorded mid-filing wait for the Captain to approve again", exc_info=True,
        )
        return 0
    for permit in requested:
        try:
            request = await requests.get(permit.request_id)
            if getattr(request, "status", "") != "approved":
                continue
            item = await items.get_work_item(permit.work_item_id)
            metadata = getattr(item, "metadata", None)
            linked = metadata.get("capability_request_id") if type(metadata) is dict else None
            if getattr(item, "status", "") != "blocked" or linked != permit.request_id:
                continue
            if await reconciler(permit.request_id):
                reconciled += 1
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.warning(
                "AD-1323: reconciling the approved request %s failed; it stays approved and "
                "the Captain can approve it again", permit.request_id[:12], exc_info=True,
            )
    return reconciled


async def _recover_one(runtime: Any, permits: Any, permit: Any) -> str:
    request_id = permit.request_id
    requests = getattr(runtime, "capability_request_store", None)
    items = getattr(runtime, "work_item_store", None)
    if requests is None or items is None:
        return "left"
    request = await requests.get(request_id)
    item = await items.get_work_item(permit.work_item_id)
    if request is None or getattr(request, "status", "") == "denied":
        await permits.void(request_id)
        return "voided"
    if item is None or getattr(item, "status", "") in _TERMINAL_ITEM_STATUSES:
        await permits.void(request_id)
        return "voided"
    metadata = getattr(item, "metadata", None)
    linked = metadata.get("capability_request_id") if type(metadata) is dict else None
    if linked != request_id or getattr(request, "status", "") != "fulfilled":
        return "left"
    if item.status == "blocked":
        driver = getattr(runtime, "capability_gap_driver", None)
        if driver is None:
            return "left"
        from probos.events import EventType

        await driver.on_capability_event(
            {"type": EventType.CAPABILITY_REQUEST_FULFILLED.value, "data": {"id": request_id}}
        )
        return "redelivered"
    if item.status == "in_progress":
        from probos.cognitive.turn_promotion import resume_promoted_turn

        await resume_promoted_turn(runtime, item, request_id)
        return "resumed"
    return "left"
