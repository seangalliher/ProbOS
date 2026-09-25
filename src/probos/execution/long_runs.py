"""AD-1246: a long ``run_python`` execution inside a turn that can stop waiting.

The unit that promotes stays the TURN (AD-1165): a 1:1 DM agentic turn that
outlives ``dm_agentic.promote_to_task_after_seconds`` becomes a background work
item without being cancelled or re-run. What stopped a long job was the tool's
inline wall clock, which every caller shares whether or not it can wait. This
module carries more reach to the one caller that can, and nowhere else:

* ``LongRunGrant`` -- created by the DM turn only when it can be promoted and
  the vessel is armed (``execution.max_runtime_seconds`` above the inline
  clock). It rides the invocation context under ``EXECUTION_LONG_RUN_GRANT_KEY``.
* ``plan_long_run`` -- the tool's single decision. ``None`` means today's path,
  byte for byte.
* ``LongRunService`` -- the ship-wide slots, a dedicated executor (so a long run
  never occupies a thread of the shared default executor) and one
  ``KillSwitch`` per admitted run.

Nothing here cancels or re-runs anything. A long run ends on its own wall
clock, when the turn awaiting it is cancelled (nobody is left to report it), or
when ``LongRunService.close`` fires its kill switch.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import logging
import math
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable

from probos.execution.isolation import KillSwitch

logger = logging.getLogger(__name__)

# The longest wall clock a call gets when its caller cannot hand the work to the
# background. It is the value that shipped (the literal ``_resolve_timeout``
# used to carry); this AD keeps it rather than re-deriving it. It stops a runaway
# script from holding such a caller, its thread and its child for longer, and
# costs any job there that needs more. Read through this module attribute at call
# time, never imported by name, so one patch reaches every reader.
INLINE_WALL_CLOCK_SECONDS: float = 300.0

# Invocation-context key that carries a ``LongRunGrant`` from the DM turn to the tool.
EXECUTION_LONG_RUN_GRANT_KEY: str = "_execution_long_run_grant"

# Held back from the turn's BF-733 deadline so the model can still read the
# result and answer before the watchdog stops the turn. It equals one LLM call
# at the 300 s tier timeout the shipped config/system.yaml sets
# (``cognitive.llm_timeout_seconds``); a re-tuned timeout does not move it. It
# costs a granted run that much of the turn's deadline.
_LONG_RUN_ANSWER_MARGIN_SECONDS: float = 300.0

# How long the stop path waits for killed runs to reach their audit record. It
# equals the tool's launch-resolve bound (``execution.audit.LAUNCH_RESOLVE_SECONDS``)
# and is a fifth of the 10 s budget ``__main__`` gives ``runtime.stop()``; a stop
# that finds a long run still unwinding can take up to that much longer.
LONG_RUN_SETTLE_SECONDS: float = 2.0

# The upper bound of ``execution.max_concurrent_long_runs``, so every admitted
# run has a pool thread of its own. A cancelled run's thread stays busy for the
# few milliseconds its reap takes after its slot is released. Threads start on
# demand and stay until ``close``, so it costs at most this many idle threads.
_LONG_RUN_POOL_WORKERS: int = 16


def coerce_positive_seconds(raw: Any) -> float:
    """A real, finite, positive number of seconds, else ``0.0`` (meaning off).

    The rule ``cognitive_agent._coerce_promotion_budget`` applies, restated
    because this layer cannot import it: an exact ``type`` check, so a ``bool``
    or a MagicMock attribute reads as 0 instead of reaching a comparison.
    """
    if type(raw) not in (int, float):
        return 0.0
    value = float(raw)
    if not math.isfinite(value) or value <= 0.0:
        return 0.0
    return value


@dataclass(frozen=True)
class LongRunGrant:
    """Permission for one turn's ``run_python`` calls to ask for more than the inline clock.

    ``deadline_monotonic`` estimates when the turn's BF-733 watchdog would stop
    it, less the answer margin. ``None`` means BF-733 is off, so the turn has no
    deadline of its own.
    """

    deadline_monotonic: float | None

    def remaining(self, now: float | None = None) -> float:
        """Seconds left before the estimate; ``inf`` with no deadline; may be negative."""
        if self.deadline_monotonic is None:
            return math.inf
        return self.deadline_monotonic - (time.monotonic() if now is None else now)

    @classmethod
    def for_promoted_turn(
        cls,
        *,
        max_runtime_seconds: Any,
        promote_after_seconds: Any,
        deadline_seconds: Any,
        now: float,
    ) -> LongRunGrant | None:
        """The grant for a DM turn that AD-1165 can promote, or ``None``.

        ``None`` unless the vessel is armed and promotion is on. The watchdog
        starts at promotion, and promotion comes no earlier than
        ``promote_after_seconds`` after ``now``, so the estimate is never later
        than the real deadline: any error is extra margin.
        """
        if coerce_positive_seconds(max_runtime_seconds) <= INLINE_WALL_CLOCK_SECONDS:
            return None
        promote_after = coerce_positive_seconds(promote_after_seconds)
        if promote_after <= 0.0:
            return None
        deadline = coerce_positive_seconds(deadline_seconds)
        if deadline <= 0.0:
            return cls(None)
        return cls(now + promote_after + deadline - _LONG_RUN_ANSWER_MARGIN_SECONDS)


class LongRunTicket:
    """One admitted long run: its slot, its kill switch and the executor it runs on.

    Constructed only by ``LongRunService.admit``.
    """

    def __init__(
        self,
        *,
        execution_id: str,
        executor: concurrent.futures.Executor,
        settled: asyncio.Future[None],
        on_finish: Callable[[str], None],
    ) -> None:
        self.execution_id = execution_id
        self.kill_switch = KillSwitch()
        self.executor = executor
        self.settled = settled
        self._on_finish = on_finish

    def finish(self) -> None:
        """Release the slot, then mark the run settled. Idempotent; never raises.

        Called on the loop thread, first in the tool's outermost ``finally``.
        """
        try:
            self._on_finish(self.execution_id)
        except Exception:  # noqa: BLE001 -- the caller's teardown must still run
            logger.warning(
                "AD-1246: releasing long-run slot %s raised; the slot may stay "
                "held, and the run is marked settled so no settle wait blocks on it",
                self.execution_id, exc_info=True,
            )
        if not self.settled.done():
            self.settled.set_result(None)


class LongRunService:
    """Ship-wide owner of long ``run_python`` executions (AD-1246).

    Holds the admitted runs, the dedicated executor they run on and a kill
    switch per run. Constructing it creates no thread, executor or loop object;
    the executor is created by the first admission.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._active: dict[str, LongRunTicket] = {}
        self._closed = False
        self._executor: concurrent.futures.ThreadPoolExecutor | None = None

    @property
    def active_count(self) -> int:
        """Admitted runs whose ticket has not finished."""
        with self._lock:
            return len(self._active)

    @property
    def closed(self) -> bool:
        """True once ``close`` ran; no further run is admitted."""
        with self._lock:
            return self._closed

    def admit(self, execution_id: str, *, limit: int) -> LongRunTicket | None:
        """A ticket for one long run, or ``None`` when closed, full or a duplicate.

        Synchronous and never blocks. Must be called on the running loop, which
        owns the ticket's ``settled`` future.
        """
        loop = asyncio.get_running_loop()
        with self._lock:
            if self._closed or len(self._active) >= limit or execution_id in self._active:
                return None
            if self._executor is None:
                self._executor = concurrent.futures.ThreadPoolExecutor(
                    max_workers=_LONG_RUN_POOL_WORKERS,
                    thread_name_prefix="probos-long-run",
                )
            ticket = LongRunTicket(
                execution_id=execution_id,
                executor=self._executor,
                settled=loop.create_future(),
                on_finish=self._release,
            )
            self._active[execution_id] = ticket
        return ticket

    def close(self, reason: str) -> None:
        """Refuse further admission and fire every active run's kill switch.

        Synchronous and idempotent. In-flight workers keep their threads: each
        still has to reap its killed child and return that result.
        """
        with self._lock:
            if self._closed:
                return
            self._closed = True
            tickets = list(self._active.values())
            executor = self._executor
        for ticket in tickets:
            ticket.kill_switch.fire(reason)
        if executor is not None:
            executor.shutdown(wait=False)
        # Silent when nothing was running, so an unarmed or idle vessel's
        # shutdown log is unchanged.
        if tickets:
            logger.info(
                "AD-1246: long-run service closed (%s); fired the kill switch of %d "
                "active run(s) and refuses any further long run",
                reason, len(tickets),
            )

    async def wait_settled(self, timeout: float) -> bool:
        """Wait up to ``timeout`` for every active run to settle; True when all did.

        Returns without suspending when nothing is active.
        """
        with self._lock:
            pending = {
                ticket.settled: ticket.execution_id
                for ticket in self._active.values()
                if not ticket.settled.done()
            }
        if not pending:
            return True
        _, unsettled = await asyncio.wait(set(pending), timeout=timeout)
        if unsettled:
            logger.warning(
                "AD-1246: %d long run(s) did not settle within %.1fs (%s); "
                "continuing without waiting for them",
                len(unsettled), timeout,
                ", ".join(sorted(pending[future] for future in unsettled)),
            )
            return False
        return True

    def _release(self, execution_id: str) -> None:
        with self._lock:
            self._active.pop(execution_id, None)


