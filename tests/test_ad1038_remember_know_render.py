"""AD-1038 (Oracle recall epic, #987): live remember/know render — surface the
agent's OWN AD-979f Tulving remember/know ``recall_type`` for the live query into
its response as a gap-safe, instructions-first metacognitive cue.

Render/gate ONLY, DEFAULT-OFF, byte-identical-when-OFF. Reuses the AD-981b shared
sovereign ``_recall_confidence_probe`` (one round-trip drives both the AD-981b
honest-absence band cue and the AD-1038 remember/know cue). DD-4 precedence: on a
weak/none FoK band the AD-981b honest-absence cue WINS and AD-1038 suppresses
"know". No episodic.py / ranking / classifier / consensus change. The issue's Q3
"know"-down-weighting in consensus is DEFERRED to AD-1039.

BF-287 discipline: REAL ``EpisodicMemory`` on ``tmp_path`` with real ONNX MiniLM
embeddings at the store boundary (NOT MagicMock). The requesting agent is a tiny
``_Holder`` _Fake* stub carrying only the two attributes the helpers read
(``id`` / ``_runtime``) plus the ``_remember_know_note`` staticmethod the segment
helper calls; the runtime is a ``SimpleNamespace`` of real subsystems.

Deterministic fixtures (proven in the AD-1038 build probe and AD-979f): a default
store with typing ON, a verbatim self-query yields a ``strong`` band; a grounded
anchor frame (channel/trigger_agent/participants/source_timestamp) + ``source
="direct"`` classifies as ``remember``; ``anchors=None`` is preserved through the
store round-trip and classifies as ``know``.
"""
from __future__ import annotations

import inspect
from pathlib import Path
from types import SimpleNamespace

import pytest

from probos.cognitive.cognitive_agent import CognitiveAgent
from probos.cognitive.decomposer import is_capability_gap
from probos.cognitive.episodic import EpisodicMemory, remember_know_phrase
from probos.config import MemoryConfig
from probos.types import AnchorFrame, Episode

# A distinctive grounded recollection (verbatim query -> strong band; grounded
# anchors + direct source -> "remember").
REMEMBER_TEXT = (
    "The captain authorized the warp core ejection drill on stardate 47988 precisely."
)
# A distinctive ungrounded recollection (verbatim query -> strong band; no anchor
# frame -> familiarity without episodic grounding -> "know").
KNOW_TEXT = (
    "The replicator pattern buffer holds three thousand recipes in cold storage."
)


def _grounded_anchors() -> AnchorFrame:
    """Maximally-grounded anchor frame (every grounding field populated) so the
    AD-979f classifier yields ``remember`` on a strong band."""
    return AnchorFrame(
        channel="dm",
        trigger_agent="captain",
        participants=["captain"],
        source_timestamp=123.0,
    )


class _Holder:
    """Minimal requesting-agent stand-in (NOT a MagicMock). The AD-1038 helpers
    read ONLY ``self._runtime`` (the probe) and ``self._remember_know_note`` (the
    segment helper, a staticmethod). Nothing else is touched.
    """

    _remember_know_note = staticmethod(CognitiveAgent._remember_know_note)
    # The AD-981b band delegator (exercised by test_band_delegator_unchanged)
    # now routes through the shared probe, so the stub must expose it too.
    _recall_confidence_probe = CognitiveAgent._recall_confidence_probe

    def __init__(self, agent_id: str = "yeoman", runtime=None) -> None:
        self.id = agent_id
        self._runtime = runtime


@pytest.fixture
async def typed_em(tmp_path: Path):
    """Default store with remember/know typing ON: a verbatim self-query yields a
    ``strong`` band and a populated ``recall_type``."""
    em = EpisodicMemory(
        db_path=str(tmp_path / "ad1038_typed.db"),
        remember_know_typing_enabled=True,
    )
    await em.start()
    yield em
    try:
        await em.stop()
    except Exception:
        pass


def _seg(holder: _Holder):
    """Bind the unbound ``_remember_know_segment`` to a holder (mirrors the AD-981b
    test access pattern)."""
    return CognitiveAgent._remember_know_segment.__get__(holder)


# --------------------------------------------------------------------------
# Pure note (no I/O)
# --------------------------------------------------------------------------


def test_note_remember_is_instructions_first_and_gap_safe() -> None:
    note = CognitiveAgent._remember_know_note("remember")
    assert "REMEMBER" in note
    # MUST NOT read as a capability gap (the _CAPABILITY_GAP_RE / self-mod trap).
    assert not is_capability_gap(note)


