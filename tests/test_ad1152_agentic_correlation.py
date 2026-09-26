"""AD-1152 run-local correlation, including a pre-edit pinned-base OFF oracle."""

from __future__ import annotations

import asyncio
import gc
import hashlib
import itertools
import json
import sqlite3
import sys
import time
import uuid
from contextlib import closing
from dataclasses import FrozenInstanceError, asdict, fields, is_dataclass
from pathlib import Path, PurePath, PurePosixPath, PureWindowsPath
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from pydantic import ValidationError

from probos.cognitive.agentic_dispatch import WorkItemAgenticExecutor
from probos.cognitive.crew_executor import CrewTaskExecutor
from probos.cognitive.crew_session import (
    CrewSessionService,
    _canonical_plan_json_bytes,
    _final_plan_hash,
    _row_semantic_projection,
)
from probos.cognitive.swe_harness.agentic_loop import (
    AgenticLoop,
    resolve_event_correlation_settings,
)
from probos.cognitive.swe_harness.native_builder import NativeBuilderHarness
from probos.cognitive.swe_harness.tool_call import TextBlock, ToolCallRequest, ToolUseBlock
from probos.config import SystemConfig
from probos.crew_utils import CREW_EXECUTION_KEYS
from probos.events import EventType
from probos.runtime import ProbOSRuntime
from probos.tools.protocol import ToolResult
from probos.types import LLMRequest, LLMResponse
from probos.workforce import WorkItemStore
from tests import test_ad1125_room_bound_execution as room
from tests.test_ad1258_self_knowledge import _OfferSysProxy


BASE_COMMIT = "7dd9542289fbe3b574b09f4e9b5fe934c35f424c"
GOLDEN_PATH = Path(__file__).parent / "fixtures" / "ad1152_agentic_off_golden.json"
LOOP_EVENTS = (
    EventType.AGENTIC_LOOP_ITERATION.value,
    EventType.AGENTIC_TOOL_CALL_STARTED.value,
    EventType.AGENTIC_TOOL_CALL_COMPLETED.value,
)


def _json_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=True, separators=(",", ":")).encode("ascii")


def _captured_path_representation(typed: Any, encoded: Any) -> Any:
    # Keep the pre-edit Windows oracle immutable when these tests run on Linux.
    if isinstance(typed, PurePath):
        return str(PureWindowsPath(typed))
    if isinstance(typed, dict):
        return {
            key: _captured_path_representation(value, encoded[key])
            for key, value in typed.items()
        }
    if isinstance(typed, (list, tuple)):
        return [
            _captured_path_representation(value, raw)
            for value, raw in zip(typed, encoded, strict=True)
        ]
    return encoded


def _snapshot(value: Any) -> Any:
    if value is None or type(value) in (bool, int, float, str):
        return value
    if isinstance(value, dict):
        return {str(key): _snapshot(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_snapshot(item) for item in value]
    if is_dataclass(value) and not isinstance(value, type):
        return {item.name: _snapshot(getattr(value, item.name)) for item in fields(value)}
    if callable(value) and hasattr(value, "__qualname__"):
        return {"callable": value.__qualname__}
    return {"type": f"{type(value).__module__}.{type(value).__qualname__}"}


def _local_runtime() -> ProbOSRuntime:
    # Exercise the real public emitter/listener without booting any services.
    runtime = ProbOSRuntime.__new__(ProbOSRuntime)
    runtime._event_listeners = []
    runtime._live_event_listeners = []
    runtime._event_listener_tasks = set()
    runtime._nats_events_wired = False
    runtime.nats_bus = None
    return runtime


def _tool_turn(*labels: str, tokens: int = 7) -> LLMResponse:
    return LLMResponse(
        content="Reading.",
        content_blocks=[
            TextBlock(text="Reading."),
            *[
                ToolUseBlock(tool_call=ToolCallRequest(
                    name="read_page", arguments={"label": label}, id=" provider/duplicate ",
                    timestamp=1_700_000_000.0,
                ))
                for label in labels
            ],
        ],
        tokens_used=tokens,
    )


class _ScriptedClient:
    def __init__(self, responses: list[LLMResponse]) -> None:
        self.responses = list(responses)
        self.requests: list[dict[str, Any]] = []

    async def complete(self, request: LLMRequest, **kwargs: Any) -> LLMResponse:
        self.requests.append({"request": asdict(request), "kwargs": _snapshot(kwargs)})
        assert self.responses, "The scripted completion premise was exhausted"
        return self.responses.pop(0)


class _ToolRecorder:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.hooks: list[Any] = []

    def add_pre_hook(self, hook: Any) -> None:
        self.hooks.append(hook)

    async def invoke(self, **kwargs: Any) -> ToolResult:
        self.calls.append(_snapshot(kwargs))
        return ToolResult(output=f"result:{kwargs['params']['label']}")


class _LocalOntology:
    def get_agent_department(self, agent_type: str) -> str:
        return "engineering"


class _LocalTrust:
    def get_score(self, agent_id: str) -> float:
        return 0.5


def _record_constructor(
    monkeypatch: pytest.MonkeyPatch, cls: type[Any], calls: list[dict[str, Any]],
) -> None:
    original = cls.__init__

    def record(self: Any, **kwargs: Any) -> None:
        calls.append({"constructor": cls.__name__, "kwargs": _snapshot(kwargs)})
        original(self, **kwargs)

    monkeypatch.setattr(cls, "__init__", record)


async def _get_existing_endpoint(store: WorkItemStore, child_id: str) -> dict[str, Any]:
    from probos.routers.deps import get_runtime
    from probos.routers.workforce import router

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_runtime] = lambda: SimpleNamespace(work_item_store=store)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://local.test",
    ) as client:
        response = await client.get(f"/api/work-items/{child_id}")
    assert response.status_code == 200, response.text
    return response.json()


