"""AD-1341 S5 (#1569), M2: the after-action turn, the chain-of-command review and the console command.

Real Ship's Records on ``tmp_path`` and the real ontology (``config/ontology`` copied); the crew's model turns are
scripted callables, so no vessel and no model is used.
"""

from __future__ import annotations

import shutil
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from rich.console import Console

from probos.after_action import (
    AFTER_ACTION_TURN_SECONDS,
    AfterActionOutcome,
    AfterActionRefused,
    after_action_prompt,
    after_action_vessel,
    chain_of_command_reviewers,
    parse_review,
    review_prompt,
    run_after_action,
)
from probos.api import _BLOCKED_COMMANDS, _handle_slash_command
from probos.config import SystemConfig
from probos.experience.commands import commands_after_action
from probos.experience.shell import ProbOSShell
from probos.knowledge.archive_promotion import plan_promotion
from probos.knowledge.lessons import AFTER_ACTION_KEY, after_action_body, parse_lesson
from probos.ontology import VesselOntologyService
from probos.stand_down import BOUNDED_TURN_PARAM, CrewMember
from probos.types import IntentResult
from tests.test_ad1340_s1_eviction import _episode
from tests.test_ad1341_s1_reset_and_erase import _SHIP, _data_dir, _records
from tests.test_ad1341_s4_stand_down import _reply

_REPO = Path(__file__).resolve().parents[1]
_FLAGGED = "20261027T015500Z"
_SUBJECT = "Coolant drift alarm, night watch"


def _member(agent_type: str, callsign: str, *, did: bool = True) -> CrewMember:
    return CrewMember(
        agent_id=f"slot-{agent_type}", agent_type=agent_type, sovereign_id=f"sov-{agent_type}",
        did=f"did:probos:{_SHIP}:{agent_type}" if did else "", callsign=callsign,
    )


_AUTHOR = _member("surgeon", "Pulaski")
_CHIEF = _member("diagnostician", "Bones")
_COUNSELOR = _member("counselor", "Troi")
_XO = _member("architect", "Number One")
_CHAIN = (("superior", _CHIEF), ("counselor_or_xo", _COUNSELOR))


class _Turns:
    """A scripted crew: each agent type's reply (a string, None, an exception, or a callable of the prompt)."""

    def __init__(self, replies: dict[str, Any]) -> None:
        self.replies = replies
        self.asked: list[str] = []
        self.prompts: dict[str, str] = {}

    async def ask(self, member: CrewMember, prompt: str) -> str | None:
        self.asked.append(member.agent_type)
        self.prompts[member.agent_type] = prompt
        reply = self.replies.get(member.agent_type)
        if isinstance(reply, BaseException):
            raise reply
        return reply(prompt) if callable(reply) else reply


async def _recall(member: CrewMember) -> list[Any]:
    return [_episode(0), _episode(1)]


async def _run(records: Any, turns: _Turns, **overrides: Any) -> Any:
    options: dict[str, Any] = {
        "subject": _SUBJECT, "flagged_at": _FLAGGED, "reviewers": lambda: _CHAIN, "ask": turns.ask, "recall": _recall,
        "records": records, "timeline_id": _SHIP,
    }
    options.update(overrides)
    return await run_after_action(options.pop("author", _AUTHOR), **options)


@pytest.fixture
async def ontology(tmp_path: Path) -> VesselOntologyService:
    destination = tmp_path / "ontology"
    shutil.copytree(_REPO / "config" / "ontology", destination)
    service = VesselOntologyService(destination, data_dir=tmp_path / "ontology-data")
    await service.initialize()
    return service


