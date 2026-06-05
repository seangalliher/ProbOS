"""Forge observability for the self-modification pipeline (AD-872).

Three pure, dependency-light units that give the forge (agent self-design
pipeline) a measurable surface:

1. ``validate_forge_shape`` — a cheap pre-design gate. Catches obviously
   malformed forge requests (empty/degenerate intent name, empty description,
   missing parameters) before the expensive design → validate → sandbox flow
   ever runs. Returns a list of error strings (empty = proceed), mirroring the
   ``CodeValidator.validate`` contract.

2. ``classify_forge_rejection`` — deterministic bucketing of a rejected
   ``DesignedAgentRecord`` into a small, stable taxonomy. Never raises; an
   unrecognized status falls through to ``"other"``.

3. ``ForgeStatsAggregator`` — pure aggregation over a list of records. Reports
   BOTH an attempt-level approval rate AND a unique-intent approval rate (three
   retries that finally succeed on one intent is one unique success, not three),
   plus a rejection histogram.

This module performs no I/O, makes no LLM calls, and persists nothing. It
imports ``DesignedAgentRecord`` only under ``TYPE_CHECKING`` and duck-types the
record at runtime (reading ``.status``, ``.intent_name``, ``.error``), so it
never participates in an import cycle with ``self_mod``.
"""

from __future__ import annotations

from collections import Counter
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - typing only, avoids self_mod import cycle
    from probos.cognitive.self_mod import DesignedAgentRecord


# Statuses that represent a record which passed the full pipeline (was built /
# deployed). A later removal does not make it a rejection.
_APPROVED_STATUSES: frozenset[str] = frozenset({"active", "removed"})

# Stable rejection bucket taxonomy. Kept here as documentation of the closed set
# that ``classify_forge_rejection`` may return.
REJECTION_BUCKETS: tuple[str, ...] = (
    "syntax_error",
    "forbidden_import",
    "schema_nonconformance",
    "judge_correctness",
    "dependency_declined",
    "dependency_failed",
    "user_rejected",
    "max_limit",
    "design_failed",
    "failed_sandbox",
    "failed_registration",
    "shape_rejected",
    "other",
)


def validate_forge_shape(
    intent_name: str,
    intent_description: str,
    parameters: dict[str, str] | None,
) -> list[str]:
    """Cheap pre-design shape gate for a forge (self-design) request.

    Catches obviously malformed requests before the expensive design pipeline
    runs. This is intentionally shallow — it does not attempt semantic judgement,
    only structural sanity.

    Args:
        intent_name: The intent the forge would build an agent for.
        intent_description: Human/LLM description of the intent.
        parameters: The parameter map for the intent. An empty dict is valid
            (many intents take no parameters); only ``None`` is treated as
            missing.

    Returns:
        A list of error strings. An empty list means the request is well-shaped
        and design may proceed. Mirrors ``CodeValidator.validate``.
    """
    errors: list[str] = []

    name = (intent_name or "").strip()
    if not name:
        errors.append("Empty intent name")
    elif len(name) < 2:
        errors.append(f"Degenerate intent name (too short): {intent_name!r}")
    elif not any(ch.isalnum() for ch in name):
        errors.append(f"Intent name has no alphanumeric content: {intent_name!r}")

    description = (intent_description or "").strip()
    if not description:
        errors.append("Empty intent description")

    if parameters is None:
        errors.append("Parameters missing (None)")
    else:
        for key in parameters:
            if not str(key).strip():
                errors.append("Parameter map contains an empty key")
                break

    return errors


def _classify_validation(blob: str) -> str:
    """Refine a validation failure into a specific bucket from its error text.

    ``blob`` is a lowercased concatenation of any validator error strings plus
    the record's own error detail. Order matters: more specific signals win.
    """
    if "syntax error" in blob:
        return "syntax_error"
    if "forbidden import" in blob:
        return "forbidden_import"
    if "judge" in blob or "correctness" in blob:
        return "judge_correctness"
    # Schema / structural conformance signals emitted by CodeValidator.
    schema_signals = (
        "missing",
        "schema",
        "baseagent subclass",
        "agent class",
        "side effect",
        "forbidden pattern",
    )
    if any(sig in blob for sig in schema_signals):
        return "schema_nonconformance"
    # Unrecognized validation failure — still a conformance problem.
    return "schema_nonconformance"


