"""AD-1156 A-3 (#1083): a plan-mode turn leaves nothing behind but its conversation.

The review of A-2 found three defects, each a way a plan-mode turn still acted:

* H1: the DM sanity gate's retry asked the agent again without the thread, so on a
  thread other than the agent's default the retry ran under that default thread's
  mode -- with every tool. The retry now carries the thread, and a turn the route
  dispatched in plan mode carries a plan-mode floor, so every agent pass it causes
  (the first, a retry, a replay of a held turn) runs in plan mode at least.
* H2: a pass that kept a held block's text in the reply exposed it to the steps
  plan mode allows: an artifact or a choice card inside a held note or DM was
  filed, and a mesh read or a deliberate re-roll inside one ran. Each pass now
  takes out what its step takes out, and the notice step shows it to the Captain.
* H3: the divergence check, allowed in plan mode, wrote trust, Hebbian weights and
  the divergence record that other agents and Ship's Records read. A pass that only
  strips the self-tag replaces it, and the emotion step, which reads its result,
  resolves nothing.

What is proven here:

* H1 and its census: the retry, through the route into a real agent turn on a
  non-default thread, in plan mode, across a mode change either way, with the
  execute and modes-off controls; a turn carrying the floor on an execute thread;
  the floor on its own; the gate's reading of the dispatch mode; and ``/mode``
  cancelling a pending AD-743 follow-up, as any Captain message does.
* H2: each nested shape through the whole pipeline in plan mode, and the execute
  control; an artifact outside a held block filed in every mode; each helper
  against the writer it mirrors.
* H3 and the census: steps 7 and 9 with a real trust network and Hebbian router;
  every one of the 24 steps in plan mode with every flag on, against collaborators
  that record their calls -- the thirteen allowed run and call only what they may,
  the eleven others do not run and call nothing.
* The Low: with no gate the runner never consults plan mode.
"""

from __future__ import annotations

import functools
import itertools
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from probos import proactive as proactive_module
from probos.avatars.divergence_detector import compute_divergence
from probos.cognitive import agent_mode as agent_mode_module
from probos.cognitive.agent_mode import TurnAgentMode, open_plan_mode_reply_gate
from probos.cognitive.dm import todo_extractor as todo_extractor_module
from probos.cognitive.dm.pacing_scheduler import ConversationPacingScheduler
from probos.cognitive.dm.reply_pipeline import DmReplyContext, DmReplyPipeline
from probos.cognitive.dm.reply_value import DmReply
from probos.cognitive.dm_sanity_gate import DmSanityGate
from probos.config import DmAgenticConfig, SystemConfig
from probos.consensus.trust import TrustNetwork
from probos.mesh.routing import HebbianRouter
from probos.threads import ChatThreadStore
from probos.threads.agent_mode import AGENT_MODE_METADATA_KEY, AgentModeRecord
from probos.types import IntentResult
from probos.workforce import WorkItemStore
from tests.test_ad1156_plan_execute_mode import (
    _Grants,
    _ScriptedLLM,
    _Tool,
    _chat_request,
    _dm_agent,
    _offered,
    _registry,
    _route_runtime,
    _runtime,
    _transcript,
)
from tests.test_ad1156_plan_mode_containment import _Ship, _gate_for, _notice, _write_column

_AGENT = "a-ezri"
_PLAN_BLOCK = "## Conversation mode: plan\n"
# The params key a plan-dispatched turn carries. A held turn keeps its params until
# it replays, so the key is pinned here literally (and checked against the module).
AGENT_MODE_FLOOR_PARAM = "agent_mode_floor"


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


@pytest.fixture
def ship(tmp_path: Path, store: ChatThreadStore, work_items: WorkItemStore) -> _Ship:
    return _Ship(tmp_path, store, work_items)


def _modes_runtime() -> Any:
    return SimpleNamespace(config=SimpleNamespace(
        dm_agentic=DmAgenticConfig(enabled=True, agent_modes_enabled=True),
    ))


# ── 1. every agent pass a plan-mode turn causes (H1) ────────────────────────


