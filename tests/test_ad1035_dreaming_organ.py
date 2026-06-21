"""AD-1035: tests for the ``DreamingOrgan`` — the per-agent personal dreaming faculty.

BF-287 discipline: real objects at the substrate boundary — a real ``DreamingOrgan``, a
real ``CognitiveSpine``, a minimal real ``CognitiveAgent`` (via the AD-1028 golden
builders), and a real ``_FakeEngine`` stub for the wrap test; NO ``MagicMock`` where an
attribute typo could pass.

asyncio_mode="auto" (pyproject.toml): async tests carry NO ``@pytest.mark.asyncio``
marker and no ``asyncio.run`` is used.

Coverage maps to the AD-1035 design decisions (DD-1..DD-6):
* DD-1 default-OFF ⇒ the organ is not composed ⇒ byte-identical (shared engine is SoT);
* DD-2 enabled ⇒ a ``DreamingOrgan`` is composed, ``organ_id`` namespaced under the parent;
* DD-3 faithful delegate ⇒ ``run_dream_cycle`` returns EXACTLY the wired engine's report;
* DD-4 no engine ⇒ ``None``; a raising engine ⇒ ``None`` (never raises across the seam);
* DD-5 background discipline ⇒ no-op cycle steps; ``drive_cycle`` never dreams;
* DD-6 non-membership ⇒ an organ (not a ``BaseAgent``); ``detach_all`` releases it.
"""
from __future__ import annotations

from typing import Any

from probos.cognitive.dreaming_organ import DreamingOrgan
from probos.cognitive.organ import BaseCognitiveOrgan
from probos.cognitive.spine import CognitiveSpine
from probos.config import SystemConfig
from probos.substrate.agent import BaseAgent
from probos.types import DreamReport
from tests.fixtures.ad1028_golden._capture_golden import make_dm_agent


# ---------------------------------------------------------------------------
# Test doubles + helpers (real small objects — BF-287)
# ---------------------------------------------------------------------------


class _Parent:
    """Minimal real parent stand-in exposing only the public id the spine/organ read."""

    def __init__(self, runtime_id: str = "agent-dream", sovereign_id: str = "") -> None:
        self.id = runtime_id
        self.sovereign_id = sovereign_id


class _Rt:
    """Minimal real runtime stand-in exposing a real ``SystemConfig``."""

    def __init__(self, config: SystemConfig) -> None:
        self.config = config


class _FakeEngine:
    """A real fake ``DreamingEngine``: records its await count, returns a fixed report."""

    def __init__(self, report: DreamReport) -> None:
        self._report = report
        self.calls = 0

    async def dream_cycle(self) -> DreamReport:
        self.calls += 1
        return self._report


class _RaisingEngine:
    """A fake engine whose ``dream_cycle`` raises — proves the seam never raises."""

    def __init__(self) -> None:
        self.calls = 0

    async def dream_cycle(self) -> DreamReport:
        self.calls += 1
        raise RuntimeError("dream boom")


def _config(*, dreaming_on: bool) -> SystemConfig:
    """A real SystemConfig with the AD-1035 dreaming-organ gate set explicitly."""
    cfg = SystemConfig()
    cfg.dreaming.organ_enabled = dreaming_on
    return cfg


# ---------------------------------------------------------------------------
# DD-1: default-OFF ⇒ no DreamingOrgan composed ⇒ byte-identical
# ---------------------------------------------------------------------------


def test_dd1_construction_default_no_dreaming_organ() -> None:
    agent = make_dm_agent()  # _runtime=None ⇒ dreaming OFF at construction
    assert agent._spine.get_organ("dreaming") is None
    assert agent._spine.has_organs is False


def test_dd1_organ_enabled_false_no_organ_attention_unaffected() -> None:
    agent = make_dm_agent()
    agent._runtime = _Rt(_config(dreaming_on=False))
    agent._compose_organs()
    assert agent._spine.get_organ("dreaming") is None
    # Attention is unaffected by the dreaming gate (both default-OFF here).
    assert agent._spine.get_organ("attention") is None
    assert agent._spine.has_organs is False


def test_dd1_systemconfig_default_is_off() -> None:
    assert SystemConfig().dreaming.organ_enabled is False


# ---------------------------------------------------------------------------
# DD-2: enabled ⇒ a DreamingOrgan is composed, namespaced under the parent
# ---------------------------------------------------------------------------


