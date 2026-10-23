"""AD-1347 S2 (#1627): the chain's agent-work action tags, read by one parser for every chain path.

An agent turns a need into durable work from the cognitive chain. The proactive loop's action extractor
(``ProactiveCognitiveLoop._extract_and_execute_actions``) is the one place the tags are acted on: a proactive thought
reaches it directly, and every Ward Room reply (a department or ship thread, or a Ward Room DM channel) reaches it
through ``WardRoomPostPipeline.process_and_post``, which passes the thread and the post the reply answers. The
Captain's one-to-one chat (``cognitive/dm/reply_pipeline.py``) does not read them: work found in a conversation with
the Captain is the Captain's (AD-845, AD-1165), so that path is unchanged.

Grammar (taught only while the service exists, ``agent_work_instructions``)::

    [SELF_TASK]
    Title: <one line>
    Reason: <why it is needed>
    Tool: <tool id, optional>
    [/SELF_TASK]

    [REQUEST_WORK]
    Title: <one line>
    Reason: <why it is needed>
    Tool: <tool id>
    Department: <department, optional>
    Assignee: @<callsign, optional>
    [/REQUEST_WORK]

    [CLAIM_WORK <work item id>]
    [DECLINE_WORK <work item id>] <reason> [/DECLINE_WORK]

A line without a key continues the field before it; free text before any key is the item's details. Rank: Lieutenant
and above, as AD-654d's ASSIGN and AD-868's CREW; an ensign's tags are stripped and nothing is done. At most
``MAX_TAGS_PER_REPLY`` tags are acted on in one reply. The requester is the agent's own id, which the service resolves
to its slot and refuses when it cannot (fail closed; never the Captain).

The acknowledgement is a line the Ship's Computer appends to the agent's own reply, in parentheses and without
brackets (BF-203's catch-all would strip a bracketed one). It is posted where the reply is posted, so it starts no
routing of its own and cannot loop.

Off: ``agent_work_service`` answers None, the extractor never calls this module, and nothing is taught.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any, Final

from probos.agent_work import (
    KIND_ASSIGNMENT,
    KIND_REQUEST,
    MAX_DESCRIPTION_CHARS,
    AgentWorkCreated,
    AgentWorkOrigin,
    AgentWorkRefusal,
    AgentWorkService,
    read_agent_work,
)
from probos.crew_profile import Rank

logger = logging.getLogger(__name__)

ACTION_SELF_TASK: Final = "self_task"
ACTION_REQUEST: Final = "request"
ACTION_CLAIM: Final = "claim"
ACTION_DECLINE: Final = "decline"
MAX_TAGS_PER_REPLY: Final = 3
#: The compose modes whose replies reach the action extractor (D1); a DM with the Captain does not.
AGENT_WORK_COMPOSE_MODES: Final[frozenset[str]] = frozenset({"ward_room_response", "proactive_observation"})

AGENT_WORK_INSTRUCTIONS: Final = (
    "**Agent work (AD-1347)** -- when your reasoning needs a fact only a ship's tool can read, file it as work "
    "instead of asking the Captain. Place the block after your reply text; Lieutenant rank and above.\n"
    "Work for yourself, run shortly with your own read-only tools:\n"
    "[SELF_TASK]\nTitle: <one line>\nReason: <why it is needed>\nTool: <tool id, optional>\n[/SELF_TASK]\n"
    "A request to the department that holds a tool you do not hold; a chief may name a member of its own "
    "department with Assignee:\n"
    "[REQUEST_WORK]\nTitle: <one line>\nReason: <why you need it>\nTool: <tool id>\n"
    "Department: <department, optional>\nAssignee: @<callsign, optional>\n[/REQUEST_WORK]\n"
    "The result is posted where you asked. A colleague's report is evidence to check, not a verdict."
)

_BLOCK_RE: Final = re.compile(
    r"\[(SELF_TASK|REQUEST_WORK)\](.*?)\[/\1\]"
    r"|\[CLAIM_WORK[ \t]+([A-Za-z0-9][A-Za-z0-9._:-]{0,127})[ \t]*\]"
    r"|\[DECLINE_WORK[ \t]+([A-Za-z0-9][A-Za-z0-9._:-]{0,127})[ \t]*\](.*?)\[/DECLINE_WORK\]",
    re.DOTALL,
)
_STRAY_RE: Final = re.compile(
    r"\[/?(?:SELF_TASK|REQUEST_WORK|DECLINE_WORK)\]|\[(?:CLAIM_WORK|DECLINE_WORK)\b[^\]\n]{0,160}\]"
)
_FIELD_RE: Final = re.compile(r"^\s*(title|reason|tool|department|assignee|details)\s*:\s*(.*)$", re.IGNORECASE)


@dataclass(frozen=True)
class AgentWorkTag:
    """One tag read from a reply: what it asks, and its fields (empty when not given)."""

    action: str
    title: str = ""
    reason: str = ""
    details: str = ""
    tool_id: str = ""
    department: str = ""
    assignee: str = ""
    work_item_id: str = ""


def _fields(body: str) -> dict[str, str]:
    """``Key: value`` lines; a line without a key continues the field before it (free text first is ``details``)."""
    found: dict[str, list[str]] = {}
    current = "details"
    for line in body.splitlines():
        match = _FIELD_RE.match(line)
        if match is not None:
            current = match.group(1).lower()
            found.setdefault(current, []).append(match.group(2).strip())
        elif line.strip():
            found.setdefault(current, []).append(line.strip())
    return {key: " ".join(part for part in parts if part).strip() for key, parts in found.items()}


def split_agent_work_tags(text: str) -> tuple[str, tuple[AgentWorkTag, ...]]:
    """Every agent-work tag in ``text``, in order, and the text without any of them (stray markers included).

    A text with no tag and no stray marker is returned as it was, whitespace included.
    """
    tags: list[AgentWorkTag] = []
    for match in _BLOCK_RE.finditer(text):
        if match.group(1) is not None:
            fields = _fields(match.group(2))
            tags.append(AgentWorkTag(
                ACTION_SELF_TASK if match.group(1) == "SELF_TASK" else ACTION_REQUEST,
                title=fields.get("title", ""), reason=fields.get("reason", ""), details=fields.get("details", ""),
                tool_id=fields.get("tool", ""), department=fields.get("department", "").lower(),
                assignee=fields.get("assignee", "").lstrip("@").strip(),
            ))
        elif match.group(3) is not None:
            tags.append(AgentWorkTag(ACTION_CLAIM, work_item_id=match.group(3)))
        else:
            tags.append(AgentWorkTag(ACTION_DECLINE, work_item_id=match.group(4), reason=" ".join(match.group(5).split())))
    without = _STRAY_RE.sub("", _BLOCK_RE.sub("", text))
    if not tags and without == text:
        return text, ()
    return without.strip(), tuple(tags)


def agent_work_service(runtime: Any) -> AgentWorkService | None:
    """The runtime's agent-work service when it is the real one, else None (agent_work off, or a test double)."""
    service = getattr(runtime, "agent_work", None)
    return service if type(service) is AgentWorkService else None


