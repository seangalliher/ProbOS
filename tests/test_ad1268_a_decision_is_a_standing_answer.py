"""AD-1268: a decision is a standing answer, so a refused repair is not asked again.

AD-1267 made the approval store the durable owner of repair-proposal identity,
but its dedup runs through ``_find_pending_action``, which skips anything
already decided. So its guarantee stopped at *pending*: a fault whose approval
the Captain DENIED raised a fresh one on its next recurrence, and the one after
that. Measured against post-AD-1267 HEAD, real stores on disk, every premise
asserted::

    PREMISE 1  a first approval exists after occurrence 2: True
    PREMISE 2  the Captain's denial is recorded: True
    PREMISE 3  nothing is pending immediately after the denial: True
      occurrence 3: pending action requests = 1
      occurrence 4: pending action requests = 1
      occurrence 5: pending action requests = 1
    rows by status : {'denied': 1, 'pending': 1}

One rule closes it: **a fault report that has ever raised a decided approval
does not raise another.** The escape hatch is resolution, not a timer — a
resolved fault that recurs takes ``file_fault``'s create branch and arrives with
a new id, so it asks cleanly.

The cost, stated rather than hidden: a repair that was dispatched and did NOT
hold will not automatically ask again. The fault stays open, keeps incrementing
and keeps emitting, but raises no new approval until the report is resolved or
dismissed. That is deliberate — ask -> approve -> dispatch -> fail -> ask spends
deep-tier tokens on a repair already known not to work, which is the harm the
approval gate exists to prevent.
"""

from __future__ import annotations

import logging
import math
from types import SimpleNamespace
from typing import Any

import pytest

from probos.capability_request import CapabilityRequestStore
from probos.cognitive.repair_dispatch import (
    REPAIR_ACTION,
    REPAIR_TOOL_ID,
    RepairDispatcher,
)
from probos.config import RepairConfig
from probos.fault_report import FaultReportStore

_ERR = "unknown browser action: 'key_type'"

_DECIDED = ("approved", "denied", "fulfilled", "failed")


def _action_payload(fault_id: str, **overrides: Any) -> dict[str, Any]:
    """A well-formed AD-1154 action payload naming ``fault_id``."""
    payload: dict[str, Any] = {
        "tool_id": "repair",
        "action": "dispatch",
        "params": {"fault_id": fault_id, "signature": "s" * 64},
        "scope_key": "browser",
        "session_id": None,
        "thread_id": "thread-1",
    }
    payload.update(overrides)
    return payload


class _NoLookupStore:
    """An AD-1267-era store: it files and dedups on pending, and nothing more.

    Delegates ``file_action_request`` to the real store so pending dedup still
    works, but exposes no ``find_action_requests_by_param``, which is what the
    dispatcher's ``hasattr`` guard has to tolerate.
    """

    def __init__(self, inner: CapabilityRequestStore) -> None:
        self._inner = inner

    async def file_action_request(self, **kw: Any) -> Any:
        return await self._inner.file_action_request(**kw)


# ── the rig: real fault store -> real dispatcher -> real approval store ──


