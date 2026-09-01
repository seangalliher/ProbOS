"""AD-733b: ProactiveVisionObserver — emits a DM when a novel scene
warrants surfacing. Bounded by:
  * scene-introduction-once-per-camera-session
  * AD-674 graduated initiative budget (default 3 emissions/session)
  * minimum dwell time between proactive emissions (default 30s)

The observer runs as a follow-up step inside VisionConsumer._process AFTER
the LLM describe has produced a description. It does NOT subscribe to the
bus directly — it shares the consumer's path so frame admission, cost
discipline, and working memory order are preserved.

Tier-2 log-and-degrade: a failed proactive emission never blocks the
working-memory write or the episode anchor.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any

# BF-790: this module must tell a policy refusal from a delivery failure.
from probos.mesh.pre_intent_auth import IntentAuthorizationDenied

logger = logging.getLogger(__name__)


@dataclass
class _SessionState:
    """Per-(session, agent) emission accounting."""
    introduction_sent: bool = False
    proactive_emissions: int = 0
    last_emission_at: float = 0.0


@dataclass
class ProactiveBudget:
    """AD-674 graduated initiative — visual variant."""
    max_emissions_per_session: int = 3
    min_dwell_seconds: float = 30.0
    novelty_threshold: float = 0.50


class ProactiveVisionObserver:
    """Decides when to emit a proactive DM about a flagged frame."""

    def __init__(
        self,
        runtime: Any,
        *,
        budget: ProactiveBudget | None = None,
    ) -> None:
        self._runtime = runtime
        self._budget = budget or ProactiveBudget()
        # Keyed by (session_id, agent_id). Reset on session_began.
        self._state: dict[tuple[str, str], _SessionState] = {}

    def reset_session(self, session_id: str, agent_id: str) -> None:
        self._state.pop((session_id, agent_id), None)

    async def maybe_emit(
        self,
        *,
        session_id: str,
        agent_id: str,
        observation: Any,  # VisionObservation
        is_first_observation: bool,
    ) -> bool:
        """Return True if a proactive DM was emitted, False otherwise.

        Tier-2: every branch handles exceptions internally; only False
        is returned on any failure.
        """
        try:
            return await self._decide_and_emit(
                session_id=session_id,
                agent_id=agent_id,
                observation=observation,
                is_first_observation=is_first_observation,
            )
        except Exception:
            logger.warning(
                "AD-733b: proactive emission decision failed for agent=%s session=%s",
                agent_id, session_id[:8], exc_info=True,
            )
            return False

    async def _decide_and_emit(
        self,
        *,
        session_id: str,
        agent_id: str,
        observation: Any,
        is_first_observation: bool,
    ) -> bool:
        key = (session_id, agent_id)
        state = self._state.setdefault(key, _SessionState())
        now = time.monotonic()

        # Trigger 1: scene introduction — first frame ever in this session.
        if is_first_observation and not state.introduction_sent:
            # BF-813: RESERVE the budget, then refund what a non-delivery did
            # not use. Two constraints pull against each other here.
            #
            # A refused emission must not consume the AD-674 allowance --
            # measured against a denying bus, a denial was byte-identical to a
            # delivery (emissions=1, dwell set, True). But simply moving the
            # mutation after the ``await`` splits check-then-act across a
            # suspension point: measured with two concurrent frames against
            # ``max_emissions=1``, BOTH passed the gate and emitted. Reserving
            # keeps the decision atomic within one loop step, exactly as the
            # pre-BF-813 code was, and errs towards one FEWER proactive DM.
            state.introduction_sent = True
            state.proactive_emissions += 1
            state.last_emission_at = now
            delivered = await self._dispatch_proactive_dm(
                agent_id=agent_id,
                session_id=session_id,
                reason="scene_introduction",
                observation=observation,
            )
            if not delivered:
                # The dwell clock is NOT refunded. A refused attempt costs a
                # dwell so a standing refusal cannot re-attempt on every
                # eligible frame; only the delivery allowance is given back.
                state.introduction_sent = False
                state.proactive_emissions -= 1
                return False
            return True

        # Trigger 2: high-novelty mid-session.
        if observation.novelty_score < self._budget.novelty_threshold:
            return False
        if state.proactive_emissions >= self._budget.max_emissions_per_session:
            logger.debug(
                "AD-733b: proactive budget exhausted for agent=%s session=%s",
                agent_id, session_id[:8],
            )
            return False
        if now - state.last_emission_at < self._budget.min_dwell_seconds:
            return False

        state.proactive_emissions += 1
        state.last_emission_at = now
        delivered = await self._dispatch_proactive_dm(
            agent_id=agent_id,
            session_id=session_id,
            reason="high_novelty",
            observation=observation,
        )
        if not delivered:
            state.proactive_emissions -= 1
            return False
        return True

    async def _dispatch_proactive_dm(
        self,
        *,
        agent_id: str,
        session_id: str,
        reason: str,
        observation: Any,
    ) -> bool:
        """Send a proactive DM to the agent so the agent's LLM composes the
        actual user-visible message. We do NOT compose user-facing text
        here — the agent does, via its own voice profile, using the
        observation in its working memory.

        BF-813: returns False on a KNOWN non-delivery -- a policy refusal, a
        dispatch failure, or a handler that ran and reported failure. It used
        to return None on every path, so the caller could not tell any of those
        from a delivery and charged the budget either way.

        A ``None`` envelope is deliberately NOT a known non-delivery. It means
        no subscriber OR a handler that timed out, and a timed-out handler may
        still compose the DM -- so refunding on it would risk a second
        proactive DM about the same frame. Silence is not proof that nothing
        happened.
        """
        from probos.types import IntentMessage

        if reason == "scene_introduction":
            user_turn = (
                "[SYSTEM-INITIATED: camera just turned on. You may briefly greet "
                "the Captain and describe what you observe — once, then wait for "
                "the Captain's reply. Keep it under 60 words.]"
            )
        else:
            user_turn = (
                "[SYSTEM-INITIATED: the scene in front of you changed materially. "
                "If — and only if — the change is worth mentioning to the Captain, "
                "say one short observation. Otherwise stay silent by returning an empty reply.]"
            )

        intent = IntentMessage(
            intent="direct_message",
            params={
                "text": user_turn,
                "from": "hxi_profile",
                "session": True,
                "is_proactive_vision": True,
                "session_id": session_id,
                "proactive_reason": reason,
            },
            target_agent_id=agent_id,
            ttl_seconds=60.0,
        )
        try:
            # BF-790: opt in to the raise. The default denial shape is ``None``,
            # which is indistinguishable here from a delivered DM -- so a REFUSED
            # proactive vision DM was logged as "dispatched" AND nudged the mode
            # controller from AMBIENT to ENGAGED, escalating the ship's
            # perception posture on the strength of a message policy refused.
            # Caught ahead of the broad handler below because a refusal is not a
            # failure: nothing is retried, nothing is broken, and reporting it as
            # a dispatch failure sends an operator to diagnose an outage that is
            # not happening (DP 13(c)).
            result = await self._runtime.intent_bus.send(intent, raise_on_denial=True)
            # BF-813: a handler that RAN and reported failure is a known
            # non-delivery, distinct from the ``None`` envelope above.
            if result is not None and getattr(result, "success", True) is False:
                logger.info(
                    "BF-813: proactive vision DM to %s was handled but failed "
                    "(%s); the budget is refunded and the mode controller is "
                    "not nudged",
                    agent_id, getattr(result, "error", "") or "no error given",
                )
                return False
            logger.info(
                "AD-733b: proactive vision DM dispatched agent=%s reason=%s novelty=%.2f",
                agent_id, reason, observation.novelty_score,
            )
            # AD-733c-2: nudge the mode controller on high-novelty emissions
            # so AMBIENT -> ENGAGED. Scene introductions also pass through
            # this path; the controller's AMBIENT -> ENGAGED transition is
            # idempotent and trigger-tagged "novelty" for both cases.
            _mode_ctrl = getattr(self._runtime, "perception_mode_controller", None)
            if _mode_ctrl is not None:
                try:
                    _mode_ctrl.note_high_novelty_event()
                except Exception:
                    logger.debug(
                        "AD-733c-2: note_high_novelty_event raised",
                        exc_info=True,
                    )
        except IntentAuthorizationDenied as exc:
            # BF-790: neither "dispatched" nor "failed" -- refused. The mode
            # controller is deliberately NOT nudged: no DM reached the Captain,
            # so there is nothing for the ship to become more engaged about.
            logger.info(
                "BF-790: proactive vision DM to %s refused by '%s'; the mode "
                "controller is not nudged and nothing is retried",
                agent_id, exc.reason,
            )
            return False
        except Exception:
            logger.warning(
                "AD-733b: proactive DM dispatch failed agent=%s reason=%s",
                agent_id, reason, exc_info=True,
            )
            return False
        return True


__all__ = ["ProactiveVisionObserver", "ProactiveBudget"]
