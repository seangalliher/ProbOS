"""AD-1191 producer -> delegate -> adapter -> next parent request crossings."""

from __future__ import annotations

import asyncio
import copy
import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest

from probos.artifacts import ArtifactStore
from probos.cognitive.agentic_dispatch import WorkItemAgenticExecutor, WorkItemAgenticOutcome
from probos.cognitive.swe_harness.tool_call import TextBlock, ToolCallRequest, ToolUseBlock
from probos.config import AgenticLoopConfig, AgenticToolsConfig, ExecutionConfig
from probos.consensus.trust import TrustNetwork
from probos.crew_profile import CallsignRegistry
from probos.tools.code_execution_tool import CodeExecutionTool
from probos.tools.delegate_task_tool import DelegateTaskTool
from probos.tools.delegation_evidence import (
    DelegatedToolResult,
    DelegationEvidence,
    MAX_FRAME_BYTES,
    MAX_TRANSPORT_BYTES,
    MESSAGE_OMISSION_MARKER,
)
from probos.tools.permissions import ToolPermissionStore
from probos.tools.protocol import ToolResult, ToolType
from probos.tools.publish_finding_tool import FindingToolResult, PublishFindingTool
from probos.tools.registry import ToolRegistry


@dataclass
class _Agent:
    id: str
    pool: str
    instructions: str
    agent_type: str = "researcher"
    department: str = "science"
    rank: str = "lieutenant"
    is_alive: bool = True


class _Registry:
    def __init__(self) -> None:
        self.agents = [
            _Agent("parent", "parent", "parent instructions"),
            _Agent("child", "child", "child instructions"),
            _Agent("grandchild", "grandchild", "grandchild instructions"),
        ]
        self.missing_identity: set[str] = set()

    def get(self, agent_id: str) -> _Agent | None:
        if agent_id in self.missing_identity:
            return None
        return next((agent for agent in self.agents if agent.id == agent_id), None)

    def get_by_pool(self, pool_name: str) -> list[_Agent]:
        return [agent for agent in self.agents if agent.pool == pool_name]

    def all(self) -> list[_Agent]:
        return list(self.agents)


class _Ontology:
    def get_agent_department(self, agent_type: str) -> str | None:
        return "science" if agent_type == "researcher" else None


class _Attachments:
    def __init__(self) -> None:
        self.blobs: dict[str, bytes] = {}
        self.writes: list[tuple[str, str]] = []
        self.fail_trace = False

    async def write(
        self, content_hash: str, blob: bytes, mime: str, *, origin: str = "chat_attachment",
    ) -> Path:
        assert hashlib.sha256(blob).hexdigest() == content_hash
        if self.fail_trace and origin == "crew_trace":
            raise OSError("local trace store failure")
        self.blobs[content_hash] = blob
        self.writes.append((content_hash, origin))
        return Path(content_hash)


class _Records:
    """The exact write/dedup port, retaining the bytes and frontmatter it receives."""

    def __init__(self) -> None:
        self.writes: list[dict[str, Any]] = []
        self.attempts = 0
        self.fail_write = False

    async def check_notebook_similarity(
        self, *, callsign: str, topic_slug: str, new_content: str,
        similarity_threshold: float, staleness_hours: float, max_scan_entries: int,
    ) -> dict[str, Any]:
        path = f"notebooks/{callsign}/{topic_slug}.md"
        return (
            {"action": "suppress", "existing_path": path}
            if any(write["path"] == path for write in self.writes)
            else {"action": "write"}
        )

    async def write_notebook(
        self, *, callsign: str, topic_slug: str, content: str, department: str,
        tags: list[str], classification: str, extra_frontmatter: dict[str, Any],
    ) -> str:
        self.attempts += 1
        if self.fail_write:
            raise OSError("local records write failure")
        path = f"notebooks/{callsign}/{topic_slug}.md"
        self.writes.append({
            "path": path, "callsign": callsign, "body_bytes": content.encode("utf-8"),
            "department": department, "tags": tags, "classification": classification,
            "frontmatter": copy.deepcopy(extra_frontmatter),
        })
        return path


@dataclass
class _Response:
    content: str = ""
    content_blocks: list[Any] = field(default_factory=list)
    tokens_used: int = 3


def _text(text: str) -> _Response:
    return _Response(content=text, content_blocks=[TextBlock(text=text)])


