"""BF-984 (#1830): AD-607's recall verdict on every public read of EpisodicMemory, and the reads exempt from it.

Before BF-984 the verdict ran in semantic, weighted and anchor recall only. With ``enforce_provenance`` armed, per-agent
recall, the recency reads, intent recall, contrastive recall and an evidence caller's ``get_by_ids`` returned a
forged-source episode with no event, and the crew's prompt recall used and fell back to them. These tests run on a real
ChromaDB-backed EpisodicMemory under tmp_path (tests/test_bf938_ad607_recall_gate.py's setup) and a real CognitiveAgent
(tests/test_ad1357_context_manifest.py's construction); each asserts its premise first. The AST tests classify every
public method whose return annotation names an episode, a recall score or an archive lookup: gated (it reaches
``_security_anomaly_drop`` through ``self`` calls) or listed in ``_EXEMPT`` with a reason. No line numbers.
"""

from __future__ import annotations

import ast
import functools
import logging
from collections.abc import Awaitable, Callable
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from probos.cognitive.cognitive_agent import CognitiveAgent
from probos.cognitive.episodic import EpisodicMemory
from probos.cognitive.source_governance import parse_anchor_query
from probos.config import TRUST_LIEUTENANT, MemorySecurityConfig, SystemConfig
from probos.crew_profile import Rank
from probos.events import EventType
from probos.types import AnchorFrame, Episode, IntentMessage
from tests import test_bf938_ad607_recall_gate as gate

_ROOT = Path(__file__).resolve().parents[1]
_SRC = _ROOT / "src" / "probos"
_EPISODIC = _SRC / "cognitive" / "episodic.py"
_GATE = "_security_anomaly_drop"
# A public method is a read to classify when its return annotation names one of these.
_EPISODE_BEARING = frozenset({"Episode", "RecallScore", "ArchiveLookupResult"})

# The public reads that return episodes WITHOUT AD-607's recall verdict, each with its reason (BF-984, #1830).
# Every other read reaches the verdict. An entry that is gated, no longer exists or no longer returns episodes fails.
_EXEMPT: dict[str, str] = {
    "list_episodes": "maintenance: AD-689's edge backfill walks every row once (knowledge/backfill.py); "
    "whether a provenance-gap row may seed an edge is #1820 bf-984 F1",
    "iter_live_episodes": "erasure: BF-905's cascade must see every live row to erase it (knowledge/erasure.py)",
    "iter_archived_episodes": "erasure: AD-1340's cascade must see every archived row to erase it (knowledge/erasure.py)",
    "lookup_archived_by_id": "the Captain's audited archive read (AD-1340 S2a, routers/security.py); "
    "each returned row has an access row",
    "lookup_archived_by_agent": "the Captain's audited archive read (AD-1340 S2a, routers/security.py); "
    "each returned row has an access row",
    "restore_from_archive": "maintenance: the Captain's audited restore of one archived row to the live store; "
    "every later read of it is gated",
    "score_recall": "a pure scorer of an episode its caller already holds; it reads nothing from the store",
    "recall_for_agent_scored": "an internal step: recall_weighted gates its merged, budgeted pool (BF-938); "
    "recall_weighted is its only production caller (test_weighted_recall_is_the_only_production_caller...)",
}


# --- the AST helpers (tests/test_bf984_rebuild_binding.py imports calls_named) ----------------------------------------


def _class_methods() -> dict[str, ast.FunctionDef | ast.AsyncFunctionDef]:
    tree = ast.parse(_EPISODIC.read_text(encoding="utf-8"))
    (cls,) = [node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "EpisodicMemory"]
    return {node.name: node for node in cls.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}


def _public(methods: dict[str, Any]) -> dict[str, Any]:
    return {name: node for name, node in methods.items() if not name.startswith("_")}


