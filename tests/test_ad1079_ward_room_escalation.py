"""AD-1079: Ward-Room -> group-chat escalation suggestion.

When a Ward Room thread becomes a sustained multi-crew working exchange, hint a
Commander+ participant to convene a dedicated room (the "social spark" the
original agent-created rooms had — a senior agent "authorizing" a room, a peer
"suggesting we pull it into one place"). Default-OFF; one-shot; delivered via the
AD-1077 note slot; only to an agent who can actually convene.
"""
from __future__ import annotations

from types import SimpleNamespace

from probos.proactive import (
    ProactiveCognitiveLoop,
    _distinct_post_authors,
    should_suggest_escalation,
)


# ---------------- pure: distinct author walk ----------------


def test_distinct_post_authors_walks_nested_tree():
    posts = [
        {"author_id": "a", "children": [{"author_id": "b", "children": []}]},
        {"author_id": "c", "children": [{"author_id": "a", "children": []}]},  # dup a
    ]
    assert _distinct_post_authors(posts) == {"a", "b", "c"}


def test_distinct_post_authors_empty_and_malformed():
    assert _distinct_post_authors([]) == set()
    assert _distinct_post_authors([None, {"children": []}, "x"]) == set()


# ---------------- pure: threshold decision ----------------


def test_should_suggest_escalation_thresholds():
    assert should_suggest_escalation(3, 6, min_crew=3, min_posts=6) is True
    assert should_suggest_escalation(2, 6, min_crew=3, min_posts=6) is False  # crew low
    assert should_suggest_escalation(3, 5, min_crew=3, min_posts=6) is False  # posts low


def test_should_suggest_escalation_two_crew_floor():
    # A room needs >=2 crew; a min_crew of 1 is floored to 2.
    assert should_suggest_escalation(1, 10, min_crew=1, min_posts=2) is False
    assert should_suggest_escalation(2, 10, min_crew=1, min_posts=2) is True


# ---------------- record (priority vs suppression) ----------------


def test_record_escalation_does_not_overwrite_suppression():
    loop = ProactiveCognitiveLoop(interval=60)
    loop._gc_coaching["a1"] = "SUPPRESSION COACHING"  # AD-1077 note already pending
    loop._record_escalation_suggestion("a1", "Stasis Audit")
    assert loop._gc_coaching["a1"] == "SUPPRESSION COACHING"  # not clobbered


def test_record_escalation_sets_note_when_slot_free():
    loop = ProactiveCognitiveLoop(interval=60)
    loop._record_escalation_suggestion("a1", "Stasis Audit")
    note = loop._gc_coaching["a1"]
    assert "Stasis Audit" in note
    assert "[GROUP_CHAT" in note


# ---------------- gated suggestion behavior ----------------


def _loop(*, enabled: bool, trust: float = 0.8, min_crew: int = 3, min_posts: int = 6):
    loop = ProactiveCognitiveLoop(interval=60)
    loop._runtime = SimpleNamespace(
        config=SimpleNamespace(
            group_chat=SimpleNamespace(
                escalation_suggestion_enabled=enabled,
                escalation_min_crew=min_crew,
                escalation_min_posts=min_posts,
            ),
            communications=SimpleNamespace(group_chat_min_rank="commander"),
        ),
        trust_network=SimpleNamespace(get_score=lambda _id: trust),
    )
    return loop


_QUALIFYING_THREAD = {
    "thread": {"title": "Emergence Correlation"},
    "total_post_count": 8,
    "posts": [
        {"author_id": "a", "children": [{"author_id": "b", "children": []}]},
        {"author_id": "c", "children": []},
    ],
}


def test_disabled_by_default_no_suggestion():
    loop = _loop(enabled=False)
    loop._maybe_suggest_escalation(SimpleNamespace(id="cmdr-1"), _QUALIFYING_THREAD)
    assert loop._gc_coaching == {}


def test_enabled_commander_qualifying_thread_suggests():
    loop = _loop(enabled=True, trust=0.8)  # 0.8 -> Commander
    loop._maybe_suggest_escalation(SimpleNamespace(id="cmdr-1"), _QUALIFYING_THREAD)
    assert "Emergence Correlation" in loop._gc_coaching["cmdr-1"]


def test_below_rank_no_suggestion():
    loop = _loop(enabled=True, trust=0.6)  # 0.6 -> Lieutenant, cannot convene
    loop._maybe_suggest_escalation(SimpleNamespace(id="lt-1"), _QUALIFYING_THREAD)
    assert loop._gc_coaching == {}


def test_below_threshold_no_suggestion():
    loop = _loop(enabled=True, trust=0.8)
    thin = {"thread": {"title": "X"}, "total_post_count": 2, "posts": [{"author_id": "a", "children": []}]}
    loop._maybe_suggest_escalation(SimpleNamespace(id="cmdr-1"), thin)
    assert loop._gc_coaching == {}
