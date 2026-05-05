"""OptimizationCounselor — watchdog for AD-659b ChainOptimizer apply path.

AD-659c v1: subscribes to OPTIMIZATION_PROPOSAL_APPLIED events; for each
applied proposal, snapshots a pre-apply success-rate baseline from
`runtime.cognitive_journal` chain traces, schedules a delayed watchdog check,
compares post-apply metrics to baseline, persists the decision, optionally
auto-reverts (gated by `auto_revert_enabled`, default False).

The counselor never raises into the runtime — every external call is wrapped
in tier-2 log-and-degrade.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import asdict, dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class OptimizationDecision:
    """Single watchdog decision record (audit trail row)."""

    proposal_id: str
    decided_at: float
    decision: str  # "regression" | "no_regression" | "skipped" | "revert_failed"
    baseline_success_rate: float | None = None
    post_success_rate: float | None = None
    drop_amount: float | None = None
    sample_count_baseline: int = 0
    sample_count_post: int = 0
    auto_revert_attempted: bool = False
    auto_revert_succeeded: bool = False
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _success_rate(traces: list[dict[str, Any]]) -> tuple[float, int]:
    """Return (success_rate, sample_count) from a list of chain trace rows.

    success_rate is 0.0 when sample_count is 0.
    """
    n = len(traces)
    if n == 0:
        return (0.0, 0)
    succ = sum(1 for r in traces if int(bool(r.get("success", 0))))
    return (succ / n, n)


class OptimizationCounselor:
    """Watchdog for AD-659b applied proposals (AD-659c v1).

    Lifecycle:
        await counselor.start()  # subscribes to OPTIMIZATION_PROPOSAL_APPLIED
        await counselor.stop()   # cancels in-flight watchdog tasks

    Flow per applied proposal:
        1. _on_apply_event captures baseline success rate from chain traces
           (last `baseline_window_seconds` before applied_at).
        2. Schedules `_watchdog_check(proposal_id, baseline_rate, baseline_n)`
           via asyncio.create_task with `await asyncio.sleep(observation_window_seconds)`.
        3. Watchdog reads chain traces from applied_at to now, computes post
           success rate, compares to baseline.
        4. If `(baseline - post) >= success_rate_drop_floor`, records a
           regression decision + emits OPTIMIZATION_REGRESSION_DETECTED.
        5. If `auto_revert_enabled` AND regression detected, calls
           `runtime.chain_optimizer.revert_proposal(proposal_id, actor="optimization_counselor")`.
        6. Persists the decision to runtime.cognitive_journal.
    """

    def __init__(
        self,
        runtime: Any,
        *,
        baseline_window_seconds: float = 1800.0,
        observation_window_seconds: float = 1800.0,
        success_rate_drop_floor: float = 0.10,
        min_samples_per_window: int = 20,
        auto_revert_enabled: bool = False,
    ) -> None:
        self._runtime = runtime
        self._baseline_window_seconds = float(baseline_window_seconds)
        self._observation_window_seconds = float(observation_window_seconds)
        self._success_rate_drop_floor = float(success_rate_drop_floor)
        self._min_samples_per_window = int(min_samples_per_window)
        self._auto_revert_enabled = bool(auto_revert_enabled)
        # In-flight watchdog tasks per proposal_id (idempotent: re-applied
        # proposals get a new proposal_id; same id during an in-flight window
        # is a no-op replace).
        self._pending_checks: dict[str, asyncio.Task[None]] = {}
        self._listener_attached: bool = False

    async def start(self) -> None:
        """Subscribe to OPTIMIZATION_PROPOSAL_APPLIED events.

        Idempotent — calling twice is a no-op.
        """
        if self._listener_attached:
            return
        from probos.events import EventType
        add_listener = getattr(self._runtime, "add_event_listener", None)
        if add_listener is None:
            logger.warning(
                "AD-659c: runtime.add_event_listener unavailable; "
                "OptimizationCounselor inert"
            )
            return
        try:
            add_listener(
                self._on_apply_event_async,
                event_types=[EventType.OPTIMIZATION_PROPOSAL_APPLIED],
            )
            self._listener_attached = True
        except Exception:
            logger.warning(
                "AD-659c: failed to attach OPTIMIZATION_PROPOSAL_APPLIED listener",
                exc_info=True,
            )

    async def stop(self) -> None:
        """Cancel any in-flight watchdog tasks. Idempotent."""
        tasks = list(self._pending_checks.values())
        self._pending_checks.clear()
        for task in tasks:
            if task.done():
                continue
            task.cancel()
            try:
                await task
            except BaseException:
                pass

    async def _on_apply_event_async(self, event: dict[str, Any]) -> None:
        """Snapshot baseline + schedule watchdog check.

        Event shape (per Section 1a emission):
            {"event_type": "...", "data": {"proposal_id", "applied_at", ...}}
        Some runtimes pass the data dict directly. Tolerate both.
        """
        try:
            data = event.get("data", event) if isinstance(event, dict) else {}
            proposal_id = str(data.get("proposal_id", ""))
            applied_at = float(data.get("applied_at") or time.time())
            if not proposal_id:
                return
            # Snapshot baseline.
            baseline_rate, baseline_n = await self._compute_success_rate_window(
                end_time=applied_at,
                window_seconds=self._baseline_window_seconds,
            )
            # Schedule watchdog. If a check already pending for this id,
            # cancel the old one (last-event-wins).
            existing = self._pending_checks.pop(proposal_id, None)
            if existing is not None and not existing.done():
                existing.cancel()
            task = asyncio.create_task(
                self._watchdog_check(
                    proposal_id=proposal_id,
                    baseline_rate=baseline_rate,
                    baseline_n=baseline_n,
                    applied_at=applied_at,
                )
            )
            self._pending_checks[proposal_id] = task
        except Exception:
            logger.warning(
                "AD-659c: _on_apply_event_async failed",
                exc_info=True,
            )

    async def _compute_success_rate_window(
        self,
        *,
        end_time: float,
        window_seconds: float,
    ) -> tuple[float, int]:
        """Pull chain traces for the [end_time - window, end_time] interval
        from runtime.cognitive_journal and return (success_rate, sample_count).

        Returns (0.0, 0) on any failure or when journal unavailable.
        """
        journal = getattr(self._runtime, "cognitive_journal", None)
        if journal is None:
            return (0.0, 0)
        try:
            # Over-fetch by limit; filter by started_at in Python because
            # get_recent_chain_traces may not honor a `since` upper bound.
            traces = await journal.get_recent_chain_traces(limit=500)
        except Exception:
            return (0.0, 0)
        start = end_time - window_seconds
        windowed = [
            r for r in traces
            if start <= float(r.get("started_at", 0.0)) <= end_time
        ]
        return _success_rate(windowed)

    async def _watchdog_check(
        self,
        *,
        proposal_id: str,
        baseline_rate: float,
        baseline_n: int,
        applied_at: float,
    ) -> None:
        """Sleep observation_window_seconds, then evaluate post-apply metrics.

        Cancellation-safe — re-raises CancelledError after cleanup.
        """
        try:
            await asyncio.sleep(self._observation_window_seconds)
        except asyncio.CancelledError:
            self._pending_checks.pop(proposal_id, None)
            raise
        try:
            now = time.time()
            post_rate, post_n = await self._compute_success_rate_window(
                end_time=now,
                window_seconds=self._observation_window_seconds,
            )
            await self._evaluate_and_record(
                proposal_id=proposal_id,
                baseline_rate=baseline_rate,
                baseline_n=baseline_n,
                post_rate=post_rate,
                post_n=post_n,
                decided_at=now,
            )
        except Exception:
            logger.warning(
                "AD-659c: _watchdog_check evaluation failed for %s",
                proposal_id, exc_info=True,
            )
        finally:
            self._pending_checks.pop(proposal_id, None)

    async def _evaluate_and_record(
        self,
        *,
        proposal_id: str,
        baseline_rate: float,
        baseline_n: int,
        post_rate: float,
        post_n: int,
        decided_at: float,
    ) -> None:
        """Decide regression/no_regression/skipped, persist, optionally revert."""
        journal = getattr(self._runtime, "cognitive_journal", None)
        # Insufficient samples → skipped (not a regression signal).
        if (
            baseline_n < self._min_samples_per_window
            or post_n < self._min_samples_per_window
        ):
            decision = OptimizationDecision(
                proposal_id=proposal_id,
                decided_at=decided_at,
                decision="skipped",
                baseline_success_rate=baseline_rate if baseline_n else None,
                post_success_rate=post_rate if post_n else None,
                drop_amount=None,
                sample_count_baseline=baseline_n,
                sample_count_post=post_n,
                detail=(
                    f"insufficient samples (baseline={baseline_n}, "
                    f"post={post_n}, floor={self._min_samples_per_window})"
                ),
            )
            await self._persist(decision, journal)
            return
        drop = baseline_rate - post_rate
        is_regression = drop >= self._success_rate_drop_floor
        if not is_regression:
            decision = OptimizationDecision(
                proposal_id=proposal_id,
                decided_at=decided_at,
                decision="no_regression",
                baseline_success_rate=baseline_rate,
                post_success_rate=post_rate,
                drop_amount=drop,
                sample_count_baseline=baseline_n,
                sample_count_post=post_n,
                detail=f"drop={drop:.3f} below floor {self._success_rate_drop_floor:.3f}",
            )
            await self._persist(decision, journal)
            return
        # Regression detected.
        revert_attempted = False
        revert_succeeded = False
        revert_detail = ""
        if self._auto_revert_enabled:
            optimizer = getattr(self._runtime, "chain_optimizer", None)
            if optimizer is not None:
                revert_attempted = True
                try:
                    await optimizer.revert_proposal(
                        proposal_id, actor="optimization_counselor",
                    )
                    revert_succeeded = True
                except Exception as exc:
                    revert_detail = f"revert raised: {type(exc).__name__}: {exc}"
                    logger.warning(
                        "AD-659c: auto-revert failed for %s",
                        proposal_id, exc_info=True,
                    )
        decision_label = (
            "revert_failed"
            if revert_attempted and not revert_succeeded
            else "regression"
        )
        decision = OptimizationDecision(
            proposal_id=proposal_id,
            decided_at=decided_at,
            decision=decision_label,
            baseline_success_rate=baseline_rate,
            post_success_rate=post_rate,
            drop_amount=drop,
            sample_count_baseline=baseline_n,
            sample_count_post=post_n,
            auto_revert_attempted=revert_attempted,
            auto_revert_succeeded=revert_succeeded,
            detail=(
                revert_detail
                or f"drop={drop:.3f} >= floor {self._success_rate_drop_floor:.3f}"
            ),
        )
        await self._persist(decision, journal)
        # Emit regression event for downstream subscribers.
        emit_event = getattr(self._runtime, "emit_event", None)
        if emit_event is not None:
            try:
                from probos.events import EventType
                emit_event(EventType.OPTIMIZATION_REGRESSION_DETECTED, {
                    "proposal_id": proposal_id,
                    "baseline_success_rate": baseline_rate,
                    "post_success_rate": post_rate,
                    "drop_amount": drop,
                    "auto_revert_attempted": revert_attempted,
                    "auto_revert_succeeded": revert_succeeded,
                })
            except Exception:
                logger.debug(
                    "AD-659c: emit OPTIMIZATION_REGRESSION_DETECTED failed",
                    exc_info=True,
                )

    async def _persist(
        self, decision: OptimizationDecision, journal: Any,
    ) -> None:
        """Record decision via journal.record_optimization_decision (best-effort)."""
        if journal is None:
            return
        try:
            await journal.record_optimization_decision(**decision.to_dict())
        except Exception:
            logger.debug(
                "AD-659c: _persist failed for %s",
                decision.proposal_id, exc_info=True,
            )
