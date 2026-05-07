"""AD-486 v1 — Holodeck Birth Chamber.

Graduated cognitive onboarding for crew agents. Agents are admitted
post-naming-ceremony, walk through five phases under completion-criteria
gates (NOT timers), and only then earn Ward Room subscription + proactive
loop dispatch.

v1 ships one concrete construct (BirthChamber). Generalization into a
reusable Holodeck construct API is forcing-function deferred to AD-486e
(consumer: AD-510 Team Simulations).
"""

from probos.holodeck.affect import (
    AffectiveBaselineCheck,
    AffectiveObservation,
    NoOpAffectiveBaselineCheck,
)
from probos.holodeck.chamber import BirthChamber, BirthChamberRecord
from probos.holodeck.phases import HolodeckPhase
from probos.holodeck.scheduler import DepartmentActivationScheduler

__all__ = [
    "AffectiveBaselineCheck",
    "AffectiveObservation",
    "BirthChamber",
    "BirthChamberRecord",
    "DepartmentActivationScheduler",
    "HolodeckPhase",
    "NoOpAffectiveBaselineCheck",
]
