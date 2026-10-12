from __future__ import annotations

import importlib.util
import json
import sys
from collections import Counter
from pathlib import Path
from types import ModuleType

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "measure_agent_token_usage.py"


@pytest.fixture(scope="module")
def measure() -> ModuleType:
    spec = importlib.util.spec_from_file_location("measure_agent_token_usage", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _t(seconds: int) -> str:
    minutes, sec = divmod(seconds, 60)
    return f"2026-10-11T10:{minutes:02d}:{sec:02d}.000Z"


def _event(kind: str, seconds: int, data: dict, agent: str | None = None) -> dict:
    event = {"type": kind, "data": data, "timestamp": _t(seconds)}
    if agent:
        event["agentId"] = agent
    return event


def _call(call_id: str, tool: str, args: dict, start: int, end: int, chars: int, agent: str | None = None) -> list[dict]:
    return [
        _event("tool.execution_start", start, {"toolCallId": call_id, "toolName": tool, "arguments": args}, agent),
        _event("tool.execution_complete", end, {"toolCallId": call_id, "result": {"content": "x" * chars}}, agent),
    ]


def _model_call(seconds: int, api_id: str, requested: list[str] | None = None, started: int | None = None) -> list[dict]:
    """An orchestrator model call: the turn starts a little before its message is received."""
    start = seconds - 1 if started is None else started
    return [
        _event("assistant.turn_start", start, {"turnId": api_id}),
        _event("assistant.message", seconds, {"apiCallId": api_id, "content": "text", "toolRequests": [{"toolCallId": c} for c in requested or []]}),
    ]


def _builder_events() -> list[dict]:
    brief = {"prompt": "p" * 700, "name": "builder-x-repair-1"}
    events: list[dict] = []
    events += _call("task-1", "task", brief, 0, 1, 10)
    events.append(_event("subagent.started", 1, {"toolCallId": "task-1", "agentName": "Builder", "agentDisplayName": "builder-x-repair-1", "model": "m1", "executionMode": "background"}, "b1"))
    events.append(_event("user.message", 1, {"content": "brief", "delivery": "idle"}, "b1"))
    events.append(_event("assistant.message", 2, {"apiCallId": "b-1", "content": "ok", "reasoningText": "r" * 40, "toolRequests": []}, "b1"))
    events += _call("v1", "view", {"path": "src/a.py"}, 3, 3, 200, "b1")
    events += _call("v2", "view", {"path": "src/a.py"}, 4, 4, 200, "b1")
    events += _call("v3", "view", {"path": "src/a.py", "view_range": [1, 10]}, 5, 5, 50, "b1")
    events.append(_event("user.message", 5, {"content": "steer", "delivery": "steering"}, "b1"))
    events += _call("i1", "view", {"path": ".github/copilot-instructions.md", "view_range": [1, 40]}, 6, 6, 2_000, "b1")
    events += _call("i2", "view", {"path": ".github/copilot-instructions.md"}, 6, 6, 148, "b1")
    events += _call("e1", "edit", {"path": "src/a.py", "old_str": "a", "new_str": "bb"}, 7, 7, 5, "b1")
    events += _call("v5", "view", {"path": "src/a.py"}, 8, 8, 200, "b1")
    events += _call("t1", "powershell", {"command": "pytest tests/x.py -q | Select-Object -Last 5"}, 9, 9, 120, "b1")
    events += _call("big", "powershell", {"command": "git diff HEAD"}, 10, 10, 41_000, "b1")
    events.append(_event("subagent.completed", 12, {"totalToolCalls": 9, "totalTokens": 900_000, "durationMs": 11_000}, "b1"))
    events.append(_event("user.message", 13, {"content": "follow-up", "delivery": "idle"}, "b1"))
    return events


def _orchestrator_events() -> list[dict]:
    events: list[dict] = []
    # A sleep that outlasts the cache; the collecting message at 1,000 s carries no API call id and refreshes nothing.
    events += _model_call(100, "o-1", ["sleep-1"])
    events += _call("sleep-1", "powershell", {"command": "Start-Sleep -Seconds 590"}, 100, 690, 10)
    events += _model_call(700, "o-2")
    events.append(_event("assistant.message", 1_000, {"content": "automatic collection", "toolRequests": []}))
    events += _model_call(1_200, "o-3")
    events += _model_call(1_230, "o-4")
    # 300 s between turn starts (1,229 s to 1,529 s) but 301 s between the messages: only the start-to-start convention keeps it inside the cache life.
    events += _model_call(1_531, "o-5", started=1_529)
    events.append(_event("session.usage_checkpoint", 1_231, {"totalNanoAiu": 7, "totalPremiumRequests": 2, "promptCacheBreakState": [{"models": {"m": {"prompt_tokens": 1000, "cache_read": 100, "cache_write": 900, "system_segments": [{"tokens": 300}], "tool_tokens": 200}}}]}))
    events.append(_event("session.compaction_complete", 1_232, {"preCompactionTokens": 1000, "postCompactionTokens": 100, "compactionTokensUsed": {"cacheWriteTokens": 5, "cacheReadTokens": 900}}))
    return events


def _write(path: Path, events: list[dict]) -> Path:
    path.write_text("\n".join(json.dumps(event) for event in events) + "\n", encoding="utf-8")
    return path


def _session(path: Path) -> Path:
    events = _builder_events() + _orchestrator_events()
    kinds = Counter(event["type"] for event in events)
    # Premises of the fixture, so a change to it cannot quietly make a test vacuous.
    assert kinds["tool.execution_start"] == 11 and kinds["subagent.completed"] == 1
    assert [e["data"].get("delivery") for e in events if e["type"] == "user.message"] == ["idle", "steering", "idle"]
    assert sum(1 for e in events if e["type"] == "assistant.message" and "agentId" not in e and "apiCallId" not in e["data"]) == 1
    assert sum(1 for e in events if e["type"] == "tool.execution_start" and e["data"]["toolName"] == "view" and e["data"]["arguments"].get("path") == "src/a.py") == 4
    return _write(path, events)


def test_collect_measures_a_delegation_from_the_log(measure: ModuleType, tmp_path: Path) -> None:
    agents, _facts = measure.collect(_session(tmp_path / "events.jsonl"))
    builder = agents["b1"]
    assert (builder.role, builder.name, builder.brief_chars) == ("Builder", "builder-x-repair-1", 700)
    assert (builder.reported_tool_calls, builder.reported_tokens) == (9, 900_000)
    assert builder.tokens_per_call == 100_000
    assert builder.reasoning_chars == 40
    assert builder.calls["view"] == 6
    assert builder.duplicate_views == 2 and builder.duplicate_views_without_edit == 1
    assert builder.paths_viewed_more_than_twice() == 1
    assert builder.max_views_of_one_path() == 4
    assert builder.test_runs == [(120, True, True)]
    assert builder.diff_chars == 41_000 and builder.big_results == [("powershell", 41_000)]
    assert builder.edits == 1 and builder.edit_chars == 2


def test_a_steering_message_is_not_a_resume(measure: ModuleType, tmp_path: Path) -> None:
    agents, _facts = measure.collect(_session(tmp_path / "events.jsonl"))
    builder = agents["b1"]
    assert (builder.idle_messages, builder.steering_messages) == (2, 1)
    assert builder.resumes == 1


def test_instruction_reads_count_only_deliveries_of_content(measure: ModuleType, tmp_path: Path) -> None:
    agents, _facts = measure.collect(_session(tmp_path / "events.jsonl"))
    builder = agents["b1"]
    assert builder.instruction_reads == [(False, 2_000), (True, 148)]
    assert builder.instruction_deliveries == [(False, 2_000)]


def test_model_calls_exclude_automatic_result_collection(measure: ModuleType, tmp_path: Path) -> None:
    agents, facts = measure.collect(_session(tmp_path / "events.jsonl"))
    gaps = facts["idle_gaps"]
    assert agents["orchestrator"].assistant_messages == 5
    assert gaps["calls"] == 5
    # Call starts at 99 s, 699 s, 1,199 s and 1,229 s: the sleep and the wait are over the limit; the collecting message at 1,000 s does not split the wait.
    assert gaps["gaps_over_ttl"] == 2
    assert set(gaps["by_cause"]) == {"watchdog sleep", "idle between turns (woken by a notification or the user)"}
    assert gaps["by_cause"]["watchdog sleep"][0] == 1
    assert facts["checkpoints"][0]["prompt_tokens"] == 1000
    assert facts["compactions"][0]["before"] == 1000


def test_render_reports_each_role_and_the_orchestrator(measure: ModuleType, tmp_path: Path) -> None:
    agents, facts = measure.collect(_session(tmp_path / "events.jsonl"))
    report = measure.render(agents, facts, measure._parse_groups(["repairs=-repair-"]))
    assert "## Builder" in report and "## orchestrator" in report
    assert "| repairs | 1 | 9 | 900,000 |" in report
    assert "reads of copilot-instructions.md: 2 attempts, 1 delivered content (at least 1,000 chars), 2,000 chars of content" in report
    assert "steering messages sent to a running delegation (not resumes): 1" in report
    assert "checkpoints whose prompt was mostly cache-written (cold): 1 of 1" in report


def test_since_inside_a_delegation_keeps_its_identity_and_marks_it_partial(measure: ModuleType, tmp_path: Path) -> None:
    path = _session(tmp_path / "events.jsonl")
    agents, facts = measure.collect(path, since=_t(5))
    builder = agents["b1"]
    assert (builder.role, builder.name) == ("Builder", "builder-x-repair-1")
    assert builder.partial_window is True
    assert builder.reported_tokens == 900_000
    assert builder.calls["view"] == 4  # only the views at or after the cutoff
    assert "builder-x-repair-1 (partial window)" in measure.render(agents, facts, [])


def test_since_is_compared_as_an_instant_not_as_text(measure: ModuleType, tmp_path: Path) -> None:
    path = _session(tmp_path / "events.jsonl")
    utc, _ = measure.collect(path, since="2026-10-11T10:00:05+00:00")
    shifted, _ = measure.collect(path, since="2026-10-11T05:00:05-05:00")
    assert utc["b1"].calls == shifted["b1"].calls
    assert utc["b1"].calls["view"] == 4
    with pytest.raises(SystemExit):
        measure.collect(path, since="not a time")


def test_an_empty_since_is_rejected_not_read_as_no_cutoff(measure: ModuleType, tmp_path: Path) -> None:
    path = _session(tmp_path / "events.jsonl")
    assert "b1" in measure.collect(path)[0]  # premise: without a cutoff the log yields the delegation
    with pytest.raises(SystemExit):
        measure.collect(path, since="")
    with pytest.raises(SystemExit):
        measure.main([str(path), "--since", ""])


# The fixture's delegation was briefed at 1 s, steered at 5 s, ended its first turn at 12 s and was restarted at 13 s.
@pytest.mark.parametrize(
    ("cutoff", "partial", "tokens"),
    [(0, False, 900_000), (2, True, 900_000), (6, True, 900_000), (12, True, 900_000), (13, True, None)],
)
def test_since_keeps_a_delegations_messages_classified_over_its_whole_life(
    measure: ModuleType, tmp_path: Path, cutoff: int, partial: bool, tokens: int | None,
) -> None:
    path = _session(tmp_path / "events.jsonl")
    whole = measure.collect(path)[0]["b1"]
    assert (whole.idle_messages, whole.steering_messages, whole.resumes) == (2, 1, 1)  # premise: the full log's classification
    builder = measure.collect(path, since=_t(cutoff))[0]["b1"]
    assert (builder.idle_messages, builder.steering_messages, builder.resumes) == (2, 1, 1)
    assert builder.partial_window is partial
    assert builder.reported_tokens == tokens  # a first turn that ended before the window is not part of what the window spent


def test_since_leaves_out_a_delegation_with_no_event_in_the_window(measure: ModuleType, tmp_path: Path) -> None:
    path = _session(tmp_path / "events.jsonl")
    everything, _ = measure.collect(path)
    assert "b1" in everything and everything["orchestrator"].calls["task"] == 1  # premise: both exist before the cutoff
    agents, facts = measure.collect(path, since=_t(14))
    assert "b1" not in agents and agents["orchestrator"].calls["task"] == 0
    report = measure.render(agents, facts, [])
    assert "## Builder" not in report and "## orchestrator" in report


def test_unrecognised_events_and_an_empty_log_do_not_stop_the_report(measure: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = tmp_path / "odd.jsonl"
    odd = [
        {"type": "mystery.event", "data": {}, "timestamp": _t(1)},
        {"type": "tool.execution_complete", "data": {"toolCallId": "orphan"}, "timestamp": _t(2)},
        {"type": "assistant.message", "data": {"apiCallId": "a", "toolRequests": ["not an object"]}, "timestamp": "garbled"},
    ]
    path.write_text("\n".join(json.dumps(event) for event in odd) + "\n\n", encoding="utf-8")
    assert measure.main([str(path)]) == 0
    assert "## orchestrator" in capsys.readouterr().out
    empty = tmp_path / "empty.jsonl"
    empty.write_text("", encoding="utf-8")
    assert measure.main([str(empty)]) == 0


@pytest.mark.parametrize("since", [None, 50], ids=["no-cutoff", "cutoff-before-both-calls"])
@pytest.mark.parametrize("start", [{"timestamp": "garbled"}, {"timestamp": ""}, {}], ids=["garbled", "blank", "missing"])
def test_model_calls_with_an_unreadable_start_time_are_skipped_and_counted(
    measure: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str], start: dict, since: int | None,
) -> None:
    def two_calls(second_start: dict) -> list[dict]:
        return _model_call(100, "o-1") + [
            {"type": "assistant.turn_start", "data": {}, **second_start},
            {"type": "assistant.message", "data": {"apiCallId": "o-2", "toolRequests": []}, "timestamp": _t(700)},
        ]

    window = {} if since is None else {"since": _t(since)}
    # Premise: a readable start at the same place makes a gap over the cache life, so reading the reply time instead of a bad start time would show as one.
    readable = measure.collect(_write(tmp_path / "readable.jsonl", two_calls({"timestamp": _t(699)})), **window)[1]["idle_gaps"]
    assert (readable["calls"], readable["gaps_over_ttl"], readable["unreadable"]) == (2, 1, 0)
    events = two_calls(start)
    assert sum(1 for e in events if e["type"] == "assistant.message" and e["data"].get("apiCallId")) == 2  # premise: two model calls
    path = _write(tmp_path / "events.jsonl", events)
    gaps = measure.collect(path, **window)[1]["idle_gaps"]
    assert (gaps["calls"], gaps["unreadable"], gaps["gaps_over_ttl"]) == (2, 1, 0)
    assert measure.main([str(path)] + ([] if since is None else ["--since", _t(since)])) == 0
    assert "pairs of calls skipped because a start time was unreadable: 1" in capsys.readouterr().out


def test_a_wait_on_a_tool_call_with_an_unreadable_start_time_is_named_unknown(measure: ModuleType, tmp_path: Path) -> None:
    events = _model_call(100, "o-1", ["c1"])
    events.append({"type": "tool.execution_start", "data": {"toolCallId": "c1", "toolName": "powershell", "arguments": {"command": "Start-Sleep -Seconds 590"}}, "timestamp": "garbled"})
    events += [_event("tool.execution_complete", 690, {"toolCallId": "c1", "result": {"content": "x"}})] + _model_call(700, "o-2")
    gaps = measure.collect(_write(tmp_path / "events.jsonl", events))[1]["idle_gaps"]
    assert gaps["gaps_over_ttl"] == 1  # premise: the 600 s wait was found, and only its cause is in doubt
    assert set(gaps["by_cause"]) == {"unknown (unreadable timestamp)"}


def test_the_orchestrators_whole_file_attempts_are_reported(measure: ModuleType, tmp_path: Path) -> None:
    events = _call("w", "view", {"path": ".github/copilot-instructions.md"}, 1, 1, 584)
    events += _call("r", "view", {"path": ".github/copilot-instructions.md", "view_range": [1, 40]}, 2, 2, 2_000)
    agents, facts = measure.collect(_write(tmp_path / "events.jsonl", events))
    assert agents["orchestrator"].instruction_reads == [(True, 584), (False, 2_000)]  # premise
    report = measure.render(agents, facts, [])
    assert "reads of copilot-instructions.md: 2 attempts, 1 delivered content; whole-file attempts 1 (delivered content: 0)" in report


def test_group_syntax_is_checked(measure: ModuleType) -> None:
    with pytest.raises(SystemExit):
        measure._parse_groups(["no-equals-sign"])


def test_main_writes_the_report_and_raw_json(measure: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = _session(tmp_path / "events.jsonl")
    raw = tmp_path / "raw.json"
    assert measure.main([str(path), "--json", str(raw), "--group", "repairs=repair"]) == 0
    assert "# Agent token usage" in capsys.readouterr().out
    payload = json.loads(raw.read_text(encoding="utf-8"))
    assert payload["agents"]["b1"]["reported_tokens"] == 900_000
    assert payload["facts"]["idle_gaps"]["gaps_over_ttl"] == 2
    assert payload["facts"]["idle_gaps"]["unreadable"] == 0
    assert "active" not in payload["agents"]["b1"]  # window bookkeeping is not part of the measurements


def test_since_windows_the_orchestrators_own_message_count(measure: ModuleType, tmp_path: Path) -> None:
    events = [_event("user.message", 1, {"content": "hello", "delivery": "idle"}), _event("user.message", 700, {"content": "again", "delivery": "idle"})]
    path = _write(tmp_path / "events.jsonl", events)
    assert measure.collect(path)[0]["orchestrator"].idle_messages == 2  # premise: both messages are in the log
    assert measure.collect(path, since=_t(100))[0]["orchestrator"].idle_messages == 1


@pytest.mark.parametrize("bad", [{"timestamp": "garbled"}, {"timestamp": ""}, {}], ids=["garbled", "blank", "missing"])
def test_since_leaves_out_events_whose_time_cannot_be_read(measure: ModuleType, tmp_path: Path, bad: dict) -> None:
    started = {"agentName": "Builder", "agentDisplayName": "b9", "model": "m1", "executionMode": "background"}
    events = [
        {"type": "user.message", "data": {"content": "hello", "delivery": "idle"}, **bad},
        {"type": "subagent.started", "data": started, "agentId": "b9", **bad},
        _event("user.message", 700, {"content": "again", "delivery": "idle"}),
    ]
    path = _write(tmp_path / "events.jsonl", events)
    whole_agents, whole_facts = measure.collect(path)
    assert (whole_agents["orchestrator"].idle_messages, "b9" in whole_agents, whole_facts["unplaced_events"]) == (2, True, 0)  # premise: without a cutoff nothing is unplaced
    agents, facts = measure.collect(path, since=_t(100))
    assert (agents["orchestrator"].idle_messages, "b9" in agents, facts["unplaced_events"]) == (1, False, 2)
    assert "Note: 2 events had no readable time and were left out of the window." in measure.render(agents, facts, [])
    assert "Note:" not in measure.render(whole_agents, whole_facts, [])
