"""AD-983d: deferred-tool model — manifest + lazy ``find_intents`` retrieval.

The scale piece of the AD-983 Copilot-parity epic. ``CapabilityRetriever`` is
``tool_search`` for ProbOS: an agent always sees a cheap manifest (name +
one-line) of the capabilities in scope and retrieves full detail (params +
``usage_hint``) only for the few it needs this turn. The decomposer renders the
domain tier as a manifest above a configurable catalog-size threshold so the
prompt stays bounded as the catalog grows to hundreds — byte-identical below it.

Real ``IntentDescriptor`` + real ``CapabilityRetriever`` + real ``PromptBuilder``
+ a real ``AgentRegistry`` (BF-287 — no MagicMock at the substrate boundary).
Reuses the AD-979c ``fts_or_query`` / ``reciprocal_rank_fusion`` helpers, so the
retriever is deterministic and surfaces a vocabulary-mismatched capability.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from probos.cognitive.capability_retriever import (
    CapabilityRetriever,
    _one_line,
    _tokenize,
)
from probos.cognitive.decomposer import IntentDecomposer
from probos.cognitive.prompt_builder import PromptBuilder
from probos.config import CognitiveConfig
from probos.substrate.registry import AgentRegistry
from probos.types import IntentDescriptor


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_WEB_SEARCH = IntentDescriptor(
    name="web_search",
    description="Search the web (DuckDuckGo)",
    params={"query": "the search terms"},
    tier="domain",
    usage_hint="[MESH web_search query=<terms>] (search the web)",
)
_READ_FILE = IntentDescriptor(
    name="read_file",
    description="Read file contents",
    params={"path": "absolute file path"},
    tier="core",
    usage_hint="[MESH read_file path=<file>] (read a file)",
)
_HEARTBEAT = IntentDescriptor(
    name="heartbeat", description="System heartbeat", tier="core"
)


def _catalog(n: int, *, tier: str = "domain") -> list[IntentDescriptor]:
    """A synthetic catalog of *n* distinct descriptors with full param tables."""
    return [
        IntentDescriptor(
            name=f"intent_{i:03d}",
            description=f"capability number {i} processes work item {i}",
            params={"arg": "an argument", "mode": "an operating mode"},
            tier=tier,
        )
        for i in range(n)
    ]


# ---------------------------------------------------------------------------
# manifest()
# ---------------------------------------------------------------------------


def test_manifest_scopes_to_granted_set() -> None:
    """An agent granted 8 of a 200-intent catalog sees a manifest of ~8."""
    catalog = _catalog(200) + [_WEB_SEARCH, _READ_FILE]
    retriever = CapabilityRetriever(catalog)
    granted = {f"intent_{i:03d}" for i in range(8)}
    manifest = retriever.manifest(scope=granted)
    assert len(manifest) == 8
    assert {name for name, _desc in manifest} == granted
    # Sorted by name (deterministic).
    assert [name for name, _ in manifest] == sorted(granted)


def test_manifest_unscoped_returns_whole_catalog() -> None:
    retriever = CapabilityRetriever(_catalog(12))
    manifest = retriever.manifest()
    assert len(manifest) == 12
    # Each entry is (name, one_line) — never a full param table.
    for name, desc in manifest:
        assert "{" not in desc  # no JSON param blob


def test_manifest_one_line_truncates_long_description() -> None:
    long = "x " * 100  # ~200 chars
    d = IntentDescriptor(name="verbose", description=long, tier="domain")
    retriever = CapabilityRetriever([d])
    (_name, one_line) = retriever.manifest()[0]
    assert len(one_line) <= 80
    assert one_line.endswith("\u2026")


def test_retriever_dedupes_by_name() -> None:
    dup = IntentDescriptor(name="web_search", description="second", tier="domain")
    retriever = CapabilityRetriever([_WEB_SEARCH, dup, _READ_FILE])
    assert retriever.catalog_size == 2  # web_search counted once


# ---------------------------------------------------------------------------
# find_intents()
# ---------------------------------------------------------------------------


def test_find_intents_returns_full_descriptor() -> None:
    """The retrieved item carries full params + usage_hint, not just a name."""
    retriever = CapabilityRetriever(_catalog(50) + [_WEB_SEARCH])
    results = retriever.find_intents("search the web")
    assert any(d.name == "web_search" for d in results)
    web = next(d for d in results if d.name == "web_search")
    assert web.params == {"query": "the search terms"}
    assert web.usage_hint == "[MESH web_search query=<terms>] (search the web)"


def test_find_intents_is_deterministic() -> None:
    retriever = CapabilityRetriever(_catalog(80) + [_WEB_SEARCH, _READ_FILE])
    first = [d.name for d in retriever.find_intents("read a file from the web")]
    second = [d.name for d in retriever.find_intents("read a file from the web")]
    assert first == second


def test_find_intents_vocabulary_mismatch_via_description() -> None:
    """A capability whose NAME shares no token with the query is still surfaced
    when its description does — the AD-979c hybrid (full-text axis) principle."""
    oracle = IntentDescriptor(
        name="oracle_lookup",
        description="search the web for current information",
        tier="domain",
    )
    retriever = CapabilityRetriever(_catalog(30) + [oracle])
    results = retriever.find_intents("web search")
    assert any(d.name == "oracle_lookup" for d in results)


def test_find_intents_empty_query_returns_empty() -> None:
    retriever = CapabilityRetriever(_catalog(10) + [_WEB_SEARCH])
    assert retriever.find_intents("") == []
    assert retriever.find_intents("   ") == []


def test_find_intents_no_lexical_match_returns_empty() -> None:
    retriever = CapabilityRetriever([_READ_FILE, _HEARTBEAT])
    assert retriever.find_intents("translate francais") == []


def test_find_intents_scope_excludes_ungranted() -> None:
    retriever = CapabilityRetriever(_catalog(20) + [_WEB_SEARCH])
    # web_search matches the query but is NOT in the granted scope.
    granted = {"intent_000", "intent_001"}
    results = retriever.find_intents("search the web", scope=granted)
    assert all(d.name != "web_search" for d in results)


def test_find_intents_respects_k() -> None:
    # Every catalog entry shares the token "work" via its description.
    retriever = CapabilityRetriever(_catalog(50))
    results = retriever.find_intents("work", k=5)
    assert len(results) == 5


def test_find_intents_dense_ranking_is_fused_and_scoped() -> None:
    """The optional dense axis (forward marker) is fused via the same RRF and
    respects scope — an out-of-scope dense hit is dropped."""
    retriever = CapabilityRetriever(_catalog(10) + [_WEB_SEARCH])
    # Pure-lexical query that matches nothing; only the dense axis contributes.
    results = retriever.find_intents(
        "zzz", dense_ranking=["web_search", "not_in_catalog"]
    )
    assert [d.name for d in results] == ["web_search"]


# ---------------------------------------------------------------------------
# BF-287: build the retriever from a real AgentRegistry
# ---------------------------------------------------------------------------


def test_retriever_from_real_registry() -> None:
    """Collect descriptors off a real AgentRegistry's live agents, build the
    retriever, and prove manifest + find_intents work end-to-end."""

    async def _run() -> None:
        reg = AgentRegistry()
        await reg.register(
            SimpleNamespace(
                id="web-0", agent_type="web_search", pool="web_search",
                capabilities=[], intent_descriptors=[_WEB_SEARCH],
            )
        )
        await reg.register(
            SimpleNamespace(
                id="fs-0", agent_type="filesystem", pool="filesystem",
                capabilities=[], intent_descriptors=[_READ_FILE],
            )
        )
        descriptors: list[IntentDescriptor] = []
        for agent in reg.all():
            descriptors.extend(getattr(agent, "intent_descriptors", None) or [])
        retriever = CapabilityRetriever(descriptors)
        assert retriever.catalog_size == 2
        names = {name for name, _ in retriever.manifest()}
        assert names == {"web_search", "read_file"}
        hits = retriever.find_intents("search the web")
        assert any(d.name == "web_search" for d in hits)

    asyncio.run(_run())


# ---------------------------------------------------------------------------
# PromptBuilder manifest mode (back-compat + tiering + boundedness)
# ---------------------------------------------------------------------------


def test_build_system_prompt_default_is_byte_identical_to_manifest_false() -> None:
    descs = _catalog(20) + [_WEB_SEARCH, _READ_FILE]
    builder = PromptBuilder()
    default = builder.build_system_prompt(descs)
    explicit = builder.build_system_prompt(descs, manifest_mode=False)
    assert default == explicit
    # Full render: a domain param table is present.
    assert '"query"' in default


def test_manifest_mode_defers_domain_params_keeps_core() -> None:
    descs = [_WEB_SEARCH, _READ_FILE, _HEARTBEAT]
    builder = PromptBuilder()
    manifest = builder.build_system_prompt(descs, manifest_mode=True)
    # Domain (web_search) param table is deferred — its param JSON is absent.
    assert '"query"' not in manifest
    # Core (read_file) keeps full params.
    assert '"path"' in manifest
    # The manifest heading is present, and lists the deferred domain capability.
    assert "Additional capabilities (manifest" in manifest
    assert "- web_search:" in manifest


def test_manifest_mode_bounds_prompt_growth() -> None:
    """As the domain catalog grows, the manifest-mode prompt grows far slower
    than the full render (the deferred-tool boundedness guarantee)."""
    big_domain = _catalog(120, tier="domain")
    descs = big_domain + [_READ_FILE]
    builder = PromptBuilder()
    full = builder.build_system_prompt(descs, manifest_mode=False)
    manifest = builder.build_system_prompt(descs, manifest_mode=True)
    assert len(manifest) < len(full)
    # The deferred tier contributes no param JSON to the manifest render.
    assert '"mode"' in full
    assert '"mode"' not in manifest


# ---------------------------------------------------------------------------
# Decomposer gate (_use_manifest) + config wiring
# ---------------------------------------------------------------------------


def _bare_decomposer(threshold: int, n_descriptors: int) -> IntentDecomposer:
    """A bare IntentDecomposer exercising only the manifest gate — no LLM
    client needed (BF-287: a real instance, attributes set directly, no Mock)."""
    dec = object.__new__(IntentDecomposer)
    dec.deferred_capability_threshold = threshold
    dec._intent_descriptors = _catalog(n_descriptors)
    return dec


def test_use_manifest_disabled_by_default() -> None:
    # Threshold 0 (the default) never defers, even for a huge catalog.
    assert _bare_decomposer(0, 500)._use_manifest() is False


def test_use_manifest_triggers_only_above_threshold() -> None:
    assert _bare_decomposer(50, 200)._use_manifest() is True
    assert _bare_decomposer(50, 30)._use_manifest() is False
    assert _bare_decomposer(50, 50)._use_manifest() is False  # strictly greater


def test_cognitive_config_threshold_defaults_to_zero() -> None:
    assert CognitiveConfig().deferred_capability_threshold == 0


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def test_tokenize_splits_underscores_and_drops_short_tokens() -> None:
    assert _tokenize("web_search") == {"web", "search"}
    assert _tokenize("") == set()
    assert "a" not in _tokenize("a big cat")  # < 2 chars dropped


def test_one_line_collapses_whitespace() -> None:
    assert _one_line("hello\n  world\t now") == "hello world now"
