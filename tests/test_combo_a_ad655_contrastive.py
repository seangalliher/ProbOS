"""Combo A AD-655: Contrastive Memory Retrieval tests."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from probos.events import EventType


@pytest.mark.asyncio
async def test_episodic_retrieve_contrastive_returns_mid_band():
    """Mock chroma returns 5 results with distances [0.1, 0.3, 0.5, 0.6, 0.9].

    Mid-band [0.4, 0.65] similarity -> distances in [0.35, 0.6].
    Expected: episodes at distances 0.5, 0.6 (similarity 0.5, 0.4).
    Distance 0.3 = similarity 0.7 (above HIGH 0.65 -> filtered).
    """
    from probos.cognitive.episodic import EpisodicMemory

    em = EpisodicMemory.__new__(EpisodicMemory)  # bypass init
    em._collection = MagicMock()
    em._collection.count = MagicMock(return_value=5)
    em._collection.query = MagicMock(return_value={
        "ids": [["ep-a", "ep-b", "ep-c", "ep-d", "ep-e"]],
        "distances": [[0.1, 0.3, 0.5, 0.6, 0.9]],
        "metadatas": [[{}, {}, {}, {}, {}]],
        "documents": [["a", "b", "c", "d", "e"]],
    })
    em._metadata_to_episode = lambda doc_id, doc, meta: SimpleNamespace(id=doc_id)

    contrastive = await em.retrieve_contrastive_episodes("query", k=5)
    ids = [ep.id for ep in contrastive]
    # Distances 0.5 (sim 0.5) and 0.6 (sim 0.4) are in mid-band [0.4, 0.65]
    assert "ep-c" in ids
    assert "ep-d" in ids
    # 0.1 (sim 0.9) is too similar; 0.3 (sim 0.7) above HIGH; 0.9 (sim 0.1) below LOW
    assert "ep-a" not in ids
    assert "ep-e" not in ids


@pytest.mark.asyncio
async def test_episodic_retrieve_contrastive_no_results_returns_empty_list():
    from probos.cognitive.episodic import EpisodicMemory

    em = EpisodicMemory.__new__(EpisodicMemory)
    em._collection = MagicMock()
    em._collection.count = MagicMock(return_value=0)
    contrastive = await em.retrieve_contrastive_episodes("query", k=2)
    assert contrastive == []


@pytest.mark.asyncio
async def test_episodic_retrieve_contrastive_emits_event():
    from probos.cognitive.episodic import EpisodicMemory

    em = EpisodicMemory.__new__(EpisodicMemory)
    em._collection = MagicMock()
    em._collection.count = MagicMock(return_value=2)
    em._collection.query = MagicMock(return_value={
        "ids": [["ep-1", "ep-2"]],
        "distances": [[0.5, 0.5]],
        "metadatas": [[{}, {}]],
        "documents": [["x", "y"]],
    })
    em._metadata_to_episode = lambda doc_id, doc, meta: SimpleNamespace(id=doc_id)
    em._emit_event = MagicMock()

    contrastive = await em.retrieve_contrastive_episodes("query", k=2)
    assert len(contrastive) == 2
    em._emit_event.assert_called_once()
    et, payload = em._emit_event.call_args[0]
    assert et == EventType.CONTRASTIVE_RECALL
    assert "episode_ids" in payload


@pytest.mark.asyncio
async def test_evaluate_handler_consults_contrastive_when_runtime_episodic_wired():
    """EvaluateHandler.__call__ enriches context with _contrastive_priors when wired."""
    from probos.cognitive.sub_tasks.evaluate import EvaluateHandler
    from probos.cognitive.sub_task import SubTaskSpec, SubTaskType

    fake_em = MagicMock()
    fake_em.retrieve_contrastive_episodes = AsyncMock(return_value=[
        SimpleNamespace(id="ep-c", user_input="contrastive prior"),
    ])

    fake_runtime = SimpleNamespace()
    fake_runtime.episodic_memory = fake_em
    fake_runtime.config = None

    handler = EvaluateHandler(llm_client=MagicMock(), runtime=fake_runtime)
    # Stub the LLM call path -- context enrichment happens BEFORE LLM dispatch
    spec = SubTaskSpec(
        sub_task_type=SubTaskType.EVALUATE,
        name="test",
        prompt_template=None,
    )
    context = {"context": "review the agent's reasoning"}

    # Force a controlled, fast return path by triggering the BF-191 raw-JSON early-out
    # (compose_output is empty -> falls through to BF-204 grounding -- which still
    # writes context["_contrastive_priors"] at our hook above the safety-checks block).
    try:
        await handler(spec, context, prior_results=[])
    except Exception:
        pass  # the LLM dispatch will fail; we only care about the context enrichment

    fake_em.retrieve_contrastive_episodes.assert_awaited_once()
    assert "_contrastive_priors" in context
    assert context["_contrastive_priors"][0]["id"] == "ep-c"
