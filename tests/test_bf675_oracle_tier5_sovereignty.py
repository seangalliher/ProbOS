"""BF-675: Oracle Tier 5 sovereign-shard bypass.

Tier 5 (`SemanticKnowledgeLayer`) recalls episodes GLOBALLY — no sovereign
filter — and the Oracle used to label those rows ``source_tier="semantic"``.
The AD-607e shard filter only inspects ``"episodic"`` rows, so an ORACLE-tier
agent received other agents' episode content verbatim, defeating the AD-397
sovereign-shard invariant that Tier 1 enforces structurally.

Two layers of fix, both covered here:
  * DD-2 (primary) — ``SemanticKnowledgeLayer.search(include_episodes=False)``
    excludes episodes at the source; the Oracle always passes it.
  * DD-3 (defence in depth) — any episode-typed row that still reaches
    ``_query_semantic`` is labelled ``"episodic"`` so AD-607e can act on it
    under non-default policies.

BF-287 discipline: the headline regression uses a REAL ``EpisodicMemory`` and a
REAL ``SemanticKnowledgeLayer`` on ``tmp_path`` — no MagicMock at the store
boundary. Determinism follows the AD-981a-proven identical-text path: the text
is stored verbatim and queried verbatim, yielding similarity >= the 0.7 recall
threshold.
"""
from __future__ import annotations

import inspect
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from probos.cognitive.episodic import EpisodicMemory
from probos.cognitive.memory_security import MemoryAccessPolicy
from probos.cognitive.oracle_service import OracleResult, OracleService
from probos.knowledge.semantic import SemanticKnowledgeLayer
from probos.types import Episode

# AD-981a-proven strong-recall text: stored verbatim and queried verbatim so
# cosine similarity clears EpisodicMemory's 0.7 relevance threshold.
EPISODE_TEXT = "The Captain approved the database migration on Tuesday afternoon."
SKILL_DESCRIPTION = "Calibrates the deflector array before a warp field transition."

AGENT_A = "agent-b-is-not-me"  # the non-owning caller
AGENT_B = "agent-b"  # the sole owner of the seeded episode


# ---------------------------------------------------------------------------
# Fixtures — real stores per BF-287
# ---------------------------------------------------------------------------


@pytest.fixture
async def episodic(tmp_path: Path):
    em = EpisodicMemory(db_path=str(tmp_path / "bf675_episodes.db"))
    await em.start()
    yield em
    try:
        await em.stop()
    except Exception:
        pass


@pytest.fixture
async def semantic(tmp_path: Path, episodic: EpisodicMemory):
    layer = SemanticKnowledgeLayer(
        db_path=tmp_path / "bf675_semantic", episodic_memory=episodic,
    )
    await layer.start()
    yield layer
    try:
        await layer.stop()
    except Exception:
        pass


class _StubSemanticLayer:
    """Async stub mirroring the post-BF-675 SemanticKnowledgeLayer.search()."""

    def __init__(self, results: list[dict] | None = None) -> None:
        self._results = results or []
        self.calls: list[dict] = []

    async def search(
        self,
        query: str,
        types: list[str] | None = None,
        limit: int = 10,
        *,
        include_episodes: bool = True,
    ) -> list[dict]:
        self.calls.append({
            "query": query,
            "types": types,
            "limit": limit,
            "include_episodes": include_episodes,
        })
        return list(self._results)


