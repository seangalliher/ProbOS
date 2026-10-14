"""AD-1299 S2a (#1352) M1: the Captain's approval of one exact repair candidate, pure and fake-store.

Pins ``src/probos/cognitive/repair_approval.py`` without a real store:

* the constants, the six-key action payload, and that the payload is not a repair dispatch;
* ``check_candidate_approval`` (pure): the fixed reason order of D4 (identity before decision), the
  24-hour window and the argument-error tier;
* ``CandidateApprovalCheck``'s record invariants;
* ``file_candidate_approval`` against ``_FakeFiler`` and ``authorize_candidate_execution`` against
  ``_FakeReader`` (one durable read, then the clock, never the other way round).

Premise rule (as in the S1a/S1b files): every refusal test first asserts that the UNMODIFIED request
authorizes, then that the single change yields the exact reason string, written as a literal, so the
reason proves which rule was reached. Expiry tests use literal seconds (86_400.0), never the module
constant, so a changed constant cannot pass them.

Fakes only: the real ``CapabilityRequestStore`` and the decide route are not used here. The one test
that crosses the file -> decide -> durable read -> authorize seam with fakes is
``test_filed_request_authorizes_only_after_the_captain_approves``.
"""

from __future__ import annotations

import asyncio
import copy
import dataclasses
import logging
from collections.abc import Callable
from types import SimpleNamespace
from typing import Any

import pytest

from probos.capability_request import (
    RATIONALE_MAX_CHARS,
    REPAIR_ACTION,
    REPAIR_TOOL_ID,
    CapabilityRequest,
    can_fulfil_request,
    repair_action,
    validate_action_payload,
)
from probos.cognitive.repair_approval import (
    APPROVAL_REASONS,
    CANDIDATE_APPROVAL_ACTION,
    CANDIDATE_APPROVAL_TOOL_ID,
    CANDIDATE_APPROVAL_TTL_SECONDS,
    CandidateApprovalCheck,
    CandidateApprovalFilingRefused,
    authorize_candidate_execution,
    candidate_approval_payload,
    check_candidate_approval,
    file_candidate_approval,
)
from probos.cognitive.repair_candidate import RepairCandidate

_REQUEST_ID = "req-1"
_AGENT_ID = "agent-1"
_CLASS = "repair"
_CAMPAIGN = "campaign-1"
_DECIDED_AT = 1_000.0
_NOW = 1_010.0  # ten seconds after the fixture request was decided
_LOGGER = "probos.cognitive.repair_approval"


# ---------------------------------------------------------------------------
# Fixtures and helpers
# ---------------------------------------------------------------------------


class _StrSubclass(str):
    """A ``str`` that is not exactly ``str``: the module checks ``type(x) is str`` on the fields it reads, except a request's ``kind``."""


def _candidate(tree_char: str) -> RepairCandidate:
    t = tree_char * 40
    return RepairCandidate("a" * 40, "b" * 40, t, t)


def _request(candidate: RepairCandidate, **overrides: Any) -> CapabilityRequest:
    """The Captain's approved request for ``candidate`` (class ``repair``, campaign ``campaign-1``)."""
    request = CapabilityRequest(
        id=_REQUEST_ID,
        agent_id=_AGENT_ID,
        kind="action",
        status="approved",
        decided_by="captain",
        decided_at=_DECIDED_AT,
        created_at=900.0,
        payload=candidate_approval_payload(candidate, authority_class=_CLASS, campaign_id=_CAMPAIGN),
    )
    return dataclasses.replace(request, **overrides)


def _edited(request: CapabilityRequest, edit: Callable[[dict[str, Any]], object]) -> CapabilityRequest:
    """A copy of ``request`` whose payload was deep-copied and then changed by ``edit``."""
    payload = copy.deepcopy(request.payload)
    edit(payload)
    return dataclasses.replace(request, payload=payload)


def _lookalike(candidate: RepairCandidate) -> SimpleNamespace:
    """Carries every field and the ``digest`` method of ``candidate`` but is not a ``RepairCandidate``."""
    return SimpleNamespace(
        base_commit=candidate.base_commit,
        candidate_commit=candidate.candidate_commit,
        tree=candidate.tree,
        index_tree=candidate.index_tree,
        digest=candidate.digest,
    )


def _check(candidate: Any, request: Any, **overrides: Any) -> CandidateApprovalCheck:
    arguments: dict[str, Any] = {
        "request_id": _REQUEST_ID, "authority_class": _CLASS, "campaign_id": _CAMPAIGN, "now": _NOW,
    }
    arguments.update(overrides)
    return check_candidate_approval(candidate, request, **arguments)


