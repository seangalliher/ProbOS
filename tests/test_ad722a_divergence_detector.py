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
    """Agent stub carrying a cached _last_self_avatar_snap.applied_modulation.

    AD-722a-7: sets ``snap.current_signals = None`` so apply_divergence_check
    skips the intent-aware recompute path and uses the test-provided
    ``fired_rules`` as-is. Tests that want to exercise the recompute path
    should set ``current_signals`` to a real ``AgentSignalsSnapshot``.
    """
    snap = MagicMock()
    snap.applied_modulation = SimpleNamespace(fired_rules=tuple(fired_rules))
    snap.current_signals = None  # AD-722a-7: bypass recompute path
    agent = MagicMock()
    agent.id = agent_id
    agent._last_self_avatar_snap = snap
    return agent


# ── §A. Tag parse + strip ────────────────────────────────────────────────


def test_parse_self_tag_happy():
    assert parse_intent_self_tag("Hello.\n<intent emotion=warm>") == "warm"


def test_parse_self_tag_self_closing():
    assert parse_intent_self_tag("Hello.\n<intent emotion=concerned/>") == "concerned"


def test_parse_self_tag_uppercase_emotion():
    assert parse_intent_self_tag("Reply.\n<intent emotion=WARM>") == "warm"


def test_parse_self_tag_unknown_emotion():
    assert parse_intent_self_tag("Reply.\n<intent emotion=feisty>") is None


def test_parse_self_tag_missing():
    assert parse_intent_self_tag("Hello, Captain.") is None


# ── AD-722a-7 taxonomy migration: retired tokens no longer parse ────────


def test_taxonomy_migration_firm_no_longer_parsed():
    """`firm` retired; v1 maps to `concerned`. Parser silently drops."""
    assert parse_intent_self_tag("Reply.\n<intent emotion=firm>") is None


def test_taxonomy_migration_alert_no_longer_parsed():
    """`alert` retired; v1 maps to `excited`. Parser silently drops."""
    assert parse_intent_self_tag("Reply.\n<intent emotion=alert>") is None


def test_taxonomy_migration_warm_concern_no_longer_parsed():
    """`warm_concern` retired; v1 collapses to `concerned`. Parser drops."""
    assert parse_intent_self_tag("Reply.\n<intent emotion=warm_concern>") is None


def test_taxonomy_migration_thoughtful_no_longer_parsed():
    """`thoughtful` retired; v1 maps to `formal`. Parser silently drops."""
    assert parse_intent_self_tag("Reply.\n<intent emotion=thoughtful>") is None


def test_strip_self_tag_idempotent():
    text = "Hello, Captain.\n<intent emotion=warm>"
    once = strip_intent_self_tag(text)
    twice = strip_intent_self_tag(once)
    assert once == twice
    assert "<intent" not in once


def test_strip_self_tag_does_not_touch_prose():
    text = "I am intent on warmth."
    assert strip_intent_self_tag(text) == text


# ── BF-603: quoted value + non-trailing position must still parse + strip ──


def test_parse_self_tag_double_quoted_value():
    """LLM sometimes emits ``emotion=\"warm\"`` -- must still parse."""
    assert parse_intent_self_tag('Hello.\n<intent emotion="warm">') == "warm"


def test_parse_self_tag_single_quoted_value():
    assert parse_intent_self_tag("Hello.\n<intent emotion='warm'>") == "warm"


def test_parse_self_tag_quoted_self_closing():
    assert parse_intent_self_tag('Reply.\n<intent emotion="concerned"/>') == "concerned"


def test_strip_self_tag_double_quoted_value():
    """The exact BF-603 leak shape -- quoted value at the start of the reply."""
    text = '<intent emotion="warm">\nUnderstood, Captain. Task opened.'
    stripped = strip_intent_self_tag(text)
    assert "<intent" not in stripped
    assert stripped == "Understood, Captain. Task opened."


def test_strip_self_tag_leading_position():
    """Tag at the very start (unquoted) must be stripped too."""
    text = "<intent emotion=warm>\nHello, Captain."
    stripped = strip_intent_self_tag(text)
    assert "<intent" not in stripped
    assert stripped == "Hello, Captain."


def test_strip_self_tag_inline_does_not_merge_words():
    """Inline removal must not glue the surrounding words together."""
    text = "Acknowledged <intent emotion='warm'> Captain."
    stripped = strip_intent_self_tag(text)
    assert "<intent" not in stripped
    assert stripped == "Acknowledged Captain."


def test_strip_self_tag_quoted_idempotent():
    text = 'Reply. <intent emotion="warm">'
    once = strip_intent_self_tag(text)
    twice = strip_intent_self_tag(once)
    assert once == twice
    assert "<intent" not in once


# ── §B. compute_divergence — match cases ─────────────────────────────────


def test_divergence_warm_intent_warm_modulation():
    # AD-722a-7: match_score is keyed against intent_* namespace.
    result = compute_divergence("warm", ("intent_warm",))
    assert result.match_score == 1.0
    assert result.magnitude == 0.0
    assert result.signed_divergence == 0.0


