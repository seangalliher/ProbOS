"""BF-679: Oracle records queries must respect the reader's identity.

Before this fix ``build_records_scope_filter("ship")`` emitted
``{'classification': {'$in': ['private', 'department', 'ship']}}`` and
``RecordsStore.search(scope="ship")`` was level-only, so Oracle Tier 2 handed
every agent's ``private`` and out-of-department notebook entries to every other
agent — on both retrieval paths.

Real fixtures throughout (BF-287): a real ``RecordsStore`` and a real
``SemanticKnowledgeLayer`` on ``tmp_path``. Nothing here mocks ChromaDB, so the
generated ``where`` clauses are executed by the installed engine — the
``$and``/``$or`` arity rule is a runtime error, not a review-time one.

**The absent-reader decision, pinned by test:** an identity-less caller is
*anonymous*, not privileged. It receives ``ship`` records and is withheld the
identity-gated classifications. ``"captain"`` remains unrestricted, matching
``RecordsStore.read_entry``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from probos.cognitive.oracle_service import (
    OracleService,
    make_reader_identity_resolver,
)
from probos.config import RecordsConfig
from probos.knowledge.records_store import RecordsStore, record_is_readable
from probos.knowledge.semantic import (
    SemanticKnowledgeLayer,
    build_records_scope_filter,
)
from probos.tools.oracle_query_tool import OracleQueryTool

_ALL_SCOPES = ("private", "department", "ship", "fleet", "nonsense")
_ALL_READERS = (None, "", "captain", "alice", "bob", "erin")
_ALL_DEPARTMENTS = ("", "engineering", "medical")

_PRIVATE = "reports/alice-private.md"
_DEPARTMENT = "reports/bob-department.md"
_SHIP = "reports/carol-ship.md"
_FLEET = "reports/dave-fleet.md"


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

@pytest.fixture
async def records(tmp_path: Path) -> RecordsStore:
    cfg = RecordsConfig(repo_path=str(tmp_path / "ship-records"), auto_commit=False)
    store = RecordsStore(cfg)
    await store.initialize()
    return store


@pytest.fixture
async def layer(tmp_path: Path):
    sk = SemanticKnowledgeLayer(db_path=tmp_path / "semantic", episodic_memory=None)
    await sk.start()
    try:
        yield sk
    finally:
        await sk.stop()


async def _seed(store: RecordsStore) -> None:
    """One record per classification, all sharing the token 'reactor'."""
    await store.write_entry(
        author="alice", path=_PRIVATE,
        content="reactor coolant readings alice keeps to herself",
        message="private", classification="private", department="engineering",
    )
    await store.write_entry(
        author="bob", path=_DEPARTMENT,
        content="reactor maintenance schedule for the engineering department",
        message="department", classification="department", department="engineering",
    )
    await store.write_entry(
        author="carol", path=_SHIP,
        content="reactor status briefing for the whole ship",
        message="ship", classification="ship",
    )
    await store.write_entry(
        author="dave", path=_FLEET,
        content="reactor doctrine shared across the fleet",
        message="fleet", classification="fleet",
    )


async def _keyword_paths(
    store: RecordsStore, reader_id: str | None, department: str = "",
) -> set[str]:
    rows = await store.search(
        "reactor", scope="ship",
        reader_id=reader_id, reader_department=department,
    )
    return {r["path"] for r in rows}


async def _semantic_paths(
    sk: SemanticKnowledgeLayer, reader_id: str | None, department: str = "",
) -> set[str]:
    rows = await sk.search(
        "reactor", types=["records"], limit=50, records_scope="ship",
        reader_id=reader_id, reader_department=department,
    )
    return {(r.get("metadata") or {}).get("path", "") for r in rows}


class _FakeAgent:
    def __init__(
        self, agent_id: str, *, callsign: str = "", agent_type: str = "",
        sovereign_id: str = "",
    ) -> None:
        self.id = agent_id
        self.callsign = callsign
        self.agent_type = agent_type
        self.sovereign_id = sovereign_id


class _FakeRegistry:
    def __init__(self, agents: list[_FakeAgent]) -> None:
        self._agents = {a.id: a for a in agents}

    def get(self, agent_id: str) -> _FakeAgent | None:
        return self._agents.get(agent_id)

    def all(self) -> list[_FakeAgent]:
        return list(self._agents.values())


class _FakeOntology:
    def __init__(self, departments: dict[str, str | None]) -> None:
        self._departments = departments

    def get_agent_department(self, agent_type: str) -> str | None:
        return self._departments.get(agent_type)


def _crew_resolver():
    """alice (engineering), bob (engineering), erin (medical)."""
    registry = _FakeRegistry([
        _FakeAgent("agent-alice", callsign="alice", agent_type="engineer"),
        _FakeAgent("agent-bob", callsign="bob", agent_type="engineer"),
        _FakeAgent("agent-erin", callsign="erin", agent_type="doctor"),
    ])
    ontology = _FakeOntology({"engineer": "engineering", "doctor": "medical"})
    return make_reader_identity_resolver(registry=registry, ontology=ontology)


def _oracle(
    *,
    records_store: Any = None,
    semantic_layer: Any = None,
    enabled: bool = False,
    resolver: Any = None,
) -> OracleService:
    return OracleService(
        records_store=records_store,
        semantic_layer=semantic_layer,
        records_semantic_enabled=enabled,
        reader_identity_resolver=resolver,
    )


def _tier2_paths(results: list[Any]) -> set[str]:
    return {r.metadata["path"] for r in results if r.source_tier == "records"}


# ---------------------------------------------------------------------------
# 1. HEADLINE — fails on a pre-fix tree, on BOTH retrieval paths
# ---------------------------------------------------------------------------

class TestHeadlinePrivateRecordIsNotReachable:
    @pytest.mark.parametrize("semantic", [False, True], ids=["keyword", "semantic"])
    async def test_agent_b_cannot_read_agent_as_private_record(
        self, records, layer, semantic: bool,
    ) -> None:
        """Alice's private record reaches Alice's Oracle query and not Bob's."""
        records.set_semantic_indexer(layer)
        await _seed(records)
        oracle = _oracle(
            records_store=records, semantic_layer=layer,
            enabled=semantic, resolver=_crew_resolver(),
        )

        as_alice = await oracle.query(
            "reactor", agent_id="agent-alice", k_per_tier=10, tiers=["records"],
        )
        as_bob = await oracle.query(
            "reactor", agent_id="agent-bob", k_per_tier=10, tiers=["records"],
        )

        assert _PRIVATE in _tier2_paths(as_alice)
        assert _PRIVATE not in _tier2_paths(as_bob)
        # Not a vacuous pass: Bob still receives the commons.
        assert _SHIP in _tier2_paths(as_bob)

    @pytest.mark.parametrize("semantic", [False, True], ids=["keyword", "semantic"])
    async def test_agent_query_tool_withholds_another_agents_private_record(
        self, records, layer, semantic: bool,
    ) -> None:
        """End-to-end through the AD-1139 tool, which is the reach that made
        this a governance defect rather than a latent one."""
        records.set_semantic_indexer(layer)
        await _seed(records)
        tool = OracleQueryTool(oracle=_oracle(
            records_store=records, semantic_layer=layer,
            enabled=semantic, resolver=_crew_resolver(),
        ))

        alice = await tool.invoke(
            {"query": "reactor", "kind": "records"}, {"agent_id": "agent-alice"},
        )
        bob = await tool.invoke(
            {"query": "reactor", "kind": "records"}, {"agent_id": "agent-bob"},
        )

        assert alice.error is None and bob.error is None
        assert "keeps to herself" in alice.output
        assert "keeps to herself" not in bob.output
        assert "whole ship" in bob.output