def _assert_refused(check: CandidateApprovalCheck, reason: str, candidate: RepairCandidate) -> None:
    assert check.reason == reason
    assert check.authorized is False
    assert check.expires_at is None
    assert check.request_id == _REQUEST_ID
    assert check.candidate_digest == candidate.digest()


class _FakeFiler:
    """Records what filing hands the store; answers like ``CapabilityRequestStore.file_action_request``."""

    def __init__(self, *, refuse: bool = False, error: BaseException | None = None) -> None:
        self.calls: list[tuple[str, dict[str, Any], str, str | None]] = []
        self.filed: CapabilityRequest | None = None
        self._refuse = refuse
        self._error = error

    async def file_action_request(
        self,
        agent_id: str,
        payload: dict[str, Any],
        *,
        rationale: str = "",
        work_item_id: str | None = None,
    ) -> CapabilityRequest | None:
        self.calls.append((agent_id, payload, rationale, work_item_id))
        if self._error is not None:
            raise self._error
        if self._refuse:
            return None
        self.filed = CapabilityRequest(
            id=_REQUEST_ID, agent_id=agent_id, kind="action", rationale=rationale,
            work_item_id=work_item_id, payload=payload,
        )
        return self.filed


class _FakeReader:
    """Answers like ``CapabilityRequestStore.get``: the request for a durable read, ``None`` otherwise."""

    def __init__(
        self,
        request: CapabilityRequest | None,
        *,
        events: list[str] | None = None,
        error: BaseException | None = None,
    ) -> None:
        self.calls: list[tuple[str, bool]] = []
        self._request = request
        self._events = events if events is not None else []
        self._error = error

    async def get(self, request_id: str, *, durable: bool = False) -> CapabilityRequest | None:
        self.calls.append((request_id, durable))
        self._events.append("read")
        if self._error is not None:
            raise self._error
        return self._request if durable else None


class _FakeClock:
    """A clock that reports a fixed reading and notes each read in an event list shared with the reader."""

    def __init__(self, reading: Any, events: list[str] | None = None) -> None:
        self.reads = 0
        self._reading = reading
        self._events = events if events is not None else []

    def __call__(self) -> Any:
        self.reads += 1
        self._events.append("clock")
        return self._reading


async def _authorize(
    reader: _FakeReader, candidate: Any, clock: Callable[[], Any], **overrides: Any,
) -> CandidateApprovalCheck:
    arguments: dict[str, Any] = {
        "request_id": _REQUEST_ID, "authority_class": _CLASS, "campaign_id": _CAMPAIGN,
    }
    arguments.update(overrides)
    return await authorize_candidate_execution(reader, candidate, clock=clock, **arguments)


# Argument errors shared by the payload builder, the check, the filer and the authorizer. Each ``changes``
# builds the replacement arguments from the candidate under test; the code is the stable message.
_BAD_IDENTITY_ARGUMENTS = [
    pytest.param(
        lambda _: {"candidate": None}, TypeError, "repair_candidate_required", id="candidate-none",
    ),
    pytest.param(
        lambda c: {"candidate": _lookalike(c)}, TypeError, "repair_candidate_required", id="candidate-lookalike",
    ),
    pytest.param(
        lambda _: {"authority_class": "upkeep"}, ValueError, "authority_class_invalid", id="class-unknown",
    ),
    pytest.param(
        lambda _: {"authority_class": _StrSubclass("repair")}, ValueError, "authority_class_invalid",
        id="class-str-subclass",
    ),
    pytest.param(lambda _: {"campaign_id": ""}, ValueError, "campaign_id_invalid", id="campaign-empty"),
    pytest.param(
        lambda _: {"campaign_id": " x"}, ValueError, "campaign_id_invalid", id="campaign-leading-space",
    ),
    pytest.param(
        lambda _: {"campaign_id": "x" * 129}, ValueError, "campaign_id_invalid", id="campaign-129-chars",
    ),
]
_BAD_CHECK_ARGUMENTS = _BAD_IDENTITY_ARGUMENTS + [
    pytest.param(
        lambda _: {"now": float("nan")}, ValueError, "approval_clock_invalid", id="now-nan",
    ),
    pytest.param(
        lambda _: {"now": float("inf")}, ValueError, "approval_clock_invalid", id="now-inf",
    ),
    pytest.param(lambda _: {"now": "1"}, ValueError, "approval_clock_invalid", id="now-str"),
    pytest.param(lambda _: {"now": True}, ValueError, "approval_clock_invalid", id="now-bool"),
    pytest.param(
        lambda _: {"request_id": " x"}, ValueError, "approval_request_id_invalid", id="request-id-leading-space",
    ),
    pytest.param(
        lambda c: {"request": SimpleNamespace(**vars(_request(c)))}, TypeError, "capability_request_required",
        id="request-namespace",
    ),
]
_BAD_FILE_ARGUMENTS = _BAD_IDENTITY_ARGUMENTS + [
    pytest.param(
        lambda _: {"agent_id": " x"}, ValueError, "agent_id_invalid", id="agent-id-leading-space",
    ),
    pytest.param(lambda _: {"agent_id": ""}, ValueError, "agent_id_invalid", id="agent-id-empty"),
]
_BAD_AUTHORIZE_ARGUMENTS = _BAD_IDENTITY_ARGUMENTS + [
    pytest.param(
        lambda _: {"request_id": " x"}, ValueError, "approval_request_id_invalid", id="request-id-leading-space",
    ),
]


