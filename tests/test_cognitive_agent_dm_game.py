"""AD-572: Tests for CognitiveAgent DM game context injection."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from probos.cognitive.llm_client import MockLLMClient
from probos.types import LLMRequest, LLMResponse, Priority


def _make_agent(runtime=None, callsign="Lynx"):
    """Create a CognitiveAgent with minimal runtime for game context tests."""
    from probos.cognitive.cognitive_agent import CognitiveAgent

    agent = CognitiveAgent.__new__(CognitiveAgent)
    agent._runtime = runtime
    agent.agent_type = "science_officer"
    agent.id = "test-agent"
    agent._model_id = "test"
    agent._system_prompt_base = ""
    agent._max_tokens = 1000
    agent._callsign = callsign
    # _resolve_callsign() checks self.callsign first
    agent.callsign = callsign
    return agent


class TestHasActiveGame:
    """CognitiveAgent._has_active_game() lightweight check."""

    def test_false_when_no_runtime(self):
        agent = _make_agent(runtime=None)
        assert agent._has_active_game() is False

    def test_false_when_no_recreation_service(self):
        rt = MagicMock(spec=[])
        agent = _make_agent(runtime=rt)
        assert agent._has_active_game() is False

    def test_false_when_no_game(self):
        rt = MagicMock()
        rt.recreation_service = MagicMock()
        rt.recreation_service.get_game_by_player.return_value = None
        rt.callsign_registry.get_callsign.return_value = "Lynx"
        agent = _make_agent(runtime=rt)
        assert agent._has_active_game() is False

    def test_true_when_game_exists(self):
        rt = MagicMock()
        rt.recreation_service = MagicMock()
        rt.recreation_service.get_game_by_player.return_value = {"game_id": "g-1"}
        rt.callsign_registry.get_callsign.return_value = "Lynx"
        agent = _make_agent(runtime=rt)
        assert agent._has_active_game() is True

    def test_false_when_no_callsign(self):
        rt = MagicMock(spec=['recreation_service'])
        rt.recreation_service = MagicMock()
        agent = _make_agent(runtime=rt, callsign="")
        assert agent._has_active_game() is False


class TestBuildActiveGameContext:
    """CognitiveAgent._build_active_game_context() board formatting."""

    def test_returns_none_when_no_game(self):
        rt = MagicMock()
        rt.recreation_service = MagicMock()
        rt.recreation_service.get_game_by_player.return_value = None
        rt.callsign_registry.get_callsign.return_value = "Lynx"
        agent = _make_agent(runtime=rt)
        assert agent._build_active_game_context() is None

    def test_returns_formatted_context(self):
        game = {
            "game_id": "g-123",
            "game_type": "tictactoe",
            "challenger": "Captain",
            "opponent": "Lynx",
            "state": {
                "board": ["X", "", "", "", "O", "", "", "", ""],
                "current_player": "Lynx",
                "status": "in_progress",
            },
            "moves_count": 2,
        }
        rt = MagicMock()
        rt.recreation_service = MagicMock()
        rt.recreation_service.get_game_by_player.return_value = game
        rt.recreation_service.render_board.return_value = " X |   |  \n---+---+---\n   | O |  \n---+---+---\n   |   |  "
        rt.recreation_service.get_valid_moves.return_value = ["1", "2", "3", "5", "6", "7", "8"]
        rt.callsign_registry.get_callsign.return_value = "Lynx"
        agent = _make_agent(runtime=rt)

        ctx = agent._build_active_game_context()
        assert ctx is not None
        assert "YOUR turn" in ctx
        assert "tictactoe" in ctx
        assert "Captain" in ctx  # opponent from Lynx's perspective

    def test_returns_none_when_no_runtime(self):
        agent = _make_agent(runtime=None)
        assert agent._build_active_game_context() is None


class _ControlledRecreationLLM(MockLLMClient):
    def __init__(self, reply: str) -> None:
        super().__init__()
        self.reply = reply
        self.requests: list[LLMRequest] = []
        self.received = asyncio.Event()
        self.release = asyncio.Event()

    async def complete(self, request: LLMRequest, *, priority: Priority = Priority.NORMAL) -> LLMResponse:
        self.requests.append(request)
        self.received.set()
        await self.release.wait()
        return LLMResponse(content=self.reply, model="controlled-recreation", request_id=request.id)


class _RecreationEpisodeStore:
    def __init__(self) -> None:
        self.episodes = []
        self.stored = asyncio.Event()

    async def store(self, episode) -> None:
        self.episodes.append(episode)
        self.stored.set()


class TestRecreationCounselorCrossing:
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("reply", "applied"),
        [
            ("I will take the upper-left corner to develop my position against your center. "
             "The board still leaves several ways for either of us to complete a line. [MOVE 0]", True),
            ("[MOVE 4] [MOVE 0]", False),
            ("[MOVE invalid]", False),
            ("[NO_RESPONSE]", False),
            ("", False),
        ],
        ids=["legal", "first_move_only", "malformed", "no_response", "empty"],
    )
    async def test_real_route_queue_counselor_applies_only_legal_reply(self, reply, applied):
        from fastapi import FastAPI
        from httpx import ASGITransport, AsyncClient

        from probos.activation.dispatcher import Dispatcher
        from probos.cognitive.counselor import CounselorAgent
        from probos.cognitive.queue import AgentCognitiveQueue
        from probos.events import EventType
        from probos.recreation.engine import TicTacToeEngine
        from probos.recreation.service import RecreationService
        from probos.routers.deps import get_runtime, get_ws_broadcast
        from probos.routers.recreation import router

        agents = []
        events = []
        received_intents = []
        model = _ControlledRecreationLLM(reply)
        episodes = _RecreationEpisodeStore()
        registry = SimpleNamespace(
            all=lambda: list(agents),
            get=lambda agent_id: next((agent for agent in agents if agent.id == agent_id), None),
            get_by_pool=lambda pool: [],
        )
        callsigns = SimpleNamespace(
            get_callsign=lambda agent_type: "Counselor" if agent_type == "counselor" else "",
            resolve=lambda callsign: None,
        )
        runtime = SimpleNamespace(
            registry=registry, callsign_registry=callsigns, ward_room=None,
            ontology=None, config=None, episodic_memory=episodes,
            emit_event=lambda kind, data: events.append((kind, data)),
        )
        agent = CounselorAgent(llm_client=model, runtime=runtime)
        agents.append(agent)

        def guard(item, message):
            received_intents.append(item.intent)
            return True, False

        queue = AgentCognitiveQueue(agent_id=agent.id, handler=agent.handle_intent, should_process=guard)
        dispatcher = Dispatcher(
            registry=registry, ontology=None,
            get_queue=lambda agent_id: queue if agent_id == agent.id else None,
            emit_event=runtime.emit_event,
        )
        service = RecreationService(
            dispatcher=dispatcher, callsign_registry=callsigns,
            emit_event_fn=runtime.emit_event,
            actor_exists=lambda agent_id: registry.get(agent_id) is not None,
        )
        runtime.recreation_service = service
        agent.recreation_turns = service.turns
        app = FastAPI()
        app.include_router(router)
        app.dependency_overrides[get_runtime] = lambda: runtime
        app.dependency_overrides[get_ws_broadcast] = lambda: None

        try:
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://recreation.test") as client:
                challenge = await client.post("/api/recreation/challenge", json={"opponent_agent_id": agent.id})
                assert challenge.status_code == 200
                game_id = challenge.json()["game_id"]
                response = await client.post("/api/recreation/move", json={"game_id": game_id, "position": "4"})
                assert response.status_code == 200
                assert response.json()["board"][4] == "X"
                assert response.json()["moves_count"] == 1
                assert response.json()["opponent_turn_status"] == "queued"
                assert queue.pending_count() == 1
                assert model.requests == []
                dispatched = [data for kind, data in events if kind == "task_event_dispatched"]
                assert len(dispatched) == 1
                assert dispatched[0]["accepted"] == 1

                await queue.start()
                await asyncio.wait_for(model.received.wait(), timeout=10)
                assert type(agent) is CounselorAgent
                assert len(received_intents) == 1
                original = received_intents[0]
                assert original.intent == "move_required"
                assert original.params["_task_event_id"] == dispatched[0]["event_id"]
                thinking = (await client.get("/api/recreation/active")).json()["game"]
                assert thinking["opponent_turn_status"] == "thinking"
                assert thinking["moves_count"] == 1
                assert thinking["opponent_agent_id"] == agent.id
                assert thinking["revision"] > response.json()["revision"]
                assert len(model.requests) == 1
                prompt = model.requests[0].system_prompt
                assert "Authoritative current board:" in prompt
                assert "Your symbol is O" in prompt
                assert "Legal moves: 0, 1, 2, 3, 5, 6, 7, 8" in prompt

                model.release.set()
                await asyncio.wait_for(episodes.stored.wait(), timeout=10)
                active = (await client.get("/api/recreation/active")).json()["game"]
                assert active["moves_count"] == (2 if applied else 1)
                assert active["board"][0] == ("O" if applied else "")
                assert active["opponent_turn_status"] == ("idle" if applied else "recoverable")
                assert active["revision"] > thinking["revision"]
                game = service.get_game_by_player("Captain")
                engine = TicTacToeEngine()
                expected = engine.make_move(engine.new_game("Captain", "Counselor"), "Captain", "4")
                if applied:
                    expected = engine.make_move(expected, "Counselor", "0")
                assert game["state"] == expected
                updates = [data for kind, data in events if kind == EventType.GAME_UPDATE]
                assert updates[-1]["board"] == active["board"]
                assert updates[-1]["revision"] == active["revision"]
                assert len(episodes.episodes) == 1
                episode = episodes.episodes[0]
                assert episode.anchors.trigger_type == "move_required"
                outcome = episode.outcomes[0]
                assert outcome["intent"] == "move_required"
                assert outcome["success"] is applied
                assert outcome["recreation"]["intent_id"] == original.id
                assert outcome["recreation"]["event_id"] == dispatched[0]["event_id"]
                assert outcome["response"] == reply

                replay = await agent.handle_intent(original)
                assert replay.success is False
                assert len(model.requests) == 1
                assert game["moves_count"] == (2 if applied else 1)
        finally:
            model.release.set()
            await queue.shutdown()


class TestRecreationTurnDependency:
    @pytest.mark.parametrize("provided", [False, True], ids=["none", "provided"])
    def test_constructor_uses_only_explicit_turn_dependency(self, provided: bool) -> None:
        from probos.cognitive.counselor import CounselorAgent
        from probos.recreation.service import RecreationService

        service = RecreationService()
        dependency = service.turns if provided else None
        agent = CounselorAgent(
            runtime=SimpleNamespace(recreation_service=RecreationService()),
            recreation_turns=dependency,
        )
        assert agent.recreation_turns is dependency

    @pytest.mark.asyncio
    @pytest.mark.parametrize("rebind", [False, True], ids=["unbound", "rebound_during_cognition"])
    async def test_issued_turn_requires_binding_and_keeps_claimed_owner(self, rebind: bool) -> None:
        from probos.activation.dispatcher import DispatchResult
        from probos.cognitive.counselor import CounselorAgent
        from probos.recreation.service import RecreationService
        from probos.types import IntentMessage

        model = _ControlledRecreationLLM(
            "I will take the upper-left corner to develop my position against your center. "
            "The board still leaves several ways for either of us to complete a line. [MOVE 0]",
        )
        episodes = _RecreationEpisodeStore()
        agents = []
        registry = SimpleNamespace(
            all=lambda: list(agents),
            get=lambda agent_id: next((agent for agent in agents if agent.id == agent_id), None),
            get_by_pool=lambda pool: [],
        )
        runtime = SimpleNamespace(
            registry=registry, ontology=None, config=None, ward_room=None,
            episodic_memory=episodes, emit_event=lambda kind, data: None,
            callsign_registry=SimpleNamespace(get_callsign=lambda agent_type: "Counselor"),
        )
        dispatcher = SimpleNamespace(
            dispatch=AsyncMock(return_value=DispatchResult("admission", 1, 1, 0, 0, [])),
        )
        service = RecreationService(dispatcher=dispatcher)
        runtime.recreation_service = service
        agent = CounselorAgent(llm_client=model, runtime=runtime)
        agents.append(agent)
        game = await service.create_game(
            "tictactoe", "Captain", "Counselor", opponent_agent_id=agent.id,
        )
        await service.make_move(game["game_id"], "Captain", "4")
        dispatcher.dispatch.assert_awaited_once()
        event = dispatcher.dispatch.call_args.args[0]
        intent = IntentMessage(
            intent=event.event_type, target_agent_id=agent.id,
            params={
                **event.payload, "_source_type": event.source_type,
                "_source_id": event.source_id, "_task_event_id": event.id,
            },
        )
        assert game["opponent_turn_status"] == "queued"
        assert agent.recreation_turns is None
        if not rebind:
            result = await agent.handle_intent(intent)
            assert result.success is False
            assert model.requests == []
            assert game["moves_count"] == 1
            assert game["opponent_turn_status"] == "queued"
            assert service.turns.claim_turn(intent, agent.id) is not None
            return

        agent.recreation_turns = service.turns
        task = asyncio.create_task(agent.handle_intent(intent))
        try:
            await asyncio.wait_for(model.received.wait(), timeout=10)
            assert game["opponent_turn_status"] == "thinking"
            assert len(model.requests) == 1
            replacement = RecreationService()
            agent.recreation_turns = replacement.turns
            model.release.set()
            result = await asyncio.wait_for(task, timeout=10)
            assert result.success is True
            assert game["moves_count"] == 2
            assert game["state"]["board"][0] == "O"
            assert replacement.get_active_games() == []
            assert agent.recreation_turns is replacement.turns
            assert len(episodes.episodes) == 1
            outcome = episodes.episodes[0].outcomes[0]["recreation"]
            assert outcome["applied"] is True
            assert outcome["event_id"] == event.id
        finally:
            model.release.set()
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)


class _QueuedRecreationLLM(MockLLMClient):
    def __init__(self) -> None:
        super().__init__()
        self.requests: list[LLMRequest] = []
        self.received: asyncio.Queue[LLMRequest] = asyncio.Queue()
        self.responses: asyncio.Queue[str | Exception | None] = asyncio.Queue()
        self.cancelled = asyncio.Event()

    async def complete(self, request: LLMRequest, *, priority: Priority = Priority.NORMAL) -> LLMResponse:
        self.requests.append(request)
        self.received.put_nowait(request)
        try:
            response = await self.responses.get()
        except asyncio.CancelledError:
            self.cancelled.set()
            raise
        if isinstance(response, Exception):
            raise response
        if response is None:
            return None
        return LLMResponse(content=response, model="controlled-recreation", request_id=request.id)


@pytest.fixture
async def counselor_recreation():
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    from probos.activation.dispatcher import Dispatcher
    from probos.cognitive.counselor import CounselorAgent
    from probos.cognitive.queue import AgentCognitiveQueue
    from probos.recreation.service import RecreationService
    from probos.recreation.turns import RecreationTurnSupport
    from probos.routers.deps import get_runtime, get_ws_broadcast
    from probos.routers.recreation import router

    model = _QueuedRecreationLLM()
    episodes = _RecreationEpisodeStore()
    agents, events, received_intents, timers = [], [], [], []
    allow = [True]
    now = [100.0]
    dequeued = asyncio.Event()
    registry = SimpleNamespace(
        all=lambda: list(agents), get_by_pool=lambda pool: [],
        get=lambda actor_id: next((agent for agent in agents if agent.id == actor_id), None),
    )
    callsigns = SimpleNamespace(get_callsign=lambda agent_type: "Counselor", resolve=lambda callsign: None)
    runtime = SimpleNamespace(
        registry=registry, callsign_registry=callsigns, ontology=None, config=None,
        ward_room=None, episodic_memory=episodes,
        emit_event=lambda kind, data: events.append((kind, data)),
    )
    agent = CounselorAgent(llm_client=model, runtime=runtime)
    agents.append(agent)

    def guard(item, message):
        received_intents.append(item.intent)
        dequeued.set()
        return allow[0], False

    def schedule(delay, callback):
        timer = SimpleNamespace(deadline=now[0] + delay, callback=callback, cancel=MagicMock())
        timers.append(timer)
        return timer

    def expire():
        now[0] += 120.0
        for timer in tuple(timers):
            if timer.deadline <= now[0] and not timer.cancel.called:
                timer.callback()

    def factory(games, **dependencies):
        return RecreationTurnSupport(games, **dependencies, schedule_timer=schedule)

    queue = AgentCognitiveQueue(agent_id=agent.id, handler=agent.handle_intent, should_process=guard)
    dispatcher = Dispatcher(
        registry=registry, ontology=None, get_queue=lambda actor_id: queue if actor_id == agent.id else None,
        emit_event=runtime.emit_event,
    )
    service = RecreationService(
        dispatcher=dispatcher, emit_event_fn=runtime.emit_event, callsign_registry=callsigns,
        clock=lambda: now[0], actor_exists=lambda actor_id: registry.get(actor_id) is not None,
        turns_factory=factory,
    )
    runtime.recreation_service = service
    agent.recreation_turns = service.turns
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_runtime] = lambda: runtime
    app.dependency_overrides[get_ws_broadcast] = lambda: None
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://recreation.test") as client:
            challenge = await client.post("/api/recreation/challenge", json={"opponent_agent_id": agent.id})
            assert challenge.status_code == 200
            game = service.get_game_by_player("Captain")
            assert game is not None and game["game_id"] == challenge.json()["game_id"]
            assert type(agent) is CounselorAgent
            yield SimpleNamespace(
                client=client, agent=agent, agents=agents, model=model, episodes=episodes,
                service=service, queue=queue, game=game, events=events, timers=timers,
                allow=allow, dequeued=dequeued, intents=received_intents, expire=expire,
            )
    finally:
        await service.turns.stop()
        model.responses.put_nowait("")
        await queue.shutdown()


def _legal_recreation_reply(position: str) -> str:
    return (
        "I will place my mark here to develop my position against your current board. "
        "I am choosing from the available legal moves and will watch your next turn. "
        f"[MOVE {position}]"
    )


class TestRecreationCounselorRecovery:
    @pytest.mark.asyncio
    async def test_crew_only_event_preserves_legacy_moves_without_new_model_call(self):
        from probos.activation.dispatcher import Dispatcher
        from probos.cognitive.counselor import CounselorAgent
        from probos.recreation.service import RecreationService

        model = MockLLMClient()
        agent = CounselorAgent(llm_client=model)
        received = []

        def enqueue(intent, priority):
            received.append(intent)
            return True

        queue = SimpleNamespace(enqueue=enqueue)
        registry = SimpleNamespace(get=lambda actor_id: agent if actor_id == agent.id else None)
        dispatcher = Dispatcher(
            registry=registry, ontology=None,
            get_queue=lambda actor_id: queue if actor_id == agent.id else None,
        )
        service = RecreationService(dispatcher=dispatcher)
        agent.recreation_turns = service.turns
        try:
            game = await service.create_game("tictactoe", "Lynx", "Counselor", opponent_agent_id=agent.id)
            await service.make_move(game["game_id"], "Lynx", "4")
            assert len(received) == 1
            assert received[0].intent == "move_required"
            assert received[0].target_agent_id == agent.id
            result = await agent.handle_intent(received[0])
            assert result is not None and result.success is False
            assert model.call_count == 0
            assert game["moves_count"] == 1
            await service.make_move(game["game_id"], "Counselor", "0")
            assert game["moves_count"] == 2
            assert game["state"]["board"][0] == "O"
        finally:
            await service.turns.stop()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("scenario", ["model_error", "absent_response", "dequeue_rejected"])
    async def test_real_queue_failure_recovers_only_after_explicit_retry(self, counselor_recreation, scenario):
        fixture = counselor_recreation
        fixture.allow[0] = scenario != "dequeue_rejected"
        response = await fixture.client.post("/api/recreation/move", json={
            "game_id": fixture.game["game_id"], "position": "4", "revision": fixture.game["revision"],
        })
        assert response.status_code == 200
        assert response.json()["opponent_turn_status"] == "queued"
        assert fixture.queue.pending_count() == 1
        assert fixture.model.requests == []
        await fixture.queue.start()
        await asyncio.wait_for(fixture.dequeued.wait(), timeout=10)
        if scenario == "dequeue_rejected":
            assert len(fixture.intents) == 1
            assert fixture.intents[0].intent == "move_required"
            assert fixture.model.requests == []
            assert fixture.game["opponent_turn_status"] == "queued"
            fixture.expire()
            assert fixture.game["opponent_turn_reason"] == "deadline_expired"
        else:
            await asyncio.wait_for(fixture.model.received.get(), timeout=10)
            assert fixture.game["opponent_turn_status"] == "thinking"
            fixture.model.responses.put_nowait(RuntimeError("model offline") if scenario == "model_error" else None)
            await asyncio.wait_for(fixture.episodes.stored.wait(), timeout=10)
            assert fixture.episodes.episodes[0].outcomes[0]["success"] is False
        assert fixture.game["opponent_turn_status"] == "recoverable"
        assert fixture.game["moves_count"] == 1
        assert fixture.game["state"]["board"][0] == ""
        failed_event = fixture.intents[0].params["_task_event_id"]
        before_count = len(fixture.model.requests)
        fixture.allow[0] = True
        fixture.episodes.stored.clear()
        retry = await fixture.client.post("/api/recreation/retry", json={
            "game_id": fixture.game["game_id"], "revision": fixture.game["revision"],
        })
        assert retry.status_code == 200
        assert retry.json()["event_id"] != failed_event
        await asyncio.wait_for(fixture.model.received.get(), timeout=10)
        assert len(fixture.model.requests) == before_count + 1
        fixture.model.responses.put_nowait(_legal_recreation_reply("0"))
        await asyncio.wait_for(fixture.episodes.stored.wait(), timeout=10)
        assert fixture.game["moves_count"] == 2
        assert fixture.game["state"]["board"][0] == "O"
        latest = fixture.episodes.episodes[-1]
        assert latest.anchors.trigger_type == "move_required"
        assert latest.outcomes[0]["success"] is True
        assert latest.outcomes[0]["recreation"]["event_id"] == retry.json()["event_id"]
        assert latest.outcomes[0]["recreation"]["intent_id"] == fixture.intents[-1].id
        assert latest.outcomes[0]["response"] == _legal_recreation_reply("0")

    @pytest.mark.asyncio
    async def test_late_model_reply_cannot_apply_after_retry_but_new_attempt_can(self, counselor_recreation):
        fixture = counselor_recreation
        response = await fixture.client.post("/api/recreation/move", json={"game_id": fixture.game["game_id"], "position": "4"})
        assert response.status_code == 200 and fixture.queue.pending_count() == 1
        await fixture.queue.start()
        await asyncio.wait_for(fixture.model.received.get(), timeout=10)
        original = fixture.intents[0]
        assert fixture.game["opponent_turn_status"] == "thinking"
        fixture.expire()
        assert fixture.game["opponent_turn_reason"] == "deadline_expired"
        retry = await fixture.client.post("/api/recreation/retry", json={
            "game_id": fixture.game["game_id"], "revision": fixture.game["revision"],
        })
        assert retry.status_code == 200
        assert retry.json()["opponent_turn_status"] == "queued"
        assert fixture.queue.pending_count() == 1
        assert len(fixture.model.requests) == 1
        fixture.model.responses.put_nowait(_legal_recreation_reply("0"))
        await asyncio.wait_for(fixture.episodes.stored.wait(), timeout=10)
        assert fixture.game["moves_count"] == 1
        old_outcome = fixture.episodes.episodes[0].outcomes[0]
        assert old_outcome["success"] is False
        assert old_outcome["recreation"]["event_id"] == original.params["_task_event_id"]
        assert old_outcome["recreation"]["intent_id"] == original.id
        await asyncio.wait_for(fixture.model.received.get(), timeout=10)
        fixture.episodes.stored.clear()
        fixture.model.responses.put_nowait(_legal_recreation_reply("1"))
        await asyncio.wait_for(fixture.episodes.stored.wait(), timeout=10)
        assert fixture.game["moves_count"] == 2
        assert fixture.game["state"]["board"][0] == ""
        assert fixture.game["state"]["board"][1] == "O"
        replay = await fixture.agent.handle_intent(original)
        assert replay.success is False
        assert len(fixture.model.requests) == 2
        assert fixture.episodes.episodes[-1].outcomes[0]["recreation"]["event_id"] == retry.json()["event_id"]

    @pytest.mark.asyncio
    @pytest.mark.parametrize("termination", ["forfeit", "removed", "stop"])
    async def test_late_concrete_reply_cannot_revive_unavailable_game_or_actor(self, counselor_recreation, termination):
        fixture = counselor_recreation
        await fixture.client.post("/api/recreation/move", json={"game_id": fixture.game["game_id"], "position": "4"})
        assert fixture.queue.pending_count() == 1
        await fixture.queue.start()
        await asyncio.wait_for(fixture.model.received.get(), timeout=10)
        assert fixture.game["opponent_turn_status"] == "thinking"
        if termination == "forfeit":
            response = await fixture.client.post("/api/recreation/forfeit", json={"game_id": fixture.game["game_id"]})
            assert response.status_code == 200
            assert response.json()["status"] == "forfeited"
        elif termination == "removed":
            fixture.agents.clear()
        else:
            await fixture.service.turns.stop()
        fixture.model.responses.put_nowait(_legal_recreation_reply("0"))
        await asyncio.wait_for(fixture.episodes.stored.wait(), timeout=10)
        assert fixture.game["moves_count"] == 1
        assert fixture.game["state"]["board"][0] == ""
        assert fixture.episodes.episodes[0].outcomes[0]["success"] is False
        assert fixture.episodes.episodes[0].outcomes[0]["recreation"]["intent_id"] == fixture.intents[0].id
        if termination == "forfeit":
            assert fixture.service.get_active_games() == []
        else:
            assert fixture.game["opponent_turn_reason"] == ("actor_unavailable" if termination == "removed" else "service_stopped")

    @pytest.mark.asyncio
    @pytest.mark.parametrize("blocked_store", [False, True])
    async def test_counselor_cancellation_propagates_with_original_episode(self, counselor_recreation, blocked_store):
        fixture = counselor_recreation
        await fixture.client.post("/api/recreation/move", json={"game_id": fixture.game["game_id"], "position": "4"})
        assert fixture.queue.pending_count() == 1
        from probos.types import IntentMessage

        projection = fixture.service.turns.snapshot(fixture.game)
        intent = IntentMessage(intent="move_required", target_agent_id=fixture.agent.id, params={
            "game_id": projection["game_id"], "turn_id": projection["turn_id"],
            "attempt_id": projection["attempt_id"], "_task_event_id": projection["event_id"],
            "_source_id": projection["game_id"], "_source_type": "recreation",
        })
        task = asyncio.create_task(fixture.agent.handle_intent(intent))
        original_store = fixture.episodes.store
        storage_entered = asyncio.Event()

        async def blocked_episode_store(episode):
            storage_entered.set()
            await asyncio.Event().wait()

        try:
            await asyncio.wait_for(fixture.model.received.get(), timeout=10)
            assert fixture.game["opponent_turn_status"] == "thinking"
            await fixture.service.turns.stop()
            if blocked_store:
                fixture.episodes.store = blocked_episode_store
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(task, timeout=2)
            assert fixture.model.cancelled.is_set()
            assert fixture.game["moves_count"] == 1
            assert fixture.service.turns.stopped
            if blocked_store:
                assert storage_entered.is_set()
                assert fixture.episodes.episodes == []
            else:
                assert fixture.episodes.episodes[0].outcomes[0]["recreation"]["intent_id"] == intent.id
        finally:
            fixture.episodes.store = original_store
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)


class TestRecreationCounselorTerminalGames:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("scenario,positions,winner", [
        ("captain_wins", ["0", "3", "1", "4", "2"], "Captain"),
        ("crew_wins", ["0", "3", "1", "4", "8", "5"], "Counselor"),
        ("draw", ["0", "1", "2", "4", "3", "5", "7", "6", "8"], ""),
    ])
    async def test_real_counselor_game_reaches_engine_verified_terminal(self, counselor_recreation, scenario, positions, winner):
        from probos.events import EventType
        from probos.recreation.engine import TicTacToeEngine

        fixture = counselor_recreation
        engine = TicTacToeEngine()
        expected = engine.new_game("Captain", "Counselor")
        await fixture.queue.start()
        for index, position in enumerate(positions):
            player = "Captain" if index % 2 == 0 else "Counselor"
            assert position in engine.get_valid_moves(expected)
            expected = engine.make_move(expected, player, position)
            if player == "Captain":
                response = await fixture.client.post("/api/recreation/move", json={
                    "game_id": fixture.game["game_id"], "position": position, "revision": fixture.game["revision"],
                })
                assert response.status_code == 200
            else:
                await asyncio.wait_for(fixture.model.received.get(), timeout=10)
                assert fixture.game["opponent_turn_status"] == "thinking"
                fixture.episodes.stored.clear()
                fixture.model.responses.put_nowait(_legal_recreation_reply(position))
                await asyncio.wait_for(fixture.episodes.stored.wait(), timeout=10)
                episode = fixture.episodes.episodes[-1]
                assert episode.anchors.trigger_type == "move_required"
                assert episode.outcomes[0]["success"] is True
                assert episode.outcomes[0]["response"] == _legal_recreation_reply(position)
                assert episode.outcomes[0]["recreation"]["intent_id"] == fixture.intents[-1].id
                assert episode.outcomes[0]["recreation"]["event_id"] == fixture.intents[-1].params["_task_event_id"]
            assert fixture.game["state"] == expected
            assert fixture.game["moves_count"] == index + 1
        assert engine.is_finished(expected)
        assert fixture.game["result"] == engine.get_result(expected)
        assert fixture.game["result"]["winner"] == winner
        assert fixture.game["result"]["status"] == ("draw" if scenario == "draw" else "won")
        assert fixture.service.get_active_games() == []
        assert (await fixture.client.get("/api/recreation/active")).json() == {"game": None}
        snapshot = fixture.service.turns.snapshot(fixture.game)
        updates = [data for kind, data in fixture.events if kind == EventType.GAME_UPDATE]
        completed = [data for kind, data in fixture.events if kind == EventType.GAME_COMPLETED]
        assert snapshot == updates[-1]
        assert len(completed) == 1
        assert snapshot["valid_moves"] == []
        assert snapshot["board_text"] == engine.render_board(expected)
        assert len(fixture.model.requests) == len(positions) // 2
        assert len(fixture.episodes.episodes) == len(fixture.model.requests)
        assert all(timer.cancel.called for timer in fixture.timers)
