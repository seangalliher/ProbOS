"""AD-1164: a step limit is a checkpoint that asks, not a cliff that truncates.

BF-697 stopped the conversational agentic loop *discarding* the work it had
done when it hit ``dm_agentic.max_iterations``. It did not give the agent any
way to SAY it was cut off, so exhausting the budget still read as finishing.
This suite covers the structural fix: continue under a standing rule, or file a
durable ask and report the partial work with an explicit cut-off statement.

**The produce -> consume path is exercised for real** (the first section). The
``stopped_reason`` and ``final_text`` this module reasons about are produced by
the REAL :class:`AgenticLoop` driven through the REAL
``OpenAICompatibleClient._call_openai`` wire parser, and consumed by the REAL
:class:`CapabilityRequestStore` / :class:`ActionApprovalStore` on real
``tmp_path`` SQLite. Nothing in that path is a hand-typed string or an
over-capable double. Today's lesson, in the words of the era preamble: a test
that supplies the very input it is meant to prove arrives from elsewhere is
structurally incapable of detecting that nothing sends it. The re-invocation
test drives a second real loop and asserts the AD-1155 continuation block
reached its prompt.

The cache-only (``db_path=""``) shortcut is deliberately NOT used for the filed
request: the payload only proves anything if it survives
``_decode_payload``'s re-validation on reload, and a cache-only store never runs
it.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import pytest

from probos.capability_request import (
    _THREAD_ID_MAX,
    CapabilityRequestStore,
    validate_action_payload,
)
from probos.cognitive.agentic_dispatch import WorkItemAgenticOutcome
from probos.cognitive.continue_or_ask import (
    _CUT_OFF_LEAD_NO_WORK,
    _CUT_OFF_LEAD_WITH_WORK,
    _CUT_OFF_SEPARATOR,
    _CUT_OFF_TAIL,
    _CUT_OFF_TAIL_WITH_REQUEST,
    _MAX_CONTINUE_PASSES,
    _display_task_text,
    _task_excerpt,
    CONTINUE_ACTION,
    CONTINUE_REQUEST_KIND,
    CONTINUE_SCOPE_KEY,
    CONTINUE_TOOL_ID,
    continue_payload,
    is_continue_or_ask_armed,
    resolve_continue_max_passes,
    resolve_exhausted_turn,
)
# BF-709: the ONE helper both Captain-facing paths now derive their text from.
# Imported from its owner so this suite cannot pass against a second copy.
from probos.cognitive.cognitive_agent import _promotion_request_text
# The real membership set and the real continuation renderer, imported so this
# suite cannot pass against a private copy (AD-1155 owns both).
from probos.cognitive.crew_executor import (
    _CONTINUATION_HEADER,
    _REINVOKABLE_STOPPED_REASONS,
    _STOPPED_REASONS,
    _render_continuation,
)
# The REAL regex, imported rather than re-typed: ``lack`` is a bare substring in
# it, so reasoning about a match is not evidence.
from probos.cognitive.decomposer import _CAPABILITY_GAP_RE
from probos.cognitive.llm_client import OpenAICompatibleClient
from probos.cognitive.swe_harness.agentic_loop import AgenticLoop
from probos.cognitive.swe_harness.tool_call import ToolCallRequest, ToolCallResult
from probos.config import DmAgenticConfig
from probos.fault_report import FaultReportStore
from probos.tools.action_approvals import ActionApprovalStore
from probos.tools.protocol import ToolResult
from probos.types import LLMRequest, LLMResponse

_REPO_ROOT = Path(__file__).resolve().parent.parent

_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "browser",
            "description": "Drive a Chromium browser.",
            "parameters": {"type": "object", "properties": {}},
        },
    }
]

_TASK = "Type Hello World into the document I have open"


# ── The real wire, so ``stopped_reason`` is produced rather than asserted ──


def _wire_body(
    *,
    text: str | None,
    tool_name: str | None = None,
    arguments: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """One raw OpenAI ``chat/completions`` body, as the proxy returns it.

    ``arguments`` is serialised to a JSON **string** because that is what the
    wire carries and what ``_call_openai`` has to parse. ``usage`` is empty,
    matching the live Copilot proxy (BF-680).
    """
    message: dict[str, Any] = {"role": "assistant", "content": text}
    if tool_name is not None:
        message["tool_calls"] = [
            {
                "id": "tc1",
                "type": "function",
                "function": {
                    "name": tool_name,
                    "arguments": json.dumps(arguments or {}),
                },
            }
        ]
    return {
        "choices": [
            {
                "message": message,
                "finish_reason": "tool_calls" if tool_name else "stop",
            }
        ],
        "usage": {},
    }


class _WireResponse:
    def __init__(self, body: dict[str, Any]) -> None:
        self._body = body

    def raise_for_status(self) -> None: ...

    def json(self) -> dict[str, Any]:
        return self._body


class _WireTransport:
    """Serves canned bodies in order; repeats the last one once exhausted."""

    def __init__(self, bodies: list[dict[str, Any]]) -> None:
        self._bodies = bodies
        self.posts = 0

    async def post(self, path, json, timeout):  # noqa: A002 - httpx kwarg name
        body = self._bodies[min(self.posts, len(self._bodies) - 1)]
        self.posts += 1
        return _WireResponse(body)


class _WireClient:
    """Drives the production wire parser instead of hand-building blocks."""

    def __init__(self, bodies: list[dict[str, Any]]) -> None:
        self._client = OpenAICompatibleClient(
            base_url="http://example", api_key="k", models={"standard": "m"}
        )
        self.transport = _WireTransport(bodies)

    async def complete(self, request: LLMRequest, **_kwargs: Any) -> LLMResponse:
        return await self._client._call_openai(
            request, "m", self.transport, timeout=5.0
        )


class _FakeToolExecutor:
    def __init__(self) -> None:
        self.invoked: list[str] = []

    async def invoke(self, *, agent_id, tool_id, params, **_kwargs):
        self.invoked.append(tool_id)
        return ToolResult(output={"ok": True})


async def _real_pass(
    bodies: list[dict[str, Any]],
    *,
    user_message: str,
    max_iterations: int = 2,
) -> WorkItemAgenticOutcome:
    """One REAL agentic pass, packaged exactly as the production caller does.

    ``WorkItemAgenticExecutor.run`` builds its :class:`WorkItemAgenticOutcome`
    from the loop's ``final_text`` and ``stopped_reason``; both values here come
    off the real loop, so nothing about the cut-off signal is authored by this
    test.
    """
    loop = AgenticLoop(
        llm_client=_WireClient(bodies),
        tool_executor=_FakeToolExecutor(),
        max_iterations=max_iterations,
    )
    result = await loop.run(
        system_prompt="You are Ezri.",
        user_message=user_message,
        tools=_TOOLS,
        context={"agent_id": "counselor_0"},
    )
    return WorkItemAgenticOutcome(
        final_text=result.final_text,
        stopped_reason=result.stopped_reason,
        total_tokens=result.total_tokens,
    )


_CUT_OFF_BODIES = [
    _wire_body(
        text="Opening the document now.",
        tool_name="browser",
        arguments={"action": "state"},
    ),
    _wire_body(
        text="I have the page open and I am lining up the cursor.",
        tool_name="browser",
        arguments={"action": "screenshot"},
    ),
]
_FINISHED_BODIES = [_wire_body(text="Typed Hello World into the document.")]


# ── Test doubles for the collaborators this module reads off the runtime ──


class _Runtime:
    """The two store attributes ``resolve_exhausted_turn`` reads, and nothing else."""

    def __init__(self, *, request_store: Any = None, approval_store: Any = None) -> None:
        self.capability_request_store = request_store
        self.action_approval_store = approval_store


class _RaisingApprovalStore:
    def is_approved_sync(self, *_args, **_kwargs):
        raise RuntimeError("cache read exploded")


class _RaisingRequestStore:
    async def file_request(self, **_kwargs):
        raise RuntimeError("db is down")


class _RecordingReinvoker:
    """Captures every task text handed to it and serves canned outcomes."""

    def __init__(self, outcomes: list[Any]) -> None:
        self._outcomes = list(outcomes)
        self.prompts: list[str] = []

    async def __call__(self, task_text: str) -> Any:
        self.prompts.append(task_text)
        if not self._outcomes:
            return WorkItemAgenticOutcome(
                final_text="still going", stopped_reason="max_iterations"
            )
        return self._outcomes.pop(0)


async def _never_reinvoked(task_text: str) -> Any:  # pragma: no cover - guard
    raise AssertionError(f"re-invocation must not happen; got {task_text!r}")


def _config(*, enabled: bool = True, max_passes: int = 2) -> DmAgenticConfig:
    """The REAL Pydantic config model, so the field names and bounds are real."""
    return DmAgenticConfig(
        enabled=True,
        continue_or_ask_enabled=enabled,
        continue_or_ask_max_passes=max_passes,
    )


async def _request_store(tmp_path: Path, name: str = "cr.db") -> CapabilityRequestStore:
    store = CapabilityRequestStore(db_path=str(tmp_path / name))
    await store.start()
    return store


async def _approvals(tmp_path: Path, name: str = "aa.db") -> ActionApprovalStore:
    store = ActionApprovalStore(db_path=str(tmp_path / name))
    await store.start()
    return store


# ── 1. The real produce -> consume path ────────────────────────────────────


class TestRealProduceConsumePath:
    @pytest.mark.asyncio
    async def test_a_real_cut_off_files_a_real_request_and_reports_it(self, tmp_path):
        """The live BF-697 signature, carried through to the Captain's inbox."""
        # Arrange — the loop really runs out of turns mid-task.
        outcome = await _real_pass(_CUT_OFF_BODIES, user_message=_TASK)
        assert outcome.stopped_reason == "max_iterations"
        assert outcome.final_text == "I have the page open and I am lining up the cursor."
        store = await _request_store(tmp_path)
        try:
            runtime = _Runtime(request_store=store)
            # Act
            text = await resolve_exhausted_turn(
                outcome,
                reinvoke=_never_reinvoked,
                runtime=runtime,
                agent_id="counselor_0",
                base_task_text=_TASK,
                thread_id="thread-1",
                config=_config(),
            )
            # Assert — the partial work survives, verbatim and first.
            assert text.startswith(outcome.final_text)
            assert "step limit" in text
            assert "still open" in text
            # ...and exactly one durable ask reached the queue.
            pending = await store.list_pending()
            assert len(pending) == 1
            assert pending[0].kind == CONTINUE_REQUEST_KIND
            assert pending[0].agent_id == "counselor_0"
            assert f"request {pending[0].id}" in text
        finally:
            await store.stop()

    @pytest.mark.asyncio
    async def test_a_real_standing_rule_reinvokes_a_real_second_loop(self, tmp_path):
        """A live AD-1154 rule turns the cliff into a checkpoint that continues."""
        # Arrange
        outcome = await _real_pass(_CUT_OFF_BODIES, user_message=_TASK)
        approvals = await _approvals(tmp_path)
        store = await _request_store(tmp_path)
        try:
            await approvals.issue_approval(
                "counselor_0",
                CONTINUE_TOOL_ID,
                CONTINUE_ACTION,
                scope_key=CONTINUE_SCOPE_KEY,
                ttl_seconds=3600,
            )
            seen: list[str] = []

            async def _reinvoke(task_text: str) -> Any:
                seen.append(task_text)
                return await _real_pass(_FINISHED_BODIES, user_message=task_text)

            runtime = _Runtime(request_store=store, approval_store=approvals)
            # Act
            text = await resolve_exhausted_turn(
                outcome,
                reinvoke=_reinvoke,
                runtime=runtime,
                agent_id="counselor_0",
                base_task_text=_TASK,
                thread_id="thread-1",
                config=_config(max_passes=2),
            )
            # Assert — the second real loop finished, and its text is the reply.
            assert text == "Typed Hello World into the document."
            assert "step limit" not in text
            assert await store.list_pending() == []
            # The AD-1155 continuation block really reached the second prompt.
            assert len(seen) == 1
            assert seen[0].startswith(_TASK)
            assert _CONTINUATION_HEADER in seen[0]
            assert outcome.final_text in seen[0]
        finally:
            await store.stop()
            await approvals.stop()

    @pytest.mark.asyncio
    async def test_the_filed_request_survives_a_store_restart(self, tmp_path):
        """A cache-only store never runs ``_decode_payload``; this one does."""
        # Arrange
        outcome = await _real_pass(_CUT_OFF_BODIES, user_message=_TASK)
        db = str(tmp_path / "restart.db")
        store = CapabilityRequestStore(db_path=db)
        await store.start()
        try:
            await resolve_exhausted_turn(
                outcome,
                reinvoke=_never_reinvoked,
                runtime=_Runtime(request_store=store),
                agent_id="counselor_0",
                base_task_text=_TASK,
                thread_id="thread-1",
                config=_config(),
            )
        finally:
            await store.stop()
        # Act — a fresh store over the same file.
        reopened = CapabilityRequestStore(db_path=db)
        await reopened.start()
        try:
            pending = await reopened.list_pending()
            # Assert
            assert len(pending) == 1
            assert pending[0].kind == CONTINUE_REQUEST_KIND
            assert pending[0].payload == continue_payload("thread-1")
        finally:
            await reopened.stop()


