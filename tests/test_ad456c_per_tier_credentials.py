"""AD-456c: Per-tier credential lookup tests."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from probos.credential_store import (
    CredentialSpec,
    CredentialStore,
    _AGENCY_ORDER,
)
from probos.events import EventType


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_store(*, with_emit: bool = True) -> tuple[CredentialStore, MagicMock]:
    """Build a CredentialStore with no config/event_log and an attached emit."""
    emit = MagicMock()
    store = CredentialStore(emit_event=emit if with_emit else None)
    return store, emit


def _set_env(monkeypatch: pytest.MonkeyPatch, name: str, value: str) -> None:
    monkeypatch.setenv(name, value)


# ---------------------------------------------------------------------------
# Spec defaults / backwards compat
# ---------------------------------------------------------------------------

def test_credential_spec_default_min_tier_is_none() -> None:
    """New ``min_tier`` field defaults to None -- preserves AD-395/AD-456 contract."""
    spec = CredentialSpec(name="custom", env_var="CUSTOM_TOKEN")
    assert spec.min_tier is None


def test_register_with_min_tier_persists_on_spec() -> None:
    store, _ = _make_store(with_emit=False)
    spec = CredentialSpec(name="ops_secret", env_var="OPS_SECRET", min_tier="autonomous")
    store.register(spec)

    assert store._specs["ops_secret"].min_tier == "autonomous"


def test_existing_builtin_specs_have_no_min_tier() -> None:
    """github / discord / llm_api are ungated v1 -- flipping defaults is AD-456c-N."""
    store, _ = _make_store(with_emit=False)

    for name in ("github", "discord", "llm_api"):
        assert store._specs[name].min_tier is None, (
            f"built-in spec {name!r} unexpectedly has min_tier -- "
            "AD-456c v1 must preserve AD-395 ungated defaults"
        )


def test_set_tier_enforcement_toggles_flag() -> None:
    store, _ = _make_store(with_emit=False)
    assert store._tier_enforcement is False

    store.set_tier_enforcement(True)
    assert store._tier_enforcement is True

    store.set_tier_enforcement(False)
    assert store._tier_enforcement is False


# ---------------------------------------------------------------------------
# Backwards compat -- enforcement off
# ---------------------------------------------------------------------------

def test_get_no_min_tier_no_enforcement_resolves(monkeypatch: pytest.MonkeyPatch) -> None:
    """Default-everything: spec ungated, enforcement off. AD-456 baseline."""
    store, _ = _make_store(with_emit=False)
    store.register(CredentialSpec(name="custom", env_var="CUSTOM_TOKEN"))
    _set_env(monkeypatch, "CUSTOM_TOKEN", "value-1")

    assert store.get("custom", requester="t") == "value-1"


def test_get_min_tier_enforcement_off_resolves_regardless_of_tier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Spec carries min_tier but enforcement is OFF -> tier is ignored.

    Locks AD-456c v1 default-False migration safety: deployments may register
    specs with min_tier before flipping the enforcement flag.
    """
    store, emit = _make_store()
    store.register(
        CredentialSpec(name="ops_secret", env_var="OPS_SECRET", min_tier="autonomous")
    )
    _set_env(monkeypatch, "OPS_SECRET", "ops-value")

    # Caller passes a too-low tier -- but enforcement is off, so resolves.
    assert store.get("ops_secret", requester="t", tier="reactive") == "ops-value"
    # No CREDENTIAL_TIER_DENIED emitted on the no-op path.
    assert not any(
        c.args and c.args[0] == EventType.CREDENTIAL_TIER_DENIED
        for c in emit.call_args_list
    )


# ---------------------------------------------------------------------------
# Enforcement on -- gate semantics
# ---------------------------------------------------------------------------

def test_get_min_tier_enforcement_on_allows_equal_tier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, _ = _make_store(with_emit=False)
    store.register(
        CredentialSpec(name="ops_secret", env_var="OPS_SECRET", min_tier="autonomous")
    )
    _set_env(monkeypatch, "OPS_SECRET", "ops-value")
    store.set_tier_enforcement(True)

    assert store.get("ops_secret", requester="t", tier="autonomous") == "ops-value"


