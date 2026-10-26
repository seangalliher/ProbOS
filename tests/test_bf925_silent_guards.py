"""BF-925 (#1655) M1: guards on methods nothing defines, driven through the real classes.

F06 the Insights report, F11 Ward Room @mention Hebbian links, F18 the Chiefs' subordinate stats,
F13 the AD-572 bridge. Each test runs the production path on the real object, so it fails if the
method it reaches disappears again: no guard is left to hide it.
"""

from __future__ import annotations

import inspect
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from probos.bridge_alerts import BridgeAlertService
from probos.capability_request import CapabilityRequestStore
from probos.cognitive.episode_clustering import EpisodeCluster
from probos.cognitive.episodic_procedural_bridge import EpisodicProceduralBridge
from probos.cognitive.insights import InsightService
from probos.cognitive.procedure_store import ProcedureStore
from probos.cognitive.procedures import Procedure
from probos.config import BridgeConfig, SystemConfig
from probos.crew_profile import CallsignRegistry
from probos.mesh.routing import REL_SOCIAL, HebbianRouter
from probos.persistent_tasks import PersistentTaskStore
from probos.proactive import ProactiveCognitiveLoop
from probos.runtime import ProbOSRuntime
from probos.skill_request import SkillRequestStore
from probos.substrate.registry import AgentRegistry
from probos.ward_room.service import WardRoomService


# --- F06: the Insights report -------------------------------------------------------------------

async def _completed_run(text: str, **_kwargs: Any) -> dict[str, Any]:
    """The task store's process_fn: a run that succeeds, so a once task completes."""
    return {"success": True, "text": text}


@pytest.fixture
async def insights_runtime(tmp_path: Path):
    """A real ProbOSRuntime (not started) holding the four real stores its start() attaches.

    start() sets bridge_alerts, capability_request_store, skill_request_store and
    persistent_task_store from the communication services; the test sets them because it boots no
    vessel. The task store's tick loop sleeps an hour, so only the test fires tasks.
    """
    runtime = ProbOSRuntime(config=SystemConfig(), data_dir=tmp_path / "runtime")
    runtime.bridge_alerts = BridgeAlertService()
    runtime.capability_request_store = CapabilityRequestStore(db_path=str(tmp_path / "capability.db"))
    runtime.skill_request_store = SkillRequestStore(db_path=str(tmp_path / "skill.db"))
    runtime.persistent_task_store = PersistentTaskStore(
        db_path=str(tmp_path / "tasks.db"), process_fn=_completed_run, tick_interval=3600.0,
    )
    stores = (runtime.capability_request_store, runtime.skill_request_store, runtime.persistent_task_store)
    for store in stores:
        await store.start()
    try:
        yield runtime
    finally:
        for store in reversed(stores):
            await store.stop()


async def test_the_report_reads_alerts_requests_and_completed_tasks(insights_runtime: Any) -> None:
    runtime = insights_runtime
    assert runtime.bridge_alerts.check_trust_change("agent-x", 0.9, 0.3) is not None  # premise: one ALERT
    await runtime.capability_request_store.file_request("agent-x", "grant", "shell")
    await runtime.skill_request_store.file_request("agent-y", "skill-1", skill_label="Triage")
    task = await runtime.persistent_task_store.create_task(
        "run diagnostics", name="Diagnostics", execute_at=time.time() - 1.0,
    )
    await runtime.persistent_task_store._execute_due_tasks()  # the tick loop's body, as BF-877's tests run it
    assert (await runtime.persistent_task_store.get_task(task.id)).status == "completed"  # premise

    report = await InsightService(runtime=runtime).build_report(days=7)

    assert [(a.severity, a.label.split(":")[0]) for a in report.anomaly_windows] == [("critical", "trust_network")]
    assert sorted((d.source, d.summary) for d in report.pending_decisions) == [
        ("capability_request", "grant shell"),
        ("skill_request", "skill Triage"),
    ]
    assert [t.description for t in report.scheduled_tasks_completed] == ["Diagnostics"]
    assert set(report.unavailable) == {"top_topics", "top_crew"}
    assert "Not available: top topics" in report.to_markdown()


async def test_a_source_that_is_not_running_reports_not_available(tmp_path: Path) -> None:
    runtime = ProbOSRuntime(config=SystemConfig(), data_dir=tmp_path / "runtime")  # not started: no store attached
    report = await InsightService(runtime=runtime).build_report(days=3)
    assert report.is_empty()
    assert report.unavailable == {
        "top_topics": "no store records recall frequency by topic",
        "top_crew": "no store counts DM or session messages per crew member",
        "scheduled_tasks_completed": "service not running",
        "pending_decisions": "service not running",
        "anomaly_windows": "service not running",
    }
    markdown = report.to_markdown()
    assert "_No activity recorded in this window._" in markdown
    assert "scheduled tasks (service not running)" in markdown


