"""BF-920 (#1633): cross-agent verification judges same-thread echoes as
dependent, names the real cascade origin, emits one cascade event per
detection, and delivers the Bridge alerts it builds.

Production objects throughout: the Ward Room schema and
``check_peer_similarity`` for the match shape, ``SocialVerificationService``,
``ThreadManager`` and ``MessageStore`` for the call sites, and
``ThreadEchoAnalyzer``, ``ObservableStateVerifier`` and
``BridgeAlertService`` for the alerts. Only the episodic store, the Ward Room
router and one state provider are doubles.
"""

from __future__ import annotations

import dataclasses
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import aiosqlite
import pytest

from probos.bridge_alerts import AlertSeverity, BridgeAlertService
from probos.cognitive.observable_state import ObservableStateVerifier, VerificationResult
from probos.cognitive.social_verification import (
    SocialVerificationService,
    compute_anchor_independence,
)
from probos.config import SocialVerificationConfig
from probos.types import AnchorFrame, Episode
from probos.ward_room._helpers import check_and_trace_echo
from probos.ward_room.messages import MessageStore
from probos.ward_room.models import _SCHEMA
from probos.ward_room.thread_echo import ThreadEchoAnalyzer
from probos.ward_room.threads import ThreadManager, check_peer_similarity

CASCADE = "cascade_confabulation_detected"
ECHO = "the sensor array reports a coolant leak in sickbay"
PEERS = [
    {"author_id": "B", "author_callsign": "Bravo", "timestamp": 100.0},
    {"author_id": "C", "author_callsign": "Charlie", "timestamp": 105.0},
]


def _thread_anchors(thread_id: str) -> AnchorFrame:
    """Anchors rich enough for check_corroboration's 0.3 confidence gate."""
    return AnchorFrame(
        duty_cycle_id="dc-1",
        channel="ward_room",
        channel_id="ch-1",
        department="medical",
        participants=["agent-x"],
        trigger_agent="agent-x",
        trigger_type="observation",
        thread_id=thread_id,
    )


def _memory(episodes: list[Episode]) -> SimpleNamespace:
    return SimpleNamespace(recall=AsyncMock(return_value=episodes))


