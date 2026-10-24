"""BF-921 (#1636): the Counselor receives the events it subscribes to, and no output suppression carries a penalty.

The contract is ``prompts/bf-921-counselor-event-delivery-and-suppression-penalty.md``.

Root cause (the contract's section 1): ``ProbOSRuntime.add_event_listener`` built its filter with ``str()``.
``EventType`` is a ``(str, Enum)``, whose ``str()`` is ``"EventType.NAME"`` on Python 3.11+, so every listener
that passed members filtered on names no event carries, locally and as NATS subjects.

Stand-ins, named: the chain executor in the suppression seam test (it returns EVALUATE's suppress); the Counselor's
``_send_therapeutic_dm`` (a spy) wherever a DM could be sent; the trust network in the handler tests; a NATS bus double
whose ``js_subscribe`` records subjects; in the cascade seam test (A1), the social verification service's episodic
memory (``_SameThreadEpisodes``: one same-thread episode per peer and one for the author); and, in the callsign tests,
``SimpleNamespace`` agents registered in a real ``AgentRegistry``. In the cascade seam test the handler spy wraps the
real ``_on_cascade_confabulation``; the service, its emitter (``runtime._emit_event``), BF-920's
``check_and_alert_cascade_risk``, the subscription and the Counselor are the booted runtime's own.

The woken consumers' first-delivery defects (A2), each made reachable by the delivery fix: in the AD-532e case the
``ProcedureStore`` is real (SQLite and its semantic index on the deterministic ``BF662EmbeddingFunctionA`` backend),
the ``DreamingEngine``'s router, trust network, episodic memory and LLM client are stand-ins, and the listener repeats
``startup/dreaming.py``'s on an unstarted runtime; in the concurrent-DM case the runtime is booted and the sender, the
DM channel and the thread storage are its own (a wrapper only records each send's result); the two failed-send cases
and the quarantine case use a ``WardRoomService`` (and its ``MessageStore``) built by ``create_autospec``, with the
real sender; in the zone-recovery case the ``CounselorProfileStore`` is real (SQLite) and the profile is reloaded
from it.
"""

from __future__ import annotations

import asyncio
import logging
import time
from types import SimpleNamespace  # not a ProbOS class
from typing import Any
from unittest.mock import AsyncMock, MagicMock, create_autospec

import pytest

from probos.cognitive.cognitive_agent import CognitiveAgent
from probos.cognitive.counselor import CounselorAgent, CounselorProfileStore
from probos.cognitive.dreaming import DreamingEngine
from probos.cognitive.llm_client import BaseLLMClient
from probos.cognitive.procedure_store import ProcedureStore
from probos.cognitive.procedures import Procedure, ProcedureStep
from probos.cognitive.sub_task import SubTaskChain, SubTaskExecutor, SubTaskResult, SubTaskSpec, SubTaskType
from probos.config import SystemConfig
from probos.consensus.trust import TrustNetwork
from probos.events import EventType
from probos.knowledge import embeddings
from probos.mesh.routing import HebbianRouter
from probos.runtime import ProbOSRuntime
from probos.substrate.registry import AgentRegistry
from probos.types import AnchorFrame, Episode
from probos.ward_room._helpers import check_and_alert_cascade_risk
from probos.ward_room.messages import MessageStore
from probos.ward_room.service import WardRoomService
from tests.fixtures.bf662_embedding_fakes import BF662EmbeddingFunctionA

#: The members the five listeners that were deaf before BF-921 pass: counselor.py (one of 24),
#: finalize.py (BF-125), dreaming.py (AD-532e, AD-534b) and optimization_counselor.py (AD-659c).
WOKEN = (
    EventType.CONFABULATION_SUPPRESSED,
    EventType.GAME_COMPLETED,
    EventType.TASK_EXECUTION_COMPLETE,
    EventType.PROCEDURE_FALLBACK_LEARNING,
    EventType.OPTIMIZATION_PROPOSAL_APPLIED,
)

#: Every reason a suppression can carry today, one added later, and none.
REASONS = ("quality_gate", "confabulation_detected", "raw_json_output", "a_reason_added_later", "")


async def _settle(predicate: Any, *, timeout: float = 3.0) -> bool:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        if predicate():
            return True
        await asyncio.sleep(0.01)
    return bool(predicate())


def _counselor() -> CounselorAgent:
    counselor = CounselorAgent(llm_client=AsyncMock(spec=BaseLLMClient))
    counselor._trust_network = MagicMock()
    counselor._send_therapeutic_dm = AsyncMock(return_value=True)
    return counselor


