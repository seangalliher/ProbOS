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
