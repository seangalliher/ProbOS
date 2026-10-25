"""BF-923 (#1652) M1: the behavioral-metric and orientation callers read the episodic store through APIs it has.

Every store here is a real ``EpisodicMemory`` unless a test is about a failing store, where the double is
``create_autospec(EpisodicMemory, instance=True)`` (signatures checked; results set by the test).
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, create_autospec, patch

import pytest

from probos.cognitive.episodic import EpisodicMemory
from probos.config import BehavioralMetricsConfig, SystemConfig
from probos.types import Episode


async def _store(tmp_path: Path, owners: dict[str, int]) -> EpisodicMemory:
    """A started real store holding ``n`` distinct episodes for each owner id."""
    memory = EpisodicMemory(db_path=str(tmp_path / "episodic" / "episodes.db"))
    await memory.start()
    now = time.time()
    for owner, count in owners.items():
        for i in range(count):
            await memory.store(
                Episode(
                    user_input=f"[BF-923] {owner} observation {i}",
                    timestamp=now - 60.0 * (i + 1),
                    agent_ids=[owner],
                    source="direct",
                )
            )
    return memory


def _thread(*authors: str, thread_id: str = "bf923-t1") -> dict[str, Any]:
    return {
        "thread_id": thread_id,
        "posts": [{"author_id": author, "body": f"post by {author}"} for author in authors],
        "unique_authors": set(authors),
        "channel_id": "ch-1",
        "channel_name": "science",
        "title": "BF-923 thread",
    }


# --- the reproduction ------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_old_call_is_rejected_by_the_real_recall(tmp_path) -> None:
    """#1652's reproduction: ``recall`` takes no ``agent_id``. Passes before and after BF-923."""
    memory = await _store(tmp_path, {"sov-a": 1})
    try:
        with pytest.raises(TypeError, match="agent_id"):
            await memory.recall("", agent_id="sov-a", k=1)
    finally:
        await memory.stop()


# --- the anchor metric -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_anchor_metric_reads_each_authors_recent_episodes(tmp_path) -> None:
    """Four episodes are needed, so both authors' two must be read."""
    from probos.cognitive.behavioral_metrics import BehavioralMetricsEngine

    memory = await _store(tmp_path, {"author-a": 2, "author-b": 2})
    try:
        engine = BehavioralMetricsEngine(BehavioralMetricsConfig(anchor_independence_min_episodes=4))
        result = await engine._compute_anchor_grounded_emergence([_thread("author-a", "author-b")], memory)
    finally:
        await memory.stop()

    assert result["analyzed_threads"] == 1
    assert 0.0 <= result["independence_score"] <= 1.0


@pytest.mark.asyncio
async def test_a_slot_author_is_read_by_the_sovereign_id_its_episodes_carry(tmp_path) -> None:
    """Ward Room posts carry slot ids; episodes carry the sovereign id the identity registry issued."""
    from probos.cognitive.behavioral_metrics import BehavioralMetricsEngine
    from probos.identity import AgentIdentityRegistry

    registry = AgentIdentityRegistry(data_dir=tmp_path)
    await registry.start()
    try:
        slots = ("scout_0_bf923", "scout_1_bf923")
        certs = [
            await registry.resolve_or_issue(
                slot_id=slot,
                agent_type="scout",
                callsign=callsign,
                instance_id="bf923",
                vessel_name="ProbOS",
                department="science",
                post_id="scout",
                baseline_version="v0",
            )
            for slot, callsign in zip(slots, ("Wesley", "Reyes"))
        ]
        assert all(cert.agent_uuid not in slots for cert in certs)
        memory = await _store(tmp_path, {cert.agent_uuid: 2 for cert in certs})
        try:
            engine = BehavioralMetricsEngine(BehavioralMetricsConfig(anchor_independence_min_episodes=4))
            engine.set_identity_registry(registry)
            result = await engine._compute_anchor_grounded_emergence([_thread(*slots)], memory)
        finally:
            await memory.stop()
    finally:
        await registry.stop()

    assert result["analyzed_threads"] == 1


