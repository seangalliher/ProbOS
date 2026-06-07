"""AD-914: group-chat fan-out + cross-agent visibility tests.

BF-287 discipline: real ``ChatThreadStore`` on ``tmp_path``, real
``IntentBus(SignalManager(reap_interval=1.0))``, real-but-fake registry /
callsign / handler stubs (NOT ``MagicMock``) at the substrate/bus boundary.
A subscribed handler records the ``session_history`` it received so the
"see each other" wire can be asserted directly. The REST cases mount the
real ``threads`` router with a ``SimpleNamespace`` runtime via
``dependency_overrides[get_runtime]`` (mirroring AD-913 / AD-791).
"""
from __future__ import annotations

from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from probos.mesh.intent import IntentBus
from probos.mesh.signal import SignalManager
from probos.routers.thread_fanout import (
    _build_session_history,
    crew_agent_participants,
    group_chat_fanout,
)
from probos.threads import ChatThreadStore
from probos.types import IntentMessage, IntentResult


# ---------------- BF-287 real-but-fake substrate stubs ----------------


class _FakeAgent:
    def __init__(self, agent_type: str) -> None:
        self.agent_type = agent_type  # real attr; is_crew_agent reads .agent_type


class _FakeRegistry:
    def __init__(self, agents: dict[str, _FakeAgent]) -> None:
        self._a = agents

    def get(self, agent_id: str):
        return self._a.get(agent_id)


class _FakeCallsigns:
    def __init__(self, mapping: dict[str, str]) -> None:
        self._m = mapping  # agent_type -> callsign

    def get_callsign(self, agent_type: str) -> str:
        return self._m.get(agent_type, "")


def _seq_clock():
    """Deterministic monotonic clock so created_at ordering (and the
    ``before=`` history filter) is exact regardless of wall-clock speed."""
    n = {"t": 0}

    def _c() -> float:
        n["t"] += 1
        return float(n["t"])

    return _c


def _make_recording_handler(received: dict, agent_id: str):
    async def _h(intent: IntentMessage) -> IntentResult:
        received[agent_id] = {
            "text": intent.params.get("text"),
            "history": intent.params.get("session_history"),
            "session": intent.params.get("session"),
            "from": intent.params.get("from"),
            "thread_id": intent.thread_id,
        }
        return IntentResult(
            intent_id=intent.id,
            agent_id=agent_id,
            success=True,
            result=f"reply::{agent_id}",
        )

    return _h


def _make_raising_handler(agent_id: str):
    async def _h(intent: IntentMessage) -> IntentResult:
        raise RuntimeError(f"boom::{agent_id}")

    return _h


def _build_env(tmp_path, *, agents, callsigns=None, subscribe=None, raising=None):
    """agents: {agent_id: agent_type}. callsigns: {agent_type: callsign}.

    subscribe: agent_ids that get a recording handler (default: all).
    raising: agent_ids whose handler raises (delivery-failed path).
    Returns (store, runtime, received).
    """
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
    )
    received: dict[str, dict] = {}
    sub_ids = list(agents.keys()) if subscribe is None else list(subscribe)
    raise_ids = set(raising or ())
    for aid in sub_ids:
        handler = _make_raising_handler(aid) if aid in raise_ids else _make_recording_handler(received, aid)
        bus.subscribe(aid, handler, intent_names=["direct_message"])
    return store, runtime, received


def _rest_client(runtime) -> TestClient:
    from probos.routers import threads as threads_router
    from probos.routers.deps import get_runtime

    app = FastAPI()
    app.include_router(threads_router.router)
    app.dependency_overrides[get_runtime] = lambda: runtime
    return TestClient(app)


# ---------------- fan-out behavior (direct helper) ----------------


