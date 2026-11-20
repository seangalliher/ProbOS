"""BF-990 (#1839): the qualification-drift ``medical_alert`` is edge-triggered.

``DriftScheduler`` holds each agent's latest ``DriftReport`` until its next run (weekly by default),
and ``VitalsMonitorAgent`` pulses every 5 s. Before BF-990, ``_check_thresholds`` sent the
qualification alert on every pulse while any held report was critical, and the Diagnostician spent
one LLM call on each. The alert now fires when a critical report ``(agent_id, timestamp)`` appears
that the last pulse did not hold; a pulse that holds none re-arms it, and an alert whose broadcast
raised is retried. Every case drives the real ``collect_metrics``; the other alert types keep
firing on every pulse.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from probos.agents.medical.diagnostician import DiagnosticianAgent
from probos.agents.medical.vitals_monitor import VitalsMonitorAgent
from probos.cognitive.drift_detector import DriftReport
from probos.types import AgentState, IntentMessage
from tests.test_medical_team import _MockIntentBus, _MockPool, _MockRuntime

_QUAL = "qualification_drift"
_DIAGNOSIS = (
    '{"severity":"medium","category":"qualification","affected_components":["qualification"],'
    '"root_cause":"drift","evidence":[],"recommended_treatment":"observe",'
    '"treatment_intent":"medical_tune","treatment_params":{}}'
)


@pytest.fixture(autouse=True)
def _clear_decision_cache():
    from probos.cognitive.cognitive_agent import _DECISION_CACHES

    _DECISION_CACHES.clear()
    yield
    _DECISION_CACHES.clear()


class _Scheduler:
    """The two members of ``DriftScheduler`` the Vitals Monitor reads."""

    def __init__(self, reports: dict[str, DriftReport] | None = None) -> None:
        self.reports: dict[str, DriftReport] = dict(reports or {})
        self.last_run_time = 1000.0

    @property
    def latest_reports(self) -> dict[str, DriftReport]:
        return dict(self.reports)


class _FailFirstQualificationBus(_MockIntentBus):
    """Raises on the first qualification broadcast; records only delivered intents."""

    def __init__(self) -> None:
        super().__init__()
        self.failed = False

    async def broadcast(self, intent: IntentMessage, timeout: float = 5.0) -> list:
        if intent.params.get("metric") == _QUAL and not self.failed:
            self.failed = True
            raise RuntimeError("bus closed")
        return await super().broadcast(intent, timeout=timeout)


def _report(agent_id: str, ts: float, severity: str = "critical") -> DriftReport:
    return DriftReport(
        agent_id=agent_id, timestamp=ts, signals=[],
        overall_severity=severity, drift_detected=severity != "normal",
    )


def _healthy_runtime(scheduler: _Scheduler | None) -> _MockRuntime:
    runtime = _MockRuntime(
        pools={"filesystem": _MockPool("filesystem", 3, 3)},
        trust_scores={"a1": 0.8, "a2": 0.7},
        agents=[MagicMock(state=AgentState.ACTIVE, confidence=0.9) for _ in range(3)],
    )
    runtime._drift_scheduler = scheduler
    return runtime


async def _pulse(agent: VitalsMonitorAgent, runtime: _MockRuntime) -> list[IntentMessage]:
    """One heartbeat; the qualification alerts it delivered."""
    before = len(runtime.intent_bus.broadcast_calls)
    await agent.collect_metrics()
    return [i for i in runtime.intent_bus.broadcast_calls[before:] if i.params.get("metric") == _QUAL]


# -- T1 -----------------------------------------------------------------------------


@pytest.mark.parametrize("n_agents", [1, 14])
async def test_one_unchanged_critical_report_alerts_once_over_three_heartbeats(n_agents: int) -> None:
    scheduler = _Scheduler({f"ag-{i}": _report(f"ag-{i}", 100.0 + i) for i in range(n_agents)})
    runtime = _healthy_runtime(scheduler)
    agent = VitalsMonitorAgent(pool="medical", runtime=runtime)

    counts = [len(await _pulse(agent, runtime)) for _ in range(3)]

    assert counts == [1, 0, 0]
    sent = [i for i in runtime.intent_bus.broadcast_calls if i.params.get("metric") == _QUAL]
    params = dict(sent[0].params)
    assert set(params) == {"severity", "metric", "current_value", "threshold", "affected", "alert", "timestamp"}
    assert params["severity"] == "warning"
    assert params["threshold"] == 0
    assert params["affected"] == "qualification"
    assert params["current_value"] == n_agents
    assert params["alert"] == f"{n_agents} agent(s) showing critical qualification drift"
    assert agent.latest_vitals["qualification_drift_critical_count"] == n_agents


# -- T2 -----------------------------------------------------------------------------


async def test_a_new_report_generation_alerts_again() -> None:
    scheduler = _Scheduler({"ag-1": _report("ag-1", 100.0)})
    runtime = _healthy_runtime(scheduler)
    agent = VitalsMonitorAgent(pool="medical", runtime=runtime)

    first = len(await _pulse(agent, runtime))
    second = len(await _pulse(agent, runtime))
    scheduler.reports["ag-1"] = _report("ag-1", 200.0)  # a later drift run, still critical
    third = len(await _pulse(agent, runtime))
    assert [first, second, third] == [1, 0, 1]

    scheduler.reports["ag-2"] = _report("ag-2", 300.0)  # a second agent while the first is held
    fourth = await _pulse(agent, runtime)
    assert len(fourth) == 1
    assert fourth[0].params["current_value"] == 2
    assert len(await _pulse(agent, runtime)) == 0


# -- T3 -----------------------------------------------------------------------------


@pytest.mark.parametrize("gap", ["empty-reports", "no-scheduler", "warning-replaces"])
async def test_the_alert_re_arms_after_a_pulse_without_a_critical_report(gap: str) -> None:
    critical = _report("ag-1", 100.0)
    scheduler = _Scheduler({"ag-1": critical})
    runtime = _healthy_runtime(scheduler)
    agent = VitalsMonitorAgent(pool="medical", runtime=runtime)

    first = len(await _pulse(agent, runtime))
    if gap == "empty-reports":
        scheduler.reports = {}
    elif gap == "no-scheduler":
        runtime._drift_scheduler = None
    else:
        scheduler.reports = {"ag-1": _report("ag-1", 150.0, "warning")}
    during = len(await _pulse(agent, runtime))
    runtime._drift_scheduler = scheduler
    scheduler.reports = {"ag-1": critical}  # the same report object returns
    after = len(await _pulse(agent, runtime))

    assert [first, during, after] == [1, 0, 1]


# -- T4 -----------------------------------------------------------------------------


@pytest.mark.parametrize("held", ["no-scheduler", "empty-reports", "warning-only", "normal-only"])
async def test_no_critical_report_never_alerts(held: str) -> None:
    scheduler: _Scheduler | None = {
        "no-scheduler": None,
        "empty-reports": _Scheduler(),
        "warning-only": _Scheduler({"ag-1": _report("ag-1", 100.0, "warning")}),
        "normal-only": _Scheduler({"ag-1": _report("ag-1", 100.0, "normal")}),
    }[held]
    runtime = _healthy_runtime(scheduler)
    agent = VitalsMonitorAgent(pool="medical", runtime=runtime)

    assert [len(await _pulse(agent, runtime)) for _ in range(3)] == [0, 0, 0]


# -- T5 -----------------------------------------------------------------------------


async def test_the_other_alerts_still_repeat_on_every_heartbeat() -> None:
    runtime = _MockRuntime(
        pools={"filesystem": _MockPool("filesystem", 3, 1)},
        trust_scores={"a1": 0.1, "a2": 0.2, "a3": 0.15, "a4": 0.25},
        agents=[MagicMock(state=AgentState.ACTIVE, confidence=0.4) for _ in range(5)],
    )
    runtime.llm_client = MagicMock(
        get_health_status=MagicMock(return_value={"overall": "offline", "tiers": {}}),
    )
    runtime._drift_scheduler = _Scheduler({"ag-1": _report("ag-1", 100.0)})
    agent = VitalsMonitorAgent(pool="medical", runtime=runtime)

    for _ in range(3):
        await agent.collect_metrics()

    by_metric: dict[str, int] = {}
    for intent in runtime.intent_bus.broadcast_calls:
        by_metric[intent.params["metric"]] = by_metric.get(intent.params["metric"], 0) + 1
    assert by_metric == {
        "pool_health": 3, "trust_outlier": 3, "system_health": 3, "llm_health": 3, _QUAL: 1,
    }


# -- T6 -----------------------------------------------------------------------------


async def test_an_alert_that_failed_to_send_is_retried_on_the_next_heartbeat() -> None:
    runtime = _healthy_runtime(_Scheduler({"ag-1": _report("ag-1", 100.0)}))
    runtime.intent_bus = _FailFirstQualificationBus()
    agent = VitalsMonitorAgent(pool="medical", runtime=runtime)

    delivered = [len(await _pulse(agent, runtime)) for _ in range(3)]

    assert runtime.intent_bus.failed is True
    assert delivered == [0, 1, 0]


# -- T7: end to end -------------------------------------------------------------------


async def test_the_diagnostician_makes_one_llm_call_for_three_heartbeats() -> None:
    runtime = _healthy_runtime(
        _Scheduler({f"ag-{i}": _report(f"ag-{i}", 100.0 + i) for i in range(14)}),
    )
    vitals = VitalsMonitorAgent(pool="medical", runtime=runtime)
    llm = MagicMock(complete=AsyncMock(return_value=MagicMock(content=_DIAGNOSIS, tier="fast")))
    diagnostician = DiagnosticianAgent(pool="medical", llm_client=llm)

    for _ in range(3):
        before = len(runtime.intent_bus.broadcast_calls)
        await vitals.collect_metrics()
        for intent in runtime.intent_bus.broadcast_calls[before:]:
            result = await diagnostician.handle_intent(intent)
            assert result is not None and result.success

    assert len(runtime.intent_bus.broadcast_calls) == 1
    assert llm.complete.await_count == 1