# ---------------------------------------------------------------------------
# 1. HEADLINE regression — fails on a pre-fix tree
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tier5_does_not_leak_foreign_agent_episodes(
    episodic: EpisodicMemory, semantic: SemanticKnowledgeLayer,
) -> None:
    """An episode owned only by agent-b never reaches agent-a via any tier.

    Runs under the DEFAULT permissive policy (no ``access_policy`` /
    ``caller_sovereign_id`` passed), which is the shipped configuration —
    the point of DD-1 is that exclusion, not relabelling, is what closes the
    hole by default.
    """
    await episodic.store(Episode(user_input=EPISODE_TEXT, agent_ids=[AGENT_B]))
    oracle = OracleService(episodic_memory=episodic, semantic_layer=semantic)

    # Control: the OWNER can still recall it, so a failed seed cannot produce
    # a vacuous pass on the assertion below.
    owner_results = await oracle.query(EPISODE_TEXT, agent_id=AGENT_B)
    assert any(EPISODE_TEXT in r.content for r in owner_results), (
        "seed/recall precondition failed — the owner cannot see its own episode"
    )

    leaked = [
        r for r in await oracle.query(EPISODE_TEXT, agent_id=AGENT_A)
        if EPISODE_TEXT in r.content
    ]
    assert leaked == [], (
        "BF-675: foreign episode content leaked to a non-owning agent via "
        f"tiers {[r.source_tier for r in leaked]}"
    )


@pytest.mark.asyncio
async def test_tier5_still_returns_semantic_collections(
    semantic: SemanticKnowledgeLayer,
) -> None:
    """Non-episode Tier 5 content is unaffected by the exclusion."""
    await semantic.index_skill(
        intent_name="calibrate_deflector", description=SKILL_DESCRIPTION,
    )
    oracle = OracleService(semantic_layer=semantic)

    results = await oracle.query(SKILL_DESCRIPTION, tiers=["semantic"])

    assert results, "Tier 5 returned nothing for an indexed skill"
    assert all(r.source_tier == "semantic" for r in results)
    assert any("calibrate_deflector" in r.content for r in results)


# ---------------------------------------------------------------------------
# 2. DD-2 — the layer-level gate
# ---------------------------------------------------------------------------


def test_search_include_episodes_is_keyword_only_and_defaults_true() -> None:
    param = inspect.signature(SemanticKnowledgeLayer.search).parameters["include_episodes"]
    assert param.kind == inspect.Parameter.KEYWORD_ONLY
    assert param.default is True


@pytest.mark.asyncio
async def test_semantic_search_default_unchanged(
    episodic: EpisodicMemory, semantic: SemanticKnowledgeLayer,
) -> None:
    """Existing callers that omit the kwarg still get episodes."""
    await episodic.store(Episode(user_input=EPISODE_TEXT, agent_ids=[AGENT_B]))

    results = await semantic.search(EPISODE_TEXT, limit=10)

    assert any(r["type"] == "episode" for r in results)


@pytest.mark.asyncio
async def test_semantic_search_include_episodes_false_excludes(
    episodic: EpisodicMemory, semantic: SemanticKnowledgeLayer,
) -> None:
    """The gate suppresses episodes even when ``types`` would admit them."""
    await episodic.store(Episode(user_input=EPISODE_TEXT, agent_ids=[AGENT_B]))

    assert await semantic.search(
        EPISODE_TEXT, limit=10, include_episodes=False,
    ) == []
    assert await semantic.search(
        EPISODE_TEXT, types=["episodes"], limit=10, include_episodes=False,
    ) == []


@pytest.mark.asyncio
async def test_query_semantic_passes_include_episodes_false() -> None:
    """The Oracle always opts out at the Tier 5 call site."""
    layer = _StubSemanticLayer([])
    oracle = OracleService(semantic_layer=layer)

    await oracle._query_semantic("q", k=5)

    assert layer.calls == [
        {"query": "q", "types": None, "limit": 5, "include_episodes": False},
    ]


# ---------------------------------------------------------------------------
# 3. DD-3 — defence-in-depth relabel
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_episode_typed_result_is_labelled_episodic() -> None:
    """An episode-typed Tier 5 row is labelled ``episodic`` and AD-607e drops it."""
    layer = _StubSemanticLayer([
        {"type": "episode", "id": "ep1", "document": EPISODE_TEXT, "score": 0.9,
         "metadata": {"type": "episode", "agent_ids": [AGENT_B]}},
        {"type": "skills", "id": "s1", "document": "skill doc", "score": 0.4,
         "metadata": {}},
    ])
    oracle = OracleService(semantic_layer=layer)

    results = await oracle._query_semantic("q", k=5)

    by_id = {r.metadata["id"]: r for r in results}
    assert by_id["ep1"].source_tier == "episodic"
    assert by_id["ep1"].provenance == "[episodic memory]"
    assert by_id["s1"].source_tier == "semantic"
    assert by_id["s1"].provenance == "[semantic: skills]"

    kept = oracle._apply_access_policy(
        results, AGENT_A, MemoryAccessPolicy.OWN_SHARD_ONLY,
    )

    assert [r.metadata["id"] for r in kept] == ["s1"]


