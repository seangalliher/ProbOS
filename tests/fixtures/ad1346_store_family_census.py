"""AD-1346 M3e4c2 (#1604): the census of #1604 property 1's store-write class: its ChromaDB and JetStream writes.

``vector_write_scan`` parses one module and reports each ChromaDB write in it (D245): a call that passes an ``ids``
keyword and whose function, or whose first positional argument, is an attribute named in ``VECTOR_RECORD_WRITES``,
and a call whose function is an attribute named in ``VECTOR_COLLECTION_WRITES``. ``bus_write_scan`` reports each call
whose function is an attribute named in ``BUS_WRITES`` (D246). A point is (enclosing scope, line, that attribute's
name), scoped as ``sql_write_scan`` of ``tests/fixtures/ad1346_store_census.py`` scopes one. ``vector_write_points``
runs the first scan over every ``src`` module, and ``bus_write_points`` the second over every ``src`` module except
``NATS_BUS``, the module that defines the bus. ``VECTOR_WRITE_SCOPES`` and ``BUS_WRITE_SCOPES`` give each (file,
enclosing scope) that holds a point a ``StoreCheck``, a ``System`` or a ``Pending`` (D247, D248, D251), and
``BUS_AGENT_ATTRIBUTED`` names, for each pending row, a scope that records the author (D251).

Among what the scans cannot see (register R127): ``ids`` passed by position or through ``**``, a method reached
through ``getattr`` or bound to a name before its call, a core NATS publish to a subject a stream holds, and a write
another process makes. ``tests/test_ad1346_admission_store_family_census.py`` checks the rows against the code.
"""

from __future__ import annotations

import ast
import functools
from collections.abc import Callable
from typing import Final

from tests.fixtures.ad1346_effect_census import SHIP, Pending, System, src_sources
from tests.fixtures.ad1346_store_census import StoreCheck

#: AD-1346 M3e4c2 (D245): ChromaDB's record writes, each a point when its call passes an ``ids`` keyword.
VECTOR_RECORD_WRITES: Final = frozenset({"add", "upsert", "update", "delete"})
#: AD-1346 M3e4c2 (D245): ChromaDB's collection writes.
VECTOR_COLLECTION_WRITES: Final = frozenset({"create_collection", "get_or_create_collection", "delete_collection", "modify"})
#: AD-1346 M3e4c2 (D246): the bus methods that write a JetStream message or create a stream.
BUS_WRITES: Final = frozenset({"js_publish", "ensure_stream", "recreate_stream"})
#: The module that defines the bus; ``bus_write_points`` leaves it out (D246).
NATS_BUS: Final = "src/probos/mesh/nats_bus.py"

#: (file, scope, line, the attribute's name).
Point = tuple[str, str, int, str]


def _attribute(node: ast.expr) -> str:
    """``node``'s attribute name when ``node`` is an attribute, else the empty string."""
    return node.attr if isinstance(node, ast.Attribute) else ""


def _vector_write(node: ast.Call) -> str:
    """The name that makes ``node`` a ChromaDB write (D245), else the empty string."""
    name = _attribute(node.func)
    if name in VECTOR_COLLECTION_WRITES:
        return name
    if not any(keyword.arg == "ids" for keyword in node.keywords):
        return ""
    for candidate in (name, _attribute(node.args[0]) if node.args else ""):
        if candidate in VECTOR_RECORD_WRITES:
            return candidate
    return ""


def _bus_write(node: ast.Call) -> str:
    """The name that makes ``node`` a JetStream write (D246), else the empty string."""
    name = _attribute(node.func)
    return name if name in BUS_WRITES else ""


