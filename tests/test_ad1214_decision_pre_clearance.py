"""AD-1214 (#1171): the Captain pre-clears one exact class of delegated decision.

After an AD-1213 delegated decision the Captain's notification offers to
pre-clear its exact class. A later decision of exactly that class is committed,
fulfilled and audited as before -- ``pre_cleared: true`` and the pre-clearance
id on its entry -- and the Captain is not notified. Nothing else changes: every
AD-1213 rule still decides whether an agent may decide at all.

The rig is AD-1213's (real stores, ontology, permission chain and audit log),
plus a real pre-clearance store on the rig's clock (H-11). H-5: every "silent"
assertion follows a positive notification from the same rig, and every
"notifies again" follows a proven silence.
"""

from __future__ import annotations

import ast
import asyncio
import dataclasses
import functools
import json
import logging
import re
import secrets
import shutil
import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from probos.cognitive.continue_or_ask import CONTINUE_REQUEST_KIND, continue_payload
from probos.cognitive.decomposer import _CAPABILITY_GAP_RE
from probos.config import AuthConfig, SystemConfig
from probos.config_models.experience import ApprovalInboxConfig
from probos.decision_pre_clearance import (
    OFFER_ID_RE,
    PRE_CLEAR_ACTION_PREFIX,
    PRE_CLEARANCE_AUDIT_CATEGORY,
    DecisionPreClearanceStore,
    PreClearance,
    PreClearanceUnavailable,
    describe_scope,
    offer_sentence,
)
from probos.delegated_approvals import AUDIT_CATEGORY, REVIEW_TOOL_ID, Refusal, _pre_clearance_armed, _record_lapse
from probos.events import EventType
from probos.ontology import VesselOntologyService
from probos.security.audit import AuditLog
from tests.test_ad1213_delegated_approvals import (
    _CAPABILITY_AUDIT_KEYS,
    _GRACE,
    _NOW,
    _REPO,
    BUILDER,
    LAFORGE,
    NUMBER_ONE,
    READ_MATRIX,
    SURGEON,
    _assert_untouched,
    _audit,
    _Clock,
    _decide,
    _decide_params,
    _FailingAppend,
    _presentation,
    _Rig,
    _StubTool,
)
from tests.test_ad1214_decision_pre_clearance_store import _key

_DECIDED = EventType.CAPABILITY_REQUEST_DECIDED.value
_MARKER_RE = re.compile(r"approval-pre-clear:([0-9a-f]{32})")
_PATH = "/api/decision-pre-clearances"
_REASON = "Routine read access."
_FO = {"decider_post": "first_officer", "decider_role": "first_officer"}
_DAY = 24 * 3600


@pytest.fixture
async def ontology(tmp_path: Path) -> VesselOntologyService:
    dst = tmp_path / "ontology"
    shutil.copytree(_REPO / "config" / "ontology", dst)
    service = VesselOntologyService(dst, data_dir=tmp_path / "ontology-data")
    await service.initialize()
    return service


@pytest.fixture
async def rig(tmp_path: Path, ontology: VesselOntologyService):
    r = _Rig(tmp_path, ontology)
    await r.start()
    try:
        yield r
    finally:
        await r.stop()


@pytest.fixture
async def store(rig: _Rig):
    """A real pre-clearance store on the rig's tmp_path and the rig's clock."""
    s = DecisionPreClearanceStore(db_path=str(rig.tmp / "decision_pre_clearances.db"), clock=rig.clock)
    await s.start()
    try:
        yield s
    finally:
        await s.stop()


def _arm(rig: _Rig, **inbox: Any) -> None:
    """Both flags on -- what AD-1214 needs -- unless overridden, plus any other inbox settings."""
    settings = {"delegated_approvals_enabled": True, "decision_pre_clearance_enabled": True, **inbox}
    rig.settings.config = ApprovalInboxConfig(**settings)


def _offer_id(note: Any) -> str:
    action_url = note["action_url"] if isinstance(note, dict) else note.action_url
    match = _MARKER_RE.fullmatch(action_url)
    assert match is not None, action_url
    return match.group(1)


def _ad1213_detail(decider: Any, requester: Any, target: str, *, reason: str = _REASON) -> str:
    """AD-1213's exact notification detail for a chief's approved grant."""
    return (
        f"Department chief {decider.id} approved {requester.id}'s grant request for '{target}'. "
        f"Class: non_destructive. Reason: {reason.rstrip('.')}. Not pre-cleared (AD-1213)."
    )


async def _pre_clear(store: DecisionPreClearanceStore, note: Any) -> PreClearance:
    """The Captain accepts the offer a notification carries (the store half of the route)."""
    offered = store.offered(_offer_id(note))
    assert offered is not None
    key, hours = offered
    return await store.issue(key, ttl_seconds=hours * 3600, issued_by="captain")


def _captain_runtime(rig: _Rig, store: Any) -> SimpleNamespace:
    """What the Captain's pre-clearance routes read."""
    return SimpleNamespace(
        decision_pre_clearance_store=store,
        config=SimpleNamespace(approval_inbox=rig.settings.config, auth=AuthConfig()),
        audit_log=rig.audit,
    )


# ===========================================================================
# The notification, the match, and what it never widens
# ===========================================================================


async def test_the_first_decision_of_a_class_offers_its_exact_scope(
    rig: _Rig, store: DecisionPreClearanceStore,
) -> None:
    _arm(rig)
    req = await rig.grant(BUILDER, "calc_tool")

    outcome = await _decide(rig.service(pre_clearances=store), LAFORGE, req, reason=_REASON)

    assert outcome.decided and (outcome.notified, outcome.pre_cleared) == (True, False)
    [note] = rig.notes.sent
    assert note.detail == (
        f"Department chief {LAFORGE.id} approved {BUILDER.id}'s grant request for 'calc_tool'. "
        "Class: non_destructive. Reason: Routine read access. Not pre-cleared (AD-1213). "
        "Pre-clear offer (AD-1214): for 24 hours after you accept, you will not be notified when the "
        "chief_engineer post, acting as department chief, approves a request from the engineering "
        "department to grant tool 'calc_tool' (class non_destructive). Each such decision is still "
        "audited, and nothing else is pre-cleared."
    )
    assert (note.agent_id, note.notification_type) == (LAFORGE.id, "info")
    assert note.action_url.startswith(PRE_CLEAR_ACTION_PREFIX)
    assert store.offered(_offer_id(note)) == (_key(), 24)
    [entry] = _audit(rig)
    assert set(entry) == _CAPABILITY_AUDIT_KEYS and entry["pre_cleared"] is False
    assert store.lookup(_key()) is None  # an offer is not a pre-clearance


async def test_a_pre_cleared_decision_is_committed_fulfilled_audited_and_not_notified(
    rig: _Rig, store: DecisionPreClearanceStore, caplog: pytest.LogCaptureFixture,
) -> None:
    _arm(rig)
    service = rig.service(pre_clearances=store)
    first = await rig.grant(BUILDER, "calc_tool")
    assert (await _decide(service, LAFORGE, first, reason=_REASON)).notified is True  # premise
    record = await _pre_clear(store, rig.notes.sent[0])
    req = await rig.grant(BUILDER, "calc_tool")

    with caplog.at_level(logging.INFO, logger="probos.delegated_approvals"):
        outcome = await _decide(service, LAFORGE, req, reason=_REASON)

    assert outcome.decided and (outcome.status, outcome.fulfilled, outcome.audited) == ("fulfilled", True, True)
    assert (outcome.notified, outcome.pre_cleared) == (False, True)
    assert len(rig.notes.sent) == 1
    stored = await rig.requests.get(req.id)
    assert (stored.status, stored.decided_by) == ("fulfilled", LAFORGE.id)
    assert len(rig.events.of(_DECIDED, req.id)) == 1
    last = _audit(rig)[-1]
    assert set(last) == _CAPABILITY_AUDIT_KEYS | {"pre_clearance_id"}
    assert (last["request_id"], last["pre_cleared"], last["pre_clearance_id"]) == (req.id, True, record.id)
    assert (last["decider_id"], last["decider_role"], last["status"], last["approve"]) == (
        LAFORGE.id, "department_chief", "approved", True,
    )
    assert any(f"matched pre-clearance {record.id[:12]}" in r.getMessage() for r in caplog.records)


