"""AD-618c: Built-in Bills + Loader tests."""

from __future__ import annotations

import logging
import textwrap
from pathlib import Path

import pytest

from probos.sop.loader import _BUILTIN_DIR, load_builtin_bills, load_custom_bills
from probos.sop.parser import parse_bill_file
from probos.sop.schema import BillDefinition, GatewayType, StepAction


# ── Built-in YAML Tests ────────────────────────────────────────────────


_GQ_PATH = _BUILTIN_DIR / "general_quarters.yaml"
_RC_PATH = _BUILTIN_DIR / "research_consultation.yaml"
_IR_PATH = _BUILTIN_DIR / "incident_response.yaml"
_DOB_PATH = _BUILTIN_DIR / "daily_operations_brief.yaml"


def test_general_quarters_parses():
    """Test 1: general_quarters.yaml parses without errors."""
    bill = parse_bill_file(_GQ_PATH)
    assert isinstance(bill, BillDefinition)
    assert bill.bill == "general_quarters"


def test_research_consultation_parses():
    """Test 2: research_consultation.yaml parses without errors."""
    bill = parse_bill_file(_RC_PATH)
    assert isinstance(bill, BillDefinition)
    assert bill.bill == "research_consultation"


def test_incident_response_parses():
    """Test 3: incident_response.yaml parses without errors."""
    bill = parse_bill_file(_IR_PATH)
    assert isinstance(bill, BillDefinition)
    assert bill.bill == "incident_response"


def test_daily_operations_brief_parses():
    """Test 4: daily_operations_brief.yaml parses without errors."""
    bill = parse_bill_file(_DOB_PATH)
    assert isinstance(bill, BillDefinition)
    assert bill.bill == "daily_operations_brief"


def test_general_quarters_roles():
    """Test 5: general_quarters has correct roles."""
    bill = parse_bill_file(_GQ_PATH)
    expected = {
        "commanding_officer", "first_officer",
        "engineering_chief", "security_chief", "science_chief",
        "medical_chief", "operations_chief",
    }
    assert set(bill.roles.keys()) == expected
    assert len(bill.roles) == 7


def test_general_quarters_step_count():
    """Test 6: general_quarters has 8 steps."""
    bill = parse_bill_file(_GQ_PATH)
    assert len(bill.steps) == 8


def test_incident_response_step_count():
    """Test 6b: incident_response has 8 steps."""
    bill = parse_bill_file(_IR_PATH)
    assert len(bill.steps) == 8
    step_ids = [s.id for s in bill.steps]
    assert step_ids == [
        "identify", "triage_decision",
        "contain_critical", "contain_standard",
        "root_cause", "remediate", "post_mortem", "crew_wellness",
    ]


def test_research_consultation_qualifications():
    """Test 7: research_consultation has qualification requirements."""
    bill = parse_bill_file(_RC_PATH)
    assert "data_analysis" in bill.roles["data_analyst"].qualifications
    assert "systems_analysis" in bill.roles["systems_analyst"].qualifications
    assert "research_methodology" in bill.roles["research_specialist"].qualifications


def test_incident_response_xor_gateway():
    """Test 8: incident_response has XOR gateway on triage_decision."""
    bill = parse_bill_file(_IR_PATH)
    triage = next(s for s in bill.steps if s.id == "triage_decision")
    assert triage.gateway_type == GatewayType.XOR_GATEWAY
    assert triage.branches == {
        "critical": "contain_critical",
        "major": "contain_standard",
        "minor": "contain_standard",
    }


def test_daily_operations_brief_schedule_trigger():
    """Test 9: daily_operations_brief has schedule trigger."""
    bill = parse_bill_file(_DOB_PATH)
    assert bill.activation.trigger.startswith("schedule:")


def test_all_builtin_bills_unique_slugs():
    """Test 10: All built-in bills have unique slugs."""
    bills = load_builtin_bills()
    slugs = list(bills.keys())
    assert len(slugs) == len(set(slugs))
    assert len(slugs) == 4


# ── Loader Tests ────────────────────────────────────────────────────────


def test_load_builtin_bills_returns_all_four():
    """Test 11: load_builtin_bills() returns all 4 bills keyed by slug."""
    bills = load_builtin_bills()
    assert len(bills) == 4
    assert set(bills.keys()) == {
        "general_quarters", "research_consultation",
        "incident_response", "daily_operations_brief",
    }
    for bill in bills.values():
        assert isinstance(bill, BillDefinition)


def test_load_builtin_bills_missing_directory(tmp_path, monkeypatch):
    """Test 12: load_builtin_bills() returns empty dict for missing dir."""
    monkeypatch.setattr("probos.sop.loader._BUILTIN_DIR", tmp_path / "nonexistent")
    bills = load_builtin_bills()
    assert bills == {}


