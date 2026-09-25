"""AD-1246 (#1241): units for the long-run planner, grant, service and kill switch,
the config bounds, and the tool's model-facing text.

The integration seams live in ``tests/test_ad1246_long_run_promotion.py``; these
are the pieces they rest on, driven directly. The kill-switch units use a real
``SubprocessSandbox`` child, and the lowered-run unit a real ``CodeExecutionTool``.
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError

import probos.tools.code_execution_tool as code_execution_tool
from probos.cognitive.decomposer import is_capability_gap
from probos.config import ExecutionConfig
from probos.execution import long_runs
from probos.execution.isolation import ExecutionRequest, KillSwitch, SubprocessSandbox
from probos.execution.long_runs import (
    EXECUTION_LONG_RUN_GRANT_KEY,
    LongRunGrant,
    LongRunService,
    plan_long_run,
)
from probos.security.audit import AuditLog
from probos.tools.executor import classify_tool_error


@pytest.fixture(scope="module", autouse=True)
def _assert_tested_source_matches_worktree() -> None:
    import probos.execution.isolation as isolation_module
    import probos.execution.long_runs as long_runs_module
    import probos.tools.code_execution_tool as tool_module

    source = Path(__file__).resolve().parents[1] / "src"
    assert Path(long_runs_module.__file__).resolve().is_relative_to(source)
    assert Path(isolation_module.__file__).resolve().is_relative_to(source)
    assert Path(tool_module.__file__).resolve().is_relative_to(source)


def _beats_code(beat_file: Path, beats: int) -> str:
    """One process, no children: append one numbered line every 0.1 s, then exit 0."""
    assert beats <= 50
    return (
        "import time\n"
        f"path = {str(beat_file)!r}\n"
        f"for i in range({beats}):\n"
        "    with open(path, 'a', encoding='utf-8') as handle:\n"
        "        handle.write(f'{i}\\n')\n"
        "    time.sleep(0.1)\n"
        f"print('beats done: {beats}')\n"
    )


def _beats(beat_file: Path) -> int:
    return beat_file.read_bytes().count(b"\n") if beat_file.exists() else 0


# ---------------------------------------------------------------------------
# M2: the kill switch
# ---------------------------------------------------------------------------


class _RecordingSwitch(KillSwitch):
    """A real switch that also records what ``attach`` answered the worker."""

    def __init__(self) -> None:
        super().__init__()
        self.attach_answers: list[bool] = []

    def attach(self, proc: Any) -> bool:
        answer = super().attach(proc)
        self.attach_answers.append(answer)
        return answer


async def test_kill_switch_fired_before_launch_kills_at_attach(tmp_path: Path) -> None:
    beat_file = tmp_path / "beats.txt"
    switch = _RecordingSwitch()
    switch.fire("x")
    # Premise: the switch fired before any child existed.
    assert switch.reason == "x"
    request = ExecutionRequest(
        code=_beats_code(beat_file, 50), workdir=tmp_path / "work",
        timeout_seconds=30.0, kill_switch=switch,
    )

    result = await asyncio.wait_for(
        SubprocessSandbox(scratch_root=tmp_path / "scratch").run(request), timeout=30,
    )
    beats_at_return = _beats(beat_file)

    assert switch.attach_answers == [False]
    assert result.success is False
    assert result.timed_out is False
    assert result.error == "stopped: x"
    assert result.exit_code != 0
    assert result.child_reaped is True
    await asyncio.sleep(0.6)
    assert _beats(beat_file) == beats_at_return < 50


def test_kill_switch_fire_after_detach_signals_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    signalled: list[Any] = []
    monkeypatch.setattr(SubprocessSandbox, "_kill", staticmethod(signalled.append))
    finished = subprocess.Popen([sys.executable, "-c", "pass"])
    finished.wait(timeout=30)
    live = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        # Premise: the spy sees a fire that reaches an attached, running child.
        control = KillSwitch()
        assert control.attach(live) is True
        control.fire("control")
        assert len(signalled) == 1 and signalled[0] is live
        signalled.clear()

        # The worker detaches once the child is reaped. A live child is the case
        # only the detach protects: its returncode is still None.
        for proc in (finished, live):
            switch = KillSwitch()
            assert switch.attach(proc) is True
            switch.detach()
            switch.fire("late")
            assert switch.reason == "late"
        assert signalled == []
    finally:
        live.kill()
        live.wait(timeout=30)


async def test_timed_out_error_with_each_wall_clock_note_classifies_as_timeout() -> None:
    """A-3: the model reads "timed out. <note>"; no note may re-categorise that failure."""
    # Premise: the classifier does notice a note that re-categorises.
    assert classify_tool_error("timed out") == "timeout"
    assert classify_tool_error("timed out. The request was denied.") == "permission_denied"
    service = LongRunService()
    tickets = []
    try:
        holder = service.admit("holder", limit=1)
        assert holder is not None
        tickets.append(holder)
        plans = {
            "long_runs_busy": plan_long_run(
                1200.0, max_runtime_seconds=1800.0, max_concurrent=1,
                grant=LongRunGrant(None), service=service, execution_id="busy",
            ),
            "turn_time_left": plan_long_run(
                1500.0, max_runtime_seconds=1800.0, max_concurrent=4,
                grant=LongRunGrant(time.monotonic() + 1187.0), service=service,
                execution_id="near",
            ),
            "max_runtime": plan_long_run(
                3600.0, max_runtime_seconds=1800.0, max_concurrent=4,
                grant=LongRunGrant(None), service=service, execution_id="capped",
            ),
        }
        for reason, plan in plans.items():
            assert plan is not None and plan.wall_clock is not None, reason
            if plan.ticket is not None:
                tickets.append(plan.ticket)
            assert plan.wall_clock["reason"] == reason
            assert classify_tool_error("timed out. " + plan.wall_clock["note"]) == "timeout", reason
    finally:
        for ticket in tickets:
            ticket.finish()
        service.close("test")
        assert await service.wait_settled(1.0) is True


# ---------------------------------------------------------------------------
# M4: the service at shutdown
# ---------------------------------------------------------------------------


def _attach_running_child(switch: KillSwitch) -> Any:
    """Attach a stand-in for a running child; ``fire`` reads only its ``returncode``."""
    child = SimpleNamespace(returncode=None)
    assert switch.attach(child) is True
    return child


async def test_service_close_fires_every_switch_and_refuses_admission(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    signalled: list[Any] = []
    monkeypatch.setattr(SubprocessSandbox, "_kill", staticmethod(signalled.append))
    service = LongRunService()
    first = service.admit("run-a", limit=4)
    second = service.admit("run-b", limit=4)
    assert first is not None and second is not None
    children = [
        _attach_running_child(first.kill_switch), _attach_running_child(second.kill_switch),
    ]
    try:
        service.close("shutdown")
        assert first.kill_switch.reason == "shutdown"
        assert second.kill_switch.reason == "shutdown"
        assert len(signalled) == 2
        assert {id(child) for child in signalled} == {id(child) for child in children}
        assert service.closed is True
        assert service.admit("run-c", limit=4) is None
    finally:
        first.finish()
        second.finish()
        assert await service.wait_settled(1.0) is True


async def test_service_close_is_idempotent(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
) -> None:
    signalled: list[Any] = []
    monkeypatch.setattr(SubprocessSandbox, "_kill", staticmethod(signalled.append))
    service = LongRunService()
    ticket = service.admit("run-a", limit=1)
    assert ticket is not None
    child = _attach_running_child(ticket.kill_switch)
    try:
        with caplog.at_level(logging.INFO, logger="probos.execution.long_runs"):
            service.close("shutdown")
            service.close("again")
        # Premise: the first close reached the still-attached child, so a second fire would too.
        assert len(signalled) == 1 and signalled[0] is child
        assert ticket.kill_switch.reason == "shutdown"
        closes = [r for r in caplog.records if "long-run service closed" in r.getMessage()]
        assert len(closes) == 1
        assert service.closed is True
    finally:
        ticket.finish()
        assert await service.wait_settled(1.0) is True


async def test_service_close_when_idle_logs_nothing(caplog: pytest.LogCaptureFixture) -> None:
    # An unarmed or idle vessel's shutdown log must not change (review, 2026-09-25).
    own = "probos.execution.long_runs"
    active = LongRunService()
    ticket = active.admit("run-a", limit=1)
    assert ticket is not None
    try:
        with caplog.at_level(logging.DEBUG, logger=own):
            # Premise: the same close does log when a run is active, so the
            # silence below comes from the idle service, not a muted logger.
            active.close("shutdown")
            assert [r for r in caplog.records if r.name == own and "long-run service closed" in r.getMessage()]
            caplog.clear()
            for phase in ("never admitted", "admitted and finished"):
                idle = LongRunService()
                if phase == "admitted and finished":
                    finished = idle.admit("run-b", limit=1)
                    assert finished is not None
                    finished.finish()
                idle.close("shutdown")
                assert idle.closed is True
                assert [r for r in caplog.records if r.name == own] == [], phase
    finally:
        ticket.finish()


async def test_wait_settled_does_not_suspend_when_idle() -> None:
    loop = asyncio.get_running_loop()
    # Premise: one suspension is enough to run a callback scheduled with call_soon.
    control = asyncio.Event()
    loop.call_soon(control.set)
    await asyncio.sleep(0)
    assert control.is_set()

    service = LongRunService()
    try:
        for phase in ("never admitted", "admitted and finished"):
            if phase == "admitted and finished":
                ticket = service.admit("run-a", limit=1)
                assert ticket is not None
                ticket.finish()
            flag = asyncio.Event()
            loop.call_soon(flag.set)
            assert await service.wait_settled(1.0) is True
            assert not flag.is_set(), phase
            await asyncio.sleep(0)
    finally:
        service.close("test")


async def test_wait_settled_times_out_and_reports_false(caplog: pytest.LogCaptureFixture) -> None:
    service = LongRunService()
    ticket = service.admit("run-never-finishes", limit=1)
    assert ticket is not None
    try:
        with caplog.at_level(logging.WARNING, logger="probos.execution.long_runs"):
            assert await service.wait_settled(0.2) is False
        warnings = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
        assert len(warnings) == 1
        assert "run-never-finishes" in warnings[0]
    finally:
        ticket.finish()
        assert await service.wait_settled(1.0) is True
        service.close("test")


# ---------------------------------------------------------------------------
# M5: config bounds, the planner and the grant
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "accepted", "error_type"),
    [
        (0.0, True, None),
        (300.0, False, "value_error"),
        (300.5, True, None),
        (1800, True, None),
        (86400, True, None),
        (-1, False, "greater_than_equal"),
        (86400.5, False, "less_than_equal"),
        (float("nan"), False, None),
        (float("inf"), False, None),
    ],
    ids=[
        "off", "inline", "just-above-inline", "recommended", "ceiling", "negative",
        "above-ceiling", "nan", "inf",
    ],
)
def test_execution_config_max_runtime_seconds_table(
    value: float, accepted: bool, error_type: str | None,
) -> None:
    if accepted:
        assert ExecutionConfig(max_runtime_seconds=value).max_runtime_seconds == float(value)
        return
    with pytest.raises(ValidationError) as info:
        ExecutionConfig(max_runtime_seconds=value)
    errors = info.value.errors()
    assert [error["loc"] for error in errors] == [("max_runtime_seconds",)]
    if error_type is not None:
        assert errors[0]["type"] == error_type


@pytest.mark.parametrize(
    ("value", "error_type"),
    [(1, None), (16, None), (0, "greater_than_equal"), (17, "less_than_equal")],
    ids=["one", "pool-size", "zero", "above-pool-size"],
)
def test_execution_config_max_concurrent_long_runs_table(value: int, error_type: str | None) -> None:
    if error_type is None:
        assert ExecutionConfig(max_concurrent_long_runs=value).max_concurrent_long_runs == value
        return
    with pytest.raises(ValidationError) as info:
        ExecutionConfig(max_concurrent_long_runs=value)
    assert [(error["loc"], error["type"]) for error in info.value.errors()] == [
        (("max_concurrent_long_runs",), error_type),
    ]


def test_validator_twin_matches_the_inline_ceiling() -> None:
    """operations.py may not import probos, so its 300.0 is a literal twin of the ceiling."""
    inline = long_runs.INLINE_WALL_CLOCK_SECONDS
    with pytest.raises(ValidationError, match=f"or above {inline:.0f} "):
        ExecutionConfig(max_runtime_seconds=inline)
    assert ExecutionConfig(max_runtime_seconds=inline + 0.001).max_runtime_seconds == inline + 0.001


def _plan(pool: LongRunService, requested: Any = 1200.0, **overrides: Any) -> Any:
    """``plan_long_run`` for an armed, granted, admissible call unless a keyword overrides it."""
    arguments: dict[str, Any] = {
        "max_runtime_seconds": 1800.0, "max_concurrent": 2, "grant": LongRunGrant(None),
        "service": pool, "execution_id": "exec-1",
    }
    arguments.update(overrides)
    return plan_long_run(requested, **arguments)


async def _finish_and_close(service: LongRunService, tickets: list[Any]) -> None:
    for ticket in tickets:
        ticket.finish()
    service.close("test")
    assert await service.wait_settled(1.0) is True


class _GrantSubclass(LongRunGrant):
    """Passes ``isinstance``, so only the planner's exact-type check can refuse it."""