@pytest.mark.parametrize("variant", ["other_tool", "other_department", "other_decider", "other_verb"])
async def test_a_pre_clearance_is_narrow(rig: _Rig, store: DecisionPreClearanceStore, variant: str) -> None:
    _arm(rig)
    rig.tools.register(_StubTool("scan_tool"), default_permissions=dict(READ_MATRIX))
    service = rig.service(pre_clearances=store)
    cleared_by_fo = variant in ("other_department", "other_decider")
    if cleared_by_fo:
        await rig.delegate()
    cleared_decider = NUMBER_ONE if cleared_by_fo else LAFORGE
    cleared_key = _key(**_FO) if cleared_by_fo else _key()

    async def decide(decider: Any, requester: Any, tool_id: str, *, approve: bool = True) -> Any:
        req = await rig.grant(requester, tool_id)
        if decider is NUMBER_ONE:
            rig.at(req, _GRACE + 1)
        return await _decide(service, decider, req, approve=approve)

    first = await decide(cleared_decider, BUILDER, "calc_tool")
    assert first.decided and first.notified is True
    assert store.offered(_offer_id(rig.notes.sent[-1])) == (cleared_key, 24)  # the offer names its exact class
    record = await _pre_clear(store, rig.notes.sent[-1])
    same = await decide(cleared_decider, BUILDER, "calc_tool")
    assert (same.pre_cleared, same.notified, len(rig.notes.sent)) == (True, False, 1)  # premise: proven silence

    if variant == "other_tool":
        outcome, expected = await decide(LAFORGE, BUILDER, "scan_tool"), _key(target="scan_tool")
    elif variant == "other_department":
        outcome = await decide(NUMBER_ONE, SURGEON, "calc_tool")
        expected = _key(requester_department="medical", **_FO)
    elif variant == "other_decider":
        outcome, expected = await decide(LAFORGE, BUILDER, "calc_tool"), _key()
    else:
        outcome, expected = await decide(LAFORGE, BUILDER, "calc_tool", approve=False), _key(decision="deny")

    assert outcome.decided and (outcome.notified, outcome.pre_cleared) == (True, False)
    assert len(rig.notes.sent) == 2
    fresh = _offer_id(rig.notes.sent[-1])
    assert fresh != _offer_id(rig.notes.sent[0])
    assert store.offered(fresh) == (expected, 24)  # its own offer, for exactly its own class
    assert rig.notes.sent[-1].detail.endswith(" " + offer_sentence(expected, hours=24))
    assert store.lookup(expected) is None and store.lookup(cleared_key) == record


async def test_an_expired_pre_clearance_notifies_again(rig: _Rig, store: DecisionPreClearanceStore) -> None:
    _arm(rig)
    service = rig.service(pre_clearances=store)
    await _decide(service, LAFORGE, await rig.grant(BUILDER, "calc_tool"))
    record = await _pre_clear(store, rig.notes.sent[-1])
    silent = await _decide(service, LAFORGE, await rig.grant(BUILDER, "calc_tool"))
    assert (silent.pre_cleared, len(rig.notes.sent)) == (True, 1)  # premise: proven silence

    rig.clock.t = record.expires_at
    outcome = await _decide(service, LAFORGE, await rig.grant(BUILDER, "calc_tool"))

    assert outcome.decided and (outcome.notified, outcome.pre_cleared) == (True, False)
    assert len(rig.notes.sent) == 2
    fresh = _offer_id(rig.notes.sent[-1])
    assert fresh != _offer_id(rig.notes.sent[0]) and store.offered(fresh) == (_key(), 24)
    assert store.lookup(_key()) is None
    assert [entry["pre_cleared"] for entry in _audit(rig)] == [False, True, False]


async def test_a_revoked_pre_clearance_notifies_again(rig: _Rig, store: DecisionPreClearanceStore) -> None:
    from probos.routers.decision_pre_clearances import revoke_decision_pre_clearance

    _arm(rig)
    service = rig.service(pre_clearances=store)
    await _decide(service, LAFORGE, await rig.grant(BUILDER, "calc_tool"))
    record = await _pre_clear(store, rig.notes.sent[-1])
    silent = await _decide(service, LAFORGE, await rig.grant(BUILDER, "calc_tool"))
    assert (silent.pre_cleared, len(rig.notes.sent)) == (True, 1)  # premise: proven silence

    revoked = await revoke_decision_pre_clearance(record.id, runtime=_captain_runtime(rig, store))
    outcome = await _decide(service, LAFORGE, await rig.grant(BUILDER, "calc_tool"))

    assert revoked == {"revoked": 1}
    assert outcome.decided and (outcome.notified, outcome.pre_cleared) == (True, False)
    assert len(rig.notes.sent) == 2
    fresh = _offer_id(rig.notes.sent[-1])
    assert fresh != _offer_id(rig.notes.sent[0]) and store.offered(fresh) == (_key(), 24)
    assert [entry["action"] for entry in _audit(rig, PRE_CLEARANCE_AUDIT_CATEGORY)] == ["revoke_pre_clearance"]


@pytest.mark.parametrize(
    "case",
    ["own_requisition", "grace_period", "delegation_absent", "outside_authority", "captain_reserved",
     "delegated_switched_off"],
)
async def test_a_pre_clearance_widens_nothing(rig: _Rig, store: DecisionPreClearanceStore, case: str) -> None:
    _arm(rig)
    service = rig.service(pre_clearances=store)
    destructive_fo = {"target": "deploy_tool", "request_class": "destructive", **_FO}
    decider = LAFORGE
    if case == "own_requisition":
        key, expected = _key(), Refusal.OWN_REQUISITION
        item = await rig.work_items.create_work_item(
            title="Refit step", description="Refit step", work_type="task",
            assigned_to=BUILDER.id, created_by=LAFORGE.id,
        )
        req = await rig.grant(BUILDER, "calc_tool", work_item_id=item.id)
    elif case == "grace_period":
        await rig.delegate()
        key, expected, decider = _key(**destructive_fo), Refusal.GRACE_PERIOD, NUMBER_ONE
        req = await rig.grant(BUILDER, "deploy_tool")
        rig.at(req, 10)
    elif case == "delegation_absent":
        key, expected, decider = _key(**destructive_fo), Refusal.DELEGATION_ABSENT, NUMBER_ONE
        req = await rig.grant(BUILDER, "deploy_tool")
        rig.at(req, _GRACE + 1)
    elif case == "outside_authority":
        key, expected = _key(requester_department="medical"), Refusal.OUTSIDE_AUTHORITY
        req = await rig.grant(SURGEON, "calc_tool")
    elif case == "captain_reserved":
        key, expected = _key(target=REVIEW_TOOL_ID), Refusal.CAPTAIN_RESERVED
        req = await rig.grant(BUILDER, REVIEW_TOOL_ID)
    else:
        key, expected = _key(), Refusal.NOT_ENABLED
        req = await rig.grant(BUILDER, "calc_tool")
    record = await store.issue(key, ttl_seconds=_DAY, issued_by="captain")
    assert store.lookup(key) == record  # premise: a live pre-clearance names what this decision would be
    if case == "delegated_switched_off":
        _arm(rig, delegated_approvals_enabled=False)

    refused = await _decide(service, decider, req)

    assert refused.refusal is expected and refused.decided is False and refused.pre_cleared is False
    await _assert_untouched(rig, req, audits=0, notes=0)
    # H-5: where the same class can be decided at all, the same pre-clearance does silence it.
    if case == "own_requisition":
        control = await _decide(service, LAFORGE, await rig.grant(BUILDER, "calc_tool"))
    elif case == "grace_period":
        rig.at(req, _GRACE + 1)
        control = await _decide(service, NUMBER_ONE, req)
    elif case == "delegation_absent":
        await rig.delegate()
        control = await _decide(service, NUMBER_ONE, req)
    elif case == "delegated_switched_off":
        _arm(rig)
        control = await _decide(service, LAFORGE, req)
    else:
        control = None
    if control is not None:
        assert control.decided and (control.pre_cleared, control.notified) == (True, False)
        assert [(e["pre_cleared"], e["pre_clearance_id"]) for e in _audit(rig)] == [(True, record.id)]
    assert rig.notes.sent == []