# ── 2. The gate: off is today ──────────────────────────────────────────────


class TestGate:
    @pytest.mark.asyncio
    async def test_gate_off_returns_the_outcome_text_unchanged(self, tmp_path):
        # Arrange
        outcome = await _real_pass(_CUT_OFF_BODIES, user_message=_TASK)
        store = await _request_store(tmp_path)
        try:
            # Act
            text = await resolve_exhausted_turn(
                outcome,
                reinvoke=_never_reinvoked,
                runtime=_Runtime(request_store=store),
                agent_id="counselor_0",
                base_task_text=_TASK,
                config=_config(enabled=False),
            )
            # Assert — byte-identical to what the caller read before AD-1164.
            assert text == outcome.final_text
            assert await store.list_pending() == []
        finally:
            await store.stop()

    @pytest.mark.asyncio
    async def test_a_truthy_non_bool_flag_does_not_arm(self, tmp_path):
        """A value that skipped Pydantic must not silently arm re-invocation."""
        # Arrange
        outcome = WorkItemAgenticOutcome(
            final_text="partial", stopped_reason="max_iterations"
        )
        store = await _request_store(tmp_path)

        class _Sloppy:
            continue_or_ask_enabled = 1
            continue_or_ask_max_passes = 2

        try:
            # Act
            text = await resolve_exhausted_turn(
                outcome,
                reinvoke=_never_reinvoked,
                runtime=_Runtime(request_store=store),
                agent_id="a",
                base_task_text=_TASK,
                config=_Sloppy(),
            )
            # Assert
            assert text == "partial"
            assert await store.list_pending() == []
        finally:
            await store.stop()

    def test_is_continue_or_ask_armed_is_identity_strict(self):
        # Act / Assert
        assert is_continue_or_ask_armed(_config(enabled=True)) is True
        assert is_continue_or_ask_armed(_config(enabled=False)) is False
        assert is_continue_or_ask_armed(None) is False
        assert is_continue_or_ask_armed(object()) is False

    def test_the_config_ships_off_with_a_cap_of_two(self):
        """Convention #14 plus the AD-1155 shape (which also ships at 2)."""
        # Act
        cfg = DmAgenticConfig()
        # Assert
        assert cfg.continue_or_ask_enabled is False
        assert cfg.continue_or_ask_max_passes == 2

    def test_both_new_config_fields_carry_a_description(self):
        """The generated config reference is only as good as these strings."""
        # Act
        fields = DmAgenticConfig.model_fields
        # Assert
        for name in ("continue_or_ask_enabled", "continue_or_ask_max_passes"):
            assert fields[name].description, name
            assert "AD-1164" in fields[name].description


