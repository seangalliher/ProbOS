"""AD-1173: a repair is verified before it returns to service.

SystemQAAgent and RedTeamAgent are implemented, registered, and have never been
spawned in production. This is the "test it, then put it back into use" half of
the loop, and for a tool fault the check is unusually direct: re-run the
operation that failed and see whether the error signature is gone.

The outcome that matters most is `inconclusive`. Closing a fault because it
could not be checked is exactly how a broken tool returns to service.
"""

from __future__ import annotations

import json

import pytest

from probos.cognitive.repair_verification import (
    VerificationResult,
    find_failing_arguments,
    verify_and_close,
    verify_repair,
)
from probos.fault_report import FaultReportStore, error_signature
from probos.tools.protocol import ToolResult

_ERROR = "unknown browser action: 'key_type'"
_SIG = error_signature(tool_id="browser", error_text=_ERROR)
_ARGS = {"action": "key_type", "text": "Hello Ezri", "delay_ms": 50}

_TRACE = [
    {"name": "browser", "arguments": {"action": "state"},
     "output": "ok", "is_error": False},
    {"name": "browser", "arguments": _ARGS, "output": _ERROR, "is_error": True},
    {"name": "browser", "arguments": {"action": "click"},
     "output": "Timeout 30000ms exceeded", "is_error": True},
]


class _Fault:
    def __init__(self, **kw) -> None:
        self.id = kw.get("id", "f1")
        self.tool_id = kw.get("tool_id", "browser")
        self.signature = kw.get("signature", _SIG)
        self.error_text = kw.get("error_text", _ERROR)
        self.tool_trace_ref = kw.get("tool_trace_ref", "sha-1")


class _Executor:
    def __init__(self, result=None, raises=None) -> None:
        self.result = result if result is not None else ToolResult(output="ok")
        self.raises = raises
        self.calls: list[dict] = []

    async def invoke(self, *, agent_id, tool_id, params, **_kw):
        self.calls.append({"agent_id": agent_id, "tool_id": tool_id, "params": params})
        if self.raises is not None:
            raise self.raises
        return self.result


class _Store:
    def __init__(self, blob=None) -> None:
        self.blob = json.dumps(_TRACE).encode() if blob is None else blob

    async def read(self, _ref):
        return self.blob


class _Runtime:
    def __init__(self, blob=None, faults=None) -> None:
        self.attachment_store = _Store(blob)
        self.fault_report_store = faults


# ── recovering the failing arguments ──────────────────────────────


def test_the_failing_arguments_are_recovered_from_the_trace() -> None:
    """No schema change needed: the trace already holds what to retry."""
    assert find_failing_arguments(_TRACE, tool_id="browser", signature=_SIG) == _ARGS


def test_a_different_error_is_not_the_one_we_want() -> None:
    other = error_signature(tool_id="browser", error_text="something else")
    assert find_failing_arguments(_TRACE, tool_id="browser", signature=other) is None


def test_a_different_tool_is_not_the_one_we_want() -> None:
    assert find_failing_arguments(_TRACE, tool_id="run_python", signature=_SIG) is None


def test_the_last_matching_attempt_wins() -> None:
    """An agent that retried has the same args each time; the final attempt is
    the one it settled on."""
    trace = [
        {"name": "browser", "arguments": {"attempt": 1},
         "output": _ERROR, "is_error": True},
        {"name": "browser", "arguments": {"attempt": 2},
         "output": _ERROR, "is_error": True},
    ]
    found = find_failing_arguments(trace, tool_id="browser", signature=_SIG)
    assert found == {"attempt": 2}


@pytest.mark.parametrize("bad", [None, "x", 42, [], [None], [{"no": "keys"}]])
def test_a_malformed_trace_recovers_nothing(bad) -> None:
    assert find_failing_arguments(bad, tool_id="browser", signature=_SIG) is None


def test_an_unrecoverable_argument_dict_is_not_reported_as_a_signature_miss(
    caplog,
) -> None:
    """R1/R2: the diagnostic must not assert something it did not check.

    Executed against the round-2 build: an entry matching the name AND the
    signature but carrying a non-dict ``arguments`` still logged "none carries
    error signature", which is false -- that entry carried it. The two causes
    need different repairs (expose the tool's arguments vs. widen the trace
    output bound), so they are counted and worded separately.
    """
    trace = [
        {"name": "browser", "arguments": "not-a-dict",
         "output": _ERROR, "is_error": True},
    ]

    with caplog.at_level("DEBUG", logger="probos.cognitive.repair_verification"):
        assert find_failing_arguments(
            trace, tool_id="browser", signature=_SIG,
        ) is None

    assert "none has a recoverable argument dictionary" in caplog.text
    assert "none carries error signature" not in caplog.text


def test_a_signature_miss_still_says_so(caplog) -> None:
    """The other branch keeps its wording: named, but signed by nothing."""
    trace = [
        {"name": "browser", "arguments": {"action": "click"},
         "output": "a completely different failure", "is_error": True},
    ]

    with caplog.at_level("DEBUG", logger="probos.cognitive.repair_verification"):
        assert find_failing_arguments(
            trace, tool_id="browser", signature=_SIG,
        ) is None

    assert "none carries error signature" in caplog.text
    assert "none has a recoverable argument dictionary" not in caplog.text


