"""AD-1156 A-2 (#1083): a plan-mode reply is held to its conversation.

The review of A-1 found three defects. F1: A-1 withheld four reply tags and left
every other channel a plan-mode reply reaches -- a notebook entry was saved and a
follow-up scheduled. A-2 decides it in the pipeline's runner instead: when the
gate withholds, only the steps in ``_PLAN_MODE_ALLOWED_STEPS`` run, each other
step is replaced by its withhold pass, and a step neither table names does not
run. F2: a metadata column that does not decode to an object read as "no mode"
and restored every tool; it now holds the turn. F3: the executor guard's log line
carried the model's tool id.

What is proven here (the step census is in tests/test_ad1156_plan_mode_reply_tags.py):

* The crossing: one reply carrying every withheld request, through ``run()``,
  against recording channels and real stores. In plan mode nothing acts, the
  notice names all nine kinds, and the conversation's own artifact is still
  filed; with no gate and with an execute gate each channel acts once.
* Each kind A-2 adds -- move, image, follow-up, notebook, room todos -- against
  its channel, with no gate and an execute gate as the controls. The notebook
  and follow-up cases are the review's reproductions. A request its step would
  not read (a channel off or absent) is left exactly as that step leaves it, and
  not reported; the plan instructions name the notebook and follow-up channels.
* The runner: a step neither table names does not run in plan mode, and the
  thread is read again only at a step plan mode could hold back.
* A metadata column that does not decode to an object: the store marks it
  without serializing the mark, the mode reader holds, a real
  ``_decide_via_llm`` turn is offered read-only tools only, ``/mode`` reports the
  hold, the reply gate withholds, and ``/mode execute`` repairs it.
* The executor guard logs a category, the agent and the id's length, never the id.
"""

from __future__ import annotations

import itertools
import logging
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest

from probos import proactive as proactive_module
from probos.artifacts import ArtifactStore
from probos.cognitive.agent_mode import open_plan_mode_reply_gate, read_turn_agent_mode
from probos.cognitive.agentic_dispatch import DispatchToolExecutor
from probos.cognitive.dm.reply_pipeline import DmReplyContext, DmReplyPipeline
from probos.cognitive.dm.reply_value import DmReply
from probos.cognitive.dm_sanity_gate import DmSanityGate
from probos.config import DmAgenticConfig
from probos.threads import ChatThreadStore
from probos.workforce import WorkItemStore
from tests.test_ad1156_plan_execute_mode import (
    _AGENT as _MODE_AGENT,
    _Grants,
    _ScriptedLLM,
    _Tool,
    _command,
    _dm_turn,
    _offered,
    _registry,
    _runtime,
)
from tests.test_ad745_pipeline_dispatch import _build_runtime as _action_runtime

_AGENT = "a-ezri"


def _notice(held: str) -> str:
    return (
        f"(Plan mode held back {held}; none of it was sent, saved or started. "
        "Once this conversation is in execute mode, ask again.)"
    )


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


def _modes_runtime() -> Any:
    return SimpleNamespace(config=SimpleNamespace(
        dm_agentic=DmAgenticConfig(enabled=True, agent_modes_enabled=True),
    ))


class _CountingStore:
    """The gate's one store method, counted."""

    def __init__(self, inner: ChatThreadStore) -> None:
        self._inner = inner
        self.reads = 0

    def get_thread(self, thread_id: str) -> Any:
        self.reads += 1
        return self._inner.get_thread(thread_id)


def _gate_for(store: Any, mode: str, thread: Any, *, reader: Any = None) -> Any:
    """``None`` for "no-gate"; otherwise a real gate on ``thread`` with a ``mode`` record."""
    if mode == "no-gate":
        return None
    store.set_agent_mode(thread.id, mode, changed_by="captain")
    gate = open_plan_mode_reply_gate(
        _modes_runtime(), reader or store, store.get_thread(thread.id), agent_id=_AGENT,
    )
    assert gate is not None
    return gate


