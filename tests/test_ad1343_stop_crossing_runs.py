"""AD-1343 S1 (#1595), amendment A2: a delegation to a stopped crew member crosses a real, booted ship (X5).

``tests/test_ad1343_agent_stop_runs.py`` proves the delegation refusal over fakes: a callsign registry, a stub runtime, a spy broker.
A chain can be dead with every link correct: a gate never handed to the registry the run entry reads, a tool registered but never
asked, an answer shaped for a stub and not for the ship's own registry. This test boots a real ``ProbOSRuntime`` on ``tmp_path`` (as
``tests/test_ad1343_stop_crossing.py`` does), registers a real ``DelegateTaskTool`` on the ship's real tool registry and crosses the
whole chain: a colleague delegates to a crew member through ``check_and_invoke``, the Captain's order is issued through the ship's
own ``agent_stops``, and the same delegation is answered as not started while the nested run's model client is never asked.

The ship lives in ``tmp_path`` (the live data directory is never read). Nothing here sleeps or waits on a timer; the delegation is
bounded by ``asyncio.wait_for``.
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any

import pytest

from probos.agent_stop import AgentStopService
from probos.cognitive.llm_client import MockLLMClient
from probos.crew_utils import is_crew_agent
from probos.runtime import ProbOSRuntime
from probos.tools.delegate_task_tool import DelegateTaskTool
from tests.test_ad1343_agent_stop import PRIVATE_FRAGMENT, REASON
from tests.test_ad1343_stop_crossing import _BUS_TIMEOUT, _crew, _ship

TASK = "AD-1343 crossing: report your status."
WATCHED_LOGGERS = ("probos.agent_stop", "probos.tools.delegate_task_tool")  # the stop module and the tool this amendment changed


class _CountingMockLLM(MockLLMClient):
    """The ship's mock LLM client, counting every request it is asked to complete."""

    def __init__(self) -> None:
        super().__init__()
        self.requests: list[str] = []

    async def complete(self, request: Any, **kwargs: Any) -> Any:
        self.requests.append(request.id)
        return await super().complete(request, **kwargs)


def _delegation_target(rt: ProbOSRuntime, colleague_id: str) -> tuple[Any, str]:
    """A crew agent other than ``colleague_id`` that the delegation tool resolves by callsign to that very agent, with the callsign."""
    for agent in rt.registry.all():
        if agent.id == colleague_id or not is_crew_agent(agent, rt.ontology):
            continue
        callsign = rt.callsign_registry.get_callsign(agent.agent_type)
        resolved = rt.callsign_registry.resolve(callsign) if callsign else None
        if resolved is not None and resolved["agent_id"] == agent.id and agent in rt.registry.get_by_pool(agent.agent_type):
            return agent, callsign
    raise AssertionError("AD-1343 X5: no crew agent on the booted ship can be delegated to by callsign")


# X5
async def test_a_delegation_to_a_stopped_crew_member_starts_nothing_on_a_real_ship(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    async with _ship(tmp_path / "data") as rt:
        colleague = _crew(rt)
        target, callsign = _delegation_target(rt, colleague.id)
        # premise: the wiring the chain rests on exists in a default boot, and the target is an agent the stop guards
        assert isinstance(rt.agent_stops, AgentStopService)
        assert rt.tool_registry.stop_gate is rt.agent_stops and rt.agent_stops.stop_for(target.id) is None
        assert target.id != colleague.id and rt.registry.get(target.id) is target
        llm = _CountingMockLLM()
        if rt.tool_registry.get("delegate_task") is None:
            rt.tool_registry.register(DelegateTaskTool(runtime=rt, llm_client=llm, max_depth=1, max_iterations=2, tier="standard"))
        assert rt.tool_registry.get("delegate_task") is not None

        async def _delegate() -> Any:
            return await asyncio.wait_for(
                rt.tool_registry.check_and_invoke(
                    colleague.id, "delegate_task", {"task": TASK, "to": callsign}, context={"thread_id": "ad1343-crossing-runs"},
                ),
                timeout=_BUS_TIMEOUT,
            )

        # golden: before any order the delegation runs the nested agent, so the counting client is on the production path
        with caplog.at_level(logging.INFO):
            caplog.clear()
            before = await _delegate()
            golden_log = [
                (r.name, r.levelno, r.getMessage()) for r in caplog.records if r.levelno >= logging.INFO and r.name in WATCHED_LOGGERS
            ]
        assert before.error is None and before.output["delegated"] is True
        assert len(llm.requests) >= 1  # the nested run really reached the counting client
        assert golden_log == []  # the gate adds no INFO or higher line for an agent that is not stopped
        reached_before_order = len(llm.requests)

        # the Captain's order, through the ship's own service
        order = await rt.agent_stops.issue_stop(target.id, reason=REASON)
        assert rt.agent_stops.stop_for(target.id) is order.record

        refused = await _delegate()
        assert refused.error is None
        assert refused.output == {"delegated": False, "reason": "agent_stopped", "stop": order.record.sender_detail()}
        assert refused.output["stop"]["stop_id"] == order.record.stop_id
        assert refused.evidence.status == "not_started"
        assert len(llm.requests) == reached_before_order  # the nested run never reached its model client: nothing was started
        assert PRIVATE_FRAGMENT not in json.dumps(refused.output)  # the order, never the Captain's reason
        assert rt.agent_stops.refused_counts(order.record.stop_id).get("delegation") == 1  # counted at the delegation seam