async def test_two_agent_thread_fans_out_to_all(tmp_path):
    store, runtime, received = _build_env(
        tmp_path,
        agents={"scout1": "scout", "counselor1": "counselor"},
        callsigns={"scout": "Scout", "counselor": "Troi"},
    )
    t = store.create_thread(title="room", participants=["scout1", "counselor1"])
    cap = store.append_message(t.id, author_id="captain", role="captain", body="status?")
    replies = await group_chat_fanout(runtime, t.id, captain_body="status?", captain_msg=cap)
    assert set(received.keys()) == {"scout1", "counselor1"}
    assert len(replies) == 2
    assert {r["agent_id"] for r in replies} == {"scout1", "counselor1"}
    # IntentMessage shape: real-DM marker + AD-791a thread provenance.
    for aid in ("scout1", "counselor1"):
        assert received[aid]["from"] == "hxi_profile"
        assert received[aid]["thread_id"] == t.id


async def test_replies_persisted_as_agent_messages(tmp_path):
    store, runtime, _ = _build_env(
        tmp_path, agents={"scout1": "scout", "counselor1": "counselor"}
    )
    t = store.create_thread(title="room", participants=["scout1", "counselor1"])
    cap = store.append_message(t.id, author_id="captain", role="captain", body="report")
    await group_chat_fanout(runtime, t.id, captain_body="report", captain_msg=cap)
    agent_rows = [m for m in store.list_messages(t.id, limit=1000) if m.role == "agent"]
    assert len(agent_rows) == 2
    assert {m.author_id for m in agent_rows} == {"scout1", "counselor1"}
    assert {m.body for m in agent_rows} == {"reply::scout1", "reply::counselor1"}


async def test_each_agent_prompt_contains_other_participants_turns(tmp_path):
    store, runtime, received = _build_env(
        tmp_path,
        agents={"scout1": "scout", "counselor1": "counselor"},
        callsigns={"scout": "Scout", "counselor": "Troi"},
    )
    t = store.create_thread(title="room", participants=["scout1", "counselor1"])
    # Seed a prior reply from scout1; both agents should see it this turn.
    store.append_message(t.id, author_id="scout1", role="agent", body="scout's earlier note")
    cap = store.append_message(t.id, author_id="captain", role="captain", body="continue")
    await group_chat_fanout(runtime, t.id, captain_body="continue", captain_msg=cap)
    for aid in ("scout1", "counselor1"):
        hist = received[aid]["history"]
        assert any(e["text"] == "scout's earlier note" for e in hist)


async def test_agent_history_labelled_with_callsign(tmp_path):
    store, runtime, received = _build_env(
        tmp_path,
        agents={"scout1": "scout", "counselor1": "counselor"},
        callsigns={"scout": "Scout", "counselor": "Troi"},
    )
    t = store.create_thread(title="room", participants=["scout1", "counselor1"])
    store.append_message(t.id, author_id="scout1", role="agent", body="scouting ahead")
    cap = store.append_message(t.id, author_id="captain", role="captain", body="go")
    await group_chat_fanout(runtime, t.id, captain_body="go", captain_msg=cap)
    hist = received["counselor1"]["history"]
    entry = next(e for e in hist if e["text"] == "scouting ahead")
    assert entry["role"] == "Scout"  # callsign, not the literal "agent"


async def test_captain_turn_passed_as_text_not_history(tmp_path):
    store, runtime, received = _build_env(
        tmp_path, agents={"scout1": "scout", "counselor1": "counselor"}
    )
    t = store.create_thread(title="room", participants=["scout1", "counselor1"])
    cap = store.append_message(t.id, author_id="captain", role="captain", body="the captain turn")
    await group_chat_fanout(runtime, t.id, captain_body="the captain turn", captain_msg=cap)
    for aid in ("scout1", "counselor1"):
        assert received[aid]["text"] == "the captain turn"
        # The just-appended Captain msg is excluded from history via before=.
        assert all(e["text"] != "the captain turn" for e in received[aid]["history"])


async def test_agent_history_callsign_fallback_to_agent(tmp_path):
    # Tier-2 degrade: get_callsign returns "" -> label falls back to "agent".
    store, runtime, received = _build_env(
        tmp_path,
        agents={"scout1": "scout", "counselor1": "counselor"},
        callsigns={},
    )
    t = store.create_thread(title="room", participants=["scout1", "counselor1"])
    store.append_message(t.id, author_id="scout1", role="agent", body="unlabelled note")
    cap = store.append_message(t.id, author_id="captain", role="captain", body="go")
    await group_chat_fanout(runtime, t.id, captain_body="go", captain_msg=cap)
    hist = received["counselor1"]["history"]
    entry = next(e for e in hist if e["text"] == "unlabelled note")
    assert entry["role"] == "agent"