async def test_a_flagged_event_gets_one_report_reviewed_by_the_chain(tmp_path: Path) -> None:
    records = _records(_data_dir(tmp_path))
    turns = _Turns({"surgeon": _reply("e1"), "diagnostician": "ENDORSE", "counselor": "**Endorse.**"})

    report = await _run(records, turns)

    assert report.outcome is AfterActionOutcome.WRITTEN and report.endorsed
    assert turns.asked == ["surgeon", "diagnostician", "counselor"]  # the author, then the chain in order
    document = await records.read_entry(report.path, "")
    envelope = document["frontmatter"][AFTER_ACTION_KEY]
    assert envelope["source_episode_ids"] == ["ep-000"] and envelope["subject"] == _SUBJECT
    assert [(entry["stage"], entry["outcome"], entry["callsign"]) for entry in envelope["review"]] == [
        ("superior", "endorsed", "Bones"), ("counselor_or_xo", "endorsed", "Troi"),
    ]
    assert document["content"] in turns.prompts["diagnostician"]  # the reviewer read the report it endorsed
    plan = await plan_promotion(records, timeline_id=_SHIP)
    assert [record.source_ref for record in plan.records] == [report.path]  # M1's rule takes what M2 writes


_CREW = (_AUTHOR, _CHIEF, _COUNSELOR, _XO)
_NO_COUNSELOR = (_AUTHOR, _CHIEF, _XO)
_CHAINS: dict[str, tuple[CrewMember, tuple[CrewMember, ...], tuple[str | None, str | None]]] = {
    "surgeon": (_AUTHOR, _CREW, ("diagnostician", "counselor")),
    "diagnostician": (_CHIEF, _CREW, ("architect", "counselor")),
    "counselor": (_COUNSELOR, _CREW, (None, "architect")),
    "architect": (_XO, _CREW, (None, "counselor")),
    "surgeon-without-a-counselor": (_AUTHOR, _NO_COUNSELOR, ("diagnostician", "architect")),
    "diagnostician-without-a-counselor": (_CHIEF, _NO_COUNSELOR, ("architect", None)),
    "surgeon-whose-chief-has-no-did": (
        _AUTHOR, (_AUTHOR, _member("diagnostician", "Bones", did=False), _COUNSELOR), (None, "counselor"),
    ),
}


@pytest.mark.parametrize("case", sorted(_CHAINS))
async def test_the_reviewers_are_found_by_billet_in_the_real_chain_of_command(
    ontology: VesselOntologyService, case: str,
) -> None:
    assert ontology.get_post_for_agent("surgeon").reports_to == "chief_medical"  # premise: the shipped chain
    author, crew, expected = _CHAINS[case]

    stages = chain_of_command_reviewers(author, crew, ontology)

    assert [stage for stage, _member in stages] == ["superior", "counselor_or_xo"]
    assert tuple(member.agent_type if member is not None else None for _stage, member in stages) == expected


@pytest.mark.parametrize(
    ("superior", "second", "asked", "outcomes"),
    [
        ("RETURN", "ENDORSE", ["surgeon", "diagnostician"], ["returned", "not_reviewed"]),
        ("ENDORSE", "RETURN: not grounded", ["surgeon", "diagnostician", "counselor"], ["endorsed", "returned"]),
    ],
    ids=["superior-returns", "counselor-returns"],
)
async def test_a_returned_report_is_kept_and_never_promoted(
    tmp_path: Path, superior: str, second: str, asked: list[str], outcomes: list[str],
) -> None:
    records = _records(_data_dir(tmp_path))
    turns = _Turns({"surgeon": _reply("e1"), "diagnostician": superior, "counselor": second})

    report = await _run(records, turns)

    assert report.outcome is AfterActionOutcome.WRITTEN and not report.endorsed
    assert turns.asked == asked  # a returned stage ends the review
    assert [review.outcome for review in report.reviews] == outcomes
    plan = await plan_promotion(records, timeline_id=_SHIP)
    assert plan.records == () and plan.withheld == (report.path,)  # kept as a record, never a promotion source


