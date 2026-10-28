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
