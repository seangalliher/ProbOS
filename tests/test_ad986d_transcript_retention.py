"""AD-986d: transcript lifecycle — retention purge + tombstones + purge-indication.

The canonical recording (``ChatThreadStore``) must not persist forever. The
retention reaper hard-deletes stale rooms, leaving a tombstone so a participant
who still holds a subjective memory of the room is honestly told the recording
was purged (rather than silently relying on a lossy recollection).

BF-287 discipline: a REAL ``ChatThreadStore`` on ``tmp_path`` with an injected
clock to age rooms deterministically (no MagicMock). The headline guards:
  * manual ``delete_thread`` leaves NO tombstone (deliberate removal);
  * SOVEREIGN SCOPE — a purge notice is only ever surfaced to a participant of
    the purged room.
"""
from __future__ import annotations

from pathlib import Path

from probos.cognitive.transcript_grounding import (
    purged_room_notice,
    render_purge_indication,
)
from probos.config import MemoryConfig
from probos.threads import ChatThreadStore
from probos.threads.transcript_reaper import TranscriptReaper


EZRI = "agent-ezri-uuid"
YEO = "agent-yeo-uuid"

_DAY = 86400


class _Clock:
    """A controllable monotonic clock for deterministic aging."""

    def __init__(self, t: float = 1_000_000.0) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


def _store(tmp_path: Path, clock: _Clock | None = None) -> ChatThreadStore:
    if clock is None:
        return ChatThreadStore(tmp_path / "chat_threads.db")
    return ChatThreadStore(tmp_path / "chat_threads.db", clock=clock)


# ---------------------------------------------------------------------------
# config
# ---------------------------------------------------------------------------


def test_config_retention_defaults_off():
    c = MemoryConfig()
    assert c.transcript_retention_days == 0  # opt-in: never purge by default
    assert c.transcript_reaper_interval_seconds == 3600


# ---------------------------------------------------------------------------
# purge_thread + tombstone
# ---------------------------------------------------------------------------


def test_purge_thread_deletes_and_tombstones(tmp_path: Path):
    clk = _Clock(1_500_000.0)
    store = _store(tmp_path, clk)
    t = store.create_thread(title="Meeting UX", participants=[EZRI, YEO, "captain"])
    store.append_message(t.id, author_id=EZRI, role="agent", body="hello")

    assert store.purge_thread(t.id) is True
    assert store.get_thread(t.id) is None
    assert store.list_messages(t.id) == []

    tss = store.tombstones_for_participant({EZRI})
    assert len(tss) == 1
    ts = tss[0]
    assert ts.id == t.id
    assert ts.title == "Meeting UX"
    assert set(ts.participants) == {EZRI, YEO, "captain"}
    assert ts.last_active_at == 1_500_000.0
    assert ts.purged_at == 1_500_000.0


def test_purge_thread_missing_returns_false(tmp_path: Path):
    store = _store(tmp_path)
    assert store.purge_thread("does-not-exist") is False
    assert store.tombstones_for_participant({EZRI}) == []


def test_delete_thread_does_not_tombstone(tmp_path: Path):
    """Manual deletion is a deliberate removal — no tombstone, no purge notice."""
    store = _store(tmp_path)
    t = store.create_thread(title="Manual", participants=[EZRI])
    assert store.delete_thread(t.id) is True
    assert store.get_thread(t.id) is None
    assert store.tombstones_for_participant({EZRI}) == []


# ---------------------------------------------------------------------------
# purge_threads_older_than
# ---------------------------------------------------------------------------


def test_purge_older_than_purges_stale_not_fresh(tmp_path: Path):
    clk = _Clock(1_000_000.0)
    store = _store(tmp_path, clk)
    old = store.create_thread(title="Old", participants=[EZRI, "captain"])
    clk.advance(10 * _DAY)
    fresh = store.create_thread(title="Fresh", participants=[EZRI, "captain"])

    cutoff = clk() - 7 * _DAY
    purged = store.purge_threads_older_than(cutoff)

    assert purged == [old.id]
    assert store.get_thread(old.id) is None
    assert store.get_thread(fresh.id) is not None