class _Turns:
    """The one-to-one route over a real thread store, with a real agent -- its own
    ``perceive`` and ``_decide_via_llm`` -- behind the intent bus, on a thread other
    than the agent's default. The first answer is three characters, so the DM
    sanity gate asks the agent again, and the retry's pass asks for a write."""

    def __init__(self, tmp_path: Path, *, modes: bool = True) -> None:
        self.rt = _route_runtime(tmp_path, modes=modes)
        self.rt.config.dm_agentic = DmAgenticConfig(
            enabled=True, max_iterations=4, agent_modes_enabled=modes,
        )
        self.store: ChatThreadStore = self.rt.chat_thread_store
        self.default = self.store.get_or_create_default_for_agent("test-agent", "Ezri")
        self.thread = self.store.create_thread(title="Planning", participants=["test-agent"])
        self.writer = _Tool("file_writer")
        agent_rt = _runtime(
            _registry(_Tool("http_fetch"), self.writer), _Grants(["http_fetch", "file_writer"]),
            cfg=self.rt.config.dm_agentic, store=self.store,
        )
        self.llm = _ScriptedLLM([
            "OK.",
            ("file_writer", {"target": "report.md"}),
            "Here is the full plan, Captain: 1. gather the figures, 2. draft the report.",
        ])
        self.agent = _dm_agent(agent_rt, self.llm)
        self.agent.id = "test-agent"
        self.sent: list[Any] = []
        self._first_request: list[int] = []
        self.after_first_pass: str | None = None
        self.rt.intent_bus.send = AsyncMock(side_effect=self._send)

    async def _send(self, intent: Any, **_kwargs: Any) -> IntentResult:
        self.sent.append(intent)
        self._first_request.append(len(self.llm.requests))
        decision = await self.agent._decide_via_llm(await self.agent.perceive(intent))
        if self.after_first_pass is not None and not intent.params.get("is_retry"):
            self.store.set_agent_mode(self.thread.id, self.after_first_pass, changed_by="captain")
        return IntentResult(
            intent_id=intent.id, agent_id="test-agent", success=True, result=decision["llm_output"],
        )

    async def say(self, message: str) -> dict[str, Any]:
        from probos.routers.agents import agent_chat

        request = _chat_request(message)
        request.thread_id = self.thread.id
        with patch("probos.routers.agents.is_crew_agent", return_value=True):
            return await agent_chat("test-agent", request, self.rt)

    def retry_request(self) -> Any:
        return self.llm.requests[self._first_request[1]]

    def assert_a_retry_ran(self) -> None:
        """The premise of every case here: one first pass, then one retry of it, on a
        thread that is not the agent's default, whose default thread has no mode."""
        assert [intent.params.get("is_retry") for intent in self.sent] == [None, True]
        assert self.thread.id != self.default.id
        assert AGENT_MODE_METADATA_KEY not in self.store.get_thread(self.default.id).metadata


async def test_seam_a_sanity_gate_retry_on_a_plan_thread_runs_in_plan_mode(tmp_path: Path) -> None:
    """Review H1's reproduction: at the A-2 candidate the retry was asked without the
    thread, resolved the agent's default thread, which has no mode, was offered every
    tool and wrote."""
    turns = _Turns(tmp_path)
    await turns.say("/mode plan")

    reply = await turns.say("Get the quarterly report moving.")

    turns.assert_a_retry_ran()
    assert _offered(turns.llm.requests[0]) == ["http_fetch"], "the first pass ran in plan mode"
    retry = turns.sent[1]
    assert retry.thread_id == turns.thread.id
    assert retry.params[AGENT_MODE_FLOOR_PARAM] == "plan"
    assert _offered(turns.retry_request()) == ["http_fetch"]
    assert _PLAN_BLOCK in turns.retry_request().system_prompt
    assert turns.writer.calls == []
    assert reply["response"].startswith("Here is the full plan")
    # The floor is a routing fact, never model input.
    assert not [r for r in turns.llm.requests if AGENT_MODE_FLOOR_PARAM in (r.system_prompt or "") + _transcript(r)]


@pytest.mark.parametrize(("dispatched", "then"), [("plan", "execute"), ("execute", "plan")])
async def test_seam_a_mode_change_before_the_retry_leaves_it_in_plan_mode(
    tmp_path: Path, dispatched: str, then: str,
) -> None:
    """The stricter mode wins. Dispatched in plan mode, the turn stays in plan mode
    through its retry whatever the thread says by then (the floor); dispatched in
    execute mode, a /mode plan before the retry reaches it (the thread)."""
    turns = _Turns(tmp_path)
    await turns.say(f"/mode {dispatched}")
    turns.after_first_pass = then

    await turns.say("Get the quarterly report moving.")

    turns.assert_a_retry_ran()
    assert turns.store.get_thread(turns.thread.id).metadata[AGENT_MODE_METADATA_KEY]["mode"] == then
    assert ("file_writer" in _offered(turns.llm.requests[0])) is (dispatched == "execute")
    assert turns.sent[1].thread_id == turns.thread.id
    assert _offered(turns.retry_request()) == ["http_fetch"]
    assert turns.writer.calls == []


async def test_seam_an_execute_thread_retries_on_its_thread_with_its_tools(tmp_path: Path) -> None:
    turns = _Turns(tmp_path)
    await turns.say("/mode execute")

    await turns.say("Get the quarterly report moving.")

    turns.assert_a_retry_ran()
    assert turns.sent[1].thread_id == turns.thread.id
    assert AGENT_MODE_FLOOR_PARAM not in turns.sent[1].params
    assert _offered(turns.retry_request()) == ["file_writer", "http_fetch"]
    assert len(turns.writer.calls) == 1


async def test_with_modes_off_the_retry_is_asked_as_before(tmp_path: Path) -> None:
    turns = _Turns(tmp_path, modes=False)
    turns.store.set_agent_mode(turns.thread.id, "plan", changed_by="captain")

    await turns.say("Get the quarterly report moving.")

    turns.assert_a_retry_ran()
    # HEAD's retry: no thread (F-26 records what that loses), no floor, every tool.
    assert turns.sent[1].thread_id is None
    assert all(AGENT_MODE_FLOOR_PARAM not in intent.params for intent in turns.sent)
    assert len(turns.writer.calls) == 1