class _CallScan(ast.NodeVisitor):
    def __init__(self, write: Callable[[ast.Call], str]) -> None:
        self.write = write
        self.scope: list[str] = []
        self.points: list[tuple[str, int, str]] = []

    def _enter(self, node: ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        self.scope.append(node.name)
        self.generic_visit(node)
        self.scope.pop()

    visit_ClassDef = visit_FunctionDef = visit_AsyncFunctionDef = _enter

    def visit_Call(self, node: ast.Call) -> None:
        name = self.write(node)
        if name:
            self.points.append((".".join(self.scope) or "<module>", node.lineno, name))
        self.generic_visit(node)


def _scan(tree: ast.Module, write: Callable[[ast.Call], str]) -> list[tuple[str, int, str]]:
    scan = _CallScan(write)
    scan.visit(tree)
    return scan.points


def vector_write_scan(source: str, filename: str = "<chroma>") -> list[tuple[str, int, str]]:
    """(scope, line, name) of each ChromaDB write in one module's source (AD-1346 M3e4c2, D245)."""
    return _scan(ast.parse(source, filename=filename), _vector_write)


def bus_write_scan(source: str, filename: str = "<bus>") -> list[tuple[str, int, str]]:
    """(scope, line, name) of each JetStream write in one module's source (AD-1346 M3e4c2, D246)."""
    return _scan(ast.parse(source, filename=filename), _bus_write)


@functools.lru_cache(maxsize=1)
def _family_points() -> tuple[tuple[Point, ...], tuple[Point, ...]]:
    """Both scans over ``src``, each module parsed once: (the ChromaDB points, the JetStream points)."""
    vector: list[Point] = []
    bus: list[Point] = []
    for rel, source in src_sources().items():
        tree = ast.parse(source, filename=rel)
        vector.extend((rel, *point) for point in _scan(tree, _vector_write))
        if rel != NATS_BUS:
            bus.extend((rel, *point) for point in _scan(tree, _bus_write))
    return tuple(vector), tuple(bus)


def vector_write_points() -> tuple[Point, ...]:
    """(file, scope, line, name) of each ChromaDB write in ``src``."""
    return _family_points()[0]


def bus_write_points() -> tuple[Point, ...]:
    """(file, scope, line, name) of each JetStream write in ``src`` outside ``NATS_BUS``."""
    return _family_points()[1]


_EPISODIC: Final = "src/probos/cognitive/episodic.py"
_SEMANTIC: Final = "src/probos/knowledge/semantic.py"
_BACKFILL: Final = "src/probos/perception/backfill.py"
_PROCEDURES: Final = "src/probos/cognitive/procedure_store.py"
_EVOLUTION: Final = "src/probos/cognitive/self_improvement/evolution_store.py"

#: AD-1346 M3e4c2 (D247, D248): each (file, enclosing scope) that holds a ChromaDB write -> its coverage.
VECTOR_WRITE_SCOPES: Final[dict[tuple[str, str], StoreCheck | System]] = {
    # Agent-attributed (D218): the episode's vector, under the check STORE_WRITE_SCOPES gives the scope (D248).
    (_EPISODIC, "EpisodicMemory.store"): StoreCheck((_EPISODIC, "EpisodicMemory.store"), "_sole_agent_id(episode)"),
    # System (D218, D239, D248): each reason names what the scope writes.
    (_EPISODIC, "migrate_episode_agent_ids"): System(SHIP, "episodes' agent ids, migrated from slot ids to sovereign ids"),
    (_EPISODIC, "migrate_anchor_metadata"): System(SHIP, "episodes' anchor fields, promoted to top-level metadata"),
    (_EPISODIC, "migrate_embedding_model"): System(SHIP, "the episode collection, recreated for a new embedding model, with copies of its episodes (D218)"),
    (_EPISODIC, "migrate_enriched_embedding"): System(SHIP, "episodes' documents rebuilt with enriched text, and the collection's version marker"),
    (_EPISODIC, "sweep_hash_integrity"): System(SHIP, "episodes' content hashes, recomputed"),
    (_EPISODIC, "_verify_episode_hash"): System(SHIP, "an episode's content hash, recomputed"),
    (_EPISODIC, "EpisodicMemory.start"): System(SHIP, "the episode collection and its metadata"),
    (_EPISODIC, "EpisodicMemory.seed"): System(SHIP, "the bulk seed of episodes"),
    (_EPISODIC, "EpisodicMemory.update_episode_metadata"): System(SHIP, "an episode's metadata fields, merged"),
    (_EPISODIC, "EpisodicMemory.update_episode_validity"): System(SHIP, "an episode's valid_until time"),
    (_EPISODIC, "EpisodicMemory._force_update"): System(SHIP, "an episode overwritten in place, which the method's docstring reserves for migration"),
    (_EPISODIC, "EpisodicMemory._remove_from_live"): System(SHIP, "episodes deleted from the live collection"),
    (_EPISODIC, "EpisodicMemory._write_restore_sidecars"): System(SHIP, "an episode restore_from_archive copies back (D218)"),
    (_SEMANTIC, "SemanticKnowledgeLayer.start"): System(SHIP, "the knowledge collections and an embedding-conflict marker"),
    (_SEMANTIC, "SemanticKnowledgeLayer._migrate_collections_if_needed"): System(SHIP, "a knowledge collection, recreated for a new embedding model"),
    (_SEMANTIC, "SemanticKnowledgeLayer.index_agent"): System(SHIP, "an agent type's index entry"),
    (_SEMANTIC, "SemanticKnowledgeLayer.index_skill"): System(SHIP, "a skill's index entry"),
    (_SEMANTIC, "SemanticKnowledgeLayer.index_workflow"): System(SHIP, "a workflow pattern's index entry"),
    (_SEMANTIC, "SemanticKnowledgeLayer.index_qa_report"): System(SHIP, "an agent type's QA verdict"),
    (_SEMANTIC, "SemanticKnowledgeLayer.index_event"): System(SHIP, "a system event's index entry"),
    (_SEMANTIC, "SemanticKnowledgeLayer.index_record"): System(SHIP, "a Ship's Records document's index entry: a copy of its text with its author, an agent's id, a callsign or a literal (D218)"),
    (_BACKFILL, "backfill_perception_episode_agent_ids"): System(SHIP, "perception episodes that name no agent, stamped with the observers' agent ids, each document written back as read"),
    (_PROCEDURES, "ProcedureStore._init_chroma"): System(SHIP, "the procedure collection"),
    (_PROCEDURES, "ProcedureStore._rebuild_chroma_from_sqlite"): System(SHIP, "the procedure collection's embedding model and state marker"),
    (_PROCEDURES, "ProcedureStore._write_to_chroma"): System(SHIP, "a procedure's search entry: its name, description and preconditions, with its evolution type, active and negative flags, compilation level and intent types, and no agent id"),
    (_PROCEDURES, "ProcedureStore.delete"): System(SHIP, "a procedure's search entry, deleted"),
    (_PROCEDURES, "ProcedureStore.deactivate"): System(SHIP, "a procedure's active flag"),
    (_PROCEDURES, "ProcedureStore.decay_stale_procedures"): System(SHIP, "a procedure's compilation level"),
    (_PROCEDURES, "ProcedureStore.archive_stale_procedures"): System(SHIP, "an archived procedure's search entry, deleted"),
    (_EVOLUTION, "EvolutionStore.start"): System(SHIP, "the evolution store's collection"),
    (_EVOLUTION, "EvolutionStore._finalize_stable"): System(SHIP, "a collection's embedding model and state marker"),
    (_EVOLUTION, "EvolutionStore._clear_transaction_markers"): System(SHIP, "a collection's metadata without its transaction markers"),
    (_EVOLUTION, "EvolutionStore._delete_owned_temporary"): System(SHIP, "a temporary collection, deleted"),
    (_EVOLUTION, "EvolutionStore._rename_collection"): System(SHIP, "a collection's name"),
    (_EVOLUTION, "EvolutionStore._transition_collection"): System(SHIP, "a shadow collection: a copy of the source collection's rows, and both collections' state markers (D218)"),
    (_EVOLUTION, "EvolutionStore._rollback_candidate_to_backup"): System(SHIP, "a failed candidate collection's role and state markers"),
    (_EVOLUTION, "EvolutionStore._recover_interrupted_state"): System(SHIP, "a failed shadow collection's role and state markers"),
    (_EVOLUTION, "EvolutionStore.record_lesson"): System(SHIP, "a lesson: a summary, a category, an outcome and the proposal it came from, with no author id (D239)"),
}

#: AD-1346 M3e4c2 (D251): a JetStream write scope that publishes an agent's text under its author's id.
_BUS_AGENT_ATTRIBUTED: Final = Pending("M3e4d", "agent-attributed (D239, D251): BUS_AGENT_ATTRIBUTED names a scope that records the author (register R113)")

#: AD-1346 M3e4c2 (D251): each (file, scope) of ``BUS_WRITE_SCOPES`` whose row is ``Pending("M3e4d")`` -> (a file, a
#: scope in it that builds a payload the row's scope publishes, the name in that scope of the id the payload records,
#: under a key of the same name, as its author).
BUS_AGENT_ATTRIBUTED: Final[dict[tuple[str, str], tuple[str, str, str]]] = {
    ("src/probos/runtime.py", "ProbOSRuntime._emit_event"): ("src/probos/cognitive/sub_tasks/query.py", "_query_oracle_lookup", "agent_id"),
    ("src/probos/cognitive/chain_nats_bridge.py", "ChainNATSBridge._safe_publish"): ("src/probos/cognitive/chain_nats_bridge.py", "ChainNATSBridge._build_payload", "agent_id"),
}

#: AD-1346 M3e4c2 (D247, D248, D251): each (file, enclosing scope) outside ``NATS_BUS`` that holds a JetStream write ->
#: its coverage.
BUS_WRITE_SCOPES: Final[dict[tuple[str, str], System | Pending]] = {
    ("src/probos/mesh/intent.py", "IntentBus.dispatch_async"): System(SHIP, "an intent's fields as _serialize_intent writes them, for the agent it targets; a Ward Room notification holds an event's author id and title and its thread's text, copies of rows the Ward Room stores (D218)"),
    ("src/probos/runtime.py", "ProbOSRuntime._emit_event"): _BUS_AGENT_ATTRIBUTED,
    ("src/probos/startup/communication.py", "init_communication._ward_room_emit"): System(SHIP, "a Ward Room event's type and data: ids, scores, settings, a prune summary, and a new thread's or post's author id, title or mentions, copies of rows the Ward Room has stored (D218)"),
    ("src/probos/cognitive/chain_nats_bridge.py", "ChainNATSBridge._safe_publish"): _BUS_AGENT_ATTRIBUTED,
    ("src/probos/cognitive/chain_nats_bridge.py", "ChainNATSBridge.ensure_stream"): System(SHIP, "the cognitive chain stream"),
    ("src/probos/startup/nats.py", "init_nats"): System(SHIP, "the four streams, recreated, which deletes the messages they held"),
}
