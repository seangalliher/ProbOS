"""Tests for Ward Room agent integration (AD-407b, AD-407d)."""

import time
import pytest
import pytest_asyncio
from unittest.mock import MagicMock, AsyncMock, patch

from probos.runtime import ProbOSRuntime
from probos.substrate.agent import BaseAgent
from probos.ward_room import WardRoomChannel, WardRoomService, _MENTION_PATTERN, extract_mentions
from probos.types import IntentMessage, IntentResult


@pytest_asyncio.fixture
async def ward_room_svc(tmp_path):
    events = []

    def capture_event(event_type, data):
        events.append({"type": event_type, "data": data})

    svc = WardRoomService(db_path=str(tmp_path / "wr.db"), emit_event=capture_event)
    await svc.start()
    svc._captured_events = events
    yield svc
    await svc.stop()


# ---------------------------------------------------------------------------
# Part 3: @mention extraction
# ---------------------------------------------------------------------------

class TestMentionExtraction:
    async def test_mention_extraction(self, ward_room_svc):
        """Extract multiple @mentions from text."""
        result = extract_mentions("Hello @wesley and @worf")
        assert result == ["wesley", "worf"]

    async def test_mention_extraction_empty(self, ward_room_svc):
        """No mentions returns empty list."""
        result = extract_mentions("No mentions here")
        assert result == []

    async def test_thread_event_includes_mentions(self, ward_room_svc):
        """Thread creation event includes extracted mentions."""
        channels = await ward_room_svc.list_channels()
        ch = channels[0]  # 'All Hands' or first default channel
        await ward_room_svc.create_thread(
            channel_id=ch.id,
            author_id="captain",
            title="Question for @wesley",
            body="Hey @wesley, how is warp drive? Also @troi weigh in.",
            author_callsign="Captain",
        )
        # Find the thread_created event
        evt = next(e for e in ward_room_svc._captured_events
                   if e["type"] == "ward_room_thread_created")
        assert "mentions" in evt["data"]
        assert "wesley" in evt["data"]["mentions"]
        assert "troi" in evt["data"]["mentions"]

    async def test_post_event_includes_mentions(self, ward_room_svc):
        """Post creation event includes extracted mentions."""
        channels = await ward_room_svc.list_channels()
        ch = channels[0]
        thread = await ward_room_svc.create_thread(
            channel_id=ch.id, author_id="captain",
            title="Test", body="body", author_callsign="Captain",
        )
        ward_room_svc._captured_events.clear()
        await ward_room_svc.create_post(
            thread_id=thread.id, author_id="captain",
            body="What do you think @troi?",
            author_callsign="Captain",
        )
        evt = next(e for e in ward_room_svc._captured_events
                   if e["type"] == "ward_room_post_created")
        assert "mentions" in evt["data"]
        assert "troi" in evt["data"]["mentions"]


# ---------------------------------------------------------------------------
# Loop prevention
# ---------------------------------------------------------------------------

class TestLoopPrevention:
    async def test_captain_posts_trigger_routing(self):
        """When author_id == 'captain', routing proceeds (does not return early)."""
        runtime = _make_mock_runtime()
        data = {"author_id": "captain", "channel_id": "ch1", "thread_id": "t1"}
        channel = _make_channel("ch1", "ship")
        runtime.ward_room.list_channels = AsyncMock(return_value=[channel])
        runtime.ward_room.get_channel = AsyncMock(return_value=channel)
        runtime.ward_room.get_thread = AsyncMock(return_value={
            "thread": {"title": "Test", "body": "Hello", "channel_id": "ch1"},
            "posts": [],
        })
        agent = _make_agent("agent-1", "architect")
        runtime.registry.all.return_value = [agent]
        runtime.callsign_registry.get_callsign.return_value = "Number One"
        runtime.callsign_registry.resolve.return_value = None
        runtime.intent_bus.send = AsyncMock(return_value=IntentResult(
            intent_id="x", agent_id="agent-1", success=True, result="[NO_RESPONSE]",
        ))

        await runtime.ward_room_router.route_event("ward_room_thread_created", data)
        runtime.intent_bus.send.assert_called()

    async def test_agent_posts_capped_by_depth_limit(self):
        """AD-407d: Agent posts route but are capped by thread depth limit."""
        runtime = _make_mock_runtime()
        # Set thread at max rounds
        runtime._ward_room_thread_rounds["t1"] = 3

        # BF-156: Thread depth check now runs after channel lookup
        channel = _make_channel("ch1", "ship")
        runtime.ward_room.list_channels = AsyncMock(return_value=[channel])
        runtime.ward_room.get_channel = AsyncMock(return_value=channel)
        runtime.ward_room.get_thread = AsyncMock(return_value={
            "thread": {"title": "Test", "body": "Hello", "channel_id": "ch1"},
            "posts": [],
        })

        data = {"author_id": "agent-scotty", "channel_id": "ch1", "thread_id": "t1"}
        await runtime.ward_room_router.route_event("ward_room_post_created", data)
        # At round limit — intent_bus.send never called
        runtime.intent_bus.send.assert_not_called()


