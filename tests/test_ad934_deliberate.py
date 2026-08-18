"""AD-934 (Option C): in-chat [THINK]/[DELIBERATE] deep-tier re-roll.

An agent may emit ``[THINK]`` or ``[DELIBERATE]`` in its draft reply. The new
flag-gated ``DmReplyPipeline.step_4j_deliberate_parse`` parses the marker and,
when ``config.dm_deliberate.enabled`` is True (default OFF), makes a single
deep-tier LLM pass that reconsiders + improves the draft, replacing the reply
text. The marker is ALWAYS stripped so it never leaks to the Captain. Tier-2
honest-degrade: a missing client / empty / raised response keeps the draft.

BF-287 discipline: REAL fixtures only — a real ``DmSanityGate``, a real
``DmDeliberateConfig``, a ``DmReplyContext`` built directly, and a
``_FakeLLMClient`` that is a real attribute object (NOT ``MagicMock``) whose
``complete()`` records the request and returns an object carrying ``.content``.
The teaching hook is exercised via the REAL
``CognitiveAgent._conversational_deliberate_protocol`` bound to a
``SimpleNamespace`` self.
"""

from __future__ import annotations

from types import SimpleNamespace

from probos.cognitive.cognitive_agent import CognitiveAgent
from probos.cognitive.decomposer import _CAPABILITY_GAP_RE
from probos.cognitive.dm.reply_pipeline import DmReplyContext, DmReplyPipeline
from probos.cognitive.dm_sanity_gate import DmSanityGate
from probos.config import DmDeliberateConfig
from probos.cognitive.dm.reply_value import DmReply  # AD-1248


# --------------------------------------------------------------------------- #
# BF-287 real-but-fake stubs                                                   #
# --------------------------------------------------------------------------- #


class _FakeLLMResponse:
    """Minimal LLMResponse stand-in carrying only ``.content`` (the field
    ``step_4j_deliberate_parse`` reads). A real attribute object, not a mock."""

    def __init__(self, content: str) -> None:
        self.content = content


class _FakeLLMClient:
    """Real-but-fake LLM client. Records every request and returns a
    preconfigured response (or raises). The signature mirrors the real
    ``OpenAICompatibleClient.complete`` (request positional, ``priority``
    keyword-only) so a wrong call site fails loudly rather than silently."""

    def __init__(self, *, content: str = "", raises: bool = False) -> None:
        self._content = content
        self._raises = raises
        self.calls: list = []

    async def complete(self, request, *, priority=None):
        self.calls.append(request)
        if self._raises:
            raise RuntimeError("boom")
        return _FakeLLMResponse(self._content)


def _runtime(*, enabled: bool, llm_client=None, tier: str = "deep") -> SimpleNamespace:
    """A SimpleNamespace runtime carrying a REAL ``DmDeliberateConfig`` under
    ``config.dm_deliberate`` plus an optional ``llm_client``."""
    cfg = SimpleNamespace(dm_deliberate=DmDeliberateConfig(enabled=enabled, tier=tier))
    return SimpleNamespace(config=cfg, llm_client=llm_client)


def _make_ctx(*, runtime, response_text: str, sanity_gate) -> DmReplyContext:
    return DmReplyContext(
        runtime=runtime,
        agent=SimpleNamespace(id="a1", agent_type="counselor"),
        agent_id="a1",
        callsign="Scout",
        req_message="What is the best approach here, and why?",
        reply=DmReply(body=response_text),
        has_image_attachment=False,
        per_attachment=[],
        sanity_gate=sanity_gate,
        params={},
        message_text="What is the best approach here, and why?",
        sampling_state=None,
        avatar_event_bus=None,
    )


# --------------------------------------------------------------------------- #
# 1. extract_deliberate                                                        #
# --------------------------------------------------------------------------- #


