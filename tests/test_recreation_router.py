"""Tests for AD-526b: Recreation API router + GAME_UPDATE + forfeit."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from probos.events import EventType
from probos.recreation.service import RecreationService


# ── EventType ────────────────────────────────────────────────────────

class TestGameUpdateEventType:
    """Verify GAME_UPDATE event type exists."""

    def test_game_update_event(self):
        assert hasattr(EventType, "GAME_UPDATE")
        assert EventType.GAME_UPDATE.value == "game_update"


# ── RecreationService.forfeit_game() ─────────────────────────────────

class TestForfeitMethod:
    """RecreationService.forfeit_game()"""

    @pytest.mark.asyncio
    async def test_forfeit_removes_from_active(self):
        """forfeit_game() removes game from active games."""
        svc = RecreationService()
        game = await svc.create_game("tictactoe", "Captain", "Lynx")
        game_id = game["game_id"]

        assert len(svc.get_active_games()) == 1
        await svc.forfeit_game(game_id, "Captain")
        assert len(svc.get_active_games()) == 0

    @pytest.mark.asyncio
    async def test_forfeit_cleans_thread_mapping(self):
        """forfeit_game() removes thread -> game mapping."""
        svc = RecreationService()
        game = await svc.create_game("tictactoe", "Captain", "Lynx", thread_id="t-123")
        game_id = game["game_id"]

        assert svc.get_game_by_thread("t-123") is not None
        await svc.forfeit_game(game_id, "Captain")
        assert svc.get_game_by_thread("t-123") is None

    @pytest.mark.asyncio
    async def test_forfeit_nonexistent_is_noop(self):
        """forfeit_game() does nothing for unknown game IDs."""
        svc = RecreationService()
        await svc.forfeit_game("nonexistent", "Captain")  # should not raise

    @pytest.mark.asyncio
    async def test_forfeit_emits_game_update(self):
        """forfeit_game() emits GAME_UPDATE event."""
        emit_fn = MagicMock()
        svc = RecreationService(emit_event_fn=emit_fn)
        game = await svc.create_game("tictactoe", "Captain", "Lynx")
        game_id = game["game_id"]

        emit_fn.reset_mock()
        await svc.forfeit_game(game_id, "Captain")
        assert emit_fn.called
        updates = [call.args[1] for call in emit_fn.call_args_list if call.args[0] == EventType.GAME_UPDATE]
        assert len(updates) == 1
        assert updates[0]["status"] == "forfeited"
        assert updates[0]["game_id"] == game_id


# ── GAME_UPDATE emission on moves ───────────────────────────────────

class TestGameUpdateEmission:
    """RecreationService emits GAME_UPDATE on moves."""

    @pytest.mark.asyncio
    async def test_move_emits_game_update(self):
        """make_move() emits GAME_UPDATE event with correct board state."""
        emit_fn = MagicMock()
        svc = RecreationService(emit_event_fn=emit_fn)
        game = await svc.create_game("tictactoe", "Captain", "Lynx")
        game_id = game["game_id"]

        await svc.make_move(game_id, "Captain", "4")

        assert emit_fn.called
        call_args = emit_fn.call_args[0]
        assert call_args[0] == EventType.GAME_UPDATE
        event_data = call_args[1]
        assert event_data["game_id"] == game_id
        assert event_data["board"][4] == "X"
        assert event_data["current_player"] == "Lynx"
        assert event_data["status"] == "in_progress"
        assert event_data["last_move"]["player"] == "Captain"
        assert event_data["last_move"]["position"] == "4"

    @pytest.mark.asyncio
    async def test_winning_move_emits_game_update_and_completed(self):
        """Winning move emits both GAME_UPDATE and GAME_COMPLETED."""
        emit_fn = MagicMock()
        svc = RecreationService(emit_event_fn=emit_fn)
        game = await svc.create_game("tictactoe", "Captain", "Lynx")
        gid = game["game_id"]

        # X plays 0,1,2 with O at 3,4
        await svc.make_move(gid, "Captain", "0")
        await svc.make_move(gid, "Lynx", "3")
        await svc.make_move(gid, "Captain", "1")
        await svc.make_move(gid, "Lynx", "4")
        await svc.make_move(gid, "Captain", "2")  # wins top row

        # Should have emitted GAME_UPDATE for each move + GAME_COMPLETED at end
        event_types = [call[0][0] for call in emit_fn.call_args_list]
        assert EventType.GAME_UPDATE in event_types
        assert EventType.GAME_COMPLETED in event_types


# ── Router endpoint validation ──────────────────────────────────────

class TestRecreationRouter:
    """Test recreation router endpoint logic via direct function calls."""

    @pytest.mark.asyncio
    async def test_challenge_endpoint_creates_game(self):
        """challenge_agent() creates game and returns state."""
        from probos.routers.recreation import challenge_agent

        runtime = MagicMock()
        agent = MagicMock()
        agent.id = "test-id"
        agent.agent_type = "science_officer"
        runtime.registry.all.return_value = [agent]
        runtime.callsign_registry.get_callsign.return_value = "Lynx"
        runtime.ward_room = AsyncMock()
        runtime.ward_room.list_channels.return_value = []
        runtime.recreation_service = MagicMock()
        emit = MagicMock()
        service = RecreationService(emit_event_fn=emit)
        runtime.recreation_service.create_game = AsyncMock(wraps=service.create_game)
        runtime.recreation_service.turns = service.turns

        broadcast = MagicMock()
        body = {"opponent_agent_id": "test-id", "game_type": "tictactoe"}

        result = await challenge_agent(body, runtime, broadcast)
        assert result["game_id"] == service.get_active_games()[0]["game_id"]
        assert result["board"] == [""] * 9
        assert result["opponent"] == "Lynx"
        broadcast.assert_not_called()
        updates = [call.args[1] for call in emit.call_args_list if call.args[0] == EventType.GAME_UPDATE]
        assert updates == [result]
        runtime.recreation_service.create_game.assert_awaited_once_with(
            "tictactoe", "Captain", "Lynx", "", opponent_agent_id="test-id",
        )

    @pytest.mark.asyncio
    async def test_challenge_rejects_unknown_agent(self):
        """challenge_agent() returns 404 for unknown agent."""
        from fastapi import HTTPException
        from probos.routers.recreation import challenge_agent

        runtime = MagicMock()
        runtime.registry.all.return_value = []
        runtime.recreation_service = MagicMock()

        with pytest.raises(HTTPException) as exc_info:
            await challenge_agent({"opponent_agent_id": "nope"}, runtime, MagicMock())
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_challenge_rejects_non_crew(self):
        """challenge_agent() returns 400 for non-crew agents."""
        from fastapi import HTTPException
        from probos.routers.recreation import challenge_agent

        runtime = MagicMock()
        agent = MagicMock()
        agent.id = "infra-id"
        agent.agent_type = "vitals_monitor"
        runtime.registry.all.return_value = [agent]
        runtime.callsign_registry.get_callsign.return_value = ""
        runtime.recreation_service = MagicMock()

        with pytest.raises(HTTPException) as exc_info:
            await challenge_agent({"opponent_agent_id": "infra-id"}, runtime, MagicMock())
        assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    async def test_challenge_no_service(self):
        """challenge_agent() returns 503 when service not available."""
        from fastapi import HTTPException
        from probos.routers.recreation import challenge_agent

        runtime = MagicMock(spec=[])

        with pytest.raises(HTTPException) as exc_info:
            await challenge_agent({"opponent_agent_id": "x"}, runtime, MagicMock())
        assert exc_info.value.status_code == 503

    @pytest.mark.asyncio
    async def test_move_endpoint_success(self):
        """make_move() returns updated board state."""
        from probos.routers.recreation import make_move

        runtime = MagicMock()
        runtime.recreation_service = RecreationService()
        game = await runtime.recreation_service.create_game("tictactoe", "Captain", "Lynx")
        runtime.ward_room = None

        result = await make_move({"game_id": game["game_id"], "position": "0"}, runtime)
        assert result["board"][0] == "X"
        assert result["current_player"] == "Lynx"
        assert result["moves_count"] == 1

    @pytest.mark.asyncio
    async def test_terminal_move_response_matches_event_and_retains_ward_room_board(self):
        from probos.routers.recreation import make_move

        emit = MagicMock()
        runtime = MagicMock()
        runtime.ward_room = AsyncMock()
        service = RecreationService(emit_event_fn=emit)
        runtime.recreation_service = service
        game = await service.create_game("tictactoe", "Captain", "Lynx", thread_id="terminal-thread")
        for player, position in [("Captain", "0"), ("Lynx", "3"), ("Captain", "1"), ("Lynx", "4")]:
            await service.make_move(game["game_id"], player, position)
        assert len(service.get_valid_moves(game["game_id"])) == 5

        result = await make_move({"game_id": game["game_id"], "position": "2"}, runtime)

        updates = [call.args[1] for call in emit.call_args_list if call.args[0] == EventType.GAME_UPDATE]
        assert result == updates[-1] == service.turns.snapshot(game)
        assert result["result"]["status"] == "won"
        assert result["board"][:3] == ["X", "X", "X"]
        assert service.get_active_games() == []
        assert game["board_text"] in runtime.ward_room.create_post.call_args.kwargs["body"]
        assert "X | X | X" in game["board_text"]

    @pytest.mark.asyncio
    async def test_move_rejects_invalid(self):
        """make_move() returns 400 for invalid moves."""
        from fastapi import HTTPException
        from probos.routers.recreation import make_move

        runtime = MagicMock()
        runtime.recreation_service = MagicMock()
        runtime.recreation_service.make_move = AsyncMock(side_effect=ValueError("Not your turn"))

        with pytest.raises(HTTPException) as exc_info:
            await make_move({"game_id": "g-1", "position": "0"}, runtime)
        assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    async def test_active_returns_captain_game(self):
        """get_active_game() returns Captain's active game."""
        from probos.routers.recreation import get_active_game

        runtime = MagicMock()
        runtime.recreation_service = MagicMock()
        service = RecreationService()
        game = await service.create_game("tictactoe", "Captain", "Lynx")
        await service.make_move(game["game_id"], "Captain", "0")
        await service.make_move(game["game_id"], "Lynx", "1")
        runtime.recreation_service.get_active_games.return_value = [game]
        runtime.recreation_service.turns = service.turns

        result = await get_active_game(runtime)
        assert result["game"] is not None
        assert result["game"]["game_id"] == game["game_id"]
        assert result["game"]["opponent"] == "Lynx"
        assert result["game"] == service.turns.snapshot(game)

    @pytest.mark.asyncio
    async def test_active_returns_null_when_no_game(self):
        """get_active_game() returns null when no active game."""
        from probos.routers.recreation import get_active_game

        runtime = MagicMock()
        runtime.recreation_service = MagicMock()
        runtime.recreation_service.get_active_games.return_value = []

        result = await get_active_game(runtime)
        assert result["game"] is None

    @pytest.mark.asyncio
    async def test_forfeit_endpoint(self):
        """forfeit_game() delegates to the event-owning service."""
        from probos.routers.recreation import forfeit_game

        runtime = MagicMock()
        runtime.recreation_service = MagicMock()
        runtime.recreation_service.forfeit_game = AsyncMock()

        result = await forfeit_game({"game_id": "g-1"}, runtime)
        assert result["status"] == "forfeited"
        runtime.recreation_service.forfeit_game.assert_called_once_with("g-1", "Captain")