# ---------------------------------------------------------------------------
# Rate limiting
# ---------------------------------------------------------------------------

class TestRateLimiting:
    async def test_cooldown_prevents_rapid_response(self):
        """Agent that responded recently is skipped."""
        runtime = _make_mock_runtime()
        runtime._ward_room_cooldowns["agent-1"] = time.time()  # Just responded

        data = {"author_id": "captain", "channel_id": "ch1", "thread_id": "t1"}
        channel = _make_channel("ch1", "ship")
        runtime.ward_room.list_channels = AsyncMock(return_value=[channel])
        runtime.ward_room.get_channel = AsyncMock(return_value=channel)
        runtime.ward_room.get_thread = AsyncMock(return_value={
            "thread": {"title": "Test", "body": "Hello", "channel_id": "ch1"},
            "posts": [],
        })
        agent = _make_agent("agent-1", "architect")
        runtime.registry.all.return_value = [agent]
        runtime.callsign_registry.get_callsign.return_value = "Number One"
        runtime.callsign_registry.resolve.return_value = None

        await runtime.ward_room_router.route_event("ward_room_thread_created", data)
        # Agent on cooldown — intent_bus.send not called
        runtime.intent_bus.send.assert_not_called()


# ---------------------------------------------------------------------------
# Agent response handling
# ---------------------------------------------------------------------------

class TestAgentResponses:
    async def test_no_response_marker_not_posted(self, ward_room_svc):
        """Agent returning [NO_RESPONSE] does not create a Ward Room post."""
        runtime = _make_mock_runtime(ward_room=ward_room_svc)
        channels = await ward_room_svc.list_channels()
        ch = channels[0]
        thread = await ward_room_svc.create_thread(
            channel_id=ch.id, author_id="captain",
            title="Test", body="Hello crew", author_callsign="Captain",
        )

        agent = _make_agent("agent-1", "architect")
        runtime.registry.all.return_value = [agent]
        runtime.callsign_registry.get_callsign.return_value = "Number One"
        runtime.callsign_registry.resolve.return_value = None
        runtime.intent_bus.send = AsyncMock(return_value=IntentResult(
            intent_id="x", agent_id="agent-1", success=True, result="[NO_RESPONSE]",
        ))

        data = {
            "author_id": "captain", "channel_id": ch.id,
            "thread_id": thread.id, "title": "Test",
        }
        await runtime.ward_room_router.route_event("ward_room_thread_created", data)
        # Verify no post was created (thread still has 0 replies)
        detail = await ward_room_svc.get_thread(thread.id)
        assert detail["thread"]["reply_count"] == 0

    async def test_agent_response_posted(self, ward_room_svc):
        """Agent returning a real response creates a Ward Room post."""
        runtime = _make_mock_runtime(ward_room=ward_room_svc)
        channels = await ward_room_svc.list_channels()
        ch = channels[0]
        thread = await ward_room_svc.create_thread(
            channel_id=ch.id, author_id="captain",
            title="Engineering report", body="Status?",
            author_callsign="Captain",
        )

        agent = _make_agent("agent-1", "architect")
        runtime.registry.all.return_value = [agent]
        runtime.registry.get.return_value = agent
        runtime.callsign_registry.get_callsign.return_value = "Number One"
        runtime.callsign_registry.resolve.return_value = None
        runtime.intent_bus.send = AsyncMock(return_value=IntentResult(
            intent_id="x", agent_id="agent-1", success=True,
            result="All systems nominal, Captain.",
        ))

        data = {
            "author_id": "captain", "channel_id": ch.id,
            "thread_id": thread.id, "title": "Engineering report",
        }
        await runtime.ward_room_router.route_event("ward_room_thread_created", data)
        # Verify post WAS created
        detail = await ward_room_svc.get_thread(thread.id)
        assert detail["thread"]["reply_count"] == 1
        assert detail["posts"][0]["body"] == "All systems nominal, Captain."
        assert detail["posts"][0]["author_id"] == "agent-1"


# ---------------------------------------------------------------------------
# Channel-based targeting
# ---------------------------------------------------------------------------