def test_purge_older_than_exempts_pinned(tmp_path: Path):
    clk = _Clock(1_000_000.0)
    store = _store(tmp_path, clk)
    pinned = store.create_thread(title="Pinned old", participants=[EZRI])
    store.update_thread(pinned.id, pinned=True)
    clk.advance(100 * _DAY)

    purged = store.purge_threads_older_than(clk())  # everything is "old"

    assert purged == []
    assert store.get_thread(pinned.id) is not None


def test_purge_older_than_includes_archived(tmp_path: Path):
    """An archived-and-stale room is the prime purge candidate."""
    clk = _Clock(1_000_000.0)
    store = _store(tmp_path, clk)
    arch = store.create_thread(title="Archived old", participants=[EZRI])
    store.update_thread(arch.id, archived=True)
    clk.advance(100 * _DAY)

    purged = store.purge_threads_older_than(clk())

    assert purged == [arch.id]
    assert store.get_thread(arch.id) is None


def test_purge_older_than_no_stale_returns_empty(tmp_path: Path):
    clk = _Clock(1_000_000.0)
    store = _store(tmp_path, clk)
    fresh = store.create_thread(title="Fresh", participants=[EZRI])
    # cutoff in the past → nothing is older than it.
    assert store.purge_threads_older_than(clk() - 999) == []
    assert store.get_thread(fresh.id) is not None


# ---------------------------------------------------------------------------
# tombstones_for_participant — sovereign scope
# ---------------------------------------------------------------------------


def test_tombstones_for_participant_only_owned(tmp_path: Path):
    store = _store(tmp_path)
    ez_room = store.create_thread(title="Ezri room", participants=[EZRI, "captain"])
    yeo_room = store.create_thread(title="Yeo solo", participants=[YEO, "captain"])
    store.purge_thread(ez_room.id)
    store.purge_thread(yeo_room.id)

    assert [t.title for t in store.tombstones_for_participant({EZRI})] == ["Ezri room"]
    assert [t.title for t in store.tombstones_for_participant({YEO})] == ["Yeo solo"]


def test_tombstones_for_participant_empty_ids(tmp_path: Path):
    store = _store(tmp_path)
    t = store.create_thread(title="X", participants=[EZRI])
    store.purge_thread(t.id)
    assert store.tombstones_for_participant(set()) == []
    assert store.tombstones_for_participant({""}) == []


# ---------------------------------------------------------------------------
# purged_room_notice — the indication
# ---------------------------------------------------------------------------


def test_purged_room_notice_matches_by_title(tmp_path: Path):
    clk = _Clock(1_700_000_000.0)  # 2023-11-14 UTC
    store = _store(tmp_path, clk)
    t = store.create_thread(title="Meeting UX design", participants=[EZRI, "captain"])
    store.append_message(t.id, author_id=EZRI, role="agent", body="sidebar idea")
    store.purge_thread(t.id)

    notice = purged_room_notice(
        store, {EZRI}, "what did we decide about the meeting design?"
    )
    assert notice is not None
    assert "Meeting UX design" in notice
    assert "2023-11-14" in notice
    assert "purged" in notice.lower()


def test_purged_room_notice_sovereign_scope(tmp_path: Path):
    """A participant of the room gets the notice; a non-participant NEVER does."""
    store = _store(tmp_path)
    t = store.create_thread(title="Secret planning", participants=[YEO, "captain"])
    store.purge_thread(t.id)

    # Even a perfectly-matching query must not leak to a non-participant.
    assert purged_room_notice(store, {EZRI}, "what was the secret planning?") is None
    # The actual participant is told honestly.
    assert purged_room_notice(store, {YEO}, "what was the secret planning?") is not None


