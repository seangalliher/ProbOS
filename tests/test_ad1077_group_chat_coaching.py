"""AD-1077: feed a suppressed [GROUP_CHAT] reason back to the agent.

A suppressed room used to vanish silently — the agent got no signal, so the
behavior extinguished (it produced nothing). AD-1077 stashes a one-shot
situational coaching note keyed by agent id when a [GROUP_CHAT] is suppressed,
delivers it on the agent's next proactive cycle via the proven cold-start
``system_note`` situational slot, and the cognitive_agent renders it.

BF-287: real ProactiveCognitiveLoop + real service/store via the AD-924 harness;
the sensorium render is exercised on the real CognitiveAgent method.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from probos.proactive import ProactiveCognitiveLoop
from probos.cognitive.cognitive_agent import CognitiveAgent

# Reuse the AD-924 end-to-end harness (real service + store + loop).
from tests.test_ad924_group_chat_trigger import _build_loop
from tests.test_ad918_agent_initiated_group_chat import _FakeAgent


# ---------------- note storage (per reason) ----------------


def test_record_coaching_no_participant_names_callsign_and_title():
    loop = ProactiveCognitiveLoop(interval=60)
    loop._record_group_chat_coaching("a1", "no_participant_resolved", "Sensor Review")
    note = loop._gc_coaching["a1"]
    assert "callsign" in note
    assert "Sensor Review" in note
    assert "@Reed" in note  # shows the correct tag shape


def test_record_coaching_rate_limited():
    loop = ProactiveCognitiveLoop(interval=60)
    loop._record_group_chat_coaching("a1", "rate_limited", "X")
    assert "rate-limited" in loop._gc_coaching["a1"]


def test_record_coaching_empty_title():
    loop = ProactiveCognitiveLoop(interval=60)
    loop._record_group_chat_coaching("a1", "empty_title", "")
    assert "title" in loop._gc_coaching["a1"]


def test_record_coaching_unknown_reason_is_noop():
    loop = ProactiveCognitiveLoop(interval=60)
    loop._record_group_chat_coaching("a1", "some_other_reason", "X")
    assert "a1" not in loop._gc_coaching


def test_record_coaching_blank_agent_id_is_noop():
    loop = ProactiveCognitiveLoop(interval=60)
    loop._record_group_chat_coaching("", "no_participant_resolved", "X")
    assert loop._gc_coaching == {}


# ---------------- one-shot injection ----------------


def test_inject_pending_coaching_is_one_shot():
    loop = ProactiveCognitiveLoop(interval=60)
    loop._gc_coaching["a1"] = "NOTE"
    ctx: dict = {}
    loop._inject_pending_coaching("a1", ctx)
    assert ctx["system_note"] == "NOTE"
    assert "a1" not in loop._gc_coaching  # consumed
    ctx2: dict = {}
    loop._inject_pending_coaching("a1", ctx2)
    assert "system_note" not in ctx2  # nothing left to deliver


def test_inject_does_not_clobber_cold_start_note():
    loop = ProactiveCognitiveLoop(interval=60)
    loop._gc_coaching["a1"] = "COACHING"
    ctx = {"system_note": "COLD START"}
    loop._inject_pending_coaching("a1", ctx)
    assert ctx["system_note"] == "COLD START"  # cold-start wins this cycle
    assert loop._gc_coaching["a1"] == "COACHING"  # still pending for next cycle


# ---------------- render (sensorium) ----------------


def test_sensorium_renders_proactive_note_when_not_cold_start():
    me = SimpleNamespace(_runtime=SimpleNamespace(is_cold_start=False))
    obs = {"_context_parts": {"system_note": "SYSTEM NOTE: name peers as @Reed."}}
    out = CognitiveAgent._sensorium_cold_start_note(me, obs)
    assert "name peers" in out


def test_sensorium_empty_when_no_note_and_not_cold_start():
    me = SimpleNamespace(_runtime=SimpleNamespace(is_cold_start=False))
    assert CognitiveAgent._sensorium_cold_start_note(me, {"_context_parts": {}}) == ""


def test_sensorium_cold_start_takes_precedence():
    me = SimpleNamespace(_runtime=SimpleNamespace(is_cold_start=True))
    obs = {"_context_parts": {"system_note": "coaching"}}
    out = CognitiveAgent._sensorium_cold_start_note(me, obs)
    assert "fresh start" in out


# ---------------- integration: suppression records coaching ----------------


@pytest.mark.asyncio
async def test_suppressed_room_records_coaching(tmp_path):
    agents = {"forge-1": _FakeAgent("forge-1", "builder")}
    loop, store, _, _ = _build_loop(tmp_path, agents=agents)
    agent = agents["forge-1"]
    # @Ghost resolves to nobody -> below the AD-966 floor -> suppressed.
    text = '[GROUP_CHAT title="Coord" @Ghost] kick off [/GROUP_CHAT]'

    _, actions = await loop._extract_and_execute_actions(agent, text)

    assert store.list_threads() == []
    assert [a for a in actions if a["type"] == "group_chat_suppressed"]
    assert "callsign" in loop._gc_coaching["forge-1"]
