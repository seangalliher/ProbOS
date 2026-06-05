"""Tests for AD-872 forge observability.

Covers the three pure units in ``probos.cognitive.forge_observability``
(``validate_forge_shape``, ``classify_forge_rejection``, ``ForgeStatsAggregator``)
plus the read-only honest-degrade wiring into ``SelfModificationPipeline``.

Uses REAL ``DesignedAgentRecord`` fixtures (no MagicMock at the substrate
boundary, per BF-287).
"""

from __future__ import annotations

import time
from unittest.mock import AsyncMock

import pytest

from probos.cognitive.forge_observability import (
    ForgeStatsAggregator,
    REJECTION_BUCKETS,
    classify_forge_rejection,
    validate_forge_shape,
)
from probos.cognitive.self_mod import DesignedAgentRecord


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _rec(intent_name: str, status: str, error: str = "") -> DesignedAgentRecord:
    """Build a real DesignedAgentRecord for aggregation/classification tests."""
    return DesignedAgentRecord(
        intent_name=intent_name,
        agent_type=intent_name,
        class_name="",
        source_code="",
        created_at=time.monotonic(),
        status=status,
        error=error,
    )


def _make_pipeline(**overrides):
    """Build a real SelfModificationPipeline with async stub callables."""
    from probos.cognitive.agent_designer import AgentDesigner
    from probos.cognitive.behavioral_monitor import BehavioralMonitor
    from probos.cognitive.code_validator import CodeValidator
    from probos.cognitive.llm_client import MockLLMClient
    from probos.cognitive.sandbox import SandboxRunner
    from probos.cognitive.self_mod import SelfModificationPipeline
    from probos.config import SelfModConfig

    config = overrides.get(
        "config",
        SelfModConfig(enabled=True, require_user_approval=False, sandbox_timeout_seconds=5.0),
    )
    designer = AgentDesigner(MockLLMClient(), config)

    async def noop(*a, **k):
        return None

    return SelfModificationPipeline(
        designer=designer,
        validator=CodeValidator(config),
        sandbox=SandboxRunner(config),
        monitor=BehavioralMonitor(),
        config=config,
        register_fn=overrides.get("register_fn", noop),
        create_pool_fn=overrides.get("create_pool_fn", noop),
        set_trust_fn=overrides.get("set_trust_fn", noop),
    )


# ---------------------------------------------------------------------------
# validate_forge_shape
# ---------------------------------------------------------------------------


class TestValidateForgeShape:
    def test_passes_well_formed_request(self):
        errors = validate_forge_shape("count_words", "Count words in text", {"text": "hi"})
        assert errors == []

    def test_accepts_empty_dict_parameters(self):
        # Empty {} is a valid no-parameter intent and must NOT be rejected.
        errors = validate_forge_shape("ping", "A ping intent", {})
        assert errors == []

    def test_rejects_empty_name(self):
        errors = validate_forge_shape("", "A description", {})
        assert any("Empty intent name" in e for e in errors)

    def test_rejects_whitespace_only_name(self):
        errors = validate_forge_shape("   ", "A description", {})
        assert any("Empty intent name" in e for e in errors)

    def test_rejects_degenerate_short_name(self):
        errors = validate_forge_shape("x", "A description", {})
        assert any("Degenerate" in e for e in errors)

    def test_rejects_non_alphanumeric_name(self):
        errors = validate_forge_shape("!!", "A description", {})
        assert any("no alphanumeric" in e for e in errors)

    def test_rejects_empty_description(self):
        errors = validate_forge_shape("count_words", "", {})
        assert any("Empty intent description" in e for e in errors)

    def test_rejects_none_parameters(self):
        errors = validate_forge_shape("count_words", "Count words", None)
        assert any("Parameters missing" in e for e in errors)

    def test_rejects_empty_parameter_key(self):
        errors = validate_forge_shape("count_words", "Count words", {"": "v"})
        assert any("empty key" in e for e in errors)


# ---------------------------------------------------------------------------
# classify_forge_rejection
# ---------------------------------------------------------------------------


class TestClassifyForgeRejection:
    def test_maps_each_direct_status(self):
        mapping = {
            "rejected_by_user": "user_rejected",
            "failed_design": "design_failed",
            "dependencies_declined": "dependency_declined",
            "dependencies_failed": "dependency_failed",
            "failed_sandbox": "failed_sandbox",
            "failed_registration": "failed_registration",
            "max_limit": "max_limit",
            "shape_rejected": "shape_rejected",
        }
        for status, expected in mapping.items():
            assert classify_forge_rejection(_rec("foo", status)) == expected

    def test_validation_syntax_error(self):
        rec = _rec("foo", "failed_validation", error="Validation: Syntax error: bad token (line 3)")
        assert classify_forge_rejection(rec) == "syntax_error"

    def test_validation_forbidden_import(self):
        rec = _rec("foo", "failed_validation", error="Validation: Forbidden import: subprocess")
        assert classify_forge_rejection(rec) == "forbidden_import"

    def test_validation_schema_nonconformance(self):
        rec = _rec("foo", "failed_validation", error="Validation: No BaseAgent subclass found")
        assert classify_forge_rejection(rec) == "schema_nonconformance"

    def test_validation_judge_correctness(self):
        rec = _rec("foo", "failed_validation", error="Judge rejected: correctness below threshold")
        assert classify_forge_rejection(rec) == "judge_correctness"

    def test_validation_uses_validator_errors_arg(self):
        rec = _rec("foo", "failed_validation", error="")
        result = classify_forge_rejection(rec, validator_errors=["Forbidden import: os"])
        assert result == "forbidden_import"

    def test_validation_unrecognized_defaults_to_schema(self):
        rec = _rec("foo", "failed_validation", error="something inscrutable")
        assert classify_forge_rejection(rec) == "schema_nonconformance"

    def test_other_fallback_for_active(self):
        assert classify_forge_rejection(_rec("foo", "active")) == "other"

    def test_other_fallback_for_unmapped_status(self):
        # failed_pool is a real status not in the explicit taxonomy.
        assert classify_forge_rejection(_rec("foo", "failed_pool")) == "other"
        assert classify_forge_rejection(_rec("foo", "totally_unknown")) == "other"

    def test_all_results_are_in_taxonomy(self):
        for status in ("rejected_by_user", "failed_design", "failed_sandbox", "active"):
            assert classify_forge_rejection(_rec("foo", status)) in REJECTION_BUCKETS


