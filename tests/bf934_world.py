"""BF-934 (#1673): the world the think-cycle tests of slices S1 to S3 share.

Real: ProactiveCognitiveLoop, WardRoomService and WardRoomRouter (SQLite on tmp_path), RecordsStore (tmp_path), TrustNetwork, the
registries, SubTaskExecutor, and a CognitiveAgent run through handle_intent. Doubles, named: the model (``Model``: one scripted answer per
request, the requests kept), the triage's ANALYZE and QUERY handlers (``Analysis``, ``Query``: no model call) and the runtime, a SimpleNamespace
that holds exactly what the think cycle reads. No network, no sleeping, no real clock where a fake will do. It imports no BF-934 name.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from probos.cognitive.cognitive_agent import _CACHE_HITS, _CACHE_MISSES, _DECISION_CACHES, CognitiveAgent
from probos.cognitive.dm_sanity_gate import DmSanityGate
from probos.cognitive.llm_client import MockLLMClient
from probos.cognitive.novelty_gate import NoveltyVerdict
from probos.cognitive.sub_task import SubTaskExecutor, SubTaskResult, SubTaskType
from probos.config import RecordsConfig, SystemConfig
from probos.consensus.trust import TrustNetwork
from probos.crew_profile import CallsignRegistry, Rank
from probos.knowledge.records_store import RecordsStore
from probos.mesh.intent import IntentBus
from probos.proactive import ProactiveCognitiveLoop
from probos.substrate.event_log import EventLog
from probos.substrate.identity import generate_pool_ids
from probos.substrate.registry import AgentRegistry
from probos.types import IntentResult, LLMResponse
from probos.ward_room.service import WardRoomService
from probos.ward_room_router import WardRoomRouter

#: The heading S1's billet carries. A model double that answers only a prompt holding it stands for a model that obeys a decision it is shown.
DECIDED = "Your triage already decided this turn"
BLOCKS = (
    "Noted for the record.\n"
    "[PROPOSAL]\n"
    "Title: Cache the roster\n"
    "Rationale: The roster is read forty times per cycle and never changes.\n"
    "Affected Systems: Ward Room\n"
    "Priority: low\n"
    "[/PROPOSAL]\n"
    "[NOTEBOOK roster-cache]\n"
    "The roster is read 40 times per cycle.\n"
    "[/NOTEBOOK]"
)
CREW = (("science_officer", "Kira", "science"), ("security_officer", "Worf", "security"), ("counselor", "Troi", "medical"))


def obeys_decision(request: Any) -> str:
    """The model double: the blocks when its prompt carries the decision, else the silence the single call defaults to."""
    return BLOCKS if DECIDED in request.prompt else "[NO_RESPONSE]"


class Model(MockLLMClient):
    """One scripted answer per request; every request is kept."""

    def __init__(self, answer: Callable[[Any], str]) -> None:
        super().__init__()
        self._answer = answer
        self.requests: list[Any] = []

    async def complete(self, request: Any, **_kwargs: Any) -> LLMResponse:
        self.requests.append(request)
        return LLMResponse(content=self._answer(request), model="test-model")


class Analysis:
    """ANALYZE's contract with no model call: the actions this triage intends."""

    def __init__(self, intended: list[str]) -> None:
        self.intended = intended

    async def __call__(self, spec: Any, context: dict, prior: list) -> SubTaskResult:
        result = {"intended_actions": list(self.intended), "composition_brief": {"situation": "test"}}
        return SubTaskResult(sub_task_type=SubTaskType.ANALYZE, name=spec.name, success=True, result=result)


class Query:
    async def __call__(self, spec: Any, context: dict, prior: list) -> SubTaskResult:
        return SubTaskResult(sub_task_type=SubTaskType.QUERY, name=spec.name, success=True, result={})


class NothingIsNovel:
    """AD-493's gate finding every observation a repeat."""

    def check(self, agent_id: str, text: str) -> NoveltyVerdict:
        return NoveltyVerdict(is_novel=False, similarity=0.99, reason="repeated", matched_preview="earlier")

    def record(self, agent_id: str, text: str) -> None:
        pass


class Crew(CognitiveAgent):
    agent_type = "science_officer"
    _handled_intents = {"proactive_think"}
    instructions = "You are a test crew agent."


@dataclass
class World:
    ws: WardRoomService
    rt: SimpleNamespace
    loop: ProactiveCognitiveLoop
    records: RecordsStore
    registry: AgentRegistry
    events: EventLog | None
    ids: dict[str, str]

    def notebook(self, callsign: str, slug: str) -> Path:
        return self.records.repo_path / "notebooks" / callsign / f"{slug}.md"


