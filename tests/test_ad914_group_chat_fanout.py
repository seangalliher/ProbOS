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

import json
from functools import partial
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
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


def _make_recording_handler(received: dict, agent_id: str, reply_text: str | None = None):
    async def _h(intent: IntentMessage) -> IntentResult:
        received[agent_id] = {
            "call_count": received.get(agent_id, {}).get("call_count", 0) + 1,
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
            result=f"reply::{agent_id}" if reply_text is None else reply_text,
        )

    return _h


def _make_raising_handler(agent_id: str):
    async def _h(intent: IntentMessage) -> IntentResult:
        raise RuntimeError(f"boom::{agent_id}")

    return _h


def _build_env(
    tmp_path, *, agents, callsigns=None, subscribe=None, raising=None,
    reply_texts=None, store=None,
):
    """agents: {agent_id: agent_type}. callsigns: {agent_type: callsign}.

    subscribe: agent_ids that get a recording handler (default: all).
    raising: agent_ids whose handler raises (delivery-failed path).
    Returns (store, runtime, received).
    """
    if store is None:
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
        handler = (
            _make_raising_handler(aid) if aid in raise_ids
            else _make_recording_handler(received, aid, (reply_texts or {}).get(aid))
        )
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
    # BF-636: counselor1 (no subscriber -> empty result) is THINNED like a decline,
    # not shown as a "(no response)" placeholder; scout1 is unaffected.
    assert "counselor1" not in by_id
    bodies = {m.body for m in store.list_messages(t.id, limit=1000) if m.role == "agent"}
    assert "reply::scout1" in bodies
    assert "(no response)" not in bodies


async def test_one_agent_handler_raise_is_thinned(tmp_path):
    store, runtime, _ = _build_env(
        tmp_path,
        agents={"scout1": "scout", "counselor1": "counselor"},
        raising=["counselor1"],  # counselor1's handler raises -> thinned (BF-636)
    )
    t = store.create_thread(title="room", participants=["scout1", "counselor1"])
    cap = store.append_message(t.id, author_id="captain", role="captain", body="trigger")
    replies = await group_chat_fanout(runtime, t.id, captain_body="trigger", captain_msg=cap)
    by_id = {r["agent_id"]: r["text"] for r in replies}
    assert by_id["scout1"] == "reply::scout1"
    # BF-636: a raising handler (delivery failure) is THINNED like a decline, not
    # shown as a "(delivery failed)" placeholder; the other recipient is unaffected.
    assert "counselor1" not in by_id
    # Neither the thinned reply nor a placeholder is persisted; scout1's is.
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
    assert isinstance(runtime.intent_bus, IntentBus)
    assert sorted(crew_agent_participants(runtime, t.participants)) == [
        "counselor1", "scout1",
    ]
    assert store.list_messages(t.id, limit=1000) == []
    client = _rest_client(runtime)
    r = client.post(
        f"/api/threads/{t.id}/messages",
        json={"author_id": "captain", "role": "captain", "body": "all hands"},
    )
    assert r.status_code == 200
    assert set(received.keys()) == {"scout1", "counselor1"}
    for agent_id in ("scout1", "counselor1"):
        assert received[agent_id]["call_count"] == 1
        assert received[agent_id]["text"] == "all hands"
        assert received[agent_id]["from"] == "hxi_profile"
        assert received[agent_id]["thread_id"] == t.id

    persisted = store.list_messages(t.id, limit=1000)
    assert len(persisted) == 3
    assert len({message.id for message in persisted}) == 3
    captain_rows = [message for message in persisted if message.role == "captain"]
    agent_rows = [message for message in persisted if message.role == "agent"]
    assert len(captain_rows) == 1
    assert captain_rows[0].author_id == "captain"
    assert captain_rows[0].body == "all hands"
    assert len(agent_rows) == 2
    assert {message.author_id for message in agent_rows} == {"scout1", "counselor1"}
    for message in agent_rows:
        assert message.body == f"reply::{message.author_id}"
        assert message.metadata["fanout"] == "ad914"
        assert message.metadata["intent_id"]

    body = r.json()
    assert "per_agent_replies" in body
    assert {
        key: value for key, value in body.items() if key != "per_agent_replies"
    } == captain_rows[0].to_dict()
    replies = body["per_agent_replies"]
    assert len(replies) == 2
    assert {x["agent_id"] for x in replies} == {"scout1", "counselor1"}
    assert {x["text"] for x in replies} == {"reply::scout1", "reply::counselor1"}
    persisted_by_author = {message.author_id: message for message in agent_rows}
    for reply in replies:
        assert reply["message"] == persisted_by_author[reply["agent_id"]].to_dict()


