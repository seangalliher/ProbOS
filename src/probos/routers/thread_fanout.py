"""AD-914: group-chat fan-out for ChatThreadStore threads.

When the Captain posts to a thread with >= 2 crew-agent participants, fan
the turn out to all agent participants in parallel, inject recent thread
history into each agent's prompt (cross-agent visibility), and persist each
reply as a chat_thread_messages row (role="agent"). The ChatThreadStore form
of the dormant AD-719a-wire marker.

Boundary (AD-914): fan out the Captain's turn ONCE (parallel) and STOP.
Agents do NOT auto-reply to each other — that is AD-915 (turn-taking) and
AD-918 (agent-initiated). Captain-seeds rule per the AD-719a contract.

Forward marker (AD-914a): the chat.py AD-719 @-mention branch shares the
parallel-dispatch shape but resolves callsigns + passes blind history; a
future AD may unify the two. Not unified here by design.
"""
from __future__ import annotations

import asyncio
import logging
import re
import time
from typing import Any

from probos.cognitive.chat_facilitator import (
    ChatFacilitator,
    SpeakerSignals,
    build_room_signal,
)
from probos.cognitive.dm import DmReplyContext, DmReplyPipeline
from probos.cognitive.similarity import jaccard_similarity, text_to_words
from probos.avatars.divergence_detector import strip_intent_self_tag
from probos.crew_profile import (
    extract_all_leading_callsign_mentions,
    extract_directed_callsign,
)
from probos.crew_utils import is_crew_agent
from probos.types import IntentMessage

logger = logging.getLogger(__name__)

# AD-914: recent-history window injected into each agent's prompt. Module
# constant — NOT config (zero-config boot). Bounds prompt size.
_FANOUT_HISTORY_LIMIT = 20

# AD-915: recent agent turns inspected by the convergence gate.
_CONVERGENCE_WINDOW = 12


def crew_agent_participants(runtime: Any, participants: list[str]) -> list[str]:
    """Participant agent_ids that resolve to crew agents (Captain/non-crew excluded)."""
    out: list[str] = []
    for pid in participants:
        agent = runtime.registry.get(pid)
        if agent is not None and is_crew_agent(agent, getattr(runtime, "ontology", None)):
            out.append(pid)
    return out


def _build_session_history(
    runtime: Any, store: Any, thread_id: str, before: float, prior: Any = None
) -> list[dict[str, str]]:
    """Recent thread turns (excluding the just-appended Captain msg) as
    ``{"role": <callsign|Captain|system>, "text": body}`` entries.

    ``list_messages`` is ``ORDER BY created_at ASC LIMIT ?`` — a bare limit
    returns the OLDEST N, so fetch the store max and tail-slice to the most
    recent window. Tier-2: callsign-label resolution failures degrade to the
    raw stored role.
    """
    if prior is None:
        prior = store.list_messages(thread_id, limit=1000, before=before)
    recent = prior[-_FANOUT_HISTORY_LIMIT:]
    history: list[dict[str, str]] = []
    for m in recent:
        if m.role == "agent":
            label = "agent"
            try:
                agent = runtime.registry.get(m.author_id)
                if agent is not None and hasattr(runtime, "callsign_registry"):
                    label = runtime.callsign_registry.get_callsign(agent.agent_type) or "agent"
            except Exception:
                logger.debug(
                    "AD-914: callsign label resolve failed for %s", m.author_id, exc_info=True
                )
        elif m.role == "captain":
            label = "Captain"
        else:
            label = "system"
        history.append({"role": label, "text": m.body})
    return history


