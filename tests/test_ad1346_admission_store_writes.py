"""AD-1346 M3e4b (#1604): the store-write checks of the Ward Room and the episodic store, in shadow; AD-1346 M3e4d1:
and of the clinical notes store and the skill request store.

``WardRoomService.create_thread``, ``create_post``, ``edit_post`` and ``endorse`` call ``check_at`` with
``EFFECT_STORE_WRITE`` after BF-903's guard, presenting the entry's author or voter id; ``EpisodicMemory.store`` calls it
after its policy check, presenting the episode's one agent id or None. From AD-1346 M3e4d1
``ClinicalNotesStore.write_note``, ``SkillRequestStore.file_request`` and ``SkillRequestStore.decide`` call it as the
statement before their ``if self._db:``, presenting ``author_agent_id``, ``agent_id`` and ``decided_by``.
``ProbOSRuntime.start`` hands the service through ``set_admission`` to the runtime's Ward Room when it is a
``WardRoomService``, to its episodic store when it is an ``EpisodicMemory``, to its clinical notes store when it is a
``ClinicalNotesStore`` and to its skill request store when it is a ``SkillRequestStore``.
``tests/fixtures/ad1346_store_census.py`` lists the checks (``STORE_WRITE_SCOPES``).

- WM1  by AST: each ``StoreCheck`` row's check function holds one ``check_at`` call, a statement of its body, with
       ``self._admission``, ``EFFECT_STORE_WRITE`` and the row's presented id; in the Ward Room it is the statement after
       BF-903's guard and before the ``return`` that calls the row's scope through the row's attribute; where the row's
       check function is its scope, it is on a line before the scope's first SQL write statement.
- WM2  by AST over ``src``: each ``<x>.<attribute>.<method>`` reference of the four Ward Room rows is in the row's check
       function; ``MessageStore`` and ``ThreadManager`` appear as ``ast.Name`` nodes only in ``ward_room/service.py``;
       the calls, assignments and returns that pass on a ``_messages`` or ``_threads`` read from ``self`` in that
       module, or from a name or attribute ending in ``ward_room`` elsewhere, are the two of ``_HAND_OFFS``; the modules
       of those two callees reference none of the four methods.
- WM3  #1604 property 1 at the Ward Room's and the episodic store's five checks: each counts ``ticket_missing`` outside a hold, ``ticket_live`` for the
       hold's agent or no presented id inside it, ``ticket_principal_mismatch`` for another agent inside it and
       ``ticket_revoked`` after a Captain's stop; a thread and a post that a Ward Room holding the episodic store also
       stores as episodes each count a second check, their episode's store.
- WM4  #1604 property 12 at those five checks: a Ward Room and an episodic store answer the same with the service and
       without it, with nothing carried, under a live ticket and after a Captain's stop.
- WM5  the production hand-off: after ``ProbOSRuntime.start`` with ``admission.shadow_enabled`` true and the Ward Room
       and skill requests on, the runtime's Ward Room, episodic store, clinical notes store and skill request store hold
       the runtime's service and their writes reach ``check_ticket`` with the presented ids; with it false all four
       hold None.
- WM6  #1604 property 1 at the three AD-1346 M3e4d1 checks: three rounds of four writes (a note by each of two agents,
       a filing by the first and its decision by the second), outside a hold, inside the first agent's hold, and inside
       it after a Captain's stop, tally 4 ``ticket_missing``, 2 ``ticket_live``, 2 ``ticket_principal_mismatch`` and 4
       ``ticket_revoked``.
- WM7  #1604 property 12 at those three checks: two pairs of stores, one with the service and one without, answer the
       same three rounds the same.

WM3 and WM4 use a real ``WardRoomService`` and ``EpisodicMemory``, and WM6 and WM7 a real ``ClinicalNotesStore`` and
``SkillRequestStore``, over ``tmp_path``, with a service built with the test's loop. WM5 boots a real runtime under
``tmp_path`` and replaces ``AdmissionService.check_ticket``, as ``tests/test_ad1346_admission_egress_sinks.py``'s ES2
does.
"""

