"""AD-708e: ServiceAdvertiser protocol for LAN service discovery.

Defines the narrow DIP seam the runtime depends on. The concrete
implementations live in ``advertiser.py``; the runtime only ever sees this
two-method interface, so a NoOp / Zeroconf / future backend is swappable
without touching the boot path.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class ServiceAdvertiser(Protocol):
    """Advertise (or no-op) a ProbOS service on the local network."""

    async def start(self) -> bool:
        """Begin advertising. Returns True iff actually advertising."""
        ...

    async def stop(self) -> None:
        """Stop advertising. Idempotent; never raises."""
        ...
