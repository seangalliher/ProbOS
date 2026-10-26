"""AD-1341 S4 M2 (#1569): the stand-down gives each crew agent one bounded, optional turn and keeps what it writes.

The service runs for real over real Ship's Records (S1's ``_records``); an agent's turn is a stub ``ask``, the only
stand-in for a model. The vessel tests (S11 to S13b, S15) run ``stand_down_vessel`` over a real ``IntentBus`` whose
subscribers answer the Captain's message as a crew agent's model would, the in-memory ``MockEpisodicMemory`` and an
identity stub returning real ``IdentityRef`` values. S15 then runs the real ``probos reset`` (S1's ``_reset``), a later
crew's real Oracle (S1's ``_oracle_query``) and S3's real AD-754 citation check.
"""

from __future__ import annotations

import ast
import asyncio
import dataclasses
import json
import re
import subprocess
import time
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest
from rich.console import Console

import probos
from probos.api import _handle_slash_command
from probos.cognitive.cognitive_agent import CognitiveAgent
from probos.cognitive.episodic_mock import MockEpisodicMemory
from probos.cognitive.llm_client import BaseLLMClient
from probos.consensus.trust import TrustNetwork
from probos.experience.commands import commands_stand_down
from probos.experience.shell import ProbOSShell
from probos.identity_service import IdentityRef
from probos.knowledge.archive_promotion import plan_promotion
from probos.knowledge.erasure import ArchiveCitationsBlockErasure, ErasureManager
from probos.knowledge.lessons import (
    DECLINE_REPLY,
    EXIT_NOTE_CALLSIGN_MAX_CHARS,
    EXIT_NOTE_KEY,
    EXIT_NOTE_STATUS,
    EXIT_NOTES_DIR,
    LESSON_MAX_CHARS,
    LESSON_SECTIONS,
    exit_note_body,
    exit_note_path,
)
from probos.mesh.intent import IntentBus
from probos.mesh.signal import SignalManager
from probos.stand_down import (
    BOUNDED_TURN_PARAM,
    EPISODE_EXCERPT_CHARS,
    STAND_DOWN_CONCURRENCY,
    STAND_DOWN_TURN_SECONDS,
    CrewMember,
    StandDownRefused,
    TurnOutcome,
    crew_for_stand_down,
    exit_notes_prompt,
    run_stand_down,
    stand_down_vessel,
)
from probos.substrate.registry import AgentRegistry
from probos.threads import ChatThreadStore
from probos.types import Episode, IntentMessage, IntentResult, LLMResponse
from probos.workforce import WorkItemStore
from tests.test_ad1341_s1_reset_and_erase import (
    _SHIP,
    _archive_store,
    _config,
    _data_dir,
    _oracle_query,
    _records,
    _reset,
    _rows,
)
from tests.test_ad1341_s4_lessons import _DID, _LESSON, _deny_reading

_SRC = Path(probos.__file__).resolve().parent


def _member(
    agent_type: str = "surgeon", callsign: str = "Chapel", did: str = _DID, sovereign: str = "sov-surgeon",
) -> CrewMember:
    return CrewMember(
        agent_id=f"slot-{agent_type}", agent_type=agent_type, sovereign_id=sovereign, did=did, callsign=callsign,
    )


def _episodes(count: int, sovereign: str = "sov-surgeon") -> list[Episode]:
    """``count`` episodes of one agent, oldest first; each opens with far more than an excerpt's characters."""
    return [
        Episode(
            id=f"ep-{index:03d}",
            timestamp=1_790_000_000.0 + index,
            agent_ids=[sovereign],
            user_input=f"Night watch {index}: the coolant drift alarm cleared again. " + "Readings logged. " * 20,
        )
        for index in range(count)
    ]


def _reply(cites: str = "e1, e2") -> str:
    """A reply in the lessons format, with a preamble and a citations line that the note never keeps."""
    return f"Here are my notes.\n\n{_LESSON.render()}\nCites: {cites}\n"


async def _no_episodes(member: CrewMember) -> list[Episode]:
    return []


async def _run(records: Any, crew: tuple[CrewMember, ...], ask: Any, recall: Any = _no_episodes, **bounds: Any) -> Any:
    return await run_stand_down(crew, ask=ask, recall=recall, records=records, timeline_id=_SHIP, **bounds)


async def _notes(records: Any) -> list[str]:
    return sorted(entry["path"] for entry in await records.list_entries(EXIT_NOTES_DIR))


def _handler(agent_id: str, reply: str | None, received: list[IntentMessage]) -> Any:
    async def _handle(intent: IntentMessage) -> IntentResult:
        received.append(intent)
        if reply is None:  # the agent refused or failed its turn
            return IntentResult(intent_id=intent.id, agent_id=agent_id, success=False, error="no turn")
        return IntentResult(intent_id=intent.id, agent_id=agent_id, success=True, result=reply, confidence=1.0)

    return _handle


def _vessel(
    config: Any, records: Any, memory: Any, *, replies: dict[str, tuple[str, str | None]], instance_id: str = _SHIP,
) -> tuple[SimpleNamespace, list[IntentMessage]]:
    """A running vessel as the stand-down reads it: crew agents on a real intent bus, and one utility agent."""
    bus = IntentBus(SignalManager())
    received: list[IntentMessage] = []
    agents = [SimpleNamespace(id="slot-file_reader", agent_type="file_reader")]  # not crew: never addressed
    refs: dict[str, IdentityRef] = {}
    for agent_type, (callsign, reply) in replies.items():
        agent_id = f"slot-{agent_type}"
        agents.append(SimpleNamespace(id=agent_id, agent_type=agent_type))
        refs[agent_id] = IdentityRef(
            slot_id=agent_id, sovereign_id=f"sov-{agent_type}", did=f"did:probos:{_SHIP}:{agent_type}",
            callsign=callsign, agent_type=agent_type,
        )
        bus.subscribe(agent_id, _handler(agent_id, reply, received), intent_names=["direct_message"])
    ontology = SimpleNamespace(
        get_vessel_identity=lambda: SimpleNamespace(instance_id=instance_id),
        get_crew_agent_types=lambda: set(replies),
    )
    runtime = SimpleNamespace(
        config=config, records_store=records, ontology=ontology, registry=SimpleNamespace(all=lambda: list(agents)),
        identity_service=SimpleNamespace(resolve=refs.get), intent_bus=bus, episodic_memory=memory,
    )
    return runtime, received


