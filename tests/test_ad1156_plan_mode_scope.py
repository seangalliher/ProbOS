"""AD-1156 A-5 (#1083): where plan mode governs, and where it does not.

What is proven here, and where:

* The CLI ``/session``: it sends the Captain's message with no thread, so the agent's
  real turn runs under its default thread's mode -- asserted on what the model was
  offered, the review's premise. The session reads that mode as the route reads its
  thread's, before it sends and once the answer is back, and marks its own episode
  of a turn plan mode governed, so the real ``_consolidate_trust`` credits nothing
  for it; an execute-mode or modes-off session turn is stored and credited exactly as
  before. With the modes off the session reads no thread.
* A thread that is not one-to-one: its group replies read no mode. A one-to-one thread
  set to plan mode and then given a second agent keeps the record; ``/mode`` says its
  group replies are not held -- and the group's reply does act, through the real
  fan-out -- and, since A-9, that this agent's own turns there are held in plan mode,
  as its real turn on the thread is. Once the thread is one-to-one again the record
  governs again, and ``/mode`` says so. With no record there, ``/mode`` names none and
  a turn runs as before; with a record, readable or not, a turn of this agent there is
  held and ``/mode`` says so; with the loop off it says so too.
* A-6, one thread and fail closed: the session sends its turn on the thread its gate
  read, with the route's plan floor when the gate read plan mode or could not resolve
  the thread. So the agent's real turn is held in plan mode when the default thread
  cannot be resolved, and stays on the gate's thread, in plan mode at least, when a
  participant joins or ``/mode execute`` lands before it runs. An agent that cannot
  resolve its thread with the modes on holds its turn, whatever surface sent it.
  ``/mode`` status reads the participants when it runs, and the writer refuses, inside
  its transaction, a thread that stopped being one-to-one after the route read it.
* A-8, a record is bound to the agent it was set for: after ``/mode execute`` for one
  agent and another agent in its place -- the review's probe -- the new agent's real
  turn does not read the approval (since A-9 it is held in plan mode, and ``/mode`` in
  its panel says so); with the first agent back the record governs again; a record
  that names no agent holds the turn in plan mode; the parser refuses a malformed
  agent; and ``/mode`` for the new agent starts its own record at revision 1.
* A-9, every read that decides a turn's mode names the turn's agent: a turn the route
  admitted for one agent, whose thread the other agent takes -- setting execute there --
  before the route's gate reads it, is held in plan mode through the real route, either
  way round, while with no record, the agent's own execute record, or the modes off it
  runs as before, and with the modes off nothing is decided; an agent reads for itself
  however its thread reaches it, and so do the CLI session and ``/mode``; a read that
  cannot name its agent, or whose thread is gone, is held; and every read in ``src``
  names its agent. (The AD-1230 replay's case is in the learning file.)
"""

from __future__ import annotations

import ast
import io
import itertools
import logging
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable
from unittest.mock import AsyncMock, patch

import pytest
from rich.console import Console

import probos
from probos.cognitive import agent_mode as agent_mode_module
from probos.cognitive.agent_mode import open_plan_mode_reply_gate, read_turn_agent_mode
from probos.cognitive.commands.mode_command import _LOOP_OFF_NOTE, handle_mode_command
from probos.cognitive.episodic_mock import MockEpisodicMemory
from probos.config import DmAgenticConfig
from probos.experience.commands.session import SessionManager
from probos.routers.thread_fanout import group_chat_fanout
from probos.threads import ChatThreadStore
from probos.threads.agent_mode import AgentModeRecordError, parse_agent_mode_record
from probos.types import EPISODE_PLAN_MODE_KEY, IntentResult, episode_ran_in_plan_mode
from probos.workforce import WorkItemStore
from tests.test_ad1156_plan_execute_mode import (
    _AGENT,
    _EventLog,
    _Grants,
    _ScriptedLLM,
    _Tool,
    _chat_request,
    _dm_agent,
    _dm_turn,
    _offered,
    _raw_metadata,
    _registry,
    _route_runtime,
    _runtime,
    _write_raw_metadata,
)
from tests.test_ad1156_plan_mode_containment import _write_column
from tests.test_ad1156_plan_mode_learning import _engine, _trust
from tests.test_ad933_group_chat_escalation import _CREATE_TASK_REPLY, _build_env

_PLAN_TEXT = "PLAN: 1. Read the figures. 2. Draft the report."
_HEAD_SESSION_KEYS = ["intent", "success", "response", "session_type", "callsign", "agent_type"]
_BOTH = ["file_writer", "http_fetch"]
# What a session turn is offered: the two tools, and the mesh's read tools, which
# an intent bus arms. Plan mode withholds the writer.
_EXEC_OFFER = ["file_writer", "http_fetch", "read_page", "web_search"]
_PLAN_OFFER = ["http_fetch", "read_page", "web_search"]
_NOT_ONE_TO_ONE = (
    "Plan and execute modes apply to a one-to-one conversation with an agent; "
    "this conversation's mode is unchanged."
)


@pytest.fixture
def store(tmp_path: Path) -> ChatThreadStore:
    ticks = itertools.count(1_000)
    return ChatThreadStore(tmp_path / "threads.db", clock=lambda: float(next(ticks)))


def _modes(*, loop: bool = True, modes: bool = True) -> Any:
    return SimpleNamespace(config=SimpleNamespace(
        dm_agentic=DmAgenticConfig(enabled=loop, agent_modes_enabled=modes),
    ))


# ── 1. the CLI session ──────────────────────────────────────────────────────


class _AgentBus:
    """Delivers the session's intent to a real agent turn, as the intent bus would:
    with the thread the intent carries, which is none, and its params, which name the
    session gate's thread (A-6). Records the params sent (without the history), what
    the model was offered and its system prompt; runs ``before`` once the session has
    sent and before the agent's turn, and ``during`` after the turn and before the
    answer returns."""

    def __init__(
        self, runtime: Any, during: Callable[[], Any] | None, before: Callable[[], Any] | None = None,
    ) -> None:
        self._runtime = runtime
        self._during = during
        self._before = before
        self.offers: list[list[str]] = []
        self.prompts: list[str] = []
        self.sent: list[dict[str, Any]] = []

    async def send(self, intent: Any) -> IntentResult:
        self.sent.append({k: v for k, v in intent.params.items() if k != "session_history"})
        if self._before is not None:
            self._before()
        llm = _ScriptedLLM([_PLAN_TEXT])
        decision = await _dm_agent(self._runtime, llm)._decide_via_llm({
            "intent": intent.intent, "params": dict(intent.params), "thread_id": intent.thread_id or "",
        })
        self.offers.append(_offered(llm.requests[0]))
        self.prompts.append(llm.requests[0].system_prompt)
        if self._during is not None:
            self._during()
        return IntentResult(intent_id=intent.id, agent_id=_AGENT, success=True, result=decision["llm_output"])


def _session_runtime(
    store: ChatThreadStore, memory: MockEpisodicMemory, *, modes: bool,
    during: Callable[[], Any] | None = None, before: Callable[[], Any] | None = None,
) -> Any:
    runtime = _runtime(
        _registry(_Tool("http_fetch"), _Tool("file_writer")), _Grants(_BOTH),
        cfg=DmAgenticConfig(enabled=True, max_iterations=4, agent_modes_enabled=modes), store=store,
    )
    runtime.episodic_memory = memory
    runtime.intent_bus = _AgentBus(runtime, during, before)
    return runtime


def _session() -> SessionManager:
    session = SessionManager()
    session.callsign, session.agent_id, session.agent_type, session.department = (
        "Ezri", _AGENT, "counselor", "medical",
    )
    session._sovereign_id = _AGENT  # set by handle_at_parsed, which the test skips
    return session


