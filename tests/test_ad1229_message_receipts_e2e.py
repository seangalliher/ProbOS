"""AD-1229 (#1202): the crossing tests -- act, the recipient responds, the agent reads it.

Nothing between the steps is stubbed. A real producer writes the direct message
into a real Ward Room, the recipient replies through the service's public API,
and the agent reads the receipt back through the tool that the real
``WorkItemAgenticExecutor`` registered and offered. The only doubles are the LLM
boundary inside the offer rig and ``SimpleNamespace`` agents.

E1 drives the proactive ``[DM @x]`` producer (crew and Captain); E2 drives the
AD-505 therapeutic DM. The executor's identity check is fail-closed (P21): a
runtime carrying a real agent registry must also carry an ontology and a trust
network, so E1 supplies a real ``TrustNetwork`` rather than stubbing identity.
"""

from __future__ import annotations

import asyncio
import hashlib
import sqlite3
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from probos.cognitive.counselor import CounselorAgent
from probos.config import SystemConfig
from probos.consensus.trust import TrustNetwork
from probos.crew_profile import CallsignRegistry
from probos.proactive import ProactiveCognitiveLoop
from probos.substrate.identity import generate_pool_ids
from probos.substrate.registry import AgentRegistry
from probos.tools.message_receipts_tool import (
    CAPTAIN_LABEL,
    DELIVERED,
    NO_REPLY_YET,
    READ_NOT_RECORDED,
    REPLIED,
    MessageReceiptsTool,
)
from probos.tools.registry import ToolRegistry
from probos.ward_room import WardRoomService
from probos.ward_room.channels import captain_dm_channel_name, dm_channel_name

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


def _dm_rows(db_path: Path) -> list[tuple[str, str]]:
    con = sqlite3.connect(str(db_path))
    try:
        return sorted(con.execute(
            "SELECT t.author_id, c.name FROM threads t JOIN channels c ON c.id = t.channel_id "
            "WHERE c.channel_type = 'dm'"
        ).fetchall())
    finally:
        con.close()


def _agent(agent_type: str, callsign: str) -> SimpleNamespace:
    return SimpleNamespace(
        id=generate_pool_ids(agent_type, agent_type, 1)[0], agent_type=agent_type, pool=agent_type,
        callsign=callsign, is_alive=True, capabilities=[],
    )


async def _directory(*agents: SimpleNamespace) -> tuple[AgentRegistry, CallsignRegistry]:
    registry = AgentRegistry()
    callsigns = CallsignRegistry()
    for agent in agents:
        await registry.register(agent)
        callsigns.set_callsign(agent.agent_type, agent.callsign)
    callsigns.bind_registry(registry)
    return registry, callsigns


class _Ontology:
    def get_agent_department(self, agent_type: str) -> str | None:
        return {
            "counselor": "medical", "security_officer": "security", "engineering_officer": "engineering",
        }.get(agent_type)


async def _capture_offer(
    monkeypatch: pytest.MonkeyPatch, runtime: Any, agent_id: str,
) -> list[str]:
    """Drive the REAL executor tool assembly (the AD-1226 rig) and name what reached the loop."""
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
    return [(d.get("function") or {}).get("name") or d.get("name") for d in seen["tools"]]


