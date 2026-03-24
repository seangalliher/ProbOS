"""Organizer utility agents (AD-251).

NoteTakerAgent and SchedulerAgent — both file-backed via mesh I/O.
"""

from __future__ import annotations

import json
import logging
import os
import time
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
    """Write a file via FileWriterAgent.commit_write (personal data path).

    Bundled agents write user-owned personal data (~/.probos/) which does
    not require multi-agent consensus. This calls commit_write() directly
    to ensure data actually reaches disk.
    """
    from probos.agents.file_writer import FileWriterAgent

    result = await FileWriterAgent.commit_write(path, content)
    return result.get("success", False)


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
                    written = await _mesh_write_file(self._runtime, path, content)
                    if not written:
                        return {"success": False, "error": f"Failed to save note: {filename}"}
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
    """Set reminders and manage schedule — tasks execute on timer within the session."""

    agent_type = "scheduler"
    instructions = (
        "You are a scheduling and reminder agent. You help the user set reminders "
        "and manage time.\n\n"
        "Operations:\n"
        "- remind: Set a reminder (will be delivered on schedule while ProbOS is running)\n"
        "- list: Show upcoming reminders and scheduled tasks\n"
        "- cancel: Cancel a reminder by task_id\n"
        "- check: Check what's coming up today/this week\n\n"
        "Reminders will now be delivered on schedule as long as ProbOS is running. "
        "Tasks are now persistent and survive server restarts. For recurring tasks, "
        "specify an interval (e.g., 'every hour', 'every day'). Cron expressions "
        "are also supported for complex schedules.\n\n"
        "Return a JSON object with:\n"
        "  action: the action performed\n"
        "  For 'remind': delay_seconds (number), text (what to do), "
        "interval_seconds (optional, for recurring), message (confirmation)\n"
        "  For 'list': message (a human-readable summary)\n"
        "  For 'cancel': task_id (string), message (confirmation)\n"
        "  For 'check': message (a human-readable summary)\n"
        "  reminders: the updated list (array of {text, when, created} objects) "
        "for file persistence\n"
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
            parts = []
            if content:
                parts.append(f"Saved reminders:\n{content}")
            else:
                parts.append("Saved reminders:\n[]")
            # Include live scheduled tasks from TaskScheduler (AD-283)
            if hasattr(self._runtime, "task_scheduler") and self._runtime.task_scheduler:
                tasks = self._runtime.task_scheduler.list_tasks()
                if tasks:
                    lines = [f"  {t.id}: {t.intent_text} (status={t.status})" for t in tasks]
                    parts.append(f"Active scheduled tasks ({len(tasks)}):\n" + "\n".join(lines))
                else:
                    parts.append("Active scheduled tasks: none")
            # Include persistent scheduled tasks (Phase 25a)
            if hasattr(self._runtime, "persistent_task_store") and self._runtime.persistent_task_store:
                try:
                    p_tasks = await self._runtime.persistent_task_store.list_tasks(limit=20)
                    if p_tasks:
                        lines = [f"  {t.id}: {t.name} ({t.schedule_type}, status={t.status}, runs={t.run_count})" for t in p_tasks]
                        parts.append(f"Persistent scheduled tasks ({len(p_tasks)}):\n" + "\n".join(lines))
                    else:
                        parts.append("Persistent scheduled tasks: none")
                except Exception:
                    pass
            obs["fetched_content"] = "\n\n".join(parts)
        return obs

    async def act(self, decision: dict) -> dict:
        if decision.get("action") == "error":
            return {"success": False, "error": decision.get("reason")}

        llm_output = decision.get("llm_output", "")

        if self._runtime:
            try:
                data = json.loads(llm_output)
                if isinstance(data, dict):
                    action = data.get("action", "")

                    # --- Schedule a task (AD-283 + Phase 25a) ---
                    if action == "remind":
                        delay = data.get("delay_seconds", 60)
                        text = data.get("text", "")
                        interval = data.get("interval_seconds")
                        channel_id = data.get("channel_id")
                        if text:
                            # Prefer persistent store (Phase 25a) over in-memory scheduler
                            if hasattr(self._runtime, "persistent_task_store") and self._runtime.persistent_task_store:
                                schedule_type = "interval" if interval else "once"
                                execute_at = time.time() + float(delay) if not interval else None
                                await self._runtime.persistent_task_store.create_task(
                                    intent_text=text,
                                    schedule_type=schedule_type,
                                    execute_at=execute_at,
                                    interval_seconds=float(interval) if interval else None,
                                    channel_id=channel_id,
                                )
                            elif hasattr(self._runtime, "task_scheduler") and self._runtime.task_scheduler:
                                self._runtime.task_scheduler.schedule(
                                    text,
                                    delay_seconds=float(delay),
                                    interval_seconds=float(interval) if interval else None,
                                    channel_id=channel_id,
                                )

                    # --- List tasks from both stores ---
                    elif action == "list":
                        all_lines = []
                        # Persistent tasks (Phase 25a)
                        if hasattr(self._runtime, "persistent_task_store") and self._runtime.persistent_task_store:
                            p_tasks = await self._runtime.persistent_task_store.list_tasks(limit=20)
                            for t in p_tasks:
                                all_lines.append(f"  [{t.schedule_type}] {t.id}: {t.name} (status={t.status}, runs={t.run_count})")
                        # In-memory tasks
                        if hasattr(self._runtime, "task_scheduler") and self._runtime.task_scheduler:
                            tasks = self._runtime.task_scheduler.list_tasks()
                            for t in tasks:
                                all_lines.append(f"  [session] {t.id}: {t.intent_text} (status={t.status})")
                        if all_lines:
                            return {"success": True, "result": f"{len(all_lines)} task(s):\n" + "\n".join(all_lines)}
                        return {"success": True, "result": data.get("message", "No scheduled tasks.")}

                    # --- Cancel a task ---
                    elif action == "cancel" and hasattr(self._runtime, "task_scheduler") and self._runtime.task_scheduler:
                        task_id = data.get("task_id", "")
                        if task_id:
                            removed = self._runtime.task_scheduler.cancel(task_id)
                            msg = f"Cancelled task {task_id}" if removed else f"Task {task_id} not found"
                            return {"success": True, "result": msg}

                    # Persist reminders to file
                    if "reminders" in data:
                        path = os.path.expanduser(self._REMINDERS_PATH)
                        written = await _mesh_write_file(
                            self._runtime, path,
                            json.dumps(data["reminders"], indent=2),
                        )
                        if not written:
                            return {"success": False, "error": "Failed to save reminders"}
            except (json.JSONDecodeError, TypeError):
                pass

        return {"success": True, "result": llm_output}
