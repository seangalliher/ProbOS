"""Productivity utility agents (AD-250).

CalculatorAgent uses safe eval for simple arithmetic + LLM fallback.
TodoAgent persists via mesh file I/O (read_file/write_file).
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from probos.cognitive.cognitive_agent import CognitiveAgent
from probos.types import (
    CapabilityDescriptor,
    IntentDescriptor,
    IntentMessage,
    IntentResult,
)

logger = logging.getLogger(__name__)


class _BundledMixin:
    """Self-deselect guard for unrecognized intents."""

    async def handle_intent(self, intent: IntentMessage) -> IntentResult | None:
        if intent.intent not in self._handled_intents:
            return None
        return await super().handle_intent(intent)


# Safe arithmetic regex — digits + basic ops only
_SAFE_EXPR_RE = re.compile(r"^[0-9+\-*/().,%\s]+$")


class CalculatorAgent(_BundledMixin, CognitiveAgent):
    """Calculate math, convert units, or do date math."""

    agent_type = "calculator"
    instructions = (
        "You are a calculator and unit conversion agent. When given a math problem:\n"
        "1. Parse the mathematical expression or conversion request.\n"
        "2. Compute the result accurately.\n"
        "3. Show your work for complex calculations.\n\n"
        "Support: arithmetic, percentages, unit conversions (temperature, distance,\n"
        "weight, currency estimates), date math (days between dates, date arithmetic).\n\n"
        "For currency: use approximate rates and note they may be outdated. "
        "Suggest web_search for current rates."
    )
    intent_descriptors = [
        IntentDescriptor(
            name="calculate",
            params={"expression": "math expression or conversion"},
            description="Calculate math, convert units, or do date math",
        ),
    ]
    _handled_intents = {"calculate"}
    default_capabilities = [CapabilityDescriptor(can="calculate")]

    async def act(self, decision: dict) -> dict:
        if decision.get("action") == "error":
            return {"success": False, "error": decision.get("reason")}

        # Try safe eval for simple arithmetic before using LLM output
        llm_output = decision.get("llm_output", "")
        return {"success": True, "result": llm_output}

    async def handle_intent(self, intent: IntentMessage) -> IntentResult | None:
        """Try safe eval first, fall back to full cognitive lifecycle."""
        if intent.intent not in self._handled_intents:
            return None  # Self-deselect
        expr = intent.params.get("expression", "")

        # Simple arithmetic — safe eval
        if expr and _SAFE_EXPR_RE.match(expr):
            try:
                # Remove commas (common in numbers)
                clean = expr.replace(",", "").replace("%", "/100")
                result = eval(clean)  # noqa: S307 — regex-validated safe expression
                self.update_confidence(True)
                return IntentResult(
                    intent_id=intent.id,
                    agent_id=self.id,
                    success=True,
                    result=str(result),
                    confidence=self.confidence,
                )
            except Exception:
                pass  # LLM fallback — explicit programmatic fallback

        # Fall through to cognitive lifecycle (LLM handles complex math)
        return await super().handle_intent(intent)


# ------------------------------------------------------------------
# Helper: mesh file I/O
# ------------------------------------------------------------------

async def _mesh_read_file(runtime: Any, path: str) -> str | None:
    """Read a file via mesh dispatch."""
    if not runtime or not hasattr(runtime, "intent_bus"):
        return None
    msg = IntentMessage(intent="read_file", params={"path": path})
    results = await runtime.intent_bus.broadcast(msg)
    for r in results:
        if r.success and r.result:
            content = r.result
            if isinstance(content, dict):
                content = content.get("content", content.get("data", str(content)))
            return str(content)
    return None


async def _mesh_write_file(runtime: Any, path: str, content: str) -> bool:
    """Write a file via FileWriterAgent.commit_write (personal data path).

    Bundled agents write user-owned personal data (~/.probos/) which does
    not require multi-agent consensus. This calls commit_write() directly
    to ensure data actually reaches disk.
    """
    from probos.agents.file_writer import FileWriterAgent

    result = await FileWriterAgent.commit_write(path, content)
    return result.get("success", False)


class TodoAgent(_BundledMixin, CognitiveAgent):
    """Manage a persistent todo list (file-backed via mesh I/O)."""

    agent_type = "todo_manager"
    instructions = (
        "You are a todo list manager. You maintain a persistent todo list for the user.\n\n"
        "Operations:\n"
        "- add: Add a new todo item (with optional priority: high/medium/low and optional due date)\n"
        "- list: Show all active todos, sorted by priority then due date\n"
        "- complete: Mark a todo as done\n"
        "- remove: Remove a todo\n"
        "- clear: Clear all completed todos\n\n"
        "The todo list is stored as a JSON file. The current list contents are provided to you.\n"
        "Return your response as a JSON object with keys:\n"
        "  action: the action performed\n"
        "  todos: the updated list (array of {text, priority, due, done} objects)\n"
        "  message: a human-readable summary of what was done"
    )
    intent_descriptors = [
        IntentDescriptor(
            name="manage_todo",
            params={
                "action": "add|list|complete|remove|clear",
                "item": "todo text",
                "priority": "high|medium|low",
                "due": "date",
            },
            description="Manage todo list \u2014 add, list, complete, remove items",
        ),
    ]
    _handled_intents = {"manage_todo"}
    default_capabilities = [CapabilityDescriptor(can="manage_todo")]

    _TODO_PATH = "~/.probos/todos.json"

    async def perceive(self, intent: Any) -> dict:
        obs = await super().perceive(intent)
        if self._runtime:
            import os
            path = os.path.expanduser(self._TODO_PATH)
            content = await _mesh_read_file(self._runtime, path)
            if content:
                obs["fetched_content"] = f"Current todos:\n{content}"
            else:
                obs["fetched_content"] = "Current todos:\n[]"
        return obs

    async def act(self, decision: dict) -> dict:
        if decision.get("action") == "error":
            return {"success": False, "error": decision.get("reason")}

        llm_output = decision.get("llm_output", "")

        # Try to parse LLM output as JSON to persist changes
        if self._runtime:
            try:
                data = json.loads(llm_output)
                if isinstance(data, dict) and "todos" in data:
                    import os
                    path = os.path.expanduser(self._TODO_PATH)
                    written = await _mesh_write_file(
                        self._runtime, path, json.dumps(data["todos"], indent=2),
                    )
                    if not written:
                        return {"success": False, "error": "Failed to save todos"}
            except (json.JSONDecodeError, TypeError):
                pass  # LLM returned prose — that's fine

        return {"success": True, "result": llm_output}