@pytest.mark.parametrize(("floor", "offered", "writes"), [
    (None, ["file_writer", "http_fetch"], 1),
    ("plan", ["http_fetch"], 0),
])
async def test_a_turn_carrying_the_floor_runs_in_plan_mode_on_an_execute_thread(
    store: ChatThreadStore, floor: str | None, offered: list[str], writes: int,
) -> None:
    """A retry and a replay of a held turn reach the agent this way, the floor in the
    intent's params: the thread says execute, and the turn is planned, with the plan
    instructions rather than the held ones."""
    thread = store.get_or_create_default_for_agent(_AGENT, "Ezri")
    store.set_agent_mode(thread.id, "execute", changed_by="captain")
    writer = _Tool("file_writer")
    rt = _runtime(
        _registry(_Tool("http_fetch"), writer), _Grants(["http_fetch", "file_writer"]),
        cfg=DmAgenticConfig(enabled=True, max_iterations=4, agent_modes_enabled=True), store=store,
    )
    llm = _ScriptedLLM([("file_writer", {"target": "report.md"}), "Done."])
    params: dict[str, Any] = {"text": "Write the report."}
    if floor is not None:
        params[AGENT_MODE_FLOOR_PARAM] = floor

    agent = _dm_agent(rt, llm)
    agent.id = _AGENT  # A-9: the agent whose record the thread stores
    await agent._decide_via_llm(
        {"intent": "direct_message", "params": params, "thread_id": thread.id},
    )

    assert _offered(llm.requests[0]) == offered
    assert len(writer.calls) == writes
    assert (_PLAN_BLOCK in llm.requests[0].system_prompt) is (floor is not None)
    assert "(held)" not in llm.requests[0].system_prompt


# A-8: a record names the agent it was set for.
_EXECUTE = AgentModeRecord("execute", 2, 100.0, "captain", "plan", _AGENT)
_PLAN = AgentModeRecord("plan", 1, 90.0, "captain", None, _AGENT)


@pytest.mark.parametrize(("turn", "floor", "expected"), [
    (None, None, None),
    (None, "plan", TurnAgentMode("plan", None)),
    (TurnAgentMode("execute", _EXECUTE), None, TurnAgentMode("execute", _EXECUTE)),
    (TurnAgentMode("execute", _EXECUTE), "plan", TurnAgentMode("plan", _EXECUTE)),
    (TurnAgentMode("execute", _EXECUTE), "execute", TurnAgentMode("execute", _EXECUTE)),
    (TurnAgentMode("execute", _EXECUTE), "PLAN", TurnAgentMode("execute", _EXECUTE)),
    (TurnAgentMode("plan", _PLAN), "plan", TurnAgentMode("plan", _PLAN)),
    (TurnAgentMode("plan", None), None, TurnAgentMode("plan", None)),
])
def test_the_floor_raises_a_turn_to_plan_mode_and_never_lowers_one(
    turn: TurnAgentMode | None, floor: str | None, expected: TurnAgentMode | None,
) -> None:
    assert agent_mode_module.AGENT_MODE_FLOOR_PARAM == AGENT_MODE_FLOOR_PARAM
    assert agent_mode_module.floor_turn_agent_mode(turn, floor) == expected


@pytest.mark.parametrize(("record", "planned"), [
    (None, False), ("execute", False), ("plan", True), ("unreadable", True), ("unresolved", True),
])
def test_the_gate_says_whether_the_turn_was_dispatched_in_plan_mode(
    store: ChatThreadStore, record: str | None, planned: bool,
) -> None:
    thread = store.get_or_create_default_for_agent(_AGENT, "Ezri")
    if record in ("plan", "execute"):
        store.set_agent_mode(thread.id, record, changed_by="captain")
    if record == "unreadable":
        _write_column(store, thread.id, "{")

    gate = open_plan_mode_reply_gate(
        _modes_runtime(), store, None if record == "unresolved" else store.get_thread(thread.id),
        agent_id=_AGENT,
    )

    assert gate is not None and gate.planned_at_dispatch is planned


@pytest.mark.parametrize("modes", [True, False])
async def test_mode_cancels_a_pending_follow_up_as_any_captain_message_does(
    tmp_path: Path, modes: bool,
) -> None:
    """At the A-2 candidate the /mode branch returned before the AD-743 cancel, so a
    follow-up an execute-mode reply scheduled still ran -- on the agent's default
    thread, with every tool -- after the Captain chose plan mode. With modes off the
    text is an ordinary message and cancels it, as it always has (the control)."""
    from probos.routers.agents import agent_chat

    rt = _route_runtime(tmp_path, modes=modes)
    cfg = SystemConfig()
    cfg.avatars.pacing_enabled = True
    scheduler = ConversationPacingScheduler(  # type: ignore[arg-type]
        SimpleNamespace(config=cfg, intent_bus=SimpleNamespace(send=AsyncMock())),
    )
    await scheduler.start()
    try:
        assert scheduler.schedule_followup("test-agent", 30, "check_progress") is True
        assert ("test-agent", "default") in scheduler.pending_followups
        rt.conversation_pacing_scheduler = scheduler

        with patch("probos.routers.agents.is_crew_agent", return_value=True):
            result = await agent_chat("test-agent", _chat_request("/mode plan"), rt)

        assert bool(result.get("system")) is modes, "handled as the command only with modes on"
        assert scheduler.pending_followups == {}
    finally:
        await scheduler.stop()


# ── 2. a request inside a held block (H2) ───────────────────────────────────

