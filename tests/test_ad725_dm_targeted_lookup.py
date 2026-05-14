"""AD-725: boundary tests for the DM targeted-lookup dispatcher."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest

from probos.cognitive.dm_targeted_lookup import (
    LookupDispatcher,
    LookupType,
    RegexSubintentClassifier,
    SubintentClassifier,
    TargetedLookupResult,
)
from probos.config import DmTargetedLookupConfig


class _FakeOracle:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    async def query(self, query_text: str, *, agent_id: str = "", **_kw: Any) -> list[str]:
        self.calls.append((query_text, agent_id))
        return [f"oracle-result for {query_text}"]


class _FakeEpisodic:
    def __init__(self, *, sleep_s: float = 0.0, return_value: Any = None) -> None:
        self.calls: list[tuple[str, str]] = []
        self._sleep_s = sleep_s
        self._return = return_value if return_value is not None else ["ep-result-1", "ep-result-2"]

    async def recall_for_agent(self, agent_id: str, query: str, k: int = 5) -> Any:
        self.calls.append((agent_id, query))
        if self._sleep_s:
            await asyncio.sleep(self._sleep_s)
        return self._return


class _FakeCodebase:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def query(self, q: str) -> str:
        self.calls.append(q)
        return f"codebase-result for {q}"


def _runtime(
    *,
    oracle: Any = None,
    episodic: Any = None,
    codebase: Any = None,
    records: Any = None,
) -> SimpleNamespace:
    rt = SimpleNamespace()
    rt.oracle = oracle
    rt.episodic_memory = episodic
    rt.codebase_index = codebase
    rt.records_store = records
    # Firewall sentinels — any access should remain at zero.
    rt.trust_network = MagicMock()
    rt.intent_bus = MagicMock()
    rt.hebbian_router = MagicMock()
    rt.consensus_engine = MagicMock()
    return rt


@pytest.mark.asyncio
async def test_disabled_config_returns_none() -> None:
    cfg = DmTargetedLookupConfig(enabled=False)
    rt = _runtime(episodic=_FakeEpisodic())
    d = LookupDispatcher(runtime=rt, config=cfg)
    out = await d.maybe_lookup("what did we discuss last time?", agent_id="ezri")
    assert out is None
    assert rt.episodic_memory.calls == []


@pytest.mark.asyncio
async def test_classifier_none_returns_none() -> None:
    cfg = DmTargetedLookupConfig(enabled=True)
    rt = _runtime(episodic=_FakeEpisodic())
    d = LookupDispatcher(runtime=rt, config=cfg)
    out = await d.maybe_lookup("hello there!", agent_id="ezri")
    assert out is None
    assert rt.episodic_memory.calls == []


@pytest.mark.asyncio
async def test_episodic_path_hits_recall_for_agent() -> None:
    cfg = DmTargetedLookupConfig(enabled=True)
    ep = _FakeEpisodic()
    rt = _runtime(episodic=ep)
    d = LookupDispatcher(runtime=rt, config=cfg)
    out = await d.maybe_lookup("what did we discuss last time?", agent_id="ezri")
    assert out is not None
    assert out.lookup_type == "episodic"
    assert len(ep.calls) == 1
    assert ep.calls[0][0] == "ezri"


@pytest.mark.asyncio
async def test_codebase_path_disabled_by_default() -> None:
    cfg = DmTargetedLookupConfig(enabled=True)  # enable_codebase defaults False
    cb = _FakeCodebase()
    rt = _runtime(codebase=cb)
    d = LookupDispatcher(runtime=rt, config=cfg)
    out = await d.maybe_lookup("which file is FooBar defined in?", agent_id="ezri")
    assert out is None
    assert cb.calls == []


@pytest.mark.asyncio
async def test_oracle_path_with_async_result() -> None:
    cfg = DmTargetedLookupConfig(enabled=True)
    oracle = _FakeOracle()
    rt = _runtime(oracle=oracle)
    d = LookupDispatcher(runtime=rt, config=cfg)
    out = await d.maybe_lookup("what time is it now?", agent_id="ezri")
    assert out is not None
    assert out.lookup_type == "oracle"
    assert "oracle-result" in out.content
    assert len(oracle.calls) == 1


@pytest.mark.asyncio
async def test_knowledge_path_with_missing_search_method() -> None:
    cfg = DmTargetedLookupConfig(enabled=True)
    # records_store object lacks `.search` attribute.
    rt = _runtime(records=SimpleNamespace())
    d = LookupDispatcher(runtime=rt, config=cfg)
    out = await d.maybe_lookup("according to the ship's records, what happened?", agent_id="ezri")
    # Defensive degrade: missing method -> empty content (caller's
    # `if _result.content:` branch will skip rendering). No crash.
    assert out is None or out.content == ""


@pytest.mark.asyncio
async def test_timeout_returns_none() -> None:
    cfg = DmTargetedLookupConfig(enabled=True, timeout_ms=50)
    ep = _FakeEpisodic(sleep_s=0.5)
    rt = _runtime(episodic=ep)
    d = LookupDispatcher(runtime=rt, config=cfg)
    out = await d.maybe_lookup("what did we discuss last time?", agent_id="ezri")
    assert out is None


@pytest.mark.asyncio
async def test_classifier_exception_degrades() -> None:
    class _BrokenClassifier:
        def classify(self, message: str, *, agent_id: str) -> tuple[LookupType, str]:
            raise RuntimeError("classifier on fire")

    cfg = DmTargetedLookupConfig(enabled=True)
    rt = _runtime(episodic=_FakeEpisodic())
    d = LookupDispatcher(
        runtime=rt, config=cfg, classifier=_BrokenClassifier(),
    )
    out = await d.maybe_lookup("anything", agent_id="ezri")
    assert out is None


@pytest.mark.asyncio
async def test_result_truncated_to_max_lookup_chars() -> None:
    cfg = DmTargetedLookupConfig(enabled=True, max_lookup_chars=20)
    huge = "x" * 1000
    ep = _FakeEpisodic(return_value=huge)
    rt = _runtime(episodic=ep)
    d = LookupDispatcher(runtime=rt, config=cfg)
    out = await d.maybe_lookup("what did we discuss last time?", agent_id="ezri")
    assert out is not None
    assert len(out.content) == 20


@pytest.mark.asyncio
async def test_no_side_effects_on_runtime() -> None:
    cfg = DmTargetedLookupConfig(enabled=True)
    rt = _runtime(episodic=_FakeEpisodic(), oracle=_FakeOracle())
    d = LookupDispatcher(runtime=rt, config=cfg)
    await d.maybe_lookup("what did we discuss last time?", agent_id="ezri")
    # Firewall: no trust/Hebbian/intent_bus/consensus calls.
    assert rt.trust_network.mock_calls == []
    assert rt.intent_bus.mock_calls == []
    assert rt.hebbian_router.mock_calls == []
    assert rt.consensus_engine.mock_calls == []


def test_regex_classifier_smoke() -> None:
    c = RegexSubintentClassifier()
    assert c.classify("what time is it?", agent_id="ezri")[0] == "oracle"
    assert c.classify("what did we discuss last time?", agent_id="ezri")[0] == "episodic"
    assert c.classify("which file is FooBar defined in?", agent_id="ezri")[0] == "codebase"
    assert c.classify("according to the manual, what?", agent_id="ezri")[0] == "knowledge"
    assert c.classify("hi", agent_id="ezri")[0] == "none"
