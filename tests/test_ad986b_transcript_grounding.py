"""AD-986b: transcript-grounded recall — consult the canonical record.

The sovereign episodic shard is a subjective, lossy recollection; the
``ChatThreadStore`` transcript is the objective record (the recording). This
module surfaces the relevant excerpt of the recording for rooms an agent took
part in, so the agent can ground a recollection in what was actually said.

BF-287 discipline: a REAL ``ChatThreadStore`` on ``tmp_path`` (no MagicMock).
The headline guard is SOVEREIGN SCOPE — an agent must NEVER receive a transcript
for a room it was not a participant in.
"""
from __future__ import annotations

from pathlib import Path

from probos.cognitive.transcript_grounding import (
    consult_transcript,
    render_transcript_grounding,
    _speaker,
    _tokens,
)
from probos.config import MemoryConfig
from probos.threads import ChatThreadStore


EZRI = "agent-ezri-uuid"
YEO = "agent-yeo-uuid"

_EZRI_DESIGN = (
    "That reframe resolves the tension. There is only one stream: the "
    "conversation. A middle path: voice mode shifts the chat to a condensed "
    "sidebar, present but peripheral, and it expands when you exit voice."
)


def _store(tmp_path: Path) -> ChatThreadStore:
    return ChatThreadStore(tmp_path / "chat_threads.db")


def _seed_design_room(store: ChatThreadStore, *, participants: list[str]) -> str:
    """A group room about the meeting text-vs-voice design conversation."""
    t = store.create_thread(title="Meeting UX", participants=participants)
    store.append_message(t.id, author_id="captain", role="captain",
                         body="How should text appear while an agent speaks with voice?")
    store.append_message(t.id, author_id=EZRI, role="agent", body=_EZRI_DESIGN,
                         metadata={"callsign": "Ezri"})
    store.append_message(t.id, author_id=YEO, role="agent",
                         body="Ezri's sidebar framing lands well for me.",
                         metadata={"callsign": "Yeo"})
    return t.id


# ---------------------------------------------------------------------------
# config
# ---------------------------------------------------------------------------


def test_config_defaults_off():
    c = MemoryConfig()
    assert c.transcript_grounded_recall_enabled is False
    assert c.transcript_grounding_max_threads == 8
    assert c.transcript_grounding_max_chars == 1200


# ---------------------------------------------------------------------------
# threads_for_participant — sovereign scope
# ---------------------------------------------------------------------------


def test_threads_for_participant_returns_only_owned_rooms(tmp_path: Path):
    store = _store(tmp_path)
    _seed_design_room(store, participants=[EZRI, YEO, "captain"])
    store.create_thread(title="Yeo solo", participants=[YEO, "captain"])
    ez = store.threads_for_participant({EZRI})
    assert [t.title for t in ez] == ["Meeting UX"]
    yeo = store.threads_for_participant({YEO})
    assert {t.title for t in yeo} == {"Meeting UX", "Yeo solo"}


def test_threads_for_participant_empty_ids(tmp_path: Path):
    store = _store(tmp_path)
    _seed_design_room(store, participants=[EZRI, "captain"])
    assert store.threads_for_participant(set()) == []
    assert store.threads_for_participant({""}) == []


def test_threads_for_participant_respects_limit(tmp_path: Path):
    store = _store(tmp_path)
    for i in range(5):
        store.create_thread(title=f"room {i}", participants=[EZRI, "captain"])
    assert len(store.threads_for_participant({EZRI}, limit=2)) == 2


# ---------------------------------------------------------------------------
# consult_transcript — the recording
# ---------------------------------------------------------------------------


def test_consult_returns_excerpt_for_owned_matching_room(tmp_path: Path):
    store = _store(tmp_path)
    _seed_design_room(store, participants=[EZRI, YEO, "captain"])
    excerpt = consult_transcript(store, {EZRI}, "sidebar condensed text voice")
    assert excerpt is not None
    assert "Room: Meeting UX" in excerpt
    assert "condensed sidebar" in excerpt
    # The agent's own contribution is labeled by callsign.
    assert "Ezri:" in excerpt