@pytest.fixture
async def recreation_http():
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    from probos.routers.deps import get_runtime, get_ws_broadcast
    from probos.routers.recreation import router

    agent = SimpleNamespace(id="crew-id", agent_type="counselor")
    agents = [agent]
    events = []
    dispatcher = SimpleNamespace(dispatch=AsyncMock(return_value=SimpleNamespace(accepted=0)))
    ward_room = SimpleNamespace(list_channels=AsyncMock(return_value=[]), create_thread=AsyncMock())
    service = RecreationService(
        dispatcher=dispatcher, ward_room=ward_room,
        actor_exists=lambda actor_id: any(actor.id == actor_id for actor in agents),
        emit_event_fn=lambda kind, data: events.append((kind, data)),
    )
    runtime = SimpleNamespace(
        recreation_service=service, ward_room=ward_room,
        registry=SimpleNamespace(all=lambda: agents),
        callsign_registry=SimpleNamespace(get_callsign=lambda agent_type: "Counselor"),
    )
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_runtime] = lambda: runtime
    app.dependency_overrides[get_ws_broadcast] = lambda: None
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://recreation.test") as client:
            yield SimpleNamespace(
                client=client, service=service, dispatcher=dispatcher, runtime=runtime,
                events=events, agents=agents, ward_room=ward_room,
            )
    finally:
        await service.turns.stop()


