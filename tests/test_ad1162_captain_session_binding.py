"""AD-1162: the producer for the session binding AD-1158 reads.

AD-1158 taught ``BrowserTool.invoke`` to read ``context["browser_session_id"]``
so an agent acts on the session the Captain is watching rather than spawning a
fresh, signed-out browser. Nothing outside tests ever *supplied* that key, so
the mechanism was inert: every agent browser call created a new session while
the Captain watched a different one.

That is the sixth instance of one shape in two days -- AD-1157 (classification
field, no caller), BF-688 (priority parameter, no caller), BF-690 (guard armed,
schema still advertised the refused actions), BF-692 (element discovery guards a
Playwright method that does not exist), BF-695 (the whole tool could not start
on Windows). In each the mechanism was correct and tested, and the thing that
would exercise it never did.

These tests pin the PRODUCER, not the reader -- the reader already had AD-1158's
suite and it passed while the feature did nothing.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from probos.cognitive.agentic_dispatch import WorkItemAgenticExecutor, _captain_browser_session_id
from probos.cognitive.swe_harness.tool_call import TextBlock, ToolCallRequest, ToolUseBlock
from probos.config import BrowserToolConfig
from probos.tools.browser.lifecycle import BrowserLifecycleConflict, BrowserLifecycleState
from probos.tools.browser.tool import BrowserTool
from probos.tools.protocol import ToolPermission, ToolResult
from probos.types import LLMResponse
from tests.test_browser_session_lifecycle import (
    _ACTOR, _bridge, browser_app, browser_clock, browser_invocations,
    lifecycle_tool, wired_browser_runtime,
)


class _SessionRowsTool(BrowserTool):
    """Exercise real binding against the public lifecycle metadata boundary."""

    def __init__(self, rows: list[dict[str, Any]]) -> None:
        super().__init__(config=BrowserToolConfig())
        self._rows = rows

    def list_sessions(self) -> list[dict[str, Any]]:
        return [
            {"state": BrowserLifecycleState.ACTIVE, "expires_at": 4102444800.0, **row}
            for row in self._rows
        ]


def _real_property(rows: list[dict[str, Any]]) -> str | None:
    """Drive the inherited property on an initialized BrowserTool."""
    return _SessionRowsTool(rows).captain_session_id


# -- the property ---------------------------------------------------------


def test_no_sessions_binds_nothing() -> None:
    assert _real_property([]) is None


def test_a_captain_session_is_bound() -> None:
    rows = [{"session_id": "sess-cap", "agent_id": "captain"}]
    assert _real_property(rows) == "sess-cap"


def test_an_agent_owned_session_is_never_bound() -> None:
    """An agent must not silently inherit another agent's browser."""
    rows = [{"session_id": "sess-ezri", "agent_id": "ezri-1"}]
    assert _real_property(rows) is None


def test_only_the_captain_row_is_selected_among_several_owners() -> None:
    rows = [
        {"session_id": "sess-a", "agent_id": "anvil-1"},
        {"session_id": "sess-cap", "agent_id": "captain"},
        {"session_id": "sess-b", "agent_id": "ezri-1"},
    ]
    assert _real_property(rows) == "sess-cap"


def test_the_most_recent_captain_session_wins_and_warns(
    caplog: pytest.LogCaptureFixture,
) -> None:
    rows = [
        {"session_id": "sess-old", "agent_id": "captain"},
        {"session_id": "sess-new", "agent_id": "captain"},
    ]
    import logging

    with caplog.at_level(logging.WARNING):
        assert _real_property(rows) == "sess-new"
    assert "AD-1162" in caplog.text
    assert "2 live browser sessions" in caplog.text


@pytest.mark.parametrize("bad", [None, "", 42, {"nested": "dict"}, []])
def test_a_malformed_session_id_binds_nothing(bad: Any) -> None:
    rows = [{"session_id": bad, "agent_id": "captain"}]
    assert _real_property(rows) is None


def test_a_row_missing_session_id_binds_nothing() -> None:
    assert _real_property([{"agent_id": "captain"}]) is None


