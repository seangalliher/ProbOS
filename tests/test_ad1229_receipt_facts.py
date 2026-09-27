"""AD-1229 (#1202): the body-free DM receipt facts, and the DM channel naming rule.

The facts are what the Ward Room already stores about a direct message an agent
wrote: the thread row, who posted in it, and who wrote elsewhere in the same DM
channel afterwards. They are read as per-author aggregates by statements that
never name a body column; the thread statement names the title only to hand it
to ``addressed_callsign``, so the one piece of title text that reaches a receipt
is the callsign a producer addressed the DM to (F5, F8, F9).

The naming rule is promoted out of ``ChannelManager.get_or_create_dm_channel`` so
the reader derives a channel name exactly as the writer does; the literal pins
below keep that rule from drifting silently, because the manager now calls the
same function and a comparison with it alone could no longer disagree.

Every test that starts a ``WardRoomService`` stops it in teardown (an unstopped
aiosqlite worker keeps the interpreter alive), and writes whose order a test
asserts are spaced by 30 ms (Windows can stamp back-to-back writes identically).
"""

from __future__ import annotations

import ast
import asyncio
import hashlib
import inspect
import re
import sqlite3
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, fields
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import probos.ward_room.receipt_facts as receipt_facts
from probos.crew_profile import CallsignRegistry
from probos.proactive import ProactiveCognitiveLoop
from probos.substrate.identity import generate_pool_ids
from probos.substrate.registry import AgentRegistry
from probos.ward_room import WardRoomService
from probos.ward_room.channels import (
    captain_dm_channel_name,
    dm_channel_keys,
    dm_channel_name,
)
from probos.ward_room.receipt_facts import MAX_CHANNEL_NAMES, MAX_THREADS

SENDER = generate_pool_ids("counselor", "counselor", 1)[0]
RECIP = generate_pool_ids("security_officer", "security_officer", 1)[0]
LAFORGE = generate_pool_ids("engineering_officer", "engineering_officer", 1)[0]
OPS = generate_pool_ids("operations_officer", "operations_officer", 1)[0]
SECOND_COUNSELOR = generate_pool_ids("counselor", "counselor", 2)[1]
SENTINELS = ("SECRET_TITLE_", "SECRET_BODY_", "SECRET_REPLY_")
_TABLES = (
    "channels", "threads", "posts", "memberships", "endorsements", "credibility", "mod_actions",
)


@dataclass
class _WardRoomRig:
    service: WardRoomService
    events: list[Any]
    db_path: Path


@pytest.fixture
async def ward_room(tmp_path: Path) -> AsyncIterator[_WardRoomRig]:
    events: list[Any] = []
    db_path = tmp_path / "wr.db"
    service = WardRoomService(
        db_path=str(db_path), emit_event=lambda event_type, _data: events.append(event_type),
    )
    await service.start()
    try:
        yield _WardRoomRig(service=service, events=events, db_path=db_path)
    finally:
        await service.stop()


async def _tick() -> None:
    await asyncio.sleep(0.03)


def _table_digest(db_path: Path) -> dict[str, str]:
    con = sqlite3.connect(str(db_path))
    try:
        return {
            table: hashlib.sha256(
                "\n".join(sorted(repr(row) for row in con.execute(f"SELECT * FROM {table}"))).encode(),
            ).hexdigest()
            for table in _TABLES
        }
    finally:
        con.close()


def _soft_delete(db_path: Path, post_id: str) -> None:
    con = sqlite3.connect(str(db_path))
    try:
        con.execute("UPDATE posts SET deleted = 1 WHERE id = ?", (post_id,))
        con.commit()
    finally:
        con.close()


def _counts(activity: tuple[Any, ...]) -> dict[str, int]:
    return {a.author_id: a.count for a in activity}


def _agent(agent_type: str, callsign: str) -> SimpleNamespace:
    return SimpleNamespace(
        id=generate_pool_ids(agent_type, agent_type, 1)[0], agent_type=agent_type, pool=agent_type,
        callsign=callsign, is_alive=True, capabilities=[],
    )


# ── F1-F9: the facts reader, through the service's public delegate ──────


