"""BF-949 (#1741): the self-monitoring notebook pull reads only the agent's own notebook, as the agent.

Real fixtures throughout: a real ``RecordsStore`` on ``tmp_path``, the real
``ProactiveCognitiveLoop._build_self_monitoring_context``, the real ``LookupDispatcher`` and the
``search_records`` route function. Nothing here replaces ``RecordsStore.search``.
"""

from __future__ import annotations

import ast
import functools
import json
import time
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.responses import JSONResponse

from probos.cognitive.dm_targeted_lookup import LookupDispatcher
from probos.config import DmTargetedLookupConfig, RecordsConfig
from probos.crew_profile import Rank
from probos.knowledge.records_store import RecordsStore
from probos.proactive import ProactiveCognitiveLoop
from probos.routers.records import search_records
from tests.test_bf679_oracle_records_reader_identity import _FakeAgent, _FakeOntology, _FakeRegistry

_SECRET = "BRAVO-PRIVATE-SECRET-7731"
_BRAVO = "notebooks/Bravo/reactor-notes.md"
_ZEPHYR = "notebooks/Zephyr/own-topic.md"
_SCOPE_ERROR = "Unknown records scope; expected one of: private, department, ship, fleet"
_SRC = Path(__file__).resolve().parents[1] / "src" / "probos"
_M2 = "BF-949 M2: on the base the pull searches the whole repository with no reader"
_M3 = "BF-949 M3: on the base the DM knowledge lookup searches with no reader"

# BF-949: every RecordsStore.search call under src/probos, by file and enclosing function.
_RECORDS_SEARCH_CALLERS = frozenset({
    ("cognitive/dm_targeted_lookup.py", "_dispatch"),
    ("cognitive/oracle_service.py", "_query_records_keyword"),
    ("proactive.py", "_build_self_monitoring_context"),
    ("routers/records.py", "search_records"),
})
# BF-949: RecordsStore.search callers that deliberately pass no reader, each with its reason. None today.
_DELIBERATELY_ANONYMOUS: dict[tuple[str, str], str] = {}


async def _store(root: Path) -> RecordsStore:
    store = RecordsStore(RecordsConfig(repo_path=str(root / "ship-records"), auto_commit=False))
    await store.initialize()
    return store


async def _write_bravo_secret(store: RecordsStore) -> None:
    """Bravo's note: the department word and the secret, at the notebook default (``private``)."""
    await store.write_notebook(
        "Bravo", "reactor-notes", f"engineering {_SECRET} written for my eyes only", department="engineering",
    )


async def _self_monitoring(store: RecordsStore, callsign: str) -> dict[str, Any]:
    """``callsign``'s self-monitoring context at trust 0.75, with no Ward Room posts and no episodic memory."""
    agent = SimpleNamespace(
        id=f"id-{callsign}", agent_type="engineering_agent", callsign=callsign,
        rank=Rank.COMMANDER, department="engineering", sovereign_id=f"id-{callsign}",
    )
    trust = MagicMock()
    trust.get_score = MagicMock(return_value=0.75)
    ward_room = MagicMock()
    ward_room.get_posts_by_author = AsyncMock(return_value=[])
    runtime = SimpleNamespace(
        ward_room=ward_room, episodic_memory=None, _records_store=store, trust_network=trust,
        _lifecycle_state="warm_boot", _start_time_wall=time.time() - 7200,
    )
    loop = ProactiveCognitiveLoop(interval=120.0, cooldown=300.0)
    return await loop._build_self_monitoring_context(agent, callsign, runtime)


_PULL_FIXTURES = [
    pytest.param(
        "Anvil", "my own calibration log, nothing else", "", None,
        id="own-note-lacks-the-word",
    ),
    pytest.param(
        "Zephyr", "engineering notes of my own", "engineering", "own-topic",
        id="agent-sorts-after-bravo",
    ),
    pytest.param(
        "Anvil", "engineering notes of my own", "engineering", "own-topic", id="agent-sorts-before-bravo",
    ),
]


@pytest.mark.asyncio
@pytest.mark.parametrize(("callsign", "own_body", "own_department", "expected_topic"), _PULL_FIXTURES)
async def test_another_agents_private_note_never_reaches_the_pull(
    tmp_path: Path, callsign: str, own_body: str, own_department: str, expected_topic: str | None,
) -> None:
    """Acceptance 1. The query is one word, so every match ties and path order picks the top hit."""
    store = await _store(tmp_path)
    await _write_bravo_secret(store)
    await store.write_notebook(callsign, "own-topic", own_body, department=own_department)
    # Premise: the identity layer refuses this reader Bravo's entry, and the secret is in it.
    assert await store.read_entry(_BRAVO, reader_id=callsign, reader_department="engineering") is None
    bravo = await store.read_entry(_BRAVO, reader_id="Bravo", reader_department="engineering")
    assert bravo["frontmatter"]["classification"] == "private" and _SECRET in bravo["content"]
    result = await _self_monitoring(store, callsign)
    assert "notebook_index" in result  # premise: the notebook block ran
    assert _SECRET not in repr(result)
    if expected_topic is None:
        assert "notebook_content" not in result
    else:
        assert result["notebook_content"]["topic"] == expected_topic
        assert own_body in result["notebook_content"]["snippet"]


