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

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from probos.crew_profile import extract_directed_callsign

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


# AD-958c: explicit peer-correction cues — an assertion that a PRIOR peer claim
# is factually WRONG. Tight allowlist (precision over recall): mere disagreement
# ("I disagree", "I'd weigh it differently", "from my vantage") must NOT match.
_CORRECTION_CUE_RE = re.compile(
    r"\b(?:"
    r"that(?:'s| is) (?:not right|not correct|incorrect|wrong|false|a mistake|an error)"
    r"|not quite right"
    r"|you(?:'re| are) (?:wrong|mistaken|incorrect)"
    r"|correction:"
    r"|actually,?\s+(?:that(?:'s| is)\s+)?(?:wrong|incorrect|not right|not correct)"
    r")\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ConversationCorrectionSignal:
    """AD-958c: one DETECTED peer-correction — corrector ``corrector_id``
    asserts ``corrected_agent_id``'s prior claim was factually wrong.

    OBSERVE-ONLY in v1: no weight/success — the negative trust write
    (``record_outcome(success=False)``) is deferred to AD-958d so the detector's
    precision can be measured on live transcripts first.
    """

    corrected_agent_id: str
    corrector_id: str
    cue: str
    intent_type: str


def detect_conversation_corrections(
    replies: list[dict[str, str]],
    *,
    intent_type: str,
    max_signals: int,
) -> list[ConversationCorrectionSignal]:
    """Pure detector for explicit peer-corrects-peer signals.

    For each reply that (A) matches ``_CORRECTION_CUE_RE`` AND (B) directly
    addresses (``extract_directed_callsign``) a peer who SPOKE EARLIER in the
    transcript, emit one signal crediting the corrector. No self-sourcing
    (corrected != corrector). NOT convergence-gated. Deduped per
    (corrector, corrected) pair, sorted for determinism, capped at
    ``max_signals``. ``max_signals <= 0`` -> ``[]``.
    """
    if max_signals <= 0:
        return []
    seen: set[tuple[str, str]] = set()
    out: list[ConversationCorrectionSignal] = []
    spoke_callsign: dict[str, str] = {}  # callsign.lower() -> most-recent prior agent_id
    for r in replies:
        corrector = r.get("agent_id", "")
        text = r.get("text", "")
        cue_m = _CORRECTION_CUE_RE.search(text or "")
        if cue_m and corrector:
            cs = extract_directed_callsign(text)
            corrected = spoke_callsign.get(cs) if cs else None
            if corrected and corrected != corrector:
                pair = (corrector, corrected)
                if pair not in seen:
                    seen.add(pair)
                    out.append(ConversationCorrectionSignal(
                        corrected_agent_id=corrected,
                        corrector_id=corrector,
                        cue=cue_m.group(0),
                        intent_type=intent_type,
                    ))
        cs_self = (r.get("callsign", "") or "").lower()
        if cs_self and corrector:
            spoke_callsign[cs_self] = corrector
    out.sort(key=lambda s: (s.corrected_agent_id, s.corrector_id))
    return out[:max_signals]
