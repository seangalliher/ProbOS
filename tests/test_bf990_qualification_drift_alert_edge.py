"""BF-990 (#1839): the qualification-drift ``medical_alert`` is edge-triggered.

``DriftScheduler`` holds each agent's latest ``DriftReport`` until its next run (weekly by default),
and ``VitalsMonitorAgent`` pulses every 5 s. Before BF-990, ``_check_thresholds`` sent the
qualification alert on every pulse while any held report was critical, and the Diagnostician spent
one LLM call on each. The alert now fires when a critical report ``(agent_id, timestamp)`` appears
that the last pulse did not hold; a pulse that holds none re-arms it. An alert that no handler
confirmed (the bus raised, returned no result, or returned only failed results) is sent again on the
next pulse, for at most three sends. Every case drives the real ``collect_metrics``; the other alert
types keep firing on every pulse.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from probos.agents.medical.diagnostician import DiagnosticianAgent
from probos.agents.medical.vitals_monitor import VitalsMonitorAgent
from probos.cognitive.drift_detector import DriftReport
from probos.mesh.intent import IntentBus
from probos.mesh.signal import SignalManager
from probos.types import AgentState, IntentMessage, IntentResult
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


class _DeliveringBus(_MockIntentBus):
    """A bus whose one handler confirms every broadcast with a successful result."""

    async def broadcast(self, intent: IntentMessage, timeout: float = 5.0) -> list:
        await super().broadcast(intent, timeout=timeout)
        return [IntentResult(intent_id=intent.id, agent_id="diagnostician", success=True)]


class _ScriptedBus(_MockIntentBus):
    """Answers each qualification broadcast from ``script``, then with ``default``; every other alert gets ``others``.

    The outcomes are the ones the real bus gives: ``ok`` (a successful result), ``empty`` (no result: a handler
    that outlived the timeout), ``failed`` (a failed result: a handler that raised) and ``raise`` (the bus itself).
    """

    def __init__(self, script: list[str], default: str = "ok", others: str = "ok") -> None:
        super().__init__()
        self._script = list(script)
        self._default = default
        self._others = others

    async def broadcast(self, intent: IntentMessage, timeout: float = 5.0) -> list:
        await super().broadcast(intent, timeout=timeout)
        if intent.params.get("metric") != _QUAL:
            outcome = self._others
        else:
            outcome = self._script.pop(0) if self._script else self._default
        if outcome == "raise":
            raise RuntimeError("bus closed")
        if outcome == "empty":
            return []
        return [IntentResult(intent_id=intent.id, agent_id="diagnostician", success=outcome == "ok")]


class _DiagnosticianBus(_MockIntentBus):
    """A bus whose one handler is a real Diagnostician: a broadcast gets that agent's own result."""

    def __init__(self, diagnostician: DiagnosticianAgent) -> None:
        super().__init__()
        self._diagnostician = diagnostician

    async def broadcast(self, intent: IntentMessage, timeout: float = 5.0) -> list:
        await super().broadcast(intent, timeout=timeout)
        result = await self._diagnostician.handle_intent(intent)
        return [result] if result is not None else []


class _ShortBus(IntentBus):
    """The real bus, with its broadcast timeout cut to 50 ms so that a slow handler times out inside a test."""

    def __init__(self) -> None:
        super().__init__(SignalManager())
        self.sent: list[IntentMessage] = []

    async def broadcast(self, intent: IntentMessage, timeout: float | None = None) -> list:
        if intent.params.get("metric") == _QUAL:
            self.sent.append(intent)
        return await super().broadcast(intent, timeout=0.05)


class _SlowFirstLLM:
    """A model whose first reply outlasts the short bus's timeout; every later reply is immediate."""

    def __init__(self) -> None:
        self.started = 0
        self.completed = 0
        self.client = MagicMock(complete=AsyncMock(side_effect=self._complete))

    async def _complete(self, *args: object, **kwargs: object) -> MagicMock:
        self.started += 1
        if self.started == 1:
            await asyncio.sleep(0.5)
        self.completed += 1
        return MagicMock(content=_DIAGNOSIS, tier="fast")


def _report(agent_id: str, ts: float, severity: str = "critical") -> DriftReport:
    return DriftReport(
        agent_id=agent_id, timestamp=ts, signals=[],
        overall_severity=severity, drift_detected=severity != "normal",
    )


def _healthy_runtime(scheduler: _Scheduler | None, bus: _MockIntentBus | IntentBus | None = None) -> _MockRuntime:
    runtime = _MockRuntime(
        pools={"filesystem": _MockPool("filesystem", 3, 3)},
        trust_scores={"a1": 0.8, "a2": 0.7},
        agents=[MagicMock(state=AgentState.ACTIVE, confidence=0.9) for _ in range(3)],
    )
    runtime._drift_scheduler = scheduler
    runtime.intent_bus = bus if bus is not None else _DeliveringBus()
    return runtime


async def _pulse(agent: VitalsMonitorAgent, runtime: _MockRuntime) -> list[IntentMessage]:
    """One heartbeat; the qualification alerts it sent."""
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
    runtime.intent_bus = _DeliveringBus()
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


@pytest.mark.parametrize("outcome", ["raise", "empty", "failed"])
async def test_an_alert_no_handler_confirmed_is_sent_again_on_the_next_heartbeat(outcome: str) -> None:
    runtime = _healthy_runtime(_Scheduler({"ag-1": _report("ag-1", 100.0)}), _ScriptedBus([outcome]))
    agent = VitalsMonitorAgent(pool="medical", runtime=runtime)

    assert [len(await _pulse(agent, runtime)) for _ in range(3)] == [1, 1, 0]