_ARTIFACT = '<artifact name="inner.md" mime="text/markdown">\n# Inner\n1. a\n</artifact>'
_CHOICE = '{"kind":"choice","prompt":"Pick a plan","options":["Plan A","Plan B"]}'


class _Model:
    def __init__(self, log: list[str]) -> None:
        self._log = log

    async def complete(self, req: Any, **_kwargs: Any) -> Any:
        self._log.append("llm: complete")
        return SimpleNamespace(content="A refined reply.", error=None)


class _Reader:
    def __init__(self, log: list[str]) -> None:
        self._log = log

    async def send(self, intent: Any, **_kwargs: Any) -> IntentResult:
        self._log.append(f"mesh: {intent.intent}")
        return IntentResult(intent_id=intent.id, agent_id="reader-1", success=True, result="file text")


def _wire_every_reader(ship: _Ship) -> None:
    """Choice cards and deliberation on, and the model and mesh reads recorded."""
    ship.runtime.config.communications.a2ui_enabled = True
    ship.runtime.config.dm_deliberate.enabled = True
    ship.runtime.llm_client = _Model(ship.log)
    ship.runtime.intent_bus = _Reader(ship.log)
    ship.runtime.registry = SimpleNamespace(get_by_pool=lambda pool: [SimpleNamespace(id="reader-1")])
    ship.runtime.hook_bus = None
    ship.runtime.intent_grant_store = None


_NESTED = {
    # shape: (reply, what execute mode does, the notice's phrase, what plan mode shows)
    "an artifact in a note": (
        f"Plan.\n[NOTEBOOK plan-notes]{_ARTIFACT}[/NOTEBOOK]",
        ["notebook: saved"], "a notebook entry", _ARTIFACT,
    ),
    "an artifact in a DM": (
        f"Plan.\n[DM @Worf] {_ARTIFACT} [/DM]",
        ["dm: sent"], "a message to a crewmate", f"[DM @Worf] {_ARTIFACT} [/DM]",
    ),
    "a choice card in a DM": (
        f"Plan.\n[DM @Worf] [A2UI]{_CHOICE}[/A2UI] [/DM]",
        ["dm: sent"], "a message to a crewmate", f"[DM @Worf] [A2UI]{_CHOICE}[/A2UI] [/DM]",
    ),
    "a mesh read in a DM": (
        "Plan.\n[DM @Worf] [MESH read_file path=notes.md] [/DM]",
        ["dm: sent"], "a message to a crewmate", "[DM @Worf] [MESH read_file path=notes.md] [/DM]",
    ),
    "a deliberation in a DM": (
        "Plan.\n[DM @Worf] Pull the figures. [THINK] [/DM]",
        ["dm: sent"], "a message to a crewmate", "[DM @Worf] Pull the figures. [THINK] [/DM]",
    ),
    "a note in a DM": (
        "Plan.\n[DM @Worf] Note this. [NOTEBOOK plan-notes]Kept.[/NOTEBOOK] [/DM]",
        ["dm: sent"], "a message to a crewmate",
        "[DM @Worf] Note this. [NOTEBOOK plan-notes]Kept.[/NOTEBOOK] [/DM]",
    ),
    "a deliberation in a checklist": (
        "Plan.\n[TODOS]\n- Draft [THINK]\n- Review\n[/TODOS]",
        [], "a change to the task checklist", "[TODOS]\n- Draft [THINK]\n- Review\n[/TODOS]",
    ),
}


async def _nested_thread(ship: _Ship, shape: str) -> Any:
    return await ship.room() if "checklist" in shape else ship.thread()


@pytest.mark.parametrize("shape", list(_NESTED))
async def test_plan_mode_acts_on_nothing_inside_a_held_request(ship: _Ship, shape: str) -> None:
    """Review H2's reproduction, and the other nested shapes: at the A-2 candidate the
    pass kept each held block's text in the reply, so the steps plan mode allows acted
    on what was inside it -- an artifact or choice card filed, a mesh read or a
    deliberate re-roll run, a note inside a DM counted as a note. Each pass now takes
    out what its step takes out; the notice step shows it, then the notice."""
    reply, _effects, phrase, shown = _NESTED[shape]
    _wire_every_reader(ship)
    thread = await _nested_thread(ship, shape)

    text = await ship.reply(reply, "plan", thread=thread)

    assert ship.log == []
    assert ship.runtime.artifact_store.list_thread_latest(thread.id) == []
    assert text == f"Plan.\n\n{shown}\n\n" + _notice(phrase)
    if "checklist" in shape:
        assert (await ship.work_items.get_work_item(thread.task_id)).steps == []


@pytest.mark.parametrize("shape", list(_NESTED))
async def test_outside_plan_mode_a_held_request_acts_and_nothing_inside_it_does(
    ship: _Ship, shape: str,
) -> None:
    """The control, and the rule plan mode keeps: it withholds what execute mode does
    and never adds to it. Execute mode acts on the outer request only."""
    reply, effects, _phrase, _shown = _NESTED[shape]
    _wire_every_reader(ship)
    thread = await _nested_thread(ship, shape)

    text = await ship.reply(reply, "execute", thread=thread)

    assert sorted(ship.log) == effects
    assert ship.runtime.artifact_store.list_thread_latest(thread.id) == []
    assert "Plan mode held back" not in text
    if "checklist" in shape:
        assert len((await ship.work_items.get_work_item(thread.task_id)).steps) == 2


