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

Reading (A1, review round 1; A2, round 2; A2b; A2c; A2d, round 3): names are read in any letter case and every marker
is removed, closers included. A marker in an inert region is an example or a quotation: removed alone, never acted on,
and no part of any block. The inert regions (``_inert_spans``, after CommonMark 0.31.2 with the differences contract
section 9 names): a code fence, from a line opening a run of three or more backticks or tildes to a line holding only a
run of the same character at least as long (an unclosed one runs to the end), with indentation read both at the top
level and as in a list item, at the item's content column (``_item_columns``); an indented code block, and the rest of
a list item's first line after five or more columns of padding; a line whose first character other than whitespace,
after any list item markers, is ``>`` (A2f); an inline code span within one line. A line ends at LF, CRLF or CR. A
block holds every block opened inside it and is closed only by its own closer once those are closed; a block that
holds any other marker is removed whole and not acted on. One pass reads the lines and the markers, each marker at
most 160 characters to its bracket, so the work is linear in the reply. A fault on one tag is acknowledged, never
retried, and the rest of the reply goes on.

Off: ``runtime.agent_work`` is None, so the extractor neither imports nor calls this module, and nothing is taught.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
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
from probos.agent_work_runner import AgentWorkRunner
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
    "The result is posted where you asked. A colleague's report is evidence to check, not a verdict.\n"
    "When the Ship's Computer asks your department to take a request, reply [CLAIM_WORK <work item id>] to take it, "
    "or [DECLINE_WORK <work item id>] <your reason> [/DECLINE_WORK] when it is not yours to do. The first claim wins."
)

#: A1 (F7, F11): every agent-work marker, opener or closer, in any letter case: ``[NAME]``, ``[/NAME]`` or
#: ``[NAME <attribute>]``, on one line (A2: no LF or CR inside) with at most 160 characters before its bracket, so one
#: scan reads each character a bounded number of times.
_MARKER_RE: Final = re.compile(
    r"\[(/?)(SELF_TASK|REQUEST_WORK|CLAIM_WORK|DECLINE_WORK)\b([^\]\r\n]{0,160})\]", re.IGNORECASE,
)
_ITEM_ID_RE: Final = re.compile(r"[ \t]+([A-Za-z0-9][A-Za-z0-9._:-]{0,127})[ \t]*")
#: A2 (F16): a line and its ending, which is LF, CRLF or CR (CommonMark 0.31.2, 2.1); ``str.splitlines`` would also
#: end a line at U+2028 and other separators that a Markdown renderer shows as text.
_LINE_RE: Final = re.compile(r"[^\r\n]*(?:\r\n|\r|\n)|[^\r\n]+")
#: A2 (F16): a code fence line (CommonMark 0.31.2, 4.5): blanks, a run of three or more backticks or tildes, and the
#: rest of the line. A2b: its column decides which reading it opens or closes (``_inert_spans``).
_FENCE_RE: Final = re.compile(r"[ \t]*(`{3,}|~{3,})(.*)")
#: A2b: the list item markers that start a line (CommonMark 0.31.2, 5.2), so a fence after a marker is read. A2c: a
#: marker may end the line (an empty item), so that item's content column is tracked too. A2d: the match ends with
#: the last marker and all of its padding, which ``_item_columns`` measures.
_LIST_ITEM_RE: Final = re.compile(r"(?:[ \t]*(?:[-+*]|[0-9]{1,9}[.)])(?:[ \t]+|$))+")
#: A2b: a line a paragraph does not continue past, so a line indented four columns after it is indented code
#: (CommonMark 0.31.2, 4.1 to 4.4): an ATX heading, or one character of ``-*_=`` repeated, which also counts a setext
#: underline and a bare list marker (this errs toward inert).
_PARAGRAPH_END_RE: Final = re.compile(r" {0,3}(?:#{1,6}(?:[ \t].*)?|([-*_=])(?:[ \t]*\1)*[ \t]*)")
#: A2 (F16): a run of backticks, which opens or closes an inline code span (CommonMark 0.31.2, 6.1).
_TICKS_RE: Final = re.compile(r"`+")
_BACKTICK: Final = "\x60"  # a backtick, spelled so the mutation table can quote the lines that use it
_BLOCK_NAMES: Final[frozenset[str]] = frozenset({"SELF_TASK", "REQUEST_WORK"})
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


