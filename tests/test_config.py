"""Tests for config loading."""

import math
from pathlib import Path

import pytest
from pydantic import ValidationError

from probos.agents.http_fetch import HttpFetchAgent
from probos.cognitive.cognitive_agent import CognitiveAgent
from probos.cognitive.yeoman import YeomanAgent
from probos.config import (
    DiscoveryConfig,
    MeshConfig,
    SensoriumConfig,
    SystemConfig,
    load_config,
)
from probos.substrate.agent import BaseAgent
from probos.types import HandlerLatencyClass


def test_handler_latency_class_values_and_agent_inheritance():
    assert [member.value for member in HandlerLatencyClass] == [
        "deterministic",
        "network",
        "cognitive",
    ]
    assert BaseAgent.handler_latency_class == HandlerLatencyClass.DETERMINISTIC
    assert CognitiveAgent.handler_latency_class == HandlerLatencyClass.COGNITIVE
    assert YeomanAgent.handler_latency_class == HandlerLatencyClass.COGNITIVE
    assert HttpFetchAgent.tier == "core"
    assert HttpFetchAgent.handler_latency_class == HandlerLatencyClass.NETWORK


class TestConfig:
    def test_default_config(self):
        cfg = SystemConfig()
        assert cfg.system.name == "ProbOS"
        assert cfg.pools.default_pool_size == 3
        assert cfg.mesh.hebbian_decay_rate == 0.995
        assert cfg.mesh.handler_latency_deterministic_ms == 100.0
        assert cfg.mesh.handler_latency_network_ms == 10_000.0
        assert cfg.mesh.handler_latency_cognitive_ms == 30_000.0

    def test_load_from_yaml(self):
        config_path = Path(__file__).resolve().parent.parent / "config" / "system.yaml"
        cfg = load_config(config_path)
        assert cfg.system.name == "ProbOS"
        assert cfg.system.version == "0.4.0"
        assert cfg.pools.default_pool_size == 3
        assert cfg.mesh.signal_ttl_seconds == 30.0
        assert cfg.mesh.handler_latency_deterministic_ms == 100.0
        assert cfg.mesh.handler_latency_network_ms == 10_000.0
        assert cfg.mesh.handler_latency_cognitive_ms == 30_000.0

    def test_load_missing_file_returns_defaults(self, tmp_path):
        cfg = load_config(tmp_path / "nonexistent.yaml")
        assert cfg.system.name == "ProbOS"

    def test_sensorium_config_alias_precedence_in_both_payload_orders(self):
        for payload in (
            {"warning_chars": 200, "token_budget_warning": 100},
            {"token_budget_warning": 100, "warning_chars": 200},
        ):
            assert SensoriumConfig.model_validate(payload).warning_chars == 200

    def test_sensorium_config_dump_and_schema_use_canonical_name_only(self):
        config = SensoriumConfig(token_budget_warning=321)
        assert config.token_budget_warning == 321
        for dumped in (config.model_dump(), config.model_dump(by_alias=True)):
            assert dumped["warning_chars"] == 321
            assert "token_budget_warning" not in dumped
        for mode in ("validation", "serialization"):
            properties = SensoriumConfig.model_json_schema(mode=mode)["properties"]
            assert "warning_chars" in properties
            assert "token_budget_warning" not in properties

    @pytest.mark.parametrize("invalid_bool", [True, False], ids=["true", "false"])
    @pytest.mark.parametrize(
        "field_name",
        [
            "warning_chars",
            "warning_cooldown_seconds",
            "warning_rearm_ratio",
            "warning_escalation_ratio",
            "top_contributors",
        ],
    )
    def test_sensorium_config_rejects_bool_before_numeric_coercion(
        self, field_name, invalid_bool,
    ):
        with pytest.raises(ValidationError):
            SensoriumConfig.model_validate({field_name: invalid_bool})

    def test_sensorium_config_accepts_ordinary_numeric_strings(self):
        config = SensoriumConfig.model_validate(
            {
                "warning_chars": "2",
                "warning_cooldown_seconds": "3.5",
                "warning_rearm_ratio": "0.5",
                "warning_escalation_ratio": "1.5",
                "top_contributors": "4",
            }
        )
        assert config.warning_chars == 2
        assert config.warning_cooldown_seconds == 3.5
        assert config.warning_rearm_ratio == 0.5
        assert config.warning_escalation_ratio == 1.5
        assert config.top_contributors == 4

    @pytest.mark.parametrize(
        ("field_name", "bad_value"),
        [
            ("warning_chars", 0),
            ("warning_chars", math.nan),
            ("warning_chars", math.inf),
            ("warning_chars", -math.inf),
            ("warning_cooldown_seconds", -1),
            ("warning_cooldown_seconds", math.nan),
            ("warning_rearm_ratio", 0),
            ("warning_rearm_ratio", 1),
            ("warning_rearm_ratio", math.inf),
            ("warning_escalation_ratio", 0.99),
            ("warning_escalation_ratio", -math.inf),
            ("top_contributors", -1),
            ("top_contributors", math.nan),
            ("top_contributors", math.inf),
            ("top_contributors", -math.inf),
        ],
    )
    def test_sensorium_config_rejects_nonfinite_and_out_of_range(
        self, field_name, bad_value,
    ):
        with pytest.raises(ValidationError):
            SensoriumConfig.model_validate({field_name: bad_value})

    def test_sensorium_config_accepts_exact_valid_boundaries(self):
        upper_rearm = math.nextafter(1.0, 0.0)
        config = SensoriumConfig(
            warning_chars=1,
            warning_cooldown_seconds=0,
            warning_rearm_ratio=upper_rearm,
            warning_escalation_ratio=1,
            top_contributors=0,
        )

        assert config.warning_chars == 1
        assert config.warning_cooldown_seconds == 0
        assert config.warning_rearm_ratio == upper_rearm
        assert config.warning_escalation_ratio == 1
        assert config.top_contributors == 0

    def test_sensorium_config_legacy_property_is_read_only(self):
        config = SensoriumConfig(warning_chars=123)
        assert config.token_budget_warning == 123
        with pytest.raises((AttributeError, ValidationError)):
            config.token_budget_warning = 999

    def test_load_config_accepts_legacy_sensorium_yaml(self, tmp_path):
        config_path = tmp_path / "legacy-system.yaml"
        config_path.write_text(
            "sensorium:\n  enabled: true\n  token_budget_warning: 7777\n",
            encoding="utf-8",
        )
        config = load_config(config_path)
        assert config.sensorium.warning_chars == 7777
        assert config.sensorium.token_budget_warning == 7777

    def test_discovery_config_default_off(self):
        # AD-708e: discovery is default-OFF and mounted on the root model.
        assert DiscoveryConfig().enabled is False
        assert SystemConfig().discovery.enabled is False

    def test_discovery_config_service_type_validator_rejects_bad(self):
        # AD-708e: service_type must end with '.local.'.
        with pytest.raises(ValidationError):
            DiscoveryConfig(service_type="_probos._tcp")

    def test_discovery_config_hostname_validator_rejects_bad(self):
        # AD-708e: hostname must be a bare DNS label (no dots/slashes, non-empty).
        with pytest.raises(ValidationError):
            DiscoveryConfig(hostname="probos.local")
        with pytest.raises(ValidationError):
            DiscoveryConfig(hostname="bad/label")
        with pytest.raises(ValidationError):
            DiscoveryConfig(hostname="")

    @pytest.mark.parametrize(
        "field_name",
        [
            "handler_latency_deterministic_ms",
            "handler_latency_network_ms",
            "handler_latency_cognitive_ms",
        ],
    )
    @pytest.mark.parametrize(
        "invalid",
        [True, False, "invalid", None, 0, -1, float("nan"), float("inf"), float("-inf")],
    )
    def test_handler_latency_threshold_rejects_invalid_values(
        self,
        field_name,
        invalid,
    ):
        with pytest.raises(ValidationError, match="handler latency thresholds"):
            MeshConfig(**{field_name: invalid})

    @pytest.mark.parametrize(
        "field_name",
        [
            "handler_latency_deterministic_ms",
            "handler_latency_network_ms",
            "handler_latency_cognitive_ms",
        ],
    )
    def test_handler_latency_threshold_accepts_positive_fraction(self, field_name):
        cfg = MeshConfig(**{field_name: "0.25"})

        assert getattr(cfg, field_name) == 0.25