async def test_facts_count_replies_and_later_activity_without_reading_content(
    ward_room: _WardRoomRig,
) -> None:
    ws = ward_room.service
    dm = await ws.get_or_create_dm_channel(SENDER, RECIP, "Ezri", "Worf")
    lf = await ws.get_or_create_dm_channel(SENDER, LAFORGE, "Ezri", "LaForge")
    cap = await ws.create_channel(captain_dm_channel_name(SENDER), "dm", SENDER)
    t0 = await ws.create_thread(lf.id, LAFORGE, "[DM to @Ezri] SECRET_TITLE_0", "SECRET_BODY_0", "LaForge")
    await _tick()
    t1 = await ws.create_thread(dm.id, SENDER, "[DM to @Worf] SECRET_TITLE_1", "SECRET_BODY_1", "Ezri")
    await _tick()
    await ws.create_post(t1.id, RECIP, "SECRET_REPLY_1", author_callsign="Worf")
    await _tick()
    await ws.create_post(t1.id, "system", "SECRET_REPLY_system")
    await _tick()
    await ws.create_post(t1.id, "captain", "SECRET_REPLY_captain")
    await _tick()
    deleted = await ws.create_post(t1.id, RECIP, "SECRET_REPLY_deleted", author_callsign="Worf")
    _soft_delete(ward_room.db_path, deleted.id)
    await _tick()
    await ws.create_post(t1.id, SENDER, "SECRET_REPLY_own", author_callsign="Ezri")
    await _tick()
    t2 = await ws.create_thread(dm.id, SENDER, "[DM to @Worf] SECRET_TITLE_2", "SECRET_BODY_2", "Ezri")
    await _tick()
    await ws.create_post(t2.id, RECIP, "SECRET_REPLY_2", author_callsign="Worf")
    await _tick()
    t_back = await ws.create_thread(dm.id, RECIP, "[DM to @Ezri] SECRET_TITLE_b", "SECRET_BODY_b", "Worf")
    await _tick()
    t3 = await ws.create_thread(lf.id, SENDER, "[DM to @LaForge] SECRET_TITLE_3", "SECRET_BODY_3", "Ezri")
    await _tick()
    t4 = await ws.create_thread(cap.id, SENDER, "[DM to Captain] SECRET_TITLE_4", "SECRET_BODY_4", "Ezri")
    await _tick()
    await ws.create_post(t4.id, "captain", "SECRET_REPLY_4")
    stamps = [t0.created_at, t1.created_at, t2.created_at, t_back.created_at, t3.created_at, t4.created_at]
    assert stamps == sorted(stamps) and len(set(stamps)) == len(stamps), "premise: ordered, distinct thread times"

    page = await ws.dm_receipt_facts(SENDER, since=time.time() - 3600, limit=10)

    assert [f.thread_id for f in page.threads] == [t4.id, t3.id, t2.id, t1.id]
    assert page.truncated is False
    by_id = {f.thread_id: f for f in page.threads}
    first = by_id[t1.id]
    assert first.channel_name == dm.name and first.archived is False
    # The soft-deleted reply and the sender's own post are not activity; system and
    # captain posts are returned for the caller to classify.
    assert [a.author_id for a in first.in_thread] == [RECIP, "system", "captain"]
    assert _counts(first.in_thread) == {RECIP: 1, "system": 1, "captain": 1}
    assert all(a.first_at <= a.last_at for a in first.in_thread)
    assert _counts(first.later_in_channel) == {RECIP: 2}
    second = by_id[t2.id]
    assert _counts(second.in_thread) == {RECIP: 1}
    assert _counts(second.later_in_channel) == {RECIP: 1}
    # LaForge wrote first, then the DM went unanswered: earlier activity is not "later".
    unanswered = by_id[t3.id]
    assert unanswered.channel_name == lf.name
    assert unanswered.in_thread == () and unanswered.later_in_channel == ()
    captain = by_id[t4.id]
    assert captain.channel_name == captain_dm_channel_name(SENDER)
    assert _counts(captain.in_thread) == {"captain": 1} and captain.later_in_channel == ()
    rendered = repr(page)
    assert not [s for s in SENTINELS if s in rendered]