@pytest.mark.asyncio
async def test_a_department_colleagues_note_is_not_shown_as_the_agents_own(tmp_path: Path) -> None:
    """Bravo's ``department`` note is readable by an engineering reader; it is still not Zephyr's notebook."""
    store = await _store(tmp_path)
    await store.write_notebook(
        "Bravo", "shared-notes", "engineering shift handover for the department",
        department="engineering", classification="department",
    )
    await store.write_notebook("Zephyr", "own-topic", "engineering notes of my own", department="engineering")
    # Premise: the identity layer admits Bravo's note to Zephyr, so only the directory keeps it out.
    assert await store.read_entry(
        "notebooks/Bravo/shared-notes.md", reader_id="Zephyr", reader_department="engineering",
    ) is not None
    result = await _self_monitoring(store, "Zephyr")
    assert result["notebook_content"]["topic"] == "own-topic"


@pytest.mark.asyncio
async def test_the_agents_own_entry_is_found_behind_twenty_readable_matches(tmp_path: Path) -> None:
    """``search`` keeps 20 hits, so a filter applied to its result would lose an entry that sorts 22nd."""
    store = await _store(tmp_path)
    for index in range(21):
        await store.write_notebook(
            f"Able{index:02d}", "status", "engineering status for the ship",
            department="engineering", classification="ship",
        )
    await store.write_notebook("Zephyr", "own-topic", "engineering notes of my own", department="engineering")
    # Premise: a whole-repository search as Zephyr returns twenty hits, none of them Zephyr's.
    hits = await store.search("engineering", scope="ship", reader_id="Zephyr", reader_department="engineering")
    assert len(hits) == 20 and not any(hit["path"].startswith("notebooks/Zephyr/") for hit in hits)
    result = await _self_monitoring(store, "Zephyr")
    assert result["notebook_content"]["topic"] == "own-topic"


@pytest.mark.asyncio
@pytest.mark.parametrize("scope", [
    pytest.param("notebooks/Anvil", id="a-path"),
    pytest.param("nonsense", id="unknown-label"),
    pytest.param("", id="empty"),
    pytest.param("Ship", id="wrong-case"),
    pytest.param(None, id="not-a-string"),
])
async def test_search_refuses_an_unknown_scope(tmp_path: Path, scope: Any) -> None:
    store = await _store(tmp_path)
    await _write_bravo_secret(store)
    with pytest.raises(ValueError, match="Unknown records scope"):
        await store.search("engineering", scope=scope)


@pytest.mark.asyncio
async def test_search_walks_only_the_directory_it_is_given(tmp_path: Path) -> None:
    store = await _store(tmp_path)
    await _write_bravo_secret(store)
    await store.write_notebook("Zephyr", "own-topic", "engineering notes of my own", department="engineering")
    everything = await store.search("engineering", scope="ship", reader_id="captain")
    assert {hit["path"] for hit in everything} == {_BRAVO, _ZEPHYR}  # premise: "" walks the whole repository
    confined = await store.search("engineering", scope="ship", reader_id="captain", directory="notebooks/Zephyr")
    assert [hit["path"] for hit in confined] == [_ZEPHYR]
    assert await store.search("engineering", scope="ship", reader_id="captain", directory="notebooks/Nobody") == []
    with pytest.raises(ValueError, match="Path traversal denied"):
        await store.search("engineering", scope="ship", reader_id="captain", directory="../outside")


class _RaisingRegistry:
    def get(self, agent_id: str) -> Any:
        raise RuntimeError("registry unavailable")

    def all(self) -> list[Any]:
        raise RuntimeError("registry unavailable")


def _dm_runtime(store: RecordsStore, registry: str) -> SimpleNamespace:
    """The surface the knowledge lookup reads: the store and, unless ``registry`` is "none", a registry and an ontology."""
    if registry == "none":
        return SimpleNamespace(records_store=store)
    crew = _FakeRegistry([_FakeAgent("id-Anvil", callsign="Anvil", agent_type="engineering_agent")])
    return SimpleNamespace(
        records_store=store,
        registry=crew if registry == "crew" else _RaisingRegistry(),
        ontology=_FakeOntology({"engineering_agent": "engineering"}),
    )


