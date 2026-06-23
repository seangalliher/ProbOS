"""BF-636 (Natural Conversation epic #882): a transient empty LLM result is
thinned like a decline, never persisted as a fake "(no response)" reply.

The Captain's live 5+ crew room during an LLM-proxy restart: several agents
showed "(no response)" entries. Root cause: ``thread_fanout._send_one`` converted
an EMPTY intent result (proxy timeout / echo / overload) into the literal string
``"(no response)"`` — which is neither ``[NO_RESPONSE]`` nor empty-after-strip, so
it slipped PAST the ``_declined`` thinning gate and got persisted + shown as if
the agent had posted it.

BF-636: an empty/None result (or a delivery exception) now yields ``text=""`` so
the existing ``_declined`` check thins it exactly like a ``[NO_RESPONSE]`` decline;
and an explicitly ADDRESSED (hard-included) agent gets ONE retry before being
thinned (a transient failure on the peer a speaker named auto-recovers, without
doubling proxy load for the whole room).

BF-287 discipline: real ``ChatThreadStore`` on ``tmp_path``, real
``IntentBus(SignalManager(...))``, real-but-fake registry/agents whose subscribed
``direct_message`` handlers return SCRIPTED results (NOT ``MagicMock``), a real
``GroupChatConfig``. Mirrors ``tests/test_ad935_group_reactivity.py``.
"""
from __future__ import annotations

from types import SimpleNamespace

from probos.config import GroupChatConfig
from probos.mesh.intent import IntentBus
from probos.mesh.signal import SignalManager
from probos.routers.thread_fanout import group_chat_fanout
from probos.threads import ChatThreadStore
from probos.types import IntentMessage, IntentResult


# ---------------- BF-287 real-but-fake substrate ----------------


class _FakeAgent:
    def __init__(self, agent_type: str) -> None:
        self.agent_type = agent_type


class _FakeRegistry:
    def __init__(self, agents: dict[str, _FakeAgent]) -> None:
        self._a = agents

    def get(self, agent_id: str):
        return self._a.get(agent_id)


class _FakeCallsigns:
    def __init__(self, mapping: dict[str, str]) -> None:
        self._m = mapping

    def get_callsign(self, agent_type: str) -> str:
        return self._m.get(agent_type, "")


def _seq_clock():
    n = {"t": 0}

    def _c() -> float:
        n["t"] += 1
        return float(n["t"])

    return _c


_CALLSIGNS = {
    "scout": "Scout",
    "diagnostician": "Bones",
    "counselor": "Ops",
    "security_officer": "Eng",
}


def _scripted_handler(agent_id: str, scripted: list[str], dispatched: list[dict]):
    """Returns SCRIPTED results keyed by per-agent call index. An empty string in
    the script yields an empty ``IntentResult.result`` (the transient-failure
    shape). Records every dispatch so tests can count retries."""
    state = {"n": 0}

    async def _h(intent: IntentMessage) -> IntentResult:
        n = state["n"]
        state["n"] += 1
        text = scripted[n] if n < len(scripted) else scripted[-1]
        dispatched.append({"agent_id": agent_id, "call": n})
        return IntentResult(
            intent_id=intent.id, agent_id=agent_id, success=True, result=text,
        )

    return _h


def _raising_handler(agent_id: str, dispatched: list[dict]):
    async def _h(intent: IntentMessage) -> IntentResult:
        dispatched.append({"agent_id": agent_id, "call": len(dispatched)})
        raise RuntimeError("simulated delivery failure")

    return _h


def _build_env(tmp_path, *, agents, handlers, gc):
    """agents: {agent_id: agent_type}. handlers: {agent_id: subscribed handler}."""
    store = ChatThreadStore(tmp_path / "threads.db", clock=_seq_clock())
    bus = IntentBus(SignalManager(reap_interval=1.0))
    registry = _FakeRegistry({aid: _FakeAgent(at) for aid, at in agents.items()})
    runtime = SimpleNamespace(
        chat_thread_store=store,
        intent_bus=bus,
        registry=registry,
        ontology=None,
        callsign_registry=_FakeCallsigns(_CALLSIGNS),
        project_store=None,
        config=SimpleNamespace(group_chat=gc, attachments=None),
    )
    for aid, handler in handlers.items():
        bus.subscribe(aid, handler, intent_names=["direct_message"])
    return store, runtime


def _agent_bodies(store, thread_id):
    return [m.body for m in store.list_messages(thread_id, limit=1000) if m.role == "agent"]


# ---------------- 1. empty result is thinned (the headline fix) ----------------


async def test_empty_result_is_thinned_not_shown(tmp_path):
    dispatched: list[dict] = []
    store, runtime = _build_env(
        tmp_path,
        agents={"scout1": "scout", "bones1": "diagnostician"},
        handlers={
            "scout1": _scripted_handler("scout1", ["a real reply"], dispatched),
            "bones1": _scripted_handler("bones1", [""], dispatched),  # transient failure
        },
        gc=GroupChatConfig(agent_reactivity_enabled=False),
    )
    t = store.create_thread(title="room", participants=["scout1", "bones1"])
    cap = store.append_message(t.id, author_id="captain", role="captain", body="status?")
    replies = await group_chat_fanout(runtime, t.id, captain_body="status?", captain_msg=cap)
    # bones1's empty result is thinned: only scout1 appears.
    assert {r["agent_id"] for r in replies} == {"scout1"}
    # No fake "(no response)" string is ever shown or persisted.
    assert all(r["text"] != "(no response)" for r in replies)
    assert "(no response)" not in _agent_bodies(store, t.id)
    # bones1 was NOT persisted at all (a decline says nothing).
    assert "bones1" not in {r["agent_id"] for r in replies}


