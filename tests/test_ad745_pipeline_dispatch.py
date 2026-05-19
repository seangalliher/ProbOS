"""AD-745: pipeline dispatch tests.

Direct unit tests of ``DmReplyPipeline.step_4e_action_dispatch`` driven
by a minimal real-config + fake-runtime fixture. Mirrors the
BF-286/287 pattern: real ``SystemConfig`` (so config fields validate
properly) + ``_Fake*`` stubs for runtime collaborators.
"""
from __future__ import annotations

from typing import Any

import pytest

from probos.cognitive.dm.action_dispatcher import ActionDispatcher, ActionStatus
from probos.cognitive.dm.reply_pipeline import DmReplyContext, DmReplyPipeline
from probos.config import SystemConfig


class _FakeBrowserTool:
    """Minimal BrowserTool stub. Returns canned results from ``invoke``."""

    def __init__(self, last_url: str | None = None) -> None:
        self._session = _FakeSession(last_url)
        self.invoked: list[dict[str, Any]] = []

    def get_session(self, agent_id: str):
        return self._session

    async def invoke(self, params: dict[str, Any], context: dict[str, Any] | None = None):
        self.invoked.append({"params": dict(params), "context": dict(context or {})})

        class _R:
            output = {"ok": True}
            error = None
        return _R()


class _FakeSession:
    def __init__(self, last_url: str | None) -> None:
        self.session_id = "sess-1"
        self.last_url = last_url
        self.aborted = False


class _FakeEpisodic:
    def __init__(self) -> None:
        self.stored: list[Any] = []

    async def store(self, ep: Any) -> None:
        self.stored.append(ep)


def _build_runtime(
    *,
    enabled: bool = True,
    page_url: str | None = None,
    max_per_dm_turn: int = 1,
    autonomous_cap: int = 5,
    destructive_patterns: list[str] | None = None,
) -> Any:
    cfg = SystemConfig()
    cfg.browser_tool.action_dispatch_enabled = enabled
    cfg.browser_tool.action_dispatch_max_per_dm_turn = max_per_dm_turn
    cfg.browser_tool.action_dispatch_max_consecutive_autonomous = autonomous_cap
    if destructive_patterns is not None:
        cfg.browser_tool.destructive_url_patterns = list(destructive_patterns)

    class _RT:
        config = cfg
        action_dispatcher = ActionDispatcher()
        browser_tool = _FakeBrowserTool(last_url=page_url)
        episodic_memory = _FakeEpisodic()

    return _RT()


def _build_pipeline(runtime: Any, reply_text: str) -> DmReplyPipeline:
    ctx = DmReplyContext(
        runtime=runtime,
        agent=object(),
        agent_id="counselor",
        callsign="Counselor",
        req_message="captain DM text",
        response_text=reply_text,
        has_image_attachment=False,
        per_attachment=[],
        sanity_gate=None,
        params={"thread_id": "t-1", "dm_turn_id": "turn-1"},
        message_text="captain DM text",
        sampling_state=None,
        avatar_event_bus=None,
    )
    return DmReplyPipeline(ctx)


@pytest.mark.asyncio
async def test_tier1_screenshot_dispatches_inline() -> None:
    runtime = _build_runtime()
    reply = 'Looking. [ACTION: {"verb":"screenshot","args":{}}]'
    pipe = _build_pipeline(runtime, reply)
    await pipe.step_4e_action_dispatch()

    actions = runtime.action_dispatcher.list_for_thread("t-1")
    assert len(actions) == 1
    a = actions[0]
    assert a.verb == "screenshot"
    assert a.tier == 1
    assert a.status == ActionStatus.EXECUTED
    # BrowserTool.invoke called once.
    assert len(runtime.browser_tool.invoked) == 1
    # Marker stripped from Captain-visible reply.
    assert "[ACTION" not in pipe.ctx.response_text


@pytest.mark.asyncio
async def test_tier2_click_blocks_on_ack() -> None:
    runtime = _build_runtime()
    reply = '[ACTION: {"verb":"click","args":{"selector":"#submit"},"intent":"submit form"}]'
    pipe = _build_pipeline(runtime, reply)
    await pipe.step_4e_action_dispatch()

    actions = runtime.action_dispatcher.list_for_thread("t-1")
    assert len(actions) == 1
    a = actions[0]
    assert a.verb == "click"
    assert a.tier == 2
    assert a.status == ActionStatus.ACK_PENDING
    # BrowserTool NOT invoked yet — waiting for Captain ACK.
    assert runtime.browser_tool.invoked == []