class TestChannelTargeting:
    async def test_department_channel_targets_department(self):
        """Department channel only targets agents in that department."""
        runtime = _make_mock_runtime()
        channel = _make_channel("ch-eng", "department", department="engineering")

        eng_agent = _make_agent("agent-eng", "engineering_officer")
        sci_agent = _make_agent("agent-sci", "architect")
        runtime.registry.all.return_value = [eng_agent, sci_agent]
        runtime.callsign_registry.get_callsign.side_effect = lambda t: {
            "engineering_officer": "LaForge",
            "architect": "NumberOne",
        }.get(t, "")

        with patch("probos.cognitive.standing_orders.get_department") as mock_dept:
            mock_dept.side_effect = lambda t: {
                "engineering_officer": "engineering",
                "architect": "science",
            }.get(t)

            targets = runtime.ward_room_router.find_targets(
                channel=channel, author_id="captain",
            )

        assert "agent-eng" in targets
        assert "agent-sci" not in targets

    async def test_ship_channel_targets_all_crew(self):
        """Ship-wide channel targets all crew agents."""
        runtime = _make_mock_runtime()
        channel = _make_channel("ch-all", "ship")

        agents = [
            _make_agent("a1", "architect"),
            _make_agent("a2", "counselor"),
            _make_agent("a3", "scout"),
        ]
        runtime.registry.all.return_value = agents
        runtime.callsign_registry.get_callsign.return_value = "SomeCallsign"

        targets = runtime.ward_room_router.find_targets(
            channel=channel, author_id="captain",
        )

        assert set(targets) == {"a1", "a2", "a3"}


# ---------------------------------------------------------------------------
# AD-407d: Agent-to-agent routing
# ---------------------------------------------------------------------------

class TestAgentToAgentRouting:
    async def test_agent_post_routes_to_mentioned_agents(self):
        """Agent post with @mention reaches the mentioned agent."""
        runtime = _make_mock_runtime()
        agent_a = _make_agent("agent-a", "builder")
        agent_b = _make_agent("agent-b", "architect")
        runtime.registry.all.return_value = [agent_a, agent_b]
        runtime.registry.get.return_value = agent_b
        runtime.callsign_registry.resolve.side_effect = lambda cs: (
            {"agent_id": "agent-b"} if cs == "numberone" else None
        )
        runtime.callsign_registry.get_callsign.return_value = "Number One"

        channel = _make_channel("ch1", "ship")
        runtime.ward_room.list_channels = AsyncMock(return_value=[channel])
        runtime.ward_room.get_channel = AsyncMock(return_value=channel)
        runtime.ward_room.get_thread = AsyncMock(return_value={
            "thread": {"title": "Test", "body": "Hey", "channel_id": "ch1"},
            "posts": [],
        })
        runtime.ward_room.create_post = AsyncMock()
        runtime.intent_bus.send = AsyncMock(return_value=IntentResult(
            intent_id="x", agent_id="agent-b", success=True,
            result="Acknowledged.",
        ))

        data = {
            "author_id": "agent-a", "thread_id": "t1",
            "mentions": ["numberone"], "author_callsign": "Scotty",
        }
        await runtime.ward_room_router.route_event("ward_room_post_created", data)
        runtime.intent_bus.send.assert_called_once()
        # Verify intent was sent to agent-b
        call_args = runtime.intent_bus.send.call_args[0][0]
        assert call_args.target_agent_id == "agent-b"

    async def test_agent_post_ship_channel_no_broadcast(self):
        """Agent post in ship-wide channel does NOT broadcast to all crew."""
        runtime = _make_mock_runtime()
        agents = [
            _make_agent("a1", "architect"),
            _make_agent("a2", "counselor"),
            _make_agent("a3", "scout"),
        ]
        runtime.registry.all.return_value = agents

        channel = _make_channel("ch1", "ship")
        runtime.ward_room.list_channels = AsyncMock(return_value=[channel])
        runtime.ward_room.get_channel = AsyncMock(return_value=channel)
        runtime.ward_room.get_thread = AsyncMock(return_value={
            "thread": {"title": "Test", "body": "Hey", "channel_id": "ch1"},
            "posts": [],
        })

        # Agent post with no @mentions in a ship channel
        data = {
            "author_id": "a1", "thread_id": "t1",
            "mentions": [], "author_callsign": "Number One",
        }
        await runtime.ward_room_router.route_event("ward_room_post_created", data)
        # No broadcast — intent_bus.send not called
        runtime.intent_bus.send.assert_not_called()

    async def test_agent_post_department_channel_reaches_peers(self):
        """Agent post in department channel reaches department peers."""
        runtime = _make_mock_runtime()
        eng1 = _make_agent("eng1", "engineering_officer")
        eng2 = _make_agent("eng2", "operations_officer")
        sci1 = _make_agent("sci1", "architect")
        runtime.registry.all.return_value = [eng1, eng2, sci1]
        runtime.registry.get.side_effect = lambda aid: {
            "eng1": eng1, "eng2": eng2, "sci1": sci1,
        }.get(aid)
        runtime.callsign_registry.get_callsign.return_value = "LaForge"

        channel = _make_channel("ch-eng", "department", department="engineering")
        runtime.ward_room.list_channels = AsyncMock(return_value=[channel])
        runtime.ward_room.get_channel = AsyncMock(return_value=channel)
        runtime.ward_room.get_thread = AsyncMock(return_value={
            "thread": {"title": "Eng Status", "body": "Report", "channel_id": "ch-eng"},
            "posts": [],
        })
        runtime.ward_room.create_post = AsyncMock()
        runtime.intent_bus.send = AsyncMock(return_value=IntentResult(
            intent_id="x", agent_id="eng2", success=True,
            result="All good.",
        ))

        with patch("probos.cognitive.standing_orders.get_department") as mock_dept:
            mock_dept.side_effect = lambda t: {
                "engineering_officer": "engineering",
                "operations_officer": "engineering",
                "architect": "science",
            }.get(t)

            data = {
                "author_id": "eng1", "thread_id": "t1",
                "mentions": [], "author_callsign": "LaForge",
            }
            await runtime.ward_room_router.route_event("ward_room_post_created", data)

        # eng2 (same dept) should be reached, sci1 (different dept) should not
        runtime.intent_bus.send.assert_called_once()
        call_args = runtime.intent_bus.send.call_args[0][0]
        assert call_args.target_agent_id == "eng2"

    async def test_captain_post_still_broadcasts_ship_wide(self):
        """Regression: Captain posts in ship channel still broadcast to all crew."""
        runtime = _make_mock_runtime()
        agents = [
            _make_agent("a1", "architect"),
            _make_agent("a2", "counselor"),
        ]
        runtime.registry.all.return_value = agents
        runtime.callsign_registry.resolve.return_value = None

        channel = _make_channel("ch1", "ship")
        runtime.ward_room.list_channels = AsyncMock(return_value=[channel])
        runtime.ward_room.get_channel = AsyncMock(return_value=channel)
        runtime.ward_room.get_thread = AsyncMock(return_value={
            "thread": {"title": "Test", "body": "Hello", "channel_id": "ch1"},
            "posts": [],
        })
        runtime.intent_bus.send = AsyncMock(return_value=IntentResult(
            intent_id="x", agent_id="a1", success=True, result="[NO_RESPONSE]",
        ))

        data = {"author_id": "captain", "channel_id": "ch1", "thread_id": "t1"}
        await runtime.ward_room_router.route_event("ward_room_thread_created", data)
        # Both agents should be reached
        assert runtime.intent_bus.send.call_count == 2


