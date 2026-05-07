"""AD-548 v1: Standing-orders blocked-paths pre-hook for native SWE tools.

Reframed scope: AD-423a/b/c + AD-448 already ship the trust-tiered access
matrix and pre/post hook substrate. v1 adds only the blocked-paths factory;
the YAML tool-policy schema (per-tool blocked_paths under tools.<name>.<key>
with hot-reload) is deferred to AD-548b — forcing function: first production
deny-policy that needs operator-side tunability without code change.
"""

from __future__ import annotations

import logging
from typing import Any, Callable

logger = logging.getLogger(__name__)

PreHook = Callable[[dict[str, Any]], bool]


def make_blocked_paths_hook(blocked_paths: list[str]) -> PreHook:
    """Factory returning an AD-448 PreHook that denies tool calls touching blocked paths.

    Match strategy:
    - For tools with a 'path' / 'file_path' param: substring match against any
      blocked pattern.
    - For ``run_command``: substring match against the ``command`` and
      ``working_directory`` params (if present).
    - All other tools: hook returns True (no path semantics, no enforcement).

    Returns False to deny — AD-448 ToolExecutor translates this to
    ``ToolResult(error="Pre-hook aborted invocation of <tool>")`` fed back
    to the LLM as a tool result so the loop can adapt. Never raises.

    Tier-2 log-and-degrade: hook errors warn and fail open (return True).
    The deny path is the safety-relevant code path; the hook itself
    failing should not block legitimate work.
    """
    if not blocked_paths:
        return lambda ctx: True

    patterns = [p for p in blocked_paths if p]

    def hook(ctx: dict[str, Any]) -> bool:
        try:
            params = ctx.get("params", {}) or {}
            tool_id = ctx.get("tool_id", "")

            check_targets: list[str] = []
            for key in ("path", "file_path"):
                if key in params and params[key] is not None:
                    check_targets.append(str(params[key]))
            if tool_id == "run_command":
                if "command" in params and params["command"] is not None:
                    check_targets.append(str(params["command"]))
                if (
                    "working_directory" in params
                    and params["working_directory"] is not None
                ):
                    check_targets.append(str(params["working_directory"]))

            for target in check_targets:
                for pattern in patterns:
                    if pattern in target:
                        logger.warning(
                            "AD-548: Pre-hook denied tool=%s for agent=%s — "
                            "param matched blocked pattern '%s' in '%s'",
                            tool_id,
                            str(ctx.get("agent_id", "<unknown>"))[:12],
                            pattern,
                            target[:80],
                        )
                        return False
            return True
        except Exception:
            logger.warning(
                "AD-548: blocked_paths hook itself failed; failing open (permissive)",
                exc_info=True,
            )
            return True

    return hook
