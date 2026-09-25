"""AD-1246 (#1241): a long run_python execution promotes instead of hitting the inline cap.

Seam tests with a real sandbox. The pieces are real -- the DM turn
(``CognitiveAgent._maybe_run_conversational_agentic``), AD-1165's
``run_with_promotion``, ``WorkItemAgenticExecutor``, ``ToolRegistry``,
``ToolPermissionStore``, ``CodeExecutionTool``, ``SubprocessSandbox``,
``LongRunService``, ``AuditLog``, ``WorkItemStore`` and ``ChatThreadStore`` --
and only the model is scripted. M3 adds a real ``ArtifactStore`` beside an
in-memory attachment store; M4 drives the real ``shutdown()`` over a minimal
fake runtime; M5 calls ``WorkItemAgenticExecutor.run`` with a probe tool and
fills a one-slot long-run pool. The harness helpers are copied from
``tests/test_ad1224_durable_tool_start.py`` rather than imported from it.
"""

from __future__ import annotations

import ast
import asyncio
import json
import threading
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import pytest_asyncio

import probos.tools.code_execution_tool as code_execution_tool
from probos.artifacts import ArtifactStore
from probos.cognitive.swe_harness.tool_call import ToolCallRequest, ToolUseBlock
from probos.cognitive.turn_promotion import _ACK_TEMPLATE, _REPORT_ABANDONED
from probos.config import DmAgenticConfig, ExecutionConfig
from probos.dm_reply import DmReply, ToolFailures, call_signature, failure_key
from probos.execution import long_runs
from probos.execution.long_runs import (
    EXECUTION_LONG_RUN_GRANT_KEY,
    LongRunGrant,
    LongRunService,
)
from probos.security.audit import AuditLog
from probos.startup.shutdown import shutdown
from probos.tools.permissions import ToolPermissionStore
from probos.tools.protocol import ToolResult
from probos.tools.registry import ToolRegistry

_FINAL_TEXT = "LONG-RUN-DONE-7f3a"
_CALL_ID = "call-ad1246"
# The short run finishes in well under a second; this threshold leaves seconds of
# slack, so a loaded host cannot turn the inline result into a promotion.
_SHORT_RUN_PROMOTE_AFTER = 5.0


@pytest.fixture(scope="module", autouse=True)
def _assert_tested_source_matches_worktree() -> None:
    import probos.execution.isolation as isolation_module
    import probos.execution.long_runs as long_runs_module
    import probos.tools.code_execution_tool as tool_module

    source = Path(__file__).resolve().parents[1] / "src"
    assert Path(long_runs_module.__file__).resolve().is_relative_to(source)
    assert Path(isolation_module.__file__).resolve().is_relative_to(source)
    assert Path(tool_module.__file__).resolve().is_relative_to(source)


# ---------------------------------------------------------------------------
# Harness copied from tests/test_ad1224_durable_tool_start.py
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def conversation_stores(tmp_path: Path) -> AsyncIterator[tuple[Any, Any]]:
    from probos.threads import ChatThreadStore
    from probos.workforce import WorkItemStore

    work_items = WorkItemStore(db_path=str(tmp_path / "work-items.db"))
    await work_items.start()
    threads = ChatThreadStore(tmp_path / "threads.db")
    try:
        yield work_items, threads
    finally:
        await work_items.stop()


def _conversational_agent(runtime: Any, llm: Any) -> Any:
    from probos.cognitive.cognitive_agent import CognitiveAgent

    agent = SimpleNamespace(
        _runtime=runtime, _llm_client=llm, id="conversation-agent",
        callsign="Probe", agent_type="counselor", department="science",
        rank="lieutenant", _promoted_turn_tasks=set(),
    )
    agent._conversational_agentic_will_run = (
        lambda observation: CognitiveAgent._conversational_agentic_will_run(agent, observation)
    )
    return agent


async def _conversation(agent: Any, thread_id: str) -> str | None:
    from probos.cognitive.cognitive_agent import CognitiveAgent

    return await CognitiveAgent._maybe_run_conversational_agentic(
        agent, {
            "intent": "direct_message", "thread_id": thread_id,
            "params": {"author_id": "captain", "captain_message": "use the inert probes"},
        },
        system_prompt="Test instructions.", user_message="Use the inert probes.",
    )


async def _drain_owned_tasks(tasks: set[asyncio.Task[Any]]) -> None:
    async def _drain() -> None:
        while tasks:
            await asyncio.gather(*tuple(tasks))
            await asyncio.sleep(0)

    await asyncio.wait_for(_drain(), timeout=15)


async def _cancel_owned_tasks(tasks: set[asyncio.Task[Any]]) -> None:
    pending = tuple(tasks)
    for task in pending:
        if not task.done():
            task.cancel()
    await asyncio.gather(*pending, return_exceptions=True)


