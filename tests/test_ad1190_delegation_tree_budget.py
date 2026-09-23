"""AD-1190 (#1127): one aggregate budget across a delegation tree.

Real seam throughout: root ``WorkItemAgenticExecutor`` -> ``AgenticLoop`` ->
``DelegateTaskTool`` -> nested executor. The fixture copies the minimal shape of
``tests/test_ad1191_delegation_wire.py`` rather than importing it.
"""

from __future__ import annotations

import ast
import asyncio
import contextlib
import copy
import hashlib
import inspect
import json
import logging
from collections.abc import Callable
from dataclasses import MISSING, dataclass, field, fields
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import ValidationError

from probos.cognitive.agentic_dispatch import WorkItemAgenticExecutor, WorkItemAgenticOutcome
from probos.cognitive.crew_verifier import (
    _ProjectedToolDefinition,
    _session_correction_runtime,
    _SessionAgenticToolsConfig,
)
from probos.cognitive.swe_harness import agentic_loop as agentic_loop_module
from probos.cognitive.swe_harness.agentic_loop import (
    TOKEN_SOURCE_ESTIMATED,
    TOKEN_SOURCE_MEASURED,
    AgenticLoop,
)
from probos.cognitive.swe_harness.tool_call import TextBlock, ToolCallRequest, ToolUseBlock
from probos.config import AgenticLoopConfig, AgenticToolsConfig, ExecutionConfig, load_config
from probos.consensus.trust import TrustNetwork
from probos.crew_profile import CallsignRegistry
from probos.tools.delegate_task_tool import DelegateTaskTool
from probos.tools.delegation_budget import (
    DELEGATION_TREE_BUDGET_KEY,
    MIN_DELEGATION_TOKEN_GRANT,
    DelegationTreeBudget,
    TreeCeilings,
    TreeGrant,
    TreeRefusal,
    read_tree_ceilings,
)
from probos.tools.delegation_evidence import DelegatedToolResult
from probos.tools.permissions import ToolPermissionStore
from probos.tools.protocol import ToolResult, ToolType
from probos.tools.registry import ToolRegistry
from probos.types import LLMResponse

_DELEGATED_KEYS = {"delegated", "to", "result", "stopped_reason"}
_BUDGET_LOGGER = "probos.tools.delegation_budget"
_TOOL_LOGGER = "probos.tools.delegate_task_tool"


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

    def get(self, agent_id: str) -> _Agent | None:
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

    async def write(
        self, content_hash: str, blob: bytes, mime: str, *, origin: str = "chat_attachment",
    ) -> Path:
        assert hashlib.sha256(blob).hexdigest() == content_hash
        self.blobs[content_hash] = blob
        return Path(content_hash)


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


def _delegate(call_id: str, task: str = "child task") -> ToolUseBlock:
    return _use("delegate_task", {"task": task, "to": "Child"}, call_id)


class _LLM:
    def __init__(self, responses: list[_Response]) -> None:
        self.responses = list(responses)
        self.requests: list[Any] = []

    async def complete(self, request: Any, **kwargs: Any) -> _Response:
        self.requests.append(copy.deepcopy(request))
        assert self.responses, "fixture exhausted: more model calls than the script allows"
        return self.responses.pop(0)


def _roles(llm: _LLM) -> list[str]:
    """Which agent each recorded request came from, by its system prompt."""
    roles = []
    for request in llm.requests:
        prompt = request.system_prompt or ""
        if "grandchild instructions" in prompt:
            roles.append("grandchild")
        elif "child instructions" in prompt:
            roles.append("child")
        elif "parent instructions" in prompt:
            roles.append("parent")
        else:
            roles.append("unknown")
    return roles


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


class _ProbeTool:
    """Records every invocation context it receives and returns ``ok``."""

    tool_id = "probe"
    name = "Probe"
    tool_type = ToolType.UTILITY_AGENT
    description = "Test probe that records its invocation context."
    input_schema: dict[str, Any] = {"type": "object", "properties": {}}
    output_schema: dict[str, Any] = {"type": "object"}

    def __init__(self) -> None:
        self.contexts: list[dict[str, Any]] = []

    async def invoke(
        self, params: dict[str, Any], context: dict[str, Any] | None = None,
    ) -> ToolResult:
        self.contexts.append(dict(context or {}))
        return ToolResult(output="ok")


def _runtime(
    tmp_path: Path, llm: Any, *, max_depth: int = 1, max_iterations: int = 5, **tree: Any,
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
        mcp_workbench=None, attachment_store=_Attachments(), artifact_store=None,
        cognitive_skill_catalog=None, emit_event=None,
        config=SimpleNamespace(
            execution=ExecutionConfig(enabled=False, scratch_dir=str(tmp_path / "scratch")),
            mcp=None,
            agentic_tools=AgenticToolsConfig(
                delegation_enabled=True, delegation_max_depth=max_depth,
                delegation_max_iterations=max_iterations, **tree,
            ),
            agentic_loop=AgenticLoopConfig(),
        ),
    )
    runtime.delegator = _RecordingDelegate(
        runtime=runtime, llm_client=llm, max_depth=max_depth,
        max_iterations=max_iterations, tier="standard",
    )
    registry.register(runtime.delegator, provider="local-test")
    runtime.probe = _ProbeTool()
    registry.register(runtime.probe, provider="local-test")
    return runtime


async def _parent(runtime: SimpleNamespace, llm: Any) -> WorkItemAgenticOutcome:
    return await WorkItemAgenticExecutor(llm_client=llm).run(
        agent_id="parent", instructions="parent instructions", task_text="delegate the work",
        runtime=runtime, thread_id="thread", max_iterations=6,
    )


def _parent_tool_content(request: Any, *, structured: bool, call_id: str) -> str:
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


def _children_refusal(ceiling: int) -> dict[str, Any]:
    return {
        "delegated": False, "reason": "delegation_tree_limit_reached",
        "tree_limit": "children", "ceiling": ceiling, "used": ceiling, "required": 1,
    }


def _refusal(limit: str, *, ceiling: int, used: int, required: int) -> dict[str, Any]:
    return {
        "delegated": False, "reason": "delegation_tree_limit_reached",
        "tree_limit": limit, "ceiling": ceiling, "used": used, "required": required,
    }


def _admit(
    budget: DelegationTreeBudget, *, child_depth: int = 1, max_depth: int = 1, cap: int = 5,
) -> TreeGrant | TreeRefusal:
    return budget.admit(child_depth=child_depth, max_depth=max_depth, per_child_iterations=cap)