class _Rig:
    """The whole seam, with nothing stubbed on either side of it.

    ``FaultReportStore.emit_event`` records the listener-shaped event that
    ``runtime._emit_event`` would build, and :meth:`drain` replays it into the
    dispatcher in order — matching production, where
    ``_emit_event_local`` spawns the listener task at emit time and it therefore
    runs against the report as it was THEN.
    """

    def __init__(self) -> None:
        self.faults: Any = None
        self.requests: Any = None
        self.dispatcher: Any = None
        self.fault_events: list[dict[str, Any]] = []

    def on_fault(self, event_type: Any, data: dict[str, Any]) -> None:
        self.fault_events.append({
            "type": getattr(event_type, "value", str(event_type)),
            "data": dict(data),
        })

    async def file(self, **kw: Any) -> Any:
        kw.setdefault("tool_id", "browser")
        kw.setdefault("error_text", _ERR)
        kw.setdefault("agent_id", "counselor-ezri")
        return await self.faults.file_fault(**kw)

    async def drain(self) -> list[int]:
        """Replay every captured event; return the reported occurrence counts."""
        pending, self.fault_events = self.fault_events, []
        counts: list[int] = []
        for event in pending:
            await self.dispatcher.on_fault_event(event)
            if event["type"] == "fault_reported":
                counts.append(int(event["data"].get("occurrences") or 0))
        return counts

    async def recur(self, times: int) -> list[int]:
        """File ``times`` more occurrences, dispatching each before the next."""
        counts: list[int] = []
        for _ in range(times):
            await self.file()
            counts += await self.drain()
        return counts

    async def pending_actions(self) -> list[Any]:
        return [
            r for r in await self.requests.list_pending() if r.kind == "action"
        ]

    def actions_for(self, fault_id: str) -> list[Any]:
        """Every action request ever filed for this fault, in any status."""
        return self.requests.find_action_requests_by_param("fault_id", fault_id)


def _dispatcher(faults: Any, requests: Any, **cfg: Any) -> RepairDispatcher:
    return RepairDispatcher(
        runtime=SimpleNamespace(attachment_store=None),
        fault_report_store=faults,
        capability_request_store=requests,
        config=RepairConfig(enabled=True, **cfg),
    )


async def _rig(tmp_path: Any, **cfg: Any) -> _Rig:
    rig = _Rig()
    rig.faults = FaultReportStore(
        db_path=str(tmp_path / "faults.db"), emit_event=rig.on_fault,
    )
    await rig.faults.start()
    rig.requests = CapabilityRequestStore(db_path=str(tmp_path / "approvals.db"))
    await rig.requests.start()
    rig.dispatcher = _dispatcher(rig.faults, rig.requests, **cfg)
    return rig


async def _close(rig: _Rig) -> None:
    await rig.faults.stop()
    await rig.requests.stop()


async def _first_approval(rig: _Rig) -> Any:
    """Drive to occurrence 2 and return the single approval it raises."""
    counts = await rig.recur(2)
    assert counts == [1, 2], (
        f"premise: two occurrences must have been dispatched while each still "
        f"carried its own count, got {counts}"
    )
    pending = await rig.pending_actions()
    assert len(pending) == 1, (
        "premise: occurrence 2 must have raised exactly one approval, or "
        "everything below is testing a path that never ran"
    )
    return pending[0]


async def _decide(rig: _Rig, request: Any, *, approve: bool) -> Any:
    decided = await rig.requests.decide(
        request.id, approve=approve, reason="the Captain answered",
    )
    assert decided is not None, "premise: the decision must have been recorded"
    return decided


# ── DD-1: any decision is a standing answer ──────────────────────────────


async def test_a_denied_repair_is_not_proposed_again(tmp_path: Any) -> None:
    """The reproduction from the module docstring, now closed."""
    rig = await _rig(tmp_path)
    try:
        first = await _first_approval(rig)
        fault_id = first.payload["params"]["fault_id"]

        denied = await _decide(rig, first, approve=False)
        assert denied.status == "denied", "premise: the denial must be recorded"
        assert await rig.pending_actions() == [], (
            "premise: nothing is pending immediately after the denial"
        )

        counts = await rig.recur(3)
        assert counts == [3, 4, 5], (
            f"premise: three further events must have crossed the threshold of "
            f"2, or 'no new approval' would just mean the path never ran, got "
            f"{counts}"
        )

        assert await rig.pending_actions() == []
        assert [r.id for r in rig.actions_for(fault_id)] == [first.id], (
            "the Captain answered; the ship must not ask again, in any status"
        )
    finally:
        await _close(rig)