def _use(name: str, params: dict[str, Any], call_id: str) -> ToolUseBlock:
    return ToolUseBlock(tool_call=ToolCallRequest(name=name, arguments=params, id=call_id))


def _calls(*uses: ToolUseBlock) -> _Response:
    return _Response(content_blocks=list(uses))


def _finding(title: str = "Evidence title", *, classification: str = "ship") -> dict[str, Any]:
    return {
        "title": f"  {title}  ", "claim": "  Original claim \u00e9  ",
        "basis": "  Measured basis  ", "classification": classification,
    }


class _LLM:
    def __init__(self, responses: list[_Response | Exception]) -> None:
        self.responses = list(responses)
        self.requests: list[Any] = []

    async def complete(self, request: Any, **kwargs: Any) -> _Response:
        self.requests.append(copy.deepcopy(request))
        assert self.responses, "fixture exhausted before the real parent crossing"
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class _RecordingDelegate(DelegateTaskTool):
    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.results: list[DelegatedToolResult] = []
        self.contexts: list[dict[str, Any]] = []

    async def invoke(
        self, params: dict[str, Any], context: dict[str, Any] | None = None,
    ) -> ToolResult:
        self.contexts.append(dict(context or {}))
        result = await super().invoke(params, context)
        assert isinstance(result, DelegatedToolResult)
        self.results.append(result)
        return result


class _RecordingPublication(PublishFindingTool):
    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.results: list[ToolResult] = []
        self.contexts: list[dict[str, Any]] = []

    async def invoke(
        self, params: dict[str, Any], context: dict[str, Any] | None = None,
    ) -> ToolResult:
        self.contexts.append(dict(context or {}))
        result = await super().invoke(params, context)
        self.results.append(result)
        return result


class _RecordingPython(CodeExecutionTool):
    def __init__(self, *, runtime: Any) -> None:
        super().__init__(runtime=runtime)
        self.results: list[ToolResult] = []

    async def invoke(
        self, params: dict[str, Any], context: dict[str, Any] | None = None,
    ) -> ToolResult:
        result = await super().invoke(params, context)
        self.results.append(result)
        return result


def _runtime(
    tmp_path: Path, llm: Any, *, structured: bool = False, cap: int = 0,
    max_depth: int = 1, max_iterations: int = 5, max_publications: int = 12,
) -> SimpleNamespace:
    profiles = tmp_path / "profiles"
    profiles.mkdir(parents=True)
    agents = _Registry()
    for agent in agents.all():
        (profiles / f"{agent.pool}.yaml").write_text(
            f"callsign: {agent.pool.capitalize()}\ndisplay_name: {agent.pool}\ndepartment: science\n",
            encoding="utf-8",
        )
    callsigns = CallsignRegistry()
    callsigns.load_from_profiles(str(profiles))
    callsigns.bind_registry(agents)
    permissions = ToolPermissionStore()
    registry = ToolRegistry()
    registry.set_permission_store(permissions)
    runtime = SimpleNamespace(
        callsign_registry=callsigns, registry=agents, ontology=_Ontology(),
        trust_network=TrustNetwork(), tool_registry=registry,
        tool_permission_store=permissions, intent_bus=None, intent_grant_store=None,
        mcp_workbench=None, attachment_store=_Attachments(),
        artifact_store=ArtifactStore(tmp_path / "artifacts.db"), cognitive_skill_catalog=None,
        emit_event=None,
        config=SimpleNamespace(
            execution=ExecutionConfig(
                enabled=True, scratch_dir=str(tmp_path / "scratch"), stage_thread_artifacts=False,
            ),
            mcp=None,
            agentic_tools=AgenticToolsConfig(
                delegation_enabled=True, delegation_max_depth=max_depth,
                delegation_max_iterations=max_iterations,
            ),
            agentic_loop=AgenticLoopConfig(
                structured_tool_messages=structured, tool_result_max_chars=cap,
            ),
        ),
    )
    runtime.records = _Records()
    runtime.publisher = _RecordingPublication(
        records_store=runtime.records, callsign_resolver=lambda agent_id: (agent_id.capitalize(), "science"),
        source_node="local-node", max_per_hour=max_publications,
    )
    registry.register(
        runtime.publisher, provider="local-test", allowed_departments=("science",),
        default_permissions={"ensign": "write", "lieutenant": "write"},
    )
    runtime.python = _RecordingPython(runtime=runtime)
    registry.register(runtime.python, provider="local-test")
    runtime.delegator = _RecordingDelegate(
        runtime=runtime, llm_client=llm, max_depth=max_depth,
        max_iterations=max_iterations, tier="standard",
    )
    registry.register(runtime.delegator, provider="local-test")
    return runtime


