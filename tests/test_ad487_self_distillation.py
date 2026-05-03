"""AD-487: Self-Distillation v1 — tests for Map-step PersonalOntologyProber."""

from __future__ import annotations

import json
from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from probos.cognitive.self_distillation import (
    PersonalOntologyProber,
    ProbeLLMError,
    ProbeRateLimitedError,
    ProbeResult,
)
from probos.config import SelfDistillationConfig, SystemConfig
from probos.events import EventType
from probos.types import LLMRequest, LLMResponse


# ---------------------------------------------------------------------------
# Fakes — stdlib-only persistence, in-memory list-backed DatabaseConnection
# ---------------------------------------------------------------------------


class _FakeDatabaseConnection:
    """In-memory fake for DatabaseConnection protocol — ad-hoc query dispatcher."""

    def __init__(self) -> None:
        self.rows: list[tuple[Any, ...]] = []  # agent_probes rows
        self._last_result: list[tuple[Any, ...]] = []
        self.closed = False

    async def execute(self, sql: str, parameters: Any = ()) -> Any:
        sql_norm = " ".join(sql.split()).lower()
        if sql_norm.startswith("select probed_at from agent_probes"):
            agent_id, domain = parameters
            matches = [r for r in self.rows if r[0] == agent_id and r[1] == domain]
            matches.sort(key=lambda r: r[5], reverse=True)
            self._last_result = [(matches[0][5],)] if matches else []
        elif sql_norm.startswith("select agent_id, domain, sub_topics_json"):
            agent_id, k = parameters
            matches = [r for r in self.rows if r[0] == agent_id]
            matches.sort(key=lambda r: r[5], reverse=True)
            self._last_result = matches[:k]
        elif sql_norm.startswith("insert into agent_probes"):
            self.rows.append(tuple(parameters))
            self._last_result = []
        else:
            self._last_result = []

    async def executemany(self, sql: str, parameters: Any) -> Any:
        for p in parameters:
            await self.execute(sql, p)

    async def executescript(self, sql_script: str) -> None:
        # Schema creation is a no-op for the fake.
        return None

    async def fetchone(self) -> Any:
        return self._last_result[0] if self._last_result else None

    async def fetchall(self) -> Any:
        return list(self._last_result)

    async def commit(self) -> None:
        return None

    async def close(self) -> None:
        self.closed = True


class _FakeFactory:
    def __init__(self, conn: _FakeDatabaseConnection) -> None:
        self.conn = conn
        self.connect_calls: list[str] = []

    async def connect(self, db_path: str) -> Any:
        self.connect_calls.append(db_path)
        return self.conn


def _make_runtime(content: str = '{"sub_topics": ["a"], "confidence": [0.8]}') -> Any:
    runtime = MagicMock()
    runtime.llm_client = MagicMock()
    runtime.llm_client.complete = AsyncMock(
        return_value=LLMResponse(content=content, model="test", tier="standard")
    )
    return runtime


# ---------------------------------------------------------------------------
# Section 0 — EventTypes
# ---------------------------------------------------------------------------


def test_event_type_ontology_probe_recorded_exists() -> None:
    assert EventType.ONTOLOGY_PROBE_RECORDED.value == "ontology_probe_recorded"


def test_event_type_ontology_probe_rate_limited_exists() -> None:
    assert EventType.ONTOLOGY_PROBE_RATE_LIMITED.value == "ontology_probe_rate_limited"


# ---------------------------------------------------------------------------
# Section 4 — Pydantic config defaults
# ---------------------------------------------------------------------------


def test_self_distillation_config_defaults() -> None:
    cfg = SelfDistillationConfig()
    assert cfg.enabled is True
    assert cfg.rate_limit_hours == 24
    assert cfg.llm_timeout_seconds == 30.0
    assert cfg.max_sub_topics == 5
    assert str(cfg.db_path).endswith("agent_probes.db")
    # Wired onto SystemConfig root
    sys_cfg = SystemConfig()
    assert isinstance(sys_cfg.self_distillation, SelfDistillationConfig)


# ---------------------------------------------------------------------------
# Section 2 — ProbeResult contract
# ---------------------------------------------------------------------------


def test_probe_result_is_frozen_dataclass() -> None:
    pr = ProbeResult(
        agent_id="a1",
        domain="naval_history",
        sub_topics=("ships", "battles"),
        confidence_scores=(0.9, 0.7),
        raw_text="{}",
        probed_at=datetime.now(timezone.utc),
    )
    with pytest.raises(FrozenInstanceError):
        pr.agent_id = "other"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Section 3 — Prober behavior
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_start_creates_table_and_index() -> None:
    conn = _FakeDatabaseConnection()
    factory = _FakeFactory(conn)
    cfg = SelfDistillationConfig()
    runtime = _make_runtime()
    prober = PersonalOntologyProber(runtime, cfg, connection_factory=factory)
    await prober.start()
    # connect() invoked with the configured path
    assert factory.connect_calls == [str(cfg.db_path)]
    # Idempotent: starting again with a fresh prober does not raise.
    prober2 = PersonalOntologyProber(runtime, cfg, connection_factory=factory)
    await prober2.start()
    await prober.stop()
    await prober2.stop()
    assert conn.closed is True


