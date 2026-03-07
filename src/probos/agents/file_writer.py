"""File writer agent — writes files, gated by consensus."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from probos.substrate.agent import BaseAgent
from probos.types import CapabilityDescriptor, IntentMessage, IntentResult

logger = logging.getLogger(__name__)


class FileWriterAgent(BaseAgent):
    """Concrete agent that writes files to the local filesystem.

    Writes are NOT executed directly. Instead, the agent proposes
    the write and sets requires_consensus=True on its result. The
    runtime's consensus layer must approve before the write commits.

    Capabilities: write_file.
    """

    agent_type: str = "file_writer"
    default_capabilities = [
        CapabilityDescriptor(
            can="write_file",
            detail="Write content to a file on the filesystem",
            formats=["text"],
        ),
    ]
    initial_confidence: float = 0.8

    _handled_intents = {"write_file"}

    async def handle_intent(self, intent: IntentMessage) -> IntentResult | None:
        """Full lifecycle: perceive -> decide -> act -> report.

        The act phase proposes the write but does NOT commit it.
        The runtime consensus layer calls commit_write() if approved.
        """
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
        content = params.get("content")

        if not path:
            return {"action": "error", "error": "No path specified"}
        if content is None:
            return {"action": "error", "error": "No content specified"}

        return {"action": "write", "path": path, "content": content}

    async def act(self, plan: Any) -> Any:
        """Validate the write operation without committing.

        The actual write happens in commit_write() after consensus.
        """
        action = plan.get("action")

        if action == "error":
            return {"success": False, "error": plan["error"]}

        if action == "write":
            path = plan["path"]
            content = plan["content"]

            # Validate that the write is feasible
            try:
                p = Path(path)
                parent = p.parent
                if not parent.exists():
                    return {
                        "success": False,
                        "error": f"Parent directory does not exist: {parent}",
                    }
                # Return a proposal (not executed)
                return {
                    "success": True,
                    "data": {
                        "path": str(p),
                        "content": content,
                        "size": len(content),
                        "requires_consensus": True,
                    },
                }
            except Exception as e:
                return {"success": False, "error": str(e)}

        return {"success": False, "error": f"Unknown action: {action}"}

    async def report(self, result: Any) -> dict[str, Any]:
        """Package the result for the mesh."""
        return result

    @staticmethod
    async def commit_write(path: str, content: str) -> dict[str, Any]:
        """Actually write the file. Called by the runtime after consensus approval."""
        try:
            p = Path(path)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8")
            return {
                "success": True,
                "path": str(p.resolve()),
                "size": len(content),
            }
        except Exception as e:
            return {"success": False, "error": str(e)}
