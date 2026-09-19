"""AD-1206: Captain approval authorizes one durable, fault-backed issue filing."""

from __future__ import annotations

import asyncio
import itertools
import json
import logging
import sqlite3
import uuid
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from fastapi import HTTPException
from pydantic import ValidationError

import probos.capability_request as request_module
import probos.fault_report as fault_module
from probos.api_models import CapabilityRequestDecideRequest
from probos.capability_request import (
    CapabilityRequest, CapabilityRequestStore, can_fulfil_request, repair_action,
)
from probos.routers.capability_requests import (
    _STANDING_RULE_KINDS, _serialize, decide_capability_request,
    list_actionable_capability_requests,
)
from probos.cognitive.repair_dispatch import RepairDispatcher
from probos.cognitive.repair_issue import (
    GitHubIssueClient, RepairIssueFulfiller, build_issue_report, issue_marker,
)
from probos.config import RepairConfig, SystemConfig, load_config
from probos.fault_report import FaultReportStore
from probos.notifications import NotificationQueue
from probos.runtime import ProbOSRuntime
from tests.test_ad1206_issue_filing_store import (
    INVALID_ISSUE_URLS, INVALID_REPOSITORY_URLS, _Factory,
)


class _Bus:
    def __init__(self):
        self.listeners = []
        self.tasks = set()
        self.events = []

    def emit(self, kind, data):
        kind = str(getattr(kind, "value", kind))
        self.events.append((kind, data))
        for listener in self.listeners:
            task = asyncio.create_task(listener({"type": kind, "data": data}))
            self.tasks.add(task)
            task.add_done_callback(self.tasks.discard)

    async def drain(self):
        while self.tasks:
            await asyncio.gather(*tuple(self.tasks))


class _Credentials:
    def __init__(self):
        self.value = "FAKE_GITHUB_TEST_CREDENTIAL"
        self.calls = []

    def get(self, name, *, requester="unknown"):
        self.calls.append((name, requester))
        return self.value


class _Trace:
    def __init__(self):
        self.entries = [{
            "name": "browser", "arguments": {"action": "key_type", "text": "safe-value"},
            "is_error": True, "output": "unknown action: key_type",
        }]
        self.error = False
        self.pause = False
        self.entered = asyncio.Event()

    async def read(self, _ref):
        if self.pause:
            self.entered.set()
            await asyncio.Event().wait()
        if self.error:
            raise RuntimeError("TRACE_EXCEPTION_SECRET")
        return json.dumps(self.entries).encode()


class _HTTP:
    def __init__(self):
        self.mode = "success"
        self.reconciliation = "unique"
        self.requests = []
        self.remote = []
        self.clients = []
        self.canonical_repository = "owner/repo"
        self.receipt_override = {}
        self.connection_failures = 0
        self.after_post = None
        self.entered = asyncio.Event()
        self.release = asyncio.Event()

    async def handle(self, request):
        if request.method == "POST" and self.mode in {"connect_timeout", "pool_timeout"}:
            self.connection_failures += 1
            error = httpx.ConnectTimeout if self.mode == "connect_timeout" else httpx.PoolTimeout
            raise error("FAKE_PRESEND_EXCEPTION_MARKER", request=request)
        self.requests.append(request)
        if request.method == "POST":
            if self.mode == "connect_failure":
                raise httpx.ConnectError("RAW_TRANSPORT_SECRET", request=request)
            if self.mode == "rejected":
                return httpx.Response(422, json={"error": "RESPONSE_SECRET"})
            body = json.loads(request.content)["body"]
            item = {
                "number": 37,
                "html_url": f"https://github.com/{self.canonical_repository}/issues/37",
                "repository_url": f"https://api.github.com/repos/{self.canonical_repository}",
                "state": "open", "body": body, **self.receipt_override,
            }
            self.remote.append(item)
            if self.after_post:
                await self.after_post()
            self.entered.set()
            if self.mode == "waiting":
                await self.release.wait()
            if self.mode == "timeout":
                raise httpx.ReadTimeout("RAW_TRANSPORT_SECRET", request=request)
            if self.mode == "write_timeout":
                raise httpx.WriteTimeout("RAW_TRANSPORT_SECRET", request=request)
            if self.mode == "server_failure":
                return httpx.Response(503, json={"error": "RESPONSE_SECRET"})
            if self.mode == "malformed":
                return httpx.Response(201, json={"html_url": "https://evil.invalid/RESPONSE_SECRET"})
            return httpx.Response(201, json=item)
        assert request.method == "GET"
        assert request.url.path == "/search/issues"
        assert "is:open" not in request.url.params["q"] and "is:closed" not in request.url.params["q"]
        items = [dict(item) for item in self.remote]
        complete = True
        headers = {}
        mode = self.reconciliation
        if mode == "empty":
            items = []
        elif mode == "multiple":
            items += [{**items[0], "number": 38, "html_url": "https://github.com/owner/repo/issues/38"}]
        elif mode == "closed":
            items[0]["state"] = "closed"
        elif mode == "wrong_marker":
            items[0]["body"] = issue_marker("b" * 64)
        elif mode == "wrong_repository":
            items[0]["repository_url"] = "https://api.github.com/repos/other/repo"
        elif mode == "invalid_receipt":
            items[0]["html_url"] += "?unexpected=true"
        elif mode == "incomplete":
            complete = False
        elif mode == "next_page":
            headers["Link"] = '<https://api.github.com/search/issues?page=2>; rel="next"'
        count = 101 if mode == "over_bound" else len(items)
        return httpx.Response(200, headers=headers, json={
            "items": items, "total_count": count, "incomplete_results": not complete,
        })

    def factory(self):
        client = httpx.AsyncClient(transport=httpx.MockTransport(self.handle), trust_env=False)
        self.clients.append(client)
        return client


def _consumer(rig, *, repository="owner/repo", enabled=True, minimum_occurrences=2):
    return RepairIssueFulfiller(
        requests=rig.requests, filings=rig.faults.issue_filings,
        client=GitHubIssueClient(
            credential_store=rig.credentials, http_client_factory=rig.http.factory,
            attachment_store=rig.trace,
        ),
        repository=repository, enabled=enabled, notify=rig.runtime.notify,
        minimum_occurrences=minimum_occurrences,
    )