async def _parent(runtime: SimpleNamespace, llm: Any) -> WorkItemAgenticOutcome:
    return await WorkItemAgenticExecutor(llm_client=llm).run(
        agent_id="parent", instructions="parent instructions", task_text="delegate the work",
        runtime=runtime, thread_id="thread", max_iterations=6,
    )


def _parent_tool_content(request: Any, *, structured: bool, call_id: str = "delegation") -> str:
    if structured:
        matched = [
            message["content"] for message in request.messages
            if message.get("role") == "tool" and message.get("tool_call_id") == call_id
        ]
        assert len(matched) == 1, "parent NEXT request must contain the correlated tool message"
        return matched[0]
    markers = [f"[tool_result:{call_id} error={error}]\n" for error in ("False", "True")]
    matched = [marker for marker in markers if marker in request.prompt]
    assert len(matched) == 1, "parent NEXT request must contain the flattened tool result"
    assert request.prompt.count(matched[0]) == 1
    return request.prompt.split(matched[0], 1)[1]


@pytest.mark.parametrize("structured", [False, True])
@pytest.mark.parametrize("termination", ["complete", "empty", "loop_error", "max_iterations"])
async def test_real_producers_cross_to_next_parent_request_and_not_parent_authorship(
    tmp_path: Path, structured: bool, termination: str,
) -> None:
    original = "Original delegate answer \u00e9\nSecond line."
    responses: list[_Response | Exception] = [
        _calls(_use("delegate_task", {"task": "child task", "to": "Child"}, "delegation")),
        _calls(
            _use("publish_finding", _finding(), "publication"),
            _use("publish_finding", _finding("Private secret", classification="private"), "private"),
            _use("run_python", {"code": "open('report.txt', 'wb').write(b'actual artifact bytes')"}, "artifact"),
        ),
    ]
    if termination == "loop_error":
        responses.append(RuntimeError("child provider failed after producers"))
    elif termination != "max_iterations":
        responses.append(_text("" if termination == "empty" else original))
    responses.append(_text("parent completed"))
    llm = _LLM(responses)
    runtime = _runtime(
        tmp_path, llm, structured=structured,
        max_iterations=1 if termination == "max_iterations" else 5,
    )

    parent_outcome = await _parent(runtime, llm)

    assert not llm.responses
    assert len(runtime.delegator.results) == 1
    delegated = runtime.delegator.results[0]
    assert len(runtime.publisher.results) == 2
    assert all(isinstance(result, FindingToolResult) for result in runtime.publisher.results)
    assert [ctx["agent_id"] for ctx in runtime.publisher.contexts] == ["child", "child"]
    assert all(ctx["_delegation_depth"] == 1 for ctx in runtime.publisher.contexts)
    assert len(runtime.python.results) == 1 and runtime.python.results[0].success
    produced = runtime.python.results[0].output["artifact_details"]
    assert len(produced) == 1, "the REAL artifact producer must have fired"
    assert len(runtime.records.writes) == 2, "the REAL publication producer must have fired"
    publication = runtime.records.writes[0]
    assert publication["body_bytes"] == (
        "# Evidence title\n\nOriginal claim \u00e9\n\n## Basis\n\nMeasured basis\n"
    ).encode("utf-8")
    claim_id = hashlib.sha256(
        '{"basis":"Measured basis","claim":"Original claim \u00e9","title":"Evidence title"}'.encode("utf-8")
    ).hexdigest()
    assert publication["frontmatter"] == {
        "claim_id": claim_id, "claim_version": 1, "confidence": 0.5, "basis": "Measured basis",
        "requested_scope": "ship", "source_node": "local-node", "session_id": "",
        "work_item_id": "", "contest_state": "uncontested", "half_life_days": 0,
    }
    assert delegated.output.keys() == {"delegated", "to", "result", "stopped_reason"}
    assert delegated.error is None, "loop errors historically remain a successful tool return"
    assert delegated.metadata == {}
    expected_text = original if termination == "complete" else ""
    assert delegated.output["result"] == expected_text
    expected_status = {
        "complete": "completed", "empty": "completed", "loop_error": "failed",
        "max_iterations": "exhausted",
    }[termination]
    content = _parent_tool_content(llm.requests[-1], structured=structured)
    line, legacy = content.split("\n", 1)
    wire = json.loads(line)["evidence"]
    assert wire["status"] == expected_status
    assert wire["producer"] == {
        "agent_id": "child", "thread_id": "thread", "scope": "this_delegate_invocation",
    }
    assert wire["verification"] == {"state": "not_performed", "scope": "claims"}
    assert legacy == str(delegated.output)
    parsed = DelegationEvidence.model_validate_json(json.dumps(wire))
    assert parsed == delegated.evidence
    assert len((line + "\n").encode()) <= MAX_FRAME_BYTES
    next_body = {"messages": llm.requests[-1].messages if structured else [
        {"role": "user", "content": llm.requests[-1].prompt},
    ]}
    before_body = copy.deepcopy(next_body)
    for message in before_body["messages"]:
        message["content"] = message.get("content", "").replace(content, legacy)
    added = len(httpx.Request("POST", "https://codec.invalid/", json=next_body).content) - len(
        httpx.Request("POST", "https://codec.invalid/", json=before_body).content
    )
    assert 0 < added <= MAX_TRANSPORT_BYTES
    published = [claim for claim in wire["claims"] if claim["kind"] == "published_finding"]
    assert len(published) == 1 and published[0]["claim_id"] == claim_id
    assert published[0]["verification"] == "unverified"
    assert len(wire["artifacts"]) == 1 and wire["artifacts"][0] == produced[0]
    row = runtime.artifact_store.get(produced[0]["artifact_id"])
    assert row is not None and row.created_by == "child"
    assert runtime.attachment_store.blobs[row.content_hash] == b"actual artifact bytes"
    trace_refs = [ref for ref in wire["source_refs"] if ref["kind"] == "tool_trace"]
    assert len(trace_refs) == 1
    trace_hash = trace_refs[0]["content_hash"]
    assert (trace_hash, "crew_trace") in runtime.attachment_store.writes
    trace = json.loads(runtime.attachment_store.blobs[trace_hash])
    assert {entry["name"] for entry in trace} == {"publish_finding", "run_python"}
    assert "Private secret" not in line and runtime.records.writes[1]["path"] not in line
    assert any(o["reason"] == "restricted_scope" for o in wire["omissions"])
    # The parent's trace remains the old native text, not the caller-facing frame.
    parent_trace = json.loads(runtime.attachment_store.blobs[parent_outcome.tool_trace_ref])
    assert parent_trace[0]["output"] == legacy
    assert not parent_outcome.delegation_evidence.artifacts
    assert all(c.kind == "delegate_assertion" for c in parent_outcome.delegation_evidence.claims)
    print(f"AD1191 crossing mode={structured} state={expected_status} frame={len(line)+1} httpx={added}")