async def test_the_report_json_keeps_its_keys_and_adds_unavailable(tmp_path: Path) -> None:
    runtime = ProbOSRuntime(config=SystemConfig(), data_dir=tmp_path / "runtime")
    data = (await InsightService(runtime=runtime).build_report(days=7)).to_json()
    assert set(data) == {
        "window_days", "generated_at", "top_topics", "top_crew", "scheduled_tasks_completed",
        "pending_decisions", "anomaly_windows", "narrative_summary", "unavailable",
    }
    assert data["top_topics"] == [] and data["top_crew"] == []  # no source; the keys stay for API readers
    assert data["unavailable"]["anomaly_windows"] == "service not running"


async def test_alerts_outside_the_window_are_left_out(insights_runtime: Any) -> None:
    runtime = insights_runtime
    old = runtime.bridge_alerts.check_trust_change("agent-old", 0.9, 0.3)
    new = runtime.bridge_alerts.check_trust_change("agent-new", 0.9, 0.7)  # an ADVISORY
    old.timestamp = time.time() - 8 * 86400.0  # the service stamps alerts when raised; this one is moved back
    report = await InsightService(runtime=runtime).build_report(days=7)
    assert [(a.label, a.severity) for a in report.anomaly_windows] == [(f"trust_network: {new.title}", "warning")]


def test_the_insights_doubles_match_the_real_classes() -> None:
    """tests/test_ad810_insights.py's fakes stand for these stores; each keeps the real parameters."""
    from tests.test_ad810_insights import _FakeAlerts, _FakeRequests

    for double, real, name in (
        (_FakeAlerts, BridgeAlertService, "get_recent_alerts"),
        (_FakeRequests, CapabilityRequestStore, "list_pending"),
        (_FakeRequests, SkillRequestStore, "list_pending"),
    ):
        assert list(inspect.signature(getattr(double, name)).parameters) == list(
            inspect.signature(getattr(real, name)).parameters
        ), f"{double.__name__}.{name} drifted from {real.__name__}.{name}"


# --- F11: Ward Room @mention Hebbian links ------------------------------------------------------

class _AcceptingDispatcher:
    """Stands for AD-654d's dispatcher, which attach_dispatcher binds with the CallsignRegistry.

    It masks only the mention TaskEvent's delivery, which BF-925 does not change; the Hebbian write
    F11 adds links the ids resolved for the dispatch, whatever the dispatch returns (A2).
    """

    async def dispatch(self, event: Any) -> Any:
        return SimpleNamespace(accepted=True, rejected=0, unroutable=0)


class _RecordingDispatcher(_AcceptingDispatcher):
    """An accepting dispatcher that records each TaskEvent and can run one step during the dispatch.

    ``during`` stands for what the real dispatcher's awaits let happen meanwhile (an agent recycled).
    """

    def __init__(self, during: Any = None) -> None:
        self.events: list[Any] = []
        self._during = during

    async def dispatch(self, event: Any) -> Any:
        self.events.append(event)
        if self._during is not None:
            await self._during()
        return await super().dispatch(event)


_CREW = (  # (agent id, agent type, callsign, alive)
    ("bones-1", "medical_officer", "Bones", True),
    ("thea-1", "science_officer", "Thea", True),
    ("ghost-1", "ghost_officer", "Ghost", False),
)


@pytest.fixture
async def ward_room(tmp_path: Path):
    """A started WardRoomService with a real HebbianRouter, AgentRegistry and CallsignRegistry.

    Crew are SimpleNamespaces with the attributes AgentRegistry.register and CallsignRegistry.resolve
    read. Thea opens the thread every test posts in.
    """
    router = HebbianRouter()
    service = WardRoomService(db_path=str(tmp_path / "ward_room.db"), hebbian_router=router)
    await service.start()
    registry = AgentRegistry()
    callsigns = CallsignRegistry()
    callsigns.bind_registry(registry)
    for agent_id, agent_type, callsign, alive in _CREW:
        await registry.register(SimpleNamespace(id=agent_id, agent_type=agent_type, pool=agent_type, is_alive=alive))
        callsigns.set_callsign(agent_type, callsign)
    service.attach_dispatcher(_AcceptingDispatcher(), callsigns)  # as startup/finalize.py does
    channel_id = (await service.list_channels())[0].id
    thread = await service.create_thread(channel_id, "thea-1", "Survey", "Opening the survey.", author_callsign="Thea")
    try:
        yield SimpleNamespace(service=service, router=router, registry=registry, callsigns=callsigns, thread_id=thread.id)
    finally:
        await service.stop()


