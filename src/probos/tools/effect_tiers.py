"""AD-1356 S2 (#1722): the tool-effect table, the one source of agent-work tiering.

A tool's tier, in AD-676's names, sets who decides an agent-work call to it (``tier_decider``, AD-1356 S4): the
Captain's ``approval_inbox`` setting for a ``routine`` or ``elevated`` tool, and the Captain for a ``critical`` one. A
tool is in the table only by name. A tool id the table does not list (a new or renamed tool) and an id that is not a
str are critical. So is an ``mcp:`` tool, except that ``filed_call_tier`` (AD-1356 S3) takes a filed call's tier from
AD-1019b's risk in the tool's registration (``mcp_tool_tier``).

``direct_tool_ids`` is what a run reads (``agent_work_runner``); ``tool_tier`` classifies one id;
``delegated_approvals.classify_capability_request`` reads ``filed_call_tier`` and ``tier_decider``. The members are
seeded from the plan-mode read set (``cognitive.agent_mode.PLAN_MODE_TOOL_IDS``, held to reads by
``tests/test_ad1156_plan_execute_mode.py``) and from ``execution.effect_broker``'s effect classes, never from the rank
grant matrix (``derive_tool_permission``), which records what a rank is granted, not what a tool does. Pinned member by
member in ``tests/test_ad1356_s2_tool_effect_table.py``. Imports only the stdlib; ``mcp_tool_tier`` imports
``McpToolRisk`` when it is called.
"""

from __future__ import annotations

import logging
from typing import Any, Final

logger = logging.getLogger(__name__)

TIER_ROUTINE: Final = "routine"
TIER_ELEVATED: Final = "elevated"
TIER_CRITICAL: Final = "critical"

#: Routine: each reads and stays on the ship. The ten tools agent work called directly before
#: AD-1356 S2, and three code readers.
ROUTINE_TOOL_IDS: Final[frozenset[str]] = frozenset({
    "event_log_query", "oracle_query", "self_query", "search_capabilities", "use_skill",
    "work_item_status", "read_owned_steps", "recall_artifact", "message_receipts", "load_tools",
    "codebase_query", "codebase_read_source", "read_file",
})
#: The routine tools that read a path through the operator's read policy (``security.file_access.resolve_for_runtime``).
#: With ``security_infra.read_roots`` unset that policy reaches outside the runtime's data directory and config
#: files, so these are routine only while the roots are set, and critical otherwise.
READ_POLICY_TOOL_IDS: Final[frozenset[str]] = frozenset({"codebase_read_source", "read_file"})
#: Elevated. find_mcp_tool discovers and offers new tools; web_search, read_page and http_fetch leave the ship (the
#: Captain's Q6, 2026-10-31); list_files is held here until the Captain decides its tier (BF-948, LF4).
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
    """The members ``tool_tier`` holds routine (``direct_tool_ids`` under the default settings)."""
    return frozenset(
        tool_id for tool_id in ROUTINE_TOOL_IDS if tool_tier(tool_id, reads_confined=reads_confined) == TIER_ROUTINE
    )


#: AD-1356 S4 (#1722): who decides an agent-work call of a tier (``approval_inbox.agent_work_<tier>_decider``).
#: ``auto``: the run calls the tier's listed tools directly (``direct_tool_ids``), and a filed call of the tier is
#: decided as under ``chief``. ``chief``: AD-1213's route decides a filed call (a department chief at the first hop in
#: the requester's department, the First Officer under a live delegation after the grace period, otherwise the
#: Captain; with ``delegated_approvals_enabled`` off, the Captain). ``captain``: the Captain alone. ``tier_decider``
#: takes no critical setting (``agent_work_critical_decider`` admits only ``captain``).
DECIDER_AUTO: Final = "auto"
DECIDER_CHIEF: Final = "chief"
DECIDER_CAPTAIN: Final = "captain"
_DELEGABLE: Final[frozenset[str]] = frozenset({DECIDER_AUTO, DECIDER_CHIEF})


def tier_decider(tier: object, *, routine: object, elevated: object) -> str:
    """Who decides a call of ``tier``: for ``routine`` and ``elevated``, the Captain's setting for it; for ``critical``
    and anything else, the Captain. A setting that is not exactly the str ``auto`` or ``chief`` is the Captain."""
    if type(tier) is not str or tier not in (TIER_ROUTINE, TIER_ELEVATED):
        return DECIDER_CAPTAIN
    chosen = routine if tier == TIER_ROUTINE else elevated
    return chosen if type(chosen) is str and chosen in _DELEGABLE else DECIDER_CAPTAIN


def direct_tool_ids(*, reads_confined: bool, routine: object, elevated: object) -> frozenset[str]:
    """An agent-work run's direct set (``ToolCallConfinement.tool_ids``): each tool the table lists whose tier's decider
    is ``auto``. With the default settings (routine ``auto``, elevated ``chief``) it is ``routine_tool_ids``. It may be
    empty."""
    return frozenset(
        tool_id for tool_id in ROUTINE_TOOL_IDS | ELEVATED_TOOL_IDS
        if tier_decider(tool_tier(tool_id, reads_confined=reads_confined), routine=routine, elevated=elevated)
        == DECIDER_AUTO
    )


def mcp_tool_tier(risk: object) -> str:
    """AD-1356 S3: an ``mcp:`` tool's tier from AD-1019b's effective risk. ``McpToolRisk.OPEN`` is elevated;
    ``CONFIRM``, ``CONSENSUS`` and anything that is not that exact member are critical."""
    from probos.integrations.mcp_bridge.risk import McpToolRisk  # loaded only when an mcp: call is classified

    return TIER_ELEVATED if risk is McpToolRisk.OPEN else TIER_CRITICAL


def filed_call_tier(tool_id: object, *, tool_registry: Any) -> str:
    """AD-1356 S3: the tier of an agent-work call that was filed, read when the call is decided.

    A tool that reads a path through the read policy (``READ_POLICY_TOOL_IDS``) is taken as if reads were unconfined, so
    it is critical whatever ``security_infra.read_roots`` says now: a change to the roots after the call was filed never
    widens who decides it. An ``mcp:`` tool takes AD-1019b's risk from its live registration in ``tool_registry``
    (``effective_risk()``); one that is not registered, is disabled, is registered under another id, or whose risk
    cannot be read is critical. Any other id gets ``tool_tier``'s answer.
    """
    if type(tool_id) is not str or not tool_id.startswith("mcp:"):
        return tool_tier(tool_id, reads_confined=False)
    registration = tool_registry.get(tool_id) if tool_registry is not None else None
    if registration is None or registration.enabled is not True or registration.tool.tool_id != tool_id:
        return TIER_CRITICAL
    try:
        return mcp_tool_tier(registration.tool.effective_risk())
    except Exception:
        logger.warning(
            "AD-1356: the risk of MCP tool %s could not be read; its filed call is critical and stays with the Captain",
            tool_id[:80], exc_info=True,
        )
        return TIER_CRITICAL
