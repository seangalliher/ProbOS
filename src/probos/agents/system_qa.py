"""SystemQAAgent — smoke-tests newly designed agents after self-modification."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, TYPE_CHECKING

from probos.substrate.agent import BaseAgent
from probos.types import IntentDescriptor, IntentMessage, IntentResult, QAReport

if TYPE_CHECKING:
    from probos.cognitive.self_mod import DesignedAgentRecord
    from probos.config import QAConfig
    from probos.substrate.pool import ResourcePool

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Param-type inference heuristics (AD-156)
# ---------------------------------------------------------------------------

_URL_KEYS = {"url", "uri", "endpoint", "href", "link"}
_PATH_KEYS = {"path", "file", "dir", "directory", "folder", "filepath", "filename"}
_NUMERIC_KEYS = {"count", "num", "limit", "size", "port", "number", "max", "min", "amount"}
_BOOL_KEYS = {"flag", "enabled", "verbose", "debug", "force", "recursive", "confirm"}

# (happy, edge, error) value triples per type
_SYNTHETIC_VALUES: dict[str, tuple[Any, Any, Any]] = {
    "url": ("https://example.com", "not-a-url", ""),
    "path": ("/tmp/test_qa.txt", "", "/nonexistent/deep/path"),
    "numeric": (42, 0, -1),
    "bool": (True, False, True),  # error case for bool still uses a valid bool
    "default": ("test_value", "", None),
}


def _infer_param_type(key: str) -> str:
    """Infer synthetic value type from param key name (AD-156)."""
    lower = key.lower()
    for part in lower.split("_"):
        if part in _URL_KEYS:
            return "url"
        if part in _PATH_KEYS:
            return "path"
        if part in _NUMERIC_KEYS:
            return "numeric"
        if part in _BOOL_KEYS:
            return "bool"
    # Also check if full key contains these
    for k in _URL_KEYS:
        if k in lower:
            return "url"
    for k in _PATH_KEYS:
        if k in lower:
            return "path"
    for k in _NUMERIC_KEYS:
        if k in lower:
            return "numeric"
    for k in _BOOL_KEYS:
        if k in lower:
            return "bool"
    return "default"


class SystemQAAgent(BaseAgent):
    """Smoke-tests newly designed agents with synthetic intents.

    Lives in a dedicated pool. Not user-facing — triggered internally
    by the self-modification pipeline (AD-153).
    """

    agent_type = "system_qa"
    tier = "utility"
    # No user-facing descriptors — QA is triggered by the self-mod pipeline,
    # not routed via the intent bus.
    intent_descriptors: list = []

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)

    # ------------------------------------------------------------------
    # BaseAgent lifecycle (minimal — QA uses run_smoke_tests directly)
    # ------------------------------------------------------------------

    async def perceive(self, intent: dict[str, Any]) -> dict[str, Any] | None:
        if intent.get("intent") == "smoke_test_agent":
            return intent
        return None

    async def decide(self, observation: dict[str, Any]) -> dict[str, Any]:
        return {"action": "smoke_test", "params": observation.get("params", {})}

    async def act(self, plan: dict[str, Any]) -> dict[str, Any]:
        return {"success": True, "data": plan.get("params", {})}

    async def report(self, result: dict[str, Any]) -> dict[str, Any]:
        return result

    async def handle_intent(self, intent: IntentMessage) -> IntentResult | None:
        if intent.intent != "smoke_test_agent":
            return None
        return IntentResult(
            intent_id=intent.id,
            agent_id=self.id,
            success=True,
            result={"status": "smoke_test_trigger"},
        )

    # ------------------------------------------------------------------
    # Core QA logic
    # ------------------------------------------------------------------

    def generate_synthetic_intents(
        self,
        record: DesignedAgentRecord,
        count: int = 5,
    ) -> list[tuple[str, IntentMessage]]:
        """Generate synthetic test cases from intent metadata.

        Returns list of (case_type, IntentMessage) tuples where
        case_type is "happy", "edge", or "error".
        """
        params = {}
        # Try to get param schema from the record
        # The DesignedAgentRecord doesn't store param schema directly,
        # but we can get it from the intent_name pattern
        # For now, use the intent metadata if available
        if hasattr(record, '_param_schema'):
            params = record._param_schema
        else:
            # Fallback: extract from source code's IntentDescriptor
            import re
            param_match = re.search(
                r'params\s*=\s*\{([^}]+)\}', record.source_code,
            )
            if param_match:
                # Parse the dict literal
                for m in re.finditer(r'"(\w+)":\s*"([^"]*)"', param_match.group(1)):
                    params[m.group(1)] = m.group(2)

        if not params:
            # Minimal fallback: create a single text param
            params = {"text": "input text"}

        cases: list[tuple[str, IntentMessage]] = []

        # Distribute cases: happy=ceil(count*0.6), edge=1, error=1
        # If count < 3, adjust
        error_count = 1 if count >= 3 else 0
        edge_count = 1 if count >= 2 else 0
        happy_count = count - error_count - edge_count

        # Happy path cases
        for i in range(happy_count):
            happy_params = {}
            for key in params:
                ptype = _infer_param_type(key)
                values = _SYNTHETIC_VALUES[ptype]
                happy_params[key] = values[0]  # First value = happy
            cases.append((
                "happy",
                IntentMessage(
                    intent=record.intent_name,
                    params=happy_params,
                ),
            ))

        # Edge case: minimal/empty params
        for _ in range(edge_count):
            edge_params = {}
            for key in params:
                ptype = _infer_param_type(key)
                values = _SYNTHETIC_VALUES[ptype]
                edge_params[key] = values[1]  # Second value = edge/minimal
            cases.append((
                "edge",
                IntentMessage(
                    intent=record.intent_name,
                    params=edge_params,
                ),
            ))

        # Error case: invalid params
        for _ in range(error_count):
            error_params = {}
            for key in params:
                ptype = _infer_param_type(key)
                values = _SYNTHETIC_VALUES[ptype]
                error_params[key] = values[2]  # Third value = error/invalid
            cases.append((
                "error",
                IntentMessage(
                    intent=record.intent_name,
                    params=error_params,
                ),
            ))

        return cases

    def validate_result(
        self,
        case_type: str,
        result: IntentResult | None,
        error: str | None,
    ) -> bool:
        """Validate a single test case result.

        Returns True if the test case passed, False otherwise.
        """
        # Unhandled exception always fails
        if error is not None:
            return False

        if case_type == "happy":
            # Must return an IntentResult with success=True and result not None
            if result is None:
                return False
            return result.success is True and result.result is not None

        elif case_type == "edge":
            # Must return an IntentResult (success or fail ok, no crash)
            return result is not None

        elif case_type == "error":
            # Accept: IntentResult with success=False and error set, OR None (declined)
            if result is None:
                return True  # Declined is acceptable for error cases
            return result.success is False and result.error is not None

        return False

    async def run_smoke_tests(
        self,
        record: DesignedAgentRecord,
        pool: ResourcePool,
        config: QAConfig,
    ) -> QAReport:
        """Run smoke tests against agents in a pool.

        Returns a QAReport with pass/fail details.
        """
        t_start = time.monotonic()

        # Generate synthetic test cases
        cases = self.generate_synthetic_intents(record, count=config.smoke_test_count)

        # Pick one agent from the pool to test
        agents = list(pool.healthy_agents)
        if not agents:
            return QAReport(
                agent_type=record.agent_type,
                intent_name=record.intent_name,
                pool_name=record.pool_name,
                total_tests=0,
                passed=0,
                failed=0,
                pass_rate=0.0,
                verdict="error",
                test_details=[],
                duration_ms=0.0,
                timestamp=time.time(),
            )

        # Use the first healthy agent
        from probos.substrate.registry import AgentRegistry
        agent = None
        if isinstance(agents[0], str):
            # healthy_agents returns IDs — need to resolve
            if hasattr(pool, 'registry'):
                agent = pool.registry.get(agents[0])
        else:
            agent = agents[0]

        if agent is None:
            return QAReport(
                agent_type=record.agent_type,
                intent_name=record.intent_name,
                pool_name=record.pool_name,
                total_tests=0,
                passed=0,
                failed=0,
                pass_rate=0.0,
                verdict="error",
                test_details=[],
                duration_ms=0.0,
                timestamp=time.time(),
            )

        # Event log: started
        if hasattr(self, '_runtime') and self._runtime:
            try:
                await self._runtime.event_log.log(
                    category="qa",
                    event="smoke_test_started",
                    detail=f"{record.agent_type}: {len(cases)} tests",
                )
            except Exception:
                pass

        test_details: list[dict] = []
        passed = 0
        failed = 0
        total_elapsed = 0.0

        for case_type, intent in cases:
            # Check total timeout
            elapsed_so_far = (time.monotonic() - t_start) * 1000
            if elapsed_so_far / 1000 >= config.total_timeout_seconds:
                # Remaining tests skipped
                test_details.append({
                    "case_type": case_type,
                    "passed": False,
                    "error": "total_timeout_exceeded",
                })
                failed += 1
                continue

            result = None
            error = None
            try:
                result = await asyncio.wait_for(
                    agent.handle_intent(intent),
                    timeout=config.timeout_per_test_seconds,
                )
            except asyncio.TimeoutError:
                error = "timeout"
            except Exception as e:
                error = f"{type(e).__name__}: {e}"

            test_passed = self.validate_result(case_type, result, error)
            if test_passed:
                passed += 1
            else:
                failed += 1

            test_details.append({
                "case_type": case_type,
                "passed": test_passed,
                "error": error,
            })

        t_end = time.monotonic()
        duration_ms = (t_end - t_start) * 1000

        total_tests = passed + failed
        pass_rate = passed / total_tests if total_tests > 0 else 0.0
        verdict = "passed" if pass_rate >= config.pass_threshold else "failed"

        # Event log: passed/failed
        if hasattr(self, '_runtime') and self._runtime:
            try:
                event = "smoke_test_passed" if verdict == "passed" else "smoke_test_failed"
                await self._runtime.event_log.log(
                    category="qa",
                    event=event,
                    detail=f"{record.agent_type}: {passed}/{total_tests}",
                )
            except Exception:
                pass

        return QAReport(
            agent_type=record.agent_type,
            intent_name=record.intent_name,
            pool_name=record.pool_name,
            total_tests=total_tests,
            passed=passed,
            failed=failed,
            pass_rate=pass_rate,
            verdict=verdict,
            test_details=test_details,
            duration_ms=duration_ms,
            timestamp=time.time(),
        )