class TestRecreationParticipantHTTP:
    @pytest.mark.asyncio
    async def test_challenge_participants_match_active_and_event(self, recreation_http):
        fixture = recreation_http
        response = await fixture.client.post("/api/recreation/challenge", json={"opponent_agent_id": "crew-id"})
        assert response.status_code == 200
        snapshot = response.json()
        assert snapshot["participants"] == ["Captain", "Counselor"]
        assert snapshot["opponent_agent_id"] == "crew-id"
        active = await fixture.client.get("/api/recreation/active")
        updates = [data for kind, data in fixture.events if kind == EventType.GAME_UPDATE]
        assert active.status_code == 200
        assert updates and active.json()["game"] == updates[-1] == snapshot

    @pytest.mark.asyncio
    @pytest.mark.parametrize("players", [("Captain", "Counselor"), ("Counselor", "Captain")])
    async def test_active_and_terminal_http_preserve_player_order(self, recreation_http, players):
        fixture = recreation_http
        game = await fixture.service.create_game("tictactoe", *players)
        active = await fixture.client.get("/api/recreation/active")
        assert active.status_code == 200
        snapshot = active.json()["game"]
        assert snapshot["participants"] == list(players)
        updates = [data for kind, data in fixture.events if kind == EventType.GAME_UPDATE]
        assert updates and snapshot == updates[-1] == fixture.service.turns.snapshot(game)
        response = await fixture.client.post("/api/recreation/forfeit", json={
            "game_id": game["game_id"], "revision": snapshot["revision"],
        })
        assert response.status_code == 200
        terminal = response.json()
        assert terminal["status"] == "forfeited"
        assert terminal["participants"] == list(players)
        updates = [data for kind, data in fixture.events if kind == EventType.GAME_UPDATE]
        assert terminal == updates[-1] == fixture.service.turns.snapshot(game)
        absent = await fixture.client.get("/api/recreation/active")
        assert absent.status_code == 200
        assert absent.json() == {"game": None}


