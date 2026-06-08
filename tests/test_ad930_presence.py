"""AD-930: crew presence endpoint tests (offline / online / working / in_meeting).

BF-287 discipline: the endpoint is exercised against a REAL ``ChatThreadStore``
on ``tmp_path`` and a REAL ``CommunicationsConfig`` — no MagicMock at the store
or config boundary. The registry is a real-but-fake stub (``_FakeRegistry`` of
``_FakeAgent`` duck-objects exposing ``id`` / ``agent_type`` / ``is_alive`` /
``meta.last_active``), and the runtime is a plain ``SimpleNamespace`` shell. The
crew ``agent_type``s are drawn from ``crew_utils._WARD_ROOM_CREW`` so
``is_crew_agent(agent, None)`` resolves crew via the legacy set.

AD-930 aggregates three verified-existing signals (it invents no telemetry):
liveness (``is_alive``), in_meeting (a non-archived thread with
``metadata.meeting_active`` + the agent in ``participants``), and working
(``meta.last_active`` within ``presence_working_window_seconds`` — an honest
recent-activity proxy, NOT a true in-flight flag).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from probos.config import CommunicationsConfig
from probos.routers.crew import crew_presence
from probos.threads import ChatThreadStore


# ---------------- BF-287 real-but-fake substrate stubs ----------------


class _FakeAgent:
    """Duck-object exposing exactly what ``crew_presence`` reads."""

    def __init__(
        self,
        agent_id: str,
        agent_type: str,
        *,
        is_alive: bool = True,
        last_active: datetime | None = None,
    ) -> None:
        self.id = agent_id
        self.agent_type = agent_type          # is_crew_agent reads .agent_type
        self.is_alive = is_alive              # liveness floor
        self.meta = SimpleNamespace(last_active=last_active)  # working proxy


class _FakeRegistry:
    """Real-but-fake registry: ``.all()`` only (no MagicMock)."""

    def __init__(self, agents: list[_FakeAgent]) -> None:
        self._a = agents

    def all(self) -> list[_FakeAgent]:
        return list(self._a)


def _runtime(
    *,
    registry,
    store,
    config: CommunicationsConfig | None = None,
):
    """A plain runtime shell — only the attrs the endpoint touches."""
    return SimpleNamespace(
        registry=registry,
        ontology=None,
        chat_thread_store=store,
        config=SimpleNamespace(communications=config or CommunicationsConfig()),
    )


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ---------------- 1. in_meeting ----------------


@pytest.mark.asyncio
async def test_in_meeting_when_participant_of_meeting_active_thread(tmp_path):
    store = ChatThreadStore(tmp_path / "chat_threads.db")
    store.create_thread(
        title="Standup",
        participants=["forge-1"],
        metadata={"meeting_active": True},
    )
    agent = _FakeAgent("forge-1", "builder", last_active=_now())
    runtime = _runtime(registry=_FakeRegistry([agent]), store=store)

    result = await crew_presence(runtime=runtime)

    assert result["presence"]["forge-1"] == "in_meeting"


# ---------------- 2. working (just inside the window) ----------------


@pytest.mark.asyncio
async def test_working_when_recently_active_just_inside_window(tmp_path):
    store = ChatThreadStore(tmp_path / "chat_threads.db")
    # 89s ago — just inside the 90s default window.
    agent = _FakeAgent(
        "forge-1", "builder", last_active=_now() - timedelta(seconds=89)
    )
    runtime = _runtime(registry=_FakeRegistry([agent]), store=store)

    result = await crew_presence(runtime=runtime)

    assert result["presence"]["forge-1"] == "working"


# ---------------- 3. online (idle, just outside the window) ----------------


@pytest.mark.asyncio
async def test_online_when_idle_just_outside_window(tmp_path):
    store = ChatThreadStore(tmp_path / "chat_threads.db")
    # 91s ago — just outside the 90s default window -> alive + idle -> online.
    agent = _FakeAgent(
        "scout-1", "scout", last_active=_now() - timedelta(seconds=91)
    )
    runtime = _runtime(registry=_FakeRegistry([agent]), store=store)

    result = await crew_presence(runtime=runtime)

    assert result["presence"]["scout-1"] == "online"


# ---------------- 4. offline (not alive) ----------------


@pytest.mark.asyncio
async def test_offline_when_not_alive(tmp_path):
    store = ChatThreadStore(tmp_path / "chat_threads.db")
    # Not alive (SPAWNING/RECYCLING) -> offline even with recent activity.
    agent = _FakeAgent(
        "bones-1", "diagnostician", is_alive=False, last_active=_now()
    )
    runtime = _runtime(registry=_FakeRegistry([agent]), store=store)

    result = await crew_presence(runtime=runtime)

    assert result["presence"]["bones-1"] == "offline"


# ---------------- 5. non-crew excluded ----------------


@pytest.mark.asyncio
async def test_non_crew_agent_absent_from_presence(tmp_path):
    store = ChatThreadStore(tmp_path / "chat_threads.db")
    crew = _FakeAgent("forge-1", "builder", last_active=_now())
    # file_reader is NOT in _WARD_ROOM_CREW -> excluded by is_crew_agent.
    non_crew = _FakeAgent("reader-1", "file_reader", last_active=_now())
    runtime = _runtime(registry=_FakeRegistry([crew, non_crew]), store=store)

    result = await crew_presence(runtime=runtime)

    assert "forge-1" in result["presence"]
    assert "reader-1" not in result["presence"]


# ---------------- 6. precedence (in_meeting beats working) ----------------


@pytest.mark.asyncio
async def test_in_meeting_beats_working_precedence(tmp_path):
    store = ChatThreadStore(tmp_path / "chat_threads.db")
    store.create_thread(
        title="Sync",
        participants=["forge-1"],
        metadata={"meeting_active": True},
    )
    # Recently active AND in a meeting -> in_meeting wins.
    agent = _FakeAgent("forge-1", "builder", last_active=_now())
    runtime = _runtime(registry=_FakeRegistry([agent]), store=store)

    result = await crew_presence(runtime=runtime)

    assert result["presence"]["forge-1"] == "in_meeting"


# ---------------- 7. registry None degrade ----------------


@pytest.mark.asyncio
async def test_registry_none_returns_empty(tmp_path):
    store = ChatThreadStore(tmp_path / "chat_threads.db")
    runtime = _runtime(registry=None, store=store)

    result = await crew_presence(runtime=runtime)

    assert result == {"presence": {}, "count": 0}


# ---------------- 8. store None degrade ----------------


@pytest.mark.asyncio
async def test_store_none_degrades_without_in_meeting(tmp_path):
    # No chat_thread_store -> no in_meeting computed; alive agents fall
    # through to working/online without crashing.
    working = _FakeAgent("forge-1", "builder", last_active=_now())
    idle = _FakeAgent(
        "scout-1", "scout", last_active=_now() - timedelta(minutes=10)
    )
    runtime = _runtime(registry=_FakeRegistry([working, idle]), store=None)

    result = await crew_presence(runtime=runtime)

    assert result["presence"]["forge-1"] == "working"
    assert result["presence"]["scout-1"] == "online"
    assert "in_meeting" not in result["presence"].values()


# ---------------- 9. count integrity ----------------


@pytest.mark.asyncio
async def test_count_equals_crew_presence_size(tmp_path):
    store = ChatThreadStore(tmp_path / "chat_threads.db")
    agents = [
        _FakeAgent("forge-1", "builder", last_active=_now()),
        _FakeAgent("scout-1", "scout", last_active=_now() - timedelta(minutes=10)),
        _FakeAgent("bones-1", "diagnostician", is_alive=False),
        _FakeAgent("reader-1", "file_reader", last_active=_now()),  # non-crew
    ]
    runtime = _runtime(registry=_FakeRegistry(agents), store=store)

    result = await crew_presence(runtime=runtime)

    # count == len(presence) and equals the crew-agent count (3 crew, 1 non-crew).
    assert result["count"] == len(result["presence"])
    assert result["count"] == 3
