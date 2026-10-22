"""BF-901 S2 (#1575): the journal records what each call cost, where the count came from, and the model that answered.

The contract is ``prompts/bf-901-s2-journal-token-provenance.md``. Every test but U9 and U12 writes through a real
``CognitiveJournal`` on ``tmp_path`` and reads the rows back through its own readers (``get_reasoning_chain``,
``get_recent_chain_traces``, ``get_token_usage``; U11 also ``get_token_usage_by``, ``get_token_usage_since`` and the
AD-617b hourly gate). U9 and U12 test the handlers' returned results, with no journal; U11 carries a replayed step
from a handler's result into the journal (review round 1, F1). The one-shot rows come from the real
``CognitiveAgent.decide`` -> ``_decide_via_llm`` (the agent
built as tests/test_cognitive_journal.py builds it, over a spec'd runtime mock); the chain rows from the real
``SubTaskExecutor`` and the real sub-task handlers. Stand-ins, named: the model client (``_OneShotClient``, a
``MockLLMClient`` that answers one scripted ``LLMResponse``), the procedural-memory lookup in U6, and in U8 a handler
whose first call never returns plus a no-wait ``asyncio.sleep`` (BF-183's 2 s back-off).

Mutants (the contract's section 10): J1, J2 U10; J3, C3, C4 U1; J4, S3 U7; C1 U3; C2 U4; C5 U5; C6 U6; S1, S2 U8;
H1-H8 U9; S4 U11; R1-R10 U12 (R4 and R5 also fail U11).
"""

from __future__ import annotations

import asyncio
import dataclasses
import time
import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from types import SimpleNamespace  # not a ProbOS class
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import aiosqlite
import pytest

from probos.cognitive.chain_trace import ChainExecutionTrace
from probos.cognitive.cognitive_agent import CognitiveAgent, _CACHE_HITS, _CACHE_MISSES, _DECISION_CACHES
from probos.cognitive.journal import CognitiveJournal
from probos.cognitive.llm_client import MockLLMClient
from probos.cognitive.sub_task import SubTaskChain, SubTaskExecutor, SubTaskResult, SubTaskSpec, SubTaskType
from probos.cognitive.sub_tasks.analyze import AnalyzeHandler
from probos.cognitive.sub_tasks.compose import ComposeHandler
from probos.cognitive.sub_tasks.evaluate import EvaluateHandler
from probos.cognitive.sub_tasks.reflect import ReflectHandler
from probos.config import CognitiveConfig, LLMRateConfig
from probos.crew_execution_usage import TOKEN_SOURCE_ESTIMATED, TOKEN_SOURCE_MEASURED
from probos.proactive import ProactiveCognitiveLoop
from probos.runtime import ProbOSRuntime
from probos.types import IntentDescriptor, LLMRequest, LLMResponse

SENT = "sent-model"
ANSWERED = "answered-model"
OBSERVATION = {"intent": "test", "params": {"q": "hello"}, "context": ""}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _TestAgent(CognitiveAgent):
    """tests/test_cognitive_journal.py's agent (copied: tests do not import each other)."""

    agent_type = "test_journal_agent"
    _handled_intents = {"test"}
    instructions = "You are a test agent."
    intent_descriptors = [IntentDescriptor(name="test", params={}, description="Test", tier="domain")]


class _OneShotClient(MockLLMClient):
    """Answers every request with one scripted response (its ``request_id`` set to the request's)."""

    def __init__(self, response: LLMResponse) -> None:
        super().__init__()
        self._response = response
        self.requests: list[LLMRequest] = []

    async def complete(self, request: LLMRequest, **_kwargs: Any) -> LLMResponse:
        self.requests.append(request)
        return dataclasses.replace(self._response, request_id=request.id)


class _OneReply:
    """A handler's ``llm_client``: answers every request with one response and records the requests."""

    def __init__(self, response: LLMResponse) -> None:
        self._response = response
        self.requests: list[LLMRequest] = []

    async def complete(self, request: LLMRequest, **_kwargs: Any) -> LLMResponse:
        self.requests.append(request)
        return self._response