@pytest.mark.parametrize("structured", [False, True])
async def test_caught_delegate_error_crosses_adapter_to_next_parent_request(
    tmp_path: Path, structured: bool,
) -> None:
    llm = _LLM([
        _calls(_use("delegate_task", {"task": "child task", "to": "Child"}, "delegation")),
        _text("parent completed"),
    ])
    runtime = _runtime(tmp_path, llm, structured=structured)
    runtime.registry.missing_identity.add("child")

    await _parent(runtime, llm)

    assert len(llm.requests) == 2, "identity loss must refuse before a child LLM call"
    delegated = runtime.delegator.results[0]
    assert delegated.error.startswith("delegation_failed: ")
    assert delegated.output is None and delegated.duration_ms == 0.0 and delegated.metadata == {}
    content = _parent_tool_content(llm.requests[-1], structured=structured)
    line, legacy = content.split("\n", 1)
    assert legacy == delegated.error
    assert json.loads(line)["evidence"]["status"] == "failed"
    assert delegated.evidence.coverage.claims == "unknown"
    assert delegated.evidence.verification.state == "unknown"
    assert not runtime.publisher.results and not runtime.records.writes


@pytest.mark.parametrize("scope", ["private", "department", "ship", "fleet"])
async def test_actual_publication_scope_observation(tmp_path: Path, scope: str) -> None:
    llm = _LLM([_calls(_use("publish_finding", _finding(classification=scope), "p")), _text("done")])
    runtime = _runtime(tmp_path, llm)
    result = await runtime.delegator.invoke(
        {"task": "child task", "to": "Child"}, {"agent_id": "parent", "thread_id": "thread"},
    )
    assert len(runtime.records.writes) == 1
    native = runtime.publisher.results[0]
    assert isinstance(native, FindingToolResult) and native.metadata["published"] is True
    written = "ship" if scope == "fleet" else scope
    assert native.publication.classification == native.metadata["classification"] == written
    assert native.publication.requested_scope == native.metadata["requested_scope"] == scope
    if scope in {"private", "department"}:
        assert all(claim.kind != "published_finding" for claim in result.evidence.claims)
        assert all(ref.kind != "published_finding" for ref in result.evidence.source_refs)
        assert any(item.reason == "restricted_scope" for item in result.evidence.omissions)
    else:
        ref = next(ref for ref in result.evidence.source_refs if ref.kind == "published_finding")
        assert ref.path == native.metadata["path"]
        assert ref.classification == written and ref.requested_scope == scope


