"""File search agent — searches for files matching a glob pattern."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from probos.substrate.agent import BaseAgent
from probos.types import CapabilityDescriptor, IntentDescriptor, IntentMessage, IntentResult

logger = logging.getLogger(__name__)


class FileSearchAgent(BaseAgent):
    """Concrete agent that searches for files matching a glob pattern.

    Capabilities: search_files.
    Low-risk operation — no consensus required.
    """

    agent_type: str = "file_search"
    tier = "core"
    default_capabilities = [
        CapabilityDescriptor(
            can="search_files",
            detail="Search for files matching a glob pattern",
            formats=["json"],
        ),
    ]
    initial_confidence: float = 0.8
    intent_descriptors = [
        IntentDescriptor(name="search_files", params={"path": "<absolute_path>", "pattern": "<glob>"}, description="Search for files matching pattern"),
    ]

    _handled_intents = {"search_files"}

    async def handle_intent(self, intent: IntentMessage) -> IntentResult | None:
        """Full lifecycle: perceive -> decide -> act -> report."""
        observation = await self.perceive(intent.__dict__)
        if observation is None:
            return None

        plan = await self.decide(observation)
        if plan is None:
            return None

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
        params = observation["params"]
        path = params.get("path")
        pattern = params.get("pattern")

        if not path:
            return {"action": "error", "error": "No path specified"}
        if not pattern:
            return {"action": "error", "error": "No pattern specified"}

        return {"action": "search", "path": path, "pattern": pattern}

    async def act(self, plan: Any) -> Any:
        """Execute the planned operation."""
        action = plan.get("action")

        if action == "error":
            return {"success": False, "error": plan["error"]}

        if action == "search":
            return await self._search_files(plan["path"], plan["pattern"])

        return {"success": False, "error": f"Unknown action: {action}"}

    async def report(self, result: Any) -> dict[str, Any]:
        """Package the result for the mesh."""
        return result

    async def _search_files(self, path: str, pattern: str) -> dict[str, Any]:
        """Search for files matching a glob pattern recursively."""
        try:
            p = Path(path)
            if not p.exists():
                return {"success": False, "error": f"Directory not found: {path}"}
            if not p.is_dir():
                return {"success": False, "error": f"Not a directory: {path}"}

            matches = sorted(str(m) for m in p.rglob(pattern))
            return {
                "success": True,
                "data": matches,
                "base_path": str(p.resolve()),
                "count": len(matches),
            }
        except Exception as e:
            return {"success": False, "error": str(e)}