@pytest.mark.parametrize(
    "answer", [None, "I think it is fine.", "ENDORSED", TimeoutError(), RuntimeError("down")],
    ids=["no-reply", "prose", "not-the-word", "timed-out", "failed"],
)
async def test_a_review_that_is_not_an_answer_keeps_the_report_out_of_canon(tmp_path: Path, answer: Any) -> None:
    records = _records(_data_dir(tmp_path))
    turns = _Turns({"surgeon": _reply("e1"), "diagnostician": answer, "counselor": "ENDORSE"})

    report = await _run(records, turns)

    assert report.outcome is AfterActionOutcome.WRITTEN and not report.endorsed
    assert [review.outcome for review in report.reviews] == ["not_reviewed", "not_reviewed"]
    assert turns.asked == ["surgeon", "diagnostician"]


@pytest.mark.parametrize(
    ("reply", "outcome"),
    [
        ("NO NOTES", AfterActionOutcome.DECLINED),
        ("We should log every alarm.", AfterActionOutcome.NOT_IN_FORMAT),
        (None, AfterActionOutcome.NO_REPLY),
        (RuntimeError("down"), AfterActionOutcome.FAILED),
        (TimeoutError(), AfterActionOutcome.TIMED_OUT),
    ],
    ids=["declined", "not-in-format", "no-reply", "failed", "timed-out"],
)
async def test_the_author_s_turn_writes_nothing_unless_it_is_a_lesson(
    tmp_path: Path, reply: Any, outcome: AfterActionOutcome,
) -> None:
    records = _records(_data_dir(tmp_path))
    turns = _Turns({"surgeon": reply, "diagnostician": "ENDORSE", "counselor": "ENDORSE"})

    report = await _run(records, turns)

    assert report.outcome is outcome and report.path == "" and report.reviews == ()
    assert turns.asked == ["surgeon"]  # the chain is never asked about a report that does not exist
    assert not (records.repo_path / "after-action").exists()


class _Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


@pytest.mark.parametrize("case", ["late-author", "late-review", "window-closed-before-write"])
async def test_the_turns_are_bounded_by_their_deadline_and_one_window(tmp_path: Path, case: str) -> None:
    records = _records(_data_dir(tmp_path))
    clock = _Clock()

    def after(seconds: float, reply: str) -> Any:
        def answer(_prompt: str) -> str:
            clock.now += seconds
            return reply
        return answer

    late = AFTER_ACTION_TURN_SECONDS + 1
    replies = {
        "late-author": {"surgeon": after(late, _reply("e1"))},
        "late-review": {"surgeon": _reply("e1"), "diagnostician": after(late, "ENDORSE"), "counselor": "ENDORSE"},
        # three turns of 160 s end exactly at a 480 s window: each in time, and no write may begin after it
        "window-closed-before-write": {
            "surgeon": after(160, _reply("e1")), "diagnostician": after(160, "ENDORSE"),
            "counselor": after(160, "ENDORSE"),
        },
    }[case]

    real_write = records.write_entry
    begun: list[str] = []

    def write_entry(**kwargs: Any) -> Any:
        begun.append(kwargs["path"])  # a write begins when it is called: its coroutine exists from here
        return real_write(**kwargs)

    with patch.object(records, "write_entry", write_entry):
        report = await _run(records, _Turns(replies), clock=clock, window_seconds=480.0)

    if case == "late-author":
        assert report.outcome is AfterActionOutcome.TIMED_OUT and report.reviews == ()
        assert begun == []
    elif case == "late-review":
        assert report.outcome is AfterActionOutcome.WRITTEN
        assert [review.outcome for review in report.reviews] == ["not_reviewed", "not_reviewed"]
        assert begun == [report.path]
    else:
        assert [review.outcome for review in report.reviews] == ["endorsed", "endorsed"]  # premise: all in time
        # No write begins once the window has closed. The outcome and the empty directory alone cannot show it:
        # asyncio.wait_for(..., timeout=0) cancels a write task before its first step (Amendment A1, W-6).
        assert begun == []
        assert report.outcome is AfterActionOutcome.TIMED_OUT and report.path == ""
        assert not (records.repo_path / "after-action").exists()
    assert not report.endorsed