# ---------------------------------------------------------------------------
# 1-4: constants and the filed payload
# ---------------------------------------------------------------------------


def test_constants_are_pinned() -> None:
    assert CANDIDATE_APPROVAL_TOOL_ID == REPAIR_TOOL_ID == "repair"
    assert CANDIDATE_APPROVAL_ACTION == "approve_candidate"
    assert CANDIDATE_APPROVAL_ACTION != REPAIR_ACTION
    assert CANDIDATE_APPROVAL_TTL_SECONDS == 86_400.0
    assert type(CANDIDATE_APPROVAL_TTL_SECONDS) is float
    assert isinstance(APPROVAL_REASONS, frozenset)
    assert APPROVAL_REASONS == frozenset({
        "approval_authorized",
        "approval_not_found",
        "approval_malformed",
        "approval_candidate_mismatch",
        "approval_class_mismatch",
        "approval_campaign_mismatch",
        "approval_pending",
        "approval_denied",
        "approval_not_approved",
        "approval_not_captain",
        "approval_decision_time_invalid",
        "approval_expired",
    })
    assert len(APPROVAL_REASONS) == 12


def test_payload_is_a_valid_action_payload_with_exact_params() -> None:
    candidate = _candidate("c")

    payload = candidate_approval_payload(candidate, authority_class="repair", campaign_id="campaign-1")

    assert validate_action_payload(payload) is payload
    assert set(payload) == {"tool_id", "action", "params", "scope_key", "session_id", "thread_id"}
    assert payload["tool_id"] == "repair"
    assert payload["action"] == "approve_candidate"
    assert payload["params"] == {
        "candidate_digest": candidate.digest(),
        "authority_class": "repair",
        "campaign_id": "campaign-1",
        "base_commit": "a" * 40,
        "candidate_commit": "b" * 40,
        "tree": "c" * 40,
    }
    assert payload["scope_key"] == "campaign-1"
    assert payload["session_id"] is None
    assert payload["thread_id"] == ""


def test_payload_is_not_a_repair_dispatch() -> None:
    candidate = _candidate("c")
    # Premise: the gate is not blind. A real dispatch for the same tool id is recognised and can be fulfilled.
    dispatch = CapabilityRequest(
        id="req-2", agent_id=_AGENT_ID, kind="action", status="pending",
        payload={
            "tool_id": "repair",
            "action": "dispatch",
            "params": {"fault_id": "fault-1", "signature": "0" * 64},
            "scope_key": "tool-1",
            "session_id": None,
            "thread_id": "",
        },
    )
    assert repair_action(dispatch) is not None
    assert can_fulfil_request(dispatch) is True

    # The approval request is an action on the same tool id, yet not a dispatch: no fulfiller runs.
    approval = _request(candidate, status="pending", decided_by="", decided_at=None)
    assert approval.kind == "action"
    assert approval.payload["tool_id"] == dispatch.payload["tool_id"]
    assert repair_action(approval) is None
    assert can_fulfil_request(approval) is False


