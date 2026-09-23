"""Automated HXI chat integration tests.

These tests start a ProbOS runtime with MockLLMClient and test
the /api/chat endpoint with common user queries to catch regressions.
"""

import asyncio
import contextlib
import copy
import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from httpx import AsyncClient, ASGITransport
from pydantic import TypeAdapter

from probos.api import create_app
from probos.cognitive.llm_client import MockLLMClient
from probos.config import SystemConfig
from probos.runtime import ProbOSRuntime
from probos.types import LLMRequest, LLMResponse, Priority
from probos.utils import response_formatter


_CALCULATOR_SCENARIOS = {
    "calculate 17 multiplied by 23 and return only the answer": [("17*23", "391")],
    "calculate 11 multiplied by 13 and return only the answer": [("11*13", "143")],
    "calculate 17 multiplied by 23 twice as separate tasks": [
        ("17*23", "391"), ("17*23", "391"),
    ],
}


@pytest.mark.parametrize("mode", ["inline", "promoted", "outbox", "lost_ack"])
async def test_consulted_real_turn_persists_own_ref_and_safe_http_without_body_changes(
    tmp_path: Path, mode: str,
) -> None:
    from tests.fixtures.consulted_evidence_bridge import (
        ConsultedEvidenceFixture, OUTPUT_SENTINEL, REPLY_BODY, REPOSITORY,
        SENSITIVE_SENTINEL, fixture_origins,
    )

    origins = fixture_origins(Path(__file__).resolve().parents[1])
    assert Path(origins["agent"]).is_relative_to(Path(origins["root"]) / "src")
    fixture = ConsultedEvidenceFixture(tmp_path)
    try:
        await fixture.start()
        snapshot = await fixture.start_turn(mode=mode)
        if mode != "inline":
            assert snapshot["llm_calls"] == 1 and not snapshot["released"]
            acknowledgement = snapshot["messages"][-1]
            assert acknowledgement["body"] == snapshot["reply"]["response"]
            assert "tool_trace_ref" not in acknowledgement["metadata"]
            snapshot = await fixture.release_turn(snapshot["turn"])
        if mode in {"outbox", "lost_ack"}:
            assert len(snapshot["pending"]) == 1
            pending = snapshot["pending"][0]
            assert pending["tool_trace_ref"] is not None
            attempts = snapshot["attempts"]
            assert len(attempts) == 3 and attempts[0] == attempts[1] == attempts[2]
            assert attempts[0]["message_id"] == pending["message_id"]
            assert attempts[0]["metadata"]["tool_trace_ref"] == pending["tool_trace_ref"]
            snapshot = await fixture.recover(snapshot["turn"])
            assert snapshot["pending"] == []
            assert snapshot["recovered"] == pending
        replies = [message for message in snapshot["messages"] if message["body"] == REPLY_BODY]
        assert len(replies) == 1
        message = replies[0]
        assert message["thread_id"] == snapshot["thread"]["id"]
        assert message["author_id"] == snapshot["agent"] == "yeo"
        ref = message["metadata"]["tool_trace_ref"]
        raw_trace = await fixture.attachments.read(ref)
        assert hashlib.sha256(raw_trace).hexdigest() == ref
        entries = json.loads(raw_trace)
        assert len(entries) == 1
        assert entries[0]["arguments"]["repoName"] == REPOSITORY
        assert entries[0]["arguments"]["query"] == snapshot["query"]
        assert SENSITIVE_SENTINEL.encode() in raw_trace
        assert OUTPUT_SENTINEL.encode() in raw_trace
        before = copy.deepcopy(snapshot["messages"])
        for _ in range(2):
            response = await fixture.client.get(f"/api/traces/{ref}/consulted")
            assert response.status_code == 200
            wire = response.content
            assert len(wire) <= 16 * 1024
            assert SENSITIVE_SENTINEL.encode() not in wire
            assert OUTPUT_SENTINEL.encode() not in wire
            assert b"fixture-user" not in wire
            assert b'"output"' not in wire and b'"calls"' not in wire
            assert response.headers["cache-control"] == "no-store"
            receipt = response.json()
            assert set(receipt) == {
                "ref", "requests", "requests_total", "requests_omitted",
                "invalid_entries", "redacted", "truncated", "notice",
            }
            assert receipt["ref"] == ref
            assert receipt["requests_total"] == len(receipt["requests"]) + receipt["requests_omitted"] == 1
            assert receipt["invalid_entries"] == 0 and receipt["redacted"] is True
            assert REPOSITORY in "\n".join(receipt["requests"])
            assert snapshot["query"] in "\n".join(receipt["requests"])
            assert "https://example.test/repos/langchain" in "\n".join(receipt["requests"])
        transcript = await fixture.client.get(f"/api/threads/{message['thread_id']}/messages")
        assert transcript.status_code == 200
        assert transcript.json()["messages"] == before
        after = await fixture.snapshot(snapshot["turn"])
        assert after["messages"] == before
        assert after["llm_calls"] == 2 and after["tool_calls"] == 1
        if mode == "inline":
            assert after["reply"]["response"] == REPLY_BODY
        else:
            assert after["messages"][1]["body"] == acknowledgement["body"]
            assert after["messages"][1]["metadata"] == acknowledgement["metadata"]
    finally:
        await fixture.stop()


