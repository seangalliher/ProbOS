"""AD-1156 A-1 (#1083): plan mode withholds the reply tags that start work.

What is proven here, and where:

* The rule (``plan_mode_governed_turn``): the thread's mode is read before the
  agent runs and again after it answered, and a turn that plan mode touched at
  any point withholds -- including a ``/mode execute`` or ``/mode plan`` that
  lands while the agent is still working.
* The gate (``PlanModeReplyGate``): opened only with agent modes, the
  dm_agentic loop and a thread store, before the agent runs; it reads the
  thread again when first asked, once -- the pipeline asks at its first step
  that could act outside the conversation (A-2); it holds on a store error, on a
  record that no longer parses, and on a thread the route could not resolve.
* Each A-1 tag -- ``[CREATE_TASK]``, ``[DM @callsign]``, ``[CHALLENGE]``,
  ``[ACTION]`` -- against the store, sender, game service or dispatcher it would
  act through, run through the pipeline's runner as ``run()`` runs it, with no
  gate and with an unchanged execute gate as the controls. The kinds A-2 adds
  are in tests/test_ad1156_plan_mode_containment.py.
* The classification (A-2): every step is either allowed in plan mode or held
  back with a notice kind and a pass, and only the runner and the notice step
  read the gate.
* The notice: after the last rewrite and before storage, never read as a
  capability gap, and logged as kinds and counts, never reply text.
* The crossing: ``/mode plan`` through the route, a real ``_decide_via_llm`` turn
  on the same thread store, and the route's reply pipeline over a real work-item
  store and a real proactive loop on a real Ward Room. Nothing is opened or sent
  in plan mode, and both happen after ``/mode execute``.
"""

from __future__ import annotations

import ast
import inspect
import itertools
import logging
import sqlite3
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from probos.cognitive.agent_mode import (
    PLAN_MODE_WITHHELD_REPLY_TAGS,
    PlanModeReplyGate,
    TurnAgentMode,
    open_plan_mode_reply_gate,
    plan_mode_governed_turn,
)
from probos.cognitive.decomposer import is_capability_gap
from probos.cognitive.dm import reply_pipeline as reply_pipeline_module
from probos.cognitive.dm.action_dispatcher import ActionStatus
from probos.cognitive.dm.reply_pipeline import DmReplyContext, DmReplyPipeline
from probos.cognitive.dm.reply_value import DmReply
from probos.cognitive.dm_sanity_gate import DmSanityGate
from probos.config import DmAgenticConfig
from probos.proactive import strip_dm_blocks
from probos.threads import ChatThreadStore
from probos.threads.agent_mode import AgentModeRecord
from probos.types import IntentResult
from probos.ward_room.service import WardRoomService
from probos.workforce import WorkItemStore
from tests.test_ad1156_plan_execute_mode import (
    _Grants,
    _ScriptedLLM,
    _Tool,
    _chat_request,
    _dm_turn,
    _offered,
    _registry,
    _route_runtime,
    _runtime,
    _write_raw_metadata,
)
from tests.test_ad745_pipeline_dispatch import _build_runtime as _action_runtime
from tests.test_bf874_dm_callsign_and_fail_closed import _Rig

_AGENT = "a-ezri"
_TASK = (
    "[CREATE_TASK title=Quarterly report | instructions=Compile the SEC-ALPHA "
    "figures | specialist=@Worf]"
)
_DM = "[DM @Worf] Please pull the SEC-BRAVO figures. [/DM]"
_CHALLENGE = "[CHALLENGE @Worf chess]"
_ACTION = '[ACTION: {"verb":"screenshot","args":{}}]'


def _notice(held: str) -> str:
    return (
        f"(Plan mode held back {held}; none of it was sent, saved or started. "
        "Once this conversation is in execute mode, ask again.)"
    )


_NOTICE_TASK_AND_DM = _notice("a new task and a message to a crewmate")


# ── fixtures and fakes ──────────────────────────────────────────────────────


@pytest.fixture
def store(tmp_path: Path) -> ChatThreadStore:
    ticks = itertools.count(1_000)
    return ChatThreadStore(tmp_path / "threads.db", clock=lambda: float(next(ticks)))


@pytest.fixture
async def work_items() -> Any:
    items = WorkItemStore(db_path=":memory:")
    await items.start()
    yield items
    await items.stop()


def _modes_runtime(*, modes: bool = True, loop: bool = True) -> Any:
    return SimpleNamespace(config=SimpleNamespace(
        dm_agentic=DmAgenticConfig(enabled=loop, agent_modes_enabled=modes),
    ))


