"""The storage gate compares an episode only with recent episodes of the same owners (#1798).

``EpisodicMemory.store`` consults the write-time storage gate, whose near-duplicate check rejected an episode alike
to ANY of its last ``recent_window`` fingerprints, whoever owned them: an agent lost its own episode when another
agent's was alike. Each fingerprint now carries its owner key (the set of ``agent_ids``) and the check reads only
fingerprints with an equal key; an ownerless episode compares only with ownerless ones. The window stays one deque
shared by every writer.

Synthetic fixtures only. Until M2 the cases marked ``built`` are strict expected failures: each fails on the base at
its own assert. M2 makes ``built`` a no-op. The unmarked cases are controls that pass on the base and after.
"""

from __future__ import annotations

import logging
import time
from typing import Any

import pytest

from probos.cognitive.episodic import EpisodicMemory
from probos.cognitive.storage_gate import StorageGate
from probos.config_models import StorageGateConfig
from probos.events import EventType
from probos.types import AnchorFrame, Episode, EpisodeStoreOutcome
from tests.test_mention_fanout_episode_owner import (
    _CREW,
    _Bus,
    _fan_out,
    _fanout_episodes_by_owner,
    _owner,
    _runtime,
    _slot,
)

# M1: each built case fails on the base at its own assert; M2 replaces this marker with a no-op.
built = pytest.mark.xfail(strict=True, reason="#1798: the gate compares across owners until M2")

_ANCHOR = AnchorFrame(channel="chat", trigger_type="group_fanout", participants=["captain"])
_TEXT = "coolant loop two reads warm at the pump bearing after the morning sweep"


def _gate(**overrides: Any) -> tuple[StorageGate, list[tuple[Any, dict[str, Any]]]]:
    events: list[tuple[Any, dict[str, Any]]] = []
    config = StorageGateConfig(**{"utility_floor": 0.0, **overrides})
    gate = StorageGate(config=config, emit_event_fn=lambda event_type, data: events.append((event_type, data)))
    return gate, events


def _episode(owners: list[str], text: str = _TEXT, *, success: bool | None = None) -> Episode:
    return Episode(
        timestamp=time.time(),
        user_input=text,
        outcomes=[] if success is None else [{"success": success}],
        agent_ids=list(owners),
        anchors=_ANCHOR,
    )


# -- the gate ---------------------------------------------------------------------------------------------------


@built
def test_two_owners_word_identical_episodes_are_both_accepted() -> None:
    """MU1: one agent's episode never rejects another agent's."""
    gate, _events = _gate()
    assert gate.evaluate(_episode(["agent-a"])).action == "ACCEPT"
    assert gate.evaluate(_episode(["agent-b"])).action == "ACCEPT"


def test_the_same_owners_identical_second_episode_is_still_rejected() -> None:
    """Control. MU2, MU8: an agent's own repeat is rejected, and the event still carries its agent_ids."""
    gate, events = _gate()
    first, repeat = _episode(["agent-a"]), _episode(["agent-a"])
    gate.evaluate(first)
    decision = gate.evaluate(repeat)
    assert (decision.action, decision.reason, decision.duplicate_of) == ("REJECT", "near_duplicate", first.id)
    assert events == [(
        EventType.EPISODE_REJECTED,
        {"episode_id": repeat.id, "agent_ids": ["agent-a"], "reason": "near_duplicate", "importance": 5},
    )]


@built
def test_an_ownerless_episode_is_not_compared_with_an_owned_one() -> None:
    """MU1, MU3, MU8: an owned episode never rejects an ownerless one."""
    gate, _events = _gate()
    gate.evaluate(_episode(["agent-a"]))
    assert gate.evaluate(_episode([])).action == "ACCEPT"


def test_an_ownerless_repeat_is_still_rejected() -> None:
    """Control. MU2: ownerless episodes compare with ownerless ones, as before."""
    gate, _events = _gate()
    first = _episode([])
    gate.evaluate(first)
    decision = gate.evaluate(_episode([]))
    assert (decision.action, decision.duplicate_of) == ("REJECT", first.id)


def test_the_owner_key_ignores_the_order_of_agent_ids() -> None:
    """Control. MU2, MU4, MU5, MU8: a shared episode's repeat, its owners listed in another order, is rejected."""
    gate, _events = _gate()
    gate.evaluate(_episode(["agent-a", "agent-b"]))
    assert gate.evaluate(_episode(["agent-b", "agent-a"])).action == "REJECT"


