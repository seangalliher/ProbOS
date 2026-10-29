"""BF-941 (#1324 slice 4d) M2: BF-034's cold-start detector asks the boot camp's new-crew predicate.

The detector tested the memory object's truthiness (true whenever a memory exists) and every
trust record against the generic prior (false whenever AD-640 gives a bridge or chief role its
own), either of which kept its branch from running (#1324 register 4b-R10). It now asks
``probos.startup.crew_start.is_new_crew_start``, which the AD-638 boot camp also asks. Its
Fresh Start thread, posted at Phase 5 where the Ward Room does not exist yet, moved to
finalization. Phase 5 runs here as ``runtime.start()`` runs it (the AD-1326 harness), with
AD-640 role priors in a real ``TrustNetwork``.
"""

from __future__ import annotations

import ast
import asyncio
import importlib
import inspect
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from probos.cognitive.cognitive_agent import CognitiveAgent
from probos.cognitive.procedure_store import ProcedureStore
from probos.config import SystemConfig
from probos.consensus.trust import TrustNetwork
from probos.dream_adapter import DreamAdapter
from probos.runtime import ProbOSRuntime
from probos.startup import dreaming
from probos.startup.dreaming import init_dreaming

_SRC = Path(__file__).resolve().parents[1] / "src" / "probos"
_TITLE = "Fresh Start — New Crew"


def _crew_start() -> ModuleType:
    """Imported per case, so that each case fails by name before the module exists."""
    return importlib.import_module("probos.startup.crew_start")


class _Stats:
    """The one read the predicate makes of an episodic memory."""

    def __init__(self, total: int = 0, error: Exception | None = None) -> None:
        self.total = total
        self.error = error

    async def get_stats(self) -> dict[str, int]:
        if self.error is not None:
            raise self.error
        return {"total": self.total}


def _memory(total: int) -> MagicMock:
    """A memory object as Phase 5 sees one: truthy, and answering ``get_stats``."""
    memory = MagicMock()
    memory.get_stats = AsyncMock(return_value={"total": total})
    return memory


def _trust_with_role_priors() -> TrustNetwork:
    """AD-640's tiers at their defaults: a bridge and a chief record above the generic prior."""
    trust = TrustNetwork()
    trust.create_with_prior("bridge-0", 4.5, 1.0)
    trust.create_with_prior("chief-0", 3.0, 1.0)
    trust.create_with_prior("crew-0", 2.0, 2.0)
    return trust


async def _idle() -> None:
    await asyncio.sleep(3600)


async def _process(_text: str, **_kwargs: Any) -> None:
    return None


@asynccontextmanager
async def _phase_five(tmp_path: Path, *, lifecycle: str, memory: Any) -> AsyncIterator[bool]:
    """``init_dreaming`` as ``runtime.start()`` calls it; its background tasks are stopped afterwards."""
    store = ProcedureStore(data_dir=tmp_path / "procedures")
    await store.start()
    result = None
    try:
        result, cold_start = await init_dreaming(
            config=SystemConfig(),
            trust_network=_trust_with_role_priors(),
            hebbian_router=MagicMock(),
            episodic_memory=memory,
            pool_scaler=None,
            knowledge_store=None,
            registry=None,
            on_gap_predictions_fn=lambda _predictions: None,
            on_contradictions_fn=lambda _contradictions: None,
            on_post_dream_fn=lambda _report: None,
            on_pre_dream_fn=lambda: None,
            on_post_micro_dream_fn=lambda _report: None,
            process_natural_language_fn=_process,
            periodic_flush_loop_fn=_idle,
            refresh_emergent_detector_roster_fn=lambda: None,
            emit_event_fn=lambda _event_type, _payload: None,
            llm_client=MagicMock(),
            procedure_store=store,
            lifecycle_state=lifecycle,
        )
        yield cold_start
    finally:
        if result is not None:
            await result.dream_scheduler.stop()
            await result.task_scheduler.stop()
            result.flush_task.cancel()
            with suppress(asyncio.CancelledError):
                await result.flush_task
        await store.stop()


def _runtime(lifecycle: str) -> ProbOSRuntime:
    """A runtime holding only what the fresh-start window reads; nothing is booted."""
    runtime = ProbOSRuntime.__new__(ProbOSRuntime)
    runtime.config = SystemConfig()
    runtime._cold_start = False
    runtime._cold_start_until = 0.0
    runtime._lifecycle_state = lifecycle
    return runtime


def _adapter(runtime: ProbOSRuntime) -> DreamAdapter:
    """A dream adapter wired as finalization wires it."""
    adapter = DreamAdapter(
        dream_scheduler=None,
        emergent_detector=None,
        episodic_memory=None,
        knowledge_store=None,
        hebbian_router=MagicMock(),
        trust_network=MagicMock(),
        event_emitter=lambda *_args, **_kwargs: None,
        self_mod_pipeline=None,
        bridge_alerts=None,
        ward_room=None,
        registry=MagicMock(),
        event_log=None,
        config=SystemConfig(),
        pools={},
        end_cold_start_fn=runtime.end_cold_start,
    )
    adapter._cold_start = runtime._cold_start  # finalize.py copies the runtime's flag the same way
    return adapter


def _calls_by_enclosing_function(name: str) -> set[str]:
    """``<path>::<innermost enclosing function>`` for every call of ``name`` under ``src/probos``."""
    found: set[str] = set()
    for path in sorted(_SRC.rglob("*.py")):
        text = path.read_text(encoding="utf-8", errors="replace")
        if name not in text:
            continue
        tree = ast.parse(text)
        parents = {child: parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)}
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if (getattr(node.func, "id", None) or getattr(node.func, "attr", None)) != name:
                continue
            owner = parents.get(node)
            while owner is not None and not isinstance(owner, (ast.FunctionDef, ast.AsyncFunctionDef)):
                owner = parents.get(owner)
            found.add(f"{path.relative_to(_SRC).as_posix()}::{owner.name if owner else '<module>'}")
    return found