class _CountingStore:
    """The gate's one store method, counted, and able to fail."""

    def __init__(self, inner: ChatThreadStore) -> None:
        self._inner = inner
        self.reads = 0
        self.fail = False

    def get_thread(self, thread_id: str) -> Any:
        self.reads += 1
        if self.fail:
            raise RuntimeError("thread store unavailable")
        return self._inner.get_thread(thread_id)


class _NullStore:
    def get_thread(self, thread_id: str) -> Any:
        raise AssertionError("this gate must not read the thread")


def _thread(store: ChatThreadStore, mode: str | None) -> Any:
    thread = store.get_or_create_default_for_agent(_AGENT, "Ezri")
    if mode is not None:
        store.set_agent_mode(thread.id, mode, changed_by="captain")
    return thread


def _open(store: Any, thread: Any) -> PlanModeReplyGate:
    gate = open_plan_mode_reply_gate(_modes_runtime(), store, thread, agent_id=_AGENT)
    assert gate is not None
    return gate


def _gate(store: ChatThreadStore, mode: str) -> PlanModeReplyGate:
    """A real gate, opened on a real thread whose record is ``mode``."""
    return _open(store, _thread(store, mode))


def _ctx(
    text: str,
    *,
    runtime: Any,
    gate: PlanModeReplyGate | None,
    sanity_gate: Any = None,
    **fields: Any,
) -> DmReplyContext:
    return DmReplyContext(
        runtime=runtime,
        agent=SimpleNamespace(id=_AGENT, agent_type="counselor", callsign="Ezri"),
        agent_id=_AGENT,
        callsign="Ezri",
        req_message="Plan the report.",
        reply=DmReply(body=text),
        has_image_attachment=False,
        per_attachment=[],
        sanity_gate=sanity_gate,
        params={"thread_id": "t-1", "dm_turn_id": "turn-1"},
        message_text="Plan the report.",
        sampling_state=None,
        avatar_event_bus=None,
        chat_thread_id="t-1",
        plan_mode_gate=gate,
        **fields,
    )


def _turn(mode: str, revision: int, previous: str | None) -> TurnAgentMode:
    # A-8: a record names the agent it was set for; every record here is the same agent's.
    return TurnAgentMode(mode=mode, record=AgentModeRecord(mode, revision, 100.0, "captain", previous, _AGENT))


_E1 = _turn("execute", 1, None)
_E2 = _turn("execute", 2, "plan")
_E3 = _turn("execute", 3, "plan")
_P1 = _turn("plan", 1, None)
_P2 = _turn("plan", 2, "execute")
_HELD = TurnAgentMode(mode="plan", record=None)
# A held turn counts however it is labelled: ``record is None`` IS "held".
_HELD_ODD = TurnAgentMode(mode="execute", record=None)
# A plan label counts whatever record it carries: plan mode only withholds.
_PLAN_ON_E1 = TurnAgentMode(mode="plan", record=_E1.record)


# ── 1. the rule ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("at_dispatch", "at_reply", "governed"),
    [
        (None, None, False),
        (None, _E1, False),
        (_E1, _E1, False),
        (_E3, _turn("execute", 3, "plan"), False),
        (None, _P1, True),
        (None, _E2, True),
        (None, _E3, True),
        (_E1, _E3, True),
        (_E1, _P2, True),
        (_P1, _E2, True),
        (_P1, _P1, True),
        (_HELD, None, True),
        (None, _HELD, True),
        (_E1, _HELD, True),
        (_HELD, _E1, True),
        (None, _HELD_ODD, True),
        (_HELD_ODD, _HELD_ODD, True),
        (_PLAN_ON_E1, _E1, True),
        (_E1, None, True),
        (_P1, None, True),
    ],
    ids=[
        "no-record", "first-execute-record", "same-execute-record",
        "equal-but-distinct-records", "plan-set-during", "plan-came-and-went",
        "plan-came-and-went-twice", "execute-changed", "plan-during-execute",
        "execute-during-plan", "plan-both", "held-then-gone", "held-at-reply",
        "execute-then-held", "held-then-execute", "held-labelled-execute",
        "held-labelled-execute-at-both", "plan-label-on-an-execute-record",
        "execute-record-vanished", "plan-record-vanished",
    ],
)
def test_plan_mode_governed_turn(
    at_dispatch: TurnAgentMode | None, at_reply: TurnAgentMode | None, governed: bool,
) -> None:
    assert plan_mode_governed_turn(at_dispatch, at_reply) is governed


# ── 2. the gate ─────────────────────────────────────────────────────────────


def test_the_gate_reads_before_the_agent_and_once_more_only_when_asked(
    store: ChatThreadStore,
) -> None:
    counting = _CountingStore(store)
    gate = _open(counting, _thread(store, "execute"))

    assert counting.reads == 1, "the first read happens when the route opens the gate"
    assert gate.notice() == "" and counting.reads == 1
    assert gate.withholds() is False
    assert gate.withholds() is False
    assert counting.reads == 2, "the reply-time read happens once and is kept"