def _ctx(
    text: str, runtime: Any, gate: Any, *, thread_id: str, sanity_gate: Any = "default",
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
        sanity_gate=DmSanityGate() if sanity_gate == "default" else sanity_gate,
        params={"thread_id": thread_id, "dm_turn_id": "turn-1"},
        message_text="Plan the report.",
        sampling_state=None,
        avatar_event_bus=None,
        chat_thread_id=thread_id,
        plan_mode_gate=gate,
    )


class _Recreation:
    def __init__(self, log: list[str]) -> None:
        self._log = log

    async def create_game(self, **kwargs: Any) -> dict[str, Any]:
        self._log.append("challenge: game created")
        return {"game_id": "g-1"}

    def get_game_by_player(self, callsign: str) -> dict[str, Any]:
        return {"game_id": "g-1", "thread_id": "wr-1"}

    async def make_move(self, **kwargs: Any) -> dict[str, Any]:
        self._log.append("move: made")
        return {"state": {"current_player": "Worf", "status": "active"}, "result": None}

    def render_board(self, game_id: str) -> str:
        return "board"


class _WardRoom:
    def __init__(self, log: list[str]) -> None:
        self._log = log

    async def list_channels(self) -> list[Any]:
        return [SimpleNamespace(id="rec", name="Recreation")]

    async def create_thread(self, **kwargs: Any) -> Any:
        self._log.append("challenge: thread posted")
        return SimpleNamespace(id="wr-1")

    async def create_post(self, **kwargs: Any) -> None:
        self._log.append("move: board posted")


class _Scheduler:
    def __init__(self, log: list[str]) -> None:
        self._log = log

    def schedule_followup(self, **kwargs: Any) -> bool:
        self._log.append("follow_up: scheduled")
        return True


class _Loop:
    """The proactive loop's two reply writers, recorded. Like the real ones, each
    removes the blocks it acts on and leaves a text without any as it was."""

    def __init__(self, log: list[str]) -> None:
        self._log = log

    async def extract_and_execute_dms(self, agent: Any, text: str) -> tuple[str, list[dict[str, str]]]:
        stripped = proactive_module.strip_dm_blocks(text)
        if not stripped.readable:
            return text, []
        self._log.append("dm: sent")
        return stripped.text, [{"type": "dm"}] * stripped.readable

    async def extract_and_execute_notebooks(self, agent: Any, text: str) -> tuple[str, list[dict[str, str]]]:
        blocks = proactive_module._NOTEBOOK_PATTERN.findall(text)
        if blocks:
            self._log.append("notebook: saved")
        return proactive_module._NOTEBOOK_PATTERN.sub("", text).strip(), [{"type": "notebook_write"}] * len(blocks)


class _Attachments:
    def __init__(self) -> None:
        self.written: list[str] = []

    async def write(self, content_hash: str, blob: bytes, mime: str, **kwargs: Any) -> None:
        self.written.append(mime)


