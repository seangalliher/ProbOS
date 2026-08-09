"""AD-1209 (#1160): read a work item's state so a status question is answered
from evidence instead of by repeating the work.

Measured on the reference vessel 2026-07-31: the Captain asked "Are you still
working on task 6419f0e144a4?" and the agent, having no way to look, answered
the only way it could -- it re-ran the whole job. 106 seconds and fifteen fresh
HTTP fetches to answer a question a database row already knew. It happened
again on 2026-08-08, four times in 26 minutes, turning one request into four
work items.

The agent's own words the same day were exactly right:

    "The task I referenced was spun up in a prior session and I don't have a
    live handle to it here -- I can't poll its status directly."

Honest, and the root of the defect. Lacking any way to look, the only route
toward answering "is it done?" is to do the work and see. So a question
becomes a job.

Governance: strictly read-only. This tool cannot cancel, resume, retry or
mutate anything -- AD-1204 owns resumption and this must not grow into it.
Scope is the asking agent's own work: a lookup of someone else's item reports
not-found rather than leaking another agent's task state, which also keeps the
answer honest instead of guessed.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from probos.tools.protocol import ToolResult, ToolType

logger = logging.getLogger(__name__)

# Statuses from which no further work will occur (workforce._TERMINAL_STATUSES).
_TERMINAL = frozenset({"done", "failed", "cancelled"})


class WorkItemStatusTool:
    """AD-1209: look up the state of a work item this agent owns.

    Satisfies the AD-423a ``Tool`` protocol (duck-typed). Never raises out of
    ``invoke`` -- every miss is an honest-degrade ``ToolResult`` the loop can
    reason over (AD-592).
    """

    def __init__(self, *, runtime: Any) -> None:
        self._runtime = runtime

    # ── Tool protocol ─────────────────────────────────────────────
    @property
    def tool_id(self) -> str:
        return "work_item_status"

    @property
    def name(self) -> str:
        return "Work Item Status"

    @property
    def tool_type(self) -> ToolType:
        return ToolType.UTILITY_AGENT

    @property
    def description(self) -> str:
        return (
            "Look up the current state of a background task you opened. Use this "
            "FIRST whenever you are asked whether something is finished, how a "
            "task is going, or what happened to a task id — including when you "
            "recognise the id from earlier in this conversation. It returns the "
            "status, when it was created and last updated, how long it has been "
            "running, and whether it has reached a final state. Answer the "
            "question from what this returns. Starting the work again to find "
            "out how the work is going produces a second copy of it, which is "
            "what this exists to prevent. It is read-only: it reports state and "
            "changes nothing."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "work_item_id": {
                    "type": "string",
                    "description": (
                        "The task id to look up. A prefix of at least 8 "
                        "characters is accepted, so an id quoted from the "
                        "conversation works."
                    ),
                },
            },
            "required": ["work_item_id"],
        }

    @property
    def output_schema(self) -> dict[str, Any]:
        return {"type": "object"}

    # ── Execution ─────────────────────────────────────────────────
    async def invoke(
        self, params: dict[str, Any], context: dict[str, Any] | None = None,
    ) -> ToolResult:
        t0 = time.monotonic()
        ctx = context or {}
        agent_id = str(ctx.get("agent_id") or "")
        wanted = str((params or {}).get("work_item_id") or "").strip()

        def _done(output: dict[str, Any]) -> ToolResult:
            return ToolResult(
                output=output, error=None, duration_ms=(time.monotonic() - t0) * 1000.0,
            )

        if len(wanted) < 8:
            return _done({
                "found": False,
                "reason": (
                    "a task id of at least 8 characters is needed to identify "
                    "one task"
                ),
            })

        store = getattr(self._runtime, "work_item_store", None)
        if store is None:
            return _done({
                "found": False,
                "reason": "task records are not available on this ship",
            })

        try:
            item = await self._resolve(store, wanted, agent_id)
        except Exception:  # noqa: BLE001 — a lookup fault must not fail the turn
            logger.warning(
                "AD-1209: work-item lookup for %r by agent %s failed; the agent "
                "receives a not-found result and continues",
                wanted, agent_id, exc_info=True,
            )
            return _done({
                "found": False,
                "reason": "the task record could not be read just now",
            })

        if item is None:
            return _done({
                "found": False,
                "work_item_id": wanted,
                "reason": (
                    "no task with that id belongs to you. It may belong to "
                    "another crew member, or the id may be wrong."
                ),
            })

        return _done(self._describe(item))

    # ── Internals ─────────────────────────────────────────────────
    async def _resolve(self, store: Any, wanted: str, agent_id: str) -> Any:
        """Find an item by id or id-prefix, scoped to this agent's work.

        Exact id first (the common case, and cheap). Prefix matching exists
        because an agent quoting an id from the transcript sees the shortened
        form the acknowledgement printed.
        """
        get = getattr(store, "get_work_item", None)
        if callable(get):
            exact = await get(wanted)
            if exact is not None and self._owned_by(exact, agent_id):
                return exact

        listing = getattr(store, "list_work_items", None)
        if not callable(listing):
            return None
        for item in await listing() or []:
            if str(getattr(item, "id", "")).startswith(wanted) and self._owned_by(
                item, agent_id
            ):
                return item
        return None

    @staticmethod
    def _owned_by(item: Any, agent_id: str) -> bool:
        """Only the assignee may read an item's state.

        Reporting another agent's task would be a guess dressed as an answer,
        and would leak one crew member's work into another's context. An empty
        ``agent_id`` (synthetic runtimes, tests) is not treated as a wildcard.
        """
        if not agent_id:
            return False
        return str(getattr(item, "assigned_to", "") or "") == agent_id

    @staticmethod
    def _describe(item: Any) -> dict[str, Any]:
        status = str(getattr(item, "status", "") or "")
        updated = float(getattr(item, "updated_at", 0) or 0)
        created = float(getattr(item, "created_at", 0) or 0)
        now = time.time()
        terminal = status in _TERMINAL
        idle = max(0.0, now - updated) if updated else 0.0

        if terminal:
            summary = f"This task is {status}; no further work will happen on it."
        else:
            summary = (
                f"This task is {status} and has not reached a final state. "
                f"Nothing has been recorded against it for "
                f"{int(idle // 60)} minutes."
            )

        return {
            "found": True,
            "work_item_id": str(getattr(item, "id", "")),
            "title": str(getattr(item, "title", "") or ""),
            "status": status,
            "is_final": terminal,
            "created_at": created,
            "updated_at": updated,
            "age_seconds": round(max(0.0, now - created), 1) if created else 0.0,
            "seconds_since_last_change": round(idle, 1),
            "summary": summary,
        }
