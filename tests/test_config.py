"""Tests for config loading."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from probos.config import DiscoveryConfig, SystemConfig, load_config


class TestConfig:
    def test_default_config(self):
        cfg = SystemConfig()
        assert cfg.system.name == "ProbOS"
        assert cfg.pools.default_pool_size == 3
        assert cfg.mesh.hebbian_decay_rate == 0.995

    def test_load_from_yaml(self):
        config_path = Path(__file__).resolve().parent.parent / "config" / "system.yaml"
        cfg = load_config(config_path)
        assert cfg.system.name == "ProbOS"
        assert cfg.system.version == "0.4.0"
        assert cfg.pools.default_pool_size == 3
        assert cfg.mesh.signal_ttl_seconds == 30.0

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
