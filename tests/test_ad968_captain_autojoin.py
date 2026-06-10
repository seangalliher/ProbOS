"""AD-968 (Natural Conversation epic #882): the Captain auto-joins a group /
agent-created room they post into.

Captain-reported bug: "some chats say Join, but they are chats I've been part of
already." Root cause: posting a Captain message never added ``captain`` to the
thread's participant set, so ``captainJoined`` (participants.includes('captain'))
stayed false and the sidebar kept showing the Join button on a room the Captain
was actively conversing in.

AD-968 adds the Captain to the participant set on a Captain post — but ONLY for
a GROUP (>= 2 crew) or an agent-created room (exactly where the Join button
shows). The 1:1 default thread keeps its single-participant invariant (the
task-promote assigned_to inference + auto-name preconditions rely on it).

BF-287 discipline: real ``ChatThreadStore`` / ``IntentBus`` / real-but-fake
registry + handlers (NOT MagicMock), driven through the real ``threads`` router
via ``dependency_overrides[get_runtime]``.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from probos.config import CommunicationsConfig, GroupChatConfig
from probos.mesh.intent import IntentBus
from probos.mesh.signal import SignalManager
from probos.threads import ChatThreadStore
from probos.types import IntentMessage, IntentResult


class _FakeAgent:
    def __init__(self, agent_type: str) -> None:
        self.agent_type = agent_type


class _FakeRegistry:
    def __init__(self, agents):
        self._a = agents

    def get(self, agent_id):
        return self._a.get(agent_id)


class _FakeCallsigns:
    def __init__(self, mapping):
        self._m = mapping

    def get_callsign(self, agent_type):
        return self._m.get(agent_type, "")


def _seq_clock():
    n = {"t": 0}

    def _c() -> float:
        n["t"] += 1
        return float(n["t"])

    return _c


def _make_handler(agent_id):
    async def _h(intent: IntentMessage) -> IntentResult:
        return IntentResult(
            intent_id=intent.id, agent_id=agent_id, success=True, result=f"reply::{agent_id}"
        )
    return _h


def _client(tmp_path, *, agents, callsigns=None):
    from probos.routers import threads as threads_router
    from probos.routers.deps import get_runtime

    store = ChatThreadStore(tmp_path / "threads.db", clock=_seq_clock())
    bus = IntentBus(SignalManager(reap_interval=1.0))
    registry = _FakeRegistry({aid: _FakeAgent(at) for aid, at in agents.items()})
    runtime = SimpleNamespace(
        chat_thread_store=store,
        intent_bus=bus,
        registry=registry,
        ontology=None,
        callsign_registry=_FakeCallsigns(callsigns or {}),
        project_store=None,
        config=SimpleNamespace(
            group_chat=GroupChatConfig(agent_reactivity_enabled=False, max_speakers_per_turn=1),
            communications=CommunicationsConfig(),
            attachments=None,
        ),
    )
    for aid in agents:
        bus.subscribe(aid, _make_handler(aid), intent_names=["direct_message"])
    app = FastAPI()
    app.include_router(threads_router.router)
    app.dependency_overrides[get_runtime] = lambda: runtime
    return TestClient(app), store


def _post_captain(c, tid, body="status team?"):
    return c.post(
        f"/api/threads/{tid}/messages",
        json={"author_id": "captain", "role": "captain", "body": body},
    )


# ---------------- group room: Captain auto-joins ----------------


def test_captain_joins_group_on_post(tmp_path):
    c, store = _client(
        tmp_path, agents={"scout1": "scout", "counselor1": "counselor"}
    )
    t = store.create_thread(title="room", participants=["scout1", "counselor1"])
    assert "captain" not in store.get_thread(t.id).participants
    r = _post_captain(c, t.id)
    assert r.status_code == 200
    assert "captain" in store.get_thread(t.id).participants


def test_captain_join_is_idempotent(tmp_path):
    c, store = _client(
        tmp_path, agents={"scout1": "scout", "counselor1": "counselor"}
    )
    t = store.create_thread(title="room", participants=["scout1", "counselor1"])
    _post_captain(c, t.id)
    _post_captain(c, t.id, body="again")
    participants = store.get_thread(t.id).participants
    assert participants.count("captain") == 1


# ---------------- agent-created room: Captain auto-joins ----------------


def test_captain_joins_agent_created_room_on_post(tmp_path):
    # A 1-crew agent-created room (e.g. a legacy room): not a group, but the
    # Join button shows for agent-created rooms, so the Captain must join.
    c, store = _client(tmp_path, agents={"scout1": "scout"})
    t = store.create_thread(
        title="Started by Scout",
        participants=["scout1"],
        metadata={"created_by_agent": "scout1"},
    )
    r = _post_captain(c, t.id)
    assert r.status_code == 200
    assert "captain" in store.get_thread(t.id).participants


# ---------------- 1:1 default thread: Captain does NOT join ----------------


def test_captain_does_not_join_one_on_one(tmp_path):
    # A single-crew, non-agent-created 1:1 keeps its single-participant
    # invariant (task-promote + auto-name depend on len(participants) == 1).
    c, store = _client(tmp_path, agents={"scout1": "scout"})
    t = store.create_thread(
        title="Scout", participants=["scout1"], metadata={"is_default": True}
    )
    r = _post_captain(c, t.id)
    assert r.status_code == 200
    parts = store.get_thread(t.id).participants
    assert parts == ["scout1"]
    assert "captain" not in parts


def test_one_on_one_stays_single_participant_for_promote_and_autoname(tmp_path):
    # Belt-and-braces: even after multiple Captain posts, the 1:1 stays at one
    # participant so the AD-815c/AD-794 single-participant paths are preserved.
    c, store = _client(tmp_path, agents={"scout1": "scout"})
    t = store.create_thread(title="Scout", participants=["scout1"])
    _post_captain(c, t.id)
    _post_captain(c, t.id, body="more")
    assert store.get_thread(t.id).participants == ["scout1"]