# ── 3. Stop reasons: only ``max_iterations`` is continued ──────────────────


class TestStopReasons:
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "reason", ["token_budget", "error", "complete", "execution_exception", ""]
    )
    async def test_a_terminal_reason_is_not_reinvoked_and_files_nothing(
        self, tmp_path, reason
    ):
        """AD-1155's exclusions hold here: an operator ceiling, window
        exhaustion a longer prompt makes worse, and the model choosing to stop
        are none of them the failure this AD addresses."""
        # Arrange
        outcome = WorkItemAgenticOutcome(final_text="body", stopped_reason=reason)
        approvals = await _approvals(tmp_path)
        store = await _request_store(tmp_path)
        try:
            await approvals.issue_approval(
                "a",
                CONTINUE_TOOL_ID,
                CONTINUE_ACTION,
                scope_key=CONTINUE_SCOPE_KEY,
                ttl_seconds=3600,
            )
            # Act — a standing rule is live, so only the reason can stop it.
            text = await resolve_exhausted_turn(
                outcome,
                reinvoke=_never_reinvoked,
                runtime=_Runtime(request_store=store, approval_store=approvals),
                agent_id="a",
                base_task_text=_TASK,
                config=_config(),
            )
            # Assert
            assert text == "body"
            assert await store.list_pending() == []
        finally:
            await store.stop()
            await approvals.stop()

    def test_the_reinvokable_set_is_unchanged(self):
        """AD-1164 consults AD-1155's set; it must not widen it."""
        # Act / Assert
        assert _REINVOKABLE_STOPPED_REASONS == {"max_iterations"}
        assert _REINVOKABLE_STOPPED_REASONS <= _STOPPED_REASONS

    @pytest.mark.asyncio
    async def test_an_unknown_reason_is_treated_as_terminal(self, tmp_path):
        """Membership ADMITS; a reason nobody has classified takes today's path."""
        # Arrange
        outcome = WorkItemAgenticOutcome(
            final_text="body", stopped_reason="something_new"
        )
        store = await _request_store(tmp_path)
        try:
            # Act
            text = await resolve_exhausted_turn(
                outcome,
                reinvoke=_never_reinvoked,
                runtime=_Runtime(request_store=store),
                agent_id="a",
                base_task_text=_TASK,
                config=_config(),
            )
            # Assert
            assert text == "body"
            assert await store.list_pending() == []
        finally:
            await store.stop()


# ── 4. The cap ─────────────────────────────────────────────────────────────


class TestPassCap:
    @pytest.mark.asyncio
    async def test_a_cap_of_one_never_reinvokes(self, tmp_path):
        # Arrange
        approvals = await _approvals(tmp_path)
        store = await _request_store(tmp_path)
        try:
            await approvals.issue_approval(
                "a",
                CONTINUE_TOOL_ID,
                CONTINUE_ACTION,
                scope_key=CONTINUE_SCOPE_KEY,
                ttl_seconds=3600,
            )
            # Act
            text = await resolve_exhausted_turn(
                WorkItemAgenticOutcome(
                    final_text="partial", stopped_reason="max_iterations"
                ),
                reinvoke=_never_reinvoked,
                runtime=_Runtime(request_store=store, approval_store=approvals),
                agent_id="a",
                base_task_text=_TASK,
                config=_config(max_passes=1),
            )
            # Assert
            assert text.startswith("partial")
            assert len(await store.list_pending()) == 1
        finally:
            await store.stop()
            await approvals.stop()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("cap", [2, 3, 5])
    async def test_the_cap_bounds_a_perpetually_cut_off_turn(self, tmp_path, cap):
        """A rule that says "keep going" still cannot loop forever."""
        # Arrange — every pass comes back at the step limit.
        approvals = await _approvals(tmp_path, name=f"aa{cap}.db")
        store = await _request_store(tmp_path, name=f"cr{cap}.db")
        try:
            await approvals.issue_approval(
                "a",
                CONTINUE_TOOL_ID,
                CONTINUE_ACTION,
                scope_key=CONTINUE_SCOPE_KEY,
                ttl_seconds=3600,
            )
            reinvoker = _RecordingReinvoker([])
            # Act
            text = await resolve_exhausted_turn(
                WorkItemAgenticOutcome(
                    final_text="pass one", stopped_reason="max_iterations"
                ),
                reinvoke=reinvoker,
                runtime=_Runtime(request_store=store, approval_store=approvals),
                agent_id="a",
                base_task_text=_TASK,
                config=_config(max_passes=cap),
            )
            # Assert — total passes == cap, so re-invocations == cap - 1.
            assert len(reinvoker.prompts) == cap - 1
            assert "step limit" in text
            assert len(await store.list_pending()) == 1
        finally:
            await store.stop()
            await approvals.stop()

    @pytest.mark.asyncio
    async def test_the_continuation_never_stacks_across_passes(self, tmp_path):
        """Each prompt is BASE + one block, rebuilt, never BASE + block + block."""
        # Arrange
        approvals = await _approvals(tmp_path)
        store = await _request_store(tmp_path)
        try:
            await approvals.issue_approval(
                "a",
                CONTINUE_TOOL_ID,
                CONTINUE_ACTION,
                scope_key=CONTINUE_SCOPE_KEY,
                ttl_seconds=3600,
            )
            reinvoker = _RecordingReinvoker([])
            # Act
            await resolve_exhausted_turn(
                WorkItemAgenticOutcome(
                    final_text="pass one", stopped_reason="max_iterations"
                ),
                reinvoke=reinvoker,
                runtime=_Runtime(request_store=store, approval_store=approvals),
                agent_id="a",
                base_task_text=_TASK,
                config=_config(max_passes=4),
            )
            # Assert
            assert len(reinvoker.prompts) == 3
            for prompt in reinvoker.prompts:
                assert prompt.count(_CONTINUATION_HEADER) == 1
                assert prompt.startswith(_TASK)
        finally:
            await store.stop()
            await approvals.stop()

    @pytest.mark.parametrize(
        "value,expected",
        [
            (1, 1),
            (2, 2),
            (5, 5),
            (0, 2),
            (6, 2),
            (-3, 2),
            (True, 2),
            (False, 2),
            (None, 2),
            ("3", 2),
            (2.0, 2),
        ],
    )
    def test_resolve_continue_max_passes_clamps_and_never_raises(self, value, expected):
        # Act / Assert
        assert resolve_continue_max_passes(value) == expected

    def test_the_module_cap_ceiling_matches_the_config_bound(self):
        """A clamp that disagrees with the Pydantic bound is a silent trap."""
        # Act
        field = DmAgenticConfig.model_fields["continue_or_ask_max_passes"]
        bounds = {
            type(m).__name__: getattr(m, "ge", getattr(m, "le", None))
            for m in field.metadata
        }
        # Assert
        assert bounds.get("Le") == _MAX_CONTINUE_PASSES
        assert bounds.get("Ge") == 1


