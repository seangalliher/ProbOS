"""AD-811c: group-chat A2UI producer (#735).

AD-933 wired ``thread_fanout._send_one`` to build a ``DmReplyPipeline`` and
call ``run_escalation_only()`` for every group reply — so the group fan-out
already runs the channel-agnostic escalation subset. The only gap was that
``step_4k_extract_a2ui`` (AD-811a) was deliberately excluded from
``_escalation_steps()`` ("1:1 only, v1 scope"). AD-811c adds it (one line,
positioned ``4f -> 4k -> 4g`` to mirror ``_full_steps``) so a group agent's
``[A2UI]`` widget tag is extracted into an artifact + inline stub on the
group path, reaching full 1:1<->group producer parity.

Default-OFF: gated on the existing ``communications.a2ui_enabled`` (default
False) — the group escalation path is byte-identical when off. No UI change
(the group transcript already shares the 1:1 ``ProfileChatTab`` render path);
no new config / kind / endpoint / response correlation.

BF-287 discipline: every test uses a REAL ``DmReplyPipeline`` + REAL
``DmReplyContext`` + a REAL ``ArtifactStore`` + a REAL filesystem
``AttachmentStore`` on ``tmp_path`` (no MagicMock at the storage boundary), so
the AD-797 two-call write is exercised end to end through the actual escalation
runner. Mirrors the 1:1 ``step_4k`` tests in ``test_ad811a_a2ui_choice.py``.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from probos.artifacts import ArtifactStore
from probos.attachments.filesystem_store import FilesystemAttachmentStore
from probos.cognitive.dm.reply_pipeline import DmReplyContext, DmReplyPipeline


# --------------------------------------------------------------------------- #
# helpers (mirror test_ad811a_a2ui_choice / test_ad811b_1_a2ui_form)           #
# --------------------------------------------------------------------------- #

def _stores(base: Path):
    base.mkdir(parents=True, exist_ok=True)
    art = ArtifactStore(base / "artifacts.db")
    att = FilesystemAttachmentStore(base / "attachments")
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


def _runtime_with_stores(base: Path, *, enabled: bool, max_options: int = 10):
    art, att = _stores(base)
    comms = SimpleNamespace(a2ui_enabled=enabled, a2ui_max_options=max_options)
    runtime = SimpleNamespace(
        config=SimpleNamespace(communications=comms),
        artifact_store=art, attachment_store=att,
    )
    return runtime, art, att


_CHOICE_JSON = (
    '{"kind":"choice","prompt":"Pick a plan","options":["Plan A","Plan B"]}'
)
_MS_JSON = (
    '{"kind":"multiselect","prompt":"Pick some","options":'
    '["Alpha","Beta","Gamma"]}'
)
_FORM_JSON = (
    '{"kind":"form","prompt":"Tell me about you","fields":'
    '[{"label":"Name"},{"label":"Role","required":true}]}'
)


# --------------------------------------------------------------------------- #
# 1. escalation-subset membership + order (the one functional change)          #
# --------------------------------------------------------------------------- #

def test_step_4k_in_escalation_steps_positioned() -> None:
    # AD-811c: step_4k now runs on the group fan-out path, between 4f and 4g.
    pipe = DmReplyPipeline(_ctx())
    esc_names = [s.__name__ for s in pipe._escalation_steps()]
    assert "step_4k_extract_a2ui" in esc_names
    i = esc_names.index("step_4k_extract_a2ui")
    assert esc_names[i - 1] == "step_4f_extract_artifacts"
    assert esc_names[i + 1] == "step_4g_create_task_parse"


def test_step_4k_still_in_full_steps() -> None:
    # 1:1 path unchanged: step_4k stays registered in _full_steps after 4f.
    pipe = DmReplyPipeline(_ctx())
    full_names = [s.__name__ for s in pipe._full_steps()]
    assert "step_4k_extract_a2ui" in full_names
    i = full_names.index("step_4k_extract_a2ui")
    assert full_names[i - 1] == "step_4f_extract_artifacts"
    assert full_names[i + 1] == "step_4g_create_task_parse"


# --------------------------------------------------------------------------- #
# 2. group escalation path — extraction fires (flag ON)                        #
# --------------------------------------------------------------------------- #

@pytest.mark.asyncio
async def test_group_escalation_extracts_choice_when_enabled(tmp_path) -> None:
    runtime, art, att = _runtime_with_stores(tmp_path, enabled=True)
    text = f"reply [A2UI]{_CHOICE_JSON}[/A2UI] end"
    ctx = _ctx(runtime=runtime, response_text=text, chat_thread_id="t1")
    pipe = DmReplyPipeline(ctx)
    await pipe.run_escalation_only()
    # the stub replaces the raw tag on the GROUP escalation path
    assert "[A2UI: a2ui-choice-1.json v1 - choice]" in ctx.response_text
    assert "[A2UI]" not in ctx.response_text
    assert "[/A2UI]" not in ctx.response_text
    # the artifact + attachment blob were persisted (AD-797 two-call write)
    latest = art.latest(thread_id="t1", name="a2ui-choice-1.json")
    assert latest is not None
    assert latest.mime == "application/json"
    assert await att.exists(latest.content_hash)


@pytest.mark.asyncio
async def test_group_escalation_disabled_byte_identical(tmp_path) -> None:
    runtime, art, _ = _runtime_with_stores(tmp_path, enabled=False)
    text = f"reply [A2UI]{_CHOICE_JSON}[/A2UI] end"
    ctx = _ctx(runtime=runtime, response_text=text, chat_thread_id="t1")
    pipe = DmReplyPipeline(ctx)
    await pipe.run_escalation_only()
    # flag OFF -> group path byte-identical (no stub, no artifact)
    assert ctx.response_text == text
    assert art.latest(thread_id="t1", name="a2ui-choice-1.json") is None


@pytest.mark.asyncio
async def test_group_escalation_no_tag_noop(tmp_path) -> None:
    runtime, art, _ = _runtime_with_stores(tmp_path, enabled=True)
    ctx = _ctx(
        runtime=runtime, response_text="just a normal group reply",
        chat_thread_id="t1",
    )
    pipe = DmReplyPipeline(ctx)
    await pipe.run_escalation_only()
    assert ctx.response_text == "just a normal group reply"
    assert art.latest(thread_id="t1", name="a2ui-choice-1.json") is None


@pytest.mark.asyncio
async def test_group_escalation_no_thread_leaves_intact(tmp_path) -> None:
    # _send_one always sets chat_thread_id, but an empty one must no-op safely.
    runtime, art, _ = _runtime_with_stores(tmp_path, enabled=True)
    text = f"reply [A2UI]{_CHOICE_JSON}[/A2UI] end"
    ctx = _ctx(runtime=runtime, response_text=text, chat_thread_id="")
    pipe = DmReplyPipeline(ctx)
    await pipe.run_escalation_only()
    assert ctx.response_text == text
    assert art.latest(thread_id="", name="a2ui-choice-1.json") is None


# --------------------------------------------------------------------------- #
# 3. kind-genericity — multiselect / form extract on the group path too        #
# --------------------------------------------------------------------------- #

@pytest.mark.asyncio
async def test_group_escalation_multiselect_extracts(tmp_path) -> None:
    runtime, art, _ = _runtime_with_stores(tmp_path, enabled=True)
    text = f"reply [A2UI]{_MS_JSON}[/A2UI] end"
    ctx = _ctx(runtime=runtime, response_text=text, chat_thread_id="t1")
    pipe = DmReplyPipeline(ctx)
    await pipe.run_escalation_only()
    assert "[A2UI: a2ui-multiselect-1.json v1 - multiselect]" in ctx.response_text
    assert "[A2UI]" not in ctx.response_text
    assert art.latest(thread_id="t1", name="a2ui-multiselect-1.json") is not None


@pytest.mark.asyncio
async def test_group_escalation_form_extracts(tmp_path) -> None:
    runtime, art, _ = _runtime_with_stores(tmp_path, enabled=True)
    text = f"reply [A2UI]{_FORM_JSON}[/A2UI] end"
    ctx = _ctx(runtime=runtime, response_text=text, chat_thread_id="t1")
    pipe = DmReplyPipeline(ctx)
    await pipe.run_escalation_only()
    assert "[A2UI: a2ui-form-1.json v1 - form]" in ctx.response_text
    assert "[A2UI]" not in ctx.response_text
    assert art.latest(thread_id="t1", name="a2ui-form-1.json") is not None


# --------------------------------------------------------------------------- #
# 4. honest-degrade — malformed tag on the group path leaves text intact        #
# --------------------------------------------------------------------------- #

@pytest.mark.asyncio
async def test_group_escalation_malformed_json_honest_degrade(tmp_path) -> None:
    runtime, art, _ = _runtime_with_stores(tmp_path, enabled=True)
    text = "reply [A2UI]{not valid json[/A2UI] end"
    ctx = _ctx(runtime=runtime, response_text=text, chat_thread_id="t1")
    pipe = DmReplyPipeline(ctx)
    await pipe.run_escalation_only()  # Tier-2: must not raise
    assert ctx.response_text == text
    assert art.latest(thread_id="t1", name="a2ui-choice-1.json") is None


# --------------------------------------------------------------------------- #
# 5. parity — same tag, same producer through _full_steps (1:1) & escalation    #
# --------------------------------------------------------------------------- #

@pytest.mark.asyncio
async def test_group_and_1to1_parity_same_stub_and_artifact(tmp_path) -> None:
    text = f"reply [A2UI]{_CHOICE_JSON}[/A2UI] end"

    # 1:1 path: the full chain (run -> _full_steps).
    rt_solo, art_solo, _ = _runtime_with_stores(tmp_path / "solo", enabled=True)
    ctx_solo = _ctx(
        runtime=rt_solo, response_text=text, chat_thread_id="t-solo",
    )
    await DmReplyPipeline(ctx_solo).run()

    # group path: the escalation subset (run_escalation_only -> _escalation_steps).
    rt_grp, art_grp, _ = _runtime_with_stores(tmp_path / "grp", enabled=True)
    ctx_grp = _ctx(
        runtime=rt_grp, response_text=text, chat_thread_id="t-grp",
    )
    await DmReplyPipeline(ctx_grp).run_escalation_only()

    # uniform producer: identical stubbed response_text + identical artifact name
    assert ctx_solo.response_text == ctx_grp.response_text
    assert "[A2UI: a2ui-choice-1.json v1 - choice]" in ctx_grp.response_text
    solo_latest = art_solo.latest(thread_id="t-solo", name="a2ui-choice-1.json")
    grp_latest = art_grp.latest(thread_id="t-grp", name="a2ui-choice-1.json")
    assert solo_latest is not None
    assert grp_latest is not None
    assert solo_latest.name == grp_latest.name == "a2ui-choice-1.json"
    assert solo_latest.content_hash == grp_latest.content_hash