@pytest.mark.parametrize("metadata", [
    {"state": BrowserLifecycleState.CREATING},
    {"state": BrowserLifecycleState.ENDING},
    {"state": BrowserLifecycleState.CLEANUP_FAILED},
    {"state": BrowserLifecycleState.ENDED},
    {"state": None},
    {"expires_at": 0},
    {"expires_at": None},
    {"expires_at": "4102444800"},
])
def test_unavailable_metadata_does_not_bind(metadata: dict[str, Any]) -> None:
    assert _real_property([{
        "session_id": "sess-cap", "agent_id": "captain", **metadata,
    }]) is None


def test_malformed_latest_row_does_not_substitute_older_session() -> None:
    assert _real_property([
        {"session_id": "sess-old", "agent_id": "captain"},
        {"session_id": None, "agent_id": "captain"},
    ]) is None


# -- the dispatch-side resolver -------------------------------------------


def test_resolver_returns_none_without_a_browser_tool() -> None:
    """Every runtime predating the browser tool must be unaffected."""
    assert _captain_browser_session_id(SimpleNamespace()) is None
    assert _captain_browser_session_id(SimpleNamespace(browser_tool=None)) is None


def test_resolver_returns_the_bound_session() -> None:
    tool = SimpleNamespace(captain_session={"session_id": "sess-cap"})
    assert _captain_browser_session_id(SimpleNamespace(browser_tool=tool)) == "sess-cap"