@pytest.mark.parametrize(("before", "during"), [("plan", "execute"), ("execute", "plan")])
def test_a_mode_change_while_the_agent_works_is_withheld(
    store: ChatThreadStore, before: str, during: str,
) -> None:
    thread = _thread(store, before)
    gate = _open(store, thread)
    store.set_agent_mode(thread.id, during, changed_by="captain")

    assert gate.withholds() is True


def test_plan_mode_that_came_and_went_while_the_agent_worked_is_withheld(
    store: ChatThreadStore,
) -> None:
    thread = _thread(store, "execute")
    gate = _open(store, thread)
    store.set_agent_mode(thread.id, "plan", changed_by="captain")
    store.set_agent_mode(thread.id, "execute", changed_by="captain")

    assert store.get_thread(thread.id).metadata["agent_mode"]["mode"] == "execute"
    assert gate.withholds() is True


def test_an_unchanged_execute_record_withholds_nothing(store: ChatThreadStore) -> None:
    gate = _gate(store, "execute")

    assert gate.withholds() is False
    assert (gate.notice(), gate.summary()) == ("", "")


def test_the_gate_holds_when_the_reply_time_read_fails(
    store: ChatThreadStore, caplog: pytest.LogCaptureFixture,
) -> None:
    counting = _CountingStore(store)
    gate = _open(counting, _thread(store, "execute"))
    counting.fail = True

    with caplog.at_level(logging.WARNING, logger="probos.cognitive.agent_mode"):
        assert gate.withholds() is True
    assert "held in plan mode" in caplog.text


def test_the_gate_holds_for_a_record_that_no_longer_parses(store: ChatThreadStore) -> None:
    thread = _thread(store, "execute")
    gate = _open(store, thread)
    _write_raw_metadata(store, thread.id, {"agent_mode": {"mode": "execute"}})

    assert gate.withholds() is True


@pytest.mark.parametrize(
    ("case", "outcome"),
    [
        ("all-on", "reads"),
        ("modes-off", "none"),
        ("loop-off", "none"),
        ("mock-config", "none"),
        ("no-store", "none"),
        ("unresolved-thread", "held"),
        ("thread-id-not-a-str", "held"),
    ],
)
def test_the_gate_opens_only_with_modes_the_loop_and_a_store(
    store: ChatThreadStore, case: str, outcome: str, caplog: pytest.LogCaptureFixture,
) -> None:
    # An unchanged execute record, so only a held gate withholds.
    thread = _thread(store, "execute")
    counting = _CountingStore(store)
    runtime, reader, target = _modes_runtime(), counting, thread
    if case == "modes-off":
        runtime = _modes_runtime(modes=False)
    elif case == "loop-off":
        runtime = _modes_runtime(loop=False)
    elif case == "mock-config":
        runtime = MagicMock()
    elif case == "no-store":
        reader = None
    elif case == "unresolved-thread":
        target = None
    elif case == "thread-id-not-a-str":
        target = MagicMock()

    with caplog.at_level(logging.WARNING, logger="probos.cognitive.agent_mode"):
        gate = open_plan_mode_reply_gate(runtime, reader, target, agent_id=_AGENT)

    if outcome == "none":
        assert gate is None and counting.reads == 0
    elif outcome == "reads":
        assert gate is not None and counting.reads == 1
        assert gate.withholds() is False
    else:
        # With a store present, a thread the route could not resolve means the
        # store raised: the mode cannot be confirmed, so the reply is held.
        assert gate is not None and counting.reads == 0
        assert gate.withholds() is True and counting.reads == 0
        assert "could not be resolved" in caplog.text


# ── 3. the notice ───────────────────────────────────────────────────────────


def test_the_notice_names_what_was_held_back_in_a_fixed_order() -> None:
    gate = PlanModeReplyGate(_NullStore(), "t-1", None, agent_id=_AGENT)
    assert (gate.notice(), gate.summary()) == ("", "")

    gate.record("dm", 2)
    gate.record("create_task")

    assert gate.notice() == _notice("a new task and 2 messages to crewmates")
    assert gate.summary() == "create_task=1 dm=2"

    gate.record("action")
    gate.record("challenge")

    assert gate.notice() == _notice(
        "a new task, 2 messages to crewmates, a game challenge and a browser action"
    )


def test_no_notice_reads_as_a_capability_gap() -> None:
    kinds = list(PLAN_MODE_WITHHELD_REPLY_TAGS)
    seen = 0
    for size in range(1, len(kinds) + 1):
        for subset in itertools.combinations(kinds, size):
            for count in (1, 3):
                gate = PlanModeReplyGate(_NullStore(), "t-1", None, agent_id=_AGENT)
                for kind in subset:
                    gate.record(kind, count)
                notice = gate.notice()
                assert notice and not is_capability_gap(notice), notice
                seen += 1

    # A-2: nine kinds now (A-1's four and five more), each non-empty subset at two counts.
    assert len(kinds) == 9 and seen == (2 ** 9 - 1) * 2