@pytest.mark.xfail(strict=True, reason=_M3)
@pytest.mark.asyncio
@pytest.mark.parametrize(("agent_id", "registry", "sees_own"), [
    pytest.param("id-Anvil", "crew", True, id="addressed-agent-resolves"),
    pytest.param("id-ghost", "crew", False, id="unresolved-agent-is-anonymous"),
    pytest.param("id-Anvil", "none", False, id="no-registry-is-anonymous"),
    pytest.param("id-Anvil", "raising", False, id="raising-registry-is-anonymous"),
])
async def test_the_dm_knowledge_lookup_reads_as_the_addressed_agent(
    tmp_path: Path, agent_id: str, registry: str, sees_own: bool,
) -> None:
    store = await _store(tmp_path)
    await _write_bravo_secret(store)
    await store.write_notebook("Anvil", "own-topic", "engineering ANVIL-OWN-NOTE", department="engineering")
    await store.write_entry(
        author="Carol", path="reports/ship-briefing.md", content="engineering briefing for the whole ship",
        message="ship", classification="ship",
    )
    config = DmTargetedLookupConfig(
        enabled=True, enable_knowledge=True, timeout_ms=10_000, max_lookup_chars=100_000,
    )
    dispatcher = LookupDispatcher(runtime=_dm_runtime(store, registry), config=config)
    result = await dispatcher.maybe_lookup("what do the ship's records say about engineering", agent_id=agent_id)
    assert result is not None and result.lookup_type == "knowledge"
    assert "reports/ship-briefing.md" in result.content  # premise: the lookup ran and read the commons
    assert _SECRET not in result.content
    assert ("ANVIL-OWN-NOTE" in result.content) is sees_own


@pytest.mark.asyncio
async def test_the_records_search_route_still_returns_what_the_captain_may_read(tmp_path: Path) -> None:
    """The route serves the Captain's notebooks browser (AD-523b): a private note is in its results, as on the base."""
    store = await _store(tmp_path)
    await _write_bravo_secret(store)
    body = await search_records(q="engineering", scope="ship", runtime=SimpleNamespace(_records_store=store))
    assert [hit["path"] for hit in body["results"]] == [_BRAVO] and body["count"] == 1


@pytest.mark.asyncio
async def test_the_records_search_route_answers_an_unknown_scope_with_400(tmp_path: Path) -> None:
    store = await _store(tmp_path)
    await _write_bravo_secret(store)
    response = await search_records(
        q="engineering", scope="notebooks/Bravo", runtime=SimpleNamespace(_records_store=store),
    )
    assert isinstance(response, JSONResponse) and response.status_code == 400
    assert json.loads(response.body) == {"error": _SCOPE_ERROR}


def _own_nodes(func: ast.AST) -> Iterator[ast.AST]:
    """Every node inside ``func`` that is not inside a nested function or lambda."""
    stack = list(ast.iter_child_nodes(func))
    while stack:
        node = stack.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            continue
        yield node
        stack.extend(ast.iter_child_nodes(node))


@functools.cache
def _records_search_calls() -> dict[tuple[str, str], tuple[ast.Call, ...]]:
    """``.search(...)`` calls whose receiver names Ship's Records, directly or through a local bound to it."""
    found: dict[tuple[str, str], list[ast.Call]] = {}
    for path in sorted(_SRC.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for func in ast.walk(tree):
            if not isinstance(func, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            nodes = list(_own_nodes(func))
            aliases = {
                target.id
                for node in nodes if isinstance(node, ast.Assign) and "records" in ast.unparse(node.value)
                for target in node.targets if isinstance(target, ast.Name)
            }
            for node in nodes:
                if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
                    continue
                receiver = node.func.value
                named = "records" in ast.unparse(receiver)
                aliased = isinstance(receiver, ast.Name) and receiver.id in aliases
                if node.func.attr == "search" and (named or aliased):
                    found.setdefault((path.relative_to(_SRC).as_posix(), func.name), []).append(node)
    return {caller: tuple(calls) for caller, calls in found.items()}


def test_the_census_finds_the_four_records_search_callers() -> None:
    """Acceptance 2's premise: the census sees the four callers and nothing else."""
    found = _records_search_calls()
    assert set(found) == _RECORDS_SEARCH_CALLERS, (
        "a RecordsStore.search caller was added, moved or renamed: give it a reader_id, then name it in "
        "_RECORDS_SEARCH_CALLERS, or in _DELIBERATELY_ANONYMOUS with its reason"
    )
    assert set(_DELIBERATELY_ANONYMOUS) <= set(found)  # no entry outlives its call


@pytest.mark.xfail(strict=True, reason=_M3)
def test_every_records_search_caller_in_src_passes_a_reader() -> None:
    """Acceptance 2: each caller passes ``reader_id`` or is named, with its reason, as deliberately anonymous."""
    for caller, calls in _records_search_calls().items():
        for call in calls:
            passes_reader = any(keyword.arg == "reader_id" for keyword in call.keywords)
            assert passes_reader or caller in _DELIBERATELY_ANONYMOUS, f"{caller} searches with no reader"
