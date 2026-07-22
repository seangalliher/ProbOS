"""AD-868 compatibility coverage after AD-1128 unified CrewSession ingress."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest

from probos.cognitive.crew_orchestrator import CrewOrchestrator
from probos.config import SystemConfig
from probos.proactive import ProactiveCognitiveLoop
from probos.runtime import ProbOSRuntime
from probos.substrate.agent import BaseAgent
from probos.ward_room_router import WardRoomRouter


@dataclass(frozen=True)
class _Principal:
    agent_id: str


class _CrewSessionServiceSpy:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.error: BaseException | None = None

    def agent_principal(self, agent_id: str) -> _Principal:
        return _Principal(agent_id)

    async def open_or_resume(self, **kwargs: Any) -> Any:
        self.calls.append(dict(kwargs))
        if self.error is not None:
            raise self.error
        return SimpleNamespace(
            disposition="created",
            parent_id="parent-1",
            thread_id="thread-1",
            state="discussing",
            facilitator_id=kwargs["principal"].agent_id,
            owner_ids=(kwargs["principal"].agent_id,),
            duplicate_resume_count=0,
            scheduled=True,
        )


def _config() -> SystemConfig:
    config = SystemConfig()
    config.agentic_dispatch.orchestrator_enabled = True
    return config


def _orchestrator(service: Any | None) -> CrewOrchestrator:
    return CrewOrchestrator(
        assignment_resolver=object(),
        delegator=object(),
        crew_executor=object(),
        verifier=object(),
        synthesizer=object(),
        work_item_store=object(),
        runtime=SimpleNamespace(),
        config=_config(),
        crew_session_service=service,
    )


async def test_originate_crew_task_delegates_to_unified_service() -> None:
    service = _CrewSessionServiceSpy()
    orchestrator = _orchestrator(service)

    parent_id = await orchestrator.originate_crew_task(
        origin_agent_id="lieutenant-1",
        goal="Inspect the anomaly",
    )

    assert parent_id == "parent-1"
    assert service.calls == [{
        "principal": _Principal("lieutenant-1"),
        "goal": "Inspect the anomaly",
        "success_criteria": [
            "Complete the stated goal with verifiable evidence.",
        ],
        "expected_deliverable": "A verified result for the stated goal.",
    }]


async def test_originate_crew_task_rejects_old_work_type_without_service_call() -> None:
    service = _CrewSessionServiceSpy()
    orchestrator = _orchestrator(service)

    parent_id = await orchestrator.originate_crew_task(
        origin_agent_id="lieutenant-1",
        goal="Inspect",
        work_type="incident",
    )

    assert parent_id is None
    assert service.calls == []


async def test_originate_crew_task_honest_degrades_service_contract_error() -> None:
    service = _CrewSessionServiceSpy()
    service.error = ValueError("crew_session_agent_rank_insufficient")
    orchestrator = _orchestrator(service)

    parent_id = await orchestrator.originate_crew_task(
        origin_agent_id="ensign-1",
        goal="Inspect",
    )

    assert parent_id is None
    assert len(service.calls) == 1


async def test_originate_crew_task_propagates_cancellation() -> None:
    service = _CrewSessionServiceSpy()
    service.error = asyncio.CancelledError()
    orchestrator = _orchestrator(service)

    with pytest.raises(asyncio.CancelledError):
        await orchestrator.originate_crew_task(
            origin_agent_id="lieutenant-1",
            goal="Inspect",
        )


def _make_proactive_runtime(*, trust_score: float, service: Any | None) -> Any:
    runtime = MagicMock(spec=ProbOSRuntime)
    runtime.ward_room = MagicMock()
    runtime.trust_network = MagicMock()
    runtime.trust_network.get_score.return_value = trust_score
    runtime.ward_room_router = MagicMock(spec=WardRoomRouter)
    runtime.ward_room_router.extract_endorsements.return_value = (None, [])
    runtime.config = MagicMock()
    runtime.config.communications = MagicMock()
    runtime.config.communications.dm_min_rank = "ensign"
    runtime.crew_session_service = service
    runtime.dispatcher = None
    runtime.callsign_registry = MagicMock()
    runtime.callsign_registry.get_callsign.return_value = "callsign"
    return runtime


def _agent(agent_id: str) -> Any:
    agent = MagicMock(spec=BaseAgent)
    agent.id = agent_id
    agent.callsign = agent_id
    return agent


async def test_proactive_lieutenant_uses_unified_service_and_exact_defaults() -> None:
    service = _CrewSessionServiceSpy()
    loop = ProactiveCognitiveLoop(cooldown=0)
    loop.set_runtime(_make_proactive_runtime(trust_score=0.6, service=service))

    cleaned, actions = await loop._extract_and_execute_actions(
        _agent("lieutenant-1"),
        "Before [CREW]Map the sensor grid[/CREW] after",
    )

    assert "[CREW]" not in cleaned and "[/CREW]" not in cleaned
    assert [action for action in actions if action.get("type") == "crew"] == [{
        "type": "crew",
        "parent_id": "parent-1",
        "goal": "Map the sensor grid",
    }]
    assert service.calls == [{
        "principal": _Principal("lieutenant-1"),
        "goal": "Map the sensor grid",
        "success_criteria": [
            "Complete the stated goal with verifiable evidence.",
        ],
        "expected_deliverable": "A verified result for the stated goal.",
    }]


async def test_proactive_ensign_strips_tag_without_ingress_call() -> None:
    service = _CrewSessionServiceSpy()
    loop = ProactiveCognitiveLoop(cooldown=0)
    loop.set_runtime(_make_proactive_runtime(trust_score=0.1, service=service))

    cleaned, actions = await loop._extract_and_execute_actions(
        _agent("ensign-1"),
        "[CREW]Do the work[/CREW]",
    )

    assert "[CREW]" not in cleaned
    assert [action for action in actions if action.get("type") == "crew"] == []
    assert service.calls == []


@pytest.mark.parametrize("trust_score", [0.75, 0.9])
async def test_proactive_commander_and_senior_reach_service(
    trust_score: float,
) -> None:
    service = _CrewSessionServiceSpy()
    loop = ProactiveCognitiveLoop(cooldown=0)
    loop.set_runtime(
        _make_proactive_runtime(trust_score=trust_score, service=service),
    )

    _cleaned, actions = await loop._extract_and_execute_actions(
        _agent("officer-1"),
        "[CREW]Coordinate the response[/CREW]",
    )

    assert len([action for action in actions if action.get("type") == "crew"]) == 1
    assert len(service.calls) == 1


async def test_proactive_missing_service_strips_and_skips() -> None:
    loop = ProactiveCognitiveLoop(cooldown=0)
    loop.set_runtime(_make_proactive_runtime(trust_score=0.6, service=None))

    cleaned, actions = await loop._extract_and_execute_actions(
        _agent("lieutenant-1"),
        "[CREW]No service[/CREW]",
    )

    assert "[CREW]" not in cleaned
    assert [action for action in actions if action.get("type") == "crew"] == []


async def test_proactive_service_error_does_not_use_alternate_runner() -> None:
    service = _CrewSessionServiceSpy()
    service.error = ValueError("crew_session_agent_invalid")
    runtime = _make_proactive_runtime(trust_score=0.6, service=service)
    runtime.crew_orchestrator = MagicMock()
    loop = ProactiveCognitiveLoop(cooldown=0)
    loop.set_runtime(runtime)

    _cleaned, actions = await loop._extract_and_execute_actions(
        _agent("lieutenant-1"),
        "[CREW]Rejected[/CREW]",
    )

    assert [action for action in actions if action.get("type") == "crew"] == []
    runtime.crew_orchestrator.originate_crew_task.assert_not_called()
