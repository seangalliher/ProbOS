"""AD-1267: at most ONE pending repair approval exists per fault report.

Across restarts, across concurrent recurrences, and across trace adoption.

Three defects conspired to break that guarantee, and each has its own
reproduction here:

- **P2** the in-process guard was marked *after* the await, and
  ``runtime._emit_event_local`` spawns an independent task per coroutine
  listener, so N recurrences all passed the check before any of them marked.
- **P3** ``action_dedup_key`` hashes ``params`` whole and the brief rendered the
  occurrence count verbatim, so occurrence 2 and occurrence 3 were *different
  keys* and the store's own dedup never matched. No restart required.
- **P4** the AD-1269 coalesce branch adopts a ``tool_trace_ref`` absent ->
  present, and the trace reached the brief twice (the evidence section and the
  provenance line), so a fault whose third occurrence carried a trace drifted
  even with the count removed.

What this does NOT claim: a fault whose approval has been *decided* can raise a
new approval on its next recurrence. That is AD-1268.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest

from probos.capability_request import CapabilityRequestStore, action_dedup_key
from probos.cognitive.repair_dispatch import RepairDispatcher
from probos.config import RepairConfig
from probos.fault_report import FaultReportStore

_ERR = "unknown browser action: 'key_type'"


# ── doubles ───────────────────────────────────────────────────────


class _Fault:
    def __init__(self, **kw: Any) -> None:
        self.id = kw.get("id", "f1")
        self.tool_id = kw.get("tool_id", "browser")
        self.signature = kw.get("signature", "a" * 64)
        self.error_text = kw.get("error_text", _ERR)
        self.occurrences = kw.get("occurrences", 2)
        self.attempted = kw.get("attempted", "type Hello into the document")
        self.agent_id = kw.get("agent_id", "counselor-ezri")
        self.thread_id = kw.get("thread_id", "thread-1")
        self.tool_trace_ref = kw.get("tool_trace_ref", "")


class _Faults:
    def __init__(self, fault: Any = None) -> None:
        self.fault = fault

    def get(self, _sig: str) -> Any:
        return self.fault


class _Recorder:
    """Records filings. Never dedups -- the durable store's job, not a fake's."""

    def __init__(self) -> None:
        self.filed: list[dict[str, Any]] = []

    async def file_action_request(
        self, *, agent_id: str, payload: dict, rationale: str = "",
        work_item_id: str | None = None,
    ) -> Any:
        self.filed.append({
            "agent_id": agent_id, "payload": payload,
            "rationale": rationale, "work_item_id": work_item_id,
        })
        return SimpleNamespace(id=f"req{len(self.filed)}")


class _Parking:
    """Parks inside ``file_action_request`` until the test releases it."""

    def __init__(self) -> None:
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self.calls = 0
        self.filed = 0

    async def file_action_request(self, **_kw: Any) -> Any:
        self.calls += 1
        self.entered.set()
        await self.release.wait()
        self.filed += 1
        return SimpleNamespace(id=f"req{self.filed}")


class _CommitsThenRaises:
    """Delegates to the real store, then raises on the FIRST call only.

    Models ``file_request``'s commit-then-emit shape: the row is durably
    committed before the emit can blow up.
    """

    def __init__(self, inner: CapabilityRequestStore) -> None:
        self._inner = inner
        self.raised = 0

    async def file_action_request(self, **kw: Any) -> Any:
        request = await self._inner.file_action_request(**kw)
        if self.raised == 0:
            self.raised += 1
            raise RuntimeError("the FILED emit blew up after the row committed")
        return request


def _event(kind: str = "fault_reported", **data: Any) -> dict[str, Any]:
    base = {"signature": "a" * 64, "occurrences": 2, "tool_id": "browser"}
    base.update(data)
    return {"type": kind, "data": base}


def _dispatcher(*, requests: Any, fault: Any = None, **cfg: Any) -> RepairDispatcher:
    return RepairDispatcher(
        runtime=SimpleNamespace(attachment_store=None),
        fault_report_store=_Faults(fault if fault is not None else _Fault()),
        capability_request_store=requests,
        config=RepairConfig(enabled=True, **cfg),
    )


# ── the end-to-end rig: real stores, real dispatcher ──────────────


class _Rig:
    """Real ``FaultReportStore`` -> real ``RepairDispatcher`` -> real store.

    The fault store's ``emit_event`` records the listener-shaped event that
    ``runtime._emit_event`` would build, and :meth:`drain` replays it into the
    dispatcher in order. That is the seam this AD lives on -- a test that stubs
    either half proves nothing about the chain.
    """

    def __init__(self, faults: Any, requests: Any, dispatcher: Any) -> None:
        self.faults = faults
        self.requests = requests
        self.dispatcher = dispatcher
        self.fault_events: list[dict[str, Any]] = []
        self.request_events: list[tuple[str, dict[str, Any]]] = []

    def on_fault(self, event_type: Any, data: dict[str, Any]) -> None:
        self.fault_events.append({
            "type": getattr(event_type, "value", str(event_type)),
            "data": dict(data),
        })

    def on_request(self, event_type: Any, data: dict[str, Any]) -> None:
        self.request_events.append(
            (getattr(event_type, "value", str(event_type)), dict(data))
        )

    async def file(self, **kw: Any) -> Any:
        kw.setdefault("tool_id", "browser")
        kw.setdefault("error_text", _ERR)
        return await self.faults.file_fault(**kw)

    async def drain(self) -> list[dict[str, Any]]:
        """Replay every captured fault event into the dispatcher, in order."""
        pending, self.fault_events = self.fault_events, []
        for event in pending:
            await self.dispatcher.on_fault_event(event)
        return pending

    async def file_and_drain(self, **kw: Any) -> list[dict[str, Any]]:
        """File one occurrence and dispatch it before the next one arrives.

        Production shape: ``runtime._emit_event_local`` spawns the listener task
        at emit time, so it runs against the report as it was THEN. Batching all
        the filings and draining once at the end would hand every replay the
        same final occurrence count -- which is exactly the value under test, so
        that shape cannot detect an unstable key and passes either way.
        """
        await self.file(**kw)
        return await self.drain()

    async def pending_actions(self) -> list[Any]:
        return [
            r for r in await self.requests.list_pending() if r.kind == "action"
        ]

    def filed_notices(self) -> list[tuple[str, dict[str, Any]]]:
        return [e for e in self.request_events if e[0] == "capability_request_filed"]


async def _rig(tmp_path: Any, **cfg: Any) -> _Rig:
    rig = _Rig(None, None, None)  # type: ignore[arg-type]
    faults = FaultReportStore(
        db_path=str(tmp_path / "faults.db"), emit_event=rig.on_fault,
    )
    await faults.start()
    requests = CapabilityRequestStore(
        db_path=str(tmp_path / "approvals.db"), emit_event=rig.on_request,
    )
    await requests.start()
    rig.faults = faults
    rig.requests = requests
    rig.dispatcher = RepairDispatcher(
        runtime=SimpleNamespace(attachment_store=None),
        fault_report_store=faults,
        capability_request_store=requests,
        config=RepairConfig(enabled=True, **cfg),
    )
    return rig


async def _close(rig: _Rig) -> None:
    await rig.faults.stop()
    await rig.requests.stop()


# ── P3: the key is stable across occurrence counts ────────────────


async def _payload_at(occurrences: int, **fault_kw: Any) -> dict[str, Any]:
    """The payload the REAL ``_file_dispatch_request`` path builds."""
    recorder = _Recorder()
    dispatcher = _dispatcher(
        requests=recorder, fault=_Fault(occurrences=occurrences, **fault_kw),
    )
    await dispatcher.on_fault_event(_event(occurrences=occurrences))
    assert recorder.filed, (
        "premise: the dispatcher must have reached the store, or the key "
        "comparison below compares nothing"
    )
    return recorder.filed[0]["payload"]


async def test_the_key_is_stable_across_occurrence_counts() -> None:
    """P3: occurrence 2 and occurrence 3 must hash to ONE key."""
    at_two = await _payload_at(2)
    at_three = await _payload_at(3)

    key_two = action_dedup_key(
        agent_id="counselor-ezri", payload=at_two, work_item_id=None,
    )
    key_three = action_dedup_key(
        agent_id="counselor-ezri", payload=at_three, work_item_id=None,
    )

    assert at_two["params"] == at_three["params"]
    assert key_two == key_three, (
        "the occurrence count reached params, so one fault raises one approval "
        "per occurrence"
    )


async def test_the_key_is_stable_across_trace_adoption(tmp_path: Any) -> None:
    """P4: the AD-1269 absent -> present trace adoption must not move the key."""
    rig = await _rig(tmp_path)
    try:
        await rig.file_and_drain(tool_trace_ref=None)
        await rig.file_and_drain(tool_trace_ref=None)

        first = await rig.pending_actions()
        assert len(first) == 1, "premise: occurrence 2 must have filed"
        assert "trace" not in first[0].payload["params"]["brief"].lower(), (
            "premise: there is no trace in the record yet, so what follows is "
            "testing the adoption and not a value that was always there"
        )
        key_before = action_dedup_key(
            agent_id=first[0].agent_id,
            payload=first[0].payload,
            work_item_id=first[0].work_item_id,
        )

        await rig.file(tool_trace_ref="trace-abc123")
        adopted = rig.faults.get(first[0].payload["params"]["fault_id"])
        assert adopted is not None
        assert adopted.tool_trace_ref == "trace-abc123", (
            "premise: the AD-1269 absent -> present adoption branch must have run"
        )
        await rig.drain()

        after = await rig.pending_actions()
        assert len(after) == 1
        assert after[0].id == first[0].id
        assert action_dedup_key(
            agent_id=after[0].agent_id,
            payload=after[0].payload,
            work_item_id=after[0].work_item_id,
        ) == key_before
    finally:
        await _close(rig)


# ── the guarantee, end to end ─────────────────────────────────────


async def test_occurrences_two_three_and_seven_file_one_approval(
    tmp_path: Any,
) -> None:
    """Seven recurrences of one fault. One decision for the Captain."""
    rig = await _rig(tmp_path)
    try:
        first = await rig.file_and_drain()
        assert len(first) == 1, "premise: occurrence 1 emitted"
        assert await rig.pending_actions() == [], (
            "once is a transient: occurrence 1 must file nothing"
        )

        counts = [int(first[0]["data"]["occurrences"])]
        for _ in range(6):
            replayed = await rig.file_and_drain()
            counts += [int(e["data"]["occurrences"]) for e in replayed]

        assert counts == [1, 2, 3, 4, 5, 6, 7], (
            f"premise: each event must be dispatched while the live report still "
            f"carries ITS own count, got {counts}"
        )
        assert len([c for c in counts if c >= 2]) >= 3, (
            "premise: at least three events must cross the threshold, or "
            "'one approval' would just mean 'the path never ran'"
        )

        pending = await rig.pending_actions()
        assert len(pending) == 1
        assert pending[0].payload["params"]["fault_id"]
    finally:
        await _close(rig)


async def test_the_approval_survives_a_restart(tmp_path: Any) -> None:
    """The #1315 reproduction: 1 pending -> restart -> still 1 pending."""
    rig = await _rig(tmp_path)
    try:
        await rig.file_and_drain()
        await rig.file_and_drain()
        before = await rig.pending_actions()
        assert len(before) == 1, "premise: occurrence 2 must have filed"
        original_id = before[0].id
        db_path = rig.requests.db_path
    finally:
        await rig.requests.stop()

    restarted = CapabilityRequestStore(db_path=db_path)
    await restarted.start()
    try:
        rig.requests = restarted
        rig.dispatcher._requests = restarted
        assert len(await rig.pending_actions()) == 1, (
            "premise: _refresh_cache must have reloaded the committed row"
        )

        await rig.file_and_drain()

        after = await rig.pending_actions()
        assert len(after) == 1
        assert after[0].id == original_id
    finally:
        await restarted.stop()
        await rig.faults.stop()


