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
from typing import Any

from probos.cognitive.chat_facilitator import ChatFacilitator, SpeakerSignals
from probos.cognitive.similarity import jaccard_similarity, text_to_words
from probos.crew_profile import extract_all_leading_callsign_mentions
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
    runtime: Any, captain_body: str, agent_ids: list[str], prior: list[Any]
) -> list[SpeakerSignals]:
    """Build per-speaker SpeakerSignals snapshots from the runtime. Every
    lookup is Tier-2 log-and-degrade (mirrors group_chat_fanout): a missing
    registry/callsign/ontology/trust never blocks facilitation.
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
        mentioned = bool(callsign) and callsign.lower() in mention_callsigns
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


async def group_chat_fanout(
    runtime: Any,
    thread_id: str,
    *,
    captain_body: str,
    captain_msg: Any,
) -> list[dict[str, str]]:
    """Fan the Captain turn out to all crew-agent participants in parallel.

    Returns a list of ``{"agent_id", "callsign", "text"}`` dicts (one per
    dispatched agent). Persists each reply as a role="agent" message.
    Assumes the caller already verified ``role == "captain"`` AND >= 2 crew
    participants. Per-agent dispatch is Tier-2 log-and-degrade: one agent's
    failure never blocks the others.
    """
    store = runtime.chat_thread_store
    thread = store.get_thread(thread_id)
    if thread is None:
        return []
    agent_ids = crew_agent_participants(runtime, thread.participants)
    # AD-915: single-read DRY — fetch the prior window once and reuse it for
    # history injection, recency, and the convergence gate.
    prior = store.list_messages(thread_id, limit=1000, before=captain_msg.created_at)
    session_history = _build_session_history(
        runtime, store, thread_id, captain_msg.created_at, prior=prior
    )
    # AD-915: facilitator decides WHO/ORDER; AD-914's _send_one still does the
    # dispatch+persist (DRY). Tier-2: any facilitation failure degrades to the
    # AD-914 all-at-once order so a facilitator bug never silences the crew.
    try:
        facilitator = ChatFacilitator.from_config(getattr(runtime, "config", None))
        signals = _assemble_speaker_signals(runtime, captain_body, agent_ids, prior)
        recent_agent_msgs = [
            (m.author_id, m.body) for m in prior[-_CONVERGENCE_WINDOW:] if m.role == "agent"
        ]
        result = facilitator.facilitate(signals, recent_agent_msgs)
        speaking_order = result.speaking_order
    except Exception:
        logger.warning(
            "AD-915: facilitation failed for thread=%s; falling back to AD-914 order",
            thread_id, exc_info=True,
        )
        speaking_order = list(agent_ids)

    # AD-916: build the group vision array once from the Captain message's
    # persisted attachment refs. None => no image refs => AD-914 text-only.
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
            "text": captain_body,
            "from": "hxi_profile",
            "session": bool(session_history),
            "session_history": session_history,
        }
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
        try:
            store.append_message(
                thread_id, author_id=agent_id, role="agent",
                body=reply_text, metadata={"intent_id": intent.id, "fanout": "ad914"},
            )
        except Exception:
            logger.warning(
                "AD-914: persist reply failed for thread=%s agent=%s",
                thread_id, agent_id, exc_info=True,
            )
        return {"agent_id": agent_id, "callsign": callsign, "text": reply_text}

    replies = await asyncio.gather(*[_send_one(a) for a in speaking_order])
    return list(replies)