def _suppressing_executor() -> MagicMock:
    executor = MagicMock(spec=SubTaskExecutor)
    executor.can_execute.return_value = True
    executor.execute = AsyncMock(return_value=[
        SubTaskResult(sub_task_type=SubTaskType.COMPOSE, name="compose-reply", result={"output": "A reply."}),
        SubTaskResult(
            sub_task_type=SubTaskType.EVALUATE,
            name="evaluate-reply",
            result={"recommendation": "suppress", "rejection_reason": "confabulation_detected"},
        ),
    ])
    return executor


# --- the seam: ProbOSRuntime.add_event_listener --------------------------------------------------


def test_a_member_filter_is_stored_as_wire_values(tmp_path) -> None:
    rt = ProbOSRuntime(config=SystemConfig(), data_dir=tmp_path)
    fn = MagicMock()
    rt.add_event_listener(fn, event_types=[EventType.CONFABULATION_SUPPRESSED, "trust_update"])

    stored = next(type_filter for listener, type_filter in rt._event_listeners if listener is fn)
    assert stored == frozenset({"confabulation_suppressed", "trust_update"})


def test_no_filter_still_means_every_event(tmp_path) -> None:
    rt = ProbOSRuntime(config=SystemConfig(), data_dir=tmp_path)
    fn = MagicMock()
    rt.add_event_listener(fn)

    assert next(type_filter for listener, type_filter in rt._event_listeners if listener is fn) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("member", WOKEN, ids=lambda m: m.value)
async def test_a_member_filter_receives_its_event_locally(tmp_path, member: EventType) -> None:
    rt = ProbOSRuntime(config=SystemConfig(), data_dir=tmp_path)
    received: list[dict[str, Any]] = []

    async def listener(event: dict[str, Any]) -> None:
        received.append(event)

    rt.add_event_listener(listener, event_types=[member])
    rt.emit_event(member, {"agent_id": "a1"})

    assert await _settle(lambda: len(received) == 1)
    assert received[0]["type"] == member.value


@pytest.mark.asyncio
async def test_a_live_listener_member_filter_receives_its_event(tmp_path) -> None:
    rt = ProbOSRuntime(config=SystemConfig(), data_dir=tmp_path)
    received: list[dict[str, Any]] = []

    async def listener(event: dict[str, Any]) -> None:
        received.append(event)

    await rt.register_live_event_listener(listener, event_types=[EventType.TRUST_UPDATE])
    rt.emit_event(EventType.TRUST_UPDATE, {"agent_id": "a1"})

    assert await _settle(lambda: len(received) == 1)


@pytest.mark.asyncio
async def test_a_member_filter_subscribes_to_its_nats_subject(tmp_path) -> None:
    rt = ProbOSRuntime(config=SystemConfig(), data_dir=tmp_path)
    rt.nats_bus = SimpleNamespace(connected=True, js_subscribe=AsyncMock())
    rt._nats_events_wired = True

    rt.add_event_listener(AsyncMock(), event_types=[EventType.CONFABULATION_SUPPRESSED])

    assert await _settle(lambda: rt.nats_bus.js_subscribe.await_count == 1)
    assert rt.nats_bus.js_subscribe.await_args.args[0] == "system.events.confabulation_suppressed"


@pytest.mark.asyncio
async def test_a_failed_nats_subscription_is_logged(tmp_path, caplog) -> None:
    rt = ProbOSRuntime(config=SystemConfig(), data_dir=tmp_path)
    rt.nats_bus = SimpleNamespace(connected=True, js_subscribe=AsyncMock(side_effect=RuntimeError("no responders")))
    rt._nats_events_wired = True

    with caplog.at_level(logging.WARNING, logger="probos.runtime"):
        rt.add_event_listener(AsyncMock(), event_types=[EventType.CONFABULATION_SUPPRESSED])
        assert await _settle(lambda: "BF-921: NATS event subscription failed" in caplog.text)
    assert "confabulation_suppressed" in caplog.text
    assert "no responders" in caplog.text


# --- the seam test through the real startup wiring -------------------------------------------------