from __future__ import annotations

import ast
import asyncio
import dataclasses
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Final

import pytest
import pytest_asyncio

from probos.admission import AdmissionService
from probos.admission.taxonomy import EFFECT_STORE_WRITE
from probos.admission.tickets import TicketRegistry
from probos.agent_stop import AgentStopService
from probos.cognitive.clinical_notes_store import ClinicalNotesStore
from probos.cognitive.episodic import EpisodicMemory
from probos.cognitive.llm_client import MockLLMClient
from probos.config import SystemConfig
from probos.crew_profile import CallsignRegistry
from probos.identity import AgentIdentityRegistry
from probos.identity_service import IdentityService
from probos.runtime import ProbOSRuntime
from probos.skill_request import SkillRequestStore
from probos.substrate.registry import AgentRegistry
from probos.types import Episode, EpisodeStoreOutcome
from probos.ward_room import WardRoomService
from tests.fixtures.ad1343_seam_census import calls, function
from tests.fixtures.ad1346_effect_census import references_outside, src_sources
from tests.fixtures.ad1346_store_census import STORE_WRITE_SCOPES, StoreCheck, sql_write_points

INSTANCE_ID = "ad1346-m3e4b-ship"
VESSEL_NAME = "Ad1346m3e4b"
AGENT_A = "ad1346-m3e4b-agent-a"
AGENT_B = "ad1346-m3e4b-agent-b"
_SERVICE: Final = "src/probos/ward_room/service.py"
_HOLDERS: Final = frozenset({"_messages", "_threads"})
#: (file, enclosing scope, callee, attribute) of the two calls that hand a Ward Room sub-store on (D230).
_HAND_OFFS: Final = {
    (_SERVICE, "WardRoomService.lookup_record", "WardRoomRecordLookup", "_messages"),
    ("src/probos/startup/finalize.py", "finalize_startup", "ThreadEchoAnalyzer", "_threads"),
}
#: The module that defines each callee of ``_HAND_OFFS``.
_CALLEE_MODULES: Final = {
    "WardRoomRecordLookup": "src/probos/ward_room/lookup.py",
    "ThreadEchoAnalyzer": "src/probos/ward_room/thread_echo.py",
}
#: The fields of an answer that a fresh store draws for itself (AD-1346 M3e4d1: and a skill request's ``decided_at``).
_DRAWN: Final = frozenset({"id", "thread_id", "channel_id", "created_at", "last_activity", "edited_at", "decided_at"})


class _Clock:
    """A fixed clock: no test in this file moves it."""

    def __init__(self) -> None:
        self.now = 1_000.0

    def __call__(self) -> float:
        return self.now


@pytest_asyncio.fixture
async def identity_registry(tmp_path: Path) -> AsyncIterator[AgentIdentityRegistry]:
    reg = AgentIdentityRegistry(data_dir=tmp_path / "identity")
    try:
        await reg.start()
        await reg.start(instance_id=INSTANCE_ID, vessel_name=VESSEL_NAME, version="1")
        yield reg
    finally:
        await reg.stop()


@pytest.fixture
def identities(tmp_path: Path, identity_registry: AgentIdentityRegistry) -> IdentityService:
    profiles = tmp_path / "profiles"
    profiles.mkdir()
    (profiles / "surgeon.yaml").write_text("callsign: Meridian\n", encoding="utf-8")
    callsigns = CallsignRegistry()
    callsigns.load_from_profiles(str(profiles))
    callsigns.bind_registry(AgentRegistry())
    return IdentityService(identity_registry, callsigns)


@pytest_asyncio.fixture
async def stops(tmp_path: Path) -> AsyncIterator[AgentStopService]:
    record = AgentStopService(data_dir=tmp_path / "stops")
    await record.start()
    try:
        yield record
    finally:
        await record.stop()


@pytest.fixture
def tickets(stops: AgentStopService) -> TicketRegistry:
    return TicketRegistry(stops, max_depth=1, clock=_Clock())


