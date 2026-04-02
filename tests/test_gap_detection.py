"""AD-539: Gap detection tests."""
import time
from dataclasses import dataclass

import pytest

from probos.cognitive.gap_predictor import (
    GapReport,
    detect_gaps,
    _priority_from_failure_rate,
)


# ── Helpers ────────────────────────────────────────────────────────────

@dataclass
class _FakeCluster:
    cluster_id: str = "c1"
    is_failure_dominant: bool = False
    episode_count: int = 10
    success_rate: float = 0.5
    intent_types: list = None

    def __post_init__(self):
        if self.intent_types is None:
            self.intent_types = ["read_file"]


def _ep(intent: str = "read_file", success: bool = True, confidence: float = 0.8, text: str = ""):
    """Create a minimal episode dict."""
    return {
        "intent": intent,
        "outcome": {"success": success, "confidence": confidence},
        "original_text": text,
    }


# ── Tests ──────────────────────────────────────────────────────────────

def test_detect_gaps_from_failure_clusters():
    """Failure-dominant cluster produces a GapReport."""
    cluster = _FakeCluster(is_failure_dominant=True, success_rate=0.3, episode_count=10)
    gaps = detect_gaps([], [cluster], [], [], agent_id="a1", agent_type="test_agent")
    assert len(gaps) >= 1
    gap = gaps[0]
    assert gap.gap_type in ("knowledge", "capability")
    assert gap.failure_rate == pytest.approx(0.7)
    assert "failure_cluster" in gap.evidence_sources[0]


def test_detect_gaps_skips_success_clusters():
    """Success-dominant cluster produces no gap."""
    cluster = _FakeCluster(is_failure_dominant=False, success_rate=0.9, episode_count=10)
    gaps = detect_gaps([], [cluster], [], [], agent_id="a1", agent_type="t")
    # Only source 1 (predict_gaps on empty episodes) produces nothing
    assert all("failure_cluster" not in ",".join(g.evidence_sources) for g in gaps)


def test_detect_gaps_from_procedure_decay():
    """Decayed procedure produces a GapReport."""
    decay = [{"id": "p1", "name": "proc_one", "intent_types": ["intent_a"]}]
    gaps = detect_gaps([], [], decay, [], agent_id="a1", agent_type="t")
    decay_gaps = [g for g in gaps if "procedure_decay" in ",".join(g.evidence_sources)]
    assert len(decay_gaps) == 1
    assert decay_gaps[0].gap_type == "knowledge"
    assert decay_gaps[0].priority == "low"


def test_detect_gaps_from_procedure_health():
    """FIX diagnosis procedure produces a GapReport."""
    health = [{"id": "p2", "name": "proc_two", "diagnosis": "FIX:high_fallback_rate",
               "intent_types": ["intent_b"], "failure_rate": 0.5, "total_selections": 20}]
    gaps = detect_gaps([], [], [], health, agent_id="a1", agent_type="t")
    health_gaps = [g for g in gaps if "procedure_health" in ",".join(g.evidence_sources)]
    assert len(health_gaps) == 1
    assert health_gaps[0].priority == "medium"


def test_detect_gaps_from_episodes():
    """Episode-based predict_gaps() output gets wrapped into GapReports."""
    # Need 3+ fallbacks on same topic for repeated_fallback detection
    episodes = [_ep(intent="", confidence=0.1, text="analyze sentiment deeply") for _ in range(4)]
    gaps = detect_gaps(episodes, [], [], [], agent_id="a1", agent_type="t")
    assert len(gaps) >= 1  # At least the fallback detection should fire


def test_detect_gaps_deduplicates():
    """Same intent from multiple sources produces single merged GapReport."""
    cluster1 = _FakeCluster(cluster_id="c1", is_failure_dominant=True, success_rate=0.2,
                            episode_count=10, intent_types=["intent_x"])
    health1 = {"id": "p3", "name": "proc", "diagnosis": "FIX:low_completion",
               "intent_types": ["intent_x"], "failure_rate": 0.6, "total_selections": 15}
    gaps = detect_gaps([], [cluster1], [], [health1], agent_id="a1", agent_type="t")
    # Both sources share intent_x → should be merged
    intent_x_gaps = [g for g in gaps if "intent_x" in g.affected_intent_types]
    assert len(intent_x_gaps) == 1
    # Merged gap should have evidence from both sources
    src_text = ",".join(intent_x_gaps[0].evidence_sources)
    assert "failure_cluster" in src_text
    assert "procedure_health" in src_text


def test_detect_gaps_respects_min_failure_rate():
    """Cluster below failure rate threshold produces no gap."""
    cluster = _FakeCluster(is_failure_dominant=True, success_rate=0.85, episode_count=10)
    gaps = detect_gaps([], [cluster], [], [], agent_id="a1", agent_type="t")
    cluster_gaps = [g for g in gaps if "failure_cluster" in ",".join(g.evidence_sources)]
    assert len(cluster_gaps) == 0


def test_detect_gaps_respects_min_episodes():
    """Cluster with too few episodes produces no gap."""
    cluster = _FakeCluster(is_failure_dominant=True, success_rate=0.2, episode_count=2)
    gaps = detect_gaps([], [cluster], [], [], agent_id="a1", agent_type="t")
    cluster_gaps = [g for g in gaps if "failure_cluster" in ",".join(g.evidence_sources)]
    assert len(cluster_gaps) == 0


def test_detect_gaps_caps_output():
    """More than GAP_REPORT_MAX_PER_DREAM gaps are capped."""
    # Create 15 unique procedures with health issues
    health_list = [
        {"id": f"p{i}", "name": f"proc_{i}", "diagnosis": "FIX:high_fallback_rate",
         "intent_types": [f"unique_intent_{i}"], "failure_rate": 0.5, "total_selections": 10}
        for i in range(15)
    ]
    gaps = detect_gaps([], [], [], health_list, agent_id="a1", agent_type="t")
    assert len(gaps) <= 10  # GAP_REPORT_MAX_PER_DREAM default is 10


def test_detect_gaps_priority_assignment():
    """High failure rate gets high priority."""
    cluster = _FakeCluster(is_failure_dominant=True, success_rate=0.1, episode_count=20)
    gaps = detect_gaps([], [cluster], [], [], agent_id="a1", agent_type="t")
    cluster_gaps = [g for g in gaps if "failure_cluster" in ",".join(g.evidence_sources)]
    assert len(cluster_gaps) == 1
    assert cluster_gaps[0].priority == "critical"  # 0.9 failure rate → critical


def test_detect_gaps_empty_inputs():
    """No clusters, no decay, no episodes → empty list."""
    gaps = detect_gaps([], [], [], [], agent_id="a1", agent_type="t")
    assert gaps == []


def test_gap_report_to_dict():
    """GapReport serialization includes all key fields."""
    gap = GapReport(
        id="test-gap-1",
        agent_id="agent1",
        agent_type="SecurityAgent",
        gap_type="knowledge",
        description="Test gap",
        evidence_sources=["episode:low_confidence"],
        affected_intent_types=["read_file"],
        failure_rate=0.5,
        episode_count=10,
        mapped_skill_id="static_analysis",
        current_proficiency=1,
        target_proficiency=3,
        priority="high",
    )
    d = gap.to_dict()
    assert d["id"] == "test-gap-1"
    assert d["gap_type"] == "knowledge"
    assert d["failure_rate"] == 0.5
    assert d["mapped_skill_id"] == "static_analysis"
    assert d["resolved"] is False
    assert d["resolved_at"] is None
    assert "affected_intent_types" in d
    assert "evidence_sources" in d
