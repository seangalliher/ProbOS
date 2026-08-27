"""AD-1276 Section 3 (BF-789, #1253): the Yeoman digest task reports its failures.

``_emit_digest`` created a background broadcast whose only done-callback was
``set.discard``, so ``task.exception()`` was never called and every failure of
that broadcast was lost.

Issue #1253 attributes this to a policy denial becoming an unretrieved task
exception. It does not: ``broadcast``'s default denial shape is ``[]``, and
this call does not opt into ``raise_on_denial``. The last test here pins that
actual shape so the next reader does not re-adopt the wrong premise.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import pytest

from probos.cognitive.yeoman import YeomanAgent
from probos.types import IntentMessage

pytestmark = pytest.mark.asyncio


class _Bus:
    def __init__(self, *, raises: BaseException | None = None, returns: Any = None):
        self._raises = raises
        self._returns = returns
        self.broadcasts: list[IntentMessage] = []

    async def broadcast(self, intent: IntentMessage, *_a: Any, **_k: Any) -> Any:
        self.broadcasts.append(intent)
        if self._raises is not None:
            raise self._raises
        return self._returns


class _Runtime:
    def __init__(self, bus: _Bus) -> None:
        self.intent_bus = bus


@pytest.fixture(autouse=True)
def _reset_yeoman_singleton():
    YeomanAgent._live_instance_count = 0
    yield
    YeomanAgent._live_instance_count = 0


def _make_yeo(bus: _Bus | None) -> YeomanAgent:
    agent = object.__new__(YeomanAgent)
    agent.id = "yeoman-001"
    agent.callsign = "Yeo"
    agent._runtime = None if bus is None else _Runtime(bus)
    agent._pending_dispatch_tasks = set()
    return agent


def _digest() -> dict[str, Any]:
    return {"scan_count": 1, "items": []}


async def _settle(agent: YeomanAgent) -> None:
    """Await the digest task itself, not a duration that correlates with it."""
    tasks = list(agent._pending_dispatch_tasks)
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)
    # The discard callback runs on the next loop iteration after completion.
    await asyncio.sleep(0)


class TestTheDigestTaskReportsItsFailures:
    async def test_an_exception_in_the_digest_broadcast_is_logged_not_swallowed(
        self, caplog
    ):
        agent = _make_yeo(_Bus(raises=RuntimeError("bus exploded")))

        with caplog.at_level(logging.ERROR, logger="probos.cognitive.yeoman"):
            await agent._emit_digest(_digest())
            await _settle(agent)

        assert any(
            "Yeoman digest broadcast failed" in r.message
            and r.levelno == logging.ERROR
            for r in caplog.records
        ), f"nothing reported the failure; records={[r.message for r in caplog.records]}"

    async def test_the_failure_log_names_the_exception_type(self, caplog):
        agent = _make_yeo(_Bus(raises=ValueError("bad payload")))

        with caplog.at_level(logging.ERROR, logger="probos.cognitive.yeoman"):
            await agent._emit_digest(_digest())
            await _settle(agent)

        assert any("ValueError" in r.getMessage() for r in caplog.records)

    async def test_the_task_is_still_discarded_from_the_pending_set(self):
        agent = _make_yeo(_Bus(raises=RuntimeError("boom")))

        await agent._emit_digest(_digest())
        await _settle(agent)

        assert agent._pending_dispatch_tasks == set(), (
            "the reporting callback displaced the discard; the pending set "
            "would grow without bound"
        )

    async def test_a_cancelled_digest_task_does_not_log_an_error(self, caplog):
        """Cancellation is lifecycle control, not a fault to report."""
        started = asyncio.Event()

        class _Hanging(_Bus):
            async def broadcast(self, intent, *_a, **_k):
                started.set()
                await asyncio.Event().wait()

        agent = _make_yeo(_Hanging())

        with caplog.at_level(logging.ERROR, logger="probos.cognitive.yeoman"):
            await agent._emit_digest(_digest())
            await started.wait()
            for task in list(agent._pending_dispatch_tasks):
                task.cancel()
            await _settle(agent)

        assert [r.message for r in caplog.records] == []

    async def test_a_successful_digest_broadcast_logs_nothing(self, caplog):
        agent = _make_yeo(_Bus(returns=[]))

        with caplog.at_level(logging.ERROR, logger="probos.cognitive.yeoman"):
            await agent._emit_digest(_digest())
            await _settle(agent)

        assert [r.message for r in caplog.records] == []

    async def test_a_policy_denial_returns_an_empty_list_and_is_not_reported_as_an_exception(
        self, caplog
    ):
        """Pins the ACTUAL shape. #1253 says a denial becomes an unretrieved
        task exception; ``broadcast``'s default denial shape is ``[]`` and this
        call does not opt into ``raise_on_denial``, so it does not."""
        bus = _Bus(returns=[])
        agent = _make_yeo(bus)

        with caplog.at_level(logging.ERROR, logger="probos.cognitive.yeoman"):
            await agent._emit_digest(_digest())
            await _settle(agent)

        assert len(bus.broadcasts) == 1
        assert [r.message for r in caplog.records] == []

    async def test_the_no_running_loop_fallback_path_is_unchanged(self, monkeypatch):
        """No loop means the broadcast is awaited inline, with no task and so
        no callback to report through."""
        bus = _Bus(returns=[])
        agent = _make_yeo(bus)

        def _no_loop():
            raise RuntimeError("no running event loop")

        monkeypatch.setattr(asyncio, "get_running_loop", _no_loop)
        await agent._emit_digest(_digest())

        assert len(bus.broadcasts) == 1
        assert agent._pending_dispatch_tasks == set()

    async def test_a_runtime_without_an_intent_bus_still_drops_the_digest_quietly(
        self, caplog
    ):
        agent = _make_yeo(None)

        with caplog.at_level(logging.WARNING, logger="probos.cognitive.yeoman"):
            await agent._emit_digest(_digest())

        assert any("no intent_bus" in r.getMessage() for r in caplog.records)
        assert agent._pending_dispatch_tasks == set()
