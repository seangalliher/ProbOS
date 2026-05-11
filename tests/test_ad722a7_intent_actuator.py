"""AD-722a-7: intent-driven voice modulation actuator -- boundary tests.

Covers:
  Section 1 manifest validator (happy + reject paths)
  Section 2 apply_voice_modulation intent layering
"""
from __future__ import annotations

import copy
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from probos.avatars.telemetry import (
    INTENT_RULES,
    PITCH_BOUNDS,
    RATE_BOUNDS,
    VOLUME_BOUNDS,
    AgentSignalsSnapshot,
    apply_voice_modulation,
)


# ── Fixtures ─────────────────────────────────────────────────────────────


def _profile(pitch: float = 1.0, rate: float = 1.0, volume: float = 1.0) -> SimpleNamespace:
    return SimpleNamespace(pitch=pitch, rate=rate, volume=volume)


def _signals(
    *,
    trust_delta: float = 0.0,
    load: float = 0.0,
    working_state: str = "idle",
    tier3_alert: bool = False,
) -> AgentSignalsSnapshot:
    return AgentSignalsSnapshot(
        trust_delta=trust_delta,
        load=load,
        working_state=working_state,
        tier3_alert=tier3_alert,
    )


# ── Section 1: Manifest validation ──────────────────────────────────────


def test_manifest_loads_intent_rules():
    """All 8 emotions present, fields typed, rule_name pattern matches."""
    assert set(INTENT_RULES.keys()) == {
        "warm", "concerned", "excited", "apologetic",
        "formal", "playful", "reassuring", "neutral",
    }
    for emotion, rule in INTENT_RULES.items():
        assert isinstance(rule["pitch"], float)
        assert isinstance(rule["rate"], float)
        assert isinstance(rule["volume"], float)
        assert isinstance(rule["rule_name"], str)
        assert rule["rule_name"] == f"intent_{emotion}"


def _load_with_patched_manifest(payload: dict, tmp_path: Path):
    """Helper: write a manifest payload to a temp file and import via the
    private loader. Uses ``_MANIFEST_PATH`` patch to avoid mutating the
    real on-disk manifest."""
    from probos.avatars import telemetry as t_mod

    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(payload), encoding="utf-8")
    with patch.object(t_mod, "_MANIFEST_PATH", manifest_path):
        return t_mod._load_modulation_manifest()


def _base_manifest_payload() -> dict:
    """Return a clean valid manifest payload for mutation in negative tests."""
    real_path = Path("ui/src/audio/modulation_manifest.json")
    return json.loads(real_path.read_text(encoding="utf-8"))


def test_manifest_rejects_unknown_emotion(tmp_path):
    payload = _base_manifest_payload()
    payload["intent_rules"]["bogus"] = {
        "pitch": 1.0, "rate": 1.0, "volume": 1.0, "rule_name": "intent_bogus",
    }
    with pytest.raises(RuntimeError, match="unknown emotion keys"):
        _load_with_patched_manifest(payload, tmp_path)


def test_manifest_rejects_missing_emotion(tmp_path):
    payload = _base_manifest_payload()
    del payload["intent_rules"]["warm"]
    with pytest.raises(RuntimeError, match="missing required emotions"):
        _load_with_patched_manifest(payload, tmp_path)


def test_manifest_rejects_missing_field(tmp_path):
    payload = _base_manifest_payload()
    del payload["intent_rules"]["warm"]["volume"]
    with pytest.raises(RuntimeError, match="missing\\s+required fields"):
        _load_with_patched_manifest(payload, tmp_path)


def test_manifest_rejects_non_numeric_factor(tmp_path):
    payload = _base_manifest_payload()
    payload["intent_rules"]["warm"]["pitch"] = "1.04"
    with pytest.raises(RuntimeError, match="must be a number"):
        _load_with_patched_manifest(payload, tmp_path)


def test_manifest_rejects_bad_rule_name(tmp_path):
    payload = _base_manifest_payload()
    payload["intent_rules"]["warm"]["rule_name"] = "warm_intent"
    with pytest.raises(RuntimeError, match="rule_name"):
        _load_with_patched_manifest(payload, tmp_path)


