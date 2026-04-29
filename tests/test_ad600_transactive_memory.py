"""AD-600: Transactive Memory expertise routing tests."""

from __future__ import annotations

from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

import pytest

from probos.cognitive.expertise_directory import ExpertiseDirectory
from probos.cognitive.oracle_service import OracleService
from probos.config import ExpertiseConfig, SystemConfig
from probos.startup.cognitive_services import init_cognitive_services
from probos.types import Episode


@dataclass
class _FakeCluster:
    cluster_id: str = "cluster-1"
    intent_types: list[str] = field(default_factory=list)
    success_rate: float = 0.8
    episode_count: int = 5
    anchor_summary: dict[str, Any] = field(default_factory=dict)
    is_success_dominant: bool = True
    is_failure_dominant: bool = False


class _FakeEpisodicMemory:
    def __init__(self) -> None:
        self.weighted_calls: list[str] = []
        self.recall_calls: list[str] = []

    async def recall_weighted(self, agent_id: str, query: str, **kwargs: Any) -> list[Any]:
        self.weighted_calls.append(agent_id)
        episode = Episode(
            id=f"ep-{agent_id}",
            user_input=f"{agent_id} remembers {query}",
            agent_ids=[agent_id],
        )
        return [SimpleNamespace(episode=episode, composite_score=0.9)]

    async def recall(self, query: str, k: int = 5) -> list[Episode]:
        self.recall_calls.append(query)
        return [Episode(id="global-ep", user_input=f"global memory {query}")]


@pytest.fixture
def directory() -> ExpertiseDirectory:
    return ExpertiseDirectory(config=ExpertiseConfig())


def test_update_profile_creates_new(directory: ExpertiseDirectory) -> None:
    directory.update_profile("agent-a", ["plasma diagnostics"], 0.8)

    profile = directory.get_profile("agent-a")
    assert profile is not None
    assert profile.topics["plasma diagnostics"] == 0.8


def test_update_profile_merges_topics(directory: ExpertiseDirectory) -> None:
    directory.update_profile("agent-a", ["plasma"], 0.4)
    directory.update_profile("agent-a", ["plasma", "warp"], 0.7)
    directory.update_profile("agent-a", ["plasma"], 0.5)

    profile = directory.get_profile("agent-a")
    assert profile is not None
    assert profile.topics == {"plasma": 0.7, "warp": 0.7}


def test_query_experts_ranked(directory: ExpertiseDirectory) -> None:
    directory.update_profile("agent-low", ["plasma"], 0.4)
    directory.update_profile("agent-high", ["plasma diagnostics"], 0.9)

    matches = directory.query_experts("plasma")

    assert [match.agent_id for match in matches] == ["agent-high", "agent-low"]


def test_query_experts_empty(directory: ExpertiseDirectory) -> None:
    directory.update_profile("agent-a", ["botany"], 0.9)

    assert directory.query_experts("plasma") == []


def test_build_from_clusters(directory: ExpertiseDirectory) -> None:
    clusters = [
        _FakeCluster(
            intent_types=["read_file", "diagnose"],
            success_rate=0.8,
            episode_count=5,
            anchor_summary={"departments": ["engineering"]},
        )
    ]

    topics_added = directory.build_from_clusters("agent-a", clusters, department="ops")
    profile = directory.get_profile("agent-a")

    assert topics_added == 3
    assert profile is not None
    assert "read_file" in profile.topics
    assert "diagnose" in profile.topics
    assert "dept:engineering" in profile.topics


def test_decay_profiles() -> None:
    directory = ExpertiseDirectory(config=ExpertiseConfig(min_confidence=0.3, decay_rate=0.5))
    directory.update_profile("agent-a", ["stable"], 0.8)
    directory.update_profile("agent-a", ["weak"], 0.4)

    removed = directory.decay_profiles()
    profile = directory.get_profile("agent-a")

    assert removed == 1
    assert profile is not None
    assert profile.topics == {"stable": 0.4}


