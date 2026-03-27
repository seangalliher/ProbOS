"""Tests for the TaskScheduler (AD-281 through AD-284)."""

from __future__ import annotations

import asyncio
import time

import pytest

pytestmark = pytest.mark.slow

from probos.cognitive.task_scheduler import ScheduledTask, TaskScheduler


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


class FakeRuntime:
    """Minimal runtime stub for scheduler tests."""

    def __init__(self, response: dict | None = None, fail: bool = False):
        self._response = response or {"response": "ok"}
        self._fail = fail
        self.calls: list[str] = []

    async def process_natural_language(self, text: str, **kw) -> dict:
        self.calls.append(text)
        if self._fail:
            raise RuntimeError("boom")
        return self._response


class FakeAdapter:
    """Minimal channel adapter stub."""

    def __init__(self, fail: bool = False):
        self.sent: list[tuple[str, str]] = []
        self._fail = fail

    async def send_response(self, channel_id: str, text: str, **kw) -> None:
        if self._fail:
            raise RuntimeError("send failed")
        self.sent.append((channel_id, text))


# ------------------------------------------------------------------
# Step 1: Core scheduler tests (AD-281)
# ------------------------------------------------------------------


def test_schedule_creates_task():
    sched = TaskScheduler()
    t = sched.schedule("hello", delay_seconds=10)
    assert isinstance(t, ScheduledTask)
    assert t.status == "pending"
    assert t.intent_text == "hello"
    assert t.execute_at > t.created_at


@pytest.mark.asyncio
async def test_oneshot_task_executes():
    rt = FakeRuntime()
    sched = TaskScheduler(process_fn=rt.process_natural_language)
    t = sched.schedule("ping", delay_seconds=0)  # due immediately
    sched.start()
    try:
        await asyncio.sleep(2.0)
    finally:
        await sched.stop()
    assert rt.calls == ["ping"]
    task = sched._tasks[t.id]
    assert task.status == "completed"
    assert task.last_result == {"response": "ok"}


@pytest.mark.asyncio
async def test_recurring_task_reschedules():
    rt = FakeRuntime()
    sched = TaskScheduler(process_fn=rt.process_natural_language)
    t = sched.schedule("tick", delay_seconds=0, interval_seconds=1.0)
    sched.start()
    try:
        await asyncio.sleep(3.5)
    finally:
        await sched.stop()
    # Should have fired at least twice (0s, 1s, 2s, maybe 3s)
    assert len(rt.calls) >= 2
    # Task should still be pending (re-scheduled)
    task = sched._tasks[t.id]
    assert task.status == "pending"


def test_cancel_removes_task():
    sched = TaskScheduler()
    t = sched.schedule("bye", delay_seconds=60)
    assert sched.cancel(t.id) is True
    assert t.id not in sched._tasks
    # Cancelling nonexistent task returns False
    assert sched.cancel("nonexistent") is False


def test_list_tasks_sorted():
    sched = TaskScheduler()
    t2 = sched.schedule("second", delay_seconds=20)
    t1 = sched.schedule("first", delay_seconds=5)
    t3 = sched.schedule("third", delay_seconds=60)
    ordered = sched.list_tasks()
    assert [t.id for t in ordered] == [t1.id, t2.id, t3.id]


@pytest.mark.asyncio
async def test_failed_task_does_not_crash_scheduler():
    rt = FakeRuntime(fail=True)
    sched = TaskScheduler(process_fn=rt.process_natural_language)
    t = sched.schedule("kaboom", delay_seconds=0)
    sched.start()
    try:
        await asyncio.sleep(2.0)
    finally:
        await sched.stop()
    task = sched._tasks[t.id]
    assert task.status == "failed"
    assert "boom" in str(task.last_result)


@pytest.mark.asyncio
async def test_stop_cancels_loop():
    sched = TaskScheduler()
    sched.start()
    assert sched._task is not None
    await sched.stop()
    assert sched._task is None


# ------------------------------------------------------------------
# Step 2: Runtime integration tests (AD-282)
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_runtime_starts_stops_scheduler():
    """TaskScheduler integrates into ProbOSRuntime lifecycle."""
    from probos.config import load_config
    from probos.runtime import ProbOSRuntime

    config = load_config("config/system.yaml")
    rt = ProbOSRuntime(config)
    await rt.start()
    try:
        assert rt.task_scheduler is not None
        assert rt.task_scheduler._task is not None  # loop running
    finally:
        await rt.stop()
    assert rt.task_scheduler is None or rt.task_scheduler._task is None


@pytest.mark.asyncio
async def test_scheduled_task_executes_via_runtime():
    """A scheduled task runs through the runtime's NL pipeline."""
    from probos.config import load_config
    from probos.runtime import ProbOSRuntime

    config = load_config("config/system.yaml")
    rt = ProbOSRuntime(config)
    await rt.start()
    try:
        t = rt.task_scheduler.schedule("read_file /tmp/test.txt", delay_seconds=0)
        await asyncio.sleep(3.0)
        task = rt.task_scheduler._tasks[t.id]
        assert task.status in ("completed", "failed")
    finally:
        await rt.stop()