@dataclass
class _OpenBlock:
    """A block opener the scan has not closed yet (A1). A2 (F17): ``open_names`` holds it and every block opened inside
    it, innermost last; only a closer of the innermost one closes a level, and the block ends when the last level does."""

    name: str
    item_id: str
    start: int
    body_start: int
    open_names: list[str]
    actionable: bool = True
    inner: list[tuple[int, int]] = field(default_factory=list)


def _code_spans(content: str, offset: int) -> list[tuple[int, int]]:
    """A2 (F16): the inline code spans of one line, as offsets into the text: from a run of backticks to the next run of
    exactly as many on the line (CommonMark 0.31.2, 6.1); a run with no such partner is text. Linear: one backward pass
    finds each run's partner."""
    runs = [(tick.start(), tick.end()) for tick in _TICKS_RE.finditer(content)]
    partner: list[int | None] = [None] * len(runs)
    latest: dict[int, int] = {}
    for index in range(len(runs) - 1, -1, -1):
        size = runs[index][1] - runs[index][0]
        partner[index] = latest.get(size)
        latest[size] = index
    spans: list[tuple[int, int]] = []
    index = 0
    while index < len(runs):
        close = partner[index]
        if close is None:
            index += 1
            continue
        spans.append((offset + runs[index][1], offset + runs[close][0]))
        index = close + 1
    return spans


def _columns(prefix: str) -> int:
    """A2b: the columns ``prefix`` spans from the start of its line; a tab advances to the next multiple of four
    (CommonMark 0.31.2, 2.2)."""
    width = 0
    for char in prefix:
        width += 4 - width % 4 if char == "\t" else 1
    return width


def _item_columns(head: str, empty: bool) -> tuple[int, bool]:
    """A2d (F22, F23; CommonMark 0.31.2, 5.2): the content column of the list item that the last marker in ``head``
    starts, and whether the item starts with indented code. ``head`` ends with that marker and its padding. The column
    is the marker's end plus the padding, for one to four columns of it; it is the marker's end plus one when the item
    starts blank (``empty``: nothing follows the marker on its line) or when five or more columns of padding follow
    (``wide``), and then the rest of the line is indented code."""
    end = _columns(head.rstrip(" \t"))
    padding = _columns(head) - end
    wide = not empty and padding >= 5
    return (end + 1 if empty or wide else end + padding), wide


def _closes(fence: tuple[str, int], run: re.Match[str] | None) -> bool:
    """A2b: whether a fence line closes a fence of this character and run length (CommonMark 0.31.2, 4.5): only a
    run of the same character at least as long, with nothing after it but blanks. Both readings use it."""
    return (
        run is not None and run.group(1)[0] == fence[0]
        and len(run.group(1)) >= fence[1]
        and not run.group(2).strip(" \t")
    )


