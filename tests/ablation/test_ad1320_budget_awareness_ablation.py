"""AD-1320 paired structural ablation: live budget-awareness notes.

Control (awareness off) and treatment (awareness on, [0.5, 0.8]) run the same
fixed goal -- identical budget, scripted responses and tools -- and differ only
in the optional note. Structural only: no live LLM, no artifacts written.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

import pytest

from probos.cognitive.swe_harness.agentic_loop import AgenticLoop

from tests.test_ad1320_agentic_budget_awareness import (
    BUDGET, MARKER, THRESHOLDS, Client, Resp, Tools, answer, fetch, state,
)

_ID = re.compile(r"[0-9a-f]{32}")


async def _arm(script: list[Resp], *, treated: bool) -> dict[str, Any]:
    awareness = state(BUDGET, THRESHOLDS) if treated else None
    client, tools = Client(script), Tools()
    observed: list[tuple[int, int]] = []
    inner = client.complete

    async def complete(req: Any, **kw: Any) -> Any:
        observed.append(
            (awareness.current_spent, awareness.current_remaining) if awareness and awareness.current_note
            else (0, BUDGET)
        )
        return await inner(req, **kw)

    client.complete = complete  # type: ignore[method-assign]
    extra = {"budget_awareness_state": awareness} if awareness is not None else {}
    loop = AgenticLoop(
        llm_client=client, tool_executor=tools, token_budget=BUDGET,
        max_total_iterations=50, max_iterations=20, **extra,
    )
    result = await loop.run(
        system_prompt="You are Ezri.", user_message="Research.", tools=[],
        context={"agent_id": "counselor-ezri"},
    )
    return {
        "arm": "treatment" if treated else "control",
        "thresholds": list(THRESHOLDS) if treated else None,
        "requests": len(client.requests),
        "tool_calls": list(tools.calls),
        "stopped_reason": result.stopped_reason,
        "iterations": result.iterations,
        "total_tokens": result.total_tokens,
        "token_source": result.token_source,
        "final_digest": hashlib.sha256((result.final_text or "").encode()).hexdigest()[:12],
        "transitions": awareness.transition_count if awareness else 0,
        "used": sorted(awareness.used_thresholds) if awareness else [],
        "markers": [(r.system_prompt or "").count(MARKER) for r in client.requests],
        "observed": observed,
        "prompts": [r.system_prompt for r in client.requests],
        "bodies": [_ID.sub("<id>", f"{r.prompt}|{r.messages}") for r in client.requests],
    }


def _fixed_goal() -> list[Resp]:
    # cumulative spend: 300, 550 (50%), 600, 700, 850 (80%), 860
    return [fetch(300), fetch(250), fetch(50), fetch(100), fetch(150), answer(10, "Findings.")]


def _jump_goal() -> list[Resp]:
    # one response crosses 50% and 80% together
    return [fetch(100), fetch(750), fetch(10), answer(10, "Findings.")]


def _metrics(r: dict[str, Any]) -> str:
    return json.dumps({k: v for k, v in r.items() if k not in {"prompts", "bodies"}}, sort_keys=True)


@pytest.mark.asyncio
async def test_ablation_fixed_goal_single_transition_per_band() -> None:
    control = await _arm(_fixed_goal(), treated=False)
    treated = await _arm(_fixed_goal(), treated=True)
    print("\nAD1320 control  ", _metrics(control))
    print("AD1320 treatment", _metrics(treated))

    assert control["requests"] == 6, "premise: the script ran in full"
    assert control["markers"] == [0] * 6
    assert treated["markers"] == [0, 0, 1, 1, 1, 1]
    assert max(treated["markers"]) == 1
    assert treated["transitions"] == 2 and treated["used"] == [0.5, 0.8]
    assert "nearly spent" not in treated["prompts"][2] and "nearly spent" in treated["prompts"][5]
    assert treated["prompts"][2] == treated["prompts"][3] == treated["prompts"][4]
    assert treated["prompts"][4] != treated["prompts"][5]
    assert treated["observed"][2][0] == 550 and treated["observed"][5][0] == 850
    for key in ("requests", "tool_calls", "stopped_reason", "iterations",
                "total_tokens", "token_source", "final_digest", "bodies"):
        assert treated[key] == control[key], key


@pytest.mark.asyncio
async def test_ablation_jump_crossing_both_bands_shows_only_severe_note() -> None:
    control = await _arm(_jump_goal(), treated=False)
    treated = await _arm(_jump_goal(), treated=True)
    print("\nAD1320 jump control  ", _metrics(control))
    print("AD1320 jump treatment", _metrics(treated))

    assert control["requests"] == 4 and control["markers"] == [0] * 4
    assert treated["markers"] == [0, 0, 1, 1]
    assert treated["transitions"] == 1 and treated["used"] == [0.5, 0.8]
    assert all("nearly spent" in p for p in treated["prompts"][2:])
    for key in ("requests", "tool_calls", "stopped_reason", "total_tokens", "final_digest", "bodies"):
        assert treated[key] == control[key], key
