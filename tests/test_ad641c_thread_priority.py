"""AD-641c: Ward Room Thread Priority tests."""

from __future__ import annotations

import math
import time
from dataclasses import FrozenInstanceError
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from probos.cognitive.thread_priority import (
    ThreadPriorityInput,
    ThreadPriorityScore,
    ThreadPriorityScorer,
    ThreadPriorityService,
)
from probos.config import ThreadPriorityConfig
from probos.events import EventType


# --------------------------------------------------------------------------- #
# Section 0 / Section 4
# --------------------------------------------------------------------------- #


def test_event_type_thread_priority_scored_exists() -> None:
    assert EventType.THREAD_PRIORITY_SCORED.value == "thread_priority_scored"


def test_thread_priority_config_defaults() -> None:
    cfg = ThreadPriorityConfig()
    assert cfg.enabled is True
    assert cfg.weight_captain == pytest.approx(0.30)
    assert cfg.weight_unresolved == pytest.approx(0.20)
    assert cfg.weight_cross_department == pytest.approx(0.15)
    assert cfg.weight_recency == pytest.approx(0.20)
    assert cfg.weight_endorsement == pytest.approx(0.15)
    assert cfg.captain_callsign == "Captain"


# --------------------------------------------------------------------------- #
# Scorer (pure)
# --------------------------------------------------------------------------- #


def test_input_and_score_are_frozen_dataclasses() -> None:
    inp = ThreadPriorityInput(thread_id="t1")
    s = ThreadPriorityScore(thread_id="t1", score=0.0)
    with pytest.raises(FrozenInstanceError):
        inp.thread_id = "t2"  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        s.score = 0.5  # type: ignore[misc]


def test_score_with_no_factors_returns_zero() -> None:
    scorer = ThreadPriorityScorer()
    out = scorer.score(ThreadPriorityInput(thread_id="t1"))
    assert out.score == pytest.approx(0.0)
    assert out.factors == {}


def test_captain_involvement_adds_captain_factor() -> None:
    scorer = ThreadPriorityScorer()
    out = scorer.score(
        ThreadPriorityInput(thread_id="t1", captain_involved=True),
    )
    assert "captain" in out.factors
    assert out.factors["captain"] == pytest.approx(0.30)
    assert out.score == pytest.approx(0.30)


def test_unresolved_question_detected_in_recent_bodies() -> None:
    scorer = ThreadPriorityScorer()
    out = scorer.score(
        ThreadPriorityInput(
            thread_id="t1",
            recent_post_bodies=["okay", "hmm?", "yes"],
        ),
    )
    assert "unresolved" in out.factors
    assert out.factors["unresolved"] == pytest.approx(0.20)


def test_cross_department_requires_two_distinct() -> None:
    scorer = ThreadPriorityScorer()
    one_dept = scorer.score(
        ThreadPriorityInput(
            thread_id="t1",
            participant_departments=["science", "science", ""],
        ),
    )
    two_dept = scorer.score(
        ThreadPriorityInput(
            thread_id="t1",
            participant_departments=["science", "engineering"],
        ),
    )
    assert "cross_department" not in one_dept.factors
    assert "cross_department" in two_dept.factors
    assert two_dept.factors["cross_department"] == pytest.approx(0.15)


def test_recency_decays_over_24h_half_life() -> None:
    scorer = ThreadPriorityScorer()
    now = time.time()
    fresh = scorer.score(
        ThreadPriorityInput(thread_id="t1", last_post_at=now),
    )
    one_day = scorer.score(
        ThreadPriorityInput(thread_id="t1", last_post_at=now - 86400),
    )
    two_days = scorer.score(
        ThreadPriorityInput(thread_id="t1", last_post_at=now - 86400 * 2),
    )
    # Recency factor stored at factors["recency"] = recency * weight_recency.
    assert fresh.factors["recency"] == pytest.approx(0.20, rel=0.01)
    assert one_day.factors["recency"] == pytest.approx(0.20 * math.exp(-1.0), rel=0.01)
    assert two_days.factors["recency"] == pytest.approx(0.20 * math.exp(-2.0), rel=0.01)


