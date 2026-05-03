"""AD-641e: LearnedShortcut shared abstraction tests."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from probos.cognitive.learned_shortcuts import (
    LearnedShortcutBackend,
    LearnedShortcutRegistry,
    WorkflowCacheBackend,
)
from probos.cognitive.workflow_cache import WorkflowCache
from probos.config import LearnedShortcutsConfig
from probos.events import EventType


# --------------------------------------------------------------------------- #
# Stubs
# --------------------------------------------------------------------------- #


class _StubWorkflowCache:
    """Minimal duck-typed stub matching the WorkflowCache surface used by the adapter."""

    def __init__(self, *, size: int = 0, lookups: dict[str, Any] | None = None) -> None:
        self._size = size
        self._lookups = lookups or {}
        self.stored: dict[str, Any] = {}

    @property
    def size(self) -> int:
        return self._size

    def lookup(self, user_input: str) -> Any | None:
        return self._lookups.get(user_input)

    def store(self, user_input: str, dag: Any) -> None:
        self.stored[user_input] = dag


class _MinimalProtocolStub:
    """Hand-rolled stub with the 5 Protocol members; no inheritance from adapter."""

    def __init__(self, kind: str = "minimal", size: int = 0) -> None:
        self._kind = kind
        self._size = size
        self._data: dict[str, Any] = {}

    @property
    def kind(self) -> str:
        return self._kind

    @property
    def size(self) -> int:
        return self._size

    def lookup(self, key: str) -> Any | None:
        return self._data.get(key)

    def store(self, key: str, value: Any) -> None:
        self._data[key] = value

    def evict(self, key: str) -> bool:
        return self._data.pop(key, None) is not None


# --------------------------------------------------------------------------- #
# Tests
# --------------------------------------------------------------------------- #


def test_event_type_learned_shortcut_registered_exists() -> None:
    assert EventType.LEARNED_SHORTCUT_REGISTERED.value == "learned_shortcut_registered"


def test_event_type_learned_shortcut_hit_exists() -> None:
    assert EventType.LEARNED_SHORTCUT_HIT.value == "learned_shortcut_hit"


def test_learned_shortcuts_config_defaults() -> None:
    cfg = LearnedShortcutsConfig()
    assert cfg.enabled is True
    assert cfg.register_workflow_cache is True


def test_protocol_runtime_checkable_recognizes_workflow_cache_backend() -> None:
    backend = WorkflowCacheBackend(workflow_cache=_StubWorkflowCache())
    assert isinstance(backend, LearnedShortcutBackend)


def test_protocol_runtime_checkable_recognizes_minimal_stub() -> None:
    stub = _MinimalProtocolStub()
    assert isinstance(stub, LearnedShortcutBackend)


def test_workflow_cache_backend_kind_and_size() -> None:
    backend = WorkflowCacheBackend(workflow_cache=_StubWorkflowCache(size=3))
    assert backend.kind == "workflow_cache"
    assert backend.size == 3


def test_workflow_cache_backend_lookup_delegates() -> None:
    sentinel = object()
    cache = _StubWorkflowCache(lookups={"hello": sentinel})
    backend = WorkflowCacheBackend(workflow_cache=cache)
    assert backend.lookup("hello") is sentinel
    assert backend.lookup("missing") is None
    # Empty key short-circuits.
    assert backend.lookup("") is None


def test_workflow_cache_backend_evict_returns_false_in_v1() -> None:
    backend = WorkflowCacheBackend(workflow_cache=_StubWorkflowCache())
    assert backend.evict("anything") is False


def test_registry_register_emits_event_with_kind_and_size() -> None:
    emit = MagicMock()
    registry = LearnedShortcutRegistry(emit_event=emit)
    backend = WorkflowCacheBackend(workflow_cache=_StubWorkflowCache(size=5))

    assert registry.register(backend) is True
    emit.assert_called_once()
    args, _ = emit.call_args
    assert args[0] == EventType.LEARNED_SHORTCUT_REGISTERED
    assert args[1] == {"kind": "workflow_cache", "size": 5}
    assert registry.kinds == ["workflow_cache"]


def test_registry_register_idempotent_for_same_kind() -> None:
    registry = LearnedShortcutRegistry()
    b1 = WorkflowCacheBackend(workflow_cache=_StubWorkflowCache())
    b2 = WorkflowCacheBackend(workflow_cache=_StubWorkflowCache())
    assert registry.register(b1) is True
    assert registry.register(b2) is False
    assert registry.kinds == ["workflow_cache"]


def test_registry_lookup_first_returns_first_hit_and_emits_hit() -> None:
    emit = MagicMock()
    registry = LearnedShortcutRegistry(emit_event=emit)
    sentinel_a = object()
    sentinel_b = object()
    a = _MinimalProtocolStub(kind="alpha")
    a.store("key", sentinel_a)
    b = _MinimalProtocolStub(kind="beta")
    b.store("key", sentinel_b)
    registry.register(a)
    registry.register(b)
    emit.reset_mock()

    result = registry.lookup_first("key")

    assert result == ("alpha", sentinel_a)
    emit.assert_called_once()
    args, _ = emit.call_args
    assert args[0] == EventType.LEARNED_SHORTCUT_HIT
    assert args[1] == {"kind": "alpha", "key": "key"}


def test_registry_lookup_first_returns_none_when_no_backend_has_key() -> None:
    registry = LearnedShortcutRegistry()
    registry.register(_MinimalProtocolStub(kind="alpha"))
    registry.register(_MinimalProtocolStub(kind="beta"))
    assert registry.lookup_first("missing") is None
    assert registry.lookup_first("") is None


def test_registry_total_size_sums_backends() -> None:
    registry = LearnedShortcutRegistry()
    registry.register(_MinimalProtocolStub(kind="alpha", size=3))
    registry.register(_MinimalProtocolStub(kind="beta", size=4))
    assert registry.total_size == 7


def test_existing_workflow_cache_public_api_unchanged() -> None:
    """Open/Closed regression guard: AD-641e must not modify WorkflowCache."""
    cache = WorkflowCache()
    # Methods.
    assert callable(getattr(cache, "store", None))
    assert callable(getattr(cache, "lookup", None))
    assert callable(getattr(cache, "lookup_fuzzy", None))
    # `size` is a @property returning int.
    assert isinstance(cache.size, int)
    assert not callable(cache.size)
