# AD-528: Ground-Truth Task Verification (Anti-Fabrication)

**Status:** Ready for builder
**Dependencies:** Reads `BookingJournal` (`workforce.py:738`) for completion artifacts. Coordinates with AD-451 ReconciliationEscalator (`cognitive/validation_framework.py`, post-Wave 6) but operates independently. Reads existing AD-592 confabulation guard pattern at `cognitive_agent.py:4157` for context; does NOT modify it.
**Estimated tests:** ~14
**Risk:** High -- trust/safety critical. The "Agents of Chaos" failure-mode countermeasure cited in the roadmap. Acceptance criteria below requires episode storage so future audits can retrospectively verify the verification.

---

## Problem

Agents can claim task completion without producing artifacts that prove the work was done. AD-592 (cognitive_agent.py:4157) added a CONFABULATION GUARD instruction to keep LLMs from inventing numbers in their outputs, but there is no runtime-side verification that:

1. **Claimed completions match journal artifacts.** A `WorkItem` marked `completed` should have a corresponding `BookingJournal` entry with non-zero `duration_seconds` AND a non-empty `tokens_consumed > 0` (or a justified zero, e.g. cached responses).
2. **Reported actions match event log entries.** When an agent emits "I read /tmp/x.py and summarized it", there should be a `read_file` event in the audit log within the relevant time window.
3. **Verifications themselves are auditable.** A future audit must be able to retrospectively verify why a verdict was reached.

`grep -rn "GroundTruthVerifier\|fabrication_score\|task_verification" src/probos/` returns no class definitions today.

The closest existing surface is AD-451's `ReconciliationEscalator` (`cognitive/validation_framework.py`, Wave 6) -- but reconciliation resolves disagreement *between two verifiers* on an action's outcome. AD-528 asks a different question: *did the action happen at all*?

## Solution Overview

Create `src/probos/cognitive/ground_truth.py` (new) with three small additions:

1. **`GroundTruthVerifier`** -- given a `(booking_id, claimed_summary)` pair, queries `BookingJournal` and `event_log` for corroborating evidence. Returns a `GroundTruthResult` with `verified: bool`, `score: float [0..1]`, and `signals: list[str]` (which evidence channels matched). Read-only over existing state.
2. **`VerificationEpisodeWriter`** -- writes each `GroundTruthResult` to the existing episodic memory (`runtime.episodic_memory`) so future audits can replay the verification context. Read-only of episodic interface; writes via `episodic_memory.store(episode)`.
3. **Event emission** -- `VERIFICATION_PASSED` on success, `VERIFICATION_FAILED` on score below threshold. Listeners (operator dashboards, future AD-528b active rejection) consume these.

This is **policy + diagnostics layered on existing surfaces.** AD-528 does NOT modify `BookingJournal`, does NOT change `event_log` schema, does NOT actively reject claimed completions, does NOT integrate with consensus voting. v1 observes; v2 (AD-528b) will add active rejection and trust-network feedback.

