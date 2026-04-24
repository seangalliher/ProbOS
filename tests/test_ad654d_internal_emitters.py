"""AD-654d: Tests for internal TaskEvent emitters.

Covers 4 emitters:
 1. RecreationService — move_required
 2. Delegation tags — [ASSIGN]/[HANDOFF]
 3. WorkItemStore — work_item_assigned
 4. Ward Room @mention — mention
"""

from __future__ import annotations

import asyncio
import re
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from probos.activation.task_event import TaskEvent, task_event_for_agent
from probos.activation.dispatcher import Dispatcher, DispatchResult
from probos.types import Priority


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_dispatch_result(accepted=1, rejected=0, unroutable=0):
    return DispatchResult(
        event_id=uuid.uuid4().hex,
        target_count=accepted + rejected + unroutable,
        accepted=accepted,
        rejected=rejected,
        unroutable=unroutable,
        agent_ids=["agent-1"],
    )


def _make_dispatcher():
    """Mock dispatcher with dispatch() returning a successful DispatchResult."""
    d = MagicMock()
    d.dispatch = AsyncMock(return_value=_make_dispatch_result())
    return d


def _make_callsign_registry(mapping: dict[str, str] | None = None):
    """Mock CallsignRegistry.  mapping: {callsign: agent_id}."""
    mapping = mapping or {}
    reg = MagicMock()

    def _resolve(callsign):
        if callsign in mapping:
            return {"callsign": callsign, "agent_id": mapping[callsign], "agent_type": callsign.lower()}
        return None
    reg.resolve = MagicMock(side_effect=_resolve)
    return reg


# ───────────────────────────────────────────────────────────────────────────
# 1) RecreationService — move_required
# ───────────────────────────────────────────────────────────────────────────

class TestRecreationMoveRequired:
    """RecreationService emits move_required TaskEvent after a non-finishing move."""

    def _make_service(self, dispatcher=None, callsign_registry=None):
        from probos.recreation.service import RecreationService
        return RecreationService(
            ward_room=MagicMock(),
            records_store=None,
            emit_event_fn=MagicMock(),
            dispatcher=dispatcher,
            callsign_registry=callsign_registry,
        )

    @pytest.mark.asyncio
    async def test_move_required_emitted_after_move(self):
        """make_move() emits TaskEvent targeting next player's agent_id."""
        disp = _make_dispatcher()
        cr = _make_callsign_registry({"Wesley": "agent-wes"})
        svc = self._make_service(dispatcher=disp, callsign_registry=cr)

        game_info = await svc.create_game("tictactoe", "Atlas", "Wesley")
        game_id = game_info["game_id"]
        await svc.make_move(game_id, "Atlas", "0")

        disp.dispatch.assert_called_once()
        event: TaskEvent = disp.dispatch.call_args[0][0]
        assert event.event_type == "move_required"
        assert event.target.agent_id == "agent-wes"
        assert event.priority == Priority.NORMAL
        assert event.source_type == "recreation"

    @pytest.mark.asyncio
    async def test_move_required_not_emitted_on_game_over(self):
        """No TaskEvent when game finishes."""
        disp = _make_dispatcher()
        cr = _make_callsign_registry({"Atlas": "agent-atl", "Wesley": "agent-wes"})
        svc = self._make_service(dispatcher=disp, callsign_registry=cr)

        game_info = await svc.create_game("tictactoe", "Atlas", "Wesley")
        game_id = game_info["game_id"]
        # Play a winning game for X (Atlas) — positions 0,1,2 = top row
        moves = [
            ("Atlas", "0"), ("Wesley", "3"),
            ("Atlas", "1"), ("Wesley", "4"),
            ("Atlas", "2"),  # Atlas wins (top row)
        ]
        for player, move in moves:
            disp.dispatch.reset_mock()
            await svc.make_move(game_id, player, move)

        # The last move (winning) should NOT have dispatched a move_required
        last_event = disp.dispatch.call_args
        if last_event is not None:
            event = last_event[0][0]
            assert event.event_type != "move_required", \
                "move_required should not be emitted on game-ending move"

    @pytest.mark.asyncio
    async def test_move_required_skipped_without_dispatcher(self):
        """Graceful degradation when dispatcher is None."""
        svc = self._make_service(dispatcher=None)
        game_info = await svc.create_game("tictactoe", "Atlas", "Wesley")
        game_id = game_info["game_id"]
        await svc.make_move(game_id, "Atlas", "0")

    @pytest.mark.asyncio
    async def test_move_required_payload_contains_game_context(self):
        """Payload includes game_id, board, valid_moves, opponent, your_symbol."""
        disp = _make_dispatcher()
        cr = _make_callsign_registry({"Wesley": "agent-wes"})
        svc = self._make_service(dispatcher=disp, callsign_registry=cr)

        game_info = await svc.create_game("tictactoe", "Atlas", "Wesley")
        game_id = game_info["game_id"]
        await svc.make_move(game_id, "Atlas", "0")

        event: TaskEvent = disp.dispatch.call_args[0][0]
        payload = event.payload
        assert payload["game_id"] == game_id
        assert payload["game_type"] == "tictactoe"
        assert "board" in payload
        assert "valid_moves" in payload
        assert payload["opponent"] == "Atlas"
        assert "your_symbol" in payload

    @pytest.mark.asyncio
    async def test_move_required_callsign_resolution_failure(self):
        """Unresolvable callsign: no crash, no dispatch."""
        disp = _make_dispatcher()
        cr = _make_callsign_registry({})  # Empty — nothing resolves
        svc = self._make_service(dispatcher=disp, callsign_registry=cr)

        game_info = await svc.create_game("tictactoe", "Atlas", "Wesley")
        game_id = game_info["game_id"]
        await svc.make_move(game_id, "Atlas", "0")

        disp.dispatch.assert_not_called()