class _Ship:
    """Every channel a reply step acts through. Recording fakes for the game
    service, the Ward Room, the pacing scheduler, the proactive loop's writers and
    image generation; AD-745's real action dispatcher with a fake browser; a real
    work-item store, thread store and artifact store."""

    def __init__(self, tmp_path: Path, store: ChatThreadStore, work_items: WorkItemStore) -> None:
        self.log: list[str] = []
        self.store = store
        self.work_items = work_items
        rt = _action_runtime()
        rt.config.communications.room_todos_enabled = True
        rt.recreation_service = _Recreation(self.log)
        rt.ward_room = _WardRoom(self.log)
        rt.callsign_registry = SimpleNamespace(resolve=lambda callsign: {"agent_id": "worf"})
        rt.conversation_pacing_scheduler = _Scheduler(self.log)
        rt.proactive_loop = _Loop(self.log)
        rt.work_item_store = work_items
        rt.chat_thread_store = store
        rt.trust_network = SimpleNamespace(get_score=lambda agent_id: 0.95)
        rt.artifact_store = ArtifactStore(tmp_path / "artifacts.db")
        rt.attachment_store = _Attachments()
        self.runtime = rt

    def thread(self) -> Any:
        return self.store.get_or_create_default_for_agent(_AGENT, "Ezri")

    async def room(self) -> Any:
        task = await self.work_items.create_work_item(title="Room task", work_type="task", created_by="captain")
        return self.store.create_thread(title="Room", participants=[_AGENT], task_id=task.id)

    async def reply(self, text: str, mode: str, *, thread: Any) -> str:
        ctx = _ctx(text, self.runtime, _gate_for(self.store, mode, thread), thread_id=thread.id)
        with patch("probos.cognitive.image_gen_dispatch.dispatch_image_gen", self._generate):
            await DmReplyPipeline(ctx).run()
        if self.runtime.browser_tool.invoked:
            self.log.append("action: run")
        return ctx.response_text

    async def _generate(self, runtime: Any, *, agent_id: str, prompt: str) -> dict[str, Any]:
        self.log.append("image: generated")
        return {"ok": True, "attachment_id": "sha-1"}


@pytest.fixture
def ship(tmp_path: Path, store: ChatThreadStore, work_items: WorkItemStore) -> _Ship:
    return _Ship(tmp_path, store, work_items)


# ── 1. the crossing: one reply carrying every withheld request ──────────────

_EVERY_REQUEST = "\n".join([
    "Here is the plan.",
    "[CREATE_TASK title=Quarterly report | instructions=Compile the figures | specialist=@Worf]",
    "[DM @Worf] Please pull the figures. [/DM]",
    "[CHALLENGE @Worf chess]",
    '[ACTION: {"verb":"screenshot","args":{}}]',
    "[MOVE 5]",
    "[GEN_IMAGE a flow diagram of the plan]",
    "[FOLLOW_UP 5 check_progress]",
    "[NOTEBOOK plan-notes]The plan in brief.[/NOTEBOOK]",
    "[TODOS]\n- Draft the report\n- Review it\n[/TODOS]",
    '<artifact name="plan.md" mime="text/markdown">\n1. Draft\n2. Review\n</artifact>',
])
_EVERY_EFFECT = [
    "action: run", "challenge: game created", "challenge: thread posted", "dm: sent",
    "follow_up: scheduled", "image: generated", "move: board posted", "move: made",
    "notebook: saved",
]


async def test_seam_plan_mode_acts_on_nothing_outside_the_conversation(ship: _Ship) -> None:
    room = await ship.room()

    text = await ship.reply(_EVERY_REQUEST, "plan", thread=room)

    assert ship.log == []
    assert ship.runtime.action_dispatcher.list_for_thread(room.id) == []
    assert [item.title for item in await ship.work_items.list_work_items()] == ["Room task"]
    assert (await ship.work_items.get_work_item(room.task_id)).steps == []
    assert text.endswith(_notice(
        "a new task, a message to a crewmate, a game challenge, a browser action, a game "
        "move, an image to generate, a scheduled follow-up, a notebook entry and a change "
        "to the task checklist"
    ))
    for tag in ("[CREATE_TASK", "[CHALLENGE", "[ACTION", "[MOVE", "[GEN_IMAGE", "[FOLLOW_UP", "[NOTEBOOK"):
        assert tag not in text, tag
    # Each taken out as its channel takes it out, so no later step acts on it (A-3),
    # and shown to the Captain before the notice: the DM block, the note's text and
    # the checklist proposal.
    assert "[DM @Worf] Please pull the figures. [/DM]" in text
    assert "[TODOS]" in text and "The plan in brief." in text
    # The conversation's own records are kept: the artifact is filed in this thread.
    assert [a.name for a in ship.runtime.artifact_store.list_thread_latest(room.id)] == ["plan.md"]
    assert "[Artifact: plan.md v1" in text


