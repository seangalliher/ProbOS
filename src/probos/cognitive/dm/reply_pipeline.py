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
import hashlib
import json
import logging
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from probos.cognitive.dm.write_ledger import (  # AD-1285 (#1087)
    WRITE_CHANNEL_ARTIFACT,
    WRITE_CHANNEL_NOTEBOOK,
    ClaimVerdict,
    WriteLedger,
    assess_write_claim,
    disclosure_for,
)
from probos.dm_reply import DmReply  # AD-1248
from probos.hooks.bus import HookEvent

logger = logging.getLogger(__name__)


#: AD-1285 (#1087): notebook action types that mean the entry is durably
#: present. ``notebook_write`` is an actual write; ``notebook_suppressed`` is
#: AD-550/AD-911 dedup against an existing highly-similar entry, so the note is
#: there and a save claim about it is true. Anything else counts as no write.
_NOTEBOOK_PRESENT_ACTIONS = frozenset({"notebook_write", "notebook_suppressed"})


# AD-869: read-only mesh intents that Yeo may resolve inline in a single
# synchronous chat turn (Tier-2 "do-and-report"). Each maps to the registry
# pool that serves it. The allowlist is the safety boundary: writes and
# ``http_fetch`` are deliberately EXCLUDED. Destructive / consensus-gated
# intents cannot resolve in one turn (consensus needs a quorum round-trip),
# so a ~5s synchronous read is structurally incapable of mutation. Anything
# heavier belongs on the Tier-3 [CREATE_TASK] async path (AD-845).
_MESH_READ_INTENT_POOLS: dict[str, str] = {
    "list_directory": "directory",
    "read_file": "filesystem",
    "stat_file": "filesystem",
    "search_files": "search",
    "search_content": "code_search",
    "web_search": "web_search",
    "read_page": "page_reader",
}
# Single-turn latency ceiling for local-IO reads (filesystem / directory /
# search). These resolve in milliseconds, so a read that cannot finish in
# this window honest-degrades to a brief note rather than blocking the reply.
_MESH_READ_TTL_SECONDS = 5.0
# BF-609: network + LLM-bound reads (web_search, read_page) need a larger
# ceiling. WebSearchAgent/PageReaderAgent mesh-fetch through the rate-limited
# ``http_fetch`` path (>=2s per-domain wait + internet round-trip) and then,
# because both carry ``requires_reflect=True``, run an LLM call to synthesize
# the result — realistically 8-20s end to end. The flat 5s ceiling timed
# these out every time ("Agent did not respond in time."). This is still a
# read-only, non-consensus intent, so the longer wait does not weaken the
# Tier-2 safety boundary (the allowlist + "consensus can't resolve in one
# turn" is what enforces it, not the latency).
_MESH_READ_NETWORK_TTL_SECONDS = 25.0
# Per-intent ceiling override. Intents absent from this map use the default
# local-IO ceiling (``_MESH_READ_TTL_SECONDS``).
_MESH_READ_TTL_BY_INTENT: dict[str, float] = {
    "web_search": _MESH_READ_NETWORK_TTL_SECONDS,
    "read_page": _MESH_READ_NETWORK_TTL_SECONDS,
}
# BF-629: reads whose raw result is a list of links / a page dump that the
# ORIGINATING agent should reason over in its own voice (search -> reason ->
# answer), rather than pasting verbatim. Exactly the ``requires_reflect`` mesh
# reads (web_search / read_page) — local-IO reads (read_file, list_directory,
# stat_file, search_files, search_content) ARE the answer as-is and skip
# synthesis. Mirrors the explicit-per-intent style of the maps above.
_MESH_READ_SYNTHESIZE_INTENTS: frozenset[str] = frozenset({"web_search", "read_page"})
# Cap on how much of a read result is inlined into the chat reply.
_MESH_READ_RENDER_MAX_CHARS = 1500


@dataclass
class DmReplyContext:
    """Mutable context threaded through every pipeline step.

    NOT frozen by design: ``response_text`` and ``emotion`` are mutated
    in place by the sanity gate, challenge/move strip, divergence check,
    and emotion-resolution steps.

    AD-1248: ``reply`` is now the canonical value and ``response_text`` is a
    PROPERTY over ``reply.body``. Reading returns the body; assigning rewrites
    the body and preserves the attachments. That is why all 34 existing
    ``ctx.response_text = ...`` lines are untouched and yet every one of them
    now carries a tool-failure disclosure through to the egress sink.
    """

    runtime: Any
    agent: Any
    agent_id: str
    callsign: str | None
    req_message: str
    reply: DmReply
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
    # AD-791a: chat-thread provenance. Passed by the router (``routers/
    # agents.py:2089``) at construction time from ``thread.id``. Threaded
    # into both AnchorFrame sites below (L658 action-dispatch episode,
    # L757 DM episode) so any episode written by this pipeline carries
    # its chat-thread tag. Defaults to ``""`` so the 7+ existing
    # ``DmReplyContext(...)`` constructions in tests continue to pass
    # without modification.
    chat_thread_id: str = ""
    # AD-728d: task reference for the fire-and-forget check_own_render
    # dispatch. Held on ctx so the asyncio runtime does not GC the
    # coroutine mid-flight. Tier-2: read by tests, not by other steps.
    _self_check_task: "asyncio.Task[None] | None" = None
    # AD-730-3: SHA-256 refs of images generated by the agent for this
    # reply. Surfaced on the response payload as ``attachment_ids``.
    # AD-731 invariant: refs only — bytes live in AttachmentStore.
    generated_attachment_ids: list[str] = field(default_factory=list)
    # AD-1285 (#1087): what this turn actually wrote. Populated by the steps
    # that own a durable-write channel; read by ``step_4m_write_claim_guard``.
    # Defaulted per the AD-791a convention above, so every existing
    # ``DmReplyContext(...)`` construction site is untouched.
    write_ledger: WriteLedger = field(default_factory=WriteLedger)
    # NOTE: ``sanity_result`` is intentionally NOT a ctx field — it is
    # produced and consumed entirely within step_1_sanity_gate_retry.

    @property
    def response_text(self) -> str:
        """The reply body. Assigning rewrites it and keeps the attachments."""
        return self.reply.body

    @response_text.setter
    def response_text(self, value: str) -> None:
        self.reply = self.reply.with_body(value)


