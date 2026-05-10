"""AD-722a: intent-vs-presentation divergence detector — boundary tests.

Six sections per the prompt's D8 spec table:
  A. Tag parse + strip
  B. compute_divergence — match cases
  C. compute_divergence — divergence cases (asymmetric sign)
  D. Trust + Hebbian wiring via apply_divergence_check
  E. Sensorium injection in _build_avatar_self_observation
  F. Self-tag instruction injection

AD-727 rule #1: this test file covers REASONING-vs-OUTPUT divergence only.
Defensive case #24 enforces the OUTPUT-as-subject phrasing rule.
"""
from __future__ import annotations

import re
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from probos.avatars.divergence_detector import (
    INTENT_EXPECTED_RULES,
    REL_AVATAR_INTENT,
    DivergenceResult,
    EmotionalIntent,
    apply_divergence_check,
    compute_divergence,
    parse_intent_self_tag,
    strip_intent_self_tag,
)


# ── Fakes / harness ──────────────────────────────────────────────────────


def _make_t_cfg(
    *,
    divergence_detection: bool = True,
    neg_threshold: float = 0.3,
    pos_threshold: float = 0.5,
    neg_weight: float = 0.4,
    pos_weight: float = 0.1,
) -> SimpleNamespace:
    return SimpleNamespace(
        divergence_detection=divergence_detection,
        divergence_negative_threshold=neg_threshold,
        divergence_positive_threshold=pos_threshold,
        divergence_negative_weight=neg_weight,
        divergence_positive_weight=pos_weight,
    )


def _make_runtime_with_real_trust_hebb(tmp_path):
    """Build a minimal runtime with REAL TrustNetwork + HebbianRouter.

    Used for §D integration tests that need to observe directional trust
    and Hebbian weight changes. In-memory only (no db_path) — fast and
    isolated.
    """
    from probos.consensus.trust import TrustNetwork
    from probos.mesh.routing import HebbianRouter

    runtime = SimpleNamespace()
    runtime.trust_network = TrustNetwork()
    runtime.hebbian_router = HebbianRouter()
    runtime.divergence_results = {}
    return runtime


def _make_agent_with_modulation(agent_id: str, fired_rules: tuple[str, ...]):
    """Agent stub carrying a cached _last_self_avatar_snap.applied_modulation."""
    snap = MagicMock()
    snap.applied_modulation = SimpleNamespace(fired_rules=tuple(fired_rules))
    agent = MagicMock()
    agent.id = agent_id
    agent._last_self_avatar_snap = snap
    return agent


# ── §A. Tag parse + strip ────────────────────────────────────────────────


def test_parse_self_tag_happy():
    assert parse_intent_self_tag("Hello.\n<intent emotion=warm>") == "warm"


def test_parse_self_tag_self_closing():
    assert parse_intent_self_tag("Hello.\n<intent emotion=firm/>") == "firm"


def test_parse_self_tag_uppercase_emotion():
    assert parse_intent_self_tag("Reply.\n<intent emotion=WARM>") == "warm"


def test_parse_self_tag_unknown_emotion():
    assert parse_intent_self_tag("Reply.\n<intent emotion=feisty>") is None


def test_parse_self_tag_missing():
    assert parse_intent_self_tag("Hello, Captain.") is None


def test_strip_self_tag_idempotent():
    text = "Hello, Captain.\n<intent emotion=warm>"
    once = strip_intent_self_tag(text)
    twice = strip_intent_self_tag(once)
    assert once == twice
    assert "<intent" not in once


def test_strip_self_tag_does_not_touch_prose():
    text = "I am intent on warmth."
    assert strip_intent_self_tag(text) == text


# ── §B. compute_divergence — match cases ─────────────────────────────────


def test_divergence_warm_intent_warm_modulation():
    result = compute_divergence("warm", ("high_trust_pitch",))
    assert result.match_score == 1.0
    assert result.magnitude == 0.0
    assert result.signed_divergence == 0.0


def test_divergence_neutral_intent_no_rules():
    result = compute_divergence("neutral", ())
    assert result.match_score == 1.0
    assert result.magnitude == 0.0


