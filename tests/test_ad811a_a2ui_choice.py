"""AD-811a: A2UI choice widget — schema, extractor, teaching block, pipeline.

BF-287 discipline: the extractor + pipeline-step tests use a REAL
``ArtifactStore`` + a REAL filesystem ``AttachmentStore`` on ``tmp_path``
(no MagicMock at the storage boundary), so the AD-797 two-call write is
exercised end to end. The teaching-block tests use the unbound-method +
``SimpleNamespace`` ``fake_self`` pattern (mirrors test_ad934_deliberate).
"""

from __future__ import annotations

import hashlib
from types import SimpleNamespace

import pytest

from probos.a2ui import AgentUIChoiceSpec
from probos.artifacts import ArtifactStore
from probos.attachments.filesystem_store import FilesystemAttachmentStore
from probos.cognitive.cognitive_agent import CognitiveAgent
from probos.cognitive.decomposer import _CAPABILITY_GAP_RE
from probos.cognitive.dm.a2ui_extractor import (
    build_a2ui_stub,
    extract_a2ui,
    replace_a2ui_with_stubs,
)
from probos.cognitive.dm.reply_pipeline import DmReplyContext, DmReplyPipeline
from probos.cognitive.dm.reply_value import DmReply  # AD-1248


# --------------------------------------------------------------------------- #
# helpers                                                                      #
# --------------------------------------------------------------------------- #

def _stores(tmp_path):
    art = ArtifactStore(tmp_path / "artifacts.db")
    att = FilesystemAttachmentStore(tmp_path / "attachments")
    return art, att


def _ctx(**overrides) -> DmReplyContext:
    base = dict(
        runtime=None, agent=None, agent_id="yeo", callsign=None,
        req_message="", reply=DmReply(body=""), has_image_attachment=False,
        per_attachment=[], sanity_gate=None, params={}, message_text="",
        sampling_state=None, avatar_event_bus=None,
    )
    base.update(overrides)
    # AD-1248: callers still express the body as text.
    if "response_text" in base:
        base["reply"] = DmReply(body=base.pop("response_text"))
    return DmReplyContext(**base)


def _runtime_with_stores(tmp_path, *, enabled: bool, max_options: int = 10):
    art, att = _stores(tmp_path)
    comms = SimpleNamespace(a2ui_enabled=enabled, a2ui_max_options=max_options)
    runtime = SimpleNamespace(
        config=SimpleNamespace(communications=comms),
        artifact_store=art, attachment_store=att,
    )
    return runtime, art, att


class _FakeTrust:
    def __init__(self, score: float) -> None:
        self._score = score

    def get_score(self, agent_id: str) -> float:
        del agent_id
        return self._score


def _teach_self(*, enabled: bool, trust: float = 0.6,
                min_rank: str = "lieutenant") -> SimpleNamespace:
    comms = SimpleNamespace(a2ui_enabled=enabled, a2ui_min_rank=min_rank)
    runtime = SimpleNamespace(
        config=SimpleNamespace(communications=comms),
        trust_network=_FakeTrust(trust),
    )
    return SimpleNamespace(id="agent-1", _runtime=runtime)


_CHOICE_JSON = (
    '{"kind":"choice","prompt":"Pick a plan","options":["Plan A","Plan B"]}'
)


# --------------------------------------------------------------------------- #
# 1. schema — AgentUIChoiceSpec                                                #
# --------------------------------------------------------------------------- #

def test_choice_spec_valid_parses() -> None:
    spec = AgentUIChoiceSpec.from_json(_CHOICE_JSON)
    assert spec.kind == "choice"
    assert spec.prompt == "Pick a plan"
    assert spec.options == ["Plan A", "Plan B"]


def test_choice_spec_too_few_options_rejected() -> None:
    with pytest.raises(Exception):
        AgentUIChoiceSpec(prompt="q", options=["only one"])


def test_choice_spec_empty_options_dropped() -> None:
    spec = AgentUIChoiceSpec(prompt="q", options=["A", "  ", "", "B"])
    assert spec.options == ["A", "B"]


def test_choice_spec_dedupe_preserves_order() -> None:
    spec = AgentUIChoiceSpec(prompt="q", options=["A", "B", "A", "C", "B"])
    assert spec.options == ["A", "B", "C"]


