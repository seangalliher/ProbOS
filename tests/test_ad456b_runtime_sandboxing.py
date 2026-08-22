"""AD-456b: Runtime Sandboxing tests."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from probos.config import SystemConfig
from probos.events import EventType
from probos.security.runtime_sandbox import (
    CapabilityDenied,
    RuntimeSandbox,
    SandboxLimits,
    SandboxOutcome,
    check_capability,
    require_capability,
)


# --- RuntimeSandbox happy path -------------------------------------------------

@pytest.mark.asyncio
async def test_execute_returns_success_outcome_for_normal_coroutine() -> None:
    sandbox = RuntimeSandbox()

    async def work() -> int:
        return 42

    outcome = await sandbox.execute(work, limits=SandboxLimits(wall_timeout_seconds=5.0))

    assert outcome.success is True
    assert outcome.result == 42
    assert outcome.error == ""
    assert outcome.limit_exceeded == ""
    assert outcome.capability_denied == ""
    assert outcome.wall_ms >= 0
    assert outcome.peak_memory_kb >= 0


# --- Wall timeout enforcement --------------------------------------------------

@pytest.mark.asyncio
async def test_execute_returns_wall_timeout_outcome_and_emits_event() -> None:
    emit_event = MagicMock()
    sandbox = RuntimeSandbox(emit_event=emit_event)

    async def slow() -> None:
        await asyncio.sleep(2.0)

    outcome = await sandbox.execute(
        slow,
        limits=SandboxLimits(wall_timeout_seconds=0.05, memory_peak_mb=256.0),
    )

    assert outcome.success is False
    assert outcome.limit_exceeded == "wall"
    assert "wall timeout" in outcome.error
    emit_event.assert_called_once()
    args, kwargs = emit_event.call_args
    assert args[0] == EventType.SANDBOX_LIMIT_EXCEEDED
    assert args[1]["kind"] == "wall"


# --- Memory peak detection -----------------------------------------------------

@pytest.mark.asyncio
async def test_execute_returns_memory_outcome_when_peak_exceeds_cap() -> None:
    emit_event = MagicMock()
    sandbox = RuntimeSandbox(emit_event=emit_event)

    async def alloc_big() -> int:
        # Allocate ~2 MB to overshoot a 0.001 MB (1 KB) cap deterministically.
        big = bytearray(2 * 1024 * 1024)
        return len(big)

    outcome = await sandbox.execute(
        alloc_big,
        limits=SandboxLimits(wall_timeout_seconds=10.0, memory_peak_mb=0.001),
    )

    assert outcome.success is False
    assert outcome.limit_exceeded == "memory"
    assert "peak memory" in outcome.error
    emit_event.assert_called_once()
    assert emit_event.call_args[0][1]["kind"] == "memory"


# --- Capability check ----------------------------------------------------------

@pytest.mark.asyncio
async def test_check_capability_returns_true_when_present() -> None:
    sandbox = RuntimeSandbox()

    async def work() -> bool:
        return check_capability("net.read")

    outcome = await sandbox.execute(
        work,
        limits=SandboxLimits(wall_timeout_seconds=5.0),
        capabilities=frozenset({"net.read"}),
    )

    assert outcome.success is True
    assert outcome.result is True


@pytest.mark.asyncio
async def test_check_capability_returns_false_when_missing() -> None:
    sandbox = RuntimeSandbox()

    async def work() -> bool:
        return check_capability("fs.write")

    outcome = await sandbox.execute(
        work,
        limits=SandboxLimits(wall_timeout_seconds=5.0),
        capabilities=frozenset({"net.read"}),
    )

    assert outcome.success is True
    assert outcome.result is False


@pytest.mark.asyncio
async def test_require_capability_raises_and_emits_when_missing() -> None:
    emit_event = MagicMock()
    sandbox = RuntimeSandbox(emit_event=emit_event)

    async def work() -> None:
        require_capability("fs.write", emit_event=emit_event)

    outcome = await sandbox.execute(
        work,
        limits=SandboxLimits(wall_timeout_seconds=5.0),
        capabilities=frozenset({"net.read"}),
    )

    assert outcome.success is False
    assert outcome.capability_denied == "fs.write"
    # SANDBOX_CAPABILITY_DENIED should have fired exactly once via require_capability.
    capability_denied_calls = [
        c for c in emit_event.call_args_list
        if c.args and c.args[0] == EventType.SANDBOX_CAPABILITY_DENIED
    ]
    assert len(capability_denied_calls) == 1
    assert capability_denied_calls[0].args[1] == {"capability": "fs.write"}


@pytest.mark.asyncio
async def test_check_capability_outside_sandbox_returns_true() -> None:
    # Consultation is no-op outside a sandbox — preserves drop-in safety
    # for code paths that consult check_capability without a wrapping sandbox.
    assert check_capability("anything") is True


# --- Context isolation ---------------------------------------------------------

@pytest.mark.asyncio
async def test_capability_context_is_reset_after_execute() -> None:
    sandbox = RuntimeSandbox()

    async def work() -> None:
        return None

    await sandbox.execute(
        work,
        limits=SandboxLimits(wall_timeout_seconds=5.0),
        capabilities=frozenset({"net.read"}),
    )

    # Outside the sandbox the context is reset.
    assert check_capability("net.read") is True  # no-active-context path
    # Confirm no leakage by running a second sandbox without capabilities.
    async def inspect() -> bool:
        return check_capability("net.read")
    outcome = await sandbox.execute(
        inspect,
        limits=SandboxLimits(wall_timeout_seconds=5.0),
    )
    assert outcome.result is False


# --- HttpFetchAgent egress integration ----------------------------------------


@pytest.fixture
def _public_dns(monkeypatch):
    """BF-828 (#1292): resolve the test host WITHOUT touching the network.

    These assertions are about the EGRESS policy. The SSRF guard runs first and
    resolves the hostname for real (``security/url_guard.py:92``), so a resolver
    hiccup on the gate machine turned an egress assertion into::

        assert 'Egress policy' in 'Cannot resolve hostname: example.com'

    Observed on a full gate run; it passed in isolation and on a re-run, so it
    was purely a network flake — and a rotating false red on the gate trains
    the reader to dismiss gate failures, which is how a real regression gets
    waved through.

    A public address is returned so the guard's private-range checks still run
    exactly as they would against the real host.
    """
    import socket as _socket

    real = _socket.getaddrinfo

    def _fake(host, port, *args, **kwargs):
        if host in ("example.com", "allowed.example.com"):
            return [(_socket.AF_INET, _socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0))]
        return real(host, port, *args, **kwargs)

    monkeypatch.setattr(_socket, "getaddrinfo", _fake)
    return _fake


def test_httpfetchagent_validate_url_blocks_when_egress_policy_denies(
    _public_dns,
) -> None:
    from probos.agents.http_fetch import HttpFetchAgent
    from probos.security.egress import EgressPolicy

    policy = EgressPolicy(
        allowlist=["allowed.example.com"],
        deny_by_default=True,
    )
    HttpFetchAgent.set_egress_policy(policy)
    try:
        agent = HttpFetchAgent(pool="http")
        # A host that passes the SSRF guards (public address, stubbed above)
        # and fails the egress check.
        error = agent._validate_url("https://example.com/")
        assert error is not None
        assert "Egress policy" in error
        assert "AD-456b" in error
    finally:
        HttpFetchAgent.set_egress_policy(None)


def test_httpfetchagent_validate_url_passes_when_egress_policy_allows(
    _public_dns,
) -> None:
    from probos.agents.http_fetch import HttpFetchAgent
    from probos.security.egress import EgressPolicy

    policy = EgressPolicy(
        allowlist=["example.com"],
        deny_by_default=True,
    )
    HttpFetchAgent.set_egress_policy(policy)
    try:
        agent = HttpFetchAgent(pool="http")
        error = agent._validate_url("https://example.com/")
        # BF-828: the resolution is stubbed, so this is now an exact assertion
        # rather than "None or some other error" -- which would have passed
        # against a DNS failure and so could not tell allow from unreachable.
        assert error is None, error
    finally:
        HttpFetchAgent.set_egress_policy(None)


def test_httpfetchagent_egress_policy_default_none_preserves_ad456_behavior() -> None:
    from probos.agents.http_fetch import HttpFetchAgent

    # Default ClassVar value — AD-456 v1 consultation-only behavior preserved.
    HttpFetchAgent.set_egress_policy(None)
    assert HttpFetchAgent._egress_policy is None


# --- Config + finalize wiring --------------------------------------------------

def test_security_infra_config_defaults_match_v1_contract() -> None:
    config = SystemConfig()
    assert config.security_infra.sandbox_enabled is True
    assert config.security_infra.sandbox_default_wall_timeout_seconds == 30.0
    assert config.security_infra.sandbox_default_memory_peak_mb == 256.0
    # egress_active_enforcement defaults to False — preserves AD-456 v1 behavior
    # on existing deployments per AD-456b DLog.
    assert config.security_infra.egress_active_enforcement is False