@pytest.mark.parametrize("case", ["scoped", "empty_author"])
async def test_facts_are_scoped_to_the_author_and_refuse_an_empty_author(
    case: str, ward_room: _WardRoomRig,
) -> None:
    ws = ward_room.service
    dm = await ws.get_or_create_dm_channel(SENDER, RECIP, "Ezri", "Worf")
    mine = await ws.create_thread(dm.id, SENDER, "[DM to @Worf]", "hello", "Ezri")
    await _tick()
    theirs = await ws.create_thread(dm.id, RECIP, "[DM to @Ezri]", "hello back", "Worf")
    since = time.time() - 3600

    if case == "scoped":
        assert [f.thread_id for f in (await ws.dm_receipt_facts(SENDER, since=since, limit=10)).threads] == [mine.id]
        assert [f.thread_id for f in (await ws.dm_receipt_facts(RECIP, since=since, limit=10)).threads] == [theirs.id]
        assert (await ws.dm_receipt_facts(LAFORGE, since=since, limit=10)).threads == ()
    else:
        with pytest.raises(ValueError, match="AD-1229"):
            await ws.dm_receipt_facts("", since=since, limit=10)


@pytest.mark.parametrize("case", ["window", "channel_filter", "truncation"])
async def test_window_channel_filter_and_truncation(case: str, ward_room: _WardRoomRig) -> None:
    ws = ward_room.service
    dm = await ws.get_or_create_dm_channel(SENDER, RECIP, "Ezri", "Worf")
    lf = await ws.get_or_create_dm_channel(SENDER, LAFORGE, "Ezri", "LaForge")
    long_ago = time.time() - 3600

    async def ids(**kwargs: Any) -> list[str]:
        return [f.thread_id for f in (await ws.dm_receipt_facts(SENDER, **kwargs)).threads]

    if case == "window":
        older = await ws.create_thread(dm.id, SENDER, "[DM to @Worf]", "one", "Ezri")
        await _tick()
        boundary = time.time()
        await _tick()
        newer = await ws.create_thread(dm.id, SENDER, "[DM to @Worf]", "two", "Ezri")
        assert await ids(since=boundary, limit=10) == [newer.id]
        assert await ids(since=long_ago, limit=10) == [newer.id, older.id]
        assert await ids(since=time.time() + 60, limit=10) == []
    elif case == "channel_filter":
        to_worf = await ws.create_thread(dm.id, SENDER, "[DM to @Worf]", "one", "Ezri")
        await _tick()
        to_laforge = await ws.create_thread(lf.id, SENDER, "[DM to @LaForge]", "two", "Ezri")
        assert await ids(since=long_ago, limit=10, channel_names=(dm.name,)) == [to_worf.id]
        assert await ids(since=long_ago, limit=10, channel_names=(dm.name, lf.name)) == [to_laforge.id, to_worf.id]
        assert await ids(since=long_ago, limit=10, channel_names=(dm_channel_name(SENDER, OPS),)) == []
    else:
        made = []
        for n in range(3):
            made.append(await ws.create_thread(dm.id, SENDER, "[DM to @Worf]", f"number {n}", "Ezri"))
            await _tick()
        two = await ws.dm_receipt_facts(SENDER, since=long_ago, limit=2)
        assert [f.thread_id for f in two.threads] == [made[2].id, made[1].id]
        assert two.truncated is True
        three = await ws.dm_receipt_facts(SENDER, since=long_ago, limit=3)
        assert len(three.threads) == 3 and three.truncated is False


@pytest.mark.parametrize(
    "case", ["limit_zero", "limit_twenty_one", "limit_bool", "since_nan", "too_many_channel_names"],
)
async def test_threads_by_author_validates_its_bounds(case: str, ward_room: _WardRoomRig) -> None:
    ws = ward_room.service
    valid: dict[str, Any] = {"since": 0.0, "limit": MAX_THREADS, "channel_names": ("dm-a-b",) * MAX_CHANNEL_NAMES}
    page = await ws.dm_receipt_facts(SENDER, **valid)
    assert page.threads == () and page.truncated is False, "premise: the neighbouring valid call is accepted"
    bad = dict(valid)
    if case == "limit_zero":
        bad["limit"] = 0
    elif case == "limit_twenty_one":
        bad["limit"] = MAX_THREADS + 1
    elif case == "limit_bool":
        bad["limit"] = True
    elif case == "since_nan":
        bad["since"] = float("nan")
    else:
        bad["channel_names"] = tuple(f"dm-a{i}-b" for i in range(MAX_CHANNEL_NAMES + 1))

    with pytest.raises(ValueError, match="AD-1229"):
        await ws.dm_receipt_facts(SENDER, **bad)