# --- S1 to S2: one turn each, and what is kept ----------------------------------------------------------------------


async def test_each_crew_agent_gets_one_turn_and_its_note_is_kept_with_its_provenance(tmp_path: Path) -> None:
    records = _records(_data_dir(tmp_path))
    asked: list[str] = []

    async def ask(member: CrewMember, prompt: str) -> str:
        asked.append(member.agent_type)
        return _reply()

    async def recall(member: CrewMember) -> list[Episode]:
        return _episodes(3, member.sovereign_id)

    crew = (_member(), _member("data_analyst", "Rahda", f"did:probos:{_SHIP}:rahda-0001", "sov-data_analyst"))
    report = await _run(records, crew, ask, recall)

    assert [(turn.agent_type, turn.outcome) for turn in report.turns] == [
        ("surgeon", TurnOutcome.WRITTEN), ("data_analyst", TurnOutcome.WRITTEN),
    ]
    assert sorted(asked) == ["data_analyst", "surgeon"]  # one turn each
    path = exit_note_path(_SHIP, "surgeon")
    assert (report.timeline_id, report.turns[0].path) == (_SHIP, path)
    note = await records.read_entry(path, "captain")
    frontmatter = note["frontmatter"]
    assert (frontmatter["author"], frontmatter["classification"], frontmatter["status"]) == (
        "Chapel", "ship", EXIT_NOTE_STATUS,
    )
    assert frontmatter[EXIT_NOTE_KEY] == {
        "version": 1, "timeline_id": _SHIP, "callsign": "Chapel", "agent_type": "surgeon", "author_did": _DID,
        "source_episode_ids": ["ep-000", "ep-001"],
    }
    # The note is its origin line and the lesson: never the reply's preamble or citations line, never episode text.
    assert note["content"] == exit_note_body("Chapel", "surgeon", _SHIP, _LESSON)
    assert "Night watch" not in note["content"] and "Cites:" not in note["content"]


@pytest.mark.parametrize(
    "case, outcome",
    [
        ("declined", TurnOutcome.DECLINED), ("not-in-format", TurnOutcome.NOT_IN_FORMAT),
        ("no-reply", TurnOutcome.NO_REPLY), ("failed", TurnOutcome.FAILED),
    ],
)
async def test_writing_is_optional_and_a_turn_that_leaves_no_lesson_writes_nothing(
    tmp_path: Path, case: str, outcome: TurnOutcome,
) -> None:
    records = _records(_data_dir(tmp_path))

    async def ask(member: CrewMember, prompt: str) -> str | None:
        if case == "failed":
            raise RuntimeError("the model call failed")
        return {"declined": DECLINE_REPLY, "not-in-format": "A few thoughts, unsorted.", "no-reply": None}[case]

    report = await _run(records, (_member(),), ask)

    assert [turn.outcome for turn in report.turns] == [outcome]
    assert await _notes(records) == []


@pytest.mark.parametrize("case", ["removed", "cannot-remove"])
async def test_a_write_that_fails_after_publishing_leaves_no_hidden_note(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, case: str,
) -> None:
    """A2 (M2-4): ``write_entry`` publishes the document before git runs, so its failure can follow the publication (a
    git timeout here, as the real call raises past its 30 s). The stand-down removes what was published: the report
    says failed, the promotion finds nothing, and the next stand-down asks again. A note it cannot remove is reported
    failed WITH its path, which is true."""
    records = _records(_data_dir(tmp_path))
    real_write = records.write_entry
    failures = [1]

    async def write_entry(**fields: Any) -> Any:
        await real_write(**fields)  # published
        if failures:
            failures.pop()
            raise subprocess.TimeoutExpired(["git", "add"], 30)
        return fields["path"]

    records.write_entry = write_entry  # type: ignore[method-assign]

    async def ask(member: CrewMember, prompt: str) -> str:
        return _reply()

    path = exit_note_path(_SHIP, "surgeon")
    if case == "cannot-remove":
        real_unlink = Path.unlink

        def unlink(self: Path, missing_ok: bool = False) -> None:
            if self.name == "surgeon.md":
                raise PermissionError(13, "the file is being used by another process", str(self))
            real_unlink(self, missing_ok=missing_ok)

        monkeypatch.setattr(Path, "unlink", unlink)
    report = await _run(records, (_member(),), ask)

    if case == "removed":
        assert [(turn.outcome, turn.path) for turn in report.turns] == [(TurnOutcome.FAILED, "")]
        assert await _notes(records) == []
        assert (await plan_promotion(records, timeline_id=_SHIP)).records == ()  # nothing for the reset to archive
        again = await _run(records, (_member(),), ask)
        assert [(turn.outcome, turn.path) for turn in again.turns] == [(TurnOutcome.WRITTEN, path)]
    else:
        assert [(turn.outcome, turn.path) for turn in report.turns] == [(TurnOutcome.FAILED, path)]
        assert await _notes(records) == [path]  # it is there, and the report says where