@pytest.mark.parametrize(("changes", "error", "code"), _BAD_IDENTITY_ARGUMENTS)
def test_payload_argument_errors_raise(
    changes: Callable[[RepairCandidate], dict[str, Any]], error: type[Exception], code: str,
) -> None:
    candidate = _candidate("c")
    arguments: dict[str, Any] = {"candidate": candidate, "authority_class": _CLASS, "campaign_id": _CAMPAIGN}
    assert validate_action_payload(candidate_approval_payload(**arguments)) is not None  # premise
    arguments.update(changes(candidate))

    with pytest.raises(error) as raised:
        candidate_approval_payload(**arguments)

    assert str(raised.value) == code


# ---------------------------------------------------------------------------
# 5-19: check_candidate_approval (pure) and CandidateApprovalCheck
# ---------------------------------------------------------------------------


def test_check_authorizes_captain_approval_within_ttl() -> None:
    candidate = _candidate("c")

    check = check_candidate_approval(
        candidate, _request(candidate), request_id="req-1", authority_class="repair",
        campaign_id="campaign-1", now=1_010.0,
    )

    assert isinstance(check, CandidateApprovalCheck)
    assert check.reason == "approval_authorized"
    assert check.authorized is True
    assert check.expires_at == 87_400.0
    assert type(check.expires_at) is float
    assert check.request_id == "req-1"
    assert check.candidate_digest == candidate.digest()


def test_check_absent_request_is_not_found() -> None:
    candidate = _candidate("c")
    assert _check(candidate, _request(candidate)).authorized  # premise

    _assert_refused(_check(candidate, None), "approval_not_found", candidate)


@pytest.mark.parametrize(
    ("asked_tree_char", "overrides", "reason"),
    [
        pytest.param("d", {}, "approval_candidate_mismatch", id="other-candidate"),
        pytest.param("c", {"authority_class": "maintenance"}, "approval_class_mismatch", id="other-class"),
        pytest.param("c", {"campaign_id": "campaign-2"}, "approval_campaign_mismatch", id="other-campaign"),
    ],
)
def test_check_identity_precedes_decision_state(
    asked_tree_char: str, overrides: dict[str, Any], reason: str,
) -> None:
    filed_for = _candidate("c")
    pending = _request(filed_for, status="pending", decided_by="", decided_at=None)
    # Premise: asked about what it was filed for, the pending request reads as pending.
    assert _check(filed_for, pending).reason == "approval_pending"

    asked = _candidate(asked_tree_char)
    # Only the other-candidate case asks about a different candidate; the class and campaign cases ask
    # about the same one, so the single changed identity is the one the case names.
    assert (asked.digest() != filed_for.digest()) is (asked_tree_char != "c")
    _assert_refused(_check(asked, pending, **overrides), reason, asked)


_MALFORMED_REQUESTS = [
    pytest.param(lambda r: dataclasses.replace(r, id="req-2"), id="other-request-id"),
    pytest.param(lambda r: dataclasses.replace(r, kind="grant"), id="kind-grant"),
    pytest.param(lambda r: dataclasses.replace(r, payload=None), id="payload-none"),
    pytest.param(lambda r: _edited(r, lambda p: p.update(tool_id="browser")), id="tool-browser"),
    pytest.param(lambda r: _edited(r, lambda p: p.update(action="dispatch")), id="action-dispatch"),
    pytest.param(lambda r: _edited(r, lambda p: p.update(session_id="session-1")), id="session-id"),
    pytest.param(lambda r: _edited(r, lambda p: p["params"].update(extra="x")), id="extra-param"),
    pytest.param(lambda r: _edited(r, lambda p: p["params"].pop("tree")), id="missing-param"),
    pytest.param(lambda r: _edited(r, lambda p: p["params"].update(tree=7)), id="int-param"),
    pytest.param(lambda r: dataclasses.replace(r, status=None), id="status-not-str"),
    pytest.param(lambda r: dataclasses.replace(r, decided_by=None), id="decided-by-not-str"),
]


@pytest.mark.parametrize("malform", _MALFORMED_REQUESTS)
def test_check_refuses_malformed_requests(malform: Callable[[CapabilityRequest], CapabilityRequest]) -> None:
    candidate = _candidate("c")
    request = _request(candidate)
    assert _check(candidate, request).authorized  # premise: the unmodified request authorizes

    malformed = malform(request)

    # The generic validator still accepts the payload, so only this module's own rule can refuse it.
    assert malformed.payload is None or validate_action_payload(malformed.payload) is malformed.payload
    _assert_refused(_check(candidate, malformed), "approval_malformed", candidate)