def test_get_min_tier_enforcement_on_allows_higher_tier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, _ = _make_store(with_emit=False)
    store.register(
        CredentialSpec(name="ops_secret", env_var="OPS_SECRET", min_tier="autonomous")
    )
    _set_env(monkeypatch, "OPS_SECRET", "ops-value")
    store.set_tier_enforcement(True)

    assert store.get("ops_secret", requester="t", tier="unrestricted") == "ops-value"


def test_get_min_tier_enforcement_on_denies_lower_tier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, _ = _make_store(with_emit=False)
    store.register(
        CredentialSpec(name="ops_secret", env_var="OPS_SECRET", min_tier="autonomous")
    )
    _set_env(monkeypatch, "OPS_SECRET", "ops-value")
    store.set_tier_enforcement(True)

    assert store.get("ops_secret", requester="t", tier="suggestive") is None


def test_get_min_tier_enforcement_on_no_tier_passed_denies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Fail-closed: when enforcement is on and the spec is gated, caller MUST
    pass ``tier=`` or the lookup is denied. Locks the AD-456c-2 forcing
    function -- caller-side tier propagation is mandatory before any
    production deployment flips the flag to True.
    """
    store, _ = _make_store(with_emit=False)
    store.register(
        CredentialSpec(name="ops_secret", env_var="OPS_SECRET", min_tier="autonomous")
    )
    _set_env(monkeypatch, "OPS_SECRET", "ops-value")
    store.set_tier_enforcement(True)

    # tier=None (default) -> deny.
    assert store.get("ops_secret", requester="t") is None


# ---------------------------------------------------------------------------
# Event + audit emission
# ---------------------------------------------------------------------------

def test_credential_tier_denied_event_emitted_on_deny(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, emit = _make_store()
    store.register(
        CredentialSpec(name="ops_secret", env_var="OPS_SECRET", min_tier="autonomous")
    )
    _set_env(monkeypatch, "OPS_SECRET", "ops-value")
    store.set_tier_enforcement(True)

    assert store.get("ops_secret", requester="ensign-007", tier="reactive") is None

    denied_calls = [
        c for c in emit.call_args_list
        if c.args and c.args[0] == EventType.CREDENTIAL_TIER_DENIED
    ]
    assert len(denied_calls) == 1
    payload = denied_calls[0].args[1]
    assert payload == {
        "name": "ops_secret",
        "requester": "ensign-007",
        "requested_tier": "reactive",
        "required_tier": "autonomous",
    }


# ---------------------------------------------------------------------------
# Fail-safe -- unknown tier strings + introspection respect gate
# ---------------------------------------------------------------------------

def test_unknown_tier_string_denies_when_enforcement_on(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unknown tier strings (operator typo, future-tier values) resolve to
    ordinal -1 via ``_AGENCY_ORDER.get(name, -1)`` and are denied. Locks
    the fail-safe contract -- never grant access on garbled tier input.
    """
    store, _ = _make_store(with_emit=False)
    store.register(
        CredentialSpec(name="ops_secret", env_var="OPS_SECRET", min_tier="suggestive")
    )
    _set_env(monkeypatch, "OPS_SECRET", "ops-value")
    store.set_tier_enforcement(True)

    # Sanity: unknown tier maps to -1 sentinel.
    assert _AGENCY_ORDER.get("captain-mode", -1) == -1
    # And lookup is denied.
    assert store.get("ops_secret", requester="t", tier="captain-mode") is None


def test_available_respects_tier_gate_when_enforcement_on(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``CredentialStore.available`` calls ``get`` internally with
    ``requester='availability_check'`` and no ``tier`` kwarg. With
    enforcement on and a spec carrying ``min_tier``, ``available`` MUST
    return False (no information leak about a restricted credential's
    underlying resolvability beyond the bare ``list_credentials`` name
    surface).
    """
    store, _ = _make_store(with_emit=False)
    store.register(
        CredentialSpec(name="ops_secret", env_var="OPS_SECRET", min_tier="autonomous")
    )
    _set_env(monkeypatch, "OPS_SECRET", "ops-value")
    store.set_tier_enforcement(True)

    # Without enforcement, available would return True (env var resolves).
    # With enforcement on AND no tier passed, get() denies -> available False.
    assert store.available("ops_secret") is False