async def test_a_report_is_never_written_over(tmp_path: Path) -> None:
    records = _records(_data_dir(tmp_path))
    first = await _run(records, _Turns({"surgeon": _reply("e1"), "diagnostician": "ENDORSE", "counselor": "ENDORSE"}))
    turns = _Turns({"surgeon": _reply("e2"), "diagnostician": "RETURN", "counselor": "RETURN"})

    again = await _run(records, turns)

    assert first.outcome is AfterActionOutcome.WRITTEN
    assert again.outcome is AfterActionOutcome.ALREADY_WRITTEN and again.path == first.path
    assert turns.asked == []  # nobody is asked for a report that exists
    document = await records.read_entry(first.path, "")
    assert document["frontmatter"][AFTER_ACTION_KEY]["source_episode_ids"] == ["ep-000"]  # the first, unchanged


async def test_a_report_cites_only_episodes_its_author_was_shown(tmp_path: Path) -> None:
    records = _records(_data_dir(tmp_path))
    turns = _Turns({"surgeon": _reply("e2, e9, e2"), "diagnostician": "ENDORSE", "counselor": "ENDORSE"})

    report = await _run(records, turns)

    document = await records.read_entry(report.path, "")
    assert document["frontmatter"][AFTER_ACTION_KEY]["source_episode_ids"] == ["ep-001"]  # e9 was never shown
    assert "\ne1 " in turns.prompts["surgeon"] and "\ne2 " in turns.prompts["surgeon"]  # shown by handle
    assert document["content"] == after_action_body("Pulaski", "surgeon", _SHIP, parse_lesson(_reply()))


@pytest.mark.parametrize("case", ["subject-too-long", "subject-on-two-lines", "no-did", "bad-timeline", "bad-flag"])
async def test_a_flag_that_cannot_stand_in_a_report_asks_nobody(tmp_path: Path, case: str) -> None:
    records = _records(_data_dir(tmp_path))
    turns = _Turns({"surgeon": _reply("e1")})
    overrides = {
        "subject-too-long": {"subject": "s" * 161},
        "subject-on-two-lines": {"subject": "Coolant\ndrift"},
        "no-did": {"author": _member("surgeon", "Pulaski", did=False)},
        "bad-timeline": {"timeline_id": "t\nu"},
        "bad-flag": {"flagged_at": "yesterday"},
    }[case]

    with pytest.raises(AfterActionRefused):
        await _run(records, turns, **overrides)

    assert turns.asked == []


@pytest.mark.parametrize(
    ("reply", "outcome"),
    [
        ("ENDORSE", "endorsed"), ("endorse.", "endorsed"), ("**Endorse**", "endorsed"),
        ("ENDORSE\nA good lesson.", "endorsed"), ("RETURN", "returned"), ("Return: not grounded", "returned"),
        ("ENDORSED", "not_reviewed"), ("I endorse it", "not_reviewed"), ("", "not_reviewed"), (None, "not_reviewed"),
        ("Approve", "not_reviewed"),
    ],
)
def test_a_review_reads_only_an_endorsement_or_a_return(reply: Any, outcome: str) -> None:
    assert parse_review(reply) == outcome


def test_the_prompts_say_what_is_asked_and_where_it_goes() -> None:
    author = after_action_prompt("Pulaski", _SUBJECT, ["e1 2026-10-26: coolant"])
    for phrase in (
        _SUBJECT, "## Observation", "## Recommendation", "Cites:", "NO NOTES", "chain of command", "Ship's Archive",
        "without using tools", "e1 2026-10-26: coolant",
    ):
        assert phrase in author
    review = review_prompt("Bones", "Pulaski", "THE REPORT")
    for phrase in ("ENDORSE", "RETURN", "Pulaski", "THE REPORT", "Ship's Archive", "without using tools"):
        assert phrase in review