@pytest.mark.parametrize(
    ("modes", "mode", "offer", "marked", "trust"),
    [
        (True, "plan", _PLAN_OFFER, True, None),
        (True, "execute", _EXEC_OFFER, False, (2.1, 2.0)),
        (False, "plan", _EXEC_OFFER, False, (2.1, 2.0)),
    ],
    ids=["plan", "execute", "modes-off-with-a-plan-record"],
)
async def test_a_session_turn_plan_mode_governed_is_marked_and_earns_no_trust(
    store: ChatThreadStore, modes: bool, mode: str, offer: list[str], marked: bool,
    trust: tuple[float, float] | None,
) -> None:
    memory = MockEpisodicMemory(relevance_threshold=0.3)
    runtime = _session_runtime(store, memory, modes=modes)
    thread = store.get_or_create_default_for_agent(_AGENT, "Ezri")
    store.set_agent_mode(thread.id, mode, changed_by="captain")
    session = _session()

    for text in ("Plan the quarterly report.", "And the budget?"):
        await session.handle_message(text, runtime, Console(file=io.StringIO()))
    episodes = await memory.recent(10)
    engine, _, network = _engine(memory)
    adjustments = engine._consolidate_trust(episodes)

    # The premise: the session's turn ran under its agent's default thread's mode.
    assert runtime.intent_bus.offers == [offer, offer]
    # What the real trust consolidation made of the session's two episodes.
    assert (adjustments, _trust(network, _AGENT)) == ((0, None) if marked else (1, trust))
    assert len(episodes) == 2
    for episode in episodes:
        assert list(episode.outcomes[0]) == [*_HEAD_SESSION_KEYS, *([EPISODE_PLAN_MODE_KEY] if marked else [])]
        assert episode.outcomes[0]["response"] == _PLAN_TEXT
        assert episode_ran_in_plan_mode(episode) is marked


@pytest.mark.parametrize(
    ("before", "during", "marked"),
    [("execute", "plan", True), ("plan", "execute", True), ("execute", None, False)],
    ids=["plan-lands-mid-turn", "execute-lands-mid-turn", "execute-throughout"],
)
async def test_a_session_turn_is_marked_when_plan_mode_came_or_went_mid_turn(
    store: ChatThreadStore, before: str, during: str | None, marked: bool,
) -> None:
    memory = MockEpisodicMemory(relevance_threshold=0.3)
    thread = store.get_or_create_default_for_agent(_AGENT, "Ezri")
    store.set_agent_mode(thread.id, before, changed_by="captain")
    switch = (lambda: store.set_agent_mode(thread.id, during, changed_by="captain")) if during else None
    runtime = _session_runtime(store, memory, modes=True, during=switch)

    await _session().handle_message("Plan it.", runtime, Console(file=io.StringIO()))
    [episode] = await memory.recent(1)

    assert runtime.intent_bus.offers == [_PLAN_OFFER if before == "plan" else _EXEC_OFFER]
    assert episode_ran_in_plan_mode(episode) is marked


class _Untouchable:
    """A thread store the session must not touch."""

    def __getattr__(self, name: str) -> Any:
        raise AssertionError(f"the session touched the thread store ({name}) with modes or the loop off")


class _Unresolvable:
    def get_or_create_default_for_agent(self, agent_id: str, agent_callsign: str) -> Any:
        raise RuntimeError("database is locked")

    def get_thread(self, thread_id: str) -> Any:
        raise AssertionError("an unresolved default thread is never read")


def test_the_session_gate_reads_the_default_thread_only_with_modes_the_loop_and_a_store(
    store: ChatThreadStore, caplog: pytest.LogCaptureFixture,
) -> None:
    from probos.cognitive.agent_mode import open_plan_mode_session_gate  # new in A-5

    assert open_plan_mode_session_gate(_modes(modes=False), _Untouchable(), _AGENT, "Ezri") is None
    assert open_plan_mode_session_gate(_modes(loop=False), _Untouchable(), _AGENT, "Ezri") is None
    assert open_plan_mode_session_gate(_modes(), None, _AGENT, "Ezri") is None

    thread = store.get_or_create_default_for_agent(_AGENT, "Ezri")
    unset = open_plan_mode_session_gate(_modes(), store, _AGENT, "Ezri")
    store.set_agent_mode(thread.id, "plan", changed_by="captain")
    planned = open_plan_mode_session_gate(_modes(), store, _AGENT, "Ezri")
    with caplog.at_level(logging.WARNING, logger="probos.cognitive.agent_mode"):
        held = open_plan_mode_session_gate(_modes(), _Unresolvable(), _AGENT, "Ezri")

    assert unset is not None and not unset.planned_at_dispatch
    assert planned is not None and planned.planned_at_dispatch and planned.withholds()
    assert held is not None and held.planned_at_dispatch and held.withholds()
    assert "could not be resolved" in caplog.text


def _locked(agent_id: str, agent_callsign: str) -> Any:
    raise RuntimeError("database is locked")


@pytest.mark.parametrize("record", ["plan", "execute"])
async def test_a_session_turn_is_held_in_plan_mode_when_its_default_thread_cannot_be_resolved(
    store: ChatThreadStore, monkeypatch: pytest.MonkeyPatch, record: str,
) -> None:
    # The review's first reproduction: a persisted record, then a default-thread lookup
    # that raises -- for the session's gate and for the agent's own lookup alike.
    memory = MockEpisodicMemory(relevance_threshold=0.3)
    thread = store.get_or_create_default_for_agent(_AGENT, "Ezri")
    store.set_agent_mode(thread.id, record, changed_by="captain")
    runtime = _session_runtime(store, memory, modes=True)
    monkeypatch.setattr(store, "get_or_create_default_for_agent", _locked)

    await _session().handle_message("Plan it.", runtime, Console(file=io.StringIO()))
    [episode] = await memory.recent(1)

    # The mode cannot be confirmed, so the agent's turn is held in plan mode whatever
    # the record says: the staged candidate offered it every tool here.
    assert runtime.intent_bus.offers == [_PLAN_OFFER]
    assert "## Conversation mode: plan (held)" in runtime.intent_bus.prompts[0]
    assert episode_ran_in_plan_mode(episode)
    # How: the session sent the route's plan floor, and no thread, since it has none.
    assert runtime.intent_bus.sent == [
        {"text": "Plan it.", "from": "captain", "session": True, "agent_mode_floor": "plan"},
    ]


@pytest.mark.parametrize(
    ("record", "before", "offer"),
    # A-9 repoint of the second case (A-6 had _EXEC_OFFER): the thread became a group
    # before the agent read it, and the record there holds the turn (A-5 read no mode).
    [("plan", "joins", _PLAN_OFFER), ("execute", "joins", _PLAN_OFFER), ("plan", "execute", _PLAN_OFFER)],
    ids=["plan-then-a-participant-joins", "execute-then-a-participant-joins", "plan-then-execute-before-the-turn"],
)
async def test_a_session_turn_runs_on_the_thread_its_gate_read_and_under_its_floor(
    store: ChatThreadStore, record: str, before: str, offer: list[str],
) -> None:
    # The review's second reproduction: the gate reads the default thread, then it gains
    # a participant before the agent's turn looks for its default thread.
    memory = MockEpisodicMemory(relevance_threshold=0.3)
    thread = store.get_or_create_default_for_agent(_AGENT, "Ezri")
    store.set_agent_mode(thread.id, record, changed_by="captain")
    change = (
        (lambda: store.add_participant(thread.id, "science-dax")) if before == "joins"
        else (lambda: store.set_agent_mode(thread.id, "execute", changed_by="captain"))
    )
    runtime = _session_runtime(store, memory, modes=True, before=change)

    await _session().handle_message("Plan it.", runtime, Console(file=io.StringIO()))
    [episode] = await memory.recent(1)

    # In plan mode at least when the gate read plan mode; after execute, a thread that
    # became a group holds the turn in plan mode too (A-9: the record governs no turn of
    # this agent on a group; A-5 read no mode there, so every tool).
    assert runtime.intent_bus.offers == [offer]
    # The agent's turn ran on the gate's thread: no second default thread was made.
    assert [t.id for t in store.list_threads()] == [thread.id]
    # The record changed between the gate's two reads, so plan mode may have governed.
    assert episode_ran_in_plan_mode(episode)
    assert [sent.get("thread_id") for sent in runtime.intent_bus.sent] == [thread.id]


