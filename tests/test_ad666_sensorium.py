"""AD-666: Agent Sensorium Formalization tests."""

from __future__ import annotations

from unittest.mock import MagicMock

from probos.cognitive.cognitive_agent import CognitiveAgent, SensoriumLayer
from probos.events import EventType


def _make_agent(**kwargs: object) -> CognitiveAgent:
    agent = CognitiveAgent(agent_id="test-agent", instructions="Test instructions.")
    agent.callsign = "TestAgent"
    agent.agent_type = "test_agent"
    agent._runtime = kwargs.get("runtime", None)
    return agent


def _make_runtime_with_sensorium_config(
    enabled: bool = True,
    threshold: int = 6000,
) -> MagicMock:
    runtime = MagicMock()
    runtime.config.sensorium.enabled = enabled
    runtime.config.sensorium.token_budget_warning = threshold
    runtime._emit_event = MagicMock()
    return runtime


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
        for method_name, (layer, description) in CognitiveAgent.SENSORIUM_REGISTRY.items():
            assert isinstance(method_name, str)
            assert layer in (
                SensoriumLayer.PROPRIOCEPTION,
                SensoriumLayer.INTEROCEPTION,
                SensoriumLayer.EXTEROCEPTION,
            )
            assert isinstance(description, str) and len(description) > 0

    def test_all_registry_methods_exist_on_class(self) -> None:
        for method_name in CognitiveAgent.SENSORIUM_REGISTRY:
            assert hasattr(CognitiveAgent, method_name)

    def test_registry_has_all_three_layers(self) -> None:
        layers_present = {layer for (layer, _) in CognitiveAgent.SENSORIUM_REGISTRY.values()}
        assert SensoriumLayer.PROPRIOCEPTION in layers_present
        assert SensoriumLayer.INTEROCEPTION in layers_present
        assert SensoriumLayer.EXTEROCEPTION in layers_present


class TestTrackSensoriumBudget:
    def test_under_budget_returns_count_no_event(self) -> None:
        runtime = _make_runtime_with_sensorium_config(threshold=6000)
        agent = _make_agent(runtime=runtime)
        cognitive = {"_temporal_context": "x" * 100, "_agent_metrics": "y" * 50}

        result = agent._track_sensorium_budget(cognitive, {})

        assert result == 150
        runtime._emit_event.assert_not_called()

    def test_over_budget_emits_event(self) -> None:
        runtime = _make_runtime_with_sensorium_config(threshold=100)
        agent = _make_agent(runtime=runtime)
        cognitive = {"_temporal_context": "x" * 80, "_agent_metrics": "y" * 50}
        situation = {"_ward_room_activity": "z" * 30}

        result = agent._track_sensorium_budget(cognitive, situation)

        assert result == 160
        runtime._emit_event.assert_called_once()
        event_type, payload = runtime._emit_event.call_args[0]
        assert event_type == EventType.SENSORIUM_BUDGET_EXCEEDED
        assert payload["total_chars"] == 160
        assert payload["threshold"] == 100
        assert payload["callsign"] == "TestAgent"

    def test_disabled_config_skips_event(self) -> None:
        runtime = _make_runtime_with_sensorium_config(enabled=False, threshold=10)
        agent = _make_agent(runtime=runtime)

        result = agent._track_sensorium_budget({"_big": "x" * 1000}, {})

        assert result == 1000
        runtime._emit_event.assert_not_called()

    def test_no_runtime_uses_default_threshold(self) -> None:
        agent = _make_agent(runtime=None)

        result = agent._track_sensorium_budget({"_small": "x" * 100}, {})

        assert result == 100

    def test_non_string_values_skipped(self) -> None:
        runtime = _make_runtime_with_sensorium_config(threshold=6000)
        agent = _make_agent(runtime=runtime)
        cognitive = {"_text": "hello", "_none_val": None, "_list_val": ["a", "b"]}

        result = agent._track_sensorium_budget(cognitive, {})

        assert result == 5

    def test_empty_dicts_returns_zero(self) -> None:
        agent = _make_agent(runtime=None)

        result = agent._track_sensorium_budget({}, {})

        assert result == 0


class TestSensoriumEventType:
    def test_event_type_exists(self) -> None:
        assert hasattr(EventType, "SENSORIUM_BUDGET_EXCEEDED")
        assert EventType.SENSORIUM_BUDGET_EXCEEDED == "sensorium_budget_exceeded"


class TestSensoriumConfig:
    def test_sensorium_config_exists(self) -> None:
        from probos.config import SensoriumConfig

        config = SensoriumConfig()
        assert config.enabled is True
        assert config.token_budget_warning == 6000

    def test_system_config_has_sensorium(self) -> None:
        from probos.config import SystemConfig

        system_config = SystemConfig()
        assert hasattr(system_config, "sensorium")
        assert system_config.sensorium.enabled is True
        assert system_config.sensorium.token_budget_warning == 6000