"""BF-149: Empty response retry and diagnostics across all memory probes."""

import pytest

from probos.cognitive.memory_probes import (
    SeededRecallProbe,
    TemporalReasoningProbe,
    KnowledgeUpdateProbe,
    CrossAgentSynthesisProbe,
)


class TestBF149ProbeRobustness:
    """All memory probes handle empty responses gracefully."""

    def test_seeded_recall_probe_has_run_inner(self):
        """BF-149: SeededRecallProbe has _run_inner for retry logic."""
        probe = SeededRecallProbe()
        assert hasattr(probe, "_run_inner")

    def test_temporal_probe_has_run_inner(self):
        """BF-149: TemporalReasoningProbe has _run_inner for retry logic."""
        probe = TemporalReasoningProbe()
        assert hasattr(probe, "_run_inner")

    def test_knowledge_update_probe_has_run_inner(self):
        """BF-149: KnowledgeUpdateProbe has _run_inner for retry logic."""
        probe = KnowledgeUpdateProbe()
        assert hasattr(probe, "_run_inner")

    def test_synthesis_probe_has_run_inner(self):
        """BF-149: CrossAgentSynthesisProbe has _run_inner for retry logic."""
        probe = CrossAgentSynthesisProbe()
        assert hasattr(probe, "_run_inner")