def _assemble_speaker_signals(
    runtime: Any, captain_body: str, agent_ids: list[str], prior: list[Any],
    addressed_callsigns: set[str] | None = None,
) -> list[SpeakerSignals]:
    """Build per-speaker SpeakerSignals snapshots from the runtime. Every
    lookup is Tier-2 log-and-degrade (mirrors group_chat_fanout): a missing
    registry/callsign/ontology/trust never blocks facilitation.

    AD-951: ``addressed_callsigns`` (lower-cased) are peers a prior-round speaker
    DIRECTLY ADDRESSED (turn-allocation rule 1a); a candidate whose callsign is
    in that set is hard-included (``mentioned=True``) exactly like a Captain
    @-mention. A non-participant callsign matches no candidate and is ignored.
    """
    # @-mentions in the Captain turn -> hard-include set (lower-cased callsigns).
    mention_callsigns: set[str] = set()
    try:
        leading, _ = extract_all_leading_callsign_mentions(captain_body or "")
        mention_callsigns.update(leading)
        for m in re.findall(r"@(\w+)", captain_body or ""):
            mention_callsigns.add(m.lower())
    except Exception:
        logger.debug("AD-915: mention parse failed", exc_info=True)
    # turns_since_last_spoke from prior (oldest->newest). Default large = quiet.
    last_idx: dict[str, int] = {}
    for i, m in enumerate(prior):
        if getattr(m, "role", "") == "agent":
            last_idx[m.author_id] = i
    n_prior = len(prior)
    cap_words = text_to_words(captain_body or "")
    trust_lookup = None
    tn = getattr(runtime, "trust_network", None)
    if tn is not None and hasattr(tn, "get_score"):
        trust_lookup = tn.get_score
    ontology = getattr(runtime, "ontology", None)
    signals: list[SpeakerSignals] = []
    for idx, aid in enumerate(agent_ids):
        agent_type = ""
        callsign = ""
        try:
            agent = runtime.registry.get(aid)
            if agent is not None:
                agent_type = getattr(agent, "agent_type", "") or ""
                if hasattr(runtime, "callsign_registry"):
                    callsign = runtime.callsign_registry.get_callsign(agent_type) or ""
        except Exception:
            logger.debug("AD-915: identity resolve failed for %s", aid, exc_info=True)
        cl = callsign.lower() if callsign else ""
        mentioned = bool(callsign) and (
            cl in mention_callsigns
            or (addressed_callsigns is not None and cl in addressed_callsigns)
        )
        turns_since = (n_prior - last_idx[aid]) if aid in last_idx else 9_999
        dept = ""
        try:
            if ontology is not None and agent_type:
                dept = ontology.get_agent_department(agent_type) or ""
        except Exception:
            logger.debug("AD-915: department resolve failed for %s", aid, exc_info=True)
        descriptor = text_to_words(f"{dept} {agent_type}")
        dep_rel = jaccard_similarity(cap_words, descriptor)
        trust = 0.5
        if trust_lookup is not None:
            try:
                trust = float(trust_lookup(aid))
            except Exception:
                logger.debug("AD-915: trust lookup failed for %s", aid, exc_info=True)
        signals.append(SpeakerSignals(
            agent_id=aid, mentioned=mentioned, turns_since_last_spoke=turns_since,
            department_relevance=dep_rel, trust=trust, order_index=idx,
        ))
    return signals


async def resolve_attachment_refs(
    store: Any, attachment_ids: list[str]
) -> list[dict[str, str]]:
    """AD-916: resolve already-uploaded SHA-256 ``attachment_ids`` to persisted
    ref records ``{"content_hash", "mime"}``. An id absent from the store
    (``mime_for`` returns None) is skipped with a warning — never raises,
    never fabricates a mime. Order-preserving.
    """
    refs: list[dict[str, str]] = []
    for aid in attachment_ids:
        try:
            mime = await store.mime_for(aid)
        except Exception:
            logger.warning(
                "AD-916: mime lookup failed for attachment %s; skipping", aid, exc_info=True
            )
            continue
        if not mime:
            logger.warning("AD-916: attachment %s not found in store; skipping ref", aid)
            continue
        refs.append({"content_hash": aid, "mime": mime})
    return refs


async def build_chat_vision_messages(
    store: Any, cfg_attach: Any, prompt: str, attachments: list[dict[str, Any]]
) -> list[dict[str, Any]] | None:
    """AD-916: build the AD-730/731 ``vision_messages`` array from the IMAGE
    subset of persisted attachment refs. Returns None when there are no image
    refs (so the caller falls back to the AD-914 text-only fan-out). Reuses
    ``build_multimodal_messages`` → the emitted blocks are the exact AD-731
    ``attachment_ref`` shape the LLM client resolves. Tier-2: any failure
    returns None (text-only).
    """
    image_shas = [
        a["content_hash"] for a in attachments
        if str(a.get("mime", "")).startswith("image/") and a.get("content_hash")
    ]
    if not image_shas:
        return None
    try:
        from probos.cognitive.vision_dispatch import build_multimodal_messages

        async def _mime_lookup(content_hash: str) -> str | None:
            return await store.mime_for(content_hash)

        messages, image_ids, _ = await build_multimodal_messages(
            prompt=prompt,
            attachment_ids=image_shas,
            store=store,
            mime_lookup=_mime_lookup,
            text_extraction_max_bytes=cfg_attach.text_extraction_max_bytes,
            pdf_extraction_enabled=cfg_attach.pdf_extraction_enabled,
        )
    except Exception:
        logger.warning("AD-916: vision_messages build failed; text-only fan-out", exc_info=True)
        return None
    return messages if image_ids else None