@pytest.mark.parametrize(
    ("modes", "with_store", "offer"),
    [(True, True, ["http_fetch"]), (True, False, _BOTH), (False, True, _BOTH)],
    ids=["modes-on", "modes-on-without-a-store", "modes-off"],
)
async def test_a_turn_whose_agent_cannot_resolve_its_thread_is_held_in_plan_mode(
    store: ChatThreadStore, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
    modes: bool, with_store: bool, offer: list[str],
) -> None:
    # A turn sent with no thread -- as an AD-743 follow-up, a channel or the federation
    # bridge sends one -- whose agent's own default-thread lookup raises.
    thread = store.get_or_create_default_for_agent(_AGENT, "Ezri")
    store.set_agent_mode(thread.id, "plan", changed_by="captain")
    monkeypatch.setattr(store, "get_or_create_default_for_agent", _locked)
    runtime = _runtime(
        _registry(_Tool("http_fetch"), _Tool("file_writer")), _Grants(_BOTH),
        cfg=DmAgenticConfig(enabled=True, max_iterations=4, agent_modes_enabled=modes),
        store=store if with_store else None,
    )
    llm = _ScriptedLLM(["A plan."])

    with caplog.at_level(logging.WARNING, logger="probos.cognitive.cognitive_agent"):
        await _dm_agent(runtime, llm)._decide_via_llm({"intent": "direct_message", "params": {"text": "Plan it."}})

    # Held only when the modes are on and a store could not resolve the thread; with no
    # store, or with the modes off, the turn runs as it did before AD-1156.
    assert _offered(llm.requests[0]) == offer
    held = offer == ["http_fetch"]
    assert ("## Conversation mode: plan (held)" in llm.requests[0].system_prompt) is held
    assert ("could not be resolved, so its mode cannot be confirmed" in caplog.text) is held


# ── 2. a thread that is not one-to-one ──────────────────────────────────────


async def test_a_converted_group_thread_says_no_mode_applies_while_its_group_replies_act(tmp_path: Path) -> None:
    items = WorkItemStore(db_path=":memory:")
    await items.start()
    try:
        store, runtime = _build_env(
            tmp_path, agents={"yeo1": "scout", "scout1": "counselor"},
            replies={"yeo1": _CREATE_TASK_REPLY, "scout1": "Standing by, Captain."},
            callsigns={"scout": "Yeo", "counselor": "Scout"}, work_item_store=items,
        )
        thread = store.get_or_create_default_for_agent("yeo1", "Yeo")
        planned = await handle_mode_command(
            "/mode plan", thread=thread, agent_id="yeo1", store=store, loop_enabled=True,
        )
        grouped = store.add_participant(thread.id, "scout1")
        status = await handle_mode_command("/mode", thread=grouped, agent_id="yeo1", store=store, loop_enabled=True)
        captain = store.append_message(thread.id, author_id="captain", role="captain", body="handle it")
        await group_chat_fanout(runtime, thread.id, captain_body="handle it", captain_msg=captain)
        opened = await items.list_work_items()
        solo = store.remove_participant(thread.id, "scout1")
        again = await handle_mode_command("/mode", thread=solo, agent_id="yeo1", store=store, loop_enabled=True)
    finally:
        await items.stop()

    assert planned["applied"] == "plan"
    # Converted, the thread keeps its record, but the Captain is told what the group
    # path does: no mode applies and the replies are not held ...
    assert grouped.metadata["agent_mode"]["mode"] == "plan"
    # A-8 repoint: a record governs again only once its thread is one-to-one with the
    # agent it was set for, so /mode says so (A-5 said "if it becomes one-to-one").
    # A-9 repoint: the group's replies are still not held, but a one-to-one turn of this
    # agent that meets the record here is held in plan mode, and /mode says that too (A-5
    # and A-8 said no mode applied here at all, and such a turn ran with every tool).
    assert status["response"] == (
        "Plan and execute modes apply only to a one-to-one conversation with an agent. "
        "This conversation is not one-to-one, so its group replies are not held, but this "
        "agent's own turns here are held in plan mode: it drafts a plan without carrying "
        "it out. Its stored plan mode (revision 1) applies again only if it becomes "
        "one-to-one with the agent it was set for."
    )
    assert (status["applied"], status["agent_mode"]) == (None, None)
    # ... and the group's reply did act: its [CREATE_TASK] opened a work item.
    assert [item.title for item in opened] == ["Sensor sweep"]
    # One-to-one again, the record governs again, and /mode says so.
    assert again["response"].startswith("This conversation is in plan mode (revision 1).")
    assert again["agent_mode"]["mode"] == "plan"
    assert read_turn_agent_mode(store, thread.id, agent_id="yeo1").mode == "plan"


@pytest.mark.parametrize(
    ("participants", "governs"),
    [([_AGENT], True), ([_AGENT, "science-dax"], False), ([_AGENT, "captain"], False), ([], False)],
    ids=["one-to-one", "group", "agent-and-captain", "no-participants"],
)
def test_a_record_governs_only_a_one_to_one_thread(
    store: ChatThreadStore, participants: list[str], governs: bool,
) -> None:
    # A-6 repoint (A-5 wrote the record on each thread directly): the writer now refuses
    # a thread that is not one-to-one, so a record reaches one the only way it can -- set
    # while the thread is one-to-one, which it then stops being.
    thread = store.create_thread(title="Room", participants=[_AGENT])
    store.set_agent_mode(thread.id, "plan", changed_by="captain")
    for extra in participants[1:]:
        store.add_participant(thread.id, extra)
    if not participants:
        store.remove_participant(thread.id, _AGENT)
    assert store.get_thread(thread.id).participants == participants

    turn = read_turn_agent_mode(store, thread.id, agent_id=_AGENT)
    gate = open_plan_mode_reply_gate(_modes(), store, store.get_thread(thread.id), agent_id=_AGENT)

    # A-9 repoint (A-5 read the record as dormant off a one-to-one thread, so a turn of
    # this agent there ran with every tool and its reply acted): the record still governs
    # only the one-to-one thread, and anywhere else it holds the turn, named but not applied.
    assert turn is not None and turn.mode == "plan"
    if governs:
        assert turn.record is not None and turn.unapplied is None
    else:
        assert turn.held and turn.unapplied is not None and turn.unapplied.agent_id == _AGENT
    assert gate is not None and gate.withholds() is True


def test_a_thread_whose_participants_are_unknown_keeps_its_record(store: ChatThreadStore) -> None:
    thread = store.get_or_create_default_for_agent(_AGENT, "Ezri")
    store.set_agent_mode(thread.id, "plan", changed_by="captain")

    class _NoParticipants:
        def get_thread(self, thread_id: str) -> Any:
            return SimpleNamespace(metadata=store.get_thread(thread_id).metadata)

    turn = read_turn_agent_mode(_NoParticipants(), thread.id, agent_id=_AGENT)

    # A-9 repoint (A-5 and A-8 let unknown participants keep the record governing, so an
    # execute record there applied to any agent's turn): unknown participants cannot show
    # that this agent is the one participant, so the record holds the turn and is named.
    assert turn is not None and turn.mode == "plan" and turn.held
    assert turn.unapplied == parse_agent_mode_record(store.get_thread(thread.id).metadata["agent_mode"])
    # A-9: only `/mode` status still asks whether a thread is dormant, and a thread whose
    # participants are unknown is not one, so status never calls it a group (A-5, A-8).
    assert agent_mode_module.agent_mode_is_dormant(_NoParticipants().get_thread(thread.id)) is False


