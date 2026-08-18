"""AD-722a-4: Boundary tests for the auto-correction loop.

Eight tests cover: default-off, threshold gate, budget enforcement, exception
degrade, pipeline slot-clear, DivergenceResult serialization, and missing
runtime-attribute degrade.
"""

from __future__ import annotations

import dataclasses
import logging
from types import SimpleNamespace
from typing import Any

import pytest

from probos.avatars.divergence_detector import (
    DivergenceResult,
    apply_divergence_check,
)
from probos.avatars.telemetry import (
    AgentSignalsSnapshot,
    ModulationSnapshot,
    apply_voice_modulation,
)
from probos.cognitive.dm import DmReplyContext, DmReplyPipeline
from probos.cognitive.dm.reply_value import DmReply  # AD-1248


# --------------------------------------------------------------------------- #
# Fixtures                                                                    #
# --------------------------------------------------------------------------- #


def _t_cfg(**over: Any) -> SimpleNamespace:
    base = dict(
        divergence_detection=True,
        divergence_negative_threshold=0.3,
        divergence_positive_threshold=0.5,
        divergence_negative_weight=0.4,
        divergence_positive_weight=0.1,
        divergence_history_size=0,
        divergence_aggregate_window=50,
        auto_correct_enabled=False,
        auto_correct_threshold=0.6,
        max_corrections_per_utterance=1,
        correction_noise_factor=1.15,
        correction_length_factor=0.92,
    )
    base.update(over)
    return SimpleNamespace(**base)


def _make_snap(magnitude: float = 0.9) -> Any:
    """Synthesize an agent snapshot that produces the desired magnitude.

    Provides ``current_signals`` so the post-correction recompute branch
    (signals is not None) is reachable.
    """
    return SimpleNamespace(
        applied_modulation=ModulationSnapshot(
            pitch_factor=1.0,
            rate_factor=1.0,
            volume_factor=1.0,
            fired_rules=("intent_excited",),
        ),
        current_signals=AgentSignalsSnapshot(
            trust_delta=0.0, load=0.0, working_state="idle", tier3_alert=False,
        ),
    )


def _make_runtime(
    *,
    corrections: dict[str, DivergenceResult] | None = "alloc",
    profile_store: Any | None = None,
    has_attr: bool = True,
) -> Any:
    rt = SimpleNamespace()
    rt.divergence_results = {}
    if has_attr:
        rt.divergence_corrections = {} if corrections == "alloc" else corrections
    rt.profile_store = profile_store
    rt.trust_network = None
    rt.hebbian_router = None
    rt.divergence_history = {}
    return rt


def _make_agent(snap: Any) -> Any:
    agent = SimpleNamespace()
    agent._last_self_avatar_snap = snap
    return agent


# --------------------------------------------------------------------------- #
# 1 default OFF                                                               #
# --------------------------------------------------------------------------- #


def test_default_off_does_not_correct() -> None:
    rt = _make_runtime()
    a = _make_agent(_make_snap())
    text = "I feel great. <intent emotion=concerned/>"
    apply_divergence_check(
        runtime=rt, agent_id="a1", agent=a,
        response_text=text, t_cfg=_t_cfg(auto_correct_enabled=False),
    )
    assert rt.divergence_corrections == {}


# --------------------------------------------------------------------------- #
# 2 below threshold                                                           #
# --------------------------------------------------------------------------- #


def test_threshold_gate_below_does_not_fire(monkeypatch: pytest.MonkeyPatch) -> None:
    rt = _make_runtime()
    a = _make_agent(_make_snap())
    text = "I feel great. <intent emotion=excited/>"
    # Force magnitude=0.5 < 0.6 threshold by monkey-patching compute_divergence.
    from probos.avatars import divergence_detector as dd

    def _fake_compute(intent_emotion: str, applied_fired_rules: tuple[str, ...]) -> DivergenceResult:
        return DivergenceResult(
            intent_emotion=intent_emotion,
            applied_fired_rules=applied_fired_rules,
            match_score=0.5,
            signed_divergence=-0.5,
            magnitude=0.5,
        )

    monkeypatch.setattr(dd, "compute_divergence", _fake_compute)
    apply_divergence_check(
        runtime=rt, agent_id="a1", agent=a,
        response_text=text, t_cfg=_t_cfg(
            auto_correct_enabled=True, auto_correct_threshold=0.6,
        ),
    )
    assert rt.divergence_corrections == {}