@pytest.fixture
async def rig(tmp_path, monkeypatch, request):
    setup = getattr(request, "param", {})
    clock = SimpleNamespace(value=1000.0)
    fault_ids, request_ids = itertools.count(1), itertools.count(1)
    monkeypatch.setattr(fault_module, "uuid", SimpleNamespace(
        uuid4=lambda: uuid.UUID(hex=f"{next(fault_ids):012x}" + "0" * 20),
    ))
    monkeypatch.setattr(request_module, "uuid", SimpleNamespace(uuid4=lambda: uuid.UUID(int=next(request_ids))))
    monkeypatch.setattr(fault_module, "time", SimpleNamespace(time=lambda: clock.value))
    monkeypatch.setattr(request_module, "time", SimpleNamespace(time=lambda: clock.value))
    bus, credentials, http, trace = _Bus(), _Credentials(), _HTTP(), _Trace()
    fault_factory, request_factory = _Factory(), _Factory()
    trust = []
    faults = FaultReportStore(
        str(tmp_path / "faults.db"), connection_factory=fault_factory, emit_event=bus.emit,
    )
    requests = CapabilityRequestStore(
        str(tmp_path / "requests.db"), connection_factory=request_factory, emit_event=bus.emit,
        trust_network=SimpleNamespace(record_outcome=lambda *args, **kwargs: trust.append((args, kwargs))),
    )
    assert Path(faults.db_path).resolve().parent == tmp_path.resolve()
    assert Path(requests.db_path).resolve().parent == tmp_path.resolve()
    await faults.start()
    await requests.start()
    runtime = object.__new__(ProbOSRuntime)
    runtime.registry = SimpleNamespace(get=lambda _id: None)
    runtime.notification_queue = NotificationQueue(on_event=bus.emit)
    runtime.capability_request_store = requests
    runtime.fault_report_store = faults
    runtime.config = SimpleNamespace(repair=RepairConfig(
        enabled=True, github_repository="owner/repo",
        propose_after_occurrences=setup.get("minimum_occurrences", 2),
    ))
    result = SimpleNamespace(
        faults=faults, requests=requests, runtime=runtime, bus=bus, trust=trust,
        credentials=credentials, http=http, trace=trace, clock=clock,
        fault_connection=fault_factory.connection, request_connection=request_factory.connection,
    )
    runtime.repair_issue_fulfiller = _consumer(
        result, minimum_occurrences=runtime.config.repair.propose_after_occurrences,
    )
    dispatcher = RepairDispatcher(
        runtime=SimpleNamespace(attachment_store=trace), fault_report_store=faults,
        capability_request_store=requests, config=runtime.config.repair,
    )
    bus.listeners.append(dispatcher.on_fault_event)
    try:
        for occurrence in range(setup.get("occurrences", 2)):
            if occurrence == 1 and setup.get("fail_second_commit"):
                fault_factory.connection.fail_commit = True
            result.fault = await faults.file_fault(
                tool_id="browser", error_text=setup.get("error_text", "unknown action: key_type"),
                attempted=setup.get("attempted", "Enter a value"), agent_id="agent", thread_id="thread",
                tool_trace_ref="trace-ref",
            )
            await bus.drain()
        pending = await requests.list_pending()
        assert len(pending) == 1 and pending[0].kind == "action"
        result.request = pending[0]
        result.clock.value = 2000.0
        yield result
    finally:
        http.release.set()
        await bus.drain()
        await requests.stop()
        await faults.stop()


async def _decide(rig, *, approve=True, request=None):
    return await decide_capability_request(
        (request or rig.request).id,
        CapabilityRequestDecideRequest(approve=approve, reason="" if approve else "Not approved"),
        rig.runtime,
    )


@pytest.mark.parametrize("rig", [{"fail_second_commit": True}], indirect=True)
async def test_failed_second_commit_approval_waits_for_durable_qualification_then_retries_once(rig):
    assert rig.fault.occurrences == 2 and "2 times" in rig.request.rationale
    with sqlite3.connect(rig.faults.db_path) as db:
        assert db.execute(
            "SELECT occurrences FROM fault_reports WHERE id = ?", (rig.fault.id,),
        ).fetchone() == (1,)
    payload = json.dumps(rig.request.payload, sort_keys=True)
    first = await _decide(rig)
    assert first["request"]["status"] == "approved" and not first["fulfilled"]
    assert first["request"]["can_retry_fulfilment"]
    assert rig.credentials.calls == rig.http.requests == rig.http.clients == []
    assert await rig.faults.issue_filings.get(rig.fault.signature) is None
    notice = rig.runtime.notification_queue.snapshot()[0]
    assert "durable_qualification_unavailable" in notice["detail"]
    assert "durable" in notice["detail"] and "evidence" in notice["detail"]
    assert "configuration" in notice["detail"]

    await rig.faults.file_fault(
        tool_id=rig.fault.tool_id, error_text=rig.fault.error_text,
        agent_id="agent", thread_id="thread",
    )
    await rig.bus.drain()
    with sqlite3.connect(rig.faults.db_path) as db:
        assert db.execute(
            "SELECT occurrences FROM fault_reports WHERE id = ?", (rig.fault.id,),
        ).fetchone() == (3,)
    assert rig.http.requests == []
    assert await rig.requests.list_pending() == []
    assert json.dumps((await rig.requests.get(rig.request.id, durable=True)).payload, sort_keys=True) == payload
    assert (await _decide(rig))["fulfilled"]
    assert len(rig.http.remote) == len(rig.http.requests) == len(rig.credentials.calls) == len(rig.trust) == 1
    assert "Occurrences: 3" in json.loads(rig.http.requests[0].content)["body"]
    with pytest.raises(HTTPException):
        await _decide(rig)
    assert len(rig.http.remote) == 1


@pytest.mark.parametrize("minimum", [None, True, False, 0, -1, 1.0, "2", 2**63])
async def test_consumer_invalid_minimum_is_refused_before_credentials_or_http(rig, minimum):
    with pytest.raises(ValueError, match="invalid_minimum_occurrences"):
        _consumer(rig, minimum_occurrences=minimum)
    assert rig.credentials.calls == rig.http.requests == []


@pytest.mark.parametrize("legacy", [False, True])
async def test_approved_payload_uses_current_consumer_threshold_not_historical_rationale(rig, legacy):
    req = rig.request
    if legacy:
        payload = {
            **req.payload,
            "params": {key: req.payload["params"][key] for key in ("fault_id", "signature")},
        }
        req = await rig.requests.file_action_request("agent", payload, rationale="Legacy approved repair")
        assert req.id != rig.request.id
    before = json.dumps(req.payload, sort_keys=True)
    rig.runtime.repair_issue_fulfiller = _consumer(rig, minimum_occurrences=3)
    first = await _decide(rig, request=req)
    assert not first["fulfilled"] and first["request"]["can_retry_fulfilment"]
    assert rig.credentials.calls == rig.http.requests == []
    assert await rig.faults.issue_filings.get(rig.fault.signature) is None
    rig.runtime.repair_issue_fulfiller = _consumer(rig, minimum_occurrences=1)
    assert (await _decide(rig, request=req))["fulfilled"]
    assert len(rig.http.remote) == len(rig.trust) == 1
    assert json.dumps((await rig.requests.get(req.id, durable=True)).payload, sort_keys=True) == before


async def test_retryable_reacquisition_requires_current_durable_threshold(rig):
    rig.credentials.value = None
    assert not (await _decide(rig))["fulfilled"]
    before = await rig.faults.issue_filings.get(rig.fault.signature)
    assert before.disposition == "retryable_failure"
    rig.credentials.value = "FAKE_GITHUB_TEST_CREDENTIAL"
    rig.runtime.repair_issue_fulfiller = _consumer(rig, minimum_occurrences=3)
    assert not (await _decide(rig))["fulfilled"]
    assert await rig.faults.issue_filings.get(rig.fault.signature) == before
    assert len(rig.credentials.calls) == 1 and rig.http.requests == []
    rig.runtime.repair_issue_fulfiller = _consumer(rig, minimum_occurrences=2)
    assert (await _decide(rig))["fulfilled"]
    assert len(rig.http.remote) == len(rig.trust) == 1


@pytest.mark.parametrize("rig", [{"occurrences": 1, "minimum_occurrences": 1}], indirect=True)
async def test_minimum_one_keeps_disabled_gate_and_allows_explicit_retry(rig):
    assert rig.fault.occurrences == 1
    rig.runtime.repair_issue_fulfiller = _consumer(rig, enabled=False, minimum_occurrences=1)
    assert not (await _decide(rig))["fulfilled"]
    assert rig.credentials.calls == rig.http.requests == []
    assert await rig.faults.issue_filings.get(rig.fault.signature) is None
    rig.runtime.repair_issue_fulfiller = _consumer(rig, minimum_occurrences=1)
    assert (await _decide(rig))["fulfilled"]
    assert "Occurrences: 1" in json.loads(rig.http.requests[0].content)["body"]
    assert len(rig.http.remote) == len(rig.trust) == 1