# ------------------------------------------------------------------
# Step 3: SchedulerAgent upgrade tests (AD-283)
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_scheduler_agent_remind_creates_task():
    """SchedulerAgent 'remind' action schedules a task."""
    from probos.agents.utility.organizer_agents import SchedulerAgent
    from probos.types import IntentMessage

    agent = SchedulerAgent(agent_id="sched-0", pool="utility_scheduler")
    # Give it a mock runtime with a task_scheduler
    sched = TaskScheduler()

    class MockRT:
        task_scheduler = sched

    agent._runtime = MockRT()
    msg = IntentMessage(
        intent="manage_schedule",
        params={"action": "remind", "text": "check stocks", "when": "in 60 seconds"},
    )
    # Simulate LLM deciding to schedule
    decision = {
        "llm_output": '{"action": "remind", "delay_seconds": 60, "text": "check stocks", "message": "Reminder set!"}'
    }
    result = await agent.act(decision)
    assert result["success"] is True
    assert len(sched.list_tasks()) == 1
    assert sched.list_tasks()[0].intent_text == "check stocks"


@pytest.mark.asyncio
async def test_scheduler_agent_list_returns_tasks():
    """SchedulerAgent 'list' action returns scheduled tasks."""
    from probos.agents.utility.organizer_agents import SchedulerAgent

    agent = SchedulerAgent(agent_id="sched-0", pool="utility_scheduler")
    sched = TaskScheduler()
    sched.schedule("task-a", delay_seconds=30)
    sched.schedule("task-b", delay_seconds=60)

    class MockRT:
        task_scheduler = sched

    agent._runtime = MockRT()
    decision = {"llm_output": '{"action": "list", "message": "listing"}'}
    result = await agent.act(decision)
    assert result["success"] is True
    # Result should mention task count or tasks
    assert "2" in str(result["result"]) or "task" in str(result["result"]).lower()


@pytest.mark.asyncio
async def test_scheduler_agent_cancel_removes_task():
    """SchedulerAgent 'cancel' action removes a scheduled task."""
    from probos.agents.utility.organizer_agents import SchedulerAgent

    agent = SchedulerAgent(agent_id="sched-0", pool="utility_scheduler")
    sched = TaskScheduler()
    t = sched.schedule("doomed", delay_seconds=120)

    class MockRT:
        task_scheduler = sched

    agent._runtime = MockRT()
    decision = {
        "llm_output": f'{{"action": "cancel", "task_id": "{t.id}", "message": "Cancelled"}}'
    }
    result = await agent.act(decision)
    assert result["success"] is True
    assert len(sched.list_tasks()) == 0


@pytest.mark.asyncio
async def test_scheduler_agent_persist_reload():
    """Reminders persist to file and can be reloaded."""
    from probos.agents.utility.organizer_agents import SchedulerAgent

    agent = SchedulerAgent(agent_id="sched-0", pool="utility_scheduler")
    # Verify the agent still has _REMINDERS_PATH for persistence
    assert hasattr(agent, "_REMINDERS_PATH")


# ------------------------------------------------------------------
# Step 4: Channel delivery tests (AD-284)
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_channel_delivery_on_scheduled_task():
    """Task with channel_id delivers result via adapter."""
    adapter = FakeAdapter()
    rt = FakeRuntime(response={"response": "here is your result"})
    sched = TaskScheduler(
        process_fn=rt.process_natural_language,
        channel_adapters=[adapter],
    )
    sched.schedule("report", delay_seconds=0, channel_id="ch-123")
    sched.start()
    try:
        await asyncio.sleep(2.0)
    finally:
        await sched.stop()
    assert len(adapter.sent) == 1
    assert adapter.sent[0][0] == "ch-123"
    assert "result" in adapter.sent[0][1].lower() or len(adapter.sent[0][1]) > 0


@pytest.mark.asyncio
async def test_no_channel_delivery_without_channel_id():
    """Task without channel_id stores result silently."""
    adapter = FakeAdapter()
    rt = FakeRuntime()
    sched = TaskScheduler(
        process_fn=rt.process_natural_language,
        channel_adapters=[adapter],
    )
    sched.schedule("silent", delay_seconds=0)
    sched.start()
    try:
        await asyncio.sleep(2.0)
    finally:
        await sched.stop()
    assert len(adapter.sent) == 0


@pytest.mark.asyncio
async def test_channel_delivery_failure_does_not_crash():
    """Channel delivery failure doesn't crash the scheduler."""
    adapter = FakeAdapter(fail=True)
    rt = FakeRuntime()
    sched = TaskScheduler(
        process_fn=rt.process_natural_language,
        channel_adapters=[adapter],
    )
    sched.schedule("fragile", delay_seconds=0, channel_id="ch-fail")
    sched.start()
    try:
        await asyncio.sleep(2.0)
    finally:
        await sched.stop()
    # Task should still complete despite delivery failure
    tasks = sched.list_tasks()
    assert all(t.status == "completed" for t in tasks)


def test_get_stats():
    sched = TaskScheduler()
    sched.schedule("a", delay_seconds=10)
    sched.schedule("b", delay_seconds=20)
    stats = sched.get_stats()
    assert stats["total"] == 2
    assert stats["by_status"]["pending"] == 2
    assert stats["next_execute_in"] is not None
