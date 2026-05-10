# AD-722a — Intent-vs-presentation divergence detector + trust/Hebbian wiring

**Status:** READY FOR BUILDER
**Wave:** 143 (single-prompt wave, single commit)
**Dispatch:** [prompts/WAVE-143-DISPATCH.md](WAVE-143-DISPATCH.md)
**Cluster plan:** [prompts/BUILDER-EXECUTION-PLAN-avatar-cluster.md](BUILDER-EXECUTION-PLAN-avatar-cluster.md)
**Depends on:** AD-722 v1 (SHIPPED Wave 140), AD-722-1 (SHIPPED Wave 141), AD-722f (SHIPPED Wave 141), AD-722b (SHIPPED Wave 142), AD-727 (constraint stack — read-only on aesthetic, FAIR on reasoning-vs-output)
**Issue:** [#567](https://github.com/seangalliher/ProbOS/issues/567)
**Risk:** **MEDIUM** — first AD that closes the read→write loop AD-722 v1 left open. Trust + Hebbian are mutated. AD-727 rule #1 (read-only on aesthetic) is preserved BY CONSTRUCTION — the divergence checked is reasoning-vs-output, never image-based.
**Estimated tests:** ≥ 18 Python boundary cases. **No UI changes; no Vitest delta.**

> **Builder:** read [prompts/WAVE-143-DISPATCH.md](WAVE-143-DISPATCH.md) for cross-AD context, license posture, and the engineering-principles checklist. Read [prompts/BUILDER-EXECUTION-PLAN.md](BUILDER-EXECUTION-PLAN.md) for the standing test-gate command, hard-stop rules, and quarantine procedure. **Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.**

---

## 1. Goal (TL;DR)

AD-722 v1 (Wave 140) shipped read-only avatar telemetry. AD-722f (Wave 141) added adaptive sampling. AD-722b (Wave 142) added the WS push channel. The read side is now complete. AD-722a is the **first consumer** that closes the perception → mutation loop:

> *Did the agent's emotional INTENT for this reply match the voice modulation that the system actually projected?*

Concretely:

1. When `avatar_telemetry.divergence_detection: True` (default OFF — operator opt-in, token cost), the LLM is instructed via a one-line system-prompt addition to append `<intent emotion=…>` on a new line at the end of every DM reply.
2. After the LLM returns and BEFORE the response is sent to the Captain, the server parses the self-tag, **strips it from the visible reply**, and computes a `DivergenceResult` against the most-recent `ModulationSnapshot.fired_rules`.
3. When `magnitude > divergence_negative_threshold` (default 0.3) AND `signed_divergence < 0` (output diverged AWAY from intent) → small-weighted negative `record_outcome`. When `magnitude > divergence_positive_threshold` (default 0.5 — higher bar) AND `signed_divergence > 0` (output exceeded intent in the SAME direction — "I meant warm; system rendered very-warm") → small-weighted positive `record_outcome`. Asymmetric weighting baked in: the negative weight (0.4) defaults heavier than the positive weight (0.1), and the negative threshold fires sooner. AD-727 dampening principle.
4. Hebbian: `record_interaction(source=agent_id, target=f"avatar:emotion:{intent_emotion}", success=match_score >= match_threshold, rel_type="avatar_intent")`. Match strengthens; non-match weakens.
5. The next prompt cycle's `_build_avatar_self_observation` block carries a divergence-note line. Phrasing rule (per AD-727 #8 translated to OUTPUT): describe the OUTPUT, never the agent.

This is the SECOND of three coherence checks per AD-727's three-AD partition:

- Self-coherence: AD-722e (deterministic projection — forward marker, not yet shipped).
- **Intent-vs-presentation: AD-722a** ← this wave.
- Digital-vs-analog: AD-728 (vision-LLM mirror — forward marker, hard-gated on AD-721i renderer).

Captain ruling 2026-05-10 ([DECISIONS.md AD-727](../DECISIONS.md)): trust delta is **fair for reasoning-vs-output divergence** (AD-722a's territory). It is **read-only-on-trust for image-based aesthetic judgments** (AD-722e/AD-728's territory). AD-722a observes that boundary by construction — it never ingests pixels, never invokes a vision LLM, never compares image to model.

---

## 2. Verified Against Codebase (2026-05-10 @ HEAD)

```
# CognitiveAgent — DM reply emission and self-observation injection
grep -n "mark_reply_emitted\|_last_self_avatar_snap\|_build_avatar_self_observation\|observe_self_avatar\|SENSORIUM_REGISTRY" src/probos/cognitive/cognitive_agent.py
   122:     SENSORIUM_REGISTRY: ClassVar[dict[str, tuple[SensoriumLayer, str]]] = {
   136:         "_build_avatar_self_observation": (SensoriumLayer.INTEROCEPTION,
   186:         # Stamped by `mark_reply_emitted()` from the chat handler at
   192:         self._last_self_avatar_snap: Any = None
  2617:     def mark_reply_emitted(self) -> None:
  2646:     async def observe_self_avatar(self) -> "AvatarTelemetrySnapshot":
  2659:     def _build_avatar_self_observation(self, observation: dict) -> str:
  2671:             snap = self._last_self_avatar_snap
  4537:             avatar_block = self._build_avatar_self_observation(observation or {})
  5155:                 _avatar_block = self._build_avatar_self_observation(observation)

# Chat handler — single mark_reply_emitted call site (AD-722 invariant)
grep -n "mark_reply_emitted\|response_text\s*=" src/probos/routers/agents.py
   750: response_text = ""
   752: response_text = str(result.result)
   754: response_text = f"(error: {result.error})"
   756: response_text = "(no response)"
   762: response_text = re.sub(r'[`*]{1,3}\[', '[', response_text)
   763: response_text = re.sub(r'\][`*]{1,3}', ']', response_text)
   908: if hasattr(agent, 'mark_reply_emitted'):
   909:     agent.mark_reply_emitted()
   922: "response": response_text,
# AD-722a hooks BETWEEN line 763 (post-process complete) and line 908
# (mark_reply_emitted) — divergence detection runs on finalized response_text.

# Telemetry surface — modulation rule output
grep -n "class ModulationSnapshot\|fired_rules\|def apply_voice_modulation" src/probos/avatars/telemetry.py
   209: class ModulationSnapshot:
   218:     fired_rules: tuple[str, ...]
   220:     def to_dict(self) -> dict[str, Any]:
   304: def apply_voice_modulation(

# TrustNetwork API — record_outcome is the real method (NOT `observe`)
grep -n "def record_outcome\|def observe\b\|class TrustNetwork" src/probos/consensus/trust.py
   112: class TrustNetwork:
   217:     def record_outcome(
# `def observe` does NOT exist. The cluster plan's `trust_network.observe(...)`
# was phantom; this AD uses `record_outcome` exclusively.

# HebbianRouter API
grep -n "def record_interaction\|REL_INTENT\s*=\|REL_AGENT\s*=" src/probos/mesh/routing.py
    28: REL_INTENT = "intent"  # intent_id → agent_id (Phase 1 default)
    29: REL_AGENT = "agent"   # agent_id → agent_id (Phase 2 verification)
   177: def record_interaction(
       source: AgentID, target: AgentID, success: bool,
       rel_type: str = REL_INTENT,
   ) -> float:
# `rel_type` is a free-form string; we introduce the namespace
# `"avatar_intent"` in `divergence_detector.py` (no edit to routing.py).

# Runtime initialization — adjacent state slots for AD-722f / AD-722b
grep -n "avatar_sampling_state\|avatar_event_bus\|avatar_telemetry_connection_manager\|divergence_results" src/probos/runtime.py
   411: # AD-722f: per-agent avatar-telemetry sampling state machine.
   416: self.avatar_sampling_state = AvatarSamplingStateMachine(
   420: # AD-722b: avatar-telemetry WS push channel — event bus + connection
   428: self.avatar_event_bus = AvatarEventBus()
   429: self.avatar_telemetry_connection_manager = AvatarTelemetryConnectionManager(
# `runtime.divergence_results` does NOT exist at HEAD — greenfield.

# Config — AvatarTelemetryConfig at HEAD
grep -n "class AvatarTelemetryConfig\|inject_into_agent_context\|max_connections_per_agent\|divergence_detection" src/probos/config.py
   973: class AvatarTelemetryConfig(BaseModel):
   990: inject_into_agent_context: bool = False
   994: max_connections_per_agent: int = 4
# `divergence_detection` and `divergence_*` fields do NOT exist — greenfield.

# Trust update precedent — `intent_type` / `source` already used by other ADs
grep -rn 'source="' src/probos/ | Select-String 'record_outcome' | Select-Object -First 3
   src/probos/cognitive/feedback.py: ... source="user_correction"
   src/probos/cognitive/finalize.py: ... source="finalization"
# v1 uses source="avatar_divergence" — new namespace, no collision.

# DECISIONS.md AD-727 — rule #1 verbatim ("aesthetic READ-ONLY on trust;
# divergence detector AD-722a CAN wire to trust because it's reasoning-vs-output").
grep -n "Aesthetic self-judgment is READ-ONLY\|Divergence detector (AD-722a)" DECISIONS.md
  1780: 1. **Aesthetic self-judgment is READ-ONLY with respect to trust/Hebbian.** Divergence detector (AD-722a) can wire to trust; AD-722e's image-based observations cannot.
```

> **Pre-flight findings (informational; do not block build):**
>
> 1. **Cluster-plan phantom API correction.** `prompts/BUILDER-EXECUTION-PLAN-avatar-cluster.md:152` cites `runtime.trust_network.observe(agent_id, delta=...)`. No such method exists on `TrustNetwork` (consensus/trust.py:112). The real API is `record_outcome(agent_id, success, weight, intent_type, episode_id, verifier_id, source) -> float`. This prompt uses the real API.
> 2. **Single `mark_reply_emitted` call site (AD-722 invariant) is preserved.** AD-722a adds the divergence detector call BEFORE `mark_reply_emitted` at the same single site (`routers/agents.py:909`). No new call sites.
> 3. **Read injection (AD-722) already lives in DM + chain paths.** AD-722a's WRITE side ships in DM only for v1 — chain reply-emission has no analogous single emit point. Chain divergence is forward marker AD-722a-2.
> 4. **WR remains unwired** per AD-722 addendum (h). AD-722a touches no WR code path.
> 5. **`_build_avatar_self_observation` is a SYNC method** (cognitive_agent.py:2659). Adding the divergence-note line stays synchronous — reads `runtime.divergence_results[agent_id]` directly, no asyncio.

---

## 3. License posture

Apache 2.0 stays Apache 2.0. **Zero new Python deps. Zero new JS deps.** The self-tag parser is a single regex; the divergence math is pure Python (no numpy, no scipy). `pyproject.toml` and `ui/package.json` are bit-for-bit identical pre/post commit — Reviewer fails on any diff.

---

## 4. Architectural decisions (resolved by architect; do NOT re-litigate)

| # | Decision | Resolution | Rationale |
|---|---|---|---|
| 1 | Intent-extraction strategy | **Prompt-engineering self-tag.** LLM appends `<intent emotion=…>` on a new line at end of reply. Server-side regex parse + strip. NO additional LLM call. | (a) Cheap (~10 prompt tokens, ~5 reply tokens). (b) Deterministic taxonomy. (c) No cross-language dependency. (d) Graceful degrade on omission. Rejected: regex against reply prose (English-brittle, unreliable). Rejected: sub-LLM classifier (~5-10× latency penalty). |
| 2 | Emotion taxonomy | **Fixed set of 8:** `warm`, `firm`, `warm_concern`, `alert`, `neutral`, `playful`, `thoughtful`, `apologetic`. | Covers Counselor's emotional repertoire from AD-718a personality data. Larger taxonomies are forward marker AD-722a-3 (per-agent custom palettes). |
| 3 | Tag format + strip | **`<intent emotion=NAME>` (case-insensitive NAME). Strip regex: `r"\s*<intent\s+emotion\s*=\s*([a-z_]+)\s*/?\s*>\s*$"` (multi-line, IGNORECASE).** | Anchored to end-of-reply (`$` with re.MULTILINE), one tag per reply, tolerant of self-closing slash. The strip MUST run server-side before the response leaves the chat handler — never leak the tag to the Captain. |
| 4 | Intent → expected-rules mapping | **`INTENT_EXPECTED_RULES: dict[str, frozenset[str]]`** — see §6 D2 for full table. Built from the existing `apply_voice_modulation` fired-rule names (`"responding_rate"`, `"blocked_rate_pitch"`, `"high_trust_pitch"`, `"low_trust_pitch"`, `"tier3_rate_volume"`). | Deterministic comparison ground. The agent's INTENT names a target affective state; the modulation table names rules that fired given the current signal context. Match = expected-rule subset is satisfied by applied rules. |
| 5 | Match score + signed divergence | **`match_score = jaccard(expected, applied)`.** **`signed_divergence = +/- (1 - match_score)`** with sign determined by the `INTENT_DIRECTION` table (warm/playful = positive direction = `+pitch`; firm/thoughtful/apologetic = negative direction = `-pitch`; neutral/alert/warm_concern = neutral direction). Positive when applied modulation MATCHES the intent's directional axis but exceeds it; negative when applied diverges to the OPPOSITE axis. | Asymmetric: same-direction-overshoot informs but does not punish (per AD-727 dampening). Opposite-axis is true divergence and earns trust delta. |
| 6 | Trust thresholds + asymmetric weighting | **Two thresholds:** `divergence_negative_threshold: float = 0.3` (gate for output-diverged-AWAY trust hit) and `divergence_positive_threshold: float = 0.5` (gate for output-exceeded-SAME-direction trust reward — higher bar because the positive update is soft). **Two weights:** `divergence_negative_weight: float = 0.4` and `divergence_positive_weight: float = 0.1`. All four configurable on `AvatarTelemetryConfig`. | Asymmetric in BOTH threshold AND weight: penalty fires sooner and weighs heavier than reward, per AD-727's dampening principle. Positive divergence is a soft informational signal; negative divergence is a real coherence failure. |
| 7 | Hebbian wiring | **`runtime.hebbian_router.record_interaction(source=agent_id, target=f"avatar:emotion:{intent_emotion}", success=(match_score >= 0.7), rel_type="avatar_intent")`.** | New `rel_type` namespace `"avatar_intent"` keeps these edges separate from intent-routing weights. Target-string format matches the existing intent_id pattern (string namespace, not agent_id) — `_is_utility_pair` is a no-op because the target is not registered. |
| 8 | DivergenceResult storage | **`runtime.divergence_results: dict[str, DivergenceResult]`** initialized in `__init__` adjacent to `avatar_event_bus` (Wave 142 pattern). | Centralized — same access pattern as `avatar_sampling_state`. Per-agent on `CognitiveAgent` was rejected: divergence is a runtime-level observation, not agent-private state, and putting it on the runtime makes the next-cycle injection from `_build_avatar_self_observation` a simple lookup. |
| 9 | Where the detector fires | **`routers/agents.py:agent_chat`, between line 763 (post-process complete) and line 908 (`mark_reply_emitted` call).** Single call site; mirrors AD-722 / AD-722b single-site invariant. | Reply is finalized post-line-763. `agent._last_self_avatar_snap` was populated by the on-demand `observe_self_avatar()` upstream OR is None (graceful degrade). The detector reads the snapshot, parses the tag, computes divergence, mutates trust + Hebbian, stores the result on runtime, AND strips the tag from `response_text` before line 908. |
| 10 | DM-only scope (chain deferred) | **AD-722a v1 wires DM only.** Chain reply-emission has no equivalent single emit point (compose step output flows through multiple intermediate phases). Forward marker AD-722a-2. | Preserves the AD-722 single-call-site invariant exactly. Chain integration earns its own AD because (a) it requires a chain-side `mark_reply_emitted` analogue, and (b) its emit semantics differ — chain compose may emit to multiple destinations (DM, WR, none). |
| 11 | Sensorium-block phrasing rule | **OUTPUT-as-subject, not agent-as-subject.** Allowed: *"Your last reply was intended as `warm` but the modulation came out as `blocked_rate_pitch` (signed divergence: -0.42)."* Forbidden: *"You sounded cold."* / *"You came across as harsh."* / *"Your tone was off."* | Inherits AD-727 rule #8 translated from RENDERER to OUTPUT. The semantic boundary protects the agent from internalising a deterministic rule-table mismatch as an identity failure. Defensive regex test enforces the boundary (D8). |
| 12 | AD-727 rule #1 inheritance check | **AD-722a is reasoning-vs-output divergence — AD-727 explicitly authorizes trust wiring on this category.** Compare AD-727 rule #1: *"Aesthetic self-judgment is READ-ONLY with respect to trust/Hebbian. Divergence detector (AD-722a) can wire to trust; AD-722e's image-based observations cannot."* | The detector ingests no pixels, invokes no vision LLM, and never compares image to model. By construction, the divergence signal is bounded to the modulation rule table (a deterministic projection from the agent's CrewProfile + signals). This is the precise category AD-727 authorizes for trust wiring. |

---

## 5. Scope (this AD only)

Single commit. Five surfaces touched + two new files:

1. **Add** `src/probos/avatars/divergence_detector.py` — `EmotionalIntent` enum, `DivergenceResult` frozen dataclass, `INTENT_EXPECTED_RULES` table, `INTENT_DIRECTION` table, `parse_intent_self_tag(text)`, `strip_intent_self_tag(text)`, `compute_divergence(intent, modulation)`, `REL_AVATAR_INTENT` constant.
2. **Modify** `src/probos/config.py` — extend `AvatarTelemetryConfig` with `divergence_detection: bool = False` + 3 threshold/weight fields + validators.
3. **Modify** `src/probos/runtime.py` — initialize `self.divergence_results: dict[str, DivergenceResult] = {}` in `__init__()` adjacent to `self.avatar_event_bus` (Wave 142 pattern).
4. **Modify** `src/probos/cognitive/cognitive_agent.py` — add `_build_intent_self_tag_instruction(self) -> str` method, call it adjacent to existing `_build_avatar_self_observation` at the DM inline-assemble site (line 5155 region) AND at the chain `_build_cognitive_baseline` site (line 4537 region) so the LLM is told to emit the tag in both reasoning paths. Extend `_build_avatar_self_observation` to append a divergence-note line when `runtime.divergence_results[agent_id]` is set.
5. **Modify** `src/probos/routers/agents.py` — add the divergence-detector call between line 763 (post-process complete) and line 908 (`mark_reply_emitted`). Tier-2 wrapped — never blocks the reply.
6. **Add** `tests/test_ad722a_divergence_detector.py` — boundary tests.

---

## 6. Non-goals (deferred forward markers)

| Marker | Deferred to | Why not v1 |
|---|---|---|
| **AD-722a-1** | Vision-LLM intent-divergence (semantic check beyond rule-table comparison) | v1 is rule-table comparison. Vision is AD-728's territory. |
| **AD-722a-2** | Chain-path divergence detection at compose-step emit | v1 is DM-only to preserve the single-call-site invariant. Chain emit is structurally more complex (multi-destination, multi-phase). |
| **AD-722a-3** | Per-agent custom emotion taxonomy | v1 is a fixed taxonomy of 8. Per-agent palettes need governance + Counselor review. |
| **AD-722a-4** | Auto-correction loop (re-modulate when divergence detected) | v1 observes only. Correction inverts the read-only contract — needs its own AD. |
| **AD-722a-5** | Divergence history surface in `<SelfImageTab>` | v1 stores only the most-recent result per agent. History + analytics is its own surface. |
| **AD-722a-6** | Cross-agent divergence observations (peer perception of intent-vs-presentation) | Pairs with AD-729 peer perception. |

Reviewer fails the prompt if any deliverable touches `voice.ts`, `CognitiveCanvas.tsx`, `agents.tsx`, `animations.tsx`, `CrewVRM.tsx`, `ParametricAvatar.tsx`, `pyproject.toml`, `ui/package.json`, the existing GET `/avatar-telemetry` HTTP endpoint, the WS `/avatar-telemetry-stream` endpoint, AD-722f's sampling state machine, or AD-722b's connection manager / event bus.

---

## 7. Deliverables

### D1 — `divergence_detector.py` (`src/probos/avatars/divergence_detector.py`, new file)

```python
"""AD-722a: intent-vs-presentation divergence detector.

Pure module. Zero I/O. Zero LLM calls. Compares the LLM's own
``<intent emotion=…>`` self-tag against the modulation rule output of
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
from typing import Final

logger = logging.getLogger(__name__)


# ── Hebbian rel_type namespace (string constant; no edit to routing.py)
REL_AVATAR_INTENT: Final[str] = "avatar_intent"


class EmotionalIntent(str, Enum):
    """v1 emotion taxonomy. Per-agent palettes is forward marker AD-722a-3."""

    WARM = "warm"
    FIRM = "firm"
    WARM_CONCERN = "warm_concern"
    ALERT = "alert"
    NEUTRAL = "neutral"
    PLAYFUL = "playful"
    THOUGHTFUL = "thoughtful"
    APOLOGETIC = "apologetic"


# ── Intent → expected fired_rules subset ────────────────────────────────
# Keys MUST be the str values from EmotionalIntent. Values MUST be subsets
# of the modulation rule names from telemetry.py:apply_voice_modulation
# (`'responding_rate'`, `'blocked_rate_pitch'`, `'high_trust_pitch'`,
# `'low_trust_pitch'`, `'tier3_rate_volume'`).
#
# Empty frozenset means "no specific rules expected" — the intent is
# compatible with neutral modulation.
INTENT_EXPECTED_RULES: Final[dict[str, frozenset[str]]] = {
    EmotionalIntent.WARM.value:         frozenset({"high_trust_pitch"}),
    EmotionalIntent.FIRM.value:         frozenset({"low_trust_pitch"}),
    EmotionalIntent.WARM_CONCERN.value: frozenset({"blocked_rate_pitch"}),
    EmotionalIntent.ALERT.value:        frozenset({"tier3_rate_volume"}),
    EmotionalIntent.NEUTRAL.value:      frozenset(),
    EmotionalIntent.PLAYFUL.value:      frozenset({"responding_rate", "high_trust_pitch"}),
    EmotionalIntent.THOUGHTFUL.value:   frozenset(),
    EmotionalIntent.APOLOGETIC.value:   frozenset({"low_trust_pitch"}),
}


# ── Intent → directional axis ───────────────────────────────────────────
# +1 = warmer/brighter (high pitch / warmer)
# -1 = firmer/lower (low pitch / cooler)
#  0 = neutral (neither axis is the divergence target)
INTENT_DIRECTION: Final[dict[str, int]] = {
    EmotionalIntent.WARM.value:          +1,
    EmotionalIntent.FIRM.value:          -1,
    EmotionalIntent.WARM_CONCERN.value:   0,
    EmotionalIntent.ALERT.value:          0,
    EmotionalIntent.NEUTRAL.value:        0,
    EmotionalIntent.PLAYFUL.value:       +1,
    EmotionalIntent.THOUGHTFUL.value:    -1,
    EmotionalIntent.APOLOGETIC.value:    -1,
}


# ── Self-tag parse + strip regexes (server-side, single source of truth)
# Matches `<intent emotion=NAME>` or `<intent emotion=NAME/>` at end-of-line,
# anywhere in the reply (multi-line). NAME is `[a-z_]+` after lowercase.
_TAG_RE: Final[re.Pattern[str]] = re.compile(
    r"<intent\s+emotion\s*=\s*([a-zA-Z_]+)\s*/?\s*>",
    re.IGNORECASE,
)
# Strip regex anchored to optional trailing whitespace at end of reply.
_TAG_STRIP_RE: Final[re.Pattern[str]] = re.compile(
    r"\s*<intent\s+emotion\s*=\s*[a-zA-Z_]+\s*/?\s*>\s*$",
    re.IGNORECASE | re.MULTILINE,
)


@dataclass(frozen=True)
class DivergenceResult:
    """Result of comparing intent self-tag against applied modulation.

    All fields required (no defaults) — frozen-dataclass field-ordering
    discipline preserved.

    - ``intent_emotion``: parsed self-tag value (one of EmotionalIntent).
    - ``applied_fired_rules``: tuple from ModulationSnapshot.fired_rules.
    - ``match_score``: Jaccard(expected, applied) in [0.0, 1.0].
      1.0 = expected ⊆ applied; 0.0 = no overlap (also when expected is
      empty AND applied is non-empty — modulation moved when intent
      asked for stillness).
    - ``signed_divergence``: in [-1.0, +1.0]. Sign determined by
      INTENT_DIRECTION × applied-direction; magnitude = (1 - match_score).
      Negative = applied diverged to opposite axis. Positive = applied
      moved on the SAME directional axis but stronger than expected
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


def parse_intent_self_tag(text: str) -> str | None:
    """Extract the emotion name from an `<intent emotion=NAME>` tag.

    Returns the lowercased name when a valid taxonomy member is found,
    otherwise ``None`` (graceful degrade — the caller skips the
    divergence pipeline entirely on None).
    """
    if not text:
        return None
    match = _TAG_RE.search(text)
    if match is None:
        return None
    name = match.group(1).strip().lower()
    if name not in INTENT_EXPECTED_RULES:
        # Unknown emotion in taxonomy — log debug, ignore.
        logger.debug(
            "AD-722a: parsed intent tag with unknown emotion=%r; ignoring",
            name,
        )
        return None
    return name


def strip_intent_self_tag(text: str) -> str:
    """Remove the trailing `<intent emotion=…>` tag from a reply.

    Server-side strip — the tag MUST NEVER reach the Captain. Trims
    trailing whitespace produced by the strip. Idempotent — calling
    twice on the same text returns the same result.
    """
    if not text:
        return text
    return _TAG_STRIP_RE.sub("", text).rstrip()


def _applied_direction(applied: tuple[str, ...]) -> int:
    """Internal: project the applied fired_rules onto the directional axis.

    +1 if rules indicate warmer modulation (high_trust_pitch dominates).
    -1 if firmer (low_trust_pitch / blocked_rate_pitch dominate).
     0 if neutral or mixed-cancelling.
    """
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
    (caller's responsibility — ``parse_intent_self_tag`` filters).
    """
    expected = INTENT_EXPECTED_RULES.get(intent_emotion, frozenset())
    applied_set = frozenset(applied_fired_rules)

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
```

### D2 — Config: divergence fields on `AvatarTelemetryConfig`

**Modify** `src/probos/config.py`.

**SEARCH** (around line 990-995):

```python
    enabled: bool = True
    inject_into_agent_context: bool = False  # Feature-gated; default OFF.
    mouth_active_window_seconds: float = 3.0
    polling_interval_ms: int = 2000          # AD-722 — UI hint, not backend-driven.
    sampling_rates: SamplingRatesConfig = Field(default_factory=SamplingRatesConfig)  # AD-722f
    max_connections_per_agent: int = 4       # AD-722b — WS popout connections per agent
```

**REPLACE** with:

```python
    enabled: bool = True
    inject_into_agent_context: bool = False  # Feature-gated; default OFF.
    mouth_active_window_seconds: float = 3.0
    polling_interval_ms: int = 2000          # AD-722 — UI hint, not backend-driven.
    sampling_rates: SamplingRatesConfig = Field(default_factory=SamplingRatesConfig)  # AD-722f
    max_connections_per_agent: int = 4       # AD-722b — WS popout connections per agent
    # AD-722a: intent-vs-presentation divergence detector.
    # Default OFF — operator opt-in for token cost (~10 prompt + ~5 reply
    # tokens per DM cycle). When True, the LLM is instructed to append
    # `<intent emotion=…>` to every DM reply, the server parses + strips
    # it, and divergence drives trust + Hebbian updates.
    divergence_detection: bool = False
    divergence_negative_threshold: float = 0.3   # |magnitude| > this fires NEGATIVE trust delta (output diverged AWAY)
    divergence_positive_threshold: float = 0.5   # |magnitude| > this fires POSITIVE trust delta (output exceeded SAME direction; higher bar)
    divergence_negative_weight: float = 0.4   # Output diverged AWAY (asymmetric heavier)
    divergence_positive_weight: float = 0.1   # Output exceeded same direction (soft inform)
```

**Insert** field validators (after `_bound_max_connections`, around line 1018):

```python
    @field_validator(
        "divergence_negative_threshold",
        "divergence_positive_threshold",
        "divergence_negative_weight",
        "divergence_positive_weight",
    )
    @classmethod
    def _bound_divergence_weights(cls, v: float) -> float:
        if not (0.0 <= v <= 1.0):
            raise ValueError(
                f"divergence weight/threshold fields must be in [0.0, 1.0], got {v}"
            )
        return v
```

### D3 — Runtime initialization

**Modify** `src/probos/runtime.py`.

**SEARCH** the AD-722b initialization block (around lines 420-431):

```python
        # AD-722b: avatar-telemetry WS push channel — event bus + connection
        # manager. Co-located with sampling_state for the same lifecycle
        # discipline (eager __init__, volatile across restarts).
        from probos.avatars.events import AvatarEventBus
        from probos.avatars.ws_connection_manager import (
            AvatarTelemetryConnectionManager,
        )
        self.avatar_event_bus = AvatarEventBus()
        self.avatar_telemetry_connection_manager = AvatarTelemetryConnectionManager(
            max_per_agent=self.config.avatar_telemetry.max_connections_per_agent,
        )
```

**REPLACE** with:

```python
        # AD-722b: avatar-telemetry WS push channel — event bus + connection
        # manager. Co-located with sampling_state for the same lifecycle
        # discipline (eager __init__, volatile across restarts).
        from probos.avatars.events import AvatarEventBus
        from probos.avatars.ws_connection_manager import (
            AvatarTelemetryConnectionManager,
        )
        self.avatar_event_bus = AvatarEventBus()
        self.avatar_telemetry_connection_manager = AvatarTelemetryConnectionManager(
            max_per_agent=self.config.avatar_telemetry.max_connections_per_agent,
        )

        # AD-722a: most-recent intent-vs-presentation divergence per agent.
        # Volatile (cleared on restart). Populated by the divergence detector
        # call site in routers/agents.py:agent_chat; consumed by
        # cognitive_agent._build_avatar_self_observation for next-cycle
        # injection. Type: dict[agent_id, DivergenceResult].
        self.divergence_results: dict[str, "DivergenceResult"] = {}
```

(The forward-reference quoting `"DivergenceResult"` avoids a module-level import cycle. If `runtime.py` already has a `TYPE_CHECKING` block, add the import there; otherwise the string annotation is sufficient — Python doesn't evaluate string annotations at runtime.)

### D4 — System-prompt instruction injection

**Modify** `src/probos/cognitive/cognitive_agent.py`. Add the new method adjacent to `_build_avatar_self_observation` (around line 2659, before or after as fits the file).

**Insert** new method:

```python
    def _build_intent_self_tag_instruction(self) -> str:
        """AD-722a (feature-gated): instruct the LLM to emit a self-tag.

        Returns a one-line instruction when
        ``avatar_telemetry.divergence_detection`` is True; empty string
        otherwise. The line is appended to the system prompt in DM and
        chain reasoning paths so the parser at the chat handler can
        extract + strip the tag and compute divergence.

        Token cost: ~10 prompt tokens + ~5 reply tokens per cycle.
        """
        cfg = getattr(self._runtime, "config", None) if self._runtime else None
        tcfg = getattr(cfg, "avatar_telemetry", None)
        if not getattr(tcfg, "divergence_detection", False):
            return ""
        return (
            "After your reply, on a new line, emit "
            "`<intent emotion=NAME>` where NAME is one of: "
            "warm | firm | warm_concern | alert | neutral | playful | "
            "thoughtful | apologetic. The tag will be stripped server-side; "
            "do not mention it in your prose."
        )
```

**SEARCH** the chain-path injection (around line 4537):

```python
            avatar_block = self._build_avatar_self_observation(observation or {})
```

**REPLACE** with:

```python
            avatar_block = self._build_avatar_self_observation(observation or {})
            # AD-722a: append the self-tag instruction (default OFF).
            _intent_tag_line = self._build_intent_self_tag_instruction()
            if _intent_tag_line:
                avatar_block = (avatar_block + "\n" + _intent_tag_line).strip("\n") + "\n"
```

**SEARCH** the DM-path injection (around line 5155):

```python
            try:
                _avatar_block = self._build_avatar_self_observation(observation)
                if _avatar_block:
                    parts.append(_avatar_block)
                    parts.append("")
            except Exception:
                logger.debug(
                    "AD-722: avatar self-observation injection in DM path failed",
                    exc_info=True,
                )
```

**REPLACE** with:

```python
            try:
                _avatar_block = self._build_avatar_self_observation(observation)
                if _avatar_block:
                    parts.append(_avatar_block)
                    parts.append("")
                # AD-722a: append the self-tag instruction (default OFF).
                _intent_tag_line = self._build_intent_self_tag_instruction()
                if _intent_tag_line:
                    parts.append(_intent_tag_line)
                    parts.append("")
            except Exception:
                logger.debug(
                    "AD-722: avatar self-observation injection in DM path failed",
                    exc_info=True,
                )
```

### D5 — Divergence-note injection in `_build_avatar_self_observation`

**Modify** `src/probos/cognitive/cognitive_agent.py`. Extend the existing method (line 2659) — append a divergence-note block at the end when `runtime.divergence_results[self.id]` is set.

**SEARCH** the final return inside `_build_avatar_self_observation` (around line 2696-2700, the assembled return string):

```python
            return (
                "Your current avatar state:\n"
                f"  expression_resting: {snap.expression_resting}\n"
                f"  working_state: {snap.current_signals.working_state}\n"
                + mod_line
                + f"  mouth_active: {snap.mouth_active}\n"
                + dsl_line
            )
```

**REPLACE** with:

```python
            base = (
                "Your current avatar state:\n"
                f"  expression_resting: {snap.expression_resting}\n"
                f"  working_state: {snap.current_signals.working_state}\n"
                + mod_line
                + f"  mouth_active: {snap.mouth_active}\n"
                + dsl_line
            )
            # AD-722a: append divergence note (OUTPUT-as-subject phrasing,
            # per AD-727 rule #8 translated to OUTPUT). Looked up by agent_id
            # on the runtime; tier-2 degrade if missing.
            divergence_note = self._build_divergence_note()
            if divergence_note:
                base = base + "\n" + divergence_note
            return base
```

**Insert** the helper method below `_build_avatar_self_observation`:

```python
    def _build_divergence_note(self) -> str:
        """AD-722a: render the most-recent divergence as an OUTPUT-subject note.

        Phrasing rule: subject is OUTPUT, never the agent. Allowed text uses
        constructions like *"Your last reply was intended as X but the
        modulation came out as Y"*. Forbidden constructions: *"You sounded …"*,
        *"You came across as …"*, *"Your tone was …"*, *"You seem …"*.

        Tier-2 — returns empty string on any failure.
        """
        try:
            rt = getattr(self, "_runtime", None)
            if rt is None:
                return ""
            results = getattr(rt, "divergence_results", None)
            if not results:
                return ""
            result = results.get(self.id)
            if result is None:
                return ""
            applied = ", ".join(result.applied_fired_rules) or "no_rules_fired"
            return (
                "Most recent intent-vs-presentation check:\n"
                f"  Your last reply was intended as `{result.intent_emotion}` "
                f"but the modulation came out as `{applied}` "
                f"(signed divergence: {result.signed_divergence:+.2f}, "
                f"match score: {result.match_score:.2f}).\n"
            )
        except Exception:
            logger.debug(
                "AD-722a: divergence-note rendering failed",
                exc_info=True,
            )
            return ""
```

### D6 — Chat-handler detector call

**Modify** `src/probos/routers/agents.py`. Add the divergence-detector call BETWEEN the response_text post-processing (line 763) and the existing `mark_reply_emitted` block (line 908). Per the AD-722 single-call-site invariant, this is exactly one new call site adjacent to the existing one.

**SEARCH** the existing mark_reply_emitted block (around lines 906-909):

```python
    # AD-722: stamp the last-reply emission timestamp. Single source of truth.
    if hasattr(agent, 'mark_reply_emitted'):
        agent.mark_reply_emitted()
```

**REPLACE** with:

```python
    # AD-722a: intent-vs-presentation divergence detection.
    # Tier-2 wrapped — never blocks a reply. Default OFF
    # (avatar_telemetry.divergence_detection). When ON, the LLM was
    # instructed via _build_intent_self_tag_instruction to append a
    # self-tag at end-of-reply. Parse + strip BEFORE the response leaves
    # the handler; never leak the tag to the Captain.
    try:
        _t_cfg = getattr(runtime.config, "avatar_telemetry", None)
        if _t_cfg is not None and getattr(_t_cfg, "divergence_detection", False):
            from probos.avatars.divergence_detector import (
                DivergenceResult,
                REL_AVATAR_INTENT,
                compute_divergence,
                parse_intent_self_tag,
                strip_intent_self_tag,
            )
            _intent = parse_intent_self_tag(response_text)
            # Strip unconditionally when feature ON — even if parse_intent
            # returned None (unknown emotion / malformed tag), the visible
            # tag must not leak.
            response_text = strip_intent_self_tag(response_text)
            _snap = getattr(agent, "_last_self_avatar_snap", None)
            _modulation = getattr(_snap, "applied_modulation", None) if _snap else None
            if _intent is not None and _modulation is not None:
                _result = compute_divergence(
                    intent_emotion=_intent,
                    applied_fired_rules=tuple(_modulation.fired_rules),
                )
                runtime.divergence_results[agent_id] = _result

                # Trust update — asymmetric thresholds AND weights per AD-727 dampening.
                _trust = getattr(runtime, "trust_network", None)
                if _trust is not None:
                    if (
                        _result.magnitude > _t_cfg.divergence_negative_threshold
                        and _result.signed_divergence < 0
                    ):
                        _trust.record_outcome(
                            agent_id=agent_id,
                            success=False,
                            weight=_result.magnitude * _t_cfg.divergence_negative_weight,
                            intent_type="avatar_divergence",
                            source="avatar_divergence",
                        )
                    elif (
                        _result.magnitude > _t_cfg.divergence_positive_threshold
                            source="avatar_divergence",
                        )

                # Hebbian update — match strengthens, non-match weakens.
                _hebb = getattr(runtime, "hebbian_router", None)
                if _hebb is not None:
                    _hebb.record_interaction(
                        source=agent_id,
                        target=f"avatar:emotion:{_intent}",
                        success=(_result.match_score >= 0.7),
                        rel_type=REL_AVATAR_INTENT,
                    )
    except Exception:
        logger.debug(
            "AD-722a: divergence detector failed for agent=%s",
            agent_id, exc_info=True,
        )

    # AD-722: stamp the last-reply emission timestamp. Single source of truth.
    if hasattr(agent, 'mark_reply_emitted'):
        agent.mark_reply_emitted()
```

`logger` is already imported at the top of `routers/agents.py` — verify at HEAD before editing. The `from probos.avatars.divergence_detector import …` is local (inside the try-block) to avoid module-load cost when the feature is OFF (the default).

### D7 — Hebbian rel-type registration

**No edit to `src/probos/mesh/routing.py`.** The `record_interaction(rel_type=…)` parameter accepts arbitrary string values and `_is_utility_pair` is a no-op when target is not a registered agent_id (the target string `"avatar:emotion:warm"` is namespaced; never registered as an agent). The `REL_AVATAR_INTENT` constant lives in `divergence_detector.py` per D1.

### D8 — Python tests (`tests/test_ad722a_divergence_detector.py`, new file)

**≥ 18 tests.** Mirror the `_make_runtime` / `_endpoint_runtime` pattern from `tests/test_ad722_avatar_telemetry.py` and the `_FakeTrustNetwork` / `_FakeHebbianRouter` patterns. Use REAL `TrustNetwork` and `HebbianRouter` for the integration tests in §F — the test-as-spec depends on observing real weight changes.

Required cases (the table is the spec — Builder may consolidate but cannot drop rows):

#### A. Tag parse + strip

| # | Test | Asserts |
|---|---|---|
| 1 | `test_parse_self_tag_happy` | `parse_intent_self_tag("Hello.\n<intent emotion=warm>")` returns `"warm"`. |
| 2 | `test_parse_self_tag_self_closing` | `parse_intent_self_tag("Hello.\n<intent emotion=firm/>")` returns `"firm"`. |
| 3 | `test_parse_self_tag_uppercase_emotion` | `parse_intent_self_tag("...\n<intent emotion=WARM>")` returns `"warm"`. |
| 4 | `test_parse_self_tag_unknown_emotion` | `parse_intent_self_tag("...\n<intent emotion=feisty>")` returns `None`. |
| 5 | `test_parse_self_tag_missing` | `parse_intent_self_tag("Hello, Captain.")` returns `None`. |
| 6 | `test_strip_self_tag_idempotent` | `strip_intent_self_tag(strip_intent_self_tag(text))` equals one application. |
| 7 | `test_strip_self_tag_does_not_touch_prose` | `strip_intent_self_tag("I am intent on warmth.")` returns the input unchanged. |

#### B. compute_divergence — match cases

| # | Test | Asserts |
|---|---|---|
| 8 | `test_divergence_warm_intent_warm_modulation` | `compute_divergence("warm", ("high_trust_pitch",))` → `match_score == 1.0`, `magnitude == 0.0`, `signed_divergence == 0.0`. |
| 9 | `test_divergence_neutral_intent_no_rules` | `compute_divergence("neutral", ())` → `match_score == 1.0`, `magnitude == 0.0`. |
| 10 | `test_divergence_neutral_intent_with_rules` | `compute_divergence("neutral", ("tier3_rate_volume",))` → `match_score == 0.0`, `magnitude == 1.0`. |

#### C. compute_divergence — divergence cases (asymmetric sign)

| # | Test | Asserts |
|---|---|---|
| 11 | `test_divergence_warm_intent_firm_modulation_negative` | `compute_divergence("warm", ("low_trust_pitch",))` → `match_score == 0.0`, `magnitude == 1.0`, `signed_divergence == -1.0` (opposite-axis). |
| 12 | `test_divergence_warm_intent_blocked_negative` | `compute_divergence("warm", ("blocked_rate_pitch",))` → `signed_divergence < 0`. |
| 13 | `test_divergence_firm_intent_warm_modulation_negative` | `compute_divergence("firm", ("high_trust_pitch",))` → `signed_divergence == -1.0`. |
| 14 | `test_divergence_warm_intent_responding_only_positive` | `compute_divergence("warm", ("responding_rate",))` — applied has no warmth-direction rule but no opposite either; `signed_divergence > 0` (same/neutral axis, informational). |

#### D. Trust + Hebbian wiring (chat-handler integration)

| # | Test | Asserts |
|---|---|---|
| 15 | `test_chat_handler_strips_tag_from_response` | Mock LLM returns `"Hello.\n<intent emotion=warm>"`; `divergence_detection=True`. POST `/api/agent/{id}/chat` → response.json()["response"] does NOT contain `<intent`. |
| 16 | `test_chat_handler_no_strip_when_feature_off` | `divergence_detection=False`; LLM returns same. Response WITH tag (no detection runs at all — but defense-in-depth: also test that with feature ON and tag absent, nothing crashes). |
| 17 | `test_chat_handler_negative_divergence_weakens_trust` | Real `TrustNetwork`; agent's prior alpha/beta. LLM returns `"...\n<intent emotion=warm>"` while `_last_self_avatar_snap.applied_modulation.fired_rules == ("low_trust_pitch",)` (low-trust signal forced via signals override). After chat → `trust.get_score(agent_id)` decreased by an amount proportional to `magnitude * negative_weight` (use `pytest.approx` with absolute tolerance ≥ 0.001; do not assert exact arithmetic — TrustNetwork has dampening). |
| 18 | `test_chat_handler_positive_divergence_rewards_trust` | Same harness; LLM intent=warm, modulation has `("responding_rate",)` (same/neutral axis but moved). `trust.get_score(agent_id)` INCREASED by a smaller amount (positive weight is lighter). |
| 19 | `test_chat_handler_below_negative_threshold_no_trust_update` | Tag intent=warm; modulation also produces `high_trust_pitch` → `magnitude == 0.0`, below negative threshold. Trust score UNCHANGED. |
| 19b | `test_chat_handler_between_positive_thresholds_no_reward` | Tag intent=warm; modulation produces a SAME-direction state with `magnitude == 0.4` (between negative_threshold=0.3 and positive_threshold=0.5; signed positive). Trust score UNCHANGED (positive path requires |magnitude| > 0.5). |
| 20 | `test_chat_handler_match_strengthens_hebbian` | Real `HebbianRouter`. After a match (intent=warm, applied=`("high_trust_pitch",)`): `hebbian.get_weight(agent_id, "avatar:emotion:warm", REL_AVATAR_INTENT) > 0.0`. |
| 21 | `test_chat_handler_mismatch_weakens_hebbian` | First a match strengthens to non-zero; then an opposite-axis mismatch — final weight < the post-match weight. |

#### E. Sensorium injection (next-cycle)

| # | Test | Asserts |
|---|---|---|
| 22 | `test_build_avatar_self_observation_with_divergence` | Pre-populate `runtime.divergence_results[agent_id] = DivergenceResult(...)` with `signed_divergence == -0.42, intent_emotion="warm", applied_fired_rules=("blocked_rate_pitch",)`. Set `inject_into_agent_context=True` and a cached `_last_self_avatar_snap`. Call `agent._build_avatar_self_observation({})` → return text contains `"intended as \`warm\`"` AND `"modulation came out as \`blocked_rate_pitch\`"` AND `"-0.42"`. |
| 23 | `test_build_avatar_self_observation_without_divergence` | `runtime.divergence_results == {}`. Same call → return text does NOT contain `"intent-vs-presentation"`. |
| 24 | `test_divergence_note_phrasing_rule` (DEFENSIVE — AD-727 #8) | Render the divergence note for every entry in `EmotionalIntent` (8 cases) × representative applied tuples. For each rendered note, assert that `re.search(r"\byou (?:sound|sounded|came across|seem|seemed|are|were|feel|felt)\b", text, re.IGNORECASE)` is `None`. The rendered text is OUTPUT-as-subject by construction, but the test is the forcing function that catches future regressions in `_build_divergence_note`. |

#### F. Self-tag instruction injection

| # | Test | Asserts |
|---|---|---|
| 25 | `test_intent_self_tag_instruction_off_by_default` | Fresh runtime; `cfg.avatar_telemetry.divergence_detection == False` (default). `agent._build_intent_self_tag_instruction()` returns `""`. |
| 26 | `test_intent_self_tag_instruction_when_on` | `cfg.avatar_telemetry.divergence_detection = True`. Method returns a string containing `"<intent emotion=NAME>"` and the full taxonomy `"warm | firm | warm_concern | alert | neutral | playful | thoughtful | apologetic"`. |

(26 tests is the floor — Builder may consolidate where overlap is genuine; cases #15-#21 may share a fixture.)

#### Test infrastructure notes

- For the chat-handler integration tests in §D, build an `_endpoint_runtime` similar to `tests/test_ad722_avatar_telemetry.py`'s pattern but with REAL `TrustNetwork(data_dir=tmp_path)` and `HebbianRouter()` (rather than MagicMocks). The trust math is tested elsewhere; here we only assert directional change (decreased / increased / unchanged), never exact arithmetic.
- The cached `agent._last_self_avatar_snap` is populated upstream by `observe_self_avatar()` in the production path. Tests pre-populate it directly to bypass the snapshot-build chain.
- Mock LLM client returns deterministic strings ending in `<intent emotion=…>` to drive the parse path.
- The test of cases #15-#21 forms a focused sub-suite; mark with `@pytest.mark.asyncio` per existing convention.

---

## 8. Tests required

- **Python:** ≥ 18 boundary tests in `tests/test_ad722a_divergence_detector.py`. The 26-row table in D8 is the floor.
- **Vitest:** **No UI changes; no Vitest delta.** Existing 561+ vitest tests stay green.
- **Existing tests must stay green** — `test_ad722_avatar_telemetry.py`, `test_ad722f_adaptive_sampling.py`, `test_ad722b_websocket_push.py`, `test_ad722_*.py` should be unaffected.

---

## 9. Hard-stop conditions

The Builder MUST stop and surface to architect (do not improvise) when:

1. **AD-727 rule #1 violated.** Any deliverable introduces a trust delta tied to image-based or aesthetic judgment. This AD's trust wiring is bounded to the `(intent_emotion, fired_rules)` tuple by construction; if a deliverable ingests pixels or invokes a vision LLM, hard stop.
2. **Read-only contract on AD-722e/AD-728 territory violated.** AD-722a does NOT touch self-perception (AD-722e) or render-coherence (AD-728) surfaces. Any deliverable that imports from those (forward-marker) modules is out of scope.
3. **Multiple `mark_reply_emitted` call sites.** AD-722's invariant: exactly one call site in production source. AD-722a's detector call sits in the SAME single block, immediately before `mark_reply_emitted`. If the chat handler's reply-emission path gains a second site, the call moves into a private helper named `_finalize_chat_reply` (mirrors AD-722 D6 approach) — but verify with architect before refactoring.
4. **Phantom API discovered.** Any concrete claim in §2 fails to verify against the actual codebase at the Builder's commit time. **Especially watch for**: the cluster plan's `runtime.trust_network.observe(...)` is a phantom (real method is `record_outcome`). The cluster plan's "Hebbian wiring" wording is non-normative; this prompt's `record_interaction(...)` invocation is the canonical signature.
5. **WR or chain reply-emit wired.** v1 is DM-only (AD-722a-2 is the chain forward marker). Any divergence detector call placed inside `_run_cognitive_lifecycle`'s chain branch, or inside any WR-post code path, is out of scope.
6. **Intent tag leaks to Captain.** The strip MUST be unconditional when `divergence_detection=True` — even on parse failure. Reviewer fails any code path that returns `<intent emotion=…>` text in the response payload when the feature is ON.
7. **Trust update without threshold gate.** Every `trust_network.record_outcome(... source="avatar_divergence")` call MUST be guarded by the appropriate asymmetric threshold: `magnitude > divergence_negative_threshold` for the `signed_divergence < 0` branch; `magnitude > divergence_positive_threshold` for the `signed_divergence > 0` branch. No unconditional updates.
8. **HXI-fragile file touched.** `CognitiveCanvas.tsx`, `agents.tsx`, `animations.tsx`, `CrewVRM.tsx`, `ParametricAvatar.tsx`, `voice.ts` MUST stay untouched. AD-722a has zero UI surface in v1.
9. **Existing AD-722 / AD-722f / AD-722-1 / AD-722b tests break.** The detector is additive — `_build_avatar_self_observation` gains a conditional appended block, but its return text when `runtime.divergence_results[agent_id]` is unset MUST be byte-identical to HEAD.
10. **New top-level dep.** `pyproject.toml` and `ui/package.json` MUST be bit-for-bit identical pre/post commit.

**HARD RULE — UI build gate:** AD-722a has no UI changes. `cd ui && npm run build` is a sanity check only, not a feature gate. Run it anyway and confirm green.

---

## 10. Wave-specific reminders

1. **Trust API is `record_outcome`, NOT `observe`.** The cluster plan's phantom is corrected in this prompt. Use the verified six-parameter signature from §2.
2. **Hebbian rel_type is `"avatar_intent"` (string namespace).** No edit to `routing.py`'s `REL_*` constants — the `record_interaction(rel_type=…)` parameter accepts any string. The constant `REL_AVATAR_INTENT` lives in `divergence_detector.py`.
3. **Strip-before-leak is unconditional when feature ON.** Even when `parse_intent_self_tag` returns `None` (unknown emotion / malformed), the strip runs to prevent visible tag leaks.
4. **Asymmetric weighting is non-negotiable.** Negative weight (default 0.4) > positive weight (default 0.1). Per AD-727 dampening principle.
5. **Phrasing rule is regex-tested.** Defensive test #24 (D8) asserts no `r"\byou (?:sound|sounded|came across|seem|seemed|are|were|feel|felt)\b"` matches in any rendered divergence note.
6. **Divergence-note injection lives inside `_build_avatar_self_observation`.** It does NOT add a new sensorium method — that would change `SENSORIUM_REGISTRY` shape. Existing `_build_avatar_self_observation` is extended.
7. **DM only.** Chain reply-emission is forward marker AD-722a-2. Single call site invariant is preserved.
8. **`runtime.divergence_results` is volatile.** Cleared on restart. No persistence in v1.
9. **Verify-first.** Before any concrete file/line/method citation in the implementation, Builder greps HEAD and pastes the result in the commit message body — especially every line number in §2.
10. **AD-numbering check.** Current AD ceiling: AD-729. AD-722a is the AD itself; sub-markers use `AD-722a-1` through `AD-722a-6` per the AD-722b precedent.

---

## 11. Tracking

After AD-722a ships:

1. **`PROGRESS.md`** — flip the AD-722a row to ✅ in Wave 143 section. One-line outcome: *"Intent-vs-presentation divergence detector — `<intent emotion=…>` self-tag parse + strip; magnitude-weighted asymmetric trust delta (negative > positive); Hebbian reinforcement on `(agent_id, avatar:emotion:NAME, REL_AVATAR_INTENT)`; OUTPUT-as-subject divergence note injected into next-cycle INTEROCEPTION block; default OFF."*
2. **`docs/development/roadmap.md`** — close Wave 143 row. File / link the forward markers below.
3. **`DECISIONS.md` + `decisions-era-5-unification.md`** — append AD-722a entry under the AD-722 addendum block. Document: (a) self-tag taxonomy (8 emotions), (b) intent → expected_rules mapping table, (c) Jaccard match score + signed-divergence axes, (d) asymmetric weighting (0.4 negative / 0.1 positive defaults), (e) AD-727 rule #1 inheritance check (reasoning-vs-output is fair; not aesthetic), (f) DM-only scope + chain forward marker, (g) phrasing rule with defensive regex test.
4. **GH issues** — close [#567](https://github.com/seangalliher/ProbOS/issues/567) with a summary comment citing the commit SHA. File AD-722a-1 through AD-722a-6 forward markers as new issues (Captain auth required — Builder lacks token scope; Builder lists the marker text in the build report and Captain files via `gh` after).

### Forward markers (Builder lists; Captain files post-build)

| Marker | One-line description |
|---|---|
| **AD-722a-1** | Vision-LLM intent-divergence (semantic match against rendered avatar — distinct from AD-728's render-coherence check). |
| **AD-722a-2** | Chain-path divergence detection at compose-step emit (multi-destination, multi-phase). |
| **AD-722a-3** | Per-agent custom emotion taxonomy (Counselor + governance review required). |
| **AD-722a-4** | Auto-correction loop (re-modulate when divergence detected — inverts read-only contract; needs its own AD). |
| **AD-722a-5** | Divergence history surface in `<SelfImageTab>` (UI consumer of accumulated `divergence_results`). |
| **AD-722a-6** | Cross-agent divergence observations (peer perception of intent-vs-presentation; pairs with AD-729). |

---

## 12. Acceptance criteria

1. ✅ One commit. Reviewer fails any split — AD-722a is a single atomic feature.
2. ✅ `pytest tests/ -q -n 8 --dist=loadfile` green at the commit. Test count delta: ≥ +18.
3. ✅ `cd ui && npx vitest run` green at the commit. Test count delta: 0 (no UI changes).
4. ✅ `cd ui && npm run build` green at the commit (sanity check only).
5. ✅ Existing AD-722 / AD-722f / AD-722-1 / AD-722b tests stay green. Reviewer fails any modification of those test bodies.
6. ✅ `pwsh scripts/phantom-api-precheck.ps1 prompts/ad-722a-divergence-detector.md` clean.
7. ✅ `pyproject.toml [project.dependencies]` AND `ui/package.json` `"dependencies"` + `"devDependencies"` are bit-for-bit identical pre/post commit.
8. ✅ Manual smoke (operator-toggled): set `avatar_telemetry.divergence_detection: true` in `config/system.yaml`. Restart. DM Counselor with a question that should evoke `warm` reasoning. Backend logs show the parsed intent and `DivergenceResult`. The Captain's chat panel shows the reply WITHOUT the `<intent emotion=…>` tag (strip succeeded). Send a follow-up DM; the next reply's INTEROCEPTION block (visible in DEBUG-level prompt log) contains the divergence note in OUTPUT-as-subject phrasing.
9. ✅ Manual smoke: with `divergence_detection: false` (default), DM replies are byte-for-byte unchanged from baseline (no tag emitted, no strip applied, no `divergence_results` populated).
10. ✅ **Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.**
