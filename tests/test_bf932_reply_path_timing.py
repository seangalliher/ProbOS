"""BF-932 (#1670): timing lines of the Captain-DM reply path (the route, the agent's turn, the concurrency queue).

Synthetic fixtures only: stubs that sleep 30 ms, ``test-id`` and ``test-agent``. ``built`` cases fail on the base at their
own assert; ``BF932_RUNXFAIL=1`` runs them as plain cases.
"""

from __future__ import annotations

import asyncio
import logging
import re
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from probos.cognitive.cognitive_agent import CognitiveAgent
from probos.cognitive.concurrency_manager import ConcurrencyManager
from probos.cognitive.llm_client import MockLLMClient
from probos.config import CognitiveConfig
from probos.routers import agents as agents_router
from probos.routers.agents import agent_chat
from probos.security.pii_redaction import PIIRedactor
from probos.types import IntentDescriptor

def built(func):
    """BF-932 M2: the built cases pass; the marker no longer fails them."""
    return func

_CREW_PATCH = patch("probos.routers.agents.is_crew_agent", return_value=True)
_ROUTE = "BF-932: dm route"
_TURN = "BF-932: dm turn"


def _lines(caplog, marker: str) -> list[str]:
    return [r.getMessage() for r in caplog.records if marker in r.getMessage()]


def _field(line: str, name: str) -> str:
    found = re.search(rf"\b{name}=(\S+)", line)
    assert found, f"{name} missing from {line!r}"
    return found.group(1)


def _one(lines: list[str]) -> str:
    assert len(lines) == 1, f"expected exactly one line, found {len(lines)}"
    return lines[0]


class _DmAgent(CognitiveAgent):
    """A minimal crew agent that accepts a direct message: the construction ``tests/test_cognitive_agent.py`` uses."""

    agent_type = "test_dm"
    _handled_intents = {"direct_message"}
    instructions = "You are a test agent. Respond concisely."
    intent_descriptors = [
        IntentDescriptor(name="direct_message", params={"text": "input"}, description="Direct message", tier="domain")
    ]


@pytest.fixture
def make_agent():
    return lambda: _DmAgent(llm_client=MockLLMClient())


def _req(message: str = "hello"):
    r = MagicMock()
    r.message = message
    r.history = []
    r.attachment_ids = []
    r.thread_id = None
    r.system_trigger = False
    return r


class _Consumer:
    """The vision consumer's seam: records its calls and the order, sleeps 30 ms, may raise (no MagicMock at this boundary)."""

    def __init__(self, order: list[str], fail: bool = False) -> None:
        self.order, self.fail, self.timeouts = order, fail, []

    async def force_describe_current_frame(self, session_id=None, *, timeout_s: float = 4.0):
        self.order.append("consumer")
        self.timeouts.append(timeout_s)
        await asyncio.sleep(0.03)
        if self.fail:
            raise RuntimeError("hook failed")
        return "scene"


def _runtime(order: list[str], *, perception: bool = True, fail: bool = False, forward=None):
    runtime = MagicMock()
    agent = MagicMock()
    agent.id = "test-id"
    agent.agent_type = "science_officer"
    agent.confidence = 0.7
    runtime.registry.get.return_value = agent
    runtime.callsign_registry.get_callsign.return_value = "test-callsign"
    result = MagicMock()
    result.result = "Acknowledged."
    result.error = None

    async def _send(intent, raise_on_denial=False):
        order.append("send")
        await asyncio.sleep(0.03)
        if forward is not None:
            await forward(intent)
        return result

    runtime.intent_bus.send = AsyncMock(side_effect=_send)
    runtime.recreation_service = None
    runtime.ward_room = None
    runtime.config = SimpleNamespace(
        attachments=SimpleNamespace(enabled=False),
        cognitive=CognitiveConfig(),
        perception=SimpleNamespace(enabled=perception, dm_force_describe_enabled=True),
        dm_targeted_lookup=SimpleNamespace(enabled=False),
    )
    runtime.llm_client = MagicMock()
    runtime.episodic_memory = None
    from probos.cognitive.dm_sanity_gate import DmSanityGate
    runtime.dm_sanity_gate = DmSanityGate()
    runtime.vision_consumer = _Consumer(order, fail=fail)
    return runtime