_GROUP_FREE = (
    "Plan and execute modes apply only to a one-to-one conversation with an agent. "
    "This conversation is not one-to-one, so no mode applies to it and its replies "
    "are not held."
)
_GROUP_HELD = (
    "Plan and execute modes apply only to a one-to-one conversation with an agent. "
    "This conversation is not one-to-one, so its group replies are not held, but this "
    "agent's own turns here are held in plan mode: it drafts a plan without carrying it out."
)


@pytest.mark.parametrize(
    ("stored", "loop", "expected", "held"),
    [
        ("nothing", True, _GROUP_FREE, False),
        # A-9 repoint (A-5 said the agent would be held only once the thread became
        # one-to-one): a turn of this agent there is held now, as the reader holds it.
        ("undecodable", True, _GROUP_HELD + " Its stored mode record cannot be read.", True),
        # A-8 repoint: the record applies again only with the agent it was set for.
        # A-9 repoint: and it holds this agent's turns there meanwhile.
        ("plan", False, _GROUP_HELD + " Its stored plan mode (revision 1) applies again only if "
                        "it becomes one-to-one with the agent it was set for." + _LOOP_OFF_NOTE, True),
    ],
    ids=["no-record", "undecodable-column", "plan-record-with-the-loop-off"],
)
async def test_mode_on_a_thread_that_is_not_one_to_one_names_only_what_it_stores(
    store: ChatThreadStore, stored: str, loop: bool, expected: str, held: bool,
) -> None:
    # A-6 repoint (A-5 created the group and then wrote the plan record on it): the
    # writer refuses a group thread, so the record is set while the thread is one-to-one
    # and a second agent then joins.
    thread = store.create_thread(title="Room", participants=[_AGENT])
    if stored == "undecodable":
        _write_column(store, thread.id, "not json")
    elif stored == "plan":
        store.set_agent_mode(thread.id, "plan", changed_by="captain")
    store.add_participant(thread.id, "science-dax")

    status = await handle_mode_command(
        "/mode", thread=store.get_thread(thread.id), agent_id=_AGENT, store=store, loop_enabled=loop,
    )

    assert status["response"] == expected
    assert (status["applied"], status["agent_mode"]) == (None, None)
    # A-9 repoint (A-5: "dormant in every case: even a column that does not decode holds no
    # turn here"): with no record a turn runs as before; with one, readable or not, a turn
    # of this agent here is held, as /mode says.
    turn = read_turn_agent_mode(store, thread.id, agent_id=_AGENT)
    assert (turn is not None and turn.held) is held


@pytest.mark.parametrize(
    ("then", "now", "expected"),
    [
        ("group", "one-to-one", "This conversation is in plan mode (revision 1)."),
        ("one-to-one", "group", "Plan and execute modes apply only to a one-to-one conversation with an agent."),
    ],
    ids=["read-as-a-group-now-one-to-one", "read-as-one-to-one-now-a-group"],
)
async def test_mode_status_reports_the_participants_as_they_are_when_it_runs(
    store: ChatThreadStore, then: str, now: str, expected: str,
) -> None:
    thread = store.get_or_create_default_for_agent(_AGENT, "Ezri")
    store.set_agent_mode(thread.id, "plan", changed_by="captain")
    if then == "group":
        store.add_participant(thread.id, "science-dax")
    routed = store.get_thread(thread.id)  # the route's copy of the thread
    if now == "group":
        store.add_participant(thread.id, "science-dax")
    else:
        store.remove_participant(thread.id, "science-dax")

    status = await handle_mode_command("/mode", thread=routed, agent_id=_AGENT, store=store, loop_enabled=True)

    # The review's reproduction said no mode applies while a turn read plan mode.
    assert status["response"].startswith(expected)
    turn = read_turn_agent_mode(store, thread.id, agent_id=_AGENT)
    # A-9: a held turn names no governing record, and status reports none.
    assert status["agent_mode"] == (None if turn is None or turn.record is None else turn.record.to_dict())


async def test_mode_refuses_a_thread_that_stopped_being_one_to_one_after_the_route_read_it(
    store: ChatThreadStore,
) -> None:
    thread = store.get_or_create_default_for_agent(_AGENT, "Ezri")
    store.set_agent_mode(thread.id, "plan", changed_by="captain")
    routed = store.get_thread(thread.id)  # one-to-one when the route read it
    store.add_participant(thread.id, "science-dax")
    events = _EventLog()

    result = await handle_mode_command(
        "/mode execute", thread=routed, agent_id=_AGENT, store=store, loop_enabled=True, event_log=events,
    )

    # The review's reproduction wrote revision 2 against the stale copy.
    assert store.get_thread(thread.id).metadata["agent_mode"]["revision"] == 1
    assert result["response"] == _NOT_ONE_TO_ONE
    assert (result["applied"], result["agent_mode"]) == (None, None)
    assert events.rows == []
    assert store.list_messages(thread.id)[-1].body == _NOT_ONE_TO_ONE


