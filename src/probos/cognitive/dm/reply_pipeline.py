"""AD-726: post-LLM cleanup pipeline for the DM one-shot path.

Nine ordered steps replicate the prior inline cascade in
``routers/agents.py:agent_chat``. Each step is a Tier-2
log-and-degrade boundary internally; the orchestrator
(:meth:`run`) wraps the whole chain in a top-level guard so a
runaway step never blocks the reply. Step ordering is load-bearing:
sanity gate MUST run before challenge / move parsers (challenge/move
markers are stripped by the sanity gate's retry path); self-check
marker parse MUST run before episodic store so the marker does not
leak into stored episode text; divergence check MUST run before
``mark_reply_emitted`` (snap-time invariant); emotion resolution MUST
run after divergence (reads ``divergence_results``).
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class DmReplyContext:
    """Mutable context threaded through every pipeline step.

    NOT frozen by design: ``response_text`` and ``emotion`` are mutated
    in place by the sanity gate, challenge/move strip, divergence check,
    and emotion-resolution steps. AD-726c will introduce a frozen
    ``DmReply`` final shape once AD-726a + AD-726b land and the full
    contract stabilizes.
    """

    runtime: Any
    agent: Any
    agent_id: str
    callsign: str | None
    req_message: str
    response_text: str
    has_image_attachment: bool
    per_attachment: list[dict[str, object]]
    sanity_gate: Any | None
    # AD-726 revision (2026-05-14): params + message_text are read by
    # step_1_sanity_gate_retry when building the AD-724-1 retry IntentMessage.
    # Sourced from the handler's pre-LLM scope (line 1216 / 1046) — safe to
    # pass through unchanged.
    params: dict[str, object]
    message_text: str
    sampling_state: Any | None
    avatar_event_bus: Any | None
    emotion: str | None = None
    game_move_result: dict[str, Any] | None = None
    # AD-728d: task reference for the fire-and-forget check_own_render
    # dispatch. Held on ctx so the asyncio runtime does not GC the
    # coroutine mid-flight. Tier-2: read by tests, not by other steps.
    _self_check_task: "asyncio.Task[None] | None" = None
    # NOTE: ``sanity_result`` is intentionally NOT a ctx field — it is
    # produced and consumed entirely within step_1_sanity_gate_retry.


class DmReplyPipeline:
    """Nine-step post-LLM cleanup chain for the DM one-shot path."""

    def __init__(self, ctx: DmReplyContext) -> None:
        self.ctx = ctx

    async def run(self) -> None:
        """Execute every step in order. Top-level guard preserves the
        Tier-2 contract: a runaway step is logged but never blocks the
        reply. Per-step guards inside the methods are preserved verbatim
        from the prior inline code; the top-level guard is belt-and-braces.
        """
        for step in (
            self.step_1_sanity_gate_retry,
            self.step_2_challenge_parse,
            self.step_3_move_parse,
            self.step_4_self_check_parse,
            self.step_4b_dm_outbound_parse,
            self.step_5_episodic_store,
            self.step_6_working_memory_record,
            self.step_7_divergence_check,
            self.step_8_mark_emitted,
            self.step_9_emotion_resolve,
        ):
            try:
                await step()
            except Exception:
                logger.warning(
                    "AD-726: pipeline step %s raised for agent=%s; continuing",
                    step.__name__, self.ctx.agent_id, exc_info=True,
                )

    # --- step 1: DM sanity gate one-shot retry (AD-724-1) ---
    async def step_1_sanity_gate_retry(self) -> None:
        """AD-724: DM sanity gate + AD-724-1 one-shot retry. Verbatim move."""
        # AD-722a-4: clear the per-utterance correction slot from the
        # PRIOR reply. TTS has had its chance to read it between the
        # prior reply's return and this new reply's arrival. Clearing
        # here — not in step_7 — keeps the slot populated through the
        # TTS read window. Tier-2 guarded: missing slot is benign.
        _corrections = getattr(self.ctx.runtime, "divergence_corrections", None)
        if _corrections is not None:
            _corrections.pop(self.ctx.agent_id, None)
        # AD-724: DM sanity gate (migrates BF-120 markdown strip + adds 3 log-only checks).
        # The gate NEVER blocks; warnings are logged and the cleaned text is returned.
        if self.ctx.response_text and self.ctx.sanity_gate is not None:
            sanity_result = self.ctx.sanity_gate.process(self.ctx.agent_id, self.ctx.response_text)
            self.ctx.response_text = sanity_result.cleaned_text
            # AD-724-1: one controlled retry on rejection. Append a hint to the
            # original Captain text so the agent sees what the gate flagged,
            # without leaking gate internals into Captain-visible output. The
            # gate's second pass honors warnings without a second retry — single
            # bounded loop, never recursive.
            if sanity_result.should_retry:
                from probos.types import IntentMessage
                retry_hint = (
                    "\n\n[SYSTEM_HINT: previous reply was rejected by the DM "
                    "sanity gate (warnings: "
                    + ", ".join(name for name, _ in sanity_result.warnings)
                    + "). Please respond again, carefully.]"
                )
                retry_intent = IntentMessage(
                    intent="direct_message",
                    params={**self.ctx.params, "text": self.ctx.message_text + retry_hint, "is_retry": True},
                    target_agent_id=self.ctx.agent_id,
                    ttl_seconds=60.0,
                )
                try:
                    retry_resp = await self.ctx.runtime.intent_bus.send(retry_intent)
                    retry_text = ""
                    if retry_resp and retry_resp.result:
                        retry_text = str(retry_resp.result)
                    if retry_text:
                        retry_result = self.ctx.sanity_gate.process(self.ctx.agent_id, retry_text)
                        self.ctx.response_text = retry_result.cleaned_text
                        logger.info(
                            "AD-724-1: DM retry for agent %s — "
                            "original_warnings=%s retry_warnings=%s",
                            self.ctx.agent_id,
                            [n for n, _ in sanity_result.warnings],
                            [n for n, _ in retry_result.warnings],
                        )
                except Exception:
                    logger.warning(
                        "AD-724-1: DM retry dispatch failed for agent %s; "
                        "shipping original reply",
                        self.ctx.agent_id, exc_info=True,
                    )

    # --- step 2: BF-119 challenge parse (AD-724) ---
    async def step_2_challenge_parse(self) -> None:
        """BF-119 (migrated to AD-724): Parse [CHALLENGE @callsign game_type] from DM response. Verbatim move."""
        # BF-119 (migrated to AD-724): Parse [CHALLENGE @callsign game_type] from DM response.
        if self.ctx.response_text and hasattr(self.ctx.runtime, 'recreation_service') and self.ctx.runtime.recreation_service:
            challenge_parsed = (
                self.ctx.sanity_gate.extract_challenge(self.ctx.response_text)
                if self.ctx.sanity_gate is not None
                else None
            )
            if challenge_parsed is not None:
                target_callsign, game_type = challenge_parsed
                try:
                    rec_svc = self.ctx.runtime.recreation_service
                    # Resolve target callsign
                    target_agent = None
                    if hasattr(self.ctx.runtime, 'callsign_registry'):
                        target_agent = self.ctx.runtime.callsign_registry.resolve(target_callsign)
                    if target_agent:
                        # Create Recreation channel thread
                        thread_id = ""
                        if self.ctx.runtime.ward_room:
                            channels = await self.ctx.runtime.ward_room.list_channels()
                            rec_ch = next((c for c in channels if c.name == "Recreation"), None)
                            if rec_ch:
                                thread = await self.ctx.runtime.ward_room.create_thread(
                                    channel_id=rec_ch.id,
                                    author_id=self.ctx.agent_id,
                                    title=f"[Challenge] {self.ctx.callsign} challenges {target_callsign} to {game_type}!",
                                    body=f"{self.ctx.callsign} has challenged {target_callsign} to a game of {game_type}! Reply to accept.",
                                    author_callsign=self.ctx.callsign,
                                )
                                thread_id = thread.id if thread else ""
                        game_info = await rec_svc.create_game(
                            game_type=game_type,
                            challenger=self.ctx.callsign,
                            opponent=target_callsign,
                            thread_id=thread_id,
                        )
                        logger.info("BF-119: %s challenged %s to %s via DM (game %s)",
                                    self.ctx.callsign, target_callsign, game_type, game_info["game_id"])
                        # Register game engagement in working memory
                        try:
                            wm = getattr(self.ctx.agent, 'working_memory', None)
                            if wm:
                                from probos.cognitive.agent_working_memory import ActiveEngagement
                                wm.add_engagement(ActiveEngagement(
                                    engagement_type="game",
                                    engagement_id=game_info["game_id"],
                                    summary=f"Playing {game_type} against {target_callsign}",
                                    state={
                                        "game_type": game_type,
                                        "opponent": target_callsign,
                                    },
                                ))
                        except Exception:
                            logger.debug("BF-119: Working memory game engagement record failed", exc_info=True)
                    else:
                        logger.debug("BF-119: Target callsign %s not found", target_callsign)
                except Exception as e:
                    logger.warning("BF-119: DM game challenge failed for %s: %s", self.ctx.callsign, e)
                # AD-724: Strip [CHALLENGE] tag from Captain-visible text.
                if self.ctx.sanity_gate is not None:
                    self.ctx.response_text = self.ctx.sanity_gate.strip_challenge(self.ctx.response_text)
                else:
                    self.ctx.response_text = re.sub(r'\[CHALLENGE\s+@\w+\s+\w+\]', '', self.ctx.response_text).strip()

    # --- step 3: AD-572 move parse ---
    async def step_3_move_parse(self) -> None:
        """AD-572 (migrated to AD-724): Parse [MOVE pos] and execute. Verbatim move."""
        # AD-572 (migrated to AD-724): Parse [MOVE pos] and execute against RecreationService.
        if self.ctx.response_text and hasattr(self.ctx.runtime, 'recreation_service') and self.ctx.runtime.recreation_service:
            position = (
                self.ctx.sanity_gate.extract_move(self.ctx.response_text)
                if self.ctx.sanity_gate is not None
                else None
            )
            if position is not None:
                try:
                    rec_svc = self.ctx.runtime.recreation_service
                    game = rec_svc.get_game_by_player(self.ctx.callsign)
                    if game:
                        self.ctx.game_move_result = await rec_svc.make_move(
                            game_id=game["game_id"],
                            player=self.ctx.callsign,
                            move=position,
                        )
                        # Post board update to Ward Room thread (same as proactive path)
                        if self.ctx.runtime.ward_room and game.get("thread_id"):
                            try:
                                result_info = self.ctx.game_move_result.get("result")
                                if result_info:
                                    body = f"Game over! {'Winner: ' + result_info.get('winner', '') if result_info.get('winner') else 'Draw!'}"
                                else:
                                    board = rec_svc.render_board(game["game_id"])
                                    body = f"```\n{board}\n```\nNext: {self.ctx.game_move_result['state']['current_player']}"
                                await self.ctx.runtime.ward_room.create_post(
                                    thread_id=game["thread_id"],
                                    author_id=self.ctx.agent_id,
                                    body=body,
                                    author_callsign=self.ctx.callsign,
                                )
                            except Exception:
                                logger.debug("AD-572: Board update post failed", exc_info=True)
                except Exception as e:
                    logger.warning("AD-572: DM game move failed for %s: %s", self.ctx.callsign, e)

                # AD-724: Strip [MOVE] tag from Captain-visible text.
                if self.ctx.sanity_gate is not None:
                    self.ctx.response_text = self.ctx.sanity_gate.strip_move(self.ctx.response_text)
                else:
                    self.ctx.response_text = re.sub(r'\[MOVE\s+\S+\]', '', self.ctx.response_text).strip()

    # --- step 4: AD-728d self-image-awareness marker parse ---
    async def step_4_self_check_parse(self) -> None:
        """AD-728d: Parse [SELF_CHECK reason] markers, dispatch the first
        valid one to ``agent.check_own_render``, strip all occurrences.

        Tier-2 log-and-degrade. The dispatched coroutine is fire-and-forget
        but its task reference is held on ``ctx._self_check_task`` so the
        async runtime keeps it alive. Multiple markers in one reply: first
        dispatches, all are stripped, a WARNING is logged for the collapse.
        """
        if not self.ctx.response_text:
            return

        reasons: list[str] = []
        if self.ctx.sanity_gate is not None:
            reasons = self.ctx.sanity_gate.extract_self_check(self.ctx.response_text)

        if reasons:
            if len(reasons) > 1:
                logger.warning(
                    "AD-728d: agent %s emitted %d [SELF_CHECK] markers in one "
                    "reply; only first reason=%r dispatches, rest stripped",
                    self.ctx.agent_id, len(reasons), reasons[0],
                )
            first = reasons[0]
            try:
                self.ctx._self_check_task = asyncio.create_task(
                    self.ctx.agent.check_own_render(reason=first)
                )
            except Exception:
                logger.warning(
                    "AD-728d: failed to dispatch check_own_render for "
                    "agent=%s reason=%r",
                    self.ctx.agent_id, first, exc_info=True,
                )

        # Always strip ALL markers (well-formed + malformed) before
        # downstream steps see ctx.response_text.
        if self.ctx.sanity_gate is not None:
            self.ctx.response_text = self.ctx.sanity_gate.strip_self_check(
                self.ctx.response_text
            )
        else:
            self.ctx.response_text = re.sub(
                r"\[SELF_CHECK\b[^\]\n]*\]", "", self.ctx.response_text
            ).strip()

    # --- step 4b: BF-296 / AD-453 [DM @callsign]...[/DM] outbound parse ---
    async def step_4b_dm_outbound_parse(self) -> None:
        """BF-296: Parse [DM @callsign]...[/DM] blocks in the Captain-bound
        reply, dispatch each as a real DM to the named crew member, strip
        the markers from ``response_text`` before display.

        Reuses ``ProactiveLoop.extract_and_execute_dms`` (AD-453) — same
        tier-1/2/3 regex, same BF-163 per-pair cooldowns, same AD-614
        self-similarity gate. When the proactive loop is not yet wired
        (early-boot / test runtimes), honest-degrade by leaving the text
        untouched.

        Runs AFTER self_check_parse so any [SELF_CHECK] markers are
        stripped before the outbound DM body could reflect them, and
        BEFORE episodic_store so the recorded episode shows the cleaned
        Captain-visible text.
        """
        if not self.ctx.response_text:
            return
        if "[DM" not in self.ctx.response_text:
            return  # fast path: no marker present
        proactive = getattr(self.ctx.runtime, "proactive_loop", None)
        if proactive is None or not hasattr(proactive, "extract_and_execute_dms"):
            logger.debug(
                "BF-296: proactive_loop unavailable; leaving [DM] markers in "
                "reply for agent=%s",
                self.ctx.agent_id,
            )
            return
        try:
            cleaned, actions = await proactive.extract_and_execute_dms(
                self.ctx.agent, self.ctx.response_text,
            )
            self.ctx.response_text = cleaned
            if actions:
                logger.info(
                    "BF-296: dispatched %d outbound DM(s) from agent=%s "
                    "DM-reply",
                    len(actions), self.ctx.agent_id,
                )
        except Exception:
            logger.warning(
                "BF-296: [DM] extraction failed for agent=%s; leaving markers "
                "in reply (Captain will see them as fallback signal)",
                self.ctx.agent_id, exc_info=True,
            )

    # --- step 5: AD-430b HXI 1:1 episodic store ---
    async def step_5_episodic_store(self) -> None:
        """AD-430b: Store HXI 1:1 interaction as episodic memory. Verbatim move."""
        # AD-430b: Store HXI 1:1 interaction as episodic memory
        if hasattr(self.ctx.runtime, 'episodic_memory') and self.ctx.runtime.episodic_memory:
            try:
                import time as _time
                from probos.cognitive.episodic import resolve_sovereign_id
                from probos.types import AnchorFrame, Episode
                sovereign_id = resolve_sovereign_id(self.ctx.agent)
                episode = Episode(
                    user_input=f"[1:1 with {self.ctx.callsign or self.ctx.agent_id}] Captain: {self.ctx.req_message}",
                    timestamp=_time.time(),
                    agent_ids=[sovereign_id],
                    outcomes=[{
                        "intent": "direct_message",
                        "success": True,
                        "response": self.ctx.response_text[:500],
                        "session_type": "1:1",
                        "callsign": self.ctx.callsign,
                        "source": "hxi_profile",
                        "agent_type": self.ctx.agent.agent_type,
                        # AD-730: tag DM episodes that included an image so Counselor
                        # wellness and AD-722a divergence analysis can filter on it.
                        "has_image_attachment": self.ctx.has_image_attachment,
                        # AD-720d-1: per-attachment timing + partial-resolve metric.
                        "image_count": sum(
                            1 for r in self.ctx.per_attachment
                            if r["ok"] and (r.get("mime") or "").startswith("image/")
                        ) if self.ctx.has_image_attachment else 0,
                        "failed_image_count": sum(1 for r in self.ctx.per_attachment if not r["ok"]),
                        "per_attachment_timing": self.ctx.per_attachment,
                    }],
                    reflection=f"Captain had a 1:1 conversation with {self.ctx.callsign or self.ctx.agent_id} via HXI.",
                    source="direct",
                    anchors=AnchorFrame(
                        channel="dm",
                        trigger_type="direct_message",
                        trigger_agent="captain",
                        participants=["captain", self.ctx.callsign or self.ctx.agent_id],
                    ),
                )
                await self.ctx.runtime.episodic_memory.store(episode)
            except Exception:
                logger.debug("Failed to store HXI conversation episode", exc_info=True)

    # --- step 6: AD-573 working-memory record ---
    async def step_6_working_memory_record(self) -> None:
        """AD-573: Record DM conversation to agent's working memory. Verbatim move."""
        # AD-573: Record DM conversation to agent's working memory
        try:
            wm = getattr(self.ctx.agent, 'working_memory', None)
            if wm:
                captain_text = self.ctx.req_message[:100] if self.ctx.req_message else ""
                wm.record_conversation(
                    f"Captain DM: '{captain_text}' → responded",
                    partner="Captain",
                    source="dm",
                )
        except Exception:
            logger.debug("AD-573: Working memory DM record failed", exc_info=True)

    # --- step 7: AD-722a divergence check ---
    async def step_7_divergence_check(self) -> None:
        """AD-722a: intent-vs-presentation divergence detection. Verbatim move."""
        # AD-722a: intent-vs-presentation divergence detection.
        # Tier-2 wrapped — never blocks a reply. Default OFF
        # (avatar_telemetry.divergence_detection). When ON, the LLM was
        # instructed via _build_intent_self_tag_instruction to append a
        # self-tag at end-of-reply. Parse + strip BEFORE the response leaves
        # the handler; never leak the tag to the Captain. Trust + Hebbian
        # wiring lives inside apply_divergence_check (single call site).
        try:
            _t_cfg = getattr(self.ctx.runtime.config, "avatar_telemetry", None)
            if _t_cfg is not None and getattr(_t_cfg, "divergence_detection", False):
                from probos.avatars.divergence_detector import apply_divergence_check
                self.ctx.response_text = apply_divergence_check(
                    runtime=self.ctx.runtime,
                    agent_id=self.ctx.agent_id,
                    agent=self.ctx.agent,
                    response_text=self.ctx.response_text,
                    t_cfg=_t_cfg,
                )
        except Exception:
            logger.debug(
                "AD-722a: divergence detector failed for agent=%s",
                self.ctx.agent_id, exc_info=True,
            )

    # --- step 8: mark_reply_emitted + AD-722f exit_dm + AD-722b wake ---
    async def step_8_mark_emitted(self) -> None:
        """AD-722: stamp last-reply emission + AD-722f exit_dm + AD-722b wake. Verbatim move."""
        # AD-722: stamp the last-reply emission timestamp. Single source of truth.
        if hasattr(self.ctx.agent, 'mark_reply_emitted'):
            self.ctx.agent.mark_reply_emitted()

        # AD-722f: matched exit for the enter_dm at the top of agent_chat.
        # Spurious-exit clamp in the state machine handles the (rare)
        # exception-path case where enter fired but exit didn't.
        if self.ctx.sampling_state is not None:
            self.ctx.sampling_state.exit_dm(self.ctx.agent_id)
        # AD-722b: wake WS publish loop — DM-exit is a state change
        # (working_state goes from 'responding' back to 'idle').
        if self.ctx.avatar_event_bus is not None:
            self.ctx.avatar_event_bus.notify(self.ctx.agent_id)

    # --- step 9: AD-738e-1 emotion resolution ---
    async def step_9_emotion_resolve(self) -> None:
        """AD-738e-1: expose parsed + v1-resolved emotion for TTS. Verbatim move."""
        # AD-738e-1: expose the parsed + v1-resolved emotion so the browser
        # can pass it to /api/avatars/tts for per-emotion prosody. Tier-2
        # log-and-degrade: missing divergence result or unresolvable name
        # falls through to ``None`` (browser then omits the field; server
        # applies default prosody). Uses the public ``resolve_emotion_to_v1``
        # alias (AD-738e-1 Section 5b) — no cross-module private access.
        # AD-726: emotion lives on ctx; pre-initialized in DmReplyContext default.
        try:
            _dr = getattr(self.ctx.runtime, "divergence_results", None)
            if _dr is not None:
                _result = _dr.get(self.ctx.agent_id)
                if _result is not None:
                    _raw = getattr(_result, "intent_emotion", None)
                    if isinstance(_raw, str) and _raw:
                        from probos.avatars.divergence_detector import (
                            resolve_emotion_to_v1,
                        )
                        _store = getattr(self.ctx.runtime, "profile_store", None)
                        _custom = None
                        if _store is not None and hasattr(_store, "get"):
                            try:
                                _crew = _store.get(self.ctx.agent_id)
                                _custom = (
                                    getattr(_crew, "custom_emotions", None)
                                    if _crew else None
                                )
                            except Exception:
                                _custom = None
                        self.ctx.emotion = resolve_emotion_to_v1(_raw, _custom) or _raw
        except Exception:
            logger.debug(
                "AD-738e-1: emotion resolution failed for agent=%s",
                self.ctx.agent_id, exc_info=True,
            )

    def build_response(self) -> dict[str, Any]:
        """Return the final response dict — verbatim move of routers/agents.py:1553..1559."""
        response: dict[str, Any] = {
            "response": self.ctx.response_text,
            "callsign": self.ctx.callsign,
            "agentId": self.ctx.agent_id,
            "emotion": self.ctx.emotion,
        }
        if self.ctx.game_move_result:
            response["gameMoveExecuted"] = True
            response["gameStatus"] = self.ctx.game_move_result.get("state", {}).get("status", "")
        return response