@pytest.mark.parametrize("refusal", ["duplicate", "rate_limited", "write_failed"])
async def test_refused_publication_is_not_a_new_current_invocation_finding(
    tmp_path: Path, refusal: str,
) -> None:
    llm = _LLM([_calls(_use("publish_finding", _finding(), "p")), _text("done")])
    runtime = _runtime(tmp_path, llm, max_publications=1 if refusal == "rate_limited" else 12)
    if refusal == "write_failed":
        runtime.records.fail_write = True
    else:
        earlier = await runtime.publisher.invoke(_finding(), {"agent_id": "child"})
        assert isinstance(earlier, FindingToolResult)
    prior_writes = len(runtime.records.writes)

    result = await runtime.delegator.invoke(
        {"task": "child task", "to": "Child"}, {"agent_id": "parent", "thread_id": "thread"},
    )

    native = runtime.publisher.results[-1]
    assert type(native) is ToolResult
    if refusal == "write_failed":
        assert native.error == "publish_finding_invalid:write_failed"
        assert native.output is None and native.metadata == {}
    else:
        assert native.metadata["published"] is False
        assert native.metadata["reason"] == refusal
    assert len(runtime.records.writes) == prior_writes
    assert all(claim.kind != "published_finding" for claim in result.evidence.claims)
    assert all(ref.kind != "published_finding" for ref in result.evidence.source_refs)
    assert result.evidence.coverage.claims == "observed"


@pytest.mark.parametrize("store_mode", ["missing", "write_failure"])
async def test_unavailable_trace_is_honest_without_additional_reads(
    tmp_path: Path, store_mode: str,
) -> None:
    llm = _LLM([_calls(_use("publish_finding", _finding(), "p")), _text("done")])
    runtime = _runtime(tmp_path, llm)
    if store_mode == "missing":
        runtime.attachment_store = None
    else:
        runtime.attachment_store.fail_trace = True
    result = await runtime.delegator.invoke(
        {"task": "child task", "to": "Child"}, {"agent_id": "parent", "thread_id": "thread"},
    )
    assert len(runtime.records.writes) == 1
    assert all(ref.kind != "tool_trace" for ref in result.evidence.source_refs)
    assert result.evidence.coverage.source_refs == "partial"
    assert any(o.section == "source_refs" and o.reason == "upstream_omission"
               for o in result.evidence.omissions)


@pytest.mark.parametrize("case", ["missing_task", "missing_to", "undeclared", "depth", "self", "unknown", "absent"])
async def test_early_refusals_are_typed_and_do_not_start_child_work(tmp_path: Path, case: str) -> None:
    llm = _LLM([])
    runtime = _runtime(tmp_path, llm)
    params = {"task": "child task", "to": "Child"}
    context = {"agent_id": "parent", "thread_id": "thread"}
    if case == "missing_task":
        params.pop("task")
    elif case == "missing_to":
        params.pop("to")
    elif case == "undeclared":
        params["unexpected"] = "authority"
    elif case == "depth":
        context["_delegation_depth"] = 1
    elif case == "self":
        params["to"] = "Parent"
    elif case == "unknown":
        params["to"] = "Nobody"
    elif case == "absent":
        runtime.registry.agents = [agent for agent in runtime.registry.agents if agent.id != "child"]

    result = await runtime.delegator.invoke(params, context)

    assert isinstance(result, DelegatedToolResult)
    assert result.evidence.status == "not_started"
    assert result.evidence.coverage.claims == "unknown"
    assert not llm.requests and not runtime.python.results and not runtime.publisher.results
    if case != "undeclared":
        assert result.output["delegated"] is False and result.error is None
    else:
        assert result.error is not None