@pytest.mark.asyncio
async def test_episode_typed_via_metadata_only_is_labelled_episodic() -> None:
    """The relabel also fires when only the nested metadata is typed."""
    layer = _StubSemanticLayer([
        {"id": "ep2", "document": EPISODE_TEXT, "score": 0.9,
         "metadata": {"type": "episode", "agent_ids": [AGENT_B]}},
    ])
    oracle = OracleService(semantic_layer=layer)

    results = await oracle._query_semantic("q", k=5)

    assert results[0].source_tier == "episodic"


@pytest.mark.asyncio
async def test_non_episode_results_keep_semantic_labelling() -> None:
    """Byte-identical labelling for every non-episode row (DD-6)."""
    layer = _StubSemanticLayer([
        {"type": "agents", "id": "a1", "document": "agent doc", "score": 0.9,
         "metadata": {"extra": "x"}},
    ])
    oracle = OracleService(semantic_layer=layer)

    result = (await oracle._query_semantic("q", k=5))[0]

    assert result.source_tier == "semantic"
    assert result.provenance == "[semantic: agents]"
    assert result.metadata == {"id": "a1", "type": "agents", "extra": "x"}


# ---------------------------------------------------------------------------
# 4. DD-4 — the Captain keeps seeing episodes through /search
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cmd_search_still_surfaces_episodes_for_captain(monkeypatch) -> None:
    from probos.experience import panels
    from probos.experience.commands.commands_knowledge import cmd_search

    oracle = SimpleNamespace(query=AsyncMock(return_value=[
        OracleResult(
            source_tier="episodic", content=EPISODE_TEXT, score=0.8,
            metadata={"episode_id": "ep1", "agent_ids": [AGENT_B]},
            provenance="[episodic memory]",
        ),
        OracleResult(
            source_tier="semantic", content="skill doc", score=0.4,
            metadata={"id": "s1", "type": "skills"},
            provenance="[semantic: skills]",
        ),
    ]))
    layer = MagicMock()
    layer.stats = MagicMock(return_value={"total": 1})
    runtime = SimpleNamespace(
        oracle=oracle, _oracle_service=oracle, _semantic_layer=layer,
    )
    rendered: list[list[dict]] = []
    monkeypatch.setattr(
        panels, "render_search_panel",
        lambda query, results, stats: rendered.append(results) or "panel",
    )

    await cmd_search(runtime, MagicMock(), "foo")

    assert oracle.query.call_args.kwargs["tiers"] == ["semantic", "episodic"]
    assert any(r["document"] == EPISODE_TEXT for r in rendered[0])


# ---------------------------------------------------------------------------
# 5. DD-5 — the Oracle-absent IntrospectAgent fallback
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_introspect_direct_layer_fallback_excludes_episodes() -> None:
    """Without an Oracle, IntrospectAgent must still opt out of episodes.

    ``types`` is ``None`` whenever the caller omits the optional "types"
    param, which is the exact condition that made the layer recall episodes
    globally.
    """
    from probos.agents.introspect import IntrospectionAgent

    layer = _StubSemanticLayer([])
    rt = SimpleNamespace(oracle=None, _semantic_layer=layer, codebase_index=None)
    agent = IntrospectionAgent.__new__(IntrospectionAgent)
    agent._runtime = rt

    await agent._search_knowledge(rt, {"query": "foo"})

    assert layer.calls[0]["types"] is None
    assert layer.calls[0]["include_episodes"] is False
