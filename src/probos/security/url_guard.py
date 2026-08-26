"""BF-743: one URL safety floor, used by every path that can reach the network.

`HttpFetchAgent._validate_url` has always resolved DNS and refused private,
loopback, link-local and reserved addresses, unconditionally and regardless of
configuration. `BrowserTool._check_domain` did string suffix matching against
two config lists and nothing else. On the shipped defaults (`domain_denylist:
[]`, `domain_allowlist: null`) that meant an agent refused `http://127.0.0.1:8000`
through the governed mesh fetch could reach the same address through
`browser.goto` -- including ProbOS's own API, which is how a browser offer
became a route around the mesh's own governance.

That is not a posture choice. Domain allow/deny lists express *policy* -- where
the crew may go. This module expresses the *floor* -- where nothing may go,
whoever asked and however it was configured. Keeping them separate is the point:
a Captain widening an allowlist should not be able to hand out the loopback
interface by accident.

DNS is resolved rather than pattern-matched because a name is not an address.
`localtest.me` resolves to 127.0.0.1 and matches no denylist anyone would write,
and a rebinding attacker controls the mapping rather than the string.
"""

from __future__ import annotations

import ipaddress
import logging
import socket
from dataclasses import dataclass
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

# Hostnames that serve cloud instance credentials. Blocked by name as well as by
# address because the address check depends on resolution succeeding.
BLOCKED_HOSTS = frozenset({
    "metadata.google.internal",
    "metadata.goog",
})

ALLOWED_SCHEMES = frozenset({"http", "https"})


@dataclass(frozen=True)
class PinnedTarget:
    """A verdict together with the addresses it was reached on.

    BF-821: the floor used to resolve, judge, then throw the addresses away and
    answer about the URL *string*. httpx resolved the name again when it
    connected, so a nameserver answering differently for the two lookups put a
    connection on loopback with the guard's blessing -- reproduced end to end.
    Handing back what was judged is what lets a caller connect to it.

    ``addresses`` is in getaddrinfo order and is non-empty whenever ``reason``
    is None and the URL had a hostname. That is enforced rather than merely
    documented: review measured a shape where every getaddrinfo entry failed to
    parse as an address, which approved the URL with nothing to pin and sent the
    caller back to the name -- reopening the very second lookup this exists to
    close. A hostname that resolves to nothing usable is now refused.
    """

    reason: str | None
    addresses: tuple[str, ...] = ()


def check_url_shape(url: str) -> str | None:
    """Structural refusals that need no network: scheme, host, literal address.

    Separated from resolution so a caller with its own domain policy can refuse
    on policy terms first -- a denylisted host should be told it is denied, not
    that it failed to resolve -- while still catching the cases policy cannot
    express. ``file:///etc/passwd`` has no hostname at all, so an allow/deny
    list matching on hostname never sees it.
    """
    if not url or not isinstance(url, str):
        return "No URL"

    try:
        parsed = urlparse(url)
    except Exception:
        return "Malformed URL"

    scheme = (parsed.scheme or "").lower()
    if scheme not in ALLOWED_SCHEMES:
        return f"Blocked scheme: {parsed.scheme}"

    hostname = parsed.hostname
    if not hostname:
        return "No hostname in URL"

    if hostname.lower() in BLOCKED_HOSTS:
        return f"Blocked metadata endpoint: {hostname}"

    # A bare IP literal needs no resolution to be judged.
    try:
        literal = ipaddress.ip_address(hostname.strip("[]"))
    except ValueError:
        return None
    return _reject_address(literal)


def check_resolved_address(url: str) -> str | None:
    """Resolve the hostname and refuse if ANY address it maps to is private.

    DNS is resolved rather than pattern-matched because a name is not an
    address. ``localtest.me`` resolves to 127.0.0.1 and matches no denylist
    anyone would think to write, and a rebinding attacker controls the mapping
    rather than the string. Every returned address is checked: one hostile
    answer among several is enough to refuse.
    """
    return resolve_and_pin(url).reason


def resolve_and_pin(url: str) -> PinnedTarget:
    """Resolve once, judge every address, and hand back the ones that passed.

    Same refusals as :func:`check_resolved_address` in the same order -- that
    function is now this one's verdict half, so the two cannot drift.

    BF-821: judging addresses and then answering about the URL *string* left a
    caller nothing to connect to but the name, which resolves again. Returning
    what was judged is what lets the connection be pinned to it.
    """
    try:
        hostname = urlparse(url).hostname
    except Exception:
        return PinnedTarget("Malformed URL")
    if not hostname:
        return PinnedTarget(None)

    try:
        addrinfo = socket.getaddrinfo(hostname, None)
    except socket.gaierror:
        return PinnedTarget(f"Cannot resolve hostname: {hostname}")

    approved: list[str] = []
    for _family, _type, _proto, _canon, sockaddr in addrinfo:
        try:
            ip = ipaddress.ip_address(sockaddr[0])
        except ValueError:
            continue
        reason = _reject_address(ip)
        if reason:
            return PinnedTarget(reason)
        approved.append(str(ip))

    if not approved:
        # Fail CLOSED. Returning ``PinnedTarget(None, ())`` here would approve
        # the URL with nothing to pin, and the caller would fall back to the
        # name -- which resolves a second time, which is the entire defect.
        # Reachable when getaddrinfo answers but no entry parses as an address.
        logger.warning(
            "BF-821: %s resolved to %d answer(s), none of which parsed as an "
            "address; refusing rather than approving a target that cannot be "
            "pinned",
            hostname, len(addrinfo),
        )
        return PinnedTarget(f"No usable address for hostname: {hostname}")

    return PinnedTarget(None, tuple(approved))


def validate_public_url(url: str, *, resolve: bool = True) -> str | None:
    """Return a refusal reason, or ``None`` when the URL may be reached.

    Args:
        url: The absolute URL to check.
        resolve: Also resolve the hostname and check every address it maps to.
            Left switchable only for callers that have already resolved; it is
            not a way to turn the floor off, since literals are judged either
            way.
    """
    shape = check_url_shape(url)
    if shape is not None:
        return shape
    return check_resolved_address(url) if resolve else None


def validate_and_pin_public_url(url: str) -> PinnedTarget:
    """:func:`validate_public_url` plus the addresses the verdict was reached on.

    Separate from ``validate_public_url`` rather than widening it: fourteen
    assertions across ``test_bf743_browser_ssrf_floor`` pin that function's
    ``str | None`` shape, one of them a standing contract that its refusal
    strings never reword, and only one caller wants the address.
    """
    shape = check_url_shape(url)
    if shape is not None:
        return PinnedTarget(shape)
    return resolve_and_pin(url)


def _reject_address(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> str | None:
    if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
        return f"Blocked private/reserved IP: {ip}"
    return None
