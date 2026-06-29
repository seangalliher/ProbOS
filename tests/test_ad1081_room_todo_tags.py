"""AD-1081: room-Todo tags drive the AD-1080 senior-validation loop.

A senior seeds the plan ([TODOS]), a worker self-reports a step done
([TODO_DONE n] -> submitted), and a senior confirms ([TODO_CONFIRM n] -> done)
or rejects ([TODO_REJECT n: reason] -> rejected). The plan-seed + confirm/reject
are senior-gated; self-report is open to any participant. Default-OFF.

BF-287: real WorkItemStore; a real DmReplyPipeline step over a SimpleNamespace
runtime (work_item_store + chat_thread_store + trust_network + config).
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
import pytest_asyncio

from probos.cognitive.dm.reply_pipeline import DmReplyContext, DmReplyPipeline
from probos.cognitive.dm.todo_extractor import (
    has_todo_tag,
    parse_todo_tags,
    strip_todo_tags,
    derive_prose_plan,
)
from probos.workforce import WorkItemStore


# ---------------- pure parser ----------------


def test_parse_plan_block():
    p = parse_todo_tags("Plan:\n[TODOS]\n- Draft the API\n- Write tests\n[/TODOS]")
    assert p.plan == ["Draft the API", "Write tests"]


def test_parse_done_confirm_reject_are_one_based():
    p = parse_todo_tags("[TODO_DONE 1] [TODO_CONFIRM 2] [TODO_REJECT 3: needs more]")
    assert p.submit == [0]
    assert p.confirm == [1]
    assert p.reject == [(2, "needs more")]


def test_reject_without_reason():
    assert parse_todo_tags("[TODO_REJECT 2]").reject == [(1, "")]


def test_has_todo_tag():
    assert has_todo_tag("[TODO_DONE 1]")
    assert has_todo_tag("[TODOS]x[/TODOS]")
    assert not has_todo_tag("just a normal reply")


def test_empty_plan_block_ignored():
    assert parse_todo_tags("[TODOS]\n[/TODOS]").plan is None


def test_strip_removes_all_tags():
    s = strip_todo_tags("Here is the plan [TODOS]\n- a\n[/TODOS] and [TODO_DONE 1] done.")
    assert "[TODO" not in s
    assert "Here is the plan" in s


# ---------------- pipeline step ----------------


@pytest_asyncio.fixture
async def store(tmp_path: Path):
    s = WorkItemStore(db_path=str(tmp_path / "wis.db"))
    await s.start()
    try:
        yield s
    finally:
        await s.stop()


def _runtime(store, *, trust: float, enabled: bool = True, task_id: str | None = "task-1"):
    return SimpleNamespace(
        work_item_store=store,
        chat_thread_store=SimpleNamespace(
            get_thread=lambda _tid: SimpleNamespace(task_id=task_id),
        ),
        trust_network=SimpleNamespace(get_score=lambda _id: trust),
        config=SimpleNamespace(
            communications=SimpleNamespace(
                room_todos_enabled=enabled, room_todos_min_rank="commander",
                room_todos_seed_min_rank="ensign",
            ),
        ),
    )


def _ctx(runtime, *, response_text: str, agent_id: str = "senior-1"):
    return DmReplyContext(
        runtime=runtime, agent=None, agent_id=agent_id, callsign=None,
        req_message="", response_text=response_text, has_image_attachment=False,
        per_attachment=[], sanity_gate=None, params={}, message_text="",
        sampling_state=None, avatar_event_bus=None, chat_thread_id="room-1",
    )


@pytest.mark.asyncio
async def test_senior_seeds_plan_and_strips_tags(store):
    wi = await store.create_work_item(title="T", work_type="task")
    rt = _runtime(store, trust=0.8, task_id=wi.id)  # 0.8 -> Commander
    ctx = _ctx(rt, response_text="Let's get organized. [TODOS]\n- Draft API\n- Write tests\n[/TODOS]")
    await DmReplyPipeline(ctx).step_4l_extract_todos()
    out = await store.get_work_item(wi.id)
    assert [s["label"] for s in out.steps] == ["Draft API", "Write tests"]
    assert out.metadata.get("steps_gate_completion") is True
    assert "[TODOS]" not in ctx.response_text
    assert "Let's get organized." in ctx.response_text


@pytest.mark.asyncio
async def test_any_crew_can_seed_plan_ad1082(store):
    wi = await store.create_work_item(title="T", work_type="task")
    rt = _runtime(store, trust=0.4, task_id=wi.id)  # ensign
    await DmReplyPipeline(_ctx(rt, response_text="[TODOS]\n- a\n[/TODOS]", agent_id="ensign-1")).step_4l_extract_todos()
    # AD-1082: plan-seed is open (room_todos_seed_min_rank default 'ensign') so
    # the asked agent can write the checklist; only confirm/reject stay gated.
    assert [s["label"] for s in (await store.get_work_item(wi.id)).steps] == ["a"]


@pytest.mark.asyncio
async def test_worker_self_reports_then_senior_confirms(store):
    wi = await store.create_work_item(title="T", work_type="task")
    await store.set_steps(wi.id, ["Draft API"], gate_completion=True)
    # A lieutenant worker reports it done -> submitted (self-report is open).
    rt_worker = _runtime(store, trust=0.6, task_id=wi.id)
    await DmReplyPipeline(_ctx(rt_worker, response_text="Done! [TODO_DONE 1]", agent_id="worker-1")).step_4l_extract_todos()
    s1 = (await store.get_work_item(wi.id)).steps[0]
    assert s1["status"] == "submitted" and s1["submitted_by"] == "worker-1"
    # A senior confirms -> done.
    rt_senior = _runtime(store, trust=0.9, task_id=wi.id)
    await DmReplyPipeline(_ctx(rt_senior, response_text="Confirmed. [TODO_CONFIRM 1]", agent_id="senior-1")).step_4l_extract_todos()
    s2 = (await store.get_work_item(wi.id)).steps[0]
    assert s2["status"] == "done" and s2["confirmed_by"] == "senior-1"


@pytest.mark.asyncio
async def test_non_senior_cannot_confirm(store):
    wi = await store.create_work_item(title="T", work_type="task")
    await store.set_steps(wi.id, [{"label": "x", "status": "submitted"}], gate_completion=True)
    rt = _runtime(store, trust=0.4, task_id=wi.id)  # ensign
    await DmReplyPipeline(_ctx(rt, response_text="[TODO_CONFIRM 1]", agent_id="ensign-1")).step_4l_extract_todos()
    assert (await store.get_work_item(wi.id)).steps[0]["status"] == "submitted"  # unchanged


@pytest.mark.asyncio
async def test_senior_reject_sends_back(store):
    wi = await store.create_work_item(title="T", work_type="task")
    await store.set_steps(wi.id, [{"label": "x", "status": "submitted"}], gate_completion=True)
    rt = _runtime(store, trust=0.9, task_id=wi.id)
    await DmReplyPipeline(_ctx(rt, response_text="[TODO_REJECT 1: missing tests]")).step_4l_extract_todos()
    s = (await store.get_work_item(wi.id)).steps[0]
    assert s["status"] == "rejected" and s["note"] == "missing tests"


@pytest.mark.asyncio
async def test_disabled_is_noop(store):
    wi = await store.create_work_item(title="T", work_type="task")
    rt = _runtime(store, trust=0.9, task_id=wi.id, enabled=False)
    ctx = _ctx(rt, response_text="[TODOS]\n- a\n[/TODOS]")
    await DmReplyPipeline(ctx).step_4l_extract_todos()
    assert (await store.get_work_item(wi.id)).steps == []  # untouched
    assert "[TODOS]" in ctx.response_text  # not stripped (step skipped)


@pytest.mark.asyncio
async def test_no_task_link_strips_only(store):
    rt = _runtime(store, trust=0.9, task_id=None)  # thread carries no task_id
    ctx = _ctx(rt, response_text="hello [TODO_DONE 1] there")
    await DmReplyPipeline(ctx).step_4l_extract_todos()
    assert "[TODO_DONE" not in ctx.response_text  # stripped so it never reaches the transcript
    assert "hello" in ctx.response_text


# ---------------- AD-1082: agents are taught the tags ----------------


def _proto_self(enabled: bool):
    return SimpleNamespace(
        _runtime=SimpleNamespace(
            config=SimpleNamespace(
                communications=SimpleNamespace(room_todos_enabled=enabled),
            ),
        ),
    )


def test_room_todo_protocol_taught_in_group_when_enabled():
    from probos.cognitive.cognitive_agent import CognitiveAgent
    txt = CognitiveAgent._conversational_room_todo_protocol(
        _proto_self(True), {"params": {"is_group_chat": True}}
    )
    assert "[TODOS]" in txt and "[TODO_DONE n]" in txt and "[TODO_CONFIRM n]" in txt


def test_room_todo_protocol_silent_off_or_one_to_one():
    from probos.cognitive.cognitive_agent import CognitiveAgent
    assert CognitiveAgent._conversational_room_todo_protocol(
        _proto_self(False), {"params": {"is_group_chat": True}}
    ) == ""
    assert CognitiveAgent._conversational_room_todo_protocol(
        _proto_self(True), {"params": {"is_group_chat": False}}
    ) == ""


# ---------------- AD-1085a: deterministic prose-plan seeding ----------------


def test_derive_prose_plan_numbered():
    plan = derive_prose_plan("Here's the plan:\n1. Draft AI section\n2. Yeo writes agent\n3. Review")
    assert plan == ["Draft AI section", "Yeo writes agent", "Review"]


def test_derive_prose_plan_single_item_ignored():
    assert derive_prose_plan("Just one thing:\n1. only step") == []


@pytest.mark.asyncio
async def test_prose_plan_seeds_when_no_tag(store):
    wi = await store.create_work_item(title="T", work_type="task")
    rt = _runtime(store, trust=0.9, task_id=wi.id)
    ctx = _ctx(rt, response_text="Plan:\n1. Write AI para\n2. Write agent para\n3. Review")
    await DmReplyPipeline(ctx).step_4l_extract_todos()
    assert [s["label"] for s in (await store.get_work_item(wi.id)).steps] == [
        "Write AI para", "Write agent para", "Review",
    ]


@pytest.mark.asyncio
async def test_prose_plan_does_not_clobber_existing(store):
    wi = await store.create_work_item(title="T", work_type="task")
    await store.set_steps(wi.id, ["keep"], gate_completion=True)
    rt = _runtime(store, trust=0.9, task_id=wi.id)
    await DmReplyPipeline(_ctx(rt, response_text="1. a\n2. b")).step_4l_extract_todos()
    assert [s["label"] for s in (await store.get_work_item(wi.id)).steps] == ["keep"]