@pytest.mark.asyncio
async def test_a_chain_suppression_reaches_the_booted_counselor(tmp_path, caplog, monkeypatch) -> None:
    """A crew agent built by the agent fleet (its runtime set by startup) and the Counselor initialized by
    finalize. Only the chain executor is a stand-in."""
    rt = ProbOSRuntime(config=SystemConfig(), data_dir=tmp_path)
    await rt.start()
    try:
        counselor = rt.registry.get_by_pool("counselor")[0]
        agent = next(
            a for a in rt.registry.all()
            if isinstance(a, CognitiveAgent) and a.agent_type != "counselor"
        )
        assert agent._runtime is rt  # set by startup, not by this test
        dm = AsyncMock(return_value=True)
        monkeypatch.setattr(counselor, "_send_therapeutic_dm", dm)
        agent._sub_task_executor = _suppressing_executor()
        chain = SubTaskChain(
            steps=[SubTaskSpec(sub_task_type=SubTaskType.COMPOSE, name="compose-reply")],
            source="bf921-seam",
        )

        with caplog.at_level(logging.INFO, logger="probos.cognitive.counselor"):
            for _ in range(2):  # BF-206's old penalty fired from the second suppression in an hour
                decision = await agent._execute_sub_task_chain(
                    chain, {"intent": "ward_room_notification", "params": {}},
                )
                assert decision is not None and decision["_suppressed"] is True
            assert await _settle(
                lambda: caplog.text.count(f"({agent.id}): reason=confabulation_detected path=chain") == 2,
            )
        assert "BF-206: Trust penalty" not in caplog.text
        assert all(call.args[0] != agent.id for call in dm.await_args_list)
    finally:
        await rt.stop()


# --- BF-920's cascade through the booted runtime (A1) ------------------------------------------------


class _SameThreadEpisodes:
    """Stand-in for the service's episodic memory: one episode per agent id, all in one Ward Room thread.

    BF-920 scores a same-thread set of two or more episodes 0.0 (one episode alone scores 1.0,
    ``social_verification.py:189-190``). ``recall`` keeps the real ``k`` cap; the service filters
    the result by agent id.
    """

    def __init__(self, agent_ids: list[str]) -> None:
        self._episodes = [
            Episode(
                id=f"bf921-episode-{index}",
                agent_ids=[agent_id],
                timestamp=1000.0 + 180.0 * index,
                anchors=AnchorFrame(
                    thread_id="bf921-thread", duty_cycle_id="dc", channel="ward_room", channel_id="ship",
                    department="science", participants=["x"], trigger_agent="x", trigger_type="observation",
                    source_origin_id="", artifact_version="",
                ),
            )
            for index, agent_id in enumerate(agent_ids)
        ]

    async def recall(self, query: str, k: int = 5) -> list[Episode]:
        return self._episodes[:k]


@pytest.mark.asyncio
@pytest.mark.parametrize(("peers", "risk"), [(1, "low"), (2, "medium"), (3, "high")], ids=["low", "medium", "high"])
async def test_one_service_cascade_reaches_the_booted_counselor_once(
    tmp_path, monkeypatch, peers: int, risk: str,
) -> None:
    """BF-920's half-chain, closed (A1). The service startup built (``emit_event_fn=runtime._emit_event``), which
    BF-920 leaves as the only emitter of CASCADE_CONFABULATION_DETECTED, is driven through BF-920's Ward Room helper;
    the Counselor that finalize subscribed handles the event once (the removed duplicate would make it twice).
    NATS is off by default, so delivery takes the local path the filter fix repairs."""
    rt = ProbOSRuntime(config=SystemConfig(), data_dir=tmp_path)
    await rt.start()
    try:
        counselor = rt.registry.get_by_pool("counselor")[0]
        service = rt._social_verification
        assert service is not None
        everyone = rt.registry.all()
        crew = [
            a for a in everyone
            if isinstance(a, CognitiveAgent) and a is not counselor and getattr(a, "callsign", "")
            and sum(getattr(b, "callsign", "") == a.callsign for b in everyone) == 1
        ][:peers]
        assert len(crew) == peers  # callsigns are set by startup; a shortfall is a hard stop (section 17)
        author_id, author_callsign = "bf921-author", "Bf921Author"
        body = "the game state is broken and stale"
        monkeypatch.setattr(service, "_episodic", _SameThreadEpisodes([a.id for a in crew] + [author_id]))
        handled = AsyncMock(wraps=counselor._on_cascade_confabulation)
        monkeypatch.setattr(counselor, "_on_cascade_confabulation", handled)
        dm = AsyncMock(return_value=True)
        monkeypatch.setattr(counselor, "_send_therapeutic_dm", dm)
        wire: list[dict[str, Any]] = []
        rt.add_event_listener(wire.append, event_types=[EventType.CASCADE_CONFABULATION_DETECTED])
        peer_matches = [
            {"author_id": a.id, "author_callsign": a.callsign, "timestamp": 100.0 + index}
            for index, a in enumerate(crew)
        ]

        await check_and_alert_cascade_risk(
            service, bridge_alerts=None, ward_room_router=None, author_id=author_id,
            author_callsign=author_callsign, post_body=body, channel_id="ship", peer_matches=peer_matches,
        )

        events = 0 if risk == "low" else 1
        dms = sorted(a.id for a in crew) if risk == "high" else []
        assert await _settle(
            lambda: len(wire) >= events and handled.await_count >= events and dm.await_count >= len(dms),
        )
        await asyncio.sleep(0.2)  # a second delivery (BF-920's removed duplicate emit) would land in this window
        assert len(wire) == events
        assert handled.await_count == events  # one Counselor handling, not two
        assert sorted(call.args[0] for call in dm.await_args_list) == dms
        if events:
            assert wire[0]["data"]["risk_level"] == risk
        else:
            result = await service.check_cascade_risk(
                author_id, author_callsign, body, "ship", peer_matches=peer_matches,
            )
            assert result is not None and result.risk_level == "low"  # low, not none; nothing below medium is emitted
    finally:
        await rt.stop()