async def test_after_action_is_a_console_command_the_hxi_cannot_reach() -> None:
    assert "/after-action" in _BLOCKED_COMMANDS and "/after-action" in ProbOSShell.COMMANDS
    console = Console(record=True, width=200)
    for arg in ("", "Pulaski", ": no callsign", "Pulaski:   "):
        await commands_after_action.cmd_after_action(MagicMock(), console, arg)
    assert console.export_text().count("Usage: /after-action CALLSIGN: SUBJECT") == 4
    for text in ("/after-action Pulaski: coolant drift", "/AFTER-ACTION Pulaski: coolant drift"):
        runtime = MagicMock()
        answer = await _handle_slash_command(text, runtime)  # the HXI chat's and the channel adapters' route
        assert answer["response"] == "/after-action is only available in the CLI terminal, not the HXI chat."
        assert runtime.mock_calls == []  # Amendment A3: refused before the shell, the bus or Ship's Records is touched


async def test_the_vessel_sends_each_turn_as_a_bounded_captain_s_message(
    tmp_path: Path, ontology: VesselOntologyService,
) -> None:
    records = _records(_data_dir(tmp_path))
    replies = {"slot-surgeon": _reply("e1"), "slot-diagnostician": "ENDORSE", "slot-counselor": "ENDORSE"}
    sent: list[Any] = []

    async def send(intent: Any) -> IntentResult:
        sent.append(intent)
        return IntentResult(
            intent_id=intent.id, agent_id=intent.target_agent_id, success=True, result=replies[intent.target_agent_id],
        )

    ontology.get_vessel_identity = lambda: SimpleNamespace(instance_id=_SHIP)  # type: ignore[method-assign]
    runtime = MagicMock()
    runtime.config = SystemConfig()
    runtime.records_store = records
    runtime.ontology = ontology
    runtime.intent_bus.send = send
    runtime.episodic_memory = None
    stamp = 1_793_066_100.0
    with patch("probos.after_action.crew_for_stand_down", return_value=_CREW):
        report = await after_action_vessel(runtime, "pulaski", _SUBJECT, now=lambda: stamp)
        with pytest.raises(AfterActionRefused):
            await after_action_vessel(runtime, "Nobody", _SUBJECT)

    assert report.endorsed
    assert report.path.endswith("-" + time.strftime("%Y%m%dT%H%M%SZ", time.gmtime(stamp)).lower() + ".md")
    assert [intent.target_agent_id for intent in sent] == ["slot-surgeon", "slot-diagnostician", "slot-counselor"]
    for intent in sent:
        assert intent.intent == "direct_message" and intent.params["from"] == "captain"
        assert intent.params[BOUNDED_TURN_PARAM] is True and intent.params["session"] is False
    runtime.config.archive.enabled = False
    with pytest.raises(AfterActionRefused):
        await after_action_vessel(runtime, "Pulaski", _SUBJECT)
    assert len(sent) == 3  # a refused flag sends nothing


@pytest.mark.parametrize("case", ["no-reviewer", "reviewer-without-a-did", "reviewer-is-the-author"])
async def test_a_billet_no_one_can_fill_is_vacant_and_never_the_author(tmp_path: Path, case: str) -> None:
    records = _records(_data_dir(tmp_path))
    turns = _Turns({"surgeon": _reply("e1"), "diagnostician": "ENDORSE", "counselor": "ENDORSE"})
    superior = {
        "no-reviewer": None,
        "reviewer-without-a-did": _member("diagnostician", "Bones", did=False),
        "reviewer-is-the-author": _AUTHOR,
    }[case]

    report = await _run(records, turns, reviewers=lambda: (("superior", superior), ("counselor_or_xo", _COUNSELOR)))

    assert [review.outcome for review in report.reviews] == ["vacant", "endorsed"]
    assert turns.asked == ["surgeon", "counselor"]  # nobody without an identity, and never the author, is asked
    assert report.endorsed  # one endorsement and a vacancy admit it (D5)


