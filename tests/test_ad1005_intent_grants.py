"""AD-1005: IntentGrantStore tests.

The per-agent mesh-intent grant substrate for the settled write-intent gating
design (authorization at origination, default-OFF, mechanism-only). Mirrors the
SkillGrantStore / ToolPermissionStore pattern. BF-287: a real store (cache-only
+ a real tmp_path SQLite DB for persistence), no mocks.
"""
from __future__ import annotations

import time
from pathlib import Path

import pytest

from probos.cognitive.intent_grants import IntentAccessGrant, IntentGrantStore


# ---------------------------------------------------------------------------
# cache-only (db_path="") — the API-test mode
# ---------------------------------------------------------------------------


async def test_issue_and_read_grant_cache_only():
    store = IntentGrantStore(db_path="")
    await store.start()
    grant = await store.issue_grant("ezri", "run_python", reason="captain enabled")
    assert isinstance(grant, IntentAccessGrant)
    active = store.get_active_grants_sync("ezri")
    assert len(active) == 1
    assert active[0].intent_name == "run_python"
    assert active[0].is_restriction is False
    await store.stop()


async def test_is_granted_sync():
    store = IntentGrantStore(db_path="")
    await store.start()
    assert store.is_granted_sync("ezri", "run_python") is False  # nothing granted
    await store.issue_grant("ezri", "run_python")
    assert store.is_granted_sync("ezri", "run_python") is True
    # a different agent / intent is unaffected
    assert store.is_granted_sync("yeo", "run_python") is False
    assert store.is_granted_sync("ezri", "install_package") is False


async def test_restriction_wins_over_grant():
    store = IntentGrantStore(db_path="")
    await store.start()
    await store.issue_grant("ezri", "run_python")
    await store.issue_grant("ezri", "run_python", is_restriction=True, reason="paused")
    # most-restrictive: a restriction overrides the grant.
    assert store.is_granted_sync("ezri", "run_python") is False
    active = store.get_active_grants_sync("ezri", "run_python")
    assert len(active) == 2
    await store.stop()


async def test_revoke_grant():
    store = IntentGrantStore(db_path="")
    await store.start()
    g = await store.issue_grant("ezri", "run_python")
    assert store.is_granted_sync("ezri", "run_python") is True
    assert await store.revoke_grant(g.id) is True
    assert store.is_granted_sync("ezri", "run_python") is False
    await store.stop()


async def test_expired_grant_filtered():
    store = IntentGrantStore(db_path="")
    await store.start()
    await store.issue_grant("ezri", "run_python", expires_at=time.time() - 10)
    assert store.get_active_grants_sync("ezri") == []
    assert store.is_granted_sync("ezri", "run_python") is False
    await store.stop()


async def test_intent_name_filter():
    store = IntentGrantStore(db_path="")
    await store.start()
    await store.issue_grant("ezri", "run_python")
    await store.issue_grant("ezri", "install_package")
    assert len(store.get_active_grants_sync("ezri")) == 2
    assert len(store.get_active_grants_sync("ezri", "run_python")) == 1
    await store.stop()


# ---------------------------------------------------------------------------
# persistence (real tmp_path SQLite DB)
# ---------------------------------------------------------------------------


async def test_persistence_across_restart(tmp_path: Path):
    db = str(tmp_path / "intent_grants.db")
    s1 = IntentGrantStore(db_path=db)
    await s1.start()
    await s1.issue_grant("ezri", "run_python", reason="captain")
    await s1.stop()

    s2 = IntentGrantStore(db_path=db)
    await s2.start()
    # The grant survives the restart (loaded into cache from disk).
    assert s2.is_granted_sync("ezri", "run_python") is True
    grants = await s2.list_grants()
    assert len(grants) == 1
    assert grants[0].agent_id == "ezri"
    await s2.stop()


async def test_revoke_persists(tmp_path: Path):
    db = str(tmp_path / "intent_grants.db")
    s1 = IntentGrantStore(db_path=db)
    await s1.start()
    g = await s1.issue_grant("ezri", "run_python")
    await s1.revoke_grant(g.id)
    await s1.stop()

    s2 = IntentGrantStore(db_path=db)
    await s2.start()
    # Soft-revoked grant is not loaded as active.
    assert s2.is_granted_sync("ezri", "run_python") is False
    assert await s2.list_grants(active_only=True) == []
    # ...but retained for audit.
    all_grants = await s2.list_grants(active_only=False)
    assert len(all_grants) == 1
    assert all_grants[0].revoked is True
    # With a real DB, revoking an unknown id returns False (rowcount==0).
    assert await s2.revoke_grant("missing-id") is False
    await s2.stop()