def _annotation_names(node: ast.expr) -> set[str]:
    names: set[str] = set()
    for part in ast.walk(node):
        if isinstance(part, ast.Name):
            names.add(part.id)
        elif isinstance(part, ast.Attribute):
            names.add(part.attr)
        elif isinstance(part, ast.Constant) and isinstance(part.value, str):
            names |= _annotation_names(ast.parse(part.value, mode="eval").body)
    return names


def _reads(methods: dict[str, Any]) -> set[str]:
    return {
        name for name, node in _public(methods).items()
        if node.returns is not None and _annotation_names(node.returns) & _EPISODE_BEARING
    }


def _self_calls(node: ast.AST) -> set[str]:
    return {
        call.func.attr for call in ast.walk(node)
        if isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute)
        and isinstance(call.func.value, ast.Name) and call.func.value.id == "self"
    }


def _reaches_gate(methods: dict[str, Any], name: str) -> bool:
    seen: set[str] = set()
    todo = [name]
    while todo:
        current = todo.pop()
        if current == _GATE:
            return True
        if current in seen or current not in methods:
            continue
        seen.add(current)
        todo.extend(_self_calls(methods[current]))
    return False


class _Calls(ast.NodeVisitor):
    """The qualified scope (classes and functions, innermost last) of each call to a callee named ``name``."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.scope: list[str] = []
        self.found: list[str] = []

    def _scoped(self, node: ast.AST, label: str) -> None:
        self.scope.append(label)
        self.generic_visit(node)
        self.scope.pop()

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._scoped(node, node.name)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._scoped(node, node.name)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._scoped(node, node.name)

    def visit_Call(self, node: ast.Call) -> None:
        func = node.func
        callee = func.attr if isinstance(func, ast.Attribute) else func.id if isinstance(func, ast.Name) else None
        if callee == self.name:
            self.found.append(".".join(self.scope))
        self.generic_visit(node)


@functools.lru_cache(maxsize=1)
def _source_trees() -> tuple[tuple[str, ast.Module], ...]:
    return tuple(
        (path.relative_to(_SRC).as_posix(), ast.parse(path.read_text(encoding="utf-8")))
        for path in sorted(_SRC.rglob("*.py"))
    )


def calls_named(name: str) -> set[tuple[str, str]]:
    """(path under src/probos, qualified scope) of every production call to a callee named ``name``."""
    found: set[tuple[str, str]] = set()
    for path, tree in _source_trees():
        visitor = _Calls(name)
        visitor.visit(tree)
        found |= {(path, scope) for scope in visitor.found}
    return found


# --- A1 to A4: the enumeration -------------------------------------------------------------------------------------


def test_the_enumeration_finds_the_reads_it_must_classify() -> None:
    methods = _class_methods()
    assert _GATE in methods  # premise: the verdict this file looks for
    assert sorted(name for name, node in _public(methods).items() if node.returns is None) == []  # unclassifiable
    reads = _reads(methods)
    assert {"recall", "recall_weighted", "recall_by_anchor", "lookup_archived_by_id", "iter_live_episodes"} <= reads
    assert {"store", "get_episode_metadata", "keyword_search"}.isdisjoint(reads)  # an outcome, a metadata dict, ids
    assert _reaches_gate(methods, "recall")  # control: through its delegate
    assert _reaches_gate(methods, "recall_weighted")  # control: directly
    assert not _reaches_gate(methods, "list_episodes")  # control: a read that does not


def test_every_public_read_is_gated_or_exempt_with_a_reason() -> None:
    methods = _class_methods()
    problems = []
    for name in sorted(_reads(methods)):
        gated, exempt = _reaches_gate(methods, name), name in _EXEMPT
        if gated and exempt:
            problems.append(f"{name}: reaches the verdict and is exempt; drop the exemption")
        elif not gated and not exempt:
            problems.append(f"{name}: neither reaches the verdict nor is exempt")
    assert problems == []


def test_every_exemption_names_a_public_read_and_gives_a_reason() -> None:
    reads = _reads(_class_methods())
    assert sorted(name for name in _EXEMPT if name not in reads) == []
    assert [name for name, reason in _EXEMPT.items() if not reason.strip()] == []


def test_weighted_recall_is_the_only_production_caller_of_its_internal_step() -> None:
    assert calls_named("recall_for_agent_scored") == {("cognitive/episodic.py", "EpisodicMemory.recall_weighted")}


# --- the reads, on a real store ------------------------------------------------------------------------------------

_ANCHOR = AnchorFrame(
    watch_section="first_watch", trigger_type="direct_message", trigger_agent="captain", department="engineering",
)
_VALID_AT = gate._T0 + 3_600.0


def _store() -> list[Episode]:
    """BF-938's four (two clean, a reflection, one forged source), each anchored in engineering for anchor recall."""
    return [replace(episode, anchors=_ANCHOR) for episode in gate._standard()]


