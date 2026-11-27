"""File search agent — searches for files matching a glob pattern."""

from __future__ import annotations

import asyncio
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
        IntentDescriptor(name="search_files", params={"path": "<absolute_path>", "pattern": "<glob>", "include_ignored": "<bool, default false>"}, description="Search for files matching pattern (skips .gitignored/.venv/node_modules by default)", usage_hint="[MESH search_files path=<dir> pattern=<glob>] (find files by name; gitignored dirs skipped — pass include_ignored=true to search them)"),
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

        return {
            "action": "search",
            "path": path,
            "pattern": pattern,
            # AD-990: skip .gitignored / .venv / node_modules / binary by default
            # (ripgrep's automatic-filtering behavior); pass include_ignored=true
            # to fall back to a raw recursive glob over everything.
            "include_ignored": bool(params.get("include_ignored", False)),
        }

    async def act(self, plan: Any) -> Any:
        """Execute the planned operation."""
        action = plan.get("action")

        if action == "error":
            return {"success": False, "error": plan["error"]}

        if action == "search":
            return await self._search_files(
                plan["path"], plan["pattern"], plan.get("include_ignored", False),
            )

        return {"success": False, "error": f"Unknown action: {action}"}

    async def report(self, result: Any) -> dict[str, Any]:
        """Package the result for the mesh."""
        return result

    async def _search_files(
        self, path: str, pattern: str, include_ignored: bool = False,
    ) -> dict[str, Any]:
        """Search for files matching a glob pattern recursively.

        AD-990: by default the walk respects ``.gitignore`` / ``.ignore`` and
        skips the default-ignore dirs (``.venv``, ``node_modules``, ``__pycache__``,
        …) + hidden + binary files — ripgrep's automatic-filtering behavior, so
        results are signal not noise. ``include_ignored=True`` restores the legacy
        raw recursive glob over everything (the escape hatch).

        BF-758: confined to the readable roots. ``search_files`` is in the same
        ``_MESH_READ_INTENT_POOLS`` allowlist as ``read_file`` and reached by
        the same seam, so leaving it open would have moved the leak rather than
        closed it.
        """
        from probos.security.file_access import resolve_for_runtime

        try:
            p = resolve_for_runtime(path, getattr(self, "_runtime", None))
        except Exception as exc:
            return {"success": False, "error": str(exc)}
        try:
            if not p.exists():
                return {"success": False, "error": f"Directory not found: {path}"}
            if not p.is_dir():
                return {"success": False, "error": f"Not a directory: {path}"}

            # BF-972 (#1803): the walk, the match, the read policy and the sort run in one worker thread, so a broad search
            # does not hold the event loop; the result is as before.
            matches = await asyncio.to_thread(_admitted_matches, p, pattern, include_ignored, getattr(self, "_runtime", None))
            return {
                "success": True,
                "data": matches,
                "base_path": str(p.resolve()),
                "count": len(matches),
            }
        except Exception as e:
            return {"success": False, "error": str(e)}


def _admitted_matches(base: Path, pattern: str, include_ignored: bool, runtime: Any) -> list[str]:
    """BF-972 (#1803): the sorted matches of *pattern* under *base* that the read policy admits; run in a worker thread.

    AD-990: the default walk skips ignored, hidden and default-ignore entries and stops at ``iter_files``'s cap;
    ``include_ignored`` is the raw recursive glob. BF-944: a ``..`` pattern or a link under the base can lead out of it, so
    a match is kept when the read policy admits the path it resolves to; the policy is composed after the walk.
    """
    from probos.security.file_access import ReadFloor

    if include_ignored:
        matches = sorted(str(m) for m in base.rglob(pattern))
    else:
        from probos.substrate.file_walk import iter_files
        matches = sorted(str(f) for f in iter_files(base, skip_binary=False) if f.match(pattern))
    floor = ReadFloor(runtime)
    kept = [m for m in matches if floor.permits(m)]  # BF-944: a match the policy refuses is left out and not counted
    if len(kept) != len(matches):
        logger.info("BF-944: file search left out %d match(es) the read policy refuses", len(matches) - len(kept))
    return kept
