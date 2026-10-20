"""AD-1343 S1 (#1595), amendment A2: a crew child of a stopped agent is not started, on a real crew executor (X6).

``tests/test_ad1343_agent_stop_crew.py`` proves the eligibility answer over the resolver alone. A chain can be dead with every link
correct: a resolver that says "stopped" while the executor that asks it never reads the answer, or reads it after the child was
admitted. X6 crosses the whole chain on real parts, as ``tests/test_ad859_crew_executor.py`` builds the lost-eligibility case:

the Captain's order (a real ``AgentStopService`` over ``agent_stops.db``) -> the real ``CrewAssignmentResolver`` given that service
-> the real ``CrewTaskExecutor`` over a real ``WorkItemStore`` -> a real ``WorkItemAgenticExecutor`` whose model client counts its
calls. The child is assigned to the stopped agent, so the run ends in the existing ``CrewWorkerUnavailable`` outcome before anything
is changed: the child is untouched, no model call is made and nothing is persisted as failed.

The amendment's table calls this test X5; its file label is X6, because ``tests/test_ad1343_stop_crossing.py`` already holds X1 to X4.

Every store lives in ``tmp_path``; the live data directory is never read. Nothing here sleeps or orders anything by wall-clock time:
the service's clock is injected and the run is bounded with ``asyncio.wait_for``.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest

from probos.cognitive.agentic_dispatch import WorkItemAgenticExecutor
from probos.cognitive.crew_executor import CrewTaskExecutor, CrewWorkerUnavailable, is_untouched_crew_child
from probos.workforce import WorkItemStore
from tests.test_ad1343_agent_stop import REASON, _Clock, _service
from tests.test_ad1343_agent_stop_crew import (
    _BOUND,
    ASSIGNMENT_LOGGER,
    STOP_LOGGER,
    _CountingLLM,
    _loud,
    _native_workers,
    _runtime,
)


def _ignore_event(*_args: Any, **_kwargs: Any) -> None:
    """The store's event sink: these tests read the store, not its events."""


@contextlib.asynccontextmanager
async def _work_items(tmp_path: Path) -> AsyncIterator[WorkItemStore]:
    """A real work-item store on ``tmp_path``, opened as tests/test_ad859_crew_executor.py opens one."""
    store = WorkItemStore(db_path=str(tmp_path / "crew.db"), emit_event=_ignore_event, tick_interval=1000)
    await store.start()
    try:
        yield store
    finally:
        await store.stop()


# X6
async def test_a_crew_child_of_a_stopped_agent_is_not_started(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    llm = _CountingLLM()
    async with (
        _service(tmp_path / "stops", clock=_Clock()) as service,
        _native_workers(tmp_path, service) as workers,
        _work_items(tmp_path) as store,
    ):
        parent = await store.create_work_item(title="parent", work_type="work_order")
        child = await store.create_work_item(
            title="analysis", description="please do analysis", work_type="task", parent_id=parent.id,
            assigned_to="builder-1", depends_on=[], metadata={"spec_id": "spec-a"},
        )
        initial_status = store.work_type_registry.get_initial_status(child.work_type)
        executor = CrewTaskExecutor(
            work_item_store=store, agent_registry=workers.registry, eligibility_resolver=workers.resolver,
            agentic_executor=WorkItemAgenticExecutor(llm_client=llm), runtime=_runtime(service),
        )

        # Golden: with no order in force the eligibility premise of tests/test_ad859_crew_executor.py holds (the resolver the
        # executor asks answers with an identity for the child's agent), the child is untouched, and neither the stop module
        # nor the resolver logs at INFO or above.
        with caplog.at_level(logging.INFO):
            assert workers.resolver.check_eligibility("builder-1").identity is not None
        assert _loud(caplog, STOP_LOGGER, ASSIGNMENT_LOGGER) == []
        assert is_untouched_crew_child(child, initial_status=initial_status)
        assert parent.status != "failed" and child.status != "failed"

        # A3 (review item a): the golden must RUN the executor, or "CrewTaskExecutor.run always raises CrewWorkerUnavailable"
        # passes. A second parent whose child is also builder-1's, run with no order in force, is started: it reaches the model
        # (which refuses every call, so the run then ends however the executor ends that) and is never refused as unavailable.
        golden_parent = await store.create_work_item(title="golden parent", work_type="work_order")
        await store.create_work_item(
            title="analysis", description="please do analysis", work_type="task", parent_id=golden_parent.id,
            assigned_to="builder-1", depends_on=[], metadata={"spec_id": "spec-a"},
        )
        try:
            await asyncio.wait_for(executor.run(golden_parent.id), timeout=_BOUND)
        except CrewWorkerUnavailable:
            raise AssertionError("AD-1343 X6 golden: an unstopped agent's child was refused as unavailable") from None
        except Exception:  # noqa: BLE001 -- the counting model refuses to answer; the golden claims only that the run started
            pass
        assert llm.calls, "AD-1343 X6 golden: the unstopped child never reached the model"
        llm.calls.clear()

        record = (await service.issue_stop("builder-1", reason=REASON)).record
        assert workers.resolver.check_eligibility("builder-1").identity is None  # the order is in the resolver's answer

        with pytest.raises(CrewWorkerUnavailable, match="^crew_worker_unavailable$"):
            await asyncio.wait_for(executor.run(parent.id), timeout=_BOUND)

        # the child was not started: untouched, its metadata unchanged, nothing persisted as failed, and no model call
        current = await store.get_work_item(child.id)
        assert current is not None
        assert is_untouched_crew_child(current, initial_status=initial_status)
        assert current.metadata == child.metadata
        assert [(item.id, item.status) for item in await store.list_work_items(parent_id=parent.id, limit=10)] == [  # A3: per parent
            (child.id, initial_status),
        ]
        parent_now = await store.get_work_item(parent.id)
        assert parent_now is not None and parent_now.status == parent.status
        assert llm.calls == []
        assert service.refused_counts(record.stop_id) == {}  # eligibility is a question, not a refusal: nothing was counted
