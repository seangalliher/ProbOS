"""AD-1326 (#1510), milestone 2: the rewrite tier (``cognitive/procedures.py``).

Procedure REWRITING (FIX and DERIVED evolution) is the optimizer and runs on ``deep`` with a
``standard`` floor, so a deep outage never lands on the fast tier; extraction and the evolution
gate stay on ``standard``. The LLM double receives the real ``LLMRequest`` and answers with a real
``LLMResponse`` whose ``tier`` is the tier asked for and whose ``answered_tier``/``answered_model``
say who answered, the way ``OpenAICompatibleClient`` sets them. Procedures, episodes and clusters
are the real ``Procedure``, ``Episode`` and ``EpisodeCluster``.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from typing import Any
from unittest.mock import MagicMock

import pytest

from probos.cognitive.episode_clustering import EpisodeCluster
from probos.cognitive.procedures import (
    PROCEDURE_REWRITE_MIN_TIER,
    PROCEDURE_REWRITE_TIER,
    Procedure,
    ProcedureStep,
    _optimizer_provenance,
    confirm_evolution_with_llm,
    evolve_derived_procedure,
    evolve_fix_from_fallback,
    evolve_fix_procedure,
    extract_compound_procedure_from_cluster,
    extract_negative_procedure_from_cluster,
    extract_procedure_from_cluster,
    extract_procedure_from_observation,
)
from probos.types import Episode, LLMRequest, LLMResponse

# One reply every procedure-producing call can read (``detail_score`` clears the observation threshold).
_PROCEDURE_JSON = json.dumps({
    "name": "Rotate a credential",
    "description": "Revoke the old key, then issue the new one.",
    "steps": [
        {
            "step_number": 1, "action": "Revoke the old key", "expected_input": "an active key",
            "expected_output": "the old key is refused", "fallback_action": "page the key owner", "invariants": [],
        },
        {
            "step_number": 2, "action": "Issue the new key", "expected_input": "the old key is refused",
            "expected_output": "the new key is accepted", "fallback_action": "", "invariants": [],
        },
    ],
    "preconditions": ["the caller holds the rotate permission"],
    "postconditions": ["only the new key is valid"],
    "change_summary": "Revoke before issuing.",
    "detail_score": 0.9,
})


# ------------------------------------------------------------------ doubles and builders


class _FakeLLM:
    """The procedure functions' LLM seam: records every real request, answers with one fixed response."""

    def __init__(self, response: Any) -> None:
        self.requests: list[LLMRequest] = []
        self._response = response

    async def complete(self, request: LLMRequest) -> Any:
        self.requests.append(request)
        return self._response


def _response(
    content: str,
    *,
    tier: str = "deep",
    answered_tier: str | None = "deep",
    answered_model: str | None = "m",
) -> LLMResponse:
    """A reply as the client builds it: ``tier`` is the tier asked for, whoever answered."""
    return LLMResponse(
        content=content,
        model="id-sent-to-the-provider",
        tier=tier,
        answered_tier=answered_tier,
        answered_model=answered_model,
    )


def _parent() -> Procedure:
    return Procedure(
        id="parent-1",
        name="Rotate a credential",
        description="Rotate one credential.",
        steps=[
            ProcedureStep(step_number=1, action="Revoke the old key"),
            ProcedureStep(step_number=2, action="Issue a new key"),
        ],
        intent_types=["rotate_key"],
    )


def _episode() -> Episode:
    return Episode(id="e1", user_input="Rotate the signing key", outcomes=[{"intent": "rotate_key", "success": True}])


def _cluster(success_rate: float = 1.0) -> EpisodeCluster:
    return EpisodeCluster(
        cluster_id="cluster-1",
        episode_ids=["e1", "e2"],
        episode_count=2,
        centroid=[0.0],
        variance=0.0,
        success_rate=success_rate,
        is_success_dominant=success_rate > 0.8,
        is_failure_dominant=(1.0 - success_rate) > 0.5,
        participating_agents=["security_officer-0a1b2c", "engineering_officer-3d4e5f"],
        intent_types=["rotate_key"],
    )


# The three calls that REWRITE a procedure from a parent (D7): the optimizer.
async def _fix(llm: _FakeLLM) -> Any:
    return await evolve_fix_procedure(_parent(), "success rate fell", {"success_rate": 0.4}, [_episode()], llm)


async def _derived(llm: _FakeLLM) -> Any:
    return await evolve_derived_procedure([_parent()], [_episode()], llm)


async def _fallback(llm: _FakeLLM) -> Any:
    return await evolve_fix_from_fallback(
        _parent(), "quality_gate_rejected", "The LLM's successful answer.", "the gate refused the replay",
        [_episode()], llm,
    )


# The calls that do not: the evolution gate and the extractions from episodes.
async def _gate(llm: _FakeLLM) -> Any:
    return await confirm_evolution_with_llm("Rotate a credential", "degraded", "success rate fell", llm)


async def _extract_from_cluster(llm: _FakeLLM) -> Any:
    return await extract_procedure_from_cluster(_cluster(), [_episode()], llm)


async def _extract_from_observation(llm: _FakeLLM) -> Any:
    return await extract_procedure_from_observation(
        "Chapel explained how to rotate the key.", "security_officer", "Chapel", 0.8, llm,
    )