def test_endorsement_diminishing_returns() -> None:
    scorer = ThreadPriorityScorer()
    zero = scorer.score(ThreadPriorityInput(thread_id="t1", endorsement_count=0))
    one = scorer.score(ThreadPriorityInput(thread_id="t1", endorsement_count=1))
    ten = scorer.score(ThreadPriorityInput(thread_id="t1", endorsement_count=10))
    assert "endorsement" not in zero.factors
    # endorsement factor = 1 - exp(-0.5 * count); test asserts the stored
    # factor (factor * weight_endorsement).
    assert one.factors["endorsement"] == pytest.approx(0.15 * (1 - math.exp(-0.5)), rel=0.01)
    assert ten.factors["endorsement"] == pytest.approx(0.15 * (1 - math.exp(-5.0)), rel=0.01)


def test_score_clamped_to_one() -> None:
    scorer = ThreadPriorityScorer(
        weight_captain=0.6,
        weight_unresolved=0.6,
        weight_cross_department=0.6,
        weight_recency=0.6,
        weight_endorsement=0.6,
    )
    out = scorer.score(
        ThreadPriorityInput(
            thread_id="t1",
            captain_involved=True,
            recent_post_bodies=["?"],
            participant_departments=["a", "b"],
            last_post_at=time.time(),
            endorsement_count=20,
        ),
    )
    assert out.score == pytest.approx(1.0)


# --------------------------------------------------------------------------- #
# Service
# --------------------------------------------------------------------------- #


def _make_service(
    *,
    ward_room: Any,
    event_log: Any | None = None,
    emit_event: Any | None = None,
    captain_callsign: str = "Captain",
) -> tuple[ThreadPriorityService, Any]:
    runtime = MagicMock()
    runtime.ward_room = ward_room
    runtime.event_log = event_log
    svc = ThreadPriorityService(
        runtime=runtime,
        scorer=ThreadPriorityScorer(),
        emit_event=emit_event,
        captain_callsign=captain_callsign,
    )
    return svc, runtime


@pytest.mark.asyncio
async def test_service_get_priority_emits_event() -> None:
    ward_room = MagicMock()
    ward_room.get_thread = AsyncMock(return_value={
        "thread": {"id": "t1"},
        "posts": [
            {
                "id": "p1",
                "author_id": "a1",
                "author_callsign": "Captain",
                "body": "what now?",
                "created_at": time.time(),
                "children": [],
            },
        ],
        "total_post_count": 1,
    })
    event_log = MagicMock()
    event_log.query_structured = AsyncMock(return_value=[])
    emit = MagicMock()
    svc, _ = _make_service(ward_room=ward_room, event_log=event_log, emit_event=emit)

    score = await svc.get_priority("t1")

    assert score is not None
    assert score.thread_id == "t1"
    assert score.score > 0.0
    emit.assert_called_once()
    args, _ = emit.call_args
    assert args[0] == EventType.THREAD_PRIORITY_SCORED
    assert args[1]["thread_id"] == "t1"
    assert "factors" in args[1]


@pytest.mark.asyncio
async def test_service_get_priority_returns_none_when_no_ward_room() -> None:
    svc, _ = _make_service(ward_room=None)
    assert await svc.get_priority("t1") is None
    assert await svc.get_priority("") is None


@pytest.mark.asyncio
async def test_service_top_priorities_takes_channel_id_and_sorts_desc() -> None:
    ward_room = MagicMock()
    ward_room.list_threads = AsyncMock(return_value=[
        {"id": "t1"}, {"id": "t2"}, {"id": "t3"},
    ])

    async def _get_thread(thread_id: str, **kwargs: Any) -> dict[str, Any]:
        bodies = {
            "t1": "calm",
            "t2": "is this urgent?",
            "t3": "calm",
        }
        return {
            "thread": {"id": thread_id},
            "posts": [
                {
                    "id": "p",
                    "author_id": "a",
                    "author_callsign": "crew",
                    "body": bodies.get(thread_id, ""),
                    "created_at": 0.0,
                    "children": [],
                },
            ],
            "total_post_count": 1,
        }

    ward_room.get_thread = AsyncMock(side_effect=_get_thread)
    event_log = MagicMock()
    event_log.query_structured = AsyncMock(return_value=[])
    svc, _ = _make_service(ward_room=ward_room, event_log=event_log)

    top = await svc.top_priorities("ch1", k=3)

    assert len(top) == 3
    # t2 has the question; should sort first.
    assert top[0][0] == "t2"
    assert top[0][1] >= top[1][1] >= top[2][1]
    # k=0 short-circuits.
    assert await svc.top_priorities("ch1", k=0) == []
    # empty channel short-circuits.
    assert await svc.top_priorities("", k=5) == []


