"""AD-1346 M3c2 (#1604): the six routing seams' shadow statements on a real boot: one crossing test and the golden test.

The six: the proactive cycle, Ward Room routing, the Captain's DM route, a group fan-out turn, the Captain's ACK of a
browser action, and the browser action a DM reply proposes inline.

- G3 one boot: under a Captain's stop on a certified crew agent, each of the six leaves a parity row of today's outcome
     ``refuse`` beside the shadow outcome ``would_refuse`` and the code ``agent_stopped`` in ``admission_shadow.db``. The
     proactive cycle, the group fan-out, the ACK and the inline action also leave an ``admit``/``admit``/``admitted`` row
     from the calls made before the order. No disagreement sample is keyed on that agent, and startup handed the Ward Room
     router the boot's service.
- G4 two boots, ``admission.shadow_enabled`` true and then false: the same calls answer the same, byte for byte once the
     order's id, its start time and the agent's id are replaced (#1604 property 12).

On every boot, G3 and G4 assert that the order is counted exactly once at the proactive, DM-route and ACK seams, which
only these calls reach while it is in force, and at least once at the Ward Room, group fan-out and tool seams, which the
ship's own work can also reach for a stopped agent.

Each boot loads ``config/system.yaml`` from this checkout, as ``ProbOSRuntime`` does when it is given no config and as
``tests/test_ad1343_stop_crossing.py`` boots its ships, with ``MockLLMClient`` and a data directory under ``tmp_path``. The
proactive loop's own task is stopped before any cycle here and its stagger is switched off, so only this test's cycles run,
and its DM sweep and think are spies. The DM route and the ACK route are called in-process through httpx's ASGI transport.
The proactive cycle, the Ward Room router and the DM route run on the boot itself; the group fan-out, the ACK and the
inline action run over test runtimes that hold the boot's stop record and shadow service, with the recording fakes of
``tests/test_ad1343_agent_stop.py`` and ``tests/test_ad745_pipeline_dispatch.py``.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from probos.admission import AdmissionService
from probos.admission.report import open_read_only, run_query
from probos.admission.store import STORE_FILENAME
from probos.cognitive.cognitive_agent import CognitiveAgent
from probos.cognitive.dm import DmReplyContext, DmReplyPipeline
from probos.cognitive.dm.action_dispatcher import ActionStatus, DispatchedAction
from probos.cognitive.llm_client import MockLLMClient
from probos.config import AuthConfig, SystemConfig, load_config
from probos.dm_reply import DmReply
from probos.routers import agent_actions as action_routes
from probos.routers import agents as agent_routes
from probos.routers.thread_fanout import _fan_one_round
from probos.runtime import ProbOSRuntime
from tests.test_ad1343_agent_stop import (
    CREW_TYPE,
    TOKEN,
    _agent,
    _bearer,
    _FakeRegistry,
    _FanoutStore,
    _RecordingBrowserTool,
    _RecordingIntentBus,
    _SpyDispatcher,
)
from tests.test_ad745_pipeline_dispatch import _build_runtime

_SYSTEM_YAML = Path(__file__).resolve().parents[1] / "config" / "system.yaml"
_THREAD = "ad1346-m3c2-thread"
_ACTION = "ad1346-m3c2-action"
_REASON = "AD-1346 M3c2 crossing"
_REPLY = 'Looking. [ACTION: {"verb":"screenshot","args":{}}]'  # a tier-1 action: the inline step runs it
#: (work kind, seam) of each routing seam's shadow statement.
_ROUTING = (
    ("proactive_cycle", "proactive"),
    ("ward_room_notice", "ward_room"),
    ("direct_message", "dm_route"),
    ("group_turn", "group_fanout"),
    ("browser_action", "browser_action_ack"),
    ("browser_action", "tool"),
)
#: The (work kind, seam) pairs G3 calls before the order, so each holds an admitted verdict.
_ADMITTED = (
    ("proactive_cycle", "proactive"),
    ("group_turn", "group_fanout"),
    ("browser_action", "browser_action_ack"),
    ("browser_action", "tool"),
)
#: Seams only these calls reach while the order is in force: the cycle runs only when called here after its task is
#: stopped, and the DM route and the ACK are routes served only by the apps built here.
_ONCE = ("browser_action_ack", "dm_route", "proactive")
#: Seams the ship's own work can also reach for a stopped agent: its Ward Room posts, AD-970 kickoffs and the tool sink.
_AT_LEAST_ONCE = ("group_fanout", "tool", "ward_room")


async def _boot(data_dir: Path, *, shadow_enabled: bool = True) -> ProbOSRuntime:
    config = load_config(_SYSTEM_YAML)
    config.admission.shadow_enabled = shadow_enabled
    runtime = ProbOSRuntime(config=config, data_dir=data_dir, llm_client=MockLLMClient())
    await runtime.start()
    return runtime


def _certified_crew(rt: ProbOSRuntime, offered: set[str]) -> CognitiveAgent:
    """The first ``CognitiveAgent`` the cycle offered whose identity the facade resolves with a DID."""
    crew = next(
        (
            a for a in rt.registry.all()
            if a.id in offered and isinstance(a, CognitiveAgent) and getattr(rt.identity_service.resolve(a.id), "did", "")
        ),
        None,
    )
    assert crew is not None, "premise: the proactive cycle offered a certified crew agent"
    return crew


async def _ward_room(rt: ProbOSRuntime, agent_id: str) -> Any:
    """One Captain post in a ship channel that targets only ``agent_id`` and does not address it, so no notice is posted."""
    return await rt.ward_room_router._route_to_agents(
        target_agent_ids=[agent_id], is_captain=True, is_agent_post=False, mentioned_agent_ids=set(),
        channel=SimpleNamespace(channel_type="ship", name="general"), thread_id=_THREAD, channel_id="ad1346-m3c2-channel",
        event_type="ward_room_post_created", title="AD-1346 M3c2", author_id="captain",
        data={"author_callsign": "Captain"}, thread_context="context", cooldown=0, current_round=0, round_participants=set(),
    )


async def _dm(rt: ProbOSRuntime, agent_id: str) -> list[Any]:
    """The Captain's DM route on an app over the boot, called in-process: its status and body."""
    app = FastAPI()
    app.include_router(agent_routes.router)
    app.state.runtime = rt
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        answer = await client.post(f"/api/agent/{agent_id}/chat", json={"message": "hi"})
    return [answer.status_code, answer.json()]