async def test_an_approved_repair_is_not_proposed_again_while_it_is_in_flight(
    tmp_path: Any,
) -> None:
    """An approved dispatch is already in flight; asking again is noise."""
    rig = await _rig(tmp_path)
    try:
        first = await _first_approval(rig)
        fault_id = first.payload["params"]["fault_id"]

        approved = await _decide(rig, first, approve=True)
        assert approved.status == "approved", "premise: the approval is recorded"
        assert await rig.pending_actions() == []

        counts = await rig.recur(3)
        assert counts == [3, 4, 5], f"premise: the threshold was crossed, got {counts}"

        assert await rig.pending_actions() == []
        assert [r.id for r in rig.actions_for(fault_id)] == [first.id]
    finally:
        await _close(rig)


async def test_a_fulfilled_repair_is_not_proposed_again(tmp_path: Any) -> None:
    """The deliberate cost in DD-1, pinned so a future reader sees it was chosen.

    A repair that ran and did NOT hold leaves the fault open and reporting, and
    this suppresses the re-ask. The alternative is ask -> approve -> dispatch ->
    fail -> ask, spending deep-tier tokens on a repair already known not to
    work. A visible, non-escalating fault is the better failure; the escape
    hatch is resolving the report, which ``repair_verification.verify_and_close``
    does for free on the path where the repair DID hold.
    """
    rig = await _rig(tmp_path)
    try:
        first = await _first_approval(rig)
        fault_id = first.payload["params"]["fault_id"]

        await _decide(rig, first, approve=True)
        fulfilled = await rig.requests.mark_fulfilled(first.id)
        assert fulfilled is not None and fulfilled.status == "fulfilled", (
            "premise: the request must really be fulfilled, not merely approved"
        )

        counts = await rig.recur(3)
        assert counts == [3, 4, 5], f"premise: the threshold was crossed, got {counts}"

        assert await rig.pending_actions() == []
        assert [r.id for r in rig.actions_for(fault_id)] == [first.id]
    finally:
        await _close(rig)


async def test_resolving_the_fault_re_arms_the_proposal(tmp_path: Any) -> None:
    """Resolution is the escape hatch, and it works by id rotation, not a timer."""
    rig = await _rig(tmp_path)
    try:
        first = await _first_approval(rig)
        old_fault_id = first.payload["params"]["fault_id"]
        await _decide(rig, first, approve=False)
        assert await rig.pending_actions() == []

        resolved = await rig.faults.resolve(
            old_fault_id, status="repaired", resolution="patched the handler",
        )
        assert resolved is not None and resolved.status == "repaired", (
            "premise: the fault must actually leave 'open', or the create "
            "branch below is never taken"
        )
        await rig.drain()

        counts = await rig.recur(2)
        assert counts == [1, 2], (
            f"premise: the resolved fault must recur on the CREATE branch and "
            f"restart its count, got {counts}"
        )

        pending = await rig.pending_actions()
        assert len(pending) == 1, "a resolved fault that recurs asks cleanly"
        assert pending[0].id != first.id
        assert pending[0].payload["params"]["fault_id"] != old_fault_id, (
            "a new request under the SAME fault id would mean the suppression "
            "simply was not working, not that resolution re-armed it"
        )
        assert [r.id for r in rig.actions_for(old_fault_id)] == [first.id], (
            "the denied answer still stands for the fault it answered"
        )
    finally:
        await _close(rig)


async def test_the_standing_answer_survives_a_restart(tmp_path: Any) -> None:
    """The whole point of putting the record in the store rather than in memory."""
    rig = await _rig(tmp_path)
    try:
        first = await _first_approval(rig)
        fault_id = first.payload["params"]["fault_id"]
        await _decide(rig, first, approve=False)

        await rig.requests.stop()
        restarted = CapabilityRequestStore(
            db_path=str(tmp_path / "approvals.db"),
        )
        await restarted.start()
        rig.requests = restarted
        rig.dispatcher = _dispatcher(rig.faults, restarted)

        survivors = restarted.find_action_requests_by_param("fault_id", fault_id)
        assert [r.status for r in survivors] == ["denied"], (
            "premise: the denial must have been reloaded from disk, or what "
            "follows proves nothing about durability"
        )

        counts = await rig.recur(3)
        assert counts == [3, 4, 5], f"premise: the threshold was crossed, got {counts}"

        assert await rig.pending_actions() == []
        assert [r.id for r in rig.actions_for(fault_id)] == [first.id]
    finally:
        await _close(rig)