@pytest.mark.parametrize("mode", ["plan", "execute"])
@pytest.mark.parametrize("where", ["on its own", "in a checklist"])
async def test_an_artifact_outside_a_held_block_is_filed_in_every_mode(
    ship: _Ship, mode: str, where: str,
) -> None:
    """The reply's own content is its conversation's (A-2's decision stands). Inside a
    checklist proposal it is filed in both modes, because step 4f runs before 4l."""
    thread = await ship.room() if where == "in a checklist" else ship.thread()
    reply = f"Plan.\n{_ARTIFACT}" if where == "on its own" else f"Plan.\n[TODOS]\n- Draft {_ARTIFACT}\n[/TODOS]"

    await ship.reply(reply, mode, thread=thread)

    assert [a.name for a in ship.runtime.artifact_store.list_thread_latest(thread.id)] == ["inner.md"]


class _Records:
    """The records store the real notebook writer uses; records what it would save."""

    def __init__(self) -> None:
        self.saved: list[str] = []

    async def check_notebook_similarity(self, **_kwargs: Any) -> dict[str, str]:
        return {"action": "write"}

    async def write_notebook(self, *, content: str, **_kwargs: Any) -> None:
        self.saved.append(content)


def _real_writer(runtime: Any) -> Any:
    loop = proactive_module.ProactiveCognitiveLoop.__new__(proactive_module.ProactiveCognitiveLoop)
    loop._runtime = runtime
    loop._dm_send_cooldowns = {}
    loop._last_dm_body = {}
    return loop


_WRITER_AGENT = SimpleNamespace(id="a-1", agent_type="counselor", callsign="Ezri")

_DM_SHAPES = [
    "",
    "No blocks here.",
    "Plan. [DM @Worf] Pull the figures. [/DM] Done.",
    "[DM @Worf] One. [/DM][DM @Troi] Two. [/DM]",
    "Plan. [DM @Worf] Unclosed to the end.",
    "Plan. [DM @Worf] Closed. [/DM] Then [DM @Troi] unclosed.  ",
    "Unreadable [DM@Troi] body [/DM] stays.",
    "A stray [/DM] closer stays.",
    "  [DM @Worf]   padded   [/DM]  ",
    "[DM @Captain] For you. [/DM]",
    "Nested [DM @Worf] outer [DM @Troi] inner [/DM] tail [/DM] end",
    "[dm @worf] lower case [/dm] after",
]


@pytest.mark.parametrize("text", _DM_SHAPES)
async def test_split_dm_blocks_leaves_the_text_the_dm_step_leaves(text: str) -> None:
    """The pass must leave every later step what the real DM writer leaves it. Here
    nothing can be sent (no callsign registry, no Ward Room), and the writer still
    strips every block it reads."""
    cleaned, _actions = await _real_writer(SimpleNamespace()).extract_and_execute_dms(_WRITER_AGENT, text)

    kept, blocks = proactive_module.split_dm_blocks(text)

    assert kept == cleaned
    assert len(blocks) == proactive_module.strip_dm_blocks(text).readable


_NOTEBOOK_SHAPES = [
    "",
    "No note.",
    "Before. [NOTEBOOK plan-notes]First entry.[/NOTEBOOK] Middle. [NOTEBOOK ops ship]Second entry.[/NOTEBOOK] After.",
    "[NOTEBOOK empty]   [/NOTEBOOK] only an empty one",
    "No note. [NOTEBOOK]Not a block the writer reads.[/NOTEBOOK]",
    f"[NOTEBOOK nested]{_ARTIFACT}[/NOTEBOOK]",
]


@pytest.mark.parametrize("text", _NOTEBOOK_SHAPES)
async def test_split_notebook_blocks_leaves_the_text_and_keeps_the_entries_the_writer_saves(text: str) -> None:
    records = _Records()
    runtime = SimpleNamespace(_records_store=records, config=None, ontology=None)
    cleaned, _actions = await _real_writer(runtime).extract_and_execute_notebooks(_WRITER_AGENT, text)

    kept, entries = proactive_module.split_notebook_blocks(text)

    assert kept == (cleaned if "[NOTEBOOK" in text else text.strip())
    assert entries == records.saved


_TODO_SHAPES = [
    "",
    "No tags.",
    "Plan:\n[TODOS]\n- Draft\n- Review\n[/TODOS]\nDone.",
    "[PLAN]one; two[/PLAN]",
    "[TODO_DONE 1] [TODO_CONFIRM 2 @view.1] [TODO_REJECT 3: not yet] [TODO_VIEW v-1] tail",
    "[todos]\n- lower\n[/todos] [TODOS]\n- second\n[/TODOS]",
]


@pytest.mark.parametrize("text", _TODO_SHAPES)
def test_split_todo_tags_leaves_what_strip_todo_tags_leaves_and_names_what_it_removed(text: str) -> None:
    kept, tags = todo_extractor_module.split_todo_tags(text)

    assert kept == todo_extractor_module.strip_todo_tags(text)
    rebuilt = text
    for tag in tags:
        assert tag in rebuilt
        rebuilt = rebuilt.replace(tag, "", 1)
    assert rebuilt.strip() == kept


# ── 3. no learning from a plan-mode reply (H3) ──────────────────────────────