@pytest.mark.parametrize("disposition", ["attempting", "outcome_unknown", "filed"])
async def test_raised_threshold_reuses_receipt_or_only_reconciles_existing_attempt(rig, disposition):
    if disposition == "outcome_unknown":
        rig.http.mode = "timeout"
    else:
        async def fail_commit():
            connection = rig.fault_connection if disposition == "attempting" else rig.request_connection
            connection.fail_commit = True
        rig.http.after_post = fail_commit
    assert not (await _decide(rig))["fulfilled"]
    before = await rig.faults.issue_filings.get(rig.fault.signature)
    assert before.disposition == disposition
    rig.http.after_post = None
    rig.runtime.repair_issue_fulfiller = _consumer(rig, minimum_occurrences=3, repository="other/repo")
    assert (await _decide(rig))["fulfilled"]
    assert [req.method for req in rig.http.requests] == (
        ["POST"] if disposition == "filed" else ["POST", "GET"]
    )
    assert len(rig.http.remote) == len(rig.trust) == 1
    assert (await rig.faults.issue_filings.get(rig.fault.signature)).repository == "owner/repo"


def _payload(**changes):
    return {
        "tool_id": "repair", "action": "dispatch",
        "params": {"fault_id": "a123456789ab", "signature": "a" * 64},
        "scope_key": "browser", "session_id": None, "thread_id": "thread",
        **changes,
    }


@pytest.mark.parametrize("payload", [
    None, {}, _payload(tool_id="browser"), _payload(action="click"),
    _payload(params={}), _payload(params={"fault_id": "f", "signature": "short"}),
    _payload(scope_key=""), _payload(session_id="old-browser"),
    {**_payload(), "extra": "not a six-key action"},
])
def test_repair_action_invalid_identity_is_not_fulfillable(payload):
    req = CapabilityRequest(kind="action", payload=payload)
    assert repair_action(req) is None
    assert not can_fulfil_request(req)


def test_repair_action_legacy_payload_retains_exact_identity():
    req = CapabilityRequest(kind="action", payload=_payload())
    identity = repair_action(req)
    assert identity is not None
    assert (identity.fault_id, identity.signature, identity.tool_id, identity.thread_id) == (
        "a123456789ab", "a" * 64, "browser", "thread",
    )
    assert can_fulfil_request(req)
    assert not repair_action(replace(req, kind="grant"))


async def test_actionable_only_reserved_repair_projects_retry():
    store = CapabilityRequestStore()
    repair = await store.file_action_request("agent", _payload())
    ordinary = await store.file_action_request("agent", _payload(tool_id="browser"))
    await store.decide(repair.id, True)
    await store.decide(ordinary.id, True)
    actionable = await store.list_actionable()
    assert [r.id for r in actionable] == [repair.id]
    assert _serialize(actionable[0], include_retry=True)["can_retry_fulfilment"]
    assert not _serialize(await store.get(ordinary.id), include_retry=True)["can_retry_fulfilment"]
    assert await store.get(repair.id, durable=True) is None


async def test_get_durable_does_not_trust_mutated_cache(tmp_path):
    store = CapabilityRequestStore(str(tmp_path / "requests.db"))
    await store.start()
    try:
        req = await store.file_action_request("agent", _payload())
        req.status, req.decided_by = "approved", "captain"
        committed = await store.get(req.id, durable=True)
        assert committed.status == "pending"
        assert committed.decided_by == ""
        assert await store.get("missing", durable=True) is None
    finally:
        await store.stop()
    assert await store.get(req.id, durable=True) is None


async def test_approve_repair_never_issues_a_standing_rule():
    class _Standing:
        async def issue_approval(self, *args, **kwargs):
            pytest.fail("repair must never grant standing authority")

    store = CapabilityRequestStore()
    req = await store.file_action_request("agent", _payload())
    runtime = SimpleNamespace(
        capability_request_store=store, action_approval_store=_Standing(),
        config=SimpleNamespace(approval_inbox=SimpleNamespace(standing_rules_enabled=True)),
    )
    result = await decide_capability_request(
        req.id, CapabilityRequestDecideRequest(approve=True, grant_standing=True), runtime,
    )
    assert result["standing_rule"] is None
    assert result["fulfilled"] is False
    assert _STANDING_RULE_KINDS == {"action", "continue"}


async def test_file_event_approve_http_receipt_fulfil_reopen_crosses_whole_chain(rig):
    response = await _decide(rig)
    await rig.bus.drain()
    assert response["fulfilled"] and response["request"]["status"] == "fulfilled"
    assert len(rig.http.requests) == len(rig.http.remote) == 1
    assert rig.credentials.calls == [("github", "repair_issue")]
    report = json.loads(rig.http.requests[0].content)
    assert len(report["title"]) <= 120 and len(report["body"]) <= 12000
    # "fault remains open" used to pin a false lifecycle claim: an approval may
    # outlive dismissal or repair, and filing must leave that status unchanged.
    for evidence in (
        rig.fault.id, rig.fault.signature, "browser", "Occurrences: 2",
        "unknown action: key_type", "Enter a value", "key_type", "safe-value",
        "trace-ref", "does not alter the fault's lifecycle status",
    ):
        assert evidence in report["body"]
    assert rig.http.requests[0].url == "https://api.github.com/repos/owner/repo/issues"
    assert all(client.is_closed for client in rig.http.clients)
    notifications = rig.runtime.notification_queue.snapshot()
    assert notifications[0]["action_url"] == "https://github.com/owner/repo/issues/37"
    assert any(kind == "notification" for kind, _ in rig.bus.events)
    assert sum(kind == "capability_request_fulfilled" for kind, _ in rig.bus.events) == 1
    await rig.requests.stop()
    await rig.faults.stop()
    await rig.requests.start()
    await rig.faults.start()
    assert (await rig.requests.get(rig.request.id, durable=True)).status == "fulfilled"
    receipt = await rig.faults.issue_filings.get(rig.fault.signature)
    assert receipt.disposition == "filed" and receipt.issue_number == 37
    assert rig.faults.get(rig.fault.id).status == "open"
    assert await rig.requests.list_actionable() == []
    with pytest.raises(HTTPException) as error:
        await _decide(rig)
    assert error.value.status_code == 400
    assert len(rig.http.requests) == 1


async def test_deny_records_decline_without_http_or_credentials(rig):
    result = await _decide(rig, approve=False)
    assert result["request"]["status"] == "denied" and not result["fulfilled"]
    assert (await rig.faults.issue_filings.get(rig.fault.signature)).disposition == "declined"
    assert rig.credentials.calls == rig.http.requests == []
    await rig.faults.file_fault(tool_id="browser", error_text=rig.fault.error_text)
    await rig.bus.drain()
    assert await rig.requests.list_pending() == []


@pytest.mark.parametrize("status", ["dismissed", "repaired"])
async def test_approval_after_resolution_reports_unchanged_lifecycle_truthfully(rig, status):
    resolved = await rig.faults.resolve(rig.fault.id, status=status, resolution="Captain disposition")
    await rig.bus.drain()
    before = resolved.to_dict()
    resolved_events = sum(kind == "fault_resolved" for kind, _ in rig.bus.events)
    assert (await rig.requests.get(rig.request.id, durable=True)).status == "pending"
    assert (await _decide(rig))["fulfilled"]
    await rig.bus.drain()
    body = json.loads(rig.http.requests[0].content)["body"]
    notice = rig.runtime.notification_queue.snapshot()[0]
    for message in (body, notice["detail"]):
        assert "remains open" not in message
        assert "does not alter the fault's lifecycle status" in message
        assert "not a fix" in message
    assert rig.faults.get(rig.fault.id).to_dict() == before
    assert rig.faults.list_open() == []
    assert sum(kind == "fault_resolved" for kind, _ in rig.bus.events) == resolved_events
    await rig.faults.stop()
    await rig.faults.start()
    assert rig.faults.get(rig.fault.id).to_dict() == before
    assert (await rig.faults.issue_filings.get(rig.fault.signature)).disposition == "filed"


