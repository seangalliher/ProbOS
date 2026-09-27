"""AD-1229 (#1202): message_receipts -- an agent reads what became of a DM it sent.

The Counselor's question on #1202 was "did this reach anyone, and did anything
come back". These tests pin that the tool answers it from facts the Ward Room
already stores, and nothing else:

* the recipient is PROVEN from the channel name the writer used and the callsign
  its title addressed, or it is not named at all (R1, R3, T10-T12, T15) -- a
  shared name key is never guessed, and a receipt from one never claims delivery;
* a recipient filter lists only proven messages and counts the rest (T11, T13),
  and every model-facing label passes the gap and referent gates (T14);
* every value is a closed code, a registry label, a count or a UTC time, and the
  receipt's constructor refuses anything else (R2), so there is no id, title,
  body or free text to leak (T9) and nothing reads as a causal claim (T7);
* ``read`` is always ``not_recorded`` because the store keeps no read record;
* the tool writes nothing and touches no learning service (T8);
* off is byte-identical: the executor's offered tool list does not change (W1).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import sqlite3
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest
import yaml

from probos.tools.message_receipts_tool import (
    CAPTAIN_CHANNEL,
    CAPTAIN_DM,
    CAPTAIN_LABEL,
    CREW_DM,
    CREW_MEMBER_LABEL,
    DELIVERED,
    EXACT,
    LABEL_RE,
    LIMIT_MAX,
    NO_REGISTERED_RECIPIENT,
    NO_REPLY_YET,
    NOTE_EMPTY,
    NOTE_UNCONFIRMED,
    OTHER_DM,
    R_FAULT,
    R_IDENTITY,
    R_NOT_ABOARD,
    R_RECIPIENT,
    R_SELF,
    R_WARD_ROOM,
    R_WHOLE,
    READ_NOT_RECORDED,
    RECIPIENT_BASES,
    REPLIED,
    REPLY_CODES,
    SHARED_KEY,
    UNCONFIRMED,
    UNKNOWN,
    UNRECOGNISED_CHANNEL,
    UNREGISTERED_KEY,
    UNREGISTERED_LABEL,
    WINDOW_DEFAULT_HOURS,
    WINDOW_MAX_HOURS,
    MessageReceipt,
    MessageReceiptsTool,
    _is_label,
    build_receipt,
    classify_dm_recipient,
)
from probos.cognitive.counselor import CounselorAgent
from probos.cognitive.decomposer import is_capability_gap
from probos.cognitive.referent_gate import _HEX_RE, extract_referents
from probos.config import SystemConfig, WardRoomConfig
from probos.crew_profile import CallsignRegistry
from probos.proactive import ProactiveCognitiveLoop
from probos.substrate.identity import generate_pool_ids
from probos.substrate.registry import AgentRegistry
from probos.tools.registry import ToolRegistry
from probos.ward_room import WardRoomService
from probos.ward_room.channels import CAPTAIN_DM_KEY, captain_dm_channel_name, dm_channel_name
from probos.ward_room.receipt_facts import AuthorActivity, DmThreadFacts
from tests.test_ad1229_message_receipts_e2e import _make_counselor

# Real ids for the (agent_type, pool) pairs in startup/agent_fleet.py (the P-C census).
_PAIRS = [
    ("counselor", "counselor"), ("yeoman", "yeoman"), ("security_officer", "security_officer"),
    ("operations_officer", "operations_officer"), ("training_officer", "training_officer"),
    ("engineering_officer", "engineering_officer"),
    ("performance_monitor", "engineering_performance"), ("maintenance", "engineering_maintenance"),
    ("damage_control", "engineering_damage_control"),
    ("operations_resource_allocator", "operations_resource_allocator"),
    ("operations_scheduler", "operations_scheduler"), ("operations_coordinator", "operations_coordinator"),
]
_IDS = {agent_type: generate_pool_ids(agent_type, pool, 1)[0] for agent_type, pool in _PAIRS}
_COUNSELOR = _IDS["counselor"]
_WORF = _IDS["security_officer"]
_OPS = _IDS["operations_officer"]
_REGISTERED = tuple(_IDS.values())
_SECOND_COUNSELOR = generate_pool_ids("counselor", "counselor", 2)[1]
_SECOND_WORF = generate_pool_ids("security_officer", "security_officer", 2)[1]
_ARCHITECT = generate_pool_ids("architect", "architect", 1)[0]
_OPS_TYPES = ("operations_officer", "operations_resource_allocator", "operations_scheduler", "operations_coordinator")
_OPS_HOLDERS = tuple(sorted(_IDS[t] for t in _OPS_TYPES))
_T0 = 1_790_000_000.0
SENTINELS = ("SECRET_TITLE_", "SECRET_BODY_", "SECRET_REPLY_")
# The review's input: a hex referent, a sentinel and a gap phrase, sent as a recipient.
_HOSTILE_RECIPIENT = "9f3c2ab1e SECRET_BODY_42 I cannot see that"
# S7 (A-3): callsigns LABEL_RE admits that read as a gap claim and carry a hex referent.
_HOSTILE_CALLSIGN = "Xy 9f3c2ab1e I cannot see that"
_HOSTILE_CALLSIGN_2 = "Zq 9f3c2ab1e unable to see"
_TABLES = (
    "channels", "threads", "posts", "memberships", "endorsements", "credibility", "mod_actions",
)
_RECEIPT_KEYS = [
    "to", "channel", "sent_at", "delivery", "recipient_basis", "archived", "reply",
    "recipient_replies", "first_reply_at", "last_reply_at", "later_in_channel", "replied_by", "read",
]
_UTC_RE = re.compile(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} UTC")


# ── shared rigs ─────────────────────────────────────────────────────────


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


@dataclass
class _Crew:
    agents: AgentRegistry
    callsigns: CallsignRegistry
    ids: dict[str, str]


async def _crew(
    *members: tuple[str, str | None], extra_callsigns: dict[str, str] | None = None,
) -> _Crew:
    """Real registries over (agent_type, callsign-or-None) members, ids from generate_pool_ids."""
    agents = AgentRegistry()
    callsigns = CallsignRegistry()
    ids: dict[str, str] = {}
    for agent_type, callsign in members:
        agent = SimpleNamespace(
            id=generate_pool_ids(agent_type, agent_type, 1)[0], agent_type=agent_type, pool=agent_type,
            callsign=callsign or "", is_alive=True, capabilities=[],
        )
        await agents.register(agent)
        if callsign:
            callsigns.set_callsign(agent_type, callsign)
        ids[callsign or agent_type] = agent.id
    for agent_type, callsign in (extra_callsigns or {}).items():
        callsigns.set_callsign(agent_type, callsign)
    callsigns.bind_registry(agents)
    return _Crew(agents=agents, callsigns=callsigns, ids=ids)


async def _standard_crew() -> _Crew:
    return await _crew(
        ("counselor", "Ezri"), ("security_officer", "Worf"), ("engineering_officer", "LaForge"),
        extra_callsigns={"medical_officer": "Crusher"},
    )


def _runtime(ward_room: Any, crew: _Crew) -> SimpleNamespace:
    attrs: dict[str, Any] = {"registry": crew.agents, "callsign_registry": crew.callsigns}
    if ward_room is not None:
        attrs["ward_room"] = ward_room
    return SimpleNamespace(**attrs)


def _registered(runtime: Any) -> ToolRegistry:
    tools = ToolRegistry()
    tools.register(
        MessageReceiptsTool(runtime=runtime), provider="AD-1229", tags=["message_receipts", "ward_room"],
    )
    return tools


async def _ask(
    tools: ToolRegistry, agent_id: str, params: dict[str, Any] | None = None,
    *, context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    result = await tools.check_and_invoke(
        agent_id, "message_receipts", params or {}, agent_rank="ensign", context=context,
    )
    assert result.error is None, result.error
    return result.output


async def _crew_dm(ws: WardRoomService, sender_id: str, recipient_id: str, *, to: str, **text: str) -> Any:
    channel = await ws.get_or_create_dm_channel(sender_id, recipient_id)
    return await ws.create_thread(  # the default title is the producer's own form (proactive.py:4809)
        channel.id, sender_id, text.get("title", f"[DM to @{to}]"), text.get("body", "hello"),
    )


async def _captain_dm(ws: WardRoomService, sender_id: str, **text: str) -> Any:
    name = captain_dm_channel_name(sender_id)
    channel = await ws.get_channel_by_name(name) or await ws.create_channel(name, "dm", sender_id)
    return await ws.create_thread(
        channel.id, sender_id, text.get("title", "[DM to Captain]"), text.get("body", "report"),
    )


async def _proactive_dm(ws: WardRoomService, crew: _Crew, sender_id: str, text: str) -> list[dict[str, Any]]:
    """The real proactive ``[DM @x]`` producer; a fresh loop per send, so no cooldown carries between sends."""
    loop = ProactiveCognitiveLoop()
    loop.set_runtime(SimpleNamespace(
        ward_room=ws, registry=crew.agents, callsign_registry=crew.callsigns, hebbian_router=None,
        emit_event=lambda *_args, **_kwargs: None,
    ))
    _, actions = await loop.extract_and_execute_dms(crew.agents.get(sender_id), text)
    return actions


async def _counselor_check_ins(ws: WardRoomService, crew: _Crew) -> None:
    """S4: real AD-505 DMs to a callsign-less agent titled by its type, its id and its empty callsign, then O'Brien."""
    coordinator, obrien = crew.ids["operations_coordinator"], crew.ids["O'Brien"]
    counselor = _make_counselor(ward_room=ws, agent_id=crew.ids["Ezri"], callsign="Ezri")
    for target, callsign in (
        (coordinator, "operations_coordinator"), (coordinator, coordinator), (coordinator, ""), (obrien, "O'Brien"),
    ):
        assert await CounselorAgent._send_therapeutic_dm(counselor, target, callsign, "Checking in after the drill.")
        await _tick()