def test_check_refuses_forged_digest_param() -> None:
    candidate = _candidate("c")
    request = _request(candidate)
    assert _check(candidate, request).authorized  # premise
    other_digest = _candidate("d").digest()
    assert other_digest != candidate.digest()

    forged = _edited(request, lambda p: p["params"].update(candidate_digest=other_digest))

    # Everything else is copied from the candidate: only the digest names another candidate.
    params = forged.payload["params"]
    assert (params["base_commit"], params["candidate_commit"], params["tree"]) == (
        candidate.base_commit, candidate.candidate_commit, candidate.tree,
    )
    assert params["candidate_digest"] == other_digest
    _assert_refused(_check(candidate, forged), "approval_candidate_mismatch", candidate)


@pytest.mark.parametrize("field", ["base_commit", "candidate_commit", "tree"])
def test_check_refuses_display_field_mismatch(field: str) -> None:
    candidate = _candidate("c")
    request = _request(candidate)
    assert _check(candidate, request).authorized  # premise

    altered = _edited(request, lambda p: p["params"].update({field: "e" * 40}))

    assert altered.payload["params"][field] != getattr(candidate, field)
    assert altered.payload["params"]["candidate_digest"] == candidate.digest()  # the digest is still right
    _assert_refused(_check(candidate, altered), "approval_candidate_mismatch", candidate)


@pytest.mark.parametrize("asked_class", ["maintenance", "enhancement"])
def test_check_refuses_other_class(asked_class: str) -> None:
    candidate = _candidate("c")
    request = _request(candidate)  # filed for class "repair"
    assert _check(candidate, request, authority_class="repair").authorized  # premise

    _assert_refused(
        _check(candidate, request, authority_class=asked_class), "approval_class_mismatch", candidate,
    )


@pytest.mark.parametrize(
    "make",
    [
        pytest.param(lambda r: (r, {"campaign_id": "campaign-2"}), id="asked-about-other-campaign"),
        # The scope key still names the asked campaign, so only the params half of the rule can refuse.
        pytest.param(
            lambda r: (_edited(r, lambda p: p["params"].update(campaign_id="campaign-2")), {}),
            id="params-name-other-campaign",
        ),
    ],
)
def test_check_refuses_other_campaign(
    make: Callable[[CapabilityRequest], tuple[CapabilityRequest, dict[str, Any]]],
) -> None:
    candidate = _candidate("c")
    request = _request(candidate)
    assert _check(candidate, request).authorized  # premise

    altered, overrides = make(request)

    _assert_refused(_check(candidate, altered, **overrides), "approval_campaign_mismatch", candidate)


def test_check_refuses_scope_key_mismatch() -> None:
    candidate = _candidate("c")
    request = _request(candidate)
    assert _check(candidate, request).authorized  # premise

    altered = _edited(request, lambda p: p.update(scope_key="campaign-2"))

    # The params still name the asked campaign, and the generic validator still accepts the payload:
    # only the scope key disagrees.
    assert altered.payload["params"]["campaign_id"] == "campaign-1"
    assert validate_action_payload(altered.payload) is altered.payload
    _assert_refused(_check(candidate, altered), "approval_campaign_mismatch", candidate)


@pytest.mark.parametrize(
    ("status", "reason"),
    [
        pytest.param("pending", "approval_pending", id="pending"),
        pytest.param("denied", "approval_denied", id="denied"),
        pytest.param("fulfilled", "approval_not_approved", id="fulfilled"),
        pytest.param("failed", "approval_not_approved", id="failed"),
    ],
)
def test_check_decision_status(status: str, reason: str) -> None:
    candidate = _candidate("c")
    request = _request(candidate)
    assert _check(candidate, request).authorized  # premise: approved by the Captain, inside the window

    _assert_refused(_check(candidate, dataclasses.replace(request, status=status)), reason, candidate)


@pytest.mark.parametrize("decider", ["first_officer", ""])
def test_check_requires_captain_decider(decider: str) -> None:
    candidate = _candidate("c")
    request = _request(candidate)
    assert _check(candidate, request).authorized  # premise

    _assert_refused(
        _check(candidate, dataclasses.replace(request, decided_by=decider)), "approval_not_captain", candidate,
    )