async def test_unaddressed_empty_is_not_retried(tmp_path):
    # A round-0 (un-addressed) agent that returns empty is dispatched EXACTLY
    # once — no retry-amplification when the whole room is failing.
    dispatched: list[dict] = []
    store, runtime = _build_env(
        tmp_path,
        agents={"scout1": "scout", "bones1": "diagnostician"},
        handlers={
            "scout1": _scripted_handler("scout1", ["a real reply"], dispatched),
            "bones1": _scripted_handler("bones1", ["", "would-be retry reply"], dispatched),
        },
        gc=GroupChatConfig(agent_reactivity_enabled=False),
    )
    t = store.create_thread(title="room", participants=["scout1", "bones1"])
    cap = store.append_message(t.id, author_id="captain", role="captain", body="status?")
    replies = await group_chat_fanout(runtime, t.id, captain_body="status?", captain_msg=cap)
    assert {r["agent_id"] for r in replies} == {"scout1"}
    bones_calls = sum(1 for d in dispatched if d["agent_id"] == "bones1")
    assert bones_calls == 1  # NO retry for an un-addressed agent
    # The would-be retry reply never surfaced.
    assert "would-be retry reply" not in _agent_bodies(store, t.id)


# ---------------- 2. delivery exception is thinned (not "(delivery failed)") ----------------


async def test_delivery_exception_is_thinned(tmp_path):
    dispatched: list[dict] = []
    store, runtime = _build_env(
        tmp_path,
        agents={"scout1": "scout", "bones1": "diagnostician"},
        handlers={
            "scout1": _scripted_handler("scout1", ["a real reply"], dispatched),
            "bones1": _raising_handler("bones1", dispatched),
        },
        gc=GroupChatConfig(agent_reactivity_enabled=False),
    )
    t = store.create_thread(title="room", participants=["scout1", "bones1"])
    cap = store.append_message(t.id, author_id="captain", role="captain", body="status?")
    replies = await group_chat_fanout(runtime, t.id, captain_body="status?", captain_msg=cap)
    assert {r["agent_id"] for r in replies} == {"scout1"}
    assert all(r["text"] != "(delivery failed)" for r in replies)
    assert "(delivery failed)" not in _agent_bodies(store, t.id)


# ---------------- 3. addressed agent retries once and recovers ----------------


async def test_addressed_agent_retries_once_and_recovers(tmp_path):
    # Scout speaks round 0 (max_speakers=1) and hands off to @Bones. In round 1
    # Bones is ADDRESSED (hard-included). Bones' first call returns empty (a
    # transient proxy failure); BF-636 retries ONCE and the real reply surfaces.
    dispatched: list[dict] = []
    store, runtime = _build_env(
        tmp_path,
        agents={"scout1": "scout", "bones1": "diagnostician"},
        handlers={
            "scout1": _scripted_handler("scout1", ["@Bones your read?"], dispatched),
            "bones1": _scripted_handler("bones1", ["", "I concur, proceed."], dispatched),
        },
        gc=GroupChatConfig(
            agent_reactivity_enabled=True,
            agent_next_speaker_selection_enabled=True,
            max_agent_rounds=1,
            max_speakers_per_turn=1,
        ),
    )
    t = store.create_thread(title="room", participants=["scout1", "bones1"])
    cap = store.append_message(t.id, author_id="captain", role="captain", body="thoughts team?")
    replies = await group_chat_fanout(
        runtime, t.id, captain_body="thoughts team?", captain_msg=cap
    )
    # The addressed agent recovered on retry — its real reply is shown.
    assert [r["agent_id"] for r in replies] == ["scout1", "bones1"]
    assert replies[1]["text"] == "I concur, proceed."
    # Proof the retry fired: bones1 was dispatched TWICE (empty, then real).
    bones_calls = sum(1 for d in dispatched if d["agent_id"] == "bones1")
    assert bones_calls == 2
    assert "I concur, proceed." in _agent_bodies(store, t.id)
    assert "(no response)" not in _agent_bodies(store, t.id)


async def test_addressed_agent_still_empty_after_retry_is_thinned(tmp_path):
    # Addressed, but BOTH attempts come back empty -> thinned (the agent simply
    # does not appear; no fake "(no response)" persisted), retry bounded to one.
    dispatched: list[dict] = []
    store, runtime = _build_env(
        tmp_path,
        agents={"scout1": "scout", "bones1": "diagnostician"},
        handlers={
            "scout1": _scripted_handler("scout1", ["@Bones your read?"], dispatched),
            "bones1": _scripted_handler("bones1", ["", "", ""], dispatched),
        },
        gc=GroupChatConfig(
            agent_reactivity_enabled=True,
            agent_next_speaker_selection_enabled=True,
            max_agent_rounds=1,
            max_speakers_per_turn=1,
        ),
    )
    t = store.create_thread(title="room", participants=["scout1", "bones1"])
    cap = store.append_message(t.id, author_id="captain", role="captain", body="thoughts team?")
    replies = await group_chat_fanout(
        runtime, t.id, captain_body="thoughts team?", captain_msg=cap
    )
    assert [r["agent_id"] for r in replies] == ["scout1"]  # bones1 thinned
    bones_calls = sum(1 for d in dispatched if d["agent_id"] == "bones1")
    assert bones_calls == 2  # one attempt + exactly one retry, then give up
    assert "(no response)" not in _agent_bodies(store, t.id)
