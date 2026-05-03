"""AD-641d: Crew Deliberation Protocol.

Judgment-level decision making, distinct from QuorumEngine's mechanical consensus.
Captain initiates or approves; crew contribute arguments; Captain resolves with
outcome ADOPTED/REJECTED/DEFERRED. Ward Room thread is the durable record.
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Any

from probos.events import EventType

logger = logging.getLogger(__name__)


class DeliberationPhase(str, Enum):
    # v1 reachable phases only. OPEN/ENDORSE phases are deferred to grandchild
    # ADs along with the explicit transitions that would set them.
    ARGUE = "argue"
    RESOLVED = "resolved"


class DeliberationOutcome(str, Enum):
    # PENDING is the initial sentinel value before resolve(); it is NOT a
    # valid resolve() outcome. resolve(outcome=PENDING) returns None.
    PENDING = "pending"
    ADOPTED = "adopted"
    REJECTED = "rejected"
    DEFERRED = "deferred"


@dataclass(frozen=True)
class DeliberationArgument:
    id: str
    agent_id: str
    agent_callsign: str
    stance: str  # "for" | "against" | "neutral"
    body: str
    submitted_at: float


@dataclass(frozen=True)
class DeliberationSession:
    id: str
    topic: str
    initiator_id: str
    initiator_callsign: str
    # `participants` is captured for future grandchild ADs (scoping of
    # `submit_argument` to invited members; notification fan-out). v1 stores
    # but does not consult it.
    participants: list[str]
    phase: DeliberationPhase
    started_at: float
    ended_at: float = 0.0
    thread_id: str = ""
    outcome: DeliberationOutcome = DeliberationOutcome.PENDING
    rationale: str = ""
    arguments: list[DeliberationArgument] = field(default_factory=list)


class DeliberationProtocol:
    """Coordinator for structured crew deliberation.

    Public API (v1):
      - initiate(topic, initiator_id, initiator_callsign, participants) -> DeliberationSession
      - submit_argument(session_id, agent_id, agent_callsign, stance, body) -> bool
      - resolve(session_id, captain_id, captain_callsign, outcome, rationale) -> DeliberationSession | None
      - get_session(session_id) -> DeliberationSession | None

    Endorsement is deferred to AD-641d-v (bridges deliberation arguments to
    `WardRoomService.endorse(target_id=, target_type=, voter_id=, direction=)`).
    """

    def __init__(
        self,
        *,
        ward_room: Any | None,
        emit_event: Any | None = None,
        captain_callsign: str = "Captain",
    ) -> None:
        self._ward_room = ward_room
        self._emit_event = emit_event
        self._captain_callsign = (captain_callsign or "Captain").strip().lower()
        self._sessions: dict[str, DeliberationSession] = {}

    async def initiate(
        self,
        *,
        topic: str,
        initiator_id: str,
        initiator_callsign: str,
        participants: list[str] | None = None,
        channel_id: str = "deliberation",
    ) -> DeliberationSession:
        sid = uuid.uuid4().hex[:12]
        thread_id = ""
        if self._ward_room is not None:
            try:
                thread = await self._ward_room.create_thread(
                    channel_id=channel_id,
                    author_id=initiator_id,
                    title=f"Deliberation: {topic}",
                    body=f"[Deliberation OPEN] Topic: {topic}",
                    author_callsign=initiator_callsign or "",
                    thread_mode="discuss",
                )
                thread_id = thread.id
            except Exception:
                logger.warning(
                    "AD-641d: Ward Room create_thread failed for topic=%r; "
                    "continuing with in-memory session only",
                    topic, exc_info=True,
                )
        session = DeliberationSession(
            id=sid,
            topic=str(topic),
            initiator_id=str(initiator_id),
            initiator_callsign=str(initiator_callsign or ""),
            participants=[str(p) for p in (participants or []) if p],
            phase=DeliberationPhase.ARGUE,
            started_at=time.time(),
            thread_id=thread_id,
        )
        self._sessions[sid] = session
        if self._emit_event is not None:
            try:
                self._emit_event(
                    EventType.DELIBERATION_INITIATED,
                    {
                        "session_id": sid,
                        "topic": session.topic,
                        "initiator_id": session.initiator_id,
                        "thread_id": session.thread_id,
                    },
                )
            except Exception:
                logger.warning(
                    "AD-641d: emit_event(DELIBERATION_INITIATED) failed; continuing",
                    exc_info=True,
                )
        return session

    async def submit_argument(
        self,
        *,
        session_id: str,
        agent_id: str,
        agent_callsign: str,
        stance: str,
        body: str,
    ) -> bool:
        session = self._sessions.get(session_id)
        if session is None or session.phase == DeliberationPhase.RESOLVED:
            return False
        if stance not in ("for", "against", "neutral"):
            return False
        arg = DeliberationArgument(
            id=uuid.uuid4().hex[:8],
            agent_id=str(agent_id),
            agent_callsign=str(agent_callsign or ""),
            stance=stance,
            body=str(body or ""),
            submitted_at=time.time(),
        )
        new_args = list(session.arguments) + [arg]
        self._sessions[session_id] = replace(session, arguments=new_args)
        if self._ward_room is not None and session.thread_id:
            try:
                await self._ward_room.create_post(
                    thread_id=session.thread_id,
                    author_id=str(agent_id),
                    author_callsign=str(agent_callsign or ""),
                    body=f"[{stance.upper()}] {body}",
                )
            except Exception:
                logger.warning(
                    "AD-641d: Ward Room create_post failed for session=%s; "
                    "continuing (argument retained in-memory)",
                    session_id, exc_info=True,
                )
        if self._emit_event is not None:
            try:
                self._emit_event(
                    EventType.DELIBERATION_ARGUMENT_SUBMITTED,
                    {
                        "session_id": session_id,
                        "argument_id": arg.id,
                        "agent_id": arg.agent_id,
                        "stance": arg.stance,
                    },
                )
            except Exception:
                logger.warning(
                    "AD-641d: emit_event(DELIBERATION_ARGUMENT_SUBMITTED) failed; continuing",
                    exc_info=True,
                )
        return True

    async def resolve(
        self,
        *,
        session_id: str,
        captain_id: str,
        captain_callsign: str,
        outcome: DeliberationOutcome,
        rationale: str = "",
    ) -> DeliberationSession | None:
        if (captain_callsign or "").strip().lower() != self._captain_callsign:
            return None
        session = self._sessions.get(session_id)
        if session is None or session.phase == DeliberationPhase.RESOLVED:
            return session
        if outcome == DeliberationOutcome.PENDING:
            return None
        resolved = replace(
            session,
            phase=DeliberationPhase.RESOLVED,
            outcome=outcome,
            rationale=str(rationale or ""),
            ended_at=time.time(),
        )
        self._sessions[session_id] = resolved
        if self._ward_room is not None and session.thread_id:
            try:
                await self._ward_room.create_post(
                    thread_id=session.thread_id,
                    author_id=str(captain_id),
                    author_callsign=str(captain_callsign or "Captain"),
                    body=f"[RESOLVED: {outcome.value.upper()}] {rationale}",
                )
            except Exception:
                logger.warning(
                    "AD-641d: Ward Room create_post (resolution) failed for "
                    "session=%s; in-memory state still RESOLVED",
                    session_id, exc_info=True,
                )
        if self._emit_event is not None:
            try:
                self._emit_event(
                    EventType.DELIBERATION_RESOLVED,
                    {
                        "session_id": session_id,
                        "outcome": outcome.value,
                        "captain_id": str(captain_id),
                    },
                )
            except Exception:
                logger.warning(
                    "AD-641d: emit_event(DELIBERATION_RESOLVED) failed; continuing",
                    exc_info=True,
                )
        return resolved

    def get_session(self, session_id: str) -> DeliberationSession | None:
        return self._sessions.get(session_id)
