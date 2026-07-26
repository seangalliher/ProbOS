"""AD-547: Tests for SessionCompactor + estimate_tokens."""

from __future__ import annotations

import pytest

from probos.cognitive.swe_harness.session_compactor import (
    SessionCompactor,
    estimate_messages_tokens,
    estimate_tokens,
)
from probos.types import LLMResponse


class _StubFastLLM:
    def __init__(self, *, summary: str = "summary text", raises: bool = False) -> None:
        self.summary = summary
        self.raises = raises
        self.calls = 0

    async def complete(self, request, **kwargs):
        self.calls += 1
        if self.raises:
            raise RuntimeError("LLM down")
        return LLMResponse(content=self.summary, tokens_used=4)


def test_estimate_tokens_empty_returns_one() -> None:
    assert estimate_tokens("") == 1


def test_estimate_tokens_char_quartering() -> None:
    text = "hello world"  # 11 chars
    assert estimate_tokens(text) == max(1, len(text) // 4)


@pytest.mark.asyncio
async def test_compact_short_circuits_when_too_few_messages() -> None:
    sc = SessionCompactor()
    msgs = [
        {"role": "system", "content": "s"},
        {"role": "user", "content": "u"},
    ]
    out = await sc.compact(msgs, preserve_count=5, fast_llm=_StubFastLLM())
    assert out is msgs


@pytest.mark.asyncio
async def test_compact_calls_fast_tier_llm() -> None:
    sc = SessionCompactor()
    llm = _StubFastLLM()
    msgs = [
        {"role": "system", "content": "s"},
        {"role": "user", "content": "task"},
        {"role": "assistant", "content": "step1"},
        {"role": "user", "content": "result1"},
        {"role": "assistant", "content": "step2"},
        {"role": "user", "content": "result2"},
        {"role": "assistant", "content": "step3"},
        {"role": "user", "content": "result3"},
        {"role": "assistant", "content": "step4"},
    ]
    out = await sc.compact(msgs, preserve_count=2, fast_llm=llm)
    assert llm.calls == 1
    # Output should be shorter than input
    assert len(out) < len(msgs)


@pytest.mark.asyncio
async def test_compact_returns_system_summary_and_tail() -> None:
    sc = SessionCompactor()
    llm = _StubFastLLM(summary="condensed")
    msgs = [
        {"role": "system", "content": "s"},
        {"role": "user", "content": "task"},
        {"role": "assistant", "content": "a1"},
        {"role": "user", "content": "r1"},
        {"role": "assistant", "content": "a2"},
        {"role": "user", "content": "r2"},
        {"role": "assistant", "content": "a3"},
    ]
    out = await sc.compact(msgs, preserve_count=2, fast_llm=llm)
    # First entry is original system message
    assert out[0]["role"] == "system"
    # Last 2 entries are preserved tail
    assert out[-1]["content"] == "a3"
    assert out[-2]["content"] == "r2"
    # Middle has the summary
    contents = [m["content"] for m in out]
    assert any("condensed" in c for c in contents)


@pytest.mark.asyncio
async def test_compact_re_compacts_when_over_budget() -> None:
    """When first pass exceeds budget, drops to system + summary + last 2."""
    sc = SessionCompactor()
    # Long summary so first pass still exceeds tiny budget
    llm = _StubFastLLM(summary="a very long summary " * 50)
    msgs = [{"role": "system", "content": "s"}]
    msgs.append({"role": "user", "content": "task"})
    for i in range(10):
        msgs.append({"role": "assistant", "content": f"a{i}"})
        msgs.append({"role": "user", "content": f"r{i}"})
    out = await sc.compact(msgs, preserve_count=3, budget_tokens=10, fast_llm=llm)
    # Re-compaction trims to system + summary + 2 tail = 4
    assert len(out) <= 5


@pytest.mark.asyncio
async def test_compact_falls_back_to_original_on_llm_failure() -> None:
    sc = SessionCompactor()
    llm = _StubFastLLM(raises=True)
    msgs = [
        {"role": "system", "content": "s"},
        {"role": "user", "content": "u"},
        {"role": "assistant", "content": "a1"},
        {"role": "user", "content": "r1"},
        {"role": "assistant", "content": "a2"},
        {"role": "user", "content": "r2"},
        {"role": "assistant", "content": "a3"},
    ]
    out = await sc.compact(msgs, preserve_count=2, fast_llm=llm)
    assert out is msgs


@pytest.mark.asyncio
async def test_compact_preserves_original_user_task() -> None:
    sc = SessionCompactor()
    llm = _StubFastLLM(summary="sum")
    original_task = "ORIGINAL_TASK_MARKER"
    msgs = [
        {"role": "system", "content": "s"},
        {"role": "user", "content": original_task},
        {"role": "assistant", "content": "a1"},
        {"role": "user", "content": "r1"},
        {"role": "assistant", "content": "a2"},
        {"role": "user", "content": "r2"},
        {"role": "assistant", "content": "a3"},
    ]
    out = await sc.compact(msgs, preserve_count=2, fast_llm=llm)
    contents = [m.get("content", "") for m in out]
    assert any(original_task in c for c in contents)


# ---------------------------------------------------------------------------
# AD-1142 / DD-6 — Defect A regressions.
#
# The re-compaction splice used to keep ``[compacted[0]]``. With both a system
# message and an original-user message in the head that is the SYSTEM message,
# so the second pass silently discarded the task the agent was given. Neither
# existing test reached the branch: ``test_compact_preserves_original_user_task``
# passes no ``budget_tokens`` (first pass only) and
# ``test_compact_re_compacts_when_over_budget`` asserts only ``len(out) <= 5``.
# Every test below forces the second pass with a low ``budget_tokens`` and a
# summary long enough that the first pass cannot fit it.
# ---------------------------------------------------------------------------

def _over_budget_history() -> list[dict]:
    msgs = [
        {"role": "system", "content": "SYSTEM_PROMPT_MARKER"},
        {"role": "user", "content": "ORIGINAL_TASK_MARKER"},
    ]
    for i in range(10):
        msgs.append({"role": "assistant", "content": f"a{i}"})
        msgs.append({"role": "user", "content": f"r{i}"})
    return msgs


@pytest.mark.asyncio
async def test_re_compaction_preserves_the_original_user_task_by_identity() -> None:
    """THE DEFECT A REGRESSION. Before AD-1142 this returned
    ``[system, summary, *tail]`` and the original task was gone."""
    sc = SessionCompactor()
    llm = _StubFastLLM(summary="a very long summary " * 50)
    msgs = _over_budget_history()

    out = await sc.compact(msgs, preserve_count=3, budget_tokens=10, fast_llm=llm)

    assert any(m is msgs[1] for m in out), "the original user task was dropped"
    assert any("ORIGINAL_TASK_MARKER" in m.get("content", "") for m in out)


@pytest.mark.asyncio
async def test_re_compaction_preserves_the_system_prompt_by_identity() -> None:
    sc = SessionCompactor()
    llm = _StubFastLLM(summary="a very long summary " * 50)
    msgs = _over_budget_history()

    out = await sc.compact(msgs, preserve_count=3, budget_tokens=10, fast_llm=llm)

    assert out[0] is msgs[0]


@pytest.mark.asyncio
async def test_re_compaction_order_is_system_then_task_then_summary_then_tail() -> None:
    sc = SessionCompactor()
    llm = _StubFastLLM(summary="a very long summary " * 50)
    msgs = _over_budget_history()

    out = await sc.compact(msgs, preserve_count=3, budget_tokens=10, fast_llm=llm)

    assert out[0] is msgs[0]
    assert out[1] is msgs[1]
    assert out[2]["role"] == "user"
    assert out[2]["content"].startswith("[CONTEXT SUMMARY")
    # The rest is the group-aligned trailing slice, in original order.
    assert out[3:] == msgs[len(msgs) - len(out[3:]):]


@pytest.mark.asyncio
async def test_re_compaction_emits_exactly_one_summary() -> None:
    sc = SessionCompactor()
    llm = _StubFastLLM(summary="a very long summary " * 50)
    msgs = _over_budget_history()

    out = await sc.compact(msgs, preserve_count=3, budget_tokens=10, fast_llm=llm)

    summaries = [
        m for m in out if str(m.get("content", "")).startswith("[CONTEXT SUMMARY")
    ]
    assert len(summaries) == 1


@pytest.mark.asyncio
async def test_re_compaction_never_repeats_a_message_object() -> None:
    """The head is de-duplicated by identity.

    ``system_msg is original_user`` cannot be produced through ``compact()`` —
    the first requires ``role == "system"`` at index 0 and the second requires
    ``role == "user"`` later, and one dict cannot report both — so the guard is
    defensive. What IS observable, and what the guard protects, is that no
    message object appears twice in the returned list.
    """
    sc = SessionCompactor()
    llm = _StubFastLLM(summary="a very long summary " * 50)
    msgs = _over_budget_history()

    out = await sc.compact(msgs, preserve_count=3, budget_tokens=10, fast_llm=llm)

    assert len({id(m) for m in out}) == len(out)


@pytest.mark.asyncio
async def test_re_compaction_without_a_system_message_keeps_the_task() -> None:
    """``head`` is ``[original_user]`` alone — the branch where ``compacted[0]``
    already WAS the original user task and the old splice happened to work."""
    sc = SessionCompactor()
    llm = _StubFastLLM(summary="a very long summary " * 50)
    msgs: list[dict] = [{"role": "assistant", "content": "preamble"}]
    msgs.append({"role": "user", "content": "ORIGINAL_TASK_MARKER"})
    for i in range(10):
        msgs.append({"role": "assistant", "content": f"a{i}"})
        msgs.append({"role": "user", "content": f"r{i}"})

    out = await sc.compact(msgs, preserve_count=3, budget_tokens=10, fast_llm=llm)

    assert out[0] is msgs[1]
    assert out[1]["content"].startswith("[CONTEXT SUMMARY")
    assert len({id(m) for m in out}) == len(out)


@pytest.mark.asyncio
async def test_re_compaction_with_no_head_does_not_duplicate_the_summary() -> None:
    """Neither a system message nor a user turn exists, so ``head`` is empty and
    ``compacted[0]`` IS the summary."""
    sc = SessionCompactor()
    llm = _StubFastLLM(summary="a very long summary " * 50)
    msgs = [
        {"role": "assistant", "content": f"a{i}"} for i in range(14)
    ]

    out = await sc.compact(msgs, preserve_count=3, budget_tokens=10, fast_llm=llm)

    summaries = [
        m for m in out if str(m.get("content", "")).startswith("[CONTEXT SUMMARY")
    ]
    assert len(summaries) == 1
    assert out[0]["content"].startswith("[CONTEXT SUMMARY")
    assert len({id(m) for m in out}) == len(out)