async def test_every_decision_is_audited_whether_or_not_pre_cleared(
    rig: _Rig, store: DecisionPreClearanceStore,
) -> None:
    _arm(rig)
    rig.tools.register(_StubTool("scan_tool"), default_permissions=dict(READ_MATRIX))
    service = rig.service(pre_clearances=store)
    ids: list[str] = []

    async def decide(tool_id: str) -> Any:
        req = await rig.grant(BUILDER, tool_id)
        ids.append(req.id)
        return await _decide(service, LAFORGE, req)

    outcomes = [await decide("calc_tool")]
    record = await _pre_clear(store, rig.notes.sent[-1])
    outcomes += [await decide("calc_tool"), await decide("scan_tool"), await decide("calc_tool")]

    assert all(outcome.decided and outcome.audited for outcome in outcomes)
    assert [outcome.pre_cleared for outcome in outcomes] == [False, True, False, True]
    entries = _audit(rig)
    assert [entry["request_id"] for entry in entries] == ids
    assert [entry["pre_cleared"] for entry in entries] == [False, True, False, True]
    assert [entry.get("pre_clearance_id") for entry in entries] == [None, record.id, None, record.id]
    assert set(entries[0]) == set(entries[2]) == _CAPABILITY_AUDIT_KEYS
    assert set(entries[1]) == set(entries[3]) == _CAPABILITY_AUDIT_KEYS | {"pre_clearance_id"}
    assert len(rig.notes.sent) == 2
    assert rig.audit.verify_chain()


class _RaisingLookup:
    """A pre-clearance book whose lookup raises."""

    def __init__(self) -> None:
        self.offers = 0

    def lookup(self, key: Any) -> Any:
        raise RuntimeError("AD-1214 test: the pre-clearance cache failed")

    def offer(self, key: Any, *, ttl_hours: int) -> str | None:
        self.offers += 1
        return None


@pytest.mark.parametrize("case", ["lookup_raises", "store_stopped"])
async def test_an_unreadable_pre_clearance_store_notifies(
    rig: _Rig, store: DecisionPreClearanceStore, case: str, caplog: pytest.LogCaptureFixture,
) -> None:
    _arm(rig)
    service = rig.service(pre_clearances=store)
    await _decide(service, LAFORGE, await rig.grant(BUILDER, "calc_tool"))
    await _pre_clear(store, rig.notes.sent[-1])
    silent = await _decide(service, LAFORGE, await rig.grant(BUILDER, "calc_tool"))
    assert (silent.pre_cleared, len(rig.notes.sent)) == (True, 1)  # premise: proven silence
    if case == "lookup_raises":
        book = _RaisingLookup()
        service = rig.service(pre_clearances=book)
    else:
        await store.stop()
    req = await rig.grant(BUILDER, "calc_tool")

    with caplog.at_level(logging.WARNING, logger="probos.delegated_approvals"):
        outcome = await _decide(service, LAFORGE, req, reason=_REASON)

    assert outcome.decided and outcome.status == "fulfilled"
    assert (outcome.notified, outcome.pre_cleared) == (True, False)
    assert len(rig.notes.sent) == 2
    note = rig.notes.sent[-1]
    assert note.detail == _ad1213_detail(LAFORGE, BUILDER, "calc_tool") and note.action_url == ""
    assert any("could not be read" in r.getMessage() for r in caplog.records if r.levelno == logging.WARNING)
    assert _audit(rig)[-1]["pre_cleared"] is False
    if case == "lookup_raises":
        assert book.offers == 0


class _StrictNotes:
    """AD-1213's exact call shape. A stray keyword (``action_url``) raises, so it reads as notified=False."""

    def __init__(self) -> None:
        self.sent: list[SimpleNamespace] = []

    def __call__(self, agent_id: str, title: str, *, detail: str, notification_type: str) -> None:
        self.sent.append(SimpleNamespace(
            agent_id=agent_id, title=title, detail=detail, notification_type=notification_type,
        ))


_AD1213_RECEIPT_KEYS = [
    "decided", "queue", "request_id", "status", "fulfilled", "captain_notified", "audited", "role",
    "request_class",
]


@pytest.mark.parametrize("case", ["no_store", "store_but_flag_off"])
async def test_switched_off_is_byte_identical_to_ad1213(
    rig: _Rig, store: DecisionPreClearanceStore, case: str,
) -> None:
    from probos.tools.review_requests_tool import ReviewRequestsTool

    notes = _StrictNotes()
    with pytest.raises(TypeError):  # premise: the strict notifier refuses a stray keyword
        notes(LAFORGE.id, "title", detail="detail", notification_type="info", action_url="x")
    if case == "no_store":
        _arm(rig)  # the flag alone arms nothing without a store
        service = rig.service(notify=notes)
    else:
        rig.settings.config = ApprovalInboxConfig(delegated_approvals_enabled=True)
        service = rig.service(notify=notes, pre_clearances=store)
    tool = ReviewRequestsTool(service=service)
    req = await rig.grant(BUILDER, "calc_tool")

    result = await tool.invoke(
        _decide_params(req, reason=_REASON), {"_tool_result_presentation": _presentation(), "agent_id": LAFORGE.id},
    )

    assert result.error is None, result.error
    receipt = ast.literal_eval(result.output)
    assert list(receipt) == _AD1213_RECEIPT_KEYS
    assert receipt == {
        "decided": True, "queue": "capability", "request_id": req.id, "status": "fulfilled",
        "fulfilled": True, "captain_notified": True, "audited": True,
        "role": "department_chief", "request_class": "non_destructive",
    }
    [note] = notes.sent
    assert note.detail == _ad1213_detail(LAFORGE, BUILDER, "calc_tool")
    assert note.title == f"Delegated decision: approved grant request {req.id[:8]}"
    [entry] = _audit(rig)
    assert set(entry) == _CAPABILITY_AUDIT_KEYS and entry["pre_cleared"] is False
    assert store.lookup(_key()) is None and store.live() == []