@pytest.mark.parametrize(
    ("requested", "overrides"),
    [
        (1200.0, {"max_runtime_seconds": 0.0}),
        (1200.0, {"max_runtime_seconds": 300.0}),
        (1200.0, {"max_runtime_seconds": MagicMock()}),
        (1200.0, {"max_concurrent": MagicMock()}),
        (1200.0, {"max_concurrent": True}),
        (1200.0, {"max_concurrent": 0}),
        (1200.0, {"grant": None}),
        (1200.0, {"grant": _GrantSubclass(None)}),
        (1200.0, {"service": None}),
        (300.0, {}),
        (30, {}),
        (None, {}),
        ("abc", {}),
        (float("inf"), {}),
        (float("nan"), {}),
    ],
    ids=[
        "unarmed", "armed-at-the-inline-clock", "mock-max-runtime", "mock-max-concurrent",
        "bool-max-concurrent", "zero-max-concurrent", "no-grant", "grant-subclass",
        "no-service", "request-at-ceiling", "request-below-ceiling", "request-none",
        "request-text", "request-inf", "request-nan",
    ],
)
async def test_plan_long_run_returns_none_for_todays_path(
    requested: Any, overrides: dict[str, Any],
) -> None:
    service = LongRunService()
    tickets: list[Any] = []
    try:
        # Premise: the same call with nothing overridden is planned and admitted.
        control = _plan(service, execution_id="control")
        assert control is not None and control.ticket is not None
        tickets.append(control.ticket)

        assert _plan(service, requested, **overrides) is None
        assert service.active_count == 1, "a call on today's path takes no long-run slot"
    finally:
        await _finish_and_close(service, tickets)