async def test_consulted_create_app_authorizes_before_storage_and_default_off_works(tmp_path: Path) -> None:
    from probos.attachments.filesystem_store import FilesystemAttachmentStore
    from tests.fixtures.consulted_evidence_bridge import ConsultedEvidenceFixture

    class _CountingStore(FilesystemAttachmentStore):
        reads = 0

        async def read(self, content_hash: str) -> bytes:
            self.reads += 1
            return await super().read(content_hash)

    fixture = ConsultedEvidenceFixture(tmp_path)
    try:
        await fixture.start()
        turn = await fixture.start_turn(mode="inline")
        ref = turn["messages"][-1]["metadata"]["tool_trace_ref"]
        store = _CountingStore(tmp_path / "attachments")
        fixture.runtime.attachments = store
        fixture.runtime.config.auth.crew_scope_token = "synthetic-consulted-auth"
        for headers in ({}, {"Authorization": "Bearer incorrect"}):
            denied = await fixture.client.get(f"/api/traces/{ref}/consulted", headers=headers)
            assert denied.status_code == 401
            assert denied.headers["cache-control"] == "no-store"
            assert b"synthetic-consulted-auth" not in denied.content
            assert store.reads == 0
        authorized = await fixture.client.get(
            f"/api/traces/{ref}/consulted",
            headers={"Authorization": "Bearer synthetic-consulted-auth"},
        )
        assert authorized.status_code == 200
        assert authorized.headers["cache-control"] == "no-store"
        assert store.reads == 1
        fixture.runtime.config.auth.crew_scope_token = ""
        default_off = await fixture.client.get(f"/api/traces/{ref}/consulted")
        assert default_off.status_code == 200 and store.reads == 2
        invalid = await fixture.client.get("/api/traces/not-a-trace/consulted")
        assert invalid.status_code == 400 and store.reads == 2
        assert invalid.headers["cache-control"] == "no-store"
    finally:
        await fixture.stop()


