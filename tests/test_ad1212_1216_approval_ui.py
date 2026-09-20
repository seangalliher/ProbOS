"""Backend crossing evidence for the ordinary AD-1212 / AD-1216 UI fixture."""

from __future__ import annotations

import json
import os
import signal
import socket
import sqlite3
import subprocess
import sys
import time
import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from probos.activation.dispatcher import Dispatcher
from probos.capability_request import can_fulfil_request, validate_action_payload
from probos.cognitive.capability_gap_driver import CapabilityGapDriver
from probos.cognitive.queue import AgentCognitiveQueue
from probos.cognitive.repair_issue import RepairIssueFulfiller
from probos.events import EventType
from probos.fault_report import FaultReportStore
from probos.mesh.work_item_router import WorkItemRouter
from probos.routers import capability_requests, threads
from probos.threads import ChatThreadStore
from tests.fixtures.approval_ui_bridge import (
    AGENT_ID, CANDIDATE, PARTIAL_TEXT, ApprovalUiBridge, MemoryDatabases, _IssueExecutionSink, create_app,
)


@pytest.fixture(autouse=True)
def no_external_network(monkeypatch: pytest.MonkeyPatch) -> None:
    original = socket.socket.connect

    def connect(connection: socket.socket, address: Any) -> Any:
        if isinstance(address, tuple) and address[0] not in ("127.0.0.1", "::1"):
            raise AssertionError(f"Approval fixture attempted non-loopback networking: {address[0]}")
        return original(connection, address)

    monkeypatch.setattr(socket.socket, "connect", connect)


@pytest.fixture
async def bridge_client() -> AsyncIterator[tuple[FastAPI, httpx.AsyncClient]]:
    app = create_app()
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1",
        ) as client:
            yield app, client


async def _scenario(client: httpx.AsyncClient, **options: Any) -> dict[str, Any]:
    response = await client.post("/__approval_ui__/scenario", json={"kind": "continue", **options})
    assert response.status_code == 200, response.text
    return response.json()


async def _state(client: httpx.AsyncClient) -> dict[str, Any]:
    response = await client.get("/__approval_ui__/state")
    assert response.status_code == 200, response.text
    return response.json()


async def _decide(client: httpx.AsyncClient, request_id: str, **changes: Any) -> httpx.Response:
    return await client.post(
        f"/api/capability-requests/{request_id}/decide",
        json={"approve": True, "reason": "", **changes},
    )


async def test_health_empty_bridge_reports_candidate_and_real_owners(bridge_client: Any) -> None:
    app, client = bridge_client
    response = await client.get("/__approval_ui__/health")
    assert response.status_code == 200
    health = response.json()
    assert health["ok"] and health["service"] == "approval-ui-test-bridge"
    assert Path(health["candidate"]).resolve() == Path(__file__).resolve().parents[1]
    assert Path(__file__).resolve().is_relative_to(CANDIDATE)
    assert len(health["module_origins"]) >= 15
    for module, origin in health["module_origins"].items():
        assert Path(origin).resolve().is_relative_to(CANDIDATE / "src"), (module, origin)
    runtime = app.state.runtime
    assert type(runtime.capability_gap_driver) is CapabilityGapDriver
    assert type(runtime.work_item_router) is WorkItemRouter
    assert type(runtime.dispatcher) is Dispatcher
    assert type(runtime.queue) is AgentCognitiveQueue
    assert isinstance(runtime.chat_thread_store, ChatThreadStore)
    assert type(runtime.chat_thread_store).append_message is ChatThreadStore.append_message
    assert type(runtime.chat_thread_store).list_messages is ChatThreadStore.list_messages
    endpoints = {(route.path, method): route.endpoint for route in app.routes for method in route.methods}
    assert endpoints[("/api/capability-requests/{request_id}/decide", "POST")] is capability_requests.decide_capability_request
    assert endpoints[("/api/threads/{thread_id}", "GET")] is threads.get_thread
    assert endpoints[("/api/threads/{thread_id}/messages", "GET")] is threads.list_messages
    state = await _state(client)
    assert state["request"] is state["work_item"] is state["message"] is None
    assert state["numeric_boundary"] is state["repair"] is None
    assert state["decision_post_count"] == 0
    assert state["execution_calls"] == state["tool_calls"] == []
    assert state["sqlite_files"] == {"requests": "", "actions": "", "work": "", "threads": ""}