@pytest.mark.parametrize("case", ["continue", "build", "legacy_install", "skill_with_unpatterned_id"])
async def test_an_unkeyable_decision_notifies_without_an_offer(
    rig: _Rig, store: DecisionPreClearanceStore, case: str,
) -> None:
    _arm(rig)
    service = rig.service(pre_clearances=store)
    control = await _decide(service, LAFORGE, await rig.grant(BUILDER, "calc_tool"))
    assert control.decided and _MARKER_RE.fullmatch(rig.notes.sent[-1].action_url)  # premise: this rig offers
    queue, decider, approve = "capability", LAFORGE, True
    if case == "continue":
        req = await rig.requests.file_request(
            agent_id=BUILDER.id, kind=CONTINUE_REQUEST_KIND, target="continue: calibrate the array",
            rationale="step limit", payload=continue_payload("thread-1"),
        )
    elif case == "build":  # destructive, so the First Officer's; denied, so nothing is built
        req = await rig.requests.file_request(
            agent_id=BUILDER.id, kind="build", target="new_agent", rationale="gap", payload={},
        )
        decider, approve = NUMBER_ONE, False
    elif case == "legacy_install":  # no provenance payload; denied, so nothing is installed
        req = await rig.requests.file_request(
            agent_id=BUILDER.id, kind="install", target="feedparser", rationale="needs rss",
        )
        decider, approve = NUMBER_ONE, False
    else:
        req = await rig.skills.file_request(
            BUILDER.id, "Damage Control!", skill_label="Damage control", source="self", justification="Drills",
        )
        queue = "skill"
    if decider is NUMBER_ONE:
        await rig.delegate()
        rig.at(req, _GRACE + 1)

    outcome = await service.decide(decider.id, queue=queue, request_id=req.id, approve=approve, reason=_REASON)

    assert outcome.decided and (outcome.notified, outcome.pre_cleared) == (True, False)
    assert len(rig.notes.sent) == 2
    note = rig.notes.sent[-1]
    assert note.action_url == "" and "Pre-clear offer" not in note.detail
    assert note.detail.endswith("Not pre-cleared (AD-1213).")
    assert _audit(rig)[-1]["pre_cleared"] is False


class _OfferBook:
    """The real store's lookup, with an offer that raises or answers junk."""

    def __init__(self, inner: DecisionPreClearanceStore, answer: Any) -> None:
        self._inner = inner
        self._answer = answer
        self.calls = 0

    def lookup(self, key: Any) -> Any:
        return self._inner.lookup(key)

    def offer(self, key: Any, *, ttl_hours: int) -> Any:
        self.calls += 1
        if isinstance(self._answer, BaseException):
            raise self._answer
        return self._answer


@pytest.mark.parametrize("answer", ["raises", None, "not-an-offer-id", "A" * 32], ids=["raises", "none", "junk", "upper"])
async def test_a_failed_offer_still_notifies_without_an_offer(
    rig: _Rig, store: DecisionPreClearanceStore, answer: Any, caplog: pytest.LogCaptureFixture,
) -> None:
    _arm(rig)
    failure = RuntimeError("AD-1214 test: the offer book failed") if answer == "raises" else answer
    book = _OfferBook(store, failure)
    req = await rig.grant(BUILDER, "calc_tool")

    with caplog.at_level(logging.WARNING, logger="probos.decision_pre_clearance"):
        outcome = await _decide(rig.service(pre_clearances=book), LAFORGE, req, reason=_REASON)

    assert book.calls == 1  # premise: the offer was attempted
    assert outcome.decided and (outcome.notified, outcome.pre_cleared) == (True, False)
    [note] = rig.notes.sent
    assert note.detail == _ad1213_detail(LAFORGE, BUILDER, "calc_tool") and note.action_url == ""
    warned = any("could not be recorded" in r.getMessage() for r in caplog.records)
    assert warned is (answer == "raises")
    assert _audit(rig)[-1]["pre_cleared"] is False


async def test_a_pre_cleared_decision_is_still_refused_without_the_audit_log(
    rig: _Rig, store: DecisionPreClearanceStore,
) -> None:
    _arm(rig)
    service = rig.service(pre_clearances=store)
    await _decide(service, LAFORGE, await rig.grant(BUILDER, "calc_tool"))
    await _pre_clear(store, rig.notes.sent[-1])
    silent = await _decide(service, LAFORGE, await rig.grant(BUILDER, "calc_tool"))
    assert silent.pre_cleared is True  # premise: the class is pre-cleared
    failing = _FailingAppend()
    req = await rig.grant(BUILDER, "calc_tool")

    refused = await _decide(rig.service(pre_clearances=store, audit_log=failing), LAFORGE, req)

    assert refused.refusal is Refusal.AUDIT_UNAVAILABLE and failing.attempts == 1
    assert refused.pre_cleared is False
    await _assert_untouched(rig, req, audits=2, notes=1)


_AD1213_DESCRIPTION = (
    "List the capability and skill requests you currently hold authority to decide, "
    "and approve or deny one. Only requests from crew under your command appear. "
    "Every decision is recorded under your identity and reported to the Captain. "
    "A request outside your authority stays with the Captain."
)
_AD1213_OUTPUT = (
    "A complete pre-rendered Python-literal object (not JSON). list: requests "
    "and more; decide: decided, queue, request_id, status, fulfilled, "
    "captain_notified, audited, role and request_class."
)
_AD1214_DESCRIPTION = (
    "List the capability and skill requests you currently hold authority to decide, "
    "and approve or deny one. Only requests from crew under your command appear. "
    "Every decision is recorded under your identity and reported to the Captain, unless the "
    "Captain has pre-cleared that exact class of decision. "
    "A request outside your authority stays with the Captain."
)
_AD1214_OUTPUT = (
    "A complete pre-rendered Python-literal object (not JSON). list: requests "
    "and more; decide: decided, queue, request_id, status, fulfilled, "
    "captain_notified, pre_cleared, audited, role and request_class."
)
_WITH_PRE_CLEARED = [*_AD1213_RECEIPT_KEYS[:6], "pre_cleared", *_AD1213_RECEIPT_KEYS[6:]]


async def test_the_review_tool_reports_pre_cleared_only_in_pre_clearance_mode(
    rig: _Rig, store: DecisionPreClearanceStore, caplog: pytest.LogCaptureFixture,
) -> None:
    from probos.tools.review_requests_tool import ReviewRequestsTool

    def unreadable() -> bool:
        raise RuntimeError("AD-1214 test: the pre-clearance flag could not be read")

    _arm(rig)
    service = rig.service(pre_clearances=store)
    off = ReviewRequestsTool(service=service)
    on = ReviewRequestsTool(service=service, pre_clearance=lambda: True)
    context = {"_tool_result_presentation": _presentation(), "agent_id": LAFORGE.id}

    assert off.description == _AD1213_DESCRIPTION
    assert off.output_schema == {"type": "string", "description": _AD1213_OUTPUT}
    assert ReviewRequestsTool(service=service, pre_clearance=lambda: 1).description == _AD1213_DESCRIPTION
    with caplog.at_level(logging.WARNING, logger="probos.tools.review_requests_tool"):
        assert ReviewRequestsTool(service=service, pre_clearance=unreadable).description == _AD1213_DESCRIPTION
    assert any("could not read whether pre-clearance is on" in r.getMessage() for r in caplog.records)
    assert on.description == _AD1214_DESCRIPTION
    assert on.output_schema == {"type": "string", "description": _AD1214_OUTPUT}

    async def receipt(tool: Any, *, approve: bool = True) -> dict[str, Any]:
        req = await rig.grant(BUILDER, "calc_tool")
        result = await tool.invoke(_decide_params(req, approve=approve, reason=_REASON), context)
        assert result.error is None, result.error
        return ast.literal_eval(result.output)

    plain = await receipt(off)
    assert list(plain) == _AD1213_RECEIPT_KEYS and plain["captain_notified"] is True
    record = await _pre_clear(store, rig.notes.sent[-1])
    cleared = await receipt(on)
    assert list(cleared) == _WITH_PRE_CLEARED
    assert (cleared["captain_notified"], cleared["pre_cleared"], cleared["status"]) == (False, True, "fulfilled")
    denied = await receipt(on, approve=False)
    assert (denied["captain_notified"], denied["pre_cleared"], denied["status"]) == (True, False, "denied")
    # A-3: this pinned that a tool without a predicate hid pre_cleared; a pre-cleared decision now always says so.
    unhidden = await receipt(off)
    assert list(unhidden) == _WITH_PRE_CLEARED
    assert (unhidden["captain_notified"], unhidden["pre_cleared"]) == (False, True)
    assert [e.get("pre_clearance_id") for e in _audit(rig)] == [None, record.id, None, record.id]
    for text in (off.description, on.description, off.output_schema["description"], on.output_schema["description"]):
        assert _CAPABILITY_GAP_RE.search(text) is None, text


