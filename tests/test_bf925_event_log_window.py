"""BF-925 (#1655) M2: episode anchors count the real EventLog window; scoring holds it out (F12)."""

from __future__ import annotations

import ast
import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from probos.cognitive.anchor_quality import compute_anchor_confidence
from probos.cognitive.episodic import EpisodicMemory
from probos.cognitive.memory_security import score_anchor_mismatch, validate_recall_result
from probos.crew_profile import Rank
from probos.proactive import ProactiveCognitiveLoop
from probos.substrate.event_log import EventLog
from probos.types import AnchorFrame, Episode, IntentResult

_PROACTIVE = Path(__file__).resolve().parents[1] / "src" / "probos" / "proactive.py"


@pytest.fixture
async def event_log(tmp_path: Path):
    log = EventLog(db_path=tmp_path / "events.db")
    await log.start()
    try:
        yield log
    finally:
        await log.stop()


async def _write_at(log: EventLog, when: float) -> None:
    """One row stamped ``when``. log() stamps the current time, so a past row is written to the table
    directly; its hash-chain columns keep their defaults, which nothing here reads."""
    await log._db.execute(
        "INSERT INTO events (timestamp, category, event) VALUES (?, 'test', 'backdated')",
        (datetime.fromtimestamp(when, tz=timezone.utc).isoformat(),),
    )
    await log._db.commit()


async def test_count_since_counts_the_events_logged_in_the_window(event_log: EventLog) -> None:
    await _write_at(event_log, time.time() - 120.0)
    await event_log.log("test", "now-1")
    await event_log.log("test", "now-2")
    assert await event_log.count_since(time.time() - 60.0) == 2
    assert await event_log.count_since(time.time() - 300.0) == 3
    assert await event_log.count_since(time.time() + 60.0) == 0


async def test_count_since_reads_at_most_cap_rows(event_log: EventLog) -> None:
    for index in range(3):
        await event_log.log("test", f"event-{index}")
    assert await event_log.count_since(0.0, cap=2) == 2
    assert await event_log.count_since(0.0, cap=-1) == 0  # SQLite reads LIMIT -1 as no limit; refused


async def test_count_since_on_an_unstarted_log_is_zero(tmp_path: Path) -> None:
    assert await EventLog(db_path=tmp_path / "events.db").count_since(0.0) == 0


class _Episodes:
    """Stands for EpisodicMemory on the runtime: records what the loop stores. The loop's other
    episodic reads for the context degrade inside their own try blocks."""

    def __init__(self) -> None:
        self.stored: list[Episode] = []

    async def store(self, episode: Episode) -> None:
        self.stored.append(episode)

    async def count_for_agent(self, agent_id: str) -> int:
        return len(self.stored)


def _silent_agent() -> SimpleNamespace:
    async def handle_intent(intent: Any) -> IntentResult:
        return IntentResult(intent_id=intent.id, agent_id="agent-bf925", success=True, result="[NO_RESPONSE]")

    return SimpleNamespace(id="agent-bf925", agent_type="counselor", callsign="Troi", handle_intent=handle_intent)


async def test_a_proactive_episode_anchor_records_the_window(event_log: EventLog, monkeypatch: pytest.MonkeyPatch) -> None:
    """Through the real _think_for_agent no-response path and a real EventLog.

    EpisodicMemory.should_store discards no-response episodes, which is why production never stores
    this anchor; the test opens that gate to read the frame the site builds. The runtime is a
    SimpleNamespace, as in test_ad1228_standing_interests.py.
    """
    monkeypatch.setattr(EpisodicMemory, "should_store", staticmethod(lambda episode: True))
    await _write_at(event_log, time.time() - 120.0)  # outside the 60 s window
    await event_log.log("test", "now-1")
    await event_log.log("test", "now-2")
    episodes = _Episodes()
    loop = ProactiveCognitiveLoop(interval=120.0, cooldown=300.0, on_event=None)
    loop.set_runtime(SimpleNamespace(episodic_memory=episodes, event_log=event_log))
    await loop._think_for_agent(_silent_agent(), Rank.LIEUTENANT, 0.6)
    assert [episode.anchors.event_log_window for episode in episodes.stored] == [2.0]