@pytest.mark.asyncio
async def test_probe_domain_calls_llm_client_complete_with_llm_request() -> None:
    conn = _FakeDatabaseConnection()
    cfg = SelfDistillationConfig()
    runtime = _make_runtime()
    prober = PersonalOntologyProber(runtime, cfg, connection_factory=_FakeFactory(conn))
    await prober.start()

    await prober.probe_domain("agent-1", "python_async")

    assert runtime.llm_client.complete.await_count == 1
    args, kwargs = runtime.llm_client.complete.call_args
    request = args[0]
    assert isinstance(request, LLMRequest)
    assert request.tier == "standard"
    assert "python_async" in request.prompt
    # max_sub_topics=5 default → both occurrences of {max_sub_topics} interpolated
    assert "5 floats" in request.prompt
    # Priority kwarg present
    from probos.types import Priority
    assert kwargs.get("priority") == Priority.NORMAL


@pytest.mark.asyncio
async def test_probe_domain_parses_json_response() -> None:
    conn = _FakeDatabaseConnection()
    cfg = SelfDistillationConfig()
    runtime = _make_runtime(
        content='{"sub_topics": ["asyncio", "tasks", "loops"], '
                '"confidence": [0.9, 0.8, 0.6]}'
    )
    prober = PersonalOntologyProber(runtime, cfg, connection_factory=_FakeFactory(conn))
    await prober.start()

    result = await prober.probe_domain("agent-1", "python_async")

    assert result.sub_topics == ("asyncio", "tasks", "loops")
    assert result.confidence_scores == (0.9, 0.8, 0.6)
    assert result.agent_id == "agent-1"
    assert result.domain == "python_async"
    assert result.probed_at.tzinfo is not None


@pytest.mark.asyncio
async def test_probe_domain_persists_to_db() -> None:
    conn = _FakeDatabaseConnection()
    cfg = SelfDistillationConfig()
    runtime = _make_runtime()
    prober = PersonalOntologyProber(runtime, cfg, connection_factory=_FakeFactory(conn))
    await prober.start()

    await prober.probe_domain("agent-1", "naval_history")

    assert len(conn.rows) == 1
    row = conn.rows[0]
    assert row[0] == "agent-1"
    assert row[1] == "naval_history"
    assert json.loads(row[2]) == ["a"]
    assert json.loads(row[3]) == [0.8]


@pytest.mark.asyncio
async def test_probe_domain_emits_recorded_event() -> None:
    conn = _FakeDatabaseConnection()
    cfg = SelfDistillationConfig()
    runtime = _make_runtime()
    events: list[tuple[EventType, dict]] = []
    prober = PersonalOntologyProber(runtime, cfg, connection_factory=_FakeFactory(conn))
    prober._emit_event_fn = lambda et, data: events.append((et, data))
    await prober.start()

    await prober.probe_domain("agent-1", "x")

    assert len(events) == 1
    assert events[0][0] == EventType.ONTOLOGY_PROBE_RECORDED
    assert events[0][1]["agent_id"] == "agent-1"
    assert events[0][1]["domain"] == "x"
    assert events[0][1]["sub_topic_count"] == 1


@pytest.mark.asyncio
async def test_probe_domain_rate_limited_within_24h() -> None:
    conn = _FakeDatabaseConnection()
    cfg = SelfDistillationConfig()
    runtime = _make_runtime()
    events: list[tuple[EventType, dict]] = []
    prober = PersonalOntologyProber(runtime, cfg, connection_factory=_FakeFactory(conn))
    prober._emit_event_fn = lambda et, data: events.append((et, data))
    await prober.start()

    # Pre-seed a recent probe (1 hour ago)
    recent = datetime.now(timezone.utc) - timedelta(hours=1)
    conn.rows.append(
        ("agent-1", "x", "[]", "[]", "{}", recent.isoformat()),
    )

    with pytest.raises(ProbeRateLimitedError):
        await prober.probe_domain("agent-1", "x")

    # LLM not called
    assert runtime.llm_client.complete.await_count == 0
    # Rate-limited event emitted
    rate_events = [e for e in events if e[0] == EventType.ONTOLOGY_PROBE_RATE_LIMITED]
    assert len(rate_events) == 1


