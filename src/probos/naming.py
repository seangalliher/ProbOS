"""AD-499: Ship & Crew Naming Conventions.

Three-layer naming policy:

1. ShipNamingPolicy — deterministic seed-based ship name selection at
   commissioning, with Captain override.
2. AgentNamingPolicy — validation and normalization for self-chosen
   agent callsigns.
3. FederationDisplayFormat — cross-instance display helper.

All three are stateless. No persistence beyond what AD-441's
AgentIdentityRegistry already provides.
"""

from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass

logger = logging.getLogger(__name__)


_SHIP_NAME_POOL: tuple[str, ...] = (
    "Enterprise", "Voyager", "Defiant", "Discovery", "Reliant",
    "Constitution", "Galaxy", "Intrepid", "Sovereign", "Excelsior",
    "Yamato", "Hood", "Pegasus", "Stargazer", "Avalon",
)

_CALLSIGN_RE = re.compile(r"^[A-Z][a-zA-Z0-9_-]{1,31}$")
_BANNED_WORDS_DEFAULT: frozenset[str] = frozenset({
    "admin", "root", "system", "ship", "captain",
    "null", "undefined", "test", "anonymous",
})


@dataclass(frozen=True)
class ShipNameDecision:
    """Outcome of a ship-naming decision."""

    name: str
    source: str
    seed: str
    pool_size: int


class ShipNamingPolicy:
    """Selects a ship name at commissioning."""

    def __init__(self, *, pool: tuple[str, ...] = _SHIP_NAME_POOL) -> None:
        if not pool:
            raise ValueError("AD-499: ship name pool must be non-empty")
        self._pool = pool

    def select(
        self,
        *,
        instance_id: str,
        override_name: str | None = None,
    ) -> ShipNameDecision:
        if override_name and override_name.strip():
            return ShipNameDecision(
                name=override_name.strip(),
                source="captain_override",
                seed=instance_id,
                pool_size=len(self._pool),
            )
        if not instance_id:
            raise ValueError("AD-499: instance_id required for seed selection")
        digest = hashlib.sha256(instance_id.encode("utf-8")).digest()
        idx = int.from_bytes(digest[:4], "big") % len(self._pool)
        return ShipNameDecision(
            name=self._pool[idx],
            source="deterministic_seed",
            seed=instance_id,
            pool_size=len(self._pool),
        )

    @property
    def pool(self) -> tuple[str, ...]:
        return self._pool


@dataclass(frozen=True)
class CallsignValidation:
    accepted: bool
    normalized: str = ""
    reason: str = ""


class AgentNamingPolicy:
    """Validate and normalize self-chosen agent callsigns.

    Rules:
      - Must match _CALLSIGN_RE (initial uppercase, 2-32 chars,
        alphanumeric + underscore + hyphen).
      - Must not appear in banned-word list (case-insensitive).
      - Trimmed before check.

    Caller passes `banned` as extras; defaults from _BANNED_WORDS_DEFAULT
    are always merged in.
    """

    def __init__(self, *, banned: frozenset[str] = frozenset()) -> None:
        merged = frozenset(b.lower() for b in (banned | _BANNED_WORDS_DEFAULT))
        self._banned = merged

    def validate(self, raw: str | None) -> CallsignValidation:
        if raw is None:
            return CallsignValidation(False, reason="empty_input")
        candidate = raw.strip()
        if not candidate:
            return CallsignValidation(False, reason="empty_input")
        if candidate.lower() in self._banned:
            return CallsignValidation(False, reason="banned_word")
        if not _CALLSIGN_RE.match(candidate):
            return CallsignValidation(False, reason="format_invalid")
        return CallsignValidation(accepted=True, normalized=candidate)

    @property
    def banned_words(self) -> frozenset[str]:
        return self._banned


class FederationDisplayFormat:
    """Cross-instance display helper.

    Stateless. `format(callsign, ship_name)` returns "Callsign [ShipName]".
    Empty inputs are tolerated and produce the most informative substring
    available; never raises.
    """

    @staticmethod
    def format(callsign: str, ship_name: str) -> str:
        cs = (callsign or "").strip()
        sh = (ship_name or "").strip()
        if cs and sh:
            return f"{cs} [{sh}]"
        if cs:
            return cs
        if sh:
            return f"[{sh}]"
        return ""
