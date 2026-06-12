"""AD-981a (Oracle-recall live-wiring): surface the AD-979a Feeling-of-Knowing
band on the LIVE sovereign recall path.

The AD-979a FoK signal + AD-979c hybrid axis were built into
``recall_with_confidence`` / ``recall`` — but the crew's live recall goes through
``recall_for_agent`` (sovereign, agent-scoped), which never produced the signal.
So the "invisible miss" the crew flagged (a relevant-ish memory just under the
bar) was invisible on the very path that matters. AD-981a wires it in:
``recall_for_agent_with_confidence`` is the new single source of truth (it
surfaces an AGENT-SCOPED band over the agent's own candidates), ``recall_for_agent``
is a byte-identical shim over it, and a default-off ``recall_fok_logging_enabled``
flag emits the band per call so a live multi-agent session is a calibration tool.

BF-287 discipline: a REAL ``EpisodicMemory`` on ``tmp_path`` with real ONNX
MiniLM embeddings (NOT MagicMock). Band assertions are made *consistent with the
pure classifier* rather than hard-coding an embedding-fragile number.
"""
from __future__ import annotations

import logging
from pathlib import Path

import pytest

from probos.cognitive.episodic import (
    EpisodicMemory,
    RecallConfidence,
    classify_recall_confidence,
)
from probos.config import MemoryConfig
from probos.types import Episode


@pytest.fixture
async def memory(tmp_path: Path):
    """FoK logging OFF (the default) — the conservative baseline."""
    em = EpisodicMemory(db_path=str(tmp_path / "ad981a.db"))
    await em.start()
    yield em
    try:
        await em.stop()
    except Exception:
        pass


@pytest.fixture
async def memory_fok(tmp_path: Path):
    """FoK logging ON — the calibration-tool configuration."""
    em = EpisodicMemory(
        db_path=str(tmp_path / "ad981a_fok.db"),
        recall_fok_logging_enabled=True,
    )
    await em.start()
    yield em
    try:
        await em.stop()
    except Exception:
        pass


# --------------------------------------------------------------------------
# config default
# --------------------------------------------------------------------------


def test_config_flag_defaults_off():
    # Conservative: zero overhead + zero new log noise out of the box.
    assert MemoryConfig().recall_fok_logging_enabled is False


# --------------------------------------------------------------------------
# recall_for_agent_with_confidence — the single source of truth
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_empty_store_is_fast_absence(memory):
    episodes, conf = await memory.recall_for_agent_with_confidence(
        "yeoman", "anything at all", k=5
    )
    assert episodes == []
    assert isinstance(conf, RecallConfidence)
    assert conf.band == "none"
    assert conf.candidate_count == 0
    assert conf.best_similarity == 0.0


@pytest.mark.asyncio
async def test_strong_self_query_returns_episode_and_strong_band(memory):
    text = "The Captain approved the database migration on Tuesday afternoon."
    await memory.store(Episode(user_input=text, agent_ids=["yeoman"]))
    episodes, conf = await memory.recall_for_agent_with_confidence("yeoman", text, k=5)
    assert conf.band == "strong"
    assert conf.best_similarity >= 0.7
    assert conf.candidate_count >= 1
    assert episodes, "a strong agent recall should return the matching episode"
    assert any("migration" in e.user_input for e in episodes)


@pytest.mark.asyncio
async def test_band_consistent_with_pure_classifier(memory):
    await memory.store(Episode(user_input="Photosynthesis converts light to sugar.", agent_ids=["yeoman"]))
    await memory.store(Episode(user_input="The reactor core temperature is nominal.", agent_ids=["yeoman"]))
    for q in ("quantum entanglement of distant particles", "reactor core temperature"):
        _episodes, conf = await memory.recall_for_agent_with_confidence("yeoman", q, k=3)
        expected = classify_recall_confidence(
            conf.best_similarity,
            conf.candidate_count,
            relevance_threshold=memory.relevance_threshold,
            weak_floor=memory._recall_confidence_weak_floor,
        )
        assert conf.band == expected