async def test_failed_decline_metadata_keeps_denial_effective_without_impossible_retry(rig, caplog):
    caplog.set_level(logging.DEBUG, logger="probos")
    rig.fault_connection.fail_commit = True
    result = await _decide(rig, approve=False)
    assert result["request"]["status"] == "denied" and not result["fulfilled"]
    assert result["request"]["can_retry_fulfilment"] is False
    assert rig.credentials.calls == rig.http.requests == []
    assert await rig.faults.issue_filings.get(rig.fault.signature) is None
    notice = rig.runtime.notification_queue.snapshot()[0]
    assert notice["notification_type"] == "action_required" and notice["action_url"] == ""
    assert "Denial remains effective" in notice["detail"]
    assert "This denial filed no issue" in notice["detail"]
    assert "decline audit metadata failed" in notice["detail"]
    assert "retry" not in notice["detail"].lower()
    assert await rig.requests.list_actionable() == []
    await rig.requests.stop()
    await rig.requests.start()
    assert (await rig.requests.get(rig.request.id, durable=True)).status == "denied"
    with pytest.raises(HTTPException) as error:
        await _decide(rig)
    assert error.value.status_code == 400
    assert len(rig.trust) == 1 and rig.credentials.calls == rig.http.requests == []


async def test_ordinary_action_with_fault_params_never_uses_repair_consumer(rig):
    ordinary = await rig.requests.file_action_request(
        "agent", {**rig.request.payload, "tool_id": "browser", "action": "click"},
        rationale="File a GitHub issue", work_item_id=None,
    )
    result = await _decide(rig, request=ordinary)
    assert not result["fulfilled"] and not result["request"]["can_retry_fulfilment"]
    assert rig.credentials.calls == rig.http.requests == []
    assert await rig.faults.issue_filings.get(rig.fault.signature) is None


@pytest.mark.parametrize("change", ["fault_id", "signature", "scope_key", "agent_id", "thread_id"])
async def test_approved_wrong_fault_identity_cannot_authorize_remote_write(rig, change):
    payload = {**rig.request.payload, "params": dict(rig.request.payload["params"])}
    # Thread is deliberately absent from the existing dedup key. This must be
    # a distinct persisted legacy ask, not a lookup returning the valid original.
    payload["params"]["targets"] = "legacy-target"
    agent = "agent"
    if change in {"fault_id", "signature"}:
        payload["params"][change] = "f" * (64 if change == "signature" else 12)
    elif change == "agent_id":
        agent = "unrelated"
    else:
        payload[change] = "unrelated"
    request = await rig.requests.file_action_request(agent, payload)
    assert request.id != rig.request.id and request.payload == payload
    result = await _decide(rig, request=request)
    assert not result["fulfilled"]
    assert rig.credentials.calls == rig.http.requests == []
    assert await rig.faults.issue_filings.get(rig.fault.signature) is None


async def test_consumer_requires_committed_captain_decision_not_cache(rig):
    rig.request.status, rig.request.decided_by, rig.request.decided_at = "approved", "captain", 1.0
    assert await rig.runtime.repair_issue_fulfiller.fulfil(rig.request.id) is None
    assert (await rig.requests.get(rig.request.id, durable=True)).status == "pending"
    assert rig.http.requests == rig.credentials.calls == []
    assert await rig.runtime.repair_issue_fulfiller.fulfil("missing") is None
    rig.request.status = "pending"
    await rig.requests.decide(rig.request.id, True, decided_by="agent")
    assert await rig.runtime.repair_issue_fulfiller.fulfil(rig.request.id) is None
    assert rig.http.requests == []


@pytest.mark.parametrize("prerequisite", ["repository", "credential", "enabled"])
async def test_missing_prerequisite_notifies_real_captain_queue_without_http(rig, prerequisite):
    if prerequisite == "repository":
        rig.runtime.repair_issue_fulfiller = _consumer(rig, repository="")
    elif prerequisite == "credential":
        rig.credentials.value = None
    else:
        rig.runtime.repair_issue_fulfiller = _consumer(rig, enabled=False)
    result = await _decide(rig)
    assert not result["fulfilled"] and result["request"]["can_retry_fulfilment"]
    assert rig.http.requests == []
    notices = rig.runtime.notification_queue.snapshot()
    assert notices[0]["notification_type"] == "action_required"
    assert rig.request.id in notices[0]["detail"] and "Retry" in notices[0]["detail"]
    if prerequisite != "credential":
        assert rig.credentials.calls == []
    rig.credentials.value = "FAKE_GITHUB_TEST_CREDENTIAL"
    rig.runtime.repair_issue_fulfiller = _consumer(rig)
    assert (await _decide(rig))["fulfilled"]
    assert len(rig.trust) == 1


@pytest.mark.parametrize("mode", ["connect_failure", "rejected"])
async def test_proven_no_creation_failure_requires_explicit_retry(rig, mode):
    rig.http.mode = mode
    first = await _decide(rig)
    assert not first["fulfilled"] and not rig.http.remote
    assert (await rig.faults.issue_filings.get(rig.fault.signature)).disposition == "retryable_failure"
    assert len(rig.http.requests) == 1
    rig.http.mode = "success"
    assert (await _decide(rig))["fulfilled"]
    assert [request.method for request in rig.http.requests] == ["POST", "POST"]
    assert len(rig.http.remote) == len(rig.trust) == 1


@pytest.mark.parametrize("mode", ["connect_timeout", "pool_timeout"])
async def test_connection_timeout_recovery_explicit_retry_posts_once_and_reuses_receipt(rig, caplog, mode):
    caplog.set_level(logging.DEBUG, logger="probos")
    rig.http.mode = mode
    first = await _decide(rig)
    assert not first["fulfilled"] and first["request"]["can_retry_fulfilment"]
    filing = await rig.faults.issue_filings.get(rig.fault.signature)
    assert filing.disposition == "retryable_failure" and filing.failure_code == "pre_send_failure"
    assert rig.http.connection_failures == 1 and rig.http.requests == rig.http.remote == []
    assert "FAKE_PRESEND_EXCEPTION_MARKER" not in caplog.text
    assert "FAKE_PRESEND_EXCEPTION_MARKER" not in json.dumps(rig.runtime.notification_queue.snapshot())
    await rig.bus.drain()
    assert rig.http.connection_failures == 1
    rig.http.mode = "success"
    assert (await _decide(rig))["fulfilled"]
    assert [req.method for req in rig.http.requests] == ["POST"]
    assert len(rig.http.remote) == len(rig.trust) == 1
    assert all(client.is_closed for client in rig.http.clients)
    receipt = await rig.faults.issue_filings.get(rig.fault.signature)
    assert receipt.disposition == "filed" and receipt.attempt_id != filing.attempt_id
    second = await rig.requests.file_action_request("agent", {
        **rig.request.payload, "params": {**rig.request.payload["params"], "targets": "legacy"},
    })
    assert (await _decide(rig, request=second))["fulfilled"]
    assert [req.method for req in rig.http.requests] == ["POST"]
    assert await rig.faults.issue_filings.get(rig.fault.signature) == receipt


@pytest.mark.parametrize("mode", ["timeout", "write_timeout", "server_failure", "malformed"])
async def test_uncertain_remote_outcome_only_reconciles_on_explicit_retry(rig, mode, caplog):
    caplog.set_level(logging.DEBUG, logger="probos")
    rig.http.mode = mode
    assert not (await _decide(rig))["fulfilled"]
    assert (await rig.faults.issue_filings.get(rig.fault.signature)).disposition == "outcome_unknown"
    assert [request.method for request in rig.http.requests] == ["POST"]
    await rig.faults.stop()
    await rig.faults.start()
    assert (await _decide(rig))["fulfilled"]
    assert [request.method for request in rig.http.requests] == ["POST", "GET"]
    assert len(rig.trust) == 1
    assert "RAW_TRANSPORT_SECRET" not in caplog.text and "RESPONSE_SECRET" not in caplog.text
    assert any("only reconciles" in item["detail"] for item in rig.runtime.notification_queue.snapshot())