def test_divergence_neutral_intent_with_rules():
    # Intent asked for stillness; modulation moved.
    result = compute_divergence("neutral", ("tier3_rate_volume",))
    assert result.match_score == 0.0
    assert result.magnitude == 1.0


# ── §C. compute_divergence — divergence cases (asymmetric sign) ─────────


def test_divergence_warm_intent_firm_modulation_negative():
    result = compute_divergence("warm", ("low_trust_pitch",))
    assert result.match_score == 0.0
    assert result.magnitude == 1.0
    assert result.signed_divergence == -1.0  # opposite-axis


def test_divergence_warm_intent_blocked_negative():
    # blocked_rate_pitch projects to firmer direction.
    result = compute_divergence("warm", ("blocked_rate_pitch",))
    assert result.signed_divergence < 0


def test_divergence_firm_intent_warm_modulation_negative():
    result = compute_divergence("firm", ("high_trust_pitch",))
    assert result.signed_divergence == -1.0


def test_divergence_warm_intent_responding_only_positive():
    # responding_rate has no direction (warm/firm); same/neutral axis
    # against warm intent -> positive informational signal.
    result = compute_divergence("warm", ("responding_rate",))
    assert result.signed_divergence > 0


# ── §D. Trust + Hebbian wiring via apply_divergence_check ───────────────


def test_apply_divergence_strips_tag_when_feature_on(tmp_path):
    runtime = _make_runtime_with_real_trust_hebb(tmp_path)
    agent = _make_agent_with_modulation("agent-007", ("high_trust_pitch",))
    t_cfg = _make_t_cfg()
    response = "Hello, Captain.\n<intent emotion=warm>"
    stripped = apply_divergence_check(
        runtime=runtime, agent_id="agent-007", agent=agent,
        response_text=response, t_cfg=t_cfg,
    )
    assert "<intent" not in stripped
    assert stripped.endswith("Captain.")


def test_apply_divergence_strips_tag_even_on_unknown_emotion(tmp_path):
    # Defense in depth: strip MUST run even when parse returns None.
    runtime = _make_runtime_with_real_trust_hebb(tmp_path)
    agent = _make_agent_with_modulation("agent-007", ("high_trust_pitch",))
    t_cfg = _make_t_cfg()
    response = "Hello.\n<intent emotion=feisty>"
    stripped = apply_divergence_check(
        runtime=runtime, agent_id="agent-007", agent=agent,
        response_text=response, t_cfg=t_cfg,
    )
    assert "<intent" not in stripped
    # No divergence stored (parse failed).
    assert "agent-007" not in runtime.divergence_results


def test_apply_divergence_negative_weakens_trust(tmp_path):
    runtime = _make_runtime_with_real_trust_hebb(tmp_path)
    # Intent=warm but modulation fired low_trust_pitch (opposite axis).
    agent = _make_agent_with_modulation("agent-007", ("low_trust_pitch",))
    t_cfg = _make_t_cfg()
    prior_score = runtime.trust_network.get_score("agent-007")

    response = "Reply.\n<intent emotion=warm>"
    apply_divergence_check(
        runtime=runtime, agent_id="agent-007", agent=agent,
        response_text=response, t_cfg=t_cfg,
    )

    new_score = runtime.trust_network.get_score("agent-007")
    assert new_score < prior_score
    assert "agent-007" in runtime.divergence_results
    result = runtime.divergence_results["agent-007"]
    assert result.signed_divergence < 0
    assert result.magnitude > t_cfg.divergence_negative_threshold