@pytest.mark.asyncio
async def test_a_failing_store_is_reported_once_at_warning(caplog) -> None:
    from probos.cognitive.behavioral_metrics import BehavioralMetricsEngine

    engine = BehavioralMetricsEngine(BehavioralMetricsConfig(anchor_independence_min_episodes=2))
    memory = create_autospec(EpisodicMemory, instance=True)
    memory.recent_for_agent.side_effect = RuntimeError("store offline")
    threads = [_thread("a1", "a2"), _thread("a3", "a4", thread_id="bf923-t2")]

    with caplog.at_level(logging.DEBUG, logger="probos.cognitive.behavioral_metrics"):
        result = await engine._compute_anchor_grounded_emergence(threads, memory)

    assert result["analyzed_threads"] == 0
    warnings = [record for record in caplog.records if record.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert "anchor analysis failed for 2 of 2 threads" in warnings[0].getMessage()


@pytest.mark.asyncio
async def test_the_booted_runtime_reads_crew_authors_episodes(tmp_path) -> None:
    """The seam: the engine the runtime built, with the identity registry the runtime bound, on the
    runtime's own store, for crew agents whose sovereign ids startup issued."""
    from probos.cognitive.cognitive_agent import CognitiveAgent
    from probos.runtime import ProbOSRuntime

    rt = ProbOSRuntime(
        config=SystemConfig(),
        data_dir=tmp_path,
        episodic_memory=EpisodicMemory(db_path=str(tmp_path / "episodic" / "episodes.db")),  # a default boot has none
    )
    await rt.start()
    try:
        crew = [
            agent for agent in rt.registry.all()
            if isinstance(agent, CognitiveAgent)
            and getattr(agent, "did", "")  # crew carry a birth certificate; utility agents hold asset tags
            and getattr(agent, "sovereign_id", "")
            and agent.sovereign_id != agent.id
        ][:2]
        assert len(crew) == 2  # a shortfall is a hard stop for the Architect (section 17), not a reason to stub
        assert rt.episodic_memory is not None
        assert rt._behavioral_metrics_engine is not None
        for agent in crew:
            for i in range(2):
                await rt.episodic_memory.store(
                    Episode(
                        user_input=f"[BF-923] {agent.id} booted observation {i}",
                        timestamp=time.time() - 60.0 * (i + 1),
                        agent_ids=[agent.sovereign_id],
                        source="direct",
                    )
                )
        result = await rt._behavioral_metrics_engine._compute_anchor_grounded_emergence(
            [_thread(crew[0].id, crew[1].id)], rt.episodic_memory,
        )
    finally:
        await rt.stop()

    assert result["analyzed_threads"] == 1


# --- the orientation count ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_count_agent_episodes_counts_the_agents_own_episodes(tmp_path) -> None:
    from probos.cognitive.orientation import count_agent_episodes

    memory = await _store(tmp_path, {"sov-a": 3, "slot-b": 1})
    try:
        assert await count_agent_episodes(memory, SimpleNamespace(id="slot-a", sovereign_id="sov-a")) == 3
        assert await count_agent_episodes(memory, SimpleNamespace(id="slot-b", sovereign_id=None)) == 1
        assert await count_agent_episodes(memory, SimpleNamespace(id="slot-c", sovereign_id="sov-c")) == 0
        assert await count_agent_episodes(None, SimpleNamespace(id="slot-a", sovereign_id="sov-a")) == 0
    finally:
        await memory.stop()


@pytest.mark.asyncio
async def test_a_failing_count_is_logged_at_warning_and_reports_none(caplog) -> None:
    from probos.cognitive.orientation import count_agent_episodes

    memory = create_autospec(EpisodicMemory, instance=True)
    memory.count_for_agent.side_effect = RuntimeError("store offline")

    with caplog.at_level(logging.WARNING, logger="probos.cognitive.orientation"):
        count = await count_agent_episodes(memory, SimpleNamespace(id="slot-a", sovereign_id="sov-a"))

    assert count == 0
    assert "BF-923: episode count failed for sov-a" in caplog.text


def _proactive_loop() -> tuple[Any, Any]:
    """The runtime shape ``tests/test_ad576_llm_unavailability.py::_make_loop`` builds."""
    from probos.consensus.trust import TrustNetwork
    from probos.crew_profile import CallsignRegistry
    from probos.knowledge.records_store import RecordsStore
    from probos.proactive import ProactiveCognitiveLoop
    from probos.runtime import ProbOSRuntime
    from probos.substrate.registry import AgentRegistry
    from probos.ward_room import WardRoomService
    from probos.ward_room_router import WardRoomRouter

    loop = ProactiveCognitiveLoop(interval=60, cooldown=60)
    rt = MagicMock(spec=ProbOSRuntime)
    rt.ward_room = MagicMock(spec=WardRoomService)
    rt.ward_room.list_channels = AsyncMock(return_value=[])
    rt.ward_room.create_thread = AsyncMock()
    rt.ward_room.get_thread = AsyncMock(return_value=None)
    rt.ward_room.get_recent_activity = AsyncMock(return_value=[])
    rt.trust_network = MagicMock(spec=TrustNetwork)
    rt.trust_network.get_score = MagicMock(return_value=0.6)
    rt.trust_network.record_outcome = MagicMock(return_value=0.6)
    rt.ward_room_router = MagicMock(spec=WardRoomRouter)
    rt.ward_room_router.extract_endorsements = MagicMock(return_value=("", []))
    rt.ward_room_router.deliver_bridge_alert = AsyncMock()
    rt._records_store = AsyncMock(spec=RecordsStore)
    rt._records_store.write_notebook = AsyncMock()
    rt.ontology = None
    rt.callsign_registry = MagicMock(spec=CallsignRegistry)
    rt.callsign_registry.get_callsign = MagicMock(return_value="TestAgent")
    rt.config = SystemConfig()
    rt.episodic_memory = None
    rt.bridge_alerts = MagicMock()
    rt.event_log = None
    rt.skill_service = None
    rt.hebbian_router = None
    rt.acm = None
    rt.registry = MagicMock(spec=AgentRegistry)
    loop.set_runtime(rt)
    return loop, rt


@pytest.mark.asyncio
async def test_the_proactive_supplement_is_built_with_the_agents_episode_count(tmp_path) -> None:
    """The caller: ``ProactiveCognitiveLoop._gather_context`` on a real store, for an agent inside its
    orientation window (the default ``orientation`` config: supplement on, 600 s window)."""
    from probos.cognitive.orientation import OrientationContext, OrientationService
    from probos.substrate.agent import BaseAgent

    loop, rt = _proactive_loop()
    memory = await _store(tmp_path, {"sov-a": 2})
    rt.episodic_memory = memory
    service = create_autospec(OrientationService, instance=True)
    service.build_orientation.return_value = OrientationContext()
    service.render_proactive_orientation.return_value = "ORIENTATION: ground claims in evidence."
    loop._orientation_service = service
    loop._config = MagicMock()
    agent = MagicMock(spec=BaseAgent)
    agent.id = "slot-a"
    agent.agent_type = "scout"
    agent.is_alive = True
    agent.sovereign_id = "sov-a"
    agent._birth_timestamp = time.time() - 60  # set by hand: fresh runtime crew lack it (filed, section 18 R11); this tests the count inside the window

    try:
        context = await loop._gather_context(agent, 0.6)
    finally:
        await memory.stop()

    assert service.build_orientation.call_args.kwargs["episodic_memory_count"] == 2
    assert context["orientation_supplement"] == "ORIENTATION: ground claims in evidence."


class _StasisCrewMember:
    """A crew agent as the warm-boot loop reads it: identity fields and ``set_orientation``."""

    def __init__(self, agent_type: str, slot_id: str, sovereign_id: str | None, callsign: str) -> None:
        self.agent_type = agent_type
        self.id = slot_id
        self.sovereign_id = sovereign_id
        self.callsign = callsign
        self.orientation_text = ""

    def set_orientation(self, rendered: str, ctx: Any) -> None:
        self.orientation_text = rendered


@pytest.mark.asyncio
async def test_the_warm_boot_orientation_tells_each_agent_its_own_episode_count(tmp_path) -> None:
    """The caller: finalize's stasis-recovery orientation, with the real OrientationService."""
    from probos.cognitive.orientation import OrientationService
    from probos.startup.finalize import _orient_crew_after_stasis

    memory = await _store(tmp_path, {"sov-scout": 3, "counselor-0": 1})
    scout = _StasisCrewMember("scout", "scout-0", "sov-scout", "Wesley")
    counselor = _StasisCrewMember("counselor", "counselor-0", None, "Troi")
    architect = _StasisCrewMember("architect", "architect-0", "sov-architect", "Number One")
    runtime = SimpleNamespace(
        _orientation_service=OrientationService(config=SystemConfig()),
        registry=SimpleNamespace(all=lambda: [scout, counselor, architect]),
        ontology=None,
        episodic_memory=memory,
        trust_network=None,
        callsign_registry=None,
        _previous_session=None,
        _stasis_duration=3600.0,
    )
    try:
        oriented = await _orient_crew_after_stasis(runtime=runtime)
    finally:
        await memory.stop()

    assert oriented == 3
    assert "You have 3 episodic memories from before stasis." in scout.orientation_text
    assert "You have 1 episodic memories from before stasis." in counselor.orientation_text
    assert "STASIS RECORD" in architect.orientation_text
    assert "episodic memories from before stasis" not in architect.orientation_text


# --- Amendment A1: the producer's thread read, its cost, and the Tier 3 hold ---------------------------


class _Ticker:
    """Counts event-loop turns. Work that holds the loop shows as no new turns while it runs."""

    def __init__(self) -> None:
        self.ticks = 0
        self._task: asyncio.Task[None] | None = None

    async def _spin(self) -> None:
        while True:
            self.ticks += 1
            await asyncio.sleep(0)

    async def __aenter__(self) -> _Ticker:
        self._task = asyncio.create_task(self._spin())
        await asyncio.sleep(0)
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        assert self._task is not None
        self._task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self._task


@pytest.mark.asyncio
async def test_the_dream_metrics_read_the_crew_channels_and_not_dms(tmp_path) -> None:
    """The producer on a real Ward Room. ``browse_threads`` reads ``channels=None`` as the given agent's
    memberships, so ``agent_id=""`` read no thread and no metric ran. A DM is private to its two parties."""
    from probos.cognitive.behavioral_metrics import BehavioralMetricsEngine
    from probos.ward_room import WardRoomService

    ward = WardRoomService(db_path=str(tmp_path / "ward.db"))
    await ward.start()
    memory = await _store(tmp_path, {"author-a": 2, "author-b": 2})
    try:
        crew_channel = next(c for c in await ward.list_channels() if c.channel_type == "ship")
        dm_channel = await ward.get_or_create_dm_channel("author-a", "author-b")
        thread_ids: dict[str, str] = {}
        for label, channel in (("crew", crew_channel), ("dm", dm_channel)):
            thread = await ward.create_thread(channel.id, "author-a", f"BF-923 {label} thread", "An opening observation.")
            await ward.create_post(thread.id, "author-b", f"{label}: a second observation.")
            await ward.create_post(thread.id, "author-a", f"{label}: a third observation.")
            await ward.create_post(thread.id, "author-b", f"{label}: a fourth observation.")
            thread_ids[label] = thread.id
        engine = BehavioralMetricsEngine()
        with patch("probos.cognitive.behavioral_metrics.embed_text", return_value=[0.5] * 10), \
                patch("probos.cognitive.behavioral_metrics._cosine_similarity", return_value=0.5), \
                patch.object(ward, "get_thread", wraps=ward.get_thread) as get_thread:
            snapshot = await engine.compute_behavioral_metrics(ward_room=ward, episodic_memory=memory)
    finally:
        await memory.stop()
        await ward.stop()

    read = {call.args[0] for call in get_thread.await_args_list}
    assert thread_ids["crew"] in read
    assert thread_ids["dm"] not in read  # never fetched, so never analysed
    assert snapshot.threads_analyzed == 1
    assert snapshot.anchor_analyzed_threads == 1


@pytest.mark.asyncio
async def test_a_failing_ward_room_read_is_logged_at_warning_and_raised(caplog) -> None:
    """The dream's step 13 catches it and continues (cognitive/dreaming.py:1683); no zero snapshot is kept."""
    from probos.cognitive.behavioral_metrics import BehavioralMetricsEngine
    from probos.ward_room import WardRoomService

    ward = create_autospec(WardRoomService, instance=True)
    ward.list_channels.side_effect = RuntimeError("ward room offline")
    engine = BehavioralMetricsEngine()

    with caplog.at_level(logging.WARNING, logger="probos.cognitive.behavioral_metrics"):
        with pytest.raises(RuntimeError, match="ward room offline"):
            await engine.compute_behavioral_metrics(ward_room=ward)

    assert "BF-923 (#1652): the Ward Room read failed" in caplog.text
    assert engine.latest_snapshot is None


@pytest.mark.asyncio
async def test_each_author_is_read_once_per_computation(tmp_path) -> None:
    """``recent_for_agent`` fetches the whole collection; a read per thread repeated it for every thread an
    author posted in (13.4 s for 10 threads on a 3,000-episode store, review round 1)."""
    from probos.cognitive.behavioral_metrics import BehavioralMetricsEngine

    memory = await _store(tmp_path, {"author-a": 2, "author-b": 2})
    try:
        engine = BehavioralMetricsEngine(BehavioralMetricsConfig(anchor_independence_min_episodes=4))
        threads = [_thread("author-a", "author-b", thread_id=f"bf923-t{i}") for i in range(10)]
        with patch.object(memory, "recent_for_agent", wraps=memory.recent_for_agent) as read:
            result = await engine._compute_anchor_grounded_emergence(threads, memory)
    finally:
        await memory.stop()

    assert result["analyzed_threads"] == 10
    assert sorted(call.args[0] for call in read.await_args_list) == ["author-a", "author-b"]


@pytest.mark.asyncio
async def test_a_failing_author_fails_only_its_threads_and_is_read_once(caplog) -> None:
    from probos.cognitive.behavioral_metrics import BehavioralMetricsEngine

    def read(owner_id: str, k: int = 5, **_: Any) -> list[Any]:
        if owner_id == "a-bad":
            raise RuntimeError("shard offline")
        return [MagicMock(), MagicMock()]

    engine = BehavioralMetricsEngine(BehavioralMetricsConfig(anchor_independence_min_episodes=2))
    memory = create_autospec(EpisodicMemory, instance=True)
    memory.recent_for_agent.side_effect = read
    threads = [
        _thread("a1", "a2", thread_id="bf923-ok"),
        _thread("a1", "a-bad", thread_id="bf923-bad-1"),
        _thread("a2", "a-bad", thread_id="bf923-bad-2"),
    ]

    with patch("probos.cognitive.social_verification.compute_anchor_independence", return_value=0.6), \
            caplog.at_level(logging.WARNING, logger="probos.cognitive.behavioral_metrics"):
        result = await engine._compute_anchor_grounded_emergence(threads, memory)

    assert result["analyzed_threads"] == 1
    assert [call.args[0] for call in memory.recent_for_agent.await_args_list].count("a-bad") == 1
    warnings = [record for record in caplog.records if record.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert "anchor analysis failed for 2 of 3 threads" in warnings[0].getMessage()


@pytest.mark.asyncio
async def test_the_author_reads_yield_to_the_event_loop() -> None:
    """Each read is a synchronous full scan; the loop runs between reads, so its longest pause is one read."""
    from probos.cognitive.behavioral_metrics import BehavioralMetricsEngine

    engine = BehavioralMetricsEngine(BehavioralMetricsConfig(anchor_independence_min_episodes=2))
    memory = create_autospec(EpisodicMemory, instance=True)
    seen: list[int] = []
    async with _Ticker() as ticker:
        def read(owner_id: str, k: int = 5, **_: Any) -> list[Any]:
            seen.append(ticker.ticks)
            return [MagicMock(), MagicMock()]

        memory.recent_for_agent.side_effect = read
        with patch("probos.cognitive.social_verification.compute_anchor_independence", return_value=0.6):
            result = await engine._compute_anchor_grounded_emergence([_thread("a1", "a2")], memory)

    assert result["analyzed_threads"] == 1
    assert len(seen) == 2
    assert seen[1] > seen[0]


@pytest.mark.asyncio
async def test_synthesis_embeds_off_the_event_loop() -> None:
    """Synthesis embeds the thread and every post with the synchronous embedder; the loop keeps running."""
    from probos.cognitive.behavioral_metrics import BehavioralMetricsEngine
    from probos.ward_room import WardRoomService
    from probos.ward_room.models import WardRoomChannel

    now = time.time()
    ward = create_autospec(WardRoomService, instance=True)
    ward.list_channels.return_value = [
        WardRoomChannel(id="ch-1", name="All Hands", channel_type="ship", department="", created_by="system", created_at=now),
    ]
    ward.browse_threads.return_value = [
        SimpleNamespace(id="bf923-t1", channel_id="ch-1", channel_name="All Hands", title="BF-923 thread"),
    ]
    ward.get_thread.return_value = {"posts": [
        {"id": f"p{i}", "author_id": f"a{i % 2}", "author_callsign": "", "body": f"observation {i}", "created_at": now - 10.0 * i}
        for i in range(4)
    ]}
    engine = BehavioralMetricsEngine()
    seen: list[int] = []
    async with _Ticker() as ticker:
        def slow_embed(text: str) -> list[float]:
            seen.append(ticker.ticks)
            time.sleep(0.02)
            return [0.5] * 10

        with patch("probos.cognitive.behavioral_metrics.embed_text", side_effect=slow_embed), \
                patch("probos.cognitive.behavioral_metrics._cosine_similarity", return_value=0.5), \
                patch.object(engine, "_compute_convergence_correctness", AsyncMock(return_value={
                    "total": 0, "correct": 0, "incorrect": 0, "unverified": 0, "correctness_rate": None,
                })):
            snapshot = await engine.compute_behavioral_metrics(ward_room=ward)

    assert snapshot.threads_analyzed == 1
    assert len(seen) == 5  # the thread and its four posts
    assert seen[-1] > seen[0]


@pytest.mark.asyncio
async def test_convergence_embeds_off_the_event_loop() -> None:
    from probos.cognitive.behavioral_metrics import BehavioralMetricsEngine

    engine = BehavioralMetricsEngine()
    seen: list[int] = []
    async with _Ticker() as ticker:
        def slow_embed(text: str) -> list[float]:
            seen.append(ticker.ticks)
            time.sleep(0.02)
            return [0.5] * 10

        with patch("probos.cognitive.behavioral_metrics.embed_text", side_effect=slow_embed), \
                patch("probos.cognitive.behavioral_metrics._cosine_similarity", return_value=0.9):
            result = await engine._compute_convergence_correctness([_thread("a1", "a2", "a3")])

    assert result["total"] == 1
    assert len(seen) == 3  # one post per author
    assert seen[-1] > seen[0]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "probe_class",
    [
        "FrameDiversityProbe",
        "SynthesisDetectionProbe",
        "CrossDeptTriggerProbe",
        "ConvergenceCorrectnessProbe",
        "AnchorGroundedEmergenceProbe",
    ],
)
async def test_the_behavioral_probes_are_held_from_drift(tmp_path, probe_class: str) -> None:
    """BF-921 D3: each probe's history is a run of zeros, so a first real score would read as critical drift
    for ``__crew__`` (a Counselor assessment, VitalsMonitor's medical alert). The score is kept; drift skips it."""
    import dataclasses

    from probos.cognitive import behavioral_probes
    from probos.cognitive.behavioral_metrics import BehavioralSnapshot
    from probos.cognitive.drift_detector import DriftDetector
    from probos.cognitive.qualification import QualificationStore, TestResult
    from probos.config import QualificationConfig

    probe = getattr(behavioral_probes, probe_class)()
    snapshot = BehavioralSnapshot(
        timestamp=time.time(),
        threads_analyzed=4,
        frame_diversity_score=0.6,
        synthesis_rate=0.6,
        cross_dept_trigger_rate=0.6,
        convergence_correctness_rate=0.6,
        anchor_grounded_rate=0.6,
    )
    runtime = SimpleNamespace(_behavioral_metrics_engine=SimpleNamespace(latest_snapshot=snapshot))
    result = await probe.run("__crew__", runtime)
    assert result.score == 0.6
    assert result.inconclusive is True

    store = QualificationStore(data_dir=tmp_path)
    await store.start()
    try:
        now = time.time()
        for subject in ("__crew__", "bf923-control"):
            for i in range(19):  # the live history: every run scored 0
                await store.save_result(TestResult(
                    agent_id=subject, test_name=probe.name, tier=3, score=0.0, passed=True,
                    timestamp=now - 3600.0 * (i + 1), duration_ms=0.0,
                ))
        await store.save_result(result)
        await store.save_result(dataclasses.replace(result, agent_id="bf923-control", inconclusive=False))
        detector = DriftDetector(store, QualificationConfig())
        held = await detector.analyze_agent("__crew__", [probe.name])
        unheld = await detector.analyze_agent("bf923-control", [probe.name])
    finally:
        await store.stop()

    assert unheld.overall_severity == "critical"  # the premise: what the first real score would raise
    assert held.overall_severity == "normal"
    assert not held.drift_detected


# --- Amendment A2: a skipped probe run is held too -----------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("state", ["no-engine", "no-snapshot-since-boot"])
async def test_a_skipped_probe_run_is_held_from_drift(tmp_path, state: str) -> None:
    """BF-711, BF-921 D3: with no engine, or no snapshot since boot (the engine keeps snapshots in memory only),
    each probe returns a skip result that measured nothing. Through the real harness and store it is stored
    inconclusive, enters no drift statistics, and still sets the first baseline (its error stays None)."""
    from probos.cognitive import behavioral_probes
    from probos.cognitive.behavioral_metrics import BehavioralMetricsEngine
    from probos.cognitive.drift_detector import DriftDetector
    from probos.cognitive.qualification import QualificationHarness, QualificationStore
    from probos.config import QualificationConfig

    engine = None if state == "no-engine" else BehavioralMetricsEngine()
    runtime = SimpleNamespace(_behavioral_metrics_engine=engine)
    store = QualificationStore(data_dir=tmp_path)
    await store.start()
    try:
        harness = QualificationHarness(store)
        for probe_class in (
            behavioral_probes.FrameDiversityProbe,
            behavioral_probes.SynthesisDetectionProbe,
            behavioral_probes.CrossDeptTriggerProbe,
            behavioral_probes.ConvergenceCorrectnessProbe,
            behavioral_probes.AnchorGroundedEmergenceProbe,
        ):
            harness.register_test(probe_class())
        results = await harness.run_collective(3, runtime)
        names = [r.test_name for r in results]
        stored = [await store.get_latest("__crew__", name) for name in names]
        report = await DriftDetector(store, QualificationConfig()).analyze_agent("__crew__", names)
    finally:
        await store.stop()

    assert len(names) == 5
    for row in stored:
        assert row is not None
        assert row.details.get("skipped") is True  # the skip path, not a measured score
        assert row.score == 0.0
        assert row.error is None
        assert row.inconclusive is True  # BF-923 A2: the skip is held
        assert row.is_baseline is True  # unchanged: a skip with no error still sets the first baseline
    assert [signal.sample_count for signal in report.signals] == [0] * 5
    assert not report.drift_detected