def _reply_ctx(
    text: str, runtime: Any, gate: Any, *, thread_id: str = "t-1", agent: Any = None, **extra: Any,
) -> DmReplyContext:
    return DmReplyContext(
        runtime=runtime,
        agent=agent or SimpleNamespace(id=_AGENT, agent_type="counselor", callsign="Ezri"),
        agent_id=_AGENT, callsign="Ezri", req_message="Plan it.", reply=DmReply(body=text),
        has_image_attachment=False, per_attachment=[], sanity_gate=DmSanityGate(),
        params={"text": "Plan it."}, message_text="Plan it.", sampling_state=None,
        avatar_event_bus=None, chat_thread_id=thread_id, plan_mode_gate=gate, **extra,
    )


class _Learning:
    """A real trust network and Hebbian router whose writes are also recorded."""

    def __init__(self) -> None:
        self.writes: list[str] = []
        self.trust = TrustNetwork()
        self.hebbian = HebbianRouter()
        self._record_outcome = self.trust.record_outcome
        self._record_interaction = self.hebbian.record_interaction
        self.trust.record_outcome = self._outcome  # type: ignore[method-assign]
        self.hebbian.record_interaction = self._interaction  # type: ignore[method-assign]

    def _outcome(self, *args: Any, **kwargs: Any) -> Any:
        self.writes.append("trust")
        return self._record_outcome(*args, **kwargs)

    def _interaction(self, *args: Any, **kwargs: Any) -> Any:
        self.writes.append("hebbian")
        return self._record_interaction(*args, **kwargs)


def _divergence_runtime(learning: _Learning, *, detection: bool = True) -> tuple[Any, Any]:
    cfg = SystemConfig()
    cfg.avatar_telemetry.divergence_detection = detection
    cfg.avatar_telemetry.divergence_history_size = 100
    earlier = compute_divergence(intent_emotion="concerned", applied_fired_rules=("intent_concerned",))
    runtime = SimpleNamespace(
        config=cfg, trust_network=learning.trust, hebbian_router=learning.hebbian,
        divergence_results={_AGENT: earlier}, divergence_history={}, divergence_corrections={},
        profile_store=None,
    )
    return runtime, earlier


def _agent_with_a_render() -> Any:
    render = SimpleNamespace(
        applied_modulation=SimpleNamespace(fired_rules=("low_trust_pitch",)), current_signals=None,
    )
    return SimpleNamespace(id=_AGENT, agent_type="counselor", callsign="Ezri", _last_self_avatar_snap=render)


@pytest.mark.parametrize("mode", ["no-gate", "execute", "plan"])
async def test_plan_mode_leaves_trust_hebbian_weights_and_the_divergence_record_as_they_were(
    store: ChatThreadStore, mode: str,
) -> None:
    """Review H3's reproduction: at the A-2 candidate the divergence check ran in plan
    mode, so a plan-mode reply moved the agent's trust and Hebbian weights and added
    to the divergence record that peer perception and Ship's Records read. The
    no-gate and execute cases are the controls and the premise: this reply scores."""
    learning = _Learning()
    runtime, earlier = _divergence_runtime(learning)
    thread = store.get_or_create_default_for_agent(_AGENT, "Ezri")
    ctx = _reply_ctx(
        "Here is the plan.\n<intent emotion=warm>", runtime, _gate_for(store, mode, thread),
        thread_id=thread.id, agent=_agent_with_a_render(),
    )
    pipeline = DmReplyPipeline(ctx)

    await pipeline._run_steps((pipeline.step_7_divergence_check, pipeline.step_9_emotion_resolve))

    assert ctx.response_text == "Here is the plan."
    if mode == "plan":
        assert learning.writes == []
        assert runtime.divergence_results[_AGENT] is earlier
        assert runtime.divergence_history == {}
        assert ctx.emotion is None, "the earlier reply's emotion is not this reply's"
    else:
        assert learning.writes == ["trust", "hebbian"]
        assert runtime.divergence_results[_AGENT].intent_emotion == "warm"
        assert len(runtime.divergence_history[_AGENT]) == 1
        assert ctx.emotion == "warm"


@pytest.mark.parametrize("mode", ["no-gate", "plan"])
@pytest.mark.parametrize("detection", [True, False])
async def test_plan_mode_strips_the_self_tag_exactly_when_the_check_would(
    store: ChatThreadStore, mode: str, detection: bool,
) -> None:
    learning = _Learning()
    runtime, _earlier = _divergence_runtime(learning, detection=detection)
    thread = store.get_or_create_default_for_agent(_AGENT, "Ezri")
    ctx = _reply_ctx(
        "Here is the plan.\n<intent emotion=warm>", runtime, _gate_for(store, mode, thread),
        thread_id=thread.id, agent=_agent_with_a_render(),
    )
    pipeline = DmReplyPipeline(ctx)

    await pipeline._run_steps((pipeline.step_7_divergence_check,))

    assert ("<intent" in ctx.response_text) is not detection


# ── 4. the census: every step in plan mode, every flag on ───────────────────


