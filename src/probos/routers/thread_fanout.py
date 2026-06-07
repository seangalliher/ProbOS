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

    async def _send_one(agent_id: str) -> dict[str, str]:
        callsign = ""
        try:
            agent = runtime.registry.get(agent_id)
            if agent is not None and hasattr(runtime, "callsign_registry"):
                callsign = runtime.callsign_registry.get_callsign(agent.agent_type) or ""
        except Exception:
            logger.debug("AD-914: callsign resolve failed for %s", agent_id, exc_info=True)
        intent = IntentMessage(
            intent="direct_message",
            params={
                "text": captain_body,
                "from": "hxi_profile",
                "session": bool(session_history),
                "session_history": session_history,
            },
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