# ── 5. Fail-safe: never fail a run that would otherwise return something ───


class TestFailSafe:
    @pytest.mark.asyncio
    async def test_a_raising_standing_rule_read_degrades_to_ask(self, tmp_path):
        """Failing OPEN here would continue on an unverified rule."""
        # Arrange
        store = await _request_store(tmp_path)
        try:
            # Act
            text = await resolve_exhausted_turn(
                WorkItemAgenticOutcome(
                    final_text="partial", stopped_reason="max_iterations"
                ),
                reinvoke=_never_reinvoked,
                runtime=_Runtime(
                    request_store=store, approval_store=_RaisingApprovalStore()
                ),
                agent_id="a",
                base_task_text=_TASK,
                config=_config(),
            )
            # Assert
            assert text.startswith("partial")
            assert "step limit" in text
            assert len(await store.list_pending()) == 1
        finally:
            await store.stop()

    @pytest.mark.asyncio
    async def test_a_raising_request_store_still_reports_the_partial_work(self):
        """An approval mechanism must never fail a run that had an answer."""
        # Act
        text = await resolve_exhausted_turn(
            WorkItemAgenticOutcome(
                final_text="partial", stopped_reason="max_iterations"
            ),
            reinvoke=_never_reinvoked,
            runtime=_Runtime(request_store=_RaisingRequestStore()),
            agent_id="a",
            base_task_text=_TASK,
            config=_config(),
        )
        # Assert
        assert text.startswith("partial")
        assert text.endswith(_CUT_OFF_TAIL)
        assert "request " not in text

    @pytest.mark.asyncio
    async def test_an_absent_request_store_still_reports_the_partial_work(self):
        # Act
        text = await resolve_exhausted_turn(
            WorkItemAgenticOutcome(
                final_text="partial", stopped_reason="max_iterations"
            ),
            reinvoke=_never_reinvoked,
            runtime=_Runtime(),
            agent_id="a",
            base_task_text=_TASK,
            config=_config(),
        )
        # Assert
        assert text == (
            "partial" + _CUT_OFF_SEPARATOR + _CUT_OFF_LEAD_WITH_WORK + _CUT_OFF_TAIL
        )

    @pytest.mark.asyncio
    async def test_a_raising_reinvocation_reports_the_last_real_outcome(self, tmp_path):
        # Arrange
        approvals = await _approvals(tmp_path)
        store = await _request_store(tmp_path)

        async def _explode(_task_text: str) -> Any:
            raise RuntimeError("the loop blew up")

        try:
            await approvals.issue_approval(
                "a",
                CONTINUE_TOOL_ID,
                CONTINUE_ACTION,
                scope_key=CONTINUE_SCOPE_KEY,
                ttl_seconds=3600,
            )
            # Act
            text = await resolve_exhausted_turn(
                WorkItemAgenticOutcome(
                    final_text="pass one", stopped_reason="max_iterations"
                ),
                reinvoke=_explode,
                runtime=_Runtime(request_store=store, approval_store=approvals),
                agent_id="a",
                base_task_text=_TASK,
                config=_config(max_passes=3),
            )
            # Assert
            assert text.startswith("pass one")
            assert len(await store.list_pending()) == 1
        finally:
            await store.stop()
            await approvals.stop()

    @pytest.mark.asyncio
    async def test_a_reinvocation_returning_none_stops(self, tmp_path):
        # Arrange
        approvals = await _approvals(tmp_path)
        store = await _request_store(tmp_path)

        async def _nothing(_task_text: str) -> Any:
            return None

        try:
            await approvals.issue_approval(
                "a",
                CONTINUE_TOOL_ID,
                CONTINUE_ACTION,
                scope_key=CONTINUE_SCOPE_KEY,
                ttl_seconds=3600,
            )
            # Act
            text = await resolve_exhausted_turn(
                WorkItemAgenticOutcome(
                    final_text="pass one", stopped_reason="max_iterations"
                ),
                reinvoke=_nothing,
                runtime=_Runtime(request_store=store, approval_store=approvals),
                agent_id="a",
                base_task_text=_TASK,
                config=_config(max_passes=3),
            )
            # Assert
            assert text.startswith("pass one")
            assert len(await store.list_pending()) == 1
        finally:
            await store.stop()
            await approvals.stop()

    @pytest.mark.asyncio
    async def test_an_expired_standing_rule_does_not_continue(self, tmp_path):
        """A TTL that has lapsed asks again; that is the point of the TTL."""
        # Arrange
        approvals = await _approvals(tmp_path)
        store = await _request_store(tmp_path)
        try:
            await approvals.issue_approval(
                "a",
                CONTINUE_TOOL_ID,
                CONTINUE_ACTION,
                scope_key=CONTINUE_SCOPE_KEY,
                ttl_seconds=-1,
            )
            # Act
            text = await resolve_exhausted_turn(
                WorkItemAgenticOutcome(
                    final_text="partial", stopped_reason="max_iterations"
                ),
                reinvoke=_never_reinvoked,
                runtime=_Runtime(request_store=store, approval_store=approvals),
                agent_id="a",
                base_task_text=_TASK,
                config=_config(),
            )
            # Assert
            assert "step limit" in text
            assert len(await store.list_pending()) == 1
        finally:
            await store.stop()
            await approvals.stop()

    @pytest.mark.asyncio
    async def test_another_agents_rule_does_not_continue_this_agent(self, tmp_path):
        """There is no wildcard; the rule is scoped to one agent."""
        # Arrange
        approvals = await _approvals(tmp_path)
        store = await _request_store(tmp_path)
        try:
            await approvals.issue_approval(
                "someone-else",
                CONTINUE_TOOL_ID,
                CONTINUE_ACTION,
                scope_key=CONTINUE_SCOPE_KEY,
                ttl_seconds=3600,
            )
            # Act
            text = await resolve_exhausted_turn(
                WorkItemAgenticOutcome(
                    final_text="partial", stopped_reason="max_iterations"
                ),
                reinvoke=_never_reinvoked,
                runtime=_Runtime(request_store=store, approval_store=approvals),
                agent_id="a",
                base_task_text=_TASK,
                config=_config(),
            )
            # Assert
            assert "step limit" in text
            assert len(await store.list_pending()) == 1
        finally:
            await store.stop()
            await approvals.stop()


