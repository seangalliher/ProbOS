"""AD-743: Adaptive conversational pacing scheduler for active 1:1 DMs.

This module owns ``ConversationPacingScheduler``, a sibling runtime
service that delivers a synthesized user-turn ``IntentMessage`` after a
configurable delay when an agent's reply carried a ``[FOLLOW_UP delay
reason]`` bracket marker. Captain interruption (a fresh DM) cancels any
pending follow-up before the agent fires again.

Design notes
------------
- The scheduler does NOT compose text. It emits a synthesized
  ``direct_message`` intent whose body is a marker
  (``[CONVERSATION_FOLLOW_UP reason=<reason>]``); the agent's own LLM
  composes the visible follow-up via its voice profile.
- Single-flight per ``(agent_id, conversation_id)``. A later FOLLOW_UP
  override cancels the prior pending task.
- Two-budget rate limit (mirrors AD-728c pattern): per active
  conversation, and per agent per hour.
- ``schedule_followup`` is sync (just spawns an asyncio task). The
  task awaits ``IntentBus.send`` without holding the scheduler lock.

AD-731 invariant: no image bytes. Source-scan test guards against
regression by asserting absence of forbidden literals in this file.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING, Any

from ...types import IntentMessage
from ...mesh.pre_intent_auth import IntentAuthorizationDenied

if TYPE_CHECKING:  # pragma: no cover - import-cycle guard
    from ...runtime import ProbOSRuntime

logger = logging.getLogger(__name__)


class ConversationPacingScheduler:
    """AD-743: schedule synthesized user-turn follow-ups for active DMs.

    One instance per runtime. Tracks pending tasks by
    ``(agent_id, conversation_id)`` and enforces two budgets:

    - ``pacing_max_followups_per_active_conversation`` (resets when the
      conversation falls out of the active window).
    - ``pacing_max_followups_per_hour_per_agent`` (rolling 1h ceiling).
    """

    def __init__(self, runtime: "ProbOSRuntime") -> None:
        self._runtime = runtime
        self._pending_tasks: dict[tuple[str, str], asyncio.Task[Any]] = {}
        # Per-conversation counters keyed by (agent_id, conversation_id) →
        # (count, last_followup_ts). Reset when last_followup_ts is older
        # than ``pacing_active_window_seconds``.
        self._conv_counts: dict[tuple[str, str], tuple[int, float]] = {}
        # Per-agent hourly log of follow-up timestamps.
        self._agent_history: dict[str, list[float]] = {}
        self._started = False

    async def start(self) -> None:
        """Mark scheduler active. No background task; per-followup tasks
        are spawned lazily."""
        self._started = True
        logger.info("AD-743: ConversationPacingScheduler started")

    async def stop(self) -> None:
        """Cancel all pending follow-up tasks; await teardown."""
        if not self._started:
            return
        self._started = False
        pending = list(self._pending_tasks.values())
        for task in pending:
            task.cancel()
        for task in pending:
            try:
                await task
            except (asyncio.CancelledError, Exception):  # pragma: no cover
                pass
        self._pending_tasks.clear()
        logger.info("AD-743: ConversationPacingScheduler stopped")

    @property
    def pending_followups(self) -> dict[tuple[str, str], asyncio.Task[Any]]:
        """Read-only view of currently pending follow-up tasks."""
        return dict(self._pending_tasks)

    def cancel_for_conversation(
        self, agent_id: str, conversation_id: str = "default"
    ) -> bool:
        """Cancel any pending follow-up for this (agent, conversation).

        Returns True if a task was cancelled, False if none was pending.
        Called when Captain sends a fresh DM (interrupts the follow-up).
        """
        key = (agent_id, conversation_id)
        task = self._pending_tasks.pop(key, None)
        if task is None:
            return False
        if not task.done():
            task.cancel()
        logger.debug(
            "AD-743: cancelled pending follow-up for agent=%s conv=%s "
            "(Captain interrupt)",
            agent_id,
            conversation_id,
        )
        return True

    def schedule_followup(
        self,
        agent_id: str,
        delay_seconds: int,
        reason: str,
        conversation_id: str = "default",
    ) -> bool:
        """Schedule a follow-up after ``delay_seconds``.

        Returns True if scheduled, False if blocked (budget exhausted,
        scheduler stopped, or invalid delay). Existing pending task for
        the same (agent, conversation) is cancelled (single-flight).
        """
        if not self._started:
            logger.debug(
                "AD-743: schedule_followup ignored — scheduler not started"
            )
            return False

        cfg = self._get_pacing_config()
        if cfg is None or not cfg["enabled"]:
            return False

        min_d = cfg["min_delay_seconds"]
        max_d = cfg["max_delay_seconds"]
        if delay_seconds < min_d or delay_seconds > max_d:
            logger.warning(
                "AD-743: follow-up delay %d out of bounds [%d, %d] for "
                "agent=%s reason=%r — discarded",
                delay_seconds,
                min_d,
                max_d,
                agent_id,
                reason,
            )
            return False

        now = time.time()
        if not self._check_budgets(agent_id, conversation_id, now, cfg):
            return False

        # Single-flight: cancel any prior pending follow-up.
        key = (agent_id, conversation_id)
        prior = self._pending_tasks.pop(key, None)
        if prior is not None and not prior.done():
            prior.cancel()

        # Record the budget usage.
        self._record_followup(agent_id, conversation_id, now, cfg)

        # Spawn the follow-up task.
        task = asyncio.create_task(
            self._emit_followup(agent_id, delay_seconds, reason, conversation_id)
        )
        self._pending_tasks[key] = task
        task.add_done_callback(
            lambda _t, _k=key: self._pending_tasks.pop(_k, None)
        )
        logger.info(
            "AD-743: scheduled follow-up agent=%s conv=%s delay=%ds reason=%r",
            agent_id,
            conversation_id,
            delay_seconds,
            reason,
        )
        return True

    async def _emit_followup(
        self,
        agent_id: str,
        delay_seconds: int,
        reason: str,
        conversation_id: str,
    ) -> None:
        """Sleep then emit the synthesized user-turn intent."""
        try:
            await asyncio.sleep(delay_seconds)
        except asyncio.CancelledError:
            logger.debug(
                "AD-743: follow-up cancelled mid-sleep for agent=%s conv=%s",
                agent_id,
                conversation_id,
            )
            raise

        try:
            intent = IntentMessage(
                intent="direct_message",
                params={
                    "text": f"[CONVERSATION_FOLLOW_UP reason={reason}]",
                    "from": "pacing_scheduler",
                    "conversation_id": conversation_id,
                    "reason": reason,
                },
                target_agent_id=agent_id,
                ttl_seconds=60.0,
            )
            bus = getattr(self._runtime, "intent_bus", None)
            if bus is None:
                logger.warning(
                    "AD-743: runtime has no intent_bus; follow-up dropped for "
                    "agent=%s reason=%r",
                    agent_id,
                    reason,
                )
                return
            # BF-790: opt in, so a refused follow-up is not logged as emitted.
            await bus.send(intent, raise_on_denial=True)
            logger.info(
                "AD-743: follow-up emitted agent=%s conv=%s reason=%r",
                agent_id,
                conversation_id,
                reason,
            )
        except asyncio.CancelledError:
            raise
        except IntentAuthorizationDenied as exc:
            # BF-790: distinct from the failure below -- nothing broke, policy
            # refused. Logging it as "failed to emit" would send anyone reading
            # the log looking for a fault that does not exist.
            logger.info(
                "AD-743: follow-up refused by pre-intent policy '%s' agent=%s "
                "reason=%r",
                exc.reason,
                agent_id,
                reason,
            )
        except Exception:
            logger.warning(
                "AD-743: failed to emit follow-up agent=%s reason=%r",
                agent_id,
                reason,
                exc_info=True,
            )

    # ── Budgets ────────────────────────────────────────────────

    def _get_pacing_config(self) -> dict[str, Any] | None:
        """Read pacing config fresh on every call (BF-308 hot-reload).

        Returns a dict of normalized fields, or None when avatars config
        is missing.
        """
        try:
            cfg = getattr(self._runtime, "config", None)
            av = getattr(cfg, "avatars", None) if cfg is not None else None
            if av is None:
                return None
            return {
                "enabled": bool(getattr(av, "pacing_enabled", False)),
                "per_conv_max": int(
                    getattr(av, "pacing_max_followups_per_active_conversation", 2)
                ),
                "per_hour_max": int(
                    getattr(av, "pacing_max_followups_per_hour_per_agent", 6)
                ),
                "active_window_seconds": int(
                    getattr(av, "pacing_active_window_seconds", 600)
                ),
                "min_delay_seconds": int(
                    getattr(av, "pacing_min_delay_seconds", 1)
                ),
                "max_delay_seconds": int(
                    getattr(av, "pacing_max_delay_seconds", 300)
                ),
            }
        except Exception:
            logger.warning(
                "AD-743: failed to read pacing config; treating as disabled",
                exc_info=True,
            )
            return None

    def _check_budgets(
        self,
        agent_id: str,
        conversation_id: str,
        now: float,
        cfg: dict[str, Any],
    ) -> bool:
        """Return True if the follow-up is within both budgets."""
        # Per-conversation budget (resets on inactivity).
        key = (agent_id, conversation_id)
        count, last_ts = self._conv_counts.get(key, (0, 0.0))
        if now - last_ts > cfg["active_window_seconds"]:
            count = 0
        if count >= cfg["per_conv_max"]:
            logger.warning(
                "AD-743: per-conversation follow-up budget exhausted "
                "(%d/%d) for agent=%s conv=%s — discarded",
                count,
                cfg["per_conv_max"],
                agent_id,
                conversation_id,
            )
            return False

        # Per-agent hourly budget.
        history = self._agent_history.get(agent_id, [])
        hour_ago = now - 3600.0
        history = [ts for ts in history if ts >= hour_ago]
        if len(history) >= cfg["per_hour_max"]:
            logger.warning(
                "AD-743: per-agent hourly follow-up budget exhausted "
                "(%d/%d) for agent=%s — discarded",
                len(history),
                cfg["per_hour_max"],
                agent_id,
            )
            self._agent_history[agent_id] = history
            return False
        return True

    def _record_followup(
        self,
        agent_id: str,
        conversation_id: str,
        now: float,
        cfg: dict[str, Any],
    ) -> None:
        """Stamp a successful schedule against both budgets."""
        key = (agent_id, conversation_id)
        count, last_ts = self._conv_counts.get(key, (0, 0.0))
        if now - last_ts > cfg["active_window_seconds"]:
            count = 0
        self._conv_counts[key] = (count + 1, now)

        history = self._agent_history.get(agent_id, [])
        hour_ago = now - 3600.0
        history = [ts for ts in history if ts >= hour_ago]
        history.append(now)
        self._agent_history[agent_id] = history