def test_manifest_rejects_missing_intent_rules_object(tmp_path):
    payload = _base_manifest_payload()
    del payload["intent_rules"]
    with pytest.raises(RuntimeError, match="missing required object keys"):
        _load_with_patched_manifest(payload, tmp_path)


# ── Section 2: apply_voice_modulation intent layering ───────────────────


@pytest.mark.parametrize("emotion", list(INTENT_RULES.keys()))
def test_intent_fires_rule_in_idle_state(emotion):
    """Every emotion -- including neutral -- records its rule_name in
    fired_rules when intent is set on an idle signal triple."""
    out = apply_voice_modulation(_profile(), _signals(), intent=emotion)
    assert f"intent_{emotion}" in out.fired_rules
    # Idle signals -> no operational rules fired.
    assert all(not r.startswith("intent_") or r == f"intent_{emotion}"
               for r in out.fired_rules)
    # Operational rules absent in idle path.
    assert "responding_rate" not in out.fired_rules
    assert "blocked_rate_pitch" not in out.fired_rules
    assert "high_trust_pitch" not in out.fired_rules
    assert "low_trust_pitch" not in out.fired_rules


def test_intent_warm_idle_applies_table_factors():
    """warm: pitch ×1.04, rate ×0.98, volume unchanged."""
    out = apply_voice_modulation(_profile(), _signals(), intent="warm")
    assert out.pitch_factor == pytest.approx(1.04, abs=1e-9)
    assert out.rate_factor == pytest.approx(0.98, abs=1e-9)
    assert out.volume_factor == pytest.approx(1.0, abs=1e-9)
    assert out.fired_rules == ("intent_warm",)


def test_intent_concerned_idle_applies_rate_only():
    out = apply_voice_modulation(_profile(), _signals(), intent="concerned")
    assert out.pitch_factor == pytest.approx(1.0, abs=1e-9)
    assert out.rate_factor == pytest.approx(0.92, abs=1e-9)
    assert out.volume_factor == pytest.approx(1.0, abs=1e-9)


def test_intent_apologetic_idle_applies_pitch_and_volume():
    out = apply_voice_modulation(_profile(), _signals(), intent="apologetic")
    assert out.pitch_factor == pytest.approx(0.96, abs=1e-9)
    assert out.rate_factor == pytest.approx(1.0, abs=1e-9)
    assert out.volume_factor == pytest.approx(0.94, abs=1e-9)


def test_intent_layers_on_operational_responding():
    """working_state='responding' + intent=excited: rate = 1.05 (op) × 1.05 (intent)
    and fired_rules order is operational-first, intent-last."""
    out = apply_voice_modulation(
        _profile(),
        _signals(working_state="responding"),
        intent="excited",
    )
    assert out.fired_rules == ("responding_rate", "intent_excited")
    # rate composition: 1.0 * 1.05 * 1.05 = 1.1025
    assert out.rate_factor == pytest.approx(1.05 * 1.05, abs=1e-9)
    # pitch: idle base * 1.06 intent
    assert out.pitch_factor == pytest.approx(1.06, abs=1e-9)


def test_intent_clamps_at_pitch_upper_bound():
    """High baseline pitch + intent=excited + high trust_delta drives composed
    value beyond PITCH_BOUNDS upper; clamps to 2.0."""
    out = apply_voice_modulation(
        _profile(pitch=1.9),
        _signals(trust_delta=0.5),
        intent="excited",
    )
    assert out.pitch_factor == pytest.approx(PITCH_BOUNDS[1], abs=1e-9)
    assert "high_trust_pitch" in out.fired_rules
    assert "intent_excited" in out.fired_rules


def test_unknown_intent_silently_dropped():
    """Unknown intent names neither raise nor fire any intent_* rule."""
    out = apply_voice_modulation(_profile(), _signals(), intent="nonexistent")
    assert not any(r.startswith("intent_") for r in out.fired_rules)
    assert out.pitch_factor == pytest.approx(1.0, abs=1e-9)
    assert out.rate_factor == pytest.approx(1.0, abs=1e-9)
    assert out.volume_factor == pytest.approx(1.0, abs=1e-9)