def test_resolver_degrades_when_the_property_raises(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """An ambient convenience must never be able to fail a run."""
    import logging

    class _Raising:
        @property
        def captain_session(self) -> dict[str, Any]:
            raise RuntimeError("session table corrupt")

    with caplog.at_level(logging.WARNING):
        result = _captain_browser_session_id(SimpleNamespace(browser_tool=_Raising()))
    assert result is None
    assert "AD-1163" in caplog.text


@pytest.mark.parametrize("bad", [None, "", 7, object()])
def test_resolver_rejects_a_non_str_binding(bad: Any) -> None:
    tool = SimpleNamespace(captain_session={"session_id": bad})
    assert _captain_browser_session_id(SimpleNamespace(browser_tool=tool)) is None


def test_resolver_tolerates_a_tool_without_the_property() -> None:
    """An older BrowserTool build lacks it; that is honest-degrade, not a crash."""
    assert _captain_browser_session_id(
        SimpleNamespace(browser_tool=SimpleNamespace())
    ) is None


class _ReservedRunLLM:
    def __init__(
        self, *, extra_session: bool = False, session_id: str | None = None,
        follow_up: bool = False, final_text: str = "done",
    ) -> None:
        self.announced = asyncio.Event()
        self.continue_to_tools = asyncio.Event()
        self.invoked = asyncio.Event()
        self.finish = asyncio.Event()
        self.calls = 0
        self.definitions: list[dict[str, Any]] = []
        self.extra_session = extra_session
        self.session_id = session_id
        self.follow_up = follow_up
        self.final_text = final_text
        self.feedback: list[str] = []

    async def complete(self, request: Any, **kwargs: Any) -> LLMResponse:
        self.calls += 1
        if self.calls == 1:
            self.definitions = list(request.tools or [])
            self.announced.set()
            await self.continue_to_tools.wait()
            arguments = {
                "action": "goto", "url": "https://selected.example/document",
            }
            if self.session_id is not None:
                arguments["session_id"] = self.session_id
            calls = [ToolCallRequest(name="browser", arguments=arguments)]
            if self.extra_session:
                calls.append(ToolCallRequest(name="browser", arguments={
                    "action": "goto", "url": "https://extra.example/document",
                    "session_id": "explicit-run-session",
                }))
            return LLMResponse(
                content="", tokens_used=1,
                content_blocks=[ToolUseBlock(tool_call=call) for call in calls],
            )
        self.feedback.append(request.prompt)
        self.invoked.set()
        await self.finish.wait()
        if self.follow_up and self.calls == 2:
            return LLMResponse(content="", tokens_used=1, content_blocks=[
                ToolUseBlock(tool_call=ToolCallRequest(name="browser", arguments={"action": "state"})),
            ])
        return LLMResponse(
            content=self.final_text, tokens_used=1,
            content_blocks=[TextBlock(text=self.final_text)],
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("completion", ["normal", "cancel", "failure"])
async def test_dispatch_handoff_reserves_announcement_context_invocation_and_finally(
    wired_browser_runtime: Any, monkeypatch: pytest.MonkeyPatch, completion: str,
) -> None:
    runtime, drivers, _ = wired_browser_runtime
    tool = runtime.browser_tool
    selected = await _bridge(tool)
    selected_navigation = await tool.invoke(
        {"action": "goto", "session_id": selected, "url": "https://user:password@selected.example/document?token=private#secret"},
        {"agent_id": "captain"},
    )
    assert selected_navigation.error is None
    other = await _bridge(tool)
    other_navigation = await tool.invoke(
        {"action": "goto", "session_id": other, "url": "https://other.example/unrelated-secret"},
        {"agent_id": "captain"},
    )
    assert other_navigation.error is None
    llm = _ReservedRunLLM()
    executor = WorkItemAgenticExecutor(llm_client=llm)
    if completion == "failure":
        async def fail_trace(*args: Any, **kwargs: Any) -> None:
            raise RuntimeError("trace persistence failed")
        monkeypatch.setattr(executor, "_persist_tool_trace", fail_trace)
    running: asyncio.Task[Any] | None = None
    async with AsyncClient(
        transport=ASGITransport(app=browser_app(runtime)), base_url="http://test",
        headers={"Authorization": "Bearer secret"},
    ) as client:
        try:
            response = await client.post(f"/api/browser/sessions/{selected}/handoff", json={"confirm": True})
            assert response.status_code == 200
            running = asyncio.create_task(executor.run(
                agent_id="crew-one", instructions="", task_text="Read the selected page", runtime=runtime,
            ))
            await asyncio.wait_for(llm.announced.wait(), 2)
            definition = next(item for item in llm.definitions if item["function"]["name"] == "browser")
            description = definition["function"]["description"]
            assert "shared with the Captain" in description
            assert "selected.example/document" in description
            assert all(secret not in description for secret in ("password", "private", "unrelated-secret", other))
            assert tool.session_snapshot(selected).pending_work is None
            rows = (await client.get("/api/browser/sessions")).json()["sessions"]
            assert next(row for row in rows if row["session_id"] == selected)["pending_work"] == 1
            assert next(row for row in rows if row["session_id"] == other)["pending_work"] == 0
            assert (await client.post(f"/api/browser/sessions/{selected}/end", json={"confirm": True})).status_code == 409
            assert (await client.post(f"/api/browser/sessions/{other}/handoff", json={"confirm": True})).status_code == 409
            llm.continue_to_tools.set()
            await asyncio.wait_for(llm.invoked.wait(), 2)
            assert len(drivers) == 2
            assert tool.get_session(selected).last_url == "https://selected.example/document"
            assert tool.get_session(other).last_url == "https://other.example/unrelated-secret"
            assert (await client.post(f"/api/browser/sessions/{selected}/end", json={"confirm": True})).status_code == 409
            if completion == "cancel":
                running.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await running
            else:
                llm.finish.set()
                if completion == "failure":
                    with pytest.raises(RuntimeError, match="trace persistence failed"):
                        await running
                else:
                    assert (await running).final_text == "done"
            ended = await client.post(f"/api/browser/sessions/{selected}/end", json={"confirm": True})
            assert ended.status_code == 200, ended.text
            assert tool.get_session(other) is not None
            assert tool.captain_session_id is None
            stale = await tool.invoke({"action": "goto", "url": "https://selected.example/"}, {
                "agent_id": "crew-one", "browser_session_id": selected,
            })
            assert stale.error == "session_not_active"
            next_llm = _ReservedRunLLM()
            next_llm.calls = 1
            next_llm.finish.set()
            next_result = await WorkItemAgenticExecutor(llm_client=next_llm).run(
                agent_id="crew-one", instructions="", task_text="Continue", runtime=runtime,
            )
            assert next_result.final_text == "done"
            assert len(drivers) == 2
            assert drivers[1].stop_count == 0
        finally:
            llm.continue_to_tools.set()
            llm.finish.set()
            if running is not None:
                if not running.done():
                    running.cancel()
                await asyncio.gather(running, return_exceptions=True)


@pytest.mark.asyncio
async def test_dispatch_reserves_own_created_and_explicit_sessions_until_run_finishes(
    wired_browser_runtime: Any,
) -> None:
    runtime, drivers, _ = wired_browser_runtime
    tool = runtime.browser_tool
    llm = _ReservedRunLLM(extra_session=True)
    running = asyncio.create_task(WorkItemAgenticExecutor(llm_client=llm).run(
        agent_id="crew-one", instructions="", task_text="Read pages", runtime=runtime,
    ))
    try:
        await asyncio.wait_for(llm.announced.wait(), 2)
        assert tool.session_count == 0
        assert not any("shared with the Captain" in item["function"]["description"] for item in llm.definitions)
        llm.continue_to_tools.set()
        await asyncio.wait_for(llm.invoked.wait(), 2)
        rows = await tool.list_session_metadata()
        assert len(rows) == len(drivers) == 2
        assert "explicit-run-session" in {row.session_id for row in rows}
        for row in rows:
            assert row.owner_id == "crew-one"
            assert row.pending_work == 1
            assert (await tool.end_session(row.session_id, actor=_ACTOR, confirm=True)).status_code == 409
        running.cancel()
        with pytest.raises(asyncio.CancelledError):
            await running
        for row in rows:
            assert (await tool.end_session(row.session_id, actor=_ACTOR, confirm=True)).status_code == 200
        assert all(driver.stop_count == 1 for driver in drivers)
    finally:
        llm.continue_to_tools.set()
        llm.finish.set()
        if not running.done():
            running.cancel()
        await asyncio.gather(running, return_exceptions=True)


@pytest.mark.asyncio
async def test_dispatch_handoff_does_not_grant_browser_permission(
    wired_browser_runtime: Any,
) -> None:
    runtime, drivers, _ = wired_browser_runtime
    selected = await _bridge(runtime.browser_tool)
    assert (await runtime.browser_tool.hand_to_crew(selected, actor=_ACTOR, confirm=True)).status_code == 200
    llm = _ReservedRunLLM()
    llm.continue_to_tools.set()
    llm.finish.set()
    await WorkItemAgenticExecutor(llm_client=llm).run(
        agent_id="probationary", instructions="", task_text="Read a page", runtime=runtime,
    )
    assert not any(item["function"]["name"] == "browser" for item in llm.definitions)
    assert not runtime.tool_registry.check_permission(
        "probationary", "browser", ToolPermission.READ, agent_department="medical", agent_rank="ensign",
    )
    assert runtime.browser_tool.get_session(selected).last_url == ""
    assert len(drivers) == 1
    assert (await runtime.browser_tool.end_session(selected, actor=_ACTOR, confirm=True)).status_code == 200


@pytest.mark.asyncio
async def test_dispatch_cleanup_failure_preserves_retry_and_allows_new_own_session(
    wired_browser_runtime: Any,
) -> None:
    runtime, drivers, _ = wired_browser_runtime
    tool = runtime.browser_tool
    first = await tool.invoke(
        {"action": "goto", "url": "https://selected.example/start"}, {"agent_id": "crew-one"},
    )
    assert first.error is None
    selected = first.metadata["session_id"]
    context = drivers[0].chromium.browser.contexts[0]
    try:
        context.fail_close = True
        failed = await tool.end_session(selected, actor=_ACTOR, confirm=True)
        assert failed.reason == "cleanup_failed"
        assert tool.session_snapshot(selected).state is BrowserLifecycleState.CLEANUP_FAILED
        assert tool.get_session(selected) is not None
        llm = _ReservedRunLLM()
        llm.continue_to_tools.set()
        llm.finish.set()
        result = await WorkItemAgenticExecutor(llm_client=llm).run(
            agent_id="crew-one", instructions="", task_text="Read another page", runtime=runtime,
        )
        assert result.final_text == "done"
        assert len(drivers) == 2
        rows = await tool.list_session_metadata()
        active = [row for row in rows if row.state is BrowserLifecycleState.ACTIVE]
        assert len(active) == 1
        assert active[0].session_id != selected
        assert active[0].owner_id == "crew-one"
        assert active[0].last_url == "https://selected.example/document"
        assert active[0].pending_work == 0
        assert (await tool.invoke(
            {"action": "state", "session_id": selected}, {"agent_id": "crew-one"},
        )).error == "session_not_active"
        context.fail_close = False
        assert (await tool.end_session(selected, actor=_ACTOR, confirm=True)).status_code == 200
        assert tool.get_session(active[0].session_id) is not None
        continued = await tool.invoke({"action": "state"}, {"agent_id": "crew-one"})
        assert continued.error is None
        assert continued.metadata["session_id"] == active[0].session_id
    finally:
        context.fail_close = False


@pytest.mark.asyncio
@pytest.mark.parametrize("expires_midrun", [False, True])
@pytest.mark.parametrize("ended_selection", [False, True])
async def test_dispatch_reserves_existing_own_session_before_first_call(
    wired_browser_runtime: Any, browser_clock: SimpleNamespace, expires_midrun: bool,
    browser_invocations: list[tuple[dict[str, Any], dict[str, Any], ToolResult]],
    ended_selection: bool,
) -> None:
    runtime, drivers, _ = wired_browser_runtime
    tool = runtime.browser_tool
    if ended_selection:
        previous = await _bridge(tool)
        assert (await tool.hand_to_crew(previous, actor=_ACTOR, confirm=True)).status_code == 200
        assert (await tool.end_session(previous, actor=_ACTOR, confirm=True)).status_code == 200
        assert tool.captain_session_id is None
        drivers.clear()
        browser_invocations.clear()
    first = await tool.invoke({"action": "goto", "url": "https://selected.example/start"}, {"agent_id": "crew-one"})
    assert first.error is None
    selected = first.metadata["session_id"]
    session = tool.get_session(selected)
    assert session is not None and not session.is_expired()
    assert session.expires_at > browser_clock.now
    assert len(browser_invocations) == 1
    browser_invocations.clear()
    llm = _ReservedRunLLM(follow_up=True)
    running = asyncio.create_task(WorkItemAgenticExecutor(llm_client=llm).run(
        agent_id="crew-one", instructions="", task_text="Continue reading", runtime=runtime,
    ))
    try:
        await asyncio.wait_for(llm.announced.wait(), 2)
        assert not any("shared with the Captain" in item["function"]["description"] for item in llm.definitions)
        assert (await tool.list_session_metadata())[0].pending_work == 1
        assert not session.is_expired()
        assert (await tool.end_session(selected, actor=_ACTOR, confirm=True)).status_code == 409
        if expires_midrun:
            browser_clock.now = session.expires_at + 1
            assert session.is_expired()
        llm.continue_to_tools.set()
        await asyncio.wait_for(llm.invoked.wait(), 2)
        assert len(browser_invocations) == 1
        params, context, invocation = browser_invocations[0]
        assert "browser_session_id" not in context
        assert "session_id" not in params
        assert invocation.error is None
        assert len(drivers) == (2 if expires_midrun else 1)
        rows = await tool.list_session_metadata()
        current = next(row for row in rows if row.last_url == "https://selected.example/document")
        assert (current.session_id != selected) is expires_midrun
        assert tool.get_session(selected) is session
        if expires_midrun:
            assert session.last_url == "https://selected.example/start"
        assert all(row.pending_work == 1 for row in rows)
        for row in rows:
            assert (await tool.end_session(row.session_id, actor=_ACTOR, confirm=True)).status_code == 409
        old_browser = drivers[0].chromium.browser
        old_context = old_browser.contexts[0]
        assert drivers[0].stop_count == old_browser.disconnect_count == 0
        assert old_context.close_count == old_context.pages[0].close_count == 0
        llm.finish.set()
        assert (await running).final_text == "done"
        assert len(browser_invocations) == 2
        assert browser_invocations[1][0] == {"action": "state"}
        assert browser_invocations[1][2].error is None
        assert browser_invocations[1][2].metadata["session_id"] == current.session_id
        assert all(row.pending_work == 0 for row in await tool.list_session_metadata())
        continued = await tool.invoke({"action": "state"}, {"agent_id": "crew-one"})
        assert continued.error is None
        assert continued.metadata["session_id"] == current.session_id
        assert len(drivers) == (2 if expires_midrun else 1)
        assert (await tool.end_session(selected, actor=_ACTOR, confirm=True)).status_code == 200
    finally:
        llm.continue_to_tools.set()
        llm.finish.set()
        if not running.done():
            running.cancel()
        await asyncio.gather(running, return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("explicit", [False, True])
async def test_dispatch_expired_intentional_target_reaches_llm_without_substitution(
    wired_browser_runtime: Any, browser_clock: SimpleNamespace, explicit: bool,
    browser_invocations: list[tuple[dict[str, Any], dict[str, Any], ToolResult]],
) -> None:
    runtime, drivers, _ = wired_browser_runtime
    tool = runtime.browser_tool
    runtime.config.agentic_loop.structured_tool_messages = False
    if explicit:
        opened = await tool.invoke(
            {"action": "goto", "url": "https://explicit.example/original"},
            {"agent_id": "crew-one"},
        )
        assert opened.error is None
        selected = opened.metadata["session_id"]
    else:
        selected = await _bridge(tool)
        opened = await tool.invoke(
            {"action": "goto", "session_id": selected,
             "url": "https://user:password@selected.example/original?token=private#secret"},
            {"agent_id": "captain"},
        )
        assert opened.error is None
    session = tool.get_session(selected)
    assert session is not None and not session.is_expired()
    original_url = session.last_url
    browser_clock.now += 10
    other = await _bridge(tool)
    other_session = tool.get_session(other)
    assert other_session is not None
    assert (await tool.invoke(
        {"action": "goto", "session_id": other, "url": "https://other.example/untouched"},
        {"agent_id": "captain"},
    )).error is None
    default = other if explicit else selected
    assert (await tool.hand_to_crew(default, actor=_ACTOR, confirm=True)).status_code == 200
    assert tool.captain_session_id == default
    browser_invocations.clear()
    answer = "The selected session is unavailable; select a session to continue."
    llm = _ReservedRunLLM(session_id=selected if explicit else None, final_text=answer)
    running = asyncio.create_task(WorkItemAgenticExecutor(llm_client=llm).run(
        agent_id="crew-one", instructions="", task_text="Read the selected document", runtime=runtime,
    ))
    try:
        await asyncio.wait_for(llm.announced.wait(), 2)
        description = next(item["function"]["description"] for item in llm.definitions
                           if item["function"]["name"] == "browser")
        assert "shared with the Captain" in description
        announced_url = "https://other.example/untouched" if explicit else "https://selected.example/original"
        assert f"shared with the Captain at {announced_url}. When the Captain" in description
        assert ("explicit.example/original" if explicit else "other.example/untouched") not in description
        assert all(secret not in description for secret in ("password", "private", "#secret"))
        assert not session.is_expired()
        metadata = {row.session_id: row for row in await tool.list_session_metadata()}
        assert metadata[default].pending_work == 1
        assert browser_invocations == []
        browser_clock.now = session.expires_at + 1
        assert session.is_expired() and not other_session.is_expired()
        llm.continue_to_tools.set()
        await asyncio.wait_for(llm.invoked.wait(), 2)
        assert len(browser_invocations) == 1
        params, context, result = browser_invocations[0]
        assert context["browser_session_id"] == default
        assert params["session_id"] == selected
        assert result.error == "session_expired"
        assert result.metadata["session_id"] == selected
        assert len(drivers) == 2
        assert session.last_url == original_url
        assert other_session.last_url == "https://other.example/untouched"
        assert "session_expired" in llm.feedback[0]
        assert "error=True" in llm.feedback[0]
        llm.finish.set()
        outcome = await asyncio.wait_for(running, 2)
        assert outcome.final_text == answer
        assert outcome.tool_failures
        assert outcome.tool_invocations is not None
        assert "browser" in outcome.tool_invocations.attempted
        assert "browser" not in outcome.tool_invocations.succeeded
        assert all(row.pending_work == 0 for row in await tool.list_session_metadata())
        assert drivers[1].stop_count == 0
    finally:
        llm.continue_to_tools.set()
        llm.finish.set()
        if not running.done():
            running.cancel()
        await asyncio.gather(running, return_exceptions=True)