@dataclass(frozen=True)
class LongRunPlan:
    """The applied wall clock for one granted call, its ticket, and why it was lowered."""

    timeout_seconds: float
    ticket: LongRunTicket | None
    wall_clock: dict[str, Any] | None


_WALL_CLOCK_NOTES: dict[str, str] = {
    "long_runs_busy": (
        "Every long-run slot was in use, so this run had the {applied:.0f}s "
        "inline wall clock. Run it again once a long job finishes, or split the work."
    ),
    "turn_time_left": (
        "The conversation turn that asked for this is near its own deadline, so "
        "the run was given {applied:.0f}s, leaving time for the report."
    ),
    "max_runtime": (
        "This vessel stops a single long run at {applied:.0f}s "
        "(execution.max_runtime_seconds). Split the work into steps that fit."
    ),
}


def _wall_clock(requested: float, applied: float, reason: str) -> dict[str, Any]:
    return {
        "requested_seconds": float(requested),
        "applied_seconds": float(applied),
        "reason": reason,
        "note": _WALL_CLOCK_NOTES[reason].format(applied=applied),
    }


def plan_long_run(
    requested: Any,
    *,
    max_runtime_seconds: Any,
    max_concurrent: Any,
    grant: Any,
    service: Any,
    execution_id: str,
) -> LongRunPlan | None:
    """Decide one ``run_python`` call's wall clock. ``None`` means today's path.

    A plan exists only for a granted call on an armed vessel that asked for more
    than the inline clock. It never applies less than the inline clock: the
    turn's remaining time, ``max_runtime_seconds`` and a full service can each
    lower the request, and each lowering is explained in ``wall_clock``.
    """
    ceiling = INLINE_WALL_CLOCK_SECONDS
    max_runtime = coerce_positive_seconds(max_runtime_seconds)
    if max_runtime <= ceiling:
        return None
    if type(max_concurrent) is not int or max_concurrent < 1:
        return None
    if type(grant) is not LongRunGrant or not isinstance(service, LongRunService):
        return None
    if requested is None:
        return None
    try:
        wanted = float(requested)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(wanted) or wanted <= ceiling:
        return None
    ticket = service.admit(
        execution_id, limit=min(max_concurrent, _LONG_RUN_POOL_WORKERS),
    )
    if ticket is None:
        return LongRunPlan(ceiling, None, _wall_clock(wanted, ceiling, "long_runs_busy"))
    remaining = grant.remaining()
    applied = max(ceiling, min(wanted, max_runtime, remaining))
    if applied >= wanted:
        return LongRunPlan(applied, ticket, None)
    reason = "max_runtime" if max_runtime <= remaining else "turn_time_left"
    return LongRunPlan(applied, ticket, _wall_clock(wanted, applied, reason))