# ── 6. The filed request carries enough context to decide ──────────────────


class TestFiledRequest:
    @pytest.mark.asyncio
    async def test_the_card_fields_the_panel_renders_are_populated(self, tmp_path):
        """``CapabilityRequestPanel`` renders kind / target / rationale only."""
        # Arrange
        store = await _request_store(tmp_path)
        try:
            # Act
            await resolve_exhausted_turn(
                WorkItemAgenticOutcome(
                    final_text="partial", stopped_reason="max_iterations"
                ),
                reinvoke=_never_reinvoked,
                runtime=_Runtime(request_store=store),
                agent_id="counselor_0",
                base_task_text=_TASK,
                thread_id="thread-1",
                config=_config(),
            )
            # Assert
            req = (await store.list_pending())[0]
            assert req.kind == CONTINUE_REQUEST_KIND
            assert _TASK in req.target
            assert req.target.startswith("continue: ")
            assert "step limit" in req.rationale
            assert "1 pass" in req.rationale
            assert req.status == "pending"
            assert req.work_item_id is None
        finally:
            await store.stop()

    @pytest.mark.asyncio
    async def test_the_rationale_reports_the_pass_count(self, tmp_path):
        # Arrange
        approvals = await _approvals(tmp_path)
        store = await _request_store(tmp_path)
        try:
            await approvals.issue_approval(
                "a",
                CONTINUE_TOOL_ID,
                CONTINUE_ACTION,
                scope_key=CONTINUE_SCOPE_KEY,
                ttl_seconds=3600,
            )
            # Act
            await resolve_exhausted_turn(
                WorkItemAgenticOutcome(
                    final_text="partial", stopped_reason="max_iterations"
                ),
                reinvoke=_RecordingReinvoker([]),
                runtime=_Runtime(request_store=store, approval_store=approvals),
                agent_id="a",
                base_task_text=_TASK,
                config=_config(max_passes=3),
            )
            # Assert
            assert "3 pass" in (await store.list_pending())[0].rationale
        finally:
            await store.stop()
            await approvals.stop()

    @pytest.mark.asyncio
    async def test_a_long_task_is_excerpted_into_the_target(self, tmp_path):
        # Arrange
        store = await _request_store(tmp_path)
        long_task = "Summarise " + ("the quarterly report " * 40)
        try:
            # Act
            await resolve_exhausted_turn(
                WorkItemAgenticOutcome(
                    final_text="partial", stopped_reason="max_iterations"
                ),
                reinvoke=_never_reinvoked,
                runtime=_Runtime(request_store=store),
                agent_id="a",
                base_task_text=long_task,
                config=_config(),
            )
            # Assert
            target = (await store.list_pending())[0].target
            assert len(target) <= len("continue: ") + 120
            assert target.endswith("\u2026")
            assert "\n" not in target
        finally:
            await store.stop()

    def test_the_payload_passes_the_ad1154_validator(self):
        """The read side re-validates, so a shape it rejects is not durable."""
        # Act
        payload = continue_payload("thread-1")
        # Assert
        assert validate_action_payload(payload) == payload
        assert payload["tool_id"] == CONTINUE_TOOL_ID
        assert payload["action"] == CONTINUE_ACTION
        assert payload["scope_key"] == CONTINUE_SCOPE_KEY
        assert payload["session_id"] is None

    @pytest.mark.parametrize("thread_id", [None, 123, "", "x" * 400])
    def test_the_payload_survives_a_malformed_thread_id(self, thread_id):
        # Act
        payload = continue_payload(thread_id)
        # Assert
        assert validate_action_payload(payload) == payload
        assert len(payload["thread_id"]) <= _THREAD_ID_MAX

    def test_the_thread_id_bound_matches_the_store(self):
        """A drift guard: the module duplicates this bound deliberately."""
        # Act
        from probos.cognitive import continue_or_ask

        # Assert
        assert continue_or_ask._THREAD_ID_MAX == _THREAD_ID_MAX

    @pytest.mark.asyncio
    async def test_exactly_one_request_is_filed_per_cut_off_turn(self, tmp_path):
        """Not one per pass — the ask is filed once, at the end."""
        # Arrange
        approvals = await _approvals(tmp_path)
        store = await _request_store(tmp_path)
        try:
            await approvals.issue_approval(
                "a",
                CONTINUE_TOOL_ID,
                CONTINUE_ACTION,
                scope_key=CONTINUE_SCOPE_KEY,
                ttl_seconds=3600,
            )
            # Act
            await resolve_exhausted_turn(
                WorkItemAgenticOutcome(
                    final_text="partial", stopped_reason="max_iterations"
                ),
                reinvoke=_RecordingReinvoker([]),
                runtime=_Runtime(request_store=store, approval_store=approvals),
                agent_id="a",
                base_task_text=_TASK,
                config=_config(max_passes=5),
            )
            # Assert
            assert len(await store.list_pending()) == 1
        finally:
            await store.stop()
            await approvals.stop()

    def test_the_hxi_panel_renders_a_new_kind_with_no_ui_change(self):
        """AD-1154's claim, re-verified rather than assumed."""
        # Act
        source = (
            _REPO_ROOT
            / "ui"
            / "src"
            / "components"
            / "capability"
            / "CapabilityRequestPanel.tsx"
        ).read_text(encoding="utf-8")
        # Assert — an untyped kind, rendered verbatim, with a neutral fallback.
        assert "kind: string;" in source
        assert "{req.kind}" in source
        assert "DEPARTMENT_COLORS[key] || DEFAULT_DEPARTMENT_COLOR" in source
        assert CONTINUE_REQUEST_KIND not in source