@pytest.mark.parametrize("mode", ["no-gate", "execute"])
async def test_seam_outside_plan_mode_every_channel_acts_as_before(ship: _Ship, mode: str) -> None:
    room = await ship.room()

    text = await ship.reply(_EVERY_REQUEST, mode, thread=room)

    assert sorted(ship.log) == _EVERY_EFFECT
    assert sorted(item.title for item in await ship.work_items.list_work_items()) == [
        "Quarterly report", "Room task",
    ]
    assert len((await ship.work_items.get_work_item(room.task_id)).steps) == 2
    assert [a.name for a in ship.runtime.artifact_store.list_thread_latest(room.id)] == ["plan.md"]
    assert "Plan mode held back" not in text


# ── 2. each kind A-2 adds ───────────────────────────────────────────────────

_KINDS = {
    # kind: (reply, what it does outside plan mode, the notice's phrase)
    "move": ("My move. [MOVE 5]", ["move: board posted", "move: made"], "a game move"),
    "image": ("A sketch. [GEN_IMAGE a flow diagram of the plan]", ["image: generated"], "an image to generate"),
    "follow_up": (
        "I will check back. [FOLLOW_UP 5 check_progress]", ["follow_up: scheduled"], "a scheduled follow-up",
    ),
    "notebook": (
        "[NOTEBOOK plan-notes]The plan in brief.[/NOTEBOOK] A note was saved.",
        ["notebook: saved"],
        "a notebook entry",
    ),
}
_TAGS = {"move": "[MOVE", "image": "[GEN_IMAGE", "follow_up": "[FOLLOW_UP", "notebook": "[NOTEBOOK"}


@pytest.mark.parametrize("kind", list(_KINDS))
async def test_plan_mode_holds_back_each_kind_and_says_so(ship: _Ship, kind: str) -> None:
    """The notebook and follow-up cases are review F1's reproductions: at the
    candidate the note was saved and the follow-up scheduled in plan mode."""
    reply, _effects, phrase = _KINDS[kind]

    text = await ship.reply(reply, "plan", thread=ship.thread())

    assert ship.log == []
    assert _TAGS[kind] not in text
    assert text.endswith(_notice(phrase))
    if kind == "notebook":
        assert "The plan in brief." in text, "the note's text stays in the reply"


@pytest.mark.parametrize("mode", ["no-gate", "execute"])
@pytest.mark.parametrize("kind", list(_KINDS))
async def test_outside_plan_mode_each_kind_acts_as_before(ship: _Ship, kind: str, mode: str) -> None:
    reply, effects, _phrase = _KINDS[kind]

    text = await ship.reply(reply, mode, thread=ship.thread())

    assert sorted(ship.log) == effects
    assert _TAGS[kind] not in text and "Plan mode held back" not in text


_TODOS = "Plan:\n[TODOS]\n- Draft the report\n- Review it\n[/TODOS]"
_PROSE_PLAN = "Here is the plan:\n1. Draft the report\n2. Review it"


async def test_plan_mode_leaves_a_room_checklist_unchanged_and_the_proposal_visible(ship: _Ship) -> None:
    room = await ship.room()

    text = await ship.reply(_TODOS, "plan", thread=room)

    assert (await ship.work_items.get_work_item(room.task_id)).steps == []
    assert "[TODOS]" in text and "- Draft the report" in text
    assert text.endswith(_notice("a change to the task checklist"))


@pytest.mark.parametrize("mode", ["no-gate", "execute"])
async def test_outside_plan_mode_the_room_checklist_is_seeded_as_before(ship: _Ship, mode: str) -> None:
    room = await ship.room()

    text = await ship.reply(_TODOS, mode, thread=room)

    assert len((await ship.work_items.get_work_item(room.task_id)).steps) == 2
    assert "[TODOS]" not in text and "Plan mode held back" not in text


