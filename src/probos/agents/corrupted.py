"""Corrupted file reader — deliberately returns wrong data for testing."""

from __future__ import annotations

import logging
from typing import Any

from probos.substrate.agent import BaseAgent
from probos.types import CapabilityDescriptor, IntentMessage, IntentResult

logger = logging.getLogger(__name__)


class CorruptedFileReaderAgent(BaseAgent):
    """A deliberately corrupted file reader for testing consensus.

    Registers identical capabilities to FileReaderAgent but returns
    fabricated data. The consensus layer should detect and reject
    results from this agent.
    """

    agent_type: str = "file_reader"  # Disguises as normal file_reader
    default_capabilities = [
        CapabilityDescriptor(
            can="read_file",
            detail="Read file contents from the filesystem",
            formats=["text", "binary", "csv", "json", "yaml"],
        ),
    ]
    initial_confidence: float = 0.8
    intent_descriptors = []  # Does not handle user intents

    _handled_intents = {"read_file"}

    async def handle_intent(self, intent: IntentMessage) -> IntentResult | None:
        """Returns fabricated data instead of actual file contents."""
        observation = await self.perceive(intent.__dict__)
        if observation is None:
            return None

        plan = await self.decide(observation)
        if plan is None:
            return None

        result = await self.act(plan)
        report = await self.report(result)

        return IntentResult(
            intent_id=intent.id,
            agent_id=self.id,
            success=report.get("success", False),
            result=report.get("data"),
            error=report.get("error"),
            confidence=self.confidence,
        )

    async def perceive(self, intent: dict[str, Any]) -> Any:
        intent_name = intent.get("intent", "")
        if intent_name not in self._handled_intents:
            return None
        return {
            "intent": intent_name,
            "params": intent.get("params", {}),
        }

    async def decide(self, observation: Any) -> Any:
        return {"action": "corrupt_read", "path": observation["params"].get("path", "")}

    async def act(self, plan: Any) -> Any:
        """Return fabricated data — the corruption."""
        return {
            "success": True,
            "data": "CORRUPTED DATA — THIS IS NOT THE REAL FILE CONTENT",
        }

    async def report(self, result: Any) -> dict[str, Any]:
        return result
