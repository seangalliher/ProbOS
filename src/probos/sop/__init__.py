"""Bill System — Declarative Multi-Agent Standard Operating Procedures (AD-618).

Bills are named, versioned, declarative multi-agent procedures with role-based
assignment, BPMN-vocabulary decision points, YAML format, and qualification
gates. Navy model: Bills (procedures), MRCs (atomic steps), WQSB (role
assignment matrix), Conditions (activation triggers).

Agents consult Bills with judgment — reference documents, not a process engine.
"""

from probos.sop.schema import (
    BillActivation,
    BillDefinition,
    BillRole,
    BillStep,
    GatewayType,
    StepAction,
    StepInput,
    StepOutput,
)
from probos.sop.parser import parse_bill, parse_bill_file, BillValidationError
from probos.sop.instance import (
    BillInstance,
    InstanceStatus,
    RoleAssignment,
    StepState,
    StepStatus,
)
from probos.sop.runtime import BillActivationError, BillRuntime
from probos.sop.loader import load_builtin_bills, load_custom_bills
from probos.sop.jit_bridge import (
    BillJITBridge,
    StepSkillMapping,
    DEFAULT_STEP_SKILL_MAPPINGS,
)

__all__ = [
    "BillActivation",
    "BillDefinition",
    "BillRole",
    "BillStep",
    "GatewayType",
    "StepAction",
    "StepInput",
    "StepOutput",
    "parse_bill",
    "parse_bill_file",
    "BillValidationError",
    "BillInstance",
    "InstanceStatus",
    "RoleAssignment",
    "StepState",
    "StepStatus",
    "BillActivationError",
    "BillRuntime",
    "load_builtin_bills",
    "load_custom_bills",
    "BillJITBridge",
    "StepSkillMapping",
    "DEFAULT_STEP_SKILL_MAPPINGS",
]