async def _ids(read: Awaitable[Any]) -> list[str]:
    return [episode.id for episode in await read]


async def _first_ids(read: Awaitable[Any]) -> list[str]:
    return [episode.id for episode in (await read)[0]]


async def _score_ids(read: Awaitable[Any]) -> list[str]:
    return [score.episode.id for score in await read]


async def _pair_ids(read: Awaitable[Any]) -> list[str]:
    return [episode.id for episode, _similarity in await read]


async def _live_ids(em: EpisodicMemory) -> list[str]:
    return [episode.id async for episode in em.iter_live_episodes()]


class _MidBand:
    """The real collection, with every query distance set to 0.5: AD-655's contrastive band is [0.4, 0.65]."""

    def __init__(self, collection: Any) -> None:
        self._collection = collection

    def count(self) -> int:
        return self._collection.count()

    def query(self, **kwargs: Any) -> Any:
        result = self._collection.query(**kwargs)
        result["distances"] = [[0.5] * len(ids) for ids in result["ids"]]
        return result


async def _contrastive_ids(em: EpisodicMemory) -> list[str]:
    real = em._collection
    em._collection = _MidBand(real)
    try:
        return await _ids(em.retrieve_contrastive_episodes(gate._QUERY, k=5))
    finally:
        em._collection = real


_Read = Callable[[EpisodicMemory], Awaitable[list[str]]]

_GATED: dict[str, _Read] = {
    "recall": lambda em: _ids(em.recall(gate._QUERY, k=5)),
    "recall_with_confidence": lambda em: _first_ids(em.recall_with_confidence(gate._QUERY, k=5)),
    "recall_with_control": lambda em: _first_ids(em.recall_with_control(gate._QUERY, k=5)),
    "recall_weighted": lambda em: _score_ids(em.recall_weighted(gate._AGENT, gate._QUERY, k=5)),
    "recall_valid_at": lambda em: _score_ids(em.recall_valid_at(_VALID_AT, gate._AGENT, gate._QUERY, k=5)),
    "recall_by_anchor": lambda em: _ids(em.recall_by_anchor(department="engineering", agent_id=gate._AGENT)),
    "recall_by_anchor_scored": lambda em: _score_ids(
        em.recall_by_anchor_scored(department="engineering", agent_id=gate._AGENT)
    ),
    "recall_for_agent": lambda em: _ids(em.recall_for_agent(gate._AGENT, gate._QUERY, k=5)),
    "recall_for_agent_with_confidence": lambda em: _first_ids(
        em.recall_for_agent_with_confidence(gate._AGENT, gate._QUERY, k=5)
    ),
    "recent_for_agent": lambda em: _ids(em.recent_for_agent(gate._AGENT, k=5)),
    "recent": lambda em: _ids(em.recent(k=5)),
    "recall_by_intent": lambda em: _ids(em.recall_by_intent("report", k=5)),
    "retrieve_contrastive_episodes": _contrastive_ids,
    "get_by_ids_for_evidence": lambda em: _ids(em.get_by_ids(sorted(gate._ALL), for_evidence=True)),
}

