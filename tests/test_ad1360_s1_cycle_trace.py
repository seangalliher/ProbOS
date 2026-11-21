"""AD-1360 S1 (#1828): the AD-492 cycle id is issued into a registry, bound for the cycle and checked once, at store time.

S1 ships with ``security.memory.correlation_cutoff`` at 0.0, so AD-607b judges no episode it did not judge before. The
crossing cases run a real CognitiveAgent cycle into a real ChromaDB-backed EpisodicMemory and recall through AD-607's
verdict.
"""

from __future__ import annotations

import ast
import asyncio
import contextlib
import contextvars
import dataclasses
import functools
import itertools
import math
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import ValidationError

from probos.cognitive import context_manifest
from probos.cognitive.cognitive_agent import CognitiveAgent, _build_result_metadata, _carry_cycle_id
from probos.cognitive.episodic import EpisodicMemory, compute_episode_hash
from probos.cognitive.episodic_mock import MockEpisodicMemory
from probos.cognitive.memory_security import (
    configured_correlation_cutoff,
    sanitize_inbound_episode,
    validate_provenance,
    validate_recall_result,
)
from probos.config import MemorySecurityConfig, SystemConfig
from probos.config_profiles import load_profile
from probos.cycle_trace import (
    VERDICT_EMPTY,
    VERDICT_RESOLVED,
    VERDICT_UNCHECKED,
    VERDICT_UNRESOLVED,
    CycleIdRegistry,
    bind_cycle,
    current_cycle_id,
    judge_correlation_id,
    new_cycle_id,
    unbind_cycle,
)
from probos.events import EventType
from probos.startup.cognitive_services import bind_episodic_memory_gates, init_cognitive_services
from probos.types import Episode, EpisodeStoreOutcome, IntentMessage, IntentResult
from tests import test_bf938_ad607_binding as binding
from tests.test_bf239_ward_room_engagement_tracking import _make_agent, _make_ward_room_intent
from tests.test_multi_agent_replay_dispatch import (
    _make_cognitive_agent,
    _make_compound_procedure,
    _make_intent,
    _make_mock_agent_entry,
    _make_mock_runtime,
    _make_store_mock,
)

_ROOT = Path(__file__).resolve().parents[1]
_T0 = 1_700_000_000.0  # long ago, so BF-039's last-hour rate limit and similarity window never see these episodes
_RECORDED = 2_000_000_000.0  # a store time after every cutoff below but the one equal to it
_HEX = frozenset("0123456789abcdef")


def _is_cycle_id(value: object) -> bool:
    return type(value) is str and len(value) == 12 and set(value) <= _HEX


class _Clock:
    def __init__(self) -> None:
        self.now = 1_000.0

    def __call__(self) -> float:
        return self.now


class _Recorder:
    def __init__(self) -> None:
        self.events: list[tuple[Any, dict[str, Any]]] = []

    def __call__(self, event_type: Any, data: dict[str, Any] | None = None) -> None:
        self.events.append((event_type, data or {}))

    def gaps(self) -> dict[str, str]:
        return {
            data.get("episode_id", ""): data.get("reason", "")
            for kind, data in self.events
            if kind == EventType.MEMORY_PROVENANCE_GAP
        }


class _Slots:
    """A concurrency manager that admits every intent: handle_intent's first lifecycle call site."""

    @contextlib.asynccontextmanager
    async def slot(self, intent: str, priority: Any) -> Any:
        yield


def _episode(episode_id: str, *, agent: str = "agent-ad1360", correlation_id: str = "", i: int = 0, **extra: Any) -> Episode:
    return Episode(
        id=episode_id,
        timestamp=_T0 + 600.0 * i,
        user_input=f"the engineering section logged coolant reading {episode_id} within limits",
        agent_ids=[agent],
        source="direct",
        correlation_id=correlation_id,
        outcomes=[{"intent": "report", "success": True}],
        **extra,
    )


def _read_back(em: EpisodicMemory, episode_id: str) -> Episode:
    got = em._collection.get(ids=[episode_id], include=["metadatas", "documents"])
    return EpisodicMemory._metadata_to_episode(got["ids"][0], got["documents"][0], got["metadatas"][0])


@pytest.fixture
async def memory(tmp_path: Path) -> Any:
    em = EpisodicMemory(db_path=str(tmp_path / "episodic.db"), relevance_threshold=0.0)
    await em.start()
    try:
        yield em
    finally:
        await em.stop()


# -- N1 to N8: the registry, the verdict and the binding ------------------------------------------------------------