@asynccontextmanager
async def world(tmp_path: Path, *, event_log: bool = False) -> AsyncIterator[World]:
    """A started ship; ``event_log`` adds a real EventLog on tmp_path (slice S3). Everything it opens is closed on exit."""
    _DECISION_CACHES.clear()
    _CACHE_HITS.clear()
    _CACHE_MISSES.clear()
    ws = WardRoomService(db_path=str(tmp_path / "wr.db"))
    await ws.start()
    records = RecordsStore(RecordsConfig(repo_path=str(tmp_path / "ship-records"), auto_commit=False))
    await records.initialize()
    events = EventLog(tmp_path / "events.db") if event_log else None
    if events is not None:
        await events.start()
    try:
        registry = AgentRegistry()
        callsigns = CallsignRegistry()
        ids = {agent_type: generate_pool_ids(agent_type, agent_type, 1)[0] for agent_type, _, _ in CREW}
        for agent_type, callsign, _ in CREW:
            callsigns.set_callsign(agent_type, callsign)
        callsigns.bind_registry(registry)
        depts = {agent_type: dept for agent_type, _, dept in CREW}
        config = SystemConfig()
        router = WardRoomRouter(
            ward_room=ws, registry=MagicMock(spec=AgentRegistry), intent_bus=MagicMock(spec=IntentBus),
            trust_network=MagicMock(), ontology=None, callsign_registry=callsigns, episodic_memory=None,
            event_emitter=MagicMock(), event_log=AsyncMock(), config=config,
        )
        rt = SimpleNamespace(
            ward_room=ws, registry=registry, callsign_registry=callsigns,
            ontology=SimpleNamespace(get_agent_department=lambda agent_type: depts.get(agent_type)),
            config=config, trust_network=TrustNetwork(), ward_room_router=router, episodic_memory=None,
            hebbian_router=None, dispatcher=None, _records_store=records, working_memory=None,
            dm_sanity_gate=DmSanityGate(), skill_service=None, boot_camp=None, emit_event=lambda *a, **k: None,
        )
        if events is not None:
            rt.event_log = events
        loop = ProactiveCognitiveLoop(interval=120.0, cooldown=300.0, on_event=None)
        loop.set_runtime(rt)
        for agent_type, callsign, _ in CREW[1:]:
            await registry.register(SimpleNamespace(
                id=ids[agent_type], agent_type=agent_type, pool=agent_type, callsign=callsign, is_alive=True, capabilities=[],
            ))
        yield World(ws, rt, loop, records, registry, events, ids)
    finally:
        await ws.stop()
        if events is not None:
            await events.stop()


async def crew(w: World, intended: list[str], answer: Callable[[Any], str]) -> tuple[Crew, Model]:
    """The real science officer (Kira): a real CognitiveAgent whose triage intends *intended* and whose model is *answer*."""
    model = Model(answer)
    agent = Crew(agent_id=w.ids["science_officer"], llm_client=model, runtime=w.rt)
    agent.callsign = "Kira"
    executor = SubTaskExecutor(config=w.rt.config.sub_task)  # enabled by default: AD-643a's routing runs, as it does on the ship
    executor.register_handler(SubTaskType.QUERY, Query())
    executor.register_handler(SubTaskType.ANALYZE, Analysis(intended))
    agent.set_sub_task_executor(executor)
    await w.registry.register(agent)
    return agent, model


def thinker(w: World, reply: str, metadata: dict | None = None) -> SimpleNamespace:
    """Kira with the model left out: ``handle_intent`` answers *reply* with *metadata*, as the cognitive agent's lifecycle would."""
    agent = SimpleNamespace(
        id=w.ids["science_officer"], agent_type="science_officer", pool="science_officer", callsign="Kira",
        is_alive=True, capabilities=[],
    )

    async def handle_intent(intent: Any) -> IntentResult:
        return IntentResult(intent_id=intent.id, agent_id=agent.id, success=True, result=reply, metadata=dict(metadata or {}))

    agent.handle_intent = handle_intent
    return agent


def observation() -> dict[str, Any]:
    """The observation a free-form proactive think perceives."""
    return {
        "intent": "proactive_think", "intent_id": "bf934-intent", "context": "ship status",
        "params": {"context_parts": {}, "trust_score": "0.6", "agency_level": "suggestive", "rank": "lieutenant", "duty": None},
    }


async def think(w: World, agent: Any, trust: float = 0.6) -> None:
    """One real think cycle for *agent* (a Lieutenant)."""
    await w.loop._think_for_agent(agent, Rank.LIEUTENANT, trust)


async def threads(w: World, channel: str | None = None) -> list[str]:
    """The titles of every thread, or of those in the channel called *channel*, oldest first."""
    titles: list[tuple[float, str]] = []
    for ch in await w.ws.list_channels():
        if channel is None or ch.name == channel:
            titles.extend((th.created_at, th.title) for th in await w.ws.list_threads(ch.id, limit=500))
    return [title for _, title in sorted(titles)]