async def _off_observation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> dict[str, Any]:
    from probos.artifacts import ArtifactStore
    from probos.attachments.filesystem_store import FilesystemAttachmentStore
    from probos.cognitive import crew_executor as crew_executor_module
    from probos.cognitive.builder import BuildSpec
    from probos.routers import chat as chat_router
    from probos.startup.finalize import _wire_crew_orchestrator, _wire_native_swe_harness
    from probos.threads import ChatThreadStore
    from probos.tools import code_execution_tool

    # Reproduce the Windows capture at the descriptor input, not in observed output.
    monkeypatch.setattr(code_execution_tool, "sys", _OfferSysProxy("win32"))
    sequence = itertools.count(1)
    monkeypatch.setenv("PROBOS_DATA_DIR", str(tmp_path / "local-data"))
    monkeypatch.setenv("PROBOS_NATS_ENABLED", "false")
    monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    monkeypatch.setattr(uuid, "uuid4", lambda: uuid.UUID(int=next(sequence) << 96))
    monkeypatch.setattr(time, "time", lambda: 1_700_000_000.0)
    monkeypatch.setattr(time, "perf_counter", lambda: 100.0)
    monkeypatch.setattr(room, "_CREW_PARENT_IDS", itertools.count(1))
    calls: list[dict[str, Any]] = []
    for cls in (AgenticLoop, NativeBuilderHarness, CrewTaskExecutor):
        _record_constructor(monkeypatch, cls, calls)

    default_config = SystemConfig()
    config = _captured_path_representation(
        default_config.model_dump(mode="python"), default_config.model_dump(mode="json"),
    )
    loop_config = config["agentic_loop"]
    if "event_correlation_enabled" in loop_config:
        assert loop_config.pop("event_correlation_enabled") is False
    # AD-1206's inert, empty issue destination was added after this historical capture.
    assert config["repair"].pop("github_repository") == ""
    # AD-1190's four inert (None) delegation-tree ceilings were added after this capture too.
    for name in (
        "delegation_tree_max_tokens", "delegation_tree_max_iterations",
        "delegation_tree_max_concurrent", "delegation_tree_max_children",
    ):
        assert config["agentic_tools"].pop(name) is None
    # AD-1189's inert 0 threshold was added after this capture too.
    assert config["agentic_tools"].pop("deferred_tool_schema_threshold_bytes") == 0
    # AD-1246's inert long-run reach (0 = off) and its slot limit were added after this capture too.
    assert config["execution"].pop("max_runtime_seconds") == 0.0
    assert config["execution"].pop("max_concurrent_long_runs") == 2
    # AD-1208's inert conversational cost budget (None = off) and its step backstop were added after this capture too.
    assert config["dm_agentic"].pop("token_budget") is None
    assert config["dm_agentic"].pop("max_total_iterations") == 100
    # AD-1213's four inert approval_inbox fields were added after this capture too.
    assert config["approval_inbox"].pop("delegated_approvals_enabled") is False
    assert config["approval_inbox"].pop("approval_grace_seconds") == 300
    assert config["approval_inbox"].pop("first_officer_delegation_max_ttl_hours") == 168
    assert config["approval_inbox"].pop("captain_unavailable_max_ttl_hours") == 72
    # AD-1214's three inert approval_inbox fields were added after this capture too.
    assert config["approval_inbox"].pop("decision_pre_clearance_enabled") is False
    assert config["approval_inbox"].pop("decision_pre_clearance_default_ttl_hours") == 24
    assert config["approval_inbox"].pop("decision_pre_clearance_max_ttl_hours") == 168
    runtime = _local_runtime()
    events: list[dict[str, Any]] = []
    runtime.add_event_listener(lambda event: events.append(_snapshot(event)), LOOP_EVENTS)
    unrelated: list[dict[str, Any]] = []
    runtime.add_event_listener(unrelated.append, ["not_a_loop_event"])
    direct: list[dict[str, Any]] = []
    for parallel, inherited in ((False, False), (True, True)):
        client = _ScriptedClient([
            _tool_turn("first", "second"),
            LLMResponse(content="Complete.", tokens_used=11),
        ])
        tools = _ToolRecorder()
        context: dict[str, Any] = {"agent_id": "golden-agent"}
        if inherited:
            context["_agentic_run_id"] = "f" * 32
        callbacks: list[str] = []
        loop = AgenticLoop(
            llm_client=client, tool_executor=tools, event_emit_fn=runtime.emit_event,
            parallel_tool_calls_enabled=parallel, structured_tool_messages=parallel,
        )
        result = await loop.run(
            system_prompt="sys", user_message="task", tools=[], context=context,
            on_run_started=callbacks.append,
        )
        assert result.stopped_reason == "complete" and result.total_tokens == 18
        assert len(tools.calls) == 2 and len(client.requests) == 2
        assert callbacks == [tools.calls[0]["context"]["_agentic_run_id"]]
        assert context == (
            {"agent_id": "golden-agent", "_agentic_run_id": "f" * 32}
            if inherited else {"agent_id": "golden-agent"}
        )
        direct.append({
            "requests": client.requests, "result": asdict(result),
            "tool_calls": tools.calls, "callbacks": callbacks, "incoming": context,
        })
    assert len(events) == 12 and not unrelated
    assert {event["type"] for event in events} == set(LOOP_EVENTS)
    assert all("run_id" not in event["data"] for event in events)

    work = WorkItemStore(db_path=str(tmp_path / "workforce.db"), tick_interval=1_000)
    await work.start()
    stores = room._Stores(
        work=work, chat=ChatThreadStore(tmp_path / "threads.db", clock=room._Clock()),
        artifacts=ArtifactStore(
            tmp_path / "artifacts.db", clock=room._Clock(5_000.0),
            id_factory=room._IdFactory(),
        ),
        attachments=room._ObservingAttachmentStore(tmp_path / "attachments"),
        events=room._EventRecorder(), admission_port=work.claim_crew_session_admission_port(),
    )
    try:
        parent, thread, service = await room._session_parent(stores)
        # The old global stream also started numbering new owned protocol
        # identities. Isolate those three draws, not the observed request IDs.
        owned_id_sequence = itertools.count(1)
        owned_ids: list[uuid.UUID] = []

        def owned_uuid() -> uuid.UUID:
            value = uuid.UUID(int=(0xF0000000 + next(owned_id_sequence)) << 96)
            owned_ids.append(value)
            return value

        adopt = service.adopt_recovery_plan

        async def adopt_with_owned_ids(*args: Any, **kwargs: Any) -> Any:
            with pytest.MonkeyPatch.context() as identities:
                identities.setattr(uuid, "uuid4", owned_uuid)
                result = await adopt(*args, **kwargs)
            assert len(owned_ids) == 2
            return result

        monkeypatch.setattr(service, "adopt_recovery_plan", adopt_with_owned_ids)
        monkeypatch.setattr(crew_executor_module, "uuid", SimpleNamespace(uuid4=owned_uuid))
        child = await work.create_work_item(
            id="golden-child", title="Child golden-child",
            description="Read input.txt and write report.txt", work_type="task",
            parent_id=parent.id, assigned_to="agent-1", depends_on=[],
            metadata={"spec_id": "golden-child"}, created_at=100.0, updated_at=100.0,
        )
        crew_runtime = room._runtime(stores, tmp_path)
        crew_runtime.emit_event = runtime.emit_event
        crew_runtime.crew_session_service = service
        client = _ScriptedClient([LLMResponse(content="Durable result.", tokens_used=20)])
        registry = room._Registry({"agent-1": room._Agent("agent-1")})
        crew_runtime.registry = registry
        crew_runtime.ontology = _LocalOntology()
        crew_runtime.trust_network = _LocalTrust()
        crew_runtime.callsign_registry = room._NoCallsigns()
        crew = CrewTaskExecutor(
            work_item_store=work, agent_registry=registry,
            agentic_executor=WorkItemAgenticExecutor(llm_client=client),
            runtime=crew_runtime, crew_session_service=service,
        )
        results = await crew.run(parent.id)
        assert len(set(owned_ids)) == len(owned_ids) == 3
        owned = await work.get_owned_steps(parent.id)
        assert owned.control.incarnation == owned_ids[0].hex
        assert owned.control.rows[0].step_id == owned_ids[1].hex
        permit = await work.get_owned_step_evidence(
            parent.id, owned.control.incarnation, "permit", owned.control.rows[0].permit,
        )
        assert permit.execution_nonce == owned_ids[2].hex
        stored = await work.get_work_item(child.id)
        assert stored is not None and stored.status == "done"
        evidence = stored.metadata["crew_execution"]
        assert set(evidence) == CREW_EXECUTION_KEYS and len(evidence) == 14
        assert "crew_execution_token_usage" not in stored.metadata
        assert evidence["tokens_used"] == stored.actual_tokens == 20
        assert len(client.requests) == 1 and len(results) == 1
        projection = _row_semantic_projection(
            stored, child_to_spec={stored.id: "golden-child"}, require_new_metadata=False,
        )
        plan_bytes = _canonical_plan_json_bytes([projection], maximum_bytes=1_048_576)
        plan_seed = hashlib.sha256(plan_bytes).hexdigest()
        plan_hash = _final_plan_hash(
            parent.id, plan_seed,
            [{"spec_id": "golden-child", "work_item_id": child.id}], policy="derived_v1",
        )
        output_ref = stored.metadata["crew_execution_output"]
        output = await stores.attachments.read(output_ref["content_hash"])
        assert hashlib.sha256(output).hexdigest() == output_ref["content_hash"]
        with closing(sqlite3.connect(tmp_path / "workforce.db")) as db:
            raw_metadata = db.execute(
                "SELECT metadata FROM work_items WHERE id = ?", (child.id,),
            ).fetchone()[0]
        assert json.loads(raw_metadata) == stored.metadata

        crew_runtime.work_item_store = work
        crew_runtime.capability_registry = SimpleNamespace()
        crew_runtime.llm_client = _ScriptedClient([
            LLMResponse(content="No file changes.", tokens_used=3),
        ])
        native_tools = _ToolRecorder()
        assert _wire_native_swe_harness(
            runtime=crew_runtime, config=crew_runtime.config, tool_executor=native_tools,
        )
        build_result = await crew_runtime.native_builder_harness.run_build(
            BuildSpec(title="Golden", description="Report.", target_files=[]),
            work_dir="<work>",
        )
        # Startup gets its own store/owner lifetime, not a second reader on
        # the executor's live assembly. Keep the original constructor types.
        await work.stop()
        work = WorkItemStore(db_path=str(tmp_path / "workforce.db"), tick_interval=1_000)
        await work.start()
        crew_runtime.work_item_store = work
        crew_runtime.crew_session_service = CrewSessionService(
            work_item_store=work, chat_thread_store=stores.chat,
        )
        startup_content = FilesystemAttachmentStore(tmp_path / "attachments")

        def startup_reader(target: Any) -> FilesystemAttachmentStore:
            assert target is crew_runtime
            return startup_content

        monkeypatch.setattr(chat_router, "_get_attachment_store", startup_reader)
        assert _wire_crew_orchestrator(runtime=crew_runtime, config=crew_runtime.config)
        await crew_runtime.crew_orchestrator.stop()
        persisted = {
            "requests": client.requests, "results": [asdict(result) for result in results],
            "raw_metadata": raw_metadata,
            "metadata_sha256": hashlib.sha256(raw_metadata.encode("utf-8")).hexdigest(),
            "output_hex": output.hex(), "output_sha256": output_ref["content_hash"],
            "plan_bytes": plan_bytes.decode("utf-8"),
            "plan_seed_hash": plan_seed, "plan_hash": plan_hash,
            "native_requests": crew_runtime.llm_client.requests,
            "native_result": build_result,
        }
    finally:
        await work.stop()
        gc.collect()
    reopened = WorkItemStore(db_path=str(tmp_path / "workforce.db"), tick_interval=1_000)
    await reopened.start()
    try:
        endpoint = await _get_existing_endpoint(reopened, "golden-child")
        assert endpoint["work_item"]["metadata"] == json.loads(persisted["raw_metadata"])
        persisted["endpoint"] = endpoint
    finally:
        await reopened.stop()
        gc.collect()
    assert [call["constructor"] for call in calls].count("AgenticLoop") == 4
    assert [call["constructor"] for call in calls].count("CrewTaskExecutor") == 2
    assert [call["constructor"] for call in calls].count("NativeBuilderHarness") == 1
    assert all("event_correlation_enabled" not in call["kwargs"] for call in calls)
    return {
        "default_config_sha256": hashlib.sha256(_json_bytes(config)).hexdigest(),
        "direct": direct, "events": events, "constructors": calls, "persisted": persisted,
    }