_BUSY_NOTE = (
    "Every long-run slot was in use, so this run had the 300s inline wall clock. "
    "Run it again once a long job finishes, or split the work."
)


@pytest.mark.parametrize("state", ["closed", "full"])
async def test_plan_long_run_without_a_slot_gets_the_inline_clock(state: str) -> None:
    service = LongRunService()
    tickets: list[Any] = []
    try:
        if state == "closed":
            service.close("test")
        else:
            for holder in ("holder-a", "holder-b"):
                ticket = service.admit(holder, limit=2)
                assert ticket is not None
                tickets.append(ticket)
        plan = _plan(service)
        assert plan is not None
        assert plan.ticket is None
        assert plan.timeout_seconds == long_runs.INLINE_WALL_CLOCK_SECONDS == 300.0
        assert plan.wall_clock == {
            "requested_seconds": 1200.0, "applied_seconds": 300.0,
            "reason": "long_runs_busy", "note": _BUSY_NOTE,
        }
    finally:
        await _finish_and_close(service, tickets)


async def test_plan_long_run_turn_time_left_lowers_the_request() -> None:
    service = LongRunService()
    tickets: list[Any] = []
    try:
        plan = _plan(service, 1500.0, grant=LongRunGrant(time.monotonic() + 1000.0))
        assert plan is not None and plan.ticket is not None
        tickets.append(plan.ticket)
        # The turn's time left binds, below both the request and max_runtime_seconds.
        assert 900.0 < plan.timeout_seconds <= 1000.0
        assert plan.wall_clock is not None
        assert plan.wall_clock["reason"] == "turn_time_left"
        assert plan.wall_clock["requested_seconds"] == 1500.0
        assert plan.wall_clock["applied_seconds"] == plan.timeout_seconds
    finally:
        await _finish_and_close(service, tickets)