def _dm_titles(db_path: Path) -> list[tuple[str, str]]:
    """(channel name, title) of every stored DM thread, oldest first, read straight from the store."""
    con = sqlite3.connect(str(db_path))
    try:
        return [tuple(row) for row in con.execute(
            "SELECT c.name, t.title FROM threads t JOIN channels c ON c.id = t.channel_id "
            "WHERE c.channel_type = 'dm' ORDER BY t.created_at, t.rowid"
        )]
    finally:
        con.close()


def _fact(
    channel_name: str, *, in_thread: tuple[AuthorActivity, ...] = (),
    later: tuple[AuthorActivity, ...] = (), archived: bool = False,
) -> DmThreadFacts:
    return DmThreadFacts(
        thread_id="internal-handle", channel_name=channel_name, created_at=_T0,
        archived=archived, in_thread=in_thread, later_in_channel=later,
    )


def _act(author_id: str, count: int = 1, first: float = _T0 + 100, last: float | None = None) -> AuthorActivity:
    return AuthorActivity(author_id=author_id, count=count, first_at=first, last_at=first if last is None else last)


def _armed_config() -> SystemConfig:
    cfg = SystemConfig()
    cfg.ward_room.message_receipts_enabled = True
    return cfg


async def _capture_offer(
    monkeypatch: pytest.MonkeyPatch, runtime: Any, agent_id: str,
) -> list[dict[str, Any]]:
    """Drive the REAL executor tool assembly (the AD-1226 rig) and return what reached the loop."""
    import probos.cognitive.swe_harness.agentic_loop as loop_mod
    from probos.cognitive.agentic_dispatch import WorkItemAgenticExecutor
    from probos.cognitive.llm_client import LLMResponse

    seen: dict[str, Any] = {}

    class _CaptureLoop:
        def __init__(self, **_kwargs: Any) -> None:
            pass

        async def run(self, **kwargs: Any) -> Any:
            seen["tools"] = list(kwargs.get("tools") or [])
            return loop_mod.AgenticResult(final_text="ok")

    class _LLM:
        async def complete(self, request: Any, **_kwargs: Any) -> Any:
            return LLMResponse(content="ok", model="m", tier="standard")

    monkeypatch.setattr(loop_mod, "AgenticLoop", _CaptureLoop)
    await WorkItemAgenticExecutor(llm_client=_LLM()).run(
        agent_id=agent_id, instructions="i", task_text="t", runtime=runtime,
    )
    assert "tools" in seen, "premise: the run reached the loop"
    return seen["tools"]


def _names(definitions: list[dict[str, Any]]) -> list[str]:
    return [(d.get("function") or {}).get("name") or d.get("name") for d in definitions]


# ── R1-R3: the pure rules ───────────────────────────────────────────────


_NOBODY: frozenset[str] = frozenset()
# Each row ends with ``addressed``: the ids of the type its title's callsign resolves to (A-3).
_R1_CASES = [
    ("crew_exact", dm_channel_name(_COUNSELOR, _WORF), _COUNSELOR, _REGISTERED, EXACT, (_WORF,), frozenset({_WORF})),
    ("crew_exact_recipient_side", dm_channel_name(_COUNSELOR, _WORF), _WORF, _REGISTERED, EXACT, (_COUNSELOR,),
     frozenset({_COUNSELOR})),
    # Was shared_ops_key (SHARED_KEY over all four holders): the title names O'Brien, so he is proven (A-3).
    ("ops_key_addressed_to_obrien", dm_channel_name(_COUNSELOR, _OPS), _COUNSELOR, _REGISTERED, EXACT, (_OPS,),
     frozenset({_OPS})),
    ("ops_key_without_addressee", dm_channel_name(_COUNSELOR, _OPS), _COUNSELOR, _REGISTERED, UNCONFIRMED,
     _OPS_HOLDERS, _NOBODY),
    ("crew_key_without_addressee", dm_channel_name(_COUNSELOR, _WORF), _COUNSELOR, _REGISTERED, UNCONFIRMED,
     (_WORF,), _NOBODY),
    ("addressee_of_another_key", dm_channel_name(_COUNSELOR, _WORF), _COUNSELOR, _REGISTERED, UNCONFIRMED,
     (_WORF,), frozenset({_IDS["engineering_officer"]})),
    ("two_holders_of_the_addressed_type", dm_channel_name(_COUNSELOR, _WORF), _COUNSELOR,
     _REGISTERED + (_SECOND_WORF,), SHARED_KEY, tuple(sorted((_WORF, _SECOND_WORF))),
     frozenset({_WORF, _SECOND_WORF})),
    ("captain_proactive_form", captain_dm_channel_name(_COUNSELOR), _COUNSELOR, _REGISTERED, CAPTAIN_CHANNEL, (),
     _NOBODY),
    ("captain_sorted_form", dm_channel_name(CAPTAIN_DM_KEY, _COUNSELOR), _COUNSELOR, _REGISTERED, CAPTAIN_CHANNEL, (),
     _NOBODY),
    ("captain_sorted_form_id_first", dm_channel_name(CAPTAIN_DM_KEY, _ARCHITECT), _ARCHITECT, _REGISTERED,
     CAPTAIN_CHANNEL, (), _NOBODY),
    ("someone_elses_captain_channel", captain_dm_channel_name(_WORF), _COUNSELOR, _REGISTERED,
     UNRECOGNISED_CHANNEL, (), _NOBODY),
    ("unregistered_key", "dm-counselo-wesley_w", _COUNSELOR, _REGISTERED, UNREGISTERED_KEY, (), _NOBODY),
    ("sender_absent_from_the_name", dm_channel_name(_WORF, _OPS), _COUNSELOR, _REGISTERED, UNRECOGNISED_CHANNEL, (),
     _NOBODY),
    ("malformed_name", "dm-a-b-c", _COUNSELOR, _REGISTERED, UNRECOGNISED_CHANNEL, (), _NOBODY),
    ("not_a_dm_name", "All Hands", _COUNSELOR, _REGISTERED, UNRECOGNISED_CHANNEL, (), _NOBODY),
    ("same_key_pair", dm_channel_name(_COUNSELOR, _SECOND_COUNSELOR), _COUNSELOR,
     _REGISTERED + (_SECOND_COUNSELOR,), EXACT, (_SECOND_COUNSELOR,), frozenset({_COUNSELOR, _SECOND_COUNSELOR})),
    ("same_key_only_the_sender_aboard", dm_channel_name(_COUNSELOR, _SECOND_COUNSELOR), _COUNSELOR, _REGISTERED,
     UNREGISTERED_KEY, (), _NOBODY),
    ("empty_sender_id", dm_channel_name(_COUNSELOR, _WORF), "", _REGISTERED, UNRECOGNISED_CHANNEL, (), _NOBODY),
]