@pytest.mark.asyncio
async def test_default_off_matches_pinned_base(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    golden = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))
    assert golden["base_commit"] == BASE_COMMIT
    assert golden["production_pristine"] is True
    actual = await _off_observation(tmp_path, monkeypatch)
    for key, expected in golden["observation"].items():
        assert actual[key] == expected, key
    assert _json_bytes(actual) == _json_bytes(golden["observation"])
    assert hashlib.sha256(_json_bytes(actual)).hexdigest() == golden["observation_sha256"]


@pytest.mark.asyncio
@pytest.mark.parametrize("ambient_platform", ["linux", "win32"])
async def test_default_off_golden_pins_only_descriptor_owner_platform(
    tmp_path: Path, ambient_platform: str,
) -> None:
    from probos.tools import code_execution_tool

    process_platform = sys.platform
    original_owner = code_execution_tool.sys
    assert original_owner is sys
    golden = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))
    captured_tool = golden["observation"]["persisted"]["requests"][0]["request"]["tools"][0]
    assert captured_tool["function"]["name"] == "run_python"
    captured_description = captured_tool["function"]["description"]
    assert ", 512 MB memory" not in captured_description
    tool = code_execution_tool.CodeExecutionTool(
        runtime=SimpleNamespace(config=SystemConfig()),
    )

    with pytest.MonkeyPatch.context() as ambient:
        owner_view = _OfferSysProxy(ambient_platform)
        ambient.setattr(code_execution_tool, "sys", owner_view)
        assert code_execution_tool.sys.platform == ambient_platform
        assert sys.platform == process_platform
        unpinned_description = tool.description
        if ambient_platform == "linux":
            prefix, separator, suffix = captured_description.partition(". Work that will not fit ")
            assert separator, "The captured limit clause must discriminate the POSIX control"
            assert unpinned_description == prefix + ", 512 MB memory" + separator + suffix
            assert unpinned_description != captured_description
        else:
            assert unpinned_description == captured_description

        with pytest.MonkeyPatch.context() as captured:
            actual = await _off_observation(tmp_path, captured)
            captured_platform = code_execution_tool.sys.platform
            assert code_execution_tool.sys is not sys
            assert all(
                getattr(code_execution_tool.sys, name) is getattr(sys, name)
                for name in ("executable", "version_info", "modules", "path")
            )
            with pytest.raises(FrozenInstanceError):
                code_execution_tool.sys.platform = "not-a-platform"
            assert sys.platform == process_platform
        assert code_execution_tool.sys is owner_view
        assert tool.description == unpinned_description
        assert sys.platform == process_platform
    assert code_execution_tool.sys is original_owner
    assert sys.platform == process_platform

    assert _json_bytes(actual) == _json_bytes(golden["observation"])
    assert hashlib.sha256(_json_bytes(actual)).hexdigest() == golden["observation_sha256"]
    assert captured_platform == "win32"