# ── 7. The honest statement ────────────────────────────────────────────────


class TestHonestStatement:
    @pytest.mark.parametrize(
        "text",
        [
            _CUT_OFF_LEAD_WITH_WORK + _CUT_OFF_TAIL,
            _CUT_OFF_LEAD_NO_WORK + _CUT_OFF_TAIL,
            _CUT_OFF_LEAD_WITH_WORK
            + _CUT_OFF_TAIL_WITH_REQUEST.format(request_id="abc-123"),
            _CUT_OFF_LEAD_NO_WORK
            + _CUT_OFF_TAIL_WITH_REQUEST.format(request_id="abc-123"),
        ],
    )
    def test_the_cut_off_text_does_not_read_as_a_capability_gap(self, text):
        """Checked against the REAL regex — ``lack`` is a bare substring in it."""
        # Act / Assert
        assert _CAPABILITY_GAP_RE.search(text) is None

    @pytest.mark.parametrize(
        "text",
        [
            _CUT_OFF_LEAD_WITH_WORK + _CUT_OFF_TAIL,
            _CUT_OFF_LEAD_NO_WORK + _CUT_OFF_TAIL,
            _CUT_OFF_LEAD_WITH_WORK
            + _CUT_OFF_TAIL_WITH_REQUEST.format(request_id="abc-123"),
            _CUT_OFF_LEAD_NO_WORK
            + _CUT_OFF_TAIL_WITH_REQUEST.format(request_id="abc-123"),
        ],
    )
    def test_the_cut_off_text_does_not_read_as_a_completion(self, text):
        """The whole point is that a cut-off turn is distinguishable from a done one."""
        # Act
        lowered = text.lower()
        # Assert
        for claim in ("all done", "task complete", "finished the", "completed the"):
            assert claim not in lowered
        assert "step limit" in lowered
        assert "still open" in lowered

    def test_the_no_work_lead_does_not_claim_there_is_work_above_it(self):
        """A text-less run must not say "the work above is partial" above nothing."""
        # Act / Assert
        assert "above" not in _CUT_OFF_LEAD_NO_WORK
        assert "above" in _CUT_OFF_LEAD_WITH_WORK

    @pytest.mark.asyncio
    async def test_the_partial_work_is_preserved_verbatim_and_first(self, tmp_path):
        # Arrange
        store = await _request_store(tmp_path)
        partial = "Line one.\nLine two, mid-sentence and"
        try:
            # Act
            text = await resolve_exhausted_turn(
                WorkItemAgenticOutcome(
                    final_text=partial, stopped_reason="max_iterations"
                ),
                reinvoke=_never_reinvoked,
                runtime=_Runtime(request_store=store),
                agent_id="a",
                base_task_text=_TASK,
                config=_config(),
            )
            # Assert
            assert text.startswith(partial)
            assert text[len(partial):].startswith(_CUT_OFF_SEPARATOR)
        finally:
            await store.stop()

    @pytest.mark.asyncio
    async def test_an_empty_partial_still_states_that_it_stopped(self):
        """A silent tool-only run must not come back as an empty reply."""
        # Act
        text = await resolve_exhausted_turn(
            WorkItemAgenticOutcome(final_text="", stopped_reason="max_iterations"),
            reinvoke=_never_reinvoked,
            runtime=_Runtime(),
            agent_id="a",
            base_task_text=_TASK,
            config=_config(),
        )
        # Assert — no orphan horizontal rule above nothing, and no false claim
        # that there is partial work to read.
        assert text == _CUT_OFF_LEAD_NO_WORK + _CUT_OFF_TAIL
        assert not text.startswith("\n")

    @pytest.mark.asyncio
    async def test_a_non_string_final_text_degrades_to_the_note(self):
        # Act
        text = await resolve_exhausted_turn(
            WorkItemAgenticOutcome(
                final_text=None, stopped_reason="max_iterations"  # type: ignore[arg-type]
            ),
            reinvoke=_never_reinvoked,
            runtime=_Runtime(),
            agent_id="a",
            base_task_text=_TASK,
            config=_config(),
        )
        # Assert
        assert text == _CUT_OFF_LEAD_NO_WORK + _CUT_OFF_TAIL


# ── 8. Reuse, asserted rather than claimed ─────────────────────────────────


class TestReuse:
    @pytest.mark.asyncio
    async def test_the_continuation_block_is_ad1155s_renderer(self, tmp_path):
        """Not a private copy: the exact output of ``_render_continuation``."""
        # Arrange
        approvals = await _approvals(tmp_path)
        store = await _request_store(tmp_path)
        try:
            await approvals.issue_approval(
                "a",
                CONTINUE_TOOL_ID,
                CONTINUE_ACTION,
                scope_key=CONTINUE_SCOPE_KEY,
                ttl_seconds=3600,
            )
            reinvoker = _RecordingReinvoker(
                [WorkItemAgenticOutcome(final_text="done", stopped_reason="complete")]
            )
            # Act
            await resolve_exhausted_turn(
                WorkItemAgenticOutcome(
                    final_text="pass one", stopped_reason="max_iterations"
                ),
                reinvoke=reinvoker,
                runtime=_Runtime(request_store=store, approval_store=approvals),
                agent_id="a",
                base_task_text=_TASK,
                config=_config(max_passes=2),
            )
            # Assert
            expected = _render_continuation(
                previous_output="pass one",
                todo_labels=None,
                completion_marker=None,
            )
            assert reinvoker.prompts == [_TASK + expected]
        finally:
            await store.stop()
            await approvals.stop()

    def test_no_second_standing_rule_store_was_built(self):
        """AD-1154's store is the only TTL-bounded standing-rule mechanism."""
        # Act
        source = (
            _REPO_ROOT / "src" / "probos" / "cognitive" / "continue_or_ask.py"
        ).read_text(encoding="utf-8")
        # Assert
        assert "CREATE TABLE" not in source
        assert "sqlite" not in source.lower()
        assert "aiosqlite" not in source

    @pytest.mark.asyncio
    async def test_a_failing_continuation_render_stops_rather_than_raising(
        self, tmp_path, monkeypatch
    ):
        # Arrange
        from probos.cognitive import continue_or_ask as module

        def _boom(**_kwargs):
            raise RuntimeError("render exploded")

        monkeypatch.setattr(module, "_render_continuation", _boom)
        approvals = await _approvals(tmp_path)
        store = await _request_store(tmp_path)
        try:
            await approvals.issue_approval(
                "a",
                CONTINUE_TOOL_ID,
                CONTINUE_ACTION,
                scope_key=CONTINUE_SCOPE_KEY,
                ttl_seconds=3600,
            )
            # Act
            text = await resolve_exhausted_turn(
                WorkItemAgenticOutcome(
                    final_text="partial", stopped_reason="max_iterations"
                ),
                reinvoke=_never_reinvoked,
                runtime=_Runtime(request_store=store, approval_store=approvals),
                agent_id="a",
                base_task_text=_TASK,
                config=_config(max_passes=3),
            )
            # Assert
            assert text.startswith("partial")
            assert len(await store.list_pending()) == 1
        finally:
            await store.stop()
            await approvals.stop()