async def test_a_pending_request_still_holds(tmp_path: Any) -> None:
    """AD-1267's guarantee is not regressed: an UNdecided ask still dedups."""
    rig = await _rig(tmp_path)
    try:
        first = await _first_approval(rig)
        fault_id = first.payload["params"]["fault_id"]

        counts = await rig.recur(3)
        assert counts == [3, 4, 5], f"premise: the threshold was crossed, got {counts}"

        pending = await rig.pending_actions()
        assert len(pending) == 1
        assert pending[0].id == first.id, (
            "the same pending card, not a second one filed beside it"
        )
        assert [r.id for r in rig.actions_for(fault_id)] == [first.id]
    finally:
        await _close(rig)


# ── DD-2: the lookup is narrow ───────────────────────────────────────────


async def test_the_lookup_ignores_other_faults_and_other_kinds(
    tmp_path: Any,
) -> None:
    """A denial elsewhere, and a denial of another kind, suppress nothing here."""
    rig = await _rig(tmp_path)
    try:
        counts = await rig.recur(1)
        assert counts == [1], "premise: occurrence 1 mints the report"
        assert await rig.pending_actions() == [], (
            "premise: once is a transient, so occurrence 1 files nothing"
        )
        fault_id = rig.faults.list_open()[0].id

        other = await rig.requests.file_action_request(
            agent_id="counselor-ezri",
            payload=_action_payload("a-different-fault"),
        )
        assert other is not None
        assert (await _decide(rig, other, approve=False)).status == "denied"

        # ``file_request`` caches ``payload`` verbatim, so a non-action kind can
        # carry an action-shaped payload naming THIS fault.
        build = await rig.requests.file_request(
            agent_id="counselor-ezri",
            kind="build",
            target="a repair harness",
            payload=_action_payload(fault_id),
        )
        assert (await _decide(rig, build, approve=False)).status == "denied"

        assert rig.actions_for(fault_id) == [], (
            "premise: neither seeded row is an ACTION row for this fault, so "
            "the proposal below is not merely suppressing itself"
        )
        assert len(
            rig.requests.find_action_requests_by_param(
                "fault_id", "a-different-fault", statuses=_DECIDED,
            )
        ) == 1, "premise: the other fault's denial really is on record"

        counts = await rig.recur(1)
        assert counts == [2], f"premise: the threshold was crossed, got {counts}"

        pending = await rig.pending_actions()
        assert len(pending) == 1, (
            "neither a different fault nor a different kind is an answer to "
            "this one"
        )
        assert pending[0].payload["params"]["fault_id"] == fault_id
    finally:
        await _close(rig)


async def test_a_malformed_payload_row_does_not_break_the_lookup(
    tmp_path: Any,
) -> None:
    """One unvalidated row must not make the lookup unanswerable for the rest."""
    rig = await _rig(tmp_path)
    try:
        genuine = await rig.requests.file_action_request(
            agent_id="counselor-ezri", payload=_action_payload("fault-abc"),
        )
        assert genuine is not None

        # ``file_request`` does not validate, so a non-dict ``params`` is a
        # reachable cache shape rather than a contrivance.
        malformed = await rig.requests.file_request(
            agent_id="counselor-ezri",
            kind="action",
            target="repair.dispatch",
            payload=_action_payload("fault-abc", params="not-a-dict"),
        )
        assert malformed.payload["params"] == "not-a-dict", (
            "premise: the malformed row must really be in the cache with a "
            "non-dict params, or the skip under test is never exercised"
        )

        found = rig.requests.find_action_requests_by_param("fault_id", "fault-abc")
        assert [r.id for r in found] == [genuine.id], (
            "the malformed row is skipped and the genuine match still returns"
        )
    finally:
        await _close(rig)