def test_extract_deliberate_detects_markers_and_rejects_others() -> None:
    gate = DmSanityGate()
    assert gate.extract_deliberate("Here. [THINK]") is True
    assert gate.extract_deliberate("Here. [THINK be rigorous]") is True
    assert gate.extract_deliberate("Here. [DELIBERATE]") is True
    assert gate.extract_deliberate("Just a normal reply, no markers.") is False
    assert gate.extract_deliberate("") is False


# --------------------------------------------------------------------------- #
# 2. strip_deliberate                                                          #
# --------------------------------------------------------------------------- #


def test_strip_deliberate_removes_marker_and_is_idempotent() -> None:
    gate = DmSanityGate()
    assert gate.strip_deliberate("Here is my answer. [THINK]") == "Here is my answer."
    assert (
        gate.strip_deliberate("Think harder. [DELIBERATE focus]")
        == "Think harder."
    )
    # Idempotent on text without a marker.
    assert gate.strip_deliberate("No marker here.") == "No marker here."
    assert gate.strip_deliberate("") == ""


# --------------------------------------------------------------------------- #
# 3. flag OFF + marker -> strip only, no llm call                             #
# --------------------------------------------------------------------------- #


async def test_flag_off_marker_strips_and_makes_no_llm_call() -> None:
    client = _FakeLLMClient(content="should not be used")
    ctx = _make_ctx(
        runtime=_runtime(enabled=False, llm_client=client),
        response_text="Here is my answer. [THINK]",
        sanity_gate=DmSanityGate(),
    )
    await DmReplyPipeline(ctx).step_4j_deliberate_parse()

    assert client.calls == []  # flag OFF -> no deep-tier pass
    assert ctx.response_text == "Here is my answer."  # marker still stripped


# --------------------------------------------------------------------------- #
# 4. flag ON + marker + refined content -> replaced, one deep-tier call       #
# --------------------------------------------------------------------------- #


async def test_flag_on_marker_refined_replaces_draft() -> None:
    client = _FakeLLMClient(content="refined reply")
    ctx = _make_ctx(
        runtime=_runtime(enabled=True, llm_client=client),
        response_text="Quick take. [THINK]",
        sanity_gate=DmSanityGate(),
    )
    await DmReplyPipeline(ctx).step_4j_deliberate_parse()

    assert ctx.response_text == "refined reply"
    assert "[THINK]" not in ctx.response_text
    assert len(client.calls) == 1
    assert client.calls[0].tier == "deep"


# --------------------------------------------------------------------------- #
# 5. flag ON + NO marker -> no llm call, unchanged                            #
# --------------------------------------------------------------------------- #


async def test_flag_on_no_marker_makes_no_call() -> None:
    client = _FakeLLMClient(content="should not be used")
    ctx = _make_ctx(
        runtime=_runtime(enabled=True, llm_client=client),
        response_text="Just a normal reply.",
        sanity_gate=DmSanityGate(),
    )
    await DmReplyPipeline(ctx).step_4j_deliberate_parse()

    assert client.calls == []
    assert ctx.response_text == "Just a normal reply."


# --------------------------------------------------------------------------- #
# 6. flag ON + marker + empty response -> honest-degrade to draft            #
# --------------------------------------------------------------------------- #


async def test_flag_on_empty_response_degrades_to_draft() -> None:
    client = _FakeLLMClient(content="")
    ctx = _make_ctx(
        runtime=_runtime(enabled=True, llm_client=client),
        response_text="Draft answer. [THINK]",
        sanity_gate=DmSanityGate(),
    )
    await DmReplyPipeline(ctx).step_4j_deliberate_parse()

    assert len(client.calls) == 1
    assert ctx.response_text == "Draft answer."  # marker stripped, draft kept


# --------------------------------------------------------------------------- #
# 7. flag ON + marker + client raises -> honest-degrade, no propagation       #
# --------------------------------------------------------------------------- #