# ---------------------------------------------------------------------------
# AD-407d: Thread depth tracking
# ---------------------------------------------------------------------------

class TestThreadDepthTracking:
    async def test_round_increments_on_agent_response(self):
        """Round counter increments when an agent responds to an agent post."""
        runtime = _make_mock_runtime()
        agent = _make_agent("agent-b", "architect")
        runtime.registry.all.return_value = [agent]
        runtime.registry.get.return_value = agent
        runtime.callsign_registry.resolve.side_effect = lambda cs: (
            {"agent_id": "agent-b"} if cs == "numberone" else None
        )
        runtime.callsign_registry.get_callsign.return_value = "Number One"

        channel = _make_channel("ch1", "ship")
        runtime.ward_room.list_channels = AsyncMock(return_value=[channel])
        runtime.ward_room.get_channel = AsyncMock(return_value=channel)
        runtime.ward_room.get_thread = AsyncMock(return_value={
            "thread": {"title": "Test", "body": "Hey", "channel_id": "ch1"},
            "posts": [],
        })
        runtime.ward_room.create_post = AsyncMock()
        runtime.intent_bus.send = AsyncMock(return_value=IntentResult(
            intent_id="x", agent_id="agent-b", success=True,
            result="I agree.",
        ))

        data = {
            "author_id": "agent-a", "thread_id": "t1",
            "mentions": ["numberone"], "author_callsign": "Scotty",
        }
        assert runtime._ward_room_thread_rounds.get("t1", 0) == 0
        await runtime.ward_room_router.route_event("ward_room_post_created", data)
        assert runtime._ward_room_thread_rounds.get("t1", 0) == 1

    async def test_round_capped_at_max(self):
        """At max rounds, agent posts are silenced."""
        runtime = _make_mock_runtime()
        runtime._ward_room_thread_rounds["t1"] = 3  # At limit

        # BF-156: Thread depth check now runs after channel lookup
        channel = _make_channel("ch1", "ship")
        runtime.ward_room.list_channels = AsyncMock(return_value=[channel])
        runtime.ward_room.get_channel = AsyncMock(return_value=channel)
        runtime.ward_room.get_thread = AsyncMock(return_value={
            "thread": {"title": "Test", "body": "Hey", "channel_id": "ch1"},
            "posts": [],
        })

        data = {"author_id": "agent-a", "channel_id": "ch1", "thread_id": "t1", "mentions": []}
        await runtime.ward_room_router.route_event("ward_room_post_created", data)
        runtime.intent_bus.send.assert_not_called()

    async def test_captain_post_resets_round(self):
        """Captain posting in a thread resets the round counter to 0."""
        runtime = _make_mock_runtime()
        runtime._ward_room_thread_rounds["t1"] = 3  # Was at limit
        runtime._ward_room_round_participants["t1:0"] = {"agent-1"}
        runtime._ward_room_round_participants["t1:1"] = {"agent-2"}

        agent = _make_agent("agent-1", "architect")
        runtime.registry.all.return_value = [agent]
        runtime.callsign_registry.resolve.return_value = None

        channel = _make_channel("ch1", "ship")
        runtime.ward_room.list_channels = AsyncMock(return_value=[channel])
        runtime.ward_room.get_channel = AsyncMock(return_value=channel)
        runtime.ward_room.get_thread = AsyncMock(return_value={
            "thread": {"title": "Test", "body": "More", "channel_id": "ch1"},
            "posts": [],
        })
        runtime.intent_bus.send = AsyncMock(return_value=IntentResult(
            intent_id="x", agent_id="agent-1", success=True, result="[NO_RESPONSE]",
        ))

        data = {"author_id": "captain", "channel_id": "ch1", "thread_id": "t1"}
        await runtime.ward_room_router.route_event("ward_room_thread_created", data)
        # Round reset to 0
        assert runtime._ward_room_thread_rounds["t1"] == 0
        # Old participants cleared (t1:1 gone; t1:0 re-created empty by current round)
        assert "t1:1" not in runtime._ward_room_round_participants
        # t1:0 exists but is empty (fresh round, no responses yet)
        assert runtime._ward_room_round_participants.get("t1:0", set()) == set()

    async def test_no_response_does_not_increment_round(self):
        """[NO_RESPONSE] from all agents does not increment the round counter."""
        runtime = _make_mock_runtime()
        agent = _make_agent("agent-b", "architect")
        runtime.registry.all.return_value = [agent]
        runtime.callsign_registry.resolve.side_effect = lambda cs: (
            {"agent_id": "agent-b"} if cs == "numberone" else None
        )

        channel = _make_channel("ch1", "ship")
        runtime.ward_room.list_channels = AsyncMock(return_value=[channel])
        runtime.ward_room.get_channel = AsyncMock(return_value=channel)
        runtime.ward_room.get_thread = AsyncMock(return_value={
            "thread": {"title": "Test", "body": "Hey", "channel_id": "ch1"},
            "posts": [],
        })
        runtime.intent_bus.send = AsyncMock(return_value=IntentResult(
            intent_id="x", agent_id="agent-b", success=True,
            result="[NO_RESPONSE]",
        ))

        data = {
            "author_id": "agent-a", "thread_id": "t1",
            "mentions": ["numberone"], "author_callsign": "Scotty",
        }
        await runtime.ward_room_router.route_event("ward_room_post_created", data)
        # No actual response -> round stays at 0
        assert runtime._ward_room_thread_rounds.get("t1", 0) == 0