def test_an_issued_id_is_ad492_shaped_and_resolves_and_a_made_up_one_does_not() -> None:
    registry = CycleIdRegistry()
    chain_id = registry.issue(kind="cognitive_cycle")
    assert _is_cycle_id(chain_id) and _is_cycle_id(new_cycle_id())
    assert registry.resolves(chain_id) is True and registry.kind_of(chain_id) == "cognitive_cycle"
    assert registry.resolves(new_cycle_id()) is False and registry.kind_of("feedfacecafe") == ""
    assert registry.resolves("") is False


def test_an_id_resolves_for_its_ttl_and_not_after() -> None:
    clock = _Clock()
    registry = CycleIdRegistry(ttl_seconds=60.0, clock=clock)
    chain_id = registry.issue(kind="cognitive_cycle")
    clock.now += 60.0
    assert registry.resolves(chain_id) is True  # at the TTL
    clock.now += 0.001
    assert registry.resolves(chain_id) is False and len(registry) == 0


def test_the_oldest_id_is_dropped_past_max_entries() -> None:
    registry = CycleIdRegistry(max_entries=2)
    first, second, third = (registry.issue(kind="cognitive_cycle") for _ in range(3))
    assert [registry.resolves(chain_id) for chain_id in (first, second, third)] == [False, True, True]
    assert len(registry) == 2


def test_register_adopts_an_external_id_and_refreshes_its_ttl() -> None:
    clock = _Clock()
    registry = CycleIdRegistry(ttl_seconds=60.0, clock=clock)
    registry.register("712ebc8d645f", kind="work_item")
    clock.now += 50.0
    registry.register("712ebc8d645f", kind="work_item")  # a resumed run registers again
    clock.now += 50.0
    assert registry.resolves("712ebc8d645f") is True and registry.kind_of("712ebc8d645f") == "work_item"


@pytest.mark.parametrize(
    "build",
    [
        lambda: CycleIdRegistry(ttl_seconds=0.0),
        lambda: CycleIdRegistry(ttl_seconds=-1.0),
        lambda: CycleIdRegistry(ttl_seconds=math.inf),
        lambda: CycleIdRegistry(max_entries=0),
        lambda: CycleIdRegistry().issue(kind=""),
        lambda: CycleIdRegistry().register("", kind="work_item"),
        lambda: CycleIdRegistry().register("712ebc8d645f", kind=" "),
        lambda: bind_cycle(""),
    ],
    ids=["ttl-zero", "ttl-negative", "ttl-inf", "no-entries", "issue-no-kind", "register-no-id", "register-no-kind",
         "bind-empty"],
)
def test_bad_arguments_raise(build: Any) -> None:
    with pytest.raises(ValueError):
        build()


def test_the_store_time_verdict_for_each_case() -> None:
    registry = CycleIdRegistry()
    issued = registry.issue(kind="cognitive_cycle")

    class _Down:
        def resolves(self, chain_id: str) -> bool:
            raise RuntimeError("ad1360: the registry is down")

    assert judge_correlation_id(issued, registry) == VERDICT_RESOLVED
    assert judge_correlation_id("deadbeef0000", registry) == VERDICT_UNRESOLVED
    assert judge_correlation_id("", registry) == VERDICT_EMPTY
    assert judge_correlation_id("   ", registry) == VERDICT_EMPTY
    assert judge_correlation_id("", None) == VERDICT_EMPTY  # an empty id needs no registry
    assert judge_correlation_id(issued, None) == VERDICT_UNCHECKED
    assert judge_correlation_id(issued, _Down()) == VERDICT_UNCHECKED


def test_unbind_puts_back_the_outer_id_and_passes_over_a_used_token() -> None:
    def _body() -> None:
        assert current_cycle_id() == ""
        outer = bind_cycle("aaaaaaaaaaaa")
        inner = bind_cycle("bbbbbbbbbbbb")
        assert current_cycle_id() == "bbbbbbbbbbbb"
        unbind_cycle(inner)
        assert current_cycle_id() == "aaaaaaaaaaaa"
        unbind_cycle(outer)
        assert current_cycle_id() == ""
        unbind_cycle(outer)  # used: passed over (PEP 567 RuntimeError)

    contextvars.copy_context().run(_body)


async def test_a_task_started_inside_a_cycle_reads_its_id() -> None:
    async def _read() -> str:
        return current_cycle_id()

    token = bind_cycle("cccccccccccc")
    try:
        child = asyncio.create_task(_read())
    finally:
        unbind_cycle(token)
    assert await child == "cccccccccccc"  # the task copied the context it was created in
    assert current_cycle_id() == ""


