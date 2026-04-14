"""AD-423a: Tool adapters — wrap existing infrastructure as Tool instances.

Three adapter types for the initial foundation:
- InfraServiceAdapter: wraps infrastructure agents (dispatched via intent bus)
- DirectServiceAdapter: wraps Ship's Computer services (direct method calls)
- DeterministicFunctionAdapter: wraps synchronous callables (Cognitive JIT procedures)
"""

from __future__ import annotations

import logging
import time
from typing import Any, Awaitable, Callable

from probos.tools.protocol import Tool, ToolResult, ToolType

logger = logging.getLogger(__name__)


class InfraServiceAdapter:
    """Wraps an infrastructure agent as a Tool.

    Invocations are dispatched via the intent bus. The adapter
    translates Tool.invoke() params into an IntentMessage and
    awaits the result.
    """

    def __init__(
        self,
        *,
        tool_id: str,
        name: str,
        description: str,
        input_schema: dict[str, Any] | None = None,
        output_schema: dict[str, Any] | None = None,
        intent_name: str,
        intent_bus: Any = None,  # IntentBus — late-bound to avoid circular imports
    ) -> None:
        self._tool_id = tool_id
        self._name = name
        self._description = description
        self._input_schema = input_schema or {}
        self._output_schema = output_schema or {}
        self._intent_name = intent_name
        self._intent_bus = intent_bus

    @property
    def tool_id(self) -> str:
        return self._tool_id

    @property
    def name(self) -> str:
        return self._name

    @property
    def tool_type(self) -> ToolType:
        return ToolType.INFRA_SERVICE

    @property
    def description(self) -> str:
        return self._description

    @property
    def input_schema(self) -> dict[str, Any]:
        return self._input_schema

    @property
    def output_schema(self) -> dict[str, Any]:
        return self._output_schema

    def set_intent_bus(self, bus: Any) -> None:
        """Late-bind the intent bus (available after startup)."""
        self._intent_bus = bus

    async def invoke(self, params: dict[str, Any], context: dict[str, Any] | None = None) -> ToolResult:
        if self._intent_bus is None:
            return ToolResult(error="Intent bus not available")
        t0 = time.monotonic()
        try:
            from probos.types import IntentMessage

            intent = IntentMessage(
                intent=self._intent_name,
                params=params,
                context=context.get("agent_id", "tool_registry") if context else "tool_registry",
            )
            results = await self._intent_bus.broadcast(intent)
            elapsed = (time.monotonic() - t0) * 1000
            # Take first successful result from responders
            for r in results:
                if r.success:
                    return ToolResult(output=r.result, duration_ms=elapsed)
            err = results[0].error if results else "No responders"
            return ToolResult(error=str(err), duration_ms=elapsed)
        except Exception as exc:
            elapsed = (time.monotonic() - t0) * 1000
            logger.warning("InfraServiceAdapter %s invoke failed: %s", self._tool_id, exc)
            return ToolResult(error=str(exc), duration_ms=elapsed)


class DirectServiceAdapter:
    """Wraps a Ship's Computer service method as a Tool.

    For services like EpisodicMemory, TrustNetwork, KnowledgeStore
    where invocation is a direct async method call.
    """

    def __init__(
        self,
        *,
        tool_id: str,
        name: str,
        description: str,
        input_schema: dict[str, Any] | None = None,
        output_schema: dict[str, Any] | None = None,
        handler: Callable[..., Awaitable[Any]],
        tool_type: ToolType = ToolType.INFRA_SERVICE,
    ) -> None:
        self._tool_id = tool_id
        self._name = name
        self._description = description
        self._input_schema = input_schema or {}
        self._output_schema = output_schema or {}
        self._handler = handler
        self._tool_type = tool_type

    @property
    def tool_id(self) -> str:
        return self._tool_id

    @property
    def name(self) -> str:
        return self._name

    @property
    def tool_type(self) -> ToolType:
        return self._tool_type

    @property
    def description(self) -> str:
        return self._description

    @property
    def input_schema(self) -> dict[str, Any]:
        return self._input_schema

    @property
    def output_schema(self) -> dict[str, Any]:
        return self._output_schema

    async def invoke(self, params: dict[str, Any], context: dict[str, Any] | None = None) -> ToolResult:
        t0 = time.monotonic()
        try:
            result = await self._handler(**params)
            elapsed = (time.monotonic() - t0) * 1000
            return ToolResult(output=result, duration_ms=elapsed)
        except Exception as exc:
            elapsed = (time.monotonic() - t0) * 1000
            logger.warning("DirectServiceAdapter %s invoke failed: %s", self._tool_id, exc)
            return ToolResult(error=str(exc), duration_ms=elapsed)


class DeterministicFunctionAdapter:
    """Wraps a synchronous callable as a Tool.

    For Cognitive JIT executable skills — deterministic functions that
    were extracted from LLM workflows and compiled to direct code.
    """

    def __init__(
        self,
        *,
        tool_id: str,
        name: str,
        description: str,
        input_schema: dict[str, Any] | None = None,
        output_schema: dict[str, Any] | None = None,
        handler: Callable[..., Any],
    ) -> None:
        self._tool_id = tool_id
        self._name = name
        self._description = description
        self._input_schema = input_schema or {}
        self._output_schema = output_schema or {}
        self._handler = handler

    @property
    def tool_id(self) -> str:
        return self._tool_id

    @property
    def name(self) -> str:
        return self._name

    @property
    def tool_type(self) -> ToolType:
        return ToolType.DETERMINISTIC_FUNCTION

    @property
    def description(self) -> str:
        return self._description

    @property
    def input_schema(self) -> dict[str, Any]:
        return self._input_schema

    @property
    def output_schema(self) -> dict[str, Any]:
        return self._output_schema

    async def invoke(self, params: dict[str, Any], context: dict[str, Any] | None = None) -> ToolResult:
        t0 = time.monotonic()
        try:
            result = self._handler(**params)
            elapsed = (time.monotonic() - t0) * 1000
            return ToolResult(output=result, duration_ms=elapsed)
        except Exception as exc:
            elapsed = (time.monotonic() - t0) * 1000
            logger.warning("DeterministicFunctionAdapter %s invoke failed: %s", self._tool_id, exc)
            return ToolResult(error=str(exc), duration_ms=elapsed)
