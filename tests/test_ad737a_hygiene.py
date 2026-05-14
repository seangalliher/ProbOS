"""AD-737a: divergence_detector hygiene — single-pass parse boundary tests.

Three boundary tests on the collapsed single-pass parse path in
``apply_divergence_check``:

1. Happy path — v1 intent, no profile_store.
2. Edge — custom emotion resolves via palette in a single call.
3. Error path — unknown intent strips tag but does not record result.

Each test patches ``parse_intent_self_tag`` with a counter to pin the
AD-737a invariant: the production code calls it AT MOST ONCE.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import probos.avatars.divergence_detector as dd
from probos.avatars.divergence_detector import apply_divergence_check
from probos.avatars.telemetry import AgentSignalsSnapshot
from probos.crew_profile import CrewProfile, EmotionProfile


def _t_cfg() -> SimpleNamespace:
    return SimpleNamespace(
        divergence_detection=True,
        divergence_negative_threshold=0.3,
        divergence_positive_threshold=0.5,
        divergence_negative_weight=0.4,
        divergence_positive_weight=0.1,
        divergence_history_size=0,
    )


def _runtime(crew: CrewProfile | None) -> SimpleNamespace:
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


def _agent(agent_id: str, signals: AgentSignalsSnapshot):
    snap = MagicMock()
    snap.applied_modulation = SimpleNamespace(
        fired_rules=("high_trust_pitch",),
    )
    snap.current_signals = signals
    agent = MagicMock()
    agent.id = agent_id
    agent._last_self_avatar_snap = snap
    return agent


def _signals() -> AgentSignalsSnapshot:
    return AgentSignalsSnapshot(
        trust_delta=0.0,
        load=0.5,
        working_state="responding",
        tier3_alert=False,
    )


def _install_counter(monkeypatch) -> dict[str, int]:
    """Wrap ``dd.parse_intent_self_tag`` with a call counter."""
    counter = {"n": 0}
    real = dd.parse_intent_self_tag

    def counting(text, *, custom_emotions=None):
        counter["n"] += 1
        return real(text, custom_emotions=custom_emotions)

    monkeypatch.setattr(dd, "parse_intent_self_tag", counting)
    return counter


def test_apply_divergence_check_single_pass_v1_intent(monkeypatch):
    """Happy path: v1 intent name, no profile_store, single parse call."""
    counter = _install_counter(monkeypatch)
    runtime = _runtime(crew=None)
    agent = _agent("agent-1", _signals())

    stripped = apply_divergence_check(
        runtime=runtime,
        agent_id="agent-1",
        agent=agent,
        response_text="hi.\n<intent emotion=warm>",
        t_cfg=_t_cfg(),
    )

    assert "<intent" not in stripped
    assert "hi." in stripped
    result = runtime.divergence_results.get("agent-1")
    assert result is not None
    assert result.intent_emotion == "warm"
    assert counter["n"] == 1, (
        f"AD-737a single-pass guarantee broken: parse_intent_self_tag "
        f"called {counter['n']} times, expected 1"
    )


def test_apply_divergence_check_single_pass_custom_intent_resolves_via_palette(
    monkeypatch,
):
    """Edge: custom emotion resolves through palette in ONE parse call."""
    counter = _install_counter(monkeypatch)
    custom = {
        "professional_concern": EmotionProfile(inherits="concerned"),
    }
    crew = CrewProfile(agent_id="agent-2", custom_emotions=custom)
    runtime = _runtime(crew=crew)
    agent = _agent("agent-2", _signals())

    stripped = apply_divergence_check(
        runtime=runtime,
        agent_id="agent-2",
        agent=agent,
        response_text="reply.\n<intent emotion=professional_concern>",
        t_cfg=_t_cfg(),
    )

    assert "<intent" not in stripped
    result = runtime.divergence_results.get("agent-2")
    assert result is not None
    assert result.intent_emotion == "professional_concern"
    assert counter["n"] == 1, (
        f"AD-737a single-pass guarantee broken: parse_intent_self_tag "
        f"called {counter['n']} times, expected 1"
    )


def test_apply_divergence_check_single_pass_unknown_intent_returns_stripped_only(
    monkeypatch,
):
    """Error path: unknown intent name strips tag but stores no result."""
    counter = _install_counter(monkeypatch)
    runtime = _runtime(crew=None)
    agent = _agent("agent-3", _signals())

    stripped = apply_divergence_check(
        runtime=runtime,
        agent_id="agent-3",
        agent=agent,
        response_text="ok.\n<intent emotion=feisty>",
        t_cfg=_t_cfg(),
    )

    assert "<intent" not in stripped
    assert "ok." in stripped
    # Unknown intent -> parse returns None -> no result stored.
    assert runtime.divergence_results.get("agent-3") is None
    assert counter["n"] == 1, (
        f"AD-737a single-pass guarantee broken: parse_intent_self_tag "
        f"called {counter['n']} times, expected 1"
    )