# -- N9 to N17: the rule, its callers and the cutoff ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("cutoff", "stored_at", "verdict", "source", "expected"),
    [
        (0.0, _RECORDED, VERDICT_UNRESOLVED, "direct", (True, "")),
        (_RECORDED, _RECORDED, VERDICT_UNRESOLVED, "direct", (True, "")),
        (_RECORDED + 1.0, _RECORDED, VERDICT_EMPTY, "direct", (True, "")),
        (1.0, 0.0, VERDICT_UNRESOLVED, "direct", (True, "")),
        (1.0, _RECORDED, VERDICT_EMPTY, "secondhand", (True, "")),
        (1.0, _RECORDED, VERDICT_EMPTY, "reflection", (True, "")),
        (1.0, _RECORDED, VERDICT_RESOLVED, "direct", (True, "")),
        (1.0, _RECORDED, VERDICT_EMPTY, "direct", (False, "direct_source_missing_correlation_id")),
        (1.0, _RECORDED, VERDICT_UNRESOLVED, "direct", (False, "direct_source_unresolved_correlation_id")),
        (1.0, _RECORDED, VERDICT_UNCHECKED, "direct", (False, "direct_source_unchecked_correlation_id")),
        (1.0, _RECORDED, "", "direct", (False, "direct_source_unchecked_correlation_id")),
    ],
    ids=["cutoff-off", "at-cutoff", "before-cutoff", "no-record", "secondhand", "reflection", "resolved", "empty",
         "unresolved", "unchecked", "blank-with-time"],
)
def test_the_correlation_rule(
    cutoff: float, stored_at: float, verdict: str, source: str, expected: tuple[bool, str],
) -> None:
    episode = Episode(agent_ids=["agent-a"], source=source, stored_at=stored_at, correlation_verdict=verdict)
    assert validate_provenance(episode, correlation_cutoff=cutoff) == expected


@pytest.mark.parametrize("verdict", ["", VERDICT_EMPTY, VERDICT_UNRESOLVED, VERDICT_UNCHECKED])
def test_a_pre_cutoff_episode_is_never_flagged(verdict: str) -> None:
    """BF-938 retired the rule for every episode then stored; AD-1360 never judges one with no store time."""
    legacy = Episode(agent_ids=["agent-a"], source="direct", correlation_id="", correlation_verdict=verdict)
    for cutoff in (0.0, 1.0, time.time()):
        assert validate_provenance(legacy, correlation_cutoff=cutoff) == (True, "")
    assert validate_provenance(legacy) == (True, "")  # the default a caller with no config passes


def test_missing_agent_ids_is_still_reported_first() -> None:
    episode = Episode(agent_ids=[], source="direct", stored_at=_RECORDED, correlation_verdict=VERDICT_EMPTY)
    assert validate_provenance(episode, correlation_cutoff=1.0) == (False, "missing_agent_ids")


def test_the_configured_cutoff_is_a_finite_positive_number_or_zero() -> None:
    assert configured_correlation_cutoff(None) == 0.0
    assert configured_correlation_cutoff(SimpleNamespace(anchor_mismatch_threshold=0.7)) == 0.0
    assert configured_correlation_cutoff(MagicMock()) == 0.0  # a mocked config never arms the rule
    assert configured_correlation_cutoff(SimpleNamespace(correlation_cutoff=True)) == 0.0
    assert configured_correlation_cutoff(SimpleNamespace(correlation_cutoff=-5.0)) == 0.0
    assert configured_correlation_cutoff(MemorySecurityConfig()) == 0.0
    assert configured_correlation_cutoff(MemorySecurityConfig(correlation_cutoff=5.0)) == 5.0


def test_the_recall_verdict_reports_a_judged_episode_only_with_a_cutoff_config() -> None:
    forged = Episode(
        agent_ids=["agent-a"], source="direct", correlation_id="deadbeef0000",
        stored_at=_RECORDED, correlation_verdict=VERDICT_UNRESOLVED,
    )
    assert validate_recall_result(forged).allowed is True
    assert validate_recall_result(forged, config=MemorySecurityConfig()).allowed is True
    judged = validate_recall_result(forged, config=MemorySecurityConfig(correlation_cutoff=1.0))
    assert judged.allowed is False and judged.anomalies == ("provenance_gap",)


