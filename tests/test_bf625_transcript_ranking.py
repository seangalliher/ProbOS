"""BF-625: consult_transcript room ranking — a long catch-all room must not
outrank the actual group chat a query names.

The v1 AD-986b scorer summed raw query-token overlap across every message, so a
long 1:1 catch-all room won on sheer volume of common words and outranked the
shorter group chat whose title named the queried participant. This was caught
live: asked "the group chat with Yeo, what visual issue did he have?", Ezri's
own 114-message default 1:1 thread (which mentions Yeo/visual in passing across
many sessions) outscored the real "Ezri, Yeo" group room.

The fix ranks by IDF-weighted BM25 body relevance + a strongly weighted title
field. BF-287 discipline: a REAL ``ChatThreadStore`` on ``tmp_path``.
"""
from __future__ import annotations

from pathlib import Path

from probos.cognitive.transcript_grounding import consult_transcript
from probos.threads import ChatThreadStore


EZRI = "agent-ezri-uuid"
YEO = "agent-yeo-uuid"


def _store(tmp_path: Path) -> ChatThreadStore:
    return ChatThreadStore(tmp_path / "chat_threads.db")


def _seed_long_catchall(store: ChatThreadStore) -> str:
    """A long 1:1 catch-all room (Ezri's default thread) — lots of chit-chat
    that includes the query's common words, and the topic only in passing."""
    t = store.create_thread(title="Hello Ezri", participants=[EZRI])
    # 30 messages of generic chatter: high raw overlap on common words.
    for i in range(30):
        store.append_message(
            t.id, author_id="captain", role="captain",
            body="Do you remember what we had with the group earlier about the plan?",
        )
        store.append_message(
            t.id, author_id=EZRI, role="agent",
            body="Yes, I have the notes on what you had with the group about that.",
            metadata={"callsign": "Ezri"},
        )
    # The topic words appear only twice, in passing.
    store.append_message(
        t.id, author_id=EZRI, role="agent",
        body="There was a visual note somewhere too, a minor issue.",
        metadata={"callsign": "Ezri"},
    )
    return t.id


def _seed_yeo_group(store: ChatThreadStore) -> str:
    """A short group room named for Yeo, densely about Yeo's visual issue."""
    t = store.create_thread(title="Ezri, Yeo", participants=[EZRI, YEO, "captain"])
    store.append_message(t.id, author_id="captain", role="captain",
                         body="Hello Ezri and Yeo")
    store.append_message(
        t.id, author_id=YEO, role="agent",
        body="Honest answer: I don't have the visual feed. The frame is stale.",
        metadata={"callsign": "Yeo"})
    store.append_message(
        t.id, author_id=EZRI, role="agent",
        body="Yeo's visual observation was a 22-hour-old frame — a camera routing miss.",
        metadata={"callsign": "Ezri"})
    store.append_message(
        t.id, author_id=YEO, role="agent",
        body="The stale visual issue persisted the whole chat; I saw an old frame.",
        metadata={"callsign": "Yeo"})
    return t.id


# ---------------------------------------------------------------------------
# headline regression
# ---------------------------------------------------------------------------


def test_long_catchall_does_not_outrank_named_group_room(tmp_path: Path):
    store = _store(tmp_path)
    _seed_long_catchall(store)          # 61 messages, high raw overlap
    _seed_yeo_group(store)              # 4 messages, on-topic + title names Yeo

    excerpt = consult_transcript(
        store, {EZRI},
        "Do you remember the group chat with Yeo? What visual issue did he have?",
    )
    assert excerpt is not None
    # The named group room wins — NOT the long catch-all 1:1.
    assert excerpt.startswith("Room: Ezri, Yeo")
    assert "Hello Ezri" not in excerpt.splitlines()[0]
    # And the excerpt is about the actual visual issue.
    assert "visual" in excerpt.lower()


def test_raw_overlap_would_have_picked_the_catchall(tmp_path: Path):
    """Guard the precise failure mode: the catch-all has MORE raw token overlap,
    so the old sum-scorer would have picked it; the new ranking must not."""
    store = _store(tmp_path)
    catchall = _seed_long_catchall(store)
    group = _seed_yeo_group(store)

    from probos.cognitive.transcript_grounding import _tokens
    q = _tokens("Do you remember the group chat with Yeo? What visual issue did he have?")

    def raw_sum(tid: str) -> int:
        return sum(len(q & _tokens(m.body)) for m in store.list_messages(tid, limit=400))

    # Precondition: the catch-all really does have higher raw overlap.
    assert raw_sum(catchall) > raw_sum(group)
    # But the fixed ranking picks the group room anyway.
    excerpt = consult_transcript(store, {EZRI}, "group chat with Yeo visual issue")
    assert excerpt is not None and excerpt.startswith("Room: Ezri, Yeo")


# ---------------------------------------------------------------------------
# title field
# ---------------------------------------------------------------------------


def test_title_naming_participant_breaks_a_tie(tmp_path: Path):
    """Two rooms with similar body content; only one names the participant in
    its title. The titled room wins (the title is the room's identity)."""
    store = _store(tmp_path)
    a = store.create_thread(title="General", participants=[EZRI])
    b = store.create_thread(title="Ezri, Yeo", participants=[EZRI, YEO, "captain"])
    body = "We discussed the scheduler plan and the rollout timeline in detail."
    for _ in range(3):
        store.append_message(a.id, author_id=EZRI, role="agent", body=body)
        store.append_message(b.id, author_id=EZRI, role="agent", body=body)

    excerpt = consult_transcript(store, {EZRI}, "the chat with Yeo about the scheduler plan")
    assert excerpt is not None
    assert excerpt.startswith("Room: Ezri, Yeo")


# ---------------------------------------------------------------------------
# idf neutralises common words
# ---------------------------------------------------------------------------


def test_common_words_do_not_carry_a_room(tmp_path: Path):
    """A room matching only ubiquitous words (present in every room) must not
    win over a room matching a rare content token."""
    store = _store(tmp_path)
    common = store.create_thread(title="Chatter", participants=[EZRI])
    rare = store.create_thread(title="Logs", participants=[EZRI])
    for _ in range(20):
        store.append_message(common.id, author_id=EZRI, role="agent",
                             body="Yes the plan is with you and we have the notes.")
    # 'plan'/'the'/'with'/'you'/'have' are in BOTH rooms (ubiquitous -> low idf).
    store.append_message(rare.id, author_id=EZRI, role="agent",
                         body="The plan with you: the telemetry kingfisher anomaly recurred.")

    excerpt = consult_transcript(store, {EZRI}, "the kingfisher anomaly we had with you")
    assert excerpt is not None
    assert excerpt.startswith("Room: Logs")


def test_no_content_match_returns_none(tmp_path: Path):
    store = _store(tmp_path)
    t = store.create_thread(title="Ezri, Yeo", participants=[EZRI, YEO])
    store.append_message(t.id, author_id=EZRI, role="agent",
                         body="The weather is fine and the coffee is hot.")
    # No query content token appears anywhere.
    assert consult_transcript(store, {EZRI}, "quantum chromodynamics lecture") is None
