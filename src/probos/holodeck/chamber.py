"""AD-486 v1: Birth Chamber orchestrator.

Public API:
- ``admit(agent)`` after naming ceremony.
- ``try_advance(agent_id)`` checks current-phase gate; advances on pass.
- ``is_graduated(agent_id)`` — production gates short-circuit on this.
- ``acknowledge_*`` setters: orientation steps, ship records, integration.

Late-bind dependencies via public setters per Wave 5 convention #5.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from probos.events import EventType
from probos.holodeck.affect import (
    AffectiveBaselineCheck,
    AffectiveObservation,
    NoOpAffectiveBaselineCheck,
)
from probos.holodeck.gates import (
    gate_calibration_baseline,
    gate_orientation_complete,
    gate_self_discovery,
    gate_ship_records,
    gate_ward_room_integration,
)
from probos.holodeck.phases import HolodeckPhase, next_phase

logger = logging.getLogger(__name__)


@dataclass
class BirthChamberRecord:
    """Per-agent chamber state."""

    agent_id: str
    agent_type: str
    department: str
    current_phase: HolodeckPhase = HolodeckPhase.ORIENTATION
    admitted_at: float = field(default_factory=time.time)
    phase_history: list[tuple[str, float]] = field(default_factory=list)
    gates_passed: dict[str, bool] = field(default_factory=dict)
    affective_observations: list[tuple[str, str, float]] = field(default_factory=list)
    self_discovery_attempts: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "agent_type": self.agent_type,
            "department": self.department,
            "current_phase": self.current_phase.value,
            "admitted_at": self.admitted_at,
            "phase_history": list(self.phase_history),
            "gates_passed": dict(self.gates_passed),
            "affective_observations": list(self.affective_observations),
        }


_GATE_BY_PHASE: dict[HolodeckPhase, Callable[..., Awaitable[tuple[bool, str]]]] = {
    HolodeckPhase.ORIENTATION: gate_orientation_complete,
    HolodeckPhase.CALIBRATION: gate_calibration_baseline,
    HolodeckPhase.SELF_DISCOVERY: gate_self_discovery,
    HolodeckPhase.SHIP_RECORDS: gate_ship_records,
    HolodeckPhase.WARD_ROOM_INTEGRATION: gate_ward_room_integration,
}


class BirthChamber:
    """v1 Birth Chamber orchestrator. AD-486."""

    def __init__(
        self,
        config: Any,
        emit_event_fn: Callable[..., None] | None = None,
        affective_check: AffectiveBaselineCheck | None = None,
    ) -> None:
        self._config = config
        self._emit_event_fn = emit_event_fn
        self._affective_check: AffectiveBaselineCheck = (
            affective_check or NoOpAffectiveBaselineCheck()
        )
        self._records: dict[str, BirthChamberRecord] = {}
        # Late-bound services — public setters per Wave 5 convention #5
        self._personal_ontology_prober: Any = None
        self._curriculum_registry: Any = None
        self._circuit_breaker: Any = None
        self._callsign_registry: Any = None
        self._episodic_memory: Any = None
        # Pending Ward Room subscriptions deferred until graduation
        self._pending_subscriptions: dict[str, list[tuple[str, Callable[..., Awaitable[Any]]]]] = {}
        # Background advance loop task ref (Wave 5 convention #14)
        self._advance_task: asyncio.Task | None = None

    # Public setters
    def set_personal_ontology_prober(self, prober: Any) -> None:
        self._personal_ontology_prober = prober

    def set_curriculum_registry(self, registry: Any) -> None:
        self._curriculum_registry = registry

    def set_circuit_breaker(self, breaker: Any) -> None:
        self._circuit_breaker = breaker

    def set_callsign_registry(self, registry: Any) -> None:
        self._callsign_registry = registry

    def set_episodic_memory(self, memory: Any) -> None:
        self._episodic_memory = memory

    # Records access
    def get_record(self, agent_id: str) -> BirthChamberRecord | None:
        return self._records.get(agent_id)

    def all_records(self) -> tuple[BirthChamberRecord, ...]:
        return tuple(self._records.values())

    def is_admitted(self, agent_id: str) -> bool:
        return agent_id in self._records

    def is_graduated(self, agent_id: str) -> bool:
        rec = self._records.get(agent_id)
        if rec is None:
            return True  # never admitted -> not gated
        return rec.current_phase == HolodeckPhase.GRADUATED

    def get_current_phase(self, agent_id: str) -> HolodeckPhase | None:
        rec = self._records.get(agent_id)
        return rec.current_phase if rec else None

    def queue_pending_subscription(
        self,
        agent_id: str,
        channel_id: str,
        subscribe_fn: Callable[..., Awaitable[Any]],
    ) -> None:
        """Defer a Ward Room subscription until graduation."""
        self._pending_subscriptions.setdefault(agent_id, []).append(
            (channel_id, subscribe_fn)
        )

    # Lifecycle
    async def admit(self, agent: Any, department: str = "") -> BirthChamberRecord:
        rec = BirthChamberRecord(
            agent_id=agent.id,
            agent_type=getattr(agent, "agent_type", ""),
            department=(department or "").lower(),
        )
        rec.phase_history.append((HolodeckPhase.ORIENTATION.value, rec.admitted_at))
        self._records[agent.id] = rec
        self._emit(EventType.HOLODECK_AGENT_ADMITTED, {
            "agent_id": agent.id,
            "agent_type": rec.agent_type,
            "department": rec.department,
        })
        self._emit(EventType.HOLODECK_PHASE_ENTERED, {
            "agent_id": agent.id,
            "phase": HolodeckPhase.ORIENTATION.value,
        })
        # Phase 1 onboarding side-effects: deliver code-of-conduct + curriculum
        await self._deliver_orientation_content(rec)
        return rec

    def acknowledge_orientation_step(self, agent_id: str, step: str) -> None:
        rec = self._records.get(agent_id)
        if rec is None:
            return
        rec.gates_passed[step] = True

    def acknowledge_ship_records(self, agent_id: str) -> None:
        rec = self._records.get(agent_id)
        if rec is not None:
            rec.gates_passed["ship_records_acknowledged"] = True

    def acknowledge_integration_ready(self, agent_id: str) -> None:
        rec = self._records.get(agent_id)
        if rec is not None:
            rec.gates_passed["integration_ready"] = True

    async def try_advance(self, agent_id: str) -> HolodeckPhase:
        rec = self._records.get(agent_id)
        if rec is None:
            return HolodeckPhase.GRADUATED
        if rec.current_phase == HolodeckPhase.GRADUATED:
            return rec.current_phase
        # SELF_DISCOVERY auto-runs probe before checking gate
        if rec.current_phase == HolodeckPhase.SELF_DISCOVERY:
            await self._run_self_discovery_step(rec)
        gate = _GATE_BY_PHASE.get(rec.current_phase)
        if gate is None:
            return rec.current_phase
        services = self._services_dict()
        try:
            passed, reason = await gate(rec, services)
        except Exception:
            logger.warning(
                "AD-486: gate %s raised for agent %s; treating as blocked",
                rec.current_phase.value, rec.agent_id, exc_info=True,
            )
            return rec.current_phase
        if not passed:
            self._emit(EventType.HOLODECK_PHASE_GATE_BLOCKED, {
                "agent_id": rec.agent_id,
                "phase": rec.current_phase.value,
                "reason": reason,
            })
            return rec.current_phase
        prev = rec.current_phase
        new = next_phase(prev)
        rec.current_phase = new
        rec.phase_history.append((new.value, time.time()))
        self._emit(EventType.HOLODECK_PHASE_GATE_PASSED, {
            "agent_id": rec.agent_id,
            "phase": prev.value,
            "next_phase": new.value,
            "reason": reason,
        })
        self._emit(EventType.HOLODECK_PHASE_ENTERED, {
            "agent_id": rec.agent_id,
            "phase": new.value,
        })
        # Affective check between phases
        if getattr(self._config, "affective_baseline_check_enabled", True):
            try:
                obs: AffectiveObservation = await self._affective_check.observe(
                    agent_id=rec.agent_id, prev_phase=prev, new_phase=new,
                )
                rec.affective_observations.append((new.value, obs.status, obs.score))
                self._emit(EventType.HOLODECK_AFFECTIVE_BASELINE_OBSERVED, {
                    "agent_id": rec.agent_id,
                    "phase": new.value,
                    "status": obs.status,
                    "score": obs.score,
                })
            except Exception:
                logger.debug(
                    "AD-486: affective check failed for %s", rec.agent_id, exc_info=True,
                )
        if new == HolodeckPhase.GRADUATED:
            await self._on_graduation(rec)
        return new

    async def run_advance_loop(self) -> None:
        """Background poll. AD-486 v1.

        Iterates all admitted, non-graduated records and calls
        ``try_advance``. Sleeps for ``auto_advance_poll_interval_seconds``.
        Cancellation: re-raises ``asyncio.CancelledError`` per
        copilot-instructions.md async discipline.
        """
        interval = float(getattr(self._config, "auto_advance_poll_interval_seconds", 2.0))
        while True:
            try:
                for agent_id in list(self._records.keys()):
                    rec = self._records.get(agent_id)
                    if rec is None or rec.current_phase == HolodeckPhase.GRADUATED:
                        continue
                    try:
                        await self.try_advance(agent_id)
                    except Exception:
                        logger.warning(
                            "AD-486: try_advance raised for %s; continuing loop",
                            agent_id, exc_info=True,
                        )
                await asyncio.sleep(interval)
            except asyncio.CancelledError:
                logger.debug("AD-486: birth chamber advance loop cancelled")
                raise
            except Exception:
                logger.exception("AD-486: advance loop iteration failed")
                await asyncio.sleep(interval)

    # Internal helpers
    async def _deliver_orientation_content(self, rec: BirthChamberRecord) -> None:
        # AD-489 Code of Conduct presentation (text already in cognitive_agent
        # system prompt — chamber emits an event so HXI / observability can
        # tag this as the canonical "code of conduct presented" moment).
        rec.gates_passed["code_of_conduct_acknowledged"] = True
        rec.gates_passed["identity_grounded"] = True
        # AD-507 curriculum: list_by_phase("orientation")
        if self._curriculum_registry is not None:
            try:
                modules = self._curriculum_registry.list_by_phase("orientation")
                module_ids = [getattr(m, "id", "") for m in modules]
                rec.gates_passed["curriculum_orientation_delivered"] = True
                self._emit(EventType.HOLODECK_PHASE_ENTERED, {
                    "agent_id": rec.agent_id,
                    "phase": HolodeckPhase.ORIENTATION.value,
                    "modules": module_ids,
                })
            except Exception:
                logger.warning(
                    "AD-486: curriculum.list_by_phase failed for %s; auto-marking delivered",
                    rec.agent_id, exc_info=True,
                )
                rec.gates_passed["curriculum_orientation_delivered"] = True
        else:
            rec.gates_passed["curriculum_orientation_delivered"] = True

    async def _run_self_discovery_step(self, rec: BirthChamberRecord) -> None:
        if rec.gates_passed.get("self_distillation_probe_succeeded", False):
            return
        prober = self._personal_ontology_prober
        if prober is None:
            rec.gates_passed["self_distillation_probe_succeeded"] = True
            return
        max_attempts = int(getattr(self._config, "max_self_discovery_probe_attempts", 3))
        if rec.self_discovery_attempts >= max_attempts:
            return
        rec.self_discovery_attempts += 1
        domain = "self-knowledge baseline"
        try:
            result = await prober.probe_domain(rec.agent_id, domain)
        except Exception:
            logger.warning(
                "AD-486: probe_domain failed for %s (attempt %d/%d)",
                rec.agent_id, rec.self_discovery_attempts, max_attempts,
                exc_info=True,
            )
            return
        sub_topics = getattr(result, "sub_topics", ())
        if sub_topics:
            rec.gates_passed["self_distillation_probe_succeeded"] = True

    async def _on_graduation(self, rec: BirthChamberRecord) -> None:
        self._emit(EventType.HOLODECK_GRADUATION, {
            "agent_id": rec.agent_id,
            "agent_type": rec.agent_type,
            "department": rec.department,
            "phase_history": list(rec.phase_history),
        })
        # Drain pending Ward Room subscriptions
        pending = self._pending_subscriptions.pop(rec.agent_id, [])
        for channel_id, fn in pending:
            try:
                await fn()
            except Exception:
                logger.warning(
                    "AD-486: pending subscription drain failed for %s/%s",
                    rec.agent_id, channel_id, exc_info=True,
                )

    def _services_dict(self) -> dict[str, Any]:
        return {
            "calibration_min_episodes": int(
                getattr(self._config, "calibration_min_episodes", 5)
            ),
            "callsign_registry": self._callsign_registry,
            "episodic_memory": self._episodic_memory,
            "circuit_breaker": self._circuit_breaker,
        }

    def _emit(self, event_type: EventType, payload: dict[str, Any]) -> None:
        if self._emit_event_fn is None:
            return
        try:
            self._emit_event_fn(event_type, payload)
        except Exception:
            logger.debug(
                "AD-486: emit_event failed for %s", event_type, exc_info=True,
            )
