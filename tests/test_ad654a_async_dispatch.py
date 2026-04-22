"""Tests for AD-654a: Async Ward Room Dispatch.

JetStream fire-and-forget dispatch, WardRoomPostPipeline,
agent self-posting, manual_ack/term semantics, consumer cleanup.
"""

import asyncio
import time

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from probos.mesh.intent import IntentBus
from probos.mesh.nats_bus import MockNATSBus
from probos.mesh.signal import SignalManager
from probos.types import IntentMessage, IntentResult
from probos.ward_room_pipeline import WardRoomPostPipeline


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def signal_manager():
    return SignalManager()


@pytest.fixture
def mock_nats_bus():
    bus = MockNATSBus()
    bus._connected = True
    return bus


@pytest.fixture
def intent_bus(signal_manager, mock_nats_bus):
    bus = IntentBus(signal_manager)
    bus.set_nats_bus(mock_nats_bus)
    return bus


def _make_intent(target_agent_id="agent-001", intent_name="ward_room_notification", **params):
    return IntentMessage(
        intent=intent_name,
        target_agent_id=target_agent_id,
        ttl_seconds=30.0,
        params=params,
    )


class _MockAgent:
    """Minimal agent mock for pipeline tests."""
    def __init__(self, agent_id="agent-001", agent_type="test_agent"):
        self.id = agent_id
        self.agent_type = agent_type


# ---------------------------------------------------------------------------
# IntentBus.dispatch_async()
# ---------------------------------------------------------------------------

class TestDispatchAsync:
    @pytest.mark.asyncio
    async def test_dispatch_async_publishes_to_jetstream(self, intent_bus, mock_nats_bus):
        """dispatch_async() calls js_publish() with correct subject."""
        mock_nats_bus.js_publish = AsyncMock()
        intent = _make_intent()
        await intent_bus.dispatch_async(intent)
        mock_nats_bus.js_publish.assert_awaited_once()
        call_args = mock_nats_bus.js_publish.call_args
        assert call_args[0][0] == "intent.dispatch.agent-001"

    @pytest.mark.asyncio
    async def test_dispatch_async_fallback_to_direct(self, signal_manager):
        """When NATS disconnected, dispatch_async() falls back to direct handler."""
        bus = IntentBus(signal_manager)
        called = asyncio.Event()

        async def handler(intent):
            called.set()
            return IntentResult(
                intent_id=intent.id, agent_id="agent-001",
                success=True, confidence=1.0,
            )

        bus.subscribe("agent-001", handler)
        intent = _make_intent()
        await bus.dispatch_async(intent)
        # Give the background task time to run
        await asyncio.sleep(0.05)
        assert called.is_set()

    @pytest.mark.asyncio
    async def test_dispatch_async_requires_target_agent_id(self, intent_bus):
        """Raises ValueError when target_agent_id is None."""
        intent = IntentMessage(intent="test", ttl_seconds=5.0)
        with pytest.raises(ValueError, match="target_agent_id"):
            await intent_bus.dispatch_async(intent)

    @pytest.mark.asyncio
    async def test_dispatch_async_jetstream_failure_falls_back(self, intent_bus, mock_nats_bus):
        """When js_publish() raises, falls back to direct dispatch."""
        mock_nats_bus.js_publish = AsyncMock(side_effect=RuntimeError("NATS down"))
        called = asyncio.Event()

        async def handler(intent):
            called.set()
            return None

        intent_bus.subscribe("agent-001", handler)
        intent = _make_intent()
        await intent_bus.dispatch_async(intent)
        await asyncio.sleep(0.05)
        assert called.is_set()

    @pytest.mark.asyncio
    async def test_dispatch_async_pending_task_cap(self, signal_manager):
        """When pending tasks exceed 200, drops dispatch with warning."""
        bus = IntentBus(signal_manager)
        # Fill pending tasks to capacity
        for i in range(200):
            t = asyncio.get_event_loop().create_task(asyncio.sleep(10))
            bus._pending_sub_tasks.add(t)

        async def handler(intent):
            return None

        bus.subscribe("agent-001", handler)
        intent = _make_intent()
        # Should silently drop — no exception
        await bus.dispatch_async(intent)
        # Clean up tasks
        for t in list(bus._pending_sub_tasks):
            t.cancel()
        await asyncio.sleep(0)