def test_apply_divergence_positive_rewards_trust(tmp_path):
    # Intent=warm, modulation=blocked_rate_pitch+high_trust_pitch fires both
    # warmer and firmer signals -- but more readily reproducible: use
    # intent=playful (expects {responding_rate, high_trust_pitch}) and
    # applied=(high_trust_pitch,) -- same-direction, magnitude=0.5
    # exactly equals positive_threshold (not > it). Use neutral intent
    # with a non-matching same-direction tuple to drive magnitude=1.0:
    # intent=playful expects 2 rules; applied=(high_trust_pitch,) gives
    # Jaccard 1/2 = 0.5, magnitude 0.5 -- still not > 0.5. Use applied
    # with high_trust_pitch+tier3_rate_volume: expected={responding_rate,
    # high_trust_pitch}, applied={high_trust_pitch, tier3_rate_volume};
    # Jaccard = 1/3, magnitude = 2/3 > 0.5; same-axis (+1).
    runtime = _make_runtime_with_real_trust_hebb(tmp_path)
    agent = _make_agent_with_modulation(
        "agent-007", ("high_trust_pitch", "tier3_rate_volume")
    )
    t_cfg = _make_t_cfg()
    prior_score = runtime.trust_network.get_score("agent-007")

    response = "Reply.\n<intent emotion=playful>"
    apply_divergence_check(
        runtime=runtime, agent_id="agent-007", agent=agent,
        response_text=response, t_cfg=t_cfg,
    )

    new_score = runtime.trust_network.get_score("agent-007")
    result = runtime.divergence_results["agent-007"]
    assert result.signed_divergence > 0
    assert result.magnitude > t_cfg.divergence_positive_threshold
    assert new_score > prior_score


def test_apply_divergence_below_negative_threshold_no_trust_update(tmp_path):
    runtime = _make_runtime_with_real_trust_hebb(tmp_path)
    # Match -- magnitude == 0.
    agent = _make_agent_with_modulation("agent-007", ("high_trust_pitch",))
    t_cfg = _make_t_cfg()
    prior_score = runtime.trust_network.get_score("agent-007")

    response = "Reply.\n<intent emotion=warm>"
    apply_divergence_check(
        runtime=runtime, agent_id="agent-007", agent=agent,
        response_text=response, t_cfg=t_cfg,
    )

    new_score = runtime.trust_network.get_score("agent-007")
    assert new_score == pytest.approx(prior_score)
    result = runtime.divergence_results["agent-007"]
    assert result.magnitude == 0.0


def test_apply_divergence_between_positive_thresholds_no_reward(tmp_path):
    # intent=playful (expects {responding_rate, high_trust_pitch});
    # applied=(high_trust_pitch,) -> Jaccard 1/2 = 0.5, magnitude 0.5,
    # NOT > positive_threshold (0.5). Same-direction so positive sign.
    runtime = _make_runtime_with_real_trust_hebb(tmp_path)
    agent = _make_agent_with_modulation("agent-007", ("high_trust_pitch",))
    t_cfg = _make_t_cfg()
    prior_score = runtime.trust_network.get_score("agent-007")

    response = "Reply.\n<intent emotion=playful>"
    apply_divergence_check(
        runtime=runtime, agent_id="agent-007", agent=agent,
        response_text=response, t_cfg=t_cfg,
    )

    new_score = runtime.trust_network.get_score("agent-007")
    result = runtime.divergence_results["agent-007"]
    # Magnitude is 0.5 -- at threshold, not above. Defensive check that
    # strict `>` is used (not `>=`): no trust update fires.
    assert result.magnitude == pytest.approx(0.5)
    assert result.signed_divergence > 0
    assert new_score == pytest.approx(prior_score)


def test_apply_divergence_match_strengthens_hebbian(tmp_path):
    runtime = _make_runtime_with_real_trust_hebb(tmp_path)
    agent = _make_agent_with_modulation("agent-007", ("high_trust_pitch",))
    t_cfg = _make_t_cfg()

    response = "Reply.\n<intent emotion=warm>"
    apply_divergence_check(
        runtime=runtime, agent_id="agent-007", agent=agent,
        response_text=response, t_cfg=t_cfg,
    )

    weight = runtime.hebbian_router.get_weight(
        "agent-007", "avatar:emotion:warm", REL_AVATAR_INTENT,
    )
    assert weight > 0.0


