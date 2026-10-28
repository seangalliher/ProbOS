"""AD-1270a migration step 2: activation receipts, the evidence that startup wired an owner.

A receipt records, for one declared capability, the production owner a startup ownership point
is meant to wire, whether it wired it, and the facts it saw, in the order it saw them. It is
**not** a health claim and not exercise evidence: :class:`ActivationReceipts` answers
``exercise_for`` and ``health_for`` with empty records, so a receipted capability's ``live``
stays ``unknown`` until migration step 3 records production exercise.

One :class:`ActivationReceipts` per finalization, held by the runtime; there is no module-level
instance. Production writes receipts and reads none. This module imports nothing from
``probos`` except :mod:`probos.maturity.model`.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from probos.maturity.model import ExerciseRecord, HealthRecord, TriState

logger = logging.getLogger(__name__)

__all__ = ["ActivationReceipt", "ActivationReceipts"]


@dataclass(frozen=True, slots=True)
class ActivationReceipt:
    """What one startup ownership point wired for one declared capability.

    ``owner`` is the dotted class path the point is meant to wire. ``activated`` is ``True``
    only when startup wired that owner and the point's own step did not fail. ``evidence`` is
    what the point saw, in order. No clock value: the order is the sequence.
    """

    capability_id: str
    activated: bool
    owner: str
    evidence: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        """Render as a JSON-safe mapping."""
        return {
            "capability_id": self.capability_id,
            "activated": self.activated,
            "owner": self.owner,
            "evidence": list(self.evidence),
        }


class ActivationReceipts:
    """One finalization's activation receipts, keyed by capability id. A ``ReceiptSource``."""

    def __init__(self) -> None:
        self._receipts: dict[str, ActivationReceipt] = {}

    def record(self, receipt: ActivationReceipt) -> bool:
        """Keep the first receipt for its capability id; return whether this one was kept.

        A second receipt for one id in one finalization is a wiring fault. Log-and-degrade:
        the first receipt stands and startup continues.
        """
        if receipt.capability_id in self._receipts:
            logger.warning(
                "AD-1270a: a second activation receipt for %s was dropped; the first one stands",
                receipt.capability_id,
            )
            return False
        self._receipts[receipt.capability_id] = receipt
        logger.info(
            "AD-1270a: activation receipt %s activated=%s owner=%s evidence=%s",
            receipt.capability_id,
            receipt.activated is True,
            receipt.owner,
            "; ".join(receipt.evidence),
        )
        return True

    def receipt_for(self, capability_id: str) -> ActivationReceipt | None:
        """The receipt recorded for this capability, or ``None``."""
        return self._receipts.get(capability_id)

    def receipts(self) -> tuple[ActivationReceipt, ...]:
        """The receipts, in the order startup recorded them."""
        return tuple(self._receipts.values())

    def activation_for(self, capability_id: str) -> TriState:
        """``TRUE`` or ``FALSE`` from a receipt; ``UNKNOWN`` when no ownership point recorded one.

        Fails closed: only ``activated is True`` reads as ``TRUE``.
        """
        receipt = self._receipts.get(capability_id)
        if receipt is None:
            return TriState.UNKNOWN
        return TriState.TRUE if receipt.activated is True else TriState.FALSE

    def exercise_for(self, capability_id: str) -> ExerciseRecord:
        """No exercise evidence: migration step 3 records it."""
        return ExerciseRecord()

    def health_for(self, capability_id: str) -> HealthRecord:
        """No health observation: an activation receipt is not one."""
        return HealthRecord()
