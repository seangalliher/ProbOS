"""AD-1324 amendment 2 (finding 6): floor re-issues count against the iteration ceiling."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from probos.cognitive.swe_harness.agentic_loop import AgenticLoop
from tests.test_ad1324_loop_tier_choice import DIRECTIVE, Client, Tools, answer, controller, read


def answer_big() -> Any:
    resp = answer("quick guess")
    resp.tokens_used = 60
    return resp


async def run(responses: list[Any], ctl: Any = None, **kw: Any) -> tuple[Any, Client, Tools]:
    client, tools = Client(responses), Tools()
    extra = {"tier_controller": ctl} if ctl is not None else {}
    loop = AgenticLoop(llm_client=client, tool_executor=tools, tier="fast", **extra, **kw)
    result = await asyncio.wait_for(  # an unbounded redo fails here instead of hanging
        loop.run(system_prompt="s", user_message="u", tools=[], context={"agent_id": "ezri"}), 10,
    )
    return result, client, tools


@pytest.mark.asyncio
async def test_redo_at_the_ceiling_is_not_sent() -> None:
    result, client, _t = await run(
        [read(DIRECTIVE), answer("quick guess"), answer("careful answer")], controller("high"),
        max_iterations=2, max_total_iterations=2, token_budget=10000,
    )
    assert [r.tier for r in client.requests] == ["standard", "fast"], "exactly the ceiling's two requests"
    assert result.stopped_reason == "max_iterations"
    assert "careful answer" not in result.final_text
    assert result.iterations == 2


@pytest.mark.asyncio
async def test_redo_with_headroom_is_sent_and_counted() -> None:
    result, client, _t = await run(
        [read(DIRECTIVE), answer("quick guess"), answer("careful answer")], controller("high"),
        max_iterations=3, max_total_iterations=3, token_budget=10000,
    )
    assert [r.tier for r in client.requests] == ["standard", "fast", "standard"]
    assert result.final_text == "careful answer"
    assert result.iterations == 3


@pytest.mark.asyncio
async def test_redo_blocked_by_token_budget_is_not_sent() -> None:
    result, client, _t = await run(
        [read(DIRECTIVE, tokens=60), answer_big(), answer("x")], controller("high"),
        max_iterations=5, token_budget=100,
    )
    assert len(client.requests) == 2 and result.stopped_reason == "token_budget"


@pytest.mark.asyncio
async def test_unarmed_loop_with_total_ceiling_is_unchanged() -> None:
    result, client, _t = await run(
        [read(), read(), answer()], max_iterations=3, max_total_iterations=3, token_budget=10000,
    )
    assert len(client.requests) == 3 and result.stopped_reason == "complete"