# ---------------------------------------------------------------------------
# 2. Semantic / keyword parity — neither path may be looser than the other
# ---------------------------------------------------------------------------

class TestPathParity:
    @pytest.mark.parametrize("reader_id", _ALL_READERS)
    @pytest.mark.parametrize("department", _ALL_DEPARTMENTS)
    async def test_store_and_filter_admit_the_same_records(
        self, records, layer, reader_id: str | None, department: str,
    ) -> None:
        """The keyword predicate and the ChromaDB filter are twins."""
        records.set_semantic_indexer(layer)
        await _seed(records)

        keyword = await _keyword_paths(records, reader_id, department)
        semantic = await _semantic_paths(layer, reader_id, department)

        assert keyword == semantic

    @pytest.mark.parametrize(
        "agent_id", ["", "captain", "agent-alice", "agent-bob", "agent-erin", "ghost"],
    )
    async def test_oracle_tier2_paths_agree_for_the_same_caller(
        self, records, layer, agent_id: str,
    ) -> None:
        """Same assertion one level up: whichever path Tier 2 takes, the
        admissible set is identical, so the AD-1138 fallback can never
        disclose more than the path it replaces."""
        records.set_semantic_indexer(layer)
        await _seed(records)
        resolver = _crew_resolver()
        keyword_oracle = _oracle(
            records_store=records, semantic_layer=layer,
            enabled=False, resolver=resolver,
        )
        semantic_oracle = _oracle(
            records_store=records, semantic_layer=layer,
            enabled=True, resolver=resolver,
        )

        keyword = await keyword_oracle.query(
            "reactor", agent_id=agent_id, k_per_tier=10, tiers=["records"],
        )
        semantic = await semantic_oracle.query(
            "reactor", agent_id=agent_id, k_per_tier=10, tiers=["records"],
        )

        assert _tier2_paths(keyword) == _tier2_paths(semantic)

    async def test_empty_semantic_result_falls_back_without_widening(
        self, records, layer,
    ) -> None:
        """The honest-degrade fallback is the obvious place for a leak: the
        semantic filter admits nothing, so Tier 2 re-runs on keyword. It must
        re-run with the SAME reader."""
        records.set_semantic_indexer(layer)
        await records.write_entry(
            author="alice", path=_PRIVATE, content="reactor coolant readings",
            message="private", classification="private", department="engineering",
        )
        oracle = _oracle(
            records_store=records, semantic_layer=layer,
            enabled=True, resolver=_crew_resolver(),
        )

        as_bob = await oracle.query(
            "reactor", agent_id="agent-bob", k_per_tier=10, tiers=["records"],
        )

        assert _tier2_paths(as_bob) == set()