# --- the predicate -------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("lifecycle", "memory", "expected"),
    [
        ("first_boot", _Stats(0), True),
        ("reset", _Stats(0), True),
        ("stasis_recovery", _Stats(0), False),
        ("restart", _Stats(0), False),
        ("", _Stats(0), False),
        ("first_boot", _Stats(4), False),
        ("first_boot", None, False),
        ("first_boot", _Stats(error=OSError("collection unavailable")), False),
    ],
    ids=["first-boot", "reset", "stasis-recovery", "restart", "no-lifecycle", "episodes-kept", "no-memory", "count-raises"],
)
async def test_a_new_crew_is_no_session_record_and_no_episodes(lifecycle: str, memory: Any, expected: bool) -> None:
    assert await _crew_start().is_new_crew_start(lifecycle, memory) is expected


def test_the_detector_and_the_boot_camp_ask_the_one_predicate() -> None:
    assert _calls_by_enclosing_function("is_new_crew_start") == {
        "startup/dreaming.py::init_dreaming",
        "startup/finalize.py::_is_new_crew_start",
    }


# --- the detector, through Phase 5 -----------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("lifecycle", "total", "cold"),
    [("first_boot", 0, True), ("stasis_recovery", 0, False), ("first_boot", 3, False), ("restart", 0, False)],
    ids=["new-crew", "stasis-recovery", "episodes-kept", "restart"],
)
async def test_the_detector_asks_the_new_crew_predicate(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, lifecycle: str, total: int, cold: bool
) -> None:
    caplog.set_level(logging.INFO, logger="probos.startup.dreaming")
    memory = _memory(total)
    assert memory, "premise: a memory object is truthy, which BF-034's `not episodic_memory` read as warm"
    priors = _trust_with_role_priors().raw_scores().values()
    generic = SystemConfig().consensus.trust_prior_alpha
    assert any(abs(r["alpha"] - generic) >= 0.01 for r in priors), "premise: AD-640 role priors differ from the generic prior"

    async with _phase_five(tmp_path, lifecycle=lifecycle, memory=memory) as cold_start:
        pass

    assert cold_start is cold
    messages = [r.getMessage() for r in caplog.records if r.name == "probos.startup.dreaming"]
    assert sum(m.startswith("BF-034: Cold start detected") for m in messages) == (1 if cold else 0)
    assert sum(m.startswith("BF-178: Stasis recovery") for m in messages) == (1 if lifecycle == "stasis_recovery" else 0)
    assert memory.get_stats.await_count == (1 if lifecycle in ("first_boot", "reset") else 0)


def test_the_fresh_start_thread_left_phase_five() -> None:
    parameters = inspect.signature(init_dreaming).parameters

    assert "ward_room" not in parameters
    assert parameters["lifecycle_state"].default == ""
    assert "create_thread" not in inspect.getsource(dreaming)


# --- the announcement ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_fresh_start_thread_goes_to_all_hands() -> None:
    ward_room = AsyncMock()
    ward_room.get_channel_by_name = AsyncMock(return_value=SimpleNamespace(id="ch-1", name="All Hands"))
    ward_room.create_thread = AsyncMock()

    assert await _crew_start().announce_fresh_start(ward_room) is True

    ward_room.get_channel_by_name.assert_awaited_once_with("All Hands")
    kwargs = ward_room.create_thread.await_args.kwargs
    assert kwargs["channel_id"] == "ch-1"
    assert kwargs["title"] == _TITLE
    assert kwargs["author_id"] == "system"
    assert kwargs["thread_mode"] == "announce"
    assert kwargs["max_responders"] == 0
    body = kwargs["body"]
    assert "starting fresh" in body
    assert "0.5" not in body
    assert "has been reset" not in body
    assert "has been cleared" not in body


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["raises", "no-all-hands"])
async def test_a_ward_room_failure_does_not_stop_startup(failure: str) -> None:
    ward_room = AsyncMock()
    if failure == "raises":
        ward_room.get_channel_by_name = AsyncMock(side_effect=RuntimeError("ward room down"))
    else:
        ward_room.get_channel_by_name = AsyncMock(return_value=None)
    ward_room.create_thread = AsyncMock()

    assert await _crew_start().announce_fresh_start(ward_room) is False
    ward_room.create_thread.assert_not_awaited()


# --- the seam: detector -> runtime -> agent note -> first dream ------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("lifecycle", "total", "fresh"),
    [("first_boot", 0, True), ("stasis_recovery", 0, False), ("first_boot", 2, False)],
    ids=["new-crew", "stasis-recovery", "episodes-kept"],
)
async def test_a_new_crew_reaches_the_agent_note_until_the_first_dream(
    tmp_path: Path, lifecycle: str, total: int, fresh: bool
) -> None:
    async with _phase_five(tmp_path, lifecycle=lifecycle, memory=_memory(total)) as cold_start:
        pass
    runtime = _runtime(lifecycle)
    runtime.adopt_new_crew_start(cold_start)  # what runtime.start() does with Phase 5's answer
    agent = SimpleNamespace(_runtime=runtime)

    assert ("fresh start" in CognitiveAgent._sensorium_cold_start_note(agent, {}).lower()) is fresh

    _adapter(runtime).on_post_dream(None)

    assert runtime.is_cold_start is False
    assert CognitiveAgent._sensorium_cold_start_note(agent, {}) == ""