@pytest.mark.parametrize("path_type", [PurePosixPath, PureWindowsPath])
def test_golden_path_normalization_preserves_untyped_values(path_type: type[PurePath]) -> None:
    typed = {"nested": [path_type("data/plan_of_day"), "data/plan_of_day", None, False]}
    encoded = {"nested": [str(typed["nested"][0]), "data/plan_of_day", None, False]}
    assert _captured_path_representation(typed, encoded) == {
        "nested": ["data\\plan_of_day", "data/plan_of_day", None, False],
    }


class _PerRunClient:
    def __init__(self) -> None:
        self.turns: dict[str, int] = {}
        self.requests: list[LLMRequest] = []

    async def complete(self, request: LLMRequest) -> LLMResponse:
        self.requests.append(request)
        name = request.system_prompt
        turn = self.turns.get(name, 0)
        self.turns[name] = turn + 1
        if turn == 0:
            return _tool_turn(f"{name}:first", f"{name}:second")
        return LLMResponse(content=f"done:{name}", tokens_used=11)


def _listened_loop(
    client: Any, tools: Any, **kwargs: Any,
) -> tuple[AgenticLoop, ProbOSRuntime, list[dict[str, Any]]]:
    runtime = _local_runtime()
    events: list[dict[str, Any]] = []
    runtime.add_event_listener(lambda event: events.append(_snapshot(event)), LOOP_EVENTS)
    return (
        AgenticLoop(
            llm_client=client, tool_executor=tools, event_emit_fn=runtime.emit_event,
            event_correlation_enabled=True, **kwargs,
        ),
        runtime,
        events,
    )


