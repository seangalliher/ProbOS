"""Measure what Copilot CLI delegations cost, from one session's ``events.jsonl``.

The Copilot CLI writes every event of a session (including its subagents') to
``~/.copilot/session-state/<session-id>/events.jsonl``. This script reads that
file and reports, per role (orchestrator, Builder, Diff Reviewer) and per
delegation, only what the log records:

* the harness-reported ``totalTokens``, ``totalToolCalls`` and duration of each
  delegation (``subagent.completed`` / ``subagent.failed``);
* the size of each brief, the number of resumes, and how many tool calls of
  each kind the agent made;
* the characters each tool returned to the agent (what enters its context),
  the characters of its own reasoning and text, and how many results exceeded
  a large-result threshold;
* repeated reads: files viewed more than twice, identical views repeated with
  no edit in between, and reads of ``copilot-instructions.md``;
* test runs (pytest or the canonical gate): how many, how many characters each
  returned, and whether the command was quiet or filtered;
* for the orchestrator: the prompt size at each usage checkpoint, the
  compactions, and the idle gaps longer than the prompt-cache time to live.

Nothing here estimates. A figure the log does not carry is reported as such.
The per-call context of a subagent is NOT in the log; ``totalTokens`` divided
by ``totalToolCalls`` is an average, labelled as one.

Usage::

    python scripts/measure_agent_token_usage.py <events.jsonl> [--json out.json]
        [--group NAME=REGEX ...] [--since ISO8601]

``--group`` assigns delegations whose display name matches REGEX to a work item
NAME, so a report can be compared across batches of issues. ``--since`` measures
only the events at or after an instant (see ``collect`` for how a delegation that
straddles it is treated).
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

BIG_RESULT_CHARS = 40_000
CONTENT_MIN_CHARS = 1_000
INSTRUCTIONS_FILE = "copilot-instructions.md"
CACHE_TTL_SECONDS = 300
TEST_RUN_RE = re.compile(r"pytest|run_test_gate\.py")
ORCHESTRATOR = "orchestrator"
# Read even before a ``--since`` cutoff: they identify a delegation and classify its messages over its whole life.
IDENTITY_EVENTS = ("subagent.started", "subagent.completed", "subagent.failed", "user.message")


@dataclass
class Delegation:
    """One agent's measured activity: a subagent, or the orchestrator."""

    agent_id: str
    name: str = ORCHESTRATOR
    role: str = ORCHESTRATOR
    model: str = ""
    mode: str = ""
    status: str = "running"
    started: str = ""
    ended: str = ""
    partial_window: bool = False
    reported_tool_calls: int | None = None
    reported_tokens: int | None = None
    duration_ms: int | None = None
    brief_chars: int = 0
    idle_messages: int = 0
    steering_messages: int = 0
    assistant_messages: int = 0
    reasoning_chars: int = 0
    text_chars: int = 0
    calls: Counter[str] = field(default_factory=Counter)
    result_chars: Counter[str] = field(default_factory=Counter)
    big_results: list[tuple[str, int]] = field(default_factory=list)
    views: list[tuple[str, str, int]] = field(default_factory=list)
    duplicate_views: int = 0
    duplicate_views_without_edit: int = 0
    edits: int = 0
    edit_chars: int = 0
    test_runs: list[tuple[int, bool, bool]] = field(default_factory=list)
    instruction_reads: list[tuple[bool, int]] = field(default_factory=list)
    diff_chars: int = 0

    @property
    def resumes(self) -> int:
        """Messages that restarted an idle delegation; steering a running one is not a resume."""
        return max(0, self.idle_messages - 1) if self.role != ORCHESTRATOR else 0

    @property
    def tokens_per_call(self) -> float | None:
        if not self.reported_tokens or not self.reported_tool_calls:
            return None
        return self.reported_tokens / self.reported_tool_calls

    @property
    def instruction_deliveries(self) -> list[tuple[bool, int]]:
        """Reads of the instructions file that returned content, not a refusal or a size notice."""
        return [read for read in self.instruction_reads if read[1] >= CONTENT_MIN_CHARS]

    def paths_viewed_more_than_twice(self) -> int:
        counts = Counter(path for path, _range, _chars in self.views)
        return sum(1 for count in counts.values() if count > 2)

    def max_views_of_one_path(self) -> int:
        counts = Counter(path for path, _range, _chars in self.views)
        return max(counts.values(), default=0)


