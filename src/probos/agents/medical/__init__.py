"""Medical team pool — specialized agents for ProbOS self-health (AD-290)."""

from probos.agents.medical.vitals_monitor import VitalsMonitorAgent
from probos.agents.medical.diagnostician import DiagnosticianAgent
from probos.agents.medical.surgeon import SurgeonAgent
from probos.agents.medical.pharmacist import PharmacistAgent
from probos.agents.medical.pathologist import PathologistAgent

__all__ = [
    "VitalsMonitorAgent",
    "DiagnosticianAgent",
    "SurgeonAgent",
    "PharmacistAgent",
    "PathologistAgent",
]