@pytest.mark.parametrize(
    ("decided_at", "reason", "expires_at"),
    [
        pytest.param(None, "approval_decision_time_invalid", None, id="none"),
        pytest.param(float("nan"), "approval_decision_time_invalid", None, id="nan"),
        pytest.param(float("inf"), "approval_decision_time_invalid", None, id="inf"),
        pytest.param(True, "approval_decision_time_invalid", None, id="true"),
        pytest.param(1_010.0 + 1.0, "approval_decision_time_invalid", None, id="future"),
        pytest.param(1_010.0, "approval_authorized", 87_410.0, id="equals-now"),
    ],
)
def test_check_decision_time(decided_at: Any, reason: str, expires_at: float | None) -> None:
    candidate = _candidate("c")
    request = _request(candidate)
    assert _check(candidate, request, now=1_010.0).authorized  # premise: decided at 1_000.0 authorizes

    check = _check(candidate, dataclasses.replace(request, decided_at=decided_at), now=1_010.0)

    assert check.reason == reason
    assert check.expires_at == expires_at
    assert check.authorized is (expires_at is not None)
    assert check.request_id == _REQUEST_ID
    assert check.candidate_digest == candidate.digest()


@pytest.mark.parametrize(
    ("now", "reason", "expires_at"),
    [
        pytest.param(1_000.0 + 86_399.5, "approval_authorized", 87_400.0, id="half-a-second-inside"),
        pytest.param(1_000.0 + 86_400.0, "approval_expired", None, id="at-expiry"),
        pytest.param(1_000.0 + 86_401.0, "approval_expired", None, id="after-expiry"),
    ],
)
def test_check_expiry_boundary(now: float, reason: str, expires_at: float | None) -> None:
    candidate = _candidate("c")
    request = _request(candidate)  # decided at 1_000.0
    assert _check(candidate, request, now=1_010.0).authorized  # premise

    check = _check(candidate, request, now=now)

    assert check.reason == reason
    assert check.expires_at == expires_at
    assert check.authorized is (expires_at is not None)


@pytest.mark.parametrize(("changes", "error", "code"), _BAD_CHECK_ARGUMENTS)
def test_check_argument_errors(
    changes: Callable[[RepairCandidate], dict[str, Any]], error: type[Exception], code: str,
) -> None:
    candidate = _candidate("c")
    arguments: dict[str, Any] = {
        "candidate": candidate, "request": _request(candidate), "request_id": _REQUEST_ID,
        "authority_class": _CLASS, "campaign_id": _CAMPAIGN, "now": _NOW,
    }
    assert check_candidate_approval(**arguments).authorized  # premise
    arguments.update(changes(candidate))

    with pytest.raises(error) as raised:
        check_candidate_approval(**arguments)

    assert str(raised.value) == code


@pytest.mark.parametrize(
    "changes",
    [
        pytest.param({"reason": "approval_unknown", "expires_at": None}, id="unknown-reason"),
        pytest.param({"reason": _StrSubclass("approval_authorized")}, id="reason-str-subclass"),
        pytest.param({"expires_at": None}, id="authorized-without-expiry"),
        pytest.param({"reason": "approval_pending"}, id="pending-with-expiry"),
        pytest.param({"expires_at": float("nan")}, id="nan-expiry"),
        pytest.param({"expires_at": float("inf")}, id="inf-expiry"),
        pytest.param({"expires_at": 87_400}, id="int-expiry"),
        pytest.param({"candidate_digest": "g" * 64}, id="non-hex-digest"),
        pytest.param({"request_id": " x"}, id="invalid-request-id"),
    ],
)
def test_check_record_invariants(changes: dict[str, Any]) -> None:
    valid: dict[str, Any] = {
        "reason": "approval_authorized",
        "request_id": _REQUEST_ID,
        "candidate_digest": _candidate("c").digest(),
        "expires_at": 87_400.0,
    }
    # Premise: a consistent authorized record and a consistent refusal both construct.
    assert CandidateApprovalCheck(**valid).authorized is True
    assert CandidateApprovalCheck(**{**valid, "reason": "approval_pending", "expires_at": None}).authorized is False

    with pytest.raises(ValueError) as raised:
        CandidateApprovalCheck(**{**valid, **changes})

    assert str(raised.value) == "candidate_approval_check_invalid"


# ---------------------------------------------------------------------------
# 20-23: file_candidate_approval against _FakeFiler
# ---------------------------------------------------------------------------


