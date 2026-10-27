"""AD-1341 S5 (#1569): continuous promotion into the Ship's Archive, a dream step behind a default-off flag.

With ``archive_promotion.enabled`` (off by default), each full dream cycle runs ``promote_settled`` once: Ship's
Records sources that meet the reset's own criteria and were last updated at least ``settle_hours`` earlier are
archived, at most ``max_per_cycle`` new entries a cycle. A source that cites episodes is archived only inside the
AD-754 erasure lock (``exclusive_with_erasure``) and only while every cited episode is live. No model call. With the
flag off nothing is wired, and the archive is written only by ``probos reset``, as before.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any

from probos.knowledge.archive_promotion import PromotionReport, promote_settled
from probos.knowledge.erasure import exclusive_with_erasure

logger = logging.getLogger(__name__)

Step = Callable[[], Awaitable[PromotionReport | None]]


def continuous_promotion_step(
    *,
    records: Callable[[], Any],
    archive: Callable[[], Any],
    memory: Callable[[], Any],
    timeline_id: Callable[[], str],
    settle_seconds: float,
    max_created: int,
    clock: Callable[[], float] = time.time,
) -> Step:
    """The dream step: each call promotes once (D8 to D11), or returns None when it cannot run now.

    The stores are read at each call, so a store closed at shutdown or failed at boot is simply absent: no step runs.
    A vessel without an instance id promotes nothing (its entries could not be attributed).
    """

    async def step() -> PromotionReport | None:
        store, documents, episodes, timeline = archive(), records(), memory(), timeline_id()
        if store is None or documents is None:
            return None  # the archive is closed, disabled or failed at boot, or Ship's Records is not running
        if type(timeline) is not str or not timeline.strip() or timeline == "unknown":
            logger.warning("AD-1341 S5: this vessel has no instance id; nothing is promoted continuously")
            return None

        async def cited_live(ids: tuple[str, ...]) -> bool:
            if episodes is None:
                return False  # the citations cannot be checked, so the lesson waits for the reset
            found = await episodes.get_by_ids(list(ids))
            return {getattr(episode, "id", None) for episode in found} >= set(ids)

        return await promote_settled(
            documents,
            store,
            timeline_id=timeline,
            settled_before=clock() - settle_seconds,
            max_created=max_created,
            cited_live=cited_live,
            exclusive=lambda: exclusive_with_erasure(episodes),
        )

    return step


def vessel_timeline(runtime: Any) -> str:
    """This vessel's timeline (its instance id), or an empty string when no ontology is loaded."""
    ontology = getattr(runtime, "ontology", None)
    return ontology.get_vessel_identity().instance_id if ontology is not None else ""


def wire_continuous_promotion(runtime: Any, engine: Any) -> bool:
    """AD-1341 S5 (D8): give ``engine`` the step when the Captain enabled it; True when wired.

    Checked by identity (``is True``), so a test double's attribute wires nothing. The Ship's Archive must be enabled
    too: a disabled archive promotes nothing at the reset either.
    """
    section = runtime.config.archive_promotion
    if getattr(section, "enabled", False) is not True:
        return False
    if getattr(runtime.config.archive, "enabled", False) is not True:
        logger.warning("AD-1341 S5: archive_promotion.enabled is set but the Ship's Archive is disabled; nothing is wired")
        return False
    engine.set_continuous_promotion(continuous_promotion_step(
        records=lambda: runtime.records_store,
        archive=lambda: runtime.archive_store,
        memory=lambda: getattr(runtime, "episodic_memory", None),
        timeline_id=lambda: vessel_timeline(runtime),
        settle_seconds=section.settle_hours * 3600.0,
        max_created=section.max_per_cycle,
    ))
    logger.info(
        "AD-1341 S5: continuous promotion wired (settle %.1f h, at most %d entries a dream cycle)",
        section.settle_hours, section.max_per_cycle,
    )
    return True