def test_apply_divergence_mismatch_weakens_hebbian(tmp_path):
    runtime = _make_runtime_with_real_trust_hebb(tmp_path)
    # First a match to build positive weight.
    agent_match = _make_agent_with_modulation("agent-007", ("high_trust_pitch",))
    t_cfg = _make_t_cfg()
    apply_divergence_check(
        runtime=runtime, agent_id="agent-007", agent=agent_match,
        response_text="Reply.\n<intent emotion=warm>", t_cfg=t_cfg,
    )
    post_match = runtime.hebbian_router.get_weight(
        "agent-007", "avatar:emotion:warm", REL_AVATAR_INTENT,
    )
    assert post_match > 0.0

    # Then an opposite-axis mismatch -- match_score is below 0.7, edge weakens.
    agent_miss = _make_agent_with_modulation("agent-007", ("low_trust_pitch",))
    apply_divergence_check(
        runtime=runtime, agent_id="agent-007", agent=agent_miss,
        response_text="Reply.\n<intent emotion=warm>", t_cfg=t_cfg,
    )
    post_miss = runtime.hebbian_router.get_weight(
        "agent-007", "avatar:emotion:warm", REL_AVATAR_INTENT,
    )
    assert post_miss < post_match


def test_apply_divergence_no_snap_graceful(tmp_path):
    # No cached snapshot -> strip runs, no divergence stored, no trust delta.
    runtime = _make_runtime_with_real_trust_hebb(tmp_path)
    agent = MagicMock()
    agent.id = "agent-007"
    agent._last_self_avatar_snap = None
    t_cfg = _make_t_cfg()
    prior_score = runtime.trust_network.get_score("agent-007")

    response = "Reply.\n<intent emotion=warm>"
    stripped = apply_divergence_check(
        runtime=runtime, agent_id="agent-007", agent=agent,
        response_text=response, t_cfg=t_cfg,
    )

    assert "<intent" not in stripped
    assert "agent-007" not in runtime.divergence_results
    assert runtime.trust_network.get_score("agent-007") == pytest.approx(prior_score)


# ── §E. Sensorium injection (_build_avatar_self_observation) ────────────


def _make_cognitive_agent_for_observation(agent_id: str, runtime):
    """Build a minimal CognitiveAgent-shaped stub for observation rendering.

    We only need ``self._runtime``, ``self.id``, ``self._last_self_avatar_snap``,
    and the divergence-note helper, which is a pure read from
    ``runtime.divergence_results``. The full self-observation rendering needs
    a valid snapshot too — pre-populate one.
    """
    from probos.avatars.telemetry import (
        AgentSignalsSnapshot,
        AvatarTelemetrySnapshot,
        ModulationSnapshot,
    )
    from probos.cognitive.cognitive_agent import CognitiveAgent

    # Bypass __init__: build a stub object using object.__new__ and assign
    # only the attrs our methods read.
    agent = object.__new__(CognitiveAgent)
    agent._runtime = runtime
    agent.id = agent_id
    signals = AgentSignalsSnapshot(
        trust_delta=0.0,
        load=0.0,
        working_state="idle",
        tier3_alert=False,
    )
    mod = ModulationSnapshot(
        pitch_factor=1.0,
        rate_factor=1.0,
        volume_factor=1.0,
        fired_rules=("high_trust_pitch",),
    )
    snap = AvatarTelemetrySnapshot(
        agent_id=agent_id,
        expression_resting="neutral",
        current_signals=signals,
        mouth_active=False,
        applied_modulation=mod,
        dsl_summary=None,
        last_observed_at=0.0,
        degraded_reasons=(),
        sampling_rate_ms=2000,
        sampling_tier="normal",
    )
    agent._last_self_avatar_snap = snap
    return agent


def test_build_avatar_self_observation_with_divergence(tmp_path):
    runtime = SimpleNamespace()
    runtime.config = SimpleNamespace(
        avatar_telemetry=SimpleNamespace(
            inject_into_agent_context=True,
            divergence_detection=True,
        ),
    )
    runtime.divergence_results = {
        "agent-007": DivergenceResult(
            intent_emotion="warm",
            applied_fired_rules=("blocked_rate_pitch",),
            match_score=0.0,
            signed_divergence=-0.42,
            magnitude=0.42,
        ),
    }
    agent = _make_cognitive_agent_for_observation("agent-007", runtime)

    text = agent._build_avatar_self_observation({})

    assert "intended as `warm`" in text
    assert "modulation came out as `blocked_rate_pitch`" in text
    assert "-0.42" in text


