"""AD-1322 paired structural ablation: the economic judgment organ.

Control (organ off) and treatment (organ on) run the same scripted goals with
identical tools and responses. The organ only informs, so a scripted client
cannot change course because of the block: the structural claim is that the two
arms are identical except for the appended block. Cost per verified outcome and
the verified-outcome rate are reported from the scripted run and are NOT evidence
of a behavioural improvement; that needs a live model and is not claimed here.

The separate epic-acceptance ablation below proves only that a deterministic
scripted policy can consume the real economic context in both requested
directions. It is not evidence of general or live-model behavioural improvement.
"""

from __future__ import annotations

import json
import asyncio
import re
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any, Literal

import pytest

from probos.cognitive.economic_judgment_organ import EconomicJudgmentOrgan
from probos.cognitive.spine import CognitiveSpine
from probos.cognitive.swe_harness.agentic_loop import AgenticLoop

from tests.test_ad1320_agentic_budget_awareness import Client, Resp, Tools, answer, fetch, write

MARKER = "Economic note"
VERIFY = "write_file"
_ID = re.compile(r"[0-9a-f]{32}")


def _goals() -> dict[str, list[Resp]]:
    return {
        "verified": [fetch(200), fetch(200), write(100), answer(10, "Done.")],
        "unverified": [fetch(300), fetch(300), answer(10, "Done.")],
    }


async def _arm(script: list[Resp], *, treated: bool) -> dict[str, Any]:
    client, tools = Client(script), Tools()
    traces: list[dict[str, Any]] = []
    extra: dict[str, Any] = {}
    if treated:
        organ = EconomicJudgmentOrgan(emit=traces.append, verification_tool_ids=[VERIFY])
        CognitiveSpine(SimpleNamespace(id="agent-1")).attach_organ(organ)
        hook = organ.open_turn_hook()  # amendment 2: one handle per turn
        hook.open_run(
            turn_key="t", value_band="minor", stakes="high", tier="standard", budget=1000,
        )
        extra["inner_loop_hook"] = hook
    loop = AgenticLoop(llm_client=client, tool_executor=tools, max_iterations=20, **extra)
    result = await loop.run(
        system_prompt="You are Ezri.", user_message="Go.", tools=[],
        context={"agent_id": "counselor-ezri"},
    )
    verified = result.stopped_reason == "complete" and VERIFY in tools.calls
    return {
        "arm": "treatment" if treated else "control",
        "requests": len(client.requests),
        "tool_calls": list(tools.calls),
        "stopped_reason": result.stopped_reason,
        "iterations": result.iterations,
        "total_tokens": result.total_tokens,
        "verified": verified,
        "markers": [(r.system_prompt or "").count(MARKER) for r in client.requests],
        "bodies": [_ID.sub("<id>", f"{r.prompt}|{r.messages}") for r in client.requests],
        "stripped": [
            (r.system_prompt or "").split("\n\n" + MARKER)[0] for r in client.requests
        ],
        "signals": sorted({s for t in traces for s in t["signals"]}),
    }


@pytest.mark.asyncio
async def test_ablation_cost_per_verified_outcome_and_verified_rate_off_vs_on() -> None:
    report: dict[str, dict[str, Any]] = {"control": {}, "treatment": {}}
    outcomes: dict[str, list[dict[str, Any]]] = {"control": [], "treatment": []}
    for name, script in _goals().items():
        control = await _arm(_goals()[name], treated=False)
        treated = await _arm(_goals()[name], treated=True)
        outcomes["control"].append(control)
        outcomes["treatment"].append(treated)

        assert control["requests"] >= 3, "premise: the script ran in full"
        assert control["markers"] == [0] * control["requests"]
        assert treated["markers"] == [1] * treated["requests"]
        for key in ("requests", "tool_calls", "stopped_reason", "iterations",
                    "total_tokens", "verified", "bodies"):
            assert treated[key] == control[key], (name, key)
        assert treated["stripped"] == [
            s for s in control["stripped"]
        ], "only the appended block may differ in the system prompt"

    for arm, runs in outcomes.items():
        verified = [r for r in runs if r["verified"]]
        total = sum(r["total_tokens"] for r in runs)
        report[arm] = {
            "verified_outcomes": len(verified),
            "verified_rate": len(verified) / len(runs),
            "tokens_per_verified_outcome": (total / len(verified)) if verified else None,
        }
    print("\nAD1322 ablation", json.dumps(report, sort_keys=True))

    assert report["control"] == report["treatment"], (
        "the organ informs only, so a scripted client cannot change course; "
        "any difference here would mean the organ altered the run"
    )
    assert report["control"]["verified_outcomes"] == 1
    assert outcomes["treatment"][1]["signals"], "premise: the unverified goal raised a signal"