# ───────────────────────────────────────────────────────────────────────────
# 2) Delegation Tags — [ASSIGN] / [HANDOFF]
# ───────────────────────────────────────────────────────────────────────────

class TestDelegationTags:
    """Delegation tag parsing in _extract_and_execute_actions()."""

    def _make_runtime(self, dispatcher=None, callsign_registry=None, trust_score=0.8):
        """Mock runtime with dispatcher, callsign_registry, and trust_network."""
        rt = MagicMock()
        rt.dispatcher = dispatcher
        rt.callsign_registry = callsign_registry
        rt.ward_room = MagicMock()
        rt.trust_network = MagicMock()
        rt.trust_network.get_score = MagicMock(return_value=trust_score)
        rt.ward_room.create_post = AsyncMock()
        rt.ward_room.get_channel_by_name = AsyncMock(return_value=None)
        rt.ward_room.get_or_create_dm_channel = AsyncMock()
        rt.ward_room.create_thread = AsyncMock()
        rt.recreation_service = None
        # Mock ward_room_router methods used by _extract_and_execute_actions
        rt.ward_room_router = MagicMock()
        rt.ward_room_router.extract_endorsements = MagicMock(
            side_effect=lambda text: (text, [])
        )
        return rt

    def _make_agent(self, agent_id="agent-sender", callsign="Sender"):
        agent = MagicMock()
        agent.id = agent_id
        agent.callsign = callsign
        agent.agent_type = "test_agent"
        return agent

    async def _run_extract(self, text, rt, agent):
        """Run _extract_and_execute_actions on text."""
        from probos.proactive import ProactiveCognitiveLoop
        loop = ProactiveCognitiveLoop.__new__(ProactiveCognitiveLoop)
        loop._runtime = rt
        loop._config = MagicMock()
        loop._config.max_dm_per_cycle = 3
        cleaned, actions = await loop._extract_and_execute_actions(agent, text)
        return cleaned, actions

    @pytest.mark.asyncio
    async def test_assign_tag_parsed_and_dispatched(self):
        """[ASSIGN @Atlas] text [/ASSIGN] → task_assigned TaskEvent to Atlas."""
        disp = _make_dispatcher()
        cr = _make_callsign_registry({"Atlas": "agent-atlas"})
        rt = self._make_runtime(dispatcher=disp, callsign_registry=cr, trust_score=0.8)
        agent = self._make_agent()

        text = "Some analysis. [ASSIGN @Atlas] investigate anomaly [/ASSIGN] Done."
        cleaned, actions = await self._run_extract(text, rt, agent)

        disp.dispatch.assert_called()
        event: TaskEvent = disp.dispatch.call_args[0][0]
        assert event.event_type == "task_assigned"
        assert event.target.agent_id == "agent-atlas"
        assert event.priority == Priority.NORMAL
        assert event.payload["task_description"] == "investigate anomaly"
        assert any(a["type"] == "assign" for a in actions)

    @pytest.mark.asyncio
    async def test_handoff_tag_parsed_and_dispatched(self):
        """[HANDOFF @Reed] context [/HANDOFF] → task_handoff with CRITICAL priority."""
        disp = _make_dispatcher()
        cr = _make_callsign_registry({"Reed": "agent-reed"})
        rt = self._make_runtime(dispatcher=disp, callsign_registry=cr, trust_score=0.3)
        agent = self._make_agent()

        text = "I'm stuck. [HANDOFF @Reed] taking over analysis [/HANDOFF]"
        cleaned, actions = await self._run_extract(text, rt, agent)

        disp.dispatch.assert_called()
        event: TaskEvent = disp.dispatch.call_args[0][0]
        assert event.event_type == "task_handoff"
        assert event.target.agent_id == "agent-reed"
        assert event.priority == Priority.CRITICAL
        assert event.payload["handoff_context"] == "taking over analysis"
        assert any(a["type"] == "handoff" for a in actions)

    @pytest.mark.asyncio
    async def test_assign_rank_gated(self):
        """Agents below Lieutenant rank: [ASSIGN] tag ignored."""
        disp = _make_dispatcher()
        cr = _make_callsign_registry({"Atlas": "agent-atlas"})
        # trust_score 0.3 → Ensign rank (below Lieutenant)
        rt = self._make_runtime(dispatcher=disp, callsign_registry=cr, trust_score=0.3)
        agent = self._make_agent()

        text = "[ASSIGN @Atlas] do this [/ASSIGN]"
        cleaned, actions = await self._run_extract(text, rt, agent)

        # ASSIGN dispatch should not have happened (rank too low)
        assign_calls = [
            c for c in disp.dispatch.call_args_list
            if c[0][0].event_type == "task_assigned"
        ]
        assert len(assign_calls) == 0

    @pytest.mark.asyncio
    async def test_handoff_no_rank_gate(self):
        """Any rank can use [HANDOFF] — escalation always allowed."""
        disp = _make_dispatcher()
        cr = _make_callsign_registry({"Reed": "agent-reed"})
        # Very low trust → Ensign
        rt = self._make_runtime(dispatcher=disp, callsign_registry=cr, trust_score=0.3)
        agent = self._make_agent()

        text = "[HANDOFF @Reed] need help [/HANDOFF]"
        cleaned, actions = await self._run_extract(text, rt, agent)

        handoff_calls = [
            c for c in disp.dispatch.call_args_list
            if c[0][0].event_type == "task_handoff"
        ]
        assert len(handoff_calls) == 1

    @pytest.mark.asyncio
    async def test_assign_self_skipped(self):
        """Agent assigning to itself is a no-op."""
        disp = _make_dispatcher()
        cr = _make_callsign_registry({"Sender": "agent-sender"})
        rt = self._make_runtime(dispatcher=disp, callsign_registry=cr, trust_score=0.8)
        agent = self._make_agent(agent_id="agent-sender", callsign="Sender")

        text = "[ASSIGN @Sender] do my own thing [/ASSIGN]"
        cleaned, actions = await self._run_extract(text, rt, agent)

        assign_calls = [
            c for c in disp.dispatch.call_args_list
            if c[0][0].event_type == "task_assigned"
        ]
        assert len(assign_calls) == 0

    @pytest.mark.asyncio
    async def test_handoff_self_skipped(self):
        """Agent handing off to itself is a no-op."""
        disp = _make_dispatcher()
        cr = _make_callsign_registry({"Sender": "agent-sender"})
        rt = self._make_runtime(dispatcher=disp, callsign_registry=cr, trust_score=0.8)
        agent = self._make_agent(agent_id="agent-sender", callsign="Sender")

        text = "[HANDOFF @Sender] context [/HANDOFF]"
        cleaned, actions = await self._run_extract(text, rt, agent)

        handoff_calls = [
            c for c in disp.dispatch.call_args_list
            if c[0][0].event_type == "task_handoff"
        ]
        assert len(handoff_calls) == 0

    @pytest.mark.asyncio
    async def test_assign_unknown_callsign_skipped(self):
        """Unresolvable callsign: no crash, no dispatch."""
        disp = _make_dispatcher()
        cr = _make_callsign_registry({})  # Nothing resolves
        rt = self._make_runtime(dispatcher=disp, callsign_registry=cr, trust_score=0.8)
        agent = self._make_agent()

        text = "[ASSIGN @Nobody] do thing [/ASSIGN]"
        cleaned, actions = await self._run_extract(text, rt, agent)

        disp.dispatch.assert_not_called()

    @pytest.mark.asyncio
    async def test_assign_tag_stripped_from_output(self):
        """Tag text removed from agent's post body after extraction."""
        disp = _make_dispatcher()
        cr = _make_callsign_registry({"Atlas": "agent-atlas"})
        rt = self._make_runtime(dispatcher=disp, callsign_registry=cr, trust_score=0.8)
        agent = self._make_agent()

        text = "Analysis complete. [ASSIGN @Atlas] investigate [/ASSIGN] Signing off."
        cleaned, _ = await self._run_extract(text, rt, agent)

        assert "[ASSIGN" not in cleaned
        assert "[/ASSIGN]" not in cleaned
        assert "investigate" not in cleaned
        assert "Analysis complete." in cleaned
        assert "Signing off." in cleaned


