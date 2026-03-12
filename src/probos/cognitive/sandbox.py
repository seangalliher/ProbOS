"""SandboxRunner — test-executes generated agents in an isolated context."""

from __future__ import annotations

import asyncio
import importlib.util
import logging
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from probos.config import SelfModConfig
    from probos.cognitive.llm_client import BaseLLMClient

from probos.substrate.agent import BaseAgent
from probos.cognitive.cognitive_agent import CognitiveAgent
from probos.types import IntentMessage, IntentResult

logger = logging.getLogger(__name__)


@dataclass
class SandboxResult:
    """Result of sandbox test execution."""

    success: bool
    agent_class: type | None = None
    error: str | None = None
    execution_time_ms: float = 0.0


class SandboxRunner:
    """Test-executes a generated agent in an isolated context.

    The sandbox:
    1. Writes the source code to a temp file
    2. Loads it as a Python module via importlib
    3. Finds the BaseAgent subclass in the module
    4. Instantiates the agent
    5. Sends a synthetic test intent and verifies the agent responds
    6. Checks that the agent conforms to the BaseAgent contract
    7. Returns the loaded class if successful

    This is NOT a security sandbox (no seccomp, no containers).
    Security is handled by CodeValidator's static analysis.
    The SandboxRunner verifies functional correctness.
    """

    def __init__(self, config: SelfModConfig, llm_client: Any = None) -> None:
        self._timeout = config.sandbox_timeout_seconds
        self._llm_client = llm_client

    async def test_agent(
        self,
        source_code: str,
        intent_name: str,
        test_params: dict | None = None,
    ) -> SandboxResult:
        """Load and test a generated agent.

        Steps:
        1. Write source to temp file
        2. importlib.util.spec_from_file_location + module_from_spec + exec_module
        3. Find the class (iterate module.__dict__ for BaseAgent subclasses)
        4. Instantiate with a mock registry
        5. Create a test IntentMessage with intent_name and test_params
        6. Call agent.handle_intent(test_intent) with asyncio.wait_for timeout
        7. Verify result is IntentResult or None
        8. Return SandboxResult with the class if successful
        """
        t_start = time.monotonic()

        try:
            # 1. Write to temp file
            tmp = tempfile.NamedTemporaryFile(
                mode="w", suffix=".py", delete=False, encoding="utf-8",
            )
            tmp.write(source_code)
            tmp.flush()
            tmp.close()
            tmp_path = tmp.name

            try:
                # 2. Load as module
                module_name = f"_probos_sandbox_{id(source_code)}"
                spec = importlib.util.spec_from_file_location(module_name, tmp_path)
                if spec is None or spec.loader is None:
                    return SandboxResult(
                        success=False,
                        error="Failed to create module spec",
                        execution_time_ms=(time.monotonic() - t_start) * 1000,
                    )

                module = importlib.util.module_from_spec(spec)
                sys.modules[module_name] = module
                spec.loader.exec_module(module)

                # 3. Find the agent class
                agent_class = self._find_agent_class(module)
                if agent_class is None:
                    return SandboxResult(
                        success=False,
                        error="No BaseAgent subclass found in loaded module",
                        execution_time_ms=(time.monotonic() - t_start) * 1000,
                    )

                # 4. Instantiate (inject LLM client if available)
                agent = agent_class(pool="sandbox", llm_client=self._llm_client)

                # 5. Create test intent
                test_intent = IntentMessage(
                    intent=intent_name,
                    params=test_params or {},
                )

                # 6. Call handle_intent with timeout
                result = await asyncio.wait_for(
                    agent.handle_intent(test_intent),
                    timeout=self._timeout,
                )

                # 7. Verify result type
                if result is not None and not isinstance(result, IntentResult):
                    return SandboxResult(
                        success=False,
                        error=f"handle_intent returned {type(result).__name__}, expected IntentResult or None",
                        execution_time_ms=(time.monotonic() - t_start) * 1000,
                    )

                # 8. Success
                return SandboxResult(
                    success=True,
                    agent_class=agent_class,
                    execution_time_ms=(time.monotonic() - t_start) * 1000,
                )

            finally:
                # Clean up temp file and module
                try:
                    Path(tmp_path).unlink(missing_ok=True)
                except OSError:
                    pass
                sys.modules.pop(module_name, None)

        except asyncio.TimeoutError:
            return SandboxResult(
                success=False,
                error=f"Agent execution timed out after {self._timeout}s",
                execution_time_ms=(time.monotonic() - t_start) * 1000,
            )
        except Exception as e:
            return SandboxResult(
                success=False,
                error=f"Sandbox error: {type(e).__name__}: {e}",
                execution_time_ms=(time.monotonic() - t_start) * 1000,
            )

    def _find_agent_class(self, module: Any) -> type | None:
        """Find the BaseAgent subclass in a loaded module.

        Must be a subclass of BaseAgent (not BaseAgent or CognitiveAgent itself).
        Must have intent_descriptors defined.
        """
        for name, obj in module.__dict__.items():
            if (
                isinstance(obj, type)
                and issubclass(obj, BaseAgent)
                and obj is not BaseAgent
                and obj is not CognitiveAgent
                and hasattr(obj, "intent_descriptors")
                and obj.intent_descriptors
            ):
                return obj
        return None