async def test_file_files_the_payload_with_a_bounded_rationale() -> None:
    candidate = _candidate("c")
    campaign_id = "c" * 128
    filer = _FakeFiler()

    filed = await file_candidate_approval(
        filer, candidate, authority_class="enhancement", campaign_id=campaign_id, agent_id="agent-1",
    )

    assert len(filer.calls) == 1
    agent_id, payload, rationale, work_item_id = filer.calls[0]
    assert agent_id == "agent-1"
    assert payload == candidate_approval_payload(candidate, authority_class="enhancement", campaign_id=campaign_id)
    assert validate_action_payload(payload) is payload  # even the longest campaign id stays store-acceptable
    assert work_item_id is None
    assert len(rationale) <= RATIONALE_MAX_CHARS
    assert candidate.digest()[:12] in rationale
    assert "24 hours" in rationale
    assert filed is filer.filed


async def test_file_refused_payload_raises() -> None:
    candidate = _candidate("c")
    healthy = _FakeFiler()  # premise: the same call is filed when the store accepts the payload
    assert isinstance(
        await file_candidate_approval(
            healthy, candidate, authority_class="repair", campaign_id="campaign-1", agent_id="agent-1",
        ),
        CapabilityRequest,
    )
    refusing = _FakeFiler(refuse=True)

    with pytest.raises(CandidateApprovalFilingRefused) as raised:
        await file_candidate_approval(
            refusing, candidate, authority_class="repair", campaign_id="campaign-1", agent_id="agent-1",
        )

    assert isinstance(raised.value, ValueError)
    assert issubclass(CandidateApprovalFilingRefused, ValueError)
    assert str(raised.value) == "candidate_approval_payload_refused"
    assert len(refusing.calls) == 1  # the store was asked, and said no


@pytest.mark.parametrize(("changes", "error", "code"), _BAD_FILE_ARGUMENTS)
async def test_file_argument_errors_raise_before_the_store(
    changes: Callable[[RepairCandidate], dict[str, Any]], error: type[Exception], code: str,
) -> None:
    candidate = _candidate("c")
    arguments: dict[str, Any] = {
        "candidate": candidate, "authority_class": _CLASS, "campaign_id": _CAMPAIGN, "agent_id": _AGENT_ID,
    }
    healthy = _FakeFiler()  # premise: the unmodified arguments reach the store
    await file_candidate_approval(healthy, **arguments)
    assert len(healthy.calls) == 1
    filer = _FakeFiler()
    arguments.update(changes(candidate))

    with pytest.raises(error) as raised:
        await file_candidate_approval(filer, **arguments)

    assert str(raised.value) == code
    assert filer.calls == []


async def test_file_store_exception_propagates() -> None:
    candidate = _candidate("c")
    failure = RuntimeError("store unavailable")
    filer = _FakeFiler(error=failure)

    with pytest.raises(RuntimeError) as raised:
        await file_candidate_approval(
            filer, candidate, authority_class="repair", campaign_id="campaign-1", agent_id="agent-1",
        )

    assert raised.value is failure
    assert len(filer.calls) == 1


# ---------------------------------------------------------------------------
# 24-29: authorize_candidate_execution against _FakeReader
# ---------------------------------------------------------------------------


async def test_authorize_reads_durably_once() -> None:
    candidate = _candidate("c")
    request = _request(candidate)
    # Negative control: the fake answers only a durable read, so a non-durable read could not authorize.
    control = _FakeReader(request)
    assert await control.get("req-1") is None
    assert await control.get("req-1", durable=True) is request
    reader = _FakeReader(request)

    check = await _authorize(reader, candidate, _FakeClock(1_010.0))

    assert check.authorized is True
    assert reader.calls == [("req-1", True)]


async def test_authorize_reads_the_clock_after_the_read() -> None:
    candidate = _candidate("c")
    events: list[str] = []
    reader = _FakeReader(_request(candidate), events=events)
    clock = _FakeClock(1_010.0, events)

    check = await _authorize(reader, candidate, clock)

    assert check.authorized is True
    assert events == ["read", "clock"]
    assert clock.reads == 1


@pytest.mark.parametrize("error_type", [RuntimeError, asyncio.CancelledError], ids=["runtime-error", "cancelled"])
async def test_authorize_reader_errors_propagate(error_type: type[BaseException]) -> None:
    candidate = _candidate("c")
    healthy_events: list[str] = []  # premise: the same wiring authorizes when the read succeeds
    healthy = await _authorize(
        _FakeReader(_request(candidate), events=healthy_events), candidate, _FakeClock(1_010.0, healthy_events),
    )
    assert healthy.authorized
    events: list[str] = []
    failure = error_type("reader failed")
    reader = _FakeReader(_request(candidate), events=events, error=failure)
    clock = _FakeClock(1_010.0, events)

    with pytest.raises(error_type) as raised:
        await _authorize(reader, candidate, clock)

    assert raised.value is failure
    assert reader.calls == [("req-1", True)]
    assert clock.reads == 0
    assert events == ["read"]