# ───────────────────────────────────────────────────────────────────────────
# 3) WorkItemStore — work_item_assigned
# ───────────────────────────────────────────────────────────────────────────

class TestWorkItemAssignment:
    """WorkItemStore emits work_item_assigned TaskEvent on assign."""

    @pytest.fixture
    async def store(self, tmp_path):
        from probos.workforce import WorkItemStore
        db_path = str(tmp_path / "work.db")
        s = WorkItemStore(db_path=db_path, emit_event=MagicMock())
        await s.start()
        yield s
        await s.stop()

    def _register(self, store, resource_id, name="Agent", capabilities=None):
        from probos.workforce import BookableResource
        res = BookableResource(resource_id=resource_id, callsign=name)
        store.register_resource(res)

    @pytest.mark.asyncio
    async def test_work_item_assigned_emits_taskevent(self, store):
        """assign_work_item() emits TaskEvent to assigned agent."""
        disp = _make_dispatcher()
        store.attach_dispatcher(disp)

        # Create work item and bookable resource
        item = await store.create_work_item(title="Fix bug", work_type="task")
        self._register(store, "agent-eng")

        await store.assign_work_item(item.id, "agent-eng", source="captain")

        disp.dispatch.assert_called_once()
        event: TaskEvent = disp.dispatch.call_args[0][0]
        assert event.event_type == "work_item_assigned"
        assert event.target.agent_id == "agent-eng"
        assert event.priority == Priority.NORMAL

    @pytest.mark.asyncio
    async def test_work_item_assigned_payload(self, store):
        """Payload includes work_item_id, title, description, work_type, status, assigned_by."""
        disp = _make_dispatcher()
        store.attach_dispatcher(disp)

        item = await store.create_work_item(
            title="Investigate anomaly",
            description="Sensor readings are off",
            work_type="incident",
        )
        self._register(store, "agent-sci")
        await store.assign_work_item(item.id, "agent-sci", source="bridge")

        event: TaskEvent = disp.dispatch.call_args[0][0]
        payload = event.payload
        assert payload["work_item_id"] == item.id
        assert payload["title"] == "Investigate anomaly"
        assert payload["description"] == "Sensor readings are off"
        assert payload["work_type"] == "incident"
        assert payload["status"] == "scheduled"
        assert payload["assigned_by"] == "bridge"

    @pytest.mark.asyncio
    async def test_work_item_assigned_no_dispatcher(self, store):
        """Graceful degradation when dispatcher is None."""
        # Don't attach dispatcher
        item = await store.create_work_item(title="Task", work_type="task")
        self._register(store, "agent-eng")
        # Should not raise
        await store.assign_work_item(item.id, "agent-eng")

    @pytest.mark.asyncio
    async def test_work_item_claim_no_taskevent(self, store):
        """claim_work_item() does NOT emit TaskEvent (agent already knows)."""
        disp = _make_dispatcher()
        store.attach_dispatcher(disp)

        item = await store.create_work_item(title="Task", work_type="task")
        self._register(store, "agent-eng")
        await store.claim_work_item(item.id, "agent-eng")

        disp.dispatch.assert_not_called()


