"""BF-731 (#1188): a Captain conversational turn must reach the reserved
interactive LLM lane.

AD-637f classifies a Captain message as ``Priority.CRITICAL`` so it gets the
reserved interactive slots. That classification was only applied on the
single-pass path (``cognitive_agent._decide_via_llm``). ``AgenticLoop`` had no
priority concept at all -- ``complete(req)`` with no argument -- so enabling
``dm_agentic`` silently moved the Captain's conversation into the background
lane shared with every agent's proactive cognition.

Measured on the reference vessel 2026-08-08: 11s to acquire the first slot
against ~1s for a direct probe of the same proxy, leaving too little of the
20s promotion budget for a second iteration. A three-word presence check
("Are you still there?") became a background task.

The load-bearing tests here assert **at the semaphore**, not at the call
argument. Asserting that ``priority=CRITICAL`` was passed would have passed
happily while the lane stayed wrong -- the argument is the mechanism, the lane
is the behaviour.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

import pytest

from probos.types import Priority


@dataclass
class _FakeRateConfig:
    rpm_fast: int = 60
    rpm_standard: int = 30
    rpm_deep: int = 15
    max_wait_seconds: float = 30.0
    cache_max_entries: int = 10
    per_agent_hourly_token_cap: int = 0
    max_concurrent_calls: int = 6
    interactive_reserved_slots: int = 2


def _make_client(**kw: Any):
    from probos.cognitive.llm_client import OpenAICompatibleClient

    return OpenAICompatibleClient(rate_config=_FakeRateConfig(**kw))


def _instrument_lanes(client: Any) -> dict:
    """Replace ``_complete_inner`` with a probe that records which lane
    semaphore was depleted while the call was in flight.

    With ``max_concurrent_calls=6`` and ``interactive_reserved_slots=2`` the
    interactive semaphore starts at 2 and the background at 4, so exactly one
    of them reads one lower during the call. That is the behaviour under test.
    """
    from probos.cognitive.llm_client import LLMResponse

    seen: dict = {}

    async def _probe(request: Any) -> Any:
        seen["interactive"] = client._interactive_semaphore._value
        seen["background"] = client._background_semaphore._value
        return LLMResponse(content="ok", model="m", tier="standard")

    client._complete_inner = _probe  # type: ignore[method-assign]
    return seen


# ── the lane itself ───────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_critical_priority_takes_the_interactive_lane() -> None:
    from probos.cognitive.llm_client import LLMRequest

    client = _make_client()
    seen = _instrument_lanes(client)
    await client.complete(LLMRequest(prompt="hi"), priority=Priority.CRITICAL)

    assert seen["interactive"] == 1, "the reserved interactive slot was not taken"
    assert seen["background"] == 4, "the background lane must be untouched"


@pytest.mark.asyncio
async def test_default_priority_takes_the_background_lane() -> None:
    from probos.cognitive.llm_client import LLMRequest

    client = _make_client()
    seen = _instrument_lanes(client)
    await client.complete(LLMRequest(prompt="hi"))

    assert seen["background"] == 3
    assert seen["interactive"] == 2, "the reserved slots must stay reserved"


def test_a_direct_message_classifies_as_critical() -> None:
    """The premise BF-731 depends on. If this ever stops being CRITICAL the
    fix below is silently pointless, so pin it rather than assume it."""
    assert Priority.classify(intent="direct_message") is Priority.CRITICAL
    assert Priority.classify(intent="proactive_think", is_captain=True) is (
        Priority.CRITICAL
    )
    assert Priority.classify(intent="proactive_think") is not Priority.CRITICAL


# ── the loop threads it ───────────────────────────────────────────────────
class _StrictLLM:
    """A client whose ``complete`` accepts NO priority kwarg.

    Many existing test doubles are shaped this way. If the loop ever passes
    ``priority=`` unconditionally, this raises TypeError -- which is the
    regression guard for every caller that did not opt in.
    """

    def __init__(self) -> None:
        self.calls = 0

    async def complete(self, request: Any) -> Any:
        from probos.cognitive.llm_client import LLMResponse

        self.calls += 1
        return LLMResponse(content="done", model="m", tier="standard")


class _RecordingLLM:
    def __init__(self) -> None:
        self.priorities: list[Any] = []

    async def complete(self, request: Any, *, priority: Any = None) -> Any:
        from probos.cognitive.llm_client import LLMResponse

        self.priorities.append(priority)
        return LLMResponse(content="done", model="m", tier="standard")


class _NoToolExecutor:
    async def invoke(self, *a: Any, **kw: Any) -> Any:  # pragma: no cover
        raise AssertionError("no tool call expected")

    def definitions(self) -> list:
        return []


def _loop(**kw: Any):
    from probos.cognitive.swe_harness.agentic_loop import AgenticLoop

    return AgenticLoop(llm_client=kw.pop("llm"), tool_executor=_NoToolExecutor(), **kw)


async def _run(loop: Any) -> Any:
    return await loop.run(
        system_prompt="s", user_message="u", tools=[], context={},
    )


@pytest.mark.asyncio
async def test_loop_without_priority_passes_no_kwarg_at_all() -> None:
    """Byte-identity for every existing caller: the kwarg must not merely be
    None, it must not be passed, or doubles like _StrictLLM break."""
    llm = _StrictLLM()
    await _run(_loop(llm=llm))
    assert llm.calls == 1


@pytest.mark.asyncio
async def test_loop_with_priority_forwards_it() -> None:
    llm = _RecordingLLM()
    await _run(_loop(llm=llm, priority=Priority.CRITICAL))
    assert llm.priorities == [Priority.CRITICAL]


# ── the crossing test ─────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_loop_priority_reaches_the_interactive_semaphore() -> None:
    """The whole chain: a real AgenticLoop, a real OpenAICompatibleClient, and
    an assertion on which semaphore was actually depleted.

    This is the one that would have caught BF-731. Every link was individually
    correct before the fix -- classification worked, the lanes worked -- and
    the chain was dead because nothing carried the priority across the seam.
    """
    client = _make_client()
    seen = _instrument_lanes(client)

    await _run(_loop(llm=client, priority=Priority.CRITICAL))

    assert seen["interactive"] == 1, (
        "a Captain-priority loop call did not reach the reserved interactive "
        "lane; the priority was dropped somewhere between the loop and the "
        "semaphore"
    )
    assert seen["background"] == 4


@pytest.mark.asyncio
async def test_loop_without_priority_still_lands_in_background() -> None:
    """The other half: crew/task runs must NOT quietly gain interactive slots."""
    client = _make_client()
    seen = _instrument_lanes(client)

    await _run(_loop(llm=client))

    assert seen["background"] == 3
    assert seen["interactive"] == 2


# ── the executor threads it ───────────────────────────────────────────────
@pytest.mark.asyncio
async def test_executor_forwards_priority_into_the_loop() -> None:
    """`WorkItemAgenticExecutor` is the seam the conversational DM path uses.

    `AgenticLoop` is imported INSIDE ``run``, so the patch must target the
    source module, not the dispatch module that imports it.
    """
    captured = await _capture_loop_kwargs(priority=Priority.CRITICAL)
    assert captured.get("priority") is Priority.CRITICAL


@pytest.mark.asyncio
async def test_executor_without_priority_omits_the_kwarg() -> None:
    captured = await _capture_loop_kwargs()
    assert "priority" not in captured, (
        "the task path must construct the loop exactly as it did before"
    )


async def _capture_loop_kwargs(**extra: Any) -> dict:
    import probos.cognitive.swe_harness.agentic_loop as loop_mod
    from probos.cognitive.agentic_dispatch import WorkItemAgenticExecutor

    captured: dict = {}

    class _CaptureLoop:
        def __init__(self, **kwargs: Any) -> None:
            captured.update(kwargs)

        async def run(self, **kwargs: Any) -> Any:
            return loop_mod.AgenticResult(final_text="ok")

    original = loop_mod.AgenticLoop
    loop_mod.AgenticLoop = _CaptureLoop  # type: ignore[misc]
    try:
        ex = WorkItemAgenticExecutor(llm_client=_RecordingLLM())
        await ex.run(
            agent_id="a",
            instructions="i",
            task_text="t",
            runtime=None,
            **extra,
        )
    finally:
        loop_mod.AgenticLoop = original  # type: ignore[misc]
    return captured