# --- the Counselor's callsign handlers against the runtime's AgentRegistry (A1) ------------------------

#: Each Counselor handler that turns a callsign into an agent id, and its payload naming ``who``.
CALLSIGN_EVENTS: dict[str, tuple[EventType, Any]] = {
    "cascade": (EventType.CASCADE_CONFABULATION_DETECTED, lambda who: {
        "risk_level": "high", "affected_agents": [who], "source_agent": "Source", "detail": "",
    }),
    "echo": (EventType.WARD_ROOM_ECHO_DETECTED, lambda who: {
        "source_callsign": "Source", "affected_callsigns": ["Source", who], "chain_length": 3,
        "independence_score": 0.0,
    }),
    "mismatch": (EventType.OBSERVABLE_STATE_MISMATCH, lambda who: {
        "agents_involved": [who], "claims_failed": 1, "ground_truth_summary": "No active games.",
    }),
    "wrong_convergence": (EventType.WRONG_CONVERGENCE_DETECTED, lambda who: {
        "agents": [who], "departments": ["science"], "topic": "bf921", "independence_score": 0.0,
    }),
}


async def _counselor_with_agent_registry() -> CounselorAgent:
    """A Counselor initialized with the registry type production passes (finalize: ``runtime.registry``)."""
    registry = AgentRegistry()
    await registry.register(
        SimpleNamespace(id="agent-kira", agent_type="science_officer", pool="science", callsign="Kira"),
    )
    counselor = _counselor()
    await counselor.initialize(registry=registry)
    return counselor


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("handler", "who"),
    [("echo", "Kira"), ("mismatch", "Kira"), ("wrong_convergence", "Kira"), ("wrong_convergence", "agent-kira")],
    ids=["echo", "mismatch", "wrong_convergence", "wrong_convergence-by-id"],
)
async def test_a_callsign_handler_resolves_through_the_agent_registry(handler: str, who: str, caplog) -> None:
    """The dict lookup (``items()``/``values()``) raised on the AgentRegistry before the first DM."""
    counselor = await _counselor_with_agent_registry()
    event_type, payload = CALLSIGN_EVENTS[handler]

    with caplog.at_level(logging.WARNING, logger="probos.cognitive.counselor"):
        await counselor._on_event_async({"type": event_type.value, "data": payload(who)})

    assert "Counselor event handler failed" not in caplog.text
    counselor._send_therapeutic_dm.assert_awaited_once()
    assert counselor._send_therapeutic_dm.await_args.args[0] == "agent-kira"


@pytest.mark.asyncio
@pytest.mark.parametrize("handler", sorted(CALLSIGN_EVENTS))
async def test_a_callsign_no_agent_carries_is_never_messaged(handler: str, caplog) -> None:
    """The Captain, or an agent that has left: no DM goes to an id no registered agent holds."""
    counselor = await _counselor_with_agent_registry()
    event_type, payload = CALLSIGN_EVENTS[handler]

    with caplog.at_level(logging.WARNING, logger="probos.cognitive.counselor"):
        await counselor._on_event_async({"type": event_type.value, "data": payload("Captain")})

    assert "Counselor event handler failed" not in caplog.text
    counselor._send_therapeutic_dm.assert_not_awaited()


# --- the penalty rule: one test per reason ---------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("reason", REASONS, ids=lambda r: r or "empty")
async def test_no_suppression_reason_carries_a_penalty_or_a_message(reason: str, caplog) -> None:
    counselor = _counselor()
    data = {"agent_id": "agent-x", "callsign": "Wesley", "rejection_reason": reason, "trust_score": 0.3}

    with caplog.at_level(logging.INFO, logger="probos.cognitive.counselor"):
        for _ in range(3):
            await counselor._on_event_async({"type": EventType.CONFABULATION_SUPPRESSED.value, "data": data})

    counselor._trust_network.record_outcome.assert_not_called()
    counselor._send_therapeutic_dm.assert_not_awaited()
    assert caplog.text.count("BF-921: Output suppression recorded for Wesley (agent-x)") == 3
    assert f"reason={reason or 'unknown'} path=chain, 3 in the last hour" in caplog.text


