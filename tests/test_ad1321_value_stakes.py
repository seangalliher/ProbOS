"""AD-1321: first-class value band / stakes with provenance and confirmation."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from probos.cognitive.crew_orchestrator import CrewOrchestrator
from probos.cognitive.orders import agent_has_authority_over
from probos.routers import workforce as workforce_router
from probos.routers.deps import get_runtime
from probos.storage.sqlite_factory import SQLiteConnectionFactory
from probos.tools.work_item_status_tool import WorkItemStatusTool
from probos.workforce import (
    CAPTAIN_VALUE_IDENTITY,
    STAKES_LEVELS,
    VALUE_BANDS,
    WorkItem,
    WorkItemStore,
    WorkItemTemplate,
    build_value_provenance,
    default_value_provenance_for_creator,
    normalize_value_context,
    normalize_value_provenance,
    normalize_value_text,
    value_context_standing_eligible,
    with_value_confirmation,
)
from tests.test_ad1128_crew_session_ingress_dedup import (  # noqa: F401
    _Harness,
    harness,
)


def _captain(recorded_at: float = 10.0) -> dict[str, Any]:
    return build_value_provenance(
        source_kind="captain", source_id="captain",
        recorded_at=recorded_at, confirmed=True,
    )


def _agent(agent_id: str = "agent-origin") -> dict[str, Any]:
    return build_value_provenance(
        source_kind="agent", source_id=agent_id, recorded_at=10.0,
    )


async def _store(tmp_path: Path) -> WorkItemStore:
    store = WorkItemStore(
        db_path=str(tmp_path / "wf.db"), tick_interval=1_000,
        connection_factory=SQLiteConnectionFactory(),
    )
    await store.start()
    return store


# -- validators ---------------------------------------------------------


def test_normalize_value_text_accepts_vocabulary_and_none() -> None:
    assert [normalize_value_text("value_band", b) for b in VALUE_BANDS] == list(VALUE_BANDS)
    assert [normalize_value_text("stakes", s) for s in STAKES_LEVELS] == list(STAKES_LEVELS)
    assert normalize_value_text("value_band", None) is None
    assert normalize_value_text("value_band", " minor ") == "minor"


@pytest.mark.parametrize("bad", ["", "huge", "LOW", 3, ["minor"], "x" * 500])
def test_normalize_value_text_rejects_outside_vocabulary(bad: Any) -> None:
    with pytest.raises(ValueError, match="value_context"):
        normalize_value_text("value_band", bad)


def test_normalize_value_text_rejects_unknown_field() -> None:
    with pytest.raises(ValueError, match="value_context_invalid"):
        normalize_value_text("priority", "minor")


def test_provenance_requires_exact_shape() -> None:
    good = _captain()
    assert normalize_value_provenance(good) == good
    assert normalize_value_provenance(None) is None
    with pytest.raises(ValueError):
        normalize_value_provenance({**good, "extra": 1})
    with pytest.raises(ValueError):
        normalize_value_provenance({k: v for k, v in good.items() if k != "source_id"})
    with pytest.raises(ValueError):
        normalize_value_provenance({**good, "source_kind": "robot"})
    with pytest.raises(ValueError):
        normalize_value_provenance("nope")


def test_value_and_provenance_must_pair() -> None:
    with pytest.raises(ValueError):
        normalize_value_context("minor", None, None, None)
    with pytest.raises(ValueError):
        normalize_value_context(None, _captain(), None, None)
    assert normalize_value_context(None, None, None, None) == (None, None, None, None)


def test_default_provenance_is_confirmed_only_for_captain() -> None:
    assert default_value_provenance_for_creator(CAPTAIN_VALUE_IDENTITY, 1.0)[
        "confirmation_kind"
    ] == "captain"
    agent = default_value_provenance_for_creator("agent-x", 1.0)
    assert agent["confirmation_kind"] is None
    assert agent["source_kind"] == "agent" and agent["source_id"] == "agent-x"


def test_with_value_confirmation_never_rewrites_source() -> None:
    proposal = _agent()
    confirmed = with_value_confirmation(
        proposal, confirmed_by="chief", confirmation_kind="chain_of_command",
    )
    assert confirmed["source_id"] == proposal["source_id"]
    assert confirmed["recorded_at"] == proposal["recorded_at"]
    assert confirmed["confirmed_by"] == "chief"
    assert proposal["confirmation_kind"] is None


def test_standing_eligibility_is_fail_closed() -> None:
    def item(**kw: Any) -> Any:
        return SimpleNamespace(**{
            "value_band": "minor", "value_band_provenance": _captain(),
            "stakes": "low", "stakes_provenance": _captain(), **kw,
        })

    assert value_context_standing_eligible(item()) is True
    assert value_context_standing_eligible(item(stakes=None, stakes_provenance=None)) is False
    assert value_context_standing_eligible(item(value_band=None, value_band_provenance=None)) is False
    assert value_context_standing_eligible(item(stakes_provenance=_agent())) is False
    assert value_context_standing_eligible(item(value_band="bogus")) is False
    assert value_context_standing_eligible(item(value_band_provenance={"junk": 1})) is False
    assert value_context_standing_eligible(None) is False
    assert value_context_standing_eligible(object()) is False


# -- WorkItem / template model ----------------------------------------


def test_workitem_defaults_are_null_and_serialised() -> None:
    data = WorkItem(id="w1", title="t").to_dict()
    assert data["value_band"] is None and data["stakes"] is None
    assert data["value_band_provenance"] is None and data["stakes_provenance"] is None


def test_workitem_rejects_unpaired_or_invalid_values() -> None:
    with pytest.raises(ValueError):
        WorkItem(id="w1", title="t", value_band="minor")
    with pytest.raises(ValueError):
        WorkItem(id="w1", title="t", stakes="catastrophic", stakes_provenance=_captain())


def test_template_value_defaults_to_captain_confirmed() -> None:
    template = WorkItemTemplate(
        template_id="t-v", name="n", description="d", work_type="task",
        title_pattern="x", value_band="significant",
    )
    assert template.value_band_provenance["confirmation_kind"] == "captain"
    assert template.to_dict()["value_band"] == "significant"
    assert template.stakes is None


# -- store: persistence, migration, inheritance -----------------------


async def test_create_round_trips_values_with_creator_provenance(tmp_path: Path) -> None:
    store = await _store(tmp_path)
    try:
        captain = await store.create_work_item(title="a", value_band="critical", stakes="severe")
        agent = await store.create_work_item(
            title="b", created_by="agent-z", value_band="minor",
        )
        bare = await store.create_work_item(title="c")
        got = await store.get_work_item(captain.id)
        assert (got.value_band, got.stakes) == ("critical", "severe")
        assert got.value_band_provenance["confirmation_kind"] == "captain"
        got_agent = await store.get_work_item(agent.id)
        assert got_agent.value_band_provenance["source_id"] == "agent-z"
        assert got_agent.value_band_provenance["confirmation_kind"] is None
        assert got_agent.stakes is None and got_agent.stakes_provenance is None
        got_bare = await store.get_work_item(bare.id)
        assert got_bare.value_band is None and got_bare.value_band_provenance is None
    finally:
        await store.stop()


async def test_create_rejects_invalid_value(tmp_path: Path) -> None:
    store = await _store(tmp_path)
    try:
        with pytest.raises(ValueError, match="value_context"):
            await store.create_work_item(title="a", value_band="enormous")
    finally:
        await store.stop()


async def test_pre_ad1321_database_migrates_additively_and_idempotently(
    tmp_path: Path,
) -> None:
    store = await _store(tmp_path)
    legacy = await store.create_work_item(title="legacy")
    await store.stop()
    path = str(tmp_path / "wf.db")
    conn = sqlite3.connect(path)
    new = ("value_band", "value_band_provenance", "stakes", "stakes_provenance")
    keep = [r[1] for r in conn.execute("PRAGMA table_info(work_items)") if r[1] not in new]
    conn.execute(f"CREATE TABLE legacy_wi AS SELECT {', '.join(keep)} FROM work_items")
    conn.execute("DROP TABLE work_items")
    conn.execute("ALTER TABLE legacy_wi RENAME TO work_items")
    conn.commit()
    conn.close()

    for _ in range(2):
        store = await _store(tmp_path)
        try:
            item = await store.get_work_item(legacy.id)
            assert item is not None and item.title == "legacy"
            assert item.value_band is None and item.stakes_provenance is None
        finally:
            await store.stop()
    conn = sqlite3.connect(path)
    columns = [r[1] for r in conn.execute("PRAGMA table_info(work_items)")]
    conn.close()
    assert columns.count("value_band") == 1 and columns.count("stakes_provenance") == 1


async def test_template_snapshot_inherits_with_template_id(tmp_path: Path) -> None:
    store = await _store(tmp_path)
    try:
        store.template_store.register(WorkItemTemplate(
            template_id="t-inherit", name="n", description="d", work_type="task",
            title_pattern="x", value_band="significant", stakes="high",
        ))
        item = await store.create_from_template("t-inherit")
        assert (item.value_band, item.stakes) == ("significant", "high")
        assert item.value_band_provenance["inherited_template_id"] == "t-inherit"
        assert item.stakes_provenance["confirmation_kind"] == "captain"
        # A later template edit never rewrites the existing item.
        store.template_store.register(WorkItemTemplate(
            template_id="t-inherit", name="n", description="d", work_type="task",
            title_pattern="x", value_band="minor",
        ))
        again = await store.get_work_item(item.id)
        assert again.value_band == "significant"
    finally:
        await store.stop()


async def test_template_override_wins_and_records_the_creator(tmp_path: Path) -> None:
    store = await _store(tmp_path)
    try:
        store.template_store.register(WorkItemTemplate(
            template_id="t-ovr", name="n", description="d", work_type="task",
            title_pattern="x", value_band="minor", stakes="low",
        ))
        item = await store.create_from_template(
            "t-ovr", overrides={"value_band": "critical"}, created_by="agent-q",
        )
        assert item.value_band == "critical"
        assert item.value_band_provenance["source_id"] == "agent-q"
        assert item.value_band_provenance["inherited_template_id"] is None
        assert item.value_band_provenance["confirmation_kind"] is None
        assert item.stakes == "low" and item.stakes_provenance["inherited_template_id"] == "t-ovr"
        with pytest.raises(ValueError, match="value_context"):
            await store.create_from_template("t-ovr", overrides={"stakes": "bogus"})
    finally:
        await store.stop()


async def test_update_requires_provenance_and_clears_with_value(tmp_path: Path) -> None:
    store = await _store(tmp_path)
    try:
        item = await store.create_work_item(title="a", value_band="minor")
        with pytest.raises(ValueError, match="value_context_provenance_required"):
            await store.update_work_item(item.id, value_band="critical")
        with pytest.raises(ValueError, match="value_context_provenance_immutable"):
            await store.update_work_item(item.id, value_band_provenance=_captain(99.0))
        updated = await store.update_work_item(
            item.id, value_band="critical", value_band_provenance=_captain(50.0),
        )
        assert updated.value_band == "critical"
        assert updated.value_band_provenance["recorded_at"] == 50.0
        cleared = await store.update_work_item(item.id, value_band=None)
        assert cleared.value_band is None and cleared.value_band_provenance is None
        conn = sqlite3.connect(str(tmp_path / "wf.db"))
        raw = conn.execute(
            "SELECT value_band_provenance FROM work_items WHERE id=?", (item.id,),
        ).fetchone()[0]
        conn.close()
        assert raw is None  # SQL NULL, never the text "null"
    finally:
        await store.stop()


async def test_confirm_value_context_is_cas_idempotent_and_conflict_safe(
    tmp_path: Path,
) -> None:
    store = await _store(tmp_path)
    try:
        item = await store.create_work_item(
            title="a", created_by="agent-z", value_band="minor", stakes="low",
        )
        expected = {
            "value_band": item.value_band,
            "value_band_provenance": item.value_band_provenance,
            "stakes": item.stakes,
            "stakes_provenance": item.stakes_provenance,
        }
        stale = {**expected, "value_band_provenance": _agent("someone-else")}
        with pytest.raises(ValueError, match="value_context_confirmation_conflict"):
            await store.confirm_value_context(
                item.id, confirmed_by="captain", confirmation_kind="captain",
                expected_declaration=stale,
            )
        done = await store.confirm_value_context(
            item.id, confirmed_by="captain", confirmation_kind="captain",
            expected_declaration=expected,
        )
        assert done.value_band_provenance["confirmed_by"] == "captain"
        assert done.value_band_provenance["source_id"] == "agent-z"
        again = await store.confirm_value_context(
            item.id, confirmed_by="captain", confirmation_kind="captain",
        )
        assert again.value_band_provenance == done.value_band_provenance
        with pytest.raises(ValueError, match="value_context_confirmation_conflict"):
            await store.confirm_value_context(
                item.id, confirmed_by="chief", confirmation_kind="chain_of_command",
            )
        assert await store.confirm_value_context(
            "missing", confirmed_by="captain", confirmation_kind="captain",
        ) is None
        bare = await store.create_work_item(title="b")
        with pytest.raises(ValueError, match="value_context_absent"):
            await store.confirm_value_context(
                bare.id, confirmed_by="captain", confirmation_kind="captain",
            )
        with pytest.raises(ValueError, match="value_context_confirmation_invalid"):
            await store.confirm_value_context(
                item.id, confirmed_by="x", confirmation_kind="self",
            )
    finally:
        await store.stop()


async def test_confirm_cas_compares_all_four_declaration_fields(tmp_path: Path) -> None:
    store = await _store(tmp_path)
    try:
        item = await store.create_work_item(
            title="a", created_by="agent-z", value_band="minor",
        )
        exact = {
            "value_band": "minor", "value_band_provenance": item.value_band_provenance,
            "stakes": None, "stakes_provenance": None,
        }
        stakes_appeared = await store.update_work_item(
            item.id, stakes="high", stakes_provenance=_agent("agent-z"),
        )
        for stale in (
            exact,  # a null expectation must not match a later non-null field
            {**exact, "value_band": "critical"},
        ):
            with pytest.raises(ValueError, match="value_context_confirmation_conflict"):
                await store.confirm_value_context(
                    item.id, confirmed_by="captain", confirmation_kind="captain",
                    expected_declaration=stale,
                )
        incomplete = {k: v for k, v in exact.items() if k != "stakes"}
        with pytest.raises(ValueError, match="value_context_confirmation_invalid"):
            await store.confirm_value_context(
                item.id, confirmed_by="captain", confirmation_kind="captain",
                expected_declaration=incomplete,
            )
        after = await store.get_work_item(item.id)
        assert after.value_band_provenance["confirmation_kind"] is None
        assert after.stakes_provenance == stakes_appeared.stakes_provenance
        assert after.stakes_provenance["confirmation_kind"] is None
    finally:
        await store.stop()


async def test_confirm_updates_only_pending_fields_and_keeps_confirmed_ones(
    tmp_path: Path,
) -> None:
    store = await _store(tmp_path)
    try:
        item = await store.create_work_item(
            title="a", created_by="agent-z", value_band="minor", stakes="low",
        )
        captain_stakes = _captain(77.0)
        await store.update_work_item(
            item.id, stakes="high", stakes_provenance=captain_stakes,
        )
        done = await store.confirm_value_context(
            item.id, confirmed_by="chief", confirmation_kind="chain_of_command",
        )
        assert done.stakes_provenance == captain_stakes
        assert done.value_band_provenance["confirmed_by"] == "chief"
        assert done.value_band_provenance["source_id"] == "agent-z"
        again = await store.confirm_value_context(
            item.id, confirmed_by="chief", confirmation_kind="chain_of_command",
        )
        assert again.stakes_provenance == captain_stakes
    finally:
        await store.stop()


async def test_child_with_parent_snapshots_omitted_value_and_stakes(tmp_path: Path) -> None:
    store = await _store(tmp_path)
    try:
        parent = await store.create_work_item(
            title="p", created_by="agent-p", value_band="critical", stakes="severe",
        )
        child = await store.create_work_item(title="c", parent_id=parent.id)
        partial = await store.create_work_item(
            title="d", parent_id=parent.id, stakes="low", created_by="agent-q",
        )
        explicit_null = await store.create_work_item(
            title="n", parent_id=parent.id, value_band=None, stakes=None,
        )
        orphan = await store.create_work_item(title="o")
        for fetched in (child, await store.get_work_item(child.id)):
            assert (fetched.value_band, fetched.stakes) == ("critical", "severe")
            assert fetched.value_band_provenance == parent.value_band_provenance
            assert fetched.stakes_provenance == parent.stakes_provenance
        assert partial.value_band == "critical"
        assert partial.value_band_provenance == parent.value_band_provenance
        assert partial.stakes == "low"
        assert partial.stakes_provenance["source_id"] == "agent-q"
        assert explicit_null.value_band is None
        assert explicit_null.value_band_provenance is None
        assert explicit_null.stakes is None
        assert explicit_null.stakes_provenance is None
        assert orphan.value_band is None and orphan.stakes_provenance is None

        await store.update_work_item(
            parent.id, value_band="minor", value_band_provenance=_captain(5.0),
        )
        again = await store.get_work_item(child.id)
        assert again.value_band == "critical"
        assert again.value_band_provenance == parent.value_band_provenance
    finally:
        await store.stop()


# -- authority --------------------------------------------------------


def _post(post_id: str, dept: str, over: list[str]) -> Any:
    return SimpleNamespace(id=post_id, department_id=dept, authority_over=over)


class _AuthOntology:
    def __init__(self) -> None:
        self.posts = {
            "eng_op": _post("eng_op", "engineering", []),
            "eng_op2": _post("eng_op2", "engineering", []),
            "chief_eng": _post("chief_eng", "engineering", ["eng_op", "eng_op2"]),
            "sci_chief": _post("sci_chief", "science", []),
            "first_officer": _post("first_officer", "command", ["chief_eng", "sci_chief"]),
        }
        self.chains = {
            "eng_op": ["eng_op", "chief_eng", "first_officer"],
            "eng_op2": ["eng_op2", "chief_eng", "first_officer"],
            "chief_eng": ["chief_eng", "first_officer"],
        }
        self.assign = {
            "t_op": "eng_op", "t_op2": "eng_op2", "t_chief": "chief_eng",
            "t_sci": "sci_chief", "t_fo": "first_officer",
        }

    def get_crew_agent_types(self) -> set[str]:
        return set(self.assign)

    def get_assignment_for_agent(self, agent_type: str) -> Any:
        post = self.assign.get(agent_type)
        return SimpleNamespace(post_id=post) if post else None

    def get_post(self, post_id: str) -> Any:
        return self.posts.get(post_id)

    def get_chain_of_command(self, post_id: str) -> list[Any]:
        return [self.posts[p] for p in self.chains.get(post_id, [post_id])]


class _Registry:
    def __init__(self) -> None:
        self.agents = {
            "op-1": "t_op", "op-2": "t_op2", "chief-1": "t_chief",
            "sci-1": "t_sci", "fo-1": "t_fo",
        }

    def all(self) -> list[Any]:
        return [SimpleNamespace(id=i, agent_type=t) for i, t in self.agents.items()]


@pytest.mark.parametrize(
    ("superior", "subordinate", "expected"),
    [
        ("chief-1", "op-1", True),
        ("fo-1", "op-1", True),
        ("op-1", "op-1", False),
        ("op-2", "op-1", False),
        ("op-1", "chief-1", False),
        ("sci-1", "op-1", False),
        ("ghost", "op-1", False),
        ("chief-1", "ghost", False),
    ],
)
def test_agent_has_authority_over_follows_the_chain(
    superior: str, subordinate: str, expected: bool,
) -> None:
    assert agent_has_authority_over(
        _AuthOntology(), _Registry(), superior, subordinate,
    ) is expected


def test_agent_has_authority_over_fails_closed_without_wiring() -> None:
    assert agent_has_authority_over(None, _Registry(), "a", "b") is False
    assert agent_has_authority_over(_AuthOntology(), None, "a", "b") is False
    assert agent_has_authority_over(_AuthOntology(), _Registry(), None, "b") is False  # type: ignore[arg-type]


# -- CrewSession ingress + confirmation (real service) --------------


async def _agent_session(harness: _Harness, **kw: Any) -> Any:
    harness.service._ontology = _AuthOntology()  # noqa: SLF001 - test wiring
    harness.service._registry = _FullRegistry(harness.service._registry)  # noqa: SLF001
    result = await harness.service.open_or_resume(
        principal=harness.service.agent_principal("op-1"),
        goal="Investigate the plasma leak",
        success_criteria=["Leak located"],
        expected_deliverable="A report",
        facilitator_id="op-1",
        **kw,
    )
    return result, await harness.work.get_work_item(result.parent_id)


class _FullRegistry:
    """Registry exposing the authority agents alongside the harness agents."""

    def __init__(self, base: Any) -> None:
        self._base = base
        self._extra = {
            aid: SimpleNamespace(id=aid, agent_type=t, pool="ops")
            for aid, t in _Registry().agents.items()
        }

    def get(self, agent_id: str) -> Any:
        return self._extra.get(agent_id) or self._base.get(agent_id)

    def all(self) -> list[Any]:
        return list(self._extra.values()) + list(self._base.all())


async def test_agent_ingress_records_unconfirmed_agent_provenance(harness: _Harness) -> None:
    _, parent = await _agent_session(harness, value_band="significant", stakes="high")
    assert (parent.value_band, parent.stakes) == ("significant", "high")
    for prov in (parent.value_band_provenance, parent.stakes_provenance):
        assert prov["source_kind"] == "agent" and prov["source_id"] == "op-1"
        assert prov["confirmation_kind"] is None


async def test_captain_ingress_is_born_confirmed_and_children_inherit(
    harness: _Harness,
) -> None:
    result = await harness.service.open_or_resume(
        principal=harness.service.captain_principal(),
        goal="Rebuild the relay", success_criteria=["Relay online"],
        expected_deliverable="Working relay", facilitator_id="facilitator-1",
        value_band="critical", stakes="severe",
    )
    parent = await harness.work.get_work_item(result.parent_id)
    assert parent.value_band_provenance["confirmation_kind"] == "captain"
    children = await harness.work.list_work_items(parent_id=parent.id)
    assert children, "decomposition should have installed at least one child"
    for child in children:
        assert (child.value_band, child.stakes) == ("critical", "severe")
        assert child.value_band_provenance == parent.value_band_provenance
        assert child.stakes_provenance == parent.stakes_provenance


async def test_ingress_without_values_leaves_them_null(harness: _Harness) -> None:
    _, parent = await _agent_session(harness)
    assert parent.value_band is None and parent.stakes_provenance is None


async def test_ingress_rejects_out_of_vocabulary_values(harness: _Harness) -> None:
    with pytest.raises(ValueError, match="crew_session_value_context_invalid"):
        await harness.service.open_or_resume(
            principal=harness.service.captain_principal(),
            goal="g", success_criteria=["c"], expected_deliverable="d",
            facilitator_id="facilitator-1", value_band="astronomical",
        )


async def test_duplicate_resume_conflicting_value_is_refused_without_overwrite(
    harness: _Harness,
) -> None:
    first, parent = await _agent_session(harness, value_band="minor")
    with pytest.raises(ValueError, match="crew_session_value_context_conflict"):
        await harness.service.open_or_resume(
            principal=harness.service.agent_principal("op-1"),
            goal="Investigate the plasma leak", success_criteria=["Leak located"],
            expected_deliverable="A report", facilitator_id="op-1",
            value_band="critical",
        )
    resumed = await harness.service.open_or_resume(
        principal=harness.service.agent_principal("op-1"),
        goal="Investigate the plasma leak", success_criteria=["Leak located"],
        expected_deliverable="A report", facilitator_id="op-1", value_band="minor",
    )
    assert resumed.parent_id == first.parent_id
    unchanged = await harness.work.get_work_item(parent.id)
    assert unchanged.value_band == "minor"
    assert unchanged.value_band_provenance == parent.value_band_provenance


async def test_confirmation_authority_matrix(harness: _Harness) -> None:
    _, parent = await _agent_session(harness, value_band="significant", stakes="high")
    service = harness.service
    for forbidden in ("op-1", "op-2", "sci-1"):
        with pytest.raises(PermissionError, match="value_context_confirmation_unauthorized"):
            await service.confirm_value_context(service.agent_principal(forbidden), parent.id)
    with pytest.raises(ValueError, match="crew_session_principal_invalid"):
        await service.confirm_value_context(
            SimpleNamespace(origin="captain", originator_id="captain"), parent.id,  # type: ignore[arg-type]
        )
    with pytest.raises(LookupError):
        await service.confirm_value_context(service.captain_principal(), "nope")
    assert value_context_standing_eligible(await harness.work.get_work_item(parent.id)) is False

    confirmed = await service.confirm_value_context(service.agent_principal("chief-1"), parent.id)
    for prov in (confirmed.value_band_provenance, confirmed.stakes_provenance):
        assert prov["confirmed_by"] == "chief-1"
        assert prov["confirmation_kind"] == "chain_of_command"
        assert prov["source_id"] == "op-1"
    assert value_context_standing_eligible(confirmed) is True
    # Idempotent for the same confirmer; the Captain cannot silently overwrite it.
    again = await service.confirm_value_context(service.agent_principal("chief-1"), parent.id)
    assert again.value_band_provenance == confirmed.value_band_provenance
    with pytest.raises(ValueError, match="value_context_confirmation_conflict"):
        await service.confirm_value_context(service.captain_principal(), parent.id)


async def test_captain_confirms_an_agent_proposal(harness: _Harness) -> None:
    _, parent = await _agent_session(harness, value_band="minor")
    confirmed = await harness.service.confirm_value_context(
        harness.service.captain_principal(), parent.id,
    )
    assert confirmed.value_band_provenance["confirmation_kind"] == "captain"
    assert confirmed.value_band_provenance["source_id"] == "op-1"


async def test_orchestrator_forwards_values_only_when_given() -> None:
    class _Spy:
        def __init__(self) -> None:
            self.calls: list[dict[str, Any]] = []

        def agent_principal(self, agent_id: str) -> str:
            return agent_id

        async def open_or_resume(self, **kwargs: Any) -> Any:
            self.calls.append(kwargs)
            return SimpleNamespace(parent_id="p-1")

    spy = _Spy()
    orchestrator = CrewOrchestrator.__new__(CrewOrchestrator)
    orchestrator._crew_session_service = spy  # noqa: SLF001
    assert await orchestrator.originate_crew_task(origin_agent_id="a", goal="g") == "p-1"
    assert await orchestrator.originate_crew_task(
        origin_agent_id="a", goal="g", value_band="minor", stakes="low",
    ) == "p-1"
    assert "value_band" not in spy.calls[0] and "stakes" not in spy.calls[0]
    assert spy.calls[1]["value_band"] == "minor" and spy.calls[1]["stakes"] == "low"


# -- REST ----------------------------------------------------------------


async def _client(runtime: Any) -> httpx.AsyncClient:
    app = FastAPI()
    app.include_router(workforce_router.router)
    app.dependency_overrides[get_runtime] = lambda: runtime
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")


async def test_api_create_get_patch_confirm_happy_path(tmp_path: Path, harness: _Harness) -> None:
    store = harness.work
    try:
        runtime = SimpleNamespace(work_item_store=store, crew_session_service=harness.service)
        async with await _client(runtime) as client:
            created = await client.post(
                "/api/work-items", json={"title": "x", "value_band": "moderate", "stakes": "low"},
            )
            assert created.status_code == 200
            body = created.json()["work_item"]
            assert body["value_band"] == "moderate"
            assert body["value_band_provenance"]["confirmation_kind"] == "captain"
            item_id = body["id"]

            patched = await client.patch(f"/api/work-items/{item_id}", json={"stakes": "severe"})
            assert patched.status_code == 200
            assert patched.json()["work_item"]["stakes"] == "severe"
            assert patched.json()["work_item"]["stakes_provenance"]["source_id"] == "captain"
            same = await client.patch(f"/api/work-items/{item_id}", json={"stakes": "severe"})
            assert same.status_code == 200

            agent_item = await store.create_work_item(
                title="y", created_by="agent-z", value_band="minor",
            )
            confirmed = await client.post(f"/api/work-items/{agent_item.id}/value-context/confirm")
            assert confirmed.status_code == 200
            prov = confirmed.json()["work_item"]["value_band_provenance"]
            assert prov["confirmed_by"] == "captain" and prov["source_id"] == "agent-z"
            fetched = await client.get(f"/api/work-items/{agent_item.id}")
            assert fetched.json()["work_item"]["value_band_provenance"] == prov
    finally:
        pass


async def test_api_rejects_forged_provenance_and_bad_values(tmp_path: Path, harness: _Harness) -> None:
    store = harness.work
    try:
        runtime = SimpleNamespace(work_item_store=store, crew_session_service=harness.service)
        async with await _client(runtime) as client:
            forged = {"title": "x", "value_band": "minor", "value_band_provenance": _captain()}
            assert (await client.post("/api/work-items", json=forged)).status_code == 422
            bad = await client.post("/api/work-items", json={"title": "x", "stakes": "huge"})
            assert bad.status_code == 422
            item = await store.create_work_item(title="z", value_band="minor")
            assert (await client.patch(
                f"/api/work-items/{item.id}", json={"stakes_provenance": _captain()},
            )).status_code == 422
            assert (await client.patch(
                f"/api/work-items/{item.id}", json={"value_band": "nope"},
            )).status_code == 422
            assert (await client.post(
                "/api/work-items/from-template/bug_report",
                json={"overrides": {"stakes_provenance": _captain()}},
            )).status_code == 422
            assert (await client.patch(
                "/api/work-items/missing", json={"stakes": "low"},
            )).status_code == 404
            assert (await client.post(
                "/api/work-items/missing/value-context/confirm",
            )).status_code == 404
            bare = await store.create_work_item(title="bare")
            assert (await client.post(
                f"/api/work-items/{bare.id}/value-context/confirm",
            )).status_code == 422
            agent_item = await store.create_work_item(
                title="a", created_by="agent-z", value_band="minor",
            )
            assert (await client.post(
                f"/api/work-items/{agent_item.id}/value-context/confirm",
            )).status_code == 200
    finally:
        pass


async def test_api_confirm_conflict_is_409(tmp_path: Path, harness: _Harness) -> None:
    store = harness.work
    try:
        runtime = SimpleNamespace(work_item_store=store, crew_session_service=harness.service)
        item = await store.create_work_item(title="a", created_by="agent-z", value_band="minor")
        await store.confirm_value_context(
            item.id, confirmed_by="chief-1", confirmation_kind="chain_of_command",
        )
        async with await _client(runtime) as client:
            response = await client.post(f"/api/work-items/{item.id}/value-context/confirm")
        assert response.status_code == 409
        assert response.json()["detail"] == "value_context_confirmation_conflict"
    finally:
        pass


async def test_confirmation_authority_is_judged_against_pending_sources(
    harness: _Harness,
) -> None:
    await _agent_session(harness)  # wires the authority ontology and registry
    store = harness.work
    item = await store.create_work_item(
        title="mixed", created_by="op-1", value_band="minor", stakes="low",
    )
    # The band is already confirmed (by a superior of a different proposer);
    # chief-1 has no authority over that proposer, only over the pending stakes.
    settled = with_value_confirmation(
        _agent("sci-1"), confirmed_by="fo-1", confirmation_kind="chain_of_command",
    )
    await store.update_work_item(
        item.id, value_band="critical", value_band_provenance=settled,
    )
    service = harness.service
    with pytest.raises(PermissionError, match="value_context_confirmation_unauthorized"):
        await service.confirm_value_context(service.agent_principal("op-2"), item.id)
    confirmed = await service.confirm_value_context(service.agent_principal("chief-1"), item.id)
    assert confirmed.value_band_provenance == settled
    assert confirmed.stakes_provenance["confirmed_by"] == "chief-1"
    assert confirmed.stakes_provenance["source_id"] == "op-1"


async def test_api_child_explicit_null_does_not_inherit(
    harness: _Harness,
) -> None:
    store = harness.work
    runtime = SimpleNamespace(work_item_store=store, crew_session_service=harness.service)
    parent = await store.create_work_item(
        title="parent", value_band="critical", stakes="severe",
    )
    async with await _client(runtime) as client:
        response = await client.post(
            "/api/work-items",
            json={
                "title": "explicit unset",
                "parent_id": parent.id,
                "value_band": None,
                "stakes": None,
            },
        )
    assert response.status_code == 200
    child = response.json()["work_item"]
    assert child["value_band"] is None
    assert child["value_band_provenance"] is None
    assert child["stakes"] is None
    assert child["stakes_provenance"] is None


async def test_api_confirm_rejects_nonempty_body_without_mutation(
    tmp_path: Path, harness: _Harness,
) -> None:
    store = harness.work
    runtime = SimpleNamespace(work_item_store=store, crew_session_service=harness.service)
    item = await store.create_work_item(title="y", created_by="agent-z", value_band="minor")
    before = item.to_dict()
    async with await _client(runtime) as client:
        for payload in (
            b"{not json", b'{"confirmed_by": "chief"}', b"[]", b"null", b"0",
            b" ", b"\n\t", b"\r\n",
        ):
            response = await client.post(
                f"/api/work-items/{item.id}/value-context/confirm",
                content=payload, headers={"content-type": "application/json"},
            )
            assert response.status_code == 422, payload
            fresh = await store.get_work_item(item.id)
            assert fresh.to_dict() == before
        empty = await client.post(
            f"/api/work-items/{item.id}/value-context/confirm",
            content=b"", headers={"content-type": "application/json"},
        )
        assert empty.status_code == 200


async def test_api_patch_normalizes_band_before_comparing(
    tmp_path: Path, harness: _Harness,
) -> None:
    store = harness.work
    runtime = SimpleNamespace(work_item_store=store, crew_session_service=harness.service)
    item = await store.create_work_item(
        title="y", created_by="agent-z", value_band="minor", stakes="low",
    )
    async with await _client(runtime) as client:
        same = await client.patch(
            f"/api/work-items/{item.id}", json={"value_band": " minor ", "stakes": "low "},
        )
        assert same.status_code == 200
        body = same.json()["work_item"]
        assert body["value_band"] == "minor"
        assert body["value_band_provenance"] == item.value_band_provenance
        assert body["stakes_provenance"] == item.stakes_provenance
        changed = await client.patch(
            f"/api/work-items/{item.id}", json={"value_band": " critical "},
        )
        assert changed.status_code == 200
        band = changed.json()["work_item"]
        assert band["value_band"] == "critical"
        assert band["value_band_provenance"]["source_id"] == "captain"
        assert band["value_band_provenance"]["confirmation_kind"] == "captain"
        assert band["stakes_provenance"] == item.stakes_provenance


async def test_api_confirm_503_without_services(tmp_path: Path) -> None:
    runtime = SimpleNamespace(work_item_store=None, crew_session_service=None)
    async with await _client(runtime) as client:
        assert (await client.post("/api/work-items/x/value-context/confirm")).status_code == 503


# -- status tool -------------------------------------------------------


async def test_status_tool_reports_values_with_explicit_nulls(tmp_path: Path) -> None:
    store = await _store(tmp_path)
    try:
        agent = "agent-owner"
        with_values = await store.create_work_item(
            title="v", created_by=agent, assigned_to=agent,
            value_band="minor", stakes="low",
        )
        bare = await store.create_work_item(title="b", created_by=agent, assigned_to=agent)
        tool = WorkItemStatusTool(runtime=SimpleNamespace(work_item_store=store))
        out = (await tool.invoke({"work_item_id": with_values.id}, {"agent_id": agent})).output
        assert out["value_band"] == "minor" and out["stakes"] == "low"
        assert out["value_band_provenance"]["source_id"] == agent
        assert out["value_band_provenance"]["confirmation_kind"] is None
        plain = (await tool.invoke({"work_item_id": bare.id}, {"agent_id": agent})).output
        assert plain["value_band"] is None and plain["stakes_provenance"] is None
        assert "value_band_provenance" in plain
    finally:
        await store.stop()

# -- end to end: template -> store -> restart -> API -> status tool ----


async def test_template_value_survives_restart_and_is_served(tmp_path: Path, harness: _Harness) -> None:
    store = await _store(tmp_path)
    store.template_store.register(WorkItemTemplate(
        template_id="t-e2e", name="n", description="d", work_type="task",
        title_pattern="x", value_band="significant", stakes="moderate",
    ))
    item = await store.create_from_template("t-e2e", created_by="captain")
    await store.stop()

    store = await _store(tmp_path)
    try:
        runtime = SimpleNamespace(work_item_store=store, crew_session_service=harness.service)
        async with await _client(runtime) as client:
            served = (await client.get(f"/api/work-items/{item.id}")).json()["work_item"]
        assert served["value_band"] == "significant"
        assert served["stakes_provenance"]["inherited_template_id"] == "t-e2e"
        assert value_context_standing_eligible(await store.get_work_item(item.id)) is True
    finally:
        await store.stop()