def _non_docstring_strings(source: str) -> list[str]:
    tree = ast.parse(source)
    docstrings: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            head = node.body[0] if node.body else None
            if isinstance(head, ast.Expr) and isinstance(head.value, ast.Constant):
                docstrings.add(id(head.value))
    return [
        node.value for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docstrings
    ]


# Was test_no_statement_selects_a_body_or_title: A-3 selects the title in the thread statement, only for
# addressed_callsign to read the callsign a producer addressed; no statement selects a body.
def test_no_statement_selects_a_body_and_the_title_reaches_only_the_parser() -> None:
    content = re.compile(r"\b(body|title)\b", re.IGNORECASE)
    body, title = re.compile(r"\bbody\b", re.IGNORECASE), re.compile(r"\btitle\b", re.IGNORECASE)
    assert content.search("SELECT t.title, p.body FROM posts p"), "premise: the scan sees a content column"
    source = inspect.getsource(receipt_facts)
    strings = _non_docstring_strings(source)
    statements = [s for s in strings if "SELECT" in s]
    assert len(statements) == 4, "premise: the scan reached the four SELECT statements"
    assert any("FROM threads" in s for s in statements) and any("FROM posts" in s for s in statements)

    assert [s for s in strings if body.search(s)] == []
    assert [s for s in strings if title.search(s)] == [receipt_facts._DM_THREADS_HEAD]
    assert not {"title", "body"} & {f.name for f in fields(receipt_facts.DmThreadFacts)}
    assert source.count("row[4]") == 1 and source.count("addressed_callsign(row[4])") == 1


async def test_reading_facts_changes_no_table_and_emits_nothing(ward_room: _WardRoomRig) -> None:
    ws = ward_room.service
    dm = await ws.get_or_create_dm_channel(SENDER, RECIP, "Ezri", "Worf")
    thread = await ws.create_thread(dm.id, SENDER, "[DM to @Worf]", "hello", "Ezri")
    await ws.create_post(thread.id, RECIP, "hi", author_callsign="Worf")
    before, emitted = _table_digest(ward_room.db_path), len(ward_room.events)

    await ws.dm_receipt_facts(SENDER, since=0.0, limit=10)
    await ws.dm_receipt_facts(SENDER, since=0.0, limit=1, channel_names=(dm.name,))
    await ws.dm_receipt_facts(RECIP, since=0.0, limit=10)

    assert _table_digest(ward_room.db_path) == before
    assert len(ward_room.events) == emitted
    await ws.create_post(thread.id, RECIP, "one more", author_callsign="Worf")
    assert _table_digest(ward_room.db_path) != before, "premise: the digest sees a real write"


@pytest.mark.parametrize("case", ["before_start", "in_memory_mode", "after_stop"])
async def test_the_delegate_before_start_and_without_a_database(case: str, tmp_path: Path) -> None:
    service = WardRoomService() if case == "in_memory_mode" else WardRoomService(db_path=str(tmp_path / "wr.db"))
    try:
        if case != "before_start":
            await service.start()
        if case == "after_stop":
            dm = await service.get_or_create_dm_channel(SENDER, RECIP, "Ezri", "Worf")
            await service.create_thread(dm.id, SENDER, "[DM to @Worf]", "hello", "Ezri")
            stored = await service.dm_receipt_facts(SENDER, since=0.0, limit=10)
            assert len(stored.threads) == 1, "premise: the running service reads the stored DM"
            await service.stop()
            assert service.is_started is False
        page = await service.dm_receipt_facts(SENDER, since=0.0, limit=10)
        assert page.threads == () and page.truncated is False
    finally:
        await service.stop()


_PARSER_CASES = [
    ("producer_crew", "[DM to @Worf]", "Worf"),
    ("apostrophe", "[DM to @O'Brien]", "O'Brien"),
    ("lowercase", "[DM to @worf]", "worf"),
    ("counselor_space", "[Counselor check-in with @Number One]", "Number One"),
    ("sixty_four", "[DM to @" + "x" * 64 + "]", "x" * 64),
    ("counselor_empty", "[Counselor check-in with @]", None),
    ("trailing_text", "[DM to @Worf] SECRET_TITLE_1", None),
    ("captain_title", "[DM to Captain from @Ezri]", None),
    ("boot_camp_title", "Welcome aboard, Worf", None),
    ("empty", "", None),
    ("none", None, None),
    ("not_a_string", 7, None),
    ("sixty_five", "[DM to @" + "x" * 65 + "]", None),
    ("inner_bracket", "[DM to @a]b]", None),
    ("newline", "[DM to @a\nb]", None),
    ("prefix_case", "[dm to @Worf]", None),
    ("trailing_newline", "[DM to @Worf]\n", None),
    ("leading_text", "x[DM to @Worf]", None),
]