def test_choice_spec_over_hard_cap_rejected() -> None:
    too_many = [f"opt{i}" for i in range(21)]  # 21 > hard cap of 20
    with pytest.raises(Exception):
        AgentUIChoiceSpec(prompt="q", options=too_many)


def test_choice_spec_trims_prompt_and_options() -> None:
    spec = AgentUIChoiceSpec(prompt="  hi  ", options=["  A  ", "B  "])
    assert spec.prompt == "hi"
    assert spec.options == ["A", "B"]


def test_choice_spec_empty_prompt_rejected() -> None:
    with pytest.raises(Exception):
        AgentUIChoiceSpec(prompt="   ", options=["A", "B"])


def test_choice_spec_kind_not_choice_rejected() -> None:
    with pytest.raises(Exception):
        AgentUIChoiceSpec.from_json(
            '{"kind":"form","prompt":"q","options":["A","B"]}'
        )


def test_choice_spec_to_json_from_json_roundtrip() -> None:
    spec = AgentUIChoiceSpec(prompt="q", options=["A", "B"])
    again = AgentUIChoiceSpec.from_json(spec.to_json())
    assert again.prompt == "q"
    assert again.options == ["A", "B"]
    assert again.kind == "choice"


# --------------------------------------------------------------------------- #
# 2. extractor — extract_a2ui / build_a2ui_stub                               #
# --------------------------------------------------------------------------- #

def test_extract_a2ui_valid_block() -> None:
    text = f"Here you go [A2UI]{_CHOICE_JSON}[/A2UI] thanks"
    specs = extract_a2ui(text)
    assert len(specs) == 1
    assert specs[0].prompt == "Pick a plan"


def test_extract_a2ui_case_insensitive_tag() -> None:
    text = f"[a2ui]{_CHOICE_JSON}[/a2ui]"
    assert len(extract_a2ui(text)) == 1


def test_extract_a2ui_malformed_json_skipped() -> None:
    assert extract_a2ui("[A2UI]{not valid json[/A2UI]") == []


def test_extract_a2ui_invalid_spec_skipped() -> None:
    # kind != choice -> from_json raises -> skipped
    bad = '{"kind":"form","prompt":"q","options":["A","B"]}'
    assert extract_a2ui(f"[A2UI]{bad}[/A2UI]") == []


def test_extract_a2ui_over_max_options_skipped() -> None:
    opts = ",".join(f'"o{i}"' for i in range(5))
    text = f'[A2UI]{{"kind":"choice","prompt":"q","options":[{opts}]}}[/A2UI]'
    # 5 valid options, but max_options=3 gates them out
    assert extract_a2ui(text, max_options=3) == []
    # ... and are honored when the cap allows
    assert len(extract_a2ui(text, max_options=5)) == 1


def test_extract_a2ui_caps_at_one() -> None:
    text = f"[A2UI]{_CHOICE_JSON}[/A2UI] and [A2UI]{_CHOICE_JSON}[/A2UI]"
    assert len(extract_a2ui(text)) == 1


def test_extract_a2ui_no_block_returns_empty() -> None:
    assert extract_a2ui("just a normal reply, no widget") == []
    assert extract_a2ui("") == []


def test_build_a2ui_stub_format() -> None:
    assert build_a2ui_stub("a2ui-choice-1.json", 1) == (
        "[A2UI: a2ui-choice-1.json v1 - choice]"
    )


# --------------------------------------------------------------------------- #
# 3. two-call write — replace_a2ui_with_stubs (real stores)                    #
# --------------------------------------------------------------------------- #