async def test_reply_persistence_metadata_tags_fanout(tmp_path):
    store, runtime, _ = _build_env(
        tmp_path, agents={"scout1": "scout", "counselor1": "counselor"}
    )
    t = store.create_thread(title="room", participants=["scout1", "counselor1"])
    cap = store.append_message(t.id, author_id="captain", role="captain", body="tag check")
    await group_chat_fanout(runtime, t.id, captain_body="tag check", captain_msg=cap)
    agent_rows = [m for m in store.list_messages(t.id, limit=1000) if m.role == "agent"]
    assert len(agent_rows) == 2
    for m in agent_rows:
        assert m.metadata.get("fanout") == "ad914"
        assert m.metadata.get("intent_id")


async def test_one_agent_no_subscriber_does_not_block_other(tmp_path):
    store, runtime, _ = _build_env(
        tmp_path,
        agents={"scout1": "scout", "counselor1": "counselor"},
        subscribe=["scout1"],  # counselor1 has no bus handler -> send() returns None
    )
    t = store.create_thread(title="room", participants=["scout1", "counselor1"])
    cap = store.append_message(t.id, author_id="captain", role="captain", body="who's there")
    replies = await group_chat_fanout(runtime, t.id, captain_body="who's there", captain_msg=cap)
    by_id = {r["agent_id"]: r["text"] for r in replies}
    assert by_id["scout1"] == "reply::scout1"
    assert by_id["counselor1"] == "(no response)"
    bodies = {m.body for m in store.list_messages(t.id, limit=1000) if m.role == "agent"}
    assert "reply::scout1" in bodies


async def test_one_agent_handler_raise_returns_delivery_failed(tmp_path):
    store, runtime, _ = _build_env(
        tmp_path,
        agents={"scout1": "scout", "counselor1": "counselor"},
        raising=["counselor1"],  # counselor1's handler raises -> "(delivery failed)"
    )
    t = store.create_thread(title="room", participants=["scout1", "counselor1"])
    cap = store.append_message(t.id, author_id="captain", role="captain", body="trigger")
    replies = await group_chat_fanout(runtime, t.id, captain_body="trigger", captain_msg=cap)
    by_id = {r["agent_id"]: r["text"] for r in replies}
    assert by_id["scout1"] == "reply::scout1"
    assert by_id["counselor1"] == "(delivery failed)"
    # The delivery-failed reply is NOT persisted; scout1's is.
    agent_rows = [m for m in store.list_messages(t.id, limit=1000) if m.role == "agent"]
    assert {m.body for m in agent_rows} == {"reply::scout1"}


# ---------------- participant filtering ----------------


async def test_non_crew_participant_excluded(tmp_path):
    store, runtime, received = _build_env(
        tmp_path, agents={"scout1": "scout", "yeo1": "yeoman"}
    )
    # "captain" sentinel + an unknown id both resolve to None in the registry.
    parts = ["scout1", "yeo1", "captain", "ghost"]
    assert crew_agent_participants(runtime, parts) == ["scout1"]
    # Paired with one crew agent -> count 1 -> endpoint does not fan out.
    t = store.create_thread(title="mixed", participants=parts)
    client = _rest_client(runtime)
    r = client.post(
        f"/api/threads/{t.id}/messages",
        json={"author_id": "captain", "role": "captain", "body": "hello"},
    )
    assert r.status_code == 200
    assert "per_agent_replies" not in r.json()
    assert received == {}


