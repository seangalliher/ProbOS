"""AD-858: tests for LLMPlanDecomposer.

Uses ``_Fake*`` stubs (not MagicMock) at the substrate boundary so attribute
lookups hit real shapes. No network. The critical bridge test invokes
``decompose`` from inside a running event loop to prove the sync->async thread
bridge does not raise ``RuntimeError: asyncio.run() cannot be called from a
running event loop``.
"""
from __future__ import annotations

import asyncio
import inspect
import json

from probos.consultation.dispatch import (
    MarkdownPlanDecomposer,
    PlanDecomposer,
    WorkItemSpec,
)
from probos.consultation.llm_decomposer import LLMPlanDecomposer
from probos.types import LLMRequest, LLMResponse


class _FakeLLMClient:
    """Returns a canned ``LLMResponse``; records the request it received."""

    def __init__(self, *, content: str = "", error: str | None = None) -> None:
        self._content = content
        self._error = error
        self.requests: list[LLMRequest] = []

    async def complete(self, request: LLMRequest, **_kwargs: Any) -> LLMResponse:
        self.requests.append(request)
        return LLMResponse(content=self._content, error=self._error)


class _RaisingLLMClient:
    """Raises inside ``complete`` to exercise the honest-degrade path."""

    async def complete(self, request: LLMRequest, **_kwargs: Any) -> LLMResponse:  # noqa: ARG002
        raise RuntimeError("boom")


def _payload(items: list[dict]) -> str:
    return json.dumps(items)


def test_decompose_happy_path_builds_dag_with_valid_deps() -> None:
    content = _payload(
        [
            {"spec_id": "research", "title": "Research the topic", "depends_on": []},
            {"spec_id": "draft", "title": "Draft the report", "depends_on": ["research"]},
            {"spec_id": "review", "title": "Review the draft", "depends_on": ["draft"]},
        ]
    )
    dec = LLMPlanDecomposer(_FakeLLMClient(content=content))

    specs = dec.decompose("Write a report on X")

    assert [s.spec_id for s in specs] == ["research", "draft", "review"]
    assert specs[0].depends_on == ()
    assert specs[1].depends_on == ("research",)
    assert specs[2].depends_on == ("draft",)


def test_decompose_carries_expected_output_when_present() -> None:
    content = _payload(
        [
            {
                "spec_id": "a",
                "title": "Do the thing",
                "depends_on": [],
                "expected_output": "A passing test suite.",
            }
        ]
    )
    dec = LLMPlanDecomposer(_FakeLLMClient(content=content))

    specs = dec.decompose("Make it work")

    assert specs[0].expected_output == "A passing test suite."


def test_decompose_expected_output_omitted_defaults_to_none() -> None:
    content = _payload([{"spec_id": "a", "title": "Do the thing", "depends_on": []}])
    dec = LLMPlanDecomposer(_FakeLLMClient(content=content))

    specs = dec.decompose("Make it work")

    assert specs[0].expected_output is None


def test_decompose_repairs_dangling_dependency_edge() -> None:
    content = _payload(
        [
            {"spec_id": "a", "title": "First", "depends_on": []},
            {"spec_id": "b", "title": "Second", "depends_on": ["a", "ghost"]},
        ]
    )
    dec = LLMPlanDecomposer(_FakeLLMClient(content=content))

    specs = dec.decompose("goal")

    by_id = {s.spec_id: s for s in specs}
    # "ghost" references no emitted spec_id and is dropped; "a" is kept.
    assert by_id["b"].depends_on == ("a",)


def test_decompose_cycle_degrades_to_single_passthrough() -> None:
    content = _payload(
        [
            {"spec_id": "a", "title": "First", "depends_on": ["b"]},
            {"spec_id": "b", "title": "Second", "depends_on": ["a"]},
        ]
    )
    dec = LLMPlanDecomposer(_FakeLLMClient(content=content))

    specs = dec.decompose("Cyclic goal")

    assert len(specs) == 1
    assert specs[0].description == "Cyclic goal"
    assert specs[0].depends_on == ()


def test_decompose_enforces_max_subtasks_cap() -> None:
    content = _payload(
        [{"spec_id": f"s{i}", "title": f"Task {i}", "depends_on": []} for i in range(10)]
    )
    dec = LLMPlanDecomposer(_FakeLLMClient(content=content), max_subtasks=3)

    specs = dec.decompose("Big goal")

    assert len(specs) == 3


def test_decompose_garbage_output_returns_passthrough_not_crash() -> None:
    dec = LLMPlanDecomposer(_FakeLLMClient(content="not json at all {{{"))

    specs = dec.decompose("Some goal")

    assert len(specs) == 1
    assert specs[0].description == "Some goal"


def test_decompose_empty_goal_returns_single_passthrough() -> None:
    dec = LLMPlanDecomposer(_FakeLLMClient(content=_payload([{"spec_id": "x", "title": "x"}])))

    specs = dec.decompose("   ")

    assert len(specs) == 1
    assert specs[0].depends_on == ()


def test_decompose_llm_error_returns_passthrough() -> None:
    dec = LLMPlanDecomposer(_FakeLLMClient(content="", error="model unavailable"))

    specs = dec.decompose("Goal under error")

    assert len(specs) == 1
    assert specs[0].description == "Goal under error"


def test_decompose_raising_client_returns_passthrough() -> None:
    dec = LLMPlanDecomposer(_RaisingLLMClient())

    specs = dec.decompose("Goal under exception")

    assert len(specs) == 1
    assert specs[0].description == "Goal under exception"


def test_decompose_tolerates_json_fenced_output() -> None:
    inner = _payload([{"spec_id": "a", "title": "Do it", "depends_on": []}])
    content = f"Here is the plan:\n```json\n{inner}\n```\nDone."
    dec = LLMPlanDecomposer(_FakeLLMClient(content=content))

    specs = dec.decompose("goal")

    assert [s.spec_id for s in specs] == ["a"]


def test_llm_plan_decomposer_satisfies_protocol() -> None:
    # Structural conformance: PlanDecomposer is a (non-runtime_checkable)
    # Protocol, so verify the method shape and a valid static assignment.
    sig = inspect.signature(LLMPlanDecomposer.decompose)
    assert list(sig.parameters) == ["self", "markdown_text"]

    dec: PlanDecomposer = LLMPlanDecomposer(
        _FakeLLMClient(content=_payload([{"spec_id": "a", "title": "x"}]))
    )
    assert callable(dec.decompose)


def test_markdown_decomposer_still_emits_none_expected_output() -> None:
    dec = MarkdownPlanDecomposer()

    specs = dec.decompose("## Task one\n\nDo the first thing.\n\n## Task two\n\nDo the second.\n")

    assert specs, "MarkdownPlanDecomposer should still parse ATX-2 headings"
    assert all(isinstance(s, WorkItemSpec) for s in specs)
    assert all(s.expected_output is None for s in specs)


def test_decompose_runs_from_inside_running_event_loop() -> None:
    """CRITICAL: ParallelDispatcher.dispatch calls decompose() inline from a
    running loop. The thread bridge must not raise.
    """
    content = _payload([{"spec_id": "a", "title": "Do it", "depends_on": []}])
    dec = LLMPlanDecomposer(_FakeLLMClient(content=content))

    async def _driver() -> list[WorkItemSpec]:
        # Synchronous call from within an active event loop.
        return dec.decompose("goal from inside the loop")

    specs = asyncio.run(_driver())

    assert [s.spec_id for s in specs] == ["a"]