@pytest.mark.parametrize(
    ("channel_name", "sender_id", "registered", "basis", "holders", "addressed"),
    [case[1:] for case in _R1_CASES],
    ids=[case[0] for case in _R1_CASES],
)
def test_classify_dm_recipient(
    channel_name: str, sender_id: str, registered: tuple[str, ...], basis: str, holders: tuple[str, ...],
    addressed: frozenset[str],
) -> None:
    assert {case[4] for case in _R1_CASES} == RECIPIENT_BASES, "premise: the table produces every basis"
    assert {_IDS[t][:8] for t in _OPS_TYPES} == {"operatio"}, "premise: four real types share one key"

    resolution = classify_dm_recipient(channel_name, sender_id, registered, addressed)

    assert (resolution.basis, resolution.holder_ids) == (basis, holders)


def _valid_receipt_kwargs() -> dict[str, Any]:
    return {
        "to": "Worf", "channel": CREW_DM, "sent_at": _T0, "delivery": DELIVERED,
        "recipient_basis": EXACT, "archived": False, "reply": REPLIED, "recipient_replies": 2,
        "first_reply_at": _T0 + 100, "last_reply_at": _T0 + 400, "later_in_channel": True,
        "replied_by": ("Worf", "Captain"),
    }


_R2_CASES: dict[str, tuple[dict[str, Any], str]] = {
    "free_text_to": ({"to": "Worf, please reply!"}, "'to'"),
    "channel_basis_mismatch": ({"channel": CAPTAIN_DM}, "channel kind"),
    "nan_sent_at": ({"sent_at": float("nan")}, "sent_at"),
    "delivery_basis_mismatch": ({"delivery": NO_REGISTERED_RECIPIENT}, "delivery"),
    "named_without_proof": ({"recipient_basis": SHARED_KEY, "delivery": UNKNOWN}, "names a recipient"),
    "read_recorded": ({"read": "read"}, "read record"),
    "reply_without_recipient": ({"to": None}, "reply is unknown"),
    "replied_with_zero": ({"recipient_replies": 0, "first_reply_at": None, "last_reply_at": None}, "posted in"),
    "times_without_reply": ({"reply": NO_REPLY_YET, "recipient_replies": 0, "last_reply_at": None}, "need a reply"),
    "unordered_times": ({"first_reply_at": _T0 + 500}, "finite and ordered"),
    "six_repliers": ({"replied_by": ("Ann", "Bea", "Cal", "Dee", "Eve", "Fay")}, "replied_by"),
    "duplicate_repliers": ({"replied_by": ("Worf", "Worf")}, "replied_by"),
    "non_label_replier": ({"replied_by": ("3f2a9c1e-5b7d-4e0a-9c1f-2b3d4e5f6a7b",)}, "replied_by"),
    "unconfirmed_named": ({"recipient_basis": UNCONFIRMED, "delivery": UNKNOWN}, "names a recipient"),
    "hostile_to": ({"to": _HOSTILE_CALLSIGN}, "'to'"),
    "hostile_replier": ({"replied_by": (_HOSTILE_CALLSIGN,)}, "replied_by"),
}


@pytest.mark.parametrize("case", list(_R2_CASES))
def test_receipt_refuses_inconsistent_or_free_text_values(case: str) -> None:
    valid = MessageReceipt(**_valid_receipt_kwargs())
    assert valid.read == READ_NOT_RECORDED, "premise: the base receipt is valid"
    if case.startswith("hostile_"):
        assert LABEL_RE.fullmatch(_HOSTILE_CALLSIGN), "premise: the pattern admits it, so only the gates refuse it"
    overrides, reason = _R2_CASES[case]

    with pytest.raises(ValueError, match=re.escape(reason)) as refused:
        MessageReceipt(**{**_valid_receipt_kwargs(), **overrides})

    assert str(refused.value).startswith("AD-1229:")


async def _r3_directory() -> tuple[AgentRegistry, CallsignRegistry]:
    agents = AgentRegistry()
    callsigns = CallsignRegistry()
    members = [
        ("counselor", _COUNSELOR, "Ezri"), ("security_officer", _WORF, "Worf"),
        ("security_officer", _SECOND_WORF, "Worf"), ("engineering_officer", _IDS["engineering_officer"], "LaForge"),
        ("operations_officer", _OPS, "O'Brien"),
        ("operations_resource_allocator", _IDS["operations_resource_allocator"], None),
        ("operations_scheduler", _IDS["operations_scheduler"], None),
        ("operations_coordinator", _IDS["operations_coordinator"], None),
    ]
    for agent_type, agent_id, callsign in members:
        await agents.register(SimpleNamespace(
            id=agent_id, agent_type=agent_type, pool=agent_type, callsign=callsign or "",
            is_alive=True, capabilities=[],
        ))
        if callsign:
            callsigns.set_callsign(agent_type, callsign)
    callsigns.bind_registry(agents)
    return agents, callsigns