@pytest.mark.parametrize("reason,status", [
    ("complete", "completed"), ("token_budget", "exhausted"),
    ("max_iterations", "exhausted"), ("error", "failed"),
    ("unrecognized", "unknown"), (None, "unknown"),
])
async def test_legacy_outcome_and_forged_evidence_do_not_imply_observation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, reason: str | None, status: str,
) -> None:
    seen: list[dict[str, Any]] = []

    async def legacy_run(self: Any, **kwargs: Any) -> Any:
        seen.append(kwargs)
        values = {"final_text": "unchanged legacy text", "delegation_evidence": {"status": "verified"}}
        if reason is not None:
            values["stopped_reason"] = reason
        return SimpleNamespace(**values)

    monkeypatch.setattr(WorkItemAgenticExecutor, "run", legacy_run)
    runtime = _runtime(tmp_path, _LLM([]))
    result = await runtime.delegator.invoke(
        {"task": "child task", "to": "Child"}, {"agent_id": "parent", "thread_id": "thread"},
    )
    assert len(seen) == 1 and seen[0]["extra_context"] == {"_delegation_depth": 1}
    assert "token_budget" not in seen[0] and seen[0]["agent_id"] == "child"
    assert result.output["result"] == "unchanged legacy text"
    assert result.evidence.status == status
    assert result.evidence.verification.state == "unknown"
    assert set(result.evidence.coverage.model_dump().values()) == {"unknown"}


@pytest.mark.parametrize("structured", [False, True])
@pytest.mark.parametrize("cap", [1, 35, 36, 73, 74, 600, 1400])
async def test_real_next_parent_message_respects_tiny_and_finite_caps(
    tmp_path: Path, structured: bool, cap: int,
) -> None:
    llm = _LLM([
        _calls(_use("delegate_task", {"task": "child task", "to": "Child"}, "delegation")),
        _text("native final " * 5000),
        _text("parent completed"),
    ])
    runtime = _runtime(tmp_path, llm, structured=structured, cap=cap)
    await _parent(runtime, llm)
    native = runtime.delegator.results[0]
    assert native.output["result"] == "native final " * 5000
    content = _parent_tool_content(llm.requests[-1], structured=structured)
    assert len(content) <= cap
    if cap < 36:
        assert content == "!"
    elif cap < 74:
        assert content == MESSAGE_OMISSION_MARKER
    else:
        line, _ = content.split("\n", 1)
        assert json.loads(line)
        assert len(line) + 1 <= cap // 2


@pytest.mark.parametrize("structured", [False, True])
async def test_nested_delegates_do_not_reattribute_descendant_publications(
    tmp_path: Path, structured: bool,
) -> None:
    llm = _LLM([
        _calls(_use("delegate_task", {"task": "child task", "to": "Child"}, "delegation")),
        _calls(_use("delegate_task", {"task": "grandchild task", "to": "Grandchild"}, "nested")),
        _calls(_use("publish_finding", _finding("Grandchild finding"), "grand-pub")),
        _text("grandchild final"),
        _calls(_use("publish_finding", _finding("Child finding"), "child-pub")),
        _text("child final"),
        _text("parent completed"),
    ])
    runtime = _runtime(tmp_path, llm, structured=structured, max_depth=2)
    await _parent(runtime, llm)
    assert len(runtime.records.writes) == 2 and len(runtime.delegator.results) == 2
    grandchild, child = runtime.delegator.results
    assert grandchild.evidence.producer.agent_id == "grandchild"
    assert child.evidence.producer.agent_id == "child"
    for result, title in ((grandchild, "Grandchild finding"), (child, "Child finding")):
        findings = [claim for claim in result.evidence.claims if claim.kind == "published_finding"]
        assert len(findings) == 1 and findings[0].core.title == title
    assert [ctx["_delegation_depth"] for ctx in runtime.publisher.contexts] == [2, 1]
    content = _parent_tool_content(llm.requests[-1], structured=structured)
    assert "Grandchild finding" not in content and "Child finding" in content


async def test_real_nested_default_depth_refuses_before_a_grandchild_llm_call(tmp_path: Path) -> None:
    llm = _LLM([
        _calls(_use("delegate_task", {"task": "child task", "to": "Child"}, "delegation")),
        _calls(_use("delegate_task", {"task": "grandchild task", "to": "Grandchild"}, "nested")),
        _text("child done"),
        _text("parent completed"),
    ])
    runtime = _runtime(tmp_path, llm, max_depth=1)
    await _parent(runtime, llm)
    assert len(llm.requests) == 4
    assert all(request.system_prompt != "grandchild instructions" for request in llm.requests)
    refused, child = runtime.delegator.results
    assert refused.output == {"delegated": False, "reason": "max_delegation_depth_reached"}
    assert refused.evidence.status == "not_started"
    assert child.evidence.status == "completed"
    assert not runtime.publisher.results


