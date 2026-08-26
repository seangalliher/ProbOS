"""Combining independent verification verdicts into one outcome (AD-1272).

Red team verification fans out over a cross product of successful results and
red-team agents, so one agent's contribution to a round can draw N independent
verdicts. Trust accrues per unit of work -- "this agent contributed to this
round" -- so those verdicts have to become a single verdict before trust is
spent once. The rule mirrors ``_evaluate_coalition`` in ``shapley.py``: the
system already decided that a weighted set of booleans agrees when its
confidence-weighted approval clears ``policy.approval_threshold``.
"""

from __future__ import annotations

import logging
import math
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from probos.types import VerificationResult

logger = logging.getLogger(__name__)


def _usable_weight(value: object) -> float | None:
    """A confidence that can actually be weighed, or ``None``.

    ``confidence`` is producer-supplied at this boundary and
    ``VerificationResult`` does not validate it. Review measured two failures a
    plain ``float`` arithmetic path cannot survive:

    * ``None`` raised ``TypeError`` straight out of the sum, which aborted the
      whole consensus round;
    * one ``NaN`` made ``total_weight`` NaN, slipped past the ``<= 0`` guard,
      and turned two APPROVALS into a rejection -- a trust penalty produced by
      a metadata gap, which is exactly what the unweighted fallback exists to
      prevent.

    Negative is unusable for the same reason: it is not a confidence. ``bool``
    is excluded explicitly because it is a subclass of ``int`` and a verdict
    weighted ``True`` would silently mean ``1.0``.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    weight = float(value)
    if not math.isfinite(weight) or weight < 0.0:
        return None
    return weight


def combine_verdicts(
    verdicts: list[VerificationResult],
    approval_threshold: float,
    use_confidence_weights: bool = True,
) -> tuple[bool, tuple[str, ...]] | None:
    """Combine independent verification verdicts into a single outcome.

    Args:
        verdicts: Every verdict returned for one target agent in one round.
            The same verifier may appear more than once -- each verdict is an
            independent judgement about a distinct result row, so duplicates
            carry signal and are all counted.
        approval_threshold: Fraction of weighted approval required, reused from
            ``QuorumPolicy.approval_threshold``. Compared with ``>=`` to match
            ``shapley._evaluate_coalition``.
        use_confidence_weights: Weight each verdict by
            ``VerificationResult.confidence``. When False, or when any verdict
            carries a confidence that cannot be weighed (``None``, non-finite,
            negative, or simply absent), an unweighted majority is used against
            the same threshold -- a verifier metadata gap must not read as
            "failed verification", which would be a trust penalty.

    Returns:
        ``(verified, verifier_ids)`` where ``verifier_ids`` is sorted and
        deduplicated, or ``None`` when there is nothing to combine and the
        caller must not touch trust.
    """
    if not verdicts:
        return None

    verifier_ids = tuple(sorted({v.verifier_id for v in verdicts}))

    weighted_approval = 0.0
    total_weight = 0.0
    unusable = 0
    if use_confidence_weights:
        for verdict in verdicts:
            weight = _usable_weight(verdict.confidence)
            if weight is None:
                unusable += 1
                continue
            total_weight += weight
            if verdict.verified:
                weighted_approval += weight

    # Any unusable confidence degrades the WHOLE set to unweighted, rather than
    # silently dropping that verdict from the tally. A verifier whose metadata
    # is malformed still returned a judgement, and disenfranchising it would be
    # a quieter version of the same defect. ``<= 0`` rather than ``== 0``
    # because a total of exactly zero is the all-zero-confidence case the
    # fallback was written for.
    if unusable or total_weight <= 0.0:
        if use_confidence_weights:
            logger.debug(
                "AD-1272: %d of %d verdict(s) from verifier(s) %s carry no "
                "usable confidence weight; falling back to unweighted majority "
                "so a metadata gap is not scored as a failed verification",
                unusable or len(verdicts),
                len(verdicts),
                ",".join(verifier_ids),
            )
        total_weight = float(len(verdicts))
        weighted_approval = float(sum(1 for verdict in verdicts if verdict.verified))

    return (weighted_approval / total_weight) >= approval_threshold, verifier_ids
