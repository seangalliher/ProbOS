"""BF-291: defensive MemoryConfig field access in shutdown.py.

Regression tests for the ``_memory_field`` helper that replaces three
fragile ``getattr(...).field_name`` reads in
``src/probos/startup/shutdown.py``. The bug surfaces when a long-running
process started with an older ``MemoryConfig`` schema (lacking
``shutdown_consolidation_timeout_s`` or ``shutdown_drain_timeout_s``)
shuts down with the newer ``shutdown.py`` code on disk: direct attribute
access on a Pydantic v2 model raises ``AttributeError``, the AD-825
drain phase never runs, and AD-820's ``shutdown_status.json`` integrity
marker is never written.
"""
from __future__ import annotations

import pytest
from pydantic import BaseModel

from probos.startup.shutdown import _memory_field


class _MemoryConfigWithoutFields(BaseModel):
    """Pydantic v2 model lacking the two BF-291 fields."""

    some_other_field: int = 0


class _MemoryConfigWithFields(BaseModel):
    """Pydantic v2 model with the BF-291 fields present."""

    shutdown_consolidation_timeout_s: float = 30.0
    shutdown_drain_timeout_s: float = 30.0


class _StubConfig:
    def __init__(self, memory: object | None) -> None:
        self.memory = memory


class _StubRuntime:
    def __init__(self, config: object | None) -> None:
        self.config = config


def test_memory_field_returns_default_when_field_absent() -> None:
    """Core regression: missing field on Pydantic v2 model returns default."""
    runtime = _StubRuntime(_StubConfig(_MemoryConfigWithoutFields()))
    result = _memory_field(runtime, "shutdown_consolidation_timeout_s", 30.0)
    assert result == 30.0


def test_memory_field_returns_value_when_field_present() -> None:
    runtime = _StubRuntime(
        _StubConfig(
            _MemoryConfigWithFields(shutdown_consolidation_timeout_s=45.0)
        )
    )
    result = _memory_field(runtime, "shutdown_consolidation_timeout_s", 30.0)
    assert result == 45.0


def test_memory_field_returns_default_when_config_is_none() -> None:
    runtime = _StubRuntime(None)
    result = _memory_field(runtime, "shutdown_drain_timeout_s", 30.0)
    assert result == 30.0


def test_memory_field_returns_default_when_memory_is_none() -> None:
    runtime = _StubRuntime(_StubConfig(None))
    result = _memory_field(runtime, "shutdown_drain_timeout_s", 30.0)
    assert result == 30.0


def test_memory_field_returns_default_when_runtime_lacks_config_attr() -> None:
    """Defensive: even a runtime with no ``config`` attribute at all."""

    class _Bare:
        pass

    result = _memory_field(_Bare(), "shutdown_drain_timeout_s", 30.0)
    assert result == 30.0
