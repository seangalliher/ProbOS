"""AD-1343 S1 (#1595): the Captain's stop crosses a real, booted ship from the order to the refusal.

``tests/test_ad1343_agent_stop.py`` proves each link over fakes: the record and its store, the routes, the sinks. A chain can be
dead with every link correct: a route never registered, a store never started or never closed, a gate never handed to the
router. These tests boot a real ``ProbOSRuntime`` on ``tmp_path`` (as ``tests/test_trust_reconcile.py`` does) and cross the
whole chain:

* X1: the Captain's order through the ship's real API app -> ``agent_stops.db`` -> the intent bus, the consultation sink and the
  tool registry -> shutdown -> a second ship on the same data directory (the stop survives the restart) -> the Captain's lift.
* X2: the DM route of the real agents router refuses a stopped agent before the intent bus is touched.
* X3: the proactive cycle offers a stopped agent neither the BF-156 DM sweep nor a think.

Every ship lives in ``tmp_path`` (the live data directory is never read). Nothing here sleeps, waits on a timer or orders
anything by wall-clock time: the proactive stagger is switched off, and each wait on the bus is bounded.
"""

from __future__ import annotations

import asyncio
import contextlib
import sqlite3
import threading
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from probos.agent_stop import STOP_METADATA_KEY, STOP_REASON_CODE, AgentStopService
from probos.api import create_app
from probos.cognitive.cognitive_agent import CognitiveAgent
from probos.cognitive.consultation import ConsultationRequest
from probos.cognitive.llm_client import MockLLMClient
from probos.crew_utils import is_crew_agent
from probos.routers import agents as agent_routes
from probos.runtime import ProbOSRuntime
from probos.types import IntentMessage, IntentResult
from tests.test_ad1343_agent_stop import PRIVATE_FRAGMENT, REASON, STOPS, TOKEN, UNKNOWN_TOOL, _bearer

_BUS_TIMEOUT = 60.0  # seconds: a bound for a wedged bus, far above a mock-LLM turn
_DM_TEXT = "AD-1343 crossing: are you there?"


@contextlib.asynccontextmanager
async def _ship(data_dir: Path) -> AsyncIterator[ProbOSRuntime]:
    """A real ship on ``data_dir`` with the mock LLM, booted as tests/test_trust_reconcile.py boots one.

    A second ``stop()`` is a no-op (the shutdown guard), so a test may stop the ship itself before the block ends.
    """
    rt = ProbOSRuntime(data_dir=data_dir, llm_client=MockLLMClient())
    await rt.start()
    try:
        yield rt
    finally:
        await rt.stop()


