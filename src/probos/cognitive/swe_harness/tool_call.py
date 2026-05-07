"""AD-543: Wire-format dataclasses for the native SWE harness tool-call loop.

Mirrors the OpenAI/Anthropic tool-call wire format so LLMResponse.content_blocks
can be passed directly between the LLM client and the AgenticLoop without
provider-specific translation.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from probos.tools.protocol import ToolRegistration, ToolResult


@dataclass(frozen=True)
class ToolCallRequest:
    """A single tool invocation request emitted by the LLM."""

    name: str = ""
    arguments: dict[str, Any] = field(default_factory=dict)
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    timestamp: float = field(default_factory=time.time)


@dataclass(frozen=True)
class ToolCallResult:
    """The outcome of a single tool invocation, fed back to the LLM."""

    id: str
    output: str = ""
    is_error: bool = False
    duration_ms: float = 0.0

    @classmethod
    def from_tool_result(
        cls,
        request_id: str,
        tool_result: "ToolResult",
        duration_ms: float,
    ) -> "ToolCallResult":
        """Adapt an AD-423a ``ToolResult`` to a ``ToolCallResult``.

        ``output`` is preserved via ``str()`` coercion when non-string.
        ``error is not None`` maps to ``is_error=True`` with the error
        text serialised into ``output`` so the LLM sees the failure cause.
        """
        if tool_result.error is not None:
            return cls(
                id=request_id,
                output=str(tool_result.error),
                is_error=True,
                duration_ms=duration_ms,
            )
        raw = tool_result.output
        out = raw if isinstance(raw, str) else str(raw) if raw is not None else ""
        return cls(
            id=request_id,
            output=out,
            is_error=False,
            duration_ms=duration_ms,
        )


@dataclass(frozen=True)
class TextBlock:
    """A plain-text content block in an LLM response."""

    text: str = ""
    kind: str = "text"


@dataclass(frozen=True)
class ToolUseBlock:
    """A tool-use content block emitted by the LLM."""

    tool_call: ToolCallRequest = field(default_factory=ToolCallRequest)
    kind: str = "tool_use"


@dataclass(frozen=True)
class ToolResultBlock:
    """A tool-result content block fed back to the LLM."""

    result: ToolCallResult = field(default_factory=lambda: ToolCallResult(id=""))
    kind: str = "tool_result"


# Python 3.10+ union syntax — confirmed via pyproject.toml requires-python.
ContentBlock = TextBlock | ToolUseBlock | ToolResultBlock


def tool_registration_to_llm_definition(reg: "ToolRegistration") -> dict[str, Any]:
    """Adapt an AD-423a ``ToolRegistration`` record to an LLM-API tool definition.

    Returns the OpenAI/Anthropic-compatible JSON shape::

        {"type": "function",
         "function": {"name": str, "description": str, "parameters": dict}}

    The ``parameters`` field is ``reg.tool.input_schema`` verbatim (already a
    JSON Schema dict per AD-423a Tool Protocol). LLM providers consume this
    format directly via the Copilot proxy; no per-provider translation needed.
    """
    schema = reg.tool.input_schema
    if not schema:
        schema = {"type": "object", "properties": {}}
    return {
        "type": "function",
        "function": {
            "name": reg.tool.tool_id,
            "description": reg.tool.description,
            "parameters": schema,
        },
    }