_CREW_CHANNEL = dm_channel_name(_COUNSELOR, _WORF)
_OPS_CHANNEL = dm_channel_name(_COUNSELOR, _OPS)
_R3_REGISTERED = (_COUNSELOR, _WORF, _IDS["engineering_officer"])
_OPS_REGISTERED = (_COUNSELOR, *_OPS_HOLDERS)
_TO_WORF = frozenset({_WORF})
# name: (fact, registered ids, addressed ids, expected receipt fields)
_R3_CASES: dict[str, tuple[DmThreadFacts, tuple[str, ...], frozenset[str], dict[str, Any]]] = {
    "exact_replied": (
        _fact(_CREW_CHANNEL, in_thread=(_act(_WORF, 2, _T0 + 100, _T0 + 400),)), _R3_REGISTERED, _TO_WORF,
        {"to": "Worf", "recipient_basis": EXACT, "delivery": DELIVERED, "channel": CREW_DM, "reply": REPLIED,
         "recipient_replies": 2, "first_reply_at": _T0 + 100, "last_reply_at": _T0 + 400,
         "later_in_channel": False, "replied_by": ("Worf",)},
    ),
    "exact_no_reply": (
        _fact(_CREW_CHANNEL), _R3_REGISTERED, _TO_WORF,
        {"to": "Worf", "recipient_basis": EXACT, "reply": NO_REPLY_YET, "recipient_replies": 0,
         "first_reply_at": None, "last_reply_at": None, "later_in_channel": False, "replied_by": ()},
    ),
    "captain_replied": (
        _fact(captain_dm_channel_name(_COUNSELOR), in_thread=(_act("captain"),)), _R3_REGISTERED, _NOBODY,
        {"to": CAPTAIN_LABEL, "recipient_basis": CAPTAIN_CHANNEL, "delivery": DELIVERED, "channel": CAPTAIN_DM,
         "reply": REPLIED, "recipient_replies": 1, "later_in_channel": False, "replied_by": (CAPTAIN_LABEL,)},
    ),
    # Was shared_one_type_labelled (to Worf, delivered): one agent type is not one agent, so a shared
    # key proves neither who received the DM nor that it was delivered (review round 1).
    "shared_one_type_is_not_named": (
        _fact(_CREW_CHANNEL, in_thread=(_act(_SECOND_WORF),)), (_COUNSELOR, _WORF, _SECOND_WORF),
        frozenset({_WORF, _SECOND_WORF}),
        {"to": None, "recipient_basis": SHARED_KEY, "delivery": UNKNOWN, "channel": CREW_DM, "reply": UNKNOWN,
         "recipient_replies": None, "first_reply_at": None, "last_reply_at": None, "later_in_channel": None,
         "replied_by": ("Worf",)},
    ),
    # Was shared_many_types_unknown (SHARED_KEY): no title addressed a holder, so the thread is unconfirmed (A-3).
    "ops_key_without_addressee_is_unconfirmed": (
        _fact(_OPS_CHANNEL, in_thread=(_act(_OPS),)), _OPS_REGISTERED, _NOBODY,
        {"to": None, "recipient_basis": UNCONFIRMED, "delivery": UNKNOWN, "channel": CREW_DM, "reply": UNKNOWN,
         "recipient_replies": None, "first_reply_at": None, "last_reply_at": None, "later_in_channel": None,
         "replied_by": ("O'Brien",)},
    ),
    "ops_key_addressed_to_obrien_is_named": (
        _fact(_OPS_CHANNEL, in_thread=(_act(_OPS),)), _OPS_REGISTERED, frozenset({_OPS}),
        {"to": "O'Brien", "recipient_basis": EXACT, "delivery": DELIVERED, "channel": CREW_DM, "reply": REPLIED,
         "recipient_replies": 1, "replied_by": ("O'Brien",)},
    ),
    "unaddressed_crew_thread_is_unconfirmed": (
        _fact(_CREW_CHANNEL, in_thread=(_act(_WORF),)), _R3_REGISTERED, _NOBODY,
        {"to": None, "recipient_basis": UNCONFIRMED, "delivery": UNKNOWN, "channel": CREW_DM, "reply": UNKNOWN,
         "recipient_replies": None, "first_reply_at": None, "last_reply_at": None, "later_in_channel": None,
         "replied_by": ("Worf",)},
    ),
    "unregistered_key": (
        _fact("dm-counselo-wesley_w", in_thread=(_act("wesley_crusher_x"),)), _R3_REGISTERED, _NOBODY,
        {"to": None, "recipient_basis": UNREGISTERED_KEY, "delivery": NO_REGISTERED_RECIPIENT, "channel": CREW_DM,
         "reply": UNKNOWN, "recipient_replies": None, "later_in_channel": None,
         "replied_by": (UNREGISTERED_LABEL,)},
    ),
    "system_post_is_not_a_reply": (
        _fact(_CREW_CHANNEL, in_thread=(_act("system"),)), _R3_REGISTERED, _TO_WORF,
        {"to": "Worf", "reply": NO_REPLY_YET, "recipient_replies": 0, "replied_by": ()},
    ),
    "captain_in_crew_dm_is_not_the_recipient": (
        _fact(_CREW_CHANNEL, in_thread=(_act("captain"),)), _R3_REGISTERED, _TO_WORF,
        {"to": "Worf", "recipient_basis": EXACT, "reply": NO_REPLY_YET, "recipient_replies": 0,
         "first_reply_at": None, "later_in_channel": False, "replied_by": (CAPTAIN_LABEL,)},
    ),
    "later_thread_is_not_a_reply": (
        _fact(_CREW_CHANNEL, later=(_act(_WORF, 1, _T0 + 900),)), _R3_REGISTERED, _TO_WORF,
        {"to": "Worf", "reply": NO_REPLY_YET, "recipient_replies": 0, "later_in_channel": True, "replied_by": ()},
    ),
}


@pytest.mark.parametrize("case", list(_R3_CASES))
async def test_build_receipt_attribution(case: str) -> None:
    agents, callsigns = await _r3_directory()
    fact, registered, addressed, expected = _R3_CASES[case]

    receipt = build_receipt(
        fact, classify_dm_recipient(fact.channel_name, _COUNSELOR, registered, addressed),
        agents=agents, callsigns=callsigns,
    )

    assert {key: getattr(receipt, key) for key in expected} == expected
    assert receipt.read == READ_NOT_RECORDED and receipt.sent_at == _T0


# ── T1-T15: the tool through the real registry and a real Ward Room ─────


async def test_tool_reports_facts_through_the_real_registry_at_ensign_rank(ward_room: _WardRoomRig) -> None:
    ws = ward_room.service
    crew = await _standard_crew()
    ezri, worf = crew.ids["Ezri"], crew.ids["Worf"]
    to_worf = await _crew_dm(ws, ezri, worf, to="Worf")
    await _tick()
    await ws.create_post(to_worf.id, worf, "Fine, Counselor.", author_callsign="Worf")
    await _tick()
    await _captain_dm(ws, ezri)

    out = await _ask(_registered(_runtime(ws, crew)), ezri)

    assert (out["count"], out["window_hours"], out["truncated"]) == (2, WINDOW_DEFAULT_HOURS, False)
    assert "note" not in out and "reason" not in out
    captain, crew_dm = out["messages"]
    assert list(crew_dm) == _RECEIPT_KEYS and list(captain) == _RECEIPT_KEYS
    assert all(_UTC_RE.fullmatch(r["sent_at"]) for r in (captain, crew_dm))
    assert _UTC_RE.fullmatch(crew_dm["first_reply_at"]) and crew_dm["first_reply_at"] == crew_dm["last_reply_at"]
    assert {k: v for k, v in crew_dm.items() if not k.endswith("_at")} == {
        "to": "Worf", "channel": CREW_DM, "delivery": DELIVERED, "recipient_basis": EXACT, "archived": False,
        "reply": REPLIED, "recipient_replies": 1, "later_in_channel": False, "replied_by": ["Worf"],
        "read": READ_NOT_RECORDED,
    }
    assert {k: v for k, v in captain.items() if k != "sent_at"} == {
        "to": CAPTAIN_LABEL, "channel": CAPTAIN_DM, "delivery": DELIVERED, "recipient_basis": CAPTAIN_CHANNEL,
        "archived": False, "reply": NO_REPLY_YET, "recipient_replies": 0, "first_reply_at": None,
        "last_reply_at": None, "later_in_channel": False, "replied_by": [], "read": READ_NOT_RECORDED,
    }


@pytest.mark.parametrize("case", ["undeclared", "since_bool", "since_text", "limit_fraction"])
async def test_tool_refuses_undeclared_and_non_integer_params(case: str, ward_room: _WardRoomRig) -> None:
    crew = await _standard_crew()
    ezri = crew.ids["Ezri"]
    tool = MessageReceiptsTool(runtime=_runtime(ward_room.service, crew))

    if case == "undeclared":
        result = await tool.invoke({"recipent": "Worf"}, {"agent_id": ezri})
        assert result.output is None and result.error is not None and "recipent" in result.error
        return
    accepted = await tool.invoke({"since_hours": 24.0, "limit": 2.0}, {"agent_id": ezri})
    assert accepted.output["window_hours"] == 24, "premise: an integral float is a whole number"
    params, name = {
        "since_bool": ({"since_hours": True}, "since_hours"),
        "since_text": ({"since_hours": "24"}, "since_hours"),
        "limit_fraction": ({"limit": 2.5}, "limit"),
    }[case]

    result = await tool.invoke(params, {"agent_id": ezri})

    assert result.error is None
    assert result.output == {"messages": [], "count": 0, "reason": R_WHOLE.format(name=name)}


@pytest.mark.parametrize("case", ["since_zero", "since_1000", "limit_zero", "limit_99"])
async def test_tool_clamps_window_and_limit(case: str, ward_room: _WardRoomRig) -> None:
    ws = ward_room.service
    crew = await _standard_crew()
    ezri, worf = crew.ids["Ezri"], crew.ids["Worf"]
    for n in range(LIMIT_MAX + 1 if case == "limit_99" else 2):
        await _crew_dm(ws, ezri, worf, to="Worf", body=f"note {n}")
    params = {
        "since_zero": {"since_hours": 0}, "since_1000": {"since_hours": 1000},
        "limit_zero": {"limit": 0}, "limit_99": {"limit": 99},
    }[case]

    out = await _ask(_registered(_runtime(ws, crew)), ezri, params)

    if case == "since_zero":
        assert (out["window_hours"], out["count"]) == (1, 2)
    elif case == "since_1000":
        assert (out["window_hours"], out["count"]) == (WINDOW_MAX_HOURS, 2)
    elif case == "limit_zero":
        assert (out["count"], out["truncated"]) == (1, True)
    else:
        assert (out["count"], out["truncated"]) == (LIMIT_MAX, True)


