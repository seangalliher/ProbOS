"""BF-938 (#1680) M1: AD-607's recall gates on a real EpisodicMemory.

Before BF-938 a bound ``MemorySecurityConfig`` raised NameError in weighted recall: the gate's query view named
another method's parameters. These tests bind the config and an event recorder on a real ChromaDB-backed
EpisodicMemory under tmp_path and recall through the public API. Every test asserts its premise first. R8 pins the
Captain's retirement of the correlation-id rule (2026-11-18; AD-1360, #1828, restores it). R9 pins the semantic gate,
including hybrid fusion's hydration. The startup binding and the store gate are tests/test_bf938_ad607_binding.py (M2).

Anchor weights (memory_security._DEFAULT_ANCHOR_WEIGHTS): temporal (watch_section) 0.25, social (trigger_agent)
0.25, causal (trigger_type) 0.15.
"""

from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

import probos.cognitive.memory_security as memory_security
from probos.cognitive.episodic import EpisodicMemory
from probos.cognitive.memory_security import validate_provenance
from probos.config import MemorySecurityConfig
from probos.events import EventType
from probos.types import AnchorFrame, Episode, MemorySource

# Long ago, so BF-039's last-hour rate limit never sees these episodes (as tests/test_ad1340_s1_eviction.py does).
_T0 = 1_700_000_000.0
_AGENT = "agent-a"
_QUERY = "coolant loop reading"
_FORGED = "bf938-forged"
_KEPT = frozenset({"bf938-clean-0", "bf938-clean-1", "bf938-reflection"})
_ALL = _KEPT | {_FORGED}


class _Recorder:
    """Every (event_type, payload) the memory emits."""

    def __init__(self) -> None:
        self.events: list[tuple[Any, dict[str, Any]]] = []

    def __call__(self, event_type: Any, payload: dict[str, Any]) -> None:
        self.events.append((event_type, payload))

    def ids(self, event_type: Any) -> list[str]:
        return [payload["episode_id"] for kind, payload in self.events if kind == event_type]


def _raising_emitter(event_type: Any, payload: dict[str, Any]) -> None:
    raise RuntimeError("bf938: the emitter is down")


def _episode(episode_id: str, i: int, *, source: str = "direct", anchors: AnchorFrame | None = None) -> Episode:
    return Episode(
        id=episode_id,
        timestamp=_T0 + 600.0 * i,
        user_input=f"the engineering section reported the {_QUERY} {i} within limits",
        agent_ids=[_AGENT],
        source=source,
        correlation_id=f"corr-{episode_id}",
        anchors=anchors,
        outcomes=[{"intent": "report", "success": True}],
    )


def _anchored(episode_id: str, i: int, watch_section: str, trigger_type: str) -> Episode:
    # trigger_agent is a callsign, as producers write it (AnchorFrame.trigger_agent); never a sovereign id.
    return _episode(episode_id, i, anchors=AnchorFrame(
        watch_section=watch_section, trigger_type=trigger_type, trigger_agent="captain", department="engineering",
    ))


def _standard() -> list[Episode]:
    """Two intact episodes, a reflection (a source ProbOS writes) and one whose source ProbOS never writes."""
    return [
        _episode("bf938-clean-0", 0),
        _episode("bf938-clean-1", 1),
        _episode("bf938-reflection", 2, source=MemorySource.REFLECTION.value),
        _episode(_FORGED, 3, source="forged_source"),
    ]


@contextlib.asynccontextmanager
async def _memory(root: Path, episodes: list[Episode], **options: Any) -> AsyncIterator[EpisodicMemory]:
    em = EpisodicMemory(
        db_path=str(root / "chroma" / "episodes.db"), max_episodes=100, relevance_threshold=0.0, **options,
    )
    await em.start()
    try:
        assert await em.seed(episodes) == len(episodes)  # premise: every episode is in the store
        yield em
    finally:
        await em.stop()


async def _weighted(em: EpisodicMemory, **cues: Any) -> set[str]:
    return {rs.episode.id for rs in await em.recall_weighted(_AGENT, _QUERY, k=5, **cues)}


