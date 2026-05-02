"""AD-475: Ready Room Session Manager -- multi-agent briefings."""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Any

from probos.events import EventType

logger = logging.getLogger(__name__)


class SessionPhase(str, Enum):
    """v1 ships 3 phases. AD-475c will introduce research + refine."""

    PRESENT = "present"      # captain or convener presents the topic
    DISCUSS = "discuss"      # participants weigh in
    CONVERGE = "converge"    # decision recorded


_PHASE_ORDER = (
    SessionPhase.PRESENT,
    SessionPhase.DISCUSS,
    SessionPhase.CONVERGE,
)


@dataclass(frozen=True)
class ReadyRoomSession:
    """One Captain-convened ready-room briefing."""

    id: str
    topic: str
    participants: list[str]            # callsigns or post titles
    phase: str = SessionPhase.PRESENT.value
    started_at: float = 0.0
    ended_at: float = 0.0
    thread_id: str = ""                # Ward Room thread created at start
    journal_correlation_id: str = ""   # Cognitive Journal correlation
    convener: str = ""
    tags: list[str] = field(default_factory=list)


class ReadyRoomSessionManager:
    """v1 session manager.

    Public API:
      - start_session(topic, participants, convener) -> ReadyRoomSession
      - advance_phase(session_id) -> ReadyRoomSession | None
      - end_session(session_id) -> ReadyRoomSession | None
      - list_sessions(state='active'|'all') -> list[ReadyRoomSession]
      - get_session(session_id) -> ReadyRoomSession | None

    On start_session: creates a Ward Room thread via runtime.ward_room.create_thread
    (verified at ward_room/service.py:357) and emits READY_ROOM_SESSION_STARTED.
    """

    def __init__(
        self,
        *,
        runtime: Any,
        emit_event: Any | None = None,
        wardroom_channel_id: str = "ready_room",
    ) -> None:
        # AD-475: defensive getattr for __new__-bypass tests (convention #11)
        self._runtime = runtime
        self._emit_event = emit_event
        self._channel_id = wardroom_channel_id
        self._sessions: dict[str, ReadyRoomSession] = {}

    async def start_session(
        self, *, topic: str, participants: list[str],
        convener: str = "captain", tags: list[str] | None = None,
    ) -> ReadyRoomSession:
        if not topic:
            raise ValueError("start_session requires non-empty topic")
        # AD-475 rev: defensive coercion of participants -> list[str].
        # Strings would silently iterate by character via ', '.join.
        if not isinstance(participants, list):
            participants = list(participants) if participants is not None else []

        session_id = uuid.uuid4().hex
        correlation_id = f"ready_room/{session_id}"
        thread_id = ""
        rt = getattr(self, "_runtime", None)
        if rt is not None:
            ward_room = getattr(rt, "ward_room", None)
            if ward_room is not None and hasattr(ward_room, "create_thread"):
                try:
                    thread = await ward_room.create_thread(
                        channel_id=self._channel_id,
                        author_id=convener,
                        title=f"Ready Room: {topic}"[:120],
                        body=f"Convened by {convener}. Participants: {', '.join(participants)}.",
                        author_callsign=convener,
                        thread_mode="discuss",
                    )
                    thread_id = getattr(thread, "id", "") or ""
                except Exception:
                    logger.warning(
                        "AD-475: ward_room.create_thread failed; session continues without thread",
                        exc_info=True,
                    )

        session = ReadyRoomSession(
            id=session_id,
            topic=topic,
            participants=list(participants),
            phase=SessionPhase.PRESENT.value,
            started_at=time.time(),
            thread_id=thread_id,
            journal_correlation_id=correlation_id,
            convener=convener,
            tags=list(tags or []),
        )
        self._sessions[session_id] = session
        self._emit_started(session)
        return session

    def advance_phase(self, session_id: str) -> ReadyRoomSession | None:
        session = self._sessions.get(session_id)
        if session is None:
            return None
        try:
            current = SessionPhase(session.phase)
        except ValueError:
            return None
        idx = _PHASE_ORDER.index(current)
        if idx >= len(_PHASE_ORDER) - 1:
            return session  # already at terminal phase; idempotent
        next_phase = _PHASE_ORDER[idx + 1]
        updated = replace(session, phase=next_phase.value)
        self._sessions[session_id] = updated
        return updated

    def end_session(self, session_id: str) -> ReadyRoomSession | None:
        session = self._sessions.get(session_id)
        if session is None:
            return None
        updated = replace(
            session,
            phase=SessionPhase.CONVERGE.value,
            ended_at=time.time(),
        )
        self._sessions[session_id] = updated
        return updated

    def list_sessions(self, *, state: str = "active") -> list[ReadyRoomSession]:
        if state == "all":
            return list(self._sessions.values())
        return [s for s in self._sessions.values() if s.ended_at == 0.0]

    def get_session(self, session_id: str) -> ReadyRoomSession | None:
        return self._sessions.get(session_id)

    def _emit_started(self, session: ReadyRoomSession) -> None:
        if self._emit_event is None:
            return
        try:
            self._emit_event(
                EventType.READY_ROOM_SESSION_STARTED,
                {
                    "session_id": session.id,
                    "topic": session.topic[:200],
                    "participants": list(session.participants),
                    "convener": session.convener,
                    "thread_id": session.thread_id,
                    "correlation_id": session.journal_correlation_id,
                },
            )
        except Exception:
            logger.warning(
                "AD-475: READY_ROOM_SESSION_STARTED emit failed (id=%s)",
                session.id, exc_info=True,
            )