def test_a_peer_episode_is_never_judged_on_its_correlation_id() -> None:
    peer = Episode(
        agent_ids=["peer-agent"], source="direct", user_input="the peer logged a routine reading",
        dag_summary={"classification": "ship"}, correlation_id="peer00000000",
        stored_at=time.time(), correlation_verdict=VERDICT_UNRESOLVED,
    )
    assert sanitize_inbound_episode(peer) == (True, "")


def test_the_cutoff_ships_at_zero_and_nothing_arms_it() -> None:
    for config in (SystemConfig(), load_profile("supported")):
        assert config.security.memory.correlation_cutoff == 0.0
    defaults = MemorySecurityConfig()
    assert (defaults.enforce_recall, defaults.enforce_provenance, defaults.enforce_store) == (False, False, False)


_DEC_1 = datetime(2026, 12, 1, tzinfo=timezone.utc)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (1796083200, 1796083200.0),
        ("1796083200.5", 1796083200.5),
        ("2026-12-01T00:00:00Z", _DEC_1.timestamp()),
        ("2026-12-01T01:00:00+01:00", _DEC_1.timestamp()),
        (_DEC_1, _DEC_1.timestamp()),
    ],
    ids=["epoch-int", "epoch-string", "iso-z", "iso-offset", "aware-datetime"],
)
def test_the_cutoff_accepts_epoch_seconds_or_an_iso_time_with_an_offset(value: Any, expected: float) -> None:
    assert MemorySecurityConfig(correlation_cutoff=value).correlation_cutoff == pytest.approx(expected)


@pytest.mark.parametrize(
    "value",
    ["2026-12-01T00:00:00", "2026-12-01", "next tuesday", math.inf, math.nan, "inf", -1.0, True, datetime(2026, 12, 1)],
    ids=["naive-iso", "date-only", "words", "inf", "nan", "inf-string", "negative", "bool", "naive-datetime"],
)
def test_the_cutoff_refuses_an_ambiguous_or_impossible_instant(value: Any) -> None:
    with pytest.raises(ValidationError):
        MemorySecurityConfig(correlation_cutoff=value)


# -- N18 to N23: the record, stored and read back -------------------------------------------------------------------


def test_the_record_round_trips_and_a_legacy_row_reads_as_not_recorded() -> None:
    episode = _episode("ad1360-rt", correlation_id="abcdefabcdef", stored_at=_RECORDED, correlation_verdict=VERDICT_RESOLVED)
    metadata = EpisodicMemory._episode_to_metadata(episode)
    assert (metadata["stored_at"], metadata["correlation_verdict"]) == (_RECORDED, VERDICT_RESOLVED)
    back = EpisodicMemory._metadata_to_episode(episode.id, episode.user_input, metadata)
    assert (back.stored_at, back.correlation_verdict) == (_RECORDED, VERDICT_RESOLVED)
    legacy = {key: value for key, value in metadata.items() if key not in ("stored_at", "correlation_verdict")}
    old = EpisodicMemory._metadata_to_episode(episode.id, episode.user_input, legacy)
    assert (old.stored_at, old.correlation_verdict) == (0.0, "")
    garbled = {**metadata, "stored_at": "not a time", "correlation_verdict": 7}
    bad = EpisodicMemory._metadata_to_episode(episode.id, episode.user_input, garbled)
    assert (bad.stored_at, bad.correlation_verdict) == (0.0, "")


def test_the_record_is_not_part_of_the_content_hash() -> None:
    episode = _episode("ad1360-hash", correlation_id="abcdefabcdef")
    recorded = dataclasses.replace(episode, stored_at=_RECORDED, correlation_verdict=VERDICT_UNRESOLVED)
    assert compute_episode_hash(episode) == compute_episode_hash(recorded)
    assert (EpisodicMemory._episode_to_metadata(episode)["content_hash"]
            == EpisodicMemory._episode_to_metadata(recorded)["content_hash"])


async def test_store_records_each_verdict_and_replaces_what_the_producer_set(memory: EpisodicMemory) -> None:
    registry = CycleIdRegistry()
    memory.set_cycle_registry(registry)
    issued = registry.issue(kind="cognitive_cycle")
    cases = {
        "ad1360-resolved": (issued, VERDICT_RESOLVED),
        "ad1360-made-up": ("deadbeef0000", VERDICT_UNRESOLVED),
        "ad1360-empty": ("", VERDICT_EMPTY),
    }
    before = time.time()
    for i, (episode_id, (chain_id, _)) in enumerate(cases.items()):
        producer_record = {"stored_at": 1.0, "correlation_verdict": VERDICT_RESOLVED}  # ignored by store()
        episode = _episode(episode_id, agent=f"agent-{i}", correlation_id=chain_id, i=i, **producer_record)
        assert await memory.store(episode) is EpisodeStoreOutcome.STORED
    after = time.time()
    for episode_id, (_, verdict) in cases.items():
        back = _read_back(memory, episode_id)
        assert back.correlation_verdict == verdict
        assert before <= back.stored_at <= after