async def test_empty_identity_is_not_a_wildcard_and_context_cannot_spoof(ward_room: _WardRoomRig) -> None:
    ws = ward_room.service
    crew = await _standard_crew()
    ezri, worf = crew.ids["Ezri"], crew.ids["Worf"]
    await _crew_dm(ws, ezri, worf, to="Worf")
    runtime = _runtime(ws, crew)
    tool = MessageReceiptsTool(runtime=runtime)

    for context in (None, {}, {"agent_id": ""}):
        result = await tool.invoke({}, context)
        assert result.error is None
        assert result.output == {"messages": [], "count": 0, "reason": R_IDENTITY}

    tools = _registered(runtime)
    assert (await _ask(tools, ezri))["count"] == 1, "premise: the stored DM is visible to its author"
    worf_view = await _ask(tools, worf, context={"agent_id": ezri})
    assert worf_view["count"] == 0 and worf_view["messages"] == [] and "note" in worf_view


@pytest.mark.parametrize(
    "case",
    ["callsign", "captain_any_case", "unknown_callsign", "own_callsign", "not_aboard", "hostile_recipient_not_echoed"],
)
async def test_recipient_filter(case: str, ward_room: _WardRoomRig) -> None:
    ws = ward_room.service
    crew = await _standard_crew()
    ezri, worf, geordi = crew.ids["Ezri"], crew.ids["Worf"], crew.ids["LaForge"]
    await _crew_dm(ws, ezri, worf, to="Worf")
    await _tick()
    await _crew_dm(ws, ezri, geordi, to="LaForge")
    await _tick()
    await _captain_dm(ws, ezri)
    tools = _registered(_runtime(ws, crew))
    assert (await _ask(tools, ezri))["count"] == 3, "premise: three messages are stored"

    if case == "callsign":
        out = await _ask(tools, ezri, {"recipient": "Worf"})
        assert [m["to"] for m in out["messages"]] == ["Worf"]
    elif case == "captain_any_case":
        out = await _ask(tools, ezri, {"recipient": "CAPTAIN"})
        assert [m["to"] for m in out["messages"]] == [CAPTAIN_LABEL]
    elif case == "hostile_recipient_not_echoed":
        assert extract_referents(_HOSTILE_RECIPIENT) and is_capability_gap(_HOSTILE_RECIPIENT), (
            "premise: the input carries a referent and a gap phrase"
        )
        out = await _ask(tools, ezri, {"recipient": _HOSTILE_RECIPIENT})
        blob = json.dumps(out)
        assert out == {"messages": [], "count": 0, "reason": R_RECIPIENT}
        assert "SECRET_BODY_42" not in blob and "9f3c2ab1e" not in blob
        assert extract_referents(blob) == [] and is_capability_gap(blob) is False
    else:
        # These used to quote the recipient back, handing the model its own input as a stored fact.
        recipient, reason, text = {
            "unknown_callsign": ("Nobody", R_RECIPIENT, "no crew member answers to that callsign"),
            "own_callsign": ("Ezri", R_SELF, "that is your own callsign; there are no direct messages to yourself"),
            "not_aboard": (
                "Crusher", R_NOT_ABOARD,
                "no crew member with that callsign is registered aboard, so there is no DM channel to look in",
            ),
        }[case]
        out = await _ask(tools, ezri, {"recipient": recipient})
        assert reason == text
        assert out == {"messages": [], "count": 0, "reason": text}
        assert recipient not in json.dumps(out)


class _RaisingFacts:
    is_started = True

    def __init__(self) -> None:
        self.calls = 0

    async def dm_receipt_facts(
        self, author_id: str, *, since: float, limit: int, channel_names: tuple[str, ...] = (),
    ) -> Any:
        self.calls += 1
        raise RuntimeError("database is locked")


