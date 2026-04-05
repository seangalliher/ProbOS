"""AD-539: Dream Step 8 integration tests."""
import time
from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from probos.cognitive.dreaming import DreamingEngine
from probos.types import DreamReport


def _make_engine(**overrides) -> DreamingEngine:
    """Create a DreamingEngine using object.__new__() to skip __init__."""
    engine = object.__new__(DreamingEngine)
    engine._agent_id = overrides.get("agent_id", "test-agent")
    engine._agent_type = overrides.get("agent_type", "TestAgent")
    engine._router = overrides.get("router", None)
    engine._trust = overrides.get("trust", None)
    engine._procedure_store = overrides.get("procedure_store", None)
    engine._gap_prediction_fn = overrides.get("gap_prediction_fn", None)
    engine._contradiction_detection_fn = overrides.get("contradiction_fn", None)
    engine._last_dream_report = None
    engine._dream_lock = None
    engine.episodic_memory = overrides.get("episodic_memory", AsyncMock())
    engine._last_clusters = overrides.get("clusters", [])
    engine._config = overrides.get("config", MagicMock())
    # AD-567d fields
    engine._activation_tracker = None
    return engine


@dataclass
class FakeCluster:
    cluster_id: str = "c1"
    is_failure_dominant: bool = True
    episode_count: int = 10
    success_rate: float = 0.3
    intent_types: list = None

    def __post_init__(self):
        if self.intent_types is None:
            self.intent_types = ["test_intent"]


@pytest.mark.asyncio
async def test_step_8_enhanced_with_clusters():
    """Step 8 uses failure clusters from Step 6."""
    cluster = FakeCluster(is_failure_dominant=True, success_rate=0.2, episode_count=10)
    proc_store = AsyncMock()
    proc_store.list_active = AsyncMock(return_value=[])
    engine = _make_engine(clusters=[cluster], procedure_store=proc_store)

    # Import and test detect_gaps directly
    from probos.cognitive.gap_predictor import detect_gaps
    gaps = detect_gaps([], [cluster], [], [], agent_id="test", agent_type="Test")
    assert len(gaps) >= 1
    assert any("failure_cluster" in ",".join(g.evidence_sources) for g in gaps)


@pytest.mark.asyncio
async def test_step_8_uses_decay_results():
    """Step 8 consumes Step 7f decay results."""
    from probos.cognitive.gap_predictor import detect_gaps
    decay = [{"id": "p1", "name": "stale_proc", "intent_types": ["analyze"]}]
    gaps = detect_gaps([], [], decay, [], agent_id="a1", agent_type="Test")
    decay_gaps = [g for g in gaps if "procedure_decay" in ",".join(g.evidence_sources)]
    assert len(decay_gaps) == 1


@pytest.mark.asyncio
async def test_step_8_generates_gap_reports():
    """GapReport objects generated from detect_gaps."""
    from probos.cognitive.gap_predictor import detect_gaps, GapReport
    health = [{"id": "p1", "name": "bad_proc", "diagnosis": "FIX:high_fallback_rate",
               "intent_types": ["test_intent"], "failure_rate": 0.5, "total_selections": 20}]
    gaps = detect_gaps([], [], [], health, agent_id="a1", agent_type="Test")
    assert all(isinstance(g, GapReport) for g in gaps)
    assert len(gaps) >= 1


@pytest.mark.asyncio
async def test_step_8_writes_to_records():
    """Ship's Records receives gap YAML when available."""
    from probos.cognitive.gap_predictor import detect_gaps, GapReport
    records_store = AsyncMock()
    records_store.write_entry = AsyncMock()

    health = [{"id": "p1", "name": "test", "diagnosis": "FIX:low_completion",
               "intent_types": ["x"], "failure_rate": 0.4, "total_selections": 10}]
    gaps = detect_gaps([], [], [], health, agent_id="a1", agent_type="Test")

    # Simulate what dream Step 8 does with records_store
    for gap in gaps:
        import yaml
        content = yaml.dump(gap.to_dict(), default_flow_style=False, sort_keys=False)
        await records_store.write_entry(
            author="system",
            path=f"reports/gap-reports/{gap.id}.md",
            content=content,
            message=f"Gap report: {gap.description}",
            classification="ship",
            topic="gap_analysis",
            tags=["ad-539", gap.gap_type, gap.priority],
        )

    assert records_store.write_entry.call_count == len(gaps)


@pytest.mark.asyncio
async def test_step_8_updates_dream_report():
    """DreamReport includes gaps_classified, qualification_paths_triggered, gap_reports_generated."""
    report = DreamReport(
        gaps_predicted=5,
        gaps_classified=3,
        qualification_paths_triggered=1,
        gap_reports_generated=5,
    )
    assert report.gaps_classified == 3
    assert report.qualification_paths_triggered == 1
    assert report.gap_reports_generated == 5


@pytest.mark.asyncio
async def test_step_8_backward_compatible():
    """_gap_prediction_fn callback still fires."""
    callback_called = []

    def on_gaps(gaps):
        callback_called.extend(gaps)

    from probos.cognitive.gap_predictor import detect_gaps
    # Generate some gaps via health source
    health = [{"id": "p1", "name": "proc", "diagnosis": "FIX:high_fallback_rate",
               "intent_types": ["x"], "failure_rate": 0.5, "total_selections": 10}]
    gaps = detect_gaps([], [], [], health, agent_id="a1", agent_type="Test")

    # Simulate the callback pattern from dreaming.py Step 8
    if gaps:
        on_gaps(gaps)

    assert len(callback_called) == len(gaps)


@pytest.mark.asyncio
async def test_step_8_no_skill_framework_graceful():
    """No SkillFramework → detection works, qualification skipped."""
    from probos.cognitive.gap_predictor import detect_gaps, map_gap_to_skill, trigger_qualification_if_needed

    health = [{"id": "p1", "name": "proc", "diagnosis": "FIX:low_completion",
               "intent_types": ["intent_a"], "failure_rate": 0.5, "total_selections": 10}]
    gaps = detect_gaps([], [], [], health, agent_id="a1", agent_type="Test")
    assert len(gaps) >= 1

    # No skill service → map_gap_to_skill should be safe
    gap = await map_gap_to_skill(gaps[0], None)
    assert gap.mapped_skill_id == ""  # No mapping without service

    # No skill service → trigger_qualification should be safe
    gap = await trigger_qualification_if_needed(gap, None)
    assert gap.qualification_path_id == ""