# ── the three outcomes ────────────────────────────────────────────


async def test_a_successful_retry_is_repaired() -> None:
    """THE AD-1173 headline."""
    executor = _Executor(ToolResult(output="typed"))
    result = await verify_repair(
        runtime=_Runtime(), fault=_Fault(), tool_executor=executor,
    )
    assert result.outcome == "repaired"
    assert result.repaired is True
    assert result.retried is True
    # It retried the exact failing call.
    assert executor.calls[0]["tool_id"] == "browser"
    assert executor.calls[0]["params"] == _ARGS


async def test_the_same_error_again_is_unrepaired() -> None:
    result = await verify_repair(
        runtime=_Runtime(),
        fault=_Fault(),
        tool_executor=_Executor(ToolResult(error=_ERROR)),
    )
    assert result.outcome == "unrepaired"
    assert result.repaired is False


async def test_a_different_error_counts_as_repaired() -> None:
    """The REPORTED fault is gone even though the operation still fails. A new
    failure is a new fault, not this one."""
    result = await verify_repair(
        runtime=_Runtime(),
        fault=_Fault(),
        tool_executor=_Executor(ToolResult(error="a completely different problem")),
    )
    assert result.outcome == "repaired"
    assert "failed differently" in result.detail


async def test_an_unrecoverable_retry_is_inconclusive_not_repaired() -> None:
    """The outcome that matters most. Closing a fault because it could not be
    checked is how a broken tool returns to service."""
    result = await verify_repair(
        runtime=_Runtime(blob=b"[]"),  # trace has no matching call
        fault=_Fault(),
        tool_executor=_Executor(),
    )
    assert result.outcome == "inconclusive"
    assert result.repaired is False


async def test_a_raising_executor_is_inconclusive() -> None:
    result = await verify_repair(
        runtime=_Runtime(),
        fault=_Fault(),
        tool_executor=_Executor(raises=RuntimeError("boom")),
    )
    assert result.outcome == "inconclusive"
    assert result.repaired is False
    assert "RuntimeError" in result.detail


async def test_no_executor_is_inconclusive() -> None:
    result = await verify_repair(
        runtime=_Runtime(), fault=_Fault(), tool_executor=None,
    )
    assert result.outcome == "inconclusive"


async def test_a_fault_without_a_signature_is_inconclusive() -> None:
    result = await verify_repair(
        runtime=_Runtime(), fault=_Fault(signature=""), tool_executor=_Executor(),
    )
    assert result.outcome == "inconclusive"


async def test_no_trace_ref_is_inconclusive() -> None:
    result = await verify_repair(
        runtime=_Runtime(),
        fault=_Fault(tool_trace_ref=""),
        tool_executor=_Executor(),
    )
    assert result.outcome == "inconclusive"


# ── closing the loop ──────────────────────────────────────────────


async def test_a_verified_repair_closes_the_fault() -> None:
    store = FaultReportStore()
    filed = await store.file_fault(tool_id="browser", error_text=_ERROR)
    runtime = _Runtime(faults=store)

    result = await verify_and_close(
        runtime=runtime,
        fault=type("F", (), {
            "id": filed.id, "tool_id": "browser", "signature": filed.signature,
            "error_text": _ERROR, "tool_trace_ref": "sha-1",
        })(),
        tool_executor=_Executor(ToolResult(output="typed")),
    )

    assert result.repaired is True
    assert store.get(filed.id).status == "repaired"
    assert store.list_open() == []


async def test_an_unverified_repair_leaves_the_fault_open() -> None:
    store = FaultReportStore()
    filed = await store.file_fault(tool_id="browser", error_text=_ERROR)
    runtime = _Runtime(faults=store)

    result = await verify_and_close(
        runtime=runtime,
        fault=type("F", (), {
            "id": filed.id, "tool_id": "browser", "signature": filed.signature,
            "error_text": _ERROR, "tool_trace_ref": "sha-1",
        })(),
        tool_executor=_Executor(ToolResult(error=_ERROR)),
    )

    assert result.repaired is False
    assert store.get(filed.id).status == "open"
    assert len(store.list_open()) == 1


async def test_no_fault_store_still_returns_the_verdict() -> None:
    result = await verify_and_close(
        runtime=_Runtime(faults=None),
        fault=_Fault(),
        tool_executor=_Executor(ToolResult(output="ok")),
    )
    assert result.repaired is True


# ── the wording ───────────────────────────────────────────────────


def test_inconclusive_says_why_it_stays_open() -> None:
    rendered = VerificationResult(
        outcome="inconclusive", tool_id="browser", detail="No executor.",
    ).render()
    assert "stays open" in rendered
    assert "not a repair" in rendered


def test_each_outcome_reads_differently() -> None:
    rendered = {
        outcome: VerificationResult(outcome=outcome, tool_id="browser").render()
        for outcome in ("repaired", "unrepaired", "inconclusive")
    }
    assert len(set(rendered.values())) == 3
    assert "no longer returns" in rendered["repaired"]
    assert "still returns" in rendered["unrepaired"]