async def _ask(tools: ToolRegistry, agent_id: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    result = await tools.check_and_invoke(agent_id, "message_receipts", params or {}, agent_rank="ensign")
    assert result.error is None, result.error
    return result.output


async def test_e2e_proactive_dm_then_reply_then_receipt_through_the_offered_tool(
    ward_room: _WardRoomRig, monkeypatch: pytest.MonkeyPatch,
) -> None:
    ws = ward_room.service
    ezri = _agent("counselor", "Ezri")
    worf = _agent("security_officer", "Worf")
    geordi = _agent("engineering_officer", "LaForge")
    agents, callsigns = await _directory(ezri, worf, geordi)

    def _runtime(config: SystemConfig) -> SimpleNamespace:
        return SimpleNamespace(
            config=config, ward_room=ws, registry=agents, callsign_registry=callsigns,
            tool_registry=ToolRegistry(), hebbian_router=None, trust_network=TrustNetwork(),
            ontology=_Ontology(), attachment_store=None, artifact_store=None, episodic_memory=None,
            work_item_store=None, chat_thread_store=None, emit_event=lambda *_args, **_kwargs: None,
        )

    armed = SystemConfig()
    armed.ward_room.message_receipts_enabled = True
    runtime = _runtime(armed)

    # Step 0 (premise): the real executor registers and offers the tool only when armed.
    assert "message_receipts" in await _capture_offer(monkeypatch, runtime, ezri.id)
    registration = runtime.tool_registry.get("message_receipts")
    assert registration is not None and registration.provider == "AD-1229"
    unarmed = _runtime(SystemConfig())
    assert "message_receipts" not in await _capture_offer(monkeypatch, unarmed, ezri.id)
    assert unarmed.tool_registry.get("message_receipts") is None

    # Step 1: the real proactive producer writes two DMs; an unknown callsign stores nothing.
    loop = ProactiveCognitiveLoop()
    loop.set_runtime(runtime)
    _, actions = await loop.extract_and_execute_dms(
        ezri,
        "[DM @Worf] How are you holding up after the drill? [/DM] "
        "[DM @captain] Crew check-ins are on schedule. [/DM] "
        "[DM @Nobody] Is anyone there? [/DM]",
    )
    assert [a["target_callsign"] for a in actions] == ["Worf", "captain"]
    assert _dm_rows(ward_room.db_path) == sorted([
        (ezri.id, dm_channel_name(ezri.id, worf.id)), (ezri.id, captain_dm_channel_name(ezri.id)),
    ])

    # Step 2: both are delivered, neither answered, read is not recorded.
    tools = runtime.tool_registry
    before = _table_digest(ward_room.db_path)
    first = await _ask(tools, ezri.id)
    assert _table_digest(ward_room.db_path) == before
    assert first["count"] == 2
    by_to = {m["to"]: m for m in first["messages"]}
    assert set(by_to) == {"Worf", CAPTAIN_LABEL}
    assert all(m["delivery"] == DELIVERED and m["reply"] == NO_REPLY_YET for m in by_to.values())
    assert all(m["read"] == READ_NOT_RECORDED for m in by_to.values())

    # Step 3: Worf and the Captain reply through the real Ward Room.
    worf_channel = await ws.get_or_create_dm_channel(ezri.id, worf.id)
    captain_channel = await ws.get_channel_by_name(captain_dm_channel_name(ezri.id))
    assert captain_channel is not None
    worf_thread = (await ws.list_threads(worf_channel.id))[0]
    captain_thread = (await ws.list_threads(captain_channel.id))[0]
    events_before_replies = len(ward_room.events)
    await _tick()
    await ws.create_post(worf_thread.id, worf.id, "Fine, Counselor. Thank you for asking.", author_callsign="Worf")
    await ws.create_post(captain_thread.id, "captain", "Noted, thank you.")
    assert len(ward_room.events) > events_before_replies, "premise: the collector sees Ward Room events"

    # Step 4 (write trap) brackets the next three reads.
    before, emitted = _table_digest(ward_room.db_path), len(ward_room.events)
    to_worf = await _ask(tools, ezri.id, {"recipient": "Worf"})
    to_captain = await _ask(tools, ezri.id, {"recipient": "captain"})
    to_laforge = await _ask(tools, ezri.id, {"recipient": "LaForge"})
    assert _table_digest(ward_room.db_path) == before
    assert len(ward_room.events) == emitted

    assert to_worf["count"] == 1
    assert (to_worf["messages"][0]["reply"], to_worf["messages"][0]["recipient_replies"]) == (REPLIED, 1)
    assert to_worf["messages"][0]["replied_by"] == ["Worf"]
    assert to_captain["count"] == 1
    assert (to_captain["messages"][0]["reply"], to_captain["messages"][0]["replied_by"]) == (REPLIED, [CAPTAIN_LABEL])

    # Step 5: nothing was sent to LaForge, so nothing is stored -- said as such.
    assert to_laforge["count"] == 0 and to_laforge["messages"] == []
    assert to_laforge["note"] == "No direct message from you to LaForge in the last 24 hours is stored in the Ward Room."


def _make_counselor(*, ward_room: WardRoomService, agent_id: str, callsign: str) -> CounselorAgent:
    """The tests/test_counselor_therapeutic.py shape, with a real id and a real Ward Room."""
    agent = object.__new__(CounselorAgent)
    agent._agent_type = "counselor"
    agent.id = agent_id
    agent.callsign = callsign
    agent._ward_room = ward_room
    agent._ward_room_router = None
    agent._directive_store = None
    agent._dream_scheduler = None
    agent._proactive_loop = None
    agent._registry = None
    agent._dm_cooldowns = {}
    agent._cognitive_profiles = {}
    agent._emit_event_fn = None
    agent._trust_network = None
    agent._hebbian_router = None
    agent._crew_profiles = None
    agent._episodic_memory = None
    agent._add_event_listener_fn = None
    agent._profile_store = None
    agent.DM_COOLDOWN_SECONDS = 0
    agent._intervention_targets = set()
    return agent


async def test_e2e_counselor_therapeutic_dm_receipt(ward_room: _WardRoomRig) -> None:
    ws = ward_room.service
    ezri = _agent("counselor", "Ezri")
    worf = _agent("security_officer", "Worf")
    agents, callsigns = await _directory(ezri, worf)
    counselor = _make_counselor(ward_room=ws, agent_id=ezri.id, callsign="Ezri")
    tools = ToolRegistry()
    tools.register(
        MessageReceiptsTool(runtime=SimpleNamespace(ward_room=ws, registry=agents, callsign_registry=callsigns)),
        provider="AD-1229", tags=["message_receipts", "ward_room"],
    )

    assert await CounselorAgent._send_therapeutic_dm(counselor, worf.id, "Worf", "Checking in after the drill.")

    sent = await _ask(tools, ezri.id)
    assert sent["count"] == 1
    assert {k: sent["messages"][0][k] for k in ("to", "delivery", "reply", "archived")} == {
        "to": "Worf", "delivery": DELIVERED, "reply": NO_REPLY_YET, "archived": False,
    }
    thread = (await ws.list_threads((await ws.get_or_create_dm_channel(ezri.id, worf.id)).id))[0]
    assert thread.author_id == ezri.id, "premise: the AD-505 DM is authored under the Counselor's registry id"

    await _tick()
    await ws.create_post(thread.id, worf.id, "Appreciated, Counselor.", author_callsign="Worf")
    replied = await _ask(tools, ezri.id)
    assert (replied["messages"][0]["reply"], replied["messages"][0]["replied_by"]) == (REPLIED, ["Worf"])
    assert [d["thread_id"] for d in await ws.get_unread_dms(ezri.id, limit=10)] == [thread.id], (
        "premise: before archival the reply is offered to Ezri as new"
    )

    await _tick()
    assert await ws.archive_dm_messages(max_age_hours=0) >= 1
    archived = await _ask(tools, ezri.id)
    assert archived["count"] == 1
    assert (archived["messages"][0]["archived"], archived["messages"][0]["reply"]) == (True, REPLIED)
    assert await ws.get_unread_dms(ezri.id, limit=10) == []
    assert await ws.get_unread_dms(worf.id, limit=10) == []
