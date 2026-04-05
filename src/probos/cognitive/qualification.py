"""AD-566a: Qualification Test Harness Infrastructure.

Provides the protocol for defining psychometric tests, the engine for
running them, the store for persisting results, and the comparison API
for detecting drift over time.

The harness is agent-type-agnostic — it takes ``agent_id: str`` and
``runtime: Any``.  Actual test implementations are registered by
AD-566b through AD-566e modules.

Design decisions
----------------
- **SQLite for results** via ``ConnectionFactory`` (cloud-ready).
- **Direct ``handle_intent()``** invocation — bypasses trust/Hebbian/routing.
- **Episode suppression** via ``_qualification_test`` intent param (D4).
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

logger = logging.getLogger(__name__)

CREW_AGENT_ID = "__crew__"

# ---------------------------------------------------------------------------
# D1 — Core types
# ---------------------------------------------------------------------------

@runtime_checkable
class QualificationTest(Protocol):
    """Protocol for a single qualification test.

    Implementations in AD-566b through AD-566e.
    """

    @property
    def name(self) -> str:
        """Unique test identifier, e.g. 'bfi2_personality_probe'."""
        ...

    @property
    def tier(self) -> int:
        """Test tier: 1 (baseline), 2 (domain), 3 (collective)."""
        ...

    @property
    def description(self) -> str:
        """Human-readable test description."""
        ...

    @property
    def threshold(self) -> float:
        """Pass/fail score threshold (0.0-1.0)."""
        ...

    async def run(self, agent_id: str, runtime: Any) -> "TestResult":
        """Execute the test and return scored result."""
        ...


@dataclass(frozen=True)
class TestResult:
    """Immutable result of a single qualification test run."""

    agent_id: str
    test_name: str
    tier: int
    score: float
    passed: bool
    timestamp: float
    duration_ms: float
    is_baseline: bool = False
    details: dict = field(default_factory=dict)
    error: str | None = None


@dataclass(frozen=True)
class ComparisonResult:
    """Comparison of current test result against baseline."""

    agent_id: str
    test_name: str
    baseline_score: float
    current_score: float
    delta: float
    percent_change: float
    significant: bool
    direction: str  # "improved" | "stable" | "declined"


def _compute_direction(delta: float, significance_threshold: float) -> str:
    """Determine direction from delta and threshold."""
    if delta > significance_threshold:
        return "improved"
    if delta < -significance_threshold:
        return "declined"
    return "stable"


# ---------------------------------------------------------------------------
# D2 — QualificationStore
# ---------------------------------------------------------------------------

_SCHEMA = """\
CREATE TABLE IF NOT EXISTS qualification_results (
    id TEXT PRIMARY KEY,
    agent_id TEXT NOT NULL,
    test_name TEXT NOT NULL,
    tier INTEGER NOT NULL,
    score REAL NOT NULL,
    passed INTEGER NOT NULL,
    timestamp REAL NOT NULL,
    duration_ms REAL NOT NULL,
    is_baseline INTEGER NOT NULL DEFAULT 0,
    details_json TEXT NOT NULL DEFAULT '{}',
    error TEXT
);

CREATE INDEX IF NOT EXISTS idx_qual_agent_test
    ON qualification_results(agent_id, test_name);

CREATE INDEX IF NOT EXISTS idx_qual_agent_baseline
    ON qualification_results(agent_id, is_baseline);