def _resolve_callsigns(runtime: Any, agent_ids: list[str]) -> dict[str, str]:
    """AD-955: agent_id -> callsign for the given agents (Tier-2; a missing
    registry/callsign is omitted, never raised). Used to name the peer the room
    would value hearing in the advisory room-awareness signal."""
    out: dict[str, str] = {}
    reg = getattr(runtime, "callsign_registry", None)
    registry = getattr(runtime, "registry", None)
    if reg is None or registry is None:
        return out
    for aid in agent_ids:
        try:
            agent = registry.get(aid)
            if agent is not None:
                cs = reg.get_callsign(getattr(agent, "agent_type", "")) or ""
                if cs:
                    out[aid] = cs
        except Exception:
            logger.debug("AD-955: callsign resolve failed for %s", aid, exc_info=True)
    return out


async def _fan_one_round(
    runtime: Any,
    store: Any,
    thread_id: str,
    *,
    trigger_body: str,
    candidate_ids: list[str],
    exclude_ids: set[str],
    vision_messages: list[dict[str, Any]] | None,
    sanity_gate: Any,
    t_start: float,
    before: float | None = None,
    addressed_callsigns: set[str] | None = None,
) -> list[dict[str, str]]:
    """One reactivity round (AD-935): facilitate over ``candidate_ids`` (minus
    ``exclude_ids``) using ``trigger_body`` for mention/relevance, dispatch the
    chosen speakers in parallel, persist each non-[NO_RESPONSE] reply, write
    AD-933a group episodes, and return the new ``{"agent_id", "callsign",
    "text"}`` replies. Returns ``[]`` when there are no candidates, the
    facilitator suppresses everyone (converged / empty), or every speaker
    declines.

    ``before`` bounds the rebuilt prior window: round 0 passes the Captain
    message timestamp so the just-appended Captain turn is excluded from history
    (AD-914 byte-identical); a cascade round passes ``None`` so the window
    INCLUDES the just-persisted prior-round replies (each speaker sees the full
    transcript). Per-agent dispatch is Tier-2 log-and-degrade: one agent's
    failure never blocks the others.
    """
    candidate_pool = [a for a in candidate_ids if a not in exclude_ids]
    if not candidate_pool:
        return []
    # AD-915: single-read DRY — fetch the prior window once and reuse it for
    # history injection, recency, and the convergence gate. ``before`` is None
    # on cascade rounds so the window includes the just-persisted replies.
    prior = store.list_messages(thread_id, limit=1000, before=before)
    session_history = _build_session_history(
        runtime, store, thread_id, before, prior=prior
    )
    # AD-915: facilitator decides WHO/ORDER; _send_one still does the
    # dispatch+persist (DRY). Tier-2: any facilitation failure degrades to the
    # AD-914 all-at-once order so a facilitator bug never silences the crew.
    signals: list[SpeakerSignals] = []
    _room_scores: list[Any] = []
    try:
        facilitator = ChatFacilitator.from_config(getattr(runtime, "config", None))
        signals = _assemble_speaker_signals(
            runtime, trigger_body, candidate_pool, prior, addressed_callsigns
        )
        recent_agent_msgs = [
            (m.author_id, m.body) for m in prior[-_CONVERGENCE_WINDOW:] if m.role == "agent"
        ]
        result = facilitator.facilitate(signals, recent_agent_msgs)
        speaking_order = result.speaking_order
        _room_scores = list(result.scores)
    except Exception:
        logger.warning(
            "AD-915: facilitation failed for thread=%s; falling back to AD-914 order",
            thread_id, exc_info=True,
        )
        speaking_order = list(candidate_pool)

    # AD-955: per-dispatched-agent ROOM AWARENESS (advisory — the agent reasons
    # over it; NO dispatch change, the cap/convergence backstops are untouched).
    # The facilitator already ranks the room every round (recency + department +
    # trust + mention); AD-955 surfaces that ranking to the speaker so a
    # dominating agent can hold back or hand off, and an agent can defer to a
    # better-placed peer BY NAME (an AD-951 hand-off). Default ON; group-only
    # (this function runs only inside group_chat_fanout). Tier-2: any failure
    # yields no signal (the agent simply replies without room sense).
    room_signals: dict[str, dict[str, Any]] = {}
    try:
        _comm_cfg = getattr(getattr(runtime, "config", None), "communications", None)
        if getattr(_comm_cfg, "room_awareness_enabled", True) and _room_scores:
            _callsign_by_agent = _resolve_callsigns(runtime, candidate_pool)
            _signal_by_agent = {s.agent_id: s for s in signals}
            _recent_authors = [
                m.author_id for m in prior if getattr(m, "role", "") == "agent"
            ]
            for _aid in speaking_order:
                _sig = _signal_by_agent.get(_aid)
                _rs = build_room_signal(
                    agent_id=_aid,
                    department_relevance=(_sig.department_relevance if _sig else 0.0),
                    recent_authors=_recent_authors,
                    scores=_room_scores,
                    callsign_by_agent=_callsign_by_agent,
                )
                if _rs:
                    room_signals[_aid] = _rs
    except Exception:
        logger.debug(
            "AD-955: room signal build failed for thread=%s; replies proceed "
            "without room sense", thread_id, exc_info=True,
        )

    async def _send_one(agent_id: str) -> dict[str, str]:
        callsign = ""
        agent: Any = None
        try:
            agent = runtime.registry.get(agent_id)
            if agent is not None and hasattr(runtime, "callsign_registry"):
                callsign = runtime.callsign_registry.get_callsign(agent.agent_type) or ""
        except Exception:
            logger.debug("AD-914: callsign resolve failed for %s", agent_id, exc_info=True)
        params: dict[str, Any] = {
            "text": trigger_body,
            "from": "hxi_profile",
            "session": bool(session_history),
            "session_history": session_history,
            # AD-935: teach the [NO_RESPONSE] decline option (group-only — the
            # cognitive_agent hook gates the teaching string on this param).
            "is_group_chat": True,
        }
        # AD-955: advisory room-awareness signal for this speaker (when one is
        # salient). The cognitive_agent hook renders it; it never changes
        # dispatch. Rides the same params dict as is_group_chat (small struct).
        _room_sig = room_signals.get(agent_id)
        if _room_sig:
            params["room_signal"] = _room_sig
        # AD-916: only vision-capable participants receive image refs. The
        # ``agent`` above was already resolved for the callsign — reuse it.
        if vision_messages is not None:
            try:
                prof = (
                    runtime.callsign_registry.get_profile(agent.agent_type)
                    if (agent is not None and hasattr(runtime, "callsign_registry"))
                    else None
                )
                if (prof or {}).get("vision_capable", False):
                    params["vision_messages"] = vision_messages
            except Exception:
                logger.debug("AD-916: vision_capable gate failed for %s", agent_id, exc_info=True)
        intent = IntentMessage(
            intent="direct_message",
            params=params,
            target_agent_id=agent_id,
            ttl_seconds=60.0,
            thread_id=thread_id,
        )
        try:
            result = await runtime.intent_bus.send(intent)
        except Exception as e:
            logger.warning(
                "AD-914 fan-out send failed for %s: %s: %s; other recipients unaffected",
                agent_id, type(e).__name__, e,
            )
            return {"agent_id": agent_id, "callsign": callsign, "text": "(delivery failed)"}
        reply_text = str(result.result) if (result and result.result) else "(no response)"
        # AD-933b: SHA refs of any image step_4c generates below. Initialized
        # here so it is always defined for the persist block even when the
        # escalation subset is skipped (no reply / no agent) or raises.
        generated_ids: list[str] = []
        # AD-933: run the channel-agnostic escalation subset on the raw reply
        # so a group-chat turn can resolve an inline mesh read (AD-869),
        # dispatch an [ACTION] (AD-745), parse a notebook (AD-911), extract
        # artifacts (AD-797), or open a [CREATE_TASK] (AD-845) — the same
        # post-LLM ladder the 1:1 path runs (AD-726), minus the 1:1-scoped
        # steps (episodic/working-memory/divergence/emotion/games/avatar) that
        # would mislabel a multi-agent turn. Only when a real reply came back
        # AND the agent resolved (no agent -> can't escalate). Tier-2
        # honest-degrade: any failure ships the raw reply_text unchanged.
        if result and result.result and agent is not None:
            try:
                pipeline = DmReplyPipeline(DmReplyContext(
                    runtime=runtime,
                    agent=agent,
                    agent_id=agent_id,
                    callsign=callsign,
                    req_message=trigger_body,
                    response_text=reply_text,
                    has_image_attachment=bool(vision_messages),
                    per_attachment=[],
                    sanity_gate=sanity_gate,
                    params=params,
                    message_text=trigger_body,
                    sampling_state=None,
                    avatar_event_bus=None,
                    chat_thread_id=thread_id,
                ))
                await pipeline.run_escalation_only()
                reply_text = pipeline.ctx.response_text or reply_text
                # AD-933b: surface SHA refs of any [GEN_IMAGE] image the
                # escalation subset (step_4c, AD-730-3) generated for this
                # group turn, read from the SAME ctx the escalation just ran.
                # [] when no image was generated; persisted below (AD-916 ref
                # carriage) only when non-empty.
                generated_ids = list(pipeline.ctx.generated_attachment_ids or [])
            except Exception:
                logger.warning(
                    "AD-933: escalation subset failed for thread=%s agent=%s; "
                    "shipping raw reply", thread_id, agent_id, exc_info=True,
                )
        # AD-948: strip the AD-722a intent self-tag (<intent emotion=...>)
        # UNCONDITIONALLY before the decline check / persist / return. The 1:1
        # path strips it via apply_divergence_check (routers/agents.py); the
        # group fan-out never did, so the internal tag leaked into the visible
        # transcript. Reuse the single-source-of-truth strip (BF-603 hardened);
        # placed BEFORE the NO_RESPONSE check so a decline that trails a tag is
        # still detected. The tag MUST NEVER reach the Captain.
        reply_text = strip_intent_self_tag(reply_text)
        # AD-935: an agent may decline to respond in a group turn. A
        # [NO_RESPONSE] (case-insensitive, after strip + bracket removal) or an
        # empty reply is NOT persisted and NOT returned — the round collector
        # filters _declined entries before persist-visibility, the episode
        # write, and per_agent_replies, so a decline neither shows in the
        # transcript nor propagates the cascade. (Also fixes round 0: a literal
        # [NO_RESPONSE] reply would previously have been persisted + shown.)
        if reply_text.strip().upper().replace("[", "").replace("]", "") == "NO_RESPONSE" or not reply_text.strip():
            return {"agent_id": agent_id, "callsign": callsign, "text": "", "_declined": True}
        try:
            # AD-933b: attach the generated-image refs only when the
            # escalation produced any; an empty/failed escalation leaves the
            # metadata byte-identical to the AD-914 baseline.
            metadata: dict[str, Any] = {"intent_id": intent.id, "fanout": "ad914"}
            if generated_ids:
                metadata["generated_attachment_ids"] = generated_ids
            store.append_message(
                thread_id, author_id=agent_id, role="agent",
                body=reply_text, metadata=metadata,
            )
        except Exception:
            logger.warning(
                "AD-914: persist reply failed for thread=%s agent=%s",
                thread_id, agent_id, exc_info=True,
            )
        return {"agent_id": agent_id, "callsign": callsign, "text": reply_text}

    raw = await asyncio.gather(*[_send_one(a) for a in speaking_order])
    # AD-935: drop [NO_RESPONSE]/empty declines BEFORE the episode write and
    # the returned per_agent_replies list. (_send_one already early-returns a
    # decline before its own append, so a decline never reaches append_message.)
    replies = [r for r in raw if not r.get("_declined")]
    t_end = time.monotonic()

    # AD-933a: group-anchored episodic write — one episode per crew reply.
    # The fan-out sends direct_message with params["from"]="hxi_profile", which
    # the agent safety-net (_store_action_episode) skips (it defers to the
    # pipeline's step_5), and AD-933 excluded step_5 from the group subset
    # (step_5 hardcodes session_type:"1:1"/channel:"dm", which would mislabel a
    # multi-agent turn). Net: neither path writes a group episode — agents
    # wouldn't remember the room (no episodic recall, no dreaming, no wellness
    # analysis). Mirrors the AD-719 @-mention fan-out (routers/chat.py) but with
    # group anchors. Tier-2 honest-degrade: every store failure logs and
    # continues; the round still returns all replies.
    episodic_memory = getattr(runtime, "episodic_memory", None)
    if episodic_memory is not None:
        from probos.types import AnchorFrame, Episode
        participants = ["captain"] + [(r["callsign"] or r["agent_id"]) for r in replies]
        # AD-935: the trigger is the Captain turn (round 0) or the prior round's
        # joined agent messages (cascade rounds) — record whichever drove this round.
        episode_input = f"[group chat] {trigger_body[:200]}"
        _sentinels = {"(no response)", "(delivery failed)", ""}
        for reply in replies:
            if not reply["agent_id"] or reply["text"] in _sentinels:
                continue
            try:
                # AD-933a: ALWAYS construct the group-anchored Episode directly.
                # NOT dream_adapter.build_episode — that helper derives
                # outcomes/agent_ids/dag_summary from an ``execution_result["dag"]``
                # (a chat fan-out has none) and never sets ``anchors``, so it
                # would silently drop the group anchor + agent_id and emit a
                # dag-shaped episode in production while the no-dream_adapter
                # test path looked correct. Direct construction is the only way
                # the group anchoring actually reaches storage.
                episode = Episode(
                    timestamp=time.time(),
                    user_input=episode_input,
                    dag_summary={},
                    outcomes=[{
                        "intent": "direct_message",
                        "success": True,
                        "response": reply["text"][:500],
                        "session_type": "group",
                        "callsign": reply["callsign"],
                        "source": "group_chat_fanout",
                    }],
                    agent_ids=[reply["agent_id"]],
                    duration_ms=(t_end - t_start) * 1000,
                    source="group_chat_fanout",  # AD-933a distinct tag
                    anchors=AnchorFrame(
                        channel="chat",
                        trigger_type="group_fanout",
                        participants=participants,
                        chat_thread_id=thread_id,
                    ),
                )
                await episodic_memory.store(episode)
            except Exception as e:
                logger.warning(
                    "AD-933a: group episode store failed for %s: %s: %s; "
                    "continuing — episodic gap accepted, replies still returned",
                    reply["callsign"] or reply["agent_id"], type(e).__name__, e,
                )

    return replies


