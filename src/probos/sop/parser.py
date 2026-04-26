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

# Gateway types that require branches
_BRANCHING_GATEWAYS = {GatewayType.XOR_GATEWAY, GatewayType.OR_GATEWAY}


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
    has_roles_section = "roles" in data and isinstance(data["roles"], dict)
    if has_roles_section:
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

        # Validate role references — strict when roles section exists
        if role and has_roles_section and role not in roles:
            raise BillValidationError(
                f"{source}: step '{step_id}' references unknown role '{role}'"
            )
        for r in step_roles:
            if has_roles_section and r not in roles:
                raise BillValidationError(
                    f"{source}: step '{step_id}' references unknown role '{r}'"
                )

        # Parse branches and condition
        branches = step_data.get("branches", {}) or {}
        condition = step_data.get("condition", "")

        # Validate gateway-branches consistency
        if gateway_type in _BRANCHING_GATEWAYS and not branches:
            raise BillValidationError(
                f"{source}: step '{step_id}' is {gateway_type.value} but has no branches"
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
            condition=condition,
            branches=branches,
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

    # --- Validate condition references ---
    for step in steps:
        if step.condition and step.condition.startswith("step:"):
            # Format: "step:{step_id}.{output_name}"
            ref = step.condition[5:]  # strip "step:"
            ref_step_id = ref.split(".")[0] if "." in ref else ref
            if ref_step_id and ref_step_id not in step_id_set:
                raise BillValidationError(
                    f"{source}: step '{step.id}' condition references "
                    f"unknown step '{ref_step_id}'"
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