def _shape(value: object) -> object:
    """An answer without the fields a fresh store draws for itself."""
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {key: item for key, item in dataclasses.asdict(value).items() if key not in _DRAWN}
    return value


async def _drive(room: WardRoomService, memory: EpisodicMemory, phase: int) -> list[object]:
    """One round of the five checked writes and two refused ones: 10 checks, presenting ``AGENT_A`` five times,
    ``AGENT_B`` three times and None twice. Returns each answer without the fields a fresh store draws."""
    channel = await room.get_channel_by_name("All Hands")
    assert channel is not None, "premise: the default channel"
    thread = await room.create_thread(channel.id, AGENT_A, f"ad1346 m3e4b title {phase}", f"alpha bravo {phase}")
    post = await room.create_post(thread.id, AGENT_A, f"charlie delta {phase}")
    edited = await room.edit_post(post.id, AGENT_A, f"echo foxtrot {phase}")
    vote = await room.endorse(post.id, "post", AGENT_B, "up")
    refused: list[str] = []
    try:
        await room.endorse(post.id, "post", AGENT_A, "up")
    except ValueError as exc:
        refused.append(str(exc))
    try:
        await room.edit_post(post.id, AGENT_B, f"golf hotel {phase}")
    except ValueError as exc:
        refused.append(str(exc))
    stored = [
        await memory.store(Episode(id=f"ad1346-m3e4b-{phase}-{key}", user_input=f"ad1346 m3e4b {word} {phase}", agent_ids=ids))
        for key, word, ids in (
            ("a", "kilo", [AGENT_A]), ("ba", "lima", [AGENT_B, AGENT_A]), ("b", "mike", [AGENT_B]), ("none", "november", []),
        )
    ]
    return [_shape(thread), _shape(post), _shape(edited), vote, refused, stored]


def _config(*, shadow_enabled: bool) -> SystemConfig:
    config = SystemConfig()
    config.admission.shadow_enabled = shadow_enabled
    config.ward_room.enabled = True  # WardRoomConfig.enabled is off by default
    config.skill_requests.enabled = True  # AD-1346 M3e4d1: SkillRequestConfig.enabled is off by default
    config.onboarding.naming_ceremony = False
    config.proactive_cognitive.enabled = False
    config.qa.enabled = False
    return config