async def _dm(runtime):
    with _CREW_PATCH:
        return await agent_chat("test-id", _req(), runtime)


@built
@pytest.mark.asyncio
async def test_r1_a_captain_dm_writes_one_route_line_with_each_step_and_the_intent_id(caplog) -> None:
    caplog.set_level(logging.INFO, logger="probos.routers.agents")
    order: list[str] = []
    runtime = _runtime(order)
    await _dm(runtime)
    runtime.intent_bus.send.assert_awaited_once()
    line = _one(_lines(caplog, _ROUTE))
    sent = runtime.intent_bus.send.call_args.args[0]
    assert _field(line, "intent") == sent.id[:8] and _field(line, "agent") == "test-id"
    assert _field(line, "hook") == "ran" and _field(line, "sent") == "yes"
    assert float(_field(line, "hook_ms")) >= 25 and float(_field(line, "send_ms")) >= 25
    assert float(_field(line, "total_ms")) >= 50
    for name in ("thread_ms", "prep_ms", "dispatch_ms"):
        float(_field(line, name))


@built
@pytest.mark.asyncio
async def test_r2_a_dm_with_perception_off_says_the_hook_was_skipped(caplog) -> None:
    caplog.set_level(logging.INFO, logger="probos.routers.agents")
    order: list[str] = []
    runtime = _runtime(order, perception=False)
    await _dm(runtime)
    runtime.intent_bus.send.assert_awaited_once()
    line = _one(_lines(caplog, _ROUTE))
    assert _field(line, "hook") == "skipped" and _field(line, "hook_ms") == "0" and order == ["send"]


@built
@pytest.mark.asyncio
async def test_r3_a_hook_that_raises_is_still_timed_and_the_reply_still_goes_out(caplog) -> None:
    caplog.set_level(logging.INFO, logger="probos.routers.agents")
    order: list[str] = []
    runtime = _runtime(order, fail=True)
    answer = await _dm(runtime)
    runtime.intent_bus.send.assert_awaited_once()
    line = _one(_lines(caplog, _ROUTE))
    assert _field(line, "hook") == "ran" and answer["response"] == "Acknowledged."


@pytest.mark.asyncio
async def test_r4_the_routes_order_cap_and_reply_are_unchanged() -> None:
    order: list[str] = []
    runtime = _runtime(order)
    answer = await _dm(runtime)
    runtime.intent_bus.send.assert_awaited_once()
    assert order == ["consumer", "send"] and runtime.vision_consumer.timeouts == [4.0]
    assert runtime.intent_bus.send.call_args.kwargs == {"raise_on_denial": True}
    assert answer["response"] == "Acknowledged."


@built
@pytest.mark.asyncio
async def test_r5_the_route_line_survives_the_log_redactor(caplog) -> None:
    caplog.set_level(logging.INFO, logger="probos.routers.agents")
    await _dm(_runtime([]))
    line = _one(_lines(caplog, _ROUTE))
    assert PIIRedactor.redact_all(line) == line


@pytest.mark.asyncio
async def test_r6_a_failing_logger_changes_nothing(monkeypatch) -> None:
    real = agents_router.logger

    class _Logger:
        """The route's logger, except that its INFO call raises for a BF-932 line and its DEBUG call for the helper's note of it."""

        def __init__(self) -> None:
            self.failed = {"info": 0, "debug": 0}

        def __getattr__(self, name):
            return getattr(real, name)

        def info(self, msg, *args, **kwargs):
            if str(msg).startswith("BF-932:"):
                self.failed["info"] += 1
                raise RuntimeError("handler failed")
            return real.info(msg, *args, **kwargs)

        def debug(self, msg, *args, **kwargs):
            if str(msg).startswith("BF-930:"):
                self.failed["debug"] += 1
                raise RuntimeError("handler failed")
            return real.debug(msg, *args, **kwargs)

    failing = _Logger()
    monkeypatch.setattr(agents_router, "logger", failing)
    answer = await _dm(_runtime([]))
    assert answer["response"] == "Acknowledged."
    assert failing.failed == {"info": 1, "debug": 1}