@pytest.mark.asyncio
async def test_tier3_compute_use_click_blocks_on_confirm() -> None:
    runtime = _build_runtime()
    reply = '[ACTION: {"verb":"compute_use_click","args":{"target":"button"}}]'
    pipe = _build_pipeline(runtime, reply)
    await pipe.step_4e_action_dispatch()

    actions = runtime.action_dispatcher.list_for_thread("t-1")
    assert len(actions) == 1
    a = actions[0]
    assert a.verb == "compute_use_click"
    assert a.tier == 3
    assert a.status == ActionStatus.CONFIRM_PENDING
    assert runtime.browser_tool.invoked == []


@pytest.mark.asyncio
async def test_destructive_url_forces_tier3() -> None:
    """Tier-2 verb (click) on a destructive URL gets forced to tier-3."""
    runtime = _build_runtime(page_url="https://shop.example.com/checkout/pay")
    reply = '[ACTION: {"verb":"click","args":{"selector":"#pay"}}]'
    pipe = _build_pipeline(runtime, reply)
    await pipe.step_4e_action_dispatch()

    a = runtime.action_dispatcher.list_for_thread("t-1")[0]
    assert a.tier == 3
    assert a.destructive_pattern_match is not None
    assert "checkout" in a.destructive_pattern_match
    assert a.status == ActionStatus.CONFIRM_PENDING


@pytest.mark.asyncio
async def test_consecutive_cap_forces_tier3() -> None:
    """After N tier-1/2 EXECUTED actions, next dispatch is forced to tier-3."""
    runtime = _build_runtime(autonomous_cap=2)
    # Pre-seed dispatcher counter at the cap.
    runtime.action_dispatcher._consec_autonomous[("captain", "counselor")] = 2

    reply = '[ACTION: {"verb":"click","args":{"selector":"#go"}}]'
    pipe = _build_pipeline(runtime, reply)
    await pipe.step_4e_action_dispatch()

    a = runtime.action_dispatcher.list_for_thread("t-1")[0]
    assert a.tier == 3
    assert a.status == ActionStatus.CONFIRM_PENDING


@pytest.mark.asyncio
async def test_per_turn_cap_enforced(caplog) -> None:
    """Per-DM-turn cap drops the extra envelopes with a WARNING."""
    runtime = _build_runtime(max_per_dm_turn=1)
    reply = (
        '[ACTION: {"verb":"screenshot","args":{}}] '
        '[ACTION: {"verb":"state","args":{}}]'
    )
    pipe = _build_pipeline(runtime, reply)
    with caplog.at_level("WARNING"):
        await pipe.step_4e_action_dispatch()

    actions = runtime.action_dispatcher.list_for_thread("t-1")
    assert len(actions) == 1
    assert any("AD-745" in r.message and "extras dropped" in r.message
               for r in caplog.records)


@pytest.mark.asyncio
async def test_master_switch_off_drops_action(caplog) -> None:
    """When action_dispatch_enabled=False, the reply is untouched."""
    runtime = _build_runtime(enabled=False)
    reply = '[ACTION: {"verb":"screenshot","args":{}}] hi'
    pipe = _build_pipeline(runtime, reply)
    await pipe.step_4e_action_dispatch()
    # Nothing dispatched, nothing stripped.
    assert runtime.action_dispatcher.list_for_thread("t-1") == []
    assert "[ACTION" in pipe.ctx.response_text


@pytest.mark.asyncio
async def test_missing_dispatcher_honest_degrade(caplog) -> None:
    """Missing runtime.action_dispatcher logs WARNING + strips markers."""
    runtime = _build_runtime()
    runtime.action_dispatcher = None  # simulate missing
    reply = 'Hi [ACTION: {"verb":"screenshot","args":{}}] there.'
    pipe = _build_pipeline(runtime, reply)
    with caplog.at_level("WARNING"):
        await pipe.step_4e_action_dispatch()
    assert "[ACTION" not in pipe.ctx.response_text
    assert any("action_dispatcher missing" in r.message for r in caplog.records)