# ---------------------------------------------------------------------------
# 3. The absent-reader decision — anonymous, not privileged
# ---------------------------------------------------------------------------

class TestAbsentReaderIsAnonymous:
    @pytest.mark.parametrize("semantic", [False, True], ids=["keyword", "semantic"])
    async def test_identity_less_caller_gets_the_commons_only(
        self, records, layer, semantic: bool,
    ) -> None:
        records.set_semantic_indexer(layer)
        await _seed(records)
        oracle = _oracle(
            records_store=records, semantic_layer=layer,
            enabled=semantic, resolver=_crew_resolver(),
        )

        results = await oracle.query(
            "reactor", agent_id="", k_per_tier=10, tiers=["records"],
        )

        assert _tier2_paths(results) == {_SHIP}

    @pytest.mark.parametrize("semantic", [False, True], ids=["keyword", "semantic"])
    async def test_unresolvable_agent_is_anonymous_not_privileged(
        self, records, layer, semantic: bool,
    ) -> None:
        """An id the registry does not know must narrow, never widen."""
        records.set_semantic_indexer(layer)
        await _seed(records)
        oracle = _oracle(
            records_store=records, semantic_layer=layer,
            enabled=semantic, resolver=_crew_resolver(),
        )

        results = await oracle.query(
            "reactor", agent_id="ghost", k_per_tier=10, tiers=["records"],
        )

        assert _tier2_paths(results) == {_SHIP}

    @pytest.mark.parametrize("semantic", [False, True], ids=["keyword", "semantic"])
    async def test_captain_reads_unrestricted_without_a_resolver(
        self, records, layer, semantic: bool,
    ) -> None:
        """The Captain keeps ``read_entry``'s unrestricted reach even before
        the resolver is attached — that is what makes fail-closed affordable."""
        records.set_semantic_indexer(layer)
        await _seed(records)
        oracle = _oracle(
            records_store=records, semantic_layer=layer,
            enabled=semantic, resolver=None,
        )

        results = await oracle.query(
            "reactor", agent_id="captain", k_per_tier=10, tiers=["records"],
        )

        assert _tier2_paths(results) == {_PRIVATE, _DEPARTMENT, _SHIP}

    @pytest.mark.parametrize("semantic", [False, True], ids=["keyword", "semantic"])
    async def test_unattached_resolver_degrades_closed(
        self, records, layer, semantic: bool,
    ) -> None:
        records.set_semantic_indexer(layer)
        await _seed(records)
        oracle = _oracle(
            records_store=records, semantic_layer=layer,
            enabled=semantic, resolver=None,
        )

        results = await oracle.query(
            "reactor", agent_id="agent-alice", k_per_tier=10, tiers=["records"],
        )

        assert _tier2_paths(results) == {_SHIP}


