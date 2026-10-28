"""AD-1270a migration step 2 (#1324 slice 5): the activation receipt model.

A receipt is evidence that a startup ownership point wired an owner. It is not a health claim
and not exercise evidence, so a receipted capability's ``live`` stays ``unknown``.

Hermetic: no runtime boot, no network, no clock, no writes.
"""

from __future__ import annotations

import ast
import importlib.util
import json
import logging
from pathlib import Path
from typing import Any

import pytest

from probos.config import SystemConfig
from probos.maturity import ActivationReceipt as ExportedReceipt
from probos.maturity import ActivationReceipts as ExportedReceipts
from probos.maturity.model import (
    ALWAYS_CONFIGURED,
    CapabilityDeclaration,
    CapabilityRow,
    ExerciseRecord,
    HealthRecord,
    HealthState,
    LiveState,
    TriState,
)
from probos.maturity.receipts import ActivationReceipt, ActivationReceipts
from probos.maturity.registry import MaturityRegistry
from probos.maturity.report import build_rows

_LOGGER = "probos.maturity.receipts"


def _receipt(
    capability_id: str = "test.capability",
    activated: Any = True,
    evidence: tuple[str, ...] = ("owner: probos.test.Owner",),
) -> ActivationReceipt:
    return ActivationReceipt(
        capability_id=capability_id, activated=activated, owner="probos.test.Owner", evidence=evidence
    )


def _registry(*ids: str) -> MaturityRegistry:
    registry = MaturityRegistry()
    for capability_id in ids:
        registry.register(
            CapabilityDeclaration(
                id=capability_id,
                title=capability_id,
                owner_module="probos.maturity.model",
                owner_symbol="TriState",
                configured_when=ALWAYS_CONFIGURED,
            )
        )
    return registry


