"""AD-1270a: the capability-truth model — the several meanings of "available".

ProbOS has had four incompatible meanings for "available": a class exists, a
config flag is on, a tool is advertised in the catalog, and a runtime reports a
healthy default. None of them is evidence that a production request ever
exercised the path, and because they were recorded nowhere together nothing
could tell *shipped* from *working*.

This module is the value layer for that distinction. It is a **leaf**: it
imports nothing from ``probos``, which is what lets a declaration module in any
layer import it without inverting the layer order. A test enforces that by
AST-scanning this file's imports.

Every axis is tri-state rather than ``bool``. "We did not look" and "we looked
and it is not there" are different facts, and collapsing them is precisely the
defect this model exists to fix.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Final, Protocol

__all__ = [
    "ALWAYS_CONFIGURED",
    "CapabilityDeclaration",
    "CapabilityRow",
    "ExerciseRecord",
    "HealthRecord",
    "HealthState",
    "LiveState",
    "ReceiptSource",
    "TriState",
]


class TriState(str, Enum):
    """A fact that may be affirmed, denied, or not yet observed."""

    TRUE = "true"
    FALSE = "false"
    UNKNOWN = "unknown"


class HealthState(str, Enum):
    """Observed health of a capability. ``UNKNOWN`` until something observes it."""

    UNKNOWN = "unknown"
    AVAILABLE = "available"
    DEGRADED = "degraded"
    FAILING = "failing"


class LiveState(str, Enum):
    """The derived verdict. Never stored — see :attr:`CapabilityRow.live`."""

    UNKNOWN = "unknown"
    INERT = "inert"
    DEGRADED = "degraded"
    LIVE = "live"


#: Sentinel ``configured_when`` meaning "unconditionally part of the profile".
#: A declaration must opt into this **by name** — an empty ``configured_when``
#: is a declaration error, not an implicit "always", because an implicit
#: always is how an unconfigured capability starts reporting itself as enabled.
ALWAYS_CONFIGURED: Final[str] = "__always__"


def _is_positive_count(attempts: object) -> bool:
    """Is this a trustworthy count of at least one exercise attempt?

    Fails closed on anything that is not a plain positive ``int``. A receipt
    source is external to this package and its annotation is not enforced at
    runtime, so ``float("nan")`` would slip past an ordinary ``>= 1`` test —
    every comparison against NaN is false — and promote an unexercised
    capability to ``LIVE``. ``bool`` is excluded because ``True >= 1`` holds.
    """
    return isinstance(attempts, int) and not isinstance(attempts, bool) and attempts >= 1


@dataclass(frozen=True, slots=True)
class ExerciseRecord:
    """Evidence that production traffic reached a capability.

    Timestamps are ISO-8601 UTC **strings**, not ``datetime``, so a row
    round-trips through JSON identically on every platform.
    """

    attempts: int = 0
    last_success: str | None = None
    last_failure: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Render as a JSON-safe mapping."""
        return {
            "attempts": self.attempts,
            "last_success": self.last_success,
            "last_failure": self.last_failure,
        }


@dataclass(frozen=True, slots=True)
class HealthRecord:
    """An observation of a capability's health, and who observed it."""

    state: HealthState = HealthState.UNKNOWN
    observed_at: str | None = None
    source: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Render as a JSON-safe mapping."""
        return {
            "state": self.state.value,
            "observed_at": self.observed_at,
            "source": self.source,
        }


@dataclass(frozen=True, slots=True)
class CapabilityDeclaration:
    """Static data *about* a capability, declared beside its owning subsystem.

    A declaration is data, never a use of the thing it declares: nothing here
    imports or constructs the owner. ``seam_ids`` is an opaque free-text
    cross-reference rendered as documentation and validated by nothing — this
    slice deliberately does not couple to the P0 seam manifest.
    """

    id: str
    title: str
    owner_module: str
    owner_symbol: str
    configured_when: str
    catalog_axis: str | None = None
    catalog_id: str | None = None
    seam_ids: tuple[str, ...] = ()
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Render as a JSON-safe mapping."""
        return {
            "id": self.id,
            "title": self.title,
            "owner_module": self.owner_module,
            "owner_symbol": self.owner_symbol,
            "configured_when": self.configured_when,
            "catalog_axis": self.catalog_axis,
            "catalog_id": self.catalog_id,
            "seam_ids": list(self.seam_ids),
            "notes": self.notes,
        }


@dataclass(frozen=True, slots=True)
class CapabilityRow:
    """One capability resolved against every authority this slice can reach."""

    declaration: CapabilityDeclaration
    present: TriState
    configured: TriState
    advertised: TriState
    activated: TriState
    exercise: ExerciseRecord
    health: HealthRecord
    resolution_errors: tuple[str, ...] = field(default=())

    @property
    def live(self) -> LiveState:
        """The derived verdict. A property, so it is structurally unstorable.

        Total function, evaluated in a fixed order. A positive denial on any
        *observable* axis beats every other signal, so the ``INERT`` test runs
        first — ``activated`` is deliberately excluded there, because a row that
        was never activated is unproven rather than denied. The rule this AD
        exists to enforce: **no path returns ``LIVE`` without every axis
        positively resolved and at least one exercise attempt**. An unresolved
        axis is not a weaker yes — ``UNKNOWN`` blocks ``LIVE`` just as ``FALSE``
        does, it simply is not evidence of absence.
        """
        if TriState.FALSE in (self.present, self.configured, self.advertised):
            return LiveState.INERT
        if self.health.state in (HealthState.FAILING, HealthState.DEGRADED):
            return LiveState.DEGRADED
        if self.exercise.last_failure and not self.exercise.last_success:
            return LiveState.DEGRADED
        if not all(
            axis is TriState.TRUE
            for axis in (self.present, self.configured, self.advertised, self.activated)
        ):
            return LiveState.UNKNOWN
        if not _is_positive_count(self.exercise.attempts):
            return LiveState.UNKNOWN
        if self.health.state is HealthState.AVAILABLE:
            return LiveState.LIVE
        return LiveState.UNKNOWN

    def to_dict(self) -> dict[str, Any]:
        """Render as a JSON-safe mapping, including the derived ``live``."""
        return {
            "id": self.declaration.id,
            "declaration": self.declaration.to_dict(),
            "present": self.present.value,
            "configured": self.configured.value,
            "advertised": self.advertised.value,
            "activated": self.activated.value,
            "exercise": self.exercise.to_dict(),
            "health": self.health.to_dict(),
            "resolution_errors": list(self.resolution_errors),
            "live": self.live.value,
        }


class ReceiptSource(Protocol):
    """Where activation, exercise and health facts come from.

    Nothing implements this in production in this slice — migration steps 2 and
    3 do. It is defined now so those slices attach receipts by *supplying an
    argument* to the existing resolver, not by changing this model.
    """

    def activation_for(self, capability_id: str) -> TriState:
        """Whether an activation owner claimed this capability."""
        ...

    def exercise_for(self, capability_id: str) -> ExerciseRecord:
        """Production exercise evidence for this capability."""
        ...

    def health_for(self, capability_id: str) -> HealthRecord:
        """The most recent health observation for this capability."""
        ...