# ---------------------------------------------------------------------------
# 4. The classification rules themselves, end to end through the Oracle
# ---------------------------------------------------------------------------

class TestClassificationRules:
    @pytest.mark.parametrize("semantic", [False, True], ids=["keyword", "semantic"])
    async def test_ship_records_are_unaffected(
        self, records, layer, semantic: bool,
    ) -> None:
        records.set_semantic_indexer(layer)
        await _seed(records)
        oracle = _oracle(
            records_store=records, semantic_layer=layer,
            enabled=semantic, resolver=_crew_resolver(),
        )

        for agent_id in ("", "captain", "agent-alice", "agent-erin", "ghost"):
            results = await oracle.query(
                "reactor", agent_id=agent_id, k_per_tier=10, tiers=["records"],
            )
            assert _SHIP in _tier2_paths(results), agent_id

    @pytest.mark.parametrize("semantic", [False, True], ids=["keyword", "semantic"])
    async def test_department_record_reaches_same_department_only(
        self, records, layer, semantic: bool,
    ) -> None:
        records.set_semantic_indexer(layer)
        await _seed(records)
        oracle = _oracle(
            records_store=records, semantic_layer=layer,
            enabled=semantic, resolver=_crew_resolver(),
        )

        # alice: engineering, not the author — admitted by department.
        insider = await oracle.query(
            "reactor", agent_id="agent-alice", k_per_tier=10, tiers=["records"],
        )
        # erin: medical, not the author — withheld.
        outsider = await oracle.query(
            "reactor", agent_id="agent-erin", k_per_tier=10, tiers=["records"],
        )

        assert _DEPARTMENT in _tier2_paths(insider)
        assert _DEPARTMENT not in _tier2_paths(outsider)

    @pytest.mark.parametrize("semantic", [False, True], ids=["keyword", "semantic"])
    async def test_author_reads_own_records_at_every_classification(
        self, records, layer, semantic: bool,
    ) -> None:
        """Bob authors one record per classification; every one comes back."""
        records.set_semantic_indexer(layer)
        for label in ("private", "department", "ship"):
            await records.write_entry(
                author="bob", path=f"reports/bob-{label}.md",
                content=f"reactor {label} note authored by bob",
                message=label, classification=label,
                # Deliberately a department bob does NOT belong to, so only the
                # authorship clause can admit the department record.
                department="medical",
            )
        oracle = _oracle(
            records_store=records, semantic_layer=layer,
            enabled=semantic, resolver=_crew_resolver(),
        )

        results = await oracle.query(
            "reactor", agent_id="agent-bob", k_per_tier=10, tiers=["records"],
        )

        assert _tier2_paths(results) == {
            "reports/bob-private.md",
            "reports/bob-department.md",
            "reports/bob-ship.md",
        }

    @pytest.mark.parametrize("semantic", [False, True], ids=["keyword", "semantic"])
    async def test_fleet_records_stay_out_of_tier2(
        self, records, layer, semantic: bool,
    ) -> None:
        """Guard on the contradiction BF-679 deliberately did not touch."""
        records.set_semantic_indexer(layer)
        await _seed(records)
        oracle = _oracle(
            records_store=records, semantic_layer=layer,
            enabled=semantic, resolver=_crew_resolver(),
        )

        results = await oracle.query(
            "reactor", agent_id="captain", k_per_tier=10, tiers=["records"],
        )

        assert _FLEET not in _tier2_paths(results)


# ---------------------------------------------------------------------------
# 5. ChromaDB filter shape across the whole input matrix
# ---------------------------------------------------------------------------

