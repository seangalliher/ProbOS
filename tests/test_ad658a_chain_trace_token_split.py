"""AD-658a: Chain trace token I/O split — tests."""

from __future__ import annotations

import dataclasses
from unittest.mock import AsyncMock, MagicMock

import aiosqlite
import pytest

from probos.cognitive.chain_trace import ChainExecutionTrace
from probos.cognitive.journal import CognitiveJournal
from probos.cognitive.sub_task import SubTaskResult, SubTaskType


# ---------------------------------------------------------------------------
# Section 1 — Frozen-dataclass field additions
# ---------------------------------------------------------------------------

def test_sub_task_result_token_split_defaults_zero() -> None:
    """AD-658a: SubTaskResult adds prompt_tokens / completion_tokens (default 0)."""
    r = SubTaskResult(sub_task_type=SubTaskType.ANALYZE, name="x")
    assert r.prompt_tokens == 0
    assert r.completion_tokens == 0
    # tokens_used remains the canonical sum-style field
    assert r.tokens_used == 0
    # frozen contract preserved
    with pytest.raises(dataclasses.FrozenInstanceError):
        r.prompt_tokens = 10  # type: ignore[misc]


def test_chain_execution_trace_token_split_defaults_and_round_trip() -> None:
    """AD-658a: ChainExecutionTrace exposes the split + to_dict round-trip."""
    trace = ChainExecutionTrace(
        chain_id="c", step_index=0, step_name="x",
        sub_task_type="analyze", tier="standard",
        tokens_used=128, prompt_tokens=80, completion_tokens=48,
    )
    assert trace.prompt_tokens == 80
    assert trace.completion_tokens == 48
    assert trace.tokens_used == 128
    d = trace.to_dict()
    assert d["prompt_tokens"] == 80
    assert d["completion_tokens"] == 48
    assert d["tokens_used"] == 128
    # Defaults preserved when omitted
    bare = ChainExecutionTrace(
        chain_id="c", step_index=0, step_name="x",
        sub_task_type="analyze", tier="standard",
    )
    assert bare.prompt_tokens == 0
    assert bare.completion_tokens == 0
    # Round-trip from dict
    again = ChainExecutionTrace(**d)
    assert again == trace


# ---------------------------------------------------------------------------
# Section 2 — Journal record + read round-trip with split
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_journal_record_chain_trace_persists_token_split(tmp_path) -> None:
    """AD-658a: record_chain_trace binds prompt_tokens / completion_tokens
    and get_recent_chain_traces returns them via SELECT * round-trip."""
    db_path = str(tmp_path / "j.db")
    journal = CognitiveJournal(db_path=db_path)
    await journal.start()
    try:
        trace = ChainExecutionTrace(
            chain_id="abc", step_index=0, step_name="analyze",
            sub_task_type="analyze", tier="fast",
            tokens_used=128, prompt_tokens=80, completion_tokens=48,
            success=True, started_at=10.0,
        )
        await journal.record_chain_trace(trace)
        rows = await journal.get_recent_chain_traces(limit=10)
        assert len(rows) == 1
        row = rows[0]
        assert row["tokens_used"] == 128
        assert row["prompt_tokens"] == 80
        assert row["completion_tokens"] == 48
    finally:
        await journal.stop()