def test_purged_room_notice_no_match_returns_none(tmp_path: Path):
    store = _store(tmp_path)
    t = store.create_thread(title="Meeting UX", participants=[EZRI])
    store.purge_thread(t.id)
    # Unrelated query → sparse, no notice.
    assert purged_room_notice(store, {EZRI}, "what is the weather in Denver?") is None


def test_purged_room_notice_empty_query_or_ids(tmp_path: Path):
    store = _store(tmp_path)
    t = store.create_thread(title="Meeting UX", participants=[EZRI])
    store.purge_thread(t.id)
    assert purged_room_notice(store, {EZRI}, "") is None
    assert purged_room_notice(store, set(), "meeting") is None


def test_purged_room_notice_ignores_live_room(tmp_path: Path):
    """A still-live room produces no purge notice (only tombstones do)."""
    store = _store(tmp_path)
    store.create_thread(title="Meeting UX", participants=[EZRI])
    assert purged_room_notice(store, {EZRI}, "what about the meeting?") is None


# ---------------------------------------------------------------------------
# render_purge_indication
# ---------------------------------------------------------------------------


def test_render_purge_indication_block():
    notice = 'The recording of "Meeting UX" was purged on 2023-11-14 (UTC).'
    block = render_purge_indication(notice)
    assert block[0].startswith("=== RECORDING PURGED")
    assert block[-1].startswith("=== END RECORDING PURGED")
    assert notice in block
    assert any("memory" in line.lower() for line in block)


# ---------------------------------------------------------------------------
# TranscriptReaper
# ---------------------------------------------------------------------------


async def test_reaper_sweep_once_purges_stale(tmp_path: Path):
    clk = _Clock(1_000_000.0)
    store = _store(tmp_path, clk)
    old = store.create_thread(title="Old room", participants=[EZRI, "captain"])
    store.append_message(old.id, author_id=EZRI, role="agent", body="hi")
    clk.advance(8 * _DAY)
    fresh = store.create_thread(title="Fresh room", participants=[EZRI, "captain"])

    reaper = TranscriptReaper(store, retention_days=7, clock=clk)
    n = await reaper.sweep_once()

    assert n == 1
    assert store.get_thread(old.id) is None
    assert store.get_thread(fresh.id) is not None
    assert [t.title for t in store.tombstones_for_participant({EZRI})] == ["Old room"]


async def test_reaper_sweep_disabled_when_retention_zero(tmp_path: Path):
    clk = _Clock(1_000_000.0)
    store = _store(tmp_path, clk)
    old = store.create_thread(title="Old", participants=[EZRI])
    clk.advance(100 * _DAY)

    reaper = TranscriptReaper(store, retention_days=0, clock=clk)
    assert await reaper.sweep_once() == 0
    assert store.get_thread(old.id) is not None


async def test_reaper_start_noop_when_retention_zero(tmp_path: Path):
    store = _store(tmp_path)
    reaper = TranscriptReaper(store, retention_days=0)
    await reaper.start()
    assert reaper._task is None  # noqa: SLF001 — assert no background task
    await reaper.stop()  # idempotent no-op


async def test_reaper_start_stop_lifecycle(tmp_path: Path):
    store = _store(tmp_path)
    reaper = TranscriptReaper(store, retention_days=7, interval_seconds=60)
    await reaper.start()
    assert reaper._task is not None and not reaper._task.done()  # noqa: SLF001
    await reaper.stop()
    assert reaper._task is None  # noqa: SLF001
    await reaper.stop()  # idempotent


class _RaisingStore(ChatThreadStore):
    def purge_threads_older_than(self, *a, **k):  # type: ignore[override]
        raise RuntimeError("boom")


async def test_reaper_sweep_honest_degrade_on_store_error(tmp_path: Path):
    store = _RaisingStore(tmp_path / "chat_threads.db")
    reaper = TranscriptReaper(store, retention_days=7)
    # Tier-2: logged + reported as 0 purged, never raises out of the loop.
    assert await reaper.sweep_once() == 0