class TestFilterShape:
    def test_no_generated_filter_has_a_short_and_or(self) -> None:
        """ChromaDB requires ``$and``/``$or`` to hold at least two expressions.

        The permitted-label set shrinks with scope and reader, so the clause
        count is data-dependent — walk the whole matrix rather than sampling.
        """

        def _walk(node: Any) -> None:
            if not isinstance(node, dict):
                return
            for key, value in node.items():
                if key in ("$and", "$or"):
                    assert isinstance(value, list) and len(value) >= 2, (
                        f"{key} must hold >= 2 expressions, got {value!r}"
                    )
                    for child in value:
                        _walk(child)
                else:
                    _walk(value)

        for scope in _ALL_SCOPES:
            for reader_id in _ALL_READERS:
                for department in _ALL_DEPARTMENTS:
                    where = build_records_scope_filter(
                        scope, reader_id=reader_id, reader_department=department,
                    )
                    if where is not None:
                        _walk(where)

    async def test_every_generated_filter_executes_against_chromadb(
        self, records, layer,
    ) -> None:
        """The arity rule fires at query time, not review time — so run them."""
        records.set_semantic_indexer(layer)
        await _seed(records)
        collection = layer._collections["records"]

        for scope in _ALL_SCOPES:
            for reader_id in _ALL_READERS:
                for department in _ALL_DEPARTMENTS:
                    where = build_records_scope_filter(
                        scope, reader_id=reader_id, reader_department=department,
                    )
                    if where is None:
                        continue
                    collection.query(
                        query_texts=["reactor"], n_results=4, where=where,
                    )

    def test_anonymous_reader_emits_the_identity_layer(self) -> None:
        """The one-line defect: ``""`` used to take the unrestricted branch."""
        where = build_records_scope_filter("ship", reader_id="")

        assert "$or" in where
        assert {"classification": {"$in": ["ship"]}} in where["$or"]
        assert {"$and": [
            {"classification": {"$in": ["private", "department"]}},
            {"author": ""},
        ]} in where["$or"]

    def test_unspecified_reader_keeps_the_scope_only_filter(self) -> None:
        """``None`` is the pre-BF-679 contract, preserved for AD-1138 callers."""
        where = build_records_scope_filter("ship", reader_id=None)

        assert where == {"classification": {"$in": ["private", "department", "ship"]}}

    def test_anonymous_reader_at_private_scope_stays_flat(self) -> None:
        """Only one clause survives, so it must not be wrapped in a 1-element $or."""
        where = build_records_scope_filter("private", reader_id="")

        assert where == {"$and": [
            {"classification": {"$in": ["private"]}}, {"author": ""},
        ]}


# ---------------------------------------------------------------------------
# 6. record_is_readable — the keyword-side predicate
# ---------------------------------------------------------------------------

