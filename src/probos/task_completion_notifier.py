"""ProbOS — Yeo task-completion Captain-DM notifier (AD-846).

Closes the async half of Yeo's Tier-3 delegation loop (AD-845): when a task
Yeo opened from a 1:1 chat finishes, Yeo proactively DMs the Captain with the
outcome instead of leaving the result to be discovered on the kanban board.

Listens for ``EventType.WORK_ITEM_STATUS_CHANGED`` and, when the new status is
terminal (``done`` / ``failed``) AND the item is a Yeo-originated dispatchable
task (``metadata.dispatchable`` is truthy AND ``tags`` contains
``"yeo-delegated"``), posts a one-line notice into the Captain's DM channel for
Yeo, reusing the AD-485 proactive Captain-DM primitive
(``dm-captain-{yeo_id[:8]}`` channel).

The ``yeo-delegated`` tag gate is load-bearing: only tasks Yeo opened on the
Captain's behalf notify, so system/crew work items never spam the Captain's DM.

Honest-degrade: a missing ward room, a missing Yeo agent, or a non-matching
event logs (if relevant) and returns without raising, so a missing chat
substrate never blocks a status transition.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

_TERMINAL_STATUSES = frozenset({"done", "failed"})
_YEO_DELEGATED_TAG = "yeo-delegated"


def _should_notify(work_item: dict[str, Any], new_status: str) -> bool:
    """AD-846: gate — terminal status + Yeo-originated dispatchable task.

    Only ``done``/``failed`` transitions on an item carrying both
    ``metadata.dispatchable`` (truthy) and the ``yeo-delegated`` tag pass.
    """
    if new_status not in _TERMINAL_STATUSES:
        return False
    metadata = work_item.get("metadata") or {}
    if not metadata.get("dispatchable"):
        return False
    tags = work_item.get("tags") or []
    return _YEO_DELEGATED_TAG in tags


def _resolve_yeo(runtime: Any) -> Any | None:
    """AD-846: resolve the live Yeo (YeomanAgent) from the registry pool.

    Returns the first agent in the ``yeoman`` pool, or ``None`` when no
    registry / no Yeo is wired. Tier-2: never raises.
    """
    registry = getattr(runtime, "registry", None)
    if registry is None:
        return None
    try:
        agents = registry.get_by_pool("yeoman")
    except Exception:
        logger.debug("AD-846: get_by_pool('yeoman') raised", exc_info=True)
        return None
    for agent in agents or []:
        if getattr(agent, "id", None):
            return agent
    return None


def _summarize_outcome(work_item: dict[str, Any], new_status: str) -> str:
    """AD-846: build a short Captain-visible completion line."""
    title = work_item.get("title") or "(untitled task)"
    if new_status == "done":
        return f"Task complete: {title}."
    return (
        f"Task did not finish: {title}. It stopped before completing — "
        f"let me know if you'd like me to open it again."
    )


async def notify_captain_of_task_completion(runtime: Any, event: Any) -> None:
    """AD-846: post a Yeo Captain-DM when a Yeo-delegated task reaches a
    terminal status.

    Reuses the AD-485 DM primitive: find-or-create the ``dm-captain-{id[:8]}``
    DM channel for Yeo, then create a thread carrying a one-line outcome
    notice. Honest-degrade throughout — never raises.
    """
    payload = getattr(event, "data", None) or getattr(event, "payload", None) or {}
    work_item = payload.get("work_item") or {}
    new_status = str(payload.get("new_status") or work_item.get("status") or "")
    if not _should_notify(work_item, new_status):
        return

    ward_room = getattr(runtime, "ward_room", None)
    if ward_room is None:
        logger.warning(
            "AD-846: task-completion notice skipped — ward room unavailable; "
            "the Captain will still see the result on the kanban board"
        )
        return

    yeo = _resolve_yeo(runtime)
    if yeo is None:
        logger.warning(
            "AD-846: task-completion notice skipped — no live Yeo agent to "
            "author the Captain DM"
        )
        return

    yeo_id = yeo.id
    yeo_callsign = getattr(yeo, "callsign", "") or "Yeo"

    try:
        channel_name = f"dm-captain-{yeo_id[:8]}"
        dm_channel = None
        channels = await ward_room.list_channels()
        for ch in channels:
            if ch.name == channel_name and ch.channel_type == "dm":
                dm_channel = ch
                break
        if dm_channel is None:
            dm_channel = await ward_room.create_channel(
                name=channel_name,
                description=f"DM: {yeo_callsign} → Captain",
                channel_type="dm",
                created_by=yeo_id,
            )

        body = _summarize_outcome(work_item, new_status)
        await ward_room.create_thread(
            channel_id=dm_channel.id,
            author_id=yeo_id,
            title=f"[Task update from @{yeo_callsign}]",
            body=body,
            author_callsign=yeo_callsign,
        )
        logger.info(
            "AD-846: task-completion Captain-DM posted by %s (item=%s, status=%s)",
            yeo_callsign, work_item.get("id", "")[:12], new_status,
        )
    except Exception:
        logger.warning(
            "AD-846: task-completion Captain-DM failed; the kanban board "
            "remains the result surface",
            exc_info=True,
        )