def _assert_paired(events: list[dict[str, Any]]) -> None:
    starts: dict[tuple[str, int, int], dict[str, Any]] = {}
    ends: dict[tuple[str, int, int], dict[str, Any]] = {}
    for event in events:
        assert set(event) == {"type", "data", "timestamp"}
        data = event["data"]
        assert uuid.UUID(hex=data["run_id"]).hex == data["run_id"]
        if event["type"] == LOOP_EVENTS[0]:
            assert set(data) == {
                "agent_id", "iteration", "tools_used_so_far", "total_tokens",
                "run_id", "token_source",
            }
            continue
        key = (data["run_id"], data["iteration"], data["tool_call_index"])
        assert data["tool_call_id"] == " provider/duplicate "
        target = starts if event["type"] == LOOP_EVENTS[1] else ends
        assert key not in target, "An invocation identity was reused"
        target[key] = data
    assert starts and starts.keys() == ends.keys()
    for key, start in starts.items():
        assert {name: ends[key][name] for name in start} == start


@pytest.mark.asyncio
async def test_concurrent_same_instance_duplicate_ids_reach_runtime_listener() -> None:
    entered = asyncio.Event()
    release = asyncio.Event()

    class _OverlappingTools(_ToolRecorder):
        def __init__(self) -> None:
            super().__init__()
            self.active = 0
            self.peak = 0
            self.second_done = {name: asyncio.Event() for name in ("alpha", "beta")}
            self.finished: list[str] = []

        async def invoke(self, **kwargs: Any) -> ToolResult:
            self.active += 1
            self.peak = max(self.peak, self.active)
            self.calls.append(_snapshot(kwargs))
            if self.active == 4:
                entered.set()
            try:
                await release.wait()
                label = kwargs["params"]["label"]
                name, slot = label.split(":")
                if slot == "first":
                    await self.second_done[name].wait()
                else:
                    self.second_done[name].set()
                self.finished.append(label)
                return ToolResult(output=label)
            finally:
                self.active -= 1

    tools = _OverlappingTools()
    client = _PerRunClient()
    loop, runtime, events = _listened_loop(
        client, tools, parallel_tool_calls_enabled=True, max_parallel_tool_calls=2,
    )
    callbacks: dict[str, list[str]] = {"alpha": [], "beta": []}
    incoming = {
        "agent_id": "same-agent", "_agentic_run_id": "f" * 32,
        "thread_id": "correlated-thread",
    }
    unrelated: list[Any] = []
    runtime.add_event_listener(unrelated.append, ["irrelevant"])
    tasks = [
        asyncio.create_task(loop.run(
            system_prompt=name, user_message="task", tools=[], context=incoming,
            on_run_started=callbacks[name].append,
        ))
        for name in callbacks
    ]
    try:
        await asyncio.wait_for(entered.wait(), 3)
        assert tools.peak == tools.active == 4, "Same-instance runs did not overlap"
        release.set()
        results = await asyncio.gather(*tasks)
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
    assert tools.active == 0 and len(events) == 12 and not unrelated
    ids = {value[0] for value in callbacks.values()}
    assert len(ids) == 2 and "f" * 32 not in ids
    assert incoming == {
        "agent_id": "same-agent", "_agentic_run_id": "f" * 32,
        "thread_id": "correlated-thread",
    }
    assert {event["data"]["run_id"] for event in events} == ids
    assert all(
        event["data"]["thread_id"] == "correlated-thread"
        for event in events if event["type"] in LOOP_EVENTS[1:]
    )
    for name, result in zip(callbacks, results):
        assert result.final_text == f"done:{name}"
        assert [item.output for item in result.tool_results] == [
            f"{name}:first", f"{name}:second",
        ]
        assert tools.finished.index(f"{name}:second") < tools.finished.index(f"{name}:first")
        contexts = [
            call["context"]["_agentic_run_id"]
            for call in tools.calls if call["params"]["label"].startswith(name)
        ]
        assert contexts == callbacks[name] * 2
    _assert_paired(events)


