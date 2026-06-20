"""AD-981b: surface the agent's OWN AD-981a Feeling-of-Knowing band for the live
query into its response, so a WEAK/NONE name-cued recall (the "Heidi" case —
"do you remember Heidi?" with no Heidi in the shard) drives an HONEST-ABSENCE
cue instead of the agent affirming + inventing provenance.

This reuses AD-981a's band (already computed unconditionally inside
``recall_for_agent_with_confidence``) via one extra sovereign probe, gated behind
the default-OFF ``MemoryConfig.recall_confidence_gating_enabled``. No episodic.py
change, no ranking change, no new recall mechanism.

BF-287 discipline: REAL ``EpisodicMemory`` on ``tmp_path`` with real ONNX MiniLM
embeddings at the store boundary (NOT MagicMock). The requesting agent is a tiny
``_Holder`` _Fake* stub carrying only the two attributes the helpers read
(``id`` / ``_runtime``) plus the ``_recall_confidence_note`` staticmethod the
segment helper calls; the runtime is a ``SimpleNamespace`` of real subsystems.

Deterministic band fixture (proven in AD-979d slice-2 / AD-981a):
``EpisodicMemory(relevance_threshold=0.99, recall_confidence_weak_floor=0.0)``
classifies any owned sub-0.99 candidate (count > 0) as ``weak``; the verbatim
query against a default store is ``strong``.
"""
from __future__ import annotations

import inspect
from pathlib import Path
from types import SimpleNamespace

import pytest

from probos.cognitive.cognitive_agent import CognitiveAgent
from probos.cognitive.decomposer import is_capability_gap
from probos.cognitive.episodic import EpisodicMemory
from probos.config import MemoryConfig
from probos.types import Episode

# The "Heidi" name-cue: nothing about Heidi is in the shard (only Grim).
GRIM = "My dog, Grim, is a giant schnauzer."
HEIDI_QUERY = "do you remember anything about Heidi"


class _Holder:
    """Minimal requesting-agent stand-in (NOT a MagicMock). The AD-981b helpers
    read ONLY ``self._runtime`` (the band probe) and ``self._recall_confidence_note``
    (the segment helper, a staticmethod). Nothing else is touched.
    """

    _recall_confidence_note = staticmethod(CognitiveAgent._recall_confidence_note)

    def __init__(self, agent_id: str = "yeoman", runtime=None) -> None:
        self.id = agent_id
        self._runtime = runtime


@pytest.fixture
async def weak_em(tmp_path: Path):
    """Deterministic-weak store: any owned sub-0.99 candidate (count > 0)
    classifies as ``weak``; absence (count == 0) is ``none``."""
    em = EpisodicMemory(
        db_path=str(tmp_path / "ad981b_weak.db"),
        relevance_threshold=0.99,
        recall_confidence_weak_floor=0.0,
    )
    await em.start()
    yield em
    try:
        await em.stop()
    except Exception:
        pass


@pytest.fixture
async def strong_em(tmp_path: Path):
    """Default store: a verbatim self-query yields a ``strong`` band."""
    em = EpisodicMemory(db_path=str(tmp_path / "ad981b_strong.db"))
    await em.start()
    yield em
    try:
        await em.stop()
    except Exception:
        pass


# --------------------------------------------------------------------------
# 1. config default OFF -> no probe, no cue -> byte-identical
# --------------------------------------------------------------------------


def test_config_default_off() -> None:
    assert MemoryConfig().recall_confidence_gating_enabled is False


# --------------------------------------------------------------------------
# 2/3/4. the pure note: gap-regex-safe honest-absence cue for weak/none, "" else
# --------------------------------------------------------------------------


def test_note_weak_is_honest_absence_and_gap_safe() -> None:
    note = CognitiveAgent._recall_confidence_note("weak")
    assert "RECALL CONFIDENCE: WEAK" in note
    assert "nothing recorded" in note
    assert "do not invent" in note
    # MUST NOT read as a capability gap (the _CAPABILITY_GAP_RE / self-mod trap).
    assert not is_capability_gap(note)


def test_note_none_is_honest_absence_and_gap_safe() -> None:
    note = CognitiveAgent._recall_confidence_note("none")
    assert "RECALL CONFIDENCE: NONE" in note
    assert "nothing recorded" in note
    assert not is_capability_gap(note)


def test_note_strong_and_empty_are_blank() -> None:
    assert CognitiveAgent._recall_confidence_note("strong") == ""
    assert CognitiveAgent._recall_confidence_note("") == ""


# --------------------------------------------------------------------------
# 5/6. the render-decision segment: present for weak/none, None otherwise
#      (test 6 is the byte-identical-OFF render proof)
# --------------------------------------------------------------------------


