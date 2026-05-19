"""AD-745: Conversation -> action dispatcher.

In-memory registry of proposed / pending / executed agent actions. The
DM pipeline ``step_4e_action_dispatch`` parses ``[ACTION:]`` markers
from agent replies and hands them to the dispatcher; tier-1 actions
fire inline, tier-2 actions wait for Captain ACK on
``POST /api/browser/actions/{action_id}/ack``, tier-3 actions wait for
an explicit Captain confirm.

Tier-2 throughout: every dispatch failure is log-and-degrade. Captain
sees a stripped-marker reply even if dispatch fails entirely.

Wave 178 GATE 1 ruling: per-action Captain ACK is the canonical
posture (NOT a v1 stopgap). AD-745-2 forward marker reframes
``requires_consensus`` swap as opt-in "autopilot mode" — Captain trades
ACK for multi-agent consensus quorum. The quorum REPLACES Captain ACK;
it does not stack.
"""
from __future__ import annotations

import asyncio
import fnmatch
import hashlib
import json
import logging
import time
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class ActionStatus(str, Enum):
    """Lifecycle states for a dispatched action.

    Aligned to the EventType emissions in the prompt (PROPOSED ->
    {EXECUTED | ACK_PENDING | CONFIRM_PENDING} -> {EXECUTED | ABORTED |
    TIMED_OUT | FAILED}).
    """

    PROPOSED = "proposed"
    EXECUTED = "executed"
    ACK_PENDING = "ack_pending"
    CONFIRM_PENDING = "confirm_pending"
    ABORTED = "aborted"
    TIMED_OUT = "timed_out"
    FAILED = "failed"


@dataclass
class DispatchedAction:
    """One agent-proposed action threaded through the dispatcher.

    Frame refs are SHA-256 attachment-store ids (AD-731 invariant): the
    bytes never live on this object; only refs do.
    """

    action_id: str
    agent_id: str
    captain_id: str
    thread_id: str | None
    verb: str
    args: dict[str, Any]
    raw_intent: str
    tier: int
    status: ActionStatus
    proposed_at: float
    page_url: str | None = None
    decided_at: float | None = None
    executed_at: float | None = None
    before_frame_ref: str | None = None
    after_frame_ref: str | None = None
    result: Any | None = None
    error: str | None = None
    destructive_pattern_match: str | None = None

    def to_public_dict(self) -> dict[str, Any]:
        """Captain-facing serialisation. Strips internal-only fields."""
        d = asdict(self)
        # Status as string per enum.
        d["status"] = self.status.value
        return d


def make_action_id(
    captain_id: str,
    agent_id: str,
    dm_turn_id: str,
    action_seq: int,
) -> str:
    """SHA-256 of the canonical tuple. Stable across restart of the
    pipeline given the same DM turn (forward marker AD-745-7 for
    cross-restart persistence)."""
    payload = json.dumps(
        [captain_id, agent_id, dm_turn_id, int(action_seq)],
        sort_keys=True,
    ).encode()
    return hashlib.sha256(payload).hexdigest()


def url_matches_destructive_pattern(
    url: str | None,
    patterns: list[str],
) -> str | None:
    """Return the first matching fnmatch pattern, or None."""
    if not url:
        return None
    for pat in patterns:
        if fnmatch.fnmatchcase(url, pat):
            return pat
    return None


class ActionDispatcher:
    """In-memory registry of dispatched actions.

    AD-722c-3 forward marker AD-745-7 covers SQLite persistence across
    restart. v1 is process-lifetime only — pending actions are dropped
    on restart with a Captain-visible log entry.
    """

    def __init__(self) -> None:
        self._actions: dict[str, DispatchedAction] = {}
        # consecutive_autonomous counter is per-(captain, agent) — reused
        # by the pipeline to force tier-3 after the cap.
        self._consec_autonomous: dict[tuple[str, str], int] = {}
        # Per-DM-turn counter, keyed by (captain, agent, dm_turn_id).
        self._per_turn: dict[tuple[str, str, str], int] = {}
        # Pending ack waiters: action_id -> asyncio.Event used by tests
        # and (forward marker AD-745-6) future plan-level orchestration.
        self._waiters: dict[str, asyncio.Event] = {}

    # --- lifecycle ---------------------------------------------------

    def reset_for_tests(self) -> None:
        self._actions.clear()
        self._consec_autonomous.clear()
        self._per_turn.clear()
        self._waiters.clear()

    # --- queries -----------------------------------------------------

    def get(self, action_id: str) -> DispatchedAction | None:
        return self._actions.get(action_id)

    def list_for_thread(self, thread_id: str | None) -> list[DispatchedAction]:
        return [
            a for a in self._actions.values()
            if a.thread_id == thread_id
        ]

    def consecutive_autonomous(self, captain_id: str, agent_id: str) -> int:
        return self._consec_autonomous.get((captain_id, agent_id), 0)

    def per_turn_count(
        self, captain_id: str, agent_id: str, dm_turn_id: str,
    ) -> int:
        return self._per_turn.get((captain_id, agent_id, dm_turn_id), 0)

    # --- mutations ---------------------------------------------------

    def register(self, action: DispatchedAction) -> None:
        self._actions[action.action_id] = action
        key = (action.captain_id, action.agent_id, action.thread_id or "")
        self._per_turn[key] = self._per_turn.get(key, 0) + 1

    def mark_executed(
        self,
        action_id: str,
        *,
        result: Any | None = None,
        after_frame_ref: str | None = None,
    ) -> DispatchedAction | None:
        a = self._actions.get(action_id)
        if a is None:
            return None
        a.status = ActionStatus.EXECUTED
        a.executed_at = time.time()
        a.result = result
        if after_frame_ref:
            a.after_frame_ref = after_frame_ref
        # Bump trust budget for tier-1/2 autonomous actions; reset on tier-3.
        if a.tier in (1, 2):
            ck = (a.captain_id, a.agent_id)
            self._consec_autonomous[ck] = self._consec_autonomous.get(ck, 0) + 1
        else:
            self._consec_autonomous[(a.captain_id, a.agent_id)] = 0
        ev = self._waiters.pop(action_id, None)
        if ev is not None:
            ev.set()
        return a

    def mark_aborted(self, action_id: str, *, error: str | None = None) -> DispatchedAction | None:
        a = self._actions.get(action_id)
        if a is None:
            return None
        a.status = ActionStatus.ABORTED
        a.decided_at = time.time()
        if error:
            a.error = error
        ev = self._waiters.pop(action_id, None)
        if ev is not None:
            ev.set()
        return a

    def mark_failed(self, action_id: str, *, error: str) -> DispatchedAction | None:
        a = self._actions.get(action_id)
        if a is None:
            return None
        a.status = ActionStatus.FAILED
        a.executed_at = time.time()
        a.error = error
        ev = self._waiters.pop(action_id, None)
        if ev is not None:
            ev.set()
        return a

    def make_waiter(self, action_id: str) -> asyncio.Event:
        """Used by the pipeline to await Captain ACK for tier-2 actions."""
        ev = asyncio.Event()
        self._waiters[action_id] = ev
        return ev
