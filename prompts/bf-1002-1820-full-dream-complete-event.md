# BF-1002 (#1820 bf-989 R6, part a): a full dream's dream_complete event reaches its listeners

**Drafted by:** `claude-architect` (Claude Code, Opus 5.5), 2026-11-26
**Status:** ready to build. **Owning issue:** #1820 (checklist item bf-989 R6, part a; the item stays open for part b). Commits say `Refs #1820.`
**Base:** origin/main after the AD-1337 R23/R7/R1 batch merges; drafted against `c3721a2d` (the files of 6.1 and 6.2 are byte-identical at `6539f04d`). Branch `fix/bf1002-1820-full-dream-complete-<date>`. **Number:** BF-1002 (ceiling BF-1001, #1861).
**Mechanical edits (orchestrator, 2026-11-27, on `4d812803`):** the two `<date>` slots of 6.4 and 6.5 are filled with 2026-11-27, and P7 is anchored on the heading of the BF-1001 entry that #1865 added (now the newest entry of `DECISIONS.md`), in place of the AD-1337 follow-up heading the draft named, as P7's label allows. The draft's seven pairs and the new file applied once each on `4d812803` before these edits.
**Review repair (orchestrator, 2026-11-27, round 1 of the Diff Reviewer, finding F1, P3):** the helper's docstring (P1) said each of the six values is the report's own field, but `dream_type` is the constant `"full"`. P1's docstring, the sentence of P6 and the text of section 2 and of the wave comment in section 12 now say that the five numeric values are the report's own fields. No code line changed.
**Line endings:** the working copies may be CRLF and the blocks below are LF; match after normalising. Every SEARCH starts at the beginning of a line and occurs once in its file at its turn. All new text is ASCII.
**Estimated tests:** 5 new in a new file; 1 changed in place in `tests/test_dreaming.py`; 0 removed.
**Scope:** one commit: `src/probos/cognitive/dreaming.py`, `tests/test_dreaming.py`, `tests/test_bf1002_full_dream_complete_event.py` (new), `PROGRESS.md`, `DECISIONS.md`, the regenerated ledger files.

## 1. Problem (premise table)

| Where | What it does today | Effect |
|---|---|---|
| `dreaming.py`:3245-3260 (`force_dream`) and :3344-3359 (monitor loop, full dream) | build the payload inside the emit call's `try`, with `"episodes_replayed": len(getattr(report, "episodes_replayed", []))` at :3253 and :3352 | `DreamReport.episodes_replayed` is `int = 0` (`types.py`:896), so `len()` raises `TypeError`, caught at `logger.debug` (:3259-3260, :3358-3359); `runtime._emit_event` is never called for a full dream |
| `DreamingEngine.dream_cycle` (:420), returns at :478 and :1867 (the report of :1758) | each return is a `DreamReport` whose count is `micro_report["episodes_replayed"]`, an int (`micro_dream` :239-305, fallback :370) | the `TypeError` is raised on every full dream at the base |
| `tests/test_dreaming.py`:522-553 | the stand-in is `SimpleNamespace(episodes_replayed=[], ...)` and the test asserts only the key set | the one payload test passes on the defect |
| `counselor.py`:2735-2740 (AD-505) | awaits `force_dream()`, then adds the agent to `_intervention_targets` for AD-506a's re-assessment in `_on_dream_complete` (:1117-1147) | the forced dream's own completion never arrives; the re-assessment runs only on a later micro completion that replayed episodes (:3288-3299) |

## 2. Overview

A module helper `_full_dream_complete_payload(report: DreamReport) -> dict[str, Any]` placed before `class DreamScheduler` returns the six-key payload, its five numeric values read from the report's own fields. Both full-dream sites call it, and each logs a payload failure at WARNING with its site's name. The micro site (:3290-3301) is unchanged. The Counselor is unchanged.

Rejected, one line each:
- `getattr(report, "episodes_replayed", 0)` at each site: it keeps the duplicated dict that carried the defect twice.
- `getattr` with defaults inside the helper: the `[]` default is what made `len()` look right; `dream_cycle` returns a `DreamReport` on every path.
- A typed `DreamCompleteEvent` (`events.py`:849-854): it declares 3 of the 6 keys; the producer-reader contract is part b's repair.
- A `DreamScheduler` method: the helper reads only the report.
- Part b in this slice: see D1.

## 3. Decisions

| # | Decision | Reason |
|---|---|---|
| D1 | Part a alone; #1820 bf-989 R6 stays open for part b, which moves with R1 and R5 | A full completion newly reaches one filtered listener, the Counselor (`counselor.py`:717), and the unfiltered HXI hub (`api.py`:127), which already receives micro completions of the same type. The Counselor path it starts (re-assessment of intervention targets) already runs on micro completions and calls no `force_dream` (its callers: `commands_memory.py`:93, `counselor.py`:2738). The reminiscence branch stays inert: `retrieval_results` is read at `counselor.py`:1151 and written by no producer. Part b would start sessions from AD-541c concerns that R1 scores from a memoryless recall and that R5 stores on a sovereign-keyed profile |
| D2 | One helper builds the payload for both sites | the defect lived in a dict written twice; one builder gives one place to type and one test reach for both sites |
| D3 | The helper reads `report.<field>` directly | `dream_cycle` is typed `-> DreamReport` and returns one on every path (section 1). The test doubles that reach the emit with an emit function set: `test_dreaming.py`:538 (changed in 6.2) only; the medical-team doubles mock the whole scheduler (`test_medical_team.py`:249-250, :312-314) |
| D4 | A payload failure logs at WARNING, naming its site (`force_dream`, `monitor loop`) | log-and-degrade: the dream and its report stand, and the loss is visible; at DEBUG it hid this loss on every full dream |
| D5 | The existing test is changed in place, with the reason inline, not deleted | its key-set assertion (no reflection-outcome fields, BF-669) stays a contract; its stand-in type was the defect's hiding place |

## 4. Milestone and commit

One commit: 6.1 to 6.5, then `d:/ProbOS/.venv/Scripts/python.exe -P scripts/gen_ad_ledger.py` (no `--online`); stage `docs/development/ad-ledger-snapshot.json` and `docs/development/open-ads-report.md` when they change. Subject: `Dream scheduler builds each full-dream completion from the report's own counts`. No subject carries an `AD-` or `BF-` token or the words close, fix or resolve. Stage explicit paths only.

## 5. Builder: may and may not

- **May:** apply the pairs in order, run `gen_ad_ledger.py`, `git diff --check`, `git diff --stat`.
- **May not:** run tests, commit, edit an unnamed file, add `skip` or a retry, or reword an anchor. If a SEARCH does not match exactly once, stop and report.

## 6. The pairs

### 6.1 `src/probos/cognitive/dreaming.py`

**P1.** SEARCH:
```python
class DreamScheduler:
    """Background scheduler that triggers dream cycles during idle periods."""
```
REPLACE:
```python
def _full_dream_complete_payload(report: DreamReport) -> dict[str, Any]:
    """The ``dream_complete`` payload of a full dream (AD-503; AD-531 and AD-551 fields).

    ``DreamScheduler.force_dream`` and its monitor loop both emit it. The five numeric
    values are the report's own fields: BF-1002 (#1820 bf-989 R6) removed a ``len()`` of
    the ``int`` ``episodes_replayed``, whose ``TypeError`` lost the completion at both sites.
    """
    return {
        "dream_type": "full",
        "duration_ms": report.duration_ms,
        "episodes_replayed": report.episodes_replayed,
        "clusters_found": report.clusters_found,
        "notebook_consolidations": report.notebook_consolidations,
        "convergence_reports_generated": report.convergence_reports_generated,
    }


class DreamScheduler:
    """Background scheduler that triggers dream cycles during idle periods."""
```

**P2.** SEARCH:
```python
            # AD-503: Emit dream complete event
            if self._emit_event_fn:
                try:
                    self._emit_event_fn(
                        "dream_complete",
                        {
                            "dream_type": "full",
                            "duration_ms": getattr(report, "duration_ms", 0),
                            "episodes_replayed": len(getattr(report, "episodes_replayed", [])),
                            "clusters_found": getattr(report, "clusters_found", 0),
                            "notebook_consolidations": getattr(report, "notebook_consolidations", 0),
                            "convergence_reports_generated": getattr(report, "convergence_reports_generated", 0),
                        },
                    )
                except Exception:
                    logger.debug("Dream complete event emission failed", exc_info=True)
```
REPLACE:
```python
            # AD-503: Emit dream complete event
            if self._emit_event_fn:
                try:
                    self._emit_event_fn("dream_complete", _full_dream_complete_payload(report))
                except Exception:
                    # BF-1002: WARNING; at DEBUG this line hid the loss of each full-dream completion.
                    logger.warning("BF-1002: full dream_complete emission failed (force_dream)", exc_info=True)
```

**P3.** SEARCH:
```python
                        # AD-503: Emit dream complete event (monitor loop, full)
                        if self._emit_event_fn:
                            try:
                                self._emit_event_fn(
                                    "dream_complete",
                                    {
                                        "dream_type": "full",
                                        "duration_ms": getattr(report, "duration_ms", 0),
                                        "episodes_replayed": len(getattr(report, "episodes_replayed", [])),
                                        "clusters_found": getattr(report, "clusters_found", 0),
                                        "notebook_consolidations": getattr(report, "notebook_consolidations", 0),
                                        "convergence_reports_generated": getattr(report, "convergence_reports_generated", 0),
                                    },
                                )
                            except Exception:
                                logger.debug("Dream complete event emission failed", exc_info=True)
```
REPLACE:
```python
                        # AD-503: Emit dream complete event (monitor loop, full)
                        if self._emit_event_fn:
                            try:
                                self._emit_event_fn("dream_complete", _full_dream_complete_payload(report))
                            except Exception:
                                # BF-1002: WARNING; at DEBUG this line hid the loss of each full-dream completion.
                                logger.warning("BF-1002: full dream_complete emission failed (monitor loop)", exc_info=True)
```

### 6.2 `tests/test_dreaming.py`

**P4.** SEARCH:
```python
    async def test_full_dream_event_shape_has_no_reflection_outcome_fields(self):
        report = SimpleNamespace(
            duration_ms=1.0,
            episodes_replayed=[],
```
REPLACE:
```python
    async def test_full_dream_event_shape_has_no_reflection_outcome_fields(self):
        # BF-1002 (#1820 bf-989 R6): a real DreamReport. The stand-in was a SimpleNamespace whose
        # episodes_replayed was a list, a type the engine never returns, so len() on the int passed here.
        report = DreamReport(
            duration_ms=1.0,
            episodes_replayed=7,
```

**P5.** SEARCH:
```python
            "notebook_consolidations",
            "convergence_reports_generated",
        }


# ---------------------------------------------------------------------------
# Runtime integration tests
```
REPLACE:
```python
            "notebook_consolidations",
            "convergence_reports_generated",
        }
        assert events[0][1]["episodes_replayed"] == 7


# ---------------------------------------------------------------------------
# Runtime integration tests
```

`SimpleNamespace` stays imported (used at :330); `DreamReport` is imported at :26.

### 6.3 `tests/test_bf1002_full_dream_complete_event.py` (new file)

```python
"""BF-1002 (#1820 bf-989 R6, part a): a full dream's dream_complete event reaches its listeners.

DreamReport.episodes_replayed is an int (types.py). Both full-dream emit sites of DreamScheduler
called len() on it while building the payload inside the emit's try, so at the base no full-dream
completion reached runtime._emit_event; the TypeError was logged at DEBUG. One module helper,
_full_dream_complete_payload, now builds the payload for both sites, and a payload failure logs at
WARNING. The last test crosses the seam: the Counselor's AD-505 forced dream, the scheduler that
startup wired, runtime._emit_event and the Counselor's own subscription (AD-506a).
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from probos.cognitive.counselor import CounselorAssessment
from probos.cognitive.dreaming import DreamScheduler
from probos.cognitive.episodic_mock import MockEpisodicMemory
from probos.config import SystemConfig
from probos.runtime import ProbOSRuntime
from probos.types import DreamReport

_DREAMING_LOGGER = "probos.cognitive.dreaming"
_FULL_KEYS = frozenset({
    "dream_type",
    "duration_ms",
    "episodes_replayed",
    "clusters_found",
    "notebook_consolidations",
    "convergence_reports_generated",
})
_EXPECTED = {
    "dream_type": "full",
    "duration_ms": 12.5,
    "episodes_replayed": 7,
    "clusters_found": 2,
    "notebook_consolidations": 3,
    "convergence_reports_generated": 1,
}


def _report() -> DreamReport:
    """A real report; each count differs, so a swapped or dropped field changes the payload."""
    return DreamReport(
        duration_ms=12.5,
        episodes_replayed=7,
        clusters_found=2,
        notebook_consolidations=3,
        convergence_reports_generated=1,
        reflections_created=4,
    )


async def _settle(predicate: Any, *, timeout: float = 5.0) -> bool:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        if predicate():
            return True
        await asyncio.sleep(0.01)
    return bool(predicate())


class _Engine:
    """Stands in for DreamingEngine: the three methods the scheduler calls."""

    def __init__(self, report: Any) -> None:
        self.report = report
        self.cycles = 0

    async def micro_dream(self) -> dict[str, int]:
        return {"episodes_replayed": 0}  # replays nothing, so the loop emits no micro completion

    async def proactive_procedure_scan(self) -> dict[str, int]:
        return {"evolved": 0}

    async def dream_cycle(self) -> Any:
        self.cycles += 1
        return self.report


def _scheduler(engine: _Engine, events: list[tuple[str, dict[str, Any]]]) -> DreamScheduler:
    scheduler = DreamScheduler(engine, idle_threshold_seconds=0.0, dream_interval_seconds=3600.0)
    scheduler._emit_event_fn = lambda event_type, data: events.append((event_type, data))
    return scheduler


async def _one_monitor_dream(scheduler: DreamScheduler, engine: _Engine) -> None:
    """Run the monitor loop until it has run one full dream (its first tick sleeps 1 s)."""
    scheduler._last_dream_time = time.monotonic() - 7200.0  # the 3600 s interval has passed
    scheduler.start()
    try:
        assert await _settle(lambda: engine.cycles >= 1)
    finally:
        await scheduler.stop()


@pytest.mark.asyncio
async def test_force_dream_emits_the_full_payload_of_a_real_report() -> None:
    events: list[tuple[str, dict[str, Any]]] = []
    report = _report()
    scheduler = _scheduler(_Engine(report), events)

    assert await scheduler.force_dream() is report

    assert events == [("dream_complete", _EXPECTED)]
    assert type(events[0][1]["episodes_replayed"]) is int  # 7.0 == 7, so the equality alone admits a float


@pytest.mark.asyncio
async def test_the_monitor_loop_emits_the_full_payload_of_a_real_report() -> None:
    events: list[tuple[str, dict[str, Any]]] = []
    engine = _Engine(_report())
    scheduler = _scheduler(engine, events)

    await _one_monitor_dream(scheduler, engine)

    assert engine.cycles == 1
    assert events == [("dream_complete", _EXPECTED)]
    assert type(events[0][1]["episodes_replayed"]) is int


@pytest.mark.asyncio
async def test_a_payload_failure_in_force_dream_logs_a_warning_and_returns_the_report(caplog) -> None:
    unreadable = object()  # carries no DreamReport field, so building the payload raises
    events: list[tuple[str, dict[str, Any]]] = []
    scheduler = _scheduler(_Engine(unreadable), events)

    with caplog.at_level(logging.WARNING, logger=_DREAMING_LOGGER):
        assert await scheduler.force_dream() is unreadable

    assert events == []
    assert "BF-1002: full dream_complete emission failed (force_dream)" in caplog.text


@pytest.mark.asyncio
async def test_a_payload_failure_in_the_monitor_loop_logs_a_warning(caplog) -> None:
    unreadable = object()
    events: list[tuple[str, dict[str, Any]]] = []
    engine = _Engine(unreadable)
    scheduler = _scheduler(engine, events)

    with caplog.at_level(logging.WARNING, logger=_DREAMING_LOGGER):
        await _one_monitor_dream(scheduler, engine)

    assert scheduler.last_dream_report is unreadable
    assert events == []
    assert "BF-1002: full dream_complete emission failed (monitor loop)" in caplog.text


@pytest.mark.asyncio
async def test_a_forced_dream_reaches_the_booted_counselor_as_a_full_completion(tmp_path, monkeypatch, caplog) -> None:
    """AD-505 forces the dream and records the agent; AD-506a re-assesses it on the completion."""
    rt = ProbOSRuntime(
        config=SystemConfig(),
        data_dir=tmp_path,
        episodic_memory=MockEpisodicMemory(relevance_threshold=0.3),
    )
    await rt.start()
    try:
        scheduler = rt.dream_scheduler
        assert scheduler is not None
        await scheduler.stop()  # quiesce the monitor so only the forced dream completes
        counselor = rt.registry.get_by_pool("counselor")[0]
        assert counselor._dream_scheduler is scheduler  # wired by finalize, not by this test

        seen: list[dict[str, Any]] = []
        handler = counselor._on_dream_complete

        async def spy(data: dict[str, Any]) -> None:
            seen.append(data)
            await handler(data)

        monkeypatch.setattr(counselor, "_on_dream_complete", spy)
        monkeypatch.setattr(counselor, "_gather_agent_metrics", MagicMock(return_value={
            "trust_score": 0.8, "confidence": 0.7, "hebbian_avg": 0.6,
            "success_rate": 0.9, "personality_drift": 0.05,
        }))
        assess = MagicMock(return_value=MagicMock(wellness_score=0.8))
        monkeypatch.setattr(counselor, "assess_agent", assess)
        monkeypatch.setattr(counselor, "_save_profile_and_assessment", AsyncMock())
        monkeypatch.setattr(counselor, "_post_recommendation_to_ward_room", AsyncMock())
        agent_id = "agent-bf1002"

        def _reassessed() -> bool:
            return any(
                call.kwargs.get("agent_id") == agent_id and call.kwargs.get("trigger") == "post_dream"
                for call in assess.call_args_list
            )

        with caplog.at_level(logging.INFO):
            await counselor._apply_intervention(
                agent_id, "BF1002", CounselorAssessment(agent_id=agent_id, wellness_score=0.2), "intervention",
            )
            assert await _settle(lambda: _reassessed() and agent_id not in counselor._intervention_targets)

        full = [data for data in seen if data.get("dream_type") == "full"]
        assert len(full) == 1
        assert set(full[0]) == _FULL_KEYS
        report = scheduler.last_dream_report
        assert report is not None
        assert type(full[0]["episodes_replayed"]) is int
        assert full[0]["episodes_replayed"] == report.episodes_replayed
        assert "AD-505: Failed to trigger dream cycle" not in caplog.text
        assert "Counselor event handler failed" not in caplog.text
        assert "BF-1002: full dream_complete emission failed" not in caplog.text
    finally:
        await rt.stop()
```

### 6.4 `PROGRESS.md`

**P6.** SEARCH:
```markdown
# ProbOS Progress
```
REPLACE:
```markdown
# ProbOS Progress

**BF-1002 (2026-11-27), #1820 item bf-989 R6, part a -- a full dream's `dream_complete` event reaches its listeners.** `DreamReport.episodes_replayed` is an `int`, and both full-dream emit sites of `DreamScheduler` (`force_dream` and the monitor loop) called `len()` on it while building the payload inside the emit's `try`, so each full-dream completion was lost to a `TypeError` logged at DEBUG; micro-dream completions were not affected. A module helper `_full_dream_complete_payload` (`cognitive/dreaming.py`) now builds the six-key payload for both sites, its five numeric values read from the report's own fields, and a payload failure at either site logs at WARNING with the site's name. A full completion now reaches the Counselor, so the AD-506a re-assessment of an agent that AD-505 sent to a forced dream runs on that dream's completion; at the base it ran only on a later micro completion that replayed episodes. The handler's reminiscence branch is unchanged and still unreachable (#1820 bf-989 R6 part b, open with R1 and R5). `tests/test_dreaming.py::test_full_dream_event_shape_has_no_reflection_outcome_fields` now builds a real `DreamReport` (its stand-in carried a list, a type the engine never returns). New `tests/test_bf1002_full_dream_complete_event.py` (5 tests). Contract `prompts/bf-1002-1820-full-dream-complete-event.md`.
```

### 6.5 `DECISIONS.md`

**P7.** SEARCH (the newest entry: the BF-1001 entry that #1865 added above the AD-1337 follow-up the draft named; anchored on its heading, as this label allows):
```markdown
### BF-1001 -- The live crew-session projection test waits for its first semantic frame by a deadline (2026-11-27, #1861)
```
REPLACE:
```markdown
### BF-1002 -- a full dream's dream_complete event reaches its listeners; one helper builds the payload for both emit sites (2026-11-27, #1820)

- *Scope.* #1820 item bf-989 R6, part a. `cognitive/dreaming.py`: `_full_dream_complete_payload` (new), `DreamScheduler.force_dream`, `DreamScheduler._monitor_loop`. Contract `prompts/bf-1002-1820-full-dream-complete-event.md`.
- *D1.* One module helper builds the full-dream payload for both sites and reads each `DreamReport` field directly. Not `getattr` with an int default at each site (it keeps the dict that held the defect twice), and not a typed `DreamCompleteEvent` (it declares 3 of the 6 keys; the producer-reader contract is part b).
- *D2.* A payload failure at either site logs at WARNING with the site's name; at DEBUG it hid this loss on every full dream.
- *D3.* Part a alone. The reminiscence branch of `Counselor._on_dream_complete` is unchanged and still unreachable: it reads `retrieval_results`, which no producer writes. Part b moves with bf-989 R1 and R5, because the concerns it would act on are scored from a memoryless recall (R1) and stored on a sovereign-keyed profile (R5).
- *Effect.* A full completion now reaches the Counselor, so the AD-506a re-assessment of an agent that AD-505 sent to a forced dream runs on that dream's completion.
- *Reversal.* Revert the commit; no persisted format changes (`DREAM_COMPLETE` is grandfathered in `event_persistence.py`, so events.db holds no row of it). A revert loses each full-dream completion again.

### BF-1001 -- The live crew-session projection test waits for its first semantic frame by a deadline (2026-11-27, #1861)
```

## 7. Consumers

| Contract | Consumer | After the change |
|---|---|---|
| full `dream_complete` envelope | `Counselor._on_event_async` (`counselor.py`:1073) to `_on_dream_complete` (:1117) | receives it; re-assesses intervention targets (:1126-1147); the reminiscence branch (:1149-1162) finds no `retrieval_results`, as today |
| | HXI hub (`api.py`:127, `ws_event_stream.py`:416); `ui/src` has no handler | one more frame per dream interval, of a type micro completions already send |
| | JetStream stream `system.events.>` (`startup/nats.py`:60; publish `runtime.py`:1990-1994) | one more message per full dream |
| | durable router (`runtime.py`:1977-1979) | not routed (`event_persistence.py`:233, :471-473): no row |
| | Night Orders (`runtime.py`:1971) | not a trigger (`watch_rotation.py`:218-221) |
| booted tests that force a dream | `test_dreaming.py`:637, :678, :1050; `test_hxi_events.py`:198 (unfiltered listener, filters `system_mode`) | they now also see a `dream_complete`; none asserts its absence |
| scanners of `dreaming.py` | each test the `rg` command of 8.2 lists | must pass unchanged |

## 8. Gates (the orchestrator runs all of them)

### 8.1 Oracle tree, before the Builder starts
- Each SEARCH of section 6 counted at its turn: 1 each; the new file does not exist.
- A/B: the new file plus 6.2 on the base without 6.1: all 6 items fail. `force_dream` and the monitor payload tests find `events == []`. Both warning tests fail at `events == []`, because the base's `getattr` defaults build a payload from `object()`. The booted test's `_settle` times out. The changed test fails at `len(events) == 1`. On the candidate all 6 pass.

### 8.2 Focused checks on the candidate
```text
d:/ProbOS/.venv/Scripts/pytest.exe tests/test_bf1002_full_dream_complete_event.py tests/test_dreaming.py tests/test_hxi_events.py tests/test_counselor_activation.py tests/test_graduated_zones.py tests/test_bf921_counselor_event_delivery.py tests/test_counselor_therapeutic.py tests/test_ad561_intervention_classification.py tests/test_ad637d_system_events_nats.py tests/test_ad1195_event_persistence_contract.py tests/test_ad583_wrong_convergence.py tests/test_medical_team.py -n 0 -q
rg -l -g 'test_*.py' -e 'rglob\("\*\.py"\)' -e 'os\.walk\(' -e 'dreaming\.py' -e 'cognitive\.dreaming' -e 'DreamScheduler' tests
d:/ProbOS/.venv/Scripts/pytest.exe <each file the rg command lists> -n 8 -q
d:/ProbOS/.venv/Scripts/python.exe -P scripts/gen_ad_ledger.py --check
d:/ProbOS/.venv/Scripts/python.exe scripts/run_test_gate.py --preflight-only --label bf-1002
```
The first line names the consumers that the `rg` pattern does not list (`test_hxi_events.py`, `test_counselor_activation.py`, `test_graduated_zones.py`, `test_counselor_therapeutic.py`, `test_ad637d_system_events_nats.py`, `test_ad1195_event_persistence_contract.py`, `test_ad583_wrong_convergence.py`, `test_medical_team.py`). Retriage a parallel failure at `-n 0`.

### 8.3 Mutation rows (one at a time on `dreaming.py`, file restored byte for byte)

Each locator is a whole stripped line of the candidate. `self._emit_event_fn("dream_complete", _full_dream_complete_payload(report))` occurs twice: the 1st is `force_dream`, the 2nd the monitor loop. The other locators occur once.

| ID | Line (stripped) | Becomes | Killed by |
|---|---|---|---|
| M1 | `"episodes_replayed": report.episodes_replayed,` | `"episodes_replayed": len(report.episodes_replayed),` | force_dream payload, monitor payload, booted, changed test |
| M2 | `"episodes_replayed": report.episodes_replayed,` | `"episodes_replayed": float(report.episodes_replayed),` | force_dream and monitor payload (`type is int`), booted |
| M3 | `"clusters_found": report.clusters_found,` | (line deleted) | force_dream and monitor payload, booted (`_FULL_KEYS`), changed test (key set) |
| M4 | `"dream_type": "full",` | `"dream_type": "micro",` | force_dream and monitor payload, booted (no full payload seen) |
| M5 | `"duration_ms": report.duration_ms,` | `"duration_ms": 0,` | force_dream and monitor payload |
| M6 | emit call (1st of 2) | `self._emit_event_fn("dream_complete", {"dream_type": "full"})` | force_dream payload, booted (`_FULL_KEYS`), changed test |
| M7 | emit call (2nd of 2) | `self._emit_event_fn("dream_complete", {"dream_type": "full"})` | monitor payload |
| M8 | `logger.warning("BF-1002: full dream_complete emission failed (force_dream)", exc_info=True)` | the same with `logger.debug(` | force_dream warning test |
| M9 | `logger.warning("BF-1002: full dream_complete emission failed (monitor loop)", exc_info=True)` | the same with `logger.debug(` | monitor-loop warning test |

### 8.4 The gate
`d:/ProbOS/.venv/Scripts/python.exe scripts/run_test_gate.py --label bf-1002 --receipt logs/gates/bf-1002.receipt.json` once on the committed head (batched per the orchestrator's rules if it rides with other issues).

## 9. Diff Reviewer: properties to verify

The change claims that a full dream's completion reaches `runtime._emit_event` with six keys whose counts are the report's ints, and that a payload failure is visible at WARNING. The consumer that must accept it: `Counselor._on_dream_complete` through the runtime's dispatch.
1. Both full-dream sites call `_full_dream_complete_payload(report)`; no other line in `dreaming.py` builds a full-dream payload; the micro site (`"dream_type": "micro"`) is byte-identical to the base.
2. The helper reads `report.<field>` for the five values, with no `len()` and no `getattr`, and returns exactly the six keys of the base payload.
3. Each `except` logs at WARNING with its site's name and `exc_info=True`; the dream, `_post_dream_fn` and the return value are unaffected by a payload failure.
4. `counselor.py`, `events.py`, `runtime.py` and `types.py` are byte-identical to the base.
5. The changed test keeps its key-set assertion and gains the value assertion; nothing is deleted.
6. The booted test drives `_apply_intervention` (not a hand-set target) and asserts the full payload's key set and the int type.
7. ASCII and LF in the new text; no file outside section 4 changes.
8. Each absolute word of the new text (each, every, no, only, none) holds against section 1, section 7 and the Absence Verified list.

## 10. Verified Against Codebase (2026-11-26, tree `6539f04d`; the files of 6.1 and 6.2 and `types.py` are identical to `c3721a2d`)

- `dreaming.py`: `from typing import TYPE_CHECKING, Any` :15; `from probos.types import (DreamReport, ...)` :50-57; `logger` :62; `micro_dream` :231 (returns :239-262, `len(episodes)` :305); `dream_cycle` :420 (returns :478, :1867; the report :1758-1759); `partial_report` :1735 (not returned); `class DreamScheduler:` :3129 and its docstring :3130; `__init__` :3132-3157 (`_emit_event_fn` :3157); `start` :3171-3177; `stop` :3179-3188; `force_dream` :3231-3270 (emit :3245-3260); `_monitor_loop` :3272 (`asyncio.sleep(1.0)` :3276, micro :3284-3308, proactive scan :3311-3322, full :3324-3370, emit :3344-3359).
- `types.py`: `DreamReport` :892-896 (`episodes_replayed: int = 0`), `duration_ms` :901, `clusters_found` :902, `notebook_consolidations` :936, `convergence_reports_generated` :938, `reflections_created` :967; every field has a default.
- `counselor.py`: `CounselorAssessment` :73-97 (all fields defaulted); `_intervention_targets` :587; `initialize` :666-741 (subscription :711-741, `DREAM_COMPLETE` :717); `_on_event_async` :1064-1115 (dispatch :1073-1074, the WARNING :1113-1115); `_on_dream_complete` :1117-1162; `_save_profile_and_assessment` :2223; `_post_recommendation_to_ward_room` :2589; `_apply_intervention` :2694-2781 (`force_dream` :2738, target added :2740); `assess_agent` :2785.
- `finalize.py`: Counselor `initialize(...)` :6274-6287 (`add_event_listener_fn=runtime.add_event_listener` :6281, `dream_scheduler=` :6285). `startup/dreaming.py`:211 sets `dream_scheduler._emit_event_fn`; `runtime.py`:3277 passes `self._emit_event`.
- `runtime.py`: `__init__` kwargs :659-662; `add_event_listener` :1733-1752; `register_live_event_listener` :1760; `_emit_event` :1952-1997; `_emit_event_local` :1999-2020 (async listener as a task :2005-2011).
- Tests: `test_dreaming.py` imports :7, :15, :18, :26; the changed test :521-553; the section header after it :556-557; `SimpleNamespace` also at :330. `test_bf921_counselor_event_delivery.py`: `_settle` :72-79, the booted pattern :182-214. `test_graduated_zones.py`:533-550 (the re-assessment stubs reused here). `test_hxi_events.py`:181-204.

### Absence Verified (2026-11-26)

- CLAIM: the two full-dream sites are the only `len(getattr(` of a report in `src`. RUN: Grep `len\(getattr\(\s*(report|dream_report|self\._last_dream_report)` over `src/probos`. FOUND: `dreaming.py`:3253, :3352. HOLDS.
- CLAIM: each return of `dream_cycle` is a `DreamReport` with an int count. RUN: Grep `^\s+return\b` over `dreaming.py`, read :420-481 and :1728-1767. FOUND in :420-1868: :478, :996 (a nested function), :1867. HOLDS.
- CLAIM: `retrieval_results` is written by no producer. RUN: Grep `retrieval_results` over `src/probos`. FOUND: `counselor.py`:1151, :1152, :1155 (reads). HOLDS.
- CLAIM: `dream_type` has no reader. RUN: Grep `dream_type` over `src/probos`. FOUND: `events.py`:852 and the three emitters. HOLDS.
- CLAIM: `force_dream` has two callers in `src`. RUN: Grep `force_dream\(` over `src/probos`. FOUND: `commands_memory.py`:93, `counselor.py`:2738. HOLDS.
- CLAIM: the Counselor is the one filtered listener for `dream_complete`, and the HXI live listener is the only unfiltered registration. RUN: Grep `(?i)dream_complete` over the repo; Grep `add_event_listener\b`, `\badd_listener\(` and `register_live_event_listener\(` over `src/probos`. FOUND: `counselor.py`:717; every other registration passes `event_types`; `api.py`:127 passes none. HOLDS.
- CLAIM: `ui` has no `dream_complete` handler. RUN: Grep `(?i)dream_?complete` over `ui` excluding `node_modules`. FOUND: 0. HOLDS.
- CLAIM: no source-scan test pins the edited lines. RUN: Grep `Dream complete event emission failed|len\(getattr\(report|getsource\((DreamScheduler|dreaming)` over `tests`. FOUND: none; `test_bf165_stasis_cluster.py`:89 and `test_bf941_cold_start_detector.py`:239 scan `startup/dreaming.py` and the module for other strings. HOLDS.
- CLAIM: the one test double that reaches the full-dream emit with an emit function is `test_dreaming.py`:538. RUN: Grep `scheduler\._emit_event_fn|DreamScheduler\(` and `dream_cycle\s*=` over `tests`. FOUND: :538 only sets it; `test_medical_team.py`:249, :312 replace the engine of a `MagicMock` scheduler. HOLDS.

## 11. What this does NOT change

- The micro-dream completion payload (`dreaming.py`:3290-3301).
- `Counselor._on_dream_complete`, its intervention-target guard and its reminiscence branch (part b).
- `DreamCompleteEvent` (`events.py`:849-854), still built by no producer.
- `DREAM_COMPLETE`'s persistence class (grandfathered; no events.db row).
- `dream_cycle`, its report and the shell's `/dream now` output.

## 12. Issue text (#1820, on merge)

Wave comment:

```text
Part a of bf-989 R6 shipped as BF-1002 (PR #<PR>, contract prompts/bf-1002-1820-full-dream-complete-event.md); the item stays open for part b.
- bf-989 R6 part a: both full-dream emit sites of DreamScheduler (force_dream and the monitor loop) called len() on the int DreamReport.episodes_replayed inside the emit's try, so each full-dream completion was lost to a TypeError logged at DEBUG. A module helper, _full_dream_complete_payload, now builds the six-key payload for both sites, its five numeric values read from the report's own fields, and a payload failure logs at WARNING with the site's name. A full completion now reaches the Counselor: a booted test drives the AD-505 forced dream and sees the AD-506a re-assessment run on that dream's completion. tests/test_dreaming.py's payload test now builds a real DreamReport (its stand-in carried a list). New tests/test_bf1002_full_dream_complete_event.py (5 tests); 9 mutation rows killed.
- bf-989 R6 part b (open): the reminiscence branch of _on_dream_complete still sits behind the empty intervention-target return and reads retrieval_results, which no producer writes. It moves with R1 and R5.
```

Replacement for the bf-989 R6 item (the box stays unticked):

```text
- [ ] **bf-989 R6 (P3, Medium; reach: ordinary, the post-dream trigger never starts a session; pre-existing, not a regression; found by BF-989's review round 2 and reproduced by execution): the post-dream reminiscence route is unreachable. Part a repaired (BF-1002, PR #<PR>); part b open.**
  - **Part a (repaired, BF-1002):** both full-dream emit sites of `DreamScheduler` called `len()` on the int `DreamReport.episodes_replayed`, so each full-dream completion was lost to a `TypeError`. One helper now builds the payload from the report's fields, and a failure logs at WARNING. A full completion now reaches `Counselor._on_dream_complete`.
  - **Part b (open):** the Counselor's reminiscence branch (`src/probos/cognitive/counselor.py`, `_on_dream_complete`) sits behind the empty intervention-target return and reads `retrieval_results`, which no producer writes. Direct initiation works (a session starts).
  - **Smallest repair (part b):** a producer-reader contract for the concern agents the post-dream trigger acts on, and the reminiscence branch separated from the intervention guard. Land it with R1 (the concerns come from a memoryless recall) and R5 (they are stored on a sovereign-keyed profile), or a session starts on a false or invisible concern.
  - **Nearest neighbour:** R1 and R5 on this issue; `force_dream` appears in #1523 only for another subject (F-695).
```

PR title: `Full dream completions reach their listeners: the scheduler reads the report's own counts`.

## 13. Prior art and blind spots

- Internal: AD-503 (the event and the Counselor's subscription), AD-531 and AD-551 (the added fields; AD-551 edited the payload in "3 locations", the duplicate that carried the defect), AD-505 and AD-506a (the forced dream and the post-dream re-assessment), BF-921 (#1636; the Counselor's handlers first ran there, and a failing handler logs at WARNING), BF-989 (found it in review round 2).
- External search skipped: this is ProbOS-specific event plumbing with no outside analogue. No row of `docs/research/reference-projects.md` was examined (date used: 2026-11-26).
- Blind spots:
  - The AD-505 to AD-506a ordering depends on the handler running after `_apply_intervention` adds the target. It holds by construction (no await between `counselor.py`:2738 and :2740; the listener runs as a task or after a NATS publish task), and the booted test pins it.
  - A `dream_cycle` that raises still emits no completion (unchanged).
  - events.db holds no `dream_complete` row, so a live vessel's confirmation is the absence of the BF-1002 WARNING plus the Counselor's "AD-506a: Post-dream improvement" INFO lines after a forced dream.

## 14. Acceptance criteria

1. The A/B of 8.1 holds: 6 items red on the base, green on the candidate; M1 to M9 are killed as 8.3 says.
2. The focused checks of 8.2 pass, the `rg` list included; the pre-existing tests in those files pass unchanged.
3. `git diff --check` is clean, the new text is ASCII, and no file outside section 4 changes.
4. The Diff Reviewer approves against section 9.
5. One receipted broad gate on the committed head is green.
6. Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.
