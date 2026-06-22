"""AD-956 (Natural Conversation epic #882): scale-aware facilitation.

The facilitator already ranks the room every turn (AD-915) and surfaces an
advisory room-awareness signal (AD-955). AD-956 makes ENFORCEMENT scale-aware:
a small room (2-4 voices, below a span-of-control threshold ratified at 5)
self-regulates with the per-turn cap OFF (ADVISORY — every relevant crew member
may answer, still convergence-gated, [NO_RESPONSE]-thinned, and
``max_agent_rounds``-bounded); a large room (>= threshold) keeps the cap to
GATE the fan-out. ``force_facilitation_min`` is an opt-in floor that gates even
small rooms.

DEFAULT-OFF / BYTE-IDENTICAL: the master flag ``scale_aware_facilitation_enabled``
ships False, so the classifier never runs, the override stays None, and every
round uses ``max_speakers_per_turn`` EXACTLY as before AD-956 (test 11).

Two layers, both tested here:
  * pure ``facilitation_mode`` (the classifier) — boundary tests 1-7,
  * end-to-end through ``group_chat_fanout`` — discriminator tests 8-13.

BF-287 discipline: real ``GroupChatConfig`` / ``ChatThreadStore`` / ``IntentBus``
(NOT MagicMock), mirroring ``tests/test_ad955_room_awareness.py``'s ``_build_env``.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from probos.cognitive.chat_facilitator import facilitation_mode
from probos.config import CommunicationsConfig, GroupChatConfig
from probos.mesh.intent import IntentBus
from probos.mesh.signal import SignalManager
from probos.routers.thread_fanout import group_chat_fanout
from probos.threads import ChatThreadStore
from probos.types import IntentMessage, IntentResult


# ======================= 1. pure facilitation_mode classifier =======================


def test_advisory_below_threshold():
    # Default threshold=5, force_min=0: a small room self-regulates (advisory).
    assert facilitation_mode(2) == "advisory"
    assert facilitation_mode(4) == "advisory"
    assert facilitation_mode(1) == "advisory"


def test_gating_at_and_above_threshold():
    # The ratified threshold of 5 is the gate (>=, inclusive).
    assert facilitation_mode(5) == "gating"
    assert facilitation_mode(8) == "gating"


def test_custom_threshold_lowers_gate():
    assert facilitation_mode(3, threshold=3) == "gating"
    assert facilitation_mode(2, threshold=3) == "advisory"


def test_custom_threshold_raises_gate():
    assert facilitation_mode(5, threshold=8) == "advisory"
    assert facilitation_mode(8, threshold=8) == "gating"


def test_force_min_gates_small_room():
    # The opt-in floor gates a room that would otherwise be advisory.
    assert facilitation_mode(3, force_min=2) == "gating"
    assert facilitation_mode(2, force_min=2) == "gating"


def test_force_min_zero_is_off():
    # force_min=0 (the default) is inert — only the threshold decides.
    assert facilitation_mode(3, force_min=0) == "advisory"
    assert facilitation_mode(4, force_min=0) == "advisory"


def test_force_min_below_count_stays_advisory():
    # A room smaller than BOTH the floor and the threshold stays advisory.
    assert facilitation_mode(2, force_min=3) == "advisory"
    assert facilitation_mode(3, force_min=3) == "gating"


# ======================= 2. end-to-end through group_chat_fanout =======================

# Crew types eligible for fan-out (all in crew_utils._WARD_ROOM_CREW).
_CREW_TYPES = ["scout", "diagnostician", "architect", "operations_officer", "engineering_officer"]


class _FakeAgent:
    def __init__(self, agent_type: str) -> None:
        self.agent_type = agent_type


class _FakeRegistry:
    def __init__(self, agents: dict) -> None:
        self._a = agents

    def get(self, agent_id: str):
        return self._a.get(agent_id)


class _FakeCallsigns:
    def __init__(self, mapping: dict) -> None:
        self._m = mapping

    def get_callsign(self, agent_type: str) -> str:
        return self._m.get(agent_type, "")


def _seq_clock():
    n = {"t": 0}

    def _c() -> float:
        n["t"] += 1
        return float(n["t"])

    return _c


def _make_handler(agent_id: str, captured: list, *, decline: bool = False):
    async def _h(intent: IntentMessage) -> IntentResult:
        captured.append(agent_id)
        text = "[NO_RESPONSE]" if decline else f"reply::{agent_id}"
        return IntentResult(intent_id=intent.id, agent_id=agent_id, success=True, result=text)
    return _h


def _build_env(tmp_path, *, gc, n: int, decline_ids: frozenset = frozenset()):
    """Real harness mirroring test_ad955_room_awareness._build_env, parameterized
    by participant count ``n``. Returns (store, runtime, captured, agent_ids).

    ``captured`` collects the agent_id of every DISPATCHED speaker (one append
    per ``direct_message`` delivery). With reactivity OFF, ``len(captured)`` is
    exactly the round-0 dispatch count.
    """
    store = ChatThreadStore(tmp_path / "threads.db", clock=_seq_clock())
    bus = IntentBus(SignalManager(reap_interval=1.0))
    types = _CREW_TYPES[:n]
    agents = {f"{t}_{i}": _FakeAgent(t) for i, t in enumerate(types)}
    runtime = SimpleNamespace(
        chat_thread_store=store,
        intent_bus=bus,
        registry=_FakeRegistry(agents),
        ontology=None,
        callsign_registry=_FakeCallsigns({t: t.title() for t in types}),
        project_store=None,
        config=SimpleNamespace(group_chat=gc, communications=CommunicationsConfig(), attachments=None),
    )
    captured: list[str] = []
    for aid in agents:
        bus.subscribe(aid, _make_handler(aid, captured, decline=aid in decline_ids), intent_names=["direct_message"])
    return store, runtime, captured, list(agents)


async def _run(store, runtime, agent_ids):
    t = store.create_thread(title="room", participants=agent_ids)
    cap = store.append_message(t.id, author_id="captain", role="captain", body="status team?")
    replies = await group_chat_fanout(runtime, t.id, captain_body="status team?", captain_msg=cap)
    return replies


@pytest.mark.asyncio
async def test_flag_on_small_room_widens_to_advisory(tmp_path):
    # (8) flag ON, threshold=5, 3 agents -> advisory (3 < 5) -> cap OFF ->
    # all 3 dispatched in round 0.
    store, runtime, captured, ids = _build_env(
        tmp_path,
        gc=GroupChatConfig(
            max_speakers_per_turn=1, agent_reactivity_enabled=False,
            scale_aware_facilitation_enabled=True, facilitation_gate_threshold=5,
        ),
        n=3,
    )
    await _run(store, runtime, ids)
    assert len(captured) == 3


@pytest.mark.asyncio
async def test_flag_on_large_room_stays_gating(tmp_path):
    # (9) flag ON, 5 agents -> gating (5 >= 5) -> cap=1 -> 1 dispatched.
    store, runtime, captured, ids = _build_env(
        tmp_path,
        gc=GroupChatConfig(
            max_speakers_per_turn=1, agent_reactivity_enabled=False,
            scale_aware_facilitation_enabled=True, facilitation_gate_threshold=5,
        ),
        n=5,
    )
    await _run(store, runtime, ids)
    assert len(captured) == 1


@pytest.mark.asyncio
async def test_force_min_gates_small_room_e2e(tmp_path):
    # (10) force_min=2, 3 agents -> gating -> 1 dispatched; the force_min=0
    # sibling of the SAME room widens to advisory -> 3 dispatched.
    store, runtime, captured, ids = _build_env(
        tmp_path,
        gc=GroupChatConfig(
            max_speakers_per_turn=1, agent_reactivity_enabled=False,
            scale_aware_facilitation_enabled=True, force_facilitation_min=2,
        ),
        n=3,
    )
    await _run(store, runtime, ids)
    assert len(captured) == 1

    store2, runtime2, captured2, ids2 = _build_env(
        tmp_path / "sib",
        gc=GroupChatConfig(
            max_speakers_per_turn=1, agent_reactivity_enabled=False,
            scale_aware_facilitation_enabled=True, force_facilitation_min=0,
        ),
        n=3,
    )
    await _run(store2, runtime2, ids2)
    assert len(captured2) == 3


@pytest.mark.asyncio
async def test_flag_off_is_byte_identical(tmp_path):
    # (11) flag OFF, 3 agents -> the classifier never runs, override stays None,
    # cap=1 -> 1 dispatched. Byte-identical to before AD-956, and identical to
    # (a) a config built WITHOUT any scale fields and (b) the per-round dispatch
    # of a flag-ON GATING (5-agent) room.
    store, runtime, captured, ids = _build_env(
        tmp_path,
        gc=GroupChatConfig(
            max_speakers_per_turn=1, agent_reactivity_enabled=False,
            scale_aware_facilitation_enabled=False,
        ),
        n=3,
    )
    await _run(store, runtime, ids)
    assert len(captured) == 1

    # No scale fields passed at all -> defaults (flag False) -> same dispatch.
    store_d, runtime_d, captured_d, ids_d = _build_env(
        tmp_path / "default",
        gc=GroupChatConfig(max_speakers_per_turn=1, agent_reactivity_enabled=False),
        n=3,
    )
    await _run(store_d, runtime_d, ids_d)
    assert len(captured_d) == 1

    # Flag-ON gating room dispatches the SAME per-round count (the cap).
    store_g, runtime_g, captured_g, ids_g = _build_env(
        tmp_path / "gating",
        gc=GroupChatConfig(
            max_speakers_per_turn=1, agent_reactivity_enabled=False,
            scale_aware_facilitation_enabled=True, facilitation_gate_threshold=5,
        ),
        n=5,
    )
    await _run(store_g, runtime_g, ids_g)
    assert len(captured) == len(captured_d) == len(captured_g) == 1


@pytest.mark.asyncio
async def test_no_response_thins_a_widened_round(tmp_path):
    # (12) advisory widens a 3-agent room to all 3 dispatched; one agent replies
    # [NO_RESPONSE]. It IS dispatched (in captured) but its reply is thinned from
    # the returned all_replies.
    store, runtime, captured, ids = _build_env(
        tmp_path,
        gc=GroupChatConfig(
            max_speakers_per_turn=1, agent_reactivity_enabled=False,
            scale_aware_facilitation_enabled=True, facilitation_gate_threshold=5,
        ),
        n=3,
        decline_ids=frozenset({"diagnostician_1"}),
    )
    replies = await _run(store, runtime, ids)
    assert len(captured) == 3                      # all dispatched (advisory widened)
    assert "diagnostician_1" in captured            # the decliner WAS dispatched
    reply_ids = {r["agent_id"] for r in replies}
    assert "diagnostician_1" not in reply_ids       # but thinned from the replies
    assert len(replies) == 2


@pytest.mark.asyncio
async def test_classify_failure_degrades_to_gating(tmp_path, monkeypatch):
    # (13) a classifier exception honest-degrades to today's gating cap
    # (override=None) and never aborts the fan-out: 1 dispatched, no raise.
    def _boom(*_a, **_k):
        raise RuntimeError("classify boom")

    monkeypatch.setattr("probos.routers.thread_fanout.facilitation_mode", _boom)
    store, runtime, captured, ids = _build_env(
        tmp_path,
        gc=GroupChatConfig(
            max_speakers_per_turn=1, agent_reactivity_enabled=False,
            scale_aware_facilitation_enabled=True, facilitation_gate_threshold=5,
        ),
        n=3,
    )
    replies = await _run(store, runtime, ids)       # must not raise
    assert len(captured) == 1
    assert isinstance(replies, list)
