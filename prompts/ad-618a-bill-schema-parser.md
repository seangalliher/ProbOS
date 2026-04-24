# AD-618a: Bill Schema + Parser

**Issue:** #204 (AD-618 umbrella)
**Status:** Ready for builder
**Priority:** Medium
**Depends:** AD-434 (Ship's Records — complete)
**Files:** `src/probos/sop/__init__.py` (NEW), `src/probos/sop/schema.py` (NEW), `src/probos/sop/parser.py` (NEW), `src/probos/knowledge/records_store.py` (EDIT), `tests/test_ad618a_bill_schema.py` (NEW)

## Problem

ProbOS has Standing Orders (T1, behavioral policy) and Cognitive JIT (T3, learned procedures), but no declarative layer for **multi-agent standard operating procedures** — named, versioned procedures that define how multiple agents coordinate to accomplish a complex objective with explicit roles, steps, decision points, and hand-offs.

The research document (`docs/research/standard-operating-procedures.md`) defines the full Bill System design. AD-618a delivers the foundation: YAML schema definition, dataclasses, parser, and Ship's Records integration. No runtime execution (AD-618b), no built-in bills (AD-618c).

**Navy model:** Bills are named multi-person procedures with role-based assignments, condition-activated triggers, and drillable steps. The Watch, Quarter, and Station Bill (WQSB) assigns every sailor to a station in every bill. ProbOS's runtime WQSB (AD-618b) will compute assignments from live agent state.

## Design

AD-618a delivers three things:

1. **Schema dataclasses** — `BillDefinition`, `BillStep`, `BillRole`, `BillActivation` — the in-memory representation of a Bill YAML file.
2. **Parser** — Load a YAML file, validate against the schema, return a `BillDefinition`. Error reporting with line context.
3. **Ship's Records integration** — Add `bills` subdirectory to RecordsStore. Add `write_bill()` and `list_bills()` convenience methods.

**What this does NOT include:**
- Bill Instance / runtime execution (AD-618b)
- Role assignment engine / WQSB (AD-618b)
- Built-in bill YAML files (AD-618c)
- HXI dashboard (AD-618d)
- Cognitive JIT bridge (AD-618e)
- Events (no BILL_CREATED event — deferred to AD-618b when bills actually run)

---

## Section 1: Create `src/probos/sop/` package

**File:** `src/probos/sop/__init__.py` (NEW)

```python
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
]
```

---

## Section 2: Bill Schema dataclasses

**File:** `src/probos/sop/schema.py` (NEW)

```python
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
```

---

## Section 3: Bill Parser

**File:** `src/probos/sop/parser.py` (NEW)

```python
"""AD-618a: Bill YAML parser — loads and validates Bill definitions.

Parses .bill.yaml files into BillDefinition dataclasses with schema validation.
Error reporting includes field context for debugging.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml

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

logger = logging.getLogger(__name__)

# Valid action strings (StepAction values)
_VALID_ACTIONS = {a.value for a in StepAction}

# Valid gateway types
_VALID_GATEWAYS = {g.value for g in GatewayType}


class BillValidationError(ValueError):
    """Raised when a Bill YAML file fails schema validation."""
    pass


def parse_bill(data: dict[str, Any], *, source: str = "<dict>") -> BillDefinition:
    """Parse a dict (from YAML) into a validated BillDefinition.

    Args:
        data: Parsed YAML dict.
        source: File path or identifier for error messages.

    Returns:
        Validated BillDefinition.

    Raises:
        BillValidationError: If the data fails schema validation.
    """
    # --- Required field ---
    bill_id = data.get("bill")
    if not bill_id or not isinstance(bill_id, str):
        raise BillValidationError(f"{source}: 'bill' field is required and must be a string")

    # --- Activation ---
    activation = BillActivation()
    if "activation" in data and isinstance(data["activation"], dict):
        act_data = data["activation"]
        activation = BillActivation(
            trigger=act_data.get("trigger", "manual"),
            authority=act_data.get("authority", "department_chief"),
        )

    # --- Roles ---
    roles: dict[str, BillRole] = {}
    if "roles" in data and isinstance(data["roles"], dict):
        for role_id, role_data in data["roles"].items():
            if not isinstance(role_data, dict):
                raise BillValidationError(
                    f"{source}: role '{role_id}' must be a mapping"
                )
            roles[role_id] = BillRole(
                id=role_id,
                qualifications=role_data.get("qualifications", []) or [],
                department=role_data.get("department", "any"),
                min_rank=role_data.get("min_rank", ""),
                count=str(role_data.get("count", "1")),
            )

    # --- Steps ---
    steps: list[BillStep] = []
    raw_steps = data.get("steps", [])
    if not isinstance(raw_steps, list):
        raise BillValidationError(f"{source}: 'steps' must be a list")

    for i, step_data in enumerate(raw_steps):
        if not isinstance(step_data, dict):
            raise BillValidationError(f"{source}: step {i} must be a mapping")

        step_id = step_data.get("id")
        if not step_id:
            raise BillValidationError(f"{source}: step {i} missing 'id'")

        step_name = step_data.get("name", step_id)

        # Parse gateway type
        raw_type = step_data.get("type", "sequential")
        if raw_type not in _VALID_GATEWAYS:
            raise BillValidationError(
                f"{source}: step '{step_id}' has invalid type '{raw_type}'. "
                f"Valid types: {', '.join(sorted(_VALID_GATEWAYS))}"
            )
        gateway_type = GatewayType(raw_type)

        # Parse action (not required for gateway steps)
        action = step_data.get("action", "")
        if action and action not in _VALID_ACTIONS:
            raise BillValidationError(
                f"{source}: step '{step_id}' has invalid action '{action}'. "
                f"Valid actions: {', '.join(sorted(_VALID_ACTIONS))}"
            )

        # Parse inputs
        inputs: list[StepInput] = []
        for inp in step_data.get("inputs", []) or []:
            if isinstance(inp, dict):
                inputs.append(StepInput(
                    name=inp.get("name", ""),
                    source=inp.get("source", ""),
                ))

        # Parse outputs
        outputs: list[StepOutput] = []
        for out in step_data.get("outputs", []) or []:
            if isinstance(out, dict):
                outputs.append(StepOutput(
                    name=out.get("name", ""),
                    type=out.get("type", "text"),
                    values=out.get("values", []) or [],
                ))

        # Parse role(s)
        role = step_data.get("role", "")
        step_roles = step_data.get("roles", []) or []

        # Validate role references
        if role and roles and role not in roles:
            raise BillValidationError(
                f"{source}: step '{step_id}' references unknown role '{role}'"
            )
        for r in step_roles:
            if roles and r not in roles:
                raise BillValidationError(
                    f"{source}: step '{step_id}' references unknown role '{r}'"
                )

        steps.append(BillStep(
            id=step_id,
            name=step_name,
            role=role,
            roles=step_roles,
            action=action,
            skill=step_data.get("skill", ""),
            tool=step_data.get("tool", ""),
            channel=step_data.get("channel", ""),
            sub_bill=step_data.get("sub_bill", ""),
            inputs=inputs,
            outputs=outputs,
            gate=step_data.get("gate", ""),
            timeout=step_data.get("timeout", 0) or 0,
            gateway_type=gateway_type,
            condition=step_data.get("condition", ""),
            branches=step_data.get("branches", {}) or {},
        ))

    # --- Validate step ID uniqueness ---
    step_ids = [s.id for s in steps]
    if len(step_ids) != len(set(step_ids)):
        dupes = [sid for sid in step_ids if step_ids.count(sid) > 1]
        raise BillValidationError(
            f"{source}: duplicate step IDs: {', '.join(set(dupes))}"
        )

    # --- Validate branch targets ---
    step_id_set = set(step_ids)
    for step in steps:
        for target in step.branches.values():
            if target not in step_id_set:
                raise BillValidationError(
                    f"{source}: step '{step.id}' branch target '{target}' "
                    f"does not match any step ID"
                )

    # --- Build BillDefinition ---
    return BillDefinition(
        bill=bill_id,
        version=data.get("version", 1),
        title=data.get("title", ""),
        description=data.get("description", ""),
        author=data.get("author", ""),
        activation=activation,
        roles=roles,
        steps=steps,
        expected_results=data.get("expected_results", []) or [],
        standing_order_constraints=data.get("standing_order_constraints", []) or [],
    )


def parse_bill_file(path: str | Path) -> BillDefinition:
    """Load and parse a Bill YAML file.

    Args:
        path: Path to a .bill.yaml file.

    Returns:
        Validated BillDefinition.

    Raises:
        BillValidationError: If the file fails schema validation.
        FileNotFoundError: If the file doesn't exist.
        yaml.YAMLError: If the file isn't valid YAML.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Bill file not found: {path}")

    raw = path.read_text(encoding="utf-8")
    data = yaml.safe_load(raw)

    if not isinstance(data, dict):
        raise BillValidationError(f"{path}: YAML root must be a mapping")

    return parse_bill(data, source=str(path))
```

---

## Section 4: Ship's Records integration

**File:** `src/probos/knowledge/records_store.py`

### 4a: Add `"bills"` to `_SUBDIRS`

Current (line 15–23):
```python
_SUBDIRS = (
    "captains-log",
    "notebooks",
    "reports",
    "duty-logs",
    "operations",
    "manuals",
    "_archived",
)
```

Change to:
```python
_SUBDIRS = (
    "bills",        # AD-618a: Standard Operating Procedures
    "captains-log",
    "notebooks",
    "reports",
    "duty-logs",
    "operations",
    "manuals",
    "_archived",
)
```

### 4b: Add `write_bill()` method

Add after the `write_notebook()` method (search for `async def write_notebook` and add after that method ends):

```python
    async def write_bill(
        self,
        bill_id: str,
        content: str,
        author: str = "captain",
        *,
        version: int = 1,
    ) -> str:
        """Write a Bill YAML file to Ship's Records (AD-618a).

        Args:
            bill_id: Unique bill identifier (slug, e.g. "research-consultation").
            content: Full YAML content of the bill.
            author: Who authored this bill.
            version: Bill version number.

        Returns:
            Relative path of the created file.
        """
        filename = f"{bill_id}.bill.yaml"
        path = f"bills/{filename}"

        return await self.write_entry(
            author=author,
            path=path,
            content=content,
            message=f"[bill] {bill_id} v{version} — authored by {author}",
            classification="ship",
            status="active",
            topic="sop",
            tags=["bill", "sop", bill_id],
        )
```

### 4c: Add `list_bills()` method

Add after `write_bill()`:

```python
    async def list_bills(self) -> list[dict]:
        """List all Bill files in Ship's Records (AD-618a).

        Returns:
            List of dicts with 'path', 'frontmatter' keys for each bill.
        """
        return await self.list_entries("bills")
```

---

## Section 5: Tests

**File:** `tests/test_ad618a_bill_schema.py` (NEW)

```python
"""Tests for AD-618a: Bill Schema + Parser."""

from __future__ import annotations

import pytest
import tempfile
from pathlib import Path

import yaml

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


# --- Fixtures ---

def _minimal_bill() -> dict:
    """Minimal valid bill YAML data."""
    return {
        "bill": "test-bill",
        "version": 1,
        "title": "Test Bill",
        "steps": [],
    }


def _full_bill() -> dict:
    """Full bill with roles, steps, gateways."""
    return {
        "bill": "research-consultation",
        "version": 2,
        "title": "Research Consultation",
        "description": "Multi-department research producing a report",
        "author": "captain",
        "activation": {
            "trigger": "manual",
            "authority": "department_chief",
        },
        "roles": {
            "lead_researcher": {
                "qualifications": ["research", "analysis"],
                "department": "science",
                "min_rank": "lieutenant",
            },
            "reviewer": {
                "qualifications": ["peer_review"],
                "department": "any",
                "count": "1-3",
            },
        },
        "steps": [
            {
                "id": "receive_request",
                "name": "Receive Research Request",
                "role": "lead_researcher",
                "action": "receive_message",
                "inputs": [{"name": "topic", "source": "activation_data"}],
                "outputs": [{"name": "research_question", "type": "text"}],
            },
            {
                "id": "parallel_research",
                "name": "Parallel Research",
                "type": "parallel",
                "roles": ["lead_researcher", "reviewer"],
                "action": "cognitive_skill",
                "skill": "deep-research",
                "timeout": 3600,
            },
            {
                "id": "review_decision",
                "name": "Review Decision",
                "type": "xor_gateway",
                "condition": "step:parallel_research.verdict",
                "branches": {
                    "approved": "deliver",
                    "revision_needed": "parallel_research",
                },
            },
            {
                "id": "deliver",
                "name": "Deliver Report",
                "role": "lead_researcher",
                "action": "post_to_channel",
                "channel": "bridge",
            },
        ],
        "expected_results": [
            "Research report posted to bridge channel",
        ],
        "standing_order_constraints": [
            "Classification restrictions per AD-339 apply",
        ],
    }


# --- Schema dataclass tests ---

class TestSchemaDataclasses:

    def test_bill_definition_defaults(self):
        """BillDefinition has sane defaults."""
        bd = BillDefinition(bill="test")
        assert bd.bill == "test"
        assert bd.version == 1
        assert bd.roles == {}
        assert bd.steps == []
        assert bd.activation.trigger == "manual"

    def test_bill_role_defaults(self):
        """BillRole defaults."""
        role = BillRole(id="test_role")
        assert role.qualifications == []
        assert role.department == "any"
        assert role.count == "1"

    def test_bill_step_defaults(self):
        """BillStep defaults."""
        step = BillStep(id="step1", name="Step 1")
        assert step.gateway_type == GatewayType.SEQUENTIAL
        assert step.inputs == []
        assert step.outputs == []
        assert step.timeout == 0

    def test_gateway_type_enum(self):
        """GatewayType enum values."""
        assert GatewayType.PARALLEL.value == "parallel"
        assert GatewayType.XOR_GATEWAY.value == "xor_gateway"
        assert GatewayType.OR_GATEWAY.value == "or_gateway"

    def test_step_action_enum(self):
        """StepAction enum values."""
        assert StepAction.COGNITIVE_SKILL.value == "cognitive_skill"
        assert StepAction.SUB_BILL.value == "sub_bill"
        assert StepAction.CAPTAIN_APPROVAL.value == "captain_approval"

    def test_step_input_output(self):
        """StepInput and StepOutput construction."""
        inp = StepInput(name="topic", source="activation_data")
        assert inp.name == "topic"
        out = StepOutput(name="result", type="enum", values=["yes", "no"])
        assert out.values == ["yes", "no"]


# --- Parser: valid inputs ---

class TestParserValid:

    def test_minimal_bill(self):
        """Minimal bill parses successfully."""
        bd = parse_bill(_minimal_bill())
        assert bd.bill == "test-bill"
        assert bd.version == 1
        assert bd.steps == []

    def test_full_bill(self):
        """Full bill with roles, steps, gateways parses correctly."""
        bd = parse_bill(_full_bill())
        assert bd.bill == "research-consultation"
        assert bd.version == 2
        assert len(bd.roles) == 2
        assert "lead_researcher" in bd.roles
        assert bd.roles["lead_researcher"].department == "science"
        assert len(bd.steps) == 4

    def test_step_parsing(self):
        """Steps parse with correct fields."""
        bd = parse_bill(_full_bill())
        step = bd.steps[0]
        assert step.id == "receive_request"
        assert step.role == "lead_researcher"
        assert step.action == "receive_message"
        assert len(step.inputs) == 1
        assert step.inputs[0].source == "activation_data"

    def test_parallel_step(self):
        """Parallel (AND gateway) step parses."""
        bd = parse_bill(_full_bill())
        step = bd.steps[1]
        assert step.gateway_type == GatewayType.PARALLEL
        assert step.roles == ["lead_researcher", "reviewer"]
        assert step.skill == "deep-research"
        assert step.timeout == 3600

    def test_xor_gateway(self):
        """XOR gateway step parses with branches."""
        bd = parse_bill(_full_bill())
        step = bd.steps[2]
        assert step.gateway_type == GatewayType.XOR_GATEWAY
        assert step.branches["approved"] == "deliver"
        assert step.branches["revision_needed"] == "parallel_research"

    def test_activation(self):
        """Activation block parses."""
        bd = parse_bill(_full_bill())
        assert bd.activation.trigger == "manual"
        assert bd.activation.authority == "department_chief"

    def test_expected_results(self):
        """Expected results list parses."""
        bd = parse_bill(_full_bill())
        assert len(bd.expected_results) == 1
        assert "bridge channel" in bd.expected_results[0]

    def test_standing_order_constraints(self):
        """Standing order constraints parse."""
        bd = parse_bill(_full_bill())
        assert len(bd.standing_order_constraints) == 1

    def test_role_qualifications(self):
        """Role qualifications parse as lists."""
        bd = parse_bill(_full_bill())
        role = bd.roles["lead_researcher"]
        assert role.qualifications == ["research", "analysis"]
        assert role.min_rank == "lieutenant"

    def test_role_flexible_count(self):
        """Role count parses as string (supports ranges)."""
        bd = parse_bill(_full_bill())
        assert bd.roles["reviewer"].count == "1-3"

    def test_no_roles_section(self):
        """Bill without roles section is valid."""
        data = _minimal_bill()
        # No "roles" key at all
        bd = parse_bill(data)
        assert bd.roles == {}

    def test_no_activation(self):
        """Bill without activation uses defaults."""
        data = _minimal_bill()
        bd = parse_bill(data)
        assert bd.activation.trigger == "manual"


# --- Parser: invalid inputs ---

class TestParserInvalid:

    def test_missing_bill_id(self):
        """Missing 'bill' field raises BillValidationError."""
        with pytest.raises(BillValidationError, match="'bill' field is required"):
            parse_bill({"title": "No ID"})

    def test_empty_bill_id(self):
        """Empty 'bill' field raises BillValidationError."""
        with pytest.raises(BillValidationError, match="'bill' field is required"):
            parse_bill({"bill": ""})

    def test_invalid_step_type(self):
        """Invalid gateway type raises BillValidationError."""
        data = _minimal_bill()
        data["steps"] = [{"id": "s1", "name": "S1", "type": "invalid"}]
        with pytest.raises(BillValidationError, match="invalid type 'invalid'"):
            parse_bill(data)

    def test_invalid_action(self):
        """Invalid action raises BillValidationError."""
        data = _minimal_bill()
        data["steps"] = [{"id": "s1", "name": "S1", "action": "teleport"}]
        with pytest.raises(BillValidationError, match="invalid action 'teleport'"):
            parse_bill(data)

    def test_duplicate_step_ids(self):
        """Duplicate step IDs raise BillValidationError."""
        data = _minimal_bill()
        data["steps"] = [
            {"id": "s1", "name": "Step 1"},
            {"id": "s1", "name": "Step 1 again"},
        ]
        with pytest.raises(BillValidationError, match="duplicate step IDs"):
            parse_bill(data)

    def test_unknown_role_reference(self):
        """Step referencing unknown role raises BillValidationError."""
        data = _minimal_bill()
        data["roles"] = {"engineer": {"qualifications": []}}
        data["steps"] = [{"id": "s1", "name": "S1", "role": "pilot"}]
        with pytest.raises(BillValidationError, match="unknown role 'pilot'"):
            parse_bill(data)

    def test_unknown_branch_target(self):
        """Gateway branch targeting non-existent step raises error."""
        data = _minimal_bill()
        data["steps"] = [
            {
                "id": "gate",
                "name": "Gate",
                "type": "xor_gateway",
                "branches": {"yes": "nonexistent"},
            },
        ]
        with pytest.raises(BillValidationError, match="branch target 'nonexistent'"):
            parse_bill(data)

    def test_steps_not_list(self):
        """Steps as non-list raises BillValidationError."""
        data = _minimal_bill()
        data["steps"] = "not a list"
        with pytest.raises(BillValidationError, match="'steps' must be a list"):
            parse_bill(data)

    def test_step_missing_id(self):
        """Step without 'id' raises BillValidationError."""
        data = _minimal_bill()
        data["steps"] = [{"name": "No ID"}]
        with pytest.raises(BillValidationError, match="missing 'id'"):
            parse_bill(data)

    def test_role_not_mapping(self):
        """Role as non-dict raises BillValidationError."""
        data = _minimal_bill()
        data["roles"] = {"bad_role": "not a dict"}
        with pytest.raises(BillValidationError, match="must be a mapping"):
            parse_bill(data)

    def test_non_dict_yaml_root(self):
        """YAML root that isn't a mapping raises error."""
        with pytest.raises(BillValidationError, match="must be a mapping"):
            parse_bill_file_from_string("- just a list")


# --- File-based parsing ---

class TestParseFile:

    def test_parse_valid_yaml_file(self, tmp_path):
        """parse_bill_file loads and parses a YAML file."""
        bill_file = tmp_path / "test.bill.yaml"
        bill_file.write_text(yaml.dump(_minimal_bill()), encoding="utf-8")

        bd = parse_bill_file(bill_file)
        assert bd.bill == "test-bill"

    def test_parse_full_yaml_file(self, tmp_path):
        """parse_bill_file handles complex bills."""
        bill_file = tmp_path / "full.bill.yaml"
        bill_file.write_text(yaml.dump(_full_bill()), encoding="utf-8")

        bd = parse_bill_file(bill_file)
        assert bd.bill == "research-consultation"
        assert len(bd.steps) == 4

    def test_file_not_found(self):
        """parse_bill_file raises FileNotFoundError."""
        with pytest.raises(FileNotFoundError):
            parse_bill_file("/nonexistent/path.yaml")

    def test_invalid_yaml(self, tmp_path):
        """parse_bill_file raises on invalid YAML."""
        bad_file = tmp_path / "bad.yaml"
        bad_file.write_text(":\n  invalid: [yaml\n", encoding="utf-8")
        with pytest.raises(Exception):  # yaml.YAMLError
            parse_bill_file(bad_file)


# --- Edge cases ---

class TestEdgeCases:

    def test_empty_qualifications(self):
        """Null qualifications treated as empty list."""
        data = _minimal_bill()
        data["roles"] = {"r1": {"qualifications": None}}
        bd = parse_bill(data)
        assert bd.roles["r1"].qualifications == []

    def test_empty_inputs_outputs(self):
        """Null inputs/outputs treated as empty lists."""
        data = _minimal_bill()
        data["steps"] = [{
            "id": "s1",
            "name": "S1",
            "inputs": None,
            "outputs": None,
        }]
        bd = parse_bill(data)
        assert bd.steps[0].inputs == []
        assert bd.steps[0].outputs == []

    def test_count_as_integer(self):
        """Integer count is coerced to string."""
        data = _minimal_bill()
        data["roles"] = {"r1": {"count": 2}}
        bd = parse_bill(data)
        assert bd.roles["r1"].count == "2"

    def test_step_without_role_no_roles_defined(self):
        """Steps without role reference are valid when no roles defined."""
        data = _minimal_bill()
        data["steps"] = [{"id": "s1", "name": "S1", "role": "anyone"}]
        # No "roles" key → no validation
        bd = parse_bill(data)
        assert bd.steps[0].role == "anyone"

    def test_or_gateway(self):
        """OR gateway type parses."""
        data = _minimal_bill()
        data["steps"] = [{"id": "s1", "name": "S1", "type": "or_gateway"}]
        bd = parse_bill(data)
        assert bd.steps[0].gateway_type == GatewayType.OR_GATEWAY

    def test_sub_bill_action(self):
        """sub_bill action and reference parse."""
        data = _minimal_bill()
        data["steps"] = [{
            "id": "s1",
            "name": "S1",
            "action": "sub_bill",
            "sub_bill": "incident-response",
        }]
        bd = parse_bill(data)
        assert bd.steps[0].action == "sub_bill"
        assert bd.steps[0].sub_bill == "incident-response"


# Helper for string-based YAML parsing tests
def parse_bill_file_from_string(yaml_string: str):
    """Parse YAML from string for testing."""
    data = yaml.safe_load(yaml_string)
    if not isinstance(data, dict):
        raise BillValidationError("YAML root must be a mapping")
    return parse_bill(data)
```

---

## Verification

```bash
# Targeted tests
d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad618a_bill_schema.py -v

# Full suite
d:/ProbOS/.venv/Scripts/pytest.exe tests/ -x -q
```

**Existing test impact:** No existing tests should be affected. This is purely additive — new package `src/probos/sop/`, new test file, and two new methods + one constant change in `records_store.py`. The `_SUBDIRS` change only adds a new directory at initialization time.

---

## Tracking

### PROGRESS.md
Add line:
```
AD-618a CLOSED. Bill Schema + Parser — BillDefinition/BillStep/BillRole/BillActivation dataclasses with GatewayType (sequential/parallel/XOR/OR) and StepAction enums. YAML parser with schema validation (role references, branch targets, step ID uniqueness, action types). Ship's Records gains `bills/` subdirectory, `write_bill()`, and `list_bills()`. New `src/probos/sop/` package. 30 new tests. Foundation for AD-618b (runtime) and AD-618c (built-in bills).
```

### DECISIONS.md
Add entry:
```
**AD-618a: Bill Schema foundation — YAML-first, BPMN-vocabulary, no execution engine.** Bills are declarative YAML files parsed into BillDefinition dataclasses. Schema uses BPMN vocabulary (XOR/AND/OR gateways, parallel lanes, sub-processes) for multi-agent SOP definition. Parser validates role references, branch targets, step ID uniqueness, and action types. Bills are stored in Ship's Records (`bills/` subdirectory). Design principle: "Reference, not engine" — agents consult Bills with judgment, they are not puppeted by a state machine. No Bill events or runtime execution in AD-618a — those come in AD-618b.
```

### docs/development/roadmap.md
Update AD-618a status from `planned` to `complete` in the sub-AD list.