def _dispatch_runtime(*, registry: Any, event_log: Any, perm_store: Any = None) -> Any:
    return SimpleNamespace(
        config=SimpleNamespace(agentic_dispatch=SimpleNamespace(enabled=True)),
        tool_registry=registry, tool_permission_store=perm_store or ToolPermissionStore(),
        capability_gap_driver=None, intent_bus=None, attachment_store=None,
        emit_event=None, event_log=event_log,
    )


# ---------------------------------------------------------------------------
# AD-1246 harness: the AD-1224 runtime plus the run_python wiring
# ---------------------------------------------------------------------------


class _ScriptedLLM:
    """Call 1 returns one tool call; call 2 returns the fixed final text.

    Every request is recorded, which is how a test reads the tool result the
    model actually received.
    """

    def __init__(self, tool_name: str, arguments: dict[str, Any]) -> None:
        self._tool_name = tool_name
        self._arguments = arguments
        self.requests: list[dict[str, Any]] = []

    async def complete(self, req: Any, **_kwargs: Any) -> Any:
        self.requests.append({
            "prompt": getattr(req, "prompt", ""),
            "messages": json.loads(json.dumps(getattr(req, "messages", None), default=str)),
        })
        if len(self.requests) == 1:
            call = ToolCallRequest(id=_CALL_ID, name=self._tool_name, arguments=dict(self._arguments))
            return SimpleNamespace(content_blocks=[ToolUseBlock(tool_call=call)], content="", tokens_used=1)
        return SimpleNamespace(content_blocks=[], content=_FINAL_TEXT, tokens_used=1)


class _GrantProbe:
    """A registered tool that records the invocation context it was handed."""

    def __init__(self) -> None:
        self.contexts: list[dict[str, Any]] = []

    @property
    def tool_id(self) -> str:
        return "grant_probe"

    @property
    def name(self) -> str:
        return "grant_probe"

    @property
    def tool_type(self) -> Any:
        from probos.tools.protocol import ToolType

        return ToolType.DETERMINISTIC_FUNCTION

    @property
    def description(self) -> str:
        return "Records the invocation context it was handed."

    @property
    def input_schema(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}}

    @property
    def output_schema(self) -> dict[str, Any]:
        return {"type": "object"}

    async def invoke(self, params: dict[str, Any], context: dict[str, Any] | None = None) -> ToolResult:
        self.contexts.append(dict(context or {}))
        return ToolResult(output="probed")


def _run_python_runtime(
    *,
    scratch: Path,
    max_runtime_seconds: float,
    dm_agentic: Any,
    work_items: Any,
    threads: Any,
) -> Any:
    """AD-1224's dispatch runtime plus the P-3 probe's run_python wiring."""
    runtime = _dispatch_runtime(registry=ToolRegistry(), event_log=None)
    runtime.config.execution = ExecutionConfig(
        enabled=True, scratch_dir=str(scratch), max_runtime_seconds=max_runtime_seconds,
    )
    runtime.config.dm_agentic = dm_agentic
    runtime.config.mcp = None
    runtime.intent_grant_store = None
    runtime.mcp_workbench = None
    runtime.artifact_store = None
    runtime.audit_log = AuditLog()
    runtime.work_item_store = work_items
    runtime.chat_thread_store = threads
    runtime.execution_long_runs = LongRunService()
    return runtime


def _beats_code(beat_file: Path, beats: int) -> str:
    """One process, no children: append one numbered line every 0.1 s, then exit 0."""
    assert beats <= 50
    return (
        "import time\n"
        f"path = {str(beat_file)!r}\n"
        f"for i in range({beats}):\n"
        "    with open(path, 'a', encoding='utf-8') as handle:\n"
        "        handle.write(f'{i}\\n')\n"
        "    time.sleep(0.1)\n"
        f"print('beats done: {beats}')\n"
    )


def _beats(beat_file: Path) -> int:
    return beat_file.read_bytes().count(b"\n") if beat_file.exists() else 0


def _code_execution_records(audit_log: AuditLog) -> list[dict[str, Any]]:
    return [json.loads(entry.detail) for entry in audit_log.entries if entry.category == "code_execution"]


def _tool_result_seen(llm: _ScriptedLLM) -> str:
    """The tool-result message exactly as the model's second call received it."""
    assert len(llm.requests) == 2, f"premise: the model was called twice, got {len(llm.requests)}"
    prompt = llm.requests[1]["prompt"]
    marker = f"[tool_result:{_CALL_ID} "
    assert prompt.count(marker) == 1, "premise: exactly one tool result reached the model"
    seen = prompt[prompt.index(marker):]
    end = seen.find("\n\n[")
    return seen if end < 0 else seen[:end]


async def _close_service(service: LongRunService) -> None:
    service.close("test")
    await service.wait_settled(5.0)


# ---------------------------------------------------------------------------
# M1
# ---------------------------------------------------------------------------


