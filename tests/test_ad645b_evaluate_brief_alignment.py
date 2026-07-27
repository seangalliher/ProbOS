"""AD-645b Phase 4: EVALUATE brief alignment criterion tests."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from probos.cognitive.sub_task import SubTaskResult, SubTaskSpec, SubTaskType
from probos.cognitive.sub_tasks.evaluate import (
    EvaluateHandler,
    _BRIEF_FIELDS_RENDERED,
    _get_composition_brief,
    _render_brief_for_eval,
)


def _make_compose_result(output: str) -> SubTaskResult:
    return SubTaskResult(
        sub_task_type=SubTaskType.COMPOSE,
        name="compose",
        result={"output": output},
        tokens_used=0,
        duration_ms=0,
        success=True,
        tier_used="",
    )


def _make_analyze_result(*, brief: dict | None) -> SubTaskResult:
    payload: dict = {"contribution_assessment": "RESPOND"}
    if brief is not None:
        payload["composition_brief"] = brief
    return SubTaskResult(
        sub_task_type=SubTaskType.ANALYZE,
        name="analyze",
        result=payload,
        tokens_used=0,
        duration_ms=0,
        success=True,
        tier_used="",
    )


_SAMPLE_BRIEF: dict = {
    "situation": "Crew morale dipped after extended yellow alert.",
    "key_evidence": [
        "Backlog of 12 ward-room threads flagged 'urgent'",
        "Sleep-cycle telemetry below baseline for 3 days",
    ],
    "response_should_cover": [
        "Acknowledge the morale dip",
        "Offer one concrete remediation",
    ],
    "tone": "warm and pragmatic",
    "sources_to_draw_on": "ward_room threads, sleep telemetry",
    "analytical_reasoning": "Pattern echoes prior under-resting episodes.",
}


def _make_spec() -> SubTaskSpec:
    return SubTaskSpec(
        sub_task_type=SubTaskType.EVALUATE,
        name="evaluate",
        prompt_template="ward_room_quality",
        tier="standard",
    )


def _make_context() -> dict:
    return {
        "_callsign": "Ezri",
        "_department": "Counseling",
        "_chain_trust_band": "high",
        "_agent_type": "ezri",
        "context": "Ward room thread on crew fatigue.",
    }


def test_get_composition_brief_returns_dict_when_present():
    prior = [_make_analyze_result(brief=_SAMPLE_BRIEF)]
    assert _get_composition_brief(prior) == _SAMPLE_BRIEF


def test_get_composition_brief_returns_none_when_absent():
    prior = [_make_analyze_result(brief=None)]
    assert _get_composition_brief(prior) is None


def test_get_composition_brief_returns_none_when_brief_not_dict():
    bad = SubTaskResult(
        sub_task_type=SubTaskType.ANALYZE,
        name="analyze",
        result={"composition_brief": "not a dict"},
        tokens_used=0,
        duration_ms=0,
        success=True,
        tier_used="",
    )
    assert _get_composition_brief([bad]) is None


def test_render_brief_includes_all_five_assessable_fields():
    rendered = _render_brief_for_eval(_SAMPLE_BRIEF)
    for key in _BRIEF_FIELDS_RENDERED:
        label = key.replace("_", " ").title()
        assert label in rendered, f"missing label {label!r} in {rendered!r}"
    assert "Analytical Reasoning" not in rendered


@pytest.mark.asyncio
async def test_brief_alignment_in_prompt_when_brief_present():
    captured: dict[str, str] = {}

    async def fake_complete(req, **_kwargs):
        captured["system"] = req.system_prompt
        captured["user"] = req.prompt
        return SimpleNamespace(
            content=json.dumps(
                {
                    "pass": True,
                    "score": 0.85,
                    "criteria": {
                        "novelty": {"pass": True, "reason": "ok"},
                        "opening_quality": {"pass": True, "reason": "ok"},
                        "non_redundancy": {"pass": True, "reason": "ok"},
                        "relevance": {"pass": True, "reason": "ok"},
                        "grounding": {"pass": True, "reason": "ok"},
                        "brief_alignment": {
                            "pass": True,
                            "score": 0.9,
                            "reason": "covered all topics, used evidence, matched tone",
                            "dimensions": {
                                "covered_topics": 0.9,
                                "used_evidence": 0.8,
                                "matched_tone": 1.0,
                            },
                        },
                    },
                    "recommendation": "approve",
                }
            ),
            tokens_used=42,
            tier="standard",
        )

    llm = SimpleNamespace(complete=fake_complete)
    handler = EvaluateHandler(llm_client=llm, runtime=None)
    prior = [
        _make_analyze_result(brief=_SAMPLE_BRIEF),
        _make_compose_result(
            "Crew fatigue is showing. Suggest a 24h reduced-ops window."
        ),
    ]
    result = await handler(_make_spec(), _make_context(), prior)

    assert "Brief alignment" in captured["system"]
    assert "brief_alignment" in captured["system"]
    assert "covered_topics" in captured["system"]
    assert "## Composition Brief" in captured["user"]
    assert "warm and pragmatic" in captured["user"]
    assert result.success is True
    ba = result.result["criteria"]["brief_alignment"]
    assert ba["score"] == 0.9
    assert ba["dimensions"] == {
        "covered_topics": 0.9,
        "used_evidence": 0.8,
        "matched_tone": 1.0,
    }
    assert result.result["score"] == 0.85


@pytest.mark.asyncio
async def test_brief_absent_post_fills_neutral_brief_alignment():
    captured: dict[str, str] = {}

    async def fake_complete(req, **_kwargs):
        captured["system"] = req.system_prompt
        captured["user"] = req.prompt
        return SimpleNamespace(
            content=json.dumps(
                {
                    "pass": True,
                    "score": 0.7,
                    "criteria": {
                        "novelty": {"pass": True, "reason": "ok"},
                        "opening_quality": {"pass": True, "reason": "ok"},
                        "non_redundancy": {"pass": True, "reason": "ok"},
                        "relevance": {"pass": True, "reason": "ok"},
                        "grounding": {"pass": True, "reason": "ok"},
                    },
                    "recommendation": "approve",
                }
            ),
            tokens_used=33,
            tier="standard",
        )

    llm = SimpleNamespace(complete=fake_complete)
    handler = EvaluateHandler(llm_client=llm, runtime=None)
    prior = [
        _make_analyze_result(brief=None),
        _make_compose_result("Some response."),
    ]
    result = await handler(_make_spec(), _make_context(), prior)

    assert "Brief alignment" not in captured["system"]
    assert "## Composition Brief" not in captured["user"]
    ba = result.result["criteria"]["brief_alignment"]
    assert ba == {
        "pass": True,
        "score": 0.5,
        "reason": "brief absent",
        "dimensions": {},
    }


@pytest.mark.asyncio
async def test_brief_present_but_llm_omits_criterion_post_fills_with_distinct_reason():
    async def fake_complete(req, **_kwargs):
        return SimpleNamespace(
            content=json.dumps(
                {
                    "pass": True,
                    "score": 0.75,
                    "criteria": {
                        "novelty": {"pass": True, "reason": "ok"},
                        "opening_quality": {"pass": True, "reason": "ok"},
                        "non_redundancy": {"pass": True, "reason": "ok"},
                        "relevance": {"pass": True, "reason": "ok"},
                        "grounding": {"pass": True, "reason": "ok"},
                    },
                    "recommendation": "approve",
                }
            ),
            tokens_used=33,
            tier="standard",
        )

    llm = SimpleNamespace(complete=fake_complete)
    handler = EvaluateHandler(llm_client=llm, runtime=None)
    prior = [
        _make_analyze_result(brief=_SAMPLE_BRIEF),
        _make_compose_result("Some response."),
    ]
    result = await handler(_make_spec(), _make_context(), prior)
    ba = result.result["criteria"]["brief_alignment"]
    assert ba["score"] == 0.5
    assert ba["reason"] == "verdict omitted criterion"
    assert ba["dimensions"] == {}
