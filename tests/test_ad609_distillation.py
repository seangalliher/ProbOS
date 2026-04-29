from dataclasses import dataclass, field

import pytest

from probos.cognitive.failure_distiller import ComparativeInsight, FailureDistiller
from probos.types import DreamReport


class _FakeDistillationConfig:
    def __init__(
        self,
        *,
        enabled: bool = True,
        min_failure_cluster_size: int = 3,
        comparative_enabled: bool = True,
    ) -> None:
        self.enabled = enabled
        self.min_failure_cluster_size = min_failure_cluster_size
        self.comparative_enabled = comparative_enabled


@dataclass
class _FakeCluster:
    cluster_id: str = "c1"
    intent_types: list[str] = field(default_factory=lambda: ["code_review"])
    success_rate: float = 0.2
    episode_count: int = 5
    is_success_dominant: bool = False
    is_failure_dominant: bool = True
    participating_agents: list[str] = field(default_factory=lambda: ["agent-1", "agent-2"])
    variance: float = 0.3
    anchor_summary: dict = field(
        default_factory=lambda: {
            "departments": ["engineering"],
            "trigger_types": ["ward_room_notification"],
        }
    )


@dataclass
class _FakeSuccessCluster:
    cluster_id: str = "s1"
    intent_types: list[str] = field(default_factory=lambda: ["code_review"])
    success_rate: float = 0.9
    episode_count: int = 8
    is_success_dominant: bool = True
    is_failure_dominant: bool = False
    participating_agents: list[str] = field(default_factory=lambda: ["agent-1", "agent-2", "agent-3"])
    variance: float = 0.1
    anchor_summary: dict = field(
        default_factory=lambda: {
            "departments": ["engineering", "science"],
            "trigger_types": ["direct_message"],
        }
    )


@pytest.fixture
def distiller() -> FailureDistiller:
    return FailureDistiller(config=_FakeDistillationConfig())


def test_distill_failure_patterns(distiller: FailureDistiller) -> None:
    procedures = distiller.distill_failure_patterns([_FakeCluster()])

    assert len(procedures) == 1
    assert procedures[0].name == "Failure: code_review"


def test_extract_failure_signals(distiller: FailureDistiller) -> None:
    signals = distiller._extract_failure_signals(_FakeCluster())

    assert signals["departments"] == ["engineering"]
    assert signals["agent_count"] == 2
    assert signals["trigger_types"] == ["ward_room_notification"]


def test_negative_procedure_fields(distiller: FailureDistiller) -> None:
    procedure = distiller.distill_failure_patterns([_FakeCluster()])[0]

    assert procedure.is_negative is True
    assert procedure.intent_types == ["code_review"]
    assert procedure.steps[0].step_number == 1
    assert "engineering" in procedure.description


def test_comparative_insight_same_intent(distiller: FailureDistiller) -> None:
    insights = distiller.distill_comparative([_FakeSuccessCluster()], [_FakeCluster()])

    assert len(insights) == 1
    assert isinstance(insights[0], ComparativeInsight)
    assert insights[0].intent_type == "code_review"


def test_comparative_differentiating_factor(distiller: FailureDistiller) -> None:
    failure = _FakeCluster(anchor_summary={"departments": ["security"], "trigger_types": []})
    insights = distiller.distill_comparative([_FakeSuccessCluster()], [failure])

    factor = insights[0].differentiating_factor

    assert "Success involves more agents" in factor
    assert "Failure-specific departments: security" in factor


def test_min_cluster_size_filter() -> None:
    distiller = FailureDistiller(config=_FakeDistillationConfig(min_failure_cluster_size=4))
    small_cluster = _FakeCluster(episode_count=2)

    assert distiller.distill_failure_patterns([small_cluster]) == []


def test_config_disabled() -> None:
    config = _FakeDistillationConfig(enabled=False)
    distiller = FailureDistiller(config=config) if config.enabled else None

    assert distiller is None


def test_dream_report_fields() -> None:
    report = DreamReport(failure_patterns_extracted=2, comparative_insights=1)

    assert report.failure_patterns_extracted == 2
    assert report.comparative_insights == 1


def test_no_failure_clusters(distiller: FailureDistiller) -> None:
    assert distiller.distill_failure_patterns([]) == []
    assert distiller.distill_comparative([_FakeSuccessCluster()], []) == []


def test_comparative_no_shared_intents(distiller: FailureDistiller) -> None:
    success = _FakeSuccessCluster(intent_types=["read_file"])
    failure = _FakeCluster(intent_types=["write_file"])

    assert distiller.distill_comparative([success], [failure]) == []