async def test_m1_long_run_promotes_keeps_running_and_reports_once(
    tmp_path: Path, conversation_stores: Any,
) -> None:
    store, threads = conversation_stores
    thread = threads.create_thread(title="Probe", participants=["conversation-agent"])
    beat_file = tmp_path / "beats.txt"
    runtime = _run_python_runtime(
        scratch=tmp_path / "scratch", max_runtime_seconds=600.0,
        dm_agentic=DmAgenticConfig(enabled=True, promote_to_task_after_seconds=0.6),
        work_items=store, threads=threads,
    )
    service = runtime.execution_long_runs
    llm = _ScriptedLLM("run_python", {"code": _beats_code(beat_file, 30), "timeout": 400})
    agent = _conversational_agent(runtime, llm)
    try:
        ack = await asyncio.wait_for(_conversation(agent, thread.id), timeout=10)
        beats_at_ack = _beats(beat_file)
        items = await store.list_work_items()

        # (a) Premise: the turn was promoted while the child was mid-run.
        assert len(items) == 1
        promoted = items[0]
        assert ack == _ACK_TEMPLATE.format(work_item_id=promoted.id)
        assert 1 <= beats_at_ack < 30, beats_at_ack

        # (b) Acceptance 3: the child outlives the acknowledgement, on the long-run pool.
        await asyncio.sleep(0.5)
        assert _beats(beat_file) > beats_at_ack
        assert service.active_count == 1
        assert any(
            worker.name.startswith("probos-long-run") and worker.is_alive()
            for worker in threading.enumerate()
        )

        # (c) Acceptance 5: nothing is audited while the run is still going.
        assert _code_execution_records(runtime.audit_log) == []

        # (d) Acceptances 2, 3 and 5: one execution, one record, one report.
        await _drain_owned_tasks(agent._promoted_turn_tasks)
        records = _code_execution_records(runtime.audit_log)
        assert len(records) == 1
        # HEAD clamps this request to 300.0, so the applied value is the reach itself.
        assert records[0]["timeout_seconds"] == 400.0
        assert records[0]["launch_state"] == "launched"
        assert records[0]["success"] is True
        assert _beats(beat_file) == 30
        agent_posts = [message for message in threads.list_messages(thread.id) if message.role == "agent"]
        assert [message.body for message in agent_posts] == [_FINAL_TEXT]
        assert agent_posts[0].metadata.get("work_item_id") == promoted.id
        assert (await store.get_work_item(promoted.id)).status == "done"
        assert service.active_count == 0

        # (e) The model read the run's own output, and nothing was lowered.
        seen = _tool_result_seen(llm)
        assert "beats done: 30" in seen
        assert "wall_clock" not in seen
    finally:
        await _cancel_owned_tasks(agent._promoted_turn_tasks)
        await _close_service(service)