def test_segment_weak_returns_cue() -> None:
    holder = _Holder()
    seg = CognitiveAgent._recall_confidence_segment.__get__(holder)(
        {"_recall_fok_band": "weak"}
    )
    assert isinstance(seg, list)
    assert any("RECALL CONFIDENCE: WEAK" in line for line in seg)


def test_segment_strong_and_missing_band_are_none() -> None:
    holder = _Holder()
    _seg = CognitiveAgent._recall_confidence_segment.__get__(holder)
    # strong band -> no cue text -> None
    assert _seg({"_recall_fok_band": "strong"}) is None
    # no _recall_fok_band key at all (the OFF path) -> None -> no emit
    assert _seg({}) is None


# --------------------------------------------------------------------------
# 7. THE REGRESSION: name-cued recall with nothing recorded -> weak/none band
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_heidi_name_cue_yields_weak_or_none_band(weak_em) -> None:
    await weak_em.store(Episode(user_input=GRIM, agent_ids=["yeoman"]))
    _eps, conf = await weak_em.recall_for_agent_with_confidence(
        "yeoman", HEIDI_QUERY, 5
    )
    # No Heidi anywhere -> the agent's own band must NOT be strong; it is the
    # weak (invisible-miss) or none (fast-absence) signal that drives the cue.
    assert conf.band in ("weak", "none")


# --------------------------------------------------------------------------
# 8. compose the regression band into the render-decision segment
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_heidi_band_composes_into_honest_absence_segment(weak_em) -> None:
    await weak_em.store(Episode(user_input=GRIM, agent_ids=["yeoman"]))
    _eps, conf = await weak_em.recall_for_agent_with_confidence(
        "yeoman", HEIDI_QUERY, 5
    )
    holder = _Holder()
    seg = CognitiveAgent._recall_confidence_segment.__get__(holder)(
        {"_recall_fok_band": conf.band}
    )
    assert seg is not None
    joined = "\n".join(seg)
    assert "RECALL CONFIDENCE:" in joined
    assert "nothing recorded" in joined
    assert not is_capability_gap(joined)


# --------------------------------------------------------------------------
# 9. the async probe via a real runtime (and the missing-em degrade path)
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_band_probe_returns_weak_via_real_runtime(weak_em) -> None:
    await weak_em.store(Episode(user_input=GRIM, agent_ids=["yeoman"]))
    runtime = SimpleNamespace(
        episodic_memory=weak_em,
        config=SimpleNamespace(
            memory=MemoryConfig(recall_confidence_gating_enabled=True)
        ),
    )
    holder = _Holder("yeoman", runtime)
    band = await CognitiveAgent._recall_confidence_band.__get__(holder)(
        query=HEIDI_QUERY, mem_id="yeoman", k=5
    )
    assert band == "weak"


@pytest.mark.asyncio
async def test_band_probe_missing_episodic_memory_returns_empty() -> None:
    holder = _Holder("yeoman", SimpleNamespace())  # no episodic_memory attr
    band = await CognitiveAgent._recall_confidence_band.__get__(holder)(
        query=HEIDI_QUERY, mem_id="yeoman", k=5
    )
    assert band == ""


# --------------------------------------------------------------------------
# 10. a genuine strong recall is unaffected -> no cue (no misfire)
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_strong_band_is_unaffected_and_emits_no_cue(strong_em) -> None:
    await strong_em.store(Episode(user_input=GRIM, agent_ids=["yeoman"]))
    _eps, conf = await strong_em.recall_for_agent_with_confidence(
        "yeoman", GRIM, 5
    )
    assert conf.band == "strong"
    holder = _Holder()
    seg = CognitiveAgent._recall_confidence_segment.__get__(holder)(
        {"_recall_fok_band": conf.band}
    )
    assert seg is None


# --------------------------------------------------------------------------
# 11/12. structural wiring guards
# --------------------------------------------------------------------------


def test_build_user_message_renders_cue_at_both_episodic_sites() -> None:
    src = inspect.getsource(CognitiveAgent._build_user_message)
    # one injection per branch (DM + WR)
    assert src.count("_recall_confidence_segment(observation)") >= 2
    assert '_emit("recall_confidence"' in src


def test_recall_relevant_memories_gates_probe_before_calling_it() -> None:
    src = inspect.getsource(CognitiveAgent._recall_relevant_memories)
    gate = src.find("recall_confidence_gating_enabled")
    probe = src.find("_recall_confidence_band")
    assert gate != -1, "the gating flag must be checked in _recall_relevant_memories"
    assert probe != -1, "the band probe must be called in _recall_relevant_memories"
    # the flag gate must precede the probe call (byte-identical-OFF guarantee)
    assert gate < probe