async def test_plan_mode_on_a_thread_without_a_task_strips_todo_tags_as_before_and_reports_nothing(
    ship: _Ship,
) -> None:
    text = await ship.reply(_TODOS, "plan", thread=ship.thread())

    assert "[TODOS]" not in text and "Plan mode held back" not in text


@pytest.mark.parametrize(("mode", "seeded"), [("plan", 0), ("execute", 2), ("no-gate", 2)])
async def test_a_prose_plan_seeds_a_room_checklist_only_outside_plan_mode(
    ship: _Ship, mode: str, seeded: int,
) -> None:
    room = await ship.room()

    text = await ship.reply(_PROSE_PLAN, mode, thread=room)

    assert len((await ship.work_items.get_work_item(room.task_id)).steps) == seeded
    # Withheld without a notice: the agent asked for nothing, and its plan is visible.
    assert text == _PROSE_PLAN


_UNREAD = {
    # case: (reply, the step that would not read it here)
    "action-with-the-switch-off": ('Looking. [ACTION: {"verb":"screenshot","args":{}}]', "step_4e_action_dispatch"),
    "challenge-without-a-game-service": ("Fancy a game? [CHALLENGE @Worf chess]", "step_2_challenge_parse"),
    "move-without-a-game-service": ("My move. [MOVE 5]", "step_3_move_parse"),
    "todos-with-room-todos-off": ("Plan:\n[TODOS]\n- Draft\n- Review\n[/TODOS]", "step_4l_extract_todos"),
    "image-without-a-sanity-gate": ("A sketch. [GEN_IMAGE a flow diagram]", "step_4c_image_gen_parse"),
}


@pytest.mark.parametrize("case", list(_UNREAD))
async def test_a_request_its_step_would_not_read_is_left_as_that_step_leaves_it(
    store: ChatThreadStore, case: str,
) -> None:
    """A pass mirrors its step's preconditions: what the step would not read, plan
    mode leaves exactly as the step does, and does not report."""
    reply, step_name = _UNREAD[case]
    runtime = _action_runtime(enabled=False)  # the switch off, no game service, room todos off
    thread = store.get_or_create_default_for_agent(_AGENT, "Ezri")
    texts = []
    for mode in ("no-gate", "plan"):
        ctx = _ctx(
            reply, runtime, _gate_for(store, mode, thread), thread_id=thread.id,
            sanity_gate=None if case == "image-without-a-sanity-gate" else DmSanityGate(),
        )
        pipeline = DmReplyPipeline(ctx)
        await pipeline._run_steps((getattr(pipeline, step_name), pipeline.step_4p_plan_mode_notice))
        texts.append(ctx.response_text)

    assert texts[1] == texts[0] == reply


def test_split_notebook_blocks_takes_each_block_out_and_keeps_the_entries_the_writer_saves() -> None:
    # A-3 (review H2; was ``unwrap_notebook_blocks``, which put each body back in
    # place, where the steps plan mode allows could act on it): the pass takes the
    # blocks out, as the writer does, and keeps each entry for the Captain.
    split = proactive_module.split_notebook_blocks
    text = (
        "Before. [NOTEBOOK plan-notes]First entry.[/NOTEBOOK] Middle. "
        "[NOTEBOOK ops ship]Second entry.[/NOTEBOOK] [NOTEBOOK empty]  [/NOTEBOOK] After."
    )

    assert split(text) == ("Before.  Middle.   After.", ["First entry.", "Second entry."])
    assert split("") == ("", [])
    unslugged = "No note. [NOTEBOOK]Not a block the writer reads.[/NOTEBOOK]"
    assert split(unslugged) == (unslugged, [])