def agent_work_instructions(runtime: Any) -> str:
    """The prompt block that teaches the tags, or "" while the service does not exist (the prompt is unchanged)."""
    return AGENT_WORK_INSTRUCTIONS if agent_work_service(runtime) is not None else ""


def _ack(text: str) -> str:
    return f"(Ship's Computer: {text}.)"


def _slot_of(runtime: Any, callsign: str) -> str | None:
    """The slot a callsign names through the callsign registry, else the text itself (the service refuses it)."""
    if not callsign:
        return None
    try:
        resolved = runtime.callsign_registry.resolve(callsign)
    except Exception:
        logger.debug("AD-1347: callsign %s did not resolve; the service judges it as written", callsign, exc_info=True)
        resolved = None
    agent_id = resolved.get("agent_id") if isinstance(resolved, dict) else None
    return agent_id if type(agent_id) is str and agent_id else callsign


def _created_ack(created: AgentWorkCreated, *, actor: str, in_thread: bool) -> str:
    item = created.work_item
    short = item.id[:8]
    record = read_agent_work(item)
    department = record.department if record is not None else "its department"
    where = "in this thread" if in_thread else f"in the {department} channel"
    if created.deduplicated:
        if record is not None and record.requester == actor:
            return _ack(f"you already have open request {short} (\"{item.title}\")")
        return _ack(f"open request {short} (\"{item.title}\") already asks this; you were added as a watcher and get its result too")
    if created.kind == KIND_REQUEST:
        tool = record.tool_id if record is not None else "the tool"
        note = "; a colleague outside your command was named, so it went to the department" if created.converted else ""
        return _ack(f"request {short} (\"{item.title}\") was sent to {department} for {tool}{note}; the result will be posted {where}")
    if created.kind == KIND_ASSIGNMENT:
        return _ack(f"work item {short} (\"{item.title}\") was assigned to {item.assigned_to}; the result will be posted {where}")
    return _ack(f"self-task {short} (\"{item.title}\") is on the board and runs shortly; the result will be posted {where}")