# --------------------------------------------------------------------------- #
# 3 above threshold fires                                                     #
# --------------------------------------------------------------------------- #


def test_threshold_gate_above_fires(monkeypatch: pytest.MonkeyPatch) -> None:
    rt = _make_runtime()
    a = _make_agent(_make_snap())
    text = "I feel great. <intent emotion=excited/>"
    from probos.avatars import divergence_detector as dd

    def _fake_compute(intent_emotion: str, applied_fired_rules: tuple[str, ...]) -> DivergenceResult:
        return DivergenceResult(
            intent_emotion=intent_emotion,
            applied_fired_rules=applied_fired_rules,
            match_score=0.1,
            signed_divergence=-0.9,
            magnitude=0.9,
        )

    monkeypatch.setattr(dd, "compute_divergence", _fake_compute)
    apply_divergence_check(
        runtime=rt, agent_id="a1", agent=a,
        response_text=text, t_cfg=_t_cfg(
            auto_correct_enabled=True, auto_correct_threshold=0.6,
        ),
    )
    assert "a1" in rt.divergence_corrections
    assert rt.divergence_corrections["a1"].corrected is True


# --------------------------------------------------------------------------- #
# 4 budget exhausted                                                          #
# --------------------------------------------------------------------------- #


def test_budget_exhausted_skips_second_correction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rt = _make_runtime()
    a = _make_agent(_make_snap())
    text = "x <intent emotion=excited/>"
    from probos.avatars import divergence_detector as dd

    def _fake(intent_emotion: str, applied_fired_rules: tuple[str, ...]) -> DivergenceResult:
        return DivergenceResult(
            intent_emotion=intent_emotion,
            applied_fired_rules=applied_fired_rules,
            match_score=0.1, signed_divergence=-0.9, magnitude=0.9,
        )

    monkeypatch.setattr(dd, "compute_divergence", _fake)
    cfg = _t_cfg(auto_correct_enabled=True, auto_correct_threshold=0.6)
    apply_divergence_check(
        runtime=rt, agent_id="a1", agent=a, response_text=text, t_cfg=cfg,
    )
    first = rt.divergence_corrections["a1"]
    # Second call within the SAME utterance — slot still populated, so the
    # budget-of-1 gate refuses to overwrite.
    apply_divergence_check(
        runtime=rt, agent_id="a1", agent=a, response_text=text, t_cfg=cfg,
    )
    assert rt.divergence_corrections["a1"] is first


# --------------------------------------------------------------------------- #
# 5 remodulation exception degrades                                            #
# --------------------------------------------------------------------------- #