@pytest.mark.parametrize(
    "case", ["plain", "normalized", "same_text", "none", "raise", "empty", "declined"],
)
def test_fanout_receipt_boundaries_preserve_successful_peer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture, case: str,
) -> None:
    from probos.cognitive.dm.bypass_egress import UNRENDERABLE_NOTE

    reply_texts = {
        "scout1": "reply::scout1",
        "counselor1": "reply::counselor1",
    }
    if case == "normalized":
        reply_texts["scout1"] = "Status [A2UI]{}[/A2UI]"
    elif case == "same_text":
        reply_texts = dict.fromkeys(reply_texts, "Ready for the next task.")
    elif case in {"empty", "declined"}:
        reply_texts["scout1"] = "" if case == "empty" else "[NO_RESPONSE]"
    store, runtime, received = _build_env(
        tmp_path,
        agents={"scout1": "scout", "counselor1": "counselor"},
        callsigns={"scout": "Scout", "counselor": "Troi"},
        reply_texts=reply_texts,
    )
    thread = store.create_thread(title="room", participants=["scout1", "counselor1"])
    assert isinstance(runtime.intent_bus, IntentBus)
    assert set(crew_agent_participants(runtime, thread.participants)) == set(reply_texts)
    assert store.list_messages(thread.id, limit=1000) == []
    committed = []
    store.set_message_committed_callback(committed.append)
    append_message = store.append_message
    attempted: list[str] = []

    def append_with_failure(thread_id: str, **kwargs: Any) -> Any:
        attempted.append(kwargs["author_id"])
        if kwargs["author_id"] == "scout1" and case in {"none", "raise"}:
            if case == "raise":
                raise RuntimeError("injected persistence failure")
            return None
        return append_message(thread_id, **kwargs)

    monkeypatch.setattr(store, "append_message", append_with_failure)
    send_count = 2 if case == "same_text" else 1
    responses: list[dict[str, Any]] = []
    with _rest_client(runtime) as client:
        for send_index in range(send_count):
            response = client.post(
                f"/api/threads/{thread.id}/messages",
                json={
                    "author_id": "captain", "role": "captain", "body": "all hands",
                    "metadata": {"client_message_id": f"send-{send_index}"},
                },
            )
            assert response.status_code == 200
            responses.append(response.json())
        history = client.get(f"/api/threads/{thread.id}/messages")
        assert history.status_code == 200

    assert set(received) == set(reply_texts)
    assert {agent_id: entry["call_count"] for agent_id, entry in received.items()} == {
        "scout1": send_count, "counselor1": send_count,
    }
    persisted = store.list_messages(thread.id, limit=1000)
    expected_agents = {"counselor1"} if case in {"none", "raise", "empty", "declined"} else set(reply_texts)
    assert len(persisted) == send_count * (1 + len(expected_agents))
    assert len({row.id for row in persisted}) == len(persisted)
    assert len([row for row in persisted if row.role == "captain"]) == send_count
    assert {row.author_id for row in persisted if row.role == "agent"} == expected_agents
    assert [row.to_dict() for row in committed] == [row.to_dict() for row in persisted]
    assert history.json() == {
        "thread_id": thread.id, "messages": [row.to_dict() for row in persisted],
    }
    persisted_by_id = {row.id: row.to_dict() for row in persisted}
    for body in responses:
        assert {key: value for key, value in body.items() if key != "per_agent_replies"} == persisted_by_id[body["id"]]
        replies = {reply["agent_id"]: reply for reply in body["per_agent_replies"]}
        expected_replies = {"counselor1"} if case in {"empty", "declined"} else set(reply_texts)
        assert set(replies) == expected_replies
        for agent_id, reply in replies.items():
            assert reply["callsign"] == {"scout1": "Scout", "counselor1": "Troi"}[agent_id]
            if agent_id == "scout1" and case in {"none", "raise"}:
                assert reply["message"] is None
                assert reply["text"] == reply_texts[agent_id]
                continue
            receipt = reply["message"]
            assert receipt == persisted_by_id[receipt["id"]]
            assert receipt["author_id"] == agent_id
            assert receipt["thread_id"] == thread.id
            assert receipt["role"] == "agent"
            if agent_id == "scout1" and case == "normalized":
                assert reply["text"] != receipt["body"]
                assert reply["text"] == reply_texts[agent_id]
                assert receipt["body"] == f"Status {UNRENDERABLE_NOTE}"
            else:
                assert reply["text"] == receipt["body"] == reply_texts[agent_id]
    assert attempted.count("captain") == send_count
    assert attempted.count("counselor1") == send_count
    assert attempted.count("scout1") == (0 if case in {"empty", "declined"} else send_count)
    if case in {"none", "raise"}:
        assert "returning transient text without a canonical message receipt" in caplog.text
        assert reply_texts["scout1"] not in caplog.text
    if case == "same_text":
        for agent_id in reply_texts:
            rows = [row for row in persisted if row.author_id == agent_id]
            assert len(rows) == 2
            assert rows[0].body == rows[1].body == reply_texts[agent_id]
            assert rows[0].id != rows[1].id
            assert rows[0].created_at < rows[1].created_at


