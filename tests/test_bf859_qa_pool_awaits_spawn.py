"""BF-859 (#1329): the QA pool holds agents, not unawaited coroutines.

``AgentSpawner.spawn`` is a coroutine function. ``_wire_self_improvement`` called
it without ``await`` from a synchronous function, so:

* the spawner body never ran (measured: 0 invocations),
* every ``qa_agents`` entry was a coroutine object, and
* ``if not qa_agents`` was False -- a list of coroutines is truthy -- so the
  in-process fallback that exists for exactly this case was skipped as well.

The function is async now solely so the spawn can be awaited; its only
production caller, ``finalize_startup``, was already async.
"""

from __future__ import annotations

import inspect
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from probos.config import SystemConfig
from probos.startup.finalize import _wire_self_improvement


@pytest.fixture(autouse=True)
def _no_real_evolution_store():
    """Keep these tests to the QA-pool question they are about.

    Wiring with ``self_improvement.enabled`` constructs a REAL ``EvolutionStore``,
    which opens Chroma and loads an embedding model (observed: ``Loading weights
    103/103``). Nothing here stops it, so it would outlive the test and leak into
    whatever runs next -- the ``TestBF662EvolutionTransitions`` test patches it
    for the same reason. These tests only care whether the QA pool holds agents
    or coroutines, and that is decided before the store matters.
    """
    with patch("probos.cognitive.self_improvement.EvolutionStore") as evolution_type:
        evolution_type.return_value.record_lesson = MagicMock(return_value="lesson")
        yield evolution_type


class _RecordingSpawner:
    """Counts real invocations. An unawaited coroutine leaves this at zero."""

    def __init__(self, agent_factory=None) -> None:
        self.calls: list[str] = []
        self._factory = agent_factory or (lambda n: SimpleNamespace(agent_id=f"qa-{n}"))

    async def spawn(self, type_name: str, pool: str = "default", **kwargs):
        self.calls.append(type_name)
        return self._factory(len(self.calls))


class _RaisingSpawner:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def spawn(self, type_name: str, pool: str = "default", **kwargs):
        self.calls.append(type_name)
        raise RuntimeError("no template")


def _runtime(tmp_path: Path, spawner) -> SimpleNamespace:
    return SimpleNamespace(
        data_dir=tmp_path,
        emit_event=None,
        spawner=spawner,
        codebase_index=None,
    )


def _config(tmp_path: Path, **extra) -> SystemConfig:
    return SystemConfig(
        self_improvement={
            "enabled": True,
            "persistence_root_dir": str(tmp_path / "versions"),
            **extra,
        }
    )


class TestTheQAPoolHoldsAgentsNotCoroutines:
    @pytest.mark.asyncio
    async def test_the_spawner_is_actually_invoked(self, tmp_path: Path) -> None:
        """The defect's signature: the coroutine was appended, so the spawner
        body never executed. A call count of 0 is the whole bug."""
        spawner = _RecordingSpawner()

        assert await _wire_self_improvement(
            runtime=_runtime(tmp_path, spawner), config=_config(tmp_path)
        ) is True

        assert spawner.calls == ["system_qa"] * 3, (
            "the spawner was never actually run; an unawaited coroutine was "
            "appended to the QA pool instead"
        )

    @pytest.mark.asyncio
    async def test_no_pool_entry_is_a_coroutine(self, tmp_path: Path) -> None:
        spawner = _RecordingSpawner()
        runtime = _runtime(tmp_path, spawner)

        await _wire_self_improvement(runtime=runtime, config=_config(tmp_path))

        pool = runtime.qa_agent_pool
        # PREMISE: a pool was actually built, or there is nothing to inspect.
        assert pool is not None, "no QAAgentPool was constructed"
        agents = pool.qa_agents
        assert agents, "the pool is empty; this asserts nothing"
        assert not any(inspect.iscoroutine(a) for a in agents), (
            "the QA pool holds unawaited coroutines"
        )

    @pytest.mark.asyncio
    async def test_the_pool_size_is_honoured(self, tmp_path: Path) -> None:
        spawner = _RecordingSpawner()

        await _wire_self_improvement(
            runtime=_runtime(tmp_path, spawner),
            config=_config(tmp_path, qa_pool_size=2),
        )

        assert spawner.calls == ["system_qa", "system_qa"]

    @pytest.mark.asyncio
    async def test_a_failing_spawner_still_reaches_the_fallback(
        self, tmp_path: Path
    ) -> None:
        """The second half of the defect: because a list of coroutines is
        truthy, ``if not qa_agents`` never fired and the in-process fallback --
        which exists for exactly this case -- was unreachable whenever a
        spawner was present."""
        spawner = _RaisingSpawner()
        runtime = _runtime(tmp_path, spawner)

        await _wire_self_improvement(runtime=runtime, config=_config(tmp_path))

        # PREMISE: the spawner really was tried and really did fail.
        assert spawner.calls == ["system_qa"]
        pool = runtime.qa_agent_pool
        assert pool is not None, "the fallback QA agent was never constructed"
        agents = pool.qa_agents
        assert len(agents) == 1
        assert not inspect.iscoroutine(agents[0])

    @pytest.mark.asyncio
    async def test_an_absent_spawner_still_reaches_the_fallback(
        self, tmp_path: Path
    ) -> None:
        runtime = _runtime(tmp_path, None)

        await _wire_self_improvement(runtime=runtime, config=_config(tmp_path))

        pool = runtime.qa_agent_pool
        assert pool is not None
        agents = pool.qa_agents
        assert len(agents) == 1
