"""AD-1322 paired structural ablation: the economic judgment organ.

Control (organ off) and treatment (organ on) run the same scripted goals with
identical tools and responses. The organ only informs, so a scripted client
cannot change course because of the block: the structural claim is that the two
arms are identical except for the appended block. Cost per verified outcome and
the verified-outcome rate are reported from the scripted run and are NOT evidence
of a behavioural improvement; that needs a live model and is not claimed here.
"""

from __future__ import annotations

import json
import asyncio
import re
from types import SimpleNamespace
from typing import Any

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