def _inert_spans(text: str) -> list[tuple[int, int]]:
    """A2 (F16), A2b, A2c: the (start, end) offsets, in order and apart, where a marker is an example or a quotation.

    One pass over the lines, read two ways at once: the scanner does not parse list items, so it cannot tell which
    reading holds, and a line is inert when either makes it so. In both, a code fence opens on a run of three or more
    backticks or tildes (after backticks, no other backtick on the line), also after list item markers, and closes on
    a line without a marker holding only a run of the same character at least as long; an unclosed one runs to the end
    of the text. The top-level reading is CommonMark's: a fence line starts within three columns, and a line indented
    four or more columns that does not continue a paragraph is indented code. The list reading opens a fence at any
    column (a fence in a list item is indented by the item). A2c (CommonMark 0.31.2, 5.2): the list reading tracks the
    last list item's content column, which a non-blank line left of it ends. A2d (F22, F23): the column is the last
    marker's (``_item_columns``); a marker line with five or more columns of padding is indented code, and no fence
    opens on it; an item with no content yet also ends at a blank line. Each fence has a floor, and a non-blank
    line left of it ends the fence before the line is read, so the line may open a new one. A list fence in a tracked
    item is floored at the item's column and closes within three columns of it; outside one it is floored at 0 within
    three columns, else three columns left of it and never below 2, and closes within three columns of itself. The
    top reading floors only a fence on a marker line. A line whose first character other than whitespace (A2f, F27:
    any), after any list item markers, is ``>`` is a quote and inert, and on any other line outside both readings'
    fences each inline code span is inert.
    """
    spans: list[tuple[int, int]] = []
    top_fence: tuple[tuple[str, int], int] | None = None
    list_fence: tuple[tuple[str, int], int, int] | None = None
    item_column: int | None = None
    item_empty: bool = False
    paragraph = False
    for line in _LINE_RE.finditer(text):
        start, end = line.span()
        content = line.group().rstrip("\r\n")
        item = _LIST_ITEM_RE.match(content)
        head = item.group() if item is not None else ""
        rest = content[len(head):]
        empty = bool(head) and not rest
        content_column, wide = _item_columns(head, empty) if head else (0, False)
        run = None if wide else _FENCE_RE.fullmatch(rest)  # A2d (F22): a wide line's rest is indented code
        closer = None if head else run
        blank = not content.strip(" \t")
        indent = _columns(content[: len(content) - len(content.lstrip(" \t"))])
        column = _columns(content[: len(head) + run.start(1)]) if run is not None else 0
        opened: tuple[str, int] | None = None
        if run is not None and not (run.group(1)[0] == _BACKTICK and _BACKTICK in run.group(2)):
            opened = (run.group(1)[0], len(run.group(1)))
        if list_fence is not None and not blank and indent < list_fence[2]:
            list_fence = None  # A2c: a line left of its item's content column ends the item
        if top_fence is not None and not blank and indent < top_fence[1]:
            top_fence = None  # A2c: likewise for a fence opened on a marker line
        if head and list_fence is None:
            item_column, item_empty = content_column, empty
        # A2d (F23): an item ends at a non-blank line left of its column, and an empty one at its first blank line
        elif item_column is not None and (item_empty if blank else indent < item_column):
            item_column = None
        elif not blank:
            item_empty = False  # A2d (F23): the item has content, so a blank line no longer ends it
        inert = top_fence is not None or list_fence is not None
        if list_fence is None and opened is not None:
            base = column if item_column is None else item_column
            floor = item_column if item_column is not None else (0 if column <= 3 else max(2, column - 3))
            list_fence, inert = (opened, base + 3, floor), True
        elif list_fence is not None and _closes(list_fence[0], closer) and column <= list_fence[1]:
            list_fence = None  # its closing fence
        if top_fence is not None:
            if _closes(top_fence[0], closer) and indent <= 3:
                top_fence = None  # its closing fence
        elif blank:
            paragraph = False  # a blank line ends a paragraph
        elif wide:
            paragraph, inert = False, True  # A2d (F22): the item starts with an indented code block
        elif opened is not None and column <= 3:
            top_fence, paragraph, inert = (opened, _columns(head)), False, True
        elif rest.lstrip().startswith(">"):  # A2f (F27): any whitespace; it can only make a line inert
            paragraph, inert = False, True
        elif indent >= 4:
            inert = inert or not paragraph
        else:
            paragraph = _PARAGRAPH_END_RE.fullmatch(content) is None
        if inert:
            spans.append((start, end))
        else:
            spans.extend(_code_spans(content, start))
    return spans


def _block_tag(block: _OpenBlock, body: str) -> AgentWorkTag:
    """The tag a closed, actionable block asks for."""
    if block.name == "DECLINE_WORK":
        return AgentWorkTag(ACTION_DECLINE, work_item_id=block.item_id, reason=" ".join(body.split()))
    fields = _fields(body)
    return AgentWorkTag(
        ACTION_SELF_TASK if block.name == "SELF_TASK" else ACTION_REQUEST,
        title=fields.get("title", ""), reason=fields.get("reason", ""), details=fields.get("details", ""),
        tool_id=fields.get("tool", ""), department=fields.get("department", "").lower(),
        assignee=fields.get("assignee", "").lstrip("@").strip(),
    )