async def test_m1_short_run_is_inline_and_byte_identical_armed_or_not(
    tmp_path: Path, conversation_stores: Any, monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, threads = conversation_stores
    real_plan = code_execution_tool.plan_long_run
    planned: list[tuple[Any, Any]] = []

    def _recording_plan(*args: Any, **kwargs: Any) -> Any:
        plan = real_plan(*args, **kwargs)
        planned.append((kwargs.get("grant"), plan))
        return plan

    monkeypatch.setattr(code_execution_tool, "plan_long_run", _recording_plan)
    seen: dict[str, str] = {}
    audits: dict[str, dict[str, Any]] = {}
    for label, max_runtime in (("unarmed", 0.0), ("armed", 600.0)):
        thread = threads.create_thread(title=f"Probe {label}", participants=["conversation-agent"])
        runtime = _run_python_runtime(
            scratch=tmp_path / f"scratch-{label}", max_runtime_seconds=max_runtime,
            dm_agentic=DmAgenticConfig(
                enabled=True, promote_to_task_after_seconds=_SHORT_RUN_PROMOTE_AFTER,
            ),
            work_items=store, threads=threads,
        )
        llm = _ScriptedLLM("run_python", {"code": 'print("hello")'})
        agent = _conversational_agent(runtime, llm)
        try:
            text = await asyncio.wait_for(_conversation(agent, thread.id), timeout=20)
            assert text == _FINAL_TEXT
            assert await store.list_work_items() == []
            seen[label] = _tool_result_seen(llm)
            records = _code_execution_records(runtime.audit_log)
            assert len(records) == 1
            audits[label] = {
                key: value for key, value in records[0].items()
                if key not in ("execution_id", "duration_ms")
            }
        finally:
            await _cancel_owned_tasks(agent._promoted_turn_tasks)
            await _close_service(runtime.execution_long_runs)

    # Premise: the armed run carried a real grant and the planner still chose today's path.
    assert len(planned) == 2
    assert planned[0] == (None, None)
    assert type(planned[1][0]) is LongRunGrant
    assert planned[1][1] is None
    assert "hello" in seen["unarmed"]
    # Acceptance 1: the model received byte-identical results; the trail differs only per run.
    assert seen["armed"].encode("utf-8") == seen["unarmed"].encode("utf-8")
    assert audits["armed"] == audits["unarmed"]


@pytest.mark.parametrize(
    ("case", "promote_after", "max_runtime", "with_thread", "expect_grant"),
    [
        ("promotion_off", 0.0, 600.0, True, False),
        ("promotable_and_armed", 0.6, 600.0, True, True),
        ("no_thread", 0.6, 600.0, False, False),
        ("unarmed", 0.6, 0.0, True, False),
    ],
)
async def test_m1_grant_reaches_the_tool_only_from_a_promotable_turn(
    tmp_path: Path, conversation_stores: Any,
    case: str, promote_after: float, max_runtime: float, with_thread: bool, expect_grant: bool,
) -> None:
    store, threads = conversation_stores
    runtime = _run_python_runtime(
        scratch=tmp_path / "scratch", max_runtime_seconds=max_runtime,
        dm_agentic=DmAgenticConfig(enabled=True, promote_to_task_after_seconds=promote_after),
        work_items=store, threads=threads,
    )
    thread_id = ""
    if with_thread:
        thread_id = threads.create_thread(title="Probe", participants=["conversation-agent"]).id
    else:
        # No observation thread and no store to derive one from: the turn has no thread.
        runtime.chat_thread_store = None
    probe = _GrantProbe()
    runtime.tool_registry.register(probe)
    agent = _conversational_agent(runtime, _ScriptedLLM("grant_probe", {}))
    try:
        await asyncio.wait_for(_conversation(agent, thread_id), timeout=15)
        await _drain_owned_tasks(agent._promoted_turn_tasks)
        # Premise: the probe ran inside this turn, beside a registered run_python.
        assert len(probe.contexts) == 1, case
        assert runtime.tool_registry.get("run_python") is not None
        grant = probe.contexts[0].get(EXECUTION_LONG_RUN_GRANT_KEY)
        if expect_grant:
            assert type(grant) is LongRunGrant, case
            # The default BF-733 deadline (1800 s) less the 300 s answer margin.
            # 1e-6: on a clock that has not ticked, float rounding overshoots by ulps.
            assert 1400.0 < grant.remaining() <= 1500.6 + 1e-6
        else:
            assert EXECUTION_LONG_RUN_GRANT_KEY not in probe.contexts[0], case
    finally:
        await _cancel_owned_tasks(agent._promoted_turn_tasks)
        await _close_service(runtime.execution_long_runs)


# ---------------------------------------------------------------------------
# M2
# ---------------------------------------------------------------------------


def _record_tool_results(monkeypatch: pytest.MonkeyPatch) -> list[ToolResult]:
    """Record every ToolResult run_python hands the loop, next to what the model read."""
    results: list[ToolResult] = []
    real_invoke = code_execution_tool.CodeExecutionTool.invoke

    async def _recording_invoke(
        self: Any, params: dict[str, Any], context: dict[str, Any] | None = None,
    ) -> ToolResult:
        result = await real_invoke(self, params, context)
        results.append(result)
        return result

    monkeypatch.setattr(code_execution_tool.CodeExecutionTool, "invoke", _recording_invoke)
    return results


async def _drain_owned_tasks_through_cancellation(tasks: set[asyncio.Task[Any]]) -> None:
    """``_drain_owned_tasks`` for a run BF-733 cancels: that cancellation is the expected outcome."""

    async def _drain() -> None:
        while tasks:
            for outcome in await asyncio.gather(*tuple(tasks), return_exceptions=True):
                if isinstance(outcome, BaseException) and not isinstance(
                    outcome, asyncio.CancelledError,
                ):
                    raise outcome
            await asyncio.sleep(0)

    await asyncio.wait_for(_drain(), timeout=15)


async def test_m2_bf733_cancel_kills_the_long_child_and_the_report_is_true(
    tmp_path: Path, conversation_stores: Any,
) -> None:
    store, threads = conversation_stores
    thread = threads.create_thread(title="Probe", participants=["conversation-agent"])
    beat_file = tmp_path / "beats.txt"
    runtime = _run_python_runtime(
        scratch=tmp_path / "scratch", max_runtime_seconds=600.0,
        dm_agentic=DmAgenticConfig(
            enabled=True, promote_to_task_after_seconds=0.6, promoted_run_deadline_seconds=1.0,
        ),
        work_items=store, threads=threads,
    )
    service = runtime.execution_long_runs
    llm = _ScriptedLLM("run_python", {"code": _beats_code(beat_file, 50), "timeout": 400})
    agent = _conversational_agent(runtime, llm)
    try:
        ack = await asyncio.wait_for(_conversation(agent, thread.id), timeout=10)
        beats_at_ack = _beats(beat_file)
        items = await store.list_work_items()
        assert len(items) == 1
        promoted = items[0]
        assert ack == _ACK_TEMPLATE.format(work_item_id=promoted.id)

        # Premise: the long child is still running after the acknowledgement.
        await asyncio.sleep(0.5)
        assert _beats(beat_file) > beats_at_ack

        await _drain_owned_tasks_through_cancellation(agent._promoted_turn_tasks)
        beats_at_report = _beats(beat_file)
        agent_posts = [message for message in threads.list_messages(thread.id) if message.role == "agent"]
        assert [message.body for message in agent_posts] == [_REPORT_ABANDONED]
        assert (await store.get_work_item(promoted.id)).status == "failed"
        # Premise: the watchdog stopped the turn inside the tool call, before the child finished.
        assert len(llm.requests) == 1
        assert beats_at_report < 50

        # "...so I stopped it" is now true: HEAD grew 16 -> 26 beats over this second (P-4).
        await asyncio.sleep(1.0)
        assert _beats(beat_file) == beats_at_report

        records = _code_execution_records(runtime.audit_log)
        assert len(records) == 1
        assert records[0]["error_type"] == "cancelled"
        assert records[0]["launch_state"] == "launched"
        # The grant's time left is below the inline clock, so the 300 s floor applied.
        assert records[0]["timeout_seconds"] == 300.0
        assert service.active_count == 0
    finally:
        await _cancel_owned_tasks(agent._promoted_turn_tasks)
        await _close_service(service)


async def test_m2_long_run_that_times_out_on_its_own_clock_still_reports(
    tmp_path: Path, conversation_stores: Any, monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, threads = conversation_stores
    thread = threads.create_thread(title="Probe", participants=["conversation-agent"])
    monkeypatch.setattr(long_runs, "INLINE_WALL_CLOCK_SECONDS", 1.0)
    results = _record_tool_results(monkeypatch)
    runtime = _run_python_runtime(
        scratch=tmp_path / "scratch", max_runtime_seconds=0.0,
        dm_agentic=DmAgenticConfig(enabled=True, promote_to_task_after_seconds=0.6),
        work_items=store, threads=threads,
    )
    # H-4: the validator refuses a 2 s reach, so this config is built without it.
    runtime.config.execution = ExecutionConfig.model_construct(
        enabled=True, scratch_dir=str(tmp_path / "scratch"), max_runtime_seconds=2.0,
    )
    service = runtime.execution_long_runs
    llm = _ScriptedLLM(
        "run_python", {"code": "import time\ntime.sleep(10)\nprint('slept')\n", "timeout": 5},
    )
    agent = _conversational_agent(runtime, llm)
    note = (
        "This vessel stops a single long run at 2s (execution.max_runtime_seconds). "
        "Split the work into steps that fit."
    )
    try:
        ack = await asyncio.wait_for(_conversation(agent, thread.id), timeout=10)
        items = await store.list_work_items()
        assert len(items) == 1
        promoted = items[0]
        # Premise: the turn was promoted before the run's own 2 s clock ended it.
        assert ack == _ACK_TEMPLATE.format(work_item_id=promoted.id)
        await _drain_owned_tasks(agent._promoted_turn_tasks)

        records = _code_execution_records(runtime.audit_log)
        assert len(records) == 1
        assert records[0]["timeout_seconds"] == 2.0
        assert records[0]["timed_out"] is True
        assert records[0]["error_type"] == "sandbox_error"

        # A-3: a failed call's output never reaches the model, so the note rides its error.
        assert len(results) == 1
        assert results[0].output["wall_clock"] == {
            "requested_seconds": 5.0, "applied_seconds": 2.0, "reason": "max_runtime", "note": note,
        }
        header, seen = _tool_result_seen(llm).split("\n", 1)
        assert header == f"[tool_result:{_CALL_ID} error=True]"
        assert seen == "timed out. " + note

        # Acceptance 6: the report still lands, carrying the AD-1248 disclosure.
        failures = ToolFailures.from_mapping({
            failure_key("r" * 12, "r" * 12, call_signature("run_python", None)): "run_python",
        })
        expected = str(DmReply(body=_FINAL_TEXT, tool_failures=failures).render())
        assert expected != _FINAL_TEXT
        agent_posts = [message for message in threads.list_messages(thread.id) if message.role == "agent"]
        assert [message.body for message in agent_posts] == [expected]
        assert (await store.get_work_item(promoted.id)).status == "done"
        assert service.active_count == 0
    finally:
        await _cancel_owned_tasks(agent._promoted_turn_tasks)
        await _close_service(service)


# ---------------------------------------------------------------------------
# M3
# ---------------------------------------------------------------------------


class _FakeAttachmentStore:
    """Protocol-faithful in-memory AttachmentStore, copied from test_ad1066."""

    def __init__(self) -> None:
        self.blobs: dict[str, tuple[bytes, str, str]] = {}

    async def write(
        self, content_hash: str, blob: bytes, mime: str, *, origin: str = "chat_attachment",
    ) -> Path:
        self.blobs[content_hash] = (blob, mime, origin)
        return Path(f"/fake/{content_hash}")


async def test_m3_promoted_long_run_artifacts_land_on_the_thread(
    tmp_path: Path, conversation_stores: Any,
) -> None:
    store, threads = conversation_stores
    thread = threads.create_thread(title="Probe", participants=["conversation-agent"])
    beat_file = tmp_path / "beats.txt"
    runtime = _run_python_runtime(
        scratch=tmp_path / "scratch", max_runtime_seconds=600.0,
        dm_agentic=DmAgenticConfig(enabled=True, promote_to_task_after_seconds=0.6),
        work_items=store, threads=threads,
    )
    runtime.artifact_store = ArtifactStore(tmp_path / "artifacts.db")
    runtime.attachment_store = _FakeAttachmentStore()
    service = runtime.execution_long_runs
    code = (
        "with open('report.txt', 'w', encoding='utf-8') as handle:\n"
        "    handle.write('long-run report\\n')\n"
    ) + _beats_code(beat_file, 20)
    llm = _ScriptedLLM("run_python", {"code": code, "timeout": 400})
    agent = _conversational_agent(runtime, llm)
    try:
        ack = await asyncio.wait_for(_conversation(agent, thread.id), timeout=10)
        beats_at_ack = _beats(beat_file)
        items = await store.list_work_items()
        assert len(items) == 1
        promoted = items[0]
        # Premise: the turn was promoted while the run was still going.
        assert ack == _ACK_TEMPLATE.format(work_item_id=promoted.id)
        assert beats_at_ack < 20
        await _drain_owned_tasks(agent._promoted_turn_tasks)

        _header, seen = _tool_result_seen(llm).split("\n", 1)
        assert ast.literal_eval(seen)["artifacts"] == ["report.txt"]
        versions = runtime.artifact_store.list_versions(thread_id=thread.id, name="report.txt")
        assert len(versions) == 1
        assert [artifact.name for artifact in runtime.artifact_store.list_thread_latest(thread.id)] == [
            "report.txt",
        ]
        blob, _mime, _origin = runtime.attachment_store.blobs[versions[0].content_hash]
        assert blob.replace(b"\r\n", b"\n") == b"long-run report\n"
        records = _code_execution_records(runtime.audit_log)
        assert len(records) == 1
        assert records[0]["artifact_count"] == 1
        assert records[0]["timeout_seconds"] == 400.0
        agent_posts = [message for message in threads.list_messages(thread.id) if message.role == "agent"]
        assert [message.body for message in agent_posts] == [_FINAL_TEXT]
        assert service.active_count == 0
    finally:
        await _cancel_owned_tasks(agent._promoted_turn_tasks)
        await _close_service(service)


# ---------------------------------------------------------------------------
# M4
# ---------------------------------------------------------------------------


class _FakeShutdownRegistry:
    def all(self) -> list[Any]:
        return []


class _FakeShutdownRuntime:
    """``_FakeRuntime`` from tests/test_bf598_shutdown_idempotency.py, plus the long-run service.

    Only what ``shutdown()`` reads up to its ``_started`` short-circuit is populated.
    """

    def __init__(
        self, *, data_dir: Path, execution_long_runs: LongRunService, crew_orchestrator: Any,
    ) -> None:
        self._data_dir = data_dir
        self._started = False
        self._shutdown_started = False
        self._session_id = "ad1246-test-session"
        self._start_time_wall = 0.0
        self._start_time = 0.0
        self.registry = _FakeShutdownRegistry()
        self.ontology = None
        self.confab_probe_tasks: set[Any] = set()
        self._confab_probe_scheduling_open = True
        self.dream_scheduler = None
        self.episodic_memory = None
        self.config = None
        self.execution_long_runs = execution_long_runs
        self.crew_orchestrator = crew_orchestrator

    def close_confab_probe_scheduling(self) -> None:
        self._confab_probe_scheduling_open = False


class _RecordingCrewOrchestrator:
    """Its ``stop()`` is shutdown's first await; it records whether long runs were closed by then."""

    def __init__(self, service: LongRunService) -> None:
        self._service = service
        self.closed_at_stop: list[bool] = []

    async def stop(self) -> None:
        self.closed_at_stop.append(self._service.closed)


async def _wait_until(predicate: Callable[[], bool], *, timeout: float) -> None:
    async def _poll() -> None:
        while not predicate():
            await asyncio.sleep(0.05)

    await asyncio.wait_for(_poll(), timeout=timeout)


async def test_m4_shutdown_kills_the_long_child_and_its_audit_says_so(tmp_path: Path) -> None:
    service = LongRunService()
    beat_file = tmp_path / "beats.txt"
    tool_runtime = SimpleNamespace(
        config=SimpleNamespace(execution=ExecutionConfig(
            enabled=True, scratch_dir=str(tmp_path / "scratch"), max_runtime_seconds=600.0,
        )),
        audit_log=AuditLog(),
        execution_long_runs=service,
    )
    tool = code_execution_tool.CodeExecutionTool(runtime=tool_runtime)
    crew = _RecordingCrewOrchestrator(service)
    fake = _FakeShutdownRuntime(data_dir=tmp_path, execution_long_runs=service, crew_orchestrator=crew)
    context = {EXECUTION_LONG_RUN_GRANT_KEY: LongRunGrant(None), "agent_id": "a", "thread_id": ""}
    observed: dict[str, int] = {}

    async def _shut_down_once_running() -> None:
        # Premise: the long child is running before shutdown starts.
        await _wait_until(lambda: _beats(beat_file) >= 3, timeout=15)
        await asyncio.wait_for(shutdown(fake, "test"), 5)
        observed["records_at_return"] = len(_code_execution_records(tool_runtime.audit_log))

    try:
        result, _ = await asyncio.wait_for(
            asyncio.gather(
                tool.invoke({"code": _beats_code(beat_file, 50), "timeout": 400}, context),
                _shut_down_once_running(),
            ),
            timeout=30,
        )
        beats_after_shutdown = _beats(beat_file)
        assert result.error == "stopped: shutdown"
        assert result.output["success"] is False
        assert result.output["timed_out"] is False
        # The close ran before shutdown's first await, and its settle outlasted the audit.
        assert crew.closed_at_stop == [True]
        assert observed["records_at_return"] == 1
        await asyncio.sleep(1.0)
        assert _beats(beat_file) == beats_after_shutdown < 50
        records = _code_execution_records(tool_runtime.audit_log)
        assert len(records) == 1
        assert records[0]["error_type"] == "stopped_at_shutdown"
        assert records[0]["timeout_seconds"] == 400.0
        assert service.active_count == 0
        assert service.admit("late", limit=2) is None
    finally:
        await _close_service(service)


# ---------------------------------------------------------------------------
# M5: the dispatch boundary, and a full long-run pool
# ---------------------------------------------------------------------------


def _probe_runtime(tmp_path: Path, stores: tuple[Any, Any]) -> tuple[Any, _GrantProbe]:
    work_items, threads = stores
    runtime = _run_python_runtime(
        scratch=tmp_path / "scratch", max_runtime_seconds=600.0,
        dm_agentic=DmAgenticConfig(enabled=True), work_items=work_items, threads=threads,
    )
    probe = _GrantProbe()
    runtime.tool_registry.register(probe)
    return runtime, probe


async def _run_with_extra_context(
    runtime: Any, llm: _ScriptedLLM, extra_context: dict[str, Any],
) -> Any:
    """The real ``WorkItemAgenticExecutor.run`` boundary, called the way a direct turn calls it."""
    from probos.cognitive.agentic_dispatch import WorkItemAgenticExecutor

    return await asyncio.wait_for(
        WorkItemAgenticExecutor(llm_client=llm).run(
            agent_id="conversation-agent", instructions="Test instructions.",
            task_text="Use the probe.", runtime=runtime, thread_id="thread",
            max_iterations=2, extra_context=extra_context,
        ),
        timeout=15,
    )


async def _assert_dispatch_refuses(
    runtime: Any, llm: _ScriptedLLM, probe: _GrantProbe, extra_context: dict[str, Any],
) -> None:
    requests_before, probes_before = len(llm.requests), len(probe.contexts)
    with pytest.raises(ValueError, match="^agentic_context_invalid$"):
        await _run_with_extra_context(runtime, llm, extra_context)
    assert (len(llm.requests), len(probe.contexts)) == (requests_before, probes_before), (
        "the refused run made no model call and reached no tool"
    )


async def test_m5_dispatch_forwards_the_grant_to_the_tool_by_identity(
    tmp_path: Path, conversation_stores: Any,
) -> None:
    runtime, probe = _probe_runtime(tmp_path, conversation_stores)
    grant = LongRunGrant(None)
    try:
        outcome = await _run_with_extra_context(
            runtime, _ScriptedLLM("grant_probe", {}), {EXECUTION_LONG_RUN_GRANT_KEY: grant},
        )
        assert outcome.final_text == _FINAL_TEXT
        assert len(probe.contexts) == 1
        assert probe.contexts[0][EXECUTION_LONG_RUN_GRANT_KEY] is grant
    finally:
        await _close_service(runtime.execution_long_runs)


class _ForgedGrant(LongRunGrant):
    """Passes ``isinstance``, so only the dispatch's exact-type check can refuse it."""


@pytest.mark.parametrize(
    "forged",
    [lambda: object(), lambda: None, lambda: {"deadline_monotonic": None}, lambda: _ForgedGrant(None)],
    ids=["object", "none", "dict", "subclass"],
)
async def test_m5_dispatch_refuses_a_grant_that_is_not_the_exact_type(
    tmp_path: Path, conversation_stores: Any, forged: Callable[[], object],
) -> None:
    runtime, probe = _probe_runtime(tmp_path, conversation_stores)
    llm = _ScriptedLLM("grant_probe", {})
    try:
        # Premise: this same boundary forwards the exact type.
        await _run_with_extra_context(runtime, llm, {EXECUTION_LONG_RUN_GRANT_KEY: LongRunGrant(None)})
        assert len(probe.contexts) == 1

        await _assert_dispatch_refuses(runtime, llm, probe, {EXECUTION_LONG_RUN_GRANT_KEY: forged()})
    finally:
        await _close_service(runtime.execution_long_runs)


@pytest.mark.parametrize(
    ("key", "value"),
    [("_delegation_depth", 1), ("_crew_session_id", "session-1"), ("_crew_work_item_id", "item-1")],
    ids=["delegated", "crew-session", "crew-work-item"],
)
async def test_m5_dispatch_refuses_a_grant_beside_a_delegated_or_crew_key(
    tmp_path: Path, conversation_stores: Any, key: str, value: Any,
) -> None:
    runtime, probe = _probe_runtime(tmp_path, conversation_stores)
    llm = _ScriptedLLM("grant_probe", {})
    try:
        # Premise: the key alone passes this boundary, so the grant beside it is what is refused.
        await _run_with_extra_context(runtime, llm, {key: value})
        assert len(probe.contexts) == 1
        assert probe.contexts[0].get(key) == value

        await _assert_dispatch_refuses(
            runtime, llm, probe, {key: value, EXECUTION_LONG_RUN_GRANT_KEY: LongRunGrant(None)},
        )
    finally:
        await _close_service(runtime.execution_long_runs)


async def test_m5_second_long_run_gets_the_inline_clock_when_slots_are_full(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(long_runs, "INLINE_WALL_CLOCK_SECONDS", 1.0)
    service = LongRunService()
    active_at_admit: list[int] = []
    real_admit = service.admit

    def _recording_admit(execution_id: str, *, limit: int) -> Any:
        active_at_admit.append(service.active_count)
        return real_admit(execution_id, limit=limit)

    monkeypatch.setattr(service, "admit", _recording_admit)
    tool_runtime = SimpleNamespace(
        # H-4: the validator refuses a 4 s reach, so this config is built without it.
        config=SimpleNamespace(execution=ExecutionConfig.model_construct(
            enabled=True, scratch_dir=str(tmp_path / "scratch"), max_runtime_seconds=4.0,
            max_concurrent_long_runs=1,
        )),
        audit_log=AuditLog(),
        execution_long_runs=service,
    )
    tool = code_execution_tool.CodeExecutionTool(runtime=tool_runtime)
    started = tmp_path / "first-started.txt"
    first_code = (
        f"import pathlib, time\npathlib.Path({str(started)!r}).write_text('up')\n"
        "time.sleep(2)\nprint('first done')\n"
    )
    second_code = "import time\ntime.sleep(2)\nprint('second done')\n"
    context = {EXECUTION_LONG_RUN_GRANT_KEY: LongRunGrant(None), "agent_id": "a", "thread_id": ""}
    note = (
        "Every long-run slot was in use, so this run had the 1s inline wall clock. "
        "Run it again once a long job finishes, or split the work."
    )

    async def _second_once_the_first_holds_the_slot() -> ToolResult:
        await _wait_until(started.exists, timeout=15)
        return await tool.invoke({"code": second_code, "timeout": 3.5}, context)

    try:
        first, second = await asyncio.wait_for(
            asyncio.gather(
                tool.invoke({"code": first_code, "timeout": 3.5}, context),
                _second_once_the_first_holds_the_slot(),
            ),
            timeout=30,
        )
        # Premise: the second call planned while the first held the pool's only slot.
        assert active_at_admit == [0, 1]

        assert first.error is None
        assert first.output["success"] is True
        assert "wall_clock" not in first.output

        assert second.output["timed_out"] is True
        assert second.output["wall_clock"] == {
            "requested_seconds": 3.5, "applied_seconds": 1.0, "reason": "long_runs_busy",
            "note": note,
        }
        # A-3: the error is all the model reads of a failed call, so the note rides it.
        assert second.error == "timed out. " + note

        records = _code_execution_records(tool_runtime.audit_log)
        assert sorted(
            (record["timeout_seconds"], record["success"], record["timed_out"]) for record in records
        ) == [(1.0, False, True), (3.5, True, False)]
        assert service.active_count == 0
    finally:
        await _close_service(service)