@pytest.mark.parametrize(
    "reading",
    [float("nan"), float("inf"), "1", True, None],
    ids=["nan", "inf", "str", "bool", "none"],
)
async def test_authorize_bad_clock_raises_after_the_read(reading: Any) -> None:
    candidate = _candidate("c")
    good = await _authorize(_FakeReader(_request(candidate)), candidate, _FakeClock(1_010.0))
    assert good.authorized  # premise: a finite reading authorizes
    events: list[str] = []
    reader = _FakeReader(_request(candidate), events=events)
    clock = _FakeClock(reading, events)

    with pytest.raises(ValueError) as raised:
        await _authorize(reader, candidate, clock)

    assert str(raised.value) == "approval_clock_invalid"
    assert reader.calls == [("req-1", True)]
    assert events == ["read", "clock"]  # the read happened first; only then was the clock found bad


@pytest.mark.parametrize(("changes", "error", "code"), _BAD_AUTHORIZE_ARGUMENTS)
async def test_authorize_argument_errors_raise_before_the_read(
    changes: Callable[[RepairCandidate], dict[str, Any]], error: type[Exception], code: str,
) -> None:
    candidate = _candidate("c")
    arguments: dict[str, Any] = {
        "candidate": candidate, "request_id": _REQUEST_ID, "authority_class": _CLASS, "campaign_id": _CAMPAIGN,
    }
    healthy = _FakeReader(_request(candidate))  # premise: the unmodified arguments are read and authorize
    assert (await authorize_candidate_execution(healthy, clock=_FakeClock(1_010.0), **arguments)).authorized
    assert healthy.calls == [("req-1", True)]
    events: list[str] = []
    reader = _FakeReader(_request(candidate), events=events)
    clock = _FakeClock(1_010.0, events)
    arguments.update(changes(candidate))

    with pytest.raises(error) as raised:
        await authorize_candidate_execution(reader, clock=clock, **arguments)

    assert str(raised.value) == code
    assert reader.calls == []
    assert events == []  # neither the read nor the clock was reached


async def test_authorize_logs_refusal_reason(caplog: pytest.LogCaptureFixture) -> None:
    candidate = _candidate("c")
    pending = _request(candidate, status="pending", decided_by="", decided_at=None)

    with caplog.at_level(logging.INFO, logger=_LOGGER):
        refused = await _authorize(_FakeReader(pending), candidate, _FakeClock(1_010.0))

    assert refused.reason == "approval_pending"
    logged = [record.getMessage() for record in caplog.records if record.name == _LOGGER]
    assert len(logged) == 1
    assert "approval_pending" in logged[0]

    caplog.clear()
    with caplog.at_level(logging.INFO, logger=_LOGGER):
        authorized = await _authorize(_FakeReader(_request(candidate)), candidate, _FakeClock(1_010.0))

    assert authorized.authorized is True
    assert [record for record in caplog.records if record.name == _LOGGER] == []


# ---------------------------------------------------------------------------
# The seam, with fakes: file -> decide -> durable read -> authorize
# ---------------------------------------------------------------------------


async def test_filed_request_authorizes_only_after_the_captain_approves() -> None:
    candidate = _candidate("c")
    filer = _FakeFiler()

    filed = await file_candidate_approval(
        filer, candidate, authority_class="repair", campaign_id="campaign-1", agent_id="agent-1",
    )

    # As filed the request is pending, so the authorizer refuses it.
    still_pending = await _authorize(_FakeReader(filed), candidate, _FakeClock(1_010.0), request_id=filed.id)
    assert still_pending.reason == "approval_pending"
    # The Captain's decision changes the row, never the filed payload.
    decided = dataclasses.replace(filed, status="approved", decided_by="captain", decided_at=1_000.0)
    assert decided.payload == filer.calls[0][1]
    approved = await _authorize(_FakeReader(decided), candidate, _FakeClock(1_010.0), request_id=filed.id)
    assert approved.authorized is True
    assert approved.expires_at == 87_400.0
    assert approved.request_id == filed.id
    assert approved.candidate_digest == candidate.digest()
    # The approval is for exactly this candidate: another one reads as a mismatch.
    other = await _authorize(_FakeReader(decided), _candidate("d"), _FakeClock(1_010.0), request_id=filed.id)
    assert other.reason == "approval_candidate_mismatch"