class _Recorder:
    """One emitter shared by the service and the store, as the runtime is."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def __call__(self, event_type, data) -> None:
        self.calls.append((getattr(event_type, "value", event_type), data))

    def count(self, name: str) -> int:
        return sum(1 for event_type, _ in self.calls if event_type == name)


class _Posts:
    """ThreadManagerProtocol double: returns copies (the analyzer adds keys)."""

    def __init__(self, posts: list[dict]) -> None:
        self._posts = posts

    async def get_thread_posts_temporal(self, thread_id: str) -> list[dict]:
        return [dict(p) for p in self._posts]


class _ContradictingProvider:
    name = "test_state"

    async def check(self, claim_text, context):
        return VerificationResult(
            provider_name=self.name, claim_text=claim_text, verified=False,
            ground_truth_summary="No active games.", confidence=0.9,
        )


def _echo_posts(gap: float) -> list[dict]:
    rows = [
        ("p1", "alice", "the game state is broken and stale"),
        ("p2", "bob", "I agree the game state is broken stale"),
        ("p3", "carol", "yes the game state appears broken and stale"),
    ]
    return [
        {
            "id": pid, "thread_id": "thread-1", "author_id": author,
            "author_callsign": author.title(), "body": body,
            "created_at": 1000.0 + i * gap,
        }
        for i, (pid, author, body) in enumerate(rows)
    ]


def _medium_cascade_service(emit) -> SocialVerificationService:
    episodes = [
        Episode(id="ep-b", agent_ids=["B"], timestamp=100.0),
        Episode(id="ep-c", agent_ids=["C"], timestamp=105.0),
        Episode(id="ep-a", agent_ids=["A"], timestamp=110.0),
    ]
    return SocialVerificationService(
        episodic_memory=_memory(episodes), config=SocialVerificationConfig(), emit_event_fn=emit,
    )


async def _real_peer_matches(now: float) -> list[dict]:
    """Bravo's thread (now-120) and Charlie's earlier reply (now-300), as the schema stores them."""
    async with aiosqlite.connect(":memory:") as db:
        await db.executescript(_SCHEMA)
        await db.execute(
            "INSERT INTO channels (id, name, channel_type, created_by, created_at) VALUES (?, ?, ?, ?, ?)",
            ("ch1", "medical", "department", "system", now - 900),
        )
        # The current author's own thread: excluded from matches, it holds Charlie's reply.
        await db.execute(
            "INSERT INTO threads (id, channel_id, author_id, title, body, created_at, last_activity, author_callsign) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("t-own", "ch1", "agent-a", "Rounds", "morning rounds summary", now - 400, now - 120, "Alpha"),
        )
        await db.execute(
            "INSERT INTO posts (id, thread_id, author_id, body, created_at, author_callsign) VALUES (?, ?, ?, ?, ?, ?)",
            ("p-charlie", "t-own", "agent-c", ECHO, now - 300, "Charlie"),
        )
        await db.execute(
            "INSERT INTO threads (id, channel_id, author_id, title, body, created_at, last_activity, author_callsign) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("t-bravo", "ch1", "agent-b", "Sensors", ECHO, now - 120, now - 120, "Bravo"),
        )
        await db.commit()
        return await check_peer_similarity(db, "ch1", "agent-a", ECHO)


# --- (1) same thread vs elapsed time -----------------------------------------------------------


def test_same_thread_minutes_apart_is_not_independent() -> None:
    episodes = [
        Episode(id=f"ep-{i}", agent_ids=[f"agent-{i}"], anchors=_thread_anchors("thread-1"),
                timestamp=1000.0 + 120.0 * i)
        for i in range(3)
    ]
    assert compute_anchor_independence(episodes) == 0.0


def test_different_threads_keep_the_time_rule() -> None:
    far = [
        Episode(id="ep-1", anchors=_thread_anchors("thread-1"), timestamp=1000.0),
        Episode(id="ep-2", anchors=_thread_anchors("thread-2"), timestamp=1120.0),
    ]
    near = [
        Episode(id="ep-3", anchors=_thread_anchors("thread-1"), timestamp=1000.0),
        Episode(id="ep-4", anchors=_thread_anchors("thread-2"), timestamp=1020.0),
    ]
    assert compute_anchor_independence(far) == 1.0
    assert compute_anchor_independence(near) == 0.0  # the time rule is what grants `far`


@pytest.mark.asyncio
async def test_corroboration_counts_no_same_thread_partner() -> None:
    episodes = [
        Episode(id=f"ep-{name}", agent_ids=[name], anchors=_thread_anchors("thread-1"),
                timestamp=1000.0 + 300.0 * i)
        for i, name in enumerate(["B", "C", "D"])
    ]
    svc = SocialVerificationService(episodic_memory=_memory(episodes), config=SocialVerificationConfig())
    result = await svc.check_corroboration("A", "coolant leak in sickbay")
    assert result.total_matching_episodes == 3  # premise: all three passed the anchor gate
    assert result.independent_anchor_count == 0
    assert result.anchor_independence_score == 0.0


@pytest.mark.asyncio
async def test_echo_minutes_apart_is_dependent_and_alerts() -> None:
    result = await ThreadEchoAnalyzer(_Posts(_echo_posts(gap=120.0))).analyze("thread-1")
    assert result.echo_detected is True  # premise
    assert result.anchor_independence_score == 0.0
    alerts = BridgeAlertService(clock=lambda: 1000.0).check_ward_room_echo(dataclasses.asdict(result))
    assert [a.alert_type for a in alerts] == ["ward_room_echo_detected"]


# --- (2) the cascade origin --------------------------------------------------------------------


@pytest.mark.asyncio
async def test_peer_matches_carry_created_at() -> None:
    now = time.time()
    by_callsign = {m["author_callsign"]: m for m in await _real_peer_matches(now)}
    assert set(by_callsign) == {"Bravo", "Charlie"}  # premise: one thread match, one reply match
    # Exact: a REAL column returns the float it was written with, so any offset fails (R17).
    assert by_callsign["Bravo"]["timestamp"] == now - 120
    assert by_callsign["Charlie"]["timestamp"] == now - 300


@pytest.mark.asyncio
async def test_cascade_source_is_the_earliest_real_poster() -> None:
    matches = await _real_peer_matches(time.time())
    assert [m["author_callsign"] for m in matches] == ["Bravo", "Charlie"]  # earliest is not first
    svc = SocialVerificationService(episodic_memory=_memory([]), config=SocialVerificationConfig())
    result = await svc.check_cascade_risk("agent-a", "Alpha", ECHO, "ch1", peer_matches=matches)
    assert result is not None
    assert result.source_agent == "Charlie"


# --- (3) one event, and (5) the cascade Bridge alert ----------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("store_cls", [ThreadManager, MessageStore])
async def test_one_cascade_event_per_detection(store_cls) -> None:
    recorder = _Recorder()
    store = store_cls(db=None, emit_fn=recorder)
    store.set_social_verification(_medium_cascade_service(recorder))
    await store._check_cascade_risk(PEERS, "A", "Alpha", "post body", "ch-1")
    assert recorder.count(CASCADE) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("store_cls", [ThreadManager, MessageStore])
async def test_cascade_bridge_alert_is_delivered(store_cls) -> None:
    router = SimpleNamespace(deliver_bridge_alert=AsyncMock())
    store = store_cls(db=None, emit_fn=_Recorder())
    store.set_social_verification(_medium_cascade_service(None))
    store.set_echo_services(bridge_alerts=BridgeAlertService(clock=lambda: 1000.0), ward_room_router=router)
    await store._check_cascade_risk(PEERS, "A", "Alpha", "post body", "ch-1")
    router.deliver_bridge_alert.assert_awaited_once()
    alert = router.deliver_bridge_alert.await_args.args[0]
    assert alert.alert_type == "cascade_confabulation"
    assert alert.severity == AlertSeverity.ADVISORY
    assert "Source: Bravo" in alert.detail


@pytest.mark.asyncio
async def test_low_cascade_raises_no_alert_and_no_event() -> None:
    recorder = _Recorder()
    router = SimpleNamespace(deliver_bridge_alert=AsyncMock())
    episodes = [Episode(id="ep-b", agent_ids=["B"], timestamp=100.0), Episode(id="ep-a", agent_ids=["A"], timestamp=105.0)]
    store = ThreadManager(db=None, emit_fn=recorder)
    store.set_social_verification(SocialVerificationService(
        episodic_memory=_memory(episodes), config=SocialVerificationConfig(), emit_event_fn=recorder,
    ))
    store.set_echo_services(bridge_alerts=BridgeAlertService(clock=lambda: 1000.0), ward_room_router=router)
    await store._check_cascade_risk([PEERS[0]], "A", "Alpha", "post body", "ch-1")
    router.deliver_bridge_alert.assert_not_awaited()
    assert recorder.count(CASCADE) == 0


@pytest.mark.asyncio
async def test_cascade_disabled_skips_the_check() -> None:
    memory = _memory([])
    svc = SocialVerificationService(episodic_memory=memory, config=SocialVerificationConfig(cascade_enabled=False))
    assert await svc.check_cascade_risk("A", "Alpha", "post body", "ch-1", peer_matches=PEERS) is None
    memory.recall.assert_not_awaited()


# --- (4) the mismatch alert, and the echo alert's affected crew ----------------------------------


@pytest.mark.asyncio
async def test_echo_trace_delivers_echo_and_mismatch_alerts() -> None:
    router = SimpleNamespace(deliver_bridge_alert=AsyncMock())
    await check_and_trace_echo(
        ThreadEchoAnalyzer(_Posts(_echo_posts(gap=120.0))),
        ObservableStateVerifier([_ContradictingProvider()]),
        _Recorder(),
        BridgeAlertService(clock=lambda: 1000.0),
        router,
        thread_id="thread-1",
        channel_id="ch-1",
        peer_matches=[{"author_id": "bob"}],
    )
    delivered = [call.args[0] for call in router.deliver_bridge_alert.await_args_list]
    assert [a.alert_type for a in delivered] == ["ward_room_echo_detected", "observable_state_mismatch"]
    assert "Affected: Bob, Carol." in delivered[0].detail