class _CommitHook:
    """The real request store, whose commit first runs ``hook``: what happens while a decision is written."""

    def __init__(self, inner: Any) -> None:
        self._inner = inner
        self.hook: Any = None
        self.fired = 0

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    async def decide(self, request_id: str, approve: bool, *, reason: str, decided_by: str) -> Any:
        if self.hook is not None:
            self.fired += 1
            await self.hook()
        return await self._inner.decide(request_id, approve, reason=reason, decided_by=decided_by)


@pytest.mark.parametrize("lapse", ["revoked", "expired", "switched_off"])
async def test_a_pre_clearance_lapsing_during_the_commit_notifies(
    rig: _Rig, store: DecisionPreClearanceStore, lapse: str,
) -> None:
    _arm(rig)
    requests = _CommitHook(rig.requests)
    service = rig.service(capability_requests=requests, pre_clearances=store)
    await _decide(service, LAFORGE, await rig.grant(BUILDER, "calc_tool"), reason=_REASON)
    record = await _pre_clear(store, rig.notes.sent[-1])
    silent = await _decide(service, LAFORGE, await rig.grant(BUILDER, "calc_tool"), reason=_REASON)
    assert (silent.pre_cleared, silent.notified, len(rig.notes.sent)) == (True, False, 1)  # premise

    async def lapse_during_commit() -> None:
        if lapse == "revoked":
            assert await store.revoke(record.id, revoked_by="captain") == 1
        elif lapse == "expired":
            rig.clock.t = record.expires_at + 1
        else:  # A-5: pre-clearance is switched off while the decision is being written
            rig.settings.config.decision_pre_clearance_enabled = False

    requests.hook = lapse_during_commit
    req = await rig.grant(BUILDER, "calc_tool")

    outcome = await _decide(service, LAFORGE, req, reason=_REASON)

    assert requests.fired == 1  # premise: the pre-clearance lapsed while the decision was being committed
    assert outcome.decided and (outcome.status, outcome.fulfilled) == ("fulfilled", True)
    assert (outcome.notified, outcome.pre_cleared) == (True, False)
    assert len(rig.notes.sent) == 2
    note = rig.notes.sent[-1]
    ad1213 = _ad1213_detail(LAFORGE, BUILDER, "calc_tool")
    if lapse == "switched_off":  # the record is still live, and nothing is offered while switched off
        assert (note.detail, note.action_url) == (ad1213, "")
        assert store.lookup(_key()) == record
    else:
        assert note.detail == ad1213 + " " + offer_sentence(_key(), hours=24)
        assert store.offered(_offer_id(note)) == (_key(), 24) and store.lookup(_key()) is None
    [decision] = [
        entry for entry in rig.audit.entries
        if entry.category == AUDIT_CATEGORY and json.loads(entry.detail)["request_id"] == req.id
    ]
    detail = json.loads(decision.detail)
    assert (detail["pre_cleared"], detail["pre_clearance_id"]) == (True, record.id)
    [correction] = [entry for entry in rig.audit.entries if entry.category == PRE_CLEARANCE_AUDIT_CATEGORY]
    assert json.loads(correction.detail) == {
        "v": 1, "action": "lapsed_before_commit", "queue": "capability", "request_id": req.id,
        "decider_id": LAFORGE.id, "pre_clearance_id": record.id, "entry_hash": decision.entry_hash,
        "cause": "switched_off" if lapse == "switched_off" else "expired_or_revoked",
    }
    assert correction.detail == json.dumps(json.loads(correction.detail), sort_keys=True, separators=(",", ":"))
    assert rig.audit.verify_chain()


def test_a_failed_lapse_correction_logs_an_error_and_never_raises(caplog: pytest.LogCaptureFixture) -> None:
    failing = _FailingAppend()
    lapsed = PreClearance(
        id=str(uuid.uuid4()), key=_key(), issued_by="captain", reason="", issued_at=_NOW, expires_at=_NOW + 60,
    )

    with caplog.at_level(logging.ERROR, logger="probos.delegated_approvals"):
        _record_lapse(
            failing, SimpleNamespace(agent_id=LAFORGE.id), "capability", SimpleNamespace(id="req-1"), lapsed,
            SimpleNamespace(entry_hash="a" * 64), switched_off=False,
        )

    assert failing.attempts == 1
    [error] = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert "recording that correction failed" in error.getMessage() and lapsed.id[:12] in error.getMessage()


@pytest.mark.parametrize(
    ("inbox", "armed"),
    [
        ({"delegated_approvals_enabled": True, "decision_pre_clearance_enabled": True}, True),
        ({"delegated_approvals_enabled": True, "decision_pre_clearance_enabled": False}, False),
        ({"delegated_approvals_enabled": False, "decision_pre_clearance_enabled": True}, False),
        ({"delegated_approvals_enabled": True, "decision_pre_clearance_enabled": 1}, False),
        (None, False),
    ],
    ids=["both_on", "pre_clearance_off", "delegation_off", "truthy_not_true", "provider_raises"],
)
def test_the_commit_time_flag_read_is_exact_and_never_raises(
    inbox: dict[str, Any] | None, armed: bool, caplog: pytest.LogCaptureFixture,
) -> None:
    def settings() -> Any:
        if inbox is None:
            raise RuntimeError("AD-1214 test: the settings provider failed")
        return SimpleNamespace(**inbox)

    with caplog.at_level(logging.WARNING, logger="probos.delegated_approvals"):
        assert _pre_clearance_armed(settings) is armed

    warnings = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == (1 if inbox is None else 0)
    assert all("treated as switched off" in text for text in warnings)


# ===========================================================================
# The Captain's routes
# ===========================================================================


def _route_runtime(store: Any, *, token: str = "", **inbox: Any) -> SimpleNamespace:
    settings = {"delegated_approvals_enabled": True, "decision_pre_clearance_enabled": True, **inbox}
    return SimpleNamespace(
        decision_pre_clearance_store=store,
        config=SimpleNamespace(
            approval_inbox=ApprovalInboxConfig(**settings), auth=AuthConfig(crew_scope_token=token),
        ),
        audit_log=AuditLog(),
    )


def _client(runtime: Any) -> TestClient:
    from probos.routers import decision_pre_clearances
    from probos.routers.deps import get_runtime

    app = FastAPI()
    app.include_router(decision_pre_clearances.router)
    app.dependency_overrides[get_runtime] = lambda: runtime
    return TestClient(app)


def _cache_store(clock: _Clock) -> DecisionPreClearanceStore:
    """A cache-only store: a TestClient runs its own loop, so no aiosqlite connection may sit behind it (H-8)."""
    cached = DecisionPreClearanceStore(db_path="", clock=clock)
    asyncio.run(cached.start())
    return cached


def _entries(runtime: Any) -> list[dict[str, Any]]:
    return [
        json.loads(entry.detail) for entry in runtime.audit_log.entries
        if entry.category == PRE_CLEARANCE_AUDIT_CATEGORY
    ]


