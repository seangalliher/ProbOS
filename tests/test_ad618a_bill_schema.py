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

    def test_non_dict_yaml_root(self, tmp_path):
        """YAML root that isn't a mapping raises error via parse_bill_file."""
        bad_file = tmp_path / "list.bill.yaml"
        bad_file.write_text("- just a list\n", encoding="utf-8")
        with pytest.raises(BillValidationError, match="YAML root must be a mapping"):
            parse_bill_file(bad_file)

    def test_xor_gateway_without_branches(self):
        """XOR gateway step without branches raises BillValidationError."""
        data = _minimal_bill()
        data["steps"] = [{"id": "s1", "name": "S1", "type": "xor_gateway"}]
        with pytest.raises(BillValidationError, match="has no branches"):
            parse_bill(data)

    def test_or_gateway_without_branches(self):
        """OR gateway step without branches raises BillValidationError."""
        data = _minimal_bill()
        data["steps"] = [{"id": "s1", "name": "S1", "type": "or_gateway"}]
        with pytest.raises(BillValidationError, match="has no branches"):
            parse_bill(data)

    def test_condition_references_unknown_step(self):
        """Condition referencing non-existent step raises BillValidationError."""
        data = _minimal_bill()
        data["steps"] = [
            {"id": "s1", "name": "S1"},
            {
                "id": "gate",
                "name": "Gate",
                "type": "xor_gateway",
                "condition": "step:nonexistent.result",
                "branches": {"yes": "s1"},
            },
        ]
        with pytest.raises(BillValidationError, match="unknown step 'nonexistent'"):
            parse_bill(data)

    def test_role_reference_with_roles_section_missing(self):
        """Step with role ref when roles section is absent — no error (lenient)."""
        data = _minimal_bill()
        # No "roles" key → has_roles_section is False → no validation
        data["steps"] = [{"id": "s1", "name": "S1", "role": "anyone"}]
        bd = parse_bill(data)
        assert bd.steps[0].role == "anyone"


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
        with pytest.raises(yaml.YAMLError):
            parse_bill_file(bad_file)

    def test_write_read_round_trip(self, tmp_path):
        """Write a bill YAML, read it back with parse_bill_file — lossless.

        This is the critical integration test: verifies that the file format
        produced by write_bill() (raw YAML, no frontmatter wrapping) is
        parseable by parse_bill_file(). The original design used write_entry()
        which wraps in markdown frontmatter, corrupting the YAML.
        """
        bill_data = _full_bill()
        yaml_content = yaml.dump(bill_data, default_flow_style=False, sort_keys=False)

        # Simulate write_bill() — raw YAML, no frontmatter
        bill_file = tmp_path / "bills" / "research-consultation.bill.yaml"
        bill_file.parent.mkdir(parents=True, exist_ok=True)
        bill_file.write_text(yaml_content, encoding="utf-8")

        # Read it back
        bd = parse_bill_file(bill_file)
        assert bd.bill == "research-consultation"
        assert bd.version == 2
        assert len(bd.roles) == 2
        assert len(bd.steps) == 4
        assert bd.steps[2].gateway_type == GatewayType.XOR_GATEWAY

    def test_list_bills_finds_yaml_files(self, tmp_path):
        """Glob for *.bill.yaml finds bill files (not *.md).

        Verifies the list_bills() pattern finds .bill.yaml files.
        The original design used list_entries() which globs *.md only.
        """
        bills_dir = tmp_path / "bills"
        bills_dir.mkdir()
        (bills_dir / "alpha.bill.yaml").write_text(
            yaml.dump(_minimal_bill()), encoding="utf-8"
        )
        (bills_dir / "beta.bill.yaml").write_text(
            yaml.dump(_minimal_bill()), encoding="utf-8"
        )
        # A .md file should NOT appear
        (bills_dir / "notes.md").write_text("# Notes\n", encoding="utf-8")

        found = sorted(bills_dir.rglob("*.bill.yaml"))
        assert len(found) == 2
        names = [f.name for f in found]
        assert "alpha.bill.yaml" in names
        assert "beta.bill.yaml" in names


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

    def test_or_gateway(self):
        """OR gateway type parses with branches."""
        data = _minimal_bill()
        data["steps"] = [
            {"id": "s1", "name": "S1"},
            {
                "id": "gate",
                "name": "Gate",
                "type": "or_gateway",
                "branches": {"a": "s1"},
            },
        ]
        bd = parse_bill(data)
        assert bd.steps[1].gateway_type == GatewayType.OR_GATEWAY

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

    def test_condition_without_step_prefix_not_validated(self):
        """Conditions not starting with 'step:' are not validated."""
        data = _minimal_bill()
        data["steps"] = [
            {"id": "s1", "name": "S1"},
            {
                "id": "gate",
                "name": "Gate",
                "type": "xor_gateway",
                "condition": "external:some_signal",
                "branches": {"yes": "s1"},
            },
        ]
        bd = parse_bill(data)
        assert bd.steps[1].condition == "external:some_signal"

    def test_parallel_gateway_no_branches_ok(self):
        """Parallel (AND) gateway without branches is valid — not a decision point."""
        data = _minimal_bill()
        data["steps"] = [{"id": "s1", "name": "S1", "type": "parallel"}]
        bd = parse_bill(data)
        assert bd.steps[0].gateway_type == GatewayType.PARALLEL