# ---------------------------------------------------------------------------
# AD-407d: Per-round participation
# ---------------------------------------------------------------------------

class TestRoundParticipation:
    async def test_agent_cannot_respond_twice_same_round(self):
        """Agent already in round participants is skipped."""
        runtime = _make_mock_runtime()
        # agent-b already responded in round 0 of thread t1
        runtime._ward_room_round_participants["t1:0"] = {"agent-b"}

        agent = _make_agent("agent-b", "architect")
        runtime.registry.all.return_value = [agent]
        # BF-157: Don't @mention agent-b — mentioned agents bypass round check.
        # Route via ambient ship channel targeting instead.
        runtime.callsign_registry.resolve.return_value = None

        channel = _make_channel("ch1", "ship")
        runtime.ward_room.list_channels = AsyncMock(return_value=[channel])
        runtime.ward_room.get_channel = AsyncMock(return_value=channel)
        runtime.ward_room.get_thread = AsyncMock(return_value={
            "thread": {"title": "Test", "body": "Hey", "channel_id": "ch1"},
            "posts": [],
        })

        data = {
            "author_id": "agent-a", "thread_id": "t1",
            "channel_id": "ch1", "author_callsign": "Scotty",
        }
        await runtime.ward_room_router.route_event("ward_room_post_created", data)
        # agent-b already in round participants — skipped
        runtime.intent_bus.send.assert_not_called()

    async def test_agent_can_respond_in_new_round(self):
        """Agent that responded in round 0 can respond again in round 1."""
        runtime = _make_mock_runtime()
        # agent-b responded in round 0, but thread is now at round 1
        runtime._ward_room_thread_rounds["t1"] = 1
        runtime._ward_room_round_participants["t1:0"] = {"agent-b"}
        # Round 1 has no participants yet

        agent = _make_agent("agent-b", "architect")
        runtime.registry.all.return_value = [agent]
        runtime.registry.get.return_value = agent
        runtime.callsign_registry.resolve.side_effect = lambda cs: (
            {"agent_id": "agent-b"} if cs == "numberone" else None
        )
        runtime.callsign_registry.get_callsign.return_value = "Number One"

        channel = _make_channel("ch1", "ship")
        runtime.ward_room.list_channels = AsyncMock(return_value=[channel])
        runtime.ward_room.get_channel = AsyncMock(return_value=channel)
        runtime.ward_room.get_thread = AsyncMock(return_value={
            "thread": {"title": "Test", "body": "Hey", "channel_id": "ch1"},
            "posts": [],
        })
        runtime.ward_room.create_post = AsyncMock()
        runtime.intent_bus.send = AsyncMock(return_value=IntentResult(
            intent_id="x", agent_id="agent-b", success=True,
            result="Good point.",
        ))

        data = {
            "author_id": "agent-a", "thread_id": "t1",
            "mentions": ["numberone"], "author_callsign": "Scotty",
        }
        await runtime.ward_room_router.route_event("ward_room_post_created", data)
        # agent-b NOT in round 1 participants yet — should be reached
        runtime.intent_bus.send.assert_called_once()