async def test_the_captain_pre_clears_from_an_offer_lists_it_and_revokes_it(
    rig: _Rig, store: DecisionPreClearanceStore,
) -> None:
    from probos.routers.decision_pre_clearances import (
        PreClearBody,
        create_decision_pre_clearance,
        list_decision_pre_clearances,
        revoke_decision_pre_clearance,
    )

    _arm(rig)
    service = rig.service(pre_clearances=store)
    runtime = _captain_runtime(rig, store)
    await _decide(service, LAFORGE, await rig.grant(BUILDER, "calc_tool"))
    offer = _offer_id(rig.notes.sent[-1])
    assert (await list_decision_pre_clearances(runtime=runtime))["pre_clearances"] == []  # premise

    created = await create_decision_pre_clearance(
        PreClearBody(offer_id=offer, reason="Routine read grants."), runtime=runtime,
    )

    record = created["pre_clearance"]
    assert (created["requested_hours"], created["granted_hours"], created["clamped"]) == (24, 24, False)
    assert record["scope"] == describe_scope(_key())
    assert record["key"] == dataclasses.asdict(_key())
    assert (record["issued_by"], record["reason"], record["revoked"]) == ("captain", "Routine read grants.", False)
    assert record["expires_at"] == pytest.approx(rig.clock.t + _DAY)
    listed = await list_decision_pre_clearances(runtime=runtime)
    assert (listed["enabled"], listed["default_ttl_hours"], listed["max_ttl_hours"]) == (True, 24, 168)
    assert listed["pre_clearances"] == [record]
    silent = await _decide(service, LAFORGE, await rig.grant(BUILDER, "calc_tool"))
    assert (silent.pre_cleared, len(rig.notes.sent)) == (True, 1)

    assert await revoke_decision_pre_clearance(record["id"], runtime=runtime) == {"revoked": 1}

    assert (await list_decision_pre_clearances(runtime=runtime))["pre_clearances"] == []
    again = await _decide(service, LAFORGE, await rig.grant(BUILDER, "calc_tool"))
    assert (again.notified, again.pre_cleared, len(rig.notes.sent)) == (True, False, 2)
    assert [e["action"] for e in _audit(rig, PRE_CLEARANCE_AUDIT_CATEGORY)] == ["pre_clear", "revoke_pre_clearance"]


def test_every_pre_clearance_route_requires_the_operator_token() -> None:
    cached = _cache_store(_Clock(_NOW))
    runtime = _route_runtime(cached, token="secret")
    client = _client(runtime)
    offer = cached.offer(_key(), ttl_hours=24)
    record = asyncio.run(cached.issue(_key(target="scan_tool"), ttl_seconds=3600, issued_by="captain"))
    calls = (
        ("GET", _PATH, None),
        ("POST", _PATH, {"offer_id": offer}),
        ("DELETE", f"{_PATH}/{record.id}", None),
    )

    for method, path, body in calls:
        assert client.request(method, path, json=body).status_code == 401, (method, path)
        wrong = client.request(method, path, json=body, headers={"Authorization": "Bearer wrong"})
        assert wrong.status_code == 401, (method, path)
    assert cached.lookup(_key()) is None and cached.lookup(_key(target="scan_tool")) == record
    assert runtime.audit_log.entries == []

    codes = {
        method: client.request(method, path, json=body, headers={"Authorization": "Bearer secret"}).status_code
        for method, path, body in calls
    }
    assert codes == {"GET": 200, "POST": 201, "DELETE": 200}
    assert cached.lookup(_key()) is not None and cached.lookup(_key(target="scan_tool")) is None


def test_pre_clearance_routes_validate_input_and_clamp_hours() -> None:
    cached = _cache_store(_Clock(_NOW))
    runtime = _route_runtime(cached)
    client = _client(runtime)
    offer = cached.offer(_key(), ttl_hours=24)

    for body in (
        {"offer_id": "A" * 32}, {"offer_id": offer[:31]}, {"offer_id": offer + "0"}, {"offer_id": "g" * 32},
        {"offer_id": offer, "extra": 1}, {"offer_id": offer, "hours": 0}, {"offer_id": offer, "hours": 8761},
        {"offer_id": offer, "reason": "x" * 501}, {"offer_id": offer, "hours": "one"}, {}, {"key": {}},
    ):
        assert client.post(_PATH, json=body).status_code == 422, body
    for bad in ("not-a-uuid", str(uuid.uuid4()).upper(), str(uuid.uuid1()), "0" * 36):
        assert client.delete(f"{_PATH}/{bad}").status_code == 422, bad
    unknown_offer = client.post(_PATH, json={"offer_id": secrets.token_hex(16)})
    assert unknown_offer.status_code == 404
    assert unknown_offer.json()["detail"] == (
        "no pre-clear offer has that id; the next decision of that class offers it again"
    )
    unknown_record = client.delete(f"{_PATH}/{uuid.uuid4()}")
    assert (unknown_record.status_code, unknown_record.json()["detail"]) == (404, "no live pre-clearance has that id")
    assert runtime.audit_log.entries == [] and cached.live() == []

    clamped = client.post(_PATH, json={"offer_id": offer, "hours": 500, "reason": "x" * 500})
    assert clamped.status_code == 201, clamped.text
    body = clamped.json()
    assert (body["requested_hours"], body["granted_hours"], body["clamped"]) == (500, 168, True)
    assert body["pre_clearance"]["expires_at"] == pytest.approx(_NOW + 168 * 3600)
    exact = client.post(_PATH, json={"offer_id": offer, "hours": 2}).json()
    assert (exact["requested_hours"], exact["granted_hours"], exact["clamped"]) == (2, 2, False)
    default = client.post(_PATH, json={"offer_id": offer}).json()
    assert (default["requested_hours"], default["granted_hours"], default["clamped"]) == (24, 24, False)
    assert [record.id for record in cached.live()] == [default["pre_clearance"]["id"]]


def test_pre_clearance_routes_answer_503_without_a_store_and_409_when_switched_off() -> None:
    calls = (
        ("GET", _PATH, None),
        ("POST", _PATH, {"offer_id": secrets.token_hex(16)}),
        ("DELETE", f"{_PATH}/{uuid.uuid4()}", None),
    )
    absent = _client(_route_runtime(None))
    for method, path, body in calls:
        response = absent.request(method, path, json=body)
        assert response.status_code == 503, (method, path)
        assert response.json()["detail"] == "decision pre-clearance is switched off"
    idle = _client(_route_runtime(DecisionPreClearanceStore(db_path="", clock=_Clock(_NOW))))
    for method, path, body in calls:
        response = idle.request(method, path, json=body)
        assert response.status_code == 503, (method, path)
        assert response.json()["detail"] == "decision pre-clearances could not be read"

    cached = _cache_store(_Clock(_NOW))
    record = asyncio.run(cached.issue(_key(), ttl_seconds=3600, issued_by="captain"))
    offer = cached.offer(_key(target="scan_tool"), ttl_hours=24)
    for inbox in ({"decision_pre_clearance_enabled": False}, {"delegated_approvals_enabled": False}):
        switched_off = _client(_route_runtime(cached, **inbox))
        refused = switched_off.post(_PATH, json={"offer_id": offer})
        assert refused.status_code == 409, inbox
        assert refused.json()["detail"] == "decision pre-clearance is switched off on this vessel"
        listed = switched_off.get(_PATH)
        assert listed.status_code == 200 and listed.json()["enabled"] is False
        assert [entry["id"] for entry in listed.json()["pre_clearances"]] == [record.id]
    assert cached.lookup(_key(target="scan_tool")) is None

    revoked = switched_off.delete(f"{_PATH}/{record.id}")  # revoking only narrows: always allowed
    assert revoked.status_code == 200 and revoked.json() == {"revoked": 1}
    assert cached.lookup(_key()) is None