# -- T7: end to end -------------------------------------------------------------------


async def test_the_diagnostician_makes_one_llm_call_for_three_heartbeats() -> None:
    llm = MagicMock(complete=AsyncMock(return_value=MagicMock(content=_DIAGNOSIS, tier="fast")))
    diagnostician = DiagnosticianAgent(pool="medical", llm_client=llm)
    runtime = _healthy_runtime(
        _Scheduler({f"ag-{i}": _report(f"ag-{i}", 100.0 + i) for i in range(14)}),
        _DiagnosticianBus(diagnostician),
    )
    vitals = VitalsMonitorAgent(pool="medical", runtime=runtime)

    for _ in range(3):
        await vitals.collect_metrics()

    assert len(runtime.intent_bus.broadcast_calls) == 1
    assert llm.complete.await_count == 1


async def test_a_diagnosis_that_timed_out_on_the_real_bus_is_sent_again_and_completes() -> None:
    llm = _SlowFirstLLM()
    diagnostician = DiagnosticianAgent(pool="medical", llm_client=llm.client)
    bus = _ShortBus()
    bus.subscribe(diagnostician.id, diagnostician.handle_intent, ["medical_alert"])
    runtime = _healthy_runtime(_Scheduler({"ag-1": _report("ag-1", 100.0)}), bus)
    vitals = VitalsMonitorAgent(pool="medical", runtime=runtime)

    sent = []
    for _ in range(3):
        before = len(bus.sent)
        await vitals.collect_metrics()
        sent.append(len(bus.sent) - before)

    assert sent == [1, 1, 0]
    assert (llm.started, llm.completed) == (2, 1)


# -- T8: the bound --------------------------------------------------------------------


async def test_an_alert_that_is_never_confirmed_is_sent_three_times_and_then_used_up(caplog: pytest.LogCaptureFixture) -> None:
    runtime = _healthy_runtime(_Scheduler({"ag-1": _report("ag-1", 100.0)}), _ScriptedBus([], default="empty"))
    agent = VitalsMonitorAgent(pool="medical", runtime=runtime)

    with caplog.at_level("WARNING", logger="probos.agents.medical.vitals_monitor"):
        sent = [len(await _pulse(agent, runtime)) for _ in range(5)]

    assert sent == [1, 1, 1, 0, 0]
    used_up = [r for r in caplog.records if r.levelname == "WARNING" and "undelivered after 3 sends" in r.getMessage()]
    assert len(used_up) == 1


async def test_a_new_report_after_a_confirmed_retry_gets_three_fresh_sends() -> None:
    scheduler = _Scheduler({"ag-1": _report("ag-1", 100.0)})
    runtime = _healthy_runtime(scheduler, _ScriptedBus(["empty", "ok"], default="empty"))
    agent = VitalsMonitorAgent(pool="medical", runtime=runtime)

    sent = [len(await _pulse(agent, runtime)) for _ in range(2)]  # unconfirmed once, then confirmed
    scheduler.reports["ag-1"] = _report("ag-1", 200.0)  # a later run, critical again, never confirmed
    sent += [len(await _pulse(agent, runtime)) for _ in range(4)]

    assert sent == [1, 1, 1, 1, 1, 0]


async def test_the_count_starts_again_after_a_pulse_that_holds_no_critical_report() -> None:
    scheduler = _Scheduler({"ag-1": _report("ag-1", 100.0)})
    runtime = _healthy_runtime(scheduler, _ScriptedBus([], default="empty"))
    agent = VitalsMonitorAgent(pool="medical", runtime=runtime)

    sent = [len(await _pulse(agent, runtime))]  # unconfirmed once
    scheduler.reports = {}
    sent.append(len(await _pulse(agent, runtime)))  # nothing is held, nothing is sent
    scheduler.reports = {"ag-1": _report("ag-1", 200.0)}
    sent += [len(await _pulse(agent, runtime)) for _ in range(4)]

    assert sent == [1, 0, 1, 1, 1, 0]


async def test_a_new_report_right_after_a_used_up_alert_gets_three_fresh_sends() -> None:
    scheduler = _Scheduler({"ag-1": _report("ag-1", 100.0)})
    runtime = _healthy_runtime(scheduler, _ScriptedBus([], default="empty"))
    agent = VitalsMonitorAgent(pool="medical", runtime=runtime)

    sent = [len(await _pulse(agent, runtime)) for _ in range(3)]  # three sends, then used up
    scheduler.reports["ag-1"] = _report("ag-1", 200.0)
    sent += [len(await _pulse(agent, runtime)) for _ in range(4)]

    assert sent == [1, 1, 1, 1, 1, 1, 0]


async def test_an_unconfirmed_alert_of_another_kind_does_not_re_arm_the_qualification_alert() -> None:
    runtime = _MockRuntime(
        pools={"filesystem": _MockPool("filesystem", 3, 1)},
        trust_scores={"a1": 0.8, "a2": 0.7},
        agents=[MagicMock(state=AgentState.ACTIVE, confidence=0.9) for _ in range(3)],
    )
    runtime._drift_scheduler = _Scheduler({"ag-1": _report("ag-1", 100.0)})
    runtime.intent_bus = _ScriptedBus([], default="ok", others="empty")
    agent = VitalsMonitorAgent(pool="medical", runtime=runtime)

    for _ in range(3):
        await agent.collect_metrics()

    by_metric: dict[str, int] = {}
    for intent in runtime.intent_bus.broadcast_calls:
        by_metric[intent.params["metric"]] = by_metric.get(intent.params["metric"], 0) + 1
    assert by_metric == {"pool_health": 3, _QUAL: 1}
