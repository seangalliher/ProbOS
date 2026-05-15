"""AD-722a-2: chain-path divergence detection at compose-step emit — tests."""
from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from probos.events import EventType


class _FakeAgent:
    """Minimal scaffold exercising mark_chain_output_emitted via the real class.

    We import the real method from CognitiveAgent and bind it onto a
    minimal stub. This avoids the full CognitiveAgent boot path while
    keeping the code under test unmodified.
    """

    def __init__(self, agent_id: str = "a1") -> None:
        from collections import deque
        self.id = agent_id
        self._runtime = MagicMock()
        self._runtime.emit_event = MagicMock()
        self._chain_divergence_buffer: dict[str, Any] = {}
        self._chain_divergence_buffer_factory = lambda: deque(maxlen=8)


def _bind_hook(agent: _FakeAgent) -> None:
    """Bind the real CognitiveAgent.mark_chain_output_emitted onto the stub."""
    from probos.cognitive.cognitive_agent import CognitiveAgent
    agent.mark_chain_output_emitted = CognitiveAgent.mark_chain_output_emitted.__get__(agent)
    agent.chain_divergence_buffer_for = CognitiveAgent.chain_divergence_buffer_for.__get__(agent)


def test_chain_emit_with_matching_intent_no_event() -> None:
    """Warm intent + intent_warm rule fired → magnitude=0 → no event."""
    agent = _FakeAgent()
    _bind_hook(agent)
    agent.mark_chain_output_emitted(
        "Glad to help.", audience="wr",
        intent_self_tag="warm",
        applied_modulation_rules=["intent_warm"],
    )
    assert agent._runtime.emit_event.call_count == 0
    buf = agent.chain_divergence_buffer_for("wr")
    assert len(buf) == 1
    assert buf[0].magnitude == pytest.approx(0.0)


def test_chain_emit_with_diverging_intent_records_and_emits() -> None:
    """Warm intent + intent_concerned (opposite axis) → magnitude > 0 + event."""
    agent = _FakeAgent()
    _bind_hook(agent)
    agent.mark_chain_output_emitted(
        "Help is here.", audience="dm_forward",
        intent_self_tag="warm",
        applied_modulation_rules=["intent_concerned"],
    )
    assert agent._runtime.emit_event.call_count == 1
    event_type, payload = agent._runtime.emit_event.call_args[0]
    assert event_type == EventType.DIVERGENCE_OBSERVED_CHAIN
    assert payload["audience"] == "dm_forward"
    assert payload["intent"] == "warm"
    assert payload["path_tag"] == "chain"
    assert payload["magnitude"] > 0.0


def test_chain_buffer_scoped_to_audience() -> None:
    """WR audience and DM-forward audience populate distinct ring buffers."""
    agent = _FakeAgent()
    _bind_hook(agent)
    agent.mark_chain_output_emitted(
        "x", audience="wr", intent_self_tag="warm",
        applied_modulation_rules=["intent_warm"],
    )
    agent.mark_chain_output_emitted(
        "y", audience="dm_forward", intent_self_tag="formal",
        applied_modulation_rules=["intent_formal"],
    )
    assert len(agent.chain_divergence_buffer_for("wr")) == 1
    assert len(agent.chain_divergence_buffer_for("dm_forward")) == 1
    assert len(agent.chain_divergence_buffer_for("sensorium")) == 0


def test_dm_path_unchanged_when_chain_hook_active() -> None:
    """Regression: mark_chain_output_emitted does NOT touch DM-path state."""
    agent = _FakeAgent()
    _bind_hook(agent)
    # No mark_reply_emitted equivalent state on this stub — verify the
    # chain hook leaves any unrelated attributes untouched.
    sentinel = object()
    agent._last_reply_emit_ts = sentinel  # type: ignore[attr-defined]
    agent.mark_chain_output_emitted(
        "x", audience="wr", intent_self_tag="warm",
        applied_modulation_rules=["intent_concerned"],
    )
    assert agent._last_reply_emit_ts is sentinel  # type: ignore[attr-defined]


def test_interoception_buffer_returns_isolated_audience() -> None:
    """chain_divergence_buffer_for returns only the requested audience."""
    agent = _FakeAgent()
    _bind_hook(agent)
    agent.mark_chain_output_emitted(
        "a", audience="wr", intent_self_tag="warm",
        applied_modulation_rules=["intent_concerned"],
    )
    agent.mark_chain_output_emitted(
        "b", audience="dm_forward", intent_self_tag="formal",
        applied_modulation_rules=["intent_warm"],
    )
    wr_only = agent.chain_divergence_buffer_for("wr")
    dm_only = agent.chain_divergence_buffer_for("dm_forward")
    assert len(wr_only) == 1
    assert len(dm_only) == 1
    assert wr_only[0].intent_emotion == "warm"
    assert dm_only[0].intent_emotion == "formal"


def test_phrasing_rule_holds_chain_path() -> None:
    """AD-727 #8: emitted payload exposes intent + magnitude, NOT agent-as-subject text."""
    agent = _FakeAgent()
    _bind_hook(agent)
    agent.mark_chain_output_emitted(
        "x", audience="wr", intent_self_tag="warm",
        applied_modulation_rules=["intent_concerned"],
    )
    _et, payload = agent._runtime.emit_event.call_args[0]
    # Payload carries the divergence facts; no rendered text that could
    # contain "you sound" / "she looks" constructions.
    forbidden = ("you sound", "you looked", "she looks", "the agent appears")
    for s in forbidden:
        for val in payload.values():
            assert s not in str(val).lower()


def test_trust_update_records_chain_path_tag() -> None:
    """The chain-path event payload carries path_tag='chain'."""
    agent = _FakeAgent()
    _bind_hook(agent)
    agent.mark_chain_output_emitted(
        "x", audience="wr", intent_self_tag="warm",
        applied_modulation_rules=["intent_apologetic"],
    )
    _et, payload = agent._runtime.emit_event.call_args[0]
    assert payload["path_tag"] == "chain"


def test_chain_divergence_buffer_capacity_8() -> None:
    """9th event in the same audience evicts the oldest (deque(maxlen=8))."""
    agent = _FakeAgent()
    _bind_hook(agent)
    for i in range(9):
        agent.mark_chain_output_emitted(
            f"x{i}", audience="wr", intent_self_tag="warm",
            applied_modulation_rules=["intent_warm"],
        )
    buf = agent.chain_divergence_buffer_for("wr")
    assert len(buf) == 8


def test_runtime_missing_continues_silently() -> None:
    """When _runtime is None, hook is a no-op (never raises)."""
    agent = _FakeAgent()
    _bind_hook(agent)
    agent._runtime = None
    agent.mark_chain_output_emitted(
        "x", audience="wr", intent_self_tag="warm",
        applied_modulation_rules=["intent_concerned"],
    )
    assert agent.chain_divergence_buffer_for("wr") == []


def test_missing_intent_or_rules_no_buffer_entry() -> None:
    """No signal to score → no buffer entry, no event."""
    agent = _FakeAgent()
    _bind_hook(agent)
    agent.mark_chain_output_emitted(
        "x", audience="wr",
        intent_self_tag=None,
        applied_modulation_rules=["intent_warm"],
    )
    agent.mark_chain_output_emitted(
        "x", audience="wr",
        intent_self_tag="warm",
        applied_modulation_rules=None,
    )
    assert agent.chain_divergence_buffer_for("wr") == []
    assert agent._runtime.emit_event.call_count == 0
