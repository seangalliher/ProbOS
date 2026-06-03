"""BF-599: Yeo conversational capability grounding.

Yeo (YeomanAgent, AD-766) confabulated "I can't browse the web" in 1:1 DMs
even though the ship has live ``web_search``/``page_reader``/``http`` pools.
Root cause: the conversational DM prompt is composed with
``hardcoded_instructions=""`` so Yeo's static role rules never reach the DM
turn. The fix adds an overridable base hook
``CognitiveAgent._conversational_capability_block`` (default ``""``) that Yeo
overrides to inject the *live* delegable web capabilities read from the
registry.

These tests use a REAL ``AgentRegistry`` fixture (not ``MagicMock`` — the
phantom-attribute trap, repo conventions) so ``get_by_pool`` lookups hit
reality.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest

from probos.cognitive.cognitive_agent import CognitiveAgent
from probos.cognitive.decomposer import _CAPABILITY_GAP_RE
from probos.cognitive.yeoman import (
    YeomanAgent,
    _DEFAULT_PERSONA,
    _ROLE_RULES,
)
from probos.substrate.registry import AgentRegistry


# ---------------------------------------------------------------------------
# Fixtures / fakes
# ---------------------------------------------------------------------------


def _stub_agent(agent_id: str, agent_type: str, pool: str) -> SimpleNamespace:
    """Minimal BaseAgent stand-in for registry.register / get_by_pool.

    ``register`` reads ``id``/``agent_type``/``pool``; ``get_by_pool`` filters
    on ``pool``. ``capabilities`` is read by other registry accessors we don't
    exercise here, included for completeness.
    """
    return SimpleNamespace(
        id=agent_id,
        agent_type=agent_type,
        pool=pool,
        capabilities=[],
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
    """Construct a YeomanAgent bypassing the full CognitiveAgent __init__.

    Mirrors the test_yeoman_agent.py pattern.
    """
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


async def _registry_with_pools(*pools: str) -> AgentRegistry:
    registry = AgentRegistry()
    for idx, pool in enumerate(pools):
        await registry.register(
            _stub_agent(f"{pool}-{idx}", f"{pool}_agent", pool)
        )
    return registry


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_capability_block_lists_live_pools() -> None:
    """Yeo's block names every present pool's delegable intent."""
    registry = asyncio.run(_registry_with_pools("web_search", "page_reader", "http"))
    yeo = _make_yeo(_FakeRuntime(registry))

    block = yeo._conversational_capability_block({"intent": "direct_message"})

    assert "web_search" in block
    assert "read_page" in block
    assert "http_fetch" in block
    # The exposed intent name is read_page, NOT the page_reader pool name.
    assert "page_reader" not in block


def test_capability_block_default_base_returns_empty() -> None:
    """The base CognitiveAgent hook is a no-op so other agents are unaffected."""
    base = object.__new__(CognitiveAgent)

    assert base._conversational_capability_block({"intent": "direct_message"}) == ""


def test_capability_block_no_runtime_degrades() -> None:
    """No runtime -> honest-degrade to empty string."""
    yeo = _make_yeo(runtime=None)

    assert yeo._conversational_capability_block({"intent": "direct_message"}) == ""


def test_capability_block_no_pools_returns_empty() -> None:
    """A live registry with none of the web pools yields no block."""
    registry = asyncio.run(_registry_with_pools("yeoman", "system"))
    yeo = _make_yeo(_FakeRuntime(registry))

    assert yeo._conversational_capability_block({"intent": "direct_message"}) == ""


def test_capability_block_no_gap_regex_tokens() -> None:
    """The rendered block must not trip the decomposer capability-gap regex."""
    registry = asyncio.run(_registry_with_pools("web_search", "page_reader", "http"))
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
