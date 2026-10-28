# AD-1270 (#1324) slice 5: AD-1270a migration step 2 -- activation receipts at startup ownership points (the boot camp, working-memory cognition and the Night Orders escalation)

**Drafted by:** `claude-architect` (Claude Code, Opus 5.5), 2026-10-28

**Status:** build-ready preview. Drafted on the oracle `67928365` (tree `17f9ec0d`): slice 4b's code plus the 4c contract (A3) applied by tool, with 4c's trackers. It builds after 4c merges. The orchestrator re-anchors every pair on the real post-4c tree with Amendment A1. No new AD or BF number: this is slice 5 of #1324 and AD-1270a's migration step 2. **Captain:** nothing parked. He may overrule D12 (scope), D13 (where a receipt lives), D14 (how startup records one) or D15 (the inventory).

**Which text describes the head.** Some parts are records of the oracle `67928365`: the Status paragraph, §1, §3, the pairs and new files in §7, §10, §11 (every Verified and Absence block and the Not verified list), §13, and the predicted counts and build orders in §4 and §6. They are not restated for the head. Where a later amendment differs from them, the amendment wins. The other parts describe the candidate's head: the front matter's Milestones and Tests lists, §2, §4's focused-gate table, §5, §6's file and case columns, §8's head constraint, §9, §12, §14, §15 and §16. They name no commit, and each count in them is one that a named command, a focused gate or the broad gate measures.

**Milestones:**
- **M1 (STANDARD):** `probos.maturity.receipts` (`ActivationReceipt`, `ActivationReceipts`), its two package exports and the `ReceiptSource` docstring. M1 changes only `src/probos/maturity/` and adds one test file (`git diff --stat` shows it).
- **M2 (HIGH):** the startup ownership points:
  - `probos.startup.activation_receipts`;
  - `finalize_startup`'s receipt calls;
  - three declarations (one new declaration module);
  - the inventory header and the regenerated inventory;
  - the package docstring.
- **M3 (docs):** trackers and the ledger.

Each milestone is one Builder delegation and one local commit, staged by explicit path (never `git add -A`). One cross-family review round (`gpt-6.1-sol`, one reviewer) covers M1 to M3 against §14, in the shape §16.3 sets. One mutation campaign of record runs on the M2 tree (§10). The broad gate runs once, after M3: `d:/ProbOS/.venv/Scripts/python.exe scripts/run_test_gate.py --label ad1270-activation-receipts --receipt logs/gates/ad1270-activation-receipts.receipt.json`.

**Tests:**
- New: `tests/test_ad1270a_activation_receipts.py` (M1, 16 cases) and `tests/test_ad1270a_startup_receipts.py` (M2, 33 cases). `pytest <file> -n 0` reports each count. With A1's teardown in the second file, the interpreter then exits by itself (§15 measures it).
- Updated: `tests/test_ad1270a_capability_truth.py`. The pinned inventory gains the three ids, with an inline `AD-1270a step 2` reason (P-T1).
- `test_a_real_boot_publishes_its_receipts` starts a real `ProbOSRuntime` on `tmp_path` with a default `SystemConfig()` and stops it in a `finally`, as `tests/test_bf927_boot_claims.py:545-549` does (that test sets one `ground_truth` field; this one sets none). A Grep of the two new files, A1's teardown included, for `LOCALAPPDATA|AppData|environ|getenv|subprocess` finds nothing (run it on the head).

## 1. Problem

- AD-1270a's ledger defines `activated` as "startup successfully wired a production owner" (`platform-maturity-program.md`, AD-1270a Decision). Migration step 2, "Add activation receipts at startup ownership points", has no producer. The Wave 1 paragraph says so: `advertised`, `activated`, `exercise` and `health` are honestly `unknown`.
- Step 1 left a seam for this: `ReceiptSource` (`maturity/model.py:215-233`), an optional `receipts=` argument to `build_rows` (`report.py:224-230`), and `_resolve_receipts` (`report.py:172-198`). Nothing implements the seam in `src`. `test_a_receipt_source_fills_activation_exercise_and_health` drives it with a fake.
- Slices 1, 3, 4b and 4c wired or repaired three owners whose startup outcome is visible nowhere except scattered log lines:
  - **Boot camp:** the Phase 7 coordinator (`runtime.py:3324-3340`), the AD-683 late-bind (`finalize.py:4212-4216`; its `bool` result is discarded) and the cold-start enrolment (`finalize.py:4221-4224`; its `bool` result is discarded).
  - **Working-memory cognition:** started after the AD-573 restore (`finalize.py:6423-6428`). The driver is published only after `start()` (`:856-857`).
  - **Night Orders escalation:** pages the Captain only through `_night_orders_mgr`, `bridge_alerts` and `ward_room_router` (`runtime.py:2151-2184`). Finalization builds or hands over all three (`finalize.py:4311`, `:5555`, `:6821-6829`; `runtime.py:3343`, `:3600`, `:3603`).

## 2. Solution

- **The receipt.** `ActivationReceipt` records, for one declared capability id, the owner the ownership point is meant to wire, whether it did, and the evidence it saw, in order. It is not a health claim.
- **The receipt set.** `ActivationReceipts`, one per finalization:
  - keeps the first receipt per id;
  - logs one INFO line per receipt;
  - implements `ReceiptSource`: `activation_for` is `TRUE` only for `activated is True`, `FALSE` for any other recorded value, `UNKNOWN` without a receipt;
  - answers `exercise_for` and `health_for` with empty records, so `live` stays derived and cannot read `live` from a receipt alone.
- **The startup side.** `probos.startup.activation_receipts` builds the three receipts and matches owners by dotted class path, so a test double reads as not activated. `begin_activation_receipts` and `record_activation` catch `Exception` and log a warning, so a failure costs one receipt and never startup.
- **What finalization records:**
  - the boot camp after its enrolment: the coordinator, then the late-bind, then the enrolment. A skipped enrolment is an activation; a failed one is not.
  - working-memory cognition after its start, with any start error;
  - the Night Orders escalation from what finalization hands the runtime.

  Each call sits after its ownership point, and nothing moves.
- **Declarations.** `core.boot-camp` and `core.night-orders-escalation` go in a new `probos.maturity_declarations`. `cognitive.working-memory-cognition` goes in the cognitive module. Each one's `notes` names its receipt point.
- **The inventory.** The generator is unchanged and still offline, so `activated` reads `unknown` there. The header now says why. The doc is regenerated by tool.
- **What the tests measure.**
  - Production writes receipts and reads none: `test_production_writes_the_receipts_and_reads_none`.
  - The importers of `probos.maturity` are a fixed set: `test_production_imports_of_the_maturity_package_are_the_known_set`.
  - Only the three ids get a receipt in a finalization: `test_a_finalization_publishes_its_receipts_on_the_runtime`.

## 3. Decisions

Numbering continues after 4c's D11. D1 to D11 of 4b and 4c are not reopened.

- **D12 (scope).** The three owners above. The eight step-1 declarations get no receipt point in this slice (register 5-R1).
- **D13 (where a receipt lives).** In memory on `runtime.activation_receipts`, plus a log line. No event type, no file, no registry, and no change to the `probos.capability-truth.v1` shape.
- **D14 (how startup records one).** At each ownership point, from its own result, through `record_activation`. A receipt set is begun once at the top of `finalize_startup`. 4b's order and its `try` blocks stay.
- **D15 (the inventory).** Header rewording plus three rows, regenerated by tool. No runtime in the generator; no new declaration field.

## 4. Milestones

Write each milestone's new test file first and run it on that milestone's base:
- **M1 base:** collection fails, pytest exit 2, with `ImportError: cannot import name 'ActivationReceipt' from 'probos.maturity'`, raised by the test's line 21 (`from probos.maturity import ActivationReceipt as ExportedReceipt`). Measured by A1's dry run on `8cb4bad5` (§17).
- **M2 base (the M1 commit):** collection fails, pytest exit 2, with `ImportError: cannot import name 'activation_receipts' from 'probos.startup'`, raised by the test's line 44 (`from probos.startup import activation_receipts as ar`). Measured by A1's dry run on its M1 commit (§17).

Never delete or loosen a test beyond P-T1. Run the M1 and M3 focused gates with `d:/ProbOS/.venv/Scripts/pytest.exe -n 0`. Run M2's with `-n 4`: its list includes `tests/test_new_crew_auto_welcome.py`, whose rig leaves non-daemon sqlite and attachment I/O threads, so a `-n 0` interpreter does not exit after the summary line (measured on the oracle stage; register 5-R4). The serial exit of `tests/test_ad1270a_startup_receipts.py` is measured once, by the orchestrator (§15).

| M | Tier | Sections | Focused gate |
|---|---|---|---|
| **M1** | STANDARD | 7.1 | `tests/test_ad1270a_activation_receipts.py tests/test_ad1270a_capability_truth.py tests/test_ad1270b_seam_contracts.py`; then `scripts/gen_capability_truth.py --check`, `-P scripts/check_architecture_principles.py --check`, `-P scripts/check_dormant_classes.py --check` (paste its whole output) |
| **M2** | HIGH | 7.2 to 7.4 | `tests/test_ad1270a_startup_receipts.py tests/test_ad1270a_activation_receipts.py tests/test_ad1270a_capability_truth.py tests/test_ad1270b_seam_contracts.py tests/test_ad1270_boot_camp_orientation.py tests/test_ad1270_boot_camp_lifecycle.py tests/test_ad1270_boot_camp_repair_a1.py tests/test_ad1270_boot_camp_tracker_retired.py tests/test_ad1270_working_memory_cognition.py tests/test_ad1270_night_orders_triggers.py tests/test_ad1270_night_orders_delivery.py tests/test_new_crew_auto_welcome.py tests/test_bf235_stale_identity_cache.py tests/test_bf927_boot_claims.py tests/test_bf926_config_readers.py tests/test_finalize.py tests/test_layer_boundaries.py tests/test_ad1270b_architecture_fitness.py tests/test_ad680_public_runtime_api.py`; then `scripts/gen_capability_truth.py --check`, `-P scripts/check_seam_contracts.py --check`, `-P scripts/check_architecture_principles.py --check`, `-P scripts/check_dormant_classes.py --check` (paste its whole output) |
| **M3** | docs | §8; `python scripts/gen_ad_ledger.py`, then stage `docs/development/open-ads-report.md` and `docs/development/ad-ledger-snapshot.json` if they changed | `tests/test_ad1184_ad_ledger.py`; `-P scripts/gen_ad_ledger.py --check`. AD-1270 must still resolve `shipped` |

**M1 build order:**
1. Write 7.1.N and run it (collection error as above).
2. Create `src/probos/maturity/receipts.py` (7.1.M).
3. Apply P-M1 and P-M2.
4. Run the gate. `gen_capability_truth.py --check` must pass: M1 changes no declaration and no header.
5. Prediction for the dormant check: it lists `maturity/receipts.py::ActivationReceipt` and `maturity/receipts.py::ActivationReceipts` as new candidates. They are used only from tests until M2. It is report-only: do not update the baseline. Any other new candidate is a stop.
6. Commit.

**M2 build order:**
1. Write 7.4.N and run it (collection error).
2. Apply P-T1.
3. Create `src/probos/maturity_declarations.py` (7.2.N) and `src/probos/startup/activation_receipts.py` (7.3.N).
4. Apply P-D1, P-D2, P-H1, P-H2, P-M3, then P-F1 to P-F5.
5. Regenerate with `python scripts/gen_capability_truth.py`. Allowed diff:
   - the two header paragraphs P-H1 and P-H2 change;
   - three inventory rows and three Detail sections are added (`cognitive.working-memory-cognition`, `core.boot-camp`, `core.night-orders-escalation`).

   Nothing else. Measured rows against `config/system.yaml` (A3), in the column order Present, Configured, Advertised, Activated, Exercise attempts, Health, Live:
   - `cognitive.working-memory-cognition`: `yes`, `no`, `unknown`, `unknown`, 0, `unknown`, `inert` (`CapabilityRow.live` returns `inert` when `present`, `configured` or `advertised` is `false`, `maturity/model.py:182-183`);
   - `core.boot-camp` and `core.night-orders-escalation`: `yes`, `yes`, `unknown`, `unknown`, 0, `unknown`, `unknown`.
6. Run the gate. The dormant check must no longer list the two M1 candidates, and must list no other new one. The architecture check must pass with no row change. The seam check must pass (the new module declares no `seam_ids`).
7. Commit.

**M3 build order:** apply U1 to U3, regenerate the ledger, run the gate, commit.

## 5. Consumers of every value this adds or changes