# ── 4. which steps consult plan mode ────────────────────────────────────────


def test_every_reply_step_is_classified_for_plan_mode() -> None:
    """A-2 (review F1) replaces the A-1 census of four consult sites, which read
    every other channel's omission as the contract -- a notebook entry was saved
    and a follow-up scheduled in plan mode. Every step is now allowed in plan mode,
    held back with a notice kind and a pass, or (A-3) replaced by a quiet pass,
    and in exactly one of them. A new step fails here until it is classified;
    until then the runner does not run it in plan mode."""
    allowed = reply_pipeline_module._PLAN_MODE_ALLOWED_STEPS
    withheld = reply_pipeline_module._PLAN_MODE_WITHHELD_STEPS
    quiet = reply_pipeline_module._PLAN_MODE_QUIET_STEPS
    steps = {
        name for name, _ in inspect.getmembers(DmReplyPipeline, inspect.iscoroutinefunction)
        if name.startswith("step_")
    }
    pipeline = DmReplyPipeline(_ctx("x", runtime=SimpleNamespace(), gate=None))

    assert allowed.isdisjoint(withheld) and allowed.isdisjoint(quiet) and set(quiet).isdisjoint(withheld)
    assert allowed | set(withheld) | set(quiet) == steps == {s.__name__ for s in pipeline._full_steps()}
    assert {s.__name__ for s in pipeline._escalation_steps()} <= steps
    # A-3 (review H3; was: fifteen allowed, steps 7 and 9 among them): the
    # divergence check writes trust, Hebbian weights and the divergence record,
    # which the ship and other agents act on, and the emotion step reads that
    # check's result, so both are replaced by passes that are not announced.
    assert allowed == {
        "step_1_sanity_gate_retry", "step_4_self_check_parse", "step_4h_mesh_read_parse",
        "step_4f_extract_artifacts", "step_4k_extract_a2ui", "step_4j_deliberate_parse",
        "step_4n_tool_write_ledger", "step_4m_write_claim_guard", "step_4o_owned_steps_feedback",
        "step_4p_plan_mode_notice", "step_5_episodic_store", "step_6_working_memory_record",
        "step_8_mark_emitted",
    }
    assert set(quiet) == {"step_7_divergence_check", "step_9_emotion_resolve"}
    assert sorted(kind for kind, _ in withheld.values()) == sorted(PLAN_MODE_WITHHELD_REPLY_TAGS)
    functions = [
        node for node in ast.walk(ast.parse(inspect.getsource(reply_pipeline_module)))
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]

    def _touching(attr: str) -> set[str]:
        return {
            node.name for node in functions
            if any(isinstance(sub, ast.Attribute) and sub.attr == attr for sub in ast.walk(node))
        }

    # A-3 (the review's Low and H1; was: the runner's helper and the notice step):
    # the runner reads the gate once per reply and hands it to its helper, so a
    # reply without one is never checked, and the retry reads only whether one
    # exists, to ask on this conversation's thread. A-4 (round-3 review, H and M;
    # was: those three): step 5 asks it whether to mark the episode and store the
    # reply as plan mode left it, and ``run_plan_mode_text`` asks it before running
    # the passes and the notice for a reply that bypasses the pipeline.
    assert _touching("plan_mode_gate") == {
        "_run_steps", "step_1_sanity_gate_retry", "step_4p_plan_mode_notice",
        "step_5_episodic_store", "run_plan_mode_text",
    }
    # A-3 (review H2): only the three passes that keep what they take out, and the
    # notice step that shows it, touch the held text.
    assert _touching("plan_mode_shown") == {
        "_withhold_dm", "_withhold_notebook", "_withhold_todos", "step_4p_plan_mode_notice",
    }


def test_the_notice_step_follows_the_last_rewrite_and_precedes_storage() -> None:
    pipeline = DmReplyPipeline(_ctx("x", runtime=SimpleNamespace(), gate=None))
    names = [step.__name__ for step in pipeline._full_steps()]
    at = names.index("step_4p_plan_mode_notice")

    assert names[at - 1] == "step_4o_owned_steps_feedback"
    assert names[at + 1] == "step_5_episodic_store"
    assert names.index("step_4j_deliberate_parse") < at
    assert "step_4p_plan_mode_notice" not in [s.__name__ for s in pipeline._escalation_steps()]


# ── 5. each withheld tag, with the unchanged paths as controls ──────────────