@pytest.mark.asyncio
async def test_band_is_agent_scoped_not_global(memory):
    # The counselor owns a strongly-matching memory; the yeoman owns only an
    # unrelated one. Querying the counselor's topic AS the yeoman must NOT yield
    # a strong band — the signal is the yeoman's OWN accessibility, not the
    # global best (which belongs to the counselor).
    await memory.store(Episode(
        user_input="Photosynthesis converts light energy into chemical sugar.",
        agent_ids=["counselor"],
    ))
    await memory.store(Episode(
        user_input="The warp core plasma injector was realigned.",
        agent_ids=["yeoman"],
    ))
    _episodes, conf = await memory.recall_for_agent_with_confidence(
        "yeoman", "photosynthesis chlorophyll light reaction", k=5
    )
    assert conf.band != "strong"
    assert conf.best_similarity < memory.relevance_threshold
    # The counselor, who owns the matching memory, DOES get a strong band.
    _c_eps, c_conf = await memory.recall_for_agent_with_confidence(
        "counselor", "photosynthesis converts light into sugar", k=5
    )
    assert c_conf.band == "strong"


# --------------------------------------------------------------------------
# recall_for_agent shim — byte-identical episodes
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_shim_returns_same_episodes_as_core(memory):
    for i in range(4):
        await memory.store(Episode(
            user_input=f"Maintenance log entry {i}: coolant valve {i} inspected.",
            agent_ids=["yeoman"],
        ))
    query = "coolant valve inspection maintenance"
    shim_eps = await memory.recall_for_agent("yeoman", query, k=3)
    core_eps, _conf = await memory.recall_for_agent_with_confidence("yeoman", query, k=3)
    assert [e.id for e in shim_eps] == [e.id for e in core_eps]


@pytest.mark.asyncio
async def test_fok_flag_does_not_change_recalled_episodes(memory, memory_fok):
    # The FoK flag is observability only — the recalled episode set must be
    # identical whether logging is on or off (same stored content + query).
    for em in (memory, memory_fok):
        for i in range(3):
            await em.store(Episode(
                user_input=f"Shift report {i}: sensor array {i} calibrated to spec.",
                agent_ids=["yeoman"],
            ))
    q = "sensor array calibration shift report"
    off_eps = await memory.recall_for_agent("yeoman", q, k=3)
    on_eps = await memory_fok.recall_for_agent("yeoman", q, k=3)
    assert [e.user_input for e in off_eps] == [e.user_input for e in on_eps]


# --------------------------------------------------------------------------
# FoK logging gate
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_flag_off_emits_no_fok_log(memory, caplog):
    await memory.store(Episode(user_input="Routine diagnostic completed.", agent_ids=["yeoman"]))
    with caplog.at_level(logging.INFO, logger="probos.cognitive.episodic"):
        await memory.recall_for_agent("yeoman", "diagnostic", k=3)
    assert not any("AD-981a recall FoK" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_flag_on_emits_fok_log_with_band(memory_fok, caplog):
    text = "The away team secured the perimeter at dawn."
    await memory_fok.store(Episode(user_input=text, agent_ids=["yeoman"]))
    with caplog.at_level(logging.INFO, logger="probos.cognitive.episodic"):
        await memory_fok.recall_for_agent("yeoman", text, k=3)
    fok_logs = [r for r in caplog.records if "AD-981a recall FoK" in r.message]
    assert fok_logs, "FoK logging enabled should emit a per-recall band line"
    rendered = fok_logs[0].getMessage()
    assert "agent=yeoman" in rendered
    assert "band=" in rendered


@pytest.mark.asyncio
async def test_fok_log_emitted_even_on_empty_recall(memory_fok, caplog):
    # An honest "I have nothing" is exactly what calibration wants to observe,
    # so the band is logged even when no episodes are returned.
    await memory_fok.store(Episode(user_input="Unrelated stored fact.", agent_ids=["counselor"]))
    with caplog.at_level(logging.INFO, logger="probos.cognitive.episodic"):
        eps = await memory_fok.recall_for_agent("yeoman", "something the yeoman never saw", k=3)
    assert eps == []
    assert any("AD-981a recall FoK" in r.message and "agent=yeoman" in r.getMessage()
               for r in caplog.records)
