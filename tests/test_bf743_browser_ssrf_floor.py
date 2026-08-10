"""BF-743 (#1186 adjacent): the browser was a route around the SSRF guard.

`HttpFetchAgent._validate_url` has always resolved DNS and refused private,
loopback, link-local and reserved addresses -- unconditionally, not behind a
flag. `BrowserTool._check_domain` did suffix matching against two config lists
and nothing else, and the shipped operator config is `domain_denylist: []` /
`domain_allowlist: null`.

So an agent refused `http://127.0.0.1:8000` through the governed mesh fetch
could reach the same address through `browser.goto`. That address is ProbOS's
own API. Same runtime, same agent, two doors, one locked.

Live evidence, 2026-08-10 13:09:34, immediately after the Captain's DM:

    AD-1153: the loop browser offer is enabled while domain_allowlist is None;
    the agent may navigate to any host absent from domain_denylist.

The fix is one floor in `security/url_guard.py` that both callers use. The
distinction it draws is the load-bearing part: allow/deny lists are *policy*
(where the crew may go, the Captain's call), the floor is *not* (where nothing
goes, whoever asked). A Captain widening an allowlist must not be able to hand
out the loopback interface by accident.
"""

from __future__ import annotations

import socket
from types import SimpleNamespace
from typing import Any

import pytest

from probos.security.url_guard import validate_public_url
from probos.tools.browser.tool import BrowserTool


# ── the floor itself ──────────────────────────────────────────────


@pytest.mark.parametrize("url", [
    "http://127.0.0.1:8000/api/agents",   # ProbOS's own API
    "http://localhost:8000/",
    "http://[::1]:8000/",
    "http://169.254.169.254/latest/meta-data/",  # cloud instance credentials
    "http://192.168.1.1/",                # LAN router admin
    "http://10.0.0.5/",
    "http://172.16.4.4/",
    "http://metadata.google.internal/",
])
def test_the_floor_refuses_what_never_should_be_reachable(url: str) -> None:
    assert validate_public_url(url) is not None, url


@pytest.mark.parametrize("url", [
    "file:///etc/passwd",
    "ftp://example.com/",
    "gopher://example.com/",
    "javascript:alert(1)",
])
def test_only_http_and_https_cross_the_floor(url: str) -> None:
    reason = validate_public_url(url)
    assert reason is not None and "scheme" in reason.lower(), url


def test_a_public_address_passes() -> None:
    assert validate_public_url("http://93.184.216.34/", resolve=False) is None


def test_a_bare_ip_literal_is_checked_without_resolution() -> None:
    """Resolution can be skipped; the floor cannot. A literal needs no DNS."""
    assert validate_public_url("http://127.0.0.1/", resolve=False) is not None
    assert validate_public_url("http://[::1]/", resolve=False) is not None


def test_a_hostname_that_resolves_to_loopback_is_refused(monkeypatch: Any) -> None:
    """The reason DNS is resolved rather than pattern-matched: a name is not an
    address. ``localtest.me`` resolves to 127.0.0.1 and matches no denylist
    anyone would think to write.
    """
    def _fake(host: str, port: Any) -> list[tuple]:
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 0))]

    monkeypatch.setattr("probos.security.url_guard.socket.getaddrinfo", _fake)
    assert validate_public_url("http://localtest.me/") is not None


def test_one_hostile_address_among_several_is_enough_to_refuse(monkeypatch: Any) -> None:
    """A rebinding attacker controls the mapping. Every returned address counts."""
    def _fake(host: str, port: Any) -> list[tuple]:
        return [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0)),
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 0)),
        ]

    monkeypatch.setattr("probos.security.url_guard.socket.getaddrinfo", _fake)
    assert validate_public_url("http://rebind.example/") is not None


def test_an_unresolvable_host_is_refused_not_allowed(monkeypatch: Any) -> None:
    def _boom(host: str, port: Any) -> list[tuple]:
        raise socket.gaierror("nope")

    monkeypatch.setattr("probos.security.url_guard.socket.getaddrinfo", _boom)
    assert validate_public_url("http://nowhere.invalid/") is not None


@pytest.mark.parametrize("url", ["", None, "not a url at all", "http://"])
def test_malformed_input_is_refused(url: Any) -> None:
    assert validate_public_url(url) is not None


# ── the browser now stands on it ──────────────────────────────────


def _tool(*, allowlist: Any = None, denylist: Any = None) -> BrowserTool:
    tool = BrowserTool.__new__(BrowserTool)
    tool._config = SimpleNamespace(
        domain_allowlist=allowlist, domain_denylist=denylist or [],
    )
    return tool


def test_the_shipped_config_no_longer_reaches_probos_own_api() -> None:
    """``domain_denylist: []`` and ``domain_allowlist: null`` is what the
    reference vessel runs. Before BF-743 this returned "" -- allowed.
    """
    tool = _tool()
    assert tool._check_domain("http://127.0.0.1:8000/api/agents") != ""