@pytest.mark.asyncio
async def test_ablation_concurrent_turns_on_one_organ_match_solo_runs() -> None:
    solo = [await _arm(_goals()[n], treated=True) for n in ("verified", "unverified")]
    organ = EconomicJudgmentOrgan(verification_tool_ids=[VERIFY])
    CognitiveSpine(SimpleNamespace(id="agent-1")).attach_organ(organ)

    async def run(script: list[Resp], key: str) -> list[str]:
        client = Client(script)
        hook = organ.open_turn_hook()
        hook.open_run(turn_key=key, value_band="minor", stakes="high", tier="standard", budget=1000)
        loop = AgenticLoop(llm_client=client, tool_executor=Tools(), max_iterations=20,
                           inner_loop_hook=hook)
        await loop.run(system_prompt="You are Ezri.", user_message="Go.", tools=[],
                       context={"agent_id": "counselor-ezri"})
        return [r.system_prompt or "" for r in client.requests]

    a, b = await asyncio.gather(run(_goals()["verified"], "A"), run(_goals()["unverified"], "B"))
    assert [p.count(MARKER) for p in a] == solo[0]["markers"] and len(a) >= 3
    assert [p.count(MARKER) for p in b] == solo[1]["markers"]
    assert len(organ.turn_summaries) == 2


@dataclass(frozen=True)
class _AcceptanceGoal:
    name: Literal["low_value", "high_stakes"]
    value_band: str
    stakes: str
    budget: int
    trust_headroom: float
    baseline_response_plan: tuple[tuple[str, int], ...]


_ACCEPTANCE_GOALS = (
    _AcceptanceGoal(
        name="low_value",
        value_band="minor",
        stakes="low",
        budget=1000,
        trust_headroom=1.0,
        baseline_response_plan=(
            ("write_file", 100),
            ("http_fetch", 400),
            ("http_fetch", 200),
            ("answer", 10),
        ),
    ),
    _AcceptanceGoal(
        name="high_stakes",
        value_band="significant",
        stakes="high",
        budget=1000,
        trust_headroom=1.0,
        baseline_response_plan=(("http_fetch", 100), ("answer", 10)),
    ),
)
_SPEND_GUIDANCE = ("Spend is high", "Spend high")
_VERIFY_GUIDANCE = ("verify the result before you finish", "verify before finishing")


def _planned_response(kind: str, tokens: int) -> Resp:
    if kind == "write_file":
        return write(tokens)
    if kind == "http_fetch":
        return fetch(tokens)
    assert kind == "answer", f"unknown acceptance response kind: {kind}"
    return answer(tokens, "Done.")


class _PolicySensitiveClient:
    """Deterministic client that can consume only rendered economic guidance."""

    def __init__(self, goal: _AcceptanceGoal, *, consume_context: bool) -> None:
        self._goal = goal
        self._consume_context = consume_context
        self._common = [
            _planned_response(kind, tokens)
            for kind, tokens in (
                goal.baseline_response_plan[:2]
                if goal.name == "low_value"
                else goal.baseline_response_plan[:1]
            )
        ]
        self._ordinary = [
            _planned_response(kind, tokens)
            for kind, tokens in (
                goal.baseline_response_plan[2:]
                if goal.name == "low_value"
                else goal.baseline_response_plan[1:]
            )
        ]
        self._contextual = (
            [answer(10, "Done.")]
            if goal.name == "low_value"
            else [write(100), answer(10, "Done.")]
        )
        self._selected: list[Resp] | None = None
        self.requests: list[Any] = []
        self.context_consumptions = 0
        self.served_responses = 0

    async def complete(self, req: Any, **_kwargs: Any) -> Resp:
        self.requests.append(req)
        if self._common:
            response = self._common.pop(0)
        else:
            if self._selected is None:
                prompt = req.system_prompt or ""
                guidance = (
                    _SPEND_GUIDANCE
                    if self._goal.name == "low_value"
                    else _VERIFY_GUIDANCE
                )
                consumed = self._consume_context and any(
                    phrase in prompt for phrase in guidance
                )
                self._selected = self._contextual if consumed else self._ordinary
                self.context_consumptions += int(consumed)
            assert self._selected, (
                f"{self._goal.name} requested an implicit fallback response"
            )
            response = self._selected.pop(0)
        self.served_responses += 1
        return response

    def assert_exhausted(self) -> None:
        assert not self._common
        assert self._selected is not None and not self._selected
        expected = (
            3
            if self._goal.name == "low_value" and self.context_consumptions
            else 4
            if self._goal.name == "low_value"
            else 3
            if self.context_consumptions
            else 2
        )
        assert self.served_responses == expected