async def test_flag_on_client_raises_degrades_to_draft() -> None:
    client = _FakeLLMClient(raises=True)
    ctx = _make_ctx(
        runtime=_runtime(enabled=True, llm_client=client),
        response_text="Draft answer. [DELIBERATE]",
        sanity_gate=DmSanityGate(),
    )
    # Must NOT raise.
    await DmReplyPipeline(ctx).step_4j_deliberate_parse()

    assert len(client.calls) == 1
    assert ctx.response_text == "Draft answer."


# --------------------------------------------------------------------------- #
# 8. flag ON + llm_client is None -> degrade to draft, no crash               #
# --------------------------------------------------------------------------- #


async def test_flag_on_missing_client_degrades_to_draft() -> None:
    ctx = _make_ctx(
        runtime=_runtime(enabled=True, llm_client=None),
        response_text="Draft answer. [THINK]",
        sanity_gate=DmSanityGate(),
    )
    await DmReplyPipeline(ctx).step_4j_deliberate_parse()

    assert ctx.response_text == "Draft answer."


# --------------------------------------------------------------------------- #
# 9. step_4j registration in both tuples                                       #
# --------------------------------------------------------------------------- #


def test_full_steps_orders_4j_between_4g_and_5() -> None:
    pipeline = DmReplyPipeline(
        _make_ctx(runtime=SimpleNamespace(), response_text="x", sanity_gate=None)
    )
    names = [s.__name__ for s in pipeline._full_steps()]
    assert len(names) == 20  # AD-1081 added step_4l_extract_todos
    assert (
        names.index("step_4g_create_task_parse")
        < names.index("step_4j_deliberate_parse")
        < names.index("step_5_episodic_store")
    )


def test_escalation_subset_appends_4j_after_4g() -> None:
    pipeline = DmReplyPipeline(
        _make_ctx(runtime=SimpleNamespace(), response_text="x", sanity_gate=None)
    )
    names = [s.__name__ for s in pipeline._escalation_steps()]
    assert names == [
        "step_4c_image_gen_parse",
        "step_4e_action_dispatch",
        "step_4i_notebook_parse",
        "step_4h_mesh_read_parse",
        "step_4f_extract_artifacts",
        "step_4k_extract_a2ui",  # AD-811c: group fan-out now extracts A2UI (4f -> 4k -> 4g)
        "step_4g_create_task_parse",
        "step_4l_extract_todos",  # AD-1081 room-Todo validation loop
        "step_4j_deliberate_parse",
    ]


# --------------------------------------------------------------------------- #
# 10. teaching hook (flag-gated, gap-regex-safe) + config defaults            #
# --------------------------------------------------------------------------- #


def test_conversational_deliberate_protocol_off_returns_empty() -> None:
    fake_self = SimpleNamespace(_runtime=_runtime(enabled=False))
    out = CognitiveAgent._conversational_deliberate_protocol(fake_self, {})
    assert out == ""


def test_conversational_deliberate_protocol_no_runtime_returns_empty() -> None:
    fake_self = SimpleNamespace(_runtime=None)
    assert CognitiveAgent._conversational_deliberate_protocol(fake_self, {}) == ""


def test_conversational_deliberate_protocol_on_is_nonempty_and_gap_safe() -> None:
    fake_self = SimpleNamespace(_runtime=_runtime(enabled=True))
    out = CognitiveAgent._conversational_deliberate_protocol(fake_self, {})
    assert out  # non-empty when flag ON
    assert "[THINK]" in out
    # Gap-regex safety (the _CAPABILITY_GAP_RE lesson): the teaching string
    # must not read like a capability-gap confession.
    assert _CAPABILITY_GAP_RE.search(out) is None
    for banned in ("can't", "cannot", "don't have", "unable to", "not able to"):
        assert banned not in out.lower()


def test_dm_deliberate_config_defaults() -> None:
    cfg = DmDeliberateConfig()
    assert cfg.enabled is False
    assert cfg.tier == "deep"
    assert cfg.max_tokens == 800