# ---------------------------------------------------------------------------
# ForgeStatsAggregator
# ---------------------------------------------------------------------------


class TestForgeStatsAggregator:
    def test_empty(self):
        agg = ForgeStatsAggregator([])
        assert agg.total_attempts == 0
        assert agg.total_unique_intents == 0
        assert agg.attempt_approval_rate == 0.0
        assert agg.unique_intent_approval_rate == 0.0
        assert agg.rejection_histogram == {}

    def test_separates_attempt_vs_unique_rate(self):
        # foo: 2 failed_validation + 1 active; bar: 1 active; baz: 1 failed_sandbox.
        records = [
            _rec("foo", "failed_validation", error="No BaseAgent subclass found"),
            _rec("foo", "failed_validation", error="Missing 'agent_type' class attribute"),
            _rec("foo", "active"),
            _rec("bar", "active"),
            _rec("baz", "failed_sandbox"),
        ]
        agg = ForgeStatsAggregator(records)
        assert agg.total_attempts == 5
        assert agg.attempt_approval_rate == pytest.approx(2 / 5)
        assert agg.total_unique_intents == 3
        # foo and bar approved at least once; baz never → 2/3.
        assert agg.unique_intent_approval_rate == pytest.approx(2 / 3)

    def test_histogram_correctness(self):
        records = [
            _rec("foo", "failed_validation", error="No BaseAgent subclass found"),
            _rec("foo", "failed_validation", error="Missing 'agent_type' class attribute"),
            _rec("foo", "active"),
            _rec("bar", "active"),
            _rec("baz", "failed_sandbox"),
        ]
        agg = ForgeStatsAggregator(records)
        assert agg.rejection_histogram == {"schema_nonconformance": 2, "failed_sandbox": 1}

    def test_removed_counts_as_approval(self):
        agg = ForgeStatsAggregator([_rec("foo", "removed")])
        assert agg.attempt_approval_rate == 1.0
        assert agg.rejection_histogram == {}

    def test_materializes_local_copy(self):
        records = [_rec("foo", "active")]
        agg = ForgeStatsAggregator(records)
        records.append(_rec("bar", "failed_sandbox"))
        # Mutating the source list after construction must not change stats.
        assert agg.total_attempts == 1

    def test_summary_shape(self):
        agg = ForgeStatsAggregator([_rec("foo", "active"), _rec("bar", "failed_sandbox")])
        summary = agg.summary()
        assert summary["total_attempts"] == 2
        assert summary["total_unique_intents"] == 2
        assert summary["attempt_approval_rate"] == pytest.approx(0.5)
        assert summary["rejection_histogram"] == {"failed_sandbox": 1}


# ---------------------------------------------------------------------------
# Pipeline wiring (read-only honest-degrade)
# ---------------------------------------------------------------------------


class TestPipelineWiring:
    @pytest.mark.asyncio
    async def test_shape_gate_short_circuits_before_design(self):
        pipeline = _make_pipeline()
        pipeline._designer.design_agent = AsyncMock()

        record = await pipeline.handle_unhandled_intent(
            intent_name="",  # malformed → shape gate rejects
            intent_description="A description",
            parameters={},
        )

        assert record is None
        pipeline._designer.design_agent.assert_not_called()
        records = pipeline.designed_agents()
        assert len(records) == 1
        assert records[0].status == "shape_rejected"
        assert "Empty intent name" in records[0].error

    @pytest.mark.asyncio
    async def test_shape_gate_honest_degrade_on_exception(self, monkeypatch):
        # If the shape gate itself raises, normal design must still proceed.
        def boom(*a, **k):
            raise RuntimeError("gate exploded")

        monkeypatch.setattr(
            "probos.cognitive.self_mod.validate_forge_shape", boom
        )
        pipeline = _make_pipeline()
        record = await pipeline.handle_unhandled_intent(
            intent_name="count_words",
            intent_description="Count the number of words",
            parameters={"text": "input text"},
        )
        assert record is not None
        assert record.status == "active"

    @pytest.mark.asyncio
    async def test_forge_stats_method_returns_aggregator(self):
        pipeline = _make_pipeline()
        await pipeline.handle_unhandled_intent(
            intent_name="count_words",
            intent_description="Count the number of words",
            parameters={"text": "input text"},
        )
        stats = pipeline.forge_stats()
        assert isinstance(stats, ForgeStatsAggregator)
        assert stats.total_attempts == 1
        assert stats.attempt_approval_rate == 1.0
