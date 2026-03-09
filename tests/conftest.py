"""Shared test fixtures."""

import pytest

from probos.substrate.registry import AgentRegistry
from probos.substrate.spawner import AgentSpawner
from probos.config import PoolConfig


def pytest_collection_modifyitems(config, items):
    """Skip live_llm tests unless explicitly requested with -m live_llm."""
    marker_expr = config.getoption("-m", default="")
    if marker_expr and "live_llm" in marker_expr:
        return
    skip_live = pytest.mark.skip(reason="live_llm tests only run with: pytest -m live_llm")
    for item in items:
        if "live_llm" in item.keywords:
            item.add_marker(skip_live)


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