# --- S3 to S6: the bounds -------------------------------------------------------------------------------------------


async def test_a_turn_that_runs_past_its_bound_is_cancelled_and_writes_nothing(tmp_path: Path) -> None:
    records = _records(_data_dir(tmp_path))
    cancelled = asyncio.Event()

    async def ask(member: CrewMember, prompt: str) -> str:
        try:
            await asyncio.sleep(5)
        except asyncio.CancelledError:
            cancelled.set()
            raise
        return _reply()

    started = time.monotonic()
    report = await _run(records, (_member(),), ask, turn_seconds=1.5, window_seconds=60.0)
    elapsed = time.monotonic() - started

    assert [turn.outcome for turn in report.turns] == [TurnOutcome.TIMED_OUT]
    assert 1.4 <= elapsed < 2.5  # A2 (M2-9), A3 (2): the turn's own bound, neither halved nor doubled, 1 s headroom
    assert cancelled.is_set()  # the turn is cancelled, never left running
    assert await _notes(records) == []


async def test_a_reply_that_returns_after_the_turn_s_deadline_writes_nothing(tmp_path: Path) -> None:
    """A2 (M2-5): an ask that suppresses its cancellation and returns after the turn's deadline, inside the window."""
    records = _records(_data_dir(tmp_path))

    async def ask(member: CrewMember, prompt: str) -> str:
        try:
            await asyncio.sleep(5)
        except asyncio.CancelledError:
            await asyncio.sleep(0.1)  # finishes late instead of stopping
        return _reply()

    report = await _run(records, (_member(),), ask, turn_seconds=0.2, window_seconds=60.0)

    assert [turn.outcome for turn in report.turns] == [TurnOutcome.TIMED_OUT]
    assert await _notes(records) == []


@pytest.mark.parametrize("case", ["slow-recall", "recall-runs-out"])
async def test_the_recall_and_the_ask_spend_one_turn(tmp_path: Path, case: str) -> None:
    """A2 (M2-5): one deadline per turn. What the recall spent is not given back to the ask, and a recall that runs
    out the turn leaves no turn to ask in.

    A3 (2): the turn runs on the stand-down's ``clock``, which the stubs advance, so the recall's end, the ask and the
    turn's deadline come in one fixed order, never raced against the event loop's timer resolution."""
    records = _records(_data_dir(tmp_path))
    now = [0.0]
    asked: list[str] = []

    async def recall(member: CrewMember) -> list[Episode]:
        if case == "slow-recall":
            now[0] = 0.3  # the recall spent 0.3 s of the 0.5 s turn
            return []
        try:
            await asyncio.sleep(5)  # hangs until the turn's bound cancels it
        except asyncio.CancelledError:
            now[0] = 0.6  # the turn is spent; the 60 s window is not
            raise
        return []

    async def ask(member: CrewMember, prompt: str) -> str:
        asked.append(member.agent_type)
        now[0] += 0.35  # inside a fresh 0.5 s turn, past what the recall left
        return _reply()

    report = await _run(
        records, (_member(),), ask, recall, turn_seconds=0.5, window_seconds=60.0, clock=lambda: now[0],
    )

    assert [turn.outcome for turn in report.turns] == [TurnOutcome.TIMED_OUT]
    assert asked == (["surgeon"] if case == "slow-recall" else [])
    assert await _notes(records) == []


async def test_the_window_closes_on_time_and_writes_nothing_late_or_unreached(tmp_path: Path) -> None:
    records = _records(_data_dir(tmp_path))
    now = [0.0]
    asked: list[str] = []

    async def ask(member: CrewMember, prompt: str) -> str:
        asked.append(member.agent_type)
        if member.agent_type == "data_analyst":
            now[0] = 1_000.0  # this reply arrives after the 60-second window has closed
        return _reply()

    crew = (
        _member(),
        _member("data_analyst", "Rahda", "did:probos:x:rahda", "sov-data_analyst"),
        _member("pathologist", "Selar", "did:probos:x:selar", "sov-pathologist"),
    )
    report = await _run(records, crew, ask, window_seconds=60.0, concurrency=1, clock=lambda: now[0])

    assert [turn.outcome for turn in report.turns] == [
        TurnOutcome.WRITTEN, TurnOutcome.TIMED_OUT, TurnOutcome.NOT_REACHED,
    ]
    assert asked == ["surgeon", "data_analyst"]  # the agent the window did not reach was never asked
    assert await _notes(records) == [exit_note_path(_SHIP, "surgeon")]


async def test_the_window_bounds_a_turn_its_own_bound_would_allow(tmp_path: Path) -> None:
    records = _records(_data_dir(tmp_path))

    async def ask(member: CrewMember, prompt: str) -> str:
        await asyncio.sleep(5)
        return _reply()

    started = time.monotonic()
    report = await _run(records, (_member(),), ask, turn_seconds=60.0, window_seconds=1.5)
    elapsed = time.monotonic() - started

    assert [turn.outcome for turn in report.turns] == [TurnOutcome.TIMED_OUT]
    assert 1.4 <= elapsed < 2.5  # A2 (M2-9), A3 (2): the window's bound, neither halved nor doubled, 1 s headroom
    assert await _notes(records) == []


