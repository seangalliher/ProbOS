"""AD-719a: persistent multi-agent chat threads under WardRoom.

Wave 163 ships the architectural contract — ``thread_mode='multi_agent'``
marker, the ``create_multi_agent_thread`` helper, and the participant
derivation. AD-719 transient @-mention fan-out wire-up is deferred to a
follow-up sub-AD (AD-719a-wire). The marker + helper are the seam that
the future wire-up consumes.

Architectural decision (Captain ruling, Wave 163):
  - YES, agents observe other agents' messages mid-thread when they have
    already been @-mentioned in the thread. Once an agent has been pulled
    into a thread, subsequent turns from other agents in that thread are
    visible context.
  - NO, agents do NOT observe messages in threads they were never
    @-mentioned in. Cross-thread observation is out of scope for v1.
  - Captain messages are always the seed. Agent-to-agent messages without
    a Captain prompt are not generated in v1 (deferred).

Participants are derived from post authorship: any agent that has authored
at least one post in the thread is a participant. The first post (which is
the thread body) lists the @-mentioned agent_ids in a structured trailer
``@participants: id1,id2,...`` so participants are knowable BEFORE any
agent replies.
"""
from __future__ import annotations

import re
from typing import Any

from probos.ward_room.models import WardRoomThread


MULTI_AGENT_THREAD_MODE = "multi_agent"

# Trailer convention. Appears verbatim at the bottom of the multi-agent
# thread body. Regex captures comma-separated agent_ids.
_PARTICIPANT_TRAILER_RE = re.compile(
    r"@participants:\s*([A-Za-z0-9_,\s-]+)$",
    re.MULTILINE,
)


def format_participant_trailer(agent_ids: list[str]) -> str:
    """Render the structured participants trailer for a multi-agent thread body."""
    cleaned = [a.strip() for a in agent_ids if a and a.strip()]
    if not cleaned:
        return ""
    return "@participants: " + ",".join(cleaned)


def parse_participants(body: str) -> list[str]:
    """Recover the @-mentioned agent_ids from a multi-agent thread body."""
    if not body:
        return []
    match = _PARTICIPANT_TRAILER_RE.search(body)
    if match is None:
        return []
    raw = match.group(1)
    return [a.strip() for a in raw.split(",") if a.strip()]


async def create_multi_agent_thread(
    service: Any,
    *,
    channel_id: str,
    captain_id: str,
    title: str,
    body: str,
    mentioned_agent_ids: list[str],
    captain_callsign: str = "Captain",
) -> WardRoomThread:
    """Create a WardRoom thread of ``thread_mode='multi_agent'`` with the
    Captain as author and the mentioned agents recorded via the participants
    trailer.

    Wave 163 contract: the Captain is the originator; agents do not seed
    multi-agent threads (deferred to AD-719a-2).
    """
    trailer = format_participant_trailer(mentioned_agent_ids)
    body_with_trailer = body
    if trailer:
        if body.strip():
            body_with_trailer = body.rstrip() + "\n\n" + trailer
        else:
            body_with_trailer = trailer
    thread = await service.create_thread(
        channel_id=channel_id,
        author_id=captain_id,
        title=title,
        body=body_with_trailer,
        author_callsign=captain_callsign,
        thread_mode=MULTI_AGENT_THREAD_MODE,
    )
    return thread


def is_participant(
    *,
    thread_body: str,
    post_authors: list[str],
    agent_id: str,
) -> bool:
    """Return True iff ``agent_id`` is a participant of the multi-agent thread.

    Per the Wave 163 ruling, an agent is a participant if EITHER it was
    @-mentioned at thread creation (recorded in the participants trailer)
    OR it has authored at least one post in the thread.
    """
    if not agent_id:
        return False
    if agent_id in parse_participants(thread_body):
        return True
    return agent_id in (post_authors or [])


def cross_agent_visibility(
    *,
    thread_body: str,
    post_authors: list[str],
    agent_id: str,
) -> bool:
    """Return True iff ``agent_id`` may observe other agents' messages
    inside the multi-agent thread.

    Wave 163 ruling: visibility within the thread is granted to all
    declared participants. Non-participants get False (no cross-thread
    observation).
    """
    return is_participant(
        thread_body=thread_body, post_authors=post_authors, agent_id=agent_id,
    )


__all__ = [
    "MULTI_AGENT_THREAD_MODE",
    "create_multi_agent_thread",
    "cross_agent_visibility",
    "format_participant_trailer",
    "is_participant",
    "parse_participants",
]