async def _extract_negative(llm: _FakeLLM) -> Any:
    return await extract_negative_procedure_from_cluster(_cluster(success_rate=0.0), [_episode()], llm)


async def _extract_compound(llm: _FakeLLM) -> Any:
    return await extract_compound_procedure_from_cluster(_cluster(), [_episode()], llm)


_REWRITERS = [
    pytest.param(_fix, id="evolve_fix_procedure"),
    pytest.param(_derived, id="evolve_derived_procedure"),
    pytest.param(_fallback, id="evolve_fix_from_fallback"),
]


# ------------------------------------------------------------------ the tier each call asks for


@pytest.mark.parametrize("rewrite", _REWRITERS)
async def test_rewrite_requests_use_deep_with_a_standard_floor(rewrite: Callable[[_FakeLLM], Awaitable[Any]]) -> None:
    llm = _FakeLLM(_response(_PROCEDURE_JSON))

    result = await rewrite(llm)

    assert result is not None  # the request was built, answered and read: this is not an early failure
    (request,) = llm.requests
    assert (request.tier, request.min_tier, request.exact_tier) == ("deep", "standard", False)
    assert (PROCEDURE_REWRITE_TIER, PROCEDURE_REWRITE_MIN_TIER) == ("deep", "standard")


@pytest.mark.parametrize(
    ("call", "content"),
    [
        pytest.param(_gate, "YES\nthe diagnosis is supported", id="confirm_evolution_with_llm"),
        pytest.param(_extract_from_cluster, _PROCEDURE_JSON, id="extract_procedure_from_cluster"),
        pytest.param(_extract_from_observation, _PROCEDURE_JSON, id="extract_procedure_from_observation"),
        pytest.param(_extract_negative, _PROCEDURE_JSON, id="extract_negative_procedure_from_cluster"),
        pytest.param(_extract_compound, _PROCEDURE_JSON, id="extract_compound_procedure_from_cluster"),
    ],
)
async def test_non_rewriting_calls_stay_standard_without_a_floor(
    call: Callable[[_FakeLLM], Awaitable[Any]], content: str,
) -> None:
    llm = _FakeLLM(_response(content, tier="standard", answered_tier="standard", answered_model="m"))

    result = await call(llm)

    assert result  # answered and read: True from the gate, a Procedure from an extraction
    (request,) = llm.requests
    assert request.tier == "standard"
    assert request.min_tier is None


# ------------------------------------------------------------------ who answered the rewrite


@pytest.mark.parametrize(
    ("answered_tier", "answered_model"),
    [
        pytest.param("deep", "m", id="answered_by_deep"),
        # The floor kept a deep outage off the fast tier; the rewrite is answered by standard and says so.
        pytest.param("standard", "claude-sonnet-4-6", id="answered_by_the_standard_floor"),
    ],
)
@pytest.mark.parametrize("rewrite", _REWRITERS)
async def test_optimizer_provenance_is_recorded_from_the_response(
    rewrite: Callable[[_FakeLLM], Awaitable[Any]], answered_tier: str, answered_model: str,
) -> None:
    response = _response(_PROCEDURE_JSON, tier="deep", answered_tier=answered_tier, answered_model=answered_model)
    assert _optimizer_provenance(response) == (answered_tier, answered_model)  # not response.tier, which says "deep"

    result = await rewrite(_FakeLLM(response))

    assert result is not None
    assert (result.optimizer_tier, result.optimizer_model) == (answered_tier, answered_model)


def _mock_response() -> MagicMock:
    """What the existing procedure tests hand the evolution functions: a bare mock that only has ``content``."""
    response = MagicMock()
    response.content = _PROCEDURE_JSON
    return response


def _answered_by(tier: Any, model: Any) -> Callable[[], LLMResponse]:
    return lambda: _response(_PROCEDURE_JSON, answered_tier=tier, answered_model=model)


@pytest.mark.parametrize(
    ("make_response", "expected"),
    [
        pytest.param(_mock_response, ("", ""), id="bare_magicmock"),
        pytest.param(_answered_by("deep", "m\x00x"), ("deep", ""), id="nul_in_the_model"),
        pytest.param(_answered_by("de\x00ep", "m"), ("", "m"), id="nul_in_the_tier"),
        pytest.param(_answered_by("deep", "m\ud800"), ("deep", ""), id="lone_surrogate_in_the_model"),
        pytest.param(_answered_by("de\ud800ep", "m"), ("", "m"), id="lone_surrogate_in_the_tier"),
        pytest.param(_answered_by("deep", "m" * 300), ("deep", ""), id="model_of_300_characters"),
        pytest.param(_answered_by("d" * 300, "m"), ("", "m"), id="tier_of_300_characters"),
        pytest.param(_answered_by(None, None), ("", ""), id="nothing_reported"),
        pytest.param(_answered_by(7, ["m"]), ("", ""), id="not_text"),
    ],
)
async def test_optimizer_provenance_is_blank_for_mocks_and_unpersistable_text(
    make_response: Callable[[], Any], expected: tuple[str, str],
) -> None:
    assert _optimizer_provenance(make_response()) == expected

    for rewrite in (_fix, _derived, _fallback):  # the rewrite still lands through each entry point, with blank provenance
        result = await rewrite(_FakeLLM(make_response()))

        assert result is not None
        assert (result.optimizer_tier, result.optimizer_model) == expected
