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


# ---------------------------------------------------------------------------
# AD-528b: Active Rejection & Quarantine
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RejectionDecision:
    """Outcome of a ``GroundTruthRejectionGate.evaluate()`` call.

    ``action`` is ``"allow"`` when the underlying verifier returned
    ``verified=True``; ``"reject"`` when the gate took the rejection branch.
    On the reject path, ``quarantine_metadata`` carries the payload that was
    (or would be) merged into the work item's metadata under the gate's
    configured ``metadata_key``. On the allow path, ``quarantine_metadata``
    is empty.

    Frozen because consumers (HXI surfaces, Counselor alert paths, and the
    future AD-528b-2 caller-integration wiring) need a value-type they can
    pass around without defensive-copy.
    """

    verified: bool
    score: float
    action: str  # "allow" | "reject"
    quarantine_metadata: dict[str, Any] = field(default_factory=dict)
    signals: list[str] = field(default_factory=list)
    booking_id: str = ""
    agent_id: str = ""
    work_item_id: str = ""


class GroundTruthRejectionGate:
    """Wraps ``GroundTruthVerifier`` with a pre-commit rejection decision +
    metadata-only quarantine.

    v1 surface: callers (deferred to AD-528b-2) invoke ``evaluate(...)``
    BEFORE attempting a ``→ done`` transition on a work item. If verification
    passes, ``evaluate`` returns ``RejectionDecision(action="allow")`` and
    the caller proceeds. If verification fails, the gate emits
    ``VERIFICATION_REJECTED``, attempts to merge a quarantine payload into
    the work item's metadata via
    ``runtime.work_item_store.update_work_item(work_item_id, metadata=...)``,
    emits ``WORK_ITEM_QUARANTINED`` on successful merge, and returns
    ``RejectionDecision(action="reject", quarantine_metadata=...)``.

    Status-machine semantics: v1 does NOT mutate work-item status. The
    caller decides whether to transition the item to ``failed``, keep it
    in ``in_progress``, or escalate. State-machine extension (adding a
    ``quarantined`` status to the ``task`` work_type) is deferred to
    AD-528b-5.

    Trust-network feedback (raise/lower trust on PASSED/FAILED/REJECTED)
    is a distinct AD — AD-528c (Wave 59). v1 of this class has zero
    coupling to ``runtime.trust_network`` or ``probos.consensus.trust``.
    """

    DEFAULT_METADATA_KEY = "ground_truth_quarantine"

    def __init__(
        self,
        *,
        verifier: GroundTruthVerifier,
        runtime: Any,
        emit_event: Any | None = None,
        metadata_key: str = DEFAULT_METADATA_KEY,
    ) -> None:
        self._verifier = verifier
        self._runtime = runtime
        self._emit_event = emit_event
        self._metadata_key = metadata_key

    async def evaluate(
        self,
        *,
        booking_id: str,
        agent_id: str,
        claimed_summary: str,
        work_item_id: str,
        completed_at: float | None = None,
    ) -> RejectionDecision:
        """Evaluate a claimed completion; return allow/reject decision."""
        result = await self._verifier.verify(
            booking_id=booking_id,
            agent_id=agent_id,
            claimed_summary=claimed_summary,
            completed_at=completed_at,
        )
        if result.verified:
            return RejectionDecision(
                verified=True,
                score=result.score,
                action="allow",
                signals=list(result.signals),
                booking_id=booking_id,
                agent_id=agent_id,
                work_item_id=work_item_id,
            )

        # Rejection branch. Emit VERIFICATION_REJECTED first (the cognitive
        # decision is independent of whether the metadata persists), then
        # attempt the metadata merge, then emit WORK_ITEM_QUARANTINED only
        # if the merge succeeded.
        payload: dict[str, Any] = {
            "score": result.score,
            "signals": list(result.signals),
            "rejected_at": time.time(),
            "reason": "ground_truth_score_below_threshold",
            "booking_id": booking_id,
            "agent_id": agent_id,
        }
        self._emit(
            EventType.VERIFICATION_REJECTED,
            {**payload, "work_item_id": work_item_id},
        )
        applied = await self._apply_quarantine(work_item_id, payload)
        if applied:
            self._emit(
                EventType.WORK_ITEM_QUARANTINED,
                {
                    **payload,
                    "work_item_id": work_item_id,
                    "metadata_key": self._metadata_key,
                },
            )
        return RejectionDecision(
            verified=False,
            score=result.score,
            action="reject",
            quarantine_metadata=payload,
            signals=list(result.signals),
            booking_id=booking_id,
            agent_id=agent_id,
            work_item_id=work_item_id,
        )

    async def _apply_quarantine(
        self, work_item_id: str, payload: dict[str, Any]
    ) -> bool:
        """Merge quarantine payload into work item metadata. Tier-2 log-and-degrade.

        Read-modify-write: fetch the current work item, copy its existing
        metadata, set ``existing[metadata_key] = payload``, write the merged
        dict back via ``update_work_item``. Existing keys in the work item's
        metadata survive the merge.

        Returns True if the merge persisted; False on any failure (missing
        runtime, missing work_item_store, missing work item, store exception).
        Failures are logged at WARNING with ``exc_info=True`` per the
        copilot-instructions tier-2 rule — ``evaluate`` has already emitted
        ``VERIFICATION_REJECTED``, so a metadata-apply failure must NOT
        propagate to the caller.
        """
        rt = self._runtime
        if rt is None or not work_item_id:
            return False
        store = getattr(rt, "work_item_store", None)
        if store is None:
            return False
        try:
            item = await store.get_work_item(work_item_id)
            if item is None:
                return False
            existing_meta = dict(getattr(item, "metadata", None) or {})
            existing_meta[self._metadata_key] = payload
            await store.update_work_item(work_item_id, metadata=existing_meta)
            return True
        except Exception:
            logger.warning(
                "AD-528b: quarantine metadata apply failed (work_item_id=%s, key=%s)",
                work_item_id, self._metadata_key, exc_info=True,
            )
            return False

    def _emit(self, event_type: EventType, payload: dict[str, Any]) -> None:
        """Synchronously emit an event via the optional ``emit_event`` hook.

        Mirrors ``GroundTruthVerifier._emit`` shape. If no hook is set, the
        emit is silent (no-op) — the gate's behaviour (decision + metadata
        apply) still executes. If the hook raises, the exception is logged
        and swallowed (tier-2 log-and-degrade) so a downstream consumer's
        bug cannot break the rejection-decision path.
        """
        if not self._emit_event:
            return
        try:
            self._emit_event(event_type, payload)
        except Exception:
            logger.warning(
                "AD-528b: %s emit failed", event_type.value, exc_info=True,
            )


