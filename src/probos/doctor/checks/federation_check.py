"""AD-801: federation peer reachability check (when federation enabled)."""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass

from probos.doctor.protocol import CheckOutcome, CheckResult, DoctorContext
from probos.doctor.registry import register_check

# zmq URL — tcp://host:port — peers can also be plain host:port.
_TCP_URL_RE = re.compile(r"^(?:tcp://)?([^:/]+):(\d+)$")


def _parse_peer_address(addr: str) -> tuple[str, int] | None:
    m = _TCP_URL_RE.match(addr.strip())
    if not m:
        return None
    return m.group(1), int(m.group(2))


@dataclass(frozen=True)
class _FederationCheck:
    name: str = "federation"

    async def run(self, ctx: DoctorContext) -> CheckResult:
        fed = getattr(ctx.config, "federation", None) if ctx.config else None
        if fed is None or not getattr(fed, "enabled", False):
            return CheckResult(
                outcome=CheckOutcome.OK,
                message="Federation: disabled in config",
            )

        peers = list(getattr(fed, "peers", []) or [])
        if not peers:
            return CheckResult(
                outcome=CheckOutcome.WARN,
                message="Federation enabled but no peers configured",
                remediation="Add peers to config.federation.peers or disable federation.",
            )

        reachable = 0
        unreachable_names: list[str] = []
        for peer in peers:
            addr = getattr(peer, "address", None) or getattr(peer, "bind_address", None)
            label = getattr(peer, "node_id", None) or addr or "<peer>"
            parsed = _parse_peer_address(addr) if addr else None
            if parsed is None:
                unreachable_names.append(f"{label}(unparseable)")
                continue
            host, port = parsed
            try:
                _, writer = await asyncio.wait_for(
                    asyncio.open_connection(host, port),
                    timeout=2.0,
                )
                writer.close()
                try:
                    await writer.wait_closed()
                except OSError:
                    pass
                reachable += 1
            except (OSError, asyncio.TimeoutError):
                unreachable_names.append(label)

        total = len(peers)
        if reachable == 0:
            return CheckResult(
                outcome=CheckOutcome.FAIL,
                message=f"Federation: 0 / {total} peers reachable",
                remediation=f"Check peers: {', '.join(unreachable_names)}",
            )
        if unreachable_names:
            return CheckResult(
                outcome=CheckOutcome.WARN,
                message=f"Federation: {reachable} / {total} peers reachable",
                remediation=f"Unreachable: {', '.join(unreachable_names)}",
            )
        return CheckResult(
            outcome=CheckOutcome.OK,
            message=f"Federation: {reachable} / {total} peers reachable",
        )


register_check(_FederationCheck())
