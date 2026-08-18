"""BF-629: conversational web_search/read_page synthesis pass.

A requires_reflect inline mesh read (web_search / read_page) should be REASONED
over by the originating agent in its own voice (search -> reason -> answer), like
an agentic tool-use loop, instead of pasting raw links/page dumps verbatim — the
gap behind "Ezri gave me links; I had to prompt her again to summarise."

BF-287: a real DmReplyPipeline + real DmSanityGate + real config-shaped runtime;
fake intent-bus + LLM client only at the edges (the bus/LLM are the I/O boundary).
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from probos.cognitive.dm import DmReplyContext, DmReplyPipeline
from probos.cognitive.dm_sanity_gate import DmSanityGate
from probos.cognitive.dm.reply_value import DmReply  # AD-1248


# ---------------------------------------------------------------------------
# harness (BF-287 — real pipeline/gate; fakes only at the I/O edges)
# ---------------------------------------------------------------------------


class _PoolRegistry:
    """registry.get_by_pool(pool) -> [agent] so _resolve_mesh_read_agent finds one."""

    def get_by_pool(self, pool: str):
        return [SimpleNamespace(id=f"{pool}-agent-1")]


class _ResultBus:
    """intent_bus.send(intent) -> a successful IntentResult-shaped object."""

    def __init__(self, result_text: str) -> None:
        self._text = result_text
        self.sent: list = []

    async def send(self, intent):
        self.sent.append(intent)
        return SimpleNamespace(success=True, result=self._text, error=None)


class _CapturingLLM:
    """llm_client.complete(req) -> a response; records the requests it saw."""

    def __init__(self, content: str = "SYNTHESISED ANSWER in Ezri's voice.", raises: bool = False) -> None:
        self._content = content
        self._raises = raises
        self.calls: list = []

    async def complete(self, req, **_kwargs):
        self.calls.append(req)
        if self._raises:
            raise RuntimeError("proxy down")
        return SimpleNamespace(content=self._content)


def _runtime(*, result_text: str, llm, enabled: bool = True) -> SimpleNamespace:
    return SimpleNamespace(
        intent_bus=_ResultBus(result_text),
        registry=_PoolRegistry(),
        llm_client=llm,
        intent_grant_store=None,  # AD-1007 capability gate honest-degrades off
        config=SimpleNamespace(
            dm_mesh_synthesis=SimpleNamespace(enabled=enabled, tier="standard", max_tokens=700),
        ),
    )


def _ctx(*, runtime, response_text: str, question: str = "Latest on the Fable LLM?") -> DmReplyContext:
    return DmReplyContext(
        runtime=runtime, agent=SimpleNamespace(agent_id="ezri"), agent_id="ezri",
        callsign="Ezri", req_message=question, reply=DmReply(body=response_text),
        has_image_attachment=False, per_attachment=[], sanity_gate=DmSanityGate(),
        params={}, message_text=question, sampling_state=None, avatar_event_bus=None,
    )


_LINKS = "Result 1:\nTitle: Fable 5\nURL: https://x/a\nSnippet: launched June 9."


# ---------------------------------------------------------------------------
# synthesis ON — web_search reasons over the result
# ---------------------------------------------------------------------------


async def test_web_search_synthesises_when_enabled():
    llm = _CapturingLLM()
    rt = _runtime(result_text=_LINKS, llm=llm, enabled=True)
    ctx = _ctx(runtime=rt, response_text="Sure — pulling that now. [MESH web_search query=fable llm]")
    await DmReplyPipeline(ctx).step_4h_mesh_read_parse()
    # The synthesised answer replaces the raw link list.
    assert "SYNTHESISED ANSWER" in ctx.response_text
    assert "Result 1:" not in ctx.response_text
    # The agent's preamble survives (synthesis follows it in one turn).
    assert "Sure" in ctx.response_text
    # exactly one synthesis pass
    assert len(llm.calls) == 1


async def test_synthesis_prompt_carries_question_and_results():
    llm = _CapturingLLM()
    rt = _runtime(result_text=_LINKS, llm=llm, enabled=True)
    ctx = _ctx(runtime=rt, response_text="[MESH web_search query=fable]", question="Why was Fable blocked?")
    await DmReplyPipeline(ctx).step_4h_mesh_read_parse()
    req = llm.calls[0]
    assert "Why was Fable blocked?" in req.prompt          # the Captain's question
    assert "Result 1:" in req.prompt                       # the rendered results
    assert "Ezri" in req.system_prompt                     # the agent's voice
    assert req.tier == "standard"


async def test_read_page_also_synthesises():
    llm = _CapturingLLM()
    rt = _runtime(result_text="<page text about the directive>", llm=llm, enabled=True)
    ctx = _ctx(runtime=rt, response_text="[MESH read_page url=https://x/a]")
    await DmReplyPipeline(ctx).step_4h_mesh_read_parse()
    assert "SYNTHESISED ANSWER" in ctx.response_text
    assert len(llm.calls) == 1


# ---------------------------------------------------------------------------
# synthesis OFF / non-synthesise reads — verbatim, no LLM call
# ---------------------------------------------------------------------------


async def test_disabled_renders_verbatim():
    llm = _CapturingLLM()
    rt = _runtime(result_text=_LINKS, llm=llm, enabled=False)
    ctx = _ctx(runtime=rt, response_text="[MESH web_search query=fable]")
    await DmReplyPipeline(ctx).step_4h_mesh_read_parse()
    assert "Result 1:" in ctx.response_text   # raw results pasted
    assert llm.calls == []                     # no synthesis pass


async def test_read_file_is_not_synthesised():
    # read_file is a verbatim read (the file content IS the answer) — no synthesis
    # even when enabled.
    llm = _CapturingLLM()
    rt = _runtime(result_text="line1\nline2\nline3", llm=llm, enabled=True)
    ctx = _ctx(runtime=rt, response_text="[MESH read_file path=/tmp/x]")
    await DmReplyPipeline(ctx).step_4h_mesh_read_parse()
    assert "line1" in ctx.response_text
    assert llm.calls == []


# ---------------------------------------------------------------------------
# honest-degrade — keeps verbatim results on any LLM failure
# ---------------------------------------------------------------------------


async def test_empty_llm_falls_back_to_verbatim():
    # The exact BF-289/612 empty-content surface: a degraded proxy must NOT drop
    # the Captain's results — fall back to the raw list.
    llm = _CapturingLLM(content="")
    rt = _runtime(result_text=_LINKS, llm=llm, enabled=True)
    ctx = _ctx(runtime=rt, response_text="[MESH web_search query=fable]")
    await DmReplyPipeline(ctx).step_4h_mesh_read_parse()
    assert "Result 1:" in ctx.response_text   # results preserved
    assert len(llm.calls) == 1


async def test_no_llm_client_falls_back_to_verbatim():
    rt = _runtime(result_text=_LINKS, llm=None, enabled=True)
    ctx = _ctx(runtime=rt, response_text="[MESH web_search query=fable]")
    await DmReplyPipeline(ctx).step_4h_mesh_read_parse()
    assert "Result 1:" in ctx.response_text


async def test_raising_llm_falls_back_to_verbatim():
    llm = _CapturingLLM(raises=True)
    rt = _runtime(result_text=_LINKS, llm=llm, enabled=True)
    ctx = _ctx(runtime=rt, response_text="[MESH web_search query=fable]")
    await DmReplyPipeline(ctx).step_4h_mesh_read_parse()
    assert "Result 1:" in ctx.response_text   # degrade, not crash
    assert len(llm.calls) == 1


async def test_failed_read_does_not_synthesise():
    # An UNSUCCESSFUL read never reaches synthesis (no results to reason over).
    class _FailBus:
        async def send(self, intent):
            return SimpleNamespace(success=False, result=None, error="timeout")

    llm = _CapturingLLM()
    rt = SimpleNamespace(
        intent_bus=_FailBus(), registry=_PoolRegistry(), llm_client=llm,
        intent_grant_store=None,
        config=SimpleNamespace(dm_mesh_synthesis=SimpleNamespace(enabled=True, tier="standard", max_tokens=700)),
    )
    ctx = _ctx(runtime=rt, response_text="[MESH web_search query=fable]")
    await DmReplyPipeline(ctx).step_4h_mesh_read_parse()
    assert llm.calls == []   # no synthesis on a failed read