async def test_concurrent_recurrences_file_one_approval() -> None:
    """P2: the storm. The guard is taken BEFORE the await, so N tasks file once.

    No sleep, and deliberately NOT "park until N callers are inside together" --
    once the guard works, a second caller can never get inside, so that
    rendezvous would deadlock on its own success. The honest shape is: park the
    one caller that got in, run the rest to completion WHILE it is parked, and
    count how many reached the store.
    """
    store = _Parking()
    dispatcher = _dispatcher(requests=store)
    event = _event(occurrences=9)

    first = asyncio.create_task(dispatcher.on_fault_event(event))
    await asyncio.wait_for(store.entered.wait(), 5.0)
    assert dispatcher._inflight, "premise: the guard is held during the filing"

    others = [
        asyncio.create_task(dispatcher.on_fault_event(event)) for _ in range(5)
    ]
    await asyncio.gather(*others)

    assert store.calls == 1, (
        "five concurrent recurrences reached the store while one filing was in "
        "flight; that is one Captain approval per occurrence"
    )

    store.release.set()
    await first
    assert store.filed == 1
    assert dispatcher._inflight == set()

    # A guard that never releases passes everything above. This half is what
    # distinguishes "released" from "permanently stuck".
    await dispatcher.on_fault_event(event)
    assert store.calls == 2