async def group_chat_fanout(
    runtime: Any,
    thread_id: str,
    *,
    captain_body: str,
    captain_msg: Any,
) -> list[dict[str, str]]:
    """Fan the Captain turn out to all crew-agent participants, then (when
    ``group_chat.agent_reactivity_enabled`` is True) run a BOUNDED SYNCHRONOUS
    agent-to-agent cascade for up to ``max_agent_rounds`` extra rounds (AD-935).

    Returns a flat list of ``{"agent_id", "callsign", "text"}`` dicts across ALL
    rounds, in order (the UI renders ``per_agent_replies`` directly). With
    reactivity OFF the result is byte-identical to the AD-914 single round.
    Each round persists its replies as role="agent" messages and writes AD-933a
    group episodes. Assumes the caller already verified ``role == "captain"``
    AND >= 2 crew participants.

    SYNCHRONOUS (awaited, NOT fire-and-forget) because the chat transcript has
    no live-refresh — every cascade reply must be returned in this POST's
    ``per_agent_replies``. The cascade is bounded by the round cap, the AD-915
    convergence gate (empty ``speaking_order`` once the exchange converges),
    exclude-prior-speakers, and all-decline. Each cascade round degrades Tier-2:
    a round failure returns the replies gathered so far. (Async/streaming
    reactivity once a live-refresh exists is forward marker AD-935a.)
    """
    # AD-933a: bound the episode duration measured across the whole fan-out.
    t_start = time.monotonic()
    store = runtime.chat_thread_store
    thread = store.get_thread(thread_id)
    if thread is None:
        return []
    agent_ids = crew_agent_participants(runtime, thread.participants)
    # AD-933: resolve the DM sanity gate ONCE (DRY) before any round — step_4g
    # ([CREATE_TASK]) early-returns without it, so every speaker across every
    # round shares the one runtime gate rather than re-reading it per agent.
    sanity_gate = getattr(runtime, "dm_sanity_gate", None)

    # AD-916: build the group vision array once from the Captain message's
    # persisted attachment refs. Round 0 ONLY (agent rounds carry no Captain
    # attachments). None => no image refs => AD-914 text-only.
    vision_messages: list[dict[str, Any]] | None = None
    try:
        _attachments = (getattr(captain_msg, "metadata", None) or {}).get("attachments") or []
        _cfg_attach = getattr(getattr(runtime, "config", None), "attachments", None)
        if _attachments and _cfg_attach is not None and getattr(_cfg_attach, "enabled", False):
            from probos.routers.chat import _get_attachment_store
            vision_messages = await build_chat_vision_messages(
                _get_attachment_store(runtime), _cfg_attach, captain_body, _attachments
            )
    except Exception:
        logger.warning(
            "AD-916: group vision build failed for thread=%s; text-only fan-out",
            thread_id, exc_info=True,
        )
        vision_messages = None

    # AD-914 round 0: the Captain turn. before=captain_msg.created_at keeps the
    # just-appended Captain message out of each agent's history (byte-identical).
    all_replies: list[dict[str, str]] = []
    round0 = await _fan_one_round(
        runtime, store, thread_id,
        trigger_body=captain_body, candidate_ids=agent_ids, exclude_ids=set(),
        vision_messages=vision_messages, sanity_gate=sanity_gate, t_start=t_start,
        before=captain_msg.created_at,
    )
    all_replies.extend(round0)

    # AD-935: bounded synchronous agent-to-agent cascade. Each extra round fans
    # the PREVIOUS round's new agent messages to the OTHER crew (excluding that
    # round's speakers — an agent never reacts to its own message), gated by the
    # AD-915 convergence gate, [NO_RESPONSE] declines, and the round cap. The
    # cap is the hard backstop; the convergence gate is the semantic terminator
    # (it returns an empty speaking_order once the exchange converges). Default
    # OFF -> the loop is skipped -> round 0 is byte-identical to AD-914.
    cfg = getattr(getattr(runtime, "config", None), "group_chat", None)
    if getattr(cfg, "agent_reactivity_enabled", False):
        max_rounds = int(getattr(cfg, "max_agent_rounds", 2))
        next_speaker_sel = getattr(cfg, "agent_next_speaker_selection_enabled", False)
        last = round0
        for _ in range(max(0, max_rounds)):
            spoke_ids = {r["agent_id"] for r in last if r.get("agent_id")}
            if not spoke_ids:
                break  # nothing new to react to
            trigger = "\n".join(
                f"{r['callsign'] or r['agent_id']}: {r['text']}" for r in last
            )
            # AD-951: turn-allocation rule 1a — when a prior-round speaker
            # DIRECTLY ADDRESSES a peer by callsign ("@yeo ..." or "Yeo, ..."),
            # select that peer to speak next (hard-included past the per-turn cap
            # + convergence, still bounded by max_agent_rounds). Scan each reply's
            # CLEAN text (AD-948 already stripped the <intent> tag); a speaker
            # never selects itself. Honest-degrade: a non-participant callsign
            # matches no candidate downstream. Gated (ships OFF; yaml flips on).
            addressed: set[str] = set()
            if next_speaker_sel:
                for r in last:
                    cs = extract_directed_callsign(r.get("text") or "")
                    if cs and cs != (r.get("callsign") or "").lower():
                        addressed.add(cs)
            try:
                nxt = await _fan_one_round(
                    runtime, store, thread_id,
                    trigger_body=trigger, candidate_ids=agent_ids, exclude_ids=spoke_ids,
                    vision_messages=None, sanity_gate=sanity_gate, t_start=t_start,
                    addressed_callsigns=addressed or None,
                )
            except Exception:
                logger.warning(
                    "AD-935: reactivity round failed for thread=%s; returning "
                    "replies gathered so far", thread_id, exc_info=True,
                )
                break
            if not nxt:
                break  # facilitator converged / suppressed everyone / all declined
            all_replies.extend(nxt)
            last = nxt
    return all_replies
