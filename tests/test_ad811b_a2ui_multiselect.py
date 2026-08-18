"""AD-811b: A2UI multiselect widget + multi-kind dispatch.

Adds the 2nd widget kind (``multiselect``) on the AD-811a choice
foundation and generalizes the single-kind path to a ``kind``-keyed
registry (:func:`~probos.a2ui.parse_a2ui_spec`). The AD-811a ``choice``
path stays byte-identical — its backend tests
(``test_ad811a_a2ui_choice.py``) pass UNCHANGED; this file ALSO re-asserts
the choice path THROUGH the new dispatch to prove no regression.

BF-287 discipline: the extractor + pipeline-step tests use a REAL
``ArtifactStore`` + a REAL filesystem ``AttachmentStore`` on ``tmp_path``
(no MagicMock at the storage boundary), so the AD-797 two-call write is
exercised end to end. The teaching-block tests use the unbound-method +
``SimpleNamespace`` ``fake_self`` pattern (mirrors AD-811a).
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from probos.a2ui import (
    AgentUIChoiceSpec,
    AgentUIMultiSelectSpec,
    parse_a2ui_spec,
)
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
# helpers (mirror test_ad811a_a2ui_choice)                                     #
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


def _teach_self(*, enabled: bool, trust: float = 0.9,
                min_rank: str = "lieutenant") -> SimpleNamespace:
    comms = SimpleNamespace(a2ui_enabled=enabled, a2ui_min_rank=min_rank)
    runtime = SimpleNamespace(
        config=SimpleNamespace(communications=comms),
        trust_network=_FakeTrust(trust),
    )
    return SimpleNamespace(id="agent-1", _runtime=runtime)


_MS_JSON = (
    '{"kind":"multiselect","prompt":"Pick some","options":'
    '["Alpha","Beta","Gamma"]}'
)
_CHOICE_JSON = (
    '{"kind":"choice","prompt":"Pick a plan","options":["Plan A","Plan B"]}'
)


# --------------------------------------------------------------------------- #
# 1. schema — AgentUIMultiSelectSpec (shared _clean_* helpers)                 #
# --------------------------------------------------------------------------- #

def test_ms_spec_valid_parses() -> None:
    spec = AgentUIMultiSelectSpec.from_json(_MS_JSON)
    assert spec.kind == "multiselect"
    assert spec.prompt == "Pick some"
    assert spec.options == ["Alpha", "Beta", "Gamma"]
    assert spec.min_select == 1
    assert spec.max_select is None


def test_ms_spec_empty_options_dropped() -> None:
    spec = AgentUIMultiSelectSpec(prompt="q", options=["A", "  ", "", "B"])
    assert spec.options == ["A", "B"]


def test_ms_spec_dedupe_preserves_order() -> None:
    spec = AgentUIMultiSelectSpec(prompt="q", options=["A", "B", "A", "C", "B"])
    assert spec.options == ["A", "B", "C"]


def test_ms_spec_too_few_options_rejected() -> None:
    with pytest.raises(Exception):
        AgentUIMultiSelectSpec(prompt="q", options=["only one"])


def test_ms_spec_over_hard_cap_rejected() -> None:
    too_many = [f"opt{i}" for i in range(21)]  # 21 > hard cap of 20
    with pytest.raises(Exception):
        AgentUIMultiSelectSpec(prompt="q", options=too_many)


def test_ms_spec_empty_prompt_rejected() -> None:
    with pytest.raises(Exception):
        AgentUIMultiSelectSpec(prompt="   ", options=["A", "B"])


def test_ms_spec_min_max_defaults() -> None:
    spec = AgentUIMultiSelectSpec(prompt="q", options=["A", "B", "C"])
    assert spec.min_select == 1
    assert spec.max_select is None


def test_ms_spec_min_select_below_one_rejected() -> None:
    with pytest.raises(Exception):
        AgentUIMultiSelectSpec(prompt="q", options=["A", "B"], min_select=0)


def test_ms_spec_max_select_below_min_rejected() -> None:
    with pytest.raises(Exception):
        AgentUIMultiSelectSpec(
            prompt="q", options=["A", "B", "C"], min_select=2, max_select=1,
        )


def test_ms_spec_max_select_over_len_clamped() -> None:
    spec = AgentUIMultiSelectSpec(prompt="q", options=["A", "B"], max_select=5)
    assert spec.max_select == 2  # clamped down to len(options)


def test_ms_spec_min_select_over_len_rejected() -> None:
    with pytest.raises(Exception):
        AgentUIMultiSelectSpec(prompt="q", options=["A", "B"], min_select=3)


def test_ms_spec_kind_not_multiselect_rejected() -> None:
    with pytest.raises(Exception):
        AgentUIMultiSelectSpec.from_json(
            '{"kind":"choice","prompt":"q","options":["A","B"]}'
        )


def test_ms_spec_to_json_from_json_roundtrip() -> None:
    spec = AgentUIMultiSelectSpec(
        prompt="q", options=["A", "B", "C"], min_select=2, max_select=3,
    )
    again = AgentUIMultiSelectSpec.from_json(spec.to_json())
    assert again.prompt == "q"
    assert again.options == ["A", "B", "C"]
    assert again.min_select == 2
    assert again.max_select == 3
    assert again.kind == "multiselect"


# --------------------------------------------------------------------------- #
# 2. dispatch — parse_a2ui_spec (the N-kind registry)                          #
# --------------------------------------------------------------------------- #

def test_dispatch_choice_returns_choice_spec() -> None:
    spec = parse_a2ui_spec(_CHOICE_JSON)
    assert isinstance(spec, AgentUIChoiceSpec)
    assert spec.kind == "choice"


def test_dispatch_multiselect_returns_ms_spec() -> None:
    spec = parse_a2ui_spec(_MS_JSON)
    assert isinstance(spec, AgentUIMultiSelectSpec)
    assert spec.kind == "multiselect"


def test_dispatch_unknown_kind_returns_none() -> None:
    assert parse_a2ui_spec(
        '{"kind":"form","prompt":"q","options":["A","B"]}'
    ) is None


def test_dispatch_malformed_json_returns_none() -> None:
    assert parse_a2ui_spec("{not valid json") is None


def test_dispatch_missing_kind_returns_none() -> None:
    assert parse_a2ui_spec('{"prompt":"q","options":["A","B"]}') is None


def test_dispatch_non_str_kind_returns_none() -> None:
    assert parse_a2ui_spec(
        '{"kind":123,"prompt":"q","options":["A","B"]}'
    ) is None


def test_dispatch_non_dict_returns_none() -> None:
    assert parse_a2ui_spec("[1, 2, 3]") is None
    assert parse_a2ui_spec('"just a string"') is None


def test_dispatch_valid_kind_invalid_spec_returns_none() -> None:
    # kind is registered but the spec body fails validation -> None
    assert parse_a2ui_spec(
        '{"kind":"multiselect","prompt":"q","options":["only"]}'
    ) is None


# --------------------------------------------------------------------------- #
# 3. extractor — extract_a2ui dispatch (choice 811a regression)               #
# --------------------------------------------------------------------------- #

def test_extract_multiselect_block() -> None:
    text = f"Here you go [A2UI]{_MS_JSON}[/A2UI] thanks"
    specs = extract_a2ui(text)
    assert len(specs) == 1
    assert isinstance(specs[0], AgentUIMultiSelectSpec)
    assert specs[0].prompt == "Pick some"


def test_extract_choice_block_through_dispatch() -> None:
    # AD-811a regression: choice still extracts through the new dispatch.
    text = f"Here you go [A2UI]{_CHOICE_JSON}[/A2UI] thanks"
    specs = extract_a2ui(text)
    assert len(specs) == 1
    assert isinstance(specs[0], AgentUIChoiceSpec)
    assert specs[0].prompt == "Pick a plan"


def test_extract_multiselect_over_max_options_skipped() -> None:
    opts = ",".join(f'"o{i}"' for i in range(5))
    text = (
        f'[A2UI]{{"kind":"multiselect","prompt":"q","options":[{opts}]}}'
        f"[/A2UI]"
    )
    # 5 valid options, but max_options=3 gates them out
    assert extract_a2ui(text, max_options=3) == []
    # ... and are honored when the cap allows
    assert len(extract_a2ui(text, max_options=5)) == 1


def test_extract_two_blocks_caps_at_first() -> None:
    text = f"[A2UI]{_MS_JSON}[/A2UI] and [A2UI]{_CHOICE_JSON}[/A2UI]"
    specs = extract_a2ui(text)
    assert len(specs) == 1
    assert isinstance(specs[0], AgentUIMultiSelectSpec)


# --------------------------------------------------------------------------- #
# 4. stub + two-call write (choice 811a regression byte-identical)            #
# --------------------------------------------------------------------------- #

def test_build_stub_multiselect_kind() -> None:
    assert build_a2ui_stub("a2ui-multiselect-1.json", 1, "multiselect") == (
        "[A2UI: a2ui-multiselect-1.json v1 - multiselect]"
    )


def test_build_stub_default_kind_is_choice() -> None:
    # 2-arg call stays byte-identical to AD-811a.
    assert build_a2ui_stub("a2ui-choice-1.json", 1) == (
        "[A2UI: a2ui-choice-1.json v1 - choice]"
    )


@pytest.mark.asyncio
async def test_replace_multiselect_names_and_stub(tmp_path) -> None:
    art, att = _stores(tmp_path)
    text = f"Choose: [A2UI]{_MS_JSON}[/A2UI] please"
    specs = extract_a2ui(text)
    new_text, artifacts = await replace_a2ui_with_stubs(
        text, specs, artifact_store=art, attachment_store=att,
        thread_id="thread-1", created_by="yeo",
    )
    assert "[A2UI: a2ui-multiselect-1.json v1 - multiselect]" in new_text
    assert "[A2UI]" not in new_text
    assert "[/A2UI]" not in new_text
    assert len(artifacts) == 1
    assert artifacts[0].name == "a2ui-multiselect-1.json"
    assert artifacts[0].version == 1
    assert artifacts[0].mime == "application/json"
    latest = art.latest(thread_id="thread-1", name="a2ui-multiselect-1.json")
    assert latest is not None


@pytest.mark.asyncio
async def test_replace_choice_names_and_stub_byte_identical(tmp_path) -> None:
    # AD-811a regression: choice -> a2ui-choice-1.json + "- choice".
    art, att = _stores(tmp_path)
    text = f"Choose: [A2UI]{_CHOICE_JSON}[/A2UI] please"
    specs = extract_a2ui(text)
    new_text, artifacts = await replace_a2ui_with_stubs(
        text, specs, artifact_store=art, attachment_store=att,
        thread_id="thread-1", created_by="yeo",
    )
    assert "[A2UI: a2ui-choice-1.json v1 - choice]" in new_text
    assert artifacts[0].name == "a2ui-choice-1.json"
    assert art.latest(thread_id="thread-1", name="a2ui-choice-1.json") is not None


# --------------------------------------------------------------------------- #
# 5. pipeline — step_4k_extract_a2ui (multiselect + default-OFF)              #
# --------------------------------------------------------------------------- #

@pytest.mark.asyncio
async def test_step_4k_enabled_extracts_multiselect(tmp_path) -> None:
    runtime, art, _ = _runtime_with_stores(tmp_path, enabled=True)
    text = f"reply [A2UI]{_MS_JSON}[/A2UI] end"
    ctx = _ctx(runtime=runtime, response_text=text, chat_thread_id="thread-1")
    pipe = DmReplyPipeline(ctx)
    await pipe.step_4k_extract_a2ui()
    assert (
        "[A2UI: a2ui-multiselect-1.json v1 - multiselect]" in ctx.response_text
    )
    assert "[A2UI]" not in ctx.response_text
    assert art.latest(
        thread_id="thread-1", name="a2ui-multiselect-1.json"
    ) is not None


@pytest.mark.asyncio
async def test_step_4k_disabled_multiselect_byte_identical(tmp_path) -> None:
    runtime, art, _ = _runtime_with_stores(tmp_path, enabled=False)
    text = f"reply [A2UI]{_MS_JSON}[/A2UI] end"
    ctx = _ctx(runtime=runtime, response_text=text, chat_thread_id="thread-1")
    pipe = DmReplyPipeline(ctx)
    await pipe.step_4k_extract_a2ui()
    # flag OFF -> text unchanged + no artifact written (byte-identical)
    assert ctx.response_text == text
    assert art.latest(
        thread_id="thread-1", name="a2ui-multiselect-1.json"
    ) is None


# --------------------------------------------------------------------------- #
# 6. teaching block — teaches BOTH kinds, gap-regex clean                      #
# --------------------------------------------------------------------------- #

def test_teach_enabled_contains_both_kinds() -> None:
    out = CognitiveAgent._conversational_a2ui_block(
        _teach_self(enabled=True, trust=0.9), {}
    )
    assert out
    assert "choice" in out
    assert "multiselect" in out


def test_teach_enabled_gap_regex_clean() -> None:
    out = CognitiveAgent._conversational_a2ui_block(
        _teach_self(enabled=True, trust=0.9), {}
    )
    assert out
    assert _CAPABILITY_GAP_RE.search(out) is None
    for banned in ("can't", "cannot", "don't have", "unable to", "not able to"):
        assert banned not in out.lower()