@pytest.mark.asyncio
async def test_replace_two_call_write_leaves_stub(tmp_path) -> None:
    art, att = _stores(tmp_path)
    text = f"Choose: [A2UI]{_CHOICE_JSON}[/A2UI] please"
    specs = extract_a2ui(text)
    new_text, artifacts = await replace_a2ui_with_stubs(
        text, specs, artifact_store=art, attachment_store=att,
        thread_id="thread-1", created_by="yeo",
    )
    # stub left, raw tag stripped
    assert "[A2UI: a2ui-choice-1.json v1 - choice]" in new_text
    assert "[A2UI]" not in new_text
    assert "[/A2UI]" not in new_text
    # artifact metadata persisted
    assert len(artifacts) == 1
    assert artifacts[0].name == "a2ui-choice-1.json"
    assert artifacts[0].version == 1
    assert artifacts[0].mime == "application/json"
    latest = art.latest(thread_id="thread-1", name="a2ui-choice-1.json")
    assert latest is not None
    # attachment bytes landed at the expected content hash
    expected_hash = hashlib.sha256(specs[0].to_json().encode("utf-8")).hexdigest()
    assert latest.content_hash == expected_hash
    assert await att.exists(expected_hash)
    assert await att.read(expected_hash) == specs[0].to_json().encode("utf-8")


@pytest.mark.asyncio
async def test_replace_no_specs_is_noop(tmp_path) -> None:
    art, att = _stores(tmp_path)
    new_text, artifacts = await replace_a2ui_with_stubs(
        "untouched", [], artifact_store=art, attachment_store=att,
        thread_id="thread-1", created_by="yeo",
    )
    assert new_text == "untouched"
    assert artifacts == []


@pytest.mark.asyncio
async def test_replace_store_error_leaves_text_intact(tmp_path) -> None:
    art, _ = _stores(tmp_path)

    class _FailingAttachment:
        async def write(self, *a, **k):
            raise RuntimeError("disk full")

    text = f"Choose: [A2UI]{_CHOICE_JSON}[/A2UI]"
    specs = extract_a2ui(text)
    new_text, artifacts = await replace_a2ui_with_stubs(
        text, specs, artifact_store=art, attachment_store=_FailingAttachment(),
        thread_id="thread-1", created_by="yeo",
    )
    # honest-degrade: original text intact, no artifact, no raise
    assert new_text == text
    assert artifacts == []
    assert art.latest(thread_id="thread-1", name="a2ui-choice-1.json") is None


# --------------------------------------------------------------------------- #
# 4. pipeline step — step_4k_extract_a2ui (default-OFF byte-identical)         #
# --------------------------------------------------------------------------- #

@pytest.mark.asyncio
async def test_step_4k_disabled_is_byte_identical(tmp_path) -> None:
    runtime, art, _ = _runtime_with_stores(tmp_path, enabled=False)
    text = f"reply [A2UI]{_CHOICE_JSON}[/A2UI] end"
    ctx = _ctx(runtime=runtime, response_text=text, chat_thread_id="thread-1")
    pipe = DmReplyPipeline(ctx)
    await pipe.step_4k_extract_a2ui()
    # flag OFF -> text unchanged + no artifact written
    assert ctx.response_text == text
    assert art.latest(thread_id="thread-1", name="a2ui-choice-1.json") is None


@pytest.mark.asyncio
async def test_step_4k_enabled_extracts(tmp_path) -> None:
    runtime, art, att = _runtime_with_stores(tmp_path, enabled=True)
    text = f"reply [A2UI]{_CHOICE_JSON}[/A2UI] end"
    ctx = _ctx(runtime=runtime, response_text=text, chat_thread_id="thread-1")
    pipe = DmReplyPipeline(ctx)
    await pipe.step_4k_extract_a2ui()
    assert "[A2UI: a2ui-choice-1.json v1 - choice]" in ctx.response_text
    assert "[A2UI]" not in ctx.response_text
    assert art.latest(thread_id="thread-1", name="a2ui-choice-1.json") is not None


@pytest.mark.asyncio
async def test_step_4k_no_thread_leaves_intact(tmp_path) -> None:
    runtime, art, _ = _runtime_with_stores(tmp_path, enabled=True)
    text = f"reply [A2UI]{_CHOICE_JSON}[/A2UI] end"
    ctx = _ctx(runtime=runtime, response_text=text, chat_thread_id="")
    pipe = DmReplyPipeline(ctx)
    await pipe.step_4k_extract_a2ui()
    assert ctx.response_text == text
    assert art.latest(thread_id="", name="a2ui-choice-1.json") is None