@pytest.mark.parametrize("mode", [
    "empty", "incomplete", "multiple", "wrong_marker", "wrong_repository",
    "invalid_receipt", "next_page", "over_bound",
])
async def test_unconfirmed_reconciliation_never_grants_resend_permission(rig, mode):
    rig.http.mode = "timeout"
    await _decide(rig)
    rig.http.reconciliation = mode
    for _ in range(2):
        result = await _decide(rig)
        assert not result["fulfilled"] and result["request"]["can_retry_fulfilment"]
    assert [request.method for request in rig.http.requests] == ["POST", "GET", "GET"]
    assert (await rig.faults.issue_filings.get(rig.fault.signature)).disposition == "outcome_unknown"
    assert len(rig.trust) == 1


async def test_closed_exact_marker_is_a_receipt_not_a_request_to_reopen(rig):
    rig.http.mode = "timeout"
    await _decide(rig)
    rig.http.reconciliation = "closed"
    assert (await _decide(rig))["fulfilled"]
    assert [request.method for request in rig.http.requests] == ["POST", "GET"]


@pytest.mark.parametrize("mode", ["success", "timeout"])
async def test_canonical_case_create_reconcile_complete_fulfil_and_reopen(rig, mode):
    rig.http.canonical_repository = "Owner/RePo"
    rig.http.mode = mode
    first = await _decide(rig)
    if mode == "timeout":
        assert not first["fulfilled"]
        assert (await _decide(rig))["fulfilled"]
    else:
        assert first["fulfilled"]
    expected_methods = ["POST"] if mode == "success" else ["POST", "GET"]
    assert [req.method for req in rig.http.requests] == expected_methods
    before = await rig.faults.issue_filings.get(rig.fault.signature)
    assert before.repository == "owner/repo"
    assert before.issue_url == "https://github.com/Owner/RePo/issues/37"
    await rig.faults.stop()
    await rig.requests.stop()
    await rig.faults.start()
    await rig.requests.start()
    assert await rig.faults.issue_filings.get(rig.fault.signature) == before
    assert (await rig.requests.get(rig.request.id, durable=True)).status == "fulfilled"
    second = await rig.requests.file_action_request("agent", {
        **rig.request.payload, "params": {**rig.request.payload["params"], "targets": "legacy"},
    })
    rig.runtime.repair_issue_fulfiller = _consumer(rig, repository="other/repo", minimum_occurrences=3)
    assert (await _decide(rig, request=second))["fulfilled"]
    assert [req.method for req in rig.http.requests] == expected_methods
    assert len(rig.http.remote) == 1 and len(rig.trust) == 2
    assert await rig.faults.issue_filings.get(rig.fault.signature) == before
    assert all(
        notice["action_url"] == before.issue_url
        for notice in rig.runtime.notification_queue.snapshot()
        if notice["title"] == "Fault issue filed"
    )


@pytest.mark.parametrize("url", INVALID_ISSUE_URLS)
async def test_create_rejects_decorated_or_wrong_issue_url_and_never_reposts(rig, url):
    rig.http.receipt_override = {"html_url": url}
    assert not (await _decide(rig))["fulfilled"]
    filing = await rig.faults.issue_filings.get(rig.fault.signature)
    assert filing.disposition == "outcome_unknown" and filing.failure_code == "malformed_receipt"
    assert not (await _decide(rig))["fulfilled"]
    assert [req.method for req in rig.http.requests] == ["POST", "GET"]
    assert len(rig.http.remote) == 1


@pytest.mark.parametrize("url", INVALID_REPOSITORY_URLS)
async def test_reconcile_rejects_decorated_or_wrong_repository_url_without_reposting(rig, url):
    rig.http.mode = "timeout"
    rig.http.receipt_override = {"repository_url": url}
    assert not (await _decide(rig))["fulfilled"]
    assert not (await _decide(rig))["fulfilled"]
    assert (await rig.faults.issue_filings.get(rig.fault.signature)).disposition == "outcome_unknown"
    assert [req.method for req in rig.http.requests] == ["POST", "GET"]
    assert len(rig.http.remote) == 1


@pytest.mark.parametrize("second_approve", [True, False])
async def test_concurrent_repair_decisions_have_one_decision_effect(rig, second_approve):
    rig.http.mode = "waiting"
    first = asyncio.create_task(_decide(rig))
    second = None
    try:
        await asyncio.wait_for(rig.http.entered.wait(), 3)
        second = asyncio.create_task(_decide(rig, approve=second_approve))
        await asyncio.sleep(0)
        assert not second.done()
        rig.http.release.set()
        assert (await first)["fulfilled"]
        with pytest.raises(HTTPException) as error:
            await second
        assert error.value.status_code == 400
        assert len(rig.http.remote) == len(rig.trust) == 1
        assert sum(kind == "capability_request_decided" for kind, _ in rig.bus.events) == 1
    finally:
        rig.http.release.set()
        await asyncio.gather(*(task for task in (first, second) if task is not None), return_exceptions=True)


async def test_two_approved_requests_share_one_signature_receipt(rig):
    payload = {**rig.request.payload, "params": {**rig.request.payload["params"], "targets": "copilot"}}
    second = await rig.requests.file_action_request("agent", payload)
    outcomes = await asyncio.gather(_decide(rig), _decide(rig, request=second))
    assert all(outcome["fulfilled"] for outcome in outcomes)
    assert len(rig.http.requests) == 1 and len(rig.trust) == 2
    assert rig.faults.get(rig.fault.id).status == "open"


@pytest.mark.parametrize("failure", ["claim", "receipt", "fulfilment"])
async def test_persistence_failure_cannot_publish_false_success_or_duplicate(rig, failure):
    if failure == "claim":
        rig.fault_connection.fail_commit = True
    else:
        async def fail_next_commit():
            connection = rig.fault_connection if failure == "receipt" else rig.request_connection
            connection.fail_commit = True
        rig.http.after_post = fail_next_commit
    result = await _decide(rig)
    assert not result["fulfilled"] and result["request"]["status"] == "approved"
    filing = await rig.faults.issue_filings.get(rig.fault.signature)
    assert (filing.disposition if filing else None) == {
        "claim": None, "receipt": "attempting", "fulfilment": "filed",
    }[failure]
    assert len(rig.http.requests) == (0 if failure == "claim" else 1)
    rig.http.after_post = None
    await rig.requests.stop()
    await rig.requests.start()
    assert (await _decide(rig))["fulfilled"]
    assert sum(request.method == "POST" for request in rig.http.requests) == 1
    assert len(rig.trust) == 1


async def test_http_runs_outside_shared_fault_database_lock(rig):
    async def persist_while_remote_request_is_inflight():
        await rig.faults.file_fault(tool_id="shell", error_text="independent fault")
    rig.http.after_post = persist_while_remote_request_is_inflight
    assert (await asyncio.wait_for(_decide(rig), 3))["fulfilled"]
    assert len(rig.faults.list_open()) == 2


@pytest.mark.parametrize("after_dispatch", [False, True])
async def test_cancellation_releases_transport_and_preserves_correct_retry_boundary(rig, after_dispatch):
    if after_dispatch:
        rig.http.mode = "waiting"
        entered = rig.http.entered
    else:
        rig.trace.pause = True
        entered = rig.trace.entered
    task = asyncio.create_task(_decide(rig))
    try:
        await asyncio.wait_for(entered.wait(), 3)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        filing = await rig.faults.issue_filings.get(rig.fault.signature)
        assert filing.disposition == ("outcome_unknown" if after_dispatch else "retryable_failure")
        assert all(client.is_closed for client in rig.http.clients)
        rig.trace.pause = False
        rig.http.release.set()
        await rig.faults.stop()
        await rig.faults.start()
        assert (await _decide(rig))["fulfilled"]
        assert [request.method for request in rig.http.requests] == (
            ["POST", "GET"] if after_dispatch else ["POST"]
        )
    finally:
        rig.http.release.set()
        await asyncio.gather(task, return_exceptions=True)