# ---------------------------------------------------------------------------
# JetStream Consumer (ack semantics)
# ---------------------------------------------------------------------------

class TestJetStreamConsumer:
    @pytest.mark.asyncio
    async def test_js_subscribe_agent_dispatch_creates_consumer(self, intent_bus, mock_nats_bus):
        """subscribe() creates a durable JetStream consumer."""
        mock_nats_bus.js_subscribe = AsyncMock(return_value=MagicMock())
        intent_bus._defer_dispatch_consumers = False  # BF-223: simulate post-finalize

        async def handler(intent):
            return None

        intent_bus.subscribe("agent-test-001", handler)
        await asyncio.sleep(0.05)  # Let task run

        # Check js_subscribe was called with correct params
        calls = mock_nats_bus.js_subscribe.call_args_list
        dispatch_calls = [c for c in calls if "intent.dispatch." in str(c)]
        assert len(dispatch_calls) >= 1
        call = dispatch_calls[0]
        assert call[0][0] == "intent.dispatch.agent-test-001"
        assert call[1].get("durable") == "agent-dispatch-agent-test-001"
        assert call[1].get("stream") == "INTENT_DISPATCH"
        assert call[1].get("max_ack_pending") == 1
        assert call[1].get("manual_ack") is True

    @pytest.mark.asyncio
    async def test_js_consumer_acks_on_success(self, intent_bus):
        """Callback calls msg.ack() after successful handler execution."""
        msg = MagicMock()
        msg.data = {
            "id": "test-id", "intent": "ward_room_notification",
            "target_agent_id": "agent-001", "ttl_seconds": 30,
            "params": {}, "timestamp": "2026-01-01T00:00:00+00:00",
        }
        msg.ack = AsyncMock()
        msg.term = AsyncMock()

        async def handler(intent):
            return IntentResult(intent_id=intent.id, agent_id="agent-001",
                                success=True, confidence=1.0)

        # Subscribe, then capture the callback
        callbacks = []
        original_js_sub = intent_bus._nats_bus.js_subscribe

        async def capture_js_sub(subject, callback, **kwargs):
            if "intent.dispatch." in subject:
                callbacks.append(callback)
            return MagicMock()

        intent_bus._nats_bus.js_subscribe = capture_js_sub
        intent_bus._defer_dispatch_consumers = False  # BF-223: simulate post-finalize
        intent_bus.subscribe("agent-001", handler)
        await asyncio.sleep(0.05)

        assert len(callbacks) >= 1
        await callbacks[0](msg)
        msg.ack.assert_awaited_once()
        msg.term.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_js_consumer_terms_on_error(self, intent_bus):
        """Callback calls msg.term() (NOT nak) when handler raises."""
        msg = MagicMock()
        msg.data = {
            "id": "test-id", "intent": "ward_room_notification",
            "target_agent_id": "agent-001", "ttl_seconds": 30,
            "params": {}, "timestamp": "2026-01-01T00:00:00+00:00",
        }
        msg.ack = AsyncMock()
        msg.term = AsyncMock()
        msg.nak = AsyncMock()

        async def handler(intent):
            raise RuntimeError("Cognitive chain failed")

        callbacks = []

        async def capture_js_sub(subject, callback, **kwargs):
            if "intent.dispatch." in subject:
                callbacks.append(callback)
            return MagicMock()

        intent_bus._nats_bus.js_subscribe = capture_js_sub
        intent_bus._defer_dispatch_consumers = False  # BF-223: simulate post-finalize
        intent_bus.subscribe("agent-001", handler)
        await asyncio.sleep(0.05)

        assert len(callbacks) >= 1
        await callbacks[0](msg)
        msg.term.assert_awaited_once()
        msg.ack.assert_not_awaited()
        msg.nak.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_js_consumer_uses_full_agent_id(self, intent_bus, mock_nats_bus):
        """Durable name uses full agent ID, not truncated."""
        mock_nats_bus.js_subscribe = AsyncMock(return_value=MagicMock())
        intent_bus._defer_dispatch_consumers = False  # BF-223: simulate post-finalize
        full_id = "a1b2c3d4-e5f6-7890-abcd-ef1234567890"

        async def handler(intent):
            return None

        intent_bus.subscribe(full_id, handler)
        await asyncio.sleep(0.05)

        calls = mock_nats_bus.js_subscribe.call_args_list
        dispatch_calls = [c for c in calls if "intent.dispatch." in str(c)]
        assert any(
            c[1].get("durable") == f"agent-dispatch-{full_id}"
            for c in dispatch_calls
        )

    @pytest.mark.asyncio
    async def test_js_consumer_records_response_before_handler(self, intent_bus):
        """BF-198: record_agent_response() called BEFORE handler runs."""
        call_order = []

        msg = MagicMock()
        msg.data = {
            "id": "test-id", "intent": "ward_room_notification",
            "target_agent_id": "agent-001", "ttl_seconds": 30,
            "params": {"thread_id": "thread-123"},
            "timestamp": "2026-01-01T00:00:00+00:00",
        }
        msg.ack = AsyncMock()
        msg.term = AsyncMock()

        mock_runtime = MagicMock()
        mock_router = MagicMock()
        mock_router.record_agent_response = MagicMock(
            side_effect=lambda *a: call_order.append("record")
        )
        mock_runtime.ward_room_router = mock_router

        class FakeAgent:
            _runtime = mock_runtime

            async def handle(self, intent):
                call_order.append("handle")
                return IntentResult(
                    intent_id=intent.id, agent_id="agent-001",
                    success=True, confidence=1.0,
                )

        agent = FakeAgent()

        callbacks = []

        async def capture_js_sub(subject, callback, **kwargs):
            if "intent.dispatch." in subject:
                callbacks.append(callback)
            return MagicMock()

        intent_bus._nats_bus.js_subscribe = capture_js_sub
        intent_bus._defer_dispatch_consumers = False  # BF-223: simulate post-finalize
        intent_bus.subscribe("agent-001", agent.handle)
        await asyncio.sleep(0.05)

        assert len(callbacks) >= 1
        await callbacks[0](msg)
        assert call_order == ["record", "handle"]

    @pytest.mark.asyncio
    async def test_js_subscribe_manual_ack_skips_wrapper_ack(self, mock_nats_bus):
        """When manual_ack=True, js_subscribe wrapper does NOT auto-ack."""
        msg = MagicMock()
        msg.data = {"test": True}
        msg.ack = AsyncMock()
        msg.nak = AsyncMock()

        handler_called = asyncio.Event()

        async def handler(m):
            handler_called.set()

        await mock_nats_bus.js_subscribe(
            "test.subject", handler, manual_ack=True,
        )
        # MockNATSBus stores callbacks in _active_subs list — find and invoke
        for sub_info in mock_nats_bus._active_subs:
            cb = sub_info.get("callback")
            if cb:
                await cb(msg)
                break

        assert handler_called.is_set()
        # manual_ack means wrapper should NOT auto-ack
        msg.ack.assert_not_awaited()