@pytest.mark.parametrize("stage", ["first-read", "write"])
async def test_the_window_bounds_the_records_reads_and_writes_too(tmp_path: Path, stage: str) -> None:
    """A2 (M2-2): the window starts before Ship's Records is first read and ends every write. A first read that hangs
    refuses the stand-down with nobody asked; a write that hangs ends with the window and leaves nothing, and the turn
    queued behind it for the write lock never starts a write.

    A3 (2): the window runs on the stand-down's ``clock``. The hanging write moves it past the deadline when the
    window's bound cancels the write, so the queued turn finds the window closed in every run; on the real clock,
    asyncio may fire the bound one clock tick early (15.6 ms on Windows before Python 3.13) and leave that turn a
    few milliseconds of window to begin a write in. A write is counted when ``write_entry`` is called: a write whose
    bound is already spent is cancelled before its coroutine runs."""
    records = _records(_data_dir(tmp_path))
    real_list, real_write = records.list_entries, records.write_entry
    now = [0.0]
    writes: list[str] = []
    asked: list[str] = []

    async def list_entries(*args: Any, **kwargs: Any) -> Any:
        await asyncio.sleep(5)
        return await real_list(*args, **kwargs)

    async def _hang(fields: dict[str, Any]) -> Any:
        try:
            await asyncio.sleep(5)
        except asyncio.CancelledError:
            now[0] = 1_000.0  # the window's bound cancelled the write: the window has closed
            raise
        return await real_write(**fields)

    def write_entry(**fields: Any) -> Any:
        writes.append(fields["path"])  # at the call, before anything awaits the write
        return _hang(fields)

    async def ask(member: CrewMember, prompt: str) -> str:
        asked.append(member.agent_type)
        return _reply()

    crew = (_member(), _member("pathologist", "Selar", "did:probos:x:selar", "sov-pathologist"))
    started = time.monotonic()
    if stage == "first-read":
        records.list_entries = list_entries  # type: ignore[method-assign]
        with pytest.raises(StandDownRefused, match="Ship's Records could not be read in time"):
            await _run(records, crew, ask, window_seconds=0.3)
        records.list_entries = real_list  # type: ignore[method-assign]
        assert asked == []
    else:
        records.write_entry = write_entry  # type: ignore[method-assign]
        report = await _run(records, crew, ask, window_seconds=0.3, clock=lambda: now[0])
        assert [turn.outcome for turn in report.turns] == [TurnOutcome.TIMED_OUT, TurnOutcome.TIMED_OUT]
        assert len(writes) == 1  # the turn behind the lock never began a write
    assert time.monotonic() - started < 3.0
    assert await _notes(records) == []


async def test_no_more_than_the_bounded_number_of_turns_run_at_once(tmp_path: Path) -> None:
    records = _records(_data_dir(tmp_path))
    running = [0, 0]  # now, peak

    async def ask(member: CrewMember, prompt: str) -> None:
        running[0] += 1
        running[1] = max(running[1], running[0])
        await asyncio.sleep(0.05)
        running[0] -= 1
        return None

    crew = tuple(_member(f"type_{index}", f"C{index}", f"did:probos:x:{index}", f"sov-{index}") for index in range(5))
    report = await _run(records, crew, ask)

    assert report.count(TurnOutcome.NO_REPLY) == 5
    assert running[1] == STAND_DOWN_CONCURRENCY == 2


async def test_the_stand_down_writes_one_note_at_a_time(tmp_path: Path) -> None:
    """A1: two turns run at once (concurrency 2), and their Ship's Records writes never overlap (7.6's write lock)."""
    records = _records(_data_dir(tmp_path))
    real_write, writing = records.write_entry, [0, 0]  # now, peak

    async def write_entry(**fields: Any) -> Any:
        writing[0] += 1
        writing[1] = max(writing[1], writing[0])
        try:
            await asyncio.sleep(0.05)  # hold the write open, so an unserialised second write would overlap it
            return await real_write(**fields)
        finally:
            writing[0] -= 1

    records.write_entry = write_entry  # type: ignore[method-assign]  # the real store's write, observed

    async def ask(member: CrewMember, prompt: str) -> str:
        return _reply()

    crew = tuple(_member(f"type_{index}", f"C{index}", f"did:probos:x:{index}", f"sov-{index}") for index in range(3))
    report = await _run(records, crew, ask)

    assert report.count(TurnOutcome.WRITTEN) == 3
    assert writing[1] == 1
    assert len(await _notes(records)) == 3


# --- S7 to S10: citations, idempotence, the prompt, identity --------------------------------------------------------


async def test_a_note_cites_only_episodes_the_agent_was_shown(tmp_path: Path) -> None:
    records = _records(_data_dir(tmp_path))
    prompts: list[str] = []

    async def recall(member: CrewMember) -> list[Episode]:
        return _episodes(13, member.sovereign_id)

    async def ask(member: CrewMember, prompt: str) -> str:
        prompts.append(prompt)
        return _reply("e1, e12, e13, e99, e1")

    report = await _run(records, (_member(),), ask, recall)

    shown = [line for line in prompts[0].splitlines() if re.match(r"^e\d+ ", line)]
    assert [line.split()[0] for line in shown] == [f"e{index}" for index in range(1, 13)]
    assert all(len(line.split(": ", 1)[1]) <= EPISODE_EXCERPT_CHARS for line in shown)
    note = await records.read_entry(report.turns[0].path, "captain")
    assert note["frontmatter"][EXIT_NOTE_KEY]["source_episode_ids"] == ["ep-000", "ep-011"]


async def test_a_failed_episode_read_offers_none_and_the_note_cites_none(tmp_path: Path) -> None:
    records = _records(_data_dir(tmp_path))

    async def recall(member: CrewMember) -> list[Episode]:
        raise OSError("the episodic store is unavailable")

    async def ask(member: CrewMember, prompt: str) -> str:
        assert "(none could be read)" in prompt
        return _reply("e1")

    report = await _run(records, (_member(),), ask, recall)

    assert [turn.outcome for turn in report.turns] == [TurnOutcome.WRITTEN]
    note = await records.read_entry(report.turns[0].path, "captain")
    assert note["frontmatter"][EXIT_NOTE_KEY]["source_episode_ids"] == []