# --- R1, R2: a bound config completes, and with every flag false changes nothing ------------------------------


@pytest.mark.parametrize(
    ("flags", "expected"),
    [({}, _ALL), ({"enforce_provenance": True}, _KEPT), ({"enforce_recall": True}, _KEPT)],
    ids=["off", "enforce_provenance", "enforce_recall"],
)
async def test_a_bound_config_completes_a_non_empty_weighted_recall(
    tmp_path: Path, flags: dict[str, bool], expected: frozenset[str],
) -> None:
    recorder = _Recorder()
    async with _memory(tmp_path, _standard()) as em:
        assert await _weighted(em) == _ALL  # premise: unbound, every episode is recalled
        em.set_security_config(MemorySecurityConfig(**flags))
        em.set_security_event_emitter(recorder)
        assert await _weighted(em) == expected
    # Reported in every mode, for the forged episode only: a reflection's source is one ProbOS writes (A-2).
    assert recorder.ids(EventType.MEMORY_RECALL_ANOMALY) == [_FORGED]
    assert recorder.ids(EventType.MEMORY_PROVENANCE_GAP) == [_FORGED]


async def test_with_every_flag_false_binding_changes_no_weighted_recall_result(tmp_path: Path) -> None:
    async with _memory(tmp_path, _standard()) as em:
        unbound = await em.recall_weighted(_AGENT, _QUERY, k=5)
        assert {rs.episode.id for rs in unbound} == _ALL  # premise: the forged episode is among them
        em.set_security_config(MemorySecurityConfig())
        em.set_security_event_emitter(_Recorder())
        bound = await em.recall_weighted(_AGENT, _QUERY, k=5)
    assert [rs.episode.id for rs in bound] == [rs.episode.id for rs in unbound]
    assert [rs.composite_score for rs in bound] == pytest.approx([rs.composite_score for rs in unbound], rel=1e-6)


# --- R3: the weighted view compares the recall's cues, never the recalling agent (D2, A-1) ---------------------


@pytest.mark.parametrize(
    ("threshold", "episodes"),
    [
        (0.2, [_anchored("bf938-same", 0, "first_watch", "direct_message"),
               _anchored("bf938-other", 1, "second_watch", "direct_message")]),
        (0.1, [_anchored("bf938-same", 0, "first_watch", "direct_message"),
               _anchored("bf938-other", 1, "first_watch", "proactive_think")]),
    ],
    ids=["watch_section", "intent_type"],
)
async def test_the_weighted_gate_uses_the_recalls_own_cues_and_never_the_recalling_agent(
    tmp_path: Path, threshold: float, episodes: list[Episode],
) -> None:
    cues = {"query_watch_section": "first_watch", "intent_type": "direct_message"}
    recorder = _Recorder()
    async with _memory(tmp_path, episodes) as em:
        assert await _weighted(em, **cues) == {"bf938-same", "bf938-other"}  # premise: both recalled unbound
        em.set_security_config(MemorySecurityConfig(enforce_recall=True, anchor_mismatch_threshold=threshold))
        em.set_security_event_emitter(recorder)
        assert await _weighted(em, **cues) == {"bf938-same"}
    assert recorder.ids(EventType.MEMORY_ANCHOR_MISMATCH) == ["bf938-other"]


# --- R4: every MemorySource value is a known source (A-2) -------------------------------------------------------


@pytest.mark.parametrize("source", [member.value for member in MemorySource])
def test_every_memory_source_probos_writes_passes_the_provenance_check(source: str) -> None:
    episode = Episode(agent_ids=[_AGENT], source=source, correlation_id="corr-1")
    assert validate_provenance(episode) == (True, "")


# --- R5, R6: a raising emitter or validator never breaks recall ----------------------------------------------------


