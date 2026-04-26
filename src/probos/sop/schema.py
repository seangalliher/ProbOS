"""AD-618a: Bill Schema — dataclasses for declarative SOPs.

Defines the in-memory representation of a Bill YAML file. Based on the
BPMN vocabulary subset defined in docs/research/standard-operating-procedures.md.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class GatewayType(str, Enum):
    """BPMN gateway types for step branching."""
    SEQUENTIAL = "sequential"    # Default — steps execute in order
    PARALLEL = "parallel"        # AND gateway — all roles execute concurrently
    XOR_GATEWAY = "xor_gateway"  # Exclusive decision — one branch taken
    OR_GATEWAY = "or_gateway"    # Inclusive decision — one or more branches


class StepAction(str, Enum):
    """Action types for bill steps."""
    COGNITIVE_SKILL = "cognitive_skill"  # Execute a T2 SKILL.md
    TOOL = "tool"                        # Execute a T4 tool
    POST_TO_CHANNEL = "post_to_channel"  # Post to Ward Room channel
    SEND_DM = "send_dm"                  # Send a direct message
    RECEIVE_MESSAGE = "receive_message"  # Wait for input
    CAPTAIN_APPROVAL = "captain_approval"  # Captain approval gate
    SUB_BILL = "sub_bill"                # Execute another Bill as nested procedure


@dataclass
class StepInput:
    """Input parameter for a bill step."""
    name: str
    source: str  # "activation_data" | "step:{step_id}.{output_name}"


@dataclass
class StepOutput:
    """Output parameter from a bill step."""
    name: str
    type: str  # "text" | "document" | "enum" | "boolean"
    values: list[str] = field(default_factory=list)  # For enum type


@dataclass
class BillRole:
    """Role definition within a Bill — filled by qualified agents at runtime."""
    id: str
    qualifications: list[str] = field(default_factory=list)
    department: str = "any"  # "any" = cross-department
    min_rank: str = ""       # Minimum rank required (empty = no minimum)
    count: str = "1"         # "1" or "1-3" (flexible headcount)


@dataclass
class BillStep:
    """A single step in a Bill procedure."""
    id: str
    name: str
    role: str = ""           # Role ID (empty for gateway steps)
    roles: list[str] = field(default_factory=list)  # For parallel steps
    action: str = ""         # StepAction value (empty for gateway steps)
    skill: str = ""          # T2 skill reference (if action = cognitive_skill)
    tool: str = ""           # T4 tool reference (if action = tool)
    channel: str = ""        # Channel name (if action = post_to_channel)
    sub_bill: str = ""       # Bill reference (if action = sub_bill)
    inputs: list[StepInput] = field(default_factory=list)
    outputs: list[StepOutput] = field(default_factory=list)
    gate: str = ""           # Approval gate type (e.g. "captain_approval")
    timeout: int = 0         # Seconds (0 = no timeout)
    gateway_type: GatewayType = GatewayType.SEQUENTIAL
    condition: str = ""      # For gateway steps: "step:{id}.{output}"
    branches: dict[str, str] = field(default_factory=dict)  # For gateway steps


@dataclass
class BillActivation:
    """Activation trigger definition for a Bill."""
    trigger: str = "manual"  # "manual" | "alert:<condition>" | "schedule:<cron>" | "event:<type>"
    authority: str = "department_chief"  # Minimum rank to activate


@dataclass
class BillDefinition:
    """Complete Bill definition — a named, versioned, declarative SOP.

    Represents the full contents of a .bill.yaml file. Loaded by the parser,
    stored in Ship's Records, and consulted by agents during execution (AD-618b).
    """
    bill: str                            # Unique bill identifier (slug)
    version: int = 1
    title: str = ""
    description: str = ""
    author: str = ""                     # Who authored this bill
    activation: BillActivation = field(default_factory=BillActivation)
    roles: dict[str, BillRole] = field(default_factory=dict)
    steps: list[BillStep] = field(default_factory=list)
    expected_results: list[str] = field(default_factory=list)
    standing_order_constraints: list[str] = field(default_factory=list)