class _Rec:
    """Records every method call made on it, by name."""

    _ASYNC = frozenset({"send", "complete", "store", "write", "check_own_render"})

    def __init__(self, name: str, log: list[str], returns: dict[str, Any] | None = None) -> None:
        self._name, self._log, self._returns = name, log, returns or {}

    def __getattr__(self, attr: str) -> Any:
        if attr.startswith("_"):
            raise AttributeError(attr)
        ret = self._returns.get(attr)

        def call(*args: Any, **kwargs: Any) -> Any:
            self._log.append(f"{self._name}.{attr}")
            return ret(*args, **kwargs) if callable(ret) else ret

        async def acall(*args: Any, **kwargs: Any) -> Any:
            return call(*args, **kwargs)

        return acall if attr in self._ASYNC else call


class _RecDict(dict):
    """A runtime slot that records every write."""

    def __init__(self, name: str, log: list[str], *args: Any) -> None:
        super().__init__(*args)
        self._name, self._log = name, log

    def __setitem__(self, key: Any, value: Any) -> None:
        self._log.append(f"{self._name}[]=")
        super().__setitem__(key, value)

    def pop(self, *args: Any) -> Any:
        self._log.append(f"{self._name}.pop")
        return super().pop(*args)


class _CensusRuntime:
    """Every collaborator a reply step reaches records its calls; an attribute that
    is not one of them is recorded as read and is absent."""

    def __init__(self, log: list[str], store: ChatThreadStore) -> None:
        cfg = SystemConfig()
        cfg.avatar_telemetry.divergence_detection = True
        cfg.avatar_telemetry.divergence_history_size = 100
        cfg.communications.a2ui_enabled = True
        cfg.communications.room_todos_enabled = True
        cfg.dm_deliberate.enabled = True
        cfg.browser_tool.action_dispatch_enabled = True
        self.config = cfg
        self.chat_thread_store = store
        self.trust_network = _Rec("trust", log, {"get_score": 0.95})
        self.hebbian_router = _Rec("hebbian", log)
        self.divergence_results = _RecDict("divergence_results", log, {
            _AGENT: compute_divergence(intent_emotion="concerned", applied_fired_rules=("intent_concerned",)),
        })
        self.divergence_history = _RecDict("divergence_history", log)
        self.divergence_corrections = _RecDict("divergence_corrections", log)
        self.episodic_memory = _Rec("episodic", log)
        self.artifact_store = _Rec("artifact_store", log, {
            "list_thread_latest": [],
            "add_version": lambda *a, **k: SimpleNamespace(
                name=k.get("name", "x"), version=1, mime=k.get("mime", "text/markdown"), id="art-1",
                artifact_id="art-1", content_hash="h", size_bytes=1,
            ),
        })
        self.attachment_store = _Rec("attachment_store", log)
        self.intent_bus = _Rec("intent_bus", log, {
            "send": lambda intent, **k: IntentResult(
                intent_id=intent.id, agent_id="r", success=True, result="A fuller answer from the retry.",
            ),
        })
        self.registry = _Rec("registry", log, {"get_by_pool": [SimpleNamespace(id="reader-1")]})
        self.llm_client = _Rec("llm", log, {"complete": SimpleNamespace(content="A refined reply.")})
        for name in (
            "recreation_service", "ward_room", "proactive_loop", "work_item_store",
            "conversation_pacing_scheduler", "action_dispatcher", "records_store", "profile_store",
            "callsign_registry", "emit_event", "event_log",
        ):
            setattr(self, name, _Rec(name, log))
        self.hook_bus = None
        self.intent_grant_store = None
        self._log = log

    def __getattr__(self, name: str) -> Any:
        self.__dict__["_log"].append(f"read:{name}")
        return None


_CENSUS = {
    # step: (reply, what it may call in plan mode, what it must call -- the premise)
    "step_1_sanity_gate_retry": ("OK.", {"divergence_corrections.pop", "intent_bus.send"}, {"intent_bus.send"}),
    "step_2_challenge_parse": ("Fancy a game? [CHALLENGE @Worf chess]", None, None),
    "step_3_move_parse": ("My move. [MOVE 5]", None, None),
    "step_4_self_check_parse": (
        "Checking. [SELF_CHECK before_reply]", {"agent.check_own_render"}, {"agent.check_own_render"},
    ),
    "step_4c_image_gen_parse": ("A sketch. [GEN_IMAGE a flow diagram]", None, None),
    "step_4d_follow_up_parse": ("Later. [FOLLOW_UP 5 check_progress]", None, None),
    "step_4e_action_dispatch": ('[ACTION: {"verb":"screenshot","args":{}}]', None, None),
    "step_4b_dm_outbound_parse": ("Plan. [DM @Worf] Pull the figures. [/DM]", None, None),
    "step_4i_notebook_parse": ("[NOTEBOOK plan-notes]The plan.[/NOTEBOOK]", None, None),
    "step_4h_mesh_read_parse": (
        "Looking. [MESH read_file path=notes.md]",
        {"registry.get_by_pool", "intent_bus.send"}, {"intent_bus.send"},
    ),
    "step_4f_extract_artifacts": (
        '<artifact name="plan.md" mime="text/markdown">\n# Plan\n1. a\n</artifact>',
        {"artifact_store.list_thread_latest", "artifact_store.add_version", "attachment_store.write"},
        {"artifact_store.add_version"},
    ),
    "step_4k_extract_a2ui": (
        f"Pick one. [A2UI]{_CHOICE}[/A2UI]",
        {"artifact_store.add_version", "attachment_store.write"}, {"artifact_store.add_version"},
    ),
    "step_4g_create_task_parse": ("[CREATE_TASK title=R | instructions=Do it | specialist=@Worf]", None, None),
    "step_4l_extract_todos": ("Plan:\n[TODOS]\n- Draft\n- Review\n[/TODOS]", None, None),
    "step_4j_deliberate_parse": ("Draft. [THINK]", {"llm.complete"}, {"llm.complete"}),
    "step_4n_tool_write_ledger": ("A plan.", set(), set()),
    "step_4m_write_claim_guard": ("A note was saved.", set(), set()),
    "step_4o_owned_steps_feedback": ("A plan.", set(), set()),
    "step_4p_plan_mode_notice": ("A plan.", set(), set()),
    "step_5_episodic_store": ("A plan.", {"episodic.store"}, {"episodic.store"}),
    "step_6_working_memory_record": (
        "A plan.", {"agent.working_memory.record_conversation"}, {"agent.working_memory.record_conversation"},
    ),
    "step_7_divergence_check": ("A plan.\n<intent emotion=warm>", None, None),
    "step_8_mark_emitted": ("A plan.", {"agent.mark_reply_emitted"}, {"agent.mark_reply_emitted"}),
    "step_9_emotion_resolve": ("A plan.", None, None),
}