def test_load_builtin_bills_skips_invalid_yaml(tmp_path, monkeypatch, caplog):
    """Test 13: load_builtin_bills() skips invalid YAML files."""
    # Write a valid file
    valid = tmp_path / "good.yaml"
    valid.write_text(textwrap.dedent("""\
        bill: good_bill
        version: 1
        title: Good Bill
        steps:
          - id: step1
            name: Step One
            action: cognitive_skill
    """))
    # Write an invalid file
    bad = tmp_path / "bad.yaml"
    bad.write_text("bill: [invalid yaml structure")

    monkeypatch.setattr("probos.sop.loader._BUILTIN_DIR", tmp_path)
    with caplog.at_level(logging.WARNING):
        bills = load_builtin_bills()

    assert "good_bill" in bills
    assert len(bills) == 1
    assert "Failed to load" in caplog.text


def test_load_custom_bills_from_temp_dir(tmp_path):
    """Test 14: load_custom_bills() loads from a temp directory."""
    yaml_file = tmp_path / "custom_bill.yaml"
    yaml_file.write_text(textwrap.dedent("""\
        bill: custom_drill
        version: 1
        title: Custom Drill
        steps:
          - id: step1
            name: Run Drill
            action: cognitive_skill
    """))

    bills = load_custom_bills(tmp_path)
    assert "custom_drill" in bills
    assert bills["custom_drill"].title == "Custom Drill"


def test_load_custom_bills_skips_duplicate_slugs(tmp_path, caplog):
    """Test 15: load_custom_bills() skips duplicate slugs (first wins)."""
    file_a = tmp_path / "a_drill.yaml"
    file_a.write_text(textwrap.dedent("""\
        bill: same_slug
        version: 1
        title: First
        steps:
          - id: s1
            name: S1
            action: cognitive_skill
    """))
    file_b = tmp_path / "b_drill.yaml"
    file_b.write_text(textwrap.dedent("""\
        bill: same_slug
        version: 2
        title: Second
        steps:
          - id: s1
            name: S1
            action: cognitive_skill
    """))

    with caplog.at_level(logging.WARNING):
        bills = load_custom_bills(tmp_path)

    assert len(bills) == 1
    assert bills["same_slug"].title == "First"  # First wins (sorted: a_ before b_)
    assert "Duplicate custom bill slug" in caplog.text


def test_load_custom_bills_missing_directory():
    """Test 16: load_custom_bills() returns empty for missing directory."""
    bills = load_custom_bills("/nonexistent/path/bills")
    assert bills == {}


# ── Schema Validation Tests (via parser) ────────────────────────────────


def test_all_builtin_bills_role_references():
    """Test 17: All built-in bills pass role reference validation."""
    bills = load_builtin_bills()
    for slug, bill in bills.items():
        for step in bill.steps:
            if step.role:
                assert step.role in bill.roles, (
                    f"Bill '{slug}' step '{step.id}' references unknown role '{step.role}'"
                )


def test_all_builtin_bills_branch_targets():
    """Test 18: All built-in bills pass branch target validation."""
    bills = load_builtin_bills()
    for slug, bill in bills.items():
        step_ids = {s.id for s in bill.steps}
        for step in bill.steps:
            for branch_value, target_id in step.branches.items():
                assert target_id in step_ids, (
                    f"Bill '{slug}' step '{step.id}' branch '{branch_value}' "
                    f"targets unknown step '{target_id}'"
                )


def test_all_builtin_bills_have_expected_results():
    """Test 19: All built-in bills have non-empty expected_results."""
    bills = load_builtin_bills()
    for slug, bill in bills.items():
        assert len(bill.expected_results) > 0, (
            f"Bill '{slug}' has no expected_results"
        )


def test_all_builtin_bills_valid_action_types():
    """Test 20: All built-in bills have valid action types."""
    valid_actions = {a.value for a in StepAction}
    bills = load_builtin_bills()
    for slug, bill in bills.items():
        for step in bill.steps:
            if step.action:
                assert step.action in valid_actions, (
                    f"Bill '{slug}' step '{step.id}' has invalid action '{step.action}'"
                )


def test_incident_response_root_cause_dual_inputs():
    """Test 21: root_cause accepts inputs from both XOR branches."""
    bill = parse_bill_file(_IR_PATH)
    root_cause = next(s for s in bill.steps if s.id == "root_cause")
    input_sources = {inp.source for inp in root_cause.inputs}
    assert "step:contain_critical.containment_status" in input_sources
    assert "step:contain_standard.containment_status" in input_sources


def test_research_consultation_requester_wiring():
    """Test 22: receive_request step uses role: requester."""
    bill = parse_bill_file(_RC_PATH)
    receive = next(s for s in bill.steps if s.id == "receive_request")
    assert receive.role == "requester"
    assert receive.role != "data_analyst"


def test_custom_bill_shadowing_builtin(tmp_path):
    """Test 23: Custom bill can shadow builtin — merge gives custom precedence."""
    custom_gq = tmp_path / "general_quarters.yaml"
    custom_gq.write_text(textwrap.dedent("""\
        bill: general_quarters
        version: 99
        title: Custom General Quarters
        steps:
          - id: step1
            name: Custom Step
            action: cognitive_skill
    """))

    builtins = load_builtin_bills()
    customs = load_custom_bills(tmp_path)

    # Custom overrides builtin when merged (custom takes precedence)
    merged = {**builtins, **customs}
    assert merged["general_quarters"].version == 99
    assert merged["general_quarters"].title == "Custom General Quarters"
