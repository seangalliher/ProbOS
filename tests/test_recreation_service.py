"""AD-526a: RecreationService tests — game lifecycle, thread routing, event emission."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from probos.recreation.engine import TicTacToeEngine
from probos.recreation.service import RecreationService
from probos.recreation.turns import RecreationGameAccess, RecreationTurns, RecreationTurnSupport


@pytest.fixture
def service():
    """RecreationService with mocked dependencies."""
    return RecreationService(
        ward_room=MagicMock(),
        records_store=AsyncMock(),
        emit_event_fn=MagicMock(),
    )


@pytest.fixture
def bare_service():
    """RecreationService with no dependencies."""
    return RecreationService()


class TestGameRegistration:
    """Verify engine registration."""

    def test_default_engine_registered(self, service):
        assert "tictactoe" in service.get_available_games()

    def test_register_custom_engine(self, service):
        mock_engine = MagicMock()
        mock_engine.game_type = "chess"
        service.register_engine(mock_engine)
        assert "chess" in service.get_available_games()


class TestCreateGame:
    """Verify game creation."""

    @pytest.mark.asyncio
    async def test_create_game_basic(self, service):
        game = await service.create_game("tictactoe", "alice", "bob")
        assert game["game_id"].startswith("game-")
        assert game["game_type"] == "tictactoe"
        assert game["challenger"] == "alice"
        assert game["opponent"] == "bob"
        assert game["moves_count"] == 0

    @pytest.mark.asyncio
    async def test_create_game_with_thread(self, service):
        game = await service.create_game("tictactoe", "alice", "bob", thread_id="th-123")
        assert game["thread_id"] == "th-123"
        assert service.get_game_by_thread("th-123") is not None

    @pytest.mark.asyncio
    async def test_create_game_unknown_type(self, service):
        with pytest.raises(ValueError, match="Unknown game type"):
            await service.create_game("nonexistent_game", "alice", "bob")

    @pytest.mark.asyncio
    async def test_active_games_tracked(self, service):
        await service.create_game("tictactoe", "alice", "bob")
        assert len(service.get_active_games()) == 1


class TestRecreationParticipants:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("players", [("Captain", "Counselor"), ("Counselor", "Captain"), ("Lynx", "Counselor")])
    @pytest.mark.parametrize("status", ["in_progress", "won", "draw", "forfeited"])
    async def test_snapshot_preserves_authoritative_participants_and_event_parity(
        self, players: tuple[str, str], status: str,
    ) -> None:
        from probos.events import EventType

        events: list[tuple[EventType, dict[str, Any]]] = []
        callsigns = MagicMock()
        callsigns.resolve.side_effect = lambda player: None if player == "Captain" else {"agent_id": f"crew-{player}"}
        service = RecreationService(
            emit_event_fn=lambda kind, data: events.append((kind, data)),
            callsign_registry=callsigns,
        )
        try:
            game = await service.create_game("tictactoe", *players)
            assert (game["challenger"], game["opponent"]) == players
            if status == "forfeited":
                await service.forfeit_game(game["game_id"], players[0])
            elif status in ("won", "draw"):
                positions = [0, 3, 1, 4, 2] if status == "won" else [0, 1, 2, 4, 3, 5, 7, 6, 8]
                for index, position in enumerate(positions):
                    await service.make_move(game["game_id"], players[index % 2], str(position))
            snapshot = service.turns.snapshot(game)
            updates = [data for kind, data in events if kind == EventType.GAME_UPDATE]
            assert snapshot["status"] == status
            assert snapshot["participants"] == list(players)
            opponent = players[0] if players[1] == "Captain" else players[1]
            assert snapshot["opponent"] == opponent
            assert snapshot["opponent_agent_id"] == f"crew-{opponent}"
            assert updates and updates[-1] == snapshot
            assert bool(service.get_active_games()) == (status == "in_progress")
            snapshot["participants"][0] = "changed"
            assert service.turns.snapshot(game)["participants"] == list(players)
        finally:
            await service.turns.stop()


class TestMakeMove:
    """Verify move execution and game completion."""

    @pytest.mark.asyncio
    async def test_make_move(self, service):
        game = await service.create_game("tictactoe", "alice", "bob")
        updated = await service.make_move(game["game_id"], "alice", "4")
        assert updated["moves_count"] == 1
        assert updated["state"]["board"][4] == "X"

    @pytest.mark.asyncio
    async def test_game_not_found(self, service):
        with pytest.raises(ValueError, match="not found"):
            await service.make_move("nonexistent", "alice", "0")

    @pytest.mark.asyncio
    async def test_game_completion_cleanup(self, service):
        game = await service.create_game("tictactoe", "a", "b")
        gid = game["game_id"]
        # Play to win: a=0,1,2  b=3,4
        await service.make_move(gid, "a", "0")
        await service.make_move(gid, "b", "3")
        await service.make_move(gid, "a", "1")
        await service.make_move(gid, "b", "4")
        result = await service.make_move(gid, "a", "2")
        assert result["result"]["status"] == "won"
        assert result["result"]["winner"] == "a"
        # Game removed from active
        assert len(service.get_active_games()) == 0

    @pytest.mark.asyncio
    async def test_game_completion_emits_event(self, service):
        game = await service.create_game("tictactoe", "a", "b")
        gid = game["game_id"]
        await service.make_move(gid, "a", "0")
        await service.make_move(gid, "b", "3")
        await service.make_move(gid, "a", "1")
        await service.make_move(gid, "b", "4")
        await service.make_move(gid, "a", "2")
        # AD-526b: now emits GAME_UPDATE per move + GAME_COMPLETED at end
        from probos.events import EventType
        completed_calls = [c for c in service._emit.call_args_list
                           if len(c[0]) >= 1 and c[0][0] == EventType.GAME_COMPLETED]
        assert len(completed_calls) == 1
        assert completed_calls[0][0][1]["game_type"] == "tictactoe"
        assert completed_calls[0][0][1]["result"]["winner"] == "a"

    @pytest.mark.asyncio
    async def test_game_completion_records(self, service):
        game = await service.create_game("tictactoe", "a", "b")
        gid = game["game_id"]
        await service.make_move(gid, "a", "0")
        await service.make_move(gid, "b", "3")
        await service.make_move(gid, "a", "1")
        await service.make_move(gid, "b", "4")
        await service.make_move(gid, "a", "2")
        service._records_store.write_entry.assert_awaited_once()
        call_kwargs = service._records_store.write_entry.call_args[1]
        assert "recreation/games/tictactoe/" in call_kwargs["path"]
        assert "Game Record" in call_kwargs["content"]


class TestThreadRouting:
    """Verify thread-to-game mapping."""

    @pytest.mark.asyncio
    async def test_get_game_by_thread(self, service):
        game = await service.create_game("tictactoe", "a", "b", thread_id="th-1")
        found = service.get_game_by_thread("th-1")
        assert found["game_id"] == game["game_id"]

    @pytest.mark.asyncio
    async def test_get_game_by_unknown_thread(self, service):
        assert service.get_game_by_thread("unknown") is None


class TestBoardRendering:
    """Verify board and valid moves access."""

    @pytest.mark.asyncio
    async def test_render_board(self, service):
        game = await service.create_game("tictactoe", "a", "b")
        board = service.render_board(game["game_id"])
        assert "---+---+---" in board

    def test_render_board_unknown_game(self, service):
        assert service.render_board("nonexistent") == ""

    @pytest.mark.asyncio
    async def test_get_valid_moves(self, service):
        game = await service.create_game("tictactoe", "a", "b")
        moves = service.get_valid_moves(game["game_id"])
        assert len(moves) == 9

    def test_get_valid_moves_unknown_game(self, service):
        assert service.get_valid_moves("nonexistent") == []


class TestNoDependencies:
    """Verify service works without optional dependencies."""

    @pytest.mark.asyncio
    async def test_no_emit_fn(self, bare_service):
        game = await bare_service.create_game("tictactoe", "a", "b")
        gid = game["game_id"]
        await bare_service.make_move(gid, "a", "0")
        await bare_service.make_move(gid, "b", "3")
        await bare_service.make_move(gid, "a", "1")
        await bare_service.make_move(gid, "b", "4")
        result = await bare_service.make_move(gid, "a", "2")
        assert result["result"]["status"] == "won"

    @pytest.mark.asyncio
    async def test_no_records_store(self, bare_service):
        game = await bare_service.create_game("tictactoe", "a", "b")
        gid = game["game_id"]
        await bare_service.make_move(gid, "a", "0")
        await bare_service.make_move(gid, "b", "3")
        await bare_service.make_move(gid, "a", "1")
        await bare_service.make_move(gid, "b", "4")
        # Should not raise even without records store
        await bare_service.make_move(gid, "a", "2")


class TestRecreationTurnComposition:
    @pytest.mark.asyncio
    async def test_factory_receives_initialized_owner_and_dependencies(self) -> None:
        factory_calls: list[tuple[RecreationGameAccess, RecreationTurns]] = []
        dispatcher = MagicMock()
        dispatcher.dispatch = AsyncMock(return_value=MagicMock(accepted=1))
        emit = MagicMock()
        clock = lambda: 100.0
        actor_exists = lambda agent_id: agent_id == "crew-id"

        def factory(
            games: RecreationGameAccess,
            *,
            dispatcher: Any,
            emit_event_fn: Callable[[Any, dict[str, Any]], None] | None,
            clock: Callable[[], float],
            actor_exists: Callable[[str], bool] | None,
        ) -> RecreationTurns:
            assert games.get_active_games() == []
            assert games.render_board("missing") == ""
            assert games.get_valid_moves("missing") == []
            support = RecreationTurnSupport(
                games, dispatcher=dispatcher, emit_event_fn=emit_event_fn,
                clock=clock, actor_exists=actor_exists,
            )
            factory_calls.append((games, support))
            return support

        service = RecreationService(
            dispatcher=dispatcher, emit_event_fn=emit, clock=clock,
            actor_exists=actor_exists, turns_factory=factory,
        )
        assert factory_calls == [(service, service.turns)]
        game = await service.create_game(
            "tictactoe", "Captain", "Counselor", opponent_agent_id="crew-id",
        )
        await service.make_move(game["game_id"], "Captain", "4")
        assert factory_calls == [(service, service.turns)]
        dispatcher.dispatch.assert_awaited_once()
        event = dispatcher.dispatch.call_args.args[0]
        assert event.deadline == 220.0
        assert event.payload["board"] == service.render_board(game["game_id"])
        assert event.payload["valid_moves"] == service.get_valid_moves(game["game_id"])
        assert service.get_active_games()[0] is game
        assert service.turns.turn_projection(game)["event_id"] == event.id
        assert game["opponent_turn_status"] == "queued"
        emit.assert_called()

    def test_factory_failure_propagates(self) -> None:
        factory = MagicMock(side_effect=ValueError("turn support unavailable"))
        with pytest.raises(ValueError, match="turn support unavailable"):
            RecreationService(turns_factory=factory)
        factory.assert_called_once()


class _ControlledTurnTimer:
    def __init__(self, deadline: float, callback: Callable[[], None]) -> None:
        self.deadline = deadline
        self.callback = callback
        self.cancelled = False

    def cancel(self) -> None:
        self.cancelled = True


class _ControlledTurnClock:
    def __init__(self) -> None:
        self.now = 100.0
        self.handles: list[_ControlledTurnTimer] = []

    def schedule(self, delay: float, callback: Callable[[], None]) -> _ControlledTurnTimer:
        handle = _ControlledTurnTimer(self.now + delay, callback)
        self.handles.append(handle)
        return handle

    def advance(self, seconds: float) -> None:
        self.now += seconds
        for handle in tuple(self.handles):
            if not handle.cancelled and handle.deadline <= self.now:
                handle.callback()


class TestRecreationTurnTimers:
    async def _setup_turn(self):
        from probos.activation.dispatcher import DispatchResult
        from probos.types import IntentMessage

        clock = _ControlledTurnClock()
        events = []
        updates = []

        class _Dispatcher:
            async def dispatch(self, event):
                events.append(event)
                return DispatchResult(event.id, 1, 1, 0, 0, ["crew-id"])

        def factory(
            games: RecreationGameAccess, *, dispatcher: Any,
            emit_event_fn: Callable[[Any, dict[str, Any]], None] | None,
            clock: Callable[[], float], actor_exists: Callable[[str], bool] | None,
        ) -> RecreationTurns:
            return RecreationTurnSupport(
                games, dispatcher=dispatcher, emit_event_fn=emit_event_fn,
                clock=clock, actor_exists=actor_exists, schedule_timer=timer_clock.schedule,
            )

        timer_clock = clock
        service = RecreationService(
            dispatcher=_Dispatcher(), clock=lambda: clock.now,
            actor_exists=lambda agent_id: agent_id == "crew-id", turns_factory=factory,
            emit_event_fn=lambda event_type, data: updates.append((event_type, data)),
        )
        game = await service.create_game(
            "tictactoe", "Captain", "Counselor", opponent_agent_id="crew-id",
        )
        await service.make_move(game["game_id"], "Captain", "4")
        assert len(events) == 1
        assert len(clock.handles) == 1
        assert clock.handles[0].deadline == events[0].deadline == 220.0
        assert game["opponent_turn_status"] == "queued"
        event = events[0]
        intent = IntentMessage(
            intent=event.event_type, target_agent_id="crew-id",
            params={
                **event.payload, "_source_type": event.source_type,
                "_source_id": event.source_id, "_task_event_id": event.id,
            },
        )
        return service, game, intent, clock, updates

    @pytest.mark.asyncio
    @pytest.mark.parametrize("received", [False, True])
    async def test_deadline_expires_without_further_queue_callback(self, received: bool) -> None:
        from probos.events import EventType

        service, game, intent, clock, updates = await self._setup_turn()
        try:
            claim = service.turns.claim_turn(intent, "crew-id") if received else None
            assert (claim is not None) is received
            assert game["opponent_turn_status"] == ("thinking" if received else "queued")
            revision = game["revision"]
            clock.advance(119.0)
            assert game["revision"] == revision
            clock.advance(1.0)
            assert game["opponent_turn_status"] == "recoverable"
            assert game["opponent_turn_reason"] == "deadline_expired"
            assert game["revision"] == revision + 1
            assert updates[-1][0] == EventType.GAME_UPDATE
            assert updates[-1][1] == service.turns.snapshot(game)
            assert clock.handles[0].cancelled
            assert service.turns.claim_turn(intent, "crew-id") is None
            if claim is not None:
                assert (await service.turns.complete_turn(claim, "0"))["applied"] is False
            assert game["moves_count"] == 1
            clock.advance(120.0)
            assert game["revision"] == revision + 1
        finally:
            await service.turns.stop()

    @pytest.mark.asyncio
    async def test_early_timer_callback_preserves_original_deadline(self) -> None:
        service, game, _, clock, _ = await self._setup_turn()
        try:
            first = clock.handles[0]
            first.callback()
            assert first.cancelled
            assert len(clock.handles) == 2
            assert clock.handles[1].deadline == first.deadline
            assert game["opponent_turn_status"] == "queued"
            clock.advance(120.0)
            assert game["opponent_turn_reason"] == "deadline_expired"
            assert all(handle.cancelled for handle in clock.handles)
        finally:
            await service.turns.stop()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("finish", ["forfeit", "move", "unusable"])
    async def test_resolution_cancels_timer_and_stale_callback_is_inert(self, finish: str) -> None:
        service, game, intent, clock, _ = await self._setup_turn()
        try:
            handle = clock.handles[0]
            claim = service.turns.claim_turn(intent, "crew-id")
            assert claim is not None
            if finish == "forfeit":
                await service.forfeit_game(game["game_id"], "Captain")
            elif finish == "move":
                assert (await service.turns.complete_turn(claim, "0"))["applied"] is True
            else:
                assert (await service.turns.complete_turn(claim, None))["applied"] is False
            assert handle.cancelled
            snapshot = service.turns.snapshot(game)
            clock.advance(120.0)
            handle.callback()
            assert service.turns.snapshot(game) == snapshot
        finally:
            await service.turns.stop()

    @pytest.mark.asyncio
    async def test_stop_cancels_timer_and_denies_claim_completion_and_mutation(self) -> None:
        service, game, intent, clock, _ = await self._setup_turn()
        try:
            claim = service.turns.claim_turn(intent, "crew-id")
            assert claim is not None
            await service.turns.stop()
            snapshot = service.turns.snapshot(game)
            assert service.turns.stopped is True
            assert snapshot["opponent_turn_reason"] == "service_stopped"
            assert snapshot["attempt_id"] == ""
            assert all(handle.cancelled for handle in clock.handles)
            assert service.turns.claim_turn(intent, "crew-id") is None
            assert (await service.turns.complete_turn(claim, "0"))["applied"] is False
            with pytest.raises(ValueError, match="stopped"):
                await service.make_move(game["game_id"], "Counselor", "0")
            with pytest.raises(ValueError, match="stopped"):
                await service.forfeit_game(game["game_id"], "Captain")
            with pytest.raises(ValueError, match="stopped"):
                await service.create_game("tictactoe", "Captain", "Counselor")
            clock.advance(120.0)
            clock.handles[0].callback()
            await service.turns.stop()
            assert service.turns.snapshot(game) == snapshot
        finally:
            await service.turns.stop()

    @pytest.mark.asyncio
    async def test_stop_before_any_game_is_idempotent_and_starts_no_timer(self) -> None:
        service = RecreationService()
        try:
            await service.turns.stop()
            await service.turns.stop()
            assert service.turns.stopped is True
            assert service.get_active_games() == []
        finally:
            await service.turns.stop()


class TestRecreationTurnClaims:
    async def _setup_turn(self):
        from probos.activation.dispatcher import DispatchResult
        from probos.types import IntentMessage

        events = []
        now = [100.0]
        present = [True]

        class _Dispatcher:
            async def dispatch(self, event):
                events.append(event)
                return DispatchResult(event.id, 1, 1, 0, 0, ["crew-id"])

        service = RecreationService(
            dispatcher=_Dispatcher(), clock=lambda: now[0],
            actor_exists=lambda agent_id: present[0] and agent_id == "crew-id",
        )
        game = await service.create_game(
            "tictactoe", "Captain", "Counselor", opponent_agent_id="crew-id",
        )
        await service.make_move(game["game_id"], "Captain", "4")
        assert len(events) == 1
        event = events[0]
        intent = IntentMessage(
            intent=event.event_type, target_agent_id="crew-id",
            params={
                **event.payload, "_source_type": event.source_type,
                "_source_id": event.source_id, "_task_event_id": event.id,
            },
        )
        return service, game, intent, now, present

    @pytest.mark.asyncio
    async def test_claim_and_completion_apply_once(self):
        service, game, intent, _, _ = await self._setup_turn()
        claim = service.turns.claim_turn(intent, "crew-id")
        assert claim is not None
        assert claim.symbol == "O"
        assert "4" not in claim.valid_moves
        assert game["opponent_turn_status"] == "thinking"
        assert service.turns.claim_turn(intent, "crew-id") is None
        outcome = await service.turns.complete_turn(claim, "0")
        assert outcome["applied"] is True
        assert game["state"]["board"][0] == "O"
        assert (await service.turns.complete_turn(claim, "1"))["applied"] is False
        assert game["moves_count"] == 2

    @pytest.mark.asyncio
    @pytest.mark.parametrize("field", ["_source_type", "_source_id", "_task_event_id", "turn_id", "attempt_id"])
    async def test_claim_rejects_mismatched_envelope(self, field):
        service, game, intent, _, _ = await self._setup_turn()
        intent.params[field] = "forged"
        assert service.turns.claim_turn(intent, "crew-id") is None
        assert game["opponent_turn_status"] == "queued"

    @pytest.mark.asyncio
    async def test_claim_rejects_empty_and_wrong_actor(self):
        service, game, intent, _, _ = await self._setup_turn()
        assert service.turns.claim_turn(None, "crew-id") is None
        assert service.turns.claim_turn(intent, "") is None
        assert service.turns.claim_turn(intent, "other-id") is None
        assert (await service.turns.complete_turn(None, "0"))["applied"] is False
        assert game["moves_count"] == 1

    @pytest.mark.asyncio
    @pytest.mark.parametrize("move", [None, "", "4", "not-a-move"])
    async def test_completion_unusable_move_does_not_change_board(self, move):
        service, game, intent, _, _ = await self._setup_turn()
        claim = service.turns.claim_turn(intent, "crew-id")
        assert claim is not None
        assert (await service.turns.complete_turn(claim, move))["applied"] is False
        assert game["moves_count"] == 1
        assert game["opponent_turn_status"] == "recoverable"

    @pytest.mark.asyncio
    @pytest.mark.parametrize("invalidate", ["deadline", "removed", "legacy_move", "forfeit"])
    async def test_completion_rejects_obsolete_claim(self, invalidate):
        service, game, intent, now, present = await self._setup_turn()
        claim = service.turns.claim_turn(intent, "crew-id")
        assert claim is not None
        if invalidate == "deadline":
            now[0] = claim.deadline
        elif invalidate == "removed":
            present[0] = False
        elif invalidate == "legacy_move":
            await service.make_move(game["game_id"], "Counselor", "1")
        else:
            await service.forfeit_game(game["game_id"], "Captain")
        assert (await service.turns.complete_turn(claim, "0"))["applied"] is False
        assert game["state"]["board"][0] == ""

    @pytest.mark.asyncio
    async def test_claim_rejects_expired_queued_work(self):
        from probos.recreation.turns import TURN_ATTEMPT_TIMEOUT_SECONDS

        service, game, intent, now, _ = await self._setup_turn()
        now[0] += TURN_ATTEMPT_TIMEOUT_SECONDS
        assert service.turns.claim_turn(intent, "crew-id") is None
        assert game["opponent_turn_reason"] == "deadline_expired"


class TestRecreationTerminalLifecycle:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("terminal", ["won", "draw", "forfeited"])
    async def test_terminal_snapshot_retains_board_and_retires_once(self, terminal: str) -> None:
        from probos.events import EventType

        emit = MagicMock()
        service = RecreationService(emit_event_fn=emit)
        game = await service.create_game("tictactoe", "Captain", "Counselor", thread_id="terminal")
        positions = {
            "won": ["0", "3", "1", "4", "2"],
            "draw": ["0", "1", "2", "4", "3", "5", "7", "6", "8"],
            "forfeited": ["4"],
        }[terminal]
        for index, position in enumerate(positions):
            player = "Captain" if index % 2 == 0 else "Counselor"
            await service.make_move(game["game_id"], player, position)
        prior_revision = game["revision"]
        if terminal == "forfeited":
            assert service.get_game_by_thread("terminal") is game
            await service.forfeit_game(game["game_id"], "Captain")
            assert game["revision"] == prior_revision + 1
        else:
            engine = TicTacToeEngine()
            assert engine.is_finished(game["state"])
            assert engine.get_result(game["state"])["status"] == terminal

        snapshot = service.turns.snapshot(game)
        await service.forfeit_game(game["game_id"], "Captain")

        assert service.get_active_games() == []
        assert service.get_game_by_thread("terminal") is None
        assert snapshot["status"] == snapshot["result"]["status"] == terminal
        assert snapshot["board"] == game["state"]["board"]
        assert len(snapshot["board"]) == 9
        assert snapshot["moves_count"] == len(positions)
        assert snapshot["valid_moves"] == []
        assert snapshot["attempt_id"] == snapshot["event_id"] == snapshot["turn_id"] == ""
        updates = [call.args[1] for call in emit.call_args_list if call.args[0] == EventType.GAME_UPDATE]
        completions = [call.args[1] for call in emit.call_args_list if call.args[0] == EventType.GAME_COMPLETED]
        assert updates[-1] == snapshot
        assert len(completions) == 1
        assert completions[0]["result"] == snapshot["result"]
        if terminal == "forfeited":
            assert completions[0]["result"]["winner"] == ""
            assert completions[0]["result"]["forfeited_by"] == "Captain"
        snapshot["board"][0] = "mutated"
        snapshot["result"]["status"] = "mutated"
        assert game["state"]["board"][0] != "mutated"
        assert game["result"]["status"] == terminal

    @pytest.mark.asyncio
    async def test_terminal_cleanup_precedes_record_io_and_forfeit_race(self) -> None:
        from probos.events import EventType

        entered = asyncio.Event()
        release = asyncio.Event()

        class _Records:
            async def write_entry(self, **kwargs: Any) -> None:
                entered.set()
                await release.wait()

        emit = MagicMock()
        service = RecreationService(records_store=_Records(), emit_event_fn=emit)
        game = await service.create_game("tictactoe", "Captain", "Counselor", thread_id="recording")
        for player, position in [("Captain", "0"), ("Counselor", "3"), ("Captain", "1"), ("Counselor", "4")]:
            await service.make_move(game["game_id"], player, position)
        task = asyncio.create_task(service.make_move(game["game_id"], "Captain", "2"))
        try:
            await asyncio.wait_for(entered.wait(), timeout=1)
            assert not task.done()
            assert service.get_active_games() == []
            assert service.get_game_by_thread("recording") is None
            await service.forfeit_game(game["game_id"], "Counselor")
            with pytest.raises(ValueError, match="not found"):
                await service.make_move(game["game_id"], "Counselor", "5")
            completions = [call.args[1] for call in emit.call_args_list if call.args[0] == EventType.GAME_COMPLETED]
            assert len(completions) == 1
            assert completions[0]["result"]["status"] == "won"
        finally:
            release.set()
            await task

    @pytest.mark.asyncio
    async def test_forfeit_invalidates_claim_before_late_completion(self) -> None:
        service, game, intent, _, _ = await TestRecreationTurnClaims()._setup_turn()
        claim = service.turns.claim_turn(intent, "crew-id")
        assert claim is not None
        assert game["opponent_turn_status"] == "thinking"
        await service.forfeit_game(game["game_id"], "Captain")
        terminal = service.turns.snapshot(game)

        outcome = await service.turns.complete_turn(claim, "0")

        assert outcome["applied"] is False
        assert service.turns.claim_turn(intent, "crew-id") is None
        assert service.turns.snapshot(game) == terminal
        assert terminal["board"][4] == "X"
        assert terminal["board"][0] == ""

    @pytest.mark.asyncio
    async def test_update_publication_failure_still_emits_completion(self) -> None:
        from probos.events import EventType

        events: list[tuple[Any, dict[str, Any]]] = []

        def emit(event: Any, data: dict[str, Any]) -> None:
            events.append((event, data))
            if event == EventType.GAME_UPDATE:
                raise RuntimeError("offline subscriber")

        service = RecreationService(emit_event_fn=emit)
        game = await service.create_game("tictactoe", "Captain", "Counselor")
        await service.forfeit_game(game["game_id"], "Captain")

        assert service.get_active_games() == []
        assert [event for event, _ in events].count(EventType.GAME_COMPLETED) == 1
        assert service.turns.snapshot(game)["status"] == "forfeited"

    @pytest.mark.parametrize("record", [None, {}, {"game_id": "", "state": {}}])
    def test_snapshot_rejects_missing_record(self, record: Any) -> None:
        with pytest.raises(ValueError, match="Snapshot requires"):
            RecreationService().turns.snapshot(record)

    @pytest.mark.asyncio
    @pytest.mark.parametrize("game_id,player", [(None, "Captain"), ([], "Captain"), ("", "Captain"), ("missing", None)])
    async def test_forfeit_rejects_noncanonical_input(self, game_id: Any, player: Any) -> None:
        with pytest.raises(ValueError, match="non-empty strings"):
            await RecreationService().forfeit_game(game_id, player)

    @pytest.mark.asyncio
    async def test_forfeit_nonparticipant_keeps_active_game(self) -> None:
        service = RecreationService()
        game = await service.create_game("tictactoe", "Captain", "Counselor")
        with pytest.raises(ValueError, match="not a participant"):
            await service.forfeit_game(game["game_id"], "outsider")
        assert service.get_game_by_player("Captain") is game
        assert game["state"]["status"] == "in_progress"


class TestRecreationRequestBoundaries:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("value", [None, "", " ", " Captain", "Captain ", [], 1, True])
    @pytest.mark.parametrize("field", ["game_type", "challenger", "opponent", "opponent_agent_id"])
    async def test_create_rejects_noncanonical_identity(self, field: str, value: Any) -> None:
        values = dict(game_type="tictactoe", challenger="Captain", opponent="Counselor", opponent_agent_id="crew-id")
        values[field] = value
        service = RecreationService()
        if field == "opponent_agent_id" and value is None:
            game = await service.create_game(**values)
            assert game["opponent_agent_id"] == ""
        else:
            with pytest.raises(ValueError):
                await service.create_game(**values)
            assert service.get_active_games() == []

    @pytest.mark.asyncio
    @pytest.mark.parametrize("thread_id", [None, [], 1, " thread "])
    async def test_create_rejects_noncanonical_thread(self, thread_id: Any) -> None:
        service = RecreationService()
        with pytest.raises(ValueError):
            await service.create_game("tictactoe", "Captain", "Counselor", thread_id)
        assert service.get_active_games() == []

    @pytest.mark.asyncio
    async def test_create_rejects_same_player_and_second_captain_game(self) -> None:
        from probos.recreation.turns import RecreationConflict

        service = RecreationService()
        with pytest.raises(ValueError, match="distinct"):
            await service.create_game("tictactoe", "Captain", "Captain")
        game = await service.create_game("tictactoe", "Captain", "Counselor")
        with pytest.raises(RecreationConflict):
            await service.create_game("chess", "Lynx", "Captain")
        assert service.get_active_games() == [game]

    @pytest.mark.asyncio
    @pytest.mark.parametrize("revision", [None, True, False, -1, "0", 0.0, []])
    @pytest.mark.parametrize("operation", ["move", "forfeit", "validate", "retry"])
    async def test_mutations_reject_noncanonical_revision(self, revision: Any, operation: str) -> None:
        service = RecreationService()
        game = await service.create_game("tictactoe", "Captain", "Counselor")
        before = service.turns.snapshot(game)
        with pytest.raises(ValueError, match="Revision"):
            if operation == "move":
                await service.make_move(game["game_id"], "Captain", "0", expected_revision=revision)
            elif operation == "forfeit":
                await service.forfeit_game(game["game_id"], "Captain", expected_revision=revision)
            elif operation == "retry":
                await service.turns.retry(game["game_id"], "Captain", expected_revision=revision)
            else:
                service.turns.validate_request(game["game_id"], "Captain", expected_revision=revision)
        assert service.turns.snapshot(game) == before

    @pytest.mark.asyncio
    @pytest.mark.parametrize("field", ["game_id", "player", "move"])
    @pytest.mark.parametrize("value", [None, "", " 0", 0, [], True])
    async def test_move_rejects_noncanonical_fields(self, field: str, value: Any) -> None:
        service = RecreationService()
        game = await service.create_game("tictactoe", "Captain", "Counselor")
        values = dict(game_id=game["game_id"], player="Captain", move="0")
        values[field] = value
        with pytest.raises(ValueError):
            await service.make_move(**values)
        assert game["moves_count"] == 0

    @pytest.mark.asyncio
    @pytest.mark.parametrize("player", [None, "", " Captain", "outsider", [], True])
    async def test_validate_request_rejects_nonparticipant_or_invalid_actor(self, player: Any) -> None:
        service = RecreationService()
        game = await service.create_game("tictactoe", "Captain", "Counselor")
        with pytest.raises(ValueError):
            service.turns.validate_request(game["game_id"], player)
        assert game["moves_count"] == 0

    @pytest.mark.asyncio
    async def test_validate_request_preserves_legacy_and_versioned_callers(self) -> None:
        from probos.recreation.turns import RecreationConflict

        service = RecreationService()
        game = await service.create_game("tictactoe", "Captain", "Counselor")
        assert service.turns.validate_request(game["game_id"], "Captain", expected_revision=0) is game
        assert service.turns.validate_request("missing", "Captain") is None
        await service.make_move(game["game_id"], "Captain", "4", expected_revision=0)
        await service.make_move(game["game_id"], "Counselor", "0")
        assert game["state"]["current_player"] == "Captain"
        with pytest.raises(RecreationConflict):
            await service.make_move(game["game_id"], "Captain", "1", expected_revision=0)
        await service.forfeit_game(game["game_id"], "Captain", expected_revision=game["revision"])
        await service.forfeit_game(game["game_id"], "Captain")
        assert game["moves_count"] == 2

    @pytest.mark.asyncio
    async def test_forfeit_while_thread_is_awaited_cannot_recreate_mapping(self) -> None:
        from types import SimpleNamespace

        entered = asyncio.Event()
        release = asyncio.Event()

        async def create_thread(**kwargs: Any) -> Any:
            entered.set()
            await release.wait()
            return SimpleNamespace(id="late-thread")

        ward_room = SimpleNamespace(
            list_channels=AsyncMock(return_value=[SimpleNamespace(name="Recreation", id="rec")]),
            create_thread=create_thread,
        )
        service = RecreationService(ward_room=ward_room)
        task = asyncio.create_task(service.create_game("tictactoe", "Captain", "Counselor"))
        try:
            await asyncio.wait_for(entered.wait(), timeout=1)
            game = service.get_game_by_player("Captain")
            assert game is not None and not task.done()
            await service.forfeit_game(game["game_id"], "Captain")
            terminal = service.turns.snapshot(game)
            release.set()
            assert await asyncio.wait_for(task, timeout=1) is game
            assert service.get_game_by_thread("late-thread") is None
            assert service.get_active_games() == []
            assert service.turns.snapshot(game) == terminal
        finally:
            release.set()
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)


class TestRecreationRetryRecovery:
    @pytest.mark.asyncio
    async def test_retry_freezes_old_attempt_and_coalesces_until_next_recovery(self) -> None:
        from probos.recreation.turns import RecreationConflict
        from probos.types import IntentMessage

        service, game, intent, clock, _ = await TestRecreationTurnTimers()._setup_turn()
        try:
            old_claim = service.turns.claim_turn(intent, "crew-id")
            assert old_claim is not None
            clock.advance(120)
            assert game["opponent_turn_status"] == "recoverable"
            revision = game["revision"]
            first, duplicate = await asyncio.gather(
                service.turns.retry(game["game_id"], "Captain", expected_revision=revision),
                service.turns.retry(game["game_id"], "Captain", expected_revision=revision),
            )
            assert first == duplicate
            assert first["attempt_id"] != old_claim.attempt_id
            assert first["turn_id"] == old_claim.turn_id
            assert len(clock.handles) == 2
            assert service.turns.claim_turn(intent, "crew-id") is None
            assert (await service.turns.complete_turn(old_claim, "0"))["applied"] is False
            current = IntentMessage(intent="move_required", target_agent_id="crew-id", params={
                **intent.params, "attempt_id": first["attempt_id"], "_task_event_id": first["event_id"],
            })
            new_claim = service.turns.claim_turn(current, "crew-id")
            assert new_claim is not None
            thinking = await service.turns.retry(game["game_id"], "Captain", expected_revision=revision)
            assert thinking["opponent_turn_status"] == "thinking"
            assert thinking["attempt_id"] == first["attempt_id"]
            assert len(clock.handles) == 2
            clock.advance(120)
            with pytest.raises(RecreationConflict):
                await service.turns.retry(game["game_id"], "Captain", expected_revision=revision)
            second = await service.turns.retry(game["game_id"], "Captain", expected_revision=game["revision"])
            assert second["attempt_id"] != first["attempt_id"]
            assert (await service.turns.complete_turn(new_claim, "0"))["applied"] is False
            assert game["moves_count"] == 1
        finally:
            await service.turns.stop()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("scenario", ["captain_turn", "pending", "nonparticipant", "stopped", "missing"])
    async def test_retry_requires_active_recoverable_opponent_turn(self, scenario: str) -> None:
        service, game, _, clock, _ = await TestRecreationTurnTimers()._setup_turn()
        try:
            game_id, player = game["game_id"], "Captain"
            if scenario == "captain_turn":
                await service.make_move(game_id, "Counselor", "0")
            elif scenario == "nonparticipant":
                player = "outsider"
            elif scenario == "stopped":
                await service.turns.stop()
            elif scenario == "missing":
                game_id = "missing"
            before = service.turns.snapshot(game)
            with pytest.raises(ValueError):
                await service.turns.retry(game_id, player, expected_revision=game["revision"])
            assert service.turns.snapshot(game) == before
            assert len(clock.handles) == 1
        finally:
            await service.turns.stop()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("scenario", ["removed", "dispatch_error", "dispatcher_absent"])
    async def test_retry_unavailable_dependency_stays_truthful(self, scenario: str) -> None:
        dispatcher = MagicMock()
        dispatcher.dispatch = AsyncMock(return_value=MagicMock(accepted=0))
        present = [True]
        service = RecreationService(
            dispatcher=None if scenario == "dispatcher_absent" else dispatcher,
            actor_exists=lambda actor_id: present[0] and actor_id == "crew-id",
        )
        try:
            game = await service.create_game("tictactoe", "Captain", "Counselor", opponent_agent_id="crew-id")
            await service.make_move(game["game_id"], "Captain", "4")
            assert game["opponent_turn_status"] == "recoverable"
            if scenario == "removed":
                present[0] = False
            elif scenario == "dispatch_error":
                dispatcher.dispatch.side_effect = RuntimeError("offline dispatcher")
            snapshot = await service.turns.retry(game["game_id"], "Captain", expected_revision=game["revision"])
            expected = {"removed": "actor_unavailable", "dispatch_error": "dispatch_failed", "dispatcher_absent": "dispatcher_unavailable"}
            assert snapshot["opponent_turn_reason"] == expected[scenario]
            assert snapshot["moves_count"] == 1
            assert snapshot["board"][0] == ""
        finally:
            await service.turns.stop()

    @pytest.mark.asyncio
    async def test_legacy_move_supersedes_retry_before_old_completion(self) -> None:
        service, game, intent, clock, _ = await TestRecreationTurnTimers()._setup_turn()
        try:
            claim = service.turns.claim_turn(intent, "crew-id")
            assert claim is not None
            clock.advance(120)
            await service.turns.retry(game["game_id"], "Captain", expected_revision=game["revision"])
            await service.make_move(game["game_id"], "Counselor", "1")
            before = service.turns.snapshot(game)
            assert (await service.turns.complete_turn(claim, "0"))["applied"] is False
            assert service.turns.snapshot(game) == before
            assert before["moves_count"] == 2
            assert all(handle.cancelled for handle in clock.handles)
        finally:
            await service.turns.stop()


class TestRecreationSupportBoundaries:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("move", ["00", "+0", "0_0", "\u0660"])
    async def test_move_requires_engine_canonical_legal_representation(self, move: str) -> None:
        service = RecreationService()
        game = await service.create_game("tictactoe", "Captain", "Counselor")
        assert int(move) == 0
        assert "0" in service.get_valid_moves(game["game_id"])
        with pytest.raises(ValueError, match="canonical"):
            await service.make_move(game["game_id"], "Captain", move)
        assert game["moves_count"] == 0

    @pytest.mark.asyncio
    @pytest.mark.parametrize("field,value", [
        ("game_id", []), ("agent_id", None), ("event_id", " event"),
        ("moves_count", True), ("deadline", float("nan")), ("deadline", None),
    ])
    async def test_completion_rejects_malformed_typed_claim(self, field: str, value: Any) -> None:
        from dataclasses import replace

        service, game, intent, _, _ = await TestRecreationTurnTimers()._setup_turn()
        try:
            claim = service.turns.claim_turn(intent, "crew-id")
            assert claim is not None
            forged = replace(claim, **{field: value})
            assert (await service.turns.complete_turn(forged, "0"))["reason"] == "invalid_claim"
            assert game["moves_count"] == 1
            assert (await service.turns.complete_turn(claim, "0"))["applied"] is True
        finally:
            await service.turns.stop()

    @pytest.mark.parametrize("value", [None, "", " text", "text ", [], True])
    def test_canonical_text_rejects_invalid_values(self, value: Any) -> None:
        from probos.recreation.turns import canonical_text

        with pytest.raises(ValueError):
            canonical_text(value, "Test")

    def test_canonical_helpers_accept_only_exact_types(self) -> None:
        from probos.recreation.turns import UNVERSIONED, canonical_text, validate_revision

        class _Text(str):
            pass

        class _Revision(int):
            pass

        assert canonical_text("Captain", "Player") == "Captain"
        assert canonical_text("", "Optional", allow_empty=True) == ""
        validate_revision(0)
        validate_revision(UNVERSIONED)
        with pytest.raises(ValueError):
            canonical_text(_Text("Captain"), "Player")
        with pytest.raises(ValueError):
            validate_revision(_Revision(0))

    @pytest.mark.asyncio
    @pytest.mark.parametrize("field,value", [
        ("game_id", None), ("game_id", ""), ("revision", True),
        ("moves_count", None), ("opponent_agent_id", []), ("state", None),
    ])
    async def test_projection_and_preparation_reject_invalid_records(self, field: str, value: Any) -> None:
        service = RecreationService()
        game = await service.create_game("tictactoe", "Captain", "Counselor")
        invalid = {**game, field: value}
        for method in (service.turns.snapshot, service.turns.turn_projection, service.turns.publish_snapshot):
            with pytest.raises(ValueError):
                method(invalid)
        with pytest.raises(ValueError):
            service.turns.prepare_turn(invalid, finished=False)

    @pytest.mark.asyncio
    async def test_prepare_rejects_forged_owner_and_invalid_flags(self) -> None:
        service, game, _, _, _ = await TestRecreationTurnTimers()._setup_turn()
        try:
            with pytest.raises(ValueError, match="authoritative"):
                service.turns.prepare_turn(dict(game), finished=False)
            with pytest.raises(ValueError, match="boolean"):
                service.turns.prepare_turn(game, finished=None)
            with pytest.raises(ValueError, match="boolean"):
                service.turns.publish_snapshot(game, completed=None)
            with pytest.raises(ValueError, match="terminal"):
                service.turns.publish_snapshot(game, completed=True)
        finally:
            await service.turns.stop()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("value", [None, "", [], " event "])
    async def test_invalidation_rejects_noncanonical_identifiers(self, value: Any) -> None:
        service = RecreationService()
        with pytest.raises(ValueError):
            service.turns.invalidate_turn(value)
        with pytest.raises(ValueError):
            service.turns.fail_queued_turn("missing", value, "dispatch_failed")
        service.turns.invalidate_turn("missing")
        service.turns.fail_queued_turn("missing", "event", "dispatch_failed")

    @pytest.mark.asyncio
    async def test_claim_and_completion_reject_noncanonical_envelope_and_reason(self) -> None:
        service, game, intent, _, _ = await TestRecreationTurnTimers()._setup_turn()
        try:
            assert service.turns.claim_turn(intent, " crew-id ") is None
            original = intent.params["_task_event_id"]
            intent.params["_task_event_id"] = None
            assert service.turns.claim_turn(intent, "crew-id") is None
            intent.params["_task_event_id"] = original
            claim = service.turns.claim_turn(intent, "crew-id")
            assert claim is not None
            assert (await service.turns.complete_turn(claim, None, reason=None))["reason"] == "invalid_reason"
            assert game["moves_count"] == 1
            assert (await service.turns.complete_turn(claim, True))["applied"] is False
            assert game["opponent_turn_status"] == "recoverable"
        finally:
            await service.turns.stop()
