"""AD-745: action endpoint tests (``/api/browser/actions/...``)."""
from __future__ import annotations

import time
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from probos.cognitive.dm.action_dispatcher import (
    ActionDispatcher,
    ActionStatus,
    DispatchedAction,
    make_action_id,
)
from probos.routers.agent_actions import router
from probos.routers.auth import require_crew_scope
from probos.routers.deps import get_runtime


class _FakeSession:
    def __init__(self) -> None:
        self.aborted = False


class _FakeBrowserTool:
    def __init__(self) -> None:
        self._session = _FakeSession()
        self.invoked: list = []

    def get_session(self, agent_id: str):
        return self._session

    async def invoke(self, params, context=None):
        self.invoked.append(dict(params))

        class _R:
            output = {"clicked": True}
            error = None
        return _R()


def _make_app() -> tuple[FastAPI, Any]:
    class _RT:
        action_dispatcher = ActionDispatcher()
        browser_tool = _FakeBrowserTool()

    rt = _RT()
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_runtime] = lambda: rt
    app.dependency_overrides[require_crew_scope] = lambda: True
    return app, rt


def _seed_action(rt: Any, *, tier: int = 2, status: ActionStatus = ActionStatus.ACK_PENDING) -> str:
    aid = make_action_id("captain", "counselor", "turn-1", 0)
    action = DispatchedAction(
        action_id=aid, agent_id="counselor", captain_id="captain",
        thread_id="thread-1", verb="click",
        args={"selector": "#submit"}, raw_intent="submit form",
        tier=tier, status=status, proposed_at=time.time(),
        page_url="https://example.com/form",
    )
    rt.action_dispatcher.register(action)
    return aid


def test_ack_executes_pending_tier2_action() -> None:
    app, rt = _make_app()
    aid = _seed_action(rt)
    with TestClient(app) as client:
        r = client.post(f"/api/browser/actions/{aid}/ack")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["action"]["status"] == "executed"
    assert rt.browser_tool.invoked, "BrowserTool.invoke was never called"
    assert rt.browser_tool.invoked[0]["action"] == "click"


def test_abort_marks_aborted_and_sets_session_flag() -> None:
    app, rt = _make_app()
    aid = _seed_action(rt)
    with TestClient(app) as client:
        r = client.post(f"/api/browser/actions/{aid}/abort")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["action"]["status"] == "aborted"
    # BrowserSession.aborted set to True so any in-flight Playwright work cancels.
    assert rt.browser_tool._session.aborted is True
    # BrowserTool.invoke NOT called on abort.
    assert rt.browser_tool.invoked == []


def test_list_thread_actions_returns_per_thread_view() -> None:
    app, rt = _make_app()
    _seed_action(rt)
    # Add an action under a different thread to verify scoping.
    other = DispatchedAction(
        action_id="other", agent_id="counselor", captain_id="captain",
        thread_id="thread-OTHER", verb="state", args={}, raw_intent="",
        tier=1, status=ActionStatus.EXECUTED, proposed_at=time.time(),
    )
    rt.action_dispatcher.register(other)
    with TestClient(app) as client:
        r = client.get("/api/browser/actions/by-thread/thread-1")
    assert r.status_code == 200
    body = r.json()
    assert len(body["actions"]) == 1
    assert body["actions"][0]["verb"] == "click"


def test_ack_unknown_action_returns_404() -> None:
    app, rt = _make_app()
    with TestClient(app) as client:
        r = client.post("/api/browser/actions/nope/ack")
    assert r.status_code == 404


def test_ack_already_executed_returns_409() -> None:
    app, rt = _make_app()
    aid = _seed_action(rt, status=ActionStatus.EXECUTED)
    with TestClient(app) as client:
        r = client.post(f"/api/browser/actions/{aid}/ack")
    assert r.status_code == 409
    assert r.json()["error"] == "action_already_decided"