@pytest.mark.asyncio
async def test_the_path_of_a_fallback_suppression_is_recorded(caplog) -> None:
    counselor = _counselor()
    data = {"agent_id": "agent-x", "callsign": "Wesley", "rejection_reason": "confabulation_detected",
            "path": "single_call_fallback"}

    with caplog.at_level(logging.INFO, logger="probos.cognitive.counselor"):
        await counselor._on_confabulation_suppressed(data)

    assert "path=single_call_fallback, 1 in the last hour" in caplog.text


@pytest.mark.asyncio
async def test_the_hourly_count_forgets_older_suppressions(caplog) -> None:
    counselor = _counselor()
    counselor._suppression_history["agent-x"] = [time.time() - 3700.0, time.time() - 3650.0]

    with caplog.at_level(logging.INFO, logger="probos.cognitive.counselor"):
        await counselor._on_confabulation_suppressed({"agent_id": "agent-x", "callsign": "W"})

    assert "1 in the last hour" in caplog.text
    assert len(counselor._suppression_history["agent-x"]) == 1


@pytest.mark.asyncio
async def test_the_counselor_ignores_its_own_suppression(caplog) -> None:
    counselor = _counselor()

    with caplog.at_level(logging.INFO, logger="probos.cognitive.counselor"):
        await counselor._on_confabulation_suppressed({"agent_id": counselor.id, "callsign": "Echo"})

    assert "BF-921: Output suppression recorded" not in caplog.text


@pytest.mark.asyncio
async def test_a_failing_counselor_handler_is_logged_at_warning(caplog) -> None:
    counselor = _counselor()
    counselor._on_trust_update = AsyncMock(side_effect=ValueError("boom"))

    with caplog.at_level(logging.WARNING, logger="probos.cognitive.counselor"):
        await counselor._on_event_async({"type": EventType.TRUST_UPDATE.value, "data": {}})

    assert "Counselor event handler failed for trust_update" in caplog.text


# --- the one emitter -------------------------------------------------------------------------------


def _bare_agent(runtime: Any) -> CognitiveAgent:
    agent = CognitiveAgent.__new__(CognitiveAgent)
    agent.id = "agent-1"
    agent.agent_type = "science_officer"
    agent.callsign = "Kira"
    agent._runtime = runtime
    return agent


def test_the_emitter_names_the_path() -> None:
    runtime = MagicMock()
    _bare_agent(runtime)._emit_output_suppressed("quality_gate", {"intent": "proactive_think"}, path="chain")

    event_type, data = runtime.emit_event.call_args.args
    assert event_type == EventType.CONFABULATION_SUPPRESSED
    assert data["path"] == "chain"
    assert data["rejection_reason"] == "quality_gate"
    assert data["callsign"] == "Kira"


def test_an_emitter_without_a_runtime_warns_and_does_not_raise(caplog) -> None:
    with caplog.at_level(logging.WARNING, logger="probos.cognitive.cognitive_agent"):
        _bare_agent(None)._emit_output_suppressed("quality_gate", {}, path="chain")

    assert "not announced: the agent has no runtime" in caplog.text


def test_a_failing_emit_is_logged_and_does_not_raise(caplog) -> None:
    runtime = MagicMock()
    runtime.emit_event.side_effect = RuntimeError("bus down")

    with caplog.at_level(logging.WARNING, logger="probos.cognitive.cognitive_agent"):
        _bare_agent(runtime)._emit_output_suppressed("quality_gate", {}, path="chain")

    assert "not announced: emit failed" in caplog.text


# --- the woken consumers' first-delivery defects (A2) ------------------------------------------------


@pytest.fixture
def deterministic_embeddings(monkeypatch) -> None:
    """The procedure store's semantic index without a model, as ``tests/test_ad1326_procedure_ledger.py`` builds it."""
    function = BF662EmbeddingFunctionA()
    backend_id = embeddings.get_embedding_backend_id(function)
    monkeypatch.setattr(embeddings, "get_collection_embedding_function", lambda: function)
    monkeypatch.setattr(embeddings, "get_active_embedding_model_name", lambda: function.name())
    monkeypatch.setattr(embeddings, "get_active_embedding_backend_id", lambda: backend_id)