_RELIEF = CrewMember(
    agent_id="slot-diagnostician-relief", agent_type="diagnostician", sovereign_id="sov-diagnostician-relief",
    did=f"did:probos:{_SHIP}:diagnostician-relief", callsign="Bones",
)
#: Amendment A3 (B1): the crew when the Captain flags, the slot whose turn changes it, the crew after, who is asked.
_ROSTER_CHANGES: dict[str, tuple[tuple[CrewMember, ...], str, tuple[CrewMember, ...], list[str]]] = {
    "superior-filled-during-the-author-s-turn": (
        (_AUTHOR, _COUNSELOR, _XO), "slot-surgeon", _CREW, ["slot-surgeon", "slot-diagnostician", "slot-counselor"],
    ),
    "superior-replaced-during-the-author-s-turn": (
        _CREW, "slot-surgeon", (_AUTHOR, _RELIEF, _COUNSELOR, _XO),
        ["slot-surgeon", "slot-diagnostician-relief", "slot-counselor"],
    ),
    "counselor-filled-during-the-superior-s-turn": (
        (_AUTHOR, _CHIEF), "slot-diagnostician", (_AUTHOR, _CHIEF, _COUNSELOR),
        ["slot-surgeon", "slot-diagnostician", "slot-counselor"],
    ),
}


@pytest.mark.parametrize("case", sorted(_ROSTER_CHANGES))
async def test_each_stage_is_reviewed_by_whoever_holds_its_billet_when_it_is_asked(
    tmp_path: Path, ontology: VesselOntologyService, case: str,
) -> None:
    before, during, after, asked = _ROSTER_CHANGES[case]
    records = _records(_data_dir(tmp_path))
    replies = {
        "slot-surgeon": _reply("e1"), "slot-diagnostician": "ENDORSE", "slot-diagnostician-relief": "ENDORSE",
        "slot-counselor": "ENDORSE",
    }
    roster = list(before)
    sent: list[str] = []

    async def send(intent: Any) -> IntentResult:
        sent.append(intent.target_agent_id)
        here = any(member.agent_id == intent.target_agent_id for member in roster)  # a slot that left answers nothing
        if intent.target_agent_id == during:
            roster[:] = after  # the pool fills or replaces a billet while this turn runs
        return IntentResult(
            intent_id=intent.id, agent_id=intent.target_agent_id, success=here,
            result=replies[intent.target_agent_id] if here else None,
        )

    ontology.get_vessel_identity = lambda: SimpleNamespace(instance_id=_SHIP)  # type: ignore[method-assign]
    runtime = MagicMock()
    runtime.config = SystemConfig()
    runtime.records_store = records
    runtime.ontology = ontology
    runtime.intent_bus.send = send
    runtime.episodic_memory = None
    with patch("probos.after_action.crew_for_stand_down", side_effect=lambda _runtime: tuple(roster)):
        report = await after_action_vessel(runtime, "Pulaski", _SUBJECT)

    assert sent == asked  # each stage asked the holder of its billet at that stage, never a slot that had left
    assert [(review.outcome, review.callsign) for review in report.reviews] == [
        ("endorsed", "Bones"), ("endorsed", "Troi"),
    ]
    assert report.endorsed


async def test_a_billet_that_cannot_be_resolved_is_not_reviewed(tmp_path: Path) -> None:
    records = _records(_data_dir(tmp_path))
    turns = _Turns({"surgeon": _reply("e1"), "diagnostician": "ENDORSE", "counselor": "ENDORSE"})
    calls: list[int] = []

    def reviewers() -> Any:
        calls.append(len(calls))
        if len(calls) > 1:  # the shape check passes; the crew read fails when the first stage is resolved
            raise RuntimeError("registry unavailable")
        return _CHAIN

    report = await _run(records, turns, reviewers=reviewers)

    assert report.outcome is AfterActionOutcome.WRITTEN and not report.endorsed
    assert [review.outcome for review in report.reviews] == ["not_reviewed", "not_reviewed"]
    assert turns.asked == ["surgeon"]  # an unknown holder is never taken for a vacancy