@pytest.mark.parametrize("partial", [False, True])
async def test_scenario_continue_hydrates_real_notice_and_explicit_provenance(
    bridge_client: Any, partial: bool,
) -> None:
    _, client = bridge_client
    scenario = await _scenario(client, partial=partial)
    state = await _state(client)
    request_id = scenario["request_id"]
    assert str(uuid.UUID(request_id)) == request_id
    assert state["request"]["status"] == "pending"
    assert state["request"]["work_item_id"] == scenario["work_item_id"]
    assert state["work_item"]["status"] == "blocked"
    assert state["work_item"]["metadata"]["capability_request_id"] == request_id
    assert state["router_predispatchable"] is True
    assert state["execution_calls"] == state["tool_calls"] == []
    assert state["request"]["payload"] == {
        "tool_id": "dm_agentic", "action": "continue", "params": {},
        "scope_key": "", "session_id": None, "thread_id": scenario["thread_id"],
    }
    lead = (
        "I have stopped and need your approval to keep going — this turn reached its step limit "
        + ("with the task still open. Partial work is below." if partial else
           "before I had anything to report back. The task is still open.")
    )
    expected = (
        lead + " Approve the pending request in the Bridge and I will pick up from exactly where "
        f"this stopped. (Request {request_id}.)"
        + ("\n\n---\n" + PARTIAL_TEXT if partial else "")
    )
    assert scenario["notice"] == expected
    thread = await client.get(f"/api/threads/{scenario['thread_id']}")
    transcript = await client.get(f"/api/threads/{scenario['thread_id']}/messages")
    assert thread.status_code == transcript.status_code == 200
    assert thread.json()["participants"] == ["captain", AGENT_ID]
    assert transcript.json()["thread_id"] == scenario["thread_id"]
    assert transcript.json()["messages"] == [scenario["message"]]
    message = transcript.json()["messages"][0]
    assert message["body"] == expected
    assert message["author_id"] == scenario["agent_id"] == AGENT_ID
    assert message["thread_id"] == scenario["thread_id"]
    assert message["role"] == "agent"
    committed = [e["data"] for e in state["events"] if e["type"] == EventType.CHAT_THREAD_MESSAGE_APPENDED.value]
    assert committed == [{
        "thread_id": scenario["thread_id"], "message_id": message["id"], "author_id": AGENT_ID,
        "role": "agent", "created_at": message["created_at"],
    }]


async def test_decide_continue_crosses_real_event_driver_router_and_execution_queue(bridge_client: Any) -> None:
    _, client = bridge_client
    scenario = await _scenario(client)
    before = await _state(client)
    assert before["setup"]["request_status"] == "pending"
    assert before["setup"]["work_status"] == "blocked"
    assert before["setup"]["router_predispatchable"]
    assert before["setup"]["execution_count"] == 0
    response = await _decide(client, scenario["request_id"])
    assert response.status_code == 200, response.text
    assert response.json()["fulfilled"] is True
    assert response.json()["standing_rule"] is None
    state = await _state(client)
    assert state["request"]["status"] == "fulfilled"
    assert state["work_item"]["status"] == "in_progress"
    assert len(state["execution_calls"]) == 1
    delivered = state["execution_calls"][0]
    assert delivered["intent"] == "work_item_dispatched"
    assert delivered["params"]["work_item_id"] == scenario["work_item_id"]
    assert delivered["params"]["_source_type"] == "work_item_router"
    assert delivered["params"]["routing_reason"] == "direct_assigned_hint"
    assert delivered["work_status"] == "in_progress"
    assert delivered["agent_id"] == scenario["agent_id"]
    assert state["decision_posts"] == [{
        "path": f"/api/capability-requests/{scenario['request_id']}/decide",
        "body": {"approve": True, "reason": ""}, "status_code": 200,
    }]
    assert state["event_counts"][EventType.CAPABILITY_REQUEST_DECIDED.value] == 1
    assert state["event_counts"][EventType.CAPABILITY_REQUEST_FULFILLED.value] == 1
    assert state["event_counts"][EventType.HYBRID_DISPATCH_DIRECT.value] == 1
    assert state["event_counts"]["task_event_dispatched"] == 1
    assert len(state["trust_outcomes"]) == 1
    assert (await client.get("/api/capability-requests/actionable")).json()["requests"] == []
    assert state["action"]["approvals"] == []


async def test_decide_denial_cancels_linked_work_without_execution(bridge_client: Any) -> None:
    _, client = bridge_client
    scenario = await _scenario(client)
    response = await _decide(client, scenario["request_id"], approve=False, reason="Stop this fixture task")
    assert response.status_code == 200
    assert response.json()["fulfilled"] is False
    assert response.json()["standing_rule"] is None
    state = await _state(client)
    assert state["request"]["status"] == "denied"
    assert state["work_item"]["status"] == "cancelled"
    assert state["work_item"]["metadata"]["denial_reason"] == "Stop this fixture task"
    assert state["execution_calls"] == state["tool_calls"] == []
    assert state["decision_posts"][0]["body"] == {"approve": False, "reason": "Stop this fixture task"}
    assert state["action"]["approvals"] == []
    assert state["event_counts"].get(EventType.CAPABILITY_REQUEST_FULFILLED.value, 0) == 0
    assert (await client.get("/api/capability-requests/actionable")).json()["requests"] == []