async def _fan_out(rt: ProbOSRuntime, agent_id: str) -> list[Any]:
    """One group fan-out round for ``agent_id`` over a test runtime holding the boot's stop record and shadow service:
    the round's replies and the agents the bus was asked to send to."""
    bus = _RecordingIntentBus()
    runtime = SimpleNamespace(
        agent_stops=rt.agent_stops, admission_service=rt.admission_service, intent_bus=bus,
        registry=_FakeRegistry(_agent(agent_id, CREW_TYPE)),
    )
    replies = await _fan_one_round(
        runtime, _FanoutStore(), _THREAD, trigger_body="hello", candidate_ids=[agent_id], exclude_ids=set(),
        vision_messages=None, sanity_gate=None, t_start=0.0, broadcast=True,
    )
    return [replies, [intent.target_agent_id for intent in bus.sent]]


async def _ack(rt: ProbOSRuntime, agent_id: str) -> list[Any]:
    """The Captain's ACK of one pending tier-2 click by ``agent_id``, on an app over a test runtime holding the boot's stop
    record and shadow service: its status, ``ok`` or the refusal body, the browser tool's invocations and the marks."""
    dispatcher = _SpyDispatcher()
    dispatcher.register(
        DispatchedAction(
            action_id=_ACTION, agent_id=agent_id, captain_id="captain", thread_id=_THREAD, verb="click",
            args={"selector": "#submit"}, raw_intent="submit the form", tier=2,
            status=ActionStatus.ACK_PENDING, proposed_at=1_700_000_000.0,
        )
    )
    tool = _RecordingBrowserTool()
    runtime = SimpleNamespace(
        agent_stops=rt.agent_stops, admission_service=rt.admission_service,
        config=SystemConfig(auth=AuthConfig(crew_scope_token=TOKEN)), action_dispatcher=dispatcher, browser_tool=tool,
    )
    app = FastAPI()
    app.include_router(action_routes.router)
    app.state.runtime = runtime
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        answer = await client.post(f"/api/browser/actions/{_ACTION}/ack", headers=_bearer())
    body = answer.json()
    return [answer.status_code, body["ok"] if answer.status_code == 200 else body, tool.invocations, dispatcher.marked]


async def _inline(rt: ProbOSRuntime, agent_id: str) -> list[Any]:
    """AD-745's inline step for a reply by ``agent_id`` proposing one tier-1 action, over AD-745's test runtime holding the
    boot's stop record and shadow service: the reply text left, the browser tool's invocations and the actions kept."""
    runtime = _build_runtime()
    runtime.agent_stops = rt.agent_stops
    runtime.admission_service = rt.admission_service
    pipeline = DmReplyPipeline(DmReplyContext(
        runtime=runtime, agent=object(), agent_id=agent_id, callsign="Crew", req_message="captain DM text",
        reply=DmReply(body=_REPLY), has_image_attachment=False, per_attachment=[], sanity_gate=None,
        params={"thread_id": _THREAD, "dm_turn_id": "turn-1"}, message_text="captain DM text", sampling_state=None,
        avatar_event_bus=None,
    ))
    await pipeline.step_4e_action_dispatch()
    kept = [(a.verb, a.tier, a.status.value) for a in runtime.action_dispatcher.list_for_thread(_THREAD)]
    return [pipeline.ctx.response_text, len(runtime.browser_tool.invoked), kept]