class TestRecreationRetryHTTP:
    @pytest.mark.asyncio
    async def test_retry_coalesces_versioned_duplicate_and_matches_active_event(self, recreation_http):
        fixture = recreation_http
        challenge = await fixture.client.post("/api/recreation/challenge", json={"opponent_agent_id": "crew-id"})
        assert challenge.status_code == 200
        initial = challenge.json()
        moved = await fixture.client.post("/api/recreation/move", json={
            "game_id": initial["game_id"], "position": "4", "revision": initial["revision"],
        })
        assert moved.status_code == 200
        failed = moved.json()
        assert failed["opponent_turn_reason"] == "dispatch_rejected"
        assert fixture.dispatcher.dispatch.await_count == 1
        fixture.dispatcher.dispatch.return_value.accepted = 1
        request = {"game_id": initial["game_id"], "revision": failed["revision"]}

        response = await fixture.client.post("/api/recreation/retry", json=request)
        duplicate = await fixture.client.post("/api/recreation/retry", json=request)

        assert response.status_code == duplicate.status_code == 200
        snapshot = response.json()
        assert snapshot == duplicate.json()
        assert snapshot["opponent_turn_status"] == "queued"
        assert snapshot["moves_count"] == 1
        assert snapshot["turn_id"] == failed["turn_id"]
        assert snapshot["attempt_id"] != failed["attempt_id"]
        assert snapshot["event_id"] != failed["event_id"]
        assert snapshot["revision"] > failed["revision"]
        assert fixture.dispatcher.dispatch.await_count == 2
        active = await fixture.client.get("/api/recreation/active")
        updates = [data for kind, data in fixture.events if kind == EventType.GAME_UPDATE]
        assert active.json()["game"] == updates[-1] == snapshot
        assert len([event for event in updates if event["revision"] == snapshot["revision"]]) == 1

    @pytest.mark.asyncio
    async def test_retry_rejects_stale_revision_without_dispatch(self, recreation_http):
        fixture = recreation_http
        game = await fixture.service.create_game("tictactoe", "Captain", "Counselor", opponent_agent_id="crew-id")
        await fixture.service.make_move(game["game_id"], "Captain", "4")
        assert game["opponent_turn_status"] == "recoverable"
        before = fixture.service.turns.snapshot(game)

        response = await fixture.client.post("/api/recreation/retry", json={
            "game_id": game["game_id"], "revision": game["revision"] - 1,
        })

        assert response.status_code == 409
        assert fixture.dispatcher.dispatch.await_count == 1
        assert fixture.service.turns.snapshot(game) == before

    @pytest.mark.asyncio
    @pytest.mark.parametrize("body", [
        {}, {"game_id": "missing"}, {"game_id": None, "revision": 0},
        {"game_id": [], "revision": 0}, {"game_id": "", "revision": 0},
        {"game_id": " game ", "revision": 0}, {"game_id": "game", "revision": None},
        {"game_id": "game", "revision": True}, {"game_id": "game", "revision": "0"},
        {"game_id": "game", "revision": -1}, {"game_id": "game", "revision": 0.0},
    ])
    async def test_retry_rejects_noncanonical_http_body(self, recreation_http, body):
        response = await recreation_http.client.post("/api/recreation/retry", json=body)
        assert response.status_code == 400
        recreation_http.dispatcher.dispatch.assert_not_awaited()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("scenario", ["missing_game", "nonparticipant", "missing_service", "stopped"])
    async def test_retry_rejects_unavailable_or_unauthorized_game(self, recreation_http, scenario):
        fixture = recreation_http
        game_id = "missing"
        if scenario == "nonparticipant":
            game = await fixture.service.create_game("tictactoe", "Lynx", "Counselor")
            game_id = game["game_id"]
        elif scenario == "missing_service":
            fixture.runtime.recreation_service = None
        elif scenario == "stopped":
            await fixture.service.turns.stop()
        response = await fixture.client.post("/api/recreation/retry", json={"game_id": game_id, "revision": 0})
        assert response.status_code == (503 if scenario == "missing_service" else 400)
        fixture.dispatcher.dispatch.assert_not_awaited()