async def _acceptance_goal(
    goal: _AcceptanceGoal,
    *,
    treated: bool,
    consume_context: bool,
) -> dict[str, Any]:
    client = _PolicySensitiveClient(goal, consume_context=consume_context)
    tools = Tools()
    traces: list[dict[str, Any]] = []
    extra: dict[str, Any] = {}
    if treated:
        organ = EconomicJudgmentOrgan(
            emit=traces.append,
            verification_tool_ids=[VERIFY],
        )
        spine = CognitiveSpine(SimpleNamespace(id=f"agent-{goal.name}"))
        spine.attach_organ(organ)
        hook = organ.open_turn_hook(trust_headroom=goal.trust_headroom)
        hook.open_run(
            turn_key=goal.name,
            value_band=goal.value_band,
            stakes=goal.stakes,
            tier="standard",
            budget=goal.budget,
        )
        extra["inner_loop_hook"] = hook
    loop = AgenticLoop(
        llm_client=client,
        tool_executor=tools,
        max_iterations=20,
        **extra,
    )
    result = await loop.run(
        system_prompt="You are Ezri.",
        user_message=f"Complete {goal.name}.",
        tools=[],
        context={"agent_id": "counselor-ezri"},
    )
    client.assert_exhausted()
    assert result.stopped_reason == "complete"
    return {
        "goal": goal,
        "spend_tokens": result.total_tokens,
        "verified": VERIFY in tools.calls,
        "tool_calls": list(tools.calls),
        "model_call_count": len(client.requests),
        "markers": sum(
            (request.system_prompt or "").count(MARKER)
            for request in client.requests
        ),
        "marker_counts": [
            (request.system_prompt or "").count(MARKER)
            for request in client.requests
        ],
        "context_consumptions": client.context_consumptions,
        "traces": traces,
    }


async def _acceptance_arm(
    arm: Literal["control", "treatment", "non_consuming_treatment"],
) -> dict[str, Any]:
    treated = arm != "control"
    consume_context = arm == "treatment"
    runs = [
        await _acceptance_goal(
            goal,
            treated=treated,
            consume_context=consume_context,
        )
        for goal in _ACCEPTANCE_GOALS
    ]
    verified = sum(int(run["verified"]) for run in runs)
    total_cost = sum(run["spend_tokens"] for run in runs)
    report = {
        "goal_count": len(runs),
        "goal_names": [run["goal"].name for run in runs],
        "verified_outcomes": verified,
        "verified_rate": verified / len(runs),
        "total_cost_tokens": total_cost,
        "cost_per_verified_outcome": total_cost / verified if verified else None,
        "low_value_spend_tokens": runs[0]["spend_tokens"],
        "high_stakes_spend_tokens": runs[1]["spend_tokens"],
        "high_stakes_verified_outcomes": int(runs[1]["verified"]),
        "model_call_count": sum(run["model_call_count"] for run in runs),
        "economic_context_markers": sum(run["markers"] for run in runs),
        "economic_context_consumptions": sum(
            run["context_consumptions"] for run in runs
        ),
    }
    return {"report": report, "runs": runs}


def _acceptance_deltas(
    control_arm: dict[str, Any],
    treatment_arm: dict[str, Any],
) -> dict[str, int]:
    control = control_arm["report"]
    treatment = treatment_arm["report"]
    control_runs = control_arm["runs"]
    treatment_runs = treatment_arm["runs"]
    return {
        "low_value_spend_avoided_tokens": (
            control["low_value_spend_tokens"]
            - treatment["low_value_spend_tokens"]
        ),
        "low_value_model_calls_avoided": (
            control_runs[0]["model_call_count"]
            - treatment_runs[0]["model_call_count"]
        ),
        "high_stakes_verifications_added": (
            treatment["high_stakes_verified_outcomes"]
            - control["high_stakes_verified_outcomes"]
        ),
        "high_stakes_model_calls_added": (
            treatment_runs[1]["model_call_count"]
            - control_runs[1]["model_call_count"]
        ),
    }


def _assert_acceptance(
    control: dict[str, Any],
    treatment: dict[str, Any],
) -> None:
    assert treatment["low_value_spend_tokens"] < control["low_value_spend_tokens"]
    assert (
        treatment["high_stakes_verified_outcomes"]
        > control["high_stakes_verified_outcomes"]
    )
    assert treatment["verified_rate"] >= control["verified_rate"]
    assert (
        treatment["cost_per_verified_outcome"]
        <= control["cost_per_verified_outcome"]
    )