@pytest.mark.asyncio
async def test_count_endorsements_filters_by_thread_id() -> None:
    """Regression guard for R1+R3: query_structured shape + entry["data"] read."""
    ward_room = MagicMock()
    # Minimal valid thread so _build_input doesn't short-circuit.
    ward_room.get_thread = AsyncMock(return_value={
        "thread": {"id": "t1"},
        "posts": [{
            "id": "p1",
            "author_id": "a1",
            "author_callsign": "crew",
            "body": "hi",
            "created_at": 0.0,
            "children": [],
        }],
        "total_post_count": 1,
    })
    event_log = MagicMock()
    # Post-R3 row shape: dicts keyed by "data" (NOT "payload").
    event_log.query_structured = AsyncMock(return_value=[
        {"data": {"thread_id": "t1"}},
        {"data": {"thread_id": "t1"}},
        {"data": {"thread_id": "t-other"}},
        {"data": None},
        {"not_a_data_key": "ignored"},
    ])
    svc, _ = _make_service(ward_room=ward_room, event_log=event_log)

    score = await svc.get_priority("t1")

    assert score is not None
    assert "endorsement" in score.factors
    # Only 2 endorsements match thread_id == "t1".
    expected = 0.15 * (1 - math.exp(-0.5 * 2))
    assert score.factors["endorsement"] == pytest.approx(expected, rel=0.01)
    # query_structured was called with the right kwargs.
    event_log.query_structured.assert_awaited_once()
    _, kwargs = event_log.query_structured.call_args
    assert kwargs["event"] == EventType.WARD_ROOM_ENDORSEMENT.value
    assert kwargs["limit"] == 200


def test_extract_posts_recursively_flattens_children() -> None:
    """Regression guard for R4: get_thread returns tree, not flat list."""
    runtime = MagicMock()
    svc = ThreadPriorityService(
        runtime=runtime,
        scorer=ThreadPriorityScorer(),
    )
    # 1 root + 2 replies (one reply has its own reply) = 4 posts total.
    thread = {
        "thread": {"id": "t1"},
        "posts": [
            {
                "id": "root",
                "body": "r",
                "children": [
                    {"id": "c1", "body": "c1", "children": []},
                    {
                        "id": "c2",
                        "body": "c2",
                        "children": [
                            {"id": "gc", "body": "gc", "children": []},
                        ],
                    },
                ],
            },
        ],
    }

    flat = svc._extract_posts(thread)

    ids = [p.get("id") for p in flat]
    assert len(flat) == 4
    assert ids == ["root", "c1", "c2", "gc"]


@pytest.mark.asyncio
async def test_build_input_extracts_distinct_departments_via_resolver(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression guard for R5: department resolved per-author via helper."""
    dept_map = {"a1": "science", "a2": "engineering"}

    def _fake_resolver(author_id: str) -> str:
        return dept_map.get(author_id, "")

    monkeypatch.setattr(
        "probos.ward_room._helpers.resolve_author_department",
        _fake_resolver,
    )

    ward_room = MagicMock()
    ward_room.get_thread = AsyncMock(return_value={
        "thread": {"id": "t1"},
        "posts": [
            {
                "id": "p1",
                "author_id": "a1",
                "author_callsign": "alpha",
                "body": "hi",
                "created_at": 0.0,
                "children": [
                    {
                        "id": "p2",
                        "author_id": "a2",
                        "author_callsign": "beta",
                        "body": "hello",
                        "created_at": 0.0,
                        "children": [],
                    },
                ],
            },
        ],
        "total_post_count": 2,
    })
    event_log = MagicMock()
    event_log.query_structured = AsyncMock(return_value=[])
    svc, _ = _make_service(ward_room=ward_room, event_log=event_log)

    inp = await svc._build_input("t1")

    assert inp is not None
    assert "science" in inp.participant_departments
    assert "engineering" in inp.participant_departments