def classify_forge_rejection(
    record: DesignedAgentRecord,
    validator_errors: list[str] | None = None,
) -> str:
    """Bucket a rejected forge record into the stable rejection taxonomy.

    Deterministic and total: every input maps to exactly one bucket and an
    unrecognized status falls through to ``"other"``. Never raises.

    Args:
        record: A ``DesignedAgentRecord`` (duck-typed; only ``.status`` and
            ``.error`` are read).
        validator_errors: Optional list of ``CodeValidator`` error strings used
            to refine a ``failed_validation`` status into a specific bucket.

    Returns:
        One of :data:`REJECTION_BUCKETS`.
    """
    status = getattr(record, "status", "") or ""

    if status == "failed_validation":
        parts: list[str] = []
        if validator_errors:
            parts.extend(str(e) for e in validator_errors)
        record_error = getattr(record, "error", "") or ""
        if record_error:
            parts.append(record_error)
        return _classify_validation(" ".join(parts).lower())

    # Direct status → bucket mappings.
    direct: dict[str, str] = {
        "rejected_by_user": "user_rejected",
        "failed_design": "design_failed",
        "dependencies_declined": "dependency_declined",
        "dependencies_failed": "dependency_failed",
        "failed_sandbox": "failed_sandbox",
        "failed_registration": "failed_registration",
        "max_limit": "max_limit",
        "shape_rejected": "shape_rejected",
    }
    if status in direct:
        return direct[status]

    # active / removed are not rejections; anything unseen is "other".
    return "other"


class ForgeStatsAggregator:
    """Pure aggregation over a list of forge (design) records (AD-872).

    Reports both an attempt-level and a unique-intent-level approval rate. These
    diverge whenever a single intent is retried: three failed attempts followed
    by one success is one unique success out of one unique intent (rate 1.0),
    but one approval out of four attempts (rate 0.25). Conflating the two
    overstates the forge's effectiveness.

    Construct with a materialized list of records; the aggregator does not
    mutate or retain references to mutable shared state beyond a local copy.
    """

    def __init__(self, records: list[DesignedAgentRecord]) -> None:
        # Materialize a local copy so later mutation of the source list does not
        # change reported stats.
        self._records: list[DesignedAgentRecord] = list(records)

    @property
    def total_attempts(self) -> int:
        """Total number of forge attempts (one record per attempt)."""
        return len(self._records)

    @property
    def total_unique_intents(self) -> int:
        """Number of distinct intent names across all attempts."""
        return len({getattr(r, "intent_name", "") or "" for r in self._records})

    @property
    def attempt_approval_rate(self) -> float:
        """Fraction of attempts that resulted in a built agent (active/removed).

        0.0 when there are no attempts.
        """
        if not self._records:
            return 0.0
        approved = sum(
            1 for r in self._records
            if (getattr(r, "status", "") or "") in _APPROVED_STATUSES
        )
        return approved / len(self._records)

    @property
    def unique_intent_approval_rate(self) -> float:
        """Fraction of distinct intents that were approved at least once.

        Retries on a single intent collapse to one unique success. 0.0 when
        there are no intents.
        """
        intents: dict[str, bool] = {}
        for r in self._records:
            name = getattr(r, "intent_name", "") or ""
            approved = (getattr(r, "status", "") or "") in _APPROVED_STATUSES
            intents[name] = intents.get(name, False) or approved
        if not intents:
            return 0.0
        approved_intents = sum(1 for ok in intents.values() if ok)
        return approved_intents / len(intents)

    @property
    def rejection_histogram(self) -> dict[str, int]:
        """Count of non-approved records bucketed by rejection reason.

        Records with an approved status (active/removed) are excluded.
        """
        counter: Counter[str] = Counter()
        for r in self._records:
            status = getattr(r, "status", "") or ""
            if status in _APPROVED_STATUSES:
                continue
            counter[classify_forge_rejection(r)] += 1
        return dict(counter)

    def summary(self) -> dict[str, object]:
        """Flat dict summary suitable for logging or shell/panel rendering."""
        return {
            "total_attempts": self.total_attempts,
            "total_unique_intents": self.total_unique_intents,
            "attempt_approval_rate": self.attempt_approval_rate,
            "unique_intent_approval_rate": self.unique_intent_approval_rate,
            "rejection_histogram": self.rejection_histogram,
        }