def test_the_plan_instructions_name_the_notebook_and_follow_up_channels() -> None:
    from probos.cognitive.agent_mode import TurnAgentMode, render_agent_mode_instructions
    from probos.threads.agent_mode import AgentModeRecord

    text = render_agent_mode_instructions(
        TurnAgentMode("plan", AgentModeRecord("plan", 1, 100.0, "captain", None, _AGENT)),  # A-8: its agent
    )

    assert "saving a note" in text and "scheduling a follow-up" in text


# ── 3. the runner ───────────────────────────────────────────────────────────


class _PipelineWithANewStep(DmReplyPipeline):
    async def step_4z_unclassified(self) -> None:
        self.ctx.response_text = f"{self.ctx.response_text} (ran)"


@pytest.mark.parametrize(("mode", "ran"), [("plan", False), ("execute", True), ("no-gate", True)])
async def test_a_step_neither_table_names_does_not_run_in_plan_mode(
    store: ChatThreadStore, mode: str, ran: bool, caplog: pytest.LogCaptureFixture,
) -> None:
    thread = store.get_or_create_default_for_agent(_AGENT, "Ezri")
    pipeline = _PipelineWithANewStep(_ctx("A plan.", SimpleNamespace(), _gate_for(store, mode, thread), thread_id=thread.id))

    with caplog.at_level(logging.WARNING, logger="probos.cognitive.dm.reply_pipeline"):
        await pipeline._run_steps((pipeline.step_4z_unclassified,))

    assert pipeline.ctx.response_text == ("A plan. (ran)" if ran else "A plan.")
    assert ("step_4z_unclassified has no plan-mode classification" in caplog.text) is not ran


async def test_the_thread_is_read_again_only_at_a_step_plan_mode_could_hold_back(store: ChatThreadStore) -> None:
    thread = store.get_or_create_default_for_agent(_AGENT, "Ezri")
    counting = _CountingStore(store)
    gate = _gate_for(store, "plan", thread, reader=counting)
    pipeline = DmReplyPipeline(_ctx("A plan.", SimpleNamespace(), gate, thread_id=thread.id))

    await pipeline._run_steps((pipeline.step_4p_plan_mode_notice, pipeline.step_8_mark_emitted))
    assert counting.reads == 1, "only the route's read: both steps are allowed"

    await pipeline._run_steps((pipeline.step_4d_follow_up_parse, pipeline.step_4i_notebook_parse))
    assert counting.reads == 2, "once more at the first step it could hold back, then kept"


# ── 4. a metadata column that does not decode to an object ─────────────────

_UNDECODABLE = ["{", "not json", "  "]
_NOT_AN_OBJECT = ["[1, 2]", "null", '"plan"', "7"]


def _write_column(store: ChatThreadStore, thread_id: str, raw: str | None) -> None:
    with store._connect() as conn:
        conn.execute("UPDATE chat_threads SET metadata = ? WHERE id = ?", (raw, thread_id))


def _plan_thread_with_column(store: ChatThreadStore, raw: str | None) -> Any:
    thread = store.get_or_create_default_for_agent(_MODE_AGENT, "Ezri")
    store.set_agent_mode(thread.id, "plan", changed_by="captain")
    _write_column(store, thread.id, raw)
    return thread


@pytest.mark.parametrize("raw", [*_UNDECODABLE, *_NOT_AN_OBJECT])
def test_the_store_marks_a_metadata_column_that_is_not_a_json_object(store: ChatThreadStore, raw: str) -> None:
    thread = _plan_thread_with_column(store, raw)

    read = store.get_thread(thread.id)

    assert read.metadata_readable is False
    if raw in _UNDECODABLE:
        assert read.metadata == {}, "what every other reader of the column saw before A-2"


@pytest.mark.parametrize("raw", [None, "", "{}", '{"meeting_active": true}'])
def test_a_column_holding_an_object_or_nothing_is_readable(store: ChatThreadStore, raw: str | None) -> None:
    thread = store.get_or_create_default_for_agent(_MODE_AGENT, "Ezri")
    _write_column(store, thread.id, raw)

    assert store.get_thread(thread.id).metadata_readable is True
    assert read_turn_agent_mode(store, thread.id, agent_id=_MODE_AGENT) is None


