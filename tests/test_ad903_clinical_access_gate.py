"""AD-903: tests for the clinical-read access gate (#866).

The pure ``resolve_clinical_access`` deny-default ladder is unit-tested with
hand-built ``ClearanceGrant`` records (no store). ``clinical_access_for_caller``
uses a REAL ``ClearanceGrantStore(db_path="")`` (cache-only, BF-287) — no
MagicMock at the store boundary.

asyncio_mode="auto": async tests (store grant issuance) carry no marker.

Run: d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad903_clinical_access_gate.py -q -n 0
"""

from __future__ import annotations

import time
from typing import Any

from probos.clearance_grants import ClearanceGrantStore
from probos.cognitive.clinical_access import (
    CLINICAL_READ_ROLES,
    ClinicalAccessDecision,
    clinical_access_for_caller,
    clinical_grant_scope,
    resolve_clinical_access,
)
from probos.earned_agency import ClearanceGrant, RecallTier


def _grant(
    *,
    scope: str,
    target_agent_id: str = "chief",
    revoked: bool = False,
    expires_at: float | None = None,
) -> ClearanceGrant:
    return ClearanceGrant(
        id="g-" + scope,
        target_agent_id=target_agent_id,
        recall_tier=RecallTier.BASIC,
        scope=scope,
        revoked=revoked,
        expires_at=expires_at,
    )


# --------------------------------------------------------------------------- #
# Helpers / constants
# --------------------------------------------------------------------------- #


def test_clinical_read_roles_is_counselor_only() -> None:
    # Fresh role set — must NOT pull in AD-635's diagnostician.
    assert CLINICAL_READ_ROLES == frozenset({"counselor"})
    assert "diagnostician" not in CLINICAL_READ_ROLES


def test_clinical_grant_scope_format() -> None:
    assert clinical_grant_scope("crewman-7") == "clinical:crewman-7"


# --------------------------------------------------------------------------- #
# Pure resolve_clinical_access — deny-by-default ladder
# --------------------------------------------------------------------------- #


def test_captain_allows() -> None:
    d = resolve_clinical_access(
        caller_agent_id="",
        caller_agent_type="",
        target_agent_id="crewman",
        is_captain=True,
    )
    assert d == ClinicalAccessDecision(allowed=True, source="captain")


def test_subject_denied_reading_own_record() -> None:
    d = resolve_clinical_access(
        caller_agent_id="crewman",
        caller_agent_type="science",
        target_agent_id="crewman",
        is_captain=False,
    )
    assert d.allowed is False
    assert d.source == "subject_denied"


def test_subject_who_is_counselor_still_denied_own() -> None:
    # Rung 2 (subject) precedes rung 3 (role): the counselor cannot read their
    # OWN clinical record even though their type is a clinical-read role.
    d = resolve_clinical_access(
        caller_agent_id="counselor-1",
        caller_agent_type="counselor",
        target_agent_id="counselor-1",
        is_captain=False,
    )
    assert d.allowed is False
    assert d.source == "subject_denied"


def test_counselor_role_allows_other() -> None:
    d = resolve_clinical_access(
        caller_agent_id="counselor-1",
        caller_agent_type="counselor",
        target_agent_id="crewman",
        is_captain=False,
    )
    assert d.allowed is True
    assert d.source == "counselor_role"


def test_active_grant_for_target_allows() -> None:
    d = resolve_clinical_access(
        caller_agent_id="chief",
        caller_agent_type="engineering",
        target_agent_id="crewman",
        is_captain=False,
        active_grants=[_grant(scope="clinical:crewman")],
    )
    assert d.allowed is True
    assert d.source == "grant"


def test_active_wildcard_grant_allows() -> None:
    d = resolve_clinical_access(
        caller_agent_id="chief",
        caller_agent_type="engineering",
        target_agent_id="crewman",
        is_captain=False,
        active_grants=[_grant(scope="clinical:*")],
    )
    assert d.allowed is True
    assert d.source == "grant"


def test_wrong_scope_grant_denied() -> None:
    # A grant for a DIFFERENT crewman (or a non-clinical scope) does not unlock.
    d = resolve_clinical_access(
        caller_agent_id="chief",
        caller_agent_type="engineering",
        target_agent_id="crewman",
        is_captain=False,
        active_grants=[_grant(scope="clinical:other"), _grant(scope="project:apollo")],
    )
    assert d.allowed is False
    assert d.source == "default"


def test_revoked_grant_denied() -> None:
    d = resolve_clinical_access(
        caller_agent_id="chief",
        caller_agent_type="engineering",
        target_agent_id="crewman",
        is_captain=False,
        active_grants=[_grant(scope="clinical:crewman", revoked=True)],
    )
    assert d.allowed is False
    assert d.source == "default"


