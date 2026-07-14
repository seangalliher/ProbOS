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
from typing import Any, Literal

from probos.cognitive.chat_facilitator import (
    ChatFacilitator,
    SpeakerSignals,
    build_room_signal,
    facilitation_mode,
)
from probos.cognitive.conversation_trust import (
    conversation_topic_tag,
    detect_conversation_corrections,
    extract_conversation_trust_outcomes,
)
from probos.cognitive.dm import DmReplyContext, DmReplyPipeline
from probos.cognitive.confab_probe import probe_referent
from probos.cognitive.emergence_taxonomy import BehaviorCode
from probos.cognitive.referent_gate import (
    GitObjectResolver,
    ReferentGroundingGate,
    build_default_resolvers,
    extract_referents,
)
from probos.cognitive.similarity import jaccard_similarity, text_to_words
from probos.avatars.divergence_detector import strip_intent_self_tag
from probos.crew_profile import (
    extract_all_leading_callsign_mentions,
    extract_directed_callsign,
    extract_handoff_callsign,
)
from probos.crew_utils import is_crew_agent
from probos.types import IntentMessage

logger = logging.getLogger(__name__)

# AD-914: recent-history window injected into each agent's prompt. Module
# constant — NOT config (zero-config boot). Bounds prompt size.
_FANOUT_HISTORY_LIMIT = 20

# AD-915: recent agent turns inspected by the convergence gate.
_CONVERGENCE_WINDOW = 12

# BF-616: a group-turn decline marker. Matched ANYWHERE in the reply
# (case-insensitive), mirroring the proactive.py ``"[NO_RESPONSE]" in ...``
# contract — a model that explains its decline in prose and trails the marker
# is still a decline, and the whole reply is suppressed (never persisted, never
# shown, never propagated to the cascade).
_NO_RESPONSE_RE = re.compile(r"\[NO_RESPONSE\]", re.IGNORECASE)


# AD-963a: broadcast-cue detector for turn-mode classification. A BROADCAST is a
# plural ask aimed at the whole room ("what do you all think?", "everyone, weigh
# in") — distinct from a DISCUSSION (the default) and from a DIRECTED address (a
# leading callsign, already handled by AD-951's next-speaker selection).
# Conservative by design: only clear plural-address cues match, so anything
# ambiguous stays DISCUSSION (today's behavior).
_BROADCAST_CUE_RE = re.compile(
    r"\b(?:you all|y'all|everyone|everybody|each of you|all of you|both of you|"
    r"whole (?:room|team|crew))\b",
    re.IGNORECASE,
)


# AD-1120: kinds eligible for cue INJECTION. `service` remains excluded as a
# central-policy constraint; BF-667 source grammar is the sole assertion-strength
# authority. Injection changes behavior, so it stays restricted to hex/entity.
_GROUNDING_INJECT_KINDS = frozenset({"hex", "entity"})


def classify_broadcast(text: str) -> bool:
    """AD-963a: True when the Captain turn is a BROADCAST (a plural ask to the
    whole room). In broadcast mode the cascade terminator becomes
    "every crew participant answers once" instead of the discussion cap +
    convergence gate. Conservative + pure: ambiguous text is DISCUSSION (False),
    so the default cascade stays byte-identical."""
    if not text or not isinstance(text, str):
        return False
    return bool(_BROADCAST_CUE_RE.search(text))


def classify_turn_mode(
    text: str, *, directed_callsign: str | None = None
) -> Literal["directed", "broadcast", "discussion"]:
    """AD-963b: classify a Captain turn into one of three turn-order MODES so the
    fan-out can apply a mode-appropriate weighting + terminator. This is the named
    v1 HEURISTIC (and the swap seam for a v2 LLM classifier): DIRECTED wins (a
    leading callsign to a present participant — AD-951's next-speaker selection
    owns the dispatch); else BROADCAST (a plural ask to the whole room, via the
    shipped AD-963a ``classify_broadcast`` cue detector); else the default
    DISCUSSION. Pure + total: any non-directed, non-broadcast text is DISCUSSION
    (today's behavior), so the policy stays conservative."""
    if directed_callsign:
        return "directed"
    if classify_broadcast(text):
        return "broadcast"
    return "discussion"


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


async def _maybe_force_describe_frame(runtime: Any) -> None:
    """AD-978: describe the latest captured frame ONCE for a group round.

    The 1:1 DM path (routers/agents.py AD-733c-1) force-describes on every DM so
    the agent sees a fresh frame. A group round shares ONE camera frame across
    all speakers, and ``force_describe_current_frame`` writes the same
    observation to EVERY observer's working memory — so describing once here,
    before the parallel fan-out, freshens every agent's ring without N parallel
    describes of the same frame. Gated on ``perception.enabled`` +
    ``dm_force_describe_enabled`` (mirrors the 1:1 gate). Tier-2 honest-degrade:
    any failure logs at debug and the round proceeds with whatever the ambient
    describe last left in the rings.
    """
    try:
        _cfg = getattr(getattr(runtime, "config", None), "perception", None)
        if _cfg is None or not getattr(_cfg, "enabled", False):
            return
        _consumer = getattr(runtime, "vision_consumer", None)
        if _consumer is not None and getattr(_cfg, "dm_force_describe_enabled", True):
            try:
                await _consumer.force_describe_current_frame(timeout_s=4.0)
            except Exception:
                logger.debug("AD-978: force_describe raised; round proceeds", exc_info=True)
    except Exception:
        logger.debug("AD-978: force-describe gate failed", exc_info=True)