def _scoped(tree: ast.Module) -> list[tuple[str, ast.AST]]:
    """Each node of one module with its enclosing class and function names, joined as the census joins a scope."""
    found: list[tuple[str, ast.AST]] = []

    def walk(node: ast.AST, scope: tuple[str, ...]) -> None:
        for child in ast.iter_child_nodes(node):
            found.append((".".join(scope) or "<module>", child))
            named = isinstance(child, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
            walk(child, (*scope, child.name) if named else scope)

    walk(tree, ())
    return found


def _holder(node: object, rel: str) -> str | None:
    """The attribute a node reads when it is ``self._messages`` or ``self._threads`` in the Ward Room service, or
    either read from a name or attribute ending in ``ward_room`` in another module; else None."""
    if not isinstance(node, ast.Attribute) or node.attr not in _HOLDERS:
        return None
    base = node.value
    name = base.id if isinstance(base, ast.Name) else base.attr if isinstance(base, ast.Attribute) else ""
    wanted = name == "self" if rel == _SERVICE else name.endswith("ward_room")
    return node.attr if wanted else None


def test_each_store_write_check_is_one_statement_in_its_place() -> None:
    """WM1 (D229, D231, D232; AD-1346 M3e4d1: D285; kills EV-2, EV-10, ED-1, ED-2, ED-3, ED-10)."""
    lines: dict[tuple[str, str], list[int]] = {}
    for path, scope, line in sql_write_points():
        lines.setdefault((path, scope), []).append(line)
    checks = [(site, cover) for site, cover in STORE_WRITE_SCOPES.items() if isinstance(cover, StoreCheck)]
    assert len(checks) == 8, checks
    for (path, scope), cover in checks:
        fn = function(*cover.check)
        found = [node for node in ast.walk(fn) if calls("check_at")(node)]
        assert len(found) == 1, (cover.check, len(found))
        call = found[0]
        assert [ast.unparse(arg) for arg in call.args] == ["self._admission"], cover.check
        keywords = {keyword.arg: ast.unparse(keyword.value) for keyword in call.keywords}
        assert keywords == {"effect": "EFFECT_STORE_WRITE", "presented_id": cover.presented}, (cover.check, keywords)
        index = next((i for i, stmt in enumerate(fn.body) if isinstance(stmt, ast.Expr) and stmt.value is call), None)
        assert index is not None, (cover.check, "the check is a statement of the function's own body")
        if cover.via:
            guard, after = ast.unparse(fn.body[index - 1]), ast.unparse(fn.body[index + 1])
            assert index == 1 and "self._require_visitor" in guard, (cover.check, guard)
            assert after.startswith(f"return await self.{cover.via}.{scope.rsplit('.', 1)[1]}("), (cover.check, after)
        else:
            assert cover.check == (path, scope) and call.lineno < min(lines[(path, scope)]), cover.check


def test_the_ward_rooms_write_methods_are_reached_only_through_their_checks() -> None:
    """WM2 (D230; kills EV-11)."""
    rows = [(scope, cover) for (_path, scope), cover in STORE_WRITE_SCOPES.items() if isinstance(cover, StoreCheck) and cover.via]
    routes = {(cover.via, scope.rsplit(".", 1)[1]): cover.check for scope, cover in rows}
    owners = {scope.split(".", 1)[0] for scope, _cover in rows}
    assert len(routes) == 4 and owners == {"MessageStore", "ThreadManager"}, (sorted(routes), owners)
    chains: set[tuple[str, str, str, str]] = set()
    named: set[str] = set()
    handed: set[tuple[str, str, str, str]] = set()
    for rel, source in src_sources().items():
        if not any(word in source for word in (*_HOLDERS, *owners)):
            continue
        for scope, node in _scoped(ast.parse(source, filename=rel)):
            if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Attribute) and (node.value.attr, node.attr) in routes:
                chains.add((rel, scope, node.value.attr, node.attr))
            if isinstance(node, ast.Name) and node.id in owners:
                named.add(rel)
            if isinstance(node, ast.Call):
                for value in (*node.args, *(keyword.value for keyword in node.keywords)):
                    holder = _holder(value, rel)
                    if holder is not None:
                        handed.add((rel, scope, ast.unparse(node.func), holder))
            if isinstance(node, (ast.Assign, ast.AnnAssign, ast.Return)):
                holder = _holder(node.value, rel)
                if holder is not None:
                    handed.add((rel, scope, "=", holder))
    assert chains == {(*check, via, method) for (via, method), check in routes.items()}, sorted(chains)
    assert named == {_SERVICE}, sorted(named)
    assert handed == _HAND_OFFS, sorted(handed)
    for callee, rel in _CALLEE_MODULES.items():
        tree = ast.parse(src_sources()[rel], filename=rel)
        assert any(isinstance(node, ast.ClassDef) and node.name == callee for node in tree.body), (rel, callee)
        assert [hit for _via, method in routes for hit in references_outside(tree, method, ())] == [], rel