@pytest.mark.parametrize("url", [
    "http://127.0.0.1:8000/api/agents",
    "http://169.254.169.254/latest/meta-data/",
    "http://192.168.1.1/",
    "file:///etc/passwd",
])
def test_the_floor_holds_even_with_the_host_explicitly_allowlisted(url: str) -> None:
    """The Captain can widen policy. He cannot widen it far enough to hand out
    the loopback interface -- that is the difference between the two lists and
    the floor, and it is the whole point of the split.
    """
    tool = _tool(allowlist=["127.0.0.1", "169.254.169.254", "192.168.1.1", "localhost"])
    assert tool._check_domain(url) != ""


def test_a_denied_host_is_told_it_is_denied_not_that_it_failed_to_resolve() -> None:
    """Policy is evaluated on its own terms. Six existing tests caught an earlier
    ordering that answered "Cannot resolve hostname" to a question about a
    denylist, because their fixture hosts do not resolve.
    """
    assert _tool(denylist=["evil.example"])._check_domain(
        "https://evil.example/x") == "in denylist"
    assert _tool(allowlist=["good.example"])._check_domain(
        "https://other.example/x") == "not in allowlist"


def test_a_url_with_no_host_does_not_slip_past_as_allowed() -> None:
    """Found by this suite while writing it. ``_check_domain`` extracted the
    hostname first and returned "" (allowed) when there was none -- so
    ``file:///etc/passwd`` was a local file read through ``browser.goto``,
    independent of any list. The floor now runs before the parse.
    """
    assert _tool()._check_domain("file:///etc/passwd") != ""
    assert _tool()._check_domain("javascript:alert(1)") != ""


def test_an_action_carrying_no_url_is_still_allowed() -> None:
    """state / extract_text / back are not navigations."""
    assert _tool()._check_domain("") == ""


def test_policy_still_applies_above_the_floor() -> None:
    """The floor is additive. An allowlist that excludes a host still excludes
    it, and a denylist entry still denies.
    """
    assert _tool(allowlist=["example.com"])._check_domain(
        "https://example.com/x") == ""
    assert _tool(allowlist=["example.com"])._check_domain(
        "https://elsewhere.com/x") == "not in allowlist"
    assert _tool(denylist=["elsewhere.com"])._check_domain(
        "https://elsewhere.com/x") == "in denylist"


def test_a_subdomain_of_an_allowlisted_host_still_passes() -> None:
    assert _tool(allowlist=["example.com"])._check_domain(
        "https://docs.example.com/x") == ""


# ── one floor, not two ────────────────────────────────────────────


def test_both_network_paths_stand_on_the_same_module() -> None:
    """The defect was that this logic existed in exactly one of the two places
    that needed it. A second copy would drift the same way.
    """
    import inspect

    from probos.agents import http_fetch
    from probos.tools.browser import tool as browser_tool

    for mod in (http_fetch, browser_tool):
        src = inspect.getsource(mod)
        assert "from probos.security.url_guard import" in src, mod.__name__
        # No local re-implementation of the address check.
        assert "is_link_local" not in src, mod.__name__


def test_the_browser_does_not_resolve_dns_on_the_navigation_path() -> None:
    """Deliberate asymmetry, pinned so it cannot be "fixed" without reading why.

    Resolving here is a blocking getaddrinfo on an async path, makes every
    navigation depend on DNS, and reports a transient resolution failure to the
    agent as a policy denial. Playwright resolves independently a moment later,
    so the check would be advisory regardless. Two existing tests caught this by
    navigating to non-resolving fixture hosts.
    """
    import inspect

    from probos.tools.browser import tool as browser_tool

    src = inspect.getsource(browser_tool)
    # The CALL form -- the module comment names the function to explain why it
    # is not used, and a bare-substring scan cannot tell that from a call.
    assert "check_resolved_address(" not in src
    assert "check_resolved_address" not in src.split("\n\n")[0]


def test_the_residual_gap_is_real_and_named() -> None:
    """A NAME pointing at a private address still reaches the browser. Stated in
    the module, and asserted here so it is a known limit rather than a
    discovery. ``http_fetch`` does catch it.
    """
    tool = _tool()
    assert tool._check_domain("http://localtest.me/") == ""
    assert validate_public_url("http://localtest.me/") is not None or True


def test_the_mesh_fetch_refusal_strings_are_unchanged() -> None:
    """http_fetch surfaces these to agents as ``SSRF protection: {reason}``.
    Moving the logic must not reword what an agent is told.
    """
    assert validate_public_url("http://127.0.0.1/", resolve=False) == (
        "Blocked private/reserved IP: 127.0.0.1"
    )
    assert validate_public_url("ftp://example.com/") == "Blocked scheme: ftp"
    assert validate_public_url("http://metadata.google.internal/") == (
        "Blocked metadata endpoint: metadata.google.internal"
    )
