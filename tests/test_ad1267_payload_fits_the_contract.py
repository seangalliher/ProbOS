"""AD-1267 (P5): an ordinary fault must be proposable at all.

Two contract mismatches made a normal report permanently unfileable:

- ``fault_report._THREAD_ID_MAX`` is 128 and ``capability_request._THREAD_ID_MAX``
  is 64, and ``_file_dispatch_request`` forwarded ``brief.thread_id`` unchanged.
  A 128-char thread id failed ``validate_action_payload``, so
  ``file_action_request`` returned ``None`` -- no request, ever.
- ``resolve_targets`` was unbounded while the canonical payload is capped at
  ``_ACTION_PAYLOAD_MAX_CHARS`` (4000).

Fixed at each source, and the fit is then *asserted* rather than *fitted*: a
truncating binary-search helper for a case the bounds make unreachable would be
machinery for an impossible state.
"""

from __future__ import annotations

import json
import logging
from types import SimpleNamespace
from typing import Any

from probos.capability_request import (
    THREAD_ID_MAX_CHARS,
    CapabilityRequestStore,
    validate_action_payload,
)
from probos.cognitive.repair_brief import (
    _TARGET_NAME_MAX,
    _TARGETS_MAX,
    build_repair_brief,
    resolve_targets,
)
from probos.cognitive.repair_dispatch import RepairDispatcher
from probos.config import RepairConfig
from probos.fault_report import FaultReportStore

_ERR = "unknown browser action: 'key_type'"
_LONG_THREAD_ID = "t" * 128


class _Fault:
    def __init__(self, **kw: Any) -> None:
        self.id = kw.get("id", "f1")
        self.tool_id = kw.get("tool_id", "browser")
        self.signature = kw.get("signature", "a" * 64)
        self.error_text = kw.get("error_text", _ERR)
        self.occurrences = kw.get("occurrences", 2)
        self.attempted = kw.get("attempted", "type Hello into the document")
        self.agent_id = kw.get("agent_id", "counselor-ezri")
        self.thread_id = kw.get("thread_id", _LONG_THREAD_ID)
        self.tool_trace_ref = kw.get("tool_trace_ref", "")


class _Faults:
    def __init__(self, fault: Any) -> None:
        self.fault = fault

    def get(self, _sig: str) -> Any:
        return self.fault


class _Recorder:
    def __init__(self) -> None:
        self.filed: list[dict[str, Any]] = []

    async def file_action_request(
        self, *, agent_id: str, payload: dict, rationale: str = "",
        work_item_id: str | None = None,
    ) -> Any:
        self.filed.append({
            "agent_id": agent_id, "payload": payload, "rationale": rationale,
        })
        return SimpleNamespace(id=f"req{len(self.filed)}")


def _event(**data: Any) -> dict[str, Any]:
    base = {"signature": "a" * 64, "occurrences": 2, "tool_id": "browser"}
    base.update(data)
    return {"type": "fault_reported", "data": base}


async def _file(fault: Any, *, targets: list[str] | None = None) -> dict[str, Any]:
    recorder = _Recorder()
    dispatcher = RepairDispatcher(
        runtime=SimpleNamespace(attachment_store=None),
        fault_report_store=_Faults(fault),
        capability_request_store=recorder,
        config=RepairConfig(enabled=True, targets=targets or ["architect"]),
    )
    await dispatcher.on_fault_event(_event())
    assert recorder.filed, "premise: the dispatcher must have reached the store"
    return recorder.filed[0]


# ── the thread-id contract ────────────────────────────────────────


async def test_an_ordinary_fault_with_a_128_char_thread_id_is_accepted() -> None:
    """THE P5 regression: 128 is an ORDINARY fault report, not an edge case."""
    payload = (await _file(_Fault(thread_id=_LONG_THREAD_ID)))["payload"]

    assert validate_action_payload(payload) is not None, (
        "the fault-report thread_id bound is 128 and the action-approval bound "
        "is 64; forwarding the wider value means no request is ever filed"
    )


async def test_the_thread_id_is_narrowed_not_dropped(tmp_path: Any) -> None:
    """Narrowed to the consumer's contract; the full value stays one lookup away."""
    faults = FaultReportStore(db_path=str(tmp_path / "faults.db"))
    await faults.start()
    try:
        await faults.file_fault(
            tool_id="browser", error_text=_ERR, thread_id=_LONG_THREAD_ID,
        )
        report = await faults.file_fault(
            tool_id="browser", error_text=_ERR, thread_id=_LONG_THREAD_ID,
        )
        assert len(report.thread_id) == 128, "premise: the report keeps all 128"

        recorder = _Recorder()
        dispatcher = RepairDispatcher(
            runtime=SimpleNamespace(attachment_store=None),
            fault_report_store=faults,
            capability_request_store=recorder,
            config=RepairConfig(enabled=True),
        )
        await dispatcher.on_fault_event(_event(signature=report.signature))
        payload = recorder.filed[0]["payload"]

        assert payload["thread_id"] == _LONG_THREAD_ID[:THREAD_ID_MAX_CHARS]
        assert len(payload["thread_id"]) == 64
        assert payload["thread_id"], "narrowed, not dropped"

        resolved = faults.get(payload["params"]["fault_id"])
        assert resolved is not None
        assert resolved.thread_id == _LONG_THREAD_ID
    finally:
        await faults.stop()