class TestRecreationVersionedHTTP:
    @pytest.mark.asyncio
    async def test_concurrent_challenge_reserves_before_ward_room_await(self, recreation_http):
        fixture = recreation_http
        entered = asyncio.Event()
        release = asyncio.Event()

        async def channels():
            entered.set()
            await release.wait()
            return [SimpleNamespace(id="recreation", name="Recreation")]

        fixture.ward_room.list_channels.side_effect = channels
        fixture.ward_room.create_thread.return_value = SimpleNamespace(id="thread-1")
        request = {"opponent_agent_id": "crew-id"}
        task = asyncio.create_task(fixture.client.post("/api/recreation/challenge", json=request))
        try:
            await asyncio.wait_for(entered.wait(), timeout=1)
            assert not task.done()
            assert len(fixture.service.get_active_games()) == 1
            duplicate = await fixture.client.post("/api/recreation/challenge", json=request)
            assert duplicate.status_code == 409
            fixture.ward_room.list_channels.assert_awaited_once()
            release.set()
            response = await asyncio.wait_for(task, timeout=1)
            assert response.status_code == 200
            snapshot = response.json()
            assert snapshot["thread_id"] == "thread-1"
            assert snapshot["opponent_agent_id"] == "crew-id"
            active = await fixture.client.get("/api/recreation/active")
            updates = [data for kind, data in fixture.events if kind == EventType.GAME_UPDATE]
            assert snapshot == active.json()["game"] == updates[-1]
            assert [update["revision"] for update in updates] == [0, 1]
        finally:
            release.set()
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    @pytest.mark.asyncio
    @pytest.mark.parametrize("operation", ["move", "forfeit"])
    async def test_stale_mutation_rejected_on_later_captain_turn(self, recreation_http, operation):
        fixture = recreation_http
        game = await fixture.service.create_game("tictactoe", "Captain", "Counselor")
        original_revision = game["revision"]
        await fixture.service.make_move(game["game_id"], "Captain", "4")
        await fixture.service.make_move(game["game_id"], "Counselor", "0")
        before = fixture.service.turns.snapshot(game)
        assert before["current_player"] == "Captain"
        response = await fixture.client.post(f"/api/recreation/{operation}", json={
            "game_id": game["game_id"], "position": "1", "revision": original_revision,
        })
        assert response.status_code == 409
        assert fixture.service.turns.snapshot(game) == before

    @pytest.mark.asyncio
    async def test_forfeit_response_is_terminal_event_and_active_becomes_null(self, recreation_http):
        fixture = recreation_http
        game = await fixture.service.create_game("tictactoe", "Captain", "Counselor")
        await fixture.service.make_move(game["game_id"], "Captain", "4")
        response = await fixture.client.post("/api/recreation/forfeit", json={
            "game_id": game["game_id"], "revision": game["revision"],
        })
        assert response.status_code == 200
        snapshot = response.json()
        assert snapshot["status"] == "forfeited"
        assert snapshot["board"][4] == "X"
        assert snapshot["result"]["winner"] == ""
        assert "X" in snapshot["board_text"]
        assert (await fixture.client.get("/api/recreation/active")).json() == {"game": None}
        updates = [data for kind, data in fixture.events if kind == EventType.GAME_UPDATE]
        assert snapshot == updates[-1]
        again = await fixture.client.post("/api/recreation/forfeit", json={"game_id": game["game_id"]})
        assert again.status_code == 200
        assert len([data for kind, data in fixture.events if kind == EventType.GAME_COMPLETED]) == 1

    @pytest.mark.asyncio
    @pytest.mark.parametrize("route,body", [
        ("challenge", {"opponent_agent_id": None}), ("challenge", {"opponent_agent_id": ""}),
        ("challenge", {"opponent_agent_id": " crew-id"}),
        ("challenge", {"opponent_agent_id": "crew-id", "game_type": None}),
        ("challenge", {"opponent_agent_id": "crew-id", "game_type": []}),
        ("move", {"game_id": None, "position": "0"}),
        ("move", {"game_id": "game", "position": 0}),
        ("move", {"game_id": "game", "position": " 0"}),
        ("move", {"game_id": "game", "position": "0", "revision": None}),
        ("forfeit", {"game_id": "game", "revision": False}),
        ("forfeit", {"game_id": ""}),
    ])
    async def test_routes_reject_noncanonical_fields(self, recreation_http, route, body):
        response = await recreation_http.client.post(f"/api/recreation/{route}", json=body)
        assert response.status_code == 400
        assert recreation_http.service.get_active_games() == []
