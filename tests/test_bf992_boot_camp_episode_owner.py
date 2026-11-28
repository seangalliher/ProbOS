"""BF-992 (#1324): the boot camp counts an enrolled agent's episodes under the id its episodes carry.

Crew episodes carry the sovereign id (``cognitive_agent.py:12857``); enrolment is keyed by the slot id.
A real coordinator over a real ``TrustNetwork`` and a real ``MockEpisodicMemory`` holding real ``Episode``
rows, enrolled through finalization's own helper. Nothing stands in for ``count_for_agent``.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from probos.boot_camp import BootCampCoordinator
from probos.cognitive.episodic_mock import MockEpisodicMemory
from probos.config import BootCampConfig
from probos.consensus.trust import TrustNetwork
from probos.events import EventType
from probos.startup.finalize import _activate_boot_camp_on_cold_start
from probos.types import Episode

_START = 1_000_000.0
_SLOT = "security_officer-0"
_SOVEREIGN = "3f9c2a1e-sovereign"


class _Clock:
    def __init__(self) -> None:
        self.now = _START

    def __call__(self) -> float:
        return self.now


def _episodes(owner: str, count: int) -> list[Episode]:
    return [Episode(user_input=f"watch report {i}", timestamp=float(i + 1), agent_ids=[owner]) for i in range(count)]


def _member(**extra: Any) -> SimpleNamespace:
    return SimpleNamespace(id=_SLOT, agent_type="security_officer", callsign="Worf", department="security", **extra)


class _Rig:
    """The shipped criteria (``BootCampConfig()``: 5 episodes, 3 posts, 1 DM, trust 0.55, 60 to 120 minutes)."""

    def __init__(self) -> None:
        self.clock = _Clock()
        self.trust = TrustNetwork()
        self.memory = MockEpisodicMemory()
        self.events: list[tuple[Any, dict]] = []
        self.coord = BootCampCoordinator(
            config=BootCampConfig(),
            trust_service=self.trust,
            episodic_memory=self.memory,
            emit_event_fn=lambda event_type, data: self.events.append((event_type, data)),
            clock=self.clock,
        )

    async def enrol(self, member: SimpleNamespace) -> None:
        runtime = SimpleNamespace(
            boot_camp=self.coord, is_cold_start=False, ontology=None, _lifecycle_state="first_boot",
            episodic_memory=self.memory,  # empty here, so this boot starts a new crew (BF-941)
            registry=SimpleNamespace(all=lambda: [member]),
        )
        assert await _activate_boot_camp_on_cold_start(runtime=runtime) is True

    async def serve(self, agent_id: str) -> None:
        """Every criterion but the episodes is met, at 61 of 120 minutes."""
        self.trust.create_with_prior(agent_id, 3.0, 2.0)  # 0.6; after activation, which skips 0.55 and above
        for _ in range(3):
            await self.coord.on_agent_post(agent_id, "department")
        self.clock.now = _START + 61 * 60
        await self.coord.on_agent_dm(agent_id)  # the last tracked activity; it checks graduation

    def of(self, event_type: EventType) -> list[dict]:
        return [data for kind, data in self.events if kind == event_type]


async def test_episodes_under_the_sovereign_id_graduate_before_the_timeout() -> None:
    rig = _Rig()
    await rig.enrol(_member(sovereign_id=_SOVEREIGN))
    await rig.memory.seed(_episodes(_SOVEREIGN, 5))  # none under the slot id
    await rig.serve(_SLOT)

    assert rig.coord.get_state(_SLOT).memory_id == _SOVEREIGN
    assert not rig.coord.is_enrolled(_SLOT)
    assert [(g["agent_id"], g["episodes"]) for g in rig.of(EventType.BOOT_CAMP_GRADUATION)] == [(_SLOT, 5)]
    assert rig.of(EventType.BOOT_CAMP_TIMEOUT) == []


async def test_episodes_under_the_slot_id_alone_do_not_count_for_an_agent_with_a_sovereign_id() -> None:
    rig = _Rig()
    await rig.enrol(_member(sovereign_id=_SOVEREIGN))
    await rig.memory.seed(_episodes(_SLOT, 5))
    await rig.serve(_SLOT)

    assert rig.coord.is_enrolled(_SLOT)
    assert rig.of(EventType.BOOT_CAMP_GRADUATION) == []


async def test_an_agent_with_no_sovereign_id_is_counted_by_its_slot_id() -> None:
    rig = _Rig()
    await rig.enrol(_member())
    await rig.memory.seed(_episodes(_SLOT, 5))
    await rig.serve(_SLOT)

    assert rig.coord.get_state(_SLOT).memory_id == _SLOT
    assert [g["episodes"] for g in rig.of(EventType.BOOT_CAMP_GRADUATION)] == [5]


async def test_an_enrolment_without_a_memory_id_counts_by_the_agent_id() -> None:
    rig = _Rig()
    await rig.coord.activate([{"agent_id": "crew-1", "callsign": "Wesley", "department": "science"}])
    await rig.memory.seed(_episodes("crew-1", 5))
    await rig.serve("crew-1")

    assert rig.coord.get_state("crew-1").memory_id == "crew-1"
    assert [g["agent_id"] for g in rig.of(EventType.BOOT_CAMP_GRADUATION)] == ["crew-1"]