def _social(router: HebbianRouter, source: str, target: str) -> float:
    return router.get_weight(source, target, rel_type=REL_SOCIAL)


async def test_a_mention_records_a_social_link_to_the_mentioned_agent(ward_room: Any) -> None:
    await ward_room.service.create_post(ward_room.thread_id, "author-1", "@Bones please check the scan", author_callsign="Avery")
    assert _social(ward_room.router, "author-1", "bones-1") == pytest.approx(0.05)  # one reinforcement (reward 0.05)
    assert _social(ward_room.router, "author-1", "thea-1") == pytest.approx(0.05)  # premise: the AD-453 reply link


async def test_one_post_reinforces_each_mentioned_agent_once(ward_room: Any) -> None:
    await ward_room.service.create_post(ward_room.thread_id, "author-1", "@Bones @bones and @Thea", author_callsign="Avery")
    assert _social(ward_room.router, "author-1", "bones-1") == pytest.approx(0.05)  # not 0.05 * 0.995 + 0.05
    assert _social(ward_room.router, "author-1", "thea-1") == pytest.approx(0.05)  # the reply link already counts Thea


async def test_no_link_for_oneself_an_unknown_callsign_or_an_agent_that_is_not_alive(ward_room: Any) -> None:
    await ward_room.service.create_post(ward_room.thread_id, "bones-1", "@Bones @Nobody @Ghost", author_callsign="Bones")
    social = {key for key in ward_room.router.all_weights_typed() if key[2] == REL_SOCIAL}
    assert social == {("bones-1", "thea-1", REL_SOCIAL)}  # only the reply link


async def test_the_link_goes_to_the_agent_the_mention_was_dispatched_to(ward_room: Any) -> None:
    """A2 (round-1 review): the recipient is recycled during the dispatch (stopped, unregistered, a new
    agent of its callsign registered). The TaskEvent and the link name the agent the mention resolved
    to for the dispatch; resolving again would link the replacement (D3: one id per mention)."""

    async def replace_bones() -> None:
        bones = ward_room.registry.get("bones-1")
        bones.is_alive = False
        await ward_room.registry.unregister("bones-1")
        await ward_room.registry.register(
            SimpleNamespace(id="bones-2", agent_type="medical_officer", pool="medical_officer", is_alive=True)
        )

    dispatcher = _RecordingDispatcher(during=replace_bones)
    ward_room.service.attach_dispatcher(dispatcher, ward_room.callsigns)
    await ward_room.service.create_post(ward_room.thread_id, "author-1", "@Bones please check the scan", author_callsign="Avery")
    # premise, asserted here and not inside the dispatch (create_post catches an exception raised there, so
    # the case would pass with its premise failed): the recipient was replaced, so a later resolve names the replacement
    assert ward_room.callsigns.resolve("Bones")["agent_id"] == "bones-2"
    assert [event.target.agent_id for event in dispatcher.events] == ["bones-1"]  # premise: AD-654d unchanged
    assert _social(ward_room.router, "author-1", "bones-1") == pytest.approx(0.05)
    assert _social(ward_room.router, "author-1", "bones-2") == 0.0


async def test_no_link_without_a_dispatcher_even_with_a_resolver(ward_room: Any) -> None:
    """A2 (round-1 review): attach_dispatcher(None, callsigns) binds a resolver but no dispatcher, so no
    TaskEvent is dispatched and no mention link is recorded (D3)."""
    ward_room.service.attach_dispatcher(None, ward_room.callsigns)
    await ward_room.service.create_post(ward_room.thread_id, "author-1", "@Bones please check the scan", author_callsign="Avery")
    social = {key for key in ward_room.router.all_weights_typed() if key[2] == REL_SOCIAL}
    assert social == {("author-1", "thea-1", REL_SOCIAL)}  # only the reply link


# --- F18: the Chiefs' subordinate communication stats -------------------------------------------

