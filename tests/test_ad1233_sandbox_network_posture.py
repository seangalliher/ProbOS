"""AD-1233 (#1186): the sandbox network posture is a decision, and says so.

`allow_network=False` sets four blackhole proxy variables. `requests` and
`httpx` honour them, which is why the block holds for every agent actually
running; a raw socket ignores them. That has always been true and always been
documented -- what was missing was a *reason*, and #1177 explicitly reserved the
question for the Captain rather than burying it under a wording fix.

The Captain's answer: keep it soft, because the governed way out already exists.
AD-1221's fetch broker performs the ordinary mesh fetch with SSRF validation,
per-domain rate limiting and audit. Hardening Tier 1 would push agents back
toward smuggling bytes through their own context window -- the exact cost
AD-1221 was built to remove -- and would buy little, because the threat model
here is a confused agent rather than a hostile one: code reaching the sandbox
has already passed approval-gated install and the tier-3 gate.

Design Principle 13(a): *a capability ceiling must be a decision, never an
inheritance. Every constraint states what it defends and what it costs.* These
tests assert that the constraint now carries both, because the failure mode this
guards against is not the proxy hint -- it is a later AD reading "no network
access" as an enforced boundary and building on it. That has already happened
once (AD-1217), which is why #1186 existed at all.
"""

from __future__ import annotations

import inspect

from probos.execution.isolation import ExecutionRequest, SubprocessSandbox


def _env(*, allow_network: bool) -> dict[str, str]:
    return SubprocessSandbox._build_env(
        ExecutionRequest(code="pass", allow_network=allow_network)
    )


# ── behaviour is unchanged ────────────────────────────────────────


def test_the_deterrent_is_still_applied_when_network_is_off() -> None:
    """Decision (c) is "keep it soft", not "remove it". The four variables are
    what makes a casual requests.get() fail fast and push the agent to the
    broker.
    """
    env = _env(allow_network=False)
    for key in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY"):
        assert env[key] == "http://127.0.0.1:9"
    assert env["no_proxy"] == ""


def test_nothing_is_applied_when_network_is_allowed() -> None:
    env = _env(allow_network=True)
    assert "http_proxy" not in env
    assert "HTTPS_PROXY" not in env


# ── the constraint states what it defends and what it costs ───────


def test_the_posture_records_why_it_is_soft() -> None:
    """Without a stated reason this is indistinguishable from an oversight, and
    the next reviewer either "fixes" it or builds on it. Both are wrong.
    """
    src = inspect.getsource(SubprocessSandbox._build_env)
    assert "AD-1233" in src
    # AD-1221 is the fetch broker -- the governed way out that makes keeping
    # this soft the right call rather than merely the easy one.
    assert "AD-1221" in src


def test_the_posture_records_what_it_costs() -> None:
    """The honest half. A constraint that only advertises what it defends is how
    AD-1217 happened -- a description read as a guarantee.
    """
    src = inspect.getsource(SubprocessSandbox._build_env)
    assert "What it defends" in src
    assert "What it costs" in src
    assert "raw socket is unimpeded" in src


def test_the_field_comment_does_not_promise_tier_two_enforcement() -> None:
    """The old comment read "hard at Tier 2", which describes a tier that is a
    stub (#939, waiting on MXC). Pointing at unbuilt enforcement is how a soft
    control gets cited as a hard one.
    """
    src = inspect.getsource(ExecutionRequest)
    assert "hard at Tier 2" not in src
    assert "AD-1233" in src


def test_no_surface_claims_the_sandbox_has_no_network_access() -> None:
    """The specific false sentence AD-1217 removed. BF-728 was an agent telling
    the Captain this; it must not return as a comment a future AD relies on.
    """
    from probos.execution import isolation
    from probos.tools import code_execution_tool

    for mod in (isolation, code_execution_tool):
        src = inspect.getsource(mod)
        # Allowed only where it is explicitly quoted as the WRONG claim.
        for line in src.splitlines():
            if "HAS NO NETWORK ACCESS" in line:
                assert "AD-1217" in src, mod.__name__