def test_the_census_names_every_step() -> None:
    pipeline = DmReplyPipeline(_reply_ctx("x", SimpleNamespace(), None))

    assert sorted(_CENSUS) == sorted(step.__name__ for step in pipeline._full_steps())


@pytest.mark.parametrize("name", list(_CENSUS))
async def test_in_plan_mode_each_step_calls_only_what_it_may(store: ChatThreadStore, name: str) -> None:
    """Each step alone, in plan mode, every flag on, against collaborators that record
    their calls. An allowed step runs (the premise: its runner let it, and it made
    the call its work needs) and calls nothing else; it writes only the reply, the
    conversation's record (its episode, the agent's working memory, this thread's
    artifacts) or what a read costs. Every other step does not run and calls nothing.
    Step 1 also updates the sanity gate's own last-reply cache, which only that
    agent's next reply reads; step 4's self-check writes only the agent's working
    memory (tests/test_ad728d_self_image_awareness_skill.py)."""
    reply, may, must = _CENSUS[name]
    thread = store.get_or_create_default_for_agent(_AGENT, "Ezri")
    log: list[str] = []
    runtime = _CensusRuntime(log, store)
    agent = SimpleNamespace(
        id=_AGENT, agent_type="counselor", callsign="Ezri",
        _last_self_avatar_snap=_agent_with_a_render()._last_self_avatar_snap,
        working_memory=_Rec("agent.working_memory", log),
        check_own_render=_Rec("agent", log).check_own_render,
        mark_reply_emitted=_Rec("agent", log).mark_reply_emitted,
    )
    ctx = _reply_ctx(
        reply, runtime, _gate_for(store, "plan", thread), thread_id=thread.id, agent=agent,
        owned_steps_feedback="Owned-step feedback." if name == "step_4o_owned_steps_feedback" else None,
    )
    pipeline = DmReplyPipeline(ctx)
    ran: list[str] = []
    real = getattr(pipeline, name)

    @functools.wraps(real)
    async def step() -> None:
        ran.append(name)
        await real()

    async def _image(runtime_: Any, **kwargs: Any) -> dict[str, Any]:
        log.append("image_gen.dispatch")
        return {"ok": True, "attachment_id": "sha-1"}

    with patch("probos.cognitive.image_gen_dispatch.dispatch_image_gen", _image):
        await pipeline._run_steps((step,))
        if ctx._self_check_task is not None:
            await ctx._self_check_task

    calls = {entry for entry in log if not entry.startswith("read:")}
    assert not [entry for entry in log if entry.startswith("read:")], "a collaborator outside the census"
    if may is None:
        assert ran == [] and calls == set()
    else:
        assert ran == [name]
        assert must <= calls <= may


# ── 5. no gate, no consultation (the Low) ───────────────────────────────────


async def test_with_no_gate_the_runner_never_consults_plan_mode(store: ChatThreadStore) -> None:
    """The review's Low: A-2's runner asked plan mode at every step of every reply,
    gate or none -- 24 calls a reply and 11 a group reply, each returning at once."""
    calls = {"n": 0}
    real = DmReplyPipeline._plan_mode_holds_back

    def _counting(self: Any, *args: Any, **kwargs: Any) -> Any:
        calls["n"] += 1
        return real(self, *args, **kwargs)

    thread = store.get_or_create_default_for_agent(_AGENT, "Ezri")
    counts = {}
    with patch.object(DmReplyPipeline, "_plan_mode_holds_back", _counting):
        for label, gate in (
            ("run", None), ("escalation", None), ("plan", _gate_for(store, "plan", thread)),
        ):
            calls["n"] = 0
            pipeline = DmReplyPipeline(_reply_ctx(
                "A plan.", SimpleNamespace(config=SystemConfig()), gate, thread_id=thread.id,
            ))
            if label == "escalation":
                await pipeline.run_escalation_only()
            else:
                await pipeline.run()
            counts[label] = calls["n"]

    assert counts == {"run": 0, "escalation": 0, "plan": 24}