async def test_each_check_counts_missing_live_mismatch_and_revoked_and_a_post_counts_its_episode(
    tmp_path: Path, identities: IdentityService, stops: AgentStopService, tickets: TicketRegistry,
) -> None:
    """WM3 (#1604 property 1 at the Ward Room's and the episodic store's five checks; D234; kills EV-1, EV-3, EV-4, EV-5, EV-6, EV-12)."""
    service = AdmissionService(identities, stops, tickets=tickets, loop=asyncio.get_running_loop())
    room = WardRoomService(db_path=str(tmp_path / "ward_room.db"))
    memory = EpisodicMemory(db_path=str(tmp_path / "episodic" / "episodes.db"))
    chained = WardRoomService(db_path=str(tmp_path / "chained.db"), episodic_memory=memory)
    for each in (room, memory, chained):
        await each.start()
        each.set_admission(service)
    try:
        await _drive(room, memory, 1)
        hold = service.hold(presented_id=AGENT_A, work_kind="agentic_run", seam="agentic_run", child=False)
        try:
            await _drive(room, memory, 2)
            await stops.issue_stop(AGENT_A, reason="ad1346-m3e4b: the Captain stops the held work")
            await _drive(room, memory, 3)
        finally:
            hold.end()
        assert tickets.tally() == {
            ("issue", "ticket_issued"): 1,
            ("store_write", "ticket_missing"): 10, ("store_write", "ticket_live"): 7,
            ("store_write", "ticket_principal_mismatch"): 3, ("store_write", "ticket_revoked"): 10,
        }
        channel = await chained.get_channel_by_name("All Hands")
        assert channel is not None, "premise: the default channel"
        thread = await chained.create_thread(channel.id, AGENT_A, "ad1346 m3e4b chained", "oscar papa")
        await chained.create_post(thread.id, AGENT_A, "quebec romeo")
        assert tickets.tally()[("store_write", "ticket_missing")] == 14, "a thread and a post each count their episode's store too"
        assert service.failures == 0
    finally:
        for each in (chained, memory, room):
            await each.stop()


async def test_with_and_without_the_service_the_checked_writes_answer_identically(
    tmp_path: Path, identities: IdentityService, stops: AgentStopService, tickets: TicketRegistry,
) -> None:
    """WM4 (#1604 property 12 at the Ward Room's and the episodic store's five checks)."""
    service = AdmissionService(identities, stops, tickets=tickets, loop=asyncio.get_running_loop())
    rooms = [WardRoomService(db_path=str(tmp_path / f"ward_room_{i}.db")) for i in (0, 1)]
    memories = [EpisodicMemory(db_path=str(tmp_path / f"episodic_{i}" / "episodes.db")) for i in (0, 1)]
    for room, memory, held in zip(rooms, memories, (service, None)):
        await room.start()
        await memory.start()
        room.set_admission(held)
        memory.set_admission(held)
    try:
        first = [await _drive(room, memory, 1) for room, memory in zip(rooms, memories)]
        hold = service.hold(presented_id=AGENT_A, work_kind="agentic_run", seam="agentic_run", child=False)
        try:
            second = [await _drive(room, memory, 2) for room, memory in zip(rooms, memories)]
            await stops.issue_stop(AGENT_A, reason="ad1346-m3e4b: the golden test's stop")
            third = [await _drive(room, memory, 3) for room, memory in zip(rooms, memories)]
        finally:
            hold.end()
    finally:
        for room, memory in zip(rooms, memories):
            await memory.stop()
            await room.stop()
    assert first[0] == first[1] and second[0] == second[1] and third[0] == third[1]
    assert first[0][4] == ["Cannot endorse own content", "Only the original author can edit"], "premise: both refusals"
    assert first[0][5][:3] == [EpisodeStoreOutcome.STORED] * 3, "premise: the episodes were stored"
    assert tickets.tally() == {
        ("issue", "ticket_issued"): 1,
        ("store_write", "ticket_missing"): 10, ("store_write", "ticket_live"): 7,
        ("store_write", "ticket_principal_mismatch"): 3, ("store_write", "ticket_revoked"): 10,
    }
    assert service.failures == 0