- `runtime.activation_receipts`: new. `begin_activation_receipts` writes it, at the top of `finalize_startup`, whose only caller in `src` is Phase 8 (`runtime.py:3595-3598`). Outside `src/probos/maturity/`, the only attribute node named `activation_receipts` in `src` is that store in `startup/activation_receipts.py`. `test_production_writes_the_receipts_and_reads_none` measures this by AST. It does not see a `getattr` that names the attribute as a string, and `finalize.py`'s import of the module and its local variable of the same name are not attribute nodes. Tests read it. Step 5 is its intended reader and must use `getattr(runtime, "activation_receipts", None)`: `ProbOSRuntime` neither declares the attribute nor defines `__getattr__`. The attribute is absent before Phase 8, after a boot that fails earlier, and when the runtime refuses it (register 5-R2).
- The results of `_late_bind_boot_camp_snapshot` and `_activate_boot_camp_on_cold_start`: discarded before, now held in locals for the receipt. Their calls, their order, the `if` and the `try` stay. The existing AST tests in `test_ad1270_boot_camp_lifecycle.py` and `test_ad1270_boot_camp_orientation.py` count each call once and check the order.
- The `except` of the activation and of `_start_working_memory_cognition`: each still logs its warning. It now also keeps the exception's class name for the receipt.
- Logs: one INFO line per receipt on `probos.maturity.receipts`, and a WARNING on `probos.startup.activation_receipts` when a receipt cannot be built or the runtime refuses the attribute.
- `DECLARATION_MODULES`: read by `load_default_registry` and, by AST, by `scripts/check_seam_contracts.py`, which reads `seam_ids` only. The new module declares none.
- `probos.maturity.__all__`: gains `ActivationReceipt` and `ActivationReceipts`.
- The inventory document: read by `test_ad1270a_capability_truth.py` (`--check`, the generated mark, the token and date scan, and `"| live |"`).
- Attribute names, string constants and call keywords in the new modules are names to BF-926's reader scan (`check_config_readers.py:80-102`), so a name equal to a config field makes that field count as read. §11 records a Grep of `config.py` and `config_models/` on the oracle that found none. On the head, `tests/test_bf926_config_readers.py` (M2's gate) measures that each BF-926 inert field still reports inert.

## 6. Tests

| File | Cases | On its milestone's base | Covers |
|---|---|---|---|
| `tests/test_ad1270a_activation_receipts.py` (M1) | 16 (predicted) | collection error | the receipt model: tri-state reads, fail-closed `is True`, first-wins duplicates, order, the log line, no exercise or health, JSON, no `live` from a receipt, through `build_rows`, exports, leaf imports, no singleton |
| `tests/test_ad1270a_startup_receipts.py` (M2) | 33 (predicted) | collection error | owners equal their declarations; the three builders (positive, missing, stand-in, failed); log-and-degrade; the helpers in finalization's order into a report row; the AST position of each receipt; the real `finalize_startup` on the auto-welcome rig (`[skipped]`, `[enrolled]`, `[failed]`); a real `ProbOSRuntime` boot; the importer census; the no-reader census |
| `tests/test_ad1270a_capability_truth.py` | unchanged count | passes after P-T1 | P-T1: the pinned inventory gains three ids |

## 7. The contract

### 7.1 M1: `src/probos/maturity/`

#### 7.1.M New file: `src/probos/maturity/receipts.py`

```python
"""AD-1270a migration step 2: activation receipts, the evidence that startup wired an owner.

A receipt records, for one declared capability, the production owner a startup ownership point
is meant to wire, whether it wired it, and the facts it saw, in the order it saw them. It is
**not** a health claim and not exercise evidence: :class:`ActivationReceipts` answers
``exercise_for`` and ``health_for`` with empty records.

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
```

#### P-M1 (`src/probos/maturity/__init__.py`)

SEARCH:
```
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
```
REPLACE:
```
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
```

#### P-M2 (`src/probos/maturity/model.py`)

SEARCH:
```
    Nothing implements this in production in this slice — migration steps 2 and
    3 do. It is defined now so those slices attach receipts by *supplying an
    argument* to the existing resolver, not by changing this model.
    """
```
REPLACE:
```
    Migration step 2's ``probos.maturity.receipts.ActivationReceipts`` implements
    it for activation and answers exercise and health with empty records; step 3
    supplies exercise. Receipts attach by *supplying an argument* to the existing
    resolver, not by changing this model.
    """
```

#### 7.1.N New file: `tests/test_ad1270a_activation_receipts.py` (16 cases predicted)

```python
"""AD-1270a migration step 2 (#1324 slice 5): the activation receipt model.

A receipt is evidence that a startup ownership point wired an owner. It is not a health claim
and not exercise evidence.

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
```

### 7.2 M2: declarations, registry, package docstring, inventory header

#### 7.2.N New file: `src/probos/maturity_declarations.py`

```python
"""AD-1270a: capability declarations owned by top-level (core) modules.

Data only — no import of the subsystems declared here. See the cognitive-layer declaration
module for the reasoning. Each declaration here has an activation receipt point at
finalization (``probos.startup.activation_receipts``, AD-1270a migration step 2).
"""

from __future__ import annotations

from probos.maturity.model import CapabilityDeclaration

MATURITY_DECLARATIONS: tuple[CapabilityDeclaration, ...] = (
    CapabilityDeclaration(
        id="core.boot-camp",
        title="Cold-start boot camp",
        owner_module="probos.boot_camp",
        owner_symbol="BootCampCoordinator",
        configured_when="boot_camp.enabled",
        notes=(
            "AD-638. Activation receipt at finalization: the coordinator Phase 7 built, then the "
            "AD-683 snapshot late-bind, then the cold-start enrolment, in that order. A boot "
            "that is not a new crew skips the enrolment and is still activated; a failed "
            "enrolment is not. Phase 7 builds the coordinator only with the Ward Room, trust "
            "and episodic memory present."
        ),
    ),
    CapabilityDeclaration(
        id="core.night-orders-escalation",
        title="Night Orders escalation to the Captain",
        owner_module="probos.bridge_alerts",
        owner_symbol="BridgeAlertService",
        configured_when="proactive_cognitive.enabled",
        notes=(
            "AD-471. Activation receipt at finalization: activated only when the Night Orders "
            "manager, the bridge-alert service and the Ward Room router are all wired, because "
            "the escalation pages the Captain only through the three. Whether Night Orders are "
            "in force is runtime state, not activation."
        ),
    ),
)
```

#### P-D1 (`src/probos/cognitive/maturity_declarations.py`)

SEARCH:
```
        seam_ids=("TA-P0-007-crew-outcome-trust",),
        notes=(
            "Owns durable workflow time for crew work: admission bounds, "
            "compare-and-set transitions, crash recovery, cancellation."
        ),
    ),
)
```
REPLACE:
```
        seam_ids=("TA-P0-007-crew-outcome-trust",),
        notes=(
            "Owns durable workflow time for crew work: admission bounds, "
            "compare-and-set transitions, crash recovery, cancellation."
        ),
    ),
    CapabilityDeclaration(
        id="cognitive.working-memory-cognition",
        title="Working-memory cognition (AD-668 salience, AD-670 metabolism)",
        owner_module="probos.cognitive.working_memory_cognition",
        owner_symbol="WorkingMemoryCognition",
        configured_when="working_memory.cognition_enabled",
        notes=(
            "Default off. Activation receipt at finalization, after the AD-573 working-memory "
            "restore: activated when startup started the cycle and published it as "
            "runtime.working_memory_cognition."
        ),
    ),
)
```

#### P-D2 (`src/probos/maturity/registry.py`)

SEARCH:
```
    "probos.tools.maturity_declarations",
    "probos.agents.maturity_declarations",
    "probos.infrastructure.maturity_declarations",
)
```
REPLACE:
```
    "probos.tools.maturity_declarations",
    "probos.agents.maturity_declarations",
    "probos.infrastructure.maturity_declarations",
    "probos.maturity_declarations",  # AD-1270a step 2 (#1324 slice 5): top-level (core) owners
)
```

#### P-M3 (`src/probos/maturity/__init__.py`)

SEARCH:
```
"""AD-1270a: the capability truth ledger — observation only.

A leaf package. Nothing in ``src/probos/`` imports it: it is consumed by
``scripts/gen_capability_truth.py`` and by tests. Importing it from a production
path would make an observation surface capable of influencing the thing it
observes, which this AD forbids.
"""
```
REPLACE:
```
"""AD-1270a: the capability truth ledger — observation only.

A leaf package. Production imports it at two kinds of site: declaration modules import
``probos.maturity.model`` (data about an owner), and ``probos.startup.activation_receipts``
imports ``probos.maturity.receipts`` to record activation receipts at finalization (migration
step 2). Production writes receipts and reads none, and no production path reads a row: the
inventory is consumed by ``scripts/gen_capability_truth.py`` and by tests. An observation
surface that production read could influence the thing it observes, which this AD forbids.
``tests/test_ad1270a_startup_receipts.py`` pins the importers and the absence of a reader.
"""
```

#### P-H1 (`src/probos/maturity/report.py`)

SEARCH:
```
This is an **observation-only** inventory (AD-1270a, migration step 1). Nothing
reads a row to make a decision: it changes no routing, permission, trust or
startup behaviour. It exists so that *shipped* and *working* stop looking alike.
```
REPLACE:
```
This is an **observation-only** inventory (AD-1270a, migration steps 1 and 2).
Nothing reads a row to make a decision: it changes no routing, permission, trust
or startup decision. It exists so that *shipped* and *working* stop looking alike.
```

#### P-H2 (`src/probos/maturity/report.py`)

SEARCH:
```
**Why so much of this page says `unknown`, and why that is the finding.**
`activated`, `exercise` and `health` have no producer yet — emitting activation
receipts is migration step 2 and recording exercise receipts is migration step 3.
The generator also runs offline and constructs no runtime, which keeps `--check`
hermetic and is why `advertised` is `unknown` here even though the axis is
genuinely wired and covered by tests. `live` is **derived, never stored**, and no
row can read `live` without both an activation fact and at least one exercise
attempt — so in this slice no capability is provably live, and the page says so
rather than defaulting to optimism.
"""
```
REPLACE:
```
**Why so much of this page says `unknown`, and why that is the finding.**
`exercise` and `health` have no producer yet: recording exercise receipts is
migration step 3. `activated` has one since migration step 2: at finalization a
running ProbOS records an activation receipt for each capability whose notes name
a receipt point, keeps them on `runtime.activation_receipts` and logs one line per
receipt. The generator runs offline and constructs no runtime, which keeps
`--check` hermetic and is why `activated` and `advertised` are `unknown` here even
though both are wired and covered by tests. `live` is **derived, never stored**,
and no row can read `live` without both an activation fact and at least one
exercise attempt — so no capability is provably live yet, and the page says so
rather than defaulting to optimism.
"""
```

#### P-T1 (`tests/test_ad1270a_capability_truth.py`)

SEARCH:
```
        "cognitive.intent-decomposition",
        "cognitive.self-modification",
        "infrastructure.snapshot-manifest",
```
REPLACE:
```
        "cognitive.intent-decomposition",
        "cognitive.self-modification",
        "cognitive.working-memory-cognition",  # AD-1270a step 2 (#1324 slice 5): has a receipt point
        "core.boot-camp",  # AD-1270a step 2: has a receipt point
        "core.night-orders-escalation",  # AD-1270a step 2: has a receipt point
        "infrastructure.snapshot-manifest",
```

### 7.3 M2: the startup ownership points

#### 7.3.N New file: `src/probos/startup/activation_receipts.py`

