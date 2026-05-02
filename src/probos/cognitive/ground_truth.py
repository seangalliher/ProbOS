"""AD-528: Ground-Truth Task Verification.

Cross-references claimed task completions against ``BookingJournal`` entries
and ``event_log`` audit records. Returns a confidence score and a list of
signals that matched (or didn't). Read-only over existing state in v1;
active rejection deferred to AD-528b.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from probos.events import EventType

if TYPE_CHECKING:
    from probos.workforce import BookingJournal

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class GroundTruthResult:
    """Outcome of a ground-truth verification."""

    verified: bool
    score: float           # 0.0 (no evidence) to 1.0 (all signals matched)
    signals: list[str] = field(default_factory=list)
    booking_id: str = ""
    agent_id: str = ""
    claimed_summary: str = ""
    completed_at: float = 0.0


class GroundTruthVerifier:
    """Score whether a claimed task completion is corroborated by artifacts.

    v1 signals:
      1. ``journal_present``  -- a BookingJournal entry exists for the booking_id.
      2. ``duration_nonzero`` -- journal duration_seconds > 0 (work happened).
      3. ``tokens_recorded``  -- journal tokens_consumed > 0 OR billable=False
                                 (cached/free completion is acceptable).
      4. ``event_within_window`` -- at least one event in event_log for the
                                    agent_id within
                                    [completed_at - window, completed_at].

    Score = sum of matched signals / total signals. Threshold default 0.75
    (3 of 4 must match for ``verified=True``; boundary is inclusive: a score
    of exactly 0.75 with threshold 0.75 verifies via >= comparison).

    No mutation. Each ``verify()`` call queries the existing surfaces and
    returns a fresh ``GroundTruthResult``.
    """

    DEFAULT_THRESHOLD = 0.75
    DEFAULT_EVENT_WINDOW_SECONDS = 600.0

    def __init__(
        self,
        *,
        runtime: Any,
        emit_event: Any | None = None,
        threshold: float = DEFAULT_THRESHOLD,
        event_window_seconds: float = DEFAULT_EVENT_WINDOW_SECONDS,
    ) -> None:
        self._runtime = runtime
        self._emit_event = emit_event
        self._threshold = threshold
        self._event_window = event_window_seconds

    async def verify(
        self,
        *,
        booking_id: str,
        agent_id: str,
        claimed_summary: str,
        completed_at: float | None = None,
    ) -> GroundTruthResult:
        completed_at = completed_at if completed_at is not None else time.time()
        signals: list[str] = []
        max_signals = 4

        journal_entry = await self._fetch_journal(booking_id)
        if journal_entry is not None:
            signals.append("journal_present")
            duration = float(getattr(journal_entry, "duration_seconds", 0.0) or 0.0)
            if duration > 0.0:
                signals.append("duration_nonzero")
            tokens = int(getattr(journal_entry, "tokens_consumed", 0) or 0)
            billable = bool(getattr(journal_entry, "billable", True))
            if tokens > 0 or not billable:
                signals.append("tokens_recorded")

        if await self._has_recent_event(agent_id, completed_at):
            signals.append("event_within_window")

        score = len(signals) / max_signals
        verified = score >= self._threshold
        result = GroundTruthResult(
            verified=verified,
            score=score,
            signals=signals,
            booking_id=booking_id,
            agent_id=agent_id,
            claimed_summary=claimed_summary,
            completed_at=completed_at,
        )
        self._emit(result)
        return result

    async def _fetch_journal(self, booking_id: str) -> "BookingJournal | None":
        """Read the booking journal via the runtime's work-item store.

        Prefers the ``journal_type='working'`` entry; falls back to the first
        entry if no 'working' record is present.
        """
        rt = self._runtime
        if rt is None or not booking_id:
            return None
        # AD-528: the public runtime attribute is `work_item_store` (verified at
        # runtime.py:212 / 421 / 1532); `work_item_store.get_booking_journal()`
        # returns a list[BookingJournal] (verified at workforce.py:1514).
        wf = getattr(rt, "work_item_store", None)
        if wf is None:
            return None
        try:
            entries = await wf.get_booking_journal(booking_id)
        except Exception:
            logger.debug(
                "AD-528: get_booking_journal failed (booking_id=%s)",
                booking_id, exc_info=True,
            )
            return None
        for entry in entries or []:
            if getattr(entry, "journal_type", "") == "working":
                return entry
        # Fall back to first entry if no "working" entry found
        return (entries[0] if entries else None)

    async def _has_recent_event(self, agent_id: str, completed_at: float) -> bool:
        rt = self._runtime
        if rt is None or not agent_id:
            return False
        log = getattr(rt, "event_log", None)
        if log is None:
            return False
        try:
            events = await log.query(agent_id=agent_id, limit=200)
        except Exception:
            logger.debug(
                "AD-528: event_log.query failed (agent_id=%s)",
                agent_id, exc_info=True,
            )
            return False
        cutoff_low = completed_at - self._event_window
        cutoff_high = completed_at + 5.0  # small forward slack
        for event in events or []:
            ts = float(event.get("timestamp", 0) or 0)
            if cutoff_low <= ts <= cutoff_high:
                return True
        return False

    def _emit(self, result: GroundTruthResult) -> None:
        if not self._emit_event:
            return
        et = EventType.VERIFICATION_PASSED if result.verified else EventType.VERIFICATION_FAILED
        try:
            self._emit_event(
                et,
                {
                    "verified": result.verified,
                    "score": result.score,
                    "signals": list(result.signals),
                    "booking_id": result.booking_id,
                    "agent_id": result.agent_id,
                    "completed_at": result.completed_at,
                },
            )
        except Exception:
            logger.warning(
                "AD-528: %s emit failed (booking_id=%s, agent_id=%s)",
                et.value, result.booking_id, result.agent_id, exc_info=True,
            )


class VerificationEpisodeWriter:
    """Writes one episodic record per ground-truth verification.

    Records survive into episodic memory so future audits can replay why
    a verdict was reached. v1 writes only -- no read API; consumers query
    via the standard episodic memory interfaces.

    Stateless on construction. Each ``write(result)`` call constructs a typed
    ``Episode`` (per ``types.py:411``) with verification metadata embedded in
    the ``dag_summary`` dict field, and persists via
    ``episodic_memory.store(episode)``. The ``claimed_summary`` is truncated
    to 1000 characters in ``user_input`` to avoid bloat in episodic store --
    long summaries can be reconstructed from the booking_id.
    """

    def __init__(self, *, runtime: Any) -> None:
        self._runtime = runtime

    async def write(self, result: GroundTruthResult) -> bool:
        rt = self._runtime
        if rt is None:
            return False
        em = getattr(rt, "episodic_memory", None)
        if em is None:
            return False
        # AD-528: construct a typed Episode (verified at types.py:411).
        # Verification metadata embedded in dag_summary (the canonical
        # structured-payload field). source=MemorySource.DIRECT.value
        # (verified at types.py:344) -- the verifier directly observed the
        # journal/event-log evidence. importance=7 for failed verifications
        # biases retention toward audit-relevant cases per AD-598.
        from probos.types import Episode, MemorySource
        episode = Episode(
            timestamp=time.time(),
            user_input=result.claimed_summary[:1000],
            agent_ids=[result.agent_id] if result.agent_id else [],
            dag_summary={
                "kind": "ground_truth_verification",
                "booking_id": result.booking_id,
                "verified": result.verified,
                "score": result.score,
                "signals": list(result.signals),
                "completed_at": result.completed_at,
            },
            source=MemorySource.DIRECT.value,
            importance=7 if not result.verified else 4,
            correlation_id="",
        )
        try:
            await em.store(episode)
            return True
        except Exception:
            logger.warning(
                "AD-528: episode store failed (booking_id=%s, agent_id=%s)",
                result.booking_id, result.agent_id, exc_info=True,
            )
            return False