async def _drive(rt: ProbOSRuntime, monkeypatch: pytest.MonkeyPatch) -> tuple[dict[str, Any], dict[str, int], str, str]:
    """A proactive cycle, a fan-out round, an ACK and an inline action with no order, then all six seams under a Captain's
    stop: the answers, the refusals the order counted at each routing seam, the normalised text and the agent."""
    loop = rt.proactive_loop
    assert loop is not None and rt.ward_room_router is not None, "premise: the boot has the proactive loop and the Ward Room router"
    await loop.stop()  # the loop's own task would run cycles of its own; only the cycles below run
    monkeypatch.setattr(rt.config.proactive_cognitive, "stagger_enabled", False)
    swept: list[str] = []

    async def _sweep(agent: Any, runtime: Any) -> None:
        swept.append(agent.id)

    async def _think(agent: Any, rank: Any, trust_score: float) -> None:
        return None

    monkeypatch.setattr(loop, "_check_unread_dms", _sweep)
    monkeypatch.setattr(loop, "_think_for_agent", _think)
    await loop._run_cycle()
    offered = set(swept)
    crew = _certified_crew(rt, offered)
    answers: dict[str, Any] = {
        "fan_out_admitted": await _fan_out(rt, crew.id),
        "ack_admitted": await _ack(rt, crew.id),
        "inline_admitted": await _inline(rt, crew.id),
    }
    record = (await rt.agent_stops.issue_stop(crew.id, reason=_REASON)).record
    before = rt.agent_stops.refused_counts(record.stop_id)
    swept.clear()
    await loop._run_cycle()
    answers["proactive_refused"] = [crew.id in swept, set(swept) == offered - {crew.id}]
    answers["ward_room_refused"] = await _ward_room(rt, crew.id)
    answers["dm_refused"] = await _dm(rt, crew.id)
    answers["fan_out_refused"] = await _fan_out(rt, crew.id)
    answers["ack_refused"] = await _ack(rt, crew.id)
    answers["inline_refused"] = await _inline(rt, crew.id)
    after = rt.agent_stops.refused_counts(record.stop_id)
    counted = {seam: after.get(seam, 0) - before.get(seam, 0) for _, seam in _ROUTING}
    text = json.dumps(answers, sort_keys=True, default=repr)
    for value, mark in ((record.stop_id, "<stop>"), (record.sender_detail()["since"], "<since>"), (crew.id, "<agent>")):
        text = text.replace(value, mark)
    return answers, counted, text, crew.id


def _assert_counted(counted: dict[str, int]) -> None:
    assert {seam: counted[seam] for seam in _ONCE} == dict.fromkeys(_ONCE, 1), counted
    assert all(counted[seam] >= 1 for seam in _AT_LEAST_ONCE), counted


async def test_each_routing_seam_records_todays_outcome_beside_the_shadow_verdict(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """G3 (kills RG-1 to RG-6 and RW-1 to RW-3)."""
    data_dir = tmp_path / "data"
    rt = await _boot(data_dir)
    try:
        assert isinstance(rt.admission_service, AdmissionService), "premise: the default boot builds the service"
        assert rt.ward_room_router is not None
        assert vars(rt.ward_room_router)["_admission"] is rt.admission_service, "startup hands the Ward Room router its service"
        answers, counted, _, agent_id = await _drive(rt, monkeypatch)
        _assert_counted(counted)
        assert answers["proactive_refused"] == [False, True]
    finally:
        await rt.stop()
    db = await open_read_only(data_dir / STORE_FILENAME)
    try:
        parity = await run_query(db, "parity_by_work_kind", ("0000-00-00",))
        disagreements = await run_query(db, "disagreement_samples", (1_000,))
    finally:
        await db.close()
    rows = {row[:5]: row[5] for row in parity}
    for work_kind, seam in _ROUTING:
        assert rows.get((work_kind, seam, "refuse", "would_refuse", "agent_stopped"), 0) >= 1, (work_kind, seam, sorted(rows))
    for work_kind, seam in _ADMITTED:
        assert rows.get((work_kind, seam, "admit", "admit", "admitted"), 0) >= 1, (work_kind, seam, sorted(rows))
    assert [row for row in disagreements if json.loads(row[-1])["key"] == agent_id] == []


async def test_with_shadow_off_the_routing_seams_answer_byte_identically(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """G4: #1604 property 12, the golden test for the six routing seams (D75)."""
    texts: dict[bool, str] = {}
    for enabled in (True, False):
        rt = await _boot(tmp_path / ("on" if enabled else "off"), shadow_enabled=enabled)
        try:
            assert isinstance(rt.admission_service, AdmissionService) is enabled, "premise: the switch decides the service"
            _, counted, texts[enabled], _ = await _drive(rt, monkeypatch)
            _assert_counted(counted)
            if enabled:
                seams = {seam for seam, _, _ in rt.admission_service.tally()}
                assert seams >= {seam for _, seam in _ROUTING}, "premise: the six shadow statements ran"
        finally:
            await rt.stop()
    assert texts[True] == texts[False]
