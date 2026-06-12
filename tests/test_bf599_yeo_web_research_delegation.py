"""BF-599 (revised by AD-983a): no-confabulation capability grounding.

Yeo (YeomanAgent, AD-766) confabulated "I can't browse the web" in 1:1 DMs
even though the ship has live ``web_search``/``page_reader`` agents. The
original fix added a Yeo-only ``_conversational_capability_block`` override.
**AD-983a** generalized that grounding to ALL crew and made it descriptor-
driven: the base ``CognitiveAgent._conversational_capability_block`` renders the
``usage_hint`` of every capability served by a live agent (``capability_affordances``).
So Yeo's no-confabulation behavior is now an inherited-base property, not a
Yeoman override. Comprehensive affordance coverage lives in
``test_ad983a_capability_affordances.py``; this file keeps the BF-599 regression
guard (Yeo gets the web affordance from a live web agent) + the mesh-only
invariant (no direct httpx import).

Real ``AgentRegistry`` fixtures — no MagicMock at the substrate boundary (BF-287).
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from probos.cognitive.cognitive_agent import CognitiveAgent
from probos.cognitive.decomposer import _CAPABILITY_GAP_RE
from probos.cognitive.yeoman import (
    YeomanAgent,
    _DEFAULT_PERSONA,
    _ROLE_RULES,
)
from probos.substrate.registry import AgentRegistry
from probos.types import IntentDescriptor


# ---------------------------------------------------------------------------
# Fixtures / fakes
# ---------------------------------------------------------------------------


def _cap_agent(agent_id: str, pool: str, *descriptors: IntentDescriptor) -> SimpleNamespace:
    """A live-agent stand-in that carries ``intent_descriptors`` (the AD-983a
    affordance source) so the base hook can read their ``usage_hint``s."""
    return SimpleNamespace(
        id=agent_id,
        agent_type=pool,
        pool=pool,
        capabilities=[],
        intent_descriptors=list(descriptors),
    )


_WEB_SEARCH = IntentDescriptor(
    name="web_search", description="Search the web",
    usage_hint="[MESH web_search query=<terms>] (search the web)",
)
_READ_PAGE = IntentDescriptor(
    name="read_page", description="Read a page",
    usage_hint="[MESH read_page url=<url>] (read & summarize a web page)",
)


class _FakeRuntime:
    def __init__(self, registry: AgentRegistry | None) -> None:
        self.registry = registry


@pytest.fixture(autouse=True)
def _reset_yeoman_singleton() -> None:
    """Reset the singleton counter so each test starts clean."""
    YeomanAgent._live_instance_count = 0
    yield
    YeomanAgent._live_instance_count = 0


def _make_yeo(runtime: _FakeRuntime | None = None) -> YeomanAgent:
    """Construct a YeomanAgent bypassing the full CognitiveAgent __init__."""
    agent = object.__new__(YeomanAgent)
    agent.id = "yeoman-001"
    agent.callsign = "Yeo"
    agent.agent_type = "yeoman"
    agent.tier = "domain"
    agent.pool = "yeoman"
    agent.instructions = _DEFAULT_PERSONA + _ROLE_RULES
    agent._runtime = runtime
    YeomanAgent._live_instance_count += 1
    return agent


async def _registry_with_web_agents() -> AgentRegistry:
    registry = AgentRegistry()
    await registry.register(_cap_agent("web-0", "web_search", _WEB_SEARCH))
    await registry.register(_cap_agent("page-0", "page_reader", _READ_PAGE))
    return registry


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_yeo_gets_web_affordance_from_live_web_agent() -> None:
    """BF-599 regression: with a live web_search agent, Yeo's conversational
    capability block names the web-search affordance (no confabulation)."""
    registry = asyncio.run(_registry_with_web_agents())
    yeo = _make_yeo(_FakeRuntime(registry))

    block = yeo._conversational_capability_block({"intent": "direct_message"})

    assert "web_search" in block
    assert "read_page" in block


def test_capability_block_no_runtime_degrades() -> None:
    """No runtime -> honest-degrade to empty string."""
    yeo = _make_yeo(runtime=None)

    assert yeo._conversational_capability_block({"intent": "direct_message"}) == ""


def test_capability_block_no_usage_hint_agents_returns_empty() -> None:
    """A live registry whose agents declare no usage_hint yields no block."""
    async def _run() -> AgentRegistry:
        registry = AgentRegistry()
        await registry.register(_cap_agent("sys-0", "system"))  # no descriptors
        return registry

    registry = asyncio.run(_run())
    yeo = _make_yeo(_FakeRuntime(registry))
    assert yeo._conversational_capability_block({"intent": "direct_message"}) == ""


def test_capability_block_no_gap_regex_tokens() -> None:
    """The rendered block must not trip the decomposer capability-gap regex."""
    registry = asyncio.run(_registry_with_web_agents())
    yeo = _make_yeo(_FakeRuntime(registry))

    block = yeo._conversational_capability_block({"intent": "direct_message"})

    assert block  # non-empty for this registry
    assert not _CAPABILITY_GAP_RE.search(block)


def test_yeoman_no_direct_http_import() -> None:
    """Web access stays mesh-delegated — Yeo must not import httpx/requests."""
    import inspect

    from probos.cognitive import yeoman

    source = inspect.getsource(yeoman)
    assert "import httpx" not in source
    assert "import requests" not in source


def test_capability_block_renders_multiple_reachable_families() -> None:
    """When several live agents declare usage_hints, the block renders all of
    them and stays gap-regex-safe (the AD-983a generalization of BF-599/BF-601:
    web + filesystem affordances together, descriptor-driven)."""
    async def _run() -> AgentRegistry:
        reg = AgentRegistry()
        await reg.register(_cap_agent("web-0", "web_search", _WEB_SEARCH))
        await reg.register(_cap_agent("page-0", "page_reader", _READ_PAGE))
        await reg.register(_cap_agent("fs-0", "filesystem", IntentDescriptor(
            name="read_file", description="Read a file",
            usage_hint="[MESH read_file path=<file>] (read a file)",
        )))
        return reg

    registry = asyncio.run(_run())
    yeo = _make_yeo(_FakeRuntime(registry))

    block = yeo._conversational_capability_block({"intent": "direct_message"})

    for intent in ("web_search", "read_page", "read_file"):
        assert intent in block
    assert not _CAPABILITY_GAP_RE.search(block)