def test_every_pre_clearance_change_is_audited_and_degrades_without_an_audit_log() -> None:
    cached = _cache_store(_Clock(_NOW))
    runtime = _route_runtime(cached)
    client = _client(runtime)
    offer = cached.offer(_key(), ttl_hours=24)

    created = client.post(_PATH, json={"offer_id": offer, "reason": "Routine read grants."}).json()
    record_id = created["pre_clearance"]["id"]
    assert client.delete(f"{_PATH}/{record_id}").json() == {"revoked": 1}

    assert _entries(runtime) == [
        {
            "v": 1, "action": "pre_clear", "record_id": record_id,
            "expires_at": created["pre_clearance"]["expires_at"], "offer_id": offer,
            "requested_hours": 24, "granted_hours": 24, "key": dataclasses.asdict(_key()),
            "reason": "Routine read grants.",
        },
        {"v": 1, "action": "revoke_pre_clearance", "record_id": record_id, "revoked": 1},
    ]

    def _failing_append(**_kwargs: Any) -> None:
        raise RuntimeError("AD-1214 test: the audit sink failed")

    runtime.audit_log = None
    again = client.post(_PATH, json={"offer_id": offer})
    assert again.status_code == 201
    runtime.audit_log = SimpleNamespace(append=_failing_append)
    assert client.delete(f"{_PATH}/{again.json()['pre_clearance']['id']}").json() == {"revoked": 1}
    assert cached.lookup(_key()) is None


def test_the_api_mounts_exactly_the_pre_clearance_routes() -> None:
    from probos.api import create_app
    from probos.routers import decision_pre_clearances

    runtime = MagicMock()
    runtime.config = SystemConfig()
    runtime._data_dir = runtime.data_dir = None  # BF-326: a MagicMock path makes create_app mkdir a stray dir
    app = create_app(runtime)

    endpoints = {(route.path, method): route.endpoint for route in app.routes for method in getattr(route, "methods", ())}
    expected = {
        (route.path, method): route.endpoint
        for route in decision_pre_clearances.router.routes for method in route.methods
    }
    assert set(expected) == {(_PATH, "GET"), (_PATH, "POST"), (f"{_PATH}/{{record_id}}", "DELETE")}
    for key, handler in expected.items():
        assert endpoints[key] is handler, key
    assert {key for key in endpoints if key[0].startswith(_PATH)} == set(expected)
    assert decision_pre_clearances.router.prefix == _PATH


# ===========================================================================
# Wiring
# ===========================================================================


async def test_the_store_starts_only_when_both_flags_are_on(tmp_path: Path) -> None:
    from probos.startup.communication import _start_decision_pre_clearance_store

    for delegated, pre_clearance in ((False, False), (True, False), (False, True)):
        config = SystemConfig(approval_inbox=ApprovalInboxConfig(
            delegated_approvals_enabled=delegated, decision_pre_clearance_enabled=pre_clearance,
        ))
        assert await _start_decision_pre_clearance_store(config, tmp_path) is None, (delegated, pre_clearance)
        assert not (tmp_path / "decision_pre_clearances.db").exists()

    on = SystemConfig(approval_inbox=ApprovalInboxConfig(
        delegated_approvals_enabled=True, decision_pre_clearance_enabled=True,
    ))
    started = await _start_decision_pre_clearance_store(on, tmp_path)
    try:
        assert isinstance(started, DecisionPreClearanceStore) and started.live() == []
        assert (tmp_path / "decision_pre_clearances.db").exists()
    finally:
        await started.stop()


@pytest.mark.parametrize("armed", [True, False], ids=["on", "off"])
async def test_wiring_hands_the_store_to_the_service_and_the_tool_only_when_on(
    rig: _Rig, store: DecisionPreClearanceStore, armed: bool,
) -> None:
    from probos.startup.finalize import _wire_delegated_approvals

    config = SystemConfig(approval_inbox=ApprovalInboxConfig(
        delegated_approvals_enabled=True, decision_pre_clearance_enabled=armed,
    ))
    runtime = rig.wiring_runtime(enabled=True, config=config, decision_pre_clearance_store=store)

    assert _wire_delegated_approvals(runtime=runtime, config=config) is True

    tool = rig.tools.get(REVIEW_TOOL_ID).tool
    outcome = await _decide(runtime.delegated_approvals, LAFORGE, await rig.grant(BUILDER, "calc_tool"))
    assert outcome.decided and outcome.notified is True
    [note] = rig.notes.sent
    if armed:
        assert store.offered(_offer_id(note)) == (_key(), 24)
        assert "unless the Captain has pre-cleared that exact class of decision" in tool.description
        assert "pre_cleared, " in tool.output_schema["description"]
    else:
        assert note.action_url == "" and note.detail.endswith("Not pre-cleared (AD-1213).")
        assert tool.description == _AD1213_DESCRIPTION
        assert tool.output_schema["description"] == _AD1213_OUTPUT
        runtime.config = SystemConfig(approval_inbox=ApprovalInboxConfig(
            delegated_approvals_enabled=True, decision_pre_clearance_enabled=True,
        ))  # A-3: switched on live, but no store was handed over at wiring
        assert tool.description == _AD1213_DESCRIPTION


async def test_shutdown_closes_the_pre_clearance_store(tmp_path: Path) -> None:
    from probos.startup.shutdown import _stop_runtime_sqlite_sidecars

    running = DecisionPreClearanceStore(db_path=str(tmp_path / "decision_pre_clearances.db"))
    await running.start()
    try:
        assert running.live() == []  # premise: running
        runtime = SimpleNamespace(decision_pre_clearance_store=running)

        await _stop_runtime_sqlite_sidecars(runtime)

        assert runtime.decision_pre_clearance_store is None
        with pytest.raises(PreClearanceUnavailable):
            running.live()
        await _stop_runtime_sqlite_sidecars(SimpleNamespace(decision_pre_clearance_store=None))  # OFF: skipped
    finally:
        await running.stop()  # idempotent


def _queue_notifier(rig: _Rig) -> tuple[Any, Any]:
    """The real ``ProbOSRuntime.notify`` bound to a stub runtime over a real ``NotificationQueue``."""
    from probos.notifications import NotificationQueue
    from probos.runtime import ProbOSRuntime

    queue = NotificationQueue()
    stub = SimpleNamespace(
        notification_queue=queue, _find_agent=rig.agents.get,
        _get_agent_department=lambda _agent_id: "engineering",
    )
    return queue, functools.partial(ProbOSRuntime.notify, stub)


async def test_the_runtime_notify_carries_the_offer_into_the_real_queue(
    rig: _Rig, store: DecisionPreClearanceStore,
) -> None:
    _arm(rig)
    queue, notify = _queue_notifier(rig)
    service = rig.service(pre_clearances=store, notify=notify)

    outcome = await _decide(service, LAFORGE, await rig.grant(BUILDER, "calc_tool"), reason=_REASON)

    assert outcome.notified is True
    [note] = queue.snapshot()
    assert note["detail"] == _ad1213_detail(LAFORGE, BUILDER, "calc_tool") + " " + offer_sentence(_key(), hours=24)
    assert (note["agent_id"], note["agent_type"], note["department"], note["notification_type"]) == (
        LAFORGE.id, "engineering_officer", "engineering", "info",
    )
    assert store.offered(_offer_id(note)) == (_key(), 24)
    assert note["suggested_action"] is None  # AD-1053's accept route is never the path