def test_remodulation_exception_logs_and_degrades(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rt = _make_runtime()
    a = _make_agent(_make_snap())
    text = "x <intent emotion=excited/>"
    from probos.avatars import divergence_detector as dd

    def _fake(intent_emotion: str, applied_fired_rules: tuple[str, ...]) -> DivergenceResult:
        return DivergenceResult(
            intent_emotion=intent_emotion,
            applied_fired_rules=applied_fired_rules,
            match_score=0.1, signed_divergence=-0.9, magnitude=0.9,
        )

    monkeypatch.setattr(dd, "compute_divergence", _fake)

    real_apply = apply_voice_modulation

    def _raise(*args: Any, **kwargs: Any) -> ModulationSnapshot:
        # Only raise on the correction call (kwargs carry the factors).
        if kwargs.get("noise_scale_factor", 1.0) != 1.0:
            raise RuntimeError("boom")
        return real_apply(*args, **kwargs)

    # Patch the LATE binding in apply_divergence_check (lazy import).
    monkeypatch.setattr(
        "probos.avatars.telemetry.apply_voice_modulation", _raise,
    )
    apply_divergence_check(
        runtime=rt, agent_id="a1", agent=a, response_text=text,
        t_cfg=_t_cfg(auto_correct_enabled=True, auto_correct_threshold=0.6),
    )
    # Original result still in divergence_results; correction slot empty.
    assert "a1" not in rt.divergence_corrections


# --------------------------------------------------------------------------- #
# 6 pipeline step_1 clears stale slot                                          #
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_pipeline_step_1_clears_stale_slot() -> None:
    rt = SimpleNamespace()
    rt.divergence_corrections = {
        "ezri": DivergenceResult(
            intent_emotion="concerned",
            applied_fired_rules=(),
            match_score=0.0, signed_divergence=-1.0, magnitude=1.0,
            corrected=True,
        ),
    }
    ctx = DmReplyContext(
        runtime=rt, agent=SimpleNamespace(), agent_id="ezri",
        callsign="ezri", req_message="hi", reply=DmReply(body=""),
        has_image_attachment=False, per_attachment=[], sanity_gate=None,
        params={}, message_text="hi", sampling_state=None, avatar_event_bus=None,
    )
    pipeline = DmReplyPipeline(ctx)
    await pipeline.step_1_sanity_gate_retry()
    assert "ezri" not in rt.divergence_corrections


# --------------------------------------------------------------------------- #
# 7 corrected field serializes                                                #
# --------------------------------------------------------------------------- #


def test_correction_result_serializes_corrected_field() -> None:
    r = DivergenceResult(
        intent_emotion="excited",
        applied_fired_rules=(),
        match_score=0.0,
        signed_divergence=-1.0,
        magnitude=1.0,
        corrected=True,
    )
    d = r.to_dict()
    assert d["corrected"] is True


# --------------------------------------------------------------------------- #
# 8 missing runtime attr logs WARNING and degrades                            #
# --------------------------------------------------------------------------- #


def test_runtime_without_divergence_corrections_attr_degrades(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
) -> None:
    rt = _make_runtime(has_attr=False)
    a = _make_agent(_make_snap())
    text = "x <intent emotion=excited/>"
    from probos.avatars import divergence_detector as dd

    def _fake(intent_emotion: str, applied_fired_rules: tuple[str, ...]) -> DivergenceResult:
        return DivergenceResult(
            intent_emotion=intent_emotion,
            applied_fired_rules=applied_fired_rules,
            match_score=0.1, signed_divergence=-0.9, magnitude=0.9,
        )

    monkeypatch.setattr(dd, "compute_divergence", _fake)
    with caplog.at_level(logging.WARNING, logger="probos.avatars.divergence_detector"):
        apply_divergence_check(
            runtime=rt, agent_id="a1", agent=a, response_text=text,
            t_cfg=_t_cfg(auto_correct_enabled=True, auto_correct_threshold=0.6),
        )
    # No exception, no slot, WARNING surfaced.
    assert not hasattr(rt, "divergence_corrections") or rt.divergence_corrections is None
    assert any("AD-722a-4" in r.message for r in caplog.records)


# --------------------------------------------------------------------------- #
# apply_voice_modulation kwargs default no-op (regression — verified)         #
# --------------------------------------------------------------------------- #


def test_apply_voice_modulation_default_kwargs_no_op() -> None:
    signals = AgentSignalsSnapshot(
        trust_delta=0.0, load=0.0, working_state="idle", tier3_alert=False,
    )
    profile = SimpleNamespace(pitch=1.0, rate=1.0, volume=1.0)
    base = apply_voice_modulation(profile, signals)
    correct = apply_voice_modulation(
        profile, signals, noise_scale_factor=1.0, length_scale_factor=1.0,
    )
    assert base == correct