async def test_plan_long_run_max_runtime_lowers_the_request() -> None:
    service = LongRunService()
    tickets: list[Any] = []
    try:
        plan = _plan(service, 3600.0)
        assert plan is not None and plan.ticket is not None
        tickets.append(plan.ticket)
        assert plan.timeout_seconds == 1800.0
        assert plan.wall_clock == {
            "requested_seconds": 3600.0, "applied_seconds": 1800.0, "reason": "max_runtime",
            "note": (
                "This vessel stops a single long run at 1800s (execution.max_runtime_seconds). "
                "Split the work into steps that fit."
            ),
        }
    finally:
        await _finish_and_close(service, tickets)


@pytest.mark.parametrize("time_left", [120.0, -50.0], ids=["below-inline", "past-deadline"])
async def test_plan_long_run_never_applies_less_than_the_inline_clock(time_left: float) -> None:
    service = LongRunService()
    tickets: list[Any] = []
    try:
        grant = LongRunGrant(time.monotonic() + time_left)
        # Premise: the turn has less time left than the inline clock.
        assert grant.remaining() < long_runs.INLINE_WALL_CLOCK_SECONDS
        plan = _plan(service, 1500.0, grant=grant)
        assert plan is not None and plan.ticket is not None
        tickets.append(plan.ticket)
        assert plan.timeout_seconds == long_runs.INLINE_WALL_CLOCK_SECONDS == 300.0
        assert plan.wall_clock is not None
        assert plan.wall_clock["reason"] == "turn_time_left"
        assert plan.wall_clock["applied_seconds"] == 300.0
    finally:
        await _finish_and_close(service, tickets)