# ---------------------------------------------------------------------------
# Section 3 — Warm-boot ALTER TABLE migration
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_journal_warm_boot_adds_split_columns_for_pre_ad658a_db(tmp_path) -> None:
    """AD-658a: warm-boot DB created without the new columns is migrated
    by journal.start() via idempotent ALTER TABLE; subsequent INSERT of a
    trace with prompt_tokens / completion_tokens succeeds."""
    db_path = str(tmp_path / "warm.db")

    # 1. Create a pre-AD-658a chain_traces table — same shape as AD-658
    #    minus the two new columns.
    pre_ad658a_schema = """
    CREATE TABLE chain_traces (
        chain_id            TEXT NOT NULL,
        step_index          INTEGER NOT NULL,
        step_name           TEXT NOT NULL,
        sub_task_type       TEXT NOT NULL,
        tier                TEXT NOT NULL DEFAULT 'standard',
        chain_source        TEXT NOT NULL DEFAULT '',
        agent_id            TEXT NOT NULL DEFAULT '',
        agent_type          TEXT NOT NULL DEFAULT '',
        intent              TEXT NOT NULL DEFAULT '',
        intent_id           TEXT NOT NULL DEFAULT '',
        started_at          REAL NOT NULL DEFAULT 0.0,
        duration_ms         REAL NOT NULL DEFAULT 0.0,
        tokens_used         INTEGER NOT NULL DEFAULT 0,
        success             INTEGER NOT NULL DEFAULT 1,
        error_truncated     TEXT NOT NULL DEFAULT '',
        context_keys_declared INTEGER NOT NULL DEFAULT 0,
        context_keys_passed   INTEGER NOT NULL DEFAULT 0,
        context_filter_applied INTEGER NOT NULL DEFAULT 0,
        communication_context TEXT,
        chain_trust_band      TEXT,
        trust_score           REAL,
        boot_camp_active      INTEGER NOT NULL DEFAULT 0,
        from_captain          INTEGER NOT NULL DEFAULT 0,
        is_dm                 INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (chain_id, step_index)
    );
    """
    async with aiosqlite.connect(db_path) as conn:
        await conn.executescript(pre_ad658a_schema)
        await conn.commit()

    # 2. Boot the journal — start() must idempotently add the split columns.
    journal = CognitiveJournal(db_path=db_path)
    await journal.start()
    try:
        # 3. Verify the columns now exist via PRAGMA table_info.
        async with aiosqlite.connect(db_path) as conn:
            cursor = await conn.execute("PRAGMA table_info(chain_traces)")
            cols = {row[1] for row in await cursor.fetchall()}
        assert "prompt_tokens" in cols
        assert "completion_tokens" in cols

        # 4. INSERT a trace with the split fields populated.
        trace = ChainExecutionTrace(
            chain_id="warm", step_index=0, step_name="x",
            sub_task_type="analyze", tier="standard",
            tokens_used=10, prompt_tokens=7, completion_tokens=3,
        )
        await journal.record_chain_trace(trace)
        rows = await journal.get_recent_chain_traces()
        assert len(rows) == 1
        assert rows[0]["prompt_tokens"] == 7
        assert rows[0]["completion_tokens"] == 3
        assert rows[0]["tokens_used"] == 10
    finally:
        await journal.stop()


@pytest.mark.asyncio
async def test_journal_warm_boot_migration_is_idempotent(tmp_path) -> None:
    """AD-658a: starting twice on the same DB does not raise — ALTER TABLE
    is wrapped in try/except OperationalError per the AD-660b precedent."""
    db_path = str(tmp_path / "twice.db")
    j1 = CognitiveJournal(db_path=db_path)
    await j1.start()
    await j1.stop()
    # Second boot must succeed even though the columns already exist.
    j2 = CognitiveJournal(db_path=db_path)
    await j2.start()
    try:
        async with aiosqlite.connect(db_path) as conn:
            cursor = await conn.execute("PRAGMA table_info(chain_traces)")
            cols = {row[1] for row in await cursor.fetchall()}
        assert "prompt_tokens" in cols
        assert "completion_tokens" in cols
    finally:
        await j2.stop()


# ---------------------------------------------------------------------------
# Section 4 — Executor emit-site forwards split from SubTaskResult
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_executor_chain_trace_emission_forwards_token_split() -> None:
    """AD-658a: when a SubTask handler returns a SubTaskResult populated with
    prompt_tokens / completion_tokens, the chain harness emits a
    ChainExecutionTrace carrying the same split. Mirrors the AD-658 executor
    emission test pattern (MagicMock journal; assert on awaited trace object)."""
    from probos.cognitive.sub_task import (
        SubTaskChain,
        SubTaskExecutor,
        SubTaskSpec,
    )

    async def handler(spec, ctx, prior):
        return SubTaskResult(
            sub_task_type=spec.sub_task_type, name=spec.name,
            tokens_used=200, prompt_tokens=140, completion_tokens=60,
            duration_ms=12.0, success=True, tier_used="standard",
        )

    executor = SubTaskExecutor()
    executor.register_handler(SubTaskType.ANALYZE, handler)
    chain = SubTaskChain(
        steps=[SubTaskSpec(
            sub_task_type=SubTaskType.ANALYZE,
            name="step-0", prompt_template="t",
            context_keys=("query",),
        )],
        source="skill",
    )
    journal = MagicMock()
    journal.record = AsyncMock()
    journal.record_chain_trace = AsyncMock()

    await executor.execute(
        chain, {"query": "X"},
        agent_id="agent-1", agent_type="counselor",
        intent="reply", intent_id="int-9",
        journal=journal,
    )

    journal.record_chain_trace.assert_awaited_once()
    trace = journal.record_chain_trace.await_args.args[0]
    assert isinstance(trace, ChainExecutionTrace)
    assert trace.tokens_used == 200
    assert trace.prompt_tokens == 140
    assert trace.completion_tokens == 60