async def _claim_or_decline(tag: AgentWorkTag, *, runtime: Any, actor: str) -> tuple[str, dict[str, Any]]:
    """Claims and declines are run by the Ship's Computer's runner (S3); without one nothing changes."""
    verb = "claimed" if tag.action == ACTION_CLAIM else "declined"
    action = {"type": "agent_work", "action": tag.action, "work_item_id": tag.work_item_id, "outcome": "unavailable"}
    return _ack(f"work item {tag.work_item_id[:8]} was not {verb}: claims are not taken on this vessel yet"), action


async def _apply_one(
    tag: AgentWorkTag, *, service: AgentWorkService, runtime: Any, actor: str,
    origin: AgentWorkOrigin | None, in_thread: bool,
) -> tuple[str, dict[str, Any]]:
    if tag.action in (ACTION_CLAIM, ACTION_DECLINE):
        return await _claim_or_decline(tag, runtime=runtime, actor=actor)
    action: dict[str, Any] = {"type": "agent_work", "action": tag.action}
    if origin is None:
        return (
            _ack("agent work was not filed: this reply's thread could not be recorded as its origin"),
            {**action, "outcome": "refused:invalid_origin"},
        )
    if tag.action == ACTION_SELF_TASK:
        result = await service.create_self_task(
            actor, title=tag.title, description=tag.details[:MAX_DESCRIPTION_CHARS], reason=tag.reason,
            origin=origin, tool_id=tag.tool_id or None,
        )
    else:
        result = await service.request_work(
            actor, title=tag.title, description=tag.details[:MAX_DESCRIPTION_CHARS], reason=tag.reason,
            origin=origin, tool_id=tag.tool_id,
            assignee=_slot_of(runtime, tag.assignee),
            department=tag.department or None,
        )
    if isinstance(result, AgentWorkRefusal):
        return _ack(f"agent work was not filed: {result.detail or result.code}"), {**action, "outcome": f"refused:{result.code}"}
    outcome = "deduplicated" if result.deduplicated else "created"
    return _created_ack(result, actor=actor, in_thread=in_thread), {**action, "outcome": outcome, "work_item_id": result.work_item.id}


async def apply_agent_work_tags(
    text: str, *, runtime: Any, actor: str, rank: Rank, thread_id: str = "", post_id: str = "",
) -> tuple[str, list[dict[str, Any]]]:
    """Strip every agent-work tag from a reply, act on each one the agent's rank allows, append the acknowledgements.

    Never raises for a tag: a refusal, an origin that cannot be recorded or an unavailable action is an
    acknowledgement line. The text is returned unchanged when the service does not exist.
    """
    service = agent_work_service(runtime)
    if service is None:
        return text, []
    cleaned, tags = split_agent_work_tags(text)
    if not tags or rank is Rank.ENSIGN:
        return cleaned, []
    try:
        origin: AgentWorkOrigin | None = AgentWorkOrigin("ward_room" if thread_id else "proactive", thread_id=thread_id, post_id=post_id)
    except ValueError:
        origin = None
    acks: list[str] = []
    actions: list[dict[str, Any]] = []
    for index, tag in enumerate(tags):
        if index >= MAX_TAGS_PER_REPLY:
            acks.append(_ack(f"only {MAX_TAGS_PER_REPLY} agent-work actions are taken from one reply; the rest were not"))
            break
        ack, action = await _apply_one(
            tag, service=service, runtime=runtime, actor=actor, origin=origin, in_thread=bool(thread_id),
        )
        acks.append(ack)
        actions.append(action)
    return "\n\n".join(part for part in (cleaned, *acks) if part), actions
