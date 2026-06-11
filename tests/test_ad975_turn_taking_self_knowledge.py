"""AD-975 (Natural Conversation epic #882): crew turn-taking self-knowledge.

In a live 3-person test the crew reasoned accurately about reading the floor but
assumed possible SIMULTANEITY ("two of us could respond before either sees the
other's reply"). In reality ``group_chat_fanout`` is sequential + synchronous:
one speaker per turn, each later speaker receives every prior reply in full
before its own turn — so two crew never answer the same point at once. AD-975
extends the AD-935/967 group-chat protocol hook to teach the real mechanism so
the agent's self-model is correct.

These are pure-function assertions on the hook (no fixtures): the teaching
string is composed deterministically from ``observation`` alone.
"""
from __future__ import annotations

from types import SimpleNamespace

from probos.cognitive.cognitive_agent import CognitiveAgent
from probos.cognitive.decomposer import _CAPABILITY_GAP_RE

_HOOK = CognitiveAgent._conversational_group_chat_protocol


def _out(**params) -> str:
    return _HOOK(SimpleNamespace(), {"params": {"is_group_chat": True, **params}})


def test_turn_taking_block_present_in_group_chat():
    out = _out()
    # The AD-975 mechanics block is taught whenever it is a group chat.
    assert "How turn-taking works here" in out
    assert "one at a time" in out


def test_teaches_sequential_not_simultaneous():
    out = _out().lower()
    # The core correction: turns are sequential, you see completed replies, and
    # two crew never collide on the same point.
    assert "completed reply" in out
    assert "never at the same instant" in out
    assert "never answer the same point at once" in out


def test_teaches_no_live_typing_cue():
    out = _out()
    assert '"typing" cue' in out
    assert "arrives when they have finished" in out


def test_teaches_address_by_name_hands_off_turn():
    out = _out().lower()
    assert "address them by name" in out


def test_not_group_chat_returns_empty():
    # 1:1 DMs are unaffected — no turn-taking block (no is_group_chat param).
    assert _HOOK(SimpleNamespace(), {"params": {}}) == ""
    assert "How turn-taking works here" not in _HOOK(SimpleNamespace(), {"params": {}})


def test_composes_with_roster_and_decline_guidance():
    # AD-967 roster + AD-935 decline + AD-975 mechanics all compose in one string.
    out = _HOOK(SimpleNamespace(), {"params": {"is_group_chat": True, "room_roster": ["Ezri", "Yeo"]}})
    assert "Present in this room: Ezri and Yeo." in out  # AD-967
    assert "[NO_RESPONSE]" in out                          # AD-935
    assert "How turn-taking works here" in out             # AD-975


def test_turn_taking_block_is_gap_regex_safe():
    # The _CAPABILITY_GAP_RE lesson: teaching text must not read like a
    # capability-gap confession (it would wrongly trigger self-mod).
    out = _out(room_roster=["Ezri", "Yeo", "Chapel"])
    assert _CAPABILITY_GAP_RE.search(out) is None
    for banned in ("can't", "cannot", "don't have", "unable to", "not able to", "lack"):
        assert banned not in out.lower()
