"""AD-1324 paired ablation: fixed tiers vs agent-chosen tier under a floor, on a scripted client.

Scripted client, identical goals, so the numbers below are STRUCTURAL, not evidence of live
quality: they show what the controller does to request tiers and what that costs under the
registry's prices. Amendment 2: every expected number is a hand-derived LITERAL (the derivation is
beside it), the observed request sequence is compared field by field, and cost counts input AND
output tokens priced at the tier that served each request. A goal is VERIFIED when it stops
``complete`` AND wrote a file. Live-model quality needs a live run and is not claimed.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest

from probos.cognitive.economic_judgment_organ import resolve_tier_pricing
from probos.cognitive.model_registry import ModelDescriptor, ModelRegistry
from probos.cognitive.swe_harness.agentic_loop import AgenticLoop
from tests.test_ad1324_loop_tier_choice import Client, Tools, answer, controller, read, write

DIRECTIVE = '@@next_tier {"tier":"fast","reason":"easy_step"}'
# USD per million tokens (input, output). Hand arithmetic below uses these, not the registry.
_PRICES = {"fast": (1.0, 5.0), "standard": (3.0, 15.0), "deep": (15.0, 75.0)}
# Scripted usage per response kind: a tool step reports 1000 prompt / 100 completion tokens, an answer 1000 / 50.
_USAGE = {"tool": (1000, 100), "answer": (1000, 50)}
_STEP_COST = {  # USD per request = 1000*in/1e6 + completion*out/1e6
    "fast": {"tool": 0.0015, "answer": 0.00125},
    "standard": {"tool": 0.0045, "answer": 0.00375},
    "deep": {"tool": 0.0225, "answer": 0.01875},
}
# Goals: V = read, write_file, answer (verified); U = read, answer (never writes: unverified).
_LITERAL = {
    "fixed_fast": {"V": 0.00425, "U": 0.00275, "total": 0.007},
    "fixed_standard": {"V": 0.01275, "U": 0.00825, "total": 0.021},
    "fixed_deep": {"V": 0.06375, "U": 0.04125, "total": 0.105},
    # V: standard read .0045 + fast write (discarded) .0015 + standard write redo .0045 + standard answer .00375
    # U: standard read .0045 + fast answer (discarded) .00125 + standard answer redo .00375
    "agent_chosen": {"V": 0.01425, "U": 0.0095, "total": 0.02375},
}
_LITERAL["unarmed_baseline"] = dict(_LITERAL["fixed_standard"])
_VERIFIED_RATE = 0.5
# Recorded by running base d811d8a3 source on goal V's unarmed arm: tiers standard x3, tools http_fetch then
# write_file, stopped complete. Usage is the scripted table. (tier, prompt_tokens, completion_tokens, tools).
_BASE_UNARMED_V = [("standard", 1000, 100, ("http_fetch",)), ("standard", 1000, 100, ("write_file",)), ("standard", 1000, 50, ())]
_AGENT_V = [
    ("standard", "tool"), ("fast", "tool"), ("standard", "tool"), ("standard", "answer"),
]
_AGENT_U = [("standard", "tool"), ("fast", "answer"), ("standard", "answer")]


def _registry() -> ModelRegistry:
    registry = ModelRegistry(seed_defaults=False)
    for tier, (cin, cout) in _PRICES.items():
        registry.register(ModelDescriptor(
            name=f"m-{tier}", provider="x", tier=tier,
            cost_per_million_input_tokens=cin, cost_per_million_output_tokens=cout,
        ))
    return registry


class _RecordingClient(Client):
    def __init__(self, responses: list[Any]) -> None:
        super().__init__(responses)
        self.served: list[Any] = []

    async def complete(self, req: Any, **_kw: Any) -> Any:
        response = await super().complete(req)
        self.served.append(response)
        return response


def _kind(response: Any) -> str:
    return "tool" if any(hasattr(b, "tool_call") for b in response.content_blocks) else "answer"


def _goal(name: str, goal: str) -> list[Any]:
    armed = name == "agent_chosen"
    if goal == "V":
        return [read(DIRECTIVE), write(), write(), answer("Done.")] if armed else [read(), write(), answer("Done.")]
    return [read(DIRECTIVE), answer("Looks fine."), answer("Looks fine.")] if armed else [read(), answer("Looks fine.")]


def _scripted(name: str, goal: str, completion: dict[int, int] | None = None) -> list[Any]:
    """The goal's responses with the usage a provider would report, set per position."""
    responses = _goal(name, goal)
    for position, response in enumerate(responses):
        prompt, done = _USAGE[_kind(response)]
        response.prompt_tokens = prompt
        response.completion_tokens = (completion or {}).get(position, done)
    return responses


