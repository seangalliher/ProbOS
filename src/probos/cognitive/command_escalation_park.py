"""AD-1328 S2c (#1530): park a dispatched work item on the command escalation it waits for.

A plain work item (``CognitiveAgent._handle_work_item_dispatch``) runs once and returns.
When its run escalated a ``run_command`` -- filed in the item's scope (``work_item:<id>``)
and linked to it by ``probos.execution.command_escalation`` -- nothing would run the
command once the Captain approves it: the agent's turn has ended. So after the run the
item is parked ``blocked`` on that request through AD-855's
``CapabilityGapDriver.block_on_request``, the one writer of the parking keys, and the
driver does the rest: FULFILLED (the approval recorded) resumes and re-dispatches the
item, whose next run issues the command again and runs it once under the approval; a
denial cancels the item. A request the Captain settled while the run was still going is
resolved as the item parks (BF-878).

Which request: the oldest still pending for this agent in this item's scope; else, of
those filed during this run, the oldest approved and fulfilled whose approval has admitted
no run yet, then the oldest denied. A request settled before this run began is never
parked on again, so a resumed run that does not re-issue its command ends as it would
have before this slice instead of resuming itself.

Never raises; a fault leaves the item as the run left it (``in_progress``). Inert unless
the command approval route is wired (``runtime.command_escalations``).
"""

from __future__ import annotations

import logging
import math
from typing import Any, Final

from probos.execution.command_approvals import (
    COMMAND_APPROVAL_ACTION,
    COMMAND_APPROVAL_TOOL_ID,
    WORK_ITEM_SCOPE_PREFIX,
    command_approval_request,
)
from probos.execution.command_escalation import CommandEscalations

logger = logging.getLogger(__name__)

#: The ``call_site`` a tool-path escalation is filed under (``RunCommandTool`` judges with
#: ``site="run_command_tool"``); the mesh path files nothing.
TOOL_CALL_SITE: Final = "run_command_tool"
#: What the board shows while the item waits (``blocked_reason``).
COMMAND_ESCALATION_BLOCKED_REASON: Final = (
    "waiting for the Captain's decision on an escalated run_command"
)
_STATUSES: Final = ("pending", "fulfilled", "denied")


def _filed_since(req: Any, since: float) -> bool:
    created = getattr(req, "created_at", None)
    return type(created) in (int, float) and math.isfinite(created) and created >= since


async def awaited_command_request(
    runtime: Any, *, agent_id: str, work_item_id: str, since: float,
) -> str:
    """The command escalation a run of ``work_item_id`` leaves the item waiting on, or ``""``.

    Raises on a store fault; :func:`park_on_command_escalation` degrades.
    """
    requests = runtime.capability_request_store
    scope_key = WORK_ITEM_SCOPE_PREFIX + work_item_id
    fulfilled: list[str] = []
    denied: list[str] = []
    for req in requests.find_action_requests_by_param(
        "call_site", TOOL_CALL_SITE, statuses=_STATUSES,
        tool_id=COMMAND_APPROVAL_TOOL_ID, action=COMMAND_APPROVAL_ACTION,
    ):
        ask = command_approval_request(req)
        if ask is None or ask.agent_id != agent_id or ask.scope_key != scope_key:
            continue
        status = getattr(req, "status", None)
        if status == "pending":
            return ask.request_id  # oldest first: the lookup sorts by created_at
        if not _filed_since(req, since):
            continue
        if status == "fulfilled":
            fulfilled.append(ask.request_id)
        elif status == "denied":
            denied.append(ask.request_id)
    approvals = getattr(runtime, "command_approval_store", None)
    if approvals is not None:
        for request_id in fulfilled:
            row = await approvals.get(request_id)
            if row is not None and row.state == "active" and row.uses == 0:
                return request_id
    return denied[0] if denied else ""


async def park_on_command_escalation(
    runtime: Any, *, agent_id: str, work_item_id: str, since: float,
) -> str:
    """After a dispatched run, park ``work_item_id`` on the command escalation it waits for.

    ``since`` is when the run began. Returns the request id the item was parked on, or
    ``""``. Never raises.
    """
    if not isinstance(getattr(runtime, "command_escalations", None), CommandEscalations):
        return ""
    driver = getattr(runtime, "capability_gap_driver", None)
    if driver is None or getattr(runtime, "capability_request_store", None) is None:
        return ""
    if type(work_item_id) is not str or not work_item_id or type(agent_id) is not str or not agent_id:
        return ""
    try:
        request_id = await awaited_command_request(
            runtime, agent_id=agent_id, work_item_id=work_item_id, since=since,
        )
    except Exception:
        logger.warning(
            "AD-1328: could not read the command escalations of work item %s; it is not "
            "parked, so approving one will not resume it", work_item_id, exc_info=True,
        )
        return ""
    if not request_id:
        return ""
    try:
        parked = bool(await driver.block_on_request(
            work_item_id=work_item_id, request_id=request_id,
            reason=COMMAND_ESCALATION_BLOCKED_REASON,
        ))
    except Exception:
        logger.warning(
            "AD-1328: parking work item %s on command request %s raised; the request "
            "stands, but approving it will not resume the item",
            work_item_id, request_id[:12], exc_info=True,
        )
        return ""
    if not parked:
        logger.warning(
            "AD-1328: work item %s could not be parked on command request %s; the request "
            "stands, but approving it will not resume the item", work_item_id, request_id[:12],
        )
        return ""
    logger.info(
        "AD-1328: work item %s parked on command request %s; the Captain's approval resumes "
        "it and a denial cancels it", work_item_id, request_id[:12],
    )
    return request_id