def _chief_loop(service: WardRoomService, registry: AgentRegistry) -> ProactiveCognitiveLoop:
    """A proactive loop whose runtime holds the real Ward Room and AgentRegistry F18 reads.

    The runtime is a MagicMock for the context sources F18 does not touch, as
    test_ad630_leadership_feedback.py's helper is; ward_room, registry and the ontology's answer are
    set explicitly. A MagicMock invents any attribute, so
    test_the_attributes_these_paths_read_exist_on_the_runtime pins the names on a real runtime.
    """
    loop = ProactiveCognitiveLoop(interval=120.0, cooldown=300.0)
    runtime = MagicMock()
    runtime.ontology.get_subordinate_agent_types = MagicMock(return_value=["engineering_officer"])
    runtime.ontology.get_crew_context = MagicMock(return_value=None)
    runtime.ward_room = service
    runtime.registry = registry
    runtime._start_time_wall = 0.0
    runtime.trust_network = AsyncMock()
    runtime.trust_network.get_score = AsyncMock(return_value=0.5)
    runtime.skill_service = None
    runtime._introspective_telemetry = None
    runtime.conn_manager = None
    runtime.cognitive_skill_catalog = None
    loop.set_runtime(runtime)
    loop._build_self_monitoring_context = AsyncMock(return_value=None)
    return loop


def _chief() -> MagicMock:
    chief = MagicMock()
    chief.agent_type = "chief_engineer"
    chief.id = "chief-1"
    chief.sovereign_id = "uuid-chief"
    chief.callsign = "LaForge"
    return chief


async def _subordinate_context(tmp_path: Path, *, alive: bool) -> dict[str, Any]:
    service = WardRoomService(db_path=str(tmp_path / "ward_room.db"))
    await service.start()
    try:
        registry = AgentRegistry()
        await registry.register(SimpleNamespace(
            id="forge-1", agent_type="engineering_officer", pool="engineering_officer",
            is_alive=alive, callsign="Forge", sovereign_id="uuid-forge",
        ))
        channel_id = (await service.list_channels())[0].id
        thread = await service.create_thread(channel_id, "ops-1", "Status", "Status thread.", author_callsign="Ops")
        for index in range(3):  # posts carry agent.id, as every create_post caller passes
            await service.create_post(thread.id, "forge-1", f"Report {index}.", author_callsign="Forge")
        return await _chief_loop(service, registry)._gather_context(_chief(), 0.5)
    finally:
        await service.stop()


async def test_a_chief_sees_a_subordinates_ward_room_stats(tmp_path: Path) -> None:
    context = await _subordinate_context(tmp_path, alive=True)
    assert context["subordinate_stats"]["Forge"]["posts_total"] == 3  # by agent.id; the sovereign id counts 0


async def test_a_subordinate_with_no_live_agent_is_skipped(tmp_path: Path) -> None:
    context = await _subordinate_context(tmp_path, alive=False)
    assert "subordinate_stats" not in context


def test_the_attributes_these_paths_read_exist_on_the_runtime(tmp_path: Path) -> None:
    runtime = ProbOSRuntime(config=SystemConfig(), data_dir=tmp_path / "runtime")
    names = {
        "ward_room", "registry", "ontology", "bridge_alerts", "capability_request_store",
        "skill_request_store", "persistent_task_store", "event_log",
    }
    assert names <= set(vars(runtime)), sorted(names - set(vars(runtime)))


# --- F13: the AD-572 episodic-procedural bridge -------------------------------------------------

def _cluster(cluster_id: str, episode_ids: list[str]) -> EpisodeCluster:
    return EpisodeCluster(
        cluster_id=cluster_id, episode_ids=episode_ids, episode_count=len(episode_ids),
        centroid=[1.0, 0.0], variance=0.0, success_rate=1.0, is_success_dominant=True,
        is_failure_dominant=False, participating_agents=["agent-a"], intent_types=["diagnose"],
        first_occurrence=1.0, last_occurrence=2.0,
    )


@pytest.fixture
async def procedure_store(tmp_path: Path):
    store = ProcedureStore(data_dir=tmp_path / "procedures")
    await store.start()
    try:
        await store.save(Procedure(
            id="p-1", name="Diagnose", intent_types=["diagnose"], provenance=["ep-0", "ep-1", "ep-2", "ep-3"],
        ))
        yield store
    finally:
        await store.stop()


async def test_the_bridge_merges_a_cluster_a_stored_procedure_covers(procedure_store: ProcedureStore) -> None:
    """The stored procedure loads through list_active and get, so a covered cluster is not new."""
    bridge = EpisodicProceduralBridge(BridgeConfig(), procedure_store=procedure_store)
    assert await bridge.bridge_episodes_to_procedures([], [_cluster("c-1", [f"ep-{i}" for i in range(5)])]) == []


async def test_the_bridge_still_bridges_a_novel_cluster(procedure_store: ProcedureStore) -> None:
    bridge = EpisodicProceduralBridge(BridgeConfig(), procedure_store=procedure_store)
    bridged = await bridge.bridge_episodes_to_procedures([], [_cluster("c-2", [f"new-{i}" for i in range(5)])])
    assert [procedure.origin_cluster_id for procedure in bridged] == ["c-2"]