# ── the target bounds ─────────────────────────────────────────────


def test_targets_are_clipped_to_eight_by_sixty_four(caplog: Any) -> None:
    declared = [f"harness-{index}-{'x' * 80}" for index in range(12)]

    with caplog.at_level(logging.WARNING, logger="probos.cognitive.repair_brief"):
        targets = resolve_targets(RepairConfig(targets=declared))

    assert len(targets) == _TARGETS_MAX
    assert all(len(name) == _TARGET_NAME_MAX for name in targets)
    assert list(targets) == [
        name[:_TARGET_NAME_MAX] for name in declared[:_TARGETS_MAX]
    ], "declared order is preserved"

    warnings = [
        r for r in caplog.records
        if r.levelno == logging.WARNING and "AD-1267" in r.getMessage()
    ]
    assert len(warnings) == 1, f"expected one WARNING, got {len(warnings)}"
    assert "4" in warnings[0].getMessage(), "names how many were dropped"


def test_an_ordinary_target_list_is_untouched_and_silent(caplog: Any) -> None:
    with caplog.at_level(logging.WARNING, logger="probos.cognitive.repair_brief"):
        targets = resolve_targets(RepairConfig(targets=["architect", "copilot"]))

    assert targets == ("architect", "copilot")
    assert [r for r in caplog.records if "AD-1267" in r.getMessage()] == []


async def test_a_maximal_fault_still_fits() -> None:
    """The assertion that replaces the fitter.

    Every field at its documented maximum. If a future field pushes the
    canonical payload over 4000, this says so and names the number.
    """
    maximal = _Fault(
        tool_id="t" * 128,          # fault_report._TOOL_ID_MAX
        signature="f" * 64,         # sha256 hex
        error_text="e" * 2000,      # fault_report._ERROR_MAX
        attempted="a" * 1000,       # fault_report._ATTEMPTED_MAX
        agent_id="g" * 128,         # fault_report._AGENT_ID_MAX
        thread_id="t" * 128,        # fault_report._THREAD_ID_MAX
        tool_trace_ref="r" * 128,   # fault_report._TRACE_REF_MAX
        occurrences=999_999,
    )
    targets = [f"{index}{'n' * 80}" for index in range(_TARGETS_MAX)]

    payload = (await _file(maximal, targets=targets))["payload"]
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"),
                         ensure_ascii=False)

    assert validate_action_payload(payload) is not None, (
        f"a maximal fault's canonical payload is {len(encoded)} chars against "
        "the 4000-char _ACTION_PAYLOAD_MAX_CHARS bound"
    )
    assert len(payload["params"]["targets"].split(",")) == _TARGETS_MAX


# ── the payload carries identity only ─────────────────────────────


async def test_the_brief_in_the_payload_has_no_occurrence_count() -> None:
    fault = _Fault(occurrences=7)
    payload = (await _file(fault))["payload"]
    brief = build_repair_brief(fault)

    assert "7 time(s)" in brief.render_markdown(), (
        "premise: the portable artifact still tells a human the count"
    )
    assert "7 time(s)" not in payload["params"]["brief"]
    assert "What is wrong" in payload["params"]["brief"], (
        "premise: the payload brief is a real brief, not an empty string"
    )


async def test_the_brief_in_the_payload_has_no_trace() -> None:
    fault = _Fault(tool_trace_ref="tr-abc123def456")
    payload = (await _file(fault))["payload"]
    brief = build_repair_brief(fault, trace_summary="4 of 6 calls failed.")

    markdown = brief.render_markdown()
    assert "Evidence from the run" in markdown, "premise: the artifact keeps it"
    assert "- Tool trace: `tr-abc123def456`" in markdown

    payload_brief = payload["params"]["brief"]
    assert "Evidence from the run" not in payload_brief
    assert "Tool trace" not in payload_brief
    assert "tr-abc123def456" not in payload_brief
    assert "Provenance" in payload_brief, (
        "premise: the rest of the provenance block still renders"
    )


async def test_the_rationale_still_tells_the_captain_the_count(
    tmp_path: Any,
) -> None:
    record = await _file(_Fault(occurrences=7))
    assert "7 times" in record["rationale"]

    store = CapabilityRequestStore(db_path=str(tmp_path / "approvals.db"))
    await store.start()
    try:
        first = await store.file_action_request(
            agent_id="counselor-ezri", payload=record["payload"],
            rationale="failed 7 times",
        )
        second = await store.file_action_request(
            agent_id="counselor-ezri", payload=record["payload"],
            rationale="failed 8 times",
        )
        assert first is not None and second is not None
        assert second.id == first.id, (
            "rationale is not key material; two filings differing only in it "
            "must dedup onto one pending request"
        )
        assert len(await store.list_pending()) == 1
    finally:
        await store.stop()


async def test_the_payload_keys_are_exactly_the_four() -> None:
    payload = (await _file(_Fault()))["payload"]
    assert set(payload["params"]) == {
        "fault_id", "signature", "targets", "brief",
    }