def test_note_know_is_gap_safe() -> None:
    note = CognitiveAgent._remember_know_note("know")
    assert "KNOW" in note
    assert "familiar" in note
    assert not is_capability_gap(note)


def test_note_none_and_empty_are_blank() -> None:
    assert CognitiveAgent._remember_know_note("none") == ""
    assert CognitiveAgent._remember_know_note("") == ""


def test_shipped_formatter_contrast_justifies_render_layer() -> None:
    # DD-3: the SHIPPED AD-979f "know" phrase trips the gap regex (its text
    # contains "can't"); the AD-1038 render-layer note does NOT. This documents
    # why the render layer uses its own gap-safe note instead of reusing
    # remember_know_phrase. (The first assert was confirmed against live code.)
    assert is_capability_gap(remember_know_phrase("know"))
    assert not is_capability_gap(CognitiveAgent._remember_know_note("know"))


# --------------------------------------------------------------------------
# Render-decision segment (no I/O) — byte-identical-OFF proof
# --------------------------------------------------------------------------


def test_segment_remember_renders_cue() -> None:
    seg = _seg(_Holder())({"_recall_recall_type": "remember"})
    assert isinstance(seg, list)
    assert any("REMEMBER" in line for line in seg)


def test_segment_know_renders_cue() -> None:
    seg = _seg(_Holder())({"_recall_recall_type": "know"})
    assert isinstance(seg, list)
    assert any("KNOW" in line for line in seg)


def test_segment_none_empty_missing_are_none() -> None:
    seg = _seg(_Holder())
    # the byte-identical-OFF render proof: no usable recall_type -> no segment.
    assert seg({"_recall_recall_type": "none"}) is None
    assert seg({"_recall_recall_type": ""}) is None
    assert seg({}) is None


def test_dd4_precedence_weak_none_defers_to_981b() -> None:
    seg = _seg(_Holder())
    # DD-4: a weak/none honest-absence band present -> AD-981b cue wins -> None.
    assert seg({"_recall_recall_type": "know", "_recall_fok_band": "weak"}) is None
    assert seg({"_recall_recall_type": "know", "_recall_fok_band": "none"}) is None
    # a strong band carries no honest-absence cue to contradict -> AD-1038 renders.
    strong = seg({"_recall_recall_type": "know", "_recall_fok_band": "strong"})
    assert strong is not None and any("KNOW" in line for line in strong)
    # band key absent (AD-981b off) -> nothing to contradict -> AD-1038 renders.
    nokey = seg({"_recall_recall_type": "know"})
    assert nokey is not None and any("KNOW" in line for line in nokey)


# --------------------------------------------------------------------------
# Live probe (real runtime)
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_probe_returns_remember_via_real_runtime(typed_em) -> None:
    await typed_em.store(
        Episode(
            user_input=REMEMBER_TEXT,
            agent_ids=["yeoman"],
            anchors=_grounded_anchors(),
            source="direct",
        )
    )
    runtime = SimpleNamespace(
        episodic_memory=typed_em,
        config=SimpleNamespace(
            memory=MemoryConfig(remember_know_typing_enabled=True)
        ),
    )
    holder = _Holder("yeoman", runtime)
    conf = await CognitiveAgent._recall_confidence_probe.__get__(holder)(
        query=REMEMBER_TEXT, mem_id="yeoman", k=5
    )
    assert conf is not None
    assert conf.band == "strong"
    assert conf.recall_type == "remember"


@pytest.mark.asyncio
async def test_probe_returns_know_for_ungrounded(typed_em) -> None:
    await typed_em.store(
        Episode(
            user_input=KNOW_TEXT,
            agent_ids=["yeoman"],
            anchors=None,
            source="direct",
        )
    )
    runtime = SimpleNamespace(
        episodic_memory=typed_em,
        config=SimpleNamespace(
            memory=MemoryConfig(remember_know_typing_enabled=True)
        ),
    )
    holder = _Holder("yeoman", runtime)
    conf = await CognitiveAgent._recall_confidence_probe.__get__(holder)(
        query=KNOW_TEXT, mem_id="yeoman", k=5
    )
    assert conf is not None
    assert conf.recall_type == "know"


@pytest.mark.asyncio
async def test_probe_missing_episodic_memory_returns_none() -> None:
    holder = _Holder("yeoman", SimpleNamespace())  # no episodic_memory attr
    conf = await CognitiveAgent._recall_confidence_probe.__get__(holder)(
        query="anything at all", mem_id="yeoman", k=5
    )
    assert conf is None