@pytest.mark.asyncio
@pytest.mark.parametrize("parallel,bound", [(False, 1), (True, 1), (True, 2), (True, 3)])
async def test_original_indices_preserve_order_ceiling_and_mutation_barrier(
    parallel: bool, bound: int,
) -> None:
    names = ["write_file", "read_page", "read_page", "read_page", "unknown"]
    response = LLMResponse(
        content="", tokens_used=7,
        content_blocks=[
            ToolUseBlock(tool_call=ToolCallRequest(
                name=name, arguments={"label": str(index)}, id=" provider/duplicate ",
                timestamp=1_700_000_000.0,
            ))
            for index, name in enumerate(names)
        ],
    )
    started = asyncio.Event()
    release = asyncio.Event()

    class _PartitionTools(_ToolRecorder):
        def __init__(self) -> None:
            super().__init__()
            self.active = 0
            self.peak = 0

        async def invoke(self, **kwargs: Any) -> ToolResult:
            if kwargs["tool_id"] != "read_page":
                assert self.active == 0, "Mutation overlapped a read"
                return await super().invoke(**kwargs)
            self.active += 1
            self.peak = max(self.active, self.peak)
            if self.active == (bound if parallel else 1):
                started.set()
            try:
                await release.wait()
                return await super().invoke(**kwargs)
            finally:
                self.active -= 1

    tools = _PartitionTools()
    loop, _, events = _listened_loop(
        _ScriptedClient([response, LLMResponse(content="done", tokens_used=1)]),
        tools, parallel_tool_calls_enabled=parallel, max_parallel_tool_calls=bound,
    )
    task = asyncio.create_task(loop.run(
        system_prompt="sys", user_message="task", tools=[], context={"agent_id": "a"},
    ))
    try:
        await asyncio.wait_for(started.wait(), 3)
        release.set()
        result = await task
    finally:
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    assert tools.peak == (bound if parallel else 1) and tools.active == 0
    assert [item.output for item in result.tool_results] == [f"result:{i}" for i in range(5)]
    starts = [event["data"]["tool_call_index"] for event in events if event["type"] == LOOP_EVENTS[1]]
    assert starts == ([1, 2, 3, 0, 4] if parallel else [0, 1, 2, 3, 4])
    _assert_paired(events)


@pytest.mark.asyncio
async def test_nested_same_instance_tool_run_keeps_parent_identity() -> None:
    nested_ids: list[str] = []
    outer_ids: list[str] = []
    nested_results: list[Any] = []

    class _NestedTools(_ToolRecorder):
        async def invoke(self, **kwargs: Any) -> ToolResult:
            self.calls.append(_snapshot(kwargs))
            if kwargs["params"]["label"] == "outer:first":
                nested_results.append(await loop.run(
                    system_prompt="inner", user_message="nested", tools=[],
                    context=kwargs["context"], on_run_started=nested_ids.append,
                ))
            return ToolResult(output=kwargs["params"]["label"])

    tools = _NestedTools()
    loop, _, events = _listened_loop(_PerRunClient(), tools)
    result = await loop.run(
        system_prompt="outer", user_message="task", tools=[],
        context={"agent_id": "same"}, on_run_started=outer_ids.append,
    )
    assert result.final_text == "done:outer" and nested_results[0].final_text == "done:inner"
    assert len(outer_ids) == len(nested_ids) == 1 and outer_ids != nested_ids
    assert [call["context"]["_agentic_run_id"] for call in tools.calls] == [
        outer_ids[0], nested_ids[0], nested_ids[0], outer_ids[0],
    ]
    _assert_paired(events)


@pytest.mark.asyncio
async def test_reentrant_callbacks_and_delayed_emission_capture_run_locals() -> None:
    runtime = _local_runtime()
    events: list[dict[str, Any]] = []
    release = asyncio.Event()
    pending_runs: list[asyncio.Task[Any]] = []
    ids: dict[str, str] = {}
    incoming = {"agent_id": "same", "_agentic_run_id": "f" * 32}

    async def delayed_emit(event: EventType, payload: dict[str, Any]) -> None:
        await release.wait()
        runtime.emit_event(event, payload)

    def start(name: str) -> None:
        def observed(run_id: str) -> None:
            ids[name] = run_id
            incoming["_agentic_run_id"] = "changed-after-capture"
            if name == "outer":
                start("callback")
        pending_runs.append(asyncio.create_task(loop.run(
            system_prompt=name, user_message=name, tools=[], context=incoming,
            on_run_started=observed,
        )))

    def listener(event: dict[str, Any]) -> None:
        events.append(_snapshot(event))
        if len(events) == 1:
            start("listener")

    runtime.add_event_listener(listener, LOOP_EVENTS)
    loop = AgenticLoop(
        llm_client=_PerRunClient(), tool_executor=_ToolRecorder(),
        event_correlation_enabled=True, event_emit_fn=delayed_emit,
    )
    start("outer")
    try:
        await pending_runs[0]
        await asyncio.gather(*pending_runs)
        assert not events, "The emission delay did not discriminate"
        release.set()
        await asyncio.gather(*tuple(loop._tasks))
        assert len(pending_runs) == 3
        await asyncio.gather(*pending_runs)
        await asyncio.gather(*tuple(loop._tasks))
        await asyncio.sleep(0)
        assert not loop._tasks
        assert set(ids) == {"outer", "callback", "listener"}
        assert len(set(ids.values())) == 3 and "f" * 32 not in ids.values()
        assert len(events) == 18 and {e["data"]["run_id"] for e in events} == set(ids.values())
        _assert_paired(events)
    finally:
        release.set()
        for task in pending_runs:
            if not task.done():
                task.cancel()
        await asyncio.gather(*pending_runs, *tuple(loop._tasks), return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "first,second,third,prefix,final",
    [
        (7, 11, 3, ["measured", "measured", "measured"], "measured"),
        (0, 0, 0, ["measured", "estimated", "estimated"], "estimated"),
        (0, 11, 3, ["measured", "estimated", "mixed"], "mixed"),
        (7, 0, 0, ["measured", "measured", "mixed"], "mixed"),
    ],
)
async def test_iteration_source_qualifies_only_accumulated_prefix(
    first: int, second: int, third: int, prefix: list[str], final: str,
) -> None:
    loop, _, events = _listened_loop(
        _ScriptedClient([
            _tool_turn("first", tokens=first), _tool_turn("second", tokens=second),
            LLMResponse(content="done", tokens_used=third),
        ]), _ToolRecorder(),
    )
    result = await loop.run(system_prompt="sys", user_message="task", tools=[], context={})
    iterations = [event["data"] for event in events if event["type"] == LOOP_EVENTS[0]]
    assert [data["token_source"] for data in iterations] == prefix
    assert iterations[0]["total_tokens"] == 0
    assert 0 < iterations[1]["total_tokens"] < iterations[2]["total_tokens"] < result.total_tokens
    assert result.token_source == final
    _assert_paired(events)