@pytest.mark.parametrize("script", ["ascii", "cjk", "astral"])
async def test_the_captain_s_message_stays_inside_the_inline_params_bound_in_any_script(
    tmp_path: Path, script: str,
) -> None:
    """A2 (M2-8): 12 episodes in any script and a callsign at its bound in CJK. The Captain's message as the transport
    encodes it (JSON, every character outside ASCII escaped) stays inside the 4 KiB standard for inline params, and
    the agent is still shown all 12."""
    letter = {"ascii": "a", "cjk": "\u6f22", "astral": "\U0001f680"}[script]
    data_dir = _data_dir(tmp_path)
    memory = MockEpisodicMemory()
    for index in range(12):
        await memory.store(Episode(
            id=f"ep-{index:03d}", timestamp=1_790_000_000.0 + index, agent_ids=["sov-surgeon"],
            user_input=f"{index} " + letter * 400,
        ))
    callsign = "\u5c0f" * EXIT_NOTE_CALLSIGN_MAX_CHARS
    runtime, received = _vessel(_config(tmp_path), _records(data_dir), memory, replies={"surgeon": (callsign, None)})

    await stand_down_vessel(runtime)

    (intent,) = received
    shown = [line for line in intent.params["text"].splitlines() if re.match(r"^e\d+ ", line)]
    assert len(shown) == 12
    assert len(json.dumps(intent.params)) <= 4096


class _Unrenderable:
    """An episode whose text cannot even be read (a store returning a broken record)."""

    id = "ep-broken"
    timestamp = 1_790_000_000.0

    @property
    def user_input(self) -> str:
        raise RuntimeError("the episode's text cannot be read")


@pytest.mark.parametrize("case", ["timestamps", "unreadable-episode", "self-cancelled"])
async def test_one_member_s_fault_never_ends_the_other_turns_or_leaves_one_running(tmp_path: Path, case: str) -> None:
    """A2 (M2-6): a timestamp that names no date (inf, NaN) is shown undated; an episode whose text cannot be read
    fails that member's turn only; a turn cancelled from inside ends the stand-down with every other turn cancelled
    and drained. Nothing outlives the call."""
    records = _records(_data_dir(tmp_path))
    stopped = asyncio.Event()
    before = asyncio.all_tasks()

    async def recall(member: CrewMember) -> list[Any]:
        if member.agent_type == "surgeon" and case == "unreadable-episode":
            return [_Unrenderable()]
        stamps = (float("inf"), float("nan")) if case == "timestamps" else (1_790_000_000.0,)
        return [
            Episode(id=f"ep-{index}", timestamp=stamp, agent_ids=[member.sovereign_id], user_input="watch")
            for index, stamp in enumerate(stamps)
        ]

    async def ask(member: CrewMember, prompt: str) -> str:
        if case == "self-cancelled":
            if member.agent_type == "surgeon":
                await asyncio.sleep(0.05)  # the other turn is waiting on its model by now
                raise asyncio.CancelledError  # cancelled from inside the turn, not by the caller
            try:
                await asyncio.sleep(5)
            except asyncio.CancelledError:
                stopped.set()
                raise
        if case == "timestamps":
            assert "undated" in prompt
        return _reply()

    crew = (_member(), _member("pathologist", "Selar", "did:probos:x:selar", "sov-pathologist"))
    if case == "self-cancelled":
        with pytest.raises(asyncio.CancelledError):
            await _run(records, crew, ask, recall)
        assert stopped.is_set()  # the other turn was cancelled, never left running
    else:
        report = await _run(records, crew, ask, recall)
        expected = TurnOutcome.FAILED if case == "unreadable-episode" else TurnOutcome.WRITTEN
        assert [turn.outcome for turn in report.turns] == [expected, TurnOutcome.WRITTEN]
    assert asyncio.all_tasks() - before == set()


async def test_a_second_stand_down_asks_only_the_agents_without_a_note(tmp_path: Path) -> None:
    records = _records(_data_dir(tmp_path))
    asked: list[str] = []

    async def ask(member: CrewMember, prompt: str) -> str:
        asked.append(member.agent_type)
        return _reply()

    pair = (_member(), _member("data_analyst", "Rahda", "did:probos:x:rahda", "sov-data_analyst"))
    await _run(records, pair, ask)
    asked.clear()
    third = _member("pathologist", "Selar", "did:probos:x:selar", "sov-pathologist")
    again = await _run(records, (*pair, third), ask)

    assert [turn.outcome for turn in again.turns] == [
        TurnOutcome.ALREADY_WRITTEN, TurnOutcome.ALREADY_WRITTEN, TurnOutcome.WRITTEN,
    ]
    assert asked == ["pathologist"]
    first_note = await records.read_entry(exit_note_path(_SHIP, "surgeon"), "captain")
    assert "revision" not in first_note["frontmatter"]  # never rewritten


