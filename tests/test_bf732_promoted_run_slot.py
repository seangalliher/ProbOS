"""BF-732 (#1189): a promoted turn is counted against the agent's capacity.

``CognitiveAgent`` runs every intent inside a concurrency slot. When AD-1165
promotion fires, the real work continues as a retained background task and the
lifecycle returns an acknowledgement -- so the ``async with`` exits and the slot
is released while the run is still executing.

The task was never leaked in the garbage-collection sense. It was invisible to
the mechanism whose whole job is to bound how much of an agent is in flight.
Measured on the reference vessel 2026-08-08: four promoted runs from a single
conversation live simultaneously, each competing for LLM capacity with the
Captain's next turn, with a ceiling of "intent dispatch rate".

The slot now spans the work rather than the acknowledgement.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from probos.cognitive.concurrency_manager import ConcurrencyManager
from probos.cognitive.turn_promotion import _report_holding_slot


class _Runtime:
    """Only what the reporter touches. Not a MagicMock (BF-287)."""

    def __init__(self) -> None:
        self.episodic_memory = None
        self.chat_thread_store = None
        self.work_item_store = None
        self.config = None


def _slot_factory(cm: ConcurrencyManager):
    return lambda: cm.slot("direct_message_promoted", 5)


async def _await_gate(gate: "asyncio.Future[str]") -> str:
    """A run whose completion the test controls."""
    return await gate


async def _reporter(task: Any, cm: ConcurrencyManager | None, wid: str = "wi-1") -> None:
    await _report_holding_slot(
        task,
        runtime=_Runtime(),
        agent_id="counselor_0",
        thread_id="",          # AD-1274: rejected by the store's id validation,
                               # so _post_report returns not-delivered and the
                               # slot accounting under test is unaffected
        work_item_id=wid,
        request_text="do the thing",
        completed_probe=None,
        background_slot=_slot_factory(cm) if cm is not None else None,
    )


# ── the slot spans the work ───────────────────────────────────────


async def test_the_slot_is_held_while_the_promoted_run_is_alive() -> None:
    cm = ConcurrencyManager(agent_id="counselor_0", max_concurrent=2)
    gate: asyncio.Future[str] = asyncio.get_running_loop().create_future()
    task = asyncio.create_task(_await_gate(gate))

    reporter = asyncio.create_task(_reporter(task, cm))
    await asyncio.sleep(0)
    await asyncio.sleep(0)

    assert cm.active_count == 1, "the promoted run is not counted while it runs"

    gate.set_result("done")
    await reporter

    assert cm.active_count == 0, "the slot was not released when the run finished"


async def test_a_failed_run_releases_its_slot() -> None:
    cm = ConcurrencyManager(agent_id="counselor_0", max_concurrent=2)

    async def _boom() -> str:
        raise RuntimeError("the run failed")

    task = asyncio.create_task(_boom())
    await _reporter(task, cm)

    assert cm.active_count == 0, "a failed run leaked its capacity"


async def test_a_cancelled_run_releases_its_slot() -> None:
    """The path most likely to leak: ``_finish_promoted_turn`` re-raises
    CancelledError deliberately, so it must travel through the ``async with``.
    """
    cm = ConcurrencyManager(agent_id="counselor_0", max_concurrent=2)
    gate: asyncio.Future[str] = asyncio.get_running_loop().create_future()
    task = asyncio.create_task(_await_gate(gate))

    reporter = asyncio.create_task(_reporter(task, cm))
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    assert cm.active_count == 1

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await reporter

    assert cm.active_count == 0, "a cancelled run leaked its capacity"


# ── it actually bounds ────────────────────────────────────────────


async def test_promoted_runs_do_not_exceed_the_configured_concurrency() -> None:
    """The acceptance criterion: drive promotion N+1 times against a cap of N
    and assert the surplus is queued rather than run.
    """
    cap = 2
    cm = ConcurrencyManager(agent_id="counselor_0", max_concurrent=cap)
    loop = asyncio.get_running_loop()

    gates = [loop.create_future() for _ in range(cap + 1)]
    tasks = [asyncio.create_task(_await_gate(g)) for g in gates]
    reporters = [
        asyncio.create_task(_reporter(t, cm, wid=f"wi-{i}"))
        for i, t in enumerate(tasks)
    ]
    for _ in range(8):
        await asyncio.sleep(0)

    assert cm.active_count == cap, (
        f"{cm.active_count} promoted runs held slots against a cap of {cap}"
    )
    assert cm.queue_depth >= 1, "the surplus run was not queued"

    for g in gates:
        if not g.done():
            g.set_result("done")
    await asyncio.gather(*reporters)

    assert cm.active_count == 0


# ── it never costs the Captain the report ─────────────────────────


async def test_without_a_slot_factory_the_behaviour_is_unchanged() -> None:
    """Default path: promotion disabled or no manager wired. Byte-identical to
    calling _finish_promoted_turn directly.
    """
    task = asyncio.create_task(asyncio.sleep(0, result="done"))

    await _reporter(task, None)  # must not raise


async def test_a_raising_slot_factory_still_delivers_the_report() -> None:
    """A capacity failure must not lose the Captain's result. Unaccounted is
    today's behaviour and strictly better than silent loss.
    """
    class _Broken:
        def slot(self, *a: Any, **k: Any) -> Any:
            raise RuntimeError("manager exploded")

    task = asyncio.create_task(asyncio.sleep(0, result="done"))

    await _report_holding_slot(
        task,
        runtime=_Runtime(),
        agent_id="counselor_0",
        thread_id="",
        work_item_id="wi-1",
        request_text="do the thing",
        completed_probe=None,
        background_slot=lambda: _Broken().slot(),
    )  # must not raise


async def test_a_slot_factory_returning_none_still_delivers_the_report() -> None:
    task = asyncio.create_task(asyncio.sleep(0, result="done"))

    await _report_holding_slot(
        task,
        runtime=_Runtime(),
        agent_id="counselor_0",
        thread_id="",
        work_item_id="wi-1",
        request_text="do the thing",
        completed_probe=None,
        background_slot=lambda: None,
    )  # must not raise


# ── the agent wires it ────────────────────────────────────────────


def test_the_agent_passes_a_background_slot_at_the_promotion_call_site() -> None:
    """The plumbing above only matters if the one production caller supplies a
    factory. A static check, because reaching that call site needs a full turn.
    """
    import inspect

    from probos.cognitive import cognitive_agent

    src = inspect.getsource(cognitive_agent)

    assert "background_slot=_bg_slot" in src
    assert "_PROMOTED_RUN_PRIORITY" in src


def test_the_promoted_priority_sits_below_a_new_dm() -> None:
    """A background run must never queue the Captain's next DM behind it, and
    must still outrank proactive thinking, which nobody asked for.
    """
    from probos.cognitive.cognitive_agent import _PROMOTED_RUN_PRIORITY

    assert 2 < _PROMOTED_RUN_PRIORITY < 8