async def test_same_signature_future_fault_reuses_closed_issue_receipt(rig):
    await _decide(rig)
    rig.http.remote[0]["state"] = "closed"
    old = rig.fault
    await rig.faults.resolve(old.id, status="dismissed", resolution="Captain disposition")
    for _ in range(2):
        newer = await rig.faults.file_fault(
            tool_id=old.tool_id, error_text=old.error_text, agent_id="agent", thread_id="thread",
        )
        await rig.bus.drain()
    pending = await rig.requests.list_pending()
    assert len(pending) == 1 and newer.id != old.id and newer.signature == old.signature
    assert (await _decide(rig, request=pending[0]))["fulfilled"]
    assert len(rig.http.requests) == len(rig.credentials.calls) == 1
    assert rig.http.remote[0]["state"] == "closed" and newer.status == "open"
    assert (await rig.faults.issue_filings.get(newer.signature)).fault_id == old.id


async def test_report_sanitizes_before_clipping_and_never_logs_raw_fault(rig, caplog):
    # Capture application diagnostics, not the SQLite driver's opt-in SQL/row dump.
    caplog.set_level(logging.DEBUG, logger="probos")
    secret = rig.credentials.value
    raw = "x" * 1960 + f" password={secret} token=OTHER_PRIVATE_TOKEN"
    rig.trace.entries = [{
        "name": "browser", "is_error": True,
        "arguments": {
            "headers": {"Authorization": secret}, "password": "STRUCTURED_SECRET",
            "note": "y" * 300 + secret, "token": "NEAR_BOUNDARY_SECRET",
        },
        "output": raw * 3,
    }] * 30
    fault = replace(rig.fault, error_text=raw * 3, attempted=f"token={secret}")
    report = await build_issue_report(fault, attachment_store=rig.trace, secrets=(secret,))
    assert len(report.title) <= 120 and len(report.body) <= 12000
    assert fault.signature in report.body and fault.id in report.body
    for value in (secret, "OTHER_PRIVATE_TOKEN", "STRUCTURED_SECRET", "NEAR_BOUNDARY_SECRET"):
        assert value not in report.title + report.body + caplog.text
    assert "[REDACTED]" in report.body
    assert secret in fault.error_text, "stored diagnostic evidence must not be mutated"
    assert (await _decide(rig))["fulfilled"]
    sent = rig.http.requests[0].content.decode()
    for value in (secret, "OTHER_PRIVATE_TOKEN", "STRUCTURED_SECRET", "NEAR_BOUNDARY_SECRET"):
        assert value not in sent
    await rig.faults.file_fault(tool_id="shell", error_text="RAW_FAULT_SECRET")
    assert "RAW_FAULT_SECRET" not in caplog.text
    rig.trace.error = True
    missing = await build_issue_report(rig.fault, attachment_store=rig.trace, secrets=(secret,))
    assert "Trace unavailable" in missing.body
    assert "TRACE_EXCEPTION_SECRET" not in caplog.text + missing.body


_OUTBOUND_KEYS = (
    "password", "passwd", "passphrase", "secret", "token", "access_token",
    "refresh_token", "api_key", "authorization", "cookie", "set-cookie",
    "private_key", "client_secret", "headers", "credential", "credentials",
)


def _assert_safe_sent_report(rig, caplog, marker):
    assert len(rig.http.requests) == 1 and rig.http.requests[0].method == "POST"
    sent = rig.http.requests[0].content.decode()
    delivered = json.dumps(rig.runtime.notification_queue.snapshot())
    assert marker not in sent + caplog.text + delivered
    report = json.loads(sent)
    assert len(report["title"]) <= 120 and len(report["body"]) <= 12000
    assert rig.fault.id in report["body"] and rig.fault.signature in report["body"]
    assert "browser" in report["body"] and "Occurrences: 2" in report["body"]
    assert "[REDACTED]" in report["body"]
    return report


@pytest.mark.parametrize("key", (*_OUTBOUND_KEYS, "PRIVATE_KEY", "ssh_private_key"))
async def test_named_nested_secret_fields_are_absent_from_final_http_logs_and_notices(rig, caplog, key):
    caplog.set_level(logging.DEBUG, logger="probos")
    marker = "FAKE_NESTED_SECRET_MARKER"
    rig.trace.entries = [{
        "name": "browser", "is_error": True,
        "arguments": {key: marker, "action": "key_type", "text": "useful-trace-context"},
        "output": {"nested": [{key: marker}], "context": "useful-error-context"},
    }] * 2
    original = json.dumps(rig.trace.entries)
    assert (await _decide(rig))["fulfilled"]
    report = _assert_safe_sent_report(rig, caplog, marker)
    assert "useful-trace-context" in report["body"] and "useful-error-context" in report["body"]
    assert json.dumps(rig.trace.entries) == original


@pytest.mark.parametrize("rig", [
    {
        "error_text": f'Useful fault context: "{key}": "FAKE_ASSIGNMENT_MARKER with spaces"; safe-tail',
        "attempted": f"Enter a value; {key}='FAKE_ASSIGNMENT_MARKER with spaces'; safe-operation",
    }
    for key in _OUTBOUND_KEYS
], indirect=True, ids=_OUTBOUND_KEYS)
async def test_named_text_assignments_are_redacted_before_title_and_body_rendering(rig, caplog):
    caplog.set_level(logging.DEBUG, logger="probos")
    original = rig.fault.to_dict()
    assert (await _decide(rig))["fulfilled"]
    report = _assert_safe_sent_report(rig, caplog, "FAKE_ASSIGNMENT_MARKER")
    assert "Useful fault context" in report["title"] + report["body"]
    assert "safe-tail" in report["body"] and "safe-operation" in report["body"]
    assert rig.fault.to_dict() == original


@pytest.mark.parametrize("rig,marker", [
    ({"error_text": f"Useful fault context: {text}", "attempted": text}, marker)
    for text, marker in (
        ("Authorization: Basic RkFLRV9CQVNJQ19NQVRFUklBTA==", "RkFLRV9CQVNJQ19NQVRFUklBTA"),
        ("basic 'FAKE_QUOTED_BASIC with spaces'", "FAKE_QUOTED_BASIC"),
        ("Authorization: Bearer FAKE_BEARER_MARKER", "FAKE_BEARER_MARKER"),
        ("data:text/plain;base64,RkFLRV9EQVRBX01BUktFUg==", "RkFLRV9EQVRBX01BUktFUg"),
        ("response contained FAKE_GITHUB_TEST_CREDENTIAL", "FAKE_GITHUB_TEST_CREDENTIAL"),
        ("-----BEGIN PRIVATE KEY-----\nFAKE_PEM_MARKER\n-----END PRIVATE KEY-----", "FAKE_PEM_MARKER"),
        ("-----BEGIN RSA PRIVATE KEY-----\nFAKE_RSA_MARKER\n-----END RSA PRIVATE KEY-----", "FAKE_RSA_MARKER"),
        ("-----BEGIN OPENSSH PRIVATE KEY-----\nFAKE_OPENSSH_MARKER\n-----END OPENSSH PRIVATE KEY-----", "FAKE_OPENSSH_MARKER"),
        ("-----BEGIN EC PRIVATE KEY-----\nFAKE_EC_MARKER\n-----END EC PRIVATE KEY-----", "FAKE_EC_MARKER"),
        ("-----BEGIN PRIVATE KEY-----\nFAKE_UNTERMINATED_MARKER", "FAKE_UNTERMINATED_MARKER"),
        ("-----BEGIN RSA PRIVATE KEY-----\nFAKE_UNTERMINATED_RSA", "FAKE_UNTERMINATED_RSA"),
        ("-----BEGIN OPENSSH PRIVATE KEY-----\nFAKE_UNTERMINATED_OPENSSH", "FAKE_UNTERMINATED_OPENSSH"),
    )
], indirect=["rig"], ids=[
    "basic", "quoted-basic", "bearer", "data-uri", "resolved-credential",
    "pem", "rsa", "openssh", "ec", "unterminated", "unterminated-rsa", "unterminated-openssh",
])
async def test_named_secret_values_are_absent_from_final_http_logs_and_notices(rig, caplog, marker):
    caplog.set_level(logging.DEBUG, logger="probos")
    original = rig.fault.to_dict()
    rig.trace.entries = [{
        "name": "browser", "is_error": True,
        "arguments": {"note": rig.fault.attempted, "text": "useful-trace-context"},
        "output": rig.fault.error_text,
    }] * 2
    assert (await _decide(rig))["fulfilled"]
    report = _assert_safe_sent_report(rig, caplog, marker)
    assert "Useful fault context" in report["body"] and "useful-trace-context" in report["body"]
    assert rig.fault.to_dict() == original


