"""AD-1019c: McpWorkbenchReaper — idle-TTL sweep + async lifecycle.

Driven through a real ``_FakeSource`` implementing the narrow
``IdleAdapterSource`` Protocol (a real object, not MagicMock) so the reaper's
loop/cancellation discipline is tested without a subprocess.
"""

from __future__ import annotations

import asyncio

import pytest

from probos.integrations.mcp_bridge.reaper import (
    IdleAdapterSource,
    McpWorkbenchReaper,
)


class _FakeSource:
    """Real structural ``IdleAdapterSource`` for the reaper tests."""

    def __init__(self, idle: list[str] | None = None, fail_on: str | None = None) -> None:
        self._idle = list(idle or [])
        self._fail_on = fail_on
        self.unloaded: list[str] = []

    def idle_tool_ids(self, ttl_seconds: float) -> list[str]:
        return list(self._idle)

    async def unload_tool(self, tool_id: str) -> None:
        if self._fail_on == tool_id:
            raise RuntimeError("boom")
        self.unloaded.append(tool_id)
        self._idle = [t for t in self._idle if t != tool_id]


def test_fake_source_conforms_to_protocol():
    assert isinstance(_FakeSource(), IdleAdapterSource)


@pytest.mark.asyncio
async def test_sweep_once_unloads_all_idle():
    source = _FakeSource(idle=["t1", "t2", "t3"])
    reaper = McpWorkbenchReaper(source, idle_ttl_seconds=1.0, interval_seconds=3600)

    count = await reaper.sweep_once()

    assert count == 3
    assert set(source.unloaded) == {"t1", "t2", "t3"}


@pytest.mark.asyncio
async def test_sweep_once_honest_degrade_on_unload_error():
    source = _FakeSource(idle=["t1", "bad", "t2"], fail_on="bad")
    reaper = McpWorkbenchReaper(source, idle_ttl_seconds=1.0, interval_seconds=3600)

    count = await reaper.sweep_once()  # must NOT raise

    assert count == 2  # t1 + t2 unloaded; bad logged + skipped
    assert "bad" not in source.unloaded


@pytest.mark.asyncio
async def test_start_is_idempotent():
    source = _FakeSource()
    reaper = McpWorkbenchReaper(source, idle_ttl_seconds=1.0, interval_seconds=3600)
    await reaper.start()
    task1 = reaper._task
    await reaper.start()
    assert reaper._task is task1
    await reaper.stop()


@pytest.mark.asyncio
async def test_stop_without_start_is_noop():
    reaper = McpWorkbenchReaper(_FakeSource(), idle_ttl_seconds=1.0, interval_seconds=3600)
    await reaper.stop()  # must not raise
    assert reaper._task is None


@pytest.mark.asyncio
async def test_loop_sweeps_in_background():
    source = _FakeSource(idle=["t1", "t2"])
    reaper = McpWorkbenchReaper(source, idle_ttl_seconds=0.0, interval_seconds=3600)

    await reaper.start()
    # The loop runs sweep_once immediately on entry (before the first wait).
    for _ in range(50):
        if set(source.unloaded) == {"t1", "t2"}:
            break
        await asyncio.sleep(0.01)
    await reaper.stop()

    assert set(source.unloaded) == {"t1", "t2"}
    assert reaper._task is None


@pytest.mark.asyncio
async def test_stop_cancels_cleanly():
    source = _FakeSource()
    reaper = McpWorkbenchReaper(source, idle_ttl_seconds=1.0, interval_seconds=3600)
    await reaper.start()
    await reaper.stop()  # cancels the waiting loop, swallows CancelledError
    assert reaper._task is None
