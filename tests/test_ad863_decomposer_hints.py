"""AD-863: tests for capability + department hints on WorkItemSpec.

The decomposer stays a pure NL->DAG mapper; AD-863 only adds two optional
advisory hints per sub-task (``capability`` and ``department``) so the AD-864
resolver can pick a qualified agent. These tests use a fake LLM client (fakes
are fine at the LLM boundary) and exercise parsing, normalization, ``to_dict``
round-trips, DAG-repair preservation, the passthrough fallback, and backward
compatibility with hint-free raw elements.
"""
from __future__ import annotations

import json

from probos.consultation.dispatch import WorkItemSpec
from probos.consultation.llm_decomposer import LLMPlanDecomposer
from probos.types import LLMRequest, LLMResponse


class _FakeLLMClient:
    """Returns a canned ``LLMResponse``; records the request it received."""

    def __init__(self, *, content: str = "", error: str | None = None) -> None:
        self._content = content
        self._error = error
        self.requests: list[LLMRequest] = []

    async def complete(self, request: LLMRequest) -> LLMResponse:
        self.requests.append(request)
        return LLMResponse(content=self._content, error=self._error)


def _payload(items: list[dict]) -> str:
    return json.dumps(items)


def test_capability_and_department_parsed_and_carried() -> None:
    content = _payload(
        [
            {
                "spec_id": "research",
                "title": "Research the topic",
                "depends_on": [],
                "capability": "web research",
                "department": "science",
            }
        ]
    )
    dec = LLMPlanDecomposer(_FakeLLMClient(content=content))

    specs = dec.decompose("Investigate X")

    assert specs[0].capability == "web research"
    assert specs[0].department == "science"


def test_missing_null_and_empty_hints_normalize_to_none() -> None:
    content = _payload(
        [
            # Missing both keys entirely.
            {"spec_id": "a", "title": "First task", "depends_on": []},
            # Explicit null.
            {
                "spec_id": "b",
                "title": "Second task",
                "depends_on": [],
                "capability": None,
                "department": None,
            },
            # Empty / whitespace strings.
            {
                "spec_id": "c",
                "title": "Third task",
                "depends_on": [],
                "capability": "   ",
                "department": "",
            },
        ]
    )
    dec = LLMPlanDecomposer(_FakeLLMClient(content=content))

    specs = dec.decompose("Do three things")

    for spec in specs:
        assert spec.capability is None
        assert spec.department is None


def test_to_dict_round_trips_capability_and_department() -> None:
    spec = WorkItemSpec(
        spec_id="x",
        title="Build the widget",
        capability="write code",
        department="engineering",
    )

    payload = spec.to_dict()

    assert payload["capability"] == "write code"
    assert payload["department"] == "engineering"
    assert "expected_output" in payload  # existing keys preserved
    assert payload["spec_id"] == "x"


def test_with_deps_preserves_hints_through_dag_repair() -> None:
    # The dangling dependency ``ghost`` is repaired away by ``_validate_dag``,
    # which routes the spec through ``_with_deps``; the hints must survive.
    content = _payload(
        [
            {
                "spec_id": "only",
                "title": "Do the work",
                "depends_on": ["ghost"],
                "capability": "analyze data",
                "department": "operations",
            }
        ]
    )
    dec = LLMPlanDecomposer(_FakeLLMClient(content=content))

    specs = dec.decompose("Analyze the dataset")

    assert specs[0].depends_on == ()  # dangling edge dropped
    assert specs[0].capability == "analyze data"
    assert specs[0].department == "operations"


def test_passthrough_carries_none_hints() -> None:
    # Empty goal forces the honest-degrade passthrough path.
    dec = LLMPlanDecomposer(_FakeLLMClient(content=""))

    specs = dec.decompose("")

    assert len(specs) == 1
    assert specs[0].capability is None
    assert specs[0].department is None


def test_backward_compat_hint_free_element_builds_valid_spec() -> None:
    content = _payload(
        [{"spec_id": "legacy", "title": "Legacy task", "depends_on": []}]
    )
    dec = LLMPlanDecomposer(_FakeLLMClient(content=content))

    specs = dec.decompose("Run the legacy flow")

    assert specs[0].spec_id == "legacy"
    assert specs[0].capability is None
    assert specs[0].department is None
    assert specs[0].expected_output is None