# ---------------------------------------------------------------------------
# DM Channel Routing (AD-574)
# ---------------------------------------------------------------------------

class TestDmChannelRouting:
    """AD-574: Captain posts in DM channels notify the target agent."""

    @pytest.mark.asyncio
    async def test_captain_post_in_dm_notifies_agent(self):
        """find_targets returns the agent when Captain posts in their DM channel."""
        runtime = _make_mock_runtime()
        agent = _make_agent("abc12345-full-uuid", "architect")
        runtime.registry.all.return_value = [agent]

        channel = _make_channel("dm-ch1", "dm")
        channel.name = "dm-captain-abc12345"

        targets = runtime.ward_room_router.find_targets(
            channel=channel, author_id="captain",
        )
        assert "abc12345-full-uuid" in targets

    @pytest.mark.asyncio
    async def test_captain_post_in_dm_does_not_notify_self(self):
        """Captain is never in the target list."""
        runtime = _make_mock_runtime()
        agent = _make_agent("abc12345-full-uuid", "architect")
        runtime.registry.all.return_value = [agent]

        channel = _make_channel("dm-ch1", "dm")
        channel.name = "dm-captain-abc12345"

        targets = runtime.ward_room_router.find_targets(
            channel=channel, author_id="captain",
        )
        assert "captain" not in targets

    @pytest.mark.asyncio
    async def test_captain_post_in_dm_no_earned_agency_gating(self):
        """DM routing bypasses Earned Agency trust-tier check."""
        runtime = _make_mock_runtime()
        runtime.config.earned_agency.enabled = True
        # Low trust agent — would be filtered by EA on ship/dept channels
        runtime.trust_network.get_score.return_value = 0.1

        agent = _make_agent("abc12345-full-uuid", "architect")
        runtime.registry.all.return_value = [agent]

        channel = _make_channel("dm-ch1", "dm")
        channel.name = "dm-captain-abc12345"

        targets = runtime.ward_room_router.find_targets(
            channel=channel, author_id="captain",
        )
        assert "abc12345-full-uuid" in targets

    @pytest.mark.asyncio
    async def test_agent_not_in_channel_not_notified(self):
        """Agents whose ID prefix doesn't match are excluded."""
        runtime = _make_mock_runtime()
        agent = _make_agent("zzz99999-other-uuid", "architect")
        runtime.registry.all.return_value = [agent]

        channel = _make_channel("dm-ch1", "dm")
        channel.name = "dm-captain-abc12345"

        targets = runtime.ward_room_router.find_targets(
            channel=channel, author_id="captain",
        )
        assert len(targets) == 0

    @pytest.mark.asyncio
    async def test_agent_initiated_dm_captain_reply_routes(self):
        """Agent-initiated DM (channel name dm-{agent}-{captain}) routes Captain reply."""
        runtime = _make_mock_runtime()
        agent = _make_agent("abc12345-full-uuid", "architect")
        runtime.registry.all.return_value = [agent]

        channel = _make_channel("dm-ch1", "dm")
        channel.name = "dm-abc12345-captain"

        targets = runtime.ward_room_router.find_targets(
            channel=channel, author_id="captain",
        )
        assert "abc12345-full-uuid" in targets


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_mock_runtime(ward_room=None):
    """Create a mock runtime with the minimum fields needed."""
    from probos.runtime import ProbOSRuntime
    from probos.ward_room_router import WardRoomRouter

    runtime = MagicMock(spec=ProbOSRuntime)
    runtime.ward_room = ward_room or MagicMock()
    # AD-616: route_event() now calls get_channel() instead of list_channels()
    if not ward_room:
        runtime.ward_room.get_channel = AsyncMock(return_value=None)
    # Config mock
    runtime.config = MagicMock()
    runtime.config.ward_room.max_agent_rounds = 3
    runtime.config.ward_room.agent_cooldown_seconds = 45
    runtime.config.ward_room.max_agent_responses_per_thread = 3
    runtime.config.earned_agency.enabled = False  # AD-357: off by default in tests

    runtime.intent_bus = MagicMock()
    runtime.intent_bus.send = AsyncMock()
    runtime.registry = MagicMock()
    runtime.registry.all.return_value = []
    runtime.registry.get.return_value = None
    runtime.callsign_registry = MagicMock()
    runtime.callsign_registry.resolve.return_value = None
    runtime.callsign_registry.get_callsign.return_value = ""
    runtime.ontology = None  # AD-429e: Explicit None so _is_crew_agent uses legacy set
    runtime.trust_network = MagicMock()
    runtime.trust_network.get_score.return_value = 0.5

    # AD-515: Create WardRoomRouter so delegation works
    event_log = AsyncMock()
    router = WardRoomRouter(
        ward_room=runtime.ward_room,
        registry=runtime.registry,
        intent_bus=runtime.intent_bus,
        trust_network=runtime.trust_network,
        ontology=runtime.ontology,
        callsign_registry=runtime.callsign_registry,
        episodic_memory=None,
        event_emitter=MagicMock(),
        event_log=event_log,
        config=runtime.config,
        notify_fn=None,
        proactive_loop=None,
    )
    runtime.ward_room_router = router

    # Expose router state through runtime attrs so tests can inspect/manipulate
    runtime._ward_room_cooldowns = router._cooldowns
    runtime._ward_room_thread_rounds = router._thread_rounds
    runtime._ward_room_round_participants = router._round_participants
    runtime._ward_room_agent_thread_responses = router._agent_thread_responses

    return runtime