@pytest.mark.asyncio
async def test_epic_acceptance_policy_sensitive_economic_context_ablation() -> None:
    arms = {
        name: await _acceptance_arm(name)
        for name in ("control", "treatment", "non_consuming_treatment")
    }
    reports = {name: arm["report"] for name, arm in arms.items()}
    control = reports["control"]
    treatment = reports["treatment"]
    non_consuming = reports["non_consuming_treatment"]
    deltas = _acceptance_deltas(arms["control"], arms["treatment"])

    expected_population = [
        (
            goal.name,
            goal.value_band,
            goal.stakes,
            goal.budget,
            goal.trust_headroom,
            goal.baseline_response_plan,
        )
        for goal in _ACCEPTANCE_GOALS
    ]
    for arm in arms.values():
        assert [
            (
                run["goal"].name,
                run["goal"].value_band,
                run["goal"].stakes,
                run["goal"].budget,
                run["goal"].trust_headroom,
                run["goal"].baseline_response_plan,
            )
            for run in arm["runs"]
        ] == expected_population
        assert arm["report"]["goal_names"] == ["low_value", "high_stakes"]

    assert control["economic_context_markers"] == 0
    for name in ("treatment", "non_consuming_treatment"):
        assert all(
            count == 1
            for run in arms[name]["runs"]
            for count in run["marker_counts"]
        )
    assert treatment["economic_context_consumptions"] == 2
    assert [
        run["context_consumptions"] for run in arms["treatment"]["runs"]
    ] == [1, 1]
    assert non_consuming["economic_context_consumptions"] == 0

    before_call_inputs = {
        run["goal"].name: [
            trace["inputs"]
            for trace in run["traces"]
            if trace["inputs"]["phase"] == "before_model_call"
        ]
        for run in arms["treatment"]["runs"]
    }
    for goal in _ACCEPTANCE_GOALS:
        assert before_call_inputs[goal.name]
        assert all(
            {
                "spend_tokens",
                "value_band",
                "stakes",
                "trust_headroom",
                "total_budget",
            }
            <= inputs.keys()
            for inputs in before_call_inputs[goal.name]
        )
        assert all(
            inputs["value_band"] == goal.value_band
            and inputs["stakes"] == goal.stakes
            and inputs["trust_headroom"] == goal.trust_headroom
            and inputs["total_budget"] == goal.budget
            for inputs in before_call_inputs[goal.name]
        )

    low_overspend = [
        trace
        for trace in arms["treatment"]["runs"][0]["traces"]
        if "high_spend_low_value" in trace["reasons"]
    ]
    assert low_overspend
    assert all(trace["inputs"]["spend_tokens"] >= 500 for trace in low_overspend)
    assert any(
        trace["inputs"]["phase"] == "before_model_call"
        and trace["inputs"]["spend_tokens"] == 500
        for trace in low_overspend
    )
    high_verify = [
        trace
        for trace in arms["treatment"]["runs"][1]["traces"]
        if "underspend" in trace["signals"]
    ]
    assert high_verify
    assert all(
        trace["inputs"]["verification_available"] is True
        and trace["inputs"]["verification_recorded"] is False
        for trace in high_verify
    )

    metric_keys = {
        "goal_count",
        "goal_names",
        "verified_outcomes",
        "verified_rate",
        "total_cost_tokens",
        "cost_per_verified_outcome",
        "low_value_spend_tokens",
        "high_stakes_spend_tokens",
        "high_stakes_verified_outcomes",
        "model_call_count",
    }
    assert {
        key: non_consuming[key] for key in metric_keys
    } == {
        key: control[key] for key in metric_keys
    }

    assert control == {
        "goal_count": 2,
        "goal_names": ["low_value", "high_stakes"],
        "verified_outcomes": 1,
        "verified_rate": 0.5,
        "total_cost_tokens": 820,
        "cost_per_verified_outcome": 820.0,
        "low_value_spend_tokens": 710,
        "high_stakes_spend_tokens": 110,
        "high_stakes_verified_outcomes": 0,
        "model_call_count": 6,
        "economic_context_markers": 0,
        "economic_context_consumptions": 0,
    }
    assert treatment == {
        "goal_count": 2,
        "goal_names": ["low_value", "high_stakes"],
        "verified_outcomes": 2,
        "verified_rate": 1.0,
        "total_cost_tokens": 720,
        "cost_per_verified_outcome": 360.0,
        "low_value_spend_tokens": 510,
        "high_stakes_spend_tokens": 210,
        "high_stakes_verified_outcomes": 1,
        "model_call_count": 6,
        "economic_context_markers": 6,
        "economic_context_consumptions": 2,
    }
    assert deltas == {
        "low_value_spend_avoided_tokens": 200,
        "low_value_model_calls_avoided": 1,
        "high_stakes_verifications_added": 1,
        "high_stakes_model_calls_added": 1,
    }
    _assert_acceptance(control, treatment)
    with pytest.raises(AssertionError):
        _assert_acceptance(control, non_consuming)

    print(
        "\nAD1322 epic acceptance ablation",
        json.dumps({"arms": reports, "directional": deltas}, sort_keys=True),
    )