def _parse_time(text: str) -> datetime | None:
    """A timestamp as an aware UTC datetime; ``None`` when it is missing or unreadable."""
    try:
        moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def _iter_events(path: Path) -> Iterator[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                yield json.loads(line)


def _result_chars(data: dict[str, Any]) -> int:
    result = data.get("result")
    if isinstance(result, dict):
        content = result.get("content")
        return len(content) if isinstance(content, str) else 0
    return 0


def _view_range(arguments: dict[str, Any]) -> str:
    view_range = arguments.get("view_range")
    return json.dumps(view_range) if view_range else "whole"


def _command_text(arguments: dict[str, Any]) -> str:
    command = arguments.get("command")
    return command if isinstance(command, str) else ""


def _is_quiet_or_filtered(command: str) -> tuple[bool, bool]:
    quiet = bool(re.search(r"(^|\s)-q(\s|$)|--quiet|-qq", command))
    filtered = bool(re.search(r"Select-Object\s+-(Last|First)|\|\s*(tail|head)\b|Select-String", command))
    return quiet, filtered


def collect(path: Path, *, since: str | None = None) -> tuple[dict[str, Delegation], dict[str, Any]]:
    """Return per-agent measurements and session-level facts from ``path``.

    ``since`` limits what is measured to events at or after that instant, and
    leaves out a delegation with no event in that window. A delegation that
    started earlier but acts inside the window keeps its identity (name, role,
    model) and its message classification (the messages that started,
    restarted or steered it, counted over its whole life, so a resume before
    the cutoff is still a resume); it is marked ``partial_window``, because its
    harness totals, when its turn ended inside the window, cover the whole
    first turn while the observed counts cover the window. A turn that ended
    before the window contributes no harness totals. An event whose time cannot
    be read is not placed in a window; ``facts["unplaced_events"]`` counts them.
    An unreadable start of an orchestrator model request is still remembered, so
    the reply after it is reported as an unreadable pair. A request sent before
    the cutoff whose reply falls inside it is timed from the reply.
    """
    cutoff = _parse_time(since) if since is not None else None
    if since is not None and cutoff is None:
        raise SystemExit(f"--since expects an ISO-8601 timestamp, got {since!r}")
    agents: dict[str, Delegation] = {ORCHESTRATOR: Delegation(ORCHESTRATOR)}
    briefs: dict[str, tuple[int, str]] = {}
    open_calls: dict[str, tuple[str, str, dict[str, Any]]] = {}
    last_edit: dict[tuple[str, str], int] = {}
    last_view: dict[tuple[str, str, str], int] = {}
    sequence = 0
    checkpoints: list[dict[str, Any]] = []
    compactions: list[dict[str, Any]] = []
    model_calls: list[tuple[str, list[str]]] = []
    orchestrator_calls: dict[str, dict[str, str]] = {}
    turn_start: str | None = None  # None: no start event seen; a start event with an unreadable time stays as it is
    active = {ORCHESTRATOR}
    unplaced = 0
    for event in _iter_events(path):
        timestamp = str(event.get("timestamp", ""))
        kind = event.get("type")
        moment = _parse_time(timestamp)
        inside = cutoff is None or (moment is not None and moment >= cutoff)
        if cutoff is not None and moment is None:
            unplaced += 1
        agent_id = str(event.get("agentId") or ORCHESTRATOR)
        if kind == "assistant.turn_start" and agent_id == ORCHESTRATOR and (inside or moment is None):
            turn_start = timestamp  # an unreadable start is kept too, so the reply after it is not timed as if no request had been seen
            continue
        if not inside and kind not in IDENTITY_EVENTS:
            continue
        data = event.get("data") or {}
        agent = agents.setdefault(agent_id, Delegation(agent_id))
        if inside:
            active.add(agent_id)
        if kind == "subagent.started":
            agent.name = str(data.get("agentDisplayName") or agent_id)
            agent.role = str(data.get("agentName") or "")
            agent.model = str(data.get("model") or "")
            agent.mode = str(data.get("executionMode") or "")
            agent.started = timestamp
            agent.partial_window = not inside
            brief = briefs.get(str(data.get("toolCallId")))
            if brief:
                agent.brief_chars = brief[0]
        elif kind in ("subagent.completed", "subagent.failed"):
            agent.status = kind.split(".")[1]
            agent.ended = timestamp
            if inside:  # a turn that ended before the window is not part of what the window spent
                agent.reported_tool_calls = data.get("totalToolCalls")
                agent.reported_tokens = data.get("totalTokens")
                agent.duration_ms = data.get("durationMs")
        elif kind == "user.message":
            if agent_id == ORCHESTRATOR and not inside:
                continue  # only a delegation's messages are classified over its whole life
            if data.get("delivery") == "steering":
                agent.steering_messages += 1
            else:
                agent.idle_messages += 1
        elif not inside:
            continue
        elif kind == "assistant.message":
            if not data.get("apiCallId"):
                continue  # automatic collection of a finished tool's result: no model call, no cache refresh
            agent.assistant_messages += 1
            agent.reasoning_chars += len(data.get("reasoningText") or "")
            agent.text_chars += len(data.get("content") or "")
            if agent_id == ORCHESTRATOR:
                requested = [str(r.get("toolCallId")) for r in data.get("toolRequests") or [] if isinstance(r, dict)]
                model_calls.append((timestamp if turn_start is None else turn_start, requested))
        elif kind == "tool.execution_start":
            sequence += 1
            tool = str(data.get("toolName") or "")
            arguments = data.get("arguments") if isinstance(data.get("arguments"), dict) else {}
            open_calls[str(data.get("toolCallId"))] = (agent_id, tool, arguments)
            agent.calls[tool] += 1
            if agent_id == ORCHESTRATOR:
                orchestrator_calls[str(data.get("toolCallId"))] = {"tool": tool, "command": _command_text(arguments), "started": timestamp}
            if tool == "task" and agent_id == ORCHESTRATOR:
                prompt = arguments.get("prompt")
                briefs[str(data.get("toolCallId"))] = (len(prompt) if isinstance(prompt, str) else 0, str(arguments.get("name") or ""))
            _record_start(agent, tool, arguments, sequence, last_edit, last_view)
        elif kind == "tool.execution_complete":
            call_id = str(data.get("toolCallId"))
            if call_id in orchestrator_calls:
                orchestrator_calls[call_id]["completed"] = timestamp
            started = open_calls.pop(call_id, None)
            if started is None:
                continue
            owner = agents.setdefault(started[0], Delegation(started[0]))
            _record_complete(owner, started[1], started[2], _result_chars(data))
        elif kind == "session.usage_checkpoint":
            checkpoints.append(_checkpoint(timestamp, data))
        elif kind == "session.compaction_complete":
            compactions.append({
                "at": timestamp,
                "before": data.get("preCompactionTokens"),
                "after": data.get("postCompactionTokens"),
                "cache_write": (data.get("compactionTokensUsed") or {}).get("cacheWriteTokens"),
                "cache_read": (data.get("compactionTokensUsed") or {}).get("cacheReadTokens"),
            })
    agents = {key: agent for key, agent in agents.items() if key in active}
    facts = {
        "checkpoints": checkpoints,
        "compactions": compactions,
        "idle_gaps": _idle_gaps(model_calls, orchestrator_calls),
        "unplaced_events": unplaced,
    }
    return agents, facts


def _record_start(
    agent: Delegation, tool: str, arguments: dict[str, Any], sequence: int,
    last_edit: dict[tuple[str, str], int], last_view: dict[tuple[str, str, str], int],
) -> None:
    path = str(arguments.get("path") or "")
    if tool in ("edit", "create") and path:
        agent.edits += 1
        agent.edit_chars += len(str(arguments.get("new_str") or arguments.get("file_text") or ""))
        last_edit[(agent.agent_id, path)] = sequence
    elif tool == "view" and path:
        key = (agent.agent_id, path, _view_range(arguments))
        if key in last_view:
            agent.duplicate_views += 1
            if last_edit.get((agent.agent_id, path), -1) < last_view[key]:
                agent.duplicate_views_without_edit += 1
        last_view[key] = sequence


def _record_complete(agent: Delegation, tool: str, arguments: dict[str, Any], chars: int) -> None:
    agent.result_chars[tool] += chars
    if chars > BIG_RESULT_CHARS:
        agent.big_results.append((tool, chars))
    if tool == "view":
        path = str(arguments.get("path") or "")
        agent.views.append((path, _view_range(arguments), chars))
        if path.replace("\\", "/").endswith(INSTRUCTIONS_FILE):
            agent.instruction_reads.append((_view_range(arguments) == "whole", chars))
    elif tool == "powershell":
        command = _command_text(arguments)
        if INSTRUCTIONS_FILE in command and re.search(r"Get-Content|\bcat\b|\btype\b", command):
            agent.instruction_reads.append(("-TotalCount" not in command and "-Tail" not in command, chars))
        if re.search(r"\bgit\b.*\bdiff\b", command):
            agent.diff_chars += chars
        if TEST_RUN_RE.search(command):
            quiet, filtered = _is_quiet_or_filtered(command)
            agent.test_runs.append((chars, quiet, filtered))


def _checkpoint(timestamp: str, data: dict[str, Any]) -> dict[str, Any]:
    state = (data.get("promptCacheBreakState") or [{}])[0]
    models = list((state.get("models") or {}).values())
    model = models[0] if models else {}
    system = sum(int(segment.get("tokens", 0)) for segment in model.get("system_segments") or [])
    return {
        "at": timestamp,
        "prompt_tokens": model.get("prompt_tokens"),
        "cache_read": model.get("cache_read"),
        "cache_write": model.get("cache_write"),
        "system_tokens": system,
        "tool_tokens": model.get("tool_tokens"),
        "total_nano_aiu": data.get("totalNanoAiu"),
        "premium_requests": data.get("totalPremiumRequests"),
    }


def _gap_cause(call: dict[str, str] | None, gap: float) -> str:
    """Name what the orchestrator was waiting on during a gap longer than the cache time to live."""
    if call is None or "completed" not in call:
        return "idle between turns (woken by a notification or the user)"
    started, completed = _parse_time(call["started"]), _parse_time(call["completed"])
    if started is None or completed is None:
        return "unknown (unreadable timestamp)"
    if (completed - started).total_seconds() < 0.5 * gap:
        return "idle between turns (woken by a notification or the user)"
    if call["tool"] in ("powershell", "read_powershell") and "Start-Sleep" in call["command"]:
        return "watchdog sleep"
    if call["tool"] == "task":
        return "sync delegation"
    if call["tool"] == "read_agent":
        return "read_agent wait"
    return f"long {call['tool']} call"


def _idle_gaps(messages: list[tuple[str, list[str]]], calls: dict[str, dict[str, str]]) -> dict[str, Any]:
    """Gaps between consecutive orchestrator model calls that exceed the cache time to live, by cause.

    A pair of calls whose start times cannot be read is skipped and counted in ``unreadable``.
    """
    by_cause: dict[str, list[float]] = {}
    over = 0
    unreadable = 0
    minutes = 0.0
    for (earlier, requested), (later, _next_requested) in zip(messages, messages[1:]):
        first, second = _parse_time(earlier), _parse_time(later)
        if first is None or second is None:
            unreadable += 1
            continue
        gap = (second - first).total_seconds()
        if gap <= CACHE_TTL_SECONDS:
            continue
        finished = [calls[i] for i in requested if i in calls and "completed" in calls[i]]
        last = max(finished, key=lambda call: call["completed"], default=None)
        cause = _gap_cause(last, gap)
        bucket = by_cause.setdefault(cause, [0.0, 0.0])
        bucket[0] += 1
        bucket[1] += gap / 60
        over += 1
        minutes += gap / 60
    return {"calls": float(len(messages)), "gaps_over_ttl": float(over), "idle_minutes_over_ttl": minutes, "unreadable": float(unreadable), "by_cause": by_cause}


def _percentile_row(values: list[float]) -> str:
    if not values:
        return "n/a"
    ordered = sorted(values)
    return f"min {ordered[0]:,.0f} / median {statistics.median(ordered):,.0f} / max {ordered[-1]:,.0f}"


def _group_of(delegation: Delegation, groups: list[tuple[str, re.Pattern[str]]]) -> str:
    for name, pattern in groups:
        if pattern.search(delegation.name):
            return name
    return "(ungrouped)"


def render(agents: dict[str, Delegation], facts: dict[str, Any], groups: list[tuple[str, re.Pattern[str]]]) -> str:
    """The report, in Markdown."""
    lines: list[str] = ["# Agent token usage (from the session event log)", ""]
    if facts["unplaced_events"]:
        lines += [f"Note: {facts['unplaced_events']} events had no readable time and were left out of the window.", ""]
    subagents = [a for a in agents.values() if a.role != ORCHESTRATOR]
    for role in sorted({a.role for a in subagents}):
        chosen = [a for a in subagents if a.role == role]
        lines += _role_section(role, chosen, groups)
    lines += _orchestrator_section(agents[ORCHESTRATOR], facts)
    return "\n".join(lines) + "\n"


def _role_section(role: str, chosen: list[Delegation], groups: list[tuple[str, re.Pattern[str]]]) -> list[str]:
    lines = [f"## {role}", ""]
    tokens = [a.reported_tokens for a in chosen if a.reported_tokens]
    per_call = [a.tokens_per_call for a in chosen if a.tokens_per_call]
    lines.append(f"- delegations: {len(chosen)} ({sum(1 for a in chosen if a.status == 'failed')} failed); resumed (restarted while idle) at least once: {sum(1 for a in chosen if a.resumes)}; started before the window: {sum(1 for a in chosen if a.partial_window)}")
    lines.append(f"- reported tokens (harness): total {sum(tokens):,}; per delegation {_percentile_row([float(t) for t in tokens])}")
    lines.append(f"- reported tokens per tool call (average, not per-call context): {_percentile_row([float(v) for v in per_call if v])}")
    lines.append(f"- tool calls: reported {sum(a.reported_tool_calls or 0 for a in chosen):,}; observed in the log (all turns, resumes included) {sum(sum(a.calls.values()) for a in chosen):,}; briefs (chars): {_percentile_row([float(a.brief_chars) for a in chosen if a.brief_chars])}")
    lines.append("- note: `subagent.completed` fires once per delegation, so reported tokens and calls cover the first turn only; the tokens of resumed turns are NOT in the log")
    lines.append(f"- own output: reasoning {sum(a.reasoning_chars for a in chosen):,} chars, text {sum(a.text_chars for a in chosen):,} chars")
    lines.append(f"- results returned to the agent: {sum(sum(a.result_chars.values()) for a in chosen):,} chars; larger than {BIG_RESULT_CHARS:,}: {sum(len(a.big_results) for a in chosen)}")
    lines.append(f"- repeated reads: paths viewed more than twice {sum(a.paths_viewed_more_than_twice() for a in chosen)}; identical views repeated {sum(a.duplicate_views for a in chosen)} (with no edit between: {sum(a.duplicate_views_without_edit for a in chosen)}); most views of one path {max((a.max_views_of_one_path() for a in chosen), default=0)}")
    deliveries = [read for a in chosen for read in a.instruction_deliveries]
    attempts = [read for a in chosen for read in a.instruction_reads]
    whole = [read for read in attempts if read[0]]
    lines.append(
        f"- reads of {INSTRUCTIONS_FILE}: {len(attempts)} attempts, {len(deliveries)} delivered content (at least {CONTENT_MIN_CHARS:,} chars), {sum(chars for _w, chars in deliveries):,} chars of content; "
        f"whole-file attempts {len(whole)} (delivered content: {sum(1 for _w, chars in whole if chars >= CONTENT_MIN_CHARS)}); chars returned by all attempts {sum(chars for _w, chars in attempts):,}"
    )
    lines.append(f"- `git diff` output returned: {sum(a.diff_chars for a in chosen):,} chars")
    fresh = [a for a in chosen if not a.resumes]
    resumed = [a for a in chosen if a.resumes]
    lines.append(f"- steering messages sent to a running delegation (not resumes): {sum(a.steering_messages for a in chosen)}")
    for label, group in (("fresh (never resumed)", fresh), ("resumed at least once", resumed)):
        group_calls = sum(a.reported_tool_calls or 0 for a in group)
        group_tokens = sum(a.reported_tokens or 0 for a in group)
        rate = f"{group_tokens / group_calls:,.0f}" if group_calls else "n/a"
        lines.append(f"- {label}: {len(group)} delegations, {group_calls:,} calls, {group_tokens:,} tokens, {rate} tokens per call")
    long_runs = [a for a in chosen if (a.reported_tool_calls or 0) > 200]
    lines.append(f"- delegations over 200 tool calls: {len(long_runs)} ({sum(a.reported_tool_calls or 0 for a in long_runs):,} calls, {sum(a.reported_tokens or 0 for a in long_runs):,} tokens)")
    runs = [run for a in chosen for run in a.test_runs]
    lines.append(f"- test runs: {len(runs)}; returned chars {_percentile_row([float(r[0]) for r in runs])}; quiet flag {sum(1 for r in runs if r[1])}; tail or filter {sum(1 for r in runs if r[2])}")
    lines.append(f"- edits and creates: {sum(a.edits for a in chosen)}; mean size {statistics.mean([a.edit_chars for a in chosen if a.edits] or [0]) / max(1, statistics.mean([a.edits for a in chosen if a.edits] or [1])):,.0f} chars")
    lines.append("")
    lines += ["| delegation | status | calls reported | calls observed | tokens (first turn) | tokens/call | brief | resumes | reasoning chars | results chars | views>2 |", "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for agent in sorted(chosen, key=lambda a: a.started):
        per = agent.tokens_per_call
        per_text = f"{per:,.0f}" if per else "n/a"
        label = f"{agent.name} (partial window)" if agent.partial_window else agent.name
        lines.append(
            f"| {label} | {agent.status} | {agent.reported_tool_calls or 0} | {sum(agent.calls.values())} | {agent.reported_tokens or 0:,} | {per_text} | {agent.brief_chars:,} | {agent.resumes} | {agent.reasoning_chars:,} | {sum(agent.result_chars.values()):,} | {agent.paths_viewed_more_than_twice()} |"
        )
    if groups:
        lines += ["", "| work item | delegations | calls | tokens |", "|---|---:|---:|---:|"]
        totals: dict[str, list[int]] = {}
        for agent in chosen:
            bucket = totals.setdefault(_group_of(agent, groups), [0, 0, 0])
            bucket[0] += 1
            bucket[1] += agent.reported_tool_calls or 0
            bucket[2] += agent.reported_tokens or 0
        lines += [f"| {name} | {b[0]} | {b[1]:,} | {b[2]:,} |" for name, b in sorted(totals.items())]
    lines.append("")
    return lines


def _orchestrator_section(agent: Delegation, facts: dict[str, Any]) -> list[str]:
    lines = [f"## {ORCHESTRATOR}", ""]
    checkpoints = [c for c in facts["checkpoints"] if isinstance(c.get("prompt_tokens"), (int, float))]
    lines.append(f"- tool calls: {sum(agent.calls.values()):,} ({', '.join(f'{k} {v}' for k, v in agent.calls.most_common(6))}); assistant messages {agent.assistant_messages:,}")
    lines.append(f"- results returned to the orchestrator: {sum(agent.result_chars.values()):,} chars; larger than {BIG_RESULT_CHARS:,}: {len(agent.big_results)}; read_agent {agent.result_chars['read_agent']:,} chars over {agent.calls['read_agent']} calls; write_agent calls {agent.calls['write_agent']}")
    lines.append(f"- own output: reasoning {agent.reasoning_chars:,} chars, text {agent.text_chars:,} chars")
    if checkpoints:
        prompts = [float(c["prompt_tokens"]) for c in checkpoints]
        lines.append(f"- prompt tokens at {len(checkpoints)} usage checkpoints: {_percentile_row(prompts)}; fixed part: system {checkpoints[0]['system_tokens']:,} + tool schemas {checkpoints[0]['tool_tokens']:,}")
        cold = [c for c in checkpoints if (c.get("cache_write") or 0) > 0.25 * float(c["prompt_tokens"])]
        lines.append(f"- checkpoints whose prompt was mostly cache-written (cold): {len(cold)} of {len(checkpoints)}")
        last = facts["checkpoints"][-1]
        lines.append(f"- last checkpoint: total nano-AIU {last.get('total_nano_aiu'):,}; premium requests {last.get('premium_requests')}")
    lines.append(f"- compactions: {len(facts['compactions'])}; " + "; ".join(f"{c['before']:,} to {c['after']:,} tokens (cache write {c['cache_write']:,}, read {c['cache_read']:,})" for c in facts["compactions"]))
    gaps = facts["idle_gaps"]
    lines.append(f"- orchestrator model calls {int(gaps['calls']):,} (assistant messages carrying an API call id; automatic result collection is excluded); gaps between call starts over the {CACHE_TTL_SECONDS} s cache time to live: {int(gaps['gaps_over_ttl'])} ({gaps['idle_minutes_over_ttl']:,.0f} idle minutes); these are gaps in requests, not measured cache misses")
    for cause, (count, minutes) in sorted(gaps["by_cause"].items()):
        lines.append(f"  - {cause}: {int(count)} ({minutes:,.0f} minutes)")
    if gaps["unreadable"]:
        lines.append(f"  - pairs of calls skipped because a start time was unreadable: {int(gaps['unreadable'])}")
    runs = agent.test_runs
    lines.append(f"- test runs by the orchestrator: {len(runs)}; returned chars {_percentile_row([float(r[0]) for r in runs])}")
    lines.append(
        f"- reads of {INSTRUCTIONS_FILE}: {len(agent.instruction_reads)} attempts, {len(agent.instruction_deliveries)} delivered content; "
        f"whole-file attempts {sum(1 for whole, _chars in agent.instruction_reads if whole)} (delivered content: {sum(1 for whole, chars in agent.instruction_reads if whole and chars >= CONTENT_MIN_CHARS)}); "
        f"paths viewed more than twice {agent.paths_viewed_more_than_twice()}; most views of one path {agent.max_views_of_one_path()}"
    )
    lines.append("")
    return lines


def _parse_groups(raw: list[str]) -> list[tuple[str, re.Pattern[str]]]:
    groups: list[tuple[str, re.Pattern[str]]] = []
    for item in raw:
        name, _, pattern = item.partition("=")
        if not name or not pattern:
            raise SystemExit(f"--group expects NAME=REGEX, got {item!r}")
        groups.append((name, re.compile(pattern)))
    return groups


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("events", type=Path, help="a session's events.jsonl")
    parser.add_argument("--json", type=Path, help="also write the raw measurements here")
    parser.add_argument("--group", action="append", default=[], help="NAME=REGEX over delegation display names")
    parser.add_argument("--since", help="measure only events at or after this ISO-8601 timestamp (one without an offset is read as UTC; an event whose time cannot be read is left out and counted); a delegation that started earlier but acts inside the window is kept and marked partial, and one with no event inside it is left out")
    args = parser.parse_args(argv)
    agents, facts = collect(args.events, since=args.since)
    sys.stdout.write(render(agents, facts, _parse_groups(args.group)))
    if args.json:
        payload = {
            "agents": {key: {**vars(value), "calls": dict(value.calls), "result_chars": dict(value.result_chars)} for key, value in agents.items()},
            "facts": facts,
        }
        args.json.write_text(json.dumps(payload, indent=1, default=str), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