async def _create_task_reply(work_items: WorkItemStore, gate: PlanModeReplyGate | None) -> tuple[str, list[str]]:
    ctx = _ctx(
        f"Plan follows. {_TASK}",
        runtime=SimpleNamespace(work_item_store=work_items, callsign_registry=None),
        gate=gate,
        sanity_gate=DmSanityGate(),
    )
    pipeline = DmReplyPipeline(ctx)
    # A-2: the runner, not the step, holds a step back, so run it as run() does.
    await pipeline._run_steps((pipeline.step_4g_create_task_parse, pipeline.step_4p_plan_mode_notice))
    return ctx.response_text, [item.title for item in await work_items.list_work_items()]


async def test_plan_mode_opens_no_task_and_says_so(
    store: ChatThreadStore, work_items: WorkItemStore,
) -> None:
    text, titles = await _create_task_reply(work_items, _gate(store, "plan"))

    assert titles == []
    assert text == "Plan follows.\n\n" + _notice("a new task")


@pytest.mark.parametrize("mode", ["no-gate", "execute"])
async def test_outside_plan_mode_the_task_opens_as_before(
    store: ChatThreadStore, work_items: WorkItemStore, mode: str,
) -> None:
    gate = None if mode == "no-gate" else _gate(store, "execute")

    text, titles = await _create_task_reply(work_items, gate)

    assert titles == ["Quarterly report"]
    item = (await work_items.list_work_items())[0]
    assert text == f"Plan follows.\n\n(Task opened: {item.id})"


class _Sender:
    """The DM step's one call, recorded. Like the real sender it removes the
    blocks it can read and leaves a text with none of them as it was (BF-874)."""

    def __init__(self) -> None:
        self.sent: list[str] = []

    async def extract_and_execute_dms(self, agent: Any, text: str) -> tuple[str, list[dict[str, str]]]:
        self.sent.append(text)
        stripped = strip_dm_blocks(text)
        if not stripped.readable:
            return text, []
        return stripped.text, [{"type": "dm"}]


async def _dm_reply(gate: PlanModeReplyGate | None, text: str) -> tuple[str, list[str]]:
    sender = _Sender()
    ctx = _ctx(text, runtime=SimpleNamespace(proactive_loop=sender), gate=gate)
    pipeline = DmReplyPipeline(ctx)
    # A-2: the runner, not the step, holds a step back, so run it as run() does.
    await pipeline._run_steps((pipeline.step_4b_dm_outbound_parse, pipeline.step_4p_plan_mode_notice))
    return ctx.response_text, sender.sent


async def test_plan_mode_sends_no_dm_and_leaves_the_block_for_the_captain(
    store: ChatThreadStore,
) -> None:
    text, sent = await _dm_reply(_gate(store, "plan"), f"Here is the plan. {_DM} {_DM}")

    assert sent == []
    # A-3 (review H2; was: the blocks stayed where the agent wrote them): the pass
    # takes the blocks out, as the DM step does, so no later step acts on what is
    # inside them, and the notice step shows them to the Captain before the notice.
    assert text == f"Here is the plan.\n\n{_DM}\n\n{_DM}\n\n" + _notice("2 messages to crewmates")


@pytest.mark.parametrize("mode", ["no-gate", "execute"])
async def test_outside_plan_mode_the_dm_is_sent_as_before(
    store: ChatThreadStore, mode: str,
) -> None:
    gate = None if mode == "no-gate" else _gate(store, "execute")

    text, sent = await _dm_reply(gate, f"Here is the plan. {_DM}")

    assert (text, sent) == ("Here is the plan.", [f"Here is the plan. {_DM}"])


async def test_a_dm_block_the_step_cannot_read_is_not_reported_as_withheld(
    store: ChatThreadStore,
) -> None:
    counting = _CountingStore(store)
    gate = _open(counting, _thread(store, "plan"))
    unreadable = "On it. [DM@Troi] SEC-CHARLIE [/DM] Done."

    text, sent = await _dm_reply(gate, unreadable)

    # A-2 (was: the sender is called and reads nothing sendable; one read): plan
    # mode now holds the DM step itself, so the sender is not called. The block
    # stays visible, as BF-874 keeps it without a gate, and is not reported. The
    # runner asks the gate once, at the first step it could hold back.
    assert sent == [] and text == unreadable
    assert counting.reads == 2


class _Recreation:
    def __init__(self) -> None:
        self.games: list[dict[str, Any]] = []

    async def create_game(self, **kwargs: Any) -> dict[str, Any]:
        self.games.append(kwargs)
        return {"game_id": f"game-{len(self.games)}"}


