"""AD-980b (Agent self-interpretation epic, #911): per-agent dream attribution.

Dream-consolidation reflections (AD-599 ``_step_15_reflection_promotion``) were
stored ownerless (``agent_ids=[]``) even though each candidate already carries
its ``involved_agents`` — so no agent could recall "its" dream, and dream
interpretation (AD-980c) was impossible (a dream had no dreamer). AD-980b stores
a reflection with ``agent_ids=<involved agents>`` when
``per_agent_dream_attribution_enabled`` is set, giving a dream a dreamer.
Reflections with NO involved agents (emergence/notebook snapshots) stay
ownerless. Default OFF -> ``agent_ids=[]`` (byte-identical to AD-599).

BF-287 discipline: a real ``DreamingConfig`` + a real recording episodic stub
(NOT MagicMock at the storage boundary).
"""
from __future__ import annotations

import dataclasses
import logging
import re
import types as stdlib_types

import pytest

from probos.config import DreamingConfig
from probos.types import EpisodeDuplicatePolicy, EpisodeStoreOutcome, MemorySource


class _RecordingEpisodic:
    def __init__(self):
        self.stored: list = []

    async def store(
        self,
        episode,
        *,
        duplicate_policy=EpisodeDuplicatePolicy.UNEXPECTED,
    ):
        self.stored.append(episode)
        return EpisodeStoreOutcome.STORED

    async def recent(self, *a, **k):
        return []

    async def get_embeddings(self, *a, **k):
        return {}


def _make_engine(*, attribution: bool):
    from unittest.mock import MagicMock

    from probos.cognitive.dreaming import DreamingEngine

    mem = _RecordingEpisodic()
    cfg = DreamingConfig(per_agent_dream_attribution_enabled=attribution)
    # router/trust are untouched by _step_15; only episodic + config matter.
    return DreamingEngine(
        router=MagicMock(),
        trust_network=MagicMock(),
        episodic_memory=mem,
        config=cfg,
    ), mem


def _make_episode(ep_id: str, agent_ids: list[str]):
    return stdlib_types.SimpleNamespace(id=ep_id, agent_ids=agent_ids)


def _make_cluster(cluster_id: str, episode_ids: list[str]):
    return stdlib_types.SimpleNamespace(
        cluster_id=cluster_id,
        episode_ids=episode_ids,
        is_success_dominant=True,
        is_failure_dominant=False,
        anchor_summary=None,
    )


# ============================ flag-off (byte-identical) ============================


@pytest.mark.asyncio
async def test_attribution_off_keeps_reflections_ownerless():
    engine, mem = _make_engine(attribution=False)
    conv = {"agents": ["yeo", "ezri"], "departments": ["ops"], "topic": "t", "coherence": 0.8}
    await engine._step_15_reflection_promotion(
        episodes=[], clusters=[], convergence_reports=[conv],
        emergence_capacity=None, coordination_balance=None,
        notebook_consolidations=0, behavioral_quality_score=None,
    )
    assert mem.stored
    assert mem.stored[0].agent_ids == []  # AD-599 byte-identical
    # The involved agents are still recorded in dag_summary (provenance).
    assert mem.stored[0].dag_summary["involved_agents"] == ["yeo", "ezri"]


# ============================ flag-on (give the dream a dreamer) ============================


@pytest.mark.asyncio
async def test_attribution_on_gives_convergence_reflection_its_dreamers():
    engine, mem = _make_engine(attribution=True)
    conv = {"agents": ["yeo", "ezri"], "departments": ["ops"], "topic": "t", "coherence": 0.8}
    await engine._step_15_reflection_promotion(
        episodes=[], clusters=[], convergence_reports=[conv],
        emergence_capacity=None, coordination_balance=None,
        notebook_consolidations=0, behavioral_quality_score=None,
    )
    assert mem.stored
    ep = mem.stored[0]
    assert ep.agent_ids == ["yeo", "ezri"]  # owned by its dreamers
    assert ep.source == MemorySource.REFLECTION