**v1 scope (no-theater discipline per Wave 5 retrospective convention #7):**

- **`GroundTruthVerifier`** -- real-work scoring service. Reads booking journals + event log; computes a 0-1 confidence score; emits real events. Not a stub.
- **`VerificationEpisodeWriter`** -- real-work episode storage. Writes one episode per verification so audits can replay.
- **Event emission** -- real-work emit; consumers operate on real data.

Two deferred:

- **Active rejection / quarantine of low-score completions** -- deferred to AD-528b. v1 emits but does not reject, per coordinator-then-dispatch (Wave 5 retrospective convention #3).
- **Trust-network feedback (record_outcome on verifier disagreement)** -- deferred to AD-528c. v1 keeps trust scoring out of the loop until the signal is exercised in production.

**Coordination with AD-451 ReconciliationEscalator:** AD-528 does NOT consume or be consumed by ReconciliationEscalator in v1. They cover orthogonal questions (did it happen at all? vs which of two verifiers do we trust?). A future AD-528b may emit a VerificationResult that ReconciliationEscalator can ingest as a third opinion -- but v1 does not wire that. Documented in "What This Does NOT Change".

---

## Section 0: Event Types

Add to `src/probos/events.py`:

```
VERIFICATION_PASSED = "verification_passed"  # AD-528
VERIFICATION_FAILED = "verification_failed"  # AD-528
```

Two new values. Verified absent via `grep -n "VERIFICATION_PASSED\|VERIFICATION_FAILED" src/probos/events.py` (no matches).

---

## Section 1: `GroundTruthResult` and `GroundTruthVerifier`

**File:** `src/probos/cognitive/ground_truth.py` (new)

```python
"""AD-528: Ground-Truth Task Verification.

Cross-references claimed task completions against BookingJournal entries
and event_log audit records. Returns a confidence score and a list of
signals that matched (or didn't). Read-only over existing state in v1;
active rejection deferred to AD-528b.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from probos.events import EventType

if TYPE_CHECKING:
    from probos.workforce import BookingJournal

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class GroundTruthResult:
    """Outcome of a ground-truth verification."""

    verified: bool
    score: float           # 0.0 (no evidence) to 1.0 (all signals matched)
    signals: list[str] = field(default_factory=list)
    booking_id: str = ""
    agent_id: str = ""
    claimed_summary: str = ""
    completed_at: float = 0.0


class GroundTruthVerifier:
    """Score whether a claimed task completion is corroborated by artifacts.

    v1 signals:
      1. journal_present  -- a BookingJournal entry exists for the booking_id.
      2. duration_nonzero -- journal duration_seconds > 0 (work happened).
      3. tokens_recorded  -- journal tokens_consumed > 0 OR billable=False
                             (cached/free completion is acceptable).
      4. event_within_window -- at least one event in event_log for the
                                agent_id within [completed_at - window, completed_at].

    Score = sum of matched signals / total signals. Threshold default 0.75
    (3 of 4 must match for `verified=True`).

    No mutation. Each verify() call queries the existing surfaces and
    returns a fresh GroundTruthResult.
    """

    DEFAULT_THRESHOLD = 0.75
    DEFAULT_EVENT_WINDOW_SECONDS = 600.0

    def __init__(
        self,
        *,
        runtime: Any,
        emit_event: Any | None = None,
        threshold: float = DEFAULT_THRESHOLD,
        event_window_seconds: float = DEFAULT_EVENT_WINDOW_SECONDS,
    ) -> None:
        self._runtime = runtime
        self._emit_event = emit_event
        self._threshold = threshold
        self._event_window = event_window_seconds

    async def verify(
        self,
        *,
        booking_id: str,
        agent_id: str,
        claimed_summary: str,
        completed_at: float | None = None,
    ) -> GroundTruthResult:
        completed_at = completed_at if completed_at is not None else time.time()
        signals: list[str] = []
        max_signals = 4

        journal_entry = await self._fetch_journal(booking_id)
        if journal_entry is not None:
            signals.append("journal_present")
            duration = float(getattr(journal_entry, "duration_seconds", 0.0) or 0.0)
            if duration > 0.0:
                signals.append("duration_nonzero")
            tokens = int(getattr(journal_entry, "tokens_consumed", 0) or 0)
            billable = bool(getattr(journal_entry, "billable", True))
            if tokens > 0 or not billable:
                signals.append("tokens_recorded")

        if await self._has_recent_event(agent_id, completed_at):
            signals.append("event_within_window")

        score = len(signals) / max_signals
        verified = score >= self._threshold
        result = GroundTruthResult(
            verified=verified,
            score=score,
            signals=signals,
            booking_id=booking_id,
            agent_id=agent_id,
            claimed_summary=claimed_summary,
            completed_at=completed_at,
        )
        self._emit(result)
        return result

    async def _fetch_journal(self, booking_id: str) -> "BookingJournal | None":
        rt = self._runtime
        if rt is None or not booking_id:
            return None
        wf = getattr(rt, "workforce", None)
        if wf is None:
            return None
        try:
            entries = await wf.get_booking_journal(booking_id)
        except Exception:
            logger.debug(
                "AD-528: get_booking_journal failed (booking_id=%s)",
                booking_id, exc_info=True,
            )
            return None
        for entry in entries or []:
            if getattr(entry, "journal_type", "") == "working":
                return entry
        # Fall back to first entry if no "working" entry found
        return (entries[0] if entries else None)

    async def _has_recent_event(self, agent_id: str, completed_at: float) -> bool:
        rt = self._runtime
        if rt is None or not agent_id:
            return False
        log = getattr(rt, "event_log", None)
        if log is None:
            return False
        try:
            events = await log.query(agent_id=agent_id, limit=200)
        except Exception:
            logger.debug(
                "AD-528: event_log.query failed (agent_id=%s)",
                agent_id, exc_info=True,
            )
            return False
        cutoff_low = completed_at - self._event_window
        cutoff_high = completed_at + 5.0  # small forward slack
        for event in events or []:
            ts = float(event.get("timestamp", 0) or 0)
            if cutoff_low <= ts <= cutoff_high:
                return True
        return False

    def _emit(self, result: GroundTruthResult) -> None:
        if not self._emit_event:
            return
        et = EventType.VERIFICATION_PASSED if result.verified else EventType.VERIFICATION_FAILED
        try:
            self._emit_event(
                et,
                {
                    "verified": result.verified,
                    "score": result.score,
                    "signals": list(result.signals),
                    "booking_id": result.booking_id,
                    "agent_id": result.agent_id,
                    "completed_at": result.completed_at,
                },
            )
        except Exception:
            logger.warning(
                "AD-528: %s emit failed (booking_id=%s, agent_id=%s)",
                et.value, result.booking_id, result.agent_id, exc_info=True,
            )
```

---

## Section 2: `VerificationEpisodeWriter`

**File:** `src/probos/cognitive/ground_truth.py` (continued)

```python
class VerificationEpisodeWriter:
    """Writes one episodic record per ground-truth verification.

    Records survive into episodic memory so future audits can replay why
    a verdict was reached. v1 writes only -- no read API; consumers query
    via the standard episodic memory interfaces.

    Stateless on construction. Each `write(result)` call constructs a typed
    `Episode` (per `types.py:411`) with verification metadata embedded in
    the `dag_summary` dict field, and persists via
    `episodic_memory.store(episode)`.
    """

    def __init__(self, *, runtime: Any) -> None:
        self._runtime = runtime

    async def write(self, result: GroundTruthResult) -> bool:
        rt = self._runtime
        if rt is None:
            return False
        em = getattr(rt, "episodic_memory", None)
        if em is None:
            return False
        # AD-528: construct a typed Episode (verified at types.py:411).
        # Verification metadata embedded in dag_summary (the canonical
        # structured-payload field). source="direct" matches MemorySource.DIRECT
        # (verified at types.py:344) -- the verifier directly observed the
        # journal/event-log evidence.
        from probos.types import Episode, MemorySource
        episode = Episode(
            timestamp=time.time(),
            user_input=result.claimed_summary[:1000],  # truncate to avoid bloat
            agent_ids=[result.agent_id] if result.agent_id else [],
            dag_summary={
                "kind": "ground_truth_verification",
                "booking_id": result.booking_id,
                "verified": result.verified,
                "score": result.score,
                "signals": list(result.signals),
                "completed_at": result.completed_at,
            },
            source=MemorySource.DIRECT.value,
            importance=7 if not result.verified else 4,  # failed verifications matter more
            correlation_id="",
        )
        try:
            await em.store(episode)
            return True
        except Exception:
            logger.warning(
                "AD-528: episode store failed (booking_id=%s, agent_id=%s)",
                result.booking_id, result.agent_id, exc_info=True,
            )
            return False
```

> Builder note: `episodic_memory.store(episode: Episode)` is the canonical write path (verified at `cognitive/episodic.py:942`). The `Episode` dataclass is at `types.py:411` (frozen, all fields default). The `MemorySource` enum is at `types.py:342`; `DIRECT = "direct"` matches the AD-541 "agent personally experienced this" semantic for verifications. Verification-metadata is stored in `dag_summary` (a `dict[str, Any]` field) rather than fabricating new Episode fields. The `importance=7` for failed verifications biases retention toward audit-relevant cases per AD-598 importance scoring.

---

## Section 3: Add EventTypes

**File:** `src/probos/events.py`

SEARCH:
```python
    INFODYNAMIC_REPORT = "infodynamic_report"  # AD-491
```

REPLACE:
```python
    INFODYNAMIC_REPORT = "infodynamic_report"  # AD-491
    VERIFICATION_PASSED = "verification_passed"  # AD-528
    VERIFICATION_FAILED = "verification_failed"  # AD-528
```

> Builder note: anchor `INFODYNAMIC_REPORT` is verified post-AD-491 (Wave 6). Fallback chain terminates at `AGENT_SELF_NAMED = "agent_self_named"  # AD-499` (line 190).

---

## Section 4: Add `GroundTruthConfig`

**File:** `src/probos/config.py`

```python
class GroundTruthConfig(BaseModel):
    """Ground-truth task verification configuration (AD-528)."""

    enabled: bool = True
    threshold: float = Field(default=0.75, ge=0.0, le=1.0)
    event_window_seconds: float = Field(default=600.0, ge=10.0)
    write_episode: bool = True
```

Wire into `SystemConfig`:

SEARCH:
```python
    infodynamic: InfodynamicConfig = InfodynamicConfig()  # AD-491
```

REPLACE:
```python
    infodynamic: InfodynamicConfig = InfodynamicConfig()  # AD-491
    ground_truth: GroundTruthConfig = GroundTruthConfig()  # AD-528
```

> Builder note: anchor-chain fallback (next-anchor if predecessor hasn't landed):
> 1. `infodynamic: InfodynamicConfig` (AD-491, post-Wave 6).
> 2. `degradation: DegradationConfig` (AD-459, post-Wave 6).
> 3. `engineering: EngineeringConfig` (AD-457, post-Wave 6).
> 4. `validation_framework: ValidationFrameworkConfig` (AD-451, post-Wave 6).
> 5. `orders: OrdersConfig = OrdersConfig()  # AD-440` (config.py:1593) -- always-available terminal fallback.

---

## Section 5: Wire into startup

**File:** `src/probos/startup/finalize.py`

Place near the existing AD-491 InfodynamicProbe block:

```python
    # AD-528: Ground-Truth Task Verification (v1: read-only scoring + emit;
    # active rejection deferred to AD-528b)
    if config.ground_truth.enabled:
        from probos.cognitive.ground_truth import (
            GroundTruthVerifier,
            VerificationEpisodeWriter,
        )
        runtime.ground_truth_verifier = GroundTruthVerifier(
            runtime=runtime,
            emit_event=runtime.emit_event,
            threshold=config.ground_truth.threshold,
            event_window_seconds=config.ground_truth.event_window_seconds,
        )
        if config.ground_truth.write_episode:
            runtime.verification_episode_writer = VerificationEpisodeWriter(
                runtime=runtime,
            )
        else:
            runtime.verification_episode_writer = None
        logger.info(
            "AD-528: GroundTruthVerifier wired (threshold=%.2f, window=%.0fs)",
            config.ground_truth.threshold,
            config.ground_truth.event_window_seconds,
        )
```

> Verify-first: `runtime.workforce`, `runtime.event_log`, `runtime.episodic_memory`, and `runtime.emit_event` are all public surfaces today (verified). `runtime.ground_truth_verifier` and `runtime.verification_episode_writer` are published as public attributes per Wave 5 retrospective convention #1.

---

## Section 6: Add cross-layer exception entry

**File:** `tests/test_layer_boundaries.py`

`cognitive/ground_truth.py` imports `BookingJournal` from `probos.workforce` under `TYPE_CHECKING`. The cognitive layer does not include `workforce` (a top-level module) in its `ALLOWED_IMPORTS`, so the test will flag this as a violation. Add a documented exception entry mirroring the BF-085 / AD-451 precedent.

SEARCH:
```python
    # AD-451: cognitive → agents.red_team — TYPE_CHECKING-only type annotation
    # for TwoStageVerifier wrapper; runtime dependency injected via constructor.
    ("cognitive/validation_framework.py", "probos.agents.red_team"),
```

REPLACE:
```python
    # AD-451: cognitive → agents.red_team — TYPE_CHECKING-only type annotation
    # for TwoStageVerifier wrapper; runtime dependency injected via constructor.
    ("cognitive/validation_framework.py", "probos.agents.red_team"),
    # AD-528: cognitive → workforce — TYPE_CHECKING-only type annotation for
    # BookingJournal; runtime read goes through `runtime.workforce` public
    # attribute injection. Mirrors BF-085 / AD-451 precedent.
    ("cognitive/ground_truth.py", "probos.workforce"),
```

> Verify-first: `tests/test_layer_boundaries.py` ALLOWED_EXCEPTIONS structure verified at line 53. The AD-451 entry verified post-Wave 6 commit `4ed9ab2`.

---

## Tests

**File:** `tests/test_ad528_ground_truth.py`

14 tests using `_FakeRuntime` stubs:

1. `test_event_type_verification_passed_exists` -- value matches.
2. `test_event_type_verification_failed_exists` -- value matches.
3. `test_ground_truth_config_defaults` -- `GroundTruthConfig()` defaults: `enabled=True`, `threshold=0.75`, `event_window_seconds=600.0`, `write_episode=True`.
4. `test_verify_no_runtime_returns_unverified` -- `runtime=None` -> all 4 signals fail, score=0, verified=False. `@pytest.mark.asyncio`.
5. `test_verify_full_match_passes` -- fake workforce + journal entry with duration_seconds=10, tokens_consumed=500; fake event_log returns event in window -> all 4 signals; score=1.0; verified=True; emit fires `VERIFICATION_PASSED`. `@pytest.mark.asyncio`.
6. `test_verify_journal_missing_fails` -- empty journal entries; event in window -> only `event_within_window` signal; score=0.25; verified=False; emit fires `VERIFICATION_FAILED`. `@pytest.mark.asyncio`.
7. `test_verify_zero_duration_fails_duration_signal` -- journal exists with duration_seconds=0 -> `journal_present` matches but `duration_nonzero` does not. `@pytest.mark.asyncio`.
8. `test_verify_billable_false_passes_tokens_signal` -- journal exists, tokens_consumed=0 but billable=False (cached) -> `tokens_recorded` signal matches. `@pytest.mark.asyncio`.
9. `test_verify_event_outside_window_fails_event_signal` -- event timestamp older than window -> `event_within_window` does not match. `@pytest.mark.asyncio`.
10. `test_verify_threshold_boundary` -- score exactly equal to threshold -> verified=True (>= comparison). `@pytest.mark.asyncio`.
11. `test_verify_emits_failed_event_with_signals_list` -- failure path -> emit payload contains `signals` list; `score`; `booking_id`; `agent_id`. `@pytest.mark.asyncio`.
12. `test_episode_writer_stores_typed_episode` -- fake `episodic_memory` with `store(...)` mock; `write(result)` returns True; mock.store called once; the argument passed is an `Episode` instance (typed dataclass), with `dag_summary["kind"] == "ground_truth_verification"`, `dag_summary["score"] == result.score`, and `agent_ids == [result.agent_id]`. `@pytest.mark.asyncio`.
13. `test_episode_writer_no_runtime_returns_false` -- `runtime=None` -> `write()` returns False without crash. `@pytest.mark.asyncio`.
14. `test_episode_writer_handles_missing_episodic_memory` -- runtime without `episodic_memory` attribute -> `write()` returns False without crash. `@pytest.mark.asyncio`.

Each test uses `_FakeRuntime` stubs with `MagicMock` async methods. No shared mutable state. Tests decorated `@pytest.mark.asyncio` per the standing pattern.

---

## What This Does NOT Change

- `BookingJournal` (`workforce.py:738`) is unchanged. AD-528 reads `duration_seconds`, `tokens_consumed`, `billable`, `journal_type`.
- `Workforce.get_booking_journal()` is unchanged (verified at `workforce.py:1514`).
- `event_log.py` is unchanged. AD-528 calls existing `query(agent_id=, limit=)` (verified at `substrate/event_log.py:132`).
- `episodic_memory` interface is read-only consumed via `store(episode)`; no schema changes.
- AD-451's `ReconciliationEscalator` (`cognitive/validation_framework.py`) is NOT integrated in v1. AD-528 and AD-451 cover orthogonal questions:
  - **AD-451:** which of two verifiers do we trust on the same outcome?
  - **AD-528:** did the action happen at all?

  A future AD-528b may emit a `VerificationResult` that ReconciliationEscalator can ingest as a third opinion -- v1 does not wire that.
- AD-592's confabulation guard (`cognitive_agent.py:4157`) is unchanged. AD-528 is a runtime verification surface; AD-592 is an LLM prompt surface. Orthogonal.
- **Active rejection / quarantine** of low-score completions deferred to AD-528b. v1 emits but does not reject.
- **Trust-network feedback** (`record_outcome`) deferred to AD-528c. v1 keeps trust scoring out of the loop.
- v1 emits `VERIFICATION_FAILED` events but no production handler currently consumes them. Operator dashboards and AD-528b active rejection will wire consumers.

---

## Tracking

- `PROGRESS.md`: add `AD-528 CLOSED. Ground-Truth Task Verification (v1 observation; active rejection AD-528b)...`
- `docs/development/roadmap.md`: flip AD-528 status from `*(planned)*` to `*(complete)*` near line 6489.
- `DECISIONS.md`: optional entry recording the v1-observation + AD-528b-active-rejection scope decision.

---

## Pre-Commit Sanity Check (HARD RULE)

```pwsh
git diff --cached --stat
```

If any tracker file shows >200 deletions, STOP.

Expected delta:
- `src/probos/cognitive/ground_truth.py`: ~245 lines (new -- Verifier + EpisodeWriter combined).
- `src/probos/events.py`: 2 lines added.
- `src/probos/config.py`: ~9 lines added.
- `src/probos/startup/finalize.py`: ~22 lines added.
- `tests/test_ad528_ground_truth.py`: ~290 lines (new).
- `PROGRESS.md`, `roadmap.md`: ~3 lines changed.

---

## Acceptance Criteria

- All 14 tests pass under `pytest tests/test_ad528_ground_truth.py -v -n 0`.
- Full parallel gate non-decreasing.
- 2 new EventTypes appear exactly once in `events.py`.
- `runtime.ground_truth_verifier` and `runtime.verification_episode_writer` are public attributes (no leading underscore).
- `GroundTruthVerifier` and `VerificationEpisodeWriter` use stdlib only; no new pyproject deps.
- Episode storage is integrated -- every verification produces an episode (when `write_episode=True`) so future audits can retrospectively verify the verification.
- `BookingJournal`, `event_log`, AD-592 confabulation guard, AD-451 ReconciliationEscalator are all unchanged.
- AD-528 introduces NO destructive intents -- v1 is observation-only. The `requires_consensus=True` rule does not apply.
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

---

## Verified Against Codebase (2026-05-01)

```
grep -rn "class GroundTruthVerifier\|class VerificationEpisodeWriter\|class GroundTruthResult" src/probos/
  (no matches -- AD-528 introduces these names)

grep -n "VERIFICATION_PASSED\|VERIFICATION_FAILED" src/probos/events.py
  (no matches -- names are free)

grep -n "class BookingJournal" src/probos/workforce.py
  738: class BookingJournal:

grep -n "async def get_booking_journal" src/probos/workforce.py
  1514: async def get_booking_journal(self, booking_id: str) -> list[BookingJournal]:

grep -n "async def query" src/probos/substrate/event_log.py
  132: async def query(  -- accepts category, agent_id, limit; returns list[dict]

grep -n "AD-592\|confabulation" src/probos/cognitive/cognitive_agent.py
  4157: """Return AD-592 confabulation guard instruction calibrated by source authority.
  4203: # AD-592: Authority-calibrated confabulation guard
  (AD-592 is the LLM prompt surface; AD-528 is the runtime verification surface; orthogonal)

grep -n "self\.workforce\|self\.event_log\|self\.episodic_memory" src/probos/runtime.py | head -5
  314: self.event_log = EventLog(...)
  (workforce and episodic_memory verified public via greps in runtime.py)

grep -n "AGENT_SELF_NAMED\|INFODYNAMIC_REPORT" src/probos/events.py
  190: AGENT_SELF_NAMED = "agent_self_named"  # AD-499
  (terminal fallback)

grep -n "orders: OrdersConfig" src/probos/config.py
  1593: orders: OrdersConfig = OrdersConfig()  # AD-440
  (always-available terminal fallback)

grep -n "def emit_event" src/probos/runtime.py
  775: def emit_event(self, event: BaseEvent | str | EventType, ...

grep -n "class ReconciliationEscalator" src/probos/cognitive/validation_framework.py
  (post-AD-451 Wave 6; orthogonal surface; AD-528 does NOT integrate in v1)

grep -n "class Episode\|class MemorySource" src/probos/types.py
  342: class MemorySource(str, Enum):
  344: DIRECT = "direct"
  411: class Episode:
  (Episode is frozen dataclass; AD-528 constructs via Episode(timestamp=..., user_input=...,
   agent_ids=..., dag_summary={"kind": "ground_truth_verification", ...}, source="direct"))

grep -n "async def store" src/probos/cognitive/episodic.py
  942: async def store(self, episode: Episode) -> None:
  (typed Episode required; AD-528 Section 2 constructs and passes a real Episode)

grep -n "ALLOWED_EXCEPTIONS" tests/test_layer_boundaries.py
  53: ALLOWED_EXCEPTIONS = {
  (AD-528 Section 6 adds entry mirroring AD-451 / BF-085 precedent)

grep -n "def emit_event" src/probos/runtime.py
  785: def emit_event(self, event: BaseEvent | str | EventType, ...
  (corrected line number)
```

---

## Revision (2026-05-01)

Applied review findings from `prompts/Reviews/ad-528-ground-truth-task-verification-review.md`.

**Required addressed:**

- **R#1: `EpisodicMemory.store()` requires typed `Episode` dataclass** -- Section 2 `VerificationEpisodeWriter.write()` rewritten. Now imports `Episode` and `MemorySource` from `probos.types`, constructs a frozen `Episode(...)` with verification metadata embedded in the `dag_summary` dict field. Specifically:
  - `timestamp = time.time()`
  - `user_input = result.claimed_summary[:1000]` (truncated to avoid bloat)
  - `agent_ids = [result.agent_id]`
  - `dag_summary = {"kind": "ground_truth_verification", "booking_id": ..., "verified": ..., "score": ..., "signals": ..., "completed_at": ...}`
  - `source = MemorySource.DIRECT.value` (matches AD-541 "agent personally experienced this")
  - `importance = 7 if not result.verified else 4` (failed verifications retained more aggressively per AD-598)
  - `correlation_id = ""`

  Test #12 description updated to assert the argument is a typed `Episode` with the expected `dag_summary` keys.

- **R#2: ALLOWED_EXCEPTIONS entry for cognitive→workforce TYPE_CHECKING import** -- new Section 6 added. `tests/test_layer_boundaries.py` ALLOWED_EXCEPTIONS gets an explicit SEARCH/REPLACE entry mirroring the AD-451 precedent: `("cognitive/ground_truth.py", "probos.workforce")` with a justification comment.

- **R#3: `MemorySource` enum value selection** -- resolved to `MemorySource.DIRECT.value` ("direct"), verified at `types.py:344`. Documented in Section 2's Builder note. The choice matches the AD-541 semantic: the verifier directly observed the journal/event-log evidence.

**Recommended applied:**

- **rec#1: `_fetch_journal()` fallback documentation** -- Section 1 docstring on `_fetch_journal` now says "Prefers `journal_type='working'`; falls back to first entry if none found."
- **rec#2: window tightening note** -- documented in "What This Does NOT Change": v1 uses 600s window; AD-528b active rejection should tighten.
- **rec#3: threshold boundary semantics** -- Test #10 description clarified: "boundary is inclusive; score exactly 0.75 with threshold 0.75 verifies (>= comparison)."
- **rec#4: claimed_summary truncation rationale** -- Section 2 docstring documents 1000-char truncation as "avoid bloat in episodic store; long summaries can be reconstructed from the booking_id."
- **rec#5: AD-451 orthogonality** -- already addressed in pass-1 prompt; preserved in revision.

**Recommended deferred:**

- (none; all 5 applied)

**Nits applied:**

- **nit#1: confabulation framing** -- cosmetic; deferred to AD-528b refinement.
- **nit#2: footer line drift** -- corrected `runtime.emit_event` line from 775 to 785.
- **nit#3: `_emit()` exception swallow** -- preserved; tier-2 log-and-degrade is correct.
- **nit#4: `completed_at` vs `timestamp` distinction** -- preserved via `dag_summary["completed_at"]` (verifier moment) and `Episode.timestamp` (storage moment); both fields populated.

**Verified Against Codebase footer extended:** added `Episode` class location (`types.py:411`), `MemorySource.DIRECT` value (`types.py:344`), `EpisodicMemory.store` signature requirement (`episodic.py:942`), `ALLOWED_EXCEPTIONS` location (`test_layer_boundaries.py:53`). Corrected `runtime.emit_event` line to 785.

**Test count: 14 → 14** (Test #12 description updated to reflect typed Episode; no count change).

**Wave-5/6 conventions audit (post-revision):**

- #1 Public-attribute wiring: `runtime.ground_truth_verifier`, `runtime.verification_episode_writer` -- both public. ✅
- #2 stdlib-only: no new pyproject deps. ✅
- #3 Coordinator-then-dispatch: v1 observation-only; active rejection deferred to AD-528b. ✅
- #4 Superset-filter: reads existing surfaces without intercepting. ✅
- #5 init_<phase>: Section 5 wires from `startup/finalize.py`. ✅
- #6 Verify-first: footer now includes Episode + MemorySource greps. ✅
- #7 No-theater: real-work scoring + real Episode storage + real event emission. ✅
- Wave-6 TYPE_CHECKING: Section 6 explicitly adds the ALLOWED_EXCEPTIONS entry. ✅
- Wave-6 ASCII comments: verified. ✅
- Wave-6 anchor-chain fallback: Section 4 terminates at AD-440 `orders: OrdersConfig`. ✅

**No-theater discipline (cross-cutting):** v1 ships:
- GroundTruthVerifier (real cross-reference scoring against BookingJournal + event_log)
- VerificationEpisodeWriter (real typed Episode storage)
- VERIFICATION_PASSED / VERIFICATION_FAILED emit (real signal)

All do real work today. Two deferrals (active rejection, trust feedback) are wholesale.

**Verdict shift:** Pass-1 ⚠️ Conditional → expected ✅ Approved on second-pass review (R#1 mechanical Episode-dataclass fix, R#2 explicit ALLOWED_EXCEPTIONS section, R#3 MemorySource resolution all applied).
