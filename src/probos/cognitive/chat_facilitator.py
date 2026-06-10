"""AD-915: pure turn-taking facilitator for ad-hoc group chats.

Deterministic, side-effect-free, LLM-free. Given per-speaker signal
snapshots and the recent agent exchange, produce an ordered, possibly
truncated, possibly suppressed speaker list:

  * relevance ranking   — weighted factors (mention, recency, department, trust)
  * @-mention hard-include — an explicitly addressed agent ALWAYS speaks,
    at the front, overriding both truncation and convergence
  * truncation cap      — bounds NON-mentioned fan-out (0 = off, AD-914)
  * convergence gate     — when the recent exchange has converged (mean
    pairwise Jaccard >= threshold across >= min_agents distinct agents over
    >= min_messages recent agent turns), suppress non-mentioned speakers

This is the shared sequencer AD-921 (meeting voice) reuses to order who
speaks aloud. It reuses the AD-583/AD-614 pure primitive
``probos.cognitive.similarity.jaccard_similarity`` rather than the
substrate-coupled convergence DETECTORS (RecordsStore / Ward Room posts),
which cannot be pointed at chat_thread_messages rows.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from probos.cognitive.similarity import jaccard_similarity, text_to_words


@dataclass(frozen=True)
class SpeakerSignals:
    """Per-speaker snapshot. Assembled by the impure layer; scored pure."""

    agent_id: str
    mentioned: bool = False            # @-addressed in the Captain turn -> hard include
    turns_since_last_spoke: int = 9_999  # large => quiet => fairness boost
    department_relevance: float = 0.0  # jaccard(captain words, dept+type words) in [0,1]
    trust: float = 0.5                 # neutral default
    order_index: int = 0               # stable tiebreak (input participant order)


@dataclass(frozen=True)
class SpeakerScore:
    agent_id: str
    score: float
    mentioned: bool
    factors: dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class FacilitationResult:
    speaking_order: list[str]          # ordered agent_ids (possibly empty/truncated)
    converged: bool                    # recent exchange converged -> non-mentioned suppressed
    scores: list[SpeakerScore] = field(default_factory=list)  # full ranking (diagnostics)


def build_room_signal(
    *,
    agent_id: str,
    department_relevance: float,
    recent_authors: list[str],
    scores: list[SpeakerScore],
    callsign_by_agent: dict[str, str],
    recent_window: int = 6,
    domain_threshold: float = 0.15,
) -> dict | None:
    """AD-955: build ONE speaker's advisory ROOM-AWARENESS signal from the
    facilitator's ranking, or ``None`` when nothing salient surfaces.

    Pure (no I/O). ``recent_authors`` is the author_id of recent agent turns
    (oldest->newest); ``scores`` is the facilitator's descending ranking;
    ``callsign_by_agent`` resolves the peer the room would most value hearing.
    The signal is ADVISORY — the cognitive_agent hook renders it and the agent
    reasons over it; it NEVER changes who is dispatched (the cap/convergence
    backstops own that). Returns a plain dict (rides ``IntentMessage.params``).

    Fields: ``recent_share`` (this agent's turns in the recent window),
    ``recent_window`` (the window actually considered), ``this_is_your_area``
    (department relevance >= threshold), ``room_would_value`` (callsign of the
    highest-ranked OTHER candidate — a defer/hand-off target — or None).
    """
    recent = recent_authors[-recent_window:] if recent_window > 0 else []
    considered = len(recent)
    recent_share = sum(1 for a in recent if a == agent_id)
    domain_relevant = department_relevance >= domain_threshold
    # The peer the room would most value hearing next: the highest-ranked
    # candidate other than this speaker that has a resolvable callsign.
    room_would_value: str | None = None
    for s in scores:
        if s.agent_id == agent_id:
            continue
        cs = callsign_by_agent.get(s.agent_id, "")
        if cs:
            room_would_value = cs
            break
    if considered == 0 and room_would_value is None and not domain_relevant:
        return None
    return {
        "recent_share": recent_share,
        "recent_window": considered,
        "this_is_your_area": domain_relevant,
        "room_would_value": room_would_value,
    }


class ChatFacilitator:
    """Pure facilitator. No I/O, no LLM, no runtime."""

    def __init__(
        self,
        *,
        max_speakers_per_turn: int = 0,
        convergence_enabled: bool = True,
        convergence_similarity_threshold: float = 0.6,
        convergence_min_messages: int = 4,
        convergence_min_agents: int = 2,
        weight_mention: float = 0.40,
        weight_recency: float = 0.25,
        weight_department: float = 0.25,
        weight_trust: float = 0.10,
        weight_exploration: float = 0.0,
    ) -> None:
        self._max_speakers = max(0, int(max_speakers_per_turn))
        self._conv_enabled = bool(convergence_enabled)
        self._conv_threshold = float(convergence_similarity_threshold)
        self._conv_min_messages = max(1, int(convergence_min_messages))
        self._conv_min_agents = max(2, int(convergence_min_agents))
        self._w_mention = float(weight_mention)
        self._w_recency = float(weight_recency)
        self._w_department = float(weight_department)
        self._w_trust = float(weight_trust)
        # AD-958a: exploration / anti-rich-get-richer (default 0.0 == off).
        self._w_exploration = max(0.0, float(weight_exploration))

    @classmethod
    def from_config(cls, config: object | None) -> "ChatFacilitator":
        """Build from a SystemConfig-like object. None / missing group_chat
        -> all defaults (zero-config boot; AD-914's minimal runtime)."""
        gc = getattr(config, "group_chat", None)
        if gc is None:
            return cls()
        return cls(
            max_speakers_per_turn=getattr(gc, "max_speakers_per_turn", 0),
            convergence_enabled=getattr(gc, "convergence_enabled", True),
            convergence_similarity_threshold=getattr(gc, "convergence_similarity_threshold", 0.6),
            convergence_min_messages=getattr(gc, "convergence_min_messages", 4),
            convergence_min_agents=getattr(gc, "convergence_min_agents", 2),
            weight_mention=getattr(gc, "weight_mention", 0.40),
            weight_recency=getattr(gc, "weight_recency", 0.25),
            weight_department=getattr(gc, "weight_department", 0.25),
            weight_trust=getattr(gc, "weight_trust", 0.10),
            weight_exploration=getattr(gc, "weight_exploration", 0.0),
        )

    # ---- pure scoring ----

    def _recency_factor(self, turns_since: int) -> float:
        # 0 turns -> 0.0 (just spoke), 1 -> 0.5, 3 -> 0.75, never-spoke -> ~1.0.
        t = max(0, int(turns_since))
        return 1.0 - 1.0 / (1.0 + t)

    def rank(self, signals: list[SpeakerSignals]) -> list[SpeakerScore]:
        """Score + sort speakers descending. Deterministic; stable tiebreak
        on (-score, order_index, agent_id)."""
        scored: list[SpeakerScore] = []
        for s in signals:
            factors: dict[str, float] = {}
            total = 0.0
            if s.mentioned:
                factors["mention"] = self._w_mention
                total += self._w_mention
            rec = self._recency_factor(s.turns_since_last_spoke) * self._w_recency
            if rec > 0.0:
                factors["recency"] = rec
                total += rec
            dep = max(0.0, min(1.0, s.department_relevance)) * self._w_department
            if dep > 0.0:
                factors["department"] = dep
                total += dep
            tr = max(0.0, min(1.0, s.trust)) * self._w_trust
            if tr > 0.0:
                factors["trust"] = tr
                total += tr
            # AD-958a: exploration / anti-rich-get-richer. A domain-relevant but
            # UNPROVEN agent gets a bonus inversely proportional to its trust, so
            # it is surfaced to EARN trust (Minimal Authority axiom). Gated on
            # department_relevance so an irrelevant agent is never boosted; a
            # high-trust agent (already carried by the trust term) gets ~0.
            # Deterministic (no RNG) — the facilitator stays pure. Off when
            # weight_exploration == 0.0 (default).
            if self._w_exploration > 0.0:
                dep_rel = max(0.0, min(1.0, s.department_relevance))
                tr_norm = max(0.0, min(1.0, s.trust))
                expl = self._w_exploration * dep_rel * (1.0 - tr_norm)
                if expl > 0.0:
                    factors["exploration"] = expl
                    total += expl
            scored.append(SpeakerScore(
                agent_id=s.agent_id, score=total, mentioned=s.mentioned, factors=factors,
            ))
        order = {s.agent_id: s.order_index for s in signals}
        scored.sort(key=lambda sc: (-sc.score, order.get(sc.agent_id, 0), sc.agent_id))
        return scored

    def is_converged(self, recent_agent_messages: list[tuple[str, str]]) -> bool:
        """recent_agent_messages: list of (author_id, body), oldest->newest,
        role=="agent" only. Converged when there are >= min_messages turns
        from >= min_agents distinct agents AND the mean pairwise Jaccard of
        their bodies >= threshold. Reuses the AD-583/AD-614 pure primitive."""
        if not self._conv_enabled:
            return False
        msgs = recent_agent_messages
        if len(msgs) < self._conv_min_messages:
            return False
        if len({a for a, _ in msgs}) < self._conv_min_agents:
            return False
        word_sets = [text_to_words(b) for _, b in msgs]
        sims: list[float] = []
        for i in range(len(word_sets)):
            for j in range(i + 1, len(word_sets)):
                sims.append(jaccard_similarity(word_sets[i], word_sets[j]))
        if not sims:
            return False
        return (sum(sims) / len(sims)) >= self._conv_threshold

    def facilitate(
        self,
        signals: list[SpeakerSignals],
        recent_agent_messages: list[tuple[str, str]],
    ) -> FacilitationResult:
        """Order, truncate, and convergence-gate. Mentioned speakers are
        ALWAYS honored (front, override truncation + convergence). The cap
        bounds NON-mentioned speakers only."""
        scores = self.rank(signals)
        mentioned = [sc.agent_id for sc in scores if sc.mentioned]
        others = [sc.agent_id for sc in scores if not sc.mentioned]
        converged = self.is_converged(recent_agent_messages)
        if converged:
            return FacilitationResult(speaking_order=list(mentioned), converged=True, scores=scores)
        if self._max_speakers > 0:
            remaining = max(0, self._max_speakers - len(mentioned))
            others = others[:remaining]
        return FacilitationResult(speaking_order=mentioned + others, converged=False, scores=scores)