@pytest.mark.parametrize(
    ("title", "expected"), [case[1:] for case in _PARSER_CASES], ids=[case[0] for case in _PARSER_CASES],
)
def test_addressed_callsign_parses_only_the_two_producer_titles(title: object, expected: str | None) -> None:
    assert receipt_facts.addressed_callsign(title) == expected


async def test_the_page_carries_the_addressed_callsign_and_never_the_title(ward_room: _WardRoomRig) -> None:
    ws = ward_room.service
    dm = await ws.get_or_create_dm_channel(SENDER, RECIP, "Ezri", "Worf")
    addressed = {
        "[DM to @Worf]": "Worf",
        "[Counselor check-in with @Number One]": "Number One",
        "[DM to @Worf] SECRET_TITLE_9": None,
        "[DM]": None,
    }
    titles: dict[str, str] = {}
    for n, title in enumerate(addressed):
        thread = await ws.create_thread(dm.id, SENDER, title, f"SECRET_BODY_{n}", "Ezri")
        titles[thread.id] = title
        await _tick()

    page = await ws.dm_receipt_facts(SENDER, since=time.time() - 3600, limit=10)

    assert len(page.threads) == len(addressed), "premise: every stored DM was read"
    assert {titles[f.thread_id]: f.addressed for f in page.threads} == addressed
    rendered = repr(page)
    assert not [s for s in SENTINELS if s in rendered]


# ── N1, N2, X1: the naming rule the reader shares with the writers ──────


async def test_dm_channel_name_matches_the_channel_manager_and_the_pinned_names(
    ward_room: _WardRoomRig,
) -> None:
    ws = ward_room.service
    for a, b in ((SENDER, RECIP), (SENDER, OPS), (SENDER, SECOND_COUNSELOR)):
        forward = await ws.get_or_create_dm_channel(a, b)
        backward = await ws.get_or_create_dm_channel(b, a)
        assert forward.id == backward.id
        assert forward.name == dm_channel_name(a, b) == dm_channel_name(b, a)
    assert dm_channel_name(SENDER, RECIP) == "dm-counselo-security"
    assert dm_channel_name(OPS, SENDER) == "dm-counselo-operatio"
    assert dm_channel_name(SENDER, SECOND_COUNSELOR) == "dm-counselo-counselo"


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("dm-counselo-security", ("counselo", "security")),
        ("dm-captain-counselo", ("captain", "counselo")),
        ("dm-a-b-c", None),
        ("xx-counselo-security", None),
        ("dm--security", None),
    ],
    ids=["crew", "captain", "four_parts", "wrong_prefix", "empty_key"],
)
def test_dm_channel_keys_parses_only_three_part_dm_names(
    name: str, expected: tuple[str, str] | None,
) -> None:
    assert dm_channel_keys(name) == expected


async def test_captain_dm_channel_name_matches_the_proactive_producer(ward_room: _WardRoomRig) -> None:
    ws = ward_room.service
    ezri = _agent("counselor", "Ezri")
    agents = AgentRegistry()
    await agents.register(ezri)
    callsigns = CallsignRegistry()
    callsigns.set_callsign("counselor", "Ezri")
    callsigns.bind_registry(agents)
    loop = ProactiveCognitiveLoop()
    loop.set_runtime(SimpleNamespace(
        ward_room=ws, registry=agents, callsign_registry=callsigns, hebbian_router=None,
        emit_event=lambda *_args, **_kwargs: None,
    ))

    _, actions = await loop.extract_and_execute_dms(ezri, "[DM @captain] Crew check-ins are on schedule. [/DM]")

    assert actions == [{"type": "dm", "target_callsign": "captain", "target_agent_id": "captain"}]
    channel = await ws.get_channel_by_name(captain_dm_channel_name(ezri.id))
    assert channel is not None and channel.channel_type == "dm"
    assert [t.author_id for t in await ws.list_threads(channel.id)] == [ezri.id]
    page = await ws.dm_receipt_facts(ezri.id, since=time.time() - 3600, limit=10)
    assert [f.channel_name for f in page.threads] == [captain_dm_channel_name(ezri.id)]