def test_intent_neutral_records_rule_with_no_factor_change():
    """intent_neutral fires its rule_name even though all factors are 1.0."""
    operational_only = apply_voice_modulation(_profile(), _signals())
    with_neutral = apply_voice_modulation(_profile(), _signals(), intent="neutral")
    # Numeric output identical to operational-only.
    assert with_neutral.pitch_factor == pytest.approx(operational_only.pitch_factor, abs=1e-9)
    assert with_neutral.rate_factor == pytest.approx(operational_only.rate_factor, abs=1e-9)
    assert with_neutral.volume_factor == pytest.approx(operational_only.volume_factor, abs=1e-9)
    # But fired_rules carries the rule_name.
    assert "intent_neutral" in with_neutral.fired_rules
    assert "intent_neutral" not in operational_only.fired_rules


def test_intent_none_preserves_pre_ad722a7_behavior():
    """Default intent=None: fired_rules contains zero intent_* entries; numeric
    output identical to a call without the keyword arg."""
    out_explicit = apply_voice_modulation(_profile(), _signals(working_state="responding"), intent=None)
    out_default = apply_voice_modulation(_profile(), _signals(working_state="responding"))
    assert out_explicit == out_default
    assert not any(r.startswith("intent_") for r in out_explicit.fired_rules)


def test_intent_layers_with_full_operational_stack():
    """All operational rules + intent layered: every rule name appears,
    operational first, intent last."""
    out = apply_voice_modulation(
        _profile(),
        _signals(working_state="responding", trust_delta=0.3, tier3_alert=True),
        intent="warm",
    )
    # Operational order: responding_rate, high_trust_pitch, tier3_rate_volume.
    # Intent last.
    assert out.fired_rules == (
        "responding_rate", "high_trust_pitch", "tier3_rate_volume", "intent_warm",
    )


def test_intent_rule_name_uses_manifest_value():
    """Defense: fired_rules entry comes from manifest['rule_name'], not
    a Python-side computed f-string. This guards against silent drift."""
    for emotion, rule in INTENT_RULES.items():
        out = apply_voice_modulation(_profile(), _signals(), intent=emotion)
        assert rule["rule_name"] in out.fired_rules


def test_intent_clamps_volume_lower_bound_for_apologetic():
    """apologetic volume ×0.94 layered on a baseline at lower bound floor."""
    out = apply_voice_modulation(
        _profile(volume=VOLUME_BOUNDS[0]),
        _signals(),
        intent="apologetic",
    )
    assert out.volume_factor >= VOLUME_BOUNDS[0]
    assert out.volume_factor == pytest.approx(VOLUME_BOUNDS[0], abs=1e-9)


# ── Section 4: router-side threading via apply_divergence_check ──────────


def _make_divergence_runtime():
    """Minimal runtime stub for apply_divergence_check integration tests."""
    from probos.consensus.trust import TrustNetwork
    from probos.mesh.routing import HebbianRouter

    runtime = SimpleNamespace()
    runtime.trust_network = TrustNetwork()
    runtime.hebbian_router = HebbianRouter()
    runtime.divergence_results = {}
    runtime.profile_store = None  # forces identity-baseline path
    return runtime


def _make_t_cfg():
    return SimpleNamespace(
        divergence_detection=True,
        divergence_negative_threshold=0.3,
        divergence_positive_threshold=0.5,
        divergence_negative_weight=0.4,
        divergence_positive_weight=0.1,
    )


def _make_agent_with_real_signals(
    agent_id: str,
    signals: AgentSignalsSnapshot,
    pre_reply_fired_rules: tuple[str, ...] = (),
):
    """Agent stub whose cached snap has REAL current_signals so the
    apply_divergence_check recompute path triggers."""
    from unittest.mock import MagicMock

    snap = MagicMock()
    snap.applied_modulation = SimpleNamespace(fired_rules=pre_reply_fired_rules)
    snap.current_signals = signals
    agent = MagicMock()
    agent.id = agent_id
    agent._last_self_avatar_snap = snap
    return agent


