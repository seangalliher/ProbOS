"""AD-666/AD-1122: Agent Sensorium telemetry tests."""

from __future__ import annotations

import ast
import inspect
import math
import textwrap
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError

from probos.cognitive.attention import estimate_tokens
from probos.cognitive.cognitive_agent import (
    CognitiveAgent,
    SensoriumEntry,
    SensoriumLayer,
    SensoriumPath,
)
from probos.cognitive.decomposer import is_capability_gap
from probos.config import SensoriumConfig, SystemConfig, load_config
from probos.events import EventType, SensoriumBudgetExceededEvent


class _Clock:
    """Deterministic monotonic clock for debounce tests."""

    def __init__(self, now: float = 100.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class _Runtime:
    """Minimal typed runtime stub with a real root configuration."""

    def __init__(self, sensorium: object | None = None) -> None:
        self.config = SystemConfig()
        if sensorium is not None:
            self.config.sensorium = sensorium  # type: ignore[assignment]
        self.events: list[SensoriumBudgetExceededEvent] = []

    def emit_event(self, event: SensoriumBudgetExceededEvent) -> None:
        self.events.append(event)


class _FailingRuntime(_Runtime):
    """Typed event sink that fails after the transition has committed."""

    def __init__(self, sensorium: object | None = None) -> None:
        super().__init__(sensorium)
        self.emit_attempts = 0

    def emit_event(self, event: SensoriumBudgetExceededEvent) -> None:
        self.emit_attempts += 1
        raise RuntimeError("event sink offline")


@dataclass
class _HarnessSensorium:
    """Non-Pydantic harness shape used only to test defensive fallbacks."""

    enabled: bool = True
    warning_chars: object = 10_000
    warning_cooldown_seconds: object = 21_600.0
    warning_rearm_ratio: object = 0.90
    warning_escalation_ratio: object = 1.25
    top_contributors: object = 5


class _StrictLLM:
    """LLM fake that records and rejects every invocation."""

    def __init__(self) -> None:
        self.calls = 0

    async def complete(self, *args: object, **kwargs: object) -> object:
        self.calls += 1
        raise AssertionError("LLM invocation crossed the telemetry sequencing boundary")


class _StrictSubTaskExecutor:
    """Sub-task fake that records and rejects every execution."""

    def __init__(self) -> None:
        self.calls = 0

    async def execute(self, *args: object, **kwargs: object) -> object:
        self.calls += 1
        raise AssertionError("sub-task execution crossed the chain-construction boundary")


class _StopAfterChainConstruction(RuntimeError):
    """Sentinel used to stop the production path before chain execution."""


def _make_agent(**kwargs: object) -> CognitiveAgent:
    agent = CognitiveAgent(
        agent_id=str(kwargs.get("agent_id", "test-agent")),
        instructions="Test instructions.",
        runtime=kwargs.get("runtime"),
    )
    agent.callsign = "TestAgent"
    agent.agent_type = "test_agent"
    clock = kwargs.get("clock")
    if clock is not None:
        agent._sensorium_budget_clock = clock  # type: ignore[attr-defined,method-assign]
    return agent


def _make_runtime_with_sensorium_config(
    enabled: bool = True,
    threshold: int = 6000,
    *,
    cooldown: float = 21_600.0,
    rearm_ratio: float = 0.90,
    escalation_ratio: float = 1.25,
    top_contributors: int = 5,
) -> _Runtime:
    return _Runtime(
        SensoriumConfig(
            enabled=enabled,
            warning_chars=threshold,
            warning_cooldown_seconds=cooldown,
            warning_rearm_ratio=rearm_ratio,
            warning_escalation_ratio=escalation_ratio,
            top_contributors=top_contributors,
        )
    )


def _event(runtime: _Runtime) -> SensoriumBudgetExceededEvent:
    assert runtime.events
    return runtime.events[-1]


class TestSensoriumLayer:
    def test_layer_enum_has_three_values(self) -> None:
        assert len(SensoriumLayer) == 3
        assert SensoriumLayer.PROPRIOCEPTION == "proprioception"
        assert SensoriumLayer.INTEROCEPTION == "interoception"
        assert SensoriumLayer.EXTEROCEPTION == "exteroception"


class TestSensoriumRegistry:
    def test_registry_is_classvar_dict(self) -> None:
        assert isinstance(CognitiveAgent.SENSORIUM_REGISTRY, dict)
        assert len(CognitiveAgent.SENSORIUM_REGISTRY) >= 13

    def test_registry_entries_are_tuples_of_layer_and_description(self) -> None:
        # AD-723 v1 reshaped entries from ``tuple[SensoriumLayer, str]`` to
        # ``SensoriumEntry`` dataclass. Layer + description fields are
        # preserved on the dataclass.
        from probos.cognitive.cognitive_agent import SensoriumEntry
        for method_name, entry in CognitiveAgent.SENSORIUM_REGISTRY.items():
            assert isinstance(method_name, str)
            assert isinstance(entry, SensoriumEntry)
            assert entry.layer in (
                SensoriumLayer.PROPRIOCEPTION,
                SensoriumLayer.INTEROCEPTION,
                SensoriumLayer.EXTEROCEPTION,
            )
            assert isinstance(entry.description, str) and len(entry.description) > 0

    def test_all_registry_methods_exist_on_class(self) -> None:
        for method_name in CognitiveAgent.SENSORIUM_REGISTRY:
            assert hasattr(CognitiveAgent, method_name)

    def test_registry_has_all_three_layers(self) -> None:
        # AD-723 v1: entries are now ``SensoriumEntry`` dataclasses;
        # access the layer via the ``.layer`` attribute.
        layers_present = {entry.layer for entry in CognitiveAgent.SENSORIUM_REGISTRY.values()}
        assert SensoriumLayer.PROPRIOCEPTION in layers_present
        assert SensoriumLayer.INTEROCEPTION in layers_present
        assert SensoriumLayer.EXTEROCEPTION in layers_present


class TestTrackSensoriumBudget:
    def test_track_signature_and_return_remain_exact(self) -> None:
        signature = inspect.signature(CognitiveAgent._track_sensorium_budget)
        assert list(signature.parameters) == ["self", "cognitive_state", "situation"]
        assert signature.return_annotation in ("int", int)

        runtime = _make_runtime_with_sensorium_config(threshold=6000)
        agent = _make_agent(runtime=runtime)
        assert agent._track_sensorium_budget({"a": "abc"}, {"b": "de"}) == 5

    def test_under_budget_returns_count_no_event(self) -> None:
        runtime = _make_runtime_with_sensorium_config(threshold=6000)
        agent = _make_agent(runtime=runtime)
        cognitive = {"_temporal_context": "x" * 100, "_agent_metrics": "y" * 50}

        result = agent._track_sensorium_budget(cognitive, {})

        assert result == 150
        assert runtime.events == []

    def test_first_crossing_emits_crossed_warning_and_typed_event_immediately(
        self, caplog: pytest.LogCaptureFixture,
    ) -> None:
        runtime = _make_runtime_with_sensorium_config(threshold=100)
        agent = _make_agent(runtime=runtime)
        cognitive = {"_temporal_context": "x" * 80, "_agent_metrics": "y" * 50}
        situation = {"_ward_room_activity": "z" * 30}

        with caplog.at_level("WARNING", logger="probos.cognitive.cognitive_agent"):
            result = agent._track_sensorium_budget(cognitive, situation)

        assert result == 160
        assert len(runtime.events) == 1
        event = _event(runtime)
        assert isinstance(event, SensoriumBudgetExceededEvent)
        assert event.event_type == EventType.SENSORIUM_BUDGET_EXCEEDED
        assert event.total_chars == 160
        assert event.threshold == event.character_threshold == 100
        assert event.reason == "crossed"
        assert event.callsign == "TestAgent"
        assert "merged chain sensorium character footprint" in caplog.text
        assert "not the full request/model-window measurement" in caplog.text
        for field_name in (
            "agent_id",
            "callsign",
            "reason",
            "total_chars",
            "estimated_tokens",
            "character_threshold",
            "cognitive_state_chars",
            "situation_chars",
            "suppressed_count",
            "peak_chars",
            "top_contributors",
        ):
            assert f"{field_name}=" in caplog.text

    def test_truthful_units_and_metadata_contain_no_content_hash_or_snippet(
        self, caplog: pytest.LogCaptureFixture,
    ) -> None:
        runtime = _make_runtime_with_sensorium_config(threshold=1)
        agent = _make_agent(runtime=runtime)
        secret = "PRIVATE-CONTENT-XYZ"

        with caplog.at_level("WARNING", logger="probos.cognitive.cognitive_agent"):
            agent._track_sensorium_budget({"mystery": secret}, {})

        event = _event(runtime)
        assert event.total_chars == len(secret)
        assert event.estimated_tokens == estimate_tokens(secret)
        serialized = str(event.top_contributors) + caplog.text
        assert secret not in serialized
        for forbidden in ("snippet", "content_hash", "digest", "embedding", "repr"):
            assert forbidden not in str(event.top_contributors)
        assert event.top_contributors[0] == {
            "bucket": "cognitive",
            "output_key": "mystery",
            "layer": None,
            "chars": len(secret),
            "estimated_tokens": estimate_tokens(secret),
        }

    def test_contributors_sort_by_negative_chars_key_bucket(self) -> None:
        runtime = _make_runtime_with_sensorium_config(threshold=1, top_contributors=10)
        agent = _make_agent(runtime=runtime)

        agent._track_sensorium_budget(
            {"z": "1" * 2, "a": "2" * 4, "same": "3" * 3},
            {"same": "4" * 3, "b": "5" * 4},
        )

        rows = _event(runtime).top_contributors
        assert [(r["chars"], r["output_key"], r["bucket"]) for r in rows] == [
            (4, "a", "cognitive"),
            (4, "b", "situation"),
            (3, "same", "cognitive"),
            (3, "same", "situation"),
            (2, "z", "cognitive"),
        ]

    def test_contributor_layers_are_resolved_by_bucket_chain_path(self) -> None:
        runtime = _make_runtime_with_sensorium_config(threshold=1, top_contributors=10)
        agent = _make_agent(runtime=runtime)

        agent._track_sensorium_budget(
            {"_cold_start_note": "cold cognitive"},
            {"_cold_start_note": "cold situation"},
        )

        rows = {r["bucket"]: r for r in _event(runtime).top_contributors}
        assert rows["cognitive"]["layer"] == "interoception"
        assert rows["situation"]["layer"] == "exteroception"

    def test_unknown_or_ambiguous_contributor_layer_is_none(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        runtime = _make_runtime_with_sensorium_config(threshold=1, top_contributors=10)
        agent = _make_agent(runtime=runtime)
        registry = dict(CognitiveAgent.SENSORIUM_REGISTRY)
        registry["_ad1122_ambiguous_a"] = SensoriumEntry(
            layer=SensoriumLayer.PROPRIOCEPTION,
            description="ambiguous A",
            paths=(SensoriumPath.CHAIN_BASELINE,),
            output_key="ambiguous",
        )
        registry["_ad1122_ambiguous_b"] = SensoriumEntry(
            layer=SensoriumLayer.INTEROCEPTION,
            description="ambiguous B",
            paths=(SensoriumPath.CHAIN_EXTENSIONS,),
            output_key="ambiguous",
        )
        monkeypatch.setattr(CognitiveAgent, "SENSORIUM_REGISTRY", registry)

        agent._track_sensorium_budget({"unknown": "xxx", "ambiguous": "yyyy"}, {})

        rows = {r["output_key"]: r for r in _event(runtime).top_contributors}
        assert rows["unknown"]["layer"] is None
        assert rows["ambiguous"]["layer"] is None

    def test_empty_and_nonstring_entries_are_ignored_without_mutating_inputs(self) -> None:
        runtime = _make_runtime_with_sensorium_config(threshold=1, top_contributors=10)
        agent = _make_agent(runtime=runtime)
        cognitive: dict[str, Any] = {"text": "hello", "empty": "", "none": None}
        situation: dict[str, Any] = {"number": 7, "text": "xy"}
        cognitive_before = dict(cognitive)
        situation_before = dict(situation)

        result = agent._track_sensorium_budget(cognitive, situation)  # type: ignore[arg-type]

        assert result == 7
        assert cognitive == cognitive_before
        assert situation == situation_before
        assert {r["bucket"] for r in _event(runtime).top_contributors} == {
            "cognitive", "situation"
        }

    def test_equal_warning_threshold_does_not_cross(self) -> None:
        runtime = _make_runtime_with_sensorium_config(threshold=5)
        agent = _make_agent(runtime=runtime)

        assert agent._track_sensorium_budget({"a": "12345"}, {}) == 5
        assert runtime.events == []

    def test_active_equal_warning_threshold_does_not_rearm(self) -> None:
        runtime = _make_runtime_with_sensorium_config(threshold=100, cooldown=999)
        agent = _make_agent(runtime=runtime, clock=_Clock())

        agent._track_sensorium_budget({"a": "x" * 110}, {})
        agent._track_sensorium_budget({"a": "x" * 100}, {})
        agent._track_sensorium_budget({"a": "x" * 110}, {})

        assert [event.reason for event in runtime.events] == ["crossed"]
        assert agent._sensorium_budget_suppressed_count == 1

    def test_sustained_overage_suppresses_and_accumulates_count_and_peak(self) -> None:
        clock = _Clock()
        runtime = _make_runtime_with_sensorium_config(threshold=100, cooldown=60)
        agent = _make_agent(runtime=runtime, clock=clock)

        agent._track_sensorium_budget({"a": "x" * 110}, {})
        agent._track_sensorium_budget({"a": "x" * 120}, {})
        agent._track_sensorium_budget({"a": "x" * 115}, {})

        assert len(runtime.events) == 1
        assert agent._sensorium_budget_suppressed_count == 2
        assert agent._sensorium_budget_peak_chars == 120

    def test_cooldown_boundary_emits_sustained_summary(self) -> None:
        clock = _Clock()
        runtime = _make_runtime_with_sensorium_config(threshold=100, cooldown=60)
        agent = _make_agent(runtime=runtime, clock=clock)
        agent._track_sensorium_budget({"a": "x" * 110}, {})
        agent._track_sensorium_budget({"a": "x" * 120}, {})
        clock.advance(60)

        agent._track_sensorium_budget({"a": "x" * 115}, {})

        event = _event(runtime)
        assert event.reason == "sustained"
        assert event.suppressed_count == 1
        assert event.peak_chars == 120

    def test_early_escalation_emits_once_before_cooldown(self) -> None:
        runtime = _make_runtime_with_sensorium_config(
            threshold=100, cooldown=999, escalation_ratio=1.25,
        )
        agent = _make_agent(runtime=runtime, clock=_Clock())

        agent._track_sensorium_budget({"a": "x" * 110}, {})
        agent._track_sensorium_budget({"a": "x" * 125}, {})
        agent._track_sensorium_budget({"a": "x" * 150}, {})

        assert [event.reason for event in runtime.events] == ["crossed", "escalated"]

    def test_initial_severe_crossing_is_crossed_and_does_not_double_escalate(self) -> None:
        runtime = _make_runtime_with_sensorium_config(
            threshold=100, cooldown=999, escalation_ratio=1.25,
        )
        agent = _make_agent(runtime=runtime, clock=_Clock())

        agent._track_sensorium_budget({"a": "x" * 130}, {})
        agent._track_sensorium_budget({"a": "x" * 130}, {})

        assert [event.reason for event in runtime.events] == ["crossed"]
        assert agent._sensorium_budget_suppressed_count == 1

    def test_rearm_ratio_equality_does_not_rearm(self) -> None:
        runtime = _make_runtime_with_sensorium_config(
            threshold=100, cooldown=999, rearm_ratio=0.90,
        )
        agent = _make_agent(runtime=runtime, clock=_Clock())

        agent._track_sensorium_budget({"a": "x" * 110}, {})
        agent._track_sensorium_budget({"a": "x" * 90}, {})
        agent._track_sensorium_budget({"a": "x" * 110}, {})

        assert [event.reason for event in runtime.events] == ["crossed"]

    def test_strictly_below_rearm_ratio_rearms_next_crossing(self) -> None:
        runtime = _make_runtime_with_sensorium_config(
            threshold=100, cooldown=999, rearm_ratio=0.90,
        )
        agent = _make_agent(runtime=runtime, clock=_Clock())

        agent._track_sensorium_budget({"a": "x" * 110}, {})
        agent._track_sensorium_budget({"a": "x" * 89}, {})
        agent._track_sensorium_budget({"a": "x" * 110}, {})

        assert [event.reason for event in runtime.events] == ["crossed", "crossed"]

    def test_cooldown_zero_emits_every_overage_cycle(self) -> None:
        runtime = _make_runtime_with_sensorium_config(
            threshold=100, cooldown=0, escalation_ratio=2.0,
        )
        agent = _make_agent(runtime=runtime, clock=_Clock())

        for chars in (110, 111, 112):
            agent._track_sensorium_budget({"a": "x" * chars}, {})

        assert [event.reason for event in runtime.events] == [
            "crossed", "sustained", "sustained"
        ]

    def test_disabled_returns_count_emits_nothing_and_resets_episode(self) -> None:
        runtime = _make_runtime_with_sensorium_config(threshold=100)
        agent = _make_agent(runtime=runtime, clock=_Clock())
        agent._track_sensorium_budget({"a": "x" * 110}, {})
        runtime.config.sensorium.enabled = False

        assert agent._track_sensorium_budget({"a": "x" * 120}, {}) == 120
        assert len(runtime.events) == 1
        assert agent._sensorium_budget_active is False
        assert agent._sensorium_budget_last_threshold is None
        runtime.config.sensorium.enabled = True
        agent._track_sensorium_budget({"a": "x" * 110}, {})
        assert [event.reason for event in runtime.events] == ["crossed", "crossed"]

    def test_warning_chars_change_resets_and_re_evaluates_current_sample(self) -> None:
        runtime = _make_runtime_with_sensorium_config(threshold=100, cooldown=999)
        agent = _make_agent(runtime=runtime, clock=_Clock())
        agent._track_sensorium_budget({"a": "x" * 110}, {})

        runtime.config.sensorium.warning_chars = 105
        agent._track_sensorium_budget({"a": "x" * 110}, {})

        assert [event.reason for event in runtime.events] == ["crossed", "crossed"]

    def test_debounce_state_is_isolated_per_agent(self) -> None:
        runtime_a = _make_runtime_with_sensorium_config(threshold=100, cooldown=999)
        runtime_b = _make_runtime_with_sensorium_config(threshold=100, cooldown=999)
        a = _make_agent(runtime=runtime_a, agent_id="a", clock=_Clock())
        b = _make_agent(runtime=runtime_b, agent_id="b", clock=_Clock())

        a._track_sensorium_budget({"x": "1" * 110}, {})
        b._track_sensorium_budget({"x": "1" * 110}, {})
        a._track_sensorium_budget({"x": "1" * 110}, {})

        assert len(runtime_a.events) == 1
        assert len(runtime_b.events) == 1
        assert a._sensorium_budget_suppressed_count == 1
        assert b._sensorium_budget_suppressed_count == 0

    @pytest.mark.asyncio
    async def test_stop_resets_debounce_state(self) -> None:
        runtime = _make_runtime_with_sensorium_config(threshold=100, cooldown=999)
        agent = _make_agent(runtime=runtime, clock=_Clock())
        agent._track_sensorium_budget({"a": "x" * 110}, {})

        await agent.stop()
        agent._track_sensorium_budget({"a": "x" * 110}, {})

        assert [event.reason for event in runtime.events] == ["crossed", "crossed"]

    def test_emitter_failure_degrades_without_rewinding_debounce_state(
        self, caplog: pytest.LogCaptureFixture,
    ) -> None:
        runtime = _FailingRuntime(SensoriumConfig(warning_chars=100))
        agent = _make_agent(runtime=runtime, clock=_Clock())

        with caplog.at_level("WARNING", logger="probos.cognitive.cognitive_agent"):
            agent._track_sensorium_budget({"a": "x" * 110}, {})
            agent._track_sensorium_budget({"a": "x" * 110}, {})

        assert caplog.text.count("merged chain sensorium character footprint") == 1
        assert caplog.text.count("telemetry continues") == 1
        assert agent._sensorium_budget_active is True
        assert agent._sensorium_budget_suppressed_count == 1

    def test_transition_logging_failure_does_not_abort_or_skip_typed_event(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        runtime = _make_runtime_with_sensorium_config(threshold=100, cooldown=999)
        agent = _make_agent(runtime=runtime, clock=_Clock())
        warning_attempts = 0

        def fail_warning(*args: object, **kwargs: object) -> None:
            nonlocal warning_attempts
            warning_attempts += 1
            raise RuntimeError("logging sink offline")

        monkeypatch.setattr(
            "probos.cognitive.cognitive_agent.logger.warning", fail_warning
        )

        result = agent._track_sensorium_budget({"a": "x" * 110}, {})

        assert result == 110
        assert warning_attempts == 1
        assert len(runtime.events) == 1
        assert _event(runtime).reason == "crossed"
        assert agent._sensorium_budget_active is True
        assert agent._sensorium_budget_last_emitted_at == 100.0

    def test_logging_and_emitter_failure_return_count_without_repeating_transition(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        runtime = _FailingRuntime(SensoriumConfig(warning_chars=100))
        agent = _make_agent(runtime=runtime, clock=_Clock())
        warning_attempts = 0

        def fail_warning(*args: object, **kwargs: object) -> None:
            nonlocal warning_attempts
            warning_attempts += 1
            raise RuntimeError("logging sink offline")

        monkeypatch.setattr(
            "probos.cognitive.cognitive_agent.logger.warning", fail_warning
        )

        first = agent._track_sensorium_budget({"a": "x" * 110}, {})
        second = agent._track_sensorium_budget({"a": "x" * 110}, {})

        assert first == second == 110
        assert warning_attempts == 2
        assert runtime.emit_attempts == 1
        assert agent._sensorium_budget_active is True
        assert agent._sensorium_budget_last_emitted_at == 100.0
        assert agent._sensorium_budget_suppressed_count == 1

    def test_warning_and_event_occur_only_at_transitions(
        self, caplog: pytest.LogCaptureFixture,
    ) -> None:
        runtime = _make_runtime_with_sensorium_config(threshold=100, cooldown=999)
        agent = _make_agent(runtime=runtime, clock=_Clock())

        with caplog.at_level("WARNING", logger="probos.cognitive.cognitive_agent"):
            agent._track_sensorium_budget({"a": "x" * 110}, {})
            agent._track_sensorium_budget({"a": "x" * 111}, {})

        assert len(runtime.events) == 1
        assert caplog.text.count("merged chain sensorium character footprint") == 1

    def test_no_runtime_uses_defaults_and_preserves_return_contract(self) -> None:
        agent = _make_agent(runtime=None, clock=_Clock())

        assert agent._track_sensorium_budget({"_small": "x" * 100}, {}) == 100
        assert agent._track_sensorium_budget({"_big": "x" * 10_001}, {}) == 10_001

    def test_same_output_key_surviving_in_both_buckets_counts_two_rows_and_both_totals(self) -> None:
        runtime = _make_runtime_with_sensorium_config(threshold=1, top_contributors=10)
        agent = _make_agent(runtime=runtime)

        agent._track_sensorium_budget(
            {"_cold_start_note": "abc"}, {"_cold_start_note": "defgh"}
        )

        event = _event(runtime)
        assert event.total_chars == 8
        assert len(event.top_contributors) == 2
        assert {row["bucket"] for row in event.top_contributors} == {
            "cognitive", "situation"
        }

    def test_estimated_token_aggregate_uses_per_entry_rounding_before_top_n(self) -> None:
        runtime = _make_runtime_with_sensorium_config(threshold=1, top_contributors=1)
        agent = _make_agent(runtime=runtime)

        agent._track_sensorium_budget({"a": "x", "b": "y", "c": "z"}, {})

        event = _event(runtime)
        assert event.estimated_tokens == 3
        assert len(event.top_contributors) == 1
        assert event.top_contributors[0]["estimated_tokens"] == 1

    def test_top_contributors_zero_and_n_change_rows_only(self) -> None:
        config_zero = SensoriumConfig(warning_chars=1, top_contributors=0)
        config_many = SensoriumConfig(warning_chars=1, top_contributors=5)
        rt_zero = _Runtime(config_zero)
        rt_many = _Runtime(config_many)
        zero = _make_agent(runtime=rt_zero, clock=_Clock())
        many = _make_agent(runtime=rt_many, clock=_Clock())
        payload = {"a": "x" * 5, "b": "y" * 3}

        zero._track_sensorium_budget(payload, {})
        many._track_sensorium_budget(payload, {})

        a, b = _event(rt_zero), _event(rt_many)
        assert a.total_chars == b.total_chars == 8
        assert a.estimated_tokens == b.estimated_tokens
        assert a.reason == b.reason == "crossed"
        assert a.top_contributors == []
        assert len(b.top_contributors) == 2

    def test_simultaneous_escalation_and_cooldown_emits_escalated_only(self) -> None:
        clock = _Clock()
        runtime = _make_runtime_with_sensorium_config(
            threshold=100, cooldown=10, escalation_ratio=1.25,
        )
        agent = _make_agent(runtime=runtime, clock=clock)
        agent._track_sensorium_budget({"a": "x" * 110}, {})
        clock.advance(10)

        agent._track_sensorium_budget({"a": "x" * 125}, {})

        assert [event.reason for event in runtime.events] == ["crossed", "escalated"]

    def test_emission_resets_interval_suppressed_count_and_peak_anchor(self) -> None:
        clock = _Clock()
        runtime = _make_runtime_with_sensorium_config(
            threshold=100, cooldown=10, escalation_ratio=2.0,
        )
        agent = _make_agent(runtime=runtime, clock=clock)
        agent._track_sensorium_budget({"a": "x" * 110}, {})
        agent._track_sensorium_budget({"a": "x" * 150}, {})
        clock.advance(10)
        agent._track_sensorium_budget({"a": "x" * 120}, {})

        event = _event(runtime)
        assert event.suppressed_count == 1
        assert event.peak_chars == 150
        assert agent._sensorium_budget_suppressed_count == 0
        assert agent._sensorium_budget_peak_chars == 120

    def test_threshold_change_over_emits_crossed_and_non_over_stays_quiet(self) -> None:
        runtime = _make_runtime_with_sensorium_config(threshold=100, cooldown=999)
        agent = _make_agent(runtime=runtime, clock=_Clock())
        agent._track_sensorium_budget({"a": "x" * 110}, {})
        runtime.config.sensorium.warning_chars = 105
        agent._track_sensorium_budget({"a": "x" * 110}, {})
        runtime.config.sensorium.warning_chars = 200
        agent._track_sensorium_budget({"a": "x" * 110}, {})

        assert [event.reason for event in runtime.events] == ["crossed", "crossed"]
        assert agent._sensorium_budget_active is False
        assert agent._sensorium_budget_last_threshold == 200

    def test_runtime_less_transition_warns_once_without_event(
        self, caplog: pytest.LogCaptureFixture,
    ) -> None:
        agent = _make_agent(runtime=None, clock=_Clock())
        with caplog.at_level("WARNING", logger="probos.cognitive.cognitive_agent"):
            agent._track_sensorium_budget({"a": "x" * 10_001}, {})
            agent._track_sensorium_budget({"a": "x" * 10_001}, {})
        assert caplog.text.count("merged chain sensorium character footprint") == 1

    def test_wrong_shaped_warning_chars_uses_default_10000(self) -> None:
        harness = _HarnessSensorium()
        harness.warning_chars = MagicMock(name="warning_chars")
        runtime = _Runtime(harness)
        agent = _make_agent(runtime=runtime, clock=_Clock())

        result = agent._track_sensorium_budget({"a": "x" * 10_001}, {})

        assert result == 10_001
        assert len(runtime.events) == 1
        assert _event(runtime).character_threshold == 10_000

    def test_wrong_shaped_cooldown_uses_default_boundary(self) -> None:
        harness = _HarnessSensorium(
            warning_chars=100,
            warning_cooldown_seconds=MagicMock(name="warning_cooldown_seconds"),
            warning_escalation_ratio=2.0,
        )
        runtime = _Runtime(harness)
        clock = _Clock()
        agent = _make_agent(runtime=runtime, clock=clock)

        agent._track_sensorium_budget({"a": "x" * 110}, {})
        clock.advance(21_599.0)
        agent._track_sensorium_budget({"a": "x" * 111}, {})
        clock.advance(1.0)
        agent._track_sensorium_budget({"a": "x" * 112}, {})

        assert [event.reason for event in runtime.events] == ["crossed", "sustained"]
        assert runtime.events[-1].suppressed_count == 1

    def test_wrong_shaped_rearm_uses_default_strict_boundaries(self) -> None:
        harness = _HarnessSensorium(
            warning_chars=100,
            warning_cooldown_seconds=999_999.0,
            warning_rearm_ratio=MagicMock(name="warning_rearm_ratio"),
        )
        runtime = _Runtime(harness)
        agent = _make_agent(runtime=runtime, clock=_Clock())

        agent._track_sensorium_budget({"a": "x" * 110}, {})
        agent._track_sensorium_budget({"a": "x" * 90}, {})
        agent._track_sensorium_budget({"a": "x" * 110}, {})
        agent._track_sensorium_budget({"a": "x" * 89}, {})
        agent._track_sensorium_budget({"a": "x" * 110}, {})

        assert [event.reason for event in runtime.events] == ["crossed", "crossed"]
        assert runtime.events[-1].suppressed_count == 0

    def test_wrong_shaped_escalation_uses_default_exact_boundary(self) -> None:
        harness = _HarnessSensorium(
            warning_chars=100,
            warning_cooldown_seconds=999_999.0,
            warning_escalation_ratio=MagicMock(name="warning_escalation_ratio"),
        )
        runtime = _Runtime(harness)
        agent = _make_agent(runtime=runtime, clock=_Clock())

        agent._track_sensorium_budget({"a": "x" * 110}, {})
        agent._track_sensorium_budget({"a": "x" * 125}, {})

        assert [event.reason for event in runtime.events] == ["crossed", "escalated"]

    def test_wrong_shaped_top_contributors_uses_default_top_five(self) -> None:
        harness = _HarnessSensorium(
            warning_chars=1,
            top_contributors=MagicMock(name="top_contributors"),
        )
        runtime = _Runtime(harness)
        agent = _make_agent(runtime=runtime, clock=_Clock())
        payload = {f"key-{index}": "x" * index for index in range(1, 7)}

        agent._track_sensorium_budget(payload, {})

        event = _event(runtime)
        assert len(event.top_contributors) == 5
        assert [row["chars"] for row in event.top_contributors] == [6, 5, 4, 3, 2]

    def test_live_cooldown_change_applies_next_observation_without_history_erasure(
        self,
    ) -> None:
        clock = _Clock()
        runtime = _make_runtime_with_sensorium_config(
            threshold=100, cooldown=100, escalation_ratio=2.0,
        )
        agent = _make_agent(runtime=runtime, clock=clock)
        agent._track_sensorium_budget({"a": "x" * 110}, {})
        agent._track_sensorium_budget({"a": "x" * 130}, {})
        clock.advance(10)

        runtime.config.sensorium.warning_cooldown_seconds = 10
        agent._track_sensorium_budget({"a": "x" * 120}, {})

        event = _event(runtime)
        assert event.reason == "sustained"
        assert event.suppressed_count == 1
        assert event.peak_chars == 130

    def test_live_rearm_change_applies_next_observation_without_history_erasure(
        self,
    ) -> None:
        runtime = _make_runtime_with_sensorium_config(
            threshold=100, cooldown=999_999, rearm_ratio=0.50,
        )
        agent = _make_agent(runtime=runtime, clock=_Clock())
        agent._track_sensorium_budget({"a": "x" * 110}, {})
        agent._track_sensorium_budget({"a": "x" * 89}, {})
        assert agent._sensorium_budget_active is True

        runtime.config.sensorium.warning_rearm_ratio = 0.90
        agent._track_sensorium_budget({"a": "x" * 89}, {})
        assert agent._sensorium_budget_active is False
        agent._track_sensorium_budget({"a": "x" * 110}, {})

        assert [event.reason for event in runtime.events] == ["crossed", "crossed"]

    def test_live_escalation_change_applies_next_observation_without_history_erasure(
        self,
    ) -> None:
        runtime = _make_runtime_with_sensorium_config(
            threshold=100, cooldown=999_999, escalation_ratio=2.0,
        )
        agent = _make_agent(runtime=runtime, clock=_Clock())
        agent._track_sensorium_budget({"a": "x" * 110}, {})
        agent._track_sensorium_budget({"a": "x" * 130}, {})

        runtime.config.sensorium.warning_escalation_ratio = 1.25
        agent._track_sensorium_budget({"a": "x" * 125}, {})

        event = _event(runtime)
        assert event.reason == "escalated"
        assert event.suppressed_count == 1
        assert event.peak_chars == 130

    def test_live_top_n_change_applies_next_observation_without_history_erasure(
        self,
    ) -> None:
        clock = _Clock()
        runtime = _make_runtime_with_sensorium_config(
            threshold=1, cooldown=10, escalation_ratio=10.0, top_contributors=1,
        )
        agent = _make_agent(runtime=runtime, clock=clock)
        payload = {"a": "x" * 6, "b": "x" * 5, "c": "x" * 4}
        agent._track_sensorium_budget(payload, {})
        agent._track_sensorium_budget(payload, {})
        clock.advance(10)

        runtime.config.sensorium.top_contributors = 3
        agent._track_sensorium_budget(payload, {})

        event = _event(runtime)
        assert event.reason == "sustained"
        assert event.suppressed_count == 1
        assert len(event.top_contributors) == 3

    def test_both_transition_and_emitter_degrade_warning_strings_are_capability_gap_clean(
        self, caplog: pytest.LogCaptureFixture,
    ) -> None:
        runtime = _FailingRuntime(SensoriumConfig(warning_chars=100))
        agent = _make_agent(runtime=runtime, clock=_Clock())
        with caplog.at_level("WARNING", logger="probos.cognitive.cognitive_agent"):
            agent._track_sensorium_budget({"a": "x" * 110}, {})
        warnings = [record.getMessage() for record in caplog.records]
        assert len(warnings) == 2
        assert all(not is_capability_gap(message) for message in warnings)

    @pytest.mark.asyncio
    async def test_tracking_preserves_chain_prompt_context_and_makes_no_llm_call(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        runtime = _make_runtime_with_sensorium_config(threshold=1_000_000)
        agent = _make_agent(runtime=runtime)
        llm = _StrictLLM()
        sub_tasks = _StrictSubTaskExecutor()
        agent._llm_client = llm
        agent._sub_task_executor = sub_tasks
        sequence: list[str] = []
        built: dict[str, dict[str, str]] = {}
        tracked_snapshots: list[tuple[list[tuple[str, str]], list[tuple[str, str]]]] = []
        tracked_results: list[int] = []

        original_cognitive_builder = agent._build_cognitive_state
        original_situation_builder = agent._build_situation_awareness
        original_tracker = agent._track_sensorium_budget
        original_memory_formatter = agent._format_memory_section
        original_chain_builder = agent._build_chain_for_intent

        def record_cognitive_build(
            context_parts: dict, observation: dict | None = None,
        ) -> dict[str, str]:
            result = original_cognitive_builder(context_parts, observation=observation)
            assert result
            built["cognitive"] = result
            sequence.append("cognitive_build")
            return result

        def record_situation_build(context_parts: dict) -> dict[str, str]:
            result = original_situation_builder(context_parts)
            assert result
            built["situation"] = result
            sequence.append("situation_build")
            return result

        def record_tracking(
            cognitive_state: dict[str, str], situation: dict[str, str],
        ) -> int:
            assert cognitive_state is built["cognitive"]
            assert situation is built["situation"]
            tracked_snapshots.append(
                (list(cognitive_state.items()), list(situation.items()))
            )
            sequence.append("tracking")
            result = original_tracker(cognitive_state, situation)
            tracked_results.append(result)
            return result

        def record_memory_formatting(
            memories: list[dict], source_framing: Any = None,
        ) -> list[str]:
            sequence.append("memory_formatting")
            return original_memory_formatter(memories, source_framing=source_framing)

        def stop_after_chain_construction(observation: dict) -> object:
            chain = original_chain_builder(observation)
            assert chain is not None
            sequence.append("chain_construction")
            raise _StopAfterChainConstruction

        monkeypatch.setattr(agent, "_build_cognitive_state", record_cognitive_build)
        monkeypatch.setattr(agent, "_build_situation_awareness", record_situation_build)
        monkeypatch.setattr(agent, "_track_sensorium_budget", record_tracking)
        monkeypatch.setattr(agent, "_format_memory_section", record_memory_formatting)
        monkeypatch.setattr(agent, "_build_chain_for_intent", stop_after_chain_construction)

        observation = {
            "intent": "ward_room_notification",
            "intent_id": "ad1122-sequence",
            "recent_memories": [{"input": "A remembered observation."}],
            "params": {
                "author_id": "crew-agent",
                "channel_name": "Bridge",
                "is_dm_channel": False,
                "context_parts": {
                    "system_note": "SYSTEM NOTE: deterministic correction test.",
                    "recent_alerts": [
                        {"severity": "INFO", "title": "Test alert", "source": "suite"}
                    ],
                },
            },
        }

        with pytest.raises(_StopAfterChainConstruction):
            await agent._execute_chain_with_intent_routing(observation)

        assert sequence == [
            "cognitive_build",
            "situation_build",
            "tracking",
            "memory_formatting",
            "chain_construction",
        ]
        assert len(tracked_snapshots) == 1
        assert list(built["cognitive"].items()) == tracked_snapshots[0][0]
        assert list(built["situation"].items()) == tracked_snapshots[0][1]
        assert len(tracked_results) == 1
        assert isinstance(tracked_results[0], int)
        assert tracked_results[0] == sum(
            len(value)
            for bucket in (built["cognitive"], built["situation"])
            for value in bucket.values()
            if isinstance(value, str) and value
        )
        assert llm.calls == 0
        assert sub_tasks.calls == 0

        source = textwrap.dedent(
            inspect.getsource(CognitiveAgent._execute_chain_with_intent_routing)
        )
        tree = ast.parse(source)
        track_calls = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "_track_sensorium_budget"
        ]
        assert len(track_calls) == 1

    def test_disabled_config_skips_event(self) -> None:
        runtime = _make_runtime_with_sensorium_config(enabled=False, threshold=10)
        agent = _make_agent(runtime=runtime)

        result = agent._track_sensorium_budget({"_big": "x" * 1000}, {})

        assert result == 1000
        assert runtime.events == []

    def test_empty_dicts_returns_zero(self) -> None:
        agent = _make_agent(runtime=None)

        result = agent._track_sensorium_budget({}, {})

        assert result == 0


class TestSensoriumEventType:
    def test_event_type_exists(self) -> None:
        assert hasattr(EventType, "SENSORIUM_BUDGET_EXCEEDED")
        assert EventType.SENSORIUM_BUDGET_EXCEEDED == "sensorium_budget_exceeded"


class TestSensoriumConfig:
    def test_sensorium_config_canonical_defaults(self) -> None:
        config = SensoriumConfig()
        assert config.enabled is True
        assert config.warning_chars == 10_000
        assert config.warning_cooldown_seconds == 21_600.0
        assert config.warning_rearm_ratio == 0.90
        assert config.warning_escalation_ratio == 1.25
        assert config.top_contributors == 5

    def test_sensorium_config_accepts_legacy_alias(self) -> None:
        config = SensoriumConfig(token_budget_warning=123)
        assert config.warning_chars == 123
        assert config.token_budget_warning == 123

    def test_sensorium_config_canonical_wins_when_both_keys_present(self) -> None:
        for payload in (
            {"warning_chars": 456, "token_budget_warning": 123},
            {"token_budget_warning": 123, "warning_chars": 456},
        ):
            assert SensoriumConfig.model_validate(payload).warning_chars == 456

    def test_sensorium_config_dump_is_canonical_and_legacy_property_reads_value(self) -> None:
        config = SensoriumConfig(warning_chars=456)
        for dumped in (config.model_dump(), config.model_dump(by_alias=True)):
            assert dumped["warning_chars"] == 456
            assert "token_budget_warning" not in dumped
        for mode in ("validation", "serialization"):
            properties = SensoriumConfig.model_json_schema(mode=mode)["properties"]
            assert "warning_chars" in properties
            assert "token_budget_warning" not in properties
        assert config.token_budget_warning == 456
        with pytest.raises((AttributeError, ValidationError)):
            config.token_budget_warning = 999  # type: ignore[misc]

    def test_load_config_accepts_legacy_sensorium_yaml_without_repo_yaml_edit(
        self, tmp_path: Path,
    ) -> None:
        path = tmp_path / "legacy.yaml"
        path.write_text(
            "sensorium:\n  enabled: true\n  token_budget_warning: 4321\n",
            encoding="utf-8",
        )

        config = load_config(path)

        assert config.sensorium.warning_chars == 4321
        assert config.sensorium.token_budget_warning == 4321

    @pytest.mark.parametrize(
        ("field_name", "bad_value"),
        [
            ("warning_chars", True),
            ("warning_chars", 0),
            ("warning_cooldown_seconds", True),
            ("warning_cooldown_seconds", -0.01),
            ("warning_cooldown_seconds", float("nan")),
            ("warning_cooldown_seconds", float("inf")),
            ("warning_rearm_ratio", True),
            ("warning_rearm_ratio", 0),
            ("warning_rearm_ratio", 1),
            ("warning_rearm_ratio", float("nan")),
            ("warning_escalation_ratio", True),
            ("warning_escalation_ratio", 0.99),
            ("warning_escalation_ratio", float("-inf")),
            ("top_contributors", True),
            ("top_contributors", -1),
        ],
    )
    def test_sensorium_config_rejects_bool_nonfinite_and_out_of_range_values(
        self, field_name: str, bad_value: object,
    ) -> None:
        with pytest.raises(ValidationError):
            SensoriumConfig.model_validate({field_name: bad_value})

        valid = SensoriumConfig(
            warning_chars=1,
            warning_cooldown_seconds=0,
            warning_rearm_ratio=math.nextafter(0.0, 1.0),
            warning_escalation_ratio=1,
            top_contributors=0,
        )
        assert valid.warning_chars == 1
        assert valid.warning_cooldown_seconds == 0
        assert 0 < valid.warning_rearm_ratio < 1
        assert valid.warning_escalation_ratio == 1
        assert valid.top_contributors == 0
        assert SensoriumConfig(
            warning_chars="2",
            warning_cooldown_seconds="3.5",
            warning_rearm_ratio="0.5",
            warning_escalation_ratio="1.5",
            top_contributors="4",
        ).model_dump() == {
            "enabled": True,
            "warning_chars": 2,
            "warning_cooldown_seconds": 3.5,
            "warning_rearm_ratio": 0.5,
            "warning_escalation_ratio": 1.5,
            "top_contributors": 4,
        }

    def test_system_config_has_sensorium(self) -> None:
        system_config = SystemConfig()
        assert hasattr(system_config, "sensorium")
        assert system_config.sensorium.enabled is True
        assert system_config.sensorium.warning_chars == 10000