@pytest.mark.asyncio
async def test_step_4k_no_block_noop(tmp_path) -> None:
    runtime, art, _ = _runtime_with_stores(tmp_path, enabled=True)
    ctx = _ctx(runtime=runtime, response_text="plain reply", chat_thread_id="t")
    pipe = DmReplyPipeline(ctx)
    await pipe.step_4k_extract_a2ui()
    assert ctx.response_text == "plain reply"


def test_full_steps_order_regression() -> None:
    pipe = DmReplyPipeline(_ctx())
    names = [s.__name__ for s in pipe._full_steps()]
    expected = [
        "step_1_sanity_gate_retry",
        "step_2_challenge_parse",
        "step_3_move_parse",
        "step_4_self_check_parse",
        "step_4c_image_gen_parse",
        "step_4d_follow_up_parse",
        "step_4e_action_dispatch",
        "step_4b_dm_outbound_parse",
        "step_4i_notebook_parse",
        "step_4h_mesh_read_parse",
        "step_4f_extract_artifacts",
        "step_4k_extract_a2ui",
        "step_4g_create_task_parse",
        "step_4l_extract_todos",
        "step_4j_deliberate_parse",
        # AD-1295 (#1087): the tool-loop write channel is a ledger PRODUCER, so
        # it must run before the guard that is its only consumer.
        "step_4n_tool_write_ledger",
        # AD-1285 (#1087): the write-claim guard reads the text the Captain
        # will actually see, so it must land AFTER the 4j deep-tier re-roll
        # and BEFORE the episodic store carries the corrected text.
        "step_4m_write_claim_guard",
        "step_5_episodic_store",
        "step_6_working_memory_record",
        "step_7_divergence_check",
        "step_8_mark_emitted",
        "step_9_emotion_resolve",
    ]
    assert names == expected
    # the new step sits immediately after artifacts, before create_task
    i = names.index("step_4k_extract_a2ui")
    assert names[i - 1] == "step_4f_extract_artifacts"
    assert names[i + 1] == "step_4g_create_task_parse"


def test_a2ui_step_in_escalation_steps_after_artifacts() -> None:
    # AD-811c (was the v1 "1:1 only" negative guard): group fan-out now
    # extracts A2UI too (step_4k after 4f, before 4g).
    pipe = DmReplyPipeline(_ctx())
    esc_names = [s.__name__ for s in pipe._escalation_steps()]
    assert "step_4k_extract_a2ui" in esc_names
    i = esc_names.index("step_4k_extract_a2ui")
    assert esc_names[i - 1] == "step_4f_extract_artifacts"
    assert esc_names[i + 1] == "step_4g_create_task_parse"


# --------------------------------------------------------------------------- #
# 5. teaching block — _conversational_a2ui_block                              #
# --------------------------------------------------------------------------- #

def test_a2ui_block_off_returns_empty() -> None:
    out = CognitiveAgent._conversational_a2ui_block(
        _teach_self(enabled=False), {}
    )
    assert out == ""


def test_a2ui_block_no_runtime_returns_empty() -> None:
    fake = SimpleNamespace(id="a", _runtime=None)
    assert CognitiveAgent._conversational_a2ui_block(fake, {}) == ""


def test_a2ui_block_enabled_rank_meets_renders() -> None:
    # trust 0.6 -> lieutenant, min_rank lieutenant -> renders
    out = CognitiveAgent._conversational_a2ui_block(
        _teach_self(enabled=True, trust=0.6, min_rank="lieutenant"), {}
    )
    assert out
    assert "[A2UI]" in out


def test_a2ui_block_enabled_rank_below_returns_empty() -> None:
    # trust 0.3 -> ensign, min_rank lieutenant -> below -> ""
    out = CognitiveAgent._conversational_a2ui_block(
        _teach_self(enabled=True, trust=0.3, min_rank="lieutenant"), {}
    )
    assert out == ""


def test_a2ui_block_gap_regex_clean() -> None:
    out = CognitiveAgent._conversational_a2ui_block(
        _teach_self(enabled=True, trust=0.9), {}
    )
    assert out
    assert _CAPABILITY_GAP_RE.search(out) is None
    for banned in ("can't", "cannot", "don't have", "unable to", "not able to"):
        assert banned not in out.lower()