async def _challenge_reply(gate: PlanModeReplyGate | None) -> tuple[str, list[dict[str, Any]]]:
    games = _Recreation()
    runtime = SimpleNamespace(
        recreation_service=games,
        ward_room=None,
        callsign_registry=SimpleNamespace(resolve=lambda callsign: {"agent_id": "worf"}),
    )
    ctx = _ctx(f"Fancy a game? {_CHALLENGE}", runtime=runtime, gate=gate, sanity_gate=DmSanityGate())
    pipeline = DmReplyPipeline(ctx)
    # A-2: the runner, not the step, holds a step back, so run it as run() does.
    await pipeline._run_steps((pipeline.step_2_challenge_parse, pipeline.step_4p_plan_mode_notice))
    return ctx.response_text, games.games


async def test_plan_mode_issues_no_challenge(store: ChatThreadStore) -> None:
    text, games = await _challenge_reply(_gate(store, "plan"))

    assert games == []
    assert "[CHALLENGE" not in text
    assert text.startswith("Fancy a game?") and text.endswith(_notice("a game challenge"))


@pytest.mark.parametrize("mode", ["no-gate", "execute"])
async def test_outside_plan_mode_the_challenge_is_issued_as_before(
    store: ChatThreadStore, mode: str,
) -> None:
    gate = None if mode == "no-gate" else _gate(store, "execute")

    text, games = await _challenge_reply(gate)

    assert [(g["challenger"], g["opponent"], g["game_type"]) for g in games] == [("Ezri", "Worf", "chess")]
    assert "[CHALLENGE" not in text and "Plan mode held back" not in text


async def _action_reply(gate: PlanModeReplyGate | None) -> tuple[str, Any]:
    runtime = _action_runtime()
    ctx = _ctx(f"Looking now. {_ACTION}", runtime=runtime, gate=gate)
    pipeline = DmReplyPipeline(ctx)
    # A-2: the runner, not the step, holds a step back, so run it as run() does.
    await pipeline._run_steps((pipeline.step_4e_action_dispatch, pipeline.step_4p_plan_mode_notice))
    return ctx.response_text, runtime


async def test_plan_mode_queues_and_runs_no_browser_action(store: ChatThreadStore) -> None:
    text, runtime = await _action_reply(_gate(store, "plan"))

    assert runtime.action_dispatcher.list_for_thread("t-1") == []
    assert runtime.browser_tool.invoked == [] and runtime.episodic_memory.stored == []
    assert "[ACTION" not in text
    assert text == "Looking now.\n\n" + _notice("a browser action")


@pytest.mark.parametrize("mode", ["no-gate", "execute"])
async def test_outside_plan_mode_the_action_runs_as_before(
    store: ChatThreadStore, mode: str,
) -> None:
    gate = None if mode == "no-gate" else _gate(store, "execute")

    text, runtime = await _action_reply(gate)

    actions = runtime.action_dispatcher.list_for_thread("t-1")
    assert [(a.verb, a.status) for a in actions] == [("screenshot", ActionStatus.EXECUTED)]
    assert len(runtime.browser_tool.invoked) == 1
    assert "[ACTION" not in text and "Plan mode held back" not in text


async def test_a_reply_without_a_held_request_is_untouched_and_unannounced(
    store: ChatThreadStore, work_items: WorkItemStore, caplog: pytest.LogCaptureFixture,
) -> None:
    counting = _CountingStore(store)
    gate = _open(counting, _thread(store, "plan"))
    runtime = SimpleNamespace(
        work_item_store=work_items, proactive_loop=_Sender(),
        recreation_service=_Recreation(), ward_room=None, callsign_registry=None,
    )
    ctx = _ctx("A plan, and no tags.", runtime=runtime, gate=gate, sanity_gate=DmSanityGate())
    pipeline = DmReplyPipeline(ctx)

    with caplog.at_level(logging.INFO, logger="probos.cognitive.dm.reply_pipeline"):
        await pipeline._run_steps((
            pipeline.step_2_challenge_parse, pipeline.step_4e_action_dispatch,
            pipeline.step_4b_dm_outbound_parse, pipeline.step_4g_create_task_parse,
            pipeline.step_4p_plan_mode_notice,
        ))

    assert ctx.response_text == "A plan, and no tags."
    # A-2 (was 1, and the test was named "read once"): the runner asks the gate at
    # the first step it could hold back, whatever the reply carries, so a gated
    # reply reads the thread once more.
    assert counting.reads == 2
    assert "AD-1156" not in caplog.text