async def test_a_store_with_no_registry_bound_records_unchecked(memory: EpisodicMemory) -> None:
    await memory.store(_episode("ad1360-unbound", correlation_id="abcdefabcdef"))
    assert _read_back(memory, "ad1360-unbound").correlation_verdict == VERDICT_UNCHECKED


async def test_seed_keeps_the_record_an_episode_carries(memory: EpisodicMemory) -> None:
    memory.set_cycle_registry(CycleIdRegistry())
    seeded = [
        _episode("ad1360-legacy"),
        _episode("ad1360-carried", correlation_id="abcdefabcdef", i=1, stored_at=_RECORDED,
                 correlation_verdict=VERDICT_RESOLVED),
    ]
    assert await memory.seed(seeded) == 2
    legacy, carried = _read_back(memory, "ad1360-legacy"), _read_back(memory, "ad1360-carried")
    assert (legacy.stored_at, legacy.correlation_verdict) == (0.0, "")
    assert (carried.stored_at, carried.correlation_verdict) == (_RECORDED, VERDICT_RESOLVED)


async def test_an_episode_without_a_record_is_kept_when_the_rule_is_armed(memory: EpisodicMemory) -> None:
    await memory.seed([_episode("ad1360-legacy", agent="agent-legacy")])
    memory.set_security_config(MemorySecurityConfig(enforce_provenance=True, correlation_cutoff=1.0))
    assert [episode.id for episode in await memory.recent_for_agent("agent-legacy", k=5)] == ["ad1360-legacy"]


# -- N24 to N27: the wiring -----------------------------------------------------------------------------------------


def test_the_binding_sets_a_registry_only_when_given_one(tmp_path: Path) -> None:
    config = SystemConfig()
    config.storage_gate.enabled = False
    em = EpisodicMemory(db_path=str(tmp_path / "episodic.db"))
    bind_episodic_memory_gates(em, config, None)  # the rebuild command's call
    assert em._cycle_registry is None
    registry = CycleIdRegistry()
    bind_episodic_memory_gates(em, config, None, cycle_registry=registry)
    assert em._cycle_registry is registry


async def test_startup_binds_the_registry_it_is_given(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    registry = CycleIdRegistry()
    monkeypatch.setattr(binding, "init_cognitive_services", functools.partial(init_cognitive_services, cycle_registry=registry))
    async with binding._bound(tmp_path, monkeypatch, SystemConfig(), binding._Recorder()) as em:
        assert em._cycle_registry is registry


async def test_the_mock_memory_accepts_the_registry_and_records_nothing() -> None:
    mock = MockEpisodicMemory()
    registry = CycleIdRegistry()
    config = SystemConfig()
    config.storage_gate.enabled = False  # AD-610 is not under test
    bind_episodic_memory_gates(mock, config, None, cycle_registry=registry)
    assert mock._cycle_registry is registry
    episode = _episode("ad1360-mock", correlation_id="deadbeef0000")
    assert await mock.store(episode) is EpisodeStoreOutcome.STORED
    assert mock._episodes == [episode]  # stored as given: the mock applies no AD-607 control and records nothing


async def test_the_runtime_owns_one_registry_and_passes_it_to_startup(tmp_path: Path) -> None:
    from probos.runtime import ProbOSRuntime

    runtime = ProbOSRuntime(config=SystemConfig(), data_dir=tmp_path)
    assert isinstance(runtime.cycle_registry, CycleIdRegistry)
    tree = ast.parse((_ROOT / "src" / "probos" / "runtime.py").read_text(encoding="utf-8"))
    calls = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "init_cognitive_services"
    ]
    assert len(calls) == 1  # premise: the one startup call
    assert {kw.arg: ast.unparse(kw.value) for kw in calls[0].keywords}.get("cycle_registry") == "self.cycle_registry"


# -- N28 to N32: the agent ------------------------------------------------------------------------------------------