def test_no_grant_default_deny() -> None:
    d = resolve_clinical_access(
        caller_agent_id="chief",
        caller_agent_type="engineering",
        target_agent_id="crewman",
        is_captain=False,
    )
    assert d.allowed is False
    assert d.source == "default"


# --------------------------------------------------------------------------- #
# Store-backed clinical_access_for_caller (real ClearanceGrantStore, cache-only)
# --------------------------------------------------------------------------- #


def test_for_caller_captain_allows_without_store() -> None:
    d = clinical_access_for_caller(
        caller_agent_id="",
        caller_agent_type="",
        target_agent_id="crewman",
        is_captain=True,
        grant_store=None,
    )
    assert d.allowed is True
    assert d.source == "captain"


def test_for_caller_counselor_role_allows() -> None:
    store = ClearanceGrantStore(db_path="")
    d = clinical_access_for_caller(
        caller_agent_id="counselor-1",
        caller_agent_type="counselor",
        target_agent_id="crewman",
        is_captain=False,
        grant_store=store,
    )
    assert d.allowed is True
    assert d.source == "counselor_role"


def test_for_caller_no_grant_default_deny() -> None:
    store = ClearanceGrantStore(db_path="")
    d = clinical_access_for_caller(
        caller_agent_id="chief",
        caller_agent_type="engineering",
        target_agent_id="crewman",
        is_captain=False,
        grant_store=store,
    )
    assert d.allowed is False
    assert d.source == "default"


async def test_for_caller_store_grant_allows() -> None:
    store = ClearanceGrantStore(db_path="")
    await store.issue_grant("chief", RecallTier.BASIC, scope="clinical:crewman")
    d = clinical_access_for_caller(
        caller_agent_id="chief",
        caller_agent_type="engineering",
        target_agent_id="crewman",
        is_captain=False,
        grant_store=store,
    )
    assert d.allowed is True
    assert d.source == "grant"
    # A different crewman is NOT unlocked by a per-target grant.
    other = clinical_access_for_caller(
        caller_agent_id="chief",
        caller_agent_type="engineering",
        target_agent_id="crewman-2",
        is_captain=False,
        grant_store=store,
    )
    assert other.allowed is False


async def test_for_caller_store_wildcard_allows_any_target() -> None:
    store = ClearanceGrantStore(db_path="")
    await store.issue_grant("chief", RecallTier.BASIC, scope="clinical:*")
    for target in ("crewman", "crewman-2", "anyone"):
        d = clinical_access_for_caller(
            caller_agent_id="chief",
            caller_agent_type="engineering",
            target_agent_id=target,
            is_captain=False,
            grant_store=store,
        )
        assert d.allowed is True
        assert d.source == "grant"


async def test_for_caller_expired_grant_denied() -> None:
    store = ClearanceGrantStore(db_path="")
    await store.issue_grant(
        "chief", RecallTier.BASIC, scope="clinical:crewman", expires_at=time.time() - 100
    )
    d = clinical_access_for_caller(
        caller_agent_id="chief",
        caller_agent_type="engineering",
        target_agent_id="crewman",
        is_captain=False,
        grant_store=store,
    )
    assert d.allowed is False
    assert d.source == "default"


# --------------------------------------------------------------------------- #
# FAIL-CLOSED: a CONFIDENTIAL gate must never fail open
# --------------------------------------------------------------------------- #


class _RaisingGrantStore:
    """A grant store whose sync read raises (transient backend failure)."""

    def get_active_grants_sync(self, agent_id: str) -> Any:
        raise RuntimeError("grant store unavailable")


class _MalformedGrantStore:
    """Returns a malformed grant object (no ``.revoked`` / ``.scope``)."""

    def get_active_grants_sync(self, agent_id: str) -> Any:
        return [object()]


def test_fail_closed_when_store_raises_denies() -> None:
    # resolve_active_grants honest-degrades the raise to []; the caller then has
    # no clinical authority → DENY. The key property is: never fail open.
    d = clinical_access_for_caller(
        caller_agent_id="chief",
        caller_agent_type="engineering",
        target_agent_id="crewman",
        is_captain=False,
        grant_store=_RaisingGrantStore(),
    )
    assert d.allowed is False


def test_fail_closed_when_grant_malformed_source_error() -> None:
    # A malformed grant makes _has_clinical_grant raise INSIDE resolution; the
    # outer fail-closed guard converts it to a deny with source="error" (proves
    # the guard is live, not dead code).
    d = clinical_access_for_caller(
        caller_agent_id="chief",
        caller_agent_type="engineering",
        target_agent_id="crewman",
        is_captain=False,
        grant_store=_MalformedGrantStore(),
    )
    assert d.allowed is False
    assert d.source == "error"