async def test_mode_refuses_a_thread_whose_one_participant_was_replaced_after_the_route_read_it(
    store: ChatThreadStore, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The review's interleaving: the handler checks the route's copy of Ezri's thread,
    # and Dax replaces Ezri as its one participant just before the writer runs.
    async def _execute(target: ChatThreadStore, *, swap: bool) -> tuple[str, dict[str, Any], _EventLog]:
        thread = target.get_or_create_default_for_agent(_AGENT, "Ezri")
        target.set_agent_mode(thread.id, "plan", changed_by="captain")
        routed = target.get_thread(thread.id)  # the route's copy: one-to-one with Ezri
        writer = target.set_agent_mode
        swapped: list[str] = []

        def _replace_then_write(*args: Any, **kwargs: Any) -> Any:
            if swap:
                target.add_participant(thread.id, "science-dax")
                target.remove_participant(thread.id, _AGENT)
                swapped.append(thread.id)
            return writer(*args, **kwargs)

        monkeypatch.setattr(target, "set_agent_mode", _replace_then_write)
        events = _EventLog()
        result = await handle_mode_command(
            "/mode execute", thread=routed, agent_id=_AGENT, store=target, loop_enabled=True, event_log=events,
        )
        assert swapped == ([thread.id] if swap else [])
        return thread.id, result, events

    # The premise: the same setup without the swap takes the same command, at revision 2.
    control = ChatThreadStore(tmp_path / "control.db", clock=lambda: 2_000.0)
    control_id, applied, applied_events = await _execute(control, swap=False)
    assert applied["applied"] == "execute"
    assert control.get_thread(control_id).metadata["agent_mode"]["revision"] == 2
    assert len(applied_events.rows) == 1

    thread_id, result, events = await _execute(store, swap=True)

    # The review's reproduction approved execution for Dax, at revision 2.
    assert store.get_thread(thread_id).participants == ["science-dax"]
    record = store.get_thread(thread_id).metadata["agent_mode"]
    assert (record["mode"], record["revision"]) == ("plan", 1)
    assert result["response"] == _NOT_ONE_TO_ONE
    assert (result["applied"], result["agent_mode"]) == (None, None)
    assert events.rows == []
    # A-8 repoint (A-7 asserted that Dax's next turn read Ezri's plan record, which followed
    # its thread): the record names Ezri, so Dax's next turn does not read it -- neither the
    # execute the review approved nor Ezri's plan. A-9 repoint (A-8 asserted no mode): Dax's
    # turn is held in plan mode, the record named but not applied.
    turn = read_turn_agent_mode(store, thread_id, agent_id="science-dax")
    assert turn is not None and turn.held and turn.unapplied.agent_id == _AGENT


@pytest.mark.parametrize(
    ("participants", "writes"),
    [([_AGENT], True), ([_AGENT, "science-dax"], False), ([], False)],
    ids=["one-to-one", "group", "no-participants"],
)
def test_the_writer_sets_a_mode_only_on_a_thread_with_one_participant(
    store: ChatThreadStore, participants: list[str], writes: bool,
) -> None:
    thread = store.create_thread(title="Room", participants=participants)
    before = _raw_metadata(store, thread.id)

    if writes:
        assert store.set_agent_mode(thread.id, "plan", changed_by="captain").changed
        return
    with pytest.raises(ValueError) as refused:
        store.set_agent_mode(thread.id, "plan", changed_by="captain")
    from probos.threads.agent_mode import AgentModeNotOneToOneError  # new in A-6

    assert refused.type is AgentModeNotOneToOneError
    assert _raw_metadata(store, thread.id) == before


@pytest.mark.parametrize(
    ("named", "writes"),
    [(_AGENT, True), ("science-dax", False), (None, True)],
    ids=["the-agent-addressed", "another-agent", "no-agent-named"],
)
def test_the_writer_sets_a_mode_only_for_the_named_participant(
    store: ChatThreadStore, named: str | None, writes: bool,
) -> None:
    thread = store.create_thread(title="Room", participants=[_AGENT])
    before = _raw_metadata(store, thread.id)
    # With no agent named the keyword is left out, as every caller but /mode leaves it.
    kwargs = {} if named is None else {"expected_participant": named}

    if writes:
        assert store.set_agent_mode(thread.id, "plan", changed_by="captain", **kwargs).changed
        return
    with pytest.raises(ValueError) as refused:
        store.set_agent_mode(thread.id, "plan", changed_by="captain", **kwargs)
    from probos.threads.agent_mode import AgentModeNotOneToOneError  # new in A-6

    assert refused.type is AgentModeNotOneToOneError
    assert _raw_metadata(store, thread.id) == before


async def test_mode_refuses_a_thread_that_is_one_to_one_with_another_agent(store: ChatThreadStore) -> None:
    thread = store.get_or_create_default_for_agent("science-dax", "Dax")

    result = await handle_mode_command("/mode plan", thread=thread, agent_id=_AGENT, store=store, loop_enabled=True)

    # A-7: the handler refuses on the route's copy, and the writer also checks, inside its
    # transaction, that the one participant is this agent.
    assert result["response"] == _NOT_ONE_TO_ONE
    assert "agent_mode" not in store.get_thread(thread.id).metadata


async def test_mode_status_reports_a_failure_when_the_thread_cannot_be_read(
    store: ChatThreadStore, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
) -> None:
    thread = store.get_or_create_default_for_agent(_AGENT, "Ezri")
    store.set_agent_mode(thread.id, "plan", changed_by="captain")

    def _unreadable(thread_id: str) -> Any:
        raise RuntimeError("database is locked")

    monkeypatch.setattr(store, "get_thread", _unreadable)
    with caplog.at_level(logging.WARNING, logger="probos.cognitive.commands.mode_command"):
        status = await handle_mode_command("/mode", thread=thread, agent_id=_AGENT, store=store, loop_enabled=True)

    # Status reads the thread when it runs; a store that cannot answer fails the command,
    # as a failing write does, rather than describing a record it could not read.
    assert status["response"] == "Mode command failed; please try again."
    assert (status["applied"], status["agent_mode"]) == (None, None)
    assert "/mode failed" in caplog.text


async def test_the_agents_real_turn_on_a_converted_thread_is_held_until_it_is_one_to_one_again(
    store: ChatThreadStore,
) -> None:
    # A-9 rename and repoint (A-5: ..._runs_as_with_no_mode, offered every tool on the
    # group): the record governs no turn of this agent on the group, and a turn of it that
    # meets the record there -- as one in flight when the thread changed does -- is held in
    # plan mode, told that the stored mode was not set for it there.
    thread = store.get_or_create_default_for_agent(_AGENT, "Ezri")
    store.set_agent_mode(thread.id, "plan", changed_by="captain")
    runtime = _runtime(
        _registry(_Tool("http_fetch"), _Tool("file_writer")), _Grants(_BOTH),
        cfg=DmAgenticConfig(enabled=True, max_iterations=4, agent_modes_enabled=True), store=store,
    )
    offers: list[list[str]] = []
    for change in (
        None,
        lambda: store.add_participant(thread.id, "science-dax"),
        lambda: store.remove_participant(thread.id, "science-dax"),
    ):
        if change is not None:
            change()
        llm = _ScriptedLLM(["A plan."])
        await _dm_turn(runtime, llm, thread.id, "Plan it.")
        offers.append((_offered(llm.requests[0]), "was not set for you here" in llm.requests[0].system_prompt))

    assert offers == [(["http_fetch"], False), (["http_fetch"], True), (["http_fetch"], False)]


# ── 3. A-8: a record is bound to the agent it was set for ─────────────────────

_DAX = "science-dax"
# A-9 (A-8's _OTHER_AGENT said no mode applied to this agent and that it worked as usual).
_UNAPPLIED = (
    "The stored {mode} mode (revision {revision}) applies only to the agent it was set for, "
    "while that agent is this conversation's one participant, so this agent is held in plan "
    "mode here: it drafts a plan without carrying it out."
)
_SET_OWN = " Send /mode plan or /mode execute to set this agent's own mode."


def _swap(store: ChatThreadStore, thread_id: str, old: str, new: str) -> None:
    """``new`` takes ``old``'s place as the thread's one participant, through the store's
    own participant API, as in the review's probe."""
    store.add_participant(thread_id, new)
    store.remove_participant(thread_id, old)
    assert store.get_thread(thread_id).participants == [new]


async def _turn_as(store: ChatThreadStore, thread_id: str, agent_id: str) -> tuple[list[str], str]:
    """One real turn of ``agent_id`` on the thread: what the model was offered, and its
    system prompt."""
    return await _turn_on(
        store, {"intent": "direct_message", "params": {"text": "Plan it."}, "thread_id": thread_id}, agent_id,
    )


async def _turn_on(store: ChatThreadStore, observation: dict[str, Any], agent_id: str) -> tuple[list[str], str]:
    """One real turn of ``agent_id`` on ``observation``, which names its thread as the
    surface that sent the turn does, or names none (A-9)."""
    runtime = _runtime(
        _registry(_Tool("http_fetch"), _Tool("file_writer")), _Grants(_BOTH),
        cfg=DmAgenticConfig(enabled=True, max_iterations=4, agent_modes_enabled=True), store=store,
    )
    llm = _ScriptedLLM(["A plan."])
    agent = _dm_agent(runtime, llm)
    agent.id = agent_id
    await agent._decide_via_llm(observation)
    return _offered(llm.requests[0]), llm.requests[0].system_prompt


async def _mode(store: ChatThreadStore, thread_id: str, message: str, agent_id: str, **kwargs: Any) -> dict[str, Any]:
    kwargs.setdefault("loop_enabled", True)
    return await handle_mode_command(
        message, thread=store.get_thread(thread_id), agent_id=agent_id, store=store, **kwargs,
    )


@pytest.mark.parametrize("loop", [True, False], ids=["loop-on", "loop-off"])
async def test_an_approval_for_one_agent_does_not_pass_to_another_that_takes_its_place(
    store: ChatThreadStore, loop: bool,
) -> None:
    # The review's probe: /mode execute succeeds for Ezri, then Dax takes her place as the
    # thread's one participant. Dax's next turn read execute, unheld, at revision 2.
    thread = store.get_or_create_default_for_agent(_AGENT, "Ezri")
    await _mode(store, thread.id, "/mode plan", _AGENT)
    approved = await _mode(store, thread.id, "/mode execute", _AGENT)
    # The premise: the approval was applied, and Ezri's turn reads it.
    assert (approved["applied"], approved["agent_mode"]["revision"]) == ("execute", 2)
    assert read_turn_agent_mode(store, thread.id, agent_id=_AGENT).mode == "execute"

    _swap(store, thread.id, _AGENT, _DAX)
    offer, prompt = await _turn_as(store, thread.id, _DAX)
    status = await _mode(store, thread.id, "/mode", _DAX, loop_enabled=loop)

    # A-9 repoint (A-8: Dax's turn read no mode and ran with every tool, its reply not
    # held): Dax's turn does not read Ezri's approval, and is held in plan mode -- the
    # read-only tools, and the held block saying the stored mode was not set for it -- and
    # its reply is held.
    assert offer == ["http_fetch"] and "was not set for you here" in prompt
    assert "## Conversation mode: execute" not in prompt
    turn = read_turn_agent_mode(store, thread.id, agent_id=_DAX)
    assert turn is not None and turn.held and turn.unapplied.agent_id == _AGENT
    gate = open_plan_mode_reply_gate(_modes(), store, store.get_thread(thread.id), agent_id=_DAX)
    assert gate is not None and gate.withholds() is True
    # The record is kept, unchanged, naming the agent it was set for.
    assert store.get_thread(thread.id).metadata["agent_mode"] == approved["agent_mode"]
    assert approved["agent_mode"]["agent_id"] == _AGENT
    # /mode in Dax's panel says Dax is held there, names the record, and says how to set
    # Dax's own mode.
    assert status["response"] == _UNAPPLIED.format(mode="execute", revision=2) + _SET_OWN + (
        "" if loop else _LOOP_OFF_NOTE
    )
    assert (status["applied"], status["agent_mode"]) == (None, None)


async def test_a_record_governs_again_once_its_agent_is_the_one_participant_again(
    store: ChatThreadStore,
) -> None:
    thread = store.get_or_create_default_for_agent(_AGENT, "Ezri")
    await _mode(store, thread.id, "/mode plan", _AGENT)
    await _mode(store, thread.id, "/mode execute", _AGENT)
    _swap(store, thread.id, _AGENT, _DAX)
    # Not Dax's while Dax is the one participant -- A-9 repoint (A-8 read no mode): Dax's
    # turn is held, the record named but not applied ...
    held = read_turn_agent_mode(store, thread.id, agent_id=_DAX)
    assert held is not None and held.held and held.unapplied.revision == 2

    _swap(store, thread.id, _DAX, _AGENT)
    offer, prompt = await _turn_as(store, thread.id, _AGENT)
    status = await _mode(store, thread.id, "/mode", _AGENT)

    # ... and Ezri's own approval governs her turns again, as the Captain left it.
    turn = read_turn_agent_mode(store, thread.id, agent_id=_AGENT)
    assert (turn.mode, turn.record.revision, turn.record.agent_id) == ("execute", 2, _AGENT)
    assert offer == _BOTH and "approving the plan drafted in plan mode" in prompt
    assert status["response"].startswith("This conversation is in execute mode (revision 2).")
    assert status["agent_mode"] == turn.record.to_dict()


async def test_a_plan_set_for_one_agent_holds_another_that_takes_its_place_as_unconfirmed(
    store: ChatThreadStore,
) -> None:
    # A-9 rename and repoint (A-8: ..._does_not_hold_another_that_takes_its_place, which
    # read no mode for Dax and offered every tool): a record that is not Dax's cannot say
    # what the Captain wants of Dax -- a turn of Dax admitted before the thread changed hands
    # may have been under Dax's own plan -- so Dax's turn is held in plan mode, told that the
    # stored mode was not set for it, rather than given Ezri's plan or every tool.
    thread = store.get_or_create_default_for_agent(_AGENT, "Ezri")
    await _mode(store, thread.id, "/mode plan", _AGENT)
    held_offer, _ = await _turn_as(store, thread.id, _AGENT)

    _swap(store, thread.id, _AGENT, _DAX)
    offer, prompt = await _turn_as(store, thread.id, _DAX)
    gate = open_plan_mode_reply_gate(_modes(), store, store.get_thread(thread.id), agent_id=_DAX)

    # The premise: Ezri's plan holds her turn to the read-only tools.
    assert held_offer == ["http_fetch"]
    assert offer == ["http_fetch"] and "was not set for you here" in prompt
    assert "## Conversation mode: plan\n" not in prompt, "Ezri's plan instructions are not Dax's"
    assert gate is not None and gate.withholds() is True


async def test_a_record_that_names_no_agent_holds_the_turn_in_plan_mode(
    store: ChatThreadStore, caplog: pytest.LogCaptureFixture,
) -> None:
    thread = store.get_or_create_default_for_agent(_AGENT, "Ezri")
    # An execute record in the shape before A-8, which cannot say whom it was set for.
    _write_raw_metadata(store, thread.id, {"agent_mode": {
        "mode": "execute", "revision": 1, "changed_at": 100.0, "changed_by": "captain", "previous": None,
    }})

    with caplog.at_level(logging.WARNING, logger="probos.cognitive.agent_mode"):
        turn = read_turn_agent_mode(store, thread.id, agent_id=_AGENT)
    offer, prompt = await _turn_as(store, thread.id, _AGENT)
    status = await _mode(store, thread.id, "/mode", _AGENT)

    # It does not parse, so it holds the turn in plan mode (A-2's rule).
    assert turn is not None and turn.held
    assert "does not parse (agent_mode_record_shape)" in caplog.text
    assert offer == ["http_fetch"] and "## Conversation mode: plan (held)" in prompt
    assert status["response"].startswith(
        "This conversation's mode record could not be read, so the agent is held in plan mode."
    )


@pytest.mark.parametrize(
    ("agent_id", "valid"),
    [
        (_AGENT, True), ("a" * 128, True),
        ("", False), ("   ", False), (7, False), (None, False), ([_AGENT], False), ("a" * 129, False),
    ],
    ids=["an-agent", "the-longest", "empty", "blank", "int", "none", "list", "too-long"],
)
def test_the_parser_accepts_only_a_record_that_names_an_agent(agent_id: Any, valid: bool) -> None:
    value = {
        "mode": "plan", "revision": 1, "changed_at": 100.0, "changed_by": "captain",
        "previous": None, "agent_id": agent_id,
    }

    if valid:
        assert parse_agent_mode_record(value).agent_id == agent_id
        return
    with pytest.raises(AgentModeRecordError, match="^agent_mode_record_agent_id$"):
        parse_agent_mode_record(value)


@pytest.mark.parametrize("mode", ["plan", "execute"])
async def test_mode_for_an_agent_that_took_anothers_place_starts_its_own_record(
    store: ChatThreadStore, mode: str,
) -> None:
    thread = store.get_or_create_default_for_agent(_AGENT, "Ezri")
    await _mode(store, thread.id, "/mode plan", _AGENT)
    _swap(store, thread.id, _AGENT, _DAX)
    events = _EventLog()

    result = await _mode(store, thread.id, f"/mode {mode}", _DAX, event_log=events)

    # Ezri's plan is not Dax's to continue: Dax's record starts at revision 1 with no
    # previous mode, so execute approves no plan Dax drafted, and plan is a change,
    # not "already in plan mode".
    record = store.get_thread(thread.id).metadata["agent_mode"]
    assert result["applied"] == mode
    assert (record["mode"], record["revision"], record["previous"]) == (mode, 1, None)
    assert "This approves the plan" not in result["response"]
    assert record["agent_id"] == _DAX and result["agent_mode"] == record
    assert len(events.rows) == 1
    assert read_turn_agent_mode(store, thread.id, agent_id=_DAX).record.agent_id == _DAX


@pytest.mark.parametrize("named", [True, False], ids=["the-agent-addressed", "no-agent-named"])
def test_the_writer_names_the_agent_its_record_is_set_for(store: ChatThreadStore, named: bool) -> None:
    thread = store.create_thread(title="Room", participants=[_DAX])
    kwargs = {"expected_participant": _DAX} if named else {}

    transition = store.set_agent_mode(thread.id, "plan", changed_by="captain", **kwargs)

    assert transition.record.agent_id == _DAX
    assert store.get_thread(thread.id).metadata["agent_mode"]["agent_id"] == _DAX


# ── 4. A-9: every read that decides a turn's mode names the turn's agent ────

_HELD_BLOCK = "## Conversation mode: plan (held)"
_NOT_SET_FOR_YOU = "was not set for you here"
_A9_REPLY = "Here is the plan, Captain: 1. gather the figures, 2. draft the report."


class _Admitted:
    """The one-to-one route over a real thread store, with a real agent turn behind the
    intent bus, on a thread made for the agent the route admits (the side-effects file's
    ``_Turns`` pattern). ``handover`` runs at the route's avatar refresh -- an await between
    the route admitting the thread and opening its reply gate, where the review's probe
    changed the thread -- and every gate the route opens is kept, to be asked."""

    def __init__(self, tmp_path: Path, admitted: str, *, modes: bool = True) -> None:
        self.rt = _route_runtime(tmp_path, modes=modes)
        self.rt.config.dm_agentic = DmAgenticConfig(enabled=True, max_iterations=4, agent_modes_enabled=modes)
        self.store: ChatThreadStore = self.rt.chat_thread_store
        self.admitted = admitted
        self.thread = self.store.create_thread(title="Planning", participants=[admitted])
        self.writer = _Tool("file_writer")
        agent_rt = _runtime(
            _registry(_Tool("http_fetch"), self.writer), _Grants(_BOTH),
            cfg=self.rt.config.dm_agentic, store=self.store,
        )
        self.llm = _ScriptedLLM([("file_writer", {"target": "report.md"}), _A9_REPLY])
        self.agent = _dm_agent(agent_rt, self.llm)
        self.agent.id = admitted
        self.sent: list[Any] = []
        self.gates: list[Any] = []
        self.handover: Callable[[], Any] | None = None
        self.rt.intent_bus.send = AsyncMock(side_effect=self._send)
        self.rt.registry.get.return_value.observe_self_avatar = AsyncMock(side_effect=self._handover)

    async def _handover(self) -> None:
        if self.handover is not None:
            await self.handover()

    async def _send(self, intent: Any, **_kwargs: Any) -> IntentResult:
        self.sent.append(intent)
        decision = await self.agent._decide_via_llm(await self.agent.perceive(intent))
        return IntentResult(
            intent_id=intent.id, agent_id=self.admitted, success=True, result=decision["llm_output"],
        )

    async def say(self, message: str) -> dict[str, Any]:
        from probos.routers import agents as agents_router

        opener = agents_router.open_plan_mode_reply_gate

        def _kept(*args: Any, **kwargs: Any) -> Any:
            self.gates.append(opener(*args, **kwargs))
            return self.gates[-1]

        request = _chat_request(message)
        request.thread_id = self.thread.id
        with (
            patch("probos.routers.agents.is_crew_agent", return_value=True),
            patch.object(agents_router, "open_plan_mode_reply_gate", _kept),
        ):
            return await agents_router.agent_chat(self.admitted, request, self.rt)


@pytest.mark.parametrize(
    ("admitted", "taker"), [(_DAX, _AGENT), (_AGENT, _DAX)], ids=["dax-admitted", "ezri-admitted"],
)
async def test_a_turn_admitted_for_one_agent_is_held_when_its_thread_changes_hands_before_the_gate(
    tmp_path: Path, admitted: str, taker: str,
) -> None:
    # The round-8 review's probe through the real route: the route admits the thread for
    # one agent, whose plan it stores; before the route opens its gate the other agent takes
    # the thread and the Captain sets execute there for it.
    vessel = _Admitted(tmp_path, admitted)
    planned = await vessel.say("/mode plan")

    async def _hand_over() -> None:
        _swap(vessel.store, vessel.thread.id, admitted, taker)
        await handle_mode_command(
            "/mode execute", thread=vessel.store.get_thread(vessel.thread.id), agent_id=taker,
            store=vessel.store, loop_enabled=True,
        )

    vessel.handover = _hand_over
    reply = await vessel.say("Get the quarterly report moving.")

    # The premise: the admitted agent's plan was set through the route, and when the gate
    # read the thread its one participant and its record were the other agent's: execute.
    assert planned["applied"] == "plan"
    stored = vessel.store.get_thread(vessel.thread.id)
    assert stored.participants == [taker]
    assert (stored.metadata["agent_mode"]["mode"], stored.metadata["agent_mode"]["agent_id"]) == ("execute", taker)
    # The staged candidate offered the admitted agent both tools with the execute block,
    # and its gate neither planned the turn nor withheld the reply. Every read holds it now:
    assert _offered(vessel.llm.requests[0]) == ["http_fetch"]
    prompt = vessel.llm.requests[0].system_prompt
    assert _HELD_BLOCK in prompt and _NOT_SET_FOR_YOU in prompt
    assert "## Conversation mode: execute" not in prompt
    assert vessel.writer.calls == []
    [gate] = vessel.gates
    assert gate.planned_at_dispatch is True and gate.withholds() is True
    assert vessel.sent[0].params["agent_mode_floor"] == "plan"
    assert reply["response"].startswith("Here is the plan")


@pytest.mark.parametrize("case", ["no-record", "own-execute", "modes-off"])
async def test_the_routes_turn_runs_as_before_when_no_other_agents_record_meets_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, case: str,
) -> None:
    decisions: list[str] = []
    decide = agent_mode_module.turn_agent_mode_of_thread

    def _counted(*args: Any, **kwargs: Any) -> Any:
        decisions.append(args[0])
        return decide(*args, **kwargs)

    monkeypatch.setattr(agent_mode_module, "turn_agent_mode_of_thread", _counted)
    vessel = _Admitted(tmp_path, _DAX, modes=case != "modes-off")
    if case == "own-execute":
        await vessel.say("/mode plan")
        await vessel.say("/mode execute")
    else:
        # The probe's hand-over with no record anywhere, or with the modes off, where /mode
        # is ordinary text, so the records are written by the one writer /mode calls.
        if case == "modes-off":
            vessel.store.set_agent_mode(vessel.thread.id, "plan", changed_by="captain", expected_participant=_DAX)

        async def _hand_over() -> None:
            _swap(vessel.store, vessel.thread.id, _DAX, _AGENT)
            if case == "modes-off":
                vessel.store.set_agent_mode(
                    vessel.thread.id, "execute", changed_by="captain", expected_participant=_AGENT,
                )

        vessel.handover = _hand_over
    decisions.clear()
    await vessel.say("Get the quarterly report moving.")

    prompt = vessel.llm.requests[0].system_prompt
    # As before A-9, and as at HEAD: every tool, the write made, no floor.
    assert _offered(vessel.llm.requests[0]) == _BOTH and len(vessel.writer.calls) == 1
    assert "agent_mode_floor" not in vessel.sent[0].params
    if case != "own-execute":
        assert vessel.store.get_thread(vessel.thread.id).participants == [_AGENT], "the hand-over ran"
    if case == "modes-off":
        # No gate, no mode block, and no decision taken at all.
        assert vessel.gates == [None] and "## Conversation mode" not in prompt
        assert decisions == []
        return
    [gate] = vessel.gates
    assert gate.planned_at_dispatch is False and gate.withholds() is False
    assert decisions, "the premise: with the modes on, every read is counted"
    if case == "own-execute":
        assert "## Conversation mode: execute" in prompt and "approving the plan drafted in plan mode" in prompt
    else:
        assert "## Conversation mode" not in prompt