async def test_plan_long_run_that_fits_carries_no_wall_clock() -> None:
    service = LongRunService()
    tickets: list[Any] = []
    try:
        plan = _plan(service, 1200.0)
        assert plan is not None and plan.ticket is not None
        tickets.append(plan.ticket)
        assert (plan.timeout_seconds, plan.wall_clock) == (1200.0, None)
        # Asking for exactly the most this vessel allows is not a lowering either.
        at_cap = _plan(service, 1800.0, execution_id="exec-2")
        assert at_cap is not None and at_cap.ticket is not None
        tickets.append(at_cap.ticket)
        assert (at_cap.timeout_seconds, at_cap.wall_clock) == (1800.0, None)
    finally:
        await _finish_and_close(service, tickets)


async def test_plan_long_run_clamps_the_limit_to_the_pool_size() -> None:
    service = LongRunService()
    tickets: list[Any] = []
    try:
        for index in range(15):
            ticket = service.admit(f"holder-{index}", limit=16)
            assert ticket is not None
            tickets.append(ticket)
        # Premise: with one of the 16 pool threads still free, a limit of 20 admits the run.
        sixteenth = _plan(service, max_concurrent=20, execution_id="sixteenth")
        assert sixteenth is not None and sixteenth.ticket is not None
        tickets.append(sixteenth.ticket)
        # With all 16 spoken for, the same limit refuses: it was clamped to the pool size.
        seventeenth = _plan(service, max_concurrent=20, execution_id="seventeenth")
        assert seventeenth is not None
        assert seventeenth.ticket is None
        assert seventeenth.wall_clock is not None
        assert seventeenth.wall_clock["reason"] == "long_runs_busy"
        assert service.active_count == 16
    finally:
        await _finish_and_close(service, tickets)


@pytest.mark.parametrize(
    ("max_runtime", "promote_after"),
    [
        (0.0, 40.0), (300.0, 40.0), (MagicMock(), 40.0), (True, 40.0),
        (1800.0, 0.0), (1800.0, -5.0), (1800.0, MagicMock()),
    ],
    ids=[
        "unarmed", "armed-at-the-inline-clock", "mock-max-runtime", "bool-max-runtime",
        "promotion-off", "promotion-negative", "mock-promotion",
    ],
)
def test_for_promoted_turn_returns_none_unless_armed_and_promotable(
    max_runtime: Any, promote_after: Any,
) -> None:
    # Premise: an armed, promotable turn does get a grant.
    assert LongRunGrant.for_promoted_turn(
        max_runtime_seconds=1800.0, promote_after_seconds=40.0, deadline_seconds=1800.0, now=0.0,
    ) is not None
    assert LongRunGrant.for_promoted_turn(
        max_runtime_seconds=max_runtime, promote_after_seconds=promote_after,
        deadline_seconds=1800.0, now=0.0,
    ) is None