# ───────────────────────────────────────────────────────────────────────────
# 4) Ward Room @mention — mention TaskEvent
# ───────────────────────────────────────────────────────────────────────────

class TestWardRoomMention:
    """Ward Room emits mention TaskEvent on @mentions in posts and threads."""

    @pytest.fixture
    async def ward_room(self, tmp_path):
        from probos.ward_room.service import WardRoomService
        db_path = str(tmp_path / "wardroom.db")
        svc = WardRoomService(db_path=db_path, emit_event=MagicMock())
        await svc.start()
        yield svc
        await svc.stop()

    @pytest.mark.asyncio
    async def test_mention_emits_taskevent(self, ward_room):
        """Post with @Reed emits TaskEvent(mention) to Reed's agent_id."""
        disp = _make_dispatcher()
        cr = _make_callsign_registry({"Reed": "agent-reed"})
        ward_room.attach_dispatcher(disp, cr)

        ch = await ward_room.create_channel("test", "department", "system")
        thread = await ward_room.create_thread(
            ch.id, "agent-author", "Test Thread", "Initial body",
            author_callsign="Author",
        )
        disp.dispatch.reset_mock()

        await ward_room.create_post(
            thread.id, "agent-author", "Hey @Reed check this out",
            author_callsign="Author",
        )

        disp.dispatch.assert_called_once()
        event: TaskEvent = disp.dispatch.call_args[0][0]
        assert event.event_type == "mention"
        assert event.target.agent_id == "agent-reed"
        assert event.priority == Priority.NORMAL
        assert event.payload["mentioned_by"] == "agent-author"
        assert event.payload["mentioned_by_callsign"] == "Author"

    @pytest.mark.asyncio
    async def test_mention_multiple_agents(self, ward_room):
        """Post with @Reed @Atlas emits one TaskEvent per agent."""
        disp = _make_dispatcher()
        cr = _make_callsign_registry({"Reed": "agent-reed", "Atlas": "agent-atlas"})
        ward_room.attach_dispatcher(disp, cr)

        ch = await ward_room.create_channel("test2", "department", "system")
        thread = await ward_room.create_thread(
            ch.id, "agent-author", "Multi Thread", "body",
            author_callsign="Author",
        )
        disp.dispatch.reset_mock()

        await ward_room.create_post(
            thread.id, "agent-author", "Hey @Reed and @Atlas",
            author_callsign="Author",
        )

        assert disp.dispatch.call_count == 2
        event_types = {c[0][0].event_type for c in disp.dispatch.call_args_list}
        assert event_types == {"mention"}
        target_ids = {c[0][0].target.agent_id for c in disp.dispatch.call_args_list}
        assert target_ids == {"agent-reed", "agent-atlas"}

    @pytest.mark.asyncio
    async def test_mention_self_excluded(self, ward_room):
        """Author mentioning themselves: no TaskEvent for self."""
        disp = _make_dispatcher()
        cr = _make_callsign_registry({"Author": "agent-author"})
        ward_room.attach_dispatcher(disp, cr)

        ch = await ward_room.create_channel("test3", "department", "system")
        thread = await ward_room.create_thread(
            ch.id, "agent-author", "Self Thread", "body",
            author_callsign="Author",
        )
        disp.dispatch.reset_mock()

        await ward_room.create_post(
            thread.id, "agent-author", "I'm @Author talking to myself",
            author_callsign="Author",
        )

        disp.dispatch.assert_not_called()

    @pytest.mark.asyncio
    async def test_mention_unknown_callsign_skipped(self, ward_room):
        """Unresolvable @mention: no crash, no dispatch."""
        disp = _make_dispatcher()
        cr = _make_callsign_registry({})  # Nothing resolves
        ward_room.attach_dispatcher(disp, cr)

        ch = await ward_room.create_channel("test4", "department", "system")
        thread = await ward_room.create_thread(
            ch.id, "agent-author", "Unknown Thread", "body",
            author_callsign="Author",
        )
        disp.dispatch.reset_mock()

        await ward_room.create_post(
            thread.id, "agent-author", "Hey @Nobody are you there?",
            author_callsign="Author",
        )

        disp.dispatch.assert_not_called()

    @pytest.mark.asyncio
    async def test_mention_thread_creation(self, ward_room):
        """Thread creation with @mentions also emits mention TaskEvents."""
        disp = _make_dispatcher()
        cr = _make_callsign_registry({"Reed": "agent-reed"})
        ward_room.attach_dispatcher(disp, cr)

        ch = await ward_room.create_channel("test5", "department", "system")

        await ward_room.create_thread(
            ch.id, "agent-author", "Attention @Reed", "Please review this @Reed",
            author_callsign="Author",
        )

        # Should have dispatched mention(s) — body contains @Reed
        mention_calls = [
            c for c in disp.dispatch.call_args_list
            if c[0][0].event_type == "mention"
        ]
        assert len(mention_calls) >= 1
        assert mention_calls[0][0][0].target.agent_id == "agent-reed"

    @pytest.mark.asyncio
    async def test_mention_no_dispatcher(self, ward_room):
        """Graceful degradation when dispatcher is None."""
        # Don't attach dispatcher
        ch = await ward_room.create_channel("test6", "department", "system")
        # Should not raise
        await ward_room.create_thread(
            ch.id, "agent-author", "No Dispatch", "@Reed ignored",
            author_callsign="Author",
        )