def _render_agent_scene_block(runtime: Any, agent_id: str) -> str:
    """AD-978: render ``agent_id``'s current visual context for prompt injection
    in the group fan-out, mirroring the 1:1 path (routers/agents.py AD-733a).

    Each agent owns a ``VisionWorkingMemory`` ring keyed by agent_id; the BF-294
    confabulation guard means ``render_for_prompt`` returns a non-empty "no
    visual data" sentinel when the ring is empty, so the agent is explicitly
    told not to invent a scene. Also notes per-agent DM activity (AD-733c-5) so
    the AMBIENT->ENGAGED transition tracks the room tempo for THIS agent without
    transitioning the whole mesh. Returns "" only when perception is disabled or
    rendering fails (Tier-2) — i.e. the block is injected whenever
    ``perception.enabled`` (which defaults False -> byte-identical when off),
    exactly like the 1:1 path.
    """
    try:
        _cfg = getattr(getattr(runtime, "config", None), "perception", None)
        if _cfg is None or not getattr(_cfg, "enabled", False):
            return ""
        # Per-agent engagement note (mirrors routers/agents.py AD-733c-5: a DM
        # to one agent must not transition the whole mesh).
        _mode_ctrl = getattr(runtime, "perception_mode_controller", None)
        _engagement = getattr(runtime, "perception_engagement_registry", None)
        if _engagement is not None:
            try:
                _per = _engagement.get(agent_id)
                if _per is not None:
                    _mode_ctrl = _per
            except Exception:
                logger.debug(
                    "AD-978: per-agent engagement lookup failed for %s",
                    agent_id, exc_info=True,
                )
        if _mode_ctrl is not None:
            try:
                _mode_ctrl.note_dm_activity()
            except Exception:
                logger.debug(
                    "AD-978: note_dm_activity raised for %s", agent_id, exc_info=True,
                )
        from probos.perception.consumer import get_or_create_working_memory
        _wm = get_or_create_working_memory(agent_id)
        # BF-617 / BF-620 / BF-624: a shared-camera room has ONE live feed, but
        # only registered ambient observers (vision_capable crew, e.g. the
        # counselor) get fresh frames fanned into their ring. A present
        # participant who is NOT an observer (e.g. the yeoman) renders whatever
        # is in its own ring — which is EMPTY after a restart (BF-620) OR a
        # STALE disk-hydrated frame (BF-624: the live "Yeo described a 22h-old
        # black shirt while Ezri saw the live plaid shirt" report — his ring
        # held an old frame so the BF-617 *empty-ring* fallback never fired and
        # he never refreshed). Fix: share the consumer's latest observation into
        # this agent's ring whenever it is FRESHER than the ring's own latest
        # (covers both empty and stale), so everyone in the room sees the same
        # current camera. Byte-identical for an up-to-date observer (the shared
        # obs is not newer than its own, so no append). Meeting-scoped (this
        # render path only); no register_observer, so no ambient cost.
        _consumer = getattr(runtime, "vision_consumer", None)
        _shared = (
            _consumer.latest_shared_observation()
            if _consumer is not None and hasattr(_consumer, "latest_shared_observation")
            else None
        )
        if _shared is not None:
            _own = _wm.latest()
            if _own is None or _shared.timestamp > _own.timestamp:
                _wm.append(_shared)
        # AD-1055: a stale (camera-off) frame renders as the no-data sentinel,
        # not a carried-over scene from a prior session.
        return _wm.render_for_prompt(
            freshness_s=getattr(_cfg, "prompt_freshness_seconds", None),
        ) or ""
    except Exception:
        logger.debug("AD-978: scene render failed for %s", agent_id, exc_info=True)
        return ""