@pytest.mark.asyncio
@pytest.mark.parametrize("parallel", [False, True])
@pytest.mark.parametrize("error", ["result", "exception"])
async def test_tool_failures_keep_pairable_identity(parallel: bool, error: str) -> None:
    class _FailedTools:
        async def invoke(self, **kwargs: Any) -> ToolResult:
            if error == "exception":
                raise RuntimeError("local tool failure")
            return ToolResult(output="local tool refusal", is_error=True)

    loop, _, events = _listened_loop(
        _ScriptedClient([_tool_turn("a", "b"), LLMResponse(content="done", tokens_used=2)]),
        _FailedTools(), parallel_tool_calls_enabled=parallel,
    )
    result = await loop.run(system_prompt="sys", user_message="task", tools=[], context={})
    assert result.stopped_reason == "complete" and all(item.is_error for item in result.tool_results)
    assert len(result.tool_results) == 2
    assert all(e["data"]["is_error"] for e in events if e["type"] == LOOP_EVENTS[2])
    _assert_paired(events)


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["zero_iterations", "empty", "llm_error", "cap", "budget"])
async def test_exit_boundaries_preserve_existing_event_cardinality(case: str) -> None:
    class _ExitClient:
        async def complete(self, request: LLMRequest) -> LLMResponse:
            if case == "llm_error":
                raise RuntimeError("local LLM failure")
            if case == "empty":
                return LLMResponse(content="", tokens_used=0)
            return _tool_turn("first")

    loop, _, events = _listened_loop(
        _ExitClient(), _ToolRecorder(), max_iterations=0 if case == "zero_iterations" else 1,
        token_budget=1 if case == "budget" else None,
    )
    ids: list[str] = []
    result = await loop.run(
        system_prompt="sys", user_message="task", tools=[], context={},
        on_run_started=ids.append,
    )
    assert len(ids) == 1
    expected = {
        "zero_iterations": ("max_iterations", 0, 0),
        "empty": ("complete", 1, 0), "llm_error": ("error", 1, 0),
        "cap": ("max_iterations", 3, 7), "budget": ("token_budget", 1, 7),
    }
    reason, event_count, total = expected[case]
    assert (result.stopped_reason, len(events), result.total_tokens) == (reason, event_count, total)
    assert result.token_source == "measured"
    assert all(event["data"]["run_id"] == ids[0] for event in events)


@pytest.mark.asyncio
@pytest.mark.parametrize("bound", [1, 2])
async def test_cancelled_executing_and_queued_calls_emit_no_fake_completion(bound: int) -> None:
    entered = asyncio.Event()
    active = 0
    calls = 0

    class _HeldTools:
        async def invoke(self, **kwargs: Any) -> ToolResult:
            nonlocal active, calls
            active += 1
            calls += 1
            if active == bound:
                entered.set()
            try:
                await asyncio.Event().wait()
                raise AssertionError("Cancelled tool resumed")
            finally:
                active -= 1

    loop, _, events = _listened_loop(
        _ScriptedClient([_tool_turn("first", "second", "queued")]), _HeldTools(),
        parallel_tool_calls_enabled=True, max_parallel_tool_calls=bound,
    )
    task = asyncio.create_task(loop.run(
        system_prompt="sys", user_message="task", tools=[], context={},
    ))
    try:
        await asyncio.wait_for(entered.wait(), 3)
        assert active == bound and calls == bound, "Queued-call premise did not hold"
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    finally:
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    assert active == 0 and calls == bound
    assert [event["type"] for event in events] == [LOOP_EVENTS[0]] + [LOOP_EVENTS[1]] * bound
    assert len({event["data"]["run_id"] for event in events}) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("sink", ["missing", "sync_failure", "async_failure"])