async def test_a_store_without_the_method_degrades_to_pending_only(
    tmp_path: Any, caplog: Any,
) -> None:
    """A store lacking the lookup degrades to AD-1267 rather than raising."""
    rig = await _rig(tmp_path)
    try:
        degraded = _NoLookupStore(rig.requests)
        assert not hasattr(degraded, "find_action_requests_by_param"), (
            "premise: the double must really lack the method"
        )
        rig.dispatcher = _dispatcher(rig.faults, degraded)

        first = await _first_approval(rig)
        await _decide(rig, first, approve=False)
        assert await rig.pending_actions() == [], (
            "premise: nothing is pending immediately after the denial"
        )

        with caplog.at_level(
            logging.DEBUG, logger="probos.cognitive.repair_dispatch",
        ):
            counts = await rig.recur(1)
        assert counts == [3], f"premise: the threshold was crossed, got {counts}"

        assert len(await rig.pending_actions()) == 1, (
            "AD-1267 behaviour: without the lookup, a denied fault asks again"
        )
        assert any("AD-1268" in message for message in caplog.messages), (
            "the degradation must be visible rather than silent"
        )
    finally:
        await _close(rig)


# ── the three adversarial-review repairs ─────────────────────────────────


async def test_a_decided_ask_for_another_tool_does_not_suppress_the_repair(
    tmp_path: Any,
) -> None:
    """A param name is not an identity.

    Review measured a DENIED ``browser.navigate`` that happened to carry the
    same ``fault_id`` suppressing a repair that had never been proposed once.
    A caller asking "has THIS question already been answered" has to say which
    question, so the lookup is narrowed to the asking tool and action.
    """
    rig = await _rig(tmp_path)
    try:
        counts = await rig.recur(1)
        assert counts == [1], f"premise: one occurrence dispatched, got {counts}"
        open_reports = rig.faults.list_open()
        assert len(open_reports) == 1, (
            f"premise: exactly one open fault report, got {len(open_reports)}"
        )
        report = open_reports[0]

        other = await rig.requests.file_action_request(
            "agent-1",
            _action_payload(report.id, tool_id="browser", action="navigate"),
        )
        assert other is not None, "premise: the unrelated ask must have filed"
        await _decide(rig, other, approve=False)

        counts = await rig.recur(1)
        assert counts == [2], (
            f"premise: the next occurrence must cross the threshold, got {counts}"
        )

        pending = await rig.pending_actions()
        assert len(pending) == 1, (
            "a denied ask for a DIFFERENT tool silenced the repair before it "
            "was ever proposed"
        )
        assert pending[0].payload is not None
        assert pending[0].payload["tool_id"] == REPAIR_TOOL_ID
    finally:
        await _close(rig)


@pytest.mark.parametrize(
    ("tool_id", "action", "which"),
    [
        ("browser", "dispatch", "tool_id"),
        (REPAIR_TOOL_ID, "navigate", "action"),
    ],
)
async def test_each_narrowing_branch_excludes_on_its_own(
    tmp_path: Any, tool_id: str, action: str, which: str,
) -> None:
    """Both branches are load-bearing, and neither may lean on the other.

    Mutation measured why this case is needed: the end-to-end test above uses a
    ``browser.navigate`` row, which differs on BOTH dimensions, so dropping
    either branch alone left the other still excluding it and the mutant
    survived. Each row here differs on exactly ONE dimension, so removing that
    branch admits it and this test dies.
    """
    rig = await _rig(tmp_path)
    try:
        near = await rig.requests.file_action_request(
            "agent-1",
            _action_payload("F-1", tool_id=tool_id, action=action),
        )
        assert near is not None, "premise: the near-miss ask must have filed"
        await _decide(rig, near, approve=False)
        assert any(
            r.status == "denied" for r in rig.requests._cache.values()
        ), "premise: the denial must be in the cache, or nothing is excluded"

        wide = rig.requests.find_action_requests_by_param(
            "fault_id", "F-1", statuses=_DECIDED,
        )
        assert len(wide) == 1, (
            f"premise: unnarrowed, this row MUST match, or the {which} branch "
            f"is never reached and this test asserts nothing"
        )

        narrow = rig.requests.find_action_requests_by_param(
            "fault_id", "F-1", statuses=_DECIDED,
            tool_id=REPAIR_TOOL_ID, action=REPAIR_ACTION,
        )
        assert narrow == [], (
            f"the {which} branch admitted a row that differs only in {which}"
        )
    finally:
        await _close(rig)