# ── 9. The production caller ───────────────────────────────────────────────


class TestConversationalSeam:
    def test_the_cognitive_agent_gates_and_calls_the_resolver(self):
        """Name the real caller. This is it, asserted at the source."""
        # Act
        source = (
            _REPO_ROOT / "src" / "probos" / "cognitive" / "cognitive_agent.py"
        ).read_text(encoding="utf-8")
        # Assert
        assert 'getattr(cfg, "continue_or_ask_enabled", False) is True' in source
        assert (
            "from probos.cognitive.continue_or_ask import resolve_exhausted_turn"
            in source
        )
        assert "reinvoke=_run_pass" in source

    def test_the_reinvocation_reuses_one_governed_executor_call(self):
        """Every pass goes back through ``WorkItemAgenticExecutor.run``, so
        grants, restrictions and trust are re-resolved each time."""
        # Act
        source = (
            _REPO_ROOT / "src" / "probos" / "cognitive" / "cognitive_agent.py"
        ).read_text(encoding="utf-8")
        # Assert
        assert "async def _run_pass(task_text: str) -> Any:" in source
        assert "outcome = await _run_pass(user_message)" in source

    @pytest.mark.asyncio
    async def test_the_resolver_logs_why_it_stopped(self, tmp_path, caplog):
        """A silent stop is what cost two diagnostic cycles on AD-1163."""
        # Arrange
        store = await _request_store(tmp_path)
        try:
            # Act
            with caplog.at_level(logging.INFO, logger="probos.cognitive.continue_or_ask"):
                await resolve_exhausted_turn(
                    WorkItemAgenticOutcome(
                        final_text="partial", stopped_reason="max_iterations"
                    ),
                    reinvoke=_never_reinvoked,
                    runtime=_Runtime(request_store=store),
                    agent_id="counselor_0",
                    base_task_text=_TASK,
                    config=_config(),
                )
            # Assert
            messages = [r.getMessage() for r in caplog.records]
            assert any("no standing rule covers continuation" in m for m in messages)
            assert any("filed continue request" in m for m in messages)
        finally:
            await store.stop()


# ── 10. BF-709: the card title is the ask, not the scaffolding ─────────────


# The exact live shape, from the seven requests pending on the reference vessel:
# the AD-1055 visual-context block and the BF-294 confabulation guard, prepended
# by the runtime, ahead of the four words the Captain actually typed.
_RAW_ASK = "Type Hello World into the document I have open"
_SCAFFOLD = (
    "--- Current Visual Context ---\n"
    "Camera not active or no frames described yet. Do NOT describe what you "
    "cannot see.\n"
    "--- End Visual Context ---\n\n"
)
_ASSEMBLED = _SCAFFOLD + _RAW_ASK


class _FaultRuntime(_Runtime):
    """``_Runtime`` plus the AD-1169 store, which only the defect path reads."""

    def __init__(self, *, request_store: Any = None, fault_store: Any = None) -> None:
        super().__init__(request_store=request_store)
        self.fault_report_store = fault_store


def _defect_outcome() -> Any:
    """The BF-701 shape, built from the REAL tool-call dataclasses.

    Two calls to the same tool, both answered with the same error, which is what
    ``detect_tool_defect`` needs to route the turn down the fault path instead of
    filing a continue request.
    """

    class _Outcome:
        final_text = "partial"
        stopped_reason = "max_iterations"
        tool_calls = [
            ToolCallRequest(name="browser", arguments={}, id="c1"),
            ToolCallRequest(name="browser", arguments={}, id="c2"),
        ]
        tool_results = [
            ToolCallResult(id="c1", output="unknown browser action: 'key_type'", is_error=True),
            ToolCallResult(id="c2", output="unknown browser action: 'key_type'", is_error=True),
        ]

    return _Outcome()


async def _target_for(tmp_path: Path, name: str, **kwargs: Any) -> str:
    """Drive the production entry point and hand back the filed card's title."""
    store = await _request_store(tmp_path, name)
    try:
        await resolve_exhausted_turn(
            WorkItemAgenticOutcome(
                final_text="partial", stopped_reason="max_iterations"
            ),
            reinvoke=_never_reinvoked,
            runtime=_Runtime(request_store=store),
            agent_id="counselor_0",
            base_task_text=_ASSEMBLED,
            thread_id="thread-1",
            config=_config(),
            **kwargs,
        )
        return (await store.list_pending())[0].target
    finally:
        await store.stop()