async def test_a_filing_that_commits_then_raises_does_not_file_twice(
    tmp_path: Any,
) -> None:
    """DD-2: release anyway -- the row is committed, so the next event dedups."""
    rig = await _rig(tmp_path)
    try:
        exploding = _CommitsThenRaises(rig.requests)
        rig.dispatcher._requests = exploding

        await rig.file_and_drain()
        await rig.file_and_drain()

        assert exploding.raised == 1, "premise: the filing must have raised"
        assert rig.dispatcher._inflight == set(), (
            "a reservation that is also the record cannot be released"
        )
        committed = await rig.pending_actions()
        assert len(committed) == 1, "premise: the row committed before the raise"

        rig.dispatcher._requests = rig.requests
        await rig.file_and_drain()

        after = await rig.pending_actions()
        assert len(after) == 1
        assert after[0].id == committed[0].id
    finally:
        await _close(rig)


async def test_a_cancelled_filing_releases_the_guard() -> None:
    """Cancellation propagates and the ``finally`` still runs."""
    store = _Parking()
    dispatcher = _dispatcher(requests=store)

    task = asyncio.create_task(dispatcher.on_fault_event(_event(occurrences=9)))
    await asyncio.wait_for(store.entered.wait(), 5.0)
    assert dispatcher._inflight, (
        "premise: the body actually RAN and reached the await -- a create_task "
        "plus an immediate cancel never executes it and cannot fail"
    )

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert dispatcher._inflight == set()