@pytest.mark.asyncio
async def test_probe_domain_allowed_after_24h_window() -> None:
    conn = _FakeDatabaseConnection()
    cfg = SelfDistillationConfig()
    runtime = _make_runtime()
    prober = PersonalOntologyProber(runtime, cfg, connection_factory=_FakeFactory(conn))
    await prober.start()

    # Pre-seed an old probe (25 hours ago) — outside the 24h window
    old = datetime.now(timezone.utc) - timedelta(hours=25)
    conn.rows.append(
        ("agent-1", "x", "[]", "[]", "{}", old.isoformat()),
    )

    result = await prober.probe_domain("agent-1", "x")

    # New probe succeeded
    assert runtime.llm_client.complete.await_count == 1
    assert result.probed_at.tzinfo is not None
    # probed_at round-trips via ISO 8601
    persisted = conn.rows[-1]
    assert datetime.fromisoformat(persisted[5]) == result.probed_at


@pytest.mark.asyncio
async def test_probe_domain_handles_malformed_json() -> None:
    conn = _FakeDatabaseConnection()
    cfg = SelfDistillationConfig()
    runtime = _make_runtime(content="not valid json at all")
    prober = PersonalOntologyProber(runtime, cfg, connection_factory=_FakeFactory(conn))
    await prober.start()

    result = await prober.probe_domain("agent-1", "x")

    assert result.sub_topics == ()
    assert result.confidence_scores == ()
    # raw_text always preserved
    assert result.raw_text == "not valid json at all"


@pytest.mark.asyncio
async def test_probe_domain_llm_error_raises_probe_llm_error() -> None:
    conn = _FakeDatabaseConnection()
    cfg = SelfDistillationConfig()
    runtime = MagicMock()
    runtime.llm_client = MagicMock()
    runtime.llm_client.complete = AsyncMock(
        return_value=LLMResponse(content="", error="upstream timeout")
    )
    prober = PersonalOntologyProber(runtime, cfg, connection_factory=_FakeFactory(conn))
    await prober.start()

    with pytest.raises(ProbeLLMError):
        await prober.probe_domain("agent-1", "x")


@pytest.mark.asyncio
async def test_get_recent_probes_returns_descending_order() -> None:
    conn = _FakeDatabaseConnection()
    cfg = SelfDistillationConfig()
    runtime = _make_runtime()
    prober = PersonalOntologyProber(runtime, cfg, connection_factory=_FakeFactory(conn))
    await prober.start()

    # Seed three probes for agent-1 with explicit timestamps
    base = datetime.now(timezone.utc) - timedelta(hours=72)
    for i in range(3):
        ts = base + timedelta(hours=i * 25)
        conn.rows.append(
            ("agent-1", f"d{i}", json.dumps([f"t{i}"]), json.dumps([0.5]), "{}", ts.isoformat()),
        )

    recents = await prober.get_recent_probes("agent-1", k=10)

    assert len(recents) == 3
    # Descending — most recent first
    assert recents[0].domain == "d2"
    assert recents[1].domain == "d1"
    assert recents[2].domain == "d0"
    # ISO 8601 round-trip
    assert recents[0].probed_at.tzinfo is not None


@pytest.mark.asyncio
async def test_get_recent_probes_filters_by_agent_id() -> None:
    conn = _FakeDatabaseConnection()
    cfg = SelfDistillationConfig()
    runtime = _make_runtime()
    prober = PersonalOntologyProber(runtime, cfg, connection_factory=_FakeFactory(conn))
    await prober.start()

    now = datetime.now(timezone.utc)
    conn.rows.append(("agent-1", "x", "[]", "[]", "{}", now.isoformat()))
    conn.rows.append(("agent-2", "y", "[]", "[]", "{}", now.isoformat()))

    recents = await prober.get_recent_probes("agent-1", k=10)
    assert len(recents) == 1
    assert recents[0].agent_id == "agent-1"


@pytest.mark.asyncio
async def test_runtime_attribute_set_when_enabled() -> None:
    from probos.startup.finalize import _wire_self_distillation

    runtime = MagicMock()
    runtime.emit_event = MagicMock()

    # Patch the prober factory to avoid touching real SQLite
    import probos.cognitive.self_distillation.prober as prober_mod

    real_init = prober_mod.PersonalOntologyProber.__init__

    def _patched_init(self, runtime, config, *, connection_factory=None):  # type: ignore[no-redef]
        conn = _FakeDatabaseConnection()
        real_init(self, runtime, config, connection_factory=_FakeFactory(conn))

    prober_mod.PersonalOntologyProber.__init__ = _patched_init  # type: ignore[assignment]
    try:
        cfg = SystemConfig()
        wired = await _wire_self_distillation(runtime=runtime, config=cfg)
    finally:
        prober_mod.PersonalOntologyProber.__init__ = real_init  # type: ignore[assignment]

    assert wired is True
    assert hasattr(runtime, "personal_ontology_prober")
    assert isinstance(runtime.personal_ontology_prober, PersonalOntologyProber)
