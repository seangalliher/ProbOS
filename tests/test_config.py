"""Tests for config loading."""

from pathlib import Path

import pytest

from probos.config import SystemConfig, load_config


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
