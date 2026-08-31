"""AD-657: Dream consolidation trace preservation tests."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from probos.cognitive.procedures import Procedure
from probos.config import DreamingConfig
from probos.types import Episode


# ---- Section 1: Procedure schema -------------------------------------------


def test_procedure_trace_exemplars_default_empty() -> None:
    proc = Procedure()
    assert proc.trace_exemplars == []


def test_procedure_trace_exemplars_round_trip() -> None:
    proc = Procedure(trace_exemplars=["a", "b", "c"])
    data = proc.to_dict()
    assert data["trace_exemplars"] == ["a", "b", "c"]
    restored = Procedure.from_dict(data)
    assert restored.trace_exemplars == ["a", "b", "c"]

    # Backward-compat: old serialized dicts (no key) load as []
    legacy: dict[str, Any] = {"id": "p1", "name": "x"}
    legacy_proc = Procedure.from_dict(legacy)
    assert legacy_proc.trace_exemplars == []


# ---- Section 2 + 3: DreamingConfig + Step 7 producer ranking ---------------


class _FakeProcedure:
    def __init__(self) -> None:
        self.trace_exemplars: list[str] = []
        self.source_anchors: list[dict[str, Any]] = []


def _select_exemplars(
    matched_episodes: list[Episode],
    config: DreamingConfig,
) -> list[str]:
    """Mirror of the Step 7 selection logic in dreaming.py for unit testing."""
    procedure = _FakeProcedure()
    n_exemplars = config.trace_exemplars_per_procedure
    if n_exemplars > 0 and matched_episodes:
        ranked = sorted(
            matched_episodes,
            key=lambda ep: (ep.importance, ep.timestamp),
            reverse=True,
        )
        procedure.trace_exemplars = [ep.id for ep in ranked[:n_exemplars]]
    return procedure.trace_exemplars


def _eps(spec: list[tuple[str, int, float]]) -> list[Episode]:
    return [
        Episode(id=eid, importance=imp, timestamp=ts, user_input=eid)
        for eid, imp, ts in spec
    ]


def test_dream_step_7_populates_top_n_by_importance() -> None:
    eps = _eps(
        [
            ("e1", 3, 10.0),
            ("e2", 9, 20.0),
            ("e3", 5, 30.0),
            ("e4", 9, 40.0),
            ("e5", 1, 50.0),
        ]
    )
    cfg = DreamingConfig(trace_exemplars_per_procedure=3)
    selected = _select_exemplars(eps, cfg)
    # importance DESC: 9,9,5,3,1 -> tie at 9 broken by timestamp DESC (40 before 20)
    assert selected == ["e4", "e2", "e3"]


def test_dream_step_7_caps_at_config() -> None:
    eps = _eps(
        [
            ("e1", 3, 10.0),
            ("e2", 9, 20.0),
            ("e3", 5, 30.0),
            ("e4", 9, 40.0),
            ("e5", 1, 50.0),
        ]
    )
    cfg = DreamingConfig(trace_exemplars_per_procedure=2)
    selected = _select_exemplars(eps, cfg)
    assert selected == ["e4", "e2"]


def test_dream_step_7_disabled_when_n_zero() -> None:
    eps = _eps([("e1", 9, 10.0), ("e2", 8, 20.0)])
    cfg = DreamingConfig(trace_exemplars_per_procedure=0)
    selected = _select_exemplars(eps, cfg)
    assert selected == []


# ---- Section 4: EpisodicMemory.get_by_ids ----------------------------------


@pytest.mark.asyncio
async def test_episodic_get_by_ids_returns_in_input_order(tmp_path: Path) -> None:
    from probos.cognitive.episodic import EpisodicMemory

    em = EpisodicMemory(db_path=str(tmp_path / "test.db"))
    await em.start()
    try:
        for i in range(1, 5):
            await em.store(
                Episode(
                    id=f"ep{i}",
                    user_input=f"input {i}",
                    timestamp=float(i * 100),
                    agent_ids=["a1"],
                )
            )

        result = await em.get_by_ids(["ep3", "ep1", "ep4", "ep_missing", "ep2"])
        assert [ep.id for ep in result] == ["ep3", "ep1", "ep4", "ep2"]

        # Empty input -> empty list (no ChromaDB call needed)
        assert await em.get_by_ids([]) == []
    finally:
        await em.stop()


@pytest.mark.asyncio
async def test_episodic_get_by_ids_no_collection_returns_empty() -> None:
    from probos.cognitive.episodic import EpisodicMemory

    em = EpisodicMemory(db_path=":memory:")
    # No start() — _collection is None
    assert await em.get_by_ids(["any"]) == []


# ---- Section 5: _gather_context consumer block -----------------------------


class _FakeProcedureStore:
    def __init__(
        self,
        match_score: float = 0.9,
        procedure: Procedure | None = None,
    ) -> None:
        self._score = match_score
        self._procedure = procedure

    async def find_matching(
        self, query: str, n_results: int = 1, exclude_negative: bool = True,
    ) -> list[dict[str, Any]]:
        if self._procedure is None:
            return []
        return [{"id": self._procedure.id, "score": self._score, "name": self._procedure.name}]

    async def get(self, procedure_id: str) -> Procedure | None:
        if self._procedure and procedure_id == self._procedure.id:
            return self._procedure
        return None


class _FakeEpisodicMemoryReturning:
    def __init__(self, episodes: list[Episode]) -> None:
        self._episodes = episodes
        self.last_for_evidence: bool | None = None
        # proactive.py also exercises recall_weighted/recall_for_agent — we need stubs.

    async def get_by_ids(
        self, episode_ids: list[str], *, for_evidence: bool = False,
    ) -> list[Episode]:
        # AD-1293 (#1200): ``proactive`` passes ``for_evidence=True`` here --
        # the exemplars land in the agent's prompt. Recorded so a caller that
        # drops the flag is visible to the assertion below.
        self.last_for_evidence = for_evidence
        wanted = set(episode_ids)
        return [ep for ep in self._episodes if ep.id in wanted]

    async def recall_for_agent(
        self, agent_id: str, query: str, k: int = 5,
    ) -> list[Episode]:
        return []

    async def recent_for_agent(self, agent_id: str, k: int = 5) -> list[Episode]:
        return []


def _make_runtime(store: Any, em: Any) -> Any:
    """Minimal runtime stub for _gather_context."""
    rt = SimpleNamespace()
    rt.procedure_store = store
    rt.episodic_memory = em
    rt.bridge_alerts = None
    rt.config = SimpleNamespace(
        temporal=SimpleNamespace(include_episode_timestamps=True),
    )
    return rt


def _make_agent() -> Any:
    return SimpleNamespace(
        id="agent-1",
        agent_type="counselor",
        callsign="A1",
        sovereign_id=None,
    )


@pytest.mark.asyncio
async def test_gather_context_surfaces_exemplars_when_procedure_matches() -> None:
    from probos.proactive import ProactiveCognitiveLoop

    long_input = "x" * 400
    eps = [
        Episode(id="ep1", user_input=long_input, reflection="ok", timestamp=1000.0, importance=9),
        Episode(id="ep2", user_input="short", reflection="r2", timestamp=2000.0, importance=8),
    ]
    proc = Procedure(
        id="proc-A",
        name="HandleReview",
        trace_exemplars=["ep1", "ep2"],
    )
    store = _FakeProcedureStore(match_score=0.9, procedure=proc)
    em = _FakeEpisodicMemoryReturning(eps)

    loop = ProactiveCognitiveLoop()
    loop.set_runtime(_make_runtime(store, em))
    context = await loop._gather_context(_make_agent(), trust_score=0.5)

    payload = context.get("recalled_procedure_exemplars")
    assert payload is not None
    assert payload["procedure_name"] == "HandleReview"
    # AD-1293 (#1200): this payload becomes prompt context, so proactive must
    # rehydrate as EVIDENCE. A bare call here leaks a self-contradicted episode.
    assert em.last_for_evidence is True
    assert payload["procedure_id"] == "proc-A"
    assert len(payload["exemplars"]) == 2
    # 300-char truncation marker present on the long one
    assert payload["exemplars"][0]["input"].endswith(" [trimmed]")
    assert len(payload["exemplars"][0]["input"]) == 300 + len(" [trimmed]")
    assert payload["exemplars"][0]["importance"] == 9
    # short input untouched
    assert payload["exemplars"][1]["input"] == "short"


@pytest.mark.asyncio
async def test_gather_context_omits_exemplars_when_episodes_missing() -> None:
    from probos.proactive import ProactiveCognitiveLoop

    proc = Procedure(id="proc-B", name="P", trace_exemplars=["gone1", "gone2"])
    store = _FakeProcedureStore(match_score=0.9, procedure=proc)
    em = _FakeEpisodicMemoryReturning([])  # all pruned

    loop = ProactiveCognitiveLoop()
    loop.set_runtime(_make_runtime(store, em))
    context = await loop._gather_context(_make_agent(), trust_score=0.5)

    assert "recalled_procedure_exemplars" not in context


@pytest.mark.asyncio
async def test_gather_context_omits_exemplars_when_score_below_floor() -> None:
    from probos.proactive import ProactiveCognitiveLoop

    proc = Procedure(id="proc-C", name="P", trace_exemplars=["ep1"])
    store = _FakeProcedureStore(match_score=0.3, procedure=proc)  # < 0.5
    em = _FakeEpisodicMemoryReturning([
        Episode(id="ep1", user_input="x", timestamp=1.0, importance=5),
    ])

    loop = ProactiveCognitiveLoop()
    loop.set_runtime(_make_runtime(store, em))
    context = await loop._gather_context(_make_agent(), trust_score=0.5)

    assert "recalled_procedure_exemplars" not in context