async def test_a_failed_window_read_records_zero_and_warns_once(caplog: pytest.LogCaptureFixture) -> None:
    class _BrokenLog:  # stands for an EventLog whose read fails; the real count_since signature
        async def count_since(self, since: float, *, cap: int = 1000) -> int:
            raise RuntimeError("events.db is locked")

    loop = ProactiveCognitiveLoop(interval=120.0, cooldown=300.0, on_event=None)
    runtime = SimpleNamespace(event_log=_BrokenLog())
    with caplog.at_level(logging.DEBUG, logger="probos.proactive"):
        assert await loop._event_log_window(runtime) == 0.0
        assert await loop._event_log_window(runtime) == 0.0
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING and "BF-925" in r.getMessage()]
    assert len(warnings) == 1


def test_both_proactive_anchor_sites_read_the_window_through_the_helper() -> None:
    """A source pin, with its limit: the thought-episode site stores only without a Ward Room, and the
    loop does not run without one, so no behavioural test reaches it; the no-response site is driven above."""
    tree = ast.parse(_PROACTIVE.read_text(encoding="utf-8"))
    values = [
        ast.unparse(keyword.value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "AnchorFrame"
        for keyword in node.keywords
        if keyword.arg == "event_log_window"
    ]
    assert values == ["await self._event_log_window(rt)"] * 2


def _frame(window: float, thread_id: str = "thread-1") -> AnchorFrame:
    return AnchorFrame(
        duty_cycle_id="duty-1", watch_section="alpha", channel="ward_room", channel_id="ch-1",
        department="science", participants=["Atlas"], trigger_agent="Atlas", trigger_type="duty_cycle",
        thread_id=thread_id, event_log_window=window,
    )


@pytest.mark.parametrize("thread_id", ["thread-1", ""], ids=["with-thread", "without-thread"])
def test_the_confidence_is_the_same_with_a_zero_and_a_real_window(thread_id: str) -> None:
    assert compute_anchor_confidence(_frame(37.0, thread_id)) == compute_anchor_confidence(_frame(0.0, thread_id))


def test_holding_out_keeps_every_score_as_before() -> None:
    """Every stored episode has window 0.0, so its score is the pre-BF-925 formula's: the window was one
    unfilled evidential field of two."""
    assert compute_anchor_confidence(_frame(0.0)) == pytest.approx(0.25 + 0.25 + 0.25 + 0.15 + 0.10 * 0.5)
    assert compute_anchor_confidence(AnchorFrame(thread_id="thread-1")) == pytest.approx(0.10 * 0.5)
    assert compute_anchor_confidence(AnchorFrame()) == 0.0


def test_the_memory_security_verdict_is_the_same_with_a_zero_and_a_real_window() -> None:
    """The mismatch score ignores the window, so the AD-607 verdict cannot depend on it.

    The production query (episodic._AnchorQueryView) has no event_log_window; this query sets one to
    show the gate ignores it even when asked. The 0.05 threshold makes one evidential mismatch (weight
    0.10) an anomaly, as it was before BF-925.
    """
    query = SimpleNamespace(thread_id="thread-1", event_log_window=37.0)
    config = SimpleNamespace(anchor_mismatch_threshold=0.05)
    verdicts = []
    for window in (0.0, 37.0):
        episode = Episode(
            user_input="x", agent_ids=["agent-1"], source="direct", correlation_id="corr-1",
            anchors=AnchorFrame(thread_id="thread-1", event_log_window=window),
        )
        verdicts.append((
            score_anchor_mismatch(episode, query),
            validate_recall_result(episode, anchor_query=query, config=config).allowed,
        ))
    assert verdicts == [(0.0, True), (0.0, True)]


def test_an_episode_stored_with_or_without_a_window_loads() -> None:
    """Through EpisodicMemory's stored shape (anchors_json) and its loader: a real window round-trips,
    and an anchors_json without the key (written before AD-567g) loads with 0.0."""
    episode = Episode(
        user_input="[Proactive thought] Troi: steady", timestamp=time.time(), agent_ids=["agent-1"],
        source="direct", anchors=AnchorFrame(channel="duty_report", event_log_window=4.0),
    )
    metadata = EpisodicMemory._episode_to_metadata(episode)
    assert EpisodicMemory._metadata_to_episode("ep-1", episode.user_input, metadata).anchors.event_log_window == 4.0
    legacy = json.loads(metadata["anchors_json"])
    del legacy["event_log_window"]
    metadata["anchors_json"] = json.dumps(legacy)
    assert EpisodicMemory._metadata_to_episode("ep-1", episode.user_input, metadata).anchors.event_log_window == 0.0
