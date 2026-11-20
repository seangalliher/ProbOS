# BF-990 (#1839): the Vitals Monitor sends the qualification-drift alert once per new critical report, not on every heartbeat

**Drafted by:** `claude-architect` (Claude Code, Opus 5.5), 2026-11-20

**Amended by:** the orchestrator, 2026-11-20: first-hand verification of the premises, and the corrections listed in section 16 (the closing keyword; the memory's default moves to the class, because three existing tests build the agent without `__init__`). After review round 1, Amendment A1 (section 17; decided by the Architect in consult `17e90eda`) repairs its three findings; its corrections are also made in place in sections 0, 2, 3, 5, 6, 7.1, 7.2, 7.3, 7.4, 8, 9, 10, 12, 14, 15 and 16. The Architect's text is otherwise unchanged.

**Status:** build-ready. Issue #1839 is wholly settled by this contract (the PR says `Refs #1839`; the orchestrator closes the issue after the merge, with its closure verified). One BF number. BF-990 appears only in REPLACE text, the new file's path and text, and tracker text, never in a SEARCH.

**Base:** BF-988's branch at `fc9b9a6f` (base `cc601a72`). `vitals_monitor.py`, `diagnostician.py`, `drift_detector.py` and `tests/test_medical_team.py` are identical to `origin/main` there. The only anchor that depends on BF-988 is the DECISIONS SEARCH (7.4). Commit BF-990 before BF-988's round-1 repair.

**Line endings:** the working copies are CRLF and the SEARCH blocks are LF. Match and write each file with its own line endings. Write the new file with LF.

**Milestones:**
- M1: the new test file first (red), then `vitals_monitor.py` (green). Tier LOW.
- M2: the trackers and the generated ledger pair.
- A1 (after review round 1): the pairs of section 17, one Builder delegation; one local commit for the source and tests, one for the trackers and the regenerated ledger pair.

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
| `IntentBus.broadcast` raises only for its own faults. It returns `[]` for a handler cancelled at the timeout, a closed bus, a denied intent and a handler that declined; a handler that raised comes back as `IntentResult(success=False)`; a federation peer's results are added | `mesh/intent.py:1355`, `:1368`, `:1479-1495`, `:1524`, `:1823-1905` |
| `_MockIntentBus.broadcast` returns `[]`: a rule that reads the results needs a bus that returns a successful one | `tests/test_medical_team.py:78-84` |
| `/diagnostic` hands the Diagnostician an `IntentMessage`, and `DiagnosticianAgent.perceive` calls `.get` on it: the on-demand path fails before it reads the window (BF-991, #1840) | `commands_diagnostic.py:65-69`, `diagnostician.py:83` |
| The decision cache is off by default | `cognitive_agent.py:13111-13126`; `config.py:766` |
| BF-879 (`:58-99`) changed which agents count as trust outliers and added no edge: its docstring says "the alert repeats on every heartbeat" (`:84-85`) | `vitals_monitor.py:58-99` |
| Test doubles: `_MockPool`, `_MockTrustNetwork`, `_MockIntentBus` (`broadcast_calls`), `_MockRuntime` (plain class, no `_drift_scheduler`, no `llm_client`) | `tests/test_medical_team.py:37-102` |
| A test module may import doubles from another | `tests/test_bf988_llm_response_text.py` (this branch); `tests/test_ad1207_fault_visibility.py:746` |
| `asyncio_mode = "auto"` | `pyproject.toml:181` |

**Readers of `metrics`, enumerated:**
- `_window`, exposed through `window` (`:370-372`), `latest_vitals` (`:378-383`) and `vitals_window` (`:385-388`).
- `latest_vitals` is read by `proactive.py:408`, which takes only named keys (`:414-434`).
- `scan_now` returns the window as `recent_history`. `DiagnosticianAgent.perceive` would JSON-dump it into the `diagnose_system` context (`diagnostician.py:100-104`), but that path fails earlier, on the `IntentMessage` the `/diagnostic` command sends (BF-991, #1840), so today no LLM context sees the window. The Diagnostician sees only a `medical_alert`'s params.
- `HeartbeatAgent._last_metrics` is used by `report()` and `info()` (`substrate/heartbeat.py:71`, `:118-124`).

A key added to `metrics` therefore reaches `scan_now`'s `recent_history` (an LLM prompt once BF-991 is repaired) and `info()` (D2).

## 1. Problem

While any `DriftReport` held by the scheduler is critical, every 5-second pulse appends a `qualification_drift` alert (`:345-356`) and broadcasts it (`:358-365`). The Diagnostician makes one LLM call for each. The report is held until the next drift run: a week, a `qualification run`, or a restart.

Measured on `fc9b9a6f` (#1839, probe `probe_vitals_diag.py`) with 14 critical agents:
- 3 heartbeats gave 3 alerts and 3 LLM calls.
- The no-report and warning-only controls gave 0 alerts.

BF-988 can make this state ordinary: a first measured recall score gives a critical signal for each agent with nine or more stored 0.5 results.

## 2. Solution overview

Remember on the agent which critical reports, as `(agent_id, report.timestamp)`, the last pulse held. Send the `qualification_drift` alert only when the current set holds a pair the last pulse did not. The memory is replaced with the current set on every pulse, so a set that empties re-arms the alert. An alert that no handler confirmed (the broadcast raised, returned no result, or returned only failed results) restores the previous memory, so the next pulse sends it again, for at most three sends per critical set (D7).

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
| The qualification alert is not confirmed: the broadcast raised, returned no result, or returned only failed results | The memory is restored to its previous value, so the next pulse sends it again, for at most three sends per critical set (D7). Without this, the edge would turn a transient bus error, a timeout or a failed handler into a week of silence |
| Three sends of one critical set are all unconfirmed | One warning is logged, the count resets, and the edge is used up until a pulse holds a report the last did not, or none (D7) |
| `rt is None` (`:110`) | `_check_thresholds` is not reached, as today. The memory is unchanged |
| The Vitals agent is respawned while the scheduler persists | The new instance alerts once for the held reports. That is one alert per incarnation, and it is accepted |

`report.timestamp` identifies a generation. It is `time.time()` at build (`drift_detector.py:114`), and two runs over one agent are seconds to weeks apart. `id(report)` was rejected because ids are reused after GC. A `DriftReport` itself is unhashable because `signals` is a list.

**D2: where the memory lives and what `metrics` gains.**
- The memory is `_critical_drift_held: frozenset[tuple[str, float]]` on the agent, in memory only like the scheduler cache it mirrors. A restart clears both. Its default is a class-level `frozenset()` (replaced per instance on the first pulse, never mutated): an agent built without `__init__` reads it too (A4).
- `metrics` gains nothing. Its readers (section 0) include `scan_now`'s `recent_history` (which the Diagnostician would put in its `diagnose_system` context, once BF-991 lets that path run) and `info()`.
- `_check_thresholds` gains a keyword-only `critical_drift: frozenset[tuple[str, float]] = frozenset()`. Its three direct callers in `tests/test_bf069_llm_health.py:218,255,285` pass `(metrics, rt)` on an agent built with `VitalsMonitorAgent.__new__` (`:199`, `:230`, `:266`), so they stay unedited only because the memory has a class-level default (A4). Its `AsyncMock` replacement at `:188` accepts the keyword.
- The qualification alert's predicate and `current_value` derive from `critical_drift`. A direct call without the keyword therefore sends no qualification alert even if `metrics` holds a count. No `src` caller does this (AV3).

**D3: tests.** The new file is `tests/test_bf990_qualification_drift_alert_edge.py`. It drives the real `VitalsMonitorAgent.collect_metrics` over `_MockRuntime` plus a scheduler double holding real `DriftReport`s, and a real `DiagnosticianAgent` over a counting LLM double. Its red states are in section 6. The inline copy at `tests/test_ad566c_drift_detection.py:717-760` is left as it is; the new file is the first real-path test.

**D4: mutation rows.** See section 10.

**D5: trackers.** One PROGRESS entry and one DECISIONS entry. The ledger pair is generated. No roadmap row, because the Bug Tracker lists only bugs deliberately not fixed.

**D7: what an undelivered alert is, and the bound (review round 1, F1; decided by the Architect, consult `17e90eda`).**
- `IntentBus.broadcast` does not raise for a handler that failed or timed out. A handler still running at the timeout is cancelled and the call returns `[]` (as it does for a closed bus, a denied intent and a handler that declined); a handler that raised comes back as `IntentResult(success=False)` (`mesh/intent.py:1479-1495`, `:1823-1905`). The first form of this repair restored the memory only when the broadcast raised, which production almost never gives.
- An alert is **delivered** iff the broadcast returned a result with `success` true (`any(r.success for r in results)`, inside the `try`, so an exception counts as undelivered). Otherwise the previous memory is restored and the next pulse sends the alert again.
- The retry is bounded. `_DRIFT_ALERT_SENDS = 3` sends for one critical set, counted by `_critical_drift_misses`. After the third unconfirmed send one `logger.warning` is written, the count resets and the edge is used up (the memory keeps the current set). The count also resets on a delivered alert and on any pulse on which the edge does not fire (an empty pulse, or a steady state). Why bounded: the broadcast's 5 s timeout cancels a Diagnostician whose LLM call is slower, so an unbounded retry would start one cancelled call per pulse for a week, which is the defect this change ends; three sends cover a provider blip or one slow call.
- Accepted: a Diagnostician stopped under AD-1343 refuses the alert and uses the edge up after three sends, with no LLM call. A report that joins a set already being retried shares its three sends. A successful result from a federation peer also counts as delivered (`mesh/intent.py:1524`).
- Rejected: **R1** (an unbounded retry: the base's behaviour on every failure path, one cancelled call per pulse for a week with a slow Diagnostician); **R3** (retry on `[]` and exceptions but not on failed results: gains nothing over the bound); **R4** (no retry: leaves F1 standing).
- Limit, recorded: whether an alert counts as delivered depends on the 5 s timeout, which cancels a Diagnostician whose LLM call is slower; that holds for every `medical_alert` and is not changed here. The live log (last written 2026-11-05) has no `Intent resolved:` line (control: no `Intent broadcast:` line either), so the share of alerts answered in time cannot be counted from it; it holds two Diagnostician recalls for the query `medical_alert` (2026-10-31 16:15:18 and 2026-11-04 19:33:00), which is all it shows of the alert's reach.

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
| The results of `rt.intent_bus.broadcast` for a `qualification_drift` alert | `_check_thresholds` itself: the delivered predicate and the bound (D7) | New reader: a result with `success` true is a delivery; its writers are the Diagnostician and, for a timeout or a failure, the bus (`[]` or a failed result) |

## 6. Tests (`tests/test_bf990_qualification_drift_alert_edge.py`)

| Test | Asserts | Red on base? |
|---|---|---|
| T1 | 1 and 14 critical agents, three pulses: qualification alerts per pulse `[1, 0, 0]`; the params are exactly the base's keys; `current_value` equals `metrics["qualification_drift_critical_count"]` | yes (`[1, 1, 1]`) |
| T2 | A new report generation alerts again (`[1, 0, 1]`). A second agent turning critical while the first is held alerts with `current_value == 2` | yes |
| T3 | Re-arm after a gap (`empty-reports`, `no-scheduler`, `warning-replaces`), with the same report object restored: `[1, 0, 1]` | no (it guards against the edge's mutations) |
| T4 | `no-scheduler`, `empty-reports`, `warning-only`, `normal-only`: `[0, 0, 0]` | no |
| T5 | Pool, trust, system and LLM alerts each fire on all three pulses; qualification fires once | yes (qualification 3) |
| T6 | The three outcomes the real bus gives for a handler that failed (the bus raises; no result; a failed result): the alert is sent on the first pulse, again on the second, and then not: `[1, 1, 0]` | yes (`[1, 1, 1]`) |
| T7 | A bus whose one handler is a real Diagnostician (its own result is what the success rule reads): three pulses give one broadcast and one LLM call | yes (3) |
| T7b | A real `IntentBus` (timeout cut to 50 ms) and a real Diagnostician whose first LLM call is slower than that: sends `[1, 1, 0]`, two calls started and one completed | yes (`[1, 1, 1]`) |
| T8a | An alert no handler ever confirms is sent three times and then not, with one warning: `[1, 1, 1, 0, 0]` | yes |
| T8b | A new report right after a confirmed retry gets three fresh sends: `[1, 1, 1, 1, 1, 0]` | yes |
| T8c | The count starts again after a pulse that holds no critical report: `[1, 0, 1, 1, 1, 0]` | yes |
| T8d | A new report right after a used-up alert gets three fresh sends: `[1, 1, 1, 1, 1, 1, 0]` | yes |
| T9 | Another alert's unconfirmed broadcast leaves the qualification edge alone: `pool_health` 3, qualification 1 | yes (3) |

## 7. The contract

### 7.1 New file: `tests/test_bf990_qualification_drift_alert_edge.py` (M1; shown in its final state after Amendment A1, whose pairs are in 17.2)

```python
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
```

### 7.2 `src/probos/agents/medical/vitals_monitor.py` (M1; the final state after Amendment A1, eight pairs in file order against `fc9b9a6f`; the pairs that move the committed M1 text are in 17.1)

**P-1.** `src/probos/agents/medical/vitals_monitor.py`: the memory, its retry count and the bound, as class-level members after `initial_confidence` (the memory's default is on the class because three existing tests build the agent with `__new__`)

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
    # BF-990: sends of that alert for one critical set before an undelivered edge is used up. The bus does
    # not raise for a handler that failed or timed out: it returns [] or a failed result.
    _DRIFT_ALERT_SENDS = 3
    _critical_drift_misses: int = 0
```

**P-2.** `src/probos/agents/medical/vitals_monitor.py`: `collect_metrics`: the comment above the qualification block: the identities stay out of `metrics`, and where the window goes

SEARCH:
```python
        # AD-566c: Qualification drift metrics
        _drift_scheduler = getattr(rt, "_drift_scheduler", None)
```
REPLACE:
```python
        # AD-566c: Qualification drift metrics
        # BF-990 (#1839): each critical report's identity, for the alert's edge. Kept out of
        # ``metrics``: ``scan_now`` returns the window as ``recent_history`` and ``info()`` reports
        # the last metrics.
        critical_drift: frozenset[tuple[str, float]] = frozenset()
        _drift_scheduler = getattr(rt, "_drift_scheduler", None)
```

**P-3.** `src/probos/agents/medical/vitals_monitor.py`: `collect_metrics`: the set of critical reports, built from the same snapshot as the counts

SEARCH:
```python
            if _reports:
                drift_agents_warning = sum(
```
REPLACE:
```python
            if _reports:
                critical_drift = frozenset(
                    (r.agent_id, r.timestamp)
                    for r in _reports.values() if r.overall_severity == "critical"
                )
                drift_agents_warning = sum(
```

**P-4.** `src/probos/agents/medical/vitals_monitor.py`: `collect_metrics`: the critical set goes to `_check_thresholds` as a keyword

SEARCH:
```python
        # Check thresholds and emit alerts
        await self._check_thresholds(metrics, rt)
```
REPLACE:
```python
        # Check thresholds and emit alerts
        await self._check_thresholds(metrics, rt, critical_drift=critical_drift)
```

**P-5.** `src/probos/agents/medical/vitals_monitor.py`: `_check_thresholds`: a keyword-only `critical_drift` and a docstring that says what the qualification alert does

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
        pulse did not. An alert that no handler confirmed is sent again on the next pulse, up to
        ``_DRIFT_ALERT_SENDS`` sends for one critical set.
        """
        alerts: list[dict[str, Any]] = []
```

**P-6.** `src/probos/agents/medical/vitals_monitor.py`: the qualification alert fires only on a critical report the last pulse did not hold, and the memory is replaced on every pulse

SEARCH:
```python
        # AD-566c: Qualification drift critical alert
        drift_critical = metrics.get("qualification_drift_critical_count", 0)
        if drift_critical > 0:
            alerts.append({
```
REPLACE:
```python
        # AD-566c: Qualification drift critical alert.
        # BF-990 (#1839): edge-triggered. The drift scheduler holds each report until its next run
        # (weekly), so a level check sent this alert on every pulse and the Diagnostician spent an
        # LLM call on each. It fires when a critical report appears that the last pulse did not
        # hold. The memory is replaced on every pulse, so a pulse holding none re-arms it. An alert
        # that no handler confirmed re-arms it too, for at most ``_DRIFT_ALERT_SENDS`` sends.
        previous_drift = self._critical_drift_held
        self._critical_drift_held = critical_drift
        if critical_drift - previous_drift:
            drift_critical = len(critical_drift)
            alerts.append({
```

**P-7.** `src/probos/agents/medical/vitals_monitor.py`: a pulse on which the edge does not fire restarts the count

SEARCH:
```python
                "timestamp": metrics["timestamp"],
            })

        # Broadcast alerts via intent bus
```
REPLACE:
```python
                "timestamp": metrics["timestamp"],
            })
        else:
            self._critical_drift_misses = 0

        # Broadcast alerts via intent bus
```

**P-8.** `src/probos/agents/medical/vitals_monitor.py`: the broadcast loop: delivered is a successful result; an unconfirmed qualification alert restores the memory for at most three sends, then one warning

SEARCH:
```python
            try:
                await rt.intent_bus.broadcast(intent, timeout=5.0)
            except Exception as e:
                logger.debug("Failed to broadcast medical alert: %s", e)
```
REPLACE:
```python
            try:
                results = await rt.intent_bus.broadcast(intent, timeout=5.0)
                delivered = any(r.success for r in results)
            except Exception as e:
                logger.debug("Failed to broadcast medical alert: %s", e)
                delivered = False
            if alert_data["metric"] == "qualification_drift":
                # BF-990: the bus returns [] for a handler that timed out and a failed result for one
                # that raised, so "delivered" is a successful result, not the absence of an exception.
                self._critical_drift_misses = 0 if delivered else self._critical_drift_misses + 1
                if 0 < self._critical_drift_misses < self._DRIFT_ALERT_SENDS:
                    self._critical_drift_held = previous_drift
                elif self._critical_drift_misses:
                    logger.warning(
                        "Qualification drift alert undelivered after %d sends; not retried until the critical reports change",
                        self._critical_drift_misses,
                    )
                    self._critical_drift_misses = 0
```

### 7.3 `PROGRESS.md` (M2)

SEARCH:
```markdown
# ProbOS Progress
```
REPLACE:
```markdown
# ProbOS Progress

**BF-990 (2026-11-20), #1839 -- the Vitals Monitor sends the qualification-drift alert once per new critical report, not on every heartbeat.** `DriftScheduler` holds each agent's latest `DriftReport` in memory until its next run (weekly, or `qualification run`), and `VitalsMonitorAgent._check_thresholds` sent a `qualification_drift` `medical_alert` on every 5 s pulse while any held report was critical; the Diagnostician made one LLM call per alert (measured: 14 critical agents, 3 heartbeats, 3 alerts, 3 calls). The alert is now edge-triggered on the set of critical reports as `(agent_id, report timestamp)`: it fires when the set holds a report the last pulse did not (a later run alerts again), and a pulse holding none re-arms it. An alert counts as delivered only when the broadcast returned a successful result: the bus gives no exception for a handler that timed out or failed (it returns no result, or a failed result), so an alert that no handler confirmed is sent again on the next pulse, for at most three sends per critical set, then one warning is logged and the edge is used up (review round 1, F1). The identities are passed to `_check_thresholds` as a keyword argument and kept out of `metrics`, which `scan_now` returns as `recent_history` and `info()` reports (the on-demand `/diagnostic` path that would put that window in the Diagnostician's context fails earlier, on the `IntentMessage` it is sent: BF-991, #1840). Params, severity and `current_value` (the total critical count) are unchanged; the pool, trust, system and LLM alerts still fire on every pulse. Lands with BF-988, whose first measured recall scores can make critical drift ordinary. New `tests/test_bf990_qualification_drift_alert_edge.py`. Contract `prompts/bf-990-qualification-drift-alert-edge.md`.
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
- *Repair.* `collect_metrics` builds `frozenset((agent_id, report.timestamp))` of critical reports from the same snapshot as the counts and passes it to `_check_thresholds(..., critical_drift=...)`. The agent keeps the last pulse's set in `_critical_drift_held` (memory only); the alert fires iff the current set holds a pair the last did not; the memory is replaced every pulse (an empty pulse re-arms). An alert counts as delivered only if the broadcast returned a result with `success` true; otherwise the previous memory is restored, so the next pulse sends it again, up to three sends per critical set (`_DRIFT_ALERT_SENDS`), after which one warning is logged and the edge is used up. The count restarts on a success, on the third unconfirmed send and on any pulse on which the edge does not fire.
- *Why this key.* Agent ids alone miss a later week; `last_run_time` re-alerts stale reports after a partial `run_now`; a cooldown still repeats an unchanged condition. Bound accepted: a pulse falling between the `__crew__` batch and the agent batch of one run can give two alerts for that run.
- *Why a result, and why three (review round 1, F1; decided by the Architect, consult `17e90eda`).* `IntentBus.broadcast` returns `[]` for a handler still running at the timeout (it is cancelled), a closed bus, a denied intent and a handler that declined, and a failed `IntentResult` for a handler that raised; it raises only for its own faults. The first form of this repair re-armed on an exception only, which production almost never gives: with a slow or failing first call the alert was lost until the next report (measured over the real bus and a real Diagnostician, 3 heartbeats: 1 call and 0 completed diagnoses, against 3 and 2 on the base). The 5 s cut-off would cancel an LLM call that is always slower, so an unbounded retry would start one cancelled call per pulse for a week, which is what this change ends; three sends cover a provider blip or one slow call. A Diagnostician that refuses the alert (stopped under AD-1343) uses the edge up after three sends with no LLM call. A report that joins a set already being retried shares its three sends.
- *Not in `metrics`.* `scan_now` returns the window as `recent_history`, and `info()` reports the last metrics. `DiagnosticianAgent.perceive` would JSON-dump the window into the `diagnose_system` context, but that path fails on the `IntentMessage` the `/diagnostic` command sends (BF-991, #1840), so today no LLM context sees it; the Diagnostician sees only a `medical_alert`'s params.
- *Limit.* Whether an alert counts as delivered depends on the 5 s timeout, which cancels a Diagnostician whose LLM call is slower; that holds for every `medical_alert` and is not changed here. The live log (last written 2026-11-05) has no `Intent resolved:` line, so the share of alerts answered in time cannot be counted from it.
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

> Fixed by BF-990 (PR #...). The qualification-drift `medical_alert` now fires once per new critical drift report (keyed on agent and report timestamp), not on every 5 s heartbeat; a later drift run alerts again, a pulse with no critical report re-arms it, and an alert that no handler confirmed (the bus raised, returned no result, or returned only failed results) is sent again on the next pulse, for at most three sends. The other Vitals alerts are unchanged. Measured before: 3 heartbeats, 3 alerts, 3 Diagnostician LLM calls; after: 1 and 1 (T7). With a slow first LLM call, over the real bus: before, 3 calls and 2 completed diagnoses; after the first form of this repair, 1 and 0; after the amendment, 2 and 1 (T7b). The on-demand `/diagnostic` command, which would put the metrics window in the Diagnostician's context, fails earlier on the `IntentMessage` it sends: BF-991, #1840.

## 9. What this does NOT change

- The pool-health, trust-outlier, system-health and LLM-health alerts, which stay level-triggered.
- `metrics` keys and values, `scan_now`, the window, `latest_vitals` and `info()`.
- `DriftScheduler`, `DriftReport`, `BridgeAlertService.check_qualification_drift` and the `QUALIFICATION_DRIFT_DETECTED` event.
- The Diagnostician and the decision cache.
- The broadcast's 5 s timeout, the Diagnostician's handling of a cancelled call, and the on-demand `/diagnostic` path (BF-991, #1840).
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
| R-6 | the restore `self._critical_drift_held = previous_drift` | `pass` | T6 (all three), T7b, T8a |
| R-7 | comprehension `== "critical"` | `in ("warning", "critical")` | T4[warning-only] |
| R-8 | the `_critical_drift_held = critical_drift` line | moved above `previous_drift = ...` | T1, T2, T7 |
| R-9 | `drift_critical = len(critical_drift)` | `len(critical_drift - previous_drift)` | T2 (`current_value == 2`) |
| R-10 | the class-level `_critical_drift_held` default (A4) | removed (the memory is set in `__init__` only, the Architect's first form) | `tests/test_bf069_llm_health.py` (the three `_check_thresholds` cases) |
| R-11 | `delivered = any(r.success for r in results)` | `delivered = bool(results)` | T6 failed |
| R-12 | same | `delivered = not results or any(r.success for r in results)` | T6 empty, T7b, T8a |
| R-13 | the except branch's `delivered = False` | `delivered = True` | T6 raise |
| R-14 | `if 0 < self._critical_drift_misses < self._DRIFT_ALERT_SENDS:` | `<=` | T8a |
| R-15 | same | `if 0 < self._critical_drift_misses:` (no bound) | T8a |
| R-16 | `self._critical_drift_misses = 0 if delivered else self._critical_drift_misses + 1` | `... = self._critical_drift_misses + (0 if delivered else 1)` (no reset on success) | T8b |
| R-17 | the edge's `else:` | `elif False:` (no reset on a pulse that does not fire) | T8c |
| R-18 | the last `self._critical_drift_misses = 0` (the used-up branch) | `pass` | T8d |
| R-19 | `delivered = any(r.success for r in results)` | `delivered = True` (revert to restoring on exceptions only) | T6 empty, T6 failed, T7b, T8a |
| R-20 | `if alert_data["metric"] == "qualification_drift":` | `if True:` | T9 |
| R-21 | the class-level `_critical_drift_misses: int = 0` | `pass` | T6 raise, T8a |
| R-22 | `_DRIFT_ALERT_SENDS = 3` | `= 2` | T8a |

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
| P3 | Each SEARCH matches once | `rg -c` the first distinctive line of each of the blocks of the first build (five pairs of the first form of 7.2, one block each in 7.3 and 7.4; 7.2 now shows the final state, eight pairs) |
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
2. `_critical_drift_held` is replaced on every `_check_thresholds` call, including with an empty set, and is restored only for an unconfirmed qualification alert (D7), never for another alert's failure (T9).
3. `critical_drift` is built from the same `_reports` snapshot as the counts, and no new key enters `metrics`.
4. The new keyword argument is keyword-only, has a default, and does not break the `tests/test_bf069_llm_health.py` call sites, whose agents are built with `__new__`: the class-level default of `_critical_drift_held` serves them.
5. The tests drive the real `collect_metrics` and a real `DiagnosticianAgent`, and T5 asserts that the four other alert types fire on all three pulses.
6. One PROGRESS entry and one DECISIONS entry are added, and the ledger pair is generated.
7. An alert counts as delivered iff some result has `success` true, an exception counts as undelivered, and an undelivered qualification alert is sent at most three times for one critical set, with one warning when the third is unconfirmed (T6, T7b, T8).
8. The count restarts on a delivered alert, on the third unconfirmed send and on every pulse on which the edge does not fire (T8b to T8d), and the class-level defaults serve an agent built without `__init__`.
9. Every claim in the PROGRESS and DECISIONS entries and in sections 0, 3, 5 and 8 about where the metrics window goes holds against the code: `scan_now` returns it, and the on-demand path that would read it fails earlier (BF-991).

## 15. Acceptance criteria

1. Three heartbeats over one unchanged critical report give one `qualification_drift` alert and one Diagnostician LLM call (T1, T7).
2. A new report generation alerts again; a set that empties and refills alerts again; warning-only, normal-only, an empty cache and no scheduler alert never (T2, T3, T4).
3. The pool, trust, system and LLM alerts fire on every heartbeat as before (T5). An alert that no handler confirmed is sent again on the next heartbeat and then not (T6), for at most three sends and one warning (T8); a real bus that times out gets its retry and the diagnosis completes (T7b); another alert's failure leaves the edge alone (T9).
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
| **Review round 1 (Amendment A1)** | F1, F2 and F3 reproduced first-hand (section 17): the production bus returns no result or a failed result, never an exception, for a handler that timed out or failed, so the exception-only retry lost the alert (3 heartbeats, a slow first call: base 3 calls and 2 completed diagnoses, candidate 1 and 0). The Architect's decisions (consult `17e90eda`): a result with `success` true is a delivery, three sends per critical set, the on-demand defect is its own issue (BF-991, #1840), the window claims are corrected. The Architect's code was checked line by line before use (the counter's resets and the bound reproduce `[1, 1, 1, 0, 0]` over five pulses). The new tests on the committed source: 7 failed, 14 passed; the A1 mutation campaign: 22 of 22 rows killed (section 10). |
| Batching | The Architect's answer (consult `624994ca`): one branch, one pull request, one gate (`bf-988-990`); BF-990 keeps its own milestones, focused check, review round and commits, after BF-988's M2 and before BF-988's repair. |

## For the register (#1839)

- **R-1.** A pulse that falls between the `__crew__` batch and the agents' batch of one drift run can give two alerts for that run (D1). Bounded, accepted.
- **R-2.** The other level-triggered alerts (pool health, trust outliers, system health, LLM proxy) still repeat on every pulse and cost the Diagnostician a call each while their condition holds. Transient by nature; not changed here.
- **R-3.** A respawned Vitals agent alerts once for the reports the scheduler still holds (D1). Accepted.
- **R-4.** An alert is delivered only if a handler answered inside the broadcast's 5 s timeout. A Diagnostician whose LLM call is always slower is cancelled each time, so its three sends are cancelled calls and the edge is then used up with one warning; the same cut-off applies to every `medical_alert` and is not changed here (D7).
- **R-5.** A report that joins a critical set that is already being retried shares that set's three sends (the count is of consecutive unconfirmed sends). Accepted.
- **R-6.** The on-demand `/diagnostic` path fails on the `IntentMessage` it is sent (BF-991, #1840); until it is repaired nothing reads the metrics window into an LLM context.

## 17. Amendment A1: review round 1 (gpt-6.1-sol, REQUEST CHANGES), three findings repaired

Review round 1 of `5040f508` (finished 06:49Z; `next/adq/b6/b990/review-b990-r1.out.md`) found three things. The orchestrator reproduced each first-hand (probe `probe_b990_r1.py`, run on `fc9b9a6f` and on `5040f508`; evidence `probe-b990-r1.base.out.txt` and `probe-b990-r1.cand.out.txt`) and took the decisions below through the Architect (read-only consult `17e90eda`, 2026-11-20).

| Finding | Reviewer's class | Verified | Disposition |
|---|---|---|---|
| F1: a failed delivery permanently consumes the alert edge | P2, ordinary, regression | Reproduced exactly. Over the real `IntentBus`, `collect_metrics` and a real Diagnostician, 3 heartbeats and a first LLM call that outlasts the 5 s timeout: base 3 alerts, 3 calls started, 2 completed; candidate 1, 1, **0**, the first broadcast returned `[]` and was never sent again. A first call that raises: base 3, 3, 2; candidate 1, 1, **0** (a failed result, never sent again). With nobody subscribed: base 3 alerts, candidate 1. The bus raises for none of these | **Fixed here** (Architect, option R2): the alert counts as delivered only if a result has `success` true; otherwise the memory is restored and the next pulse sends it again, for at most 3 sends per critical set, then one warning (D7) |
| F2: the on-demand consumer fails before receiving the history | P2, ordinary, not a regression | Reproduced, identical on the base: `DiagnosticianAgent.perceive` calls `intent.get("level")` on an `IntentMessage` (`diagnostician.py:83`); `/diagnostic` (`commands_diagnostic.py:65-69`, the only producer of `diagnose_system` in `src`) fails with `'IntentMessage' object has no attribute 'get'` and makes 0 LLM calls; the same Diagnostician handles a `medical_alert` `IntentMessage` | Filed as **BF-991, #1840** (an independently reachable production defect; the Architect's decision (a); the 6th and last filing of the discovery budget). The claims that the window reaches the Diagnostician's LLM context are corrected (sections 0, 3, 5, 7.2, 7.4, PROGRESS.md) |
| F3: an unused `Any` import | P3, ordinary, size | Reproduced (the import in the test file and its copy in 7.1; no other reference) | Removed from both |

Sections 0, 2, 3, 5 to 10, 12, 14, 15 and 16 above were corrected in place so that they show the final state; 7.1 and 7.2 show the final files; 17.1 to 17.3 hold the SEARCH/REPLACE pairs that move the files as committed (`vitals_monitor.py` and the test file at `5040f508`; the trackers at `5040f508` and `ac827027`) to that state. Where an older sentence of sections 0 to 16 disagrees with this section, this section governs.

**The Architect's code, checked.** The Architect gave the production change as a snippet (two class-level members, an `else` on the edge, the loop body). It was applied as given except that the call and the predicate are two statements (`results = ...; delivered = any(r.success for r in results)`) and the warning's text says what happens next. Its claims were re-run: five pulses over a bus that never confirms send `[1, 1, 1, 0, 0]` with one warning (T8a); a fail, a success and a new generation that always fails send 3 times for the new one (T8b); an empty pulse restarts the count (T8c); a new report right after a used-up alert sends 3 times (T8d).

**Milestone A1** (one Builder delegation, tier LOW, then one local commit for the source and tests and one for the trackers): 17.1, 17.2 and 17.3 in order. Focused gate: `pytest tests/test_bf990_qualification_drift_alert_edge.py tests/test_bf069_llm_health.py tests/test_medical_team.py tests/test_diagnostician.py -q -n 0`.

### 17.1 `src/probos/agents/medical/vitals_monitor.py` (A1)

**A1-1.** `src/probos/agents/medical/vitals_monitor.py`: the retry bound and the counter, after the memory's class-level default (the bus does not raise for a handler that timed out or failed, so "not sent" needs a count)

SEARCH:
```python
    _critical_drift_held: frozenset[tuple[str, float]] = frozenset()
```
REPLACE:
```python
    _critical_drift_held: frozenset[tuple[str, float]] = frozenset()
    # BF-990: sends of that alert for one critical set before an undelivered edge is used up. The bus does
    # not raise for a handler that failed or timed out: it returns [] or a failed result.
    _DRIFT_ALERT_SENDS = 3
    _critical_drift_misses: int = 0
```

**A1-2.** `src/probos/agents/medical/vitals_monitor.py`: the comment in `collect_metrics`: where the window goes, said as it is (the on-demand path that would read it fails earlier, BF-991, #1840)

SEARCH:
```python
        # BF-990 (#1839): each critical report's identity, for the alert's edge. Kept out of
        # ``metrics``: the window reaches the Diagnostician's LLM context (``scan_now``'s
        # ``recent_history``) and ``info()``.
        critical_drift: frozenset[tuple[str, float]] = frozenset()
```
REPLACE:
```python
        # BF-990 (#1839): each critical report's identity, for the alert's edge. Kept out of
        # ``metrics``: ``scan_now`` returns the window as ``recent_history`` and ``info()`` reports
        # the last metrics.
        critical_drift: frozenset[tuple[str, float]] = frozenset()
```

**A1-3.** `src/probos/agents/medical/vitals_monitor.py`: the docstring of `_check_thresholds`: an alert that no handler confirmed is sent again, up to `_DRIFT_ALERT_SENDS` sends for one critical set

SEARCH:
```python
        as ``(agent_id, report timestamp)``, and that alert fires only when it holds one the last
        pulse did not.
        """
```
REPLACE:
```python
        as ``(agent_id, report timestamp)``, and that alert fires only when it holds one the last
        pulse did not. An alert that no handler confirmed is sent again on the next pulse, up to
        ``_DRIFT_ALERT_SENDS`` sends for one critical set.
        """
```

**A1-4.** `src/probos/agents/medical/vitals_monitor.py`: the comment above the edge says the same

SEARCH:
```python
        # LLM call on each. It fires when a critical report appears that the last pulse did not
        # hold. The memory is replaced on every pulse, so a pulse holding none re-arms it.
        previous_drift = self._critical_drift_held
```
REPLACE:
```python
        # LLM call on each. It fires when a critical report appears that the last pulse did not
        # hold. The memory is replaced on every pulse, so a pulse holding none re-arms it. An alert
        # that no handler confirmed re-arms it too, for at most ``_DRIFT_ALERT_SENDS`` sends.
        previous_drift = self._critical_drift_held
```

**A1-5.** `src/probos/agents/medical/vitals_monitor.py`: a pulse on which the edge does not fire restarts the count

SEARCH:
```python
                "timestamp": metrics["timestamp"],
            })

        # Broadcast alerts via intent bus
```
REPLACE:
```python
                "timestamp": metrics["timestamp"],
            })
        else:
            self._critical_drift_misses = 0

        # Broadcast alerts via intent bus
```

**A1-6.** `src/probos/agents/medical/vitals_monitor.py`: the broadcast loop: delivered means a handler returned a successful result; an unconfirmed qualification alert restores the previous memory for at most three sends, then one warning and the edge is used up

SEARCH:
```python
            try:
                await rt.intent_bus.broadcast(intent, timeout=5.0)
            except Exception as e:
                logger.debug("Failed to broadcast medical alert: %s", e)
                if alert_data["metric"] == "qualification_drift":
                    # BF-990: an edge alert that was not sent re-arms, so the next pulse retries it.
                    self._critical_drift_held = previous_drift
```
REPLACE:
```python
            try:
                results = await rt.intent_bus.broadcast(intent, timeout=5.0)
                delivered = any(r.success for r in results)
            except Exception as e:
                logger.debug("Failed to broadcast medical alert: %s", e)
                delivered = False
            if alert_data["metric"] == "qualification_drift":
                # BF-990: the bus returns [] for a handler that timed out and a failed result for one
                # that raised, so "delivered" is a successful result, not the absence of an exception.
                self._critical_drift_misses = 0 if delivered else self._critical_drift_misses + 1
                if 0 < self._critical_drift_misses < self._DRIFT_ALERT_SENDS:
                    self._critical_drift_held = previous_drift
                elif self._critical_drift_misses:
                    logger.warning(
                        "Qualification drift alert undelivered after %d sends; not retried until the critical reports change",
                        self._critical_drift_misses,
                    )
                    self._critical_drift_misses = 0
```

### 17.2 `tests/test_bf990_qualification_drift_alert_edge.py` (A1)

**A1-7.** `tests/test_bf990_qualification_drift_alert_edge.py`: the module docstring: an alert that no handler confirmed is sent again, for at most three sends

SEARCH:
```python
one LLM call on each. The alert now fires when a critical report ``(agent_id, timestamp)`` appears
that the last pulse did not hold; a pulse that holds none re-arms it, and an alert whose broadcast
raised is retried. Every case drives the real ``collect_metrics``; the other alert types keep
firing on every pulse.
"""
```
REPLACE:
```python
one LLM call on each. The alert now fires when a critical report ``(agent_id, timestamp)`` appears
that the last pulse did not hold; a pulse that holds none re-arms it. An alert that no handler
confirmed (the bus raised, returned no result, or returned only failed results) is sent again on the
next pulse, for at most three sends. Every case drives the real ``collect_metrics``; the other alert
types keep firing on every pulse.
"""
```

**A1-8.** `tests/test_bf990_qualification_drift_alert_edge.py`: imports: `asyncio` in (the slow double sleeps), `typing.Any` out (round 1, F3: it was unused)

SEARCH:
```python
from typing import Any
from unittest.mock import AsyncMock, MagicMock
```
REPLACE:
```python
import asyncio
from unittest.mock import AsyncMock, MagicMock
```

**A1-9.** `tests/test_bf990_qualification_drift_alert_edge.py`: imports: the real bus, the signal manager and `IntentResult`

SEARCH:
```python
from probos.cognitive.drift_detector import DriftReport
from probos.types import AgentState, IntentMessage
from tests.test_medical_team import _MockIntentBus, _MockPool, _MockRuntime
```
REPLACE:
```python
from probos.cognitive.drift_detector import DriftReport
from probos.mesh.intent import IntentBus
from probos.mesh.signal import SignalManager
from probos.types import AgentState, IntentMessage, IntentResult
from tests.test_medical_team import _MockIntentBus, _MockPool, _MockRuntime
```

**A1-10.** `tests/test_bf990_qualification_drift_alert_edge.py`: the doubles: `_FailFirstQualificationBus` (it raised, which the production bus does not) goes; `_DeliveringBus`, `_ScriptedBus`, `_DiagnosticianBus`, `_ShortBus` and `_SlowFirstLLM` come

SEARCH:
```python
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
```
REPLACE:
```python
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
```

**A1-11.** `tests/test_bf990_qualification_drift_alert_edge.py`: `_healthy_runtime` takes the bus the case wants

SEARCH:
```python
def _healthy_runtime(scheduler: _Scheduler | None) -> _MockRuntime:
    runtime = _MockRuntime(
```
REPLACE:
```python
def _healthy_runtime(scheduler: _Scheduler | None, bus: _MockIntentBus | IntentBus | None = None) -> _MockRuntime:
    runtime = _MockRuntime(
```

**A1-12.** `tests/test_bf990_qualification_drift_alert_edge.py`: `_healthy_runtime` installs it, a confirming bus by default

SEARCH:
```python
    runtime._drift_scheduler = scheduler
    return runtime
```
REPLACE:
```python
    runtime._drift_scheduler = scheduler
    runtime.intent_bus = bus if bus is not None else _DeliveringBus()
    return runtime
```

**A1-13.** `tests/test_bf990_qualification_drift_alert_edge.py`: `_pulse` returns the qualification alerts it sent, not the ones a bus delivered

SEARCH:
```python
async def _pulse(agent: VitalsMonitorAgent, runtime: _MockRuntime) -> list[IntentMessage]:
    """One heartbeat; the qualification alerts it delivered."""
    before = len(runtime.intent_bus.broadcast_calls)
```
REPLACE:
```python
async def _pulse(agent: VitalsMonitorAgent, runtime: _MockRuntime) -> list[IntentMessage]:
    """One heartbeat; the qualification alerts it sent."""
    before = len(runtime.intent_bus.broadcast_calls)
```

**A1-14.** `tests/test_bf990_qualification_drift_alert_edge.py`: T5 builds its own runtime and takes the confirming bus too

SEARCH:
```python
    runtime._drift_scheduler = _Scheduler({"ag-1": _report("ag-1", 100.0)})
    agent = VitalsMonitorAgent(pool="medical", runtime=runtime)
```
REPLACE:
```python
    runtime._drift_scheduler = _Scheduler({"ag-1": _report("ag-1", 100.0)})
    runtime.intent_bus = _DeliveringBus()
    agent = VitalsMonitorAgent(pool="medical", runtime=runtime)
```

**A1-15.** `tests/test_bf990_qualification_drift_alert_edge.py`: T6 runs the three outcomes the real bus gives (an exception, no result, a failed result): the alert is sent again once and then not

SEARCH:
```python
async def test_an_alert_that_failed_to_send_is_retried_on_the_next_heartbeat() -> None:
    runtime = _healthy_runtime(_Scheduler({"ag-1": _report("ag-1", 100.0)}))
    runtime.intent_bus = _FailFirstQualificationBus()
    agent = VitalsMonitorAgent(pool="medical", runtime=runtime)

    delivered = [len(await _pulse(agent, runtime)) for _ in range(3)]

    assert runtime.intent_bus.failed is True
    assert delivered == [0, 1, 0]
```
REPLACE:
```python
@pytest.mark.parametrize("outcome", ["raise", "empty", "failed"])
async def test_an_alert_no_handler_confirmed_is_sent_again_on_the_next_heartbeat(outcome: str) -> None:
    runtime = _healthy_runtime(_Scheduler({"ag-1": _report("ag-1", 100.0)}), _ScriptedBus([outcome]))
    agent = VitalsMonitorAgent(pool="medical", runtime=runtime)

    assert [len(await _pulse(agent, runtime)) for _ in range(3)] == [1, 1, 0]
```

**A1-16.** `tests/test_bf990_qualification_drift_alert_edge.py`: T7 crosses the seam: the bus answers with the real Diagnostician's own result, so the success rule reads it

SEARCH:
```python
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
```
REPLACE:
```python
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
```

**A1-17.** `tests/test_bf990_qualification_drift_alert_edge.py`: T7b (the real bus times out on a slow first call and the second send completes), T8 (the bound and its resets) and T9 (another alert's failure leaves the edge alone)

SEARCH:
```python
    assert llm.complete.await_count == 1
```
REPLACE:
```python
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
```

### 17.3 The trackers (A1)

The two entries of BF-990 move to the corrected text of sections 7.3 and 7.4. The SEARCH blocks quote the text they replace, by design.

**A1-18.** `PROGRESS.md`: the BF-990 paragraph: an unconfirmed alert is sent again for at most three sends (the bus returns no result or a failed result, not an exception), and the window sentence says where the window goes

SEARCH:
```markdown
**BF-990 (2026-11-20), #1839 -- the Vitals Monitor sends the qualification-drift alert once per new critical report, not on every heartbeat.** `DriftScheduler` holds each agent's latest `DriftReport` in memory until its next run (weekly, or `qualification run`), and `VitalsMonitorAgent._check_thresholds` sent a `qualification_drift` `medical_alert` on every 5 s pulse while any held report was critical; the Diagnostician made one LLM call per alert (measured: 14 critical agents, 3 heartbeats, 3 alerts, 3 calls). The alert is now edge-triggered on the set of critical reports as `(agent_id, report timestamp)`: it fires when the set holds a report the last pulse did not (a later run alerts again), a pulse holding none re-arms it, and an alert whose broadcast raised is retried on the next pulse. The identities are passed to `_check_thresholds` as a keyword argument and kept out of `metrics`, whose window reaches the Diagnostician's LLM context. Params, severity and `current_value` (the total critical count) are unchanged; the pool, trust, system and LLM alerts still fire on every pulse. Lands with BF-988, whose first measured recall scores can make critical drift ordinary. New `tests/test_bf990_qualification_drift_alert_edge.py`. Contract `prompts/bf-990-qualification-drift-alert-edge.md`.
```
REPLACE:
```markdown
**BF-990 (2026-11-20), #1839 -- the Vitals Monitor sends the qualification-drift alert once per new critical report, not on every heartbeat.** `DriftScheduler` holds each agent's latest `DriftReport` in memory until its next run (weekly, or `qualification run`), and `VitalsMonitorAgent._check_thresholds` sent a `qualification_drift` `medical_alert` on every 5 s pulse while any held report was critical; the Diagnostician made one LLM call per alert (measured: 14 critical agents, 3 heartbeats, 3 alerts, 3 calls). The alert is now edge-triggered on the set of critical reports as `(agent_id, report timestamp)`: it fires when the set holds a report the last pulse did not (a later run alerts again), and a pulse holding none re-arms it. An alert counts as delivered only when the broadcast returned a successful result: the bus gives no exception for a handler that timed out or failed (it returns no result, or a failed result), so an alert that no handler confirmed is sent again on the next pulse, for at most three sends per critical set, then one warning is logged and the edge is used up (review round 1, F1). The identities are passed to `_check_thresholds` as a keyword argument and kept out of `metrics`, which `scan_now` returns as `recent_history` and `info()` reports (the on-demand `/diagnostic` path that would put that window in the Diagnostician's context fails earlier, on the `IntentMessage` it is sent: BF-991, #1840). Params, severity and `current_value` (the total critical count) are unchanged; the pool, trust, system and LLM alerts still fire on every pulse. Lands with BF-988, whose first measured recall scores can make critical drift ordinary. New `tests/test_bf990_qualification_drift_alert_edge.py`. Contract `prompts/bf-990-qualification-drift-alert-edge.md`.
```

**A1-19.** `DECISIONS.md`: the BF-990 entry: the repair says what delivered means and bounds the retry; two bullets say why (the bus, and the 5 s cut-off) and that the window is not read today; one bullet records the limit

SEARCH:
```markdown
- *Mechanism.* The drift scheduler's in-memory `latest_reports` holds each critical `DriftReport` for a week; `VitalsMonitorAgent._check_thresholds` re-sent the `qualification_drift` `medical_alert` on every 5 s pulse, and each cost the Diagnostician an LLM call (decision cache off by default).
- *Repair.* `collect_metrics` builds `frozenset((agent_id, report.timestamp))` of critical reports from the same snapshot as the counts and passes it to `_check_thresholds(..., critical_drift=...)`. The agent keeps the last pulse's set in `_critical_drift_held` (memory only); the alert fires iff the current set holds a pair the last did not; the memory is replaced every pulse (an empty pulse re-arms); a failed broadcast restores the previous memory (retried next pulse).
- *Why this key.* Agent ids alone miss a later week; `last_run_time` re-alerts stale reports after a partial `run_now`; a cooldown still repeats an unchanged condition. Bound accepted: a pulse falling between the `__crew__` batch and the agent batch of one run can give two alerts for that run.
- *Not in `metrics`.* The window reaches the Diagnostician's `diagnose_system` LLM context via `scan_now`'s `recent_history`, and `info()`.
- *Scope.* Pool, trust (BF-879 added no edge), system and LLM alerts stay level-triggered by design.
```
REPLACE:
```markdown
- *Mechanism.* The drift scheduler's in-memory `latest_reports` holds each critical `DriftReport` for a week; `VitalsMonitorAgent._check_thresholds` re-sent the `qualification_drift` `medical_alert` on every 5 s pulse, and each cost the Diagnostician an LLM call (decision cache off by default).
- *Repair.* `collect_metrics` builds `frozenset((agent_id, report.timestamp))` of critical reports from the same snapshot as the counts and passes it to `_check_thresholds(..., critical_drift=...)`. The agent keeps the last pulse's set in `_critical_drift_held` (memory only); the alert fires iff the current set holds a pair the last did not; the memory is replaced every pulse (an empty pulse re-arms). An alert counts as delivered only if the broadcast returned a result with `success` true; otherwise the previous memory is restored, so the next pulse sends it again, up to three sends per critical set (`_DRIFT_ALERT_SENDS`), after which one warning is logged and the edge is used up. The count restarts on a success, on the third unconfirmed send and on any pulse on which the edge does not fire.
- *Why this key.* Agent ids alone miss a later week; `last_run_time` re-alerts stale reports after a partial `run_now`; a cooldown still repeats an unchanged condition. Bound accepted: a pulse falling between the `__crew__` batch and the agent batch of one run can give two alerts for that run.
- *Why a result, and why three (review round 1, F1; decided by the Architect, consult `17e90eda`).* `IntentBus.broadcast` returns `[]` for a handler still running at the timeout (it is cancelled), a closed bus, a denied intent and a handler that declined, and a failed `IntentResult` for a handler that raised; it raises only for its own faults. The first form of this repair re-armed on an exception only, which production almost never gives: with a slow or failing first call the alert was lost until the next report (measured over the real bus and a real Diagnostician, 3 heartbeats: 1 call and 0 completed diagnoses, against 3 and 2 on the base). The 5 s cut-off would cancel an LLM call that is always slower, so an unbounded retry would start one cancelled call per pulse for a week, which is what this change ends; three sends cover a provider blip or one slow call. A Diagnostician that refuses the alert (stopped under AD-1343) uses the edge up after three sends with no LLM call. A report that joins a set already being retried shares its three sends.
- *Not in `metrics`.* `scan_now` returns the window as `recent_history`, and `info()` reports the last metrics. `DiagnosticianAgent.perceive` would JSON-dump the window into the `diagnose_system` context, but that path fails on the `IntentMessage` the `/diagnostic` command sends (BF-991, #1840), so today no LLM context sees it; the Diagnostician sees only a `medical_alert`'s params.
- *Limit.* Whether an alert counts as delivered depends on the 5 s timeout, which cancels a Diagnostician whose LLM call is slower; that holds for every `medical_alert` and is not changed here. The live log (last written 2026-11-05) has no `Intent resolved:` line, so the share of alerts answered in time cannot be counted from it.
- *Scope.* Pool, trust (BF-879 added no edge), system and LLM alerts stay level-triggered by design.
```

### 17.4 Generated: the ledger pair (A1)

After 17.3, run `d:/ProbOS/.venv/Scripts/python.exe -P scripts/gen_ad_ledger.py`. It regenerates `docs/development/open-ads-report.md` and `docs/development/ad-ledger-snapshot.json`; do not paste them. Verify with `--check` and `tests/test_ad1184_ad_ledger.py`.

### 17.5 Mutation rows (A1)

Section 10 holds all 22 rows (R-1 to R-10 of the first campaign, R-6 re-pointed, and R-11 to R-22 new). The campaign of record for A1 runs all 22 on the final files; record the sha256 of `vitals_monitor.py` and of the test file. A row is killed when every named case fails; other cases may fail with it.

### 17.6 Reviewer properties for the delta (properties to verify, not attack scenarios)

1. An alert counts as delivered iff the broadcast returned a result with `success` true; an exception, an empty list and a list of failed results are undelivered; the predicate sits inside the `try`.
2. An undelivered qualification alert restores the previous memory, at most three times for one critical set, then logs one warning and keeps the current set; the count restarts on a delivered alert, on the used-up branch and on every pulse on which the edge does not fire; no other alert's outcome touches the memory or the count.
3. `_DRIFT_ALERT_SENDS` and `_critical_drift_misses` are class-level defaults, replaced per instance and never mutated, so an agent built with `__new__` (`tests/test_bf069_llm_health.py`) still works; no `metrics` key and no signature changed other than A0's keyword.
4. The new tests drive the real `collect_metrics`; T7 reads a real Diagnostician's own result through the bus double; T7b uses a real `IntentBus` with the timeout cut to 50 ms and a real Diagnostician, and is not timing-fragile (the first call sleeps 0.5 s against a 50 ms timeout; nothing waits on the sleep); on the committed source 7 cases fail (T6 empty and failed, T7b, T8a to T8d) and 14 pass.
5. Every sentence of sections 0, 3, 5, 7.2, 7.4, 8 and the PROGRESS and DECISIONS entries about where the metrics window goes holds against the code, and says that the on-demand path fails earlier (BF-991, #1840); the contract's 7.1 and the test file are identical, and neither imports `typing.Any`.
6. The only files that change are `vitals_monitor.py`, the test file, the contract, `PROGRESS.md`, `DECISIONS.md` and the ledger pair; `diagnostician.py` and `commands_diagnostic.py` are untouched.