```python
"""AD-1270a migration step 2 (#1324 slice 5): activation receipts at startup ownership points.

Finalization records a receipt after each ownership point listed here runs, from what the
point returned: the owner it was meant to wire, whether it did, and what it saw, in order.
``runtime.activation_receipts`` holds them for this run, and each is logged once. A receipt
is not a health claim and not exercise evidence. Startup writes receipts and reads none, and
nothing here changes what finalization wires or in which order. Each function is
log-and-degrade: a failure costs a receipt, never startup.

An owner is matched by its dotted class path, so a test double standing in for an owner is
recorded as not activated rather than as the owner.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from probos.maturity.receipts import ActivationReceipt, ActivationReceipts

logger = logging.getLogger(__name__)

__all__ = [
    "BOOT_CAMP",
    "BOOT_CAMP_OWNER",
    "BRIDGE_ALERTS_OWNER",
    "COGNITION_OWNER",
    "NIGHT_ORDERS_ESCALATION",
    "NIGHT_ORDERS_OWNER",
    "WARD_ROOM_ROUTER_OWNER",
    "WORKING_MEMORY_COGNITION",
    "begin_activation_receipts",
    "boot_camp_receipt",
    "night_orders_escalation_receipt",
    "record_activation",
    "type_path",
    "working_memory_cognition_receipt",
]

#: Declared capability ids; the declaration modules carry the same strings.
BOOT_CAMP = "core.boot-camp"
WORKING_MEMORY_COGNITION = "cognitive.working-memory-cognition"
NIGHT_ORDERS_ESCALATION = "core.night-orders-escalation"

#: Dotted class paths of the owners startup wires.
BOOT_CAMP_OWNER = "probos.boot_camp.BootCampCoordinator"
COGNITION_OWNER = "probos.cognitive.working_memory_cognition.WorkingMemoryCognition"
BRIDGE_ALERTS_OWNER = "probos.bridge_alerts.BridgeAlertService"
NIGHT_ORDERS_OWNER = "probos.watch_rotation.NightOrdersManager"
WARD_ROOM_ROUTER_OWNER = "probos.ward_room_router.WardRoomRouter"


def type_path(value: Any) -> str:
    """The dotted class path of ``value``; ``"None"`` for ``None``."""
    if value is None:
        return "None"
    cls = type(value)
    return f"{cls.__module__}.{cls.__qualname__}"


def begin_activation_receipts(runtime: Any) -> ActivationReceipts:
    """A fresh receipt set for this finalization, published as ``runtime.activation_receipts``.

    Log-and-degrade: when the runtime refuses the attribute, receipts are still recorded and
    logged, only not published.
    """
    receipts = ActivationReceipts()
    try:
        runtime.activation_receipts = receipts
    except Exception:
        logger.warning(
            "AD-1270a: activation receipts could not be published on the runtime; they are still logged",
            exc_info=True,
        )
    return receipts


def record_activation(receipts: ActivationReceipts, build: Callable[[], ActivationReceipt]) -> None:
    """Build one receipt and record it. A failure costs this receipt, never startup."""
    try:
        receipts.record(build())
    except Exception:
        logger.warning(
            "AD-1270a: an activation receipt could not be recorded; startup continues",
            exc_info=True,
        )


def _late_bind(bound: bool | None) -> str:
    if bound is None:
        return "not attempted"
    return "bound" if bound else "not bound"


def _enrolment(enrolled: bool, error: str | None) -> str:
    if error is not None:
        return f"failed ({error})"
    return "ran" if enrolled else "skipped"


def boot_camp_receipt(
    runtime: Any, *, late_bind: bool | None, enrolled: bool, enrolment_error: str | None
) -> ActivationReceipt:
    """AD-638's coordinator, then the AD-683 late-bind, then the cold-start enrolment.

    Activated when Phase 7 wired a ``BootCampCoordinator`` and the enrolment did not fail. A
    boot that is not a new crew skips the enrolment and is still activated. ``late_bind`` is
    ``None`` when the late-bind did not run (no AD-683 builder this run).
    """
    observed = type_path(getattr(runtime, "boot_camp", None))
    return ActivationReceipt(
        capability_id=BOOT_CAMP,
        activated=observed == BOOT_CAMP_OWNER and enrolment_error is None,
        owner=BOOT_CAMP_OWNER,
        evidence=(
            f"runtime.boot_camp: {observed}",
            f"ship-state builder late-bind: {_late_bind(late_bind)}",
            f"cold-start enrolment: {_enrolment(enrolled, enrolment_error)}",
        ),
    )


def working_memory_cognition_receipt(runtime: Any, *, start_error: str | None) -> ActivationReceipt:
    """AD-668/AD-670 working-memory cognition: activated when startup started its cycle.

    ``_start_working_memory_cognition`` publishes the driver only after ``start()``, so the
    owner on the runtime is the evidence. It is off by default; its receipt then reads not
    activated, which the ``configured`` axis explains.
    """
    observed = type_path(getattr(runtime, "working_memory_cognition", None))
    evidence = [f"runtime.working_memory_cognition: {observed}"]
    if start_error is not None:
        evidence.append(f"start failed ({start_error})")
    return ActivationReceipt(
        capability_id=WORKING_MEMORY_COGNITION,
        activated=observed == COGNITION_OWNER and start_error is None,
        owner=COGNITION_OWNER,
        evidence=tuple(evidence),
    )


def night_orders_escalation_receipt(
    runtime: Any, *, night_orders_mgr: Any, ward_room_router: Any
) -> ActivationReceipt:
    """AD-471 / #1324 slice 1: the escalation pages the Captain only through three links.

    Activated when finalization hands the runtime a ``NightOrdersManager`` and a
    ``WardRoomRouter`` and Phase 7 wired a ``BridgeAlertService``. Whether Night Orders are in
    force is runtime state, not activation.
    """
    links = (
        ("night orders manager", night_orders_mgr, NIGHT_ORDERS_OWNER),
        ("runtime.bridge_alerts", getattr(runtime, "bridge_alerts", None), BRIDGE_ALERTS_OWNER),
        ("ward room router", ward_room_router, WARD_ROOM_ROUTER_OWNER),
    )
    seen = tuple((label, type_path(value), owner) for label, value, owner in links)
    return ActivationReceipt(
        capability_id=NIGHT_ORDERS_ESCALATION,
        activated=all(path == owner for _, path, owner in seen),
        owner=BRIDGE_ALERTS_OWNER,
        evidence=tuple(f"{label}: {path}" for label, path, _ in seen),
    )
```

#### P-F1 (`src/probos/startup/finalize.py`)

SEARCH:
```
from probos.crew_utils import is_crew_agent
from probos.credential_store import crew_scope_token

if TYPE_CHECKING:
```
REPLACE:
```
from probos.crew_utils import is_crew_agent
from probos.credential_store import crew_scope_token
from probos.startup.activation_receipts import (
    begin_activation_receipts,
    boot_camp_receipt,
    night_orders_escalation_receipt,
    record_activation,
    working_memory_cognition_receipt,
)

if TYPE_CHECKING:
```

#### P-F2 (`src/probos/startup/finalize.py`)

SEARCH:
```
    from probos.cognitive.standing_orders import clear_cache as clear_standing_orders_cache
    clear_standing_orders_cache()

    if _wire_anomaly_window(runtime=runtime, config=config):
```
REPLACE:
```
    from probos.cognitive.standing_orders import clear_cache as clear_standing_orders_cache
    clear_standing_orders_cache()

    # AD-1270a step 2 (#1324): this finalization's activation receipts, published as
    # runtime.activation_receipts. Startup writes them below and reads none.
    activation_receipts = begin_activation_receipts(runtime)

    if _wire_anomaly_window(runtime=runtime, config=config):
```

#### P-F3 (`src/probos/startup/finalize.py`)

SEARCH:
```
    if _wire_ship_state_snapshot(runtime=runtime, config=config):
        logger.info("AD-683: Ship State Snapshot v1 wired during finalization")
        # BF-261 / AD-1270 (#1324): late-bind into BootCampCoordinator (created at Phase 7, before
        # finalize) through its public setter, before the activation below captures the snapshot.
        _late_bind_boot_camp_snapshot(runtime=runtime)

    # AD-1270 (#1324): AD-638 activation for a new crew, after the coordinator (Phase 7) and the
    # AD-683 snapshot late-bind above. Log-and-degrade: startup continues. ``activate`` enrols
    # agent by agent and nothing is rolled back, so a failure part-way can leave some crew enrolled.
    try:
        await _activate_boot_camp_on_cold_start(runtime=runtime)
    except Exception:
        logger.warning("AD-1270: boot-camp activation failed; startup continues", exc_info=True)
```
REPLACE:
```
    _boot_camp_late_bind: bool | None = None  # AD-1270a step 2: None when the late-bind did not run
    if _wire_ship_state_snapshot(runtime=runtime, config=config):
        logger.info("AD-683: Ship State Snapshot v1 wired during finalization")
        # BF-261 / AD-1270 (#1324): late-bind into BootCampCoordinator (created at Phase 7, before
        # finalize) through its public setter, before the activation below captures the snapshot.
        _boot_camp_late_bind = _late_bind_boot_camp_snapshot(runtime=runtime) is True

    # AD-1270 (#1324): AD-638 activation for a new crew, after the coordinator (Phase 7) and the
    # AD-683 snapshot late-bind above. Log-and-degrade: startup continues. ``activate`` enrols
    # agent by agent and nothing is rolled back, so a failure part-way can leave some crew enrolled.
    _boot_camp_enrolled = False
    _boot_camp_enrolment_error: str | None = None
    try:
        _boot_camp_enrolled = await _activate_boot_camp_on_cold_start(runtime=runtime) is True
    except Exception as _boot_camp_exc:
        _boot_camp_enrolment_error = type(_boot_camp_exc).__name__
        logger.warning("AD-1270: boot-camp activation failed; startup continues", exc_info=True)
    # AD-1270a step 2 (#1324): the boot-camp receipt: the coordinator, then the late-bind, then the enrolment.
    record_activation(
        activation_receipts,
        lambda: boot_camp_receipt(
            runtime,
            late_bind=_boot_camp_late_bind,
            enrolled=_boot_camp_enrolled,
            enrolment_error=_boot_camp_enrolment_error,
        ),
    )
```

#### P-F4 (`src/probos/startup/finalize.py`)

SEARCH:
```
    # AD-1270 (#1324): AD-668/AD-670 for crew working memory, default off. After the
    # AD-573 restore above, which replaces each restored agent's working memory.
    try:
        await _start_working_memory_cognition(runtime=runtime, config=config)
    except Exception:
        logger.warning("AD-1270: _start_working_memory_cognition failed", exc_info=True)
```
REPLACE:
```
    # AD-1270 (#1324): AD-668/AD-670 for crew working memory, default off. After the
    # AD-573 restore above, which replaces each restored agent's working memory.
    _cognition_start_error: str | None = None
    try:
        await _start_working_memory_cognition(runtime=runtime, config=config)
    except Exception as _cognition_exc:
        _cognition_start_error = type(_cognition_exc).__name__
        logger.warning("AD-1270: _start_working_memory_cognition failed", exc_info=True)
    # AD-1270a step 2 (#1324): the working-memory cognition receipt (off by default: not activated).
    record_activation(
        activation_receipts,
        lambda: working_memory_cognition_receipt(runtime, start_error=_cognition_start_error),
    )
```

#### P-F5 (`src/probos/startup/finalize.py`)

SEARCH:
```
    logger.info("Startup [finalize]: complete")
    return FinalizationResult(
```
REPLACE:
```
    # AD-1270a step 2 (#1324): the Night Orders escalation receipt, from what finalization hands the runtime.
    record_activation(
        activation_receipts,
        lambda: night_orders_escalation_receipt(
            runtime, night_orders_mgr=night_orders_mgr, ward_room_router=ward_room_router
        ),
    )

    logger.info("Startup [finalize]: complete")
    return FinalizationResult(
```

### 7.4 M2: tests

#### 7.4.N New file: `tests/test_ad1270a_startup_receipts.py` (33 cases predicted)

