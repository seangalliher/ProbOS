# BF-990 (#1839): the Vitals Monitor sends the qualification-drift alert once per new critical report, not on every heartbeat

**Drafted by:** `claude-architect` (Claude Code, Opus 5.5), 2026-11-20

**Amended by:** the orchestrator, 2026-11-20: first-hand verification of the premises, and the corrections listed in section 16 (the closing keyword; the memory's default moves to the class, because three existing tests build the agent without `__init__`). The Architect's text is otherwise unchanged.

**Status:** build-ready. Issue #1839 is wholly settled by this contract (the PR says `Refs #1839`; the orchestrator closes the issue after the merge, with its closure verified). One BF number. BF-990 appears only in REPLACE text, the new file's path and text, and tracker text, never in a SEARCH.

**Base:** BF-988's branch at `fc9b9a6f` (base `cc601a72`). `vitals_monitor.py`, `diagnostician.py`, `drift_detector.py` and `tests/test_medical_team.py` are identical to `origin/main` there. The only anchor that depends on BF-988 is the DECISIONS SEARCH (7.4). Commit BF-990 before BF-988's round-1 repair.

**Line endings:** the working copies are CRLF and the SEARCH blocks are LF. Match and write each file with its own line endings. Write the new file with LF.

**Milestones:**
- M1: the new test file first (red), then `vitals_monitor.py` (green). Tier LOW.
- M2: the trackers and the generated ledger pair.

Each milestone is one Builder delegation and one local commit. One broad gate covers the batch with BF-988 (section 8).

**Captain:** no condition is met. This is an internal change to when an existing alert fires. It changes no schema, security or governance control, spend authority, OSS/commercial boundary or product objective, and it reduces LLM spend.

---

## 0. Premises (re-verified on `fc9b9a6f`)

| Fact | Where |
|---|---|
| The agent's constructor has no alert memory; `interval=5.0` | `src/probos/agents/medical/vitals_monitor.py:49-56` |
| `collect_metrics` reads `_drift_scheduler.latest_reports` and sets the warning count, the critical count and `last_run_time` | `:176-190` |
| `collect_metrics` appends `metrics` to `_window`, then `await self._check_thresholds(metrics, rt)` | `:199`, `:202` |
| `scan_now` checks no threshold and puts `list(self._window)` into `recent_history` | `:206-272` (`:270`) |
| The qualification alert fires on every call while the count is above 0 | `:345-356` |
| Every alert is broadcast; an exception is logged at debug and swallowed | `:358-367` |
| `DriftReport(agent_id, timestamp, signals, overall_severity, drift_detected)` is frozen, with `timestamp=time.time()` at build | `drift_detector.py:48-56`, `:112-115` |
| The scheduler's cache is in memory only. `__crew__` reports are written at `:355`, then `await analyze_all_agents` at `:362`, then agent reports at `:366`, then `_last_run_time` at `:370`. `run_now` has the same shape (`:412`, `:419-425`) | `drift_detector.py:280`, `:316-426` |
| `latest_reports` returns a copy | `drift_detector.py:433-436` |
| `medical_alert` subscriber: the Diagnostician | `diagnostician.py:59` |
| The decision cache is off by default | `cognitive_agent.py:13111-13126`; `config.py:766` |
| BF-879 (`:58-99`) changed which agents count as trust outliers and added no edge: its docstring says "the alert repeats on every heartbeat" (`:84-85`) | `vitals_monitor.py:58-99` |
| Test doubles: `_MockPool`, `_MockTrustNetwork`, `_MockIntentBus` (`broadcast_calls`), `_MockRuntime` (plain class, no `_drift_scheduler`, no `llm_client`) | `tests/test_medical_team.py:37-102` |
| A test module may import doubles from another | `tests/test_bf988_llm_response_text.py` (this branch); `tests/test_ad1207_fault_visibility.py:746` |
| `asyncio_mode = "auto"` | `pyproject.toml:181` |

**Readers of `metrics`, enumerated:**
- `_window`, exposed through `window` (`:370-372`), `latest_vitals` (`:378-383`) and `vitals_window` (`:385-388`).
- `latest_vitals` is read by `proactive.py:408`, which takes only named keys (`:414-434`).
- `scan_now`'s `recent_history` is JSON-dumped into the Diagnostician's `diagnose_system` LLM context (`diagnostician.py:100-104`).
- `HeartbeatAgent._last_metrics` is used by `report()` and `info()` (`substrate/heartbeat.py:71`, `:118-124`).

A key added to `metrics` therefore reaches an LLM prompt and `info()` (D2).

## 1. Problem

While any `DriftReport` held by the scheduler is critical, every 5-second pulse appends a `qualification_drift` alert (`:345-356`) and broadcasts it (`:358-365`). The Diagnostician makes one LLM call for each. The report is held until the next drift run: a week, a `qualification run`, or a restart.

Measured on `fc9b9a6f` (#1839, probe `probe_vitals_diag.py`) with 14 critical agents:
- 3 heartbeats gave 3 alerts and 3 LLM calls.
- The no-report and warning-only controls gave 0 alerts.

BF-988 can make this state ordinary: a first measured recall score gives a critical signal for each agent with nine or more stored 0.5 results.

## 2. Solution overview

Remember on the agent which critical reports, as `(agent_id, report.timestamp)`, the last pulse held. Send the `qualification_drift` alert only when the current set holds a pair the last pulse did not. The memory is replaced with the current set on every pulse, so a set that empties re-arms the alert. An alert whose broadcast raised restores the previous memory, so the next pulse retries it.

The pair set is computed in `collect_metrics` from the same `_reports` snapshot as the counts. It is passed to `_check_thresholds` as a keyword-only argument and never placed in `metrics`. The alert's params keep their keys and meaning. `current_value` stays the total critical count, which equals the existing metric.

Rejected designs (one line each):
- **Key on `last_run_time` (option a).** It re-alerts for unchanged stale reports after a partial `run_now([one agent])`. It can alert twice per run anyway, because the `__crew__` batch is written before `_last_run_time`.
- **Key on agent ids only (option c).** A later week that holds the same agents critical never alerts again.
- **A time cooldown, as in `BridgeAlertService._should_emit` (`bridge_alerts.py:102-113`).** It still repeats an unchanged condition (288 a day at 300 s), and report identity is available.
- **An edge for all alert types.** Out of scope (#1839, item 2). The other alerts are transient, while this one is held for a week by construction.
- **Pair keys in `metrics`.** They would reach the Diagnostician's prompt and `info()` (D2).
- **Reading the scheduler a second time inside `_check_thresholds`.** It is a second snapshot that could disagree with the counts. Explicit injection is clearer.

## 3. Decisions

**D1: the edge is option (b), keyed on `(agent_id, report.timestamp)` for critical reports.** The rule is `new = held_now - held_last_pulse`, alert iff `new` is non-empty, and then `held_last_pulse = held_now`.

| Case | Behaviour |
|---|---|
| A later run (weekly or `run_now`) builds a new critical report for an agent already critical | Its timestamp differs, so it alerts again (a new week alerts) |
| A partial `run_now([x])` that makes `x` newly critical | One alert. `current_value` is the total critical count, as today |
| The set empties (no critical report, empty cache, or no scheduler), then refills | Alerts again, even if the same report object returns. The memory is replaced every pulse, so an empty pulse clears it |
| The scheduler is absent | `held_now` is empty: no alert, and the memory clears |
| `__crew__` and agents both turn critical in one run | At most two alerts per run, because the `__crew__` batch is written before the `await` at `drift_detector.py:362` and a pulse can fall between the batches. Each alert reports a genuinely new critical report. The bound is accepted and recorded |
| The broadcast of the qualification alert raises | The memory is restored to its previous value, so the next pulse retries. Without this, the edge would turn a transient bus error into a week of silence |
| `rt is None` (`:110`) | `_check_thresholds` is not reached, as today. The memory is unchanged |
| The Vitals agent is respawned while the scheduler persists | The new instance alerts once for the held reports. That is one alert per incarnation, and it is accepted |

`report.timestamp` identifies a generation. It is `time.time()` at build (`drift_detector.py:114`), and two runs over one agent are seconds to weeks apart. `id(report)` was rejected because ids are reused after GC. A `DriftReport` itself is unhashable because `signals` is a list.

**D2: where the memory lives and what `metrics` gains.**
- The memory is `_critical_drift_held: frozenset[tuple[str, float]]` on the agent, in memory only like the scheduler cache it mirrors. A restart clears both. Its default is a class-level `frozenset()` (replaced per instance on the first pulse, never mutated): an agent built without `__init__` reads it too (A4).
- `metrics` gains nothing. Its readers (section 0) include the Diagnostician's LLM context through `recent_history`, and `info()`.
- `_check_thresholds` gains a keyword-only `critical_drift: frozenset[tuple[str, float]] = frozenset()`. Its three direct callers in `tests/test_bf069_llm_health.py:218,255,285` pass `(metrics, rt)` on an agent built with `VitalsMonitorAgent.__new__` (`:199`, `:230`, `:266`), so they stay unedited only because the memory has a class-level default (A4). Its `AsyncMock` replacement at `:188` accepts the keyword.
- The qualification alert's predicate and `current_value` derive from `critical_drift`. A direct call without the keyword therefore sends no qualification alert even if `metrics` holds a count. No `src` caller does this (AV3).

**D3: tests.** The new file is `tests/test_bf990_qualification_drift_alert_edge.py`. It drives the real `VitalsMonitorAgent.collect_metrics` over `_MockRuntime` plus a scheduler double holding real `DriftReport`s, and a real `DiagnosticianAgent` over a counting LLM double. Its red states are in section 6. The inline copy at `tests/test_ad566c_drift_detection.py:717-760` is left as it is; the new file is the first real-path test.

**D4: mutation rows.** See section 10.

**D5: trackers.** One PROGRESS entry and one DECISIONS entry. The ledger pair is generated. No roadmap row, because the Bug Tracker lists only bugs deliberately not fixed.

**D6: who decides.** The Architect. None of the six conditions applies:
- No security, governance or audit control is weakened. `medical_alert` is advisory input to the Diagnostician, and the Bridge's own drift alert (`bridge_alerts.py:795-816`) is untouched.
- No schema or persisted data changes.
- No spend authority is widened; spend falls.
- No OSS/commercial boundary is crossed.
- No product objective or feature is switched on or off.
- No authority ceiling or approval rule changes.

## 4. Milestones and focused gates

- **M1.** Write 7.1. Record it red against the base (P2). Then apply 7.2.
  - Focused gate: `pytest tests/test_bf990_qualification_drift_alert_edge.py tests/test_medical_team.py tests/test_bf069_llm_health.py tests/test_diagnostician.py tests/test_bf879_designed_agents_start_probationary.py tests/test_ad566c_drift_detection.py tests/test_public_apis.py -q -n 0`.
- **M2.** 7.3, 7.4 and 7.5. Then `pytest tests/test_ad1184_ad_ledger.py -q -n 0`.

## 5. Consumers of every value this changes

| Value | Consumers | Effect |
|---|---|---|
| The count of `medical_alert` intents with `metric == "qualification_drift"` | `DiagnosticianAgent` (`diagnostician.py:59`) -> `decide()` -> LLM | One per new critical report instead of one per 5 s |
| `_check_thresholds`'s signature | `vitals_monitor.py:202`; `tests/test_bf069_llm_health.py:188,218,255,285` | Additive keyword-only argument with a default |
| `metrics` | window, `latest_vitals`, `scan_now`, `info()` | Unchanged keys and values |

## 6. Tests (`tests/test_bf990_qualification_drift_alert_edge.py`)

| Test | Asserts | Red on base? |
|---|---|---|
| T1 | 1 and 14 critical agents, three pulses: qualification alerts per pulse `[1, 0, 0]`; the params are exactly the base's keys; `current_value` equals `metrics["qualification_drift_critical_count"]` | yes (`[1, 1, 1]`) |
| T2 | A new report generation alerts again (`[1, 0, 1]`). A second agent turning critical while the first is held alerts with `current_value == 2` | yes |
| T3 | Re-arm after a gap (`empty-reports`, `no-scheduler`, `warning-replaces`), with the same report object restored: `[1, 0, 1]` | no (it guards against the edge's mutations) |
| T4 | `no-scheduler`, `empty-reports`, `warning-only`, `normal-only`: `[0, 0, 0]` | no |
| T5 | Pool, trust, system and LLM alerts each fire on all three pulses; qualification fires once | yes (qualification 3) |
| T6 | A qualification broadcast that raises is retried on the next pulse and then not again: delivered `[0, 1, 0]` | yes (`[0, 1, 1]`) |
| T7 | A real Diagnostician over a counting double: three pulses give one LLM call | yes (3) |

## 7. The contract

### 7.1 New file: `tests/test_bf990_qualification_drift_alert_edge.py` (M1)

```python
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
```

### 7.2 `src/probos/agents/medical/vitals_monitor.py` (M1, five pairs in file order; the first as amended in section 16)

SEARCH:
```python
    initial_confidence = 0.95
```
REPLACE:
```python
    initial_confidence = 0.95
    # BF-990 (#1839): the critical drift reports, as (agent_id, report timestamp), that the last pulse held.
    # In memory only, like the drift scheduler's cache it mirrors. A class-level default: the value is replaced,
    # never mutated, and an agent built without __init__ (tests/test_bf069_llm_health.py) reads it too.
    _critical_drift_held: frozenset[tuple[str, float]] = frozenset()
```

SEARCH:
```python
        # AD-566c: Qualification drift metrics
        _drift_scheduler = getattr(rt, "_drift_scheduler", None)
        if _drift_scheduler:
            _reports = _drift_scheduler.latest_reports
            if _reports:
```
REPLACE:
```python
        # AD-566c: Qualification drift metrics
        # BF-990 (#1839): each critical report's identity, for the alert's edge. Kept out of
        # ``metrics``: the window reaches the Diagnostician's LLM context (``scan_now``'s
        # ``recent_history``) and ``info()``.
        critical_drift: frozenset[tuple[str, float]] = frozenset()
        _drift_scheduler = getattr(rt, "_drift_scheduler", None)
        if _drift_scheduler:
            _reports = _drift_scheduler.latest_reports
            if _reports:
                critical_drift = frozenset(
                    (r.agent_id, r.timestamp)
                    for r in _reports.values() if r.overall_severity == "critical"
                )
```

SEARCH:
```python
        # Check thresholds and emit alerts
        await self._check_thresholds(metrics, rt)

        return metrics
```
REPLACE:
```python
        # Check thresholds and emit alerts
        await self._check_thresholds(metrics, rt, critical_drift=critical_drift)

        return metrics
```

SEARCH:
```python
    async def _check_thresholds(self, metrics: dict[str, Any], rt: Any) -> None:
        """Check metrics against thresholds and broadcast alerts if breached."""
        alerts: list[dict[str, Any]] = []
```
REPLACE:
```python
    async def _check_thresholds(
        self,
        metrics: dict[str, Any],
        rt: Any,
        *,
        critical_drift: frozenset[tuple[str, float]] = frozenset(),
    ) -> None:
        """Check metrics against thresholds and broadcast alerts if breached.

        Every alert repeats on each pulse while its condition holds, except the qualification
        drift alert (BF-990, #1839): ``critical_drift`` is the set of critical reports held now,
        as ``(agent_id, report timestamp)``, and that alert fires only when it holds one the last
        pulse did not.
        """
        alerts: list[dict[str, Any]] = []
```

SEARCH:
```python
        # AD-566c: Qualification drift critical alert
        drift_critical = metrics.get("qualification_drift_critical_count", 0)
        if drift_critical > 0:
            alerts.append({
                "severity": "warning",
                "metric": "qualification_drift",
                "current_value": drift_critical,
                "threshold": 0,
                "affected": "qualification",
                "alert": f"{drift_critical} agent(s) showing critical qualification drift",
                "timestamp": metrics["timestamp"],
            })

        # Broadcast alerts via intent bus
        for alert_data in alerts:
            intent = IntentMessage(
                intent="medical_alert",
                params=alert_data,
            )
            try:
                await rt.intent_bus.broadcast(intent, timeout=5.0)
            except Exception as e:
                logger.debug("Failed to broadcast medical alert: %s", e)
```
REPLACE:
```python
        # AD-566c: Qualification drift critical alert.
        # BF-990 (#1839): edge-triggered. The drift scheduler holds each report until its next run
        # (weekly), so a level check sent this alert on every pulse and the Diagnostician spent an
        # LLM call on each. It fires when a critical report appears that the last pulse did not
        # hold. The memory is replaced on every pulse, so a pulse holding none re-arms it.
        previous_drift = self._critical_drift_held
        self._critical_drift_held = critical_drift
        if critical_drift - previous_drift:
            drift_critical = len(critical_drift)
            alerts.append({
                "severity": "warning",
                "metric": "qualification_drift",
                "current_value": drift_critical,
                "threshold": 0,
                "affected": "qualification",
                "alert": f"{drift_critical} agent(s) showing critical qualification drift",
                "timestamp": metrics["timestamp"],
            })

        # Broadcast alerts via intent bus
        for alert_data in alerts:
            intent = IntentMessage(
                intent="medical_alert",
                params=alert_data,
            )
            try:
                await rt.intent_bus.broadcast(intent, timeout=5.0)
            except Exception as e:
                logger.debug("Failed to broadcast medical alert: %s", e)
                if alert_data["metric"] == "qualification_drift":
                    # BF-990: an edge alert that was not sent re-arms, so the next pulse retries it.
                    self._critical_drift_held = previous_drift
```

### 7.3 `PROGRESS.md` (M2)

SEARCH:
```markdown
# ProbOS Progress
```
REPLACE:
```markdown
# ProbOS Progress

**BF-990 (2026-11-20), #1839 -- the Vitals Monitor sends the qualification-drift alert once per new critical report, not on every heartbeat.** `DriftScheduler` holds each agent's latest `DriftReport` in memory until its next run (weekly, or `qualification run`), and `VitalsMonitorAgent._check_thresholds` sent a `qualification_drift` `medical_alert` on every 5 s pulse while any held report was critical; the Diagnostician made one LLM call per alert (measured: 14 critical agents, 3 heartbeats, 3 alerts, 3 calls). The alert is now edge-triggered on the set of critical reports as `(agent_id, report timestamp)`: it fires when the set holds a report the last pulse did not (a later run alerts again), a pulse holding none re-arms it, and an alert whose broadcast raised is retried on the next pulse. The identities are passed to `_check_thresholds` as a keyword argument and kept out of `metrics`, whose window reaches the Diagnostician's LLM context. Params, severity and `current_value` (the total critical count) are unchanged; the pool, trust, system and LLM alerts still fire on every pulse. Lands with BF-988, whose first measured recall scores can make critical drift ordinary. New `tests/test_bf990_qualification_drift_alert_edge.py`. Contract `prompts/bf-990-qualification-drift-alert-edge.md`.
```

### 7.4 `DECISIONS.md` (M2)

SEARCH:
```markdown
### BF-988 -- #1523 F-19: an LLM reply's text is read through one reader; guided reminiscence never takes a response's repr as its text (2026-11-20, #1523)
```
REPLACE:
```markdown
### BF-990 -- The qualification-drift medical alert is edge-triggered on the critical reports' identities (2026-11-20, #1839)

- *Mechanism.* The drift scheduler's in-memory `latest_reports` holds each critical `DriftReport` for a week; `VitalsMonitorAgent._check_thresholds` re-sent the `qualification_drift` `medical_alert` on every 5 s pulse, and each cost the Diagnostician an LLM call (decision cache off by default).
- *Repair.* `collect_metrics` builds `frozenset((agent_id, report.timestamp))` of critical reports from the same snapshot as the counts and passes it to `_check_thresholds(..., critical_drift=...)`. The agent keeps the last pulse's set in `_critical_drift_held` (memory only); the alert fires iff the current set holds a pair the last did not; the memory is replaced every pulse (an empty pulse re-arms); a failed broadcast restores the previous memory (retried next pulse).
- *Why this key.* Agent ids alone miss a later week; `last_run_time` re-alerts stale reports after a partial `run_now`; a cooldown still repeats an unchanged condition. Bound accepted: a pulse falling between the `__crew__` batch and the agent batch of one run can give two alerts for that run.
- *Not in `metrics`.* The window reaches the Diagnostician's `diagnose_system` LLM context via `scan_now`'s `recent_history`, and `info()`.
- *Scope.* Pool, trust (BF-879 added no edge), system and LLM alerts stay level-triggered by design.
- *Decided by the Architect.* None of the six conditions is met: an advisory alert's timing; less spend; no schema, control, boundary or objective.
- *Reversal.* Revert the BF-990 commits.

### BF-988 -- #1523 F-19: an LLM reply's text is read through one reader; guided reminiscence never takes a response's repr as its text (2026-11-20, #1523)
```

If BF-988's repair has already changed that heading, insert the BF-990 entry directly above the first `### ` entry heading below line 1660 instead, and record the anchor used in the commit message.

### 7.5 Generated: the ledger pair (M2)

Run `d:/ProbOS/.venv/Scripts/python.exe -P scripts/gen_ad_ledger.py`. Commit `docs/development/open-ads-report.md` and `docs/development/ad-ledger-snapshot.json`; do not paste them. Verify with `--check` and `tests/test_ad1184_ad_ledger.py`. If BF-988's later repair also regenerates the pair, its regeneration supersedes this one.

## 8. Batch, gate and closure (the orchestrator; nothing here edits GitHub)

BF-990 goes on BF-988's branch, as its own M1 and M2 commits after BF-988's M2 and before BF-988's round-1 repair. It has its own focused check and Diff Reviewer round.
- One broad gate for the batch: `d:/ProbOS/.venv/Scripts/python.exe scripts/run_test_gate.py --label bf-988-990 --receipt logs/gates/bf-988-990.receipt.json`.
- One PR: `Refs #1523`, `Refs #1839`. The orchestrator closes #1839 after the merge, with its closure verified.
- If BF-988 parks, cherry-pick the BF-990 commits onto `origin/main`. Re-anchor 7.4 to the then-first `### ` heading and regenerate the ledger. BF-990 then ships alone under its own gate.

Comment on #1839 at merge (and then close it, with the closure verified):

> Fixed by BF-990 (PR #...). The qualification-drift `medical_alert` now fires once per new critical drift report (keyed on agent and report timestamp), not on every 5 s heartbeat; a later drift run alerts again, a pulse with no critical report re-arms it, and a failed send is retried. The other Vitals alerts are unchanged. Measured before: 3 heartbeats, 3 alerts, 3 Diagnostician LLM calls; after: 1 and 1 (T7).

## 9. What this does NOT change

- The pool-health, trust-outlier, system-health and LLM-health alerts, which stay level-triggered.
- `metrics` keys and values, `scan_now`, the window, `latest_vitals` and `info()`.
- `DriftScheduler`, `DriftReport`, `BridgeAlertService.check_qualification_drift` and the `QUALIFICATION_DRIFT_DETECTED` event.
- The Diagnostician and the decision cache.
- `tests/test_ad566c_drift_detection.py:717-760` (the inline copy), `tests/test_medical_team.py` and `tests/test_bf069_llm_health.py`, none of them edited.
- Config, `EventType`, routes, tables, flags and stored data: none added or changed.

## 10. Mutation rows (one campaign; restore between rows; run only the listed killers)

Record the base tree and the sha256 of `vitals_monitor.py`. That is the campaign of record; rerun a row only if the file differs.

| # | Site | Mutate to | Killed by |
|---|---|---|---|
| R-1 | `if critical_drift - previous_drift:` | `if critical_drift:` (edge removed) | T1, T2, T5, T6, T7 |
| R-2 | comprehension `(r.agent_id, r.timestamp)` | `(r.agent_id, 0.0)` (agent id only) | T2 |
| R-3 | `self._critical_drift_held = critical_drift` | `self._critical_drift_held = previous_drift \| critical_drift` (never cleared) | T3 (all three) |
| R-4 | same line | `if critical_drift: self._critical_drift_held = critical_drift` (kept while empty) | T3 (all three) |
| R-5 | `for alert_data in alerts:` | wrapped in `if not critical_drift or critical_drift - previous_drift:` (the edge swallows the others) | T5 |
| R-6 | the except branch's restore | removed | T6 |
| R-7 | comprehension `== "critical"` | `in ("warning", "critical")` | T4[warning-only] |
| R-8 | the `_critical_drift_held = critical_drift` line | moved above `previous_drift = ...` | T1, T2, T7 |
| R-9 | `drift_critical = len(critical_drift)` | `len(critical_drift - previous_drift)` | T2 (`current_value == 2`) |
| R-10 | the class-level `_critical_drift_held` default (A4) | removed (the memory is set in `__init__` only, the Architect's first form) | `tests/test_bf069_llm_health.py` (the three `_check_thresholds` cases) |

## 11. Verified Against Codebase (2026-11-20, `fc9b9a6f`)

```
vitals_monitor.py:49-56 __init__ (interval=5.0; _window; _max_trust_outliers at :56) ; :58 def _trust_outliers ; :84-85 "the alert repeats on every heartbeat"
vitals_monitor.py:101 collect_metrics ; :110-111 rt None return ; :176-190 drift block ; :199 _window.append ; :201-202 _check_thresholds(metrics, rt) ; :204 return metrics
vitals_monitor.py:206-272 scan_now (:270 recent_history = list(self._window)) ; :274-276 _check_thresholds ; :345-356 qualification alert ; :358-367 broadcast loop ; :370-388 window/latest_vitals/vitals_window
drift_detector.py:48-56 DriftReport (frozen; signals: list) ; :112-115 DriftReport(... timestamp=time.time()) ; :280 _latest_reports ; :355 crew write ; :362 await analyze ; :366 agent write ; :370 _last_run_time ; :412, :419-425 run_now ; :433-436 latest_reports copy
diagnostician.py:59 _handled_intents ; :100-104 scan_now -> json.dumps into context
substrate/heartbeat.py:71 _last_metrics = metrics ; :118-124 report()/info()
proactive.py:408 agent.latest_vitals ; :414-434 named keys only
bridge_alerts.py:102-113 _should_emit cooldown ; :795-816 check_qualification_drift
cognitive_agent.py:361 _DECISION_CACHES ; :13111-13126 _decision_cache_enabled default False
tests/test_medical_team.py:24-30 cache fixture ; :37 _MockPool ; :48 _MockTrustNetwork ; :78-84 _MockIntentBus ; :87-102 _MockRuntime ; :184-194 Diagnostician over MagicMock(complete=AsyncMock)
tests/test_bf069_llm_health.py:188 _check_thresholds = AsyncMock() ; :218, :255, :285 _check_thresholds(metrics, rt)
tests/test_ad566c_drift_detection.py:717-760 inline copy ; pyproject.toml:181 asyncio_mode = "auto"
PROGRESS.md:1 # ProbOS Progress ; DECISIONS.md:1661 ### BF-988 -- ... (once)
```

## Absence Verified (2026-11-20)

| | CLAIM | RUN | FOUND | HOLDS |
|---|---|---|---|---|
| AV1 | `medical_alert` has no subscriber besides the Diagnostician | `rg medical_alert src/probos` (count) | `vitals_monitor.py` 4, `diagnostician.py` 3 | yes |
| AV2 | Nothing in `src` reads `qualification_drift_*_count` | `rg 'qualification_drift_\|qualification_last_check' src` | `vitals_monitor.py:187-189,346`. `bridge_alerts.py:813,834` are `alert_type` strings; `counselor.py:1515,1532-1534` are trigger strings | yes |
| AV3 | No `src` caller of `_check_thresholds` besides `:202` | `rg _check_thresholds` | `vitals_monitor.py:202,274`; tests `test_bf069_llm_health.py` only | yes |
| AV4 | No test pins the per-pulse repetition or scans `vitals_monitor.py` source | `rg 'qualification_drift_critical_count\|qualification_drift"' tests`; `rg 'vitals_monitor\.py\|getsource\(.*vitals' tests` | only the `test_ad566c` inline copy (`:745`, `:749`) and `test_bf923:69` (unrelated parametrize); no source scan | yes |
| AV5 | `_critical_drift_held` and `critical_drift` are free names | `rg '_critical_drift_held\|critical_drift\b'` | `test_ad566c` and an archived prompt (as `drift_critical`-style text), not in `src` | yes |
| AV6 | BF-990 is free and held by #1839 | `git log --all -E -i --grep=BF-99[0-9]`: none. Glob `prompts/bf-9[89]*.md`: highest `bf-988`. `gh issue list --search "BF-990 in:title"`: #1839 only. `rg BF-99\d` *.md: only a "BF-985 to BF-992" search range in `prompts/bf-985-*.md:6` | as stated | yes |

## 12. Premises to verify first-hand before building

| P | Premise | Probe |
|---|---|---|
| P1 | BF-990 is free | Re-run AV6 |
| P2 | Red first | With only 7.1 added, T1, T2, T5, T6 and T7 fail with the base counts in section 6, and T3 and T4 pass. Record the times and `vitals_monitor.py`'s sha256 |
| P3 | Each SEARCH matches once | `rg -c` the first distinctive line of each of the seven blocks (five in 7.2, one each in 7.3 and 7.4) |
| P4 | Cross-module import | `python -c "import tests.test_medical_team"` from the repo root |
| P5 | The Diagnostician makes one LLM call per alert on base | T7 on base reports `await_count == 3` with 3 broadcasts |

## 13. Prior art and blind spots

- **Internal.**
  - `BridgeAlertService._should_emit` (`bridge_alerts.py:102-113`) dedups with a 300 s cooldown. It was adapted as a rejected alternative: report identity is available, and a cooldown still repeats.
  - BF-879 changed trust-outlier membership and added no edge.
  - AD-566c defined the alert.
- **External.** No search was made. This is a bug fix of ProbOS-specific plumbing, and edge-versus-level alerting is a settled pattern: alerting on a state transition (identity-keyed dedup) rather than on condition presence.
- **Blind spots, recorded.**
  - The two-batch window (D1).
  - The respawned-agent alert (D1).
  - `__crew__` counts as an "agent" in `current_value`, as before.
  - A failed broadcast is still logged at debug only (unchanged).
  - The inline copy in `test_ad566c` still does not exercise the real path (T1 now does).

## 14. Diff Reviewer: properties to verify

1. Only the qualification alert's predicate changed. The other four alert blocks and their params are byte-identical, and every alert still goes through the one broadcast loop.
2. `_critical_drift_held` is replaced on every `_check_thresholds` call, including with an empty set, and is restored only in the except branch, only for the qualification alert.
3. `critical_drift` is built from the same `_reports` snapshot as the counts, and no new key enters `metrics`.
4. The new keyword argument is keyword-only, has a default, and does not break the `tests/test_bf069_llm_health.py` call sites, whose agents are built with `__new__`: the class-level default of `_critical_drift_held` serves them.
5. The tests drive the real `collect_metrics` and a real `DiagnosticianAgent`, and T5 asserts that the four other alert types fire on all three pulses.
6. One PROGRESS entry and one DECISIONS entry are added, and the ledger pair is generated.

## 15. Acceptance criteria

1. Three heartbeats over one unchanged critical report give one `qualification_drift` alert and one Diagnostician LLM call (T1, T7).
2. A new report generation alerts again; a set that empties and refills alerts again; warning-only, normal-only, an empty cache and no scheduler alert never (T2, T3, T4).
3. The pool, trust, system and LLM alerts fire on every heartbeat as before (T5). A failed send is retried once (T6).
4. Every section 10 row is killed by its named tests, and T1, T2, T5, T6 and T7 were recorded red first (P2).
5. One broad gate and one PR batched with BF-988 (section 8). The #1839 comment is posted after the merge.
6. Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## 16. Orchestrator verification (2026-11-20)

Each premise below was run first-hand on `fc9b9a6f` (base `cc601a72`; `vitals_monitor.py`, `diagnostician.py`, `drift_detector.py` and `tests/test_medical_team.py` equal `origin/main` there), with a probe that asserts its own premise before it reports. All agree with the Architect's text except where an amendment is named.

| Premise | Result |
|---|---|
| P1: BF-990 is free and held by #1839 | `git log --all` subjects and bodies (highest BF-986), `prompts/bf-*.md` (highest `bf-988`), GitHub issue titles in all states (BF-989 is #1838, BF-990 is #1839, filed 06:02Z), the trackers and the roadmap (no BF-99x). |
| The measurement of #1839 | The real `VitalsMonitorAgent.collect_metrics` over the test suite's `_MockRuntime` with a drift scheduler double holding 14 critical `DriftReport`s: 3 heartbeats gave 3 `qualification_drift` alerts, and a real `DiagnosticianAgent` over a counting LLM double made 3 calls for the 3 alerts (the decision cache is off by default; the same alerts with the timestamp removed also made 3 calls). Controls with no report and with a warning-only report: 0 alerts. |
| P2: red first | With only 7.1 written into a scratch tree of `fc9b9a6f`: 6 failed (T1 for 1 and for 14 agents, T2, T5, T6, T7) and 7 passed (T3 for its three gaps, T4 for its four holds), as section 6 says. |
| P3: each SEARCH matches once | The apply tool applied the five pairs of 7.2, as amended below, with 0 failures. |
| **Amendment A4/A5: the memory's default lives on the class** | The Architect put `self._critical_drift_held = frozenset()` in `__init__` and said the three direct callers of `_check_thresholds` in `tests/test_bf069_llm_health.py` (`:218`, `:255`, `:285`) "are unaffected". They are not: those tests build the agent with `VitalsMonitorAgent.__new__(VitalsMonitorAgent)` (`:199`, `:230`, `:266`), set five attributes and call `_check_thresholds(metrics, rt)`. With the `__init__` form, the focused check failed three cases with `AttributeError: 'VitalsMonitorAgent' object has no attribute '_critical_drift_held'`. The first pair of 7.2 is therefore a class-level default (`_critical_drift_held: frozenset[tuple[str, float]] = frozenset()` after `initial_confidence`), which the instance replaces and nothing mutates; the three tests stay unedited. Mutation row R-10 pins it. |
| Closing keyword | The PR says `Refs #1839`, as the repository's practice is: the orchestrator closes the issue after the merge and verifies the closure. |
| P5: the Diagnostician makes one LLM call per alert on the base | T7 on the base reports 3 broadcasts and `await_count == 3`. |
| Batching | The Architect's answer (consult `624994ca`): one branch, one pull request, one gate (`bf-988-990`); BF-990 keeps its own milestones, focused check, review round and commits, after BF-988's M2 and before BF-988's repair. |

## For the register (#1839)

- **R-1.** A pulse that falls between the `__crew__` batch and the agents' batch of one drift run can give two alerts for that run (D1). Bounded, accepted.
- **R-2.** The other level-triggered alerts (pool health, trust outliers, system health, LLM proxy) still repeat on every pulse and cost the Diagnostician a call each while their condition holds. Transient by nature; not changed here.
- **R-3.** A respawned Vitals agent alerts once for the reports the scheduler still holds (D1). Accepted.