def _budget_warnings(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [
        record for record in caplog.records
        if record.name == _BUDGET_LOGGER and record.levelno >= logging.WARNING
    ]


# ── G.M1: real seam, root executor -> AgenticLoop -> DelegateTaskTool -> nested executor ──


async def test_run_three_sibling_delegations_with_children_ceiling_two_refuses_third_typed(
    tmp_path: Path,
) -> None:
    llm = _LLM([
        _calls(_delegate("d1", "task one"), _delegate("d2", "task two"), _delegate("d3", "task three")),
        _text("child answer one"),
        _text("child answer two"),
        _text("parent completed"),
    ])
    runtime = _runtime(tmp_path, llm, delegation_tree_max_children=2)

    outcome = await _parent(runtime, llm)

    assert not llm.responses
    assert _roles(llm) == ["parent", "child", "child", "parent"]
    assert outcome.final_text == "parent completed"
    contexts = runtime.delegator.contexts
    assert len(contexts) == 3
    budget = contexts[0][DELEGATION_TREE_BUDGET_KEY]
    assert type(budget) is DelegationTreeBudget
    assert all(ctx[DELEGATION_TREE_BUDGET_KEY] is budget for ctx in contexts)
    first, second, third = runtime.delegator.results
    assert [first.output["result"], second.output["result"]] == [
        "child answer one", "child answer two",
    ]
    assert third.output == _children_refusal(2)
    assert third.error is None and third.metadata == {}
    assert third.evidence.status == "not_started"
    usage = budget.usage()
    assert (usage.children_admitted, usage.in_flight) == (2, 0)
    # The refusal is what the parent reads on its next request.
    content = _parent_tool_content(llm.requests[-1], structured=False, call_id="d3")
    line, legacy = content.split("\n", 1)
    assert legacy == str(third.output)
    assert json.loads(line)["evidence"]["status"] == "not_started"


async def test_run_three_sibling_delegations_without_ceilings_runs_all_three(
    tmp_path: Path,
) -> None:
    llm = _LLM([
        _calls(_delegate("d1", "task one"), _delegate("d2", "task two"), _delegate("d3", "task three")),
        _text("child answer one"),
        _text("child answer two"),
        _text("child answer three"),
        _text("parent completed"),
    ])
    runtime = _runtime(tmp_path, llm)
    assert runtime.config.agentic_tools.delegation_tree_max_children is None

    await _parent(runtime, llm)

    assert not llm.responses
    assert _roles(llm) == ["parent", "child", "child", "child", "parent"]
    assert len(runtime.delegator.contexts) == 3
    assert all(DELEGATION_TREE_BUDGET_KEY not in ctx for ctx in runtime.delegator.contexts)
    results = runtime.delegator.results
    assert [result.output["result"] for result in results] == [
        "child answer one", "child answer two", "child answer three",
    ]
    assert all(result.output.keys() == _DELEGATED_KEYS for result in results)


async def test_run_delegations_across_root_iterations_share_one_children_ceiling(
    tmp_path: Path,
) -> None:
    llm = _LLM([
        _calls(_delegate("d1", "task one")),
        _calls(_use("probe", {}, "p1")),
        _text("child answer one"),
        _calls(_delegate("d2", "task two")),
        _text("child answer two"),
        _calls(_delegate("d3", "task three")),
        _text("parent completed"),
    ])
    runtime = _runtime(tmp_path, llm, delegation_tree_max_children=2)

    await _parent(runtime, llm)

    assert not llm.responses
    assert _roles(llm) == ["parent", "child", "child", "parent", "child", "parent", "parent"]
    contexts = runtime.delegator.contexts
    assert len(contexts) == 3
    # Premise: each delegation came from a different iteration of the root run.
    assert len({ctx["iteration"] for ctx in contexts}) == 3
    budget = contexts[0][DELEGATION_TREE_BUDGET_KEY]
    assert type(budget) is DelegationTreeBudget
    assert all(ctx[DELEGATION_TREE_BUDGET_KEY] is budget for ctx in contexts)
    # The nested run's own tool context holds the SAME object, not a copy.
    assert len(runtime.probe.contexts) == 1
    probe_ctx = runtime.probe.contexts[0]
    assert (probe_ctx["agent_id"], probe_ctx["_delegation_depth"]) == ("child", 1)
    assert probe_ctx[DELEGATION_TREE_BUDGET_KEY] is budget
    results = runtime.delegator.results
    assert [result.output["delegated"] for result in results] == [True, True, False]
    assert results[2].output == _children_refusal(2)
    assert results[2].evidence.status == "not_started"
    assert budget.usage().in_flight == 0


async def test_run_separate_root_runs_receive_independent_tree_budgets(tmp_path: Path) -> None:
    llm = _LLM([
        _calls(_delegate("d1", "task one")),
        _text("child answer one"),
        _text("parent completed one"),
        _calls(_delegate("d2", "task two")),
        _text("child answer two"),
        _text("parent completed two"),
    ])
    runtime = _runtime(tmp_path, llm, delegation_tree_max_children=1)

    first = await _parent(runtime, llm)
    second = await _parent(runtime, llm)

    assert not llm.responses
    assert _roles(llm) == ["parent", "child", "parent", "parent", "child", "parent"]
    assert (first.final_text, second.final_text) == ("parent completed one", "parent completed two")
    one, two = (ctx[DELEGATION_TREE_BUDGET_KEY] for ctx in runtime.delegator.contexts)
    assert type(one) is DelegationTreeBudget and type(two) is DelegationTreeBudget
    assert one is not two
    assert [result.output["result"] for result in runtime.delegator.results] == [
        "child answer one", "child answer two",
    ]
    assert [(b.usage().children_admitted, b.usage().in_flight) for b in (one, two)] == [
        (1, 0), (1, 0),
    ]


# ── G.M2: grant maths, settlement, and the iteration and token ceilings ──


def test_admit_leaf_child_iterations_grant_is_min_of_cap_and_remaining() -> None:
    budget = DelegationTreeBudget(TreeCeilings(max_iterations=7))

    first = _admit(budget, cap=5)
    second = _admit(budget, cap=5)
    third = _admit(budget, cap=5)

    assert isinstance(first, TreeGrant) and isinstance(second, TreeGrant)
    # The per-child cap binds while the tree has more left; then the remainder binds.
    assert (first.max_iterations, first.token_budget, first.iterations_limited) == (5, None, False)
    assert (second.max_iterations, second.token_budget, second.iterations_limited) == (2, None, True)
    assert third == TreeRefusal(limit="iterations", ceiling=7, used=7, required=1)
    usage = budget.usage()
    assert (usage.iterations_reserved, usage.iterations_spent, usage.in_flight) == (7, 0, 2)


def test_admit_nonleaf_child_grant_is_depth_share_and_leaves_room_for_descendants() -> None:
    tokens = DelegationTreeBudget(TreeCeilings(max_tokens=4096))

    child = _admit(tokens, child_depth=1, max_depth=2)
    grandchild = _admit(tokens, child_depth=2, max_depth=2)
    refused = _admit(tokens, child_depth=2, max_depth=2)

    # Depth 1 of 2 takes half the remainder; the leaf below it takes all that is left.
    assert isinstance(child, TreeGrant) and child.token_budget == 2048
    assert isinstance(grandchild, TreeGrant) and grandchild.token_budget == 2048
    assert refused == TreeRefusal(limit="tokens", ceiling=4096, used=4096, required=1024)
    iterations = DelegationTreeBudget(TreeCeilings(max_iterations=9))
    child_turns = _admit(iterations, child_depth=1, max_depth=2, cap=25)
    grandchild_turns = _admit(iterations, child_depth=2, max_depth=2, cap=25)
    assert isinstance(child_turns, TreeGrant) and isinstance(grandchild_turns, TreeGrant)
    assert (child_turns.max_iterations, child_turns.iterations_limited) == (4, True)
    assert (grandchild_turns.max_iterations, grandchild_turns.iterations_limited) == (5, True)


def test_admit_nonleaf_share_never_drops_below_the_floors() -> None:
    tokens = DelegationTreeBudget(TreeCeilings(max_tokens=1500))
    iterations = DelegationTreeBudget(TreeCeilings(max_iterations=1))

    token_grant = _admit(tokens, child_depth=1, max_depth=3)
    iteration_grant = _admit(iterations, child_depth=1, max_depth=3)

    # 1500 // 3 and 1 // 3 fall below the floors, so the floors are granted instead.
    assert isinstance(token_grant, TreeGrant)
    assert token_grant.token_budget == MIN_DELEGATION_TOKEN_GRANT
    assert isinstance(iteration_grant, TreeGrant) and iteration_grant.max_iterations == 1


@pytest.mark.parametrize("spent", [1024, 1025])
def test_admit_tokens_below_minimum_grant_refuses_tokens(spent: int) -> None:
    budget = DelegationTreeBudget(TreeCeilings(max_tokens=2048))
    first = _admit(budget)
    assert isinstance(first, TreeGrant) and first.token_budget == 2048
    budget.settle(first, tokens_used=spent, iterations_used=1, stopped_reason="complete")

    second = _admit(budget)

    if spent == 1024:
        # Premise: exactly the minimum grant still admits, so the next row is the boundary.
        assert isinstance(second, TreeGrant)
        assert second.token_budget == MIN_DELEGATION_TOKEN_GRANT
    else:
        assert second == TreeRefusal(limit="tokens", ceiling=2048, used=1025, required=1024)
        assert budget.usage().in_flight == 0


_EXHAUSTED_BY_ONE_CHILD = {
    "max_children": 1, "max_concurrent": 1, "max_iterations": 1, "max_tokens": 1024,
}


@pytest.mark.parametrize(("relaxed", "expected"), [
    ((), "children"),
    (("max_children",), "concurrency"),
    (("max_children", "max_concurrent"), "iterations"),
    (("max_children", "max_concurrent", "max_iterations"), "tokens"),
])
def test_admit_refusal_order_is_children_concurrency_iterations_tokens(
    relaxed: tuple[str, ...], expected: str,
) -> None:
    budget = DelegationTreeBudget(TreeCeilings(**{
        name: None if name in relaxed else value
        for name, value in _EXHAUSTED_BY_ONE_CHILD.items()
    }))
    held = _admit(budget, cap=1)
    assert isinstance(held, TreeGrant)

    refused = _admit(budget, cap=1)

    # Premise: the held child exhausts every ceiling still set, so the FIRST checked one reports.
    assert isinstance(refused, TreeRefusal) and refused.limit == expected


@pytest.mark.parametrize("ceilings", [
    TreeCeilings(max_children=1),
    TreeCeilings(max_concurrent=1),
    TreeCeilings(max_iterations=1),
    TreeCeilings(max_tokens=1024),
], ids=["children", "concurrency", "iterations", "tokens"])
def test_admit_refusal_leaves_counters_unchanged(ceilings: TreeCeilings) -> None:
    budget = DelegationTreeBudget(ceilings)
    held = _admit(budget, cap=1)
    assert isinstance(held, TreeGrant)
    before = budget.usage()

    refused = _admit(budget, cap=1)

    assert isinstance(refused, TreeRefusal)
    assert budget.usage() == before
    # The held grant is still the only open one: it settles once and releases everything.
    budget.settle(held, tokens_used=0, iterations_used=1, stopped_reason="complete")
    after = budget.usage()
    assert (after.in_flight, after.iterations_reserved, after.tokens_reserved) == (0, 0, 0)


@pytest.mark.parametrize("arguments", [
    {"child_depth": 0}, {"child_depth": True}, {"child_depth": "1"},
    {"max_depth": -1}, {"max_depth": 1.0},
    {"per_child_iterations": 0}, {"per_child_iterations": None},
])
def test_admit_invalid_arguments_raise_before_any_counter_changes(
    arguments: dict[str, Any],
) -> None:
    budget = DelegationTreeBudget(TreeCeilings(max_children=5, max_iterations=10, max_tokens=4096))
    before = budget.usage()

    with pytest.raises(ValueError, match="delegation_tree_admission_invalid"):
        budget.admit(**{"child_depth": 1, "max_depth": 1, "per_child_iterations": 5, **arguments})

    assert budget.usage() == before


# 1 is the smallest token total charged as reported; a zero total is unknown (below).
@pytest.mark.parametrize("spent", [1, 500])
def test_settle_charges_actual_usage_and_refunds_unused_reservation(
    caplog: pytest.LogCaptureFixture, spent: int,
) -> None:
    budget = DelegationTreeBudget(TreeCeilings(max_tokens=2048, max_iterations=6))
    first = _admit(budget, cap=5)
    assert isinstance(first, TreeGrant)
    assert (first.token_budget, first.max_iterations) == (2048, 5)

    with caplog.at_level(logging.WARNING, logger=_BUDGET_LOGGER):
        budget.settle(first, tokens_used=spent, iterations_used=2, stopped_reason="complete")

    assert not _budget_warnings(caplog)
    usage = budget.usage()
    assert (usage.tokens_spent, usage.tokens_reserved) == (spent, 0)
    assert (usage.iterations_spent, usage.iterations_reserved, usage.in_flight) == (2, 0, 0)
    second = _admit(budget, cap=5)
    assert isinstance(second, TreeGrant)
    assert (second.token_budget, second.max_iterations) == (2048 - spent, 4)


_OVER_GRANT = "one-more-than-the-grant"


@pytest.mark.parametrize(("usage_field", "reported"), [
    ("iterations_used", None), ("iterations_used", 0), ("iterations_used", -1),
    ("iterations_used", True), ("iterations_used", "3"), ("iterations_used", _OVER_GRANT),
    ("tokens_used", None), ("tokens_used", 0), ("tokens_used", -1), ("tokens_used", True),
    ("tokens_used", "3"),
])
def test_settle_unknown_or_invalid_usage_charges_full_grant(
    caplog: pytest.LogCaptureFixture, usage_field: str, reported: object,
) -> None:
    budget = DelegationTreeBudget(TreeCeilings(max_tokens=4096, max_iterations=10))
    grant = _admit(budget, cap=3)
    assert isinstance(grant, TreeGrant)
    assert (grant.max_iterations, grant.token_budget) == (3, 4096)
    usage: dict[str, Any] = {"tokens_used": 100, "iterations_used": 2, "stopped_reason": "complete"}
    usage[usage_field] = grant.max_iterations + 1 if reported == _OVER_GRANT else reported

    with caplog.at_level(logging.WARNING, logger=_BUDGET_LOGGER):
        budget.settle(grant, **usage)

    after = budget.usage()
    expected = (3, 100) if usage_field == "iterations_used" else (2, 4096)
    assert (after.iterations_spent, after.tokens_spent) == expected
    assert (after.in_flight, after.iterations_reserved, after.tokens_reserved) == (0, 0, 0)
    (warning,) = _budget_warnings(caplog)
    # The warning names the one value it did not trust, as reported, and what it charged.
    shown = "<not an int>" if type(usage[usage_field]) is str else repr(usage[usage_field])
    charged = 3 if usage_field == "iterations_used" else 4096
    assert f"{usage_field}={shown} charged as {charged}" in warning.getMessage()
    other = "tokens_used" if usage_field == "iterations_used" else "iterations_used"
    assert f"{other}=" not in warning.getMessage()


@pytest.mark.parametrize("reported", [None, 0])
def test_settle_unknown_tokens_without_a_token_grant_charges_zero(
    caplog: pytest.LogCaptureFixture, reported: int | None,
) -> None:
    budget = DelegationTreeBudget(TreeCeilings(max_children=2))
    grant = _admit(budget)
    assert isinstance(grant, TreeGrant) and grant.token_budget is None

    with caplog.at_level(logging.WARNING, logger=_BUDGET_LOGGER):
        budget.settle(grant, tokens_used=reported, iterations_used=1, stopped_reason="complete")

    assert (budget.usage().tokens_spent, budget.usage().iterations_spent) == (0, 1)
    # Before review round 3 this pinned a WARNING reading "charged as 0", which substituted
    # nothing: with no token grant there is no allowance to charge, so nothing is logged.
    assert not _budget_warnings(caplog)


def test_settle_warning_never_formats_an_int_too_large_to_show(
    caplog: pytest.LogCaptureFixture,
) -> None:
    huge = -(10**5000)
    # Premise: Python refuses to format this int in decimal, so formatting it would raise.
    with pytest.raises(ValueError):
        repr(huge)
    budget = DelegationTreeBudget(TreeCeilings(max_tokens=4096))
    grant = _admit(budget)
    assert isinstance(grant, TreeGrant)

    with caplog.at_level(logging.WARNING, logger=_BUDGET_LOGGER):
        budget.settle(grant, tokens_used=huge, iterations_used=1, stopped_reason="complete")

    assert budget.usage().tokens_spent == 4096
    (warning,) = _budget_warnings(caplog)
    assert "tokens_used=<an int too large to show> charged as 4096" in warning.getMessage()


def test_settle_foreign_or_repeated_grant_is_ignored_without_raising(
    caplog: pytest.LogCaptureFixture,
) -> None:
    budget = DelegationTreeBudget(TreeCeilings(max_children=3))
    other = DelegationTreeBudget(TreeCeilings(max_children=3))
    grant = _admit(budget)
    foreign = _admit(other)
    assert isinstance(grant, TreeGrant) and isinstance(foreign, TreeGrant)
    usage: dict[str, Any] = {"tokens_used": 10, "iterations_used": 1, "stopped_reason": "complete"}
    budget.settle(grant, **usage)
    settled = budget.usage()
    lookalike = TreeGrant(
        max_iterations=grant.max_iterations, token_budget=grant.token_budget,
        iterations_limited=grant.iterations_limited,
    )

    with caplog.at_level(logging.WARNING, logger=_BUDGET_LOGGER):
        budget.settle(grant, **usage)
        budget.settle(foreign, **usage)
        budget.settle(lookalike, **usage)
        budget.settle(object(), **usage)  # type: ignore[arg-type]

    assert budget.usage() == settled
    assert len(_budget_warnings(caplog)) == 4
    assert other.usage().in_flight == 1, "the foreign grant is still open in its own tree"


async def test_run_iteration_ceiling_limits_second_child_and_refuses_third(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    llm = _LLM([
        _calls(_delegate("d1", "task one"), _delegate("d2", "task two"), _delegate("d3", "task three")),
        _text("child answer one"),
        _calls(_use("probe", {}, "p1")),
        _calls(_use("probe", {}, "p2")),
        _text("parent completed"),
    ])
    runtime = _runtime(tmp_path, llm, delegation_tree_max_iterations=3)

    with caplog.at_level(logging.INFO):
        outcome = await _parent(runtime, llm)

    assert not llm.responses
    assert _roles(llm) == ["parent", "child", "child", "child", "parent"]
    assert outcome.final_text == "parent completed"
    first, second, third = runtime.delegator.results
    assert first.output == {
        "delegated": True, "to": "Child", "result": "child answer one", "stopped_reason": "complete",
    }
    # The second child got the 2 iterations left, below the per-child cap of 5, and used both.
    assert len(runtime.probe.contexts) == 2
    assert second.output == {
        "delegated": True, "to": "Child", "result": "", "stopped_reason": "max_iterations",
        "tree_limit": "iterations",
    }
    assert second.evidence.status == "exhausted"
    assert third.output == _refusal("iterations", ceiling=3, used=3, required=1)
    assert third.evidence.status == "not_started"
    budget = runtime.delegator.contexts[0][DELEGATION_TREE_BUDGET_KEY]
    usage = budget.usage()
    assert (usage.iterations_spent, usage.iterations_reserved, usage.in_flight) == (3, 0, 0)
    # Actual iterations are known, so neither settle fell back to charging a whole grant.
    assert not _budget_warnings(caplog)


async def test_run_token_ceiling_stops_child_at_grant_and_reports_overshoot_on_next_refusal(
    tmp_path: Path,
) -> None:
    llm = _LLM([
        _calls(_delegate("d1", "task one"), _delegate("d2", "task two")),
        _Response(
            content="child answer one", content_blocks=[TextBlock(text="child answer one")],
            tokens_used=3000,
        ),
        _text("parent completed"),
    ])
    runtime = _runtime(tmp_path, llm, delegation_tree_max_tokens=2048)

    outcome = await _parent(runtime, llm)

    assert not llm.responses
    assert _roles(llm) == ["parent", "child", "parent"]
    first, second = runtime.delegator.results
    # One 3000-token call against a 2048 grant: the loop checks the grant only after a call.
    assert first.output == {
        "delegated": True, "to": "Child", "result": "child answer one",
        "stopped_reason": "token_budget", "tree_limit": "tokens",
    }
    assert first.evidence.status == "exhausted"
    # Measured: the tree spent 952 over its ceiling; the root's own two 3-token calls are not in it.
    assert second.output == _refusal("tokens", ceiling=2048, used=3000, required=1024)
    assert second.evidence.status == "not_started"
    budget = runtime.delegator.contexts[0][DELEGATION_TREE_BUDGET_KEY]
    assert (budget.usage().tokens_spent, budget.usage().tokens_reserved) == (3000, 0)
    assert outcome.total_tokens == 6


async def test_run_per_child_cap_stop_does_not_report_tree_limit(tmp_path: Path) -> None:
    llm = _LLM([
        _calls(_delegate("d1")),
        _calls(_use("probe", {}, "p1")),
        _calls(_use("probe", {}, "p2")),
        _text("parent completed"),
    ])
    runtime = _runtime(
        tmp_path, llm, max_iterations=2,
        delegation_tree_max_iterations=100, delegation_tree_max_tokens=100_000,
    )

    await _parent(runtime, llm)

    assert not llm.responses
    assert _roles(llm) == ["parent", "child", "child", "parent"]
    (result,) = runtime.delegator.results
    assert result.output["stopped_reason"] == "max_iterations"
    assert result.output.keys() == _DELEGATED_KEYS
    # Premise: the child DID run under a tree grant, so the per-child cap is what stopped it.
    budget = runtime.delegator.contexts[0][DELEGATION_TREE_BUDGET_KEY]
    usage = budget.usage()
    assert (usage.children_admitted, usage.iterations_spent, usage.tokens_spent) == (1, 2, 6)


@pytest.mark.parametrize(("ceilings", "stopped_reason", "max_iterations", "token_budget"), [
    (TreeCeilings(max_iterations=10), "token_budget", 5, None),
    (TreeCeilings(max_children=3), "max_iterations", 5, None),
    (TreeCeilings(max_iterations=2, max_tokens=4096), "complete", 2, 4096),
], ids=["token-stop-without-token-grant", "cap-bound-iterations", "completed"])
async def test_invoke_tree_limit_is_absent_unless_the_grant_caused_the_stop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, ceilings: TreeCeilings,
    stopped_reason: str, max_iterations: int, token_budget: int | None,
) -> None:
    seen: list[dict[str, Any]] = []

    async def stopped_run(self: Any, **kwargs: Any) -> WorkItemAgenticOutcome:
        seen.append(kwargs)
        return WorkItemAgenticOutcome(
            final_text="partial", stopped_reason=stopped_reason, iterations=1,
        )

    monkeypatch.setattr(WorkItemAgenticExecutor, "run", stopped_run)
    runtime = _runtime(tmp_path, _LLM([]))
    budget = DelegationTreeBudget(ceilings)

    result = await runtime.delegator.invoke(
        {"task": "child task", "to": "Child"},
        {"agent_id": "parent", "thread_id": "thread", DELEGATION_TREE_BUDGET_KEY: budget},
    )

    # Premise: the nested run received exactly the grant whose stop is being classified.
    assert len(seen) == 1 and seen[0]["extra_context"][DELEGATION_TREE_BUDGET_KEY] is budget
    assert seen[0]["max_iterations"] == max_iterations
    assert seen[0].get("token_budget") == token_budget
    assert ("token_budget" in seen[0]) is (token_budget is not None)
    assert result.output["stopped_reason"] == stopped_reason
    assert result.output.keys() == _DELEGATED_KEYS


async def test_run_outcome_projects_loop_iterations_as_last_field(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    llm = _LLM([_calls(_use("probe", {}, "p1")), _text("parent completed")])
    runtime = _runtime(tmp_path, llm)

    with caplog.at_level(logging.WARNING):
        outcome = await _parent(runtime, llm)

    assert not llm.responses
    assert outcome.final_text == "parent completed"
    assert outcome.iterations == 2
    assert fields(WorkItemAgenticOutcome)[-1].name == "iterations"
    assert WorkItemAgenticOutcome().iterations == 0
    assert not [r for r in caplog.records if "invalid iteration count" in r.getMessage()]


@pytest.mark.parametrize("forged", [-1, True, "2", None])
async def test_run_invalid_loop_iteration_count_records_zero_and_warns(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
    forged: object,
) -> None:
    original = AgenticLoop.run
    counted: list[Any] = []

    async def forged_count(self: Any, **kwargs: Any) -> Any:
        result = await original(self, **kwargs)
        counted.append(result.iterations)
        result.iterations = forged
        return result

    monkeypatch.setattr(AgenticLoop, "run", forged_count)
    llm = _LLM([_text("parent completed")])
    runtime = _runtime(tmp_path, llm)

    with caplog.at_level(logging.WARNING):
        outcome = await _parent(runtime, llm)

    # Premise: the real loop ran and counted its one iteration before the count was forged.
    assert counted == [1] and not llm.responses
    assert outcome.final_text == "parent completed"
    assert outcome.iterations == 0
    warnings = [r for r in caplog.records if "invalid iteration count" in r.getMessage()]
    assert [r.levelno for r in warnings] == [logging.WARNING]


# ── G.M3: concurrency, nesting across depths, and settlement on failure ──


_CHILD_PARAMS = {"task": "child task", "to": "Child"}


def _direct_context(budget: DelegationTreeBudget) -> dict[str, Any]:
    return {"agent_id": "parent", "thread_id": "thread", DELEGATION_TREE_BUDGET_KEY: budget}


def _to_grandchild(call_id: str) -> ToolUseBlock:
    return _use("delegate_task", {"task": "grandchild task", "to": "Grandchild"}, call_id)


async def test_invoke_concurrent_admissions_beyond_ceiling_refuse_while_siblings_in_flight(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    entered = 0
    both_in = asyncio.Event()
    release = asyncio.Event()

    async def held_run(self: Any, **kwargs: Any) -> WorkItemAgenticOutcome:
        nonlocal entered
        entered += 1
        # Only the first two park, so a wrongly admitted third cannot hang the test.
        if entered <= 2:
            if entered == 2:
                both_in.set()
            await release.wait()
        return WorkItemAgenticOutcome(final_text="done", stopped_reason="complete", iterations=1)

    monkeypatch.setattr(WorkItemAgenticExecutor, "run", held_run)
    runtime = _runtime(tmp_path, _LLM([]))
    budget = DelegationTreeBudget(TreeCeilings(max_concurrent=2))
    first = asyncio.create_task(runtime.delegator.invoke(_CHILD_PARAMS, _direct_context(budget)))
    second = asyncio.create_task(runtime.delegator.invoke(_CHILD_PARAMS, _direct_context(budget)))
    try:
        # Premise: both siblings are inside their nested runs, each holding a slot.
        await asyncio.wait_for(both_in.wait(), 5)
        assert entered == 2 and budget.usage().in_flight == 2

        third = await runtime.delegator.invoke(_CHILD_PARAMS, _direct_context(budget))

        assert third.output == _refusal("concurrency", ceiling=2, used=2, required=1)
        assert third.error is None and third.evidence.status == "not_started"
        assert entered == 2, "the refused delegation started no nested run"
    finally:
        release.set()
        settled = await asyncio.gather(first, second, return_exceptions=True)
    assert [
        isinstance(result, DelegatedToolResult) and result.output["delegated"]
        for result in settled
    ] == [True, True]
    usage = budget.usage()
    assert (usage.children_admitted, usage.in_flight) == (2, 0)
    fourth = await runtime.delegator.invoke(_CHILD_PARAMS, _direct_context(budget))
    assert fourth.output["delegated"] is True and entered == 3


async def test_run_nested_delegation_counts_in_flight_parent_against_concurrency(
    tmp_path: Path,
) -> None:
    llm = _LLM([
        _calls(_delegate("d1")),
        _calls(_to_grandchild("g1")),
        _text("child answer"),
        _text("parent completed"),
    ])
    runtime = _runtime(tmp_path, llm, max_depth=2, delegation_tree_max_concurrent=1)

    outcome = await _parent(runtime, llm)

    assert not llm.responses
    assert _roles(llm) == ["parent", "child", "child", "parent"]
    assert outcome.final_text == "parent completed"
    root_ctx, child_ctx = runtime.delegator.contexts
    # Premise: the refused delegation came from inside the admitted child's own run.
    assert (child_ctx["agent_id"], child_ctx["_delegation_depth"]) == ("child", 1)
    budget = root_ctx[DELEGATION_TREE_BUDGET_KEY]
    assert type(budget) is DelegationTreeBudget
    assert child_ctx[DELEGATION_TREE_BUDGET_KEY] is budget
    refused, delegated = runtime.delegator.results
    assert refused.output == _refusal("concurrency", ceiling=1, used=1, required=1)
    assert refused.evidence.status == "not_started"
    # The child read the refusal on its own next request, so it was in flight when refused.
    content = _parent_tool_content(llm.requests[2], structured=False, call_id="g1")
    assert content.split("\n", 1)[1] == str(refused.output)
    assert delegated.output == {
        "delegated": True, "to": "Child", "result": "child answer", "stopped_reason": "complete",
    }
    usage = budget.usage()
    assert (usage.children_admitted, usage.in_flight) == (1, 0)


async def test_run_nested_delegation_shares_children_ceiling_across_depths(
    tmp_path: Path,
) -> None:
    llm = _LLM([
        _calls(_delegate("d1", "task one")),
        _calls(_to_grandchild("g1")),
        _text("grandchild answer"),
        _text("child answer"),
        _calls(_delegate("d2", "task two")),
        _text("parent completed"),
    ])
    runtime = _runtime(tmp_path, llm, max_depth=2, delegation_tree_max_children=2)

    outcome = await _parent(runtime, llm)

    assert not llm.responses
    assert _roles(llm) == ["parent", "child", "grandchild", "child", "parent", "parent"]
    assert outcome.final_text == "parent completed"
    contexts = runtime.delegator.contexts
    assert [(ctx["agent_id"], ctx.get("_delegation_depth")) for ctx in contexts] == [
        ("parent", None), ("child", 1), ("parent", None),
    ]
    budget = contexts[0][DELEGATION_TREE_BUDGET_KEY]
    assert type(budget) is DelegationTreeBudget
    assert all(ctx[DELEGATION_TREE_BUDGET_KEY] is budget for ctx in contexts)
    nested, first, second = runtime.delegator.results
    assert (nested.output["delegated"], nested.output["result"]) == (True, "grandchild answer")
    assert (first.output["delegated"], first.output["result"]) == (True, "child answer")
    assert second.output == _children_refusal(2)
    assert second.evidence.status == "not_started"
    usage = budget.usage()
    assert (usage.children_admitted, usage.in_flight) == (2, 0)


async def test_invoke_child_exception_releases_slot_and_charges_full_grant(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
) -> None:
    seen: list[dict[str, Any]] = []

    async def failing_run(self: Any, **kwargs: Any) -> WorkItemAgenticOutcome:
        seen.append(kwargs)
        raise RuntimeError("nested run failed")

    monkeypatch.setattr(WorkItemAgenticExecutor, "run", failing_run)
    runtime = _runtime(tmp_path, _LLM([]))
    budget = DelegationTreeBudget(
        TreeCeilings(max_concurrent=1, max_iterations=10, max_tokens=4096),
    )

    with caplog.at_level(logging.WARNING, logger=_BUDGET_LOGGER):
        result = await runtime.delegator.invoke(_CHILD_PARAMS, _direct_context(budget))

    # Premise: the child was admitted and its nested run entered with the whole grant.
    assert len(seen) == 1
    assert (seen[0]["max_iterations"], seen[0]["token_budget"]) == (5, 4096)
    assert result.error is not None and result.error.startswith("delegation_failed: ")
    assert result.evidence.status == "failed"
    usage = budget.usage()
    assert (usage.children_admitted, usage.in_flight) == (1, 0)
    assert (usage.iterations_spent, usage.tokens_spent) == (5, 4096)
    assert (usage.iterations_reserved, usage.tokens_reserved) == (0, 0)
    assert len(_budget_warnings(caplog)) == 1
    # The slot is free again, so the first check to fail is tokens, which the failure used up.
    assert _admit(budget) == TreeRefusal(limit="tokens", ceiling=4096, used=4096, required=1024)


async def test_invoke_child_cancellation_propagates_and_releases_slot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
) -> None:
    entered = asyncio.Event()

    async def parked_run(self: Any, **kwargs: Any) -> WorkItemAgenticOutcome:
        entered.set()
        await asyncio.Event().wait()
        raise AssertionError("a parked nested run must only end by cancellation")

    monkeypatch.setattr(WorkItemAgenticExecutor, "run", parked_run)
    runtime = _runtime(tmp_path, _LLM([]))
    budget = DelegationTreeBudget(
        TreeCeilings(max_concurrent=1, max_iterations=10, max_tokens=4096),
    )
    task = asyncio.create_task(runtime.delegator.invoke(_CHILD_PARAMS, _direct_context(budget)))
    try:
        # Premise: the nested run was entered, holding its slot, before cancel().
        await asyncio.wait_for(entered.wait(), 5)
        assert budget.usage().in_flight == 1
        with caplog.at_level(logging.WARNING, logger=_BUDGET_LOGGER):
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
    finally:
        if not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
    assert task.cancelled()
    assert runtime.delegator.results == [], "a cancelled delegation folds no result"
    usage = budget.usage()
    assert (usage.children_admitted, usage.in_flight) == (1, 0)
    assert (usage.iterations_spent, usage.tokens_spent) == (5, 4096)
    assert (usage.iterations_reserved, usage.tokens_reserved) == (0, 0)
    assert len(_budget_warnings(caplog)) == 1


def test_admit_and_settle_are_synchronous() -> None:
    # Premise: the check does report a coroutine function when it is given one.
    assert inspect.iscoroutinefunction(DelegateTaskTool.invoke)

    assert not inspect.iscoroutinefunction(DelegationTreeBudget.admit)
    assert not inspect.iscoroutinefunction(DelegationTreeBudget.settle)
    budget = DelegationTreeBudget(TreeCeilings(max_children=1))
    grant = _admit(budget)
    assert isinstance(grant, TreeGrant)
    assert budget.settle(grant, tokens_used=0, iterations_used=1, stopped_reason="complete") is None
    assert budget.usage().in_flight == 0


# ── G.M4: boundaries, forgery, the session-correction root and the default-off proof ──


_TREE_CONFIG = {
    "delegation_tree_max_tokens": 4096,
    "delegation_tree_max_iterations": 7,
    "delegation_tree_max_concurrent": 2,
    "delegation_tree_max_children": 3,
}
# AgenticToolsConfig field -> (TreeCeilings field, lowest valid value)
_TREE_FIELDS = {
    "delegation_tree_max_tokens": ("max_tokens", MIN_DELEGATION_TOKEN_GRANT),
    "delegation_tree_max_iterations": ("max_iterations", 1),
    "delegation_tree_max_concurrent": ("max_concurrent", 1),
    "delegation_tree_max_children": ("max_children", 1),
}
_ABSENT = object()
_BUDGET_INVALID = {"delegated": False, "reason": "delegation_tree_budget_invalid"}


class _ForgedBudget(DelegationTreeBudget):
    """Passes ``isinstance``, so only an exact-type check can refuse it."""


def _one_child_budget() -> DelegationTreeBudget:
    return DelegationTreeBudget(TreeCeilings(max_children=1))


def _offered(request: Any) -> list[str]:
    return [definition["function"]["name"] for definition in request.tools or []]


async def _run_child(
    runtime: Any, llm: Any, extra_context: dict[str, Any],
) -> WorkItemAgenticOutcome:
    return await WorkItemAgenticExecutor(llm_client=llm).run(
        agent_id="child", instructions="child instructions", task_text="child task",
        runtime=runtime, thread_id="thread", max_iterations=2, extra_context=extra_context,
    )


async def _assert_boundary_refuses(
    runtime: Any, llm: _LLM, extra_context: dict[str, Any],
) -> None:
    before = len(llm.requests)
    with pytest.raises(ValueError, match="^agentic_context_invalid$"):
        await _run_child(runtime, llm, extra_context)
    assert len(llm.requests) == before, "the refused run made no model call"


async def _assert_boundary_accepts_exact_budget(runtime: Any, llm: _LLM) -> None:
    accepted = await _run_child(
        runtime, llm, {"_delegation_depth": 1, DELEGATION_TREE_BUDGET_KEY: _one_child_budget()},
    )
    assert (accepted.final_text, len(llm.requests)) == ("accepted", 1)


@pytest.mark.parametrize("forged", [
    lambda: None,
    lambda: object(),
    lambda: {"max_children": 1},
    lambda: SimpleNamespace(admit=lambda **_: None, settle=lambda *_, **__: None),
], ids=["none", "object", "dict", "duck-typed"])
async def test_run_extra_context_budget_wrong_type_raises_agentic_context_invalid(
    tmp_path: Path, forged: Callable[[], object],
) -> None:
    llm = _LLM([_text("accepted")])
    runtime = _runtime(tmp_path, llm)
    # Premise: this same boundary accepts the exact type beside a valid depth.
    await _assert_boundary_accepts_exact_budget(runtime, llm)

    await _assert_boundary_refuses(
        runtime, llm, {"_delegation_depth": 1, DELEGATION_TREE_BUDGET_KEY: forged()},
    )


async def test_run_extra_context_budget_subclass_raises_agentic_context_invalid(
    tmp_path: Path,
) -> None:
    llm = _LLM([_text("accepted")])
    runtime = _runtime(tmp_path, llm)
    forged = _ForgedBudget(TreeCeilings(max_children=1))
    # Premise: the subclass passes isinstance, and the exact type passes this boundary.
    assert isinstance(forged, DelegationTreeBudget)
    await _assert_boundary_accepts_exact_budget(runtime, llm)

    await _assert_boundary_refuses(
        runtime, llm, {"_delegation_depth": 1, DELEGATION_TREE_BUDGET_KEY: forged},
    )


@pytest.mark.parametrize("depth", [_ABSENT, 0, True, "1"], ids=["absent", "zero", "bool", "str"])
async def test_run_extra_context_budget_without_delegation_depth_raises_agentic_context_invalid(
    tmp_path: Path, depth: object,
) -> None:
    llm = _LLM([_text("accepted")])
    runtime = _runtime(tmp_path, llm)
    depth_context: dict[str, Any] = {} if depth is _ABSENT else {"_delegation_depth": depth}
    # Premise: this depth alone passes the boundary, so the budget beside it is what is refused.
    accepted = await _run_child(runtime, llm, dict(depth_context))
    assert (accepted.final_text, len(llm.requests)) == ("accepted", 1)

    await _assert_boundary_refuses(
        runtime, llm, {**depth_context, DELEGATION_TREE_BUDGET_KEY: _one_child_budget()},
    )


@pytest.mark.parametrize("forged", [
    lambda: {"max_children": 99},
    lambda: DelegationTreeBudget(TreeCeilings(max_children=99)),
], ids=["json-shaped", "budget-object"])
async def test_invoke_budget_supplied_in_params_is_refused_as_undeclared(
    tmp_path: Path, forged: Callable[[], object],
) -> None:
    llm = _LLM([_text("child answer")])
    runtime = _runtime(tmp_path, llm)
    budget = _one_child_budget()
    smuggled = forged()

    refused = await runtime.delegator.invoke(
        {**_CHILD_PARAMS, DELEGATION_TREE_BUDGET_KEY: smuggled}, _direct_context(budget),
    )

    assert refused.output is None
    assert refused.error == (
        "delegate_task: unknown parameter(s) _delegation_tree_budget. Accepted: task, to."
    )
    assert refused.evidence.status == "not_started"
    assert budget.usage().children_admitted == 0 and not llm.requests
    if isinstance(smuggled, DelegationTreeBudget):
        assert smuggled.usage().children_admitted == 0
    # Premise: the context budget is live -- the same call without the smuggled key is admitted.
    admitted = await runtime.delegator.invoke(_CHILD_PARAMS, _direct_context(budget))
    assert admitted.output["delegated"] is True
    assert (budget.usage().children_admitted, len(llm.requests)) == (1, 1)


@pytest.mark.parametrize("forged", [
    lambda: object(),
    lambda: {"max_children": 1},
    lambda: _ForgedBudget(TreeCeilings(max_children=5)),
], ids=["object", "dict", "subclass"])
async def test_invoke_malformed_budget_in_context_refuses_without_starting_child(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, forged: Callable[[], object],
) -> None:
    llm = _LLM([_text("child answer")])
    runtime = _runtime(tmp_path, llm)
    malformed = forged()

    with caplog.at_level(logging.WARNING, logger=_TOOL_LOGGER):
        refused = await runtime.delegator.invoke(
            _CHILD_PARAMS,
            {"agent_id": "parent", "thread_id": "thread", DELEGATION_TREE_BUDGET_KEY: malformed},
        )

    assert refused.output == _BUDGET_INVALID
    assert refused.error is None and refused.metadata == {}
    assert refused.evidence.status == "not_started"
    assert not llm.requests, "no nested run started"
    if isinstance(malformed, DelegationTreeBudget):
        assert malformed.usage().children_admitted == 0
    warnings = [
        record for record in caplog.records
        if record.name == _TOOL_LOGGER and record.levelno == logging.WARNING
    ]
    assert len(warnings) == 1 and "AD-1190" in warnings[0].getMessage()
    # Premise: the same call without a budget in its context does start a child.
    control = await runtime.delegator.invoke(
        _CHILD_PARAMS, {"agent_id": "parent", "thread_id": "thread"},
    )
    assert control.output["delegated"] is True and len(llm.requests) == 1


@pytest.mark.parametrize(("params", "extra", "expected"), [
    (_CHILD_PARAMS, {"_delegation_depth": 1},
     {"delegated": False, "reason": "max_delegation_depth_reached"}),
    ({"task": "child task", "to": "Nobody"}, {},
     {"delegated": False, "reason": "target_not_found"}),
    ({"task": "own task", "to": "Parent"}, {},
     {"delegated": False, "reason": "target_not_found"}),
    ({"task": "", "to": "Child"}, {},
     {"delegated": False, "reason": "task_and_to_required"}),
], ids=["depth", "unknown-target", "self-target", "missing-task"])
async def test_invoke_target_not_found_and_depth_refusal_consume_no_slot(
    tmp_path: Path, params: dict[str, Any], extra: dict[str, Any], expected: dict[str, Any],
) -> None:
    llm = _LLM([_text("child answer")])
    runtime = _runtime(tmp_path, llm)
    budget = _one_child_budget()
    before = budget.usage()

    refused = await runtime.delegator.invoke(params, {**_direct_context(budget), **extra})

    # Exact: a budget in the context adds nothing to an earlier refusal.
    assert refused.output == expected
    assert refused.error is None and refused.metadata == {}
    assert refused.evidence.status == "not_started"
    assert budget.usage() == before and not llm.requests
    # Premise: the tree's only child slot is still free, so the refusal consumed nothing.
    admitted = await runtime.delegator.invoke(_CHILD_PARAMS, _direct_context(budget))
    assert admitted.output["delegated"] is True
    assert budget.usage().children_admitted == 1


async def test_invoke_default_context_nested_run_kwargs_byte_identical(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[dict[str, Any]] = []

    async def spy_run(self: Any, **kwargs: Any) -> WorkItemAgenticOutcome:
        seen.append(kwargs)
        return WorkItemAgenticOutcome(final_text="done", stopped_reason="complete", iterations=1)

    monkeypatch.setattr(WorkItemAgenticExecutor, "run", spy_run)
    runtime = _runtime(tmp_path, _LLM([]))

    result = await runtime.delegator.invoke(
        _CHILD_PARAMS, {"agent_id": "parent", "thread_id": "thread"},
    )

    # Exactly the arguments a nested run received before AD-1190.
    assert seen == [{
        "agent_id": "child", "instructions": "child instructions", "task_text": "child task",
        "runtime": runtime, "thread_id": "thread", "max_iterations": 5, "tier": "standard",
        "extra_context": {"_delegation_depth": 1},
    }]
    assert seen[0]["runtime"] is runtime
    assert result.output == {
        "delegated": True, "to": "Child", "result": "done", "stopped_reason": "complete",
    }
    assert result.error is None and result.metadata == {}


@pytest.mark.parametrize(("ceilings", "token_budget"), [
    (TreeCeilings(max_iterations=3), None),
    (TreeCeilings(max_iterations=3, max_tokens=4096), 4096),
], ids=["without-token-ceiling", "with-token-ceiling"])
async def test_invoke_budgeted_context_nested_run_carries_same_budget_and_grant(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, ceilings: TreeCeilings,
    token_budget: int | None,
) -> None:
    budget = DelegationTreeBudget(ceilings)
    seen: list[tuple[dict[str, Any], Any]] = []

    async def spy_run(self: Any, **kwargs: Any) -> WorkItemAgenticOutcome:
        seen.append((kwargs, budget.usage()))
        return WorkItemAgenticOutcome(final_text="done", stopped_reason="complete", iterations=1)

    monkeypatch.setattr(WorkItemAgenticExecutor, "run", spy_run)
    runtime = _runtime(tmp_path, _LLM([]))

    result = await runtime.delegator.invoke(_CHILD_PARAMS, _direct_context(budget))

    ((kwargs, in_flight),) = seen
    assert kwargs["extra_context"] == {"_delegation_depth": 1, DELEGATION_TREE_BUDGET_KEY: budget}
    assert kwargs["extra_context"][DELEGATION_TREE_BUDGET_KEY] is budget
    # The grant is the 3 iterations left, below the per-child cap of 5, reserved while it runs.
    assert (kwargs["max_iterations"], in_flight.iterations_reserved) == (3, 3)
    assert ("token_budget" in kwargs) is (token_budget is not None)
    assert kwargs.get("token_budget") == token_budget
    assert in_flight.tokens_reserved == (token_budget or 0)
    assert {
        key: value for key, value in kwargs.items()
        if key not in {"extra_context", "max_iterations", "token_budget"}
    } == {
        "agent_id": "child", "instructions": "child instructions", "task_text": "child task",
        "runtime": runtime, "thread_id": "thread", "tier": "standard",
    }
    assert result.output == {
        "delegated": True, "to": "Child", "result": "done", "stopped_reason": "complete",
    }


@pytest.mark.parametrize(("delegation_enabled", "tree", "opened"), [
    (True, {}, False),
    (True, {"delegation_tree_max_children": 3}, True),
    (False, {"delegation_tree_max_children": 3}, False),
], ids=["default-config", "ceiling-set", "ceiling-set-delegation-off"])
async def test_run_default_config_offers_tools_no_budget_key(
    tmp_path: Path, delegation_enabled: bool, tree: dict[str, Any], opened: bool,
) -> None:
    llm = _LLM([_calls(_use("probe", {}, "p1")), _text("parent completed")])
    runtime = _runtime(tmp_path, llm)
    runtime.config.agentic_tools = AgenticToolsConfig(
        delegation_enabled=delegation_enabled, **tree,
    )

    outcome = await _parent(runtime, llm)

    assert (outcome.final_text, llm.responses) == ("parent completed", [])
    # Premise: delegation was offered to the root exactly when it is enabled.
    assert ("delegate_task" in _offered(llm.requests[0])) is delegation_enabled
    (probe_ctx,) = runtime.probe.contexts
    assert probe_ctx["agent_id"] == "parent" and "_delegation_depth" not in probe_ctx
    assert (DELEGATION_TREE_BUDGET_KEY in probe_ctx) is opened
    if opened:
        budget = probe_ctx[DELEGATION_TREE_BUDGET_KEY]
        assert type(budget) is DelegationTreeBudget
        assert budget.ceilings == TreeCeilings(max_children=3)
        assert budget.usage().children_admitted == 0


async def test_run_executor_registered_delegate_tool_enforces_children_ceiling(
    tmp_path: Path,
) -> None:
    llm = _LLM([
        _calls(_delegate("d1", "task one"), _delegate("d2", "task two")),
        _text("child answer one"),
        _text("parent completed"),
    ])
    runtime = _runtime(tmp_path, llm, delegation_tree_max_children=1)
    assert runtime.tool_registry.unregister("delegate_task") is True
    assert runtime.tool_registry.get("delegate_task") is None

    outcome = await _parent(runtime, llm)

    assert not llm.responses
    assert _roles(llm) == ["parent", "child", "parent"]
    assert outcome.final_text == "parent completed"
    # Premise: the executor registered its own AD-1072 tool; the recording fixture never ran.
    registration = runtime.tool_registry.get("delegate_task")
    assert type(registration.tool) is DelegateTaskTool
    assert registration.provider == "AD-1072"
    assert runtime.delegator.contexts == []
    content = _parent_tool_content(llm.requests[-1], structured=False, call_id="d2")
    line, legacy = content.split("\n", 1)
    assert legacy == str(_children_refusal(1))
    assert json.loads(line)["evidence"]["status"] == "not_started"


@pytest.mark.parametrize("config", [
    lambda: None, lambda: SimpleNamespace(), lambda: AgenticToolsConfig(),
], ids=["none", "no-attributes", "defaults"])
def test_from_config_all_none_returns_none(config: Callable[[], object]) -> None:
    cfg = config()

    assert read_tree_ceilings(cfg) == TreeCeilings()
    assert read_tree_ceilings(cfg).unbounded
    assert DelegationTreeBudget.from_config(cfg) is None
    # Premise: one ceiling on the same model does open a budget.
    opened = DelegationTreeBudget.from_config(AgenticToolsConfig(delegation_tree_max_children=2))
    assert type(opened) is DelegationTreeBudget
    assert opened.ceilings == TreeCeilings(max_children=2)


_INVALID_CEILINGS = [
    pytest.param(
        config_name, raw, id=f"{config_name.removeprefix('delegation_tree_max_')}-{label}",
    )
    for config_name in _TREE_FIELDS
    for label, raw in (
        ("bool", True), ("str", "5"), ("float", 5.0), ("object", object()),
        ("zero", 0), ("negative", -1),
    )
] + [pytest.param("delegation_tree_max_tokens", 1023, id="tokens-below-minimum-grant")]


@pytest.mark.parametrize(("config_name", "raw"), _INVALID_CEILINGS)
def test_from_config_invalid_values_degrade_to_no_ceiling(config_name: str, raw: object) -> None:
    field_name, floor = _TREE_FIELDS[config_name]
    # Premise: the lowest valid value in this same slot opens a budget.
    valid = DelegationTreeBudget.from_config(SimpleNamespace(**{config_name: floor}))
    assert valid is not None and getattr(valid.ceilings, field_name) == floor

    ceilings = read_tree_ceilings(SimpleNamespace(**{config_name: raw}))

    assert getattr(ceilings, field_name) is None and ceilings.unbounded
    assert DelegationTreeBudget.from_config(SimpleNamespace(**{config_name: raw})) is None
    # One malformed ceiling does not discard a valid one beside it.
    other = next(name for name in _TREE_FIELDS if name != config_name)
    other_field, other_floor = _TREE_FIELDS[other]
    mixed = read_tree_ceilings(SimpleNamespace(**{config_name: raw, other: other_floor}))
    assert mixed == TreeCeilings(**{other_field: other_floor})


@pytest.mark.parametrize(("field_name", "value"), [
    ("max_tokens", MIN_DELEGATION_TOKEN_GRANT - 1), ("max_tokens", True),
    ("max_iterations", 0), ("max_iterations", 2.0),
    ("max_concurrent", "2"), ("max_concurrent", -1),
    ("max_children", False), ("max_children", 0),
])
def test_tree_ceilings_rejects_invalid_values(field_name: str, value: object) -> None:
    floor = MIN_DELEGATION_TOKEN_GRANT if field_name == "max_tokens" else 1
    # Premise: the floor itself is accepted, and no ceiling at all means unbounded.
    assert getattr(TreeCeilings(**{field_name: floor}), field_name) == floor
    assert TreeCeilings().unbounded and not TreeCeilings(**{field_name: floor}).unbounded

    with pytest.raises(ValueError, match=f"^delegation_tree_ceiling_invalid:{field_name}$"):
        TreeCeilings(**{field_name: value})


@pytest.mark.parametrize(("name", "floor", "ceiling"), [
    ("delegation_tree_max_tokens", 1024, None),
    ("delegation_tree_max_iterations", 1, 2500),
    ("delegation_tree_max_concurrent", 1, 16),
    ("delegation_tree_max_children", 1, 100),
])
def test_agentic_tools_config_tree_ceilings_default_none_and_bounds(
    name: str, floor: int, ceiling: int | None,
) -> None:
    assert getattr(AgenticToolsConfig(), name) is None
    assert getattr(AgenticToolsConfig(**{name: None}), name) is None
    assert getattr(AgenticToolsConfig(**{name: floor}), name) == floor
    with pytest.raises(ValidationError) as below:
        AgenticToolsConfig(**{name: floor - 1})
    assert {tuple(error["loc"]) for error in below.value.errors()} == {(name,)}
    if ceiling is None:
        # No upper bound, like crew_token_budget.
        assert getattr(AgenticToolsConfig(**{name: 10**12}), name) == 10**12
    else:
        assert getattr(AgenticToolsConfig(**{name: ceiling}), name) == ceiling
        with pytest.raises(ValidationError) as above:
            AgenticToolsConfig(**{name: ceiling + 1})
        assert {tuple(error["loc"]) for error in above.value.errors()} == {(name,)}


def test_system_yaml_leaves_tree_ceilings_unset() -> None:
    path = Path(__file__).resolve().parent.parent / "config" / "system.yaml"
    assert path.is_file()

    agentic = load_config(path).agentic_tools

    # Premise: the shipped file was really read -- a missing file loads defaults, delegation off.
    assert (agentic.delegation_enabled, agentic.delegation_max_depth) == (True, 1)
    assert [getattr(agentic, name) for name in _TREE_FIELDS] == [None, None, None, None]
    assert DelegationTreeBudget.from_config(agentic) is None


@pytest.mark.parametrize(("source", "expected"), [
    ({}, dict.fromkeys(_TREE_CONFIG)),
    (_TREE_CONFIG, _TREE_CONFIG),
], ids=["defaults", "all-set"])
def test_session_correction_projection_carries_tree_ceilings(
    tmp_path: Path, source: dict[str, int], expected: dict[str, int | None],
) -> None:
    runtime = _runtime(tmp_path, _LLM([]), **source)

    projection = _session_correction_runtime(
        runtime, agent_id="parent", department="science", rank="lieutenant",
    )

    projected = projection.config.agentic_tools
    assert type(projected) is _SessionAgenticToolsConfig
    assert {name: getattr(projected, name) for name in _TREE_FIELDS} == expected
    # The root reads the projection through the same normalizer, so it opens the same tree.
    assert read_tree_ceilings(projected) == read_tree_ceilings(runtime.config.agentic_tools)


def test_session_correction_projection_normalizes_invalid_tree_ceilings(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path, _LLM([]))
    runtime.config.agentic_tools = SimpleNamespace(
        tool_search_enabled=False, delegation_enabled=True, delegation_max_depth=1,
        delegation_max_iterations=5, delegation_tier="standard",
        delegation_tree_max_tokens=MIN_DELEGATION_TOKEN_GRANT - 1,
        delegation_tree_max_iterations=True, delegation_tree_max_concurrent="2",
        delegation_tree_max_children=2,
    )

    projected = _session_correction_runtime(
        runtime, agent_id="parent", department="science", rank="lieutenant",
    ).config.agentic_tools

    assert {name: getattr(projected, name) for name in _TREE_FIELDS} == {
        "delegation_tree_max_tokens": None, "delegation_tree_max_iterations": None,
        "delegation_tree_max_concurrent": None, "delegation_tree_max_children": 2,
    }


def test_session_agentic_tools_config_requires_every_tree_ceiling() -> None:
    required = [
        item.name for item in fields(_SessionAgenticToolsConfig)
        if item.default is MISSING and item.default_factory is MISSING
    ]

    # No default, so a future constructor cannot silently drop a ceiling.
    assert required[-4:] == list(_TREE_FIELDS)
    with pytest.raises(TypeError):
        _SessionAgenticToolsConfig(  # type: ignore[call-arg]
            tool_search_enabled=False, delegation_enabled=True, delegation_max_depth=1,
            delegation_max_iterations=5, delegation_tier="standard",
        )


async def test_session_correction_root_enforces_children_ceiling(tmp_path: Path) -> None:
    llm = _LLM([
        _calls(_delegate("d1", "task one"), _delegate("d2", "task two")),
        _text("child answer one"),
        _text("parent completed"),
    ])
    runtime = _runtime(tmp_path, llm, delegation_tree_max_children=1)
    projection = _session_correction_runtime(
        runtime, agent_id="parent", department="science", rank="lieutenant",
    )
    # Premise: the projection carries the ceiling but holds only a projected definition.
    assert projection.config.agentic_tools.delegation_tree_max_children == 1
    assert type(projection.tool_registry.get("delegate_task").tool) is _ProjectedToolDefinition

    outcome = await WorkItemAgenticExecutor(llm_client=llm).run(
        agent_id="parent", instructions="parent instructions", task_text="delegate the work",
        runtime=projection, department="science", rank="lieutenant", thread_id="thread",
        max_iterations=6,
    )

    assert not llm.responses
    assert _roles(llm) == ["parent", "child", "parent"]
    assert outcome.final_text == "parent completed"
    # Premise: both invocations crossed the projection into the SOURCE recording tool.
    contexts = runtime.delegator.contexts
    assert [ctx["agent_id"] for ctx in contexts] == ["parent", "parent"]
    budget = contexts[0][DELEGATION_TREE_BUDGET_KEY]
    assert type(budget) is DelegationTreeBudget
    assert contexts[1][DELEGATION_TREE_BUDGET_KEY] is budget
    assert budget.ceilings == TreeCeilings(max_children=1)
    first, second = runtime.delegator.results
    assert (first.output["delegated"], first.output["result"]) == (True, "child answer one")
    assert second.output == _children_refusal(1)
    assert second.evidence.status == "not_started"
    assert budget.usage().in_flight == 0


# ── A3, review round 1: a negative usage report, and a delegated context without its budget ──


_LOOP_LOGGER = "probos.cognitive.swe_harness.agentic_loop"


class _LoopTools:
    """Answers every loop tool call with ``ok``."""

    async def invoke(self, *, tool_id: str, **_kwargs: Any) -> ToolResult:
        return ToolResult(output="ok")


class _ServedLLM(_LLM):
    """Also records which scripted response answered each request."""

    def __init__(self, responses: list[Any]) -> None:
        super().__init__(responses)
        self.served: list[Any] = []

    async def complete(self, request: Any, **kwargs: Any) -> Any:
        response = await super().complete(request, **kwargs)
        self.served.append(response)
        return response


def _answer(usage: int) -> LLMResponse:
    return LLMResponse(
        content="an answer", content_blocks=[TextBlock(text="an answer")],
        tokens_used=usage, model="provider-model",
    )


def _no_output(usage: int) -> LLMResponse:
    return LLMResponse(content="", tokens_used=usage, model="provider-model")


async def _loop_run(
    responses: list[Any], *, token_budget: int | None = None, max_iterations: int = 3,
) -> Any:
    client: Any = _LLM(responses)
    tools: Any = _LoopTools()
    loop = AgenticLoop(
        llm_client=client, tool_executor=tools,
        max_iterations=max_iterations, token_budget=token_budget,
    )
    return await loop.run(
        system_prompt="sys", user_message="task", tools=[], context={"agent_id": "a1"},
    )


def _negative_usage_warnings(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [
        record for record in caplog.records
        if record.name == _LOOP_LOGGER and record.levelno == logging.WARNING
        and "negative token usage" in record.getMessage()
    ]


_LOOSE_BUDGET = 1_000_000


@pytest.mark.parametrize(("completion", "source"), [
    (_answer, TOKEN_SOURCE_ESTIMATED), (_no_output, TOKEN_SOURCE_MEASURED),
], ids=["beside-output", "beside-no-output"])
async def test_loop_run_budgeted_negative_reported_usage_is_charged_exactly_as_an_absent_report(
    caplog: pytest.LogCaptureFixture, completion: Callable[[int], LLMResponse], source: str,
) -> None:
    negative = completion(-500)
    # Premise: the provider response under test really reports a negative figure.
    assert negative.tokens_used == -500

    with caplog.at_level(logging.WARNING, logger=_LOOP_LOGGER):
        charged = await _loop_run([negative], token_budget=_LOOSE_BUDGET)
    warnings = _negative_usage_warnings(caplog)
    caplog.clear()
    with caplog.at_level(logging.WARNING, logger=_LOOP_LOGGER):
        absent = await _loop_run([completion(0)], token_budget=_LOOSE_BUDGET)

    # The absent report's own charge and label, never a subtraction.
    assert (charged.total_tokens, charged.token_source, charged.stopped_reason) == (
        absent.total_tokens, absent.token_source, absent.stopped_reason,
    )
    assert charged.stopped_reason == "complete"
    assert charged.token_source == source and charged.total_tokens >= 0
    assert (charged.total_tokens > 0) is (source == TOKEN_SOURCE_ESTIMATED)
    (warning,) = warnings
    message = warning.getMessage()
    for fragment in ("'provider-model'", "tier=", "(-500)", "iteration=1", "agent=a1", "token_budget"):
        assert fragment in message
    assert not _negative_usage_warnings(caplog)


@pytest.mark.parametrize("completion", [_answer, _no_output], ids=["beside-output", "beside-no-output"])
async def test_loop_run_unbudgeted_negative_reported_usage_is_charged_verbatim(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
    completion: Callable[[int], LLMResponse],
) -> None:
    def refuse_estimate(*_args: Any) -> int:
        raise AssertionError("an unbudgeted negative report must never reach the estimator")

    negative = completion(-500)
    # Premise: the provider response under test really reports a negative figure.
    assert negative.tokens_used == -500
    monkeypatch.setattr(agentic_loop_module, "_estimate_call_tokens", refuse_estimate)
    with caplog.at_level(logging.WARNING, logger=_LOOP_LOGGER):
        result = await _loop_run([negative], token_budget=None)

    # With no token_budget the repair stays off: HEAD's verbatim charge, and no WARNING.
    assert (result.total_tokens, result.token_source, result.stopped_reason) == (
        -500, TOKEN_SOURCE_MEASURED, "complete",
    )
    assert not [
        record for record in caplog.records
        if record.name == _LOOP_LOGGER and record.levelno >= logging.WARNING
    ]


async def test_loop_run_negative_reported_usage_still_stops_at_token_budget(
    caplog: pytest.LogCaptureFixture,
) -> None:
    turns = [
        LLMResponse(
            content="w" * 2000, tokens_used=-500, model="provider-model",
            content_blocks=[TextBlock(text="w" * 2000), _use("probe", {}, f"p{index}")],
        )
        for index in range(10)
    ]

    with caplog.at_level(logging.WARNING, logger=_LOOP_LOGGER):
        result = await _loop_run(turns, token_budget=4096, max_iterations=10)

    # Premise: every turn the run could be served reports a negative figure.
    assert {turn.tokens_used for turn in turns} == {-500}
    assert result.stopped_reason == "token_budget"
    assert result.total_tokens >= 4096 and result.iterations < 10
    assert result.token_source == TOKEN_SOURCE_ESTIMATED
    assert len(_negative_usage_warnings(caplog)) == result.iterations


@pytest.mark.parametrize(("completion", "reported"), [
    (_no_output, 0), (_answer, 1), (_answer, 500), (_answer, 3000),
], ids=["zero-beside-no-output", "one", "five-hundred", "three-thousand"])
async def test_loop_run_non_negative_reported_usage_is_charged_verbatim(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
    completion: Callable[[int], LLMResponse], reported: int,
) -> None:
    def refuse_estimate(*_args: Any) -> int:
        raise AssertionError("a non-negative report must never reach the estimator")

    # A zero beside output is BF-680's absent report, pinned in its own test file.
    monkeypatch.setattr(agentic_loop_module, "_estimate_call_tokens", refuse_estimate)
    with caplog.at_level(logging.WARNING, logger=_LOOP_LOGGER):
        result = await _loop_run([completion(reported)])

    assert (result.total_tokens, result.token_source, result.stopped_reason) == (
        reported, TOKEN_SOURCE_MEASURED, "complete",
    )
    assert not _negative_usage_warnings(caplog)


async def test_run_negative_child_usage_is_charged_so_the_token_ceiling_refuses_the_next_child(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    negative = _answer(-500)
    llm = _ServedLLM([
        _calls(_delegate("d1", "task one"), _delegate("d2", "task two")),
        negative,
        _text("parent completed"),
    ])
    runtime = _runtime(tmp_path, llm, delegation_tree_max_tokens=MIN_DELEGATION_TOKEN_GRANT)

    with caplog.at_level(logging.WARNING):
        outcome = await _parent(runtime, llm)

    # Premise: the first child's provider response really carried -500.
    assert _roles(llm)[1] == "child" and llm.served[1] is negative
    assert negative.tokens_used == -500
    assert _roles(llm) == ["parent", "child", "parent"]
    first, second = runtime.delegator.results
    assert first.output == {
        "delegated": True, "to": "Child", "result": "an answer", "stopped_reason": "complete",
    }
    budget = runtime.delegator.contexts[0][DELEGATION_TREE_BUDGET_KEY]
    spent = budget.usage().tokens_spent
    assert spent > 0
    assert second.output == _refusal(
        "tokens", ceiling=MIN_DELEGATION_TOKEN_GRANT, used=spent,
        required=MIN_DELEGATION_TOKEN_GRANT,
    )
    assert second.evidence.status == "not_started"
    assert outcome.final_text == "parent completed"
    # The child's loop charged its estimate and said so; nothing recorded an invalid total.
    (warning,) = _negative_usage_warnings(caplog)
    assert "agent=child" in warning.getMessage() and "(-500)" in warning.getMessage()
    assert not [r for r in caplog.records if "invalid token total" in r.getMessage()]


@pytest.mark.parametrize("config_name", list(_TREE_FIELDS))
async def test_run_depth_without_budget_under_configured_ceilings_raises_agentic_context_invalid(
    tmp_path: Path, config_name: str,
) -> None:
    llm = _LLM([_text("accepted")])
    runtime = _runtime(
        tmp_path, llm, tool_search_enabled=True, **{config_name: _TREE_FIELDS[config_name][1]},
    )
    # Premise: this configuration opens a tree, so a delegated run must carry its budget.
    assert DelegationTreeBudget.from_config(runtime.config.agentic_tools) is not None

    await _assert_boundary_refuses(runtime, llm, {"_delegation_depth": 1})

    # Refused before any side effect inside _run_reserved, not even an idempotent tool
    # registration; the caller's scoped browser-use reservation is released by its own finally.
    assert runtime.tool_registry.get("search_capabilities") is None
    # Premise: beside its budget the same depth is accepted, and that run does register.
    await _assert_boundary_accepts_exact_budget(runtime, llm)
    assert runtime.tool_registry.get("search_capabilities") is not None


async def test_run_depth_without_budget_and_no_ceilings_is_accepted(tmp_path: Path) -> None:
    llm = _LLM([_calls(_use("probe", {}, "p1")), _text("accepted")])
    runtime = _runtime(tmp_path, llm)
    # Premise: no ceiling is configured, so there is no tree to join.
    assert DelegationTreeBudget.from_config(runtime.config.agentic_tools) is None

    outcome = await _run_child(runtime, llm, {"_delegation_depth": 1})

    assert (outcome.final_text, llm.responses) == ("accepted", [])
    (probe_ctx,) = runtime.probe.contexts
    assert probe_ctx["_delegation_depth"] == 1
    assert DELEGATION_TREE_BUDGET_KEY not in probe_ctx


async def test_invoke_without_budget_under_configured_ceilings_returns_delegation_failed(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    llm = _LLM([_text("child answer")])
    runtime = _runtime(tmp_path, llm, delegation_tree_max_children=1)

    with caplog.at_level(logging.WARNING, logger=_TOOL_LOGGER):
        result = await runtime.delegator.invoke(
            _CHILD_PARAMS, {"agent_id": "parent", "thread_id": "thread"},
        )

    # The tool's existing never-raise failure shape; the nested run made no model call.
    assert result.error == "delegation_failed: agentic_context_invalid"
    assert (result.output, result.metadata) == (None, {})
    assert result.evidence.status == "failed"
    assert not llm.requests and len(llm.responses) == 1
    # Premise: the nested run was entered and refused at its own boundary.
    (failure,) = [
        record for record in caplog.records
        if record.name == _TOOL_LOGGER and "delegation failed" in record.getMessage()
    ]
    assert failure.exc_info is not None and isinstance(failure.exc_info[1], ValueError)


# ── A4, review round 2: an unmeasured empty completion is not free to the tree ──


def _record_settles(monkeypatch: pytest.MonkeyPatch) -> list[tuple[object, object, object, int]]:
    """Record each settle's reported usage and stop, and the tree's tokens spent right after."""
    settled: list[tuple[object, object, object, int]] = []
    original_settle = DelegationTreeBudget.settle

    def recording_settle(self: DelegationTreeBudget, grant: TreeGrant, **usage: object) -> None:
        original_settle(self, grant, **usage)
        settled.append((
            usage["tokens_used"], usage["iterations_used"],
            usage.get("stopped_reason", "<not passed>"), self.usage().tokens_spent,
        ))

    monkeypatch.setattr(DelegationTreeBudget, "settle", recording_settle)
    return settled


@pytest.mark.parametrize("reported", [0, -500], ids=["zero", "negative"])
async def test_run_empty_unmeasured_child_completion_is_charged_so_the_next_child_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
    reported: int,
) -> None:
    empty = _no_output(reported)
    llm = _ServedLLM([
        _calls(_delegate("d1", "task one"), _delegate("d2", "task two")),
        empty,
        _text("parent completed"),
    ])
    runtime = _runtime(tmp_path, llm, delegation_tree_max_tokens=MIN_DELEGATION_TOKEN_GRANT)
    outcomes: list[tuple[str, WorkItemAgenticOutcome]] = []
    original_run = WorkItemAgenticExecutor.run

    async def recording_run(self: Any, **kwargs: Any) -> WorkItemAgenticOutcome:
        outcome = await original_run(self, **kwargs)
        outcomes.append((kwargs["agent_id"], outcome))
        return outcome

    monkeypatch.setattr(WorkItemAgenticExecutor, "run", recording_run)
    settled = _record_settles(monkeypatch)

    with caplog.at_level(logging.WARNING):
        outcome = await _parent(runtime, llm)

    # Premise: the first child's only call was an empty completion reporting this figure,
    assert _roles(llm)[1] == "child" and llm.served[1] is empty
    assert (empty.content, list(empty.content_blocks or []), empty.tokens_used) == (
        "", [], reported,
    )
    # and its outcome carried no measured spend for its one iteration.
    child_outcomes = [result for agent, result in outcomes if agent == "child"]
    assert (child_outcomes[0].total_tokens, child_outcomes[0].iterations) == (0, 1)
    # Charged its whole grant rather than nothing, which leaves no room for a second child.
    assert settled == [(0, 1, "complete", MIN_DELEGATION_TOKEN_GRANT)]
    first, second = runtime.delegator.results
    assert first.output == {
        "delegated": True, "to": "Child", "result": "", "stopped_reason": "complete",
    }
    assert second.output == _refusal(
        "tokens", ceiling=MIN_DELEGATION_TOKEN_GRANT, used=MIN_DELEGATION_TOKEN_GRANT,
        required=MIN_DELEGATION_TOKEN_GRANT,
    )
    assert second.evidence.status == "not_started"
    assert _roles(llm) == ["parent", "child", "parent"]
    assert outcome.final_text == "parent completed"
    (warning,) = _budget_warnings(caplog)
    assert f"tokens_used=0 charged as {MIN_DELEGATION_TOKEN_GRANT}" in warning.getMessage()


async def test_run_final_empty_unmeasured_call_adds_nothing_to_a_measured_child_charge(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
) -> None:
    empty = _no_output(0)
    llm = _ServedLLM([
        _calls(_delegate("d1")),
        _Response(content_blocks=[_use("probe", {}, "p1")], tokens_used=500),
        empty,
        _text("parent completed"),
    ])
    runtime = _runtime(tmp_path, llm, delegation_tree_max_tokens=4096)
    settled = _record_settles(monkeypatch)

    with caplog.at_level(logging.WARNING, logger=_BUDGET_LOGGER):
        outcome = await _parent(runtime, llm)

    # Premise: the child made a measured tool call, then ended on the unmeasured empty one.
    assert _roles(llm) == ["parent", "child", "child", "parent"] and not llm.responses
    assert llm.served[2] is empty and len(runtime.probe.contexts) == 1
    assert outcome.final_text == "parent completed"
    # The documented residual: its total is trusted, so that final call is charged nothing.
    assert settled == [(500, 2, "complete", 500)]
    assert not _budget_warnings(caplog)


# ── A5, review round 3: a run that stops uncleanly is charged at least its whole grant ──


def _stop_reasons_assigned(scope: ast.AST) -> set[str]:
    """Each value assigned to a ``stopped_reason`` anywhere under ``scope``, as source."""
    found: set[str] = set()
    for node in ast.walk(scope):
        if isinstance(node, ast.keyword) and node.arg == "stopped_reason":
            found.add(ast.unparse(node.value))
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if getattr(target, "attr", getattr(target, "id", None)) == "stopped_reason":
                    found.add(ast.unparse(node.value) if node.value is not None else "<bare>")
    return found


def test_settle_clean_stops_are_the_loop_census_without_its_error_stop() -> None:
    # Premise: the census sees an annotated default, an attribute store and a keyword.
    probe = ast.parse(
        'class R:\n    stopped_reason: str = "a"\n'
        'r.stopped_reason = "b"\nR(stopped_reason="c")\n'
    )
    assert _stop_reasons_assigned(probe) == {"'a'", "'b'", "'c'"}
    loop_census = _stop_reasons_assigned(ast.parse(inspect.getsource(agentic_loop_module)))
    executor_census = _stop_reasons_assigned(ast.parse(inspect.getsource(WorkItemAgenticExecutor)))

    # A new loop stop reason fails here first, so it is classified before it ships.
    assert loop_census == {"'complete'", "'error'", "'max_iterations'", "'token_budget'"}
    # The executor originates none: every outcome it builds carries the loop's own.
    assert executor_census == {"agentic_result.stopped_reason"}
    for reason in sorted(ast.literal_eval(value) for value in loop_census):
        budget = DelegationTreeBudget(TreeCeilings(max_tokens=4096))
        grant = _admit(budget)
        assert isinstance(grant, TreeGrant)
        budget.settle(grant, tokens_used=500, iterations_used=1, stopped_reason=reason)
        assert budget.usage().tokens_spent == (4096 if reason == "error" else 500), reason


@pytest.mark.parametrize("stopped_reason", ["complete", "max_iterations", "token_budget"])
@pytest.mark.parametrize("reported", [500, 5000], ids=["under-grant", "past-grant"])
def test_settle_clean_stop_charges_the_counted_total(
    caplog: pytest.LogCaptureFixture, stopped_reason: str, reported: int,
) -> None:
    budget = DelegationTreeBudget(TreeCeilings(max_tokens=4096))
    grant = _admit(budget)
    assert isinstance(grant, TreeGrant) and grant.token_budget == 4096

    with caplog.at_level(logging.WARNING, logger=_BUDGET_LOGGER):
        budget.settle(
            grant, tokens_used=reported, iterations_used=2, stopped_reason=stopped_reason,
        )

    assert (budget.usage().tokens_spent, budget.usage().iterations_spent) == (reported, 2)
    assert not _budget_warnings(caplog)


class _StopLike(str):
    """Equal to a clean stop reason, but not exactly a ``str``."""


@pytest.mark.parametrize(("stopped_reason", "shown"), [
    ("error", "'error'"), ("", "''"), ("cancelled", "'cancelled'"), (None, "None"),
    (1, "<not a str>"), (_StopLike("complete"), "<not a str>"),
], ids=["error", "empty", "unknown", "none", "not-a-str", "str-subclass"])
@pytest.mark.parametrize(("reported", "charged"), [
    (500, 4096), (5000, 5000), (None, 4096),
], ids=["under-grant", "past-grant", "unknown-usage"])
def test_settle_unclean_stop_charges_at_least_the_whole_token_grant(
    caplog: pytest.LogCaptureFixture, stopped_reason: object, shown: str,
    reported: int | None, charged: int,
) -> None:
    budget = DelegationTreeBudget(TreeCeilings(max_tokens=4096))
    grant = _admit(budget)
    assert isinstance(grant, TreeGrant) and grant.token_budget == 4096

    with caplog.at_level(logging.WARNING, logger=_BUDGET_LOGGER):
        budget.settle(
            grant, tokens_used=reported, iterations_used=2, stopped_reason=stopped_reason,
        )

    usage = budget.usage()
    # The larger of a valid counted total and the grant; iterations stay as counted.
    assert (usage.tokens_spent, usage.iterations_spent, usage.in_flight) == (charged, 2, 0)
    (warning,) = _budget_warnings(caplog)
    message = warning.getMessage()
    assert (
        f"tokens_used={reported!r} charged as {charged} "
        f"(stopped_reason={shown} is not a clean stop)"
    ) in message
    assert "iterations_used=" not in message


@pytest.mark.parametrize(("reported", "charged"), [(500, 500), (None, 0)])
def test_settle_unclean_stop_without_a_token_grant_charges_the_counted_total_quietly(
    caplog: pytest.LogCaptureFixture, reported: int | None, charged: int,
) -> None:
    budget = DelegationTreeBudget(TreeCeilings(max_children=2))
    grant = _admit(budget)
    assert isinstance(grant, TreeGrant) and grant.token_budget is None

    with caplog.at_level(logging.WARNING, logger=_BUDGET_LOGGER):
        budget.settle(grant, tokens_used=reported, iterations_used=1, stopped_reason="error")

    assert (budget.usage().tokens_spent, budget.usage().iterations_spent) == (charged, 1)
    assert not _budget_warnings(caplog)


class _ScriptedLLM(_ServedLLM):
    """Raises a scripted exception in place of a response, after recording the request."""

    async def complete(self, request: Any, **kwargs: Any) -> Any:
        response = await super().complete(request, **kwargs)
        if isinstance(response, Exception):
            raise response
        return response


def _record_runs(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, WorkItemAgenticOutcome]]:
    """Record each executor run's agent and the outcome it returned."""
    outcomes: list[tuple[str, WorkItemAgenticOutcome]] = []
    original_run = WorkItemAgenticExecutor.run

    async def recording_run(self: Any, **kwargs: Any) -> WorkItemAgenticOutcome:
        outcome = await original_run(self, **kwargs)
        outcomes.append((kwargs["agent_id"], outcome))
        return outcome

    monkeypatch.setattr(WorkItemAgenticExecutor, "run", recording_run)
    return outcomes


def _fail_presentation_of_budgeted_loops(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    """Build every loop that has a token budget with a presentation hook that raises.

    Only an owned-steps turn wires this hook in production. It is the loop's one error
    exit that fires after a call's usage was counted and before that call's budget check.
    """
    hooked: list[int] = []

    async def refuse(_request: Any, _presented: Any) -> None:
        raise RuntimeError("presenting a measured response failed")

    class _HookedLoop(AgenticLoop):
        def __init__(self, **kwargs: Any) -> None:
            if kwargs.get("token_budget") is not None:
                hooked.append(kwargs["token_budget"])
                kwargs["on_model_request_presented"] = refuse
            super().__init__(**kwargs)

    monkeypatch.setattr(agentic_loop_module, "AgenticLoop", _HookedLoop)
    return hooked


async def test_run_child_erroring_after_counted_usage_is_charged_its_whole_token_grant(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
) -> None:
    failure = RuntimeError("the provider accepted the request, then failed")
    llm = _ScriptedLLM([
        _calls(_delegate("d1", "task one"), _delegate("d2", "task two")),
        _Response(content_blocks=[_use("probe", {}, "p1")], tokens_used=500),
        failure,
        _text("parent completed"),
    ])
    runtime = _runtime(tmp_path, llm, delegation_tree_max_tokens=2048)
    outcomes = _record_runs(monkeypatch)
    settled = _record_settles(monkeypatch)

    with caplog.at_level(logging.WARNING):
        outcome = await _parent(runtime, llm)

    # Premise: the first child counted 500 tokens on a tool call, then its next model
    # call raised, so its own loop stopped with "error" on its second iteration.
    assert _roles(llm)[:3] == ["parent", "child", "child"] and llm.served[2] is failure
    child = [result for agent, result in outcomes if agent == "child"][0]
    assert (child.stopped_reason, child.total_tokens, child.iterations) == ("error", 500, 2)
    first, second = runtime.delegator.results
    assert first.output == {
        "delegated": True, "to": "Child", "result": "", "stopped_reason": "error",
    }
    assert first.evidence.status == "failed"
    # The failed call may have been billed without being counted, so the whole grant is.
    assert second.output == _refusal("tokens", ceiling=2048, used=2048, required=1024)
    assert second.evidence.status == "not_started"
    assert _roles(llm) == ["parent", "child", "child", "parent"] and not llm.responses
    assert outcome.final_text == "parent completed"
    assert settled == [(500, 2, "error", 2048)]
    (warning,) = _budget_warnings(caplog)
    assert (
        "tokens_used=500 charged as 2048 (stopped_reason='error' is not a clean stop)"
        in warning.getMessage()
    )


async def test_run_child_erroring_after_counting_past_its_grant_is_charged_that_total(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
) -> None:
    over = _Response(
        content="partial", content_blocks=[TextBlock(text="partial")], tokens_used=3000,
    )
    llm = _ServedLLM([
        _calls(_delegate("d1", "task one"), _delegate("d2", "task two")),
        over,
        _text("parent completed"),
    ])
    runtime = _runtime(tmp_path, llm, delegation_tree_max_tokens=2048)
    hooked = _fail_presentation_of_budgeted_loops(monkeypatch)
    outcomes = _record_runs(monkeypatch)
    settled = _record_settles(monkeypatch)

    with caplog.at_level(logging.WARNING):
        outcome = await _parent(runtime, llm)

    # Premise: only the child's loop, built with its 2048-token grant, had the failing hook,
    assert hooked == [2048] and llm.served[1] is over
    (presentation_failure,) = [
        record for record in caplog.records
        if "presentation acknowledgement failed" in record.getMessage()
    ]
    assert "agent=child" in presentation_failure.getMessage()
    # and it counted its one 3000-token call, past that grant, before stopping with "error".
    child = [result for agent, result in outcomes if agent == "child"][0]
    assert (child.stopped_reason, child.total_tokens, child.iterations) == ("error", 3000, 1)
    first, second = runtime.delegator.results
    assert (first.output["delegated"], first.output["stopped_reason"]) == (True, "error")
    # The counted total is larger than the grant, so it is kept rather than cut back to it.
    assert second.output == _refusal("tokens", ceiling=2048, used=3000, required=1024)
    assert _roles(llm) == ["parent", "child", "parent"] and not llm.responses
    assert outcome.final_text == "parent completed"
    assert settled == [(3000, 1, "error", 3000)]
    (warning,) = _budget_warnings(caplog)
    assert (
        "tokens_used=3000 charged as 3000 (stopped_reason='error' is not a clean stop)"
        in warning.getMessage()
    )


async def test_run_children_only_ceiling_unmeasured_empty_child_logs_no_budget_warning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
) -> None:
    empty = _no_output(0)
    llm = _ServedLLM([_calls(_delegate("d1")), empty, _text("parent completed")])
    runtime = _runtime(tmp_path, llm, delegation_tree_max_children=1)
    outcomes = _record_runs(monkeypatch)
    settled = _record_settles(monkeypatch)

    with caplog.at_level(logging.WARNING, logger=_BUDGET_LOGGER):
        outcome = await _parent(runtime, llm)

    # Premise: the child's only call was an empty completion reporting 0, in a tree with
    # no token ceiling, so it held no token grant for that zero to be charged against.
    assert _roles(llm) == ["parent", "child", "parent"] and llm.served[1] is empty
    child = [result for agent, result in outcomes if agent == "child"][0]
    assert (child.stopped_reason, child.total_tokens, child.iterations) == ("complete", 0, 1)
    budget = runtime.delegator.contexts[0][DELEGATION_TREE_BUDGET_KEY]
    assert budget.ceilings == TreeCeilings(max_children=1)
    assert outcome.final_text == "parent completed"
    # Nothing was substituted, so nothing is worth a WARNING.
    assert not _budget_warnings(caplog)
    assert settled == [(0, 1, "complete", 0)]