@pytest.mark.parametrize("rig", [{
    "error_text": "Useful context " + "x" * 1920 + " passphrase=FAKE_CLIP_MARKER" * 3,
    "attempted": "x" * 940 + ' private_key="FAKE_CLIP_MARKER with a long unterminated value',
}], indirect=True)
async def test_redaction_precedes_fault_and_trace_summary_clipping(rig, caplog):
    caplog.set_level(logging.DEBUG, logger="probos")
    rig.trace.entries = [{
        "name": "browser", "is_error": True,
        "arguments": {"note": "x" * 50 + " Basic FAKE_CLIP_MARKER", "text": "useful-trace-context"},
        "output": "x" * 255 + " -----BEGIN PRIVATE KEY-----\nFAKE_CLIP_MARKER\n" + "x" * 1000,
    }] * 2
    assert "FAKE_CLIP" in rig.fault.error_text and len(rig.fault.error_text) == 2000
    assert (await _decide(rig))["fulfilled"]
    report = _assert_safe_sent_report(rig, caplog, "FAKE_CLIP")
    assert "Useful context" in report["body"] and "useful-trace-context" in report["body"]


@pytest.mark.parametrize("value", [
    "https://github.com/owner/repo", "owner/repo/issues", "owner", " owner/repo",
    "owner/repo?token=secret", "../repo", "owner/..", "owner/repo\n",
    "a--b/repo",
])
def test_repository_configuration_rejects_non_repository_destinations(value):
    with pytest.raises(ValueError, match="owner/repo"):
        RepairConfig(github_repository=value)


def test_repository_configuration_preserves_empty_boot_default_and_existing_policy():
    config = RepairConfig()
    assert config.model_dump() == {
        "enabled": False, "targets": ["architect"], "propose_after_occurrences": 2,
        "github_repository": "",
    }
    assert RepairConfig(github_repository="owner/repo").github_repository == "owner/repo"


async def test_complete_python_responses_match_shared_component_fixture(rig):
    fixture = json.loads((
        Path(__file__).resolve().parents[1] / "ui/e2e/fixtures/ad1206-repair-approvals.json"
    ).read_text(encoding="utf-8"))
    assert await list_actionable_capability_requests(rig.runtime) == fixture["pending"]
    rig.credentials.value = None
    assert await _decide(rig) == fixture["approved"]
    assert await list_actionable_capability_requests(rig.runtime) == {
        "view": "actionable", "requests": [fixture["approved"]["request"]],
    }
    rig.credentials.value = "FAKE_GITHUB_TEST_CREDENTIAL"
    assert await _decide(rig) == fixture["fulfilled"]
    assert await list_actionable_capability_requests(rig.runtime) == fixture["empty"]
    ordinary = await rig.requests.file_action_request("agent", _payload(tool_id="browser", action="click"))
    assert await list_actionable_capability_requests(rig.runtime) == fixture["ordinary_pending"]
    assert await _decide(rig, request=ordinary) == fixture["ordinary_approved"]
    assert await list_actionable_capability_requests(rig.runtime) == fixture["empty"]
    assert len(rig.http.requests) == 1


async def test_transport_cleanup_failure_after_post_is_not_a_presend_retry(rig, monkeypatch):
    class _FailingCloseClient(httpx.AsyncClient):
        async def aclose(self):
            await super().aclose()
            raise httpx.ConnectError("CLOSE_EXCEPTION_SECRET")

        async def __aexit__(self, *args):
            await super().__aexit__(*args)
            raise httpx.ConnectError("CLOSE_EXCEPTION_SECRET")

    original_factory = rig.http.factory
    monkeypatch.setattr(rig.http, "factory", lambda: _FailingCloseClient(
        transport=httpx.MockTransport(rig.http.handle), trust_env=False,
    ))
    rig.runtime.repair_issue_fulfiller = _consumer(rig)
    assert not (await _decide(rig))["fulfilled"]
    assert (await rig.faults.issue_filings.get(rig.fault.signature)).disposition == "outcome_unknown"
    monkeypatch.setattr(rig.http, "factory", original_factory)
    rig.runtime.repair_issue_fulfiller = _consumer(rig)
    assert (await _decide(rig))["fulfilled"]
    assert [request.method for request in rig.http.requests] == ["POST", "GET"]


async def test_concurrent_deny_before_approve_never_dispatches(rig):
    denied, approved = await asyncio.gather(
        _decide(rig, approve=False), _decide(rig), return_exceptions=True,
    )
    assert denied["request"]["status"] == "denied"
    assert isinstance(approved, HTTPException) and approved.status_code == 400
    assert (await rig.faults.issue_filings.get(rig.fault.signature)).disposition == "declined"
    assert len(rig.trust) == 1 and rig.http.requests == rig.credentials.calls == []


@pytest.mark.parametrize("minimum", [1, 2, 3])
async def test_existing_finalize_wiring_composes_an_idle_injected_consumer(rig, monkeypatch, minimum):
    from probos.startup.finalize import _wire_repair_dispatcher

    original_client = httpx.AsyncClient

    def fake_client(**kwargs):
        assert kwargs == {"timeout": 20.0, "follow_redirects": False}
        client = original_client(transport=httpx.MockTransport(rig.http.handle), trust_env=False)
        rig.http.clients.append(client)
        return client

    monkeypatch.setattr(httpx, "AsyncClient", fake_client)
    listeners = []
    rig.runtime.config.repair.propose_after_occurrences = minimum
    runtime = SimpleNamespace(
        fault_report_store=rig.faults, capability_request_store=rig.requests,
        credential_store=rig.credentials, attachment_store=rig.trace,
        config=rig.runtime.config, notify=rig.runtime.notify,
        add_event_listener=lambda *args, **kwargs: listeners.append((args, kwargs)),
    )
    assert _wire_repair_dispatcher(runtime=runtime, config=runtime.config)
    assert isinstance(runtime.repair_issue_fulfiller, RepairIssueFulfiller)
    assert len(listeners) == 1 and rig.credentials.calls == rig.http.requests == []
    result = await decide_capability_request(
        rig.request.id, CapabilityRequestDecideRequest(approve=True), runtime,
    )
    assert result["fulfilled"] is (minimum <= 2)
    assert len(rig.http.requests) == (1 if minimum <= 2 else 0)
    if minimum > 2:
        assert rig.credentials.calls == []
        assert await rig.faults.issue_filings.get(rig.fault.signature) is None


def _parse_repair_config(source: str, repair: dict[str, object], path: Path) -> SystemConfig:
    raw = {"repair": repair}
    if source == "model_validate":
        return SystemConfig.model_validate(raw)
    assert source == "load_config"
    path.write_text(json.dumps(raw), encoding="utf-8")
    return load_config(path)


def _config_wiring_runtime(
    rig: SimpleNamespace, config: object,
) -> tuple[SimpleNamespace, list[object]]:
    listeners: list[object] = []
    runtime = SimpleNamespace(
        fault_report_store=rig.faults, capability_request_store=rig.requests,
        credential_store=rig.credentials, attachment_store=rig.trace,
        config=config, notify=rig.runtime.notify,
        repair_dispatcher=object(), repair_issue_fulfiller=object(),
        add_event_listener=lambda *args, **kwargs: listeners.append((args, kwargs)),
    )
    return runtime, listeners


