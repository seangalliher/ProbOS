"""AD-1235: a bounded browser egress policy, chosen rather than defaulted.

`domain_allowlist` shipped `None` -- allow-all -- and the AD-1153 warning said
so at every boot. BF-743 closed the floor beneath it: loopback, private ranges,
`file://` and metadata hosts are refused whatever the lists say. But the floor
cannot stop a NAME that resolves to a private address, and it has no opinion at
all about the open internet.

The selection rule, because a list without one becomes whatever was convenient
last: a site an agent needs in order to do the work the Captain asks for,
weighted toward authored content over user-submitted. **Prompt injection travels
through page text, so every page an agent reads is a page that can address it.**
That is the real argument for keeping this short rather than comprehensive, and
it is why vendor documentation outranks forums here.

The shipped default stays `None`. Narrowing an existing deployment silently is
its own defect, and Design Principle 13 says a ceiling must be a decision. The
reference vessel adopts the list in `config/system.yaml`; everyone else opts in.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from probos.config import BrowserToolConfig
from probos.tools.browser.tool import BrowserTool


def _tool(allowlist: Any) -> BrowserTool:
    tool = BrowserTool.__new__(BrowserTool)
    tool._config = SimpleNamespace(domain_allowlist=allowlist, domain_denylist=[])
    return tool


_TRUSTED = BrowserToolConfig.trusted_agentic_domains()


# ── the list is a decision, not a default ─────────────────────────


def test_the_shipped_default_is_still_open() -> None:
    """Narrowing an existing deployment silently is its own defect. The list is
    available and adopted by the reference vessel; it is not imposed.
    """
    assert BrowserToolConfig().domain_allowlist is None


def test_the_curated_list_is_reachable_from_config() -> None:
    assert isinstance(_TRUSTED, list)
    assert len(_TRUSTED) >= 30


def test_every_entry_is_a_bare_registrable_domain() -> None:
    """Suffix matching means `github.com` already covers `docs.github.com`. A
    scheme, path or leading dot would match nothing and fail silently.
    """
    for d in _TRUSTED:
        assert d == d.lower(), d
        assert "/" not in d, d
        assert not d.startswith("."), d
        assert "://" not in d, d
        assert "*" not in d, d
        assert "." in d, d


def test_no_duplicates() -> None:
    assert len(_TRUSTED) == len(set(_TRUSTED))


def test_no_entry_is_shadowed_by_another() -> None:
    """`docs.github.com` alongside `github.com` is dead weight that reads as
    intent. Suffix matching makes the narrower entry unreachable.
    """
    shadowed = [
        a for a in _TRUSTED
        for b in _TRUSTED
        if a != b and a.endswith("." + b)
    ]
    assert shadowed == [], f"already covered by a broader entry: {shadowed}"


# ── it admits what the work needs ─────────────────────────────────


@pytest.mark.parametrize("url", [
    "https://github.com/anthropics/anthropic-sdk-python",
    "https://raw.githubusercontent.com/x/y/main/README.md",
    "https://pypi.org/project/httpx/",
    "https://files.pythonhosted.org/packages/x/httpx-0.27.0.tar.gz",
    "https://docs.python.org/3/library/asyncio.html",
    "https://developer.mozilla.org/en-US/docs/Web/API/fetch",
    "https://learn.microsoft.com/en-us/azure/",
    "https://modelcontextprotocol.io/specification",
    "https://docs.anthropic.com/en/api/messages",
    "https://en.wikipedia.org/wiki/Bayesian_inference",
])
def test_the_sites_an_agent_actually_needs_are_admitted(url: str) -> None:
    assert _tool(_TRUSTED)._check_domain(url) == ""


def test_subdomains_are_covered_without_being_listed() -> None:
    for url in (
        "https://docs.github.com/en/rest",
        "https://gist.githubusercontent.com/x/raw/y",
        "https://doc.rust-lang.org/book/",
    ):
        assert _tool(_TRUSTED)._check_domain(url) == "", url


# ── and refuses what it does not ──────────────────────────────────


@pytest.mark.parametrize("url", [
    "https://pastebin.com/raw/abc",
    "https://example-exfil.test/collect?data=secrets",
    "https://discord.com/api/webhooks/x/y",
    "https://t.me/somechannel",
])
def test_an_unlisted_host_is_refused_with_a_readable_reason(url: str) -> None:
    """The refusal names the reason so the Captain can add the host rather than
    widening back to null.
    """
    assert _tool(_TRUSTED)._check_domain(url) == "not in allowlist"


def test_a_lookalike_domain_does_not_pass_as_a_listed_one() -> None:
    """Suffix matching must anchor on a dot boundary, or `evil-github.com` and
    `github.com.evil.test` both slip through.
    """
    for url in (
        "https://evil-github.com/x",
        "https://github.com.evil.test/x",
        "https://notpypi.org/x",
    ):
        assert _tool(_TRUSTED)._check_domain(url) == "not in allowlist", url


# ── the BF-743 floor still runs underneath ────────────────────────


@pytest.mark.parametrize("url", [
    "http://127.0.0.1:8000/api/agents",
    "http://192.168.1.1/",
    "file:///etc/passwd",
    "http://169.254.169.254/latest/meta-data/",
])
def test_the_address_floor_is_not_weakened_by_having_an_allowlist(url: str) -> None:
    """An allowlist is policy. The floor is not, and adding policy must not
    displace it -- these are refused for a reason the lists cannot express.
    """
    reason = _tool(_TRUSTED)._check_domain(url)
    assert reason != ""
    assert reason != "not in allowlist"


def test_allow_all_still_means_allow_all_above_the_floor() -> None:
    """The operator who has not adopted the list is unchanged."""
    assert _tool(None)._check_domain("https://pastebin.com/raw/abc") == ""
    assert _tool(None)._check_domain("http://127.0.0.1:8000/") != ""