# ───────────────────────────────────────────────────────────────────────────
# 5) End-to-End Delivery
# ───────────────────────────────────────────────────────────────────────────

class TestEndToEndDelivery:
    """TaskEvent dispatched through real Dispatcher reaches cognitive queue."""

    @pytest.mark.asyncio
    async def test_move_required_reaches_cognitive_queue(self):
        """Dispatcher routes move_required to agent's cognitive queue."""
        from probos.cognitive.queue import AgentCognitiveQueue

        # Build a real queue
        received = []

        async def _handler(intent):
            received.append(intent)

        queue = AgentCognitiveQueue(
            agent_id="agent-wes",
            handler=_handler,
            emit_event=MagicMock(),
        )
        await queue.start()

        try:
            # Build a real Dispatcher
            reg = MagicMock()
            agent_mock = MagicMock()
            agent_mock.id = "agent-wes"
            reg.get = MagicMock(return_value=agent_mock)

            dispatcher = Dispatcher(
                registry=reg,
                ontology=MagicMock(),
                get_queue=lambda aid: queue if aid == "agent-wes" else None,
                emit_event=MagicMock(),
            )

            event = task_event_for_agent(
                agent_id="agent-wes",
                source_type="recreation",
                source_id="game-123",
                event_type="move_required",
                priority=Priority.NORMAL,
                payload={"game_id": "game-123", "board": "..."},
            )
            result = await dispatcher.dispatch(event)

            assert result.accepted == 1
            assert result.rejected == 0

            # Give the queue a moment to process
            await asyncio.sleep(0.1)

            # The intent should have been delivered
            assert len(received) == 1
            assert received[0].intent == "move_required"
            assert received[0].params.get("game_id") == "game-123"
        finally:
            await queue.shutdown()

    @pytest.mark.asyncio
    async def test_assign_reaches_cognitive_queue(self):
        """Dispatcher routes task_assigned to target agent's queue."""
        from probos.cognitive.queue import AgentCognitiveQueue

        received = []

        async def _handler(intent):
            received.append(intent)

        queue = AgentCognitiveQueue(
            agent_id="agent-atlas",
            handler=_handler,
            emit_event=MagicMock(),
        )
        await queue.start()

        try:
            reg = MagicMock()
            agent_mock = MagicMock()
            agent_mock.id = "agent-atlas"
            reg.get = MagicMock(return_value=agent_mock)

            dispatcher = Dispatcher(
                registry=reg,
                ontology=MagicMock(),
                get_queue=lambda aid: queue if aid == "agent-atlas" else None,
                emit_event=MagicMock(),
            )

            event = task_event_for_agent(
                agent_id="agent-atlas",
                source_type="agent",
                source_id="agent-sender",
                event_type="task_assigned",
                priority=Priority.NORMAL,
                payload={
                    "from_agent_id": "agent-sender",
                    "from_callsign": "Sender",
                    "task_description": "investigate anomaly",
                },
            )
            result = await dispatcher.dispatch(event)

            assert result.accepted == 1
            await asyncio.sleep(0.1)

            assert len(received) == 1
            assert received[0].intent == "task_assigned"
            assert received[0].params.get("task_description") == "investigate anomaly"
        finally:
            await queue.shutdown()