"""


class QualificationStore:
    """SQLite persistence for qualification test results.

    Uses ``ConnectionFactory`` for cloud-ready storage — commercial
    overlay can swap to Postgres without changing this code.
    """

    def __init__(
        self,
        data_dir: str | Path | None = None,
        connection_factory: Any = None,
    ) -> None:
        self._data_dir = Path(data_dir) if data_dir else None
        self._connection_factory = connection_factory
        self._db: Any = None

    async def start(self) -> None:
        """Initialize DB connection and schema."""
        if not self._data_dir:
            return
        if self._connection_factory is None:
            from probos.storage.sqlite_factory import default_factory
            self._connection_factory = default_factory
        db_path = str(self._data_dir / "qualification_results.db")
        self._db = await self._connection_factory.connect(db_path)
        await self._db.executescript(_SCHEMA)
        await self._db.commit()

    async def stop(self) -> None:
        """Close DB connection."""
        if self._db is not None:
            try:
                await self._db.close()
            except Exception:
                pass
            self._db = None

    async def save_result(self, result: TestResult) -> None:
        """Persist a test result. Generates UUID for id."""
        if self._db is None:
            return
        row = _result_to_row(result)
        await self._db.execute(
            "INSERT INTO qualification_results "
            "(id, agent_id, test_name, tier, score, passed, timestamp, "
            "duration_ms, is_baseline, details_json, error) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            row,
        )
        await self._db.commit()

    async def get_baseline(
        self, agent_id: str, test_name: str
    ) -> TestResult | None:
        """Get the baseline result for an agent+test."""
        if self._db is None:
            return None
        cursor = await self._db.execute(
            "SELECT * FROM qualification_results "
            "WHERE agent_id = ? AND test_name = ? AND is_baseline = 1 "
            "ORDER BY timestamp DESC LIMIT 1",
            (agent_id, test_name),
        )
        row = await cursor.fetchone()
        return _row_to_result(row) if row else None

    async def set_baseline(
        self, agent_id: str, test_name: str, result_id: str
    ) -> None:
        """Mark a specific result as baseline, clearing any previous."""
        if self._db is None:
            return
        await self._db.execute(
            "UPDATE qualification_results SET is_baseline = 0 "
            "WHERE agent_id = ? AND test_name = ? AND is_baseline = 1",
            (agent_id, test_name),
        )
        await self._db.execute(
            "UPDATE qualification_results SET is_baseline = 1 WHERE id = ?",
            (result_id,),
        )
        await self._db.commit()

    async def get_latest(
        self, agent_id: str, test_name: str
    ) -> TestResult | None:
        """Get the most recent result for an agent+test."""
        if self._db is None:
            return None
        cursor = await self._db.execute(
            "SELECT * FROM qualification_results "
            "WHERE agent_id = ? AND test_name = ? "
            "ORDER BY timestamp DESC LIMIT 1",
            (agent_id, test_name),
        )
        row = await cursor.fetchone()
        return _row_to_result(row) if row else None

    async def get_history(
        self, agent_id: str, test_name: str, *, limit: int = 20
    ) -> list[TestResult]:
        """Get chronological history (newest-first) for an agent+test."""
        if self._db is None:
            return []
        cursor = await self._db.execute(
            "SELECT * FROM qualification_results "
            "WHERE agent_id = ? AND test_name = ? "
            "ORDER BY timestamp DESC LIMIT ?",
            (agent_id, test_name, limit),
        )
        rows = await cursor.fetchall()
        return [_row_to_result(r) for r in rows]

    async def get_agent_summary(self, agent_id: str) -> dict:
        """Aggregate summary across all tests for an agent."""
        if self._db is None:
            return {
                "agent_id": agent_id,
                "tests_run": 0,
                "tests_passed": 0,
                "pass_rate": 0.0,
                "baseline_set": False,
                "latest_results": {},
            }
        # Total count and pass count
        cursor = await self._db.execute(
            "SELECT COUNT(*), SUM(passed) FROM qualification_results "
            "WHERE agent_id = ?",
            (agent_id,),
        )
        row = await cursor.fetchone()
        tests_run = row[0] or 0
        tests_passed = int(row[1] or 0)

        # Baseline exists?
        cursor = await self._db.execute(
            "SELECT COUNT(*) FROM qualification_results "
            "WHERE agent_id = ? AND is_baseline = 1",
            (agent_id,),
        )
        baseline_row = await cursor.fetchone()
        baseline_set = (baseline_row[0] or 0) > 0

        # Latest per test — get distinct test names, then latest for each
        cursor = await self._db.execute(
            "SELECT DISTINCT test_name FROM qualification_results "
            "WHERE agent_id = ?",
            (agent_id,),
        )
        test_names = [r[0] for r in await cursor.fetchall()]

        latest_results: dict[str, dict] = {}
        for tn in test_names:
            cursor = await self._db.execute(
                "SELECT score, passed, timestamp FROM qualification_results "
                "WHERE agent_id = ? AND test_name = ? "
                "ORDER BY timestamp DESC LIMIT 1",
                (agent_id, tn),
            )
            lr = await cursor.fetchone()
            if lr:
                latest_results[tn] = {
                    "score": lr[0],
                    "passed": bool(lr[1]),
                    "timestamp": lr[2],
                }

        return {
            "agent_id": agent_id,
            "tests_run": tests_run,
            "tests_passed": tests_passed,
            "pass_rate": tests_passed / tests_run if tests_run > 0 else 0.0,
            "baseline_set": baseline_set,
            "latest_results": latest_results,
        }


def _result_to_row(result: TestResult) -> tuple:
    """Convert TestResult to SQLite INSERT tuple."""
    return (
        str(uuid.uuid4()),
        result.agent_id,
        result.test_name,
        result.tier,
        result.score,
        1 if result.passed else 0,
        result.timestamp,
        result.duration_ms,
        1 if result.is_baseline else 0,
        json.dumps(result.details),
        result.error,
    )


def _row_to_result(row: Any) -> TestResult:
    """Reconstruct TestResult from SQLite SELECT row."""
    return TestResult(
        agent_id=row[1],
        test_name=row[2],
        tier=row[3],
        score=row[4],
        passed=bool(row[5]),
        timestamp=row[6],
        duration_ms=row[7],
        is_baseline=bool(row[8]),
        details=json.loads(row[9]) if row[9] else {},
        error=row[10],
    )


# ---------------------------------------------------------------------------
# D3 — QualificationHarness
# ---------------------------------------------------------------------------

class QualificationHarness:
    """Engine for registering, executing, and comparing qualification tests.

    Manages the test registry, baseline capture, result persistence, and
    comparison against baselines.  Event emission is optional (``None``
    gracefully handled).
    """

    def __init__(
        self,
        store: QualificationStore,
        emit_event_fn: Any | None = None,
        config: Any | None = None,
    ) -> None:
        from probos.config import QualificationConfig
        self._store = store
        self._emit_event_fn = emit_event_fn
        self._config: QualificationConfig = config or QualificationConfig()
        self._tests: dict[str, QualificationTest] = {}
        self._latest_results: dict[str, TestResult] = {}

    def register_test(self, test: QualificationTest) -> None:
        """Register a test implementation."""
        self._tests[test.name] = test

    @property
    def registered_tests(self) -> dict[str, QualificationTest]:
        """Read-only view of registered tests."""
        return dict(self._tests)

    async def run_test(
        self, agent_id: str, test_name: str, runtime: Any
    ) -> TestResult:
        """Run a single test for an agent."""
        test = self._tests.get(test_name)
        if test is None:
            raise KeyError(f"Unknown test: {test_name}")

        t0 = time.time()
        try:
            result = await asyncio.wait_for(
                test.run(agent_id, runtime),
                timeout=self._config.test_timeout_seconds,
            )
        except asyncio.TimeoutError:
            result = TestResult(
                agent_id=agent_id,
                test_name=test_name,
                tier=test.tier,
                score=0.0,
                passed=False,
                timestamp=time.time(),
                duration_ms=(time.time() - t0) * 1000,
                error="Test timed out",
            )
        except Exception as exc:
            result = TestResult(
                agent_id=agent_id,
                test_name=test_name,
                tier=test.tier,
                score=0.0,
                passed=False,
                timestamp=time.time(),
                duration_ms=(time.time() - t0) * 1000,
                error=str(exc),
            )

        # Auto-baseline on first run
        if self._config.baseline_auto_capture and result.error is None:
            existing = await self._store.get_baseline(agent_id, test_name)
            if existing is None:
                result = dataclasses.replace(result, is_baseline=True)
                if self._emit_event_fn:
                    self._emit_event_fn(
                        "qualification_baseline_set",
                        {
                            "agent_id": agent_id,
                            "test_name": test_name,
                            "score": result.score,
                        },
                    )

        await self._store.save_result(result)
        self._latest_results[f"{agent_id}:{test_name}"] = result

        if self._emit_event_fn:
            self._emit_event_fn(
                "qualification_test_complete",
                {
                    "agent_id": agent_id,
                    "test_name": test_name,
                    "score": result.score,
                    "passed": result.passed,
                    "is_baseline": result.is_baseline,
                },
            )

        return result

    async def run_tier(
        self, agent_id: str, tier: int, runtime: Any
    ) -> list[TestResult]:
        """Run all registered tests for a specific tier."""
        results = []
        for test in self._tests.values():
            if test.tier == tier:
                r = await self.run_test(agent_id, test.name, runtime)
                results.append(r)
        return results

    async def run_all(
        self, agent_id: str, runtime: Any
    ) -> list[TestResult]:
        """Run all registered tests for an agent."""
        results = []
        for test_name in self._tests:
            r = await self.run_test(agent_id, test_name, runtime)
            results.append(r)
        return results

    async def run_collective(
        self, tier: int, runtime: Any
    ) -> list[TestResult]:
        """Run all registered tests of a tier once for the crew collective.

        Unlike run_tier() which iterates per-agent, this runs each test
        once with agent_id='__crew__'.  Used for Tier 3 collective tests.
        """
        results = []
        for test in self._tests.values():
            if test.tier == tier:
                r = await self.run_test(CREW_AGENT_ID, test.name, runtime)
                results.append(r)
        return results

    async def run_baseline(
        self, agent_id: str, runtime: Any
    ) -> list[TestResult]:
        """Run all tests and mark results as baseline."""
        results = []
        for test in self._tests.values():
            t0 = time.time()
            try:
                result = await asyncio.wait_for(
                    test.run(agent_id, runtime),
                    timeout=self._config.test_timeout_seconds,
                )
            except asyncio.TimeoutError:
                result = TestResult(
                    agent_id=agent_id,
                    test_name=test.name,
                    tier=test.tier,
                    score=0.0,
                    passed=False,
                    timestamp=time.time(),
                    duration_ms=(time.time() - t0) * 1000,
                    error="Test timed out",
                )
            except Exception as exc:
                result = TestResult(
                    agent_id=agent_id,
                    test_name=test.name,
                    tier=test.tier,
                    score=0.0,
                    passed=False,
                    timestamp=time.time(),
                    duration_ms=(time.time() - t0) * 1000,
                    error=str(exc),
                )

            # Force baseline regardless of error
            if result.error is None:
                result = dataclasses.replace(result, is_baseline=True)

            await self._store.save_result(result)
            self._latest_results[f"{agent_id}:{test.name}"] = result

            if self._emit_event_fn:
                self._emit_event_fn(
                    "qualification_test_complete",
                    {
                        "agent_id": agent_id,
                        "test_name": test.name,
                        "score": result.score,
                        "passed": result.passed,
                        "is_baseline": result.is_baseline,
                    },
                )
                if result.is_baseline:
                    self._emit_event_fn(
                        "qualification_baseline_set",
                        {
                            "agent_id": agent_id,
                            "test_name": test.name,
                            "score": result.score,
                        },
                    )

            results.append(result)
        return results

    async def compare(
        self, agent_id: str, test_name: str
    ) -> ComparisonResult | None:
        """Compare latest result against baseline."""
        baseline = await self._store.get_baseline(agent_id, test_name)
        latest = await self._store.get_latest(agent_id, test_name)
        if baseline is None or latest is None:
            return None

        delta = latest.score - baseline.score
        percent_change = (delta / baseline.score * 100) if baseline.score > 0 else 0.0
        direction = _compute_direction(delta, self._config.significance_threshold)

        return ComparisonResult(
            agent_id=agent_id,
            test_name=test_name,
            baseline_score=baseline.score,
            current_score=latest.score,
            delta=delta,
            percent_change=percent_change,
            significant=abs(delta) > self._config.significance_threshold,
            direction=direction,
        )

    async def compare_all(
        self, agent_id: str
    ) -> dict[str, ComparisonResult]:
        """Compare all tests for an agent."""
        results: dict[str, ComparisonResult] = {}
        for test_name in self._tests:
            cr = await self.compare(agent_id, test_name)
            if cr is not None:
                results[test_name] = cr
        return results

    async def get_agent_summary(self, agent_id: str) -> dict:
        """Delegate to store."""
        return await self._store.get_agent_summary(agent_id)

    @property
    def latest_snapshot(self) -> dict | None:
        """Most recent results dict for VitalsMonitor integration."""
        if not self._latest_results:
            return None
        snapshot: dict[str, dict[str, float]] = {}
        for key, result in self._latest_results.items():
            aid = result.agent_id
            if aid not in snapshot:
                snapshot[aid] = {}
            snapshot[aid][result.test_name] = result.score
        return snapshot