def test_router_threads_intent_to_actuator():
    """AD-722a-7 §4: a reply tagged `<intent emotion=warm>` produces a
    DivergenceResult whose applied_fired_rules contains 'intent_warm'.

    Direct call into apply_divergence_check (the router's single divergence
    invocation site) -- avoids the FastAPI TestClient harness while still
    asserting the threading contract.
    """
    from probos.avatars.divergence_detector import apply_divergence_check

    runtime = _make_divergence_runtime()
    signals = AgentSignalsSnapshot(
        trust_delta=0.0, load=0.0, working_state="idle", tier3_alert=False,
    )
    agent = _make_agent_with_real_signals("agent-007", signals)

    stripped = apply_divergence_check(
        runtime=runtime, agent_id="agent-007", agent=agent,
        response_text="Hello.\n<intent emotion=warm>",
        t_cfg=_make_t_cfg(),
    )

    assert "<intent" not in stripped
    result = runtime.divergence_results["agent-007"]
    assert "intent_warm" in result.applied_fired_rules
    assert result.match_score == 1.0  # intent_warm both expected and applied


def test_router_with_no_intent_tag_works_identically_to_pre_ad722a7():
    """No `<intent>` tag in the reply -> no divergence stored; the
    pre-reply applied_modulation passes through unchanged."""
    from probos.avatars.divergence_detector import apply_divergence_check

    runtime = _make_divergence_runtime()
    signals = AgentSignalsSnapshot(
        trust_delta=0.0, load=0.0, working_state="idle", tier3_alert=False,
    )
    agent = _make_agent_with_real_signals(
        "agent-007", signals,
        pre_reply_fired_rules=("high_trust_pitch",),
    )

    stripped = apply_divergence_check(
        runtime=runtime, agent_id="agent-007", agent=agent,
        response_text="Hello, Captain.",
        t_cfg=_make_t_cfg(),
    )

    assert stripped == "Hello, Captain."
    assert "agent-007" not in runtime.divergence_results


# ── Section 9: Standing Orders vocabulary doc ───────────────────────────
def test_standing_orders_emotion_vocabulary_lists_v1_eight():
    """federation.md carries the v1 eight-emotion bullet list."""
    import re

    so_path = Path("config/standing_orders/federation.md")
    text = so_path.read_text(encoding="utf-8")
    assert "## Emotional Intent Vocabulary (AD-722a-7)" in text

    # Slice to the section -- ends at the next H2.
    section_start = text.index("## Emotional Intent Vocabulary (AD-722a-7)")
    section_rest = text[section_start:]
    next_h2 = section_rest.find("\n## ", 5)
    section = section_rest[:next_h2] if next_h2 != -1 else section_rest

    bullets = re.findall(r"^- \*\*`([a-z_]+)`\*\*", section, re.MULTILINE)
    assert set(bullets) == {
        "warm", "concerned", "excited", "apologetic",
        "formal", "playful", "reassuring", "neutral",
    }, f"vocabulary drift in federation.md: {sorted(bullets)}"
    # No retired tokens leak.
    for retired in ("firm", "warm_concern", "alert", "thoughtful"):
        assert f"`{retired}`" not in section, f"retired {retired!r} in section"


# ── Section 7: TS↔Python byte-parity fixture ─────────────────────────────


def test_intent_byte_parity_fixture_matches_python_actuator():
    """AD-722a-7 §7: the committed fixture vectors are produced by the
    Python actuator. The TS Vitest test (voiceModulation.test.ts) consumes
    the same fixture and asserts numeric equality to 6 decimal places.

    Re-derives every vector from the Python side and compares against the
    committed fixture -- the fixture is the contract; the TS test enforces
    the other half."""
    fixture_path = Path("tests/fixtures/intent_parity_vectors.json")
    assert fixture_path.is_file(), f"missing parity fixture at {fixture_path}"
    vectors = json.loads(fixture_path.read_text(encoding="utf-8"))
    # 8 emotions × 3 working_states × 3 trust regimes × 2 tier3 = 144.
    assert len(vectors) == 144, f"vector count drift: {len(vectors)}"

    for v in vectors:
        signals = AgentSignalsSnapshot(
            trust_delta=v["signals"]["trust_delta"],
            load=v["signals"]["load"],
            working_state=v["signals"]["working_state"],
            tier3_alert=v["signals"]["tier3_alert"],
        )
        profile = SimpleNamespace(**v["baseline"])
        out = apply_voice_modulation(profile, signals, intent=v["intent"])
        assert out.pitch_factor == pytest.approx(v["expected"]["pitch"], abs=1e-9), v
        assert out.rate_factor == pytest.approx(v["expected"]["rate"], abs=1e-9), v
        assert out.volume_factor == pytest.approx(v["expected"]["volume"], abs=1e-9), v