# ---------------------------------------------------------------------------
# AD-528c: Trust-Network Feedback
# ---------------------------------------------------------------------------


class GroundTruthTrustFeedback:
    """Subscribes to ground-truth verification events; updates ``TrustNetwork``.

    v1 surface: registered as a sync listener via
    ``runtime.add_event_listener(feedback.on_event, event_types=[
        EventType.VERIFICATION_PASSED.value,
        EventType.VERIFICATION_FAILED.value,
    ])`` in ``startup/finalize.py``. On each event, ``on_event`` reads the
    event payload, extracts ``agent_id`` + ``booking_id``, and calls
    ``runtime.trust_network.record_outcome(...)`` with an asymmetric weight
    scheme: ``success_weight`` (default 1.0) on PASSED, ``failure_weight``
    (default 0.5) on FAILED.

    ``VERIFICATION_REJECTED`` and ``WORK_ITEM_QUARANTINED`` are NOT consumed
    in v1. Every REJECTED co-fires with a FAILED inside
    ``GroundTruthVerifier._emit`` (the verifier emits PASSED/FAILED
    unconditionally before the rejection-gate emit logic runs). Listening
    to REJECTED would double-count negative trust updates. Distinct
    REJECTED-aware weighting (escalate negative weight when the gate
    engaged) is deferred to AD-528c-1.

    ProbOS principle 3 compliance is structural — ``record_outcome``
    internally stores raw ``(alpha, beta)`` Beta-distribution parameters
    and applies AD-558 dampening + cascade breaker + hard floor. v1
    invokes the public method only; never mutates ``record.alpha`` /
    ``record.beta`` directly, never bypasses dampening, never derives
    means.

    Tier-2 log-and-degrade: a ``record_outcome`` exception is logged at
    WARNING with ``exc_info=True`` but NOT propagated — the listener is
    invoked from the runtime's local event-dispatch path which already
    wraps in debug-level swallowing; the inner WARNING gives operators a
    visible failure signal without crashing the event-dispatch path.
    """

    def __init__(
        self,
        *,
        runtime: Any,
        success_weight: float = 1.0,
        failure_weight: float = 0.5,
    ) -> None:
        self._runtime = runtime
        self._success_weight = success_weight
        self._failure_weight = failure_weight

    def on_event(self, event: dict[str, Any]) -> None:
        """Process a single verification event; update trust if applicable.

        Synchronous (not ``async``) — the runtime's local dispatch path
        routes sync vs async via ``asyncio.iscoroutinefunction``; sync is
        preferred because ``record_outcome`` itself is sync and we avoid
        spawning fire-and-forget tasks per event.
        """
        type_str = event.get("type", "")
        data = event.get("data", {}) or {}
        agent_id = str(data.get("agent_id", ""))
        if not agent_id:
            return
        tn = getattr(self._runtime, "trust_network", None)
        if tn is None:
            return
        if type_str == EventType.VERIFICATION_PASSED.value:
            success, weight = True, self._success_weight
        elif type_str == EventType.VERIFICATION_FAILED.value:
            success, weight = False, self._failure_weight
        else:
            # REJECTED, QUARANTINED, and any future event type: no-op in v1.
            # See class docstring for double-counting rationale.
            return
        booking_id = str(data.get("booking_id", ""))
        try:
            tn.record_outcome(
                agent_id,
                success=success,
                weight=weight,
                intent_type="ground_truth_verification",
                episode_id=booking_id,
                verifier_id="ground_truth",
                source="ground_truth_verification",
            )
        except Exception:
            logger.warning(
                "AD-528c: trust_network.record_outcome failed (agent_id=%s, success=%s)",
                agent_id, success, exc_info=True,
            )