@built
def test_a_shared_episode_does_not_reject_one_owners_own() -> None:
    """MU1, MU5: an owner set compares only with an equal set; agent-a alone is not agent-a with agent-b."""
    gate, _events = _gate()
    gate.evaluate(_episode(["agent-a", "agent-b"]))
    assert gate.evaluate(_episode(["agent-a"])).action == "ACCEPT"


def test_the_window_is_one_window_shared_by_every_owner() -> None:
    """Control. MU6: an owner's fingerprint ages out after ``recent_window`` writes by anyone, as before."""
    gate, _events = _gate(recent_window=2)
    gate.evaluate(_episode(["agent-a"]))
    gate.evaluate(_episode(["agent-b"], "forward array sweep returns nominal echoes on every band"))
    gate.evaluate(_episode(["agent-c"], "shuttle bay doors cycle within tolerance during the drill"))
    assert gate.recent_count == 2
    assert gate.evaluate(_episode(["agent-a"])).action == "ACCEPT"


@built
def test_a_contradiction_across_owners_is_still_flagged_and_accepted(caplog: pytest.LogCaptureFixture) -> None:
    """MU1, MU7: the contradiction check still reads every owner's fingerprints; it only logs."""
    gate, _events = _gate()
    gate.evaluate(_episode(["agent-a"], success=True))
    with caplog.at_level(logging.INFO, logger="probos.cognitive.storage_gate"):
        decision = gate.evaluate(_episode(["agent-b"], success=False))
    assert decision.action == "ACCEPT"
    assert "Contradiction detected" in caplog.text


# -- the store seam, the gate at its shipped settings (StorageGateConfig defaults equal config/system.yaml's) ------


@pytest.fixture
async def gated_memory(tmp_path):
    memory = EpisodicMemory(db_path=tmp_path / "episodes.db", max_episodes=100, relevance_threshold=0.3)
    memory.set_storage_gate(StorageGate(config=StorageGateConfig()))
    await memory.start()
    yield memory
    await memory.stop()


_TRIGGER = " ".join(f"t{i}" for i in range(1, 41))
_GROUP = {"test_alpha_slot": "TestAlpha", "test_bravo_slot": "TestBravo", "test_charlie_slot": "TestCharlie"}


def _group_episode(slot: str, callsign: str) -> Episode:
    """The group fan-out's episode, field by field (routers/thread_fanout.py), with group enrichment off."""
    return Episode(
        timestamp=time.time(),
        user_input=f"[group chat] {_TRIGGER}",
        dag_summary={},
        outcomes=[{
            "intent": "direct_message", "success": True, "response": "Acknowledged.",
            "session_type": "group", "callsign": callsign, "source": "group_chat_fanout",
        }],
        agent_ids=[slot],
        reflection=f"{callsign} said in group chat: Acknowledged.",
        source="group_chat_fanout",
        anchors=AnchorFrame(channel="chat", trigger_type="group_fanout", participants=["captain", *_GROUP.values()]),
    )


@built
async def test_three_agents_alike_group_episodes_are_each_stored(gated_memory) -> None:
    """MU1: a 40-word trigger and identical short replies; each agent's episode is stored by the real store."""
    assert len(set(_TRIGGER.split())) == 40 and len(_TRIGGER) <= 200, "premise: 40 distinct words, under the cap"
    outcomes = [await gated_memory.store(_group_episode(slot, callsign)) for slot, callsign in _GROUP.items()]
    assert outcomes == [EpisodeStoreOutcome.STORED] * 3
    stored = [ep for ep in await gated_memory.recent(k=50) if str(ep.source) == "group_chat_fanout"]
    assert sorted(ep.agent_ids[0] for ep in stored) == sorted(_GROUP)


_ALIKE_REPLY = " ".join(f"n{i}" for i in range(1, 96))


@built
async def test_mention_fanout_alike_long_replies_are_each_stored_as_their_owners(tmp_path, gated_memory) -> None:
    """MU1: the @-mention route, the real store and gate; three agents give one 95-word reply. Two agents' episodes
    differ only by the callsign, twice each, so the base stored one of the three."""
    assert len(set(_ALIKE_REPLY.split())) == 95 and len(_ALIKE_REPLY) <= 500, "premise: 95 distinct words, uncut"
    bus = _Bus(replies={_slot(callsign): _ALIKE_REPLY for callsign in _CREW})
    response = await _fan_out(_runtime(tmp_path, gated_memory, bus))
    assert [r["status"] for r in response["per_agent_replies"]] == ["", "", ""], "premise: three genuine replies"
    by_owner = await _fanout_episodes_by_owner(gated_memory)
    assert sorted(by_owner) == sorted(_owner(callsign) for callsign in _CREW)