@pytest.fixture(autouse=True)
def _clear_decision_caches() -> None:
    _DECISION_CACHES.clear()
    _CACHE_HITS.clear()
    _CACHE_MISSES.clear()


@pytest.fixture
async def journal(tmp_path: Path) -> AsyncIterator[CognitiveJournal]:
    j = CognitiveJournal(db_path=str(tmp_path / "cognitive_journal.db"))
    await j.start()
    try:
        yield j
    finally:
        await j.stop()


def _runtime(journal: CognitiveJournal, *, decision_cache: bool = False) -> Any:
    rt = MagicMock(spec=ProbOSRuntime)
    rt.cognitive_journal = journal
    if decision_cache:
        # BF-864: the decision cache is off unless configured on (tests/test_cognitive_journal.py, test 10).
        rt.config = SimpleNamespace(cognitive=CognitiveConfig(decision_cache_enabled=True))
    return rt


async def _rows(journal: CognitiveJournal, agent_id: str) -> list[dict[str, Any]]:
    return await journal.get_reasoning_chain(agent_id, limit=50)


def _len4(text: str) -> int:
    """AD-1142's estimate of one message: ``max(1, len(text) // 4)``, worked here, not imported."""
    return max(1, len(text) // 4)


# ---------------------------------------------------------------------------
# 1. The one-shot call (cognitive_agent.py, _decide_via_llm)
# ---------------------------------------------------------------------------


async def test_a_one_shot_call_records_an_estimate_where_the_provider_reported_zeros(journal: CognitiveJournal) -> None:
    """U1: the proxy's shape. The row's counts are the estimate, labelled, and it names the answering model."""
    reply = "z" * 400
    llm = _OneShotClient(LLMResponse(content=reply, model=SENT, answered_model=ANSWERED, usage_reported=True))
    agent = _TestAgent(llm_client=llm, runtime=_runtime(journal))

    await agent.decide(dict(OBSERVATION))

    (request,) = llm.requests
    assert request.messages is None  # premise: the prompt shape, so the estimate is system + user
    expected_prompt = (_len4(request.system_prompt) if request.system_prompt else 0) + _len4(request.prompt)
    (row,) = await _rows(journal, agent.id)
    assert row["token_source"] == TOKEN_SOURCE_ESTIMATED
    assert row["completion_tokens"] == _len4(reply)
    assert row["prompt_tokens"] == expected_prompt
    assert row["total_tokens"] == expected_prompt + _len4(reply)
    assert row["model"] == ANSWERED
    assert row["cached"] == 0
    assert row["success"] == 1


async def test_a_one_shot_call_records_measured_counts(journal: CognitiveJournal) -> None:
    """U2: reported counts are recorded as reported."""
    llm = _OneShotClient(
        LLMResponse(content="ok", model=SENT, tokens_used=150, prompt_tokens=100, completion_tokens=50, usage_reported=True),
    )
    agent = _TestAgent(llm_client=llm, runtime=_runtime(journal))

    await agent.decide(dict(OBSERVATION))

    (row,) = await _rows(journal, agent.id)
    assert (row["prompt_tokens"], row["completion_tokens"], row["total_tokens"]) == (100, 50, 150)
    assert row["token_source"] == TOKEN_SOURCE_MEASURED


@pytest.mark.parametrize(
    ("response", "model", "source", "success"),
    [
        pytest.param(
            LLMResponse(content="ok", model=SENT, answered_model=ANSWERED, tokens_used=9, usage_reported=True),
            ANSWERED, TOKEN_SOURCE_MEASURED, 1, id="answered",
        ),
        pytest.param(LLMResponse(content="ok", model=SENT, tokens_used=9, usage_reported=True), SENT, TOKEN_SOURCE_MEASURED, 1, id="sent"),
        pytest.param(LLMResponse(content="", model="", error="All LLM tiers unavailable"), "unknown", "", 0, id="error"),
    ],
)
async def test_a_one_shot_row_names_the_model_that_answered(
    journal: CognitiveJournal, response: LLMResponse, model: str, source: str, success: int,
) -> None:
    """U3: answered first, then the id sent, then ``unknown``; never empty."""
    agent = _TestAgent(llm_client=_OneShotClient(response), runtime=_runtime(journal))

    await agent.decide(dict(OBSERVATION))

    (row,) = await _rows(journal, agent.id)
    assert (row["model"], row["token_source"], row["success"]) == (model, source, success)


async def test_a_replay_row_is_cached_and_adds_nothing_to_token_usage(journal: CognitiveJournal) -> None:
    """U4: a client cache replay carries the original call's count and ``cached=True``; recorded as cached, the
    readers' ``cached = 0`` filter keeps it out of spend. The control call that follows is counted."""
    replay = LLMResponse(content="cached text", model=SENT, tokens_used=500, cached=True)
    agent = _TestAgent(llm_client=_OneShotClient(replay), runtime=_runtime(journal))

    await agent.decide(dict(OBSERVATION))

    (row,) = await _rows(journal, agent.id)
    assert row["cached"] == 1
    assert row["total_tokens"] == 500  # premise: the replay's count is on the row
    usage = await journal.get_token_usage()
    assert (usage["total_tokens"], usage["total_calls"]) == (0, 0)

    agent._llm_client = _OneShotClient(
        LLMResponse(content="ok", model=SENT, tokens_used=150, prompt_tokens=100, completion_tokens=50, usage_reported=True),
    )
    await agent.decide(dict(OBSERVATION))

    usage = await journal.get_token_usage()
    assert (usage["total_tokens"], usage["total_calls"]) == (150, 1)


# ---------------------------------------------------------------------------
# 2. The rows that make no model call (cognitive_agent.py:3668, :3705)
# ---------------------------------------------------------------------------


async def test_a_decision_cache_hit_row_names_unknown(journal: CognitiveJournal) -> None:
    """U5: the second identical observation is a decision-cache hit; its row is cached and names ``unknown``."""
    agent = _TestAgent(llm_client=MockLLMClient(), runtime=_runtime(journal, decision_cache=True), pool="test")

    await agent.decide(dict(OBSERVATION))
    await agent.decide(dict(OBSERVATION))

    rows = {row["cached"]: row for row in await _rows(journal, agent.id)}
    assert set(rows) == {0, 1}  # premise: one model call, one cache hit
    assert rows[1]["model"] == "unknown"
    assert rows[1]["token_source"] == ""
    assert rows[0]["model"] == "mock"  # the call's own row names the mock client's model


async def test_a_procedural_replay_row_names_unknown(journal: CognitiveJournal) -> None:
    """U6: a procedural replay makes no model call; its row names ``unknown``."""
    agent = _TestAgent(llm_client=MockLLMClient(), runtime=_runtime(journal))
    agent._check_procedural_memory = AsyncMock(
        return_value={"action": "execute", "llm_output": "replayed", "procedure_id": "proc-1"},
    )

    await agent.decide(dict(OBSERVATION))

    (row,) = await _rows(journal, agent.id)
    assert row["procedure_id"] == "proc-1"  # premise: the replay branch wrote it
    assert row["model"] == "unknown"
    assert row["cached"] == 1


# ---------------------------------------------------------------------------
# 3. Chain steps (sub_task.py)
# ---------------------------------------------------------------------------

_CONTEXT = {
    "_agent_type": "science_officer",
    "_callsign": "Lynx",
    "_department": "Science",
    "context": "Thread content here.",
}


async def test_a_chain_step_records_the_handler_charge_and_model(journal: CognitiveJournal) -> None:
    """U7: the real executor, the real compose handler and the real journal. The step row carries the handler's
    charge (the proxy's zeros, so an estimate), its split, its source and the answering model; the trace carries the
    same source and total."""
    reply = "A reply to the thread."
    llm = _OneReply(LLMResponse(content=reply, model=SENT, answered_model=ANSWERED, usage_reported=True))
    executor = SubTaskExecutor()
    executor.register_handler(SubTaskType.COMPOSE, ComposeHandler(llm_client=llm, runtime=None))
    chain = SubTaskChain(steps=[SubTaskSpec(sub_task_type=SubTaskType.COMPOSE, name="compose", tier="standard")], source="test")

    await executor.execute(
        chain, dict(_CONTEXT), agent_id="agent-1", agent_type="science_officer",
        intent="ward_room_notification", intent_id="int-1", journal=journal,
    )

    assert len(llm.requests) == 1  # premise: the handler made its call
    (row,) = await _rows(journal, "agent-1")
    assert row["dag_node_id"].endswith(":compose")
    assert row["token_source"] == TOKEN_SOURCE_ESTIMATED
    assert row["model"] == ANSWERED
    assert row["completion_tokens"] == _len4(reply)
    assert row["prompt_tokens"] > 0
    assert row["total_tokens"] == row["prompt_tokens"] + row["completion_tokens"]
    (trace,) = await journal.get_recent_chain_traces(limit=10)
    assert trace["token_source"] == TOKEN_SOURCE_ESTIMATED
    assert trace["tokens_used"] == row["total_tokens"]


class _SlowOnce:
    """A handler whose first call never returns (BF-183 times it out and retries) and whose retry names no model."""

    def __init__(self) -> None:
        self.calls = 0

    async def __call__(self, spec: SubTaskSpec, context: dict, prior: list[SubTaskResult]) -> SubTaskResult:
        self.calls += 1
        if self.calls == 1:
            await asyncio.Event().wait()
        return SubTaskResult(
            sub_task_type=spec.sub_task_type, name=spec.name, result={"output": "ok"}, success=True, tier_used="standard",
        )


async def test_a_timed_out_attempt_and_its_retry_name_unknown(
    journal: CognitiveJournal, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """U8: the timed-out attempt's row (``sub_task.py:586``) and the step's row for a result that names no model
    (``:657``) both say ``unknown``; neither accounts for tokens."""
    real_sleep = asyncio.sleep

    async def _no_backoff(delay: float, result: Any = None) -> Any:
        await real_sleep(0)
        return result

    monkeypatch.setattr(asyncio, "sleep", _no_backoff)
    handler = _SlowOnce()
    executor = SubTaskExecutor()
    executor.register_handler(SubTaskType.COMPOSE, handler)
    chain = SubTaskChain(
        steps=[SubTaskSpec(sub_task_type=SubTaskType.COMPOSE, name="compose", tier="standard", timeout_ms=50)],
        chain_timeout_ms=60_000, source="test",
    )

    await executor.execute(chain, dict(_CONTEXT), agent_id="agent-2", agent_type="science_officer", journal=journal)

    assert handler.calls == 2  # premise: timed out once, retried once
    rows = await _rows(journal, "agent-2")
    attempts = [r for r in rows if r["dag_node_id"].endswith(":timeout")]
    steps = [r for r in rows if not r["dag_node_id"].endswith(":timeout")]
    assert len(attempts) == 1 and len(steps) == 1
    assert attempts[0]["model"] == "unknown"
    assert attempts[0]["success"] == 0
    assert steps[0]["model"] == "unknown"
    assert (attempts[0]["token_source"], steps[0]["token_source"]) == ("", "")


async def test_a_replayed_chain_step_is_journaled_cached_and_adds_nothing_to_spend(journal: CognitiveJournal) -> None:
    """U11 (A1, review round 1 F1): the chain path of U4, from the handler to the spend readers. A client cache replay
    of a zero-count answer, built as llm_client.py's two replay paths build it (the original's content, models and
    ``tokens_used``, ``cached=True``, usage presence not stated), goes through the real compose handler, the real
    executor and the real journal. S1 charges it as an estimate, as it charges a one-shot replay; the step row is
    ``cached=1``, so ``get_token_usage``, ``get_token_usage_by``, ``get_token_usage_since`` and the real AD-617b gate
    (called as tests/test_ad617b_per_agent_token_budget.py calls it, with a 1-token cap) leave it out. A fresh step
    that follows is counted by all four: the filter is not vacuous."""
    loop = ProactiveCognitiveLoop()
    loop.set_runtime(
        SimpleNamespace(
            config=SimpleNamespace(llm_rate=LLMRateConfig(per_agent_hourly_token_cap=1)), cognitive_journal=journal,
        ),
    )
    since = time.time() - 3600.0

    async def _step(response: LLMResponse) -> None:
        executor = SubTaskExecutor()
        executor.register_handler(SubTaskType.COMPOSE, ComposeHandler(llm_client=_OneReply(response), runtime=None))
        chain = SubTaskChain(
            steps=[SubTaskSpec(sub_task_type=SubTaskType.COMPOSE, name="compose", tier="standard")], source="test",
        )
        await executor.execute(
            chain, dict(_CONTEXT), agent_id="agent-3", agent_type="science_officer",
            intent="ward_room_notification", intent_id="int-3", journal=journal,
        )

    replay = LLMResponse(
        content="A reply to the thread.", model=SENT, answered_model=ANSWERED, tokens_used=0, cached=True,
    )
    await _step(replay)

    (replay_row,) = await _rows(journal, "agent-3")
    assert replay_row["token_source"] == TOKEN_SOURCE_ESTIMATED  # premise: S1 charges the zero-count replay
    assert replay_row["total_tokens"] > 0  # premise: so only ``cached`` keeps it out of spend
    assert replay_row["cached"] == 1
    usage = await journal.get_token_usage("agent-3")
    assert (usage["total_tokens"], usage["total_calls"]) == (0, 0)
    assert await journal.get_token_usage_by(group_by="model", agent_id="agent-3") == []
    assert await journal.get_token_usage_since("agent-3", since) == 0
    assert await loop._is_over_token_budget("agent-3") is False

    await _step(LLMResponse(content="A fresh reply.", model=SENT, answered_model=ANSWERED, usage_reported=True))

    (fresh,) = [row for row in await _rows(journal, "agent-3") if row["cached"] == 0]
    spent = fresh["total_tokens"]
    assert spent > 0  # premise: the control is charged
    usage = await journal.get_token_usage("agent-3")
    assert (usage["total_tokens"], usage["total_calls"]) == (spent, 1)
    by_model = await journal.get_token_usage_by(group_by="model", agent_id="agent-3")
    assert [(g["model"], g["total_calls"], g["total_tokens"]) for g in by_model] == [(ANSWERED, 1, spent)]
    assert await journal.get_token_usage_since("agent-3", since) == spent
    assert await loop._is_over_token_budget("agent-3") is True


# ---------------------------------------------------------------------------
# 4. The four handlers' success results
# ---------------------------------------------------------------------------

_HANDLERS = {
    "analyze": (AnalyzeHandler, SubTaskType.ANALYZE, '{"contribution_assessment": "RESPOND"}'),
    "compose": (ComposeHandler, SubTaskType.COMPOSE, "A reply to the thread."),
    "evaluate": (
        EvaluateHandler, SubTaskType.EVALUATE,
        '{"pass": true, "score": 0.9, "criteria": {}, "recommendation": "approve"}',
    ),
    "reflect": (ReflectHandler, SubTaskType.REFLECT, '{"output": "A reply to the thread.", "revised": false}'),
}


@pytest.mark.parametrize("mode", ["estimated", "measured"])
@pytest.mark.parametrize("kind", sorted(_HANDLERS))
async def test_each_handler_charges_its_call(kind: str, mode: str) -> None:
    """U9: each handler's success result carries the charge, its source and the answering model."""
    handler_cls, step_type, content = _HANDLERS[kind]
    if mode == "estimated":
        response = LLMResponse(content=content, model=SENT, answered_model=ANSWERED, usage_reported=True)
    else:
        response = LLMResponse(
            content=content, model=SENT, answered_model=ANSWERED,
            tokens_used=150, prompt_tokens=100, completion_tokens=50, usage_reported=True,
        )
    llm = _OneReply(response)
    handler = handler_cls(llm_client=llm, runtime=None)

    result = await handler(SubTaskSpec(sub_task_type=step_type, name=kind, tier="standard"), dict(_CONTEXT), [])

    assert len(llm.requests) == 1  # premise: the handler reached its model call
    assert result.success is True
    assert result.model == ANSWERED
    assert result.cached is False  # BF-901 (A1): a fresh call is not a replay
    if mode == "estimated":
        assert result.token_source == TOKEN_SOURCE_ESTIMATED
        assert result.prompt_tokens > 0
        assert result.completion_tokens == _len4(content)
        assert result.tokens_used == result.prompt_tokens + result.completion_tokens
    else:
        assert result.token_source == TOKEN_SOURCE_MEASURED
        assert (result.prompt_tokens, result.completion_tokens, result.tokens_used) == (100, 50, 150)


_NOT_JSON = "No JSON in this reply."
_REPLAY_CASES = {
    # case id: (handler, reply, the result's success, a result key, its value); the last three pin the branch
    "analyze-parsed": ("analyze", _HANDLERS["analyze"][2], True, "contribution_assessment", "RESPOND"),
    "analyze-parse-failure": ("analyze", _NOT_JSON, False, "contribution_assessment", None),
    "compose": ("compose", _HANDLERS["compose"][2], True, "output", "A reply to the thread."),
    "evaluate-verdict": ("evaluate", _HANDLERS["evaluate"][2], True, "score", 0.9),
    "evaluate-default": ("evaluate", _NOT_JSON, True, "score", 1.0),
    "reflect": ("reflect", _HANDLERS["reflect"][2], True, "output", "A reply to the thread."),
}


@pytest.mark.parametrize("case", list(_REPLAY_CASES))
async def test_each_completed_result_carries_the_replay_flag(case: str) -> None:
    """U12 (A1, review round 1 F1): every result built from a completed call, the analyze parse-failure and the
    evaluate default-verdict results included, carries a client cache replay's ``cached`` beside the charge S1 makes
    for it (a zero-count replay: an estimate) and the answering model. U11 carries one such result into the journal."""
    kind, reply, success, key, value = _REPLAY_CASES[case]
    handler_cls, step_type, _ = _HANDLERS[kind]
    llm = _OneReply(LLMResponse(content=reply, model=SENT, answered_model=ANSWERED, cached=True))
    handler = handler_cls(llm_client=llm, runtime=None)

    result = await handler(SubTaskSpec(sub_task_type=step_type, name=kind, tier="standard"), dict(_CONTEXT), [])

    assert len(llm.requests) == 1  # premise: the handler reached its model call
    assert (result.success, result.result.get(key)) == (success, value)  # premise: the branch the case names
    assert result.cached is True
    assert result.token_source == TOKEN_SOURCE_ESTIMATED
    assert result.model == ANSWERED


# ---------------------------------------------------------------------------
# 5. The migration
# ---------------------------------------------------------------------------

_PRE_BF901_JOURNAL = """
CREATE TABLE journal (
    id          TEXT PRIMARY KEY,
    timestamp   REAL NOT NULL,
    agent_id    TEXT NOT NULL,
    agent_type  TEXT NOT NULL DEFAULT '',
    tier        TEXT NOT NULL DEFAULT 'standard',
    model       TEXT NOT NULL DEFAULT '',
    prompt_tokens    INTEGER NOT NULL DEFAULT 0,
    completion_tokens INTEGER NOT NULL DEFAULT 0,
    total_tokens     INTEGER NOT NULL DEFAULT 0,
    latency_ms       REAL NOT NULL DEFAULT 0.0,
    intent           TEXT NOT NULL DEFAULT '',
    success          INTEGER NOT NULL DEFAULT 1,
    cached           INTEGER NOT NULL DEFAULT 0,
    request_id       TEXT NOT NULL DEFAULT '',
    prompt_hash      TEXT NOT NULL DEFAULT '',
    response_length  INTEGER NOT NULL DEFAULT 0,
    intent_id        TEXT NOT NULL DEFAULT '',
    dag_node_id      TEXT NOT NULL DEFAULT '',
    response_hash    TEXT NOT NULL DEFAULT '',
    procedure_id     TEXT NOT NULL DEFAULT '',
    correlation_id   TEXT NOT NULL DEFAULT '',
    level            TEXT NOT NULL DEFAULT '',
    level_rank       INTEGER NOT NULL DEFAULT 0
);
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
    prompt_tokens       INTEGER NOT NULL DEFAULT 0,
    completion_tokens   INTEGER NOT NULL DEFAULT 0,
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
INSERT INTO journal (id, timestamp, agent_id, model, total_tokens) VALUES ('old-row', 1.0, 'agent-old', '', 0);
INSERT INTO chain_traces (chain_id, step_index, step_name, sub_task_type, agent_id, started_at)
    VALUES ('old-chain', 0, 'compose', 'compose', 'agent-old', 1.0);
"""


async def _columns(db_path: str, table: str) -> list[str]:
    async with aiosqlite.connect(db_path) as conn:
        cursor = await conn.execute(f"PRAGMA table_info({table})")
        return [row[1] for row in await cursor.fetchall()]


async def test_a_warm_boot_adds_the_columns_once_and_old_rows_read_empty(tmp_path: Path) -> None:
    """U10: a database with the pre-BF-901 schema and one row in each table."""
    db_path = str(tmp_path / "warm.db")
    async with aiosqlite.connect(db_path) as conn:
        await conn.executescript(_PRE_BF901_JOURNAL)
        await conn.commit()
    assert "token_source" not in await _columns(db_path, "journal")  # premise: the old shape

    journal = CognitiveJournal(db_path=db_path)
    await journal.start()
    try:
        assert (await _columns(db_path, "journal")).count("token_source") == 1
        assert (await _columns(db_path, "chain_traces")).count("token_source") == 1
        (old,) = await journal.get_reasoning_chain("agent-old")
        assert old["token_source"] == ""
        (old_trace,) = await journal.get_recent_chain_traces(agent_id="agent-old")
        assert old_trace["token_source"] == ""
        await journal.record(
            entry_id=uuid.uuid4().hex, timestamp=time.time(), agent_id="agent-new", model="m",
            total_tokens=7, token_source=TOKEN_SOURCE_MEASURED,
        )
        await journal.record_chain_trace(
            ChainExecutionTrace(
                chain_id="new-chain", step_index=0, step_name="compose", sub_task_type="compose", tier="standard",
                agent_id="agent-new", started_at=time.time(), tokens_used=7, token_source=TOKEN_SOURCE_ESTIMATED,
            ),
        )
        (new,) = await journal.get_reasoning_chain("agent-new")
        assert new["token_source"] == TOKEN_SOURCE_MEASURED
        (new_trace,) = await journal.get_recent_chain_traces(agent_id="agent-new")
        assert new_trace["token_source"] == TOKEN_SOURCE_ESTIMATED
    finally:
        await journal.stop()

    again = CognitiveJournal(db_path=db_path)
    await again.start()  # the second start: the ALTERs find the columns and are skipped
    try:
        assert (await _columns(db_path, "journal")).count("token_source") == 1
        assert (await _columns(db_path, "chain_traces")).count("token_source") == 1
    finally:
        await again.stop()