def test_group_reply_identity_fixture_matches_real_producers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    import probos.runtime as runtime_module
    import probos.threads as threads_module
    from probos.config import SystemConfig
    from probos.routers import thread_fanout

    message_ids = iter(["identity-room", "identity-captain", "identity-reply-1", "identity-reply-2"])
    with monkeypatch.context() as constructor_patch:
        constructor_patch.setattr(
            threads_module, "ChatThreadStore",
            partial(ChatThreadStore, clock=_seq_clock(), id_factory=lambda: next(message_ids)),
        )
        event_runtime = runtime_module.ProbOSRuntime(
            config=SystemConfig(), data_dir=tmp_path,
        )
    monkeypatch.setattr(
        runtime_module, "time",
        SimpleNamespace(**{**vars(runtime_module.time), "time": lambda: 1000.0}),
    )

    def deterministic_intent(**kwargs: Any) -> IntentMessage:
        return IntentMessage(id=f"identity-intent-{kwargs['target_agent_id']}", **kwargs)

    monkeypatch.setattr(thread_fanout, "IntentMessage", deterministic_intent)
    store, runtime, received = _build_env(
        tmp_path,
        agents={"scout1": "scout", "counselor1": "counselor"},
        callsigns={"scout": "Scout", "counselor": "Troi"},
        store=event_runtime.chat_thread_store,
    )
    events: list[dict[str, Any]] = []

    def capture_committed_event(event: dict[str, Any]) -> None:
        if event["type"] == "chat_thread_message_appended":
            events.append(event)

    event_runtime.add_event_listener(capture_committed_event)
    thread = store.create_thread(title="Identity room", participants=["scout1", "counselor1"])
    assert store is event_runtime.chat_thread_store
    assert isinstance(store, ChatThreadStore)
    assert isinstance(runtime.intent_bus, IntentBus)
    assert sorted(crew_agent_participants(runtime, thread.participants)) == ["counselor1", "scout1"]
    assert store.list_messages(thread.id, limit=1000) == []
    assert events == []
    request = {
        "author_id": "captain", "role": "captain", "body": "all hands",
        "metadata": {"client_message_id": "identity-send-1"},
    }
    with _rest_client(runtime) as client:
        response = client.post(f"/api/threads/{thread.id}/messages", json=request)
        assert response.status_code == 200
        history = client.get(f"/api/threads/{thread.id}/messages")
        assert history.status_code == 200

    assert set(received) == {"scout1", "counselor1"}
    for agent_id, entry in received.items():
        assert entry["call_count"] == 1
        assert entry["text"] == request["body"]
        assert entry["from"] == "hxi_profile"
        assert entry["thread_id"] == thread.id
        assert runtime.registry.get(agent_id) is not None
    rows = store.list_messages(thread.id, limit=1000)
    assert len(rows) == 3
    assert len({row.id for row in rows}) == 3
    assert [row.author_id for row in rows if row.role == "captain"] == ["captain"]
    assert {row.author_id for row in rows if row.role == "agent"} == set(received)
    assert history.json() == {"thread_id": thread.id, "messages": [row.to_dict() for row in rows]}
    body = response.json()
    assert {key: value for key, value in body.items() if key != "per_agent_replies"} == rows[0].to_dict()
    assert len(body["per_agent_replies"]) == 2
    rows_by_author = {row.author_id: row for row in rows}
    for reply in body["per_agent_replies"]:
        assert reply["message"] == rows_by_author[reply["agent_id"]].to_dict()
        assert reply["text"] == f"reply::{reply['agent_id']}"
    assert len(events) == 3
    for event, row in zip(events, rows):
        assert event["data"] == {
            "thread_id": row.thread_id, "message_id": row.id,
            "author_id": row.author_id, "role": row.role, "created_at": row.created_at,
        }
        assert event["timestamp"] == 1000.0
    actual = {
        "thread": thread.to_dict(), "request": request,
        "response": body, "history": history.json(), "events": events,
    }
    fixture_path = Path(__file__).resolve().parents[1] / "ui/e2e/fixtures/group-reply-identity.json"
    if not fixture_path.is_file():
        pytest.fail(
            "Producer assertions passed; Worker must bank this actual fixture payload:\n"
            + json.dumps(actual, indent=2, sort_keys=True),
            pytrace=False,
        )
    assert json.loads(fixture_path.read_text(encoding="utf-8")) == actual


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