@pytest.mark.parametrize("source", ["intent-thread", "params-thread", "default-thread"])
async def test_an_agent_reads_its_thread_for_itself_however_the_thread_reaches_it(
    store: ChatThreadStore, source: str,
) -> None:
    # Ezri's approval, on the thread each of BF-698's three sources resolves: the intent's
    # thread (the route, inline @callsign, a sanity-gate retry, an AD-1230 replay, AD-839),
    # the params' thread (the CLI session), or the agent's default thread (an AD-743
    # follow-up, a channel, the federation bridge, the yeoman, perception, a qualification
    # probe).
    thread = store.create_thread(title="Ezri", participants=[_AGENT])
    await _mode(store, thread.id, "/mode plan", _AGENT)
    await _mode(store, thread.id, "/mode execute", _AGENT)
    observation: dict[str, Any] = {"intent": "direct_message", "params": {"text": "Plan it."}}
    if source == "intent-thread":
        observation["thread_id"] = thread.id
    elif source == "params-thread":
        observation["params"]["thread_id"] = thread.id
    else:
        # The oldest thread whose one participant is Dax is Dax's default: Ezri's, once Dax
        # has taken her place.
        _swap(store, thread.id, _AGENT, _DAX)
        assert store.get_or_create_default_for_agent(_DAX, "Dax").id == thread.id

    offer, prompt = await _turn_on(store, observation, _DAX)

    # The staged candidate gave Dax Ezri's approval on the first two, where the thread was
    # Ezri's one-to-one, and every tool with no mode on the third (A-8's dormant record).
    assert offer == ["http_fetch"] and _NOT_SET_FOR_YOU in prompt
    assert "approving the plan" not in prompt


