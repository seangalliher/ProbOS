"""AD-536: Procedure Criticality classification tests (8 tests).

Tests ProcedureCriticality enum and classify_criticality() function
from probos.cognitive.procedure_store.
"""

from __future__ import annotations

import pytest

from probos.cognitive.procedures import Procedure, ProcedureStep
from probos.cognitive.procedure_store import (
    ProcedureCriticality,
    classify_criticality,
)


def _make_step(step_number: int = 1, action: str = "do thing", agent_role: str = "") -> ProcedureStep:
    return ProcedureStep(step_number=step_number, action=action, agent_role=agent_role)


def _make_procedure(**kwargs) -> Procedure:
    defaults = dict(
        id="crit-test",
        name="test procedure",
        description="a test procedure",
        intent_types=["test"],
        steps=[_make_step()],
    )
    defaults.update(kwargs)
    return Procedure(**defaults)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestClassifyCriticality:
    """Tests for classify_criticality() rule cascade."""

    def test_security_role_in_step_returns_high(self):
        """Step with agent_role containing 'security' -> HIGH."""
        proc = _make_procedure(
            steps=[
                _make_step(1, "scan for threats", agent_role="security_analysis"),
                _make_step(2, "report findings"),
            ],
        )
        assert classify_criticality(proc) == ProcedureCriticality.HIGH

    def test_compound_multi_agent_returns_high(self):
        """Multiple distinct agent_roles (compound procedure) -> HIGH."""
        proc = _make_procedure(
            steps=[
                _make_step(1, "analyze code", agent_role="engineering"),
                _make_step(2, "review results", agent_role="science"),
            ],
        )
        assert classify_criticality(proc) == ProcedureCriticality.HIGH

    def test_destructive_keyword_in_intent_types_returns_critical(self):
        """Destructive keyword in intent_types -> CRITICAL (highest priority)."""
        proc = _make_procedure(
            intent_types=["delete_records"],
            steps=[_make_step()],
        )
        assert classify_criticality(proc) == ProcedureCriticality.CRITICAL

    def test_destructive_keyword_in_name_returns_critical(self):
        """Destructive keyword in procedure name -> CRITICAL."""
        proc = _make_procedure(
            name="force reset configuration",
            steps=[_make_step()],
        )
        assert classify_criticality(proc) == ProcedureCriticality.CRITICAL

    def test_simple_procedure_returns_low(self):
        """Simple procedure (1-5 steps, no special markers) -> LOW."""
        proc = _make_procedure(
            steps=[_make_step(i, f"step {i}") for i in range(1, 4)],
        )
        assert classify_criticality(proc) == ProcedureCriticality.LOW

    def test_many_steps_returns_medium(self):
        """Procedure with >5 steps -> MEDIUM."""
        proc = _make_procedure(
            steps=[_make_step(i, f"step {i}") for i in range(1, 8)],
        )
        assert classify_criticality(proc) == ProcedureCriticality.MEDIUM

    def test_empty_steps_returns_low(self):
        """Edge case: empty steps list -> LOW."""
        proc = _make_procedure(steps=[])
        assert classify_criticality(proc) == ProcedureCriticality.LOW

    def test_no_intent_pattern_returns_low(self):
        """Edge case: no intent types, generic name/description -> LOW."""
        proc = _make_procedure(
            intent_types=[],
            name="routine check",
            description="a routine operation",
            steps=[_make_step()],
        )
        assert classify_criticality(proc) == ProcedureCriticality.LOW