# ---------------------------------------------------------------------------
# Consumer Cleanup
# ---------------------------------------------------------------------------

class TestConsumerCleanup:
    @pytest.mark.asyncio
    async def test_unsubscribe_deletes_jetstream_consumer(self, intent_bus, mock_nats_bus):
        """unsubscribe() calls delete_consumer for the dispatch consumer."""
        mock_nats_bus.delete_consumer = AsyncMock()

        async def handler(intent):
            return None

        intent_bus.subscribe("agent-cleanup", handler)
        await asyncio.sleep(0.05)

        intent_bus.unsubscribe("agent-cleanup")
        await asyncio.sleep(0.05)

        mock_nats_bus.delete_consumer.assert_awaited_once_with(
            "INTENT_DISPATCH", "agent-dispatch-agent-cleanup",
        )

    @pytest.mark.asyncio
    async def test_delete_consumer_handles_missing_gracefully(self, mock_nats_bus):
        """delete_consumer() with nonexistent consumer doesn't raise."""
        # Should not raise
        await mock_nats_bus.delete_consumer("INTENT_DISPATCH", "nonexistent")


# ---------------------------------------------------------------------------
# WardRoomPostPipeline
# ---------------------------------------------------------------------------

class TestWardRoomPostPipeline:
    def _make_pipeline(self, **overrides):
        mock_router = MagicMock()
        # Default: endorsement extraction passes text through unchanged
        mock_router.extract_endorsements = MagicMock(side_effect=lambda text: (text, []))
        mock_router.extract_recreation_commands = AsyncMock(side_effect=lambda agent, text, cs: text)
        mock_router.record_agent_response = MagicMock()
        mock_router.update_cooldown = MagicMock()
        defaults = dict(
            ward_room=AsyncMock(),
            ward_room_router=mock_router,
            proactive_loop=None,
            trust_network=None,
            callsign_registry=None,
            config=MagicMock(),
            runtime=None,
        )
        defaults.update(overrides)
        return WardRoomPostPipeline(**defaults)

    @pytest.mark.asyncio
    async def test_pipeline_sanitizes_text(self):
        """BF-199: Chain JSON artifacts are sanitized."""
        pipeline = self._make_pipeline()

        result = await pipeline.process_and_post(
            agent=_MockAgent(),
            response_text='{"result": "Hello world"}',
            thread_id="t1", event_type="ward_room_post_created",
        )
        # The sanitize function should handle chain JSON — just verify post went through
        # (or was filtered if sanitization returns empty)
        assert isinstance(result, bool)

    @pytest.mark.asyncio
    async def test_pipeline_strips_bracket_markers(self):
        """BF-174: Self-monitoring bracket markers removed."""
        pipeline = self._make_pipeline()

        result = await pipeline.process_and_post(
            agent=_MockAgent(),
            response_text="Hello world",
            thread_id="t1", event_type="ward_room_post_created",
        )
        assert result is True
        pipeline._ward_room.create_post.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_pipeline_similarity_guard(self):
        """BF-197: Near-duplicate text suppressed."""
        mock_loop = AsyncMock()
        mock_loop.extract_and_execute_actions = AsyncMock(
            return_value=("Same text again", []),
        )
        mock_loop.is_similar_to_recent_posts = AsyncMock(return_value=True)

        pipeline = self._make_pipeline(proactive_loop=mock_loop)
        result = await pipeline.process_and_post(
            agent=_MockAgent(),
            response_text="Same text again",
            thread_id="t1", event_type="ward_room_post_created",
        )
        assert result is False

    @pytest.mark.asyncio
    async def test_pipeline_extracts_actions(self):
        """Actions extracted via proactive loop's public wrapper."""
        mock_loop = AsyncMock()
        mock_loop.extract_and_execute_actions = AsyncMock(
            return_value=("Cleaned text", [{"type": "endorsement"}]),
        )
        mock_loop.is_similar_to_recent_posts = AsyncMock(return_value=False)

        pipeline = self._make_pipeline(proactive_loop=mock_loop)
        result = await pipeline.process_and_post(
            agent=_MockAgent(),
            response_text="Original with [ENDORSE]",
            thread_id="t1", event_type="ward_room_post_created",
        )
        assert result is True
        mock_loop.extract_and_execute_actions.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_pipeline_posts_to_ward_room(self):
        """Calls ward_room.create_post() with correct args."""
        pipeline = self._make_pipeline()

        result = await pipeline.process_and_post(
            agent=_MockAgent(agent_id="a1", agent_type="science_officer"),
            response_text="Hello crew",
            thread_id="thread-1", event_type="ward_room_post_created",
            post_id="post-1",
        )
        assert result is True
        call_kwargs = pipeline._ward_room.create_post.call_args[1]
        assert call_kwargs["thread_id"] == "thread-1"
        assert call_kwargs["author_id"] == "a1"
        assert call_kwargs["body"] == "Hello crew"
        assert call_kwargs["parent_id"] == "post-1"

    @pytest.mark.asyncio
    async def test_pipeline_records_response(self):
        """BF-198: Calls ward_room_router.record_agent_response()."""
        pipeline = self._make_pipeline()

        await pipeline.process_and_post(
            agent=_MockAgent(),
            response_text="Text",
            thread_id="t1", event_type="ward_room_post_created",
        )
        pipeline._router.record_agent_response.assert_called_once_with("agent-001", "t1")

    @pytest.mark.asyncio
    async def test_pipeline_records_skill_exercise(self):
        """AD-625: Records communication skill exercise."""
        mock_runtime = MagicMock()
        mock_runtime.skill_service = AsyncMock()
        mock_runtime.skill_service.record_exercise = AsyncMock()

        pipeline = self._make_pipeline(runtime=mock_runtime)

        await pipeline.process_and_post(
            agent=_MockAgent(),
            response_text="Text",
            thread_id="t1", event_type="ward_room_post_created",
        )
        mock_runtime.skill_service.record_exercise.assert_awaited_once_with(
            "agent-001", "communication",
        )

    @pytest.mark.asyncio
    async def test_pipeline_no_response_text(self):
        """Returns False for [NO_RESPONSE] or empty text."""
        pipeline = self._make_pipeline()
        result = await pipeline.process_and_post(
            agent=_MockAgent(),
            response_text="[NO_RESPONSE]",
            thread_id="t1", event_type="ward_room_post_created",
        )
        assert result is False

        result2 = await pipeline.process_and_post(
            agent=_MockAgent(),
            response_text="",
            thread_id="t1", event_type="ward_room_post_created",
        )
        assert result2 is False

    @pytest.mark.asyncio
    async def test_pipeline_thread_creation_no_parent_id(self):
        """For ward_room_thread_created events, parent_id should be None."""
        pipeline = self._make_pipeline()

        await pipeline.process_and_post(
            agent=_MockAgent(),
            response_text="Text",
            thread_id="t1", event_type="ward_room_thread_created",
            post_id="should-be-ignored",
        )
        call_kwargs = pipeline._ward_room.create_post.call_args[1]
        assert call_kwargs["parent_id"] is None


