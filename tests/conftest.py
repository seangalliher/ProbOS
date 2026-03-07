"""Shared test fixtures."""

import pytest

from probos.substrate.registry import AgentRegistry
from probos.substrate.spawner import AgentSpawner
from probos.config import PoolConfig


@pytest.fixture
def registry():
    return AgentRegistry()


@pytest.fixture
def spawner(registry):
    return AgentSpawner(registry)


@pytest.fixture
def pool_config():
    return PoolConfig(
        default_pool_size=3,
        max_pool_size=7,
        min_pool_size=2,
        spawn_cooldown_ms=100,
        health_check_interval_seconds=1.0,
    )