async def test_a_booted_runtime_hands_its_service_to_the_ward_room_and_the_episodic_store(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """WM5 (D233: the production hand-off; AD-1346 M3e4d1: D286; kills EV-7, EV-8, ED-5, ED-6)."""
    memory = EpisodicMemory(db_path=str(tmp_path / "on" / "episodic" / "episodes.db"))
    runtime = ProbOSRuntime(
        config=_config(shadow_enabled=True), data_dir=tmp_path / "on" / "data", llm_client=MockLLMClient(),
        episodic_memory=memory,
    )
    await asyncio.wait_for(runtime.start(), timeout=600)
    try:
        service = runtime.admission_service
        room = runtime.ward_room
        assert type(service) is AdmissionService and type(room) is WardRoomService, "premise: the boot built both"
        assert vars(room)["_admission"] is service and vars(memory)["_admission"] is service
        notes, skills = runtime.clinical_notes_store, runtime.skill_request_store
        assert type(notes) is ClinicalNotesStore and type(skills) is SkillRequestStore, "premise: the boot built both stores"
        assert vars(notes)["_admission"] is service and vars(skills)["_admission"] is service  # AD-1346 M3e4d1
        seen: list[tuple[bool, object]] = []

        def record(self: AdmissionService, *, effect: str, presented_id: object) -> None:
            if effect == EFFECT_STORE_WRITE:
                seen.append((self is service, presented_id))

        monkeypatch.setattr(AdmissionService, "check_ticket", record)
        channel = await room.get_channel_by_name("All Hands")
        assert channel is not None, "premise: the default channel"
        await room.create_thread(channel.id, AGENT_A, "ad1346 m3e4b boot", "sierra tango")
        await memory.store(Episode(id="ad1346-m3e4b-boot", user_input="ad1346 m3e4b uniform", agent_ids=[AGENT_B]))
        assert (True, AGENT_A) in seen and (True, AGENT_B) in seen and all(ours for ours, _id in seen), seen
        marks = [len(seen)]  # AD-1346 M3e4d1: the check each of the next three calls records first
        await notes.write_note(target_agent_id=AGENT_A, author_agent_id=AGENT_B, body="ad1346 m3e4d1 victor")
        marks.append(len(seen))
        filed = await skills.file_request(AGENT_A, "ad1346-m3e4d1-skill", justification="ad1346 m3e4d1 whiskey")
        marks.append(len(seen))
        await skills.decide(filed.id, True, reason="ad1346 m3e4d1 xray", decided_by=AGENT_B)
        assert [seen[mark] for mark in marks] == [(True, AGENT_B), (True, AGENT_A), (True, AGENT_B)], (marks, seen)
    finally:
        await asyncio.wait_for(runtime.stop(), timeout=600)
    off_memory = EpisodicMemory(db_path=str(tmp_path / "off" / "episodic" / "episodes.db"))
    off = ProbOSRuntime(
        config=_config(shadow_enabled=False), data_dir=tmp_path / "off" / "data", llm_client=MockLLMClient(),
        episodic_memory=off_memory,
    )
    await asyncio.wait_for(off.start(), timeout=600)
    try:
        assert off.admission_service is None and type(off.ward_room) is WardRoomService, "premise: shadow off, Ward Room on"
        assert vars(off.ward_room)["_admission"] is None and vars(off_memory)["_admission"] is None
        off_notes, off_skills = off.clinical_notes_store, off.skill_request_store
        assert type(off_notes) is ClinicalNotesStore and type(off_skills) is SkillRequestStore, "premise: both stores built"
        assert vars(off_notes)["_admission"] is None and vars(off_skills)["_admission"] is None  # AD-1346 M3e4d1
    finally:
        await asyncio.wait_for(off.stop(), timeout=600)


async def _note_file_decide(notes: ClinicalNotesStore, skills: SkillRequestStore, phase: int) -> list[object]:
    """AD-1346 M3e4d1: one round of four checked writes: a note by ``AGENT_A`` and one by ``AGENT_B``, a filing by
    ``AGENT_A`` and its decision by ``AGENT_B``. Returns each answer without the fields a fresh store draws."""
    answers: list[object] = [
        _shape(await notes.write_note(target_agent_id=AGENT_B, author_agent_id=AGENT_A, body=f"ad1346 m3e4d1 alpha {phase}")),
        _shape(await notes.write_note(target_agent_id=AGENT_A, author_agent_id=AGENT_B, body=f"ad1346 m3e4d1 bravo {phase}")),
    ]
    filed = await skills.file_request(AGENT_A, f"ad1346-m3e4d1-skill-{phase}", justification=f"ad1346 m3e4d1 charlie {phase}")
    answers.append(_shape(filed))
    answers.append(_shape(await skills.decide(filed.id, True, reason=f"ad1346 m3e4d1 delta {phase}", decided_by=AGENT_B)))
    return answers


async def test_the_note_filing_and_decision_checks_count_missing_live_mismatch_and_revoked(
    tmp_path: Path, identities: IdentityService, stops: AgentStopService, tickets: TicketRegistry,
) -> None:
    """WM6 (#1604 property 1 at the three AD-1346 M3e4d1 checks; D285; kills ED-4, ED-7, ED-8)."""
    service = AdmissionService(identities, stops, tickets=tickets, loop=asyncio.get_running_loop())
    notes = ClinicalNotesStore(db_path=str(tmp_path / "clinical_notes.db"))
    skills = SkillRequestStore(db_path=str(tmp_path / "skill_requests.db"))
    await notes.start()
    await skills.start()
    notes.set_admission(service)
    skills.set_admission(service)
    try:
        await _note_file_decide(notes, skills, 1)
        hold = service.hold(presented_id=AGENT_A, work_kind="agentic_run", seam="agentic_run", child=False)
        try:
            await _note_file_decide(notes, skills, 2)
            await stops.issue_stop(AGENT_A, reason="ad1346-m3e4d1: the Captain stops the held work")
            await _note_file_decide(notes, skills, 3)
        finally:
            hold.end()
        assert tickets.tally() == {
            ("issue", "ticket_issued"): 1,
            ("store_write", "ticket_missing"): 4, ("store_write", "ticket_live"): 2,
            ("store_write", "ticket_principal_mismatch"): 2, ("store_write", "ticket_revoked"): 4,
        }
        assert service.failures == 0
    finally:
        await skills.stop()
        await notes.stop()


async def test_with_and_without_the_service_the_note_filing_and_decision_answer_identically(
    tmp_path: Path, identities: IdentityService, stops: AgentStopService, tickets: TicketRegistry,
) -> None:
    """WM7 (#1604 property 12 at the three AD-1346 M3e4d1 checks; D287)."""
    service = AdmissionService(identities, stops, tickets=tickets, loop=asyncio.get_running_loop())
    pairs = [
        (ClinicalNotesStore(db_path=str(tmp_path / f"clinical_notes_{i}.db")), SkillRequestStore(db_path=str(tmp_path / f"skill_requests_{i}.db")))
        for i in (0, 1)
    ]
    for (notes, skills), held in zip(pairs, (service, None)):
        await notes.start()
        await skills.start()
        notes.set_admission(held)
        skills.set_admission(held)
    try:
        first = [await _note_file_decide(notes, skills, 1) for notes, skills in pairs]
        hold = service.hold(presented_id=AGENT_A, work_kind="agentic_run", seam="agentic_run", child=False)
        try:
            second = [await _note_file_decide(notes, skills, 2) for notes, skills in pairs]
            await stops.issue_stop(AGENT_A, reason="ad1346-m3e4d1: the golden test's stop")
            third = [await _note_file_decide(notes, skills, 3) for notes, skills in pairs]
        finally:
            hold.end()
    finally:
        for notes, skills in pairs:
            await skills.stop()
            await notes.stop()
    assert first[0] == first[1] and second[0] == second[1] and third[0] == third[1]
    assert first[0][0]["author_agent_id"] == AGENT_A, "premise: the note was stored with its author"
    assert first[0][3]["status"] == "approved" and first[0][3]["decided_by"] == AGENT_B, "premise: the decision was stored"
    assert tickets.tally() == {
        ("issue", "ticket_issued"): 1,
        ("store_write", "ticket_missing"): 4, ("store_write", "ticket_live"): 2,
        ("store_write", "ticket_principal_mismatch"): 2, ("store_write", "ticket_revoked"): 4,
    }
    assert service.failures == 0
