"""AD-907: tests for the skill-request holodeck-training completion subscriber.

asyncio_mode="auto": plain ``async def``. The TEAM_SIMULATION_COMPLETED event
is mocked at the boundary as the dict shape the runtime delivers
(``{"type", "data", "timestamp"}``); the store is a real ``SkillRequestStore``.
"""
from __future__ import annotations

from typing import Any

import pytest

from probos.skill_request import SkillRequestStore
from probos.skill_request_training import on_team_simulation_completed


class _FakeRuntime:
    def __init__(self, store: SkillRequestStore | None) -> None:
        self.skill_request_store = store


def _completed_event(simulation_id: str, outcome_score: float) -> dict[str, Any]:
    return {
        "type": "team_simulation_completed",
        "data": {
            "scenario_id": "scn-1",
            "simulation_id": simulation_id,
            "debrief_id": "dbf-1",
            "outcome_score": outcome_score,
            "passed": True,
        },
        "timestamp": 1.0,
    }


@pytest.fixture
async def store() -> SkillRequestStore:
    s = SkillRequestStore(db_path="")
    await s.start()
    try:
        yield s
    finally:
        await s.stop()


async def test_completed_event_advances_in_training_request(
    store: SkillRequestStore,
) -> None:
    req = await store.file_request("agent-1", "summarization")
    await store.decide(req.id, approve=True)
    await store.begin_training(req.id, "sim-42")

    await on_team_simulation_completed(_FakeRuntime(store), _completed_event("sim-42", 0.87))

    updated = await store.get(req.id)
    assert updated is not None
    assert updated.status == "completed"
    assert updated.post_metric == pytest.approx(0.87)


async def test_honest_degrade_when_store_absent() -> None:
    # No store on the runtime -> no-op, no raise.
    await on_team_simulation_completed(_FakeRuntime(None), _completed_event("sim-1", 0.5))


async def test_unknown_simulation_id_is_noop(store: SkillRequestStore) -> None:
    req = await store.file_request("agent-2", "negotiation")
    await store.decide(req.id, approve=True)
    await store.begin_training(req.id, "sim-known")

    await on_team_simulation_completed(
        _FakeRuntime(store), _completed_event("sim-UNKNOWN", 0.9)
    )

    # The in-training request is untouched (still in_training, no post_metric).
    unchanged = await store.get(req.id)
    assert unchanged is not None
    assert unchanged.status == "in_training"
    assert unchanged.post_metric is None


async def test_event_missing_simulation_id_is_noop(store: SkillRequestStore) -> None:
    bad_event = {"type": "team_simulation_completed", "data": {}, "timestamp": 1.0}
    # Should not raise even with a malformed payload.
    await on_team_simulation_completed(_FakeRuntime(store), bad_event)