async def test_consulted_real_promoted_commit_reaches_live_http_event_consumer(tmp_path: Path) -> None:
    from websockets.asyncio.client import connect

    from tests.fixtures.consulted_evidence_bridge import ConsultedEvidenceFixture, REPLY_BODY

    fixture = ConsultedEvidenceFixture(tmp_path)
    try:
        await fixture.start()
        async with connect(fixture.origin.replace("http://", "ws://") + "/ws/events") as socket:
            initial = json.loads(await asyncio.wait_for(socket.recv(), timeout=5))
            assert initial["type"] == "state_snapshot"

            async def _committed(message_id: str) -> dict[str, Any]:
                async with asyncio.timeout(5):
                    while True:
                        frame = json.loads(await socket.recv())
                        if (
                            frame.get("type") == "chat_thread_message_appended"
                            and frame["data"].get("message_id") == message_id
                        ):
                            return frame

            acknowledged = await fixture.start_turn(mode="promoted")
            acknowledgement = acknowledged["messages"][-1]
            first = await _committed(acknowledgement["id"])
            assert first["data"]["thread_id"] == acknowledged["thread"]["id"]
            assert not acknowledged["released"]
            assert "tool_trace_ref" not in acknowledgement["metadata"]
            completed = await fixture.release_turn(acknowledged["turn"])
            report = completed["messages"][-1]
            final = await _committed(report["id"])
            assert final["data"]["thread_id"] == report["thread_id"]
            assert final["data"]["author_id"] == report["author_id"] == "yeo"
            assert "body" not in final["data"] and "metadata" not in final["data"]
            assert report["body"] == REPLY_BODY
            ref = report["metadata"]["tool_trace_ref"]
            receipt = await fixture.client.get(f"/api/traces/{ref}/consulted")
            assert receipt.status_code == 200 and receipt.json()["ref"] == ref
            assert completed["llm_calls"] == 2 and completed["tool_calls"] == 1
    finally:
        await fixture.stop()


class _CalculatorDAGClient(MockLLMClient):
    async def complete(
        self, request: LLMRequest, *, priority: Priority = Priority.NORMAL,
    ) -> LLMResponse:
        message = request.prompt.lower().rsplit("user request: ", 1)[-1].strip()
        expressions = _CALCULATOR_SCENARIOS.get(message)
        if expressions is None:
            return await super().complete(request, priority=priority)
        content = json.dumps({
            "intents": [
                {
                    "id": f"calculation-{index}",
                    "intent": "calculate",
                    "params": {"expression": expression},
                    "depends_on": [],
                    "use_consensus": False,
                }
                for index, (expression, _) in enumerate(expressions)
            ],
            "reflect": False,
        })
        return LLMResponse(
            content=content, model="mock", tier=request.tier, request_id=request.id,
        )


async def _calculator_api_responses(
    requests: list[dict[str, Any]], data_dir: Path,
) -> list[dict[str, Any]]:
    config = SystemConfig()
    config.utility_agents.enabled = True
    config.qa.enabled = False
    runtime = ProbOSRuntime(
        config=config, data_dir=data_dir, llm_client=_CalculatorDAGClient(),
    )
    extracted: list[dict[str, Any]] = []
    original_formatter = response_formatter.extract_response_text

    def capture_response(dag_result: dict[str, Any] | None) -> str:
        assert dag_result is not None
        assert not dag_result.get("response")
        assert not dag_result.get("reflection")
        original = copy.deepcopy(dag_result)
        contribution_list = dag_result["results"]
        references = {
            node_id: tuple(node["results"])
            for node_id, node in contribution_list.items()
        }
        response = original_formatter(dag_result)
        assert dag_result == original
        assert dag_result["results"] is contribution_list
        for node_id, contributions in references.items():
            assert all(
                before is after
                for before, after in zip(contributions, contribution_list[node_id]["results"])
            )
        extracted.append(TypeAdapter(dict[str, Any]).dump_python(contribution_list, mode="json"))
        return response

    responses: list[dict[str, Any]] = []
    try:
        await runtime.start()
        app = create_app(runtime)
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test",
        ) as client:
            with patch.object(response_formatter, "extract_response_text", capture_response):
                previous_message = None
                for request in requests:
                    if request["message"] != previous_message:
                        runtime.workflow_cache.clear()
                    previous_message = request["message"]
                    scenarios = _CALCULATOR_SCENARIOS[request["message"]]
                    extraction_count = len(extracted)
                    response = await client.post("/api/chat", json=request)
                    assert response.status_code == 200, response.text
                    payload = response.json()
                    assert len(extracted) == extraction_count + 1
                    assert payload["results"] == extracted[-1]
                    assert payload["dag"]["source_text"] == request["message"]
                    assert payload["dag"]["reflect"] is False
                    assert len(payload["results"]) == len(scenarios)
                    assert list(payload["results"]) == list(extracted[-1])
                    for node, (_, answer) in zip(payload["results"].values(), scenarios):
                        contributors = node["results"]
                        assert len(contributors) >= 2
                        assert node["result_count"] == len(contributors)
                        assert len({item["agent_id"] for item in contributors}) == len(contributors)
                        assert len({item["intent_id"] for item in contributors}) == 1
                        for item in contributors:
                            assert set(item) == {
                                "intent_id", "agent_id", "success", "result", "error",
                                "confidence", "timestamp", "metadata",
                            }
                            assert item["success"] is True
                            assert item["result"] == answer
                            assert item["error"] is None
                    assert payload["response"] == "\n".join(answer for _, answer in scenarios)
                    responses.append(payload)
    finally:
        await runtime.stop()
    return responses


