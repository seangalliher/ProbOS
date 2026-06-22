"""AD-958 (Natural Conversation epic #882, #894): pure conversational-trust
extraction.

A convergent group conversation is corroboration. When several crew members
talk a topic through and CONVERGE (the AD-915 facilitator's pure convergence
test), each contributing voice has been validated by its peers. This module
turns that convergence into a bounded set of POSITIVE trust observations — one
per distinct contributor, each CREDITED BY A DIFFERENT PEER, so a subject can
never raise its own trust (the anti-gaming rule). The heavier negative path
(peer-corrects-peer) is reserved for AD-958c and is intentionally not derived
here.

Pure: no I/O, no LLM, no consensus import. The impure caller
(``routers/thread_fanout.py``) owns building the facilitator and recording the
outcomes against the trust network.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from probos.cognitive.chat_facilitator import ChatFacilitator


@dataclass(frozen=True)
class ConversationTrustOutcome:
    """One positive trust observation drawn from a convergent conversation.

    ``verifier_id`` is the PEER that corroborates ``agent_id`` — always a
    different agent (the anti-self-sourcing rule), so the resulting TrustEvent
    attributes the credit to a distinct verifier.
    """

    agent_id: str
    success: bool
    weight: float
    intent_type: str
    verifier_id: str


def conversation_topic_tag(title: str) -> str:
    """Normalize a thread title into a stable trust ``intent_type`` tag.

    Lowercase, collapse runs of whitespace to a single space, cap at 64 chars.
    An empty / whitespace-only title falls back to ``"group_chat"``.
    """
    tag = " ".join((title or "").lower().split())
    if not tag:
        return "group_chat"
    return tag[:64]


def extract_conversation_trust_outcomes(
    replies: list[dict[str, str]],
    *,
    facilitator: "ChatFacilitator",
    intent_type: str,
    positive_weight: float,
    max_outcomes: int,
    convergence_window: int = 12,
) -> list[ConversationTrustOutcome]:
    """Derive bounded positive trust outcomes from a convergent conversation.

    ``replies`` are the fan-out's ``{"agent_id", "callsign", "text"}`` dicts in
    order. Returns ``[]`` unless the recent window has CONVERGED (per the pure
    ``facilitator.is_converged``) across at least two distinct contributors. On
    convergence, emit one outcome per distinct contributor (sorted, capped at
    ``max_outcomes``), each credited by the NEXT distinct peer in ring order so
    the verifier is always a different agent.
    """
    if max_outcomes <= 0 or positive_weight <= 0:
        return []
    pairs = [(r.get("agent_id", ""), r.get("text", "")) for r in replies]
    window = pairs[-convergence_window:] if convergence_window > 0 else pairs
    if not facilitator.is_converged(window):
        return []
    distinct: list[str] = []
    for aid, _ in pairs:
        if aid and aid not in distinct:
            distinct.append(aid)
    n = len(distinct)
    if n < 2:
        return []
    distinct.sort()
    outcomes: list[ConversationTrustOutcome] = []
    for i, aid in enumerate(distinct[:max_outcomes]):
        verifier = distinct[(i + 1) % n]
        outcomes.append(ConversationTrustOutcome(
            agent_id=aid,
            success=True,
            weight=positive_weight,
            intent_type=intent_type,
            verifier_id=verifier,
        ))
    return outcomes
