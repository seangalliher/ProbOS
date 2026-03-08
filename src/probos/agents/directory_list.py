"""Directory list agent — lists files and directories."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from probos.substrate.agent import BaseAgent
from probos.types import CapabilityDescriptor, IntentDescriptor, IntentMessage, IntentResult

logger = logging.getLogger(__name__)


class DirectoryListAgent(BaseAgent):
    """Concrete agent that lists directory contents.

    Capabilities: list_directory.
    Low-risk operation — no consensus required.
    """

    agent_type: str = "directory_list"
    default_capabilities = [
        CapabilityDescriptor(
            can="list_directory",
            detail="List files and directories in a directory",
            formats=["json"],
        ),
    ]
    initial_confidence: float = 0.8
    intent_descriptors = [
        IntentDescriptor(name="list_directory", params={"path": "<absolute_path>"}, description="List files and directories"),
    ]

    _handled_intents = {"list_directory"}

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

        if not path:
            return {"action": "error", "error": "No path specified"}

        return {"action": "list", "path": path}

    async def act(self, plan: Any) -> Any:
        """Execute the planned operation."""
        action = plan.get("action")

        if action == "error":
            return {"success": False, "error": plan["error"]}

        if action == "list":
            return await self._list_directory(plan["path"])

        return {"success": False, "error": f"Unknown action: {action}"}

    async def report(self, result: Any) -> dict[str, Any]:
        """Package the result for the mesh."""
        return result

    async def _list_directory(self, path: str) -> dict[str, Any]:
        """List directory contents."""
        try:
            p = Path(path)
            if not p.exists():
                return {"success": False, "error": f"Directory not found: {path}"}
            if not p.is_dir():
                return {"success": False, "error": f"Not a directory: {path}"}

            entries = []
            for entry in sorted(p.iterdir()):
                try:
                    stat = entry.stat()
                    entries.append({
                        "name": entry.name,
                        "type": "dir" if entry.is_dir() else "file",
                        "size": stat.st_size,
                    })
                except OSError:
                    entries.append({
                        "name": entry.name,
                        "type": "unknown",
                        "size": 0,
                    })

            return {
                "success": True,
                "data": entries,
                "path": str(p.resolve()),
                "count": len(entries),
            }
        except Exception as e:
            return {"success": False, "error": str(e)}
