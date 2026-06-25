"""AD-811b-1: A2UI form widget (the 3rd widget kind on the N-kind dispatch).

Adds the ``form`` widget kind (multi-field labeled free-text input) on the
AD-811b multiselect + dispatch foundation. The key shape difference: a
``form`` carries ``fields`` (label + free-text per field) and has NO
``options`` — so the extractor's option-gate already no-ops for it
(``getattr(spec, "options", None) is None``), which is proved here
BEHAVIORALLY (``a2ui_extractor.py`` is UNTOUCHED).

The AD-811a ``choice`` + AD-811b ``multiselect`` paths stay byte-identical
— their backend tests (``test_ad811a_a2ui_choice.py`` /
``test_ad811b_a2ui_multiselect.py``) pass UNCHANGED; this file ALSO
re-asserts both THROUGH the registry to prove no regression.

BF-287 discipline: the extractor + pipeline-step tests use a REAL
``ArtifactStore`` + a REAL filesystem ``AttachmentStore`` on ``tmp_path``
(no MagicMock at the storage boundary). The teaching-block tests use the
unbound-method + ``SimpleNamespace`` ``fake_self`` pattern (mirrors 811a/b).
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from probos.a2ui import (
    AgentUIChoiceSpec,
    AgentUIFormField,
    AgentUIFormSpec,
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


# --------------------------------------------------------------------------- #
# helpers (mirror test_ad811b_a2ui_multiselect)                               #
# --------------------------------------------------------------------------- #

def _stores(tmp_path):
    art = ArtifactStore(tmp_path / "artifacts.db")
    att = FilesystemAttachmentStore(tmp_path / "attachments")
    return art, att


def _ctx(**overrides) -> DmReplyContext:
    base = dict(
        runtime=None, agent=None, agent_id="yeo", callsign=None,
        req_message="", response_text="", has_image_attachment=False,
        per_attachment=[], sanity_gate=None, params={}, message_text="",
        sampling_state=None, avatar_event_bus=None,
    )
    base.update(overrides)
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


_FORM_JSON = (
    '{"kind":"form","prompt":"Tell me about you","fields":'
    '[{"label":"Name"},{"label":"Role","required":true}]}'
)
_MS_JSON = (
    '{"kind":"multiselect","prompt":"Pick some","options":'
    '["Alpha","Beta","Gamma"]}'
)
_CHOICE_JSON = (
    '{"kind":"choice","prompt":"Pick a plan","options":["Plan A","Plan B"]}'
)


# --------------------------------------------------------------------------- #
# 1. schema — AgentUIFormSpec / AgentUIFormField                              #
# --------------------------------------------------------------------------- #

def test_form_spec_valid_parses() -> None:
    spec = AgentUIFormSpec.from_json(_FORM_JSON)
    assert spec.kind == "form"
    assert spec.prompt == "Tell me about you"
    assert len(spec.fields) == 2
    assert spec.fields[0].label == "Name"
    assert spec.fields[0].required is False
    assert spec.fields[1].label == "Role"
    assert spec.fields[1].required is True


def test_form_spec_required_flag_explicit_true() -> None:
    spec = AgentUIFormSpec(
        prompt="q", fields=[AgentUIFormField(label="X", required=True)],
    )
    again = AgentUIFormSpec.from_json(spec.to_json())
    assert again.fields[0].required is True


def test_form_spec_empty_label_fields_dropped() -> None:
    spec = AgentUIFormSpec(
        prompt="q",
        fields=[
            AgentUIFormField(label="A"),
            AgentUIFormField(label="  "),
            AgentUIFormField(label=""),
            AgentUIFormField(label="B"),
        ],
    )
    assert [f.label for f in spec.fields] == ["A", "B"]


def test_form_spec_dedupe_by_label_preserves_order() -> None:
    spec = AgentUIFormSpec(
        prompt="q",
        fields=[AgentUIFormField(label=lbl) for lbl in ["A", "B", "A", "C", "B"]],
    )
    assert [f.label for f in spec.fields] == ["A", "B", "C"]


def test_form_spec_zero_fields_rejected() -> None:
    with pytest.raises(Exception):
        AgentUIFormSpec(prompt="q", fields=[])


def test_form_spec_over_max_fields_rejected() -> None:
    too_many = [AgentUIFormField(label=f"f{i}") for i in range(21)]  # 21 > 20
    with pytest.raises(Exception):
        AgentUIFormSpec(prompt="q", fields=too_many)


def test_form_spec_single_field_ok() -> None:
    # forms allow 1 field (unlike choice's 2-option floor).
    spec = AgentUIFormSpec(prompt="q", fields=[AgentUIFormField(label="Only")])
    assert len(spec.fields) == 1


def test_form_spec_empty_prompt_rejected() -> None:
    with pytest.raises(Exception):
        AgentUIFormSpec(prompt="   ", fields=[AgentUIFormField(label="A")])


def test_form_spec_kind_not_form_rejected() -> None:
    with pytest.raises(Exception):
        AgentUIFormSpec.from_json(
            '{"kind":"choice","prompt":"q","fields":[{"label":"A"}]}'
        )


def test_form_spec_to_json_from_json_roundtrip() -> None:
    spec = AgentUIFormSpec(
        prompt="q",
        fields=[
            AgentUIFormField(label="Name"),
            AgentUIFormField(label="Role", required=True),
        ],
    )
    again = AgentUIFormSpec.from_json(spec.to_json())
    assert again.kind == "form"
    assert again.prompt == "q"
    assert [f.label for f in again.fields] == ["Name", "Role"]
    assert [f.required for f in again.fields] == [False, True]


# --------------------------------------------------------------------------- #
# 2. dispatch — parse_a2ui_spec (the N-kind registry, now with form)          #
# --------------------------------------------------------------------------- #

def test_dispatch_form_returns_form_spec() -> None:
    spec = parse_a2ui_spec(_FORM_JSON)
    assert isinstance(spec, AgentUIFormSpec)
    assert spec.kind == "form"


def test_dispatch_choice_still_returns_choice() -> None:
    # AD-811a regression THROUGH the registry (now that form is registered).
    spec = parse_a2ui_spec(_CHOICE_JSON)
    assert isinstance(spec, AgentUIChoiceSpec)
    assert spec.kind == "choice"


def test_dispatch_multiselect_still_returns_ms() -> None:
    # AD-811b regression THROUGH the registry.
    spec = parse_a2ui_spec(_MS_JSON)
    assert isinstance(spec, AgentUIMultiSelectSpec)
    assert spec.kind == "multiselect"


def test_dispatch_truly_unknown_kind_returns_none() -> None:
    # A non-stale unknown-kind guard: "range" is NOT registered (the 811b
    # test's kind:"form" example is now a *valid* kind, so this replaces its
    # semantic intent here).
    assert parse_a2ui_spec(
        '{"kind":"range","prompt":"q","min":0,"max":10}'
    ) is None


def test_dispatch_form_missing_fields_returns_none() -> None:
    # valid kind, invalid spec (no fields) -> None.
    assert parse_a2ui_spec('{"kind":"form","prompt":"q"}') is None


def test_dispatch_form_zero_fields_returns_none() -> None:
    assert parse_a2ui_spec('{"kind":"form","prompt":"q","fields":[]}') is None


def test_dispatch_malformed_json_returns_none() -> None:
    assert parse_a2ui_spec("{not valid json") is None


def test_dispatch_non_dict_returns_none() -> None:
    assert parse_a2ui_spec("[1, 2, 3]") is None
    assert parse_a2ui_spec('"just a string"') is None


# --------------------------------------------------------------------------- #
# 3. extractor — extract_a2ui (module UNCHANGED; behavioral proof)            #
# --------------------------------------------------------------------------- #

def test_extract_form_block() -> None:
    text = f"Here you go [A2UI]{_FORM_JSON}[/A2UI] thanks"
    specs = extract_a2ui(text)
    assert len(specs) == 1
    assert isinstance(specs[0], AgentUIFormSpec)
    assert specs[0].prompt == "Tell me about you"


def test_extract_form_ignores_option_gate() -> None:
    # KEY GUARD: a form with 5 fields + max_options=3 STILL extracts, because
    # the option-gate no-ops for an option-less spec (getattr(form, "options",
    # None) is None). a2ui_extractor.py is UNTOUCHED.
    fields = ",".join(f'{{"label":"f{i}"}}' for i in range(5))
    text = f'[A2UI]{{"kind":"form","prompt":"q","fields":[{fields}]}}[/A2UI]'
    specs = extract_a2ui(text, max_options=3)
    assert len(specs) == 1
    assert isinstance(specs[0], AgentUIFormSpec)
    assert len(specs[0].fields) == 5


def test_extract_choice_still_gated() -> None:
    # The option-gate is UNCHANGED for option-bearing specs.
    opts = ",".join(f'"o{i}"' for i in range(5))
    text = f'[A2UI]{{"kind":"choice","prompt":"q","options":[{opts}]}}[/A2UI]'
    assert extract_a2ui(text, max_options=3) == []
    assert len(extract_a2ui(text, max_options=5)) == 1


def test_extract_multiselect_still_gated() -> None:
    opts = ",".join(f'"o{i}"' for i in range(5))
    text = (
        f'[A2UI]{{"kind":"multiselect","prompt":"q","options":[{opts}]}}'
        f"[/A2UI]"
    )
    assert extract_a2ui(text, max_options=3) == []
    assert len(extract_a2ui(text, max_options=5)) == 1


# --------------------------------------------------------------------------- #
# 4. stub + AD-797 two-call write                                             #
# --------------------------------------------------------------------------- #

def test_build_stub_form_kind() -> None:
    assert build_a2ui_stub("a2ui-form-1.json", 1, "form") == (
        "[A2UI: a2ui-form-1.json v1 - form]"
    )


@pytest.mark.asyncio
async def test_replace_form_names_and_stub(tmp_path) -> None:
    art, att = _stores(tmp_path)
    text = f"Fill this: [A2UI]{_FORM_JSON}[/A2UI] please"
    specs = extract_a2ui(text)
    new_text, artifacts = await replace_a2ui_with_stubs(
        text, specs, artifact_store=art, attachment_store=att,
        thread_id="thread-1", created_by="yeo",
    )
    assert "[A2UI: a2ui-form-1.json v1 - form]" in new_text
    assert "[A2UI]" not in new_text
    assert "[/A2UI]" not in new_text
    assert len(artifacts) == 1
    assert artifacts[0].name == "a2ui-form-1.json"
    assert artifacts[0].version == 1
    assert artifacts[0].mime == "application/json"
    latest = art.latest(thread_id="thread-1", name="a2ui-form-1.json")
    assert latest is not None


# --------------------------------------------------------------------------- #
# 5. pipeline — step_4k_extract_a2ui (form + default-OFF)                     #
# --------------------------------------------------------------------------- #

@pytest.mark.asyncio
async def test_step_4k_enabled_extracts_form(tmp_path) -> None:
    runtime, art, _ = _runtime_with_stores(tmp_path, enabled=True)
    text = f"reply [A2UI]{_FORM_JSON}[/A2UI] end"
    ctx = _ctx(runtime=runtime, response_text=text, chat_thread_id="thread-1")
    pipe = DmReplyPipeline(ctx)
    await pipe.step_4k_extract_a2ui()
    assert "[A2UI: a2ui-form-1.json v1 - form]" in ctx.response_text
    assert "[A2UI]" not in ctx.response_text
    assert art.latest(thread_id="thread-1", name="a2ui-form-1.json") is not None


@pytest.mark.asyncio
async def test_step_4k_disabled_form_byte_identical(tmp_path) -> None:
    runtime, art, _ = _runtime_with_stores(tmp_path, enabled=False)
    text = f"reply [A2UI]{_FORM_JSON}[/A2UI] end"
    ctx = _ctx(runtime=runtime, response_text=text, chat_thread_id="thread-1")
    pipe = DmReplyPipeline(ctx)
    await pipe.step_4k_extract_a2ui()
    # flag OFF -> text unchanged + no artifact written (byte-identical)
    assert ctx.response_text == text
    assert art.latest(thread_id="thread-1", name="a2ui-form-1.json") is None


# --------------------------------------------------------------------------- #
# 6. teaching block — teaches form, still choice + multiselect, gap-clean      #
# --------------------------------------------------------------------------- #

def test_form_teach_contains_form_kind() -> None:
    out = CognitiveAgent._conversational_a2ui_block(
        _teach_self(enabled=True, trust=0.9), {}
    )
    assert out
    assert "form" in out
    assert "choice" in out
    assert "multiselect" in out


def test_form_teach_gap_regex_clean() -> None:
    out = CognitiveAgent._conversational_a2ui_block(
        _teach_self(enabled=True, trust=0.9), {}
    )
    assert out
    assert _CAPABILITY_GAP_RE.search(out) is None
    for banned in ("can't", "cannot", "don't have", "unable to", "not able to"):
        assert banned not in out.lower()
