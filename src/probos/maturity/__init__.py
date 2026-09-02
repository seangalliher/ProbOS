"""AD-1270a: the capability truth ledger — observation only.

A leaf package. Nothing in ``src/probos/`` imports it: it is consumed by
``scripts/gen_capability_truth.py`` and by tests. Importing it from a production
path would make an observation surface capable of influencing the thing it
observes, which this AD forbids.
"""

from __future__ import annotations

from probos.maturity.model import (
    ALWAYS_CONFIGURED,
    CapabilityDeclaration,
    CapabilityRow,
    ExerciseRecord,
    HealthRecord,
    HealthState,
    LiveState,
    ReceiptSource,
    TriState,
)
from probos.maturity.registry import (
    DECLARATION_MODULES,
    MaturityRegistry,
    load_default_registry,
)
from probos.maturity.report import build_rows, render_json, render_markdown

__all__ = [
    "ALWAYS_CONFIGURED",
    "DECLARATION_MODULES",
    "CapabilityDeclaration",
    "CapabilityRow",
    "ExerciseRecord",
    "HealthRecord",
    "HealthState",
    "LiveState",
    "MaturityRegistry",
    "ReceiptSource",
    "TriState",
    "build_rows",
    "load_default_registry",
    "render_json",
    "render_markdown",
]
