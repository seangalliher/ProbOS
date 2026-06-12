"""AD-983a: capability affordance layer — the tool carries its own manual.

The headline of the AD-983 Copilot-harness-parity epic: every crew agent
automatically knows how to invoke the capabilities it can reach, with no
per-agent behavior rules teaching "how to use" a tool. ``IntentDescriptor`` now
carries an optional ``usage_hint``; ``CognitiveAgent.capability_affordances()``
derives ``{intent: usage_hint}`` from the LIVE registry (substrate-gated — only
agents that are actually serving contribute); and the base
``_conversational_capability_block`` renders those hints into every crew agent's
conversational prompt. This generalizes the Yeo-only BF-599/AD-870 grounding to
the whole crew and folds in AD-957 (web search for everyone).

Real ``AgentRegistry`` + real ``IntentDescriptor`` (BF-287 — no MagicMock at the
substrate boundary). The base method is exercised on a bare CognitiveAgent and
on a non-Yeo crew agent (CounselorAgent) to prove it is universal, not Yeo-only.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from probos.cognitive.cognitive_agent import CognitiveAgent
from probos.cognitive.decomposer import _CAPABILITY_GAP_RE
from probos.substrate.registry import AgentRegistry
from probos.types import IntentDescriptor


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_WEB_SEARCH = IntentDescriptor(
    name="web_search", description="Search the web",
    usage_hint="[MESH web_search query=<terms>] (search the web)",
)
_READ_FILE = IntentDescriptor(
    name="read_file", description="Read a file",
    usage_hint="[MESH read_file path=<file>] (read a file)",
)
_NO_HINT = IntentDescriptor(name="heartbeat", description="System heartbeat")  # no usage_hint


def _agent(agent_id: str, pool: str, *descriptors: IntentDescriptor) -> SimpleNamespace:
    return SimpleNamespace(
        id=agent_id, agent_type=pool, pool=pool, capabilities=[],
        intent_descriptors=list(descriptors),
    )


async def _registry(*agents: SimpleNamespace) -> AgentRegistry:
    reg = AgentRegistry()
    for a in agents:
        await reg.register(a)
    return reg


def _bare_agent(runtime: object) -> CognitiveAgent:
    """A bare CognitiveAgent (not Yeo) carrying just a runtime — proves the
    affordance is a universal base capability, not a Yeoman override."""
    agent = object.__new__(CognitiveAgent)
    agent._runtime = runtime
    return agent


# ---------------------------------------------------------------------------
# capability_affordances()
# ---------------------------------------------------------------------------


def test_affordances_collect_usage_hints_from_live_agents() -> None:
    async def _run() -> None:
        reg = await _registry(
            _agent("web-0", "web_search", _WEB_SEARCH),
            _agent("fs-0", "filesystem", _READ_FILE),
        )
        aff = _bare_agent(SimpleNamespace(registry=reg)).capability_affordances()
        assert aff == {
            "web_search": "[MESH web_search query=<terms>] (search the web)",
            "read_file": "[MESH read_file path=<file>] (read a file)",
        }

    asyncio.run(_run())


def test_affordances_skip_descriptors_without_a_usage_hint() -> None:
    async def _run() -> None:
        reg = await _registry(_agent("sys-0", "system", _NO_HINT))
        assert _bare_agent(SimpleNamespace(registry=reg)).capability_affordances() == {}

    asyncio.run(_run())


def test_affordances_are_substrate_gated_to_live_agents() -> None:
    async def _run() -> None:
        # Only the web agent is live -> only web_search is reachable; the
        # filesystem read is absent because no agent serves it this turn.
        reg = await _registry(_agent("web-0", "web_search", _WEB_SEARCH))
        aff = _bare_agent(SimpleNamespace(registry=reg)).capability_affordances()
        assert "web_search" in aff
        assert "read_file" not in aff

    asyncio.run(_run())


def test_affordances_dedupe_by_intent_name() -> None:
    async def _run() -> None:
        # Two live agents serve web_search -> one entry, first wins.
        reg = await _registry(
            _agent("web-0", "web_search", _WEB_SEARCH),
            _agent("web-1", "web_search_backup", _WEB_SEARCH),
        )
        aff = _bare_agent(SimpleNamespace(registry=reg)).capability_affordances()
        assert list(aff.keys()) == ["web_search"]

    asyncio.run(_run())


def test_affordances_no_runtime_returns_empty() -> None:
    assert _bare_agent(None).capability_affordances() == {}


def test_affordances_no_registry_returns_empty() -> None:
    assert _bare_agent(SimpleNamespace(registry=None)).capability_affordances() == {}


# ---------------------------------------------------------------------------
# base _conversational_capability_block (the rendered affordance)
# ---------------------------------------------------------------------------


def test_base_block_renders_reachable_affordances_for_any_crew() -> None:
    async def _run() -> None:
        reg = await _registry(
            _agent("web-0", "web_search", _WEB_SEARCH),
            _agent("fs-0", "filesystem", _READ_FILE),
        )
        block = _bare_agent(SimpleNamespace(registry=reg))._conversational_capability_block(
            {"intent": "direct_message"}
        )
        assert "[MESH web_search query=<terms>] (search the web)" in block
        assert "[MESH read_file path=<file>] (read a file)" in block

    asyncio.run(_run())


def test_base_block_is_deterministically_ordered() -> None:
    async def _run() -> None:
        # Registered fs THEN web; the rendered order is sorted by intent name
        # (read_file before web_search) regardless of registration order.
        reg = await _registry(
            _agent("fs-0", "filesystem", _READ_FILE),
            _agent("web-0", "web_search", _WEB_SEARCH),
        )
        block = _bare_agent(SimpleNamespace(registry=reg))._conversational_capability_block(
            {"intent": "direct_message"}
        )
        assert block.index("read_file") < block.index("web_search")

    asyncio.run(_run())


def test_base_block_empty_when_nothing_reachable() -> None:
    async def _run() -> None:
        reg = await _registry(_agent("sys-0", "system", _NO_HINT))
        block = _bare_agent(SimpleNamespace(registry=reg))._conversational_capability_block(
            {"intent": "direct_message"}
        )
        assert block == ""

    asyncio.run(_run())


def test_base_block_empty_without_runtime() -> None:
    # A bare CognitiveAgent with no runtime wired -> "" (byte-identical to the
    # pre-AD-983a default, so agents in no-mesh contexts are unaffected).
    base = object.__new__(CognitiveAgent)
    assert base._conversational_capability_block({"intent": "direct_message"}) == ""


def test_base_block_is_gap_regex_safe() -> None:
    async def _run() -> None:
        reg = await _registry(_agent("web-0", "web_search", _WEB_SEARCH))
        block = _bare_agent(SimpleNamespace(registry=reg))._conversational_capability_block(
            {"intent": "direct_message"}
        )
        assert block
        assert _CAPABILITY_GAP_RE.search(block) is None

    asyncio.run(_run())


def test_non_yeo_crew_agent_gets_the_affordance() -> None:
    """The headline: a non-Yeo crew agent (the Counselor) now gets the web
    affordance with NO agent-specific override — proving the capability carries
    its own manual to every holder."""
    from probos.cognitive.counselor import CounselorAgent

    async def _run() -> None:
        reg = await _registry(_agent("web-0", "web_search", _WEB_SEARCH))
        ezri = object.__new__(CounselorAgent)
        ezri._runtime = SimpleNamespace(registry=reg)
        block = ezri._conversational_capability_block({"intent": "direct_message"})
        assert "web_search" in block

    asyncio.run(_run())


# ---------------------------------------------------------------------------
# usage_hint declared on the real read-intent descriptors
# ---------------------------------------------------------------------------


def test_real_read_descriptors_declare_usage_hints() -> None:
    """The 5 [MESH]-backed read intents ship a usage_hint on their real
    descriptors (so a live deployment surfaces them)."""
    from probos.agents.directory_list import DirectoryListAgent
    from probos.agents.file_reader import FileReaderAgent
    from probos.agents.file_search import FileSearchAgent
    from probos.agents.utility.web_agents import PageReaderAgent, WebSearchAgent

    def _hint(cls: type, intent: str) -> str:
        for d in cls.intent_descriptors:
            if d.name == intent:
                return d.usage_hint
        return ""

    assert "[MESH list_directory" in _hint(DirectoryListAgent, "list_directory")
    assert "[MESH read_file" in _hint(FileReaderAgent, "read_file")
    assert "[MESH search_files" in _hint(FileSearchAgent, "search_files")
    assert "[MESH web_search" in _hint(WebSearchAgent, "web_search")
    assert "[MESH read_page" in _hint(PageReaderAgent, "read_page")