def test_the_mark_is_not_part_of_the_thread_api(store: ChatThreadStore) -> None:
    thread = _plan_thread_with_column(store, "{")

    assert set(store.get_thread(thread.id).to_dict()) == {
        "id", "title", "participants", "project_id", "task_id", "pinned", "archived",
        "personality_override", "workspace_root", "created_at", "last_active_at",
        "preprompt", "model", "metadata",
    }


@pytest.mark.parametrize("raw", [*_UNDECODABLE, *_NOT_AN_OBJECT])
def test_the_mode_reader_holds_a_thread_whose_metadata_is_not_an_object(
    store: ChatThreadStore, raw: str, caplog: pytest.LogCaptureFixture,
) -> None:
    thread = _plan_thread_with_column(store, raw)

    with caplog.at_level(logging.WARNING, logger="probos.cognitive.agent_mode"):
        turn = read_turn_agent_mode(store, thread.id, agent_id=_MODE_AGENT)

    assert turn is not None and turn.held is True and turn.mode == "plan"
    assert thread.id in caplog.text and "held in plan mode" in caplog.text


async def test_seam_a_corrupt_column_holds_a_real_dm_turn_to_read_only_tools(store: ChatThreadStore) -> None:
    """Review F2's reproduction: a plan record, then ``{`` in the column. At the
    candidate the turn read "no mode", was offered file_writer and ran it."""
    thread = _plan_thread_with_column(store, "{")
    writer = _Tool("file_writer")
    runtime = _runtime(
        _registry(_Tool("http_fetch"), writer), _Grants(["http_fetch", "file_writer"]),
        cfg=DmAgenticConfig(enabled=True, max_iterations=4, agent_modes_enabled=True), store=store,
    )
    llm = _ScriptedLLM([("file_writer", {"target": "report.md"}), "Done."])

    await _dm_turn(runtime, llm, thread.id, "Write the report.")

    assert _offered(llm.requests[0]) == ["http_fetch"]
    assert writer.calls == []
    assert "## Conversation mode: plan (held)" in llm.requests[0].system_prompt


async def test_mode_reports_the_hold_the_reply_gate_withholds_and_mode_execute_repairs_it(
    store: ChatThreadStore,
) -> None:
    thread = _plan_thread_with_column(store, "{")

    status = await _command(store, thread, "/mode")
    gate = open_plan_mode_reply_gate(_modes_runtime(), store, store.get_thread(thread.id), agent_id=_MODE_AGENT)

    assert "could not be read" in status["response"]
    assert gate is not None and gate.withholds() is True

    await _command(store, thread, "/mode execute")

    assert store.get_thread(thread.id).metadata_readable is True
    assert read_turn_agent_mode(store, thread.id, agent_id=_MODE_AGENT).mode == "execute"


# ── 5. the executor guard's log line ────────────────────────────────────────


async def test_the_plan_mode_guard_logs_no_model_text(caplog: pytest.LogCaptureFixture) -> None:
    """Review F3: the line carried the model-supplied tool id verbatim."""
    executor = DispatchToolExecutor(registry=_registry(_Tool("http_fetch")))
    executor.restrict_to_plan_mode(frozenset({"http_fetch"}))

    with caplog.at_level(logging.DEBUG):
        result = await executor.invoke("counselor-ezri", "MODEL_TEXT_SECRET_012345", {})

    assert result.error is not None
    ours = [r.getMessage() for r in caplog.records if "AD-1156" in r.getMessage()]
    assert ours == [
        "AD-1156: plan mode refused a tool call from agent counselor-ez (a str id of 24 "
        "characters); not run"
    ]
    assert "MODEL_TEXT_SECRET" not in caplog.text
