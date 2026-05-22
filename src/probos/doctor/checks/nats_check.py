"""AD-801: NATS reachability check (when enabled in config)."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from probos.doctor.protocol import CheckOutcome, CheckResult, DoctorContext
from probos.doctor.registry import register_check


@dataclass(frozen=True)
class _NATSCheck:
    name: str = "nats"

    async def run(self, ctx: DoctorContext) -> CheckResult:
        if ctx.config is None or not getattr(ctx.config, "nats", None) or not ctx.config.nats.enabled:
            return CheckResult(
                outcome=CheckOutcome.OK,
                message="NATS: disabled in config",
            )
        url = ctx.config.nats.url
        host_port = url.replace("nats://", "").replace("tls://", "")
        parts = host_port.split(":")
        host = parts[0]
        port = int(parts[1]) if len(parts) > 1 else 4222

        try:
            _, writer = await asyncio.wait_for(
                asyncio.open_connection(host, port),
                timeout=3.0,
            )
            writer.close()
            try:
                await writer.wait_closed()
            except OSError:
                pass
        except (OSError, asyncio.TimeoutError) as exc:
            return CheckResult(
                outcome=CheckOutcome.FAIL,
                message=f"NATS unreachable: {url}",
                remediation=(
                    f"Start nats-server, or set config.nats.enabled=false. "
                    f"({type(exc).__name__})"
                ),
            )
        return CheckResult(
            outcome=CheckOutcome.OK,
            message=f"NATS reachable: {url}",
        )


register_check(_NATSCheck())
