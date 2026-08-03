"""ProbOS — Capability-request Captain-DM notifier (AD-857).

Listens for ``EventType.CAPABILITY_REQUEST_FILED`` and posts a one-line notice
into the Captain's DM channel for the requesting agent, reusing the AD-485
proactive Captain-DM primitive (``dm-captain-{agent_id[:8]}`` channel). This is
the chat half of the dual-surface decision surface — the HXI card is the other.

Honest-degrade: if the ward room is unavailable, log and return without raising
so a missing chat substrate never blocks request filing.

BF-708: every real producer hands listeners a *dict* envelope
(``ProbOSRuntime._emit_event`` and ``BaseEvent.to_dict`` both build
``{"type", "data", "timestamp"}``), but this module read the envelope with
``getattr``, which on a dict returns ``None``. Every notice was dropped with the
AD-857 "missing agent_id" warning while the field sat one level down. The shape
question is answered once, in :func:`event_payload`, because any other
``add_event_listener`` consumer faces it too.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# Envelope keys, in precedence order. ``data`` is what ProbOSRuntime._emit_event
# and BaseEvent.to_dict emit; ``payload`` is the older alternate spelling.
_ENVELOPE_KEYS: tuple[str, ...] = ("data", "payload")


def event_payload(event: Any) -> dict[str, Any]:
    """Return the domain-field mapping carried by a system event (BF-708).

    Accepts every shape an ``add_event_listener`` consumer can be handed:

    1. dict envelope with ``data``      -> the inner ``data`` mapping
    2. dict envelope with ``payload``   -> the inner ``payload`` mapping
    3. object with ``.data``            -> that mapping
    4. object with ``.payload``         -> that mapping
    5. bare dict of domain fields       -> the dict itself

    A dict that carries an envelope key resolves to the *inner* mapping even
    when that mapping is empty — an envelope with no domain fields genuinely has
    none, and falling back to the envelope would surface ``type``/``timestamp``
    as if they were domain fields. Anything unrecognised yields ``{}`` so the
    caller's own missing-field diagnostic fires rather than an AttributeError.
    """
    if isinstance(event, dict):
        for key in _ENVELOPE_KEYS:
            inner = event.get(key)
            if isinstance(inner, dict):
                return inner
        return event
    for key in _ENVELOPE_KEYS:
        inner = getattr(event, key, None)
        if isinstance(inner, dict):
            return inner
    return {}


async def notify_captain_of_capability_request(runtime: Any, event: Any) -> None:
    """Post a Captain-DM notice for a filed capability request (AD-857).

    Reuses the AD-485 DM primitive: find-or-create the ``dm-captain-{id[:8]}``
    DM channel for the requesting agent, then create a thread carrying a
    one-line "pending your approval" notice. Best-effort callsign resolution;
    degrades to the agent id when the registry can't resolve it.
    """
    ward_room = getattr(runtime, "ward_room", None)
    if ward_room is None:
        logger.warning(
            "AD-857: capability-request notice skipped — ward room unavailable; "
            "Captain will still see the request in the HXI card"
        )
        return

    payload = event_payload(event)
    agent_id = payload.get("agent_id") or ""
    if not agent_id:
        logger.warning(
            "AD-857: capability-request notice skipped — event missing agent_id"
        )
        return

    kind = payload.get("kind") or "capability"
    target = payload.get("target") or ""
    request_id = payload.get("id") or ""

    # Best-effort callsign resolution (degrade to agent id).
    sender_callsign = ""
    try:
        registry = getattr(runtime, "registry", None)
        callsign_registry = getattr(runtime, "callsign_registry", None)
        if registry is not None and callsign_registry is not None:
            agent = registry.get(agent_id)
            if agent is not None:
                sender_callsign = callsign_registry.get_callsign(agent.agent_type)
    except Exception:
        logger.warning(
            "AD-857: callsign resolution failed for %s; using agent id",
            agent_id[:12],
            exc_info=True,
        )
    display = sender_callsign or agent_id[:12]

    try:
        channel_name = f"dm-captain-{agent_id[:8]}"
        dm_channel = None
        channels = await ward_room.list_channels()
        for ch in channels:
            if ch.name == channel_name and ch.channel_type == "dm":
                dm_channel = ch
                break
        if dm_channel is None:
            dm_channel = await ward_room.create_channel(
                name=channel_name,
                description=f"DM: {display} → Captain",
                channel_type="dm",
                created_by=agent_id,
            )

        body = (
            f"Capability request pending your approval: {kind} '{target}' "
            f"(id={request_id[:12]}). Approve or deny it in the HXI."
        )
        await ward_room.create_thread(
            channel_id=dm_channel.id,
            author_id=agent_id,
            title=f"[Capability request from @{display}]",
            body=body,
            author_callsign=sender_callsign or agent_id,
        )
        logger.info(
            "AD-857: capability-request Captain-DM posted for %s (id=%s)",
            display,
            request_id[:12],
        )
    except Exception:
        logger.warning(
            "AD-857: capability-request Captain-DM failed for %s; the HXI card "
            "remains the decision path",
            display,
            exc_info=True,
        )