_EXEMPT_READS: dict[str, _Read] = {
    "get_by_ids": lambda em: _ids(em.get_by_ids(sorted(gate._ALL))),  # the bare call is history (AD-1293)
    "list_episodes": lambda em: _ids(em.list_episodes()),
    "iter_live_episodes": _live_ids,
    "recall_for_agent_scored": lambda em: _pair_ids(em.recall_for_agent_scored(gate._AGENT, gate._QUERY, k=5)),
}


@pytest.mark.parametrize("name", sorted(_GATED))
async def test_each_gated_read_leaves_out_a_forged_source_only_when_armed(tmp_path: Path, name: str) -> None:
    read = _GATED[name]
    recorder = gate._Recorder()
    async with gate._memory(tmp_path, _store()) as em:
        assert set(await read(em)) == gate._ALL  # premise: unbound, the read returns all four
        em.set_security_config(MemorySecurityConfig(enforce_provenance=True))
        em.set_security_event_emitter(recorder)
        assert set(await read(em)) == gate._KEPT
    assert set(recorder.ids(EventType.MEMORY_RECALL_ANOMALY)) == {gate._FORGED}
    assert set(recorder.ids(EventType.MEMORY_PROVENANCE_GAP)) == {gate._FORGED}


@pytest.mark.parametrize("name", sorted(_EXEMPT_READS))
async def test_an_exempt_read_returns_every_episode_when_armed(tmp_path: Path, name: str) -> None:
    recorder = gate._Recorder()
    async with gate._memory(tmp_path, _store()) as em:
        em.set_security_config(MemorySecurityConfig(enforce_provenance=True, enforce_recall=True))
        em.set_security_event_emitter(recorder)
        assert set(await _EXEMPT_READS[name](em)) == gate._ALL
    assert recorder.events == []


@pytest.mark.parametrize("name", sorted(_GATED))
async def test_with_every_flag_false_binding_changes_no_read(tmp_path: Path, name: str) -> None:
    read = _GATED[name]
    recorder = gate._Recorder()
    async with gate._memory(tmp_path, _store()) as em:
        unbound = await read(em)
        assert set(unbound) == gate._ALL  # premise: the forged episode is among them
        em.set_security_config(MemorySecurityConfig())
        em.set_security_event_emitter(recorder)
        assert await read(em) == unbound
    assert set(recorder.ids(EventType.MEMORY_PROVENANCE_GAP)) == {gate._FORGED}  # reported, never dropped


async def test_a_recency_read_reports_only_the_episodes_it_returns(tmp_path: Path) -> None:
    older = gate._episode("bf984-forged-older", 0, source="forged_source")
    newer = gate._episode("bf984-forged-newer", 1, source="forged_source")
    recorder = gate._Recorder()
    async with gate._memory(tmp_path, [older, newer]) as em:
        assert [episode.id for episode in await em.recent(k=2)] == [newer.id, older.id]  # premise: newest first
        em.set_security_config(MemorySecurityConfig())
        em.set_security_event_emitter(recorder)
        assert [episode.id for episode in await em.recent(k=1)] == [newer.id]
    assert recorder.ids(EventType.MEMORY_RECALL_ANOMALY) == [newer.id]
    assert recorder.ids(EventType.MEMORY_PROVENANCE_GAP) == [newer.id]
    assert len(recorder.events) == 2


async def test_an_enforced_drop_that_empties_agent_recall_reports_band_none(tmp_path: Path) -> None:
    forged = gate._episode(gate._FORGED, 0, source="forged_source")
    async with gate._memory(tmp_path, [forged]) as em:
        episodes, confidence = await em.recall_for_agent_with_confidence(gate._AGENT, gate._QUERY, k=5)
        assert [episode.id for episode in episodes] == [forged.id]  # premise: unbound, it is recalled
        assert confidence.band != "none"  # premise: with a band the reset can change
        em.set_security_config(MemorySecurityConfig(enforce_provenance=True))
        episodes, confidence = await em.recall_for_agent_with_confidence(gate._AGENT, gate._QUERY, k=5)
    assert episodes == []
    assert confidence.band == "none"