@contextlib.asynccontextmanager
async def _calling(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    """``app`` called through ASGI on the test's own loop (never ``TestClient``)."""
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        yield client


def _crew(rt: ProbOSRuntime, *, not_this: str = "") -> Any:
    """The first crew agent of the ship, other than ``not_this``."""
    return next(a for a in rt.registry.all() if is_crew_agent(a, rt.ontology) and a.id != not_this)


def _dm(agent_id: str) -> IntentMessage:
    """A Captain's DM as the DM route builds it, minus the route's context blocks."""
    return IntentMessage(
        intent="direct_message",
        params={"text": _DM_TEXT, "from": "hxi_profile", "session": False, "session_history": []},
        target_agent_id=agent_id,
        ttl_seconds=_BUS_TIMEOUT,
    )


async def _send(rt: ProbOSRuntime, agent_id: str) -> IntentResult | None:
    """One DM through the ship's intent bus, the way every targeted intent travels."""
    return await asyncio.wait_for(rt.intent_bus.send(_dm(agent_id)), timeout=_BUS_TIMEOUT)


def _count_llm_requests_for_the_dm(rt: ProbOSRuntime, monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Wrap the ship's LLM client so every request that carries the crossing DM's text is recorded; returns the live record."""
    reached: list[str] = []
    real_complete = rt.llm_client.complete

    async def _recording_complete(request: Any, *args: Any, **kwargs: Any) -> Any:
        if _DM_TEXT in request.prompt or _DM_TEXT in str(request.messages):  # the DM text rides in the messages, not the prompt
            reached.append(request.id)
        return await real_complete(request, *args, **kwargs)

    monkeypatch.setattr(rt.llm_client, "complete", _recording_complete)
    return reached


def _names_the_order_not_the_reason(text: str | None, stop_id: str) -> bool:
    """A sender is told which order stopped the agent, never the Captain's reason."""
    return text is not None and stop_id in text and PRIVATE_FRAGMENT not in text


# X1
async def test_a_captain_stop_crosses_route_store_restart_and_the_sinks(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    data_dir = tmp_path / "data"
    async with _ship(data_dir) as rt:
        monkeypatch.setattr(rt.config.auth, "crew_scope_token", TOKEN)
        crew = _crew(rt)
        other = _crew(rt, not_this=crew.id)
        # premise: the wiring the whole chain rests on exists in a default boot, and the agent is one the stop guards
        assert isinstance(rt.agent_stops, AgentStopService)
        assert rt.tool_registry.stop_gate is rt.agent_stops
        assert rt.ward_room_router is not None and vars(rt.ward_room_router)["_agent_stops"] is rt.agent_stops
        assert isinstance(crew, CognitiveAgent) and rt.agent_stops.stop_for(crew.id) is None

        reached = _count_llm_requests_for_the_dm(rt, monkeypatch)
        # golden: before any order, a DM is delivered and carries no stop
        before = await _send(rt, crew.id)
        assert before is not None and STOP_METADATA_KEY not in (before.metadata or {})
        assert len(reached) >= 1  # the DM really reached the LLM client: "no stop metadata" alone is also true of a DM that went nowhere
        reached_before_order = len(reached)

        # the Captain's order, through the real API app
        async with _calling(create_app(rt)) as client:
            issued = await client.post(f"{STOPS}/{crew.id}", json={"reason": REASON}, headers=_bearer())
        assert issued.status_code == 200, issued.text
        stop_id = issued.json()["stop"]["stop_id"]
        assert rt.agent_stops.stop_for(crew.id).stop_id == stop_id

        # the sinks: each names the order and not the reason
        refused = await _send(rt, crew.id)
        assert refused is not None and refused.success is False
        assert _names_the_order_not_the_reason(refused.error, stop_id)
        assert refused.metadata[STOP_METADATA_KEY]["stop_id"] == stop_id
        assert len(reached) == reached_before_order  # the sink refused before any LLM work: the refused DM never reached the client
        consultation = await crew.handle_consultation_request(
            ConsultationRequest(requester_id="x", topic="t", question="q", target_agent_id=crew.id)
        )
        assert consultation.confidence == 0.0
        assert consultation.reasoning_summary == STOP_REASON_CODE
        assert _names_the_order_not_the_reason(consultation.answer, stop_id)

        tool = await rt.tool_registry.check_and_invoke(crew.id, UNKNOWN_TOOL, {})
        assert tool.metadata[STOP_METADATA_KEY]["stop_id"] == stop_id
        assert _names_the_order_not_the_reason(tool.error, stop_id)

        # the ship stops: the store is closed, the order is still in force in memory, and a new order cannot be written
        await rt.stop()
        assert rt.agent_stops.stop_for(crew.id) is not None
        unwritten = await rt.agent_stops.issue_stop(other.id, reason="x")
        assert unwritten.durable is False

    # the same data directory, a second ship: the order survived the restart
    async with _ship(data_dir) as rt2:
        monkeypatch.setattr(rt2.config.auth, "crew_scope_token", TOKEN)
        crew2 = rt2.registry.get(crew.id)
        assert crew2 is not None and crew2 is not crew  # premise: the same slot, a new agent object
        assert rt2.agent_stops is not rt.agent_stops
        record = rt2.agent_stops.stop_for(crew.id)
        assert record is not None and record.stop_id == stop_id
        assert rt2.agent_stops.stop_for(other.id) is None  # the order that was never written did not survive

        reached2 = _count_llm_requests_for_the_dm(rt2, monkeypatch)
        again = await _send(rt2, crew.id)
        assert again is not None and again.success is False
        assert _names_the_order_not_the_reason(again.error, stop_id)
        assert reached2 == []  # still refused after the restart: no LLM work for the DM

        async with _calling(create_app(rt2)) as client:
            lifted = await client.post(f"{STOPS}/{crew.id}/lift", json={"reason": "x"}, headers=_bearer())
        assert lifted.status_code == 200, lifted.text
        assert lifted.json()["refused_while_stopped"]["intent"] >= 1
        assert rt2.agent_stops.stop_for(crew.id) is None

        after = await _send(rt2, crew.id)
        assert after is not None and STOP_METADATA_KEY not in (after.metadata or {})
        assert len(reached2) >= 1  # and after the Captain's lift the DM reaches the LLM client again


def _store_worker_threads() -> set[threading.Thread]:
    """Every live SQLite connection worker thread (aiosqlite names its thread after ``_connection_worker_thread``)."""
    return {t for t in threading.enumerate() if t.is_alive() and "_connection_worker_thread" in t.name}


# X2
async def test_a_stopped_agent_gets_no_dm_turn_through_the_route(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    async with _ship(tmp_path / "data") as rt:
        crew = _crew(rt)
        sent: list[IntentMessage] = []
        real_send = rt.intent_bus.send

        async def spy(intent: IntentMessage, **kwargs: Any) -> IntentResult | None:
            sent.append(intent)
            return await real_send(intent, **kwargs)

        monkeypatch.setattr(rt.intent_bus, "send", spy)
        app = FastAPI()
        app.include_router(agent_routes.router)
        app.state.runtime = rt
        assert isinstance(rt.agent_stops, AgentStopService) and rt.agent_stops.stop_for(crew.id) is None  # premise

        async with _calling(app) as client:
            # golden: with no order, the DM route reaches the bus, so the spy is on the production path
            # (the route may send more than once: it retries a DM whose reply repeats the last one, as the mock LLM's does)
            delivered = await client.post(f"/api/agent/{crew.id}/chat", json={"message": "hi"})
            assert delivered.status_code == 200, delivered.text
            assert any(i.intent == "direct_message" and i.target_agent_id == crew.id for i in sent)
            sent.clear()

            order = await rt.agent_stops.issue_stop(crew.id, reason=REASON)
            refused = await client.post(f"/api/agent/{crew.id}/chat", json={"message": "hi"})

        assert refused.status_code == 409, refused.text
        detail = refused.json()["detail"]
        assert detail["code"] == "agent_stopped" and detail["stop_id"] == order.record.stop_id
        assert PRIVATE_FRAGMENT not in refused.text
        assert sent == []  # the route refused before the bus: no turn was begun, nothing queued for later


# X3
async def test_the_proactive_cycle_offers_a_stopped_agent_nothing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    async with _ship(tmp_path / "data") as rt:
        # premise: a default boot has the loop and the Ward Room it needs. If either is absent, stop and report: no fixture is made here.
        assert rt.proactive_loop is not None and rt.ward_room is not None
        # The loop's own task began a cycle at boot, with a list of agents it made before any order: it would offer them
        # to the spies below at whatever moment it wakes. Only this test's cycles may run.
        await rt.proactive_loop.stop()
        monkeypatch.setattr(rt.config.proactive_cognitive, "stagger_enabled", False)
        sweeps: list[str] = []
        thinks: list[str] = []

        async def sweep(agent: Any, runtime: Any) -> None:
            sweeps.append(agent.id)

        async def think(agent: Any, rank: Any, trust_score: float) -> None:
            thinks.append(agent.id)

        monkeypatch.setattr(rt.proactive_loop, "_check_unread_dms", sweep)
        monkeypatch.setattr(rt.proactive_loop, "_think_for_agent", think)

        # golden: with no order, the cycle offers crew the DM sweep and a think, so the spies see what the cycle does
        await rt.proactive_loop._run_cycle()
        offered_sweeps, offered_thinks = set(sweeps), set(thinks)
        both = [agent_id for agent_id in sweeps if agent_id in offered_thinks]
        assert len(offered_sweeps) >= 2 and both
        stopped_id = both[0]
        sweeps.clear()
        thinks.clear()

        order = await rt.agent_stops.issue_stop(stopped_id, reason=REASON)
        assert order.durable is True
        await rt.proactive_loop._run_cycle()

        assert stopped_id not in sweeps and stopped_id not in thinks
        assert sweeps and set(sweeps) == offered_sweeps - {stopped_id}  # the order took one agent out of the cycle, no one else
        assert set(thinks) == offered_thinks - {stopped_id}


# X4
async def test_a_ship_whose_stop_store_cannot_open_does_not_start_and_runs_no_agent(tmp_path: Path) -> None:
    probe = AgentStopService(data_dir=tmp_path / "probe")
    await probe.start()
    try:
        assert _store_worker_threads()  # premise: an open store shows up as a live worker thread, so the check below can see one
    finally:
        await probe.stop()

    data_dir = tmp_path / "data"
    (data_dir / "agent_stops.db").mkdir(parents=True)  # a directory where the database file belongs: SQLite cannot open it
    assert (data_dir / "agent_stops.db").is_dir()  # premise
    threads_before = _store_worker_threads()

    rt = ProbOSRuntime(data_dir=data_dir, llm_client=MockLLMClient())
    try:
        with pytest.raises((OSError, sqlite3.Error)):
            await rt.start()  # the rollback of a failed start tears the half-built ship down and re-raises the store's error

        assert list(rt.registry.all()) == []  # no agent was registered: nothing ran without the record
    finally:
        await rt.stop()  # a no-op after the rollback of a failed start; it ends a ship that did start, so a failing test leaks nothing
    stragglers = _store_worker_threads() - threads_before
    for straggler in stragglers:
        straggler.join(timeout=10.0)  # a closed connection's worker thread may still be winding down: bounded, never a sleep
    assert {t for t in stragglers if t.is_alive()} == set()  # and the failed boot left no store connection thread running