@built
@pytest.mark.asyncio
async def test_c1_a_promoted_intent_reports_how_long_it_waited(caplog) -> None:
    caplog.set_level(logging.INFO, logger="probos.cognitive.concurrency_manager")
    manager = ConcurrencyManager("test-agent", max_concurrent=1, queue_max_size=2)
    held = await manager.acquire("proactive_think", 2)
    waiter = asyncio.create_task(manager.acquire("direct_message", 8))
    await asyncio.sleep(0.08)
    await manager.release(held)
    await asyncio.wait_for(waiter, 5)
    [line] = _lines(caplog, "AD-672: Promoted queued intent")
    assert line.startswith("AD-672: Promoted queued intent 'direct_message' for agent test-agent at priority=8")
    assert float(_field(line, "waited_ms")) >= 60  # the queue stamps with time.monotonic (15.6 ms ticks on Windows)


@pytest.mark.asyncio
async def test_c2_an_intent_that_gets_a_slot_at_once_logs_no_promotion_line(caplog) -> None:
    caplog.set_level(logging.INFO, logger="probos.cognitive.concurrency_manager")
    manager = ConcurrencyManager("test-agent", max_concurrent=1, queue_max_size=2)
    thread_id = await manager.acquire("direct_message", 8)
    await manager.release(thread_id)
    assert not _lines(caplog, "Promoted queued intent")


def _slow(delay: float, result=None):
    async def stub(*_a, **_k):
        await asyncio.sleep(delay)
        return result
    return stub


async def _turn(agent, monkeypatch, *, sender: str, caplog):
    from probos.types import IntentMessage
    caplog.set_level(logging.INFO, logger="probos.cognitive.cognitive_agent")
    monkeypatch.setattr(agent, "perceive", _slow(0.03, {"intent": "direct_message", "params": {}}))
    monkeypatch.setattr(agent, "_recall_relevant_memories", _slow(0.03, {"intent": "direct_message", "params": {}}))

    async def stop(*_a, **_k):
        raise RuntimeError("end of the measured window")

    monkeypatch.setattr(agent, "decide", stop)
    intent = IntentMessage(intent="direct_message", params={"text": "hi", "from": sender}, target_agent_id=agent.id)
    with pytest.raises(RuntimeError, match="end of the measured window"):
        await agent.handle_intent(intent)
    return intent


@built
@pytest.mark.asyncio
async def test_a1_an_hxi_dm_turn_logs_its_perceive_and_recall_times_with_the_intent_id(make_agent, monkeypatch, caplog) -> None:
    intent = await _turn(make_agent(), monkeypatch, sender="hxi_profile", caplog=caplog)
    line = _one(_lines(caplog, _TURN))
    assert _field(line, "intent") == intent.id[:8]
    assert float(_field(line, "perceive_ms")) >= 25 and float(_field(line, "recall_ms")) >= 25


@pytest.mark.asyncio
async def test_a2_a_dm_from_another_sender_logs_no_turn_line(make_agent, monkeypatch, caplog) -> None:
    await _turn(make_agent(), monkeypatch, sender="crew_member", caplog=caplog)
    assert not _lines(caplog, _TURN)


@built
@pytest.mark.asyncio
async def test_r1b_one_captain_dm_is_joinable_from_the_route_line_to_the_turn_line(make_agent, monkeypatch, caplog) -> None:
    caplog.set_level(logging.INFO)
    agent = make_agent()
    monkeypatch.setattr(agent, "perceive", _slow(0.0, {"intent": "direct_message", "params": {}}))
    monkeypatch.setattr(agent, "_recall_relevant_memories", _slow(0.0, {"intent": "direct_message", "params": {}}))
    monkeypatch.setattr(agent, "decide", _slow(0.0, {"action": "none"}))

    async def forward(intent):
        try:
            await agent.handle_intent(intent)
        except Exception:
            pass  # the turn's later stages are not under test; the line precedes them

    await _dm(_runtime([], forward=forward))
    route = _one(_lines(caplog, _ROUTE))
    turn = _one(_lines(caplog, _TURN))
    assert _field(route, "intent") == _field(turn, "intent")