def _make_agent(agent_id: str, agent_type: str):
    """Create a mock agent."""
    agent = MagicMock(spec=BaseAgent)
    agent.id = agent_id
    agent.agent_type = agent_type
    agent.is_alive = True
    agent.handle_intent = AsyncMock()
    return agent


def _make_channel(channel_id: str, channel_type: str, department: str = ""):
    """Create a mock channel."""
    ch = MagicMock(spec=WardRoomChannel)
    ch.id = channel_id
    ch.channel_type = channel_type
    ch.department = department
    ch.name = f"Channel-{channel_id}"
    return ch


# ---------------------------------------------------------------------------
# Thread Mode Routing (AD-424)
# ---------------------------------------------------------------------------

class TestThreadModeRouting:

    @pytest.mark.asyncio
    async def test_inform_thread_no_agent_notification(self):
        """INFORM threads skip agent notification entirely."""
        runtime = _make_mock_runtime()
        channel = _make_channel("ch1", "ship")
        runtime.ward_room.list_channels = AsyncMock(return_value=[channel])
        runtime.ward_room.get_channel = AsyncMock(return_value=channel)
        runtime.ward_room.get_thread = AsyncMock(return_value={
            "thread": {"title": "Alert", "body": "Status", "channel_id": "ch1",
                       "thread_mode": "inform", "max_responders": 0},
            "posts": [],
        })
        agent = _make_agent("agent-1", "architect")
        runtime.registry.all.return_value = [agent]

        data = {"author_id": "captain", "channel_id": "ch1", "thread_id": "t1",
                "thread_mode": "inform"}
        await runtime.ward_room_router.route_event("ward_room_thread_created", data)
        runtime.intent_bus.send.assert_not_called()

    @pytest.mark.asyncio
    async def test_discuss_thread_notifies_agents(self):
        """DISCUSS threads DO notify agents."""
        runtime = _make_mock_runtime()
        channel = _make_channel("ch1", "ship")
        runtime.ward_room.list_channels = AsyncMock(return_value=[channel])
        runtime.ward_room.get_channel = AsyncMock(return_value=channel)
        runtime.ward_room.get_thread = AsyncMock(return_value={
            "thread": {"title": "Discussion", "body": "Thoughts?", "channel_id": "ch1",
                       "thread_mode": "discuss", "max_responders": 0},
            "posts": [],
        })
        agent = _make_agent("agent-1", "architect")
        runtime.registry.all.return_value = [agent]
        runtime.callsign_registry.get_callsign.return_value = "Number One"
        runtime.intent_bus.send = AsyncMock(return_value=IntentResult(
            intent_id="x", agent_id="agent-1", success=True, result="[NO_RESPONSE]",
        ))

        data = {"author_id": "captain", "channel_id": "ch1", "thread_id": "t1",
                "thread_mode": "discuss"}
        await runtime.ward_room_router.route_event("ward_room_thread_created", data)
        runtime.intent_bus.send.assert_called()

    @pytest.mark.asyncio
    async def test_discuss_ship_wide_lieutenant_can_respond(self):
        """BF-022: DISCUSS threads on ship-wide let Lieutenants respond."""
        runtime = _make_mock_runtime()
        runtime.config.earned_agency.enabled = True
        # trust_network already returns 0.5 (Lieutenant) from _make_mock_runtime

        channel = _make_channel("ch1", "ship")
        agent = _make_agent("agent-1", "architect")
        runtime.registry.all.return_value = [agent]

        targets = runtime.ward_room_router.find_targets(
            channel=channel, author_id="captain",
            mentions=None, thread_mode="discuss",
        )
        assert "agent-1" in targets

    @pytest.mark.asyncio
    async def test_action_thread_only_mentions(self):
        """ACTION threads only notify @mentioned agents."""
        runtime = _make_mock_runtime()
        channel = _make_channel("ch1", "ship")
        runtime.ward_room.list_channels = AsyncMock(return_value=[channel])
        runtime.ward_room.get_channel = AsyncMock(return_value=channel)
        runtime.ward_room.get_thread = AsyncMock(return_value={
            "thread": {"title": "Order", "body": "Do it", "channel_id": "ch1",
                       "thread_mode": "action", "max_responders": 0},
            "posts": [],
        })
        a1 = _make_agent("agent-1", "architect")
        a2 = _make_agent("agent-2", "security_officer")
        a3 = _make_agent("agent-3", "counselor")
        runtime.registry.all.return_value = [a1, a2, a3]
        runtime.registry.get.return_value = a1
        runtime.callsign_registry.resolve.side_effect = lambda c: (
            {"agent_id": "agent-1"} if c == "numberone" else None
        )
        runtime.callsign_registry.get_callsign.return_value = "Number One"
        runtime.intent_bus.send = AsyncMock(return_value=IntentResult(
            intent_id="x", agent_id="agent-1", success=True, result="Aye",
        ))

        data = {"author_id": "captain", "channel_id": "ch1", "thread_id": "t1",
                "thread_mode": "action", "mentions": ["numberone"]}
        await runtime.ward_room_router.route_event("ward_room_thread_created", data)
        # Only agent-1 (mentioned) should get notified
        assert runtime.intent_bus.send.call_count == 1

    @pytest.mark.asyncio
    async def test_discuss_responder_cap_applied(self):
        """DISCUSS thread max_responders caps number of agents notified."""
        runtime = _make_mock_runtime()
        channel = _make_channel("ch1", "ship")
        runtime.ward_room.list_channels = AsyncMock(return_value=[channel])
        runtime.ward_room.get_channel = AsyncMock(return_value=channel)
        runtime.ward_room.get_thread = AsyncMock(return_value={
            "thread": {"title": "Capped", "body": "body", "channel_id": "ch1",
                       "thread_mode": "discuss", "max_responders": 2},
            "posts": [],
        })
        # 5 agents
        agents = [_make_agent(f"agent-{i}", "architect") for i in range(5)]
        runtime.registry.all.return_value = agents
        runtime.callsign_registry.get_callsign.return_value = "Crew"
        runtime.intent_bus.send = AsyncMock(return_value=IntentResult(
            intent_id="x", agent_id="agent-0", success=True, result="[NO_RESPONSE]",
        ))

        data = {"author_id": "captain", "channel_id": "ch1", "thread_id": "t1",
                "thread_mode": "discuss", "max_responders": 2}
        await runtime.ward_room_router.route_event("ward_room_thread_created", data)
        assert runtime.intent_bus.send.call_count <= 2

    @pytest.mark.asyncio
    async def test_inform_not_passed_to_targets(self):
        """INFORM threads short-circuit before find_targets."""
        runtime = _make_mock_runtime()
        # Patch find_targets on the router to track if called
        import types
        original = runtime.ward_room_router.find_targets
        call_tracker = {"called": False}

        def tracking_targets(*a, **kw):
            call_tracker["called"] = True
            return original(*a, **kw)

        runtime.ward_room_router.find_targets = tracking_targets

        channel = _make_channel("ch1", "ship")
        runtime.ward_room.list_channels = AsyncMock(return_value=[channel])
        runtime.ward_room.get_channel = AsyncMock(return_value=channel)

        data = {"author_id": "captain", "channel_id": "ch1", "thread_id": "t1",
                "thread_mode": "inform"}
        await runtime.ward_room_router.route_event("ward_room_thread_created", data)
        assert not call_tracker["called"]
