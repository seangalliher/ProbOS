"""AD-737: per-agent custom emotion taxonomy — boundary tests.

Eight tests:

1. EmotionProfile.inherits must be a v1 name.
2. EmotionProfile shift bounds (±0.15).
3. CrewProfile rejects a custom emotion key that collides with a v1 name.
4. CrewProfile rejects >8 custom emotions.
5. parse_intent_self_tag accepts a custom name when custom_emotions is passed.
6. apply_voice_modulation composes the custom delta on top of the parent's
   v1 factor AND fired_rules contains BOTH the parent ``intent_X`` and the
   ``custom_X`` observability tag.
7. _build_intent_self_tag_instruction includes the agent's custom names.
8. apply_divergence_check parent-equivalence: a zero-shift custom emotion
   that inherits from ``concerned`` produces identical match_score /
   signed_divergence / magnitude as ``concerned`` itself.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from probos.avatars.divergence_detector import (
    EmotionalIntent,
    apply_divergence_check,
    parse_intent_self_tag,
)
from probos.avatars.telemetry import (
    AgentSignalsSnapshot,
    INTENT_RULES,
    apply_voice_modulation,
)
from probos.crew_profile import (
    CrewProfile,
    EmotionProfile,
    VoiceProfile,
)


# ── Fakes ───────────────────────────────────────────────────────────────


def _t_cfg() -> SimpleNamespace:
    return SimpleNamespace(
        divergence_detection=True,
        divergence_negative_threshold=0.3,
        divergence_positive_threshold=0.5,
        divergence_negative_weight=0.4,
        divergence_positive_weight=0.1,
        divergence_history_size=0,
    )


def _make_runtime_with_store(crew: CrewProfile | None) -> SimpleNamespace:
    from probos.consensus.trust import TrustNetwork
    from probos.mesh.routing import HebbianRouter

    runtime = SimpleNamespace()
    runtime.trust_network = TrustNetwork()
    runtime.hebbian_router = HebbianRouter()
    runtime.divergence_results = {}
    if crew is not None:
        store = MagicMock()
        store.get = MagicMock(return_value=crew)
        runtime.profile_store = store
    else:
        runtime.profile_store = None
    return runtime


def _make_agent(agent_id: str, signals: AgentSignalsSnapshot):
    """Agent stub carrying a cached snap; current_signals drives the
    recompute path in apply_divergence_check.
    """
    snap = MagicMock()
    snap.applied_modulation = SimpleNamespace(
        fired_rules=("high_trust_pitch",),
    )
    snap.current_signals = signals
    agent = MagicMock()
    agent.id = agent_id
    agent._last_self_avatar_snap = snap
    return agent


# ── 1. EmotionProfile.inherits must be v1 ───────────────────────────────


def test_emotion_profile_inherits_must_be_v1():
    with pytest.raises(ValueError, match="inherits"):
        EmotionProfile(inherits="not_a_v1_name")
    # Happy path: every v1 emotion is accepted.
    p = EmotionProfile(inherits="concerned")
    assert p.inherits == "concerned"


# ── 2. shift bounds ─────────────────────────────────────────────────────


def test_emotion_profile_shift_bounds():
    with pytest.raises(ValueError, match="pitch_shift"):
        EmotionProfile(inherits="warm", pitch_shift=0.2)
    with pytest.raises(ValueError, match="rate_shift"):
        EmotionProfile(inherits="warm", rate_shift=-0.16)
    # Boundary: ±0.15 inclusive is fine.
    p = EmotionProfile(inherits="warm", pitch_shift=0.15, volume_shift=-0.15)
    assert p.pitch_shift == 0.15
    assert p.volume_shift == -0.15


# ── 3. v1 name collision ────────────────────────────────────────────────


def test_crew_profile_custom_emotion_collides_with_v1():
    with pytest.raises(ValueError, match="collides with v1 taxonomy"):
        CrewProfile(
            agent_id="a1",
            custom_emotions={
                "concerned": EmotionProfile(inherits="formal"),
            },
        )


# ── 4. max 8 ────────────────────────────────────────────────────────────


def test_crew_profile_custom_emotions_max_8():
    # The custom-name regex forbids digits; use letter-only labels.
    _names = (
        "alpha", "beta", "gamma", "delta",
        "epsilon", "zeta", "eta", "theta", "iota",
    )
    # 8 entries: fine.
    eight = {n: EmotionProfile(inherits="neutral") for n in _names[:8]}
    profile = CrewProfile(agent_id="a1", custom_emotions=eight)
    assert len(profile.custom_emotions) == 8
    # 9 entries: rejected.
    nine = {n: EmotionProfile(inherits="neutral") for n in _names[:9]}
    with pytest.raises(ValueError, match="max 8 entries"):
        CrewProfile(agent_id="a1", custom_emotions=nine)


# ── 5. parse_intent_self_tag accepts custom name ────────────────────────


def test_parse_intent_self_tag_accepts_custom_name():
    custom = {
        "professional_concern": EmotionProfile(inherits="concerned"),
    }
    text = "Some reply.\n<intent emotion=professional_concern>"
    # With custom_emotions: parsed as the custom name.
    assert parse_intent_self_tag(text, custom_emotions=custom) == (
        "professional_concern"
    )
    # Without: None (backward-compat path intact — v1-only).
    assert parse_intent_self_tag(text) is None
    # v1 names still work even when custom is passed (short-circuit).
    assert parse_intent_self_tag(
        "Hi.\n<intent emotion=warm>", custom_emotions=custom,
    ) == "warm"


# ── 6. apply_voice_modulation composes custom delta ─────────────────────


def test_apply_voice_modulation_composes_custom_delta_on_inherits():
    profile = VoiceProfile()  # default pitch=0.9, rate=0.95, volume=0.8
    signals = AgentSignalsSnapshot(
        trust_delta=0.0,
        load=0.5,
        working_state="responding",
        tier3_alert=False,
    )
    custom = {
        "professional_concern": EmotionProfile(
            inherits="concerned", pitch_shift=-0.1,
        ),
    }
    snap = apply_voice_modulation(
        profile, signals, intent="professional_concern",
        custom_emotions=custom,
    )
    # The parent's intent_concerned rule fires AND the custom_X tag.
    assert "intent_concerned" in snap.fired_rules, (
        f"missing intent_concerned in {snap.fired_rules!r} — "
        "compute_divergence's startswith('intent_') filter would yield 0.0"
    )
    assert "custom_professional_concern" in snap.fired_rules
    # Pitch is base * concerned_rule_factor * (1 + delta), clamped.
    rule = INTENT_RULES["concerned"]
    expected_pitch = 0.9 * rule["pitch"] * (1.0 - 0.1)
    # responding_rate also fires; doesn't touch pitch.
    assert snap.pitch_factor == pytest.approx(expected_pitch, rel=0.01)


# ── 7. _build_intent_self_tag_instruction includes custom names ─────────


def test_build_intent_self_tag_instruction_includes_custom_names():
    from probos.cognitive.cognitive_agent import CognitiveAgent

    crew = CrewProfile(
        agent_id="agent-007",
        custom_emotions={
            "professional_concern": EmotionProfile(inherits="concerned"),
        },
    )
    store = MagicMock()
    store.get = MagicMock(return_value=crew)
    runtime = SimpleNamespace(
        config=SimpleNamespace(
            avatar_telemetry=SimpleNamespace(divergence_detection=True),
        ),
        profile_store=store,
    )

    # Build agent without going through __init__ (CognitiveAgent has heavy
    # dependencies); only _runtime + id are needed by the method.
    agent = CognitiveAgent.__new__(CognitiveAgent)
    agent._runtime = runtime
    agent.id = "agent-007"

    instruction = agent._build_intent_self_tag_instruction()
    assert "professional_concern" in instruction
    for v1 in ("warm", "concerned", "excited", "apologetic",
               "formal", "playful", "reassuring", "neutral"):
        assert v1 in instruction


# ── 8. parent-equivalence (must-pass scoring invariant) ─────────────────


def test_custom_emotion_divergence_score_equals_parent():
    """AD-737: a zero-shift custom emotion inheriting from ``concerned``
    must produce identical divergence math as ``concerned`` itself.

    Pins the v2-parity contract: any drift here means the dual-tag
    (``intent_X`` + ``custom_X``) and pre-resolution shape is broken.
    """
    custom = {
        "professional_concern": EmotionProfile(inherits="concerned"),
    }
    crew = CrewProfile(agent_id="agent-007", custom_emotions=custom)
    signals = AgentSignalsSnapshot(
        trust_delta=0.0,
        load=0.5,
        working_state="responding",
        tier3_alert=False,
    )
    t_cfg = _t_cfg()

    # Custom branch.
    runtime_custom = _make_runtime_with_store(crew)
    agent_custom = _make_agent("agent-007", signals)
    apply_divergence_check(
        runtime=runtime_custom, agent_id="agent-007", agent=agent_custom,
        response_text="reply.\n<intent emotion=professional_concern>",
        t_cfg=t_cfg,
    )
    result_custom = runtime_custom.divergence_results.get("agent-007")
    assert result_custom is not None

    # Parent branch (same crew but emit the v1 name directly).
    runtime_parent = _make_runtime_with_store(crew)
    agent_parent = _make_agent("agent-007", signals)
    apply_divergence_check(
        runtime=runtime_parent, agent_id="agent-007", agent=agent_parent,
        response_text="reply.\n<intent emotion=concerned>",
        t_cfg=t_cfg,
    )
    result_parent = runtime_parent.divergence_results.get("agent-007")
    assert result_parent is not None

    # Math is identical.
    assert result_custom.match_score == pytest.approx(result_parent.match_score)
    assert result_custom.signed_divergence == pytest.approx(
        result_parent.signed_divergence
    )
    assert result_custom.magnitude == pytest.approx(result_parent.magnitude)
    # Custom name surfaces; parent name surfaces.
    assert result_custom.intent_emotion == "professional_concern"
    assert result_parent.intent_emotion == "concerned"
    # Critical correctness pin: match_score must equal 1.0 for the
    # parent (intent_concerned in fired_rules + expected={intent_concerned}).
    # If this is 0.0, the dual-tag scoring fix is broken.
    assert result_parent.match_score == pytest.approx(1.0), (
        f"match_score for parent = {result_parent.match_score}; "
        "expected 1.0 (intent_concerned should fire and match the "
        "expected rule set). If 0.0, the apply_voice_modulation dual-tag "
        "fix is broken."
    )
    assert result_custom.match_score == pytest.approx(1.0), (
        f"match_score for custom = {result_custom.match_score}; "
        "expected 1.0 (parent-equivalence required)."
    )