def test_the_agent_issues_from_the_runtime_registry_and_never_from_a_mock() -> None:
    agent = _make_agent()
    registry = CycleIdRegistry()
    agent._runtime = SimpleNamespace(cycle_registry=registry)
    issued = agent._issue_cycle_id()
    assert registry.resolves(issued) and registry.kind_of(issued) == "cognitive_cycle"
    for runtime in (MagicMock(), None):  # a test runtime's attribute is not a registry
        agent._runtime = runtime
        assert _is_cycle_id(agent._issue_cycle_id())


async def test_perceive_takes_the_bound_id_and_issues_one_when_none_is_bound() -> None:
    agent = _make_agent()
    intent = IntentMessage(intent="direct_message", params={"text": "status"})
    token = bind_cycle("feedfacecafe")
    try:
        bound = await agent.perceive(intent)
    finally:
        unbind_cycle(token)
    assert bound["correlation_id"] == "feedfacecafe" == agent._current_correlation_id
    unbound = await agent.perceive(intent)
    assert _is_cycle_id(unbound["correlation_id"]) and unbound["correlation_id"] != "feedfacecafe"


def test_the_result_metadata_carries_the_cycle_id_as_a_bounded_fact() -> None:
    assert _build_result_metadata({}, {}, {"correlation_id": "abcdefabcdef"}) == {"correlation_id": "abcdefabcdef"}
    assert _build_result_metadata({}, {}, {}) == {}
    assert _build_result_metadata({}, {}, {"correlation_id": ""}) == {}
    assert _build_result_metadata({}, {}, {"correlation_id": 7}) == {}
    assert _build_result_metadata({}, {}, {"correlation_id": "x" * 100})["correlation_id"] == "x" * 64


@pytest.mark.parametrize("slots", [False, True], ids=["plain", "concurrency-slot"])
async def test_handle_intent_binds_a_new_id_for_each_cycle_and_puts_back_the_outer_one(slots: bool) -> None:
    seen: list[str] = []

    async def _lifecycle(self: Any, intent: Any, csi: Any = None, se: Any = None) -> IntentResult:
        seen.append(current_cycle_id())
        return IntentResult(intent_id=intent.id, agent_id=self.id, success=True, result="ok")

    agent = _make_agent()
    if slots:
        agent._concurrency_manager = _Slots()
    outer = bind_cycle("0123456789ab")
    try:
        with patch.object(type(agent), "_run_cognitive_lifecycle", _lifecycle):
            for thread_id in ("thread-ad1360-a", "thread-ad1360-b"):
                await agent.handle_intent(_make_ward_room_intent(thread_id))
        assert current_cycle_id() == "0123456789ab"
    finally:
        unbind_cycle(outer)
    assert len(seen) == 2 and seen[0] != seen[1]
    assert all(_is_cycle_id(chain_id) and chain_id != "0123456789ab" for chain_id in seen)


async def test_the_cycle_id_is_put_back_when_the_lifecycle_raises() -> None:
    async def _raises(self: Any, intent: Any, csi: Any = None, se: Any = None) -> IntentResult:
        assert _is_cycle_id(current_cycle_id())
        raise RuntimeError("ad1360: the lifecycle failed")

    agent = _make_agent()
    with patch.object(type(agent), "_run_cognitive_lifecycle", _raises):
        with pytest.raises(RuntimeError, match="ad1360"):
            await agent.handle_intent(_make_ward_room_intent("thread-ad1360-raise"))
    assert current_cycle_id() == ""


# -- N33, N34: crossing, from a real cycle to the stored record and an armed recall ---------------------------------


class _CycleAgent(CognitiveAgent):
    """A real CognitiveAgent whose model steps are stubbed (test_ad1034_cognitive_spine's pattern): the real perceive,
    lifecycle and AD-430c episode write run."""

    agent_type = "ad1360_test"
    instructions = "AD-1360 cycle test agent."

    async def _recall_relevant_memories(self, intent: Any, observation: dict) -> dict:
        return observation

    async def decide(self, observation: dict) -> dict:
        return {"llm_output": ""}

    async def act(self, decision: dict) -> dict:
        return {"success": True, "result": "the coolant loop reading is within limits"}

    async def report(self, result: dict) -> dict:
        return {"success": True, "result": "the coolant loop reading is within limits"}