async def _fan_one_round(
    runtime: Any,
    store: Any,
    thread_id: str,
    *,
    trigger_body: str,
    trigger_speaker: str = "",
    candidate_ids: list[str],
    exclude_ids: set[str],
    vision_messages: list[dict[str, Any]] | None,
    sanity_gate: Any,
    t_start: float,
    before: float | None = None,
    addressed_callsigns: set[str] | None = None,
    room_roster: list[str] | None = None,
    grounding_cue: str | None = None,
    broadcast: bool = False,
    max_speakers_override: int | None = None,
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
        facilitator = ChatFacilitator.from_config(
            getattr(runtime, "config", None),
            broadcast=broadcast,
            max_speakers_override=max_speakers_override,
        )
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
        # BF-651: saved-output manifest so a reviewer verifies against STORAGE,
        # not memory (crew read_file outputs/X.docx came back empty — artifacts
        # live in the ArtifactStore by name, not on disk). Honest-degrade to [].
        room_outputs: list[str] = []
        try:
            _arts = getattr(runtime, "artifact_store", None)
            if _arts is not None:
                room_outputs = [
                    f"{a.name} v{a.version} ({a.size_bytes} B)"
                    for a in _arts.list_thread_latest(thread_id)
                ][:20]
        except Exception:
            logger.debug("BF-651: outputs manifest build failed for %s", thread_id, exc_info=True)
        params: dict[str, Any] = {
            "text": trigger_body,
            "from": "hxi_profile",
            "session": bool(session_history),
            "session_history": session_history,
            # AD-935: teach the [NO_RESPONSE] decline option (group-only — the
            # cognitive_agent hook gates the teaching string on this param).
            "is_group_chat": True,
            "room_outputs": room_outputs,  # BF-651
        }
        # AD-978: prepend THIS agent's visual context (camera/screen) so the
        # crew can SEE in a group chat. The 1:1 path injects it (AD-733a) but the
        # group fan-out never did — that was the bug (camera feed invisible to
        # crew in group chat). Per-agent ring keyed by agent_id; the shared frame
        # was force-described ONCE for this round above. Empty ring -> BF-294 "no
        # visual data" sentinel (the agent is told NOT to confabulate), so this
        # is gated only on perception.enabled exactly like the 1:1 path. Override
        # params["text"] (what the LLM receives); trigger_body stays clean for
        # the episode/pipeline so the stored episode records the Captain's actual
        # message, not the ephemeral scene.
        _scene_block = _render_agent_scene_block(runtime, agent_id)
        if _scene_block:
            params["text"] = f"{_scene_block}\n\n{trigger_body}"
        # AD-967: present-participant roster so the dispatched agent knows WHO is
        # in the room (the cognitive_agent group hook renders it). Fixes agents
        # addressing a peer who was never invited (the Sentinel/Vance bug). Rides
        # the same params dict as is_group_chat; omitted when empty.
        if room_roster:
            params["room_roster"] = room_roster
        # AD-1120: honest-absence cue for an unresolved CENTRAL room referent.
        # Rides the same params dict as room_roster (AD-967); omitted when None
        # (default-OFF / resolved / ineligible) so the fan-out is byte-identical.
        if grounding_cue:
            params["grounding_cue"] = grounding_cue
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
        async def _dispatch_intent() -> tuple[Any, str]:
            """BF-636: one send attempt -> (result, cleaned_text). An empty/None
            result OR a delivery exception yields text="" — NOT a visible
            "(no response)"/"(delivery failed)" placeholder — so the _declined
            check below thins it exactly like a [NO_RESPONSE] decline. A transient
            LLM failure (proxy timeout / echo / overload) therefore never gets
            persisted into the transcript as a fake agent reply."""
            try:
                res = await runtime.intent_bus.send(intent)
            except Exception as exc:
                logger.warning(
                    "AD-914 fan-out send failed for %s: %s: %s; other recipients unaffected",
                    agent_id, type(exc).__name__, exc,
                )
                return None, ""
            txt = str(res.result) if (res and res.result) else ""
            # BF-622: a degraded LLM proxy can echo its INPUT (the AD-978 scene
            # block) back as the completion. Strip any visual-context scaffolding
            # so internal context never surfaces; an only-echo reply degrades to
            # "" (thinned below, not a visible placeholder).
            if txt and "Current Visual Context" in txt:
                from probos.perception.working_memory import strip_visual_context_block
                txt = strip_visual_context_block(txt) or ""
            return res, txt

        result, reply_text = await _dispatch_intent()
        # BF-636: an EMPTY result is a transient LLM failure, NOT a reply. For an
        # explicitly ADDRESSED (hard-included) agent — the peer a prior speaker or
        # the Captain named (AD-951) — retry ONCE before giving up; un-addressed
        # agents are thinned immediately so a whole-room failure never doubles the
        # load on an already-struggling proxy. Either way an empty reply falls to
        # the _declined thinning below and is never shown as "(no response)".
        _is_addressed = bool(
            addressed_callsigns and callsign and callsign.lower() in addressed_callsigns
        )
        if not reply_text.strip() and _is_addressed:
            result, reply_text = await _dispatch_intent()
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
        # BF-616: detect the [NO_RESPONSE] token ANYWHERE (case-insensitive),
        # not just when the reply is EXACTLY the marker. Models frequently
        # explain their decline in prose and then append [NO_RESPONSE] instead
        # of emitting the bare marker the prompt asks for; the old equality
        # check let "prose + [NO_RESPONSE]" through, leaking the marker into the
        # visible transcript. Matching the established proactive.py contract
        # (``"[NO_RESPONSE]" in response_text``), any decline marker suppresses
        # the whole reply — a human who decides not to respond says nothing.
        _declined = bool(_NO_RESPONSE_RE.search(reply_text)) or not reply_text.strip()
        if _declined:
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

    # AD-978: freshen every observer agent's visual working memory ONCE before
    # the parallel dispatch (shared camera frame -> one describe, not one per
    # agent). No-op + cheap when perception is disabled (the default).
    await _maybe_force_describe_frame(runtime)
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
        # AD-986a/AD-987: group-episode enrichment + visual binding, both default-off
        # (byte-identical group episodes until enabled in config).
        _mem_cfg = getattr(getattr(runtime, "config", None), "memory", None)
        _enrich = bool(getattr(_mem_cfg, "group_episode_enrichment_enabled", False))
        _refl_cap = int(getattr(_mem_cfg, "group_reflection_max_chars", 600)) if _enrich else 240
        _bind_visual = bool(getattr(_mem_cfg, "episode_visual_binding_enabled", False))
        # AD-986a: the trigger is the Captain turn (round 0) or the prior round's
        # joined agent messages (cascade rounds, which already carry per-line
        # "callsign: text" labels). When enrichment is on, label the round-0 Captain
        # trigger explicitly so "who said what" survives recall; cascade triggers
        # (trigger_speaker="") are left as-is since their labels are already embedded.
        if _enrich and trigger_speaker:
            episode_input = f"[group chat] {trigger_speaker}: {trigger_body[:200]}"
        else:
            episode_input = f"[group chat] {trigger_body[:200]}"
        _trigger_agent = trigger_speaker if _enrich else ""
        _sentinels = {"(no response)", "(delivery failed)", ""}
        for reply in replies:
            if not reply["agent_id"] or reply["text"] in _sentinels:
                continue
            try:
                # AD-987: bind the frame the replying agent saw at capture so the
                # conversational episode and its visual co-occurrence become ONE
                # memory. The ref is a content-addressable AttachmentStore SHA, so it
                # survives the VisionWorkingMemory ring's TTL reap. Tier-2: a binding
                # failure must never block the episode write.
                _visual_ref = ""
                _visual_desc = ""
                if _bind_visual:
                    try:
                        from probos.perception.consumer import (
                            get_or_create_working_memory,
                        )
                        _obs = get_or_create_working_memory(reply["agent_id"]).latest()
                        if _obs is not None and getattr(_obs, "attachment_ref", ""):
                            _visual_ref = _obs.attachment_ref
                            _visual_desc = getattr(_obs, "description", "") or ""
                    except Exception:
                        logger.debug(
                            "AD-987: visual binding skipped for %s",
                            reply["callsign"] or reply["agent_id"], exc_info=True,
                        )
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
                    # AD-977/AD-986a: index the agent's OWN reply so it can recall what
                    # it said in the room. The embedded document (_prepare_document)
                    # and the FTS5 sidecar index user_input + reflection, but NOT
                    # outcomes[].response — so without this the group episode was
                    # findable only by the Captain's trigger text, never by the
                    # agent's contribution (the group-vs-1:1 recall gap). AD-986a
                    # raises the cap from 240 to ``_refl_cap`` when enrichment is on so
                    # a substantive multi-paragraph reply is findable by its payload,
                    # not just its opening. Mirrors the 1:1 _store_action_episode
                    # reflection ("<callsign> handled <intent>: <response>").
                    reflection=(
                        f"{reply['callsign'] or reply['agent_id']} said in group chat: "
                        f"{reply['text'][:_refl_cap]}"
                    ),
                    source="group_chat_fanout",  # AD-933a distinct tag
                    anchors=AnchorFrame(
                        channel="chat",
                        trigger_type="group_fanout",
                        participants=participants,
                        trigger_agent=_trigger_agent,  # AD-986a: who drove this turn
                        chat_thread_id=thread_id,
                        visual_attachment_ref=_visual_ref,  # AD-987
                        visual_description=_visual_desc,     # AD-987
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


def _record_conversation_trust(
    runtime: Any,
    thread: Any,
    all_replies: list[dict[str, str]],
    agent_ids: list[str],
) -> None:
    """AD-958 (epic #882, #894): credit a CONVERGENT conversation as bounded
    positive trust.

    Default-OFF: when the master flag ``group_chat.conversation_trust_enabled``
    is False (the default), this returns on the first line so the trust network
    stays byte-identical to the pre-AD-958 fan-out. When ON, build the pure
    AD-915 facilitator + the AD-958 extractor, then record one positive per
    corroborated contributor — each credited by a DISTINCT peer (no
    self-sourcing). Honest-degrade Tier-2: any extract or record failure logs
    and returns; the fan-out result is never touched.
    """
    cfg = getattr(getattr(runtime, "config", None), "group_chat", None)
    if not getattr(cfg, "conversation_trust_enabled", False):
        return
    tn = getattr(runtime, "trust_network", None)
    if tn is None or not hasattr(tn, "record_outcome"):
        return
    try:
        facilitator = ChatFacilitator.from_config(runtime.config)
        topic = conversation_topic_tag(getattr(thread, "title", "") or "")
        outcomes = extract_conversation_trust_outcomes(
            all_replies,
            facilitator=facilitator,
            intent_type=topic,
            positive_weight=getattr(cfg, "conversation_trust_positive_weight", 0.05),
            max_outcomes=getattr(cfg, "conversation_trust_max_outcomes", 4),
            convergence_window=_CONVERGENCE_WINDOW,
        )
    except Exception:
        logger.warning(
            "AD-958: conversation-trust extract failed for thread=%s; skipping "
            "(fan-out result unaffected)",
            getattr(thread, "id", "?"), exc_info=True,
        )
        return
    for o in outcomes:
        try:
            tn.record_outcome(
                o.agent_id,
                success=o.success,
                weight=o.weight,
                intent_type=o.intent_type,
                episode_id="",
                verifier_id=o.verifier_id,
                source="conversation",
            )
        except Exception:
            logger.warning(
                "AD-958: conversation-trust record_outcome failed for agent=%s; "
                "continuing with the remaining outcomes",
                o.agent_id, exc_info=True,
            )
            continue


def _observe_conversation_corrections(
    runtime: Any,
    thread: Any,
    all_replies: list[dict[str, str]],
    agent_ids: list[str],
) -> None:
    """AD-958c (#882, #894): DETECT-AND-OBSERVE peer-corrects-peer signals.

    Default-OFF: when ``group_chat.conversation_trust_correction_observe_enabled``
    is False (default), returns on the first line so the fan-out is
    byte-identical. When ON, run the pure AD-958c detector and emit one
    structured INFO log per detected correction. OBSERVE-ONLY: writes NOTHING to
    the trust network (the negative ``record_outcome`` is deferred to AD-958d).
    Tier-2 honest-degrade: any failure logs a warning and returns.
    """
    cfg = getattr(getattr(runtime, "config", None), "group_chat", None)
    if not getattr(cfg, "conversation_trust_correction_observe_enabled", False):
        return
    try:
        topic = conversation_topic_tag(getattr(thread, "title", "") or "")
        signals = detect_conversation_corrections(
            all_replies,
            intent_type=topic,
            max_signals=getattr(cfg, "conversation_trust_max_outcomes", 4),
        )
    except Exception:
        logger.warning(
            "AD-958c: correction observe failed for thread=%s; skipping "
            "(fan-out result unaffected)",
            getattr(thread, "id", "?"), exc_info=True,
        )
        return
    for s in signals:
        logger.info(
            "AD-958c[observe]: peer-correction detected thread=%s corrector=%s "
            "corrected=%s cue=%r topic=%s (observe-only, NO trust write)",
            getattr(thread, "id", "?"), s.corrector_id, s.corrected_agent_id,
            s.cue, s.intent_type,
        )


async def _observe_referent_grounding(
    runtime: Any,
    thread: Any,
    seed_text: str,
) -> str | None:
    """AD-1119/AD-1120 (#1022/#1023): ground the room seed's referents and,
    when AD-1120 is enabled, RETURN the honest-absence cue for the CENTRAL one.

    ``seed_text`` is the Captain's current-turn text — the input the crew reasons
    on, at the fan-out choke point where a cascade-confabulation begins. When a
    central referent (a git object, an agent, a ward-room channel) cannot be
    resolved, the crew is at risk of building an investigation on a fabricated id
    (the live ``e77acec7`` case).

    Default-OFF: when ``grounding.referent_gate_enabled`` is False (default),
    returns ``None`` on the first line so the fan-out is byte-identical — NO gate
    is built and NO git subprocess runs (the AD-1119 ``test_observe_off_is_noop``
    contract). When ON, build the gate from the runtime's narrow deps, evaluate
    the seed, and emit one structured WARNING per actionable unresolved referent.

    AD-1120 (behavioral half): when
    ``grounding.ground_before_collaborate_enabled`` is ALSO True, select the
    CENTRAL unresolved referent (DD-1120-2/3) and RETURN its ``is_capability_gap``
    -clean cue so the fan-out injects it into each dispatched crew agent's
    context. When that flag is off (default) this returns ``None`` after the
    observe log — the two-flag dependency — so both AD-1119 (observe-only) and
    the injection path stay byte-identical. Tier-2 honest-degrade: any failure
    logs a warning and returns ``None`` (no injection).
    """
    cfg = getattr(getattr(runtime, "config", None), "grounding", None)
    if not getattr(cfg, "referent_gate_enabled", False):
        return None
    try:
        gate = ReferentGroundingGate(
            build_default_resolvers(
                registry=getattr(runtime, "registry", None),
                callsign_registry=getattr(runtime, "callsign_registry", None),
                ward_room=getattr(runtime, "ward_room", None),
            )
        )
        verdict = await gate.evaluate(seed_text or "")
    except Exception:
        logger.warning(
            "AD-1119: referent grounding observe failed for thread=%s; skipping "
            "(fan-out result unaffected)",
            getattr(thread, "id", "?"), exc_info=True,
        )
        return None
    # AD-1120/AD-1121: compute the central token at most once, only when either
    # behavioral half is enabled. Reuse it for warning disposition, probe
    # scheduling, and the cue return.
    probe_on = getattr(cfg, "confab_probe_enabled", False)
    b2_on = getattr(cfg, "ground_before_collaborate_enabled", False)
    central_token = None
    if probe_on or b2_on:
        central_token = await _select_central_referent(verdict, seed_text or "")
    for token in verdict.unresolved:
        logger.warning(
            "AD-1119[observe]: unresolved referent thread=%s token=%r cue=%r "
            "central=%s ground_before_collaborate=%s confab_probe=%s",
            getattr(thread, "id", "?"), token, verdict.cues.get(token, ""),
            token == central_token, b2_on, probe_on,
        )
    if not (probe_on or b2_on):
        return None
    if probe_on and central_token is not None:
        # AD-1121: schedule the context-free divergence probe as a BEST-EFFORT
        # background task (non-blocking) so it never delays the crew reply. The
        # public runtime scheduler atomically owns both shutdown admission and
        # task registration; this router never reads a private lifecycle flag.
        try:
            task = runtime.schedule_confab_probe(
                lambda: _probe_cascade_confab(runtime, thread, central_token),
                name=f"confab-probe:{getattr(thread, 'id', '?')}:{central_token}",
            )
            if task is None:
                logger.debug(
                    "BF-663: confab probe scheduling closed for thread=%s "
                    "token=%r; probe refused during shutdown",
                    getattr(thread, "id", "?"), central_token,
                )
        except AttributeError:
            # The promoted scheduler is a stable production runtime contract.
            # A malformed runtime must fail loudly rather than silently skip
            # the lifecycle safety seam.
            raise
        except Exception:
            logger.warning(
                "AD-1121: failed to schedule confab probe for thread=%s token=%r; "
                "skipping (fan-out result unaffected)",
                getattr(thread, "id", "?"), central_token, exc_info=True,
            )
    if not b2_on:
        return None
    return verdict.cues.get(central_token) if central_token is not None else None


async def _select_central_referent(verdict: Any, seed_text: str) -> str | None:
    """AD-1120/AD-1121: the CENTRAL unresolved referent TOKEN, or None.

    The token-selection half of the former ``_select_central_cue`` (kind /
    stop-word filter + the ONE git-HEAD availability probe for a hex). AD-1120
    maps the returned token to ``verdict.cues[token]`` (the injected honest-absence
    cue); AD-1121 feeds the token to the context-free divergence probe. Selection
    (DD-1120-2/3): re-extract referents (pure — NOT a re-resolve; the git
    subprocesses live in ``evaluate``) for their kinds, keep the first actionable
    unresolved token (seed-appearance order) whose kind is injectable
    (hex/entity), and — for a hex — only when git is actually available
    (DD-1120-3, so a git-less deploy does not falsely flag every hex).
    Returns the token verbatim or ``None`` when nothing qualifies. Tier-2
    honest-degrade: any failure returns ``None``.
    """
    try:
        kinds = {r.token: r.kind for r in extract_referents(seed_text)}
    except Exception:
        logger.warning(
            "AD-1120: referent re-extract failed; skipping central-token selection",
            exc_info=True,
        )
        return None
    # Candidate tokens in seed order, kind-filtered. BF-667 source grammar is the
    # single assertion authority; no downstream conceptual/stop-word heuristic.
    candidates = [
        t
        for t in verdict.unresolved
        if kinds.get(t) in _GROUNDING_INJECT_KINDS
    ]
    if not candidates:
        return None
    # DD-1120-3: probe git availability ONCE, only when a hex candidate exists —
    # a git-less deploy reads every hex as UNRESOLVED, which would falsely tell
    # the crew every hex id is fabricated. ``GitObjectResolver().resolve("HEAD")``
    # reuses the shipped resolver as a positive control (no referent_gate.py edit).
    git_ok = True
    if any(kinds.get(t) == "hex" for t in candidates):
        try:
            git_ok = await GitObjectResolver().resolve("HEAD")
        except Exception:
            logger.warning(
                "AD-1120: git availability probe failed; treating git as "
                "unavailable (hex tokens skipped)",
                exc_info=True,
            )
            git_ok = False
    for t in candidates:
        if kinds.get(t) == "hex" and not git_ok:
            continue
        return t
    return None


async def _probe_cascade_confab(runtime: Any, thread: Any, token: str) -> None:
    """AD-1121: context-free divergence probe on an UNRESOLVED central referent.

    Best-effort. On a divergence verdict: record a CASCADE_CONFAB observation
    (via the AD-454 collector, if wired) and notify the Captain (always). NEVER
    raises out (scheduled fire-and-forget); NEVER auto-acts on the room.
    """
    try:
        llm = getattr(runtime, "llm_client", None)
        if llm is None:
            return
        result = await probe_referent(llm, token)
        if not result.is_divergent:
            return
        room_title = getattr(thread, "title", "") or ""
        thread_id = getattr(thread, "id", "") or ""
        sample_digest = " | ".join(
            s.strip().replace("\n", " ") for s in result.samples
        )
        if len(sample_digest) > 600:
            sample_digest = sample_digest[:600] + "…"
        reasoning = (
            f"AD-1121 divergence probe: referent '{token}' is unresolved by ship "
            f"ground truth and independent context-free samples failed to affirm "
            f"its existence ({result.affirm}/{result.usable} affirmed). Possible "
            f"cascade confabulation. Samples: {sample_digest}"
        )
        logger.info(
            "AD-1121: divergence flagged thread=%s token=%r affirm=%d usable=%d "
            "(recording observation + notifying Captain)",
            thread_id, token, result.affirm, result.usable,
        )
        # (1) Record a CASCADE_CONFAB observation via the AD-454 taxonomy pipeline.
        # Skip when the collector is disabled (its default) — honest-degrade; the
        # notification still fires.
        collector = getattr(runtime, "evidence_collector", None)
        if collector is not None:
            try:
                await collector.record_observation(
                    behavior_code=BehaviorCode.CASCADE_CONFAB,
                    thread_id=thread_id,
                    author_id=thread_id,
                    author_callsign="confab-probe",
                    reasoning=reasoning,
                    confidence=round(1.0 - result.affirm_rate, 3),
                )
            except Exception:
                logger.warning(
                    "AD-1121: failed to record CASCADE_CONFAB observation for "
                    "thread=%s token=%r (notification still fires)",
                    thread_id, token, exc_info=True,
                )
        # (2) Notify the Captain — ALWAYS fires (surface, don't act). No
        # suggested_action: the divergence verdict is a signal for human
        # adjudication, never an auto-terminate / room-close gate.
        nq = getattr(runtime, "notification_queue", None)
        if nq is not None:
            try:
                nq.notify(
                    agent_id="confab-probe",
                    agent_type="utility",
                    department="science",
                    title=f"Possible confabulation cascade: '{token}'",
                    detail=(
                        f"The referent '{token}' at the centre of room "
                        f"\"{room_title}\" cannot be resolved against ship ground "
                        f"truth, and {result.usable - result.affirm} of "
                        f"{result.usable} independent context-free checks found no "
                        f"record of it. Recommend reviewing this room before the "
                        f"crew builds further findings on it."
                    ),
                    notification_type="action_required",
                )
            except Exception:
                logger.warning(
                    "AD-1121: failed to notify Captain for thread=%s token=%r",
                    thread_id, token, exc_info=True,
                )
    except Exception:
        logger.warning(
            "AD-1121: cascade-confab probe wiring raised for thread=%s token=%r; "
            "skipping (best-effort, no room action)",
            getattr(thread, "id", "?"), token, exc_info=True,
        )


async def group_chat_fanout(
    runtime: Any,
    thread_id: str,
    *,
    captain_body: str,
    captain_msg: Any,
    opener_id: str | None = None,
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
    # AD-1119/AD-1120 (#1022/#1023): referent-grounding gate on the room seed —
    # resolve each candidate referent (git object / agent / ward-room channel)
    # before the crew reasons on it, logging an honest-absence cue for the
    # unresolved ones (AD-1119, observe-only). AD-1120 (both flags on) RETURNS the
    # central unresolved referent's cue so the fan-out injects it into each
    # dispatched agent's context via the AD-967 param path. Default-OFF (None) →
    # byte-identical.
    grounding_cue = await _observe_referent_grounding(runtime, thread, captain_body)
    # AD-967: build the present-participant roster ONCE (stable across rounds):
    # crew callsigns + "the Captain" when the Captain has joined. Each dispatched
    # agent receives it so it addresses only present members and asks the Captain
    # to add anyone else (fixes the absent-peer address bug). Tier-2: a missing
    # callsign falls back to the agent_id.
    _roster_callsigns = _resolve_callsigns(runtime, agent_ids)
    room_roster = [_roster_callsigns.get(a) or a for a in agent_ids]
    if "captain" in (thread.participants or []):
        room_roster.append("the Captain")
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
    # AD-970: an agent-initiated kickoff passes opener_id so the opener is
    # excluded from round 0 (it just spoke); a Captain turn excludes nobody.
    all_replies: list[dict[str, str]] = []
    # AD-963b: hoist the turn-mode policy ABOVE round 0 so the department-dominant
    # weight tilt reaches round 0 — the round that decides who FRAMES the topic
    # first. ``cfg`` is reused by the AD-935 cascade below (the duplicate read was
    # removed). With the master flag OFF (default) ``turn_mode`` stays None and
    # ``broadcast_weights`` stays False => byte-identical AD-963a (standard
    # weights; the terminator keys off the shipped ``classify_broadcast``).
    # Honest-degrade: ``classify_turn_mode`` is pure + total, so a classification
    # can never abort the fan-out.
    cfg = getattr(getattr(runtime, "config", None), "group_chat", None)
    policy_on = bool(getattr(cfg, "turn_mode_policy_enabled", False))
    turn_mode: str | None = None
    if policy_on:
        _leading = extract_directed_callsign(captain_body or "")
        _participant_cs = {c.lower() for c in _roster_callsigns.values() if c}
        _directed = _leading if (_leading and _leading in _participant_cs) else None
        turn_mode = classify_turn_mode(captain_body, directed_callsign=_directed)
    broadcast_weights = policy_on and turn_mode == "broadcast"
    # AD-956 (Natural Conversation epic #882): scale-aware facilitation. When the
    # master flag is ON, classify the room by participant count: a small room
    # (2-4, below the ratified threshold of 5) widens to ADVISORY — the per-turn
    # cap is turned OFF (override=0) so every relevant crew member may answer,
    # still convergence-gated, [NO_RESPONSE]-thinned, and max_agent_rounds-bounded
    # (the participant count is the per-round ceiling; advisory only fires for
    # 2-4-voice rooms => <= 4 parallel/round). A large room (>= threshold) stays
    # GATING (override=None) so the configured cap throttles the fan-out. Flag OFF
    # (default) => the classifier never runs, override stays None, and every round
    # uses ``max_speakers_per_turn`` EXACTLY as today (byte-identical). The widening
    # raises NEITHER ``max_agent_rounds`` NOR bypasses the convergence gate — only
    # the per-round cap. Honest-degrade: any classify failure falls back to today's
    # gating cap (override=None) and never aborts the fan-out.
    _speakers_override: int | None = None
    if bool(getattr(cfg, "scale_aware_facilitation_enabled", False)):
        try:
            _mode = facilitation_mode(
                len(agent_ids),
                threshold=int(getattr(cfg, "facilitation_gate_threshold", 5)),
                force_min=int(getattr(cfg, "force_facilitation_min", 0)),
            )
            if _mode == "advisory":
                _speakers_override = 0
        except Exception:
            logger.warning(
                "AD-956: facilitation-mode classify failed for thread=%s (n=%d); "
                "falling back to the configured gating cap",
                thread_id, len(agent_ids), exc_info=True,
            )
            _speakers_override = None
    round0 = await _fan_one_round(
        runtime, store, thread_id,
        trigger_body=captain_body, trigger_speaker="Captain", candidate_ids=agent_ids,
        exclude_ids=({opener_id} if opener_id else set()),
        vision_messages=vision_messages, sanity_gate=sanity_gate, t_start=t_start,
        before=captain_msg.created_at,
        room_roster=room_roster,
        grounding_cue=grounding_cue,
        broadcast=broadcast_weights,
        max_speakers_override=_speakers_override,
    )
    all_replies.extend(round0)

    # AD-935: bounded synchronous agent-to-agent cascade. Each extra round fans
    # the PREVIOUS round's new agent messages to the OTHER crew (excluding that
    # round's speakers — an agent never reacts to its own message), gated by the
    # AD-915 convergence gate, [NO_RESPONSE] declines, and the round cap. The
    # cap is the hard backstop; the convergence gate is the semantic terminator
    # (it returns an empty speaking_order once the exchange converges). Default
    # OFF -> the loop is skipped -> round 0 is byte-identical to AD-914.
    # AD-963b: ``cfg`` is now resolved above round 0 (the turn-mode hoist) and
    # reused here; the duplicate read was removed.
    if getattr(cfg, "agent_reactivity_enabled", False):
        max_rounds = int(getattr(cfg, "max_agent_rounds", 2))
        next_speaker_sel = getattr(cfg, "agent_next_speaker_selection_enabled", False)
        # AD-961: cascade-extend-on-address. Past the normal max_rounds cap, an
        # unanswered directed address ("Ezri, ...") earns up to this many EXTRA
        # rounds so a hand-off is always answered — bounded so mutual hand-offs
        # can't ping-pong forever. Only meaningful with next-speaker selection on.
        max_addr_ext = int(getattr(cfg, "max_address_extensions", 1)) if next_speaker_sel else 0
        # AD-961: lower-cased callsign -> agent_id, so the extension decision can
        # tell a REAL directed address (to a participant who can answer) from a
        # false vocative opener ("Agreed," / "Well,") that extract_directed_callsign
        # also matches. Built once; Tier-2 empty => no extension ever fires.
        _callsign_to_agent: dict[str, str] = {}
        if max_addr_ext > 0:
            for _aid, _cs in _resolve_callsigns(runtime, agent_ids).items():
                if _cs:
                    _callsign_to_agent[_cs.lower()] = _aid
        # AD-963a: broadcast turn-mode. A plural ask to the whole room ("what do
        # you all think?") round-robins every crew participant ONCE instead of the
        # discussion cap + convergence terminator. Gated (ships OFF; yaml flips
        # on); a non-broadcast turn (the default classification) is byte-identical
        # to AD-935/961.
        # AD-963b: when the turn-mode policy is on, the terminator keys off the
        # hoisted ``turn_mode`` (so directed/discussion turns never round-robin even
        # with a broadcast cue present); when off, it keys off the shipped AD-963a
        # ``classify_broadcast`` (byte-identical).
        broadcast_mode = (
            getattr(cfg, "broadcast_terminator_enabled", False)
            and ((turn_mode == "broadcast") if policy_on else classify_broadcast(captain_body))
        )
        # AD-963a: cumulative set of EVERY agent who has spoken. Broadcast mode
        # excludes them ALL each round so each speaks exactly once; discussion
        # mode excludes only the last round's speakers (preserving the AD-935
        # back-and-forth). Seeded with round 0's speakers.
        broadcast_spoke: set[str] = (
            {r["agent_id"] for r in round0 if r.get("agent_id")} if broadcast_mode else set()
        )
        last = round0
        rounds_done = 0
        addr_ext_used = 0
        while True:
            spoke_ids = {r["agent_id"] for r in last if r.get("agent_id")}
            if not spoke_ids:
                break  # nothing new to react to
            # AD-951 + BF-619: turn-allocation rule 1a — when a prior-round
            # speaker ADDRESSES a peer by callsign, select that peer to speak
            # next (hard-included past the per-turn cap + convergence, still
            # bounded by the round budget). BF-619: use extract_handoff_callsign
            # so an END-of-turn hand-off ("... Yeo, your read?" / "what do you
            # think, Yeo?") is detected, not just a LEADING address — natural
            # conversation hands off at the end of a turn, and the leading-only
            # AD-951 matcher missed it (an agent's question went unanswered).
            # Scan each reply's CLEAN text (AD-948 already stripped the <intent>
            # tag); a speaker never selects itself. Honest-degrade: a
            # non-participant callsign matches no candidate downstream. Gated
            # (ships OFF; yaml flips on).
            addressed: set[str] = set()
            if next_speaker_sel:
                for r in last:
                    cs = extract_handoff_callsign(r.get("text") or "")
                    if cs and cs != (r.get("callsign") or "").lower():
                        addressed.add(cs)
            # AD-961: budget gate. Within the normal cap, always continue (AD-935
            # byte-identical). PAST the cap, continue ONLY for an address to a
            # REAL participant who hasn't just spoken (a peer who can take the
            # turn) — never a false vocative opener — and only while extension
            # budget remains. Each such round consumes one extension.
            # AD-963a: broadcast mode round-robins every crew participant once,
            # bounded by the participant count (naturally finite) — it bypasses
            # the discussion cap + the AD-961 address-extension budget. Discussion
            # mode is unchanged.
            if broadcast_mode:
                if len(broadcast_spoke) >= len(agent_ids):
                    break  # every crew participant has spoken once
            elif rounds_done >= max_rounds:
                _answerable = any(
                    _callsign_to_agent.get(cs) is not None
                    and _callsign_to_agent.get(cs) not in spoke_ids
                    for cs in addressed
                )
                if not (_answerable and addr_ext_used < max_addr_ext):
                    break
                addr_ext_used += 1
            trigger = "\n".join(
                f"{r['callsign'] or r['agent_id']}: {r['text']}" for r in last
            )
            # AD-963a: exclude EVERY prior speaker in broadcast (round-robin, once
            # each); discussion excludes only the last round's speakers.
            _exclude = broadcast_spoke if broadcast_mode else spoke_ids
            try:
                nxt = await _fan_one_round(
                    runtime, store, thread_id,
                    trigger_body=trigger, trigger_speaker="", candidate_ids=agent_ids,
                    exclude_ids=_exclude,
                    vision_messages=None, sanity_gate=sanity_gate, t_start=t_start,
                    addressed_callsigns=addressed or None,
                    room_roster=room_roster,
                    grounding_cue=grounding_cue,
                    broadcast=broadcast_weights,
                    max_speakers_override=_speakers_override,
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
            if broadcast_mode:
                broadcast_spoke |= {r["agent_id"] for r in nxt if r.get("agent_id")}
            rounds_done += 1
    _record_conversation_trust(runtime, thread, all_replies, agent_ids)
    _observe_conversation_corrections(runtime, thread, all_replies, agent_ids)
    return all_replies