class TestRecordIsReadable:
    def test_unspecified_reader_applies_scope_level_only(self) -> None:
        fm = {"classification": "private", "author": "alice"}

        assert record_is_readable(fm, scope="ship") is True
        assert record_is_readable(fm, scope="ship", reader_id=None) is True

    def test_anonymous_reader_is_denied_gated_classifications(self) -> None:
        assert record_is_readable(
            {"classification": "private", "author": "alice"},
            scope="ship", reader_id="",
        ) is False
        assert record_is_readable(
            {"classification": "department", "author": "alice",
             "department": "engineering"},
            scope="ship", reader_id="",
        ) is False

    def test_anonymous_reader_still_sees_ship(self) -> None:
        assert record_is_readable(
            {"classification": "ship"}, scope="ship", reader_id="",
        ) is True

    def test_captain_is_unrestricted_within_scope(self) -> None:
        assert record_is_readable(
            {"classification": "private", "author": "alice"},
            scope="ship", reader_id="captain",
        ) is True

    def test_scope_level_still_bounds_the_captain(self) -> None:
        assert record_is_readable(
            {"classification": "fleet"}, scope="ship", reader_id="captain",
        ) is False

    def test_author_reads_own_private_record(self) -> None:
        assert record_is_readable(
            {"classification": "private", "author": "alice"},
            scope="ship", reader_id="alice",
        ) is True

    def test_author_reads_own_department_record_from_another_department(self) -> None:
        assert record_is_readable(
            {"classification": "department", "author": "bob",
             "department": "engineering"},
            scope="ship", reader_id="bob", reader_department="medical",
        ) is True

    def test_same_department_reads_a_department_record(self) -> None:
        assert record_is_readable(
            {"classification": "department", "author": "bob",
             "department": "engineering"},
            scope="ship", reader_id="erin", reader_department="engineering",
        ) is True

    def test_other_department_is_denied(self) -> None:
        assert record_is_readable(
            {"classification": "department", "author": "bob",
             "department": "engineering"},
            scope="ship", reader_id="erin", reader_department="medical",
        ) is False

    def test_departmentless_reader_is_denied_a_departmentless_record(self) -> None:
        """Documented divergence from ``read_entry``: empty does not match
        empty, because the ChromaDB twin omits the clause entirely and parity
        is the requirement. Of the two behaviours, closed is the safe one."""
        assert record_is_readable(
            {"classification": "department", "author": "bob"},
            scope="ship", reader_id="erin",
        ) is False

    def test_missing_classification_defaults_to_ship(self) -> None:
        assert record_is_readable({}, scope="ship", reader_id="") is True

    def test_unknown_classification_takes_the_level_zero_default(self) -> None:
        """Byte-identical to the pre-BF-679 inline check in ``search``."""
        assert record_is_readable(
            {"classification": "top-secret"}, scope="private", reader_id=None,
        ) is True

    def test_unhashable_classification_does_not_raise(self) -> None:
        assert record_is_readable(
            {"classification": ["private"]}, scope="ship", reader_id="",
        ) is True

    def test_unknown_scope_defaults_to_ship_level(self) -> None:
        assert record_is_readable(
            {"classification": "fleet"}, scope="nonsense", reader_id=None,
        ) is False
        assert record_is_readable(
            {"classification": "ship"}, scope="nonsense", reader_id=None,
        ) is True


# ---------------------------------------------------------------------------
# 7. RecordsStore.search — opt-in identity, byte-identical default
# ---------------------------------------------------------------------------

class TestRecordsStoreSearch:
    async def test_default_call_is_unchanged_by_bf679(self, records) -> None:
        """``/records/search`` and self-monitoring pass no reader; they keep
        the level-only behaviour they have always had."""
        await _seed(records)

        rows = await records.search("reactor", scope="ship")

        assert {r["path"] for r in rows} == {_PRIVATE, _DEPARTMENT, _SHIP}

    async def test_anonymous_reader_withholds_gated_records(self, records) -> None:
        await _seed(records)

        rows = await records.search("reactor", scope="ship", reader_id="")

        assert {r["path"] for r in rows} == {_SHIP}

    async def test_reader_receives_own_and_department_records(self, records) -> None:
        await _seed(records)

        rows = await records.search(
            "reactor", scope="ship",
            reader_id="alice", reader_department="engineering",
        )

        assert {r["path"] for r in rows} == {_PRIVATE, _DEPARTMENT, _SHIP}

    async def test_result_shape_is_unchanged(self, records) -> None:
        await _seed(records)

        rows = await records.search("reactor", scope="ship", reader_id="captain")

        assert rows
        for row in rows:
            assert set(row) == {"path", "frontmatter", "score", "snippet"}

    async def test_empty_repository_returns_nothing(self, records) -> None:
        assert await records.search("reactor", scope="ship", reader_id="alice") == []


# ---------------------------------------------------------------------------
# 8. Reader-identity resolution
# ---------------------------------------------------------------------------

