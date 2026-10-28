"""AD-1270 (#1324) slice 4c, M3: the birth chamber reports the orientation modules it delivers.

``holodeck/chamber.py`` read ``m.id`` from AD-507's ``CurriculumModule``, whose key is
``module_id``, so ``HOLODECK_PHASE_ENTERED.modules`` was a list of empty strings.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from probos.config import HolodeckBirthChamberConfig
from probos.crew_development import CoreKnowledgeCurriculumRegistry
from probos.events import EventType
from probos.holodeck import BirthChamber


class _Agent:
    id = "a1"
    agent_type = "engineer"


def _chamber(registry: Any) -> tuple[BirthChamber, list[tuple[Any, dict[str, Any]]]]:
    events: list[tuple[Any, dict[str, Any]]] = []
    chamber = BirthChamber(
        config=HolodeckBirthChamberConfig(enabled=True, auto_advance_enabled=False),
        emit_event_fn=lambda event_type, payload: events.append((event_type, dict(payload))),
    )
    chamber.set_curriculum_registry(registry)
    return chamber, events


def _module_events(events: list[tuple[Any, dict[str, Any]]]) -> list[list[str]]:
    return [p["modules"] for t, p in events if t == EventType.HOLODECK_PHASE_ENTERED and "modules" in p]


async def test_the_orientation_event_names_the_delivered_modules() -> None:
    registry = CoreKnowledgeCurriculumRegistry()
    expected = [m.module_id for m in registry.list_by_phase("orientation")]
    assert expected == ["identity_grounding", "chain_of_command", "ethics_boundaries"]  # premise
    chamber, events = _chamber(registry)

    await chamber.admit(_Agent())

    assert _module_events(events) == [expected]


async def test_a_malformed_module_still_marks_orientation_delivered() -> None:
    chamber, events = _chamber(SimpleNamespace(list_by_phase=lambda phase: (object(),)))

    record = await chamber.admit(_Agent())

    assert _module_events(events) == []
    assert record.gates_passed["curriculum_orientation_delivered"] is True