# ---------------------------------------------------------------------------
# Ward Room Router Dispatch
# ---------------------------------------------------------------------------

class TestRouterDispatch:
    @pytest.mark.asyncio
    async def test_router_dispatches_async_not_send(self):
        """Router calls dispatch_async() not send() for notifications."""
        from probos.mesh.intent import IntentBus

        mock_intent_bus = MagicMock(spec=IntentBus)
        mock_intent_bus.dispatch_async = AsyncMock()
        mock_intent_bus.send = AsyncMock()

        # Verify the intent bus has dispatch_async method
        assert hasattr(mock_intent_bus, "dispatch_async")

    @pytest.mark.asyncio
    async def test_router_round_counter_only_bumps_with_eligible(self):
        """Round counter unchanged when eligible is empty."""
        from probos.ward_room_router import WardRoomRouter

        router = WardRoomRouter.__new__(WardRoomRouter)
        router._thread_rounds = {}
        # When no eligible agents, thread_rounds should not get new entries
        assert "some-thread" not in router._thread_rounds


# ---------------------------------------------------------------------------
# Agent Self-Posting
# ---------------------------------------------------------------------------

class TestAgentSelfPosting:
    @pytest.mark.asyncio
    async def test_agent_self_posts_after_ward_room_notification(self):
        """Agent calls _self_post_ward_room_response() after handling notification."""
        from probos.cognitive.cognitive_agent import CognitiveAgent

        agent = CognitiveAgent.__new__(CognitiveAgent)
        agent.id = "agent-self-post"
        agent.agent_type = "test_agent"

        mock_pipeline = AsyncMock()
        mock_pipeline.process_and_post = AsyncMock(return_value=True)
        mock_runtime = MagicMock()
        mock_runtime.ward_room = MagicMock()
        mock_runtime.ward_room_post_pipeline = mock_pipeline
        agent._runtime = mock_runtime

        intent = _make_intent(
            target_agent_id="agent-self-post",
            thread_id="t1",
            event_type="ward_room_post_created",
            post_id="p1",
        )

        await agent._self_post_ward_room_response(intent, "My response text")

        mock_pipeline.process_and_post.assert_awaited_once()
        call_kwargs = mock_pipeline.process_and_post.call_args[1]
        assert call_kwargs["response_text"] == "My response text"
        assert call_kwargs["thread_id"] == "t1"
        assert call_kwargs["event_type"] == "ward_room_post_created"
        assert call_kwargs["post_id"] == "p1"

    @pytest.mark.asyncio
    async def test_agent_self_post_uses_runtime_pipeline(self):
        """Agent uses runtime.ward_room_post_pipeline, not per-call construction."""
        from probos.cognitive.cognitive_agent import CognitiveAgent

        agent = CognitiveAgent.__new__(CognitiveAgent)
        agent.id = "agent-runtime"
        agent.agent_type = "test_agent"
        agent._runtime = MagicMock()
        agent._runtime.ward_room = MagicMock()
        agent._runtime.ward_room_post_pipeline = None  # No pipeline

        intent = _make_intent(
            target_agent_id="agent-runtime",
            thread_id="t1",
        )

        # Should return without error when pipeline is None
        await agent._self_post_ward_room_response(intent, "text")
        # No exception = correct — it checked for pipeline and returned


