"""AD-1267 (P1): a recurrence emits, so the repair threshold is reachable.

``_emit_fault`` had exactly two call sites -- the *create* branch of
``file_fault`` and ``resolve``. The coalesce branch persisted the increment and
returned without emitting, so every ``FAULT_REPORTED`` event carried
``occurrences=1`` while ``RepairDispatcher.on_fault_event`` requires
``>= propose_after_occurrences`` (default 2).

``FAULT_REPORTED`` had one emitter and one consumer, and the two could not
agree: at HEAD no repair proposal could ever be raised. These tests pin the
emission, not the threshold -- "once is a transient, twice is the tool" is
unchanged.
"""

from __future__ import annotations

from typing import Any

from probos.fault_report import FaultReportStore

_ERR = "unknown browser action: 'key_type'"
_OTHER = "target closed while typing"


class _Capture:
    """Records fault events for the TEST to read.

    Deliberately assertion-free. ``_emit_fault`` wraps the call in its own
    ``except Exception``, so an assertion raised in here is swallowed and the
    test passes whatever happened. Recording and asserting outside is the only
    shape that can fail.
    """

    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, Any]]] = []

    def __call__(self, event_type: Any, data: dict[str, Any]) -> None:
        self.events.append((getattr(event_type, "value", str(event_type)), dict(data)))

    def reported(self) -> list[dict[str, Any]]:
        return [data for name, data in self.events if name == "fault_reported"]

    def occurrences(self) -> list[int]:
        return [int(data["occurrences"]) for data in self.reported()]


async def test_a_recurrence_emits_with_the_post_increment_count() -> None:
    """THE P1 regression: the second occurrence must be observable, as 2."""
    cap = _Capture()
    store = FaultReportStore(emit_event=cap)

    await store.file_fault(tool_id="browser", error_text=_ERR)
    await store.file_fault(tool_id="browser", error_text=_ERR)

    assert cap.occurrences() == [1, 2]


async def test_every_recurrence_is_observable() -> None:
    cap = _Capture()
    store = FaultReportStore(emit_event=cap)

    for _ in range(5):
        await store.file_fault(tool_id="browser", error_text=_ERR)

    counts = cap.occurrences()
    assert counts == [1, 2, 3, 4, 5]
    assert max(counts) >= 2, (
        "RepairDispatcher.on_fault_event requires occurrences >= "
        "propose_after_occurrences (default 2); an emitter that never exceeds 1 "
        "makes the repair path unreachable"
    )


async def test_a_different_signature_starts_its_own_count() -> None:
    cap = _Capture()
    store = FaultReportStore(emit_event=cap)

    await store.file_fault(tool_id="browser", error_text=_ERR)
    await store.file_fault(tool_id="browser", error_text=_OTHER)
    await store.file_fault(tool_id="browser", error_text=_OTHER)

    assert cap.occurrences() == [1, 1, 2]


async def test_a_resolved_fault_that_recurs_is_a_new_report() -> None:
    """A repair that did not hold is a new fault, not occurrence 3 of the old."""
    cap = _Capture()
    store = FaultReportStore(emit_event=cap)

    first = await store.file_fault(tool_id="browser", error_text=_ERR)
    await store.resolve(first.signature, status="repaired", resolution="BF-701")
    second = await store.file_fault(tool_id="browser", error_text=_ERR)

    assert second.id != first.id
    assert second.occurrences == 1
    assert cap.occurrences() == [1, 1]


async def test_an_emit_failure_still_lets_the_turn_finish() -> None:
    """``file_fault``'s "never raises" contract survives the new emit site."""

    def _boom(*_args: Any, **_kwargs: Any) -> None:
        raise RuntimeError("event bus down")

    store = FaultReportStore(emit_event=_boom)

    first = await store.file_fault(tool_id="browser", error_text=_ERR)
    second = await store.file_fault(tool_id="browser", error_text=_ERR)

    assert second is first
    assert second.occurrences == 2
    assert second.status == "open"


async def test_the_adoption_branch_still_emits() -> None:
    """The emit sits AFTER the AD-1269 absent -> present trace adoption."""
    cap = _Capture()
    store = FaultReportStore(emit_event=cap)

    first = await store.file_fault(
        tool_id="browser", error_text=_ERR, tool_trace_ref=None,
    )
    assert first.tool_trace_ref is None, "premise: there is nothing to adopt yet"

    second = await store.file_fault(
        tool_id="browser", error_text=_ERR, tool_trace_ref="trace-abc123",
    )

    assert second.tool_trace_ref == "trace-abc123", (
        "premise: the AD-1269 adoption branch must have run, or this test says "
        "nothing about emitting from it"
    )
    assert cap.occurrences() == [1, 2]