async def test_decide_approved_retry_fulfils_without_duplicate_decision_or_standing(bridge_client: Any) -> None:
    _, client = bridge_client
    scenario = await _scenario(client, approved_retry=True)
    before = await _state(client)
    assert before["request"]["status"] == "approved"
    assert before["work_item"]["status"] == "blocked"
    assert before["execution_calls"] == []
    assert before["event_counts"][EventType.CAPABILITY_REQUEST_DECIDED.value] == 1
    assert before["decision_post_count"] == 0
    rows = (await client.get("/api/capability-requests/actionable")).json()["requests"]
    assert len(rows) == 1 and rows[0]["can_retry_fulfilment"] is True
    response = await _decide(client, scenario["request_id"])
    assert response.status_code == 200 and response.json()["fulfilled"]
    after = await _state(client)
    assert after["request"]["status"] == "fulfilled"
    assert after["request"]["decided_at"] == before["request"]["decided_at"]
    assert after["request"]["decision_reason"] == before["request"]["decision_reason"]
    assert len(after["execution_calls"]) == 1
    assert after["event_counts"][EventType.CAPABILITY_REQUEST_DECIDED.value] == 1
    assert after["trust_outcomes"] == before["trust_outcomes"]
    assert after["action"]["approvals"] == []
    assert after["decision_posts"][0]["body"] == {"approve": True, "reason": ""}


@pytest.mark.parametrize("approve", [False, True])
async def test_decide_settled_request_rejects_second_post_without_duplicate_effect(
    bridge_client: Any, approve: bool,
) -> None:
    _, client = bridge_client
    scenario = await _scenario(client)
    first = await _decide(client, scenario["request_id"], approve=approve, reason="Reviewed")
    assert first.status_code == 200
    before = await _state(client)
    second = await _decide(client, scenario["request_id"], approve=approve, reason="Reviewed")
    assert second.status_code == 400
    after = await _state(client)
    assert after["request"] == before["request"]
    assert after["execution_calls"] == before["execution_calls"]
    assert after["trust_outcomes"] == before["trust_outcomes"]
    assert after["decision_post_count"] == 2
    assert after["event_counts"][EventType.CAPABILITY_REQUEST_DECIDED.value] == 1


@pytest.mark.parametrize("grant_standing", [False, True])
async def test_decide_ordinary_action_never_replays_and_future_reads_real_standing_store(
    bridge_client: Any, grant_standing: bool,
) -> None:
    _, client = bridge_client
    scenario = await _scenario(client, kind="action")
    before = await _state(client)
    assert before["request"]["status"] == "pending"
    assert before["request"]["work_item_id"] == before["work_item"]["id"] == scenario["work_item_id"]
    assert before["work_item"]["status"] == "blocked" and before["router_predispatchable"]
    assert before["execution_calls"] == before["tool_calls"] == []
    body = {"grant_standing": True, "standing_ttl_hours": 1} if grant_standing else {}
    response = await _decide(client, scenario["request_id"], **body)
    assert response.status_code == 200
    assert response.json()["request"]["status"] == "approved"
    assert response.json()["request"]["can_retry_fulfilment"] is False
    assert response.json()["fulfilled"] is False
    state = await _state(client)
    assert state["work_item"]["status"] == "blocked"
    assert state["tool_calls"] == state["execution_calls"] == []
    assert state["event_counts"].get(EventType.HYBRID_DISPATCH_DIRECT.value, 0) == 0
    assert state["event_counts"].get(EventType.CAPABILITY_REQUEST_FULFILLED.value, 0) == 0
    assert state["decision_posts"][0]["body"] == {"approve": True, "reason": "", **body}
    assert (await client.get("/api/capability-requests/actionable")).json()["requests"] == []
    receipt = response.json()["standing_rule"]
    if grant_standing:
        assert receipt["agent_id"] == AGENT_ID
        assert receipt["tool_id"] == "browser" and receipt["action"] == "compute_use_click"
        assert receipt["scope_key"] == "approval.example"
        assert receipt["expires_at"] - receipt["issued_at"] == pytest.approx(3600)
        assert state["action"]["approvals"][0]["id"] == receipt["id"]
    else:
        assert receipt is None and state["action"]["approvals"] == []
    later = await client.post("/__approval_ui__/future", json={})
    assert later.status_code == 200, later.text
    assert later.json()["admitted"] is grant_standing
    state = await _state(client)
    assert len(state["tool_calls"]) == int(grant_standing)
    assert len(later.json()["requests"]) == int(not grant_standing)
    assert state["execution_calls"] == []
    assert state["work_item"]["status"] == "blocked"
    assert state["decision_post_count"] == 1