@pytest.mark.asyncio
async def test_global_calculators_preserve_contributors_and_independent_requests(tmp_path):
    repeated, different, separate = _CALCULATOR_SCENARIOS
    requests = [{"message": message} for message in (repeated, repeated, different, separate)]
    responses = await _calculator_api_responses(requests, tmp_path / "calculator-data")
    assert [response["response"] for response in responses] == ["391", "391", "143", "391\n391"]


def _calculator_bridge() -> dict[str, Any]:
    with contextlib.redirect_stdout(sys.stderr):
        root = Path(__file__).resolve().parents[1]
        assert Path(response_formatter.__file__).resolve().is_relative_to(root / "src")
        request_bytes = sys.stdin.buffer.read(65537)
        if len(request_bytes) > 65536:
            raise ValueError("Calculator test request exceeds 65536 bytes")
        requests = json.loads(request_bytes)
        repeated, different, separate = _CALCULATOR_SCENARIOS
        expected_messages = [repeated, repeated, different, separate, repeated]
        if type(requests) is not list or len(requests) != len(expected_messages):
            raise ValueError("Calculator bridge requires the complete five-request batch")
        if any(
            type(request) is not dict or request.get("message") != expected
            for request, expected in zip(requests, expected_messages)
        ):
            raise ValueError("Unsupported or misordered calculator test scenario")
        data_dir = Path(os.environ["PROBOS_DATA_DIR"]).resolve()
        if (
            data_dir.parent != Path(tempfile.gettempdir()).resolve()
            or not data_dir.name.startswith("probos-calculator-test-")
            or not data_dir.is_dir()
        ):
            raise ValueError("Calculator bridge requires a caller-owned temporary data directory")
        responses = asyncio.run(_calculator_api_responses(requests, data_dir))
    return {
        "pairs": [
            {"request": request, "envelope": response}
            for request, response in zip(requests, responses)
        ],
    }


@pytest.fixture
async def chat_client(tmp_path):
    """Create a test client with a running ProbOS runtime."""
    rt = ProbOSRuntime(data_dir=tmp_path / "data", llm_client=MockLLMClient())
    await rt.start()
    app = create_app(rt)
    assert app.state.broadcast_event is None
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
    await rt.stop()


@pytest.mark.asyncio
async def test_owned_steps_real_create_app_auth_and_legacy_wire(
    tmp_path: Path,
    monkeypatch,
) -> None:
    rt = ProbOSRuntime(
        data_dir=tmp_path / "owned-steps-data",
        llm_client=MockLLMClient(),
    )
    await rt.start()
    item = await rt.work_item_store.create_work_item(
        id="hxi-owned-unmanaged",
        title="HXI unmanaged",
        steps=[
            {
                "label": "Wire row",
                "status": "pending",
                "assigned_to": None,
                "submitted_by": None,
                "confirmed_by": None,
                "note": None,
            }
        ],
    )
    app = create_app(rt)
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:
            legacy = await client.get(f"/api/work-items/{item.id}/steps")
            assert legacy.content == (
                b'{"steps":[{"label":"Wire row","status":"pending",'
                b'"assigned_to":null,"submitted_by":null,'
                b'"confirmed_by":null,"note":null}],'
                b'"gate_completion":false}'
            )
            unmanaged = await client.get(
                f"/api/work-items/{item.id}/owned-steps"
            )
            assert unmanaged.status_code == 200
            assert unmanaged.json()["mode"] == "unmanaged"
            assert unmanaged.json()["rows"][0]["todo"] == item.steps[0]
            reads = 0
            original = rt.work_item_store.resolve_owned_steps_parent_id

            async def counted(work_item_id: str):
                nonlocal reads
                reads += 1
                return await original(work_item_id)

            monkeypatch.setattr(
                rt.work_item_store,
                "resolve_owned_steps_parent_id",
                counted,
            )
            rt.config.auth.crew_scope_token = "hxi-owned-secret"
            denied = await client.get(
                f"/api/work-items/{item.id}/owned-steps"
            )
            assert denied.status_code == 401
            assert reads == 0
    finally:
        await rt.stop()


