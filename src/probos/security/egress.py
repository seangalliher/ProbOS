"""AD-456: EgressPolicy -- allow/deny consultation for outbound HTTP.

v1 read-only consultation surface. Subsystems that send outbound HTTP
(HttpFetchAgent, RedTeamAgent verification probes) call ``is_allowed(url)``
before making the request. v1 emits ``EGRESS_BLOCKED`` when a check would
block -- but does NOT actually intercept the request. Active interception
(consumer wiring) is deferred to AD-456b per the coordinator-then-dispatch
convention.

v1 default: ``deny_by_default=True`` with a built-in allowlist
(``127.0.0.1``, ``localhost``, ``::1``). This makes ``EGRESS_BLOCKED`` events
fire on every unknown-host request -- producing real signal even before
AD-456b adds active interception.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

from probos.events import EventType

logger = logging.getLogger(__name__)


# Default loopback / localhost endpoints (IPv4 + IPv6). Operators extend.
_DEFAULT_ALLOWLIST: tuple[str, ...] = (
    "127.0.0.1",
    "localhost",
    "::1",
)


@dataclass(frozen=True)
class EgressDecision:
    """Result of a policy check."""

    allowed: bool
    url: str
    matched_rule: str = ""
    reason: str = ""


@dataclass
class EgressPolicy:
    """In-memory allow/deny policy over outbound URLs.

    v1 surface:
      - ``is_allowed(url) -> bool`` (consultation; no interception)
      - ``check(url) -> EgressDecision`` (rich result for logging)
      - ``allow_host(host: str) / deny_host(host: str)`` (operator-side mutation)

    v1 emits ``EGRESS_BLOCKED`` on every blocked decision (deny-by-default OR
    denylist match). Operators get observable signal today; AD-456b adds
    active interception by wiring ``EgressPolicy.is_allowed()`` into
    ``HttpFetchAgent``'s request path.
    """

    allowlist: list[str] = field(default_factory=lambda: list(_DEFAULT_ALLOWLIST))
    denylist: list[str] = field(default_factory=list)
    emit_event: Any | None = None
    deny_by_default: bool = True  # v1 default: real signal via EGRESS_BLOCKED

    def is_allowed(self, url: str) -> bool:
        return self.check(url).allowed

    def check(self, url: str) -> EgressDecision:
        host = self._extract_host(url)
        if not host:
            decision = EgressDecision(
                allowed=not self.deny_by_default,
                url=url,
                matched_rule="",
                reason="no host parsed",
            )
            if not decision.allowed:
                self._emit_blocked(decision)
            return decision

        for pattern in self.denylist:
            if self._host_matches(host, pattern):
                decision = EgressDecision(
                    allowed=False, url=url, matched_rule=pattern,
                    reason="denylist match",
                )
                self._emit_blocked(decision)
                return decision

        for pattern in self.allowlist:
            if self._host_matches(host, pattern):
                return EgressDecision(
                    allowed=True, url=url, matched_rule=pattern,
                    reason="allowlist match",
                )

        # No allowlist match
        if self.deny_by_default:
            decision = EgressDecision(
                allowed=False, url=url, matched_rule="",
                reason="not in allowlist (deny_by_default)",
            )
            self._emit_blocked(decision)
            return decision
        return EgressDecision(
            allowed=True, url=url, matched_rule="",
            reason="not in allowlist (allow_by_default)",
        )

    def allow_host(self, host: str) -> None:
        if host and host not in self.allowlist:
            self.allowlist.append(host)

    def deny_host(self, host: str) -> None:
        if host and host not in self.denylist:
            self.denylist.append(host)

    def _extract_host(self, url: str) -> str:
        try:
            parsed = urlparse(url)
            return (parsed.hostname or "").lower()
        except Exception:
            return ""

    def _host_matches(self, host: str, pattern: str) -> bool:
        # Exact match or wildcard suffix (e.g., ".example.com" matches "x.example.com")
        if pattern == host:
            return True
        if pattern.startswith(".") and host.endswith(pattern):
            return True
        return False

    def _emit_blocked(self, decision: EgressDecision) -> None:
        if not self.emit_event:
            return
        try:
            self.emit_event(
                EventType.EGRESS_BLOCKED,
                {
                    "url": decision.url,
                    "matched_rule": decision.matched_rule,
                    "reason": decision.reason,
                },
            )
        except Exception:
            logger.warning(
                "AD-456: EGRESS_BLOCKED emit failed (url=%s)", decision.url,
                exc_info=True,
            )