# --- S1: the seam, the crew's prompt recall over the real memory -----------------------------------------------------

_FORGED_MEMORY = "the coolant loop pressure held steady through the shift"
_ASK = "What do you recall about the coolant loop pressure?"


class _Trust:
    """A trust network with one score: Rank.from_trust gives the agent's rank, and so its recall tier (BF-263)."""

    def __init__(self, score: float) -> None:
        self.score = score

    def get_score(self, _agent_id: str) -> float:
        return self.score


def _counted(calls: dict[str, int], name: str, original: Callable[..., Awaitable[Any]]) -> Callable[..., Awaitable[Any]]:
    async def counted(*args: Any, **kwargs: Any) -> Any:
        calls[name] = calls.get(name, 0) + 1
        return await original(*args, **kwargs)

    return counted


async def _prompt_recall(agent: CognitiveAgent, params: dict[str, Any]) -> dict[str, Any]:
    """``_run_cognitive_lifecycle``'s recall step for a Captain's direct message (test_ad1357's ``_turn``, recall only)."""
    intent = IntentMessage(intent="direct_message", params=params)
    observation = {"intent": "direct_message", "intent_id": intent.id, "params": params}
    return await agent._recall_relevant_memories(intent, observation)


@pytest.mark.parametrize(
    ("trust", "rank"),
    [(0.1, Rank.ENSIGN), (TRUST_LIEUTENANT, Rank.LIEUTENANT)],
    ids=["basic_tier", "weighted_then_fallback"],
)
async def test_the_prompt_recall_gives_nothing_from_a_store_holding_only_a_forged_memory(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, trust: float, rank: Rank,
) -> None:
    assert Rank.from_trust(trust) is rank  # premise: an ensign recalls at BASIC, a lieutenant at ENHANCED
    assert not parse_anchor_query(_ASK, known_callsigns=[]).has_anchor_signal  # premise: no anchor recall runs
    agent = CognitiveAgent(agent_id="bf984-agent", instructions="You are Ezri.")
    agent.agent_type = "scout"
    agent.callsign = "Ezri"
    mem_id = agent.sovereign_id or agent.id
    forged = Episode(
        id="bf984-forged", timestamp=gate._T0, user_input=_FORGED_MEMORY, agent_ids=[mem_id],
        source="forged_source", correlation_id="corr-bf984-forged", outcomes=[{"intent": "report", "success": True}],
    )
    params = {"text": _ASK, "captain_message": _ASK}
    calls: dict[str, int] = {}
    recorder = gate._Recorder()
    async with gate._memory(tmp_path, [forged]) as em:
        agent._runtime = SimpleNamespace(
            config=SystemConfig(), cognitive_journal=None, episodic_memory=em, ontology=None, trust_network=_Trust(trust),
        )
        for name in ("recall_weighted", "recall_for_agent", "recent_for_agent"):
            setattr(em, name, _counted(calls, name, getattr(em, name)))
        unbound = await _prompt_recall(agent, params)
        assert [memory["input"] for memory in unbound.get("recent_memories", [])] == [_FORGED_MEMORY]  # premise
        assert ("recall_weighted" in calls) is (rank is Rank.LIEUTENANT)  # premise: the basic tier skips it
        em.set_security_config(MemorySecurityConfig(enforce_provenance=True))
        em.set_security_event_emitter(recorder)
        calls.clear()
        with caplog.at_level(logging.WARNING):
            bound = await _prompt_recall(agent, params)
    assert "recent_memories" not in bound
    assert calls.get("recent_for_agent") == 1  # the turn fell through to the last fallback, which returned nothing
    assert set(recorder.ids(EventType.MEMORY_PROVENANCE_GAP)) == {forged.id}  # the verdict left it out
    assert not [record for record in caplog.records if "BF-138" in record.getMessage()]  # recall did not fail
