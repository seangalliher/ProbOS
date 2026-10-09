"""AD-1324 amendment 2: the structured audit sink for tier decisions and terminal outcomes.

The controller reports each decision to a plain callable, and the loop reports every armed terminal
(refused, asked, faulted) through ``emit_terminal``; this sink maps both to ONE closed record and
writes it through the runtime's public ``event_log.log`` seam. A record holds ids, tiers, outcome
and short closed tokens only -- never prompt, response or rationale text. A sink failure is logged
and never reaches the step that produced it. The write is a retained background task: the run waits
for it only up to ``AUDIT_DRAIN_TIMEOUT_S`` (the records are evidence, not control), and the number
of unfinished writes is bounded by ``AUDIT_MAX_INFLIGHT``.
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

EVENT_NAME = "ad1324_tier_decision"
AUDIT_DRAIN_TIMEOUT_S = 0.25
AUDIT_MAX_INFLIGHT = 64

_TOKEN = re.compile(r"[a-z0-9_:]{1,48}")
_WORK_ITEM = re.compile(r"[A-Za-z0-9_.:-]{1,80}")
_TIERS = frozenset({"fast", "standard", "deep"})
# Every unfinished write, for the whole process: a task whose drain timed out is never cancelled
# and must not be garbage collected, so this set (not the sink) owns it until it finishes.
_RETAINED: set[asyncio.Task[None]] = set()

_OUTCOMES = {
    "call_site": "served",
    "agent_choice": "served",
    "no_directive": "served",
    "floor_raise": "raised",
    "floor_redo": "redo",
}


def _token(value: Any) -> str | None:
    """``value`` when it is a short closed token, else None (free text never reaches a record)."""
    return value if type(value) is str and _TOKEN.fullmatch(value) else None


def _work_item(value: Any) -> str | None:
    """``value`` when it is a short id-shaped string, else None (free text never reaches a record)."""
    return value if type(value) is str and _WORK_ITEM.fullmatch(value) else None


def _tier(value: Any) -> str:
    return value if type(value) is str and value in _TIERS else ""


class TierAuditSink:
    """Maps controller payloads and loop terminals to audit records and writes them without blocking."""

    def __init__(self, event_log: Any, *, agent_id: str, thread_id: str) -> None:
        self._event_log = event_log
        self._agent_id = agent_id
        self._thread_id = thread_id
        self._tasks: set[asyncio.Task[None]] = set()

    def emit(self, payload: dict[str, Any]) -> None:
        """The controller's audit callable: map one decision payload to a record."""
        raw = str(payload.get("outcome", ""))
        outcome = "refused" if raw.startswith("rejected:") else _OUTCOMES.get(raw, raw)
        self.record(
            outcome, step=payload.get("step", 0), requested_tier=payload.get("requested", ""),
            effective_tier=payload.get("effective", ""), floor=payload.get("floor"),
            evidence=_token(payload.get("evidence") or None), model_reason=payload.get("model_reason", ""),
            work_item_id=payload.get("work_item_id"),
        )

    def emit_terminal(
        self, *, outcome: str, step: int | None, floor: str | None, request_id: str | None,
        error_kind: str | None = None, cause: str | None = None, evidence: str | None = None,
        ask_request_id: str | None = None, parked: bool | None = None,
        work_item_id: str | None = None, requested_tier: str | None = None, effective_tier: str | None = None,
    ) -> None:
        """One terminal record (refused|asked|faulted); never raises."""
        try:
            self.record(
                outcome, step=step if type(step) is int else 0, floor=floor, request_id=request_id,
                error_kind=_token(error_kind), cause=_token(cause), evidence=_token(evidence),
                ask_request_id=ask_request_id, parked=parked, work_item_id=_work_item(work_item_id),
                requested_tier=_tier(requested_tier), effective_tier=_tier(effective_tier),
            )
        except Exception:
            logger.warning(
                "AD-1324: a terminal tier audit record (%s) could not be built; the outcome stands",
                outcome, exc_info=True,
            )

    def record(self, outcome: str, *, work_item_id: str | None = None, **fields: Any) -> None:
        """Write one record (outcome: served|raised|redo|refused|asked|faulted)."""
        record: dict[str, Any] = {
            "event": EVENT_NAME, "agent_id": self._agent_id, "work_item_id": work_item_id,
            "thread_id": self._thread_id, "step": 0, "requested_tier": "", "effective_tier": "",
            "floor": None, "outcome": outcome, "evidence": None, "model_reason": "", "exact": True,
            "request_id": None, "error_kind": None, "cause": None, "ask_request_id": None, "parked": None,
        }
        record.update({k: v for k, v in fields.items() if k in record})
        if self._event_log is None:
            return
        if len(_RETAINED) >= AUDIT_MAX_INFLIGHT:
            logger.warning(
                "AD-1324: %d tier audit writes are still unfinished; the %s record for step %s is "
                "logged only", len(_RETAINED), outcome, record["step"],
            )
            return
        try:
            task = asyncio.get_running_loop().create_task(self._write(record))
        except RuntimeError:
            logger.warning("AD-1324: no running loop; tier audit record for step %s was logged only", record["step"])
            return
        self._tasks.add(task)
        _RETAINED.add(task)
        task.add_done_callback(self._tasks.discard)
        task.add_done_callback(_RETAINED.discard)

    async def drain(self) -> None:
        """Wait up to ``AUDIT_DRAIN_TIMEOUT_S`` for records still being written.

        A slow writer is not cancelled: it finishes in the background and its record lands once.
        Cancellation of the caller propagates.
        """
        pending = [t for t in self._tasks if not t.done()]
        if not pending:
            return
        try:
            await asyncio.wait_for(
                asyncio.shield(asyncio.gather(*pending, return_exceptions=True)), AUDIT_DRAIN_TIMEOUT_S,
            )
        except asyncio.TimeoutError:
            logger.warning(
                "AD-1324: %d tier audit write(s) did not finish within %.2fs; the run continues and "
                "they complete in the background", len(pending), AUDIT_DRAIN_TIMEOUT_S,
            )

    async def _write(self, record: dict[str, Any]) -> None:
        try:
            await self._event_log.log(
                category="cognitive", event=EVENT_NAME, agent_id=record["agent_id"], data=record,
            )
        except Exception:
            logger.warning(
                "AD-1324: tier audit event for agent %s step %s could not be written; the decision "
                "stands and its log line remains", record["agent_id"][:12], record["step"], exc_info=True,
            )