async def test_future_changed_params_session_and_thread_do_not_narrow_standing_scope(bridge_client: Any) -> None:
    _, client = bridge_client
    scenario = await _scenario(client, kind="action")
    response = await _decide(client, scenario["request_id"], grant_standing=True, standing_ttl_hours=1)
    assert response.status_code == 200
    changed = {"x": 91, "y": 37, "selector": "#different", "text": "<img src=x onerror=alert(1)>"}
    future = await client.post("/__approval_ui__/future", json={"params": changed})
    assert future.status_code == 200 and future.json()["admitted"]
    assert future.json()["requests"] == []
    assert future.json()["thread_id"] != scenario["thread_id"]
    state = await _state(client)
    assert len(state["tool_calls"]) == 1
    params = state["tool_calls"][0]["params"]
    for key, value in changed.items():
        assert params[key] == value
    assert params["session_id"] != state["request"]["payload"]["session_id"]
    assert params["thread_id"] != state["request"]["payload"]["thread_id"]
    assert params["action"] == state["action"]["approvals"][0]["action"]
    assert state["decision_post_count"] == 1


@pytest.mark.parametrize("change", [
    {"scope_key": "other.example"}, {"scope_key": ""},
    {"agent_id": "another-agent"}, {"action": "upload_file"}, {"expired": True},
])
async def test_future_mismatch_or_expiry_reasks_without_reaching_execution(
    bridge_client: Any, change: dict[str, Any],
) -> None:
    _, client = bridge_client
    scenario = await _scenario(client, kind="action")
    response = await _decide(client, scenario["request_id"], grant_standing=True, standing_ttl_hours=1)
    assert response.status_code == 200
    original_receipt = response.json()["standing_rule"]
    future = await client.post("/__approval_ui__/future", json=change)
    assert future.status_code == 200, future.text
    assert future.json()["admitted"] is False
    assert future.json()["result"]["error"]
    assert len(future.json()["requests"]) == 1
    new_request = future.json()["requests"][0]
    assert new_request["status"] == "pending"
    assert new_request["id"] != scenario["request_id"]
    assert new_request["agent_id"] == change.get("agent_id", AGENT_ID)
    assert new_request["payload"]["scope_key"] == change.get("scope_key", "approval.example")
    assert new_request["payload"]["action"] == change.get("action", "compute_use_click")
    state = await _state(client)
    assert state["tool_calls"] == state["execution_calls"] == []
    assert state["request"]["status"] == "approved" and state["work_item"]["status"] == "blocked"
    assert state["decision_post_count"] == 1
    if change.get("expired"):
        expired = state["action"]["approvals"][0]
        assert expired["id"] == original_receipt["id"]
        assert expired["expires_at"] < time.time()
        assert expired["expires_at"] - expired["issued_at"] == pytest.approx(3600)
        assert state["action"]["active_approvals"] == []


@pytest.mark.parametrize("grant_standing, change, admitted", [
    (False, {}, False), (True, {}, True), (True, {"expired": True}, False),
    (True, {"agent_id": "another-agent"}, False),
])
async def test_future_continue_uses_real_resolver_on_new_thread(
    bridge_client: Any, grant_standing: bool, change: dict[str, Any], admitted: bool,
) -> None:
    app, client = bridge_client
    scenario = await _scenario(client)
    extras = {"grant_standing": True, "standing_ttl_hours": 1} if grant_standing else {}
    response = await _decide(client, scenario["request_id"], **extras)
    assert response.status_code == 200 and response.json()["fulfilled"]
    if grant_standing:
        assert response.json()["standing_rule"]["scope_key"] == ""
        assert response.json()["standing_rule"]["tool_id"] == "dm_agentic"
    future = await client.post("/__approval_ui__/future", json=change)
    assert future.status_code == 200
    assert future.json()["admitted"] is admitted
    assert future.json()["thread_id"] != scenario["thread_id"]
    state = await _state(client)
    assert len(state["execution_calls"]) == 1
    assert len(state["continuation_calls"]) == int(admitted)
    assert len(future.json()["requests"]) == int(not admitted)
    if not admitted:
        request = future.json()["requests"][0]
        assert request["kind"] == "continue" and request["status"] == "pending"
        assert request["payload"]["thread_id"] == future.json()["thread_id"]
        assert f"(Request {request['id']}.)" in future.json()["result"]
        item = await app.state.runtime.work_item_store.get_work_item(request["work_item_id"])
        assert item is not None and item.status == "blocked"


async def test_decide_standing_ttl_is_clamped_by_real_settings_route(bridge_client: Any) -> None:
    _, client = bridge_client
    scenario = await _scenario(client, kind="action")
    settings = await client.get("/api/config")
    assert settings.status_code == 200
    policy = settings.json()["config"]["approval_inbox"]
    assert policy["enabled"] and policy["standing_rules_enabled"]
    maximum = policy["standing_rule_max_ttl_hours"]
    response = await _decide(
        client, scenario["request_id"], grant_standing=True, standing_ttl_hours=maximum + 1,
    )
    assert response.status_code == 200, response.text
    receipt = response.json()["standing_rule"]
    assert receipt["expires_at"] - receipt["issued_at"] == pytest.approx(maximum * 3600)