@pytest.mark.parametrize("case", ["same-type", "same-member", "written-meanwhile"])
async def test_one_billet_gets_one_turn_and_no_note_is_ever_replaced(tmp_path: Path, case: str) -> None:
    """A2 (M2-3): two crew agents of one agent type share their billet's path (register R9). The first in crew order
    takes the turn and the second is not asked. A member listed twice is asked once. A note written by anyone after
    the stand-down began is found under the write lock and kept."""
    records = _records(_data_dir(tmp_path))
    asked: list[str] = []
    path = exit_note_path(_SHIP, "surgeon")

    async def ask(member: CrewMember, prompt: str) -> str:
        asked.append(member.agent_id)
        if case == "written-meanwhile":
            await records.write_entry(
                author="Bones", path=path, content="Written by hand meanwhile.", message="test: meanwhile",
                classification="ship",
            )
        return _reply()

    first = _member()
    second = CrewMember("slot-second", "surgeon", "sov-second", "did:probos:x:selar", "Selar")
    crew = {"same-type": (first, second), "same-member": (first, first), "written-meanwhile": (first,)}[case]
    report = await _run(records, crew, ask, concurrency=1)

    note = await records.read_entry(path, "captain")
    if case == "written-meanwhile":
        assert [turn.outcome for turn in report.turns] == [TurnOutcome.ALREADY_WRITTEN]
        assert note["frontmatter"]["author"] == "Bones" and "revision" not in note["frontmatter"]
    else:
        assert [(turn.outcome, turn.path) for turn in report.turns] == [
            (TurnOutcome.WRITTEN, path), (TurnOutcome.DUPLICATE, path),
        ]
        assert asked == ["slot-surgeon"]
        assert note["frontmatter"]["author"] == "Chapel" and "revision" not in note["frontmatter"]


