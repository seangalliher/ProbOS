"""Tests for config loading."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from probos.agents.http_fetch import HttpFetchAgent
from probos.cognitive.cognitive_agent import CognitiveAgent
from probos.cognitive.yeoman import YeomanAgent
from probos.config import DiscoveryConfig, MeshConfig, SystemConfig, load_config
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