@pytest.mark.parametrize("options", [
    {}, {"kind": "unknown"}, {"kind": "action", "approved_retry": True},
    {"kind": "action", "partial": True}, {"kind": "continue", "extra": True},
    {"kind": "continue", "partial": "yes"},
    {"kind": "continue", "numeric_boundary": True}, {"kind": "action", "numeric_boundary": "yes"},
    {"kind": "action", "numeric_overflow": "positive"},
    {"kind": "action", "numeric_boundary": True, "numeric_overflow": "invalid"},
    {"kind": "action", "numeric_boundary": True, "numeric_overflow": 1},
])
async def test_scenario_invalid_input_never_creates_authority(
    bridge_client: Any, options: dict[str, Any],
) -> None:
    _, client = bridge_client
    response = await client.post("/__approval_ui__/scenario", json=options)
    assert response.status_code == 422
    state = await _state(client)
    assert state["request"] is None
    assert state["decision_post_count"] == 0
    assert state["events"] == state["tool_calls"] == state["execution_calls"] == []


@pytest.mark.parametrize("body, status", [
    ({}, 409), ({"expired": "yes"}, 422), ({"params": []}, 422),
    ({"scope_key": "https://outside.example"}, 422), ({"extra": True}, 422),
])
async def test_future_empty_or_invalid_setup_is_not_admission(
    bridge_client: Any, body: dict[str, Any], status: int,
) -> None:
    _, client = bridge_client
    response = await client.post("/__approval_ui__/future", json=body)
    assert response.status_code == status
    assert (await _state(client))["tool_calls"] == []


async def test_future_continue_refuses_fictitious_nonempty_scope(bridge_client: Any) -> None:
    _, client = bridge_client
    await _scenario(client)
    response = await client.post("/__approval_ui__/future", json={"scope_key": "other.example"})
    assert response.status_code == 422
    assert (await _state(client))["continuation_calls"] == []


async def test_routes_missing_rows_return_errors_without_fabricated_provenance(bridge_client: Any) -> None:
    _, client = bridge_client
    missing = uuid.uuid4().hex
    assert (await client.get(f"/api/threads/{missing}")).status_code == 404
    assert (await client.get(f"/api/threads/{missing}/messages")).status_code == 404
    assert (await _decide(client, str(uuid.uuid4()))).status_code == 404
    state = await _state(client)
    assert state["message"] is None and state["request"] is None
    assert state["trust_outcomes"] == state["execution_calls"] == []