def test_divergence_neutral_intent_with_neutral_rule():
    # AD-722a-7: intent_neutral is recorded -> match against neutral intent.
    result = compute_divergence("neutral", ("intent_neutral",))
    assert result.match_score == 1.0
    assert result.magnitude == 0.0


def test_divergence_neutral_intent_with_operational_only():
    # Operational rules alone do NOT satisfy a neutral intent (which
    # expects intent_neutral fired). match_score = 0; mag = 1.
    result = compute_divergence("neutral", ("tier3_rate_volume",))
    assert result.match_score == 0.0
    assert result.magnitude == 1.0


def test_match_score_ignores_operational_rules():
    """AD-722a-7: match_score restricts applied set to the intent_* namespace.
    Operational rules in applied_fired_rules MUST NOT affect the score."""
    result = compute_divergence(
        "warm", ("responding_rate", "high_trust_pitch", "intent_warm"),
    )
    assert result.match_score == 1.0
    assert result.magnitude == 0.0


# ── §C. compute_divergence — divergence cases (asymmetric sign) ─────────


def test_divergence_warm_intent_low_trust_operational_negative():
    # AD-722a-7: intent declared warm; modulation fired only an opposite-
    # axis operational rule (low_trust_pitch). applied_set after filter is
    # empty; mag = 1.0; direction falls back to operational rule projection.
    result = compute_divergence("warm", ("low_trust_pitch",))
    assert result.match_score == 0.0
    assert result.magnitude == 1.0
    assert result.signed_divergence == -1.0  # opposite-axis


def test_divergence_warm_intent_blocked_negative():
    # blocked_rate_pitch projects to firmer direction.
    result = compute_divergence("warm", ("blocked_rate_pitch",))
    assert result.signed_divergence < 0


def test_divergence_concerned_intent_warm_modulation_negative():
    # AD-722a-7: concerned subsumes the retired `firm` token; same direction.
    result = compute_divergence("concerned", ("high_trust_pitch",))
    assert result.signed_divergence == -1.0


def test_divergence_warm_intent_responding_only_positive():
    # responding_rate has no direction (warm/firmer); same/neutral axis
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
    # AD-722a-7: applied_set after intent_* filter is empty; mag=1.0; sign
    # comes from operational-rule fallback (low_trust_pitch -> -1).
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
    # AD-722a-7: intent=playful, applied has same-axis operational rule
    # (high_trust_pitch) but NO intent_* rule fired. After filter,
    # applied_set is empty -> match=0, mag=1.0. Direction falls back to
    # operational (high_trust_pitch -> +1); playful intent_dir=+1; same
    # axis -> signed=+1.0 > pos_threshold=0.5 -> trust strengthens.
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
    # Match -- magnitude == 0 (intent_warm fired + intent=warm).
    agent = _make_agent_with_modulation("agent-007", ("intent_warm",))
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
    # AD-722a-7: intent=playful expects {intent_playful}; applied carries
    # two same-axis intent_* rules ({intent_playful, intent_warm}). Jaccard
    # = 1/2 = 0.5 -> mag=0.5, exactly at positive_threshold (0.5). Defensive
    # check that strict `>` is used (not `>=`): no trust update fires.
    runtime = _make_runtime_with_real_trust_hebb(tmp_path)
    agent = _make_agent_with_modulation(
        "agent-007", ("intent_playful", "intent_warm")
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
    assert result.magnitude == pytest.approx(0.5)
    assert result.signed_divergence > 0
    assert new_score == pytest.approx(prior_score)


def test_apply_divergence_match_strengthens_hebbian(tmp_path):
    runtime = _make_runtime_with_real_trust_hebb(tmp_path)
    # AD-722a-7: applied carries intent_warm -> match=1.0 with intent=warm.
    agent = _make_agent_with_modulation("agent-007", ("intent_warm",))
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
    agent_match = _make_agent_with_modulation("agent-007", ("intent_warm",))
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
    # AD-722a-7: v1 eight-emotion vocabulary.
    assert (
        "warm | concerned | excited | apologetic | formal | playful | "
        "reassuring | neutral"
    ) in line


def test_self_tag_instruction_lists_v1_eight_emotions():
    """AD-722a-7: vocabulary contains exactly the v1 eight; none of the
    four retired tokens leak through."""
    runtime = SimpleNamespace()
    runtime.config = SimpleNamespace(
        avatar_telemetry=SimpleNamespace(divergence_detection=True),
    )
    from probos.cognitive.cognitive_agent import CognitiveAgent
    agent = object.__new__(CognitiveAgent)
    agent._runtime = runtime
    line = agent._build_intent_self_tag_instruction()
    for v1 in ("warm", "concerned", "excited", "apologetic",
               "formal", "playful", "reassuring", "neutral"):
        assert v1 in line, f"v1 emotion {v1!r} missing"
    for retired in ("firm", "warm_concern", "alert", "thoughtful"):
        # Token-bounded: ensure the retired name is not present as a bare
        # token in the pipe-separated list.
        assert (
            f" {retired} " not in line
            and not line.endswith(f" {retired}")
            and not line.startswith(f"{retired} ")
        ), f"retired emotion {retired!r} leaked"


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
