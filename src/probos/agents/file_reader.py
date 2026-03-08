"""File reader agent — reads files from the filesystem."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from probos.substrate.agent import BaseAgent
from probos.types import CapabilityDescriptor, IntentDescriptor, IntentMessage, IntentResult

logger = logging.getLogger(__name__)


class FileReaderAgent(BaseAgent):
    """Concrete agent that reads files from the local filesystem.

    Capabilities: read_file, stat_file.
    Participates in the mesh via intent self-selection.
    """

    agent_type: str = "file_reader"
    default_capabilities = [
        CapabilityDescriptor(
            can="read_file",
            detail="Read file contents from the filesystem",
            formats=["text", "binary", "csv", "json", "yaml"],
        ),
        CapabilityDescriptor(
            can="stat_file",
            detail="Return file metadata (size, modified, permissions)",
        ),
    ]
    initial_confidence: float = 0.8
    intent_descriptors = [
        IntentDescriptor(name="read_file", params={"path": "<absolute_path>"}, description="Read a file and return content"),
        IntentDescriptor(name="stat_file", params={"path": "<absolute_path>"}, description="Get file size, mtime, etc."),
    ]

    # Intent names this agent handles
    _handled_intents = {"read_file", "stat_file"}

    async def handle_intent(self, intent: IntentMessage) -> IntentResult | None:
        """Full lifecycle: perceive -> decide -> act -> report.

        Called by the intent bus. Returns None if this agent declines.
        """
        observation = await self.perceive(intent.__dict__)
        if observation is None:
            return None  # Not my job

        plan = await self.decide(observation)
        if plan is None:
            return None  # Declined

        result = await self.act(plan)
        report = await self.report(result)

        success = report.get("success", False)
        self.update_confidence(success)

        return IntentResult(
            intent_id=intent.id,
            agent_id=self.id,
            success=success,
            result=report.get("data"),
            error=report.get("error"),
            confidence=self.confidence,
        )

    async def perceive(self, intent: dict[str, Any]) -> Any:
        """Check if this intent is something we handle."""
        intent_name = intent.get("intent", "")
        if intent_name not in self._handled_intents:
            return None
        return {
            "intent": intent_name,
            "params": intent.get("params", {}),
        }

    async def decide(self, observation: Any) -> Any:
        """Plan what to do based on the perceived intent."""
        intent_name = observation["intent"]
        params = observation["params"]

        if intent_name == "read_file":
            path = params.get("path")
            if not path:
                return {"action": "error", "error": "No path specified"}
            return {"action": "read", "path": path}

        if intent_name == "stat_file":
            path = params.get("path")
            if not path:
                return {"action": "error", "error": "No path specified"}
            return {"action": "stat", "path": path}

        return None

    async def act(self, plan: Any) -> Any:
        """Execute the planned filesystem operation."""
        action = plan.get("action")

        if action == "error":
            return {"success": False, "error": plan["error"]}

        if action == "read":
            return await self._read_file(plan["path"])

        if action == "stat":
            return await self._stat_file(plan["path"])

        return {"success": False, "error": f"Unknown action: {action}"}

    async def report(self, result: Any) -> dict[str, Any]:
        """Package the result for the mesh."""
        return result

    async def _read_file(self, path: str) -> dict[str, Any]:
        """Read file contents."""
        try:
            p = Path(path)
            if not p.exists():
                return {"success": False, "error": f"File not found: {path}"}
            if not p.is_file():
                return {"success": False, "error": f"Not a file: {path}"}

            content = p.read_text(encoding="utf-8", errors="replace")
            return {
                "success": True,
                "data": content,
                "path": str(p.resolve()),
                "size": len(content),
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def _stat_file(self, path: str) -> dict[str, Any]:
        """Get file metadata."""
        try:
            p = Path(path)
            if not p.exists():
                return {"success": False, "error": f"File not found: {path}"}

            stat = p.stat()
            return {
                "success": True,
                "data": {
                    "path": str(p.resolve()),
                    "size": stat.st_size,
                    "modified": stat.st_mtime,
                    "is_file": p.is_file(),
                    "is_dir": p.is_dir(),
                },
            }
        except Exception as e:
            return {"success": False, "error": str(e)}
