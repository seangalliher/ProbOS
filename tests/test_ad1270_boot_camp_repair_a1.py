"""AD-1270 (#1324) slice 4b, Amendment A1: each chain phase asks for the relaxation again, and
the boot camp finds a new crew without BF-034's cold-start flag.

The chain cases use the AD-1347 S4 harness: a real ``CognitiveAgent`` and ``SubTaskExecutor``,
with ANALYZE and COMPOSE as stand-ins that make no model call, and the real ``EvaluateHandler``
and ``ReflectHandler`` with AD-639 on. The coordinator is real, with an injected clock, and
trust is a real ``TrustNetwork``. The new-crew cases use a real ``EpisodicMemory`` on
``tmp_path``. Nothing here reads the vessel's data directory or starts a vessel.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from probos.boot_camp import BootCampCoordinator
from probos.cognitive.cognitive_agent import CognitiveAgent
from probos.cognitive.sub_task import SubTaskChain, SubTaskExecutor, SubTaskResult, SubTaskSpec, SubTaskType
from probos.cognitive.sub_tasks.evaluate import EvaluateHandler
from probos.cognitive.sub_tasks.reflect import ReflectHandler
from probos.config import BootCampConfig, SystemConfig
from probos.consensus.trust import TrustNetwork
from probos.startup.finalize import _activate_boot_camp_on_cold_start

_START = 1_000_000.0
_TIMEOUT_S = 120 * 60
CREW = {"agent_id": "crew-1", "callsign": "Wesley", "department": "science"}
_FLEET = [
    SimpleNamespace(id="security_officer-0", agent_type="security_officer", callsign="Worf", department="security"),
    SimpleNamespace(id="file_reader-0", agent_type="file_reader", callsign="", department=""),
]


class _Clock:
    def __init__(self) -> None:
        self.now = _START

    def __call__(self) -> float:
        return self.now


class _Episodes:
    """The coordinator's episode-count collaborator (not under repair)."""

    async def count_for_agent(self, agent_id: str) -> int:
        return 0


def _coordinator(clock: _Clock, *, trust: TrustNetwork | None = None, memory: Any = None) -> BootCampCoordinator:
    return BootCampCoordinator(
        config=BootCampConfig(
            relax_quality_gates=True, min_time_minutes=0, nudge_cooldown_seconds=0, timeout_minutes=120,
        ),
        ward_room=SimpleNamespace(),
        trust_service=trust if trust is not None else TrustNetwork(),
        episodic_memory=memory if memory is not None else _Episodes(),
        emit_event_fn=lambda event_type, data: None,
        clock=clock,
    )


# --- each chain phase asks again ------------------------------------------------------------


class _Runtime:
    """The runtime attributes the chain entry points read directly, plus a no-op emit_event."""

    def __init__(self, coord: BootCampCoordinator, trust: TrustNetwork) -> None:
        self.boot_camp = coord
        self.trust_network = trust  # no record for the crew agent: the 0.5 prior, AD-639's low band
        self.config = SystemConfig()  # chain_tuning on, low_trust_ceiling 0.60

    def emit_event(self, *args: Any, **kwargs: Any) -> None:
        return None


class _Analysis:
    """ANALYZE's JSON contract, with no model call. Records the marker each call is given."""

    def __init__(self, during_triage: Callable[[], None]) -> None:
        self.markers: list[Any] = []
        self._during_triage = during_triage

    async def __call__(self, spec: Any, context: dict, prior_results: list) -> SubTaskResult:
        self.markers.append(context.get("_boot_camp_active"))
        if len(self.markers) == 1:
            self._during_triage()
        return SubTaskResult(
            sub_task_type=SubTaskType.ANALYZE, name=spec.name, success=True,
            result={"intended_actions": ["ward_room_reply"], "contribution_assessment": "RESPOND"},
        )


class _Compose:
    """COMPOSE with no model call."""

    async def __call__(self, spec: Any, context: dict, prior_results: list) -> SubTaskResult:
        return SubTaskResult(
            sub_task_type=SubTaskType.COMPOSE, name=spec.name, success=True, result={"output": "The sweep is clean."},
        )


class _Seen:
    """A real handler, with each result it returned recorded."""

    def __init__(self, handler: Any) -> None:
        self._handler = handler
        self.results: list[dict] = []

    async def __call__(self, spec: Any, context: dict, prior_results: list) -> SubTaskResult:
        result = await self._handler(spec, context, prior_results)
        self.results.append(result.result)
        return result


def _chain() -> SubTaskChain:
    return SubTaskChain(steps=[
        SubTaskSpec(sub_task_type=SubTaskType.ANALYZE, name="analyze"),
        SubTaskSpec(sub_task_type=SubTaskType.COMPOSE, name="compose"),
        SubTaskSpec(sub_task_type=SubTaskType.EVALUATE, name="evaluate"),
        SubTaskSpec(sub_task_type=SubTaskType.REFLECT, name="reflect"),
    ])


def _agent(coord: BootCampCoordinator, trust: TrustNetwork, analysis: _Analysis) -> tuple[Any, _Seen, _Seen]:
    # Every path here returns before a model call; a client with no methods makes one fail loudly.
    evaluate = _Seen(EvaluateHandler(llm_client=SimpleNamespace(), runtime=None))
    reflect = _Seen(ReflectHandler(llm_client=SimpleNamespace(), runtime=None))
    executor = SubTaskExecutor(config=None)
    executor.register_handler(SubTaskType.ANALYZE, analysis)
    executor.register_handler(SubTaskType.COMPOSE, _Compose())
    executor.register_handler(SubTaskType.EVALUATE, evaluate)
    executor.register_handler(SubTaskType.REFLECT, reflect)
    agent: Any = CognitiveAgent(agent_id=CREW["agent_id"], instructions="Test instructions.", runtime=None)
    agent.agent_type = "science_officer"
    agent.callsign = CREW["callsign"]
    agent.set_sub_task_executor(executor)
    agent._runtime = _Runtime(coord, trust)
    agent._build_chain_for_intent = lambda observation: _chain()  # chain construction is not under test
    return agent, evaluate, reflect