async def test_single_agent_thread_does_not_fan_out(tmp_path):
    store, runtime, received = _build_env(tmp_path, agents={"scout1": "scout"})
    t = store.create_thread(title="1:1", participants=["scout1"])
    assert len(crew_agent_participants(runtime, t.participants)) == 1
    client = _rest_client(runtime)
    r = client.post(
        f"/api/threads/{t.id}/messages",
        json={"author_id": "captain", "role": "captain", "body": "hi"},
    )
    assert r.status_code == 200
    assert "per_agent_replies" not in r.json()
    assert received == {}
    agent_rows = [m for m in store.list_messages(t.id, limit=1000) if m.role == "agent"]
    assert agent_rows == []


# ---------------- REST seam (response shape + back-compat) ----------------


async def test_non_captain_author_does_not_trigger_fanout(tmp_path):
    store, runtime, received = _build_env(
        tmp_path, agents={"scout1": "scout", "counselor1": "counselor"}
    )
    t = store.create_thread(title="room", participants=["scout1", "counselor1"])
    client = _rest_client(runtime)
    r_agent = client.post(
        f"/api/threads/{t.id}/messages",
        json={"author_id": "scout1", "role": "agent", "body": "agent says hi"},
    )
    r_system = client.post(
        f"/api/threads/{t.id}/messages",
        json={"author_id": "sys", "role": "system", "body": "system note"},
    )
    assert r_agent.status_code == 200 and "per_agent_replies" not in r_agent.json()
    assert r_system.status_code == 200 and "per_agent_replies" not in r_system.json()
    assert received == {}
    # Only the explicitly-appended agent message exists — no fan-out replies.
    agent_rows = [m for m in store.list_messages(t.id, limit=1000) if m.role == "agent"]
    assert {m.body for m in agent_rows} == {"agent says hi"}


async def test_fanout_response_includes_per_agent_replies(tmp_path):
    store, runtime, received = _build_env(
        tmp_path,
        agents={"scout1": "scout", "counselor1": "counselor"},
        callsigns={"scout": "Scout", "counselor": "Troi"},
    )
    t = store.create_thread(title="room", participants=["scout1", "counselor1"])
    client = _rest_client(runtime)
    r = client.post(
        f"/api/threads/{t.id}/messages",
        json={"author_id": "captain", "role": "captain", "body": "all hands"},
    )
    assert r.status_code == 200
    body = r.json()
    assert "per_agent_replies" in body
    replies = body["per_agent_replies"]
    assert {x["agent_id"] for x in replies} == {"scout1", "counselor1"}
    assert {x["text"] for x in replies} == {"reply::scout1", "reply::counselor1"}
    assert set(received.keys()) == {"scout1", "counselor1"}


async def test_messages_endpoint_unchanged_for_non_group(tmp_path):
    store, runtime, _ = _build_env(tmp_path, agents={"scout1": "scout"})
    t = store.create_thread(title="1:1", participants=["scout1"])
    client = _rest_client(runtime)
    r = client.post(
        f"/api/threads/{t.id}/messages",
        json={"author_id": "captain", "role": "captain", "body": "solo"},
    )
    assert r.status_code == 200
    body = r.json()
    assert "per_agent_replies" not in body
    assert body["role"] == "captain"
    assert body["body"] == "solo"
    assert "id" in body and "created_at" in body


# ---------------- history builder (Tier-2 boundary) ----------------


async def test_build_session_history_tail_slices_most_recent(tmp_path):
    # ASC + LIMIT returns the OLDEST N — the builder must tail-slice to the
    # most-recent window. Seed 25 prior agent turns, assert only the last 20
    # survive and they are the most-recent ones (not the oldest).
    store, runtime, _ = _build_env(tmp_path, agents={"scout1": "scout"})
    t = store.create_thread(title="room", participants=["scout1"])
    for i in range(25):
        store.append_message(t.id, author_id="scout1", role="agent", body=f"turn-{i}")
    cap = store.append_message(t.id, author_id="captain", role="captain", body="now")
    history = _build_session_history(runtime, store, t.id, cap.created_at)
    assert len(history) == 20
    texts = [e["text"] for e in history]
    assert texts[0] == "turn-5" and texts[-1] == "turn-24"
    assert "turn-0" not in texts  # oldest dropped, not the recent ones
