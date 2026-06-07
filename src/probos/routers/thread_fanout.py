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
from typing import Any

from probos.crew_utils import is_crew_agent
from probos.types import IntentMessage

logger = logging.getLogger(__name__)

# AD-914: recent-history window injected into each agent's prompt. Module
# constant — NOT config (zero-config boot). Bounds prompt size.
_FANOUT_HISTORY_LIMIT = 20


def crew_agent_participants(runtime: Any, participants: list[str]) -> list[str]:
    """Participant agent_ids that resolve to crew agents (Captain/non-crew excluded)."""
    out: list[str] = []
    for pid in participants:
        agent = runtime.registry.get(pid)
        if agent is not None and is_crew_agent(agent, getattr(runtime, "ontology", None)):
            out.append(pid)
    return out


def _build_session_history(
    runtime: Any, store: Any, thread_id: str, before: float
) -> list[dict[str, str]]:
    """Recent thread turns (excluding the just-appended Captain msg) as
    ``{"role": <callsign|Captain|system>, "text": body}`` entries.

    ``list_messages`` is ``ORDER BY created_at ASC LIMIT ?`` — a bare limit
    returns the OLDEST N, so fetch the store max and tail-slice to the most
    recent window. Tier-2: callsign-label resolution failures degrade to the
    raw stored role.
    """
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
    session_history = _build_session_history(runtime, store, thread_id, captain_msg.created_at)

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

    replies = await asyncio.gather(*[_send_one(a) for a in agent_ids])
    return list(replies)