def _observation() -> dict:
    return {
        "intent": "ward_room_notification",
        "intent_id": "ad1270-a1",
        "context": "LaForge: Wesley, what did the sensor sweep show?",
        "params": {
            "channel_name": "Science", "is_dm_channel": False,
            "author_id": "laforge-1", "author_callsign": "LaForge",
            "title": "Sensor sweep", "text": "Wesley, what did the sensor sweep show?",
        },
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("expires", [False, True], ids=["held", "expired-in-triage"])
async def test_a_relaxation_that_expires_during_triage_does_not_reach_phase_two(expires: bool) -> None:
    clock, trust = _Clock(), TrustNetwork()
    coord = _coordinator(clock, trust=trust)
    await coord.activate([CREW])

    def during_triage() -> None:
        if expires:
            clock.now = _START + _TIMEOUT_S  # ordinary elapsed time: the deadline passes during triage

    analysis = _Analysis(during_triage)
    agent, evaluate, reflect = _agent(coord, trust, analysis)
    observation = _observation()

    await agent._execute_chain_with_intent_routing(observation)

    assert len(analysis.markers) == 2, "premise: triage and phase 2 both ran"
    assert evaluate.results and reflect.results, "premise: phase 2 reached the real gates"
    assert coord.is_enrolled(CREW["agent_id"]) is not expires
    if expires:
        assert analysis.markers == [True, None]
        assert "_boot_camp_active" not in observation
        assert evaluate.results[-1].get("bypass_reason") == "low_trust_band"  # AD-639 ran in phase 2
        assert reflect.results[-1].get("reflection") == "low_trust_band_bypass"
    else:
        assert analysis.markers == [True, True]
        assert evaluate.results[-1].get("bypass_reason") == "boot_camp"
        assert reflect.results[-1].get("bypass_reason") == "boot_camp"


@pytest.mark.asyncio
@pytest.mark.parametrize("entry", ["direct", "routed"])
async def test_each_chain_entry_asks_again_on_a_reused_observation(entry: str) -> None:
    clock, trust = _Clock(), TrustNetwork()
    coord = _coordinator(clock, trust=trust)
    await coord.activate([CREW])
    clock.now = _START + _TIMEOUT_S  # the relaxation ended before this chain started
    analysis = _Analysis(lambda: None)
    agent, evaluate, _ = _agent(coord, trust, analysis)
    observation = _observation()
    observation["_boot_camp_active"] = True  # an earlier phase's answer on the same dict (the phase-2 hand-off)

    if entry == "direct":
        await agent._execute_sub_task_chain(_chain(), observation)
    else:
        await agent._execute_chain_with_intent_routing(observation)

    assert analysis.markers == ([None] if entry == "direct" else [None, None])
    assert "_boot_camp_active" not in observation
    assert evaluate.results[-1].get("bypass_reason") == "low_trust_band"


# --- a new crew, without BF-034's flag ------------------------------------------------------


class _Stats:
    """The one read ``_is_new_crew_start`` makes of the episodic memory."""

    def __init__(self, total: int = 0, error: Exception | None = None) -> None:
        self.total = total
        self.error = error

    async def get_stats(self) -> dict:
        if self.error is not None:
            raise self.error
        return {"total": self.total}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("lifecycle", "memory", "expected"),
    [
        ("first_boot", _Stats(0), True),
        ("reset", _Stats(0), True),
        ("stasis_recovery", _Stats(0), False),
        ("first_boot", _Stats(3), False),
        ("first_boot", _Stats(error=OSError("collection unavailable")), False),
    ],
    ids=["first-boot", "reset", "stasis-recovery", "episodes", "count-raises"],
)
async def test_a_new_crew_needs_no_session_record_and_no_episodes(lifecycle: str, memory: _Stats, expected: bool) -> None:
    from probos.startup.finalize import _is_new_crew_start  # imported here so each case fails by name on M2

    runtime = SimpleNamespace(_lifecycle_state=lifecycle, episodic_memory=memory, is_cold_start=False)

    assert await _is_new_crew_start(runtime) is expected


@pytest.mark.asyncio
@pytest.mark.parametrize("lifecycle", ["first_boot", "stasis_recovery"], ids=["first-boot", "stasis-recovery"])
async def test_finalization_enrols_a_new_crew_with_a_real_empty_memory(tmp_path: Path, lifecycle: str) -> None:
    from probos.cognitive.episodic import EpisodicMemory

    memory = EpisodicMemory(db_path=str(tmp_path / "episodic" / "episodes.db"))
    await memory.start()
    try:
        assert memory, "premise: a live memory object is truthy, so BF-034's `not episodic_memory` reads it as warm"
        coord = _coordinator(_Clock(), memory=memory)
        runtime = SimpleNamespace(
            boot_camp=coord, is_cold_start=False, ontology=None, _lifecycle_state=lifecycle,
            episodic_memory=memory, registry=SimpleNamespace(all=lambda: list(_FLEET)),
        )
        ran = await _activate_boot_camp_on_cold_start(runtime=runtime)
    finally:
        await memory.stop()

    new_crew = lifecycle == "first_boot"
    assert ran is new_crew
    assert coord.is_enrolled("security_officer-0") is new_crew
    assert not coord.is_enrolled("file_reader-0")  # not crew (crew_utils.is_crew_agent)