def test_for_promoted_turn_with_no_deadline_has_unbounded_time() -> None:
    grant = LongRunGrant.for_promoted_turn(
        max_runtime_seconds=1800.0, promote_after_seconds=40.0, deadline_seconds=0.0, now=100.0,
    )
    assert grant is not None
    assert grant.deadline_monotonic is None
    assert grant.remaining() == math.inf
    assert grant.remaining(now=1e9) == math.inf


def test_for_promoted_turn_estimates_the_watchdog_less_the_answer_margin() -> None:
    grant = LongRunGrant.for_promoted_turn(
        max_runtime_seconds=1800.0, promote_after_seconds=40.0, deadline_seconds=1800.0, now=1000.0,
    )
    assert grant is not None
    # now + promote_after + deadline - the 300 s answer margin.
    assert grant.deadline_monotonic == 1000.0 + 40.0 + 1800.0 - 300.0 == 2540.0
    assert grant.remaining(now=1000.0) == 1540.0
    assert grant.remaining(now=3000.0) == -460.0


async def test_lowered_run_that_finishes_carries_no_wall_clock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(long_runs, "INLINE_WALL_CLOCK_SECONDS", 1.0)
    real_plan = code_execution_tool.plan_long_run
    planned: list[Any] = []

    def _recording_plan(*args: Any, **kwargs: Any) -> Any:
        plan = real_plan(*args, **kwargs)
        planned.append(plan)
        return plan

    monkeypatch.setattr(code_execution_tool, "plan_long_run", _recording_plan)
    service = LongRunService()
    runtime = SimpleNamespace(
        # H-4: the validator refuses a 2 s reach, so this config is built without it.
        config=SimpleNamespace(execution=ExecutionConfig.model_construct(
            enabled=True, scratch_dir=str(tmp_path / "scratch"), max_runtime_seconds=2.0,
        )),
        audit_log=AuditLog(),
        execution_long_runs=service,
    )
    tool = code_execution_tool.CodeExecutionTool(runtime=runtime)
    context = {EXECUTION_LONG_RUN_GRANT_KEY: LongRunGrant(None), "agent_id": "a", "thread_id": ""}
    try:
        result = await asyncio.wait_for(
            tool.invoke(
                {"code": "import time\ntime.sleep(0.3)\nprint('done')\n", "timeout": 5}, context,
            ),
            timeout=30,
        )
        # Premise: the request was lowered, so an explanation existed for this call ...
        assert len(planned) == 1 and planned[0] is not None
        assert planned[0].timeout_seconds == 2.0
        assert planned[0].wall_clock is not None
        assert planned[0].wall_clock["reason"] == "max_runtime"
        records = [
            json.loads(entry.detail) for entry in runtime.audit_log.entries
            if entry.category == "code_execution"
        ]
        assert len(records) == 1 and records[0]["timeout_seconds"] == 2.0
        # ... but the run finished inside the lowered clock, so nothing was cut short.
        assert result.output["success"] is True
        assert result.output["timed_out"] is False
        assert "done" in result.output["stdout"]
        assert "wall_clock" not in result.output
        assert result.error is None
        assert service.active_count == 0
    finally:
        service.close("test")
        await service.wait_settled(5.0)


# ---------------------------------------------------------------------------
# M6: model-facing text
# ---------------------------------------------------------------------------

_UNARMED_TIMEOUT_TEXT = "Optional max seconds (default from config; capped at 300)."


def _tool_with_reach(tmp_path: Path, max_runtime_seconds: float) -> Any:
    runtime = SimpleNamespace(config=SimpleNamespace(execution=ExecutionConfig(
        enabled=True, scratch_dir=str(tmp_path / "scratch"),
        max_runtime_seconds=max_runtime_seconds,
    )))
    return code_execution_tool.CodeExecutionTool(runtime=runtime)


def _armed_wall_clock_part(reach: float) -> str:
    return (
        "30s wall clock by default (the timeout parameter raises it to 300s, or to "
        f"{reach:.0f}s in a direct conversation turn, which continues in the background "
        "once it outlasts a reply)"
    )