@pytest.mark.asyncio
@pytest.mark.usefixtures("deterministic_embeddings")
@pytest.mark.parametrize("stored", [True, False], ids=["matched", "unmatched"])
async def test_a_delivered_task_completion_queries_the_real_procedure_store(tmp_path, monkeypatch, stored: bool) -> None:
    """AD-532e's reactive trigger called ``find_matching(intent, threshold=...)`` and read the result as a dict. The
    real method takes no ``threshold`` and returns a ranked list, so every delivered completion raised a TypeError,
    logged at DEBUG (A2). The listener is registered as ``startup/dreaming.py`` registers it."""
    procedure = Procedure(
        id="bf921-proc",
        name="Read the log tail",
        description="Read the log tail and report errors",
        steps=[ProcedureStep(step_number=1, action="Read the log tail")],
        intent_types=["read"],
        extraction_date=1_000.0,
    )
    # The store indexes "<name>. <description>. Preconditions: <...>" (procedure_store.py, _chroma_payload); this
    # query is that text, so its cosine distance on the deterministic backend is 0 and its score 1.0.
    intent = f"{procedure.name}. {procedure.description}. Preconditions: "
    store = ProcedureStore(tmp_path / "procedures")
    await store.start()
    try:
        if stored:
            await store.save(procedure)
        metrics = AsyncMock(wraps=store.get_quality_metrics)
        monkeypatch.setattr(store, "get_quality_metrics", metrics)
        engine = DreamingEngine(
            router=MagicMock(spec=HebbianRouter),
            trust_network=MagicMock(spec=TrustNetwork),
            episodic_memory=AsyncMock(),
            config=SystemConfig().dreaming,
            llm_client=AsyncMock(spec=BaseLLMClient),
            procedure_store=store,
        )
        rt = ProbOSRuntime(config=SystemConfig(), data_dir=tmp_path)

        async def on_task_complete(event: dict[str, Any]) -> None:  # startup/dreaming.py's AD-532e listener
            await engine.on_task_execution_complete(event.get("data", event))

        rt.add_event_listener(on_task_complete, event_types=[EventType.TASK_EXECUTION_COMPLETE])
        rt.emit_event(EventType.TASK_EXECUTION_COMPLETE, {  # the payload cognitive_agent.py emits after an LLM task
            "agent_id": "agent-1", "agent_type": "science_officer", "intent_type": intent,
            "success": True, "used_procedure": False, "correlation_id": "",
        })

        if stored:
            assert await _settle(lambda: metrics.await_count == 1)
            assert metrics.await_args.args == ("bf921-proc",)
            assert intent not in engine._extraction_candidates
        else:
            assert await _settle(lambda: intent in engine._extraction_candidates)
            metrics.assert_not_awaited()
    finally:
        await store.stop()


@pytest.mark.asyncio
async def test_concurrent_causes_send_one_agent_one_dm_an_hour(tmp_path, monkeypatch) -> None:
    """Four callsign causes for one agent, delivered together: one DM thread, not four (A2). The sender checked the
    hourly cooldown before its awaits and set it after them, and each listener runs as its own task
    (``runtime._emit_event_local``), so all four passed the check. The runtime is booted; the sender, the DM channel
    and the thread storage are its own, and the wrapper only records each send's result."""
    config = SystemConfig()
    config.ward_room.enabled = True  # the sender's real channel and thread storage need the Ward Room, off in a default boot
    rt = ProbOSRuntime(config=config, data_dir=tmp_path)
    await rt.start()
    try:
        counselor = rt.registry.get_by_pool("counselor")[0]
        everyone = rt.registry.all()
        target = next(
            a for a in everyone
            if isinstance(a, CognitiveAgent) and a is not counselor and getattr(a, "callsign", "")
            and sum(getattr(b, "callsign", "") == a.callsign for b in everyone) == 1
        )
        channel = await rt.ward_room.get_or_create_dm_channel(
            counselor.id, target.id, counselor.callsign, target.callsign,
        )
        threads_before = await rt.ward_room.count_threads(channel.id)
        real_send = counselor._send_therapeutic_dm
        sends: list[tuple[str, bool]] = []

        async def recording_send(agent_id: str, callsign: str, message: str) -> bool:
            sent = await real_send(agent_id, callsign, message)
            sends.append((agent_id, sent))
            return sent

        monkeypatch.setattr(counselor, "_send_therapeutic_dm", recording_send)
        for event_type, payload in CALLSIGN_EVENTS.values():
            rt.emit_event(event_type, payload(target.callsign))

        assert await _settle(lambda: sum(agent_id == target.id for agent_id, _ in sends) >= len(CALLSIGN_EVENTS))
        await asyncio.sleep(0.2)  # a late sender would land in this window
        assert [sent for agent_id, sent in sends if agent_id == target.id].count(True) == 1
        assert await rt.ward_room.count_threads(channel.id) - threads_before == 1
    finally:
        await rt.stop()