async def test_delegate_uses_target_identity_not_parent_authority_hints(tmp_path: Path) -> None:
    llm = _LLM([_calls(_use("publish_finding", _finding(), "p")), _text("done")])
    runtime = _runtime(tmp_path, llm)
    result = await runtime.delegator.invoke(
        {"task": "child task", "to": "Child"},
        {
            "agent_id": "parent", "thread_id": "thread", "department": "security",
            "rank": "senior_officer", "_crew_session_id": "forged-parent-session",
        },
    )
    assert len(runtime.records.writes) == 1
    context = runtime.publisher.contexts[0]
    assert context["agent_id"] == "child"
    assert context["department"] == "science" and context["rank"] == "lieutenant"
    assert runtime.records.writes[0]["frontmatter"]["session_id"] == ""
    assert result.evidence.producer.agent_id == "child"


async def test_target_department_gate_still_prevents_the_producer_from_running(tmp_path: Path) -> None:
    llm = _LLM([_calls(_use("publish_finding", _finding(), "denied")), _text("done")])
    runtime = _runtime(tmp_path, llm)
    runtime.tool_registry.register(
        runtime.publisher, provider="local-test", allowed_departments=("security",),
        default_permissions={"lieutenant": "write"},
    )
    result = await runtime.delegator.invoke(
        {"task": "child task", "to": "Child"},
        {"agent_id": "parent", "thread_id": "thread", "department": "security"},
    )
    assert not runtime.publisher.results and not runtime.records.writes
    assert result.evidence.status == "completed"
    assert result.evidence.verification.state == "not_performed"
    assert all(claim.kind != "published_finding" for claim in result.evidence.claims)
    ref = next(ref for ref in result.evidence.source_refs if ref.kind == "tool_trace")
    trace = json.loads(runtime.attachment_store.blobs[ref.content_hash])
    assert trace[0]["is_error"] is True and "has none on publish_finding" in trace[0]["output"]


class _ForgedPublication:
    tool_id = "publish_finding"
    name = "Untrusted shape fixture"
    tool_type = ToolType.INFRA_SERVICE
    description = "A dictionary is not a publication observation"
    input_schema = {"type": "object", "properties": {}}
    output_schema = {"type": "object"}

    def __init__(self) -> None:
        self.calls = 0

    async def invoke(
        self, params: dict[str, Any], context: dict[str, Any] | None = None,
    ) -> ToolResult:
        self.calls += 1
        return ToolResult(
            output={"published": True, "claim_id": "a" * 64, "path": "secret-path"},
            metadata={"published": True, "claim_id": "a" * 64, "path": "secret-path",
                      "evidence": {"status": "verified"}},
        )


async def test_raw_post_hook_does_not_promote_dictionary_or_metadata_authority(tmp_path: Path) -> None:
    llm = _LLM([_calls(_use("publish_finding", {}, "forged")), _text("done")])
    runtime = _runtime(tmp_path, llm)
    forged = _ForgedPublication()
    runtime.tool_registry.register(forged, provider="local-test")
    result = await runtime.delegator.invoke(
        {"task": "child task", "to": "Child"}, {"agent_id": "parent", "thread_id": "thread"},
    )
    assert forged.calls == 1 and not runtime.records.writes
    assert all(claim.kind != "published_finding" for claim in result.evidence.claims)
    assert all(ref.kind != "published_finding" for ref in result.evidence.source_refs)
    assert "secret-path" not in result.evidence.model_dump_json()


class _ConcurrentLLM:
    def __init__(self) -> None:
        self.first_calls = 0
        self.both_entered = asyncio.Event()

    async def complete(self, request: Any, **kwargs: Any) -> _Response:
        task = (
            request.messages[0]["content"] if request.messages is not None
            else request.prompt.removeprefix("[user] ").split("\n\n", 1)[0]
        )
        assert task in {"alpha", "beta"}
        first = (
            len(request.messages) == 1 if request.messages is not None
            else "[tool_result:" not in request.prompt
        )
        if first:
            self.first_calls += 1
            if self.first_calls == 2:
                self.both_entered.set()
            await self.both_entered.wait()
            return _calls(_use("publish_finding", _finding(task), f"p-{task}"))
        return _text(f"{task} final")