def test_consult_sovereign_scope_never_leaks_unowned_room(tmp_path: Path):
    """THE load-bearing guard: a room the agent is NOT in must never surface,
    even when its content matches the query perfectly."""
    store = _store(tmp_path)
    # Only Yeo + Captain are in this room; Ezri is NOT a participant.
    _seed_design_room(store, participants=[YEO, "captain"])
    excerpt = consult_transcript(store, {EZRI}, "sidebar condensed text voice")
    assert excerpt is None


def test_consult_returns_none_on_no_lexical_match(tmp_path: Path):
    store = _store(tmp_path)
    _seed_design_room(store, participants=[EZRI, "captain"])
    assert consult_transcript(store, {EZRI}, "warp core plasma injector") is None


def test_consult_empty_query_or_ids_returns_none(tmp_path: Path):
    store = _store(tmp_path)
    _seed_design_room(store, participants=[EZRI, "captain"])
    assert consult_transcript(store, {EZRI}, "") is None
    assert consult_transcript(store, {EZRI}, "   ") is None
    assert consult_transcript(store, set(), "sidebar") is None


def test_consult_picks_the_best_matching_room(tmp_path: Path):
    store = _store(tmp_path)
    # A weakly-matching room + the strongly-matching design room, both owned.
    weak = store.create_thread(title="Smalltalk", participants=[EZRI, "captain"])
    store.append_message(weak.id, author_id="captain", role="captain",
                         body="The text on the shelf looks dim.")
    _seed_design_room(store, participants=[EZRI, YEO, "captain"])
    excerpt = consult_transcript(store, {EZRI}, "condensed sidebar voice stream")
    assert excerpt is not None
    assert "Room: Meeting UX" in excerpt


def test_consult_excerpt_is_bounded_by_max_chars(tmp_path: Path):
    store = _store(tmp_path)
    t = store.create_thread(title="Long room", participants=[EZRI, "captain"])
    for i in range(40):
        store.append_message(t.id, author_id=EZRI, role="agent",
                             body=f"sidebar discussion point number {i} about condensed layout",
                             metadata={"callsign": "Ezri"})
    excerpt = consult_transcript(store, {EZRI}, "sidebar condensed", max_chars=300)
    assert excerpt is not None
    assert len(excerpt) <= 320  # header + cap + ellipsis slack


def test_consult_matches_by_id_set_robustness(tmp_path: Path):
    """The agent's id set may carry several of its own identifiers; a match on
    any one surfaces the room (sovereign — all ids are the agent's own)."""
    store = _store(tmp_path)
    _seed_design_room(store, participants=[EZRI, "captain"])
    # sovereign_id form differs from the participant id; the real id still matches.
    excerpt = consult_transcript(store, {"agent-ezri-sovereign", EZRI}, "sidebar condensed")
    assert excerpt is not None


# ---------------------------------------------------------------------------
# render + pure helpers
# ---------------------------------------------------------------------------


def test_render_labels_excerpt_as_the_recording():
    block = render_transcript_grounding("Room: X\nCaptain: hi")
    text = "\n".join(block)
    assert "CANONICAL TRANSCRIPT (the recording)" in text
    assert "NOT your memory" in text
    assert "Room: X" in text
    assert "END TRANSCRIPT" in text


def test_speaker_label():
    class _M:
        role = "captain"
        author_id = "captain"
        metadata: dict = {}
    assert _speaker(_M()) == "Captain"

    class _A:
        role = "agent"
        author_id = "agent-ezri-uuid"
        metadata = {"callsign": "Ezri"}
    assert _speaker(_A()) == "Ezri"

    class _B:
        role = "agent"
        author_id = "agent-x"
        metadata: dict = {}
    assert _speaker(_B()) == "agent-x"


def test_tokens_reuses_fts_tokenizer():
    assert _tokens("Condensed Sidebar!") == {"condensed", "sidebar"}
    assert _tokens("") == set()