@pytest.mark.asyncio
async def test_attribution_on_gives_cluster_reflection_its_dreamers():
    engine, mem = _make_engine(attribution=True)
    # A success-dominant cluster of >=5 episodes participated in by yeo + bones.
    episodes = [_make_episode(f"e{i}", ["yeo"] if i % 2 else ["bones"]) for i in range(6)]
    cluster = _make_cluster("c1", [e.id for e in episodes])
    await engine._step_15_reflection_promotion(
        episodes=episodes, clusters=[cluster], convergence_reports=[],
        emergence_capacity=None, coordination_balance=None,
        notebook_consolidations=0, behavioral_quality_score=None,
    )
    assert mem.stored
    ep = mem.stored[0]
    # The cluster's participating agents own the dream (sorted set, capped 5).
    assert set(ep.agent_ids) == {"yeo", "bones"}


@pytest.mark.asyncio
async def test_agentless_reflection_stays_ownerless_even_when_on():
    # An emergence snapshot has NO involved agents -> stays ownerless even with
    # attribution enabled (not every reflection has a dreamer).
    engine, mem = _make_engine(attribution=True)
    await engine._step_15_reflection_promotion(
        episodes=[], clusters=[], convergence_reports=[],
        emergence_capacity=0.7, coordination_balance=0.5,
        notebook_consolidations=0, behavioral_quality_score=0.6,
    )
    assert mem.stored
    # the emergence snapshot reflection carries no involved agents
    emergence = [e for e in mem.stored if "emergence" in e.user_input.lower()]
    assert emergence
    assert emergence[0].agent_ids == []


@pytest.mark.asyncio
async def test_default_config_is_off():
    # The flag ships OFF (byte-identical default).
    assert DreamingConfig().per_agent_dream_attribution_enabled is False


@pytest.mark.asyncio
async def test_same_reflection_with_changed_attribution_conflicts_without_overwrite(caplog):
    """BF-669: AD-980b attribution is stable canonical content, not replay drift."""
    from unittest.mock import MagicMock

    from probos.cognitive.dreaming import DreamingEngine
    from probos.cognitive.episodic import compute_episode_hash
    from probos.cognitive.episodic_mock import MockEpisodicMemory

    memory = MockEpisodicMemory()
    off_engine = DreamingEngine(
        router=MagicMock(), trust_network=MagicMock(), episodic_memory=memory,
        config=DreamingConfig(per_agent_dream_attribution_enabled=False),
    )
    on_engine = DreamingEngine(
        router=MagicMock(), trust_network=MagicMock(), episodic_memory=memory,
        config=DreamingConfig(per_agent_dream_attribution_enabled=True),
    )
    conv = {
        "agents": ["yeo", "ezri"], "departments": ["ops"],
        "topic": "stable attribution", "coherence": 0.8,
    }
    assert await off_engine._step_15_reflection_promotion(
        episodes=[], clusters=[], convergence_reports=[conv],
        emergence_capacity=None, coordination_balance=None,
        notebook_consolidations=0, behavioral_quality_score=None,
    ) == 1

    with caplog.at_level(logging.WARNING, logger="probos.cognitive.episodic_mock"):
        created = await on_engine._step_15_reflection_promotion(
            episodes=[], clusters=[], convergence_reports=[conv],
            emergence_capacity=None, coordination_balance=None,
            notebook_consolidations=0, behavioral_quality_score=None,
        )

    assert created == 0
    assert len(memory._episodes) == 1
    existing = memory._episodes[0]
    incoming = dataclasses.replace(existing, agent_ids=["yeo", "ezri"])
    assert existing.agent_ids == []
    warnings = [
        record.message
        for record in caplog.records
        if record.levelno == logging.WARNING
    ]
    assert len(warnings) == 1
    warning = warnings[0]
    assert "reason=content_conflict" in warning
    hash_match = re.search(
        r"incoming_hash=([0-9a-f]{12}) existing_hash=([0-9a-f]{12});",
        warning,
    )
    assert hash_match is not None
    assert hash_match.groups() == (
        compute_episode_hash(incoming)[:12],
        compute_episode_hash(existing)[:12],
    )
    assert "existing write remains authoritative" in warning
    assert existing.user_input not in warning
    assert existing.reflection not in warning