async def test_a_session_turn_is_held_when_its_thread_changes_hands_before_the_agent_reads_it(
    store: ChatThreadStore,
) -> None:
    memory = MockEpisodicMemory(relevance_threshold=0.3)
    thread = store.get_or_create_default_for_agent(_AGENT, "Ezri")

    def _hand_over() -> None:
        # After the session's gate read Ezri's thread (no record, so no floor) and before
        # Ezri's turn reads it: Dax takes the thread, and a plan for Dax is approved there.
        _swap(store, thread.id, _AGENT, _DAX)
        store.set_agent_mode(thread.id, "plan", changed_by="captain", expected_participant=_DAX)
        store.set_agent_mode(thread.id, "execute", changed_by="captain", expected_participant=_DAX)

    runtime = _session_runtime(store, memory, modes=True, before=_hand_over)
    await _session().handle_message("Plan it.", runtime, Console(file=io.StringIO()))
    [episode] = await memory.recent(1)

    # The premise: the session sent the turn on the thread its gate read, with no floor.
    assert runtime.intent_bus.sent == [
        {"text": "Plan it.", "from": "captain", "session": True, "thread_id": thread.id},
    ]
    # The staged candidate gave Ezri's turn Dax's approval: every tool, "approving the plan".
    assert runtime.intent_bus.offers == [_PLAN_OFFER]
    assert _NOT_SET_FOR_YOU in runtime.intent_bus.prompts[0]
    assert "approving the plan" not in runtime.intent_bus.prompts[0]
    assert episode_ran_in_plan_mode(episode)