class DmReplyPipeline:
    """Post-LLM cleanup chain for the DM one-shot path.

    BF-796: the count lives in :meth:`_full_steps` and its guard test, not in
    prose here -- this docstring said "nine-step" across six insertions.
    """

    def __init__(self, ctx: DmReplyContext) -> None:
        self.ctx = ctx

    async def run(self) -> None:
        """Execute every step in order. Top-level guard preserves the
        Tier-2 contract: a runaway step is logged but never blocks the
        reply. Per-step guards inside the methods are preserved verbatim
        from the prior inline code; the top-level guard is belt-and-braces.
        """
        await self._run_steps(self._full_steps())

    def _full_steps(self) -> tuple[Callable, ...]:
        """AD-933: the full DM one-shot chain in load-bearing order, the single
        source of truth executed by :meth:`run`. **21 steps** (BF-796: this said
        18 while the tuple returned 20 -- a reader trusts this line when judging
        whether an insertion is in scope, so it is now guarded by a test rather
        than maintained by hand) after AD-934 inserted
        ``step_4j_deliberate_parse`` between ``step_4g_create_task_parse`` and
        ``step_5_episodic_store`` (so the deep-tier re-rolled reply is what gets
        stored / divergence-checked / emitted), and AD-1285 inserted
        ``step_4m_write_claim_guard`` between ``step_4j_deliberate_parse`` and
        ``step_5_episodic_store`` (after 4j so the guard reads the text the
        Captain will actually see, before 5 so the stored episode and the
        divergence check carry the corrected text). Ordering is invariant
        (sanity gate before challenge/move parsers, self-check before episodic
        store, deliberate re-roll before episodic store, write-claim guard after
        the re-roll, divergence before ``mark_reply_emitted``, emotion after
        divergence) and MUST stay byte-identical apart from those two
        insertions."""
        return (
            self.step_1_sanity_gate_retry,
            self.step_2_challenge_parse,
            self.step_3_move_parse,
            self.step_4_self_check_parse,
            self.step_4c_image_gen_parse,  # AD-730-3
            self.step_4d_follow_up_parse,  # AD-743
            self.step_4e_action_dispatch,  # AD-745
            self.step_4b_dm_outbound_parse,
            self.step_4i_notebook_parse,  # AD-911
            self.step_4h_mesh_read_parse,  # AD-869
            self.step_4f_extract_artifacts,  # AD-797 (Wave 197)
            self.step_4k_extract_a2ui,  # AD-811a (default-OFF; group via AD-811c)
            self.step_4g_create_task_parse,  # AD-845
            self.step_4l_extract_todos,  # AD-1081 room-Todo validation loop
            self.step_4j_deliberate_parse,  # AD-934
            self.step_4m_write_claim_guard,  # AD-1285 (#1087)
            self.step_5_episodic_store,
            self.step_6_working_memory_record,
            self.step_7_divergence_check,
            self.step_8_mark_emitted,
            self.step_9_emotion_resolve,
        )

    def _escalation_steps(self) -> tuple[Callable, ...]:
        """AD-933: the channel-agnostic escalation subset reused by the
        group-chat fan-out (``routers/thread_fanout.py:group_chat_fanout``).
        Each step is a strict no-op for any reply lacking its marker, and the
        markers are emitted only by specifically-taught agents, so the subset
        is inherently bounded and safe outside the 1:1 path. Relative order is
        preserved from :meth:`_full_steps` (4c -> 4e -> 4i -> 4h -> 4f -> 4k ->
        4g -> 4j).

        Included: ``step_4c_image_gen_parse`` (AD-730-3 ``[GEN_IMAGE]``, added
        AD-933b), ``step_4e_action_dispatch`` (AD-745 ``[ACTION]``),
        ``step_4i_notebook_parse`` (AD-911), ``step_4h_mesh_read_parse``
        (AD-869 read-only mesh), ``step_4f_extract_artifacts`` (AD-797),
        ``step_4k_extract_a2ui`` (AD-811a/c — extracts ``[A2UI]`` widget tags
        into artifacts + inline stubs; channel-agnostic, reads
        ``chat_thread_id`` / ``a2ui_enabled``; AD-811c activates it on the
        group fan-out path), ``step_4g_create_task_parse`` (AD-845
        ``[CREATE_TASK]``), ``step_4j_deliberate_parse`` (AD-934
        ``[THINK]``/``[DELIBERATE]`` deep-tier re-roll, flag-gated, appended
        last).

        Excluded (1:1 semantics / mislabel risk): sanity-gate retry (1),
        games (2/3), self-check (4), follow-up (4d), outbound-DM (4b),
        episodic store (5 — hardcodes ``session_type:"1:1"``, so firing it on a
        multi-agent group reply writes mislabeled episodes), working memory
        (6 — records ``"Captain DM"``), divergence (7), mark-emitted/avatar
        (8), emotion (9). Forward marker: AD-933b-2 (``step_4d_follow_up``,
        whose ``conversation_pacing_scheduler`` re-injects a synthesized
        user-turn — an ambiguous target in a multi-agent room). Forward marker:
        AD-1285 ``step_4m_write_claim_guard`` is 1:1-only pending group-sink
        verification (#1087) — the same write-claim hazard exists on the group
        fan-out, but its disclosure sink is unverified."""
        return (
            self.step_4c_image_gen_parse,  # AD-933b (AD-730-3 [GEN_IMAGE])
            self.step_4e_action_dispatch,
            self.step_4i_notebook_parse,
            self.step_4h_mesh_read_parse,
            self.step_4f_extract_artifacts,
            self.step_4k_extract_a2ui,  # AD-811c (group A2UI producer; #735)
            self.step_4g_create_task_parse,
            self.step_4l_extract_todos,  # AD-1081 room-Todo validation loop
            self.step_4j_deliberate_parse,  # AD-934
        )

    async def _run_steps(self, steps: tuple[Callable, ...]) -> None:
        """AD-933: run an ordered tuple of pipeline steps under the verbatim
        AD-726 per-step Tier-2 guard — a runaway step is logged but never
        blocks the reply. Shared by :meth:`run` (full chain) and
        :meth:`run_escalation_only` (escalation subset)."""
        for step in steps:
            try:
                await step()
            except Exception:
                logger.warning(
                    "AD-726: pipeline step %s raised for agent=%s; continuing",
                    step.__name__, self.ctx.agent_id, exc_info=True,
                )

    async def run_escalation_only(self) -> None:
        """AD-933: run ONLY the channel-agnostic escalation subset
        (:meth:`_escalation_steps`) under the same per-step Tier-2 guard as
        :meth:`run`. Reused by the group-chat fan-out so a group reply can
        fire the escalation ladder ([ACTION] / notebook / mesh-read /
        artifacts / [CREATE_TASK]) without the 1:1-scoped steps (episodic,
        working memory, divergence, emotion, games, avatar) that would
        mislabel a multi-agent turn. See :meth:`_escalation_steps` for the
        full include/exclude rationale."""
        await self._run_steps(self._escalation_steps())

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
                        # AD-1248 / BF-800: a retry is a FRESH ANSWER to the same
                        # question, so DD-2 makes it ``replaced_by`` -- not the
                        # ``with_body`` the ``response_text`` property performs.
                        # Assigning through the property preserved the FIRST
                        # attempt's tool failures onto a reply that never made
                        # those calls, and dropped the retry's own. Measured
                        # wrong in both directions. Only on a valid result: the
                        # empty and error branches below still retain the
                        # previous reply, or a failed retry would erase a good
                        # disclosure.
                        self.ctx.reply = self.ctx.reply.replaced_by(
                            DmReply.from_intent_result(retry_resp).with_body(
                                retry_result.cleaned_text
                            )
                        )
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

    # --- step 4c: AD-730-3 [GEN_IMAGE prompt] parse + dispatch ---
    async def step_4c_image_gen_parse(self) -> None:
        """AD-730-3: parse ``[GEN_IMAGE prompt]`` markers, dispatch
        image generation, and attach SHA refs to the reply.

        Strips the marker before downstream steps see the text. First
        marker dispatched; additional markers stripped with a single
        WARNING. Honest-degrade when the tier is disabled/unconfigured:
        marker stripped, no image attached, and the operator-facing
        honest-degrade message appended to the reply so the Captain
        knows why no image came through.

        Tier-2: every failure path logs + degrades. Never raises.
        """
        gate = self.ctx.sanity_gate
        if gate is None or not self.ctx.response_text:
            return
        runtime = self.ctx.runtime
        cfg = getattr(runtime, "config", None)
        av_cfg = getattr(cfg, "avatars", None)
        max_chars = int(getattr(av_cfg, "image_gen_max_prompt_chars", 512))

        try:
            prompts = gate.extract_gen_image(
                self.ctx.response_text, max_chars=max_chars
            )
        except Exception:
            logger.warning(
                "AD-730-3: extract_gen_image raised for agent=%s",
                self.ctx.agent_id, exc_info=True,
            )
            prompts = []

        # Always strip BEFORE returning so markers don't leak even on
        # disabled/unconfigured tiers.
        try:
            self.ctx.response_text = gate.strip_gen_image(self.ctx.response_text)
        except Exception:
            logger.warning(
                "AD-730-3: strip_gen_image raised for agent=%s",
                self.ctx.agent_id, exc_info=True,
            )

        if not prompts:
            return
        if len(prompts) > 1:
            logger.warning(
                "AD-730-3: agent=%s emitted %d GEN_IMAGE markers in one "
                "reply; dispatching first only",
                self.ctx.agent_id, len(prompts),
            )

        # Sync-await dispatch so the SHA can be attached to THIS reply's
        # response payload. ``dispatch_image_gen`` enforces its own
        # timeout via the image_gen tier config.
        from probos.cognitive.image_gen_dispatch import dispatch_image_gen

        result = await dispatch_image_gen(
            runtime, agent_id=self.ctx.agent_id, prompt=prompts[0],
        )
        if result.get("ok"):
            self.ctx.generated_attachment_ids.append(result["attachment_id"])
        else:
            # Honest-degrade: append message so the Captain sees why no
            # image came through.
            message = str(result.get("message") or "")
            if message:
                self.ctx.response_text = (
                    f"{self.ctx.response_text}\n\n{message}".strip()
                )

    # --- step 4d: AD-743 [FOLLOW_UP delay reason] parse + schedule ---
    async def step_4d_follow_up_parse(self) -> None:
        """AD-743: parse ``[FOLLOW_UP delay reason]`` markers, schedule
        a synthesized user-turn after ``delay`` seconds via the runtime's
        ``conversation_pacing_scheduler``, and strip the marker before
        downstream steps see ``response_text``.

        First well-formed marker schedules; additional markers stripped
        with a single WARNING. Honest-degrade when the scheduler is
        absent (``pacing_enabled=False``): marker silently stripped, no
        follow-up scheduled, no Captain-visible bleed.

        Tier-2: every failure path logs + degrades. Never raises.
        """
        gate = self.ctx.sanity_gate
        if gate is None or not self.ctx.response_text:
            return

        try:
            followup = gate.extract_followup(self.ctx.response_text)
        except Exception:
            logger.warning(
                "AD-743: extract_followup raised for agent=%s",
                self.ctx.agent_id, exc_info=True,
            )
            followup = None

        # Strip BEFORE returning so markers don't leak even when the
        # scheduler is disabled.
        try:
            self.ctx.response_text = gate.strip_followup(self.ctx.response_text)
        except Exception:
            logger.warning(
                "AD-743: strip_followup raised for agent=%s",
                self.ctx.agent_id, exc_info=True,
            )

        if followup is None:
            return

        delay, reason = followup
        scheduler = getattr(
            self.ctx.runtime, "conversation_pacing_scheduler", None
        )
        if scheduler is None:
            logger.debug(
                "AD-743: pacing scheduler not wired; marker stripped for "
                "agent=%s reason=%r (pacing disabled)",
                self.ctx.agent_id, reason,
            )
            return

        try:
            scheduler.schedule_followup(
                agent_id=self.ctx.agent_id,
                delay_seconds=delay,
                reason=reason,
            )
        except Exception:
            logger.warning(
                "AD-743: schedule_followup raised for agent=%s reason=%r",
                self.ctx.agent_id, reason, exc_info=True,
            )

    # --- step 4e: AD-745 [ACTION:] dispatch to BrowserTool ---
    async def step_4e_action_dispatch(self) -> None:
        """AD-745: parse ``[ACTION: <json>]`` markers, classify via
        existing AD-706e ``classify_action``, queue with the runtime's
        action_dispatcher, and dispatch tier-1 inline. Tier-2/3 wait
        for Captain ACK / confirm. Markers are stripped from the
        Captain-visible reply regardless of dispatch outcome.

        Tier-2 honest-degrade: every failure mode (missing dispatcher,
        missing BrowserTool, classifier raise, malformed envelope)
        degrades to "drop the action, keep the reply." NEVER raises.

        Wave 178 GATE 1 ruling: per-action Captain ACK is canonical;
        AD-745-2 forward marker tracks autopilot mode (opt-in quorum
        substitution per https://docs.github.com/en/copilot/concepts/agents/copilot-cli/autopilot).
        """
        if not self.ctx.response_text:
            return

        cfg = getattr(self.ctx.runtime, "config", None)
        browser_cfg = getattr(cfg, "browser_tool", None) if cfg else None
        if browser_cfg is None or not getattr(
            browser_cfg, "action_dispatch_enabled", False,
        ):
            return  # master switch off; reply unchanged.

        from probos.cognitive.dm.action_parser import (
            parse_action_envelopes,
            strip_action_markers,
        )
        from probos.cognitive.dm.action_dispatcher import (
            ActionStatus,
            DispatchedAction,
            make_action_id,
            url_matches_destructive_pattern,
        )

        envelopes = parse_action_envelopes(self.ctx.response_text)
        if not envelopes:
            return

        # Enforce per-DM-turn cap; extra envelopes dropped + logged.
        max_per_turn = int(getattr(
            browser_cfg, "action_dispatch_max_per_dm_turn", 1,
        ))
        if len(envelopes) > max_per_turn:
            logger.warning(
                "AD-745: %d action envelopes parsed for agent=%s; cap=%d "
                "(extras dropped — AD-745-6 forward marker covers multi-step)",
                len(envelopes), self.ctx.agent_id, max_per_turn,
            )
            envelopes = envelopes[:max_per_turn]

        dispatcher = getattr(self.ctx.runtime, "action_dispatcher", None)
        if dispatcher is None:
            logger.warning(
                "AD-745: runtime.action_dispatcher missing; stripping markers "
                "and degrading for agent=%s",
                self.ctx.agent_id,
            )
            self.ctx.response_text = strip_action_markers(self.ctx.response_text)
            return

        browser_tool = getattr(self.ctx.runtime, "browser_tool", None)
        captain_id = "captain"
        dm_turn_id = str(self.ctx.params.get("dm_turn_id") or int(time.time() * 1000))

        page_url: str | None = None
        session = None
        if browser_tool is not None:
            try:
                # Best-effort: pick the agent's most-recent session by id.
                session = browser_tool.get_session(self.ctx.agent_id)
                if session is not None:
                    page_url = getattr(session, "last_url", None)
            except Exception:
                logger.warning(
                    "AD-745: get_session raised for agent=%s; tier-3 fall-back "
                    "until classifier-known URL is available",
                    self.ctx.agent_id, exc_info=True,
                )

        # Classifier (AD-706e) + destructive-pattern override + budget cap.
        try:
            from probos.tools.browser.actions import classify_action
        except Exception:
            classify_action = None  # type: ignore[assignment]

        destructive_patterns: list[str] = list(getattr(
            browser_cfg, "destructive_url_patterns", [],
        ))
        consec_cap = int(getattr(
            browser_cfg, "action_dispatch_max_consecutive_autonomous", 5,
        ))

        for seq, envelope in enumerate(envelopes):
            base_tier = 2
            if classify_action is not None and session is not None:
                try:
                    base_tier = classify_action(session, envelope.verb, envelope.args)
                except Exception:
                    logger.warning(
                        "AD-745: classify_action raised for verb=%r agent=%s; "
                        "defaulting to tier-2",
                        envelope.verb, self.ctx.agent_id, exc_info=True,
                    )
                    base_tier = 2

            destructive_match = url_matches_destructive_pattern(
                page_url, destructive_patterns,
            )
            tier = base_tier
            if destructive_match:
                tier = 3
            elif dispatcher.consecutive_autonomous(
                captain_id, self.ctx.agent_id,
            ) >= consec_cap:
                tier = 3
                logger.info(
                    "AD-745: trust-budget cap reached (%d) for agent=%s; "
                    "forcing tier-3 Captain confirm",
                    consec_cap, self.ctx.agent_id,
                )

            action_id = make_action_id(
                captain_id, self.ctx.agent_id, dm_turn_id, seq,
            )
            initial_status = ActionStatus.PROPOSED
            if tier == 1:
                initial_status = ActionStatus.EXECUTED
            elif tier == 2:
                initial_status = ActionStatus.ACK_PENDING
            else:
                initial_status = ActionStatus.CONFIRM_PENDING

            action = DispatchedAction(
                action_id=action_id,
                agent_id=self.ctx.agent_id,
                captain_id=captain_id,
                thread_id=str(self.ctx.params.get("thread_id") or ""),
                verb=envelope.verb,
                args=dict(envelope.args),
                raw_intent=envelope.raw_intent,
                tier=tier,
                status=initial_status,
                proposed_at=time.time(),
                page_url=page_url,
                destructive_pattern_match=destructive_match,
            )
            dispatcher.register(action)

            if tier == 1 and browser_tool is not None:
                # Inline tier-1 dispatch. Tier-1 verbs are observation-only.
                try:
                    params = {"action": envelope.verb, **envelope.args}
                    if session is not None:
                        params["session_id"] = session.session_id
                    result = await browser_tool.invoke(
                        params, context={"agent_id": self.ctx.agent_id},
                    )
                    dispatcher.mark_executed(
                        action_id, result=getattr(result, "output", None),
                    )
                except Exception as ex:
                    dispatcher.mark_failed(action_id, error=str(ex))
                    logger.warning(
                        "AD-745: tier-1 dispatch failed verb=%r agent=%s: %s",
                        envelope.verb, self.ctx.agent_id, ex, exc_info=True,
                    )
            # Tier-2 / tier-3 stay queued — endpoint /ack or /abort
            # closes them. Episode anchor written by mark_executed path
            # consumer (forward marker AD-745-7 SQLite covers durability).

            # AD-541b: episode anchor for every PROPOSED/EXECUTED action.
            try:
                from probos.types import AnchorFrame, Episode
                episodic = getattr(self.ctx.runtime, "episodic_memory", None)
                if episodic is not None:
                    args_hash = hashlib.sha256(
                        json.dumps(envelope.args, sort_keys=True).encode(),
                    ).hexdigest()
                    ep = Episode(
                        timestamp=time.time(),
                        user_input=self.ctx.message_text or "",
                        outcomes=[{
                            "intent": "agent_action_executed",
                            "verb": envelope.verb,
                            "args_hash": args_hash,
                            "before_frame_ref": action.before_frame_ref,
                            "after_frame_ref": action.after_frame_ref,
                            "result": action.result,
                            "tier_classified": tier,
                        }],
                        reflection=(
                            f"{self.ctx.agent_id} proposed {envelope.verb} "
                            f"({envelope.raw_intent or 'no intent given'})"
                        ),
                        source="action_dispatch",
                        importance=7,
                        anchors=AnchorFrame(
                            channel="action",
                            trigger_type="agent_action_executed",
                            trigger_agent=self.ctx.agent_id,
                            chat_thread_id=self.ctx.chat_thread_id,  # AD-791a
                        ),
                    )
                    await episodic.store(ep)
            except Exception:
                logger.warning(
                    "AD-745: episode-anchor write failed agent=%s verb=%r",
                    self.ctx.agent_id, envelope.verb, exc_info=True,
                )

        # Strip ALL markers (even malformed ones) so the Captain-visible
        # reply never leaks JSON envelopes.
        self.ctx.response_text = strip_action_markers(self.ctx.response_text)

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

    # --- step 4i: AD-911 notebook persistence (Yeoman record-keeping) ---
    async def step_4i_notebook_parse(self) -> None:
        """AD-911 / AD-912: Persist ``[NOTEBOOK slug]...[/NOTEBOOK]`` blocks an
        agent emits when the Captain asks it to save a note in 1:1 chat.

        AD-911 added this for the Yeoman; AD-912 generalized it to any crew
        agent — notebooks are a universal agent capability on the proactive /
        Ward-Room path, and this brings the 1:1 path to parity. Reuses
        ``ProactiveLoop.extract_and_execute_notebooks``, which writes to the
        agent's notebook in the records store (AD-550 dedup, callsign-keyed)
        and strips the markers from the Captain-visible reply. Runs after the
        [DM] outbound parse and before episodic store so the recorded episode
        shows the cleaned text.

        Tier-2 honest-degrade: when the proactive loop is not wired (or a
        write fails), nothing is persisted. A final safety-net unwrap strips
        any markers that survived (no store, write failure) so the Captain
        never sees a raw block. NEVER raises.
        """
        if not self.ctx.response_text:
            return
        if "[NOTEBOOK" not in self.ctx.response_text:
            return  # fast path: no marker present

        proactive = getattr(self.ctx.runtime, "proactive_loop", None)
        if proactive is not None and hasattr(
            proactive, "extract_and_execute_notebooks"
        ):
            # AD-1285 residual: no channel exists here, which is a different
            # fact from "a channel ran and wrote nothing", so the ledger stays
            # untouched on the else. On a ship advertising notebooks with
            # ``proactive_loop`` unwired every marker is a phantom save and
            # nothing flags it -- a deployment defect for a startup check, not
            # a per-reply disclosure.
            try:
                cleaned, actions = await proactive.extract_and_execute_notebooks(
                    self.ctx.agent, self.ctx.response_text,
                )
                self.ctx.response_text = cleaned
                # AD-1285 (#1087): the channel ran, and ``actions`` is the only
                # in-process evidence of whether it wrote. It was previously
                # logged and dropped, which is why a marker whose write failed
                # produced a reply indistinguishable from a successful one.
                #
                # Match on action TYPE rather than list truthiness. The producer
                # emits exactly two kinds (``proactive.py`` 3128/4178 write,
                # 3019/3088/4163 suppress) and BOTH mean the note is durably
                # present: a suppression is AD-550/AD-911 dedup against an
                # existing highly-similar entry, so "I saved it" stays true and
                # flagging it would be a false positive. Truthiness happened to
                # agree today; it would silently count any future non-write
                # action as a write.
                self.ctx.write_ledger = self.ctx.write_ledger.consulted_with(
                    WRITE_CHANNEL_NOTEBOOK,
                    wrote=any(
                        isinstance(action, dict)
                        and action.get("type") in _NOTEBOOK_PRESENT_ACTIONS
                        for action in actions
                    ),
                )
                if actions:
                    logger.info(
                        "AD-912: persisted %d notebook action(s) from DM "
                        "reply for agent=%s",
                        len(actions), self.ctx.agent_id,
                    )
            except Exception:
                # AD-1285: the write raised. Consulted, wrote nothing.
                self.ctx.write_ledger = self.ctx.write_ledger.consulted_with(
                    WRITE_CHANNEL_NOTEBOOK, wrote=False,
                )
                logger.warning(
                    "AD-911: notebook extraction failed for agent=%s; will "
                    "unwrap stray markers",
                    self.ctx.agent_id, exc_info=True,
                )

        # Safety net: strip any markers that survived (no store wired, a
        # write failure, or the proactive loop unavailable) so the Captain
        # never sees a raw notebook block.
        if "[NOTEBOOK" in self.ctx.response_text:
            self.ctx.response_text = re.sub(
                r'\[NOTEBOOK\s+[\w-]+\](.*?)\[/NOTEBOOK\]',
                r'\1',
                self.ctx.response_text,
                flags=re.DOTALL,
            ).strip()

    # --- step 4h: AD-869 synchronous mesh-read (Tier-2 do-and-report) ---
    async def step_4h_mesh_read_parse(self) -> None:
        """AD-869: parse a ``[MESH <intent> key=value ...]`` tag, run ONE
        read-only intent synchronously via the mesh (~5s ceiling), render
        the result inline, and strip the tag.

        This is Yeo's Tier-2 default: a lightweight lookup the Captain wants
        answered *this turn* without spinning up a tracked task. Only the
        read-only intents in :data:`_MESH_READ_INTENT_POOLS` are ever
        executed — a non-allowlisted intent is stripped and shipped, never
        run. Resolution is a single targeted ``IntentBus.send`` (NOT a
        broadcast: broadcasting would fan out to every pool subscriber).

        Tier-2 honest-degrade: a missing sanity gate, missing intent bus, no
        capable agent, a send failure, or a timeout logs a warning, strips
        the tag, appends a brief honest note, and ships the reply. NEVER
        raises (the top-level ``run()`` guard is belt-and-braces).
        """
        if not self.ctx.response_text or self.ctx.sanity_gate is None:
            return
        gate = self.ctx.sanity_gate
        parsed = gate.extract_mesh_read(self.ctx.response_text)
        if parsed is None:
            return
        intent_name, params = parsed

        pool_name = _MESH_READ_INTENT_POOLS.get(intent_name)
        if pool_name is None:
            # Non-allowlisted intent: strip the tag, ship the reply, do NOT
            # execute. The allowlist is the Tier-2 safety boundary.
            logger.warning(
                "AD-869: [MESH %s] from agent=%s is not a read-only "
                "allowlisted intent; stripping tag, no execution",
                intent_name, self.ctx.agent_id,
            )
            self.ctx.response_text = gate.strip_mesh_read(self.ctx.response_text)
            return

        # AD-1007/AD-1012: per-agent capability gate. A Captain restriction on
        # this intent for the ORIGINATING agent blocks the conversational [MESH]
        # request — an explicit agent-level disable wins over the role/ship
        # default (agent-precedence). When the AD-1004 lifecycle-hook bus is
        # wired (config.hooks.enabled), the gate runs as a ``PreDispatch`` hook
        # so Capability-Pack (#948) + consensus handlers gate at the same point
        # (most-restrictive-wins); otherwise the inline IntentGrantStore check
        # is authoritative (byte-identical default). Honest-degrade: no
        # bus/store -> no gating; only an explicit ``restricted``/``deny`` blocks.
        blocked = False
        hook_bus = getattr(self.ctx.runtime, "hook_bus", None)
        if hook_bus is not None:
            decision = await hook_bus.fire(
                HookEvent.PRE_DISPATCH,
                {
                    "agent_id": self.ctx.agent_id,
                    "intent_name": intent_name,
                    "params": params,
                },
            )
            blocked = decision.denied
        else:
            igs = getattr(self.ctx.runtime, "intent_grant_store", None)
            blocked = (
                igs is not None
                and igs.resolve_sync(self.ctx.agent_id, intent_name) == "restricted"
            )
        if blocked:
            logger.info(
                "AD-1012: [MESH %s] blocked for agent=%s (capability disabled "
                "by the Captain); stripping tag, no execution",
                intent_name, self.ctx.agent_id,
            )
            self.ctx.response_text = (
                gate.strip_mesh_read(self.ctx.response_text).rstrip()
                + f"\n\n(I'm not authorized to use {intent_name} right now.)"
            )
            return

        intent_bus = getattr(self.ctx.runtime, "intent_bus", None)
        if intent_bus is None:
            logger.warning(
                "AD-869: [MESH %s] from agent=%s but runtime.intent_bus is "
                "None; stripping tag and degrading (no read run)",
                intent_name, self.ctx.agent_id,
            )
            self.ctx.response_text = gate.strip_mesh_read(self.ctx.response_text)
            return

        target_id = self._resolve_mesh_read_agent(pool_name)
        if target_id is None:
            logger.warning(
                "AD-869: [MESH %s] but no live agent in pool %r; degrading",
                intent_name, pool_name,
            )
            self.ctx.response_text = (
                gate.strip_mesh_read(self.ctx.response_text).rstrip()
                + f"\n\n(Couldn't reach a {intent_name} handler just now.)"
            )
            return

        try:
            from probos.types import IntentMessage
            result = await intent_bus.send(
                IntentMessage(
                    intent=intent_name,
                    params=dict(params),
                    target_agent_id=target_id,
                    ttl_seconds=_MESH_READ_TTL_BY_INTENT.get(
                        intent_name, _MESH_READ_TTL_SECONDS
                    ),
                )
            )
        except Exception:
            logger.warning(
                "AD-869: mesh read send failed intent=%s agent=%s; "
                "stripping tag and degrading",
                intent_name, self.ctx.agent_id, exc_info=True,
            )
            self.ctx.response_text = (
                gate.strip_mesh_read(self.ctx.response_text).rstrip()
                + f"\n\n(The {intent_name} lookup didn't finish in time.)"
            )
            return

        rendered = self._render_mesh_read_result(intent_name, result)
        # BF-629: for a requires_reflect read (web_search / read_page) the raw
        # result is a list of links / a page dump. Reason over it in the agent's
        # own voice (search -> reason -> answer), like an agentic tool-use loop,
        # instead of pasting it verbatim — the gap behind "Ezri gave me links, I
        # had to prompt her again to summarise." One LLM pass, same fast turn.
        # Verbatim reads (read_file, list_directory) are the answer as-is and
        # skip this. Honest-degrade lives in the helper (keeps the verbatim
        # render on any failure, incl. the BF-289/612 empty-content surface).
        if (
            intent_name in _MESH_READ_SYNTHESIZE_INTENTS
            and getattr(result, "success", False)
        ):
            rendered = await self._synthesize_mesh_read(intent_name, rendered)
        logger.info(
            "AD-869: agent=%s ran inline read intent=%s (success=%s)",
            self.ctx.agent_id, intent_name,
            bool(getattr(result, "success", False)),
        )
        self.ctx.response_text = (
            gate.strip_mesh_read(self.ctx.response_text).rstrip()
            + "\n\n" + rendered
        )

    def _resolve_mesh_read_agent(self, pool_name: str) -> str | None:
        """AD-869: resolve the first live agent in ``pool_name`` to a UUID.

        Reuses the ``registry.get_by_pool`` resolution pattern already used
        by Yeo's capability block (BF-599). Returns ``None`` when the
        registry is absent or the pool is empty. Tier-2: never raises.
        """
        registry = getattr(self.ctx.runtime, "registry", None)
        if registry is None:
            return None
        try:
            agents = registry.get_by_pool(pool_name)
        except Exception:
            logger.debug(
                "AD-869: get_by_pool(%r) raised", pool_name, exc_info=True,
            )
            return None
        for agent in agents or []:
            agent_id = getattr(agent, "id", None)
            if agent_id:
                return agent_id
        return None

    def _render_mesh_read_result(self, intent_name: str, result: Any) -> str:
        """AD-869: render an :class:`IntentResult` into Captain-visible text.

        Honest-degrades to a brief note on a missing / unsuccessful result.
        Large payloads are truncated to :data:`_MESH_READ_RENDER_MAX_CHARS`.
        Note wording avoids the decomposer capability-gap tokens (BF-599)."""
        if result is None or not getattr(result, "success", False):
            err = getattr(result, "error", None) if result is not None else None
            note = f" ({err})" if err else ""
            return f"(The {intent_name} lookup came back empty{note}.)"
        text = self._stringify_mesh_payload(getattr(result, "result", None))
        if len(text) > _MESH_READ_RENDER_MAX_CHARS:
            text = text[:_MESH_READ_RENDER_MAX_CHARS].rstrip() + "\n… (truncated)"
        return text

    async def _synthesize_mesh_read(self, intent_name: str, rendered: str) -> str:
        """BF-629: reason over a requires_reflect mesh-read result in the agent's
        own voice (search → reason → answer), instead of pasting raw results.

        One LLM pass through the runtime's tiered client, in the originating
        agent's voice, with the Captain's question + the rendered results as
        context. Flag-gated (``config.dm_mesh_synthesis.enabled``, default OFF in
        the model / ON in system.yaml). Tier-2 honest-degrade: a disabled flag,
        a missing client, empty ``rendered``, or an empty/raised LLM response all
        return the verbatim ``rendered`` unchanged — so a degraded LLM (incl. the
        BF-289/612 empty-content proxy surface) never drops the Captain's
        results, it just falls back to the raw list. NEVER raises."""
        cfg = getattr(getattr(self.ctx.runtime, "config", None), "dm_mesh_synthesis", None)
        if not bool(getattr(cfg, "enabled", False)):
            return rendered
        client = getattr(self.ctx.runtime, "llm_client", None)
        if client is None or not rendered.strip():
            return rendered
        try:
            from probos.cognitive.llm_client import LLMRequest
            callsign = self.ctx.callsign or self.ctx.agent_id
            question = (self.ctx.req_message or self.ctx.message_text or "").strip()
            resp = await client.complete(LLMRequest(
                prompt=(
                    f"The Captain asked:\n{question}\n\n"
                    f"Results from your {intent_name}:\n{rendered}\n\n"
                    "Answer the Captain's question now by reasoning over these "
                    "results in your own voice — synthesise the key findings, "
                    "don't just list them. Note the most relevant sources inline. "
                    "If the results don't actually answer the question, say so "
                    "honestly rather than padding. Output only your reply."
                ),
                system_prompt=(
                    f"You are {callsign}. You just ran a {intent_name} and received "
                    "the results below. Reason over them and give the Captain a "
                    "clear, synthesised answer in your natural voice. Never "
                    "fabricate beyond what the results support."
                ),
                tier=str(getattr(cfg, "tier", "standard")),
                max_tokens=int(getattr(cfg, "max_tokens", 700)),
            ))
            synth = (resp.content or "").strip() if resp else ""
            return synth or rendered
        except Exception:
            logger.warning(
                "BF-629: mesh-read synthesis failed intent=%s agent=%s; keeping "
                "verbatim render", intent_name, self.ctx.agent_id, exc_info=True,
            )
            return rendered

    @staticmethod
    def _stringify_mesh_payload(payload: Any) -> str:
        """AD-869: best-effort stringify of a read result payload."""
        if payload is None:
            return "(empty result)"
        if isinstance(payload, str):
            return payload
        try:
            return json.dumps(payload, indent=2, default=str, ensure_ascii=False)
        except Exception:
            return str(payload)

    # --- step 4f: AD-797 (Wave 197) artifact extractor ---
    async def step_4f_extract_artifacts(self) -> None:
        """AD-797 (Wave 197): extract ``<artifact>`` tags + large fenced-code
        blocks from ``self.ctx.response_text``, persist bytes to the
        AttachmentStore + metadata to the ArtifactStore, and rewrite
        ``response_text`` with stub lines so downstream episodic storage
        + Captain-visible text see the clean scrollback.

        Runs AFTER ``step_4b_dm_outbound_parse`` (so [DM] markers are
        already extracted into outbound DMs and the body is final) and
        BEFORE ``step_5_episodic_store`` (so the stored episode carries
        the stubbed body, not the raw blocks).

        Honest-degrade: any failure logs a warning and leaves
        ``response_text`` untouched. The whole step is Tier-2.
        """
        try:
            text = self.ctx.response_text or ""
            if not text:
                return
            artifact_store = getattr(self.ctx.runtime, "artifact_store", None)
            attachment_store = getattr(self.ctx.runtime, "attachment_store", None)
            if artifact_store is None or attachment_store is None:
                return
            thread_id = self.ctx.chat_thread_id
            if not thread_id:
                return  # no thread context — nothing to anchor extraction
            try:
                existing = artifact_store.list_thread_latest(thread_id)
            except Exception:
                logger.warning(
                    "AD-797: list_thread_latest failed for thread=%s; "
                    "skipping extraction",
                    thread_id, exc_info=True,
                )
                return
            unnamed_count = sum(
                1 for a in existing if a.name.startswith("artifact-")
            )
            config = getattr(self.ctx.runtime, "config", None)
            cognitive_cfg = getattr(config, "cognitive", None) if config else None
            threshold = getattr(
                cognitive_cfg, "artifact_fenced_threshold_lines", 40,
            )
            from probos.cognitive.dm.artifact_extractor import (
                extract_artifacts,
                has_explicit_artifact_marker,
                replace_with_stubs,
            )
            extracted = extract_artifacts(
                text,
                fenced_threshold_lines=threshold,
                existing_unnamed_count=unnamed_count,
            )
            if not extracted:
                return
            comm_cfg = getattr(self.ctx.runtime.config, "communications", None)
            new_text, _artifacts = await replace_with_stubs(
                text, extracted,
                artifact_store=artifact_store,
                attachment_store=attachment_store,
                thread_id=thread_id,
                created_by=self.ctx.agent_id or "agent",
                office_backend=getattr(comm_cfg, "office_backend", "python-docx"),
                libreoffice_path=getattr(comm_cfg, "libreoffice_path", ""),
            )
            self.ctx.response_text = new_text
            if _artifacts:
                # AD-1285 (#1087): an artifact reached the ArtifactStore, so
                # this turn DID write. The no-write direction below is gated on
                # an explicit <artifact> marker, because ``extract_artifacts``
                # has a second pass that lifts any fenced block of >= 40 lines
                # with no marker and no save claim from the agent -- recording
                # THAT as a channel which wrote nothing would let Branch 1,
                # which reads no text at all, append a save disclosure to a
                # reply that described no save.
                self.ctx.write_ledger = self.ctx.write_ledger.consulted_with(
                    WRITE_CHANNEL_ARTIFACT, wrote=True,
                )
                logger.info(
                    "AD-797: extracted %d artifact(s) from agent=%s reply "
                    "in thread=%s",
                    len(_artifacts), self.ctx.agent_id, thread_id,
                )
            elif has_explicit_artifact_marker(text):
                # AD-1285 (#1087): an explicit <artifact> tag asked for a save
                # and nothing persisted -- ``replace_with_stubs`` swallows an
                # ``add_version`` failure and returns only the rows that landed.
                # Without this the channel stays unrecorded, 4m abstains, and a
                # failed artifact write reaches the Captain reading like a
                # success. Gated on the explicit marker for the reason above:
                # a pass-2 lift is not a save the agent claimed.
                self.ctx.write_ledger = self.ctx.write_ledger.consulted_with(
                    WRITE_CHANNEL_ARTIFACT, wrote=False,
                )
                logger.warning(
                    "AD-1285: artifact marker present for agent=%s in "
                    "thread=%s but no artifact persisted; disclosing",
                    self.ctx.agent_id, thread_id,
                )
        except Exception as exc:
            logger.warning(
                "AD-797: artifact extractor failed for agent=%s; "
                "response_text left intact (%s)",
                self.ctx.agent_id, exc, exc_info=True,
            )

    # --- step 4k: AD-811a [A2UI]{json}[/A2UI] choice-widget extraction ---
    async def step_4k_extract_a2ui(self) -> None:
        """AD-811a: extract ``[A2UI]{json}[/A2UI]`` choice-widget blocks from
        ``self.ctx.response_text``, persist each as an ``application/json``
        artifact (the AD-797 two-call write), and rewrite ``response_text``
        with an inline ``[A2UI: name vN - choice]`` stub so the HXI renders an
        interactive choice card in the transcript.

        Default-OFF: gated on ``config.communications.a2ui_enabled`` (default
        False). When off the step returns immediately doing nothing, so the
        reply is byte-identical to pre-AD-811a. AD-811c registers this in BOTH
        :meth:`_full_steps` (1:1) and :meth:`_escalation_steps` (group
        fan-out); it is channel-agnostic — ``chat_thread_id`` and
        ``a2ui_enabled`` are set on both paths.

        Runs adjacent to ``step_4f_extract_artifacts`` (after it, before
        ``step_4g_create_task_parse``) under the same per-step Tier-2 guard.
        Honest-degrade: any failure logs a warning and leaves
        ``response_text`` untouched.
        """
        try:
            text = self.ctx.response_text or ""
            if not text:
                return
            config = getattr(self.ctx.runtime, "config", None)
            comms_cfg = (
                getattr(config, "communications", None) if config else None
            )
            if not getattr(comms_cfg, "a2ui_enabled", False):
                return  # default-OFF: byte-identical when the flag is off
            if "[A2UI]" not in text.upper():
                return  # cheap early-out before the regex/store work
            artifact_store = getattr(self.ctx.runtime, "artifact_store", None)
            attachment_store = getattr(
                self.ctx.runtime, "attachment_store", None
            )
            if artifact_store is None or attachment_store is None:
                return
            thread_id = self.ctx.chat_thread_id
            if not thread_id:
                return  # no thread context — nothing to anchor extraction
            max_options = getattr(comms_cfg, "a2ui_max_options", 10)
            from probos.cognitive.dm.a2ui_extractor import (
                extract_a2ui,
                replace_a2ui_with_stubs,
            )
            specs = extract_a2ui(text, max_options=max_options)
            if not specs:
                return
            new_text, _artifacts = await replace_a2ui_with_stubs(
                text, specs,
                artifact_store=artifact_store,
                attachment_store=attachment_store,
                thread_id=thread_id,
                created_by=self.ctx.agent_id or "agent",
            )
            self.ctx.response_text = new_text
            if _artifacts:
                logger.info(
                    "AD-811a: extracted %d A2UI choice widget(s) from "
                    "agent=%s reply in thread=%s",
                    len(_artifacts), self.ctx.agent_id, thread_id,
                )
        except Exception as exc:
            logger.warning(
                "AD-811a: A2UI extractor failed for agent=%s; "
                "response_text left intact (%s)",
                self.ctx.agent_id, exc, exc_info=True,
            )

    # --- step 4l: AD-1081 room-Todo tags -> the AD-1080 validation loop ---
    async def step_4l_extract_todos(self) -> None:
        """AD-1081: drive the AD-1080 senior-validation Todo loop from an agent's
        room reply. Tags: [TODOS]...[/TODOS] (a SENIOR seeds the plan),
        [TODO_DONE n] (a worker self-reports step n -> submitted),
        [TODO_CONFIRM n] / [TODO_REJECT n: reason] (a SENIOR confirms/rejects).
        Default-OFF (``communications.room_todos_enabled``). Resolves the room's
        task via ``chat_thread_id -> thread.task_id``; no task -> strip-only.
        AD-1085a: if the agent narrated a numbered plan but skipped [TODOS],
        seed the checklist from the prose (only when the task has no steps yet).
        Tier-2 honest-degrade: any failure logs and leaves the reply intact."""
        try:
            text = self.ctx.response_text or ""
            if not text:
                return
            config = getattr(self.ctx.runtime, "config", None)
            comms_cfg = getattr(config, "communications", None) if config else None
            if not getattr(comms_cfg, "room_todos_enabled", False):
                return  # default-OFF: byte-identical when the flag is off
            from probos.cognitive.dm.todo_extractor import (
                has_todo_tag, parse_todo_tags, strip_todo_tags, derive_prose_plan,
            )
            store = getattr(self.ctx.runtime, "work_item_store", None)
            thread_store = getattr(self.ctx.runtime, "chat_thread_store", None)
            thread_id = self.ctx.chat_thread_id
            if store is None or thread_store is None or not thread_id:
                if has_todo_tag(text):
                    self.ctx.response_text = strip_todo_tags(text)
                return
            thread = thread_store.get_thread(thread_id)
            task_id = getattr(thread, "task_id", None) if thread else None
            if task_id:
                if has_todo_tag(text):
                    await self._apply_room_todos(store, task_id, parse_todo_tags(text))
                else:
                    # AD-1085a: deterministic fallback — the agent narrated a
                    # numbered plan but skipped [TODOS]. Seed from the prose IF
                    # the task has no steps yet (never clobber an existing plan).
                    plan = derive_prose_plan(text)
                    if len(plan) >= 2 and self._todo_actor_can_seed(self.ctx.agent_id or "agent"):
                        item = await store.get_work_item(task_id)
                        if item and not (item.steps or []):
                            await store.set_steps(task_id, plan, gate_completion=True, facilitator=self.ctx.agent_id or "agent")
                            await self._maybe_title_room(store, task_id, item)
            if has_todo_tag(text):
                self.ctx.response_text = strip_todo_tags(text)
        except Exception as exc:
            logger.warning(
                "AD-1081: todo extractor failed for agent=%s; text left intact (%s)",
                self.ctx.agent_id, exc, exc_info=True,
            )

    def _todo_actor_is_senior(self, agent_id: str) -> bool:
        """AD-1081: True iff the actor's rank >= ``room_todos_min_rank`` (the
        senior/facilitator who owns the plan + validation). Honest-degrade to
        False on any error (deny the privileged action, never raise)."""
        return self._todo_actor_meets(agent_id, "room_todos_min_rank", "commander")

    def _todo_actor_can_seed(self, agent_id: str) -> bool:
        """AD-1082: True iff the actor's rank >= ``room_todos_seed_min_rank``.
        Seeding the plan is open by default (any crew can write the checklist
        the Captain asked for); only confirm/reject stay senior-gated."""
        return self._todo_actor_meets(agent_id, "room_todos_seed_min_rank", "ensign")

    def _todo_actor_meets(self, agent_id: str, field: str, fallback: str) -> bool:
        """AD-1082: True iff the actor's rank >= the named config min-rank.
        Honest-degrade to False on any error (deny, never raise)."""
        rt = self.ctx.runtime
        try:
            from probos.crew_profile import Rank
            tn = getattr(rt, "trust_network", None)
            if tn is None:
                return False
            rank = Rank.from_trust(tn.get_score(agent_id))
            comms = getattr(getattr(rt, "config", None), "communications", None)
            min_str = str(getattr(comms, field, fallback))
            order = [Rank.ENSIGN, Rank.LIEUTENANT, Rank.COMMANDER, Rank.SENIOR]
            min_rank = (
                Rank[min_str.upper()]
                if min_str.upper() in Rank.__members__
                else Rank[fallback.upper()]
            )
            return order.index(rank) >= order.index(min_rank)
        except Exception:
            return False

    _GENERIC_ROOM_TITLES = frozenset({"", "room workspace", "untitled", "task"})

    @staticmethod
    def _derive_room_title(text: str) -> str:
        """AD-1094: a concise room title from the Captain's request — first
        sentence/line, trimmed to ~60 chars (e.g. 'Create a Word document...')."""
        t = (text or "").strip()
        for sep in ("\n", ". ", "? ", "! "):
            if sep in t:
                t = t.split(sep, 1)[0]
                break
        t = t.strip().rstrip(".?!").strip()
        return t[:60].strip()

    async def _maybe_title_room(self, store: Any, task_id: str, item: Any) -> None:
        """AD-1094: when a room task still has a generic/empty title, name it
        after the Captain's request so the Crew Collaboration topic line is
        meaningful. Honest-degrade: any failure leaves the title unchanged."""
        try:
            current = (getattr(item, "title", "") or "").strip().lower()
            if current not in self._GENERIC_ROOM_TITLES:
                return
            title = self._derive_room_title(self.ctx.req_message)
            if title and hasattr(store, "update_work_item"):
                await store.update_work_item(task_id, title=title)
        except Exception:
            logger.debug("AD-1094: room title derive failed for %s", task_id, exc_info=True)

    async def _apply_room_todos(self, store: Any, task_id: str, parsed: Any) -> None:
        """AD-1081/AD-1087: apply parsed room-todo intents. Plan seeding is open
        (the seeder is recorded as facilitator); confirm/reject are allowed for a
        senior OR the facilitator who created the plan (whoever kicked off the
        task validates it). A worker may self-report its own step (submit)."""
        actor = self.ctx.agent_id or "agent"
        item = await store.get_work_item(task_id)
        facilitator = (getattr(item, "metadata", {}) or {}).get("facilitator") if item else None
        is_senior = self._todo_actor_is_senior(actor)
        can_validate = is_senior or actor == facilitator
        if parsed.plan is not None and self._todo_actor_can_seed(actor):
            await store.set_steps(task_id, parsed.plan, gate_completion=True, facilitator=actor)
            await self._maybe_title_room(store, task_id, item)
        for idx in parsed.submit:
            await store.update_step(task_id, idx, status="submitted", actor=actor)
        if can_validate:
            for idx in parsed.confirm:
                await store.update_step(task_id, idx, status="done", actor=actor)
            for idx, reason in parsed.reject:
                await store.update_step(
                    task_id, idx, status="rejected", actor=actor, note=reason,
                )

    # --- step 4g: AD-845 [CREATE_TASK ...] parse + dispatchable work item ---
    async def step_4g_create_task_parse(self) -> None:
        """AD-845: parse a ``[CREATE_TASK title=... | instructions=... |
        specialist=@callsign]`` tag from the reply, create a dispatchable
        work item assigned to the resolved specialist, and strip the tag.

        Only Yeo is taught the tag (via ``_conversational_task_protocol``),
        so this is effectively Yeo-scoped; the parser is agent-agnostic and a
        no-op for any reply without the tag. The created item carries
        ``metadata.dispatchable=True`` + ``tags=["yeo-delegated"]`` so the
        AD-834/AD-839 ``WorkItemRouter`` runs the work automatically and it
        surfaces on the Captain's kanban board.

        Tier-2 honest-degrade: a missing sanity gate, missing work-item
        store, or a create failure logs a warning, strips the tag, and ships
        the conversational reply unchanged. NEVER raises (the top-level
        ``run()`` guard is belt-and-braces).
        """
        if not self.ctx.response_text or self.ctx.sanity_gate is None:
            return
        parsed = self.ctx.sanity_gate.extract_create_task(self.ctx.response_text)
        if parsed is None:
            return
        title, instructions, specialist = parsed

        store = getattr(self.ctx.runtime, "work_item_store", None)
        if store is None:
            logger.warning(
                "AD-845: [CREATE_TASK] from agent=%s but runtime.work_item_store "
                "is None; stripping tag and degrading (no task created)",
                self.ctx.agent_id,
            )
            self.ctx.response_text = self.ctx.sanity_gate.strip_create_task(
                self.ctx.response_text
            )
            return

        # Resolve specialist callsign -> live agent UUID. assigned_to may
        # remain None (no live specialist) — the item is still created and
        # dispatchable so the router can assign it (AD-845 acceptance (e)).
        assigned_to = self._resolve_specialist_agent_id(specialist, instructions)

        try:
            item = await store.create_work_item(
                title=title,
                description=instructions,
                work_type="task",
                assigned_to=assigned_to,
                created_by="captain",
                metadata={"dispatchable": True},
                tags=["yeo-delegated"],
            )
            logger.info(
                "AD-845: agent=%s opened dispatchable task %s "
                "(assigned_to=%s) from chat: %r",
                self.ctx.agent_id, item.id, assigned_to, title,
            )
            self.ctx.response_text = (
                self.ctx.sanity_gate.strip_create_task(self.ctx.response_text)
                + f"\n\n(Task opened: {item.id})"
            )
        except Exception:
            logger.warning(
                "AD-845: create_work_item failed for agent=%s title=%r; "
                "stripping tag and shipping reply unchanged",
                self.ctx.agent_id, title, exc_info=True,
            )
            self.ctx.response_text = self.ctx.sanity_gate.strip_create_task(
                self.ctx.response_text
            )

    def _resolve_specialist_agent_id(
        self, specialist: str, instructions: str,
    ) -> str | None:
        """AD-845: resolve a specialist callsign to a live agent UUID.

        Primary: ``callsign_registry.resolve``. Fallback when the callsign is
        unknown or has no live agent: Yeo's department keyword map
        (``resolve_delegate``) over the instructions text. Returns ``None``
        when neither path yields a live agent — the work item is still
        created (unassigned but dispatchable). Tier-2: never raises.
        """
        registry = getattr(self.ctx.runtime, "callsign_registry", None)

        def _lookup(callsign: str) -> str | None:
            if registry is None or not callsign:
                return None
            try:
                resolved = registry.resolve(callsign)
            except Exception:
                logger.debug(
                    "AD-845: callsign resolve raised for %r",
                    callsign, exc_info=True,
                )
                return None
            if resolved is None:
                return None
            return resolved.get("agent_id")

        agent_id = _lookup(specialist)
        if agent_id is not None:
            return agent_id

        # Fallback: keyword-map the instructions to a department callsign.
        try:
            from probos.cognitive.yeoman import resolve_delegate
            fallback_callsign = resolve_delegate(instructions)
        except Exception:
            fallback_callsign = None
        if fallback_callsign:
            return _lookup(fallback_callsign)
        return None

    async def step_4j_deliberate_parse(self) -> None:
        """AD-934 (Option C): on a [THINK]/[DELIBERATE] marker, make ONE deep-tier
        LLM pass that reconsiders + improves the agent's draft reply, replacing the
        reply text. Flag-gated (config.dm_deliberate.enabled, default OFF). The
        marker is ALWAYS stripped (even when disabled) so it never leaks. Tier-2
        honest-degrade: a missing client / disabled tier / empty or raised response
        keeps the draft unchanged. NEVER raises."""
        if not self.ctx.response_text or self.ctx.sanity_gate is None:
            return
        cfg = getattr(getattr(self.ctx.runtime, "config", None), "dm_deliberate", None)
        enabled = bool(getattr(cfg, "enabled", False))
        # Always strip the marker first so it never leaks, even disabled.
        has_marker = self.ctx.sanity_gate.extract_deliberate(self.ctx.response_text)
        if not enabled or not has_marker:
            if has_marker:
                self.ctx.response_text = self.ctx.sanity_gate.strip_deliberate(self.ctx.response_text)
            return
        draft = self.ctx.sanity_gate.strip_deliberate(self.ctx.response_text)
        client = getattr(self.ctx.runtime, "llm_client", None)
        if client is None:
            self.ctx.response_text = draft
            return
        try:
            from probos.cognitive.llm_client import LLMRequest
            callsign = self.ctx.callsign or self.ctx.agent_id
            question = (self.ctx.req_message or self.ctx.message_text or "").strip()
            resp = await client.complete(LLMRequest(
                prompt=(
                    f"The message you are replying to:\n{question}\n\n"
                    f"Your draft reply:\n{draft}\n\n"
                    "Reconsider your draft carefully and produce a more thorough, "
                    "well-reasoned version. Output ONLY the improved reply text — "
                    "no tags, no preamble, no meta-commentary."
                ),
                system_prompt=(
                    f"You are {callsign}. You flagged this turn for deeper "
                    "deliberation. Improve your own draft reply: tighten the "
                    "reasoning, fill gaps, and keep your natural voice. Output only "
                    "the final reply."
                ),
                tier=str(getattr(cfg, "tier", "deep")),
                max_tokens=int(getattr(cfg, "max_tokens", 800)),
            ))
            refined = (resp.content or "").strip() if resp else ""
            # Strip any stray marker the re-roll might echo, then adopt or degrade.
            refined = self.ctx.sanity_gate.strip_deliberate(refined)
            self.ctx.response_text = refined or draft
        except Exception:
            logger.warning(
                "AD-934: deliberate re-roll failed for agent=%s; keeping draft",
                self.ctx.agent_id, exc_info=True,
            )
            self.ctx.response_text = draft

    # --- step 4m: AD-1285 (#1087 / BF-687) write-claim guard ---
    async def step_4m_write_claim_guard(self) -> None:
        """AD-1285 (#1087 / BF-687): a turn that claims a save must prove one.

        Compares :class:`WriteLedger` against itself -- which durable-write
        channels ran this turn versus which of them produced a write -- and
        appends one honest sentence when a channel ran and wrote nothing. The
        reply is only the surface the disclosure lands on; no text is read.
        Never blocks and never rewrites the agent's substance (#13(c): a
        refusal that ends the work is a capability ceiling in a governance
        costume).

        Abstains whenever no channel ran, so a ship with no write channel
        wired is byte-identical.

        Tier-2 honest-degrade: never raises.
        """
        try:
            if not self.ctx.response_text:
                return
            config = getattr(self.ctx.runtime, "config", None)
            guard_cfg = (
                getattr(config, "write_claim_guard", None) if config else None
            )
            if not getattr(guard_cfg, "enabled", True):
                return  # flag exists so this can be turned off without a revert

            verdict = assess_write_claim(self.ctx.write_ledger)
            if verdict is ClaimVerdict.ABSTAIN:
                return

            logger.warning(
                "AD-1285: write-claim guard verdict=%s agent=%s thread=%s "
                "ran_without_writing=%s wrote=%s",
                verdict.value,
                self.ctx.agent_id,
                self.ctx.chat_thread_id,
                sorted(self.ctx.write_ledger.wrote_nothing),
                sorted(self.ctx.write_ledger.wrote),
            )
            self.ctx.response_text = (
                self.ctx.response_text + disclosure_for(verdict)
            )
        except Exception:
            logger.warning(
                "AD-1285: write-claim guard raised for agent=%s; shipping "
                "the reply unmarked",
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
                        chat_thread_id=self.ctx.chat_thread_id,  # AD-791a
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
        """Return the final response dict — verbatim move of routers/agents.py:1553..1559.

        AD-1248: this is the route's SINGLE composition point. Both sinks on
        this route — the HTTP body and the thread append — read the value
        composed here, so the disclosure cannot reach one and miss the other.
        """
        response: dict[str, Any] = {
            "response": self.ctx.reply.render(),
            "callsign": self.ctx.callsign,
            "agentId": self.ctx.agent_id,
            "emotion": self.ctx.emotion,
        }
        # AD-730-3: generated images attached as SHA refs (AD-731).
        if self.ctx.generated_attachment_ids:
            response["attachment_ids"] = list(self.ctx.generated_attachment_ids)
        if self.ctx.game_move_result:
            response["gameMoveExecuted"] = True
            response["gameStatus"] = self.ctx.game_move_result.get("state", {}).get("status", "")
        return response