@pytest.mark.asyncio
async def test_band_delegator_unchanged(typed_em) -> None:
    # AD-981b regression guard: the band-only delegator still returns "strong"
    # for a verbatim self-query even with the new probe underneath it.
    await typed_em.store(
        Episode(
            user_input=REMEMBER_TEXT,
            agent_ids=["yeoman"],
            anchors=_grounded_anchors(),
            source="direct",
        )
    )
    runtime = SimpleNamespace(
        episodic_memory=typed_em,
        config=SimpleNamespace(
            memory=MemoryConfig(remember_know_typing_enabled=True)
        ),
    )
    holder = _Holder("yeoman", runtime)
    band = await CognitiveAgent._recall_confidence_band.__get__(holder)(
        query=REMEMBER_TEXT, mem_id="yeoman", k=5
    )
    assert band == "strong"


@pytest.mark.asyncio
async def test_typing_off_yields_empty_recall_type(tmp_path: Path) -> None:
    # byte-identical-OFF at the store: no flag -> recall_type "" -> segment None.
    em = EpisodicMemory(db_path=str(tmp_path / "ad1038_off.db"))
    await em.start()
    try:
        await em.store(
            Episode(
                user_input=REMEMBER_TEXT,
                agent_ids=["yeoman"],
                anchors=_grounded_anchors(),
                source="direct",
            )
        )
        _eps, conf = await em.recall_for_agent_with_confidence(
            "yeoman", REMEMBER_TEXT, 5
        )
        assert conf.recall_type == ""
        seg = _seg(_Holder())({"_recall_recall_type": conf.recall_type})
        assert seg is None
    finally:
        try:
            await em.stop()
        except Exception:
            pass


# --------------------------------------------------------------------------
# End-to-end render (live conf -> rendered cue segment)
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_live_remember_composes_into_cue_segment(typed_em) -> None:
    await typed_em.store(
        Episode(
            user_input=REMEMBER_TEXT,
            agent_ids=["yeoman"],
            anchors=_grounded_anchors(),
            source="direct",
        )
    )
    runtime = SimpleNamespace(
        episodic_memory=typed_em,
        config=SimpleNamespace(
            memory=MemoryConfig(remember_know_typing_enabled=True)
        ),
    )
    holder = _Holder("yeoman", runtime)
    conf = await CognitiveAgent._recall_confidence_probe.__get__(holder)(
        query=REMEMBER_TEXT, mem_id="yeoman", k=5
    )
    assert conf.recall_type == "remember"
    seg = _seg(holder)({"_recall_recall_type": conf.recall_type})
    assert seg is not None
    joined = "\n".join(seg)
    assert "REMEMBER" in joined
    assert not is_capability_gap(joined)


@pytest.mark.asyncio
async def test_live_know_composes_into_cue_segment(typed_em) -> None:
    await typed_em.store(
        Episode(
            user_input=KNOW_TEXT,
            agent_ids=["yeoman"],
            anchors=None,
            source="direct",
        )
    )
    runtime = SimpleNamespace(
        episodic_memory=typed_em,
        config=SimpleNamespace(
            memory=MemoryConfig(remember_know_typing_enabled=True)
        ),
    )
    holder = _Holder("yeoman", runtime)
    conf = await CognitiveAgent._recall_confidence_probe.__get__(holder)(
        query=KNOW_TEXT, mem_id="yeoman", k=5
    )
    assert conf.recall_type == "know"
    seg = _seg(holder)({"_recall_recall_type": conf.recall_type})
    assert seg is not None
    joined = "\n".join(seg)
    assert "KNOW" in joined
    assert not is_capability_gap(joined)


# --------------------------------------------------------------------------
# Structural wiring guards
# --------------------------------------------------------------------------


def test_build_user_message_renders_remember_know_at_both_sites() -> None:
    src = inspect.getsource(CognitiveAgent._build_user_message)
    # one injection per episodic render branch (DM + WR), mirroring AD-981b.
    assert src.count("_remember_know_segment(observation)") >= 2
    assert '_emit("remember_know"' in src


def test_probe_block_gates_recall_type_on_typing_flag() -> None:
    src = inspect.getsource(CognitiveAgent._recall_relevant_memories)
    assert "_recall_recall_type" in src
    assert "remember_know_typing_enabled" in src
    assert "_recall_confidence_probe" in src
