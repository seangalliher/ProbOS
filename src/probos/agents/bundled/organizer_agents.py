"""Organizer bundled agents (AD-251).

NoteTakerAgent and SchedulerAgent — both file-backed via mesh I/O.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

from probos.cognitive.cognitive_agent import CognitiveAgent
from probos.types import (
    CapabilityDescriptor,
    IntentDescriptor,
    IntentMessage,
    IntentResult,
)

logger = logging.getLogger(__name__)


# ------------------------------------------------------------------
# Bundled agent mixin: self-deselect for unrecognized intents
# ------------------------------------------------------------------

class _BundledMixin:
    """Mixin that guards handle_intent to self-deselect unrecognized intents."""

    async def handle_intent(self, intent: IntentMessage) -> IntentResult | None:
        if intent.intent not in self._handled_intents:
            return None  # Self-deselect
        return await super().handle_intent(intent)


# ------------------------------------------------------------------
# Mesh file I/O helpers (same pattern as productivity_agents)
# ------------------------------------------------------------------

async def _mesh_read_file(runtime: Any, path: str) -> str | None:
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
    if not runtime or not hasattr(runtime, "intent_bus"):
        return False
    msg = IntentMessage(
        intent="write_file",
        params={"path": path, "content": content},
    )
    results = await runtime.intent_bus.broadcast(msg)
    return any(r.success for r in results)


async def _mesh_list_dir(runtime: Any, path: str) -> str | None:
    if not runtime or not hasattr(runtime, "intent_bus"):
        return None
    msg = IntentMessage(intent="list_directory", params={"path": path})
    results = await runtime.intent_bus.broadcast(msg)
    for r in results:
        if r.success and r.result:
            return str(r.result)
    return None


# ------------------------------------------------------------------
# NoteTakerAgent
# ------------------------------------------------------------------

class NoteTakerAgent(_BundledMixin, CognitiveAgent):
    """Save, search, and organize personal notes (file-backed)."""

    agent_type = "note_taker"
    instructions = (
        "You are a personal notes agent. You help the user save and retrieve notes.\n\n"
        "Operations:\n"
        "- save: Save a note with a title and optional tags\n"
        "- search: Find notes matching a query\n"
        "- list: Show recent notes\n"
        "- read: Read a specific note by title\n\n"
        "Notes are stored as individual files in ~/.probos/notes/ \u2014 one .md file per note.\n"
        "The current directory listing or note content is provided to you.\n\n"
        "For save operations, return a JSON object with:\n"
        "  action: \"save\"\n"
        "  filename: the sanitized filename (e.g., my-note.md)\n"
        "  content: the note content in markdown\n"
        "  message: confirmation message\n\n"
        "For other operations, return a human-readable response."
    )
    intent_descriptors = [
        IntentDescriptor(
            name="manage_notes",
            params={
                "action": "save|search|list|read",
                "title": "note title",
                "content": "note content",
                "query": "search query",
            },
            description="Save, search, and organize personal notes",
        ),
    ]
    _handled_intents = {"manage_notes"}
    default_capabilities = [CapabilityDescriptor(can="manage_notes")]

    _NOTES_DIR = "~/.probos/notes"

    async def perceive(self, intent: Any) -> dict:
        obs = await super().perceive(intent)
        if not self._runtime:
            return obs

        action = obs.get("params", {}).get("action", "list")
        notes_dir = os.path.expanduser(self._NOTES_DIR)

        if action == "read":
            title = obs.get("params", {}).get("title", "")
            if title:
                # Sanitize filename
                filename = title.replace(" ", "-").lower()
                if not filename.endswith(".md"):
                    filename += ".md"
                content = await _mesh_read_file(self._runtime, f"{notes_dir}/{filename}")
                if content:
                    obs["fetched_content"] = f"Note '{title}':\n{content}"
                else:
                    obs["fetched_content"] = f"Note '{title}' not found."

        elif action == "search":
            query = obs.get("params", {}).get("query", "")
            # Try semantic search first
            if hasattr(self._runtime, "_semantic_layer") and self._runtime._semantic_layer:
                results = self._runtime._semantic_layer.search(query, limit=5)
                if results:
                    obs["fetched_content"] = f"Search results for '{query}':\n{json.dumps(results, default=str)}"
                    return obs
            # Fall back to listing
            listing = await _mesh_list_dir(self._runtime, notes_dir)
            obs["fetched_content"] = f"Available notes:\n{listing or 'None'}"

        else:  # list
            listing = await _mesh_list_dir(self._runtime, notes_dir)
            obs["fetched_content"] = f"Available notes:\n{listing or 'None'}"

        return obs

    async def act(self, decision: dict) -> dict:
        if decision.get("action") == "error":
            return {"success": False, "error": decision.get("reason")}

        llm_output = decision.get("llm_output", "")

        # Handle save operations
        if self._runtime:
            try:
                data = json.loads(llm_output)
                if isinstance(data, dict) and data.get("action") == "save":
                    notes_dir = os.path.expanduser(self._NOTES_DIR)
                    filename = data.get("filename", "untitled.md")
                    content = data.get("content", "")
                    path = f"{notes_dir}/{filename}"
                    await _mesh_write_file(self._runtime, path, content)
                    return {
                        "success": True,
                        "result": data.get("message", f"Note saved: {filename}"),
                    }
            except (json.JSONDecodeError, TypeError):
                pass

        return {"success": True, "result": llm_output}


# ------------------------------------------------------------------
# SchedulerAgent
# ------------------------------------------------------------------

class SchedulerAgent(_BundledMixin, CognitiveAgent):
    """Set reminders and manage schedule (file-backed, no background timer)."""

    agent_type = "scheduler"
    instructions = (
        "You are a scheduling and reminder agent. You help the user set reminders "
        "and manage time.\n\n"
        "Operations:\n"
        "- remind: Set a reminder (stored with timestamp)\n"
        "- list: Show upcoming reminders\n"
        "- cancel: Cancel a reminder\n"
        "- check: Check what's coming up today/this week\n\n"
        "Reminders are stored in ~/.probos/reminders.json. The current reminders are "
        "provided to you.\n\n"
        "Return a JSON object with:\n"
        "  action: the action performed\n"
        "  reminders: the updated list (array of {text, when, created} objects)\n"
        "  message: a human-readable summary\n\n"
        "Note: ProbOS currently has no background timer \u2014 reminders are checked "
        "when the user interacts or at boot. Be transparent about this limitation."
    )
    intent_descriptors = [
        IntentDescriptor(
            name="manage_schedule",
            params={
                "action": "remind|list|cancel|check",
                "text": "reminder text",
                "when": "datetime or relative time",
            },
            description="Set reminders and manage schedule",
            requires_reflect=True,
        ),
    ]
    _handled_intents = {"manage_schedule"}
    default_capabilities = [CapabilityDescriptor(can="manage_schedule")]

    _REMINDERS_PATH = "~/.probos/reminders.json"

    async def perceive(self, intent: Any) -> dict:
        obs = await super().perceive(intent)
        if self._runtime:
            path = os.path.expanduser(self._REMINDERS_PATH)
            content = await _mesh_read_file(self._runtime, path)
            if content:
                obs["fetched_content"] = f"Current reminders:\n{content}"
            else:
                obs["fetched_content"] = "Current reminders:\n[]"
        return obs

    async def act(self, decision: dict) -> dict:
        if decision.get("action") == "error":
            return {"success": False, "error": decision.get("reason")}

        llm_output = decision.get("llm_output", "")

        # Persist changes
        if self._runtime:
            try:
                data = json.loads(llm_output)
                if isinstance(data, dict) and "reminders" in data:
                    path = os.path.expanduser(self._REMINDERS_PATH)
                    await _mesh_write_file(
                        self._runtime, path,
                        json.dumps(data["reminders"], indent=2),
                    )
            except (json.JSONDecodeError, TypeError):
                pass

        return {"success": True, "result": llm_output}