async def test_a_stand_down_that_cannot_read_a_written_note_asks_nobody(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A2 (M1-F1 asked of the stand-down): a note already written that the OS refuses to read when the stand-down
    lists the notes. A skip would ask its author again and replace the note; the stand-down refuses instead."""
    records = _records(_data_dir(tmp_path))
    asked: list[str] = []

    async def ask(member: CrewMember, prompt: str) -> str:
        asked.append(member.agent_type)
        return _reply()

    await _run(records, (_member(),), ask)
    asked.clear()
    path = exit_note_path(_SHIP, "surgeon")
    _deny_reading(monkeypatch, records.repo_path / path)
    with pytest.raises(StandDownRefused, match="Ship's Records could not be read"):
        await _run(records, (_member(),), ask)
    monkeypatch.undo()

    assert asked == []
    assert "revision" not in (await records.read_entry(path, "captain"))["frontmatter"]


def test_the_prompt_says_writing_is_optional_and_what_the_note_is_for() -> None:
    prompt = exit_notes_prompt("Chapel", ("e1 2026-10-25: the coolant alarm cleared again",))

    for phrase in (
        "Captain to Chapel",
        "Your successor in this billet will not share your memories",
        "what you learned, what you would do differently, and what remains open",
        "Writing is optional",
        f"reply exactly {DECLINE_REPLY} and nothing is recorded",
        f"the four sections together at most {LESSON_MAX_CHARS} characters",
        *(f"## {name}\n" for name in LESSON_SECTIONS),
        "Cites: (optional)",
        "kept in Ship's Records under your callsign and DID",
        "The Captain may review them and veto them",
        "archived in the Ship's Archive at the reset, where every later crew can read them",
        "labelled as inherited from this crew",  # A2 (M2-9)
        "Reply with the notes alone, without using tools",
        "Write nothing you would not share with the whole ship",
        "do not quote your memories",
        "e1 2026-10-25: the coolant alarm cleared again",
    ):
        assert phrase in prompt, phrase


async def test_an_agent_without_an_identity_is_not_asked(tmp_path: Path) -> None:
    records = _records(_data_dir(tmp_path))
    asked: list[str] = []

    async def ask(member: CrewMember, prompt: str) -> str:
        asked.append(member.agent_type)
        return _reply()

    crew = (_member(did=""), _member("pathologist", "", "did:probos:x:selar", "sov-pathologist"))
    report = await _run(records, crew, ask)

    assert [turn.outcome for turn in report.turns] == [TurnOutcome.NO_IDENTITY, TurnOutcome.NO_IDENTITY]
    assert asked == []
    assert await _notes(records) == []


@pytest.mark.parametrize(
    "field, value",
    [
        ("callsign", "Chapel\n## Observation"), ("callsign", "C" * (EXIT_NOTE_CALLSIGN_MAX_CHARS + 1)),
        ("agent_type", "sur\x00geon"), ("did", "did:probos:x:\ud800"),
    ],
    ids=["multiline-callsign", "long-callsign", "nul-agent-type", "surrogate-did"],
)
async def test_an_identity_that_cannot_stand_in_the_note_is_not_asked(tmp_path: Path, field: str, value: str) -> None:
    """A2 (M2-7): the promotion's own provenance check, before the turn. An identity whose note the promotion would
    withhold (a line break or NUL in the origin line, a value past its bound, a DID SQLite cannot store) is never
    asked and never reported written."""
    records = _records(_data_dir(tmp_path))
    asked: list[str] = []

    async def ask(member: CrewMember, prompt: str) -> str:
        asked.append(member.agent_type)
        return _reply()

    member = dataclasses.replace(_member(), **{field: value})
    report = await _run(records, (member,), ask)

    assert [turn.outcome for turn in report.turns] == [TurnOutcome.NO_IDENTITY]
    assert asked == []
    assert await _notes(records) == []


# --- S11 to S14: the vessel, the console, and what it never touches ------------------------------------------------


@pytest.mark.parametrize("case", ["archive-disabled", "no-records", "no-instance-id", "unknown-instance-id"])
async def test_the_stand_down_refuses_when_nothing_could_be_kept_or_attributed(tmp_path: Path, case: str) -> None:
    data_dir = _data_dir(tmp_path)
    config = _config(tmp_path, archive_enabled=case != "archive-disabled")
    records = None if case == "no-records" else _records(data_dir)
    instance_id = {"no-instance-id": "", "unknown-instance-id": "unknown"}.get(case, _SHIP)
    runtime, received = _vessel(
        config, records, MockEpisodicMemory(), replies={"surgeon": ("Chapel", _reply())}, instance_id=instance_id,
    )

    refusal = {
        "archive-disabled": "Ship's Archive is disabled", "no-records": "Ship's Records is not running",
        "no-instance-id": "has no instance id", "unknown-instance-id": "has no instance id",
    }[case]
    with pytest.raises(StandDownRefused, match=refusal):  # each case's own refusal, never another's (A1)
        await stand_down_vessel(runtime)

    assert received == []  # nobody was asked


async def test_the_vessel_stand_down_sends_each_crew_agent_the_captains_message_through_the_intent_bus(
    tmp_path: Path,
) -> None:
    data_dir = _data_dir(tmp_path)
    memory = MockEpisodicMemory()
    for episode in _episodes(2, "sov-surgeon"):
        await memory.store(episode)
    runtime, received = _vessel(
        _config(tmp_path), _records(data_dir), memory,
        replies={"surgeon": ("Chapel", _reply("e1")), "data_analyst": ("Rahda", None)},
    )

    report = await stand_down_vessel(runtime)

    assert [(turn.agent_type, turn.outcome) for turn in report.turns] == [
        ("data_analyst", TurnOutcome.NO_REPLY), ("surgeon", TurnOutcome.WRITTEN),
    ]  # the utility agent is not crew and has no turn
    assert sorted(intent.target_agent_id for intent in received) == ["slot-data_analyst", "slot-surgeon"]
    for intent in received:
        assert intent.intent == "direct_message"
        assert (intent.params["from"], intent.params["session"]) == ("captain", False)
        assert intent.params[BOUNDED_TURN_PARAM] is True  # A2 (M2-1): the DM consumer answers it inline, single-pass
        assert intent.ttl_seconds == STAND_DOWN_TURN_SECONDS
        assert "Writing is optional" in intent.params["text"]
    note = await _records(data_dir).read_entry(report.turns[1].path, "captain")
    assert note["frontmatter"][EXIT_NOTE_KEY]["author_did"] == f"did:probos:{_SHIP}:surgeon"
    assert note["frontmatter"][EXIT_NOTE_KEY]["source_episode_ids"] == ["ep-001"]  # e1: the most recent episode
    assert await _notes(_records(data_dir)) == [exit_note_path(_SHIP, "surgeon")]


async def test_only_the_console_runs_a_stand_down(monkeypatch: pytest.MonkeyPatch) -> None:
    assert "/stand-down" in ProbOSShell.COMMANDS
    called: list[str] = []

    async def _recorded(runtime: Any, console: Any, arg: str) -> None:
        called.append(arg)

    monkeypatch.setattr(commands_stand_down, "cmd_stand_down", _recorded)
    shell = ProbOSShell.__new__(ProbOSShell)
    shell.runtime, shell.console, shell.renderer = MagicMock(), MagicMock(), MagicMock()

    await shell._dispatch_slash("/stand-down")

    assert called == [""]
    runtime = MagicMock()
    answer = await _handle_slash_command("/stand-down", runtime)
    assert "only available in the CLI terminal" in answer["response"]
    assert runtime.mock_calls == []  # the HXI chat and the channels reach nothing on the vessel


async def test_the_console_command_reports_each_turn_and_the_next_steps(tmp_path: Path) -> None:
    data_dir = _data_dir(tmp_path)
    runtime, _received = _vessel(  # A2 (M2-9): a callsign that is Rich markup is printed as text
        _config(tmp_path), _records(data_dir), MockEpisodicMemory(),
        replies={"surgeon": ("[bold]Chapel[/bold]", _reply())},
    )
    output = StringIO()

    await commands_stand_down.cmd_stand_down(runtime, Console(file=output, width=200), "")

    text = output.getvalue()
    assert f"[bold]Chapel[/bold]: written -> {exit_note_path(_SHIP, 'surgeon')}" in text
    assert "probos archive pending" in text and "probos archive veto PATH --reason TEXT" in text
    runtime.config.archive.enabled = False
    refused = StringIO()
    await commands_stand_down.cmd_stand_down(runtime, Console(file=refused, width=200), "")
    assert "Stand-down refused" in refused.getvalue()


def test_the_stand_down_never_writes_the_ship_s_archive() -> None:
    tree = ast.parse((_SRC / "stand_down.py").read_text(encoding="utf-8"))
    imported = {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module}
    imported |= {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
    imported |= {  # A2 (M2-9): ``from probos.knowledge import archive_store`` names the module through its alias
        f"{node.module}.{alias.name}"
        for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module for alias in node.names
    }
    called = {
        node.func.attr for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }

    assert not any(name.startswith("probos.knowledge.archive") for name in imported)
    assert called.isdisjoint({"promote_entry", "veto_source", "erase_entry", "record_generation"})


# --- S15: the real seam ----------------------------------------------------------------------------------------------


async def _remember_and_stand_down(runtime: Any, memory: MockEpisodicMemory) -> Any:
    for episode in _episodes(2, "sov-surgeon"):
        await memory.store(episode)
    return await stand_down_vessel(runtime)


async def _erase_the_cited_episode(tmp_path: Path, memory: MockEpisodicMemory, episode_id: str) -> tuple[int, ...]:
    store = _archive_store(tmp_path)  # the next generation's vessel opens the same archive
    await store.initialize()
    try:
        with pytest.raises(ArchiveCitationsBlockErasure) as refused:
            await ErasureManager(memory, None, None, archive_store=store).forget_episode(episode_id)
        return refused.value.entry_ids
    finally:
        await store.close()


def test_a_stand_down_note_reaches_a_later_crew_as_inherited_and_its_citation_reaches_the_erasure_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    config, data_dir = _config(tmp_path), _data_dir(tmp_path)
    memory = MockEpisodicMemory()
    runtime, _received = _vessel(config, _records(data_dir), memory, replies={"surgeon": ("Chapel", _reply("e1"))})

    report = asyncio.run(_remember_and_stand_down(runtime, memory))
    path = report.turns[0].path
    assert report.turns[0].outcome is TurnOutcome.WRITTEN

    assert _reset(monkeypatch, config, data_dir) == 0  # the real probos reset promotes before it wipes
    archive = tmp_path / "archive.db"
    ((entry_id, kind, timeline, did, cited),) = _rows(
        archive, "SELECT id, source_kind, timeline_id, author_did, source_episode_ids FROM archive WHERE source_ref = ?",
        (path,),
    )
    assert (kind, timeline, did, json.loads(cited)) == ("exit_note", _SHIP, f"did:probos:{_SHIP}:surgeon", ["ep-001"])

    results = asyncio.run(_oracle_query(tmp_path, "coolant drift alarm"))  # a later crew's real Oracle
    inherited = [result for result in results if "Exit notes left by Chapel" in result.content]
    assert len(inherited) == 1
    assert inherited[0].content.splitlines()[0] == "[Inherited from the crew of generation 1: not your own memory]"

    # Here the cited episode outlives the reset (this memory is not the reset's data directory). S3's check refuses its
    # erasure, which is the citation S5's continuous promotion will rely on while episodes are still live.
    assert asyncio.run(_erase_the_cited_episode(tmp_path, memory, "ep-001")) == (entry_id,)


# --- S16: the real DM consumer (A2, M2-1) ----------------------------------------------------------------------------


async def test_a_stand_down_turn_is_answered_inline_by_the_real_dm_consumer_and_never_promoted(tmp_path: Path) -> None:
    """A2 (M2-1), the real seam: real ``CognitiveAgent`` DM consumers (``perceive``, then the conversational agentic
    gate the agent's decision step calls) with the shipped ``dm_agentic`` settings armed: the tool-calling loop on, and
    promotion into a background work item after 40 s. The stand-down's turns take the single-pass path: the loop's
    model is never called, no work item is opened and no promoted task is left. The control: the same agent's ordinary
    1:1 message still runs the loop."""
    runtime, received = _vessel(
        _config(tmp_path), _records(_data_dir(tmp_path)), MockEpisodicMemory(),
        replies={"surgeon": ("Chapel", None), "data_analyst": ("Rahda", None)},
    )
    runtime.config.dm_agentic.enabled = True  # the shipped settings (config/system.yaml, dm_agentic)
    runtime.config.dm_agentic.promote_to_task_after_seconds = 40.0
    work = WorkItemStore(db_path=str(tmp_path / "work.db"))
    await work.start()
    runtime.work_item_store = work
    runtime.chat_thread_store = ChatThreadStore(tmp_path / "threads.db")
    runtime.trust_network = TrustNetwork()
    runtime.ontology.get_agent_department = lambda agent_type: "medical"
    loop_requests: list[Any] = []
    single_pass: list[str] = []

    class OfflineModel(BaseLLMClient):
        """The only stand-in: the model behind the tool-calling loop answers at once, and is counted."""

        async def complete(self, request: Any, *, priority: Any = None) -> LLMResponse:
            loop_requests.append(request)
            return LLMResponse(
                content=_reply(), model="offline-stub", tier=request.tier, tokens_used=1, request_id=request.id,
            )

    members = crew_for_stand_down(runtime)
    runtime.registry = AgentRegistry()
    agents: list[CognitiveAgent] = []
    for member in members:
        agent = CognitiveAgent(
            agent_id=member.agent_id, instructions="Offline only.", runtime=runtime, llm_client=OfflineModel(),
        )
        agent.agent_type, agent.callsign = member.agent_type, member.callsign
        await runtime.registry.register(agent)
        agents.append(agent)

        async def consumer(intent: IntentMessage, agent: CognitiveAgent = agent) -> IntentResult:
            received.append(intent)
            observation = await agent.perceive(intent)
            text = await agent._maybe_run_conversational_agentic(  # the gate the decision step calls first
                observation, system_prompt="Offline only.",
                user_message=CognitiveAgent._format_direct_message_trigger(intent.params),
            )
            if text is None:  # the single-pass path answers inline; the stub stands for its one model call
                single_pass.append(intent.target_agent_id)
                text = _reply()
            return IntentResult(intent_id=intent.id, agent_id=agent.id, success=True, result=text, confidence=1.0)

        runtime.intent_bus.subscribe(member.agent_id, consumer, intent_names=["direct_message"])
    try:
        report = await stand_down_vessel(runtime)
        turns, items, during = list(received), await work.list_work_items(), len(loop_requests)
        control = await runtime.intent_bus.send(IntentMessage(
            intent="direct_message", params={"text": "How was the watch?", "from": "captain", "session": False},
            target_agent_id=members[0].agent_id, ttl_seconds=60.0,
        ))
    finally:
        for agent in agents:
            while agent._promoted_turn_tasks:
                await asyncio.gather(*tuple(agent._promoted_turn_tasks), return_exceptions=True)
        await work.stop()

    assert len(turns) == 2 and all(intent.params[BOUNDED_TURN_PARAM] is True for intent in turns)
    assert report.count(TurnOutcome.WRITTEN) == 2
    assert sorted(single_pass) == sorted(member.agent_id for member in members)  # each answered inline
    assert during == 0  # the tool-calling loop never ran for a stand-down turn
    assert items == []  # and nothing was promoted into a work item
    assert all(not agent._promoted_turn_tasks for agent in agents)
    assert control is not None and control.success
    assert len(loop_requests) > during  # the control: an ordinary 1:1 message still runs the loop