async def test_sink_failures_do_not_change_execution(sink: str) -> None:
    failed_tasks: list[asyncio.Task[Any]] = []

    def sync_failure(event: EventType, payload: dict[str, Any]) -> None:
        raise RuntimeError("local sync sink failure")

    async def async_failure(event: EventType, payload: dict[str, Any]) -> None:
        task = asyncio.current_task()
        assert task is not None
        failed_tasks.append(task)
        raise RuntimeError("local async sink failure")

    loop = AgenticLoop(
        llm_client=_ScriptedClient([_tool_turn("first"), LLMResponse(content="done", tokens_used=2)]),
        tool_executor=_ToolRecorder(), event_correlation_enabled=True,
        event_emit_fn={"missing": None, "sync_failure": sync_failure, "async_failure": async_failure}[sink],
    )
    ids: list[str] = []
    result = await loop.run(
        system_prompt="sys", user_message="task", tools=[], context={}, on_run_started=ids.append,
    )
    outcomes = await asyncio.gather(*tuple(loop._tasks), return_exceptions=True)
    assert result.stopped_reason == "complete" and result.total_tokens == 9 and len(ids) == 1
    if sink == "async_failure":
        assert len(failed_tasks) == len(outcomes) == 4
        assert all(isinstance(outcome, RuntimeError) for outcome in outcomes)


@pytest.mark.parametrize("config", [
    None, SimpleNamespace(), SimpleNamespace(event_correlation_enabled=False),
    SimpleNamespace(event_correlation_enabled=1), SimpleNamespace(event_correlation_enabled="true"),
])
def test_unarmed_config_forwards_no_new_keyword(config: Any) -> None:
    assert resolve_event_correlation_settings(config) == {}


def test_shared_flag_defaults_off_and_roundtrips() -> None:
    config = SystemConfig()
    assert config.agentic_loop.event_correlation_enabled is False
    assert resolve_event_correlation_settings(config.agentic_loop) == {}
    config.agentic_loop.event_correlation_enabled = True
    restored = SystemConfig.model_validate_json(config.model_dump_json())
    assert resolve_event_correlation_settings(restored.agentic_loop) == {"event_correlation_enabled": True}


@pytest.mark.parametrize("value", [None, "not-a-boolean", {}])
def test_shared_flag_rejects_invalid_config(value: Any) -> None:
    with pytest.raises(ValidationError):
        SystemConfig.model_validate({"agentic_loop": {"event_correlation_enabled": value}})


@pytest.mark.asyncio
async def test_native_startup_and_harness_forward_shared_enabled_flag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from probos.cognitive.builder import BuildSpec
    from probos.startup.finalize import _wire_native_swe_harness
    from probos.tools.registry import ToolRegistry

    config = SystemConfig()
    config.agentic_loop.event_correlation_enabled = True
    emitter = _local_runtime()
    events: list[Any] = []
    emitter.add_event_listener(events.append, LOOP_EVENTS)
    runtime = SimpleNamespace(
        config=config, tool_registry=ToolRegistry(), emit_event=emitter.emit_event,
        llm_client=_ScriptedClient([LLMResponse(content="No changes.", tokens_used=1)]),
    )
    calls: list[dict[str, Any]] = []
    for cls in (NativeBuilderHarness, AgenticLoop):
        _record_constructor(monkeypatch, cls, calls)
    assert _wire_native_swe_harness(runtime=runtime, config=config, tool_executor=_ToolRecorder())
    result = await runtime.native_builder_harness.run_build(
        BuildSpec(title="Local", description="Report."), work_dir="<local>",
    )
    assert result["metadata"]["stopped_reason"] == "complete"
    assert len(calls) == 2
    assert all(call["kwargs"]["event_correlation_enabled"] is True for call in calls)
    assert len(events) == 1 and events[0]["data"]["token_source"] == "measured"
    assert uuid.UUID(hex=events[0]["data"]["run_id"]).hex == events[0]["data"]["run_id"]


@pytest.mark.asyncio
async def test_enabled_run_identity_reaches_real_tool_records_without_changing_invocation_budget(
    tmp_path: Path,
) -> None:
    from probos.substrate.event_log import EventLog
    from probos.tools.executor import ToolExecutor
    from tests.test_ad1224_durable_tool_start import _FakeRegistry, _paired, _rows

    log = EventLog(db_path=tmp_path / "tool-events.db")
    await log.start()
    try:
        registry = _FakeRegistry()
        executor = ToolExecutor(registry=registry)
        _paired(executor, log, max_records_per_run=1)
        loop, _, events = _listened_loop(_PerRunClient(), executor)
        ids: list[str] = []
        for name in ("first", "second"):
            result = await loop.run(
                system_prompt=name, user_message="task", tools=[],
                context={"agent_id": "same", "_agentic_run_id": "inherited"},
                on_run_started=ids.append,
            )
            assert len(result.tool_calls) == 2 and result.stopped_reason == "complete"
        starts = await _rows(log, EventType.TOOL_STARTED.value)
        completions = await _rows(log, EventType.TOOL_INVOKED.value)
        exhausted = await _rows(log, EventType.TOOL_RECORD_BUDGET_EXHAUSTED.value)
        assert len(registry.calls) == 4
        assert len(starts) == len(completions) == len(exhausted) == 2
        assert len(set(ids)) == 2 and {row["data"]["run_id"] for row in starts} == set(ids)
        invocation_ids = {row["correlation_id"] for row in starts}
        assert len(invocation_ids) == 2
        assert invocation_ids == {row["correlation_id"] for row in completions}
        assert invocation_ids.isdisjoint(ids) and " provider/duplicate " not in invocation_ids
        _assert_paired(events)
    finally:
        await log.stop()
    reopened = EventLog(db_path=tmp_path / "tool-events.db")
    await reopened.start()
    try:
        assert await _rows(reopened, EventType.TOOL_STARTED.value) == starts
    finally:
        await reopened.stop()