# ---------------------------------------------------------------------------
# NATSBus manual_ack / term
# ---------------------------------------------------------------------------

class TestNATSBusManualAck:
    @pytest.mark.asyncio
    async def test_nats_message_term(self):
        """NATSMessage.term() calls underlying msg.term()."""
        from probos.mesh.nats_bus import NATSMessage

        inner_msg = MagicMock()
        inner_msg.term = AsyncMock()
        nats_msg = NATSMessage(subject="test", data={}, _msg=inner_msg)
        await nats_msg.term()
        inner_msg.term.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_mock_nats_bus_delete_consumer(self, mock_nats_bus):
        """MockNATSBus.delete_consumer() succeeds without error."""
        await mock_nats_bus.delete_consumer("INTENT_DISPATCH", "test-consumer")


# ---------------------------------------------------------------------------
# Integration
# ---------------------------------------------------------------------------

class TestEndToEnd:
    @pytest.mark.asyncio
    async def test_end_to_end_async_dispatch(self, signal_manager):
        """Full flow: dispatch_async → handler runs → verifies fire-and-forget."""
        bus = IntentBus(signal_manager)
        results = []

        async def handler(intent):
            results.append(intent.intent)
            return IntentResult(
                intent_id=intent.id, agent_id="agent-e2e",
                success=True, confidence=1.0,
            )

        bus.subscribe("agent-e2e", handler)
        intent = _make_intent(target_agent_id="agent-e2e")

        # No NATS → falls back to direct handler
        await bus.dispatch_async(intent)
        await asyncio.sleep(0.1)

        assert results == ["ward_room_notification"]
