"""AD-1346 M3a (#1604) - real-boot tests: the shadow ``AdmissionService`` is wired, and a constructor that raises is logged.

These boot a real ``ProbOSRuntime`` through every startup phase with the mock LLM, as
``tests/test_ad1346_identity_service_boot.py`` does:

- T17 after a boot the service answers over the runtime's own facade and stop record: each agent the facade resolves is
      admitted under its slot, a Captain's stop issued through ``runtime.agent_stops`` is seen by the next decision and
      no refusal is counted for it, and a clean ``stop()`` releases the service.
- T18 the service exists when ``create_agent_fleet`` is reached and answers there, and the rollback of a start that fails
      there releases it.
- T19 a constructor that raises ``RuntimeError`` is logged once at WARNING with its traceback,
      ``runtime.admission_service`` stays None, and that boot completes.

T17 and T19 boot with ``SystemConfig()`` and the three switches M1a's boot tests turn off (naming ceremony, proactive
loop, QA); T18 uses ``lifecycle_config(..., zero_grace=True)`` as M1a's T15 does. M3a adds no configuration field (T13).
Every data directory is under ``tmp_path``.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import pytest

import probos.admission as admission
from probos.admission import AdmissionService, AdmissionVerdict, WorkRequest
from probos.agent_stop import AgentStopService
from probos.cognitive.llm_client import MockLLMClient
from probos.config import SystemConfig
from probos.crew_utils import is_crew_agent
from probos.identity_service import IdentityService
from probos.runtime import ProbOSRuntime
from tests.fixtures.runtime_factory import make_runtime
from tests.fixtures.runtime_lifecycle import InjectedStartFailure, inject_start_failure, lifecycle_config

CANARY = "CANARY-ad1346-m3a-boot: the Captain's private reason"


def _config() -> SystemConfig:
    config = SystemConfig()
    config.onboarding.naming_ceremony = False
    config.proactive_cognitive.enabled = False
    config.qa.enabled = False
    return config


async def _boot(data_dir: Path) -> ProbOSRuntime:
    runtime = ProbOSRuntime(config=_config(), data_dir=data_dir, llm_client=MockLLMClient())
    await runtime.start()
    return runtime


def _intent(presented_id: str) -> WorkRequest:
    return WorkRequest(presented_id, "intent", "intent", "captain", "captain")


async def test_after_a_boot_the_service_answers_over_the_runtimes_own_facade_and_stop_record(tmp_path: Path) -> None:
    """T17 (kills M16, M17, M22, M25, M33, M36)."""
    rt = await _boot(tmp_path / "data")
    try:
        gate = rt.admission_service
        assert isinstance(gate, AdmissionService), "the boot must build the shadow admission service"
        assert isinstance(rt.identity_service, IdentityService) and isinstance(rt.agent_stops, AgentStopService)
        kinds: set[str] = set()
        for agent in rt.registry.all():
            ref = rt.identity_service.resolve(agent.id)
            if ref is None:
                continue  # T7 covers an unresolved principal
            verdict = gate.decide(_intent(agent.id))
            assert (verdict.outcome, verdict.key, verdict.principal) == ("admit", agent.id, ref), agent.id
            kinds.add(verdict.principal_kind)
        assert kinds == {"certificate", "asset"}, f"premise: the boot has a certified agent and an asset: {kinds}"
        crew = next(
            (
                a for a in rt.registry.all()
                if a.did and is_crew_agent(a, rt.ontology) and getattr(rt.identity_service.resolve(a.did), "slot_id", None) == a.id
            ),
            None,
        )
        assert crew is not None, "premise: a certified crew agent whose DID resolves to its own slot"
        issued = await rt.agent_stops.issue_stop(crew.id, reason=CANARY)
        try:
            before = rt.agent_stops.refused_counts(issued.record.stop_id)
            verdict = gate.decide(_intent(crew.did))  # no await between the two reads of the counts
            assert rt.agent_stops.refused_counts(issued.record.stop_id) == before, "decide counted a refusal"
            assert (verdict.reason_code, verdict.stop_id, verdict.key) == ("agent_stopped", issued.record.stop_id, crew.id)
            assert "CANARY" not in json.dumps(verdict.to_dict())
        finally:
            await rt.agent_stops.lift_stop(crew.id, reason="lifted by the test")
    finally:
        await rt.stop()
    assert rt.admission_service is None, "a clean stop must release the service"


async def test_the_service_exists_before_the_fleet_and_a_failed_start_releases_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """T18: built before ``create_agent_fleet`` and answering there; the rollback releases it (kills M3, M13, M33, M36, M37)."""
    monkeypatch.chdir(tmp_path)
    runtime = make_runtime(tmp_path, config=lifecycle_config(tmp_path, zero_grace=True))
    seen: list[tuple[Any, AdmissionVerdict | None]] = []

    def at_fleet_entry(rt: ProbOSRuntime) -> None:
        gate = rt.admission_service
        answer = None
        if isinstance(gate, AdmissionService):
            answer = gate.decide(WorkRequest("system:ship_computer", "intent", "intent", "system", "system:ship_computer"))
        seen.append((gate, answer))

    failure = inject_start_failure(monkeypatch, runtime, "fleet_entry", on_fire=at_fleet_entry)
    with pytest.raises(InjectedStartFailure) as raised:
        await runtime.start()

    assert raised.value is failure.error
    assert len(seen) == 1, "premise: the start reached create_agent_fleet"
    gate, answer = seen[0]
    assert isinstance(gate, AdmissionService), "the service must exist when the fleet is created"
    assert answer is not None and answer.outcome == "admit"
    assert runtime.admission_service is None, "a rolled-back start must release the service"


async def test_a_constructor_that_raises_is_logged_and_the_boot_completes_without_the_service(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
) -> None:
    """T19: #1604 property 11 for a constructor that raises ``RuntimeError``: logged, the attribute None, the boot completes (kills M34, M35)."""

    class _Refuses:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            raise RuntimeError("INJECTED admission construction failure")

    monkeypatch.setattr(admission, "AdmissionService", _Refuses)
    caplog.set_level(logging.WARNING, logger="probos.runtime")
    rt = await _boot(tmp_path / "data")
    try:
        assert rt.admission_service is None
        assert isinstance(rt.identity_service, IdentityService), "premise: the boot went past Phase 2 entry"
        assert rt.registry.count > 0, "premise: the fleet was created after the failure"
        warned = [
            r for r in caplog.records
            if r.name == "probos.runtime" and "shadow admission service was not built" in r.getMessage()
        ]
        assert len(warned) == 1 and warned[0].levelno == logging.WARNING
        assert warned[0].exc_info is not None and "INJECTED admission construction failure" in str(warned[0].exc_info[1])
    finally:
        await rt.stop()