async def test_review_tool_shape_follows_the_live_flag(
    rig: _Rig, store: DecisionPreClearanceStore, monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    from probos.startup.finalize import _wire_delegated_approvals

    def inbox(**flags: bool) -> SystemConfig:
        settings = {"delegated_approvals_enabled": True, "decision_pre_clearance_enabled": True, **flags}
        return SystemConfig(approval_inbox=ApprovalInboxConfig(**settings))

    runtime = rig.wiring_runtime(enabled=True, config=inbox(), decision_pre_clearance_store=store)
    assert _wire_delegated_approvals(runtime=runtime, config=runtime.config) is True
    tool = rig.tools.get(REVIEW_TOOL_ID).tool
    context = {"_tool_result_presentation": _presentation(), "agent_id": LAFORGE.id}

    def shape() -> tuple[str, str]:
        return tool.description, tool.output_schema["description"]

    async def receipt() -> dict[str, Any]:
        req = await rig.grant(BUILDER, "calc_tool")
        result = await tool.invoke(_decide_params(req, reason=_REASON), context)
        assert result.error is None, result.error
        return ast.literal_eval(result.output)

    assert shape() == (_AD1214_DESCRIPTION, _AD1214_OUTPUT)
    first = await receipt()
    assert list(first) == _WITH_PRE_CLEARED and (first["captain_notified"], first["pre_cleared"]) == (True, False)
    await _pre_clear(store, rig.notes.sent[-1])
    cleared = await receipt()
    assert (cleared["captain_notified"], cleared["pre_cleared"]) == (False, True)  # premise: on, and pre-cleared

    runtime.config = inbox(decision_pre_clearance_enabled=False)  # switched off live
    assert shape() == (_AD1213_DESCRIPTION, _AD1213_OUTPUT)
    off = await receipt()
    assert list(off) == _AD1213_RECEIPT_KEYS and off["captain_notified"] is True
    assert rig.notes.sent[-1].detail == _ad1213_detail(LAFORGE, BUILDER, "calc_tool")
    assert rig.notes.sent[-1].action_url == ""

    runtime.config = inbox()  # and on again
    assert shape() == (_AD1214_DESCRIPTION, _AD1214_OUTPUT)
    again = await receipt()
    assert list(again) == _WITH_PRE_CLEARED and (again["captain_notified"], again["pre_cleared"]) == (False, True)

    service = runtime.delegated_approvals
    real_decide = service.decide
    switched: list[bool] = []

    async def decide_then_switch_off(*args: Any, **kwargs: Any) -> Any:
        outcome = await real_decide(*args, **kwargs)
        runtime.config = inbox(decision_pre_clearance_enabled=False)  # after the decision, before its receipt
        switched.append(True)
        return outcome

    monkeypatch.setattr(service, "decide", decide_then_switch_off)
    raced = await receipt()
    assert switched == [True] and shape() == (_AD1213_DESCRIPTION, _AD1213_OUTPUT)  # premise: off by the receipt
    assert list(raced) == _WITH_PRE_CLEARED and (raced["captain_notified"], raced["pre_cleared"]) == (False, True)

    runtime.config = inbox(delegated_approvals_enabled=False)
    assert shape() == (_AD1213_DESCRIPTION, _AD1213_OUTPUT)  # both flags must read True
    runtime.config = SimpleNamespace()  # settings that cannot be read
    with caplog.at_level(logging.WARNING, logger="probos.startup.finalize"):
        assert shape() == (_AD1213_DESCRIPTION, _AD1213_OUTPUT)
    assert any("settings could not be read" in r.getMessage() for r in caplog.records)


def test_the_hxi_and_the_server_agree_on_the_offer_marker_and_route() -> None:
    from probos.routers.decision_pre_clearances import router

    source = (_REPO / "ui" / "src" / "components" / "bridge" / "BridgeNotifications.tsx").read_text(encoding="utf-8")

    assert f"const PRE_CLEAR_OFFER_RE = /^{PRE_CLEAR_ACTION_PREFIX}({OFFER_ID_RE.pattern})$/;" in source
    assert f"const PRE_CLEAR_ROUTE = '{router.prefix}';" in source
    assert OFFER_ID_RE.pattern == "[0-9a-f]{32}"
    for _ in range(64):
        assert OFFER_ID_RE.fullmatch(secrets.token_hex(16))


# ===========================================================================
# End to end
# ===========================================================================


async def test_e2e_notify_then_pre_clear_then_same_class_silent_then_other_class_notifies(
    rig: _Rig, store: DecisionPreClearanceStore,
) -> None:
    from probos.routers.decision_pre_clearances import PreClearBody, create_decision_pre_clearance, router
    from probos.startup.finalize import _wire_delegated_approvals

    config = SystemConfig(approval_inbox=ApprovalInboxConfig(
        delegated_approvals_enabled=True, decision_pre_clearance_enabled=True,
    ))
    rig.tools.register(_StubTool("scan_tool"), default_permissions=dict(READ_MATRIX))
    queue, notify = _queue_notifier(rig)
    runtime = rig.wiring_runtime(enabled=True, config=config, notify=notify, decision_pre_clearance_store=store)
    assert _wire_delegated_approvals(runtime=runtime, config=config) is True
    await rig.grant_review_tool(LAFORGE)

    async def laforge_decides(tool_id: str) -> tuple[Any, dict[str, Any]]:
        req = await rig.grant(BUILDER, tool_id)
        result = await rig.tools.check_and_invoke(
            LAFORGE.id, REVIEW_TOOL_ID, _decide_params(req, reason=_REASON), agent_rank="commander",
            context={"_tool_result_presentation": _presentation()},
        )
        assert result.error is None, result.error
        return req, ast.literal_eval(result.output)

    # 1. The first decision of the class notifies, and the notification offers its exact scope.
    first, receipt = await laforge_decides("calc_tool")
    assert (receipt["captain_notified"], receipt["pre_cleared"]) == (True, False)
    [note] = queue.snapshot()
    assert note["detail"].endswith(" " + offer_sentence(_key(), hours=24))
    o1 = _offer_id(note)

    # 2. The Captain pre-clears it through the route.
    [post] = [route for route in router.routes if "POST" in route.methods]
    assert post.status_code == 201
    created = await create_decision_pre_clearance(PreClearBody(offer_id=o1), runtime=runtime)
    assert created["granted_hours"] == 24
    pre_clearance_id = created["pre_clearance"]["id"]

    # 3. The same class decides silently, and is still committed, fulfilled and audited.
    second, receipt = await laforge_decides("calc_tool")
    assert (receipt["captain_notified"], receipt["pre_cleared"]) == (False, True)
    assert len(queue.snapshot()) == 1
    stored = await rig.requests.get(second.id)
    assert (stored.status, stored.decided_by) == ("fulfilled", LAFORGE.id)
    newest = _audit(rig)[-1]
    assert (newest["request_id"], newest["pre_cleared"], newest["pre_clearance_id"]) == (
        second.id, True, pre_clearance_id,
    )

    # 4. A different class still notifies, with its own offer.
    third, receipt = await laforge_decides("scan_tool")
    assert (receipt["captain_notified"], receipt["pre_cleared"]) == (True, False)
    notes = queue.snapshot()
    assert len(notes) == 2
    [other] = [entry for entry in notes if entry["id"] != note["id"]]
    o2 = _offer_id(other)
    assert o2 != o1 and store.offered(o2) == (_key(target="scan_tool"), 24)
    last = _audit(rig)[-1]
    assert (last["request_id"], last["pre_cleared"]) == (third.id, False) and "pre_clearance_id" not in last
    assert [entry["request_id"] for entry in _audit(rig)] == [first.id, second.id, third.id]
