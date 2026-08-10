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
import socket
from urllib.parse import urlparse

# Hostnames that serve cloud instance credentials. Blocked by name as well as by
# address because the address check depends on resolution succeeding.
BLOCKED_HOSTS = frozenset({
    "metadata.google.internal",
    "metadata.goog",
})

ALLOWED_SCHEMES = frozenset({"http", "https"})


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
    try:
        hostname = urlparse(url).hostname
    except Exception:
        return "Malformed URL"
    if not hostname:
        return None

    try:
        addrinfo = socket.getaddrinfo(hostname, None)
    except socket.gaierror:
        return f"Cannot resolve hostname: {hostname}"

    for _family, _type, _proto, _canon, sockaddr in addrinfo:
        try:
            ip = ipaddress.ip_address(sockaddr[0])
        except ValueError:
            continue
        reason = _reject_address(ip)
        if reason:
            return reason

    return None


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


def _reject_address(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> str | None:
    if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
        return f"Blocked private/reserved IP: {ip}"
    return None