def _assert_gap_detector_is_live() -> None:
    # Premise: the real detector does flag a gap phrase, so a False below means clean.
    assert is_capability_gap("I cannot run that here") is True


def test_armed_description_states_the_reach_and_is_gap_clean(tmp_path: Path) -> None:
    _assert_gap_detector_is_live()
    description = _tool_with_reach(tmp_path, 1800.0).description
    assert "or to 1800s in a direct conversation turn" in description
    assert description.count(_armed_wall_clock_part(1800.0)) == 1
    assert is_capability_gap(description) is False


def test_armed_description_differs_only_in_the_wall_clock_part(tmp_path: Path) -> None:
    armed = _tool_with_reach(tmp_path, 1800.0).description
    unarmed = _tool_with_reach(tmp_path, 0.0).description
    # Premise: the unarmed text names the plain wall clock and nothing of the long reach.
    assert "30s wall clock" in unarmed
    assert "direct conversation turn" not in unarmed
    assert armed != unarmed
    assert armed.replace(_armed_wall_clock_part(1800.0), "30s wall clock") == unarmed


def test_armed_schema_text_is_gap_clean(tmp_path: Path) -> None:
    _assert_gap_detector_is_live()
    armed = _tool_with_reach(tmp_path, 1800.0).input_schema
    unarmed = _tool_with_reach(tmp_path, 0.0).input_schema
    text = armed["properties"]["timeout"]["description"]
    assert text == (
        "Optional max seconds (default from config; capped at 300, or at 1800 in a direct "
        "conversation turn that continues in the background)."
    )
    assert is_capability_gap(text) is False
    # That one string is the only difference between the armed and unarmed schemas.
    armed["properties"]["timeout"]["description"] = _UNARMED_TIMEOUT_TEXT
    assert armed == unarmed


@pytest.mark.parametrize("configured", ["unarmed", "reach-at-the-inline-clock", "no-config"])
def test_unarmed_schema_text_is_the_golden_literal(tmp_path: Path, configured: str) -> None:
    if configured == "no-config":
        tool = code_execution_tool.CodeExecutionTool(runtime=SimpleNamespace())
    elif configured == "reach-at-the-inline-clock":
        # A reach that lengthens nothing is not armed (the validator refuses it at parse time).
        tool = code_execution_tool.CodeExecutionTool(runtime=SimpleNamespace(config=SimpleNamespace(
            execution=ExecutionConfig.model_construct(enabled=True, max_runtime_seconds=300.0),
        )))
    else:
        tool = _tool_with_reach(tmp_path, 0.0)
    assert tool.input_schema["properties"]["timeout"]["description"] == _UNARMED_TIMEOUT_TEXT


async def test_every_wall_clock_note_is_gap_clean() -> None:
    _assert_gap_detector_is_live()
    service = LongRunService()
    tickets: list[Any] = []
    try:
        holder = service.admit("holder", limit=1)
        assert holder is not None
        tickets.append(holder)
        plans = [
            plan_long_run(
                1200.0, max_runtime_seconds=1800.0, max_concurrent=1,
                grant=LongRunGrant(None), service=service, execution_id="busy",
            ),
            plan_long_run(
                1500.0, max_runtime_seconds=1800.0, max_concurrent=4,
                grant=LongRunGrant(time.monotonic() + 1187.0), service=service,
                execution_id="near",
            ),
            plan_long_run(
                3600.0, max_runtime_seconds=1800.0, max_concurrent=4,
                grant=LongRunGrant(None), service=service, execution_id="capped",
            ),
        ]
        reasons = []
        for plan in plans:
            assert plan is not None and plan.wall_clock is not None
            if plan.ticket is not None:
                tickets.append(plan.ticket)
            reasons.append(plan.wall_clock["reason"])
            note = plan.wall_clock["note"]
            # The bare note, and the full error the model reads when the run times out (A-3).
            assert is_capability_gap(note) is False, note
            assert is_capability_gap("timed out. " + note) is False, note
        assert reasons == ["long_runs_busy", "turn_time_left", "max_runtime"]
    finally:
        await _finish_and_close(service, tickets)


@pytest.mark.parametrize("error", ["stopped: shutdown", "stopped: cancelled"])
def test_stopped_error_is_gap_clean(error: str) -> None:
    _assert_gap_detector_is_live()
    assert is_capability_gap(error) is False
