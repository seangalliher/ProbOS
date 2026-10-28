"""AD-1270a: the capability truth ledger — observation only.

A leaf package. Production imports it at two kinds of site: declaration modules import
``probos.maturity.model`` (data about an owner), and ``probos.startup.activation_receipts``
imports ``probos.maturity.receipts`` to record activation receipts at finalization (migration
step 2). Production writes receipts and reads none, and no production path reads a row: the
inventory is consumed by ``scripts/gen_capability_truth.py`` and by tests. An observation
surface that production read could influence the thing it observes, which this AD forbids.
``tests/test_ad1270a_startup_receipts.py`` pins the importers and the absence of a reader.
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
from probos.maturity.receipts import ActivationReceipt, ActivationReceipts
from probos.maturity.registry import (
    DECLARATION_MODULES,
    MaturityRegistry,
    load_default_registry,
)
from probos.maturity.report import build_rows, render_json, render_markdown

__all__ = [
    "ALWAYS_CONFIGURED",
    "DECLARATION_MODULES",
    "ActivationReceipt",
    "ActivationReceipts",
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
