"""AD-1356 S2 (#1722): the tool-effect table, the one source of agent-work tiering.

A tool's tier names who authorises an agent-work call to it, in AD-676's names: a ``routine`` call runs with no
approval; an ``elevated`` or ``critical`` call is put to the run's gate. A tool is in the table only by name. A tool id
the table does not list (a new or renamed tool, every ``mcp:`` tool) and an id that is not a str are critical.

``routine_tool_ids`` is what a run reads (``agent_work_runner``); ``tool_tier`` classifies one id. The members are
seeded from the plan-mode read set (``cognitive.agent_mode.PLAN_MODE_TOOL_IDS``, held to reads by
``tests/test_ad1156_plan_execute_mode.py``) and from ``execution.effect_broker``'s effect classes, never from the rank
grant matrix (``derive_tool_permission``), which records what a rank is granted, not what a tool does. Pinned member by
member in ``tests/test_ad1356_s2_tool_effect_table.py``. Stdlib only.
"""

from __future__ import annotations

from typing import Final

TIER_ROUTINE: Final = "routine"
TIER_ELEVATED: Final = "elevated"
TIER_CRITICAL: Final = "critical"

#: Routine: each reads, changes nothing and stays on the ship. The ten tools agent work called directly before
#: AD-1356 S2, and three code readers.
ROUTINE_TOOL_IDS: Final[frozenset[str]] = frozenset({
    "event_log_query", "oracle_query", "self_query", "search_capabilities", "use_skill",
    "work_item_status", "read_owned_steps", "recall_artifact", "message_receipts", "load_tools",
    "codebase_query", "codebase_read_source", "read_file",
})
#: The routine tools that read a path through the operator's read policy (``security.file_access.resolve_for_runtime``).
#: With ``security_infra.read_roots`` unset that policy reaches any file outside the runtime's data directory and config
#: files, so these are routine only while the roots are set, and critical otherwise.
READ_POLICY_TOOL_IDS: Final[frozenset[str]] = frozenset({"codebase_read_source", "read_file"})
#: Elevated: reads that reach past what the ship holds or past the read policy. find_mcp_tool discovers and offers new
#: tools; web_search, read_page and http_fetch leave the ship (the Captain's Q6, 2026-10-31); list_files resolves its
#: path without the read policy (``swe_harness.tools._resolve_path``).
ELEVATED_TOOL_IDS: Final[frozenset[str]] = frozenset({
    "find_mcp_tool", "http_fetch", "list_files", "read_page", "web_search",
})


def tool_tier(tool_id: object, *, reads_confined: bool) -> str:
    """The tier of ``tool_id``; ``reads_confined`` is whether ``security_infra.read_roots`` is set."""
    if type(tool_id) is not str:
        return TIER_CRITICAL
    if tool_id in ROUTINE_TOOL_IDS:
        return TIER_ROUTINE if reads_confined or tool_id not in READ_POLICY_TOOL_IDS else TIER_CRITICAL
    if tool_id in ELEVATED_TOOL_IDS:
        return TIER_ELEVATED
    return TIER_CRITICAL


def routine_tool_ids(*, reads_confined: bool) -> frozenset[str]:
    """The tools an agent-work run calls with no approval: the members ``tool_tier`` holds routine."""
    return frozenset(
        tool_id for tool_id in ROUTINE_TOOL_IDS if tool_tier(tool_id, reads_confined=reads_confined) == TIER_ROUTINE
    )