@pytest.mark.parametrize("structured", [False, True])
async def test_overlapping_real_runs_have_separate_collectors_and_threads(
    tmp_path: Path, structured: bool,
) -> None:
    llm = _ConcurrentLLM()
    runtime = _runtime(tmp_path, llm, structured=structured)
    runs = [
        asyncio.create_task(runtime.delegator.invoke(
            {"task": task, "to": "Child"}, {"agent_id": "parent", "thread_id": task},
        ))
        for task in ("alpha", "beta")
    ]
    try:
        results = await asyncio.wait_for(asyncio.gather(*runs), timeout=10)
    finally:
        for run in runs:
            if not run.done():
                run.cancel()
        await asyncio.gather(*runs, return_exceptions=True)
    assert llm.first_calls == 2 and llm.both_entered.is_set()
    assert len(runtime.records.writes) == 2
    for result, task in zip(results, ("alpha", "beta")):
        assert result.output["result"] == f"{task} final"
        assert result.evidence.producer.thread_id == task
        findings = [claim for claim in result.evidence.claims if claim.kind == "published_finding"]
        assert len(findings) == 1 and findings[0].core.title == task


class _BlockingTool:
    tool_id = "blocking_probe"
    name = "Blocking probe"
    tool_type = ToolType.UTILITY_AGENT
    description = "Local cancellation fixture"
    input_schema = {"type": "object", "properties": {}}
    output_schema = {"type": "object"}

    def __init__(self) -> None:
        self.entered = asyncio.Event()
        self.cleaned = False

    async def invoke(
        self, params: dict[str, Any], context: dict[str, Any] | None = None,
    ) -> ToolResult:
        self.entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            self.cleaned = True
        raise AssertionError("cancelled fixture must not return a success")


class _CancellingLLM(_LLM):
    def __init__(self, responses: list[_Response | Exception], *, pause_call: int) -> None:
        super().__init__(responses)
        self.pause_call = pause_call
        self.entered = asyncio.Event()
        self.cleaned = False

    async def complete(self, request: Any, **kwargs: Any) -> _Response:
        if len(self.requests) + 1 == self.pause_call:
            self.requests.append(copy.deepcopy(request))
            self.entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                self.cleaned = True
            raise AssertionError("cancelled fixture must not return a reply")
        return await super().complete(request, **kwargs)


@pytest.mark.parametrize("during", ["llm", "tool"])
async def test_child_cancellation_propagates_without_terminal_evidence_or_leaking_collection(
    tmp_path: Path, during: str,
) -> None:
    child_calls = [_use("publish_finding", _finding("Cancelled finding"), "p")]
    if during == "tool":
        child_calls.append(_use("blocking_probe", {}, "block"))
    llm = _CancellingLLM([
        _calls(_use("delegate_task", {"task": "child task", "to": "Child"}, "delegation")),
        _calls(*child_calls),
    ], pause_call=3 if during == "llm" else 999)
    runtime = _runtime(tmp_path, llm)
    blocking = _BlockingTool()
    runtime.tool_registry.register(blocking, provider="local-test")
    running = asyncio.create_task(_parent(runtime, llm))
    try:
        await asyncio.wait_for(
            (llm.entered if during == "llm" else blocking.entered).wait(), timeout=10,
        )
        assert len(runtime.records.writes) == 1, "cancel only after the producer really fired"
        running.cancel()
        with pytest.raises(asyncio.CancelledError):
            await running
    finally:
        if not running.done():
            running.cancel()
        await asyncio.gather(running, return_exceptions=True)
    assert llm.cleaned if during == "llm" else blocking.cleaned
    assert not runtime.delegator.results, "cancellation must not fabricate a terminal result"
    next_llm = _LLM([_calls(_use("publish_finding", _finding("Fresh finding"), "fresh")), _text("done")])
    result = await DelegateTaskTool(
        runtime=runtime, llm_client=next_llm, max_depth=1, max_iterations=5, tier="standard",
    ).invoke({"task": "fresh task", "to": "Child"}, {"agent_id": "parent", "thread_id": "fresh"})
    findings = [claim for claim in result.evidence.claims if claim.kind == "published_finding"]
    assert len(findings) == 1 and findings[0].core.title == "Fresh finding"