```python
"""AD-1270a migration step 2 (#1324 slice 5): activation receipts at startup ownership points.

Finalization records a receipt after the boot camp's late-bind and enrolment, after
working-memory cognition starts, and for the Night Orders escalation from what it hands the
runtime. A receipt names the owner and the evidence; it is not a health claim. Production
writes receipts and reads none: the two source censuses at the
end pin it.
"""

from __future__ import annotations

import ast
import asyncio
import importlib
import logging
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import aiosqlite
import pytest

from probos.boot_camp import BootCampCoordinator
from probos.bridge_alerts import BridgeAlertService
from probos.cognitive.working_memory_cognition import WorkingMemoryCognition
from probos.config import (
    AgenticDispatchConfig,
    BootCampConfig,
    DiscoveryLearningConfig,
    MCPConfig,
    ModelRoutingConfig,
    SystemConfig,
    WorkingMemoryConfig,
    WorkstationsConfig,
)
from probos.consensus.trust import TrustNetwork
from probos.maturity.model import LiveState, TriState
from probos.maturity.receipts import ActivationReceipt, ActivationReceipts
from probos.maturity.registry import load_default_registry
from probos.maturity.report import build_rows
from probos.onboarding import ShipStateSnapshot
from probos.startup import activation_receipts as ar
from probos.startup import finalize
from probos.ward_room_router import WardRoomRouter
from probos.watch_rotation import NightOrdersManager

_SRC = Path(__file__).resolve().parents[1] / "src" / "probos"
_LOGGER = "probos.startup.activation_receipts"
_BC = "runtime.boot_camp: probos.boot_camp.BootCampCoordinator"


class _Episodes:
    async def count_for_agent(self, agent_id: str) -> int:
        return 10


class _Builder:
    """The one method the coordinator calls on an AD-683 builder."""

    def __init__(self) -> None:
        self.builds = 0

    async def build(self) -> ShipStateSnapshot:
        self.builds += 1
        return ShipStateSnapshot(captured_at=1_000_000.0, vessel_name="Enterprise", active_crew_count=1)


class _NewCrewStats:
    """The one episodic-memory read ``finalize._is_new_crew_start`` makes: an empty store."""

    async def get_stats(self) -> dict:
        return {"total": 0}


def _coordinator() -> BootCampCoordinator:
    return BootCampCoordinator(
        config=BootCampConfig(min_time_minutes=0, timeout_minutes=120),
        trust_service=TrustNetwork(),
        episodic_memory=_Episodes(),
        clock=lambda: 1_000_000.0,
    )


def _bare(cls: type) -> Any:
    """An instance of ``cls`` without running its constructor: a receipt reads only its type."""
    return cls.__new__(cls)


def _messages(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [record.getMessage() for record in caplog.records if record.name == _LOGGER]


# --- the declarations and the owners ---------------------------------------------------------


@pytest.mark.parametrize(
    ("capability_id", "owner"),
    [
        pytest.param(ar.BOOT_CAMP, ar.BOOT_CAMP_OWNER, id="boot-camp"),
        pytest.param(ar.WORKING_MEMORY_COGNITION, ar.COGNITION_OWNER, id="working-memory-cognition"),
        pytest.param(ar.NIGHT_ORDERS_ESCALATION, ar.BRIDGE_ALERTS_OWNER, id="night-orders-escalation"),
    ],
)
def test_each_receipt_owner_is_its_declarations_owner(capability_id: str, owner: str) -> None:
    declaration = load_default_registry().get(capability_id)

    assert declaration is not None, f"{capability_id} has a receipt point but no declaration"
    assert f"{declaration.owner_module}.{declaration.owner_symbol}" == owner


@pytest.mark.parametrize(
    "owner",
    [
        pytest.param(ar.BOOT_CAMP_OWNER, id="boot-camp"),
        pytest.param(ar.COGNITION_OWNER, id="working-memory-cognition"),
        pytest.param(ar.BRIDGE_ALERTS_OWNER, id="bridge-alerts"),
        pytest.param(ar.NIGHT_ORDERS_OWNER, id="night-orders"),
        pytest.param(ar.WARD_ROOM_ROUTER_OWNER, id="ward-room-router"),
    ],
)
def test_the_declared_owners_are_the_classes_startup_wires(owner: str) -> None:
    module_name, _, symbol = owner.rpartition(".")
    cls = getattr(importlib.import_module(module_name), symbol)

    assert ar.type_path(_bare(cls)) == owner


# --- the boot camp ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("late_bind", "enrolled", "late_bind_text", "enrolment_text"),
    [
        pytest.param(True, True, "bound", "ran", id="bound-ran"),
        pytest.param(None, False, "not attempted", "skipped", id="not-attempted-skipped"),
        pytest.param(False, False, "not bound", "skipped", id="not-bound-skipped"),
    ],
)
def test_boot_camp_activated_when_phase_7_wired_the_coordinator(
    late_bind: bool | None, enrolled: bool, late_bind_text: str, enrolment_text: str
) -> None:
    """A warm boot skips the enrolment and is still an activation (systemd's "active (exited)")."""
    receipt = ar.boot_camp_receipt(
        SimpleNamespace(boot_camp=_bare(BootCampCoordinator)),
        late_bind=late_bind,
        enrolled=enrolled,
        enrolment_error=None,
    )

    assert (receipt.capability_id, receipt.owner) == (ar.BOOT_CAMP, ar.BOOT_CAMP_OWNER)
    assert receipt.activated is True
    assert receipt.evidence == (
        _BC,
        f"ship-state builder late-bind: {late_bind_text}",
        f"cold-start enrolment: {enrolment_text}",
    )


@pytest.mark.parametrize(
    ("coordinator", "seen"),
    [pytest.param(None, "None", id="none"), pytest.param(MagicMock(), "unittest.mock.MagicMock", id="stand-in")],
)
def test_boot_camp_not_activated_without_a_coordinator_or_with_a_stand_in(coordinator: Any, seen: str) -> None:
    receipt = ar.boot_camp_receipt(
        SimpleNamespace(boot_camp=coordinator), late_bind=None, enrolled=False, enrolment_error=None
    )

    assert receipt.activated is False
    assert receipt.evidence[0] == f"runtime.boot_camp: {seen}"


def test_a_failed_enrolment_is_not_an_activation() -> None:
    receipt = ar.boot_camp_receipt(
        SimpleNamespace(boot_camp=_bare(BootCampCoordinator)),
        late_bind=True,
        enrolled=False,
        enrolment_error="RuntimeError",
    )

    assert receipt.activated is False
    assert receipt.evidence == (_BC, "ship-state builder late-bind: bound", "cold-start enrolment: failed (RuntimeError)")


# --- working-memory cognition ----------------------------------------------------------------


async def test_working_memory_cognition_activated_when_startup_started_it() -> None:
    runtime = SimpleNamespace(registry=SimpleNamespace(all=lambda: []), ontology=None)
    config = SystemConfig.model_validate({"working_memory": {"cognition_enabled": True}})

    await finalize._start_working_memory_cognition(runtime=runtime, config=config)
    try:
        receipt = ar.working_memory_cognition_receipt(runtime, start_error=None)
    finally:
        if runtime.working_memory_cognition is not None:
            await runtime.working_memory_cognition.stop()

    assert receipt.activated is True
    assert receipt.evidence == (f"runtime.working_memory_cognition: {ar.COGNITION_OWNER}",)


async def test_working_memory_cognition_off_is_not_activated() -> None:
    runtime = SimpleNamespace(registry=SimpleNamespace(all=lambda: []), ontology=None)

    await finalize._start_working_memory_cognition(runtime=runtime, config=SystemConfig())
    receipt = ar.working_memory_cognition_receipt(runtime, start_error=None)

    assert receipt.activated is False
    assert receipt.evidence == ("runtime.working_memory_cognition: None",)


def test_a_failed_cognition_start_is_not_an_activation() -> None:
    runtime = SimpleNamespace(working_memory_cognition=_bare(WorkingMemoryCognition))

    receipt = ar.working_memory_cognition_receipt(runtime, start_error="RuntimeError")

    assert receipt.activated is False
    assert receipt.evidence == (
        f"runtime.working_memory_cognition: {ar.COGNITION_OWNER}",
        "start failed (RuntimeError)",
    )


# --- the Night Orders escalation -------------------------------------------------------------


@pytest.mark.parametrize(
    ("missing", "replacement"),
    [
        pytest.param(None, None, id="all"),
        pytest.param("night_orders_mgr", None, id="no-manager"),
        pytest.param("bridge_alerts", None, id="no-alerts"),
        pytest.param("ward_room_router", None, id="no-router"),
        pytest.param("bridge_alerts", "stand-in", id="stand-in-alerts"),
    ],
)
def test_night_orders_escalation_activated_only_with_all_three_links(missing: str | None, replacement: str | None) -> None:
    links: dict[str, Any] = {
        "night_orders_mgr": _bare(NightOrdersManager),
        "bridge_alerts": _bare(BridgeAlertService),
        "ward_room_router": _bare(WardRoomRouter),
    }
    if missing is not None:
        links[missing] = MagicMock() if replacement == "stand-in" else None

    receipt = ar.night_orders_escalation_receipt(
        SimpleNamespace(bridge_alerts=links["bridge_alerts"]),
        night_orders_mgr=links["night_orders_mgr"],
        ward_room_router=links["ward_room_router"],
    )

    assert (receipt.capability_id, receipt.owner) == (ar.NIGHT_ORDERS_ESCALATION, ar.BRIDGE_ALERTS_OWNER)
    assert receipt.activated is (missing is None)
    assert receipt.evidence == (
        f"night orders manager: {ar.type_path(links['night_orders_mgr'])}",
        f"runtime.bridge_alerts: {ar.type_path(links['bridge_alerts'])}",
        f"ward room router: {ar.type_path(links['ward_room_router'])}",
    )


# --- log-and-degrade -------------------------------------------------------------------------


def test_a_receipt_that_cannot_be_built_costs_only_that_receipt(caplog: pytest.LogCaptureFixture) -> None:
    receipts = ActivationReceipts()

    def _broken() -> ActivationReceipt:
        raise RuntimeError("owner unreadable")

    with caplog.at_level(logging.WARNING, logger=_LOGGER):
        ar.record_activation(receipts, _broken)
        ar.record_activation(
            receipts, lambda: ActivationReceipt(capability_id="a.next", activated=True, owner="probos.x.Y")
        )

    assert [receipt.capability_id for receipt in receipts.receipts()] == ["a.next"]
    assert _messages(caplog) == ["AD-1270a: an activation receipt could not be recorded; startup continues"]


def test_begin_publishes_a_fresh_receipt_set_on_the_runtime() -> None:
    runtime = SimpleNamespace()

    first = ar.begin_activation_receipts(runtime)
    assert isinstance(first, ActivationReceipts) and runtime.activation_receipts is first
    second = ar.begin_activation_receipts(runtime)

    assert runtime.activation_receipts is second and second is not first


class _Sealed:
    __slots__ = ()


def test_a_runtime_that_refuses_the_attribute_still_gets_receipts(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING, logger=_LOGGER):
        receipts = ar.begin_activation_receipts(_Sealed())

    assert isinstance(receipts, ActivationReceipts)
    assert _messages(caplog) == [
        "AD-1270a: activation receipts could not be published on the runtime; they are still logged"
    ]


# --- across the seam -------------------------------------------------------------------------


async def test_the_boot_camp_receipt_from_the_real_helpers_reaches_the_report_row() -> None:
    """Finalization's own helpers, in finalization's order, into a receipt, into the report."""
    builder = _Builder()
    member = SimpleNamespace(id="crew-1", agent_type="security_officer", callsign="Tester", department="security")
    runtime = SimpleNamespace(
        boot_camp=_coordinator(),
        ship_state_snapshot=builder,
        ontology=None,
        _lifecycle_state="first_boot",
        episodic_memory=_NewCrewStats(),
        registry=SimpleNamespace(all=lambda: [member]),
    )
    receipts = ar.begin_activation_receipts(runtime)
    late_bind = finalize._late_bind_boot_camp_snapshot(runtime=runtime) is True
    enrolled = await finalize._activate_boot_camp_on_cold_start(runtime=runtime) is True
    ar.record_activation(
        receipts,
        lambda: ar.boot_camp_receipt(runtime, late_bind=late_bind, enrolled=enrolled, enrolment_error=None),
    )

    rows = {
        row.declaration.id: row
        for row in await build_rows(load_default_registry(), config=SystemConfig(), receipts=runtime.activation_receipts)
    }

    assert (late_bind, enrolled, builder.builds) == (True, True, 1)
    assert runtime.activation_receipts.receipt_for(ar.BOOT_CAMP).evidence == (
        _BC,
        "ship-state builder late-bind: bound",
        "cold-start enrolment: ran",
    )
    assert rows[ar.BOOT_CAMP].activated is TriState.TRUE
    assert rows[ar.BOOT_CAMP].live is LiveState.UNKNOWN
    assert {key for key, row in rows.items() if row.activated is not TriState.UNKNOWN} == {ar.BOOT_CAMP}


def _finalize_startup() -> ast.AsyncFunctionDef:
    tree = ast.parse((_SRC / "startup" / "finalize.py").read_bytes())
    return next(n for n in tree.body if isinstance(n, ast.AsyncFunctionDef) and n.name == "finalize_startup")


def _call_lines(body: ast.AST, name: str) -> list[int]:
    return sorted(
        node.lineno
        for node in ast.walk(body)
        if isinstance(node, ast.Call)
        and (
            (isinstance(node.func, ast.Name) and node.func.id == name)
            or (isinstance(node.func, ast.Attribute) and node.func.attr == name)
        )
    )


def test_finalization_records_each_receipt_after_its_ownership_point() -> None:
    """Source scan of production source (a shared contract), parsed from bytes."""
    body = _finalize_startup()
    wirers = sorted(
        node.lineno
        for node in ast.walk(body)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id.startswith("_wire_")
    )
    begin = _call_lines(body, "begin_activation_receipts")
    records = _call_lines(body, "record_activation")
    boot = _call_lines(body, "boot_camp_receipt")
    cognition = _call_lines(body, "working_memory_cognition_receipt")
    night = _call_lines(body, "night_orders_escalation_receipt")
    binds = _call_lines(body, "_late_bind_boot_camp_snapshot")
    enrolments = _call_lines(body, "_activate_boot_camp_on_cold_start")
    starts = _call_lines(body, "_start_working_memory_cognition")
    routers = [
        node.lineno
        for node in ast.walk(body)
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "ward_room_router" for target in node.targets)
    ]
    finals = [
        node.lineno
        for node in ast.walk(body)
        if isinstance(node, ast.Return)
        and isinstance(node.value, ast.Call)
        and isinstance(node.value.func, ast.Name)
        and node.value.func.id == "FinalizationResult"
    ]

    assert (len(begin), len(records), len(boot), len(cognition), len(night), len(finals)) == (1, 3, 1, 1, 1, 1)
    assert begin[0] < wirers[0]
    assert binds[0] < enrolments[0] < boot[0]  # slice 4b's order, then its receipt
    assert starts[0] < cognition[0]
    assert max(routers) < night[0] < finals[0]


def _finalize_rig() -> tuple[MagicMock, MagicMock]:
    """test_new_crew_auto_welcome's rig (a MagicMock runtime that runs the whole finalize_startup),
    with a real boot-camp coordinator and working-memory cognition off."""
    agent1 = SimpleNamespace(
        callsign="Kira", agent_type="data_analyst", _newly_commissioned=True, id="sci_data_analyst_0_abc12345"
    )
    agent2 = SimpleNamespace(
        callsign="Lynx", agent_type="systems_analyst", _newly_commissioned=True, id="sci_systems_analyst_0_def67890"
    )
    ward_room = AsyncMock()
    ward_room.get_channel_by_name = AsyncMock(return_value=SimpleNamespace(id="ch-1", name="All Hands"))
    ward_room.create_thread = AsyncMock()
    registry = MagicMock()
    registry.all.return_value = [agent1, agent2]
    registry.count = 2

    runtime = MagicMock()
    runtime.ward_room = ward_room
    runtime._cold_start = False
    runtime.registry = registry
    runtime._started = False
    runtime._lifecycle_state = "restart"
    runtime._stasis_duration = 0
    runtime._previous_session = None
    runtime.event_log = AsyncMock()
    runtime.pools = {}
    runtime.red_team_agents = []
    runtime.ontology = None
    runtime.trust_network = MagicMock()
    runtime.trust_network.set_department_lookup = MagicMock()
    runtime.trust_network.set_event_callback = MagicMock()
    runtime.dream_scheduler = None
    runtime.self_mod_pipeline = None
    runtime.callsign_registry = None
    runtime.episodic_memory = None
    runtime.intent_bus = None
    runtime._knowledge_store = None
    runtime.initiative = None
    runtime._emergent_detector = None
    runtime.hebbian_router = None
    runtime.bridge_alerts = None
    runtime.behavioral_monitor = None
    runtime.acm = None
    runtime.onboarding = MagicMock()
    runtime.nats_bus = None
    runtime.boot_camp = _coordinator()  # AD-1270a step 2: a real owner, so the receipt can read activated
    runtime.working_memory_cognition = None

    config = MagicMock()
    config.proactive_cognitive.enabled = False
    config.agentic_dispatch = AgenticDispatchConfig(orchestrator_enabled=False)
    config.discovery_learning = DiscoveryLearningConfig(enabled=False)
    config.mcp = MCPConfig(enabled=False)
    config.model_routing = ModelRoutingConfig(enabled=False)
    config.workstations = WorkstationsConfig(enabled=False)
    config.working_memory = WorkingMemoryConfig()  # cognition off: the builder returns None
    return runtime, config


async def _enrol(**_: Any) -> bool:
    return True


async def _raise(**_: Any) -> bool:
    raise RuntimeError("wiring failed")


def _record_sqlite_connections(monkeypatch: pytest.MonkeyPatch) -> list[Any]:
    """A1: every aiosqlite connection opened while the rig runs, so the test can close it.

    Production opens each one through a call-time ``aiosqlite.connect(...)`` lookup, so the
    patched name sees them all. Their worker threads are not daemons: one left open keeps a
    ``-n 0`` interpreter alive after the session ends.
    """
    opened: list[Any] = []
    connect = aiosqlite.connect

    def _connect(*args: Any, **kwargs: Any) -> Any:
        connection = connect(*args, **kwargs)
        opened.append(connection)
        return connection

    monkeypatch.setattr(aiosqlite, "connect", _connect)
    return opened


async def _close_what_finalization_opened(runtime: Any, opened: list[Any]) -> None:
    """A1: close the rig's sqlite connections, then its attachment store's I/O threads.

    ``aiosqlite.Connection.close`` returns at once for a connection never opened, and stops
    the worker thread in its ``finally``, so a close error still ends the thread. Errors are
    collected, not raised: this is teardown. A connection opened while closing is closed in
    the next pass.
    """
    from probos.routers.chat import close_attachment_store

    while opened:
        batch = opened[:]
        del opened[:]
        await asyncio.gather(*(connection.close() for connection in batch), return_exceptions=True)
    close_attachment_store(runtime)


@pytest.mark.parametrize(
    ("case", "boot_activated", "enrolment"),
    [
        pytest.param("skipped", True, "skipped", id="skipped"),
        pytest.param("enrolled", True, "ran", id="enrolled"),
        pytest.param("failed", False, "failed (RuntimeError)", id="failed"),
    ],
)
async def test_a_finalization_publishes_its_receipts_on_the_runtime(
    case: str, boot_activated: bool, enrolment: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The real finalize_startup, end to end: receipts on the runtime, in order, into the report.
    A failing ownership point costs its receipt's activation, never the finalization."""
    runtime, config = _finalize_rig()
    opened = _record_sqlite_connections(monkeypatch)
    if case == "enrolled":
        monkeypatch.setattr(finalize, "_activate_boot_camp_on_cold_start", _enrol)
    if case == "failed":
        monkeypatch.setattr(finalize, "_activate_boot_camp_on_cold_start", _raise)
        monkeypatch.setattr(finalize, "_start_working_memory_cognition", _raise)

    try:
        await finalize.finalize_startup(runtime=runtime, config=config)
    finally:
        await _close_what_finalization_opened(runtime, opened)

    receipts = runtime.activation_receipts
    assert isinstance(receipts, ActivationReceipts)
    by_id = {receipt.capability_id: receipt for receipt in receipts.receipts()}
    assert list(by_id) == [ar.BOOT_CAMP, ar.WORKING_MEMORY_COGNITION, ar.NIGHT_ORDERS_ESCALATION]
    assert by_id[ar.BOOT_CAMP].activated is boot_activated
    assert by_id[ar.BOOT_CAMP].evidence == (_BC, "ship-state builder late-bind: bound", f"cold-start enrolment: {enrolment}")
    cognition = ("runtime.working_memory_cognition: None",) + (
        ("start failed (RuntimeError)",) if case == "failed" else ()
    )
    assert (by_id[ar.WORKING_MEMORY_COGNITION].activated, by_id[ar.WORKING_MEMORY_COGNITION].evidence) == (False, cognition)
    assert by_id[ar.NIGHT_ORDERS_ESCALATION].activated is False
    assert by_id[ar.NIGHT_ORDERS_ESCALATION].evidence == (
        "night orders manager: None",
        "runtime.bridge_alerts: None",
        f"ward room router: {ar.WARD_ROOM_ROUTER_OWNER}",
    )
    rows = {
        row.declaration.id: row
        for row in await build_rows(load_default_registry(), config=SystemConfig(), receipts=receipts)
    }
    assert rows[ar.BOOT_CAMP].activated is (TriState.TRUE if boot_activated else TriState.FALSE)
    assert LiveState.LIVE not in {row.live for row in rows.values()}


async def test_a_real_boot_publishes_its_receipts(tmp_path: Path) -> None:
    """The production path, as BF-927's boot test runs it: a real runtime and a default config,
    where no Ward Room exists, cognition is off and the proactive loop is off."""
    from probos.runtime import ProbOSRuntime

    rt = ProbOSRuntime(config=SystemConfig(), data_dir=tmp_path)
    try:
        await rt.start()
        receipts = rt.activation_receipts
    finally:
        await rt.stop()

    assert isinstance(receipts, ActivationReceipts)
    assert [receipt.capability_id for receipt in receipts.receipts()] == [
        ar.BOOT_CAMP,
        ar.WORKING_MEMORY_COGNITION,
        ar.NIGHT_ORDERS_ESCALATION,
    ]
    assert {receipt.capability_id: receipt.evidence[0] for receipt in receipts.receipts()} == {
        ar.BOOT_CAMP: "runtime.boot_camp: None",
        ar.WORKING_MEMORY_COGNITION: "runtime.working_memory_cognition: None",
        ar.NIGHT_ORDERS_ESCALATION: "night orders manager: None",
    }
    assert [receipt.activated for receipt in receipts.receipts()] == [False, False, False]


# --- the two source censuses -----------------------------------------------------------------


def _production_trees() -> Iterator[tuple[str, ast.AST]]:
    for path in sorted(_SRC.rglob("*.py")):
        relative = path.relative_to(_SRC).as_posix()
        if relative.startswith("maturity/"):
            continue
        yield relative, ast.parse(path.read_bytes())


def _maturity_imports(tree: ast.AST) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(
                alias.name for alias in node.names
                if alias.name == "probos.maturity" or alias.name.startswith("probos.maturity.")
            )
        elif isinstance(node, ast.ImportFrom) and node.module:
            if node.module == "probos.maturity" or node.module.startswith("probos.maturity."):
                names.add(node.module)
            elif node.module == "probos" and any(alias.name == "maturity" for alias in node.names):
                names.add("probos.maturity")
    return names


def test_production_imports_of_the_maturity_package_are_the_known_set() -> None:
    """Declarations import the model; one startup module imports the receipts. Nothing else."""
    found = {relative: names for relative, tree in _production_trees() if (names := _maturity_imports(tree))}

    assert found == {
        "agents/maturity_declarations.py": {"probos.maturity.model"},
        "cognitive/maturity_declarations.py": {"probos.maturity.model"},
        "infrastructure/maturity_declarations.py": {"probos.maturity.model"},
        "maturity_declarations.py": {"probos.maturity.model"},
        "startup/activation_receipts.py": {"probos.maturity.receipts"},
        "tools/maturity_declarations.py": {"probos.maturity.model"},
    }


_READS = frozenset({"activation_for", "exercise_for", "health_for", "receipt_for", "receipts"})


def test_production_writes_the_receipts_and_reads_none() -> None:
    """The ledger is observation-only: no routing, permission, trust or startup decision reads it."""
    published: list[tuple[str, str]] = []
    reads: list[tuple[str, str]] = []
    for relative, tree in _production_trees():
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr == "activation_receipts":
                published.append((relative, type(node.ctx).__name__))
            elif isinstance(node, ast.Attribute) and node.attr in _READS:
                reads.append((relative, node.attr))

    assert published == [("startup/activation_receipts.py", "Store")]
    assert reads == []
```