@pytest.mark.parametrize("source", ["model_validate", "load_config"])
@pytest.mark.parametrize("minimum", [
    pytest.param(None, id="none"),
    pytest.param(True, id="true"),
    pytest.param(False, id="false"),
    pytest.param(1.0, id="float"),
    pytest.param("1", id="string"),
    pytest.param(0, id="zero"),
    pytest.param(-1, id="negative"),
    pytest.param(2**63, id="overflow"),
])
async def test_system_config_invalid_repair_minimum_rejects_before_wiring(
    rig: SimpleNamespace, tmp_path: Path, source: str, minimum: object,
) -> None:
    from probos.startup.finalize import _wire_repair_dispatcher

    runtime, listeners = _config_wiring_runtime(rig, None)
    before = vars(runtime).copy()
    with pytest.raises(ValidationError) as caught:
        config = _parse_repair_config(
            source, {"propose_after_occurrences": minimum}, tmp_path / "system.yaml",
        )
        _wire_repair_dispatcher(runtime=runtime, config=config)
    assert any(
        error["loc"] == ("repair", "propose_after_occurrences")
        for error in caught.value.errors()
    )
    assert vars(runtime) == before and listeners == []
    assert rig.credentials.calls == rig.http.requests == rig.http.clients == []
    assert await rig.faults.issue_filings.get(rig.fault.signature) is None


@pytest.mark.parametrize("source", ["model_validate", "load_config", "non_model"])
@pytest.mark.parametrize("enabled", [False, True])
@pytest.mark.parametrize("minimum", [
    pytest.param(None, id="default"),
    pytest.param(1, id="min"),
    pytest.param(2**63 - 1, id="max"),
])
async def test_system_config_valid_repair_minimum_reaches_wired_approval_consumer(
    rig: SimpleNamespace, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
    source: str, enabled: bool, minimum: int | None,
) -> None:
    from probos.startup.finalize import _wire_repair_dispatcher

    repair: dict[str, object] = {"enabled": enabled, "github_repository": "owner/repo"}
    if minimum is not None:
        repair["propose_after_occurrences"] = minimum
    parsed = _parse_repair_config(
        "model_validate" if source == "non_model" else source,
        repair, tmp_path / "system.yaml",
    )
    expected = 2 if minimum is None else minimum
    assert type(parsed.repair.propose_after_occurrences) is int
    assert parsed.repair.propose_after_occurrences == expected
    config = (
        SimpleNamespace(repair=SimpleNamespace(**parsed.repair.model_dump()))
        if source == "non_model" else parsed
    )
    runtime, listeners = _config_wiring_runtime(rig, config)
    original_client = httpx.AsyncClient

    def fake_client(**kwargs):
        assert kwargs == {"timeout": 20.0, "follow_redirects": False}
        client = original_client(transport=httpx.MockTransport(rig.http.handle), trust_env=False)
        rig.http.clients.append(client)
        return client

    monkeypatch.setattr(httpx, "AsyncClient", fake_client)
    assert _wire_repair_dispatcher(runtime=runtime, config=config)
    assert isinstance(runtime.repair_issue_fulfiller, RepairIssueFulfiller)
    assert len(listeners) == 1
    assert rig.credentials.calls == rig.http.requests == rig.http.clients == []
    result = await decide_capability_request(
        rig.request.id, CapabilityRequestDecideRequest(approve=True), runtime,
    )
    fulfilled = enabled and expected <= rig.fault.occurrences
    assert result["fulfilled"] is fulfilled
    assert len(rig.http.requests) == len(rig.http.remote) == len(rig.credentials.calls) == int(fulfilled)
    if not fulfilled:
        assert result["request"]["can_retry_fulfilment"]
        assert await rig.faults.issue_filings.get(rig.fault.signature) is None


@pytest.mark.parametrize("shape", ["mutated_model", "non_model"])
@pytest.mark.parametrize("enabled", [False, True])
@pytest.mark.parametrize("minimum", [
    pytest.param(None, id="none"),
    pytest.param(True, id="true"),
    pytest.param(False, id="false"),
    pytest.param(1.0, id="float"),
    pytest.param("1", id="string"),
    pytest.param(0, id="zero"),
    pytest.param(-1, id="negative"),
    pytest.param(2**63, id="overflow"),
])
async def test_finalize_wiring_invalid_repair_minimum_leaves_no_partial_wiring(
    rig: SimpleNamespace, shape: str, enabled: bool, minimum: object,
) -> None:
    from probos.startup.finalize import _wire_repair_dispatcher

    config = SystemConfig.model_validate({
        "repair": {"enabled": enabled, "github_repository": "owner/repo"},
    })
    config.repair.propose_after_occurrences = minimum
    if shape == "non_model":
        config = SimpleNamespace(repair=SimpleNamespace(**vars(config.repair)))
    runtime, listeners = _config_wiring_runtime(rig, config)
    before = vars(runtime).copy()
    with pytest.raises(ValueError, match="^invalid_minimum_occurrences$"):
        _wire_repair_dispatcher(runtime=runtime, config=config)
    assert vars(runtime) == before and listeners == []
    assert rig.credentials.calls == rig.http.requests == rig.http.clients == []
    assert await rig.faults.issue_filings.get(rig.fault.signature) is None


@pytest.mark.parametrize("shape", ["mutated_model", "non_model"])
async def test_finalize_wiring_missing_repair_minimum_does_not_fallback(
    rig: SimpleNamespace, shape: str,
) -> None:
    from probos.startup.finalize import _wire_repair_dispatcher

    config = SystemConfig()
    del config.repair.propose_after_occurrences
    if shape == "non_model":
        config = SimpleNamespace(repair=SimpleNamespace(**vars(config.repair)))
    runtime, listeners = _config_wiring_runtime(rig, config)
    before = vars(runtime).copy()
    with pytest.raises(ValueError, match="^invalid_minimum_occurrences$"):
        _wire_repair_dispatcher(runtime=runtime, config=config)
    assert vars(runtime) == before and listeners == []
    assert rig.credentials.calls == rig.http.requests == rig.http.clients == []
    assert await rig.faults.issue_filings.get(rig.fault.signature) is None


@pytest.mark.parametrize("missing", ["repair_absent", "repair_none", "fault_absent", "fault_none"])
async def test_finalize_wiring_legitimately_unwired_preserves_runtime(
    rig: SimpleNamespace, missing: str,
) -> None:
    from probos.startup.finalize import _wire_repair_dispatcher

    config = SimpleNamespace(repair=SimpleNamespace(propose_after_occurrences=True))
    runtime, listeners = _config_wiring_runtime(rig, config)
    if missing == "repair_absent":
        del config.repair
    elif missing == "repair_none":
        config.repair = None
    elif missing == "fault_absent":
        del runtime.fault_report_store
    else:
        runtime.fault_report_store = None
    before = vars(runtime).copy()
    assert not _wire_repair_dispatcher(runtime=runtime, config=config)
    assert vars(runtime) == before and listeners == []
    assert rig.credentials.calls == rig.http.requests == rig.http.clients == []


async def test_cancelled_presend_with_failed_status_commit_retains_uncertain_notice(rig):
    rig.trace.pause = True
    task = asyncio.create_task(_decide(rig))
    try:
        await asyncio.wait_for(rig.trace.entered.wait(), 3)
        rig.fault_connection.fail_commit = True
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert (await rig.faults.issue_filings.get(rig.fault.signature)).disposition == "attempting"
        notice = rig.runtime.notification_queue.snapshot()[0]
        assert "only reconciles" in notice["detail"]
        rig.trace.pause = False
        assert not (await _decide(rig))["fulfilled"]
        assert [request.method for request in rig.http.requests] == ["GET"]
    finally:
        await asyncio.gather(task, return_exceptions=True)