@pytest.mark.parametrize(
    ("taker", "reader", "alone"),
    [(_DAX, _DAX, True), (_DAX, _AGENT, False)],
    ids=["another-agent-took-the-thread", "this-agent-left-the-thread"],
)
async def test_mode_status_names_a_record_that_governs_no_turn_of_this_agent(
    store: ChatThreadStore, taker: str, reader: str, alone: bool,
) -> None:
    thread = store.get_or_create_default_for_agent(_AGENT, "Ezri")
    await _mode(store, thread.id, "/mode plan", _AGENT)
    routed = store.get_thread(thread.id)  # the route's copy, one-to-one with Ezri
    _swap(store, thread.id, _AGENT, taker)

    status = await handle_mode_command("/mode", thread=routed, agent_id=reader, store=store, loop_enabled=True)

    # Status reads the thread as it is, and decides for the agent it addressed as that
    # agent's turn does: held, the record named. Only the one participant can set its own
    # mode there, so only it is told how. The staged candidate told Dax it worked as usual,
    # and told Ezri that her own record had been set for another agent.
    assert status["response"] == _UNAPPLIED.format(mode="plan", revision=1) + (_SET_OWN if alone else "")
    assert (status["applied"], status["agent_mode"]) == (None, None)


async def test_a_thread_that_is_gone_holds_the_turn_and_fails_mode_status(store: ChatThreadStore) -> None:
    thread = store.get_or_create_default_for_agent(_AGENT, "Ezri")
    await _mode(store, thread.id, "/mode plan", _AGENT)
    routed = store.get_thread(thread.id)  # the route's copy, before the thread went
    assert store.delete_thread(thread.id)

    status = await handle_mode_command("/mode", thread=routed, agent_id=_AGENT, store=store, loop_enabled=True)
    offer, prompt = await _turn_as(store, thread.id, _AGENT)

    # The staged candidate said "No mode is set" and ran the turn with every tool, though
    # the Captain's plan for this agent may have governed it when the route admitted it.
    assert status["response"] == "Mode command failed; please try again."
    assert (status["applied"], status["agent_mode"]) == (None, None)
    assert offer == ["http_fetch"] and _HELD_BLOCK in prompt


@pytest.mark.parametrize("agent", [None, "", 7], ids=["none", "blank", "not-a-str"])
def test_a_read_that_cannot_name_its_agent_is_held_by_any_record(store: ChatThreadStore, agent: Any) -> None:
    thread = store.get_or_create_default_for_agent(_AGENT, "Ezri")
    # With no record there is nothing to confirm, so the turn runs as before ...
    assert read_turn_agent_mode(store, thread.id, agent_id=agent) is None
    store.set_agent_mode(thread.id, "execute", changed_by="captain")

    turn = read_turn_agent_mode(store, thread.id, agent_id=agent)
    gate = open_plan_mode_reply_gate(_modes(), store, store.get_thread(thread.id), agent_id=agent)

    # ... and any record holds it: a record governs only a turn of the agent it names.
    assert turn is not None and turn.held and turn.unapplied.mode == "execute"
    assert gate is not None and gate.planned_at_dispatch and gate.withholds()


# Every call in src of a function that decides, or opens a gate that decides, a turn's
# mode, by module and name (A-9's census). A reader added later must name its agent and
# be added here.
_READER_CALLS: dict[tuple[str, str], int] = {
    ("cognitive/agent_mode.py", "PlanModeReplyGate"): 4,
    ("cognitive/agent_mode.py", "agent_mode_record_governs"): 1,
    ("cognitive/agent_mode.py", "open_plan_mode_reply_gate"): 1,
    ("cognitive/agent_mode.py", "read_turn_agent_mode"): 3,
    ("cognitive/agent_mode.py", "turn_agent_mode_of_thread"): 1,
    ("cognitive/cognitive_agent.py", "read_turn_agent_mode"): 1,
    ("cognitive/commands/mode_command.py", "turn_agent_mode_of_thread"): 2,
    ("cognitive/turn_promotion.py", "PlanModeReplyGate"): 1,
    ("experience/commands/session.py", "open_plan_mode_session_gate"): 1,
    ("routers/agents.py", "open_plan_mode_reply_gate"): 1,
    ("startup/finalize.py", "open_plan_mode_replay_gate"): 1,
}


def test_every_read_that_decides_a_turns_mode_names_its_agent() -> None:
    # Taken from the AST of every module under src/probos, so neither an import alias nor a
    # line break hides a call: each call names the turn's agent, and the calls are exactly
    # the ones A-9 enumerated.
    root = Path(probos.__file__).resolve().parent
    names = {name for _, name in _READER_CALLS}
    found: dict[tuple[str, str], int] = {}
    unnamed: list[str] = []
    for path in sorted(root.rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = func.id if isinstance(func, ast.Name) else func.attr if isinstance(func, ast.Attribute) else ""
            if name not in names:
                continue
            key = (path.relative_to(root).as_posix(), name)
            found[key] = found.get(key, 0) + 1
            # The session gate takes its agent positionally, its third argument (A-5).
            named = any(keyword.arg == "agent_id" for keyword in node.keywords) or (
                name == "open_plan_mode_session_gate" and len(node.args) >= 3
            )
            if not named:
                unnamed.append(f"{key[0]}:{node.lineno} {name}")

    assert unnamed == []
    assert found == _READER_CALLS
