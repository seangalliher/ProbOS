"""BF-864: the AD-272 decision cache key must survive a real cognitive cycle.

Issue #1273. Measured on the live vessel before the fix
(``%LOCALAPPDATA%\\ProbOS\\data\\cognitive_journal.db``): 21,243 journal rows,
0 with ``cached=1`` — a 0.000% hit rate across every agent, including the
highest-volume ones (architect 2669, counselor 2034, systems_analyst 1794).

The cause was structural rather than statistical. ``_compute_cache_key`` hashed
the *entire* observation dict, and ``perceive()`` stamps a fresh ``uuid4`` into
``intent_id`` and ``correlation_id`` on every cycle, so the digest was unique on
every call: the cache was written on every miss and read with a key that could
never recur.

Every pre-existing cache test hand-built ``{intent, params, context}`` and so
hit happily — no test had ever run ``perceive() -> decide()``, which is the seam
where the defect lived. These tests cross it.

Repairing the key would have made the cache live on the vessel for the first
time, so ``cognitive.decision_cache_enabled`` now gates it and defaults OFF.
The key tests below are gate-independent (``_compute_cache_key`` is pure); the
``decide()`` tests take an explicit side, and both sides are asserted.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from probos.cognitive.cognitive_agent import (
    _CACHE_HITS,
    _CACHE_MISSES,
    _DECISION_CACHES,
    CognitiveAgent,
)
from probos.cognitive.llm_client import MockLLMClient
from probos.config import CognitiveConfig
from probos.types import IntentMessage


class _CacheProbeAgent(CognitiveAgent):
    """Minimal concrete agent; instructions deliberately free of TTL keywords."""

    agent_type = "bf864_probe"
    _handled_intents = {"bf864_probe_intent"}
    instructions = "You are a deterministic test double."
    intent_descriptors = []


@pytest.fixture(autouse=True)
def _clear_caches():
    _DECISION_CACHES.clear()
    _CACHE_HITS.clear()
    _CACHE_MISSES.clear()
    yield
    _DECISION_CACHES.clear()
    _CACHE_HITS.clear()
    _CACHE_MISSES.clear()


def _runtime(*, cache_enabled: bool) -> SimpleNamespace:
    """A runtime carrying the real ``CognitiveConfig`` and nothing else."""
    return SimpleNamespace(
        config=SimpleNamespace(
            cognitive=CognitiveConfig(decision_cache_enabled=cache_enabled),
        ),
    )


def _agent(*, cache_enabled: bool = False) -> tuple[_CacheProbeAgent, MockLLMClient]:
    llm = MockLLMClient()
    agent = _CacheProbeAgent(
        llm_client=llm, pool="test", runtime=_runtime(cache_enabled=cache_enabled),
    )
    return agent, llm


# ---------------------------------------------------------------------------
# The gate: default OFF, and OFF must be inert.
# ---------------------------------------------------------------------------


def test_decision_cache_defaults_off():
    """The shipped default must be OFF — the whole point of the gate."""
    assert CognitiveConfig().decision_cache_enabled is False


def test_gate_rejects_a_non_bool_config_value():
    """A truthy non-bool must read as OFF.

    Load-bearing, not defensive padding: a large number of rigs pass
    ``MagicMock`` runtimes whose attribute access auto-vivifies to a truthy
    mock, and without this the default-OFF feature would silently arm itself
    across most of the suite.
    """
    from unittest.mock import MagicMock

    agent, _ = _agent()
    assert agent._decision_cache_enabled() is False

    agent._runtime = MagicMock()
    assert agent._decision_cache_enabled() is False

    agent._runtime = None
    assert agent._decision_cache_enabled() is False

    agent._runtime = _runtime(cache_enabled=True)
    assert agent._decision_cache_enabled() is True


@pytest.mark.asyncio
async def test_disabled_cache_never_hits():
    """Two identical cycles must both reach the LLM when the gate is off."""
    agent, llm = _agent()

    first = await agent.perceive(
        IntentMessage(intent="bf864_probe_intent", params={"q": "hello"})
    )
    second = await agent.perceive(
        IntentMessage(intent="bf864_probe_intent", params={"q": "hello"})
    )

    assert "cached" not in await agent.decide(first)
    assert "cached" not in await agent.decide(second)
    assert llm.call_count == 2


@pytest.mark.asyncio
async def test_disabled_cache_is_never_populated():
    """No entry may be written while the gate is off.

    HEAD wrote an entry on every miss under a key that could never recur, so
    the cache was pure memory cost. Off means off: nothing is stored.
    """
    agent, _ = _agent()

    await agent.decide(
        await agent.perceive(
            IntentMessage(intent="bf864_probe_intent", params={"q": "hello"})
        )
    )

    assert _DECISION_CACHES.get(agent.agent_type) == {}
    assert CognitiveAgent.cache_stats()[agent.agent_type]["entries"] == 0


@pytest.mark.asyncio
async def test_disabled_cache_computes_no_key():
    """The gate must skip the lookup itself, not merely discard its result."""
    agent, _ = _agent()
    obs = await agent.perceive(
        IntentMessage(intent="bf864_probe_intent", params={"q": "hello"})
    )

    calls: list[dict] = []
    original = agent._compute_cache_key
    agent._compute_cache_key = lambda o: (calls.append(o), original(o))[1]  # type: ignore[method-assign]

    await agent.decide(obs)
    assert calls == []

    # Guard the premise: the spy must be capable of recording a call, or the
    # assertion above would pass for the wrong reason.
    agent._runtime = _runtime(cache_enabled=True)
    await agent.decide(obs)
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_disabled_cache_still_counts_a_miss():
    """``cache_stats()`` must report the numbers HEAD reports today.

    HEAD counts one miss per ``decide()`` and zero hits; that is exactly what
    the vessel's 21,243/0 journal shows. The gate must not change the meter.
    """
    agent, _ = _agent()

    await agent.decide({"intent": "bf864_probe_intent", "params": {}, "context": ""})

    stats = CognitiveAgent.cache_stats()[agent.agent_type]
    assert stats["misses"] == 1
    assert stats["hits"] == 0


@pytest.mark.asyncio
async def test_turning_the_gate_off_stops_serving_existing_entries():
    """Entries written while the gate was on must not be served once it is off.

    ``on -> off`` is reachable: the settings watcher hot-reloads config, and the
    partition keeps whatever was written before the flip. This is the case the
    *lookup* guard exists for — with population already gated, a fresh agent's
    partition is empty and no lookup could hit anyway, so this transition is the
    only state in which that guard decides anything.
    """
    agent, llm = _agent(cache_enabled=True)
    obs = {"intent": "bf864_probe_intent", "params": {"q": "hello"}, "context": ""}

    await agent.decide(dict(obs))
    # Guard the premise: if it did not hit while on, the flip below proves nothing.
    assert (await agent.decide(dict(obs)))["cached"] is True
    assert llm.call_count == 1

    agent._runtime = _runtime(cache_enabled=False)

    assert "cached" not in await agent.decide(dict(obs))
    assert llm.call_count == 2


# ---------------------------------------------------------------------------
# The property: a real cycle must be able to hit.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_decide_hits_cache_across_two_real_perceive_cycles():
    """Two semantically identical intents, each through perceive(), must hit.

    This is the assertion the defect could never satisfy: it goes through the
    real ``perceive()`` (which mints ``intent_id``/``correlation_id``/
    ``created_at``) rather than a hand-built observation.
    """
    agent, llm = _agent(cache_enabled=True)

    first = await agent.perceive(
        IntentMessage(intent="bf864_probe_intent", params={"q": "hello"})
    )
    second = await agent.perceive(
        IntentMessage(intent="bf864_probe_intent", params={"q": "hello"})
    )

    # Guard the premise: if these did NOT differ, the test would pass for the
    # wrong reason and prove nothing about the key.
    assert first["intent_id"] != second["intent_id"]
    assert first["correlation_id"] != second["correlation_id"]

    await agent.decide(first)
    result = await agent.decide(second)

    assert result["cached"] is True
    assert llm.call_count == 1


@pytest.mark.asyncio
async def test_volatile_identifiers_do_not_change_the_key():
    """The key must ignore intent_id / correlation_id / created_at."""
    agent, _ = _agent()

    base = {"intent": "bf864_probe_intent", "params": {"q": "hello"}, "context": ""}
    a = {**base, "intent_id": "aaa", "correlation_id": "111", "created_at": 1.0}
    b = {**base, "intent_id": "bbb", "correlation_id": "222", "created_at": 2.0}

    assert agent._compute_cache_key(a) == agent._compute_cache_key(b)


@pytest.mark.asyncio
async def test_injected_underscore_state_does_not_change_the_key():
    """Downstream-injected ``_``-prefixed agent state must not enter the key.

    ``_emit_event_fn`` is a *callable*: under the old whole-dict hash its
    ``default=str`` repr embedded a memory address, so it was an independent
    source of per-call uniqueness that no denylist would have anticipated.
    """
    agent, _ = _agent()

    base = {"intent": "bf864_probe_intent", "params": {"q": "hello"}, "context": ""}
    bare = agent._compute_cache_key(base)
    enriched = agent._compute_cache_key(
        {
            **base,
            "_emit_event_fn": lambda *a, **k: None,
            "_trust_score": 0.73,
            "_agent_id": "agent-xyz",
            "_chain_trust_band": "amber",
            "qualification_standing": "provisional",
        }
    )

    assert bare == enriched


# ---------------------------------------------------------------------------
# The key must still DISCRIMINATE. A key too narrow serves a wrong answer,
# which is worse than a miss.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("field", "other"),
    [
        ("intent", "bf864_other_intent"),
        ("context", "a different context"),
        ("thread_id", "thread-b"),
    ],
)
async def test_semantic_fields_still_separate_entries(field: str, other: object):
    """Each allowlisted field must still produce a distinct key."""
    agent, _ = _agent()

    base = {
        "intent": "bf864_probe_intent",
        "params": {"q": "hello"},
        "context": "",
        "thread_id": "thread-a",
    }
    assert agent._compute_cache_key(base) != agent._compute_cache_key({**base, field: other})


@pytest.mark.asyncio
async def test_different_params_still_miss():
    """Different request payloads must not collide."""
    agent, llm = _agent(cache_enabled=True)

    a = await agent.perceive(
        IntentMessage(intent="bf864_probe_intent", params={"q": "hello"})
    )
    b = await agent.perceive(
        IntentMessage(intent="bf864_probe_intent", params={"q": "world"})
    )

    await agent.decide(a)
    await agent.decide(b)

    assert llm.call_count == 2


@pytest.mark.asyncio
async def test_thread_id_separates_identical_messages():
    """AD-809 binds a per-thread personality overlay to thread_id.

    The same text in a different thread must not be served thread A's answer —
    that would be a *wrong* answer, not merely a stale one.
    """
    agent, llm = _agent(cache_enabled=True)

    a = await agent.perceive(
        IntentMessage(
            intent="bf864_probe_intent", params={"q": "hello"}, thread_id="thread-a"
        )
    )
    b = await agent.perceive(
        IntentMessage(
            intent="bf864_probe_intent", params={"q": "hello"}, thread_id="thread-b"
        )
    )

    await agent.decide(a)
    await agent.decide(b)

    assert llm.call_count == 2


@pytest.mark.asyncio
async def test_same_agent_type_different_instructions_do_not_collide():
    """Instructions must stay in the key material, and be tested *directly*.

    ``_DECISION_CACHES`` is partitioned by ``agent_type`` first, so the
    pre-existing ``test_decision_cache_key_includes_instructions`` (which uses
    two different ``agent_type`` values) passes on that partitioning alone and
    cannot fail if ``instructions`` is dropped from the key — mutation-verified
    as a survivor. ``__init__`` accepts a per-instance ``instructions=``
    override, so two agents of the *same* type genuinely share one cache dict
    and only the instructions component separates them.
    """
    llm = MockLLMClient()
    a = _CacheProbeAgent(
        llm_client=llm,
        pool="test",
        instructions="You translate.",
        runtime=_runtime(cache_enabled=True),
    )
    b = _CacheProbeAgent(
        llm_client=llm,
        pool="test",
        instructions="You summarise.",
        runtime=_runtime(cache_enabled=True),
    )

    assert a.agent_type == b.agent_type  # same cache partition
    obs = {"intent": "bf864_probe_intent", "params": {"q": "hello"}, "context": ""}

    assert a._compute_cache_key(obs) != b._compute_cache_key(obs)

    await a.decide(dict(obs))
    await b.decide(dict(obs))
    assert llm.call_count == 2


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "field",
    ["codebase_context", "file_context", "target_context", "fetched_content"],
)
async def test_external_state_snapshots_separate_entries(field: str):
    """Snapshots of mutable external state must participate in the key.

    ``perceive()`` overrides add these: ArchitectAgent (``codebase_context``),
    BuilderAgent (``file_context``/``target_context``) and AgentDesigner
    (``fetched_content``). Each is a live read of the codebase, of files on
    disk, or of an HTTP response — none is a function of ``params`` — and each
    is read straight back into the prompt. All three agents reach the cached
    ``decide()`` (Architect and AgentDesigner do not override it; Builder's
    override falls through to ``super().decide()``).

    Omitting any of them would let two requests with identical params collide
    across a change to the underlying state — e.g. Builder applying an edit
    computed against a stale copy of the file it is about to rewrite. That is a
    wrong answer, not a stale one.
    """
    agent, _ = _agent()

    base = {
        "intent": "bf864_probe_intent",
        "params": {"title": "same spec"},
        "context": "",
        field: "=== foo.py ===\nversion one\n",
    }
    changed = {**base, field: "=== foo.py ===\nversion two\n"}

    assert agent._compute_cache_key(base) != agent._compute_cache_key(changed)


@pytest.mark.asyncio
async def test_allowlist_is_closed_against_new_volatile_fields():
    """A newly-added observation field must not be able to re-break the key.

    This is the regression guard for the defect class itself: exclusion is by
    construction, so a future field lands outside the key unless it is
    deliberately added to ``_CACHE_KEY_FIELDS``.
    """
    agent, _ = _agent()

    base = {"intent": "bf864_probe_intent", "params": {"q": "hello"}, "context": ""}
    assert agent._compute_cache_key(base) == agent._compute_cache_key(
        {**base, "some_future_run_id": "run-0001", "emitted_at": 1234.5}
    )
