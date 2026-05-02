"""AD-456 Security Infrastructure tests.

Covers:
- 3 new EventTypes
- SecurityInfraConfig defaults
- CredentialStore rotation + JSON store + SECRET_ROTATED emission
- EgressPolicy allowlist/denylist/deny_by_default + EGRESS_BLOCKED emission
- AuditLog hash chain + verify_chain tamper detection + AUDIT_RECORDED emission
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from probos.config import SecurityInfraConfig
from probos.credential_store import CredentialSpec, CredentialStore
from probos.events import EventType
from probos.security.audit import AuditLog
from probos.security.egress import EgressDecision, EgressPolicy


# ----- EventTypes -----


def test_event_type_secret_rotated_exists():
    assert EventType.SECRET_ROTATED.value == "secret_rotated"


def test_event_type_egress_blocked_exists():
    assert EventType.EGRESS_BLOCKED.value == "egress_blocked"


def test_event_type_audit_recorded_exists():
    assert EventType.AUDIT_RECORDED.value == "audit_recorded"


# ----- Config -----


def test_security_infra_config_defaults():
    cfg = SecurityInfraConfig()
    assert cfg.secrets_persistence_enabled is True
    assert cfg.secrets_store_filename == "secrets.json"
    assert cfg.egress_enabled is True
    assert cfg.egress_deny_by_default is True
    assert cfg.audit_enabled is True


# ----- CredentialStore extension -----


def test_credential_store_rotate_persists_to_store(tmp_path, monkeypatch):
    # Ensure no env var collides with the test key
    monkeypatch.delenv("AD456_TEST_KEY", raising=False)
    store_path = tmp_path / "secrets.json"
    emit = MagicMock()
    store = CredentialStore(store_path=store_path, emit_event=emit)
    store.register(CredentialSpec(name="ad456_test_key", description="test"))

    rotated = store.rotate("ad456_test_key", "v1")

    assert rotated is True
    assert store_path.exists()
    assert store.get("ad456_test_key") == "v1"

    emit.assert_called_once()
    event_type, payload = emit.call_args[0]
    assert event_type == EventType.SECRET_ROTATED
    assert payload["name"] == "ad456_test_key"
    assert payload["source"] == "store"
    assert payload["persisted"] is True


def test_credential_store_rotate_skipped_when_env_set(tmp_path, monkeypatch):
    store_path = tmp_path / "secrets.json"
    emit = MagicMock()
    store = CredentialStore(store_path=store_path, emit_event=emit)
    store.register(CredentialSpec(name="ad456_envset", env_var="AD456_ENVSET"))
    monkeypatch.setenv("AD456_ENVSET", "from-env")

    rotated = store.rotate("ad456_envset", "ignored")

    assert rotated is False
    assert not store_path.exists()
    emit.assert_called_once()
    _, payload = emit.call_args[0]
    assert payload["source"] == "env"
    assert payload["persisted"] is False


def test_credential_store_rotate_returns_false_when_no_store_path():
    emit = MagicMock()
    store = CredentialStore(emit_event=emit)  # no store_path
    store.register(CredentialSpec(name="ad456_no_store"))

    rotated = store.rotate("ad456_no_store", "v1")

    assert rotated is False
    emit.assert_called_once()
    _, payload = emit.call_args[0]
    assert payload["source"] == "no_store"
    assert payload["persisted"] is False


def test_credential_store_resolution_chain_includes_store(tmp_path, monkeypatch):
    monkeypatch.delenv("AD456_CHAIN_KEY", raising=False)
    store_path = tmp_path / "secrets.json"
    store = CredentialStore(store_path=store_path)
    store.register(
        CredentialSpec(
            name="ad456_chain_key",
            env_var="AD456_CHAIN_KEY",  # absent in env
        )
    )
    # Persist via rotate so resolution chain reads from JSON store
    store.rotate("ad456_chain_key", "from-store")

    assert store.get("ad456_chain_key") == "from-store"


# ----- EgressPolicy -----


def test_egress_policy_default_allowlist_includes_localhost():
    policy = EgressPolicy()
    assert policy.is_allowed("http://127.0.0.1:8080/v1") is True
    assert policy.is_allowed("http://localhost:8000") is True
    assert policy.is_allowed("http://[::1]:9000/healthz") is True


def test_egress_policy_denylist_blocks_match():
    emit = MagicMock()
    policy = EgressPolicy(emit_event=emit)
    policy.deny_host("evil.com")
    policy.allow_host("evil.com")  # denylist precedes allowlist

    decision = policy.check("https://evil.com/x")

    assert isinstance(decision, EgressDecision)
    assert decision.allowed is False
    assert decision.matched_rule == "evil.com"
    assert "denylist" in decision.reason

    emit.assert_called_once()
    event_type, payload = emit.call_args[0]
    assert event_type == EventType.EGRESS_BLOCKED
    assert payload["matched_rule"] == "evil.com"


def test_egress_policy_deny_by_default_blocks_unknown():
    emit = MagicMock()
    policy = EgressPolicy(emit_event=emit)  # deny_by_default=True
    decision = policy.check("https://unknown.example.com/x")

    assert decision.allowed is False
    assert "deny_by_default" in decision.reason
    assert emit.call_count == 1
    event_type, payload = emit.call_args[0]
    assert event_type == EventType.EGRESS_BLOCKED


def test_egress_policy_allow_by_default_permits_unknown():
    emit = MagicMock()
    policy = EgressPolicy(emit_event=emit, deny_by_default=False)
    decision = policy.check("https://unknown.example.com/x")

    assert decision.allowed is True
    emit.assert_not_called()


# ----- AuditLog -----


def test_audit_log_append_creates_chained_entry():
    emit = MagicMock()
    log = AuditLog(emit_event=emit)

    e1 = log.append(category="auth", detail="login user=alice")
    e2 = log.append(category="auth", detail="logout user=alice")

    assert e1.sequence == 0
    assert e1.prior_hash == AuditLog.GENESIS_HASH
    assert e2.sequence == 1
    assert e2.prior_hash == e1.entry_hash
    assert e1.entry_hash != e2.entry_hash

    assert emit.call_count == 2
    for call in emit.call_args_list:
        event_type, payload = call.args
        assert event_type == EventType.AUDIT_RECORDED
        assert "sequence" in payload
        assert "entry_hash" in payload


def test_audit_log_verify_chain_detects_tamper():
    log = AuditLog()
    log.append(category="a", detail="x")
    log.append(category="b", detail="y")
    log.append(category="c", detail="z")

    assert log.verify_chain() is True

    # Tamper a middle entry's detail (frozen dataclass; rebuild via list replace)
    tampered = AuditEntry_replace(log.entries[1], detail="MUTATED")
    log.entries[1] = tampered

    assert log.verify_chain() is False


def test_audit_log_verify_chain_detects_genesis_tamper():
    log = AuditLog()
    log.append(category="a", detail="x")
    log.append(category="b", detail="y")
    log.append(category="c", detail="z")

    # Mutate first entry's prior_hash to non-GENESIS value
    tampered = AuditEntry_replace(log.entries[0], prior_hash="f" * 64)
    log.entries[0] = tampered

    assert log.verify_chain() is False


def test_audit_log_verify_chain_intact_after_appends():
    log = AuditLog()
    for i in range(5):
        log.append(category="evt", detail=f"item-{i}")
    assert log.verify_chain() is True


# Frozen dataclass replace helper (avoids importing dataclasses.replace at top)
def AuditEntry_replace(entry, **changes):
    from dataclasses import replace
    return replace(entry, **changes)
