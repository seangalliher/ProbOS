"""AD-722a: intent-vs-presentation divergence detector.

Pure module. Zero I/O. Zero LLM calls. Compares the LLM's own
``<intent emotion=...>`` self-tag against the modulation rule output of
``probos.avatars.telemetry.apply_voice_modulation`` for the agent's
last reply. Produces a ``DivergenceResult`` consumed by
``routers/agents.py:agent_chat`` for trust + Hebbian updates.

AD-727 rule #1: this detector observes REASONING-vs-OUTPUT divergence
(the agent's stated intent vs. the deterministic projection of her
modulation rules). It does NOT ingest pixels, invoke a vision LLM, or
compare image to model. It is therefore the precise category that
AD-727 explicitly authorizes for trust wiring.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Any, Final

if TYPE_CHECKING:
    from probos.runtime import ProbOSRuntime
    from probos.crew_profile import EmotionProfile  # AD-737

logger = logging.getLogger(__name__)


# Hebbian rel_type namespace (string constant; no edit to routing.py).
REL_AVATAR_INTENT: Final[str] = "avatar_intent"


class EmotionalIntent(str, Enum):
    """v1 emotion taxonomy (AD-722a-7 migration). Per-agent palettes is
    forward marker AD-722a-3 (#612)."""

    WARM = "warm"
    CONCERNED = "concerned"
    EXCITED = "excited"
    APOLOGETIC = "apologetic"
    FORMAL = "formal"
    PLAYFUL = "playful"
    REASSURING = "reassuring"
    NEUTRAL = "neutral"


# Intent -> expected fired_rules subset.
# AD-722a-7: keys are the str values from EmotionalIntent. Values are the
# matching ``intent_X`` rule names emitted by ``apply_voice_modulation``
# when the intent fires. ``match_score`` is computed against the
# ``intent_*`` namespace only -- operational rules
# (``responding_rate``, ``blocked_rate_pitch``, ``high_trust_pitch``,
# ``low_trust_pitch``, ``tier3_rate_volume``) are informational; they
# reflect agent state, not intent fulfillment.
INTENT_EXPECTED_RULES: Final[dict[str, frozenset[str]]] = {
    EmotionalIntent.WARM.value: frozenset({"intent_warm"}),
    EmotionalIntent.CONCERNED.value: frozenset({"intent_concerned"}),
    EmotionalIntent.EXCITED.value: frozenset({"intent_excited"}),
    EmotionalIntent.APOLOGETIC.value: frozenset({"intent_apologetic"}),
    EmotionalIntent.FORMAL.value: frozenset({"intent_formal"}),
    EmotionalIntent.PLAYFUL.value: frozenset({"intent_playful"}),
    EmotionalIntent.REASSURING.value: frozenset({"intent_reassuring"}),
    EmotionalIntent.NEUTRAL.value: frozenset({"intent_neutral"}),
}


# Intent -> directional axis.
# +1 = warmer/brighter (high pitch / warmer)
# -1 = firmer/lower (low pitch / cooler)
#  0 = neutral (neither axis is the divergence target)
INTENT_DIRECTION: Final[dict[str, int]] = {
    EmotionalIntent.WARM.value: +1,
    EmotionalIntent.CONCERNED.value: -1,
    EmotionalIntent.EXCITED.value: +1,
    EmotionalIntent.APOLOGETIC.value: -1,
    EmotionalIntent.FORMAL.value: 0,
    EmotionalIntent.PLAYFUL.value: +1,
    EmotionalIntent.REASSURING.value: -1,
    EmotionalIntent.NEUTRAL.value: 0,
}


# Self-tag parse + strip regexes (server-side, single source of truth).
# Matches ``<intent emotion=NAME>`` or ``<intent emotion=NAME/>``,
# anywhere in the reply (multi-line). NAME is ``[a-zA-Z_]+``; lowercased on parse.
_TAG_RE: Final[re.Pattern[str]] = re.compile(
    r"<intent\s+emotion\s*=\s*([a-zA-Z_]+)\s*/?\s*>",
    re.IGNORECASE,
)


def _resolve_intent_name(
    name: str,
    custom_emotions: "dict[str, EmotionProfile] | None",
) -> str | None:
    """AD-737: resolve a parsed intent name to a v1 EmotionalIntent value.

    Returns the v1 emotion name (one of ``EmotionalIntent.value``) if
    ``name`` is either (a) a v1 name directly, or (b) a custom emotion
    whose ``inherits`` field points at a v1 name. Returns ``None``
    otherwise (caller short-circuits the divergence pipeline).
    """
    if name in INTENT_EXPECTED_RULES:
        return name
    if not custom_emotions:
        return None
    profile = custom_emotions.get(name)
    if profile is None:
        return None
    parent = getattr(profile, "inherits", None)
    if parent in INTENT_EXPECTED_RULES:
        return parent
    # Defensive: stale config drift could put a bad inherits past the
    # CrewProfile validator (e.g. dataclass mutated post-construct).
    logger.debug(
        "AD-737: custom emotion %r has invalid inherits=%r; treating as unknown",
        name, parent,
    )
    return None
# Strip regex anchored to optional trailing whitespace at end-of-line.
_TAG_STRIP_RE: Final[re.Pattern[str]] = re.compile(
    r"\s*<intent\s+emotion\s*=\s*[a-zA-Z_]+\s*/?\s*>\s*$",
    re.IGNORECASE | re.MULTILINE,
)


@dataclass(frozen=True)
class DivergenceResult:
    """Result of comparing intent self-tag against applied modulation.

    All fields required (no defaults) -- frozen-dataclass field-ordering
    discipline preserved.

    - ``intent_emotion``: parsed self-tag value (one of EmotionalIntent).
    - ``applied_fired_rules``: tuple from ModulationSnapshot.fired_rules.
    - ``match_score``: Jaccard(expected, applied) in [0.0, 1.0].
      1.0 = expected == applied (or both empty); 0.0 = no overlap (also
      when expected is empty AND applied is non-empty -- modulation moved
      when intent asked for stillness).
    - ``signed_divergence``: in [-1.0, +1.0]. Sign determined by
      INTENT_DIRECTION x applied-direction; magnitude = (1 - match_score).
      Negative = applied diverged to opposite axis. Positive = applied
      moved on the SAME directional axis (or neutral) but match was imperfect
      (informational; does not punish trust).
    - ``magnitude``: abs(signed_divergence) in [0.0, 1.0].
    """

    intent_emotion: str
    applied_fired_rules: tuple[str, ...]
    match_score: float
    signed_divergence: float
    magnitude: float

    def to_dict(self) -> dict[str, object]:
        return {
            "intent_emotion": self.intent_emotion,
            "applied_fired_rules": list(self.applied_fired_rules),
            "match_score": self.match_score,
            "signed_divergence": self.signed_divergence,
            "magnitude": self.magnitude,
        }


@dataclass(frozen=True)
class DivergenceHistoryEntry:
    """One historical divergence event with its capture timestamp.

    AD-722a-5: wraps ``DivergenceResult`` with the wall-clock timestamp at
    capture. Frozen -- captured value, not a live reference.

    Phrasing rule (AD-727 #8): ``to_note()`` describes the OUTPUT, never
    the agent. The forbidden-phrasing regex test at
    ``tests/test_ad722a_divergence_detector.py:497`` continues to gate.
    """

    timestamp: float
    result: DivergenceResult

    def to_dict(self) -> dict[str, object]:
        return {
            "timestamp": self.timestamp,
            "result": self.result.to_dict(),
            "note": self.to_note(),
        }

    def to_note(self) -> str:
        """Render a one-line OUTPUT-subject note.

        Subject of every sentence is the REPLY / OUTPUT, never the agent.
        The phrasing mirrors ``_build_divergence_note_suffix()`` in
        ``cognitive_agent.py`` so the AD-727 regex test covers both.
        """
        applied = ", ".join(self.result.applied_fired_rules) or "no_rules_fired"
        return (
            f"Reply intended as `{self.result.intent_emotion}` "
            f"came out as `{applied}` "
            f"(signed divergence: {self.result.signed_divergence:+.2f}, "
            f"match score: {self.result.match_score:.2f})."
        )


def parse_intent_self_tag(
    text: str,
    custom_emotions: "dict[str, EmotionProfile] | None" = None,
) -> str | None:
    """Extract the emotion name from an ``<intent emotion=NAME>`` tag.

    Returns the parsed name when it is either (a) a v1
    ``EmotionalIntent`` value, or (b) AD-737 a custom emotion declared
    in ``custom_emotions``. Returns ``None`` for unknown names --
    graceful degrade; the caller short-circuits the divergence pipeline
    on None.
    """
    if not text:
        return None
    match = _TAG_RE.search(text)
    if match is None:
        return None
    name = match.group(1).strip().lower()
    if _resolve_intent_name(name, custom_emotions) is None:
        logger.debug(
            "AD-722a: parsed intent tag with unknown emotion=%r; ignoring",
            name,
        )
        return None
    return name


def strip_intent_self_tag(text: str) -> str:
    """Remove the trailing ``<intent emotion=...>`` tag from a reply.

    Server-side strip -- the tag MUST NEVER reach the Captain. Trims
    trailing whitespace produced by the strip. Idempotent -- calling
    twice on the same text returns the same result.
    """
    if not text:
        return text
    return _TAG_STRIP_RE.sub("", text).rstrip()


def _applied_direction(applied: tuple[str, ...]) -> int:
    """Project the applied fired_rules onto the directional axis.

    AD-722a-7: intent rules dominate when present (they were explicitly
    chosen by the agent). Operational rules contribute only when no
    intent rule fired.

    +1 = warmer (high pitch / brighter); -1 = firmer (lower pitch);
     0 = neutral or mixed-cancelling.
    """
    intent_pos = sum(1 for r in applied if r in {
        "intent_warm", "intent_excited", "intent_playful",
    })
    intent_neg = sum(1 for r in applied if r in {
        "intent_concerned", "intent_apologetic", "intent_reassuring",
    })
    if intent_pos > intent_neg:
        return +1
    if intent_neg > intent_pos:
        return -1
    if intent_pos > 0 or intent_neg > 0:
        # Intent rules present but cancelling -- explicit neutral.
        return 0

    # Fallback: project operational rules (pre-AD-722a-7 behavior).
    pos = sum(1 for r in applied if r in {"high_trust_pitch"})
    neg = sum(1 for r in applied if r in {"low_trust_pitch", "blocked_rate_pitch"})
    if pos > neg:
        return +1
    if neg > pos:
        return -1
    return 0


def compute_divergence(
    intent_emotion: str,
    applied_fired_rules: tuple[str, ...],
) -> DivergenceResult:
    """Compute a DivergenceResult.

    Pure function. ``intent_emotion`` MUST be a valid taxonomy member
    (caller's responsibility -- ``parse_intent_self_tag`` filters).

    AD-722a-7: ``match_score`` is computed against the ``intent_*``
    namespace only. Operational rules in ``applied_fired_rules``
    (``responding_rate``, ``blocked_rate_pitch``, ``high_trust_pitch``,
    ``low_trust_pitch``, ``tier3_rate_volume``) are informational -- they
    reflect agent state, not intent fulfillment.
    """
    expected = INTENT_EXPECTED_RULES.get(intent_emotion, frozenset())
    # Restrict applied set to the intent_* namespace for match calculation.
    applied_set = frozenset(
        r for r in applied_fired_rules if r.startswith("intent_")
    )

    # Jaccard score, with the "empty intent + non-empty applied" edge
    # handled explicitly: intent asked for stillness, modulation moved.
    if not expected and not applied_set:
        match_score = 1.0
    elif not expected and applied_set:
        match_score = 0.0
    else:
        union = expected | applied_set
        match_score = len(expected & applied_set) / len(union) if union else 1.0

    raw_magnitude = 1.0 - match_score

    # Sign the magnitude using directional axes.
    intent_dir = INTENT_DIRECTION.get(intent_emotion, 0)
    applied_dir = _applied_direction(applied_fired_rules)
    if intent_dir == 0 or applied_dir == 0 or intent_dir == applied_dir:
        # Same-axis or neutral: positive (informational; does not punish).
        signed = +raw_magnitude
    else:
        # Opposite-axis: true divergence (negative signal for trust).
        signed = -raw_magnitude

    return DivergenceResult(
        intent_emotion=intent_emotion,
        applied_fired_rules=tuple(applied_fired_rules),
        match_score=float(match_score),
        signed_divergence=float(signed),
        magnitude=float(raw_magnitude),
    )


# Match-strengthens threshold for the Hebbian success bit. A reply whose
# applied modulation has Jaccard >= this against the expected rule set
# is treated as a "match"; below this, the edge weakens.
_HEBBIAN_MATCH_THRESHOLD: Final[float] = 0.7


def _resolve_voice_profile_for_intent(runtime: Any, agent_id: str) -> Any:
    """AD-722a-7: synchronous voice-profile lookup for intent-modulation recompute.

    Returns a duck-typed object exposing ``pitch`` / ``rate`` / ``volume``
    attributes. The caller only reads these to compose baseline numeric
    factors; ``fired_rules`` content is independent of the baseline.

    Tier-2 log-and-degrade: any lookup failure returns a synthetic
    identity baseline (pitch=rate=volume=1.0). NEVER raises.
    """
    store = getattr(runtime, "profile_store", None)
    if store is not None:
        try:
            crew = store.get(agent_id)
            if crew is not None and getattr(crew, "voice", None) is not None:
                return crew.voice
        except Exception:
            logger.debug(
                "AD-722a-7: profile_store lookup failed for %s; "
                "using identity baseline",
                agent_id, exc_info=True,
            )
    # Identity baseline -- safe for the fired_rules-only consumer downstream.
    from types import SimpleNamespace
    return SimpleNamespace(pitch=1.0, rate=1.0, volume=1.0)


def apply_divergence_check(
    runtime: "ProbOSRuntime | Any",
    agent_id: str,
    agent: Any,
    response_text: str,
    t_cfg: Any,
) -> str:
    """Parse, strip, score, and wire divergence for a finalized reply.

    Single-call-site helper invoked from
    ``routers/agents.py:agent_chat`` immediately before
    ``mark_reply_emitted``. Tier-2 internally: caller wraps in try/except
    for defense in depth.

    Always strips the self-tag from ``response_text`` when the feature is
    ON, even on parse failure (defense against leaking the tag to the
    Captain). Returns the stripped text.

    When the parsed intent is valid AND the agent has a cached
    ``_last_self_avatar_snap`` with applied modulation:
      - computes ``DivergenceResult`` and stores it on
        ``runtime.divergence_results[agent_id]``
      - asymmetric trust update gated by negative/positive thresholds
      - Hebbian edge ``(agent_id, "avatar:emotion:NAME", REL_AVATAR_INTENT)``

    AD-727 rule #1 inheritance: this wiring touches trust + Hebbian
    because the signal is REASONING-vs-OUTPUT (intent self-tag vs.
    deterministic modulation projection). It never compares image to
    model.
    """
    intent = parse_intent_self_tag(response_text)
    # AD-737: look up the agent's custom emotion palette (tier-2
    # log-and-degrade). Then re-parse with the palette so custom names
    # like ``professional_concern`` resolve through ``inherits``.
    custom_emotions: dict[str, Any] | None = None
    store = getattr(runtime, "profile_store", None)
    if store is not None:
        try:
            crew = store.get(agent_id) if hasattr(store, "get") else None
            custom_emotions = (
                getattr(crew, "custom_emotions", None) if crew else None
            )
        except Exception:
            logger.debug(
                "AD-737: profile_store custom_emotions lookup failed for %s",
                agent_id, exc_info=True,
            )
    if intent is None and custom_emotions:
        intent = parse_intent_self_tag(
            response_text, custom_emotions=custom_emotions,
        )
    # Strip unconditionally when feature ON -- even on parse failure
    # (unknown emotion / malformed tag), the visible tag must not leak.
    stripped = strip_intent_self_tag(response_text)

    snap = getattr(agent, "_last_self_avatar_snap", None)
    modulation = getattr(snap, "applied_modulation", None) if snap is not None else None
    if intent is None or modulation is None:
        return stripped

    # AD-722a-7 / AD-737: recompute the modulation with the parsed
    # intent (custom or v1) so ``fired_rules`` carries both the parent
    # ``intent_X`` rule (used by ``compute_divergence``'s
    # ``startswith('intent_')`` filter) AND, for custom emotions, the
    # ``custom_X`` tag for observability.
    signals = getattr(snap, "current_signals", None)
    if signals is not None:
        from probos.avatars.telemetry import apply_voice_modulation
        voice_profile = _resolve_voice_profile_for_intent(runtime, agent_id)
        modulation = apply_voice_modulation(
            voice_profile, signals, intent=intent,
            custom_emotions=custom_emotions,
        )

    # AD-737 critical scoring fix: ``compute_divergence`` keys
    # ``expected`` on the v1 INTENT_EXPECTED_RULES table; a raw custom
    # name yields ``frozenset()`` and the ``not expected and applied_set``
    # branch forces ``match_score = 0.0`` (silent maximum-divergence
    # corruption). Resolve to the v1 parent for scoring, then restore the
    # custom name on the DivergenceResult for downstream observability.
    resolved_v1 = _resolve_intent_name(intent, custom_emotions) or intent
    result = compute_divergence(
        intent_emotion=resolved_v1,
        applied_fired_rules=tuple(modulation.fired_rules),
    )
    if resolved_v1 != intent:
        import dataclasses as _dc
        result = _dc.replace(result, intent_emotion=intent)

    # Centralized per-agent store; volatile across restarts.
    div_results = getattr(runtime, "divergence_results", None)
    if div_results is not None:
        div_results[agent_id] = result

    # AD-722a-5: append to per-agent ring buffer. Tier-2 -- buffer absence
    # or zero-sized buffer is a silent no-op (history surface degrades to
    # empty). The deque is allocated lazily on first append so memory is
    # only spent on agents that actually produce divergences.
    history_size = int(getattr(t_cfg, "divergence_history_size", 0))
    if history_size > 0:
        div_history = getattr(runtime, "divergence_history", None)
        if div_history is not None:
            import time as _time
            from collections import deque as _deque
            entry = DivergenceHistoryEntry(
                timestamp=_time.time(),
                result=result,
            )
            bucket = div_history.get(agent_id)
            if bucket is None or bucket.maxlen != history_size:
                # Lazy alloc OR resize on config change. Preserves existing
                # entries up to the new cap.
                old = list(bucket) if bucket is not None else []
                bucket = _deque(old, maxlen=history_size)
                div_history[agent_id] = bucket
            bucket.append(entry)

    # Trust update -- asymmetric thresholds AND weights per AD-727 dampening.
    trust = getattr(runtime, "trust_network", None)
    if trust is not None:
        neg_threshold = float(getattr(t_cfg, "divergence_negative_threshold", 0.3))
        pos_threshold = float(getattr(t_cfg, "divergence_positive_threshold", 0.5))
        neg_weight = float(getattr(t_cfg, "divergence_negative_weight", 0.4))
        pos_weight = float(getattr(t_cfg, "divergence_positive_weight", 0.1))
        if result.magnitude > neg_threshold and result.signed_divergence < 0:
            trust.record_outcome(
                agent_id=agent_id,
                success=False,
                weight=result.magnitude * neg_weight,
                intent_type="avatar_divergence",
                source="avatar_divergence",
            )
        elif result.magnitude > pos_threshold and result.signed_divergence > 0:
            trust.record_outcome(
                agent_id=agent_id,
                success=True,
                weight=result.magnitude * pos_weight,
                intent_type="avatar_divergence",
                source="avatar_divergence",
            )

    # Hebbian update -- match strengthens, non-match weakens.
    hebb = getattr(runtime, "hebbian_router", None)
    if hebb is not None:
        hebb.record_interaction(
            source=agent_id,
            target=f"avatar:emotion:{intent}",
            success=(result.match_score >= _HEBBIAN_MATCH_THRESHOLD),
            rel_type=REL_AVATAR_INTENT,
        )

    return stripped