@pytest.mark.parametrize(
    ("flags", "expected"),
    [({}, _ALL), ({"enforce_provenance": True}, _KEPT)],
    ids=["off", "enforce_provenance"],
)
async def test_an_emitter_that_raises_never_breaks_weighted_recall(
    tmp_path: Path, flags: dict[str, bool], expected: frozenset[str],
) -> None:
    async with _memory(tmp_path, _standard()) as em:
        em.set_security_config(MemorySecurityConfig(**flags))
        em.set_security_event_emitter(_raising_emitter)
        assert await _weighted(em) == expected


async def test_a_validator_that_raises_never_breaks_weighted_recall(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _raise(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("bf938: the validator is down")

    async with _memory(tmp_path, _standard()) as em:
        em.set_security_config(MemorySecurityConfig(enforce_provenance=True))
        assert await _weighted(em) == _KEPT  # premise: the bound gate drops the forged episode
        monkeypatch.setattr(memory_security, "validate_recall_result", _raise)
        assert await _weighted(em) == _ALL  # AD-607's design: the verdict fails open (logged at DEBUG)


# --- R7: anchor recall never compares the recalling agent (A-1) --------------------------------------------------


async def test_anchor_recall_never_compares_the_recalling_agent_with_who_drove_the_episode(tmp_path: Path) -> None:
    episodes = [
        _anchored("bf938-a", 0, "first_watch", "direct_message"),
        _anchored("bf938-b", 1, "first_watch", "direct_message"),
    ]
    recorder = _Recorder()
    async with _memory(tmp_path, episodes) as em:
        premise = await em.recall_by_anchor(department="engineering", agent_id=_AGENT)
        assert {episode.id for episode in premise} == {"bf938-a", "bf938-b"}  # premise: both recalled unbound
        em.set_security_config(MemorySecurityConfig(enforce_recall=True, anchor_mismatch_threshold=0.2))
        em.set_security_event_emitter(recorder)
        recalled = await em.recall_by_anchor(department="engineering", agent_id=_AGENT)
    assert {episode.id for episode in recalled} == {"bf938-a", "bf938-b"}
    assert recorder.events == []


# --- R8: the retired correlation-id rule (the Captain's decision of 2026-11-18; AD-1360, #1828) ----------------


async def test_a_direct_episode_without_a_correlation_id_is_neither_reported_nor_dropped(tmp_path: Path) -> None:
    bare = replace(_episode("bf938-bare", 4), correlation_id="")
    recorder = _Recorder()
    async with _memory(tmp_path, [*_standard(), bare]) as em:
        assert await _weighted(em) == _ALL | {bare.id}  # premise: unbound, all five are recalled
        em.set_security_config(MemorySecurityConfig(enforce_provenance=True))
        em.set_security_event_emitter(recorder)
        assert await _weighted(em) == _KEPT | {bare.id}
    assert recorder.ids(EventType.MEMORY_PROVENANCE_GAP) == [_FORGED]


# --- R9: the semantic gate behind recall(), including hybrid fusion's hydration (D9) ------------------------------


@pytest.mark.parametrize("hybrid", [False, True], ids=["dense", "hybrid"])
async def test_semantic_recall_drops_a_forged_source_only_when_enforce_provenance_is_armed(
    tmp_path: Path, hybrid: bool,
) -> None:
    recorder = _Recorder()
    async with _memory(tmp_path, _standard(), hybrid_recall_enabled=hybrid) as em:
        assert {episode.id for episode in await em.recall(_QUERY, k=5)} == _ALL  # premise: unbound, all recalled
        if hybrid:  # premise: the sparse axis finds the forged episode, so fusion would hydrate it
            assert _FORGED in {episode_id for episode_id, _rank in await em.keyword_search(_QUERY, k=15)}
        em.set_security_config(MemorySecurityConfig(enforce_provenance=True))
        em.set_security_event_emitter(recorder)
        assert {episode.id for episode in await em.recall(_QUERY, k=5)} == _KEPT
    # Hybrid gates the dense candidate and the hydrated copy, so the forged episode may be reported twice (G9).
    assert set(recorder.ids(EventType.MEMORY_PROVENANCE_GAP)) == {_FORGED}
