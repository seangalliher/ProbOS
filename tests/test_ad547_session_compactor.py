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