class TestDisplayTextIsTheAsk:
    @pytest.mark.asyncio
    async def test_a_supplied_display_text_titles_the_card_with_the_raw_ask(
        self, tmp_path
    ):
        """The defect, inverted: the Captain reads what they asked for."""
        # Act
        target = await _target_for(
            tmp_path, "supplied.db", display_task_text=_RAW_ASK
        )
        # Assert — the ask is there in full, and none of the scaffolding is.
        assert target == f"continue: {_RAW_ASK}"
        assert "Visual Context" not in target
        assert "Do NOT describe" not in target

    @pytest.mark.asyncio
    async def test_omitting_the_display_text_is_byte_identical_to_today(
        self, tmp_path
    ):
        """The default-preserving claim, proved by a caller that does not pass one."""
        # Act — the pre-BF-709 call, argument for argument.
        target = await _target_for(tmp_path, "omitted.db")
        # Assert — exactly what the assembled prompt excerpted to before.
        assert target == f"continue: {_task_excerpt(_ASSEMBLED)}"
        assert "Visual Context" in target

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "blank", ["", "   ", "\n\t ", "\u00a0"], ids=["empty", "spaces", "mixed", "nbsp"]
    )
    async def test_a_blank_display_text_falls_back_rather_than_emptying_the_title(
        self, tmp_path, blank
    ):
        """A whitespace-only message is not an ask, and must not become the title.

        ``or`` would not do: every value here except ``""`` is truthy, so a
        truthiness fallback would excerpt whitespace to ``""`` and degrade the
        card to the bare ``"continue"`` with no context at all.
        """
        # Act
        target = await _target_for(
            tmp_path, "blank.db", display_task_text=blank
        )
        # Assert
        assert target == f"continue: {_task_excerpt(_ASSEMBLED)}"
        assert target != "continue"
        assert target != "continue: "

    @pytest.mark.asyncio
    async def test_reinvocation_still_receives_the_full_assembled_prompt(
        self, tmp_path
    ):
        """THE regression guard. Fixing the title by changing ``base_task_text``
        would pass every assertion above and silently strip working memory,
        episodic recall and session history off every continued pass.

        A continued turn must be handed the SAME prompt the first pass got,
        plus AD-1155's continuation block — never the four words on the card.
        """
        # Arrange — a live standing rule, so re-invocation actually happens.
        approvals = await _approvals(tmp_path)
        store = await _request_store(tmp_path)
        try:
            await approvals.issue_approval(
                "counselor_0",
                CONTINUE_TOOL_ID,
                CONTINUE_ACTION,
                scope_key=CONTINUE_SCOPE_KEY,
                ttl_seconds=3600,
            )
            reinvoker = _RecordingReinvoker(
                [WorkItemAgenticOutcome(final_text="done", stopped_reason="complete")]
            )
            # Act — with a display text supplied, which is the whole point.
            await resolve_exhausted_turn(
                WorkItemAgenticOutcome(
                    final_text="pass one", stopped_reason="max_iterations"
                ),
                reinvoke=reinvoker,
                runtime=_Runtime(request_store=store, approval_store=approvals),
                agent_id="counselor_0",
                base_task_text=_ASSEMBLED,
                display_task_text=_RAW_ASK,
                config=_config(max_passes=2),
            )
            # Assert — the exact prompt, composed from the ASSEMBLED base.
            expected = _render_continuation(
                previous_output="pass one",
                todo_labels=None,
                completion_marker=None,
            )
            assert reinvoker.prompts == [_ASSEMBLED + expected]
            # Said the other way round, so a future refactor cannot pass by
            # accident: the scaffolding survived and the raw ask alone did not
            # become the prompt.
            assert _SCAFFOLD in reinvoker.prompts[0]
            assert reinvoker.prompts[0] != _RAW_ASK + expected
        finally:
            await store.stop()
            await approvals.stop()

    @pytest.mark.asyncio
    async def test_the_fault_report_records_the_raw_ask_as_what_was_attempted(
        self, tmp_path
    ):
        """AD-1170's ``attempted`` is Captain-facing too, so it gets the ask."""
        # Arrange
        faults = FaultReportStore()
        store = await _request_store(tmp_path)
        try:
            # Act
            text = await resolve_exhausted_turn(
                _defect_outcome(),
                reinvoke=_never_reinvoked,
                runtime=_FaultRuntime(request_store=store, fault_store=faults),
                agent_id="counselor_0",
                base_task_text=_ASSEMBLED,
                display_task_text=_RAW_ASK,
                thread_id="thread-1",
                config=_config(),
            )
            # Assert — the defect path really ran...
            assert "fault report" in text
            open_faults = faults.list_open()
            assert len(open_faults) == 1
            # ...and it recorded the ask, not the prompt.
            assert open_faults[0].attempted == _RAW_ASK
            assert "Visual Context" not in open_faults[0].attempted
        finally:
            await store.stop()

    @pytest.mark.asyncio
    async def test_the_fault_report_falls_back_when_no_display_text_is_given(
        self, tmp_path
    ):
        """Same default-preserving guarantee on the second Captain-facing site."""
        # Arrange
        faults = FaultReportStore()
        store = await _request_store(tmp_path)
        try:
            # Act
            await resolve_exhausted_turn(
                _defect_outcome(),
                reinvoke=_never_reinvoked,
                runtime=_FaultRuntime(request_store=store, fault_store=faults),
                agent_id="counselor_0",
                base_task_text=_ASSEMBLED,
                thread_id="thread-1",
                config=_config(),
            )
            # Assert
            assert faults.list_open()[0].attempted == _ASSEMBLED
        finally:
            await store.stop()

    @pytest.mark.parametrize(
        "display",
        [None, 123, b"bytes", "", "   ", object()],
        ids=["none", "int", "bytes", "empty", "spaces", "object"],
    )
    def test_the_resolver_falls_back_for_anything_that_is_not_a_real_ask(
        self, display
    ):
        """Boundary cases on the new helper. ``type(...) is str`` rather than
        ``isinstance`` follows the module's existing idiom."""
        # Act / Assert
        assert _display_task_text(display, _ASSEMBLED) == _ASSEMBLED

    def test_the_resolver_prefers_a_real_ask(self):
        # Act / Assert
        assert _display_task_text(_RAW_ASK, _ASSEMBLED) == _RAW_ASK


class TestBothCaptainFacingPathsAgree:
    """AD-1201 put continue requests in front of the Captain and AD-1165 puts
    promoted turns on the board. Until BF-709 the two read differently from the
    SAME turn; these assert they now derive from one helper on one observation.
    """

    @pytest.mark.asyncio
    async def test_one_observation_yields_the_same_text_on_both_surfaces(
        self, tmp_path
    ):
        # Arrange — the observation the DM router builds (``captain_message`` is
        # set there precisely so downstream consumers can recover the raw ask).
        observation = {"params": {"captain_message": _RAW_ASK, "text": _RAW_ASK}}
        derived = _promotion_request_text(observation, _ASSEMBLED)
        # Act
        target = await _target_for(
            tmp_path, "agree.db", display_task_text=derived
        )
        # Assert — the promotion path's string and the card title are one string.
        assert derived == _RAW_ASK
        assert target == f"continue: {derived}"

    def test_the_helper_still_falls_back_to_the_assembled_prompt(self):
        """No ``captain_message`` anywhere ⇒ today's behaviour on both paths."""
        # Act / Assert
        assert _promotion_request_text({}, _ASSEMBLED) == _ASSEMBLED

    def test_the_arming_site_passes_the_shared_helper_as_the_display_text(self):
        """The seam. Without this, every test above proves the module works and
        none of them proves anything calls it that way — the exact failure this
        suite's own preamble warns about."""
        # Act
        source = (
            _REPO_ROOT / "src" / "probos" / "cognitive" / "cognitive_agent.py"
        ).read_text(encoding="utf-8")
        # Assert — the display text is the shared helper...
        assert "display_task_text=_promotion_request_text(" in source
        # ...and the base is STILL the assembled prompt. If this line ever
        # changes, continuation silently loses its context.
        assert "base_task_text=user_message," in source

    def test_the_module_does_not_import_the_arming_sites_helper(self):
        """``continue_or_ask`` is imported lazily BY ``cognitive_agent``;
        reaching back for ``_promotion_request_text`` would invert that."""
        # Act
        source = (
            _REPO_ROOT / "src" / "probos" / "cognitive" / "continue_or_ask.py"
        ).read_text(encoding="utf-8")
        # Assert
        assert "import _promotion_request_text" not in source
        assert "from probos.cognitive.cognitive_agent import" not in source

    def test_reinvocation_is_never_handed_the_display_text(self):
        """Asserted at the source as well as behaviourally, because this is the
        one line whose regression no title assertion could catch."""
        # Act
        source = (
            _REPO_ROOT / "src" / "probos" / "cognitive" / "continue_or_ask.py"
        ).read_text(encoding="utf-8")
        # Assert
        assert "await reinvoke(base_task_text + block)" in source
        assert "reinvoke(display_task_text" not in source
