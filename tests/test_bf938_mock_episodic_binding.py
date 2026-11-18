"""BF-938 (#1680) R1, amendment A-7: startup's unwrapped AD-607 binding accepts the in-memory MockEpisodicMemory.

Runtime-boot tests install MockEpisodicMemory (21 boots in 10 files), and the binding raised AttributeError in each.
B7 runs B1's startup (``_bound`` in tests/test_bf938_ad607_binding.py) with the mock in place of the real memory.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from probos.cognitive.episodic_mock import MockEpisodicMemory
from probos.cognitive.memory_security import MemorySecurityGate
from probos.config import SystemConfig
from probos.events import EventType
from probos.types import EpisodeStoreOutcome
from tests import test_bf938_ad607_binding as binding


async def test_startup_binds_the_in_memory_mock_and_the_mock_gates_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock = MockEpisodicMemory(relevance_threshold=0.0)
    monkeypatch.setattr(binding, "EpisodicMemory", lambda **_kwargs: mock)  # the name _bound builds its memory through
    config = SystemConfig()
    config.security.memory.enforce_store = True  # armed, and the mock must still store: it gates nothing
    emit = binding._Recorder()
    injected = binding._episode("bf938-injected", 1, text=binding._INJECTED)
    async with binding._bound(tmp_path, monkeypatch, config, emit) as em:
        assert em is mock  # premise: startup ran on the mock, not on a real memory
        assert mock._security_config is config.security.memory
        assert isinstance(mock._security_gate, MemorySecurityGate)
        assert mock._security_event_emitter is emit
        assert await mock.store(injected) is EpisodeStoreOutcome.STORED
        assert [ep.id for ep in await mock.recall(binding._QUERY, k=5)] == [injected.id]
    assert emit.ids(EventType.MEMORY_INJECTION_SUSPECTED) == []