def split_agent_work_tags(text: str) -> tuple[str, tuple[AgentWorkTag, ...]]:
    """Every agent-work tag in ``text``, in order, and the text without any marker.

    One pass over the markers (A1: F6, F7, F11; A2: F16, F17). Names are read in any letter case. A marker in an inert
    region (``_inert_spans``: a fence, indented code, a quote line, a code span) is removed alone, never acted on, and is
    no part of any block. A block opened outside one holds every block opened inside it and is closed only by its own
    closer once each of those is closed; a block that holds any other marker is removed whole and not acted on. An
    unclosed block's opener and the markers after it, and every stray marker, are removed alone. A text with no marker
    is returned as it was, whitespace included.
    """
    tags: list[AgentWorkTag] = []
    cuts: list[tuple[int, int]] = []
    spans = _inert_spans(text)
    span = 0
    block: _OpenBlock | None = None
    for match in _MARKER_RE.finditer(text):
        while span < len(spans) and spans[span][1] <= match.start():
            span += 1
        inert = span < len(spans) and spans[span][0] <= match.start()
        closer, name, attribute = match.group(1) == "/", match.group(2).upper(), match.group(3)
        item_id = _ITEM_ID_RE.fullmatch(attribute) if not closer and name in ("CLAIM_WORK", "DECLINE_WORK") else None
        opener = (not closer and name in _BLOCK_NAMES and not attribute.strip()) or (item_id is not None and name == "DECLINE_WORK")
        if block is not None:
            closes = closer and not inert and not attribute.strip()
            if closes and name == block.open_names[-1]:
                block.open_names.pop()
                if not block.open_names:
                    if block.actionable:
                        tags.append(_block_tag(block, text[block.body_start:match.start()]))
                    cuts.append((block.start, match.end()))
                    block = None
                    continue
            elif not inert and opener:
                block.open_names.append(name)
            block.actionable = False
            block.inner.append((match.start(), match.end()))
            continue
        if opener and not inert:
            block = _OpenBlock(name, item_id.group(1) if item_id is not None else "", match.start(), match.end(), [name])
            continue
        if item_id is not None and not inert:
            tags.append(AgentWorkTag(ACTION_CLAIM, work_item_id=item_id.group(1)))
        cuts.append((match.start(), match.end()))
    if block is not None:
        cuts.extend([(block.start, block.body_start), *block.inner])
    if not cuts:
        return text, ()
    kept: list[str] = []
    position = 0
    for start, end in cuts:
        kept.append(text[position:start])
        position = end
    kept.append(text[position:])
    return "".join(kept).strip(), tuple(tags)


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
    runner = getattr(runtime, "agent_work_runner", None)
    verb = "claimed" if tag.action == ACTION_CLAIM else "declined"
    if type(runner) is not AgentWorkRunner:
        action = {"type": "agent_work", "action": tag.action, "work_item_id": tag.work_item_id, "outcome": "unavailable"}
        return _ack(f"work item {tag.work_item_id[:8]} was not {verb}: claims are not taken on this vessel yet"), action
    if tag.action == ACTION_CLAIM:
        outcome, said = await runner.claim(actor, tag.work_item_id)
    else:
        outcome, said = await runner.decline(actor, tag.work_item_id, tag.reason)
    return _ack(said), {"type": "agent_work", "action": tag.action, "work_item_id": tag.work_item_id, "outcome": outcome}


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


async def _apply_guarded(
    tag: AgentWorkTag, *, service: AgentWorkService, runtime: Any, actor: str,
    origin: AgentWorkOrigin | None, in_thread: bool,
) -> tuple[str, dict[str, Any]]:
    """One tag, isolated (A1, F10): a fault is logged and acknowledged, never retried (whether the write landed is
    unknown, so the agent is told to check the board), and the reply and its other tags go on."""
    try:
        return await _apply_one(tag, service=service, runtime=runtime, actor=actor, origin=origin, in_thread=in_thread)
    except Exception:
        logger.warning("AD-1347: an agent-work %s tag from %s could not be completed; the reply goes on", tag.action, actor, exc_info=True)
        return (
            _ack(f"the {tag.action.replace('_', '-')} could not be confirmed: check the board before asking again"),
            {"type": "agent_work", "action": tag.action, "outcome": "error"},
        )


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
        ack, action = await _apply_guarded(tag, service=service, runtime=runtime, actor=actor, origin=origin, in_thread=bool(thread_id))
        acks.append(ack)
        actions.append(action)
    return "\n\n".join(part for part in (cleaned, *acks) if part), actions
