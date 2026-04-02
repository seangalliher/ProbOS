"""AD-537: Observational extraction tests.

Tests cover extract_procedure_from_observation() — the function that
analyzes Ward Room discussion threads and extracts procedures an
observer agent can learn from.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from probos.cognitive.procedures import (
    Procedure,
    extract_procedure_from_observation,
    _OBSERVATION_SYSTEM_PROMPT,
)


# ---------------------------------------------------------------------------
# Mock LLM helpers
# ---------------------------------------------------------------------------

_VALID_OBSERVATION_JSON = json.dumps({
    "detail_score": 0.8,
    "name": "Test Procedure",
    "description": "Observed from test_agent's discussion about testing.",
    "steps": [
        {
            "step_number": 1,
            "action": "do thing",
            "expected_input": "",
            "expected_output": "",
            "fallback_action": "",
            "invariants": [],
        },
    ],
    "preconditions": [],
    "postconditions": [],
})

_LOW_DETAIL_JSON = json.dumps({
    "detail_score": 0.3,
    "error": "insufficient_detail",
})


def _mock_llm_response(content: str) -> MagicMock:
    resp = MagicMock()
    resp.content = content
    return resp


class MockLLMClient:
    """Async LLM client that returns a canned response."""

    def __init__(self, response_json: str) -> None:
        self._response_json = response_json

    async def complete(self, request: object) -> MagicMock:
        return _mock_llm_response(self._response_json)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_extract_from_detailed_thread():
    """LLM returns detail_score=0.8 with procedure -> procedure extracted."""
    client = MockLLMClient(_VALID_OBSERVATION_JSON)
    result = await extract_procedure_from_observation(
        thread_content="LaForge: Here's exactly how to recalibrate the EPS conduit...",
        observer_agent_type="EngineeringAgent",
        author_callsign="LaForge",
        author_trust=0.75,
        llm_client=client,
    )
    assert result is not None
    assert isinstance(result, Procedure)
    assert result.name == "Test Procedure"
    assert len(result.steps) == 1
    assert result.steps[0].action == "do thing"


@pytest.mark.asyncio
async def test_extract_from_vague_thread():
    """LLM returns detail_score=0.3 with error -> returns None."""
    client = MockLLMClient(_LOW_DETAIL_JSON)
    result = await extract_procedure_from_observation(
        thread_content="Data: I believe the solution involves some sort of adjustment.",
        observer_agent_type="ScienceAgent",
        author_callsign="Data",
        author_trust=0.70,
        llm_client=client,
    )
    assert result is None


@pytest.mark.asyncio
async def test_learned_via_observational():
    """Extracted procedure has learned_via='observational'."""
    client = MockLLMClient(_VALID_OBSERVATION_JSON)
    result = await extract_procedure_from_observation(
        thread_content="Detailed procedure discussion...",
        observer_agent_type="SecurityAgent",
        author_callsign="Worf",
        author_trust=0.80,
        llm_client=client,
    )
    assert result is not None
    assert result.learned_via == "observational"


@pytest.mark.asyncio
async def test_learned_from_populated():
    """Extracted procedure has learned_from=author_callsign."""
    client = MockLLMClient(_VALID_OBSERVATION_JSON)
    result = await extract_procedure_from_observation(
        thread_content="Detailed procedure discussion...",
        observer_agent_type="OperationsAgent",
        author_callsign="OBrien",
        author_trust=0.65,
        llm_client=client,
    )
    assert result is not None
    assert result.learned_from == "OBrien"


@pytest.mark.asyncio
async def test_compilation_level_always_1():
    """Observed procedures always start at compilation Level 1 (Novice)."""
    client = MockLLMClient(_VALID_OBSERVATION_JSON)
    result = await extract_procedure_from_observation(
        thread_content="Detailed procedure discussion...",
        observer_agent_type="EngineeringAgent",
        author_callsign="LaForge",
        author_trust=0.90,
        llm_client=client,
    )
    assert result is not None
    assert result.compilation_level == 1


@pytest.mark.asyncio
async def test_trust_threshold_filter():
    """The function itself does not filter by author trust — that is the
    dream step's responsibility.  Verify extraction succeeds even with
    low trust values."""
    client = MockLLMClient(_VALID_OBSERVATION_JSON)
    result = await extract_procedure_from_observation(
        thread_content="Detailed procedure discussion...",
        observer_agent_type="ScienceAgent",
        author_callsign="Wesley",
        author_trust=0.10,  # Very low trust — function should not reject
        llm_client=client,
    )
    assert result is not None
    assert result.learned_from == "Wesley"


@pytest.mark.asyncio
async def test_self_observation_skip():
    """Self-observation filtering is the dream step's responsibility, not
    this function.  Verify the function works when observer matches author."""
    client = MockLLMClient(_VALID_OBSERVATION_JSON)
    result = await extract_procedure_from_observation(
        thread_content="Detailed procedure discussion...",
        observer_agent_type="SecurityAgent",
        author_callsign="SecurityAgent",
        author_trust=0.80,
        llm_client=client,
    )
    assert result is not None
    assert result.learned_from == "SecurityAgent"


@pytest.mark.asyncio
async def test_teaching_format_detection():
    """is_teaching=True -> learned_via='taught', compilation_level=2."""
    client = MockLLMClient(_VALID_OBSERVATION_JSON)
    result = await extract_procedure_from_observation(
        thread_content="Teaching DM: Here is how to perform a level-5 diagnostic...",
        observer_agent_type="EngineeringAgent",
        author_callsign="LaForge",
        author_trust=0.90,
        llm_client=client,
        is_teaching=True,
    )
    assert result is not None
    assert result.learned_via == "taught"
    assert result.compilation_level == 2


@pytest.mark.asyncio
async def test_observation_provenance_tags():
    """Extracted procedure has empty provenance — tags added by dream step."""
    client = MockLLMClient(_VALID_OBSERVATION_JSON)
    result = await extract_procedure_from_observation(
        thread_content="Detailed procedure discussion...",
        observer_agent_type="OperationsAgent",
        author_callsign="OBrien",
        author_trust=0.70,
        llm_client=client,
    )
    assert result is not None
    assert result.provenance == []


def test_observation_system_prompt_includes_read_only():
    """Verify _OBSERVATION_SYSTEM_PROMPT contains 'READ-ONLY' guard."""
    # Not async — just inspecting the constant
    assert "READ-ONLY" in _OBSERVATION_SYSTEM_PROMPT