def test_dd2_composed_when_organ_enabled() -> None:
    agent = make_dm_agent()
    agent._runtime = _Rt(_config(dreaming_on=True))
    agent._compose_organs()
    organ = agent._spine.get_organ("dreaming")
    assert isinstance(organ, DreamingOrgan)
    # Identity is derived + namespaced under the parent (AD-1033).
    expected_parent = (
        getattr(agent, "sovereign_id", "") or getattr(agent, "id", "") or str(agent)
    )
    assert organ.parent_id == expected_parent
    assert organ.organ_id == f"{expected_parent}.dreaming"
    # Only dreaming composed — attention stays OFF (independent gates).
    assert agent._spine.get_organ("attention") is None


def test_dd2_compose_is_idempotent_when_enabled() -> None:
    agent = make_dm_agent()
    agent._runtime = _Rt(_config(dreaming_on=True))
    agent._compose_organs()
    first = agent._spine.get_organ("dreaming")
    agent._compose_organs()  # second call must not replace the composed organ
    assert agent._spine.get_organ("dreaming") is first


# ---------------------------------------------------------------------------
# DD-3: faithful delegate ⇒ run_dream_cycle returns EXACTLY the engine's report
# ---------------------------------------------------------------------------


async def test_dd3_faithful_delegate_returns_engine_report() -> None:
    report = DreamReport(episodes_replayed=7)
    engine = _FakeEngine(report)
    organ = DreamingOrgan(engine=engine)
    result = await organ.run_dream_cycle()
    assert result is report  # returns EXACTLY await engine.dream_cycle()
    assert engine.calls == 1  # the wrapped engine was awaited exactly once
    assert organ.last_report is report  # and the report is cached for introspection


# ---------------------------------------------------------------------------
# DD-4: no engine ⇒ None; a raising engine ⇒ None (never raises across the seam)
# ---------------------------------------------------------------------------


async def test_dd4_no_engine_returns_none() -> None:
    organ = DreamingOrgan()  # v1 default: no engine wired ⇒ inert
    assert await organ.run_dream_cycle() is None
    assert organ.last_report is None


async def test_dd4_engine_raises_returns_none_no_raise() -> None:
    engine = _RaisingEngine()
    organ = DreamingOrgan(engine=engine)
    # Never raises across the seam — a dream failure log-and-degrades to None.
    assert await organ.run_dream_cycle() is None
    assert engine.calls == 1
    assert organ.last_report is None


async def test_dd4_set_engine_wires_the_inert_organ() -> None:
    report = DreamReport(weights_strengthened=3)
    organ = DreamingOrgan()
    assert await organ.run_dream_cycle() is None  # inert until wired
    organ.set_engine(_FakeEngine(report))
    assert await organ.run_dream_cycle() is report


# ---------------------------------------------------------------------------
# DD-5: background discipline ⇒ no-op cycle steps; drive_cycle never dreams
# ---------------------------------------------------------------------------


def test_dd5_cycle_steps_are_inherited_noops() -> None:
    organ = DreamingOrgan(engine=_FakeEngine(DreamReport()))
    assert organ.perceive({"any": "context"}) is None
    assert organ.decide("observation") is None
    assert organ.act("decision") is None


def test_dd5_drive_cycle_does_not_invoke_dream_cycle() -> None:
    engine = _FakeEngine(DreamReport())
    spine = CognitiveSpine(_Parent())
    spine.attach_organ(DreamingOrgan(engine=engine))
    spine.drive_cycle({"turn": 1})  # the per-turn hot path
    # The background organ is NEVER driven to dream on the cognitive cycle.
    assert engine.calls == 0


# ---------------------------------------------------------------------------
# DD-6: non-membership ⇒ an organ, not a BaseAgent; detach_all releases it
# ---------------------------------------------------------------------------


def test_dd6_is_organ_not_a_mesh_agent() -> None:
    organ = DreamingOrgan()
    assert isinstance(organ, BaseCognitiveOrgan)
    assert not isinstance(organ, BaseAgent)


def test_dd6_detach_all_releases_dreaming_organ() -> None:
    spine = CognitiveSpine(_Parent())
    organ = DreamingOrgan()
    spine.attach_organ(organ)
    assert organ.attached is True
    spine.detach_all()
    assert organ.attached is False
    assert spine.get_organ("dreaming") is None