class TestChatEndpoint:
    """Test common chat queries don't crash or hang."""

    @pytest.mark.asyncio
    async def test_hello(self, chat_client):
        """Conversational greeting returns a response."""
        r = await chat_client.post("/api/chat", json={"message": "hello"})
        assert r.status_code == 200
        data = r.json()
        assert data["response"]  # non-empty

    @pytest.mark.asyncio
    async def test_what_can_you_do(self, chat_client):
        """Capability question returns a response."""
        r = await chat_client.post("/api/chat", json={"message": "what can you do?"})
        assert r.status_code == 200
        data = r.json()
        assert data["response"]  # non-empty

    @pytest.mark.asyncio
    async def test_read_file(self, chat_client):
        """File read query produces a result."""
        r = await chat_client.post(
            "/api/chat", json={"message": "read the file at /tmp/test.txt"}
        )
        assert r.status_code == 200
        data = r.json()
        assert data.get("response") or data.get("results")

    @pytest.mark.asyncio
    async def test_slash_status(self, chat_client):
        """Slash command /status returns clean text."""
        r = await chat_client.post("/api/chat", json={"message": "/status"})
        assert r.status_code == 200
        data = r.json()
        assert data["response"]
        # Should NOT contain box-drawing characters
        assert "\u2502" not in data["response"]
        assert "\u2500" not in data["response"]

    @pytest.mark.asyncio
    async def test_slash_model(self, chat_client):
        """Slash command /model returns LLM info."""
        r = await chat_client.post("/api/chat", json={"message": "/model"})
        assert r.status_code == 200
        data = r.json()
        assert data["response"]

    @pytest.mark.asyncio
    async def test_slash_help(self, chat_client):
        """Slash command /help returns command list."""
        r = await chat_client.post("/api/chat", json={"message": "/help"})
        assert r.status_code == 200
        data = r.json()
        assert data["response"]

    @pytest.mark.asyncio
    async def test_slash_quit_blocked(self, chat_client):
        """Slash command /quit is blocked from API."""
        r = await chat_client.post("/api/chat", json={"message": "/quit"})
        assert r.status_code == 200
        data = r.json()
        assert "not available" in data["response"].lower() or "CLI" in data["response"]

    @pytest.mark.asyncio
    async def test_slash_feedback_no_execution(self, chat_client):
        """/feedback good without prior execution returns appropriate message."""
        r = await chat_client.post("/api/chat", json={"message": "/feedback good"})
        assert r.status_code == 200
        data = r.json()
        assert data["response"]  # should say something about no recent execution

    @pytest.mark.asyncio
    async def test_empty_message(self, chat_client):
        """Empty message doesn't crash."""
        r = await chat_client.post("/api/chat", json={"message": ""})
        assert r.status_code == 200

    @pytest.mark.asyncio
    async def test_timeout_handling(self, chat_client):
        """Long-running query eventually returns (doesn't hang forever)."""
        r = await chat_client.post(
            "/api/chat",
            json={"message": "what time is it in Tokyo, Japan?"},
            timeout=35.0,
        )
        assert r.status_code == 200
        data = r.json()
        assert data["response"]


class TestHealthEndpoint:
    """Test health and status endpoints."""

    @pytest.mark.asyncio
    async def test_health(self, chat_client):
        r = await chat_client.get("/api/health")
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "ok"
        assert data["agents"] > 0

    @pytest.mark.asyncio
    async def test_status(self, chat_client):
        r = await chat_client.get("/api/status")
        assert r.status_code == 200
        data = r.json()
        assert "total_agents" in data