def test_max_topics_cap() -> None:
    directory = ExpertiseDirectory(config=ExpertiseConfig(max_topics_per_agent=2, min_confidence=0.0))
    directory.update_profile("agent-a", ["low"], 0.2)
    directory.update_profile("agent-a", ["high"], 0.9)
    directory.update_profile("agent-a", ["mid"], 0.5)

    profile = directory.get_profile("agent-a")
    assert profile is not None
    assert set(profile.topics) == {"high", "mid"}


def test_min_confidence_filter() -> None:
    directory = ExpertiseDirectory(config=ExpertiseConfig(min_confidence=0.5))
    directory.update_profile("agent-a", ["weak"], 0.4)

    assert directory.get_profile("agent-a") is None


def test_department_enrichment(directory: ExpertiseDirectory) -> None:
    directory.update_profile("agent-a", ["plasma"], 0.8, department="engineering")
    directory.update_profile("agent-a", ["warp"], 0.8, department="science")

    profile = directory.get_profile("agent-a")
    assert profile is not None
    assert profile.department == "engineering"


@pytest.mark.asyncio
async def test_oracle_uses_expertise(directory: ExpertiseDirectory) -> None:
    memory = _FakeEpisodicMemory()
    directory.update_profile("expert-a", ["plasma diagnostics"], 0.9)
    directory.update_profile("expert-b", ["botany"], 0.9)
    oracle = OracleService(episodic_memory=memory, expertise_directory=directory)

    results = await oracle.query("plasma", tiers=["episodic"], k_per_tier=1)

    assert memory.weighted_calls == ["expert-a"]
    assert memory.recall_calls == []
    assert results[0].metadata["agent_scope"] == "expert-a"


@pytest.mark.asyncio
async def test_oracle_fallback_full_scan() -> None:
    memory = _FakeEpisodicMemory()
    oracle = OracleService(episodic_memory=memory)

    results = await oracle.query("plasma", tiers=["episodic"], k_per_tier=1)

    assert memory.weighted_calls == []
    assert memory.recall_calls == ["plasma"]
    assert results[0].content == "global memory plasma"


@pytest.mark.asyncio
async def test_config_disabled(tmp_path) -> None:
    config = SystemConfig()
    config.self_mod.enabled = False
    config.knowledge.enabled = False
    config.records.enabled = False
    config.orientation.enabled = False
    config.social_verification.enabled = False
    config.consultation.enabled = False
    config.expertise.enabled = False

    result = await init_cognitive_services(
        config=config,
        data_dir=tmp_path,
        registry=object(),
        pools={},
        llm_client=object(),
        trust_network=object(),
        hebbian_router=object(),
        episodic_memory=None,
        intent_bus=object(),
        working_memory=object(),
        event_log=object(),
        workflow_cache=object(),
        qa_reports={},
        submit_intent_with_consensus_fn=lambda *args, **kwargs: None,
        register_designed_agent_fn=lambda *args, **kwargs: None,
        unregister_designed_agent_fn=lambda *args, **kwargs: None,
        create_designed_pool_fn=lambda *args, **kwargs: None,
        set_probationary_trust_fn=lambda *args, **kwargs: None,
        add_skill_to_agents_fn=lambda *args, **kwargs: None,
        create_pool_fn=lambda *args, **kwargs: None,
    )

    assert result.expertise_directory is None


def test_multiple_topics_per_agent(directory: ExpertiseDirectory) -> None:
    directory.update_profile("agent-a", ["plasma", "warp", "diagnostics"], 0.8)

    assert directory.query_experts("warp")[0].agent_id == "agent-a"
    assert directory.query_experts("diagnostics")[0].agent_id == "agent-a"


def test_expert_match_ordering() -> None:
    directory = ExpertiseDirectory(config=ExpertiseConfig(top_k_experts=2))
    directory.update_profile("agent-low", ["topic"], 0.3)
    directory.update_profile("agent-high", ["topic"], 0.9)
    directory.update_profile("agent-mid", ["topic"], 0.6)

    matches = directory.query_experts("topic")

    assert [match.agent_id for match in matches] == ["agent-high", "agent-mid"]