async def test_the_notice_follows_owned_step_feedback_once(
    store: ChatThreadStore, work_items: WorkItemStore,
) -> None:
    ctx = _ctx(
        f"Plan follows. {_TASK}",
        runtime=SimpleNamespace(work_item_store=work_items, callsign_registry=None),
        gate=_gate(store, "plan"),
        sanity_gate=DmSanityGate(),
        owned_steps_feedback="(Step 2 was not adopted.)",
    )
    pipeline = DmReplyPipeline(ctx)

    # A-2: through the runner, which holds the create-task step back.
    await pipeline._run_steps((
        pipeline.step_4g_create_task_parse, pipeline.step_4o_owned_steps_feedback,
        pipeline.step_4p_plan_mode_notice, pipeline.step_4p_plan_mode_notice,
    ))

    assert ctx.response_text == (
        "Plan follows.\n\n(Step 2 was not adopted.)\n\n" + _notice("a new task")
    )


async def test_the_log_names_kinds_and_counts_never_the_reply(
    store: ChatThreadStore, work_items: WorkItemStore, caplog: pytest.LogCaptureFixture,
) -> None:
    runtime = SimpleNamespace(
        work_item_store=work_items, callsign_registry=None, proactive_loop=_Sender(),
    )
    ctx = _ctx(
        f"Plan. {_TASK} {_DM}", runtime=runtime, gate=_gate(store, "plan"),
        sanity_gate=DmSanityGate(),
    )
    pipeline = DmReplyPipeline(ctx)

    with caplog.at_level(logging.DEBUG):
        await pipeline._run_steps((
            pipeline.step_4b_dm_outbound_parse, pipeline.step_4g_create_task_parse,
            pipeline.step_4p_plan_mode_notice,
        ))

    ours = [r.getMessage() for r in caplog.records if "AD-1156" in r.getMessage()]
    # A-2: through the runner; "saved" joins the summary now notebook entries are held.
    assert ours == [
        "AD-1156: plan mode held back create_task=1 dm=1 from agent a-ezri's reply "
        "on thread t-1; none of it was sent, saved or started"
    ]
    for secret in ("SEC-ALPHA", "SEC-BRAVO", "Quarterly", "Worf"):
        assert secret not in caplog.text


# ── 6. the crossing: route -> agent turn -> reply pipeline -> real stores ───


@pytest.fixture
async def ward_room(tmp_path: Path) -> Any:
    rig = _Rig(WardRoomService(db_path=str(tmp_path / "wr.db")), dm_min_rank="ensign", aboard=None)
    await rig.start()
    yield rig
    await rig.ws.stop()


class _Vessel:
    """The one-to-one route over a real thread store, a real work-item store and a
    real proactive loop on a real Ward Room, with the agent's real DM turn
    (``_decide_via_llm``, on the same thread store) behind the intent bus."""

    def __init__(self, tmp_path: Path, ward_room: Any, work_items: WorkItemStore, *, modes: bool = True) -> None:
        self.rt = _route_runtime(tmp_path, modes=modes)
        self.rt.config.dm_agentic = DmAgenticConfig(
            enabled=True, max_iterations=4, agent_modes_enabled=modes,
        )
        crewmate = ward_room.agents["Troi"]
        agent = self.rt.registry.get.return_value
        agent.id, agent.agent_type, agent.callsign = crewmate.id, crewmate.agent_type, "Troi"
        self.rt.callsign_registry.resolve.return_value = None
        self.rt.proactive_loop = ward_room.loop
        self.rt.work_item_store = work_items
        self.store: ChatThreadStore = self.rt.chat_thread_store
        self.thread = self.store.get_or_create_default_for_agent("test-agent", "Ezri")
        self.writer = _Tool("file_writer")
        self.agent_rt = _runtime(
            _registry(_Tool("http_fetch"), self.writer), _Grants(["http_fetch", "file_writer"]),
            cfg=self.rt.config.dm_agentic, store=self.store,
        )
        self.llms: list[_ScriptedLLM] = []
        self.during_turn: Callable[[], Any] | None = None
        self.rt.intent_bus.send = AsyncMock(side_effect=self._send)

    async def _send(self, intent: Any, **_kwargs: Any) -> IntentResult:
        # A-9: the turn is the admitted agent's, whose record the route's thread stores.
        decision = await _dm_turn(
            self.agent_rt, self.llms[-1], intent.thread_id, intent.params["text"], agent_id="test-agent",
        )
        if self.during_turn is not None:
            self.during_turn()
        return IntentResult(
            intent_id=intent.id, agent_id="test-agent", success=True, result=decision["llm_output"],
        )

    async def say(self, message: str, *steps: Any) -> dict[str, Any]:
        from probos.routers.agents import agent_chat

        if steps:
            self.llms.append(_ScriptedLLM(list(steps)))
            # The repetition check compares a reply with the agent's previous one,
            # and these tests send the same tags twice on purpose.
            self.rt.dm_sanity_gate = DmSanityGate()
        with patch("probos.routers.agents.is_crew_agent", return_value=True):
            return await agent_chat("test-agent", _chat_request(message), self.rt)