async def _arm(name: str, goal: str, completion: dict[int, int] | None = None) -> dict[str, Any]:
    tier = {"fixed_fast": "fast", "fixed_deep": "deep"}.get(name, "standard")
    scripted = _scripted(name, goal, completion)
    client, tools = _RecordingClient(list(scripted)), Tools()
    ctl = controller("high", call_site="standard") if name == "agent_chosen" else None
    loop = AgenticLoop(
        llm_client=client, tool_executor=tools, tier=tier, max_iterations=10,
        **({"tier_controller": ctl} if ctl is not None else {}),
    )
    result = await loop.run(system_prompt="s", user_message="u", tools=[], context={"agent_id": "ezri"})
    registry = _registry()
    cost = 0.0
    for req, response in zip(client.requests, client.served, strict=True):
        pin, _w = resolve_tier_pricing(registry, req.tier)
        descriptors = [d for d in registry.by_tier(req.tier) if d.available]
        assert len(descriptors) == 1 and pin == _PRICES[req.tier][0], "premise: one priced descriptor per tier"
        assert response.prompt_tokens > 0 and response.completion_tokens > 0, "premise: the served response reports usage"
        cost += (
            response.prompt_tokens * _PRICES[req.tier][0] / 1e6
            + response.completion_tokens * descriptors[0].cost_per_million_output_tokens / 1e6
        )
    assert len(client.served) == len(scripted) and all(s is c for s, c in zip(scripted, client.served, strict=True)), (
        "premise: the priced responses are the scripted objects the client served"
    )
    return {
        "client": client, "tools": tools, "result": result, "cost": cost,
        "verified": result.stopped_reason == "complete" and "write_file" in tools.calls,
        "sequence": [(r.tier, _kind(s)) for r, s in zip(client.requests, client.served, strict=True)],
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("name", ["fixed_fast", "fixed_standard", "fixed_deep", "agent_chosen", "unarmed_baseline"])
async def test_ablation_arm_costs_match_hand_derived_literals(name: str) -> None:
    v, u = await _arm(name, "V"), await _arm(name, "U")
    expected = _LITERAL[name]
    assert v["cost"] == pytest.approx(expected["V"], abs=1e-9)
    assert u["cost"] == pytest.approx(expected["U"], abs=1e-9)
    assert v["cost"] + u["cost"] == pytest.approx(expected["total"], abs=1e-9)
    assert (v["verified"], u["verified"]) == (True, False), "premise: the goals discriminate"
    verified = int(v["verified"]) + int(u["verified"])
    assert verified / 2 == _VERIFIED_RATE
    assert (v["cost"] + u["cost"]) / verified == pytest.approx(expected["total"], abs=1e-9)
    print("\nAD1324 ablation", json.dumps({name: expected}, sort_keys=True))


@pytest.mark.asyncio
async def test_ablation_cost_follows_served_usage_perturbation() -> None:
    base = await _arm("agent_chosen", "V")
    bumped = await _arm("agent_chosen", "V", completion={1: 200})  # the discarded fast write_file response
    assert [r.tier for r in bumped["client"].requests] == [r.tier for r in base["client"].requests]
    assert bumped["sequence"] == base["sequence"]
    assert bumped["cost"] - base["cost"] == pytest.approx(100 * 5.0 / 1e6, abs=1e-12)
    assert bumped["cost"] == pytest.approx(0.01475, abs=1e-9)


@pytest.mark.asyncio
async def test_ablation_agent_chosen_request_sequence_includes_the_discarded_redo() -> None:
    v, u = await _arm("agent_chosen", "V"), await _arm("agent_chosen", "U")
    assert v["sequence"] == _AGENT_V and u["sequence"] == _AGENT_U
    assert [r.tier_choice_reason for r in v["client"].requests] == ["call_site", "agent_choice", "floor_redo", "floor_raise"]
    for step_tier, kind in v["sequence"] + u["sequence"]:
        assert _STEP_COST[step_tier][kind] > 0
    rank = {"fast": 0, "standard": 1, "deep": 2}
    for req in v["client"].requests + u["client"].requests:
        if req.min_tier is not None:
            assert rank[req.tier] >= rank[req.min_tier], "the floor is never violated"
    assert "@@next_tier" not in v["result"].final_text


@pytest.mark.asyncio
async def test_ablation_unarmed_matches_fixed_standard_and_the_base_recording() -> None:
    unarmed, fixed = await _arm("unarmed_baseline", "V"), await _arm("fixed_standard", "V")
    fields = lambda a: [  # noqa: E731
        (r.tier, r.min_tier, r.tier_choice_reason, r.agent_id, r.work_item_id, r.exact_tier, r.system_prompt)
        for r in a["client"].requests
    ]
    assert fields(unarmed) == fields(fixed)
    observed = [
        (r.tier, s.prompt_tokens, s.completion_tokens, tuple(c.tool_call.name for c in s.content_blocks if hasattr(c, "tool_call")))
        for r, s in zip(unarmed["client"].requests, unarmed["client"].served, strict=True)
    ]
    assert len(unarmed["client"].requests) == 3, "the base recording made exactly three requests"
    assert observed == [tuple(row) for row in _BASE_UNARMED_V]
    assert unarmed["tools"].calls == ["http_fetch", "write_file"]
    assert all(r.min_tier is None and r.tier_choice_reason is None for r in unarmed["client"].requests)


def test_ablation_file_has_no_commented_assertions_or_literal_backtick_n() -> None:
    text = Path(__file__).read_text(encoding="utf-8")
    assert not re.search(r"#\s*assert", text)
    assert "`" + "n" not in text