@pytest.mark.parametrize("case", ["no_ward_room", "stopped_ward_room", "raising_facts"])
async def test_absent_stopped_or_faulting_sources_degrade_honestly(
    case: str, tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    crew = await _standard_crew()
    raising = _RaisingFacts()
    if case == "no_ward_room":
        runtime = _runtime(None, crew)
    elif case == "stopped_ward_room":
        service = WardRoomService(db_path=str(tmp_path / "wr.db"))
        await service.start()
        await service.stop()
        runtime = _runtime(service, crew)
    else:
        runtime = _runtime(raising, crew)

    with caplog.at_level(logging.WARNING, logger="probos.tools.message_receipts_tool"):
        result = await MessageReceiptsTool(runtime=runtime).invoke({}, {"agent_id": crew.ids["Ezri"]})

    assert result.error is None
    expected = R_FAULT if case == "raising_facts" else R_WARD_ROOM
    assert result.output == {"messages": [], "count": 0, "reason": expected}
    warnings = [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING]
    if case == "raising_facts":
        assert raising.calls == 1, "premise: the read was attempted"
        assert any(message.startswith("AD-1229:") for message in warnings)
    else:
        assert warnings == []


_CAUSAL_RE = re.compile(
    r"\b(?:work(?:ed|s|ing)?|effect(?:s|ive|ively|iveness)?|help(?:ed|s|ful)?|"
    r"improv(?:e|ed|es|ement)|land(?:ed|s)?|success(?:ful|fully)?|impact(?:s|ed)?|"
    r"caus(?:e|ed|es|al)|because|result(?:ed|s)?\s+in|led\s+to|shift(?:ed)?|chang(?:e|ed)\s+(?:their|his|her))\b",
    re.IGNORECASE,
)
_CAUSAL_POSITIVE = (
    "the DM worked", "it helped Worf", "cohesion improved", "your message had an effect",
    "the check-in landed", "a successful intervention", "this led to a change",
)
_CAUSAL_NEGATIVE = (
    "delivered", "the recipient replied", "no reply yet", "sent at 14:05 UTC",
    "archived after a day", "read is not_recorded", "wrote elsewhere afterwards",
)


def test_every_model_facing_text_is_gap_clean_causal_free_and_referent_free() -> None:
    assert is_capability_gap("I cannot see that") and not is_capability_gap("The message was delivered.")
    assert all(_CAUSAL_RE.search(s) for s in _CAUSAL_POSITIVE), "premise: the causal scan sees causal phrasing"
    assert not any(_CAUSAL_RE.search(s) for s in _CAUSAL_NEGATIVE), "premise: the causal scan passes facts"
    assert extract_referents("see commit 9f3c2ab1e and node 'alpha7'"), "premise: the extractor finds a referent"
    tool = MessageReceiptsTool(runtime=SimpleNamespace())
    texts: dict[str, str] = {"description": tool.description}
    for key, spec in tool.input_schema["properties"].items():
        texts[f"param:{key}"] = spec["description"]
    texts.update({
        "r_identity": R_IDENTITY, "r_ward_room": R_WARD_ROOM, "r_fault": R_FAULT,
        "r_recipient": R_RECIPIENT, "r_not_aboard": R_NOT_ABOARD, "r_self": R_SELF,
        "r_whole_since": R_WHOLE.format(name="since_hours"),
        "r_whole_limit": R_WHOLE.format(name="limit"),
    })
    for to_part in ("", " to the Captain", " to Worf", " to that crew member"):
        for hours in (1, WINDOW_DEFAULT_HOURS, WINDOW_MAX_HOURS):
            texts[f"note:{to_part}:{hours}"] = NOTE_EMPTY.format(to_part=to_part, hours=hours)
            texts[f"note_unconfirmed:{to_part}:{hours}"] = NOTE_UNCONFIRMED.format(to_part=to_part, hours=hours)
    receipts = [
        MessageReceipt(**_valid_receipt_kwargs()),
        MessageReceipt(
            to=None, channel=CREW_DM, sent_at=_T0, delivery=UNKNOWN, recipient_basis=SHARED_KEY, archived=True,
            reply=UNKNOWN, recipient_replies=None, first_reply_at=None, last_reply_at=None,
            later_in_channel=None, replied_by=(),
        ),
        MessageReceipt(
            to=None, channel=OTHER_DM, sent_at=_T0, delivery=UNKNOWN, recipient_basis=UNRECOGNISED_CHANNEL,
            archived=False, reply=UNKNOWN, recipient_replies=None, first_reply_at=None, last_reply_at=None,
            later_in_channel=None, replied_by=(UNREGISTERED_LABEL, CREW_MEMBER_LABEL),
        ),
    ]
    page = {"messages": [r.to_output() for r in receipts], "count": 3, "window_hours": 24, "truncated": False}
    texts["page"] = json.dumps(page)
    texts["page_pretty"] = json.dumps(page, indent=2)
    keys = {"messages", "count", "window_hours", "truncated", "note", "reason", "unconfirmed", *receipts[0].to_output()}
    texts.update({f"key:{key}": key for key in keys})
    codes = {
        CREW_DM, CAPTAIN_DM, OTHER_DM, *RECIPIENT_BASES, UNCONFIRMED, DELIVERED, NO_REGISTERED_RECIPIENT, UNKNOWN,
        READ_NOT_RECORDED, *REPLY_CODES, CAPTAIN_LABEL, UNREGISTERED_LABEL, CREW_MEMBER_LABEL,
    }
    texts.update({f"code:{code}": code for code in codes})
    assert len(texts) >= 50, "premise: the scan covers the whole surface"

    assert [key for key, text in texts.items() if is_capability_gap(text)] == []
    assert [(key, m.group(0)) for key, text in texts.items() if (m := _CAUSAL_RE.search(text))] == []
    assert [(key, [r.token for r in refs]) for key, text in texts.items() if (refs := extract_referents(text))] == []


_WATCHED = frozenset({"episodic_memory", "trust_network", "hebbian_router", "emit_event"})


class _Tripwire:
    """Records any attribute read or call."""

    def __init__(self, name: str, log: list[str]) -> None:
        object.__setattr__(self, "_name", name)
        object.__setattr__(self, "_log", log)

    def __getattr__(self, attr: str) -> Any:
        self._log.append(f"{self._name}.{attr}")
        return self

    def __call__(self, *args: Any, **kwargs: Any) -> None:
        self._log.append(f"{self._name}()")


class _WatchedRuntime:
    """A runtime that records every read of a learning or event service."""

    def __init__(self, log: list[str], **attrs: Any) -> None:
        object.__setattr__(self, "_watch_log", log)
        for key, value in attrs.items():
            object.__setattr__(self, key, value)

    def __getattribute__(self, name: str) -> Any:
        if name in _WATCHED:
            object.__getattribute__(self, "_watch_log").append(f"runtime.{name}")
        return object.__getattribute__(self, name)


async def test_the_tool_writes_nothing(ward_room: _WardRoomRig) -> None:
    ws = ward_room.service
    crew = await _standard_crew()
    ezri, worf = crew.ids["Ezri"], crew.ids["Worf"]
    thread = await _crew_dm(ws, ezri, worf, to="Worf")
    await ws.create_post(thread.id, worf, "ok", author_callsign="Worf")
    await _captain_dm(ws, ezri)
    log: list[str] = []
    runtime = _WatchedRuntime(
        log, ward_room=ws, registry=crew.agents, callsign_registry=crew.callsigns,
        **{name: _Tripwire(name, log) for name in _WATCHED},
    )
    runtime.episodic_memory.store  # noqa: B018 -- premise: the watch sees a touch
    assert log == ["runtime.episodic_memory", "episodic_memory.store"]
    log.clear()
    tools = _registered(runtime)
    before, emitted = _table_digest(ward_room.db_path), len(ward_room.events)

    for params in ({}, {"recipient": "Worf"}, {"recipient": "captain"}, {"recipient": "Nobody"}):
        await _ask(tools, ezri, params)

    assert log == []
    assert _table_digest(ward_room.db_path) == before
    assert len(ward_room.events) == emitted


async def test_output_carries_no_ids_titles_or_bodies(ward_room: _WardRoomRig) -> None:
    ws = ward_room.service
    crew = await _standard_crew()
    ezri, worf = crew.ids["Ezri"], crew.ids["Worf"]
    to_worf = await _crew_dm(ws, ezri, worf, to="Worf", title="[DM to @Worf] SECRET_TITLE_1", body="SECRET_BODY_1")
    reply = await ws.create_post(to_worf.id, worf, "SECRET_REPLY_1", author_callsign="Worf")
    to_captain = await _captain_dm(ws, ezri, title="[DM to Captain] SECRET_TITLE_2", body="SECRET_BODY_2")
    worf_channel = await ws.get_or_create_dm_channel(ezri, worf)
    captain_channel = await ws.get_channel_by_name(captain_dm_channel_name(ezri))
    assert captain_channel is not None
    ids = [to_worf.id, reply.id, to_captain.id, worf_channel.id, captain_channel.id]
    assert any(_HEX_RE.search(i) for i in ids), "premise: a Ward Room id reads as an AD-1119 hex referent"

    out = await _ask(_registered(_runtime(ws, crew)), ezri)

    assert out["count"] == 2, "premise: both messages were reported"
    blob = json.dumps(out)
    leaked = [f for f in (*ids, worf_channel.name, captain_channel.name, ezri, worf, *SENTINELS) if f in blob]
    assert leaked == []
    assert _HEX_RE.search(blob) is None


# Was test_only_addressable_crew_count_as_recipients: O'Brien was named because the other three holders of
# his key have no callsign. A-3 counts every registered holder and names him from the title the producer wrote.
async def test_the_addressed_callsign_names_one_holder_among_many(ward_room: _WardRoomRig) -> None:
    ws = ward_room.service
    crew = await _crew(
        ("counselor", "Ezri"), ("operations_officer", "O'Brien"), ("operations_coordinator", None),
        ("operations_resource_allocator", None), ("operations_scheduler", None),
    )
    ezri, obrien = crew.ids["Ezri"], crew.ids["O'Brien"]
    ops_ids = [obrien, *(crew.ids[t] for t in _OPS_TYPES[1:])]
    assert {i[:8] for i in ops_ids} == {"operatio"}, "premise: four registered types share one key"
    await _proactive_dm(ws, crew, ezri, "[DM @O'Brien] Status of the plasma relays? [/DM]")
    await _tick()
    await _proactive_dm(ws, crew, ezri, "[DM @o'brien] And the transporter buffers? [/DM]")
    assert [title for _name, title in _dm_titles(ward_room.db_path)] == ["[DM to @O'Brien]", "[DM to @o'brien]"], (
        "premise: the producer titled each DM with the callsign as typed"
    )
    tools = _registered(_runtime(ws, crew))
    keys = ("to", "recipient_basis", "delivery", "reply")

    out = await _ask(tools, ezri)
    filtered = await _ask(tools, ezri, {"recipient": "O'Brien"})

    assert [tuple(m[k] for k in keys) for m in out["messages"]] == [("O'Brien", EXACT, DELIVERED, NO_REPLY_YET)] * 2
    assert (filtered["count"], filtered["unconfirmed"], "note" in filtered) == (2, 0, False)
    channel = await ws.get_or_create_dm_channel(ezri, obrien)
    first = next(t for t in await ws.list_threads(channel.id) if t.title == "[DM to @O'Brien]")
    await _tick()
    await ws.create_post(first.id, obrien, "Relays nominal.", author_callsign="O'Brien")
    replied = await _ask(tools, ezri)
    assert [(m["reply"], m["replied_by"]) for m in replied["messages"]] == [(NO_REPLY_YET, []), (REPLIED, ["O'Brien"])]


async def test_a_shared_channel_key_never_names_a_recipient_or_asserts_delivery(ward_room: _WardRoomRig) -> None:
    ws = ward_room.service
    agents, callsigns = AgentRegistry(), CallsignRegistry()
    for agent_id, agent_type, callsign in (
        (_COUNSELOR, "counselor", "Ezri"), (_WORF, "security_officer", "Worf"),
        (_SECOND_WORF, "security_officer", "Worf"),
    ):
        await agents.register(SimpleNamespace(
            id=agent_id, agent_type=agent_type, pool=agent_type, callsign=callsign, is_alive=True, capabilities=[],
        ))
        callsigns.set_callsign(agent_type, callsign)
    callsigns.bind_registry(agents)
    tools = _registered(_runtime(ws, _Crew(agents=agents, callsigns=callsigns, ids={})))
    to_first = await _crew_dm(ws, _COUNSELOR, _WORF, to="Worf")
    await _tick()
    to_second = await _crew_dm(ws, _COUNSELOR, _SECOND_WORF, to="Worf")
    assert to_first.channel_id == to_second.channel_id, "premise: both DMs share one channel"
    alone = classify_dm_recipient(
        dm_channel_name(_COUNSELOR, _WORF), _COUNSELOR, (_COUNSELOR, _WORF), frozenset({_WORF}),
    )
    assert alone.basis == EXACT, "premise: with one holder aboard the same channel would be exact"
    unproven = {
        "to": None, "delivery": "unknown", "recipient_basis": "shared_key", "reply": "unknown",
        "recipient_replies": None, "first_reply_at": None, "last_reply_at": None, "later_in_channel": None,
    }

    out = await _ask(tools, _COUNSELOR)
    assert [{key: m[key] for key in unproven} for m in out["messages"]] == [unproven, unproven]
    # Was the same two unproven receipts under {"recipient": "Worf"}: a filter now lists only proven
    # messages and counts the rest (A-3), so a shared key yields none and says it is unconfirmed.
    filtered = await _ask(tools, _COUNSELOR, {"recipient": "Worf"})
    assert (filtered["messages"], filtered["count"], filtered["unconfirmed"], filtered["note"]) == (
        [], 0, 2, NOTE_UNCONFIRMED.format(to_part=" to Worf", hours=WINDOW_DEFAULT_HOURS),
    )
    await ws.create_post(to_second.id, _WORF, "Acknowledged.", author_callsign="Worf")
    out = await _ask(tools, _COUNSELOR)

    assert [{key: m[key] for key in unproven} for m in out["messages"]] == [unproven, unproven]
    assert [m["replied_by"] for m in out["messages"]] == [["Worf"], []]


async def test_a_thread_names_only_the_recipient_its_title_addressed(ward_room: _WardRoomRig) -> None:
    ws = ward_room.service
    crew = await _crew(
        ("counselor", "Ezri"), ("operations_officer", "O'Brien"), ("operations_scheduler", "Odo"),
        ("operations_coordinator", None), ("operations_resource_allocator", None),
    )
    ezri, obrien = crew.ids["Ezri"], crew.ids["O'Brien"]
    await _proactive_dm(ws, crew, ezri, "[DM @O'Brien] Status of the plasma relays? [/DM]")
    await _tick()
    await _proactive_dm(ws, crew, ezri, "[DM @Odo] Any anomalies on your watch? [/DM]")
    shared = dm_channel_name(ezri, obrien)
    assert _dm_titles(ward_room.db_path) == [(shared, "[DM to @O'Brien]"), (shared, "[DM to @Odo]")], (
        "premise: both DMs share one channel, each titled with its recipient"
    )
    tools = _registered(_runtime(ws, crew))
    keys = ("to", "recipient_basis", "delivery", "reply")
    named = await _ask(tools, ezri)
    assert [tuple(m[k] for k in keys) for m in named["messages"]] == [
        ("Odo", EXACT, DELIVERED, NO_REPLY_YET), ("O'Brien", EXACT, DELIVERED, NO_REPLY_YET),
    ], "premise: while both callsigns resolve, each thread names its own recipient"
    crew.callsigns.set_callsign("operations_scheduler", "")
    assert crew.callsigns.resolve("Odo") is None, "premise: Odo's callsign is gone"

    out = await _ask(tools, ezri)

    assert [tuple(m[k] for k in keys) for m in out["messages"]] == [
        (None, UNCONFIRMED, UNKNOWN, UNKNOWN), ("O'Brien", EXACT, DELIVERED, NO_REPLY_YET),
    ]


@pytest.mark.parametrize(
    "case", ["proven_to_someone_else", "unconfirmed_counted", "truncated_page", "counselor_unaddressed"],
)
async def test_recipient_filter_lists_only_proven_messages_and_counts_the_rest(
    case: str, ward_room: _WardRoomRig,
) -> None:
    ws = ward_room.service
    notes = {
        "empty": NOTE_EMPTY.format(to_part=" to O'Brien", hours=WINDOW_DEFAULT_HOURS),
        "unconfirmed": NOTE_UNCONFIRMED.format(to_part=" to O'Brien", hours=WINDOW_DEFAULT_HOURS),
    }
    if case == "counselor_unaddressed":
        crew = await _crew(("counselor", "Ezri"), ("operations_officer", "O'Brien"), ("operations_coordinator", None))
        await _counselor_check_ins(ws, crew)

        out = await _ask(_registered(_runtime(ws, crew)), crew.ids["Ezri"], {"recipient": "O'Brien"})

        assert (out["count"], [m["to"] for m in out["messages"]], out["unconfirmed"], "note" in out) == (
            1, ["O'Brien"], 3, False,
        )
        return
    crew = await _crew(("counselor", "Ezri"), ("operations_officer", "O'Brien"), ("operations_scheduler", "Odo"))
    ezri = crew.ids["Ezri"]
    tools = _registered(_runtime(ws, crew))
    if case == "truncated_page":
        for text in (
            "[DM @O'Brien] Relays? [/DM]", "[DM @Odo] Anomalies? [/DM]", "[DM @Odo] Second watch report due. [/DM]",
        ):
            await _proactive_dm(ws, crew, ezri, text)
            await _tick()
        assert len(_dm_titles(ward_room.db_path)) == 3, "premise: three DMs are stored in the shared channel"

        one = await _ask(tools, ezri, {"recipient": "O'Brien", "limit": 1})
        three = await _ask(tools, ezri, {"recipient": "O'Brien", "limit": 3})

        assert (one["count"], one["truncated"], one["unconfirmed"], one["note"]) == (0, True, 0, notes["unconfirmed"])
        assert (three["count"], [m["to"] for m in three["messages"]], three["truncated"]) == (1, ["O'Brien"], False)
        return
    await _proactive_dm(ws, crew, ezri, "[DM @Odo] Any anomalies on your watch? [/DM]")
    unfiltered = await _ask(tools, ezri)
    assert [(m["to"], m["recipient_basis"]) for m in unfiltered["messages"]] == [("Odo", EXACT)], (
        "premise: the one stored DM is proven to Odo"
    )
    if case == "unconfirmed_counted":
        crew.callsigns.set_callsign("operations_scheduler", "")
        assert crew.callsigns.resolve("Odo") is None, "premise: Odo's callsign is gone"

    out = await _ask(tools, ezri, {"recipient": "O'Brien"})

    counted, note = (1, "unconfirmed") if case == "unconfirmed_counted" else (0, "empty")
    assert (out["count"], out["messages"], out["unconfirmed"], out["note"]) == (0, [], counted, notes[note])


@pytest.mark.parametrize("case", ["to_and_replied_by", "note_to_part", "crew_profile_callsigns"])
async def test_every_model_facing_label_passes_the_gap_and_referent_gates(case: str, ward_room: _WardRoomRig) -> None:
    if case == "crew_profile_callsigns":
        folder = Path(__file__).resolve().parents[1] / "config" / "standing_orders" / "crew_profiles"
        profiles = [yaml.safe_load(p.read_text(encoding="utf-8")) or {} for p in sorted(folder.glob("*.yaml"))]
        callsigns = [str(p["callsign"]) for p in profiles if p.get("callsign")]
        assert len(callsigns) >= 15 and {"Number One", "O'Brien"} <= set(callsigns), "premise: the scan read the crew"

        refused = [label for label in (*callsigns, CAPTAIN_LABEL, UNREGISTERED_LABEL, CREW_MEMBER_LABEL)
                   if not _is_label(label)]

        assert refused == []
        return
    for hostile in (_HOSTILE_CALLSIGN, _HOSTILE_CALLSIGN_2):
        assert LABEL_RE.fullmatch(hostile) and is_capability_gap(hostile) and extract_referents(hostile), (
            "premise: the pattern admits it, so only the gates can refuse it"
        )
    ws = ward_room.service
    crew = await _crew(
        ("counselor", "Ezri"), ("security_officer", _HOSTILE_CALLSIGN), ("engineering_officer", _HOSTILE_CALLSIGN_2),
    )
    ezri, worf = crew.ids["Ezri"], crew.ids[_HOSTILE_CALLSIGN]
    tools = _registered(_runtime(ws, crew))
    if case == "to_and_replied_by":
        counselor = _make_counselor(ward_room=ws, agent_id=ezri, callsign="Ezri")
        assert await CounselorAgent._send_therapeutic_dm(counselor, worf, _HOSTILE_CALLSIGN, "Checking in.")
        thread = (await ws.list_threads((await ws.get_or_create_dm_channel(ezri, worf)).id))[0]
        await _tick()
        await ws.create_post(thread.id, worf, "ok", author_callsign=_HOSTILE_CALLSIGN)

        out = await _ask(tools, ezri)
        filtered = await _ask(tools, ezri, {"recipient": _HOSTILE_CALLSIGN})

        assert [(m["to"], m["replied_by"], m["recipient_basis"]) for m in out["messages"]] == [
            (CREW_MEMBER_LABEL, [CREW_MEMBER_LABEL], EXACT),
        ]
        assert [m["to"] for m in filtered["messages"]] == [CREW_MEMBER_LABEL]
        blob = json.dumps([out, filtered])
    else:
        empty = await _ask(tools, ezri, {"recipient": _HOSTILE_CALLSIGN_2})

        assert empty["note"] == NOTE_EMPTY.format(to_part=" to that crew member", hours=WINDOW_DEFAULT_HOURS)
        blob = json.dumps(empty)

    assert "9f3c2ab1e" not in blob
    assert extract_referents(blob) == [] and is_capability_gap(blob) is False


@pytest.mark.parametrize("case", ["type_id_or_empty", "space_callsign"])
async def test_counselor_titles_name_only_a_resolvable_callsign(case: str, ward_room: _WardRoomRig) -> None:
    ws = ward_room.service
    keys = ("to", "recipient_basis", "delivery")
    if case == "type_id_or_empty":
        crew = await _crew(("counselor", "Ezri"), ("operations_officer", "O'Brien"), ("operations_coordinator", None))
        coordinator = crew.ids["operations_coordinator"]
        await _counselor_check_ins(ws, crew)
        assert [title for _name, title in _dm_titles(ward_room.db_path)] == [
            "[Counselor check-in with @operations_coordinator]", f"[Counselor check-in with @{coordinator}]",
            "[Counselor check-in with @]", "[Counselor check-in with @O'Brien]",
        ], "premise: the real producer titled them by type, by id, by an empty callsign and by a callsign"

        out = await _ask(_registered(_runtime(ws, crew)), crew.ids["Ezri"])

        assert [tuple(m[k] for k in keys) for m in out["messages"]] == (
            [("O'Brien", EXACT, DELIVERED)] + [(None, UNCONFIRMED, UNKNOWN)] * 3
        )
        return
    crew = await _crew(("counselor", "Ezri"), ("architect", "Number One"))
    ezri, number_one = crew.ids["Ezri"], crew.ids["Number One"]
    counselor = _make_counselor(ward_room=ws, agent_id=ezri, callsign="Ezri")
    assert await CounselorAgent._send_therapeutic_dm(counselor, number_one, "Number One", "Checking in.")
    assert [title for _name, title in _dm_titles(ward_room.db_path)] == ["[Counselor check-in with @Number One]"], (
        "premise: the title carries a callsign with a space"
    )
    tools = _registered(_runtime(ws, crew))

    out = await _ask(tools, ezri)
    filtered = await _ask(tools, ezri, {"recipient": "number one"})

    assert [tuple(m[k] for k in keys) for m in out["messages"]] == [("Number One", EXACT, DELIVERED)]
    assert (filtered["count"], [m["to"] for m in filtered["messages"]], filtered["unconfirmed"]) == (
        1, ["Number One"], 0,
    )


def test_the_flag_defaults_off() -> None:
    assert "message_receipts_enabled" in WardRoomConfig.model_fields
    assert WardRoomConfig().message_receipts_enabled is False
    assert SystemConfig().ward_room.message_receipts_enabled is False


# ── W1-W3: the executor offer ───────────────────────────────────────────


@pytest.mark.parametrize("case", ["flag_off", "no_ward_room", "mock_config"])
async def test_the_offer_is_unchanged_when_off(
    case: str, ward_room: _WardRoomRig, monkeypatch: pytest.MonkeyPatch,
) -> None:
    ws = ward_room.service
    baseline = await _capture_offer(
        monkeypatch, SimpleNamespace(config=SystemConfig(), tool_registry=ToolRegistry()), _COUNSELOR,
    )
    armed = SimpleNamespace(config=_armed_config(), ward_room=ws, tool_registry=ToolRegistry())
    assert "message_receipts" in _names(await _capture_offer(monkeypatch, armed, _COUNSELOR)), (
        "premise: the rig sees the offer when it is armed"
    )
    if case == "flag_off":
        runtime = SimpleNamespace(config=SystemConfig(), ward_room=ws, tool_registry=ToolRegistry())
    elif case == "no_ward_room":
        runtime = SimpleNamespace(config=_armed_config(), tool_registry=ToolRegistry())
    else:
        config = SystemConfig()
        config.ward_room = MagicMock()
        runtime = SimpleNamespace(config=config, ward_room=ws, tool_registry=ToolRegistry())

    offered = await _capture_offer(monkeypatch, runtime, _COUNSELOR)

    assert offered == baseline
    assert runtime.tool_registry.get("message_receipts") is None


async def test_the_offer_registers_once_and_offers_when_on(
    ward_room: _WardRoomRig, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
) -> None:
    tools = ToolRegistry()
    runtime = SimpleNamespace(config=_armed_config(), ward_room=ward_room.service, tool_registry=tools)

    first = _names(await _capture_offer(monkeypatch, runtime, _COUNSELOR))

    assert first.count("message_receipts") == 1
    registration = tools.get("message_receipts")
    assert registration is not None and isinstance(registration.tool, MessageReceiptsTool)
    assert registration.provider == "AD-1229" and registration.tags == ["message_receipts", "ward_room"]
    with caplog.at_level(logging.WARNING, logger="probos.tools.registry"):
        second = _names(await _capture_offer(monkeypatch, runtime, _COUNSELOR))
    assert second.count("message_receipts") == 1
    assert tools.get("message_receipts") is registration
    assert [r for r in caplog.records if "Replacing existing tool registration" in r.getMessage()] == []


class _RefusingRegistry(ToolRegistry):
    def register(self, tool: Any, **kwargs: Any) -> Any:
        if tool.tool_id == "message_receipts":
            raise RuntimeError("registration refused for the test")
        return super().register(tool, **kwargs)


async def test_an_offer_registration_failure_degrades(
    ward_room: _WardRoomRig, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
) -> None:
    runtime = SimpleNamespace(config=_armed_config(), ward_room=ward_room.service, tool_registry=_RefusingRegistry())

    with caplog.at_level(logging.WARNING, logger="probos.cognitive.agentic_dispatch"):
        offered = _names(await _capture_offer(monkeypatch, runtime, _COUNSELOR))

    assert "message_receipts" not in offered
    assert runtime.tool_registry.get("message_receipts") is None
    assert any(r.getMessage().startswith("AD-1229:") for r in caplog.records if r.levelno == logging.WARNING)