def test_build_avatar_self_observation_without_divergence(tmp_path):
    runtime = SimpleNamespace()
    runtime.config = SimpleNamespace(
        avatar_telemetry=SimpleNamespace(
            inject_into_agent_context=True,
            divergence_detection=False,
        ),
    )
    runtime.divergence_results = {}
    agent = _make_cognitive_agent_for_observation("agent-007", runtime)

    text = agent._build_avatar_self_observation({})

    assert "intent-vs-presentation" not in text
    assert text  # base observation block still produced


_FORBIDDEN_PHRASING_RE = re.compile(
    r"\byou (?:sound|sounded|came across|seem|seemed|are|were|feel|felt)\b",
    re.IGNORECASE,
)


def test_divergence_note_phrasing_rule():
    """Defensive: every intent x applied combo MUST avoid agent-as-subject."""
    runtime = SimpleNamespace()
    runtime.config = SimpleNamespace(
        avatar_telemetry=SimpleNamespace(
            inject_into_agent_context=True,
            divergence_detection=True,
        ),
    )
    applied_samples = [
        ("high_trust_pitch",),
        ("low_trust_pitch",),
        ("blocked_rate_pitch",),
        ("tier3_rate_volume",),
        ("responding_rate", "high_trust_pitch"),
    ]
    agent = _make_cognitive_agent_for_observation("agent-007", runtime)
    for intent in EmotionalIntent:
        for applied in applied_samples:
            runtime.divergence_results = {
                "agent-007": compute_divergence(intent.value, applied),
            }
            text = agent._build_avatar_self_observation({})
            assert _FORBIDDEN_PHRASING_RE.search(text) is None, (
                f"OUTPUT-subject rule violated for intent={intent.value!r} "
                f"applied={applied!r}: {text!r}"
            )


# ── §F. Self-tag instruction injection ──────────────────────────────────


def test_intent_self_tag_instruction_off_by_default():
    runtime = SimpleNamespace()
    runtime.config = SimpleNamespace(
        avatar_telemetry=SimpleNamespace(divergence_detection=False),
    )
    from probos.cognitive.cognitive_agent import CognitiveAgent
    agent = object.__new__(CognitiveAgent)
    agent._runtime = runtime
    assert agent._build_intent_self_tag_instruction() == ""


def test_intent_self_tag_instruction_when_on():
    runtime = SimpleNamespace()
    runtime.config = SimpleNamespace(
        avatar_telemetry=SimpleNamespace(divergence_detection=True),
    )
    from probos.cognitive.cognitive_agent import CognitiveAgent
    agent = object.__new__(CognitiveAgent)
    agent._runtime = runtime
    line = agent._build_intent_self_tag_instruction()
    assert "<intent emotion=NAME>" in line
    assert (
        "warm | firm | warm_concern | alert | neutral | playful | "
        "thoughtful | apologetic"
    ) in line


# ── Config validation ───────────────────────────────────────────────────


def test_config_defaults_are_safe():
    from probos.config import AvatarTelemetryConfig
    cfg = AvatarTelemetryConfig()
    assert cfg.divergence_detection is False  # operator opt-in
    assert 0.0 <= cfg.divergence_negative_threshold <= 1.0
    assert 0.0 <= cfg.divergence_positive_threshold <= 1.0
    assert cfg.divergence_negative_weight > cfg.divergence_positive_weight


def test_config_out_of_bounds_rejected():
    from probos.config import AvatarTelemetryConfig
    with pytest.raises(ValueError):
        AvatarTelemetryConfig(divergence_negative_threshold=1.5)
    with pytest.raises(ValueError):
        AvatarTelemetryConfig(divergence_positive_weight=-0.1)


def test_intent_taxonomy_covers_eight_emotions():
    # Floor check: AD-722a v1 emotion taxonomy is exactly 8.
    assert len(INTENT_EXPECTED_RULES) == 8
    assert set(INTENT_EXPECTED_RULES) == {e.value for e in EmotionalIntent}