def _messages(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [record.getMessage() for record in caplog.records if record.name == _LOGGER]


def test_a_recorded_receipt_answers_its_activation() -> None:
    receipts = ActivationReceipts()

    assert receipts.record(_receipt("a.on", True)) is True
    assert receipts.record(_receipt("a.off", False)) is True

    assert receipts.activation_for("a.on") is TriState.TRUE
    assert receipts.activation_for("a.off") is TriState.FALSE


def test_no_receipt_is_unknown_not_false() -> None:
    """No ownership point recorded it: not observed, which is not evidence of absence."""
    receipts = ActivationReceipts()

    assert receipts.activation_for("never.recorded") is TriState.UNKNOWN
    assert receipts.receipt_for("never.recorded") is None


@pytest.mark.parametrize("activated", [1, "yes", None, 1.0], ids=["int", "str", "none", "float"])
def test_only_true_reads_as_activated(activated: Any) -> None:
    receipts = ActivationReceipts()
    receipts.record(_receipt("a.odd", activated))

    assert receipts.activation_for("a.odd") is TriState.FALSE


def test_a_second_receipt_for_an_id_is_dropped_and_logged(caplog: pytest.LogCaptureFixture) -> None:
    receipts = ActivationReceipts()
    first = _receipt("a.dup", True)
    receipts.record(first)

    with caplog.at_level(logging.WARNING, logger=_LOGGER):
        kept = receipts.record(_receipt("a.dup", False))

    assert kept is False
    assert receipts.receipt_for("a.dup") is first
    assert receipts.activation_for("a.dup") is TriState.TRUE
    assert _messages(caplog) == ["AD-1270a: a second activation receipt for a.dup was dropped; the first one stands"]


def test_receipts_keep_the_order_startup_recorded_them() -> None:
    receipts = ActivationReceipts()
    for capability_id in ("z.first", "a.second", "m.third"):
        receipts.record(_receipt(capability_id))

    assert [receipt.capability_id for receipt in receipts.receipts()] == ["z.first", "a.second", "m.third"]


def test_each_receipt_is_logged_once_with_its_owner_and_evidence(caplog: pytest.LogCaptureFixture) -> None:
    receipts = ActivationReceipts()

    with caplog.at_level(logging.INFO, logger=_LOGGER):
        receipts.record(_receipt("a.logged", True, evidence=("first: x", "second: y")))

    assert _messages(caplog) == [
        "AD-1270a: activation receipt a.logged activated=True owner=probos.test.Owner evidence=first: x; second: y"
    ]


def test_a_receipt_is_no_exercise_and_no_health() -> None:
    receipts = ActivationReceipts()
    receipts.record(_receipt("a.on", True))

    assert receipts.exercise_for("a.on") == ExerciseRecord()
    assert receipts.health_for("a.on") == HealthRecord()


def test_to_dict_is_json_safe_and_ordered() -> None:
    receipt = _receipt("a.dict", False, evidence=("one", "two"))

    assert receipt.to_dict() == {
        "capability_id": "a.dict",
        "activated": False,
        "owner": "probos.test.Owner",
        "evidence": ["one", "two"],
    }
    assert json.loads(json.dumps(receipt.to_dict())) == receipt.to_dict()


def test_an_activated_receipt_alone_never_makes_a_row_live() -> None:
    """Every observable axis affirmed and a receipt: still not live, because nothing exercised it."""
    receipts = ActivationReceipts()
    receipts.record(_receipt("a.on", True))
    declaration = _registry("a.on").get("a.on")
    assert declaration is not None

    row = CapabilityRow(
        declaration=declaration,
        present=TriState.TRUE,
        configured=TriState.TRUE,
        advertised=TriState.TRUE,
        activated=receipts.activation_for("a.on"),
        exercise=receipts.exercise_for("a.on"),
        health=receipts.health_for("a.on"),
    )

    assert row.activated is TriState.TRUE
    assert row.live is LiveState.UNKNOWN


async def test_receipts_reach_the_report_row_and_leave_live_unknown() -> None:
    """ActivationReceipts is the ReceiptSource step 1 left room for: supplied, not patched in."""
    receipts = ActivationReceipts()
    receipts.record(_receipt("a.on", True))
    receipts.record(_receipt("b.off", False))

    rows = {
        row.declaration.id: row
        for row in await build_rows(
            _registry("a.on", "b.off", "c.none"), config=SystemConfig(), receipts=receipts
        )
    }

    assert {key: row.activated for key, row in rows.items()} == {
        "a.on": TriState.TRUE,
        "b.off": TriState.FALSE,
        "c.none": TriState.UNKNOWN,
    }
    assert all(row.exercise.attempts == 0 for row in rows.values())
    assert all(row.health.state is HealthState.UNKNOWN for row in rows.values())
    assert {row.live for row in rows.values()} == {LiveState.UNKNOWN}
    assert not [note for row in rows.values() for note in row.resolution_errors if note.startswith("activated:")]


def test_the_package_exports_the_receipt_types() -> None:
    assert ExportedReceipt is ActivationReceipt
    assert ExportedReceipts is ActivationReceipts


def test_receipts_import_only_the_maturity_model() -> None:
    """A leaf beside model.py, so startup can import it without pulling a subsystem."""
    spec = importlib.util.find_spec("probos.maturity.receipts")
    assert spec is not None and spec.origin is not None
    names: set[str] = set()
    for node in ast.walk(ast.parse(Path(spec.origin).read_bytes())):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)

    assert {name for name in names if name == "probos" or name.startswith("probos.")} == {"probos.maturity.model"}


def test_activation_receipts_is_not_a_singleton() -> None:
    """One set per finalization; a module-level instance would be the shared global AD-1270a forbids."""
    import probos.maturity.receipts as module

    first, second = ActivationReceipts(), ActivationReceipts()
    first.record(_receipt("only.in.first"))

    assert second.receipt_for("only.in.first") is None
    assert not [value for value in vars(module).values() if isinstance(value, ActivationReceipts)]