async def test_the_lookup_survives_a_payload_that_is_not_a_dict(
    tmp_path: Any, caplog: Any,
) -> None:
    """``file_request`` caches ``payload`` verbatim with no validation.

    Review measured ``AttributeError: 'str' object has no attribute 'get'``.
    One malformed row must not make the lookup unanswerable for the
    well-formed rows beside it -- inside ``on_fault_event`` that raise lands in
    the broad handler and the fault is silently not proposed.

    A shape that is simply not a match is a QUIET skip. The per-row guard added
    in round 2 would also swallow this one, but it would warn on every pass:
    the ``isinstance`` check is what keeps a benign non-match off the cheap path
    from becoming log spam on a busy store, so it is pinned separately here.
    """
    rig = await _rig(tmp_path)
    try:
        good = await rig.requests.file_action_request(
            "agent-1", _action_payload("F-good"),
        )
        assert good is not None, "premise: the well-formed row must file"

        await rig.requests.file_request(
            agent_id="agent-1", kind="action", target="junk",
            payload="not-a-dict",  # type: ignore[arg-type]
        )
        cached = [
            r for r in rig.requests._cache.values()
            if r.kind == "action" and not isinstance(r.payload, dict)
        ]
        assert cached, (
            "premise: a non-dict payload must actually be in the cache, or "
            "this asserts nothing about the skip"
        )

        with caplog.at_level(logging.WARNING):
            found = rig.requests.find_action_requests_by_param(
                "fault_id", "F-good",
                tool_id=REPAIR_TOOL_ID, action=REPAIR_ACTION,
            )

        assert [r.id for r in found] == [good.id]
        assert not [m for m in caplog.messages if "AD-1268" in m], (
            "a non-dict payload is a plain non-match, not an unreadable row; "
            "it must skip quietly rather than warn on every lookup"
        )
    finally:
        await _close(rig)


async def test_the_lookup_survives_an_unusable_created_at(tmp_path: Any) -> None:
    """An untyped sort key raises TypeError on the first mixed pair.

    Unusable timestamps sort LAST: an oldest-first caller wants the earliest
    row it can actually date, not one it cannot.
    """
    rig = await _rig(tmp_path)
    try:
        first = await rig.requests.file_action_request(
            "agent-1", _action_payload("F-x", scope_key="one"),
        )
        second = await rig.requests.file_action_request(
            "agent-2", _action_payload("F-x", scope_key="two"),
        )
        assert first is not None and second is not None
        assert first.id != second.id, (
            "premise: two DISTINCT rows, or the sort has nothing to order"
        )
        first.created_at = "not-a-number"  # type: ignore[assignment]

        found = rig.requests.find_action_requests_by_param(
            "fault_id", "F-x", tool_id=REPAIR_TOOL_ID, action=REPAIR_ACTION,
        )

        assert {r.id for r in found} == {first.id, second.id}
        assert found[-1].id == first.id, (
            "a row that cannot be dated must sort last, not raise"
        )
    finally:
        await _close(rig)


# ── the three round-2 review repairs ─────────────────────────────────────