class TestMakeReaderIdentityResolver:
    def test_resolves_callsign_and_department(self) -> None:
        resolve = _crew_resolver()

        assert resolve("agent-alice") == ("alice", "engineering")
        assert resolve("agent-erin") == ("erin", "medical")

    def test_unknown_agent_resolves_to_anonymous(self) -> None:
        assert _crew_resolver()("ghost") == ("", "")

    def test_falls_back_to_the_sovereign_id(self) -> None:
        """AD-441 callers pass ``sovereign_id or id``; the registry keys on id."""
        registry = _FakeRegistry([
            _FakeAgent(
                "agent-alice", callsign="alice", agent_type="engineer",
                sovereign_id="sov-alice",
            ),
        ])
        resolve = make_reader_identity_resolver(
            registry=registry,
            ontology=_FakeOntology({"engineer": "engineering"}),
        )

        assert resolve("sov-alice") == ("alice", "engineering")

    def test_falls_back_to_agent_type_when_no_callsign(self) -> None:
        """Mirrors the write side: ``agent.callsign or agent.agent_type``."""
        registry = _FakeRegistry([_FakeAgent("a1", agent_type="engineer")])
        resolve = make_reader_identity_resolver(
            registry=registry,
            ontology=_FakeOntology({"engineer": "engineering"}),
        )

        assert resolve("a1") == ("engineer", "engineering")

    def test_unresolved_department_still_yields_the_reader(self) -> None:
        """Losing the department costs same-department reach, not authorship."""
        registry = _FakeRegistry([_FakeAgent("a1", callsign="alice", agent_type="x")])
        resolve = make_reader_identity_resolver(
            registry=registry, ontology=_FakeOntology({"x": None}),
        )

        assert resolve("a1") == ("alice", "")

    def test_agent_without_identity_resolves_to_anonymous(self) -> None:
        registry = _FakeRegistry([_FakeAgent("a1")])
        resolve = make_reader_identity_resolver(
            registry=registry, ontology=_FakeOntology({}),
        )

        assert resolve("a1") == ("", "")


class TestResolveRecordsReader:
    def test_empty_agent_id_is_anonymous(self) -> None:
        assert _oracle(resolver=_crew_resolver())._resolve_records_reader("") == ("", "")

    def test_non_string_agent_id_is_anonymous(self) -> None:
        oracle = _oracle(resolver=_crew_resolver())

        assert oracle._resolve_records_reader(None) == ("", "")  # type: ignore[arg-type]

    def test_captain_is_recognised_without_a_resolver(self) -> None:
        assert _oracle()._resolve_records_reader("captain") == ("captain", "")

    def test_missing_resolver_is_anonymous(self) -> None:
        assert _oracle()._resolve_records_reader("agent-alice") == ("", "")

    def test_raising_resolver_degrades_to_anonymous(self, caplog) -> None:
        def _boom(_agent_id: str) -> tuple[str, str]:
            raise RuntimeError("registry offline")

        oracle = _oracle(resolver=_boom)

        assert oracle._resolve_records_reader("agent-alice") == ("", "")
        assert "BF-679" in caplog.text

    @pytest.mark.parametrize(
        "bad", ["alice", ("alice",), ("alice", "eng", "x"), (1, "eng"), ("alice", 2)],
    )
    def test_malformed_resolver_output_degrades_to_anonymous(self, bad: Any) -> None:
        oracle = _oracle(resolver=lambda _agent_id: bad)

        assert oracle._resolve_records_reader("agent-alice") == ("", "")

    def test_attach_is_idempotent_and_accepts_none(self) -> None:
        oracle = _oracle()
        resolver = _crew_resolver()

        oracle.attach_reader_identity_resolver(resolver)
        oracle.attach_reader_identity_resolver(resolver)
        assert oracle._resolve_records_reader("agent-alice") == ("alice", "engineering")

        oracle.attach_reader_identity_resolver(None)
        assert oracle._resolve_records_reader("agent-alice") == ("", "")


# ---------------------------------------------------------------------------
# 9. Tool boundary — identity must actually leave the tool
# ---------------------------------------------------------------------------

class TestToolForwardsIdentity:
    async def test_agent_id_from_context_reaches_the_oracle(self) -> None:
        calls: list[dict[str, Any]] = []

        class _Recording:
            async def query(self, query_text: str = "", **kwargs: Any) -> list[Any]:
                calls.append({"query_text": query_text, **kwargs})
                return []

        await OracleQueryTool(oracle=_Recording()).invoke(
            {"query": "reactor"}, {"agent_id": "agent-alice"},
        )

        assert calls[0]["agent_id"] == "agent-alice"

    async def test_missing_context_forwards_the_anonymous_actor(self) -> None:
        calls: list[dict[str, Any]] = []

        class _Recording:
            async def query(self, query_text: str = "", **kwargs: Any) -> list[Any]:
                calls.append({"query_text": query_text, **kwargs})
                return []

        await OracleQueryTool(oracle=_Recording()).invoke({"query": "reactor"})

        assert calls[0]["agent_id"] == ""