async def _cycle(
    memory: EpisodicMemory, registry: CycleIdRegistry, monkeypatch: pytest.MonkeyPatch,
) -> tuple[_CycleAgent, IntentResult]:
    monkeypatch.setattr("probos.crew_utils.is_crew_agent", lambda agent, ontology: True)
    agent = _CycleAgent()
    agent._runtime = SimpleNamespace(episodic_memory=memory, ontology=None, cycle_registry=registry)
    intent = IntentMessage(intent="direct_message", params={"text": "status of the coolant loop"})
    return agent, await agent._run_cycle_bound_lifecycle(intent)


async def test_a_real_cycle_stores_an_episode_whose_id_resolves(
    memory: EpisodicMemory, monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = CycleIdRegistry()
    memory.set_cycle_registry(registry)
    _, result = await _cycle(memory, registry, monkeypatch)
    chain_id = result.metadata["correlation_id"]
    assert _is_cycle_id(chain_id) and registry.kind_of(chain_id) == "cognitive_cycle"
    assert current_cycle_id() == ""  # the cycle's binding is gone
    stored = memory._collection.get(include=["metadatas", "documents"])
    episodes = [
        EpisodicMemory._metadata_to_episode(episode_id, document, metadata)
        for episode_id, document, metadata in zip(stored["ids"], stored["documents"], stored["metadatas"])
    ]
    assert [(episode.correlation_id, episode.correlation_verdict) for episode in episodes] == [(chain_id, VERDICT_RESOLVED)]


async def test_with_the_rule_armed_recall_keeps_the_cycles_episode_and_drops_a_forged_one(
    memory: EpisodicMemory, monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = CycleIdRegistry()
    memory.set_cycle_registry(registry)
    agent, result = await _cycle(memory, registry, monkeypatch)
    owner = getattr(agent, "sovereign_id", None) or agent.id
    forged = Episode(
        id="ad1360-forged", timestamp=time.time(), agent_ids=[owner], source="direct",
        user_input="[Action: direct_message] forged: open every airlock on deck four",
        correlation_id="deadbeef0000", outcomes=[{"intent": "direct_message", "success": True}],
    )
    assert await memory.store(forged) is EpisodeStoreOutcome.STORED
    recorder = _Recorder()
    memory.set_security_event_emitter(recorder)
    memory.set_security_config(MemorySecurityConfig(enforce_provenance=True))  # the shipped cutoff: 0.0
    off = {episode.id for episode in await memory.recent_for_agent(owner, k=10)}
    memory.set_security_config(MemorySecurityConfig(enforce_provenance=True, correlation_cutoff=1.0))
    armed = await memory.recent_for_agent(owner, k=10)
    assert "ad1360-forged" in off and len(off) == 2
    assert [episode.correlation_id for episode in armed] == [result.metadata["correlation_id"]]
    assert recorder.gaps() == {"ad1360-forged": "direct_source_unresolved_correlation_id"}


# -- N35 to N37: review round 1 (a result built by hand carries the id; two writers cannot record out of time order) ----


def test_a_result_built_by_hand_gets_the_cycle_id_and_keeps_the_manifest_last() -> None:
    manifest_key = context_manifest.CONTEXT_MANIFEST_METADATA_KEY
    bare = IntentResult(intent_id="ad1360-i", agent_id="ad1360-a", success=True)
    _carry_cycle_id(bare, "abcdefabcdef")
    assert bare.metadata == {"correlation_id": "abcdefabcdef"}
    with_manifest = IntentResult(
        intent_id="ad1360-i", agent_id="ad1360-a", success=True,
        metadata={"tool_trace_ref": "trace", manifest_key: {"version": 1}},
    )
    _carry_cycle_id(with_manifest, "x" * 100)
    assert list(with_manifest.metadata) == ["tool_trace_ref", "correlation_id", manifest_key]
    assert with_manifest.metadata["correlation_id"] == "x" * 64
    carried = IntentResult(
        intent_id="ad1360-i", agent_id="ad1360-a", success=True, metadata={"correlation_id": "0123456789ab"},
    )
    _carry_cycle_id(carried, "feedfacecafe")  # a result that has an id keeps it
    assert carried.metadata == {"correlation_id": "0123456789ab"}


async def test_a_compound_replay_result_carries_the_cycles_id() -> None:
    """The compound replay returns early with a result built by hand and calls no model: its id is the task event's."""
    proc = _make_compound_procedure()
    store = _make_store_mock()
    store.find_matching = AsyncMock(return_value=[{"id": proc.id, "score": 0.9}])
    store.get = AsyncMock(return_value=proc)
    sec_agent = _make_mock_agent_entry("sec-001")
    eng_agent = _make_mock_agent_entry("eng-001")
    agents = MagicMock()
    agents.get_by_pool = MagicMock(side_effect=lambda pool: [sec_agent] if "security" in pool else [eng_agent])
    bus = AsyncMock()
    bus.send = AsyncMock(
        side_effect=[
            IntentResult(intent_id="i1", agent_id="sec-001", success=True, result="ok"),
            IntentResult(intent_id="i2", agent_id="eng-001", success=True, result="ok"),
        ]
    )
    cycles = CycleIdRegistry()
    runtime = _make_mock_runtime(intent_bus=bus, registry=agents)
    runtime.cycle_registry = cycles
    agent = _make_cognitive_agent(runtime=runtime, procedure_store=store)
    result = await agent.handle_intent(_make_intent(intent_type="security_review"))
    event = runtime.emit_event.call_args[0][1]
    assert event["compound_dispatched"] is True and result.success is True  # the early return ran
    chain_id = result.metadata["correlation_id"]
    assert _is_cycle_id(chain_id) and chain_id == event["correlation_id"]
    assert cycles.kind_of(chain_id) == "cognitive_cycle" and current_cycle_id() == ""


class _GatedLock:
    """The registry's lock with the thread named ``first`` held at the door until the one named ``second`` has been
    through it: the interleaving two writers can have, made certain."""

    def __init__(self) -> None:
        self._inner = threading.Lock()
        self.first_at_the_door = threading.Event()
        self.second_has_been_through = threading.Event()
        self.second_passed_while_first_waited = False

    def __enter__(self) -> None:
        if threading.current_thread().name == "first":
            self.first_at_the_door.set()
            self.second_passed_while_first_waited = self.second_has_been_through.wait(timeout=10.0)
        self._inner.acquire()

    def __exit__(self, *exc_info: object) -> None:
        self._inner.release()
        if threading.current_thread().name == "second":
            self.second_has_been_through.set()


def test_two_writers_cannot_record_out_of_time_order_so_an_expired_id_never_resolves() -> None:
    ticks = itertools.count(100)
    sampled: dict[str, float] = {}
    now_override: list[float] = []

    def clock() -> float:
        if now_override:
            return now_override[0]
        value = float(next(ticks))
        sampled[threading.current_thread().name] = value
        return value

    registry = CycleIdRegistry(ttl_seconds=60.0, clock=clock)
    gate = _GatedLock()
    registry._lock = gate  # type: ignore[assignment]
    ids: dict[str, str] = {}

    def write() -> None:
        ids[threading.current_thread().name] = registry.issue(kind="cognitive_cycle")

    first = threading.Thread(target=write, name="first")
    second = threading.Thread(target=write, name="second")
    first.start()
    assert gate.first_at_the_door.wait(timeout=10.0)
    second.start()
    first.join(timeout=10.0)
    second.join(timeout=10.0)
    assert not first.is_alive() and not second.is_alive() and sorted(ids) == ["first", "second"]
    # A second writer too slow to get through while the first waits would leave the writers in time order, and this
    # case would pass the previous code: the premise is asserted, so a missed interleaving fails.
    assert gate.second_passed_while_first_waited

    earlier, later = sorted(ids, key=sampled.__getitem__)  # the writer that read the clock first, and the other
    now_override.append(sampled[earlier] + 60.5)  # the earlier id is now past its TTL; the later one, a tick newer, is not
    assert registry.resolves(ids[earlier]) is False
    assert registry.resolves(ids[later]) is True


# -- N38: review round 2 (a reader that waits for the lock judges an id by the time it gets the lock) ----------------


class _SlowLock:
    """A lock that takes time to get: entering it moves the clock on, as a caller waiting behind another does."""

    def __init__(self, now: list[float], arrives_at: float) -> None:
        self._now = now
        self._arrives_at = arrives_at

    def __enter__(self) -> None:
        self._now[0] = self._arrives_at

    def __exit__(self, *exc_info: object) -> None:
        return None


def test_a_reader_waiting_for_the_lock_judges_an_id_by_the_time_it_gets_the_lock() -> None:
    now = [100.0]
    registry = CycleIdRegistry(ttl_seconds=60.0, clock=lambda: now[0])
    chain_id = registry.issue(kind="cognitive_cycle")  # recorded at 100
    assert registry.resolves(chain_id) is True  # the premise: at 100 the id is live
    registry._lock = _SlowLock(now, 161.0)  # type: ignore[assignment]
    assert registry.resolves(chain_id) is False  # waiting for the lock took the id past its TTL of 60