@pytest.mark.parametrize("junk", ["nan", "inf", "-inf"])
async def test_a_non_finite_created_at_is_unusable_not_merely_odd(
    tmp_path: Any, junk: str,
) -> None:
    """``float("nan")`` converts happily and then compares false against
    everything, so it does not raise but does make the order arbitrary.

    Review measured a NaN row ranking alongside well-dated ones, which
    contradicts the sort key's own documented unusable-last contract.
    """
    rig = await _rig(tmp_path)
    try:
        first = await rig.requests.file_action_request(
            "agent-1", _action_payload("F-x", scope_key="one"),
        )
        second = await rig.requests.file_action_request(
            "agent-2", _action_payload("F-x", scope_key="two"),
        )
        assert first is not None and second is not None
        assert first.id != second.id, (
            "premise: two DISTINCT rows, or the sort has nothing to order"
        )
        assert float(junk) != float(junk) or not math.isfinite(float(junk)), (
            f"premise: {junk!r} must actually be non-finite"
        )
        first.created_at = junk  # type: ignore[assignment]

        found = rig.requests.find_action_requests_by_param(
            "fault_id", "F-x", tool_id=REPAIR_TOOL_ID, action=REPAIR_ACTION,
        )

        assert {r.id for r in found} == {first.id, second.id}
        assert found[-1].id == first.id, (
            f"a {junk} timestamp is not a date; it must sort last"
        )
    finally:
        await _close(rig)


class _HostileDict(dict):
    """A dict subclass that satisfies ``isinstance`` and still raises."""

    def get(self, *args: Any, **kwargs: Any) -> Any:  # type: ignore[override]
        raise RuntimeError("hostile payload")


async def test_one_unreadable_row_does_not_take_down_the_answer(
    tmp_path: Any, caplog: Any,
) -> None:
    """``isinstance(x, dict)`` is not enough on its own.

    Review measured a dict subclass overriding ``get`` raising straight through
    the lookup. Inside ``on_fault_event`` that raise lands in the broad handler
    and the fault is SILENTLY not proposed, so the lookup has to be total
    per-row rather than merely type-checked.
    """
    rig = await _rig(tmp_path)
    try:
        good = await rig.requests.file_action_request(
            "agent-1", _action_payload("F-good"),
        )
        assert good is not None, "premise: the well-formed row must file"

        await rig.requests.file_request(
            agent_id="agent-2", kind="action", target="hostile",
            payload=_HostileDict(_action_payload("F-good")),
        )
        hostile = [
            r for r in rig.requests._cache.values()
            if isinstance(r.payload, _HostileDict)
        ]
        assert hostile, (
            "premise: the hostile row must actually be in the cache, or this "
            "asserts nothing about surviving it"
        )
        with pytest.raises(RuntimeError):
            hostile[0].payload.get("tool_id")

        with caplog.at_level(logging.WARNING):
            found = rig.requests.find_action_requests_by_param(
                "fault_id", "F-good",
                tool_id=REPAIR_TOOL_ID, action=REPAIR_ACTION,
            )

        assert [r.id for r in found] == [good.id], (
            "one unreadable row made the answer unavailable for the readable "
            "row beside it"
        )
        assert any("AD-1268" in m for m in caplog.messages), (
            "the skip must be visible rather than silent"
        )
    finally:
        await _close(rig)


async def test_a_lookup_that_is_present_but_uncallable_degrades(
    tmp_path: Any, caplog: Any,
) -> None:
    """``hasattr`` passes on an attribute that cannot be called.

    That TypeError would land in the broad handler and skip the honest degrade
    log, so the fault would be silently un-proposed instead of proposed under
    AD-1267 pending-only dedup.
    """
    rig = await _rig(tmp_path)
    try:
        rig.requests.find_action_requests_by_param = "not-callable"  # type: ignore[assignment]
        assert hasattr(rig.requests, "find_action_requests_by_param"), (
            "premise: hasattr must still pass, or this tests the wrong gate"
        )
        assert not callable(rig.requests.find_action_requests_by_param)

        with caplog.at_level(logging.DEBUG):
            counts = await rig.recur(2)

        assert counts == [1, 2], f"premise: the threshold was crossed, got {counts}"
        assert len(await rig.pending_actions()) == 1, (
            "an uncallable lookup must degrade to AD-1267 pending-only dedup, "
            "not silently swallow the proposal"
        )
        assert any(
            "AD-1268" in m and "cannot answer" in m for m in caplog.messages
        ), "the degrade must be logged honestly"
    finally:
        await _close(rig)