## 8. Tracking (M3's commit)

**Head constraint:** neither new head has a lifecycle keyword (`RETIRED|ABANDONED|WITHDRAWN|SUPERSEDED|DEFERRED|POSTPONED|CLOSED|SHIPPED|STAGED|LANDED|OPEN`) in its first 120 characters (`gen_ad_ledger.py`'s `_STATUS_PATTERNS` and `_HEAD_WINDOW`). The orchestrator replaces `2026-10-2X` with M3's date.

**Pair U1 (`PROGRESS.md`).** SEARCH:
```
# ProbOS Progress

```
REPLACE:
```
# ProbOS Progress

**AD-1270 (2026-10-2X), #1324 slice 5 -- AD-1270a migration step 2: finalization records activation receipts for the boot camp, working-memory cognition and the Night Orders escalation.** A receipt (`probos.maturity.receipts.ActivationReceipt`) names the owner a startup ownership point is meant to wire, whether it did, and the evidence it saw, in order; it is not a health claim. `ActivationReceipts` is step 1's `ReceiptSource`, and it answers exercise and health with empty records. `finalize_startup` records the receipts through `probos.startup.activation_receipts` on `runtime.activation_receipts`, one log line each. The boot camp's receipt lists the AD-638 coordinator, then the AD-683 late-bind, then the cold-start enrolment, in slice 4b's order, which is unchanged; a warm boot's skipped enrolment is still an activation, a failed one is not. Working-memory cognition's receipt follows its start (off by default, so not activated). The Night Orders escalation's receipt lists its three links: the manager, the bridge alerts and the Ward Room router. Owners are matched by class path, so a test double is recorded as not activated, and each receipt site is log-and-degrade. Three declarations join the inventory: `core.boot-camp` and `core.night-orders-escalation` in a new `probos.maturity_declarations`, and `cognitive.working-memory-cognition`. The offline inventory still shows `activated` as `unknown`, and its header now says why. Production writes receipts and reads none; two source censuses in `tests/test_ad1270a_startup_receipts.py` pin the importers and the absence of a reader. The eight step-1 declarations have no receipt point yet (#1324 register 5-R1). The contract is `prompts/ad-1270a-activation-receipts.md`.

```

**Pair U2 (`DECISIONS.md`).** SEARCH:
```
### AD-1270 (#1324) -- the boot-camp tail: AD-509's tracker and AD-638's phases 2 and 3 deleted; AD-683's snapshot keyed on enrolment (2026-10-28)
```
REPLACE:
```
### AD-1270 (#1324) -- AD-1270a migration step 2: activation receipts at finalization for the boot camp, working-memory cognition and the Night Orders escalation (2026-10-2X)

**Decision.** Record an in-process activation receipt after each of three startup ownership points, from that point's own result: the AD-638 coordinator with the AD-683 late-bind and the cold-start enrolment, AD-668/AD-670 working-memory cognition after it starts, and the Night Orders escalation's three links. Keep them on `runtime.activation_receipts`, log one line each, and serve them through `ActivationReceipts`, step 1's `ReceiptSource`, which supplies no exercise and no health. Activated means startup wired the declared owner, matched by class path, and the point's own step did not fail; a warm boot's skipped enrolment is an activation. Declare the three owners. Change nothing about what finalization wires or in which order, and make each receipt site log-and-degrade. **Why.** The plan sequenced step 2 after slices 1, 3 and 4b/4c so that receipts cover the owners those slices wired instead of being retrofitted. A call at each point sees the late-bind result, the enrolment outcome and a start error, which a sweep after wiring cannot see without inferring activation from construction. **Effect.** Startup gains three log lines and one runtime attribute. No event type, config key, file or JSON-schema change; the inventory gains three rows and a reworded header, and `activated` there stays `unknown` because the generator runs offline. **Captain.** Nothing is parked. He may widen receipts to the step-1 declarations (a later slice) or ask for exposure (step 5). **Rejected.** A post-wiring sweep (it guesses from construction). A new event type (it joins the durable-event contract for an observation). A ledger file (a new persisted schema). Receipts parameters on the wirers (signature churn, and the wirers coupled to the observation package). A receipt-point field in the declaration schema (`notes` carries it). Booting a runtime in the generator (`--check` would stop being hermetic).

### AD-1270 (#1324) -- the boot-camp tail: AD-509's tracker and AD-638's phases 2 and 3 deleted; AD-683's snapshot keyed on enrolment (2026-10-28)
```

**Pair U3 (`docs/development/platform-maturity-program.md`).** SEARCH:
```
- **AD-1270a capability truth shadow report — migration step 1 DELIVERED (inventory only).**
    `src/probos/maturity/` resolves eight declarations against three distinct
    authorities (import system / `SystemConfig` / `list_capability_catalog`) and
    renders `docs/development/capability-truth-inventory.md` via a `--check`-able
    generator. Observation only: zero production call sites changed, and nothing
    reads a row to make a decision. **Migration steps 2-5 remain open** — activation
    receipts (step 2), exercise receipts (step 3), Doctor reuse and a live-runtime
    projection (step 5) have no producer yet, so `advertised`, `activated`,
    `exercise` and `health` are honestly `unknown` and no row can evaluate `live`.
```
REPLACE:
```
- **AD-1270a capability truth shadow report — migration step 1 DELIVERED (inventory only); step 2 delivered for three owners (#1324 slice 5).**
    `src/probos/maturity/` resolves the declarations against three distinct
    authorities (import system / `SystemConfig` / `list_capability_catalog`) and
    renders `docs/development/capability-truth-inventory.md` via a `--check`-able
    generator; step 1 shipped eight. Observation only: nothing reads a row to make
    a decision. **Step 2:** finalization records an activation receipt (the owner,
    whether startup wired it, and the evidence in order; not a health claim) for
    `core.boot-camp`, `cognitive.working-memory-cognition` and
    `core.night-orders-escalation`, keeps them on `runtime.activation_receipts` and
    logs one line each; production writes receipts and reads none. The other
    declarations have no receipt point yet. **Steps 3-5 remain open** — exercise
    receipts (step 3), Doctor reuse and a live-runtime projection (step 5) have no
    producer yet, so `advertised`, `exercise` and `health` are honestly `unknown`,
    the offline inventory shows `activated` as `unknown` too, and no row can
    be `live`.
```

Parent checklist (the orchestrator, on #1324): add and tick a slice-5 item with the commits and the receipt.

## 9. What this does NOT change

- What finalization wires, and in which order: the AD-683 wiring, the late-bind, the activation and its `try`, the cognition start after the AD-573 restore, and the Night Orders and router construction. 4b's AST cases and §7.4.N's position case pin this.
- `report.build_rows`, `_resolve_receipts`, `CapabilityRow.live`, the `probos.capability-truth.v1` JSON shape, `scripts/gen_capability_truth.py`, and the eight step-1 declarations (no receipt point; register 5-R1).
- `runtime.py`: the attribute is set by finalization, as `runtime.working_memory_cognition` is. No `__init__` declaration (register 5-R3).
- Event types, config models, `config/system.yaml`, the facade baseline, the config reference, the AD-1152 golden, `architecture-baseline.yaml` (no row change), `dormant-class-baseline.yaml` (checked, not regenerated) and the seam manifest.
- `_is_new_crew_start` and BF-034's detector (slice 4d), shutdown, Doctor and any API route (step 5).

## 10. Mutation rows (one campaign of record on the M2 tree, after an unmutated baseline of the three files below passes; run on the Captain's Windows host)

Run with `--tests "tests/test_ad1270a_activation_receipts.py tests/test_ad1270a_startup_receipts.py tests/test_ad1270a_capability_truth.py"`. Every claimed function is defined in those files. No row is equivalent.

Two properties are pinned by the AST case `test_finalization_records_each_receipt_after_its_ownership_point`, not by a row: each receipt call's position after its ownership point, and `begin_activation_receipts` before the first wirer. A single-line mutant cannot move a block.

| # | M | File | Line | Mutate to | Killed by |
|---|---|---|---|---|---|
| R-1 | M1 | `maturity/receipts.py` | `return TriState.TRUE if receipt.activated is True else TriState.FALSE` | `return TriState.TRUE if receipt.activated else TriState.FALSE` | `test_only_true_reads_as_activated[int]`, `test_only_true_reads_as_activated[str]`, `test_only_true_reads_as_activated[float]` |
| R-2 | M1 | `maturity/receipts.py` | `return TriState.UNKNOWN` | `return TriState.FALSE` | `test_no_receipt_is_unknown_not_false`, `test_receipts_reach_the_report_row_and_leave_live_unknown` |
| R-3 | M1 | `maturity/receipts.py` | `if receipt.capability_id in self._receipts:` | `if False:` | `test_a_second_receipt_for_an_id_is_dropped_and_logged` |
| R-4 | M1 | `maturity/receipts.py` | `self._receipts[receipt.capability_id] = receipt` | `pass` | `test_a_recorded_receipt_answers_its_activation`, `test_receipts_keep_the_order_startup_recorded_them` |
| R-5 | M1 | `maturity/receipts.py` | `return ExerciseRecord()` | `return ExerciseRecord(attempts=1, last_success="2026-01-01T00:00:00Z")` | `test_a_receipt_is_no_exercise_and_no_health`, `test_receipts_reach_the_report_row_and_leave_live_unknown` |
| R-6 | M1 | `maturity/receipts.py` | `return HealthRecord()` | `return HealthRecord(source="activation")` | `test_a_receipt_is_no_exercise_and_no_health` |
| R-7 | M1 | `maturity/receipts.py` | `return tuple(self._receipts.values())` | `return tuple(sorted(self._receipts.values(), key=lambda r: r.capability_id))` | `test_receipts_keep_the_order_startup_recorded_them` |
| R-8 | M1 | `maturity/receipts.py` | the R-6 line (the file's last line, in `health_for`) | `return HealthRecord()\n\n\n_DEFAULT_RECEIPTS = ActivationReceipts()` | `test_activation_receipts_is_not_a_singleton` |
| R-9 | M1 | `maturity/receipts.py` | `from probos.maturity.model import ExerciseRecord, HealthRecord, TriState` | `from probos.maturity.model import ExerciseRecord, HealthRecord, TriState\nimport probos.utils` | `test_receipts_import_only_the_maturity_model` |
| R-10 | M1 | `maturity/receipts.py` | `"evidence": list(self.evidence),` | `"evidence": self.evidence,` | `test_to_dict_is_json_safe_and_ordered` |
| S-1 | M2 | `startup/activation_receipts.py` | `activated=observed == BOOT_CAMP_OWNER and enrolment_error is None,` | `activated=observed == BOOT_CAMP_OWNER,` | `test_a_failed_enrolment_is_not_an_activation`, `test_a_finalization_publishes_its_receipts_on_the_runtime[failed]` |
| S-2 | M2 | same | same | `activated=enrolment_error is None,` | `test_boot_camp_not_activated_without_a_coordinator_or_with_a_stand_in[none]`, `test_boot_camp_not_activated_without_a_coordinator_or_with_a_stand_in[stand-in]`, `test_a_real_boot_publishes_its_receipts` |
| S-3 | M2 | `startup/activation_receipts.py` | `activated=all(path == owner for _, path, owner in seen),` | `activated=any(path == owner for _, path, owner in seen),` | `test_night_orders_escalation_activated_only_with_all_three_links[no-manager]`, `test_night_orders_escalation_activated_only_with_all_three_links[no-alerts]`, `test_night_orders_escalation_activated_only_with_all_three_links[no-router]`, `test_night_orders_escalation_activated_only_with_all_three_links[stand-in-alerts]` |
| S-4 | M2 | `startup/activation_receipts.py` | `activated=observed == COGNITION_OWNER and start_error is None,` | `activated=observed == COGNITION_OWNER,` | `test_a_failed_cognition_start_is_not_an_activation` |
| S-5 | M2 | `startup/activation_receipts.py` | `return f"{cls.__module__}.{cls.__qualname__}"` | `return cls.__qualname__` | `test_the_declared_owners_are_the_classes_startup_wires[boot-camp]`, `test_the_declared_owners_are_the_classes_startup_wires[ward-room-router]`, `test_boot_camp_activated_when_phase_7_wired_the_coordinator[bound-ran]` |
| S-6 | M2 | `startup/activation_receipts.py` | `if value is None:` | `if False:` | `test_boot_camp_not_activated_without_a_coordinator_or_with_a_stand_in[none]`, `test_working_memory_cognition_off_is_not_activated`, `test_a_real_boot_publishes_its_receipts` |
| S-7 | M2 | `startup/activation_receipts.py` | `runtime.activation_receipts = receipts` | `pass` | `test_begin_publishes_a_fresh_receipt_set_on_the_runtime`, `test_a_real_boot_publishes_its_receipts`, `test_a_finalization_publishes_its_receipts_on_the_runtime[skipped]` |
| S-8 | M2 | `startup/activation_receipts.py` | `receipts.record(build())` | `build()` | `test_the_boot_camp_receipt_from_the_real_helpers_reaches_the_report_row`, `test_a_finalization_publishes_its_receipts_on_the_runtime[skipped]` |
| S-9 | M2 | `startup/activation_receipts.py` | `return "ran" if enrolled else "skipped"` | `return "ran"` | `test_boot_camp_activated_when_phase_7_wired_the_coordinator[not-attempted-skipped]`, `test_boot_camp_activated_when_phase_7_wired_the_coordinator[not-bound-skipped]`, `test_a_finalization_publishes_its_receipts_on_the_runtime[skipped]` |
| S-10 | M2 | `startup/activation_receipts.py` | `return "bound" if bound else "not bound"` | `return "bound"` | `test_boot_camp_activated_when_phase_7_wired_the_coordinator[not-bound-skipped]` |
| S-11 | M2 | `startup/activation_receipts.py` | `evidence.append(f"start failed ({start_error})")` | `pass` | `test_a_failed_cognition_start_is_not_an_activation`, `test_a_finalization_publishes_its_receipts_on_the_runtime[failed]` |
| S-12 | M2 | `startup/activation_receipts.py` | `return receipts` | `return receipts if receipts.receipts() is not None else receipts` | `test_production_writes_the_receipts_and_reads_none` |
| S-13 | M2 | `startup/activation_receipts.py` | `from probos.maturity.receipts import ActivationReceipt, ActivationReceipts` | `from probos.maturity.receipts import ActivationReceipt, ActivationReceipts\nfrom probos.maturity.report import build_rows` | `test_production_imports_of_the_maturity_package_are_the_known_set` |
| F-1 | M2 | `startup/finalize.py` | `activation_receipts = begin_activation_receipts(runtime)` | `activation_receipts = begin_activation_receipts(object())` | `test_a_finalization_publishes_its_receipts_on_the_runtime[skipped]`, `test_a_finalization_publishes_its_receipts_on_the_runtime[enrolled]`, `test_a_finalization_publishes_its_receipts_on_the_runtime[failed]`, `test_a_real_boot_publishes_its_receipts` |
| F-2 | M2 | `startup/finalize.py` | `_boot_camp_late_bind = _late_bind_boot_camp_snapshot(runtime=runtime) is True` | `_late_bind_boot_camp_snapshot(runtime=runtime)` | `test_a_finalization_publishes_its_receipts_on_the_runtime[skipped]` |
| F-3 | M2 | `startup/finalize.py` | `_boot_camp_enrolled = await _activate_boot_camp_on_cold_start(runtime=runtime) is True` | `await _activate_boot_camp_on_cold_start(runtime=runtime)` | `test_a_finalization_publishes_its_receipts_on_the_runtime[enrolled]` |
| F-4 | M2 | `startup/finalize.py` | `_boot_camp_enrolment_error = type(_boot_camp_exc).__name__` | `pass` | `test_a_finalization_publishes_its_receipts_on_the_runtime[failed]` |
| F-5 | M2 | `startup/finalize.py` | `_cognition_start_error = type(_cognition_exc).__name__` | `pass` | `test_a_finalization_publishes_its_receipts_on_the_runtime[failed]` |
| F-6 | M2 | `startup/finalize.py` | `runtime, night_orders_mgr=night_orders_mgr, ward_room_router=ward_room_router` | `runtime, night_orders_mgr=night_orders_mgr, ward_room_router=None` | `test_a_finalization_publishes_its_receipts_on_the_runtime[skipped]` |
| F-7 | M2 | `startup/finalize.py` | `lambda: working_memory_cognition_receipt(runtime, start_error=_cognition_start_error),` | `lambda: working_memory_cognition_receipt(runtime, start_error=None),` | `test_a_finalization_publishes_its_receipts_on_the_runtime[failed]` |
| D-1 | M2 | `maturity_declarations.py` | `configured_when="boot_camp.enabled",` | `configured_when="boot_camp.relax_quality_gates",` | `test_the_inventory_matches_the_declarations` |
| D-2 | M2 | `maturity/registry.py` | `"probos.maturity_declarations",  # AD-1270a step 2 (#1324 slice 5): top-level (core) owners` | `# removed` | `test_load_default_registry_ships_exactly_the_declared_inventory`, `test_each_receipt_owner_is_its_declarations_owner[boot-camp]`, `test_each_receipt_owner_is_its_declarations_owner[night-orders-escalation]`, `test_the_inventory_matches_the_declarations` |
| D-3 | M2 | `maturity_declarations.py` | `owner_symbol="BridgeAlertService",` | `owner_symbol="WardRoomRouter",` | `test_every_shipped_declaration_resolves_present_true`, `test_each_receipt_owner_is_its_declarations_owner[night-orders-escalation]`, `test_the_inventory_matches_the_declarations` |
| D-4 | M2 | `cognitive/maturity_declarations.py` | `id="cognitive.working-memory-cognition",` | `id="cognitive.working-memory",` | `test_load_default_registry_ships_exactly_the_declared_inventory`, `test_each_receipt_owner_is_its_declarations_owner[working-memory-cognition]`, `test_the_inventory_matches_the_declarations` |

## 11. Verified Against Codebase (2026-10-28, on the oracle `67928365`, tree `17f9ec0d`)

Read and Grep tool calls in this worktree:

```
Read src/probos/maturity/model.py
  215-233: class ReceiptSource(Protocol): activation_for / exercise_for / health_for
  218-220: "Nothing implements this in production in this slice — migration steps 2 and 3 do."
  169-197: CapabilityRow.live: activated is excluded from the INERT test; UNKNOWN without exercise
Read src/probos/maturity/report.py
  172-198: _resolve_receipts: receipts None -> UNKNOWN, empty records; per-axis try
  224-230: async def build_rows(registry, *, config, runtime=None, receipts=None)
  305-336: _HEADER (the two P-H pairs' SEARCH text)
Read src/probos/maturity/registry.py
  26-31: DECLARATION_MODULES = cognitive, tools, agents, infrastructure
Read src/probos/maturity/__init__.py
  1-7: "Nothing in ``src/probos/`` imports it"; 22-45 imports and __all__
Read scripts/gen_capability_truth.py
  41-49: build_rows(registry, config=config, runtime=None)  (no receipts, offline)
Read tests/test_ad1270a_capability_truth.py
  290-307 exact inventory; 566-585 --check subprocess; 595-617 no tokens/dates;
  652-667 no LIVE row, "| live |" absent; 670-688 configured discriminates on SystemConfig();
  707-736 model leaf + declaration modules import only the model; 739-762 ReceiptSource seam test
Read src/probos/{cognitive,tools,agents,infrastructure}/maturity_declarations.py (four modules, eight declarations)
Grep "^async def |^def |_activate_boot_camp_on_cold_start|_late_bind_boot_camp_snapshot" src/probos/startup/finalize.py
  819 _start_working_memory_cognition; 883 _late_bind_boot_camp_snapshot (-> bool, :894);
  918 _activate_boot_camp_on_cold_start (-> bool); 4146 finalize_startup; 4216; 4222
Read src/probos/startup/finalize.py
  17-23 imports (P-F1); 4170-4173 (P-F2); 4212-4224 (P-F3); 4306-4311 NightOrdersManager under
  proactive_cognitive.enabled and runtime.ward_room; 5554-5555 WardRoomRouter under runtime.ward_room;
  6423-6428 (P-F4); 6820-6829 the return (P-F5); 827, 856-857: working_memory_cognition = None first,
  published after start()
Grep "^    return |^        return FinalizationResult" src/probos/startup/finalize.py
  6821 is the one function-level return after 4146
Read src/probos/runtime.py
  2137-2192 escalation reads _night_orders_mgr, bridge_alerts, ward_room_router; 3324-3340 Phase 7
  coordinator (needs ward_room, trust, episodic memory); 3343 bridge_alerts; 3598-3605 fin.* assigned
Grep "self.ward_room" src/probos/runtime.py -> 1091, 3281;  communication.py:408-409 ward_room only if config.ward_room.enabled
Grep classes: bridge_alerts.py:57 BridgeAlertService; watch_rotation.py:302 NightOrdersManager;
  ward_room_router.py:36 WardRoomRouter; boot_camp.py:49 BootCampCoordinator;
  cognitive/working_memory_cognition.py:59 WorkingMemoryCognition, 84-87 running, 142-147 start
Read src/probos/boot_camp.py:64-121 (constructor, clock, bind_ship_state_builder -> bool)
Grep config: config_models/crew.py:19-20 BootCampConfig.enabled default True; :314 WardRoomConfig.enabled False;
  config_models/cognition.py:294 cognition_enabled default False; config.py:3208-3210
  ProactiveCognitiveConfig.enabled False; config.py:3950 ward_room; config.py:40 re-exports WorkingMemoryConfig
Read config/system.yaml 1042-1043 proactive_cognitive enabled true; 1967-1980 working_memory (no
  cognition_enabled); 2109-2116 boot_camp enabled true, no relax_quality_gates
Read tests/test_ad1270_boot_camp_lifecycle.py:394-416, test_ad1270_boot_camp_orientation.py:255-303,
  test_ad1270_working_memory_cognition.py:862-869 (call counts and order by AST; one call each)
Read tests/test_new_crew_auto_welcome.py:165-225 (MagicMock rig that completes finalize_startup);
  tests/test_ad641d_deliberation.py:250-257 (a thinner rig, skipped: BF-657 hang)
Read tests/test_bf927_boot_claims.py:529-551 (a real ProbOSRuntime boot on tmp_path in the suite)
Read tests/test_layer_boundaries.py:16-27,137-165 (maturity, startup unmapped -> unchecked)
Read docs/development/architecture-baseline.yaml:12-17 (layers: substrate..experience)
Read scripts/check_seam_contracts.py:319-387 (DECLARATION_MODULES by AST; reads seam_ids only)
Read scripts/check_dormant_classes.py:1-33 (report-only; exit 0); baseline maturity/registry.py false-positive
Read scripts/check_config_readers.py:80-102 (names = attributes, string constants, call keywords)
Read scripts/gen_ad_ledger.py:120-139,176-184 (keywords, 120-character head window)
Read logs/ad1270/s6_census.py:1-104 and census_rows_audit2.py (the row grammar in §10)
Grep pyproject.toml asyncio_mode -> 181: "auto"
```

## Absence Verified (2026-10-28)

```
CLAIM: no production module outside the maturity package imports it, other than the four declaration modules
RUN:   Grep "probos\.maturity" src
FOUND: the four */maturity_declarations.py (probos.maturity.model) and maturity/* itself
HOLDS: yes

CLAIM: nothing in src reads a receipt source today
RUN:   Grep "\.(receipts|receipt_for|activation_for|exercise_for|health_for)\b" src/probos
FOUND: maturity/report.py:182, :189, :194 only
HOLDS: yes (the census excludes maturity/)

CLAIM: the new names are free
RUN:   Grep "activation_receipts|ActivationReceipt|activation receipt|maturity/receipts|crew\.boot-camp|night-orders-escalation|working-memory-cognition" src, tests (-i)
FOUND: runtime.py:2184 task name "night-orders-escalation"; working_memory_cognition.py:147 and
       tests/test_ad1270_working_memory_cognition.py:52 task name "ad1270-working-memory-cognition"
HOLDS: yes (task names, not capability ids or symbols)

CLAIM: no local name in startup collides
RUN:   Grep "receipt|activation_" src/probos/startup (-i)
FOUND: activation_tracker (cognitive_services, dreaming, results, shutdown), department_activation_scheduler (finalize.py:1067)
HOLDS: yes

CLAIM: no config field shares a name with the new keywords or strings (BF-926's reader scan)
RUN:   Grep "^\s+(owner|evidence|activated|enrolled|late_bind|enrolment_error|start_error|capability_id|night_orders_mgr|ward_room_router|bound|skipped|ran|build|receipts|runtime|value|cls|links|seen|observed|label|path):\s" config.py, config_models/*.py
FOUND: none
HOLDS: yes

CLAIM: maturity and startup are unranked for both layer checks
RUN:   Read tests/test_layer_boundaries.py:16-27; Read architecture-baseline.yaml:12-17; Grep "maturity|finalize" architecture-baseline.yaml
FOUND: LAYER_MAP has neither; layers substrate..experience; only crew_finalizer::CrewSessionFinalizer matches "finalize"
HOLDS: yes

CLAIM: no test pins platform-maturity-program.md text
RUN:   Grep "platform-maturity-program" tests
FOUND: none
HOLDS: yes
```

## Not verified (the orchestrator verifies by running)

- Each predicted case count, each focused gate, the regenerated inventory's diff, and the dormant-check output at M1 and M2.
- That the auto-welcome rig wires a real `ShipStateSnapshotBuilder` (so the late-bind reads `bound`) and a real `WardRoomRouter`. The code path says so: `finalize.py:1267-1281` with a MagicMock config, and `:5554-5555` with an `AsyncMock` Ward Room.
- That a default-config real boot builds no Ward Room, no coordinator, no cognition driver and no Night Orders manager (`communication.py:408-409`; `runtime.py:3324-3329`; the defaults above).
- The `contract_claims_inventory.py` output for this draft: the bridge cannot run Python. §15's last item asks the reviewer to run it.

## 12. Deterministic gate checks, resolved up front

- **Generated files that move:**
  - `docs/development/capability-truth-inventory.md` (M2). Regenerate with `python scripts/gen_capability_truth.py`; check with `--check`, which `test_the_inventory_matches_the_declarations` runs.
  - `docs/development/open-ads-report.md` and `docs/development/ad-ledger-snapshot.json` (M3, if they change). Regenerate with `python scripts/gen_ad_ledger.py`; check with `-P scripts/gen_ad_ledger.py --check`.
- **Checked, not regenerated:**
  - `-P scripts/check_architecture_principles.py --check` passes with no row change.
  - `-P scripts/check_seam_contracts.py --check` passes.
  - `-P scripts/check_dormant_classes.py --check` is report-only. At M2 it must list no new candidate.
- **No change expected:** the config facade baseline, the config reference, the config profiles and the AD-1152 golden (no config, schema or event change). The broad gate measures them.
- **Broad gate**, once after M3, with its receipt: `d:/ProbOS/.venv/Scripts/python.exe scripts/run_test_gate.py --label ad1270-activation-receipts --receipt logs/gates/ad1270-activation-receipts.receipt.json`.

## 13. Prior Art and Blind Spots

**Internal.**
- AD-1270a's program text (Decision, Ownership, Migration): reused as the definition of `activated`.
- Step 1's `ReceiptSource` seam: reused unchanged; no new resolver.
- `tests/test_bf927_boot_claims.py`'s real boot: reused as the production-path vehicle.
- `test_new_crew_auto_welcome.py`'s rig: reused as the only full-finalize rig that completes. `test_ad641d`'s thinner rig is skipped as hanging (BF-657).

**External** (two searches, 2026-10-28):
- [Spring Framework `ApplicationStartup`](https://docs.spring.io/spring-boot/4.0/api/rest/actuator/startup.html) records startup steps with ordered tags. **Adopted:** evidence is an ordered tuple of facts per step. **Rejected:** its buffer is drained by a POST endpoint ([source](https://code.yawk.at/org.springframework.boot/spring-boot-actuator/2.4.1/org/springframework/boot/actuate/startup/StartupEndpoint.java)). Here a read must not mutate, and exposure is step 5's job. See also [Baeldung](https://www.baeldung.com/spring-boot-actuator-startup).
- [systemd's `ActiveState` and `SubState`](https://flaviocopes.com/courses/systemd/read-unit-state/) separate "started" from "working", and a oneshot unit stays "active (exited)". **Adopted:** activation is not health, and a warm boot's skipped enrolment is still an activation.
- `docs/research/reference-projects.md`: no listed project addresses startup activation evidence. Its overdue rows were considered and deferred (judged on 2026-10-28). No row updates (read-only run).

**Blind spots, decided:**
- Receipts describe the last finalization in the process; an in-process restart rebuilds them.
- `runtime.activation_receipts` is set only by `begin_activation_receipts`, at the top of `finalize_startup`, whose only caller in `src` is Phase 8 (`runtime.py:3598`). It is absent before Phase 8, after a boot that fails earlier, and when the runtime refuses it. Step 5 must read it with `getattr` (register 5-R2).
- Matching by class path reads a future subclass or proxy of an owner as not activated. The failure is loud in the receipt, and the owner-class case pins the paths.
- Evidence strings are diagnostic text, not an API. A reader should use `activated`.
- `configured` yes with `activated` no is the finding this ledger exists to show. Example: boot camp enabled in `system.yaml`, but no Ward Room, so no coordinator.
- The full-finalize case depends on the auto-welcome rig's opt-outs. If a future wirer hangs on it (the BF-657 pattern), the helper-level crossing and the real-boot case still stand.
- Slice 4d (BF-034) may touch the same finalization region. A1 re-anchors on the real tree.
- **Considered, deferred:** receipts for the step-1 declarations (5-R1; `cognitive.crew-session` is the cheapest, through `_wire_crew_orchestrator`'s `bool`).

## 14. Diff Reviewer: properties to verify

1. Finalization wires the same things in the same order: the AD-683 wiring, then the late-bind, then the activation (awaited, inside its `try`), then cognition after the AD-573 restore. Only receipt code is added.
2. A receipt site cannot raise into startup: `begin_activation_receipts` and `record_activation` catch `Exception`, and the builders run inside `record_activation`.
3. A receipt names the owner and the evidence. It produces no exercise and no health, and no path makes `live` read `live` from a receipt.
4. A test double is never an activated owner.
5. Production imports `probos.maturity` only at the census's set, and reads no receipt (the two census cases).
6. There is no module-level receipt instance, and receipts hold strings, not owner objects.
7. The declarations are data only and import only the model. Each receipt owner constant equals its declaration's owner.
8. The inventory was regenerated by tool, and its header is true on the head.
9. No event type, config key, persisted file or JSON-schema change.
10. The MagicMock rig mirrors the auto-welcome rig (`tests/test_new_crew_auto_welcome.py:186-222`) plus three lines (`runtime.boot_camp`, `runtime.working_memory_cognition`, `config.working_memory`), and `monkeypatch` restores what it patches, `aiosqlite.connect` included.
11. (A1) The rig case records every sqlite connection opened during its finalization. In a `finally` it closes them, then the attachment store's I/O threads. A serial run of the file exits by itself (§15's probe run).

## 15. Acceptance criteria

- The focused gates of M1 to M3 pass, and the census of record in §10 kills every row.
- `scripts/gen_capability_truth.py --check`, `-P scripts/check_seam_contracts.py --check`, `-P scripts/check_architecture_principles.py --check` and `-P scripts/gen_ad_ledger.py --check` pass. AD-1270 still resolves `shipped`.
- `test_a_real_boot_publishes_its_receipts` and `test_a_finalization_publishes_its_receipts_on_the_runtime` pass on the head.
- (A1) On the frozen M2 candidate, the orchestrator runs `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad1270a_startup_receipts.py -n 0` once, under its session-finish probe (`threading.enumerate()` at `pytest_sessionfinish`, `faulthandler.dump_traceback_later(20, exit=True)`). Pass: 33 passed, and the process exits with pytest's own status before the timer. A `_connection_worker_thread` in the probe's list is a stop, back to the Architect. A `probos-attachment-io` worker that is listed but gone by exit is recorded, not a stop.
- The broad gate's receipt is green.
- Verify that the changes comply with the Engineering Principles in `.github/copilot-instructions.md`.
- Run `logs/ad1270/contract_claims_inventory.py` on this contract, and check each listed head-describing line against the head.

## 16. Amendment A1 (2026-10-28, on the real 4c candidate `8cb4bad5`, tree `1e8bcaea`)

**16.1 The `-n 0` hang (decided).** The dry run measured it: `pytest tests/test_ad1270a_startup_receipts.py -n 0` printed `33 passed` and the interpreter did not exit. A session-finish probe found one live non-daemon aiosqlite worker thread and one `probos-attachment-io` worker per case of `test_a_finalization_publishes_its_receipts_on_the_runtime`. `tests/test_new_crew_auto_welcome.py`, whose rig this case mirrors, leaves the same threads (pre-existing). xdist runs end normally.

Decision: the case records every sqlite connection opened while finalization runs. `_record_sqlite_connections` wraps the call-time `aiosqlite.connect` lookup that every production open uses. In a `finally`, the case closes them with `aiosqlite.Connection.close()`, then closes the attachment store's I/O threads with `probos.routers.chat.close_attachment_store(runtime)` (which calls `FilesystemAttachmentStore.close()`).

Not adopted:
- A real `tmp_path` as the rig's `runtime.data_dir`. It changes which stores finalization can open (for example `EvolutionStore(chroma_path=runtime.data_dir)`, `finalize.py:2653-2660`, and the backup roots, `:3742-3747`), an unmeasured change to the rig's behaviour and its thread profile. The `MagicMock/` directory that the BF-326 janitor cleans therefore stays (5-R4).
- Instructions alone (run this file with `-n 4`). They hide a leak that any serial run, the census of record included, then waits on.

`tests/test_new_crew_auto_welcome.py` and `tests/conftest.py` are shared and unchanged in this slice (5-R4).

**16.2 Head-text check.** Every head-describing sentence was checked against `8cb4bad5`.
- Repaired: the front matter's review sentence, counts and BF-927 comparison; §4's `-n` rule; §5's `runtime.activation_receipts` and BF-926 items; §10's pinned-properties sentence; §13's attribute blind spot; §14 item 10 and the new item 11; §15's exit criterion; 5-R2; and the new 5-R4.
- The rest held.
- Two oracle records are now measured by the dry run:
  - §11's first rig item under "Not verified": the `[skipped]` case passed, so the late-bind read `bound` and the router was a real `WardRoomRouter`.
  - §13's "the only full-finalize rig that completes": it completes, and it leaks threads (16.1).

**16.3 The review round (M2's HIGH tier).**
- **Reviewer and scope.** One reviewer, `gpt-6.1-sol`, in one round over all three milestones: `git diff <4c merge> <M3 head>`. M1 has no production importer until M2, so the receipt seam can only be reviewed with M2. M3's tracker text is in scope for its truth on the head and for §8's head constraint.
- **Inputs.** This contract, the diff, `git diff --stat <4c merge> <M3 head>`, the claims inventory (`logs/ad1270/contract_claims_inventory.py` on this contract, as run for `claims-ad1270s5-draft.txt`), the dry-run logs, and the §15 probe output.
- **§14, by execution** (all pytest runs `d:/ProbOS/.venv/Scripts/pytest.exe ... -n 4`):
  1. `tests/test_ad1270_boot_camp_lifecycle.py tests/test_ad1270_boot_camp_orientation.py tests/test_ad1270a_startup_receipts.py -k "after_the_snapshot_late_bind or late_binds_through_the_public_setter or after_its_ownership_point"`. Then read `git diff <4c merge> <M3 head> -- src/probos/startup/finalize.py`: only added lines and the result captures.
  2. `tests/test_ad1270a_startup_receipts.py -k "cannot_be_built or refuses_the_attribute or publishes_its_receipts_on_the_runtime"`.
  3. `tests/test_ad1270a_activation_receipts.py -k "no_exercise or never_makes_a_row_live or leave_live_unknown"`.
  4. `tests/test_ad1270a_startup_receipts.py -k "stand_in or all_three_links"`.
  5. `tests/test_ad1270a_startup_receipts.py -k "known_set or reads_none"`.
  6. `tests/test_ad1270a_activation_receipts.py -k "not_a_singleton or json_safe"`.
  7. `tests/test_ad1270a_startup_receipts.py -k "declarations_owner or classes_startup_wires"`, and `d:/ProbOS/.venv/Scripts/python.exe -P scripts/check_seam_contracts.py --check`.
  8. `d:/ProbOS/.venv/Scripts/python.exe scripts/gen_capability_truth.py --check`.
  9. The `--stat` lists no `config.py`, `config_models/`, `config/system.yaml`, event-type or schema file.
  10. and 11. Read the rig against `tests/test_new_crew_auto_welcome.py:186-222`, and read the §15 probe output.
- **The `-n 0` hazard.** The reviewer runs tests with `-n 4` only (both new files together: 49 passed) and reads the orchestrator's probe run for the serial exit. It runs no file of M2's gate with `-n 0` outside that probe.
- **End of the round.** The round ends when the verdict marks each property verified or a finding, and no Critical or High finding is open. Repairs are re-reviewed as a delta (Review Rounds and Progress).
- **Recorded, not blocking:**
  - the BF-326 `MagicMock/` warning on the three rig cases;
  - the `coroutine ... was never awaited` warnings from the rig's `AsyncMock` Ward Room (`finalize.py:5556`, `:5568`, `:5570`, `:6137`, as in the auto-welcome rig);
  - the dormant check's report-only lines;
  - 5-R4;
  - Low findings and nits.

**16.4 Tiers.** M1 stays STANDARD: it adds a leaf module, two exports and a docstring. It has no production importer until M2 (the importer census pins this) and no security, governance or data-integrity surface. No Captain ruling.

## 17. Amendment A2 (2026-10-28, on slice 4c's final head `698ec7e1`, tree `a8dae8cb`)

- **§4's base lines.** The draft predicted `ModuleNotFoundError` on both bases. A1's dry run measured `ImportError` at the new files' first import of the new code (`evidence-ad1270s5-a1-tf1.txt` and `-tf2.txt`: one collection error each, pytest exit 2). §4 now states those measurements. No other line names the error.
- **Head-text check.** From `8cb4bad5` to `698ec7e1`, `git diff --stat` lists three files: `prompts/ad-1270-boot-camp-tail.md`, `src/probos/holodeck/phases.py` and `tests/test_ad1270_boot_camp_trust.py` (4c's A4 and R1). This contract cites none of them, so A1's head-text check (16.2) still holds. Spot-checked on `698ec7e1` and holding: the citations to `test_bf927_boot_claims.py:545-549`, `runtime.py:3598`, `check_config_readers.py:80-102` and `test_new_crew_auto_welcome.py:186-222`; the M2 and M3 gate file lists; and U1 to U3's SEARCH anchors.

## 18. Amendment A3 (2026-10-28, on slice 4c's final head `698ec7e1`)

- **§4's predicted rows.** M2 step 5 said every axis other than `configured` reads `unknown`, with live `unknown`. Two independent builds regenerated the same inventory and measured `present` `yes` on all three rows and `live` `inert` on `cognitive.working-memory-cognition`, whose `configured` is `no` (`maturity/model.py:182-183`). Step 5 now states the measured rows.
- **What 16.2 and A2 missed.** Their checks covered sentences describing the head, not predictions of build output, and A1's dry run did not regenerate the inventory. A Grep of this contract for `unknown`, `inert`, `inventory`, `rows` and `predicted` finds no other claim about these rows' axis values. §2 and §5 say `activated` reads `unknown` offline (true). P-H2's and U3's "no row can read (or evaluate) `live`" mean that no row reaches `live`, which holds with an `inert` row; their bodies are unchanged.

## 19. Amendment A4 (2026-10-28, on slice 4c's final head `698ec7e1`)

- **Round 1's finding (P3, ordinary reach).** Four shipped texts said a receipted capability's `live` stays `unknown`: U1 (`PROGRESS.md`), 7.1.M (`receipts.py` module docstring) and the 7.1.N and 7.4.N test-module docstrings. `CapabilityRow.live` returns `inert` when `present`, `configured` or `advertised` is `false` (`maturity/model.py:182-183`), which the reviewer measured on `cognitive.working-memory-cognition` through the real receipt source and `build_rows`. Each clause is deleted, and the rest of each sentence stands. No receipt makes a row reach `live` (`model.py:193-194`; §2, §14 item 3).
- **U3.** "No row can evaluate `live`" is weakened to "no row can be `live`". Every row evaluates the property, and one evaluates to `inert`. This supersedes A3's reading of U3 (§18). P-H2's header sentence states a condition on reaching `live`, holds, and is unchanged.
- **What A3's sweep missed.** It covered the contract's own prose, not the prose inside pair and new-file bodies (docstrings in 7.1.M, 7.1.N and 7.4.N, and the tracker texts U1 and U3), which ship. A4's Grep for `stays`, `stay`, `remains`, `unknown`, `live`, `inert` and `LiveState` over the whole contract found no other false claim. The test assertions in 7.1.N and 7.4.N that compare `live` are about specific rows and hold (their line citations were removed after round 2).
- **Scope.** Wording only. No code, assertion, test count, decision or milestone changes. M3's existing `gen_ad_ledger.py` regenerate and `--check` covers the U1 body edit. A delta review round follows.

## 20. Follow-up S5-F1 (2026-10-28, in slice 1b's branch, on `4b228a27`)

- **Finding.** Slice 1b's first canonical gate failed one test, `tests/test_ad152_regressions.py::TestHttpFetchTimeoutMessage::test_timeout_error_message_value`, on an egress refusal. Its file passed when run alone, and failed the same way when run serially after `tests/test_ad1270a_startup_receipts.py` or after `tests/test_new_crew_auto_welcome.py`. Run serially after this file, the other 21 test files that name `HttpFetchAgent` (at `4b228a27`) together showed that one failure and no other.
- **Cause.** `_finalize_rig` passed `config = MagicMock()`, whose `security_infra.egress_active_enforcement` is truthy, so the real `finalize_startup` installed an `EgressPolicy` through `HttpFetchAgent.set_egress_policy`. The policy is a class attribute, and no fixture removed it. Under `--dist=loadfile` a worker runs whole files, and xdist hands them out most tests first after the heaviest few (`tests/fixtures/duration_scheduler.py`): this file (33 tests) is handed out before `test_ad152_regressions.py` (27 tests), while `tests/test_new_crew_auto_welcome.py` (6 tests), the only one of the other four files in 5-R5 that leaves the policy set, is handed out after it.
- **Repair.** The rig sets `config.security_infra = SecurityInfraConfig()`, whose default leaves active enforcement off. The rig's test asserts that `HttpFetchAgent._egress_policy` is the same object after finalization as before. `tests/conftest.py`'s `_ad682_clear_module_caches` resets the policy to `None` at each test's setup when `probos.agents.http_fetch` is loaded, which also covers `tests/test_new_crew_auto_welcome.py` (5-R5). A new file, `tests/test_conftest_egress_policy_isolation.py`, seeds a policy from a module-scoped fixture and asserts that the autouse fixture removed it.
- **Scope.** Tests and this record only. No production file and no slice-1b file changes, and no test is added to `tests/test_ad1270a_startup_receipts.py`.

## For the register (#1324)

- **5-R1.** Activation receipts for the eight step-1 declarations. Their owners are wired outside finalization, except `cognitive.crew-session` (`_wire_crew_orchestrator`).
- **5-R2.** Step 5's reader of `runtime.activation_receipts` must use `getattr`. Only `begin_activation_receipts`, at the top of `finalize_startup` (Phase 8, `runtime.py:3595-3598`), sets it. It is absent before Phase 8, after a boot that fails earlier, and when the runtime refuses the attribute.
- **5-R3.** `ProbOSRuntime.__init__` does not declare `activation_receipts`, as it does not declare `working_memory_cognition`. Declare both together if the runtime's attribute surface is ever made explicit.
- **5-R4.** The MagicMock full-finalize rig family leaks:
  - `tests/test_new_crew_auto_welcome.py` leaves one non-daemon aiosqlite worker and one `probos-attachment-io` worker per case, so a `-n 0` run does not exit (measured 2026-10-28; xdist runs end normally). Its cases also create the `MagicMock/` directory that BF-326 cleans.
  - `tests/conftest.py` clears `_ATTACHMENT_STORE_CACHE` at setup without closing the stores.

  Both are shared. A later BF closes them as §16.1 does (or in a shared fixture), and gives the rig a real data directory once the stores that then open have been measured.
- **5-R5.** A test that runs the real `finalize_startup` as far as its egress block installs `HttpFetchAgent`'s egress policy, a class attribute, when its config reads `egress_enabled` and `egress_active_enforcement` as true, as a MagicMock config does (S5-F1, §20). A Grep for `finalize_startup\(` in `tests/` lists five files. Measured on `4b228a27`, one file per process, by reading `HttpFetchAgent._egress_policy` after the run: slice 5's file and `test_new_crew_auto_welcome.py` left a policy set, and the other three did not. `test_ad641d_deliberation.py`'s only call is in a test marked `skip` (BF-657); `test_bf235_stale_identity_cache.py`'s call is inside `try/except` and does not reach the egress block (that run never imports `probos.agents.http_fetch`); `test_bf908_crew_scope_token.py` never calls it (a docstring and a source-order assertion name it). Slice 5's rig now uses a real `SecurityInfraConfig`. `test_new_crew_auto_welcome.py` is unchanged, and `tests/conftest.py` resets the policy before each test. With a MagicMock config, finalization also sets `standing_orders`' module-level task context and step router (`set_task_context`, `set_step_router`), which `clear_cache` does not reset. No failure from them has been measured.