async def test_a_resolved_fault_that_recurs_can_propose_again(
    tmp_path: Any,
) -> None:
    """DD-5(1): a new fault id is a new identity, so it may ask again."""
    rig = await _rig(tmp_path)
    try:
        await rig.file_and_drain()
        first_report = await rig.file()
        await rig.drain()
        first = await rig.pending_actions()
        assert len(first) == 1, "premise: the original fault filed"

        await rig.faults.resolve(
            first_report.signature, status="repaired", resolution="BF-701",
        )
        await rig.drain()

        await rig.file_and_drain()
        await rig.file_and_drain()

        after = await rig.pending_actions()
        assert len(after) == 2
        ids = {r.payload["params"]["fault_id"] for r in after}
        assert len(ids) == 2, (
            f"the recurrence must carry a NEW fault id, got {ids}"
        )
    finally:
        await _close(rig)


async def test_one_captain_notice_per_fault(tmp_path: Any) -> None:
    """``CAPABILITY_REQUEST_FILED`` drives a Captain DM. Exactly one per fault."""
    rig = await _rig(tmp_path)
    try:
        for _ in range(7):
            await rig.file_and_drain()

        assert len(await rig.pending_actions()) == 1, (
            "premise: occurrences 2..7 must have deduped onto one request"
        )
        notices = rig.filed_notices()
        assert len(notices) >= 1, "premise: the notice fired at all"
        assert len(notices) == 1, (
            f"occurrences 2..7 produced {len(notices)} Captain notices; a dedup "
            "returns before file_request and must emit nothing"
        )
    finally:
        await _close(rig)