async def _counselor_with_ward_room() -> tuple[CounselorAgent, Any]:
    """A Counselor whose Ward Room is built from ``WardRoomService`` (``create_autospec``); its sender is real."""
    ward_room = create_autospec(WardRoomService, instance=True)
    ward_room.get_or_create_dm_channel.return_value = SimpleNamespace(id="dm-channel")
    counselor = CounselorAgent(llm_client=AsyncMock(spec=BaseLLMClient))
    await counselor.initialize(ward_room=ward_room)
    return counselor, ward_room


@pytest.mark.asyncio
async def test_a_dm_that_was_not_sent_gives_the_hour_back() -> None:
    """The hour is reserved before the sender's awaits (A2); a DM the Ward Room refused does not hold it."""
    counselor, ward_room = await _counselor_with_ward_room()
    ward_room.get_or_create_dm_channel.side_effect = [
        RuntimeError("database is locked"), SimpleNamespace(id="dm-channel"),
    ]

    assert await counselor._send_therapeutic_dm("agent-kira", "Kira", "first") is False
    assert await counselor._send_therapeutic_dm("agent-kira", "Kira", "second") is True
    assert ward_room.create_thread.await_count == 1


@pytest.mark.asyncio
async def test_a_sent_dm_keeps_the_hour_when_its_record_fails(monkeypatch) -> None:
    """A DM that was sent holds the hour even if its intervention record then fails, as before A2."""
    counselor, ward_room = await _counselor_with_ward_room()
    monkeypatch.setattr(counselor, "_record_intervention", MagicMock(side_effect=RuntimeError("record failed")))

    assert await counselor._send_therapeutic_dm("agent-kira", "Kira", "first") is False
    assert await counselor._send_therapeutic_dm("agent-kira", "Kira", "second") is False
    assert ward_room.create_thread.await_count == 1


@pytest.mark.asyncio
async def test_a_cancelled_dm_that_started_no_thread_gives_the_hour_back() -> None:
    """A3: a task cancelled during the DM channel lookup has sent nothing (no thread can exist yet), so the hour goes
    back and the cancellation still propagates. A2's give-back ran only for an ``Exception``; ``CancelledError`` is a
    ``BaseException``, so the agent lost an hour of DMs although none was sent."""
    counselor, ward_room = await _counselor_with_ward_room()
    entered = asyncio.Event()

    async def paused_lookup(*args: Any, **kwargs: Any) -> Any:
        entered.set()
        await asyncio.Event().wait()  # never set: the task is cancelled here

    ward_room.get_or_create_dm_channel.side_effect = paused_lookup
    task = asyncio.create_task(counselor._send_therapeutic_dm("agent-kira", "Kira", "cancelled"))
    await asyncio.wait_for(entered.wait(), 2)
    assert "agent-kira" in counselor._dm_cooldowns, "premise: the hour was reserved before the awaits"
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert ward_room.create_thread.await_count == 0, "premise: the cancelled attempt started no thread"

    ward_room.get_or_create_dm_channel.side_effect = None
    assert await counselor._send_therapeutic_dm("agent-kira", "Kira", "retry") is True
    assert ward_room.create_thread.await_count == 1