async def test_decide_invalid_json_is_recorded_but_never_decided(bridge_client: Any) -> None:
    _, client = bridge_client
    scenario = await _scenario(client)
    response = await client.post(
        f"/api/capability-requests/{scenario['request_id']}/decide",
        content="{", headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 422
    state = await _state(client)
    assert state["request"]["status"] == "pending" and state["work_item"]["status"] == "blocked"
    assert state["execution_calls"] == state["trust_outcomes"] == []
    assert state["decision_posts"][0]["body"] is None
    assert state["decision_posts"][0]["status_code"] == 422


async def test_real_router_nondispatchable_item_cannot_fake_execution_from_status_change(bridge_client: Any) -> None:
    app, client = bridge_client
    scenario = await _scenario(client)
    runtime = app.state.runtime
    item = await runtime.work_item_store.get_work_item(scenario["work_item_id"])
    assert item is not None and runtime.work_item_router.is_dispatchable(item.to_dict())
    await runtime.work_item_store.update_work_item(
        item.id, metadata={**item.metadata, "dispatchable": False},
    )
    assert (await _state(client))["router_predispatchable"] is False
    response = await _decide(client, scenario["request_id"])
    assert response.status_code == 200 and response.json()["fulfilled"]
    state = await _state(client)
    assert state["work_item"]["status"] == "in_progress"
    assert state["execution_calls"] == []
    assert state["event_counts"].get("task_event_dispatched", 0) == 0


@pytest.mark.parametrize("origin, expected", [
    ("http://127.0.0.1:43127", 200), ("http://localhost:43127", 200),
    ("https://external.example", 400),
])
async def test_browser_cors_allows_only_loopback_origins(
    bridge_client: Any, origin: str, expected: int,
) -> None:
    _, client = bridge_client
    response = await client.options("/__approval_ui__/scenario", headers={
        "Origin": origin, "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "Content-Type",
    })
    assert response.status_code == expected
    if expected == 200:
        assert response.headers["access-control-allow-origin"] == origin
    else:
        assert "access-control-allow-origin" not in response.headers


async def test_scenario_reset_closes_owned_resources_and_clears_previous_authority(bridge_client: Any) -> None:
    app, client = bridge_client
    first = await _scenario(client)
    previous = app.state.runtime
    connections = tuple(previous.databases.connections.values()) + tuple(previous.databases.readers)
    response = await _decide(client, first["request_id"], grant_standing=True)
    assert response.status_code == 200
    second = await _scenario(client, kind="action")
    assert first["thread_id"] != second["thread_id"]
    assert previous.closed and previous.databases.connections == {}
    assert previous.queue.pending_count() == 0
    for connection in connections:
        with pytest.raises(sqlite3.ProgrammingError):
            connection.execute("SELECT 1")
    assert (await client.get(f"/api/threads/{first['thread_id']}")).status_code == 404
    state = await _state(client)
    assert state["decision_post_count"] == 0 and state["action"]["approvals"] == []
    assert state["trust_outcomes"] == state["execution_calls"] == []


async def test_start_failure_closes_already_opened_fixture_databases(monkeypatch: pytest.MonkeyPatch) -> None:
    original = MemoryDatabases.open

    def fail_actions(databases: MemoryDatabases, name: str) -> str:
        if name == "actions":
            raise RuntimeError("test-owned connection setup failed")
        return original(databases, name)

    monkeypatch.setattr(MemoryDatabases, "open", fail_actions)
    runtime = ApprovalUiBridge()
    with pytest.raises(RuntimeError, match="test-owned connection setup failed"):
        await runtime.start()
    assert runtime.closed
    assert runtime.databases.connections == {}
    await runtime.stop()


@pytest.mark.parametrize("standing_fields", [False, True])
async def test_repair_real_consumer_retries_without_standing_or_duplicate_decision(
    bridge_client: Any, standing_fields: bool,
) -> None:
    app, client = bridge_client
    runtime = app.state.runtime
    faults = FaultReportStore(
        runtime.databases.open("faults"), connection_factory=runtime.connection_factory,
        emit_event=runtime.emit_event,
    )
    runtime.resources.push_async_callback(faults.stop)
    await faults.start()
    for _ in range(2):
        fault = await faults.file_fault(
            tool_id="browser", error_text="unknown action: fixture_action",
            attempted="Perform an isolated fixture action", agent_id=AGENT_ID,
        )
    request = await runtime.capability_request_store.file_action_request(AGENT_ID, {
        "tool_id": "repair", "action": "dispatch", "scope_key": "browser",
        "params": {"fault_id": fault.id, "signature": fault.signature},
        "session_id": None, "thread_id": "",
    })
    assert request is not None
    sink = _IssueExecutionSink()
    runtime.repair_issue_fulfiller = RepairIssueFulfiller(
        requests=runtime.capability_request_store, filings=faults.issue_filings, client=sink,
        repository="fixture/fixture", enabled=True, notify=lambda *args, **kwargs: None,
    )
    extras = {"grant_standing": True, "standing_ttl_hours": 1} if standing_fields else {}
    first = await _decide(client, request.id, **extras)
    assert first.status_code == 200, first.text
    assert first.json()["request"]["status"] == "approved"
    assert first.json()["fulfilled"] is False and first.json()["standing_rule"] is None
    first_filing = await faults.issue_filings.get(fault.signature)
    assert first_filing.disposition == "retryable_failure"
    assert first_filing.failure_code == "pre_send_failure"
    rows = (await client.get("/api/capability-requests/actionable")).json()["requests"]
    assert len(rows) == 1 and rows[0]["can_retry_fulfilment"]
    before = await _state(client)
    second = await _decide(client, request.id)
    assert second.status_code == 200, second.text
    assert second.json()["fulfilled"] is True and second.json()["standing_rule"] is None
    assert second.json()["request"]["decided_at"] == first.json()["request"]["decided_at"]
    after = await _state(client)
    assert len(sink.calls) == 2
    assert len(after["trust_outcomes"]) == 1
    assert after["trust_outcomes"] == before["trust_outcomes"]
    assert after["event_counts"][EventType.CAPABILITY_REQUEST_DECIDED.value] == 1
    assert after["event_counts"][EventType.CAPABILITY_REQUEST_FULFILLED.value] == 1
    assert after["action"]["approvals"] == []
    assert after["execution_calls"] == after["tool_calls"] == []
    assert after["decision_posts"][1]["body"] == {"approve": True, "reason": ""}
    receipt = await faults.issue_filings.get(fault.signature)
    assert receipt.disposition == "filed" and receipt.issue_number == 17
    assert (await _decide(client, request.id)).status_code == 400
    assert len(sink.calls) == 2
    assert (await client.get("/api/capability-requests/actionable")).json()["requests"] == []


async def test_numeric_boundary_http_rows_preserve_real_ordinary_approval_and_repair_retry(
    bridge_client: Any,
) -> None:
    app, client = bridge_client
    scenario = await _scenario(client, kind="action", numeric_boundary=True)
    boundary = scenario["numeric_boundary"]
    ordinary_id, repair_id = scenario["request_id"], boundary["repair"]["request_id"]
    runtime = app.state.runtime
    ordinary = await runtime.capability_request_store.get(ordinary_id, durable=True)
    repair = await runtime.capability_request_store.get(repair_id, durable=True)
    assert ordinary is not None and repair is not None
    assert validate_action_payload(ordinary.payload) is not None
    assert validate_action_payload(repair.payload) is not None
    assert not can_fulfil_request(ordinary) and can_fulfil_request(repair)
    assert boundary["ordinary"]["python_characters"] == 3998
    assert boundary["repair"]["python_characters"] == 4000
    assert boundary["repair"]["can_fulfil"] is True
    response = await client.get("/api/capability-requests/actionable")
    assert response.status_code == 200
    rows = response.json()["requests"]
    assert len(rows) == 4
    unrelated = [row for row in rows if row["id"] in boundary["unrelated_request_ids"]]
    assert len(unrelated) == 2 and all(row["status"] == "pending" for row in unrelated)
    # Raw-wire TS assertions moved to ApprovalWave.test.tsx, whose job owns both toolchains.

    before = await _state(client)
    assert before["repair"]["request"]["status"] == "approved"
    assert before["repair"]["filing"]["disposition"] == "retryable_failure"
    assert len(before["repair"]["issue_calls"]) == 1
    assert before["event_counts"][EventType.CAPABILITY_REQUEST_DECIDED.value] == 1
    approval = await _decide(client, ordinary_id)
    assert approval.status_code == 200
    assert approval.json()["request"]["status"] == "approved"
    assert approval.json()["fulfilled"] is False and approval.json()["standing_rule"] is None
    middle = await _state(client)
    assert middle["execution_calls"] == middle["tool_calls"] == []
    assert middle["work_item"]["status"] == "blocked"
    middle_rows = (await client.get("/api/capability-requests/actionable")).json()["requests"]
    assert {row["id"] for row in middle_rows} == {repair_id, *boundary["unrelated_request_ids"]}
    retried = await _decide(client, repair_id)
    assert retried.status_code == 200
    assert retried.json()["fulfilled"] is True and retried.json()["standing_rule"] is None
    after = await _state(client)
    assert after["repair"]["request"]["decided_at"] == before["repair"]["request"]["decided_at"]
    assert after["repair"]["filing"]["disposition"] == "filed"
    assert after["repair"]["filing"]["issue_number"] == 17
    assert len(after["repair"]["issue_calls"]) == 2
    assert after["event_counts"][EventType.CAPABILITY_REQUEST_DECIDED.value] == 2
    assert after["event_counts"][EventType.CAPABILITY_REQUEST_FULFILLED.value] == 1
    assert after["trust_outcomes"] == middle["trust_outcomes"]
    assert len(after["trust_outcomes"]) == 2
    assert after["action"]["approvals"] == []
    assert after["execution_calls"] == after["tool_calls"] == []
    assert after["decision_post_count"] == 2
    assert all(post["body"] == {"approve": True, "reason": ""} for post in after["decision_posts"])
    assert (await client.get("/api/capability-requests/actionable")).json()["requests"] == unrelated


@pytest.mark.parametrize("overflow_sign,value", [
    ("positive", 10**309), ("negative", -(10**309)),
], ids=["positive", "negative"])
async def test_numeric_overflow_http_rows_preserve_real_queue_and_repair_retry(
    bridge_client: Any, overflow_sign: str, value: int,
) -> None:
    app, client = bridge_client
    scenario = await _scenario(
        client, kind="action", numeric_boundary=True, numeric_overflow=overflow_sign,
    )
    boundary = scenario["numeric_boundary"]
    ordinary_id, repair_id = scenario["request_id"], boundary["repair"]["request_id"]
    runtime = app.state.runtime
    ordinary = await runtime.capability_request_store.get(ordinary_id, durable=True)
    repair = await runtime.capability_request_store.get(repair_id, durable=True)
    assert ordinary is not None and repair is not None
    for row in (ordinary, repair):
        assert validate_action_payload(row.payload) is row.payload
        assert type(row.payload["params"]["value"]) is int
        assert row.payload["params"]["value"] == value
    assert ordinary.status == "pending" and not can_fulfil_request(ordinary)
    assert repair.status == "approved" and can_fulfil_request(repair)
    assert boundary["ordinary"]["python_characters"] == 3998
    assert boundary["repair"]["python_characters"] == 4000
    assert boundary["repair"]["can_fulfil"] is True
    response = await client.get("/api/capability-requests/actionable")
    assert response.status_code == 200
    assert response.text.count(f'"value":{value}') == 2
    assert "Infinity" not in response.text and '"value":null' not in response.text
    rows = response.json()["requests"]
    assert len(rows) == 4
    remaining = [row for row in rows if row["id"] != repair_id]
    assert {row["id"] for row in remaining} == {ordinary_id, *boundary["unrelated_request_ids"]}
    # Keep real effects here; ApprovalWave.test.tsx checks these raw HTTP rows in TS.
    before = await _state(client)
    assert before["repair"]["filing"]["disposition"] == "retryable_failure"
    assert before["repair"]["filing"]["failure_code"] == "pre_send_failure"
    assert len(before["repair"]["issue_calls"]) == 1
    assert before["event_counts"][EventType.CAPABILITY_REQUEST_DECIDED.value] == 1
    retried = await _decide(client, repair_id)
    assert retried.status_code == 200, retried.text
    assert retried.json()["fulfilled"] is True and retried.json()["standing_rule"] is None
    assert retried.json()["request"]["payload"] == repair.payload
    after = await _state(client)
    assert after["repair"]["request"]["status"] == "fulfilled"
    for field in ("decided_at", "decided_by", "decision_reason", "payload"):
        assert after["repair"]["request"][field] == before["repair"]["request"][field]
    assert after["repair"]["filing"]["disposition"] == "filed"
    assert after["repair"]["filing"]["issue_number"] == 17
    assert len(after["repair"]["issue_calls"]) == 2
    assert after["event_counts"][EventType.CAPABILITY_REQUEST_DECIDED.value] == 1
    assert after["event_counts"][EventType.CAPABILITY_REQUEST_FULFILLED.value] == 1
    assert after["trust_outcomes"] == before["trust_outcomes"]
    assert len(after["trust_outcomes"]) == 1
    assert after["action"]["approvals"] == []
    assert after["execution_calls"] == after["tool_calls"] == []
    assert after["request"]["status"] == "pending" and after["work_item"]["status"] == "blocked"
    assert after["decision_post_count"] == 1
    assert after["decision_posts"][0]["body"] == {"approve": True, "reason": ""}
    assert (await client.get("/api/capability-requests/actionable")).json()["requests"] == remaining


def _server_command(port: int) -> list[str]:
    return [
        sys.executable, str(CANDIDATE / "tests/fixtures/approval_ui_bridge.py"), "--port", str(port),
    ]


def _server_environment() -> dict[str, str]:
    return {
        **os.environ, "PYTHONPATH": os.pathsep.join((str(CANDIDATE / "src"), str(CANDIDATE))),
        "PYTHONDONTWRITEBYTECODE": "1", "PROBOS_NATS_ENABLED": "false", "HF_HUB_OFFLINE": "1",
    }


def test_loopback_server_cli_runs_real_routes_with_owned_readiness_and_cleanup() -> None:
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]
    process = subprocess.Popen(
        _server_command(port), cwd=CANDIDATE, env=_server_environment(),
        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    server_pid: int | None = None
    try:
        deadline = time.monotonic() + 20
        with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=1, trust_env=False) as client:
            while True:
                if process.poll() is not None:
                    pytest.fail(f"Owned bridge exited before readiness: {process.communicate()}")
                try:
                    ready = client.get("/__approval_ui__/health")
                    if ready.status_code == 200:
                        break
                except httpx.TransportError:
                    pass
                if time.monotonic() >= deadline:
                    pytest.fail("Owned loopback approval bridge missed its bounded readiness deadline")
                time.sleep(0.025)
            health = ready.json()
            assert health["service"] == "approval-ui-test-bridge" and health["ok"]
            # Windows' approved venv executable is a launcher. Bind readiness
            # to that exact process or its direct child, never a reused server.
            assert health["pid"] == process.pid or health["parent_pid"] == process.pid
            server_pid = health["pid"]
            assert Path(health["candidate"]).resolve() == CANDIDATE
            assert all(Path(origin).is_relative_to(CANDIDATE / "src") for origin in health["module_origins"].values())
            setup = client.post("/__approval_ui__/scenario", json={"kind": "continue", "partial": True})
            assert setup.status_code == 200, setup.text
            scenario = setup.json()
            assert client.get(f"/api/threads/{scenario['thread_id']}/messages").json()["messages"] == [scenario["message"]]
            decision = client.post(
                f"/api/capability-requests/{scenario['request_id']}/decide",
                json={"approve": True, "reason": ""},
            )
            assert decision.status_code == 200 and decision.json()["fulfilled"]
            state = client.get("/__approval_ui__/state").json()
            assert len(state["execution_calls"]) == 1
            assert state["execution_calls"][0]["params"]["work_item_id"] == scenario["work_item_id"]
    finally:
        if server_pid is not None and server_pid != process.pid:
            try:
                os.kill(server_pid, signal.SIGTERM)
            except ProcessLookupError:
                pass  # The verified owned child already exited.
        if process.poll() is None:
            process.terminate()
        try:
            process.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.communicate(timeout=5)
    assert process.poll() is not None


def test_loopback_server_cli_refuses_occupied_port_instead_of_reusing_server() -> None:
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        reservation.listen(1)
        port = reservation.getsockname()[1]
        result = subprocess.run(
            _server_command(port), cwd=CANDIDATE, env=_server_environment(),
            capture_output=True, text=True, timeout=20,
        )
    assert result.returncode != 0
    assert "error while attempting to bind" in result.stderr.lower()


@pytest.mark.parametrize("port", [0, 65536])
def test_loopback_server_cli_rejects_invalid_port(port: int) -> None:
    result = subprocess.run(
        _server_command(port), cwd=CANDIDATE, env=_server_environment(),
        capture_output=True, text=True, timeout=20,
    )
    assert result.returncode == 2
    assert "--port must be between 1 and 65535" in result.stderr