_PLAN_REPLY = f"Here is the plan: 1. compile the figures, 2. brief Worf.\n{_TASK}\n{_DM}"
_EXECUTE_REPLY = f"Carrying it out now.\n{_TASK}\n{_DM}"


async def test_seam_plan_mode_opens_and_sends_nothing_and_execute_mode_does_both(
    tmp_path: Path, ward_room: Any, work_items: WorkItemStore,
) -> None:
    vessel = _Vessel(tmp_path, ward_room, work_items)

    await vessel.say("/mode plan")
    planned = await vessel.say(
        "Get the quarterly report moving.",
        ("file_writer", {"target": "report.md"}),
        _PLAN_REPLY,
    )

    # The agent ran in plan mode, and ignored its instructions in the reply.
    assert _offered(vessel.llms[-1].requests[0]) == ["http_fetch"]
    assert vessel.writer.calls == []
    # Nothing was opened or sent, and the Captain is told so.
    assert await work_items.list_work_items() == []
    assert await ward_room.dm_titles() == []
    body = planned["response"]
    assert "[CREATE_TASK" not in body and "(Task opened" not in body
    assert _DM in body, "an unsent DM block stays visible to the Captain (BF-874)"
    assert body.endswith(_NOTICE_TASK_AND_DM)
    transcript = [m.body for m in vessel.store.list_messages(vessel.thread.id) if m.role == "agent"]
    assert transcript[-1].endswith(_NOTICE_TASK_AND_DM)
    episode = vessel.rt.episodic_memory.store.await_args.args[0]
    assert episode.outcomes[0]["response"].endswith(_NOTICE_TASK_AND_DM)

    await vessel.say("/mode execute")
    executed = await vessel.say("Go ahead.", _EXECUTE_REPLY)

    assert "approving the plan drafted in plan mode" in vessel.llms[-1].requests[0].system_prompt
    assert [item.title for item in await work_items.list_work_items()] == ["Quarterly report"]
    assert await ward_room.dm_titles() == ["[DM to @Worf]"]
    assert "(Task opened: " in executed["response"]
    assert "Plan mode held back" not in executed["response"] and _DM not in executed["response"]


@pytest.mark.parametrize(("before", "during"), [("plan", "execute"), ("execute", "plan")])
async def test_seam_a_mode_change_while_the_agent_works_withholds_its_tags(
    tmp_path: Path, ward_room: Any, work_items: WorkItemStore, before: str, during: str,
) -> None:
    vessel = _Vessel(tmp_path, ward_room, work_items)
    await vessel.say(f"/mode {before}")
    vessel.during_turn = lambda: vessel.store.set_agent_mode(
        vessel.thread.id, during, changed_by="captain",
    )

    reply = await vessel.say("Get the quarterly report moving.", _EXECUTE_REPLY)

    assert vessel.store.get_thread(vessel.thread.id).metadata["agent_mode"]["mode"] == during
    assert await work_items.list_work_items() == []
    assert await ward_room.dm_titles() == []
    assert reply["response"].endswith(_NOTICE_TASK_AND_DM)


async def test_seam_with_modes_off_a_stored_plan_record_is_inert(
    tmp_path: Path, ward_room: Any, work_items: WorkItemStore,
) -> None:
    vessel = _Vessel(tmp_path, ward_room, work_items, modes=False)
    vessel.store.set_agent_mode(vessel.thread.id, "plan", changed_by="captain")

    reply = await vessel.say("Get the quarterly report moving.", _EXECUTE_REPLY)

    assert [item.title for item in await work_items.list_work_items()] == ["Quarterly report"]
    assert await ward_room.dm_titles() == ["[DM to @Worf]"]
    assert "Plan mode held back" not in reply["response"]


async def test_seam_a_thread_the_route_cannot_resolve_holds_the_reply(
    tmp_path: Path, ward_room: Any, work_items: WorkItemStore,
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
) -> None:
    vessel = _Vessel(tmp_path, ward_room, work_items)
    real = vessel.store.get_or_create_default_for_agent
    calls: list[str] = []

    def _locked_once(agent_id: str, title: str) -> Any:
        calls.append(agent_id)
        if len(calls) == 1:
            raise sqlite3.OperationalError("database is locked")
        return real(agent_id, title)

    monkeypatch.setattr(vessel.store, "get_or_create_default_for_agent", _locked_once)

    with caplog.at_level(logging.WARNING):
        reply = await vessel.say("Get the quarterly report moving.", _EXECUTE_REPLY)

    # Premise: the route's own resolution is the call that failed.
    assert calls[0] == "test-agent"
    assert "chat-thread resolve failed" in caplog.text
    assert "could not be resolved" in caplog.text
    assert await work_items.list_work_items() == []
    assert await ward_room.dm_titles() == []
    assert reply["response"].endswith(_NOTICE_TASK_AND_DM)