@pytest.mark.asyncio
async def test_a_cancelled_dm_keeps_the_hour_once_its_thread_was_started() -> None:
    """A3: once ``create_thread`` is awaited, a cancellation may land after its commit (``ward_room/threads.py``
    commits before its later awaits), so the hour stays reserved and a retry sends no second DM. This pins the half
    of the cleanup that a blanket give-back would break."""
    counselor, ward_room = await _counselor_with_ward_room()
    entered = asyncio.Event()

    async def paused_thread(*args: Any, **kwargs: Any) -> Any:
        entered.set()
        await asyncio.Event().wait()  # never set: the task is cancelled here

    ward_room.create_thread.side_effect = paused_thread
    task = asyncio.create_task(counselor._send_therapeutic_dm("agent-kira", "Kira", "cancelled"))
    await asyncio.wait_for(entered.wait(), 2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert ward_room.create_thread.await_count == 1, "premise: the cancelled attempt had started its thread"

    ward_room.create_thread.side_effect = None
    assert await counselor._send_therapeutic_dm("agent-kira", "Kira", "retry") is False
    assert ward_room.create_thread.await_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", ["raises", "cancelled"])
async def test_an_older_attempt_never_releases_a_newer_reservation(fault: str) -> None:
    """A3: an attempt gives back only the reservation it still holds. A real newer reservation comes at least
    ``DM_COOLDOWN_SECONDS`` after the older one (the check refuses anything sooner), so it holds a different clock
    value; the stand-in writes that value directly while the older attempt is in its channel lookup, as a newer
    attempt that reserved and sent would, so nothing depends on the clock's resolution. A2's give-back wrote the
    older attempt's stale value over it, and a retry inside the newer hour sent a second DM."""
    counselor, ward_room = await _counselor_with_ward_room()
    entered = asyncio.Event()
    held: list[float] = []

    async def overtaken_lookup(*args: Any, **kwargs: Any) -> Any:
        held.append(counselor._dm_cooldowns["agent-kira"])
        counselor._dm_cooldowns["agent-kira"] = held[0] + counselor.DM_COOLDOWN_SECONDS  # the newer reservation
        entered.set()
        if fault == "raises":
            raise RuntimeError("database is locked")
        await asyncio.Event().wait()  # never set: the task is cancelled here

    ward_room.get_or_create_dm_channel.side_effect = overtaken_lookup
    task = asyncio.create_task(counselor._send_therapeutic_dm("agent-kira", "Kira", "older"))
    await asyncio.wait_for(entered.wait(), 2)
    if fault == "cancelled":
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    else:
        assert await task is False
    newer = held[0] + counselor.DM_COOLDOWN_SECONDS
    assert newer > held[0] > float("-inf"), "premise: the older attempt held its own, earlier reservation"
    assert counselor._dm_cooldowns["agent-kira"] == newer, "the older attempt released the newer reservation"

    ward_room.get_or_create_dm_channel.side_effect = None
    assert await counselor._send_therapeutic_dm("agent-kira", "Kira", "inside the newer hour") is False
    assert ward_room.create_thread.await_count == 0


@pytest.mark.asyncio
async def test_one_delivered_zone_recovery_is_one_assessment_in_the_reloaded_profile(tmp_path) -> None:
    """AD-506b's handler appended the assessment ``assess_agent`` had already appended: one recovery became two
    entries in the persisted profile that clinical history and drift trends read, against one table row (A2). The
    ``CounselorProfileStore`` is real (SQLite); the profile is reloaded from it."""
    store = CounselorProfileStore(tmp_path)
    await store.start()
    try:
        counselor = CounselorAgent(llm_client=AsyncMock(spec=BaseLLMClient), profile_store=store)
        await counselor.initialize()

        await counselor._on_event_async({"type": EventType.ZONE_RECOVERY.value, "data": {
            "agent_id": "agent-kira", "agent_callsign": "Kira", "old_zone": "amber", "new_zone": "green",
        }})

        reloaded = await store.load_profile("agent-kira")
        rows = await store.get_assessment_history("agent-kira")
        assert reloaded is not None
        assert len(counselor.get_profile("agent-kira").assessments) == 1
        assert len(reloaded.assessments) == 1
        assert len(rows) == 1
        assert reloaded.assessments[0].tier_credit == "self_correction"
        assert rows[0].tier_credit == "self_correction"
        assert reloaded.self_corrections == 1
    finally:
        await store.stop()


@pytest.mark.asyncio
async def test_a_quarantine_recommendation_restricts_and_messages_no_one(caplog) -> None:
    """AD-529's handler restricted the agent from posting and told it so. The restriction blocks every thread and reply
    and nothing lifts it, on a heuristic gauge that is not qualified, so delivery must not apply it (A2). The Ward Room
    and its message store are built from their classes (``create_autospec``)."""
    registry = AgentRegistry()
    await registry.register(
        SimpleNamespace(id="agent-kira", agent_type="science_officer", pool="science", callsign="Kira"),
    )
    ward_room = create_autospec(WardRoomService, instance=True)
    ward_room._messages = create_autospec(MessageStore, instance=True)
    counselor = CounselorAgent(llm_client=AsyncMock(spec=BaseLLMClient))
    await counselor.initialize(registry=registry, ward_room=ward_room)

    with caplog.at_level(logging.WARNING, logger="probos.cognitive.counselor"):
        await counselor._on_event_async({"type": EventType.CONTENT_QUARANTINE_RECOMMENDED.value, "data": {
            "agent_id": "agent-kira", "flags_in_window": 5, "window_seconds": 3600.0,
            "reasons": ["ungrounded_hex_ids"],
        }})

    assert "BF-921: Quarantine criteria met for agent-ki" in caplog.text
    ward_room._messages.set_restriction.assert_not_awaited()
    ward_room.get_or_create_dm_channel.assert_not_awaited()
    ward_room.create_thread.assert_not_awaited()
